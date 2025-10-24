import os
import smtplib
import requests
import feedparser
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

# -------------------------
# 환경설정
# -------------------------
TIMEZONE      = os.getenv("TIMEZONE", "Asia/Seoul")
DAYS_WINDOW   = int(os.getenv("DAYS_WINDOW", "14"))     # 유튜브 최근 N일 (일간 섹션)
MIN_VIEWS     = int(os.getenv("MIN_VIEWS", "1000000"))  # 유튜브 최소 조회수 (일간 섹션)
NEWS_DAYS     = int(os.getenv("NEWS_DAYS", "10"))       # 뉴스 최근 N일 (웹/방송 섹션)

# 주간 섹션(월요일)
WEEKLY_DAYS_WINDOW = 30            # 최근 30일
WEEKLY_MIN_VIEWS   = 100_000       # 10만 이상
WEEKLY_MAX_TOPICS  = 5             # 최대 5개 주제
WEEKLY_TOP_VIDEOS  = 5             # Top 5 영상

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
NEWSAPI_KEY     = os.getenv("NEWSAPI_KEY")   # 선택 (없으면 RSS 사용)

SMTP_HOST       = os.getenv("SMTP_HOST")
SMTP_PORT       = os.getenv("SMTP_PORT")
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASS       = os.getenv("SMTP_PASS")
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")

REPORT_PATH = "data/outputs/report.md"
LOG_DIR     = Path("data/logs")

# -------------------------
# 공통 유틸
# -------------------------
def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))  # KST 고정

def ensure_dirs():
    Path(REPORT_PATH).parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

def log(msg: str):
    ensure_dirs()
    ts = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    print(line, end="")
    log_file = LOG_DIR / f"run-{now_kst().strftime('%Y%m%d')}.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line)

def send_email_markdown(markdown_body: str, subject: str):
    missing = [k for k,v in {
        "SMTP_HOST": SMTP_HOST, "SMTP_PORT": SMTP_PORT,
        "SMTP_USER": SMTP_USER, "SMTP_PASS": SMTP_PASS,
        "REPORT_EMAIL_TO": REPORT_EMAIL_TO
    }.items() if not v]
    if missing:
        raise EnvironmentError(f"누락된 환경변수: {', '.join(missing)}")

    msg = MIMEText(markdown_body, _charset="utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"]    = SMTP_USER
    msg["To"]      = REPORT_EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, int(SMTP_PORT)) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [REPORT_EMAIL_TO], msg.as_string())

def parse_int(x):
    try: return int(x)
    except: return 0

def within_days_utc(iso_s: str, days: int) -> bool:
    try:
        dt = datetime.fromisoformat(iso_s.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt) <= timedelta(days=days)
    except:
        return False

# -------------------------
# 유튜브 트렌딩 (일간용)
# -------------------------
def fetch_youtube_trending_kr(max_results=50):
    log("유튜브 트렌딩 조회 시작")
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": "KR",
        "maxResults": max_results,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    log(f"유튜브 트렌딩 결과 개수: {len(items)}")
    return items

# 시니어 3개 주제 라벨
TOPIC_RULES = {
    "시니어 건강": ["health","건강","혈당","당뇨","콜레스테롤","피부","노화","헬스","운동","한방","한의","관절","근육"],
    "시니어 북한": ["북한","평양","김정","탈북","안보","장성택","핵","미사일","제재","북중","북러"],
    "시니어 인생스토리": ["사연","썰","드라마","가족","며느리","시어머니","반전","감동","고부","사기","유산"],
}

def label_topic(title: str, desc: str) -> str:
    text = (title or "") + " " + (desc or "")
    text_lower = text.lower()
    for topic, kws in TOPIC_RULES.items():
        for kw in kws:
            if kw.lower() in text_lower:
                return topic
    return "기타"

def pick_youtube_recos(items):
    filtered = []
    for it in items:
        sn = it.get("snippet", {})
        st = it.get("statistics", {})
        views = parse_int(st.get("viewCount"))
        if views < MIN_VIEWS:
            continue
        if not within_days_utc(sn.get("publishedAt",""), DAYS_WINDOW):
            continue
        topic = label_topic(sn.get("title",""), sn.get("description",""))
        filtered.append({
            "id": it.get("id"),
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "views": views,
            "topic": topic,
        })
    by_topic = {}
    for v in sorted(filtered, key=lambda x: x["views"], reverse=True):
        if v["topic"] not in by_topic:
            by_topic[v["topic"]] = v

    priority = ["시니어 건강", "시니어 북한", "시니어 인생스토리"]
    top3 = [by_topic[p] for p in priority if p in by_topic][:3]
    if len(top3) < 3:
        for t, v in by_topic.items():
            if len(top3) >= 3: break
            if v not in top3: top3.append(v)

    today = next((v for v in top3 if v["topic"] == "시니어 건강"), None)
    if not today and top3: today = max(top3, key=lambda x: x["views"])

    log(f"유튜브 추천 선정: {len(top3)}개 / 오늘추천: {today['title'] if today else '없음'}")
    return top3, today

# -------------------------
# 뉴스(웹/방송) 섹션 (일간용)
# -------------------------
def newsapi_search(query: str, from_days: int):
    url = "https://newsapi.org/v2/everything"
    params = {
        "apiKey": NEWSAPI_KEY,
        "q": query,
        "language": "ko",
        "sortBy": "popularity",
        "pageSize": 50,
        "from": (datetime.utcnow() - timedelta(days=from_days)).date().isoformat(),
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    arts = r.json().get("articles", [])
    results = []
    for a in arts:
        results.append({
            "title": a.get("title"),
            "url": a.get("url"),
            "source": (a.get("source") or {}).get("name"),
            "publishedAt": a.get("publishedAt"),
            "score": 1.0,
        })
    return results

def google_news_rss_search(query: str, days: int):
    url = f"https://news.google.com/rss/search?q={quote(query)}+when:{days}d&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    results = []
    for e in feed.entries[:100]:
        title = e.get("title")
        link  = e.get("link")
        source= (e.get("source") or {}).get("title") or (e.get("author") or "")
        pub   = e.get("published_parsed")
        if pub:
            dt = datetime(*pub[:6], tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - dt).days
            recency = max(0.0, 1.0 - (age_days / (days+0.1)))
        else:
            recency = 0.5
        results.append({
            "title": title, "url": link, "source": source, "score": recency
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def fetch_news_topics():
    log("뉴스 트렌드 수집 시작")
    topics = {
        "시니어 건강": "건강 OR 혈당 OR 당뇨 OR 콜레스테롤 OR 피부 OR 노화 OR 한방 OR 운동",
        "시니어 북한": "북한 OR 평양 OR 김정은 OR 탈북 OR 제재 OR 미사일",
    }
    out = {}
    for ch, q in topics.items():
        if NEWSAPI_KEY:
            items = newsapi_search(q, NEWS_DAYS)
        else:
            items = google_news_rss_search(q, NEWS_DAYS)
        seen = set()
        uniq = []
        for it in items:
            t = (it["title"] or "").strip()
            if not t or t in seen: continue
            seen.add(t)
            uniq.append(it)
        out[ch] = uniq[:3]
        log(f"뉴스 '{ch}' 추출: {len(out[ch])}개")
    return out

# -------------------------
# 주간 섹션 (월요일): 시니어 타깃 신규 유망 주제 & Top 5 영상
# -------------------------
# 1) 최근 30일, 시니어 관련 키워드로 검색(조회수순)
SENIOR_QUERY = "시니어 OR 노년 OR 어르신 OR 50대 OR 60대 OR 중장년"

def youtube_search_recent_by_views(query: str, days: int, max_results=50):
    """search.list 로 최근 N일 내 영상을 조회수순으로 검색, 그 후 videos.list로 상세 조회."""
    log(f"유튜브 검색 시작 (query='{query}', {days}일)")
    url = "https://www.googleapis.com/youtube/v3/search"
    published_after = (datetime.utcnow() - timedelta(days=days)).replace(tzinfo=timezone.utc).isoformat()
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "publishedAfter": published_after,
        "maxResults": max_results,
        "relevanceLanguage": "ko",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
    if not ids:
        return []

    # videos.list 로 통계 가져오기
    details = youtube_videos_details(ids)
    # snippet 합치기
    by_id = {d["id"]: d for d in details}
    merged = []
    for it in items:
        vid = it["id"]["videoId"]
        sn  = it.get("snippet", {})
        d   = by_id.get(vid)
        if not d: continue
        merged.append({
            "id": vid,
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "views": parse_int((d.get("statistics") or {}).get("viewCount")),
            "description": sn.get("description",""),
        })
    # 필터링: 최근 days(보장) + 조회수 하한
    merged = [m for m in merged if m["views"] >= WEEKLY_MIN_VIEWS]
    log(f"유튜브 검색 결과(필터 후): {len(merged)}개")
    return merged

def youtube_videos_details(video_ids):
    """videos.list로 snippet,statistics 모두 조회"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet,statistics",
        "id": ",".join(video_ids[:50])  # 50개 제한
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("items", [])

# 2) 주제 클러스터링(라이트 버전): 간단 키워드 그룹
#    - 기존 3개(건강/북한/인생사연) 외에 자주 보이는 키워드로 주제명 부여
NEW_TOPIC_RULES = {
    "재테크/연금/퇴직": ["연금","퇴직","노후","재테크","배당","주식","ETF","연금저축","퇴직연금"],
    "부동산/임대": ["부동산","아파트","전세","월세","임대","등기","청약"],
    "의학정보/병원": ["치매","골다공증","허리","무릎","척추","고혈압","고지혈","관상동맥","검진","병원","의사"],
    "요리/집밥/레시피": ["반찬","국","찌개","김치","집밥","요리","레시피","전통","된장","간장","건강식"],
    "취미/여가/여행": ["등산","낚시","여행","캠핑","트레킹","풍경","꽃","정원","텃밭","원예"],
    "노래/트로트/향수": ["트로트","7080","가요","명곡","노래방","콘서트","추억","레전드"],
    "법/상속/사회복지": ["상속","유언","증여","의료비","장기요양","요양","연금공단","국민연금","복지"],
}

BASE_3 = {"시니어 건강", "시니어 북한", "시니어 인생스토리"}

def label_new_topic(title: str, desc: str) -> str | None:
    text = (title or "") + " " + (desc or "")
    low = text.lower()
    # 기존 3개는 제외
    base = label_topic(title, desc)
    if base in BASE_3:
        return None
    for t, kws in NEW_TOPIC_RULES.items():
        for kw in kws:
            if kw.lower() in low:
                return t
    # 못 찾으면 None (기타는 주간 추천에서 제외)
    return None

def build_weekly_section():
    """월요일에만 사용하는 주간 리포트 섹션 문자열 반환 (없으면 빈 문자열)"""
    # 시니어 타깃 검색
    videos = youtube_search_recent_by_views(SENIOR_QUERY, WEEKLY_DAYS_WINDOW, max_results=50)
    if not videos:
        return "## C) 주간 리서치 (시니어 타깃)\n- 최근 30일 자료 부족으로 추천 불가\n\n"

    # 신규 유망 주제 탐색
    topic_bucket = {}
    for v in videos:
        new_t = label_new_topic(v["title"], v.get("description",""))
        if not new_t:
            continue
        topic_bucket.setdefault(new_t, []).append(v)

    # 각 주제 내에서 조회수 상위 1개 대표 선정
    topic_recos = []
    for t, lst in topic_bucket.items():
        best = max(lst, key=lambda x: x["views"])
        topic_recos.append((t, best))
    # 조회수 기준으로 정렬 후 최대 N개
    topic_recos.sort(key=lambda tb: tb[1]["views"], reverse=True)
    topic_recos = topic_recos[:WEEKLY_MAX_TOPICS]

    # Top 5 영상(전체) 목록
    top5_all = sorted(videos, key=lambda x: x["views"], reverse=True)[:WEEKLY_TOP_VIDEOS]

    lines = [
        "## C) 주간 리서치 (시니어 타깃)",
        f"- 기준: 최근 {WEEKLY_DAYS_WINDOW}일 · 조회수 ≥ {WEEKLY_MIN_VIEWS:,} · 검색쿼리: {SENIOR_QUERY}",
        "",
        "### 1) 신규 유망 주제 (기존 3개 제외)",
    ]
    if topic_recos:
        for i, (t, v) in enumerate(topic_recos, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            lines += [
                f"{i}. **{t}**",
                f"   - 예시: [{v['title']}]({url}) · 조회수 {v['views']:,} · 채널 {v['channel']}",
                ""
            ]
    else:
        lines.append("- (이번 주 신규 유망 주제를 찾지 못했습니다)")
        lines.append("")

    lines += [
        "### 2) Top 5 영상 (최근 30일 · 조회수)",
    ]
    if top5_all:
        for i, v in enumerate(top5_all, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            lines.append(f"{i}. [{v['title']}]({url}) · 조회수 {v['views']:,} · 채널 {v['channel']}")
        lines.append("")
    else:
        lines.append("- (해당 조건의 상위 영상 없음)")
        lines.append("")

    return "\n".join(lines)

# -------------------------
# 리포트 작성 (일간 + 월요일 주간 포함)
# -------------------------
def build_report_md(youtube_top3, youtube_today, news_map, include_weekly=False):
    kst_now = now_kst().strftime("%Y-%m-%d %H:%M (KST)")
    lines = [
        f"# Daily Auto Story — {kst_now}",
        "",
        "아래는 매일 오전 8시에 자동 발송되는 요약 리포트입니다.",
        "",
        "## A) 유튜브 트렌드 (최근 {d}일 · 조회수 ≥ {v:,})".format(d=DAYS_WINDOW, v=MIN_VIEWS),
    ]
    if youtube_top3:
        for i, v in enumerate(youtube_top3, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            when = v["publishedAt"].replace("T"," ").replace("Z"," UTC")
            lines += [
                f"{i}. **[{v['title']}]({url})**",
                f"   - 채널: {v['channel']} · 주제: {v['topic']} · 조회수: {v['views']:,} · 업로드: {when}",
                ""
            ]
    else:
        lines.append("- (조건에 맞는 항목 없음)")
        lines.append("")

    if youtube_today:
        reason = []
        if youtube_today["topic"] == "시니어 건강":
            reason.append("채널 포트폴리오와 시너지가 큼(건강/한방/시니어 타깃)")
        if youtube_today["views"] >= 2_000_000:
            reason.append("조회수가 매우 높아 파생 트래픽 기대")
        if not reason:
            reason.append("최근 트렌드와 주제 적합성")
        lines += [
            "### 오늘 제작 추천 (1개)",
            f"- **주제:** “{youtube_today['title']}” → 시니어 친화 정보/스토리텔링으로 로컬라이징",
            f"- **이유:** {(' · '.join(reason))}",
            f"- **참고 원본:** https://www.youtube.com/watch?v={youtube_today['id']}",
            ""
        ]

    # ---- 뉴스/방송 섹션 ----
    source_note = "데이터 출처: Google News RSS (NEWSAPI 미사용)"
    if os.getenv("NEWSAPI_KEY"):
        source_note = "데이터 출처: NewsAPI(인기순)"
    lines += [
        "## B) 웹/방송 트렌드 (최근 {d}일)".format(d=NEWS_DAYS),
        source_note,
        "다음은 **뉴스·방송·포털 기사 기반**으로 시니어 타깃에 적합한 주제입니다.",
        ""
    ]
    for ch in ["시니어 건강", "시니어 북한"]:
        lines.append(f"### {ch} 추천 3개")
        items = news_map.get(ch, [])
        if not items:
            lines.append("- (결과 없음)")
            lines.append("")
            continue
        for i, it in enumerate(items, 1):
            src = f" · 출처: {it['source']}" if it.get("source") else ""
            lines.append(f"{i}. **[{it['title']}]({it['url']})**{src}")
        lines.append("")

    # ---- 월요일 주간 섹션 ----
    if include_weekly:
        lines.append(build_weekly_section())

    return "\n".join(lines)

# -------------------------
# 메인
# -------------------------
def main():
    ensure_dirs()
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY 없음 (Secrets에 추가 필요)")

    # 1) 유튜브 (일간)
    yt_items = fetch_youtube_trending_kr()
    yt_top3, yt_today = pick_youtube_recos(yt_items)

    # 2) 뉴스/방송 (일간)
    news_map = fetch_news_topics()

    # 3) 월요일 여부(KST) 판단 → 주간 섹션 포함
    weekday = now_kst().weekday()  # Monday=0
    include_weekly = (weekday == 0)

    # 4) 리포트 생성/저장/메일발송
    md = build_report_md(yt_top3, yt_today, news_map, include_weekly=include_weekly)
    Path(REPORT_PATH).write_text(md, encoding="utf-8")
    log(f"리포트 저장: {REPORT_PATH}")

    subject = "✅ Daily Auto Story: 유튜브 100만+ 3개 & 오늘추천 + 웹/방송 트렌드"
    if include_weekly:
        subject = "✅ (월요일) 주간 포함: 시니어 신규 유망 주제 + Top5 영상"

    send_email_markdown(md, subject)
    log("메일 발송 완료")

if __name__ == "__main__":
    main()

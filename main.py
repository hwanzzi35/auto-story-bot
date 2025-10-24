import os
import smtplib
import requests
import feedparser
import re
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

# -------------------------
# 환경설정
# -------------------------
TIMEZONE      = os.getenv("TIMEZONE", "Asia/Seoul")
DAYS_WINDOW   = int(os.getenv("DAYS_WINDOW", "14"))    # (기존) 트렌딩 섹션 참조
MIN_VIEWS     = int(os.getenv("MIN_VIEWS", "1000000")) # (기존) 트렌딩 섹션 필터
NEWS_DAYS     = int(os.getenv("NEWS_DAYS", "10"))      # 뉴스 최근 N일
YT_TOP_DAYS   = int(os.getenv("YT_TOP_DAYS", "7"))     # ★ 신규: 주제별 Top5 기간(기본 7일)

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
    return datetime.now(timezone(timedelta(hours=9)))

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
# 유튜브 API helpers (공용)
# -------------------------
def youtube_videos_details(video_ids):
    """videos.list로 snippet,statistics 조회"""
    if not video_ids: return []
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet,statistics",
        "id": ",".join(video_ids[:50])
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("items", [])

def youtube_search_recent_by_views(query: str, days: int, max_results=50):
    """
    최근 N일 내 검색어로 검색 → 조회수순 상위 영상 상세조회 → 리스트 반환
    """
    log(f"[YT] search recent by views: '{query}', {days}일")
    published_after = (datetime.utcnow() - timedelta(days=days)).replace(tzinfo=timezone.utc).isoformat()
    url = "https://www.googleapis.com/youtube/v3/search"
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
    if not ids: return []

    details = youtube_videos_details(ids)
    dmap = {d["id"]: d for d in details}

    merged = []
    for it in items:
        vid = it["id"]["videoId"]
        sn  = it.get("snippet", {})
        d   = dmap.get(vid)
        if not d: continue
        views = parse_int((d.get("statistics") or {}).get("viewCount"))
        merged.append({
            "id": vid,
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "views": views,
            "desc": sn.get("description","")
        })
    merged.sort(key=lambda x: x["views"], reverse=True)
    return merged

# -------------------------
# (기존) 유튜브 트렌딩 mostPopular (참고용)
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

TOPIC_RULES = {
    "시니어 건강": ["health","건강","혈당","당뇨","콜레스테롤","피부","노화","헬스","운동","한방","한의","관절","근육","무릎","허리","치매","혈압"],
    "시니어 북한": ["북한","평양","김정","탈북","안보","핵","미사일","제재","북중","북러"],
    "시니어 인생스토리": ["사연","썰","드라마","가족","며느리","시어머니","반전","감동","고부","사기","유산","눈물","효도"],
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
# 뉴스(웹/방송)
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
        "시니어 건강": "건강 OR 혈당 OR 당뇨 OR 콜레스테롤 OR 피부 OR 노화 OR 한방 OR 운동 OR 무릎 OR 허리 OR 치매",
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
# 신규: 주제별(건강/북한/인생스토리) 유튜브 Top5 (최근 7일)
# -------------------------
YT_QUERIES = {
    "시니어 건강": "건강 OR 혈당 OR 당뇨 OR 콜레스테롤 OR 무릎 OR 허리 OR 치매 OR 관절 OR 한방",
    "시니어 북한": "북한 OR 김정은 OR 평양 OR 미사일 OR 제재 OR 탈북",
    "시니어 인생스토리": "사연 OR 썰 OR 반전 OR 감동 OR 가족 OR 시어머니 OR 고부 OR 효도",
}

def fetch_topic_top5():
    out = {}
    for topic, q in YT_QUERIES.items():
        items = youtube_search_recent_by_views(q, YT_TOP_DAYS, max_results=50)
        out[topic] = items[:5]
        log(f"[YT Top5] {topic}: {len(out[topic])}개")
    return out

# -------------------------
# 오리지널 아이디어 생성기 (룰베이스)
# -------------------------
STOPWORDS = set(["영상","뉴스","속보","라이브","LIVE","풀영상","핫이슈","브이로그","모음","하이라이트","클립"])

def extract_keywords(titles):
    # 아주 단순화된 키워드 추출: 특수문자 제거 → 띄어쓰기 → 2글자 이상 & 불용어 제외
    counts = {}
    for t in titles:
        if not t: continue
        t = re.sub(r"[\[\]\(\)<>【】『』〈〉\-–—_|@:~·•….,!?\"'`]", " ", t)
        for tok in t.split():
            tok = tok.strip()
            if len(tok) < 2: continue
            if tok in STOPWORDS: continue
            counts[tok] = counts.get(tok, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)

def make_original_idea(topic_top5, news_map):
    # 모든 Top5 제목/뉴스 제목에서 키워드 모으기
    all_titles = []
    for lst in topic_top5.values():
        for v in lst:
            all_titles.append(v["title"])
    for ch, items in news_map.items():
        for it in items:
            all_titles.append(it["title"])
    kw = extract_keywords(all_titles)
    top_words = [w for (w,c) in kw[:6]]

    # 간단한 테마 결정: 건강/북한/인생 중 어디가 강한지
    sizes = {k: len(v) for k, v in topic_top5.items()}
    dominant = max(sizes, key=sizes.get) if sizes else "시니어 건강"

    # 템플릿 조합
    if dominant == "시니어 건강":
        title = f"{top_words[0] if top_words else '건강'} 진짜 몰랐던 {top_words[1] if len(top_words)>1 else '비밀'} | 병원 안 가고도 달라지는 3가지"
        thumb = f"{top_words[0] if top_words else '건강'} 충격 팩트!"
        synopsis = [
            "40~70대 시청자 관점에서 ‘오늘 당장 실천 가능한’ 팁 3가지",
            "의학 논란/오해를 쉬운 비유로 정리(광고·과장 주의)",
            "실패/성공 후기 1~2개를 삽입해 현실감 부여",
            "주의사항·금기사항을 카드형 그래픽으로 정리",
        ]
    elif dominant == "시니어 북한":
        title = f"최근 {top_words[0] if top_words else '북한'} 동향, 우리가 놓친 핵심 3포인트 (한눈 요약)"
        thumb = "핵심 3포인트"
        synopsis = [
            "지난 1주 키워드 타임라인(지도/사진 없이도 이해되게)",
            "한국 시니어 시청자에게 직접 영향 갈 수 있는 경제·안보 포인트",
            "국내 보도와 해외 보도 시각 차이 1가지 비교",
            "과열/공포 조장 금지: 팩트 체크 표기",
        ]
    else:  # 시니어 인생스토리
        title = f"며느리 한마디에 뒤집힌 {top_words[0] if top_words else '가족'} 모임, 반전의 결말"
        thumb = "반전 실화"
        synopsis = [
            "실제 사연 포맷(도입-갈등-전환-결말) 4막 구성",
            "시니어 공감 포인트(효·재산·건강·관계) 명확히",
            "시청자 참여 유도: ‘내 이야기’ 댓글 질문 2개",
            "과도한 자극·비방 회피(정서적 카타르시스 중심)",
        ]

    return {"title": title, "thumb": thumb, "synopsis": synopsis, "dominant": dominant, "keywords": top_words}

# -------------------------
# 리포트 작성
# -------------------------
def build_report_md(youtube_top3, youtube_today, news_map, topic_top5, original_idea):
    kst_now = now_kst().strftime("%Y-%m-%d %H:%M (KST)")
    lines = [
        f"# Daily Auto Story — {kst_now}",
        "",
        "매일 오전 8시에 자동 발송되는 요약 리포트입니다.",
        "",
    ]

    # ★ 신규 섹션: 주제별 유튜브 Top5 (최근 7일)
    lines += [
        "## A) 주제별 유튜브 Top 5 (최근 {d}일)".format(d=YT_TOP_DAYS),
        "시니어 타깃 3개 채널(건강/북한/인생스토리) 기준으로 최근 7일 조회수 상위 영상을 모았습니다.",
        ""
    ]
    for ch in ["시니어 건강", "시니어 북한", "시니어 인생스토리"]:
        lines.append(f"### {ch} — Top 5")
        items = topic_top5.get(ch, [])
        if not items:
            lines.append("- (해당 기간에 조건을 만족하는 영상이 없습니다)")
            lines.append("")
            continue
        for i, v in enumerate(items, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            when = (v.get("publishedAt","") or "").replace("T"," ").replace("Z"," UTC")
            lines.append(f"{i}. **[{v['title']}]({url})**")
            lines.append(f"   - 채널: {v['channel']} · 조회수: {v['views']:,} · 업로드: {when}")
        lines.append("")

    # ★ 오리지널 제작 제안
    idea = original_idea
    lines += [
        "## B) 오늘 제작 추천 (오리지널 제안)",
        f"- **메인 주제:** {idea['dominant']}",
        f"- **제목 제안:** {idea['title']}",
        f"- **썸네일 문구(짧게):** {idea['thumb']}",
        "- **시놉시스:**",
    ]
    for s in idea["synopsis"]:
        lines.append(f"  - {s}")
    if idea["keywords"]:
        lines += [f"- 참고 키워드: {', '.join(idea['keywords'])}", ""]
    else:
        lines.append("")

    # (기존) 간단 트렌딩 3개 & 오늘 추천(참고용) — 유지
    lines += [
        "## C) 유튜브 트렌드 스냅샷 (최근 {d}일 · 조회수 ≥ {v:,})".format(d=DAYS_WINDOW, v=MIN_VIEWS),
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
        lines += [
            "### 참고: 트렌딩 기반 오늘의 추천(자동)",
            f"- **주제:** “{youtube_today['title']}”",
            f"- **원본:** https://www.youtube.com/watch?v={youtube_today['id']}",
            ""
        ]

    # 뉴스/방송 트렌드
    source_note = "데이터 출처: Google News RSS (NEWSAPI 미사용)"
    if os.getenv("NEWSAPI_KEY"):
        source_note = "데이터 출처: NewsAPI(인기순)"
    lines += [
        "## D) 웹/방송 트렌드 (최근 {d}일)".format(d=NEWS_DAYS),
        source_note,
        "뉴스·방송·포털 기사 기반으로 시니어 타깃에 적합한 주제입니다.",
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
    return "\n".join(lines)

# -------------------------
# 메인
# -------------------------
def main():
    ensure_dirs()
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY 없음 (Secrets에 추가 필요)")

    # 1) 주제별(건강/북한/인생스토리) Top5 (최근 7일)
    topic_top5 = fetch_topic_top5()

    # 2) 뉴스/방송
    news_map = fetch_news_topics()

    # 3) 오리지널 아이디어 생성
    original_idea = make_original_idea(topic_top5, news_map)

    # 4) (참고) mostPopular 트렌딩 3개
    yt_items = fetch_youtube_trending_kr()
    yt_top3, yt_today = pick_youtube_recos(yt_items)

    # 5) 리포트 작성/저장/메일
    md = build_report_md(yt_top3, yt_today, news_map, topic_top5, original_idea)
    Path(REPORT_PATH).write_text(md, encoding="utf-8")
    log(f"리포트 저장: {REPORT_PATH}")

    subject = "✅ Daily Auto Story: 주제별 유튜브 Top5 + 오리지널 오늘의 주제 + 웹/방송"
    send_email_markdown(md, subject)
    log("메일 발송 완료")

if __name__ == "__main__":
    main()

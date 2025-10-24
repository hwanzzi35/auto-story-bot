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
DAYS_WINDOW   = int(os.getenv("DAYS_WINDOW", "14"))    # (기존) 스냅샷 섹션 참조
MIN_VIEWS     = int(os.getenv("MIN_VIEWS", "1000000")) # (기존) 스냅샷 섹션 필터
NEWS_DAYS     = int(os.getenv("NEWS_DAYS", "10"))      # 뉴스 최근 N일
YT_TOP_DAYS   = int(os.getenv("YT_TOP_DAYS", "7"))     # 주제별 Top5 기간(기본 7일)
LONGFORM_MIN_SECONDS = 180                              # ★ 롱폼 하한: 3분

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
# 사용자 제공 예시(메일 본문에 '참고 스타일'로 노출)
# -------------------------
EXAMPLES_NK = [
    "https://youtu.be/nyxyzqiq6hg?si=iEmALurSivENO1Ak",
    "https://youtu.be/j6TvIBaJtvk?si=liWm9cZcqTYM--7S",
    "https://youtu.be/4yMefBgmPDo?si=M4Ct0rGZnkCCmxd0",
    "https://youtu.be/SXs1eJmlJRM?si=6tP4l6FaNUJagSup",
    "https://youtu.be/kayKpgPINp8?si=l1JjZge7etyFRcVh",
]
EXAMPLES_HEALTH = [
    "https://youtu.be/pnDaOj6qZzk?si=sv9JADMWGxyxb3q8",
    "https://youtu.be/9yqcyl_uzKg?si=vDrKvWlhWRiNoaen",
    "https://youtu.be/R7Kb5-Grbbk?si=hckluLXruAMT3-iV",
    "https://youtu.be/XKecVRIdEOE?si=AEyCbj7HmZj9oq5i",
    "https://youtu.be/FseG8J62eII?si=Ha4zJSNf5gqDrdEn",
    "https://youtu.be/OntC4H67VWM?si=JMCMtuEe6CkJmdI0",
    "https://youtu.be/YYwS4Fx9XxU?si=t4uiHEVefcK-xX6Y",
    "https://youtu.be/30sIvCY0ul4?si=GJGiUVtKsFl-rQRG",
    "https://youtu.be/op_d99AJnz4?si=yJ7Nuqi74ERJvvoy",
    "https://youtu.be/5-R3Qjoqg0s?si=-NuKvzl7bME1LZ58",
    "https://youtu.be/mRa2MEuirpk?si=E9h4QATtSsch6VT3",
]
EXAMPLES_STORY = [
    "https://youtu.be/3p0J0_V4seA?si=NXrZryBy1zQi62Qv",
    "https://youtu.be/BzD9ZgX7b0M?si=RfeDPJscVlI4bIP5",
    "https://youtu.be/Ze9t7VAfEc8?si=H1RfCU6C2jtZ7m4u",
    "https://youtu.be/L3WCz-2kUHg?si=VDl7Z-_BsUt7ZZ47",
    "https://youtu.be/CpBD7dYgkJk?si=zP5wkgRZmr2D7lX8",
    "https://youtu.be/lrg7p6crYvY?si=65kQEBZwm2cMYgzg",
    "https://youtu.be/dO9RLPETiMQ?si=q91sxJqgInpRA_Xu",
    "https://youtu.be/snU_B3F1WxE?si=JiZqUXFCTO8LThYm",
    "https://youtu.be/uOjNsbFvMD0?si=SD4GJ8YJbTzU5gxV",
    "https://youtu.be/Y_3RRkwy4Wc?si=5YBGWHotJ5pQuIcF",
    "https://youtu.be/6PtqKq8M9lk?si=g4NM-Npnz91Y1yTp",
    "https://youtu.be/9zFsgf-kA2U?si=woD7D8TrjWbG5tBh",
]

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
# YouTube API helpers
# -------------------------
def parse_iso8601_duration(dur: str) -> int:
    """
    ISO8601 duration (e.g., PT15M33S) -> seconds
    """
    if not dur or not dur.startswith("PT"):
        return 0
    hours = minutes = seconds = 0
    m = re.findall(r'(\d+H|\d+M|\d+S)', dur)
    for part in m:
        if part.endswith('H'):
            hours = int(part[:-1])
        elif part.endswith('M'):
            minutes = int(part[:-1])
        elif part.endswith('S'):
            seconds = int(part[:-1])
    return hours*3600 + minutes*60 + seconds

def youtube_videos_details(video_ids):
    """videos.list로 snippet, statistics, contentDetails 조회 (길이 필터용)"""
    if not video_ids: return []
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet,statistics,contentDetails",
        "id": ",".join(video_ids[:50])
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("items", [])

def youtube_search_recent_by_views(query: str, days: int, max_results=50):
    """
    최근 N일 내 검색어로 검색 → 조회수순 상위 영상 상세조회 → 롱폼 필터 → 리스트 반환
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
        # videoDuration는 any로 두고, 상세 조회 후 durationSec으로 필터
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
    if not ids: return []

    details = youtube_videos_details(ids)
    merged = []
    for d in details:
        sn = d.get("snippet", {}) or {}
        st = d.get("statistics", {}) or {}
        cd = d.get("contentDetails", {}) or {}
        if sn.get("liveBroadcastContent") and sn.get("liveBroadcastContent") != "none":
            continue  # 라이브 제외
        duration_sec = parse_iso8601_duration(cd.get("duration"))
        if duration_sec < LONGFORM_MIN_SECONDS:
            continue  # ★ 3분 미만 제외(숏폼/쇼츠 차단)
        vid = d.get("id")
        merged.append({
            "id": vid,
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "views": parse_int(st.get("viewCount")),
            "desc": sn.get("description",""),
            "durationSec": duration_sec
        })
    merged.sort(key=lambda x: x["views"], reverse=True)
    return merged

# -------------------------
# (참고) mostPopular 스냅샷
# -------------------------
def fetch_youtube_trending_kr(max_results=50):
    log("유튜브 트렌딩 조회 시작")
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet,statistics,contentDetails",
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
        sn = it.get("snippet", {}) or {}
        st = it.get("statistics", {}) or {}
        cd = it.get("contentDetails", {}) or {}
        views = parse_int(st.get("viewCount"))
        duration_sec = parse_iso8601_duration(cd.get("duration"))
        if duration_sec < LONGFORM_MIN_SECONDS:  # 롱폼만
            continue
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
            "durationSec": duration_sec
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

    log(f"유튜브 추천 선정(롱폼): {len(top3)}개 / 오늘추천: {today['title'] if today else '없음'}")
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
            source_note = "데이터 출처: NewsAPI(인기순)"
        else:
            items = google_news_rss_search(q, NEWS_DAYS)
            source_note = "데이터 출처: Google News RSS (NEWSAPI 미사용)"
        seen = set()
        uniq = []
        for it in items:
            t = (it["title"] or "").strip()
            if not t or t in seen: continue
            seen.add(t)
            uniq.append(it)
        out[ch] = {"items": uniq[:3], "source_note": source_note}
        log(f"뉴스 '{ch}' 추출: {len(out[ch]['items'])}개")
    return out

# -------------------------
# 주제별(건강/북한/인생스토리) 유튜브 Top5 (최근 7일/롱폼만)
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
        log(f"[YT Top5 롱폼] {topic}: {len(out[topic])}개")
    return out

# -------------------------
# 오리지널 아이디어 생성 (카테고리별)
# -------------------------
STOPWORDS = set(["영상","뉴스","속보","라이브","LIVE","풀영상","핫이슈","브이로그","모음","하이라이트","클립"])

def extract_keywords(titles):
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

def propose_for_category(category: str, items: list[dict]):
    titles = [v["title"] for v in items]
    kw = extract_keywords(titles)
    top_words = [w for (w,c) in kw[:6]]
    if category == "시니어 건강":
        title = f"{top_words[0] if top_words else '건강'} 진짜 바꾸는 7일 루틴 | 병원 안 가고 체감되는 변화 3가지"
        thumb = "7일만 따라해보세요"
        synopsis = [
            "근거 중심 팁 3가지(식단/활동/수면) — 과장 금지",
            "주의·금기 항목을 카드형으로 정리",
            "시청자 체크리스트(PDF 링크 가능) 제안",
            "사례 1~2개로 현실감 보강",
        ]
        keyword = top_words[:3] or ["건강","루틴","체크리스트"]
    elif category == "시니어 북한":
        title = f"최근 {top_words[0] if top_words else '북한'} 동향 핵심 브리핑 | 한국 시니어가 꼭 알아야 할 3포인트"
        thumb = "핵심 3포인트"
        synopsis = [
            "지난 1주 주요 사건 타임라인 정리",
            "국내외 시각 비교(국내 보도 vs 해외 싱크탱크)",
            "생활/경제에 미칠 영향 포인트",
            "팩트체크 출처 병기(스크린샷/링크)",
        ]
        keyword = top_words[:3] or ["북한","동향","영향"]
    else:  # 시니어 인생스토리
        title = f"며느리 한마디에 뒤집힌 {top_words[0] if top_words else '가족'} 모임, 끝은 반전이었다"
        thumb = "반전 실화"
        synopsis = [
            "도입-갈등-전환-결말 4막 구성",
            "시니어 공감 키워드(효·재산·건강·관계)",
            "시청자 참여 질문 2개 삽입",
            "자극·비방 회피, 감정선 중심",
        ]
        keyword = top_words[:3] or ["가족","반전","갈등"]
    return {"category": category, "title": title, "thumb": thumb, "synopsis": synopsis, "keywords": keyword}

# -------------------------
# 북한 주제 자료 리소스 추천(정적 권장 리스트)
# -------------------------
def nk_research_resources():
    return [
        "- 통일부/국방부 공식 브리핑(보도자료)",
        "- 외교부/청와대 국가안보실 공개자료",
        "- 유엔 안보리 문서/제재위 보고서",
        "- 미국 국무부/국방부 발표, 의회조사국(CRS) 보고서",
        "- 싱크탱크: 38 North, CSIS, RAND, Brookings",
        "- 국제/해외 언론: VOA, RFA, BBC, NHK 등",
        "- 衛星/OSINT: 위성사진 분석(상용 이미지 서비스 인용), OSINT 연구자 블로그",
        "- 학술데이터: KCI/DBpia의 북한·안보 관련 논문(배경설명용)",
    ]

# -------------------------
# 리포트 작성
# -------------------------
def build_report_md(youtube_top3, youtube_today, news_map, topic_top5, per_category_ideas):
    kst_now = now_kst().strftime("%Y-%m-%d %H:%M (KST)")
    lines = [
        f"# Daily Auto Story — {kst_now}",
        "",
        "매일 오전 8시 자동 발송 리포트입니다. **롱폼(3분 이상)만** 선별해 제공합니다.",
        "",
    ]

    # A) 주제별 유튜브 Top 5 (롱폼/최근 7일)
    lines += [
        "## A) 주제별 유튜브 Top 5 (최근 {d}일 · 롱폼만)".format(d=YT_TOP_DAYS),
        "시니어 타깃 3개 채널(건강/북한/인생스토리) 기준으로 최근 7일 조회수 상위 **롱폼** 영상을 모았습니다.",
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
            mm = v.get("durationSec",0)//60
            ss = v.get("durationSec",0)%60
            lines.append(f"{i}. **[{v['title']}]({url})**")
            lines.append(f"   - 채널: {v['channel']} · 조회수: {v['views']:,} · 길이: {mm}:{ss:02d} · 업로드: {when}")
        lines.append("")

    # B) 오늘 제작 추천(카테고리별 오리지널 제안)
    lines += ["## B) 오늘 제작 추천 (카테고리별 오리지널 제안)",]
    for idea in per_category_ideas:
        lines += [
            f"### {idea['category']}",
            f"- **추천 키워드:** {', '.join(idea['keywords'])}",
            f"- **제목 제안:** {idea['title']}",
            f"- **썸네일 문구:** {idea['thumb']}",
            "- **시놉시스:**",
        ]
        for s in idea["synopsis"]:
            lines.append(f"  - {s}")
        lines.append("")

    # C) 스냅샷(롱폼)
    lines += [
        "## C) 유튜브 트렌드 스냅샷 (최근 {d}일 · 조회수 ≥ {v:,} · 롱폼만)".format(d=DAYS_WINDOW, v=MIN_VIEWS),
    ]
    if youtube_top3:
        for i, v in enumerate(youtube_top3, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            when = v["publishedAt"].replace("T"," ").replace("Z"," UTC")
            mm = v.get("durationSec",0)//60
            ss = v.get("durationSec",0)%60
            lines += [
                f"{i}. **[{v['title']}]({url})**",
                f"   - 채널: {v['channel']} · 주제: {label_topic(v['title'], '')} · 조회수: {v['views']:,} · 길이: {mm}:{ss:02d} · 업로드: {when}",
                ""
            ]
    else:
        lines.append("- (조건에 맞는 항목 없음)")
        lines.append("")

    # D) 웹/방송 트렌드 + 출처
    lines += [
        "## D) 웹/방송 트렌드 (최근 {d}일)".format(d=NEWS_DAYS),
        "뉴스·방송·포털 기사 기반으로 시니어 타깃에 적합한 주제입니다.",
        ""
    ]
    for ch in ["시니어 건강", "시니어 북한"]:
        info = news_map.get(ch, {}) or {}
        items = info.get("items", [])
        source_note = info.get("source_note", "")
        lines.append(f"### {ch} 추천 3개")
        if source_note: lines.append(f"- {source_note}")
        if not items:
            lines.append("- (결과 없음)")
            lines.append("")
            continue
        for i, it in enumerate(items, 1):
            src = f" · 출처: {it['source']}" if it.get("source") else ""
            lines.append(f"{i}. **[{it['title']}]({it['url']})**{src}")
        lines.append("")

    # E) 참고 스타일(사용자 제공 예시 링크)
    lines += [
        "## E) 참고 스타일 (사용자 제공 예시 링크)",
        "실제 제작 톤/구성 참고용입니다.",
        "",
        "### 북한 관련",
    ] + [f"- {u}" for u in EXAMPLES_NK] + [
        "",
        "### 시니어 건강",
    ] + [f"- {u}" for u in EXAMPLES_HEALTH] + [
        "",
        "### 시니어 인생스토리",
    ] + [f"- {u}" for u in EXAMPLES_STORY] + [""]

    # F) 북한 주제: 신뢰 가능한 자료 리소스(권장)
    lines += [
        "## F) 북한 주제 리서치 자료 추천",
        "영상 제작 시 팩트체크/배경설명에 권장되는 출처입니다.",
    ] + nk_research_resources() + [""]

    return "\n".join(lines)

# -------------------------
# 메인
# -------------------------
def main():
    ensure_dirs()
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY 없음 (Secrets에 추가 필요)")

    # 1) 주제별 Top5 (최근 7일/롱폼만)
    topic_top5 = fetch_topic_top5()

    # 2) 카테고리별 오리지널 아이디어
    per_category_ideas = []
    for cat in ["시니어 건강", "시니어 북한", "시니어 인생스토리"]:
        per_category_ideas.append(propose_for_category(cat, topic_top5.get(cat, [])))

    # 3) 뉴스/방송
    news_map = fetch_news_topics()

    # 4) 스냅샷(롱폼 필터 적용)
    yt_items = fetch_youtube_trending_kr()
    yt_top3, yt_today = pick_youtube_recos(yt_items)

    # 5) 리포트 작성/저장/메일
    md = build_report_md(yt_top3, yt_today, news_map, topic_top5, per_category_ideas)
    Path(REPORT_PATH).write_text(md, encoding="utf-8")

    subject = "✅ Daily Auto Story: 롱폼 Top5(건강/북한/인생)+오늘제작추천+웹/방송"
    send_email_markdown(md, subject)

if __name__ == "__main__":
    main()

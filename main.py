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
DAYS_WINDOW   = int(os.getenv("DAYS_WINDOW", "14"))    # 유튜브 최근 N일
MIN_VIEWS     = int(os.getenv("MIN_VIEWS", "1000000")) # 유튜브 최소 조회수
NEWS_DAYS     = int(os.getenv("NEWS_DAYS", "10"))      # 뉴스 최근 N일

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
NEWSAPI_KEY     = os.getenv("NEWSAPI_KEY")   # 선택

SMTP_HOST       = os.getenv("SMTP_HOST")
SMTP_PORT       = os.getenv("SMTP_PORT")
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASS       = os.getenv("SMTP_PASS")
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")

# 경로
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
# 유튜브 트렌딩
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
    # 필터: 조회수/기간
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
    # 주제 다양성 고려: 각 주제 1개 우선
    by_topic = {}
    for v in sorted(filtered, key=lambda x: x["views"], reverse=True):
        if v["topic"] not in by_topic:
            by_topic[v["topic"]] = v

    priority = ["시니어 건강", "시니어 북한", "시니어 인생스토리"]
    top3 = []
    for p in priority:
        if p in by_topic:
            top3.append(by_topic[p])
    # 부족하면 기타에서 채움
    if len(top3) < 3:
        for t, v in by_topic.items():
            if len(top3) >= 3: break
            if v not in top3:
                top3.append(v)
    top3 = top3[:3]

    # 오늘의 추천: 건강 우선 → 없으면 조회수 최대
    today = None
    for v in top3:
        if v["topic"] == "시니어 건강":
            today = v; break
    if not today and top3:
        today = max(top3, key=lambda x: x["views"])

    log(f"유튜브 추천 선정: {len(top3)}개 / 오늘추천: {today['title'] if today else '없음'}")
    return top3, today

# -------------------------
# 뉴스(웹/방송) 트렌드
# -------------------------
def newsapi_search(query: str, from_days: int):
    # NewsAPI가 있으면 인기(popularity) 정렬 사용
    url = "https://newsapi.org/v2/everything"
    params = {
        "apiKey": NEWSAPI_KEY,
        "q": query,
        "language": "ko",
        "sortBy": "popularity",  # 인기순
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
            "score": 1.0,  # popularity 정렬을 신뢰
        })
    return results

def google_news_rss_search(query: str, days: int):
    # Google News RSS (최근 N일)
    url = f"https://news.google.com/rss/search?q={quote(query)}+when:{days}d&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    results = []
    # 간단 점수: 최신일수록 가점
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
            "title": title, "url": link, "source": source, "publishedAt": None, "score": recency
        })
    # 점수순 내림차순
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
        # 중복 제거(제목 기준) 후 상위 3개
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
# 리포트 생성
# -------------------------
def build_report_md(youtube_top3, youtube_today, news_map):
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
            reason.append("채널 폿폴리오와 시너지가 큼(건강/한방/시니어 타깃)")
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

    lines += [
        "## B) 웹/방송 트렌드 (최근 {d}일)".format(d=NEWS_DAYS),
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

    return "\n".join(lines)

# -------------------------
# 메인
# -------------------------
def main():
    ensure_dirs()
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY 없음 (Secrets에 추가 필요)")

    # 1) 유튜브
    yt_items = fetch_youtube_trending_kr()
    yt_top3, yt_today = pick_youtube_recos(yt_items)

    # 2) 뉴스/방송
    news_map = fetch_news_topics()

    # 3) 리포트 생성/저장/메일발송
    md = build_report_md(yt_top3, yt_today, news_map)
    Path(REPORT_PATH).write_text(md, encoding="utf-8")
    log(f"리포트 저장: {REPORT_PATH}")

    subject = "✅ Daily Auto Story: 유튜브 100만+ 3개 & 오늘추천 + 웹/방송 트렌드"
    send_email_markdown(md, subject)
    log("메일 발송 완료")

if __name__ == "__main__":
    main()

import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 환경변수
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
SMTP_HOST       = os.getenv("SMTP_HOST")
SMTP_PORT       = os.getenv("SMTP_PORT")
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASS       = os.getenv("SMTP_PASS")
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")

REPORT_PATH = "data/outputs/weekly_report.md"

# 공통 유틸
def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

def send_email_markdown(body: str, subject: str):
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_USER
    msg["To"] = REPORT_EMAIL_TO
    with smtplib.SMTP(SMTP_HOST, int(SMTP_PORT)) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [REPORT_EMAIL_TO], msg.as_string())

def parse_int(x):
    try: return int(x)
    except: return 0

# 주간 리서치 기준
DAYS_WINDOW = 30
MIN_VIEWS = 100_000
QUERY = "시니어 OR 노년 OR 어르신 OR 50대 OR 60대 OR 중장년"

NEW_TOPIC_RULES = {
    "재테크/연금/퇴직": ["연금","퇴직","노후","재테크","배당","주식","ETF","연금저축","퇴직연금"],
    "부동산/임대": ["부동산","아파트","전세","월세","임대","청약"],
    "의학정보/병원": ["치매","골다공증","허리","무릎","척추","고혈압","고지혈","관상동맥","검진","병원"],
    "요리/집밥/레시피": ["반찬","국","찌개","김치","집밥","요리","레시피","전통","된장","간장"],
    "취미/여가/여행": ["등산","낚시","여행","캠핑","트레킹","정원","텃밭","원예"],
    "노래/트로트/향수": ["트로트","7080","가요","명곡","노래방","추억","콘서트"],
    "법/상속/복지": ["상속","유언","증여","의료비","요양","연금공단","복지"],
}

# 기존 3개 주제
BASE_3 = ["시니어 건강","시니어 북한","시니어 인생스토리"]

def youtube_videos_details(video_ids):
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet,statistics",
        "id": ",".join(video_ids[:50])
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("items", [])

def youtube_search_recent_by_views(query, days, max_results=50):
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

    details = youtube_videos_details(ids)
    detail_map = {d["id"]: d for d in details}
    merged = []
    for it in items:
        vid = it["id"]["videoId"]
        sn  = it.get("snippet", {})
        d   = detail_map.get(vid)
        if not d: continue
        merged.append({
            "id": vid,
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "views": parse_int((d.get("statistics") or {}).get("viewCount")),
            "desc": sn.get("description","")
        })
    merged = [m for m in merged if m["views"] >= MIN_VIEWS]
    return merged

def label_new_topic(title, desc):
    text = (title or "") + " " + (desc or "")
    low = text.lower()
    for t, kws in NEW_TOPIC_RULES.items():
        for kw in kws:
            if kw.lower() in low:
                return t
    return None

def build_weekly_report():
    videos = youtube_search_recent_by_views(QUERY, DAYS_WINDOW, max_results=50)
    if not videos:
        return "# Weekly Senior Trends Report\n\n(데이터 부족)\n"

    topic_bucket = {}
    for v in videos:
        t = label_new_topic(v["title"], v["desc"])
        if not t: continue
        topic_bucket.setdefault(t, []).append(v)

    topic_recos = []
    for t, lst in topic_bucket.items():
        best = max(lst, key=lambda x: x["views"])
        topic_recos.append((t, best))
    topic_recos.sort(key=lambda tb: tb[1]["views"], reverse=True)
    topic_recos = topic_recos[:5]

    top5 = sorted(videos, key=lambda x: x["views"], reverse=True)[:5]

    lines = [
        f"# Weekly Senior Trends Report — {now_kst().strftime('%Y-%m-%d %H:%M (KST)')}",
        "",
        f"기준: 최근 {DAYS_WINDOW}일 · 조회수 ≥ {MIN_VIEWS:,} · 검색어: {QUERY}",
        "",
        "## 신규 유망 주제 Top 5 (기존 3개 제외)",
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
        lines.append("- (이번 주 신규 유망 주제 없음)")
        lines.append("")

    lines += ["## 전체 Top 5 영상"]
    for i, v in enumerate(top5, 1):
        url = f"https://www.youtube.com/watch?v={v['id']}"
        lines.append(f"{i}. [{v['title']}]({url}) · 조회수 {v['views']:,} · 채널 {v['channel']}")
    lines.append("")
    return "\n".join(lines)

def main():
    md = build_weekly_report()
    Path(REPORT_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(REPORT_PATH).write_text(md, encoding="utf-8")
    subject = "✅ Weekly Senior Trends Report — 신규 유망 주제 + Top5 영상"
    send_email_markdown(md, subject)

if __name__ == "__main__":
    main()

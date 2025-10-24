import os
import smtplib
import csv
import requests
from email.mime.text import MIMEText
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta, timezone
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ===== 환경 =====
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")  # 플랜B용
SMTP_HOST       = os.getenv("SMTP_HOST")
SMTP_PORT       = os.getenv("SMTP_PORT")
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASS       = os.getenv("SMTP_PASS")
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")

OUT_DIR   = Path("data/outputs")
HIST_DIR  = Path("data/history")
PDF_PATH  = OUT_DIR / "monthly_report.pdf"

# 분석 기준 (주간과 동일 철학)
DAYS_28    = 28
DAYS_30    = 30
MIN_VIEWS  = 100_000
SENIOR_Q   = "시니어 OR 노년 OR 어르신 OR 50대 OR 60대 OR 중장년"

def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

def send_email_with_pdf(subject: str, body_text: str, pdf_path: Path):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and REPORT_EMAIL_TO):
        raise EnvironmentError("SMTP 환경변수가 누락되었습니다.")
    if not pdf_path.exists():
        raise FileNotFoundError(f"첨부할 PDF가 없습니다: {pdf_path}")

    msg = MIMEMultipart()
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_USER
    msg["To"] = REPORT_EMAIL_TO

    msg.attach(MIMEText(body_text, _charset="utf-8"))

    with pdf_path.open("rb") as f:
        part = MIMEBase("application", "pdf")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{pdf_path.name}"')
    msg.attach(part)

    with smtplib.SMTP(SMTP_HOST, int(SMTP_PORT)) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [REPORT_EMAIL_TO], msg.as_string())

def list_recent_weeks(n_days=DAYS_28):
    cutoff = now_kst() - timedelta(days=n_days)
    folders = []
    for p in HIST_DIR.glob("*"):
        if p.is_dir():
            try:
                dt = datetime.strptime(p.name, "%Y%m%d")
                if dt >= cutoff.replace(tzinfo=None):
                    folders.append((dt, p))
            except:
                pass
    folders.sort(key=lambda x: x[0])
    return [p for _, p in folders]

def read_csv_rows(path: Path):
    try:
        with path.open(encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except:
        return []

# ---------- 플랜B: 히스토리 없으면 실시간 간단 분석 ----------
def youtube_videos_details(video_ids):
    if not (YOUTUBE_API_KEY and video_ids):
        return []
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet,statistics",
        "id": ",".join(video_ids[:50])
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("items", [])

def youtube_search_recent(query, days, order="viewCount", max_results=50):
    if not YOUTUBE_API_KEY:
        return []
    published_after = (datetime.utcnow() - timedelta(days=days)).replace(tzinfo=timezone.utc).isoformat()
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": order,
        "publishedAfter": published_after,
        "maxResults": max_results,
        "relevanceLanguage": "ko",
    }
    r = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
    if not ids:
        return []

    details = youtube_videos_details(ids)
    dmap = {d["id"]: d for d in details}
    merged = []
    for it in items:
        vid = it["id"]["videoId"]
        sn  = it.get("snippet", {})
        d   = dmap.get(vid)
        if not d: continue
        views = int((d.get("statistics") or {}).get("viewCount", 0))
        if views < MIN_VIEWS:  # 10만 이상
            continue
        merged.append({
            "id": vid,
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "views": views
        })
    return sorted(merged, key=lambda x: x["views"], reverse=True)[:10]

# ---------- PDF 생성 ----------
def build_pdf(topics_all, top5_all, rising_all, comp_all):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(PDF_PATH), pagesize=A4)
    W, H = A4
    margin = 40
    y = H - margin

    def line(txt, font="Helvetica", size=11, gap=16, bold=False):
        nonlocal y
        if bold:
            c.setFont("Helvetica-Bold", size)
        else:
            c.setFont(font, size)
        c.drawString(margin, y, (txt or "")[:110])
        y -= gap
        if y < margin:
            c.showPage()
            y = H - margin

    # 표지
    line(f"Monthly Senior Trends — {now_kst().strftime('%Y-%m-%d %H:%M (KST)')}", size=14, bold=True, gap=20)
    line("최근 4주(28일) 집계 · 주간 리포트 CSV 합산 요약", gap=24)

    # 1) 신규 유망 주제
    line("1) 신규 유망 주제 (4주 합산) — 예시 상위 8개", bold=True, gap=18)
    topic_counter = {}
    for r in topics_all:
        t = (r.get("topic") or "").strip()
        if t:
            topic_counter[t] = topic_counter.get(t, 0) + 1
    if topic_counter:
        for i, (t, cnt) in enumerate(sorted(topic_counter.items(), key=lambda x: x[1], reverse=True)[:8], 1):
            line(f"{i}. {t} · {cnt}회 등장")
    else:
        line("- (데이터 없음)")

    # 2) 누적 Top 영상 5
    line("", gap=10)
    line("2) 누적 Top 영상 (상위 5)", bold=True, gap=18)
    def to_int(x):
        try: return int(x)
        except: return 0
    top5_all_sorted = sorted(
        [{"title": r.get("title",""), "url": r.get("url",""), "views": to_int(r.get("views"))} for r in top5_all],
        key=lambda x: x["views"], reverse=True
    )[:5]
    if top5_all_sorted:
        for i, r in enumerate(top5_all_sorted, 1):
            line(f"{i}. {r['title']} · 조회수 {r['views']:,}")
    else:
        line("- (데이터 없음)")

    # 3) 급상승 키워드
    line("", gap=10)
    line("3) 급상승 키워드 (4주 합산 상위 5)", bold=True, gap=18)
    def parse_float(x):
        try: return float(x)
        except: return None
    rising_scored = []
    for r in rising_all:
        delta = to_int(r.get("delta"))
        pct = parse_float(r.get("change_pct"))
        score = (delta * 10) + (pct if pct is not None else 50)
        rising_scored.append((r.get("keyword",""), score))
    summarised = {}
    for k, s in rising_scored:
        summarised[k] = summarised.get(k,0) + s
    if summarised:
        for i, (k, s) in enumerate(sorted(summarised.items(), key=lambda x: x[1], reverse=True)[:5], 1):
            line(f"{i}. {k} (점수 {int(s)})")
    else:
        line("- (데이터 없음)")

    # 4) 경쟁도
    line("", gap=10)
    line("4) 카테고리 경쟁도 (상위/하위)", bold=True, gap=18)
    comp_agg = {}
    for r in comp_all:
        t = r.get("archetype","")
        up = to_int(r.get("uploads"))
        th = to_int(r.get("top_hits"))
        if t:
            u0, t0 = comp_agg.get(t, (0,0))
            comp_agg[t] = (u0+up, t0+th)
    ratios = []
    for t, (up, th) in comp_agg.items():
        ratio = (th / up) if up else 0
        ratios.append((t, ratio))
    if ratios:
        for hdr, seq in [("상위 3 (진입 쉬움)", sorted(ratios, key=lambda x: x[1], reverse=True)[:3]),
                         ("하위 3 (진입 어려움)", sorted(ratios, key=lambda x: x[1])[:3])]:
            line(hdr, bold=True)
            for t, rto in seq:
                line(f"- {t}: 진입률 {round(rto*100,1)}%")
            line("", gap=8)
    else:
        line("- (데이터 없음)")

    c.showPage()
    c.save()

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 히스토리에서 4주치 CSV 읽기
    weeks = list_recent_weeks(DAYS_28)
    topics_all, top5_all, rising_all, comp_all = [], [], [], []
    for wk in weeks:
        topics_all += read_csv_rows(wk / "weekly_topics.csv")
        top5_all  += read_csv_rows(wk / "weekly_top5_videos.csv")
        rising_all+= read_csv_rows(wk / "weekly_rising_keywords.csv")
        comp_all  += read_csv_rows(wk / "weekly_archetype_competition.csv")

    # 2) 히스토리가 없으면 플랜B: 최근 30일 실시간 조회로 간단 섹션 구성
    if not (topics_all or top5_all or rising_all or comp_all):
        # 상위 영상 10개를 뽑아 Top5로 사용(간이)
        latest = youtube_search_recent(SENIOR_Q, DAYS_30, order="viewCount", max_results=50)
        # 간단한 테이블 변환
        top5_all = [{"title": v["title"], "url": f"https://www.youtube.com/watch?v={v['id']}", "views": v["views"]} for v in latest[:5]]
        # 나머지는 빈 리스트로 두되, PDF 표기에서 "데이터 없음"이 아닌 **실제 Top5**는 나오도록
        topics_all, rising_all, comp_all = [], [], []

    # 3) PDF 생성
    build_pdf(topics_all, top5_all, rising_all, comp_all)

    # 4) 이메일 첨부 발송
    subject = "📊 Monthly Senior Trends — 4주 합산 PDF (첨부)"
    body = "월간 종합 PDF를 첨부했습니다.\n(히스토리가 없으면 최근 30일 실시간 Top5로 대체되어 채워집니다)"
    send_email_with_pdf(subject, body, PDF_PATH)

if __name__ == "__main__":
    main()

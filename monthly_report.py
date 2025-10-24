import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# 환경
SMTP_HOST       = os.getenv("SMTP_HOST")
SMTP_PORT       = os.getenv("SMTP_PORT")
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASS       = os.getenv("SMTP_PASS")
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")

OUT_DIR   = Path("data/outputs")
HIST_DIR  = Path("data/history")
PDF_PATH  = OUT_DIR / "monthly_report.pdf"

def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

def send_email_markdown(body: str, subject: str):
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_USER
    msg["To"]   = REPORT_EMAIL_TO
    with smtplib.SMTP(SMTP_HOST, int(SMTP_PORT)) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [REPORT_EMAIL_TO], msg.as_string())

def list_recent_weeks(n_days=28):
    # history 디렉토리에서 최근 n_days 내 폴더(YYYYMMDD)를 수집
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

def build_pdf():
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
        c.drawString(margin, y, txt[:110])  # 한 줄 최대 길이 제한
        y -= gap
        if y < margin:
            c.showPage()
            y = H - margin

    # 데이터 합산
    weeks = list_recent_weeks(28)
    topics_all, top5_all, rising_all, comp_all = [], [], [], []
    for wk in weeks:
        topics_all += read_csv_rows(wk / "weekly_topics.csv")
        top5_all  += read_csv_rows(wk / "weekly_top5_videos.csv")
        rising_all+= read_csv_rows(wk / "weekly_rising_keywords.csv")
        comp_all  += read_csv_rows(wk / "weekly_archetype_competition.csv")

    # 표지를 간단 텍스트로
    line(f"Monthly Senior Trends — {now_kst().strftime('%Y-%m-%d %H:%M (KST)')}", size=14, bold=True, gap=20)
    line("최근 4주(28일) 집계 · 주간 리포트 CSV 합산 요약", gap=24)

    # 1) 신규 유망 주제(주간 예시들을 주제명 기준 Top hits)
    line("1) 신규 유망 주제 (4주 합산) — 예시 상위 8개", bold=True, gap=18)
    topic_counter = {}
    for r in topics_all:
        t = r.get("topic","").strip()
        if t: topic_counter[t] = topic_counter.get(t, 0) + 1
    for i, (t, cnt) in enumerate(sorted(topic_counter.items(), key=lambda x: x[1], reverse=True)[:8], 1):
        line(f"{i}. {t} · {cnt}회 등장")

    # 2) Top5 영상 누적에서 상위 뷰수 5개 (중복 허용)
    line("", gap=10)
    line("2) 누적 Top 영상 (상위 5)", bold=True, gap=18)
    top5_all_sorted = sorted(
        [{"title": r.get("title",""), "url": r.get("url",""), "views": int((r.get("views") or 0) or 0)} for r in top5_all],
        key=lambda x: x["views"], reverse=True
    )[:5]
    for i, r in enumerate(top5_all_sorted, 1):
        line(f"{i}. {r['title']} · 조회수 {r['views']:,}")

    # 3) 급상승 키워드 — 등장 delta/percent 기반 상위 5
    line("", gap=10)
    line("3) 급상승 키워드 (4주 합산 상위 5)", bold=True, gap=18)
    def parse_float(x):
        try: return float(x)
        except: return None
    rising_scored = []
    for r in rising_all:
        delta = int((r.get("delta") or 0) or 0)
        pct = parse_float(r.get("change_pct"))
        score = (delta * 10) + (pct if pct is not None else 50)  # 간단 가중 점수
        rising_scored.append((r.get("keyword",""), score))
    summarised = {}
    for k, s in rising_scored:
        summarised[k] = summarised.get(k,0) + s
    for i, (k, s) in enumerate(sorted(summarised.items(), key=lambda x: x[1], reverse=True)[:5], 1):
        line(f"{i}. {k} (점수 {int(s)})")

    # 4) 경쟁도 — 아키타입별 평균 진입률 상위/하위 3
    line("", gap=10)
    line("4) 카테고리 경쟁도 (상위/하위)", bold=True, gap=18)
    comp_agg = {}
    for r in comp_all:
        t = r.get("archetype","")
        uploads = int((r.get("uploads") or 0) or 0)
        top_hits = int((r.get("top_hits") or 0) or 0)
        if t:
            up, th = comp_agg.get(t, (0,0))
            comp_agg[t] = (up+uploads, th+top_hits)
    ratios = []
    for t, (up, th) in comp_agg.items():
        ratio = (th / up) if up else 0
        ratios.append((t, ratio))
    for hdr, seq in [("상위 3 (진입 쉬움)", sorted(ratios, key=lambda x: x[1], reverse=True)[:3]),
                     ("하위 3 (진입 어려움)", sorted(ratios, key=lambda x: x[1])[:3])]:
        line(hdr, bold=True)
        for t, rto in seq:
            line(f"- {t}: 진입률 {round(rto*100,1)}%")
        line("", gap=8)

    c.showPage()
    c.save()

def main():
    build_pdf()
    subject = "📊 Monthly Senior Trends — 4주 합산 PDF"
    body = "월간 종합 PDF를 첨부 아티팩트로 업로드했습니다.\nActions > monthly-pdf 아티팩트에서 다운로드하세요."
    send_email_markdown(body, subject)

if __name__ == "__main__":
    main()

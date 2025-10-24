import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

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

def send_email_with_pdf(subject: str, body_text: str, pdf_path: Path):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and REPORT_EMAIL_TO):
        raise EnvironmentError("SMTP 환경변수가 누락되었습니다.")
    if not pdf_path.exists():
        raise FileNotFoundError(f"첨부할 PDF가 없습니다: {pdf_path}")

    msg = MIMEMultipart()
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_USER
    msg["To"] = REPORT_EMAIL_TO

    # 본문
    msg.attach(MIMEText(body_text, _charset="utf-8"))

    # 첨부
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

    # 표지
    line(f"Monthly Senior Trends — {now_kst().strftime('%Y-%m-%d %H:%M (KST)')}", size=14, bold=True, gap=20)
    line("최근 4주(28일) 집계 · 주간 리포트 CSV 합산 요약", gap=24)

    # 1) 신규 유망 주제(합산)
    line("1) 신규 유망 주제 (4주 합산) — 예시 상위 8개", bold=True, gap=18)
    topic_counter = {}
    for r in topics_all:
        t = (r.get("topic") or "").strip()
        if t:
            topic_counter[t] = topic_counter.get(t, 0) + 1
    for i, (t, cnt) in enumerate(sorted(topic_counter.items(), key=lambda x: x[1], reverse=True)[:8], 1):
        line(f"{i}. {t} · {cnt}회 등장")

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
    for i, r in enumerate(top5_all_sorted, 1):
        line(f"{i}. {r['title']} · 조회수 {r['views']:,}")

    # 3) 급상승 키워드 Top 5
    line("", gap=10)
    line("3) 급상승 키워드 (4주 합산 상위 5)", bold=True, gap=18)
    def parse_float(x):
        try: return float(x)
        except: return None
    rising_scored = []
    for r in rising_all:
        delta = to_int(r.get("delta"))
        pct = parse_float(r.get("change_pct"))
        score = (delta * 10) + (pct if pct is not None else 50)  # 간단 가중 점수
        rising_scored.append((r.get("keyword",""), score))
    summarised = {}
    for k, s in rising_scored:
        summarised[k] = summarised.get(k,0) + s
    for i, (k, s) in enumerate(sorted(summarised.items(), key=lambda x: x[1], reverse=True)[:5], 1):
        line(f"{i}. {k} (점수 {int(s)})")

    # 4) 경쟁도 — 아키타입 평균 진입률 상/하위 3
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
    for hdr, seq in [("상위 3 (진입 쉬움)", sorted(ratios, key=lambda x: x[1], reverse=True)[:3]),
                     ("하위 3 (진입 어려움)", sorted(ratios, key=lambda x: x[1])[:3])]:
        line(hdr, bold=True)
        for t, rto in seq:
            line(f"- {t}: 진입률 {round(rto*100,1)}%")
        line("", gap=8)

    c.showPage()
    c.save()

def main():
    # PDF 생성
    build_pdf()

    # 이메일로 PDF 첨부 발송
    subject = "📊 Monthly Senior Trends — 4주 합산 PDF (첨부)"
    body = "월간 종합 PDF를 첨부했습니다.\n(아티팩트에서도 다운로드 가능: Actions > monthly-pdf)"
    send_email_with_pdf(subject, body, PDF_PATH)

if __name__ == "__main__":
    main()

import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

# =========================
# 환경변수
# =========================
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
SMTP_HOST       = os.getenv("SMTP_HOST")
SMTP_PORT       = os.getenv("SMTP_PORT")
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASS       = os.getenv("SMTP_PASS")
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")

REPORT_PATH = "data/outputs/weekly_report.md"

# =========================
# 공통 유틸
# =========================
def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))  # KST

def send_email_markdown(body: str, subject: str):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and REPORT_EMAIL_TO):
        raise EnvironmentError("SMTP 환경변수가 누락되었습니다.")
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_USER
    msg["To"]   = REPORT_EMAIL_TO
    with smtplib.SMTP(SMTP_HOST, int(SMTP_PORT)) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [REPORT_EMAIL_TO], msg.as_string())

def parse_int(x):
    try: return int(x)
    except: return 0

def iso_utc(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()

# =========================
# 기준값
# =========================
# 주간(월요일 발송) 기본
DAYS_WINDOW_MONTH = 30           # 한달 분석
MIN_VIEWS_MONTH   = 100_000

# 급상승 키워드 분석용
CURRENT_DAYS = 7                 # 최근 7일
PREVIOUS_DAYS = 7                # 그 전 7일

# 검색 쿼리 (시니어 타깃)
SENIOR_QUERY = "시니어 OR 노년 OR 어르신 OR 50대 OR 60대 OR 중장년"

# 신규 유망 주제 라벨 (기존 3대 주제 제외용 아키타입)
NEW_TOPIC_RULES = {
    "재테크/연금/퇴직": ["연금","퇴직","노후","재테크","배당","주식","ETF","연금저축","퇴직연금","국민연금"],
    "부동산/임대": ["부동산","아파트","전세","월세","임대","청약","등기"],
    "의학정보/병원": ["치매","골다공증","허리","무릎","척추","고혈압","고지혈","관상동]()

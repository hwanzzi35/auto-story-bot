import os, smtplib
from email.mime.text import MIMEText

def send_email_markdown(md_text, subject="일일 스토리 리포트"):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT") or "587")
    user = os.getenv("SMTP_USER")
    pwd  = os.getenv("SMTP_PASS")
    to   = os.getenv("REPORT_EMAIL_TO")

    # 값 점검 로그 (비번은 길이만)
    print("SMTP ENV:",
          "HOST=", host,
          "PORT=", port,
          "USER=", user,
          "PASS_LEN=", len(pwd) if pwd else 0,
          "TO=", to)

    if not (host and port and user and pwd and to):
        raise ValueError("SMTP 환경변수 누락: HOST/PORT/USER/PASS/TO 확인")

    msg = MIMEText(md_text, _subtype="plain", _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to

    with smtplib.SMTP(host, port, timeout=30) as s:
        s.set_debuglevel(1)   # 서버 응답 로그 보기
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(user, pwd)    # ← 여기서 535면 아이디/앱비번/IMAP설정 문제
        s.send_message(msg)

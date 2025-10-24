import os, smtplib
from email.mime.text import MIMEText

def send_email_markdown(md_text, subject="일일 스토리 리포트"):
    msg = MIMEText(md_text, _subtype="plain", _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_USER")
    msg["To"] = os.getenv("REPORT_EMAIL_TO")

    with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT"))) as s:
        s.starttls()
        s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        s.send_message(msg)

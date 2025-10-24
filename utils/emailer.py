import os, smtplib
from email.mime.text import MIMEText
from email.header import Header

def send_email_markdown(markdown_body: str, subject: str):
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = os.getenv("SMTP_PORT")
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASS = os.getenv("SMTP_PASS")
    REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")
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

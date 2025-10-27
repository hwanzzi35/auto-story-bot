import os, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime_text import MIMEText

def _smtp_env():
    need = ["SMTP_HOST","SMTP_PORT","SMTP_USER","SMTP_PASS","REPORT_EMAIL_TO"]
    miss = [k for k in need if not os.getenv(k)]
    if miss:
        raise EnvironmentError("SMTP 환경변수 누락: " + ", ".join(miss))
    return (
        os.getenv("SMTP_HOST"),
        int(os.getenv("SMTP_PORT")),
        os.getenv("SMTP_USER"),
        os.getenv("SMTP_PASS"),
        os.getenv("REPORT_EMAIL_TO"),
    )

def send_email_markdown(markdown_text: str, subject: str):
    host, port, user, pwd, to_addr = _smtp_env()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(markdown_text, "plain", "utf-8"))

    with smtplib.SMTP(host, port) as s:
        try:
            s.starttls()
        except smtplib.SMTPException:
            # TLS 미지원 서버일 경우 무시
            pass
        s.login(user, pwd)
        s.sendmail(user, [to_addr], msg.as_string())

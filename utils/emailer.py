import os
import smtplib
import ssl
from email.utils import formataddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _smtp_env():
    need = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "REPORT_EMAIL_TO"]
    miss = [k for k in need if not os.getenv(k)]
    if miss:
        raise EnvironmentError("SMTP 환경변수 누락: " + ", ".join(miss))

    host = os.getenv("SMTP_HOST")
    # PORT는 문자열일 수도 있으므로 안전하게 캐스팅
    try:
        port = int(os.getenv("SMTP_PORT"))
    except Exception:
        raise ValueError("SMTP_PORT는 정수여야 합니다.")

    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_PASS")
    to_addr = os.getenv("REPORT_EMAIL_TO")

    # 선택 옵션
    sender_name = os.getenv("SMTP_SENDER_NAME", "")  # 예: "Auto Story Bot"
    use_ssl = os.getenv("SMTP_SSL", "0") == "1"      # SMTPS(SSL) 사용 (포트 보통 465)
    use_tls = os.getenv("SMTP_USE_TLS", "1") != "0"  # STARTTLS 사용 (포트 보통 587)

    return host, port, user, pwd, to_addr, sender_name, use_ssl, use_tls


def send_email_markdown(markdown_text: str, subject: str):
    """
    간단 텍스트(마크다운) 본문 메일 발송.
    - SMTP_SSL=1 이면 smtplib.SMTP_SSL 사용
    - 아니면 SMTP 후 STARTTLS (SMTP_USE_TLS=0이면 TLS 생략)
    """
    host, port, user, pwd, to_addr, sender_name, use_ssl, use_tls = _smtp_env()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, user)) if sender_name else user
    msg["To"] = to_addr

    # 텍스트 파트 (마크다운을 그냥 텍스트로 보냄)
    msg.attach(MIMEText(markdown_text, "plain", "utf-8"))

    server = None
    try:
        if use_ssl:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.ehlo()
            if use_tls:
                try:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                except smtplib.SMTPException:
                    # 일부 서버가 STARTTLS를 지원하지 않을 수 있음 → 경고만 하고 계속
                    pass

        server.login(user, pwd)
        server.sendmail(user, [to_addr], msg.as_string())

    finally:
        try:
            if server is not None:
                server.quit()
        except Exception:
            # 네트워크 환경에 따라 quit() 예외 무시
            pass

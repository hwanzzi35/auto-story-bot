from send_outputs import send_email_markdown

def main():
    send_email_markdown("✅ 액션/이메일 파이프라인 정상 동작 테스트", subject="테스트 메일")

if __name__ == "__main__":
    main()

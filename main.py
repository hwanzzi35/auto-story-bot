import os
from pathlib import Path
from utils.io import OUT_DIR, now_kst, load_yaml, log_info
from utils.emailer import send_email_markdown
from utils.youtube import search_story_candidates, filter_story
from utils.nlp import extract_top_keywords, make_strong_titles_from_keywords

REPORT_PATH = OUT_DIR / "report.md"

def _require_envs():
    need = ["YOUTUBE_API_KEY","SMTP_HOST","SMTP_PORT","SMTP_USER","SMTP_PASS","REPORT_EMAIL_TO"]
    missing = [k for k in need if not os.getenv(k)]
    if missing:
        raise EnvironmentError("필수 환경변수 누락: " + ", ".join(missing))

def load_story_keywords():
    cfg = load_yaml("config/keywords.yaml").get("story", {})
    return (
        [w.lower() for w in (cfg.get("must_phrases") or [])],
        [w.lower() for w in (cfg.get("include") or [])],
        [w.lower() for w in (cfg.get("exclude") or [])],
    )

def build_email_md(top5: list[dict], kw_summary: list[str], new_titles: list[dict], window_note:str):
    kst_now = now_kst().strftime("%Y-%m-%d %H:%M (KST)")
    lines = [
        f"# 시니어 인생스토리 리포트 — {kst_now}",
        "",
        f"> 기준: **최근 {window_note} 영상** · **제목/태그에 필수 문구 1+** · **길이 30~120분**",
        "",
        "## A) 시니어 인생스토리 — Top 5 (조회수순)",
    ]
    if not top5:
        lines += ["- (조건을 만족하는 영상이 없습니다)", ""]
    else:
        for i, v in enumerate(top5, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            mm = v.get("durationSec",0)//60
            ss = v.get("durationSec",0)%60
            when = (v.get("publishedAt","") or "").replace("T"," ").replace("Z"," UTC")
            lines += [
                f"{i}. **[{v['title']}]({url})**",
                f"   - 채널: {v['channel']} · 조회수: {v['views']:,} · 길이: {mm}:{ss:02d} · 업로드: {when}",
            ]
        lines.append("")

    lines += [
        "## B) 최근 상위 영상에서 추출한 핵심 키워드",
        ("- " + ", ".join(kw_summary)) if kw_summary else "- (키워드 추출 불가)",
        "",
        "## C) 오늘의 신규 제목 제안 (표절 금지 · 자극 강)",
    ]
    if new_titles:
        for t in new_titles:
            lines.append(f"- **제목:** {t['title']}  \n  **썸네일:** {t['thumb']}")
    else:
        lines.append("- (제안 생성 불가)")
    lines.append("")
    return "\n".join(lines)

def main():
    _require_envs()
    must, include, exclude = load_story_keywords()

    # 1) 후보 수집(7일) → 부족 시 14일→21일로 기간만 확장 (조건 완화 없음)
    plan = [(7,"7일"), (14,"14일"), (21,"21일")]
    picked = []
    window_note = "7일"
    base_query = "사연 OR 라디오 OR 오디오북 OR 반전 OR 가족 OR 시어머니 OR 고부 OR 무시 OR 복수 OR 백만장자 OR 재벌"
    seen = set()

    for days, note in plan:
        window_note = note
        cand = search_story_candidates(base_query, days, max_results=100)
        kept = filter_story(cand, must, include, exclude, step=days)
        for v in kept:
            if v["id"] in seen: continue
            picked.append(v); seen.add(v["id"])
            if len(picked) >= 5: break
        if len(picked) >= 5: break

    top5 = picked[:5]

    # 2) 키워드 요약 + 신규 제목 5개(표절 금지)
    titles = [v["title"] for v in top5]
    tags = [v.get("tags",[]) for v in top5]
    kw_summary = extract_top_keywords(titles, tags, topk=12)
    new_titles = make_strong_titles_from_keywords(kw_summary, n=5)

    # 3) 메일 본문 작성 및 발송
    md = build_email_md(top5, kw_summary, new_titles, window_note)
    Path(REPORT_PATH).write_text(md, encoding="utf-8")
    send_email_markdown(md, "✅ 시니어 인생스토리: Top5 & 신규 강제목 5개")

if __name__ == "__main__":
    main()

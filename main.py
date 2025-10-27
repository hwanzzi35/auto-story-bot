import os
from pathlib import Path
from utils.io import (
    OUT_DIR, now_kst, load_yaml,
    log_event, log_warn, log_error,
    log_fallback, log_summary, log_pick, log_exclude,
)
from utils.emailer import send_email_markdown
from utils.news import fetch_news_topics
from utils.youtube import (
    search_recent_by_views, apply_category_rules
)
from utils.nlp import propose_for_category, make_titles

REPORT_PATH = OUT_DIR / "report.md"

# 카테고리별 기본 쿼리(너무 광범위하면 노이즈 증가 → 핵심어 위주)
YT_QUERIES = {
    "시니어 건강": "건강 OR 혈당 OR 당뇨 OR 콜레스테롤 OR 무릎 OR 허리 OR 치매 OR 관절 OR 한방 OR 루틴 OR 식단 OR 운동",
    "시니어 북한": "북한 OR 김정은 OR 평양 OR 미사일 OR 제재 OR 탈북 OR 안보 OR 장마당 OR 군사",
    "시니어 인생스토리": "사연 OR 썰 OR 반전 OR 가족 OR 시어머니 OR 고부 OR 무시 OR 복수 OR 백만장자 OR 재벌",
}

def _require_envs():
    need = ["YOUTUBE_API_KEY","SMTP_HOST","SMTP_PORT","SMTP_USER","SMTP_PASS","REPORT_EMAIL_TO"]
    missing = [k for k in need if not os.getenv(k)]
    if missing:
        raise EnvironmentError("필수 환경변수 누락: " + ", ".join(missing))

def _load_configs():
    keywords = load_yaml("config/keywords.yaml")
    inc = {
        "시니어 건강": [w.lower() for w in (keywords.get("health",{}).get("include",[]) or [])],
        "시니어 북한": [w.lower() for w in (keywords.get("nk",{}).get("include",[]) or [])],
        "시니어 인생스토리": [w.lower() for w in (keywords.get("story",{}).get("include",[]) or [])],
    }
    exc = {
        "시니어 건강": [w.lower() for w in (keywords.get("health",{}).get("exclude",[]) or [])],
        "시니어 북한": [w.lower() for w in (keywords.get("nk",{}).get("exclude",[]) or [])],
        "시니어 인생스토리": [w.lower() for w in (keywords.get("story",{}).get("exclude",[]) or [])],
    }
    # NEW: must phrases for story
    must = {
        "시니어 건강": [],
        "시니어 북한": [],
        "시니어 인생스토리": [w.lower() for w in (keywords.get("story",{}).get("must_phrases",[]) or [])],
    }
    return inc, exc, must

def _fetch_candidates(cat:str, days:int, query:str, include:list, exclude:list, must:list):
    cand = search_recent_by_views(query, days, max_results=100)
    kept = apply_category_rules(cat, cand, include, exclude, must_phrases=must)
    log_event("fetch_candidates", cat=cat, days=days, total=len(cand), kept=len(kept))
    return kept

def _ensure_top5(cat:str, query:str, include:list, exclude:list, must:list):
    """
    5개 보장 — 기간만 넓힘(조건은 완화하지 않음)
    """
    plan = [
        {"step":1, "days":7,  "note":"base"},
        {"step":2, "days":14, "note":"expand_window"},
        {"step":3, "days":21, "note":"expand_window_21"},
    ]
    picked = []
    used_step = 0
    for p in plan:
        used_step = p["step"]
        log_fallback(cat, used_step, p["days"], p["note"])
        cands = _fetch_candidates(cat, p["days"], query, include, exclude, must)

        seen = set(x["id"] for x in picked)
        for v in cands:
            if v["id"] in seen: continue
            picked.append(v); seen.add(v["id"]); log_pick(cat, v, step=used_step)
            if len(picked) >= 5: break
        if len(picked) >= 5: break

    log_summary(cat, len(picked), used_step)
    return picked[:5]

def build_report_md(topic_top5:dict, per_category_ideas:list, strong_titles:dict, news_map:dict):
    kst_now = now_kst().strftime("%Y-%m-%d %H:%M (KST)")
    lines = [
        f"# Daily Auto Story — {kst_now}",
        "",
        "시니어 3대 니치(건강/북한/인생스토리)를 **길이/키워드/블랙리스트/필수문구(스토리)**로 선별했습니다.",
        "",
        "## A) 카테고리별 유튜브 Top 5 (정책 적용)",
    ]
    for ch in ["시니어 건강", "시니어 북한", "시니어 인생스토리"]:
        items = topic_top5.get(ch, [])
        lines.append(f"### {ch} — Top 5")
        if not items:
            lines += ["- (해당 조건을 만족하는 영상이 없습니다)", ""]
            continue
        for i, v in enumerate(items, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            mm = v.get("durationSec",0)//60
            ss = v.get("durationSec",0)%60
            when = (v.get("publishedAt","") or "").replace("T"," ").replace("Z"," UTC")
            lines += [
                f"{i}. **[{v['title']}]({url})**",
                f"   - 채널: {v['channel']} · 조회수: {v['views']:,} · 길이: {mm}:{ss:02d} · 업로드: {when}",
            ]
        lines.append("")

    # 강(자극형) 제목/썸네일 5개
    lines += ["## B) 카테고리별 강(자극형) 제목·썸네일 5개"]
    for ch in ["시니어 건강", "시니어 북한", "시니어 인생스토리"]:
        lines.append(f"### {ch} — 추천 제목 5개")
        for t in strong_titles.get(ch, []):
            lines.append(f"- **제목:** {t['title']}  \n  **썸네일:** {t['thumb']}")
        lines.append("")

    # 오늘 제작 추천(요약형 1개)
    lines += ["## C) 오늘 제작 추천 (카테고리별 오리지널 제안)"]
    for idea in per_category_ideas:
        lines += [
            f"### {idea['category']}",
            f"- **추천 키워드:** {', '.join(idea.get('keywords',[])) or '-'}",
            f"- **제목 제안:** {idea['title']}",
            f"- **썸네일 문구:** {idea['thumb']}",
            "- **시놉시스:**",
        ] + [f"  - {s}" for s in idea["synopsis"]] + [""]

    # 뉴스/방송
    lines += [
        "## D) 웹/방송 트렌드 (최근 10일)",
        "뉴스·방송·포털 기사 기반으로 시니어 타깃에 적합한 주제입니다.",
        ""
    ]
    for ch in ["시니어 건강", "시니어 북한"]:
        info = news_map.get(ch, {}) or {}
        items = info.get("items", [])
        source_note = info.get("source_note", "")
        lines.append(f"### {ch} 추천 3개")
        if source_note: lines.append(f"- {source_note}")
        if not items:
            lines += ["- (결과 없음)", ""]
            continue
        for i, it in enumerate(items, 1):
            src = f" · 출처: {it.get('source','')}" if it.get("source") else ""
            lines.append(f"{i}. **[{it['title']}]({it['url']})**{src}")
        lines.append("")
    return "\n".join(lines)

def main():
    _require_envs()
    include_map, exclude_map, must_map = _load_configs()

    topic_top5 = {}
    for cat, query in YT_QUERIES.items():
        top5 = _ensure_top5(
            cat, query,
            include_map.get(cat, []),
            exclude_map.get(cat, []),
            must_map.get(cat, [])
        )
        topic_top5[cat] = top5

    # 강(자극형) 제목·썸네일 5개씩
    strong_titles = {
        cat: make_titles(cat, topic_top5.get(cat, []), strength="강", n=5)
        for cat in ["시니어 건강","시니어 북한","시니어 인생스토리"]
    }

    # 오늘 제작 추천(요약형 1개)
    per_category_ideas = [propose_for_category(cat, topic_top5.get(cat, []))
                          for cat in ["시니어 건강","시니어 북한","시니어 인생스토리"]]

    # 뉴스/방송
    news_map = fetch_news_topics()

    # 리포트 생성/발송
    md = build_report_md(topic_top5, per_category_ideas, strong_titles, news_map)
    Path(REPORT_PATH).write_text(md, encoding="utf-8")
    send_email_markdown(md, "✅ Daily Auto Story: 정책적용 Top5 (스토리=오디오북/라디오사연 계열 강제)")

if __name__ == "__main__":
    main()

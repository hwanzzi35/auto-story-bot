import os
from pathlib import Path
from utils.io import log, load_yaml, OUT_DIR, now_kst
from utils.emailer import send_email_markdown
from utils.news import fetch_news_topics
from utils.youtube import (
    search_recent_by_views, build_anchor_profile, filter_and_rank
)
from utils.nlp import propose_for_category

REPORT_PATH = OUT_DIR / "report.md"

# 카테고리별 기본 쿼리
YT_QUERIES = {
    "시니어 건강": "건강 OR 혈당 OR 당뇨 OR 콜레스테롤 OR 무릎 OR 허리 OR 치매 OR 관절 OR 한방 OR 루틴 OR 식단 OR 운동",
    "시니어 북한": "북한 OR 김정은 OR 평양 OR 미사일 OR 제재 OR 탈북 OR 안보",
    "시니어 인생스토리": "사연 OR 썰 OR 반전 OR 감동 OR 가족 OR 시어머니 OR 고부 OR 효도 OR 무시 OR 복수",
}

def build_report_md(topic_top5:dict, per_category_ideas:list, news_map:dict, anchors:dict, keywords:dict):
    kst_now = now_kst().strftime("%Y-%m-%d %H:%M (KST)")
    lines = [
        f"# Daily Auto Story — {kst_now}",
        "",
        "시니어 3대 니치(건강/북한/인생스토리)를 **레퍼런스 채널/영상에 앵커링**하여, 최근 7일 **롱폼(3분 이상)** Top 5만 선별했습니다.",
        "",
        "## A) 카테고리별 유튜브 Top 5 (최근 7일 · 롱폼만)",
    ]
    for ch in ["시니어 건강", "시니어 북한", "시니어 인생스토리"]:
        items = topic_top5.get(ch, [])
        lines.append(f"### {ch} — Top 5")
        if not items:
            lines += ["- (해당 기간에 조건을 만족하는 영상이 없습니다)", ""]
            continue
        for i, v in enumerate(items, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            when = (v.get("publishedAt","") or "").replace("T"," ").replace("Z"," UTC")
            mm = v.get("durationSec",0)//60
            ss = v.get("durationSec",0)%60
            lines += [
                f"{i}. **[{v['title']}]({url})**",
                f"   - 채널: {v['channel']} · 조회수: {v['views']:,} · 길이: {mm}:{ss:02d} · 업로드: {when}",
            ]
        lines.append("")

    lines += ["## B) 오늘 제작 추천 (카테고리별 오리지널 제안)"]
    for idea in per_category_ideas:
        lines += [
            f"### {idea['category']}",
            f"- **추천 키워드:** {', '.join(idea.get('keywords',[])) or '-'}",
            f"- **제목 제안:** {idea['title']}",
            f"- **썸네일 문구:** {idea['thumb']}",
            "- **시놉시스:**",
        ] + [f"  - {s}" for s in idea["synopsis"]] + [""]

    lines += [
        "## C) 웹/방송 트렌드 (최근 10일)",
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
            src = f" · 출처: {it['source']}" if it.get("source") else ""
            lines.append(f"{i}. **[{it['title']}]({it['url']})**{src}")
        lines.append("")

    lines += [
        "## D) 참고 스타일(앵커) 요약",
        "- **인생스토리 앵커 채널 수:** " + str(len(anchors['story']['channels'])),
        "- **건강 앵커 채널 수:** " + str(len(anchors['health']['channels'])),
        "- **북한 앵커 채널 수:** " + str(len(anchors['nk']['channels'])),
        "",
        "### 인생스토리 화이트 키워드",
        ", ".join(keywords.get("story",{}).get("include",[]) or []),
        "",
        "### 건강 화이트 키워드",
        ", ".join(keywords.get("health",{}).get("include",[]) or []),
        "",
        "### 북한 화이트 키워드",
        ", ".join(keywords.get("nk",{}).get("include",[]) or []),
        ""
    ]
    return "\n".join(lines)

def main():
    # 0) 설정 로드
    anchors = load_yaml("config/anchors.yaml")
    keywords = load_yaml("config/keywords.yaml")

    # 1) 카테고리별 앵커 프로필 만들기
    anchor_profiles = {}
    for cat in ["health","story","nk"]:
        a = anchors.get(cat, {})
        prof = build_anchor_profile(a.get("channels",[]), a.get("videos",[]))
        anchor_profiles[cat] = prof
        log(f"[anchor] {cat}: channels={len(prof['channels'])}, kw={len(prof['keywords'])}")

    # 2) 카테고리별 후보 수집 → 앵커링 스코어 → Top5
    strict_map = {
        "시니어 건강": (os.getenv("STRICT_HEALTH","1")=="1"),
        "시니어 인생스토리": (os.getenv("STRICT_STORY","1")=="1"),
        "시니어 북한": (os.getenv("STRICT_NK","0")=="1"),
    }
    topic_map = {"시니어 건강":"health","시니어 인생스토리":"story","시니어 북한":"nk"}
    topic_top5 = {}
    for cat, query in YT_QUERIES.items():
        candidates = search_recent_by_views(query, int(os.getenv("YT_TOP_DAYS","7")), max_results=50)
        ap = anchor_profiles[topic_map[cat]]
        inc = [w.lower() for w in (keywords.get(topic_map[cat],{}).get("include",[]) or [])]
        exc = [w.lower() for w in (keywords.get(topic_map[cat],{}).get("exclude",[]) or [])]
        picked = filter_and_rank(candidates, ap, inc, exc, strict=strict_map[cat], need=5)
        topic_top5[cat] = picked
        log(f"[Top5] {cat}: {len(picked)}개 (strict={strict_map[cat]})")

    # 3) 오늘 제작 추천 (카테고리별)
    per_category_ideas = [propose_for_category(cat, topic_top5.get(cat, []))
                          for cat in ["시니어 건강","시니어 북한","시니어 인생스토리"]]

    # 4) 뉴스/방송
    news_map = fetch_news_topics()

    # 5) 리포트 생성/발송
    md = build_report_md(topic_top5, per_category_ideas, news_map, anchor_profiles, keywords)
    Path(REPORT_PATH).write_text(md, encoding="utf-8")
    send_email_markdown(md, "✅ Daily Auto Story: 앵커링된 롱폼 Top5 + 오늘제작추천 + 웹/방송")

if __name__ == "__main__":
    main()

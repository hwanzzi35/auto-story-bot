import re

STOP = set(["영상","뉴스","속보","라이브","LIVE","풀영상","핫이슈","브이로그","모음","하이라이트","클립"])

def extract_keywords(titles, topk=10):
    counts = {}
    for t in titles:
        if not t: continue
        t = re.sub(r"[\[\]\(\)<>【】『』〈〉\-–—_|@:~·•….,!?\"'`]", " ", t)
        for tok in t.split():
            tok = tok.strip()
            if len(tok) < 2 or tok in STOP: continue
            counts[tok] = counts.get(tok, 0) + 1
    return [w for w,_ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:topk]]

def propose_for_category(category: str, items: list[dict]):
    titles = [v.get("title","") for v in items]
    kws = extract_keywords(titles, topk=6)
    if category == "시니어 건강":
        title = f"{(kws[0] if kws else '건강')} 진짜 바꾸는 7일 루틴 | 병원 안 가고 체감되는 변화 3가지"
        thumb = "7일만 따라해보세요"
        synopsis = [
            "근거 중심 팁 3가지(식단/활동/수면) — 과장 금지",
            "주의·금기 항목을 카드형으로 정리",
            "시청자 체크리스트 제공(설명란)",
        ]
    elif category == "시니어 북한":
        title = f"최근 {(kws[0] if kws else '북한')} 동향 핵심 브리핑 | 시니어가 알아야 할 3포인트"
        thumb = "핵심 3포인트"
        synopsis = [
            "지난 1주 주요 사건 타임라인",
            "국내·해외 보도 시각 비교",
            "생활/경제 영향 포인트와 팩트체크 링크",
        ]
    else:
        title = f"며느리 한마디에 뒤집힌 {(kws[0] if kws else '가족')} 모임, 결말은 반전이었다"
        thumb = "뒤집어버렸습니다"
        synopsis = [
            "도입-갈등-전환-결말 4막 구성",
            "효·재산·건강·관계 등 시니어 공감 키워드",
            "시청자 참여 유도 질문 2개 삽입",
        ]
    return {"category": category, "title": title, "thumb": thumb, "synopsis": synopsis, "keywords": (kws[:3] if kws else [])}

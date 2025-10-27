import re

STOP = set(["영상","뉴스","속보","라이브","LIVE","풀영상","하이라이트","클립","브이로그"])

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

def make_titles(category:str, items:list[dict], strength:str="강", n:int=5):
    titles = [v.get("title","") for v in items]
    kws = extract_keywords(titles, topk=8)
    out = []
    if category == "시니어 건강":
        bases = [
            "의사도 인정한 {k1} 루틴, 단 7일이면 뒤집힙니다",
            "당장 끊어야 할 {k1} 습관 3가지 | {k2}까지 무너집니다",
            "병원 가기 전 꼭 보세요: {k1} 잡는 아침 한 접시",
            "노년 {k1}의 진실 | 절대 함께 먹지 마세요",
            "{k1} 올리는 숨은 범인, 이 조합만 끊으세요"
        ]
        thumbs = ["단 7일 루틴", "의사 경고", "아침 한 접시", "절대 함께 NO", "숨어있던 범인"]
    elif category == "시니어 북한":
        bases = [
            "이제 못 막는다: 최근 {k1} 동향 핵심 3포인트",
            "\"{k1}\"… 내부 자료로 본 진짜 의미",
            "{k1} 후폭풍 | 시니어가 꼭 알아야 할 변화",
            "해외언론이 본 {k1}… 우리가 놓친 것들",
            "타임라인으로 본 일주일: {k1}의 모든 것"
        ]
        thumbs = ["핵심 3포인트", "내부 자료", "필수 변화", "해외 시각", "1주 총정리"]
    else:
        bases = [
            "무시하던 {k1}, 내 정체 알자… 모두 뒤집었습니다",
            "예비며느리의 한마디, 그날 이후 나는 복수했습니다",
            "청소부라며 조롱… 알고 보니 {k1}였습니다",
            "동창회에서 당한 모욕, 결국 {k1}로 갚았습니다",
            "황혼의 {k1}, 유산 10억… 결말은 충격"
        ]
        thumbs = ["뒤집어버렸습니다", "복수했습니다", "충격적입니다", "상상도 못했습니다", "반전 결말"]

    while len(out) < n:
        i = len(out) % len(bases)
        k1 = (kws[0] if kws else category)
        k2 = (kws[1] if len(kws)>1 else "건강")
        out.append({"title": bases[i].format(k1=k1, k2=k2), "thumb": thumbs[i]})
    return out[:n]

def propose_for_category(category: str, items: list[dict]):
    # 유지(요약형 1개)
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

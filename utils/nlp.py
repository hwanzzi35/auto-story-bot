import re
from collections import Counter

STOP = set(["영상","뉴스","속보","라이브","LIVE","풀영상","하이라이트","클립","브이로그","라디오","오디오북"])

def tokenize(text: str):
    t = re.sub(r"[\[\]\(\)<>【】『』〈〉\-–—_|@:~·•….,!?\"'`]", " ", text or "")
    toks = [w.strip() for w in t.split() if w.strip()]
    return [w for w in toks if len(w) >= 2 and w not in STOP]

def extract_top_keywords(titles: list[str], tags: list[list[str]], topk=12):
    c = Counter()
    for t in titles:
        for tok in tokenize(t):
            c[tok] += 1
    for taglist in tags:
        for tag in taglist or []:
            for tok in tokenize(tag):
                c[tok] += 1
    return [w for w,_ in c.most_common(topk)]

def make_strong_titles_from_keywords(kws: list[str], n:int=5):
    """표절 금지: 원제 복사 금지. 템플릿+키워드 합성으로 완전 신규 생성."""
    k1 = kws[0] if kws else "가족"
    k2 = kws[1] if len(kws)>1 else "사연"
    k3 = kws[2] if len(kws)>2 else "반전"

    bases = [
        "무시하던 {k1}, 정체 드러난 그날… 모두 뒤집혔습니다",
        "예비며느리의 한마디 이후 {k2}가 터졌다… 결말은 충격",
        "청소부라 조롱받던 그는 사실 {k1}… 동창회가 얼어붙었습니다",
        "유산 {k3}을 두고 벌어진 가족의 진실게임… 끝은 반전",
        "황혼의 재혼, 숨긴 진실과 {k2}… 마지막에 오열했습니다"
    ]
    thumbs = ["뒤집어버렸습니다","충격적입니다","복수했습니다","상상도 못했습니다","반전 결말"]
    out = []
    for i in range(n):
        base = bases[i % len(bases)]
        out.append({
            "title": base.format(k1=k1, k2=k2, k3=k3),
            "thumb": thumbs[i % len(thumbs)]
        })
    return out[:n]

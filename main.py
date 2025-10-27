import os
from pathlib import Path
from utils.io import OUT_DIR, now_kst, load_yaml, log_fallback, log_summary, log_pick
from utils.emailer import send_email_markdown
from utils.youtube import search_story_candidates, filter_story
from utils.nlp import extract_top_keywords, make_strong_titles_from_keywords

REPORT_PATH=OUT_DIR/"report.md"

def _env():
    need=["YOUTUBE_API_KEY","SMTP_HOST","SMTP_PORT","SMTP_USER","SMTP_PASS","REPORT_EMAIL_TO"]
    miss=[k for k in need if not os.getenv(k)]
    if miss: raise EnvironmentError("NO ENV: "+", ".join(miss))

def load_kw():
    c=load_yaml("config/keywords.yaml").get("story",{})
    return c.get("must_phrases",[]), c.get("include",[]), c.get("exclude",[])

def email_md(videos, kw, titles, note):
    ts=now_kst().strftime("%Y-%m-%d %H:%M")
    L=[
        f"# 시니어 인생스토리 리포트 — {ts}",
        "",
        f"> 기준: 최근 {note} · 필수문구(감동사연 등) · 길이 30~120분",
        "",
        "## A) Top 10"
    ]
    for i,v in enumerate(videos,1):
        url=f"https://www.youtube.com/watch?v={v['id']}"
        m=v['durationSec']//60
        s=v['durationSec']%60
        up=v['publishedAt'].replace("T"," ").replace("Z","")
        L.append(f"{i}. **[{v['title']}]({url})**")
        L.append(f"   - 조회수: {v['views']:,} · {m}:{s:02d} · {v['channel']} · {up}")
    L+=["","## B) 키워드", "- "+", ".join(kw),"","## C) 신규 제목 10개"]
    for t in titles:
        L.append(f"- **{t['title']}** / 썸네일: {t['thumb']}")
    return "\n".join(L)

def main():
    _env()
    must,inc,exc=load_kw()
    plans=[(7,"7일"),(14,"14일"),(21,"21일"),(28,"28일"),(35,"35일")]
    picked=[];seen=set()
    extra="사연 감동 가족 황혼 연애 상속 유산"

    for days,note in plans:
        log_fallback(cat="스토리", step=days, days=days)
        c=search_story_candidates(must,days,extra,max_pages=5)
        k=filter_story(c,must,inc,exc,step=days)
        for v in k:
            if v["id"] in seen: continue
            picked.append(v);seen.add(v["id"]);log_pick(cat="story",video=v)
            if len(picked)>=10: break
        if len(picked)>=10: break

    top10=picked[:10]
    log_summary(cat="story",count=len(top10))

    titles=[v["title"] for v in top10]
    tags=[v.get("tags",[]) for v in top10]
    kws=extract_top_keywords(titles,tags,topk=15)
    new=make_strong_titles_from_keywords(kws,n=10)

    md=email_md(top10,kws,new,note)
    Path(REPORT_PATH).write_text(md,encoding="utf-8")
    send_email_markdown(md,"✅ 시니어 인생스토리 Top10 + 신규제목10")

if __name__=="__main__":
    main()

import os, requests, feedparser
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from .io import log

NEWS_DAYS = int(os.getenv("NEWS_DAYS", "10"))
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

def newsapi_search(query: str, from_days: int):
    url = "https://newsapi.org/v2/everything"
    params = {
        "apiKey": NEWSAPI_KEY,
        "q": query,
        "language": "ko",
        "sortBy": "popularity",
        "pageSize": 50,
        "from": (datetime.utcnow() - timedelta(days=from_days)).date().isoformat(),
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    arts = r.json().get("articles", [])
    out = []
    for a in arts:
        out.append({
            "title": a.get("title"),
            "url": a.get("url"),
            "source": (a.get("source") or {}).get("name"),
            "publishedAt": a.get("publishedAt"),
            "score": 1.0,
        })
    return out

def google_news_rss_search(query: str, days: int):
    url = f"https://news.google.com/rss/search?q={quote(query)}+when:{days}d&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries[:100]:
        title = e.get("title")
        link  = e.get("link")
        source= (e.get("source") or {}).get("title") or (e.get("author") or "")
        pub   = e.get("published_parsed")
        if pub:
            dt = datetime(*pub[:6], tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - dt).days
            recency = max(0.0, 1.0 - (age_days / (days+0.1)))
        else:
            recency = 0.5
        out.append({"title": title, "url": link, "source": source, "score": recency})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out

def fetch_news_topics():
    topics = {
        "시니어 건강": "건강 OR 혈당 OR 당뇨 OR 콜레스테롤 OR 피부 OR 노화 OR 한방 OR 운동 OR 무릎 OR 허리 OR 치매",
        "시니어 북한": "북한 OR 평양 OR 김정은 OR 탈북 OR 제재 OR 미사일",
    }
    out = {}
    for ch, q in topics.items():
        if NEWSAPI_KEY:
            items = newsapi_search(q, NEWS_DAYS); source = "데이터 출처: NewsAPI(인기순)"
        else:
            items = google_news_rss_search(q, NEWS_DAYS); source = "데이터 출처: Google News RSS (NEWSAPI 미사용)"
        seen, uniq = set(), []
        for it in items:
            t = (it["title"] or "").strip()
            if not t or t in seen: continue
            seen.add(t); uniq.append(it)
        out[ch] = {"items": uniq[:3], "source_note": source}
        log(f"뉴스 '{ch}' {len(out[ch]['items'])}개")
    return out

import os, re, requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from .io import log_exclude, log_error

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

DURATION_MIN = 1800   # 30min
DURATION_MAX = 7200   # 120min

CHANNEL_BLACK = ["JTBC","MBC","SBS","YTN","연합뉴스","TV조선","채널A","MBN"]

def _require_key():
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY 없음")

def parse_int(x):
    try: return int(x)
    except: return 0

def parse_duration(iso):
    if not iso or not iso.startswith("PT"): return 0
    h = m = s = 0
    for part in re.findall(r'(\d+H|\d+M|\d+S)', iso):
        if part.endswith('H'): h=int(part[:-1])
        elif part.endswith('M'): m=int(part[:-1])
        elif part.endswith('S'): s=int(part[:-1])
    return h*3600 + m*60 + s

def videos_details(ids):
    if not ids: return []
    url = "https://www.googleapis.com/youtube/v3/videos"
    r = requests.get(url, params={
        "key":YOUTUBE_API_KEY,
        "part":"snippet,statistics,contentDetails",
        "id":",".join(ids[:50])
    }, timeout=30)
    if r.status_code!=200:
        log_error("videos_fail", status=r.status_code, detail=r.text[:120])
        return []
    return r.json().get("items", [])

def _normalize(s):
    s = (s or "").lower()
    s = re.sub(r"[#\s\[\]\(\)\-….,!?\"'`]", "", s)
    return s

def _match_must(title, tags, must_list):
    norm_t = _normalize(title)
    norm_tags = _normalize(" ".join(tags or []))
    return any(m in norm_t or m in norm_tags for m in must_list)

def search_story_candidates(must, days, extra, max_pages=5):
    _require_key()
    published_after = (datetime.utcnow()-timedelta(days=days)).replace(tzinfo=timezone.utc).isoformat()

    or_terms = [f"\"{m}\"" for m in must]
    q = f"({' OR '.join(or_terms)}) {extra}"

    url="https://www.googleapis.com/youtube/v3/search"
    params={
        "key":YOUTUBE_API_KEY,
        "part":"snippet",
        "type":"video",
        "order":"viewCount",
        "publishedAfter":published_after,
        "videoDuration":"long",
        "safeSearch":"none",
        "maxResults":50,
        "q":q
    }

    items=[]
    page=None
    for _ in range(max_pages):
        if page: params["pageToken"]=page
        r=requests.get(url,params=params,timeout=30)
        if r.status_code!=200: break
        data=r.json()
        items+=data.get("items",[])
        page=data.get("nextPageToken")
        if not page: break

    ids=list(dict.fromkeys([i.get("id",{}).get("videoId") for i in items if i.get("id",{}).get("videoId")]))
    det=[]
    for i in range(0,len(ids),50):
        det+=videos_details(ids[i:i+50])

    out=[]
    for d in det:
        sn=d.get("snippet",{})
        st=d.get("statistics",{})
        cd=d.get("contentDetails",{})
        dur=parse_duration(cd.get("duration"))
        out.append({
            "id":d.get("id"),
            "title":sn.get("title"),
            "tags":sn.get("tags",[]) or [],
            "channel":sn.get("channelTitle"),
            "publishedAt":sn.get("publishedAt"),
            "views":parse_int(st.get("viewCount")),
            "durationSec":dur
        })
    out.sort(key=lambda x:x["views"], reverse=True)
    return out

def filter_story(videos, must, include, exclude, step):
    must_norm=[_normalize(m) for m in must]
    exc=[e.lower() for e in exclude]
    keep=[]
    for v in videos:
        t=v["title"] or ""
        tags=v.get("tags",[])
        ch=v.get("channel","")
        low=t.lower()
        Ta=" ".join(tags).lower()
        dur=v["durationSec"]

        if dur<DURATION_MIN or dur>DURATION_MAX:
            log_exclude("duration",v,step=step); continue
        if not any("가"<=c<="힣" for c in t):
            log_exclude("nokr",v,step=step); continue
        if any(b.lower() in ch.lower() for b in CHANNEL_BLACK):
            log_exclude("news",v,step=step); continue
        if any(e in low or e in Ta for e in exc):
            log_exclude("black",v,step=step); continue
        if not _match_must(t,tags,must_norm):
            log_exclude("nomust",v,step=step); continue

        keep.append(v)
    return keep

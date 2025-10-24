import os, re, requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs, unquote
from .io import log

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YT_TOP_DAYS = int(os.getenv("YT_TOP_DAYS", "7"))
LONGFORM_MIN_SECONDS = int(os.getenv("LONGFORM_MIN_SECONDS", "180"))

STRICT_HEALTH = (os.getenv("STRICT_HEALTH","1") == "1")
STRICT_STORY  = (os.getenv("STRICT_STORY","1") == "1")
STRICT_NK     = (os.getenv("STRICT_NK","0") == "1")

def _require_key():
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY가 환경변수에 없습니다. GitHub Secrets로 등록하고 워크플로에서 $GITHUB_ENV로 export하세요.")

def parse_int(x): 
    try: return int(x)
    except: return 0

def parse_iso8601_duration(dur: str) -> int:
    if not dur or not dur.startswith("PT"): return 0
    h = m = s = 0
    for part in re.findall(r'(\d+H|\d+M|\d+S)', dur):
        if part.endswith('H'): h = int(part[:-1])
        elif part.endswith('M'): m = int(part[:-1])
        elif part.endswith('S'): s = int(part[:-1])
    return h*3600 + m*60 + s

def within_days_utc(iso_s: str, days: int) -> bool:
    try:
        dt = datetime.fromisoformat(iso_s.replace("Z","+00:00"))
        return (datetime.now(timezone.utc) - dt) <= timedelta(days=days)
    except: return False

def extract_video_id(url: str):
    try:
        u = urlparse(url)
        if u.netloc in ("youtu.be","www.youtu.be"):
            return u.path.strip("/").split("/")[0]
        if "watch" in u.path:
            return parse_qs(u.query).get("v", [None])[0]
    except:
        return None

def resolve_channel_id(channel_url: str):
    """
    /channel/UCxxxx... → 그대로
    /@핸들 → 한글/인코딩 핸들 디코딩 후 search.list로 channelId 획득
    """
    _require_key()
    u = urlparse(channel_url)
    # 1) 명시적 /channel/UC... 인 경우
    if "/channel/" in u.path:
        return u.path.split("/channel/")[1].split("/")[0]

    # 2) /@handle 케이스 (한글 가능)
    handle = None
    if "/@" in u.path:
        handle = u.path.split("/@")[1].split("/")[0]
        handle = unquote(handle)  # %EB%... → 유니코드 복원

    if handle:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "key": YOUTUBE_API_KEY,
            "part": "snippet",
            "q": f"@{handle}",
            "type": "channel",
            "maxResults": 1
        }
        r = requests.get(url, params=params, timeout=20)
        # 403 등 에러 상황을 로깅하고 None 반환(앵커가 하나 빠져도 전체 파이프라인은 계속)
        if r.status_code != 200:
            log(f"[warn] channel handle resolve 실패 ({handle}) status={r.status_code} detail={r.text[:200]}")
            return None
        items = r.json().get("items",[])
        if items:
            return items[0]["snippet"]["channelId"]
        log(f"[warn] channel handle 검색 결과 없음: @{handle}")
    else:
        log(f"[warn] 채널 URL에서 핸들을 찾지 못했습니다: {channel_url}")

    return None

def videos_details(video_ids, parts="snippet,statistics,contentDetails"):
    if not video_ids: return []
    _require_key()
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"key": YOUTUBE_API_KEY, "part": parts, "id": ",".join(video_ids[:50])}
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json().get("items", [])

def search_recent_by_views(query: str, days: int, max_results=50):
    _require_key()
    published_after = (datetime.utcnow() - timedelta(days=days)).replace(tzinfo=timezone.utc).isoformat()
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY, "part":"snippet", "q":query, "type":"video",
        "order":"viewCount", "publishedAfter": published_after,
        "maxResults": max_results, "relevanceLanguage":"ko",
    }
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    items = r.json().get("items", [])
    ids = [it["id"]["videoId"] for it in items if it.get("id",{}).get("videoId")]
    if not ids: return []
    dets = videos_details(ids)
    out = []
    for d in dets:
        sn = d.get("snippet",{}) or {}
        st = d.get("statistics",{}) or {}
        cd = d.get("contentDetails",{}) or {}
        if sn.get("liveBroadcastContent") and sn.get("liveBroadcastContent")!="none":
            continue
        duration = parse_iso8601_duration(cd.get("duration"))
        if duration < LONGFORM_MIN_SECONDS:
            continue
        out.append({
            "id": d.get("id"),
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "channelId": sn.get("channelId"),
            "publishedAt": sn.get("publishedAt"),
            "views": parse_int(st.get("viewCount")),
            "durationSec": duration
        })
    out.sort(key=lambda x: x["views"], reverse=True)
    return out

def build_anchor_profile(channels:list[str], videos:list[str]):
    ch_ids = set()
    for cu in channels or []:
        cid = resolve_channel_id(cu)
        if cid: ch_ids.add(cid)
    titles = []
    vid_ids = []
    for vu in videos or []:
        vid = extract_video_id(vu)
        if vid: vid_ids.append(vid)
    if vid_ids:
        info = videos_details(vid_ids, parts="snippet")
        for d in info:
            sn = d.get("snippet",{}) or {}
            cid = sn.get("channelId")
            if cid: ch_ids.add(cid)
            t = sn.get("title")
            if t: titles.append(t)
    # 간단 키워드 추출
    kw_counts = {}
    for t in titles:
        for tok in re.sub(r"[^\w가-힣 ]"," ", t).split():
            if len(tok)<2: continue
            kw_counts[tok] = kw_counts.get(tok,0)+1
    keywords = set([w for w,_ in sorted(kw_counts.items(), key=lambda x:x[1], reverse=True)[:20]])
    return {"channels": ch_ids, "keywords": keywords}

def score_by_anchor(video, anchor, kw_include):
    score = 0
    if video.get("channelId") in anchor["channels"]:
        score += 5
    title = (video.get("title") or "").lower()
    if any(k.lower() in title for k in (anchor["keywords"] or [])):
        score += 2
    if any(k.lower() in title for k in (kw_include or [])):
        score += 1
    return score

def filter_and_rank(videos, anchor, inc_keywords, exc_keywords, strict=False, need=5):
    scored = []
    for v in videos:
        title = (v.get("title") or "").lower()
        if any(ex.lower() in title for ex in (exc_keywords or [])):
            continue
        s = score_by_anchor(v, anchor, inc_keywords or [])
        if strict and s == 0:
            continue
        scored.append((s, v))
    scored.sort(key=lambda sv: (sv[0], sv[1]["views"]), reverse=True)
    picked = [v for _,v in scored][:need]
    if len(picked)<need and not strict:
        seen = {v["id"] for v in picked}
        for v in videos:
            t = (v.get("title") or "").lower()
            if any(ex.lower() in t for ex in (exc_keywords or [])): continue
            if v["id"] in seen: continue
            picked.append(v); seen.add(v["id"])
            if len(picked)>=need: break
    return picked[:need]

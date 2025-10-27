import os, re, requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs, unquote
from .io import log_event, log_warn, log_error, log_exclude

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YT_TOP_DAYS = int(os.getenv("YT_TOP_DAYS", "7"))

# 카테고리별 길이 하한/상한(초)
DURATION_RULES = {
    "시니어 건강": (1200, 2400),    # 20~40분
    "시니어 인생스토리": (1800, 7200),  # 30~120분
    "시니어 북한": (1800, 7200),    # 30~120분
}

def _require_key():
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY가 환경변수에 없습니다.")

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
    _require_key()
    u = urlparse(channel_url)
    if "/channel/" in u.path:
        return u.path.split("/channel/")[1].split("/")[0]
    handle = None
    if "/@" in u.path:
        handle = unquote(u.path.split("/@")[1].split("/")[0])
    if handle:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"key": YOUTUBE_API_KEY, "part":"snippet", "q":f"@{handle}", "type":"channel", "maxResults":1}
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200:
            log_warn("handle resolve 실패", handle=handle, status=r.status_code, detail=r.text[:200])
            return None
        items = r.json().get("items",[])
        if items: return items[0]["snippet"]["channelId"]
        log_warn("handle 검색 결과 없음", handle=handle)
        return None
    log_warn("채널 URL에서 핸들을 찾지 못함", url=channel_url)
    return None

def videos_details(video_ids, parts="snippet,statistics,contentDetails"):
    if not video_ids: return []
    _require_key()
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"key": YOUTUBE_API_KEY, "part": parts, "id": ",".join(video_ids[:50])}
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        log_error("videos.list 실패", status=r.status_code, detail=r.text[:200])
        r.raise_for_status()
    return r.json().get("items", [])

def search_recent_by_views(query: str, days: int, max_results=100):
    _require_key()
    published_after = (datetime.utcnow() - timedelta(days=days)).replace(tzinfo=timezone.utc).isoformat()
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY, "part":"snippet", "q":query, "type":"video",
        "order":"viewCount", "publishedAfter": published_after,
        "maxResults": max_results, "relevanceLanguage":"ko",
    }
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        log_error("search.list 실패", status=r.status_code, detail=r.text[:200])
        r.raise_for_status()
    items = r.json().get("items", [])
    ids = [it.get("id",{}).get("videoId") for it in items if it.get("id",{}).get("videoId")]
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

def _contains_korean(text:str)->bool:
    return bool(re.search(r"[가-힣]", text or ""))

def apply_category_rules(cat:str, videos:list, include:list, exclude:list):
    """길이/한글/블랙리스트/화이트리스트(필수1+) + 건강 ‘한방’ 동시등장 규칙. 모두 로그 남김."""
    inc = [w.lower() for w in (include or [])]
    exc = [w.lower() for w in (exclude or [])]
    dmin, dmax = DURATION_RULES.get(cat, (0, 10**9))

    # 건강 핵심어(한방 중의성 방지용 co-occurrence)
    health_core = {
        "혈당","당뇨","콜레스테롤","고혈압","중성지방","치매",
        "관절","무릎","허리","통증","수면","불면","단백질","근감소증",
        "루틴","식단","운동","소화","위","장","간","신장","비타민","오메가3"
    }
    health_core_low = {w.lower() for w in health_core}

    kept = []
    for v in videos:
        title = (v.get("title") or "")
        t_low = title.lower()
        dur = v.get("durationSec") or 0

        # 길이
        if dur < dmin:
            log_exclude(cat, "duration_short", v); continue
        if dur > dmax:
            log_exclude(cat, "duration_long", v); continue

        # 한글 포함
        if not _contains_korean(title):
            log_exclude(cat, "non_korean_title", v); continue

        # 블랙리스트 즉시 제외
        if any(x in t_low for x in exc):
            log_exclude(cat, "blacklist_match", v); continue

        # 화이트리스트(필수 1+)
        if inc and not any(x in t_low for x in inc):
            log_exclude(cat, "no_whitelist_keyword", v); continue

        # 건강: '한방/한의사/약초/차' 중의성 방지 — 의료 핵심어 동반 요구
        if cat == "시니어 건강":
            if any(tok in t_low for tok in ["한방","한의사","약초"," 탕"," 차 ","경혈","침","뜸","보약","한약"]):
                if not any(core in t_low for core in health_core_low):
                    log_exclude(cat, "hanbang_without_medical_core", v); continue

        kept.append(v)
    return kept

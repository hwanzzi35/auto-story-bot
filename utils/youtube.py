import os, re, requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs
from .io import log_warn, log_error, log_exclude

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# 인생스토리 길이: 30~120분
DURATION_MIN = 1800
DURATION_MAX = 7200

def _require_key():
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY 환경변수 없음")

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

def search_story_candidates(query: str, days: int, max_results=50):
    """최근 N일, 조회수순 후보 수집 → details로 확장"""
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
            "tags": sn.get("tags", []) or [],
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "views": parse_int(st.get("viewCount")),
            "durationSec": duration
        })
    out.sort(key=lambda x: x["views"], reverse=True)
    return out

def _contains_korean(text:str)->bool:
    return bool(re.search(r"[가-힣]", text or ""))

def filter_story(videos: list, must_phrases: list, include_words: list, exclude_words: list, step:int):
    """길이/한글/블랙/필수문구 검사. 제외 사유 전부 로깅."""
    must = [w.lower() for w in (must_phrases or [])]
    inc  = [w.lower() for w in (include_words or [])]
    exc  = [w.lower() for w in (exclude_words or [])]

    kept = []
    for v in videos:
        title = (v.get("title") or "")
        tags = v.get("tags") or []
        t_low = title.lower()
        tags_low = " ".join(tags).lower()
        dur = v.get("durationSec") or 0

        if dur < DURATION_MIN:
            log_exclude("duration_short", v, step=step); continue
        if dur > DURATION_MAX:
            log_exclude("duration_long", v, step=step); continue
        if not _contains_korean(title):
            log_exclude("non_korean_title", v, step=step); continue
        if any(x in t_low for x in exc) or any(x in tags_low for x in exc):
            log_exclude("blacklist_match", v, step=step); continue
        # 필수 문구: 제목 또는 태그 중 1개 이상
        if must and not (any(x in t_low for x in must) or any(x in tags_low for x in must)):
            log_exclude("no_must_phrase", v, step=step); continue

        kept.append(v)
    return kept

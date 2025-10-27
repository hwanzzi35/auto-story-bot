import os, re, requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
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

def _normalize(s: str) -> str:
    """#, 공백, 괄호/기호 제거 후 소문자. (라디오 사연 == 라디오사연 == #라디오사연)"""
    if not s: return ""
    s = s.lower()
    s = re.sub(r"[#\[\]\(\)<>【】『』〈〉\-–—_|@:~·•….,!?\"'`/\\]", " ", s)
    s = re.sub(r"\s+", "", s)
    return s

def _build_must_regex(must_phrases: list[str]):
    """필수 문구를 '공백 무시' 규칙으로 매칭할 정규식 세트 구성"""
    regs = []
    for p in (must_phrases or []):
        p_norm = _normalize(p)
        if not p_norm: continue
        regs.append(re.compile(re.escape(p_norm)))
    return regs

def _match_must(title: str, tags: list[str], must_regs):
    t = _normalize(title)
    tg = _normalize(" ".join(tags or []))
    for rg in must_regs:
        if rg.search(t) or rg.search(tg):
            return True
    return False

def search_story_candidates(must_phrases: list[str], days: int, base_extra_query: str = "", max_pages: int = 5):
    """
    검색 결과를 pages 만큼 모아서 candidates 반환.
    - 검색어: (must OR ...) + base_extra_query
    - 정렬: viewCount
    - 기간: publishedAfter = now- days
    - 길이: videoDuration=long (20분 이상, 이후 30~120분으로 재필터)
    """
    _require_key()
    published_after = (datetime.utcnow() - timedelta(days=days)).replace(tzinfo=timezone.utc).isoformat()

    # 필수문구 OR 묶음 (큰따옴표로 정확도 향상 + 공백/기호 변형은 후처리로 커버)
    or_terms = [f"\"{p}\"" for p in (must_phrases or []) if p]
    must_block = "(" + " OR ".join(or_terms) + ")" if or_terms else ""
    query = f"{must_block} {base_extra_query}".strip()

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "publishedAfter": published_after,
        "maxResults": 50,              # 페이지 당 최대
        "relevanceLanguage": "ko",
        "videoDuration": "long",       # 20분 이상
        "safeSearch": "none",
    }

    items = []
    page_token = None
    for _ in range(max_pages):
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            log_error("search.list 실패", status=r.status_code, detail=r.text[:200])
            r.raise_for_status()
        data = r.json()
        items.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    ids = [it.get("id",{}).get("videoId") for it in items if it.get("id",{}).get("videoId")]
    ids = list(dict.fromkeys(ids))  # 중복 제거, 순서 유지
    if not ids: return []

    # 50개씩 나눠서 details 조회
    details = []
    for i in range(0, len(ids), 50):
        details.extend(videos_details(ids[i:i+50]))

    out = []
    for d in details:
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
    """
    길이/한글/블랙/필수문구 검사. 제외 사유 전부 로깅.
    - 필수문구는 '공백/기호 무시' 정규화로 매칭
    """
    must_regs = _build_must_regex(must_phrases or [])
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

        # 필수 문구: 제목 또는 태그에 1개 이상 (정규화 매칭)
        if must_regs and not _match_must(title, tags, must_regs):
            log_exclude("no_must_phrase", v, step=step); continue

        kept.append(v)
    return kept

import os
import csv
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
import math
import statistics

# =========================
# 환경변수 / 경로
# =========================
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
SMTP_HOST       = os.getenv("SMTP_HOST")
SMTP_PORT       = os.getenv("SMTP_PORT")
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASS       = os.getenv("SMTP_PASS")
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")

RISING_SORT_MODE = (os.getenv("RISING_SORT_MODE", "percent") or "percent").lower()
EXTRA_ARCHETYPES_JSON = os.getenv("EXTRA_ARCHETYPES_JSON", "")
EXTRA_KEYWORDS_JSON   = os.getenv("EXTRA_KEYWORDS_JSON", "")

OUT_DIR     = Path("data/outputs")
HIST_DIR    = Path("data/history")      # 월간 PDF용 집계에 활용
REPORT_PATH = OUT_DIR / "weekly_report.md"

# =========================
# 공통 유틸
# =========================
def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))  # KST

def ensure_dirs():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HIST_DIR.mkdir(parents=True, exist_ok=True)

def send_email_markdown(body: str, subject: str):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and REPORT_EMAIL_TO):
        raise EnvironmentError("SMTP 환경변수가 누락되었습니다.")
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_USER
    msg["To"]   = REPORT_EMAIL_TO
    with smtplib.SMTP(SMTP_HOST, int(SMTP_PORT)) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [REPORT_EMAIL_TO], msg.as_string())

def parse_int(x):
    try: return int(x)
    except: return 0

def iso_utc(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()

def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    ensure_dirs()
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

# =========================
# 기준값
# =========================
DAYS_WINDOW_MONTH = 30           # 한달 분석
MIN_VIEWS_MONTH   = 100_000

CURRENT_DAYS  = 7                # 최근 7일
PREVIOUS_DAYS = 7                # 그 전 7일

SENIOR_QUERY = "시니어 OR 노년 OR 어르신 OR 50대 OR 60대 OR 중장년"

NEW_TOPIC_RULES = {
    "재테크/연금/퇴직": ["연금","퇴직","노후","재테크","배당","주식","ETF","연금저축","퇴직연금","국민연금"],
    "부동산/임대": ["부동산","아파트","전세","월세","임대","청약","등기"],
    "의학정보/병원": ["치매","골다공증","허리","무릎","척추","고혈압","고지혈","관상동맥","검진","병원","의사","수술"],
    "요리/집밥/레시피": ["반찬","국","찌개","김치","집밥","요리","레시피","전통","된장","간장","건강식","밑반찬"],
    "취미/여가/여행": ["등산","낚시","여행","캠핑","트레킹","정원","텃밭","원예","풍경","꽃"],
    "노래/트로트/향수": ["트로트","7080","가요","명곡","노래방","추억","콘서트"],
    "법/상속/복지": ["상속","유언","증여","의료비","장기요양","요양","연금공단","복지","기초연금"],
    "스마트폰/생활IT": ["스마트폰","휴대폰","핸드폰","카카오톡","유튜브 사용법","사진 정리","폰 설정","QR","앱 설치"],
}
BASE_3 = {"시니어 건강","시니어 북한","시니어 인생스토리"}

KEYWORDS = {
    "연금": ["연금","국민연금","퇴직연금","연금저축"],
    "부동산": ["부동산","아파트","전세","월세","임대","청약"],
    "건강/병원": ["치매","허리","무릎","척추","고혈압","당뇨","콜레스테롤","검진","병원","의사","수술"],
    "요리/레시피": ["요리","레시피","반찬","국","찌개","집밥","밑반찬","전통"],
    "트로트/7080": ["트로트","7080","가요","명곡","노래","노래방"],
    "여행/여가": ["여행","캠핑","등산","낚시","트레킹"],
    "법/상속/복지": ["상속","유언","증여","복지","기초연금","장기요양","요양"],
    "스마트폰/생활IT": ["스마트폰","휴대폰","핸드폰","카카오톡","폰","QR","설정","사진 정리","앱"],
    "북한/시사": ["북한","평양","김정은","미사일","제재","북러","북중","안보","탈북"],
    "인생사연/감동": ["사연","썰","감동","반전","가족","며느리","시어머니","고부","눈물","드라마"],
}

# ===== 사용자 확장 병합 (선택) =====
def merge_json(target: dict, extra_json: str):
    if not extra_json:
        return
    try:
        data = json.loads(extra_json)
        for k, v in data.items():
            if not isinstance(v, list): continue
            base = target.get(k, [])
            merged = base + [x for x in v if x not in base]
            target[k] = merged
    except Exception:
        pass

merge_json(NEW_TOPIC_RULES, EXTRA_ARCHETYPES_JSON)
merge_json(KEYWORDS, EXTRA_KEYWORDS_JSON)

# =========================
# YouTube API helpers
# =========================
def youtube_videos_details(video_ids):
    if not video_ids:
        return []
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet,statistics",
        "id": ",".join(video_ids[:50])
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("items", [])

def youtube_search_recent(query, published_after, published_before=None, order="viewCount", max_results=50):
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": order,
        "publishedAfter": published_after,
        "maxResults": max_results,
        "relevanceLanguage": "ko",
    }
    if published_before:
        params["publishedBefore"] = published_before

    r = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
    if not ids:
        return []
    details = youtube_videos_details(ids)
    detail_map = {d["id"]: d for d in details}

    merged = []
    for it in items:
        vid = it["id"]["videoId"]
        sn  = it.get("snippet", {})
        d   = detail_map.get(vid)
        if not d: continue
        merged.append({
            "id": vid,
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "views": parse_int((d.get("statistics") or {}).get("viewCount")),
            "desc": sn.get("description","")
        })
    return merged

# =========================
# 분석 로직
# =========================
def label_new_topic(title, desc):
    text = f"{title or ''} {desc or ''}".lower()
    for t, kws in NEW_TOPIC_RULES.items():
        for kw in kws:
            if kw.lower() in text:
                return t
    return None

def count_keywords(videos):
    counts = defaultdict(int)
    buckets = defaultdict(list)
    for v in videos:
        text = f"{v['title'] or ''} {v.get('desc','') or ''}".lower()
        for key, kw_list in KEYWORDS.items():
            if any(kw.lower() in text for kw in kw_list):
                counts[key] += 1
                buckets[key].append(v)
    return counts, buckets

def title_pattern_stats(videos):
    """
    상위 영상 title 기반 패턴/길이 통계.
    썸네일 텍스트 길이는 title 길이로 근사(외부 OCR 없이 가볍게 운영).
    """
    patterns = {
        "has_number": 0,
        "has_brackets": 0,   # (), [], 【】, 『』
        "has_exclaim": 0,    # !, ?!?!
        "has_shocking": 0,   # 충격, 경악, 소름, 역대급 등
    }
    shocking_words = ["충격", "경악", "소름", "경악", "역대급", "말문이", "충…", "헉", "충격적"]
    lengths_char = []
    lengths_word = []

    for v in videos:
        t = (v["title"] or "").strip()
        if not t: continue
        if any(ch.isdigit() for ch in t): patterns["has_number"] += 1
        if any(b in t for b in ["(",")","[","]","【","】","『","』","〈","〉","<",">"]): patterns["has_brackets"] += 1
        if "!" in t or "?" in t: patterns["has_exclaim"] += 1
        if any(w in t for w in shocking_words): patterns["has_shocking"] += 1
        lengths_char.append(len(t))
        lengths_word.append(len(t.split()))

    total = max(1, len(videos))
    stats = {
        "ratio_number": round(patterns["has_number"]/total*100, 1),
        "ratio_brackets": round(patterns["has_brackets"]/total*100, 1),
        "ratio_exclaim": round(patterns["has_exclaim"]/total*100, 1),
        "ratio_shocking": round(patterns["has_shocking"]/total*100, 1),
        "avg_len_char": round(statistics.mean(lengths_char), 1) if lengths_char else 0.0,
        "avg_len_word": round(statistics.mean(lengths_word), 1) if lengths_word else 0.0,
    }
    return stats

def suggest_title_templates(stats):
    """
    통계 기반 추천 템플릿 3개.
    숫자/괄호/감탄사/충격어 비율에 따라 가중합성 제공.
    """
    templates = []
    # 1) 숫자 + 괄호형
    if stats["ratio_number"] >= 30 and stats["ratio_brackets"] >= 30:
        templates.append("({키워드}) {숫자}가지 핵심 | {핵심혜택} 한 번에 정리!")
    else:
        templates.append("{키워드} 핵심 {숫자}가지 | {한줄효과} (초보도 쉽게)")

    # 2) 감탄사 강조형
    if stats["ratio_exclaim"] >= 40 or stats["ratio_shocking"] >= 20:
        templates.append("“{강조문구}!” {키워드} 이것만 알면 됩니다")
    else:
        templates.append("{키워드} 시작 전 꼭 알아야 할 3가지")

    # 3) 길이 최적화형 (avg_len_word 기준)
    if stats["avg_len_word"] >= 9:
        templates.append("{키워드} 완전정복: {핵심요약} | {숫자}분 요약")
    else:
        templates.append("{키워드} 한눈에 끝! {핵심요약}")

    # 중복 제거 후 3개 제한
    out = []
    seen = set()
    for t in templates:
        if t not in seen:
            out.append(t); seen.add(t)
        if len(out) >= 3: break
    return out

def difficulty_from_ratio(ratio):
    if ratio >= 0.35: return "쉬움"   # 상위권 진입률 높음 → 진입 쉬움
    if ratio >= 0.2:  return "보통"
    return "어려움"

# =========================
# 리포트 생성 (MD + CSV + 히스토리 저장)
# =========================
def build_weekly_markdown_and_csv():
    ensure_dirs()
    now = datetime.utcnow()

    # 최근 30일 (신규 주제 & 경쟁도용 & Top5)
    month_after = iso_utc(now - timedelta(days=DAYS_WINDOW_MONTH))
    month_videos = youtube_search_recent(SENIOR_QUERY, month_after, order="viewCount", max_results=50)
    month_videos = [v for v in month_videos if v["views"] >= MIN_VIEWS_MONTH]

    # 신규 유망 주제 (기존 3개 제외)
    topic_bucket = {}
    for v in month_videos:
        t = label_new_topic(v["title"], v["desc"])
        if not t:
            continue
        topic_bucket.setdefault(t, []).append(v)

    topic_recos = []
    for t, lst in topic_bucket.items():
        best = max(lst, key=lambda x: x["views"])
        topic_recos.append((t, best))
    topic_recos.sort(key=lambda tb: tb[1]["views"], reverse=True)
    topic_recos = topic_recos[:5]

    top5 = sorted(month_videos, key=lambda x: x["views"], reverse=True)[:5]

    # 제목/썸네일(근사치) 벤치마킹: 상위 20개 기준
    top20 = sorted(month_videos, key=lambda x: x["views"], reverse=True)[:20]
    tstats = title_pattern_stats(top20)
    title_templates = suggest_title_templates(tstats)

    # 경쟁도: 상위권(Top 20% by views) 기준 진입률
    if month_videos:
        cutoff_index = max(1, math.floor(len(month_videos) * 0.2) - 1)
        view_sorted = sorted(month_videos, key=lambda x: x["views"], reverse=True)
        cutoff_views = view_sorted[cutoff_index]["views"]
    else:
        cutoff_views = float("inf")

    archetype_counts = defaultdict(int)
    archetype_top_hits = defaultdict(int)
    for v in month_videos:
        text = f"{v['title'] or ''} {v.get('desc','') or ''}".lower()
        hits = []
        for t, kws in NEW_TOPIC_RULES.items():
            if any(kw.lower() in text for kw in kws):
                hits.append(t)
        for t in set(hits):
            archetype_counts[t] += 1
            if v["views"] >= cutoff_views:
                archetype_top_hits[t] += 1

    competition_rows = []
    for t, cnt in sorted(archetype_counts.items(), key=lambda x: x[1], reverse=True):
        top = archetype_top_hits.get(t, 0)
        ratio = (top / cnt) if cnt else 0.0
        competition_rows.append({
            "archetype": t,
            "uploads": cnt,
            "top_hits": top,
            "top_ratio": round(ratio, 3),
            "difficulty": difficulty_from_ratio(ratio),
        })

    # ====== 급상승 키워드 (7일 vs 직전 7일) ======
    cur_after = iso_utc(now - timedelta(days=CURRENT_DAYS))
    cur_videos = youtube_search_recent(SENIOR_QUERY, cur_after, order="date", max_results=50)

    prev_after = iso_utc(now - timedelta(days=CURRENT_DAYS + PREVIOUS_DAYS))
    prev_before = iso_utc(now - timedelta(days=CURRENT_DAYS))
    prev_videos = youtube_search_recent(SENIOR_QUERY, prev_after, published_before=prev_before, order="date", max_results=50)

    cur_counts, cur_buckets = count_keywords(cur_videos)
    prev_counts, _         = count_keywords(prev_videos)

    growth = []
    for key in KEYWORDS.keys():
        cur = cur_counts.get(key, 0)
        prev = prev_counts.get(key, 0)
        delta = cur - prev
        if cur == 0 and prev == 0:
            continue
        if prev == 0 and cur > 0:
            change_pct = None  # NEW
        else:
            change_pct = ((cur - prev) / prev) * 100 if prev > 0 else None
        rep = None
        if cur_buckets.get(key):
            rep = max(cur_buckets[key], key=lambda x: x["views"])
        growth.append({
            "keyword": key,
            "current_count": cur,
            "previous_count": prev,
            "delta": delta,
            "change_pct": (round(change_pct, 1) if change_pct is not None else None),
            "rep_title": rep["title"] if rep else "",
            "rep_url": f"https://www.youtube.com/watch?v={rep['id']}" if rep else "",
            "rep_views": rep["views"] if rep else "",
            "rep_channel": rep["channel"] if rep else "",
        })

    def sort_key_percent(g):
        is_new = 1 if (g["previous_count"] == 0 and g["current_count"] > 0) else 0
        pct = g["change_pct"] if g["change_pct"] is not None else 9999.0
        return (is_new, pct, g["delta"], g["current_count"])

    def sort_key_delta(g):
        return (g["delta"], g["current_count"], g["change_pct"] if g["change_pct"] is not None else 0)

    if RISING_SORT_MODE == "percent":
        growth.sort(key=sort_key_percent, reverse=True)
    else:
        growth.sort(key=sort_key_delta, reverse=True)

    rising_top3 = growth[:3]

    # =========================
    # CSV 저장 + 주별 히스토리 스냅샷
    # =========================
    write_csv(
        OUT_DIR / "weekly_topics.csv",
        rows=[{"topic": t, "example_title": v["title"], "example_url": f"https://www.youtube.com/watch?v={v['id']}", "views": v["views"], "channel": v["channel"]} for t, v in topic_recos],
        fieldnames=["topic","example_title","example_url","views","channel"]
    )
    write_csv(
        OUT_DIR / "weekly_top5_videos.csv",
        rows=[{"rank": i+1, "title": v["title"], "url": f"https://www.youtube.com/watch?v={v['id']}", "views": v["views"], "channel": v["channel"]} for i, v in enumerate(top5)],
        fieldnames=["rank","title","url","views","channel"]
    )
    write_csv(
        OUT_DIR / "weekly_rising_keywords.csv",
        rows=rising_top3,
        fieldnames=["keyword","current_count","previous_count","delta","change_pct","rep_title","rep_url","rep_views","rep_channel"]
    )
    write_csv(
        OUT_DIR / "weekly_archetype_competition.csv",
        rows=competition_rows,
        fieldnames=["archetype","uploads","top_hits","top_ratio","difficulty"]
    )
    write_csv(
        OUT_DIR / "weekly_title_patterns.csv",
        rows=[tstats],
        fieldnames=list(tstats.keys())
    )

    # 히스토리 스냅샷 저장 (월간 PDF용)
    stamp = now_kst().strftime("%Y%m%d")
    hist_dir = HIST_DIR / stamp
    hist_dir.mkdir(parents=True, exist_ok=True)
    for name in [
        "weekly_topics.csv",
        "weekly_top5_videos.csv",
        "weekly_rising_keywords.csv",
        "weekly_archetype_competition.csv",
        "weekly_title_patterns.csv",
    ]:
        (hist_dir / name).write_text((OUT_DIR / name).read_text(encoding="utf-8-sig"), encoding="utf-8-sig")

    # =========================
    # 메일 본문(MD)
    # =========================
    lines = [
        f"# Weekly Senior Trends Report — {now_kst().strftime('%Y-%m-%d %H:%M (KST)')}",
        "",
        f"기준: 최근 {DAYS_WINDOW_MONTH}일 · 조회수 ≥ {MIN_VIEWS_MONTH:,} · 검색어: {SENIOR_QUERY}",
        "",
        "## 1) 신규 유망 주제 Top 5 (기존 3개 제외)",
    ]
    if topic_recos:
        for i, (t, v) in enumerate(topic_recos, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            lines += [
                f"{i}. **{t}**",
                f"   - 예시: [{v['title']}]({url}) · 조회수 {v['views']:,} · 채널 {v['channel']}",
                ""
            ]
    else:
        lines += ["- (이번 주 신규 유망 주제 없음)", ""]

    lines += ["## 2) 최근 30일 Top 5 영상 (조회수순)"]
    if top5:
        for i, v in enumerate(top5, 1):
            url = f"https://www.youtube.com/watch?v={v['id']}"
            lines.append(f"{i}. [{v['title']}]({url}) · 조회수 {v['views']:,} · 채널 {v['channel']}")
        lines.append("")
    else:
        lines += ["- (해당 조건의 상위 영상 없음)", ""]

    lines += [
        f"## 3) 주간 급상승 키워드 TOP3 (최근 7일 vs 그 전 7일 · 정렬: {RISING_SORT_MODE})",
        "- 산정: 제목/설명 키워드 출현 수 비교 (변화율 %, 또는 NEW/증가 개수)",
        ""
    ]
    if rising_top3:
        for i, g in enumerate(rising_top3, 1):
            change_str = "NEW" if (g["previous_count"] == 0 and g["current_count"] > 0) else f"{g['change_pct']}%"
            rep_line = f"\n   - 대표 영상: [{g['rep_title']}]({g['rep_url']}) · 조회수 {g['rep_views']:,} · 채널 {g['rep_channel']}" if g["rep_url"] else ""
            lines.append(f"{i}. **{g['keyword']}** — 이번주 {g['current_count']} / 지난주 {g['previous_count']} · Δ {g['delta']:+d} · 변화율 {change_str}{rep_line}")
        lines.append("")
    else:
        lines += ["- (급상승 키워드 없음)", ""]

    # 제목/썸네일 벤치마킹 + 템플릿
    lines += [
        "## 4) 제목/썸네일 벤치마킹 & 금주 추천 제목 템플릿",
        f"- 숫자 포함 비율: {tstats['ratio_number']}% · 괄호 사용 비율: {tstats['ratio_brackets']}%",
        f"- 감탄/의문 사용 비율: {tstats['ratio_exclaim']}% · ‘충격/역대급’ 류 사용 비율: {tstats['ratio_shocking']}%",
        f"- 평균 제목 길이(글자): {tstats['avg_len_char']} · 평균 단어 개수: {tstats['avg_len_word']}",
        "",
        "### 추천 템플릿 3개",
    ] + [f"- {tpl}" for tpl in title_templates] + [""]

    # 경쟁도 지표
    lines += ["## 5) 카테고리별 경쟁도 (최근 30일, 상위 20% 진입률 기준)"]
    if competition_rows:
        for r in sorted(competition_rows, key=lambda x: x["top_ratio"], reverse=True):
            lines.append(f"- {r['archetype']}: 업로드 {r['uploads']} · 상위권 {r['top_hits']} · 진입률 {round(r['top_ratio']*100,1)}% → **{r['difficulty']}**")
        lines.append("")
    else:
        lines += ["- (자료 없음)", ""]

    md = "\n".join(lines)
    REPORT_PATH.write_text(md, encoding="utf-8")
    return md

# =========================
# 메인
# =========================
def main():
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY 가 없습니다. Secrets에 추가하세요.")
    md = build_weekly_markdown_and_csv()
    subject = "✅ Weekly Senior Trends Report — 신규 주제/Top5/급상승/제목벤치/경쟁도"
    send_email_markdown(md, subject)

if __name__ == "__main__":
    main()

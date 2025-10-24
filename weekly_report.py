import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

# =========================
# 환경변수
# =========================
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
SMTP_HOST       = os.getenv("SMTP_HOST")
SMTP_PORT       = os.getenv("SMTP_PORT")
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASS       = os.getenv("SMTP_PASS")
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")

REPORT_PATH = "data/outputs/weekly_report.md"

# =========================
# 공통 유틸
# =========================
def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))  # KST

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

# =========================
# 기준값
# =========================
# 주간(월요일 발송) 기본
DAYS_WINDOW_MONTH = 30           # 한달 분석
MIN_VIEWS_MONTH   = 100_000

# 급상승 키워드 분석용
CURRENT_DAYS = 7                 # 최근 7일
PREVIOUS_DAYS = 7                # 그 전 7일

# 검색 쿼리 (시니어 타깃)
SENIOR_QUERY = "시니어 OR 노년 OR 어르신 OR 50대 OR 60대 OR 중장년"

# 신규 유망 주제 라벨 (기존 3대 주제 제외용 아키타입)
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

# 기존 3개 큰 주제(분리 목적)
BASE_3 = {"시니어 건강","시니어 북한","시니어 인생스토리"}

# 급상승 키워드 후보(동의어 포함)
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

# =========================
# YouTube API helpers
# =========================
def youtube_videos_details(video_ids):
    """videos.list 로 snippet, statistics 조회 (최대 50개)"""
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
    """search.list 로 기간/쿼리 기반 검색 후 videos.list로 viewCount 등 상세 합치기"""
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": order,  # viewCount, date 등
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
        if not d:
            continue
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
    """영상 리스트에서 KEYWORDS 사전에 정의된 키워드별 등장 건수를 집계"""
    counts = defaultdict(int)
    buckets = defaultdict(list)  # 키워드별 영상 모음(대표 영상 뽑기용)
    for v in videos:
        text = f"{v['title'] or ''} {v.get('desc','') or ''}".lower()
        for key, kw_list in KEYWORDS.items():
            if any(kw.lower() in text for kw in kw_list):
                counts[key] += 1
                buckets[key].append(v)
    return counts, buckets

def build_weekly_section():
    """주간 리포트 전체 본문 구성"""
    now = datetime.utcnow()
    # 최근 30일(신규 유망 주제 & Top5)
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

    # ====== 주간 급상승 키워드 (최근 7일 vs 그 전 7일) ======
    # 최근 7일
    cur_after = iso_utc(now - timedelta(days=CURRENT_DAYS))
    cur_videos = youtube_search_recent(SENIOR_QUERY, cur_after, order="date", max_results=50)

    # 그 전 7일 (8~14일 전)
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
            change = "NEW"
        else:
            change = f"{((cur - prev) / prev) * 100:.0f}%"
        # 대표 영상(최근 7일 중 해당 키워드 포함 영상들에서 조회수 최고)
        rep = None
        if cur_buckets.get(key):
            rep = max(cur_buckets[key], key=lambda x: x["views"])
        growth.append((key, cur, prev, delta, change, rep))

    # 증가폭 우선 정렬 (delta, cur 둘 다 고려)
    growth.sort(key=lambda x: (x[3], x[1]), reverse=True)
    rising_top3 = growth[:3]

    # ====== 연령대별 선호 콘텐츠(추정) ======
    # 실제 연령 데이터는 없으므로, 아키타입 카테고리 비중으로 추정
    archetype_counts = defaultdict(int)
    for v in month_videos:
        text = f"{v['title'] or ''} {v.get('desc','') or ''}".lower()
        for t, kws in NEW_TOPIC_RULES.items():
            if any(kw.lower() in text for kw in kws):
                archetype_counts[t] += 1

    # 50대 성향(추정): 재테크/부동산/스마트폰
    seg_50 = ["재테크/연금/퇴직","부동산/임대","스마트폰/생활IT"]
    # 60~70대 성향(추정): 요리/트로트/여가/의학/법·복지
    seg_6070 = ["요리/집밥/레시피","노래/트로트/향수","취미/여가/여행","의학정보/병원","법/상속/복지"]

    seg_50_sum = sum(archetype_counts.get(k,0) for k in seg_50)
    seg_6070_sum = sum(archetype_counts.get(k,0) for k in seg_6070)

    # =========================
    # 본문 구성
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
        "## 3) 주간 급상승 키워드 TOP3 (최근 7일 vs 그 전 7일)",
        "- 산정 방식: 제목/설명에 포함된 키워드 출현 수 비교 (성장률 또는 NEW)",
        ""
    ]
    if rising_top3:
        for i, (key, cur, prev, delta, change, rep) in enumerate(rising_top3, 1):
            rep_line = ""
            if rep:
                rep_url = f"https://www.youtube.com/watch?v={rep['id']}"
                rep_line = f"\n   - 대표 영상: [{rep['title']}]({rep_url}) · 조회수 {rep['views']:,} · 채널 {rep['channel']}"
            lines.append(f"{i}. **{key}** — 이번주 {cur}건 / 지난주 {prev}건 · 증감 {delta:+d} · 변화율 {change}{rep_line}")
        lines.append("")
    else:
        lines += ["- (이번 주 뚜렷한 급상승 키워드 없음)", ""]

    lines += [
        "## 4) 연령대별 선호 콘텐츠 차이 (추정)",
        "> ⚠️ YouTube API는 시청자 연령을 제공하지 않습니다. 아래 결과는 **주제 아키타입 분포 기반의 추정**입니다.",
        f"- 50대 성향 지표(재테크/부동산/스마트폰): **{seg_50_sum}건**",
        f"- 60~70대 성향 지표(요리/트로트/여가/의학/법·복지): **{seg_6070_sum}건**",
        "",
        "### 아키타입 분포 (최근 30일, 건수 기준 상위)",
    ]
    if archetype_counts:
        for t, c in sorted(archetype_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {t}: {c}건")
        lines.append("")
    else:
        lines += ["- (최근 30일 아키타입 매칭 결과 없음)", ""]

    return "\n".join(lines)

# =========================
# 메인
# =========================
def main():
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("YOUTUBE_API_KEY 가 없습니다. Secrets에 추가하세요.")
    md = build_weekly_section()
    Path(REPORT_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(REPORT_PATH).write_text(md, encoding="utf-8")
    subject = "✅ Weekly Senior Trends Report — 신규 유망 주제 + Top5 + 주간 급상승 키워드"
    send_email_markdown(md, subject)

if __name__ == "__main__":
    main()

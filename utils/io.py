from pathlib import Path
from datetime import datetime, timezone, timedelta
import os, json, uuid

# 디렉토리
LOG_DIR = Path("data/logs")
OUT_DIR = Path("data/outputs")
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 설정
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()    # DEBUG/INFO/WARN/ERROR
LOG_JSON  = os.getenv("LOG_JSON", "1") == "1"
TZ = timezone(timedelta(hours=9))
LEVEL_MAP = {"DEBUG":10, "INFO":20, "WARN":30, "ERROR":40}

def now_kst():
    return datetime.now(TZ)

def _enabled(level: str) -> bool:
    return LEVEL_MAP.get(level, 20) >= LEVEL_MAP.get(LOG_LEVEL, 20)

def _files():
    day = now_kst().strftime("%Y%m%d")
    text_file = LOG_DIR / f"run-{day}.log"
    json_file = LOG_DIR / f"run-{day}.jsonl"
    return text_file, json_file

def log_line(level: str, msg: str):
    if not _enabled(level): return
    ts = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}][{level}] {msg}\n"
    print(line, end="")
    text_file, _ = _files()
    with text_file.open("a", encoding="utf-8") as fp:
        fp.write(line)

def log_event(event: str, **fields):
    if not _enabled("INFO"): return
    _, json_file = _files()
    rec = {"ts": now_kst().isoformat(), "event": event, "run_id": os.getenv("RUN_ID") or str(uuid.uuid4())}
    rec.update(fields or {})
    if LOG_JSON:
        with json_file.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # 콘솔 요약
    summary_keys = ("cat","reason","id","title","views","dur","step","days","count","note")
    summary = " ".join(f"{k}={fields.get(k)}" for k in summary_keys if fields.get(k) is not None)
    if summary:
        log_line("INFO", f"{event} {summary}")

# ---- 공용 로거들 (하위호환 포함) ----
def log_warn(msg:str, **kw):
    log_line("WARN", msg); log_event("warn", msg=msg, **kw)

def log_error(msg:str, **kw):
    log_line("ERROR", msg); log_event("error", msg=msg, **kw)

def log_info(msg:str, **kw):
    log_line("INFO", msg); log_event("info", msg=msg, **kw)

def log_exclude(cat_or_reason, video:dict=None, step:int=None, extra:dict=None):
    """
    과거 코드 호환:
    - 새 코드: log_exclude(reason=..., video=..., step=...)
    - 과거 코드: log_exclude(cat, reason, video, step=...) 형태도 있었음
    여기서는 가장 단순한 형태로 reason만 남겨도 동작하게 구성.
    """
    fields = {}
    reason = None
    cat = None
    if isinstance(cat_or_reason, str):
        # 새 코드에서 reason만 주는 경우
        reason = cat_or_reason
    if video:
        fields.update({
            "id": video.get("id"),
            "title": video.get("title"),
            "views": video.get("views"),
            "dur": video.get("durationSec"),
            "channel": video.get("channel")
        })
    if step is not None: fields["step"] = step
    if extra: fields.update(extra)
    if cat: fields["cat"] = cat
    if reason: fields["reason"] = reason
    log_event("exclude", **fields)

# 과거 심볼(호환 목적) — 다른 파일에서 임포트하더라도 에러 안 나게 제공
def log_fallback(cat:str=None, step:int=None, days:int=None, note:str=None):
    log_event("fallback", cat=cat, step=step, days=days, note=note)

def log_summary(cat:str=None, count:int=None, step:int=None):
    log_event("summary", cat=cat, count=count, step=step)

def log_pick(cat:str=None, video:dict=None, step:int=None):
    fields = {"cat":cat, "step":step}
    if video:
        fields.update({"id": video.get("id"), "title": video.get("title"), "views": video.get("views"), "dur": video.get("durationSec")})
    log_event("pick", **fields)

# 설정 로드
def load_yaml(path: str):
    import yaml
    p = Path(path)
    if not p.exists(): return {}
    with p.open(encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}

# 과거 코드 호환용 단일 함수
def log(message: str):
    log_line("INFO", message)

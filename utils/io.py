from pathlib import Path
from datetime import datetime, timezone, timedelta
import yaml

LOG_DIR = Path("data/logs")
OUT_DIR = Path("data/outputs")
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

def log(msg: str):
    ts = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    print(line, end="")
    f = LOG_DIR / f"run-{now_kst().strftime('%Y%m%d')}.log"
    with f.open("a", encoding="utf-8") as fp:
        fp.write(line)

def load_yaml(path: str):
    p = Path(path)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}

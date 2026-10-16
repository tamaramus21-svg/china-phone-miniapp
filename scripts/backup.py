"""Consistent SQLite backup, including a running WAL database. No credentials copied."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Config, BASE_DIR


def backup():
    source = Config.load().database_path
    if not source.is_file():
        raise SystemExit("Database does not exist")
    directory = BASE_DIR / "backups"
    directory.mkdir(exist_ok=True)
    target = directory / ("shop-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3")
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        assert dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    print("Backup created:", target)


if __name__ == "__main__":
    backup()

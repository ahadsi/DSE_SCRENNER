"""Database safety tools. Nothing here deletes or rewrites market data.

    python db_tools.py check     # row counts + date span + safety guard
    python db_tools.py backup    # consistent copy into db/backup/

run_live.py calls guard_and_backup() on every start:
  * one backup per day (last 5 kept; only files in db/backup/ named dse_live_*.db are ever pruned)
  * a high-water mark of daily_bars rows is stored in collector_status;
    if the row count ever drops, a loud warning is printed.
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import database as dbm

TABLES = ["daily_bars", "quotes", "market_snapshots", "scanner_results", "decision_results", "trade_setups"]


def stats():
    p = dbm.DB_PATH
    if not Path(p).exists():
        return None
    con = sqlite3.connect(p)
    out = {"path": str(p), "size_mb": round(Path(p).stat().st_size / 1e6, 2), "tables": {}}
    for t in TABLES:
        try: out["tables"][t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error: out["tables"][t] = None
    try:
        out["daily_symbols"] = con.execute("SELECT COUNT(DISTINCT symbol) FROM daily_bars").fetchone()[0]
        out["daily_min"], out["daily_max"] = con.execute("SELECT MIN(date),MAX(date) FROM daily_bars").fetchone()
    except sqlite3.Error:
        pass
    con.close()
    return out


def backup(keep=5):
    p = Path(dbm.DB_PATH)
    if not p.exists():
        return None
    bdir = p.parent / "backup"; bdir.mkdir(exist_ok=True)
    dest = bdir / f"dse_live_{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(p); dst = sqlite3.connect(dest)
    try: src.backup(dst)
    finally: dst.close(); src.close()
    old = sorted(bdir.glob("dse_live_*.db"))
    for f in old[:-keep]:
        try: f.unlink()
        except OSError: pass
    return dest


def _has_backup_today():
    bdir = Path(dbm.DB_PATH).parent / "backup"
    return bdir.exists() and any(bdir.glob(f"dse_live_{datetime.now():%Y%m%d}_*.db"))


def guard_and_backup():
    s = stats()
    if s is None:
        print("[DB] No existing database yet - a new one will be created (nothing to protect).")
        return
    rows = s["tables"].get("daily_bars") or 0
    print(f"[DB] {s['path']}: daily_bars={rows:,} rows, {s.get('daily_symbols', '?')} symbols, "
          f"{s.get('daily_min')} -> {s.get('daily_max')}, {s['size_mb']} MB")
    if rows and not _has_backup_today():
        d = backup()
        print(f"[DB] Backup saved: {d}")
    dbm.init_db()
    hw = dbm.get_status("daily_bars_rows_high_water")
    try: hw = int(hw) if hw is not None else 0
    except ValueError: hw = 0
    if hw and rows < hw:
        print(f"[DB] WARNING: daily_bars has {rows:,} rows but previously reached {hw:,}. "
              f"Do not continue until you check db/backup/.")
    if rows > hw:
        dbm.set_status("daily_bars_rows_high_water", rows)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "backup":
        print("Backup:", backup())
    else:
        s = stats()
        if s is None: print("Database not found at", dbm.DB_PATH)
        else:
            for k, v in s.items(): print(f"{k}: {v}")

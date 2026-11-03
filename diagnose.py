import sqlite3
from pathlib import Path
from database import DB_PATH
db=Path(DB_PATH)
if not db.exists():
    print("Database not created yet.")
    raise SystemExit
con=sqlite3.connect(db)
for q,label in [
("SELECT COUNT(*) FROM quotes","Live quote rows"),
("SELECT COUNT(*) FROM daily_bars","Historical daily rows"),
("SELECT COUNT(DISTINCT symbol) FROM daily_bars","Historical symbols"),
("SELECT MIN(date),MAX(date) FROM daily_bars","Historical date span"),
("SELECT COUNT(*) FROM decision_results","Decision history rows"),
("SELECT key,value FROM collector_status","Collector status")]:
    print("\n"+label+":")
    for r in con.execute(q): print(r)
con.close()

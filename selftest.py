"""Self-test for V4. Uses a TEMPORARY database - your real db/dse_live.db is never opened.

    python selftest.py

Checks:
  1. an OLD-schema database with 132,903 daily_bars rows survives the V4 migration with every row intact
  2. backup + guard work
  3. indicators, 7 primary gates, Fibonacci zones/targets, scanner and backtest run end to end
"""
import os, sys, shutil, sqlite3, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp(prefix="dse_selftest_"))
os.environ["DSE_DB_PATH"] = str(tmp / "db" / "dse_live.db")
sys.path.insert(0, str(HERE)); os.chdir(tmp)

import numpy as np, pandas as pd
import database as dbm

OLD_DECISION = """CREATE TABLE decision_results (
    ts TEXT NOT NULL, symbol TEXT NOT NULL, legacy_score REAL, decision_score REAL, technical_score REAL,
    fundamental_score REAL, fundamental_status TEXT, action TEXT, entry_quality TEXT, confirmation TEXT,
    breakout_confirmed INTEGER, pullback_confirmed INTEGER, exit_signal TEXT, market_stress REAL, market_regime TEXT,
    ltp REAL, rsi REAL, volume_ratio REAL, extension_pct REAL, entry_low REAL, entry_high REAL, stop_loss REAL,
    target1 REAL, target2 REAL, target3 REAL, risk_reward REAL, risk_pct REAL, trend TEXT, momentum TEXT,
    wave TEXT, wave_bias TEXT, wave_confidence REAL, PRIMARY KEY (ts, symbol));"""

def make_old_db(n_rows=132_903):
    rng = np.random.default_rng(7)
    (tmp / "db").mkdir()
    con = sqlite3.connect(dbm.DB_PATH)
    con.executescript("""CREATE TABLE daily_bars (date TEXT NOT NULL, symbol TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL, volume INTEGER, PRIMARY KEY (date,symbol));
    CREATE TABLE quotes (ts TEXT NOT NULL, symbol TEXT NOT NULL, ltp REAL, high REAL, low REAL, close REAL, ycp REAL, change_pct REAL, trades INTEGER, value REAL, volume INTEGER, PRIMARY KEY (ts,symbol));
    CREATE TABLE market_snapshots (ts TEXT PRIMARY KEY, dsex REAL, dses REAL, ds30 REAL, total_trades INTEGER, total_volume INTEGER, total_value REAL, advancers INTEGER, decliners INTEGER, unchanged INTEGER);
    CREATE TABLE collector_status (key TEXT PRIMARY KEY, value TEXT);""")
    con.execute(OLD_DECISION)
    days = 332; nsym = 400; rows = []; last = {}
    dates = pd.bdate_range(end="2026-10-29", periods=days + 103).strftime("%Y-%m-%d").tolist()
    for i in range(nsym):
        sym = f"SYM{i:03d}"; nd = days + 103 if i == 0 else days
        drift = rng.choice([-0.002, 0.0, 0.001, 0.003]); vol = rng.uniform(0.012, 0.03)
        c = 50 * np.exp(np.cumsum(rng.normal(drift, vol, nd)))
        o = c * (1 + rng.normal(0, .004, nd)); h = np.maximum(o, c) * (1 + abs(rng.normal(0, .008, nd))); l = np.minimum(o, c) * (1 - abs(rng.normal(0, .008, nd)))
        v = (rng.lognormal(12, .5, nd) * (1 + 0.8 * (rng.random(nd) < .08))).astype(int)
        for d, a, b, cc, dd, vv in zip(dates[-nd:], o, h, l, c, v): rows.append((d, sym, float(a), float(b), float(cc), float(dd), int(vv)))
        last[sym] = (float(c[-1]), float(h[-1]), float(l[-1]), int(v[-1]))
    rows = rows[:n_rows] if len(rows) > n_rows else rows
    con.executemany("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?)", rows)
    con.execute("INSERT INTO decision_results (ts,symbol,decision_score,action) VALUES ('2026-10-01T10:00','OLD001',77,'BUY - OLD')")
    ts = "2026-10-29T11:30:00"
    con.executemany("INSERT INTO quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)", [(ts, s, v[0], v[1], v[2], v[0], v[0], 0, 100, 1e6, v[3]) for s, v in last.items()])
    for k in range(8):
        con.execute("INSERT INTO market_snapshots(ts,dsex,advancers,decliners,unchanged) VALUES (?,?,?,?,?)", (f"2026-10-{20+k}T14:30:00", 5400 + k * 5, 170, 150, 60))
    con.commit(); n = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]; con.close()
    return n

ok = True
def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {extra}" if extra else "")); ok = ok and bool(cond)

n_before = make_old_db()
print(f"Old-schema test database built: daily_bars={n_before:,}")
before = pd.read_sql_query("SELECT * FROM daily_bars ORDER BY date,symbol", sqlite3.connect(dbm.DB_PATH))

import db_tools
db_tools.guard_and_backup()
dbm.init_db()
con = sqlite3.connect(dbm.DB_PATH)
n_after = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
after = pd.read_sql_query("SELECT * FROM daily_bars ORDER BY date,symbol", con)
cols = {r[1] for r in con.execute("PRAGMA table_info(decision_results)")}
old_row = con.execute("SELECT action FROM decision_results WHERE symbol='OLD001'").fetchone()
con.close()
check("daily_bars row count unchanged by migration", n_before == n_after, f"{n_before:,} -> {n_after:,}")
check("daily_bars content identical", before.equals(after))
check("old decision_results history kept", old_row == ("BUY - OLD",))
check("new V4 columns added", {"supporting_score", "fib_ext_1272", "primary_fail", "macd_status"} <= cols)
check("backup file created", any((tmp / "db" / "backup").glob("dse_live_*.db")))

import live_scanner
res = live_scanner.scan(30)
check("scanner ran on full universe", len(res) > 300, f"rows={len(res)}")
con = sqlite3.connect(dbm.DB_PATH)
nd = con.execute("SELECT COUNT(*) FROM decision_results WHERE engine_version='V4'").fetchone()[0]
nb = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]; con.close()
check("V4 decision rows written", nd > 300, f"rows={nd}")
check("daily_bars still untouched after scan", nb == n_before)

print("\nAction distribution:\n" + res.action.value_counts().to_string())
print("\nPrimary gates passed (count of symbols):\n" + res.primary_passed.value_counts().sort_index().to_string())
gate_cols = ["gate_trend", "gate_rsi", "gate_macd", "gate_volume", "gate_location", "gate_extension", "gate_rr"]
print("\nGate pass rate %:\n" + (res[gate_cols].astype(bool).mean() * 100).round(1).to_string())
buys = res[res.action.str.startswith("BUY")]
check("every BUY passes all 7 gates", buys.empty or (buys.primary_passed == 7).all())
check("no BUY with RSI>70 or ext>10", buys.empty or ((buys.rsi <= 70) & (buys.extension_pct <= 10)).all())
check("every BUY has R:R(T2)>=2 and risk<=12%", buys.empty or ((buys.risk_reward >= 2) & (buys.risk_pct <= 12)).all())
check("targets ordered and above entry", ((res.target1 < res.target2) & (res.target2 < res.target3) & (res.target1 > res.entry_low)).all())
check("stop below entry zone", (res.stop_loss < res.entry_low).all())
print("\nSample BUY / near-BUY rows:")
show = ["symbol", "action", "entry_quality", "decision_score", "primary_passed", "primary_fail", "location_type", "ltp", "rsi", "macd_status", "volume_ratio", "extension_pct", "entry_low", "entry_high", "stop_loss", "target1", "target2", "target3", "risk_reward", "target_method"]
print((buys if not buys.empty else res).head(8)[show].to_string(index=False))

import subprocess
r = subprocess.run([sys.executable, str(HERE / "backtest_action_engine.py"), "--days", "300", "--horizon", "10"], capture_output=True, text=True, cwd=tmp, env=os.environ | {"PYTHONPATH": str(HERE)})
print("\nBacktest exit code:", r.returncode); print(r.stdout[-1800:] if r.returncode == 0 else r.stderr[-1500:])
check("backtest runs on V4 engine", r.returncode == 0)


# ---------------- Scenario tests: one gate broken at a time ----------------
from types import SimpleNamespace
from decision_engine import build_decision
BASE = dict(close=118.0, open=117.4, ema20=117.5, ema50=112.0, ema200=100.0, rsi14=58.0, volume_ratio=1.1, extension_pct=0.43,
            ret5=1.5, ret20=4.0, atr14=2.0, macd=1.2, macd_signal=1.0, macd_hist=0.2, macd_hist_prev=0.1, macd_cross_up_3d=0,
            prev_close=117.2, prev_high20=125.0, low10=114.0, low20=110.0, vol3_ratio=0.9, updown_vol10=1.3, candle_body_pct=0.6,
            fib_valid=1, fib_swing_high=130.0, fib_swing_low=100.0, ema50_slope5=0.5)
def run(stress=45, wave=None, **kw):
    return build_decision(SimpleNamespace(**{**BASE, **kw}), stress, wave, None)
print("\n--- Scenario tests (hand-made rows) ---")
d = run()
check("ideal Fib+EMA20 pullback -> BUY PULLBACK", d["action"] == "BUY - PULLBACK CONFIRMED" and d["primary_passed"] == 7, f"{d['action']} grade={d['entry_quality']} score={d['decision_score']} loc={d['location_type']}")
check("Fib extension targets used (T1=swing high)", d["target_method"] == "FIB_EXTENSION" and abs(d["target1"] - 130.0) < .01, f"T1/T2/T3={d['target1']}/{d['target2']}/{d['target3']} R:R(T2)={d['risk_reward']}")
check("trend gate fails when EMA50 > EMA20", not run(ema20=111.0, ema50=112.0)["gate_trend"])
check("RSI 72 -> overbought, NO NEW ENTRY", run(rsi14=72.0)["action"].startswith("NO NEW ENTRY"))
check("RSI 48 -> RSI gate fails, no BUY", (lambda x: (not x["gate_rsi"]) and not x["action"].startswith("BUY"))(run(rsi14=48.0)))
check("MACD bearish and no crossover -> no BUY", not run(macd=0.8, macd_signal=1.0, macd_hist=-0.2, macd_hist_prev=-0.1)["action"].startswith("BUY"))
check("MACD fresh crossover passes the MACD gate", run(macd_hist=0.05, macd_hist_prev=-0.1, macd_cross_up_3d=1)["gate_macd"] and run(macd_hist=0.05, macd_hist_prev=-0.1, macd_cross_up_3d=1)["macd_status"] == "BULLISH_CROSSOVER")
check("down day on heavy volume = distribution -> volume gate fails", not run(prev_close=119.0, volume_ratio=1.8)["gate_volume"])
check("no volume confirmation -> no BUY", not run(prev_close=118.5, volume_ratio=0.5, vol3_ratio=1.3, candle_body_pct=-0.2)["action"].startswith("BUY"))
check("price far above any support zone -> location fails", not run(close=124.0, ema20=116.0, extension_pct=6.9, prev_high20=130.0)["gate_location"])
check("extension 11% -> NO CHASE", run(extension_pct=11.0)["action"].startswith("NO NEW ENTRY"))
check("5-day run 13% -> NO CHASE", run(ret5=13.0)["action"].startswith("NO NEW ENTRY"))
check("tiny swing (R:R too low) -> R:R gate fails, no BUY", (lambda x: (not x["gate_rr"]) and not x["action"].startswith("BUY"))(run(fib_swing_high=122.0, fib_swing_low=110.0, atr14=1.0)))
check("market stress 75 blocks BUY", run(stress=75)["action"] == "WAIT / HIGH MARKET RISK")
check("market stress 60 is CAUTION, still BUY if score high", run(stress=60)["market_gate"] == "CAUTION")
check("Elliott bearish does NOT veto BUY (secondary only)", run(wave={"wave_bias": "BEARISH", "wave_confidence": 80})["action"].startswith("BUY"))
bo = run(close=127.0, ema20=123.5, extension_pct=2.8, prev_close=125.5, prev_high20=125.0, volume_ratio=1.9, vol3_ratio=1.3, candle_body_pct=1.0, ret5=4.0, rsi14=62.0, macd_hist=0.4, macd_hist_prev=0.2, low10=119.0)
check("volume breakout above prior 20d high -> BUY BREAKOUT", bo["action"] == "BUY - BREAKOUT CONFIRMED", f"{bo['action']} fail={bo['primary_fail']} rr={bo['risk_reward']}")
print("Scenario BUY detail:", {k: d[k] for k in ["entry_low", "entry_high", "stop_loss", "target1", "target2", "target3", "risk_reward", "risk_reward_t1", "risk_pct", "supporting_score"]})

print("\nRESULT:", "ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
print("Temp folder (safe to delete):", tmp)
sys.exit(0 if ok else 1)

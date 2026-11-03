import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

# DSE_DB_PATH is only for tests. Normal use always reads/writes db/dse_live.db.
DB_PATH = Path(os.environ.get('DSE_DB_PATH', 'db/dse_live.db'))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS quotes (
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ltp REAL, high REAL, low REAL, close REAL, ycp REAL, change_pct REAL,
    trades INTEGER, value REAL, volume INTEGER,
    PRIMARY KEY (ts, symbol)
);
CREATE INDEX IF NOT EXISTS idx_quotes_symbol_ts ON quotes(symbol, ts);
CREATE TABLE IF NOT EXISTS daily_bars (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    PRIMARY KEY (date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_daily_symbol_date ON daily_bars(symbol, date);
CREATE TABLE IF NOT EXISTS market_snapshots (
    ts TEXT PRIMARY KEY,
    dsex REAL, dses REAL, ds30 REAL,
    total_trades INTEGER, total_volume INTEGER, total_value REAL,
    advancers INTEGER, decliners INTEGER, unchanged INTEGER,
    dsex_change REAL, dses_change REAL, ds30_change REAL,
    dsex_change_pct REAL, dses_change_pct REAL, ds30_change_pct REAL
);
CREATE TABLE IF NOT EXISTS scanner_results (
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    score REAL,
    action TEXT,
    market_stress REAL,
    ltp REAL,
    rsi REAL,
    macd REAL,
    macd_signal REAL,
    ema20 REAL,
    ema50 REAL,
    ema200 REAL,
    volume_ratio REAL,
    ret5 REAL,
    ret20 REAL,
    PRIMARY KEY (ts, symbol)
);
CREATE TABLE IF NOT EXISTS trade_setups (
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    score REAL,
    action TEXT,
    entry_quality TEXT,
    trend TEXT,
    momentum TEXT,
    volume_status TEXT,
    extension_status TEXT,
    entry_low REAL,
    entry_high REAL,
    stop_loss REAL,
    target1 REAL,
    target2 REAL,
    target3 REAL,
    risk_reward REAL,
    risk_pct REAL,
    market_stress REAL,
    PRIMARY KEY (ts, symbol)
);
CREATE TABLE IF NOT EXISTS decision_results (
    ts TEXT NOT NULL, symbol TEXT NOT NULL, legacy_score REAL, decision_score REAL, technical_score REAL,
    fundamental_score REAL, fundamental_status TEXT, action TEXT, entry_quality TEXT, confirmation TEXT,
    breakout_confirmed INTEGER, pullback_confirmed INTEGER, exit_signal TEXT, market_stress REAL, market_regime TEXT,
    ltp REAL, rsi REAL, volume_ratio REAL, extension_pct REAL, entry_low REAL, entry_high REAL, stop_loss REAL,
    target1 REAL, target2 REAL, target3 REAL, risk_reward REAL, risk_pct REAL, trend TEXT, momentum TEXT,
    wave TEXT, wave_bias TEXT, wave_confidence REAL, PRIMARY KEY (ts, symbol)
);
CREATE INDEX IF NOT EXISTS idx_decision_symbol_ts ON decision_results(symbol, ts);
CREATE TABLE IF NOT EXISTS collector_status (
    key TEXT PRIMARY KEY,
    value TEXT
);
'''

@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA synchronous=NORMAL')
        yield con
        con.commit()
    finally:
        con.close()

# V4 columns added to decision_results. ADD COLUMN only - existing rows and columns are never touched.
DECISION_EXTRA_COLS = {
    'engine_version': 'TEXT', 'supporting_score': 'REAL', 'primary_pass': 'INTEGER', 'primary_passed': 'INTEGER',
    'primary_fail': 'TEXT', 'macd_hist': 'REAL', 'macd_status': 'TEXT', 'volume_reason': 'TEXT',
    'location_type': 'TEXT', 'support_confluence': 'INTEGER', 'fib_valid': 'INTEGER',
    'fib_swing_low': 'REAL', 'fib_swing_high': 'REAL', 'fib_382': 'REAL', 'fib_618': 'REAL',
    'fib_ext_1272': 'REAL', 'fib_ext_1618': 'REAL', 'target_method': 'TEXT',
    'risk_reward_t1': 'REAL', 'risk_reward_t3': 'REAL', 'market_gate': 'TEXT', 'entry_status': 'TEXT',
}


def _ensure_columns(con, table, cols):
    existing = {r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()}
    for name, typ in cols.items():
        if name not in existing:
            con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {typ}')


def init_db():
    with connect() as con:
        con.executescript(SCHEMA)
        _ensure_columns(con, 'decision_results', DECISION_EXTRA_COLS)
        existing={r[1] for r in con.execute('PRAGMA table_info(market_snapshots)').fetchall()}
        additions={'dsex_change':'REAL','dses_change':'REAL','ds30_change':'REAL','dsex_change_pct':'REAL','dses_change_pct':'REAL','ds30_change_pct':'REAL'}
        for name, typ in additions.items():
            if name not in existing: con.execute(f'ALTER TABLE market_snapshots ADD COLUMN {name} {typ}')

def set_status(key, value):
    with connect() as con:
        con.execute('INSERT OR REPLACE INTO collector_status(key,value) VALUES(?,?)',(key,str(value)))

def get_status(key, default=None):
    with connect() as con:
        row = con.execute('SELECT value FROM collector_status WHERE key=?',(key,)).fetchone()
    return row[0] if row else default

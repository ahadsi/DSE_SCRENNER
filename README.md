# DSE Smart Scanner V4 — Fibonacci + MACD + Volume Action Engine

V4 keeps the live architecture (DSE data -> `bdshare` collector -> SQLite -> indicators -> action engine -> Top-30 CSV/dashboard)
and replaces the decision rules with the final V4 specification.

## IMPORTANT — your database is safe
* This ZIP contains **no `db/` folder**, so extracting it over your existing project can never overwrite `db/dse_live.db`.
  If you extract into a NEW folder, copy your old `db/` folder into it before running.
* V4 only does `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN` (new columns on `decision_results`). Nothing is dropped, deleted or rewritten.
* On every start `run_live.py` prints the row counts, saves a backup (once per day, last 5 kept) in `db/backup/`, and warns loudly if `daily_bars` ever has fewer rows than before.
* `python db_tools.py check` shows row counts any time (you should see 132,903+ `daily_bars` rows). `python db_tools.py backup` makes a manual backup.
* `python selftest.py` proves the migration on a temporary 132,903-row copy; it never opens your real database.

## BUY rule: 7 primary gates + supporting score
A BUY needs **all 7 primary gates**. Supporting indicators are scored separately and do **not** all have to be bullish.

| # | Primary gate | Rule |
|---|---|---|
| 1 | Trend | EMA20 > EMA50 > EMA200 and price > EMA50 |
| 2 | RSI 14 | between 50 and 70. Ideal 55–65 earns score. Above 70 = overbought, excluded |
| 3 | MACD 12/26/9 | histogram > 0 **or** bullish crossover within the last 3 bars |
| 4 | Volume confirmation | breakout >= 1.5x 20-day avg, or up-day >= 1.0x avg, or quiet pullback followed by a bullish bounce. A down day on heavy volume (distribution) fails |
| 5 | Location | price inside a Fibonacci 38.2–61.8% retracement band, an EMA20/EMA50 support band, or a breakout/retest of the prior 20-day high |
| 6 | Extension | <= 10% above EMA20 and 5-day run <= 12%, otherwise **NO CHASE** (<7% is "healthy") |
| 7 | Risk/Reward | reward to Target 2 / risk >= 2, Target 1 >= 1, stop distance <= 12% |

**Supporting score (0–100):** trend quality 15, RSI ideal zone 15, MACD quality (histogram, rising, crossover) 15, volume quality 15,
support confluence (Fib + EMA zones overlapping) 15, extension 10, **Elliott Wave 10 (secondary, never a veto)**, R:R bonus 5.
BUY needs score >= 55 (>= 65 when market is in CAUTION). Grades: A+ >= 80, A >= 65, B otherwise.

**Market regime:** stress >= 70 blocks all new BUYs; stress >= 55 is CAUTION (stricter score). Stress = 50 + breadth (±20) + DSEX day change (±10) + DSEX vs 10-day average (±10).

## Entry zone, stop, targets
* **Entry zone** = the Fibonacci/EMA/breakout zone price is currently in (overlap when several agree). If price is not in any zone, the nearest zone below price is shown as the pullback level to wait for.
* **Stop** = below the zone by 1 ATR, and (pullback entries) below the 10-day swing low. Breakout entries use the breakout level minus 1 ATR.
* **Targets T1/T2/T3** = Fibonacci **extension** of the latest up-swing (levels 1.0, 1.272, 1.618, 2.0, 2.618 measured from the swing low); levels closer than 3% to entry are skipped. If no clean swing (>= 8% inside 60 bars) exists, ATR targets are used, flagged `target_method=ATR_FALLBACK` and scored -3.
* Fibonacci swing = highest high / lowest low in the last 60 bars, valid only if the low came first, the swing is >= 8%, and price has not broken below the 78.6% retracement.
* **XABCD/Harmonic patterns are not included.**

## Action labels
`BUY - BREAKOUT CONFIRMED`, `BUY - PULLBACK CONFIRMED`, `WAIT FOR BREAKOUT/PULLBACK` (trend/MACD/RSI fine, only location/volume/R:R missing), `WATCH`, `WATCH / WAIT`, `NO NEW ENTRY / PROFIT PROTECT` (RSI>70 or extension>10% or 5-day run>12%), `WAIT / HIGH MARKET RISK`, `AVOID`.
Exit labels: `HOLD / TRAIL`, `TREND_WEAKENING`, `PARTIAL_PROFIT`, `PROFIT_PROTECT`, `EXIT_BREAKDOWN`.

## New output columns (live_scan.csv / live_scan_all.csv / decision_results)
`supporting_score, primary_passed (x/7), primary_fail, gate_trend/rsi/macd/volume/location/extension/rr, macd_hist, macd_status, volume_reason, location_type, support_confluence, fib_swing_low/high, fib_382/500/618, fib_ext_1272/1618, target_method, risk_reward (T2), risk_reward_t1, risk_reward_t3, market_gate, engine_version`.
`primary_fail` tells you exactly why a stock is not a BUY (for example `volume, risk_reward`).

## Tuning
All thresholds live in `config.py`. Change numbers there, then run the backtest (`run_backtest.bat`) before trusting the change.

## Run
```
start_windows.bat            (collector + scanner)
start_dashboard.bat          (dashboard)
python selftest.py           (safe self-test on temporary data)
python db_tools.py check     (row counts of your real DB)
python backtest_action_engine.py --days 365 --horizon 10
```

## Known limits
* **Intraday volume:** the live quote volume is the day so far, compared with full-day averages, so `volume_ratio` under-reads before the close. Volume-dependent BUYs are most reliable after about 2:00 pm, or on the next morning's scan.
* BUY signals are deliberately rare: 7 gates must pass. The V4 thresholds are a specification, not yet tuned on your 132k-row history. Run the backtest and use `backtest_parameter_analysis.csv` to adjust `config.py`.
* Rule-based decision support, not a prediction. The scanner does not know your holdings; exit labels are generic.
* `bdshare` polling is near-real-time, not tick/Level-2 data.

## Fundamentals (optional)
Copy `data/fundamentals_template.csv` to `data/fundamentals.csv` and fill `Ticker, EPS, PE, NAV, ROE, DividendYield, RevenueGrowth, EPSGrowth, Sector`. When loaded: decision_score = 0.7 x supporting score + fundamental score (max 30).

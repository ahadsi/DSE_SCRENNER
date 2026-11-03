# V4 changes
* NEW `config.py` (all thresholds), `market_regime.py` (one stress formula for scanner and dashboard), `db_tools.py` (backup/check/guard), `selftest.py`.
* `indicators.py`: MACD histogram + crossover flags, Fibonacci swing, up/down volume, 3-day volume, 10-day low.
* `decision_engine.py`: rewritten - 7 primary gates + supporting score, Fibonacci zones and extension targets, real R:R (old R:R was always 2.0 by construction), Elliott as secondary score.
* `live_scanner.py`: new columns, shared market regime, V4 rows written to `decision_results` (existing rows untouched).
* `database.py`: additive migration only (ADD COLUMN). Optional `DSE_DB_PATH` env var is for tests only.
* `dashboard.py`: gate checklist, Fibonacci levels, V4 columns; fixed a crash when `backtest_parameter_analysis.csv` exists.
* `backtest_action_engine.py`: new parameter buckets (MACD state, location type, confluence, supporting score, target method).
* `run_live.py`: DB guard + daily backup before start.
* `dse_collector.py`, `elliott_wave.py`: unchanged.

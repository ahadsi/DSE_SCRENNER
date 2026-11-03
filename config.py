"""Central tunable thresholds for DSE Smart Scanner V4.

Change numbers here, not inside decision_engine.py. Run the backtest
(python backtest_action_engine.py) after any change.
"""

# ---- Primary gates (all must pass for a BUY) -------------------------------
RSI_GATE_MIN = 50.0        # below this = no momentum
RSI_GATE_MAX = 70.0        # above this = overbought -> excluded
RSI_IDEAL_MIN = 55.0       # ideal fresh-entry zone (supporting score bonus)
RSI_IDEAL_MAX = 65.0

EXT_PREFERRED = 7.0        # % above EMA20: healthy
EXT_NO_CHASE = 10.0        # % above EMA20: NO CHASE above this
RET5_NO_CHASE = 12.0       # % 5-day run: NO CHASE above this

RR_MIN_T2 = 2.0            # reward to Target2 / risk, mandatory
RR_MIN_T1 = 1.0            # reward to Target1 / risk, sanity floor
MAX_RISK_PCT = 12.0        # stop distance cap, % of entry

VOL_BREAKOUT = 1.5         # breakout needs >= 1.5x 20-day average volume
VOL_CONFIRM_UP = 1.0       # up-day needs >= 1.0x average to count as confirmed

# ---- Supporting score -------------------------------------------------------
MIN_SUPPORT_SCORE = 55.0           # BUY needs primary gates + this score
MIN_SUPPORT_SCORE_CAUTION = 65.0   # stricter when market stress is elevated
GRADE_A_PLUS = 80.0
GRADE_A = 65.0

# ---- Market regime ----------------------------------------------------------
STRESS_BLOCK = 70.0        # >= this: no new BUY
STRESS_CAUTION = 55.0      # >= this: stricter supporting score

# ---- Fibonacci --------------------------------------------------------------
FIB_LOOKBACK = 60          # bars used to find the latest swing
FIB_MIN_SWING_PCT = 8.0    # swing must be at least this big
FIB_RETR_LEVELS = (0.382, 0.5, 0.618)
FIB_EXT_LEVELS = (1.0, 1.272, 1.618, 2.0, 2.618)
MIN_TARGET_DISTANCE = 0.03  # Fib extension levels closer than 3% to entry are skipped as targets

# ---- Zones (tolerance around support) --------------------------------------
EMA20_BAND = 0.015
EMA50_BAND = 0.02
BREAKOUT_MAX_ABOVE = 0.03  # price within 3% above prior 20-day high = breakout/retest

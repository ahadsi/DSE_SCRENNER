"""DSE decision engine V4 - primary gates + supporting score.

PRIMARY GATES (all 7 must pass for a BUY):
  1 trend       EMA20 > EMA50 > EMA200 and price > EMA50
  2 rsi         RSI14 between 50 and 70 (ideal 55-65 earns score, >70 = overbought, excluded)
  3 macd        MACD > signal (histogram > 0) OR a bullish crossover in the last 3 bars
  4 volume      volume confirms the price move (breakout >=1.5x, up-day >=1.0x,
                or quiet pullback then bullish bounce); heavy-volume down day = distribution = fail
  5 location    price is inside a Fibonacci 38.2-61.8 retracement band, an EMA20/EMA50
                support band, or a breakout/retest of the prior 20-day high
  6 extension   <=10% above EMA20 and 5-day run <=12% (otherwise NO CHASE)
  7 risk/reward Target2 reward / risk >= 2, Target1 >= 1, stop distance <= 12%

SUPPORTING SCORE (0-100, ranks setups; never needs every indicator bullish):
  trend quality 15, RSI ideal zone 15, MACD quality 15, volume quality 15,
  support confluence 15, extension 10, Elliott Wave (secondary) 10, R:R bonus 5.

Market regime: stress >= 70 blocks BUY; stress >= 55 raises the minimum supporting score.
"""
import math

import config as C


def _f(x, default=0.0):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def fundamental_score(f):
    if f is None:
        return None, "NOT_LOADED"
    def n(k): return _f(f.get(k, 0), 0)
    eps, pe, nav, roe, dy, rg, eg = (n(k) for k in ["EPS", "PE", "NAV", "ROE", "DividendYield", "RevenueGrowth", "EPSGrowth"])
    points = 0
    if eps > 0: points += 6
    if 0 < pe <= 12: points += 6
    elif 12 < pe <= 20: points += 3
    if nav > 0: points += 4
    if roe >= 15: points += 5
    elif roe >= 10: points += 3
    if dy >= 5: points += 3
    elif dy >= 3: points += 2
    if eg > 0: points += 4
    if rg > 0: points += 2
    return min(30, points), "LOADED"


def _zones(price, ema20, ema50, prev_high, fib_valid, fh, fl, trend_ok):
    """Return list of (name, low, high, priority) candidate support/entry zones."""
    z = []
    if prev_high > 0 and prev_high * 0.995 <= price <= prev_high * (1 + C.BREAKOUT_MAX_ABOVE):
        z.append(("BREAKOUT_RETEST", prev_high * 0.995, prev_high * (1 + C.BREAKOUT_MAX_ABOVE), 0))
    if fib_valid and fh > fl:
        rng = fh - fl
        r382 = fh - 0.382 * rng; r618 = fh - 0.618 * rng
        z.append(("FIB_38-61", r618 * 0.995, r382 * 1.005, 1))
    if ema20 > 0:
        z.append(("EMA20_SUPPORT", ema20 * (1 - C.EMA20_BAND), ema20 * (1 + C.EMA20_BAND), 2))
    if ema50 > 0 and trend_ok:
        z.append(("EMA50_SUPPORT", ema50 * (1 - C.EMA50_BAND), ema50 * (1 + C.EMA50_BAND), 3))
    return z


def build_decision(row, stress, wave=None, fundamentals=None):
    g = lambda k, d=0.0: _f(getattr(row, k, d), d)
    price = _f(row.close); ema20 = _f(row.ema20); ema50 = _f(row.ema50); ema200 = _f(row.ema200)
    rsi = _f(row.rsi14); vr = _f(row.volume_ratio); ext = _f(row.extension_pct); ret5 = _f(row.ret5)
    atr = max(_f(row.atr14, price * .03), price * .01, .01)
    hist = g("macd_hist", _f(row.macd) - _f(row.macd_signal))
    hist_prev = g("macd_hist_prev", hist)
    cross3 = g("macd_cross_up_3d", 0) >= 1
    prev_close = g("prev_close", price)
    prev_high = g("prev_high20", 0)
    low10 = g("low10", _f(row.low20, price))
    vol3 = g("vol3_ratio", vr)
    udv = g("updown_vol10", 1.0)
    body = g("candle_body_pct", 0)
    fib_valid = g("fib_valid", 0) >= 1
    fh = g("fib_swing_high", 0); fl = g("fib_swing_low", 0)

    # ---------------- 1. TREND ----------------
    stack = ema20 > ema50 > ema200
    trend_ok = bool(stack and price > ema50)
    trend = "BULLISH" if trend_ok else ("MIXED" if price > ema200 else "BEARISH")

    # ---------------- 2. RSI ------------------
    rsi_ok = C.RSI_GATE_MIN <= rsi <= C.RSI_GATE_MAX
    rsi_ideal = C.RSI_IDEAL_MIN <= rsi <= C.RSI_IDEAL_MAX

    # ---------------- 3. MACD -----------------
    macd_ok = bool(hist > 0 or cross3)
    hist_rising = hist > hist_prev
    if cross3 and hist > 0: macd_status = "BULLISH_CROSSOVER"
    elif hist > 0 and hist_rising: macd_status = "BULLISH_RISING"
    elif hist > 0: macd_status = "BULLISH_FADING"
    else: macd_status = "BEARISH"
    momentum = "BULLISH" if (macd_ok and (hist_rising or cross3)) else ("MIXED" if macd_ok else "BEARISH")

    # ---------------- 5. LOCATION (needed before volume path) ----------------
    zones = _zones(price, ema20, ema50, prev_high, fib_valid, fh, fl, trend_ok)
    active = [z for z in zones if z[1] <= price <= z[2]]
    location_ok = len(active) > 0
    is_breakout = any(z[0] == "BREAKOUT_RETEST" for z in active) and prev_high > 0 and price > prev_high
    location_type = "+".join(z[0] for z in sorted(active, key=lambda z: z[3])) if active else "NONE"
    confluence = len(active)

    # ---------------- 4. VOLUME ---------------
    up_day = price > prev_close
    bullish_candle = body > 0
    distribution = (price < prev_close) and vr >= C.VOL_BREAKOUT
    quiet_pullback = vol3 <= 1.0 and bullish_candle and vr >= 0.7
    if distribution:
        volume_ok, vol_reason = False, "DISTRIBUTION (down day, heavy volume)"
    elif is_breakout and up_day and vr >= C.VOL_BREAKOUT:
        volume_ok, vol_reason = True, "BREAKOUT_VOLUME"
    elif up_day and vr >= C.VOL_CONFIRM_UP:
        volume_ok, vol_reason = True, "UP_DAY_VOLUME"
    elif quiet_pullback:
        volume_ok, vol_reason = True, "QUIET_PULLBACK_BOUNCE"
    else:
        volume_ok, vol_reason = False, "NO_VOLUME_CONFIRMATION"

    # ---------------- 6. EXTENSION ------------
    extension_ok = ext <= C.EXT_NO_CHASE and ret5 <= C.RET5_NO_CHASE
    chase = (rsi > C.RSI_GATE_MAX) or (ext > C.EXT_NO_CHASE) or (ret5 > C.RET5_NO_CHASE)
    overheated = rsi > 75 and ext > 15

    # ---------------- Entry zone / stop / targets ----------------
    if active:
        pri = sorted(active, key=lambda z: z[3])
        lo = max(z[1] for z in pri); hi = min(z[2] for z in pri)
        if hi <= lo:            # no overlap between zones -> use best-priority zone
            lo, hi = pri[0][1], pri[0][2]
        entry_low, entry_high = lo, min(hi, max(price * 1.005, lo * 1.005))
    else:
        below = [z for z in zones if z[2] < price]
        zz = max(below, key=lambda z: z[2]) if below else ("EMA20_SUPPORT", ema20 * (1 - C.EMA20_BAND), ema20 * (1 + C.EMA20_BAND), 2)
        entry_low, entry_high = zz[1], zz[2]
    entry_low = max(0.01, entry_low)
    if entry_high <= entry_low: entry_high = entry_low * 1.01
    entry_ref = min(max(price, entry_low), entry_high)

    # Breakout: invalidated when price falls back through the breakout level (1 ATR buffer).
    # Pullback/support entry: stop below the support zone AND the recent 10-day swing low.
    if is_breakout:
        stop = entry_low - 1.0 * atr
    else:
        stop = min(entry_low - 1.0 * atr, low10 - 0.3 * atr)
    stop = max(0.01, stop)
    if stop >= entry_low: stop = max(0.01, entry_low - 1.0 * atr)
    risk = max(entry_ref - stop, 0.01)
    risk_pct = risk / entry_ref * 100

    targets = []
    target_method = "FIB_EXTENSION"
    if fib_valid and fh > fl:
        rng = fh - fl
        targets = [fl + x * rng for x in C.FIB_EXT_LEVELS if fl + x * rng > entry_ref * (1 + C.MIN_TARGET_DISTANCE)]
    if not targets:
        target_method = "ATR_FALLBACK"
        targets = [entry_ref + 2 * atr, entry_ref + 3.5 * atr, entry_ref + 5 * atr]
    while len(targets) < 3:
        targets.append(targets[-1] + 1.5 * atr)
    t1, t2, t3 = targets[:3]
    rr1 = (t1 - entry_ref) / risk; rr2 = (t2 - entry_ref) / risk; rr3 = (t3 - entry_ref) / risk
    rr_ok = rr2 >= C.RR_MIN_T2 and rr1 >= C.RR_MIN_T1 and risk_pct <= C.MAX_RISK_PCT

    # ---------------- Supporting score ----------------
    s = 0.0
    # trend quality 15
    s += 5 if stack else 0
    s += 5 if price > ema20 else 2 if price > ema50 else 0
    s += 5 if g("ema50_slope5", 0) > 0 else 0
    # RSI 15
    if rsi_ideal: s += 15
    elif 50 <= rsi < 55 or 65 < rsi <= 68: s += 10
    elif 68 < rsi <= 70: s += 5
    elif 45 <= rsi < 50: s += 3
    # MACD 15
    s += 5 if hist > 0 else 0
    s += 5 if hist_rising else 0
    s += 5 if cross3 else 0
    # volume 15
    if vr >= 1.5: s += 10
    elif vr >= 1.2: s += 8
    elif vr >= 1.0: s += 6
    elif vr >= 0.8: s += 3
    s += 5 if udv >= 1.2 else (2 if udv >= 1.0 else 0)
    # support confluence 15
    s += {0: 0, 1: 8, 2: 12}.get(confluence, 15)
    # extension 10
    if -3 <= ext <= 3: s += 10
    elif 3 < ext <= C.EXT_PREFERRED: s += 7
    elif C.EXT_PREFERRED < ext <= C.EXT_NO_CHASE: s += 3
    # Elliott Wave: secondary, max 10, never a veto
    wb = (wave or {}).get("wave_bias", "NEUTRAL"); wc = _f((wave or {}).get("wave_confidence", 0))
    if wb == "BULLISH" and wc >= 70: s += 10
    elif wb == "BULLISH" and wc >= 50: s += 6
    elif wb == "BEARISH" and wc >= 60: s += 0
    else: s += 4
    wave_conflict = bool(wb == "BEARISH" and wc >= 60)
    # R:R bonus 5
    s += 5 if rr2 >= 3 else (3 if rr2 >= 2.5 else 0)
    if target_method == "ATR_FALLBACK": s -= 3
    support = round(max(0.0, min(100.0, s)), 1)

    fs, fstatus = fundamental_score(fundamentals)
    final = round(support * 0.7 + fs, 1) if fs is not None else support

    # ---------------- Primary gate summary ----------------
    gates = {"trend": trend_ok, "rsi": rsi_ok, "macd": macd_ok, "volume": volume_ok,
             "location": location_ok, "extension": extension_ok, "risk_reward": rr_ok}
    passed = sum(gates.values())
    failed = [k for k, v in gates.items() if not v]
    primary_pass = passed == len(gates)

    breakout = bool(primary_pass and is_breakout)
    pullback = bool(primary_pass and not is_breakout)
    confirmation = "BREAKOUT_CONFIRMED" if breakout else ("PULLBACK_CONFIRMED" if pullback else "NO_CONFIRMATION")

    # ---------------- Market regime + action ----------------
    market_block = stress >= C.STRESS_BLOCK
    caution = stress >= C.STRESS_CAUTION
    min_support = C.MIN_SUPPORT_SCORE_CAUTION if caution else C.MIN_SUPPORT_SCORE
    core_ok = trend_ok and macd_ok and extension_ok and rsi_ok

    if market_block:
        action, quality = "WAIT / HIGH MARKET RISK", "D"
    elif overheated or chase:
        action, quality = "NO NEW ENTRY / PROFIT PROTECT", "C"
    elif trend == "BEARISH":
        action, quality = "AVOID", "D"
    elif not trend_ok:
        action, quality = "WATCH / WAIT", "C" if final >= 60 else "D"
    elif primary_pass and final >= min_support:
        label = "BREAKOUT" if is_breakout else "PULLBACK"
        action = f"BUY - {label} CONFIRMED"
        quality = "A+" if final >= C.GRADE_A_PLUS else ("A" if final >= C.GRADE_A else "B")
    elif core_ok and set(failed) <= {"volume", "location", "risk_reward"}:
        action, quality = "WAIT FOR BREAKOUT/PULLBACK", ("B" if final >= 60 else "C")
    elif final >= 55:
        action, quality = "WATCH", "C"
    else:
        action, quality = "AVOID", "D"

    return {
        "technical_score": support, "supporting_score": support,
        "fundamental_score": fs if fs is not None else 0, "fundamental_status": fstatus,
        "decision_score": final,
        "trend": trend, "momentum": momentum, "confirmation": confirmation,
        "breakout_confirmed": breakout, "pullback_confirmed": pullback,
        "preferred_entry_zone": bool(rsi_ideal and ext < C.EXT_PREFERRED), "chase_risk": bool(chase),
        "action": action, "entry_quality": quality,
        "primary_pass": primary_pass, "primary_passed": passed, "primary_total": len(gates),
        "primary_fail": ", ".join(failed) if failed else "NONE",
        "gate_trend": trend_ok, "gate_rsi": rsi_ok, "gate_macd": macd_ok, "gate_volume": volume_ok,
        "gate_location": location_ok, "gate_extension": extension_ok, "gate_rr": rr_ok,
        "macd_hist": round(hist, 4), "macd_status": macd_status, "macd_cross_up_3d": bool(cross3),
        "volume_reason": vol_reason, "location_type": location_type, "support_confluence": confluence,
        "fib_valid": bool(fib_valid),
        "fib_swing_low": round(fl, 2) if fib_valid else 0.0, "fib_swing_high": round(fh, 2) if fib_valid else 0.0,
        "fib_382": round(fh - .382 * (fh - fl), 2) if fib_valid else 0.0,
        "fib_500": round(fh - .5 * (fh - fl), 2) if fib_valid else 0.0,
        "fib_618": round(fh - .618 * (fh - fl), 2) if fib_valid else 0.0,
        "fib_ext_1272": round(fl + 1.272 * (fh - fl), 2) if fib_valid else 0.0,
        "fib_ext_1618": round(fl + 1.618 * (fh - fl), 2) if fib_valid else 0.0,
        "target_method": target_method, "wave_conflict": wave_conflict,
        "entry_low": round(entry_low, 2), "entry_high": round(entry_high, 2),
        "stop_loss": round(stop, 2), "target1": round(t1, 2), "target2": round(t2, 2), "target3": round(t3, 2),
        "risk_reward": round(rr2, 2), "risk_reward_t1": round(rr1, 2), "risk_reward_t3": round(rr3, 2),
        "risk_pct": round(risk_pct, 2),
        "market_gate": "BLOCK" if market_block else ("CAUTION" if caution else "OPEN"),
        "rsi_zone": "55-65 IDEAL" if rsi_ideal else (">70 OVERHEATED" if rsi > 70 else ("50-55/65-70 OK" if rsi_ok else "BELOW 50 WEAK")),
        "extension_status": "HEALTHY <7%" if ext < C.EXT_PREFERRED else ("CAUTION 7-10%" if ext <= C.EXT_NO_CHASE else "EXTENDED >10% NO CHASE"),
    }

import numpy as np
import pandas as pd

import config as C


def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=1).mean()


def rsi(s, n=14):
    d = s.diff()
    gain = d.clip(lower=0).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _roll_argmax(s, n, minp):
    return s.rolling(n, min_periods=minp).apply(np.argmax, raw=True)


def _roll_argmin(s, n, minp):
    return s.rolling(n, min_periods=minp).apply(np.argmin, raw=True)


def add_indicators(df):
    df = df.sort_values('date').copy()
    for c in ['open', 'high', 'low', 'close', 'volume']:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    # ---- Trend: EMA 20/50/200 ------------------------------------------------
    df['ema20'] = ema(df.close, 20)
    df['ema50'] = ema(df.close, 50)
    df['ema200'] = ema(df.close, 200)
    df['ema50_slope5'] = (df.ema50 / df.ema50.shift(5) - 1) * 100

    # ---- RSI 14 --------------------------------------------------------------
    df['rsi14'] = rsi(df.close, 14)

    # ---- MACD 12/26/9 + histogram + crossover -------------------------------
    fast = ema(df.close, 12)
    slow = ema(df.close, 26)
    df['macd'] = fast - slow
    df['macd_signal'] = ema(df.macd, 9)
    df['macd_hist'] = df.macd - df.macd_signal
    df['macd_hist_prev'] = df.macd_hist.shift(1)
    up_cross = (df.macd_hist > 0) & (df.macd_hist.shift(1) <= 0)
    dn_cross = (df.macd_hist < 0) & (df.macd_hist.shift(1) >= 0)
    df['macd_cross_up'] = up_cross.astype(int)
    df['macd_cross_up_3d'] = up_cross.astype(int).rolling(3, min_periods=1).max().fillna(0).astype(int)
    df['macd_cross_down'] = dn_cross.astype(int)

    # ---- Volume confirmation -------------------------------------------------
    df['vol20'] = df.volume.rolling(20, min_periods=5).mean()
    df['volume_ratio'] = df.volume / df.vol20.replace(0, np.nan)
    df['vol3_ratio'] = df.volume.rolling(3, min_periods=2).mean() / df.vol20.replace(0, np.nan)
    prev_close = df.close.shift(1)
    up = df.close > prev_close
    dn = df.close < prev_close
    upv = df.volume.where(up, 0).rolling(10, min_periods=5).sum()
    dnv = df.volume.where(dn, 0).rolling(10, min_periods=5).sum()
    df['updown_vol10'] = upv / dnv.replace(0, np.nan)

    # ---- Returns / ranges ----------------------------------------------------
    df['ret5'] = df.close.pct_change(5) * 100
    df['ret20'] = df.close.pct_change(20) * 100
    df['high20'] = df.high.rolling(20, min_periods=5).max()
    df['low20'] = df.low.rolling(20, min_periods=5).min()
    df['low10'] = df.low.rolling(10, min_periods=5).min()
    df['prev_high20'] = df.high.shift(1).rolling(20, min_periods=5).max()
    df['prev_low20'] = df.low.shift(1).rolling(20, min_periods=5).min()
    df['prev_close'] = prev_close
    df['candle_body_pct'] = ((df.close - df.open) / df.open.replace(0, np.nan)) * 100
    df['ema20_distance_pct'] = ((df.close / df.ema20) - 1) * 100
    df['ema50_distance_pct'] = ((df.close / df.ema50) - 1) * 100

    # ---- ATR 14 --------------------------------------------------------------
    tr = pd.concat([
        (df.high - df.low).abs(),
        (df.high - prev_close).abs(),
        (df.low - prev_close).abs()
    ], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14, min_periods=5).mean()
    df['extension_pct'] = ((df.close / df.ema20) - 1) * 100

    # ---- Fibonacci swing (latest up-swing inside lookback window) -----------
    n = C.FIB_LOOKBACK
    minp = max(20, n // 2)
    sw_hi = df.high.rolling(n, min_periods=minp).max()
    sw_lo = df.low.rolling(n, min_periods=minp).min()
    a_hi = _roll_argmax(df.high, n, minp)
    a_lo = _roll_argmin(df.low, n, minp)
    swing_pct = (sw_hi / sw_lo.replace(0, np.nan) - 1) * 100
    intact = df.close >= (sw_hi - 0.786 * (sw_hi - sw_lo))   # swing not broken (below 78.6%)
    df['fib_swing_high'] = sw_hi
    df['fib_swing_low'] = sw_lo
    df['fib_valid'] = ((a_lo < a_hi) & (swing_pct >= C.FIB_MIN_SWING_PCT) & intact).fillna(False).astype(int)
    return df

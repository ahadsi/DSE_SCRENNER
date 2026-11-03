"""Single market-regime calculation shared by the scanner and the dashboard.

stress = 50
       + breadth   (-20..+20)  decliners vs advancers
       + DSEX day  (-10..+10)  today's index change
       + DSEX trend(-10..+10)  index vs its recent daily average (needs >=5 days of snapshots)
Higher = riskier. Missing inputs are skipped, never invented.
"""
import pandas as pd

import config as C


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def regime_label(stress):
    if stress >= C.STRESS_BLOCK: return "RISK-OFF"
    if stress >= C.STRESS_CAUTION: return "CAUTION"
    if stress <= 40: return "RISK-ON"
    return "NEUTRAL"


def compute_stress(con):
    """Return (stress, latest_snapshot_df, regime_label, detail_dict)."""
    m = pd.read_sql_query("SELECT * FROM market_snapshots ORDER BY ts DESC LIMIT 4000", con)
    if m.empty:
        return 50.0, m, "NEUTRAL", {"note": "no market snapshot"}
    r = m.iloc[0]
    stress = 50.0
    detail = {}
    a, d = r.get("advancers"), r.get("decliners")
    if pd.notna(a) and pd.notna(d):
        a, d = float(a), float(d)
        comp = _clip((d - a) / max(a + d, 1) * 25, -20, 20)
        stress += comp; detail["breadth"] = round(comp, 1)
    pct = r.get("dsex_change_pct")
    if pd.notna(pct):
        comp = _clip(-float(pct) * 5, -10, 10)
        stress += comp; detail["dsex_day"] = round(comp, 1)
    try:
        x = m.dropna(subset=["dsex"]).copy()
        x["day"] = x.ts.astype(str).str[:10]
        daily = x.groupby("day").dsex.first()          # rows are newest-first, so first = last of day
        if len(daily) >= 5:
            cur = float(daily.iloc[0]); avg = float(daily.iloc[:10].mean())
            comp = _clip(-(cur / avg - 1) * 100 * 3, -10, 10)
            stress += comp; detail["dsex_trend"] = round(comp, 1)
    except Exception:
        pass
    stress = _clip(stress, 0, 100)
    return stress, m.iloc[[0]], regime_label(stress), detail

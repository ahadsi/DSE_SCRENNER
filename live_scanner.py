import argparse, json, time
from datetime import datetime
from pathlib import Path
import pandas as pd
from database import connect, init_db, DECISION_EXTRA_COLS
DECISION_NEW_COLS=set(DECISION_EXTRA_COLS)
from indicators import add_indicators
from elliott_wave import detect_elliott
from decision_engine import build_decision
from market_regime import compute_stress

ENGINE_VERSION="V4"

OUT=Path("output"); OUT.mkdir(exist_ok=True)

NEW_KEYS=["supporting_score","primary_pass","primary_passed","primary_total","primary_fail",
    "gate_trend","gate_rsi","gate_macd","gate_volume","gate_location","gate_extension","gate_rr",
    "macd_hist","macd_status","macd_cross_up_3d","volume_reason","location_type","support_confluence",
    "fib_valid","fib_swing_low","fib_swing_high","fib_382","fib_500","fib_618","fib_ext_1272","fib_ext_1618",
    "target_method","wave_conflict","risk_reward_t1","risk_reward_t3","market_gate"]

def fundamentals():
    p=Path("data/fundamentals.csv")
    if p.exists():
        try: return pd.read_csv(p).set_index("Ticker")
        except Exception: return pd.DataFrame()
    return pd.DataFrame()

def latest_quotes():
    with connect() as con:
        return pd.read_sql_query("""SELECT q.* FROM quotes q JOIN
            (SELECT symbol, MAX(ts) ts FROM quotes GROUP BY symbol) x
            ON q.symbol=x.symbol AND q.ts=x.ts""", con)

def history(symbol):
    with connect() as con:
        return pd.read_sql_query("SELECT date,symbol,open,high,low,close,volume FROM daily_bars WHERE symbol=? ORDER BY date", con, params=[symbol])

def market_stress():
    with connect() as con:
        stress,m,regime,_=compute_stress(con)
    return stress,m,regime

def legacy_score(row,f=None):
    s=0
    if row.ema20>row.ema50:s+=7
    if row.ema50>row.ema200:s+=7
    if row.close>row.ema200:s+=6
    if 50<=row.rsi14<=68:s+=8
    elif 45<=row.rsi14<50:s+=4
    if row.macd>row.macd_signal:s+=7
    if row.volume_ratio>=1.5:s+=10
    elif row.volume_ratio>=1.1:s+=6
    elif row.volume_ratio>=0.8:s+=3
    if row.ret20>0:s+=5
    if row.close>=0.98*row.high20:s+=8
    if row.close>1.05*row.low20:s+=7
    if f is not None:
        def num(k):
            try:return float(f.get(k,0) or 0)
            except:return 0
        eps,pe,nav,roe,dy,eg=(num(x) for x in ["EPS","PE","NAV","ROE","DividendYield","EPSGrowth"])
        if eps>0:s+=4
        if 0<pe<=20:s+=4
        if nav>0:s+=3
        if roe>=10:s+=3
        if dy>=3:s+=2
        if eg>0:s+=4
    else:s+=10
    return min(100,round(s,2))

def exit_signal(row):
    r=float(row.rsi14); ext=float(row.extension_pct); vr=float(row.volume_ratio)
    price=float(row.close); ema20=float(row.ema20); ema50=float(row.ema50)
    hist=float(row.macd-row.macd_signal)
    if price<ema50*0.99 or (price<ema20 and vr>=1.5):
        return "EXIT_BREAKDOWN"
    if r>75 and ext>15:
        return "PROFIT_PROTECT"
    if r>70 or ext>10:
        return "PARTIAL_PROFIT"
    if hist<0 and price<ema20:
        return "TREND_WEAKENING"
    return "HOLD / TRAIL"

def scan(limit=30):
    init_db(); q=latest_quotes(); stress,_,market_regime=market_stress(); f=fundamentals(); results=[]
    if q.empty:
        print("Scanner status: WARMING_UP - No live DSE quotes yet.")
        return pd.DataFrame()
    skipped=[]
    # Scan the full local DSE universe: every symbol in historical daily_bars plus live quotes.
    # Only the dashboard defaults to Top 30; all scanned rows are saved to live_scan_all.csv.
    with connect() as con:
        hist_symbols=pd.read_sql_query("SELECT DISTINCT symbol FROM daily_bars WHERE symbol IS NOT NULL AND TRIM(symbol)<>''",con)['symbol'].astype(str).str.upper().tolist()
    quote_map={str(r.symbol).upper(): r for _,r in q.iterrows()}
    universe=sorted(set(hist_symbols) | set(quote_map.keys()))
    for sym in universe:
        qr=quote_map.get(sym)
        h=history(sym)
        if len(h)<40: continue
        if qr is not None:
            qts=str(qr.ts)
            try: today=pd.to_datetime(qts).date().isoformat()
            except Exception: today=datetime.now().date().isoformat()
            live_close=float(qr.ltp) if pd.notna(qr.ltp) else float(qr.close)
            if not pd.notna(live_close) or live_close<=0:
                skipped.append((sym,"invalid LTP")); continue
            quote_status="LIVE_QUOTE"
            ltp_source="LIVE"
            mask=h.date.astype(str)==today
            if mask.any():
                for c,v in [("close",live_close),("high",qr.high),("low",qr.low),("volume",qr.volume)]:
                    if pd.notna(v): h.loc[mask,c]=v
            else:
                h=pd.concat([h,pd.DataFrame([{"date":today,"symbol":sym,"open":live_close,"high":qr.high,"low":qr.low,"close":live_close,"volume":qr.volume}])],ignore_index=True)
        else:
            # Historical-only symbol: keep it searchable, but explicitly mark the price as stale.
            last=h.sort_values('date').iloc[-1]
            today=str(last.date)
            live_close=float(last.close)
            qts=""
            quote_status="NO_LIVE_QUOTE"
            ltp_source="DAILY_CLOSE"
        df=add_indicators(h); d=df.iloc[-1]
        needed=["rsi14","macd","macd_signal","ema20","ema50","ema200","volume_ratio","ret5","ret20","high20","low20","atr14","prev_high20"]
        if any(pd.isna(d.get(x)) for x in needed): continue
        ff=f.loc[sym] if not f.empty and sym in f.index else None
        try:
            sc=legacy_score(d,ff); ew=detect_elliott(df); dec=build_decision(d,stress,ew,ff)
            sell=exit_signal(d)
        except (ZeroDivisionError, ValueError, OverflowError, FloatingPointError) as e:
            skipped.append((sym,repr(e))); continue
        if str(dec["action"]).startswith("BUY"):
            if live_close >= dec["entry_low"] and live_close <= dec["entry_high"]:
                entry_status="ENTRY NOW"; entry_status_reason="Price is inside the active entry zone."
            elif live_close < dec["entry_low"]:
                entry_status="WAIT / RECONFIRM"; entry_status_reason="Price is below the active entry zone; do not blindly use an old signal."
            else:
                entry_status="NO CHASE / WAIT"; entry_status_reason="Price is above the active entry zone; wait for pullback or valid breakout confirmation."
        elif "NO NEW ENTRY" in str(dec["action"]):
            entry_status="NO ENTRY"; entry_status_reason="Setup is overheated/extended."
        elif "WATCH" in str(dec["action"]) or "WAIT" in str(dec["action"]):
            entry_status="WAIT"; entry_status_reason="Setup is not currently confirmed for a fresh entry."
        else:
            entry_status="AVOID"; entry_status_reason="Current setup does not meet the entry rules."

        results.append({
            "timestamp":datetime.now().astimezone().isoformat(timespec="seconds"),"quote_timestamp":qts,"symbol":sym,
            "quote_status":quote_status,"ltp_source":ltp_source,
            "entry_status":entry_status,"entry_status_reason":entry_status_reason,
            "legacy_score":sc,"decision_score":dec["decision_score"],"technical_score":dec["technical_score"],
            "fundamental_score":dec["fundamental_score"],"fundamental_status":dec["fundamental_status"],
            "action":dec["action"],"entry_quality":dec["entry_quality"],"confirmation":dec["confirmation"],
            "breakout_confirmed":dec["breakout_confirmed"],"pullback_confirmed":dec["pullback_confirmed"],
            "preferred_entry_zone":dec["preferred_entry_zone"],"chase_risk":dec["chase_risk"],"exit_signal":sell,
            "market_stress":stress,"market_regime":market_regime,"ltp":live_close,
            "trend":dec["trend"],"momentum":dec["momentum"],"rsi":round(float(d.rsi14),2),
            "rsi_zone":dec["rsi_zone"],"macd":round(float(d.macd),4),"macd_signal":round(float(d.macd_signal),4),
            "ema20":round(float(d.ema20),4),"ema50":round(float(d.ema50),4),"ema200":round(float(d.ema200),4),
            "volume_ratio":round(float(d.volume_ratio),2),"volume_status":"STRONG" if d.volume_ratio>=1.5 else ("GOOD" if d.volume_ratio>=1.2 else ("NORMAL" if d.volume_ratio>=.8 else "WEAK")),
            "ret5":round(float(d.ret5),2),"ret20":round(float(d.ret20),2),"extension_pct":round(float(d.extension_pct),2),
            "extension_status":dec["extension_status"],"entry_low":dec["entry_low"],"entry_high":dec["entry_high"],
            "stop_loss":dec["stop_loss"],"target1":dec["target1"],"target2":dec["target2"],"target3":dec["target3"],
            "risk_reward":dec["risk_reward"],"risk_pct":dec["risk_pct"],
            "wave":ew["wave"],"wave_bias":ew["wave_bias"],"wave_confidence":ew["wave_confidence"],"wave_score":ew["wave_score"],
            "wave_stage":ew["wave_stage"],"wave_entry":ew["wave_entry"],"wave_stop":ew["wave_stop"],"wave_target1":ew["wave_target1"],
            "wave_target2":ew["wave_target2"],"wave_reason":ew["wave_reason"],
            "engine_version":ENGINE_VERSION,
            **{k:dec[k] for k in NEW_KEYS}
        })
    if not results:
        print("Scanner status: WARMING_UP - Not enough valid historical OHLCV data for indicators yet.")
        return pd.DataFrame()
    out=pd.DataFrame(results)
    qrank={"A+":1,"A":2,"B":3,"C":4,"D":5}
    out["quality_rank"]=out.entry_quality.map(qrank).fillna(9)
    out["confirm_rank"]=out.confirmation.map({"BREAKOUT_CONFIRMED":1,"PULLBACK_CONFIRMED":1,"NO_CONFIRMATION":3}).fillna(3)
    out["entry_rank"]=out.entry_status.map({"ENTRY NOW":1,"NO CHASE / WAIT":2,"WAIT / RECONFIRM":3,"WAIT":4,"NO ENTRY":5,"AVOID":6}).fillna(9)
    # Full-universe ranking is saved first; Top 30 is only the default presentation.
    ranked=out.sort_values(["entry_rank","quality_rank","confirm_rank","decision_score","volume_ratio"],ascending=[True,True,True,False,False]).drop(columns=["quality_rank","confirm_rank","entry_rank"])
    ranked.to_csv(OUT/"live_scan_all.csv",index=False)
    top30=ranked.head(limit).copy()
    top30.to_csv(OUT/"live_scan.csv",index=False)
    buys=ranked[ranked.action.str.startswith("BUY")].copy()
    buys.to_csv(OUT/"top_buy_candidates.csv",index=False)
    top=buys.iloc[0] if not buys.empty else ranked.iloc[0]
    summary=[
        f"last_scanner_run={datetime.now().astimezone().isoformat(timespec='seconds')}",f"rows_all={len(ranked)}",f"rows_top30={len(top30)}",
        f"latest_quote={out.quote_timestamp.max()}",f"market_regime={market_regime}",f"market_stress={stress}",
        f"buy_candidates={len(buys)}",f"top_symbol={top.symbol}",f"top_action={top.action}",f"top_score={top.decision_score}",
        "engine=V4 | gates=Trend+RSI50-70+MACD+Volume+Fib/EMA location+Extension<=10%+R:R>=2 | score=supporting 0-100"
    ]
    (OUT/"scanner_status.txt").write_text("\n".join(summary)+"\n",encoding="utf-8")
    top.to_json(OUT/"top_pick.json",indent=2)
    with connect() as con:
        for r in out.to_dict("records"):
            con.execute("INSERT OR REPLACE INTO scanner_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["timestamp"],r["symbol"],r["legacy_score"],r["action"],r["market_stress"],r["ltp"],r["rsi"],r["macd"],r["macd_signal"],r["ema20"],r["ema50"],r["ema200"],r["volume_ratio"],r["ret5"],r["ret20"]))
            cols=["ts","symbol","legacy_score","decision_score","technical_score","fundamental_score","fundamental_status","action","entry_quality","confirmation",
                  "breakout_confirmed","pullback_confirmed","exit_signal","market_stress","market_regime","ltp","rsi","volume_ratio","extension_pct","entry_low","entry_high","stop_loss",
                  "target1","target2","target3","risk_reward","risk_pct","trend","momentum","wave","wave_bias","wave_confidence",
                  "engine_version","entry_status"]+[k for k in NEW_KEYS if k in DECISION_NEW_COLS]
            def val(c):
                if c=="ts": return r["timestamp"]
                v=r[c]
                if isinstance(v,(bool,)) or str(type(v)).endswith("bool_'>"): return int(v)
                return v
            con.execute(f"INSERT OR REPLACE INTO decision_results ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",[val(c) for c in cols])
    (OUT/"top_pick.txt").write_text(json.dumps(top.to_dict(),indent=2),encoding="utf-8")
    return ranked

def main():
    p=argparse.ArgumentParser(); p.add_argument("--once",action="store_true"); p.add_argument("--interval",type=int,default=120); p.add_argument("--limit",type=int,default=30); a=p.parse_args()
    while True:
        try:
            out=scan(a.limit)
            if not out.empty:
                cols=["symbol","decision_score","action","entry_quality","primary_passed","primary_fail","location_type","ltp","rsi","macd_status","volume_ratio","extension_pct","entry_low","entry_high","stop_loss","target1","target2","target3","risk_reward","exit_signal"]
                print(out.head(a.limit)[[c for c in cols if c in out.columns]].to_string(index=False))
        except Exception as e: print("Scanner error:",repr(e))
        if a.once: break
        time.sleep(max(a.interval,30))

if __name__=="__main__": main()

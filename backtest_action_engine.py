"""Robust backtest for the DSE Action Engine.

Key rules:
- No look-ahead: indicators/decision are built only from data available on signal date.
- Signals are executed on the next trading day by default.
- Entry zone, stop-loss and T1/T2/T3 are tested using future OHLC.
- If a future candle touches both stop and target, STOP is assumed first (conservative daily-bar rule).
- Produces trade-level results, summary by grade/action, and parameter attribution.

Run:
    python backtest_action_engine.py --days 365 --horizon 10
"""
import argparse
from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd
from database import connect, init_db
from indicators import add_indicators
from decision_engine import build_decision

OUT=Path('output'); OUT.mkdir(exist_ok=True)


def load_bars():
    with connect() as con:
        return pd.read_sql_query(
            'SELECT date,symbol,open,high,low,close,volume FROM daily_bars ORDER BY symbol,date', con
        )


def first_hit(future, entry, stop, t1, t2, t3, horizon):
    """Return first outcome using conservative OHLC-only sequencing."""
    fut=future.iloc[:horizon].copy()
    for n, (_,b) in enumerate(fut.iterrows(), start=1):
        lo=float(b.low); hi=float(b.high)
        stop_hit=lo <= stop
        t1_hit=hi >= t1
        t2_hit=hi >= t2
        t3_hit=hi >= t3
        if stop_hit:
            return 'STOP_LOSS', n, stop
        if t3_hit:
            return 'TARGET3', n, t3
        if t2_hit:
            return 'TARGET2', n, t2
        if t1_hit:
            return 'TARGET1', n, t1
    if len(fut):
        last=float(fut.iloc[-1].close)
        return 'TIMEOUT', len(fut), last
    return 'NO_FUTURE', 0, np.nan


def execute_next_day(day, nextbar, entry_low, entry_high):
    """Conservative next-day entry model using only OHLC.

    If next-day open is inside zone, fill at open. If open is above zone but
    the day trades back into the zone, fill at entry_high. If open is below
    zone but trades back through it, fill at entry_low. Otherwise no fill.
    """
    o=float(nextbar.open); lo=float(nextbar.low); hi=float(nextbar.high)
    if entry_low <= o <= entry_high:
        return o, 'NEXT_OPEN_IN_ZONE'
    if o > entry_high and lo <= entry_high:
        return entry_high, 'PULLBACK_FILL'
    if o < entry_low and hi >= entry_low:
        return entry_low, 'RECLAIM_FILL'
    return np.nan, 'NO_FILL'


def add_bucket_rows(td):
    rows=[]
    specs={
        'A+': td.entry_quality.eq('A+'),
        'A': td.entry_quality.eq('A'),
        'RSI_55_65': td.rsi.between(55,65,inclusive='both'),
        'RSI_50_60': td.rsi.between(50,60,inclusive='both'),
        'EXT_LT_2': td.extension_pct < 2,
        'EXT_LT_5': td.extension_pct < 5,
        'EXT_LT_7': td.extension_pct < 7,
        'VOL_GE_1': td.volume_ratio >= 1,
        'VOL_GE_1_2': td.volume_ratio >= 1.2,
        'VOL_GE_1_5': td.volume_ratio >= 1.5,
        'RISK_ON': td.market_regime.eq('RISK-ON'),
        'PULLBACK': td.confirmation.eq('PULLBACK_CONFIRMED'),
        'BREAKOUT': td.confirmation.eq('BREAKOUT_CONFIRMED'),
        'RR_GE_2': td.risk_reward >= 2,
        'RR_GE_3': td.risk_reward >= 3,
        'MACD_CROSSOVER': td.macd_status.eq('BULLISH_CROSSOVER'),
        'MACD_RISING': td.macd_status.eq('BULLISH_RISING'),
        'LOC_FIB': td.location_type.str.contains('FIB',na=False),
        'LOC_EMA20': td.location_type.str.contains('EMA20',na=False),
        'LOC_EMA50': td.location_type.str.contains('EMA50',na=False),
        'LOC_BREAKOUT': td.location_type.str.contains('BREAKOUT',na=False),
        'CONFLUENCE_GE_2': td.support_confluence >= 2,
        'SUPPORT_GE_70': td.supporting_score >= 70,
        'SUPPORT_LT_65': td.supporting_score < 65,
        'FIB_TARGETS': td.target_method.eq('FIB_EXTENSION'),
        'ATR_TARGETS': td.target_method.eq('ATR_FALLBACK'),
    }
    for name,mask in specs.items():
        g=td.loc[mask]
        if g.empty: continue
        wins=g.outcome.str.startswith('TARGET')
        rows.append({
            'parameter':name,'signals':len(g),'win_rate_pct':round(wins.mean()*100,1),
            'avg_return_pct':round(g.realized_return_pct.mean(),2),
            'median_return_pct':round(g.realized_return_pct.median(),2),
            'target1_hit_pct':round((g.outcome=='TARGET1').mean()*100,1),
            'target2_hit_pct':round(g.outcome.isin(['TARGET2','TARGET3']).mean()*100,1),
            'target3_hit_pct':round((g.outcome=='TARGET3').mean()*100,1),
            'stop_loss_pct':round((g.outcome=='STOP_LOSS').mean()*100,1),
            'no_fill_pct':round((g.outcome=='NO_FILL').mean()*100,1),
        })
    return pd.DataFrame(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--days',type=int,default=365)
    ap.add_argument('--horizon',type=int,default=10)
    ap.add_argument('--min-history',type=int,default=200)
    ap.add_argument('--min-score',type=float,default=0)
    args=ap.parse_args()
    init_db(); bars=load_bars()
    if bars.empty:
        print('No daily_bars available.'); return
    bars['date']=pd.to_datetime(bars.date)
    max_date=bars.date.max()
    cutoff=max_date-pd.Timedelta(days=args.days)
    trades=[]

    for sym,g in bars.groupby('symbol'):
        g=g.sort_values('date').reset_index(drop=True)
        if len(g) < args.min_history + 2: continue
        full=add_indicators(g.copy())
        # Last signal date must have enough future bars for the requested horizon.
        last_signal=len(full)-args.horizon-1
        if last_signal <= args.min_history: continue
        for i in range(args.min_history,last_signal+1):
            d=full.iloc[i]
            if d.date < cutoff: continue
            needed=['rsi14','ema200','volume_ratio','macd','macd_signal','atr14','ret5','ret20','low10']
            if any(pd.isna(d.get(x)) for x in needed): continue
            dec=build_decision(d,50,None,None)
            if not str(dec['action']).startswith('BUY'): continue
            if float(dec['decision_score']) < args.min_score: continue
            # Signal at close; execute next trading day only.
            nb=full.iloc[i+1]
            entry,entry_mode=execute_next_day(d,nb,float(dec['entry_low']),float(dec['entry_high']))
            future=full.iloc[i+1:i+1+args.horizon]
            if not np.isfinite(entry):
                outcome='NO_FILL'; hit_day=0; exit_price=np.nan
                realized=np.nan
            else:
                outcome,hit_day,exit_price=first_hit(future,entry,float(dec['stop_loss']),float(dec['target1']),float(dec['target2']),float(dec['target3']),args.horizon)
                realized=(exit_price/entry-1)*100 if np.isfinite(exit_price) else np.nan
            trades.append({
                'signal_date':d.date.date().isoformat(),'symbol':sym,'entry_mode':entry_mode,
                'signal_close':float(d.close),'entry':round(float(entry),4) if np.isfinite(entry) else np.nan,
                'entry_low':dec['entry_low'],'entry_high':dec['entry_high'],'stop_loss':dec['stop_loss'],
                'target1':dec['target1'],'target2':dec['target2'],'target3':dec['target3'],
                'action':dec['action'],'entry_quality':dec['entry_quality'],'confirmation':dec['confirmation'],
                'decision_score':dec['decision_score'],'rsi':round(float(d.rsi14),2),
                'volume_ratio':round(float(d.volume_ratio),2),'extension_pct':round(float(d.extension_pct),2),
                'trend':dec['trend'],'momentum':dec['momentum'],'risk_reward':dec['risk_reward'],
                'supporting_score':dec['supporting_score'],'macd_status':dec['macd_status'],'location_type':dec['location_type'],'support_confluence':dec['support_confluence'],'target_method':dec['target_method'],'volume_reason':dec['volume_reason'],
                'market_regime':'NEUTRAL','outcome':outcome,'hit_day':hit_day,
                'exit_price':round(float(exit_price),4) if np.isfinite(exit_price) else np.nan,
                'realized_return_pct':round(float(realized),2) if np.isfinite(realized) else np.nan,
            })

    td=pd.DataFrame(trades)
    if td.empty:
        print('No historical BUY signals found under the current rules.'); return
    td.to_csv(OUT/'backtest_trades.csv',index=False)

    valid=td[td.outcome!='NO_FILL'].copy()
    summary_rows=[]
    for label,g in [('ALL',valid),('A+',valid[valid.entry_quality=='A+']),('A',valid[valid.entry_quality=='A'])]:
        if g.empty: continue
        wins=g.outcome.str.startswith('TARGET')
        summary_rows.append({
            'group':label,'signals':len(g),'win_rate_pct':round(wins.mean()*100,1),
            'avg_return_pct':round(g.realized_return_pct.mean(),2),
            'median_return_pct':round(g.realized_return_pct.median(),2),
            'target1_hit_pct':round((g.outcome=='TARGET1').mean()*100,1),
            'target2plus_hit_pct':round(g.outcome.isin(['TARGET2','TARGET3']).mean()*100,1),
            'target3_hit_pct':round((g.outcome=='TARGET3').mean()*100,1),
            'stop_loss_pct':round((g.outcome=='STOP_LOSS').mean()*100,1),
            'timeout_pct':round((g.outcome=='TIMEOUT').mean()*100,1),
        })
    pd.DataFrame(summary_rows).to_csv(OUT/'backtest_summary.csv',index=False)
    params=add_bucket_rows(valid)
    params.to_csv(OUT/'backtest_parameter_analysis.csv',index=False)

    # Repeated signals: shows whether an A/A+ setup remains valid on consecutive days.
    if not td.empty:
        x=td.sort_values(['symbol','signal_date']).copy()
        x['prev_signal_date']=x.groupby('symbol').signal_date.shift(1)
        x['prev_quality']=x.groupby('symbol').entry_quality.shift(1)
        x['consecutive_signal']=x.apply(lambda r: bool(r.prev_signal_date and (pd.Timestamp(r.signal_date)-pd.Timestamp(r.prev_signal_date)).days<=4),axis=1)
        x[['signal_date','symbol','entry_quality','action','decision_score','entry','entry_low','entry_high','outcome','realized_return_pct','consecutive_signal']].to_csv(OUT/'backtest_signal_persistence.csv',index=False)

    print('\n=== BACKTEST SUMMARY ===')
    print(pd.DataFrame(summary_rows).to_string(index=False))
    print('\n=== PARAMETER ANALYSIS ===')
    print(params.sort_values(['win_rate_pct','avg_return_pct'],ascending=False).to_string(index=False))
    print(f'\nWrote {len(td)} signals to output/backtest_trades.csv')

if __name__=='__main__': main()

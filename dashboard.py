import streamlit as st
import pandas as pd
from pathlib import Path
from database import connect, init_db
from market_regime import compute_stress

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60000, key='dse_live_refresh')
except Exception:
    pass

st.set_page_config(page_title='DSE Smart Scanner — Full Universe', layout='wide')
st.title('DSE Smart Scanner V4 — Fibonacci + MACD + Volume Action Engine')
st.caption('Default view = Top 30. Search any symbol to inspect any stock in the scanned local DSE universe. A/A+ is setup quality; ENTRY NOW is the execution status.')

def market_status():
    init_db()
    with connect() as con:
        m=pd.read_sql_query('SELECT * FROM market_snapshots ORDER BY ts DESC LIMIT 2',con)
    if m.empty: return None
    latest=m.iloc[0]; prev=m.iloc[1] if len(m)>1 else None
    def val(x):
        try: return float(x) if pd.notna(x) else None
        except Exception: return None
    out={'ts':latest.get('ts')}
    for idx in ['dsex','dses','ds30']:
        cur=val(latest.get(idx)); old=val(prev.get(idx)) if prev is not None else None
        out[idx]=cur; change=val(latest.get(idx+'_change'))
        out[idx+'_change']=change if change is not None else (cur-old if cur is not None and old is not None else None)
        pct=val(latest.get(idx+'_change_pct'))
        out[idx+'_change_pct']=pct if pct is not None else (((cur/old)-1)*100 if cur is not None and old not in (None,0) else None)
    for k in ['advancers','decliners','unchanged','total_trades','total_volume','total_value']: out[k]=val(latest.get(k))
    adv,dec,unc=out['advancers'],out['decliners'],out['unchanged']
    with connect() as con:
        stress,_,regime,_d=compute_stress(con)
    breadth=('BULLISH' if adv>dec else ('BEARISH' if dec>adv else 'NEUTRAL')) if adv is not None and dec is not None else 'N/A'
    out.update({'breadth':breadth,'stress':stress,'regime':regime}); return out

ms=market_status()
if ms:
    st.subheader('📈 DSE Market & Index Status')
    c1,c2,c3,c4,c5,c6=st.columns(6)
    for col,idx,label in [(c1,'dsex','DSEX'),(c2,'dses','DSES'),(c3,'ds30','DS30')]:
        v=ms.get(idx); ch=ms.get(idx+'_change'); pct=ms.get(idx+'_change_pct')
        delta='—' if ch is None else (f'{ch:+,.2f} pts ({pct:+.2f}%)' if pct is not None else f'{ch:+,.2f} pts')
        col.metric(label,'—' if v is None else f'{v:,.2f}',delta)
    c4.metric('Market Regime',ms['regime']); c5.metric('Breadth',ms['breadth'])
    c6.metric('Gainers / Losers',f"{int(ms['advancers'] or 0)} / {int(ms['decliners'] or 0)}")
    b1,b2,b3,b4=st.columns(4)
    b1.metric('Gainers',f"{int(ms['advancers'] or 0):,}"); b2.metric('Losers',f"{int(ms['decliners'] or 0):,}")
    b3.metric('Unchanged',f"{int(ms['unchanged'] or 0):,}"); b4.metric('Market Stress',f"{ms['stress']:.0f}/100")
    st.caption(f"Snapshot: {ms['ts']} | Trades: {ms['total_trades'] or '—'} | Volume: {ms['total_volume'] or '—'} | Value (mn): {ms['total_value'] or '—'}")
else:
    st.info('DSE index and market breadth appear after successful market-summary collection. Missing provider values are shown as —, never estimated.')

p_all=Path('output/live_scan_all.csv')
if not p_all.exists():
    st.warning('Scanner is warming up. live_scan_all.csv is not ready yet.')
    st.stop()

df=pd.read_csv(p_all)
if df.empty:
    st.warning('No valid setup yet.'); st.stop()
df['symbol']=df['symbol'].astype(str).str.upper()

st.subheader('🔎 DSE Stock Scanner — Top 30 + Search Full Universe')
st.caption('One table only: Top 30 is shown by default. Search any symbol to replace the view with that stock, even if it is outside Top 30.')
q=st.text_input('Search DSE stock',placeholder='e.g. SQURPHARMA, POWERGRID, SOUTHEASTB').strip().upper()
status_filter=st.selectbox('Entry status',['ALL','ENTRY NOW','WAIT','NO ENTRY / AVOID'])
if q:
    view=df[df.symbol.str.contains(q,case=False,na=False)].copy(); view_title=f'Search result: {q}'
else:
    view=df.head(30).copy(); view_title='Top 30 Decision Ranking'
if status_filter=='ENTRY NOW': view=view[view.entry_status.eq('ENTRY NOW')]
elif status_filter=='WAIT': view=view[view.entry_status.astype(str).str.contains('WAIT',na=False)]
elif status_filter=='NO ENTRY / AVOID': view=view[view.entry_status.astype(str).isin(['NO ENTRY','AVOID'])]

cols=['symbol','decision_score','supporting_score','entry_quality','action','entry_status','primary_passed','primary_fail','ltp','rsi','macd_status','volume_ratio','volume_reason','extension_pct','trend','location_type','entry_low','entry_high','stop_loss','target1','target2','target3','risk_reward','risk_reward_t1','target_method','confirmation','wave','wave_bias','market_regime','market_gate']
show=[c for c in cols if c in view.columns]
m1,m2,m3=st.columns(3)
m1.metric('Local DSE universe scanned',f'{len(df):,}'); m2.metric('Rows shown',f'{len(view):,}'); m3.metric('ENTRY NOW',f"{int((df.entry_status=='ENTRY NOW').sum()):,}")
st.markdown(f'**{view_title}**')
if view.empty: st.warning('No stock matches the current search/filter.')
else: st.dataframe(view[show],use_container_width=True,hide_index=True)

buy_path=Path('output/top_buy_candidates.csv')
if buy_path.exists():
    buys=pd.read_csv(buy_path)
    st.subheader('🟢 BUY Candidates')
    if not buys.empty:
        preferred=[c for c in ['symbol','entry_status','entry_quality','decision_score','action','ltp','location_type','entry_low','entry_high','stop_loss','target1','target2','target3','risk_reward','rsi','macd_status','volume_ratio','market_regime'] if c in buys.columns]
        st.dataframe(buys[preferred].head(30),use_container_width=True,hide_index=True)
    else: st.info('No BUY candidates currently meet the scanner rules.')

if q and not view.empty:
    top=view.iloc[0]
    st.subheader(f'📌 {top.symbol} — Detailed Decision')
    a,b,c,d,e,f=st.columns(6)
    a.metric('Price',top.get('ltp','-')); b.metric('Quality',top.get('entry_quality','-')); c.metric('Score',top.get('decision_score','-')); d.metric('Entry Status',top.get('entry_status','-')); e.metric('RSI',top.get('rsi','-')); f.metric('Market',top.get('market_regime','-'))
    st.write({'Action':top.get('action'),'Entry Zone':f"{top.get('entry_low')} – {top.get('entry_high')}",'Stop Loss':top.get('stop_loss'),'Target 1':top.get('target1'),'Target 2':top.get('target2'),'Target 3':top.get('target3'),'R:R':top.get('risk_reward'),'Confirmation':top.get('confirmation'),'Trend':top.get('trend'),'Momentum':top.get('momentum'),'Volume Ratio':top.get('volume_ratio'),'Extension %':top.get('extension_pct'),'Quote Source':top.get('ltp_source'),'Entry Reason':top.get('entry_status_reason')})
    st.markdown('**Primary gate checklist (all 7 needed for BUY)**')
    gate_names=[('gate_trend','1 Trend EMA20>50>200'),('gate_rsi','2 RSI 50-70'),('gate_macd','3 MACD bullish/crossover'),('gate_volume','4 Volume confirms'),('gate_location','5 Fib / EMA support zone'),('gate_extension','6 Not extended (NO CHASE)'),('gate_rr','7 R:R >= 1:2')]
    gc=st.columns(7)
    for col,(k,label) in zip(gc,gate_names):
        v=top.get(k)
        col.metric(label,'PASS' if str(v) in ('True','1','1.0') else 'FAIL')
    st.write({'Supporting score':top.get('supporting_score'),'Gates passed':f"{top.get('primary_passed')}/{top.get('primary_total')}",'Failed gates':top.get('primary_fail'),'MACD':top.get('macd_status'),'Volume':top.get('volume_reason'),'Location':top.get('location_type'),'Fib swing low/high':f"{top.get('fib_swing_low')} / {top.get('fib_swing_high')}",'Fib 38.2 / 50 / 61.8':f"{top.get('fib_382')} / {top.get('fib_500')} / {top.get('fib_618')}",'Fib ext 1.272 / 1.618':f"{top.get('fib_ext_1272')} / {top.get('fib_ext_1618')}",'Target method':top.get('target_method'),'R:R T1 / T2 / T3':f"{top.get('risk_reward_t1')} / {top.get('risk_reward')} / {top.get('risk_reward_t3')}",'Elliott (secondary)':f"{top.get('wave')} {top.get('wave_bias')} {top.get('wave_confidence')}",'Market gate':top.get('market_gate')})
    if str(top.get('quote_status'))!='LIVE_QUOTE': st.warning('No current live quote is available for this symbol. Verify the live price before trading.')

st.subheader('📊 Action Engine Backtest')
bs=Path('output/backtest_summary.csv'); bp=Path('output/backtest_parameter_analysis.csv'); bt=Path('output/backtest_trades.csv')
if bs.exists():
    st.dataframe(pd.read_csv(bs),use_container_width=True,hide_index=True)
if bp.exists():
    st.write('Parameter performance')
    st.dataframe(pd.read_csv(bp).sort_values(['win_rate_pct','avg_return_pct'],ascending=False),use_container_width=True,hide_index=True)
if bt.exists():
    st.download_button('Download backtest trades CSV',Path(bt).read_bytes(),file_name='backtest_trades.csv',mime='text/csv')

st.subheader('How to read the scanner')
st.markdown('''
- **BUY needs all 7 primary gates** (trend, RSI, MACD, volume, Fib/EMA location, extension, R:R) **plus** a minimum supporting score. Supporting indicators do not all have to be bullish.
- **A+ / A / B** = setup quality, not a permanent buy instruction.
- **ENTRY NOW** = current price is inside the active entry zone and the setup is confirmed.
- **WAIT / RECONFIRM** = wait for the entry zone/confirmation to become valid.
- **NO CHASE / WAIT** = price is above the zone; wait for pullback or fresh breakout confirmation.
- **NO ENTRY / AVOID** = do not open a fresh position under the current rules.
- **Top 30** is only the default display. The search box can inspect any symbol present in the local DSE universe.
''')
if 'quote_timestamp' in df.columns:
    qt=pd.to_datetime(df.quote_timestamp.replace('',pd.NA),errors='coerce').max(); st.caption('Latest live quote timestamp: '+str(qt))
st.caption('Rule-based decision support only. Validate liquidity, corporate actions, event risk and live price before trading.')

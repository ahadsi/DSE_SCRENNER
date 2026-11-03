import argparse, time, logging
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from bdshare import get_current_trade_data, get_historical_data, get_market_info, BDShareError
from database import connect, init_db, set_status, get_status

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')

def norm_live(df):
    df = df.copy()
    rename = {'symbol':'symbol','ltp':'ltp','high':'high','low':'low','close':'close','ycp':'ycp','change':'change_pct','trade':'trades','value':'value','volume':'volume'}
    df = df.rename(columns=rename)
    for c in ['ltp','high','low','close','ycp','change_pct','trades','value','volume']:
        if c in df: df[c] = pd.to_numeric(df[c], errors='coerce')
    if {'ltp','ycp'}.issubset(df.columns):
        valid=df.ycp.notna() & (df.ycp>0) & df.ltp.notna()
        df.loc[valid,'change_pct']=(df.loc[valid,'ltp']/df.loc[valid,'ycp']-1)*100
    return df

def norm_hist(df):
    df = df.reset_index() if hasattr(df.index,'name') and df.index.name else df.copy()
    lower = {str(c).lower().strip():c for c in df.columns}
    def pick(*names):
        for n in names:
            if n in lower: return lower[n]
        return None
    out = pd.DataFrame()
    out['date'] = pd.to_datetime(df[pick('date','trading date','timestamp')], errors='coerce').dt.date.astype('string')
    sym = pick('symbol','code','trading code')
    if sym: out['symbol']=df[sym].astype(str).str.strip().str.upper()
    for dst, names in [('open',('open',)),('high',('high',)),('low',('low',)),('close',('close','ltp')),('volume',('volume','total volume'))]:
        src=pick(*names)
        out[dst]=pd.to_numeric(df[src],errors='coerce') if src else None
    return out.dropna(subset=['date','symbol','close'])

def save_quotes(ts, df):
    rows=[]
    for _,r in df.iterrows():
        rows.append((ts, r.get('symbol'), r.get('ltp'), r.get('high'), r.get('low'), r.get('close'), r.get('ycp'), r.get('change_pct'), r.get('trades'), r.get('value'), r.get('volume')))
    with connect() as con:
        con.executemany('''INSERT OR REPLACE INTO quotes
        (ts,symbol,ltp,high,low,close,ycp,change_pct,trades,value,volume)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''', rows)

def _num(v):
    try:
        if pd.isna(v): return None
        return float(str(v).replace(',', '').replace('%','').strip())
    except Exception: return None

def _find_market_value(frame, aliases):
    if frame is None or frame.empty: return None
    cols={str(c).strip().lower():c for c in frame.columns}
    for alias in aliases:
        key=alias.lower()
        if key in cols:
            vals=pd.to_numeric(frame[cols[key]].astype(str).str.replace(',','',regex=False),errors='coerce').dropna()
            if not vals.empty: return float(vals.iloc[-1])
    for c in frame.columns:
        name=str(c).strip().lower()
        if any(a.lower() in name for a in aliases) and not any(x in name for x in ['change','%']):
            vals=pd.to_numeric(frame[c].astype(str).str.replace(',','',regex=False),errors='coerce').dropna()
            if not vals.empty: return float(vals.iloc[-1])
    return None

def save_market(ts, live):
    # Count breadth from LTP versus previous close (YCP), not an ambiguous provider field.
    work=live.copy()
    if {'ltp','ycp'}.issubset(work.columns):
        ltp=pd.to_numeric(work.ltp,errors='coerce'); ycp=pd.to_numeric(work.ycp,errors='coerce')
        valid=ltp.notna() & ycp.notna() & (ycp>0)
        adv=int(((ltp>ycp) & valid).sum()); dec=int(((ltp<ycp) & valid).sum()); unc=int(((ltp==ycp) & valid).sum())
    else:
        cp=pd.to_numeric(work.get('change_pct',pd.Series(dtype=float)),errors='coerce')
        adv=int((cp>0).sum()); dec=int((cp<0).sum()); unc=int((cp==0).sum())
    dsex=dses=ds30=None; total_trades=total_volume=total_value=None
    try:
        m=get_market_info()
        if m is not None and not m.empty:
            dsex=_find_market_value(m,['DSEX Index','DSEX'])
            dses=_find_market_value(m,['DSES Index','DSES'])
            ds30=_find_market_value(m,['DS30 Index','DS30','DSE30 Index'])
            last=m.iloc[-1]
            def stat(names):
                for name in names:
                    if name in m.columns: return _num(last.get(name))
                return None
            total_trades=stat(['Total Trade','Total Trades','Total trade'])
            total_volume=stat(['Total Volume','Total volume'])
            total_value=stat(['Total Value (mn)','Total Value','Total value (mn)'])
        if dsex is None or dses is None or ds30 is None:
            logging.warning('Index field missing from bdshare market summary. Columns=%s | extracted DSEX=%s DSES=%s DS30=%s',list(m.columns) if m is not None else [],dsex,dses,ds30)
        else:
            logging.info('DSE index values extracted: DSEX=%s DSES=%s DS30=%s',dsex,dses,ds30)
    except Exception as e:
        logging.warning('Could not read DSE index/market summary: %s',e)
    with connect() as con:
        prev=con.execute('SELECT dsex,dses,ds30 FROM market_snapshots WHERE substr(ts,1,10) < substr(?,1,10) AND dsex IS NOT NULL ORDER BY ts DESC LIMIT 1',(ts,)).fetchone()
        old=list(prev) if prev else [None,None,None]; vals=[dsex,dses,ds30]
        changes=[(v-o) if v is not None and o is not None else None for v,o in zip(vals,old)]
        pcts=[((v/o)-1)*100 if v is not None and o not in (None,0) else None for v,o in zip(vals,old)]
        con.execute("""INSERT OR REPLACE INTO market_snapshots
        (ts,dsex,dses,ds30,total_trades,total_volume,total_value,advancers,decliners,unchanged,
         dsex_change,dses_change,ds30_change,dsex_change_pct,dses_change_pct,ds30_change_pct)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ts,dsex,dses,ds30,total_trades,total_volume,total_value,adv,dec,unc,*changes,*pcts))

def bootstrap(days=320):
    """Build local OHLCV cache in visible, retryable monthly chunks."""
    logging.info('Bootstrapping historical daily data (%s calendar days) in chunks...', days)
    set_status('history_bootstrap_state', 'STARTED')
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    # Fetch in ~30-day chunks so the user sees progress and one timeout does not
    # discard all work. Rows are upserted after every successful chunk.
    cursor = start_date
    total_rows = 0
    chunks_ok = 0
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=29), end_date)
        label = f'{cursor.isoformat()}..{chunk_end.isoformat()}'
        logging.info('History chunk %s: requesting...', label)
        set_status('history_bootstrap_state', f'FETCHING {label}')
        try:
            chunk = norm_hist(get_historical_data(cursor.isoformat(), chunk_end.isoformat()))
            if not chunk.empty:
                rows = list(chunk[['date','symbol','open','high','low','close','volume']].itertuples(index=False,name=None))
                with connect() as con:
                    con.executemany('INSERT OR REPLACE INTO daily_bars VALUES (?,?,?,?,?,?,?)', rows)
                total_rows += len(rows)
                chunks_ok += 1
                logging.info('History chunk %s: stored %s rows (total this run=%s).', label, len(rows), total_rows)
            else:
                logging.warning('History chunk %s returned no rows.', label)
        except Exception as e:
            logging.exception('History chunk %s failed: %s', label, e)
            set_status('history_bootstrap_last_chunk_error', f'{label} | {type(e).__name__}: {e}')
        cursor = chunk_end + timedelta(days=1)

    with connect() as con:
        n = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        sym_n = con.execute("SELECT COUNT(DISTINCT symbol) FROM daily_bars").fetchone()[0]
        span = con.execute("SELECT MIN(date), MAX(date) FROM daily_bars").fetchone()
        trading_days = con.execute("SELECT COUNT(DISTINCT date) FROM daily_bars").fetchone()[0]
    ready = bool(span[0] and span[1] and trading_days >= 190 and sym_n >= 100)
    if ready:
        set_status('history_bootstrapped_at', now())
        set_status('history_bootstrap_state', 'READY')
        set_status('history_bootstrap_error', '')
        logging.info('Historical data ready: rows=%s symbols=%s trading_days=%s range=%s..%s; chunks_ok=%s.', n, sym_n, trading_days, span[0], span[1], chunks_ok)
    else:
        msg = f'Insufficient history after chunked fetch: rows={n}, symbols={sym_n}, trading_days={trading_days}, range={span[0]}..{span[1]}, chunks_ok={chunks_ok}.'
        set_status('history_bootstrap_state', 'FAILED')
        set_status('history_bootstrap_error', msg)
        raise RuntimeError(msg)

def upsert_today_bar(live):
    """Continuously roll the current live snapshot into today's OHLCV bar.
    This is critical: indicators must see the current day's LTP/high/low/volume,
    not only the last historical close.
    """
    today=datetime.now().date().isoformat()
    rows=[]
    with connect() as con:
        for _,r in live.iterrows():
            sym=str(r.get("symbol") or "").strip().upper()
            if not sym: continue
            ltp=pd.to_numeric(r.get("ltp"),errors="coerce")
            hi=pd.to_numeric(r.get("high"),errors="coerce")
            lo=pd.to_numeric(r.get("low"),errors="coerce")
            vol=pd.to_numeric(r.get("volume"),errors="coerce")
            if pd.isna(ltp) or float(ltp)<=0: continue
            old=con.execute("SELECT open,high,low,close,volume FROM daily_bars WHERE date=? AND symbol=?",(today,sym)).fetchone()
            if old:
                op=old[0] if old[0] is not None else float(r.get("ycp") or ltp)
                old_hi=old[1] if old[1] is not None else float(hi if pd.notna(hi) else ltp)
                old_lo=old[2] if old[2] is not None else float(lo if pd.notna(lo) else ltp)
                old_vol=old[4] if old[4] is not None else 0
                hi_val=max(float(old_hi),float(hi if pd.notna(hi) else ltp),float(ltp))
                lo_val=min(float(old_lo),float(lo if pd.notna(lo) else ltp),float(ltp))
                vol_val=max(float(old_vol),float(vol if pd.notna(vol) else 0))
            else:
                op=float(r.get("ycp") if pd.notna(r.get("ycp")) and float(r.get("ycp"))>0 else ltp)
                hi_val=float(hi if pd.notna(hi) else ltp); lo_val=float(lo if pd.notna(lo) else ltp)
                vol_val=float(vol if pd.notna(vol) else 0)
            rows.append((today,sym,op,hi_val,lo_val,float(ltp),int(vol_val)))
        con.executemany("INSERT OR REPLACE INTO daily_bars(date,symbol,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",rows)
    set_status("last_daily_update",now())
    set_status("last_daily_rows",len(rows))

def collect_once():
    ts=now()
    live=norm_live(get_current_trade_data())
    if live.empty: raise RuntimeError('DSE live data returned no rows')
    save_quotes(ts,live)
    upsert_today_bar(live)
    save_market(ts,live)
    set_status('last_success',ts)
    set_status('last_rows',len(live))
    sample=live.iloc[0].to_dict() if not live.empty else {}
    logging.info("Collected %s symbols | ts=%s | sample=%s",len(live),ts,sample)
    return live

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--interval',type=int,default=120,help='seconds between DSE polls')
    p.add_argument('--bootstrap',action='store_true',help='download daily history before polling')
    p.add_argument('--history-days',type=int,default=320,help='calendar days of history to download (320 is enough for ~200 trading sessions plus buffer)')
    p.add_argument('--once',action='store_true')
    args=p.parse_args()
    init_db()
    # IMPORTANT: get one LIVE snapshot first. The historical bootstrap can be slow.
    try:
        collect_once()
    except (BDShareError, Exception) as e:
        set_status('last_error',f'{now()} | LIVE | {e}')
        logging.exception('Initial live collection failed: %s', e)

    if args.bootstrap:
        try:
            with connect() as con:
                n=con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
                sym_n=con.execute("SELECT COUNT(DISTINCT symbol) FROM daily_bars").fetchone()[0]
                span=con.execute("SELECT MIN(date), MAX(date) FROM daily_bars").fetchone()
                trading_days=con.execute("SELECT COUNT(DISTINCT date) FROM daily_bars").fetchone()[0]
            # A row-count threshold alone is unsafe: a partial/old DB can have many rows
            # but still lack enough sessions for EMA200.
            ready = bool(span[0] and span[1] and trading_days >= 205 and sym_n >= 100)
            if not ready:
                logging.info("History incomplete: rows=%s symbols=%s trading_days=%s range=%s..%s; downloading %s calendar days...", n, sym_n, trading_days, span[0], span[1], args.history_days)
                bootstrap(args.history_days)
            else:
                logging.info("Historical bootstrap already sufficient: rows=%s symbols=%s trading_days=%s range=%s..%s; skipping re-download.", n, sym_n, trading_days, span[0], span[1])
                set_status('history_bootstrapped_at', get_status('history_bootstrapped_at') or now())
        except Exception as e:
            set_status('history_bootstrap_state', 'FAILED')
            set_status('history_bootstrap_error', f'{type(e).__name__}: {e}')
            set_status('last_error',f'{now()} | HISTORY | {e}')
            logging.exception('Bootstrap failed: %s',e)

    while True:
        try: collect_once()
        except (BDShareError, Exception) as e:
            set_status('last_error',f'{now()} | LIVE | {e}')
            logging.exception('Collection failed')
        if args.once: break
        time.sleep(max(args.interval,30))

if __name__=='__main__': main()

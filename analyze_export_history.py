"""Analyze exported scanner snapshots from New_Action/*.csv.

This does not claim a trade win-rate. It measures signal persistence/downgrade,
price movement after a signal, and how often A/A+ changes before the next snapshot.
"""
import argparse
from pathlib import Path
import pandas as pd


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dir',default='reference_data/7day_exports'); args=ap.parse_args()
    files=sorted(Path(args.dir).glob('*.csv'))
    if not files:
        print('No export CSVs found.'); return
    frames=[]
    for f in files:
        x=pd.read_csv(f)
        x['snapshot_file']=f.name
        x['snapshot_date']=pd.to_datetime(f.name[:10],errors='coerce')
        frames.append(x)
    df=pd.concat(frames,ignore_index=True).sort_values(['symbol','snapshot_date'])
    df['prev_quality']=df.groupby('symbol').entry_quality.shift(1)
    df['prev_action']=df.groupby('symbol').action.shift(1)
    df['next_price']=df.groupby('symbol').ltp.shift(-1)
    df['next_return_pct']=(df.next_price/df.ltp-1)*100
    qr={'A+':1,'A':2,'B':3,'C':4,'D':5}
    df['quality_change']=df.apply(lambda r: 'UP' if qr.get(r.entry_quality,9)<qr.get(r.prev_quality,9) else ('DOWN' if qr.get(r.entry_quality,9)>qr.get(r.prev_quality,9) else 'SAME'),axis=1)
    df.to_csv('output/export_signal_history.csv',index=False)
    # Focus on A/A+ snapshots and what happened by the next snapshot.
    sig=df[df.entry_quality.isin(['A+','A'])].copy()
    if not sig.empty:
        summary=(sig.groupby('entry_quality')
            .agg(signals=('symbol','size'),avg_next_return_pct=('next_return_pct','mean'),
                 positive_next_snapshot_pct=('next_return_pct',lambda s:(s.dropna()>0).mean()*100))
            .reset_index())
        summary.to_csv('output/export_signal_summary.csv',index=False)
        print(summary.to_string(index=False))
    print(f'Analyzed {len(df)} snapshot rows across {df.symbol.nunique()} symbols and {df.snapshot_date.nunique()} snapshots.')

if __name__=='__main__': main()

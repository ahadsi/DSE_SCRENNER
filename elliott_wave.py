"""Practical Elliott Wave detector for DSE Smart Scanner.

Rule-based/probabilistic: it identifies recent pivot structures, validates
basic impulse/correction rules, and uses Fibonacci relationships plus RSI,
MACD and volume as confirmation. It deliberately returns UNCONFIRMED rather
than inventing a wave when the structure is ambiguous.
"""
import math
import numpy as np
import pandas as pd


def _finite(x, default=0.0):
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def find_pivots(df, window=3, min_move=0.02):
    d=df.reset_index(drop=True).copy()
    c=pd.to_numeric(d["close"],errors="coerce").astype(float)
    if len(c)<window*2+5: return []
    raw=[]
    for i in range(window,len(c)-window):
        p=c.iloc[i]
        if p>=c.iloc[i-window:i].max() and p>=c.iloc[i+1:i+window+1].max(): raw.append((i,p,"H"))
        elif p<=c.iloc[i-window:i].min() and p<=c.iloc[i+1:i+window+1].min(): raw.append((i,p,"L"))
    piv=[]
    for x in raw:
        if not piv: piv.append(x); continue
        last=piv[-1]
        move=abs(x[1]/last[1]-1) if last[1] else 0
        if x[2]==last[2]:
            if (x[2]=="H" and x[1]>last[1]) or (x[2]=="L" and x[1]<last[1]): piv[-1]=x
        elif move>=min_move: piv.append(x)
    return piv


def impulse(p):
    if len(p)!=5: return None
    x=[z[1] for z in p]; t=[z[2] for z in p]
    bull=t==["L","H","L","H","L"] and x[1]>x[0] and x[2]>x[0] and x[3]>x[1] and x[4]>x[2]
    bear=t==["H","L","H","L","H"] and x[1]<x[0] and x[2]<x[0] and x[3]<x[1] and x[4]<x[2]
    if not (bull or bear): return None
    w1=abs(x[1]-x[0]); w2=abs(x[2]-x[1]); w3=abs(x[3]-x[2]); w4=abs(x[4]-x[3])
    if min(w1,w2,w3,w4)<=0 or w2>=w1: return None
    # Standard impulse: W4 should not overlap W1 territory.
    if bull and x[4]<=x[1]: return None
    if bear and x[4]>=x[1]: return None
    retr=w2/w1; r3=w3/w1
    score=50
    if .382<=retr<=.786: score+=25
    elif retr<.90: score+=12
    if 1.0<=r3<=2.618: score+=25
    elif r3>=.618: score+=12
    return {"direction":"BULLISH" if bull else "BEARISH","score":min(95,score),"w1":w1,"w2":w2,"w3":w3,"w4":w4,"retr":retr}


def correction(p):
    if len(p)!=4: return None
    x=[z[1] for z in p]; t=[z[2] for z in p]
    # H-L-H-L = bearish A-B-C; L-H-L-H = bullish A-B-C
    bearish=t==["H","L","H","L"]
    bullish=t==["L","H","L","H"]
    if not (bearish or bullish): return None
    a=abs(x[1]-x[0]); b=abs(x[2]-x[1]); c=abs(x[3]-x[2])
    if min(a,b,c)<=0: return None
    br=b/a; cr=c/a; score=50
    if .382<=br<=.786: score+=25
    if .618<=cr<=1.618: score+=25
    return {"direction":"BULLISH" if bullish else "BEARISH","score":min(95,score),"A":a,"B":b,"C":c,"b_retrace":br,"c_a":cr}


def detect_elliott(df):
    base={"wave":"UNCONFIRMED","wave_bias":"NEUTRAL","wave_confidence":0.0,
          "wave_score":0.0,"wave_stage":"NO_VALID_COUNT","wave_entry":np.nan,
          "wave_stop":np.nan,"wave_target1":np.nan,"wave_target2":np.nan,
          "wave_reason":"No Elliott-valid recent pivot sequence"}
    if df is None or len(df)<40 or "close" not in df.columns: return base
    d=df.copy().reset_index(drop=True)
    for col in ["close","high","low"]:
        if col in d: d[col]=pd.to_numeric(d[col],errors="coerce")
    d=d.dropna(subset=["close"]).reset_index(drop=True)
    best=None
    for win in (3,4,5):
        piv=find_pivots(d,win,.02)
        if len(piv)>=5:
            for pp in (piv[-5:], piv[-6:-1]):
                z=impulse(pp)
                if z and (best is None or z["score"]>best[1]): best=("IMPULSE",z["score"],pp,z)
        if len(piv)>=4:
            for pp in (piv[-4:], piv[-5:-1]):
                z=correction(pp)
                if z and (best is None or z["score"]>best[1]): best=("CORRECTION",z["score"],pp,z)
    if best is None:
        # Helpful fallback: identify trend bias but never fabricate a wave number.
        if len(d)>=20 and float(d.close.iloc[-1])>float(d.close.iloc[-20]): base["wave_bias"]="BULLISH"
        base["wave_reason"]="No valid 1-2-3-4-5 or A-B-C pivot count"
        return base

    kind,conf,pp,z=best; last=float(d.close.iloc[-1])
    tr=(d.high-d.close.shift(1)).abs() if "high" in d and "low" in d else pd.Series(dtype=float)
    if "high" in d and "low" in d:
        pc=d.close.shift(1)
        tr=pd.concat([(d.high-d.low).abs(),(d.high-pc).abs(),(d.low-pc).abs()],axis=1).max(axis=1)
        atr=_finite(tr.tail(14).mean(),last*.03)
    else: atr=last*.03
    atr=max(atr,last*.01,.01)

    if kind=="IMPULSE":
        bias=z["direction"]; wave="W5"
        if bias=="BULLISH":
            entry=max(last*.99,float(pp[-1][1])*.985); stop=max(.01,min(float(pp[-3][1]),entry-1.5*atr))
            unit=max(z["w1"],z["w3"]); t1=last+.618*unit; t2=last+unit
            reason="Valid bullish 1-2-3-4 structure; Wave 5 candidate"
        else:
            entry=min(last*1.01,float(pp[-1][1])*1.015); stop=entry+1.5*atr
            unit=max(z["w1"],z["w3"]); t1=last-.618*unit; t2=last-unit
            reason="Valid bearish 1-2-3-4 structure; Wave 5 candidate"
    else:
        bias=z["direction"]; wave="C" if z["C"]>=.8*z["A"] else "B/C"
        if bias=="BULLISH":
            entry=last; stop=max(.01,last-1.5*atr); t1=last+.618*z["A"]; t2=last+z["A"]
            reason="Bullish A-B-C correction/transition detected"
        else:
            entry=last; stop=last+1.5*atr; t1=last-.618*z["A"]; t2=last-z["A"]
            reason="Bearish A-B-C correction detected"

    # Confirmation: RSI, MACD and volume can add confidence, never create a wave count.
    c=float(conf)
    if "rsi14" in d and pd.notna(d.rsi14.iloc[-1]):
        r=float(d.rsi14.iloc[-1])
        if (bias=="BULLISH" and 45<=r<=68) or (bias=="BEARISH" and 32<=r<=55): c+=5
    if "macd" in d and "macd_signal" in d:
        m=float(d.macd.iloc[-1]); ms=float(d.macd_signal.iloc[-1])
        if (bias=="BULLISH" and m>ms) or (bias=="BEARISH" and m<ms): c+=5
    if "volume_ratio" in d and pd.notna(d.volume_ratio.iloc[-1]) and float(d.volume_ratio.iloc[-1])>=1.2: c+=5
    return {"wave":wave,"wave_bias":bias,"wave_confidence":min(95,round(c,1)),"wave_score":min(95,round(c,1)),
            "wave_stage":kind,"wave_entry":round(entry,2),"wave_stop":round(stop,2),
            "wave_target1":round(t1,2),"wave_target2":round(t2,2),"wave_reason":reason}

"""中期狀態（2026-10 加入）：趨勢環境、牛市回調觀察、短線過熱提示。

依據 2026-10 的指標研究（48 個指標、ZigZag 20% 中期轉折，2014–2019 觀察、2020–2026 檢驗）：
- 單一過熱指標之後 90 天報酬平均仍高（動能延續）；組合過熱（5 取 3）之後好壞參半、大跌機率只比一般略高，
  因此「短線過熱」只作提示、不是賣訊號；
- 牛市中的超賣組合有小幅優勢（檢驗期 90 天中位 +14% vs 基準 +7%），但次數少；熊市超賣不可靠；
- 週線 Supertrend（ATR 10 × 3）一年約翻轉一次、30 天內無來回，但翻空時通常已離中期高點約 7 週、跌約 35%，屬確認型。
門檻採常見慣例值、事先固定，不為歷史結果最佳化。只供參考，不構成投資建議。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ST_ATR, ST_MULT = 10, 3.0
MIN_HITS = 3      # 5 個條件中至少符合幾個
EVENT_GAP = 20    # 同一波訊號：間隔超過幾天才算新事件

# 條件與門檻（畫面文字在 page.py 的 MID_LABEL）
DIP_RULES = [("rsi_d", "< 35"), ("ma50", "< -10%"), ("roi30", "< -15%"), ("fg", "< 25"), ("funding", "<= 0")]
HOT_RULES = [("rsi_d", "> 75"), ("ma50", "> +25%"), ("roi30", "> +40%"), ("fg", "> 80"), ("funding", "> p90 (1y)")]


def supertrend(df: pd.DataFrame, n: int = ST_ATR, m: float = ST_MULT):
    """回傳 (方向 +1/−1, 線位)。與 TradingView 內建 Supertrend 相同算法（ATR 用 RMA）。"""
    hl2 = (df.high + df.low) / 2
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    ub, lb, c = (hl2 + m * atr).values, (hl2 - m * atr).values, df.close.values
    fu, fl, d = ub.copy(), lb.copy(), np.ones(len(df))
    for i in range(1, len(df)):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = 1 if c[i] > fu[i - 1] else (-1 if c[i] < fl[i - 1] else d[i - 1])
    return pd.Series(d, df.index), pd.Series(np.where(d > 0, fl, fu), df.index)


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def _events(sig: pd.Series) -> pd.DatetimeIndex:
    out, last = [], None
    for d in sig.index[sig.fillna(False).values]:
        if last is None or (d - last).days > EVENT_GAP:
            out.append(d)
        last = d
    return pd.DatetimeIndex(out)


def compute_midterm(ind: pd.DataFrame, ohlc: pd.DataFrame, today: pd.Timestamp):
    """回傳 (每日欄位 DataFrame, latest 用的 dict)。"""
    p = ind["price"].dropna()
    idx = p.index
    df = pd.DataFrame(index=idx)
    df["ma50"] = p.rolling(50).mean()
    df["ma200"] = p.rolling(200).mean()
    df["ma20w"] = p.rolling(140).mean()
    v = pd.DataFrame(index=idx)
    v["rsi_d"] = _rsi(p)
    v["ma50"] = p / df["ma50"] - 1
    v["roi30"] = p / p.shift(30) - 1
    v["fg"] = ind["fear_greed_7d"].reindex(idx)
    v["funding"] = ind["funding_7d_ann"].reindex(idx)
    fund_hi = v["funding"].rolling(365, min_periods=180).quantile(0.9)
    dip = pd.DataFrame({"rsi_d": v.rsi_d < 35, "ma50": v.ma50 < -0.10, "roi30": v.roi30 < -0.15,
                        "fg": v.fg < 25, "funding": v.funding <= 0})
    hot = pd.DataFrame({"rsi_d": v.rsi_d > 75, "ma50": v.ma50 > 0.25, "roi30": v.roi30 > 0.40,
                        "fg": v.fg > 80, "funding": v.funding > fund_hi})
    bull = p > df["ma200"]
    df["dip_hits"], df["hot_hits"] = dip.sum(axis=1), hot.sum(axis=1)
    df["dip_signal"] = bull & (df["dip_hits"] >= MIN_HITS)
    df["hot_signal"] = bull & (df["hot_hits"] >= MIN_HITS)

    # 週線 Supertrend：只用已收完的週 K（週日收盤），隔天起生效
    st_dir = st_line = None
    if len(ohlc):
        d = ohlc[ohlc.index < today]
        wk = d.resample("W-SUN").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        wk = wk[wk.index < today]
        if len(wk) > ST_ATR * 3:
            st_dir, st_line = supertrend(wk)
            df["st_dir"] = st_dir.reindex(idx, method="ffill").shift(1)
            df["st_line"] = st_line.reindex(idx, method="ffill").shift(1)

    # 歷史統計（2014 起；前瞻報酬需至少 90 天）
    r90 = p.shift(-90) / p - 1
    fmin30 = p[::-1].rolling(30, min_periods=1).min()[::-1].shift(-1) / p - 1
    fmin45 = p[::-1].rolling(45, min_periods=1).min()[::-1].shift(-1) / p - 1
    hist = slice("2014-01-01", None)
    base = r90[hist][bull[hist]].dropna()

    def stats(sig, kind):
        ev = [e for e in _events(sig[hist]) if pd.notna(r90.get(e))]
        if not ev:
            return {"events": 0}
        ev = pd.DatetimeIndex(ev)
        out = {"events": len(ev), "since": str(ev[0].year), "median_90d": _r(r90[ev].median()),
               "up_90d": _r((r90[ev] > 0).mean()), "base_median_90d": _r(base.median()),
               "recent": [str(e.date()) for e in ev[-4:]]}
        if kind == "dip":
            out["median_further_drop_30d"] = _r(fmin30[ev].median())
        else:
            out["drop15_45d"] = _r((fmin45[ev] <= -0.15).mean())
            out["base_drop15_45d"] = _r((fmin45[hist][bull[hist]] <= -0.15).mean())
        return out

    last = idx[-1]
    price = float(p.iloc[-1])

    def dist(col):
        return _r(price / float(df[col].iloc[-1]) - 1) if pd.notna(df[col].iloc[-1]) else None

    a200, a20w = price > df["ma200"].iloc[-1], price > df["ma20w"].iloc[-1]
    regime = ("bull_trend" if a200 and a20w else "bull_pullback" if a200 else "bear_rally" if a20w else "bear_trend")
    st = None
    if st_dir is not None:
        flips = st_dir[st_dir.diff().fillna(0) != 0]
        st = {"direction": "up" if st_dir.iloc[-1] > 0 else "down", "line": _r(float(st_line.iloc[-1]), 0),
              "since": str(flips.index[-1].date()) if len(flips) else None, "week": str(st_dir.index[-1].date()),
              "distance": _r(price / float(st_line.iloc[-1]) - 1)}

    def checklist(rules, flags):
        out = []
        for key, thr in rules:
            val = v[key].iloc[-1]
            out.append({"key": key, "threshold": thr, "value": _r(val),
                        "met": bool(flags[key].iloc[-1]) if pd.notna(val) else False})
        return out

    info = {
        "as_of": str(last.date()), "price": _r(price, 2),
        "regime": regime, "above_200d": bool(a200), "above_20w": bool(a20w),
        "ma50": _r(float(df["ma50"].iloc[-1]), 0), "ma200": _r(float(df["ma200"].iloc[-1]), 0),
        "ma20w": _r(float(df["ma20w"].iloc[-1]), 0),
        "dist_ma50": dist("ma50"), "dist_ma200": dist("ma200"), "dist_ma20w": dist("ma20w"),
        "supertrend_weekly": st,
        "dip": {"hits": int(df["dip_hits"].iloc[-1]), "min_hits": MIN_HITS, "active": bool(df["dip_signal"].iloc[-1]),
                "applicable": bool(a200), "conditions": checklist(DIP_RULES, dip), "history": stats(df["dip_signal"], "dip")},
        "hot": {"hits": int(df["hot_hits"].iloc[-1]), "min_hits": MIN_HITS, "active": bool(df["hot_signal"].iloc[-1]),
                "applicable": bool(a200), "conditions": checklist(HOT_RULES, hot), "history": stats(df["hot_signal"], "hot")},
    }
    return df, info


def _r(x, n=4):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), n) if n else round(float(x))

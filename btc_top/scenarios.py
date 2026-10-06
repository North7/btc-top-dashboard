"""未來情境（2026-10 加入，經使用者同意）：三條「歷史規律外推」的價格路徑，不是預測。

- 保守：頂部 ÷ 前一輪低點的倍數，以最近三輪（2017、2021、2025）對數線性外推，乘上本輪低點。
- 中間：頂部 MVRV（價格 ÷ 實現價格）以四次頂部對數線性外推，乘上「實現價格依近 4 年年增率推到頂部日」。
- 樂觀：冪律趨勢價（頂部倍數取 1.0；全部歷史擬合）。
頂部日期：兩個時機時鐘預估中心的中點。路徑形狀：過去三輪「低點 → 頂部」的對數價格走法（時間、漲幅各自標準化後平均），
從今天的價格接到各情境頂部。每日依最新數據重算。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from btc_top import scoring as S

GRID = 200


def _next(vals) -> float:
    """對數線性擬合後的下一個值。"""
    x = np.arange(len(vals))
    b, a = np.polyfit(x, np.log(vals), 1)
    return float(np.exp(a + b * len(vals)))


def _shape(price: pd.Series, pairs) -> np.ndarray:
    """過去各輪低點 → 頂部的標準化走法平均（0→1）。"""
    curves = []
    for lo, top in pairs:
        seg = np.log(price[lo:top].values)
        f = (seg - seg[0]) / (seg[-1] - seg[0])
        curves.append(np.interp(np.linspace(0, 1, GRID), np.linspace(0, 1, len(f)), f))
    c = np.clip(np.mean(curves, axis=0), 0, 1)
    k = 31  # 移動平均平滑（約 15% 的週期長度），再取單調遞增，避免階梯狀
    pad = np.concatenate([np.full(k, c[0]), c, np.full(k, c[-1])])
    c = np.convolve(pad, np.ones(k) / k, mode="same")[k:-k]
    c = np.maximum.accumulate(c)
    return (c - c[0]) / (c[-1] - c[0])


def compute_scenarios(ind: pd.DataFrame, timing: dict, today: pd.Timestamp) -> dict:
    price = ind["price"].dropna()
    tops = [price[m].idxmax() for m in [S.PRE_TOP_MONTH] + list(S.TOP_MONTHS)]
    lows = [price[tops[k]:tops[k + 1]].idxmin() for k in range(len(tops) - 1)]  # 每個頂部之前的低點
    cur_low = pd.Timestamp(timing["cycle_low_date"])
    now_d, now_p = price.index[-1], float(price.iloc[-1])

    c1 = pd.Timestamp(timing["expected_window_by_low"]["center"])
    c2 = pd.Timestamp(timing["expected_window_by_halving"]["center"])
    top_d = (c1 + (c2 - c1) / 2).normalize()

    # 保守：頂部 ÷ 前低（最近三輪）
    r_low = [price[tops[k + 1]] / price[lows[k]] for k in range(1, len(lows))]
    cons = price[cur_low] * _next(r_low)
    # 中間：頂部 MVRV × 實現價格成長
    rp = ind["realized_price"].dropna()
    mv = [float(ind["rp_multiple"][t]) for t in tops[1:]]
    g = (rp.iloc[-1] / rp[rp.index >= rp.index[-1] - pd.Timedelta(days=1461)].iloc[0]) ** (1 / 4)
    yrs = (top_d - rp.index[-1]).days / 365.25
    mid = float(rp.iloc[-1] * g ** yrs * _next(mv))
    # 樂觀：冪律趨勢價
    age = lambda d: (pd.Timestamp(d) - pd.Timestamp("2009-01-03")).days
    b, a = np.polyfit(np.log10([age(d) for d in price.index]), np.log10(price.values), 1)
    opt = float(10 ** (a + b * np.log10(age(top_d))))

    shape = _shape(price, [(lows[k], tops[k + 1]) for k in range(1, len(lows))])
    span = (top_d - cur_low).days
    t0 = (now_d - cur_low).days / span
    f0 = float(np.interp(t0, np.linspace(0, 1, GRID), shape))
    dates = pd.date_range(now_d, top_d, freq="7D")
    if dates[-1] != top_d:
        dates = dates.append(pd.DatetimeIndex([top_d]))
    tau = np.array([(d - cur_low).days / span for d in dates])
    f = np.interp(tau, np.linspace(0, 1, GRID), shape)
    w = np.clip((f - f0) / max(1e-9, 1 - f0), 0, 1)

    def path(top_p):
        return [round(float(np.exp(np.log(now_p) + x * (np.log(top_p) - np.log(now_p)))), 0) for x in w]

    sc = {"conservative": cons, "base": mid, "optimistic": opt}
    return {
        "as_of": str(now_d.date()), "price": round(now_p, 2), "top_date": str(top_d.date()),
        "window": {"from": min(timing["expected_window_by_low"]["full_from"], timing["expected_window_by_halving"]["full_from"]),
                   "to": max(timing["expected_window_by_low"]["full_to"], timing["expected_window_by_halving"]["full_to"])},
        "tops": {k: round(v, 0) for k, v in sc.items()},
        "inputs": {"top_over_prior_low": [round(float(x), 2) for x in r_low], "next_top_over_low": round(_next(r_low), 2),
                   "cycle_low": round(float(price[cur_low]), 2), "top_mvrv": [round(x, 2) for x in mv], "next_top_mvrv": round(_next(mv), 2),
                   "realized_price": round(float(rp.iloc[-1]), 0), "realized_growth": round(float(g - 1), 4),
                   "powerlaw_slope": round(float(b), 3),
                   "top_over_prior_top": [round(float(price[tops[k + 1]] / price[tops[k]]), 2) for k in range(1, len(tops) - 1)],
                   "ratio_method_top": round(float(price[tops[-1]] * _next([price[tops[k + 1]] / price[tops[k]] for k in range(1, len(tops) - 1)])), 0)},
        "dates": [str(d.date()) for d in dates],
        "paths": {k: path(v) for k, v in sc.items()},
    }


def track_scenarios(snap: dict, price: pd.Series) -> dict:
    """定案日凍結的三條路徑 vs 實際價格：今天各情境「當時預估的價格」與實際的差距、最貼近哪一條。"""
    p = price.dropna()
    d, now = p.index[-1], float(p.iloc[-1])
    dates = pd.to_datetime(snap["dates"])
    t = np.array([(x - dates[0]).days for x in dates], float)
    td = (d - dates[0]).days
    rows = {}
    for k, path in snap["paths"].items():
        v = float(np.exp(np.interp(td, t, np.log(path))))
        rows[k] = {"expected": round(v, 0), "diff": round(now / v - 1, 4) + 0.0}
    closest = min(rows, key=lambda k: abs(np.log(now / rows[k]["expected"])))
    return {"snapshot_date": snap["as_of"], "as_of": str(d.date()), "price": round(now, 2), "rows": rows, "closest": closest,
            "tops": snap["tops"], "top_date": snap["top_date"]}

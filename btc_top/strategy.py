"""週期策略（2026-10 加入，經使用者同意公開）：「警戒 + 趨勢確認」，含逐輪回測與模擬資金曲線。

規則（門檻事先固定為 50，未針對歷史最佳化；40/50/60 的 27 種組合回測皆勝過持有）：
- 持有中：頂部訊號 ≥ 50 或頂部時機 ≥ 50 → 進入警戒（保持到賣出）；警戒中週線 Supertrend 由多轉空 → 全部賣出。
- 空手中：底部訊號 ≥ 50 或週線 Supertrend 由空轉多 → 全部買回。

逐輪回測：日期落在第 k 個頂部之前的那一輪時，訊號參數只用當時已發生的頂部與底部計算（不偷看未來）；
最後一輪（2025-10 頂部之後）即網站目前的訊號。第一輪只有 2013 一個減半後頂部，另加入 2011 頂部才能算出冷度。
模擬：每次換倉手續費 0.1%，空手時現金不計利息。只供參考，不構成投資建議。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from btc_top import scoring as S

ARM_SIG, ARM_TIM, BUY_BSIG = 50, 50, 50
FEE = 0.001
START = "2014-01-01"
STARTS = ["2014-01-01", "2016-01-01", "2018-01-01", "2020-01-01", "2022-01-01"]
# 每一輪「當時已知」的頂部月份（第 0 輪需要 2011 頂部才有已知底部）
KNOWN = [["2011-06", "2013-12"], ["2011-06", "2013-12", "2017-12"], ["2013-12", "2017-12", "2021-11"]]


def _signals(ind: pd.DataFrame, months) -> pd.DataFrame:
    """只用 months 這些頂部計算 頂部訊號、頂部時機、底部訊號。"""
    _, _, _, heat, _, tops, bottoms = S.compute_heat(ind.copy(), months)
    h0 = S.HALVINGS[0]  # 減半前的頂部／底部沒有「距減半天數」
    tops_h = [t for t in tops if t >= h0]
    bots_h = [b for b in bottoms if b >= h0]
    tim, _ = S.compute_timing(ind.index, ind["price"], tops_h)
    out = pd.DataFrame({"sig": S.top_signal(heat, tim["timing"]), "tim": tim["timing"]})
    if bots_h:
        _, _, cold, _, _ = S.compute_cold(ind, tops, bottoms)
        btim, _ = S.compute_bottom_timing(ind.index, ind["price"], tops_h, bots_h)
        out["bsig"] = S.bottom_signal(cold, btim["timing"])
    else:
        out["bsig"] = np.nan
    return out


def walk_forward(ind: pd.DataFrame, live: pd.DataFrame) -> pd.DataFrame:
    """拼接逐輪訊號；live 為網站目前（全部頂部）的 sig/tim/bsig。"""
    tops = [ind["price"][m].idxmax() for m in S.TOP_MONTHS]
    seg = np.searchsorted(np.array(tops, dtype="datetime64[ns]"), ind.index.values, side="left")
    parts = [_signals(ind, m) for m in KNOWN] + [live]
    out = pd.DataFrame(index=ind.index, columns=["sig", "tim", "bsig"], dtype=float)
    for k in range(len(tops) + 1):
        mask = seg == k
        src = parts[max(k - 1, 0)] if k <= len(KNOWN) else live
        out.loc[mask] = src.loc[mask, ["sig", "tim", "bsig"]].values
    return out


def positions(sig, tim, bsig, st):
    """逐日狀態機。回傳 (持倉 0/1, 交易列表, 每日是否警戒)。"""
    pos, armed_s, trades = [], [], []
    s, armed, prev = 1.0, False, np.nan
    for d in sig.index:
        a, tm, b, t = sig.get(d), tim.get(d), bsig.get(d), st.get(d)
        why = None
        if s > 0 and ((a >= ARM_SIG) or (tm >= ARM_TIM)):
            if not armed:
                trades.append({"date": d, "action": "arm", "why": "sig" if a >= ARM_SIG else "tim"})
            armed = True
        if s > 0 and armed and t < 0 and prev > 0:
            s, armed, why = 0.0, False, "st_down"
        elif s == 0 and ((b >= BUY_BSIG) or (t > 0 and prev < 0)):
            s, why = 1.0, ("bsig" if b >= BUY_BSIG else "st_up")
        if why:
            trades.append({"date": d, "action": "sell" if s == 0 else "buy", "why": why})
        pos.append(s)
        armed_s.append(armed)
        prev = t
    return pd.Series(pos, index=sig.index), trades, pd.Series(armed_s, index=sig.index)


def backtest(price: pd.Series, pos: pd.Series, start: str):
    p = price[start:].dropna()
    r = p.pct_change().fillna(0)
    w = pos.reindex(p.index).shift(1).fillna(1.0)  # 收盤決定、隔天生效
    turn = w.diff().abs().fillna(0)
    eq = (1 + w * r - turn * FEE).cumprod()
    bh = p / p.iloc[0]
    yrs = (p.index[-1] - p.index[0]).days / 365.25
    dd = lambda e: float((e / e.cummax() - 1).min())
    return {"start": start[:4], "strategy": _r(eq.iloc[-1], 2), "hold": _r(bh.iloc[-1], 2), "ratio": _r(eq.iloc[-1] / bh.iloc[-1], 2),
            "cagr": _r(eq.iloc[-1] ** (1 / yrs) - 1), "cagr_hold": _r(bh.iloc[-1] ** (1 / yrs) - 1),
            "max_dd": _r(dd(eq)), "max_dd_hold": _r(dd(bh)), "time_in": _r(w.mean())}, eq, bh


def compute_strategy(ind: pd.DataFrame, live: pd.DataFrame, st: pd.Series, today: pd.Timestamp):
    """回傳 (每日欄位：資金曲線、持倉, latest 用的 dict)。"""
    price = ind["price"].dropna()
    wf = walk_forward(ind, live).reindex(price.index)
    st = st.reindex(price.index)
    pos, trades, armed = positions(wf["sig"], wf["tim"], wf["bsig"], st)
    m, eq, bh = backtest(price, pos, START)
    stats = [backtest(price, pos, s)[0] for s in STARTS]

    # 交易紀錄（含每次「賣出 → 買回」與「買回 → 賣出」的價格變化）
    tl = [t for t in trades if t["date"] >= pd.Timestamp(START)]
    rows = []
    for t in tl:
        if t["action"] == "arm":
            continue
        rows.append({"date": str(t["date"].date()), "action": t["action"], "why": t["why"], "price": _r(price[t["date"]], 2)})
    for i, r in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        r["next_price_change"] = _r(nxt["price"] / r["price"] - 1) if nxt else None

    last = price.index[-1]
    holding = bool(pos.iloc[-1] > 0)
    last_trade = rows[-1] if rows else None
    info = {
        "rules": {"arm_top_signal": ARM_SIG, "arm_top_timing": ARM_TIM, "buy_bottom_signal": BUY_BSIG, "fee": FEE,
                  "supertrend": "weekly ATR 10 x 3"},
        "as_of": str(last.date()),
        "state": "holding" if holding else "cash",
        "armed": bool(armed.iloc[-1]),
        "since": last_trade["date"] if last_trade else None, "since_price": last_trade["price"] if last_trade else None,
        "now": {"top_signal": _r(live["sig"].iloc[-1], 1), "top_timing": _r(live["tim"].iloc[-1], 1),
                "bottom_signal": _r(live["bsig"].iloc[-1], 1),
                "supertrend": "up" if st.iloc[-1] > 0 else "down"},
        "backtest": m, "by_start": stats, "trades": rows,
    }
    df = pd.DataFrame({"strat_eq": eq, "strat_bh": bh, "strat_pos": pos.reindex(eq.index)})
    return df, info


def _r(x, n=4):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), n)


def projected_arm(timing: dict, today: pd.Timestamp):
    """依時鐘推算「頂部時機 ≥ 50」最早的日期（假設本輪低點不再被跌破、減半日期不變）。"""
    days = pd.date_range(today, today + pd.Timedelta(days=365 * 6))
    last_h = pd.Series([S.HALVINGS[S.HALVINGS <= d].max() for d in days], index=days)
    dh = pd.Series((days - pd.DatetimeIndex(last_h.values)).days, index=days, dtype=float)
    dl = pd.Series((days - pd.Timestamp(timing["cycle_low_date"])).days, index=days, dtype=float)
    score = (S._trap(dh, timing["center_halving_days"]) + S._trap(dl, timing["center_low_days"])) / 2 * 100
    hit = score[score >= ARM_TIM]
    return str(hit.index[0].date()) if len(hit) else None

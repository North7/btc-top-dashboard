"""週期策略（2026-10 加入，經使用者同意公開）：「警戒 + 趨勢確認」，含逐輪回測與模擬資金曲線。

規則（門檻事先固定為 50，未針對歷史最佳化；40/50/60 的 27 種組合皆勝過持有，但實際只產生 3 條不同的持倉路徑）：
- 持有中：頂部訊號 ≥ 50 或頂部時機 ≥ 50 → 進入警戒（保持到賣出）；警戒中週線 Supertrend 由多轉空 → 全部賣出。
  注意：頂部訊號 = 熱度 × 時機 ÷ 100 ≤ 時機，所以這個條件實際上等於「頂部時機 ≥ 50」，熱度不影響交易（外部審查指出）。
- 空手中：底部訊號 ≥ 50 或週線 Supertrend 由空轉多 → 全部買回。

逐輪回測：日期落在第 k 個頂部之前的那一輪時，訊號參數只用當時已發生的頂部與底部計算（不偷看未來）；
最後一輪（2025-10 頂部之後）即網站目前的訊號。第一輪只有 2013 一個減半後頂部，另加入 2011 頂部才能算出冷度。
模擬：每次換倉手續費 0.1%，空手時現金不計利息。只供參考，不構成投資建議。
各起點的回測都從「滿倉、未警戒」重新開始（不沿用起點以前的警戒狀態）。
已知限制：頂部日期是事後指定、資料修訂沒有保留當時版本，所以「無前視」尚未被完整證明；
定案日之後的每日決策寫入 data/strategy_ledger.csv（只新增、不改寫），實際追蹤以這份紀錄為準。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from btc_top import scoring as S

ARM_SIG, ARM_TIM, BUY_BSIG = 50, 50, 50
FINAL_DATE = "2026-10-06"  # 策略定案日：之前是回測，之後是實際追蹤（規則不可再為績效調整）
BATCH_KEEP = 2 / 3  # 分批版（對照用）：進入警戒時先賣 1/3，週線 Supertrend 轉空再賣完
FEE = 0.001
START = "2014-01-01"
CHART_STARTS = ["2018", "2022"]  # 資金曲線圖可切換的其他起點（2014 即主曲線）
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


def positions(sig, tim, bsig, st, keep_on_alert: float = 1.0):
    """逐日狀態機。回傳 (持倉, 交易列表, 每日是否警戒)。keep_on_alert < 1 為分批版：進入警戒時先降到此倉位。"""
    pos, armed_s, trades = [], [], []
    s, armed, prev = 1.0, False, np.nan
    for d in sig.index:
        a, tm, b, t = sig.get(d), tim.get(d), bsig.get(d), st.get(d)
        why = None
        if s > 0 and ((a >= ARM_SIG) or (tm >= ARM_TIM)):
            if not armed:
                trades.append({"date": d, "action": "arm", "why": "sig" if a >= ARM_SIG else "tim"})
                s = min(s, keep_on_alert)
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


def fresh(wf: pd.DataFrame, st: pd.Series, start: str, keep_on_alert: float = 1.0) -> pd.Series:
    """從 start 當天以「滿倉、未警戒」重新開始跑狀態機。"""
    f = wf.loc[start:]
    return positions(f["sig"], f["tim"], f["bsig"], st.reindex(f.index), keep_on_alert)[0]


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


def _alerts(trades: list, start: str) -> list:
    """警戒期間：進入警戒 → 賣出（尚未賣出則到今天）；start 以前開始、之後才賣出的警戒也保留。"""
    out, cur = [], None
    for t in trades:
        if t["action"] == "arm":
            cur = {"from": str(t["date"].date()), "to": None, "why": t["why"]}
            out.append(cur)
        elif t["action"] == "sell" and cur is not None:
            cur["to"], cur = str(t["date"].date()), None
    return [x for x in out if x["to"] is None or x["to"] >= start]


def compute_strategy(ind: pd.DataFrame, live: pd.DataFrame, st: pd.Series, today: pd.Timestamp, ledger_path=None):
    """回傳 (每日欄位：資金曲線、持倉, latest 用的 dict)。ledger_path：不可改寫的每日決策紀錄（CSV）。"""
    price = ind["price"].dropna()
    wf = walk_forward(ind, live).reindex(price.index)
    st = st.reindex(price.index)
    pos, trades, armed = positions(wf["sig"], wf["tim"], wf["bsig"], st)
    m, eq, bh = backtest(price, pos, START)
    stats = [backtest(price, fresh(wf, st, s), s)[0] for s in STARTS]
    pos_b, _, _ = positions(wf["sig"], wf["tim"], wf["bsig"], st, BATCH_KEEP)
    mb, eqb, _ = backtest(price, pos_b, START)
    stats_b = [backtest(price, fresh(wf, st, s, BATCH_KEEP), s)[0] for s in STARTS]
    alerts = _alerts(trades, START)
    # 圖表切換 2018／2022 起點時，用各自「重新開始」的資金曲線與買賣點（與績效表一致）
    runs, extra = {}, {}
    for y in CHART_STARTS:
        f = wf.loc[f"{y}-01-01":]
        p_y, t_y, _ = positions(f["sig"], f["tim"], f["bsig"], st.reindex(f.index))
        extra[f"strat_eq_{y}"] = backtest(price, p_y, f"{y}-01-01")[1]
        extra[f"strat_eq_b_{y}"] = backtest(price, fresh(wf, st, f"{y}-01-01", BATCH_KEEP), f"{y}-01-01")[1]
        runs[y] = {k: [str(t["date"].date()) for t in t_y if t["action"] == k] for k in ("sell", "buy")}
        runs[y]["alerts"] = _alerts(t_y, f"{y}-01-01")

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
        "backtest": m, "by_start": stats, "trades": rows, "alerts": alerts, "chart_runs": runs,
        "live": _live(price, pos, rows, _ledger(ledger_path, wf, st, pos, armed, price)),
        "batch": {"keep_on_alert": _r(BATCH_KEEP), "position": _r(pos_b.iloc[-1]), "backtest": mb, "by_start": stats_b},
    }
    df = pd.DataFrame({"strat_eq": eq, "strat_bh": bh, "strat_eq_b": eqb, "strat_pos": pos.reindex(eq.index), **extra})
    return df, info


LEDGER_COLS = ["date", "price", "top_signal", "top_timing", "bottom_signal", "supertrend", "armed", "position", "recorded_at"]


def _ledger(path, wf, st, pos, armed, price) -> pd.DataFrame | None:
    """定案日之後的每日決策：只新增當天以前尚未記錄的日期，既有列一律不改寫。回傳完整紀錄。"""
    if path is None:
        return None
    from pathlib import Path
    path = Path(path)
    old = pd.read_csv(path, dtype={"date": str}) if path.exists() else pd.DataFrame(columns=LEDGER_COLS)
    done = set(old["date"])
    now = pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%MZ")
    new = []
    for d in price[FINAL_DATE:].dropna().index:
        k = str(d.date())
        if k in done:
            continue
        new.append({"date": k, "price": _r(price[d], 2), "top_signal": _r(wf.at[d, "sig"], 2), "top_timing": _r(wf.at[d, "tim"], 2),
                    "bottom_signal": _r(wf.at[d, "bsig"], 2), "supertrend": int(st.get(d)) if pd.notna(st.get(d)) else None,
                    "armed": bool(armed.get(d)), "position": _r(pos.get(d)), "recorded_at": now})
    if new:
        old = pd.concat([old, pd.DataFrame(new, columns=LEDGER_COLS)], ignore_index=True) if len(old) else pd.DataFrame(new, columns=LEDGER_COLS)
        old.to_csv(path, index=False)
    return old


def _live(price: pd.Series, pos: pd.Series, rows: list, ledger: pd.DataFrame | None = None) -> dict:
    """定案日之後的實際追蹤：有決策紀錄時，持倉以紀錄為準（不受之後資料修訂或程式改動影響）。"""
    p = price[FINAL_DATE:].dropna()
    out = {"final_date": FINAL_DATE, "days": int(max(0, (price.index[-1] - pd.Timestamp(FINAL_DATE)).days)),
           "trades": [t for t in rows if t["date"] >= FINAL_DATE]}
    if ledger is not None and len(ledger):
        lp = pd.Series(ledger["position"].astype(float).values, index=pd.to_datetime(ledger["date"]))
        diff = int((lp != pos.reindex(lp.index)).sum())
        out.update({"source": "ledger", "ledger_rows": int(len(lp)), "recomputed_differs": diff})
        pos = pos.copy()
        pos.loc[lp.index] = lp.values
    if len(p) >= 2:
        m, _, _ = backtest(price, pos, FINAL_DATE)
        out.update({"strategy": m["strategy"], "hold": m["hold"], "max_dd": m["max_dd"], "max_dd_hold": m["max_dd_hold"]})
    else:
        out.update({"strategy": 1.0, "hold": 1.0, "max_dd": 0.0, "max_dd_hold": 0.0})
    return out


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

"""新指標驗證：用 data/raw 的歷史資料檢查候選指標在歷史頂部、底部與假訊號的表現。只讀資料，不寫任何檔案。

用法（在倉庫根目錄）：
  .venv/bin/python .claude/skills/validate-indicator/validate.py --name "SSR" \
      --expr "cm.CapMrktCurUSD / raw['stablecoins'].stable_supply_usd.reindex(cm.index).ffill(limit=5)" \
      --transform z200 --above 2 --below -2

--expr 可用的變數：ind（網站的指標表，含 price、mvrv_z、nupl…）、raw（各原始資料 DataFrame）、
cm（Coin Metrics 原始欄位，已對齊日期）、price、np、pd。
--csv/--col：改用外部 CSV（第一欄為日期）。外部資料只能在本機研究，不可寫入倉庫。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from btc_top import scoring as S  # noqa: E402

# 中段假頂（熱度常高於真頂部）與中段假底（急跌但不是週期底部）：取該月最高／最低收盤日
FALSE_TOPS = ["2019-06", "2021-04", "2024-03"]
FALSE_BOTTOMS = ["2019-12", "2020-03", "2021-07", "2024-08"]


def load():
    raw = {p.stem: pd.read_csv(p, index_col=0, parse_dates=True) for p in (ROOT / "data/raw").glob("*.csv")}
    ind = S.build_indicators(raw)
    cm = raw["coinmetrics"].reindex(ind.index)
    return raw, ind, cm


def transform(s: pd.Series, how: str | None) -> pd.Series:
    if not how:
        return s
    if how.startswith("z"):  # 相對 N 日均值的標準差倍數
        n = int(how[1:])
        return (s - s.rolling(n).mean()) / s.rolling(n).std()
    if how.startswith("ma"):  # 相對 N 日均線的倍數
        n = int(how[2:])
        return s / s.rolling(n).mean()
    if how == "log":
        return np.log(s)
    raise SystemExit(f"不認得的 --transform：{how}")


def at(s: pd.Series, d: pd.Timestamp, win: int = 0):
    if win:
        w = s[d - pd.Timedelta(days=win):d + pd.Timedelta(days=win)]
        return w.max() if len(w.dropna()) else np.nan
    return s.get(d, np.nan)


def fmt(x, n=3):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{n}f}"


def events(s: pd.Series, cond: pd.Series, gap: int = 60) -> list[pd.Timestamp]:
    """條件由否轉是的日子；距上一次事件不足 gap 天的不算新事件。"""
    hit = cond & ~cond.shift(1, fill_value=False)
    out, last = [], None
    for d in hit[hit].index:
        if last is None or (d - last).days >= gap:
            out.append(d)
        last = d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--expr")
    ap.add_argument("--csv")
    ap.add_argument("--col")
    ap.add_argument("--transform", help="z200（200 日標準差倍數）、ma200（相對 200 日均線）、log")
    ap.add_argument("--above", type=float, help="事件：由下往上穿越此值")
    ap.add_argument("--below", type=float, help="事件：由上往下穿越此值")
    ap.add_argument("--start", default="2012-01-01", help="分析起點（早期資料太少時調後）")
    a = ap.parse_args()

    raw, ind, cm = load()
    price = ind["price"]
    if a.csv:
        s = pd.read_csv(a.csv, index_col=0, parse_dates=True)[a.col].reindex(ind.index)
    else:
        s = eval(a.expr, {"ind": ind, "raw": raw, "cm": cm, "price": price, "np": np, "pd": pd})  # noqa: S307
        s = pd.Series(s, index=ind.index) if not isinstance(s, pd.Series) else s.reindex(ind.index)
    s = transform(s.astype(float), a.transform)[a.start:].replace([np.inf, -np.inf], np.nan)
    v = s.dropna()
    if v.empty:
        raise SystemExit("指標沒有任何數值")

    tops, bottoms = S.find_cycles(price.dropna())
    ftops = [price[m].idxmax() for m in FALSE_TOPS]
    fbots = [price[m].idxmin() for m in FALSE_BOTTOMS]
    cur_low = price[tops[-1]:].idxmin()

    print(f"# 指標驗證：{a.name}\n")
    print(f"- 資料範圍：{v.index[0].date()} ～ {v.index[-1].date()}（{len(v):,} 天）")
    n_top = sum(pd.notna(at(s, t)) for t in tops)
    n_bot = sum(pd.notna(at(s, b)) for b in bottoms)
    print(f"- 涵蓋週期頂部 {n_top}/{len(tops)} 次、週期底部 {n_bot}/{len(bottoms)} 次"
          + ("（不足 3 次：無法用週期法驗證，只能看百分位或當參考）" if min(n_top, n_bot) < 3 else ""))
    pct = v.rolling("1460D", min_periods=365).rank(pct=True) * 100
    print(f"- 目前：{fmt(v.iloc[-1])}（4 年百分位 {fmt(pct.iloc[-1], 0)}%）\n")

    print("## 頂部：真頂部要比中段假頂高，才分得出來\n")
    print("| 類型 | 日期 | 當日值 | 前後 30 天最高 |\n|---|---|---|---|")
    for t in tops:
        print(f"| 週期頂部 | {t.date()} | {fmt(at(s, t))} | {fmt(at(s, t, 30))} |")
    for t in ftops:
        print(f"| 中段假頂 | {t.date()} | {fmt(at(s, t))} | {fmt(at(s, t, 30))} |")
    tv = [at(s, t, 30) for t in tops if pd.notna(at(s, t, 30))]
    fv = [at(s, t, 30) for t in ftops if pd.notna(at(s, t, 30))]
    if tv and fv:
        gap = min(tv) - max(fv)
        print(f"\n跨輪分辨力（真頂部最低 − 假頂最高）：{fmt(gap)} → {'分得開' if gap > 0 else '分不開（假頂不低於真頂部）'}")
        ok = []
        for f in ftops:  # 同一輪比較：假頂 vs 它之後的那個真頂部（頂部讀數逐輪遞減，同輪比較較公平）
            nxt = next((t for t in tops if t > f), None)
            fv1, tv1 = at(s, f, 30), at(s, nxt, 30) if nxt is not None else np.nan
            if pd.notna(fv1) and pd.notna(tv1):
                ok.append(tv1 > fv1)
                print(f"- 同輪：假頂 {f.date()} {fmt(fv1, 2)} vs 真頂部 {nxt.date()} {fmt(tv1, 2)} → {'真頂部較高 ✓' if tv1 > fv1 else '假頂較高 ✗'}")
        if ok:
            print(f"同輪分辨：{sum(ok)}/{len(ok)} 次真頂部較高")
        if len(tv) >= 3:
            print(f"真頂部讀數逐輪：{' → '.join(fmt(x, 2) for x in tv)}（逐輪遞減時不能用固定紅線，要用週期法擬合）")

    print("\n## 底部：真底部要比中段假底更極端\n")
    print("| 類型 | 日期 | 當日值 |\n|---|---|---|")
    for b in bottoms:
        print(f"| 週期底部 | {b.date()} | {fmt(at(s, b))} |")
    for b in fbots:
        print(f"| 中段假底 | {b.date()} | {fmt(at(s, b))} |")
    print(f"| 本輪低點（樣本外） | {cur_low.date()} | {fmt(at(s, cur_low))} |")

    print("\n## 和現有指標的相關性（Spearman，日資料）\n")
    cols = [c for c in ind.columns if c != "price" and ind[c].notna().sum() > 365]
    mom = transform(price, "ma200").rename("價格 ÷ 200 日均線")
    base = pd.concat([ind[cols], mom], axis=1)[a.start:]
    rs = s.rank()  # Spearman = 排名後的 Pearson（不需要 scipy）
    corr = pd.Series({c: base[c].rank().corr(rs) for c in base.columns}).dropna()
    for k, c in corr.reindex(corr.abs().sort_values(ascending=False).index).head(6).items():
        print(f"- {k}：{c:+.2f}")
    print("\n（|相關| ≥ 0.7 代表和現有指標高度重複，加入只是重複計分）")

    fwd = {n: price.shift(-n) / price - 1 for n in (30, 90, 180)}
    bull = price > price.rolling(200).mean()
    for label, thr, cond in (("由下往上穿越", a.above, (s >= a.above) if a.above is not None else None),
                             ("由上往下穿越", a.below, (s <= a.below) if a.below is not None else None)):
        if cond is None:
            continue
        ev = events(s, cond.fillna(False))
        print(f"\n## 事件：{label} {thr}（相隔 60 天以上才算新事件，共 {len(ev)} 次）\n")
        if not ev:
            continue
        print("| 日期 | 牛市（價格 > 200 日均線） | 30 天 | 90 天 | 180 天 |\n|---|---|---|---|---|")
        for d in ev:
            print(f"| {d.date()} | {'是' if bull.get(d) else '否'} | " + " | ".join(
                "—" if pd.isna(fwd[n].get(d)) else f"{fwd[n][d] * 100:+.0f}%" for n in (30, 90, 180)) + " |")
        rng = slice(v.index[0], None)
        med = {n: fwd[n].loc[ev].median() for n in fwd}
        allm = {n: fwd[n][rng].median() for n in fwd}
        print("\n| | 30 天 | 90 天 | 180 天 |\n|---|---|---|---|")
        print("| 事件後中位 | " + " | ".join(f"{med[n] * 100:+.0f}%" for n in fwd) + " |")
        print("| 同期所有日子中位 | " + " | ".join(f"{allm[n] * 100:+.0f}%" for n in fwd) + " |")
        print("\n（事件少於 8 次時，任何差異都可能只是巧合）")


if __name__ == "__main__":
    main()

"""每日執行：抓資料 → 計算分數 → 輸出 data/ 與 docs/。

任何單一資料源失敗都不會讓流程失敗：沿用 data/raw/ 中前一次的資料並標記 stale。
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from btc_top import sources
from btc_top.page import render_page
from btc_top.scoring import CATEGORIES, UNAVAILABLE, build_indicators, compute_scores, zone_of

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
DOCS = ROOT / "docs"
STALE_DAYS = 3  # 資料日期落後超過幾天視為 stale

INDICATOR_SOURCE = {
    "mvrv_z": "coinmetrics", "nupl": "coinmetrics", "puell": "coinmetrics", "rp_multiple": "coinmetrics",
    "exchange_netflow_30d_pct": "coinmetrics",
    "etf_flow_30d": "etf", "etf_flow_momentum": "etf",
    "stable_growth_90d": "stablecoins", "coinbase_premium_7d": "coinbase_premium",
    "funding_7d_ann": "funding", "oi_to_mcap": "open_interest", "basis_ann": "basis",
    "fear_greed_7d": "fear_greed", "days_since_halving": None,
}


def load_raw(name: str) -> pd.DataFrame:
    p = RAW / f"{name}.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, index_col="date", parse_dates=["date"])


def save_raw(name: str, df: pd.DataFrame):
    RAW.mkdir(parents=True, exist_ok=True)
    df.sort_index().to_csv(RAW / f"{name}.csv", index_label="date", float_format="%.10g")


def fetch_all(today: pd.Timestamp):
    """回傳 (raw dict, 來源狀態 dict)。"""
    def since(name, back=3):
        old = load_raw(name)
        return old.index.max() - pd.Timedelta(days=back) if len(old) else None

    cb_old = load_raw("coinbase_premium")
    plan = {
        "coinmetrics": [sources.coinmetrics],
        "stablecoins": [sources.stablecoins],
        "fear_greed": [sources.fear_greed],
        "funding": [lambda: sources.funding_binance(since("funding")), sources.funding_okx],
        "open_interest": [sources.open_interest_okx, sources.open_interest_binance],
        "basis": [lambda: sources.basis_binance(since("basis")), sources.basis_okx],
        "coinbase_premium": [lambda: sources.coinbase_premium(30 if len(cb_old) else 1500)],
        "etf": [sources.etf_farside],
    }
    raw, status = {}, {}
    for name, fetchers in plan.items():
        old = load_raw(name)
        new, errors = None, []
        for f in fetchers:
            try:
                new = f()
                if len(new):
                    break
            except Exception as e:  # noqa: BLE001
                errors.append(str(e)[:200])
        if new is not None and len(new):
            df = pd.concat([old, new]) if len(old) else new
            df = df[~df.index.duplicated(keep="last")].sort_index()
            save_raw(name, df)
            fetched = True
        else:
            df, fetched = old, False
        raw[name] = df
        last = df.index.max() if len(df) else None
        status[name] = {
            "fetched": fetched,
            "last_date": str(last.date()) if last is not None else None,
            "stale": (not fetched) or last is None or (today - last).days > STALE_DAYS,
            "available": len(df) > 0,
            "errors": errors if not fetched else [],
        }
        flag = "OK" if fetched else ("沿用舊資料" if len(df) else "無資料")
        print(f"[{name}] {flag} 最新 {status[name]['last_date']} {'; '.join(errors)[:160]}")
    return raw, status


def r(x, n=4):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), n)


def main():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    raw, status = fetch_all(today)
    if not len(raw["coinmetrics"]):
        print("Coin Metrics 無任何資料（首次執行且抓取失敗），無法計算。")
        sys.exit(1)

    ind, defs = build_indicators(raw)
    scores, cat_scores, composite, meta, tops, bottoms = compute_scores(ind, defs)

    # ---- 歷史時間序列 ----
    ind.to_csv(ROOT / "data" / "indicators.csv", index_label="date", float_format="%.6g")
    hist = pd.concat({"price": ind["price"], "composite": composite}, axis=1)
    hist = hist.join(cat_scores.add_prefix("cat_")).join(scores.add_prefix("score_"))
    hist = hist.dropna(subset=["composite"]).loc["2011-01-01":]
    hist.to_csv(ROOT / "data" / "scores.csv", index_label="date", float_format="%.4g")

    # ---- latest.json ----
    last_row = hist.index.max()
    filled_ind = ind.ffill()
    categories = {}
    for cat, info in CATEGORIES.items():
        inds = {}
        for key, (c, label, unit) in defs.items():
            if c != cat:
                continue
            src = INDICATOR_SOURCE[key]
            s = ind[key].dropna()
            if not len(s):
                inds[key] = {"label": label, "status": "unavailable",
                             "reason": "; ".join(status.get(src, {}).get("errors", [])) or "免費來源無法取得"}
                continue
            as_of = s.index.max()
            stale = (today - as_of).days > STALE_DAYS or (src and status[src]["stale"])
            inds[key] = {
                "label": label, "unit": unit, "value": r(filled_ind[key].iloc[-1]),
                "score": r(scores[key].ffill().iloc[-1], 1), "as_of": str(as_of.date()),
                "stale": bool(stale), "status": "ok", **{k: (r(v) if isinstance(v, float) else v)
                                                         for k, v in meta[key].items()},
            }
        for key, why in UNAVAILABLE.get(cat, {}).items():
            inds[key] = {"label": why.split("（")[0], "status": "unavailable", "reason": why}
        sc = cat_scores[cat].iloc[-1]
        ok = [v for v in inds.values() if v["status"] == "ok"]
        categories[cat] = {
            "label": info["label"], "weight": info["weight"],
            "score": r(sc, 1),
            "status": "unavailable" if not ok else ("partial" if len(ok) < len(inds) else "ok"),
            "stale": any(v["stale"] for v in ok),
            "indicators": inds,
        }
    avail_w = sum(c["weight"] for c in categories.values() if c["score"] is not None)
    for c in categories.values():
        c["effective_weight"] = r(c["weight"] / avail_w, 3) if c["score"] is not None else 0

    comp = float(composite.loc[last_row])
    hot = sum(1 for c in categories.values() if c["score"] is not None and c["score"] >= 80)
    latest = {
        "date": str(today.date()),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_usd": r(filled_ind["price"].iloc[-1], 2),
        "price_date": str(ind["price"].dropna().index.max().date()),
        "composite_score": r(comp, 1),
        "hot_categories": hot,
        "zone": zone_of(comp, hot),
        "stale": any(c["stale"] for c in categories.values()),
        "categories": categories,
        "cycle_tops": [str(t.date()) for t in tops],
        "cycle_bottoms": [str(b.date()) for b in bottoms],
        "sources": status,
        "zone_rules": "cold < 40 ≤ warm < 65 ≤ hot；top_zone = 總分 ≥ 80 且熱類別（≥80）≥ 3",
        "disclaimer": "僅供參考，不構成投資建議。",
    }
    DOCS.mkdir(exist_ok=True)
    (DOCS / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2))
    render_page(latest, hist, DOCS / "index.html")
    (DOCS / ".nojekyll").touch()
    print(f"完成：{latest['date']} 總分 {latest['composite_score']} zone={latest['zone']} "
          f"熱類別={hot} stale={latest['stale']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

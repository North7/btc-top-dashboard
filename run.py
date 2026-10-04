"""每日執行：抓資料 → 計算分數 → 輸出 data/ 與 docs/。

任何單一資料源失敗都不會讓流程失敗：沿用 data/raw/ 中前一次的資料並標記 stale。

`python run.py --private`：本機私人版。另外抓 BGeometrics 持有者指標（條款禁止公開再散布），
所有資料與輸出都寫在不上傳的 private/，不會改動公開版的 data/ 與 docs/。
"""
from __future__ import annotations

import json
import math
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from btc_top import sources
from btc_top.page import render_page
from btc_top.scoring import (BOTTOM_STRONG, BOTTOM_WINDOW, CATEGORIES, COLD_GROUP_LABEL, COLD_INDICATORS,
                             COLD_WEIGHTS, HALVINGS, SIGNAL_ALERT, SIGNAL_WINDOW, TIMING_FLAT, TIMING_RAMP,
                             bottom_level, bottom_signal, build_indicators, compute_bottom_timing, compute_cold,
                             compute_heat, compute_timing, heat_zone, indicator_defs, signal_level, top_signal,
                             unavailable_defs)

ROOT = Path(__file__).parent
PRIVATE = "--private" in sys.argv
OUT = ROOT / "private" if PRIVATE else ROOT  # 私人版所有輸出都在 private/
DATA = OUT / "data"
RAW = DATA / "raw"
DOCS = OUT / "docs"
STALE_DAYS = 3  # 資料日期落後超過幾天視為 stale

# 私人版：BGeometrics 端點（每天 3 次請求，免費額度每天 15 次）
BGEO = {"bgeo_lth_sopr": ("lth-sopr", "lthSopr"), "bgeo_cdd": ("cdd", "cdd"),
        "bgeo_lth_mvrv": ("lth-mvrv", "lthMvrv")}

INDICATOR_SOURCE = {
    "mvrv_z": "coinmetrics", "nupl": "coinmetrics", "puell": "coinmetrics", "rp_multiple": "coinmetrics",
    "etf_flow_30d": "etf", "etf_flow_momentum": "etf",
    "stable_growth_90d": "stablecoins", "coinbase_premium_7d": "coinbase_premium",
    "funding_7d_ann": "funding", "oi_to_mcap": "open_interest", "basis_ann": "basis",
    "fear_greed_7d": "fear_greed",
    "lth_sopr_7d": "bgeo_lth_sopr", "cdd_30d": "bgeo_cdd", "lth_mvrv": "bgeo_lth_mvrv",
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
        "etf": [sources.etf_tftc, sources.etf_farside],
    }
    if PRIVATE:
        for name, (endpoint, field) in BGEO.items():
            plan[name] = [lambda e=endpoint, f=field: sources.bgeometrics(e, f)]
    marker = RAW / "bgeo_fetched.txt"
    bgeo_done_today = marker.exists() and marker.read_text().strip() == str(today.date())
    raw, status = {}, {}
    for name, fetchers in plan.items():
        old = load_raw(name)
        if name in BGEO and bgeo_done_today and len(old):
            # 今天已抓過，避免重複執行用光每日額度
            raw[name] = old
            last = old.index.max()
            status[name] = {"fetched": True, "last_date": str(last.date()),
                            "stale": (today - last).days > STALE_DAYS, "available": True,
                            "errors": [], "note": "今日已抓取，沿用"}
            print(f"[{name}] 今日已抓取，沿用 最新 {last.date()}")
            continue
        new, errors = None, []
        for f in fetchers:
            try:
                new = f()
                if len(new):
                    break
            except Exception as e:  # noqa: BLE001
                errors.append(str(e)[:200])
        if new is not None and len(new):
            df = pd.concat([old.reindex(columns=new.columns), new]) if len(old) else new
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
    if PRIVATE and all(status[n]["fetched"] for n in BGEO):
        marker.write_text(str(today.date()))
    return raw, status


def r(x, n=4):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), n)


def window(center: pd.Timestamp) -> dict:
    d = lambda n: str((center + pd.Timedelta(days=n)).date())
    return {"center": d(0), "full_from": d(-TIMING_FLAT), "full_to": d(TIMING_FLAT),
            "from": d(-TIMING_FLAT - TIMING_RAMP), "to": d(TIMING_FLAT + TIMING_RAMP)}


def seed_private():
    """私人版首次執行：複製公開版的原始資料快取，之後各自更新。"""
    if PRIVATE and not RAW.exists():
        shutil.copytree(ROOT / "data" / "raw", RAW)


def build_bottom(ind, hist, cold_sc, cold_grp, cold_meta, ribbon_min90, btim, binfo, tim, tops, bottoms, last):
    """底部訊號與週期結構驗證（本輪低點是否就是週期底部）。"""
    price = ind["price"]
    b = btim.loc[last]
    sig = float(hist.loc[last, "bottom_signal"])
    comps = {}
    for key, (grp, label, col, unit, desc) in COLD_INDICATORS.items():
        src = ribbon_min90 if col == "hash_ribbon_min90" else ind[col]
        comps[key] = {"label": label, "group": COLD_GROUP_LABEL[grp], "unit": unit, "description": desc,
                      "value": r(src.ffill().iloc[-1]), "score": r(cold_sc[key].ffill().iloc[-1], 1),
                      **{k: (r(v) if isinstance(v, float) else v) for k, v in cold_meta[key].items()}}
    last_top = pd.Timestamp(b["last_top"])
    last_h = HALVINGS[HALVINGS <= last].max()
    by_top = window(last_top + pd.Timedelta(days=binfo["center_top_days"]))
    by_h = window(last_h + pd.Timedelta(days=binfo["center_halving_days"]))
    decisive = max(by_top["full_to"], by_h["full_to"])  # 兩個滿分窗口都結束的日期

    # 過去底部 vs 本輪低點
    def stats(d, top):
        d = pd.Timestamp(d)
        return {"date": str(d.date()), "price": r(price[d], 2), "days_since_top": (d - top).days,
                "drawdown_pct": r((price[d] / price[top] - 1) * 100, 1), "mvrv": r(ind.loc[d, "rp_multiple"], 3),
                "nupl": r(ind.loc[d, "nupl"], 3), "bottom_signal_max_cycle": None}
    past = []
    for i, bd in enumerate(bottoms):
        st = stats(bd, tops[i])
        seg = hist.loc[tops[i]:tops[i + 1], "bottom_signal"]
        st["bottom_signal_max_cycle"] = r(seg.max(), 1)
        st["days_bottom_zone"] = int((seg >= BOTTOM_WINDOW).sum())
        past.append(st)
    low_date = pd.Timestamp(tim.loc[last, "cycle_low_date"])
    cur = stats(low_date, last_top)
    seg = hist.loc[last_top:, "bottom_signal"]
    cur["bottom_signal_max_cycle"] = r(seg.max(), 1)
    cur["bottom_signal_max_date"] = str(seg.idxmax().date()) if seg.notna().any() else None
    cur["days_bottom_zone"] = int((seg >= BOTTOM_WINDOW).sum())
    mvrv_lt1 = int((ind.loc[last_top:, "rp_multiple"] < 1).sum())
    today = str(last.date())
    if today <= decisive:
        status = "testing"
        verdict = (f"驗證中：若到 {decisive} 為止都沒有跌破本輪低點 ${cur['price']:,.0f}（{cur['date']}），"
                   f"支持「本輪低點即週期底部、ETF 時代熊市變淺」；若之後出現更低的低點且 MVRV 跌破 1，則代表底部尚未出現。")
    else:
        status = "supported" if mvrv_lt1 == 0 else "classic"
        verdict = (f"底部時間窗口已於 {decisive} 結束，本輪低點 {cur['date']}（${cur['price']:,.0f}）未被跌破，"
                   + ("且估值未出現投降（MVRV 從未跌破 1），支持「熊市變淺」。" if mvrv_lt1 == 0
                      else "期間曾出現估值投降（MVRV 跌破 1），屬傳統型底部。"))
    return {
        "signal": r(sig, 1), "level": bottom_level(sig),
        "cold_score": r(float(hist.loc[last, "cold"]), 1),
        "groups": {COLD_GROUP_LABEL[g]: {"score": r(cold_grp[g].ffill().iloc[-1], 1), "weight": w}
                   for g, w in COLD_WEIGHTS.items()},
        "indicators": comps,
        "timing": {"score": r(b["timing"], 1), "score_top": r(b["timing_top"], 1), "score_halving": r(b["timing_halving"], 1),
                   "days_since_top": int(b["days_since_top"]), "days_since_halving": int(b["days_since_halving"]),
                   "last_top": str(last_top.date()), "last_halving": str(last_h.date()),
                   "window_by_top": by_top, "window_by_halving": by_h, **binfo},
        "cycle_test": {"status": status, "decisive_date": decisive, "verdict": verdict,
                       "current_low": cur, "past_bottoms": past, "days_mvrv_below_1_this_cycle": mvrv_lt1},
        "note": "參數只依 2015、2018、2022 底部與中段假底部決定，本輪為樣本外檢驗。",
    }


def main():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    seed_private()
    raw, status = fetch_all(today)
    if not len(raw["coinmetrics"]):
        print("Coin Metrics 無任何資料（首次執行且抓取失敗），無法計算。")
        sys.exit(1)

    ind = build_indicators(raw)
    defs = indicator_defs(PRIVATE)
    scores, pcts, cat_scores, heat, meta, tops, bottoms = compute_heat(ind, PRIVATE)
    tim, tinfo = compute_timing(ind.index, ind["price"], tops)
    signal = top_signal(heat, tim["timing"])
    cold_sc, cold_grp, cold, cold_meta, ribbon_min90 = compute_cold(ind, tops, bottoms)
    btim, binfo = compute_bottom_timing(ind.index, ind["price"], tops, bottoms)
    bsig = bottom_signal(cold, btim["timing"])

    # ---- 歷史時間序列 ----
    ind.to_csv(DATA / "indicators.csv", index_label="date", float_format="%.6g")
    hist = pd.concat({"price": ind["price"], "top_signal": signal, "heat": heat,
                      "heat_7d": heat.rolling(7, min_periods=1).mean(), "timing": tim["timing"],
                      "timing_halving": tim["timing_halving"], "timing_low": tim["timing_low"],
                      "days_since_halving": tim["days_since_halving"], "days_since_low": tim["days_since_low"],
                      "bottom_signal": bsig, "cold": cold, "cold_7d": cold.rolling(7, min_periods=1).mean(),
                      "bottom_timing": btim["timing"], "days_since_top": btim["days_since_top"]},
                     axis=1)
    hist = hist.join(cold_grp.add_prefix("coldgrp_")).join(cold_sc.add_prefix("coldscore_"))
    hist["hash_ribbon_min90"] = ribbon_min90
    hist = hist.join(cat_scores.add_prefix("cat_")).join(scores.add_prefix("score_"))
    hist = hist.dropna(subset=["heat"]).loc["2011-01-01":]
    hist.to_csv(DATA / "scores.csv", index_label="date", float_format="%.4g")

    # ---- latest.json ----
    last = hist.index.max()
    filled_ind = ind.ffill()
    categories = {}
    for cat, info in CATEGORIES.items():
        inds = {}
        for key, (c, label, unit, role, desc) in defs.items():
            if c != cat:
                continue
            src = INDICATOR_SOURCE[key]
            s = ind[key].dropna()
            if not len(s):
                inds[key] = {"label": label, "role": role, "description": desc, "status": "unavailable",
                             "reason": "; ".join(status.get(src, {}).get("errors", [])) or "免費來源無法取得"}
                continue
            as_of = s.index.max()
            stale = (today - as_of).days > STALE_DAYS or (src and status[src]["stale"])
            inds[key] = {
                "label": label, "unit": unit, "role": role, "description": desc,
                "value": r(filled_ind[key].iloc[-1]),
                "score": r(scores[key].ffill().iloc[-1], 1) if role == "score" else None,
                "percentile": r(pcts[key].ffill().iloc[-1], 1),
                "as_of": str(as_of.date()), "stale": bool(stale), "status": "ok",
                **{k: (r(v) if isinstance(v, float) else v) for k, v in meta[key].items()},
            }
        for key, why in unavailable_defs(PRIVATE).get(cat, {}).items():
            inds[key] = {"label": why.split("（")[0], "role": "score", "status": "unavailable", "reason": why}
        sc = cat_scores[cat].iloc[-1]
        scored = [v for v in inds.values() if v["status"] == "ok" and v["role"] == "score"]
        n_score = sum(1 for v in inds.values() if v["role"] == "score")
        categories[cat] = {
            "label": info["label"], "weight": info["weight"], "score": r(sc, 1),
            "status": "unavailable" if not scored else ("partial" if len(scored) < n_score else "ok"),
            "stale": any(v["stale"] for v in scored),
            "indicators": inds,
        }
    avail_w = sum(c["weight"] for c in categories.values() if c["score"] is not None)
    for c in categories.values():
        c["effective_weight"] = r(c["weight"] / avail_w, 3) if c["score"] is not None else 0

    h = float(heat.loc[last])
    sig = float(signal.loc[last])
    hot = sum(1 for c in categories.values() if c["score"] is not None and c["score"] >= 80)
    t = tim.loc[last]
    # 預估頂部窗口：依減半（若已超過本次窗口，改看下一次減半）與依本輪低點（低點若再創新低會移動）
    last_h = HALVINGS[HALVINGS <= last].max()
    if t["days_since_halving"] > tinfo["center_halving_days"] + TIMING_FLAT + TIMING_RAMP:
        nxt = HALVINGS[HALVINGS > last]
        last_h = nxt.min() if len(nxt) else last_h
    low_date = pd.Timestamp(t["cycle_low_date"])
    timing = {
        "score": r(t["timing"], 1),
        "score_halving": r(t["timing_halving"], 1), "score_low": r(t["timing_low"], 1),
        "days_since_halving": int(t["days_since_halving"]), "days_since_low": int(t["days_since_low"]),
        "last_halving": str(HALVINGS[HALVINGS <= last].max().date()),
        "next_halving": str(HALVINGS[HALVINGS > last].min().date()) if (HALVINGS > last).any() else None,
        "next_halving_estimated": True,
        "cycle_low_date": str(low_date.date()),
        "cycle_low_price": r(ind["price"].get(low_date), 2),
        "window_halving": str(last_h.date()),
        "expected_window_by_halving": window(last_h + pd.Timedelta(days=tinfo["center_halving_days"])),
        "expected_window_by_low": window(low_date + pd.Timedelta(days=tinfo["center_low_days"])),
        **tinfo,
    }
    bottom = build_bottom(ind, hist, cold_sc, cold_grp, cold_meta, ribbon_min90, btim, binfo, tim, tops, bottoms, last)
    latest = {
        "date": str(today.date()),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_usd": r(filled_ind["price"].iloc[-1], 2),
        "price_date": str(ind["price"].dropna().index.max().date()),
        "top_signal": r(sig, 1),
        "signal_level": signal_level(sig),
        "heat_score": r(h, 1),
        "composite_score": r(h, 1),
        "timing_score": r(t["timing"], 1),
        "hot_categories": hot,
        "zone": "top_zone" if sig >= SIGNAL_WINDOW else heat_zone(h),
        "stale": any(c["stale"] for c in categories.values()),
        "timing": timing,
        "bottom_signal": bottom["signal"],
        "bottom_level": bottom["level"],
        "cold_score": bottom["cold_score"],
        "bottom_timing_score": bottom["timing"]["score"],
        "bottom": bottom,
        "categories": categories,
        "cycle_tops": [str(x.date()) for x in tops],
        "cycle_bottoms": [str(b.date()) for b in bottoms],
        "sources": status,
        "rules": {
            "top_signal": "頂部訊號 = 熱度（7 日均）× 時機 ÷ 100",
            "signal_level": f"none < {SIGNAL_WINDOW} ≤ window（頂部窗口）< {SIGNAL_ALERT} ≤ alert（高度警戒）",
            "zone": f"頂部訊號 ≥ {SIGNAL_WINDOW} 時為 top_zone；否則依熱度：cold < 40 ≤ warm < 65 ≤ hot",
            "composite_score": "與 heat_score 相同（保留舊欄位名稱）",
            "hot_categories": "類別分數 ≥ 80 的類別數",
            "bottom_signal": "底部訊號 = 冷度（7 日均）× 底部時機 ÷ 100",
            "bottom_level": f"none < {BOTTOM_WINDOW} ≤ zone（底部區）< {BOTTOM_STRONG} ≤ strong（強烈底部）",
        },
        "disclaimer": "僅供參考，不構成投資建議。",
        "private": PRIVATE,
    }
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2))
    render_page(latest, hist, ind, DOCS / "index.html", defs, PRIVATE, lang="zh")
    render_page(latest, hist, ind, DOCS / "en" / "index.html", defs, PRIVATE, lang="en")
    (DOCS / ".nojekyll").touch()
    print(f"底部訊號 {latest['bottom_signal']}（{latest['bottom_level']}） 冷度 {latest['cold_score']} "
          f"底部時機 {latest['bottom_timing_score']}　{bottom['cycle_test']['verdict']}")
    print(f"完成：{latest['date']} 頂部訊號 {latest['top_signal']}（{latest['signal_level']}） "
          f"熱度 {latest['heat_score']} 時機 {latest['timing_score']} zone={latest['zone']} "
          f"熱類別={hot} stale={latest['stale']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

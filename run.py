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

import numpy as np
import pandas as pd

from btc_top import sources
from btc_top.midterm import compute_midterm
from btc_top.strategy import compute_strategy, projected_arm
from btc_top.scenarios import compute_scenarios, track_scenarios
from btc_top.events import detect as detect_events
from btc_top.checks import run_checks
from btc_top.page import render_page
from btc_top.scoring import (BOTTOM_STRONG, BOTTOM_WINDOW, CATEGORIES, COLD_GROUP_LABEL, COLD_INDICATORS,
                             COLD_WEIGHTS, HALVINGS, SIGNAL_ALERT, SIGNAL_WINDOW, TIMING_FLAT, TIMING_RAMP,
                             bottom_level, bottom_signal, build_indicators, compute_bottom_timing, compute_cold,
                             compute_heat, compute_timing, heat_zone, indicator_defs, signal_level, top_signal,
                             unavailable_defs)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
RAW = DATA / "raw"
DOCS = ROOT / "docs"
STALE_DAYS = 3  # 資料日期落後超過幾天視為 stale
# 只在美股交易日有資料、且當天資金流隔天才公布的來源：改用工作日計算落後天數（避免週末後每週二誤報）
TRADING_DAY_SOURCES = {"etf"}
TRADING_DAY_LAG = 2  # 落後超過幾個工作日視為 stale（容許一天美股假日）


def is_lagging(name: str, last, today: pd.Timestamp) -> bool:
    """資料最新日期是否落後太多。"""
    if last is None:
        return True
    if name in TRADING_DAY_SOURCES:
        return int(np.busday_count((last + pd.Timedelta(days=1)).date(), today.date())) > TRADING_DAY_LAG
    return (today - last).days > STALE_DAYS

INDICATOR_SOURCE = {
    "mvrv_z": "coinmetrics", "nupl": "coinmetrics", "puell": "coinmetrics", "rp_multiple": "coinmetrics",
    "etf_flow_30d": "etf", "etf_flow_momentum": "etf",
    "stable_growth_90d": "stablecoins", "coinbase_premium_7d": "coinbase_premium",
    "funding_7d_ann": "funding", "oi_to_mcap": "open_interest", "basis_ann": "basis",
    "fear_greed_7d": "fear_greed",
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
        "open_interest": [sources.open_interest_okx_swaps, sources.open_interest_okx, sources.open_interest_binance],
        "basis": [lambda: sources.basis_binance(since("basis")), sources.basis_okx],
        "coinbase_premium": [lambda: sources.coinbase_premium(30 if len(cb_old) else 1500)],
        "etf": [sources.etf_tftc, sources.etf_farside],
        "ohlc": [lambda: sources.ohlc_bitstamp(since("ohlc", 5)),
                 lambda: sources.ohlc_coinbase(30 if len(load_raw("ohlc")) else 2000)],
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
            "stale": (not fetched) or is_lagging(name, last, today),
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


def window(center: pd.Timestamp) -> dict:
    d = lambda n: str((center + pd.Timedelta(days=n)).date())
    return {"center": d(0), "full_from": d(-TIMING_FLAT), "full_to": d(TIMING_FLAT),
            "from": d(-TIMING_FLAT - TIMING_RAMP), "to": d(TIMING_FLAT + TIMING_RAMP)}


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
    # 驗證基準固定：第一次建立假說時把「候選低點」與判定日寫入 data/cycle_test.json，之後不再移動。
    # （2026-10 外部驗證指出：舊版每天改用「截至目前的最低點」，跌破後基準也跟著下移，判定永遠成立。）
    hyp_path = DATA / "cycle_test.json"
    hyp = json.loads(hyp_path.read_text()) if hyp_path.exists() else None
    if not hyp or hyp.get("cycle_top") != str(last_top.date()):
        hyp = {"cycle_top": str(last_top.date()), "hypothesis_created_at": today,
               "candidate_low_date": cur["date"], "candidate_low_price": cur["price"], "deadline": decisive}
        hyp_path.write_text(json.dumps(hyp, ensure_ascii=False, indent=2))
    cand_d, cand_p, deadline = pd.Timestamp(hyp["candidate_low_date"]), hyp["candidate_low_price"], hyp["deadline"]
    after = price.loc[cand_d + pd.Timedelta(days=1):].dropna()
    broken = after[after < cand_p]
    broken_date = str(broken.index[0].date()) if len(broken) else None
    if broken_date:
        status = "failed"
        verdict = (f"假說不成立：候選低點 ${cand_p:,.0f}（{cand_d.date()}）已於 {broken_date} 被跌破，"
                   f"本輪低點不是週期底部。新的低點為 ${cur['price']:,.0f}（{cur['date']}），如要再驗證需另建新假說。")
    elif today <= deadline:
        status = "testing"
        verdict = (f"驗證中：若到 {deadline} 為止都沒有跌破候選低點 ${cand_p:,.0f}（{cand_d.date()}），"
                   f"支持「本輪低點即週期底部、ETF 時代熊市變淺」；一旦跌破即判定假說不成立。")
    else:
        status = "supported" if mvrv_lt1 == 0 else "classic"
        verdict = (f"底部時間窗口已於 {deadline} 結束，候選低點 {cand_d.date()}（${cand_p:,.0f}）未被跌破，"
                   + ("且估值未出現投降（MVRV 從未跌破 1），支持「熊市變淺」。之後若跌破，判定會改為不成立。" if mvrv_lt1 == 0
                      else "期間曾出現估值投降（MVRV 跌破 1），屬傳統型底部。"))
    return {
        "signal": r(sig, 1), "level": bottom_level(sig),
        "cold_score": r(float(hist.loc[last, "cold"]), 1),
        "groups": {COLD_GROUP_LABEL[g]: {"score": r(cold_grp[g].ffill().iloc[-1], 1), "weight": w}
                   for g, w in COLD_WEIGHTS.items()},
        "indicators": comps,
        "references": {"ref_delta": {
            "label": "Delta Price 倍數（價格 ÷ Delta Price）", "unit": "x", "scored": False,
            "value": r(ind["delta_ratio"].ffill().iloc[-1]), "delta_price": r(ind["delta_price"].ffill().iloc[-1], 0),
            "past_bottoms": {str(d.date()): r(ind.loc[d, "delta_ratio"], 3) for d in bottoms},
            "description": "Delta Price =（實現市值 − 平均市值）÷ 流通量。過去三次週期底部價格都落在 Delta Price 的 1.0–1.25 倍，"
                           "假底部都在 1.4 倍以上。2026-10 驗證後只作參考、不計入冷度（與 MVRV 高度相關，加入後分辨力略降）。"}},
        "timing": {"score": r(b["timing"], 1), "score_top": r(b["timing_top"], 1), "score_halving": r(b["timing_halving"], 1),
                   "days_since_top": int(b["days_since_top"]), "days_since_halving": int(b["days_since_halving"]),
                   "last_top": str(last_top.date()), "last_halving": str(last_h.date()),
                   "window_by_top": by_top, "window_by_halving": by_h, **binfo},
        "cycle_test": {"status": status, "decisive_date": deadline, "verdict": verdict, "hypothesis": hyp, "broken_date": broken_date,
                       "current_low": cur, "past_bottoms": past, "days_mvrv_below_1_this_cycle": mvrv_lt1},
        "note": "參數只依 2015、2018、2022 底部與中段假底部決定，本輪為樣本外檢驗。",
    }


def main():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    raw, status = fetch_all(today)
    if not len(raw["coinmetrics"]):
        print("Coin Metrics 無任何資料（首次執行且抓取失敗），無法計算。")
        sys.exit(1)

    ind = build_indicators(raw)
    defs = indicator_defs()
    scores, pcts, cat_scores, heat, meta, tops, bottoms = compute_heat(ind)
    tim, tinfo = compute_timing(ind.index, ind["price"], tops)
    signal = top_signal(heat, tim["timing"])
    cold_sc, cold_grp, cold, cold_meta, ribbon_min90 = compute_cold(ind, tops, bottoms)
    btim, binfo = compute_bottom_timing(ind.index, ind["price"], tops, bottoms)
    bsig = bottom_signal(cold, btim["timing"])
    mid, mid_info = compute_midterm(ind, raw.get("ohlc", pd.DataFrame()), today)
    live = pd.DataFrame({"sig": signal, "tim": tim["timing"], "bsig": bsig})
    strat, strat_info = compute_strategy(ind, live, mid["st_dir"] if "st_dir" in mid else pd.Series(dtype=float), today, DATA / "strategy_ledger.csv")

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
    hist = hist.join(mid.drop(columns=["dip_hits", "hot_hits"]).astype(float).add_prefix("mid_"))
    hist = hist.join(strat)
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
        for key, why in unavailable_defs().get(cat, {}).items():
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
        "midterm": mid_info,
        "strategy": strat_info,
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
    }
    try:  # 未來情境只是參考，計算失敗不可讓整個流程失敗
        latest["scenarios"] = compute_scenarios(ind, timing, today)
    except Exception as e:  # noqa: BLE001
        print("未來情境計算失敗：", e)
    strat_info["projected_arm"] = projected_arm(timing, today) if strat_info["state"] == "holding" and not strat_info["armed"] else None
    # 定案後追蹤：情境路徑在定案日凍結一份，之後每天比較實際價格
    if latest.get("scenarios"):
        snap = DATA / "scenario_snapshot.json"
        if not snap.exists():
            snap.write_text(json.dumps({k: latest["scenarios"][k] for k in ("as_of", "top_date", "tops", "dates", "paths")}, ensure_ascii=False))
        latest["scenarios"]["tracking"] = track_scenarios(json.loads(snap.read_text()), ind["price"])

    DOCS.mkdir(parents=True, exist_ok=True)
    old_path = DOCS / "latest.json"
    try:
        old = json.loads(old_path.read_text()) if old_path.exists() else None
    except Exception:  # noqa: BLE001
        old = None
    # 與上一次的輸出比較（GitHub 上是前一天 commit 的版本；同一天重跑時事件已在第一次通知過，不會重複）
    latest["events"] = detect_events(old, latest)
    (DOCS / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2))
    render_page(latest, hist, ind, DOCS / "index.html", defs, lang="zh")
    render_page(latest, hist, ind, DOCS / "en" / "index.html", defs, lang="en")
    (DOCS / ".nojekyll").touch()
    try:  # 分享預覽圖：失敗不影響主流程
        from btc_top.ogimage import make_og
        make_og(latest, DOCS / "og.png")
    except Exception as e:  # noqa: BLE001
        print("分享預覽圖產生失敗：", e)
    # 健康檢查：只把「新出現」的警告標出來，避免同一問題每天重複通知
    _, warns = run_checks(DOCS)
    key = lambda w: w.split("（")[0]
    old_keys = {key(w) for w in ((old or {}).get("health") or {}).get("warnings", [])}
    latest["health"] = {"warnings": warns, "new_warnings": [w for w in warns if key(w) not in old_keys]}
    (DOCS / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2))
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

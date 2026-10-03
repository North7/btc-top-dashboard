"""指標計算、正規化與頂部訊號。

三個主要輸出（見 CLAUDE.md「計分結構」）：
- 熱度（heat_score）：四類市場指標加權平均，回答「市場有多熱」。
- 時機（timing_score）：距減半天數 + 距週期低點天數，回答「是否進入歷史上的頂部時間窗口」。
- 頂部訊號（top_signal）= 熱度（7 日均）× 時機 ÷ 100。只有「夠熱」且「時間對」才會高。

熱度的正規化：
- 週期法：取各次週期頂部當日數值，以對數線性擬合遞減趨勢，推估本輪預期頂部值；
  底部同理推估下界。分數 = 當前值在「下界 → 預期頂部」的位置 × 100，下限 0，可超過 100。
- 百分位法：歷史不足 3 個週期（或擬合區間無效）的指標，用自身過去 4 年的滾動百分位，
  再做中心化：百分位 ≤ 35 為 0 分，100 為 100 分（避免平常狀態被算成「半熱」）。
- 加總時單一指標分數上限 120，避免單一指標主導類別分數。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TOP_MONTHS = ["2013-12", "2017-12", "2021-11", "2025-10"]
PRE_TOP_MONTH = "2011-06"  # 2011 泡沫頂：只用來界定 2013 週期的低點
HALVINGS = pd.to_datetime(["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20", "2028-04-15"])
# 2028 減半日期為依區塊速度的估計值，實際日期出來後請更新

CATEGORIES = {
    "onchain_valuation": {"label": "鏈上估值", "weight": 0.35},
    "holder_behavior": {"label": "持有者行為", "weight": 0.20},
    "capital_flows": {"label": "資金流與機構", "weight": 0.20},
    "leverage": {"label": "槓桿與衍生品", "weight": 0.15},
    "sentiment_cycle": {"label": "情緒", "weight": 0.10},
}

# key: (類別, 名稱, 單位, 角色, 說明)。角色 score = 計入熱度；ref = 僅顯示供參考
INDICATORS = {
    "mvrv_z": ("onchain_valuation", "MVRV Z-score", "", "score",
               "市值與實現市值（所有幣最後移動時價格的總和）的差距，以標準差衡量。越高代表整體未實現獲利越大。"),
    "nupl": ("onchain_valuation", "NUPL", "", "score",
             "淨未實現損益占市值比例。接近 0.75 以上歷來是極度貪婪區。"),
    "puell": ("onchain_valuation", "Puell Multiple", "", "score",
              "礦工每日收入 ÷ 365 日均。礦工收入異常高時，往往是價格過熱。"),
    "rp_multiple": ("onchain_valuation", "實現價格倍數", "x", "score",
                    "價格 ÷ 實現價格（市場平均持幣成本）。數學上等於 MVRV。"),
    "exchange_netflow_30d_pct": ("holder_behavior", "交易所 30 日淨流入", "% 流通量", "ref",
                                 "流入交易所減流出的 30 日合計。在頂部出貨與底部投降時都可能升高，方向不明確，因此僅供參考。"),
    "exchange_balance_90d_pct": ("holder_behavior", "交易所餘額 90 日變化", "% 流通量", "ref",
                                 "交易所持有 BTC 的 90 日變化。上升代表更多幣準備賣出。受交易所涵蓋範圍變動影響，僅供參考。"),
    "etf_flow_30d": ("capital_flows", "ETF 30 日累計淨流入", "百萬美元", "score",
                     "美國現貨 ETF 過去 30 日的淨申購合計。"),
    "etf_flow_momentum": ("capital_flows", "ETF 流入動能", "百萬美元", "score",
                          "最近 30 日淨流入減前 30 日，正值代表流入在加速。"),
    "stable_growth_90d": ("capital_flows", "穩定幣 90 日增速", "%", "score",
                          "穩定幣總供給 90 日成長率，代表場內可用的新資金。"),
    "coinbase_premium_7d": ("capital_flows", "Coinbase 溢價（7 日均）", "%", "score",
                            "Coinbase 美元價格相對 OKX USDT 價格的溢價，反映美國買盤強度。"),
    "funding_7d_ann": ("leverage", "資金費率 7 日均（年化）", "%", "score",
                       "永續合約多方付給空方的費率。越高代表槓桿做多越擁擠。"),
    "oi_to_mcap": ("leverage", "未平倉量 / 市值", "%", "score",
                   "全市場 BTC 合約未平倉量占市值比例，代表槓桿規模。"),
    "basis_ann": ("leverage", "期現基差（年化）", "%", "score",
                  "季度期貨相對現貨的年化溢價。越高代表期貨買方越願意付溢價。"),
    "fear_greed_7d": ("sentiment_cycle", "恐懼貪婪指數（7 日均）", "", "score",
                      "alternative.me 綜合波動、成交量、社群與搜尋的情緒指數（0–100）。"),
}

# 免費源無法取得、標記為 unavailable 的指標（v2 接付費源）
UNAVAILABLE = {
    "holder_behavior": {
        "lth_supply_change": "長期持有者供給變化（需 Glassnode / CryptoQuant）",
        "lth_sopr": "LTH-SOPR（需 Glassnode / CryptoQuant）",
        "cdd_dormancy": "CDD / Dormancy（需 Glassnode / CryptoQuant）",
    },
    "sentiment_cycle": {
        "google_trends": "Google Trends「bitcoin」（無官方免費 API，第一版跳過）",
    },
}

# 僅本機私人版（`run.py --private`）使用的 BGeometrics 指標；條款禁止公開再散布，不可出現在公開版
PRIVATE_INDICATORS = {
    "lth_sopr_7d": ("holder_behavior", "LTH-SOPR（7 日均）", "", "score",
                    "長期持有者賣出的幣，賣價 ÷ 買入成本。明顯高於 1 代表長期持有者正在大量獲利了結。"),
    "cdd_30d": ("holder_behavior", "CDD（30 日均）", "百萬幣天", "score",
                "Coin Days Destroyed：被移動的幣數 × 持有天數。老幣大量移動常見於頂部出貨。"),
    "lth_mvrv": ("holder_behavior", "LTH-MVRV", "", "score",
                 "長期持有者的平均帳面獲利倍數。越高代表長期持有者越有動機賣出。"),
}
PRIVATE_COVERS = {"holder_behavior": ["lth_sopr", "cdd_dormancy"]}  # 私人版已有資料、不再列為 unavailable


def indicator_defs(private: bool = False) -> dict:
    return INDICATORS | PRIVATE_INDICATORS if private else INDICATORS


def unavailable_defs(private: bool = False) -> dict:
    if not private:
        return UNAVAILABLE
    return {cat: {k: v for k, v in items.items() if k not in PRIVATE_COVERS.get(cat, [])}
            for cat, items in UNAVAILABLE.items()}


PCT_WINDOW = 1460  # 百分位滾動視窗（天）
PCT_MIN = 90       # 至少需要的資料點（太少時百分位無意義，分數留空）
PCT_PIVOT = 35     # 百分位中心化：此百分位以下為 0 分
SCORE_CAP = 120    # 加總時單一指標分數上限

# 時機：以最近 3 次頂部的平均天數為中心；中心 ±FLAT 天內滿分，再往外 RAMP 天線性降到 0
TIMING_FLAT = 60
TIMING_RAMP = 240
TIMING_RECENT = 3
SIGNAL_WINDOW = 50  # 頂部訊號 ≥ 此值：頂部窗口
SIGNAL_ALERT = 70   # 頂部訊號 ≥ 此值：高度警戒


def find_cycles(price: pd.Series):
    """回傳 (頂部日期列表, 底部日期列表)。頂部 = 指定月份最高收盤日；底部 = 兩頂之間最低收盤日。"""
    tops = [price[m].idxmax() for m in TOP_MONTHS]
    bottoms = [price[tops[i]:tops[i + 1]].idxmin() for i in range(len(tops) - 1)]
    return tops, bottoms


def build_indicators(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """由原始資料計算各指標的每日數值。"""
    cm = raw["coinmetrics"]
    idx = pd.date_range(cm.index.min(), max(cm.index.max(), *(d.index.max() for d in raw.values() if len(d))))
    cm = cm.reindex(idx)
    mc, mvrv = cm["CapMrktCurUSD"], cm["CapMVRVCur"]
    rc = mc / mvrv
    ind = pd.DataFrame(index=idx)
    ind["price"] = cm["PriceUSD"]
    ind["realized_price"] = rc / cm["SplyCur"]

    # 一、鏈上估值
    ind["mvrv_z"] = (mc - rc) / mc.expanding(min_periods=365).std()
    ind["nupl"] = 1 - 1 / mvrv
    ind["puell"] = cm["IssTotUSD"] / cm["IssTotUSD"].rolling(365, min_periods=300).mean()
    ind["rp_multiple"] = cm["PriceUSD"] / ind["realized_price"]

    # 二、持有者行為（僅參考）
    net = (cm["FlowInExNtv"] - cm["FlowOutExNtv"]).rolling(30, min_periods=25).sum()
    ind["exchange_netflow_30d_pct"] = net / cm["SplyCur"] * 100
    ind["exchange_balance_90d_pct"] = (cm["SplyExNtv"] - cm["SplyExNtv"].shift(90)) / cm["SplyCur"] * 100

    # 三、資金流
    if len(raw.get("etf", [])):
        etf = raw["etf"]["etf_flow_musd"].reindex(idx).fillna(0)
        etf[idx < raw["etf"].index.min()] = np.nan
        s30 = etf.rolling(30).sum()
        ind["etf_flow_30d"] = s30
        ind["etf_flow_momentum"] = s30 - s30.shift(30)
    if len(raw.get("stablecoins", [])):
        st = raw["stablecoins"]["stable_supply_usd"].reindex(idx).interpolate(limit=5, limit_area="inside")
        ind["stable_growth_90d"] = st.pct_change(90, fill_method=None) * 100
    if len(raw.get("coinbase_premium", [])):
        ind["coinbase_premium_7d"] = (raw["coinbase_premium"]["coinbase_premium"].reindex(idx)
                                      .rolling(7, min_periods=5).mean() * 100)

    # 四、槓桿
    if len(raw.get("funding", [])):
        ind["funding_7d_ann"] = (raw["funding"]["funding"].reindex(idx)
                                 .rolling(7, min_periods=5).mean() * 3 * 365 * 100)
    if len(raw.get("open_interest", [])):
        ind["oi_to_mcap"] = raw["open_interest"]["oi_usd"].reindex(idx) / mc.ffill(limit=3) * 100
    if len(raw.get("basis", [])):
        ind["basis_ann"] = raw["basis"]["basis_ann"].reindex(idx).rolling(7, min_periods=1).mean() * 100

    # 五、情緒
    if len(raw.get("fear_greed", [])):
        ind["fear_greed_7d"] = raw["fear_greed"]["fear_greed"].reindex(idx).rolling(7, min_periods=5).mean()

    # 私人版：BGeometrics 持有者指標
    if len(raw.get("bgeo_lth_sopr", [])):
        ind["lth_sopr_7d"] = raw["bgeo_lth_sopr"]["lthSopr"].reindex(idx).rolling(7, min_periods=5).mean()
    if len(raw.get("bgeo_cdd", [])):
        ind["cdd_30d"] = raw["bgeo_cdd"]["cdd"].reindex(idx).rolling(30, min_periods=25).mean() / 1e6
    if len(raw.get("bgeo_lth_mvrv", [])):
        ind["lth_mvrv"] = raw["bgeo_lth_mvrv"]["lthMvrv"].reindex(idx)

    for k in INDICATORS:
        if k not in ind:
            ind[k] = np.nan
    return ind


def _fit(xs, ys, x_target):
    """對數線性擬合（全正值時），否則線性擬合；只有一點時回傳該值。"""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    if len(ys) == 1:
        return float(ys[0])
    if (ys > 0).all():
        b, a = np.polyfit(xs, np.log(ys), 1)
        return float(np.exp(a + b * x_target))
    b, a = np.polyfit(xs, ys, 1)
    return float(a + b * x_target)


def _cycle_index(index: pd.DatetimeIndex, tops) -> pd.Series:
    """每天所屬的週期序號 k = 該日之前已發生的頂部數。"""
    return pd.Series(np.searchsorted(np.array(tops, dtype="datetime64[ns]"), index.values, side="left"),
                     index=index)


def cycle_params(s: pd.Series, tops, bottoms):
    """回傳 {週期序號 k: (下界, 預期頂部)}；資料不足 3 個頂部或區間無效時回傳 None。"""
    top_pts = [(i, s.get(t)) for i, t in enumerate(tops) if pd.notna(s.get(t))]
    bot_pts = [(i + 0.5, s.get(b)) for i, b in enumerate(bottoms) if pd.notna(s.get(b))]
    if len(top_pts) < 3 or not bot_pts:
        return None
    params = {}
    for k in range(len(tops) + 1):
        top = _fit(*zip(*top_pts), k)
        bot = _fit(*zip(*bot_pts), k - 0.5)
        if top <= bot:
            return None
        params[k] = (bot, top)
    return {"params": params, "top_values": dict(top_pts), "bottom_values": dict(bot_pts)}


def score_cycle(s: pd.Series, tops, cp) -> pd.Series:
    k = _cycle_index(s.index, tops)
    bot = k.map(lambda i: cp["params"][i][0])
    top = k.map(lambda i: cp["params"][i][1])
    return ((s - bot) / (top - bot) * 100).clip(lower=0)


def rolling_percentile(s: pd.Series) -> pd.Series:
    v = s.dropna()
    if len(v) < PCT_MIN:
        return pd.Series(np.nan, index=s.index)
    return (v.rolling(PCT_WINDOW, min_periods=PCT_MIN).rank(pct=True) * 100).reindex(s.index)


def score_percentile(pct: pd.Series) -> pd.Series:
    return ((pct - PCT_PIVOT) / (100 - PCT_PIVOT) * 100).clip(lower=0)


def compute_heat(ind: pd.DataFrame, private: bool = False):
    """回傳 (指標分數, 指標百分位, 類別分數, 熱度, meta, tops, bottoms)。"""
    defs = indicator_defs(private)
    for k in defs:
        if k not in ind:
            ind[k] = np.nan
    tops, bottoms = find_cycles(ind["price"].dropna())
    scores = pd.DataFrame(index=ind.index)
    pcts = pd.DataFrame(index=ind.index)
    meta = {}
    for key in defs:
        s = ind[key]
        pcts[key] = rolling_percentile(s)
        if s.notna().sum() == 0:
            meta[key] = {"method": None}
            scores[key] = np.nan
            continue
        cp = cycle_params(s, tops, bottoms)
        if cp:
            scores[key] = score_cycle(s, tops, cp)
            bot, top = cp["params"][len(tops)]
            meta[key] = {"method": "cycle", "bottom_bound": bot, "expected_top": top,
                         "past_tops": {str(tops[i].date()): v for i, v in cp["top_values"].items()}}
        else:
            scores[key] = score_percentile(pcts[key])
            meta[key] = {"method": "percentile", "history_days": int(s.notna().sum())}

    # 類別分數：同類「計分」指標先平均（單一指標上限 SCORE_CAP）。
    # 指標向前沿用最後一筆數值（對齊各來源更新時間；抓取失敗時沿用前值），是否過期由 stale 標記表示
    filled = scores.ffill().clip(upper=SCORE_CAP)
    cat_scores = pd.DataFrame(index=ind.index)
    for cat in CATEGORIES:
        cols = [k for k, d in defs.items() if d[0] == cat and d[3] == "score"]
        cat_scores[cat] = filled[cols].mean(axis=1, skipna=True) if cols else np.nan
    w = pd.Series({c: v["weight"] for c, v in CATEGORIES.items()})
    avail = cat_scores.notna()
    weighted = (cat_scores.fillna(0) * w).sum(axis=1) / (avail * w).sum(axis=1)
    heat = weighted.clip(0, 100).where(avail.any(axis=1))
    return scores, pcts, cat_scores, heat, meta, tops, bottoms


def _trap(x: pd.Series, center: float) -> pd.Series:
    d = (x - center).abs()
    return (1 - ((d - TIMING_FLAT) / TIMING_RAMP).clip(0, 1)).where(x.notna())


def compute_timing(index: pd.DatetimeIndex, price: pd.Series, tops):
    """時機分數（0–100）與相關資訊。

    - 距減半天數：最近一次減半至今。
    - 距週期低點天數：上一個週期頂部之後的最低收盤日至今（逐日累計，只用當時已知的資料）。
    兩者各自以最近 TIMING_RECENT 次頂部的平均天數為中心計分，再取平均。
    """
    days = pd.Series(index, index=index)
    last_halving = days.apply(lambda d: HALVINGS[HALVINGS <= d].max())
    days_halving = (days - last_halving).dt.days

    anchors = [price[PRE_TOP_MONTH].idxmax()] + list(tops)
    # 頂部當天仍屬於前一輪（side="left"），隔天起才開始找新一輪的低點
    k = pd.Series(np.searchsorted(np.array(anchors, dtype="datetime64[ns]"), index.values, side="left") - 1,
                  index=index)
    low_date = pd.Series(pd.NaT, index=index, dtype="datetime64[ns]")
    for seg_k, seg in price.reindex(index).groupby(k):
        if seg_k < 0:
            continue
        seg = seg.ffill()
        run_min = seg.cummin()
        is_new = seg <= run_min
        low_date[seg.index] = pd.Series(seg.index.where(is_new), index=seg.index).ffill()
    days_low = (days - low_date).dt.days

    top_h = [int(days_halving[t]) for t in tops]
    top_l = [int(days_low[t]) for t in tops]
    center_h = float(np.mean(top_h[-TIMING_RECENT:]))
    center_l = float(np.mean(top_l[-TIMING_RECENT:]))
    th = _trap(days_halving, center_h) * 100
    tl = _trap(days_low, center_l) * 100
    timing = (th + tl) / 2
    df = pd.DataFrame({"days_since_halving": days_halving, "days_since_low": days_low,
                       "timing_halving": th, "timing_low": tl, "timing": timing,
                       "cycle_low_date": low_date})
    info = {"center_halving_days": round(center_h), "center_low_days": round(center_l),
            "flat_days": TIMING_FLAT, "ramp_days": TIMING_RAMP,
            "past_tops_halving_days": dict(zip([str(t.date()) for t in tops], top_h)),
            "past_tops_low_days": dict(zip([str(t.date()) for t in tops], top_l))}
    return df, info


def top_signal(heat: pd.Series, timing: pd.Series) -> pd.Series:
    return heat.rolling(7, min_periods=1).mean() * timing / 100


def heat_zone(heat: float) -> str:
    if heat >= 65:
        return "hot"
    if heat >= 40:
        return "warm"
    return "cold"


def signal_level(sig: float) -> str:
    if sig >= SIGNAL_ALERT:
        return "alert"
    if sig >= SIGNAL_WINDOW:
        return "window"
    return "none"

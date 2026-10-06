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

# key: (類別, 名稱, 單位, 角色, 說明)。角色 score = 計入熱度
INDICATORS = {
    "mvrv_z": ("onchain_valuation", "MVRV Z-score", "", "score",
               "市值與實現市值（所有幣最後移動時價格的總和）的差距，以標準差衡量。越高代表整體未實現獲利越大。"),
    "nupl": ("onchain_valuation", "NUPL", "", "score",
             "淨未實現損益占市值比例。接近 0.75 以上歷來是極度貪婪區。"),
    "puell": ("onchain_valuation", "Puell Multiple", "", "score",
              "礦工每日收入 ÷ 365 日均。礦工收入異常高時，往往是價格過熱。"),
    "rp_multiple": ("onchain_valuation", "實現價格倍數", "x", "score",
                    "價格 ÷ 實現價格（市場平均持幣成本）。數學上等於 MVRV。"),
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

def indicator_defs() -> dict:
    return INDICATORS


def unavailable_defs() -> dict:
    return UNAVAILABLE


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


def find_cycles(price: pd.Series, top_months=None):
    """回傳 (頂部日期列表, 底部日期列表)。頂部 = 指定月份最高收盤日；底部 = 兩頂之間最低收盤日。
    top_months 可指定只用部分頂部（策略逐輪回測用：只用當時已發生的頂部）。"""
    tops = [price[m].idxmax() for m in (top_months or TOP_MONTHS)]
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

    # 底部用：Hash Ribbons（算力 30 日均 ÷ 60 日均 − 1，%）；低於 0 代表礦工投降
    ind["hash_ribbon"] = (cm["HashRate"].rolling(30, min_periods=25).mean()
                          / cm["HashRate"].rolling(60, min_periods=50).mean() - 1) * 100

    # 底部用：AHR999 =（價格 ÷ 200 日幾何平均）×（價格 ÷ 長期指數成長估值）
    age = (idx - pd.Timestamp("2009-01-03")).days.astype(float)
    growth = pd.Series(10 ** (5.84 * np.log10(age) - 17.01), index=idx)
    gm200 = np.exp(np.log(cm["PriceUSD"]).rolling(200, min_periods=200).mean())
    ind["ahr999"] = (cm["PriceUSD"] / gm200) * (cm["PriceUSD"] / growth)
    # 底部參考（不計分）：Delta Price =（實現市值 − 平均市值）÷ 流通量；平均市值為上市以來市值的累計平均（只用當天以前）。
    # 2026-10 驗證：三次底部 1.01–1.24 倍、假底部 ≥1.42 倍；加入冷度後分辨力略降（與 MVRV 相關 0.67），因此只作參考。
    ind["delta_price"] = (rc - mc.expanding().mean()) / cm["SplyCur"]
    ind["delta_ratio"] = cm["PriceUSD"] / ind["delta_price"]
    # 底部用：Power Law = 價格 ÷ 冪律趨勢價（log 價格對 log 天數的直線；每天只用當天以前的資料擬合，無前視）
    ind["powerlaw"] = powerlaw_ratio(cm["PriceUSD"])

    # 二、持有者行為：無免費、可公開的完整歷史資料（交易所流量實測方向失效，已移除）

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

    for k in INDICATORS:
        if k not in ind:
            ind[k] = np.nan
    return ind


def powerlaw_ratio(price: pd.Series, min_days: int = 730) -> pd.Series:
    """價格 ÷ 冪律趨勢價。趨勢線 log10(價格) = a + b·log10(距創世區塊天數)，以擴展視窗逐日擬合（只用當天以前的資料）；
    前 min_days 天資料太少不計算。"""
    p = price.where(price > 0)
    x = pd.Series(np.log10((p.index - pd.Timestamp("2009-01-03")).days.astype(float)), index=p.index)
    y = np.log10(p)
    ok = y.notna()
    xs, ys = x.where(ok, 0.0), y.fillna(0.0)
    n, sx, sy = ok.cumsum(), xs.cumsum(), ys.cumsum()
    sxx, sxy = (xs * xs).cumsum(), (xs * ys).cumsum()
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    a = (sy - b * sx) / n
    r = 10 ** (y - (a + b * x))
    first = p.first_valid_index()
    return r.where(p.index >= first + pd.Timedelta(days=min_days)) if first is not None else r


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


def compute_heat(ind: pd.DataFrame, top_months=None):
    """回傳 (指標分數, 指標百分位, 類別分數, 熱度, meta, tops, bottoms)。"""
    defs = indicator_defs()
    for k in defs:
        if k not in ind:
            ind[k] = np.nan
    tops, bottoms = find_cycles(ind["price"].dropna(), top_months)
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


# =====================================================================
# 底部訊號（2026-10 加入）
# 參數只依 2015、2018、2022 三次底部與中段假底部（2019-12、2020-03、2021-07、2024-08）決定，
# 未參考 2026 年資料，因此本輪（2026）的結果是樣本外檢驗。
# 底部訊號 = 冷度（7 日均）× 底部時機 ÷ 100
# =====================================================================
BOTTOM_WINDOW = 50  # 底部訊號 ≥ 此值：底部區
BOTTOM_STRONG = 70  # 底部訊號 ≥ 此值：強烈底部
COLD_WEIGHTS = {"valuation": 0.5, "miners": 0.3, "price": 0.2}
RIBBON_FULL = 5.0   # 近 90 日 Hash Ribbon 最深 −5% 視為完全投降（100 分）

COLD_INDICATORS = {
    # key: (群組, 名稱, 來源欄位, 單位, 說明)
    "cold_mvrv": ("valuation", "MVRV（價格 ÷ 實現價格）", "rp_multiple", "x",
                  "低於 1 代表價格跌破市場平均持幣成本。過去三次底部為 0.56、0.69、0.75。"),
    "cold_nupl": ("valuation", "NUPL", "nupl", "",
                  "淨未實現損益。過去三次底部都轉為負值（整體市場帳面虧損）。"),
    "cold_puell": ("miners", "Puell Multiple", "puell", "",
                   "礦工收入相對一年均值。過去三次底部為 0.31、0.39、0.48。2024 減半後礦工收入結構性下降，可能使此項偏冷。"),
    "cold_ribbon": ("miners", "Hash Ribbons（近 90 日最深）", "hash_ribbon_min90", "%",
                    "算力 30 日均跌破 60 日均代表礦工關機投降，常出現在底部前後；但減半後與政策事件也會發生，僅作輔助。"),
    "cold_ahr999": ("price", "AHR999", "ahr999", "",
                    "價格相對 200 日幾何平均與長期指數成長曲線的位置。過去三次底部為 0.23、0.27、0.26；慣用 1.2 為定投線（中性）。"),
    "cold_powerlaw": ("price", "Power Law（價格 ÷ 冪律趨勢價）", "powerlaw", "x",
                      "比特幣長期價格沿冪律曲線成長（對數價格與對數天數近似直線）；趨勢線每天只用當天以前的資料擬合。"
                      "1.0 倍＝趨勢價（中性）；過去三次底部為 0.24、0.48、0.36 倍。與 AHR999 高度相關，同組平均、不重複計分。"
                      "只用於底部：頂部倍數逐輪快速下降（8.5→6.6→2.3→1.1），且 2021-04、2024-03 中段高點不低於真頂部。"),
}
COLD_GROUP_LABEL = {"valuation": "估值", "miners": "礦工", "price": "價格結構"}
# 中性點固定的指標（其頂部讀數遞減過快，外推的預期頂部會低於預期底部，中點因此失去意義）：
# Puell 定義為「礦工收入 ÷ 一年均值」，1.0 即中性；AHR999 慣用 1.2 為定投線；Power Law 以趨勢價（1.0 倍）為中性。
# Power Law 已測試（2026-10）：三次底部訊號 73/95/83 → 74/93/84，四次假底部仍為 0、熊市外 ≥50 天數仍為 0，因此加入價格結構組。
# Pi Cycle（111 日均 ÷ 350 日均×2）已測試：加入頂部訊號後 2021 頂部下降、窗外假訊號上升，未採用。
COLD_NEUTRAL_FIXED = {"cold_puell": 1.0, "cold_ahr999": 1.2, "cold_powerlaw": 1.0}


def compute_cold(ind: pd.DataFrame, tops, bottoms):
    """冷度（0–100）。週期法：本輪預期底部 = 過去底部讀數擬合外推；中性 = 本輪預期底部與預期頂部的中點；
    冷度 = (中性 − 當前) ÷ (中性 − 預期底部) × 100（0–120）。Puell 中性固定為 1.0。Hash Ribbons 依投降深度計分。"""
    k = _cycle_index(ind.index, tops)
    ind = ind.copy()
    ind["hash_ribbon_min90"] = ind["hash_ribbon"].rolling(90, min_periods=30).min()
    scores = pd.DataFrame(index=ind.index)
    meta = {}
    for key, (grp, label, col, unit, desc) in COLD_INDICATORS.items():
        s = ind[col]
        if key == "cold_ribbon":
            scores[key] = (-s / RIBBON_FULL * 100).clip(0, 100)
            meta[key] = {"method": "ribbon", "full_at": -RIBBON_FULL}
            continue
        bot_pts = [(i + 0.5, s.get(b)) for i, b in enumerate(bottoms) if pd.notna(s.get(b))]
        top_pts = [(i, s.get(t)) for i, t in enumerate(tops) if pd.notna(s.get(t))]
        if not bot_pts or not top_pts:  # 已知頂部／底部的指標資料不足（僅逐輪回測的早期會發生）
            scores[key] = np.nan
            meta[key] = {"method": None}
            continue
        bot = k.map(lambda i: _fit(*zip(*bot_pts), i - 0.5))
        top = k.map(lambda i: _fit(*zip(*top_pts), i))
        neutral = (bot + top) / 2 if key not in COLD_NEUTRAL_FIXED else pd.Series(COLD_NEUTRAL_FIXED[key], index=s.index)
        scores[key] = ((neutral - s) / (neutral - bot) * 100).clip(0, 120)
        meta[key] = {"method": "cycle_bottom", "expected_bottom": float(bot.iloc[-1]), "neutral": float(neutral.iloc[-1]),
                     "past_bottoms": {str(bottoms[int(x - 0.5)].date()): v for x, v in bot_pts}}
    filled = scores.ffill()
    groups = pd.DataFrame({g: filled[[k_ for k_, d in COLD_INDICATORS.items() if d[0] == g]].mean(axis=1)
                           for g in COLD_WEIGHTS})
    cold = sum(groups[g] * w for g, w in COLD_WEIGHTS.items()).clip(0, 100)
    return scores, groups, cold, meta, ind["hash_ribbon_min90"]


def compute_bottom_timing(index: pd.DatetimeIndex, price: pd.Series, tops, bottoms):
    """底部時機（0–100）：距上次頂部天數、距上次減半天數，各以過去三次底部的平均為中心。"""
    days = pd.Series(index, index=index)
    days_halving = (days - days.apply(lambda d: HALVINGS[HALVINGS <= d].max())).dt.days
    anchors = np.array([price[PRE_TOP_MONTH].idxmax()] + list(tops), dtype="datetime64[ns]")
    pos = np.searchsorted(anchors, index.values, side="left") - 1
    last_top = pd.Series([pd.Timestamp(anchors[i]) if i >= 0 else pd.NaT for i in pos], index=index)
    days_top = (days - last_top).dt.days
    b_top = [(b - tops[i]).days for i, b in enumerate(bottoms)]
    b_h = [int(days_halving[b]) for b in bottoms]
    c_top, c_h = float(np.mean(b_top)), float(np.mean(b_h))
    tt = _trap(days_top, c_top) * 100
    th = _trap(days_halving, c_h) * 100
    df = pd.DataFrame({"days_since_top": days_top, "days_since_halving": days_halving,
                       "timing_top": tt, "timing_halving": th, "timing": (tt + th) / 2, "last_top": last_top})
    info = {"center_top_days": round(c_top), "center_halving_days": round(c_h),
            "flat_days": TIMING_FLAT, "ramp_days": TIMING_RAMP,
            "past_bottoms_top_days": dict(zip([str(b.date()) for b in bottoms], b_top)),
            "past_bottoms_halving_days": dict(zip([str(b.date()) for b in bottoms], b_h))}
    return df, info


def bottom_signal(cold: pd.Series, timing: pd.Series) -> pd.Series:
    return cold.rolling(7, min_periods=1).mean() * timing / 100


def bottom_level(sig: float) -> str:
    if sig >= BOTTOM_STRONG:
        return "strong"
    if sig >= BOTTOM_WINDOW:
        return "zone"
    return "none"

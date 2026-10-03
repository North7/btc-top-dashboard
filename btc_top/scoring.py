"""指標計算與正規化。

核心方法（見 CLAUDE.md「正規化方法」）：
- 週期法：取各次週期頂部當日數值，以對數線性擬合遞減趨勢，推估本輪預期頂部值；
  底部同理推估下界。分數 = 當前值在「下界 → 預期頂部」的位置 × 100，可超過 100，下限 0。
- 百分位法：歷史不足 3 個週期的指標，用自身過去 4 年的滾動百分位。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TOP_MONTHS = ["2013-12", "2017-12", "2021-11", "2025-10"]
HALVINGS = pd.to_datetime(["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20", "2028-04-15"])
# 2028 減半日期為依區塊速度的估計值，實際日期出來後請更新

CATEGORIES = {
    "onchain_valuation": {"label": "鏈上估值", "weight": 0.35},
    "holder_behavior": {"label": "持有者行為", "weight": 0.20},
    "capital_flows": {"label": "資金流與機構", "weight": 0.20},
    "leverage": {"label": "槓桿與衍生品", "weight": 0.15},
    "sentiment_cycle": {"label": "情緒與週期", "weight": 0.10},
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

PCT_WINDOW = 1460  # 百分位滾動視窗（天）
PCT_MIN = 90       # 至少需要的資料點（太少時百分位無意義，分數留空）


def find_cycles(price: pd.Series):
    """回傳 (頂部日期列表, 底部日期列表)。頂部 = 指定月份最高收盤日；底部 = 兩頂之間最低收盤日。"""
    tops = [price[m].idxmax() for m in TOP_MONTHS]
    bottoms = [price[tops[i]:tops[i + 1]].idxmin() for i in range(len(tops) - 1)]
    return tops, bottoms


def build_indicators(raw: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """由原始資料計算各指標的每日數值。回傳 (DataFrame, 指標定義)。"""
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

    # 二、持有者行為：交易所 30 日淨流入（占流通量 %）
    net = (cm["FlowInExNtv"] - cm["FlowOutExNtv"]).rolling(30, min_periods=25).sum()
    ind["exchange_netflow_30d_pct"] = net / cm["SplyCur"] * 100

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

    # 五、情緒與週期
    if len(raw.get("fear_greed", [])):
        ind["fear_greed_7d"] = raw["fear_greed"]["fear_greed"].reindex(idx).rolling(7, min_periods=5).mean()
    last_halving = pd.Series(idx, index=idx).apply(lambda d: HALVINGS[HALVINGS <= d].max())
    ind["days_since_halving"] = (pd.Series(idx, index=idx) - last_halving).dt.days

    defs = {
        "mvrv_z": ("onchain_valuation", "MVRV Z-score", ""),
        "nupl": ("onchain_valuation", "NUPL", ""),
        "puell": ("onchain_valuation", "Puell Multiple", ""),
        "rp_multiple": ("onchain_valuation", "實現價格倍數", "x"),
        "exchange_netflow_30d_pct": ("holder_behavior", "交易所 30 日淨流入", "% 流通量"),
        "etf_flow_30d": ("capital_flows", "ETF 30 日累計淨流入", "百萬美元"),
        "etf_flow_momentum": ("capital_flows", "ETF 流入動能", "百萬美元"),
        "stable_growth_90d": ("capital_flows", "穩定幣 90 日增速", "%"),
        "coinbase_premium_7d": ("capital_flows", "Coinbase 溢價（7 日均）", "%"),
        "funding_7d_ann": ("leverage", "資金費率 7 日均（年化）", "%"),
        "oi_to_mcap": ("leverage", "未平倉量 / 市值", "%"),
        "basis_ann": ("leverage", "期現基差（年化）", "%"),
        "fear_greed_7d": ("sentiment_cycle", "恐懼貪婪指數（7 日均）", ""),
        "days_since_halving": ("sentiment_cycle", "距最近一次減半", "天"),
    }
    # ETF 尚無資料時仍列出，之後標記 unavailable
    for k in defs:
        if k not in ind:
            ind[k] = np.nan
    return ind, defs


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
    # 每天所屬的週期序號 k = 該日之前已發生的頂部數
    k = pd.Series(np.searchsorted(np.array(tops, dtype="datetime64[ns]"), s.index.values, side="left"),
                  index=s.index)
    bot = k.map(lambda i: cp["params"][i][0])
    top = k.map(lambda i: cp["params"][i][1])
    return ((s - bot) / (top - bot) * 100).clip(lower=0)


def score_percentile(s: pd.Series) -> pd.Series:
    v = s.dropna()
    if len(v) < PCT_MIN:
        return pd.Series(np.nan, index=s.index)
    r = v.rolling(PCT_WINDOW, min_periods=PCT_MIN).rank(pct=True) * 100
    return r.reindex(s.index)


def score_halving(days: pd.Series, tops) -> tuple[pd.Series, float]:
    """距減半天數：以各次頂部距減半天數線性外推本輪預期天數 E。

    分數 = 天數 / E × 100（到 E 時為 100），超過 E 後線性下降，在 1.5E 時歸 0，
    避免熊市後期仍被誤判為「熱」。
    """
    top_days = [days[t] for t in tops]
    b, a = np.polyfit(range(len(top_days)), top_days, 1)
    expected = a + b * len(top_days)
    up = days / expected * 100
    down = (100 - (days - expected) / expected * 200).clip(lower=0)
    return up.where(days <= expected, down), float(expected)


def compute_scores(ind: pd.DataFrame, defs: dict):
    tops, bottoms = find_cycles(ind["price"].dropna())
    scores = pd.DataFrame(index=ind.index)
    meta = {}
    for key, (cat, label, unit) in defs.items():
        s = ind[key]
        if s.notna().sum() == 0:
            meta[key] = {"method": None}
            scores[key] = np.nan
            continue
        if key == "days_since_halving":
            scores[key], expected = score_halving(s, tops)
            meta[key] = {"method": "halving", "expected_top_days": round(expected)}
            continue
        cp = cycle_params(s, tops, bottoms)
        if cp:
            scores[key] = score_cycle(s, tops, cp)
            bot, top = cp["params"][len(tops)]
            meta[key] = {"method": "cycle", "bottom_bound": bot, "expected_top": top,
                         "past_tops": {str(tops[i].date()): v for i, v in cp["top_values"].items()}}
        else:
            scores[key] = score_percentile(s)
            meta[key] = {"method": "percentile", "history_days": int(s.notna().sum())}

    # 類別分數：同類指標先平均。指標向前沿用最後一筆數值（對齊各來源更新時間；
    # 抓取失敗時沿用前值），是否過期由 run.py 的 stale 標記表示
    filled = scores.ffill()
    cat_scores = pd.DataFrame(index=ind.index)
    for cat in CATEGORIES:
        cols = [k for k, d in defs.items() if d[0] == cat]
        cat_scores[cat] = filled[cols].mean(axis=1, skipna=True)
    w = pd.Series({c: v["weight"] for c, v in CATEGORIES.items()})
    avail = cat_scores.notna()
    weighted = (cat_scores.fillna(0) * w).sum(axis=1) / (avail * w).sum(axis=1)
    composite = weighted.clip(0, 100).where(avail.any(axis=1))
    return scores, cat_scores, composite, meta, tops, bottoms


def zone_of(composite: float, hot: int) -> str:
    if composite >= 80 and hot >= 3:
        return "top_zone"
    if composite >= 65:
        return "hot"
    if composite >= 40:
        return "warm"
    return "cold"

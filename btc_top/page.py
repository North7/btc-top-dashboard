"""產生 docs/index.html：分頁式儀表板。靜態、內嵌資料、不在瀏覽器端呼叫外部 API。"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import pandas as pd

from btc_top.midterm import _events as _mid_events
from btc_top.scoring import BOTTOM_STRONG, BOTTOM_WINDOW, COLD_INDICATORS, INDICATORS, PCT_PIVOT, SIGNAL_ALERT, SIGNAL_WINDOW

REPO = "https://github.com/North7/tidemark"
BRAND = "Tidemark"          # 產品名稱（潮汐：頂部＝滿潮、底部＝退潮）；改名只需改這裡
BRAND_ZH = "⟪BTC 週期訊號|BTC Cycle Signals⟫"
LOGO_SVG = ('<svg class="logo" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#e0525d"/><stop offset="1" stop-color="#22a57f"/></linearGradient></defs>'
            '<rect width="32" height="32" rx="9" fill="url(#lg)"/>'
            '<path d="M6 18.5c2.6 0 2.6-7 5.2-7s2.6 7 5.2 7 2.6-7 5.2-7 2.6 7 4.4 7" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
            '<circle cx="11.2" cy="11.5" r="1.6" fill="#fff"/></svg>')
FAVICON = ("data:image/svg+xml," + LOGO_SVG.replace('class="logo" ', 'xmlns="http://www.w3.org/2000/svg" ')
           .replace("#", "%23").replace('"', "'").replace("<", "%3C").replace(">", "%3E"))
LEVEL_TEXT = {"none": "⟪未觸發|Not triggered⟫", "window": "⟪頂部窗口|Top window⟫", "alert": "⟪高度警戒|High alert⟫"}
HEAT_TEXT = {"cold": "⟪冷|Cold⟫", "warm": "⟪溫|Warm⟫", "hot": "⟪熱|Hot⟫"}
CAT_SHORT = {"onchain_valuation": "⟪鏈上|On-chain⟫", "holder_behavior": "⟪持有者|Holders⟫", "capital_flows": "⟪資金流|Flows⟫",
             "leverage": "⟪槓桿|Leverage⟫", "sentiment_cycle": "⟪情緒|Sentiment⟫"}


# =====================================================================
# 雙語：文字寫成 ⟪中文|English⟫，產生頁面時依語言挑出一邊
# =====================================================================
import re as _re
_LANG = "zh"
_MARK = _re.compile(r"⟪(.*?)\|(.*?)⟫", _re.S)


def _pick(text: str) -> str:
    return _MARK.sub(lambda m: m.group(2) if _LANG == "en" else m.group(1), text)


# 指標英文名稱與說明（中文來自 scoring.py）
IND_EN = {
    "mvrv_z": ("MVRV Z-score", "Gap between market cap and realized cap (sum of each coin's last-moved price), in standard deviations. Higher means larger unrealized profit across the network."),
    "nupl": ("NUPL", "Net unrealized profit/loss as a share of market cap. Readings near 0.75+ have marked extreme greed."),
    "puell": ("Puell Multiple", "Daily miner revenue ÷ its 365-day average. Unusually high miner income tends to coincide with overheated prices."),
    "rp_multiple": ("Realized price multiple", "Price ÷ realized price (the market's average cost basis). Mathematically equal to MVRV."),
    "etf_flow_30d": ("ETF 30-day net inflow", "Net creations into US spot bitcoin ETFs over the last 30 days."),
    "etf_flow_momentum": ("ETF flow momentum", "Last 30 days of net inflow minus the prior 30 days; positive means inflows are accelerating."),
    "stable_growth_90d": ("Stablecoin 90-day growth", "90-day growth of total stablecoin supply — new capital available on exchanges."),
    "coinbase_premium_7d": ("Coinbase premium (7d avg)", "Coinbase USD price vs OKX USDT price; reflects US buying pressure."),
    "funding_7d_ann": ("Funding rate 7d avg (annualized)", "Rate longs pay shorts on perpetual futures. Higher means crowded leveraged longs."),
    "oi_to_mcap": ("Open interest / market cap", "Total BTC futures open interest as a share of market cap — the size of leverage."),
    "basis_ann": ("Futures basis (annualized)", "Annualized premium of quarterly futures over spot. Higher means buyers pay up for futures."),
    "fear_greed_7d": ("Fear & Greed Index (7d avg)", "alternative.me sentiment index combining volatility, volume, social and search data (0–100)."),
    "cold_mvrv": ("MVRV (price ÷ realized price)", "Below 1 means price is under the market's average cost basis. Past bottoms: 0.56, 0.69, 0.75."),
    "cold_nupl": ("NUPL", "Net unrealized profit/loss. It turned negative (network-wide unrealized loss) at all three past bottoms."),
    "cold_puell": ("Puell Multiple", "Miner revenue vs its one-year average. Past bottoms: 0.31, 0.39, 0.48. Structurally lower miner revenue after the 2024 halving may make this read colder."),
    "cold_ribbon": ("Hash Ribbons (deepest in 90d)", "Hashrate 30d avg falling below 60d avg means miners are capitulating — common around bottoms, but also after halvings and policy shocks, so it is only supporting evidence."),
    "cold_ahr999": ("AHR999", "Price relative to its 200-day geometric mean and a long-term exponential growth curve. Past bottoms: 0.23, 0.27, 0.26; 1.2 is the customary DCA line (neutral)."),
    "cold_powerlaw": ("Power Law (price ÷ power-law trend)", "Bitcoin's long-run price has grown along a power law (log price vs. log days is close to a straight line); the trend line is fitted each day using only data up to that day. 1.0x = trend price (neutral); past bottoms: 0.24x, 0.48x, 0.36x. Highly correlated with AHR999, so the two are averaged within one group rather than double-counted. Used for bottoms only: top multiples fall fast each cycle (8.5→6.6→2.3→1.1), and the 2021-04 and 2024-03 mid-cycle highs were as high as the real tops."),
}
CAT_EN = {"onchain_valuation": "On-chain valuation", "holder_behavior": "Holder behavior", "capital_flows": "Capital flows",
          "leverage": "Leverage & derivatives", "sentiment_cycle": "Sentiment"}
GRP_EN = {"估值": "Valuation", "礦工": "Miners", "價格結構": "Price structure"}
UNIT_EN = {"百萬美元": "USD m", "% 流通量": "% of supply", "百萬幣天": "M coin-days", "天": "days"}
REASON_EN = {"lth_supply_change": "Long-term holder supply change (needs Glassnode / CryptoQuant)",
             "lth_sopr": "LTH-SOPR (needs Glassnode / CryptoQuant)", "cdd_dormancy": "CDD / Dormancy (needs Glassnode / CryptoQuant)",
             "google_trends": "Google Trends “bitcoin” (no official free API; skipped in v1)"}


def _m(zh: str, en: str) -> str:
    return f"⟪{html.escape(zh)}|{html.escape(en)}⟫"


def _lab(k, zh):
    return _m(zh, IND_EN.get(k, (zh, ""))[0])


def _desc(k, zh):
    return _m(zh, IND_EN.get(k, ("", zh))[1])


def _cat(k, zh):
    return _m(zh, CAT_EN.get(k, zh))


def _grp(zh):
    return _m(zh, GRP_EN.get(zh, zh))


def _unit(u):
    return _m(u, UNIT_EN[u]) if u in UNIT_EN else u


def _reason(k, zh):
    return _m(zh, REASON_EN.get(k, zh))


def _verdict(ct) -> str:
    cur, d = ct["current_low"], ct["decisive_date"]
    price = f"${cur['price']:,.0f}"
    if ct["status"] == "testing":
        return (f"⟪驗證中：若到 {d} 為止都沒有跌破本輪低點 {price}（{cur['date']}），支持「本輪低點即週期底部、ETF 時代熊市變淺」；"
                f"若之後出現更低的低點且 MVRV 跌破 1，則代表底部尚未出現。"
                f"|Testing: if price holds above this cycle's low of {price} ({cur['date']}) through {d}, that supports "
                f"“this low is the cycle bottom and ETF-era bears are shallower”. A lower low with MVRV below 1 would mean the bottom is still ahead.⟫")
    shallow = ct["days_mvrv_below_1_this_cycle"] == 0
    return (f"⟪底部時間窗口已於 {d} 結束，本輪低點 {cur['date']}（{price}）未被跌破，"
            + ("且估值未出現投降（MVRV 從未跌破 1），支持「熊市變淺」。" if shallow else "期間曾出現估值投降（MVRV 跌破 1），屬傳統型底部。")
            + f"|The bottom window closed on {d} and this cycle's low of {cur['date']} ({price}) held. "
            + ("Valuation never capitulated (MVRV never below 1), supporting “shallower bear markets”." if shallow
               else "Valuation did capitulate (MVRV below 1) — a classic bottom.") + "⟫")


def _fmt(v, unit=""):
    if v is None:
        return "—"
    a = abs(v)
    s = f"{v:,.0f}" if a >= 1000 else f"{v:,.2f}" if a >= 1 else f"{v:.3f}"
    if unit in ("", None):
        return s
    return f"{s}{unit}" if unit in ("x", "%") else f"{s} {unit}"


def _method(i):
    m = i.get("method")
    if m == "cycle":
        return f"⟪週期法：本輪下界|Cycle method: this cycle's floor⟫ {_fmt(i.get('bottom_bound'))} → ⟪預期頂部|expected top⟫ {_fmt(i.get('expected_top'))}"
    if m == "percentile":
        p = i.get("percentile")
        return (f"⟪4 年百分位|4-yr percentile⟫ {p:.0f}%" if p is not None else "⟪百分位（資料累積中）|Percentile (collecting data)⟫") + f"⟪，超過 {PCT_PIVOT}% 才開始計分|; scores only above {PCT_PIVOT}%⟫"
    return ""


def _method_short(i):
    return {"cycle": "⟪週期法|Cycle method⟫", "percentile": "⟪4 年百分位|4-yr percentile⟫"}.get(i.get("method"), "")


def _band(score):
    if score is None:
        return "na"
    return "top" if score >= 80 else "hot" if score >= 65 else "warm" if score >= 40 else "cold"


def _heat_zone(h):
    return "hot" if h >= 65 else "warm" if h >= 40 else "cold"


def _n(v):
    return "—" if v is None or pd.isna(v) else f"{v:.0f}"


def _series(hist: pd.DataFrame, ind: pd.DataFrame, defs: dict) -> dict:
    """內嵌資料：一年前以前每週一點，最近一年每日一點。"""
    cols = {"p": hist["price"], "sig": hist["top_signal"], "heat": hist["heat_7d"], "tim": hist["timing"],
            "bsig": hist["bottom_signal"], "cold": hist["cold_7d"]}
    for k in defs:
        cols["v_" + k] = ind[k].reindex(hist.index)
        if defs[k][3] == "score":
            cols["s_" + k] = hist["score_" + k]
    for k, (grp, label, col, unit, desc) in COLD_INDICATORS.items():
        cols["v_" + k] = (hist[col] if col in hist else ind[col].reindex(hist.index))
        cols["s_" + k] = hist["coldscore_" + k]
    for k, col in (("seq", "strat_eq"), ("sbh", "strat_bh"), ("ma50", "mid_ma50"), ("ma200", "mid_ma200"), ("ma20w", "mid_ma20w"), ("stl", "mid_st_line"), ("std", "mid_st_dir")):
        if col in hist:
            cols[k] = hist[col]
    cols["v_days_since_halving"] = hist["days_since_halving"]
    cols["v_days_since_low"] = hist["days_since_low"]
    df = pd.DataFrame(cols).dropna(subset=["p"])
    cut = df.index.max() - pd.Timedelta(days=365)
    df = pd.concat([df[df.index < cut].resample("W").last(), df[df.index >= cut]])

    def arr(s):
        return [None if pd.isna(x) else round(float(x), 4 if abs(x) < 10 else 1) for x in s]

    return {"d": [d.strftime("%Y-%m-%d") for d in df.index], **{k: arr(df[k]) for k in df.columns}}


def _gauge(value, size, stroke, color, thresholds=()):
    """270° 弧形儀表（0–100）。"""
    r = (size - stroke) / 2 - 2
    c = 2 * math.pi * r
    arc = 0.75 * c
    v = max(0.0, min(100.0, value or 0)) / 100 * arc
    cx = cy = size / 2
    ticks = ""
    for t in thresholds:
        a = math.radians(135 + 270 * t / 100)
        r1, r2 = r - stroke / 2 - 3, r + stroke / 2 + 3
        ticks += (f'<line x1="{cx + r1 * math.cos(a):.1f}" y1="{cy + r1 * math.sin(a):.1f}" '
                  f'x2="{cx + r2 * math.cos(a):.1f}" y2="{cy + r2 * math.sin(a):.1f}" class="g-tick"/>')
    return (f'<svg class="gauge" viewBox="0 0 {size} {size}" aria-hidden="true">'
            f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" class="g-track" stroke-width="{stroke}" '
            f'stroke-dasharray="{arc:.1f} {c:.1f}" transform="rotate(135 {cx} {cy})"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" class="g-val" stroke="var({color})" stroke-width="{stroke}" '
            f'stroke-dasharray="{v:.1f} {c:.1f}" transform="rotate(135 {cx} {cy})"/>{ticks}</svg>')


def _pct(d, start, end):
    return max(0.0, min(100.0, (pd.Timestamp(d) - start).days / max(1, (end - start).days) * 100))


def _cycle_timeline(latest: dict) -> str:
    """總覽：從上次頂部到預估窗口的時間軸。"""
    t = latest["timing"]
    wh, wl = t["expected_window_by_halving"], t["expected_window_by_low"]
    start = pd.Timestamp(latest["cycle_tops"][-1])
    end = max(pd.Timestamp(wh["to"]), pd.Timestamp(wl["full_to"])) + pd.Timedelta(days=60)
    now = pd.Timestamp(latest["date"])
    p = lambda d: f"{_pct(d, start, end):.2f}%"
    years = "".join(f'<span class="tl-year" style="left:{p(f"{y}-01-01")}">{y}</span>'
                    for y in range(start.year + 1, end.year + 1))
    marks = [(latest["cycle_tops"][-1], "⟪上次頂部|Last top⟫", "m-top"), (t["cycle_low_date"], "⟪本輪低點|Cycle low⟫", "m-low")]
    if t.get("next_halving"):
        marks.append((t["next_halving"], "⟪減半（估）|Halving (est.)⟫", "m-halving"))
    marks.sort(key=lambda m: m[0])
    marks_html, last_x, row = "", -100.0, 0
    for d, lbl, cls in marks:
        x = _pct(d, start, end)
        row = 1 - row if x - last_x < 24 else 0  # 太近的標籤錯開到第二排（手機上一個標籤約占 20% 寬）
        last_x = x
        align = " al" if x < 10 else " ar" if x > 90 else ""  # 兩端標籤靠邊對齊，避免超出卡片
        marks_html += (f'<span class="tl-mark {cls}{" r2" if row else ""}{align}" style="left:{x:.2f}%" title="{lbl} {d}">'
                       f'<i></i><b>{lbl}</b></span>')
    full_c = pd.Timestamp(wh["full_from"]) + (pd.Timestamp(wh["full_to"]) - pd.Timestamp(wh["full_from"])) / 2
    months = max(0, round((full_c - now).days / 30.4))
    return f"""
<div class="tl">
  <div class="tl-track">
    <span class="tl-band soft" style="left:{p(wh['from'])};width:calc({p(wh['to'])} - {p(wh['from'])})"></span>
    <span class="tl-band low" style="left:{p(wl['full_from'])};width:calc({p(wl['full_to'])} - {p(wl['full_from'])})"></span>
    <span class="tl-band" style="left:{p(wh['full_from'])};width:calc({p(wh['full_to'])} - {p(wh['full_from'])})"></span>
    <span class="tl-progress" style="width:{p(now)}"></span>
    {marks_html}
    <span class="tl-now" style="left:{p(now)}"><b>⟪現在|Now⟫</b></span>
  </div>
  <div class="tl-years">{years}</div>
</div>
<div class="tl-legend"><span><i class="k-band"></i>⟪依減半推算的頂部窗口|Top window by halving⟫ {wh['full_from'][:7]} ～ {wh['full_to'][:7]}</span>
<span><i class="k-low"></i>⟪依本輪低點推算|By cycle low⟫ {wl['full_from'][:7]} ～ {wl['full_to'][:7]}</span></div>
<p class="muted small">⟪距依減半推算的窗口中心約|About⟫ <b>{months}</b> ⟪個月。若價格再創本輪新低，低點與其推算窗口會往後移。|months to the center of the halving-based window. If price makes a new cycle low, the low and its window shift later.⟫</p>"""


def _clock(days_now, center, flat, ramp, past: dict, label_now, kind="top") -> str:
    """時機頁：天數軌道（過去頂部、窗口、現在位置）。"""
    end = max(1500, days_now + 120)
    p = lambda x: f"{max(0, min(100, x / end * 100)):.2f}%"
    dots = "".join(f'<span class="ck-top{" ck-bot" if kind == "bot" else ""}" style="left:{p(v)}" title="{d[:7]}: {v} ⟪天|days⟫"><i></i></span>'
                   for d, v in past.items())
    # 距離很近的頂部合併成一個標籤（例如 2017·2021·2025），避免文字重疊
    groups = []
    for d, v in sorted(past.items(), key=lambda kv: kv[1]):
        if groups and v - groups[-1][-1][1] < end * 0.06:
            groups[-1].append((d, v))
        else:
            groups.append([(d, v)])
    labels, last_x, row = "", -100.0, 0
    for g in groups:
        x = sum(v for _, v in g) / len(g) / end * 100
        text = "·".join("'" + d[2:4] for d, _ in sorted(g))
        row = 1 - row if x - last_x < 16 else 0  # 太近就錯開到上一排
        last_x = x
        labels += f'<span class="ck-lbl{" r2" if row else ""}" style="left:{x:.2f}%">{text}</span>'
    tops = dots + labels
    ticks = "".join(f'<span class="ck-tick" style="left:{p(x)}">{x}</span>' for x in range(0, end + 1, 250))
    return f"""
<div class="ck">
  <div class="ck-track">
    <span class="ck-band soft" style="left:{p(center - flat - ramp)};width:calc({p(center + flat + ramp)} - {p(center - flat - ramp)})"></span>
    <span class="ck-band" style="left:{p(center - flat)};width:calc({p(center + flat)} - {p(center - flat)})"></span>
    {tops}
    <span class="ck-now{' al' if days_now / end < .1 else ' ar' if days_now / end > .9 else ''}" style="left:{p(days_now)}"><b>{label_now}</b></span>
  </div>
  <div class="ck-ticks">{ticks}</div>
</div>"""


BOTTOM_LEVEL_TEXT = {"none": "⟪未觸發|Not triggered⟫", "zone": "⟪底部區|Bottom zone⟫", "strong": "⟪強烈底部|Strong bottom⟫"}
STATUS_TEXT = {"testing": "⟪驗證中|Testing⟫", "supported": "⟪支持：熊市變淺|Supported: shallower bear⟫", "classic": "⟪傳統型底部|Classic bottom⟫"}


TICKER_CODE = {"mvrv_z": "MVRV-Z", "nupl": "NUPL", "puell": "PUELL", "rp_multiple": "MVRV", "etf_flow_30d": "ETF 30D",
               "etf_flow_momentum": "ETF MOM", "stable_growth_90d": "STABLE 90D", "coinbase_premium_7d": "CB PREMIUM",
               "funding_7d_ann": "FUNDING", "oi_to_mcap": "OI/MCAP", "basis_ann": "BASIS", "fear_greed_7d": "F&amp;G",
               "cold_ribbon": "HASH RIBBON", "cold_ahr999": "AHR999", "cold_powerlaw": "POWER LAW"}


def _tick_val(v, unit):
    if v is None:
        return "—"
    a = abs(v)
    s = f"{v:,.0f}" if a >= 1000 else f"{v:.2f}" if a >= 1 else f"{v:.3f}"
    return s + ("%" if unit == "%" else "")


def _ticker(latest: dict) -> str:
    """瑞士式指標跑馬燈（內容重複兩次以無縫循環）。"""
    items = [("BTC", f"${latest['price_usd']:,.0f}"), ("TOP", f"{latest['top_signal']:.0f}"), ("BOTTOM", f"{latest['bottom_signal']:.0f}")]
    for c in latest["categories"].values():
        for k, i in c["indicators"].items():
            if i.get("status") == "ok" and k in TICKER_CODE:
                items.append((TICKER_CODE[k], _tick_val(i["value"], i.get("unit"))))
    for k, i in latest["bottom"]["indicators"].items():
        if k in TICKER_CODE:
            items.append((TICKER_CODE[k], _tick_val(i["value"], i.get("unit"))))
    row = "".join(f"<span>{k}<b>{v}</b></span>" for k, v in items)
    return f'<div class="ticker" aria-hidden="true"><div class="track">{row}{row}</div></div>'


BAND_TEXT = {"cold": "⟪冷|Cold⟫", "warm": "⟪溫|Warm⟫", "hot": "⟪熱|Hot⟫", "top": "⟪過熱|Very hot⟫", "na": "—"}


def _bigcats(items) -> str:
    """總覽：瑞士式大數字類別格（名稱、權重、分數、分數條）。items: (名稱, 權重, 分數, 連結, 條色 class, 帶狀文字)"""
    cells = []
    for name, w, sc, href, cls, band in items:
        cells.append(
            f'<a class="bigcat" href="{href}" style="--w:{min(sc or 0, 100):.0f}%">'
            f'<span class="bc-top"><span class="bc-name">{name}</span><span class="bc-w">{band + "⟪ · |  ·  ⟫" if band else ""}⟪權重|Weight⟫ {w * 100:.0f}%</span></span>'
            f'<b class="cu" data-v="{_n(sc)}">{_n(sc)}</b>'
            f'<span class="bc-bar"><i class="{cls}"></i><em></em></span></a>')
    return f'<div class="bigcats">{"".join(cells)}</div>'


MID_LABEL = {"rsi_d": "⟪日 RSI(14)|Daily RSI(14)⟫", "ma50": "⟪相對 50 日均線|vs 50-day MA⟫", "roi30": "⟪30 日漲跌|30-day change⟫",
             "fg": "⟪恐懼貪婪（7 日均）|Fear &amp; Greed (7d)⟫", "funding": "⟪資金費率（7 日均・年化）|Funding (7d, annualized)⟫"}
MID_THR = {"<= 0": "≤ 0%", "> p90 (1y)": "⟪近一年前 10%|top 10% of past year⟫", "< -10%": "&lt; −10%", "< -15%": "&lt; −15%"}
REGIME = {
    "bull_trend": ("⟪多頭趨勢|Uptrend⟫", "⟪價格在 200 日均線與 20 週均線之上。|Price is above both the 200-day and 20-week moving averages.⟫", True),
    "bull_pullback": ("⟪多頭回調|Pullback in uptrend⟫", "⟪價格仍在 200 日均線之上，但跌破 20 週均線（牛市支撐帶）。|Price is still above the 200-day MA but has lost the 20-week MA (bull-market support band).⟫", True),
    "bear_rally": ("⟪空頭反彈|Bear-market rally⟫", "⟪價格在 200 日均線之下，但站上 20 週均線。|Price is below the 200-day MA but has reclaimed the 20-week MA.⟫", False),
    "bear_trend": ("⟪空頭趨勢|Downtrend⟫", "⟪價格在 200 日均線與 20 週均線之下。|Price is below both the 200-day and 20-week moving averages.⟫", False),
}


def _spct(x, sign=True):
    return "—" if x is None else (f"{x * 100:+.1f}%" if sign else f"{x * 100:.0f}%").replace("-", "−")


def _mid_val(key, v):
    if v is None:
        return "—"
    if key in ("ma50", "roi30"):
        return _spct(v)
    if key == "funding":
        return f"{v:+.1f}%".replace("-", "−")
    return f"{v:.0f}"


def _midterm(latest: dict) -> str:
    """總覽：中期狀態（趨勢環境、牛市回調觀察、短線過熱）。"""
    m = latest.get("midterm")
    if not m:
        return ""
    name, desc, up = REGIME[m["regime"]]
    arrow = ('<path d="M5 17L11 11l3 3 5-6"/><path d="M14 8h5v5"/>' if up else '<path d="M5 7l6 6 3-3 5 6"/><path d="M14 16h5v-5"/>')
    rows = []
    st = m.get("supertrend_weekly")
    if st:
        upd = st["direction"] == "up"
        rows.append(f'<div class="mid-row"><span>⟪週線 Supertrend|Weekly Supertrend⟫<small>⟪自|since⟫ {st["since"]} '
                    f'{"⟪轉多|turned up⟫" if upd else "⟪轉空|turned down⟫"}</small></span>'
                    f'<span class="r"><b class="{"st-up" if upd else "st-dn"}">{"⟪多方|Up⟫" if upd else "⟪空方|Down⟫"}</b>'
                    f'<small>{"⟪支撐|support⟫" if upd else "⟪壓力|resistance⟫"} ${st["line"]:,.0f} · {_spct(st["distance"])}</small></span></div>')
    for key, lab in (("ma200", "⟪200 日均線|200-day MA⟫"), ("ma20w", "⟪20 週均線（牛市支撐帶）|20-week MA (bull support band)⟫"), ("ma50", "⟪50 日均線|50-day MA⟫")):
        rows.append(f'<div class="mid-row"><span>{lab}</span><span class="r"><b>{_spct(m["dist_" + key])}</b><small>${m[key]:,.0f}</small></span></div>')
    trend = (f'<div class="card mid-card mid-trend"><div class="eyebrow">TREND · {m["as_of"]}</div>'
             f'<div class="mid-big"><svg viewBox="0 0 24 24" aria-hidden="true">{arrow}</svg>{name}</div>'
             f'<p class="mid-desc">{desc}</p><div class="mid-rows">{"".join(rows)}</div></div>')

    def block(kind, title, eyebrow, data):
        hits, need = data["hits"], data["min_hits"]
        dots = "".join(f'<i class="{"on" if i < hits else ""}"></i>' for i in range(5))
        checks = "".join(
            f'<div class="mid-check"><span>{MID_LABEL[c["key"]]}</span><span class="v">{_mid_val(c["key"], c["value"])}</span>'
            f'<span class="t">{MID_THR.get(c["threshold"], c["threshold"].replace("<", "&lt;").replace(">", "&gt;"))}</span>'
            f'<span class="{"ok" if c["met"] else "no"}" aria-label="{"⟪符合|met⟫" if c["met"] else "⟪未符合|not met⟫"}">{"●" if c["met"] else "○"}</span></div>'
            for c in data["conditions"])
        h = data["history"]
        if not data["applicable"]:
            status = ("⟪目前在 200 日均線之下：此訊號只在牛市環境計算（熊市中的超賣歷史上不可靠）。|Price is below the 200-day MA: this signal only applies in a bull-market regime (oversold readings in bear markets have been unreliable).⟫"
                      if kind == "dip" else "⟪目前在 200 日均線之下：過熱提示只在牛市環境計算。|Price is below the 200-day MA: the overheating flag only applies in a bull-market regime.⟫")
        elif data["active"]:
            status = ("⟪觸發：進入牛市回調觀察區|Triggered: bull-market dip zone⟫" if kind == "dip" else "⟪觸發：短線過熱|Triggered: short-term overheating⟫")
        else:
            status = f"⟪未觸發（需符合 {need} 項以上）|Not triggered (needs {need}+)⟫"
        if h.get("events"):
            if kind == "dip":
                stat = (f"⟪{h['since']} 年以來觸發 {h['events']} 次：90 天後報酬中位 {_spct(h['median_90d'])}（上漲比例 {_spct(h['up_90d'], False)}），"
                        f"牛市一般日子為 {_spct(h['base_median_90d'])}；觸發後 30 天內通常還會再跌 {_spct(h['median_further_drop_30d'])}。|"
                        f"Triggered {h['events']} times since {h['since']}: median 90-day return {_spct(h['median_90d'])} ({_spct(h['up_90d'], False)} higher) "
                        f"vs {_spct(h['base_median_90d'])} on ordinary bull-market days; price typically fell another {_spct(h['median_further_drop_30d'])} within 30 days.⟫")
            else:
                stat = (f"⟪{h['since']} 年以來觸發 {h['events']} 次：90 天後報酬中位 {_spct(h['median_90d'])}（牛市一般日子 {_spct(h['base_median_90d'])}）；"
                        f"45 天內跌 ≥15% 的比例 {_spct(h['drop15_45d'], False)}（一般 {_spct(h['base_drop15_45d'], False)}）。|"
                        f"Triggered {h['events']} times since {h['since']}: median 90-day return {_spct(h['median_90d'])} (ordinary bull days {_spct(h['base_median_90d'])}); "
                        f"a 15%+ drop within 45 days followed {_spct(h['drop15_45d'], False)} of the time (ordinary {_spct(h['base_drop15_45d'], False)}).⟫")
            stat += f" ⟪最近：|Recent: ⟫{'⟪、|, ⟫'.join(d[:7] for d in h['recent'])}"
        else:
            stat = ""
        extra = ""
        if kind == "hot":
            tim = latest["timing_score"]
            extra = (f'<p class="mid-hint warn">⟪頂部時機分數 {tim:.0f}：時間已進入歷史頂部窗口，過熱可能是次頂或週期頂部，請同時看頂部訊號。|'
                     f'Top timing score {tim:.0f}: the calendar is inside the historical top window, so overheating may mark a secondary or cycle top — check the top signal.⟫</p>'
                     if tim >= 50 else
                     f'<p class="mid-hint">⟪過熱不是可靠的賣訊號：歷史上之後的走勢好壞參半，大跌的機率只比一般日子略高（見下方統計）。目前頂部時機分數 {tim:.0f}，只有時機也進入頂部窗口時，過熱才可能是次頂。|'
                     f'Overheating is not a reliable sell signal: what followed was mixed, and a big drop was only slightly more likely than on an ordinary day (see the stats below). Top timing is {tim:.0f}; only when timing is also inside the top window can overheating mark a secondary top.⟫</p>')
        return (f'<div class="card mid-card"><div class="card-head"><div><div class="eyebrow">{eyebrow}</div><h3>{title}</h3></div>'
                f'<div class="mid-hits"><b>{hits}<small>/5</small></b><span class="dots">{dots}</span></div></div>'
                f'<div class="mid-status{" on" if data["active"] else ""}">{status}</div>'
                f'<div class="mid-checks">{checks}</div>{extra}<p class="mid-stats">{stat}</p></div>')

    dip = block("dip", "⟪牛市回調觀察|Bull-market dip watch⟫", "DIP WATCH", m["dip"])
    hot = block("hot", "⟪短線過熱|Short-term overheating⟫", "OVERHEAT", m["hot"])
    return f"""
  <div class="view-head"><div class="sec-n">⟪中期狀態|MARKET STATE⟫ · ⟪與頂部／底部訊號無關|INDEPENDENT OF TOP / BOTTOM⟫</div><h2>⟪中期|Market⟫ <span>⟪狀態|state⟫</span></h2>
    <p>⟪趨勢環境、牛市回調與短線過熱。與頂部／底部訊號無關，不隨模式切換；證據比頂部／底部訊號弱，僅供參考。|Trend, bull-market dips and short-term overheating. Independent of the top/bottom signals and unaffected by the mode switch; the evidence is weaker than for those signals — reference only.⟫ </p></div>
  <div id="sec-mid">
    <div class="mid-grid">{trend}{dip}{hot}</div>
    <div class="card mid-chart">
      <div class="card-head"><div><div class="eyebrow">PRICE &amp; TREND</div><h3>⟪價格與趨勢線|Price &amp; trend lines⟫</h3></div>
        <div class="seg" data-g="mid"><button data-y="1">⟪1 年|1Y⟫</button><button data-y="2" class="on">⟪2 年|2Y⟫</button><button data-y="4">⟪4 年|4Y⟫</button></div></div>
      <div class="tip" id="tip-mid"></div>
      <svg class="chart" id="c-mid" height="340" role="img" aria-label="⟪價格、均線與週線 Supertrend|Price, moving averages and weekly Supertrend⟫"></svg>
      <div class="legend">
        <span class="static"><i style="background:var(--fg)"></i>⟪BTC 價格（對數）|BTC price (log)⟫</span>
        <span class="static"><i style="background:var(--s-bot)"></i>⟪週線 Supertrend 多方|Weekly Supertrend up⟫</span>
        <span class="static"><i style="background:var(--s-sig)"></i>⟪週線 Supertrend 空方|Weekly Supertrend down⟫</span>
        <span class="static"><i style="background:var(--s-heat)"></i>⟪200 日均線|200-day MA⟫</span>
        <span class="static"><i style="height:0;background:none;border-top:2px dashed var(--s-cold)"></i>⟪20 週均線|20-week MA⟫</span>
        <span class="static"><i style="background:var(--s-tim)"></i>⟪50 日均線|50-day MA⟫</span>
        <span class="static"><i class="dash" style="border-top-color:var(--s-bot)"></i>⟪回調觀察觸發|Dip watch triggered⟫</span>
        <span class="static"><i class="dash" style="border-top-color:var(--a3)"></i>⟪短線過熱觸發|Overheating triggered⟫</span>
      </div>
    </div>
    <p class="muted small mid-note">⟪依 2026-10 的指標研究設計：48 個指標以 2014–2019 年觀察、2020–2026 年檢驗。單一過熱指標（RSI、均線乖離、貪婪等）之後平均仍續漲，組合過熱之後好壞參半，都不是可靠的賣訊號；牛市中的超賣組合有小幅優勢但次數少；
週線 Supertrend（ATR 10 × 3，以 Bitstamp 日 K 計算、只用已收完的週 K）約一年翻轉一次、很少來回，但屬確認型，翻空時通常已離高點數週。門檻採常見慣例值、未針對歷史最佳化。僅供參考，不構成投資建議。|
Built from an October 2026 indicator study: 48 indicators, observed on 2014–2019 and tested on 2020–2026. Single overheating readings (RSI, distance from moving averages, greed) were on average followed by further gains, and combined overheating had mixed outcomes — neither is a reliable sell signal; oversold combinations in bull markets showed a small edge but few occurrences.
The weekly Supertrend (ATR 10 × 3, from Bitstamp daily candles, completed weeks only) flips about once a year with few whipsaws, but it confirms rather than predicts — by the time it turns down, price is usually weeks past the high. Thresholds are conventional values, not fitted to history. For reference only — not investment advice.⟫</p>
  </div>"""


WHY = {"st_down": "⟪週線 ST 轉空|Weekly ST down⟫", "st_up": "⟪週線 ST 轉多|Weekly ST up⟫",
       "bsig": "⟪底部訊號 ≥ 50|Bottom signal ≥ 50⟫"}


def _x(v):
    return "—" if v is None else f"{v:,.1f}×" if v < 100 else f"{v:,.0f}×"


def _strategy(latest: dict) -> str:
    """週期策略頁：目前狀態、規則、模擬資金曲線、各起點績效、交易紀錄、限制。"""
    g = latest.get("strategy")
    if not g:
        return ""
    now, m = g["now"], latest.get("midterm", {}).get("supertrend_weekly") or {}
    hold = g["state"] == "holding"
    line = f'${m["line"]:,.0f}' if m.get("line") else "—"
    if hold and not g["armed"]:
        state, cls = "⟪持有中|Holding⟫", "hold"
        nxt = (f"⟪下一步：進入警戒（頂部訊號 ≥ 50 或頂部時機 ≥ 50）。依時鐘推算最早約 <b>{g.get('projected_arm') or '—'}</b>（假設本輪低點不再被跌破）。"
               f"進入警戒後，要等週線 Supertrend 轉空才賣出。|Next: enter alert (top signal ≥ 50 or top timing ≥ 50). By the cycle clocks the earliest is about "
               f"<b>{g.get('projected_arm') or '—'}</b> (assuming this cycle's low holds). Once on alert, it sells only when the weekly Supertrend turns down.⟫")
    elif hold:
        state, cls = "⟪持有中・警戒|Holding · on alert⟫", "alert"
        nxt = (f"⟪警戒中：週線 Supertrend 轉空就全部賣出。目前 Supertrend 支撐 {line}。|On alert: sells everything when the weekly Supertrend turns down. "
               f"Current Supertrend support: {line}.⟫")
    else:
        state, cls = "⟪空手|In cash⟫", "cash"
        nxt = (f"⟪等待買回：底部訊號 ≥ 50（目前 {now['bottom_signal']:.0f}），或週線 Supertrend 轉多（目前壓力 {line}）。|Waiting to buy back: bottom signal ≥ 50 "
               f"(now {now['bottom_signal']:.0f}) or the weekly Supertrend turning up (resistance {line}).⟫")
    st_txt = "⟪多方|Up⟫" if now["supertrend"] == "up" else "⟪空方|Down⟫"
    act = ("買進", "bought") if hold else ("賣出", "sold")
    since = (f"⟪自 {g['since']} 以 ${g['since_price']:,.0f} {act[0]}|{act[1]} on {g['since']} at ${g['since_price']:,.0f}⟫"
             if g.get("since") else "")
    status = f"""
    <div class="card st-card st-{cls}">
      <div class="eyebrow">STATUS · {g['as_of']}</div>
      <div class="st-big">{state}</div>
      <p class="st-since">{since}</p>
      <div class="st-grid">
        <div><span>⟪頂部訊號|Top signal⟫</span><b>{now['top_signal']:.0f}<small>/50</small></b></div>
        <div><span>⟪頂部時機|Top timing⟫</span><b>{now['top_timing']:.0f}<small>/50</small></b></div>
        <div><span>⟪底部訊號|Bottom signal⟫</span><b>{now['bottom_signal']:.0f}<small>/50</small></b></div>
        <div><span>⟪週線 Supertrend|Weekly Supertrend⟫</span><b class="{'up' if now['supertrend'] == 'up' else 'dn'}">{st_txt}</b></div>
      </div>
      <p class="st-next">{nxt}</p>
    </div>"""
    rules = """
    <div class="card st-rules">
      <div class="eyebrow">RULES</div><h3>⟪規則|Rules⟫</h3>
      <ol>
        <li><b>⟪警戒|Alert⟫</b>⟪持有中，頂部訊號 ≥ 50 或頂部時機 ≥ 50 → 進入警戒（保持到賣出）。|While holding, top signal ≥ 50 or top timing ≥ 50 → on alert (stays until a sale).⟫</li>
        <li><b>⟪賣出|Sell⟫</b>⟪警戒中，週線 Supertrend（ATR 10 × 3）由多轉空 → 全部賣出。|On alert, the weekly Supertrend (ATR 10 × 3) turns down → sell everything.⟫</li>
        <li><b>⟪買回|Buy back⟫</b>⟪空手時，底部訊號 ≥ 50 或週線 Supertrend 由空轉多 → 全部買回。|In cash, bottom signal ≥ 50 or the weekly Supertrend turns up → buy everything back.⟫</li>
      </ol>
      <p class="muted small">⟪頂部訊號與時機會提早亮，所以只用來「進入警戒」；真正賣出要等週線趨勢確認轉空。門檻固定為 50，未針對歷史最佳化；40／50／60 的 27 種組合回測都勝過持有。|The top signal and timing light up early, so they only put the strategy on alert; the actual sale waits for the weekly trend to confirm. Thresholds are fixed at 50, not fitted to history; all 27 combinations of 40/50/60 beat holding in backtests.⟫</p>
    </div>"""
    bt = g["backtest"]
    rows = "".join(
        f"<tr><td>{x['start']}</td><td><b>{_x(x['strategy'])}</b></td><td>{_x(x['hold'])}</td><td><b class='st-ratio'>{x['ratio']:.1f}×</b></td>"
        f"<td class='wd'>{_spct(x['cagr'], False)}</td><td class='wd'>{_spct(x['cagr_hold'], False)}</td><td>{_spct(x['max_dd'], False)}</td><td class='wd'>{_spct(x['max_dd_hold'], False)}</td></tr>"
        for x in g["by_start"])
    perf = f"""
    <div class="card">
      <div class="card-head"><div><div class="eyebrow">PERFORMANCE</div><h3>⟪各起點績效|Performance by start year⟫</h3></div></div>
      <div class="scroll"><table class="data fit"><thead><tr><th>⟪起點|Start⟫</th><th>⟪策略|Strategy⟫</th><th>⟪持有|Hold⟫</th><th>⟪策略／持有|Strat / hold⟫</th>
        <th class="wd">⟪策略年化|Strat CAGR⟫</th><th class="wd">⟪持有年化|Hold CAGR⟫</th><th>⟪策略最大回撤|Strat max DD⟫</th><th class="wd">⟪持有最大回撤|Hold max DD⟫</th></tr></thead><tbody>{rows}</tbody></table></div>
      <p class="muted small" style="margin:8px 0 0">⟪從各年 1 月 1 日起投入 1 單位，至今的資金倍數。手續費每次 0.1%，空手時現金不計利息。|Growth of 1 unit invested on January 1 of each year to today. 0.1% fee per trade; cash earns nothing.⟫</p>
    </div>"""
    trs = []
    for t in g["trades"]:
        chg = t.get("next_price_change")
        if t["action"] == "sell":
            note = ("—" if chg is None else
                    (f"⟪買回便宜 {_spct(-chg, False)}|rebought {_spct(-chg, False)} lower⟫" if chg < 0 else f"⟪買回貴 {_spct(chg, False)}|rebought {_spct(chg, False)} higher⟫"))
        else:
            pc = f"{chg * 100:+,.0f}%".replace("-", "−") if chg is not None else ""
            note = "⟪持有中|holding⟫" if chg is None else f"⟪持有 {pc}|held {pc}⟫"
        bad = t["action"] == "sell" and chg is not None and chg > 0
        trs.append(f"<tr class='{'bad' if bad else ''}'><td>{t['date']}<small>{WHY.get(t['why'], t['why'])}</small></td>"
                   f"<td><span class='act {t['action']}'>{'⟪賣出|Sell⟫' if t['action'] == 'sell' else '⟪買回|Buy⟫'}</span></td>"
                   f"<td>${t['price']:,.0f}</td><td>{note}</td></tr>")
    trades = f"""
    <div class="card">
      <div class="card-head"><div><div class="eyebrow">TRADES</div><h3>⟪歷史交易|Past trades⟫</h3></div></div>
      <div class="scroll"><table class="data fit st-trades"><thead><tr><th>⟪日期・原因|Date · trigger⟫</th><th>⟪動作|Action⟫</th><th>⟪價格|Price⟫</th><th>⟪結果|Outcome⟫</th></tr></thead>
      <tbody>{''.join(trs)}</tbody></table></div>
      <p class="muted small" style="margin:8px 0 0">⟪ST = Supertrend。紅底為賣錯的一次（2021-05 中段回調被誤判，買回時更貴）。|ST = Supertrend. The highlighted row is a bad sale (the 2021-05 mid-cycle dip was misread; it bought back higher).⟫</p>
    </div>"""
    limits = """
    <div class="card st-limits">
      <div class="eyebrow">LIMITATIONS</div><h3>⟪限制|Limitations⟫</h3>
      <ul>
        <li>⟪不是賣在頂部：要等趨勢確認，過去賣出時已從頂部跌了 26–65%。超額報酬主要來自避開熊市、在接近底部時買回。|It does not sell the top: it waits for trend confirmation, and past sales came 26–65% below the peak. The edge comes from sitting out bear markets and buying back near bottoms.⟫</li>
        <li>⟪會犯錯：2021-05 誤賣一次。持有期間仍可能經歷 −70% 等級的回撤。|It makes mistakes (a bad sale in 2021-05), and drawdowns of around −70% can still happen while holding.⟫</li>
        <li>⟪樣本少：只有 4 次熊市可驗證；若四年週期不再延續，策略可能失效。|Small sample: only four bear markets to test; if the four-year cycle breaks, the strategy may fail.⟫</li>
        <li>⟪逐輪回測：每一輪只用當時已發生的頂部與底部設定參數（不偷看未來）；最近一輪即網站目前的訊號。|Walk-forward: each cycle uses only the tops and bottoms known at the time (no look-ahead); the latest cycle uses the site's current signals.⟫</li>
        <li>⟪模擬結果，不代表實際交易；僅供參考，不構成投資建議。|Simulated results, not actual trading. For reference only — not investment advice.⟫</li>
      </ul>
    </div>"""
    return f"""
  <div class="view-head"><div class="sec-n">⟪週期策略|CYCLE STRATEGY⟫ · ⟪回測模擬|BACKTEST⟫</div><h2>⟪週期|Cycle⟫ <span>⟪策略|strategy⟫</span></h2>
    <p>⟪「警戒 + 趨勢確認」：用頂部／底部訊號判斷週期位置，用週線 Supertrend 確認趨勢。逐輪回測自 2014 年起 {_x(bt['strategy'])}，同期持有 {_x(bt['hold'])}。|“Alert + trend confirmation”: the top/bottom signals locate the cycle and the weekly Supertrend confirms the trend. Walk-forward backtest since 2014: {_x(bt['strategy'])} vs {_x(bt['hold'])} for holding.⟫</p></div>
  <div class="st-top">{status}{rules}</div>
  <div class="card st-chart">
    <div class="card-head"><div><div class="eyebrow">EQUITY</div><h3>⟪模擬資金曲線|Simulated equity⟫</h3></div>
      <div class="seg" data-g="strat"><button data-y="2014" class="on">2014</button><button data-y="2018">2018</button><button data-y="2022">2022</button></div></div>
    <div class="tip" id="tip-strat"></div>
    <svg class="chart" id="c-strat" height="380" role="img" aria-label="⟪策略與持有的資金曲線|Strategy vs hold equity⟫"></svg>
    <div class="legend">
      <span class="static"><i style="background:var(--strat)"></i>⟪策略|Strategy⟫</span>
      <span class="static"><i style="background:var(--price)"></i>⟪持續持有|Buy &amp; hold⟫</span>
      <span class="static"><i class="dash" style="border-top-color:var(--s-sig)"></i>⟪賣出|Sell⟫</span>
      <span class="static"><i class="dash" style="border-top-color:var(--s-bot)"></i>⟪買回|Buy⟫</span>
    </div>
    <p class="muted small" style="margin:8px 0 0">⟪對數刻度，起點 = 1。|Log scale; start = 1.⟫</p>
  </div>
  <div class="grid st-bottom">{perf}{trades}</div>
  {limits}"""


def _years_label(n: int) -> str:
    """歷史走勢標題用的年數（中文數字）。"""
    d = "零一二三四五六七八九"
    zh = (("十" if n < 20 else d[n // 10] + "十") + (d[n % 10] if n % 10 else "")) if n >= 10 else d[n]
    return f"⟪{zh}年的|{n} years of⟫"


def _hero(mode: str, latest: dict, ncat: int) -> str:
    """全屏首屏：液態大數字（瑞士）＋水位尺（潮汐）＋極光波浪。"""
    top = mode == "top"
    if top:
        v, t = latest["top_signal"], latest["timing"]
        wh = t["expected_window_by_halving"]
        title = "⟪頂部訊號|TOP SIGNAL⟫"
        level = LEVEL_TEXT[latest["signal_level"]]
        lede = (f"⟪熱度 × 時機。潮水要夠高、時間也要對，才會漲過警戒線。下一個頂部窗口|Heat × timing. The tide must be high and the "
                f"calendar right before it crosses the line. Next top window⟫ <b>{wh['full_from'][:7]} – {wh['full_to'][:7]}</b>")
        hz = _heat_zone(latest["heat_score"])
        kpis = [(f"{latest['heat_score']:.0f}", f"⟪熱度|Heat⟫ · {HEAT_TEXT[hz]}", "#heat"),
                (f"{latest['timing_score']:.0f}", "⟪時機|Timing⟫", "#timing"),
                (f"{latest['hot_categories']}<small>/{ncat}</small>", "⟪熱類別 ≥ 80|Hot ≥ 80⟫", "#heat")]
        marks = [("⟪熱度|Heat⟫", latest["heat_score"]), ("⟪時機|Timing⟫", latest["timing_score"])]
        thr = [(SIGNAL_WINDOW, "⟪頂部窗口|Top window⟫"), (SIGNAL_ALERT, "⟪高度警戒|High alert⟫")]
    else:
        b = latest["bottom"]
        v, ct = b["signal"], b["cycle_test"]
        title = "⟪底部訊號|BOTTOM SIGNAL⟫"
        level = BOTTOM_LEVEL_TEXT[b["level"]]
        lede = (f"⟪冷度 × 底部時機。本輪低點|Coldness × bottom timing. Is this cycle's low⟫ ${ct['current_low']['price']:,.0f} "
                f"⟪是否就是週期底部？判定日|the cycle bottom? Verdict on⟫ <b>{ct['decisive_date']}</b>")
        kpis = [(f"{b['cold_score']:.0f}", "⟪冷度|Coldness⟫", "#b/heat"),
                (f"{b['timing']['score']:.0f}", "⟪底部時機|Bottom timing⟫", "#b/timing"),
                (_n(ct["current_low"]["bottom_signal_max_cycle"]), "⟪本輪最高|Cycle peak⟫", "#b/overview")]
        marks = [("⟪冷度|Coldness⟫", b["cold_score"]), ("⟪底部時機|Bottom timing⟫", b["timing"]["score"])]
        thr = [(BOTTOM_WINDOW, "⟪底部區|Bottom zone⟫"), (BOTTOM_STRONG, "⟪強烈底部|Strong bottom⟫")]
    ticks = "".join(f'<i class="tk{" big" if x % 25 == 0 else ""}" style="bottom:{x}%"></i>'
                    + (f'<em style="bottom:{x}%">{x}</em>' if x % 25 == 0 else "") for x in range(0, 101, 5))
    thr_html = "".join(f'<div class="thr" style="bottom:{x}%"><span>{lbl} {x}</span></div>' for x, lbl in thr)
    pos = [min(max(val or 0, 0), 100) for _, val in marks]
    low = 0 if pos[0] <= pos[1] else 1  # 兩條刻度太近時，較低者的標籤放到線下方避免重疊
    mk_html = "".join(f'<div class="mk{" below" if i == low and abs(pos[0] - pos[1]) < 9 else ""}" style="bottom:{pos[i]:.1f}%"><span>{lbl}<b>{val or 0:.0f}</b></span></div>'
                      for i, (lbl, val) in enumerate(marks))
    kpi_html = "".join(f'<a class="kpi2" href="{href}"><b>{val}</b><span>{lbl}</span></a>' for val, lbl, href in kpis)
    num = f"{v:.0f}"
    pad = num.rjust(2, "0")
    lead = pad[:len(pad) - len(num)] if len(num) < 2 else ""
    return f"""
  <div class="hero2" data-hero="{mode}">
    <div class="h2-left">
      <div class="eyebrow2"><i class="live"></i>LIVE · {latest['date']} — {title}</div>
      <div class="giant" data-v="{v:.1f}" role="img" aria-label="{num}"><span class="z">{lead}</span><span class="v">{num}</span></div>
      <div class="statusline"><span class="pill2">{level}</span><p>{lede}</p></div>
      <div class="kpis2">{kpi_html}</div>
    </div>
    <div class="staff2" aria-hidden="true"><div class="rule"></div>{ticks}{thr_html}<div class="water" style="height:{max(v, 1.2):.1f}%"></div>{mk_html}</div>
    <svg class="waves2" viewBox="0 0 1440 300" preserveAspectRatio="none" data-lv="{v:.1f}" aria-hidden="true"></svg>
    <a class="scrollcue" href="#{'b/' if not top else ''}overview" data-scroll>SCROLL<span>↓</span></a>
  </div>"""



def _bottom_overview(latest: dict) -> str:
    """總覽（底部模式）：底部儀表 + 週期結構驗證 + 冷度組成摘要。"""
    b = latest["bottom"]
    ct, tm = b["cycle_test"], b["timing"]
    cur = ct["current_low"]
    days_left = (pd.Timestamp(ct["decisive_date"]) - pd.Timestamp(latest["date"])).days
    rows = "".join(
        f"<tr><td>{x['date'][:7]}</td><td>{x['days_since_top']}</td><td>{x['drawdown_pct']:.0f}%</td>"
        f"<td>{x['mvrv']:.2f}</td><td>{_n(x['bottom_signal_max_cycle'])}</td><td>{x['days_bottom_zone']}</td></tr>"
        for x in ct["past_bottoms"])
    rows += (f"<tr class='cur'><td>{cur['date'][:7]}<small>⟪本輪|This cycle⟫</small></td><td>{cur['days_since_top']}</td><td>{cur['drawdown_pct']:.0f}%</td>"
             f"<td>{cur['mvrv']:.2f}</td><td>{_n(cur['bottom_signal_max_cycle'])}</td><td>{cur['days_bottom_zone']}</td></tr>")
    grp_rows = "".join(
        f'<a class="crow" href="#b/heat/{GRP_KEY[g]}"><span class="crow-name">{_grp(g)}</span>'
        f'<span class="crow-bar"><i class="cool" style="width:{min(v["score"] or 0, 100):.0f}%"></i></span>'
        f'<span class="crow-sc cool-t">{_n(v["score"])}</span></a>'
        for g, v in b["groups"].items())
    lvl = b["level"]
    groups = _bigcats([(_grp(g), v["weight"], v["score"], f"#b/heat/{GRP_KEY[g]}", "cool", "")
                       for g, v in b["groups"].items()])
    return f"""
  <div class="sec reveal">
    <div class="sec-h"><div><div class="sec-n">COLDNESS BY GROUP</div><h2>⟪各組|Coldness by⟫<em>⟪冷度|group⟫</em></h2></div><a class="sec-link" href="#b/heat">⟪全部指標|All indicators⟫ →</a></div>
    {groups}
  </div>
  <div class="sec reveal">
    <div class="sec-h"><div><div class="sec-n">CYCLE STRUCTURE TEST</div><h2>⟪週期結構|Cycle structure⟫<em>⟪驗證|test⟫</em></h2></div><a class="sec-link" href="#b/timing">⟪底部時機|Bottom timing⟫ →</a></div>
      <div class="card verdict">
        <div class="card-head"><div><div class="eyebrow">CYCLE TEST</div></div><span class="status st-{ct['status']}">{STATUS_TEXT[ct['status']]}</span></div>
        <p class="q">⟪ETF 時代熊市是否變淺？本輪低點（|Are bear markets shallower in the ETF era? Is this cycle's low (⟫{cur['date']}, ${cur['price']:,.0f}⟪）是否就是週期底部？|) the cycle bottom?⟫</p>
        <div class="countdown"><div><b>{max(days_left, 0)}</b><span>⟪天後判定|days to verdict⟫</span></div><div><b>{ct['decisive_date']}</b><span>⟪底部窗口結束|bottom window ends⟫</span></div><div><b>{ct['days_mvrv_below_1_this_cycle']}</b><span>⟪MVRV&lt;1 天數|days MVRV&lt;1⟫</span></div></div>
        <p class="small">{_verdict(ct)}</p>
        <table class="data fit"><thead><tr><th>⟪底部|Bottom⟫</th><th>⟪距頂|From top⟫</th><th>⟪跌幅|Drop⟫</th><th>MVRV</th><th>⟪最高|Peak⟫</th><th>≥{BOTTOM_WINDOW} ⟪天|days⟫</th></tr></thead><tbody>{rows}</tbody></table>
        <p class="muted small" style="margin:6px 0 0">⟪距頂：距前次頂部天數；最高：該輪底部訊號最高分；≥{BOTTOM_WINDOW} 天：底部訊號達 {BOTTOM_WINDOW} 以上的天數。|From top: days since the previous top; Peak: highest bottom signal that cycle; ≥{BOTTOM_WINDOW} days: days with bottom signal at or above {BOTTOM_WINDOW}.⟫</p>
      </div>
  </div>"""

def _bottom_timing(latest: dict) -> str:
    """時機頁（底部模式）：距上次頂部、距上次減半兩個時鐘，標出過去底部。"""
    tm = latest["bottom"]["timing"]
    wt, wh = tm["window_by_top"], tm["window_by_halving"]
    past_rows = "".join(f"<tr><td>{d[:7]}</td><td>{tm['past_bottoms_top_days'][d]}</td><td>{tm['past_bottoms_halving_days'][d]}</td></tr>"
                        for d in tm["past_bottoms_top_days"])
    return f"""
<div class="card">
  <div class="card-head"><div><div class="eyebrow">⟪時鐘一|CLOCK 1⟫</div><h3>⟪距上次頂部|Days since last top⟫</h3></div>
    <div class="kpi"><span class="kpi-v">{tm['score_top']:.0f}</span><span class="kpi-l">⟪分|pts⟫</span></div></div>
  <div class="facts"><div><span>⟪現在|Now⟫</span><b>{tm['days_since_top']} ⟪天|d⟫</b></div><div><span>⟪上次頂部|Last top⟫</span><b>{tm['last_top']}</b></div>
    <div><span>⟪過去底部平均|Past bottoms avg⟫</span><b>{tm['center_top_days']} ⟪天|d⟫</b></div></div>
  {_clock(tm['days_since_top'], tm['center_top_days'], tm['flat_days'], tm['ramp_days'], tm['past_bottoms_top_days'], f"⟪現在|Now⟫ {tm['days_since_top']}", "bot")}
  <p class="muted small">⟪依|From the⟫ {tm['last_top']} ⟪頂部推算，滿分窗口|top: full-score window⟫ <b>{wt['full_from']} ～ {wt['full_to']}</b>⟪，有分數的範圍|; scoring range⟫ {wt['from']} ～ {wt['to']}.</p>
</div>
<div class="card">
  <div class="card-head"><div><div class="eyebrow">⟪時鐘二|CLOCK 2⟫</div><h3>⟪距上次減半|Days since last halving⟫</h3></div>
    <div class="kpi"><span class="kpi-v">{tm['score_halving']:.0f}</span><span class="kpi-l">⟪分|pts⟫</span></div></div>
  <div class="facts"><div><span>⟪現在|Now⟫</span><b>{tm['days_since_halving']} ⟪天|d⟫</b></div><div><span>⟪上次減半|Last halving⟫</span><b>{tm['last_halving']}</b></div>
    <div><span>⟪過去底部平均|Past bottoms avg⟫</span><b>{tm['center_halving_days']} ⟪天|d⟫</b></div></div>
  {_clock(tm['days_since_halving'], tm['center_halving_days'], tm['flat_days'], tm['ramp_days'], tm['past_bottoms_halving_days'], f"⟪現在|Now⟫ {tm['days_since_halving']}", "bot")}
  <p class="muted small">⟪依|From the⟫ {tm['last_halving']} ⟪減半推算，滿分窗口|halving: full-score window⟫ <b>{wh['full_from']} ～ {wh['full_to']}</b>⟪，有分數的範圍|; scoring range⟫ {wh['from']} ～ {wh['to']}.</p>
</div>
<div class="card">
  <div class="card-head"><div><div class="eyebrow">⟪參考|REFERENCE⟫</div><h3>⟪過去底部的天數|Day counts at past bottoms⟫</h3></div></div>
  <table class="data compact"><thead><tr><th>⟪底部|Bottom⟫</th><th>⟪距前次頂部|Since prior top⟫</th><th>⟪距減半|Since halving⟫</th></tr></thead><tbody>{past_rows}</tbody></table>
  <p class="muted small">⟪窗口中心取過去三次底部（2015、2018、2022）的平均；中心前後 {tm['flat_days']} 天內滿分，再往外 {tm['ramp_days']} 天線性降到 0。
  中段急跌（2019-12、2020-03、2021-07、2024-08）的時機皆為 0，因此未觸發底部訊號。|Window centers are the average of the three past bottoms (2015, 2018, 2022); full score within ±{tm['flat_days']} days, then linearly down to 0 over another {tm['ramp_days']} days.
  Mid-cycle crashes (2019-12, 2020-03, 2021-07, 2024-08) all had timing 0, so the bottom signal did not trigger.⟫</p>
</div>"""


def _bottom_cold(latest: dict, ind_meta: dict) -> str:
    """冷度頁（底部模式）：估值、礦工、價格結構三組，指標卡片可點開看歷史。"""
    b = latest["bottom"]
    out = []
    for grp, g in b["groups"].items():
        cards = []
        for k, i in b["indicators"].items():
            if i["group"] != grp:
                continue
            sc = i["score"]
            meth = (f"⟪本輪預期底部|Expected bottom this cycle⟫ {_fmt(i['expected_bottom'])} · ⟪中性|neutral⟫ {_fmt(i['neutral'])}" if i.get("method") == "cycle_bottom"
                    else f"⟪近 90 日最深投降；{i.get('full_at')}% 為滿分|Deepest capitulation in 90 days; {i.get('full_at')}% = full score⟫")
            ind_meta[k] = {"label": _lab(k, i["label"]), "cat": "⟪冷度|Coldness⟫ · " + _grp(grp), "unit": _unit(i.get("unit", "")), "desc": _desc(k, i["description"]),
                           "method": meth + "⟪。冷度 100 = 達到本輪預期底部，0 = 中性以上。|. Coldness 100 = at this cycle's expected bottom; 0 = neutral or above.⟫",
                           "value": _fmt(i["value"], i["unit"]), "score": None if sc is None else round(sc),
                           "band": "cool-t", "asOf": latest["price_date"], "stale": False, "hasScore": sc is not None}
            cards.append(
                f'<button class="ind" data-k="{k}" aria-label="{_lab(k, i["label"])} ⟪詳情|details⟫">'
                f'<span class="ind-top"><span class="ind-name">{_lab(k, i["label"])}</span></span>'
                f'<span class="ind-mid"><span class="ind-val">{_fmt(i["value"], i["unit"])}</span>'
                f'<span class="ind-sc cool-t">{_n(sc)}</span></span>'
                f'<span class="mbar"><i class="cool" style="width:{min(sc or 0, 100):.0f}%"></i></span>'
                f'<span class="ind-foot">{"⟪週期底部法|Cycle-bottom method⟫" if i.get("method") == "cycle_bottom" else "⟪投降深度|Capitulation depth⟫"}<span class="more">⟪詳情|Details⟫ ›</span></span></button>')
        out.append(f"""
<details class="cat" id="grp-{GRP_KEY[grp]}" open>
  <summary>
    <span class="cat-top"><span class="cat-name">{_grp(grp)}</span><span class="cat-w">⟪權重|Weight⟫ {g['weight']*100:.0f}%</span>
      <span class="cat-sc cool-t">{_n(g['score'])}</span><span class="chev" aria-hidden="true"></span></span>
    <span class="bar"><i class="cool" style="width:{min(g['score'] or 0, 100):.0f}%"></i></span>
  </summary>
  <div class="ind-grid">{''.join(cards)}</div>
</details>""")
    return "".join(out)


def _bottom_table(hist: pd.DataFrame, latest: dict) -> str:
    groups = list(latest["bottom"]["groups"])
    h = hist.dropna(subset=["price"]).tail(30).iloc[::-1]
    head = "".join(f"<th>{_grp(g)}</th>" for g in groups)
    keys = {"估值": "valuation", "礦工": "miners", "價格結構": "price"}
    rows = []
    for d, r in h.iterrows():
        cells = "".join(f"<td>{_n(r.get('coldgrp_' + keys[g]))}</td>" for g in groups)
        rows.append(f"<tr><td>{d:%m-%d}</td><td>{r['price']:,.0f}</td><td class='b'>{_n(r['bottom_signal'])}</td>"
                    f"<td>{_n(r['cold'])}</td><td>{_n(r['bottom_timing'])}</td>{cells}</tr>")
    return (f"<table class='data'><thead><tr><th>⟪日期|Date⟫</th><th>⟪價格|Price⟫</th><th>⟪底部訊號|Bottom signal⟫</th><th>⟪冷度|Coldness⟫</th><th>⟪底部時機|Bottom timing⟫</th>"
            f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>")


GRP_KEY = {"估值": "valuation", "礦工": "miners", "價格結構": "price"}


def _recent_table(hist: pd.DataFrame, cats: dict) -> str:
    h = hist.dropna(subset=["price"]).tail(30).iloc[::-1]
    head = "".join(f"<th>{CAT_SHORT.get(k, c['label'])}</th>" for k, c in cats.items())
    rows = []
    for d, r in h.iterrows():
        cells = "".join(f"<td>{_n(r.get('cat_' + k))}</td>" for k in cats)
        rows.append(f"<tr><td>{d:%m-%d}</td><td>{r['price']:,.0f}</td><td class='b'>{_n(r['top_signal'])}</td>"
                    f"<td>{_n(r['heat'])}</td><td>{_n(r['timing'])}</td>{cells}</tr>")
    return (f"<table class='data'><thead><tr><th>⟪日期|Date⟫</th><th>⟪價格|Price⟫</th><th>⟪訊號|Signal⟫</th><th>⟪熱度|Heat⟫</th><th>⟪時機|Timing⟫</th>"
            f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>")


def render_page(latest: dict, hist: pd.DataFrame, ind: pd.DataFrame, path: Path,
                defs: dict = INDICATORS, lang: str = "zh"):
    """lang="zh" 輸出中文版；lang="en" 輸出英文版（放在 docs/en/，連結需多退一層）。"""
    global _LANG
    _LANG = lang
    up = "../" if lang == "en" else ""
    t = latest["timing"]
    sig, lvl, heat, tim = latest["top_signal"], latest["signal_level"], latest["heat_score"], latest["timing_score"]
    shown = {k: c for k, c in latest["categories"].items() if c["status"] != "unavailable"}  # 無資料的類別不顯示

    # ---- 總覽：類別列表 ----
    cat_rows = "".join(
        f'<a class="crow" href="#heat/{k}"><span class="crow-name">{_cat(k, c["label"])}</span>'
        f'<span class="crow-bar"><i class="{_band(c["score"])}" style="width:{min(c["score"] or 0, 100):.0f}%"></i><em></em></span>'
        f'<span class="crow-sc {_band(c["score"])}">{_n(c["score"])}</span></a>'
        for k, c in shown.items())

    # ---- 熱度頁：類別手風琴 + 指標卡片 ----
    ind_meta = {}
    cats_html = []
    for key, c in shown.items():
        cards, missing = [], []
        for k, i in c["indicators"].items():
            if i["status"] != "ok":
                missing.append(_reason(k, i.get("reason", i["label"])))
                continue
            sc = i["score"]
            b = _band(sc)
            ind_meta[k] = {"label": _lab(k, i["label"]), "cat": _cat(key, c["label"]), "unit": _unit(i.get("unit", "")),
                           "desc": _desc(k, i.get("description", "")), "method": _method(i), "value": _fmt(i["value"], _unit(i["unit"])),
                           "score": None if sc is None else round(sc), "band": b, "asOf": i["as_of"],
                           "stale": i["stale"], "hasScore": sc is not None}
            stale = '<span class="pill warn">⟪舊資料|Stale⟫</span>' if i["stale"] else ""
            cards.append(
                f'<button class="ind" data-k="{k}" aria-label="{_lab(k, i["label"])} ⟪詳情|details⟫">'
                f'<span class="ind-top"><span class="ind-name">{_lab(k, i["label"])}</span>{stale}</span>'
                f'<span class="ind-mid"><span class="ind-val">{_fmt(i["value"], _unit(i["unit"]))}</span>'
                f'<span class="ind-sc {b}">{"—" if sc is None else f"{sc:.0f}"}</span></span>'
                f'<span class="mbar"><i class="{b}" style="width:{min(sc or 0, 100):.0f}%"></i></span>'
                f'<span class="ind-foot">{_method_short(i)} · {i["as_of"]}<span class="more">⟪詳情|Details⟫ ›</span></span></button>')
        eff = c["effective_weight"]
        wtxt = f'⟪權重|Weight⟫ {c["weight"]*100:.0f}%' + (f' · ⟪實際|effective⟫ {eff*100:.0f}%' if eff and abs(eff - c["weight"]) > .005 else "")
        sc = c["score"]
        na = f'<p class="muted small na">⟪無免費資料：|No free data: ⟫{"⟪、|; ⟫".join(missing)}</p>' if missing else ""
        cats_html.append(f"""
<details class="cat" id="cat-{key}" open>
  <summary>
    <span class="cat-top"><span class="cat-name">{_cat(key, c['label'])}</span><span class="cat-w">{wtxt}</span>
      <span class="cat-sc {_band(sc)}">{_n(sc)}</span><span class="chev" aria-hidden="true"></span></span>
    <span class="bar"><i class="{_band(sc)}" style="width:{min(sc or 0, 100):.0f}%"></i><em></em></span>
  </summary>
  <div class="ind-grid">{''.join(cards)}</div>{na}
</details>""")

    # ---- 時機頁 ----
    wh, wl = t["expected_window_by_halving"], t["expected_window_by_low"]
    past_rows = "".join(f"<tr><td>{d[:7]}</td><td>{t['past_tops_halving_days'][d]}</td><td>{t['past_tops_low_days'][d]}</td></tr>"
                        for d in t["past_tops_halving_days"])
    halving_note = f"⟪依|From the⟫ {t['window_halving']}{'⟪（估計）| (est.)⟫' if t['window_halving'] == t['next_halving'] else ''} ⟪減半推算|halving⟫"
    timing_html = f"""
<div class="card">
  <div class="card-head"><div><div class="eyebrow">⟪時鐘一|CLOCK 1⟫</div><h3>⟪距最近一次減半|Days since last halving⟫</h3></div>
    <div class="kpi"><span class="kpi-v {_band(t['score_halving'])}">{t['score_halving']:.0f}</span><span class="kpi-l">⟪分|pts⟫</span></div></div>
  <div class="facts"><div><span>⟪現在|Now⟫</span><b>{t['days_since_halving']} ⟪天|d⟫</b></div><div><span>⟪上次減半|Last halving⟫</span><b>{t['last_halving']}</b></div>
    <div><span>⟪過去頂部平均|Past tops avg⟫</span><b>{t['center_halving_days']} ⟪天|d⟫</b></div></div>
  {_clock(t['days_since_halving'], t['center_halving_days'], t['flat_days'], t['ramp_days'], t['past_tops_halving_days'], f"⟪現在|Now⟫ {t['days_since_halving']}")}
  <p class="muted small">{halving_note}⟪，滿分窗口|: full-score window⟫ <b>{wh['full_from']} ～ {wh['full_to']}</b>⟪，有分數的範圍|; scoring range⟫ {wh['from']} ～ {wh['to']}.</p>
</div>
<div class="card">
  <div class="card-head"><div><div class="eyebrow">⟪時鐘二|CLOCK 2⟫</div><h3>⟪距本輪週期低點|Days since cycle low⟫</h3></div>
    <div class="kpi"><span class="kpi-v {_band(t['score_low'])}">{t['score_low']:.0f}</span><span class="kpi-l">⟪分|pts⟫</span></div></div>
  <div class="facts"><div><span>⟪現在|Now⟫</span><b>{t['days_since_low']} ⟪天|d⟫</b></div><div><span>⟪本輪低點|Cycle low⟫</span><b>{t['cycle_low_date']}</b></div>
    <div><span>⟪過去頂部平均|Past tops avg⟫</span><b>{t['center_low_days']} ⟪天|d⟫</b></div></div>
  {_clock(t['days_since_low'], t['center_low_days'], t['flat_days'], t['ramp_days'], t['past_tops_low_days'], f"⟪現在|Now⟫ {t['days_since_low']}")}
  <p class="muted small">⟪依目前低點（|From the current low (⟫${t['cycle_low_price']:,.0f}⟪）推算，滿分窗口|): full-score window⟫ <b>{wl['full_from']} ～ {wl['full_to']}</b>⟪。若價格再創本輪新低，低點與窗口會跟著往後移。|. A new cycle low would shift the low and the window later.⟫</p>
</div>
<div class="card">
  <div class="card-head"><div><div class="eyebrow">⟪參考|REFERENCE⟫</div><h3>⟪過去頂部的天數|Day counts at past tops⟫</h3></div></div>
  <table class="data compact"><thead><tr><th>⟪頂部|Top⟫</th><th>⟪距減半|Since halving⟫</th><th>⟪距週期低點|Since cycle low⟫</th></tr></thead><tbody>{past_rows}</tbody></table>
  <p class="muted small">⟪窗口中心取最近三次（2017、2021、2025）的平均；中心前後 {t['flat_days']} 天內滿分，再往外 {t['ramp_days']} 天線性降到 0。2013 年那一輪較短，不在平均內。|Window centers are the average of the last three tops (2017, 2021, 2025); full score within ±{t['flat_days']} days, then linearly down to 0 over another {t['ramp_days']} days. The shorter 2013 cycle is excluded.⟫</p>
</div>"""

    stale_banner = ('<div class="banner warn">⟪部分資料源今日抓取失敗，沿用前一次數值（指標標示「舊資料」）。|Some sources failed today; previous values are used (marked "Stale").⟫</div>'
                    if latest["stale"] else "")
    hz = _heat_zone(heat)
    rep = {
        "__TITLE__": f"{BRAND} · {BRAND_ZH}",
        "__BRAND__": BRAND,
        "__BRAND_ZH__": BRAND_ZH,
        "__LOGO__": LOGO_SVG.replace('<stop offset="0" stop-color="#e0525d"/><stop offset="1" stop-color="#22a57f"/>',
                                     '<stop offset="0" style="stop-color:var(--a1)"/><stop offset="1" style="stop-color:var(--a2)"/>')
                            .replace('x1="0" y1="0" x2="0" y2="1"', 'x1="0" y1="0" x2="1" y2="1"'),
        "__FAVICON__": FAVICON,
        "__BADGE__": "",
        "__DATE__": latest["date"],
        "__PRICE__": f'{latest["price_usd"]:,.0f}',
        "__PRICE_DATE__": latest["price_date"],
        "__BANNERS__": stale_banner,
        "__SIG__": f"{sig:.0f}",
        "__LVL__": lvl,
        "__LVL_TEXT__": LEVEL_TEXT[lvl],
        "__G_SIG__": _gauge(sig, 220, 16, "--lv-" + lvl if lvl != "none" else "--top-c", (SIGNAL_WINDOW, SIGNAL_ALERT)),
        "__G_HEAT__": _gauge(heat, 96, 9, "--" + _band(heat)),
        "__G_TIM__": _gauge(tim, 96, 9, "--accent"),
        "__HEAT__": f"{heat:.0f}",
        "__HEAT_BAND__": _band(heat),
        "__HEAT_TEXT__": HEAT_TEXT[hz],
        "__TIM__": f"{tim:.0f}",
        "__HOT__": str(latest["hot_categories"]),
        "__NCAT__": str(len(shown)),
        "__NCAT_TEXT__": "⟪" + "一二三四五"[len(shown) - 1] + "類|" + str(len(shown)) + " categories⟫",
        "__CATLIST__": "⟪、|, ⟫".join(_cat(k, c["label"]) for k, c in shown.items()),
        "__CAT_ROWS__": cat_rows,
        "__TIMELINE__": _cycle_timeline(latest),
        "__HERO_TOP__": _hero("top", latest, len(shown)),
        "__HERO_BOTTOM__": _hero("bottom", latest, 0),
        "__MIDTERM__": _midterm(latest),
        "__STRATEGY__": _strategy(latest),
        "__STRAT_TRADES__": json.dumps({**{k: [t["date"] for t in latest.get("strategy", {}).get("trades", []) if t["action"] == k] for k in ("sell", "buy")},
                                        # 各起點 1 月 1 日的精確基準（圖表資料一年前為每週一點）
                                        "base": {y: [float(hist.loc[f"{y}-01-01", "strat_eq"]), float(hist.loc[f"{y}-01-01", "strat_bh"])]
                                                 for y in ("2014", "2018", "2022")} if "strat_eq" in hist else {}}),
        "__MID_EVENTS__": json.dumps({k: [str(d.date()) for d in _mid_events(hist["mid_" + k + "_signal"] > 0)]
                                      for k in ("dip", "hot")} if "mid_dip_signal" in hist else {"dip": [], "hot": []}),
        "__BIGCATS__": _bigcats([(_cat(k, c["label"]), c["effective_weight"], c["score"], f"#heat/{k}", _band(c["score"]), BAND_TEXT[_band(c["score"])])
                                 for k, c in shown.items()]),
        "__YEARS__": _years_label(hist.index[-1].year - hist.index[0].year),
        "__Y0__": str(hist.index[0].year),
        "__Y1__": str(hist.index[-1].year),
        "__SIG2__": f"{sig:.0f}",
        "__BSIG2__": f'{latest["bottom_signal"]:.0f}',
        "__TICKER__": _ticker(latest),
        "__FONT_BASE__": up + "fonts/",
        "__BOTTOM_OVERVIEW__": _bottom_overview(latest),
        "__BTIMING__": _bottom_timing(latest),
        "__COLD__": _bottom_cold(latest, ind_meta),
        "__BTABLE__": _bottom_table(hist, latest),
        "__COLD_SCORE__": f'{latest["cold_score"]:.0f}',
        "__BTIM__": f'{latest["bottom_timing_score"]:.0f}',
        "__BWIN__": str(BOTTOM_WINDOW),
        "__CATS__": "".join(cats_html),
        "__TIMING__": timing_html,
        "__TABLE__": _recent_table(hist, shown),
        "__WIN__": str(SIGNAL_WINDOW),
        "__ALERT__": str(SIGNAL_ALERT),
        "__PIVOT__": str(PCT_PIVOT),
        "__CENTER_H__": str(t["center_halving_days"]),
        "__CENTER_L__": str(t["center_low_days"]),
        "__CSV_SCORES__": REPO + "/blob/main/data/scores.csv",
        "__CSV_IND__": REPO + "/blob/main/data/indicators.csv",
        "__CSV_RAW__": REPO + "/tree/main/data/raw",
        "__JSON_HREF__": up + "latest.json",
        "__LANG_HREF__": "../index.html" if lang == "en" else "en/index.html",
        "__LANG_LABEL__": "中" if lang == "en" else "EN",
        "__LANG_TITLE__": "切換為中文" if lang == "en" else "Switch to English",
        "__EXTRA_SRC__": "",
        "__REPO__": REPO,
        "__GENERATED__": latest["generated_at"],
        "__TOPS__": json.dumps(latest["cycle_tops"]),
        "__BOTTOMS__": json.dumps(latest["cycle_bottoms"]),
        "__CUR_LOW__": json.dumps(latest["bottom"]["cycle_test"]["current_low"]["date"]),
        "__DATA__": json.dumps(_series(hist, ind, defs), separators=(",", ":")),
    }
    rep["__IND__"] = json.dumps(ind_meta, ensure_ascii=False, separators=(",", ":"))
    page = _pick(TEMPLATE)  # 先挑語言再填值，避免雙語標記巢狀
    for k, v in rep.items():
        page = page.replace(k, _pick(v))
    if lang == "en":
        page = page.replace("\u3000", " ")  # 英文版不用全形空格
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")


ICONS = {
    "overview": '<path d="M4 15a8 8 0 1 1 16 0"/><path d="M12 15l4-5"/>',
    "timing": '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
    "heat": '<path d="M12 3c1 3 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 1-9z"/>',
    "chart": '<path d="M4 19h16"/><path d="M5 15l4-4 3 3 6-7"/>',
    "data": '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 10h16M10 10v9"/>',
    "mid": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "strat": '<path d="M4 19V5"/><path d="M4 19h16"/><path d="M7 15l4-4 3 2 5-6"/><circle cx="19" cy="7" r="1.6"/>',
}
TABS = [("overview", "⟪總覽|Overview⟫"), ("timing", "⟪時機|Timing⟫"), ("heat", "⟪熱度|Heat⟫"), ("data", "⟪數據|Data⟫")]
ICONS["cold"] = '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.5 4.5L12 7l2.5-2.5M9.5 19.5L12 17l2.5 2.5"/>'


def _tab(k, v):
    if k == "heat":  # 頂部模式「熱度」、底部模式「冷度」
        icon = (f'<svg class="tb-top" viewBox="0 0 24 24" aria-hidden="true">{ICONS["heat"]}</svg>'
                f'<svg class="tb-bot" viewBox="0 0 24 24" aria-hidden="true">{ICONS["cold"]}</svg>')
        return f'<a class="tab" href="#{k}" data-tab="{k}">{icon}<span class="tb-top">⟪熱度|Heat⟫</span><span class="tb-bot">⟪冷度|Cold⟫</span></a>'
    return f'<a class="tab" href="#{k}" data-tab="{k}"><svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[k]}</svg><span>{v}</span></a>'


# 中期狀態不屬於頂部／底部：放在最後、以分隔線隔開，用不編號的獨立按鈕樣式
TAB_HTML = ("".join(_tab(k, v) for k, v in TABS) + '<span class="tab-sep" aria-hidden="true"></span>'
            + f'<a class="tab tab-mid" href="#mid" data-tab="mid" title="⟪中期狀態|Market state⟫"><svg viewBox="0 0 24 24" aria-hidden="true">{ICONS["mid"]}</svg>'
              '<span>⟪中期狀態|Market⟫</span></a>'
            + f'<a class="tab tab-mid tab-strat" href="#strat" data-tab="strat" title="⟪週期策略|Cycle strategy⟫"><svg viewBox="0 0 24 24" aria-hidden="true">{ICONS["strat"]}</svg>'
              '<span>⟪週期策略|Strategy⟫</span></a>')

TEMPLATE = r"""<!doctype html>
<html lang="⟪zh-Hant|en⟫">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__TITLE__</title>
<link rel="icon" href="__FAVICON__">
<meta name="description" content="⟪每日更新的比特幣週期訊號：頂部訊號（熱度 × 時機）與底部訊號（冷度 × 底部時機）。|Daily bitcoin cycle signals: a top signal (heat × timing) and a bottom signal (coldness × bottom timing).⟫">
<script>/* 預設深色；使用者選過（dark／light／auto）就沿用 */
var THEME0='dark';try{var t=localStorage.getItem('theme');if(t==='light'||t==='dark'||t==='auto')THEME0=t;}catch(e){}
if(THEME0!=='auto')document.documentElement.dataset.theme=THEME0;
try{var L=localStorage.getItem('lang'),here='⟪zh|en⟫';
  if(!L){L=/^zh/i.test(navigator.language||'')?'zh':'en';}
  if(L!==here&&!/[?&]nolang/.test(location.search))location.replace((here==='zh'?'en/':'../')+(location.protocol==='file:'?'index.html':'')+location.hash);}catch(e){}</script>
<meta name="theme-color" content="#0b0d10" id="theme-color">
<style>
:root{color-scheme:light;--bg:#f3f4f6;--surface:#fff;--surface2:#f7f8fa;--line:rgba(15,23,42,.08);--line2:rgba(15,23,42,.14);
--fg:#0f172a;--mut:#5b6474;--faint:#8b93a1;--top-c:#d93f4c;--top-c2:#a8263a;--bot-c:#1f9a78;--bot-c2:#137057;--accent:var(--top-c);--accent-soft:color-mix(in srgb,var(--accent) 12%,transparent);
--cold:#3b82f6;--warm:#c98a0b;--hot:#ea6a2a;--top:#dc3545;--na:#a0a7b3;
--lv-window:#c98a0b;--lv-alert:#dc3545;--price:#475569;--s-sig:var(--top-c);--s-heat:#c8941c;--s-tim:#94a3b8;--glow2:#6d5ce8;--topline:#7c5cd6;--s-bot:var(--bot-c);--s-cold:#3a8fc9;--botline:#c026d3;
--shadow:0 1px 2px rgba(15,23,42,.04),0 12px 32px rgba(15,23,42,.07);--hl:rgba(255,255,255,.7);--r:18px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0b0d10;--surface:#13161b;--surface2:#191d23;
--line:rgba(255,255,255,.07);--line2:rgba(255,255,255,.13);--fg:#eef1f5;--mut:#9aa3af;--faint:#6b7480;
--top-c:#f0616a;--top-c2:#c23a4b;--bot-c:#34c294;--bot-c2:#1d8f6c;--accent:var(--top-c);--accent-soft:color-mix(in srgb,var(--accent) 16%,transparent);--cold:#5b9cff;--warm:#e3a92b;--hot:#f2834a;--top:#f2555a;--na:#4b5360;
--lv-window:#e3a92b;--lv-alert:#f2555a;--price:#aeb6c2;--s-sig:var(--top-c);--s-heat:#e2b44a;--s-tim:#6b7480;--glow2:#7c6cff;--topline:#a48bff;--s-bot:var(--bot-c);--s-cold:#5cb3e8;--botline:#e879f9;
--shadow:0 10px 30px rgba(0,0,0,.35);--hl:rgba(255,255,255,.06)}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0b0d10;--surface:#13161b;--surface2:#191d23;
--line:rgba(255,255,255,.07);--line2:rgba(255,255,255,.13);--fg:#eef1f5;--mut:#9aa3af;--faint:#6b7480;
--top-c:#f0616a;--top-c2:#c23a4b;--bot-c:#34c294;--bot-c2:#1d8f6c;--accent:var(--top-c);--accent-soft:color-mix(in srgb,var(--accent) 16%,transparent);--cold:#5b9cff;--warm:#e3a92b;--hot:#f2834a;--top:#f2555a;--na:#4b5360;
--lv-window:#e3a92b;--lv-alert:#f2555a;--price:#aeb6c2;--s-sig:var(--top-c);--s-heat:#e2b44a;--s-tim:#6b7480;--glow2:#7c6cff;--topline:#a48bff;--s-bot:var(--bot-c);--s-cold:#5cb3e8;--botline:#e879f9;
--shadow:0 10px 30px rgba(0,0,0,.35);--hl:rgba(255,255,255,.06)}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body::before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;
background:radial-gradient(900px 520px at 10% 4%,color-mix(in srgb,var(--accent) 26%,transparent),transparent 65%),
radial-gradient(800px 500px at 100% 12%,color-mix(in srgb,var(--glow2) 18%,transparent),transparent 62%),
radial-gradient(1200px 700px at 50% 115%,color-mix(in srgb,var(--accent) 7%,transparent),transparent 60%);transition:background .6s ease}
body::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
background-image:radial-gradient(color-mix(in srgb,var(--fg) 9%,transparent) 1px,transparent 1.2px);background-size:22px 22px;
-webkit-mask-image:linear-gradient(to bottom,#000 0,rgba(0,0,0,.55) 35%,transparent 75%);mask-image:linear-gradient(to bottom,#000 0,rgba(0,0,0,.55) 35%,transparent 75%)}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang TC","Noto Sans TC","Microsoft JhengHei",sans-serif;
-webkit-font-smoothing:antialiased;padding-bottom:calc(76px + env(safe-area-inset-bottom))}
a{color:inherit}
.num,.kpi-v,.hero-num,.crow-sc,.cat-sc,.ind-val,.ind-sc,table.data{font-variant-numeric:tabular-nums}
.muted{color:var(--mut)}.small{font-size:12.5px}
.wrap{max-width:1080px;margin:0 auto;padding:0 16px}
/* 頂部 */
.appbar{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 55%,transparent);backdrop-filter:saturate(1.4) blur(14px);-webkit-backdrop-filter:saturate(1.4) blur(14px);border-bottom:1px solid var(--line)}
.appbar-in{display:flex;align-items:center;gap:12px;height:58px}
.brand{flex:1;min-width:0;display:flex;align-items:center;gap:10px;text-decoration:none}
.logo{width:32px;height:32px;flex:none;border-radius:9px;box-shadow:0 4px 14px rgba(0,0,0,.18),inset 0 0 0 1px rgba(255,255,255,.12)}
.brand-txt{min-width:0}
.brand h1{font-size:17px;margin:0;display:flex;align-items:center;gap:8px;line-height:1.15}
.wordmark{font-family:"SF Pro Display",-apple-system,BlinkMacSystemFont,"Inter","Helvetica Neue",sans-serif;font-weight:700;letter-spacing:-.02em;
background:linear-gradient(90deg,var(--fg) 40%,color-mix(in srgb,var(--accent) 70%,var(--fg)));-webkit-background-clip:text;background-clip:text;color:transparent}
.brand .sub{font-size:11.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:.2px}
.badge{font-size:11px;font-weight:600;color:var(--accent);background:var(--accent-soft);border-radius:999px;padding:1px 8px}
.appbar-in .iconbtn+.iconbtn{margin-left:-4px}
.iconbtn svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.iconbtn.lang{font-size:12.5px;font-weight:700;text-decoration:none;letter-spacing:.3px}
.iconbtn{width:36px;height:36px;border-radius:12px;border:1px solid var(--line2);background:var(--surface);color:var(--fg);font:600 15px/1 inherit;cursor:pointer;display:grid;place-items:center}
.tabs{display:flex;gap:4px}
.tab{display:flex;align-items:center;gap:6px;text-decoration:none;color:var(--mut);font-size:14px;padding:7px 12px;border-radius:10px;transition:background .15s,color .15s}
.tab svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.tab.on{color:var(--fg);background:var(--surface);box-shadow:var(--shadow)}
.tabs-top{display:none}
.tabs-bottom{position:fixed;left:0;right:0;bottom:0;z-index:20;justify-content:space-around;padding:6px 8px calc(6px + env(safe-area-inset-bottom));
background:color-mix(in srgb,var(--surface) 88%,transparent);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border-top:1px solid var(--line)}
.tabs-bottom .tab{flex-direction:column;gap:2px;font-size:11px;padding:6px 10px;flex:1;align-items:center}
.tabs-bottom .tab svg{width:22px;height:22px}
.tabs-bottom .tab.on{background:transparent;box-shadow:none;color:var(--accent)}
@media (min-width:900px){.tabs-top{display:flex}.tabs-bottom{display:none}body{padding-bottom:40px}}
/* 視圖 */
.view{display:none;padding:18px 0 8px;animation:in .28s ease}
.view.on{display:block}
@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.view-head{margin:4px 2px 14px}.view-head h2{font-size:22px;margin:0;letter-spacing:.2px}.view-head p{margin:4px 0 0;color:var(--mut);font-size:13.5px}
.grid{display:grid;gap:14px}.grid>*{min-width:0}
@media (min-width:900px){.g-2{grid-template-columns:1.25fr 1fr}.g-ind{grid-template-columns:1fr 1fr}.g-tim{grid-template-columns:1fr 1fr}.g-tim>.card:last-child{grid-column:1/-1}}

.card{background:color-mix(in srgb,var(--surface) 82%,transparent);backdrop-filter:blur(14px) saturate(1.2);-webkit-backdrop-filter:blur(14px) saturate(1.2);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow),inset 0 1px 0 var(--hl);padding:18px}
.card+.card{margin-top:14px}.grid>.card+.card{margin-top:0}
.card-head{display:flex;align-items:flex-start;gap:12px;margin-bottom:10px}.card-head>div:first-child{flex:1}
.card h3{margin:0;font-size:16px}
.eyebrow{font-size:11px;letter-spacing:1.2px;color:var(--faint);font-weight:600}
.link{font-size:13px;color:var(--accent);text-decoration:none;white-space:nowrap}
.banner{border-radius:14px;padding:10px 14px;font-size:13px;margin:14px 0 0}
.banner.warn{background:color-mix(in srgb,var(--warm) 14%,transparent);border:1px solid color-mix(in srgb,var(--warm) 40%,transparent)}
/* 總覽 */
.hero{display:flex;flex-direction:column;align-items:center;text-align:center;padding:22px 18px 18px;position:relative;overflow:hidden}
.hero::before{content:"";position:absolute;left:50%;top:-40%;width:130%;height:90%;transform:translateX(-50%);pointer-events:none;background:radial-gradient(closest-side,color-mix(in srgb,var(--accent) 22%,transparent),transparent);filter:blur(8px)}
.hero>*{position:relative}
.gwrap{position:relative;width:220px;height:200px}
.gauge{width:100%;height:auto;display:block}
.g-track{fill:none;stroke:var(--line2);stroke-linecap:round}
.g-val{fill:none;stroke-linecap:round;transition:stroke-dasharray .8s ease}
.g-tick{stroke:var(--mut);stroke-width:2;stroke-linecap:round}
.gcenter{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding-top:6px}
.hero-label{font-size:12.5px;color:var(--mut);letter-spacing:.5px}
.hero-num{font-size:68px;font-weight:700;line-height:1;letter-spacing:-2px;margin:2px 0 6px}
.lv{display:inline-block;padding:4px 14px;border-radius:999px;font-weight:600;font-size:13.5px}
.lv-none,.lvb-none{background:var(--line2);color:var(--fg)}.lvb-zone{background:var(--s-bot);color:#fff}.lvb-strong{background:var(--bot-c2);color:#fff}.lv-window{background:var(--lv-window);color:#fff}.lv-alert{background:var(--lv-alert);color:#fff}
.formula{font-size:12.5px;color:var(--mut);margin-top:12px}
.formula b{color:var(--fg);font-weight:600}
.minis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;width:100%;margin-top:16px}
.mini{background:var(--surface2);border:1px solid var(--line);border-radius:14px;padding:10px 6px 8px;text-decoration:none}
.mini .gwrap{width:86px;height:78px;margin:0 auto}
.mini .gcenter{padding-top:4px}.mini .mv{font-size:24px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
.mini .ml{font-size:12px;color:var(--mut);margin-top:2px}
.mini .big{font-size:30px;font-weight:700;line-height:78px;font-variant-numeric:tabular-nums}.mini .big small{font-size:15px;color:var(--mut)}
.crow{display:grid;grid-template-columns:88px 1fr 34px;align-items:center;gap:12px;padding:9px 2px;text-decoration:none;border-top:1px solid var(--line)}
.crow:first-of-type{border-top:0}
.crow-name{font-size:14px}.crow-sc{text-align:right;font-weight:700}
.crow-bar,.bar,.mbar{position:relative;display:block;height:8px;background:var(--line);border-radius:99px;overflow:hidden}
.crow-bar i,.bar i,.mbar i{display:block;height:100%;border-radius:99px}
.crow-bar em,.bar em{position:absolute;left:80%;top:0;bottom:0;width:2px;background:var(--fg);opacity:.25}
i.cold{background:var(--cold)}i.warm{background:var(--warm)}i.hot{background:var(--hot)}i.top{background:var(--top)}i.na{background:transparent}
.cold{color:var(--cold)}.warm{color:var(--warm)}.hot{color:var(--hot)}.top{color:var(--top)}.na{color:var(--na)}
/* 頂部／底部切換 */
.mode-bar{position:sticky;top:58px;z-index:15;margin:0 -16px 6px;padding:10px 16px;background:transparent;pointer-events:none}.mode-bar .seg-mode{pointer-events:auto}
.seg-mode{display:grid;grid-template-columns:1fr 1fr;gap:6px;background:color-mix(in srgb,var(--surface) 78%,transparent);backdrop-filter:blur(18px) saturate(1.3);-webkit-backdrop-filter:blur(18px) saturate(1.3);border:1px solid var(--line2);border-radius:16px;padding:5px;box-shadow:var(--shadow);max-width:560px;margin:0 auto}
.seg-mode a{display:flex;align-items:center;justify-content:center;gap:10px;text-decoration:none;color:var(--mut);padding:9px 10px;border-radius:12px;transition:background .2s,color .2s}
.seg-mode a svg{width:22px;height:22px;flex:none;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.seg-mode a span{display:flex;flex-direction:column;line-height:1.25}
.seg-mode a b{font-size:15.5px;font-weight:700}.seg-mode a small{font-size:11px;opacity:.8}
.seg-mode a:hover{color:var(--fg)}
.seg-mode a.on[data-mode="top"]{background:linear-gradient(135deg,var(--top-c),var(--top-c2));color:#fff;box-shadow:0 6px 18px color-mix(in srgb,var(--top-c) 32%,transparent),inset 0 1px 0 rgba(255,255,255,.18)}
.seg-mode a.on[data-mode="bottom"]{background:linear-gradient(135deg,var(--bot-c),var(--bot-c2));color:#fff;box-shadow:0 6px 18px color-mix(in srgb,var(--bot-c) 32%,transparent),inset 0 1px 0 rgba(255,255,255,.18)}
@media (min-width:900px){.mode-bar{top:58px}}
body.mode-bottom{--glow2:#2b8fd6;--accent:var(--bot-c);--accent-soft:color-mix(in srgb,var(--bot-c) 14%,transparent)}
.mode{display:none}body:not(.mode-bottom) .mode[data-mode="top"],body.mode-bottom .mode[data-mode="bottom"]{display:block;animation:in .25s ease}
.tb-bot{display:none!important}body.mode-bottom .tb-bot{display:inline!important}body.mode-bottom .tb-top{display:none!important}
.ck-top.ck-bot i{background:var(--botline)}
i.cool{background:var(--s-cold)}.cool-t{color:var(--s-cold)}
.status{font-size:12.5px;font-weight:600;border-radius:99px;padding:3px 12px;white-space:nowrap}
.st-testing{background:color-mix(in srgb,var(--warm) 18%,transparent);color:var(--warm)}
.st-supported{background:color-mix(in srgb,var(--s-bot) 18%,transparent);color:var(--s-bot)}
.st-classic{background:var(--accent-soft);color:var(--accent)}
.verdict .q{font-size:14px;margin:0 0 10px}
.countdown{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px}
.countdown div{background:var(--surface2);border:1px solid var(--line);border-radius:12px;padding:8px 10px}
.countdown b{display:block;font-size:17px;font-variant-numeric:tabular-nums;white-space:nowrap}.countdown span{font-size:11.5px;color:var(--mut)}
table.data.fit{table-layout:fixed;font-size:12.5px}table.data.fit th,table.data.fit td{padding:7px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}table.data.fit th{white-space:normal;line-height:1.25;vertical-align:bottom}
table.data.fit th:first-child,table.data.fit td:first-child{width:24%}table.data.fit td small{display:block;font-size:10.5px;font-weight:500;color:var(--mut)}
tr.cur td{font-weight:700;background:color-mix(in srgb,var(--s-bot) 8%,transparent)}
.grp{background:var(--surface2);border:1px solid var(--line);border-radius:14px;padding:10px 12px;margin-top:10px}
.grp-head{display:flex;align-items:baseline;gap:8px;font-weight:700;margin-bottom:4px}.grp-head .muted{flex:1;font-weight:400}.grp-head b{font-size:18px}
.crow2{display:grid;grid-template-columns:1fr auto 34px;gap:4px 10px;padding:8px 0;border-top:1px solid var(--line)}
.c2-name{font-weight:600;font-size:13.5px}.c2-desc{font-size:12px;color:var(--mut);line-height:1.5}.c2-meta{font-size:11.5px;color:var(--faint);margin-top:2px}
.c2-val{text-align:right;font-variant-numeric:tabular-nums;font-size:14px;white-space:nowrap}.c2-sc{text-align:right;font-weight:700;color:var(--s-cold);font-variant-numeric:tabular-nums}
.c2-bar{grid-column:1/-1;height:5px}
/* 時間軸 */
.tl{margin:8px 0 6px;padding:26px 0 0}
.tl-track{position:relative;height:12px;background:var(--line);border-radius:99px}
.tl-progress{position:absolute;left:0;top:0;bottom:0;border-radius:99px;background:linear-gradient(90deg,transparent,var(--accent-soft))}
.tl-band{position:absolute;top:0;bottom:0;background:var(--accent);border-radius:99px;opacity:.9}
.tl-band.soft{background:var(--accent);opacity:.18}
.tl-band.low{background:transparent;border:2px dashed var(--warm);top:-4px;bottom:-4px;opacity:.9}
.tl-mark{position:absolute;top:50%;transform:translate(-50%,-50%)}
.tl-mark i{display:block;width:10px;height:10px;border-radius:50%;background:var(--surface);border:2px solid var(--mut)}
.tl-mark.m-top i{border-color:var(--topline)}.tl-mark.m-low i{border-color:var(--cold)}.tl-mark.m-halving i{border-color:var(--warm)}
.tl-mark.r2 b{top:32px}
.tl-mark.al b{left:-5px;transform:none}.tl-mark.ar b{left:auto;right:-5px;transform:none}
.tl-mark b{position:absolute;top:16px;left:50%;transform:translateX(-50%);font-size:11px;font-weight:500;color:var(--mut);white-space:nowrap}
.tl-now{position:absolute;top:-8px;bottom:-8px;width:2px;background:var(--fg);transform:translateX(-1px);border-radius:2px}
.tl-now b{position:absolute;bottom:calc(100% + 4px);left:50%;transform:translateX(-50%);font-size:11px;background:var(--fg);color:var(--bg);padding:1px 7px;border-radius:99px;white-space:nowrap}
.tl-years{position:relative;height:18px;margin-top:46px;border-top:1px solid var(--line)}
.tl-year{position:absolute;top:3px;transform:translateX(-50%);font-size:11px;color:var(--faint)}
.tl-legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--mut);margin-top:6px}
.tl-legend i{display:inline-block;width:18px;height:8px;border-radius:99px;margin-right:6px;vertical-align:0}
.k-band{background:var(--accent)}.k-low{border:2px dashed var(--warm);height:10px!important}
/* 時鐘 */
.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:2px 0 6px}
.facts div{background:var(--surface2);border:1px solid var(--line);border-radius:12px;padding:8px 10px}
.facts span{display:block;font-size:11.5px;color:var(--mut)}.facts b{font-size:13.5px;font-variant-numeric:tabular-nums;white-space:nowrap}
.ck{padding:48px 0 0;margin-bottom:6px}
.ck-track{position:relative;height:10px;background:var(--line);border-radius:99px}
.ck-band{position:absolute;top:0;bottom:0;background:var(--accent);border-radius:99px}.ck-band.soft{opacity:.2}
.ck-top{position:absolute;top:50%;transform:translate(-50%,-50%)}
.ck-top i{display:block;width:12px;height:12px;border-radius:50%;background:var(--topline);border:2px solid var(--surface)}
.ck-lbl.r2{bottom:30px}
.ck-lbl{position:absolute;bottom:16px;transform:translateX(-50%);font-size:10.5px;color:var(--mut);white-space:nowrap}
.ck-now{position:absolute;top:-7px;bottom:-7px;width:2px;background:var(--fg);transform:translateX(-1px)}
.ck-now b{position:absolute;top:calc(100% + 4px);left:50%;transform:translateX(-50%);font-size:11px;background:var(--fg);color:var(--bg);padding:1px 7px;border-radius:99px;white-space:nowrap}
.ck-now.al b{left:-2px;transform:none}.ck-now.ar b{left:auto;right:-2px;transform:none}
.ck-ticks{position:relative;height:16px;margin-top:28px}
.ck-tick{position:absolute;transform:translateX(-50%);font-size:10.5px;color:var(--faint)}
.kpi{text-align:right}.kpi-v{font-size:30px;font-weight:700;line-height:1}.kpi-l{font-size:12px;color:var(--mut);margin-left:3px}
/* 熱度 */
.cat{background:color-mix(in srgb,var(--surface) 82%,transparent);backdrop-filter:blur(14px) saturate(1.2);-webkit-backdrop-filter:blur(14px) saturate(1.2);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow),inset 0 1px 0 var(--hl);margin-bottom:14px;overflow:hidden}
.cat summary{list-style:none;cursor:pointer;padding:16px 18px}
.cat summary::-webkit-details-marker{display:none}
.cat-top{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}
.cat-name{font-size:17px;font-weight:700}.cat-w{flex:1;font-size:12px;color:var(--mut)}
.cat-sc{font-size:28px;font-weight:700;line-height:1}
.chev{width:10px;height:10px;border-right:2px solid var(--faint);border-bottom:2px solid var(--faint);transform:rotate(45deg);margin-left:4px;transition:transform .2s;align-self:center}
.cat[open] .chev{transform:rotate(-135deg)}
.ind-grid{display:grid;gap:10px;padding:0 14px 14px}
@media (min-width:640px){.ind-grid{grid-template-columns:1fr 1fr}}
.ind{all:unset;box-sizing:border-box;display:block;cursor:pointer;background:var(--surface2);border:1px solid var(--line);border-radius:14px;padding:12px 14px;transition:border-color .15s,transform .15s}
.ind:hover{border-color:var(--line2)}.ind:active{transform:scale(.99)}
.ind:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.ind-top{display:flex;align-items:center;gap:6px;font-size:13.5px;font-weight:600}
.ind-mid{display:flex;align-items:baseline;justify-content:space-between;margin:6px 0 8px}
.ind-val{font-size:19px;font-weight:600}.ind-sc{font-size:22px;font-weight:700}
.mbar{height:6px}
.ind-foot{display:flex;font-size:11.5px;color:var(--faint);margin-top:8px}.ind-foot .more{margin-left:auto;color:var(--accent)}
.pill{font-size:10.5px;border-radius:99px;padding:0 7px;font-weight:600}.pill.warn{background:var(--warm);color:#fff}
.na{padding:0 18px 14px;margin:0}
/* 圖表 */
.seg{display:inline-flex;background:var(--surface2);border:1px solid var(--line);border-radius:12px;padding:3px;gap:2px}
.seg button{border:0;background:transparent;color:var(--mut);font:inherit;font-size:13px;padding:5px 12px;border-radius:9px;cursor:pointer}
.seg button.on{background:var(--surface);color:var(--fg);box-shadow:var(--shadow)}
.chart-card{margin-top:14px}.chart-card .card-head{flex-wrap:wrap;align-items:center}
.mode+.mode{margin-top:0}
.chart-top{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:10px}
svg.chart{width:100%;display:block;touch-action:pan-y;overflow:visible}
.tip{font-size:12.5px;min-height:22px;display:flex;gap:12px;flex-wrap:wrap;color:var(--mut);margin-bottom:4px;font-variant-numeric:tabular-nums}
.tip b{color:var(--fg)}
.legend{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.legend button{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--surface2);color:var(--fg);font:inherit;font-size:12.5px;padding:4px 10px;border-radius:99px;cursor:pointer}
.legend button.off{opacity:.4}
.legend i{width:14px;height:3px;border-radius:2px;display:inline-block}
.legend .static{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;padding:4px 10px;border:1px dashed var(--line2);border-radius:99px;color:var(--mut);cursor:default}
.legend i.area{height:10px;width:14px;border-radius:3px;background:color-mix(in srgb,var(--price) 30%,transparent);border-top:1.5px solid var(--price)}
.legend i.dash{height:0;background:none!important;border-top:2px dashed var(--topline)}
.legend i.dash.bot{border-top-color:var(--botline)}.legend i.dash.dot{border-top-style:dotted;opacity:.7}
.mk-bot{display:none!important}body.mode-bottom .mk-bot{display:inline-flex!important}body.mode-bottom .mk-top{display:none!important}
/* 數據 */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:thin;scrollbar-color:var(--line2) transparent}
.scroll::-webkit-scrollbar{height:6px}.scroll::-webkit-scrollbar-thumb{background:var(--line2);border-radius:99px}.scroll::-webkit-scrollbar-track{background:transparent}
table.data{border-collapse:collapse;width:100%;font-size:13px}
table.data th,table.data td{padding:8px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
table.data th{color:var(--mut);font-weight:500;font-size:12px;position:sticky;top:0;background:var(--surface)}
table.data th:first-child,table.data td:first-child{text-align:left}
table.data tbody tr:hover{background:var(--surface2)}
table.data.compact td,table.data.compact th{padding:6px 8px}
td.b{font-weight:700}
.dl{display:grid;gap:10px}
@media (min-width:640px){.dl{grid-template-columns:repeat(2,1fr)}}
.dl a{display:flex;align-items:center;justify-content:space-between;text-decoration:none;background:var(--surface2);border:1px solid var(--line);border-radius:14px;padding:12px 14px;font-size:14px}
.dl a span{color:var(--mut);font-size:12px}
footer{color:var(--faint);font-size:12px;padding:20px 2px 8px;line-height:1.7}
/* 抽屜 */
.sheet-wrap{position:fixed;inset:0;z-index:50;display:flex;align-items:flex-end;justify-content:center}
.sheet-wrap[hidden]{display:none}
.backdrop{position:absolute;inset:0;background:rgba(0,0,0,.45);animation:fade .2s}
.sheet{position:relative;width:100%;max-width:720px;max-height:88vh;overflow:auto;background:var(--surface);border-radius:22px 22px 0 0;
padding:10px 18px calc(22px + env(safe-area-inset-bottom));box-shadow:0 -10px 40px rgba(0,0,0,.3);animation:up .26s cubic-bezier(.2,.8,.2,1)}
@media (min-width:900px){.sheet-wrap{align-items:center}.sheet{border-radius:22px;max-height:84vh}}
.grab{width:40px;height:5px;border-radius:99px;background:var(--line2);margin:0 auto 8px}
.x{position:absolute;right:14px;top:12px}
@keyframes up{from{transform:translateY(40px);opacity:.6}to{transform:none;opacity:1}}
@keyframes fade{from{opacity:0}}
.sh-cat{font-size:12px;color:var(--mut);margin-top:6px}.sh-title{font-size:20px;font-weight:700;margin:2px 40px 10px 0}
.sh-kpis{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px}
.sh-kpis div{background:var(--surface2);border:1px solid var(--line);border-radius:14px;padding:10px 12px}
.sh-kpis span{display:block;font-size:12px;color:var(--mut)}.sh-kpis b{font-size:22px;font-variant-numeric:tabular-nums}
.sh-p{font-size:14px;margin:0 0 8px}.sh-m{font-size:12.5px;color:var(--mut);margin:0 0 14px}
.guide h3{font-size:15px;margin:16px 0 6px}.guide p,.guide li{font-size:14px}.guide ul{padding-left:20px;margin:6px 0}
.guide .callout{background:var(--surface2);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin:10px 0}
/* 寬螢幕：放寬內容寬度、總覽三欄 */
@media (min-width:1200px){
  .wrap{max-width:1440px;padding:0 28px}
  .mode-bar{margin:0 -28px 6px;padding:10px 28px}
  .g-2{grid-template-columns:1.05fr 1fr 1fr;align-items:stretch}
  .g-2>.grid{display:contents}
  .g-2>.grid>.card{margin:0}
  .view-head p{max-width:860px}
  .ind-grid{grid-template-columns:repeat(3,1fr)}
  .dl{grid-template-columns:repeat(4,1fr)}
}
@media (min-width:1560px){.ind-grid{grid-template-columns:repeat(4,1fr)}}
@media (min-width:1200px){.cold-groups{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;align-items:start}.cold-groups .cat{margin:0}.cold-groups .ind-grid{grid-template-columns:1fr}}

/* =====================================================================
   極光潮汐 Aurora Tide（覆蓋上方舊樣式；結構與功能不變）
   ===================================================================== */
@font-face{font-family:"Archivo";src:url("__FONT_BASE__Archivo.woff2") format("woff2");font-weight:100 900;font-display:swap}
@font-face{font-family:"JetBrains Mono";src:url("__FONT_BASE__JetBrainsMono.woff2") format("woff2");font-weight:100 800;font-display:swap}
:root{--disp:"Archivo",-apple-system,"PingFang TC","Noto Sans TC",sans-serif;--mono:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,monospace;
  /* 淺色（白天版極光） */
  --bg:#f1f2f8;--surface:rgba(255,255,255,.74);--surface2:rgba(255,255,255,.6);--line:rgba(20,24,60,.10);--line2:rgba(20,24,60,.17);
  --fg:#0e1124;--mut:#535a77;--faint:#8a90a8;--shadow:0 16px 40px rgba(20,24,60,.10);--hl:rgba(255,255,255,.9);--price:#5b6178;
  --a1:#e2365a;--a2:#9b2fe0;--a3:#e8862a;--top-c:#e2365a;--top-c2:#9b2fe0;--bot-c:#0fae86;--bot-c2:#1f8fe0;
  --s-sig:#e2365a;--s-bot:#0fae86;--s-heat:#c8941c;--s-cold:#2a8fc9;--s-tim:#8b93a8;--topline:#7c5cd6;--botline:#c026d3;
  --aurora-op:.32;--star-op:0;--veil:var(--bg);--glass-blur:18px}
body.mode-bottom{--a1:#0fae86;--a2:#1f8fe0;--a3:#2fbf92}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#03040a;--surface:rgba(13,15,26,.62);--surface2:rgba(255,255,255,.035);--line:rgba(255,255,255,.08);--line2:rgba(255,255,255,.15);
  --fg:#f3f5ff;--mut:#9aa1c0;--faint:#5f6684;--shadow:0 20px 60px rgba(0,0,0,.45);--hl:rgba(255,255,255,.07);--price:#aeb6d0;
  --a1:#ff4d6d;--a2:#c03cff;--a3:#ff9f43;--top-c:#ff4d6d;--top-c2:#c03cff;--bot-c:#20e3b2;--bot-c2:#2aa8ff;
  --s-sig:#ff4d6d;--s-bot:#20e3b2;--s-heat:#e9b44c;--s-cold:#4cc3f5;--s-tim:#6b7393;--topline:#a48bff;--botline:#e879f9;--aurora-op:.62;--star-op:1}
  :root:not([data-theme="light"]) body.mode-bottom{--a1:#20e3b2;--a2:#2aa8ff;--a3:#7cffcb}}
:root[data-theme="dark"]{
  --bg:#03040a;--surface:rgba(13,15,26,.62);--surface2:rgba(255,255,255,.035);--line:rgba(255,255,255,.08);--line2:rgba(255,255,255,.15);
  --fg:#f3f5ff;--mut:#9aa1c0;--faint:#5f6684;--shadow:0 20px 60px rgba(0,0,0,.45);--hl:rgba(255,255,255,.07);--price:#aeb6d0;
  --a1:#ff4d6d;--a2:#c03cff;--a3:#ff9f43;--top-c:#ff4d6d;--top-c2:#c03cff;--bot-c:#20e3b2;--bot-c2:#2aa8ff;
  --s-sig:#ff4d6d;--s-bot:#20e3b2;--s-heat:#e9b44c;--s-cold:#4cc3f5;--s-tim:#6b7393;--topline:#a48bff;--botline:#e879f9;--aurora-op:.62;--star-op:1}
:root[data-theme="dark"] body.mode-bottom{--a1:#20e3b2;--a2:#2aa8ff;--a3:#7cffcb}
body{background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang TC","Noto Sans TC","Microsoft JhengHei",sans-serif}
body::before,body::after{content:none}
body,body.mode-bottom{--accent:var(--a1);--accent-soft:color-mix(in srgb,var(--a1) 14%,transparent)}
/* 背景：星空＋極光 */
#stars{position:fixed;inset:0;z-index:-2;pointer-events:none;opacity:var(--star-op);transition:opacity .6s}
.aurora{position:fixed;inset:-20%;z-index:-3;pointer-events:none;filter:blur(90px) saturate(1.25);opacity:var(--aurora-op);transition:opacity .6s}
.aurora i{position:absolute;border-radius:50%;mix-blend-mode:screen;transition:background 1.4s}
:root[data-theme="light"] .aurora i{mix-blend-mode:multiply}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]) .aurora i{mix-blend-mode:multiply}}
.aurora i:nth-child(1){width:55vw;height:40vw;left:2%;top:0;background:var(--a1);animation:au1 18s ease-in-out infinite alternate}
.aurora i:nth-child(2){width:45vw;height:35vw;left:48%;top:4%;background:var(--a2);animation:au2 22s ease-in-out infinite alternate}
.aurora i:nth-child(3){width:30vw;height:24vw;left:28%;top:34%;background:var(--a3);opacity:.45;animation:au3 26s ease-in-out infinite alternate}
@keyframes au1{to{transform:translate(12vw,8vh) scale(1.15) rotate(12deg)}}
@keyframes au2{to{transform:translate(-14vw,10vh) scale(.9) rotate(-10deg)}}
@keyframes au3{to{transform:translate(8vw,-8vh) scale(1.2)}}
.veil{position:fixed;inset:0;z-index:-1;pointer-events:none;background:radial-gradient(130% 90% at 50% 0%,transparent 38%,var(--bg) 88%)}
/* 跑馬燈（瑞士） */
.ticker{height:28px;overflow:hidden;white-space:nowrap;display:flex;align-items:center;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--bg) 55%,transparent);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.ticker .track{display:inline-flex;gap:40px;padding-left:40px;animation:tick 48s linear infinite}
.ticker span{font:500 11px var(--mono);color:var(--mut);letter-spacing:.05em}.ticker b{color:var(--fg);font-weight:600;margin-left:8px}
@keyframes tick{to{transform:translateX(-50%)}}
/* 頁首與標誌 */
.appbar{background:color-mix(in srgb,var(--bg) 50%,transparent)}
.wordmark{font-family:var(--disp);font-weight:800;letter-spacing:-.02em;background:none;color:var(--fg);-webkit-text-fill-color:currentColor}
.logo{box-shadow:0 0 22px color-mix(in srgb,var(--a1) 50%,transparent),inset 0 0 0 1px rgba(255,255,255,.18);transition:box-shadow 1s}
.logo stop{transition:stop-color 1s}
.brand .sub{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em}
.tab{font-weight:500}.tab.on{color:var(--fg)}
.tabs-top .tab.on{background:color-mix(in srgb,var(--a1) 14%,transparent);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--a1) 40%,transparent)}
.tabs-bottom .tab.on{color:var(--a1)}
.seg-mode{background:color-mix(in srgb,var(--surface) 70%,transparent)}
/* 全屏首屏 */
.hero2{position:relative;min-height:calc(100vh - 168px);min-height:calc(100svh - 168px);display:grid;grid-template-columns:1fr minmax(210px,300px);gap:3vw;
  margin:0 -28px;padding:2vh 28px 0;overflow:hidden}
.h2-left{display:flex;flex-direction:column;justify-content:center;padding-bottom:24vh;min-width:0}
.eyebrow2{font:600 11px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--mut)}
.giant{font:900 clamp(190px,30vw,500px)/.8 var(--disp);letter-spacing:-.075em;margin:1vh 0 0 -1vw;white-space:nowrap;font-variant-numeric:tabular-nums}
.giant .z{color:transparent;-webkit-text-stroke:1.5px color-mix(in srgb,var(--fg) 14%,transparent)}
.giant .v{color:transparent;-webkit-text-stroke:2px color-mix(in srgb,var(--fg) 55%,transparent);background-repeat:repeat-x,no-repeat;-webkit-background-clip:text;background-clip:text;
  filter:drop-shadow(0 0 36px color-mix(in srgb,var(--a1) 28%,transparent))}
.statusline{display:flex;align-items:center;gap:14px;margin-top:2.4vh;flex-wrap:wrap}
.pill2{font:700 14px/1 -apple-system,"PingFang TC",sans-serif;padding:9px 16px;border-radius:999px;background:linear-gradient(135deg,var(--a1),var(--a2));color:#fff;
  box-shadow:0 6px 24px color-mix(in srgb,var(--a1) 40%,transparent);white-space:nowrap}
.statusline p{margin:0;color:var(--mut);max-width:600px;font-size:14.5px}.statusline p b{color:var(--fg)}
.kpis2{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin-top:3.6vh;border-top:1px solid var(--line);border-bottom:1px solid var(--line);max-width:760px}
.kpi2{padding:14px 18px 12px 0;border-right:1px solid var(--line);text-decoration:none;min-width:0}.kpi2+.kpi2{padding-left:18px}.kpi2:last-child{border-right:0}
.kpi2 b{display:block;font:900 clamp(48px,5.6vw,92px)/.9 var(--disp);letter-spacing:-.045em;font-variant-numeric:tabular-nums}
.kpi2 b small{font-size:.42em;color:var(--mut);letter-spacing:0}
.kpi2 span{display:block;font:600 10.5px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--mut);margin-top:8px}
.kpi2:hover b{color:var(--a1)}
.staff2{position:relative;align-self:center;height:min(58vh,540px);margin-bottom:20vh}
.staff2 .rule{position:absolute;left:44px;top:0;bottom:0;width:2px;background:linear-gradient(transparent,color-mix(in srgb,var(--fg) 35%,transparent),transparent)}
.staff2 .tk{position:absolute;left:30px;width:14px;height:1px;background:color-mix(in srgb,var(--fg) 28%,transparent)}
.staff2 .tk.big{left:18px;width:26px;background:color-mix(in srgb,var(--fg) 60%,transparent)}
.staff2 em{position:absolute;left:0;font:500 10.5px var(--mono);font-style:normal;color:var(--faint);transform:translateY(50%)}
.staff2 .water{position:absolute;left:50px;right:0;bottom:0;border-top:2px solid var(--a1);
  background:linear-gradient(180deg,color-mix(in srgb,var(--a1) 55%,transparent),color-mix(in srgb,var(--a2) 18%,transparent) 60%,transparent);
  box-shadow:0 -8px 30px color-mix(in srgb,var(--a1) 40%,transparent);animation:rise 2.4s cubic-bezier(.2,.8,.2,1) both}
.staff2 .mk{position:absolute;left:50px;right:0;height:0;border-top:1px dashed color-mix(in srgb,var(--fg) 40%,transparent);animation:riseb 2.2s cubic-bezier(.2,.8,.2,1) both}
.staff2 .mk span{position:absolute;right:0;top:-28px;font-size:12px;white-space:nowrap}
.staff2 .mk.below span{top:4px}
.staff2 .mk span b{font:900 22px var(--disp);margin-left:6px;vertical-align:-3px}
.staff2 .thr{position:absolute;left:50px;right:0;height:0;border-top:1px solid color-mix(in srgb,var(--a1) 60%,transparent)}
.staff2 .thr span{position:absolute;left:4px;top:-17px;font:600 10px var(--mono);letter-spacing:.12em;color:var(--a1)}
@keyframes rise{from{height:0}}
@keyframes riseb{from{bottom:0}}
.waves2{position:absolute;left:0;bottom:0;width:100%;height:26vh;pointer-events:none;z-index:0}
.h2-left,.staff2{position:relative;z-index:1}
.scrollcue{position:absolute;left:50%;bottom:2.4vh;transform:translateX(-50%);z-index:2;font:600 10.5px var(--mono);letter-spacing:.28em;color:color-mix(in srgb,var(--fg) 70%,transparent);text-decoration:none;animation:bob 2.4s ease-in-out infinite}
@keyframes bob{50%{transform:translate(-50%,6px);opacity:.5}}
.ov-cards{margin-top:14px}
@media (min-width:900px){.ov-cards{grid-template-columns:1fr 1fr}}
/* 各頁標題：瑞士式大字＋等寬編號 */
.view-head{margin:18px 2px 22px}
.view-head h2{font:900 clamp(44px,6.4vw,104px)/1.02 var(--disp);letter-spacing:-.04em}
.view-head h2 span{background:linear-gradient(90deg,var(--a1),var(--a2),var(--a3));-webkit-background-clip:text;background-clip:text;color:transparent}
.view-head p{font-size:14px;max-width:760px}
.eyebrow,.card-head .eyebrow{font-family:var(--mono);letter-spacing:.14em;color:var(--faint)}
.card h3{font-size:18px;letter-spacing:-.01em}
.card,.cat{border-radius:20px;backdrop-filter:blur(var(--glass-blur)) saturate(1.2);-webkit-backdrop-filter:blur(var(--glass-blur)) saturate(1.2)}
.kpi-v,.cat-sc,.crow-sc,.ind-sc,.ind-val,.hero-num,.mini .mv,.mini .big,.facts b,.countdown b,.sh-kpis b,.hval,.cat-name{font-family:var(--disp);letter-spacing:-.02em}
.cat-sc,.kpi-v{font-weight:900;font-size:34px}.ind-sc{font-weight:900;font-size:26px}.ind-val{font-weight:800}
.crow-sc{font-weight:900;font-size:18px}
.chart-card h3{font:900 clamp(30px,3.4vw,52px)/1 var(--disp);letter-spacing:-.03em}
svg.chart text{font-family:var(--mono)}
.tip,.legend button,.legend .static,.seg button,table.data,.facts span,.countdown span,.ind-foot,.tl-year,.ck-tick,.ck-lbl{font-family:var(--mono)}
table.data th{font-family:var(--mono);letter-spacing:.06em}
i.cool,.cat .bar i.cool{background:linear-gradient(90deg,var(--a2),var(--a1))}
.sheet{background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px)}
@media (max-width:899px){
  .hero2{grid-template-columns:1fr;margin:0 -16px;padding:1vh 16px 0;min-height:auto}
  .h2-left{padding-bottom:2vh}
  .giant{font-size:clamp(150px,50vw,290px);margin-left:-2vw}
  .kpi2 b{font-size:clamp(38px,11vw,56px)}.kpi2{padding-right:10px}.kpi2+.kpi2{padding-left:10px}
  .staff2{height:38vh;margin:3vh 0 24vh;max-width:380px}
  .view-head h2{font-size:clamp(40px,12vw,64px)}
}
@media (min-width:1200px){.hero2{margin:0 -28px;padding-left:28px;padding-right:28px}}
@media (prefers-reduced-motion:reduce){.aurora i,.ticker .track,.scrollcue{animation:none}.staff2 .water,.staff2 .mk{animation:none}}

/* =====================================================================
   v2：全屏首屏、懸浮導航、滑動模式切換、全版大字區塊、進場動效
   ===================================================================== */
html{scroll-padding-top:var(--hdr,96px)}
body{overflow-x:clip}
.topbar{position:fixed;top:0;left:0;right:0;z-index:30;transition:background .5s,box-shadow .5s}
.topbar::before{content:"";position:absolute;inset:0;z-index:-1;opacity:0;transition:opacity .5s;
  background:color-mix(in srgb,var(--bg) 66%,transparent);backdrop-filter:blur(20px) saturate(1.4);-webkit-backdrop-filter:blur(20px) saturate(1.4);box-shadow:0 1px 0 var(--line)}
.topbar.solid::before{opacity:1}
.topbar .ticker{background:transparent;backdrop-filter:none;-webkit-backdrop-filter:none}
.topbar .appbar{position:static;background:transparent;backdrop-filter:none;-webkit-backdrop-filter:none;border:0}
.appbar-in{display:flex;align-items:center;gap:22px;height:66px;padding:0 max(16px,3vw)}
.brand{flex:none}
.brand .logo{width:34px;height:34px;border-radius:10px}
.wordmark{font-size:19px}
.tabs-top{position:relative;gap:4px;margin-left:auto;counter-reset:tb}
.topbar .tabs-top .tab,.topbar .tabs-top .tab.on{background:none;box-shadow:none;border-radius:0;padding:10px 12px;font-size:14px;font-weight:500;gap:7px;color:var(--mut);transition:color .3s}
.tabs-top .tab svg{display:none!important}
.tabs-top .tab::before{counter-increment:tb;content:"0" counter(tb);font:600 10px var(--mono);letter-spacing:.06em;color:var(--faint);transition:color .3s}
.topbar .tabs-top .tab:hover,.topbar .tabs-top .tab.on{color:var(--fg)}
.tabs-top .tab.on::before{color:var(--a1)}
.tab-ind{position:absolute;left:0;bottom:2px;height:2px;width:0;border-radius:2px;background:linear-gradient(90deg,var(--a1),var(--a2));
  box-shadow:0 0 12px var(--a1);transition:transform .55s cubic-bezier(.2,.8,.2,1),width .55s cubic-bezier(.2,.8,.2,1),opacity .3s;pointer-events:none}
/* 模式切換：滑動光塊 */
.sw{position:relative;flex:none;display:grid;grid-template-columns:1fr 1fr;padding:4px;border-radius:999px;
  background:color-mix(in srgb,var(--surface) 55%,transparent);border:1px solid var(--line2);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px)}
.sw a{position:relative;z-index:1;display:flex;align-items:center;justify-content:center;gap:8px;padding:8px 16px;border-radius:999px;text-decoration:none;
  color:var(--mut);font-size:13.5px;font-weight:600;white-space:nowrap;transition:color .45s}
.sw a:hover{color:var(--fg)}
.sw a svg{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
.sw a em{font:700 11px/1 var(--mono);font-style:normal;padding:4px 6px;border-radius:6px;background:color-mix(in srgb,var(--fg) 9%,transparent);color:var(--fg);transition:background .45s,color .45s}
.sw a.on,.sw a.on:hover{color:#fff}.sw a.on em{background:rgba(255,255,255,.22);color:#fff}
.sw-thumb{position:absolute;z-index:0;top:4px;bottom:4px;left:4px;width:calc(50% - 4px);border-radius:999px;overflow:hidden;
  background:linear-gradient(135deg,var(--a1),var(--a2));box-shadow:0 8px 26px color-mix(in srgb,var(--a1) 45%,transparent),inset 0 1px 0 rgba(255,255,255,.28);
  transition:transform .65s cubic-bezier(.65,0,.25,1),box-shadow .8s}
.sw-thumb::after{content:"";position:absolute;top:0;bottom:0;width:40%;left:-60%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.35),transparent);animation:shine 5.5s ease-in-out infinite}
@keyframes shine{0%,70%{left:-60%}100%{left:130%}}
body.mode-bottom .sw-thumb{transform:translateX(100%)}
.tools{display:flex;align-items:center;gap:2px;padding-left:14px;border-left:1px solid var(--line2)}
.topbar .tools .iconbtn{width:34px;height:34px;margin:0;border:0;border-radius:10px;background:transparent;color:var(--mut);transition:color .2s,background .2s}
.topbar .tools .iconbtn:hover{color:var(--fg);background:color-mix(in srgb,var(--fg) 8%,transparent)}
.banners{padding:0 max(16px,3vw) 8px}.banners:empty{display:none}.banners .banner{margin:0}
/* 版面：內容從頁首下方開始；總覽首屏鋪滿整個視窗 */
main.wrap{padding-top:var(--hdr,96px)}
.view{padding-top:6px}
.view[data-view="overview"]{padding-top:0}
.hero2{min-height:100vh;min-height:100svh;margin:calc(-1 * var(--hdr,96px)) calc(50% - 50vw) 0;padding:calc(var(--hdr,96px) + 2vh) max(16px,4vw) 0;
  grid-template-columns:1fr minmax(220px,300px);gap:3vw}
.h2-left{padding-bottom:20vh}
.giant{font-size:clamp(200px,33vw,560px);line-height:.78;margin:2vh 0 0 -1.2vw}
.staff2{height:min(60vh,560px);margin-bottom:18vh}
.waves2{height:30vh}
.eyebrow2{display:flex;align-items:center;gap:10px}
.live{width:7px;height:7px;border-radius:50%;background:var(--a1);box-shadow:0 0 0 0 color-mix(in srgb,var(--a1) 60%,transparent);animation:pulse 2s infinite}
@keyframes pulse{70%{box-shadow:0 0 0 9px transparent}100%{box-shadow:0 0 0 0 transparent}}
.scrollcue{display:flex;flex-direction:column;align-items:center;gap:4px;bottom:3vh}
.scrollcue span{font-size:14px;letter-spacing:0}
/* 全版區塊 */
.sec{position:relative;padding:12vh 0 2vh}
.sec-h{display:flex;align-items:flex-end;justify-content:space-between;gap:16px 24px;flex-wrap:wrap;margin-bottom:4vh}
.sec-h>div:first-child{min-width:0}
.sec-h h2{font:900 clamp(52px,7.6vw,132px)/1 var(--disp);letter-spacing:-.05em;margin:10px 0 0}
.sec-h h2 em,.view-head h2 span{font-style:normal;background:linear-gradient(90deg,var(--a1),var(--a2),var(--a3),var(--a1));background-size:300% 100%;
  -webkit-background-clip:text;background-clip:text;color:transparent;animation:sheen 10s linear infinite}
@keyframes sheen{to{background-position:300% 0}}
.sec-n{font:600 11px var(--mono);letter-spacing:.18em;text-transform:uppercase;color:var(--mut)}
.sec-link{font:600 12px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--fg);text-decoration:none;padding:10px 16px;border:1px solid var(--line2);border-radius:999px;transition:.3s;white-space:nowrap}
.sec-link:hover{background:linear-gradient(135deg,var(--a1),var(--a2));border-color:transparent;color:#fff;box-shadow:0 6px 24px color-mix(in srgb,var(--a1) 40%,transparent)}
.chart-sec .seg{background:color-mix(in srgb,var(--surface) 55%,transparent)}
.chart-sec svg.chart{width:100%;display:block;margin-top:6px}
.chart-sec .tip{font-size:12.5px}
/* 大數字類別格 */
.bigcats{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));border-top:1px solid var(--line2)}
.bigcat{display:flex;flex-direction:column;justify-content:space-between;gap:3vh;min-height:30vh;padding:3vh 2vw 3vh 0;border-bottom:1px solid var(--line2);text-decoration:none;position:relative}
.bigcat+.bigcat{padding-left:2vw;border-left:1px solid var(--line2)}
.bigcat::after{content:"";position:absolute;inset:0;background:radial-gradient(60% 80% at 30% 100%,color-mix(in srgb,var(--a1) 14%,transparent),transparent);opacity:0;transition:opacity .4s;pointer-events:none}
.bigcat:hover::after{opacity:1}
.bc-top{display:flex;flex-direction:column;gap:4px}
.bc-name{font-size:16px;font-weight:600}
.bc-w{font:500 10.5px var(--mono);letter-spacing:.12em;color:var(--mut);text-transform:uppercase}
.bigcat b{font:900 clamp(96px,10.5vw,190px)/.85 var(--disp);letter-spacing:-.06em;font-variant-numeric:tabular-nums;transition:color .35s}
.bigcat:hover b{color:var(--a1)}
.bc-bar{position:relative;display:block;height:3px;background:var(--line2);border-radius:3px;margin-top:2.4vh}
.bc-bar i{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:3px;transition:width 1.8s cubic-bezier(.2,.8,.2,1) .2s}
.bc-bar i.cool{background:linear-gradient(90deg,var(--a2),var(--a1));box-shadow:0 0 14px var(--a1)}
.bc-bar em{position:absolute;left:80%;top:-5px;bottom:-5px;width:1px;background:var(--fg);opacity:.3}
.sec.in .bc-bar i,html:not(.js) .bc-bar i{width:var(--w)}
.verdict{max-width:none}
/* 進場動效 */
.js .reveal{opacity:0;transform:translateY(56px);transition:opacity 1.1s ease,transform 1.2s cubic-bezier(.2,.8,.2,1)}
.js .reveal.in{opacity:1;transform:none}
.view.on .view-head{animation:up .9s cubic-bezier(.2,.8,.2,1) both}
.view.on>.mode>.grid>.card,.view.on>.mode>.card,.view.on>.card,.view.on .cat,.view.on .cold-groups>*{animation:up .9s cubic-bezier(.2,.8,.2,1) both;animation-delay:.12s}
.view.on .cat:nth-of-type(2),.view.on .g-tim>.card:nth-child(2),.view.on .cold-groups>*:nth-child(2){animation-delay:.2s}
.view.on .cat:nth-of-type(3),.view.on .g-tim>.card:nth-child(3),.view.on .cold-groups>*:nth-child(3){animation-delay:.28s}
.view.on .cat:nth-of-type(4){animation-delay:.36s}
@keyframes up{from{opacity:0;transform:translateY(34px)}}
.view-head{margin:5vh 2px 4vh}
.view-head .sec-n{margin-bottom:10px}
.view-head h2{font-size:clamp(52px,7.6vw,132px);letter-spacing:-.05em}
/* 手機底部導覽：懸浮膠囊 */
.tabs-bottom{left:12px;right:12px;bottom:calc(10px + env(safe-area-inset-bottom));padding:6px;border-radius:24px;border:1px solid var(--line2);
  background:color-mix(in srgb,var(--bg) 62%,transparent);backdrop-filter:blur(22px) saturate(1.5);-webkit-backdrop-filter:blur(22px) saturate(1.5);box-shadow:0 14px 44px rgba(0,0,0,.35)}
.tabs-bottom .tab{border-radius:18px;padding:7px 4px;gap:3px;transition:background .4s,color .4s,box-shadow .4s}
.tabs-bottom .tab.on{color:#fff;background:linear-gradient(135deg,var(--a1),var(--a2));box-shadow:0 6px 20px color-mix(in srgb,var(--a1) 40%,transparent)}
@media (max-width:1180px){.sw a em{display:none}.brand .sub{display:none}.appbar-in{gap:14px}.sw a{padding:8px 13px}}
@media (max-width:899px){
  body{padding-bottom:calc(98px + env(safe-area-inset-bottom))}
  .appbar-in{flex-wrap:wrap;height:auto;padding:10px 16px;gap:10px}
  .brand{flex:1}.brand .sub{display:block}.wordmark{font-size:18px}
  .sw{order:3;flex:1 1 100%}.sw a{padding:8px 10px;font-size:13.5px}.sw a em{display:inline-block}
  .tools{border-left:0;padding-left:0}
  .hero2{grid-template-columns:1fr;min-height:auto;padding:calc(var(--hdr,96px) + 3vh) 16px 0}
  .h2-left{padding-bottom:2vh}
  .giant{font-size:clamp(150px,52vw,300px);margin-left:-2vw}
  .staff2{height:38vh;margin:4vh 0 24vh;max-width:380px}
  .sec{padding:9vh 0 1vh}
  .sec-h h2,.view-head h2{font-size:clamp(46px,13vw,72px)}
  .bigcats{grid-template-columns:1fr 1fr}
  .bigcat,.bigcat+.bigcat{min-height:0;padding:20px 12px 20px 0;border-left:0}
  .bigcat:nth-child(even){padding-left:14px;border-left:1px solid var(--line2)}
  .bigcat b{font-size:clamp(64px,19vw,96px)}
  .view-head{margin:3vh 2px 3vh}
}
@media (prefers-reduced-motion:reduce){.js .reveal{opacity:1;transform:none;transition:none}.sw-thumb::after,.live,.sec-h h2 em,.view-head h2 span{animation:none}
  .view.on .view-head,.view.on .card,.view.on .cat,.view.on .cold-groups>*{animation:none}.bc-bar i{transition:none}}

/* 中期狀態 */
.mid-grid{display:grid;gap:14px}
@media (min-width:900px){.mid-grid{grid-template-columns:1fr 1fr}.mid-trend{grid-column:1/-1}}
@media (min-width:1200px){.mid-grid{grid-template-columns:1.05fr 1fr 1fr}.mid-trend{grid-column:auto}}
.mid-grid>.card+.card{margin-top:0}
.mid-card{display:flex;flex-direction:column;gap:12px}
.mid-card .card-head{margin-bottom:0}
.mid-big{display:flex;align-items:center;gap:12px;font:900 clamp(38px,4vw,58px)/1 var(--disp);letter-spacing:-.04em}
.mid-big svg{width:.8em;height:.8em;flex:none;fill:none;stroke:var(--a1);stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round;filter:drop-shadow(0 0 10px var(--a1))}
.mid-desc{margin:0;color:var(--mut);font-size:13.5px}
.mid-row{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:10px 0;border-top:1px solid var(--line);font-size:14px}
.mid-row small{display:block;color:var(--faint);font:500 11px var(--mono);margin-top:2px}
.mid-row .r{text-align:right}.mid-row b{font:700 15px var(--mono)}
.mid-row b.st-up{color:var(--s-bot)}.mid-row b.st-dn{color:var(--s-sig)}
.mid-hits{display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.mid-hits b{font:900 34px/1 var(--disp);letter-spacing:-.03em}.mid-hits b small{font-size:.5em;color:var(--mut)}
.dots{display:flex;gap:5px}.dots i{width:9px;height:9px;border-radius:50%;background:var(--line2)}
.dots i.on{background:var(--a1);box-shadow:0 0 10px var(--a1)}
.mid-status{font-size:13px;padding:9px 12px;border-radius:12px;background:var(--surface2);border:1px solid var(--line)}
.mid-status.on{background:color-mix(in srgb,var(--a1) 16%,transparent);border-color:color-mix(in srgb,var(--a1) 50%,transparent);color:var(--fg);font-weight:600}
.mid-check{display:grid;grid-template-columns:minmax(0,1fr) auto auto 16px;gap:12px;align-items:center;padding:8px 0;border-top:1px solid var(--line);font-size:13px}
.mid-check .v{font:600 13px var(--mono);text-align:right}
.mid-check .t{font:500 11px var(--mono);color:var(--faint);text-align:right;min-width:64px}
.mid-check .ok{color:var(--a1);text-shadow:0 0 8px var(--a1)}.mid-check .no{color:var(--faint)}
.mid-hint{margin:0;font-size:12.5px;color:var(--mut);padding:9px 12px;border-left:2px solid var(--line2)}
.mid-hint.warn{border-left-color:var(--a1);color:var(--fg)}
.mid-stats{margin:auto 0 0;font-size:12.5px;color:var(--mut)}
.mid-chart{margin-top:14px}
.mid-note{margin:12px 2px 0;max-width:980px}
.sec-tag{font:600 11px var(--mono);letter-spacing:.12em;color:var(--mut);padding:8px 14px;border:1px dashed var(--line2);border-radius:999px;white-space:nowrap}
@media (max-width:899px){.mid-check{grid-template-columns:minmax(0,1fr) auto 16px}.mid-check .t{display:none}}

/* 中期分頁：不屬於頂部或底部，隱藏模式切換、使用中性配色 */
body.view-side .sw{visibility:hidden}
@media (max-width:899px){body.view-side .sw{display:none}}
/* 選擇器加重以蓋過深淺色的頂部／底部配色 */
:root body.view-mid.view-mid{--a1:#7c8cff;--a2:#2aa8ff;--a3:#a48bff}
:root[data-theme="light"] body.view-mid.view-mid{--a1:#4f5bd5;--a2:#1f8fe0;--a3:#7c5cd6}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]) body.view-mid.view-mid{--a1:#4f5bd5;--a2:#1f8fe0;--a3:#7c5cd6}}
.mid-grid{margin-top:4px}

/* 中期狀態按鈕：與 01–04 頂底分頁區隔（不編號、分隔線、膠囊外框） */
.tab-sep{width:1px;align-self:stretch;margin:8px 6px;background:var(--line2)}
.tabs-top .tab.tab-mid::before{content:none;counter-increment:none}
.topbar .tabs-top .tab.tab-mid{border:1px dashed var(--line2);border-radius:999px;padding:7px 14px;margin-left:2px}
.tabs-top .tab.tab-mid svg{display:block!important;width:15px;height:15px}
.topbar .tabs-top .tab.tab-mid:hover{border-color:#7c8cff;color:var(--fg)}
.topbar .tabs-top .tab.tab-mid.on{border-style:solid;border-color:transparent;color:#fff;background:linear-gradient(135deg,#7c8cff,#2aa8ff);box-shadow:0 6px 22px rgba(42,168,255,.35)}
.tabs-bottom .tab-sep{margin:10px 2px}
.tabs-bottom .tab.tab-mid{border:1px dashed var(--line2)}
.tabs-bottom .tab.tab-mid.on{border-color:transparent}

/* 週期策略 */
:root body.view-strat.view-strat{--a1:#f5b84c;--a2:#ff7a45;--a3:#ffd36e}
:root[data-theme="light"] body.view-strat.view-strat{--a1:#c98a12;--a2:#e0602a;--a3:#d9a520}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]) body.view-strat.view-strat{--a1:#c98a12;--a2:#e0602a;--a3:#d9a520}}
.topbar .tabs-top .tab.tab-strat:hover{border-color:#f5b84c}
.topbar .tabs-top .tab.tab-strat.on{background:linear-gradient(135deg,#f5b84c,#ff7a45);box-shadow:0 6px 22px rgba(255,122,69,.35)}
.tabs-bottom .tab.tab-strat.on{background:linear-gradient(135deg,#f5b84c,#ff7a45);box-shadow:0 6px 20px rgba(255,122,69,.4)}
.st-top{display:grid;gap:14px}
@media (min-width:900px){.st-top{grid-template-columns:1.3fr 1fr}}
.st-top>.card+.card,.st-bottom>.card+.card{margin-top:0}
.st-card{display:flex;flex-direction:column;gap:10px}
.st-big{font:900 clamp(44px,5vw,72px)/1 var(--disp);letter-spacing:-.04em;background:linear-gradient(90deg,var(--a1),var(--a2));-webkit-background-clip:text;background-clip:text;color:transparent}
.st-cash .st-big{background:linear-gradient(90deg,var(--mut),var(--fg));-webkit-background-clip:text;background-clip:text}
.st-since{margin:0;color:var(--mut);font:500 13px var(--mono)}
.st-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.st-grid div{padding:12px 10px 10px 0}.st-grid div+div{padding-left:12px;border-left:1px solid var(--line)}
.st-grid span{display:block;font:600 10.5px var(--mono);letter-spacing:.08em;color:var(--mut);text-transform:uppercase}
.st-grid b{display:block;font:900 32px/1.1 var(--disp);letter-spacing:-.03em;margin-top:6px}.st-grid b small{font-size:.45em;color:var(--mut)}
.st-grid b.up{color:var(--s-bot)}.st-grid b.dn{color:var(--s-sig)}
.st-next{margin:0;font-size:14px;padding:10px 12px;border-left:2px solid var(--a1);background:color-mix(in srgb,var(--a1) 8%,transparent);border-radius:0 10px 10px 0}
.st-rules ol{margin:10px 0;padding-left:20px}.st-rules li{margin:8px 0;font-size:14px}.st-rules li b{display:inline-block;min-width:5.6em;color:var(--a1)}
.st-chart{margin-top:14px}
.st-bottom{margin-top:14px}
@media (min-width:1200px){.st-bottom{grid-template-columns:1.1fr 1fr}}
.st-ratio{color:var(--a1)}
.st-trades .act{font:700 12px var(--mono);padding:3px 8px;border-radius:6px}
.st-trades .act.sell{color:var(--s-sig);background:color-mix(in srgb,var(--s-sig) 14%,transparent)}
.st-trades .act.buy{color:var(--s-bot);background:color-mix(in srgb,var(--s-bot) 14%,transparent)}
.st-trades tr.bad td{background:color-mix(in srgb,var(--s-sig) 8%,transparent)}
.st-limits{margin-top:14px}.st-limits ul{margin:8px 0 0;padding-left:20px}.st-limits li{font-size:13.5px;margin:6px 0;color:var(--mut)}
@media (max-width:899px){.st-grid{grid-template-columns:1fr 1fr}.st-grid div:nth-child(3){padding-left:0;border-left:0}.st-grid div:nth-child(n+3){border-top:1px solid var(--line)}}
.tabs-bottom .tab{min-width:0}.tabs-bottom .tab span{white-space:nowrap}

:root{--strat:#c98a12}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--strat:#f5b84c}}
:root[data-theme="dark"]{--strat:#f5b84c}
table.data.fit.st-trades th:first-child,table.data.fit.st-trades td:first-child{width:34%}
table.data.fit.st-trades td small{font-family:var(--mono)}
table.data.fit.st-trades th:nth-child(2),table.data.fit.st-trades td:nth-child(2){width:16%}
table.data.fit.st-trades td:last-child{white-space:normal;overflow:visible;line-height:1.35}
@media (max-width:899px){table.data .wd{display:none}}

.tabs-top .tab span{white-space:nowrap}

/* 頁首隨寬度逐步縮減，避免右側工具被擠出畫面 */
@media (min-width:900px) and (max-width:1600px){.brand .sub{display:none}.sw a em{display:none}.appbar-in{gap:14px}
  .topbar .tabs-top .tab{padding:10px 9px}.topbar .tabs-top .tab.tab-mid{padding:7px 12px}.sw a{padding:8px 13px}}
@media (min-width:900px) and (max-width:1360px){.tabs-top .tab.tab-mid span{display:none}.topbar .tabs-top .tab.tab-mid{padding:8px 10px}
  .tabs-top .tab.tab-mid svg{width:17px;height:17px}}
@media (min-width:900px) and (max-width:1150px){.appbar-in{flex-wrap:wrap;row-gap:6px;padding-top:8px;padding-bottom:8px;height:auto;min-height:66px}
  .tabs-top{margin-left:auto}.sw{order:3;flex:1 1 100%;max-width:560px;margin:0 auto 4px}.tools{padding-left:8px}}

/* 全寬：內容隨螢幕撐滿（左右留約 3% 邊距），文字段落維持可讀寬度 */
@media (min-width:900px){.wrap{max-width:none;padding-left:max(28px,3vw);padding-right:max(28px,3vw)}
  .mode-bar{margin-left:calc(-1 * max(28px,3vw));margin-right:calc(-1 * max(28px,3vw))}}
@media (min-width:1200px){.ind-grid{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}.cold-groups .ind-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<canvas id="stars" aria-hidden="true"></canvas><div class="aurora" aria-hidden="true"><i></i><i></i><i></i></div><div class="veil" aria-hidden="true"></div>
<div class="topbar" id="topbar">
__TICKER__
<header class="appbar"><div class="appbar-in">
  <a class="brand" href="#overview" aria-label="__BRAND__ ⟪首頁|home⟫">__LOGO__<div class="brand-txt"><h1><span class="wordmark">__BRAND__</span>__BADGE__</h1><div class="sub">__BRAND_ZH__ · $__PRICE__ · __PRICE_DATE__</div></div></a>
  <nav class="tabs tabs-top" aria-label="⟪分頁|Tabs⟫">__TABS__<i class="tab-ind" aria-hidden="true"></i></nav>
  <div class="sw" role="tablist" aria-label="⟪訊號類型|Signal type⟫"><i class="sw-thumb" aria-hidden="true"></i>
    <a href="#overview" data-mode="top" id="mode-top" role="tab"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 17L11 11l3 3 5-6"/><path d="M14 8h5v5"/></svg><span>⟪頂部訊號|Top signal⟫</span><em>__SIG2__</em></a>
    <a href="#b/overview" data-mode="bottom" id="mode-bottom" role="tab"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7l6 6 3-3 5 6"/><path d="M14 16h5v-5"/></svg><span>⟪底部訊號|Bottom signal⟫</span><em>__BSIG2__</em></a>
  </div>
  <div class="tools">
    <a class="iconbtn lang" id="lang" href="__LANG_HREF__" title="__LANG_TITLE__" aria-label="__LANG_TITLE__">__LANG_LABEL__</a>
    <button class="iconbtn" id="theme" aria-label="⟪切換深淺色|Toggle theme⟫" title="⟪深淺色：深色|Theme: dark⟫"></button>
    <button class="iconbtn" id="help" aria-label="⟪怎麼看這個頁面|How to read this page⟫">?</button>
  </div>
</div></header>
<div class="banners">__BANNERS__</div>
</div>

<main class="wrap">

<section class="view" data-view="overview" aria-label="⟪總覽|Overview⟫">
  <div class="mode" data-mode="top">__HERO_TOP__</div>
  <div class="mode" data-mode="bottom">__HERO_BOTTOM__</div>
  <div class="sec chart-sec reveal" id="sec-history">
    <div class="sec-h"><div><div class="sec-n">HISTORY · __Y0__ — __Y1__</div><h2><span class="tb-top">__YEARS__<em>⟪潮汐|tides⟫</em></span><span class="tb-bot">⟪每一次|Every⟫<em>⟪退潮|ebb⟫</em></span></h2></div>
      <div class="seg" data-g="main"><button data-y="0" class="on">⟪全部|All⟫</button><button data-y="8">⟪8 年|8Y⟫</button><button data-y="4">⟪4 年|4Y⟫</button><button data-y="1">⟪1 年|1Y⟫</button></div></div>
    <div class="tip" id="tip-main"></div>
    <svg class="chart" id="c-main" height="320" role="img" aria-label="⟪訊號與價格歷史|Signal and price history⟫"></svg>
    <div class="legend" id="legend-main">
      <button data-s="sig"><i style="background:var(--s-sig)"></i>⟪頂部訊號|Top signal⟫</button>
      <button data-s="heat"><i style="background:var(--s-heat)"></i>⟪熱度|Heat⟫</button>
      <button data-s="tim"><i style="height:0;background:none;border-top:2px dashed var(--s-tim)"></i>⟪時機|Timing⟫</button>
      <button data-s="bsig"><i style="background:var(--s-bot)"></i>⟪底部訊號|Bottom signal⟫</button>
      <button data-s="cold"><i style="background:var(--s-cold)"></i>⟪冷度|Coldness⟫</button>
      <span class="static"><i class="area"></i>⟪BTC 價格（右軸・對數）|BTC price (right axis, log)⟫</span>
      <span class="static mk-top"><i class="dash"></i>⟪過去頂部|Past tops⟫</span>
      <span class="static mk-bot"><i class="dash bot"></i>⟪過去底部|Past bottoms⟫</span>
      <span class="static mk-bot"><i class="dash bot dot"></i>⟪本輪低點（待驗證）|Cycle low (unconfirmed)⟫</span>
    </div>
    <p class="muted small" style="margin:10px 0 0">⟪左軸為分數（0–100），右軸為 BTC 價格（對數）。兩者刻度不同，線條交叉沒有意義。虛線為 __WIN__ 與 __ALERT__ 門檻。點圖例開關線條；切換頂部／底部時會換成對應的預設線條。|Left axis: scores (0–100); right axis: BTC price (log). The scales differ, so line crossings mean nothing. Dashed lines mark the __WIN__ and __ALERT__ thresholds. Tap the legend to toggle lines; switching top/bottom swaps in the matching default lines.⟫</p>
    </div>
  <div class="mode" data-mode="top">
  <div class="sec reveal">
    <div class="sec-h"><div><div class="sec-n">HEAT BY CATEGORY</div><h2>⟪各類|Heat by⟫<em>⟪熱度|category⟫</em></h2></div><a class="sec-link" href="#heat">⟪全部指標|All indicators⟫ →</a></div>
    __BIGCATS__
  </div>
  <div class="sec reveal">
    <div class="sec-h"><div><div class="sec-n">CYCLE POSITION</div><h2>⟪週期|Cycle⟫<em>⟪位置|position⟫</em></h2></div><a class="sec-link" href="#timing">⟪時機詳情|Timing details⟫ →</a></div>
    <div class="card">__TIMELINE__</div>
  </div>
  </div>
  <div class="mode" data-mode="bottom">__BOTTOM_OVERVIEW__
  </div>
</section>

<section class="view" data-view="timing" aria-label="⟪時機|Timing⟫">
  <div class="mode" data-mode="top">
  <div class="view-head"><div class="sec-n">02 — ⟪時機|TIMING⟫</div><h2>⟪頂部時機|Top timing⟫ <span>__TIM__</span></h2><p>⟪兩個時鐘各自 0–100，取平均。紫點是過去四次頂部；色帶是窗口（深色滿分、淺色有分數）。|Two clocks, each 0–100, averaged. Purple dots are the four past tops; the band is the window (dark = full score, light = partial).⟫</p></div>
  <div class="grid g-tim">__TIMING__</div>
  </div>
  <div class="mode" data-mode="bottom">
  <div class="view-head"><div class="sec-n">02 — ⟪時機|TIMING⟫</div><h2>⟪底部時機|Bottom timing⟫ <span>__BTIM__</span></h2><p>⟪兩個時鐘各自 0–100，取平均。洋紅點是過去三次底部；色帶是窗口（深色滿分、淺色有分數）。|Two clocks, each 0–100, averaged. Magenta dots are the three past bottoms; the band is the window (dark = full score, light = partial).⟫</p></div>
  <div class="grid g-tim">__BTIMING__</div>
  </div>
</section>

<section class="view" data-view="heat" aria-label="⟪熱度|Heat⟫">
  <div class="mode" data-mode="top">
  <div class="view-head"><div class="sec-n">03 — ⟪熱度|HEAT⟫</div><h2>⟪熱度|Heat⟫ <span class="__HEAT_BAND__">__HEAT__</span></h2><p>⟪__CATLIST____NCAT_TEXT__加權平均。週期法用過去頂部推估本輪預期頂部；百分位法超過 __PIVOT__% 才計分；單一指標加總上限 120。點任一指標看說明與歷史走勢。|Weighted average of __NCAT_TEXT__: __CATLIST__. The cycle method projects this cycle's expected top from past tops; percentile indicators only score above __PIVOT__%; each indicator is capped at 120. Tap any indicator for details and history.⟫</p></div>
  __CATS__
  </div>
  <div class="mode" data-mode="bottom">
  <div class="view-head"><div class="sec-n">03 — ⟪冷度|COLDNESS⟫</div><h2>⟪冷度|Coldness⟫ <span class="cool-t">__COLD_SCORE__</span></h2><p>⟪估值、礦工、價格結構三組加權平均。冷度 100 代表達到本輪推估的底部水準，0 代表在中性以上。點任一指標看說明與歷史走勢。|Weighted average of three groups: valuation, miners and price structure. 100 means this cycle's projected bottom level; 0 means neutral or above. Tap any indicator for details and history.⟫</p></div>
  <div class="cold-groups">__COLD__</div>
  </div>
</section>

<section class="view" data-view="data" aria-label="⟪數據|Data⟫">
  <div class="view-head"><div class="sec-n">04 — ⟪數據|DATA⟫</div><h2>⟪數據|Data⟫</h2><p>⟪最近 30 天每日數值與完整資料下載。|Daily values for the last 30 days, plus full downloads.⟫</p></div>
  <div class="mode" data-mode="top"><div class="card"><div class="card-head"><div><div class="eyebrow">TOP</div><h3>⟪頂部相關|Top signals⟫</h3></div></div><div class="scroll">__TABLE__</div></div></div>
  <div class="mode" data-mode="bottom"><div class="card"><div class="card-head"><div><div class="eyebrow">BOTTOM</div><h3>⟪底部相關|Bottom signals⟫</h3></div></div><div class="scroll">__BTABLE__</div></div></div>
  <div class="card">
    <div class="card-head"><div><div class="eyebrow">DOWNLOAD</div><h3>⟪完整資料|Full data⟫</h3></div></div>
    <div class="dl">
      <a href="__JSON_HREF__">latest.json<span>⟪今日完整數據|Today, full detail⟫ ›</span></a>
      <a href="__CSV_SCORES__">scores.csv<span>⟪每日分數|Daily scores⟫ ›</span></a>
      <a href="__CSV_IND__">indicators.csv<span>⟪每日指標|Daily indicators⟫ ›</span></a>
      <a href="__CSV_RAW__">⟪原始資料|Raw data⟫<span>⟪各資料源|Per source⟫ ›</span></a>
    </div>
  </div>
  <footer>⟪資料來源：|Sources: ⟫Coin Metrics Community (CC BY-NC 4.0), DefiLlama, TFTC ⟪（ETF 資金流，CC BY 4.0）|(ETF flows, CC BY 4.0)⟫, OKX, Binance, Coinbase, alternative.me__EXTRA_SRC__.<br>
  ⟪僅使用公開數據，不含任何個人資訊或交易功能；僅供參考，不構成投資建議。|Public data only; no personal information or trading features. For reference only — not investment advice.⟫<br>
  <a href="__REPO__">⟪原始碼與方法說明|Source code &amp; methodology⟫</a> · ⟪產生時間|Generated⟫ __GENERATED__</footer>
</section>

<section class="view" data-view="mid" aria-label="⟪中期狀態|Market state⟫">
__MIDTERM__
</section>

<section class="view" data-view="strat" aria-label="⟪週期策略|Cycle strategy⟫">
__STRATEGY__
</section>
</main>

<nav class="tabs tabs-bottom" aria-label="⟪分頁|Tabs⟫">__TABS__</nav>

<div class="sheet-wrap" id="sheet" hidden>
  <div class="backdrop" data-close></div>
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
    <div class="grab"></div><button class="iconbtn x" data-close aria-label="⟪關閉|Close⟫">✕</button>
    <div id="sheet-body"></div>
  </div>
</div>

<template id="tpl-help"><div class="guide">
  <div class="sh-title" id="sheet-title">⟪怎麼看這個頁面|How to read this page⟫</div>
  <p>⟪<b>頂部訊號</b>是主要數字。只有「市場夠熱」而且「時間進入歷史上的頂部窗口」時才會升高，兩者缺一不可。|The <b>top signal</b> is the headline number. It rises only when the market is hot <i>and</i> the calendar is inside the historical top window — both are required.⟫</p>
  <div class="callout">⟪頂部訊號 = 熱度（7 日均）× 時機 ÷ 100<br>≥ __WIN__ 頂部窗口　·　≥ __ALERT__ 高度警戒|Top signal = heat (7d avg) × timing ÷ 100<br>≥ __WIN__ top window　·　≥ __ALERT__ high alert⟫</div>
  <h3>⟪熱度（0–100）|Heat (0–100)⟫</h3><p>⟪__CATLIST____NCAT_TEXT__指標的加權平均，回答「市場現在有多熱」。冷 &lt; 40 ≤ 溫 &lt; 65 ≤ 熱。|Weighted average of __NCAT_TEXT__ (__CATLIST__): how hot is the market right now? Cold &lt; 40 ≤ warm &lt; 65 ≤ hot.⟫</p>
  <h3>⟪時機（0–100）|Timing (0–100)⟫</h3><p>⟪比較「距減半天數」與「距本輪低點天數」和過去頂部的距離，回答「時間上像不像週期頂部」。過去三次頂部約在減半後 __CENTER_H__ 天、低點後 __CENTER_L__ 天。|Compares days since halving and days since the cycle low with past tops: does the calendar look like a cycle top? The last three tops came about __CENTER_H__ days after the halving and __CENTER_L__ days after the low.⟫</p>
  <h3>⟪為什麼要乘上時機？|Why multiply by timing?⟫</h3><p>⟪只看熱度時，2021-04、2024-03 這些中段高點的熱度其實比真正的週期頂部（2021-11、2025-10）還高。最終頂部的特徵是時間點很規律：最近三次都在減半後 525–546 天、低點後約 1,060 天。加入時機後，最近三輪的最終頂部都成為該輪訊號最高的時候。|On heat alone, mid-cycle highs such as 2021-04 and 2024-03 ran hotter than the real cycle tops (2021-11, 2025-10). What final tops share is timing: the last three came 525–546 days after the halving and about 1,060 days after the low. With timing included, each of the last three final tops is its cycle's highest signal.⟫</p>
  <h3>⟪底部訊號（切換到「底部訊號」模式）|Bottom signal (switch to “Bottom signal” mode)⟫</h3>
  <div class="callout">⟪底部訊號 = 冷度（7 日均）× 底部時機 ÷ 100<br>≥ __BWIN__ 底部區　·　≥ 70 強烈底部|Bottom signal = coldness (7d avg) × bottom timing ÷ 100<br>≥ __BWIN__ bottom zone　·　≥ 70 strong bottom⟫</div>
  <p>⟪<b>冷度</b>：估值（MVRV、NUPL）50%、礦工（Puell、Hash Ribbons）30%、價格結構（AHR999、Power Law）20%。100 代表達到本輪推估的底部水準。|<b>Coldness</b>: valuation (MVRV, NUPL) 50%, miners (Puell, Hash Ribbons) 30%, price structure (AHR999, Power Law) 20%. 100 means this cycle's projected bottom level.⟫</p>
  <p>⟪<b>底部時機</b>：距上次頂部天數（過去底部平均約 379 天）與距上次減半天數（約 859 天）。|<b>Bottom timing</b>: days since the last top (past bottoms averaged ~379) and days since the last halving (~859).⟫</p>
  <p>⟪參數只依 2015、2018、2022 三次底部與中段假底部決定，本輪（2026）是樣本外檢驗；「週期結構驗證」會追蹤本輪低點是否就是週期底部。切換模式後，時機、熱度（冷度）、數據各頁都會換成對應內容。|Parameters were set only from the 2015, 2018 and 2022 bottoms and mid-cycle false bottoms, so this cycle (2026) is an out-of-sample test. The “cycle structure test” tracks whether this cycle's low is the bottom. Switching modes swaps the Timing, Heat/Cold and Data tabs to match.⟫</p>
  <h3>⟪中期狀態（「中期」分頁）|Market state (“Market” tab)⟫</h3>
  <p>⟪<b>趨勢環境</b>：價格相對 200 日均線、20 週均線（牛市支撐帶）、50 日均線，以及週線 Supertrend（ATR 10 × 3）的方向與支撐／壓力位。|<b>Trend</b>: price versus the 200-day MA, the 20-week MA (bull-market support band) and the 50-day MA, plus the weekly Supertrend (ATR 10 × 3) direction and its support/resistance level.⟫</p>
  <p>⟪<b>牛市回調觀察</b>：價格在 200 日均線之上時，日 RSI&lt;35、低於 50 日均線 10%、30 日跌逾 15%、恐懼貪婪&lt;25、資金費率 ≤0，五項符合三項即觸發。<b>短線過熱</b>為對應的五個相反條件。|<b>Dip watch</b>: with price above the 200-day MA, it triggers when 3 of 5 hold — daily RSI&lt;35, 10% below the 50-day MA, down 15%+ in 30 days, Fear &amp; Greed&lt;25, funding ≤0. <b>Overheating</b> uses the five opposite conditions.⟫</p>
  <p>⟪研究結果：過熱不是可靠的賣訊號（單一指標過熱之後平均仍續漲，組合過熱之後好壞參半）；牛市回調有小幅優勢但次數少；Supertrend 屬確認型。這一區只幫助看清目前狀態，證據比頂部／底部訊號弱。|Findings: overheating is not a reliable sell signal (single overheated indicators were on average followed by further gains; combined overheating had mixed outcomes); bull-market dips showed a small edge with few occurrences; the Supertrend confirms rather than predicts. This section helps read the current state; its evidence is weaker than the top/bottom signals.⟫</p>
  <h3>⟪週期策略（「週期策略」頁）|Cycle strategy (“Strategy” tab)⟫</h3>
  <p>⟪持有中，頂部訊號或頂部時機 ≥ 50 進入警戒，警戒中週線 Supertrend 轉空就賣出；空手時，底部訊號 ≥ 50 或 Supertrend 轉多就買回。頁面顯示目前狀態、逐輪回測（不偷看未來）的模擬資金曲線與歷史交易。|While holding, top signal or top timing ≥ 50 puts it on alert, and a weekly Supertrend down-turn on alert sells; in cash, bottom signal ≥ 50 or a Supertrend up-turn buys back. The tab shows the current state, a walk-forward (no look-ahead) simulated equity curve and past trades.⟫</p>
  <h3>⟪限制|Limitations⟫</h3><ul>
    <li>⟪時機假設約四年的週期會延續；週期若變長或變短，訊號可能提早、延後甚至整輪不亮，請同時看熱度與時機。|Timing assumes the ~4-year cycle continues. If cycles stretch or shrink, signals may come early, late, or not at all — watch heat and timing separately too.⟫</li>
    <li>⟪訊號是「幾個月的窗口」，不是精確的頂部日期。|Signals mark a window of months, not an exact top date.⟫</li>
    <li>⟪歷史訊號以目前參數回推（樣本內），過去只有 4 次頂部可驗證。|Historical signals use today's parameters (in-sample); there are only 4 past tops to test against.⟫</li>
    <li>⟪僅供參考，不構成投資建議。|For reference only — not investment advice.⟫</li></ul>
</div></template>

<script>
document.documentElement.classList.add('js');
const MID=__MID_EVENTS__,STR=__STRAT_TRADES__;
const D=__DATA__,IND=__IND__,TOPS=__TOPS__,BOTTOMS=__BOTTOMS__,CUR_LOW=__CUR_LOW__,WIN=__WIN__,ALERT=__ALERT__;
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const TS=D.d.map(d=>Date.parse(d));  /* 橫軸依實際日期（資料一年前每週一點、最近一年每日一點） */
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const st={strat:{years:2014,hover:null},mid:{years:2,hover:null},main:{years:0,hover:null,hide:new Set(),p:0},ind:{years:0,hover:null,k:null},mode:'top',modeApplied:null};
function i0of(y){if(!y)return 0;const c=new Date(D.d[D.d.length-1]);c.setFullYear(c.getFullYear()-y);const s=c.toISOString().slice(0,10);return Math.max(0,D.d.findIndex(x=>x>=s));}
function niceTicks(lo,hi){const span=hi-lo,step=10**Math.floor(Math.log10(span/3)),m=[1,2,5,10].find(k=>span/(k*step)<=5)*step,out=[];for(let v=Math.ceil(lo/m)*m;v<=hi;v+=m)out.push(+v.toFixed(10));return out;}
function short(v){const a=Math.abs(v);return a>=1e6?(v/1e6)+'M':a>=1e3?(v/1e3)+'k':+v.toFixed(3)+'';}
function chart(el,i0,series,o){
  const W=el.clientWidth,H=+el.getAttribute('height'),L=44,R=o.bg?50:10,T=10,B=o.axis?24:8,n=D.d.length-i0;
  if(!W)return;el.dataset.l=L;el.dataset.r=R;
  const t0=TS[i0],t1=TS[D.d.length-1],x=i=>L+(W-L-R)*(TS[i0+i]-t0)/Math.max(1,t1-t0);
  let lo=o.min,hi=o.max;
  if(lo==null||hi==null){const v=[];series.forEach(s=>s.a.slice(i0).forEach(z=>{if(z!=null&&(!o.log||z>0))v.push(o.log?Math.log10(z):z)}));
    if(!v.length){el.innerHTML=`<text x="${W/2}" y="${H/2}" font-size="12" text-anchor="middle" fill="${css('--mut')}">⟪無資料|No data⟫</text>`;return;}
    lo=Math.min(...v);hi=Math.max(...v);if(lo===hi){lo-=1;hi+=1;}if(!o.log){const p=(hi-lo)*.08;lo-=p;hi+=p;}}
  const y=v=>{const tv=Math.min(Math.max(o.log?Math.log10(v):v,lo),hi);return T+(H-T-B)*(1-(tv-lo)/(hi-lo));};
  let g=`<defs><filter id="gl-${el.id}" x="-5%" y="-30%" width="110%" height="160%"><feGaussianBlur stdDeviation="3.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;const grid=css('--line'),mut=css('--faint');
  const ticks=o.ticks?[...o.ticks]:(o.log?[]:niceTicks(lo,hi));
  if(o.log){if(hi-lo<1.3)niceTicks(10**lo,10**hi).forEach(v=>ticks.push(v));else for(let e=Math.ceil(lo);e<=hi;e++)ticks.push(10**e);}
  ticks.forEach(v=>{const yy=y(v);g+=`<line x1="${L}" x2="${W-R}" y1="${yy}" y2="${yy}" stroke="${grid}"/><text x="${L-6}" y="${yy+4}" font-size="11" text-anchor="end" fill="${mut}">${o.log?(v>=1000?(+(v/1000).toFixed(1))+'k':v):short(v)}</text>`;});
  (o.thresholds||[]).forEach(v=>{g+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="${css('--mut')}" stroke-dasharray="3 4" opacity=".7"/>`;});
  (o.marks||[{d:TOPS,c:'--topline',dash:'3 3',op:.6}]).forEach(m=>m.d.forEach(t=>{const i=D.d.findIndex(v=>v>=t)-i0;if(i>0&&i<n)g+=`<line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${H-B}" stroke="${css(m.c)}" stroke-dasharray="${m.dash}" opacity="${m.op}"/>`;}));
  const rv=o.reveal==null?1:o.reveal,cw=L+(W-L-R)*rv;
  if(rv<1)g+=`<clipPath id="cp-${el.id}"><rect x="0" y="0" width="${cw}" height="${H}"/></clipPath>`;
  g+=rv<1?`<g clip-path="url(#cp-${el.id})">`:'<g>';
  let y2=null;
  if(o.bg){/* 背景價格層：獨立的對數刻度，佔滿圖高，刻度標在右側 */
    const pv=o.bg.a.slice(i0).filter(z=>z!=null&&z>0).map(Math.log10),plo=Math.min(...pv),phi=Math.max(...pv),pad=(phi-plo)*.04;
    const a=plo-pad,b=phi+pad;y2=v=>T+(H-T-B)*(1-(Math.log10(v)-a)/(b-a));
    const st10=(b-a)>3?1:(b-a)>1.2?0.5:0.25,pc=css('--price');
    for(let e=Math.ceil(a/st10)*st10;e<=b;e+=st10){const v=10**e,lab=v>=1e3?Math.round(v/1e3)+'k':Math.round(v);g+=`<text x="${W-R+6}" y="${y2(v)+4}" font-size="10.5" fill="${pc}" opacity=".85">${lab}</text>`;}
    let d='',first=-1;o.bg.a.slice(i0).forEach((v,i)=>{if(v==null||v<=0)return;if(first<0)first=i;d+=(d?'L':'M')+x(i).toFixed(1)+','+y2(v).toFixed(1);});
    if(d){g+=`<path d="${d}L${x(n-1)},${H-B}L${x(first)},${H-B}Z" fill="${pc}" opacity=".10"/><path d="${d}" fill="none" stroke="${pc}" stroke-width="1.4" opacity=".55" stroke-linejoin="round"/>`;}}
  if(o.axis){const y0=+D.d[i0].slice(0,4),y1=+D.d[D.d.length-1].slice(0,4),s=Math.max(1,Math.ceil((y1-y0)/6));
    for(let yr=y0+1;yr<=y1;yr+=s){const i=D.d.findIndex(v=>v>=yr+'-01-01')-i0;if(i>0)g+=`<text x="${x(i)}" y="${H-6}" font-size="11" text-anchor="middle" fill="${mut}">${yr}</text>`;}}
  series.forEach(s=>{if(s.hide)return;let d='',pen=false;s.a.slice(i0).forEach((v,i)=>{if(v==null||(o.log&&v<=0)){pen=false;return;}d+=(pen?'L':'M')+x(i).toFixed(1)+','+y(v).toFixed(1);pen=true;});
    if(s.fill&&d){const first=s.a.slice(i0).findIndex(v=>v!=null);g+=`<path d="${d}L${x(n-1)},${H-B}L${x(first)},${H-B}Z" fill="${css(s.c)}" opacity=".08"/>`;}
    g+=`<path d="${d}" fill="none" stroke="${css(s.c)}" stroke-width="${s.w||2}" stroke-linejoin="round" stroke-linecap="round"${s.dash?` stroke-dasharray="${s.dash}"`:''}${s.glow?` filter="url(#gl-${el.id})"`:''}/>`;});
  g+='</g>';
  if(rv<1)g+=`<line class="scan" x1="${cw}" x2="${cw}" y1="${T}" y2="${H-B}" stroke="${cssb('--a1')}" stroke-width="2" filter="url(#gl-${el.id})"/>`;
  const h=o.hover;if(h!=null&&h<n){g+=`<line x1="${x(h)}" x2="${x(h)}" y1="${T}" y2="${H-B}" stroke="${css('--fg')}" opacity=".3"/>`;
    if(y2&&o.bg.a[i0+h]>0)g+=`<circle cx="${x(h)}" cy="${y2(o.bg.a[i0+h])}" r="3.5" fill="${css('--price')}" stroke="${css('--surface')}" stroke-width="2"/>`;
    series.forEach(s=>{const v=s.a[i0+h];if(!s.hide&&v!=null&&(!o.log||v>0))g+=`<circle cx="${x(h)}" cy="${y(v)}" r="4.5" fill="${css(s.c)}" stroke="${css('--surface')}" stroke-width="2"/>`;});}
  el.innerHTML=g;
}
function nearest(i0,t){let a=i0,b=TS.length-1;while(b-a>1){const m=(a+b)>>1;TS[m]<t?a=m:b=m;}return (t-TS[a]<=TS[b]-t?a:b)-i0;}
function bind(els,g,i0fn,draw){const mv=ev=>{const el=ev.currentTarget,L=+(el.dataset.l||44),R=+(el.dataset.r||10),r=el.getBoundingClientRect(),cx=(ev.touches?ev.touches[0].clientX:ev.clientX)-r.left,i0=i0fn();
  const f=Math.max(0,Math.min(1,(cx-L)/(el.clientWidth-L-R)));st[g].hover=nearest(i0,TS[i0]+f*(TS[TS.length-1]-TS[i0]));draw();};
  els.forEach(e=>{if(!e)return;e.onmousemove=mv;e.ontouchmove=mv;e.ontouchstart=mv;e.onmouseleave=()=>{st[g].hover=null;draw();};});}
const f0=v=>v==null?'—':Math.round(v);
function mainMarks(){return st.mode==='bottom'?[{d:BOTTOMS,c:'--botline',dash:'3 3',op:.75},{d:[CUR_LOW],c:'--botline',dash:'1 4',op:.55}]:[{d:TOPS,c:'--topline',dash:'3 3',op:.6}];}
function drawMain(){const s=st.main,i0=i0of(s.years),mk=mainMarks();$('#c-main').setAttribute('height',chartH(320,.6));
  chart($('#c-main'),i0,[{a:D.tim,c:'--s-tim',w:1.6,dash:'5 4',hide:s.hide.has('tim')},{a:D.heat,c:'--s-heat',w:1.7,hide:s.hide.has('heat')},{a:D.cold,c:'--s-cold',w:1.6,hide:s.hide.has('cold')},{a:D.bsig,c:'--s-bot',w:2.4,fill:true,glow:true,hide:s.hide.has('bsig')},{a:D.sig,c:'--s-sig',w:2.6,fill:true,glow:true,hide:s.hide.has('sig')}],{min:0,max:100,ticks:[0,25,50,75,100],thresholds:[WIN,ALERT],axis:true,hover:s.hover,marks:mk,bg:{a:D.p},reveal:s.p});
  const j=i0+(s.hover==null?D.d.length-1-i0:s.hover);
  $('#tip-main').innerHTML=`<b>${D.d[j]}</b><span>${D.p[j]==null?'—':'$'+Math.round(D.p[j]).toLocaleString()}</span><span>⟪訊號|Top⟫ <b>${f0(D.sig[j])}</b></span><span>⟪熱度|Heat⟫ <b>${f0(D.heat[j])}</b></span><span>⟪時機|Timing⟫ <b>${f0(D.tim[j])}</b></span><span>⟪底部|Bottom⟫ <b>${f0(D.bsig[j])}</b></span><span>⟪冷度|Cold⟫ <b>${f0(D.cold[j])}</b></span>`;}
/* 圖表高度：桌機依視窗高度（360–820px），寬螢幕下不會顯得扁 */
function chartH(mobile,k){return innerWidth>=900?Math.round(Math.max(360,Math.min(820,innerHeight*k,innerWidth*.42))):mobile;}
function drawMid(){const el=$('#c-mid');if(!el||!D.ma200)return;const s=st.mid,i0=i0of(s.years);el.setAttribute('height',chartH(280,.5));
  const up=D.stl.map((v,i)=>D.std[i]>0?v:null),dn=D.stl.map((v,i)=>D.std[i]<0?v:null),since=D.d[i0];
  chart(el,i0,[{a:D.ma50,c:'--s-tim',w:1.2},{a:D.ma20w,c:'--s-cold',w:1.5,dash:'5 4'},{a:D.ma200,c:'--s-heat',w:1.6},{a:up,c:'--s-bot',w:2.4,glow:true},{a:dn,c:'--s-sig',w:2.4,glow:true},{a:D.p,c:'--fg',w:1.6}],
    {log:true,axis:true,hover:s.hover,marks:[{d:MID.dip.filter(x=>x>=since),c:'--s-bot',dash:'2 4',op:.8},{d:MID.hot.filter(x=>x>=since),c:'--a3',dash:'2 4',op:.8}]});
  const j=i0+(s.hover==null?D.d.length-1-i0:s.hover),m=v=>v==null?'—':'$'+Math.round(v).toLocaleString();
  $('#tip-mid').innerHTML=`<b>${D.d[j]}</b><span>${m(D.p[j])}</span><span>Supertrend <b>${D.std[j]==null?'—':(D.std[j]>0?'⟪多|Up⟫ ':'⟪空|Down⟫ ')+m(D.stl[j])}</b></span><span>⟪200 日|200D⟫ <b>${m(D.ma200[j])}</b></span><span>⟪20 週|20W⟫ <b>${m(D.ma20w[j])}</b></span><span>⟪50 日|50D⟫ <b>${m(D.ma50[j])}</b></span>`;}
function drawStrat(){const el=$('#c-strat');if(!el||!D.seq)return;const s=st.strat;el.setAttribute('height',chartH(300,.55));
  const i0=Math.max(0,D.d.findIndex(x=>x>=s.years+'-01-01')),bs=(STR.base||{})[s.years]||[D.seq[i0],D.sbh[i0]],b1=bs[0],b2=bs[1],since=D.d[i0];
  const a=D.seq.map((v,i)=>i<i0||v==null?null:v/b1),b=D.sbh.map((v,i)=>i<i0||v==null?null:v/b2);
  chart(el,i0,[{a:b,c:'--price',w:1.6},{a:a,c:'--strat',w:2.6,glow:true}],{log:true,axis:true,hover:s.hover,
    marks:[{d:STR.sell.filter(x=>x>=since),c:'--s-sig',dash:'2 4',op:.85},{d:STR.buy.filter(x=>x>=since),c:'--s-bot',dash:'2 4',op:.85}]});
  const j=i0+(s.hover==null?D.d.length-1-i0:s.hover),f=v=>v==null?'—':(v>=100?Math.round(v).toLocaleString():v.toFixed(2))+'×';
  $('#tip-strat').innerHTML=`<b>${D.d[j]}</b><span>⟪策略|Strategy⟫ <b>${f(a[j])}</b></span><span>⟪持有|Hold⟫ <b>${f(b[j])}</b></span><span>${D.p[j]==null?'':'$'+Math.round(D.p[j]).toLocaleString()}</span>`;}
function drawInd(){const s=st.ind,k=s.k;if(!k)return;const i0=i0of(s.years),v=D['v_'+k],sc=D['s_'+k],m=IND[k];
  chart($('#c-val'),i0,[{a:v,c:'--s-heat',w:1.8}],{hover:s.hover});
  if(sc)chart($('#c-sc'),i0,[{a:sc,c:k.startsWith('cold_')?'--s-cold':'--s-sig',w:1.8,fill:true}],{min:0,max:120,ticks:[0,40,80,120],axis:true,hover:s.hover});
  const j=i0+(s.hover==null?D.d.length-1-i0:s.hover),fmt=x=>x==null?'—':(Math.abs(x)>=1000?Math.round(x).toLocaleString():Math.abs(x)>=1?x.toFixed(2):x.toFixed(3));
  $('#tip-ind').innerHTML=`<b>${D.d[j]}</b><span>⟪數值|Value⟫ <b>${fmt(v[j])}${m.unit&&m.unit!=='x'?' '+m.unit:m.unit}</b></span>`+(sc?`<span>⟪分數|Score⟫ <b>${f0(sc[j])}</b></span>`:'');}
/* 抽屜 */
let lastFocus=null;
function openSheet(html,after){lastFocus=document.activeElement;$('#sheet-body').innerHTML=html;$('#sheet').hidden=false;document.body.style.overflow='hidden';$('#sheet .x').focus();after&&requestAnimationFrame(after);}
function closeSheet(){$('#sheet').hidden=true;document.body.style.overflow='';st.ind.k=null;lastFocus&&lastFocus.focus();}
$$('[data-close]').forEach(e=>e.onclick=closeSheet);
addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#sheet').hidden)closeSheet();});
$('#help').onclick=()=>openSheet($('#tpl-help').innerHTML);
$('#lang').onclick=e=>{e.preventDefault();try{localStorage.setItem('lang','⟪en|zh⟫');}catch(_){}
  /* 本機直接開檔（file://）不會自動補 index.html，要寫完整路徑 */
  location.href='⟪en/|../⟫'+(location.protocol==='file:'?'index.html':'')+location.hash;};
const THEME_ICON={auto:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16z" fill="currentColor"/></svg>',
  light:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  dark:'<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>'};
const THEME_TEXT={auto:'⟪自動（跟隨系統）|Auto (system)⟫',light:'⟪淺色|Light⟫',dark:'⟪深色|Dark⟫'};
function setTheme(t,save){if(t==='auto')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=t;
  const dark=t==='dark'||(t==='auto'&&matchMedia('(prefers-color-scheme: dark)').matches);$('#theme-color').setAttribute('content',dark?'#0b0d10':'#f3f4f6');
  $('#theme').innerHTML=THEME_ICON[t];$('#theme').title='⟪深淺色：|Theme: ⟫'+THEME_TEXT[t];$('#theme').setAttribute('aria-label','⟪深淺色：|Theme: ⟫'+THEME_TEXT[t]+'⟪（點擊切換）| (tap to change)⟫');
  if(save){try{localStorage.setItem('theme',t);}catch(e){}}requestAnimationFrame(redraw);}
setTheme(THEME0,false);
$('#theme').onclick=()=>{const order=['dark','light','auto'],cur=document.documentElement.dataset.theme||'auto';setTheme(order[(order.indexOf(cur)+1)%3],true);};
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(!document.documentElement.dataset.theme)setTheme('auto',false);});
function openInd(k){const m=IND[k];st.ind={years:0,hover:null,k};
  openSheet(`<div class="sh-cat">${m.cat}</div><div class="sh-title" id="sheet-title">${m.label}</div>
  <div class="sh-kpis"><div><span>⟪目前數值|Current value⟫ (${m.asOf})</span><b>${m.value}</b></div><div><span>⟪分數|Score⟫</span><b class="${m.band}">${m.score==null?'—':m.score}</b></div></div>
  <p class="sh-p">${m.desc}</p><p class="sh-m">${m.method}${m.stale?'　·　⚠ ⟪舊資料|Stale⟫':''}</p>
  <div class="chart-top"><div class="seg" data-g="ind"><button data-y="0" class="on">⟪全部|All⟫</button><button data-y="4">⟪4 年|4Y⟫</button><button data-y="1">⟪1 年|1Y⟫</button></div></div>
  <div class="tip" id="tip-ind"></div><svg class="chart" id="c-val" height="160" role="img" aria-label="⟪指標數值歷史|Indicator value history⟫"></svg>
  ${D['s_'+k]?'<svg class="chart" id="c-sc" height="120" role="img" aria-label="⟪指標分數歷史|Indicator score history⟫"></svg>':''}`,()=>{bindSeg();bind([$('#c-val'),$('#c-sc')],'ind',()=>i0of(st.ind.years),drawInd);drawInd();});}
$$('.ind').forEach(b=>b.onclick=()=>openInd(b.dataset.k));
function bindSeg(){$$('.seg').forEach(box=>box.querySelectorAll('button').forEach(b=>b.onclick=()=>{box.querySelectorAll('button').forEach(o=>o.classList.remove('on'));b.classList.add('on');const g=box.dataset.g;st[g].years=+b.dataset.y;st[g].hover=null;g==='main'?animMain():g==='mid'?drawMid():g==='strat'?drawStrat():drawInd();}));}
$$('#legend-main button').forEach(b=>b.onclick=()=>{const k=b.dataset.s,h=st.main.hide;h.has(k)?h.delete(k):h.add(k);b.classList.toggle('off');drawMain();});
/* ===== 極光潮汐動效：星空、液態大數字、首屏波浪（只動畫可見的首屏） ===== */
const RM=matchMedia('(prefers-reduced-motion: reduce)').matches;
const cssb=n=>getComputedStyle(document.body).getPropertyValue(n).trim();
const SC=$('#stars'),SX=SC.getContext('2d');let STARS=[];
function initStars(){const r=devicePixelRatio||1;SC.width=innerWidth*r;SC.height=innerHeight*r;
  STARS=Array.from({length:Math.round(Math.min(200,innerWidth/7))},()=>({x:Math.random()*SC.width,y:Math.random()*SC.height*.85,r:(.3+Math.random()*.9)*r,p:Math.random()*6.28}));drawStars(0);}
function drawStars(t){SX.clearRect(0,0,SC.width,SC.height);SX.fillStyle='#fff';for(const s of STARS){SX.globalAlpha=.18+.5*Math.abs(Math.sin(t/1700+s.p));SX.beginPath();SX.arc(s.x,s.y,s.r,0,6.28);SX.fill();}}
function activeHero(){return document.querySelector(`.view.on[data-view="overview"] .mode[data-mode="${st.mode}"] .hero2`);}
/* 量出數字墨跡的上下緣（行內元素背景畫在內容區，基線距頂 = fontBoundingBoxAscent） */
const INK=document.createElement('canvas').getContext('2d');
function inkBox(el){const cs=getComputedStyle(el);INK.font=`${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;const m=INK.measureText(el.textContent||'0'),base=m.fontBoundingBoxAscent;
  return {top:base-m.actualBoundingBoxAscent,bottom:base+m.actualBoundingBoxDescent};}
const LQ={lv:0,target:0,x:0};let PH=0;
function paintLiquid(el){const ib=inkBox(el),h=el.offsetHeight,top=ib.bottom-(ib.bottom-ib.top)*LQ.lv/100,a1=cssb('--a1'),a2=cssb('--a2');
  const w=`<svg xmlns='http://www.w3.org/2000/svg' width='600' height='60'><defs><linearGradient id='g' x1='0' x2='1'><stop offset='0' stop-color='${a2}'/><stop offset='.5' stop-color='${a1}'/><stop offset='1' stop-color='${a2}'/></linearGradient></defs><path d='M0 30 C 75 6, 225 6, 300 30 S 525 54, 600 30 V60 H0Z' fill='url(%23g)'/></svg>`;
  el.style.backgroundImage=`url("data:image/svg+xml,${w.replace(/#/g,'%23').replace(/</g,'%3C').replace(/>/g,'%3E')}"),linear-gradient(180deg,${a1},${a2})`;
  el.style.backgroundSize=`600px 60px,100% ${Math.max(h-top-28,0)}px`;el.style.backgroundPosition=`${LQ.x}px ${top-30}px,0 ${top+28}px`;}
function drawWaves(svg){const lv=(+svg.dataset.lv||0)/100,A=16+lv*70,a1=cssb('--a1'),a2=cssb('--a2'),a3=cssb('--a3');
  const P=(amp,len,sp,y)=>{let d=`M0 ${y}`;for(let x=0;x<=1440;x+=16)d+=` L${x} ${(y+Math.sin(x/len+PH*sp)*amp+Math.sin(x/(len*2.4)+PH*sp*.6)*amp*.5).toFixed(1)}`;return d;};
  const top=P(A,95,1.4,200);
  svg.innerHTML=`<defs><linearGradient id="w1" x1="0" x2="1"><stop offset="0" stop-color="${a2}"/><stop offset=".55" stop-color="${a1}"/><stop offset="1" stop-color="${a3}"/></linearGradient>
  <linearGradient id="wf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient><mask id="wm"><rect width="1440" height="300" fill="url(#wf)"/></mask></defs>
  <g mask="url(#wm)"><path d="${P(A*.6,180,.7,120)} L1440 300 L0 300Z" fill="url(#w1)" opacity=".12"/><path d="${P(A*.8,130,1,160)} L1440 300 L0 300Z" fill="url(#w1)" opacity=".2"/><path d="${top} L1440 300 L0 300Z" fill="url(#w1)" opacity=".34"/></g>
  <path d="${top}" fill="none" stroke="url(#w1)" stroke-width="2" opacity=".9"/>`;}
function setGiant(g,v){const n=String(Math.round(v)),pad=n.padStart(2,'0'),lead=pad.slice(0,pad.length-n.length);g.innerHTML=`<span class="z">${lead}</span><span class="v">${n}</span>`;}
function heroShow(){const h=activeHero();if(!h)return;const g=h.querySelector('.giant'),v=+g.dataset.v;LQ.target=Math.max(v,6);
  if(RM){setGiant(g,v);LQ.lv=LQ.target;const pl=()=>{paintLiquid(g.querySelector('.v'));drawWaves(h.querySelector('.waves2'));};pl();document.fonts&&document.fonts.ready.then(pl);return;}
  LQ.lv=0;let i=0;const steps=16;(function tick(){i++;setGiant(g,i>=steps?v:Math.max(0,Math.round(v*i/steps+(Math.random()-.5)*30*(1-i/steps))));if(i<steps)setTimeout(tick,55);})();}
let lastStar=0;
function frame(t){if(!document.hidden){
    if(t-lastStar>33&&+cssb('--star-op')>0){drawStars(t);lastStar=t;}
    const h=activeHero();if(h){const r=h.getBoundingClientRect();if(r.bottom>0&&r.top<innerHeight){PH+=.012;LQ.x=(LQ.x+1.1)%600;LQ.lv+=(LQ.target-LQ.lv)*.025;
      drawWaves(h.querySelector('.waves2'));const v=h.querySelector('.giant .v');if(v)paintLiquid(v);}}}
  requestAnimationFrame(frame);}
document.addEventListener('click',e=>{const a=e.target.closest('[data-scroll]');if(!a)return;e.preventDefault();const c=$('#sec-history');if(c)scrollTo({top:c.getBoundingClientRect().top+scrollY-hdr()+8,behavior:'smooth'});});
addEventListener('resize',initStars);
/* 頁首：量高度、捲動後變毛玻璃、分頁底線滑動 */
const TB=$('#topbar');function hdr(){return TB.offsetHeight;}
function setHdr(){document.documentElement.style.setProperty('--hdr',hdr()+'px');}
if(window.ResizeObserver)new ResizeObserver(setHdr).observe(TB);setHdr();
function onScroll(){TB.classList.toggle('solid',scrollY>8);}addEventListener('scroll',onScroll,{passive:true});onScroll();
function moveInd(){const on=$('.tabs-top .tab.on'),ind=$('.tab-ind');if(!ind)return;if(!on||!on.offsetWidth||on.classList.contains('tab-mid')){ind.style.opacity=0;return;}
  ind.style.opacity=1;ind.style.width=(on.offsetWidth-24)+'px';ind.style.transform=`translateX(${on.offsetLeft+12}px)`;}
addEventListener('resize',moveInd);document.fonts&&document.fonts.ready.then(()=>{moveInd();setHdr();});
/* 數字滾動 */
function countUp(el,dur=1500){const tn=[...el.childNodes].find(n=>n.nodeType===3&&/\d/.test(n.textContent));if(!tn)return;const to=+(el.dataset.to??=tn.textContent.replace(/[^\d.-]/g,''));if(!isFinite(to))return;
  if(RM){tn.textContent=Math.round(to);return;}tn.textContent=0;let t0=null;requestAnimationFrame(function f(t){t0??=t;const k=Math.min(1,(t-t0)/dur),e=1-Math.pow(1-k,4);tn.textContent=Math.round(to*e);if(k<1)requestAnimationFrame(f);});}
/* 區塊進場 */
const IO=new IntersectionObserver(es=>es.forEach(e=>{if(!e.isIntersecting)return;const el=e.target;
  if(!el.classList.contains('in')){el.classList.add('in');el.querySelectorAll('.cu').forEach(b=>countUp(b));}
  if(el.id==='sec-history'&&!st.main.played){st.main.played=true;animMain();}}),{threshold:.15});
$$('.reveal').forEach(e=>IO.observe(e));
/* 歷史走勢：由左到右逐步繪製 */
function animMain(){cancelAnimationFrame(animMain.id);if(RM){st.main.p=1;drawMain();return;}
  let t0=null;const dur=2600;st.main.p=0;drawMain();
  animMain.id=requestAnimationFrame(function f(t){t0??=t;const k=Math.min(1,(t-t0)/dur),e=k<.5?4*k*k*k:1-Math.pow(-2*k+2,3)/2;st.main.p=e;
    const el=$('#c-main'),r=el.querySelector('clipPath rect'),sc=el.querySelector('.scan');
    if(k>=1||!r){st.main.p=1;drawMain();return;}
    const L=+el.dataset.l,R=+el.dataset.r,cw=L+(el.clientWidth-L-R)*e;r.setAttribute('width',cw);if(sc){sc.setAttribute('x1',cw);sc.setAttribute('x2',cw);}
    animMain.id=requestAnimationFrame(f);});}
/* 路由 */
const VIEWS=['overview','timing','heat','data','mid','strat'];
const MODE_HIDE={top:['bsig','cold'],bottom:['sig','heat','tim']};
function applyMode(m){if(st.modeApplied===m)return;st.modeApplied=m;st.main.hide=new Set(MODE_HIDE[m]);$$('#legend-main button').forEach(b=>b.classList.toggle('off',st.main.hide.has(b.dataset.s)));}
function parseHash(){let p=(location.hash.slice(1)||'overview').split('/'),mode='top';
  if(p[0]==='b'){mode='bottom';p.shift();}
  if(p[0]==='overview'&&p[1]==='bottom'){mode='bottom';p=['overview'];}   /* 相容舊網址 */
  let v=p[0]||'overview';if(!VIEWS.includes(v))v='overview';return {mode,v,sub:p[1]};}
function route(){const {mode,v,sub}=parseHash();st.mode=mode;
  document.body.classList.toggle('mode-bottom',mode==='bottom');document.body.classList.toggle('view-mid',v==='mid');document.body.classList.toggle('view-strat',v==='strat');document.body.classList.toggle('view-side',v==='mid'||v==='strat');
  $$('.view').forEach(e=>e.classList.toggle('on',e.dataset.view===v));
  $$('.tab').forEach(e=>{e.classList.toggle('on',e.dataset.tab===v);e.setAttribute('href','#'+(mode==='bottom'?'b/':'')+e.dataset.tab);});
  $('#mode-top').setAttribute('href','#'+v);$('#mode-bottom').setAttribute('href','#b/'+v);
  $$('.sw a').forEach(e=>{e.classList.toggle('on',e.dataset.mode===mode);e.setAttribute('aria-selected',e.dataset.mode===mode);});
  applyMode(mode);moveInd();
  if(v==='overview'){requestAnimationFrame(heroShow);$$('.hero2 .kpi2 b').forEach(b=>{if(b.offsetParent)countUp(b,1400);});
    st.main.played=false;if(!RM)st.main.p=0;
    requestAnimationFrame(()=>{const c=$('#sec-history'),r=c.getBoundingClientRect();if(r.top<innerHeight*.85&&r.bottom>0){st.main.played=true;animMain();}});}
  if(sub){const el=document.getElementById((mode==='bottom'?'grp-':'cat-')+sub);if(el){el.open=true;setTimeout(()=>{const y=el.getBoundingClientRect().top+scrollY-hdr()-16;scrollTo({top:y,behavior:'smooth'});},30);}}else scrollTo(0,0);
  redraw();}
function redraw(){const {v}=parseHash();if(v==='overview')drawMain();if(v==='mid')drawMid();if(v==='strat')drawStrat();if(st.ind.k)drawInd();}
bind([$('#c-main')],'main',()=>i0of(st.main.years),drawMain);bind([$('#c-mid')],'mid',()=>i0of(st.mid.years),drawMid);bind([$('#c-strat')],'strat',()=>Math.max(0,D.d.findIndex(x=>x>=st.strat.years+'-01-01')),drawStrat);bindSeg();
addEventListener('hashchange',route);addEventListener('resize',redraw);matchMedia('(prefers-color-scheme: dark)').addEventListener('change',redraw);
initStars();route();if(!RM)requestAnimationFrame(frame);
</script>
</body>
</html>
""".replace("__TABS__", TAB_HTML)

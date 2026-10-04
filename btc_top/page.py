"""產生 docs/index.html：分頁式儀表板。靜態、內嵌資料、不在瀏覽器端呼叫外部 API。"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import pandas as pd

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
    "lth_sopr_7d": ("LTH-SOPR (7d avg)", "Sell price ÷ cost basis of coins sold by long-term holders. Well above 1 means heavy profit-taking."),
    "cdd_30d": ("CDD (30d avg)", "Coin days destroyed: coins moved × days held. Old coins moving in size often marks distribution at tops."),
    "lth_mvrv": ("LTH-MVRV", "Average unrealized profit multiple of long-term holders. Higher means more incentive to sell."),
    "cold_mvrv": ("MVRV (price ÷ realized price)", "Below 1 means price is under the market's average cost basis. Past bottoms: 0.56, 0.69, 0.75."),
    "cold_nupl": ("NUPL", "Net unrealized profit/loss. It turned negative (network-wide unrealized loss) at all three past bottoms."),
    "cold_puell": ("Puell Multiple", "Miner revenue vs its one-year average. Past bottoms: 0.31, 0.39, 0.48. Structurally lower miner revenue after the 2024 halving may make this read colder."),
    "cold_ribbon": ("Hash Ribbons (deepest in 90d)", "Hashrate 30d avg falling below 60d avg means miners are capitulating — common around bottoms, but also after halvings and policy shocks, so it is only supporting evidence."),
    "cold_ahr999": ("AHR999", "Price relative to its 200-day geometric mean and a long-term exponential growth curve. Past bottoms: 0.23, 0.27, 0.26; 1.2 is the customary DCA line (neutral)."),
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
    return f"""
  <div class="grid g-2">
    <div class="card hero">
      <div class="gwrap">{_gauge(b['signal'], 220, 16, '--s-bot', (BOTTOM_WINDOW, BOTTOM_STRONG))}<div class="gcenter"><div class="hero-label">⟪底部訊號|Bottom signal⟫</div><div class="hero-num">{b['signal']:.0f}</div><span class="lv lvb-{lvl}">{BOTTOM_LEVEL_TEXT[lvl]}</span></div></div>
      <div class="formula"><b>⟪冷度|Coldness⟫</b>⟪（7 日均）| (7d avg)⟫ × <b>⟪底部時機|Bottom timing⟫</b> ÷ 100　·　≥ {BOTTOM_WINDOW} ⟪底部區|bottom zone⟫　·　≥ {BOTTOM_STRONG} ⟪強烈底部|strong bottom⟫</div>
      <div class="minis">
        <a class="mini" href="#b/heat"><div class="gwrap">{_gauge(b['cold_score'], 96, 9, '--s-cold')}<div class="gcenter"><div class="mv cool-t">{b['cold_score']:.0f}</div></div></div><div class="ml">⟪冷度|Coldness⟫</div></a>
        <a class="mini" href="#b/timing"><div class="gwrap">{_gauge(tm['score'], 96, 9, '--accent')}<div class="gcenter"><div class="mv">{tm['score']:.0f}</div></div></div><div class="ml">⟪底部時機|Bottom timing⟫</div></a>
        <div class="mini"><div class="big">{_n(cur['bottom_signal_max_cycle'])}</div><div class="ml">⟪本輪最高|Cycle high⟫ · {(cur.get('bottom_signal_max_date') or '')[5:]}</div></div>
      </div>
    </div>
    <div class="grid">
      <div class="card verdict">
        <div class="card-head"><div><div class="eyebrow">CYCLE TEST</div><h3>⟪週期結構驗證|Cycle structure test⟫</h3></div><span class="status st-{ct['status']}">{STATUS_TEXT[ct['status']]}</span></div>
        <p class="q">⟪ETF 時代熊市是否變淺？本輪低點（|Are bear markets shallower in the ETF era? Is this cycle's low (⟫{cur['date']}, ${cur['price']:,.0f}⟪）是否就是週期底部？|) the cycle bottom?⟫</p>
        <div class="countdown"><div><b>{max(days_left, 0)}</b><span>⟪天後判定|days to verdict⟫</span></div><div><b>{ct['decisive_date']}</b><span>⟪底部窗口結束|bottom window ends⟫</span></div><div><b>{ct['days_mvrv_below_1_this_cycle']}</b><span>⟪MVRV&lt;1 天數|days MVRV&lt;1⟫</span></div></div>
        <p class="small">{_verdict(ct)}</p>
        <table class="data fit"><thead><tr><th>⟪底部|Bottom⟫</th><th>⟪距頂|From top⟫</th><th>⟪跌幅|Drop⟫</th><th>MVRV</th><th>⟪最高|Peak⟫</th><th>≥{BOTTOM_WINDOW} ⟪天|days⟫</th></tr></thead><tbody>{rows}</tbody></table>
        <p class="muted small" style="margin:6px 0 0">⟪距頂：距前次頂部天數；最高：該輪底部訊號最高分；≥{BOTTOM_WINDOW} 天：底部訊號達 {BOTTOM_WINDOW} 以上的天數。|From top: days since the previous top; Peak: highest bottom signal that cycle; ≥{BOTTOM_WINDOW} days: days with bottom signal at or above {BOTTOM_WINDOW}.⟫</p>
      </div>
      <div class="card">
        <div class="card-head"><div><div class="eyebrow">COLD</div><h3>⟪各組冷度|Coldness by group⟫</h3></div><a class="link" href="#b/heat">⟪全部指標|All indicators⟫ ›</a></div>
        {grp_rows}
      </div>
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
                defs: dict = INDICATORS, private: bool = False, lang: str = "zh"):
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
    private_banner = ('<div class="banner private">⟪私人版：含 BGeometrics 持有者指標（免費版條款僅限個人使用），只存在這台電腦，請勿上傳或分享。|Private build: includes BGeometrics holder metrics (free tier is personal use only). Stored on this computer only — do not upload or share.⟫</div>' if private else "")
    hz = _heat_zone(heat)
    rep = {
        "__TITLE__": f"{BRAND} · {BRAND_ZH}" + ("⟪（私人版）| (Private)⟫" if private else ""),
        "__BRAND__": BRAND,
        "__BRAND_ZH__": BRAND_ZH,
        "__LOGO__": LOGO_SVG,
        "__FAVICON__": FAVICON,
        "__BADGE__": '<span class="badge">⟪私人版|Private⟫</span>' if private else "",
        "__DATE__": latest["date"],
        "__PRICE__": f'{latest["price_usd"]:,.0f}',
        "__PRICE_DATE__": latest["price_date"],
        "__BANNERS__": private_banner + stale_banner,
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
        "__CSV_SCORES__": up + "../data/scores.csv" if private else REPO + "/blob/main/data/scores.csv",
        "__CSV_IND__": up + "../data/indicators.csv" if private else REPO + "/blob/main/data/indicators.csv",
        "__CSV_RAW__": up + "../data/raw" if private else REPO + "/tree/main/data/raw",
        "__JSON_HREF__": up + "latest.json",
        "__LANG_HREF__": "../index.html" if lang == "en" else "en/index.html",
        "__LANG_LABEL__": "中" if lang == "en" else "EN",
        "__LANG_TITLE__": "切換為中文" if lang == "en" else "Switch to English",
        "__EXTRA_SRC__": "⟪、BGeometrics（bitcoin-data.com，僅個人使用）|, BGeometrics (bitcoin-data.com, personal use only)⟫" if private else "",
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
}
TABS = [("overview", "⟪總覽|Overview⟫"), ("timing", "⟪時機|Timing⟫"), ("heat", "⟪熱度|Heat⟫"), ("data", "⟪數據|Data⟫")]
ICONS["cold"] = '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.5 4.5L12 7l2.5-2.5M9.5 19.5L12 17l2.5 2.5"/>'


def _tab(k, v):
    if k == "heat":  # 頂部模式「熱度」、底部模式「冷度」
        icon = (f'<svg class="tb-top" viewBox="0 0 24 24" aria-hidden="true">{ICONS["heat"]}</svg>'
                f'<svg class="tb-bot" viewBox="0 0 24 24" aria-hidden="true">{ICONS["cold"]}</svg>')
        return f'<a class="tab" href="#{k}" data-tab="{k}">{icon}<span class="tb-top">⟪熱度|Heat⟫</span><span class="tb-bot">⟪冷度|Cold⟫</span></a>'
    return f'<a class="tab" href="#{k}" data-tab="{k}"><svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[k]}</svg><span>{v}</span></a>'


TAB_HTML = "".join(_tab(k, v) for k, v in TABS)

TEMPLATE = r"""<!doctype html>
<html lang="⟪zh-Hant|en⟫">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__TITLE__</title>
<link rel="icon" href="__FAVICON__">
<meta name="description" content="⟪每日更新的比特幣週期訊號：頂部訊號（熱度 × 時機）與底部訊號（冷度 × 底部時機）。|Daily bitcoin cycle signals: a top signal (heat × timing) and a bottom signal (coldness × bottom timing).⟫">
<script>try{var t=localStorage.getItem('theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t;}catch(e){}
try{var L=localStorage.getItem('lang'),here='⟪zh|en⟫';
  if(!L){L=/^zh/i.test(navigator.language||'')?'zh':'en';}
  if(L!==here&&!/[?&]nolang/.test(location.search))location.replace((here==='zh'?'en/':'../')+(location.protocol==='file:'?'index.html':'')+location.hash);}catch(e){}</script>
<meta name="theme-color" content="#0b0d10" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#f3f4f6" media="(prefers-color-scheme: light)">
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
.banner.private{background:var(--accent-soft);border:1px solid color-mix(in srgb,var(--accent) 45%,transparent)}
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
</style>
</head>
<body>
<header class="appbar"><div class="wrap appbar-in">
  <a class="brand" href="#overview" aria-label="__BRAND__ ⟪首頁|home⟫">__LOGO__<div class="brand-txt"><h1><span class="wordmark">__BRAND__</span>__BADGE__</h1><div class="sub">__BRAND_ZH__ · $__PRICE__ · __PRICE_DATE__</div></div></a>
  <nav class="tabs tabs-top" aria-label="⟪分頁|Tabs⟫">__TABS__</nav>
  <a class="iconbtn lang" id="lang" href="__LANG_HREF__" title="__LANG_TITLE__" aria-label="__LANG_TITLE__">__LANG_LABEL__</a>
  <button class="iconbtn" id="theme" aria-label="⟪切換深淺色|Toggle theme⟫" title="⟪深淺色：自動|Theme: auto⟫"></button>
  <button class="iconbtn" id="help" aria-label="⟪怎麼看這個頁面|How to read this page⟫">?</button>
</div></header>

<main class="wrap">
__BANNERS__
  <div class="mode-bar"><div class="seg-mode" role="tablist" aria-label="⟪訊號類型|Signal type⟫">
    <a href="#overview" data-mode="top" id="mode-top" role="tab"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 17L11 11l3 3 5-6"/><path d="M14 8h5v5"/></svg><span><b>⟪頂部訊號|Top signal⟫</b><small>⟪熱度 × 時機|Heat × timing⟫</small></span></a>
    <a href="#b/overview" data-mode="bottom" id="mode-bottom" role="tab"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7l6 6 3-3 5 6"/><path d="M14 16h5v-5"/></svg><span><b>⟪底部訊號|Bottom signal⟫</b><small>⟪冷度 × 底部時機|Coldness × timing⟫</small></span></a>
  </div></div>

<section class="view" data-view="overview" aria-label="⟪總覽|Overview⟫">
  <div class="mode" data-mode="top">
  <div class="grid g-2">
    <div class="card hero">
      <div class="gwrap">__G_SIG__<div class="gcenter"><div class="hero-label">⟪頂部訊號|Top signal⟫</div><div class="hero-num">__SIG__</div><span class="lv lv-__LVL__">__LVL_TEXT__</span></div></div>
      <div class="formula"><b>⟪熱度|Heat⟫</b>⟪（7 日均）| (7d avg)⟫ × <b>⟪時機|Timing⟫</b> ÷ 100　·　≥ __WIN__ ⟪頂部窗口|top window⟫　·　≥ __ALERT__ ⟪高度警戒|high alert⟫</div>
      <div class="minis">
        <a class="mini" href="#heat"><div class="gwrap">__G_HEAT__<div class="gcenter"><div class="mv __HEAT_BAND__">__HEAT__</div></div></div><div class="ml">⟪熱度|Heat⟫ · __HEAT_TEXT__</div></a>
        <a class="mini" href="#timing"><div class="gwrap">__G_TIM__<div class="gcenter"><div class="mv">__TIM__</div></div></div><div class="ml">⟪時機|Timing⟫</div></a>
        <a class="mini" href="#heat"><div class="big">__HOT__<small>/__NCAT__</small></div><div class="ml">⟪熱類別 ≥ 80|Hot (≥ 80)⟫</div></a>
      </div>
    </div>
    <div class="grid">
      <div class="card">
        <div class="card-head"><div><div class="eyebrow">CYCLE</div><h3>⟪週期位置|Cycle position⟫</h3></div><a class="link" href="#timing">⟪時機詳情|Timing details⟫ ›</a></div>
        __TIMELINE__
      </div>
      <div class="card">
        <div class="card-head"><div><div class="eyebrow">HEAT</div><h3>⟪各類熱度|Heat by category⟫</h3></div><a class="link" href="#heat">⟪全部指標|All indicators⟫ ›</a></div>
        __CAT_ROWS__
      </div>
    </div>
  </div>
  </div>
  <div class="mode" data-mode="bottom">__BOTTOM_OVERVIEW__
  </div>
  <div class="card chart-card">
    <div class="card-head"><div><div class="eyebrow">HISTORY</div><h3>⟪歷史走勢|History⟫</h3></div>
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
</section>

<section class="view" data-view="timing" aria-label="⟪時機|Timing⟫">
  <div class="mode" data-mode="top">
  <div class="view-head"><h2>⟪頂部時機|Top timing⟫ __TIM__</h2><p>⟪兩個時鐘各自 0–100，取平均。紫點是過去四次頂部；色帶是窗口（深色滿分、淺色有分數）。|Two clocks, each 0–100, averaged. Purple dots are the four past tops; the band is the window (dark = full score, light = partial).⟫</p></div>
  <div class="grid g-tim">__TIMING__</div>
  </div>
  <div class="mode" data-mode="bottom">
  <div class="view-head"><h2>⟪底部時機|Bottom timing⟫ __BTIM__</h2><p>⟪兩個時鐘各自 0–100，取平均。洋紅點是過去三次底部；色帶是窗口（深色滿分、淺色有分數）。|Two clocks, each 0–100, averaged. Magenta dots are the three past bottoms; the band is the window (dark = full score, light = partial).⟫</p></div>
  <div class="grid g-tim">__BTIMING__</div>
  </div>
</section>

<section class="view" data-view="heat" aria-label="⟪熱度|Heat⟫">
  <div class="mode" data-mode="top">
  <div class="view-head"><h2>⟪熱度|Heat⟫ <span class="__HEAT_BAND__">__HEAT__</span></h2><p>⟪__CATLIST____NCAT_TEXT__加權平均。週期法用過去頂部推估本輪預期頂部；百分位法超過 __PIVOT__% 才計分；單一指標加總上限 120。點任一指標看說明與歷史走勢。|Weighted average of __NCAT_TEXT__: __CATLIST__. The cycle method projects this cycle's expected top from past tops; percentile indicators only score above __PIVOT__%; each indicator is capped at 120. Tap any indicator for details and history.⟫</p></div>
  __CATS__
  </div>
  <div class="mode" data-mode="bottom">
  <div class="view-head"><h2>⟪冷度|Coldness⟫ <span class="cool-t">__COLD_SCORE__</span></h2><p>⟪估值、礦工、價格結構三組加權平均。冷度 100 代表達到本輪推估的底部水準，0 代表在中性以上。點任一指標看說明與歷史走勢。|Weighted average of three groups: valuation, miners and price structure. 100 means this cycle's projected bottom level; 0 means neutral or above. Tap any indicator for details and history.⟫</p></div>
  <div class="cold-groups">__COLD__</div>
  </div>
</section>

<section class="view" data-view="data" aria-label="⟪數據|Data⟫">
  <div class="view-head"><h2>⟪數據|Data⟫</h2><p>⟪最近 30 天每日數值與完整資料下載。|Daily values for the last 30 days, plus full downloads.⟫</p></div>
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
  <p>⟪<b>冷度</b>：估值（MVRV、NUPL）50%、礦工（Puell、Hash Ribbons）30%、價格結構（AHR999）20%。100 代表達到本輪推估的底部水準。|<b>Coldness</b>: valuation (MVRV, NUPL) 50%, miners (Puell, Hash Ribbons) 30%, price structure (AHR999) 20%. 100 means this cycle's projected bottom level.⟫</p>
  <p>⟪<b>底部時機</b>：距上次頂部天數（過去底部平均約 379 天）與距上次減半天數（約 859 天）。|<b>Bottom timing</b>: days since the last top (past bottoms averaged ~379) and days since the last halving (~859).⟫</p>
  <p>⟪參數只依 2015、2018、2022 三次底部與中段假底部決定，本輪（2026）是樣本外檢驗；「週期結構驗證」會追蹤本輪低點是否就是週期底部。切換模式後，時機、熱度（冷度）、數據各頁都會換成對應內容。|Parameters were set only from the 2015, 2018 and 2022 bottoms and mid-cycle false bottoms, so this cycle (2026) is an out-of-sample test. The “cycle structure test” tracks whether this cycle's low is the bottom. Switching modes swaps the Timing, Heat/Cold and Data tabs to match.⟫</p>
  <h3>⟪限制|Limitations⟫</h3><ul>
    <li>⟪時機假設約四年的週期會延續；週期若變長或變短，訊號可能提早、延後甚至整輪不亮，請同時看熱度與時機。|Timing assumes the ~4-year cycle continues. If cycles stretch or shrink, signals may come early, late, or not at all — watch heat and timing separately too.⟫</li>
    <li>⟪訊號是「幾個月的窗口」，不是精確的頂部日期。|Signals mark a window of months, not an exact top date.⟫</li>
    <li>⟪歷史訊號以目前參數回推（樣本內），過去只有 4 次頂部可驗證。|Historical signals use today's parameters (in-sample); there are only 4 past tops to test against.⟫</li>
    <li>⟪僅供參考，不構成投資建議。|For reference only — not investment advice.⟫</li></ul>
</div></template>

<script>
const D=__DATA__,IND=__IND__,TOPS=__TOPS__,BOTTOMS=__BOTTOMS__,CUR_LOW=__CUR_LOW__,WIN=__WIN__,ALERT=__ALERT__;
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const TS=D.d.map(d=>Date.parse(d));  /* 橫軸依實際日期（資料一年前每週一點、最近一年每日一點） */
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const st={main:{years:0,hover:null,hide:new Set()},ind:{years:0,hover:null,k:null},mode:'top',modeApplied:null};
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
  let g='';const grid=css('--line'),mut=css('--faint');
  const ticks=o.ticks?[...o.ticks]:(o.log?[]:niceTicks(lo,hi));
  if(o.log){for(let e=Math.ceil(lo);e<=hi;e++)ticks.push(10**e);}
  ticks.forEach(v=>{const yy=y(v);g+=`<line x1="${L}" x2="${W-R}" y1="${yy}" y2="${yy}" stroke="${grid}"/><text x="${L-6}" y="${yy+4}" font-size="11" text-anchor="end" fill="${mut}">${o.log?(v>=1000?(v/1000)+'k':v):short(v)}</text>`;});
  (o.thresholds||[]).forEach(v=>{g+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="${css('--mut')}" stroke-dasharray="3 4" opacity=".7"/>`;});
  (o.marks||[{d:TOPS,c:'--topline',dash:'3 3',op:.6}]).forEach(m=>m.d.forEach(t=>{const i=D.d.findIndex(v=>v>=t)-i0;if(i>0&&i<n)g+=`<line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${H-B}" stroke="${css(m.c)}" stroke-dasharray="${m.dash}" opacity="${m.op}"/>`;}));
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
    g+=`<path d="${d}" fill="none" stroke="${css(s.c)}" stroke-width="${s.w||2}" stroke-linejoin="round" stroke-linecap="round"${s.dash?` stroke-dasharray="${s.dash}"`:''}/>`;});
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
function drawMain(){const s=st.main,i0=i0of(s.years),mk=mainMarks();$('#c-main').setAttribute('height',innerWidth>=1200?440:innerWidth>=900?370:320);
  chart($('#c-main'),i0,[{a:D.tim,c:'--s-tim',w:1.6,dash:'5 4',hide:s.hide.has('tim')},{a:D.heat,c:'--s-heat',w:1.7,hide:s.hide.has('heat')},{a:D.cold,c:'--s-cold',w:1.6,hide:s.hide.has('cold')},{a:D.bsig,c:'--s-bot',w:2.2,fill:true,hide:s.hide.has('bsig')},{a:D.sig,c:'--s-sig',w:2.4,fill:true,hide:s.hide.has('sig')}],{min:0,max:100,ticks:[0,25,50,75,100],thresholds:[WIN,ALERT],axis:true,hover:s.hover,marks:mk,bg:{a:D.p}});
  const j=i0+(s.hover==null?D.d.length-1-i0:s.hover);
  $('#tip-main').innerHTML=`<b>${D.d[j]}</b><span>$${Math.round(D.p[j]).toLocaleString()}</span><span>⟪訊號|Top⟫ <b>${f0(D.sig[j])}</b></span><span>⟪熱度|Heat⟫ <b>${f0(D.heat[j])}</b></span><span>⟪時機|Timing⟫ <b>${f0(D.tim[j])}</b></span><span>⟪底部|Bottom⟫ <b>${f0(D.bsig[j])}</b></span><span>⟪冷度|Cold⟫ <b>${f0(D.cold[j])}</b></span>`;}
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
  $('#theme').innerHTML=THEME_ICON[t];$('#theme').title='⟪深淺色：|Theme: ⟫'+THEME_TEXT[t];$('#theme').setAttribute('aria-label','⟪深淺色：|Theme: ⟫'+THEME_TEXT[t]+'⟪（點擊切換）| (tap to change)⟫');
  if(save){try{t==='auto'?localStorage.removeItem('theme'):localStorage.setItem('theme',t);}catch(e){}}requestAnimationFrame(redraw);}
setTheme(document.documentElement.dataset.theme||'auto',false);
$('#theme').onclick=()=>{const order=['auto','light','dark'],cur=document.documentElement.dataset.theme||'auto';setTheme(order[(order.indexOf(cur)+1)%3],true);};
function openInd(k){const m=IND[k];st.ind={years:0,hover:null,k};
  openSheet(`<div class="sh-cat">${m.cat}</div><div class="sh-title" id="sheet-title">${m.label}</div>
  <div class="sh-kpis"><div><span>⟪目前數值|Current value⟫ (${m.asOf})</span><b>${m.value}</b></div><div><span>⟪分數|Score⟫</span><b class="${m.band}">${m.score==null?'—':m.score}</b></div></div>
  <p class="sh-p">${m.desc}</p><p class="sh-m">${m.method}${m.stale?'　·　⚠ ⟪舊資料|Stale⟫':''}</p>
  <div class="chart-top"><div class="seg" data-g="ind"><button data-y="0" class="on">⟪全部|All⟫</button><button data-y="4">⟪4 年|4Y⟫</button><button data-y="1">⟪1 年|1Y⟫</button></div></div>
  <div class="tip" id="tip-ind"></div><svg class="chart" id="c-val" height="160" role="img" aria-label="⟪指標數值歷史|Indicator value history⟫"></svg>
  ${D['s_'+k]?'<svg class="chart" id="c-sc" height="120" role="img" aria-label="⟪指標分數歷史|Indicator score history⟫"></svg>':''}`,()=>{bindSeg();bind([$('#c-val'),$('#c-sc')],'ind',()=>i0of(st.ind.years),drawInd);drawInd();});}
$$('.ind').forEach(b=>b.onclick=()=>openInd(b.dataset.k));
function bindSeg(){$$('.seg').forEach(box=>box.querySelectorAll('button').forEach(b=>b.onclick=()=>{box.querySelectorAll('button').forEach(o=>o.classList.remove('on'));b.classList.add('on');const g=box.dataset.g;st[g].years=+b.dataset.y;st[g].hover=null;g==='main'?drawMain():drawInd();}));}
$$('#legend-main button').forEach(b=>b.onclick=()=>{const k=b.dataset.s,h=st.main.hide;h.has(k)?h.delete(k):h.add(k);b.classList.toggle('off');drawMain();});
/* 路由 */
const VIEWS=['overview','timing','heat','data'];
const MODE_HIDE={top:['bsig','cold'],bottom:['sig','heat','tim']};
function applyMode(m){if(st.modeApplied===m)return;st.modeApplied=m;st.main.hide=new Set(MODE_HIDE[m]);$$('#legend-main button').forEach(b=>b.classList.toggle('off',st.main.hide.has(b.dataset.s)));}
function parseHash(){let p=(location.hash.slice(1)||'overview').split('/'),mode='top';
  if(p[0]==='b'){mode='bottom';p.shift();}
  if(p[0]==='overview'&&p[1]==='bottom'){mode='bottom';p=['overview'];}   /* 相容舊網址 */
  let v=p[0]||'overview';if(!VIEWS.includes(v))v='overview';return {mode,v,sub:p[1]};}
function route(){const {mode,v,sub}=parseHash();st.mode=mode;
  document.body.classList.toggle('mode-bottom',mode==='bottom');
  $$('.view').forEach(e=>e.classList.toggle('on',e.dataset.view===v));
  $$('.tab').forEach(e=>{e.classList.toggle('on',e.dataset.tab===v);e.setAttribute('href','#'+(mode==='bottom'?'b/':'')+e.dataset.tab);});
  $('#mode-top').setAttribute('href','#'+v);$('#mode-bottom').setAttribute('href','#b/'+v);
  $$('.seg-mode a').forEach(e=>e.classList.toggle('on',e.dataset.mode===mode));
  applyMode(mode);
  if(sub){const el=document.getElementById((mode==='bottom'?'grp-':'cat-')+sub);if(el){el.open=true;setTimeout(()=>{const y=el.getBoundingClientRect().top+scrollY-130;scrollTo({top:y,behavior:'smooth'});},30);}}else scrollTo(0,0);
  redraw();}
function redraw(){const {v}=parseHash();if(v==='overview')drawMain();if(st.ind.k)drawInd();}
bind([$('#c-main')],'main',()=>i0of(st.main.years),drawMain);bindSeg();
addEventListener('hashchange',route);addEventListener('resize',redraw);matchMedia('(prefers-color-scheme: dark)').addEventListener('change',redraw);
route();
</script>
</body>
</html>
""".replace("__TABS__", TAB_HTML)

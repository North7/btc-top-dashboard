"""產生 docs/index.html：靜態、內嵌資料、不在瀏覽器端呼叫外部 API。"""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from btc_top.scoring import INDICATORS, PCT_PIVOT, SIGNAL_ALERT, SIGNAL_WINDOW

REPO = "https://github.com/North7/btc-top-dashboard"
LEVEL_TEXT = {"none": "未觸發", "window": "頂部窗口", "alert": "高度警戒"}
HEAT_TEXT = {"cold": "冷", "warm": "溫", "hot": "熱"}


def _fmt(v, unit=""):
    if v is None:
        return "—"
    a = abs(v)
    s = f"{v:,.0f}" if a >= 1000 else f"{v:,.2f}" if a >= 1 else f"{v:.3f}"
    if unit in ("", None):
        return s
    return f"{s}{unit}" if unit in ("x", "%") else f"{s} {unit}"


def _val_html(v, unit):
    """數值欄：長單位放在數值下方，避免把指標說明擠窄。"""
    if v is None or unit in ("", None, "x", "%"):
        return _fmt(v, unit)
    return f'{_fmt(v)}<span class="u">{html.escape(unit)}</span>'


def _method(i):
    if i.get("role") == "ref":
        p = i.get("percentile")
        return "僅供參考，不計分" + (f"（4 年百分位 {p:.0f}%）" if p is not None else "")
    m = i.get("method")
    if m == "cycle":
        return f"週期法：本輪下界 {_fmt(i.get('bottom_bound'))} → 預期頂部 {_fmt(i.get('expected_top'))}"
    if m == "percentile":
        p = i.get("percentile")
        return (f"4 年百分位 {p:.0f}%" if p is not None else "百分位（資料累積中）") + f"，超過 {PCT_PIVOT}% 才開始計分"
    return ""


def _band(score):
    if score is None:
        return "na"
    return "top" if score >= 80 else "hot" if score >= 65 else "warm" if score >= 40 else "cold"


def _series(hist: pd.DataFrame, ind: pd.DataFrame, defs: dict) -> dict:
    """內嵌資料：一年前以前每週一點，最近一年每日一點。"""
    cols = {"p": hist["price"], "sig": hist["top_signal"], "heat": hist["heat_7d"], "tim": hist["timing"]}
    for k in defs:
        cols["v_" + k] = ind[k].reindex(hist.index)
        if defs[k][3] == "score":
            cols["s_" + k] = hist["score_" + k]
    cols["v_days_since_halving"] = hist["days_since_halving"]
    cols["v_days_since_low"] = hist["days_since_low"]
    df = pd.DataFrame(cols).dropna(subset=["p"])
    cut = df.index.max() - pd.Timedelta(days=365)
    df = pd.concat([df[df.index < cut].resample("W").last(), df[df.index >= cut]])

    def arr(s):
        return [None if pd.isna(x) else round(float(x), 4 if abs(x) < 10 else 1) for x in s]

    return {"d": [d.strftime("%Y-%m-%d") for d in df.index], **{k: arr(df[k]) for k in df.columns}}


def _n(v):
    return "—" if v is None or pd.isna(v) else f"{v:.0f}"


def _recent_table(hist: pd.DataFrame, latest: dict) -> str:
    cats = list(latest["categories"].items())
    h = hist.dropna(subset=["price"]).tail(30).iloc[::-1]
    head = "".join(f"<th>{html.escape(c['label'])}</th>" for _, c in cats)
    rows = []
    for d, r in h.iterrows():
        cells = "".join(f"<td>{_n(r.get('cat_' + k))}</td>" for k, _ in cats)
        rows.append(f"<tr><td>{d:%m-%d}</td><td>{r['price']:,.0f}</td><td class='b'>{_n(r['top_signal'])}</td>"
                    f"<td>{_n(r['heat'])}</td><td>{_n(r['timing'])}</td>{cells}</tr>")
    return (f"<table class='data'><thead><tr><th>日期</th><th>價格</th><th>頂部訊號</th><th>熱度</th><th>時機</th>"
            f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>")


def render_page(latest: dict, hist: pd.DataFrame, ind: pd.DataFrame, path: Path,
                defs: dict = INDICATORS, private: bool = False):
    t = latest["timing"]
    sig, lvl = latest["top_signal"], latest["signal_level"]

    # ---- 熱度：各類別與指標 ----
    cats_html = []
    for key, c in latest["categories"].items():
        sc = c["score"]
        band = _band(sc)
        rows = []
        for i in c["indicators"].values():
            name = html.escape(i["label"])
            if i["status"] != "ok":
                rows.append(f'<div class="ind na"><div class="ind-main"><div class="ind-name">{name}</div>'
                            f'<div class="ind-desc">{html.escape(i.get("reason", "無免費資料"))}</div></div>'
                            f'<div class="ind-val">—</div><div class="ind-sc">—</div></div>')
                continue
            stale = '<span class="tag">舊資料</span>' if i["stale"] else ""
            ref = '<span class="tag ref">參考</span>' if i["role"] == "ref" else ""
            score = "—" if i["score"] is None else f'{i["score"]:.0f}'
            rows.append(
                f'<div class="ind"><div class="ind-main"><div class="ind-name">{name}{ref}{stale}</div>'
                f'<div class="ind-desc">{html.escape(i.get("description", ""))}</div>'
                f'<div class="ind-meta">{html.escape(_method(i))} · 資料日 {i["as_of"]}</div></div>'
                f'<div class="ind-val">{_val_html(i["value"], i["unit"])}</div>'
                f'<div class="ind-sc {_band(i["score"])}">{score}</div></div>')
        if c["status"] == "unavailable":
            note = f'目前無可計分的免費資料，{c["weight"]*100:.0f}% 權重已按比例分給其他類別。'
        elif c["status"] == "partial":
            note = "部分指標無免費資料，以可用指標平均。"
        else:
            note = ""
        eff = c["effective_weight"]
        wtxt = f'權重 {c["weight"]*100:.0f}%' + (f'（實際 {eff*100:.0f}%）' if eff and abs(eff - c["weight"]) > .005 else "")
        cats_html.append(f"""
<div class="sub cat{' muted' if c['status'] == 'unavailable' else ''}">
  <div class="cat-head"><span class="cat-name">{c['label']}</span><span class="w">{wtxt}</span>
    <span class="sc {band}">{'—' if sc is None else f'{sc:.0f}'}</span></div>
  <div class="bar"><div class="fill {band}" style="width:{0 if sc is None else min(sc, 100)}%"></div><div class="m80"></div></div>
  {f'<div class="note">{note}</div>' if note else ''}
  <div class="ind-h"><div>指標</div><div>目前數值</div><div>分數</div></div>
  <div class="inds">{''.join(rows)}</div>
</div>""")

    # ---- 時機 ----
    wh, wl = t["expected_window_by_halving"], t["expected_window_by_low"]
    past = "".join(f"<tr><td>{d[:7]}</td><td>{t['past_tops_halving_days'][d]}</td><td>{t['past_tops_low_days'][d]}</td></tr>"
                   for d in t["past_tops_halving_days"])
    timing_html = f"""
<div class="sub">
<div class="trow">
  <div class="tl"><div class="tname">距最近一次減半</div><div class="tsub">{t['last_halving']} 減半</div></div>
  <div class="tv">{t['days_since_halving']} 天</div><div class="sc {_band(t['score_halving'])}">{t['score_halving']:.0f}</div>
</div>
<div class="bar"><div class="fill {_band(t['score_halving'])}" style="width:{t['score_halving']}%"></div></div>
<div class="note">過去三次頂部平均在減半後 <b>{t['center_halving_days']}</b> 天。依 {t['window_halving']}{'（估計）' if t['window_halving'] == t['next_halving'] else ''} 減半推算，滿分窗口 <b>{wh['full_from']} ～ {wh['full_to']}</b>，有分數的範圍 {wh['from']} ～ {wh['to']}。</div>
</div>
<div class="sub">
<div class="trow">
  <div class="tl"><div class="tname">距本輪週期低點</div><div class="tsub">{t['cycle_low_date']} 低點 ${t['cycle_low_price']:,.0f}</div></div>
  <div class="tv">{t['days_since_low']} 天</div><div class="sc {_band(t['score_low'])}">{t['score_low']:.0f}</div>
</div>
<div class="bar"><div class="fill {_band(t['score_low'])}" style="width:{t['score_low']}%"></div></div>
<div class="note">過去三次頂部平均在週期低點後 <b>{t['center_low_days']}</b> 天。依目前低點推算，滿分窗口 <b>{wl['full_from']} ～ {wl['full_to']}</b>。若價格再創本輪新低，低點日期與窗口會跟著往後移。</div>
</div>
<details class="past"><summary>過去頂部的天數</summary>
<table class="data"><thead><tr><th>頂部</th><th>距減半</th><th>距週期低點</th></tr></thead><tbody>{past}</tbody></table>
<div class="note">窗口中心取最近三次（2017、2021、2025）的平均；中心前後 {t['flat_days']} 天內為滿分，再往外 {t['ramp_days']} 天線性降到 0。2013 年那一輪較短，不在平均內。</div>
</details>"""

    options = "".join(
        f'<option value="{k}">{html.escape(CAT_LABEL[d[0]])}｜{html.escape(d[1])}</option>' for k, d in defs.items())
    options += '<option value="days_since_halving">時機｜距減半天數</option><option value="days_since_low">時機｜距週期低點天數</option>'
    units = {k: d[2] for k, d in defs.items()} | {"days_since_halving": "天", "days_since_low": "天"}

    stale_banner = ('<div class="banner">部分資料源今日抓取失敗，沿用前一次數值（指標旁標示「舊資料」）。</div>'
                    if latest["stale"] else "")
    page = (TEMPLATE
            .replace("__DATE__", latest["date"])
            .replace("__PRICE__", f'{latest["price_usd"]:,.0f}')
            .replace("__PRICE_DATE__", latest["price_date"])
            .replace("__SIG__", f"{sig:.0f}")
            .replace("__LVL__", lvl)
            .replace("__LVL_TEXT__", LEVEL_TEXT[lvl])
            .replace("__HEAT__", f'{latest["heat_score"]:.0f}')
            .replace("__HEAT_BAND__", _band(latest["heat_score"]))
            .replace("__HEAT_TEXT__", HEAT_TEXT[_heat_zone(latest["heat_score"])])
            .replace("__TIM__", f'{latest["timing_score"]:.0f}')
            .replace("__HOT__", str(latest["hot_categories"]))
            .replace("__WIN__", str(SIGNAL_WINDOW))
            .replace("__ALERT__", str(SIGNAL_ALERT))
            .replace("__PIVOT__", str(PCT_PIVOT))
            .replace("__CENTER_H__", str(t["center_halving_days"]))
            .replace("__CENTER_L__", str(t["center_low_days"]))
            .replace("__WIN_H__", f'{wh["full_from"][:7]} ～ {wh["full_to"][:7]}')
            .replace("__TIMING__", timing_html)
            .replace("__CATS__", "".join(cats_html))
            .replace("__OPTIONS__", options)
            .replace("__TABLE__", _recent_table(hist, latest))
            .replace("__STALE__", (PRIVATE_BANNER if private else "") + stale_banner)
            .replace("__CSV_SCORES__", "../data/scores.csv" if private else REPO + "/blob/main/data/scores.csv")
            .replace("__CSV_IND__", "../data/indicators.csv" if private else REPO + "/blob/main/data/indicators.csv")
            .replace("__CSV_RAW__", "../data/raw" if private else REPO + "/tree/main/data/raw")
            .replace("__EXTRA_SRC__", "、BGeometrics（bitcoin-data.com，僅個人使用）" if private else "")
            .replace("__TITLE__", "BTC 週期頂部儀表板（私人版）" if private else "BTC 週期頂部儀表板")
            .replace("__REPO__", REPO)
            .replace("__GENERATED__", latest["generated_at"])
            .replace("__UNITS__", json.dumps(units, ensure_ascii=False))
            .replace("__TOPS__", json.dumps(latest["cycle_tops"]))
            .replace("__DATA__", json.dumps(_series(hist, ind, defs), separators=(",", ":"))))
    path.write_text(page, encoding="utf-8")


PRIVATE_BANNER = ('<div class="banner private">私人版：含 BGeometrics 持有者指標（免費版條款僅限個人使用），'
                  '只存在這台電腦，請勿上傳或分享。公開版不含這些數據。</div>')

CAT_LABEL = {"onchain_valuation": "鏈上估值", "holder_behavior": "持有者行為", "capital_flows": "資金流",
             "leverage": "槓桿", "sentiment_cycle": "情緒"}


def _heat_zone(h):
    return "hot" if h >= 65 else "warm" if h >= 40 else "cold"


TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<meta name="description" content="每日更新的比特幣週期頂部訊號：市場熱度 × 週期時機。">
<style>
:root{--bg:#eceef1;--card:#fff;--sub:#f5f6f8;--tile:#fff;--head:#f0f3f8;--fg:#0b0b0b;--mut:#5d5c58;--faint:#8d8c86;
--line:#dcdde1;--grid:#eceae6;--accent:#2a78d6;
--s1:#2a78d6;--s2:#eb6834;--s0:#8d8c86;--price:#52514e;--topline:#e34948;
--cold:#2a78d6;--warm:#c98500;--hot:#eb6834;--top:#d03b3b;--na:#b9b8b2;--lv-none:#8d8c86;--lv-window:#c98500;--lv-alert:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0b0b0a;--card:#191918;--sub:#222220;--tile:#191918;--head:#1f2329;
--fg:#fff;--mut:#c3c2b7;--faint:#8a897f;--line:#34342f;--grid:#2c2c29;--accent:#3987e5;
--s1:#3987e5;--s2:#d95926;--s0:#8a897f;--price:#c3c2b7;--topline:#e66767;
--cold:#3987e5;--warm:#d9a21b;--hot:#e5713d;--top:#e66767;--na:#55554f;--lv-none:#6f6e68;--lv-window:#c98500;--lv-alert:#d64545}}
:root[data-theme="dark"]{--bg:#0b0b0a;--card:#191918;--sub:#222220;--tile:#191918;--head:#1f2329;
--fg:#fff;--mut:#c3c2b7;--faint:#8a897f;--line:#34342f;--grid:#2c2c29;--accent:#3987e5;
--s1:#3987e5;--s2:#d95926;--s0:#8a897f;--price:#c3c2b7;--topline:#e66767;
--cold:#3987e5;--warm:#d9a21b;--hot:#e5713d;--top:#e66767;--na:#55554f;--lv-none:#6f6e68;--lv-window:#c98500;--lv-alert:#d64545}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang TC","Noto Sans TC","Microsoft JhengHei",sans-serif}
main{max-width:760px;margin:0 auto;padding:16px}
h1{font-size:18px;margin:4px 0 0}h2{font-size:16.5px;margin:0;flex:1}
.meta,.note,.ind-desc,.tsub{color:var(--mut)}.meta{font-size:13px}
.toc{position:sticky;top:0;z-index:5;display:flex;gap:6px;overflow-x:auto;margin:12px -16px 0;padding:8px 16px;background:var(--bg);border-bottom:1px solid var(--line);scrollbar-width:none}
.toc::-webkit-scrollbar{display:none}
.toc a{flex:none;text-decoration:none;font-size:13px;padding:4px 12px;border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
section{scroll-margin-top:56px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;margin:20px 0;overflow:hidden}
.card-h{display:flex;align-items:center;gap:10px;padding:12px 16px;background:var(--head);border-bottom:1px solid var(--line);border-top:3px solid var(--accent)}
.kicker{font-size:12px;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums;letter-spacing:.5px}
.hval{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
.card-b{padding:14px 16px 16px}
.sub{background:var(--sub);border:1px solid var(--line);border-radius:12px;padding:12px;margin:12px 0}
.sub:first-child{margin-top:0}
.lead{font-size:13px;color:var(--mut);margin:0 0 4px}
.hero{text-align:center;padding:18px 16px;border-top:3px solid var(--accent)}
.hero .lbl{color:var(--mut);font-size:13px}
.hero .big{font-size:64px;font-weight:700;line-height:1.05;font-variant-numeric:tabular-nums}
.lv{display:inline-block;padding:3px 14px;border-radius:999px;color:#fff;font-weight:600;font-size:15px;margin-top:6px}
.lv-none{background:var(--lv-none)}.lv-window{background:var(--lv-window)}.lv-alert{background:var(--lv-alert)}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px}
.tile{background:var(--sub);border:1px solid var(--line);border-radius:12px;padding:8px 4px}
.tile .v{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}
.tile .k{font-size:12px;color:var(--mut)}
.formula{font-size:13px;color:var(--mut);margin-top:10px}
.banner.private{background:color-mix(in srgb,var(--accent) 16%,transparent);border:1px solid var(--accent)}
.banner{background:color-mix(in srgb,var(--warm) 18%,transparent);border-radius:10px;padding:10px 12px;font-size:13px;margin:12px 0}
.guide p{margin:6px 0;font-size:14px}.guide b{font-weight:600}
.guide ul{margin:6px 0;padding-left:20px;font-size:14px}.guide li{margin:3px 0}
.sc{font-weight:700;font-variant-numeric:tabular-nums}
.sc.cold,.ind-sc.cold{color:var(--cold)}.sc.warm,.ind-sc.warm{color:var(--warm)}.sc.hot,.ind-sc.hot{color:var(--hot)}
.sc.top,.ind-sc.top{color:var(--top)}.sc.na,.ind-sc.na{color:var(--na)}
.bar{position:relative;height:8px;background:var(--grid);border-radius:5px;margin:8px 0 4px;overflow:hidden}
.fill{height:100%;border-radius:5px}.fill.cold{background:var(--cold)}.fill.warm{background:var(--warm)}
.fill.hot{background:var(--hot)}.fill.top{background:var(--top)}.fill.na{background:transparent}
.m80{position:absolute;left:80%;top:0;bottom:0;width:2px;background:var(--fg);opacity:.3}
.note{font-size:12.5px;margin:6px 0 0}.note b{color:var(--fg)}
.trow{display:flex;align-items:baseline;gap:10px}.tl{flex:1}.tname{font-weight:600}.tsub{font-size:12px}
.tv{font-variant-numeric:tabular-nums;color:var(--mut)}.trow .sc{font-size:22px;min-width:34px;text-align:right}
details.past{margin-top:4px}details.past summary{cursor:pointer;font-size:13px;color:var(--mut)}
.cat-head{display:flex;align-items:baseline;gap:8px}.cat-name{font-weight:700;font-size:16px}
.cat-head .w{color:var(--mut);font-size:12px;flex:1}.cat-head .sc{font-size:24px}
.cat.muted .cat-name,.cat.muted .cat-head .w{color:var(--mut)}
.ind-h{display:grid;grid-template-columns:1fr auto 38px;gap:8px;font-size:11.5px;color:var(--faint);margin:10px 2px 2px}
.ind-h div:nth-child(n+2){text-align:right}
.inds{display:grid;gap:6px}
.ind{display:grid;grid-template-columns:1fr auto 38px;gap:8px;padding:10px;background:var(--tile);border:1px solid var(--line);border-radius:10px;align-items:start}
.ind-name{font-weight:600;font-size:14px}.ind-desc{font-size:12px;line-height:1.5;margin-top:2px}
.ind-meta{font-size:11.5px;color:var(--faint);margin-top:4px;padding-top:4px;border-top:1px dashed var(--line)}
.ind-val{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;font-size:14px}
.ind-val .u{display:block;font-size:11px;color:var(--faint)}
.ind-sc{text-align:right;font-weight:700;font-variant-numeric:tabular-nums;font-size:16px}
.ind.na{background:transparent;border-style:dashed}.ind.na .ind-name{color:var(--mut)}
.tag{font-size:10.5px;background:var(--warm);color:#fff;border-radius:4px;padding:0 5px;margin-left:6px;font-weight:500;vertical-align:1px;white-space:nowrap}
.tag.ref{background:var(--faint)}
.ranges{display:flex;gap:6px;margin:0 0 10px}
.ranges button{flex:1;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:6px;font:inherit;font-size:13px;cursor:pointer}
.ranges button.on{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.chartbox{padding:10px 8px}
svg.chart{width:100%;display:block;touch-action:pan-y}
.legend{display:flex;gap:12px;font-size:12px;color:var(--mut);margin:8px 0 0;flex-wrap:wrap}
.legend i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:4px;border-radius:2px}
.tip{font-size:12.5px;min-height:22px;font-variant-numeric:tabular-nums;display:flex;gap:12px;flex-wrap:wrap;padding:0 4px 6px}
select{width:100%;font:inherit;font-size:14px;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);margin-bottom:10px}
.scroll{overflow-x:auto;padding:4px 8px}
table.data{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
table.data th,table.data td{padding:6px;text-align:right;white-space:nowrap;border-top:1px solid var(--line)}
table.data thead th{border-top:0}
table.data th{color:var(--mut);font-weight:500}table.data th:first-child,table.data td:first-child{text-align:left}
table.data tbody tr:nth-child(even){background:color-mix(in srgb,var(--card) 60%,transparent)}
td.b{font-weight:700}
.links a{display:inline-block;margin:4px 10px 4px 0;font-size:13.5px}
footer{color:var(--mut);font-size:12px;padding:8px 0 28px}
a{color:inherit}
</style>
</head>
<body>
<main>
<h1>__TITLE__</h1>
<div class="meta">__DATE__ 更新 · BTC $__PRICE__（__PRICE_DATE__ 收盤）</div>
__STALE__

<nav class="toc" aria-label="頁面分區"><a href="#s-signal">訊號</a><a href="#s-guide">說明</a><a href="#s-timing">時機</a><a href="#s-heat">熱度</a><a href="#s-chart">走勢</a><a href="#s-ind">指標</a><a href="#s-data">數據</a></nav>

<section class="card hero" id="s-signal">
  <div class="lbl">頂部訊號</div>
  <div class="big">__SIG__</div>
  <div class="lv lv-__LVL__">__LVL_TEXT__</div>
  <div class="tiles">
    <div class="tile"><div class="k">熱度</div><div class="v sc __HEAT_BAND__">__HEAT__</div><div class="k">__HEAT_TEXT__</div></div>
    <div class="tile"><div class="k">時機</div><div class="v">__TIM__</div><div class="k">0–100</div></div>
    <div class="tile"><div class="k">熱類別</div><div class="v">__HOT__<span style="font-size:15px;color:var(--mut)">/5</span></div><div class="k">類別分數 ≥ 80</div></div>
  </div>
  <div class="formula">頂部訊號 = 熱度（7 日均）× 時機 ÷ 100　·　≥ __WIN__ 頂部窗口　·　≥ __ALERT__ 高度警戒</div>
</section>

<section class="card guide" id="s-guide">
  <header class="card-h"><span class="kicker">01</span><h2>怎麼看這個頁面</h2></header>
  <div class="card-b">
  <p><b>頂部訊號</b>是主要數字。它只有在「市場夠熱」而且「時間進入歷史上的頂部窗口」時才會升高，兩個條件缺一不可。</p>
  <ul>
    <li><b>熱度（0–100）</b>：鏈上估值、資金流、槓桿、情緒四類指標的加權平均，回答「市場現在有多熱」。冷 &lt; 40 ≤ 溫 &lt; 65 ≤ 熱。</li>
    <li><b>時機（0–100）</b>：比較「距減半天數」與「距本輪低點天數」和過去頂部的距離，回答「時間上像不像週期頂部」。過去三次頂部約在減半後 __CENTER_H__ 天、低點後 __CENTER_L__ 天。</li>
    <li><b>頂部訊號 ≥ __WIN__</b> 代表進入頂部窗口；<b>≥ __ALERT__</b> 為高度警戒。</li>
  </ul>
  <p><b>為什麼要乘上時機？</b>只看熱度時，2021 年 4 月、2024 年 3 月這些中段高點的熱度，其實比真正的週期頂部（2021-11、2025-10）還高。最終頂部的特徵是「時間點很規律」：最近三次都在減半後 525–546 天、低點後約 1,060 天。加入時機後，最近三輪的最終頂部都成為該輪訊號最高的時候。</p>
  <p><b>要注意的限制</b></p>
  <ul>
    <li>時機假設約四年的週期會延續。若週期變長或變短，訊號可能提早、延後，甚至整輪不亮，所以熱度與時機也要分開看。</li>
    <li>訊號給的是「幾個月的窗口」，不是精確的頂部日期。</li>
    <li>歷史訊號用目前的參數回推計算（樣本內），過去只有 4 次頂部可驗證。</li>
    <li>僅供參考，不構成投資建議。</li>
  </ul>
</div>
</section>

<section class="card" id="s-timing">
  <header class="card-h"><span class="kicker">02</span><h2>時機</h2><span class="hval">__TIM__</span></header>
  <div class="card-b">
  <p class="lead">兩項各自 0–100，取平均。依減半推算的本輪滿分窗口：__WIN_H__。</p>
  __TIMING__
</div>
</section>

<section class="card" id="s-heat">
  <header class="card-h"><span class="kicker">03</span><h2>熱度</h2><span class="hval"><span class="sc __HEAT_BAND__">__HEAT__</span></span></header>
  <div class="card-b">
  <p class="lead">同類指標先平均成類別分數，再依權重加總。週期法指標用過去頂部推估本輪預期頂部；歷史較短的指標用 4 年百分位，百分位超過 __PIVOT__% 才開始計分。單一指標加總時上限 120。標示「參考」的指標只顯示、不計分。</p>
  __CATS__
  <div class="note">分數條上的直線為 80 分。</div>
</div>
</section>

<section class="card" id="s-chart">
  <header class="card-h"><span class="kicker">04</span><h2>歷史走勢</h2></header>
  <div class="card-b">
  <div class="ranges" data-g="main"><button data-y="0" class="on">全部</button><button data-y="8">8 年</button><button data-y="4">4 年</button><button data-y="1">1 年</button></div>
  <div class="sub chartbox"><div class="tip" id="tip-main"></div>
  <svg class="chart" id="c-price" height="130" role="img" aria-label="BTC 價格（對數）"></svg>
  <svg class="chart" id="c-main" height="240" role="img" aria-label="頂部訊號、熱度與時機歷史"></svg>
  <div class="legend"><span><i style="background:var(--s1)"></i>頂部訊號</span><span><i style="background:var(--s2)"></i>熱度（7 日均）</span><span><i style="background:var(--s0)"></i>時機</span><span><i style="background:var(--topline)"></i>過去頂部</span></div></div>
  <div class="note">上圖為價格（對數），下圖三條線同為 0–100。虛線為 __WIN__ 與 __ALERT__ 門檻。一年以前每週一點，最近一年每日一點。</div>
</div>
</section>

<section class="card" id="s-ind">
  <header class="card-h"><span class="kicker">05</span><h2>單一指標歷史</h2></header>
  <div class="card-b">
  <select id="pick">__OPTIONS__</select>
  <div class="ranges" data-g="ind"><button data-y="0" class="on">全部</button><button data-y="8">8 年</button><button data-y="4">4 年</button><button data-y="1">1 年</button></div>
  <div class="sub chartbox"><div class="tip" id="tip-ind"></div>
  <svg class="chart" id="c-val" height="150" role="img" aria-label="指標數值歷史"></svg>
  <svg class="chart" id="c-sc" height="110" role="img" aria-label="指標分數歷史"></svg></div>
  <div class="note">上圖為原始數值，下圖為計分（0–120）；「參考」指標與時機天數沒有分數圖。</div>
</div>
</section>

<section class="card" id="s-data">
  <header class="card-h"><span class="kicker">06</span><h2>最近 30 天數據</h2></header>
  <div class="card-b">
  <div class="sub scroll">__TABLE__</div>
  <div class="links">
    <a href="latest.json">latest.json（今日完整數據）</a>
    <a href="__CSV_SCORES__">每日分數 CSV</a>
    <a href="__CSV_IND__">每日指標 CSV</a>
    <a href="__CSV_RAW__">原始資料</a>
  </div>
</div>
</section>

<footer>
資料來源：Coin Metrics Community（CC BY-NC 4.0）、DefiLlama、Farside Investors、OKX、Binance、Coinbase、alternative.me__EXTRA_SRC__。<br>
僅使用公開數據，不含任何個人資訊或交易功能；僅供參考，不構成投資建議。<br>
<a href="__REPO__">原始碼與方法說明</a> · 產生時間 __GENERATED__
</footer>
</main>
<script>
const D=__DATA__,TOPS=__TOPS__,UNITS=__UNITS__,WIN=__WIN__,ALERT=__ALERT__;
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const st={main:{years:0,hover:null},ind:{years:0,hover:null}};
const fmt=(v,u)=>v==null?'—':(Math.abs(v)>=1000?Math.round(v).toLocaleString():Math.abs(v)>=1?v.toFixed(2):v.toFixed(3))+(u?(u==='%'||u==='x'?u:' '+u):'');
function i0of(y){if(!y)return 0;const c=new Date(D.d[D.d.length-1]);c.setFullYear(c.getFullYear()-y);const s=c.toISOString().slice(0,10);return Math.max(0,D.d.findIndex(x=>x>=s));}
function chart(el,i0,series,o){
  const W=el.clientWidth,H=+el.getAttribute('height'),L=44,R=10,T=8,B=o.axis?22:6,n=D.d.length-i0;
  const x=i=>L+(W-L-R)*i/Math.max(1,n-1);
  let lo=o.min,hi=o.max;
  if(lo==null||hi==null){const v=[];series.forEach(s=>s.a.slice(i0).forEach(z=>{if(z!=null&&(!o.log||z>0))v.push(o.log?Math.log10(z):z)}));
    if(!v.length){el.innerHTML=`<text x="${W/2}" y="${H/2}" font-size="12" text-anchor="middle" fill="${css('--mut')}">無資料</text>`;return x;}
    lo=Math.min(...v);hi=Math.max(...v);if(lo===hi){lo-=1;hi+=1;}const p=(hi-lo)*.06;if(!o.log){lo-=p;hi+=p;}}
  const y=v=>{const tv=Math.min(Math.max(o.log?Math.log10(v):v,lo),hi);return T+(H-T-B)*(1-(tv-lo)/(hi-lo));};
  let g='';
  const ticks=o.ticks||(o.log?[]:niceTicks(lo,hi));
  if(o.log){for(let e=Math.ceil(lo);e<=hi;e++)ticks.push(10**e);}
  ticks.forEach(v=>{const yy=y(v);if(yy<T-1||yy>H-B+1)return;g+=`<line x1="${L}" x2="${W-R}" y1="${yy}" y2="${yy}" stroke="${css('--grid')}"/><text x="${L-5}" y="${yy+4}" font-size="11" text-anchor="end" fill="${css('--mut')}">${o.log?(v>=1000?(v/1000)+'k':v):short(v)}</text>`;});
  (o.thresholds||[]).forEach(v=>{g+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="${css('--mut')}" stroke-dasharray="4 4" opacity=".8"/>`;});
  TOPS.forEach(t=>{const i=D.d.findIndex(v=>v>=t)-i0;if(i>0&&i<n)g+=`<line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${H-B}" stroke="${css('--topline')}" stroke-dasharray="3 3" opacity=".75"/>`;});
  if(o.axis){const y0=+D.d[i0].slice(0,4),y1=+D.d[D.d.length-1].slice(0,4),s=Math.max(1,Math.ceil((y1-y0)/6));
    for(let yr=y0+1;yr<=y1;yr+=s){const i=D.d.findIndex(v=>v>=yr+'-01-01')-i0;if(i>0)g+=`<text x="${x(i)}" y="${H-6}" font-size="11" text-anchor="middle" fill="${css('--mut')}">${yr}</text>`;}}
  series.forEach(s=>{let d='',pen=false;s.a.slice(i0).forEach((v,i)=>{if(v==null||(o.log&&v<=0)){pen=false;return;}d+=(pen?'L':'M')+x(i).toFixed(1)+','+y(v).toFixed(1);pen=true;});
    g+=`<path d="${d}" fill="none" stroke="${css(s.c)}" stroke-width="${s.w||2}" stroke-linejoin="round" ${s.dash?`stroke-dasharray="${s.dash}"`:''}/>`;});
  const h=o.hover;if(h!=null&&h<n){g+=`<line x1="${x(h)}" x2="${x(h)}" y1="${T}" y2="${H-B}" stroke="${css('--fg')}" opacity=".35"/>`;
    series.forEach(s=>{const v=s.a[i0+h];if(v!=null&&(!o.log||v>0))g+=`<circle cx="${x(h)}" cy="${y(v)}" r="4" fill="${css(s.c)}" stroke="${css('--card')}" stroke-width="2"/>`;});}
  el.innerHTML=g;return x;
}
function niceTicks(lo,hi){const span=hi-lo,step=10**Math.floor(Math.log10(span/3)),m=[1,2,5,10].find(k=>span/(k*step)<=5)*step,out=[];for(let v=Math.ceil(lo/m)*m;v<=hi;v+=m)out.push(+v.toFixed(10));return out;}
function short(v){const a=Math.abs(v);return a>=1e6?(v/1e6)+'M':a>=1e3?(v/1e3)+'k':+v.toFixed(3)+'';}
function bind(els,g,draw){const L=44,R=10;const mv=ev=>{const el=ev.currentTarget,r=el.getBoundingClientRect(),cx=(ev.touches?ev.touches[0].clientX:ev.clientX)-r.left,n=D.d.length-i0of(st[g].years);
  st[g].hover=Math.max(0,Math.min(n-1,Math.round((cx-L)/(el.clientWidth-L-R)*(n-1))));draw();};
  els.forEach(e=>{e.onmousemove=mv;e.ontouchmove=mv;e.ontouchstart=mv;e.onmouseleave=()=>{st[g].hover=null;draw();};});}
function drawMain(){const s=st.main,i0=i0of(s.years);
  chart(document.getElementById('c-price'),i0,[{a:D.p,c:'--price',w:1.5}],{log:true,hover:s.hover});
  chart(document.getElementById('c-main'),i0,[{a:D.tim,c:'--s0',w:1.5},{a:D.heat,c:'--s2',w:1.6},{a:D.sig,c:'--s1',w:2.2}],{min:0,max:100,ticks:[0,25,50,75,100],thresholds:[WIN,ALERT],axis:true,hover:s.hover});
  const j=i0+(s.hover==null?D.d.length-1-i0:s.hover),f=v=>v==null?'—':Math.round(v);
  document.getElementById('tip-main').innerHTML=`<b>${D.d[j]}</b><span>價格 $${Math.round(D.p[j]).toLocaleString()}</span><span style="color:var(--s1)">頂部訊號 <b>${f(D.sig[j])}</b></span><span>熱度（7 日均） ${f(D.heat[j])}</span><span>時機 ${f(D.tim[j])}</span>`;}
function drawInd(){const s=st.ind,i0=i0of(s.years),k=document.getElementById('pick').value,v=D['v_'+k],sc=D['s_'+k];
  chart(document.getElementById('c-val'),i0,[{a:v,c:'--s2',w:1.6}],{hover:s.hover});
  const scEl=document.getElementById('c-sc');scEl.style.display=sc?'block':'none';
  if(sc)chart(scEl,i0,[{a:sc,c:'--s1',w:1.6}],{min:0,max:120,ticks:[0,40,80,120],axis:true,hover:s.hover});
  const j=i0+(s.hover==null?D.d.length-1-i0:s.hover);
  document.getElementById('tip-ind').innerHTML=`<b>${D.d[j]}</b><span>數值 <b>${fmt(v[j],UNITS[k])}</b></span>`+(sc?`<span>分數 <b>${sc[j]==null?'—':Math.round(sc[j])}</b></span>`:'');}
document.querySelectorAll('.ranges').forEach(box=>box.querySelectorAll('button').forEach(b=>b.onclick=()=>{box.querySelectorAll('button').forEach(o=>o.classList.remove('on'));b.classList.add('on');const g=box.dataset.g;st[g].years=+b.dataset.y;st[g].hover=null;g==='main'?drawMain():drawInd();}));
document.getElementById('pick').onchange=()=>{st.ind.hover=null;drawInd();};
bind([document.getElementById('c-price'),document.getElementById('c-main')],'main',drawMain);
bind([document.getElementById('c-val'),document.getElementById('c-sc')],'ind',drawInd);
const redraw=()=>{drawMain();drawInd();};
addEventListener('resize',redraw);matchMedia('(prefers-color-scheme: dark)').addEventListener('change',redraw);
redraw();
</script>
</body>
</html>
"""

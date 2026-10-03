"""產生 docs/index.html：靜態、內嵌資料、不在瀏覽器端呼叫外部 API。"""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

ZONE_TEXT = {"cold": "冷", "warm": "溫", "hot": "熱", "top_zone": "頂部區"}


def _fmt(v, unit=""):
    if v is None:
        return "—"
    a = abs(v)
    s = f"{v:,.0f}" if a >= 1000 else f"{v:,.2f}" if a >= 1 else f"{v:.3f}"
    return f"{s}{(' ' + unit) if unit and unit not in ('x', '%') else unit}"


def _method(i):
    m = i.get("method")
    if m == "cycle":
        return f"週期法：下界 {_fmt(i.get('bottom_bound'))} → 預期頂部 {_fmt(i.get('expected_top'))}"
    if m == "percentile":
        return f"滾動百分位（{i.get('history_days')} 天歷史）"
    if m == "halving":
        return f"預期頂部約在減半後 {i.get('expected_top_days')} 天"
    return ""


def render_page(latest: dict, hist: pd.DataFrame, path: Path):
    h = hist[["price", "composite"]].copy()
    h["composite"] = h["composite"].rolling(7, min_periods=1).mean()  # 圖表用 7 日均，降低雜訊
    h = h.dropna()
    series = {
        "d": [d.strftime("%Y-%m-%d") for d in h.index],
        "p": [round(float(x), 2) for x in h["price"]],
        "s": [round(float(x), 1) for x in h["composite"]],
        "tops": latest["cycle_tops"],
    }

    cats_html = []
    for key, c in latest["categories"].items():
        sc = c["score"]
        width = 0 if sc is None else min(sc, 100)
        cls = "na" if sc is None else "top" if sc >= 80 else "hot" if sc >= 65 else "warm" if sc >= 40 else "cold"
        rows = []
        for i in c["indicators"].values():
            if i["status"] != "ok":
                rows.append(f'<tr class="muted"><td>{html.escape(i["label"])}</td><td colspan="2">無免費資料</td></tr>')
                continue
            stale = ' <span class="tag">舊資料</span>' if i["stale"] else ""
            score = "—" if i["score"] is None else f'{i["score"]:.0f}'
            rows.append(
                f'<tr><td>{html.escape(i["label"])}{stale}<div class="sub">{html.escape(_method(i))}'
                f' · {i["as_of"]}</div></td><td class="num">{_fmt(i["value"], i["unit"])}</td>'
                f'<td class="num b">{score}</td></tr>')
        note = {"partial": "部分指標無資料", "unavailable": "無可用資料，權重已分給其他類別"}.get(c["status"], "")
        cats_html.append(f"""
<details class="cat">
  <summary>
    <div class="cat-head"><span>{c['label']}</span>
      <span class="w">權重 {c['weight']*100:.0f}%{f"（實際 {c['effective_weight']*100:.0f}%）" if c['effective_weight'] and abs(c['effective_weight']-c['weight'])>0.005 else ""}</span>
      <span class="sc {cls}">{'—' if sc is None else f'{sc:.0f}'}</span></div>
    <div class="bar"><div class="fill {cls}" style="width:{width}%"></div><div class="m80"></div></div>
    {f'<div class="sub">{note}</div>' if note else ''}
  </summary>
  <table><thead><tr><th>指標</th><th class="num">數值</th><th class="num">分數</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table>
</details>""")

    zone = latest["zone"]
    stale_banner = ('<div class="banner">部分資料源今日抓取失敗，沿用前一次數值（標記「舊資料」）。</div>'
                    if latest["stale"] else "")
    page = TEMPLATE.format(
        date=latest["date"], price=f'{latest["price_usd"]:,.0f}', price_date=latest["price_date"],
        score=f'{latest["composite_score"]:.0f}', zone=zone, zone_text=ZONE_TEXT[zone],
        hot=latest["hot_categories"], cats="".join(cats_html), stale_banner=stale_banner,
        generated=latest["generated_at"], data=json.dumps(series, separators=(",", ":")),
        tops="、".join(t[:7] for t in latest["cycle_tops"]),
    )
    path.write_text(page, encoding="utf-8")


TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC 週期頂部儀表板</title>
<meta name="description" content="每日更新的比特幣週期頂部分數，綜合鏈上、資金流、衍生品與情緒指標。">
<style>
:root{{--bg:#f6f7f9;--card:#fff;--fg:#14171c;--mut:#667080;--line:#e3e6eb;
--cold:#3b82c4;--warm:#c99a1e;--hot:#e0702a;--top:#d23b3b;--price:#8a93a3;--na:#b9c0ca}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0f1216;--card:#181c22;--fg:#e8ebef;--mut:#98a2b3;
--line:#2a3039;--cold:#5ea3e0;--warm:#e2b23a;--hot:#f08a45;--top:#f05a5a;--price:#7d8696;--na:#4a525e}}}}
:root[data-theme="dark"]{{--bg:#0f1216;--card:#181c22;--fg:#e8ebef;--mut:#98a2b3;--line:#2a3039;
--cold:#5ea3e0;--warm:#e2b23a;--hot:#f08a45;--top:#f05a5a;--price:#7d8696;--na:#4a525e}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"PingFang TC","Noto Sans TC","Microsoft JhengHei",sans-serif}}
main{{max-width:720px;margin:0 auto;padding:16px}}
h1{{font-size:17px;margin:4px 0 2px}}
.meta{{color:var(--mut);font-size:13px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:12px 0}}
.hero{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;text-align:center}}
.hero .big{{font-size:44px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}}
.hero .lbl{{color:var(--mut);font-size:12px}}
.zone{{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:700;color:#fff;margin-top:6px;font-size:20px}}
.z-cold{{background:var(--cold)}}.z-warm{{background:var(--warm)}}.z-hot{{background:var(--hot)}}.z-top_zone{{background:var(--top)}}
.banner{{background:color-mix(in srgb,var(--warm) 18%,transparent);border-radius:10px;padding:10px 12px;font-size:13px;margin:12px 0}}
.cat{{border-top:1px solid var(--line);padding:10px 0}}.cat:first-of-type{{border-top:0}}
.cat summary{{list-style:none;cursor:pointer}}.cat summary::-webkit-details-marker{{display:none}}
.cat-head{{display:flex;align-items:baseline;gap:8px}}.cat-head span:first-child{{font-weight:600}}
.cat-head .w{{color:var(--mut);font-size:12px;flex:1}}
.sc{{font-weight:700;font-size:18px;font-variant-numeric:tabular-nums}}
.sc.cold{{color:var(--cold)}}.sc.warm{{color:var(--warm)}}.sc.hot{{color:var(--hot)}}.sc.top{{color:var(--top)}}.sc.na{{color:var(--na)}}
.bar{{position:relative;height:10px;background:var(--line);border-radius:6px;margin-top:6px;overflow:hidden}}
.fill{{height:100%;border-radius:6px}}.fill.cold{{background:var(--cold)}}.fill.warm{{background:var(--warm)}}
.fill.hot{{background:var(--hot)}}.fill.top{{background:var(--top)}}
.m80{{position:absolute;left:80%;top:0;bottom:0;width:2px;background:var(--fg);opacity:.35}}
table{{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}}
th{{text-align:left;color:var(--mut);font-weight:500;padding:4px 0}}
td{{padding:6px 0;border-top:1px solid var(--line);vertical-align:top}}
.num{{text-align:right;white-space:nowrap;padding-left:8px;font-variant-numeric:tabular-nums}}.b{{font-weight:700}}
.sub{{color:var(--mut);font-size:11.5px}}.muted td{{color:var(--mut)}}
.tag{{font-size:10.5px;background:var(--warm);color:#fff;border-radius:4px;padding:0 4px;margin-left:4px}}
.hint{{color:var(--mut);font-size:12px;margin-top:6px}}
.ranges{{display:flex;gap:6px;margin-bottom:8px}}
.ranges button{{flex:1;border:1px solid var(--line);background:transparent;color:var(--fg);border-radius:8px;padding:6px;font:inherit;font-size:13px}}
.ranges button.on{{background:var(--fg);color:var(--bg)}}
#chart{{width:100%;height:280px;display:block;touch-action:pan-y}}
.legend{{display:flex;gap:14px;font-size:12px;color:var(--mut);margin-top:4px;flex-wrap:wrap}}
.legend i{{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:4px}}
#tip{{font-size:12.5px;min-height:20px;font-variant-numeric:tabular-nums}}
footer{{color:var(--mut);font-size:12px;padding:8px 0 24px}}
a{{color:inherit}}
</style>
</head>
<body>
<main>
<h1>BTC 週期頂部儀表板</h1>
<div class="meta">{date} 更新 · BTC ${price}（{price_date}）</div>
{stale_banner}
<section class="card hero">
  <div><div class="lbl">總分</div><div class="big">{score}</div><div class="lbl">0–100</div></div>
  <div><div class="lbl">區間</div><div class="zone z-{zone}">{zone_text}</div><div class="lbl" style="margin-top:6px">{zone}</div></div>
  <div><div class="lbl">熱類別</div><div class="big">{hot}<span style="font-size:20px;color:var(--mut)">/5</span></div><div class="lbl">分數 ≥ 80</div></div>
</section>
<div class="hint">頂部區條件：總分 ≥ 80 且熱類別 ≥ 3。冷 &lt; 40 ≤ 溫 &lt; 65 ≤ 熱。</div>

<section class="card">
{cats}
<div class="hint">點類別可展開指標。直線刻度為 80 分。</div>
</section>

<section class="card">
  <div class="ranges"><button data-y="0" class="on">全部</button><button data-y="8">8 年</button><button data-y="4">4 年</button><button data-y="1">1 年</button></div>
  <div id="tip"></div>
  <svg id="chart" role="img" aria-label="總分與價格歷史走勢"></svg>
  <div class="legend"><span><i style="background:var(--hot)"></i>總分 7 日均（右軸 0–100）</span><span><i style="background:var(--price)"></i>BTC 價格（左軸，對數）</span><span><i style="border-top:2px dashed var(--top);height:0"></i>過去頂部：{tops}</span></div>
</section>

<footer>
資料來源：Coin Metrics Community、DefiLlama、OKX、Binance、Coinbase、alternative.me。<br>
歷史分數以目前擬合參數計算（樣本內），僅供參考，不構成投資建議。<br>
<a href="latest.json">latest.json</a> · 產生時間 {generated}
</footer>
</main>
<script>
const D={data};
const svg=document.getElementById('chart'),tip=document.getElementById('tip');
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
let years=0;
function draw(){{
  const W=svg.clientWidth,H=svg.clientHeight,L=44,R=30,T=10,B=22;
  let i0=0;
  if(years){{const c=new Date(D.d[D.d.length-1]);c.setFullYear(c.getFullYear()-years);const cs=c.toISOString().slice(0,10);i0=D.d.findIndex(x=>x>=cs);}}
  const d=D.d.slice(i0),p=D.p.slice(i0),s=D.s.slice(i0),n=d.length;
  const lp=p.map(Math.log10),mn=Math.min(...lp),mx=Math.max(...lp);
  const x=i=>L+(W-L-R)*i/(n-1),yp=v=>T+(H-T-B)*(1-(Math.log10(v)-mn)/(mx-mn||1)),ys=v=>T+(H-T-B)*(1-v/100);
  const path=(arr,f)=>arr.map((v,i)=>(i?'L':'M')+x(i).toFixed(1)+','+f(v).toFixed(1)).join('');
  let g='';
  [20,40,60,80].forEach(v=>g+=`<line x1="${{L}}" x2="${{W-R}}" y1="${{ys(v)}}" y2="${{ys(v)}}" stroke="${{css('--line')}}"/><text x="${{W-R+4}}" y="${{ys(v)+4}}" font-size="10" fill="${{css('--mut')}}">${{v}}</text>`);
  for(let e=Math.ceil(mn);e<=mx;e++){{const v=10**e;g+=`<text x="${{L-4}}" y="${{yp(v)+4}}" font-size="10" text-anchor="end" fill="${{css('--mut')}}">${{v>=1000?(v/1000)+'k':v}}</text>`;}}
  const y0=+d[0].slice(0,4),y1=+d[n-1].slice(0,4),step=Math.max(1,Math.ceil((y1-y0)/6));
  for(let y=y0+1;y<=y1;y+=step){{const i=d.findIndex(v=>v>=y+'-01-01');if(i>0)g+=`<text x="${{x(i)}}" y="${{H-6}}" font-size="10" text-anchor="middle" fill="${{css('--mut')}}">${{y}}</text>`;}}
  D.tops.forEach(t=>{{const i=d.findIndex(v=>v>=t);if(i>=0)g+=`<line x1="${{x(i)}}" x2="${{x(i)}}" y1="${{T}}" y2="${{H-B}}" stroke="${{css('--top')}}" stroke-dasharray="4 3" opacity=".7"/>`;}});
  g+=`<path d="${{path(p,yp)}}" fill="none" stroke="${{css('--price')}}" stroke-width="1.3"/>`;
  g+=`<path d="${{path(s,ys)}}" fill="none" stroke="${{css('--hot')}}" stroke-width="1.6"/>`;
  g+=`<line id="cur" y1="${{T}}" y2="${{H-B}}" stroke="${{css('--fg')}}" opacity="0" />`;
  svg.innerHTML=g;
  const show=i=>{{tip.textContent=`${{d[i]}}　總分 7 日均 ${{s[i].toFixed(0)}}　價格 $${{Math.round(p[i]).toLocaleString()}}`;const c=svg.querySelector('#cur');c.setAttribute('x1',x(i));c.setAttribute('x2',x(i));c.setAttribute('opacity','.4');}};
  const mv=ev=>{{const r=svg.getBoundingClientRect(),cx=(ev.touches?ev.touches[0].clientX:ev.clientX)-r.left;show(Math.max(0,Math.min(n-1,Math.round((cx-L)/(W-L-R)*(n-1)))));}};
  svg.onmousemove=mv;svg.ontouchmove=mv;svg.ontouchstart=mv;
  show(n-1);
}}
document.querySelectorAll('.ranges button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.ranges button').forEach(o=>o.classList.remove('on'));b.classList.add('on');years=+b.dataset.y;draw();}});
addEventListener('resize',draw);
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
draw();
</script>
</body>
</html>
"""

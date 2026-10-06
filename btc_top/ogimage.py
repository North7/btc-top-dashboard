"""每日分享預覽圖（docs/og.png，1200×630）：分享連結到 LINE、Facebook、X 時顯示當日訊號。

只用英文與數字（字型為 Archivo，OFL 授權，見 assets/OFL.txt）。產生失敗不影響主流程。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = Path(__file__).parent / "assets" / "Archivo.ttf"
W, H = 1200, 630
BG = (3, 4, 10)


def _font(size, weight=900, width=100):
    f = ImageFont.truetype(str(FONT), size)
    try:
        f.set_variation_by_axes([weight, width])
    except Exception:  # noqa: BLE001
        pass
    return f


def make_og(latest: dict, path: Path):
    bs, ts = latest["bottom_signal"], latest["top_signal"]
    bottom_first = True  # 網站預設顯示底部模式
    img = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W, H), BG)
    g = ImageDraw.Draw(glow)
    g.ellipse((-220, -260, 620, 360), fill=(15, 140, 110))     # 綠（底部）
    g.ellipse((420, -300, 1260, 330), fill=(26, 110, 190))     # 藍
    g.ellipse((760, 330, 1420, 900), fill=(150, 40, 110))      # 紫紅（頂部）
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.blend(img, glow, .85)
    d = ImageDraw.Draw(img)

    white, mut = (243, 245, 255), (160, 168, 196)
    d.text((64, 54), "TIDEMARK", font=_font(34, 800), fill=white)
    d.text((64, 98), "BTC CYCLE SIGNALS  ·  " + latest["date"], font=_font(20, 500), fill=mut)

    blocks = [("BOTTOM SIGNAL", bs, (32, 227, 178)), ("TOP SIGNAL", ts, (255, 77, 109))]
    if not bottom_first:
        blocks.reverse()
    x = 64
    for label, val, col in blocks:
        d.text((x, 180), label, font=_font(22, 700), fill=col)
        d.text((x - 6, 205), f"{val:.0f}", font=_font(230, 900), fill=white)
        x += 540

    d.line((64, 492, W - 64, 492), fill=(70, 76, 100), width=1)
    d.text((64, 516), f"BTC ${latest['price_usd']:,.0f}", font=_font(40, 800), fill=white)
    d.text((64, 568), f"Heat {latest['heat_score']:.0f}  ·  Timing {latest['timing_score']:.0f}  ·  "
                      f"Coldness {latest['cold_score']:.0f}", font=_font(22, 500), fill=mut)
    d.text((W - 64, 568), "north7.github.io/tidemark", font=_font(22, 600), fill=mut, anchor="ra")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)

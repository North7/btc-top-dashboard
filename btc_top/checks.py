"""每日輸出的自動檢查。

`python -m btc_top.checks`：有「錯誤」時結束代碼為 1（工作流程會停止、不 commit，並發出故障通知）；
「警告」（資料過期等）不阻擋更新，由 notify 一併通知。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def run_checks(docs: Path = DOCS) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    try:
        latest = json.loads((docs / "latest.json").read_text())
    except Exception as e:  # noqa: BLE001
        return [f"latest.json 無法讀取：{e}"], []

    # 必要欄位與數值範圍
    for k in ("date", "price_usd", "top_signal", "heat_score", "timing_score", "bottom_signal", "cold_score", "categories", "bottom"):
        if latest.get(k) is None:
            errors.append(f"latest.json 缺少欄位 {k}")
    for k in ("top_signal", "heat_score", "timing_score", "bottom_signal", "cold_score"):
        v = latest.get(k)
        if isinstance(v, (int, float)) and not (0 <= v <= 120):
            errors.append(f"{k} 數值異常：{v}")
    p = latest.get("price_usd")
    if isinstance(p, (int, float)) and not (1_000 < p < 10_000_000):
        errors.append(f"價格異常：{p}")
    for k in ("strategy", "midterm", "scenarios"):
        if not latest.get(k):
            warnings.append(f"latest.json 沒有 {k} 區塊（該功能計算失敗）")

    # 頁面
    for f, en in (("index.html", False), ("en/index.html", True)):
        path = docs / f
        if not path.exists():
            errors.append(f"缺少 {f}")
            continue
        s = path.read_text()
        if len(s) < 100_000:
            errors.append(f"{f} 大小異常（{len(s)} bytes）")
        left = sorted(set(re.findall(r"__[A-Z0-9_]{3,}__", s)))
        if left:
            errors.append(f"{f} 有未替換的佔位符：{', '.join(left[:5])}")
        if "⟪" in s or "⟫" in s:
            errors.append(f"{f} 有未處理的雙語標記")
        if en:
            body = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", s, flags=re.S)
            body = re.sub(r"<[^>]+>", " ", body).replace("中", "")  # 語言切換按鈕的「中」是刻意的
            cjk = sorted(set(re.findall(r"[一-鿿]+", body)))
            if cjk:
                errors.append(f"英文頁有殘留中文：{'、'.join(cjk[:8])}")

    # 資料新鮮度（警告）
    today = pd.Timestamp(latest.get("date"))
    pd_ = pd.Timestamp(latest.get("price_date", latest.get("date")))
    if (today - pd_).days > 3:
        warnings.append(f"價格資料停在 {pd_.date()}（落後 {(today - pd_).days} 天）")
    for name, st in (latest.get("sources") or {}).items():
        if st.get("stale"):
            warnings.append(f"資料源 {name} 過期或抓取失敗（最新 {st.get('last_date')}）")
    return errors, warnings


def main():
    errors, warnings = run_checks()
    for w in warnings:
        print("警告：", w)
    for e in errors:
        print("錯誤：", e)
    if errors:
        sys.exit(1)
    print("檢查通過")


if __name__ == "__main__":
    main()

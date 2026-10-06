"""重要事件偵測：比較昨天與今天的 latest.json，找出值得通知的變化（訊號跨門檻、策略動作、趨勢翻轉、驗證判定）。"""
from __future__ import annotations

import pandas as pd

# cron-job.org 觸發用的 GitHub 權杖到期日（更換權杖後請一併更新）
CRON_TOKEN_EXPIRES = "2027-10-06"

LEVEL_ZH = {"none": "未觸發", "window": "頂部窗口", "alert": "高度警戒", "zone": "底部區", "strong": "強烈底部"}
WHY_ZH = {"st_down": "週線 Supertrend 轉空", "st_up": "週線 Supertrend 轉多", "bsig": "底部訊號 ≥ 50"}
STATUS_ZH = {"testing": "驗證中", "supported": "支持「本輪低點即週期底部」", "classic": "傳統型底部（曾出現估值投降）"}


def _get(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def detect(old: dict | None, new: dict) -> list[dict]:
    """回傳事件列表 [{"type", "text"}]。old 為 None（第一次執行）時不產生訊號事件。"""
    ev = []
    if old:
        a, b = old.get("bottom_level"), new.get("bottom_level")
        if a and b and a != b:
            ev.append({"type": "bottom_level", "text": f"底部訊號：{LEVEL_ZH.get(a, a)} → {LEVEL_ZH.get(b, b)}（{new['bottom_signal']:.0f}）"})
        a, b = old.get("signal_level"), new.get("signal_level")
        if a and b and a != b:
            ev.append({"type": "signal_level", "text": f"頂部訊號：{LEVEL_ZH.get(a, a)} → {LEVEL_ZH.get(b, b)}（{new['top_signal']:.0f}）"})
        so, sn = old.get("strategy") or {}, new.get("strategy") or {}
        if so and sn:
            if so.get("state") != sn.get("state"):
                t = (sn.get("trades") or [{}])[-1]
                act = "全部賣出" if sn["state"] == "cash" else "全部買回"
                ev.append({"type": "strategy_trade",
                           "text": f"週期策略：{act}（{WHY_ZH.get(t.get('why'), t.get('why'))}，價格 ${t.get('price', 0):,.0f}）"})
            elif not so.get("armed") and sn.get("armed"):
                ev.append({"type": "strategy_arm", "text": "週期策略：進入警戒（頂部訊號或頂部時機 ≥ 50），之後週線 Supertrend 轉空就賣出"})
        do, dn = _get(old, "midterm", "supertrend_weekly", "direction"), _get(new, "midterm", "supertrend_weekly", "direction")
        if do and dn and do != dn:
            line = _get(new, "midterm", "supertrend_weekly", "line")
            ev.append({"type": "supertrend", "text": f"週線 Supertrend 翻{'多' if dn == 'up' else '空'}（{'支撐' if dn == 'up' else '壓力'} ${line or 0:,.0f}）"})
        co, cn = _get(old, "bottom", "cycle_test", "status"), _get(new, "bottom", "cycle_test", "status")
        if co and cn and co != cn:
            ev.append({"type": "cycle_test", "text": f"週期結構驗證：{STATUS_ZH.get(co, co)} → {STATUS_ZH.get(cn, cn)}"})
    # 權杖到期提醒：到期前 30 天、7 天、當天
    days = (pd.Timestamp(CRON_TOKEN_EXPIRES) - pd.Timestamp(new["date"])).days
    if days in (30, 7, 0):
        ev.append({"type": "token", "text": f"提醒：每日自動更新用的 GitHub 權杖將在 {days} 天後（{CRON_TOKEN_EXPIRES}）到期，請重新產生並更新 cron-job.org 的設定"})
    return ev

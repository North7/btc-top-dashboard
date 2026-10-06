"""LINE 通知（LINE 官方帳號 Messaging API 的 push message）。

金鑰放在 GitHub Secrets：LINE_CHANNEL_TOKEN（Channel access token）、LINE_USER_ID（你的 User ID）。
沒有設定時只印出訊息、不發送。

python -m btc_top.notify            每日：有事件或資料警告時才發送
python -m btc_top.notify --failure  每日更新失敗（帶 RUN_URL 環境變數）
python -m btc_top.notify --test     測試訊息
"""
from __future__ import annotations

import json
import os
import sys

import requests

from btc_top.checks import DOCS, run_checks

SITE = "https://north7.github.io/tidemark/"


def send(text: str) -> bool:
    token, to = os.environ.get("LINE_CHANNEL_TOKEN"), os.environ.get("LINE_USER_ID")
    print(text)
    if not token or not to:
        print("（未設定 LINE_CHANNEL_TOKEN／LINE_USER_ID，不發送）")
        return False
    r = requests.post("https://api.line.me/v2/bot/message/push", timeout=30,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                      json={"to": to, "messages": [{"type": "text", "text": text[:4900]}]})
    print("LINE 回應：", r.status_code, r.text[:200])
    return r.ok


def main():
    args = sys.argv[1:]
    if "--test" in args:
        send(f"Tidemark 測試通知：LINE 設定成功，之後有重要事件會傳到這裡。\n{SITE}")
        return
    if "--failure" in args:
        send(f"⚠️ Tidemark 每日更新失敗\n網站與 latest.json 維持前一天的數據，請查看執行紀錄：\n{os.environ.get('RUN_URL', '')}")
        return
    latest = json.loads((DOCS / "latest.json").read_text())
    events = latest.get("events") or []
    _, warnings = run_checks()
    if not events and not warnings:
        print("今天沒有需要通知的事件")
        return
    lines = [f"Tidemark {latest['date']}　BTC ${latest['price_usd']:,.0f}"]
    if events:
        lines += ["", "【重要事件】"] + [f"• {e['text']}" for e in events]
    if warnings:
        lines += ["", "【資料警告】"] + [f"• {w}" for w in warnings]
    lines += ["", f"頂部訊號 {latest['top_signal']:.0f}｜底部訊號 {latest['bottom_signal']:.0f}", SITE]
    send("\n".join(lines))


if __name__ == "__main__":
    main()

"""列出簡體版裡 OpenCC（tw2sp）做的「用語替換」，供人工檢查是否適合本站語境。只讀檔，不寫檔。

用法：.venv/bin/python .claude/skills/ship/hans_terms.py
不適合的替換加到 btc_top/page.py 的 HANS_FIX（例如 指针→指标、仿真→模拟）。
"""
import difflib
import re
from pathlib import Path

from opencc import OpenCC

ROOT = Path(__file__).resolve().parents[3]
s = (ROOT / "docs/index.html").read_text()
tw2sp, t2s = OpenCC("tw2sp"), OpenCC("t2s")
pairs = {}
for run in set(re.findall(r"[㐀-鿿]+", s)):
    a, b = tw2sp.convert(run), t2s.convert(run)
    if a == b:
        continue
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, b, a).get_opcodes():
        if op != "equal":
            pairs.setdefault((b[i1:i2], a[j1:j2]), b[max(0, i1 - 3):i2 + 3])
for (b, a), ctx in sorted(pairs.items()):
    print(f"{b} → {a}\t（例：{ctx}）")

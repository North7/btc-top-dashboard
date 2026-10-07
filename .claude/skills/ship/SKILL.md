---
name: ship
description: 把 Tidemark 的修改安全地更新上線：同步 GitHub 最新版、重跑數據與頁面、自動檢查、三語與手機／電腦畫面確認、提交並推送。使用者說「推送」「上線」「commit」「更新到 GitHub」，或改完程式／頁面要發布時使用。
---

# 更新上線

使用者不是工程師：每一步用一句繁體中文說明在做什麼；最後回報「改了什麼、網址、有沒有需要使用者動手的事」。
推送是對外公開的動作：只在使用者要求推送、或已明確同意時執行。

## 0. 推送前的安全檢查

- 倉庫是公開的：diff 裡不可有個人持倉、資產、成本、個人買賣決定、使用者日報的策略規則、任何金鑰或權杖
  （cron-job.org 的權杖只存在 cron-job.org；LINE 金鑰只放 GitHub Secrets）。
- 不可加入作品集頁 `docs/case-study/` 的連結到網站或 README。
- `git status` 看清楚要提交哪些檔案；`.claude/launch.json` 等本機設定不用提交。

## 1. 先同步 GitHub 上的版本（最容易出錯的一步）

GitHub Actions 每天 UTC 00:15 左右會自動提交「data: daily update 日期」，並寫入**不可改寫**的紀錄檔。
本機重跑會產生不同時間戳的同一筆紀錄；若直接推送，會覆蓋掉正式紀錄。所以：

```bash
git fetch -q && git log --oneline HEAD..origin/main
```

- 遠端有新提交時：本機的 `data/`、`docs/` 都是可以重新產生的輸出，先丟掉再同步（**只丟這兩個資料夾，程式碼的修改要保留**）：
  ```bash
  git checkout -- data docs
  git pull -q --ff-only
  ```
  若有本機新產生、但遠端也有的未追蹤檔（例如 `data/strategy_ledger.csv`），先確認內容只是同一天的重複紀錄再刪除本機那份。
  `docs/case-study/` 是手動維護的作品集頁，若有未提交的修改不可丟掉，先單獨處理。
- 不可改寫的檔案：`data/strategy_ledger.csv`（只能新增列）、`data/scenario_snapshot.json`、`data/cycle_test.json`（凍結的假說）。

## 2. 重跑與自動檢查

```bash
.venv/bin/python run.py
.venv/bin/python -m btc_top.checks
```

- `checks` 有「錯誤」就不能推送：先修好。「警告」（資料過期等）照實告訴使用者。
- 確認不可改寫的檔案只有新增、沒有刪改（這行沒有輸出才對）：
  ```bash
  git diff -U0 data/strategy_ledger.csv data/scenario_snapshot.json data/cycle_test.json | grep '^-[^-]'
  ```

## 3. 頁面有改時：看畫面

- 預覽：`.claude/launch.json` 的 `docs`（port 8766）；若 port 已被本機的 http.server 占用，直接開 `http://localhost:8766`。
  網址加 `?nolang` 可避免依語言自動導向，例如 `http://localhost:8766/zh-hans/?nolang#mid`。
- 三個語言都要看：`/`（繁體）、`/zh-hans/`、`/en/`。英文版不可殘留中文；新增的畫面文字都要寫成 `⟪中文|English⟫`。
- 寬度：電腦（≥1200）與手機（resize_window mobile）；看頁首有沒有被擠爆、選單有沒有被遮住或透明。測完把視窗恢復成 desktop，並清掉測試時存的 `localStorage` 語言設定。
- 深淺色：預設深色，也要看淺色。
- 有新增中文文字時，檢查簡體版的用語替換，不適合的加到 `btc_top/page.py` 的 `HANS_FIX`，再重跑一次：
  ```bash
  .venv/bin/python .claude/skills/ship/hans_terms.py
  ```
  已知要修正的：指针→指标、仿真→模拟、拷贝→复制、页眉→顶栏、缺省→默认、水准→水平。

## 4. 文件同步

行為、數字或頁面結構有變時，同步更新 README（給讀者）與 CLAUDE.md（給之後的 Claude）；策略或回測數字變了，
還要檢查 `docs/case-study/index.html` 的數字（只改文字，不加連結）。

## 5. 提交與推送

提交訊息用繁體中文：第一行一句話摘要，下面條列重點，最後加上系統提示要求的 Co-Authored-By 行。

```bash
git add <要提交的檔案>
git commit -q -F - <<'EOF'
摘要

- 重點

Co-Authored-By: ...
EOF
git pull -q --rebase -X theirs
git -c credential.helper= -c credential.helper="!$HOME/.local/bin/gh auth git-credential" push -q
git log --oneline -2
```

`pull --rebase -X theirs` 之前一定要先做第 1 步；否則它會用本機版本蓋掉遠端的每日紀錄。

## 6. 回報

- 改了什麼（白話、條列）、檢查結果、還沒做的事。
- 網址：儀表板 https://north7.github.io/tidemark/ （簡體 /zh-hans/、英文 /en/），GitHub Pages 約 1 分鐘後生效。
- 需要使用者動手的事要明確說點哪裡。

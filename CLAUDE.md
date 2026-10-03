# BTC 週期頂部儀表板（btc-top-dashboard）

## 給 Claude Code 的說明
使用者不是工程師。請你負責全部的建置與部署，每一步用繁體中文簡短說明在做什麼。
需要使用者動手的事（登入、授權、安裝）要明確告訴他點哪裡。
安裝任何東西或執行有副作用的指令前，先徵求同意。

## 目標
每天自動抓取 BTC 鏈上、資金流、衍生品、情緒數據，計算「週期頂部分數」，輸出：
1. `docs/latest.json`：當日分數（供每日報告讀取）
2. `docs/index.html`：手機友善的儀表板頁面（GitHub Pages）
3. `data/`：歷史時間序列（CSV），供計算百分位與日後回測

用途是在 2028 減半後的週期（預期頂部 2029–2030）辨識頂部區。只提供參考，不接任何交易功能。

## 硬性限制
- 倉庫為公開倉庫：**禁止寫入任何個人持倉、資產、成本、賣出計畫或規則參數**，只放公開市場數據與程式。
- 不使用任何交易所的交易 API 金鑰；只用公開端點。
- 第一版只用免費資料源，不需要任何金鑰。若之後加入付費源，金鑰一律放 GitHub Secrets，不可寫入程式或 commit。
- 抓取失敗時沿用前一日數值並在 JSON 標記 `stale: true`，不可讓整個流程失敗。

## 技術架構
- Python 3.11+，套件：pandas、requests、numpy（必要時再加）
- 每日由 GitHub Actions 排程執行（UTC 00:15，在每日報告 00:40 之前完成）
- 執行後自動 commit 更新的 `data/` 與 `docs/`
- GitHub Pages 從 `docs/` 發布

## 指標與權重
同一類內的指標先平均成類別分數，再按權重加總，避免高度相關的指標重複計分。

### 一、鏈上估值（35%）
MVRV Z-score、NUPL、Puell Multiple、Realized Price 倍數（價格 / 實現價格）
來源：Coin Metrics Community API（免費）。先查詢 catalog 確認可用欄位，例如 PriceUSD、CapMrktCurUSD、CapRealUSD、CapMVRVCur、IssTotUSD 或 RevUSD；不可用的指標自行由可用欄位推導，或標記為缺漏。

### 二、持有者行為（20%）
長期持有者供給變化、LTH-SOPR、CDD / Dormancy、交易所淨流入
第一版：先找免費來源；找不到就在 JSON 標記 `unavailable`，該類權重按比例分給其他類，並在 README 列出可用的付費選項（Glassnode、CryptoQuant）。

### 三、資金流與機構（20%）
現貨 ETF 每日淨流入（30 日累計與動能）、穩定幣總供給 90 日增速、Coinbase 溢價（若有免費源）
來源：ETF 用 Farside 網站表格；穩定幣用 DefiLlama stablecoins API。

### 四、槓桿與衍生品（15%）
永續資金費率（7 日均）、未平倉量 / 市值、期現基差
來源：OKX 與 Binance 公開 API。

### 五、情緒與週期（10%）
恐懼貪婪指數（alternative.me）、Google Trends「bitcoin」（若不穩定可先跳過）、距最近一次減半天數（固定日期計算）

## 正規化方法（核心）
經典指標每輪頂部讀數都在下降，所以不用固定紅線：
1. 歷史週期頂部日期：2013-12、2017-12、2021-11、2025-10。實際頂部日由價格數據取該月最高收盤日，不要寫死價格。
2. 對每個指標，取各次頂部當日數值，以對數線性擬合遞減趨勢，推估「本輪預期頂部值」。
3. 同樣取各週期底部數值作為下界。
4. 指標分數 = 當前值在「底部下界 → 本輪預期頂部值」之間的位置，換算成 0–100，可超過 100。
5. 歷史資料不足 3 個週期的指標（如 ETF），改用該指標自身歷史的滾動百分位。

## 輸出
- `composite_score`：0–100 加權總分
- `hot_categories`：類別分數 ≥ 80 的類別數（0–5）
- `zone`：`cold` / `warm` / `hot` / `top_zone`（top_zone 條件：總分 ≥ 80 且 hot_categories ≥ 3）
- 各類別分數、各指標原始值與分數、資料日期、stale 與 unavailable 標記

`latest.json` 範例結構：
```json
{
  "date": "2026-10-03",
  "composite_score": 0,
  "hot_categories": 0,
  "zone": "cold",
  "categories": {
    "onchain_valuation": {"score": 0, "weight": 0.35, "indicators": {}},
    "holder_behavior": {"score": null, "weight": 0.20, "status": "unavailable"}
  }
}
```

## 頁面（docs/index.html）
- 繁體中文、手機優先、支援深色模式
- 最上方：總分、zone、熱類別數
- 中段：五類別分數條
- 下方：總分與價格的歷史走勢圖，標出過去頂部日期
- 只用靜態檔案與內嵌資料，不在瀏覽器端呼叫外部 API

## 部署步驟（由 Claude Code 執行）
1. 確認 git 與 GitHub CLI（gh）已安裝，沒有就引導安裝
2. `gh auth login`：告訴使用者瀏覽器會跳出授權頁，請他點同意
3. 建立公開倉庫 `btc-top-dashboard` 並推送
4. 先在本地執行一次，回補歷史數據並確認輸出正確
5. 設定 GitHub Actions 每日排程，並手動觸發一次確認成功
6. 開啟 GitHub Pages（來源：main 分支 /docs）
7. 最後給使用者兩個網址：儀表板頁面與 latest.json

## 完成後
把 latest.json 網址交給使用者，讓他加進每日報告任務：每天讀取該網址，將總分、zone、熱類別數寫入報告並解讀。

## 之後的版本（先不做）
- v2：接入付費持有者行為數據
- v3：用同一套歷史數據回測賣出規則（規則參數只放本機，不進公開倉庫）

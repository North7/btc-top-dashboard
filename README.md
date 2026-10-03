# BTC 週期頂部儀表板

每天自動抓取 BTC 的公開市場數據（鏈上、資金流、衍生品、情緒），計算 0–100 的「週期頂部分數」。
用途是在 2028 年減半後的週期（預期頂部 2029–2030）辨識頂部區。**僅供參考，不構成投資建議，不含任何交易功能。**

- 儀表板：`https://<帳號>.github.io/btc-top-dashboard/`
- 當日分數：`https://<帳號>.github.io/btc-top-dashboard/latest.json`

## 輸出

| 檔案 | 內容 |
|---|---|
| `docs/latest.json` | 當日總分、zone、熱類別數、各類別與指標的原始值和分數、stale / unavailable 標記 |
| `docs/index.html` | 手機版儀表板（靜態、資料內嵌，瀏覽器不呼叫外部 API） |
| `data/raw/*.csv` | 各資料源的原始歷史（每日合併更新） |
| `data/indicators.csv` | 各指標每日數值 |
| `data/scores.csv` | 每日總分、類別分數、指標分數（2011 年起） |

zone 規則：`cold` < 40 ≤ `warm` < 65 ≤ `hot`；`top_zone` = 總分 ≥ 80 且熱類別（類別分數 ≥ 80）≥ 3。

## 指標與資料源（全部免費、無需金鑰）

| 類別（權重） | 指標 | 來源 | 計分方法 |
|---|---|---|---|
| 鏈上估值（35%） | MVRV Z-score、NUPL、實現價格倍數 | Coin Metrics Community | 週期法 |
| | Puell Multiple | Coin Metrics（IssTotUSD / 365 日均） | 百分位（見下方說明） |
| 持有者行為（20%） | 交易所 30 日淨流入（占流通量 %） | Coin Metrics | 百分位 |
| 資金流與機構（20%） | ETF 30 日累計淨流入、ETF 流入動能 | Farside | 百分位 |
| | 穩定幣總供給 90 日增速 | DefiLlama | 百分位 |
| | Coinbase 溢價（7 日均） | Coinbase BTC-USD ÷ OKX BTC-USDT | 百分位 |
| 槓桿與衍生品（15%） | 資金費率 7 日均（年化） | Binance（2019 起），OKX 備援 | 百分位 |
| | 未平倉量 / 市值 | OKX（全市場 BTC 合約），Binance 備援 | 百分位 |
| | 期現基差（年化） | Binance 當季合約 K 線（2021 起），OKX 備援 | 百分位 |
| 情緒與週期（10%） | 恐懼貪婪指數（7 日均） | alternative.me | 百分位 |
| | 距最近一次減半天數 | 固定日期 | 減半法 |

說明：
- 實現市值由 `CapMrktCurUSD ÷ CapMVRVCur` 推導（Community API 未提供 CapRealUSD）。實現價格倍數在數學上等於 MVRV，依規格仍列為獨立指標，因此在鏈上估值類中的實際權重偏重 MVRV。
- 2028 減半日期為估計值（2028-04-15），實際日期確定後請更新 `btc_top/scoring.py` 的 `HALVINGS`。
- Google Trends 沒有穩定的免費官方 API，第一版跳過。

### 無法免費取得（標記 unavailable）

持有者行為類的 **長期持有者供給變化、LTH-SOPR、CDD / Dormancy** 需要付費數據。可選方案：
- **Glassnode**（Professional 方案提供 API，含 LTH Supply、LTH-SOPR、CDD、Dormancy）
- **CryptoQuant**（Advanced 以上方案提供 API，含 SOPR、CDD、交易所流量）

接入時把金鑰放在 GitHub → Settings → Secrets and variables → Actions，不可寫進程式或 commit。

## 正規化方法

經典指標每輪頂部讀數都在下降，所以不用固定紅線：

1. **週期頂部**：2013-12、2017-12、2021-11、2025-10 各月的最高收盤日（由價格數據決定）；**底部**為兩次頂部之間的最低收盤日。
2. **週期法**：對各次頂部當日的指標值做對數線性擬合（含負值時改用線性），外推本輪預期頂部值；底部同理推得下界。
   分數 = (當前值 − 下界) ÷ (預期頂部 − 下界) × 100，下限 0，可超過 100。
3. **百分位法**：歷史不足 3 個週期，或擬合出的預期頂部 ≤ 下界（區間無意義）時，改用該指標過去 4 年的滾動百分位。少於 90 天資料時不計分。
   - Puell Multiple 因 2024 減半後讀數大幅下降，外推頂部低於底部下界，因此改用百分位。
   - 交易所淨流入在頂部與底部（投降拋售）都可能偏高，與週期擬合不相容，因此用百分位。
4. **減半法**：以各次頂部距減半的天數線性外推本輪預期天數 E；分數 = 天數 ÷ E × 100，超過 E 後線性下降，於 1.5E 歸零。
5. 同類指標先平均成類別分數，再按權重加總（無資料的類別權重按比例分給其他類），總分限制在 0–100。

### 已知限制

- 歷史分數以目前的擬合參數計算（樣本內），不是當時即時可得的數值，回測時需注意。
- 對數線性外推會讓本輪預期頂部值偏低（例如 MVRV Z 約 1.7），所以鏈上估值類在中段行情就可能出現較高分數。
- 2019 年以前缺少衍生品與資金流數據，早期總分主要由鏈上與持有者類別決定，可信度較低（例如 2018-12 底部總分約 40）。
- 以百分位計分的衍生品指標歷史較短（未平倉量僅數個月），分數會隨資料累積而變穩定。

## 運作方式

- GitHub Actions 每天 UTC 00:15 執行 `run.py`，完成後自動 commit `data/` 與 `docs/`。
- 任一資料源失敗時沿用前一次的資料，並在 JSON 標記 `stale: true`，不讓整個流程失敗。
- GitHub Pages 從 main 分支的 `/docs` 發布。

本機執行：

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

## 公開倉庫規則

本倉庫只放公開市場數據與程式。**禁止寫入任何個人持倉、資產、成本、賣出計畫或規則參數。**
不使用任何交易所的交易 API 金鑰。v3 的賣出規則回測參數只放本機（`private/` 已列入 `.gitignore`）。

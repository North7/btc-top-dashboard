"""抓取公開免費資料源。每個函式回傳以日期（UTC）為索引的 DataFrame。

所有函式在失敗時丟出例外，由 run.py 統一處理（沿用舊資料並標記 stale）。
"""
from __future__ import annotations

import io
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (tidemark; public data only)"}
TIMEOUT = 30


def _get(url: str, params: dict | None = None, retries: int = 3):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET {url} 失敗：{last}")


def _ms_to_date(ms) -> pd.Timestamp:
    return pd.to_datetime(int(ms), unit="ms", utc=True).tz_localize(None).normalize()


# ---------- Coin Metrics Community（鏈上） ----------
CM_METRICS = ["PriceUSD", "CapMrktCurUSD", "CapMVRVCur", "IssTotUSD", "SplyCur", "HashRate"]


def coinmetrics() -> pd.DataFrame:
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    params = {"assets": "btc", "metrics": ",".join(CM_METRICS), "frequency": "1d",
              "start_time": "2010-07-01", "page_size": 10000, "paging_from": "start"}
    rows = []
    while True:
        d = _get(url, params)
        rows += d["data"]
        nxt = d.get("next_page_url")
        if not nxt:
            break
        url, params = nxt, None
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["time"].str[:10])
    df = df.set_index("date")[CM_METRICS].apply(pd.to_numeric, errors="coerce")
    return df.dropna(subset=["PriceUSD"])


# ---------- DefiLlama（穩定幣總供給） ----------
def stablecoins() -> pd.DataFrame:
    d = _get("https://stablecoins.llama.fi/stablecoincharts/all")
    df = pd.DataFrame({
        "date": [pd.to_datetime(int(x["date"]), unit="s").normalize() for x in d],
        "stable_supply_usd": [x.get("totalCirculatingUSD", {}).get("peggedUSD") for x in d],
    })
    return df.set_index("date").astype(float)


# ---------- alternative.me（恐懼貪婪指數） ----------
def fear_greed() -> pd.DataFrame:
    d = _get("https://api.alternative.me/fng/", {"limit": 0, "format": "json"})["data"]
    df = pd.DataFrame({
        "date": [pd.to_datetime(int(x["timestamp"]), unit="s").normalize() for x in d],
        "fear_greed": [float(x["value"]) for x in d],
    })
    return df.set_index("date").sort_index()


# ---------- 資金費率：Binance 為主（2019 起），OKX 備援 ----------
def funding_binance(since: pd.Timestamp | None) -> pd.DataFrame:
    start = int((since or pd.Timestamp("2019-09-01")).timestamp() * 1000)
    out = []
    while True:
        d = _get("https://fapi.binance.com/fapi/v1/fundingRate",
                 {"symbol": "BTCUSDT", "startTime": start, "limit": 1000})
        if not d:
            break
        out += d
        if len(d) < 1000:
            break
        start = d[-1]["fundingTime"] + 1
    df = pd.DataFrame({"date": [_ms_to_date(x["fundingTime"]) for x in out],
                       "funding": [float(x["fundingRate"]) for x in out]})
    return df.groupby("date").mean()


def funding_okx() -> pd.DataFrame:
    d = _get("https://www.okx.com/api/v5/public/funding-rate-history",
             {"instId": "BTC-USDT-SWAP", "limit": 100})["data"]
    df = pd.DataFrame({"date": [_ms_to_date(x["fundingTime"]) for x in d],
                       "funding": [float(x["realizedRate"] or x["fundingRate"]) for x in d]})
    return df.groupby("date").mean()


# ---------- 未平倉量（USD）：OKX 全市場 BTC 合約為主，Binance 備援 ----------
def open_interest_okx() -> pd.DataFrame:
    d = _get("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume",
             {"ccy": "BTC", "period": "1D"})["data"]
    df = pd.DataFrame({"date": [_ms_to_date(x[0]) for x in d],
                       "oi_usd": [float(x[1]) for x in d]})
    return df.set_index("date").sort_index()


def open_interest_binance() -> pd.DataFrame:
    d = _get("https://fapi.binance.com/futures/data/openInterestHist",
             {"symbol": "BTCUSDT", "period": "1d", "limit": 30})
    df = pd.DataFrame({"date": [_ms_to_date(x["timestamp"]) for x in d],
                       "oi_usd": [float(x["sumOpenInterestValue"]) for x in d]})
    return df.set_index("date").sort_index()


# ---------- 期現基差（年化）：Binance 當季合約為主，OKX 季度合約快照備援 ----------
def _quarter_expiry(d: pd.Timestamp) -> pd.Timestamp:
    """Binance 季度合約到期日：3/6/9/12 月最後一個週五。回傳 d 之後最近的一個。"""
    for i in range(5):
        y, m = d.year + (d.month - 1 + 3 * i) // 12, (d.month - 1 + 3 * i) % 12 + 1
        m = ((m - 1) // 3 + 1) * 3
        last = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
        exp = last - pd.Timedelta(days=(last.weekday() - 4) % 7)
        if exp > d:
            return exp
    raise ValueError(d)


def basis_binance(since: pd.Timestamp | None) -> pd.DataFrame:
    """當季合約收盤 vs 指數收盤的年化基差。用日 K 線，可回補到 2020 年。

    到期前 7 天內以 7 天計算年化，避免分母過小放大雜訊。
    """
    start = int((since or pd.Timestamp("2020-09-01")).timestamp() * 1000)

    def klines(url, params):
        out, s = [], start
        while True:
            d = _get(url, {**params, "interval": "1d", "startTime": s, "limit": 1500})
            out += d
            if len(d) < 1500:
                return {_ms_to_date(x[0]): float(x[4]) for x in out}
            s = d[-1][0] + 1

    fut = klines("https://fapi.binance.com/fapi/v1/continuousKlines",
                 {"pair": "BTCUSDT", "contractType": "CURRENT_QUARTER"})
    idx = klines("https://fapi.binance.com/fapi/v1/indexPriceKlines", {"pair": "BTCUSDT"})
    df = pd.concat({"f": pd.Series(fut), "i": pd.Series(idx)}, axis=1).dropna().sort_index()
    days = pd.Series([max((_quarter_expiry(d) - d).days, 7) for d in df.index], index=df.index)
    out = pd.DataFrame({"basis_ann": (df["f"] / df["i"] - 1) * 365 / days})
    out.index.name = "date"
    return out


def basis_okx() -> pd.DataFrame:
    inst = _get("https://www.okx.com/api/v5/public/instruments",
                {"instType": "FUTURES", "instFamily": "BTC-USD"})["data"]
    q = next(i for i in inst if i["alias"] == "quarter")
    fut = float(_get("https://www.okx.com/api/v5/market/ticker", {"instId": q["instId"]})["data"][0]["last"])
    idx = float(_get("https://www.okx.com/api/v5/market/index-tickers", {"instId": "BTC-USD"})["data"][0]["idxPx"])
    days = max((int(q["expTime"]) / 1000 - time.time()) / 86400, 1)
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    return pd.DataFrame({"basis_ann": [(fut / idx - 1) * 365 / days]}, index=pd.DatetimeIndex([today], name="date"))


# ---------- Coinbase 溢價：Coinbase BTC-USD 收盤 / OKX BTC-USDT 收盤 - 1 ----------
def coinbase_premium(days: int = 1500) -> pd.DataFrame:
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    cb = []
    t = start
    while t < end:
        t2 = min(t + timedelta(days=299), end)
        cb += _get("https://api.exchange.coinbase.com/products/BTC-USD/candles",
                   {"granularity": 86400, "start": t.isoformat(), "end": t2.isoformat()})
        t = t2
        time.sleep(0.3)
    cb_s = pd.Series({pd.to_datetime(int(x[0]), unit="s"): float(x[4]) for x in cb})

    ok = {}
    after = None
    while True:
        p = {"instId": "BTC-USDT", "bar": "1Dutc", "limit": 100}
        if after:
            p["after"] = after
        d = _get("https://www.okx.com/api/v5/market/history-candles", p)["data"]
        if not d:
            break
        for x in d:
            ok[_ms_to_date(x[0])] = float(x[4])
        after = d[-1][0]
        if _ms_to_date(after) < pd.Timestamp(start.date()):
            break
        time.sleep(0.15)
    ok_s = pd.Series(ok)
    df = pd.concat({"cb": cb_s, "okx": ok_s}, axis=1).dropna().sort_index()
    df.index.name = "date"
    return pd.DataFrame({"coinbase_premium": df["cb"] / df["okx"] - 1})


# ---------- 美國現貨 ETF 資金流：TFTC 為主（CC BY 4.0，不擋雲端 IP），Farside 備援 ----------
def etf_tftc() -> pd.DataFrame:
    """TFTC 整理的美國現貨 BTC ETF 每日淨流入（2024-01-11 起），換算成百萬美元。

    授權 CC BY 4.0，需標註來源：TFTC — tftc.io/bitcoin-etf-flows。
    """
    d = _get("https://www.tftc.io/bitcoin-etf-flows/data.json")
    rows = [(pd.Timestamp(r["date"]), r["netFlowUsd"] / 1e6) for r in d["days"] if r.get("netFlowUsd") is not None]
    df = pd.DataFrame(rows, columns=["date", "etf_flow_musd"]).set_index("date").sort_index()
    return df


# ---------- Farside ETF 資金流（備援） ----------
def etf_farside() -> pd.DataFrame:
    """美國現貨 ETF 每日淨流入合計（百萬美元）。

    Farside 有時會以 Cloudflare 驗證擋下請求（403）。依規格不繞過驗證：
    失敗時由 run.py 沿用已存的歷史並標記 stale。表格中負數以括號表示，例如 (148.7)。
    """
    r = requests.get("https://farside.co.uk/bitcoin-etf-flow-all-data/", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    t = max(pd.read_html(io.StringIO(r.text)), key=len)
    t["date"] = pd.to_datetime(t["Date"], format="%d %b %Y", errors="coerce")
    t = t.dropna(subset=["date"]).set_index("date")
    s = t["Total"].astype(str).str.replace(",", "").str.strip()
    s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True).replace({"-": "0"})
    return pd.DataFrame({"etf_flow_musd": pd.to_numeric(s, errors="coerce")}).dropna()


# ---------- BGeometrics（僅本機私人版使用） ----------
def bgeometrics(endpoint: str, field: str) -> pd.DataFrame:
    """BGeometrics 免費 API（近 4 年資料，每小時 10 次、每天 15 次，依 IP 計算）。

    條款禁止公開再散布，因此只在 `run.py --private` 使用，資料存放在不上傳的 private/。
    """
    d = _get(f"https://bitcoin-data.com/v1/{endpoint}", retries=1)
    if isinstance(d, dict):
        raise RuntimeError(d.get("error", {}).get("message", str(d))[:200])
    df = pd.DataFrame({"date": pd.to_datetime([x["d"] for x in d]),
                       field: pd.to_numeric([x.get(field) for x in d], errors="coerce")})
    return df.set_index("date").dropna().sort_index()

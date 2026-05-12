#!/usr/bin/env python3
"""
美股科技股候选数据获取
从预设候选池获取行情、技术指标、综合评分
主数据源：akshare（中国大陆服务器可用）
备用数据源：yfinance（需 HTTPS_PROXY 环境变量或海外 IP）
输出：.tmp/us_tech_candidates.json
"""

import json
import os
import time
import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import socket
import requests
import concurrent.futures
import pandas as pd

socket.setdefaulttimeout(15)

_TZ_BEIJING = ZoneInfo("Asia/Shanghai")

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

CANDIDATE_POOL = [
    # 半导体 / AI 硬件
    "NVDA", "AMD", "AVGO", "TSM", "QCOM", "AMAT", "MU",
    # AI 平台 / 大厂
    "MSFT", "GOOGL", "META", "AMZN", "ORCL", "CRM", "NOW", "PLTR",
    # 云计算 / SaaS
    "SNOW", "DDOG", "NET", "ZS", "CRWD",
    # 消费科技
    "AAPL", "NFLX",
]

SYMBOL_NAMES = {
    "NVDA": "英伟达", "AMD": "超微半导体", "AVGO": "博通",
    "TSM": "台积电", "QCOM": "高通", "AMAT": "应用材料", "MU": "美光科技",
    "MSFT": "微软", "GOOGL": "Alphabet", "META": "Meta", "AMZN": "亚马逊",
    "ORCL": "甲骨文", "CRM": "Salesforce", "NOW": "ServiceNow", "PLTR": "Palantir",
    "SNOW": "Snowflake", "DDOG": "Datadog", "NET": "Cloudflare",
    "ZS": "Zscaler", "CRWD": "CrowdStrike", "AAPL": "苹果", "NFLX": "奈飞",
}


def _make_yf_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
        log.info(f"yfinance 使用代理: {proxy}")
    adapter = requests.adapters.HTTPAdapter(
        max_retries=requests.adapters.Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
        )
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _calc_rsi(closes: pd.Series, period: int = 14):
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    rsi = (100 - 100 / (1 + rs)).iloc[-1]
    return round(float(rsi), 2) if not pd.isna(rsi) else None


def _calc_ma_signal(closes: pd.Series):
    ma20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else None
    ma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None
    if ma20 is None or ma50 is None or pd.isna(ma20) or pd.isna(ma50):
        return None, None, "数据不足"
    prev_ma20 = float(closes.rolling(20).mean().iloc[-2]) if len(closes) >= 21 else ma20
    prev_ma50 = float(closes.rolling(50).mean().iloc[-2]) if len(closes) >= 51 else ma50
    if ma20 > ma50 and prev_ma20 <= prev_ma50:
        signal = "金叉"
    elif ma20 < ma50 and prev_ma20 >= prev_ma50:
        signal = "死叉"
    elif ma20 > ma50:
        signal = "多头排列"
    else:
        signal = "空头排列"
    return ma20, ma50, signal


def _score(stock: dict) -> float:
    """综合评分 0-100：技术面40% + 基本面40% + 动量20%"""
    score = 50.0

    tech = stock.get("technicals", {})
    fund = stock.get("fundamentals", {})
    price = stock.get("price", {})

    rsi = tech.get("rsi_14")
    if rsi is not None:
        if rsi < 35:
            score += 12
        elif rsi < 50:
            score += 6
        elif rsi > 70:
            score -= 8
        elif rsi > 60:
            score -= 2

    ma_signal = tech.get("ma_signal")
    if ma_signal == "金叉":
        score += 12
    elif ma_signal == "多头排列":
        score += 8
    elif ma_signal == "空头排列":
        score -= 8
    elif ma_signal == "死叉":
        score -= 12

    vol_ratio = tech.get("volume_ratio_vs_20d_avg")
    if vol_ratio and vol_ratio > 1.5:
        score += 6
    elif vol_ratio and vol_ratio < 0.6:
        score -= 4

    rev_growth = fund.get("revenue_growth")
    if rev_growth is not None:
        if rev_growth > 0.3:
            score += 14
        elif rev_growth > 0.15:
            score += 8
        elif rev_growth > 0:
            score += 3
        else:
            score -= 6

    fwd_pe = fund.get("forward_pe")
    if fwd_pe is not None and fwd_pe > 0:
        if fwd_pe < 20:
            score += 10
        elif fwd_pe < 35:
            score += 5
        elif fwd_pe > 60:
            score -= 6

    profit_margin = fund.get("profit_margins")
    if profit_margin is not None:
        if profit_margin > 0.25:
            score += 8
        elif profit_margin > 0.1:
            score += 3
        elif profit_margin < 0:
            score -= 8

    month_ret = price.get("month_return_pct")
    if month_ret is not None:
        if month_ret > 15:
            score += 10
        elif month_ret > 5:
            score += 5
        elif month_ret < -15:
            score -= 10
        elif month_ret < -5:
            score -= 4

    week52_pos = price.get("week_52_position_pct")
    if week52_pos is not None:
        if week52_pos < 0.5:
            score += 4
        elif week52_pos > 0.9:
            score -= 3

    return round(min(max(score, 0), 100), 1)


def _patch_akshare_readonly():
    """修复 akshare 1.18.x 中部分美股符号触发的 'assignment destination is read-only' bug。
    使用 importlib.util.find_spec 获取文件路径（不 import 子模块，避免并发死锁）。
    """
    try:
        import importlib.util
        spec = importlib.util.find_spec("akshare.stock.stock_us_sina")
        if spec is None or not spec.origin:
            return
        filepath = spec.origin
        with open(filepath, "r") as f:
            content = f.read()
        old = "new_range.index.values[0] = pd.to_datetime(str(data_df.index.date[0]))"
        new = (
            "idx_vals = new_range.index.values.copy()\n"
            "            idx_vals[0] = pd.to_datetime(str(data_df.index.date[0]))\n"
            "            new_range.index = idx_vals"
        )
        if old in content:
            with open(filepath, "w") as f:
                f.write(content.replace(old, new))
            log.info("akshare stock_us_sina.py read-only bug 已修复")
    except Exception:
        pass


_patch_akshare_readonly()


def _fetch_via_akshare(symbol: str) -> dict | None:
    """通过 akshare 获取美股数据，适用于中国大陆服务器。"""
    import akshare as ak

    df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
    if df is None or df.empty:
        log.warning(f"{symbol}: akshare 无数据，跳过")
        return None

    # 252 个交易日用于 52 周高低点（.copy() 避免 NumPy read-only 错误）
    df_52 = df.tail(252).copy()
    high52 = float(df_52["high"].max())
    low52 = float(df_52["low"].min())

    # 取最近 100 个交易日用于技术指标计算（保证 MA50 有效）
    df_calc = df.tail(100).copy().reset_index(drop=True)
    closes = df_calc["close"]
    volumes = df_calc["volume"]

    current_price = float(closes.iloc[-1])

    # 近 1 月收益（约 22 个交易日）
    open_price = float(closes.iloc[-22]) if len(closes) > 22 else float(closes.iloc[0])
    month_return = (current_price - open_price) / open_price * 100

    # 52 周位置
    range52 = high52 - low52
    week52_pos = (current_price - low52) / range52 if range52 > 0 else 0.5

    # 均线信号
    ma20, ma50, ma_signal = _calc_ma_signal(closes)

    # 量比
    avg_vol = float(volumes.rolling(20).mean().iloc[-1]) if len(volumes) >= 20 else None
    latest_vol = float(volumes.iloc[-1])
    vol_ratio = latest_vol / avg_vol if avg_vol and avg_vol > 0 else None

    result = {
        "symbol": symbol,
        "name": SYMBOL_NAMES.get(symbol, symbol),
        "sector": "Technology",
        "fetched_at": datetime.now(_TZ_BEIJING).isoformat(),
        "source": "akshare",
        "price": {
            "current": round(current_price, 2),
            "month_return_pct": round(month_return, 2),
            "week_52_high": round(high52, 2),
            "week_52_low": round(low52, 2),
            "week_52_position_pct": round(week52_pos, 3),
        },
        "fundamentals": {
            "market_cap": None,
            "pe_ratio": None,
            "forward_pe": None,
            "revenue_growth": None,
            "profit_margins": None,
            "beta": None,
        },
        "technicals": {
            "ma20": round(ma20, 2) if ma20 else None,
            "ma50": round(ma50, 2) if ma50 else None,
            "ma_signal": ma_signal,
            "rsi_14": _calc_rsi(closes),
            "volume_ratio_vs_20d_avg": round(vol_ratio, 2) if vol_ratio else None,
        },
    }
    result["score"] = _score(result)
    return result


def _fetch_via_yfinance(symbol: str, period: str = "3mo") -> dict | None:
    """通过 yfinance 获取美股数据（需要海外 IP 或代理）。"""
    import yfinance as yf

    # yfinance 1.3+ 内部自行管理 Session，不能传入自定义 requests.Session
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period)
    if hist.empty:
        log.warning(f"{symbol}: yfinance 无历史数据，跳过")
        return None

    info = ticker.info
    closes = hist["Close"]
    current_price = float(closes.iloc[-1])

    open_price = float(closes.iloc[-22]) if len(closes) > 22 else float(closes.iloc[0])
    month_return = (current_price - open_price) / open_price * 100

    high52 = info.get("fiftyTwoWeekHigh") or current_price
    low52 = info.get("fiftyTwoWeekLow") or current_price
    range52 = high52 - low52
    week52_pos = (current_price - low52) / range52 if range52 > 0 else 0.5

    ma20, ma50, ma_signal = _calc_ma_signal(closes)

    avg_vol = float(hist["Volume"].rolling(20).mean().iloc[-1]) if len(hist) >= 20 else None
    latest_vol = int(hist["Volume"].iloc[-1])
    vol_ratio = latest_vol / avg_vol if avg_vol and avg_vol > 0 else None

    result = {
        "symbol": symbol,
        "name": info.get("longName", SYMBOL_NAMES.get(symbol, symbol)),
        "sector": info.get("sector", "Technology"),
        "fetched_at": datetime.now(_TZ_BEIJING).isoformat(),
        "source": "yfinance",
        "price": {
            "current": round(current_price, 2),
            "month_return_pct": round(month_return, 2),
            "week_52_high": info.get("fiftyTwoWeekHigh"),
            "week_52_low": info.get("fiftyTwoWeekLow"),
            "week_52_position_pct": round(week52_pos, 3),
        },
        "fundamentals": {
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margins": info.get("profitMargins"),
            "beta": info.get("beta"),
        },
        "technicals": {
            "ma20": round(ma20, 2) if ma20 else None,
            "ma50": round(ma50, 2) if ma50 else None,
            "ma_signal": ma_signal,
            "rsi_14": _calc_rsi(closes),
            "volume_ratio_vs_20d_avg": round(vol_ratio, 2) if vol_ratio else None,
        },
    }
    result["score"] = _score(result)
    return result


def fetch_single(symbol: str, period: str = "3mo") -> dict | None:
    """获取单只美股数据，akshare 优先，yfinance 备用。"""
    try:
        data = _fetch_via_akshare(symbol)
        if data:
            log.info(f"{symbol}: akshare 获取成功，评分 {data['score']}")
            return data
    except Exception as e:
        log.warning(f"{symbol}: akshare 失败 ({e})，尝试 yfinance...")

    try:
        data = _fetch_via_yfinance(symbol, period)
        if data:
            log.info(f"{symbol}: yfinance 获取成功，评分 {data['score']}")
            return data
    except Exception as e:
        log.error(f"{symbol}: 获取失败 - {e}")

    return None


def fetch_all(period: str = "3mo", top: int = 20) -> list[dict]:
    results = []
    TIMEOUT = 30  # akshare 单次请求可能略慢，适当增加超时

    def fetch_with_timeout(symbol):
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = ex.submit(fetch_single, symbol, period)
        try:
            return future.result(timeout=TIMEOUT)
        except concurrent.futures.TimeoutError:
            log.warning(f"{symbol}: 超时跳过")
            return None
        finally:
            ex.shutdown(wait=False)

    # akshare 并发数可适当提高，使用国内数据源限流宽松
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_with_timeout, sym): sym for sym in CANDIDATE_POOL}
        for future in concurrent.futures.as_completed(futures, timeout=180):
            sym = futures[future]
            try:
                data = future.result()
                if data:
                    results.append(data)
            except Exception as e:
                log.error(f"{sym}: 异常 - {e}")

    if len(results) < 5:
        cache_path = TMP_DIR / "us_tech_candidates.json"
        if cache_path.exists():
            import json as _json
            cached = _json.loads(cache_path.read_text())
            cached_stocks = cached.get("stocks", [])
            if len(cached_stocks) >= len(results):
                log.warning(f"实时数据仅 {len(results)} 只，使用缓存数据（{len(cached_stocks)} 只）")
                return cached_stocks[:top]

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="3mo")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    log.info(f"开始获取美股科技股候选数据，候选池 {len(CANDIDATE_POOL)} 只...")
    candidates = fetch_all(args.period, args.top)

    out = {
        "fetched_at": datetime.now(_TZ_BEIJING).isoformat(),
        "total": len(candidates),
        "stocks": candidates,
    }
    out_path = TMP_DIR / "us_tech_candidates.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    log.info(f"完成，筛选出 {len(candidates)} 只，已保存至 {out_path}")
    return out


if __name__ == "__main__":
    main()

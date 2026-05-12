#!/usr/bin/env python3
"""
获取股票基础数据：价格历史 + 关键财务指标
输出到 .tmp/stock_data_{symbol}.json
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

import yfinance as yf

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)


def fetch(symbol: str, period: str = "3mo") -> dict:
    ticker = yf.Ticker(symbol)

    hist = ticker.history(period=period)
    if hist.empty:
        raise ValueError(f"No data found for symbol: {symbol}")

    info = ticker.info

    current_price = hist["Close"].iloc[-1]
    open_price = hist["Close"].iloc[-22] if len(hist) > 22 else hist["Close"].iloc[0]
    month_return = (current_price - open_price) / open_price * 100

    closes = hist["Close"]
    ma20 = closes.rolling(20).mean().iloc[-1] if len(closes) >= 20 else None
    ma50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else None

    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    rsi = (100 - 100 / (1 + rs)).iloc[-1] if len(closes) >= 14 else None

    avg_vol_20 = hist["Volume"].rolling(20).mean().iloc[-1] if len(hist) >= 20 else None
    latest_vol = hist["Volume"].iloc[-1]
    vol_ratio = latest_vol / avg_vol_20 if avg_vol_20 else None

    result = {
        "symbol": symbol,
        "fetched_at": datetime.now().isoformat(),
        "period": period,
        "price": {
            "current": round(float(current_price), 4),
            "month_return_pct": round(float(month_return), 2),
            "week_52_high": info.get("fiftyTwoWeekHigh"),
            "week_52_low": info.get("fiftyTwoWeekLow"),
        },
        "fundamentals": {
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margins": info.get("profitMargins"),
            "beta": info.get("beta"),
            "dividend_yield": info.get("dividendYield"),
        },
        "technicals": {
            "ma20": round(float(ma20), 4) if ma20 is not None else None,
            "ma50": round(float(ma50), 4) if ma50 is not None else None,
            "rsi_14": round(float(rsi), 2) if rsi is not None else None,
            "volume_latest": int(latest_vol),
            "volume_ratio_vs_20d_avg": round(float(vol_ratio), 2) if vol_ratio else None,
        },
        "company": {
            "name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": (info.get("longBusinessSummary") or "")[:300],
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", help="股票代码，如 AAPL 或 000001.SZ")
    parser.add_argument("--period", default="3mo", help="历史数据周期，默认 3mo")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    data = fetch(symbol, args.period)

    out_path = TMP_DIR / f"stock_data_{symbol}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"[OK] {symbol} 数据已保存至 {out_path}")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


if __name__ == "__main__":
    main()

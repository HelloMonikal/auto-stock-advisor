#!/usr/bin/env python3
"""
获取股票近期新闻（通过 yfinance）
输出到 .tmp/stock_news_{symbol}.json
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

import yfinance as yf

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)


def fetch(symbol: str, limit: int = 10) -> dict:
    ticker = yf.Ticker(symbol)
    raw_news = ticker.news or []

    news_items = []
    for item in raw_news[:limit]:
        content = item.get("content", {})
        news_items.append({
            "title": content.get("title", item.get("title", "")),
            "summary": (content.get("summary") or "")[:200],
            "publisher": content.get("provider", {}).get("displayName", item.get("publisher", "")),
            "published_at": content.get("pubDate", item.get("providerPublishTime", "")),
            "url": content.get("canonicalUrl", {}).get("url", item.get("link", "")),
        })

    result = {
        "symbol": symbol,
        "fetched_at": datetime.now().isoformat(),
        "news_count": len(news_items),
        "news": news_items,
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", help="股票代码，如 AAPL")
    parser.add_argument("--limit", type=int, default=10, help="获取新闻数量，默认 10 条")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    data = fetch(symbol, args.limit)

    out_path = TMP_DIR / f"stock_news_{symbol}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"[OK] {symbol} 新闻已保存至 {out_path}，共 {data['news_count']} 条")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
调用 Claude API 对股票数据 + 新闻进行综合分析
输入：.tmp/stock_data_{symbol}.json + .tmp/stock_news_{symbol}.json
输出：.tmp/stock_report_{symbol}.json
"""

import json
import argparse
from pathlib import Path
from datetime import datetime

import anthropic
from dotenv import load_dotenv

load_dotenv()

TMP_DIR = Path(__file__).parent.parent / ".tmp"
CLIENT = anthropic.Anthropic()
MODEL = "claude-sonnet-4-6"


def analyze(symbol: str) -> dict:
    symbol = symbol.upper()

    data_path = TMP_DIR / f"stock_data_{symbol}.json"
    news_path = TMP_DIR / f"stock_news_{symbol}.json"

    if not data_path.exists():
        raise FileNotFoundError(f"缺少股票数据文件: {data_path}，请先运行 fetch_stock_data.py")

    stock_data = json.loads(data_path.read_text())
    news_data = json.loads(news_path.read_text()) if news_path.exists() else {"news": []}

    prompt = f"""你是一位专业的量化分析师。请根据以下数据，对股票 {symbol} 进行客观分析。

## 股票基础数据
{json.dumps(stock_data, ensure_ascii=False, indent=2)}

## 近期新闻
{json.dumps(news_data.get('news', []), ensure_ascii=False, indent=2)}

## 分析要求
请严格按照以下 JSON 格式输出，不要输出任何其他内容：

{{
  "rating": "买入" 或 "持有" 或 "卖出",
  "confidence": 0.0 到 1.0 之间的数字（如 0.75 表示 75% 置信度）,
  "target_price_range": {{"low": 数字, "high": 数字}} 或 null（如无法判断），
  "summary": "50字以内的一句话总结",
  "bull_case": ["利多因素1", "利多因素2", "利多因素3"],
  "bear_case": ["利空因素1", "利空因素2"],
  "key_risks": ["风险1", "风险2"],
  "technical_signal": "超买" 或 "超卖" 或 "中性" 或 "看涨" 或 "看跌",
  "news_sentiment": "正面" 或 "负面" 或 "中性",
  "disclaimer": "本分析仅供参考，不构成投资建议"
}}"""

    message = CLIENT.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    analysis = json.loads(raw)

    report = {
        "symbol": symbol,
        "analyzed_at": datetime.now().isoformat(),
        "price_at_analysis": stock_data["price"]["current"],
        "analysis": analysis,
        "data_snapshot": {
            "pe_ratio": stock_data["fundamentals"]["pe_ratio"],
            "market_cap": stock_data["fundamentals"]["market_cap"],
            "rsi_14": stock_data["technicals"]["rsi_14"],
            "month_return_pct": stock_data["price"]["month_return_pct"],
        },
    }

    out_path = TMP_DIR / f"stock_report_{symbol}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[OK] {symbol} 分析报告已保存至 {out_path}")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", help="股票代码，如 AAPL")
    args = parser.parse_args()

    report = analyze(args.symbol)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

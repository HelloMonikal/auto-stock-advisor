#!/usr/bin/env python3
"""
调用 DeepSeek API 对候选股票/基金进行分析，输出 TOP 5 推荐
输入：.tmp/us_tech_candidates.json 或 .tmp/a_share_fund_candidates.json
输出：.tmp/us_recommendations.json 或 .tmp/fund_recommendations.json
"""

import json
import logging
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI
from dotenv import load_dotenv

_TZ_BEIJING = ZoneInfo("Asia/Shanghai")
_TZ_US_EASTERN = ZoneInfo("America/New_York")


def _us_market_status(now_et: datetime) -> str:
    if now_et.weekday() >= 5:
        return "休市（周末）"
    t = now_et.hour * 60 + now_et.minute
    if t < 240:
        return "休市（夜间）"
    if t < 570:
        return "盘前交易（04:00-09:30 ET）"
    if t < 960:
        return "交易中（09:30-16:00 ET）"
    if t < 1200:
        return "盘后交易（16:00-20:00 ET）"
    return "休市（夜间）"


def _get_time_context() -> str:
    """返回当前北京时间 + 美东时间 + 美股市场状态，注入 prompt 供 AI 感知市场时态。"""
    now_bj = datetime.now(_TZ_BEIJING)
    now_et = datetime.now(_TZ_US_EASTERN)
    return (
        f"⏱ 当前时间 — 北京时间：{now_bj.strftime('%Y-%m-%d %H:%M %Z')} | "
        f"美国东部时间：{now_et.strftime('%Y-%m-%d %H:%M %Z')} | "
        f"美股市场状态：{_us_market_status(now_et)}"
    )

load_dotenv()

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")

# 注入历史表现摘要，使 AI 能校正置信度和收益预期
sys.path.insert(0, str(Path(__file__).parent))
try:
    from performance_tracker import build_performance_summary as _build_perf
    _PERFORMANCE_SUMMARY = _build_perf()
except Exception as _e:
    logging.getLogger(__name__).debug(f"历史表现数据加载跳过: {_e}")
    _PERFORMANCE_SUMMARY = ""
log = logging.getLogger(__name__)

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

SESSION_CONTEXT = {
    "morning": {
        "label": "早间（10:00）",
        "us_focus": "分析美股昨日收盘情况，结合隔夜盘后交易信号，判断今日美股盘前方向，重点关注哪些科技股有明确的短期买入机会。",
        "fund_focus": "A股今日开盘30分钟，结合昨日收盘和今日开盘走势，推荐最值得今日建仓的科技基金，给出预期持仓周期。",
    },
    "afternoon": {
        "label": "下午（16:00）",
        "us_focus": "美股今晚即将开盘，结合技术指标和基本面，判断哪些科技股今晚有望表现强劲，预测今晚收盘价区间。",
        "fund_focus": "A股今日已收盘，对今日表现进行复盘，推荐明日继续值得持有或加仓的科技基金，结合收盘涨跌给出操作建议。",
    },
    "evening": {
        "label": "晚间（21:00）",
        "us_focus": "美股已开盘约3小时，结合当日实时走势和盘中技术信号，判断今日尾盘方向和明日开盘走势，推荐短线机会最大的5只科技股。",
        "fund_focus": "结合今日美股盘中表现（对A股明日有联动效应），推荐明日最值得布局的科技类A股基金，给出目标涨幅预期。",
    },
}

US_PROMPT_TEMPLATE = """你是一位专业的美股科技股量化分析师，擅长技术面和基本面结合的投资分析。

## 当前时间
{time_context}

## 当前时段背景
{session_focus}

## 候选科技股数据（已按综合评分排序，取前 {n} 只）
{candidates_json}

## 分析要求
从以上候选股票中，严格筛选出最值得买入的 TOP 5，要求：
1. 预期收益率有一定确定性（不是纯投机）
2. 持仓周期明确（1-4周短线 或 1-3月中线）
3. 风险可控
4. 理由充分、逻辑清晰

请严格按如下 JSON 格式输出，不要输出任何其他内容（不要加 markdown 代码块）：
{{
  "market": "US",
  "session": "{session}",
  "generated_at": "{now}",
  "market_context": "当前美股市场整体判断（40字内）",
  "recommendations": [
    {{
      "rank": 1,
      "symbol": "代码",
      "name": "公司名",
      "current_price": 数字,
      "rating": "强烈买入 | 买入 | 谨慎买入",
      "confidence": 0.0到1.0,
      "expected_return_pct": {{"low": 数字, "high": 数字}},
      "holding_period": "如：2-4周 或 1-2个月",
      "core_logic": "核心买入逻辑（60字内）",
      "bull_points": ["利多点1（20字内）", "利多点2（20字内）"],
      "key_risk": "最主要风险（20字内）",
      "technical_signal": "超买 | 超卖 | 看涨 | 看跌 | 中性",
      "score": 评分数字
    }}
  ]
}}"""

FUND_PROMPT_TEMPLATE = """你是一位专业的 A 股基金分析师，熟悉科技类开放式基金的筛选和配置。

## 当前时间
{time_context}

## 当前时段背景
{session_focus}

## 候选基金数据（已按综合评分排序，取前 {n} 只，优先科技类）
{candidates_json}

## 分析要求
从候选基金中筛选最值得买入的 TOP 5，要求：
1. 近期走势有明确向上趋势
2. 基金主题与当前市场热点匹配
3. 持仓周期明确
4. 给出预期收益区间

请严格按如下 JSON 格式输出，不要输出任何其他内容（不要加 markdown 代码块）：
{{
  "market": "A_FUND",
  "session": "{session}",
  "generated_at": "{now}",
  "market_context": "当前A股市场整体判断（40字内）",
  "recommendations": [
    {{
      "rank": 1,
      "code": "基金代码",
      "name": "基金名称",
      "latest_nav": 净值数字或null,
      "rating": "强烈推荐 | 推荐 | 谨慎推荐",
      "confidence": 0.0到1.0,
      "expected_return_pct": {{"low": 数字, "high": 数字}},
      "holding_period": "如：1-2周 或 1个月",
      "core_logic": "推荐逻辑（60字内）",
      "bull_points": ["利多点1（20字内）", "利多点2（20字内）"],
      "key_risk": "最主要风险（20字内）",
      "recent_trend": "上升 | 下降 | 震荡",
      "score": 评分数字
    }}
  ]
}}"""


def _call_deepseek(prompt: str, max_retries: int = 3) -> str:
    import os
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.warning(f"DeepSeek 调用失败（第{attempt+1}次）: {e}")
            if attempt < max_retries - 1:
                time.sleep(30)
    raise RuntimeError("DeepSeek API 多次重试失败")


def _parse_json_response(raw: str, timestamp: str) -> dict:
    text = raw.strip()
    # 去掉可能的 markdown 代码块
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raw_path = TMP_DIR / f"deepseek_raw_{timestamp}.txt"
        raw_path.write_text(raw)
        log.error(f"JSON 解析失败，原始响应已保存至 {raw_path}")
        raise e


def analyze_us(session: str, top_n: int = 20) -> dict:
    data_path = TMP_DIR / "us_tech_candidates.json"
    if not data_path.exists():
        raise FileNotFoundError("缺少美股候选数据，请先运行 fetch_us_tech_stocks.py")

    data = json.loads(data_path.read_text())
    stocks = data["stocks"][:top_n]

    # 精简数据减少 token 消耗
    slim = [{
        "symbol": s["symbol"],
        "name": s["name"],
        "price": s["price"]["current"],
        "month_return_pct": s["price"]["month_return_pct"],
        "week_52_position_pct": s["price"].get("week_52_position_pct"),
        "forward_pe": s["fundamentals"].get("forward_pe"),
        "revenue_growth": s["fundamentals"].get("revenue_growth"),
        "profit_margins": s["fundamentals"].get("profit_margins"),
        "rsi_14": s["technicals"].get("rsi_14"),
        "ma_signal": s["technicals"].get("ma_signal"),
        "volume_ratio": s["technicals"].get("volume_ratio_vs_20d_avg"),
        "score": s["score"],
    } for s in stocks]

    ctx = SESSION_CONTEXT[session]
    now = datetime.now(_TZ_BEIJING).isoformat()
    prompt = US_PROMPT_TEMPLATE.format(
        time_context=_get_time_context(),
        session_focus=ctx["us_focus"],
        candidates_json=json.dumps(slim, ensure_ascii=False, indent=2),
        n=len(slim),
        session=session,
        now=now,
    )
    if _PERFORMANCE_SUMMARY:
        prompt = _PERFORMANCE_SUMMARY + "\n\n" + prompt
        log.info("已注入历史推荐表现数据（用于AI校正）")

    log.info(f"调用 DeepSeek 分析美股推荐（时段: {ctx['label']}）...")
    raw = _call_deepseek(prompt)
    result = _parse_json_response(raw, now.replace(":", "-"))

    out_path = TMP_DIR / "us_recommendations.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    log.info(f"美股推荐分析完成，已保存至 {out_path}")
    return result


def analyze_funds(session: str, top_n: int = 30) -> dict:
    data_path = TMP_DIR / "a_share_fund_candidates.json"
    if not data_path.exists():
        raise FileNotFoundError("缺少 A 股基金候选数据，请先运行 fetch_a_share_funds.py")

    data = json.loads(data_path.read_text())
    funds = data["funds"][:top_n]

    slim = [{
        "code": f["code"],
        "name": f["name"],
        "fund_type": f["fund_type"],
        "is_tech": f["is_tech"],
        "nav": f.get("单位净值"),
        "r1w": f.get("近1周"),
        "r1m": f.get("近1月"),
        "r3m": f.get("近3月"),
        "r6m": f.get("近6月"),
        "r1y": f.get("近1年"),
        "score": f["score"],
    } for f in funds]

    ctx = SESSION_CONTEXT[session]
    now = datetime.now(_TZ_BEIJING).isoformat()
    prompt = FUND_PROMPT_TEMPLATE.format(
        time_context=_get_time_context(),
        session_focus=ctx["fund_focus"],
        candidates_json=json.dumps(slim, ensure_ascii=False, indent=2),
        n=len(slim),
        session=session,
        now=now,
    )
    if _PERFORMANCE_SUMMARY:
        prompt = _PERFORMANCE_SUMMARY + "\n\n" + prompt

    log.info(f"调用 DeepSeek 分析 A 股基金推荐（时段: {ctx['label']}）...")
    raw = _call_deepseek(prompt)
    result = _parse_json_response(raw, now.replace(":", "-"))

    out_path = TMP_DIR / "fund_recommendations.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    log.info(f"A 股基金推荐分析完成，已保存至 {out_path}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["us", "fund", "all"], default="all")
    parser.add_argument("--session", choices=["morning", "afternoon", "evening"], required=True)
    args = parser.parse_args()

    if args.type in ("us", "all"):
        analyze_us(args.session)
    if args.type in ("fund", "all"):
        analyze_funds(args.session)


if __name__ == "__main__":
    main()

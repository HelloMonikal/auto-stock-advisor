#!/usr/bin/env python3
"""
持仓决策分析工具：基于当前持仓和预算约束，调用 DeepSeek 给出今日操作建议
输出：减仓 / 持有 / 加仓 / 清仓，以及整体资金分配建议
"""
import json
import os
import time
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_TZ_BEIJING = ZoneInfo("Asia/Shanghai")
_TZ_US_EASTERN = ZoneInfo("America/New_York")

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

# ─── 交易日判断 ──────────────────────────────────────────────────────────────

_US_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 7, 3),
    date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
}

_A_HOLIDAYS_2026 = {
    date(2026, 1, 1),
    date(2026, 1, 28), date(2026, 1, 29), date(2026, 1, 30),
    date(2026, 2, 2), date(2026, 2, 3), date(2026, 2, 4),
    date(2026, 4, 5), date(2026, 4, 6),
    date(2026, 5, 1), date(2026, 5, 4), date(2026, 5, 5),
    date(2026, 6, 19),
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5),
    date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8),
}


def _is_us_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _US_HOLIDAYS_2026


def _is_a_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _A_HOLIDAYS_2026


def _next_trading_day(d: date, market: str) -> date:
    checker = _is_us_trading_day if market == "US" else _is_a_trading_day
    nxt = d + timedelta(days=1)
    while not checker(nxt):
        nxt += timedelta(days=1)
    return nxt


def get_trading_day_info() -> dict:
    today_et = datetime.now(_TZ_US_EASTERN).date()
    today_bj = datetime.now(_TZ_BEIJING).date()
    us_ok = _is_us_trading_day(today_et)
    a_ok = _is_a_trading_day(today_bj)
    return {
        "us_today": today_et.isoformat(),
        "us_is_trading_day": us_ok,
        "us_next_trading_day": today_et.isoformat() if us_ok else _next_trading_day(today_et, "US").isoformat(),
        "a_today": today_bj.isoformat(),
        "a_is_trading_day": a_ok,
        "a_next_trading_day": today_bj.isoformat() if a_ok else _next_trading_day(today_bj, "A").isoformat(),
    }


# ─── DeepSeek Prompt ────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """你是一位专业的个人投资组合管理顾问，擅长美股和A股基金的综合配置与风险管理。

## 当前时间与交易日
{time_context}

## 预算与持仓概览
{budget_context}

## 持仓明细（含盈亏）
{positions_json}

## 分析要求
请对每个持仓给出明确的今日（或下一交易日）操作建议，并给出整体预算分配建议。

操作类型（action）：
- hold：维持现有仓位，不操作
- increase：建议加仓，给出具体股数/份数和金额
- reduce：建议减仓，给出具体股数/份数、金额和减仓比例
- close：建议全部清仓，说明理由

注意：
- 美股：股数为小数，金额用美元
- A股基金：份数可为整数，金额用人民币
- 若今日非交易日，给出下一交易日的操作计划
- 止损止盈价格仅对"持有/加仓"时提供

请严格按如下 JSON 格式输出，不要输出任何其他内容（不要加 markdown 代码块）：
{{
  "trade_date": "今日或下一交易日 YYYY-MM-DD",
  "market_context": "整体市场研判（50字内）",
  "portfolio_health": "持仓整体健康度评估（60字内）",
  "cash_advice": "对剩余可用资金的建议（50字内）",
  "decisions": [
    {{
      "symbol": "代码",
      "name": "名称",
      "market": "US或A_FUND",
      "action": "hold | increase | reduce | close",
      "action_shares": 建议操作股数（正数=买入 负数=卖出，清仓填负的全部持股数），
      "action_amount": 对应金额（正数=买入金额 负数=卖出金额，单位与持仓货币一致）,
      "reduce_pct": 减仓百分比（0-100，仅reduce/close时填写，其余填0）,
      "reason": "操作理由（60字内）",
      "confidence": 0.0到1.0,
      "target_price": 目标价或null,
      "stop_loss": 止损价或null
    }}
  ],
  "rebalance_tips": [
    "调仓建议1（40字内）",
    "调仓建议2（40字内）"
  ]
}}"""


def _build_time_context(trade_info: dict) -> str:
    now_bj = datetime.now(_TZ_BEIJING)
    now_et = datetime.now(_TZ_US_EASTERN)
    lines = [
        f"北京时间：{now_bj.strftime('%Y-%m-%d %H:%M')} | 美东时间：{now_et.strftime('%Y-%m-%d %H:%M')}",
    ]
    if trade_info["us_is_trading_day"]:
        lines.append(f"美股：今日（{trade_info['us_today']}）为交易日")
    else:
        lines.append(f"美股：今日休市，下一交易日 {trade_info['us_next_trading_day']}")
    if trade_info["a_is_trading_day"]:
        lines.append(f"A股：今日（{trade_info['a_today']}）为交易日")
    else:
        lines.append(f"A股：今日休市，下一交易日 {trade_info['a_next_trading_day']}")
    return "\n".join(lines)


def _build_budget_context(us_budget: float, a_budget: float, positions: list) -> str:
    us_value = sum(
        p.get("current_value") or p.get("cost", 0)
        for p in positions if p["market"] == "US"
    )
    a_value = sum(
        p.get("current_value") or p.get("cost", 0)
        for p in positions if p["market"] == "A_FUND"
    )
    us_avail = max(0, us_budget - us_value)
    a_avail = max(0, a_budget - a_value)
    lines = []
    if us_budget > 0:
        used_pct = us_value / us_budget * 100 if us_budget else 0
        lines.append(
            f"美股总预算：${us_budget:,.0f} | 已投入：${us_value:,.2f}（{used_pct:.1f}%） | 可用：${us_avail:,.2f}"
        )
    if a_budget > 0:
        used_pct = a_value / a_budget * 100 if a_budget else 0
        lines.append(
            f"A股总预算：¥{a_budget:,.0f} | 已投入：¥{a_value:,.2f}（{used_pct:.1f}%） | 可用：¥{a_avail:,.2f}"
        )
    return "\n".join(lines) if lines else "（未设置预算）"


def analyze_portfolio_decisions(
    positions_with_price: list,
    us_budget: float = 0.0,
    a_budget: float = 0.0,
) -> dict:
    """
    调用 DeepSeek 分析当前持仓并给出操作建议。

    :param positions_with_price: 已计算 current_price / pnl_pct 的持仓列表（open 状态）
    :param us_budget: 美股总预算（USD）
    :param a_budget: A股总预算（CNY）
    :return: 决策分析结果字典
    """
    if not positions_with_price:
        return {"error": "无持仓数据"}

    trade_info = get_trading_day_info()
    time_ctx = _build_time_context(trade_info)
    budget_ctx = _build_budget_context(us_budget, a_budget, positions_with_price)

    slim = []
    for p in positions_with_price:
        cur = p.get("current_price")
        cur_val = p.get("current_value")
        pnl_pct = p.get("pnl_pct")
        currency = "$" if p["market"] == "US" else "¥"
        slim.append({
            "symbol": p["symbol"],
            "name": p.get("name", p["symbol"]),
            "market": p["market"],
            "shares": float(p["shares"]),
            "buy_price": f"{currency}{float(p['buy_price']):.4f}",
            "current_price": f"{currency}{cur:.4f}" if cur else "N/A",
            "cost": f"{currency}{p.get('cost', 0):,.2f}",
            "current_value": f"{currency}{cur_val:,.2f}" if cur_val else "N/A",
            "pnl_pct": f"{pnl_pct:+.2f}%" if pnl_pct is not None else "N/A",
            "buy_date": (p.get("buy_date") or "")[:10],
        })

    prompt = _PROMPT_TEMPLATE.format(
        time_context=time_ctx,
        budget_context=budget_ctx,
        positions_json=json.dumps(slim, ensure_ascii=False, indent=2),
    )

    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )

    raw = ""
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2500,
                temperature=0.3,
            )
            raw = resp.choices[0].message.content.strip()
            break
        except Exception as e:
            log.warning(f"DeepSeek 调用失败（第{attempt+1}次）: {e}")
            if attempt < 2:
                time.sleep(30)
            else:
                raise RuntimeError("DeepSeek API 多次重试失败")

    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    result = json.loads(text)
    now = datetime.now(_TZ_BEIJING)

    # 补充统计数据
    us_value = sum(
        p.get("current_value") or p.get("cost", 0)
        for p in positions_with_price if p["market"] == "US"
    )
    a_value = sum(
        p.get("current_value") or p.get("cost", 0)
        for p in positions_with_price if p["market"] == "A_FUND"
    )
    result.update({
        "generated_at": now.isoformat(),
        "us_budget": us_budget,
        "a_budget": a_budget,
        "us_invested": round(us_value, 2),
        "a_invested": round(a_value, 2),
        "us_available": round(max(0, us_budget - us_value), 2),
        "a_available": round(max(0, a_budget - a_value), 2),
        "trade_info": trade_info,
    })

    out_path = TMP_DIR / "portfolio_decisions.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    log.info(f"持仓决策分析完成，已保存至 {out_path}")
    return result


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from portfolio_tracker import load_portfolio, calculate_pnl

    positions = [p for p in load_portfolio() if p["status"] == "open"]
    enriched = [calculate_pnl(p) for p in positions]

    us_b = float(sys.argv[1]) if len(sys.argv) > 1 else 8000.0
    a_b = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    result = analyze_portfolio_decisions(enriched, us_budget=us_b, a_budget=a_b)
    print(json.dumps(result, ensure_ascii=False, indent=2))

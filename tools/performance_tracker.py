#!/usr/bin/env python3
"""
历史推荐准确性评估：计算AI推荐的实战表现，用于下次推荐时的校正反馈
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

TMP_DIR = Path(__file__).parent.parent / ".tmp"
HISTORY_FILE = TMP_DIR / "recommendation_history.jsonl"


def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    records = []
    for line in HISTORY_FILE.read_text().strip().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def evaluate_us_recs(min_age_days: int = 3) -> dict:
    """
    对历史美股推荐进行实际表现评估。
    只评估 min_age_days 天前的推荐（确保有足够时间验证）。
    """
    records = load_history()
    cutoff = datetime.now() - timedelta(days=min_age_days)
    us_recs = [r for r in records if r.get("market") == "US"]

    evaluated = []
    for r in us_recs:
        try:
            archived_at = datetime.fromisoformat(r["archived_at"])
            if archived_at > cutoff:
                continue
            symbol = r.get("symbol")
            buy_price = r.get("price_at_recommendation")
            if not symbol or not buy_price:
                continue

            import yfinance as yf
            hist = yf.Ticker(symbol).history(period="5d")
            if hist.empty:
                continue

            current_price = float(hist["Close"].iloc[-1])
            actual_pct = (current_price - buy_price) / buy_price * 100
            exp = r.get("expected_return") or {}
            exp_low = float(exp.get("low") or 0)
            exp_high = float(exp.get("high") or 0)
            exp_mid = (exp_low + exp_high) / 2

            evaluated.append({
                "symbol": symbol,
                "name": r.get("name", symbol),
                "archived_at": r["archived_at"],
                "buy_price": buy_price,
                "current_price": round(current_price, 2),
                "actual_pct": round(actual_pct, 2),
                "expected_pct": round(exp_mid, 2),
                "expected_low": exp_low,
                "hit": actual_pct >= exp_low,
                "rating": r.get("rating", ""),
                "session": r.get("session", ""),
            })
        except Exception as e:
            log.debug(f"评估跳过: {e}")

    if not evaluated:
        return {"count": 0, "avg_actual": 0.0, "avg_expected": 0.0,
                "hit_rate": 0.0, "details": []}

    avg_actual = sum(e["actual_pct"] for e in evaluated) / len(evaluated)
    avg_expected = sum(e["expected_pct"] for e in evaluated) / len(evaluated)
    hit_rate = sum(1 for e in evaluated if e["hit"]) / len(evaluated) * 100

    return {
        "count": len(evaluated),
        "avg_actual": round(avg_actual, 2),
        "avg_expected": round(avg_expected, 2),
        "hit_rate": round(hit_rate, 1),
        "details": sorted(evaluated, key=lambda x: x["archived_at"], reverse=True),
    }


def build_performance_summary() -> str:
    """
    生成历史推荐表现摘要，注入到 AI 提示词中用于校正置信度和收益区间。
    返回空字符串表示暂无足够历史数据。
    """
    try:
        perf = evaluate_us_recs()
    except Exception as e:
        log.warning(f"历史表现计算失败（不影响主流程）: {e}")
        return ""

    if perf["count"] == 0:
        return ""

    def sign(v: float) -> str:
        return f"+{v}" if v >= 0 else str(v)

    detail_lines = []
    for d in perf["details"][:5]:
        hit_str = "达标✓" if d["hit"] else "未达✗"
        detail_lines.append(
            f"  - {d['symbol']}（{d['rating']}）: "
            f"买入${d['buy_price']} → 现${d['current_price']} "
            f"实际{sign(d['actual_pct'])}% / 预期{sign(d['expected_pct'])}% {hit_str}"
        )

    # 根据达成率动态生成校正指令
    if perf["hit_rate"] < 40:
        calibration = (
            "历史达成率偏低（<40%），本次请大幅提高谨慎度："
            "confidence 整体降低 0.15~0.2，expected_return_pct 区间收窄 30%，"
            "评级门槛上移（非强烈信号不得给出「强烈买入」）。"
        )
    elif perf["hit_rate"] < 60:
        calibration = (
            "历史达成率中等（40%~60%），请适度保守："
            "confidence 降低 0.05~0.1，expected_return_pct 区间小幅收窄 15%。"
        )
    else:
        calibration = "历史达成率良好（≥60%），保持正常判断标准，可适当提高高置信标的的评级。"

    lines = [
        f"## 历史推荐实战表现（最近 {perf['count']} 条已验证推荐）",
        f"- 平均实际收益率：{sign(perf['avg_actual'])}%",
        f"- 平均预期收益率：{sign(perf['avg_expected'])}%",
        f"- 预期达成率：{perf['hit_rate']}%",
        "",
        "近期验证案例：",
        *detail_lines,
        "",
        f"⚡ 校正要求：{calibration}",
    ]
    return "\n".join(lines)

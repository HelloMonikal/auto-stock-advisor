#!/usr/bin/env python3
"""
Telegram Bot 消息发送工具
将推荐结果格式化为结构化消息并推送
"""

import os
import json
import logging
import time
import argparse
from pathlib import Path
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TMP_DIR = Path(__file__).parent.parent / ".tmp"

SESSION_LABELS = {
    "morning": "早间推荐 🌅",
    "afternoon": "午后推荐 ☀️",
    "evening": "晚间推荐 🌙",
}

RATING_EMOJI = {
    "强烈买入": "🔥", "强烈推荐": "🔥",
    "买入": "✅", "推荐": "✅",
    "谨慎买入": "⚠️", "谨慎推荐": "⚠️",
}

SIGNAL_EMOJI = {
    "看涨": "📈", "上升": "📈",
    "看跌": "📉", "下降": "📉",
    "超买": "🔴", "超卖": "🟢", "震荡": "➡️", "中性": "➡️",
}

RANK_EMOJI = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]


def _fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    return f"{v:+.1f}%"


def _fmt_return_range(rng: dict) -> str:
    if not rng:
        return "N/A"
    low, high = rng.get("low", 0), rng.get("high", 0)
    return f"+{low}% ~ +{high}%"


def format_us_section(data: dict) -> str:
    recs = data.get("recommendations", [])
    ctx = data.get("market_context", "")
    lines = ["🇺🇸 *美股科技 TOP 5*", f"_{ctx}_", ""]

    for r in recs[:5]:
        rank_idx = r.get("rank", 1) - 1
        rank_icon = RANK_EMOJI[rank_idx] if rank_idx < len(RANK_EMOJI) else f"{r['rank']}."
        rating = r.get("rating", "")
        r_emoji = RATING_EMOJI.get(rating, "")
        signal = r.get("technical_signal", "")
        s_emoji = SIGNAL_EMOJI.get(signal, "")
        conf = int(r.get("confidence", 0) * 100)

        lines.append(f"{rank_icon} *{r.get('symbol')}* | {r.get('name', '')}")
        lines.append(f"   现价: ${r.get('current_price', 'N/A')}  {r_emoji} {rating}（{conf}%置信）")
        lines.append(f"   预期收益: {_fmt_return_range(r.get('expected_return_pct'))}  持仓: {r.get('holding_period', 'N/A')}")
        lines.append(f"   技术: {s_emoji}{signal}  评分: {r.get('score', 'N/A')}/100")
        lines.append(f"   💡 {r.get('core_logic', '')}")
        bull = r.get("bull_points", [])
        if bull:
            lines.append(f"   ✦ {bull[0]}")
            if len(bull) > 1:
                lines.append(f"   ✦ {bull[1]}")
        lines.append(f"   ⚠️ 风险: {r.get('key_risk', 'N/A')}")
        lines.append("")

    return "\n".join(lines)


def format_fund_section(data: dict) -> str:
    recs = data.get("recommendations", [])
    ctx = data.get("market_context", "")
    lines = ["🇨🇳 *A股基金 TOP 5*", f"_{ctx}_", ""]

    for r in recs[:5]:
        rank_idx = r.get("rank", 1) - 1
        rank_icon = RANK_EMOJI[rank_idx] if rank_idx < len(RANK_EMOJI) else f"{r['rank']}."
        rating = r.get("rating", "")
        r_emoji = RATING_EMOJI.get(rating, "")
        trend = r.get("recent_trend", "")
        t_emoji = SIGNAL_EMOJI.get(trend, "")
        conf = int(r.get("confidence", 0) * 100)
        nav = r.get("latest_nav")
        nav_str = f"¥{nav:.4f}" if nav else "N/A"

        lines.append(f"{rank_icon} *{r.get('name', '')}*")
        lines.append(f"   代码: {r.get('code', '')}  净值: {nav_str}")
        lines.append(f"   {r_emoji} {rating}（{conf}%置信）  持仓: {r.get('holding_period', 'N/A')}")
        lines.append(f"   预期收益: {_fmt_return_range(r.get('expected_return_pct'))}  趋势: {t_emoji}{trend}")
        lines.append(f"   💡 {r.get('core_logic', '')}")
        bull = r.get("bull_points", [])
        if bull:
            lines.append(f"   ✦ {bull[0]}")
            if len(bull) > 1:
                lines.append(f"   ✦ {bull[1]}")
        lines.append(f"   ⚠️ 风险: {r.get('key_risk', 'N/A')}")
        lines.append("")

    return "\n".join(lines)


def build_message(us_data: dict, fund_data: dict, session: str) -> str:
    label = SESSION_LABELS.get(session, session)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    header = f"📊 *智能股票助手 | {label}*\n`{now_str}`\n\n"
    divider = "─" * 20 + "\n\n"
    footer = "\n⚠️ _以上内容仅供参考，不构成投资建议_"

    us_section = format_us_section(us_data)
    fund_section = format_fund_section(fund_data)

    return header + us_section + divider + fund_section + footer


def send_message(text: str, parse_mode: str = "Markdown", retries: int = 2) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        log.error("缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 环境变量")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            result = resp.json()
            if result.get("ok"):
                log.info("Telegram 消息发送成功")
                return True
            else:
                log.error(f"Telegram API 返回错误: {result}")
        except Exception as e:
            log.warning(f"发送失败（第{attempt+1}次）: {e}")
            if attempt < retries:
                time.sleep(10)

    # 记录失败日志
    fail_log = TMP_DIR / "failed_sends.log"
    with fail_log.open("a") as f:
        f.write(f"{datetime.now().isoformat()} | 发送失败\n{text[:200]}\n---\n")
    return False


def send_error_notification(error_msg: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    text = f"⚠️ 智能股票助手运行异常\n`{datetime.now().strftime('%Y-%m-%d %H:%M')}`\n\n{error_msg}"
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", choices=["morning", "afternoon", "evening"], required=True)
    parser.add_argument("--test", action="store_true", help="只打印消息，不发送")
    args = parser.parse_args()

    us_path = TMP_DIR / "us_recommendations.json"
    fund_path = TMP_DIR / "fund_recommendations.json"

    if not us_path.exists() or not fund_path.exists():
        log.error("推荐数据文件缺失，请先运行 analyze_with_deepseek.py")
        return

    us_data = json.loads(us_path.read_text())
    fund_data = json.loads(fund_path.read_text())

    msg = build_message(us_data, fund_data, args.session)

    if args.test:
        print(msg)
        return

    send_message(msg)


if __name__ == "__main__":
    main()

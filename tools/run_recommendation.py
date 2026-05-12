#!/usr/bin/env python3
"""
主编排脚本：数据获取 → DeepSeek 分析 → Telegram 推送
遵循 daily_recommendation.md 工作流

用法：
  python tools/run_recommendation.py --session morning|afternoon|evening
  python tools/run_recommendation.py --session morning --test   # 仅打印，不发送
"""

import json
import logging
import argparse
import sys
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ_BEIJING = ZoneInfo("Asia/Shanghai")
import concurrent.futures

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).parent
TMP_DIR = TOOLS_DIR.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

# 预先 import，避免在并发线程中同时 import akshare 子模块导致 ModuleLock 死锁
sys.path.insert(0, str(TOOLS_DIR))
import fetch_us_tech_stocks as _fus  # noqa: F401
import fetch_a_share_funds as _faf   # noqa: F401

# 缓存有效期（秒）：同一时段内复用上次数据，避免重复 API 调用
CACHE_TTL_SECONDS = 60 * 30  # 30 分钟


def _cache_valid(path: Path) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < CACHE_TTL_SECONDS


def step_fetch_data(force_refresh: bool = False) -> bool:
    """Step 1 & 2：并行获取美股和 A 股基金数据"""
    import importlib.util

    us_cache = TMP_DIR / "us_tech_candidates.json"
    fund_cache = TMP_DIR / "a_share_fund_candidates.json"

    need_us = force_refresh or not _cache_valid(us_cache)
    need_fund = force_refresh or not _cache_valid(fund_cache)

    if not need_us and not need_fund:
        log.info("数据缓存有效，跳过获取步骤")
        return True

    errors = []

    def fetch_us():
        sys.path.insert(0, str(TOOLS_DIR))
        from fetch_us_tech_stocks import fetch_all
        import json as _json
        result = fetch_all()
        out = {"fetched_at": datetime.now(_TZ_BEIJING).isoformat(), "total": len(result), "stocks": result}
        us_cache.write_text(_json.dumps(out, ensure_ascii=False, indent=2))
        log.info(f"美股数据获取完成，共 {len(result)} 只")

    def fetch_fund():
        sys.path.insert(0, str(TOOLS_DIR))
        from fetch_a_share_funds import fetch_all as fund_fetch_all
        import json as _json
        result = fund_fetch_all()
        out = {"fetched_at": datetime.now(_TZ_BEIJING).isoformat(), "total": len(result), "funds": result}
        fund_cache.write_text(_json.dumps(out, ensure_ascii=False, indent=2))
        log.info(f"A 股基金数据获取完成，共 {len(result)} 只")

    tasks = []
    if need_us:
        tasks.append(("美股数据", fetch_us))
    if need_fund:
        tasks.append(("A股基金数据", fetch_fund))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(fn): name for name, fn in tasks}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                log.error(f"{name} 获取失败: {e}")
                errors.append(name)

    if errors:
        log.warning(f"以下数据获取失败: {errors}，将尝试使用缓存")
        # 只要两个数据文件存在（可能是旧缓存），就继续
        if not us_cache.exists() or not fund_cache.exists():
            return False

    return True


def step_analyze(session: str) -> bool:
    """Step 3：DeepSeek 分析（美股 + 基金并行）"""
    sys.path.insert(0, str(TOOLS_DIR))
    from analyze_with_deepseek import analyze_us, analyze_funds

    errors = []

    def run_us():
        analyze_us(session)
        log.info("美股推荐分析完成")

    def run_fund():
        analyze_funds(session)
        log.info("A股基金推荐分析完成")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(run_us): "美股分析",
            executor.submit(run_fund): "A股基金分析",
        }
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                log.error(f"{name} 失败: {e}")
                errors.append(name)

    if errors:
        log.error(f"分析步骤失败: {errors}")
        return False
    return True


def step_send(session: str, test_mode: bool = False) -> bool:
    """Step 4：发送 Telegram 消息"""
    sys.path.insert(0, str(TOOLS_DIR))
    from send_telegram import build_message, send_message, send_error_notification
    import json as _json

    us_path = TMP_DIR / "us_recommendations.json"
    fund_path = TMP_DIR / "fund_recommendations.json"

    if not us_path.exists() or not fund_path.exists():
        log.error("推荐数据文件不存在，无法发送")
        return False

    us_data = _json.loads(us_path.read_text())
    fund_data = _json.loads(fund_path.read_text())
    msg = build_message(us_data, fund_data, session)

    if test_mode:
        print("\n" + "=" * 50)
        print(msg)
        print("=" * 50 + "\n")
        log.info("测试模式：消息已打印，未发送")
        return True

    return send_message(msg)


def step_archive(session: str) -> None:
    """Step 5：归档推荐历史"""
    history_path = TMP_DIR / "recommendation_history.jsonl"
    us_path = TMP_DIR / "us_recommendations.json"
    fund_path = TMP_DIR / "fund_recommendations.json"

    records = []
    if us_path.exists():
        try:
            data = json.loads(us_path.read_text())
            for r in data.get("recommendations", []):
                records.append({
                    "archived_at": datetime.now(_TZ_BEIJING).isoformat(),
                    "session": session,
                    "market": "US",
                    "rank": r.get("rank"),
                    "symbol": r.get("symbol"),
                    "name": r.get("name"),
                    "price_at_recommendation": r.get("current_price"),
                    "expected_return": r.get("expected_return_pct"),
                    "holding_period": r.get("holding_period"),
                    "rating": r.get("rating"),
                    "confidence": r.get("confidence"),
                })
        except Exception as e:
            log.warning(f"美股归档失败: {e}")

    if fund_path.exists():
        try:
            data = json.loads(fund_path.read_text())
            for r in data.get("recommendations", []):
                records.append({
                    "archived_at": datetime.now(_TZ_BEIJING).isoformat(),
                    "session": session,
                    "market": "A_FUND",
                    "rank": r.get("rank"),
                    "code": r.get("code"),
                    "name": r.get("name"),
                    "nav_at_recommendation": r.get("latest_nav"),
                    "expected_return": r.get("expected_return_pct"),
                    "holding_period": r.get("holding_period"),
                    "rating": r.get("rating"),
                    "confidence": r.get("confidence"),
                })
        except Exception as e:
            log.warning(f"基金归档失败: {e}")

    if records:
        with history_path.open("a") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.info(f"推荐历史归档完成，新增 {len(records)} 条")


def run(session: str, test_mode: bool = False, force_refresh: bool = False) -> bool:
    log.info(f"开始执行推荐流程 | 时段: {session} | 测试模式: {test_mode}")
    start = time.time()

    # Step 1 & 2
    log.info("[Step 1/4] 获取数据...")
    if not step_fetch_data(force_refresh):
        msg = "数据获取失败且无缓存可用，流程中止"
        log.error(msg)
        from send_telegram import send_error_notification
        send_error_notification(msg)
        return False

    # Step 3
    log.info("[Step 2/4] DeepSeek 分析...")
    if not step_analyze(session):
        msg = "DeepSeek 分析失败，流程中止"
        log.error(msg)
        from send_telegram import send_error_notification
        send_error_notification(msg)
        return False

    # Step 4
    log.info("[Step 3/4] 发送 Telegram...")
    step_send(session, test_mode)

    # Step 5
    log.info("[Step 4/4] 归档历史...")
    step_archive(session)

    elapsed = round(time.time() - start, 1)
    log.info(f"全流程完成，耗时 {elapsed}s")
    return True


# 需要在模块级别 import json（step_archive 用到）
import json


def main():
    parser = argparse.ArgumentParser(description="智能股票推荐 - 手动触发")
    parser.add_argument("--session", choices=["morning", "afternoon", "evening"], required=True,
                        help="推送时段")
    parser.add_argument("--test", action="store_true", help="测试模式：打印消息但不发送")
    parser.add_argument("--force-refresh", action="store_true", help="强制刷新数据（忽略缓存）")
    args = parser.parse_args()

    success = run(args.session, test_mode=args.test, force_refresh=args.force_refresh)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

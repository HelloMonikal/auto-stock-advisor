#!/usr/bin/env python3
"""
定时调度器：每天 10:00、16:00、21:00 自动触发推荐流程
运行方式：python tools/scheduler.py
后台运行：nohup python tools/scheduler.py > logs/scheduler.log 2>&1 &
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

_TZ_BEIJING = ZoneInfo("Asia/Shanghai")
_TZ_US_EASTERN = ZoneInfo("America/New_York")

load_dotenv()

# 确保 tools 目录在 path 中
sys.path.insert(0, str(Path(__file__).parent))

# 创建 logs 目录
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

SCHEDULE = [
    {"session": "morning",   "hour": 10, "minute": 0},
    {"session": "afternoon", "hour": 16, "minute": 0},
    {"session": "evening",   "hour": 21, "minute": 0},
]


def job(session: str) -> None:
    now_bj = datetime.now(_TZ_BEIJING)
    now_et = datetime.now(_TZ_US_EASTERN)
    log.info(
        f"定时任务触发: {session} | "
        f"北京时间 {now_bj.strftime('%Y-%m-%d %H:%M %Z')} | "
        f"美东时间 {now_et.strftime('%Y-%m-%d %H:%M %Z')}"
    )
    try:
        from run_recommendation import run
        # test_mode=True：完整执行数据获取和 AI 分析，但不推送 Telegram
        # 若需要在本机器上恢复自动推送，将此改为 run(session)
        run(session, test_mode=True)
    except Exception as e:
        log.error(f"任务执行异常: {e}", exc_info=True)


def main():
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    for item in SCHEDULE:
        scheduler.add_job(
            func=job,
            trigger=CronTrigger(
                hour=item["hour"],
                minute=item["minute"],
                timezone="Asia/Shanghai",
            ),
            args=[item["session"]],
            id=f"recommendation_{item['session']}",
            name=f"推荐推送 - {item['session']}",
            misfire_grace_time=300,  # 允许最多延迟 5 分钟触发
        )
        log.info(f"已注册任务: {item['session']} 每天 {item['hour']:02d}:{item['minute']:02d}")

    log.info("调度器启动，等待任务触发...")
    log.info("时区: Asia/Shanghai（北京时间）")
    log.info("推送时间: 10:00 / 16:00 / 21:00")
    log.info("按 Ctrl+C 停止\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("调度器已停止")


if __name__ == "__main__":
    main()

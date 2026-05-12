#!/usr/bin/env python3
"""
A 股基金候选数据获取（基于 AKShare）
筛选科技/成长类开放式基金，计算综合评分
输出：.tmp/a_share_fund_candidates.json
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime

import pandas as pd

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

TECH_KEYWORDS = [
    "科技", "AI", "芯片", "半导体", "信息", "数字", "智能", "创新",
    "新能源", "成长", "先进制造", "硬科技", "高端制造", "电子",
]

FUND_TYPES = ["股票型", "混合型"]


def _to_float(val):
    try:
        if val is None or str(val).strip() in ("", "--", "---", "暂无"):
            return None
        return float(str(val).replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def _score_fund(fund: dict) -> float:
    score = 50.0

    r1m = _to_float(fund.get("近1月"))
    r3m = _to_float(fund.get("近3月"))
    r6m = _to_float(fund.get("近6月"))
    r1y = _to_float(fund.get("近1年"))

    # 近3月（40分权重）
    if r3m is not None:
        if r3m > 20:
            score += 20
        elif r3m > 10:
            score += 12
        elif r3m > 5:
            score += 6
        elif r3m > 0:
            score += 2
        else:
            score -= 8

    # 近1月（30分权重）
    if r1m is not None:
        if r1m > 10:
            score += 15
        elif r1m > 5:
            score += 8
        elif r1m > 0:
            score += 3
        elif r1m < -5:
            score -= 6

    # 近6月（30分权重）
    if r6m is not None:
        if r6m > 30:
            score += 12
        elif r6m > 15:
            score += 7
        elif r6m > 0:
            score += 2
        else:
            score -= 5

    # 近1年加权参考
    if r1y is not None:
        if r1y > 50:
            score += 5
        elif r1y > 20:
            score += 2
        elif r1y < -20:
            score -= 4

    return round(min(max(score, 0), 100), 1)


def _is_tech_fund(name: str) -> bool:
    return any(kw in name for kw in TECH_KEYWORDS)


def fetch_fund_rank(fund_type: str = "股票型") -> pd.DataFrame:
    import akshare as ak
    for attempt in range(3):
        try:
            df = ak.fund_open_fund_rank_em(symbol=fund_type)
            log.info(f"{fund_type}基金排行获取成功，共 {len(df)} 条")
            return df
        except Exception as e:
            log.warning(f"获取{fund_type}排行失败（第{attempt+1}次）: {e}")
            if attempt < 2:
                time.sleep(30)
    return pd.DataFrame()


def fetch_all(top: int = 30) -> list[dict]:
    all_funds = []

    for fund_type in FUND_TYPES:
        df = fetch_fund_rank(fund_type)
        if df.empty:
            continue

        # 保存原始数据供调试
        raw_path = TMP_DIR / f"raw_fund_{fund_type}.json"
        raw_path.write_text(df.to_json(orient="records", force_ascii=False))

        for _, row in df.iterrows():
            name = str(row.get("基金简称", ""))
            code = str(row.get("基金代码", ""))
            if not code or not name:
                continue

            fund = {
                "code": code,
                "name": name,
                "fund_type": fund_type,
                "is_tech": _is_tech_fund(name),
                "净值日期": str(row.get("净值日期", "")),
                "单位净值": _to_float(row.get("单位净值")),
                "近1周": _to_float(row.get("近1周")),
                "近1月": _to_float(row.get("近1月")),
                "近3月": _to_float(row.get("近3月")),
                "近6月": _to_float(row.get("近6月")),
                "近1年": _to_float(row.get("近1年")),
                "fetched_at": datetime.now().isoformat(),
            }
            fund["score"] = _score_fund(fund)
            all_funds.append(fund)

    if not all_funds:
        log.error("未获取到任何基金数据")
        return []

    # 优先科技基金，再按评分排序
    tech_funds = [f for f in all_funds if f["is_tech"]]
    other_funds = [f for f in all_funds if not f["is_tech"]]

    tech_funds.sort(key=lambda x: x["score"], reverse=True)
    other_funds.sort(key=lambda x: x["score"], reverse=True)

    # 科技基金优先，不足时补充其他优质基金
    result = tech_funds[:top]
    if len(result) < top:
        result += other_funds[: top - len(result)]

    log.info(f"共筛选 {len(result)} 只基金（科技类 {len(tech_funds)} 只）")
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()

    log.info("开始获取 A 股基金候选数据...")
    candidates = fetch_all(args.top)

    out = {
        "fetched_at": datetime.now().isoformat(),
        "total": len(candidates),
        "funds": candidates,
    }
    out_path = TMP_DIR / "a_share_fund_candidates.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    log.info(f"完成，已保存至 {out_path}")
    return out


if __name__ == "__main__":
    main()

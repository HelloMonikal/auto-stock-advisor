#!/usr/bin/env python3
"""
持仓跟踪工具：记录买入操作，实时计算盈亏
"""
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)
PORTFOLIO_FILE = TMP_DIR / "portfolio.json"


def load_portfolio() -> list:
    if not PORTFOLIO_FILE.exists():
        return []
    try:
        return json.loads(PORTFOLIO_FILE.read_text()).get("positions", [])
    except Exception:
        return []


def save_portfolio(positions: list) -> None:
    data = {"updated_at": datetime.now().isoformat(), "positions": positions}
    PORTFOLIO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def add_position(market: str, symbol: str, name: str, shares: float,
                 buy_price: float, session: str = "") -> dict:
    positions = load_portfolio()
    pos = {
        "id": str(uuid.uuid4())[:8],
        "market": market,
        "symbol": symbol,
        "name": name,
        "shares": float(shares),
        "buy_price": float(buy_price),
        "buy_date": datetime.now().isoformat(),
        "session": session,
        "status": "open",
        "sell_price": None,
        "sell_date": None,
    }
    positions.append(pos)
    save_portfolio(positions)
    return pos


def close_position(position_id: str, sell_price: float) -> bool:
    positions = load_portfolio()
    for p in positions:
        if p["id"] == position_id and p["status"] == "open":
            p["status"] = "closed"
            p["sell_price"] = float(sell_price)
            p["sell_date"] = datetime.now().isoformat()
            save_portfolio(positions)
            return True
    return False


def delete_position(position_id: str) -> bool:
    positions = load_portfolio()
    filtered = [p for p in positions if p["id"] != position_id]
    if len(filtered) == len(positions):
        return False
    save_portfolio(filtered)
    return True


def get_us_price(symbol: str) -> Optional[float]:
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="2d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 4)
    except Exception as e:
        log.warning(f"价格获取失败 {symbol}: {e}")
    return None


def get_fund_nav(code: str) -> Optional[float]:
    try:
        import akshare as ak
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        if df is not None and not df.empty:
            return round(float(df["单位净值"].iloc[-1]), 4)
    except Exception as e:
        log.warning(f"净值获取失败 {code}: {e}")
    return None


def calculate_pnl(position: dict, current_price: Optional[float] = None) -> dict:
    buy_price = float(position["buy_price"])
    shares = float(position["shares"])
    cost = round(buy_price * shares, 4)
    currency = "$" if position["market"] == "US" else "¥"

    if position["status"] == "closed":
        current_price = float(position["sell_price"])
    elif current_price is None:
        if position["market"] == "US":
            current_price = get_us_price(position["symbol"])
        else:
            current_price = get_fund_nav(position["symbol"])

    if current_price is None:
        return {
            **position,
            "cost": cost,
            "current_price": None,
            "current_value": None,
            "pnl": None,
            "pnl_pct": None,
            "currency": currency,
        }

    current_value = round(current_price * shares, 4)
    pnl = round(current_value - cost, 4)
    pnl_pct = round((current_price - buy_price) / buy_price * 100, 2)

    return {
        **position,
        "cost": cost,
        "current_price": current_price,
        "current_value": current_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "currency": currency,
    }

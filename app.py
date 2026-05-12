#!/usr/bin/env python3
"""
智能股票助手 - Streamlit Web 仪表盘
运行方式：streamlit run app.py
"""
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from typing import Optional

_TZ_BEIJING = ZoneInfo("Asia/Shanghai")
_TZ_US_EASTERN = ZoneInfo("America/New_York")

# 确保 tools/ 可导入
sys.path.insert(0, str(Path(__file__).parent / "tools"))

TMP_DIR = Path(__file__).parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

# ─── 页面配置 ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="智能股票助手",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
div[data-testid="metric-container"] > label { font-size: 0.8rem; }
.stButton > button { width: 100%; }
</style>
""", unsafe_allow_html=True)

# ─── 访问密码保护 ─────────────────────────────────────────────────────────────

def _check_password() -> bool:
    """若设置了 APP_PASSWORD 环境变量则强制要求密码登录。"""
    app_pwd = os.environ.get("APP_PASSWORD", "")
    if not app_pwd:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.title("📈 智能股票助手")
    st.divider()
    _, col, _ = st.columns([1, 1, 1])
    with col:
        pwd = st.text_input("访问密码", type="password", placeholder="请输入密码")
        if st.button("登录", use_container_width=True, type="primary"):
            if pwd == app_pwd:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("密码错误")
    st.stop()
    return False

_check_password()

# ─── 工具函数 ────────────────────────────────────────────────────────────────

RANK_EMOJI = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
RATING_BADGE = {
    "强烈买入": "🔥", "强烈推荐": "🔥",
    "买入": "✅", "推荐": "✅",
    "谨慎买入": "⚠️", "谨慎推荐": "⚠️",
}
SIGNAL_EMOJI = {
    "看涨": "📈", "上升": "📈",
    "看跌": "📉", "下降": "📉",
    "超买": "🔴", "超卖": "🟢",
    "震荡": "➡️", "中性": "➡️",
}


def load_json(path: Path) -> Optional[dict]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    return None


def sign_str(v: float, decimals: int = 2) -> str:
    fmt = f"{{:+.{decimals}f}}"
    return fmt.format(v)


def pnl_color(v: Optional[float]) -> str:
    if v is None:
        return "—"
    color = "#00c853" if v >= 0 else "#ff1744"
    return f'<span style="color:{color};font-weight:bold">{sign_str(v)}%</span>'


def fmt_ret_range(rng: dict) -> str:
    if not rng:
        return "N/A"
    return f"+{rng.get('low', 0)}% ~ +{rng.get('high', 0)}%"


# ─── 市场状态（根据当前系统时间实时判定）────────────────────────────────────

def _a_share_status(now_bj: datetime) -> str:
    """根据北京时间判断 A 股市场状态。"""
    if now_bj.weekday() >= 5:
        return "🔴 休市（周末）"
    h, m = now_bj.hour, now_bj.minute
    t = h * 60 + m
    if 570 <= t < 690:   # 09:30–11:30
        return "🟢 交易中（上午）"
    if 780 <= t < 900:   # 13:00–15:00
        return "🟢 交易中（下午）"
    if 540 <= t < 570:   # 09:00–09:30
        return "🟡 集合竞价"
    if 690 <= t < 780:   # 11:30–13:00
        return "⚫ 午间休市"
    return "⚫ 休市"


def _us_market_status(now_et: datetime) -> str:
    """根据美东时间判断美股市场状态。"""
    if now_et.weekday() >= 5:
        return "🔴 休市（周末）"
    t = now_et.hour * 60 + now_et.minute
    if t < 240:
        return "⚫ 休市（夜间）"
    if t < 570:
        return "🟡 盘前（04:00–09:30 ET）"
    if t < 960:
        return "🟢 交易中（09:30–16:00 ET）"
    if t < 1200:
        return "🟡 盘后（16:00–20:00 ET）"
    return "⚫ 休市（夜间）"


def _auto_session() -> str:
    """根据当前北京时间自动判定推荐时段。"""
    now_bj = datetime.now(_TZ_BEIJING)
    h = now_bj.hour
    if 6 <= h < 13:
        return "morning"
    if 13 <= h < 18:
        return "afternoon"
    return "evening"


# ─── 缓存价格 ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_us_spot_df():
    """获取东方财富美股实时行情（全量，缓存5分钟）。"""
    import akshare as ak
    return ak.stock_us_spot_em()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_us_price(symbol: str) -> tuple[Optional[float], Optional[str]]:
    """返回 (价格, 来源标签)。优先东财实时，失败则退回日线收盘。"""
    # 主选：东财近实时行情
    try:
        df = _fetch_us_spot_df()
        if df is not None and not df.empty:
            code_col = next((c for c in df.columns if "代码" in c), None)
            price_col = next((c for c in df.columns if "最新" in c), None)
            if code_col and price_col:
                row = df[df[code_col].str.upper() == symbol.upper()]
                if not row.empty:
                    val = row[price_col].iloc[0]
                    if val and float(val) > 0:
                        return round(float(val), 4), "东财实时"
    except Exception:
        pass
    # 兜底：日线收盘（T+1）
    try:
        import akshare as ak
        df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
        if df is not None and not df.empty:
            price = round(float(df["close"].iloc[-1]), 4)
            date_str = str(df["date"].iloc[-1])[:10]
            return price, f"收盘 {date_str[5:]}"
    except Exception:
        pass
    return None, None


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_fund_daily_df():
    """全量开放式基金日数据（含代码、简称、净值），缓存10分钟。"""
    import akshare as ak
    return ak.fund_open_fund_daily_em()


def lookup_fund_name(code: str) -> str:
    """按基金代码查中文名称，找不到则返回代码本身。"""
    try:
        df = _fetch_fund_daily_df()
        if df is not None and not df.empty:
            row = df[df["基金代码"] == code.strip()]
            if not row.empty:
                return str(row["基金简称"].iloc[0])
    except Exception:
        pass
    return code


@st.cache_data(ttl=600, show_spinner=False)
def fetch_fund_nav(code: str) -> Optional[float]:
    """优先从全量缓存取净值，失败则逐只查询。"""
    try:
        df = _fetch_fund_daily_df()
        if df is not None and not df.empty:
            nav_cols = [c for c in df.columns if "单位净值" in c]
            row = df[df["基金代码"] == code.strip()]
            if not row.empty and nav_cols:
                val = row[nav_cols[0]].iloc[0]
                if val and str(val) not in ("", "nan"):
                    return round(float(val), 4)
    except Exception:
        pass
    # 兜底：逐只查询
    try:
        import akshare as ak
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        if df is not None and not df.empty:
            return round(float(df["单位净值"].iloc[-1]), 4)
    except Exception:
        pass
    return None


@st.cache_data(ttl=300, show_spinner=False)
def get_performance_data() -> dict:
    try:
        from performance_tracker import evaluate_us_recs
        return evaluate_us_recs()
    except Exception:
        return {"count": 0, "details": []}


# ─── 页面：当前推荐 ──────────────────────────────────────────────────────────

def page_recommendations():
    st.title("📊 当前推荐")

    us_data = load_json(TMP_DIR / "us_recommendations.json")
    fund_data = load_json(TMP_DIR / "fund_recommendations.json")

    if not us_data and not fund_data:
        st.warning("暂无推荐数据，请前往「🔄 生成推荐」页面生成。")
        return

    # ── 待添加持仓的内联表单 ──────────────────────────────────────────────
    if "pending_add" in st.session_state:
        pa = st.session_state["pending_add"]
        currency = "$" if pa["market"] == "US" else "¥"
        unit_label = "股" if pa["market"] == "US" else "份"

        with st.form("form_add_pos", clear_on_submit=True):
            st.subheader(f"📝 添加持仓：{pa['name']} ({pa['symbol']})")
            c1, c2, c3 = st.columns(3)
            buy_price = c1.number_input(
                f"买入价格 ({currency})",
                value=float(pa["price"]),
                min_value=0.0001,
                format="%.4f",
            )
            shares = c2.number_input(
                f"买入数量 ({unit_label})",
                value=1.0,
                min_value=0.0001,
                step=1.0,
                format="%.2f",
            )
            total = buy_price * shares
            c3.metric("预计总成本", f"{currency}{total:,.2f}")
            col_ok, col_cancel = st.columns(2)
            submitted = col_ok.form_submit_button("✅ 确认添加", use_container_width=True)
            cancelled = col_cancel.form_submit_button("取消", use_container_width=True)

        if submitted:
            from portfolio_tracker import add_position
            add_position(
                market=pa["market"],
                symbol=pa["symbol"],
                name=pa["name"],
                shares=shares,
                buy_price=buy_price,
                session=pa.get("session", ""),
            )
            del st.session_state["pending_add"]
            st.success(f"✅ 已记录：{pa['name']} {shares:.2f}{unit_label} @ {currency}{buy_price:.4f}")
            time.sleep(0.5)
            st.rerun()

        if cancelled:
            del st.session_state["pending_add"]
            st.rerun()

        st.divider()

    col_us, col_fund = st.columns(2)

    with col_us:
        if us_data:
            st.subheader("🇺🇸 美股科技 TOP 5")
            st.caption(
                f"📌 {us_data.get('market_context', '')}  "
                f"｜ 生成于 {(us_data.get('generated_at') or '')[:16]}"
            )
            for r in us_data.get("recommendations", [])[:5]:
                _render_us_card(r, us_data.get("session", ""))

    with col_fund:
        if fund_data:
            st.subheader("🇨🇳 A股基金 TOP 5")
            st.caption(
                f"📌 {fund_data.get('market_context', '')}  "
                f"｜ 生成于 {(fund_data.get('generated_at') or '')[:16]}"
            )
            for r in fund_data.get("recommendations", [])[:5]:
                _render_fund_card(r, fund_data.get("session", ""))


def _render_us_card(r: dict, session: str):
    rank_idx = r.get("rank", 1) - 1
    rank_icon = RANK_EMOJI[rank_idx] if rank_idx < len(RANK_EMOJI) else str(r.get("rank"))
    rating = r.get("rating", "")
    badge = RATING_BADGE.get(rating, "")
    signal = r.get("technical_signal", "")
    sig_icon = SIGNAL_EMOJI.get(signal, "")
    conf = int((r.get("confidence") or 0) * 100)
    price = r.get("current_price", "N/A")

    with st.container(border=True):
        st.markdown(f"**{rank_icon} {r.get('symbol')} — {r.get('name', '')}**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("现价", f"${price}")
        c2.metric("预期收益", fmt_ret_range(r.get("expected_return_pct", {})))
        c3.metric("评分", f"{r.get('score', 'N/A')}/100")
        c4.metric("置信度", f"{conf}%")
        st.caption(
            f"{badge} {rating}  ｜  {sig_icon}{signal}  ｜  持仓 {r.get('holding_period', 'N/A')}"
        )
        st.caption(f"💡 {r.get('core_logic', '')}")
        bull = r.get("bull_points") or []
        if bull:
            st.caption("  ✦ " + "  ✦ ".join(bull[:2]))
        if r.get("key_risk"):
            st.caption(f"  ⚠️ 风险：{r['key_risk']}")

        if st.button("＋ 添加持仓", key=f"add_us_{r.get('symbol')}_{rank_idx}"):
            st.session_state["pending_add"] = {
                "market": "US",
                "symbol": r.get("symbol", ""),
                "name": r.get("name", ""),
                "price": price if isinstance(price, (int, float)) else 1.0,
                "session": session,
            }
            st.rerun()


def _render_fund_card(r: dict, session: str):
    rank_idx = r.get("rank", 1) - 1
    rank_icon = RANK_EMOJI[rank_idx] if rank_idx < len(RANK_EMOJI) else str(r.get("rank"))
    rating = r.get("rating", "")
    badge = RATING_BADGE.get(rating, "")
    trend = r.get("recent_trend", "")
    trend_icon = SIGNAL_EMOJI.get(trend, "")
    conf = int((r.get("confidence") or 0) * 100)
    nav = r.get("latest_nav")
    nav_str = f"¥{nav:.4f}" if nav else "N/A"

    with st.container(border=True):
        st.markdown(f"**{rank_icon} {r.get('name', '')}**  `{r.get('code', '')}`")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("净值", nav_str)
        c2.metric("预期收益", fmt_ret_range(r.get("expected_return_pct", {})))
        c3.metric("评分", f"{r.get('score', 'N/A')}/100")
        c4.metric("置信度", f"{conf}%")
        st.caption(
            f"{badge} {rating}  ｜  {trend_icon}{trend}  ｜  持仓 {r.get('holding_period', 'N/A')}"
        )
        st.caption(f"💡 {r.get('core_logic', '')}")
        bull = r.get("bull_points") or []
        if bull:
            st.caption("  ✦ " + "  ✦ ".join(bull[:2]))
        if r.get("key_risk"):
            st.caption(f"  ⚠️ 风险：{r['key_risk']}")

        code = r.get("code", "")
        if st.button("＋ 添加持仓", key=f"add_fund_{code}_{rank_idx}"):
            st.session_state["pending_add"] = {
                "market": "A_FUND",
                "symbol": code,
                "name": r.get("name", ""),
                "price": float(nav) if nav else 1.0,
                "session": session,
            }
            st.rerun()


# ─── 页面：我的持仓 ──────────────────────────────────────────────────────────

def page_portfolio():
    st.title("💼 我的持仓")

    from portfolio_tracker import (
        load_portfolio, add_position, close_position, delete_position
    )

    positions = load_portfolio()
    open_pos = [p for p in positions if p["status"] == "open"]
    closed_pos = [p for p in positions if p["status"] == "closed"]

    # ── 自动补全 A 股基金名称 ──────────────────────────────────────────────────
    _needs_save = False
    for p in positions:
        if p["market"] == "A_FUND" and not p.get("name"):
            found = lookup_fund_name(p["symbol"])
            if found and found != p["symbol"]:
                p["name"] = found
                _needs_save = True
    if _needs_save:
        from portfolio_tracker import save_portfolio
        save_portfolio(positions)
        open_pos  = [p for p in positions if p["status"] == "open"]
        closed_pos = [p for p in positions if p["status"] == "closed"]

    # ── 汇总统计（仅开仓持仓）────────────────────────────────────────────────
    if open_pos:
        st.subheader("📊 持仓概览")
        st.info(
            "🇺🇸 美股优先使用东方财富近实时行情，失败时退回上一交易日收盘价。"
            "🇨🇳 基金净值为 T+1。盈亏仅供参考，以券商实际价格为准。",
            icon="ℹ️",
        )
        with st.spinner("获取价格中..."):
            enriched = []
            for p in open_pos:
                if p["market"] == "US":
                    price, price_label = fetch_us_price(p["symbol"])
                else:
                    price, price_label = fetch_fund_nav(p["symbol"]), "净值"
                e = _calc_pnl_inline(p, price)
                e["price_label"] = price_label
                enriched.append(e)

        us_pos = [e for e in enriched if e["market"] == "US"]
        a_pos  = [e for e in enriched if e["market"] == "A_FUND"]

        def _summary_metrics(pos_list: list, currency: str, label: str):
            if not pos_list:
                return
            cost  = sum(e["cost"] for e in pos_list)
            value = sum(e["current_value"] for e in pos_list if e["current_value"] is not None)
            pnl   = value - cost if value else None
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(f"{label} 持仓数", len(pos_list))
            c2.metric("总成本", f"{currency}{cost:,.2f}")
            c3.metric(
                "当前市值",
                f"{currency}{value:,.2f}" if value else "—",
                delta=f"{sign_str(pnl)}" if pnl is not None else None,
            )
            c4.metric(
                "总盈亏",
                f"{sign_str(pnl)}" if pnl is not None else "—",
                delta=f"{pnl / cost * 100:+.2f}%" if pnl is not None and cost else None,
            )

        _summary_metrics(us_pos, "$", "🇺🇸")
        if us_pos and a_pos:
            st.divider()
        _summary_metrics(a_pos, "¥", "🇨🇳")

        st.divider()
        _render_portfolio_charts(enriched)
        st.divider()

        # ── 持仓明细 ─────────────────────────────────────────────────────────
        for e in enriched:
            _render_position_card(e, is_open=True)
    else:
        st.info("暂无开仓持仓，前往「📊 当前推荐」添加持仓。")

    # ── 手动添加持仓 ──────────────────────────────────────────────────────────
    with st.expander("✏️ 手动添加持仓"):
        c1, c2 = st.columns(2)
        market = c1.selectbox(
            "市场", ["US", "A_FUND"],
            format_func=lambda x: "🇺🇸 美股" if x == "US" else "🇨🇳 A股基金",
            key="_madd_market",
        )
        symbol = c2.text_input("代码（美股如 AAPL，基金如 110011）", key="_madd_symbol")

        # A 股基金：自动查名称
        if market == "A_FUND" and symbol and symbol.strip():
            if st.button("🔍 自动获取基金名称"):
                with st.spinner("查询中..."):
                    found = lookup_fund_name(symbol.strip())
                st.session_state["_madd_name"] = found
                if found != symbol.strip():
                    st.success(f"找到：{found}")
                else:
                    st.warning("未找到该基金，请手动输入名称")
                st.rerun()

        c3, c4, c5 = st.columns(3)
        name = c3.text_input("名称（可选）", key="_madd_name")
        buy_price = c4.number_input("买入价格", min_value=0.0001, value=1.0, format="%.4f", key="_madd_price")
        shares = c5.number_input("买入数量", min_value=0.0001, value=1.0, format="%.2f", key="_madd_shares")

        if st.button("✅ 添加持仓", type="primary", use_container_width=True):
            if symbol and symbol.strip():
                add_position(
                    market=market, symbol=symbol.strip().upper(),
                    name=name, shares=shares, buy_price=buy_price,
                )
                st.success(f"已添加：{symbol.strip().upper()}")
                for k in ["_madd_symbol", "_madd_name", "_madd_price", "_madd_shares"]:
                    st.session_state.pop(k, None)
                st.rerun()
            else:
                st.warning("请输入代码")

    # ── 已平仓记录 ────────────────────────────────────────────────────────────
    if closed_pos:
        st.divider()
        st.subheader("📁 已平仓记录")
        for p in closed_pos[-10:]:
            e = _calc_pnl_inline(p, float(p["sell_price"]))
            _render_position_card(e, is_open=False)


def _render_portfolio_charts(enriched: list):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    valid = [e for e in enriched if e.get("current_value") is not None]
    if not valid:
        return

    # ── 饼图数据 ──────────────────────────────────────────────────────────────
    labels = [f"{e.get('name') or e['symbol']} ({e['symbol']})" for e in valid]
    values = [e["current_value"] for e in valid]
    colors = ["#1565C0" if e["market"] == "US" else "#C62828" for e in valid]

    # ── 盈亏柱状图数据 ────────────────────────────────────────────────────────
    bar_labels = [e.get("name") or e["symbol"] for e in valid]
    bar_values = [e.get("pnl_pct") or 0.0 for e in valid]
    bar_colors = ["#00C853" if v >= 0 else "#FF1744" for v in bar_values]

    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "domain"}, {"type": "xy"}]],
        subplot_titles=("仓位分布（当前市值）", "各持仓盈亏 %"),
    )

    fig.add_trace(
        go.Pie(
            labels=labels,
            values=values,
            marker=dict(colors=colors),
            textinfo="percent+label",
            hovertemplate="%{label}<br>市值：%{value:,.2f}<br>占比：%{percent}<extra></extra>",
            hole=0.35,
        ),
        row=1, col=1,
    )

    fig.add_trace(
        go.Bar(
            x=bar_labels,
            y=bar_values,
            marker_color=bar_colors,
            text=[f"{v:+.2f}%" for v in bar_values],
            textposition="outside",
            hovertemplate="%{x}<br>盈亏：%{y:+.2f}%<extra></extra>",
        ),
        row=1, col=2,
    )

    fig.update_layout(
        height=360,
        margin=dict(t=40, b=20, l=10, r=10),
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
    )
    fig.update_yaxes(ticksuffix="%", row=1, col=2)

    st.plotly_chart(fig, use_container_width=True)


def _calc_pnl_inline(position: dict, current_price: Optional[float]) -> dict:
    buy_price = float(position["buy_price"])
    shares = float(position["shares"])
    cost = round(buy_price * shares, 4)
    currency = "$" if position["market"] == "US" else "¥"

    if current_price is None:
        return {**position, "cost": cost, "current_price": None,
                "current_value": None, "pnl": None, "pnl_pct": None, "currency": currency}

    current_value = round(current_price * shares, 4)
    pnl = round(current_value - cost, 4)
    pnl_pct = round((current_price - buy_price) / buy_price * 100, 2)
    return {**position, "cost": cost, "current_price": current_price,
            "current_value": current_value, "pnl": pnl, "pnl_pct": pnl_pct, "currency": currency}


def _render_position_card(e: dict, is_open: bool):
    from portfolio_tracker import close_position, delete_position

    currency = e["currency"]
    pnl = e.get("pnl")
    pnl_pct = e.get("pnl_pct")
    pnl_delta = f"{sign_str(pnl_pct)}%" if pnl_pct is not None else None
    market_label = "🇺🇸" if e["market"] == "US" else "🇨🇳"
    unit = "股" if e["market"] == "US" else "份"
    buy_dt = (e.get("buy_date") or "")[:10]

    with st.container(border=True):
        title_col, btn_col = st.columns([4, 1])
        with title_col:
            st.markdown(f"**{market_label} {e.get('name') or e['symbol']}** `{e['symbol']}` — {e['shares']:.2f} {unit}  ｜  买入 {buy_dt}")

        if not is_open:
            price_label = "卖出价"
        elif e["market"] == "US":
            price_label = e.get("price_label") or "前收 (T+1)"
        else:
            price_label = e.get("price_label") or "净值"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("买入价", f"{currency}{e['buy_price']:.4f}")
        c2.metric(
            price_label,
            f"{currency}{e['current_price']:.4f}" if e["current_price"] else "获取中",
        )
        c3.metric("总成本", f"{currency}{e['cost']:,.4f}")
        c4.metric(
            "盈亏(参考)",
            f"{currency}{sign_str(pnl)}" if pnl is not None else "—",
            delta=pnl_delta,
        )

        if e.get("session"):
            st.caption(f"来源：{e['session']} 时段推荐")

        if is_open:
            with btn_col:
                with st.popover("操作"):
                    sell_price = st.number_input(
                        "卖出价格", min_value=0.0001,
                        value=float(e["current_price"] or e["buy_price"]),
                        format="%.4f",
                        key=f"sell_{e['id']}",
                    )
                    if st.button("确认平仓", key=f"close_{e['id']}", use_container_width=True):
                        close_position(e["id"], sell_price)
                        st.rerun()
                    if st.button("🗑️ 删除记录", key=f"del_{e['id']}", use_container_width=True):
                        delete_position(e["id"])
                        st.rerun()
        else:
            sell_dt = (e.get("sell_date") or "")[:10]
            st.caption(f"卖出价：{currency}{e.get('sell_price', 'N/A')}  ｜  平仓日：{sell_dt}")


# ─── 持仓决策：预算持久化 ────────────────────────────────────────────────────

BUDGET_FILE = TMP_DIR / "budget_settings.json"


def load_budget() -> tuple[float, float]:
    """返回 (us_budget, a_budget)。"""
    if BUDGET_FILE.exists():
        try:
            d = json.loads(BUDGET_FILE.read_text())
            return float(d.get("us_budget", 0)), float(d.get("a_budget", 0))
        except Exception:
            pass
    return 0.0, 0.0


def save_budget(us_budget: float, a_budget: float) -> None:
    BUDGET_FILE.write_text(json.dumps({
        "us_budget": us_budget,
        "a_budget": a_budget,
        "updated_at": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2))


# ─── 页面：今日决策 ──────────────────────────────────────────────────────────

ACTION_LABEL = {
    "hold": ("➡️ 持有", "#2196F3"),
    "increase": ("⬆️ 加仓", "#00C853"),
    "reduce": ("⬇️ 减仓", "#FF9800"),
    "close": ("❌ 清仓", "#F44336"),
}


def page_portfolio_decisions():
    st.title("💡 今日决策建议")

    from portfolio_tracker import load_portfolio

    # ── 预算设置区 ────────────────────────────────────────────────────────────
    us_budget_saved, a_budget_saved = load_budget()

    with st.expander("⚙️ 预算设置", expanded=(us_budget_saved == 0 and a_budget_saved == 0)):
        st.markdown("设置你的总投资预算上限，AI 将据此建议仓位分配。")
        bc1, bc2, bc3 = st.columns([2, 2, 1])
        us_input = bc1.number_input(
            "🇺🇸 美股总预算（USD）",
            min_value=0.0, value=us_budget_saved, step=500.0, format="%.0f",
        )
        a_input = bc2.number_input(
            "🇨🇳 A股基金总预算（CNY）",
            min_value=0.0, value=a_budget_saved, step=1000.0, format="%.0f",
        )
        if bc3.button("💾 保存预算", use_container_width=True):
            save_budget(us_input, a_input)
            st.success("预算已保存")
            st.rerun()

    us_budget, a_budget = load_budget()

    # ── 持仓 + 预算概览 ───────────────────────────────────────────────────────
    positions = load_portfolio()
    open_pos = [p for p in positions if p["status"] == "open"]

    if not open_pos:
        st.warning("暂无开仓持仓。请先在「💼 我的持仓」或「📊 当前推荐」中添加持仓。")
        return

    st.subheader("📊 当前预算使用情况")
    st.info(
        "🇺🇸 美股优先使用东方财富近实时行情；🇨🇳 基金净值为 T+1。建议方向仅供参考，实际操作以券商价格为准。",
        icon="ℹ️",
    )

    with st.spinner("获取持仓价格中..."):
        enriched = []
        for p in open_pos:
            if p["market"] == "US":
                price, price_label = fetch_us_price(p["symbol"])
            else:
                price, price_label = fetch_fund_nav(p["symbol"]), "净值"
            e = _calc_pnl_inline(p, price)
            e["price_label"] = price_label
            enriched.append(e)

    us_positions = [e for e in enriched if e["market"] == "US"]
    a_positions = [e for e in enriched if e["market"] == "A_FUND"]

    us_value = sum(e["current_value"] or e["cost"] for e in us_positions)
    a_value = sum(e["current_value"] or e["cost"] for e in a_positions)

    col_us, col_a = st.columns(2)
    with col_us:
        if us_budget > 0:
            used_pct = us_value / us_budget * 100
            avail = max(0, us_budget - us_value)
            st.metric("🇺🇸 美股预算", f"${us_budget:,.0f}")
            st.metric("已投入", f"${us_value:,.2f}", delta=f"{used_pct:.1f}% 已用")
            st.metric("可用资金", f"${avail:,.2f}")
            st.progress(min(used_pct / 100, 1.0))
        else:
            st.info("未设置美股预算")

    with col_a:
        if a_budget > 0:
            used_pct = a_value / a_budget * 100
            avail = max(0, a_budget - a_value)
            st.metric("🇨🇳 A股基金预算", f"¥{a_budget:,.0f}")
            st.metric("已投入", f"¥{a_value:,.2f}", delta=f"{used_pct:.1f}% 已用")
            st.metric("可用资金", f"¥{avail:,.2f}")
            st.progress(min(used_pct / 100, 1.0))
        else:
            st.info("未设置A股预算")

    st.divider()

    # ── 生成 AI 决策建议 ──────────────────────────────────────────────────────
    decisions_file = TMP_DIR / "portfolio_decisions.json"
    cached = load_json(decisions_file)
    if cached:
        gen_at = cached.get("generated_at") or ""
        gen_at_short = gen_at[:16]
        try:
            age_h = (datetime.now() - datetime.fromisoformat(gen_at)).total_seconds() / 3600
            if age_h > 12:
                st.warning(f"⚠️ 当前建议生成于 {age_h:.0f} 小时前，市场可能已变化，建议点击「重新生成」。")
            else:
                st.caption(f"上次分析时间：{gen_at_short}　　点击「重新生成」更新")
        except Exception:
            st.caption(f"上次分析时间：{gen_at_short}")

    col_btn1, col_btn2 = st.columns([2, 1])
    do_generate = col_btn1.button(
        "⚡ 生成今日 AI 决策建议", type="primary", use_container_width=True
    )
    do_clear = col_btn2.button("🗑️ 清除缓存", use_container_width=True)

    if do_clear and decisions_file.exists():
        decisions_file.unlink()
        st.rerun()

    if do_generate:
        if not enriched:
            st.warning("无持仓数据")
        else:
            with st.spinner("DeepSeek 正在分析持仓决策（约 30~60 秒）..."):
                try:
                    from analyze_portfolio_decisions import analyze_portfolio_decisions
                    result = analyze_portfolio_decisions(
                        positions_with_price=enriched,
                        us_budget=us_budget,
                        a_budget=a_budget,
                    )
                    st.success("分析完成！")
                    cached = result
                except Exception as e:
                    st.error(f"分析失败：{e}")

    # ── 渲染决策结果 ──────────────────────────────────────────────────────────
    if cached and "decisions" in cached:
        _render_decisions(cached, enriched)


def _render_decisions(result: dict, enriched: list):
    trade_info = result.get("trade_info", {})
    trade_date = result.get("trade_date", "")

    # 交易日状态 banner
    us_ok = trade_info.get("us_is_trading_day", True)
    a_ok = trade_info.get("a_is_trading_day", True)
    if us_ok and a_ok:
        st.success(f"📅 今日为交易日，以下建议适用于 **{trade_date}**")
    else:
        next_days = []
        if not us_ok:
            next_days.append(f"美股 {trade_info.get('us_next_trading_day', '')}")
        if not a_ok:
            next_days.append(f"A股 {trade_info.get('a_next_trading_day', '')}")
        st.warning(
            f"📅 今日部分市场休市。以下建议适用于下一交易日：**{', '.join(next_days)}**"
        )

    # 市场研判 + 持仓评估
    c1, c2 = st.columns(2)
    c1.info(f"🌐 **市场研判**\n\n{result.get('market_context', '')}")
    c2.info(f"💼 **持仓健康度**\n\n{result.get('portfolio_health', '')}")

    if result.get("cash_advice"):
        st.info(f"💰 **资金建议** — {result['cash_advice']}")

    st.divider()

    # 每个持仓的决策卡片
    st.subheader("📋 各持仓操作建议")

    decisions = result.get("decisions", [])
    pos_map = {e["symbol"]: e for e in enriched}

    for d in decisions:
        symbol = d.get("symbol", "")
        action = d.get("action", "hold")
        label, color = ACTION_LABEL.get(action, ("➡️ 持有", "#2196F3"))
        action_shares = d.get("action_shares", 0)
        action_amount = d.get("action_amount", 0)
        reduce_pct = d.get("reduce_pct", 0)
        confidence = int((d.get("confidence") or 0) * 100)
        pos = pos_map.get(symbol, {})
        market = d.get("market", pos.get("market", "US"))
        currency = "$" if market == "US" else "¥"
        unit = "股" if market == "US" else "份"

        with st.container(border=True):
            header_col, badge_col = st.columns([4, 1])
            market_flag = "🇺🇸" if market == "US" else "🇨🇳"
            header_col.markdown(
                f"**{market_flag} {d.get('name', symbol)}** `{symbol}`"
            )
            badge_col.markdown(
                f'<span style="background:{color};color:white;padding:4px 10px;'
                f'border-radius:12px;font-size:0.85rem;font-weight:bold">{label}</span>',
                unsafe_allow_html=True,
            )

            # 当前持仓数据
            c1, c2, c3, c4 = st.columns(4)
            shares = pos.get("shares", 0)
            cur_price = pos.get("current_price")
            pnl_pct = pos.get("pnl_pct")
            c1.metric("持有数量", f"{shares:.2f} {unit}")
            c2.metric(
                "当前价格",
                f"{currency}{cur_price:.4f}" if cur_price else "—",
            )
            pnl_str = f"{pnl_pct:+.2f}%" if pnl_pct is not None else "—"
            c3.metric(
                "当前盈亏",
                pnl_str,
                delta=pnl_str if pnl_pct is not None else None,
            )
            c4.metric("置信度", f"{confidence}%")

            # 操作详情
            if action in ("increase", "reduce", "close") and action_shares != 0:
                abs_shares = abs(action_shares)
                abs_amount = abs(action_amount)
                action_verb = "买入" if action == "increase" else "卖出"
                detail = f"建议 **{action_verb} {abs_shares:.2f} {unit}**（约 {currency}{abs_amount:,.2f}）"
                if action == "reduce" and reduce_pct > 0:
                    detail += f"，减仓 **{reduce_pct:.0f}%**"
                st.markdown(detail)

            # 理由 + 止盈止损
            st.caption(f"💡 {d.get('reason', '')}")
            meta_parts = []
            if d.get("target_price"):
                meta_parts.append(f"目标价：{currency}{d['target_price']:.2f}")
            if d.get("stop_loss"):
                meta_parts.append(f"止损价：{currency}{d['stop_loss']:.2f}")
            if meta_parts:
                st.caption("  ｜  ".join(meta_parts))

    # 整体调仓建议
    tips = result.get("rebalance_tips", [])
    if tips:
        st.divider()
        st.subheader("🔄 整体调仓建议")
        for tip in tips:
            st.markdown(f"• {tip}")


# ─── 页面：历史表现 ──────────────────────────────────────────────────────────

def page_performance():
    st.title("📈 历史推荐表现")

    with st.spinner("分析历史推荐中（需获取当前价格）..."):
        perf = get_performance_data()

    if perf["count"] == 0:
        st.info("暂无可评估的历史推荐（推荐需至少 3 天前生成才纳入统计）。")
        _show_raw_history()
        return

    # 汇总指标
    hit_rate = perf["hit_rate"]
    avg_actual = perf["avg_actual"]
    avg_expected = perf["avg_expected"]
    sign = lambda v: f"+{v}%" if v >= 0 else f"{v}%"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("已评估推荐数", perf["count"])
    c2.metric("平均实际收益", sign(avg_actual))
    c3.metric("平均预期收益", sign(avg_expected))
    hit_color = "normal" if hit_rate >= 60 else ("off" if hit_rate < 40 else "normal")
    c4.metric("预期达成率", f"{hit_rate}%")

    # 评级标注
    if hit_rate >= 70:
        st.success(f"AI 推荐准确率良好（{hit_rate}%），预测可信度高。")
    elif hit_rate >= 50:
        st.warning(f"AI 推荐准确率中等（{hit_rate}%），建议结合个人判断。")
    else:
        st.error(f"AI 推荐准确率偏低（{hit_rate}%），下次推荐将自动收紧预期区间。")

    # 明细表格
    st.divider()
    st.subheader("推荐明细")
    details = perf.get("details", [])
    if details:
        import pandas as pd
        rows = []
        for d in details:
            rows.append({
                "代码": d["symbol"],
                "名称": d["name"],
                "推荐日期": (d["archived_at"] or "")[:10],
                "评级": d["rating"],
                "买入价($)": d["buy_price"],
                "当前价($)": d["current_price"],
                "实际收益": f"{'+' if d['actual_pct'] >= 0 else ''}{d['actual_pct']}%",
                "预期收益(中值)": f"+{d['expected_pct']}%",
                "是否达标": "✓" if d["hit"] else "✗",
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

    _show_raw_history()


def _show_raw_history():
    history_file = TMP_DIR / "recommendation_history.jsonl"
    if not history_file.exists():
        return
    st.divider()
    with st.expander("📋 原始推荐历史（最近 20 条）"):
        lines = history_file.read_text().strip().splitlines()
        for line in reversed(lines[-20:]):
            try:
                r = json.loads(line)
                market = r.get("market", "")
                name = r.get("name") or r.get("code", "")
                symbol = r.get("symbol") or r.get("code", "")
                exp = r.get("expected_return") or {}
                st.text(
                    f"{(r.get('archived_at') or '')[:16]}  [{market}]  "
                    f"{symbol} {name}  评级:{r.get('rating','')}  "
                    f"预期:+{exp.get('low',0)}%~+{exp.get('high',0)}%"
                )
            except Exception:
                pass


# ─── 页面：生成推荐 ──────────────────────────────────────────────────────────

def page_generate():
    st.title("🔄 生成推荐")

    st.markdown("""
推荐时段说明：
- **早间** — 美股隔夜复盘 + A股开盘建仓机会
- **午后** — A股收盘复盘 + 美股开盘前布局
- **晚间** — 美股盘中分析 + A股次日展望
""")

    col1, col2 = st.columns([1, 2])
    with col1:
        auto_sess = _auto_session()
        session_opts = ["morning", "afternoon", "evening"]
        session = st.selectbox(
            "选择时段",
            session_opts,
            index=session_opts.index(auto_sess),
            format_func=lambda x: {"morning": "早间 🌅", "afternoon": "午后 ☀️", "evening": "晚间 🌙"}[x],
            help=f"当前北京时间 {datetime.now(_TZ_BEIJING).strftime('%H:%M')}，已自动选择推荐时段",
        )
        force_refresh = st.checkbox("强制刷新数据（忽略30分钟缓存）", value=False)
        test_mode = st.checkbox("测试模式（不发送 Telegram）", value=False)

    with col2:
        st.info(
            "点击「一键生成」将依次执行：\n"
            "1. 获取美股 + A股基金候选数据\n"
            "2. DeepSeek AI 分析（含历史准确率反馈）\n"
            "3. 发送 Telegram 推送\n"
            "4. 归档推荐历史"
        )

    if st.button("⚡ 一键生成推荐", type="primary", use_container_width=True):
        _run_recommendation(session, force_refresh, test_mode)

    # 仅发送（使用已有分析结果）
    st.divider()
    st.subheader("单独操作")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📤 重新发送 Telegram（使用现有分析）", use_container_width=True):
            _send_only(session)
    with c2:
        if st.button("🔍 仅分析（不发送）", use_container_width=True):
            _analyze_only(session)


def _run_recommendation(session: str, force_refresh: bool, test_mode: bool):
    cmd = [sys.executable, "tools/run_recommendation.py", "--session", session]
    if force_refresh:
        cmd.append("--force-refresh")
    if test_mode:
        cmd.append("--test")

    st.markdown("**⏳ 执行中...**")
    output_area = st.empty()
    progress = st.progress(0, text="启动中...")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        lines = []
        step_map = {
            "Step 1": 25, "Step 2": 50, "Step 3": 75, "Step 4": 90,
            "全流程完成": 100,
        }
        for line in proc.stdout:
            line = line.strip()
            if line:
                lines.append(line)
                output_area.code("\n".join(lines[-20:]), language="text")
                for keyword, pct in step_map.items():
                    if keyword in line:
                        progress.progress(pct / 100, text=line[:80])
        proc.wait()
        if proc.returncode == 0:
            progress.progress(1.0, text="✅ 完成")
            st.success("推荐生成成功！前往「📊 当前推荐」查看结果。")
        else:
            st.error("推荐生成失败，请查看上方日志。")
    except Exception as e:
        st.error(f"执行出错：{e}")


def _send_only(session: str):
    with st.spinner("发送中..."):
        result = subprocess.run(
            [sys.executable, "tools/send_telegram.py", "--session", session],
            cwd=str(Path(__file__).parent),
            capture_output=True, text=True,
        )
    if result.returncode == 0:
        st.success("Telegram 推送成功！")
    else:
        st.error(f"发送失败：{result.stderr[-500:]}")


def _analyze_only(session: str):
    with st.spinner("DeepSeek 分析中（约 30~60 秒）..."):
        result = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0,'tools'); "
             f"from analyze_with_deepseek import analyze_us, analyze_funds; "
             f"analyze_us('{session}'); analyze_funds('{session}')"],
            cwd=str(Path(__file__).parent),
            capture_output=True, text=True,
        )
    if result.returncode == 0:
        st.success("分析完成！前往「📊 当前推荐」查看结果。")
    else:
        st.error(f"分析失败：{result.stderr[-500:]}")


# ─── 主路由 ──────────────────────────────────────────────────────────────────

def main():
    with st.sidebar:
        st.title("📈 智能股票助手")
        st.caption("DeepSeek AI 驱动的个人投资参考工具")
        st.divider()
        page = st.radio(
            "导航",
            ["📊 当前推荐", "💼 我的持仓", "💡 今日决策", "📈 历史表现", "🔄 生成推荐"],
            label_visibility="collapsed",
        )
        st.divider()
        # 实时市场状态（使用各自正确的时区判定）
        now_bj = datetime.now(_TZ_BEIJING)
        now_et = datetime.now(_TZ_US_EASTERN)
        st.caption(f"🇨🇳 A股  {now_bj.strftime('%H:%M')} BJT")
        st.caption(_a_share_status(now_bj))
        st.caption(f"🇺🇸 美股  {now_et.strftime('%H:%M')} ET")
        st.caption(_us_market_status(now_et))
        st.divider()
        # 快捷状态
        us_data = load_json(TMP_DIR / "us_recommendations.json")
        fund_data = load_json(TMP_DIR / "fund_recommendations.json")
        if us_data:
            st.caption(f"最新美股推荐：{(us_data.get('generated_at') or '')[:16]}")
        if fund_data:
            st.caption(f"最新A股推荐：{(fund_data.get('generated_at') or '')[:16]}")
        st.divider()
        st.caption("⚠️ 仅供个人参考，不构成投资建议")

    if page == "📊 当前推荐":
        page_recommendations()
    elif page == "💼 我的持仓":
        page_portfolio()
    elif page == "💡 今日决策":
        page_portfolio_decisions()
    elif page == "📈 历史表现":
        page_performance()
    elif page == "🔄 生成推荐":
        page_generate()


if __name__ == "__main__":
    main()

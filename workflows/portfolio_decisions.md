# 持仓决策分析工作流

## 目标
基于用户当前持仓、实时价格、预算约束，调用 DeepSeek AI 生成今日（或下一交易日）的具体操作建议。

## 输入
- 当前开仓持仓列表（来自 `.tmp/portfolio.json`）
- 美股总预算（USD）和 A 股总预算（CNY）（来自 `.tmp/budget_settings.json`）
- 实时/最近一交易日价格（akshare 获取）

## 调用工具
`tools/analyze_portfolio_decisions.py`

## 执行步骤

1. **加载持仓** — `portfolio_tracker.load_portfolio()` 取 `status=open` 的持仓
2. **获取价格** — 美股用 `akshare.stock_us_daily`，A 股基金用 `akshare.fund_open_fund_info_em`
3. **计算盈亏** — `_calc_pnl_inline` 算出 cost / current_value / pnl_pct
4. **交易日判断** — `get_trading_day_info()` 检查今日是否为美股 / A 股交易日，计算下一交易日
5. **构建 Prompt** — 注入预算、持仓盈亏、交易日信息
6. **调用 DeepSeek** — `deepseek-chat`，temperature=0.3，最多重试 3 次
7. **解析输出** — 得到每个持仓的 action（hold/increase/reduce/close）+ 操作股数/金额
8. **保存结果** — `.tmp/portfolio_decisions.json`

## 输出格式
```json
{
  "trade_date": "YYYY-MM-DD",
  "market_context": "市场研判",
  "portfolio_health": "持仓健康度",
  "cash_advice": "资金建议",
  "decisions": [
    {
      "symbol": "META",
      "action": "hold | increase | reduce | close",
      "action_shares": 0.5,
      "action_amount": 325.0,
      "reduce_pct": 0,
      "reason": "操作理由",
      "confidence": 0.8,
      "target_price": 700.0,
      "stop_loss": 620.0
    }
  ],
  "rebalance_tips": ["调仓建议1", "调仓建议2"]
}
```

## 异常处理
- DeepSeek 超时/限流：自动重试 3 次，间隔 30 秒
- 价格获取失败：使用买入成本作为 current_value 估算（标注"N/A"）
- JSON 解析失败：抛出异常，原始响应打印到日志

## 注意事项
- 美股价格为前一交易日收盘价（T+1），非实时，建议仅作参考方向
- 假期表仅覆盖 2026 年，需每年更新 `_US_HOLIDAYS_2026` 和 `_A_HOLIDAYS_2026`
- 结果缓存在 `.tmp/portfolio_decisions.json`，点击「清除缓存」或「重新生成」刷新

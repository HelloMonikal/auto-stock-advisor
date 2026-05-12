# DeepSeek 智能分析与推荐排名工作流

## 执行目标
调用 DeepSeek API，对候选股票/基金进行综合分析，输出排名 TOP 5 及结构化推荐理由。

## 必填输入
- `us_candidates_path`：`.tmp/us_tech_candidates.json`（美股候选数据）
- `fund_candidates_path`：`.tmp/a_share_fund_candidates.json`（A 股基金候选数据）
- `session`：推送时段，`morning`/`afternoon`/`evening`

## 执行步骤

### Step 1：DeepSeek 美股分析
**工具**：`tools/analyze_with_deepseek.py --type us --session {session}`
**入参**：`us_tech_candidates.json`
**产出**：TOP 5 美股推荐，含排名、评级、目标价、持仓周期、核心逻辑
**存储**：`.tmp/us_recommendations.json`

### Step 2：DeepSeek A 股基金分析
**工具**：`tools/analyze_with_deepseek.py --type fund --session {session}`
**入参**：`a_share_fund_candidates.json`
**产出**：TOP 5 基金推荐，含排名、评级、持仓周期、核心逻辑
**存储**：`.tmp/fund_recommendations.json`

## 时段差异化分析策略

### 早间（morning，10:00）
- 重点：A 股开盘方向研判 + 美股隔夜收盘复盘
- 美股 prompt 附加：隔夜涨跌幅解读、今日关注点
- 基金 prompt 附加：A 股高开/低开预期，建仓时机

### 下午（afternoon，16:00）
- 重点：A 股收盘复盘 + 美股今晚开盘预判
- 美股 prompt 附加：今晚美股开盘方向预测
- 基金 prompt 附加：今日 A 股表现分析，持仓建议

### 晚间（evening，21:00）
- 重点：美股盘中实时分析 + 明日 A 股展望
- 美股 prompt 附加：当日盘中表现、尾盘方向
- 基金 prompt 附加：明日 A 股基金布局建议

## DeepSeek 输出格式要求
```json
{
  "session": "morning",
  "market": "US",
  "generated_at": "2026-04-29T10:00:00",
  "recommendations": [
    {
      "rank": 1,
      "symbol": "NVDA",
      "name": "英伟达",
      "current_price": 890.2,
      "rating": "强烈买入",
      "confidence": 0.85,
      "expected_return_pct": {"low": 8, "high": 15},
      "holding_period": "1-3个月",
      "core_logic": "50字内核心逻辑",
      "bull_points": ["利多1", "利多2"],
      "key_risk": "最主要风险",
      "technical_signal": "看涨",
      "score": 88
    }
  ],
  "market_context": "当前市场整体判断（50字）"
}
```

## 历史追踪
- 每次推荐存档至 `.tmp/recommendation_history.jsonl`（追加模式）
- 格式：每行一条推荐记录，包含推荐时间和当时价格
- 用途：下次推送时计算上次推荐至今的实际收益率，增加可信度

## 异常兜底
- DeepSeek API 超时/限流：等待 30 秒重试，最多 3 次
- JSON 解析失败：记录原始响应至 `.tmp/deepseek_raw_{timestamp}.txt`，使用上次结果
- 候选数据不足（< 5 只）：直接用现有数量生成推荐，不强制凑 5

# 每日自动推荐主工作流

## 执行目标
每天 10:00、16:00、21:00 自动完成：数据获取 → AI 分析 → Telegram 推送全流程。

## 触发方式
- **定时触发**：`tools/scheduler.py` 通过 APScheduler 在三个时间点自动触发
- **手动触发**：`python tools/run_recommendation.py --session morning|afternoon|evening`

## 完整执行流程

```
[定时触发]
     │
     ▼
Step 1: 获取美股科技股数据
     tools/fetch_us_tech_stocks.py
     → .tmp/us_tech_candidates.json
     │
     ▼
Step 2: 获取 A 股基金数据（并行执行）
     tools/fetch_a_share_funds.py
     → .tmp/a_share_fund_candidates.json
     │
     ▼
Step 3: DeepSeek 分析（美股 + 基金并行）
     tools/analyze_with_deepseek.py --type us
     tools/analyze_with_deepseek.py --type fund
     → .tmp/us_recommendations.json
     → .tmp/fund_recommendations.json
     │
     ▼
Step 4: 发送 Telegram 消息
     tools/send_telegram.py
     ← us_recommendations.json + fund_recommendations.json
     │
     ▼
Step 5: 归档推荐历史（异步）
     追加至 .tmp/recommendation_history.jsonl
```

## 时间节点说明

| 时间 | 时段标识 | 市场状态 | 分析重点 |
|------|---------|---------|---------|
| 10:00 | morning | A 股开盘30分钟 / 美股昨日收盘 | A 股开盘方向 + 美股隔夜解读 |
| 16:00 | afternoon | A 股收盘后 / 美股开盘前 | A 股收盘复盘 + 美股今晚预判 |
| 21:00 | evening | A 股收盘 / 美股开盘约 3h | 美股盘中实时 + 明日 A 股布局 |

## 异常处理优先级
1. 数据获取失败 → 使用 `.tmp/` 最近一次缓存（< 8 小时）
2. DeepSeek 分析失败 → 发送简化版消息（仅数据，无 AI 分析）
3. Telegram 发送失败 → 记录至 `.tmp/failed_sends.log`，10 分钟后重试一次
4. 全流程失败 → 发送错误通知至 Telegram

## 执行日志
所有执行日志输出至标准输出（可重定向至文件）
格式：`[timestamp] [level] [step] message`

## 注意事项
- 确保 `.env` 已配置 `DEEPSEEK_API_KEY` 和 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`
- 首次运行前执行：`pip install -r requirements.txt`
- 调度器以服务方式运行：`python tools/scheduler.py`
- 建议用 `nohup` 或 `screen` 保持后台运行

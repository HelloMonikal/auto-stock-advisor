# 股票分析工作流

## 执行目标
对指定股票进行多维度分析，生成投资参考报告，归档至 Google Sheets。

## 必填输入
- `symbols`：股票代码列表，如 `["AAPL", "TSLA", "NVDA"]`
- `market`：市场类型，`US`（美股）或 `CN`（A股，代码格式如 `000001.SZ`）

## 可选输入
- `period`：历史数据周期，默认 `3mo`（可选：1mo / 3mo / 6mo / 1y / 2y）
- `output_sheet`：Google Sheets 工作表名称，默认 `Stock Analysis`

## 执行步骤

### Step 1：获取股票基础数据
**工具**：`tools/fetch_stock_data.py`
**入参**：symbol, period
**产出**：价格历史、基础财务指标（PE、市值、52周高低等）
**存储**：`.tmp/stock_data_{symbol}.json`

### Step 2：获取近期新闻与舆情
**工具**：`tools/fetch_stock_news.py`
**入参**：symbol, limit=10
**产出**：最近新闻标题、来源、情绪评分
**存储**：`.tmp/stock_news_{symbol}.json`

### Step 3：AI 综合分析
**工具**：`tools/analyze_stock.py`
**入参**：`.tmp/stock_data_{symbol}.json` + `.tmp/stock_news_{symbol}.json`
**产出**：投资评级（买入/持有/卖出）、风险提示、关键驱动因素
**存储**：`.tmp/stock_report_{symbol}.json`

### Step 4：归档至 Google Sheets（可选）
**工具**：`tools/export_to_sheets.py`
**入参**：所有 `.tmp/stock_report_*.json` 文件 + spreadsheet_id
**产出**：Google Sheets 链接

## 输出标准
每只股票报告包含：
- 基础数据：现价、涨跌幅、PE、市值
- 技术面：均线趋势、RSI、成交量变化
- 基本面：营收增长、利润率
- 新闻情绪：近期利好/利空比例
- AI 评级：买入 / 持有 / 卖出 + 置信度 + 核心理由

## 异常兜底
- 股票代码无效：跳过该股票，记录错误，继续处理其余代码
- API 限流：等待 60 秒后重试，最多重试 3 次
- Google Sheets 写入失败：本地保存至 `.tmp/final_report.json` 作为备份
- 数据缺失：标注"数据不可用"，不影响其余字段生成

## 注意事项
- yfinance 免费但数据延迟约 15 分钟
- A 股数据通过 yfinance 获取时代码需加后缀：`.SS`（上交所）或 `.SZ`（深交所）
- AI 分析结果仅供参考，不构成投资建议

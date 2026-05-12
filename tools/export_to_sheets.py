#!/usr/bin/env python3
"""
将所有股票分析报告归档至 Google Sheets
输入：.tmp/stock_report_*.json 文件
输出：Google Sheets 链接
"""

import json
import argparse
from pathlib import Path
from datetime import datetime

import gspread
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dotenv import load_dotenv
import os

load_dotenv()

TMP_DIR = Path(__file__).parent.parent / ".tmp"
CREDENTIALS_FILE = Path(__file__).parent.parent / "credentials.json"
TOKEN_FILE = Path(__file__).parent.parent / "token.json"
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

HEADERS = [
    "分析时间", "股票代码", "当前价格", "月涨跌幅(%)",
    "PE 市盈率", "市值", "RSI(14)",
    "评级", "置信度", "技术信号", "新闻情绪",
    "一句话总结", "目标价区间(低)", "目标价区间(高)",
    "利多因素", "利空因素", "主要风险",
    "免责声明",
]


def get_gspread_client():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "缺少 credentials.json，请从 Google Cloud Console 下载 OAuth 凭证"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return gspread.authorize(creds)


def load_reports() -> list[dict]:
    reports = []
    for path in sorted(TMP_DIR.glob("stock_report_*.json")):
        try:
            reports.append(json.loads(path.read_text()))
        except Exception as e:
            print(f"[WARN] 跳过 {path.name}：{e}")
    return reports


def report_to_row(r: dict) -> list:
    a = r.get("analysis", {})
    snap = r.get("data_snapshot", {})
    target = a.get("target_price_range") or {}
    return [
        r.get("analyzed_at", ""),
        r.get("symbol", ""),
        r.get("price_at_analysis", ""),
        snap.get("month_return_pct", ""),
        snap.get("pe_ratio", ""),
        snap.get("market_cap", ""),
        snap.get("rsi_14", ""),
        a.get("rating", ""),
        a.get("confidence", ""),
        a.get("technical_signal", ""),
        a.get("news_sentiment", ""),
        a.get("summary", ""),
        target.get("low", ""),
        target.get("high", ""),
        " / ".join(a.get("bull_case", [])),
        " / ".join(a.get("bear_case", [])),
        " / ".join(a.get("key_risks", [])),
        a.get("disclaimer", ""),
    ]


def export(spreadsheet_id: str, sheet_name: str = "Stock Analysis") -> str:
    reports = load_reports()
    if not reports:
        raise ValueError("未找到任何 .tmp/stock_report_*.json 文件，请先运行 analyze_stock.py")

    client = get_gspread_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    try:
        ws = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=sheet_name, rows=500, cols=len(HEADERS))

    existing = ws.get_all_values()
    if not existing or existing[0] != HEADERS:
        ws.clear()
        ws.append_row(HEADERS)

    rows = [report_to_row(r) for r in reports]
    ws.append_rows(rows, value_input_option="USER_ENTERED")

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    print(f"[OK] 已写入 {len(rows)} 条报告 → {url}")
    return url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
        help="Google Sheets ID（也可通过 .env 配置 GOOGLE_SHEETS_SPREADSHEET_ID）",
    )
    parser.add_argument("--sheet-name", default="Stock Analysis", help="工作表名称")
    args = parser.parse_args()

    if not args.spreadsheet_id:
        raise ValueError("请通过 --spreadsheet-id 或 .env 中的 GOOGLE_SHEETS_SPREADSHEET_ID 提供表格 ID")

    url = export(args.spreadsheet_id, args.sheet_name)
    print(url)


if __name__ == "__main__":
    main()

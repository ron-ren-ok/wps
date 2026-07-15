#!/usr/bin/env python3
"""Send the current daily-progress values from Google Sheets to a WPS group bot.

This job only reads the spreadsheet's existing formula results.  It does not
call an AI service or alter the spreadsheet.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from zoneinfo import ZoneInfo

import google.auth.transport.requests
from google.oauth2 import service_account
import requests


SPREADSHEET_ID = "1vSBU84SFoVlXdaczYYAev8mC0PEfjRQyVSv8s2OAGW4"
SHEET_NAME = "日进度追踪"
SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    f"{SPREADSHEET_ID}/edit#gid=1377957533"
)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
BJ_TZ = ZoneInfo("Asia/Shanghai")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def row_value(rows: list[list[dict]], row: int, column: int) -> str:
    try:
        return rows[row][column].get("formattedValue", "").strip()
    except IndexError as exc:
        raise RuntimeError("The 日进度追踪 summary range is incomplete.") from exc


def normalized_date(value: str) -> str:
    return value.strip().replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")


def last_status(rows: list[list[dict]], date_column: int, status_column: int) -> str:
    for row in reversed(rows):
        if len(row) > status_column:
            date = row[date_column].get("formattedValue", "").strip()
            status = row[status_column].get("formattedValue", "").strip()
            if date and status:
                return status
    return "状态待核对"


def status_for_date(rows: list[list[dict]], target_date: str, date_column: int, status_column: int) -> tuple[str, bool]:
    target = normalized_date(target_date)
    for row in rows:
        if len(row) > status_column and normalized_date(row[date_column].get("formattedValue", "")) == target:
            status = row[status_column].get("formattedValue", "").strip()
            if status:
                return status, False
    return last_status(rows, date_column, status_column), True


def display_status(status: str) -> str:
    if status == "完整":
        return "✅ 数据完整"
    return f"⚠️ {status}" if status else "⚠️ 状态待核对"


def request_values() -> list[list[list[dict]]]:
    info = json.loads(required("GOOGLE_SERVICE_ACCOUNT_JSON"))
    credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    session = google.auth.transport.requests.AuthorizedSession(credentials)
    response = session.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}",
        params={
            "ranges": [f"{SHEET_NAME}!A1:P6", f"{SHEET_NAME}!A10:I40", f"{SHEET_NAME}!J10:R40"],
            "includeGridData": "true",
            "fields": "sheets(data(rowData(values(formattedValue,effectiveValue))))",
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json().get("sheets", [{}])[0].get("data", [])
    if len(data) != 3:
        raise RuntimeError("Google Sheets returned an unexpected number of ranges.")
    return [[row.get("values", []) for row in grid.get("rowData", [])] for grid in data]

def card_text(summary: list[list[dict]], revenue_rows: list[list[dict]], users_rows: list[list[dict]]) -> str:
    # A1:P6 indices: row 2 => 1, row 4 => 3, row 6 => 5; B/D/F/H/J/L/N/P => 1/3/.../15.
    cutoff = row_value(summary, 1, 4)
    revenue_status, revenue_fallback = status_for_date(revenue_rows, cutoff, 0, 8)
    users_status, users_fallback = status_for_date(users_rows, cutoff, 0, 8)
    fallback_note = "\n\n⚠️ 状态待核对：未找到数据截止日对应的状态行，已使用最近一条状态。" if revenue_fallback or users_fallback else ""

    def metric(row: int, unit: str, title: str) -> str:
        return (
            f"**{title}（{unit}）**\n"
            f"累计完成 **{row_value(summary, row, 3)}**　目标 **{row_value(summary, row, 1)}**　完成率 **{row_value(summary, row, 5)}**\n"
            f"时间进度 {row_value(summary, row, 13)}　·　{row_value(summary, row, 15)}\n"
            f"剩余目标 {row_value(summary, row, 7)}　·　后续日均需完成 {row_value(summary, row, 11)}"
        )

    return (
        f"{metric(3, '万美元', '血量')}\n\n"
        f"{metric(5, '万', '360 新增')}\n\n"
        "**数据状态**\n"
        f"血量：{display_status(revenue_status)}\n"
        f"360新增：{display_status(users_status)}"
        f"{fallback_note}\n\n[查看日进度追踪]({SHEET_URL})"
    )


def send_report(text: str) -> int:
    body = json.dumps(
        {
            "msgtype": "card",
            "card": {
                "header": {
                    "title": {"tag": "text", "content": {"type": "plainText", "text": "日血量进度播报"}},
                    "subtitle": {"tag": "text", "content": {"type": "plainText", "text": datetime.now(BJ_TZ).strftime("%Y-%m-%d")}},
                },
                "elements": [
                    {
                        "tag": "text",
                        # WPS card elements require content.type, not content.tag.
                        "content": {"type": "markdown", "text": text},
                    }
                ],
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    key, secret = os.environ.get("WPS_WEBHOOK_KEY"), os.environ.get("WPS_WEBHOOK_SECRET")
    if bool(key) != bool(secret):
        raise RuntimeError("WPS_WEBHOOK_KEY and WPS_WEBHOOK_SECRET must be set together.")
    if key and secret:
        content_md5 = hashlib.md5(body).hexdigest()
        date = format_datetime(datetime.now(timezone.utc), usegmt=True)
        signature = hashlib.sha1(f"{secret}{content_md5}application/json{date}".encode("utf-8")).hexdigest()
        headers.update({"Content-Md5": content_md5, "DATE": date, "Authorization": f"{key}:{signature}"})
    response = requests.post(required("WPS_WEBHOOK_URL"), data=body, headers=headers, timeout=30)
    response.raise_for_status()
    return response.status_code

def main() -> None:
    summary, revenue_rows, users_rows = request_values()
    text = card_text(summary, revenue_rows, users_rows)
    status = send_report(text)
    # Keep logs useful while never exposing secrets or webhook addresses.
    print(f"WPS daily-progress card sent successfully (HTTP {status}).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Daily progress job failed: {exc}", file=sys.stderr)
        raise

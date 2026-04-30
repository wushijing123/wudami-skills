#!/usr/bin/env python3
"""Incrementally sync normalized ZSXQ topics into an existing Feishu Base table."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from zsxq_fetcher import (
    CHINA_TZ,
    DEFAULT_CATEGORY_KEYWORDS,
    ConfigError,
    classify_text,
    clean_text,
    first_title,
    format_datetime,
    is_placeholder,
    load_config,
    summarize_text,
)


FIELD_SCHEMAS: list[dict[str, Any]] = [
    {"type": "text", "name": "topic_id", "style": {"type": "plain"}},
    {"type": "text", "name": "标题", "style": {"type": "plain"}},
    {"type": "text", "name": "正文", "style": {"type": "plain"}},
    {"type": "text", "name": "摘要", "style": {"type": "plain"}},
    {"type": "datetime", "name": "发布时间", "style": {"format": "yyyy-MM-dd HH:mm"}},
    {"type": "text", "name": "链接", "style": {"type": "url"}},
    {
        "type": "select",
        "name": "分类",
        "multiple": False,
        "options": [
            {"name": "干货教程", "hue": "Blue", "lightness": "Lighter"},
            {"name": "案例分享", "hue": "Green", "lightness": "Lighter"},
            {"name": "工具推荐", "hue": "Purple", "lightness": "Lighter"},
            {"name": "课程更新", "hue": "Orange", "lightness": "Lighter"},
            {"name": "互动问答", "hue": "Wathet", "lightness": "Lighter"},
            {"name": "其他", "hue": "Gray", "lightness": "Lighter"},
        ],
    },
    {"type": "number", "name": "图片数", "style": {"type": "plain", "precision": 0, "percentage": False, "thousands_separator": False}},
    {"type": "number", "name": "字数", "style": {"type": "plain", "precision": 0, "percentage": False, "thousands_separator": False}},
    {"type": "datetime", "name": "同步时间", "style": {"format": "yyyy-MM-dd HH:mm"}},
]

REQUIRED_FIELD_NAMES = [schema["name"] for schema in FIELD_SCHEMAS]


class LarkError(RuntimeError):
    """Raised when lark-cli fails or returns an unexpected payload."""


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def extract_json(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "{[":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[index:])
            return payload
        except json.JSONDecodeError:
            continue
    raise LarkError(f"lark-cli did not return JSON: {stripped[:200]}")


def get_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "records", "fields", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = get_items(value)
            if nested:
                return nested
    return []


def get_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), list) and isinstance(data.get("record_id_list"), list):
        fields = data.get("fields") or []
        records: list[dict[str, Any]] = []
        for record_id, row in zip(data.get("record_id_list") or [], data.get("data") or []):
            if not isinstance(row, list):
                continue
            record_fields = {name: row[index] if index < len(row) else None for index, name in enumerate(fields)}
            records.append({"record_id": record_id, "fields": record_fields})
        return records
    return get_items(payload)


def field_name(field: dict[str, Any]) -> str:
    value = field.get("name") or field.get("field_name") or field.get("fieldName")
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def cell_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        return " ".join(filter(None, (cell_to_text(item) for item in value))).strip()
    if isinstance(value, dict):
        for key in ("text", "value", "name", "link", "url"):
            if key in value:
                return cell_to_text(value.get(key))
        return " ".join(filter(None, (cell_to_text(item) for item in value.values()))).strip()
    return str(value).strip()


def normalize_input_item(
    item: dict[str, Any],
    *,
    summary_length: int,
    category_keywords: dict[str, list[str]],
    link_template: str,
) -> dict[str, Any] | None:
    topic_id = item.get("topic_id") or item.get("id") or item.get("主题ID")
    if is_placeholder(topic_id):
        return None
    topic_id = str(topic_id).strip()
    text = clean_text(item.get("text") or item.get("正文") or item.get("content") or item.get("完整内容") or "")
    title = clean_text(item.get("title") or item.get("标题") or first_title(text))
    summary = clean_text(item.get("summary") or item.get("摘要") or summarize_text(text, summary_length))
    created_at = format_datetime(item.get("created_at") or item.get("create_time") or item.get("发布时间") or item.get("time"))
    url = clean_text(item.get("url") or item.get("link") or item.get("链接") or link_template.format(topic_id=topic_id))
    category = clean_text(item.get("category") or item.get("分类") or classify_text(text, category_keywords))

    try:
        image_count = int(item.get("image_count") if item.get("image_count") is not None else item.get("图片数") or 0)
    except (TypeError, ValueError):
        image_count = 0

    try:
        word_count = int(item.get("word_count") if item.get("word_count") is not None else item.get("字数") or len(text))
    except (TypeError, ValueError):
        word_count = len(text)

    return {
        "topic_id": topic_id,
        "标题": title[:30] if title else first_title(text),
        "正文": text,
        "摘要": summary[:summary_length] if summary_length > 0 else summary,
        "发布时间": created_at,
        "链接": url,
        "分类": category or "其他",
        "图片数": image_count,
        "字数": word_count,
        "同步时间": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }


def load_topics(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "topics", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError(f"Unsupported input JSON shape: {path}")


class LarkClient:
    def __init__(self, *, base_token: str, table_id: str, lark_bin: str, dry_run: bool = False) -> None:
        self.base_token = base_token
        self.table_id = table_id
        self.lark_bin = lark_bin
        self.dry_run = dry_run
        self.planned: list[list[str]] = []

    def run(self, args: list[str]) -> Any:
        command = [self.lark_bin, "base", *args]
        if self.dry_run and any(action in args for action in ("+field-create", "+record-upsert")):
            self.planned.append(command)
            return {"dry_run": True}

        try:
            process = subprocess.run(command, check=False, text=True, capture_output=True)
        except FileNotFoundError as exc:
            raise LarkError(f"Cannot find lark-cli executable: {self.lark_bin}") from exc
        if process.returncode != 0:
            stderr = process.stderr.strip()
            stdout = process.stdout.strip()
            message = stderr or stdout or f"lark-cli exited with {process.returncode}"
            raise LarkError(message)
        return extract_json(process.stdout)

    def list_fields(self) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self.run(
                [
                    "+field-list",
                    "--base-token",
                    self.base_token,
                    "--table-id",
                    self.table_id,
                    "--offset",
                    str(offset),
                    "--limit",
                    "200",
                ]
            )
            page_items = get_items(payload)
            fields.extend(page_items)
            total = payload.get("total") if isinstance(payload, dict) else None
            if len(page_items) < 200 or (isinstance(total, int) and len(fields) >= total):
                break
            offset += 200
        return fields

    def create_field(self, schema: dict[str, Any]) -> None:
        self.run(
            [
                "+field-create",
                "--base-token",
                self.base_token,
                "--table-id",
                self.table_id,
                "--json",
                json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
            ]
        )

    def list_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self.run(
                [
                    "+record-list",
                    "--base-token",
                    self.base_token,
                    "--table-id",
                    self.table_id,
                    "--offset",
                    str(offset),
                    "--limit",
                    "200",
                ]
            )
            page_items = get_records(payload)
            records.extend(page_items)
            total = payload.get("total") if isinstance(payload, dict) else None
            if len(page_items) < 200 or (isinstance(total, int) and len(records) >= total):
                break
            offset += 200
        return records

    def upsert_record(self, payload: dict[str, Any], record_id: str | None = None) -> None:
        args = [
            "+record-upsert",
            "--base-token",
            self.base_token,
            "--table-id",
            self.table_id,
            "--json",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        ]
        if record_id:
            args.extend(["--record-id", record_id])
        self.run(args)


def ensure_fields(client: LarkClient, *, create_missing: bool) -> list[str]:
    existing = {field_name(field) for field in client.list_fields()}
    missing = [schema for schema in FIELD_SCHEMAS if schema["name"] not in existing]
    if missing and not create_missing:
        missing_names = ", ".join(schema["name"] for schema in missing)
        raise LarkError(f"Missing required fields: {missing_names}")
    for schema in missing:
        eprint(f"Creating missing field: {schema['name']}")
        client.create_field(schema)
        time.sleep(0.2)
    return [schema["name"] for schema in missing]


def existing_topic_records(records: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for record in records:
        record_id = str(record.get("record_id") or record.get("id") or "")
        fields = record.get("fields") if isinstance(record.get("fields"), dict) else record
        topic_id = cell_to_text(fields.get("topic_id") if isinstance(fields, dict) else "")
        if topic_id:
            mapping[topic_id] = record_id
    return mapping


def build_record_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = {key: item.get(key) for key in REQUIRED_FIELD_NAMES if key in item}
    return {key: value for key, value in payload.items() if value not in (None, "")}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync normalized ZSXQ topics into Feishu Base.")
    parser.add_argument("--config", help="Config JSON path.")
    parser.add_argument("--input", "-i", required=True, help="Input JSON from zsxq_fetcher.py.")
    parser.add_argument("--base-token", help="Feishu Base token. Overrides config.")
    parser.add_argument("--table-id", help="Feishu table ID/name. Overrides config.")
    parser.add_argument("--lark-bin", default="lark-cli", help="lark-cli executable path.")
    parser.add_argument("--overwrite", action="store_true", help="Update existing records with matching topic_id.")
    parser.add_argument("--no-create-fields", action="store_true", help="Fail instead of auto-creating missing standard fields.")
    parser.add_argument("--dry-run", action="store_true", help="Plan field creation and record writes without mutating Base.")
    parser.add_argument("--limit", type=int, default=0, help="Limit input topic count, mainly for tests.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        config, config_path = load_config(args.config, create_if_missing=True)
    except ConfigError as exc:
        eprint(str(exc))
        return 2

    feishu_config = config.get("feishu", {}) if isinstance(config.get("feishu"), dict) else {}
    zsxq_config = config.get("zsxq", {}) if isinstance(config.get("zsxq"), dict) else {}
    sync_config = config.get("sync", {}) if isinstance(config.get("sync"), dict) else {}
    base_token = args.base_token or feishu_config.get("base_token")
    table_id = args.table_id or feishu_config.get("table_id")

    if is_placeholder(base_token):
        eprint("Missing feishu.base_token. Fill the config or pass --base-token.")
        return 2
    if is_placeholder(table_id):
        eprint("Missing feishu.table_id. Fill the config or pass --table-id.")
        return 2
    if shutil.which(args.lark_bin) is None:
        eprint(f"Cannot find lark-cli executable: {args.lark_bin}")
        return 2

    raw_topics = load_topics(args.input)
    if args.limit > 0:
        raw_topics = raw_topics[: args.limit]

    summary_length = int(sync_config.get("summary_length") or 100)
    category_keywords = sync_config.get("category_keywords") or DEFAULT_CATEGORY_KEYWORDS
    link_template = zsxq_config.get("link_template") or "https://wx.zsxq.com/mweb/views/topicdetail/topicdetail.html?topic_id={topic_id}"
    topics = [
        normalized
        for raw in raw_topics
        if (
            normalized := normalize_input_item(
                raw,
                summary_length=summary_length,
                category_keywords=category_keywords,
                link_template=link_template,
            )
        )
    ]

    client = LarkClient(base_token=str(base_token), table_id=str(table_id), lark_bin=args.lark_bin, dry_run=args.dry_run)

    try:
        created_fields = ensure_fields(client, create_missing=not args.no_create_fields)
        existing_records = existing_topic_records(client.list_records())
        created = 0
        updated = 0
        skipped = 0

        for item in topics:
            topic_id = item["topic_id"]
            record_payload = build_record_payload(item)
            existing_record_id = existing_records.get(topic_id)
            if existing_record_id and not args.overwrite:
                skipped += 1
                continue
            if existing_record_id and args.overwrite:
                client.upsert_record(record_payload, record_id=existing_record_id)
                updated += 1
            else:
                client.upsert_record(record_payload)
                created += 1
            time.sleep(0.2)
    except LarkError as exc:
        eprint(str(exc))
        return 1

    report = {
        "success": True,
        "config_path": str(config_path),
        "input_count": len(raw_topics),
        "normalized_count": len(topics),
        "created_fields": created_fields,
        "created_records": created,
        "updated_records": updated,
        "skipped_existing": skipped,
        "dry_run": args.dry_run,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

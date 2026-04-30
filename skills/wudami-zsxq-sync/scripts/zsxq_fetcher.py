#!/usr/bin/env python3
"""Fetch ZSXQ owner topics and write a normalized JSON payload."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CHINA_TZ = timezone(timedelta(hours=8))
CONFIG_ENV = "ZSXQ_SYNC_CONFIG"
COOKIE_ENV = "ZSXQ_COOKIE"
GROUP_ENV = "ZSXQ_GROUP_ID"
DEFAULT_CONFIG_PATH = Path.home() / ".codex" / "zsxq-sync" / "config.json"
LEGACY_CONFIG_PATH = Path.home() / ".claude" / "zsxq-sync" / "config.json"

DEFAULT_CATEGORY_KEYWORDS = {
    "干货教程": ["教程", "方法", "步骤", "实操", "拆解", "指南", "怎么做"],
    "案例分享": ["案例", "学员", "复盘", "成果", "经验", "故事"],
    "工具推荐": ["工具", "插件", "软件", "应用", "AI工具", "提示词"],
    "课程更新": ["课程", "直播", "作业", "训练营", "更新", "通知"],
    "互动问答": ["问答", "提问", "回复", "答疑", "问题", "评论"],
}

CONFIG_TEMPLATE = {
    "zsxq": {
        "group_id": "YOUR_GROUP_ID",
        "cookie": "YOUR_COOKIE_STRING",
        "scope": "all",
        "owner_name": "吴大咪",
        "api_base": "https://api.zsxq.com",
        "link_template": "https://wx.zsxq.com/mweb/views/topicdetail/topicdetail.html?topic_id={topic_id}",
    },
    "feishu": {
        "base_token": "YOUR_BASE_TOKEN",
        "table_id": "YOUR_TABLE_ID",
    },
    "sync": {
        "default_days": 1,
        "summary_mode": "truncate",
        "summary_length": 100,
        "auto_classify": True,
        "category_keywords": DEFAULT_CATEGORY_KEYWORDS,
    },
}


class ConfigError(RuntimeError):
    """Raised when local configuration is missing or incomplete."""


class FetchError(RuntimeError):
    """Raised when ZSXQ fetching fails."""


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def redact(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text.startswith("YOUR_")


def resolve_config_path(cli_path: str | None = None) -> Path:
    if cli_path:
        return Path(cli_path).expanduser()
    env_path = os.environ.get(CONFIG_ENV)
    if env_path:
        return Path(env_path).expanduser()
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    if LEGACY_CONFIG_PATH.exists():
        return LEGACY_CONFIG_PATH
    return DEFAULT_CONFIG_PATH


def write_config_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(CONFIG_TEMPLATE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_config(cli_path: str | None = None, create_if_missing: bool = True) -> tuple[dict[str, Any], Path]:
    path = resolve_config_path(cli_path)
    if not path.exists():
        if create_if_missing:
            write_config_template(path)
        raise ConfigError(f"Config file not found. A template was created at: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8")), path
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON config at {path}: {exc}") from exc


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(
        r'<e\b[^>]*\btitle="([^"]+)"[^>]*/?>',
        lambda match: urllib.parse.unquote(match.group(1)),
        text,
        flags=re.I,
    )
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\u200b", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_datetime(value: Any, *, end_of_day: bool = False) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=CHINA_TZ)

    text = str(value).strip()
    if not text:
        return None

    date_only = re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) or re.fullmatch(r"\d{4}/\d{2}/\d{2}", text)
    if date_only:
        text = text.replace("/", "-") + (" 23:59:59" if end_of_day else " 00:00:00")

    text = text.replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    text = text.replace("/", "-")

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(text[:26], fmt)
            return dt.replace(tzinfo=CHINA_TZ)
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CHINA_TZ)
    return dt.astimezone(CHINA_TZ)


def format_datetime(value: Any) -> str:
    dt = parse_datetime(value)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def trim_summary(text: str, length: int = 100) -> str:
    text = re.sub(r"\s+", " ", clean_text(text)).strip(" ，,。.")
    if len(text) <= length:
        return text
    return text[: max(0, length - 1)].rstrip(" ，,。.") + "。"


def content_subject(title: str, text: str) -> str:
    source = clean_text(title) or clean_text(text)
    source = re.sub(r"[！!。].*$", "", source).strip()
    source = re.sub(r"\s+", " ", source)
    return source[:36].strip(" ，,。.")


def interpretive_summary(text: str, title: str = "", category: str = "", length: int = 100) -> str:
    cleaned = re.sub(r"\s+", " ", clean_text(text)).strip()
    subject = content_subject(title, cleaned)
    if not cleaned and subject:
        return trim_summary(f"记录一条关于{subject}的星球更新。", length)
    if not subject:
        return ""

    # Common ZSXQ post patterns. These produce a short explanation instead of copying the body.
    if "已经可以" in cleaned or "可以完整" in cleaned:
        audience = ""
        match = re.search(r"(你们的[^，。！!~]+也可以[^，。！!~]+)", cleaned)
        if match:
            audience = "，" + match.group(1).replace("啦", "")
        return trim_summary(f"介绍{subject}的能力{audience}，方便判断是否适合拿来做业务自动化。", length)

    if "课程" in cleaned or "课程链接" in cleaned:
        return trim_summary(f"更新一份课程/学习资料，主题是{subject}，适合后续补课或查找相关教程。", length)

    if "提醒" in cleaned or "处罚" in cleaned or "封禁" in cleaned or "合规" in cleaned:
        return trim_summary(f"提醒关注{subject}相关风险，重点是平台规则、合规要求和处理建议。", length)

    if "小伙伴问" in cleaned or "解答" in cleaned or "怎么办" in cleaned or "区别是什么" in cleaned:
        return trim_summary(f"解答关于{subject}的问题，包含判断逻辑和可执行建议。", length)

    if "工具" in cleaned or "指令" in cleaned or "提示词" in cleaned or "模型" in cleaned:
        return trim_summary(f"分享{subject}相关工具或资源，便于直接收藏、测试或复用到内容生产。", length)

    if category:
        prefix = {
            "干货教程": "说明一个实操方法",
            "案例分享": "分享一个案例",
            "工具推荐": "推荐一类工具/资源",
            "课程更新": "更新课程/资料",
            "互动问答": "解答一个常见问题",
        }.get(category, "记录一条星球更新")
        return trim_summary(f"{prefix}：{subject}，方便快速判断内容主题和用途。", length)

    return trim_summary(f"记录一条关于{subject}的星球更新，方便快速判断内容主题和用途。", length)


def summarize_text(text: str, length: int = 100, title: str = "", category: str = "") -> str:
    return interpretive_summary(text, title=title, category=category, length=length)


def classify_text(text: str, category_keywords: dict[str, list[str]] | None = None) -> str:
    keywords = category_keywords or DEFAULT_CATEGORY_KEYWORDS
    normalized = clean_text(text).lower()
    best_category = "其他"
    best_score = 0
    for category, words in keywords.items():
        score = sum(normalized.count(str(word).lower()) for word in words)
        if score > best_score:
            best_category = category
            best_score = score
    return best_category


def first_title(text: str, max_len: int = 30) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    first_line = next((line.strip() for line in cleaned.splitlines() if line.strip()), cleaned)
    return first_line[:max_len]


def collect_text_parts(topic: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    def append_unique(raw: Any) -> None:
        text = clean_text(raw)
        if not text:
            return
        for existing in list(parts):
            if text == existing or text in existing:
                return
            if existing in text:
                parts.remove(existing)
        parts.append(text)

    for container_key in ("talk", "question", "answer", "solution", "task", "article"):
        container = topic.get(container_key)
        if isinstance(container, dict):
            for key in ("title", "text", "content", "description"):
                append_unique(container.get(key))
        elif isinstance(container, str):
            append_unique(container)

    if not parts:
        for key in ("title", "text", "content", "description"):
            append_unique(topic.get(key))
    return parts


def collect_images(value: Any) -> list[Any]:
    images: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "images" and isinstance(child, list):
                images.extend(child)
            elif isinstance(child, (dict, list)):
                images.extend(collect_images(child))
    elif isinstance(value, list):
        for child in value:
            images.extend(collect_images(child))
    return images


def collect_tags(topic: dict[str, Any]) -> list[str]:
    raw_tags: list[Any] = []
    for source in (topic.get("tags"), topic.get("talk", {}).get("tags") if isinstance(topic.get("talk"), dict) else None):
        if isinstance(source, list):
            raw_tags.extend(source)
    tags: list[str] = []
    for item in raw_tags:
        if isinstance(item, dict):
            tag = item.get("name") or item.get("title") or item.get("text")
        else:
            tag = item
        tag_text = clean_text(tag)
        if tag_text and tag_text not in tags:
            tags.append(tag_text)
    return tags


def normalize_topic(
    topic: dict[str, Any],
    *,
    link_template: str,
    summary_length: int,
    category_keywords: dict[str, list[str]] | None,
) -> dict[str, Any] | None:
    topic_id = topic.get("topic_id") or topic.get("topic_id_str") or topic.get("id")
    if not topic_id:
        return None
    topic_id = str(topic_id)
    topic_uid = str(topic.get("topic_uid") or topic.get("topic_uid_str") or topic_id)

    text = clean_text("\n\n".join(collect_text_parts(topic)))
    if not text:
        text = clean_text(json.dumps(topic, ensure_ascii=False))

    created_at = topic.get("create_time") or topic.get("created_at") or topic.get("time")
    image_count = len(collect_images(topic))
    title = first_title(topic.get("title") or text)
    url = link_template.format(topic_id=topic_id)

    category = classify_text(text, category_keywords)
    return {
        "topic_id": topic_id,
        "topic_uid": topic_uid,
        "title": title,
        "text": text,
        "summary": summarize_text(text, summary_length, title=title, category=category),
        "created_at": format_datetime(created_at),
        "url": url,
        "category": category,
        "image_count": image_count,
        "word_count": len(text),
        "type": topic.get("type") or "",
        "tags": collect_tags(topic),
    }


def topic_owner_name(topic: dict[str, Any]) -> str:
    for container_key in ("talk", "question", "answer", "solution", "task", "article"):
        container = topic.get(container_key)
        if not isinstance(container, dict):
            continue
        owner = container.get("owner") or container.get("user") or container.get("author")
        if isinstance(owner, dict):
            name = clean_text(owner.get("name") or owner.get("nickname") or owner.get("display_name"))
            if name:
                return name
    owner = topic.get("owner") or topic.get("user") or topic.get("author")
    if isinstance(owner, dict):
        return clean_text(owner.get("name") or owner.get("nickname") or owner.get("display_name"))
    return ""


def response_topics(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("succeeded") is False:
        message = payload.get("error") or payload.get("message") or payload.get("code") or "ZSXQ API returned failure"
        raise FetchError(str(message))

    candidates = [
        payload.get("topics"),
        payload.get("resp_data", {}).get("topics") if isinstance(payload.get("resp_data"), dict) else None,
        payload.get("data", {}).get("topics") if isinstance(payload.get("data"), dict) else None,
        payload.get("resp_data", {}).get("list") if isinstance(payload.get("resp_data"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def http_get_json(url: str, headers: dict[str, str], timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise FetchError(f"ZSXQ authentication failed with HTTP {exc.code}. Refresh the Cookie or use --mode cdp.") from exc
        raise FetchError(f"ZSXQ API failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"ZSXQ API request failed: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise FetchError(f"ZSXQ API returned non-JSON response: {exc}") from exc


def is_transient_zsxq_error(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("succeeded") is False and payload.get("code") == 1059


def http_get_zsxq_json(url: str, headers: dict[str, str], retries: int = 3) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for _ in range(max(1, retries)):
        payload = http_get_json(url, headers=headers)
        if not is_transient_zsxq_error(payload):
            return payload
    return payload


def fetch_share_url(topic_key: str, headers: dict[str, str], api_base: str) -> str | None:
    url = f"{api_base.rstrip('/')}/v2/topics/{urllib.parse.quote(str(topic_key))}/share_url"
    for _ in range(3):
        try:
            payload = http_get_zsxq_json(url, headers=headers)
        except FetchError:
            return None
        resp_data = payload.get("resp_data") if isinstance(payload, dict) else None
        if isinstance(resp_data, dict):
            share_url = resp_data.get("share_url")
            if isinstance(share_url, str) and share_url.startswith("http"):
                return share_url
        if payload.get("code") != 1059:
            break
    return None


def share_url_candidates(item: dict[str, Any]) -> list[str]:
    """Return ZSXQ share-url keys in the order that works for old and new posts."""
    candidates: list[str] = []
    for key in (item.get("topic_uid"), item.get("topic_id")):
        text = str(key).strip() if key is not None else ""
        if text and text not in candidates:
            candidates.append(text)
    return candidates


def fetch_share_url_for_item(item: dict[str, Any], headers: dict[str, str], api_base: str) -> str | None:
    for topic_key in share_url_candidates(item):
        share_url = fetch_share_url(topic_key, headers, api_base)
        if share_url:
            return share_url
    return None


def fetch_api(
    *,
    group_id: str,
    cookie: str,
    scope: str,
    since: datetime | None,
    until: datetime | None,
    fetch_all: bool,
    count: int,
    max_pages: int,
    api_base: str,
    link_template: str,
    summary_length: int,
    category_keywords: dict[str, list[str]] | None,
    owner_name: str | None = None,
    resolve_share_url: bool = True,
) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
        "Origin": "https://wx.zsxq.com",
        "Referer": f"https://wx.zsxq.com/group/{group_id}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    }

    endpoint = f"{api_base.rstrip('/')}/v2/groups/{urllib.parse.quote(str(group_id))}/topics"
    cursor: str | None = None
    seen_cursors: set[str] = set()
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    for page_index in range(max_pages):
        params = {"scope": scope, "count": str(count)}
        if cursor:
            params["end_time"] = cursor
        url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        payload = http_get_json(url, headers=headers)
        raw_topics = response_topics(payload)
        if not raw_topics:
            break

        last_time_raw = raw_topics[-1].get("create_time") or raw_topics[-1].get("created_at")
        next_cursor = str(last_time_raw) if last_time_raw else None
        last_dt = parse_datetime(last_time_raw)

        for raw_topic in raw_topics:
            if owner_name and topic_owner_name(raw_topic) != owner_name:
                continue
            item = normalize_topic(
                raw_topic,
                link_template=link_template,
                summary_length=summary_length,
                category_keywords=category_keywords,
            )
            if not item or item["topic_id"] in seen_ids:
                continue
            if resolve_share_url:
                item["url"] = fetch_share_url_for_item(item, headers, api_base) or item["url"]
            created_dt = parse_datetime(item.get("created_at"))
            if until and created_dt and created_dt > until:
                continue
            if since and created_dt and created_dt < since:
                continue
            results.append(item)
            seen_ids.add(item["topic_id"])

        if not fetch_all and since and last_dt and last_dt < since:
            break
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        eprint(f"Fetched page {page_index + 1}, total normalized topics: {len(results)}")

    return results


def fetch_cdp(
    *,
    cdp_url: str,
    group_id: str,
    since: datetime | None,
    until: datetime | None,
    fetch_all: bool,
    count: int,
    max_pages: int,
    scope: str,
    api_base: str,
    link_template: str,
    summary_length: int,
    category_keywords: dict[str, list[str]] | None,
    owner_name: str | None = None,
    resolve_share_url: bool = True,
) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise FetchError("CDP mode requires playwright. Install it or use API mode.") from exc

    version_url = cdp_url.rstrip("/") + "/json/version"
    payload = http_get_json(version_url, headers={})
    ws_url = payload.get("webSocketDebuggerUrl")
    if not ws_url:
        raise FetchError("Could not read Chrome DevTools WebSocket URL.")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = next((pg for pg in context.pages if "zsxq.com" in pg.url), None)
        if page is None:
            raise FetchError("No zsxq.com page found in the connected browser.")
        page.wait_for_timeout(500)

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    cursor: str | None = None
    seen_cursors: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = next((pg for pg in context.pages if "zsxq.com" in pg.url), None)
        if page is None:
            raise FetchError("No zsxq.com page found in the connected browser.")
        for page_index in range(max_pages):
            params = {"scope": scope, "count": str(count)}
            if cursor:
                params["end_time"] = cursor
            query = urllib.parse.urlencode(params)
            payload = page.evaluate(
                """async ({apiBase, groupId, query}) => {
                    let payload = null;
                    for (let attempt = 0; attempt < 3; attempt += 1) {
                        const url = `${apiBase.replace(/\\/$/, "")}/v2/groups/${groupId}/topics?${query}`;
                        const res = await fetch(url, {credentials: "include", headers: {accept: "application/json, text/plain, */*"}});
                        payload = await res.json();
                        if (payload?.succeeded !== false || payload?.code !== 1059) {
                            return payload;
                        }
                    }
                    return payload;
                }""",
                {"apiBase": api_base, "groupId": str(group_id), "query": query},
            )
            try:
                raw_topics = response_topics(payload)
            except FetchError:
                if results:
                    eprint("ZSXQ pagination stopped after a later-page API error; keeping fetched topics.")
                    break
                raise
            if not raw_topics:
                break
            last_time_raw = raw_topics[-1].get("create_time") or raw_topics[-1].get("created_at")
            next_cursor = str(last_time_raw) if last_time_raw else None
            last_dt = parse_datetime(last_time_raw)
            for raw_topic in raw_topics:
                if owner_name and topic_owner_name(raw_topic) != owner_name:
                    continue
                item = normalize_topic(
                    raw_topic,
                    link_template=link_template,
                    summary_length=summary_length,
                    category_keywords=category_keywords,
                )
                if not item or item["topic_id"] in seen_ids:
                    continue
                if resolve_share_url:
                    share_payload = page.evaluate(
                        """async ({apiBase, topicKeys}) => {
                            for (const topicKey of topicKeys) {
                                for (let attempt = 0; attempt < 3; attempt += 1) {
                                    const url = `${apiBase.replace(/\\/$/, "")}/v2/topics/${encodeURIComponent(topicKey)}/share_url`;
                                    const res = await fetch(url, {credentials: "include", headers: {accept: "application/json, text/plain, */*"}});
                                    const payload = await res.json();
                                    const shareUrl = payload?.resp_data?.share_url;
                                    if (typeof shareUrl === "string" && shareUrl.startsWith("http")) {
                                        return payload;
                                    }
                                    if (payload?.code !== 1059) {
                                        break;
                                    }
                                }
                            }
                            return null;
                        }""",
                        {"apiBase": api_base, "topicKeys": share_url_candidates(item)},
                    )
                    resp_data = share_payload.get("resp_data") if isinstance(share_payload, dict) else None
                    if isinstance(resp_data, dict) and isinstance(resp_data.get("share_url"), str):
                        item["url"] = resp_data["share_url"]
                created_dt = parse_datetime(item.get("created_at"))
                if until and created_dt and created_dt > until:
                    continue
                if since and created_dt and created_dt < since:
                    continue
                results.append(item)
                seen_ids.add(item["topic_id"])
            if not fetch_all and since and last_dt and last_dt < since:
                break
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            eprint(f"Fetched browser API page {page_index + 1}, total normalized topics: {len(results)}")
    return results


def build_output(source: str, items: list[dict[str, Any]], config_path: Path | None) -> dict[str, Any]:
    return {
        "success": True,
        "source": source,
        "count": len(items),
        "items": items,
        "config_path": str(config_path) if config_path else "",
        "fetched_at": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch ZSXQ owner topics into normalized JSON.")
    parser.add_argument("--config", help="Config JSON path.")
    parser.add_argument("--mode", choices=("api", "cdp"), default="api", help="Fetch mode. Default: api.")
    parser.add_argument("--group-id", help="ZSXQ group ID. Overrides config.")
    parser.add_argument("--cookie", help="ZSXQ request Cookie. Prefer config or ZSXQ_COOKIE env.")
    parser.add_argument("--scope", default=None, help="ZSXQ topic scope. Default from config or by_owner.")
    parser.add_argument("--owner-name", default=None, help="Filter topics by owner name. Default from config.")
    parser.add_argument("--since", help="Start date/time, inclusive. Example: 2026-04-01")
    parser.add_argument("--until", help="End date/time, inclusive. Example: 2026-04-28")
    parser.add_argument("--all", action="store_true", help="Fetch all pages until API pagination ends.")
    parser.add_argument("--count", type=int, default=20, help="API page size.")
    parser.add_argument("--max-pages", type=int, default=200, help="Hard pagination cap.")
    parser.add_argument("--limit", type=int, default=0, help="Limit normalized output count, mainly for tests.")
    parser.add_argument("--no-share-url", action="store_true", help="Do not resolve t.zsxq.com share URLs.")
    parser.add_argument("--cdp-url", default="http://localhost:9222", help="Chrome DevTools URL for --mode cdp.")
    parser.add_argument("--output", "-o", help="Output JSON file. If omitted, writes JSON to stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        config, config_path = load_config(args.config, create_if_missing=True)
    except ConfigError as exc:
        eprint(str(exc))
        return 2

    zsxq_config = config.get("zsxq", {}) if isinstance(config.get("zsxq"), dict) else {}
    sync_config = config.get("sync", {}) if isinstance(config.get("sync"), dict) else {}
    category_keywords = sync_config.get("category_keywords") or DEFAULT_CATEGORY_KEYWORDS
    summary_length = int(sync_config.get("summary_length") or 100)
    link_template = zsxq_config.get("link_template") or CONFIG_TEMPLATE["zsxq"]["link_template"]

    since = parse_datetime(args.since)
    until = parse_datetime(args.until, end_of_day=True)
    if not args.all and since is None:
        default_days = int(sync_config.get("default_days") or 1)
        since = datetime.now(CHINA_TZ) - timedelta(days=default_days)

    try:
        if args.mode == "api":
            group_id = args.group_id or os.environ.get(GROUP_ENV) or zsxq_config.get("group_id")
            cookie = args.cookie or os.environ.get(COOKIE_ENV) or zsxq_config.get("cookie")
            if is_placeholder(group_id):
                raise ConfigError("Missing zsxq.group_id. Fill the local config or pass --group-id.")
            if is_placeholder(cookie):
                raise ConfigError("Missing zsxq.cookie. Fill the local config or set ZSXQ_COOKIE.")
            eprint(f"Using config: {config_path}")
            eprint(f"Fetching ZSXQ group {group_id} with Cookie {redact(str(cookie))}")
            items = fetch_api(
                group_id=str(group_id),
                cookie=str(cookie),
                scope=args.scope or zsxq_config.get("scope") or "all",
                since=since,
                until=until,
                fetch_all=args.all,
                count=args.count,
                max_pages=args.max_pages,
                api_base=zsxq_config.get("api_base") or "https://api.zsxq.com",
                link_template=link_template,
                summary_length=summary_length,
                category_keywords=category_keywords,
                owner_name=args.owner_name or zsxq_config.get("owner_name"),
                resolve_share_url=not args.no_share_url,
            )
            source = "api"
        else:
            group_id = args.group_id or os.environ.get(GROUP_ENV) or zsxq_config.get("group_id")
            if is_placeholder(group_id):
                raise ConfigError("Missing zsxq.group_id. Fill the local config or pass --group-id.")
            eprint(f"Fetching from browser via CDP: {args.cdp_url}")
            items = fetch_cdp(
                cdp_url=args.cdp_url,
                group_id=str(group_id),
                since=since,
                until=until,
                fetch_all=args.all,
                count=args.count,
                max_pages=args.max_pages,
                scope=args.scope or zsxq_config.get("scope") or "all",
                api_base=zsxq_config.get("api_base") or "https://api.zsxq.com",
                link_template=link_template,
                summary_length=summary_length,
                category_keywords=category_keywords,
                owner_name=args.owner_name or zsxq_config.get("owner_name"),
                resolve_share_url=not args.no_share_url,
            )
            source = "browser-api"
    except (ConfigError, FetchError) as exc:
        eprint(str(exc))
        if args.mode == "api":
            eprint("Fallback: open a logged-in ZSXQ page in Chrome and retry with --mode cdp --cdp-url http://localhost:9222.")
        return 2

    if args.limit > 0:
        items = items[: args.limit]

    output = build_output(source, items, config_path)
    output_json = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).expanduser().write_text(output_json + "\n", encoding="utf-8")
        eprint(f"Wrote {len(items)} normalized topics to {args.output}")
    else:
        print(output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

---
name: wudami-zsxq-sync
description: Synchronize ZSXQ/知识星球 owner topics into an existing Lark/Feishu Base table. Use when the user says "同步星球", "知识星球同步", "更新星球内容", "zsxq sync", or asks to fetch/sync star-owner posts from wx.zsxq.com/api.zsxq.com into 飞书多维表格 with incremental de-duplication, summaries, and categories.
---

# Wudami ZSXQ Sync

## Quick Start

Use this skill to sync 知识星球星主内容 into an existing 飞书多维表格. Default to API mode with a browser Cookie and owner-name filtering; use CDP mode to call the same ZSXQ API from an already logged-in browser when direct HTTP mode fails.

1. Ensure `lark-cli` works and the target Base/Table already exists.
2. Put config in `~/.codex/zsxq-sync/config.json`. If it does not exist, the scripts create a template there and exit.
3. Fetch topics:

```bash
python /Users/wushijing/.claude/skills/wudami-zsxq-sync/scripts/zsxq_fetcher.py \
  --since 2026-04-01 \
  --until 2026-04-28 \
  --output /tmp/zsxq_topics.json
```

4. Sync to Base:

```bash
python /Users/wushijing/.claude/skills/wudami-zsxq-sync/scripts/zsxq_sync.py \
  --input /tmp/zsxq_topics.json
```

## User Commands

- `同步星球`: fetch and sync the last configured default window, normally 24 hours, in both API and CDP modes.
- `同步星球 最近7天`: pass `--since` as 7 days ago.
- `同步星球 全部`: pass `--all`.
- `同步星球 2026-04-01 2026-04-15`: pass the two dates as `--since` and `--until`.

When the user provides a Base URL instead of tokens, extract `/base/{base_token}` and `?table={table_id}`. If it is a `/wiki/{token}` URL, resolve the real object token with `lark-cli wiki spaces get_node` before using `lark-cli base +...`.

## Configuration

Config lookup order:

1. `--config`
2. `ZSXQ_SYNC_CONFIG`
3. `~/.codex/zsxq-sync/config.json`
4. `~/.claude/zsxq-sync/config.json`

Required values:

- `zsxq.group_id`
- `zsxq.cookie`
- `zsxq.owner_name` (default `吴大咪`; used to filter star-owner posts when `scope=by_owner` is unavailable)
- `feishu.base_token`
- `feishu.table_id`

Never echo the Cookie in chat or logs. If the Cookie expires, ask the user to log in at `wx.zsxq.com` and copy the full request Cookie from the browser Network panel.

## Data Model

Read `references/bitable-schema.md` before changing fields. The sync script auto-creates missing standard fields in the existing table:

`topic_id`, `标题`, `正文`, `摘要`, `发布时间`, `链接`, `分类`, `图片数`, `字数`, `同步时间`.

De-duplicate by `topic_id`. By default, existing records are not overwritten; use `--overwrite` only when the user explicitly asks to refresh existing rows.

Links must use the ZSXQ share URL endpoint, not `https://wx.zsxq.com/topic/{topic_id}`. Some ZSXQ posts expose both `topic_id` and `topic_uid`, and the share endpoint may only accept `topic_uid`. Resolve each link by trying `/v2/topics/{topic_uid}/share_url` first, then `/v2/topics/{topic_id}/share_url`; retry transient code `1059` up to three attempts per key. If both keys fail for deleted or unavailable posts, fall back to `https://wx.zsxq.com/mweb/views/topicdetail/topicdetail.html?topic_id={topic_id}`.

Summaries should explain what the post is about, not copy the first N characters. Use `summarize_text()` / `interpretive_summary()` so the `摘要` field reads like a quick content identification note.

## CDP Fallback

Use CDP fallback when API mode returns authentication errors, anti-bot errors, or empty data despite visible content in the browser. CDP mode should call `api.zsxq.com` from the logged-in browser context and keep owner filtering; it should not scrape broad DOM containers.

ZSXQ list pagination can intermittently return code `1059`. Treat this as transient and retry up to three attempts before failing the page.

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/zsxq-chrome &
```

Ask the user to open the ZSXQ topic list in that browser, log in, and scroll until the needed content is loaded. Then run:

```bash
python /Users/wushijing/.claude/skills/wudami-zsxq-sync/scripts/zsxq_fetcher.py \
  --mode cdp \
  --cdp-url http://localhost:9222 \
  --output /tmp/zsxq_topics.json
```

## Safety Rules

- Use only `lark-cli base +...` commands for Base operations.
- Before writing, the sync script must call `+field-list` and create missing storage fields only.
- `+field-list` and `+record-list` are serialized; `+record-list` uses `--limit 200`.
- Do not write formula, lookup, system, attachment, created/updated fields through `+record-upsert`.
- Keep API results in `/tmp` unless the user asks for a project artifact.

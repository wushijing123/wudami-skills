# ZSXQ Sync Bitable Schema

Use these fields for the target existing Feishu Base table. The sync script creates missing fields automatically and does not delete or rename existing fields.

| Field | Type | Write value |
| --- | --- | --- |
| `topic_id` | text/plain | ZSXQ topic ID, unique de-duplication key |
| `标题` | text/plain | First line or first 30 Chinese characters |
| `正文` | text/plain | Full normalized content |
| `摘要` | text/plain | Truncated summary, default 100 characters |
| `发布时间` | datetime | `YYYY-MM-DD HH:mm:ss` |
| `链接` | text/url | ZSXQ short share URL from `/v2/topics/{topic_uid}/share_url`, then `/v2/topics/{topic_id}/share_url`; mweb topic detail URL as fallback |
| `分类` | select/single | `干货教程`, `案例分享`, `工具推荐`, `课程更新`, `互动问答`, `其他` |
| `图片数` | number/plain | Number of images detected |
| `字数` | number/plain | Text length after whitespace normalization |
| `同步时间` | datetime | Local sync time |

## Field Creation JSON

Use `lark-cli base +field-create --json` with these shortcut payloads:

```json
{"type":"text","name":"topic_id","style":{"type":"plain"}}
{"type":"text","name":"标题","style":{"type":"plain"}}
{"type":"text","name":"正文","style":{"type":"plain"}}
{"type":"text","name":"摘要","style":{"type":"plain"}}
{"type":"datetime","name":"发布时间","style":{"format":"yyyy-MM-dd HH:mm"}}
{"type":"text","name":"链接","style":{"type":"url"}}
{"type":"select","name":"分类","multiple":false,"options":[{"name":"干货教程","hue":"Blue","lightness":"Lighter"},{"name":"案例分享","hue":"Green","lightness":"Lighter"},{"name":"工具推荐","hue":"Purple","lightness":"Lighter"},{"name":"课程更新","hue":"Orange","lightness":"Lighter"},{"name":"互动问答","hue":"Wathet","lightness":"Lighter"},{"name":"其他","hue":"Gray","lightness":"Lighter"}]}
{"type":"number","name":"图片数","style":{"type":"plain","precision":0,"percentage":false,"thousands_separator":false}}
{"type":"number","name":"字数","style":{"type":"plain","precision":0,"percentage":false,"thousands_separator":false}}
{"type":"datetime","name":"同步时间","style":{"format":"yyyy-MM-dd HH:mm"}}
```

## Record Rules

- Read existing records with `+record-list --limit 200` and paginate by offset.
- Treat the real API `topic_id` as the only unique key. Avoid syncing synthetic `cdp-*` IDs.
- The `摘要` field is an interpretive note about the content, not a raw body excerpt.
- Create missing records with `+record-upsert` without `--record-id`.
- Only use `--record-id` when the user explicitly requests `--overwrite`.

---
name: wudami-xhs-koubo-all
description: >
  小红书博主全量笔记雷达扫描 + 精选爆款批量提纯工具（双阶段点菜式）。当需要查看对标账号、批量抓取笔记时使用。Stage 1 拉清单，Stage 2 精准提取口播/封面/原文。
---

# `wudami-xhs-koubo-all` 小红书博主全量爆款双阶段提纯工作流

这是吴大咪体系中体验最优的**"双段点菜式高维图谱生成工具"**！所有指令必须严格按照**[第一阶段：下沉雷达] -> [确认] -> [第二阶段：定向狙击]**顺序触发。

## ⚠️ 前置要求（强制规则）
**必须配置 `TIKHUB_API_KEY`**，否则脚本会立刻报错退出，不予执行。
同时需要 `SILICONFLOW_API_KEY`（用于视频 ASR 和封面 VLM 识别）。

TikHub 2026-04 文档提示：中国大陆环境默认使用 `https://api.tikhub.dev`，脚本已内置该默认值；如需临时切回其他域名，可设置 `TIKHUB_BASE_URL`。接口超时默认 `45s`，可用 `TIKHUB_TIMEOUT` 覆盖。

**执行方式硬规则**：本 Skill 默认使用本地 Python 脚本直接请求 TikHub HTTP API，不走 MCP。除非主理人明确要求使用 MCP，否则不要调用 `mcp__tikhub*` 工具；MCP 链路通常更慢，且不复用本脚本里的缓存、降级路由和 HTML MP4 兜底。

**HTTP 失败处理规则**：如果本地脚本返回 `401 Unauthorized`，这不是接口字段兼容问题，而是 `TIKHUB_API_KEY` 没有被当前 Agent 环境正确加载、Key 失效、或 HTTP 与 MCP 使用了不同凭证。必须先提示检查/修复 `TIKHUB_API_KEY`，不要静默切到 MCP 大批量补抓。MCP 只能作为主理人明确同意后的临时小批量兜底，并且要说明它会产生额外 TikHub 调用成本，且结果不会自动复用本脚本缓存。

**最终兜底规则**：MCP 不作为自动兜底。视频 URL 缺失、视频下载失败、或抽音失败时，默认走 `wudami-xhs-note-analyzer-cdp` 的浏览器 CDP 单篇补洞链路，端口固定沿用 `9333`，独立 profile 为 `~/.xhs-chrome-profile/`。CDP 只用于第二阶段少量失败视频的补洞，不用于第一阶段全量扫描。

**CDP 兜底配置**：
- `KOUBO_CDP_FALLBACK_MAX`：单次 extract 最多自动 CDP 补洞篇数，默认 `5`；设为 `0` 可关闭。
- `XHS_CDP_PORT`：CDP 端口，默认 `9333`，必须与 `wudami-xhs-note-analyzer-cdp` 保持一致。
- `XHS_NOTE_ANALYZER_CDP_DIR`：CDP Skill 目录，默认 `~/.claude/skills/wudami-xhs-note-analyzer-cdp`。
- 如果浏览器出现登录或 `xsec` 滑块验证，脚本会停在浏览器等待主理人手动完成，验证通过后继续抓取。

## 🎯 核心使用场景
当主理人丢过来说："给我扒一下这个博主"、"抓取这个主页所有的笔记"。

## 🔌 第一阶段（先做这个）：执行侦察扫描 (List 模式)

每次拿到包含博主主页 URL 的请求，无论如何**第一步必须透明运行雷达指令**，不要去预设提取点赞：

```bash
python3 ~/.claude/skills/wudami-xhs-koubo-all/scripts/batch_author_spider.py --url "<博主个人主页URL>" --mode list
```

> **大模型注意**：系统将穿透 TikHub 降级路由（自动切换可用端点），为你无视分页一次性捕获该博主建号以来的全量历史笔记（默认上限999条）。全部落入专属 Cache 缓存。
> 脚本会在跑完预扫描后，**全自动**在主理人的 Obsidian 目录创建独立文件夹 `{YYYY-MM-DD-账号昵称}`，并在里面生成一张包含直达链接的 `全量雷达扫描-博主昵称-xx条.md` 大表。
> **文件夹规范（重要）**：
> - `list` 和 `extract` 模式**必须写入同一个文件夹**（`YYYY-MM-DD-博主昵称`），绝不能分别建新文件夹。
> - 文件夹位置：`02-素材库/脚本库/YYYY-MM-DD-博主昵称/`
> - 博主昵称通过 TikHub `/web/get_user_info` 接口直接获取，自动归一化（括号替换为下划线、去除空格、折叠重复下划线）。
> - 该文件夹是所有产出的唯一归宿：全量雷达扫描、萃取聚合表、videos/、视频索引，全部放在这里。

> **同时导出一份 CSV 到桌面**（`~/Desktop/雷达扫描-{昵称}-{N}条.csv`），主理人无需打开 Obsidian，直接在桌面用 Excel 打开查看、筛选、点菜。
> 点菜支持划定全局门槛（如：赞>1000），或者点名特定的序号（如：提取 1, 5, 8）！

---

## 🔌 第二阶段（等用户点菜后）：执行无损萃取 (Extract 模式)

主理人看完清单并对你下达具体的提取要求后（这可能是：点赞条件过滤，也可能是点名了编号），请再次透明运行对应的狙击指令：

### 情况 A：主人给的是门槛要求（比如：只要 1000 赞以上并且只要图文）
```bash
python3 ~/.claude/skills/wudami-xhs-koubo-all/scripts/batch_author_spider.py --url "<博主主页URL>" --mode extract --min-likes 1000 --note-type normal
```
*(注意 `--note-type` 只能是 `all`, `video`, `normal` 三种之一)*

### 情况 B：主人给你的是直接指定的特定序号组合（比如：我要第1，第4，第7篇）
```bash
python3 ~/.claude/skills/wudami-xhs-koubo-all/scripts/batch_author_spider.py --url "<博主主页URL>" --mode extract --target-ids "1,4,7"
```

## 💰 计费与预算警告（AI 注意）
**⚠️ 极其重要**：TikHub 的每次接口调用大约需要扣除 10-20 积分，由于 TikHub 官方调整，**单次调用成本约为 0.01 美金（约 0.07 元人民币）**。
- **List 模式（第一阶段）**：翻页拉取几百条笔记仅需大约十几毛钱，成本极低。
- **Extract 模式（第二阶段）**：如果直接使用 `--min-likes 10` 大批量提取 100 多篇笔记，将会瞬间消耗 1~2 美金（约 10~15 元人民币）。
- **行动指南**：大模型在接受用户提取指令时，如果预估提取数量过大（超过 20 篇），**必须主动向主理人提示 API 费用成本**。强烈建议主理人先通过 Excel 筛选出核心的 5-10 篇爆款，再使用 `--target-ids` 进行精准点菜提取，避免预算烧空。

## 💡 终段交付与系统依赖
等待第二阶段脚本执行完毕后，内部会经历复杂的全自动化工业管线流水线：
- **视频剥离**：使用 FFmpeg 对全量视频抽取音频流（Wav）。
- **语音听写**：将离线音轨喂给 `SiliconFlow SenseVoiceSmall`，生成带 `🎼` 前缀的精准高保真字幕，放入【口播提取 (ASR)】独立列。
- **视觉提纯**：将所有封面塞给 `Qwen/Qwen2-VL-72B-Instruct` 看图说话，提取主KV与标题排版视觉信息，放入独立列。
- **原文封存**：将帖子原本带的话题和文案放在单独的【标题+正文 (原帖)】列。
- **CDP补洞**：如果 TikHub/HTML/native_voice 仍拿不到可用视频，或视频下载/抽音失败，会调用 `wudami-xhs-note-analyzer-cdp` 在 `9333` 端口用真实浏览器补抓单篇，复用其登录态、`xsec` 等待和多级 ASR 策略。

最后，提醒主理人前往提取专属目录查看：
`02-素材库/脚本库/{YYYY-MM-DD-账号昵称}/{YYYY-MM-DD-账号昵称}.md`
同时在桌面也有一份 CSV：`~/Desktop/萃取结果-{账号昵称}-{N}篇.csv`。

## 🛡️ 系统鲁棒性说明（API 防御机制）
为了应付第三方接口的抽风断联，本工具内核自研了极其强大的强容错机制，无须人工干预即可抵御：
1. **TikHub 请求限流冷启动**：采用循环 `Attempt 3` 重试机制，如果拉取某篇笔记详情时视频 URL 意外丢失，系统会自动 `sleep 2s` 并发起重试，杜绝 "漏取视频口播" 的故障。
2. **SiliconFlow VLM 格式排斥**：由于小红书部分封面 URL 会带 `##c=vx` 畸形碎片导致硅基流动报 `400 Bad Request`，脚本在传入前内置了 URL 净化手术刀（`url.split('#')[0]`），保证 OCR 一次性过。
3. **视频字段新版兼容**：视频 URL 解析同时兼容 `video_info_v2`、`video`、`video_info`、`videoInfo`、`noteCard.video`，并同时识别 `master_url/masterUrl` 与 `backup_urls/backupUrls`。不要依赖 `widgets_context.note_sound_info` 作为主兜底，因为不是所有笔记都有该字段。
4. **CDP 浏览器最终补洞**：自动兜底顺序为 TikHub 详情端点 → 多视频字段 → HTML MP4 → native_voice 音频 → CDP 单篇浏览器补洞 → 标注失败原因。MCP 仅在主理人明确要求时手动小批量试用，不进入默认自动链路。

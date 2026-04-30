---
name: wudami-jiaoben-api
description: >
  短视频逐字稿与脚本详细拆解技能。当用户要求“通过短视频链接提取口播文案”、“抓取视频脚本”、“详细拆解视频脚本”时使用本技能。
  基于 TikHub API 解析任意短视频内容，通过 FFmpeg 和硅基流动 SenseVoice 提取口播音频转化为文本，并使用 DeepSeek/Qwen 系列强 LLM 生成高度详细的段落拆解结构，最终输出到吴大咪系统本地脚本库（02-素材库/脚本库）。
---

# `wudami-jiaoben-api` 视频文案提取与拆解工作流

当用户提供一个视频的分享链接，并希望“提取文案”、“抓取脚本”或“拆解脚本”时，请使用本技能进行一键化全自动处理。
这套流程无缝集成了视频抓取、音频提取、ASR语音转文字文案扒取，以及结构化 LLM 脚本拆解。

**执行方式硬规则**：默认运行本地 Python 脚本直接请求 TikHub HTTP API，不走 MCP。除非主理人明确要求使用 MCP，否则不要调用 `mcp__tikhub*` 工具；MCP 链路通常更慢，且不复用脚本内置的 TikHub 降级链和 HTML MP4 兜底。

**TikHub 配置**：默认使用 `https://api.tikhub.dev`，可用 `TIKHUB_BASE_URL` 覆盖；默认超时 `45s`，可用 `TIKHUB_TIMEOUT` 覆盖。小红书视频解析兼容 `video_info_v2`、`video`、`video_info`、`videoInfo`、`noteCard.video`。

## 使用方法

当你被要求根据链接抓取和拆解视频脚本时，直接**在后台运行**以下指令即可。无需干预。

### 1. 运行核心分析脚本
**单篇提取**：
```bash
python3 ~/.claude/skills/wudami-jiaoben-api/scripts/video_script_analyzer.py --url "<单条视频分享链接>"
```

**批量提取（博主全量）**：当用户要求“批量提取这位博主的全部视频”或“抓取这个主页所有的笔记视频”时使用：
```bash
python3 ~/.claude/skills/wudami-jiaoben-api/scripts/batch_author_spider.py --url "<博主个人主页URL>" --max-count 30
```

### 2. 执行后的响应规范
成功运行上述脚本后，脚本会自动：
- 抓取视频详情。
- 将视频中包含的干货音频发送给大语音模型（ASR）转译得到逐字稿。
- 将逐字稿发给文字大模型提取精美的结构化分析。
- 自动提取故事板视频截帧图片，并将 Markdown 文档写到用户要求的一人公司系统中 `/Users/wushijing/Obsidian仓库/吴大咪一人公司/02-素材库/脚本库` 目录下。

你可以从终端输出中获知保存的文件名。

完成脚本执行后，**向用户展示大模型的成功提取信息，并将脚本库的文档路径或前置片段反馈给用户**：“脚本已被深度拆解并存入：02-素材库/脚本库/...”

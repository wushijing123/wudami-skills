---
name: wudami-xhs-video-diagnostic-api
description: >
  小红书短视频风控与限流深度诊断器。结合 VLM 视觉理解与大语言模型，通过对视频的逐帧视觉解析和 ASR 听写，自动排查广告法违规（极限词、夸大宣传）、完播率杀手（硬广前置）及恶意拉踩等限流因素，并输出完整的 8 段式深度拆解报告。支持本地视频文件和线上链接。
---

# `wudami-xhs-video-diagnostic-api` 短视频风控限流深度诊断器

这是吴大咪体系中专属的 **“商单防踩坑法医”** 与 **“质量内审质检员”**。它将传统的“拆解”升维到了防风控级别，帮助主理人提前排除死局或在笔记发不出去时找出“隐形限流”的真相。

## 🎯 核心使用场景

当主理人甩来一个本地剪好的视频说：“帮我审一下这篇要发的报备笔记”，或者丢来一个没流量的链接说：“查一下这篇为什么被限流了？”。

## 🔌 触发指令

该工具采用极简命令行触发，全自动完成“音轨抽取 → 关键帧截取 → 视觉识别(VLM) → 语音识别(ASR) → LLM深度风控诊断”。

### 场景 A：主理人给出本地视频路径（发布前质检）
```bash
python3 ~/.claude/skills/wudami-xhs-video-diagnostic-api/scripts/diagnostic_engine.py --file "/Users/wushijing/Desktop/xxx.mp4"
```

### 场景 B：主理人给出小红书链接（发布后复盘死因）
```bash
python3 ~/.claude/skills/wudami-xhs-video-diagnostic-api/scripts/diagnostic_engine.py --url "https://www.xiaohongshu.com/explore/xxxxxxxx"
```

## ⚠️ 核心工作管线与 API 依赖

此流水线高度依赖系统底层的 API 通信，**如果缺失将直接阻断运行**：
- `SILICONFLOW_API_KEY` (必填): 用于调用 `SenseVoiceSmall` (语音转文本)、`Qwen2-VL-72B` (视频画面视觉理解) 以及 `Qwen2.5-72B-Instruct` (限流风控判官)。
- `TIKHUB_API_KEY` (链接模式必填): 用于解析和下载无水印短视频原流。

**执行方式硬规则**：链接模式默认运行本地 Python 脚本直接请求 TikHub HTTP API，不走 MCP。除非主理人明确要求使用 MCP，否则不要调用 `mcp__tikhub*` 工具；MCP 链路通常更慢，且不复用脚本内置的 `App V2 → App → Web V3 → Web V4 → HTML MP4` 兜底。

**TikHub 配置**：默认使用 `https://api.tikhub.dev`，可用 `TIKHUB_BASE_URL` 覆盖；默认超时 `45s`，可用 `TIKHUB_TIMEOUT` 覆盖。视频 URL 解析兼容 `video_info_v2`、`video`、`video_info`、`videoInfo`、`noteCard.video`。

如果主理人的终端没有配这些环境变量，请礼貌地要求主理人配置。

## 💡 交付物规范

脚本运行约耗时 30~60 秒，期间会在标准错误输出中静默打印进度（提取音轨、视觉分析等）。
当执行成功后，会自动将报告及抽帧沉淀到你的 Obsidian 专属目录，格式为一个文件夹：
`02-素材库/脚本库/YYYY-MM-DD-限流诊断与拆解_视频名称/` (内含 `.md` 报告文件和 `frames/` 截图文件夹)

**大模型（你）的任务：**
脚本运行结束后，**你必须主动去读取那个生成的 `.md` 报告，并在对话框中将最重要的【🚫 限流风控深度诊断】结果和【避坑建议】呈现给主理人！** 告诉主理人死因是什么，或者恭喜主理人可以安全发布。

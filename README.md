# Wudami Skills

吴大咪自建 Skill 归档仓库。

本仓库收录本机 `/Users/wushijing/.agents/skills/` 下以 `wudami-` 开头的 Skill，保留可复用的 `SKILL.md`、脚本、模板、提示词、references 和 assets。

## 仓库结构

```text
.
├── skills/                  # Skill 本体
│   └── wudami-*/            # 每个 Skill 一个目录
├── docs/
│   └── skills-overview.md   # 每个 Skill 的解读和使用说明
└── README.md
```

## 收录范围

本次收录 13 个顶层 Skill：

- `wudami-content-workflow`
- `wudami-jiaoben-api`
- `wudami-lark-single-video-api`
- `wudami-live-teleprompter`
- `wudami-xhs-account-analyzer`
- `wudami-xhs-analyzer-claw`
- `wudami-xhs-koubo-all`
- `wudami-xhs-note-analyzer-api`
- `wudami-xhs-note-analyzer-cdp`
- `wudami-xhs-scraper-api`
- `wudami-xhs-video-diagnostic-api`
- `wudami-xhs-viral-analyzer`
- `wudami-zsxq-sync`

另有一个嵌套 Skill：

- `wudami-xhs-analyzer-claw/wudami-xhs-account-analyzer_scraper`

## 未收录内容

以下文件属于运行产物或本机缓存，未进入仓库：

- `outputs/`
- `__pycache__/`
- `*.pyc`
- `.DS_Store`
- `state*.json`
- `page.html`
- 小红书抓取结果、音视频文件、抽帧图片、临时报告

## 环境变量

部分 Skill 运行时依赖外部服务，仓库只保留读取环境变量的代码，不保存任何实际密钥。

常见变量：

- `TIKHUB_API_KEY`
- `SILICONFLOW_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `TIKHUB_BASE_URL`
- `TIKHUB_TIMEOUT`

## 解读文档

每个 Skill 的定位、触发场景、主要脚本、依赖和风险点见：

[docs/skills-overview.md](docs/skills-overview.md)


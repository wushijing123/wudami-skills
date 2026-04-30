# Wudami Skills

吴大咪自建 Skill 归档仓库。

本仓库收录本机 `/Users/wushijing/.agents/skills/` 下以 `wudami-` 开头的 Skill。

## 仓库结构

```text
.
├── skills/                  # Skill 本体
│   └── wudami-*/            # 每个 Skill 一个目录
├── docs/
│   └── skills-overview.md   # 每个 Skill 的解读和使用说明
└── README.md
```

## Skill 清单

| Skill | 它是干嘛的 |
|---|---|
| `wudami-content-workflow` | 吴大咪内容生产总流程，从找选题到写脚本、写文章、标题、开头和正文生成。 |
| `wudami-jiaoben-api` | 从短视频链接提取口播文案，并把脚本拆成结构化分析。 |
| `wudami-lark-single-video-api` | 单条小红书视频口播提取器，适合给飞书表格自动补“口播文案”字段。 |
| `wudami-live-teleprompter` | 把 Markdown、DOCX、HTML、大纲转成直播投屏器和口播提词器。 |
| `wudami-xhs-account-analyzer` | 手动资料版小红书账号拆解，根据用户提供的数据、截图、爆款笔记做对标分析。 |
| `wudami-xhs-analyzer-claw` | 浏览器自动抓取版账号拆解，抓全量笔记后生成账号分析报告和可视化。 |
| `wudami-xhs-koubo-all` | 小红书博主全量笔记扫描工具，先拉清单，再批量提取精选爆款内容。 |
| `wudami-xhs-note-analyzer-api` | API 版单篇小红书笔记深度拆解，不依赖浏览器登录。 |
| `wudami-xhs-note-analyzer-cdp` | 浏览器版单篇小红书笔记深度拆解，可抓正文、评论、图片、视频口播。 |
| `wudami-xhs-scraper-api` | 多平台数据抓取工具，覆盖小红书、抖音、B站、微博等平台的数据采集。 |
| `wudami-xhs-video-diagnostic-api` | 短视频风控和限流诊断工具，用来审待发视频或复盘低流量视频。 |
| `wudami-xhs-viral-analyzer` | 小红书低粉爆款扫描器，找低粉高赞选题，并生成可拍的口播脚本框架。 |
| `wudami-zsxq-sync` | 知识星球内容同步工具，把星主内容同步到飞书多维表格。 |
| `wudami-xhs-analyzer-claw/wudami-xhs-account-analyzer_scraper` | 嵌套在账号拆解工具里的 API 抓取说明，用于补充账号数据抓取路线。 |

更详细的逐个说明见：[docs/skills-overview.md](docs/skills-overview.md)

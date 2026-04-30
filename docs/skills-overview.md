# Wudami Skill 解读

本文档用于快速理解每个 `wudami-` Skill 的定位、使用场景、关键依赖和维护注意事项。

## 总览

| Skill | 一句话定位 | 主要场景 |
|---|---|---|
| `wudami-content-workflow` | 内容生产总流程入口 | 找选题、写脚本、写文章、标题和开头优化 |
| `wudami-jiaoben-api` | 视频文案提取和脚本拆解 | 从短视频链接提取口播、生成段落拆解 |
| `wudami-lark-single-video-api` | 单条视频静默 ASR 管道 | 给飞书表格补充单条小红书视频口播 |
| `wudami-live-teleprompter` | 直播投屏器生成器 | 把文档转成演示页和口播稿 |
| `wudami-xhs-account-analyzer` | 人工资料驱动的账号拆解 | 基于用户提供资料分析对标账号 |
| `wudami-xhs-analyzer-claw` | 浏览器自动抓取的账号拆解 | 通过 CDP 抓取账号全量笔记并生成报告 |
| `wudami-xhs-koubo-all` | 博主全量笔记扫描和精选提纯 | 先拉清单，再批量提取爆款口播和封面 |
| `wudami-xhs-note-analyzer-api` | 单篇笔记 API 深拆 | 用 TikHub 付费接口拆解单篇笔记 |
| `wudami-xhs-note-analyzer-cdp` | 单篇笔记浏览器深拆 | 用登录浏览器免费抓取并拆解单篇笔记 |
| `wudami-xhs-scraper-api` | 多平台 TikHub 数据抓取工具 | 抓取小红书、抖音、B 站、微博等平台数据 |
| `wudami-xhs-video-diagnostic-api` | 短视频风控和限流诊断 | 审核待发视频或复盘低流量视频 |
| `wudami-xhs-viral-analyzer` | 小红书低粉爆款扫描和脚本生成 | 搜索关键词，找低粉高赞选题并生成脚本框架 |
| `wudami-zsxq-sync` | 知识星球到飞书 Base 同步 | 同步星主内容、去重、摘要和分类 |

## 逐个解读

### `wudami-content-workflow`

这是吴大咪内容系统的总控型 Skill，覆盖从选题发现到稿子生成、标题、开头、正文和发布前渲染的流程。它不是单点工具，更像是内容生产的调度入口。

- 适合使用：用户说“找选题”“写脚本”“写公众号文章”“帮我创作内容”。
- 核心价值：把选题来源、筛选标准、平台分流和输出格式统一起来。
- 外部依赖：实时选题部分会用 TikHub、小红书热榜、虎嗅、AIbase、机器之心等来源。
- 维护重点：热榜来源和平台链接规则容易过期，要定期检查。

### `wudami-jiaoben-api`

这是短视频文案提取和脚本拆解管道。它通过 TikHub 解析视频，使用 FFmpeg 抽音频，再用语音识别和大模型生成结构化脚本拆解。

- 适合使用：用户给视频链接，要求“提取文案”“抓取脚本”“拆解脚本”。
- 主要脚本：`scripts/video_script_analyzer.py`。
- 外部依赖：`TIKHUB_API_KEY`、`SILICONFLOW_API_KEY`、FFmpeg、Python 依赖包。
- 输出位置：默认写入吴大咪 Obsidian 系统里的脚本库。
- 维护重点：TikHub 字段兼容和视频地址兜底逻辑。

### `wudami-lark-single-video-api`

这是为自动化流水线准备的极简单条视频口播提取器。它的设计目标是“少输出、好对接”，标准输出只保留可写入飞书字段的口播文本。

- 适合使用：给飞书 Base 某条记录补齐小红书视频口播。
- 主要脚本：`scripts/single_video_asr.py`。
- 外部依赖：`TIKHUB_API_KEY`、`SILICONFLOW_API_KEY`。
- 输出特征：控制台输出单行中文文案，带音乐符号前缀。
- 维护重点：不要把调试日志混入 stdout，否则会污染飞书字段。

### `wudami-live-teleprompter`

这是直播演示工具生成器。它把 Markdown、DOCX、HTML 或大纲转成 Web 投屏器，包含主控台和独立投屏窗口。

- 适合使用：用户要直播投屏、演示页、提词器、OBS 捕获窗口。
- 主要资产：`assets/teleprompter/`。
- 主要脚本：`scripts/serve.sh`。
- 输出物：`index.html` 主控台、`cast.html` 投屏页、`data.js` 内容数据。
- 维护重点：前端模板和 `data.js` 数据格式要保持一致。

### `wudami-xhs-account-analyzer`

这是基于用户手动提供资料的账号拆解 Skill。它不强调自动抓取，而是强调信息采集、事实约束和高质量分析。

- 适合使用：用户说“拆解账号”“分析对标账号”“这个博主为什么能爆”。
- 数据要求：账号信息、近期笔记数据、主页截图、爆款笔记、变现情况。
- 核心价值：在资料不完整时能主动追问，不硬编。
- 维护重点：分析结构和采集问题要保持清晰，避免模板化输出。

### `wudami-xhs-analyzer-claw`

这是自动浏览器版的小红书账号深度拆解系统。它通过独立 Chrome 和 CDP 抓取账号全量笔记，再做语义归类、报告生成和 HTML 可视化。

- 适合使用：用户提供小红书账号主页链接，希望自动抓取和分析。
- 主要脚本：`launch_chrome.py`、`xhs_account_scraper.py`、`xhs_account_analyzer.py`、`xhs_visualizer.py`。
- 外部依赖：Playwright、requests、jieba 等。
- 关键约束：使用独立端口 `9333`，不能动用户默认浏览器。
- 维护重点：登录检测、滚动策略、`xsec_token` 链接保真。

#### 嵌套 Skill：`wudami-xhs-account-analyzer_scraper`

这是 `wudami-xhs-analyzer-claw` 内部的补充型 Skill，偏向 TikHub API 账号抓取说明。它可作为 API 抓取路线的参考，但仓库里仍按原目录保留在父 Skill 下。

### `wudami-xhs-koubo-all`

这是博主全量笔记扫描和爆款提纯工具，采用双阶段流程：先拉清单，再由用户选择目标内容做深度提取。

- 适合使用：批量查看对标账号笔记，挑选爆款做口播、封面和原文提纯。
- 主要脚本：`scripts/batch_author_spider.py`、`scripts/video_script_analyzer.py`。
- 外部依赖：`TIKHUB_API_KEY`、`SILICONFLOW_API_KEY`。
- 核心设计：Stage 1 生成清单，Stage 2 定向提取，避免盲目全量高成本分析。
- 维护重点：API 鉴权失败不能静默切换，避免重复调用造成成本浪费。

### `wudami-xhs-note-analyzer-api`

这是 TikHub API 版单篇小红书笔记深度拆解工具。它不依赖浏览器登录，适合稳定自动化，但依赖付费 API。

- 适合使用：用户明确要求 API 拆解、免登录拆解、付费拆解。
- 主要脚本：`scripts/xhs_note_api_scraper.py`、`scripts/export_to_desktop.py`。
- 外部依赖：`TIKHUB_API_KEY`，视频笔记还需要 `SILICONFLOW_API_KEY`。
- 输出物：Markdown、DOCX、HTML 形式的拆解报告。
- 维护重点：运行前必须检查 API Key，避免先清缓存再失败。

### `wudami-xhs-note-analyzer-cdp`

这是 CDP 浏览器版单篇笔记拆解工具。它通过登录态浏览器抓取页面、评论、视频和图片，再输出 8 段式拆解报告。

- 适合使用：用户提供笔记链接，希望免费通过浏览器抓取。
- 主要脚本：`launch_chrome.py`、`xhs_note_scraper.py`、`export_to_desktop.py`。
- 外部依赖：Python3、浏览器、可选 `SILICONFLOW_API_KEY` 或 OpenAI 兼容转录接口。
- 关键约束：必须原样保留用户 URL，特别是查询参数和 `xsec_token`。
- 维护重点：每次新任务前清理历史缓存，防止报告串数据。

### `wudami-xhs-scraper-api`

这是多平台社交媒体数据抓取工具，底层主要通过 TikHub HTTP API 调用，覆盖小红书、抖音、TikTok、Bilibili、微博、公众号、视频号、Twitter/X、YouTube 等平台能力说明。

- 适合使用：用户需要跨平台抓取账号、内容列表、评论、搜索或热榜数据。
- 主要脚本：小红书和抖音账号抓取、分析、可视化脚本。
- 外部依赖：`TIKHUB_API_KEY`、httpx、requests、jieba、playwright。
- 核心价值：提供统一的数据抓取端点和标准代码模板。
- 维护重点：TikHub 端点变化、鉴权错误、平台字段结构变化。

### `wudami-xhs-video-diagnostic-api`

这是短视频发布前质检和发布后限流诊断工具。它结合视频抽帧、视觉理解、ASR 和 LLM 判断广告法风险、硬广问题、拉踩表达和完播率杀手。

- 适合使用：用户说“帮我审一下视频”“为什么这条被限流了”“发前检查”。
- 主要脚本：`scripts/diagnostic_engine.py`。
- 外部依赖：`SILICONFLOW_API_KEY`，链接模式还需要 `TIKHUB_API_KEY`。
- 输出物：Obsidian 脚本库中的诊断报告和抽帧文件夹。
- 维护重点：诊断完成后要读取报告，把最重要的限流原因和避坑建议反馈给用户。

### `wudami-xhs-viral-analyzer`

这是小红书低粉爆款扫描和短视频脚本生成 Skill。它强调先用浏览器抓搜索结果，再筛选低粉高赞内容，最后结合吴大咪短视频方法论生成可拍脚本。

- 适合使用：用户说“扫爆款”“找低粉爆款”“扫描赛道”“分析小红书关键词”。
- 主要脚本：`launch_chrome.py`、`xhs_scraper.py`、`xhs_analyzer.py`、`single_note_extractor.py`。
- 关键流程：AI 只启动浏览器，用户手动搜索并选择“最新”，确认后 AI 接管抓取。
- 核心价值：避免小红书前端 UI 不稳定导致自动搜索失败。
- 维护重点：链接保真、低粉筛选阈值、报告写入 Obsidian 的路径规则。

### `wudami-zsxq-sync`

这是知识星球到飞书多维表格的同步 Skill。它负责抓取星主内容、生成摘要和分类，并按 `topic_id` 去重同步到已有飞书 Base。

- 适合使用：用户说“同步星球”“知识星球同步”“更新星球内容”。
- 主要脚本：`scripts/zsxq_fetcher.py`、`scripts/zsxq_sync.py`。
- 配置位置：`~/.codex/zsxq-sync/config.json` 或 `~/.claude/zsxq-sync/config.json`。
- 外部依赖：知识星球 Cookie、飞书 Base token、table id、`lark-cli`。
- 维护重点：不要在聊天或日志里暴露 Cookie；链接生成要优先使用 share URL。

## 维护建议

1. 新增吴大咪自建 Skill 时继续使用 `wudami-` 前缀。
2. 不要提交运行产物、抓取数据、音视频文件、浏览器状态和真实配置。
3. 涉及 TikHub 的脚本优先保留 HTTP API 路线，只有用户明确要求时再走 MCP。
4. 对外发布前再次运行敏感信息检查，确认没有实际 Cookie、Token、Key。


---
name: wudami-xhs-scraper-api
description: 多平台社交媒体数据抓取工具，基于 TikHub API。支持小红书、抖音、TikTok、Bilibili、微博、YouTube、微信公众号、视频号、Twitter/X。触发词：「小红书」「抖音」「TikTok」「B站」「bilibili」「微博」「YouTube」「公众号」「视频号」「Twitter」「X平台」「抓取数据」「获取用户」「搜索」「评论」「笔记」「视频」。只要用户提到这些平台 + 数据需求，立即触发此 skill。
version: 1.1.0
metadata:
  openclaw:
    requires:
      env:
        - TIKHUB_API_KEY
      bins:
        - python3
    primaryEnv: TIKHUB_API_KEY
    emoji: 🔍
    homepage: https://github.com/wushijing123/xhs-scraper-skill
    setup:
      command: pip3 install httpx
---

# 多平台数据抓取 Skill（TikHub API）

## 概述

通过 TikHub API 直接 HTTP 调用抓取多平台数据。API key 存储在环境变量 `TIKHUB_API_KEY` 中，**无需用户提供**。

> **重要**：不要使用 `tikhub` Python SDK，它的端点已过时。直接用 `httpx` 调用 API。
> **执行方式硬规则**：默认运行本地 Python 脚本或 `httpx` 代码直接请求 TikHub HTTP API，不走 MCP。除非主理人明确要求使用 MCP，否则不要调用 `mcp__tikhub*` 工具。

## 支持平台一览

| 平台 | 用户信息 | 内容列表 | 内容详情 | 评论 | 搜索 | 热搜 |
|------|---------|---------|---------|------|------|------|
| 小红书 | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 抖音 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| TikTok | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Bilibili | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 微博 | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| 微信公众号 | — | ✅ | ✅ | ✅ | — | — |
| 微信视频号 | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| Twitter / X | ✅ | ✅ | — | — | ✅ | — |
| YouTube | — | — | — | — | ✅ | — |

## 运行前置条件与系统依赖
在 OpenClaw 或任何自动化 Agent 环境中接管本 Skill 时，必须确保以下环境配置：
1. **环境变量 API Key **：必须在系统中配置 `TIKHUB_API_KEY`，否则一切 API 请求将超时或拒绝访问。（大模型在执行前应该检查自身环境是否载入了此变量）
2. **包依赖要求**：底层分析和清洗模块强依赖于 Python 库。请确保执行机已经安装：
   ```bash
   pip3 install httpx requests jieba playwright
   ```
   *（注：jieba 附带了自动尝试安装逻辑，但最好在 Agent 初始化时统一挂载依赖。）*

## 标准代码模板

```python
import asyncio, os, httpx

BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
TIKHUB_TIMEOUT = float(os.environ.get("TIKHUB_TIMEOUT", "45"))
HEADERS = {"Authorization": f"Bearer {os.environ.get('TIKHUB_API_KEY')}"}

async def api_get(endpoint: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=TIKHUB_TIMEOUT) as client:
        r = await client.get(f"{BASE_URL}{endpoint}", params=params, headers=HEADERS)
        r.raise_for_status()
        return r.json()
```

---

## 平台一：小红书（Xiaohongshu）

### 端点列表

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 搜索用户 | `GET /api/v1/xiaohongshu/web/search_users` | `keyword`, `page` |
| 获取用户信息（Web） | `GET /api/v1/xiaohongshu/web/get_user_info` | `user_id` |
| 获取用户信息（App） | `GET /api/v1/xiaohongshu/app/get_user_info` | `user_id` |
| 获取用户笔记 | App V2 → App → Web V3 → Web V2 降级链 | `user_id`, `cursor` |
| 获取笔记详情 | App V2 → App → Web V3 → Web V4 降级链 | `note_id` 或 `share_text` |
| 获取笔记评论 | `GET /api/v1/xiaohongshu/app/get_note_comments` | `note_id` |
| 按话题获取笔记 | `GET /api/v1/xiaohongshu/app/get_notes_by_topic` | `topic_id` |
| 首页推荐 | `GET /api/v1/xiaohongshu/web/get_home_recommend` | 无 |

### ⚠️ 避坑指南：小红书突破 21 条无尽抓取
- **优先使用新版 App V2**：先走 `app_v2/get_user_posted_notes`，失败后再降级 `app/get_user_notes`、`web_v3/fetch_user_notes`、`web/get_user_notes_v2`。
- **游标兼容多结构**：不同端点的 `cursor` 位置不同，脚本会从顶层 `cursor`、`next_cursor`、最后一条笔记的 `cursor/note_id/id` 依次兜底。
- **关于点赞数**：App/App V2 通常会直接提供更完整的互动数据，Web 端作为兜底使用。
- **扫码拦截墙与搜索直达降维打击**：App 端点天然不返回 `xsec_token` 网页护照，导致在 PC 浏览器点击原生笔记链接（需护照验证）必定触发“请扫码”报错死局。架构中已将 `xhs_visualizer.py` 内嵌 HTML 跳板转化协议：直接把缺失护照的底层链接强行伪装拼接为小红书原生搜索入口 `search_result/?keyword={URL_encoded_title}`。借助搜索免扫码特性，换取全量极速稳定抓取。

### 响应要点

- **笔记详情路径**：`data["data"][0]["note_list"][0]`
- **互动数**：`liked_count` / `collected_count` / `comments_count` / `shared_count` 在顶层，`interact_info` 始终为空
- **时间戳**：秒级，用 `datetime.fromtimestamp(ts)`
- **封面图**：`images_list[0]["original"]`（原图）或 `["url"]`（压缩版），CDN 有时效，立刻提取
- `note_id` 优先于 `share_text`；`xhslink.com` 短链可直接作为 `share_text`

### ID 提取

```
用户ID：https://www.xiaohongshu.com/user/profile/{user_id}
笔记ID：https://www.xiaohongshu.com/explore/{note_id}
```

### 💎 尊享版：小红书端到端账号高级拆解流水线

针对首要平台“小红书”，我们集成了最高级别全自动拆解环境，专门为**高级付费使用**（无需启动本地浏览器，规避封控）。
当你需要深度分析对标账号时（遇到“拆解账号”“分析对标”等指令），请严格依次执行以下完整的**四步流水线**指令链。

> **🤖 给大模型（OpenClaw）的路径变量指示**：执行下述 Python 脚本指令时，请自行将 `[SKILL_DIR]` 替换为当前运行此 Skill 根目录的绝对路径（例如 `~/.claude/skills/wudami-xhs-scraper-skill` 或 `~/.openclaw/skills/openclaw-media-analyzer` 等）。

**第一步：全量高速 API 抓取**
```bash
python3 [SKILL_DIR]/scripts/xhs_tikhub_account_scraper.py \
  --url "https://www.xiaohongshu.com/user/profile/{user_id}" \
  --max-notes 999 \
  --output outputs/raw_data.json
```
*(注：该脚本将 TikHub API 数据自动映射为系统标准格式。请确保存放此 output 的 cwd 目录是安全的持久化工作区。)*

**第二步：数学引擎与 NLP 统计分析**
```bash
python3 [SKILL_DIR]/scripts/xhs_account_analyzer.py \
  -i outputs/raw_data.json \
  -o outputs/account_report.md \
  -j outputs/account_data.json
```
*(内置动态去噪机制：自动提取账号昵称并碎片化加入 NLP 停用词库，彻底解决作者名霸屏词云现象。)*

**第三步：AI 深度解读撰写**
大模型应当读取 `outputs/account_report.md` 中的提纯基础数据，严格遵守“防幻觉”规则，编写标准的**小红书专属11段式商业拆解报告**，并保存为 `outputs/深度拆解报告.md`。必须包含以下带前缀 `## ` 的 11 个标准段落（⚠️ 请严格遵循该框架，绝不要与抖音的拆解框架混用）：
1. 一、吸睛开场
2. 二、账号速览
3. 三、账号发展路径
4. 四、爆款因子
5. 五、人设打造策略
6. 六、内容形式拆解（含 `**④ 词云分析**` 锚点词）
7. 七、选题维度拆解
8. 八、内容生产 SOP 倒推
9. 九、变现分析
10. 十、直接可抄的行动清单
11. 十一、三大启示

**第四步：可交互 HTML 战报渲染**
```bash
python3 [SKILL_DIR]/scripts/xhs_visualizer.py \
  --md outputs/深度拆解报告.md \
  --json outputs/account_data.json \
  --out outputs/拆解可视化报告.html
```
*(内置优化：自动无缝转换防拦截搜索跳板链接、悬浮 Tooltip 动态高亮原图、可点击交互画廊，以及底层渲染引擎对冗余词云数据源文本的自动化拦截吞噬，呈现干净极简的高级 UI。)*

**第五步：桌面打包交付（开箱即用体验）**
为了提供“开箱即用”的小白体验，在上述步骤运行完后，你**必须**在对话框静默执行这条指令，把生成的文件打包导出到用户的 Mac 桌面：
```bash
python3 [SKILL_DIR]/scripts/export_to_desktop.py \
  --md outputs/深度拆解报告.md \
  --html outputs/拆解可视化报告.html \
  --json outputs/account_data.json
```
*(内置特性：自动免配置依赖安装 python-docx，将报告完美转化为 Word 格式文档，并把交互式 HTML 抓取至桌面，以 strictly `日期-账号名-文档类型` 的规范发送。)*

**第六步：向用户交付最终结果（输出规范）**
当上述所有抓取、撰写、渲染以及**桌面推送**步骤全部完成后，**大模型必须在对话框中向用户直接展示最终成果**，严格遵循以下提交流程：
1. **直接输出 Markdown 原文**：在对话框中，将你在“第三步”中撰写完成的《深度拆解报告.md》的完整内容（完整的 11 段式文本）直接打印输出，方便用户在对话界面快速通读。
2. **附带收尾提示**：在输出完长篇 Markdown 报告后，**必须**在结尾处，醒目地告知用户：
   「💎 **你的专属高级可视化战报 (.html) 和 深度拆解报告 (.docx) 已经全部自动发往你的电脑桌面！纯净无痕，开箱即用！**」

---

## 平台二：抖音（Douyin）

### 端点列表

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 获取用户主页 | `GET /api/v1/douyin/web/handler_user_profile` | `unique_id` 或 `sec_user_id` |
| 获取用户视频列表 | `GET /api/v1/douyin/web/fetch_user_post_videos` | `sec_user_id`, `max_cursor` |
| 获取单条视频 | `GET /api/v1/douyin/web/fetch_one_video` | `aweme_id` |
| 通过分享链接获取视频 | `GET /api/v1/douyin/web/fetch_one_video_by_share_url` | `share_url` |
| 获取视频评论 | `GET /api/v1/douyin/web/fetch_video_comments` | `aweme_id`, `cursor` |
| 搜索用户 | `GET /api/v1/douyin/web/fetch_user_search_result` | `keyword`, `cursor` |
| 搜索视频 | `GET /api/v1/douyin/web/fetch_video_search_result` | `keyword`, `cursor` |
| 热搜榜 | `GET /api/v1/douyin/web/fetch_hot_search_result` | 无 |

### 备用端点（App 版，Web 失败时用）

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 获取用户主页 | `GET /api/v1/douyin/app/v3/handler_user_profile` | `sec_user_id` |
| 获取用户视频 | `GET /api/v1/douyin/app/v3/fetch_user_post_videos` | `sec_user_id`, `max_cursor` |
| 获取单条视频 | `GET /api/v1/douyin/app/v3/fetch_one_video` | `aweme_id` |
| 通过分享链接获取视频 | `GET /api/v1/douyin/app/v3/fetch_one_video_by_share_url` | `share_url` |
| 搜索视频 | `GET /api/v1/douyin/app/v3/fetch_video_search_result` | `keyword`, `cursor` |

### 响应要点

- `unique_id` = 抖音号（@xxx），`sec_user_id` = URL 中的长 ID
- 视频列表翻页用 `max_cursor`（不是 `cursor`）
- 从 URL 提取 `aweme_id`：`douyin.com/video/{aweme_id}`

### ID 提取

```
sec_user_id：https://www.douyin.com/user/{sec_user_id}
aweme_id：https://www.douyin.com/video/{aweme_id}
```

### 💎 尊享版：抖音端到端账号高级拆解流水线

与小红书对等，我们也为**抖音**部署了全自动的四步拆解环境。当你指令要求“拆解抖音账号”时，请严格依次执行以下完整的**四步流水线**指令链：

**第一步：全量高速 API 抓取**
```bash
python3 [SKILL_DIR]/scripts/douyin_tikhub_account_scraper.py \
  --url "https://www.douyin.com/user/{sec_user_id}" \
  --max-notes 999 \
  --output outputs/raw_data.json
```
*(注：由于抖音返回 aweme 接口，该脚本会将其清洗并映射为系统通用大盘格式。)*

**第二步：数学引擎与 NLP 统计分析**
```bash
python3 [SKILL_DIR]/scripts/douyin_account_analyzer.py \
  -i outputs/raw_data.json \
  -o outputs/account_report.md \
  -j outputs/account_data.json
```
*(内置动态去噪机制：自动提取账号昵称并碎片化加入 NLP 停用词库，同时对标题进行平台解耦映射，有效防范 AI 重复幻觉。)*

**第三步：AI 深度解读撰写**
大模型应当读取 `outputs/account_report.md` 中的提纯基础数据，严格遵守“防幻觉”规则，编写标准的**抖音专属11段式高级商业报告**，并保存为 `outputs/深度拆解报告.md`。必须包含以下带前缀 `## ` 的 11 个标准段落（⚠️ 请严格遵循抖音暗黑系商业思维框架，绝不要与小红书的拆解框架混用）：
1. 一、核心数据资产总览
2. 二、三重定位法剖析（人设/内容/变现）
3. 三、流量密码与爆款引擎
4. 四、编年史演进（点赞潮汐时间轴分析）
5. 五、内容的“5维词汇”画像
6. 六、四大核心内容维度语义归类
7. 七、视觉与表现张力推演
8. 八、商业模式的普适性借鉴意义全盘扫描
9. 九、突破与演进的操盘建议
10. 十、AI 拆解总结结论
11. 十一、TOP3 爆款视频图鉴长廊

**第四步：可交互 HTML 战报渲染**
```bash
python3 [SKILL_DIR]/scripts/douyin_visualizer.py \
  --md outputs/深度拆解报告.md \
  --json outputs/account_data.json \
  --out outputs/拆解可视化报告.html
```
*(内置特性：采用高度解耦的独立渲染器与抖音原生暗黑极客 UI 引擎封装，独家支持 TOP3 爆款悬浮链接交互与发光 Rank 徽章特写效。)*

**第五步：桌面打包交付（开箱即用体验）**
为了提供“开箱即用”的小白体验，在上述步骤运行完后，你**必须**在对话框静默执行这条指令，把生成的文件打包导出到用户的 Mac 桌面：
```bash
python3 [SKILL_DIR]/scripts/export_to_desktop.py \
  --md outputs/深度拆解报告.md \
  --html outputs/拆解可视化报告.html \
  --json outputs/account_data.json
```
*(内置特性：自动免配置依赖安装 python-docx，将报告完美转化为 Word 格式文档，并把交互式 HTML 抓取至桌面，以 strictly `日期-账号名-文档类型` 的规范发送。)*

**第六步：向用户交付最终结果（输出规范）**
当上述所有抓取、撰写、渲染以及**桌面推送**步骤全部完成后，**大模型必须在对话框中向用户直接展示最终成果**，严格遵循以下提交流程：
1. **直接输出 Markdown 原文**：在对话框中，将你在“第三步”中撰写完成的《深度拆解报告.md》的完整内容（完整的 11 段式商业文本）直接打印输出，方便用户在对话界面快速通读和复用。
2. **附带收尾提示**：在输出完长篇 Markdown 报告后，**必须**在结尾处，醒目地告知用户：
   「💎 **你的专属抖音黑客风高级战报 (.html) 和 深度拆解报告 (.docx) 已经全部自动发往你的电脑桌面！纯净无痕，开箱即用！**」

---

## 平台三：TikTok

### 端点列表

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 获取用户主页 | `GET /api/v1/tiktok/web/fetch_user_profile` | `uniqueId` |
| 获取用户视频 | `GET /api/v1/tiktok/web/fetch_user_post` | `secUid`, `cursor`, `count` |
| 获取视频详情 | `GET /api/v1/tiktok/web/fetch_post_detail` | `itemId` |
| 通过分享链接获取视频 | `GET /api/v1/tiktok/app/v3/fetch_one_video_by_share_url` | `share_url` |
| 获取视频评论 | `GET /api/v1/tiktok/web/fetch_post_comment` | `aweme_id`, `cursor` |
| 搜索用户 | `GET /api/v1/tiktok/web/fetch_search_user` | `keyword`, `cursor` |
| 搜索视频 | `GET /api/v1/tiktok/web/fetch_search_video` | `keyword`, `count`, `offset` |
| 热门话题 | `GET /api/v1/tiktok/web/fetch_trending_searchwords` | 无 |

### 备用端点（App 版，Web 失败时用）

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 获取用户主页 | `GET /api/v1/tiktok/app/v3/handler_user_profile` | `sec_user_id` |
| 获取用户视频 | `GET /api/v1/tiktok/app/v3/fetch_user_post_videos` | `sec_user_id`, `max_cursor` |
| 获取单条视频 | `GET /api/v1/tiktok/app/v3/fetch_one_video` | `aweme_id` |
| 搜索用户 | `GET /api/v1/tiktok/app/v3/fetch_user_search_result` | `keyword`, `cursor` |
| 搜索视频 | `GET /api/v1/tiktok/app/v3/fetch_video_search_result` | `keyword`, `cursor` |

### 响应要点

- `uniqueId` = @用户名（不含@），`secUid` = URL 中的长 ID
- 先用 `uniqueId` 调用 `fetch_user_profile` 拿到 `secUid`，再翻页获取视频
- 视频列表翻页用 `cursor`

### ID 提取

```
uniqueId：https://www.tiktok.com/@{uniqueId}
itemId：https://www.tiktok.com/@xxx/video/{itemId}
```

---

## 平台四：Bilibili

### 端点列表

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 获取用户主页 | `GET /api/v1/bilibili/web/fetch_user_profile` | `uid` |
| 获取用户视频 | `GET /api/v1/bilibili/web/fetch_user_post_videos` | `uid`, `page`, `pagesize` |
| 获取视频详情 | `GET /api/v1/bilibili/web/fetch_one_video` | `bvid` 或 `aid` |
| 获取视频详情 v2 | `GET /api/v1/bilibili/web/fetch_video_detail` | `bvid` |
| 获取视频评论 | `GET /api/v1/bilibili/web/fetch_video_comments` | `bvid`, `page` |
| 综合搜索 | `GET /api/v1/bilibili/web/fetch_general_search` | `keyword`, `page` |
| 热搜 | `GET /api/v1/bilibili/web/fetch_hot_search` | 无 |

### 备用端点（App 版，Web 失败时用）

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 获取用户信息 | `GET /api/v1/bilibili/app/fetch_user_info` | `uid` |
| 获取用户视频 | `GET /api/v1/bilibili/app/fetch_user_videos` | `uid`, `page` |
| 获取视频详情 | `GET /api/v1/bilibili/app/fetch_one_video` | `bvid` |
| 获取视频评论 | `GET /api/v1/bilibili/app/fetch_video_comments` | `bvid`, `page` |
| 综合搜索 | `GET /api/v1/bilibili/app/fetch_search_all` | `keyword`, `page` |

### 响应要点

- `uid` = 数字用户 ID
- `bvid` = BV 号（如 `BV1xx411c7mD`），`aid` = AV 号（数字）
- 视频列表翻页用 `page`（从 1 开始），`pagesize` 默认 30

### ID 提取

```
uid：https://space.bilibili.com/{uid}
bvid：https://www.bilibili.com/video/{bvid}
```

---

## 平台五：微博（Weibo）

### 端点列表

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 获取用户信息 | `GET /api/v1/weibo/app/fetch_user_info` | `uid` 或 `screen_name` |
| 获取用户微博 | `GET /api/v1/weibo/web/fetch_user_posts` | `uid`, `page` |
| 获取用户视频 | `GET /api/v1/weibo/web_v2/fetch_user_video_list` | `uid`, `page` |
| 搜索（综合） | `GET /api/v1/weibo/web/fetch_search` | `keyword`, `page` |
| 搜索用户 | `GET /api/v1/weibo/web_v2/fetch_user_search` | `keyword`, `page` |
| 搜索视频 | `GET /api/v1/weibo/web_v2/fetch_video_search` | `keyword`, `page` |
| 热搜榜 | `GET /api/v1/weibo/app/fetch_hot_search` | 无 |
| AI 热点搜索 | `GET /api/v1/weibo/web_v2/fetch_ai_search` | `keyword` |
| 高级搜索 | `GET /api/v1/weibo/web_v2/fetch_advanced_search` | `keyword`, `page` |

### 响应要点

- `uid` = 数字 ID，`screen_name` = 微博昵称
- 翻页用 `page`（从 1 开始）

### ID 提取

```
uid：https://weibo.com/u/{uid}
     https://weibo.com/{screen_name}（昵称直接用）
```

---

## 平台六：YouTube

> ⚠️ **目前仅支持搜索**，暂无频道详情或视频详情端点。

### 端点列表

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 综合搜索 | `GET /api/v1/youtube/web_v2/get_general_search` | `keyword` |
| 搜索频道 | `GET /api/v1/youtube/web_v2/search_channels` | `keyword` |
| 搜索视频 | `GET /api/v1/youtube/web/search_video` | `keyword` |
| 搜索 Shorts | `GET /api/v1/youtube/web_v2/get_shorts_search` | `keyword` |
| 搜索建议词 | `GET /api/v1/youtube/web_v2/get_search_suggestions` | `keyword` |

---

## 平台七：微信公众号（WeChat MP）

### 端点列表

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 获取文章详情（JSON） | `GET /api/v1/wechat_mp/web/fetch_mp_article_detail_json` | `url` |
| 获取文章详情（HTML） | `GET /api/v1/wechat_mp/web/fetch_mp_article_detail_html` | `url` |
| 获取公众号文章列表 | `GET /api/v1/wechat_mp/web/fetch_mp_article_list` | `url` 或 `biz` |
| 获取文章评论 | `GET /api/v1/wechat_mp/web/fetch_mp_article_comment_list` | `url` |
| 获取文章阅读数 | `GET /api/v1/wechat_mp/web/fetch_mp_article_read_count` | `url` |
| 获取相关文章 | `GET /api/v1/wechat_mp/web/fetch_mp_related_articles` | `url` |
| 获取文章广告 | `GET /api/v1/wechat_mp/web/fetch_mp_article_ad` | `url` |

### 响应要点

- 所有端点主要参数为文章 `url`（`mp.weixin.qq.com/s/...`）
- `biz` = 公众号唯一标识，从文章 URL 中提取：`__biz=MzI...`

---

## 平台八：微信视频号（WeChat Channels）

### 端点列表

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 搜索创作者 | `GET /api/v1/wechat_channels/fetch_user_search` | `keyword` |
| 搜索创作者 v2 | `GET /api/v1/wechat_channels/fetch_user_search_v2` | `keyword` |
| 综合搜索 | `GET /api/v1/wechat_channels/fetch_default_search` | `keyword` |
| 最新内容搜索 | `GET /api/v1/wechat_channels/fetch_search_latest` | `keyword` |
| 普通内容搜索 | `GET /api/v1/wechat_channels/fetch_search_ordinary` | `keyword` |
| 获取视频详情 | `GET /api/v1/wechat_channels/fetch_video_detail` | `video_id` 或 `url` |
| 获取视频评论 | `GET /api/v1/wechat_channels/fetch_comments` | `video_id` |
| 主页内容 | `GET /api/v1/wechat_channels/fetch_home_page` | `username` |
| 热词 | `GET /api/v1/wechat_channels/fetch_hot_words` | 无 |
| 直播历史 | `GET /api/v1/wechat_channels/fetch_live_history` | `username` |

---

## 平台九：Twitter / X

### 端点列表

| 功能 | 端点 | 主要参数 |
|------|------|---------|
| 获取用户主页 | `GET /api/v1/twitter/web/fetch_user_profile` | `screen_name` 或 `user_id` |
| 获取用户推文 | `GET /api/v1/twitter/web/fetch_user_post_tweet` | `user_id`, `cursor` |
| 搜索推文 | `GET /api/v1/twitter/web/fetch_search_timeline` | `keyword`, `cursor` |

### 响应要点

- `screen_name` = @用户名（不含@），`user_id` = 数字 ID
- 先用 `screen_name` 调 `fetch_user_profile` 获取 `user_id`，再翻页

### ID 提取

```
screen_name：https://twitter.com/{screen_name}
             https://x.com/{screen_name}
```

---

## 批量翻页通用模板

```python
async def fetch_all_pages(endpoint, base_params, cursor_key="cursor", data_key="list"):
    """通用翻页抓取"""
    all_items = []
    cursor = None
    while True:
        params = {**base_params}
        if cursor:
            params[cursor_key] = cursor
        result = await api_get(endpoint, params)
        inner = result.get("data", {}).get("data", {})
        items = inner.get(data_key, [])
        all_items.extend(items)
        has_more = inner.get("has_more", False)
        cursor = inner.get(cursor_key)
        if not has_more or not cursor:
            break
        await asyncio.sleep(0.5)
    return all_items
```

> ⚠️ cursor_key 差异：小红书/TikTok/Twitter 用 `cursor`，抖音用 `max_cursor`，Bilibili/微博用 `page`（数字递增）

---

## 常见问题

| 报错 | 可能原因 | 解决方法 |
|------|---------|---------|
| `400` | 端点需要额外参数或内容已删除 | 换分享链接方式，或换 v2/v3 备用端点 |
| `401` | API Key 未配置 | 检查 `TIKHUB_API_KEY` 环境变量 |
| `429` | 限流 | 每次请求间加 `await asyncio.sleep(0.5~1)` |
| 超时 | 域名/网络链路不匹配 | 国内默认使用 `api.tikhub.dev`，必要时用 `TIKHUB_BASE_URL` 切换 |

## API 基础信息

- **Base URL**: 国内默认 `https://api.tikhub.dev`；可用 `TIKHUB_BASE_URL` 覆盖
- **Timeout**: 默认 `45s`；可用 `TIKHUB_TIMEOUT` 覆盖
- **鉴权**: `Authorization: Bearer {TIKHUB_API_KEY}`
- **定价**: $0.001/次，详见 [TikHub Pricing](https://user.tikhub.io/dashboard/pricing)
- **缓存**: 成功请求缓存 24 小时，重复请求不额外计费

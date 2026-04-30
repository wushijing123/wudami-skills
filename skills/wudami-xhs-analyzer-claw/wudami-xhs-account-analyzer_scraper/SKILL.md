---
name: wudami-xhs-auto-analyzer
description: >
  深度拆解小红书对标账号，全自动数据采集 + 专业分析。当用户说「拆解账号」「分析对标」「对标账号分析」「帮我看看这个博主」「分析一下这个账号」「我想学这个博主」「这个账号为什么能爆」「对标研究」「竞品账号」时立即触发。
  用户只需提供一个账号主页链接或昵称，skill 自动完成：数据抓取 → 数据解析 → 11段式分析报告 → 归档到「对标账号库」。无需用户手动输入任何数据。
---

# 小红书账号深度拆解（全自动版）

## 核心流程

```
用户给链接 → 自动抓取数据 → 自动分析 → 输出报告 → 归档
```

**三步完成，无需用户介入数据采集环节。**

## Step 1：数据采集（调用 TikHub API）

直接用 Python 脚本调用 TikHub API，无需用户登录或提供 cookie。

**执行方式硬规则**：默认运行本地 Python 脚本直接请求 TikHub HTTP API，不走 MCP。除非主理人明确要求使用 MCP，否则不要调用 `mcp__tikhub*` 工具。

**TikHub 配置**：默认使用 `https://api.tikhub.dev`，可用 `TIKHUB_BASE_URL` 覆盖；默认超时 `45s`，可用 `TIKHUB_TIMEOUT` 覆盖。

### 采集内容

| 数据 | 端点 | 说明 |
|------|------|------|
| 用户基本信息 | `GET /api/v1/xiaohongshu/web/get_user_info` / App 备用 | 昵称、粉丝数、笔记数、简介 |
| 用户笔记列表 | App V2 → App → Web V3 → Web V2 降级链 | 含点赞/收藏/评论，翻页抓取全部 |
| 爆款笔记详情 | App V2 → App → Web V3 → Web V4 降级链 | 点赞最高的前3篇笔记的完整内容 |

### 数据采集脚本

```python
import asyncio, os, json, httpx
from datetime import datetime

BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
TIKHUB_TIMEOUT = float(os.environ.get("TIKHUB_TIMEOUT", "45"))
HEADERS = {"Authorization": f"Bearer {os.environ.get('TIKHUB_API_KEY')}"}

async def fetch_user_info(user_id: str) -> dict:
    async with httpx.AsyncClient(timeout=TIKHUB_TIMEOUT) as client:
        r = await client.get(f"{BASE_URL}/api/v1/xiaohongshu/app/get_user_info",
                             params={"user_id": user_id}, headers=HEADERS)
        r.raise_for_status()
        return r.json().get("data", {}).get("data", {})

async def fetch_all_notes(user_id: str) -> list:
    all_notes = []
    cursor = None
    endpoints = [
        "/api/v1/xiaohongshu/app_v2/get_user_posted_notes",
        "/api/v1/xiaohongshu/app/get_user_notes",
        "/api/v1/xiaohongshu/web_v3/fetch_user_notes",
        "/api/v1/xiaohongshu/web/get_user_notes_v2",
    ]
    async with httpx.AsyncClient(timeout=TIKHUB_TIMEOUT) as client:
        for endpoint in endpoints:
            try:
                while True:
                    params = {"user_id": user_id}
                    if cursor:
                        params["cursor"] = cursor
                    r = await client.get(f"{BASE_URL}{endpoint}", params=params, headers=HEADERS)
                    r.raise_for_status()
                    inner = r.json().get("data", {}).get("data", {})
                    notes = inner.get("notes") or inner.get("items") or []
                    all_notes.extend(notes)
                    cursor = inner.get("cursor") or inner.get("next_cursor")
                    has_more = inner.get("has_more", False)
                    if not has_more or not cursor:
                        break
                    await asyncio.sleep(0.5)
                if all_notes:
                    return all_notes
            except Exception:
                all_notes = []
                cursor = None
    return all_notes

async def fetch_note_detail(share_text: str) -> dict:
    async with httpx.AsyncClient(timeout=TIKHUB_TIMEOUT) as client:
        r = await client.get(f"{BASE_URL}/api/v1/xiaohongshu/app_v2/get_video_note_detail",
                             params={"share_text": share_text}, headers=HEADERS)
        r.raise_for_status()
        return r.json()

async def main(user_id: str, top_note_share_texts: list):
    # 1. 拉用户信息
    user_info = await fetch_user_info(user_id)

    # 2. 拉全部笔记（含互动数据）
    all_notes = await fetch_all_notes(user_id)

    # 3. 拉前3篇爆款笔记详情
    top_notes = []
    for share_text in top_note_share_texts[:3]:
        detail = await fetch_note_detail(share_text)
        top_notes.append(detail)
        await asyncio.sleep(0.5)

    return {"user_info": user_info, "all_notes": all_notes, "top_notes": top_notes}
```

### ID 提取规则

- **主页链接**：`xiaohongshu.com/user/profile/5c1234...` → user_id = `5c1234...`
- **分享链接**：`xhslink.com/a/xxxxx` → 直接作为 `share_text` 传入
- **只有昵称**：先用 `search_users` 搜索，再用第一个结果

## Step 2：数据分析

数据到手后，按以下结构输出分析。写作风格 = 专业内核 + 生动口语，禁止模板腔。

### 数据预处理

抓取完成后，打印以下统计供分析参考：
- 笔记总数、点赞分布（前10/前20/前50）
- 平均互动率 = (点赞+收藏+评论) / 粉丝数
- 发布频率（最近30天发布条数）
- 最高点赞笔记标题 + 点赞数

### 输出结构

#### 一、吸睛开场
2-3 句原创钩子，制造冲突/悬念/惊喜。**禁止**「今天给大家拆解一个账号」套话。

#### 二、账号速览
昵称、粉丝量级、作品体量、首发时间、近期互动率，结尾加随性评价。

#### 三、账号发展路径
根据笔记时间/风格变化梳理：冷启动期→转型期（如有）→成熟期。若数据不足写「根据当前数据无法判断」。

#### 四、爆款因子
≥3条。结构：**现象 → 原理 → 可抄走的做法**，每条≥80字。

#### 五、人设打造策略
记忆点设计（反差标签/视觉锤/口头禅）+ 信任体系（简介/置顶/背书）+ 情绪价值。

#### 六、内容形式分析
拍摄&剪辑可复用优点 + 封面四维点评 + 标题套路综述+2-3条拆解。

#### 七、选题维度拆解
3-5个主题维度，各含占比/代表性标题/核心痛点/爆点逻辑。

#### 八、内容生产 SOP
固定模块 + 变量模块 + 差异化定位公式。

#### 九、变现分析
现有路径（标注成熟度）+ 3条升级/借鉴方案（每条60-80字）。

#### 十、可复用行动清单
5条短段落（每条40-70字），可直接读出。

#### 十一、三大启示
150-200字收尾，末句给可执行行动号召。

## Step 3：归档

分析完成后，自动写入 Obsidian 对标账号库：

**文件路径**：`02-素材库/对标账号库/账号档案/{账号昵称}/README.md`

**文件内容**：
```markdown
# {账号昵称} 账号拆解

> 拆解时间：{YYYY-MM-DD}

## 基础信息
- 粉丝数：
- 笔记数：
- 赞藏比：
- 更新频率：

## 分析报告
{11段式完整分析内容粘贴于此}

## 原始数据
- 笔记列表：[notes.json](./notes.json)
- 爆款详情：[top-notes.json](./top-notes.json)
```

同时保存原始数据：
- `02-素材库/对标账号库/账号档案/{账号昵称}/notes.json`
- `02-素材库/对标账号库/账号档案/{账号昵称}/top-notes.json`

## 异常处理

| 情况 | 处理方式 |
|------|---------|
| API 返回 401 | 检查 TIKHUB_API_KEY 配置 |
| API 返回 429 | 等待1秒后重试，循环最多3次 |
| 笔记列表为空 | 可能是账号不存在或笔记已删除，告知用户 |
| 爆款详情拉取失败 | 降级：用笔记列表中的描述字段替代，不阻断分析 |
| 用户只给了昵称 | 先调用 `search_users` 找到 user_id，再继续 |

## 核心约束（与旧版相同）

1. **事实为本，拒绝编造**：严格基于 API 返回数据分析
2. **不止罗列现象**：说明背后的心理学逻辑或运营心机
3. **信息不足时主动提示**：缺少变现数据等，明确告知用户

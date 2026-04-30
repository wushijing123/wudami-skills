---
name: wudami-live-teleprompter
description: 直播投屏器 — 将内容文件（Markdown、DOCX、HTML、大纲）自动转化为演示 slides + 口播稿，生成 Web 投屏器应用。支持主控台（slide + 口播稿）和独立投屏窗口（纯 slide 展示，用于 OBS 捕获）。当用户提到「投屏器」「直播投屏」「teleprompter」「演示文稿+口播稿」「做一个投屏」「直播演示」「帮我做投屏」时触发。
---

# Live Teleprompter — 直播投屏器

将用户输入文件自动转化为「演示 slides + 口播稿」，生成 Web 投屏器。

## 产出物

- **主控台**（index.html）：左屏 slide 演示 + 右屏口播稿 + 翻页控制
- **投屏窗口**（cast.html）：独立窗口，全屏 slide 展示，供 OBS 窗口捕获

## 脚本目录

`SKILL_DIR` = 此 SKILL.md 所在目录。

| 脚本 | 用途 |
|------|------|
| `scripts/serve.sh` | 启动本地 HTTP 服务并打开浏览器 |

## 工作流

```
1. 解析文件 → 2. 生成 data.js → 3. 复制模板 → 4. 启动服务
```

### Step 1: 解析用户文件

根据文件格式提取内容：

| 格式 | 方法 |
|------|------|
| `.md` | 直接读取 |
| `.docx` | `textutil -convert txt -stdout <file>` |
| `.html` | 读取提取正文 |
| 纯文本/大纲 | 直接使用 |

### Step 2: 生成 data.js

读取 `references/content-generation.md` 获取完整的生成规则和数据格式。

核心原则：
- 第 1 页 = `cover`，最后 1 页 = `closing`
- 每页 3-5 个要点，总页数 8-20
- 口播稿口语化、有节奏、有过渡句
- `title` 支持 `<em>` 标签实现金色高亮

生成完成后将 `data.js` 写入目标目录。

### Step 3: 复制模板

将 `${SKILL_DIR}/assets/teleprompter/` 下的所有文件复制到工作目录：

```bash
WORK_DIR="teleprompter-output/{topic-slug}"
mkdir -p "$WORK_DIR"
cp ${SKILL_DIR}/assets/teleprompter/index.html "$WORK_DIR/"
cp ${SKILL_DIR}/assets/teleprompter/cast.html "$WORK_DIR/"
cp ${SKILL_DIR}/assets/teleprompter/styles.css "$WORK_DIR/"
cp ${SKILL_DIR}/assets/teleprompter/app.js "$WORK_DIR/"
cp ${SKILL_DIR}/assets/teleprompter/cast.js "$WORK_DIR/"
```

然后将生成的 `data.js` 写入 `$WORK_DIR/data.js`（覆盖模板中的示例数据）。

### Step 4: 启动服务

```bash
bash ${SKILL_DIR}/scripts/serve.sh "$WORK_DIR"
```

浏览器自动打开主控台。用户点击「打开投屏」按钮启动独立投屏窗口。

## 操作指南（告知用户）

启动后向用户说明：

```
🖥️ 投屏器已就绪！

操作方式：
- ← → 键翻页（鼠标点击也可以）
- 点击底部缩略图快速跳转
- A-/A+ 调整口播稿字号
- 点击「打开投屏」弹出独立窗口用于 OBS 捕获
- 主控台翻页时，投屏窗口和口播稿自动同步
```

## 输出目录结构

```
teleprompter-output/{topic-slug}/
├── index.html      # 主控台
├── cast.html       # 投屏窗口
├── styles.css      # 样式
├── app.js          # 主控台逻辑
├── cast.js         # 投屏窗口逻辑
└── data.js         # 生成的内容数据
```

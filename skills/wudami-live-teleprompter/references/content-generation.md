# 内容生成指南 — Slide + 口播稿

将用户输入文件转化为 `data.js` 格式的结构化数据。

## 文件解析

| 格式 | 解析方式 |
|------|---------|
| `.md` | 直接读取 Markdown 内容 |
| `.docx` | 运行 `textutil -convert txt -stdout <file>` 提取纯文本 |
| `.html` | 读取文件，提取 `<body>` 正文内容 |
| 纯文本/大纲 | 直接使用 |

## Slide 拆分规则

1. **第 1 页**固定为 `cover` 布局 — 包含主标题、副标题、年份（可选）
2. 每个一级标题（`#`）或核心章节拆为 1 个 slide
3. 每页 slide 控制 **3-5 个要点**，超出则拆分为多页
4. **最后 1 页**固定为 `closing` 布局 — 总结/号召
5. 总页数建议 **8-20 页**

## Layout 选择

| 内容特征 | Layout | 说明 |
|---------|--------|------|
| 标题/主题介绍 | `cover` | 大标题 + 副标题 + 年份 |
| 3-5 个并列要点 | `bullets` | 标题 + 项目符号列表 |
| 两组对比数据 | `comparison` | 标题 + 左右两栏对比 |
| 引用/金句/关键观点 | `quote` | 引号 + 引用文本 + 来源 |
| 总结/CTA/结束语 | `closing` | 大标题 + 副标题 |

## 口播稿生成规则

每页 slide 对应一段口播稿，结构：

```json
{
  "label": "段落小标题（2-4字）",
  "text": "口播内容正文"
}
```

### 写作要求

- **口语化** — 像跟朋友聊天，不是念稿。用"你"不用"您"，用"我们"拉近距离
- **有节奏** — 短句为主，适当换行形成呼吸感。关键观点前加停顿
- **有过渡** — 每段开头用过渡句衔接（"接下来…"、"这意味着什么？"、"你可能会问…"）
- **有案例** — 用具体场景和数字说明抽象概念
- **控制长度** — 每段 100-300 字，适合 1-3 分钟讲解
- **label 精炼** — 用 2-4 字高度概括（"开场定调"、"核心观点"、"案例分析"、"总结号召"）

## data.js 输出格式

```javascript
const TELEPROMPTER_DATA = {
  title: "演示主题",
  totalSlides: N,
  slides: [
    // cover
    {
      id: 1,
      layout: "cover",
      title: "主标题\n可换行",
      subtitle: "副标题",
      year: "2025",
      script: { label: "开场定调", text: "口播内容..." }
    },
    // bullets
    {
      id: 2,
      layout: "bullets",
      title: "章节标题",
      bullets: ["要点1", "要点2", "要点3"],
      script: { label: "段落标题", text: "口播内容..." }
    },
    // comparison
    {
      id: 3,
      layout: "comparison",
      title: "对比标题",
      left:  { heading: "左栏标题", items: ["left1", "left2"] },
      right: { heading: "右栏标题", items: ["right1", "right2"] },
      script: { label: "对比分析", text: "口播内容..." }
    },
    // quote
    {
      id: 4,
      layout: "quote",
      quote: "引用文本",
      author: "—— 来源",
      script: { label: "关键观点", text: "口播内容..." }
    },
    // closing
    {
      id: N,
      layout: "closing",
      title: "结尾标题",
      subtitle: "结尾副标题",
      script: { label: "结尾号召", text: "口播内容..." }
    }
  ]
};
```

### title 字段支持 HTML

`title` 字段支持 `<em>` 标签实现金色高亮，例如：

```javascript
title: "什么是 <em>Claude Skills</em>"
// "Claude Skills" 会以金色高亮显示
```

## 生成示例

**输入**：一篇关于"远程办公"的 Markdown 文章

**输出 data.js**（节选）：
```javascript
{
  id: 1, layout: "cover",
  title: "远程办公\n生存指南",
  subtitle: "从工具选择到心态调整",
  year: "2025",
  script: {
    label: "开场引入",
    text: "有多少人觉得远程办公=在家摸鱼？\n\n说实话，三年前我也这么想。..."
  }
}
```

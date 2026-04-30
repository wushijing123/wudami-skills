#!/usr/bin/env python3
"""
小红书爆款笔记分析脚本

功能：
- 分析抓取到的笔记和评论数据
- 过滤低粉爆款（互动高、粉丝少）
- 提炼评论区心声
- 生成3个选题方向（含标题 + 口播初稿/内容建议）

用法：
    python xhs_analyzer.py -i /tmp/xhs_result.json
    python xhs_analyzer.py -i /tmp/xhs_result.json --notes-json /tmp/notes_detail.json
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime


def parse_count(text: str) -> int:
    """解析互动数字，支持 '1.2万' '3000' 等格式"""
    if not text:
        return 0
    text = str(text).strip().replace(",", "").replace(" ", "")
    if "万" in text:
        try:
            return int(float(text.replace("万", "")) * 10000)
        except ValueError:
            return 0
    try:
        return int(text)
    except ValueError:
        return 0


def score_virality(note: dict) -> float:
    """
    计算爆款得分
    - 互动总量（点赞+收藏+评论）是核心指标
    - 低粉丝爆款加权（粉丝越少权重越高）
    """
    likes = parse_count(note.get("likes", note.get("likeCount", 0)))
    collects = parse_count(note.get("collects", 0))
    comments = parse_count(note.get("comments", 0))

    total_interaction = likes + collects * 2 + comments * 3  # 收藏和评论权重更高

    fans = parse_count(note.get("fansCount", "50000"))
    if fans <= 0:
        fans = 10000  # 默认值

    # 低粉系数：粉丝越少，同等互动的爆款价值越高
    if fans < 1000:
        fan_multiplier = 3.0
    elif fans < 5000:
        fan_multiplier = 2.0
    elif fans < 10000:
        fan_multiplier = 1.5
    elif fans < 30000:
        fan_multiplier = 1.2
    elif fans < 50000:
        fan_multiplier = 1.0
    else:
        fan_multiplier = 0.5  # 高粉不是重点

    return total_interaction * fan_multiplier


def extract_comment_themes(comments: list[dict]) -> dict:
    """
    提炼评论区核心心声
    返回：痛点、共鸣点、问题、期待
    """
    themes = {
        "pain_points": [],      # 痛点/问题
        "resonance": [],        # 共鸣/认同
        "questions": [],        # 疑问/求教
        "requests": [],         # 期待/请求
        "top_comments": [],     # 高赞评论
    }

    # 关键词映射
    pain_keywords = ["好难", "不知道", "搞不懂", "踩坑", "失败", "困扰", "苦恼", "愁", "怎么办", "帮帮我"]
    resonance_keywords = ["太对了", "同款", "一模一样", "就是我", "说的就是我", "哭了", "OMG", "真的", "超级", "救了"]
    question_keywords = ["怎么", "哪里", "多少钱", "链接", "是什么", "教程", "攻略", "求"]
    request_keywords = ["希望", "如果能", "能不能", "什么时候", "出一期", "拍一个", "分享一下"]

    all_comment_text = []

    for comment in comments:
        text = comment.get("text", "")
        likes = parse_count(comment.get("likes", 0))

        if not text:
            continue

        all_comment_text.append(text)

        # 高赞评论
        if likes >= 50:
            themes["top_comments"].append({"text": text, "likes": likes})

        # 分类
        if any(kw in text for kw in pain_keywords):
            themes["pain_points"].append(text)
        if any(kw in text for kw in resonance_keywords):
            themes["resonance"].append(text)
        if any(kw in text for kw in question_keywords):
            themes["questions"].append(text)
        if any(kw in text for kw in request_keywords):
            themes["requests"].append(text)

    # 排序高赞评论
    themes["top_comments"].sort(key=lambda x: x["likes"], reverse=True)
    themes["top_comments"] = themes["top_comments"][:5]

    return themes


def generate_topic_directions(notes: list[dict], keyword: str = "") -> list[dict]:
    """
    根据爆款笔记内容和评论区心声生成3个选题方向

    每个方向包含：
    - 选题方向（核心角度）
    - 推荐标题（3个备选）
    - 口播初稿 / 内容建议
    """
    # 收集所有评论和内容
    all_comments = []
    all_titles = []
    all_contents = []
    pain_points = []
    questions = []
    resonance = []

    for note in notes:
        if note.get("title"):
            all_titles.append(note["title"])
        if note.get("content"):
            all_contents.append(note["content"])

        themes = extract_comment_themes(note.get("commentList", []))
        pain_points.extend(themes["pain_points"][:3])
        questions.extend(themes["questions"][:3])
        resonance.extend(themes["resonance"][:3])
        all_comments.extend(note.get("commentList", [])[:10])

    # 分析高频词
    all_text = " ".join(all_titles + all_contents)
    words = re.findall(r"[\u4e00-\u9fa5]{2,6}", all_text)
    word_freq = Counter(words).most_common(20)
    hot_words = [w for w, c in word_freq if c >= 2]

    # 构建3个选题方向
    directions = []

    # 方向1：痛点切入（最高共鸣）
    pain_summary = pain_points[:3] if pain_points else ["解决常见困惑"]
    direction_1 = {
        "方向": f"痛点共鸣型 —— 直击{'、'.join(hot_words[:3]) if hot_words else keyword}的真实困境",
        "核心逻辑": "用户在评论区暴露的痛点是选题金矿，展示'我也经历过'能迅速建立信任",
        "推荐标题": [
            f"我{keyword}失败了N次，才发现这个关键点...（亲测有效）",
            f"99%的人{keyword}都踩过的坑，你中了几个？",
            f"为什么你{keyword}总是事倍功半？看完这个你就懂了",
        ],
        "口播初稿": f"""大家好，我是[昵称]。
今天想跟大家聊一个很多人都遇到过的问题——[具体痛点场景]。

其实我之前也一样，[描述自己的失败/困惑经历]。

后来我发现，问题出在[关键原因]。

[解决方案/核心干货，3-5个步骤]

如果你也有同样的困扰，记得收藏这条视频，下次遇到直接套用！""",
        "内容建议": [
            "开头用痛点场景代入，前3秒说出'你是不是也...'",
            f"展示对比效果（before/after），来自评论区的真实反馈：{pain_summary[0] if pain_summary else ''}",
            "结尾引导评论：'你遇到过这个问题吗？评论区告诉我'",
        ],
        "参考爆款标题": all_titles[:3],
    }
    directions.append(direction_1)

    # 方向2：干货教程型（问题驱动）
    question_summary = questions[:2] if questions else ["如何做到", "在哪里找"]
    direction_2 = {
        "方向": f"干货教程型 —— 手把手教{keyword}，解答评论区高频问题",
        "核心逻辑": "评论区大量'怎么做''在哪里买'说明用户有明确需求，做成教程直接满足",
        "推荐标题": [
            f"【完整教程】{keyword}从0到1，新手也能看懂",
            f"手把手教你{keyword}，超详细步骤（附资源）",
            f"{keyword}保姆级攻略，收藏备用！",
        ],
        "口播初稿": f"""这期视频给大家整理了一套{keyword}的完整流程。

第一步：[准备工作/前期了解]
第二步：[核心操作步骤]
第三步：[细节注意点]

很多人问我[评论区高频问题]，答案是[具体回答]。

整个流程我走下来大概需要[时间/成本]，对新手来说[评价/建议]。

评论区告诉我，你最卡在哪一步？""",
        "内容建议": [
            "用分屏/字幕标注每个步骤，方便截图保存",
            f"针对性解答：{question_summary[0] if question_summary else '常见问题'}",
            "加入'避坑提示'环节，能显著提升收藏率",
            "文案结构：数字清单型（1.2.3.），降低阅读门槛",
        ],
        "参考爆款标题": all_titles[3:6] if len(all_titles) > 3 else all_titles,
    }
    directions.append(direction_2)

    # 方向3：故事共鸣型（情绪驱动）
    resonance_summary = resonance[:2] if resonance else ["真实经历", "情感共鸣"]
    direction_3 = {
        "方向": f"故事共鸣型 —— 用真实经历引发情感共鸣，低粉也能爆",
        "核心逻辑": "评论区'太对了''就是我'说明情感认同最易传播，低粉博主靠真实感突围",
        "推荐标题": [
            f"我{keyword}这一年，有些话想对你说",
            f"那个坚持{keyword}3个月的人，现在怎么样了",
            f"说说我{keyword}路上的那些真实时刻",
        ],
        "口播初稿": f"""我想跟你分享一个很真实的故事。

[从一个具体的场景/时间点开始]

那时候我[状态描述]，[遇到了什么]。

我记得最清楚的一次是[具体细节，越具体越有代入感]。

后来[转折]，我才明白[感悟/结论]。

如果你现在也在[相关处境]，我想告诉你：[鼓励/建议]。

你有没有类似的经历？""",
        "内容建议": [
            "视频风格：真实感 > 精致感，手持拍摄、口语化表达更能引发共鸣",
            "开头不要自我介绍，直接从故事最有张力的时刻切入",
            f"引用评论区原话作为素材，例如：'{resonance_summary[0] if resonance_summary else '评论区的真实反馈'}'",
            "结尾留开放性问题，鼓励用户分享自己的故事",
        ],
        "参考爆款标题": all_titles[-3:] if len(all_titles) >= 3 else all_titles,
    }
    directions.append(direction_3)

    return directions


def format_report(notes: list[dict], directions: list[dict], keyword: str = "") -> str:
    """生成格式化分析报告"""
    lines = []
    lines.append(f"# 小红书爆款分析报告")
    lines.append(f"关键词：{keyword}  |  生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # 爆款笔记列表
    lines.append(f"## 📊 爆款笔记列表（共 {len(notes)} 条）")
    lines.append("")
    lines.append("| # | 标题 | 点赞 | 收藏 | 评论 | 博主 | 粉丝数 |")
    lines.append("|---|------|------|------|------|------|--------|")

    for i, note in enumerate(notes[:20], 1):
        title = note.get("title", "")[:25] + ("..." if len(note.get("title", "")) > 25 else "")
        likes = note.get("likes", note.get("likeCount", "0"))
        collects = note.get("collects", "-")
        comments = note.get("comments", "-")
        author = note.get("authorName", "-")
        fans = note.get("fansCount", "-")
        lines.append(f"| {i} | {title} | {likes} | {collects} | {comments} | {author} | {fans} |")

    lines.append("")
    lines.append("💡 **搜索提示**：请直接在小红书 App 或网页端搜索上方标题，找到对应笔记查看详情。")
    lines.append("")

    # 选题方向
    lines.append("## 🎯 三个选题方向")
    lines.append("")

    for i, direction in enumerate(directions, 1):
        lines.append(f"### 方向 {i}：{direction['方向']}")
        lines.append(f"**核心逻辑**：{direction['核心逻辑']}")
        lines.append("")

        lines.append("**推荐标题**（三选一或组合）：")
        for title in direction["推荐标题"]:
            lines.append(f"- {title}")
        lines.append("")

        lines.append("**口播初稿 / 内容建议**：")
        if direction.get("口播初稿"):
            lines.append("```")
            lines.append(direction["口播初稿"])
            lines.append("```")
        lines.append("")

        if direction.get("内容建议"):
            lines.append("**执行要点**：")
            for tip in direction["内容建议"]:
                lines.append(f"- {tip}")
        lines.append("")

        if direction.get("参考爆款标题") and any(direction["参考爆款标题"]):
            lines.append("**参考爆款标题**（来自本次分析）：")
            for ref in direction["参考爆款标题"]:
                if ref:
                    lines.append(f"- {ref}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="小红书爆款笔记分析器")
    parser.add_argument("-i", "--input", required=True, help="抓取结果 JSON 文件")
    parser.add_argument("--keyword", default="", help="搜索关键词")
    parser.add_argument("--max-fans", type=int, default=50000, help="低粉阈值（默认5万）")
    parser.add_argument("--min-likes", type=int, default=500, help="最小点赞数（默认500）")
    parser.add_argument("-o", "--output", help="输出文件路径（默认打印到终端）")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 支持两种格式：直接列表 或 {data: [...]}
    if isinstance(raw, list):
        notes = raw
    elif isinstance(raw, dict):
        notes = raw.get("data", raw.get("notes", [raw]))
    else:
        notes = []

    print(f"📥 读取到 {len(notes)} 条笔记")

    # 过滤低粉爆款
    filtered = []
    for note in notes:
        fans = parse_count(note.get("fansCount", "0"))
        likes = parse_count(note.get("likes", note.get("likeCount", "0")))

        # 如果没有粉丝数据，只按互动过滤
        if fans == 0:
            if likes >= args.min_likes:
                filtered.append(note)
        elif fans <= args.max_fans and likes >= args.min_likes:
            filtered.append(note)

    # 按爆款得分排序
    filtered.sort(key=score_virality, reverse=True)

    print(f"✅ 筛选出 {len(filtered)} 条低粉爆款（粉丝<{args.max_fans}, 点赞>{args.min_likes}）")

    if not filtered:
        print("⚠️  没有符合条件的笔记，使用全部数据进行分析...")
        filtered = sorted(notes, key=score_virality, reverse=True)

    # 生成选题方向
    directions = generate_topic_directions(filtered, args.keyword)

    # 生成报告
    report = format_report(filtered, directions, args.keyword)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"💾 报告已保存到: {args.output}")
    else:
        print("\n" + report)


if __name__ == "__main__":
    main()

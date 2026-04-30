#!/usr/bin/env python3
"""
小红书爆款笔记分析脚本（吴大咪增强版）

基于 xhs-viral-analyzer 原版，融合吴大咪 5 套短视频方法论：
- 17 种开头方法论（黄金前3秒）
- 5 种脚本模型（结构化叙事）
- 混合钩子组合（2-3种方法论叠加）
- 口语化原创规范（去AI味）
- 评论区痛点/共鸣/提问 情绪词典

用法：
    python xhs_analyzer.py -i /tmp/xhs_result.json --keyword "关键词"
    python xhs_analyzer.py -i /tmp/xhs_result.json --keyword "关键词" --mode hooks
    python xhs_analyzer.py -i /tmp/xhs_result.json --keyword "关键词" --mode full
"""

import argparse
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime


# ============================================================
# 吴大咪方法论常量
# ============================================================

HOOK_FORMULAS = {
    "好奇": "提出引发强烈好奇心的问题，让人忍不住看下去",
    "恐吓": "利用损失厌恶，引起危机感",
    "痛点": "直接戳中观众当下的痛苦或烦恼",
    "震惊": "抛出极具争议或反常识的观点",
    "圈人群共鸣": "描述特定人群困扰，让观众觉得'这就是在说我'",
    "疑问": "提出观众心中已有的困惑",
    "逆向思维": "反常识，打破固有认知",
    "数据对比": "利用具体、意外的数据差造成冲击",
    "情感共鸣": "唤起内心深处的情感",
    "揭秘": "满足窥探欲，揭示内幕",
    "故事引入": "用具体场景或微故事开场",
    "反问": "用反问句强化语气，引发思考",
    "悬念": "话只说一半，暗示后面有大招",
    "对比": "通过强烈反差突显主题",
    "情景假设": "带入具体场景，引发想象",
    "成功案例": "用结果说话，提供确定性",
    "观众误解": "纠正错误认知，建立专家人设",
}

SCRIPT_MODELS = {
    "模型1-三段论": {
        "名称": "讲故事+唤起疑问+引导互动+给出答案",
        "结构": ["讲故事（相关经历）", "唤起疑问（好奇心）", "引导互动（点赞收藏）", "给出答案（三个理由支撑）"],
        "适用": "有个人经历可分享、能给出明确答案的选题",
    },
    "模型2-结果先行": {
        "名称": "输出结果+讲故事+确认承诺+给出答案+引导互动",
        "结构": ["输出结果（直接给结论）", "讲故事（解释背后经历）", "确认承诺（保证有价值信息）", "给出答案（关键步骤）", "引导互动"],
        "适用": "有成功案例或明确结果可展示的选题",
    },
    "模型3-冲突型": {
        "名称": "唤起选择+制造冲突+给出分析+说明原因+下结论",
        "结构": ["唤起选择（提出思考）", "制造冲突（不同观点）", "给出分析（利弊分析）", "说明原因（支持哪个）", "下结论"],
        "适用": "有争议性话题、需要表达观点的选题",
    },
    "模型4-痛点型": {
        "名称": "罗列痛点+制造认同+给出答案+聚合推荐",
        "结构": ["罗列痛点（3-5个）", "制造认同（分享经历引起共鸣）", "给出答案（解决方法）", "聚合推荐（相关资源）"],
        "适用": "能命中多个痛点、有解决方案可提供的选题",
    },
    "模型5-恐慌型": {
        "名称": "引起恐慌+给出论据+唤起需求+满足需求",
        "结构": ["引起恐慌（提示风险）", "给出论据（数据或事实）", "唤起需求（意识到问题）", "满足需求（解决策略）"],
        "适用": "涉及风险警示、紧迫感强的选题",
    },
}

MIXED_HOOK_COMBOS = [
    {"组合": "痛点 + 权威 + 价值", "逻辑": "直击困境 → 资历/数据背书 → 立刻可用的好处"},
    {"组合": "故事 + 反转 + 悬念", "逻辑": "真实片段带入 → 认知反转 → 留疑问"},
    {"组合": "数据/对比 + 趋势 + 价值", "逻辑": "数字冲突 → 行业趋势 → 可复用框架"},
    {"组合": "情绪 + 痛点 + 价值", "逻辑": "情绪共鸣开场 → 具体痛点命中 → 解决路径"},
    {"组合": "观点 + 权威 + 价值", "逻辑": "犀利判断 → 专业背书 → 明确实操收获"},
    {"组合": "好奇/悬念 + 权威 + 价值", "逻辑": "问题引子 → 可信来源 → 直接可用的方法"},
]

# 去AI味自检项
ANTI_AI_CHECKLIST = [
    "禁止使用\"首先、其次、最后\"，改用\"第一个、第二个、第三个\"",
    "禁止\"嘿/哈喽/大家好\"等打招呼的词开头",
    "禁止书面语：\"由此可见\"\"综上所述\"\"总之\"\"值得注意的是\"",
    "必须口语化：像朋友聊天一样自然，可以用\"你有没有发现\"\"其实我觉得\"",
    "禁止排比对仗、段尾升华、预告数量",
    "字数与原文相当，朗读时长控制在1-2分钟",
]


# ============================================================
# 数据解析（继承原版逻辑）
# ============================================================

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

    total_interaction = likes + collects * 2 + comments * 3

    fans = parse_count(note.get("fansCount", "50000"))
    if fans <= 0:
        fans = 10000

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
        fan_multiplier = 0.5

    return total_interaction * fan_multiplier


# ============================================================
# 评论区情绪词典分析（增强版）
# ============================================================

def extract_comment_themes(comments: list[dict]) -> dict:
    """提炼评论区核心心声，返回分类后的痛点/共鸣/问题/期待"""
    themes = {
        "pain_points": [],
        "resonance": [],
        "questions": [],
        "requests": [],
        "top_comments": [],
    }

    pain_keywords = ["好难", "不知道", "搞不懂", "踩坑", "失败", "困扰", "苦恼", "愁", "怎么办", "帮帮我", "焦虑", "崩溃", "太累", "做不到"]
    resonance_keywords = ["太对了", "同款", "一模一样", "就是我", "说的就是我", "哭了", "OMG", "真的", "超级", "救了", "说到心坎", "扎心"]
    question_keywords = ["怎么", "哪里", "多少钱", "链接", "是什么", "教程", "攻略", "求", "能不能教", "怎么做到的"]
    request_keywords = ["希望", "如果能", "能不能", "什么时候", "出一期", "拍一个", "分享一下", "求更新"]

    for comment in comments:
        text = comment.get("text", "")
        likes = parse_count(comment.get("likes", 0))
        if not text:
            continue

        if likes >= 50:
            themes["top_comments"].append({"text": text, "likes": likes})

        if any(kw in text for kw in pain_keywords):
            themes["pain_points"].append(text)
        if any(kw in text for kw in resonance_keywords):
            themes["resonance"].append(text)
        if any(kw in text for kw in question_keywords):
            themes["questions"].append(text)
        if any(kw in text for kw in request_keywords):
            themes["requests"].append(text)

    themes["top_comments"].sort(key=lambda x: x["likes"], reverse=True)
    themes["top_comments"] = themes["top_comments"][:5]

    return themes


# ============================================================
# 核心：融合方法论的选题方向生成
# ============================================================

def select_best_hooks(direction_type: str) -> list[str]:
    """根据选题方向类型，推荐最匹配的开头公式"""
    hook_map = {
        "痛点共鸣": ["痛点", "圈人群共鸣", "恐吓", "疑问", "情感共鸣"],
        "干货教程": ["好奇", "数据对比", "揭秘", "成功案例", "悬念"],
        "故事逆袭": ["故事引入", "情景假设", "震惊", "对比", "反问"],
    }
    return hook_map.get(direction_type, list(HOOK_FORMULAS.keys())[:5])


def select_best_script_model(direction_type: str) -> tuple[str, dict]:
    """根据选题方向类型，推荐最匹配的脚本模型"""
    model_map = {
        "痛点共鸣": "模型4-痛点型",
        "干货教程": "模型1-三段论",
        "故事逆袭": "模型2-结果先行",
    }
    key = model_map.get(direction_type, "模型1-三段论")
    return key, SCRIPT_MODELS[key]


def generate_topic_directions(notes: list[dict], keyword: str = "") -> list[dict]:
    """
    融合吴大咪方法论的选题方向生成器

    每个方向包含：
    - 选题方向（核心角度）
    - 推荐开头公式（从17种里精选）
    - 推荐脚本模型（从5种里匹配）
    - 混合钩子组合建议
    - 口播初稿框架（基于脚本模型结构）
    - 去AI味自检提示
    """
    all_titles = []
    all_contents = []
    all_pain_points = []
    all_questions = []
    all_resonance = []

    for note in notes:
        if note.get("title"):
            all_titles.append(note["title"])
        if note.get("content"):
            all_contents.append(note["content"])

        themes = extract_comment_themes(note.get("commentList", []))
        all_pain_points.extend(themes["pain_points"][:3])
        all_questions.extend(themes["questions"][:3])
        all_resonance.extend(themes["resonance"][:3])

    # 高频词分析
    all_text = " ".join(all_titles + all_contents)
    words = re.findall(r"[\u4e00-\u9fa5]{2,6}", all_text)
    word_freq = Counter(words).most_common(20)
    hot_words = [w for w, c in word_freq if c >= 2]

    directions = []

    # ====== 方向1：痛点共鸣型 ======
    hooks_1 = select_best_hooks("痛点共鸣")
    model_key_1, model_1 = select_best_script_model("痛点共鸣")
    combo_1 = MIXED_HOOK_COMBOS[3]  # 情绪+痛点+价值

    direction_1 = {
        "方向": f"痛点共鸣型 —— 直击{'、'.join(hot_words[:3]) if hot_words else keyword}的真实困境",
        "核心逻辑": "评论区暴露的痛点是选题金矿，展示'我也经历过'能迅速建立信任",
        "推荐开头公式": {k: HOOK_FORMULAS[k] for k in hooks_1[:3]},
        "推荐脚本模型": {"模型": model_key_1, "结构": model_1["结构"], "适用": model_1["适用"]},
        "混合钩子建议": combo_1,
        "推荐标题": [
            f"99%的人{keyword}都踩过的坑，你中了几个？",
            f"为什么你{keyword}总是事倍功半？看完这个你就懂了",
            f"我{keyword}失败了N次，才发现这个关键点...（亲测有效）",
        ],
        "口播初稿框架": f"""【开头·用「痛点」或「圈人群共鸣」公式，15秒内抓住注意力】

【第一段·罗列痛点】
把你在{keyword}这条路上遇到的3个最扎心的问题，用口语说出来。
参考评论区真实痛点：{'; '.join(all_pain_points[:2]) if all_pain_points else '（待补充真实评论）'}

【第二段·制造认同】
分享你自己或身边人的真实经历，让观众觉得"说的就是我"。
参考评论区共鸣：{'; '.join(all_resonance[:2]) if all_resonance else '（待补充真实评论）'}

【第三段·给出答案】
提供你验证过的解决方法，用"第一个...第二个...第三个..."的结构。

【收尾·引导互动】
"你遇到过这个问题吗？评论区告诉我" 或 "有问题问大咪，有问必答哦"
""",
        "参考爆款标题": all_titles[:3],
        "评论区真实弹药": {
            "痛点原话": all_pain_points[:3],
            "共鸣原话": all_resonance[:3],
        },
    }
    directions.append(direction_1)

    # ====== 方向2：干货教程型 ======
    hooks_2 = select_best_hooks("干货教程")
    model_key_2, model_2 = select_best_script_model("干货教程")
    combo_2 = MIXED_HOOK_COMBOS[2]  # 数据/对比+趋势+价值

    direction_2 = {
        "方向": f"干货教程型 —— 手把手教{keyword}，解答评论区高频问题",
        "核心逻辑": "评论区大量'怎么做''在哪里买'说明用户有明确需求，做成教程直接满足",
        "推荐开头公式": {k: HOOK_FORMULAS[k] for k in hooks_2[:3]},
        "推荐脚本模型": {"模型": model_key_2, "结构": model_2["结构"], "适用": model_2["适用"]},
        "混合钩子建议": combo_2,
        "推荐标题": [
            f"【完整教程】{keyword}从0到1，新手也能看懂",
            f"手把手教你{keyword}，超详细步骤（附资源）",
            f"{keyword}保姆级攻略，收藏备用！",
        ],
        "口播初稿框架": f"""【开头·用「好奇」或「数据对比」公式，15秒内抓住注意力】

【第一段·讲故事 / 抛结果】
直接说你用这个方法做到了什么结果，或者讲一个你踩坑后找到方法的经历。

【第二段·给出答案（步骤化）】
"第一个步骤...第二个步骤...第三个步骤..."
针对评论区高频问题：{'; '.join(all_questions[:2]) if all_questions else '（待补充真实提问）'}

【第三段·唤起疑问 + 引导互动】
"很多人问我{all_questions[0] if all_questions else '这个问题'}，答案是..."
"评论区告诉我，你最卡在哪一步？"

【收尾】
"有问题问大咪，有问必答哦"
""",
        "参考爆款标题": all_titles[3:6] if len(all_titles) > 3 else all_titles,
        "评论区真实弹药": {
            "高频提问": all_questions[:3],
        },
    }
    directions.append(direction_2)

    # ====== 方向3：故事逆袭型 ======
    hooks_3 = select_best_hooks("故事逆袭")
    model_key_3, model_3 = select_best_script_model("故事逆袭")
    combo_3 = MIXED_HOOK_COMBOS[1]  # 故事+反转+悬念

    direction_3 = {
        "方向": f"故事共鸣型 —— 用真实经历引发情感共鸣，低粉也能爆",
        "核心逻辑": "评论区'太对了''就是我'说明情感认同最易传播，低粉博主靠真实感突围",
        "推荐开头公式": {k: HOOK_FORMULAS[k] for k in hooks_3[:3]},
        "推荐脚本模型": {"模型": model_key_3, "结构": model_3["结构"], "适用": model_3["适用"]},
        "混合钩子建议": combo_3,
        "推荐标题": [
            f"我{keyword}这一年，有些话想对你说",
            f"那个坚持{keyword}3个月的人，现在怎么样了",
            f"说说我{keyword}路上的那些真实时刻",
        ],
        "口播初稿框架": f"""【开头·用「故事引入」或「情景假设」公式，直接从最有张力的时刻切入，不要自我介绍】

【第一段·输出结果】
先给一个让人惊讶的结果或转变（before/after 对比）。

【第二段·讲故事】
从一个具体的时间点和场景开始："我记得最清楚的一次是..."
越具体越有代入感——时间、地点、当时的心情、说了什么话。

【第三段·确认承诺 + 给出答案】
"后来我才明白..." 转折点出现，分享你的感悟和方法。

【收尾·开放性问题】
"你有没有类似的经历？" 或 "有问题问大咪，有问必答哦"
""",
        "参考爆款标题": all_titles[-3:] if len(all_titles) >= 3 else all_titles,
        "评论区真实弹药": {
            "共鸣原话": all_resonance[:3],
            "期待请求": [t for t in all_questions[:2]],
        },
    }
    directions.append(direction_3)

    return directions


# ============================================================
# 报告格式化（增强版）
# ============================================================

def format_report(notes: list[dict], directions: list[dict], keyword: str = "") -> str:
    """生成融合方法论的增强版分析报告"""
    lines = []
    lines.append(f"# 小红书爆款分析报告（吴大咪增强版）")
    lines.append(f"关键词：{keyword}  |  生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # 爆款笔记列表
    lines.append(f"## 📊 低粉爆款榜单（共 {len(notes)} 条）")
    lines.append("")
    lines.append("| # | 标题 | 点赞 | 收藏 | 评论 | 博主 | 粉丝数 | 链接 |")
    lines.append("|---|------|------|------|------|------|--------|------|")

    for i, note in enumerate(notes[:50], 1):
        title = note.get("title", "")[:25] + ("..." if len(note.get("title", "")) > 25 else "")
        likes = note.get("likes", note.get("likeCount", "0"))
        collects = note.get("collects", "-")
        comments = note.get("comments", "-")
        author = note.get("authorName", "-")
        fans = note.get("fansCount", "-")
        link = note.get("link", "")
        lines.append(f"| {i} | {title} | {likes} | {collects} | {comments} | {author} | {fans} | [查看]({link}) |")

    lines.append("")
    lines.append("💡 **搜索提示**：直接在小红书 App 或网页搜索标题查看详情。")
    lines.append("")

    # 选题方向（增强版）
    lines.append("## 🎯 三个选题方向（融合吴大咪方法论）")
    lines.append("")

    for i, d in enumerate(directions, 1):
        lines.append(f"### 方向 {i}：{d['方向']}")
        lines.append(f"**核心逻辑**：{d['核心逻辑']}")
        lines.append("")

        # 推荐开头公式
        lines.append("**🎣 推荐开头公式（从17种里精选）**：")
        for name, desc in d["推荐开头公式"].items():
            lines.append(f"- **{name}**：{desc}")
        lines.append("")

        # 推荐脚本模型
        model_info = d["推荐脚本模型"]
        lines.append(f"**📝 推荐脚本模型：{model_info['模型']}**")
        lines.append(f"结构：{'→'.join(model_info['结构'])}")
        lines.append(f"适用：{model_info['适用']}")
        lines.append("")

        # 混合钩子
        combo = d["混合钩子建议"]
        lines.append(f"**🎛 混合钩子组合：{combo['组合']}**")
        lines.append(f"逻辑：{combo['逻辑']}")
        lines.append("")

        # 推荐标题
        lines.append("**推荐标题**（三选一或组合）：")
        for title in d["推荐标题"]:
            lines.append(f"- {title}")
        lines.append("")

        # 口播初稿
        lines.append("**🎙️ 口播初稿框架**：")
        lines.append("```")
        lines.append(d["口播初稿框架"])
        lines.append("```")
        lines.append("")

        # 评论区弹药
        if d.get("评论区真实弹药"):
            lines.append("**💣 评论区真实弹药**（可直接嵌入脚本）：")
            for label, items in d["评论区真实弹药"].items():
                if items:
                    lines.append(f"- {label}：")
                    for item in items[:3]:
                        lines.append(f"  - 「{item}」")
            lines.append("")

        # 参考爆款
        if d.get("参考爆款标题") and any(d["参考爆款标题"]):
            lines.append("**参考爆款标题**（来自本次分析）：")
            for ref in d["参考爆款标题"]:
                if ref:
                    lines.append(f"- {ref}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 方法论速查附录
    lines.append("## 📚 附录：吴大咪方法论速查")
    lines.append("")
    lines.append("### 17种开头公式")
    lines.append("| # | 公式 | 说明 |")
    lines.append("|---|------|------|")
    for i, (name, desc) in enumerate(HOOK_FORMULAS.items(), 1):
        lines.append(f"| {i} | {name} | {desc} |")
    lines.append("")

    lines.append("### 5种脚本模型")
    for key, model in SCRIPT_MODELS.items():
        lines.append(f"- **{key}**：{'→'.join(model['结构'])} | 适用：{model['适用']}")
    lines.append("")

    lines.append("### ⚠️ 去AI味自检清单")
    for item in ANTI_AI_CHECKLIST:
        lines.append(f"- {item}")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="小红书爆款笔记分析器（吴大咪增强版）")
    parser.add_argument("-i", "--input", required=True, help="抓取结果 JSON 文件")
    parser.add_argument("--keyword", default="", help="搜索关键词")
    parser.add_argument("--max-fans", type=int, default=50000, help="低粉阈值（默认5万）")
    parser.add_argument("--min-likes", type=int, default=500, help="最小点赞数（默认500）")
    parser.add_argument("-o", "--output", help="输出文件路径（默认打印到终端）")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        notes = raw
    elif isinstance(raw, dict):
        notes = raw.get("data", raw.get("notes", [raw]))
    else:
        notes = []

    print(f"📥 读取到 {len(notes)} 条笔记")

    # 过滤低粉爆款
    filtered = []
    missing_fans_count = 0
    
    for note in notes:
        if "fansCount" not in note or note.get("fansCount") == "":
            missing_fans_count += 1
            
        fans = parse_count(note.get("fansCount", "0"))
        likes = parse_count(note.get("likes", note.get("likeCount", "0")))

        if fans == 0:
            if likes >= args.min_likes:
                filtered.append(note)
        elif fans <= args.max_fans and likes >= args.min_likes:
            filtered.append(note)

    if missing_fans_count > 0:
        print(f"⚠️  警告: 发现 {missing_fans_count} 条笔记没有粉丝数数据。")
        print(f"   (这些笔记被暂时当作低粉处理。为了获得真实的低粉爆款，请在抓取时使用 --deep-fetch 参数进行二次探测)")
        
    filtered.sort(key=score_virality, reverse=True)
    print(f"✅ 筛选出 {len(filtered)} 条低粉爆款候选（筛选门槛: 粉丝<{args.max_fans}, 点赞>{args.min_likes}）")

    if not filtered:
        print("⚠️  没有符合条件的笔记，使用全部数据进行分析...")
        filtered = sorted(notes, key=score_virality, reverse=True)

    # 生成选题方向（融合方法论版）
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

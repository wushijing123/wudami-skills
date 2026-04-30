#!/usr/bin/env python3
"""
小红书账号数据分析脚本
读取抓取的账号数据，进行统计分析和结构化提炼，
输出用于生成完整拆解报告的结构化数据。
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from typing import Optional

try:
    import requests
    from playwright.sync_api import sync_playwright
except ImportError:
    pass  # 分析脚本不需要 playwright


def parse_count(text: str) -> int:
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


def extract_interact_nums(interact_text: str) -> dict:
    """从互动文本中提取点赞/收藏/评论数"""
    result = {"likes": 0, "collects": 0, "comments": 0}

    # 小红书通常按 点赞 · 收藏 · 评论 顺序排列
    nums = re.findall(r"(\d+[\d.,]*)", interact_text)
    # 过滤掉太小或太大的数（可能是时间戳等干扰数据）
    nums = [n for n in nums if 0 <= parse_count(n) < 10_000_000]

    if len(nums) >= 1:
        result["likes"] = parse_count(nums[0])
    if len(nums) >= 2:
        result["collects"] = parse_count(nums[1])
    if len(nums) >= 3:
        result["comments"] = parse_count(nums[2])

    return result


def analyze_account(data: dict) -> dict:
    """对账号数据进行统计分析"""
    account = data.get("account", {})
    notes = data.get("notes", [])

    fans_count = parse_count(account.get("fansCount", "0"))

    # 解析每条笔记的互动数据
    # scraper 新版直接提供 likes 字段（已解析），兼容旧版 interactText
    analyzed_notes = []
    for note in notes:
        # 优先用新字段 likes，回退到旧版 interactText 解析
        if note.get("likes") and str(note["likes"]).strip() not in ("", "0"):
            likes = parse_count(str(note["likes"]))
        else:
            likes = extract_interact_nums(note.get("interactText", ""))["likes"]

        # 小红书主页卡片架构上不提供收藏/评论数，留0并标注
        note_analysis = {
            "title": note.get("title", ""),
            "noteUrl": note.get("noteUrl", ""),
            "cover": note.get("coverImg", note.get("cover", "")),
            "isVideo": note.get("isVideo", False),
            "dateText": note.get("dateText", ""),
            "parsedDate": note.get("parsedDate"),
            "likes": likes,
            "collects": 0,   # 主页卡片不展示，需进详情页获取
            "comments": 0,   # 主页卡片不展示，需进详情页获取
            "totalInteraction": likes,
        }
        analyzed_notes.append(note_analysis)

    # 排序：按总互动量
    analyzed_notes.sort(key=lambda x: x["totalInteraction"], reverse=True)

    # 基础统计
    if analyzed_notes:
        all_likes = [n["likes"] for n in analyzed_notes]
        all_collects = [n["collects"] for n in analyzed_notes]
        all_comments = [n["comments"] for n in analyzed_notes]
        all_total = [n["totalInteraction"] for n in analyzed_notes]

        stats = {
            "totalNotes": len(analyzed_notes),
            "avgLikes": sum(all_likes) // len(all_likes) if all_likes else 0,
            "avgCollects": sum(all_collects) // len(all_collects) if all_collects else 0,
            "avgComments": sum(all_comments) // len(all_comments) if all_comments else 0,
            "maxLikes": max(all_likes) if all_likes else 0,
            "topNote": analyzed_notes[0] if analyzed_notes else {},
        }
    else:
        stats = {"totalNotes": 0, "avgLikes": 0, "avgCollects": 0, "avgComments": 0, "maxLikes": 0, "topNote": {}}

    # 内容类型分布
    video_count = sum(1 for n in analyzed_notes if n["isVideo"])
    image_count = len(analyzed_notes) - video_count

    # 近30天 vs 更早（如果解析出日期）
    recent_count = sum(1 for n in analyzed_notes if n.get("parsedDate"))
    # 注意：parsedDate 解析不一定完整，这里只是提示性数据

    # 爆款定义：点赞 > 平均3倍
    virality_threshold = stats["avgLikes"] * 3 if stats["avgLikes"] > 0 else 1000
    viral_notes = [n for n in analyzed_notes if n["likes"] >= virality_threshold]

    # 选题关键词提取（从标题）
    all_titles = [n["title"] for n in analyzed_notes if n["title"]]
    topic_keywords = extract_keywords([t for t in all_titles])

    # 新增：预先做精准的数据聚类（防大模型估算幻觉）
    # 关键词簇定义（根据小红书常见痛点划分）
    dim1_kws = ['失业', '网站', '破产', '倒闭', '离职', '裸辞', '裁员', '副业']
    dim2_kws = ['流量', '限流', '技巧', '发布', '涨', '起号', '眼睛', '笔记', '数据', '变现', '规则']
    dim3_kws = ['AI', 'Ai', '神器', 'deepseek', 'Claude', 'OpenClaw', '工具', '自动', 'GPT']
    dim4_kws = ['电商', '货源', '薯店', '1688', '带货', '搞钱', '搞💰', '拼多多', '淘宝']

    def categorize(notes_list, keywords):
        return [n for n in notes_list if any(k.lower() in n.get('title', '').lower() for k in keywords)]

    dim1_notes = categorize(analyzed_notes, dim1_kws)
    rem2 = [n for n in analyzed_notes if n not in dim1_notes]
    dim2_notes = categorize(rem2, dim2_kws)
    rem3 = [n for n in rem2 if n not in dim2_notes]
    dim3_notes = categorize(rem3, dim3_kws)
    rem4 = [n for n in rem3 if n not in dim3_notes]
    dim4_notes = categorize(rem4, dim4_kws)
    other_notes = [n for n in rem4 if n not in dim4_notes]

    def stat_dim(dim_list, name):
        cnt = len(dim_list)
        if cnt == 0: return {"name": name, "count": 0, "ratio": 0, "avgLikes": 0, "topTitle": ""}
        avg = sum(n["likes"] for n in dim_list) // cnt
        highest = max(dim_list, key=lambda x: x["likes"])
        return {
            "name": name,
            "count": cnt,
            "ratio": round(cnt / len(analyzed_notes) * 100),
            "avgLikes": avg,
            "topTitle": highest["title"],
            "topLikes": highest["likes"]
        }

    dimensions = [
        stat_dim(dim1_notes, "情绪共鸣/资源盘点类"),
        stat_dim(dim2_notes, "平台机制/运营技巧类"),
        stat_dim(dim3_notes, "AI工具/提效实操类"),
        stat_dim(dim4_notes, "电商/带货/变现类"),
        stat_dim(other_notes, "其他/日常类")
    ]
    # 按数量排序维度
    dimensions.sort(key=lambda x: x["count"], reverse=True)

    # 互动率估算（点赞+收藏+评论 / 粉丝数）
    if fans_count > 0 and len(analyzed_notes) > 0:
        avg_interaction = sum(n["totalInteraction"] for n in analyzed_notes) / len(analyzed_notes)
        engagement_rate = avg_interaction / fans_count * 100
    else:
        engagement_rate = None

    return {
        "account": {
            "nickname": account.get("nickname", ""),
            "desc": account.get("desc", ""),
            "fansCount": fans_count,
            "followingCount": parse_count(account.get("followingCount", "")),
            "likeCount": parse_count(account.get("likeCount", "")),
            "postsCount": len(notes),  # 主页不直接给笔记数，用抓取数量代替
            "ipLocation": account.get("ipLocation", ""),
            "verifyInfo": account.get("verifyInfo", ""),
            "pageUrl": account.get("pageUrl", data.get("sourceUrl", "")),
        },
        "notes": analyzed_notes,
        "stats": stats,
        "contentType": {
            "video": video_count,
            "image": image_count,
            "videoRatio": round(video_count / len(analyzed_notes), 2) if analyzed_notes else 0,
        },
        "viralNotes": viral_notes[:5],  # Top 5 viral notes
        "topicKeywords": topic_keywords,
        "dimensions": dimensions,
        "engagementRate": round(engagement_rate, 2) if engagement_rate is not None else None,
        "scrapedAt": data.get("scrapedAt", ""),
        "sourceUrl": data.get("sourceUrl", ""),
    }


def extract_keywords(titles: list[str], top_n: int = 15) -> list[dict]:
    """从标题中提取高频词和短语"""
    stop_words = {"的", "了", "是", "我", "你", "他", "她", "在", "和", "与", "及",
                  "这", "那", "有", "没有", "不", "也", "就", "都", "很", "太",
                  "一个", "什么", "怎么", "如何", "为什么", "可以", "能", "要", "吗",
                  "吧", "呢", "啊", "哦", "呀", "嘛", "哦", "啦", "～", "..."}

    # 提取2-4字的词
    words = []
    for title in titles:
        title = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", " ", title)
        for length in [2, 3, 4]:
            for i in range(len(title) - length + 1):
                word = title[i:i+length]
                if word not in stop_words and not word.isdigit():
                    words.append(word)

    # 统计词频
    word_freq = Counter(words).most_common(top_n * 2)
    # 去重（短词被长词包含的情况）
    seen = set()
    result = []
    for word, freq in word_freq:
        if len(result) >= top_n:
            break
        skip = False
        for existing in result:
            if existing["word"] in word:
                skip = True
                break
        if not skip:
            result.append({"word": word, "freq": freq})

    return result[:top_n]


def generate_report(data: dict) -> str:
    """生成 Markdown 格式的账号拆解报告"""
    account = data["account"]
    stats = data["stats"]
    notes = data["notes"]
    topics = data.get("topicKeywords", [])
    viral = data.get("viralNotes", [])
    ct = data.get("contentType", {})

    lines = []
    lines.append(f"# {account['nickname']} 账号拆解报告")
    lines.append(f"_抓取时间：{data.get('scrapedAt', '')[:10]} | 数据来源：{data.get('sourceUrl', '')}_")
    lines.append("")

    # 账号基础信息
    lines.append("## 一、账号速览")
    lines.append(f"| 项目 | 数据 |")
    lines.append(f"|------|------|")
    lines.append(f"| 昵称 | {account['nickname']} |")
    lines.append(f"| 粉丝数 | {account['fansCount']:,} |")
    lines.append(f"| 笔记数 | {account['postsCount'] or stats['totalNotes']} |")
    if account['ipLocation']:
        lines.append(f"| IP属地 | {account['ipLocation']} |")
    if account['verifyInfo']:
        lines.append(f"| 认证 | {account['verifyInfo']} |")
    if data.get('engagementRate') is not None:
        lines.append(f"| 估算互动率 | {data['engagementRate']}% |")
    lines.append("")
    if account['desc']:
        lines.append(f"**简介**：`{account['desc']}`")
        lines.append("")

    # 内容类型
    lines.append("## 二、内容类型")
    lines.append(f"- 图文笔记：{ct.get('image', 0)} 条")
    lines.append(f"- 视频笔记：{ct.get('video', 0)} 条")
    if ct.get('videoRatio', 0) > 0:
        lines.append(f"- 视频占比：{ct.get('videoRatio', 0)*100:.0f}%")
    lines.append("")

    # 互动统计
    lines.append("## 三、互动数据统计（抓取的笔记）")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 抓取笔记数 | {stats['totalNotes']} |")
    lines.append(f"| 平均点赞 | {stats['avgLikes']:,} |")
    lines.append(f"| 平均收藏 | {stats['avgCollects']:,} |")
    lines.append(f"| 平均评论 | {stats['avgComments']:,} |")
    if stats['maxLikes']:
        lines.append(f"| 最高点赞 | {stats['maxLikes']:,} |")
    lines.append("")

    # Top 笔记
    if notes:
        lines.append("## 四、Top 10 高互动笔记")
        lines.append("")
        lines.append("| # | 标题 | 点赞 | 收藏 | 评论 | 类型 |")
        lines.append("|---|------|------|------|------|------|")
        for i, n in enumerate(notes[:10], 1):
            title = n["title"][:30] + ("..." if len(n["title"]) > 30 else "")
            lines.append(f"| {i} | {title} | {n['likes']:,} | {n['collects']:,} | {n['comments']:,} | {'视频' if n['isVideo'] else '图文'} |")
        lines.append("")

    # 爆款笔记
    if viral:
        lines.append("## 五、爆款笔记（点赞 > 平均3倍）")
        lines.append("")
        for n in viral[:5]:
            lines.append(f"**{n['title']}**")
            lines.append(f"- 点赞 {n['likes']:,} | 收藏 {n['collects']:,} | 评论 {n['comments']:,}")
            lines.append("")

    # 选题关键词
    if topics:
        lines.append("## 六、选题高频词")
        kw_parts = [f"`{t['word']}`({t['freq']}次)" for t in topics[:10]]
        lines.append("、".join(kw_parts))
        lines.append("")

    # 精准聚类数据输出
    if data.get("dimensions"):
        lines.append("## 七、精准聚类数据（严禁篡改占比）")
        lines.append("> ⚠️ **AI 核心约束**：以下为 Python 脚本精确计算的内容维度数据，请在输出「选题维度拆解」模块时，**1:1 照搬此数据，严禁自行估算占比和均赞！**")
        lines.append("")
        for d in data["dimensions"]:
            if d["count"] > 0:
                lines.append(f"- **{d['name']}**：{d['count']} 篇（占比 {d['ratio']}%） | 平均点赞：{d['avgLikes']:,} | 爆款代表：《{d['topTitle']}》（{d['topLikes']:,}赞）")
        lines.append("")

    lines.append("---")
    lines.append("## 🤖 执行给大模型的防幻觉约束语（System Prompt 补丁）")
    lines.append("```markdown")
    lines.append("1. **时间线防幻觉**：因为本次抓取缺失发布日期，在写【三、账号发展路径】时，禁止捏造时间线，必须写明是“基于选题聚类反推”的发展阶段。")
    lines.append("2. **降维分析声明**：由于小红书反爬拦截，本次抓取缺失了评论数和收藏数，在【二、账号速览】中必须公开声明“本次爆款评判唯一标准为绝对点赞量”。")
    lines.append("3. **剪辑视角排雷**：本次抓取仅获取了标题和封面图片，未获取视频正文内容，在【六、内容形式分析-剪辑】部分禁止臆想“镜头语言/配乐跳跃”，仅能从外排封面密度倒推。")
    lines.append("4. **严格遵照比例**：在【七、选题维度拆解】模块中，必须绝对参考上面提供的“精准聚类数据”，按占比从高到低排列，不允许使用“大约”、“估计”等词汇改变原始数值。")
    lines.append("```")
    lines.append("")
    lines.append("> 以上为自动化抓取+深度前置分析结果。请直接将以上数据连同 `06-账号深度拆解-终版` Prompt 喂给 AI 以生成最终的 11 段无幻觉报告。")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="小红书账号数据分析")
    parser.add_argument("-i", "--input", required=True, help="抓取结果 JSON 文件")
    parser.add_argument("-o", "--output", help="输出 Markdown 文件（可选）")
    parser.add_argument("-j", "--json", help="输出结构化 JSON（可选）")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = analyze_account(data)
    print(f"📊 分析完成：{result['account']['nickname']}，{result['stats']['totalNotes']} 条笔记")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"💾 结构化数据已保存到: {args.json}")

    if args.output:
        report = generate_report(result)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"📄 Markdown 报告已保存到: {args.output}")
    else:
        print("\n" + generate_report(result))


if __name__ == "__main__":
    main()

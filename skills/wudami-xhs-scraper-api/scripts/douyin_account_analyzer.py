#!/usr/bin/env python3
"""
抖音账号数据分析脚本
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

import subprocess

def auto_install_jieba():
    try:
        import jieba
        return True
    except ImportError:
        print("📦 正在自动安装必需的依赖库 (jieba)...")
        try:
            cmd = [sys.executable, "-m", "pip", "install", "jieba", "--quiet"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0 and 'externally-managed-environment' in res.stderr:
                # 兼容 Mac Homebrew / Python 3.11+ 的环境策略
                cmd.append("--break-system-packages")
                subprocess.run(cmd, capture_output=True)
            import jieba
            print("✅ jieba 安装成功！")
            return True
        except Exception as e:
            print(f"⚠️ 自动安装 jieba 失败，词云解析将被跳过。错误: {e}")
            return False

HAS_JIEBA = auto_install_jieba()
if HAS_JIEBA:
    import jieba

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

    # 抖音通常按 点赞 · 收藏 · 评论 顺序排列
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

    # 解析每条视频的互动数据
    # scraper 新版直接提供 likes 字段（已解析），兼容旧版 interactText
    analyzed_notes = []
    for note in notes:
        # 优先用新字段 likes，回退到旧版 interactText 解析
        if note.get("likes") and str(note["likes"]).strip() not in ("", "0"):
            likes = parse_count(str(note["likes"]))
        else:
            likes = extract_interact_nums(note.get("interactText", ""))["likes"]

        # 抖音主页卡片架构上不提供收藏/评论数，留0并标注
        note_analysis = {
            "title": note.get("title", ""),
            "noteUrl": note.get("noteUrl", ""),
            "cover": note.get("coverImg", ""),
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

    all_titles = [n["title"] for n in analyzed_notes if n["title"]]
    topic_keywords = extract_keywords([t for t in all_titles], top_n=15)

    # 五维词云分析（需要 jieba）
    account_nickname = data["account"].get("nickname", "") if "account" in data else ""
    wordcloud_data = analyze_wordcloud(all_titles, nickname=account_nickname)

    # 不再做关键词维度聚类，改为输出全量视频标题清单供 AI 做语义维度归类
    # AI 会基于内容主题（而非关键词）给出 4-6 个内容特有的维度名
    dimensions = []  # 留空，由 AI 在报告中自行分类

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
            "postsCount": len(notes),  # 主页不直接给视频数，用抓取数量代替
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
        "wordcloud": wordcloud_data,
        "engagementRate": round(engagement_rate, 2) if engagement_rate is not None else None,
        "scrapedAt": data.get("scrapedAt", ""),
        "sourceUrl": data.get("sourceUrl", ""),
    }


def extract_keywords(titles: list[str], top_n: int = 15) -> list[dict]:
    """从标题中提取高频词和短语（fallback：无 jieba 时用 n-gram）"""
    stop_words = {"的", "了", "是", "我", "你", "他", "她", "在", "和", "与", "及",
                  "这", "那", "有", "没有", "不", "也", "就", "都", "很", "太",
                  "一个", "什么", "怎么", "如何", "为什么", "可以", "能", "要", "吗",
                  "吧", "呢", "啊", "哦", "呀", "嘛", "哦", "啦", "～", "..."}

    words = []
    for title in titles:
        title = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", title)
        for length in [2, 3, 4]:
            for i in range(len(title) - length + 1):
                word = title[i:i+length]
                if word not in stop_words and not word.isdigit() and len(word.strip()) > 1:
                    words.append(word)

    word_freq = Counter(words).most_common(top_n * 2)
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


def analyze_wordcloud(titles: list[str], nickname: str = "") -> dict:
    """
    基于 jieba 分词的五维词云分析。
    返回结构化数据：global_top / crowd / emotion / action / scene 各维度 TOP 词频。
    如果 jieba 不可用，返回空字典。
    """
    if not HAS_JIEBA or not titles:
        return {}

    # 母婴领域自定义词典
    custom_words = [
        '宝宝', '新手爸妈', '新手妈妈', '辅食', '感统', '月龄', '睡眠',
        '带娃', '养娃', '早教', '育儿', '宝妈', '脊柱', '大运动',
        '扶站', '翻身', '抬头', '爬行', '如厕', '戒奶', '断奶',
        '夜奶', '哺乳', '产后', '坐月子', '红黑榜', '一锅蒸',
        '辅食机', '遛娃', '踩坑', '避坑', '拼接床', '睡袋',
        '安全座椅', '推车', '背带', '腰凳', '头型', '圆头',
        '吐奶', '湿疹', '黄疸', '肠绞痛', '好物', '测评',
        '亲测', '自查', '攻略', '干货', '托举', '女儿', '儿子',
    ]
    for w in custom_words:
        jieba.add_word(w)

    stopwords = set('的了是在不个有这我你他她它们都也就和与及还以要会被让把给用到过能好很大小多少上下前后左右中内外来去做说看找买'
                    '一二三四五六七八九十百千万个月天年次岁件种样些什么怎么为什么如何哪些这些那些可以需要应该')
                    
    # 动态加入该账号的昵称作为停用词，防止自己的名字霸榜词云
    if nickname:
        stopwords.add(nickname)
        stopwords.add(nickname.lower())
        for part in nickname.split():
            stopwords.add(part)
            stopwords.add(part.lower())
        # 对于类似 dontbesilent 的名，连在一起也会被算
        clean_nick = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', nickname)
        if clean_nick: stopwords.add(clean_nick.lower())

    all_words = []
    for t in titles:
        cleaned = re.sub(r'[^\u4e00-\u9fff0-9a-zA-Z]', ' ', t).strip()
        words = jieba.lcut(cleaned)
        for w in words:
            w = w.strip()
            if len(w) >= 2 and w not in stopwords:
                all_words.append(w)

    freq = Counter(all_words)

    # 五个维度的种子词集合
    dim_crowd = {'宝宝', '新手', '妈妈', '爸妈', '宝妈', '新手爸妈', '新手妈妈',
                 '老人', '女儿', '儿子', '孩子', '婴儿', '新生儿', '奶爸', '爷爷奶奶', '姥姥姥爷'}
    dim_emotion = {'错误', '避坑', '踩坑', '自查', '别买', '警惕', '注意', '当心',
                   '后悔', '震惊', '没想到', '居然', '竟然', '真的', '太', '超', '绝了',
                   '赞', '推荐', '必须', '一定', '千万', '别再', '停止', '赶紧', '快',
                   '神器', '天花板', '亲测', '实测', '干货', '红黑榜', '冤枉钱'}
    dim_action = {'引导', '训练', '教', '学', '做', '选', '买', '用', '吃', '喂',
                  '睡', '洗', '换', '调整', '纠正', '预防', '改善', '促进', '锻炼',
                  '扶站', '翻身', '抬头', '爬行', '如厕', '断奶', '戒奶', '哺乳',
                  '按摩', '拍嗝', '搞定', '解决', '自查', '测评', '托举'}
    dim_scene = {'在家', '居家', '出门', '出行', '旅行', '早教', '医院', '打疫苗',
                 '辅食', '睡眠', '洗澡', '换尿布', '大运动', '感统', '游戏',
                 '夜奶', '坐月子', '产后', '哺乳', '溢奶', '吐奶'}

    def classify(word):
        cats = []
        if word in dim_crowd: cats.append('人群词')
        if word in dim_emotion: cats.append('情绪钩子词')
        if word in dim_action: cats.append('动作指令词')
        if word in dim_scene: cats.append('场景/需求词')
        return cats if cats else ['通用高频词']

    cat_freq = {'人群词': Counter(), '情绪钩子词': Counter(), '动作指令词': Counter(), '场景/需求词': Counter()}
    for word, count in freq.items():
        for c in classify(word):
            if c in cat_freq:
                cat_freq[c][word] = count

    return {
        'global_top': [{'word': w, 'count': c} for w, c in freq.most_common(10)],
        'crowd': [{'word': w, 'count': c} for w, c in cat_freq['人群词'].most_common(5)],
        'emotion': [{'word': w, 'count': c} for w, c in cat_freq['情绪钩子词'].most_common(5)],
        'action': [{'word': w, 'count': c} for w, c in cat_freq['动作指令词'].most_common(5)],
        'scene': [{'word': w, 'count': c} for w, c in cat_freq['场景/需求词'].most_common(5)],
    }


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
    lines.append(f"| 视频数 | {account['postsCount'] or stats['totalNotes']} |")
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
    lines.append(f"- 图文视频：{ct.get('image', 0)} 条")
    lines.append(f"- 视频视频：{ct.get('video', 0)} 条")
    if ct.get('videoRatio', 0) > 0:
        lines.append(f"- 视频占比：{ct.get('videoRatio', 0)*100:.0f}%")
    lines.append("")

    # 互动统计
    lines.append("## 三、互动数据统计（抓取的视频）")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 抓取视频数 | {stats['totalNotes']} |")
    lines.append(f"| 平均点赞 | {stats['avgLikes']:,} |")
    lines.append(f"| 平均收藏 | {stats['avgCollects']:,} |")
    lines.append(f"| 平均评论 | {stats['avgComments']:,} |")
    if stats['maxLikes']:
        lines.append(f"| 最高点赞 | {stats['maxLikes']:,} |")
    lines.append("")

    # Top 视频
    if notes:
        lines.append("## 四、Top 10 高互动视频")
        lines.append("")
        lines.append("| # | 标题 | 点赞 | 收藏 | 评论 | 类型 |")
        lines.append("|---|------|------|------|------|------|")
        for i, n in enumerate(notes[:10], 1):
            title = n["title"][:30] + ("..." if len(n["title"]) > 30 else "")
            lines.append(f"| {i} | {title} | {n['likes']:,} | {n['collects']:,} | {n['comments']:,} | {'视频' if n['isVideo'] else '图文'} |")
        lines.append("")

    # 爆款视频
    if viral:
        lines.append("## 五、爆款视频（点赞 > 平均3倍）")
        lines.append("")
        for n in viral[:5]:
            lines.append(f"**{n['title']}**")
            lines.append(f"- 点赞 {n['likes']:,} | 收藏 {n['collects']:,} | 评论 {n['comments']:,}")
            lines.append("")

    # 选题关键词
    if topics:
        lines.append("## 六、选题高频词")
        kw_parts = [f"`{t['word']}`({t['freq']}次)" for t in topics[:15]]
        lines.append("、".join(kw_parts))
        lines.append("")

    # 五维词云分析
    wc = data.get("wordcloud", {})
    if wc:
        lines.append("## 六-B、五维词云分析（jieba 分词预计算）")
        lines.append('> ⚠️ **AI 核心约束**：以下数据由 Python jieba 分词精确计算，写【六、内容形式分析-④词云分析】时必须 1:1 引用，禁止自行估算词频。')
        lines.append("")

        def fmt_list(items):
            return '、'.join([f'{d["word"]}({d["count"]}次)' for d in items])

        lines.append(f'**全局高频词 TOP 10**：{fmt_list(wc.get("global_top", []))}')
        lines.append("")
        lines.append(f'**人群词**（精准锁定谁在看）：{fmt_list(wc.get("crowd", []))}')
        lines.append("")
        lines.append(f'**情绪钩子词**（制造点击冲动）：{fmt_list(wc.get("emotion", []))}')
        lines.append("")
        lines.append(f'**动作指令词**（降低执行门槛）：{fmt_list(wc.get("action", []))}')
        lines.append("")
        lines.append(f'**场景/需求词**（覆盖哪些战场）：{fmt_list(wc.get("scene", []))}')
        lines.append("")

    # 全量视频标题清单（供 AI 做语义维度归类）
    lines.append("## 七、全量视频清单（供语义维度归类）")
    lines.append('> ⚠️ **AI 核心约束**：Python 不再预设维度名称。请阅读以下全部标题，自行归纳 4-6 个该账号特有的内容维度，每条视频只归入一个维度。维度名必须具体到该账号内容，禁止使用万能模板标签。')
    lines.append("")
    for i, n in enumerate(notes, 1):
        date_str = f"[{n.get('dateText', '')}]" if n.get('dateText') else ""
        lines.append(f"{i}. {date_str}[{n['likes']:,}赞] {n['title']}")
    lines.append("")
    lines.append(f"**共 {len(notes)} 条 | 平均点赞 {stats['avgLikes']:,}**")
    lines.append("")

    lines.append("---")
    lines.append("## 🤖 执行给大模型的防幻觉约束语（System Prompt 补丁）")
    lines.append("```markdown")
    lines.append('1. **时间线编年史**：各项清单已提供精准的发布日期。必须深度追踪点赞潮汐与时间轴的关系，据此划分「前期、中期、后期」，严禁脱离时间序列做静态猜测。')
    lines.append('2. **降维分析声明**：由于抖音反爬拦截缺失了评论数和收藏数，在账号速览中必须公开声明本次爆款评判唯一标准为绝对点赞量。')
    lines.append('3. **剪辑视角排雷**：仅获取了标题和封面图片，未获取视频正文内容，禁止臆想镜头语言/配乐跳跃，仅能从外排封面密度倒推。')
    lines.append('4. **选题维度命名约束**：在选题维度拆解中，基于全量视频标题进行语义归类，给出 4-6 个内容特有的维度名称。每个维度包含：维度名、视频数量 N 篇（占比 X%）、平均点赞、代表性视频标题、战略意图与核心痛点。禁止使用万能模板标签。')
    lines.append("```")
    lines.append("")
    lines.append('> 以上为自动化抓取+深度前置分析结果。AI 将基于全量标题进行语义维度归类，输出最终的 11 段深度报告。')

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="抖音账号数据分析")
    parser.add_argument("-i", "--input", required=True, help="抓取结果 JSON 文件")
    parser.add_argument("-o", "--output", help="输出 Markdown 文件（可选）")
    parser.add_argument("-j", "--json", help="输出结构化 JSON（可选）")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = analyze_account(data)
    print(f"📊 分析完成：{result['account']['nickname']}，{result['stats']['totalNotes']} 条视频")

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

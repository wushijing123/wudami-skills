#!/usr/bin/env python3
"""
小红书账号信息抓取脚本
连接 CDP 浏览器，抓取账号主页信息 + 滚动加载笔记列表（标题/日期/互动数据）
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

try:
    import requests
    from playwright.sync_api import sync_playwright
except ImportError:
    print("缺少依赖，请运行：pip install playwright requests && playwright install chromium")
    sys.exit(1)


def connect_to_chrome(cdp_url: str) -> str:
    try:
        resp = requests.get(f"{cdp_url}/json/version", timeout=5)
        return resp.json()["webSocketDebuggerUrl"]
    except Exception as e:
        print(f"无法连接到 Chrome: {e}")
        print(f"请确保 Chrome 已启动并监听 {cdp_url}")
        sys.exit(1)


def get_or_create_page(playwright, ws_url: str, target_url: Optional[str] = None):
    browser = playwright.chromium.connect_over_cdp(ws_url)
    context = browser.contexts[0]
    pages = [p for p in context.pages if "xiaohongshu.com" in p.url or "xhslink.com" in p.url]
    if pages:
        page = pages[0]
        if target_url:
            page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
        return page, browser

    page = context.new_page()
    page.goto(target_url or "https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=15000)
    time.sleep(2)
    return page, browser


def parse_count(text: str) -> int:
    if not text:
        return 0
    text = text.strip().replace(",", "").replace(" ", "")
    if "万" in text:
        try:
            return int(float(text.replace("万", "")) * 10000)
        except ValueError:
            return 0
    if "亿" in text:
        try:
            return int(float(text.replace("亿", "")) * 100000000)
        except ValueError:
            return 0
    try:
        return int(text)
    except ValueError:
        return 0


def parse_relative_date(text: str) -> Optional[str]:
    now = datetime.now()
    text = text.strip()
    if "刚刚" in text or "刚才" in text:
        return now.strftime("%Y-%m-%d")
    m = re.search(r"(\d+)分钟前", text)
    if m:
        return (now - timedelta(minutes=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.search(r"(\d+)小时前", text)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).strftime("%Y-%m-%d")
    if "昨天" in text:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    m = re.search(r"(\d+)天前", text)
    if m:
        return (now - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.search(r"(\d+)[周星期]前", text)
    if m:
        return (now - timedelta(weeks=int(m.group(1)))).strftime("%Y-%m-%d")
    for fmt in ["%Y-%m-%d", "%m-%d", "%Y/%m/%d"]:
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in ("%m-%d", "%Y/%m/%d"):
                dt = dt.replace(year=now.year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def scrape_account_info(page) -> dict:
    return page.evaluate("""
        () => {
            const getText = (sel) => {
                const el = document.querySelector(sel);
                return el ? el.innerText.trim() : '';
            };

            // 昵称：.user-nickname 或 .nickname
            const nickname = getText('.user-nickname, .nickname, [class*="nickname"]');

            // 简介：.user-desc 区域
            const desc = getText('.user-desc, .desc, [class*="user-desc"]');

            // 头像
            const avatarEl = document.querySelector('.avatar-wrapper img, .avatar img, [class*="avatar"] img');
            const avatar = avatarEl ? avatarEl.src : '';

            // 粉丝数/关注数/获赞与收藏：.user-interactions 区域
            // 结构：<div><span class="count">7.6万</span><span class="shows">粉丝</span></div>
            let fansCount = '', followingCount = '', likeCount = '';
            const interactionDivs = document.querySelectorAll('.user-interactions > div, [class*="interactions"] > div');
            interactionDivs.forEach(div => {
                const countEl = div.querySelector('span.count, .count');
                const labelEl = div.querySelector('span.shows, .shows');
                if (!countEl || !labelEl) return;
                const val = countEl.innerText.trim();
                const label = labelEl.innerText.trim();
                if (label.includes('粉丝')) fansCount = val;
                else if (label.includes('关注')) followingCount = val;
                else if (label.includes('获赞') || label.includes('收藏')) likeCount = val;
            });

            // IP属地：小红书用 .user-IP-text 或 [class*="ip-location"]
            const ipSelectors = ['.user-IP-text', '[class*="ip-location"]', '[class*="ipLocation"]',
                                 '[class*="ip-text"]', '[class*="user-ip"]'];
            let ipLocation = '';
            for (const sel of ipSelectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.trim()) { ipLocation = el.innerText.trim(); break; }
            }

            // 认证信息：用精准选择器，避免误匹配 author 相关元素
            // 小红书认证标签通常在 .verify-badge / [class*="official"] 下
            const verifySelectors = ['.verify-badge', '[class*="official-tag"]',
                                     '[class*="verify-badge"]', '[class*="certification"]'];
            let verifyInfo = '';
            for (const sel of verifySelectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.trim()) { verifyInfo = el.innerText.trim(); break; }
            }

            return { nickname, desc, avatar, fansCount, followingCount, likeCount, ipLocation, verifyInfo, pageUrl: window.location.href };
        }
    """)


def scroll_and_scrape_notes(page, max_notes: int = 200, scroll_pause: float = 2.5) -> list[dict]:
    print(f"📜 滚动抓取笔记（目标: {max_notes} 条）...")
    seen_ids = set()
    notes = []
    scroll_count = 0
    max_scrolls = 200

    while len(notes) < max_notes and scroll_count < max_scrolls:
        result = page.evaluate("""
            () => {
                // 小红书主页笔记卡片固定用 section.note-item
                const cards = Array.from(document.querySelectorAll('section.note-item, .note-item'));
                const items = [];
                for (const card of cards) {
                    try {
                        // 标题：footer 区域的 a.title span
                        const titleEl = card.querySelector('a.title span, a.title, .title span, .title');
                        const title = titleEl ? titleEl.innerText.trim() : '';
                        if (!title || title.length < 2) continue;

                        // 封面图：cover 区域的 img
                        const imgEl = card.querySelector('a.cover img, a.mask img, img');
                        const coverImg = imgEl ? imgEl.src : '';

                        // 笔记链接：两种格式都有（/explore/xxx 或 /user/profile/uid/nid）
                        // 优先取 display:none 的 a[href*='/explore/'] 纯笔记ID链接
                        const pureLink = card.querySelector('a[href*="/explore/"]:not(.cover):not(.mask)');
                        const coverLink = card.querySelector('a.cover, a.mask');
                        const noteUrl = (pureLink ? pureLink.href : '') || (coverLink ? coverLink.href : '');

                        // 点赞数：.like-wrapper span.count
                        // 注意：小红书主页卡片只显示点赞，收藏/评论不在卡片上
                        const likeEl = card.querySelector('.like-wrapper span.count, .like-wrapper .count');
                        const likes = likeEl ? likeEl.innerText.trim() : '0';

                        // 视频识别：有 span.play-icon 就是视频
                        const isVideo = !!card.querySelector('span.play-icon, .play-icon');

                        // 发布日期：主页卡片不含日期，需进入详情页才能获取
                        // dateText 留空，标注为架构性缺失
                        const dateText = '';

                        items.push({
                            title,
                            coverImg,
                            noteUrl,
                            isVideo,
                            likes,          // 直接存解析好的点赞数字符串
                            interactText: likes,  // 兼容旧字段
                            dateText,
                        });
                    } catch(e) {}
                }
                return items;
            }
        """)

        for item in result:
            note_id = item.get("noteUrl", "") or item.get("title", "")
            if note_id and note_id not in seen_ids:
                seen_ids.add(note_id)
                # 解析日期
                if item.get("dateText"):
                    item["parsedDate"] = parse_relative_date(item["dateText"])
                notes.append(item)

        print(f"  滚动 {scroll_count + 1}：本次 {len(result)} 条，累计 {len(notes)} 条")
        scroll_count += 1

        if len(notes) >= max_notes:
            break

        page.evaluate("window.scrollBy(0, window.innerHeight * 1.2);")
        time.sleep(scroll_pause)

        at_bottom = page.evaluate(
            "(window.innerHeight + window.scrollY) >= document.body.scrollHeight - 100"
        )
        if at_bottom:
            print("  → 已到达页面底部")
            break

    return notes



def main():
    parser = argparse.ArgumentParser(description="小红书账号信息抓取器")
    parser.add_argument("--cdp", default="http://localhost:9222", help="Chrome CDP 地址")
    parser.add_argument("--url", help="账号主页 URL（可选，不提供则使用当前页面）")
    parser.add_argument("--output", "-o", default="/tmp/xhs_account.json", help="输出文件路径")
    parser.add_argument("--max-notes", type=int, default=200, help="最多抓取笔记数（默认200，设为999可不封顶）")
    args = parser.parse_args()

    print(f"🔗 连接到 Chrome: {args.cdp}")
    ws_url = connect_to_chrome(args.cdp)

    with sync_playwright() as p:
        page, browser = get_or_create_page(p, ws_url, args.url)

        if not args.url:
            current = page.url
            if "xiaohongshu.com" not in current:
                print(f"\n⚠️  当前不在小红书页面：{current}")
                print("请在浏览器中打开目标账号主页，然后按 Enter 继续...")
                input()
            else:
                print(f"📌 当前页面: {current}")
                print("确认这是目标账号主页后按 Enter 继续抓取...")
                input()

        print("\n👤 抓取账号信息...")
        account_info = scrape_account_info(page)
        print(f"  昵称: {account_info.get('nickname', 'N/A')}")
        print(f"  简介: {account_info.get('desc', 'N/A')[:60]}")
        print(f"  粉丝: {account_info.get('fansCount', 'N/A')}")

        notes = scroll_and_scrape_notes(page, max_notes=args.max_notes)
        print(f"\n✅ 共抓取 {len(notes)} 条笔记")

        output = {
            "account": account_info,
            "notes": notes,
            "noteCount": len(notes),
            "scrapedAt": __import__("datetime").datetime.now().isoformat(),
            "sourceUrl": page.url
        }

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"💾 数据已保存到: {args.output}")
        browser.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
小红书爆款分析抓取脚本

功能：
- 连接已登录的 Chrome 浏览器（CDP）
- 从当前搜索结果页抓取笔记列表（标题、互动数据、博主粉丝数）
- 过滤最近7天、低粉（<5万）、高互动的爆款笔记
- 支持抓取笔记评论区

用法：
    python xhs_scraper.py --mode search --keyword 穿搭 --output /tmp/xhs_results.json
    python xhs_scraper.py --mode note --url <note_url> --output /tmp/xhs_note.json
    python xhs_scraper.py --cdp http://localhost:9333 --mode search --keyword 穿搭
"""

import argparse
import json
import sys
import time
import urllib.parse
from datetime import datetime, timedelta

try:
    import requests
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ 缺少依赖，请运行：pip install playwright requests && playwright install chromium")
    sys.exit(1)

try:
    from playwright_stealth import stealth_sync
except ImportError:
    stealth_sync = None
    
import random

def connect_to_chrome(cdp_url: str):
    """连接到已运行的 Chrome 浏览器"""
    try:
        resp = requests.get(f"{cdp_url}/json/version", timeout=5)
        ws_url = resp.json()["webSocketDebuggerUrl"]
        return ws_url
    except Exception as e:
        print(f"❌ 无法连接到 Chrome: {e}")
        print(f"   请确保 Chrome 已启动并监听 {cdp_url}")
        sys.exit(1)


def get_xhs_page(playwright, ws_url: str, keyword: str = ""):
    """获取小红书页面"""
    browser = playwright.chromium.connect_over_cdp(ws_url)
    context = browser.contexts[0]
    
    if keyword:
        print("✨ 创建新标签页执行搜索，避免状态冲突...")
        page = context.new_page()
        if stealth_sync:
            try:
                stealth_sync(page)
            except Exception:
                pass
    else:
        pages = context.pages
        xhs_pages = [p for p in pages if "xiaohongshu.com" in p.url or "xhslink.com" in p.url]
        if xhs_pages:
            page = xhs_pages[0]
            print(f"♻️ 复用已打开的小红书页面: {page.url}")
        else:
            page = context.new_page()
            if stealth_sync:
                try:
                    stealth_sync(page)
                except Exception:
                    pass

    if keyword:
        print(f"🔄 正在准备搜索关键词: {keyword}")
        # 强制回到首页以确保搜索状态干净
        page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
        time.sleep(2)
        
        try:
            print(f"🖱️ 尝试在搜索框输入关键词并回车...")
            # 关闭可能遮挡搜索框的笔记详情弹窗
            page.keyboard.press("Escape")
            time.sleep(1)
            
            search_input = page.locator('#search-input')
            if search_input.count() == 0:
                search_input = page.locator('.search-input').first
            
            search_input.click(force=True)
            time.sleep(0.5)
            page.keyboard.press("Meta+A")
            page.keyboard.press("Backspace")
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            search_input.fill(keyword)
            # 立即回车，不等待，防止触发联想词或下拉框默认选中用户
            search_input.press("Enter")
            
            # 等待搜索结果页面加载
            time.sleep(5)
            
            print(f"🖱️ 尝试点击 [最新] 标签...")
            
            clicked_latest = False
            # 辅助函数：通过 JS 强行点击最新按钮
            def click_visible_latest():
                try:
                    clicked = page.evaluate("""() => {
                        const els = Array.from(document.querySelectorAll('*'))
                            .filter(el => el.innerText && el.innerText.includes('最') && el.innerText.includes('新') && el.innerText.length < 5);
                        if (els.length > 0) {
                            els[els.length - 1].click(); // 通常最后一个是当前弹出的那个
                            return true;
                        }
                        return false;
                    }""")
                    if clicked:
                        return True
                except:
                    pass
                return False
                
            clicked_latest = False
            
            # 方案一：直接点顶部出现的 "最新" 文本
            if click_visible_latest():
                print("✅ 成功直接点击 [最新]")
                clicked_latest = True
            else:
                # 方案二：尝试点击排序下拉框（综合）
                sort_dropdown = page.locator('.sort, .filter, .tab').get_by_text('综合', exact=True).first
                if sort_dropdown.count() > 0 and sort_dropdown.is_visible():
                    sort_dropdown.click()
                    time.sleep(1)
                    if click_visible_latest():
                        print("✅ 成功通过下拉框点击 [最新]")
                        clicked_latest = True
                    else:
                        print("⚠️ 下拉框中未找到 [最新]")
                
                # 如果前两个都没成功，尝试方案三：通过“筛选”面板
                if not clicked_latest:
                    filter_btn = page.locator('.filter, [class*="filter"]').filter(has_text='筛选').first
                    if filter_btn.count() > 0:
                        filter_btn.click(force=True)
                        print("🖱️ 已点击筛选面板，等待展开...")
                        time.sleep(2)
                        if click_visible_latest():
                            print("✅ 成功通过筛选面板点击 [最新]")
                            clicked_latest = True
                        else:
                            print("⚠️ 筛选面板展开后未找到 [最新]")
                    else:
                        print("⚠️ 找不到任何排序或筛选按钮")
            
            if not clicked_latest:
                print("⚠️ 尝试使用终极 fallback 点击")
                try:
                    page.get_by_text('最新', exact=True).first.click(timeout=3000, force=True)
                    print("✅ 成功通过终极 fallback 强制点击 [最新]")
                except:
                    print("❌ 所有寻找 [最新] 的方法均失败")
            
            time.sleep(3)
        except Exception as e:
            print(f"⚠️ 搜索操作失败: {e}")
    else:
        if "xiaohongshu.com" not in page.url:
            page.goto("https://www.xiaohongshu.com/explore", wait_until="networkidle")
        time.sleep(2)

    return page, browser


def parse_count(text: str) -> int:
    """解析互动数字，支持 '1.2万' '3000' 等格式"""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    if "万" in text:
        return int(float(text.replace("万", "")) * 10000)
    if "亿" in text:
        return int(float(text.replace("亿", "")) * 100000000)
    try:
        return int(text)
    except ValueError:
        return 0


def parse_relative_time(text: str) -> datetime | None:
    """解析相对时间，如 '3天前' '昨天' '2小时前'"""
    now = datetime.now()
    text = text.strip()

    if "刚刚" in text or "刚才" in text:
        return now
    if "分钟前" in text:
        m = re.search(r"(\d+)分钟前", text)
        if m:
            return now - timedelta(minutes=int(m.group(1)))
    if "小时前" in text:
        m = re.search(r"(\d+)小时前", text)
        if m:
            return now - timedelta(hours=int(m.group(1)))
    if "昨天" in text:
        return now - timedelta(days=1)
    if "天前" in text:
        m = re.search(r"(\d+)天前", text)
        if m:
            return now - timedelta(days=int(m.group(1)))
    if "周前" in text or "星期前" in text:
        m = re.search(r"(\d+)[周星期]前", text)
        if m:
            return now - timedelta(weeks=int(m.group(1)))
    # 尝试解析绝对日期 "01-15" 或 "2024-01-15"
    for fmt in ["%Y-%m-%d", "%m-%d"]:
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%m-%d":
                dt = dt.replace(year=now.year)
            return dt
        except ValueError:
            pass
    return None


def scrape_search_results(page, keyword: str, days: int = 7, max_followers: int = 50000, auto_scroll: bool = False, target_count: int = 200) -> dict:
    """
    从当前页面或搜索结果中抓取笔记列表
    支持 CDP 自动滚动防虚拟列表回收机制，按目标数量自动停止
    """
    print(f"📋 开始抓取搜索结果页...")

    # 等待页面加载
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    js_extraction_code = """
        () => {
            const results = [];
            const selectors = [
                'section.note-item',
                '.note-item',
                '.feeds-container section',
            ];

            let noteElements = [];
            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                if (els.length > 0) {
                    noteElements = Array.from(els);
                    break;
                }
            }

            for (const el of noteElements) {
                try {
                    const titleEl = el.querySelector('.title, .note-title, [class*="title"]');
                    const title = titleEl ? titleEl.innerText.trim() : '';
                    
                    // 优先获取带 xsec_token 的链接（避免扫码墙）
                    const allLinks = el.querySelectorAll('a');
                    let link = '';
                    let bareLink = '';
                    for (const a of allLinks) {
                        const h = a.href || '';
                        // 笔记的链接可能带有 /explore/ 或 /search_result/，但绝不能是 /user/profile/
                        if (h.includes('xsec_token') && !h.includes('/user/profile/')) {
                            link = h;
                            break;
                        }
                        if (!bareLink && h.includes('/explore/')) {
                            bareLink = h;
                        }
                    }
                    if (!link) link = bareLink;
                    
                    // 统一替换为 explore 格式，因为小红书可能在搜索页呈现为 /search_result/
                    if (link && link.includes('/search_result/')) {
                        link = link.replace('/search_result/', '/explore/');
                    }
                    
                    const likeEl = el.querySelector('.like-wrapper .count, .likes-count, [class*="like"] .count, .interact-info .like-count');
                    const likeCount = likeEl ? likeEl.innerText.trim() : '0';
                    
                    const authorEl = el.querySelector('.author-info .name, .author .name, [class*="author"] .name');
                    const authorName = authorEl ? authorEl.innerText.trim() : '';
                    
                    const authorLinkEl = el.querySelector('a.author, a[href*="/user/profile/"]');
                    const authorLink = authorLinkEl ? authorLinkEl.href : '';
                    
                    const imgEl = el.querySelector('img');
                    const coverImg = imgEl ? imgEl.src : '';

                    if (title && link) {
                        results.push({
                            title, link, likeCount, authorName, authorLink, coverImg,
                            rawHtml: el.outerHTML.substring(0, 2000)
                        });
                    }
                } catch(e) {}
            }
            return results;
        }
    """

    all_results_dict = {}

    def safe_evaluate():
        for _ in range(3):
            try:
                return page.evaluate(js_extraction_code)
            except Exception as e:
                if "Execution context was destroyed" in str(e) or "Target closed" in str(e):
                    time.sleep(2)
                else:
                    raise
        return []

    if auto_scroll:
        print(f"🚀 开启全自动滚屏模式，目标抓取 {target_count} 条...")
        scroll_attempts = 0
        max_attempts = max(50, target_count // 5) # 设置防死循环上限
        
        while len(all_results_dict) < target_count and scroll_attempts < max_attempts:
            # 提取当前屏幕内容
            current_batch = safe_evaluate()
            new_count = 0
            for item in current_batch:
                link = item.get("link")
                if link and link not in all_results_dict:
                    all_results_dict[link] = item
                    new_count += 1
            
            print(f"  👉 [滚屏 {scroll_attempts+1}/{max_attempts}] 当前提取新增 {new_count} 条，累计发现 {len(all_results_dict)}/{target_count} 条独立笔记")
            
            if len(all_results_dict) >= target_count:
                break
                
            # 仿生学：随机滚动跨度与概率回滚机制
            scroll_y = random.randint(600, 1200)
            if random.random() < 0.15: # 15% 概率回滚一小段，模拟真人重新看或者划过头
                page.mouse.wheel(0, -random.randint(100, 300))
                time.sleep(random.uniform(0.3, 0.8))
                
            page.mouse.wheel(0, scroll_y)
            
            # 仿生学：幽灵鼠标轨迹 (在屏幕可视范围内随意滑动)
            try:
                page.mouse.move(random.randint(200, 800), random.randint(200, 800), steps=random.randint(5, 15))
            except:
                pass
                
            # 仿生学：高斯分布的随机延迟，替代固定的 2.5 秒
            time.sleep(random.uniform(2.1, 4.2))
            scroll_attempts += 1
            
        # 裁剪到 target_count
        final_list = list(all_results_dict.values())[:target_count]
        all_results_dict = {item["link"]: item for item in final_list}
    else:
        # 单次抓取（兼容老模式）
        current_batch = safe_evaluate()
        for item in current_batch:
            if item.get("link"):
                all_results_dict[item["link"]] = item

    return {
        "count": len(all_results_dict),
        "data": list(all_results_dict.values()),
        "url": page.url,
        "pageTitle": page.title()
    }


def scrape_author_profile(page, author_url: str = None) -> dict:
    """抓取博主主页获取粉丝数"""
    if author_url:
        page.goto(author_url, wait_until="domcontentloaded")
        time.sleep(2)

    for attempt in range(3):
        try:
            result = page.evaluate("""
                () => {
                    let fansCount = '0';
                    // 小红书主页的粉丝数一般在 .user-interactions .count 或者包含“粉丝”的元素的兄弟节点
                    const dataItems = document.querySelectorAll('.user-data .data-item, .user-interactions > div, [class*="data-item"]');
                    for (const item of dataItems) {
                        if (item.innerText.includes('粉丝')) {
                            const countEl = item.querySelector('.count');
                            if (countEl) {
                                fansCount = countEl.innerText.trim();
                            } else {
                                // 如果没有 .count，可能直接是文字如 "1.2万 粉丝"
                                fansCount = item.innerText.replace('粉丝', '').trim();
                            }
                            break;
                        }
                    }
                    // 兼容旧版或不同DOM结构
                    if (fansCount === '0') {
                        const fansEl = document.querySelector('.fans-count, [class*="fans"] .count, .author-detail .fans');
                        if (fansEl) fansCount = fansEl.innerText.trim();
                    }
                    return { fansCount };
                }
            """)
            return result
        except Exception as e:
            if "Execution context was destroyed" in str(e) or "Target closed" in str(e):
                print(f"     ⚠️ 页面重载，等待 2 秒后重试 ({attempt+1}/3)...")
                time.sleep(2)
            else:
                print(f"     ❌ 提取报错: {e}")
                return {}
    return {}


def main():
    parser = argparse.ArgumentParser(description="小红书爆款分析抓取器")
    parser.add_argument("--cdp", default="http://localhost:9333", help="Chrome CDP 地址")
    parser.add_argument("--mode", choices=["search", "note"], default="search", help="抓取模式")
    parser.add_argument("--keyword", help="搜索关键词（search 模式）")
    parser.add_argument("--url", help="笔记 URL（note 模式）")
    parser.add_argument("--days", type=int, default=7, help="最近N天（默认7）")
    parser.add_argument("--max-fans", type=int, default=50000, help="最大粉丝数（默认5万）")
    parser.add_argument("--auto-scroll", action="store_true", help="是否开启自动滚动突破DOM限制")
    parser.add_argument("--target-count", type=int, default=100, help="目标抓取数量（默认100条）")
    parser.add_argument("--deep-fetch", action="store_true", help="是否开启二次深度抓取以获取真实粉丝数")
    parser.add_argument("--test-one", action="store_true", help="测试模式：只深度抓取一条笔记")
    parser.add_argument("--min-likes", type=int, default=500, help="触发深度抓取的最小点赞数门槛（默认500）")
    parser.add_argument("--output", "-o", default="/tmp/xhs_result.json", help="输出文件路径")
    args = parser.parse_args()

    print(f"🔗 连接到 Chrome: {args.cdp}")
    ws_url = connect_to_chrome(args.cdp)

    with sync_playwright() as p:
        page, browser = get_xhs_page(p, ws_url, args.keyword or "")

        if args.mode == "search":
            print(f"📌 当前页面: {page.url}")
            if not args.auto_scroll:
                print(f"⚠️  未开启自动滚动。请在浏览器中手动滚动加载内容后，按 Enter 继续...")
                input()

            result = scrape_search_results(page, args.keyword or "", args.days, args.max_fans, args.auto_scroll, args.target_count)
            print(f"✅ 去重后共抓取到 {result['count']} 条独立笔记")

            if getattr(args, 'deep_fetch', False):
                # 标记并筛选候选人
                for item in result['data']:
                    item['is_viral_candidate'] = (parse_count(item.get('likeCount', '0')) >= args.min_likes)
                
                candidates = [item for item in result['data'] if item['is_viral_candidate']]
                
                print(f"🔍 开启二次深度抓取（Deep Fetch），找到 {len(candidates)} 篇点赞大于 {args.min_likes} 的候选笔记...")
                context = browser.contexts[0]
                
                # 为了防止 macOS 下每次新建标签页都强行抢占焦点弹窗，
                # 我们直接复用原有的 page（搜索页）进行主页跳转。
                for i, item in enumerate(candidates, 1):
                    authorLink = item.get('authorLink')
                    if not authorLink:
                        print(f"  👉 [深度探测 {i}/{len(candidates)}] 缺少博主主页链接，跳过...")
                        continue

                    print(f"  👉 [深度探测 {i}/{len(candidates)}] 访问博主主页: {item.get('authorName', '')}...")
                    try:
                        # 仿生学：模拟点击前的幽灵鼠标和思考延时
                        try:
                            page.mouse.move(random.randint(100, 800), random.randint(100, 800), steps=random.randint(5, 15))
                            time.sleep(random.uniform(0.2, 0.7))
                        except:
                            pass
                            
                        profile_data = scrape_author_profile(page, authorLink)
                        item['fansCount'] = profile_data.get('fansCount', '0')
                        item['commentList'] = []
                        
                        # 仿生学：防风控的长停顿机制（模拟喝水、回微信）
                        if i % 20 == 0:
                            print(f"  ☕ [防风控长停顿] 已连续探测 {i} 个，模拟真人喝水休息 10~15 秒...")
                            time.sleep(random.uniform(8.0, 15.0))
                        else:
                            time.sleep(random.uniform(2.5, 4.8))  # 正态分布随机延时防风控
                            
                    except Exception as e:
                        print(f"     ❌ 提取失败: {e}")
                            
                    if getattr(args, 'test_one', False):
                        print(f"🛑 测试模式(--test-one)已开启，完成一条深度抓取后停止。")
                        break

        elif args.mode == "note":
            print(f"⚠️  不再支持 mode=note（避免扫码风控），请使用 search 模式")

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"💾 结果已保存到: {args.output}")
        browser.close()


if __name__ == "__main__":
    main()

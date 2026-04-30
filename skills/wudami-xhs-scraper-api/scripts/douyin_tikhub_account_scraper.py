#!/usr/bin/env python3
import asyncio
import argparse
import json
import os
import sys
import re
import httpx
from datetime import datetime

BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
TIKHUB_TIMEOUT = float(os.environ.get("TIKHUB_TIMEOUT", "45"))
HEADERS = {"Authorization": f"Bearer {os.environ.get('TIKHUB_API_KEY')}"}

async def api_get(endpoint: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=TIKHUB_TIMEOUT) as client:
        r = await client.get(f"{BASE_URL}{endpoint}", params=params, headers=HEADERS)
        r.raise_for_status()
        return r.json()

def extract_sec_user_id(url: str) -> str:
    # 匹配 https://www.douyin.com/user/MS4w...
    match = re.search(r'user/(MS4w[^?\/]+)', url)
    if match:
        return match.group(1)
    
    match = re.search(r'sec_uid=(MS4w[^&]+)', url)
    if match:
        return match.group(1)
        
    return url  # Fallback: assume url is just the ID

def parse_relative_date(timestamp_ms: int) -> str:
    if not timestamp_ms:
        return ""
    try:
        # Douyin timestamps are generally in seconds (10 digits)
        if timestamp_ms > 10000000000:
            dt = datetime.fromtimestamp(timestamp_ms / 1000.0)
        else:
            dt = datetime.fromtimestamp(timestamp_ms)
        return dt.strftime("%Y-%m-%d")
    except:
        return ""

async def scrape_douyin_videos(sec_user_id: str, max_notes: int):
    api_calls = 0
    account_info = {}
    try:
        user_res = await api_get("/api/v1/douyin/web/handler_user_profile", {"sec_user_id": sec_user_id})
        api_calls += 1
        
        user_data = user_res.get("data", {})
        if "user" in user_data:
            user_data = user_data["user"]
            
        nickname = user_data.get("nickname", "")
        desc = user_data.get("signature", "")
        fans = str(user_data.get("follower_count", ""))
        
        account_info = {"nickname": nickname, "desc": desc, "fansCount": fans}
    except Exception as e:
        print(f"⚠️ 获取用户信息失败: {e}")

    print("\n👤 抓取账号信息...")
    print(f"  昵称: {account_info.get('nickname', 'N/A')}")
    print(f"  简介: {account_info.get('desc', 'N/A')[:60]}")
    print(f"  粉丝: {account_info.get('fansCount', 'N/A')}")

    print(f"📜 抓取视频（API 调用, 目标: {max_notes} 条）...")

    notes = []
    max_cursor = 0
    seen_ids = set()

    for page in range(999):
        params = {"sec_user_id": sec_user_id, "count": 20}
        if max_cursor:
            params["max_cursor"] = max_cursor
        
        try:
            res = await api_get("/api/v1/douyin/web/fetch_user_post_videos", params)
            api_calls += 1
            
            data_node = res.get("data", {})
            if "aweme_list" not in data_node and "data" in data_node:
                data_node = data_node["data"]
                
            video_list = data_node.get("aweme_list", [])
            has_more = data_node.get("has_more", False)
            max_cursor = data_node.get("max_cursor", 0)
        except httpx.HTTPError as e:
            print(f"❌ API 请求失败: {e}")
            break

        prev_count = len(notes)
        for raw_video in video_list:
            vid = raw_video.get("aweme_id")
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            
            video_url = f"https://www.douyin.com/video/{vid}"
            
            # 封面提取
            cover_img = ""
            video_cover_obj = raw_video.get("video", {})
            if video_cover_obj.get("cover", {}).get("url_list"):
                cover_img = video_cover_obj["cover"]["url_list"][0]
            
            # 数据统计
            stats = raw_video.get("statistics", {})
            likes = str(stats.get("digg_count", 0))
            
            time_val = raw_video.get("create_time", 0)
            date_text = parse_relative_date(time_val) if time_val else ""

            # Mapping 格式严格遵守 analyzer 所需的 input schema (假装是notes方便复用下半场流程)
            notes.append({
                "title": raw_video.get("desc", ""),
                "coverImg": cover_img,
                "noteUrl": video_url,
                "isVideo": True,
                "likes": likes,
                "interactText": likes,
                "dateText": date_text,
                "parsedDate": date_text
            })

            if len(notes) >= max_notes:
                break
                
        new_count = len(notes) - prev_count
        print(f"  翻页 {page+1}：本次新增 {new_count} 条，累计 {len(notes)} 条")
        
        if len(notes) >= max_notes or not has_more or not max_cursor:
            break
            
        await asyncio.sleep(0.5)

    print(f"\n✅ 共抓取 {len(notes)} 条视频")
    
    # 账单结算计算
    cost_usd = api_calls * 0.001
    cost_rmb = cost_usd * 7.2
    print(f"💸 本次 API 调用总计: {api_calls} 次 (含主页鉴权及翻页请求)")
    print(f"💲 预估 API 消耗金额: ${cost_usd:.3f} USD (约 {cost_rmb:.3f} 元 RMB)")
    
    return account_info, notes

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="目标抖音账号主页URL或sec_user_id")
    parser.add_argument("--output", "-o", default="/tmp/douyin_account.json", help="输出文件路径")
    parser.add_argument("--max-notes", type=int, default=200, help="最多抓取视频数（默认200，设为999可不封顶）")
    args = parser.parse_args()

    api_key = os.environ.get("TIKHUB_API_KEY")
    if not api_key:
        print("❌ 错误: 未设置 TIKHUB_API_KEY 环境变量！")
        print("💡 提示: 请配置 export TIKHUB_API_KEY=your_key")
        sys.exit(1)

    sec_user_id = extract_sec_user_id(args.url)
    print(f"🔗 解析 sec_user_id: {sec_user_id}")
    
    try:
        account_info, notes = asyncio.run(scrape_douyin_videos(sec_user_id, args.max_notes))
        output = {
            "account": account_info,
            "notes": notes
        }
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"💾 数据已保存到: {args.output}")
    except KeyboardInterrupt:
        print("\n\n⚠️ 中断抓取，已保存已有数据？（此处未接管）")

if __name__ == "__main__":
    main()

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

def _parse_notes_response(res: dict):
    actual = res.get("data", {})
    if isinstance(actual, dict) and isinstance(actual.get("data"), dict):
        actual = actual["data"]
    elif isinstance(actual, list) and actual:
        actual = actual[0]
    if not isinstance(actual, dict):
        return [], False, ""
    notes = actual.get("notes") or actual.get("items") or actual.get("note_list") or []
    has_more = actual.get("has_more", False) or actual.get("hasMore", False)
    cursor = actual.get("cursor") or actual.get("next_cursor") or ""
    if not cursor and notes:
        cursor = notes[-1].get("cursor") or notes[-1].get("note_id") or notes[-1].get("id") or ""
    return notes, has_more, cursor

async def fetch_user_notes_page(user_id: str, cursor: str):
    endpoints = [
        ("/api/v1/xiaohongshu/app_v2/get_user_posted_notes", "cursor", {}),
        ("/api/v1/xiaohongshu/app/get_user_notes", "cursor", {}),
        ("/api/v1/xiaohongshu/web_v3/fetch_user_notes", "cursor", {"num": 30}),
        ("/api/v1/xiaohongshu/web/get_user_notes_v2", "lastCursor", {}),
    ]
    last_error = None
    for endpoint, cursor_key, extra in endpoints:
        params = {"user_id": user_id, **extra}
        if cursor:
            params[cursor_key] = cursor
        try:
            res = await api_get(endpoint, params)
            notes, has_more, next_cursor = _parse_notes_response(res)
            if notes:
                return endpoint, notes, has_more, next_cursor
            print(f"⚠️ {endpoint} 返回空数据，继续降级")
        except Exception as e:
            last_error = e
            print(f"⚠️ {endpoint} 请求失败: {e}")
    raise RuntimeError(f"所有用户笔记端点均失败: {last_error}")

def extract_user_id(url: str) -> str:
    match = re.search(r'profile/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    return url  # Fallback: assume url is just the ID

def parse_relative_date(timestamp_ms: int) -> str:
    # 转换为形如 "2024-05-12" 或 "刚刚"
    if not timestamp_ms:
        return ""
    try:
        # TikHub returned time is often in milliseconds or seconds.
        # Check if it's 13 digits or 10 digits
        if timestamp_ms > 10000000000:
            dt = datetime.fromtimestamp(timestamp_ms / 1000.0)
        else:
            dt = datetime.fromtimestamp(timestamp_ms)
        return dt.strftime("%Y-%m-%d")
    except:
        return ""

async def scrape_tikhub_notes(user_id: str, max_notes: int):
    api_calls = 0
    # 先获取用户信息
    account_info = {}
    try:
        user_res = await api_get("/api/v1/xiaohongshu/web/get_user_info", {"user_id": user_id})
        api_calls += 1
        user_data = user_res.get("data", {}).get("data", {})
        basic_info = user_data.get("basic_info", {})
        interactions = user_data.get("interactions", [])
        
        desc = basic_info.get("desc", "")
        nickname = basic_info.get("nickname", "")
        fans = ""
        for i in interactions:
            if i.get("type") == "fans":
                fans = i.get("count", "")
        account_info = {"nickname": nickname, "desc": desc, "fansCount": fans}
    except Exception as e:
        print(f"⚠️ 获取用户信息失败: {e}")

    print("\n👤 抓取账号信息...")
    print(f"  昵称: {account_info.get('nickname', 'N/A')}")
    print(f"  简介: {account_info.get('desc', 'N/A')[:60]}")
    print(f"  粉丝: {account_info.get('fansCount', 'N/A')}")

    print(f"📜 抓取笔记（API 调用, 目标: {max_notes} 条）...")

    notes = []
    cursor = ""
    seen_ids = set()

    for page in range(999):
        params = {"user_id": user_id}
        if cursor:
            params["cursor"] = cursor
        
        try:
            endpoint, note_list, has_more, cursor = await fetch_user_notes_page(user_id, cursor)
            api_calls += 1
        except httpx.HTTPError as e:
            print(f"❌ API 请求失败: {e}")
            break

        prev_count = len(notes)
        for raw_note in note_list:
            note_card = raw_note.get("noteCard") if isinstance(raw_note, dict) else None
            if isinstance(note_card, dict):
                raw_note = {**raw_note, **note_card}
            nid = raw_note.get("note_id") or raw_note.get("noteId") or raw_note.get("id")
            if not nid or nid in seen_ids:
                continue
            seen_ids.add(nid)
            
            note_url = f"https://www.xiaohongshu.com/explore/{nid}"
            xsec_token = raw_note.get("xsec_token", "") or raw_note.get("xsecToken", "")
            if xsec_token:
                note_url += f"?xsec_token={xsec_token}&xsec_source=pc_share"
                
            cover_img = ""
            images = raw_note.get("images_list") or raw_note.get("image_list") or raw_note.get("imageList") or []
            if images and len(images) > 0:
                first_image = images[0]
                cover_img = first_image.get("url", "") or first_image.get("original", "") if isinstance(first_image, dict) else str(first_image)
            elif raw_note.get("cover"):
                cover = raw_note.get("cover", {})
                cover_img = cover.get("url", "") if isinstance(cover, dict) else str(cover)
            
            # App 端直出 likes, Web 端出 interact_info.liked_count
            likes_val = raw_note.get("likes")
            if likes_val is None:
                interact = raw_note.get("interact_info", {}) or raw_note.get("interactInfo", {})
                likes_val = interact.get("liked_count", interact.get("likedCount", 0))
            likes = str(likes_val)
            
            is_video = raw_note.get("type") in ["video", "normal_video", "2"] or bool(raw_note.get("video") or raw_note.get("video_info"))
            time_val = raw_note.get("create_time") or raw_note.get("time", 0)
            date_text = parse_relative_date(time_val) if time_val else ""

            # Mapping 格式严格遵守 analyzer 所需的 input schema
            notes.append({
                "title": raw_note.get("display_title", "") or raw_note.get("displayTitle", "") or raw_note.get("title", ""),
                "coverImg": cover_img,
                "noteUrl": note_url,
                "isVideo": is_video,
                "likes": likes,
                "interactText": likes,
                "dateText": date_text,
                "parsedDate": date_text
            })

            if len(notes) >= max_notes:
                break
                
        new_count = len(notes) - prev_count
        print(f"  翻页 {page+1}（{endpoint}）：本次新增 {new_count} 条，累计 {len(notes)} 条")
        
        if len(notes) >= max_notes or not has_more or not cursor:
            break
            
        await asyncio.sleep(0.5)

    print(f"\n✅ 共抓取 {len(notes)} 条笔记")
    
    # 账单结算计算
    cost_usd = api_calls * 0.001
    cost_rmb = cost_usd * 7.2
    print(f"💸 本次 API 调用总计: {api_calls} 次 (含主页鉴权及翻页请求)")
    print(f"💲 预估 API 消耗金额: ${cost_usd:.3f} USD (约 {cost_rmb:.3f} 元 RMB)")
    
    return account_info, notes

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="目标小红书账号主页URL或ID")
    parser.add_argument("--output", "-o", default="/tmp/xhs_account.json", help="输出文件路径")
    parser.add_argument("--max-notes", type=int, default=200, help="最多抓取笔记数（默认200，设为999可不封顶）")
    args = parser.parse_args()

    api_key = os.environ.get("TIKHUB_API_KEY")
    if not api_key:
        print("❌ 错误: 未设置 TIKHUB_API_KEY 环境变量！")
        print("💡 提示: 请配置 export TIKHUB_API_KEY=your_key")
        sys.exit(1)

    user_id = extract_user_id(args.url)
    print(f"🔗 解析 User ID: {user_id}")
    
    try:
        account_info, notes = asyncio.run(scrape_tikhub_notes(user_id, args.max_notes))
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

#!/usr/bin/env python3
"""
wudami-xhs-koubo-all 小红书博主全量高赞笔记双阶段提纯工厂
Stage 1 (list): 极速导出清单与统计数据
Stage 2 (extract): 加载缓存、精准OCR/ASR榨取并聚合最终表
"""

import argparse
import base64
import io
import sys
import os
import re
import json
import httpx
import requests
import subprocess
import tempfile
import time
import urllib.parse
from datetime import datetime
from PIL import Image

# ── 强制前置检查（不进函数，直接拦在入口） ────────────────────────────────
if not os.environ.get("TIKHUB_API_KEY"):
    print("❌ 强制中断：未检测到 TIKHUB_API_KEY 环境变量，本工具无法执行。")
    print("   请先配置 TIKHUB_API_KEY 后重试。")
    sys.exit(1)

TIKHUB_BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
TIKHUB_TIMEOUT = float(os.environ.get("TIKHUB_TIMEOUT", "45"))
TIKHUB_DETAIL_RETRIES = int(os.environ.get("TIKHUB_DETAIL_RETRIES", "2"))
KOUBO_CDP_FALLBACK_MAX = int(os.environ.get("KOUBO_CDP_FALLBACK_MAX", "5"))
XHS_CDP_PORT = os.environ.get("XHS_CDP_PORT", "9333")
CDP_SKILL_DIR = os.path.expanduser(os.environ.get(
    "XHS_NOTE_ANALYZER_CDP_DIR",
    "~/.claude/skills/wudami-xhs-note-analyzer-cdp"
))
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
OUTPUTS_DIR = os.path.expanduser("~/.claude/skills/wudami-xhs-koubo-all/outputs")

def _masked_key_info() -> str:
    key = os.environ.get("TIKHUB_API_KEY", "")
    if not key:
        return "未加载"
    return f"已加载，长度 {len(key)}，尾号 {key[-4:]}"

def _print_tikhub_auth_failure():
    print("❌ TikHub HTTP 鉴权失败：服务端返回 401 Unauthorized。")
    print(f"   当前 Base URL: {TIKHUB_BASE_URL}")
    print(f"   当前 TIKHUB_API_KEY: {_masked_key_info()}")
    print("   这通常不是视频字段或端点降级问题，而是 Key 未被当前 Agent 环境正确加载、Key 已失效，或 HTTP/MCP 使用了不同凭证。")
    print("   请先修复 TIKHUB_API_KEY；不要静默切 MCP 大批量补抓，以免重复产生 TikHub 调用成本。")

def parse_count(num_str) -> int:
    if isinstance(num_str, int):
        return num_str
    if not num_str:
        return 0
    num_str = str(num_str).strip().lower()
    try:
        if 'w' in num_str or '万' in num_str:
            num_str = num_str.replace('w', '').replace('万', '')
            return int(float(num_str) * 10000)
        if 'k' in num_str:
            num_str = num_str.replace('k', '')
            return int(float(num_str) * 1000)
        return int(num_str)
    except:
        return 0

def extract_user_id(url: str) -> str:
    m = re.search(r'profile/([a-zA-Z0-9]+)', url)
    if m: return m.group(1)
    return url.strip()

def _try_endpoint(client, headers, endpoint, params):
    """尝试单个端点，返回 (response_json, error_msg)"""
    try:
        res = client.get(f"{TIKHUB_BASE_URL}{endpoint}", params=params, headers=headers)
        if res.status_code == 401:
            return None, "AUTH_FAILED"
        if res.status_code == 403:
            return None, "PERM_DENIED"
        res.raise_for_status()
        return res.json(), None
    except Exception as e:
        return None, str(e)

def _first_non_empty(*values):
    for value in values:
        if value:
            return value
    return ""

def _dig(data, *keys):
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur

def _extract_video_url(note: dict) -> str:
    """兼容 App/App V2/Web 多种视频字段，尽量拿到可下载视频 URL。"""
    if not isinstance(note, dict):
        return ""

    video_info = (
        note.get("video_info_v2")  # Web V2 接口，视频 URL 藏在 media.stream.h264[].master_url
        or note.get("video")
        or note.get("video_info")
        or note.get("videoInfo")
        or {}
    )
    media = video_info.get("media", {}) if isinstance(video_info, dict) else {}
    stream = media.get("stream", {}) if isinstance(media, dict) else {}

    streams = []
    if isinstance(stream, dict):
        for key in ("h264", "h265", "h266", "av1"):
            value = stream.get(key)
            if isinstance(value, list):
                streams.extend(value)
            elif isinstance(value, dict):
                streams.append(value)

    for item in streams:
        if not isinstance(item, dict):
            continue
        direct = _first_non_empty(item.get("master_url"), item.get("masterUrl"), item.get("url"), item.get("backup_url"))
        if direct:
            return direct
        url_list = item.get("url_list") or item.get("backup_urls") or item.get("backupUrls")
        if isinstance(url_list, list) and url_list:
            return url_list[0]

    return _first_non_empty(
        note.get("video_url"),
        note.get("videoUrl"),
        note.get("url"),
        video_info.get("url") if isinstance(video_info, dict) else "",
        video_info.get("master_url") if isinstance(video_info, dict) else "",
        _dig(video_info, "stream", "h264", "master_url"),
    )

def _extract_cover_url(note: dict) -> str:
    if not isinstance(note, dict):
        return ""
    for key in ("images_list", "image_list", "images"):
        images = note.get(key)
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                return _first_non_empty(first.get("url"), first.get("original"), first.get("url_default"), first.get("urlDefault"))
            if isinstance(first, str):
                return first
    cover = note.get("cover")
    if isinstance(cover, dict):
        return _first_non_empty(cover.get("urlDefault"), cover.get("urlPre"), cover.get("url"), cover.get("url_default"))
    if isinstance(cover, str):
        return cover
    return ""

def _find_first_note(data):
    """从 TikHub 不同版本响应中递归找第一条笔记详情。"""
    queue = [data]
    seen = set()
    while queue:
        cur = queue.pop(0)
        cur_id = id(cur)
        if cur_id in seen:
            continue
        seen.add(cur_id)

        if isinstance(cur, list):
            queue.extend(cur[:10])
            continue

        if not isinstance(cur, dict):
            continue

        note_list = cur.get("note_list") or cur.get("notes") or cur.get("items")
        if isinstance(note_list, list) and note_list:
            queue.insert(0, note_list[0])

        has_note_shape = (
            cur.get("desc") is not None or cur.get("title") is not None or
            cur.get("display_title") is not None or cur.get("video") or
            cur.get("video_info") or cur.get("image_list") or cur.get("images_list")
        )
        if has_note_shape:
            return cur

        for key in ("data", "noteCard", "note_card", "note", "note_info", "noteInfo", "detail", "result"):
            value = cur.get(key)
            if isinstance(value, (dict, list)):
                queue.append(value)
    return {}

def _html_video_fallback(note_id: str, xsec_token: str = "") -> str:
    note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token:
        note_url = f"{note_url}?xsec_token={urllib.parse.quote(xsec_token)}"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        resp = requests.get(note_url, headers=headers, timeout=20)
        html_text = resp.text.replace("\\u002F", "/")
        vids = re.findall(r'https?://[^"\'\s]+\.mp4[^"\'\s]*', html_text)
        if vids:
            https_vids = [v for v in vids if v.startswith("https")]
            return https_vids[0] if https_vids else vids[0]
    except Exception as e:
        print(f"  ⚠️ HTML MP4 兜底失败: {e}")
    return ""

def _note_share_url(note_id: str) -> str:
    return f"https://www.xiaohongshu.com/explore/{note_id}"

def _note_browser_url(note_id: str, xsec_token: str = "") -> str:
    base = _note_share_url(note_id)
    if not xsec_token:
        return base
    return f"{base}?{urllib.parse.urlencode({'xsec_token': xsec_token, 'xsec_source': 'pc_user'})}"

def _run_cdp_note_fallback(note_id: str, xsec_token: str, output_dir: str, reason: str) -> dict:
    """Use the single-note CDP skill as the final free browser fallback.

    This is intentionally a low-volume fallback for selected extract targets, not the
    bulk list/extract primary path. The CDP scraper may pause for login/xsec checks.
    """
    if KOUBO_CDP_FALLBACK_MAX <= 0:
        return {}

    launch_script = os.path.join(CDP_SKILL_DIR, "scripts", "launch_chrome.py")
    scraper_script = os.path.join(CDP_SKILL_DIR, "scripts", "xhs_note_scraper.py")
    if not os.path.exists(launch_script) or not os.path.exists(scraper_script):
        print(f"  ⚠️ CDP 兜底不可用：未找到 {CDP_SKILL_DIR}")
        return {}

    fallback_dir = os.path.join(output_dir, "cdp_fallback")
    os.makedirs(fallback_dir, exist_ok=True)
    output_path = os.path.join(fallback_dir, f"{note_id}.json")
    note_url = _note_browser_url(note_id, xsec_token)

    print(f"  🧩 启用 CDP 浏览器兜底（端口 {XHS_CDP_PORT}）：{reason}")
    print("     若浏览器出现登录/滑块验证，请手动完成，脚本会继续。")

    try:
        launch = subprocess.run(
            [sys.executable, launch_script],
            cwd=CDP_SKILL_DIR,
            text=True,
            capture_output=True,
            timeout=45
        )
        if launch.returncode != 0:
            print(f"  ⚠️ CDP Chrome 启动失败: {(launch.stderr or launch.stdout).strip()[:300]}")
            return {}

        cmd = [
            sys.executable,
            scraper_script,
            "--cdp", f"http://localhost:{XHS_CDP_PORT}",
            "--url", note_url,
            "--max-comments", "0",
            "--output", output_path,
        ]
        result = subprocess.run(cmd, cwd=CDP_SKILL_DIR, text=True)
        if result.returncode != 0:
            print(f"  ⚠️ CDP 单篇抓取失败，退出码 {result.returncode}")
            return {}
        if not os.path.exists(output_path):
            print("  ⚠️ CDP 单篇抓取未生成结果文件")
            return {}

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        note = data.get("note") or {}
        if note:
            print(f"  ✅ CDP 兜底成功：{note.get('noteType', '未知类型')} / {note.get('title', '')[:30]}")
        return note
    except Exception as e:
        print(f"  ⚠️ CDP 兜底异常: {e}")
        return {}

def _merge_cdp_note(note: dict, desc: str, likes: str, collects: str, comments: str, video_url: str, cover_url: str):
    if not note:
        return desc, likes, collects, comments, video_url, cover_url, ""

    cdp_desc = note.get("content") or ""
    if cdp_desc and not desc:
        desc = cdp_desc

    if likes in ("", "0") and note.get("likes"):
        likes = str(note.get("likes"))
    if collects in ("", "0") and note.get("collects"):
        collects = str(note.get("collects"))
    if comments in ("", "0") and note.get("comments"):
        comments = str(note.get("comments"))

    if not video_url and note.get("videoUrl"):
        video_url = note.get("videoUrl")
    images = note.get("images") or []
    if not cover_url and images:
        cover_url = images[0]

    spoken = note.get("audioText") or ""
    return desc, likes, collects, comments, video_url, cover_url, spoken

def _parse_notes_from_response(data: dict) -> tuple:
    """从不同版本 API 的响应中统一提取 (note_list, has_more, next_cursor)"""
    actual = data.get("data", {})
    
    # web_v3 格式: {"data": {"notes": [...], "cursor": "...", "has_more": true}}
    if isinstance(actual, dict) and "data" in actual and isinstance(actual["data"], dict):
        inner = actual["data"]
        notes = inner.get("notes") or inner.get("note_list") or inner.get("items") or []
        has_more = inner.get("has_more", False) or inner.get("hasMore", False)
        cursor = inner.get("cursor", "")
        if not cursor and notes:
            cursor = notes[-1].get("cursor", "")
        return notes, has_more, cursor
    
    # app 格式: {"data": {"note_list": [...]}}  或  {"data": [{"note_list": [...]}]}
    if isinstance(actual, list) and len(actual) > 0:
        actual = actual[0]
    
    notes = actual.get("note_list") or actual.get("notes") or actual.get("items") or []
    has_more = actual.get("has_more", False)
    cursor = actual.get("cursor") or actual.get("next_cursor", "")
    if not cursor and notes:
        cursor = notes[-1].get("cursor", "")
    return notes, has_more, cursor

# 降级路由表: (端点路径, 游标参数名, 额外固定参数)
# TikHub 2026-04 文档推荐优先级：App V2 > App > Web V3 > Web V2 > Web。
ENDPOINT_CHAIN = [
    ("/api/v1/xiaohongshu/app_v2/get_user_posted_notes", "cursor", {}),
    ("/api/v1/xiaohongshu/app/get_user_notes",        "cursor", {}),
    ("/api/v1/xiaohongshu/web_v3/fetch_user_notes",   "cursor", {"num": 30}),
    ("/api/v1/xiaohongshu/web/get_user_notes_v2",     "lastCursor", {}),
]

def fetch_all_notes(user_id: str, max_count: int) -> list:
    tikhub_key = os.environ.get("TIKHUB_API_KEY")
    if not tikhub_key:
        # Top-level guard already exited; this is a fallback for direct function calls
        print("❌ 未设置 TIKHUB_API_KEY 环境变量！")
        sys.exit(1)
        
    headers = {"Authorization": f"Bearer {tikhub_key}"}
    all_filtered = []
    cursor = ""
    scraped_total = 0
    seen_ids = set()
    
    # 探测可用端点 (首次请求时自动选定)
    active_endpoint = None
    active_cursor_key = None
    active_extra_params = {}
    
    with httpx.Client(timeout=TIKHUB_TIMEOUT) as client:
        while scraped_total < max_count:
            # ---- 第一次循环: 逐个尝试所有端点，锁定能用的那个 ----
            if active_endpoint is None:
                print("  🔍 正在探测可用 API 端点 ...")
                perm_denied_endpoints = []
                for ep, ckey, extra in ENDPOINT_CHAIN:
                    params = {"user_id": user_id, **extra}
                    if cursor:
                        params[ckey] = cursor
                    data, err = _try_endpoint(client, headers, ep, params)
                    if err == "AUTH_FAILED":
                        _print_tikhub_auth_failure()
                        sys.exit(1)
                    if err == "PERM_DENIED":
                        perm_denied_endpoints.append(ep)
                        print(f"    ⚠️ {ep} → 权限不足（403），跳过")
                        continue
                    if err:
                        print(f"    ❌ {ep} → 失败: {err}")
                        continue
                    # 成功！
                    notes, has_more, next_cursor = _parse_notes_from_response(data)
                    if notes:
                        active_endpoint = ep
                        active_cursor_key = ckey
                        active_extra_params = extra
                        print(f"    ✅ 锁定可用端点: {ep}")
                        # 直接处理第一批数据
                        break
                    else:
                        print(f"    ⚠️ {ep} → 返回数据为空")
                        continue
                
                if active_endpoint is None:
                    print("\n❌ 所有 TikHub 小红书笔记接口均不可用！")
                    if perm_denied_endpoints:
                        print("="*60)
                        print("🔑 检测到部分端点返回 403 权限不足！")
                        print("   请前往 TikHub 后台开启 API Token 权限：")
                        print("   👉 https://user.tikhub.io/dashboard/api")
                        print("   在 Token Scopes 中勾选 web_v3 相关权限后重试。")
                        print("="*60)
                    sys.exit(1)
            else:
                # ---- 后续循环: 使用已锁定的端点翻页 ----
                params = {"user_id": user_id, **active_extra_params}
                if cursor:
                    params[active_cursor_key] = cursor
                print(f"  👉 正在拉取博主数据 (游标: {cursor or '初始'}) ...")
                
                # ---- 防假死重试层 ----
                retry_count = 0
                max_retries = 3
                fetch_success = False
                
                while retry_count < max_retries:
                    data, err = _try_endpoint(client, headers, active_endpoint, params)
                    if err:
                        retry_count += 1
                        print(f"    ⚠️ 端点 {active_endpoint} 拉取失败 ({err})，重试 {retry_count}/{max_retries}...")
                        time.sleep(2)
                        continue
                        
                    notes, has_more, next_cursor = _parse_notes_from_response(data)
                    
                    # 假终点探测：有时候 API 随机返回 notes 为空
                    if not notes or not isinstance(notes, list):
                        retry_count += 1
                        print(f"    ⚠️ 返回笔记为空 (防截断探测)，重试 {retry_count}/{max_retries}...")
                        time.sleep(2)
                        continue
                        
                    fetch_success = True
                    break
                
                # ---- 自动降级穿透 ----
                if not fetch_success:
                    print(f"  ❌ 当前端点 {active_endpoint} 彻底失效或到达真终点，尝试降级穿透...")
                    fallback_success = False
                    for ep, ckey, extra in ENDPOINT_CHAIN:
                        if ep == active_endpoint: continue
                        print(f"    🔄 尝试降级至端点: {ep}")
                        fb_params = {"user_id": user_id, **extra}
                        if cursor: fb_params[ckey] = cursor
                        
                        fb_retry = 0
                        while fb_retry < 2:
                            fb_data, fb_err = _try_endpoint(client, headers, ep, fb_params)
                            if not fb_err:
                                fb_notes, fb_has_more, fb_next_cursor = _parse_notes_from_response(fb_data)
                                if fb_notes and isinstance(fb_notes, list):
                                    notes, has_more, next_cursor = fb_notes, fb_has_more, fb_next_cursor
                                    active_endpoint, active_cursor_key, active_extra_params = ep, ckey, extra
                                    fallback_success = True
                                    print(f"    ✅ 降级成功！已锁定新端点: {ep}")
                                    break
                            fb_retry += 1
                            time.sleep(1)
                            
                        if fallback_success:
                            break
                            
                    if not fallback_success:
                        print("  ℹ️ 所有降级策略均无数据，确定已到达翻页终点。")
                        break
            
            for note in notes:
                n_id = note.get("noteId") or note.get("note_id") or note.get("id")
                if not n_id or n_id in seen_ids:
                    continue
                seen_ids.add(n_id)
                scraped_total += 1
                
                n_type = str(note.get("type", ""))
                is_video = n_type == "video" or n_type == "2" or note.get("video")
                mapped_type = "video" if is_video else "normal"
                
                likes_raw = note.get("likes") or note.get("liked_count") or note.get("interactInfo", {}).get("likedCount") or note.get("interact_info", {}).get("liked_count", 0)
                likes = parse_count(likes_raw)
                
                disp_title = note.get("displayTitle") or note.get("display_title") or note.get("title", "")
                basic_info = {
                    "idx": scraped_total,
                    "id": n_id,
                    "title": disp_title,
                    "type": mapped_type,
                    "likes": likes,
                    "likes_raw": str(likes_raw),
                    "cover": "",
                    "video_url": "",
                    "desc": note.get("desc", disp_title),
                    "xsec_token": note.get("xsec_token") or note.get("xsecToken") or note.get("xsec_token_str") or ""
                }
                
                basic_info["cover"] = _extract_cover_url(note)
                    
                if is_video:
                    basic_info["video_url"] = _extract_video_url(note)
                
                all_filtered.append(basic_info)
                
            if not next_cursor or next_cursor == cursor:
                print("  ℹ️ 游标不再更新，结束翻页。")
                break
                
            if not has_more:
                print("  ⚠️ 接口提示无更多数据(has_more=False)，将强行向下探测防截断...")
                
            cursor = next_cursor
            time.sleep(1)
            
    return all_filtered

def get_sf_key() -> str:
    sf_key = os.environ.get("SILICONFLOW_API_KEY")
    if not sf_key:
        print("❌ 未设置 SILICONFLOW_API_KEY")
        sys.exit(1)
    return sf_key

import requests

def _url_to_base64_jpeg(cover_url: str) -> str:
    """下载图片并统一转为 JPEG base64 data URI（自动处理 HEIF/WebP/AVIF）。
    优先用 pillow-heif，失败则用 ffmpeg 兜底，均失败则报错字符串。"""
    try:
        import pillow_heif
        HAS_HEIF = True
    except ImportError:
        HAS_HEIF = False

    # 1. 清理 URL 畸形后缀
    clean_url = re.sub(r'#.*$', '', cover_url)
    for suffix in ['|imageMogr2/str', '|imageMogr2']:
        clean_url = clean_url.replace(suffix, '')

    try:
        resp = requests.get(clean_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        raw_bytes = resp.content
        content_type = resp.headers.get("Content-Type", "").lower()
    except Exception as e:
        return f"[下载失败] {e}"

    # 2. 按格式转换
    image = None
    err_msg = ""

    if "heif" in content_type or "heic" in content_type:
        if HAS_HEIF:
            try:
                image = pillow_heif.open(io.BytesIO(raw_bytes)).to_pillow()
            except Exception as e:
                err_msg = str(e)
        else:
            err_msg = "pillow-heif 未安装"

        # pillow-heif 失败 → 尝试 ffmpeg 兜底
        if image is None:
            image = _ffmpeg_convert_heif(raw_bytes)
            if image is None:
                return f"[HEIF转换失败] {err_msg}"

    elif "webp" in content_type or "avif" in content_type:
        try:
            image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        except Exception as e:
            return f"[{content_type}转换失败] {e}"

    else:
        try:
            image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        except Exception as e:
            return f"[图片读取失败] {e}"

    # 3. 统一转 JPEG base64
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"

def _ffmpeg_convert_heif(raw_bytes: bytes):
    """用 ffmpeg 将 HEIF 字节流转为 PIL RGB Image（兜底方案）"""
    import shutil
    ffmpeg_cmd = shutil.which("ffmpeg")
    if not ffmpeg_cmd:
        for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
            if os.path.exists(p):
                ffmpeg_cmd = p
                break
    if not ffmpeg_cmd:
        return None

    with tempfile.NamedTemporaryFile(suffix=".heic", delete=False) as f:
        f.write(raw_bytes)
        heic_path = f.name

    out_path = heic_path.replace(".heic", ".jpg")
    try:
        subprocess.run(
            [ffmpeg_cmd, "-i", heic_path, out_path, "-y"],
            capture_output=True, timeout=30
        )
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return Image.open(out_path).convert("RGB")
    finally:
        for p in [heic_path, out_path]:
            if os.path.exists(p):
                os.remove(p)
    return None

def analyze_cover_text_with_vlm(cover_url: str) -> str:
    if not cover_url:
        return "无封面图"
    sf_key = get_sf_key()
    url = f"{SILICONFLOW_BASE_URL}/chat/completions"

    data_uri = _url_to_base64_jpeg(cover_url)
    if data_uri.startswith("[") and "失败" in data_uri:
        return data_uri

    payload = {
        "model": "Qwen/Qwen2-VL-72B-Instruct",
        "messages": [
            {"role": "system", "content": "你是一个图片内容文字提取器。请直接输出图片上能看到的所有文字（按排版重要程度罗列），不需要任何其余解释。"},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": "请提取这张封面上的所有文字。如果在图上没有看到任何文字，请回答'无字'"}
            ]}
        ],
        "temperature": 0.1,
        "max_tokens": 1024
    }

    try:
        resp = requests.post(url, headers={"Authorization": f"Bearer {sf_key}", "Content-Type": "application/json"}, json=payload, timeout=60)
        resp.raise_for_status()
        text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        return text.strip().replace("\n", " ")
    except Exception as e:
        return f"VLM读取失败: {e}"

def download_video(video_url: str, save_path: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.xiaohongshu.com/",
        "Origin": "https://www.xiaohongshu.com",
        "Range": "bytes=0-",
    }
    with requests.get(video_url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    if not os.path.exists(save_path) or os.path.getsize(save_path) < 1024:
        raise RuntimeError("视频下载结果为空或过小")

def extract_audio(video_path: str) -> str:
    import shutil
    ffmpeg_cmd = shutil.which("ffmpeg")
    if not ffmpeg_cmd:
        for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
            if os.path.exists(p):
                ffmpeg_cmd = p
                break
    audio_path = video_path.replace(".mp4", ".wav")
    cmd = [ffmpeg_cmd, "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path, "-y"]
    subprocess.run(cmd, capture_output=True, timeout=60)
    return audio_path

def transcribe_audio_with_sf(audio_path: str) -> str:
    sf_key = get_sf_key()
    url = f"{SILICONFLOW_BASE_URL}/audio/transcriptions"
    try:
        with open(audio_path, "rb") as f:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {sf_key}"},
                files={"file": ("audio.wav", f, "audio/wav")},
                data={"model": "FunAudioLLM/SenseVoiceSmall"},
                timeout=120
            )
        resp.raise_for_status()
        return resp.json().get("text", "").strip()
    except Exception as e:
        return f"提取失败: {e}"

def _normalize_folder_name(name: str) -> str:
    """统一文件夹命名：去除特殊符号，替换括号为下划线"""
    import re
    name = name.replace('/', '_').replace('（', '_').replace('）', '_').replace('(', '_').replace(')', '_').replace(' ', '_')
    name = re.sub(r'_+', '_', name)
    return name.strip('_')

def _resolve_author_dir(folder_name: str) -> str:
    """复用已存在的博主文件夹（最早日期优先），不存在则创建今天的文件夹。"""
    base_dir = "/Users/wushijing/Obsidian仓库/吴大咪一人公司/02-素材库/脚本库"
    if os.path.exists(base_dir):
        matched = sorted([
            d for d in os.listdir(base_dir)
            if d.endswith(f"-{folder_name}") and os.path.isdir(os.path.join(base_dir, d))
        ])
        if matched:
            return os.path.join(base_dir, matched[0])
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, f"{datetime.now().strftime('%Y-%m-%d')}-{folder_name}")

def get_author_nickname(user_id: str) -> str:
    """直接用 user_id 获取博主昵称，比 note 嵌套字段更可靠"""
    headers = {"Authorization": f"Bearer {os.environ.get('TIKHUB_API_KEY')}"}
    for attempt in range(3):
        try:
            res = requests.get(
                f"{TIKHUB_BASE_URL}/api/v1/xiaohongshu/web/get_user_info",
                params={"user_id": user_id},
                headers=headers,
                timeout=TIKHUB_TIMEOUT
            )
            data = res.json()
            if data.get("code") == 200:
                user_data = data.get("data", {})
                # 兼容不同 API 响应结构
                user_info = user_data.get("data", user_data)
                nickname = (
                    user_info.get("nickname") or
                    user_info.get("user", {}).get("nickname") or
                    user_info.get("basic_info", {}).get("nickname") or
                    ""
                )
                if nickname:
                    return nickname.replace('/', '_').replace(' ', '').replace('（', '_').replace('）', '_').replace('(', '_').replace(')', '_')
            time.sleep(1)
        except Exception:
            if attempt < 2:
                time.sleep(2)
    return ""


def full_note_detail(note_id: str, note_type: str = "video", xsec_token: str = ""):
    headers = {"Authorization": f"Bearer {os.environ.get('TIKHUB_API_KEY')}"}

    # TikHub 小红书详情降级链（按优先级）：
    # App V2 → App → Web V3 → Web V2 → Web V7。
    # Web V2 返回的视频字段常在 video_info_v2.media.stream.h264[].master_url，
    # _extract_video_url() 必须兼容 video_info_v2，不能只看 video/video_info/videoInfo。

    share_url = _note_share_url(note_id)
    detail_endpoints = [
        ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", {"note_id": note_id}),
        ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", {"share_text": share_url}),
        ("/api/v1/xiaohongshu/app/get_note_info", {"note_id": note_id}),
        ("/api/v1/xiaohongshu/app/get_note_info", {"share_text": share_url}),
        ("/api/v1/xiaohongshu/web_v3/fetch_note_detail", {"note_id": note_id, "xsec_token": xsec_token}),
        ("/api/v1/xiaohongshu/web_v2/fetch_feed_notes_v2", {"note_id": note_id}),
        ("/api/v1/xiaohongshu/web/get_note_info_v7", {"note_id": note_id, "share_text": share_url}),
    ]

    for endpoint, params in detail_endpoints:
        for attempt in range(TIKHUB_DETAIL_RETRIES):
            try:
                res = requests.get(f"{TIKHUB_BASE_URL}{endpoint}", params=params, headers=headers, timeout=TIKHUB_TIMEOUT)
                data_resp = res.json()
                if res.status_code == 401:
                    _print_tikhub_auth_failure()
                    return {}
                if res.status_code == 403:
                    print(f"  ⚠️ {endpoint} 权限不足（403），跳过")
                    break
                if res.status_code >= 400 or data_resp.get("code") not in (None, 0, 200):
                    print(f"  ⚠️ {endpoint} 响应异常 (attempt {attempt+1}): {data_resp.get('message', res.status_code)}")
                    time.sleep(2 + attempt * 2)
                    continue

                note = _find_first_note(data_resp)
                if not note:
                    print(f"  ⚠️ {endpoint} 未解析到笔记详情 (attempt {attempt+1})")
                    time.sleep(2 + attempt * 2)
                    continue

                desc = note.get("desc", "")
                interact = note.get("interact_info") or note.get("interactInfo") or note.get("interaction") or {}
                video_url = _extract_video_url(note)
                is_video = note_type == "video" or note.get("type") in ("video", "2") or bool(note.get("video") or note.get("video_info") or video_url)

                # 兜底：从 native_voice_info 拿 m4a 音频 URL（TikHub 对部分笔记限流视频但音频仍可访问）
                if is_video and not video_url:
                    native_voice = note.get("native_voice_info") or note.get("nativeVoiceInfo") or {}
                    if not native_voice and isinstance(note, dict):
                        # 尝试从 widgets_context 解析
                        wc = note.get("widgets_context", "")
                        if wc:
                            try:
                                wc_data = json.loads(wc) if isinstance(wc, str) else wc
                                native_voice = wc_data.get("note_sound_info", {})
                            except Exception:
                                pass
                    audio_url = native_voice.get("url") if isinstance(native_voice, dict) else ""
                    if audio_url:
                        print(f"  🎧 视频URL受限，启用音频兜底: native_voice duration={native_voice.get('duration', '?')}ms")
                        video_url = audio_url  # m4a URL，ffmpeg 同样能抽音轨

                if is_video and not video_url and attempt < TIKHUB_DETAIL_RETRIES - 1:
                    print(f"  ⚠️ {endpoint} 已拿到详情但缺视频 URL，重试 {attempt+1}/{TIKHUB_DETAIL_RETRIES}...")
                    time.sleep(2 + attempt * 2)
                    continue

                nickname = ""
                user = note.get("user") or note.get("user_info") or note.get("userInfo") or {}
                if isinstance(user, dict):
                    nickname = user.get("nickname", "")

                return (
                    desc,
                    str(_first_non_empty(interact.get("liked_count"), interact.get("likedCount"), note.get("liked_count"), note.get("likes"), "0")),
                    str(_first_non_empty(interact.get("collected_count"), interact.get("collectedCount"), note.get("collected_count"), note.get("collects"), "0")),
                    str(_first_non_empty(interact.get("comments_count"), interact.get("comment_count"), interact.get("commentCount"), note.get("comments"), "0")),
                    video_url,
                    nickname
                )
            except Exception as e:
                if attempt < TIKHUB_DETAIL_RETRIES - 1:
                    print(f"  ⚠️ {endpoint} 请求失败 ({e})，重试 {attempt+1}/{TIKHUB_DETAIL_RETRIES}...")
                    time.sleep(2 + attempt * 2)
                else:
                    print(f"  ❌ {endpoint} 连续失败: {e}")

    print("  ⚠️ TikHub 详情接口均未拿到视频 URL，尝试 HTML MP4 兜底...")
    return "", "0", "0", "0", _html_video_fallback(note_id, xsec_token), ""

def _export_csv_to_desktop(rows: list, filename_prefix: str, columns: list):
    """通用 CSV 导出：写 Obsidian MD + 桌面 CSV 双份"""
    import csv
    desktop_dir = os.path.expanduser("~/Desktop")
    csv_path = os.path.join(desktop_dir, f"{filename_prefix}.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  📊 CSV 已导出至桌面：{csv_path}")
    return csv_path

def do_list_mode(user_id: str, max_count: int):
    print(f"\n🏃💨 开始全量预扫描博主主页: {user_id}")
    notes = fetch_all_notes(user_id, max_count)

    if not notes:
        print("❌ 未抓取到任何笔记。")
        sys.exit(0)

    cache_path = os.path.join(OUTPUTS_DIR, f"cache_{user_id}.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

    print(f"\n====================== 预览目录 ======================")
    print(f"{'序号':<5} | {'笔记ID':<25} | {'类型':<8} | {'点赞数':<10} | {'标题':<30}")
    print("-" * 90)
    for v in notes:
        title = v['title'].replace('\n', ' ')
        if len(title) > 25: title = title[:24] + "..."
        print(f"[{v['idx']:02d}]  | {v['id']:<25} | {v['type']:<8} | {v['likes_raw']:<10} | {title}")

    # Generate the Markdown Radar Table on disk automatically
    date_str = datetime.now().strftime("%Y-%m-%d")
    nickname = get_author_nickname(user_id)

    # 拿不到昵称就用「博主资料」兜底
    folder_name = nickname if nickname else "博主资料"
    folder_name = _normalize_folder_name(folder_name)
    obsidian_base_dir = _resolve_author_dir(folder_name)
    videos_dir = os.path.join(obsidian_base_dir, "videos")
    os.makedirs(videos_dir, exist_ok=True)
    md_file = os.path.join(obsidian_base_dir, f"全量雷达扫描-{folder_name}-{len(notes)}条.md")

    md_content = f"# 全量雷达扫描 | {folder_name} ({len(notes)}条)\n\n"
    md_content += f"- **博主URL**：https://www.xiaohongshu.com/user/profile/{user_id}\n"
    md_content += f"- **扫描时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    md_content += f"| 序号 | 笔记ID | 类型 | 点赞数 | 标题 | 直达原帖 |\n"
    md_content += f"|---|---|---|---|---|---|\n"
    for v in notes:
        t_title = v['title'].replace('\n', ' ').replace('|', '')
        md_content += f"| {v['idx']} | ``{v['id']}`` | {v['type']} | {v['likes_raw']} | {t_title} | [查看原帖](https://www.xiaohongshu.com/explore/{v['id']}) |\n"

    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_content)

    # ── 同步导出 CSV 到桌面 ──────────────────────────────────────────────
    csv_columns = ["序号", "笔记ID", "类型", "点赞数", "标题", "直达原帖"]
    csv_rows = []
    for v in notes:
        t_title = v['title'].replace('\n', ' ').replace('|', '')
        csv_rows.append({
            "序号": v['idx'],
            "笔记ID": v['id'],
            "类型": v['type'],
            "点赞数": v['likes_raw'],
            "标题": t_title,
            "直达原帖": f"https://www.xiaohongshu.com/explore/{v['id']}"
        })
    desktop_csv = _export_csv_to_desktop(csv_rows, f"雷达扫描-{nickname}-{len(notes)}条", csv_columns)

    print("\n" + "="*80)
    print(f"📦 共缓存 {len(notes)} 条数据记录已存入本地 ({cache_path})。")
    print(f"👉 第一阶段扫描清单已自动生成至：\n   {md_file}")
    print(f"\n👉 下一步请下达具体指令（无需关闭当前会话）：\n   比如使用 `--mode extract --target-ids {notes[0]['id']},{notes[1]['id']}`")
    print(f"   或者使用 `--mode extract --min-likes 1000 --note-type video`")

def do_extract_mode(user_id: str, url: str, target_ids: str, min_likes: int, note_type: str):
    cache_path = os.path.join(OUTPUTS_DIR, f"cache_{user_id}.json")
    if not os.path.exists(cache_path):
        print("❌ 未发现该博主的预扫描缓存，请先运行 `--mode list` 预扫描。")
        sys.exit(1)
        
    with open(cache_path, "r", encoding="utf-8") as f:
        all_notes = json.load(f)
        
    # 过滤环节
    filtered_notes = []
    if target_ids:
        t_ids = [t.strip() for t in target_ids.split(",")]
        # Support extracting by ID or by Index
        filtered_notes = [n for n in all_notes if n['id'] in t_ids or str(n['idx']) in t_ids]
    else:
        for n in all_notes:
            if note_type != "all" and n['type'] != note_type:
                continue
            if n['likes'] < min_likes:
                continue
            filtered_notes.append(n)
            
    if not filtered_notes:
        print("❌ 根据你指定的门槛/ID，没有匹配到任何符合条件的笔记。")
        sys.exit(0)

    print(f"\n🎯 二次提纯启动，共选中 {len(filtered_notes)} 篇巅峰作品。即将进入矩阵榨取厂...")

    date_str = datetime.now().strftime("%Y-%m-%d")
    # 直接用 user_id 拿博主昵称，比嵌套在 note 里更可靠
    account_name = get_author_nickname(user_id)

    folder_name = account_name if account_name else "博主资料"
    folder_name = _normalize_folder_name(folder_name)
    obsidian_base_dir = _resolve_author_dir(folder_name)
    videos_dir = os.path.join(obsidian_base_dir, "videos")
    os.makedirs(videos_dir, exist_ok=True)
    index_file = os.path.join(obsidian_base_dir, f"{os.path.basename(obsidian_base_dir)}.md")

    results_md = f"# 博主巅峰笔记素材提取聚合表 ({len(filtered_notes)} 篇)\n\n"
    results_md += f"- **博主URL**：{url}\n- **抓取时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    results_md += "| 笔记主题 | 互动大盘基础数据 | 口播提取 (ASR) | 标题+正文 (原帖) | 封面视觉文字排版 (AI提取) | 查看原帖 |\n"
    results_md += "|---|---|---|---|---|---|\n"

    cdp_fallback_attempts = 0

    for i, v in enumerate(filtered_notes, 1):
        note_id = v['id']
        title = v['title'].replace(chr(10), "")
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"

        print(f"\n=======================================================")
        print(f" 🎬 正在攻克第 {i}/{len(filtered_notes)} 条高赞任务: [{title[:20]}]")

        desc, likes, collects, comments, detail_video_url, nickname = full_note_detail(note_id, v.get("type", "all"), v.get("xsec_token", ""))
        if likes == "0": likes = v['likes_raw']

        original_desc = f"**{title}**<br><br>" + desc.replace(chr(10), "<br>")
        spoken_text = "无提取音频"
        final_video_url = detail_video_url or v.get('video_url', '')
        cdp_note = {}
        cdp_spoken = ""

        if v['type'] == "video" and not final_video_url and cdp_fallback_attempts < KOUBO_CDP_FALLBACK_MAX:
            cdp_fallback_attempts += 1
            cdp_note = _run_cdp_note_fallback(
                note_id,
                v.get("xsec_token", ""),
                obsidian_base_dir,
                "TikHub/HTML 均未拿到视频 URL"
            )
            desc, likes, collects, comments, final_video_url, v['cover'], cdp_spoken = _merge_cdp_note(
                cdp_note, desc, likes, collects, comments, final_video_url, v.get('cover', '')
            )
            original_desc = f"**{title}**<br><br>" + desc.replace(chr(10), "<br>")
            if cdp_spoken:
                spoken_text = cdp_spoken

        if v['type'] == "video" and final_video_url:
            print(f"  🎙️ 侦测为视频笔记，启动沙箱音规抽离...")
            with tempfile.TemporaryDirectory() as temp_dir:
                v_path = os.path.join(temp_dir, "source.mp4")
                try:
                    download_video(final_video_url, v_path)
                    # 持久化保存到 videos_dir
                    safe_title = re.sub(r'[\\/:*?"<>|]', '', title)[:40]
                    persistent_video_path = os.path.join(videos_dir, f"{note_id}_{safe_title}.mp4")
                    import shutil
                    shutil.copy2(v_path, persistent_video_path)
                    print(f"  💾 视频已保存: {persistent_video_path}")
                    a_path = extract_audio(v_path)
                    print(f"  🎙️ 发送给 SenseVoice 转写...")
                    spoken = transcribe_audio_with_sf(a_path)
                    if spoken and not spoken.startswith("提取失败"):
                        spoken_text = spoken
                    elif cdp_spoken:
                        spoken_text = cdp_spoken
                    else:
                        spoken_text = "提取失败"
                except Exception as e:
                    print(f"  ⚠️ 视频处理失败: {e}")
                    if not cdp_note and cdp_fallback_attempts < KOUBO_CDP_FALLBACK_MAX:
                        cdp_fallback_attempts += 1
                        cdp_note = _run_cdp_note_fallback(
                            note_id,
                            v.get("xsec_token", ""),
                            obsidian_base_dir,
                            f"视频下载/抽音失败：{e}"
                        )
                        desc, likes, collects, comments, final_video_url, v['cover'], cdp_spoken = _merge_cdp_note(
                            cdp_note, desc, likes, collects, comments, final_video_url, v.get('cover', '')
                        )
                        original_desc = f"**{title}**<br><br>" + desc.replace(chr(10), "<br>")
                    spoken_text = cdp_spoken if cdp_spoken else f"视频处理失败: {e}"
        elif v['type'] == "video" and cdp_spoken:
            spoken_text = cdp_spoken
        elif v['type'] == "video":
            spoken_text = "视频URL缺失，TikHub/HTML/CDP 均未提取到可用音频"
        elif v['type'] != "video":
            spoken_text = "图文内容无口播"

        print(f"  👁️‍🗨️ VLM 视觉大模型正在解析封面排版字迹...")
        cover_text = analyze_cover_text_with_vlm(v['cover'])  # 函数内部自动做 URL 净化 + HEIF→JPEG 转换

        t_title = title.replace('|', '')
        t_stats = f"**赞**: {likes}<br>**藏**: {collects}<br>**评**: {comments}"
        t_spoken = spoken_text.replace('|', '').replace('\n', '<br>')
        t_desc = original_desc.replace('|', '').replace('\n', '<br>')
        t_cover = cover_text.replace('|', '').replace('\n', '<br>')

        results_md += f"| {t_title} | {t_stats} | {t_spoken} | {t_desc} | {t_cover} | [直达原帖]({note_url}) |\n"

        # 写入详情字段，供 CSV 导出使用
        v["_title"] = t_title
        v["_likes"] = likes
        v["_collects"] = collects
        v["_comments"] = comments
        v["_spoken"] = spoken_text
        v["_desc"] = original_desc
        v["_cover"] = cover_text

        if obsidian_base_dir and index_file:
            with open(index_file, "w", encoding="utf-8") as f:
                f.write(results_md)
            
    if obsidian_base_dir and index_file:
        print(f"\n🏆 全部萃取矩阵提纯完毕！")
        print(f"  👉 聚合长桌已保存至：\n{index_file}")
        # ── 同步导出聚合表 CSV 到桌面 ─────────────────────────────────
        csv_columns = ["笔记主题", "赞", "藏", "评", "口播提取", "原文", "封面文字", "直达原帖"]
        csv_rows = []
        for v in filtered_notes:
            csv_rows.append({
                "笔记主题": v.get("_title", ""),
                "赞": v.get("_likes", ""),
                "藏": v.get("_collects", ""),
                "评": v.get("_comments", ""),
                "口播提取": v.get("_spoken", ""),
                "原文": v.get("_desc", ""),
                "封面文字": v.get("_cover", ""),
                "直达原帖": f"https://www.xiaohongshu.com/explore/{v['id']}"
            })
        if csv_rows:
            _export_csv_to_desktop(csv_rows, f"萃取结果-{folder_name}-{len(filtered_notes)}篇", csv_columns)
    else:
        print(f"\n⚠️ 萃取执行结束，但未能生成任何结果（可能未抓取到有效账号昵称或所有内容全军覆没）。")

def main():
    parser = argparse.ArgumentParser("wudami-xhs-koubo-all 双阶抓取工序")
    parser.add_argument("--url", required=True, help="博主的小红书主页地址")
    parser.add_argument("--mode", required=True, choices=["list", "extract"], help="模式：list（预扫描）或 extract（提取聚合）")
    parser.add_argument("--max-count", type=int, default=999, help="预扫描最多条数")
    
    # Extract params
    parser.add_argument("--min-likes", type=int, default=0, help="提取时的最低赞门槛")
    parser.add_argument("--note-type", choices=["all", "video", "normal"], default="all", help="提取视频/图文模式")
    parser.add_argument("--target-ids", type=str, default="", help="精准指定的笔记 序号索引组合，无视点赞门槛。比如 '1,2,5' 或 note_id 组合。")
    
    args = parser.parse_args()
    user_id = extract_user_id(args.url)
    
    if args.mode == "list":
        do_list_mode(user_id, args.max_count)
    elif args.mode == "extract":
        do_extract_mode(user_id, args.url, args.target_ids, args.min_likes, args.note_type)

if __name__ == "__main__":
    main()

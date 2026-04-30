#!/usr/bin/env python3
"""
小红书单篇笔记数据抓取脚本（TikHub API 版）
通过 TikHub API 直接 HTTP 调用抓取笔记详情+评论，无需浏览器和登录。
输出格式与 CDP 版完全一致，确保下游 AI 分析和桌面导出脚本无缝兼容。
"""

import argparse
import json
import os
import re
import sys
import time
import subprocess
import math
import glob
from datetime import datetime
from typing import Optional

def ensure_dependencies():
    """自动安装依赖（开箱即用）"""
    required = {
        "httpx": "httpx",
        "requests": "requests",
        "imageio_ffmpeg": "imageio-ffmpeg",
        "PIL": "Pillow"
    }
    missing = []
    for mod, pip_name in required.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print(f"📦 自动安装依赖: {', '.join(missing)}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing, "-q"])
        except subprocess.CalledProcessError:
            # macOS Homebrew Python (PEP 668) 禁止系统级安装，降级为 --user 或 --break-system-packages
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", *missing, "-q"])
            except subprocess.CalledProcessError:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--break-system-packages", *missing, "-q"])
        print("✅ 依赖安装完成！")

ensure_dependencies()

import httpx
import requests as req_lib

BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
TIKHUB_TIMEOUT = float(os.environ.get("TIKHUB_TIMEOUT", "45"))


# ═══════════════════════════════════════════════════════════════
# 1. TikHub API 数据采集
# ═══════════════════════════════════════════════════════════════

def extract_note_id(url: str) -> str:
    """从各种小红书链接格式中提取 note_id"""
    # https://www.xiaohongshu.com/explore/{note_id}?...
    m = re.search(r'explore/([a-zA-Z0-9]+)', url)
    if m:
        return m.group(1)
    # https://www.xiaohongshu.com/discovery/item/{note_id}
    m = re.search(r'item/([a-zA-Z0-9]+)', url)
    if m:
        return m.group(1)
    # xhslink.com 短链 — 直接传给 API 的 share_text 参数
    if 'xhslink.com' in url:
        return url
    # 纯 ID
    return url.strip()

def extract_xsec_token(url: str) -> Optional[str]:
    """从 URL 中提取 xsec_token 参数（web_v4 端点需要）"""
    m = re.search(r'xsec_token=([^&]+)', url)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    return None

def api_get(endpoint: str, params: dict, api_key: str) -> dict:
    """同步 HTTP GET 请求 TikHub API"""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=TIKHUB_TIMEOUT) as client:
            r = client.get(f"{BASE_URL}{endpoint}", params=params, headers=headers)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        print(f"❌ API 请求失败 [{e.response.status_code}]: {e.response.text[:300]}")
        raise
    except Exception as e:
        print(f"❌ API 请求异常: {e}")
        raise

def _first_non_empty(*values):
    for value in values:
        if value:
            return value
    return ""

def _find_first_note(data):
    """从 App/App V2/Web V3/Web V4 不同响应结构中找到实际 note dict。"""
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

        if cur.get("desc") is not None or cur.get("title") is not None or cur.get("display_title") is not None or cur.get("noteCard") or cur.get("video") or cur.get("video_info_v2") or cur.get("video_info") or cur.get("image_list") or cur.get("images_list"):
            if "noteCard" in cur and isinstance(cur["noteCard"], dict):
                return cur["noteCard"]
            return cur

        for key in ("data", "noteCard", "note_card", "note", "note_info", "noteInfo", "detail", "result"):
            value = cur.get(key)
            if isinstance(value, (dict, list)):
                queue.append(value)
    return {}

def _extract_video_url(note: dict) -> str:
    if not isinstance(note, dict):
        return ""
    video_info = note.get("video_info_v2") or note.get("video") or note.get("video_info") or note.get("videoInfo") or {}
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
        video_info.get("url") if isinstance(video_info, dict) else "",
        video_info.get("master_url") if isinstance(video_info, dict) else "",
    )

def _parse_note_raw(note_list: dict, note_id: str, xsec_token: str = "") -> dict:
    """将 TikHub 返回的原始笔记 dict 映射为标准 JSON 格式（两个端点共用）"""
    # 提取字段
    title = note_list.get("display_title", "") or note_list.get("title", "")
    desc = note_list.get("desc", "") or note_list.get("content", "")

    # 话题标签
    tags = []
    # app 端返回 tag_list，web_v4 端返回 hash_tag
    tag_list = note_list.get("tag_list", []) or note_list.get("tagList", []) or note_list.get("hash_tag", []) or []
    for t in tag_list:
        name = t.get("name", "")
        if name:
            tags.append(f"#{name}" if not name.startswith("#") else name)
    # 也从正文里匹配 #xxx
    for m in re.finditer(r'#[^\s#]+', desc):
        if m.group() not in tags:
            tags.append(m.group())

    # 互动数据（App 端和 Web 端字段名略有差异，全部兼容）
    interact = note_list.get("interact_info", {}) or note_list.get("interactInfo", {})
    likes = str(note_list.get("likes", "") or note_list.get("liked_count", "") or interact.get("liked_count", "") or interact.get("likedCount", ""))
    collects = str(note_list.get("collected_count", "") or interact.get("collected_count", "") or interact.get("collectedCount", ""))
    comments_count = str(note_list.get("comments_count", "") or interact.get("comment_count", "") or interact.get("comments_count", "") or interact.get("commentCount", ""))
    shares = str(note_list.get("shared_count", "") or interact.get("shared_count", "") or interact.get("shareCount", ""))

    # 作者（web_v4: user 在外层，但也会在 note_list 内部出现）
    user = note_list.get("user", {}) or note_list.get("author", {}) or {}
    author_name = user.get("nickname", "") or user.get("name", "")
    author_avatar = user.get("avatar", "") or user.get("image", "")

    # 时间
    ts = note_list.get("time", 0) or note_list.get("create_time", 0)
    date_text = ""
    if ts:
        try:
            if ts > 10000000000:
                dt = datetime.fromtimestamp(ts / 1000.0)
            else:
                dt = datetime.fromtimestamp(ts)
            date_text = f"发布于 {dt.strftime('%Y-%m-%d')}"
        except Exception:
            pass

    # 图片
    images = []
    images_list = note_list.get("images_list", []) or note_list.get("image_list", []) or note_list.get("imageList", []) or []
    for img in images_list:
        url = img.get("original", "") or img.get("url", "") or img.get("url_default", "")
        if url and not url.startswith("http"):
            url = "https:" + url if url.startswith("//") else "https://sns-webpic-qc.xhscdn.com/" + url
        if url:
            images.append(url)

    # 视频
    video_url = ""
    is_video = note_list.get("type") in ["video", "normal_video", "2"] or bool(note_list.get("video") or note_list.get("video_info"))
    if is_video:
        video_info = note_list.get("video", {}) or {}
        media = video_info.get("media", {}) or {}
        stream = media.get("stream", {}) or {}
        video_url = _extract_video_url(note_list)
        h264 = stream.get("h264", []) or stream.get("h265", [])
        if not video_url and h264 and len(h264) > 0:
            video_url = h264[0].get("master_url", "") or h264[0].get("masterUrl", "") or h264[0].get("url", "")
        if not video_url:
            video_url = video_info.get("url", "") or note_list.get("video_url", "")

    note_type = "视频" if is_video else "图文"
    page_url = f"https://www.xiaohongshu.com/explore/{note_id}" if not note_id.startswith("http") else note_id

    # ━━ HTML 直搜兜底机制 ━━
    # 如果 API 返回了 is_video 但抹除了 video 字段，直接强取源网页 HTML 用正则暴破！
    if is_video and not video_url:
        print("  ⚠️ TikHub API 视频地址缺失，尝试直接从 HTML 源码暴力提取...")
        try:
            import requests
            # 必须用浏览器 UA 伪装，否则不出数据
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            
            # 由于高优风控笔记必须带 xsec_token 才能访问页面，这里需拼接
            request_url = page_url
            if xsec_token:
                request_url = f"{page_url}?xsec_token={xsec_token}"
                
            r = requests.get(request_url, headers=headers, timeout=10)
            # 处理小红书特有的 unicode 斜杠转义
            html_text = r.text.replace("\\u002F", "/")
            vids = re.findall(r'https?://[^\"\'\s]+\.mp4[^\"\'\s]*', html_text)
            if vids:
                # 优先挑 https 的源
                https_vids = [v for v in vids if v.startswith("https")]
                video_url = https_vids[0] if https_vids else vids[0]
                print(f"  ✅ HTML 暴力提取成功: {video_url[:60]}...")
        except Exception as e:
            print(f"  ⚠️ HTML 提取失败: {e}")

    return {
        "title": title,
        "content": desc,
        "tags": tags,
        "likes": likes,
        "collects": collects,
        "comments": comments_count,
        "shares": shares,
        "authorName": author_name,
        "authorAvatar": author_avatar,
        "dateText": date_text,
        "images": images,
        "videoUrl": video_url,
        "isVideo": is_video,
        "noteType": note_type,
        "pageUrl": page_url
    }


def _dig_note_from_response(res: dict) -> dict:
    """从 TikHub 各端点返回的 JSON 中挖出实际的笔记 dict。"""
    return _find_first_note(res)


def fetch_note_detail(note_id: str, api_key: str, xsec_token: Optional[str] = None) -> dict:
    """调用 TikHub API 获取笔记详情，自动容错链：App V2 → App → Web V3 → Web。"""
    note_id_clean = extract_note_id(note_id)
    share_url = note_id if note_id.startswith("http") else f"https://www.xiaohongshu.com/explore/{note_id_clean}"
    endpoints = [
        ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", {"note_id": note_id_clean}),
        ("/api/v1/xiaohongshu/app_v2/get_image_note_detail", {"note_id": note_id_clean}),
        ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", {"share_text": share_url}),
        ("/api/v1/xiaohongshu/app_v2/get_image_note_detail", {"share_text": share_url}),
        ("/api/v1/xiaohongshu/app/get_note_info", {"note_id": note_id_clean}),
        ("/api/v1/xiaohongshu/app/get_note_info", {"share_text": share_url}),
        ("/api/v1/xiaohongshu/app/get_note_info_v2", {"note_id": note_id_clean}),
        ("/api/v1/xiaohongshu/web_v3/fetch_note_detail", {"note_id": note_id_clean, "xsec_token": xsec_token or ""}),
        ("/api/v1/xiaohongshu/web/get_note_info_v4", {"note_id": note_id_clean}),
        ("/api/v1/xiaohongshu/web/get_note_info_v4", {"share_text": share_url}),
    ]

    for endpoint, params in endpoints:
        try:
            res = api_get(endpoint, params, api_key)
            note_raw = _dig_note_from_response(res)
            if note_raw.get("title") or note_raw.get("display_title") or note_raw.get("desc") or note_raw.get("video") or note_raw.get("image_list"):
                print(f"  📡 数据源: {endpoint}")
                return _parse_note_raw(note_raw, note_id_clean, xsec_token or "")
            print(f"  ⚠️ {endpoint} 返回数据为空，继续降级...")
        except Exception as e:
            print(f"  ⚠️ {endpoint} 失败: {e}")

    print("  ❌ TikHub 所有详情端点均失败")
    sys.exit(1)

def fetch_comments(note_id: str, api_key: str, max_comments: int = 20, xsec_token: Optional[str] = None) -> list:
    """调用 TikHub API 获取评论（自动容错链：app → web_v2）"""
    if note_id.startswith("http"):
        print("  ⚠️ 短链暂不支持评论抓取，跳过评论步骤")
        return []

    comments = []

    # ── 策略 1: app/get_note_comments ──
    try:
        res = api_get("/api/v1/xiaohongshu/app/get_note_comments", {"note_id": note_id}, api_key)
        data = res.get("data", {}).get("data", {})
        comment_list = data.get("comments", []) or []
        for c in comment_list[:max_comments]:
            user_info = c.get("user_info", {}) or {}
            comments.append({
                "nickname": user_info.get("nickname", "") or c.get("nickname", ""),
                "content": c.get("content", ""),
                "likes": str(c.get("like_count", "") or c.get("likes", ""))
            })
        if comments:
            return comments
    except Exception as e:
        print(f"  ⚠️ app 评论端点失败: {e}")

    # ── 策略 2: web/get_note_comments（需要 xsec_token）──
    if xsec_token and not comments:
        try:
            print("  🔄 尝试 web 评论端点...")
            params = {"note_id": note_id, "xsec_token": xsec_token}
            res = api_get("/api/v1/xiaohongshu/web/get_note_comments", params, api_key)
            data = res.get("data", {}).get("data", {})
            comment_list = data.get("comments", []) or []
            for c in comment_list[:max_comments]:
                user_info = c.get("user_info", {}) or c.get("user", {}) or {}
                comments.append({
                    "nickname": user_info.get("nickname", "") or user_info.get("name", "") or c.get("nickname", ""),
                    "content": c.get("content", ""),
                    "likes": str(c.get("like_count", "") or c.get("likes", "") or c.get("liked_count", ""))
                })
        except Exception as e:
            print(f"  ⚠️ web 评论端点也失败: {e}")

    return comments


# ═══════════════════════════════════════════════════════════════
# 2. 视觉处理（复用 CDP 版逻辑）
# ═══════════════════════════════════════════════════════════════

def find_ffmpeg() -> Optional[str]:
    """获取跨平台内置的 ffmpeg"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil
        ffmpeg_cmd = shutil.which("ffmpeg")
        if ffmpeg_cmd:
            return ffmpeg_cmd
        for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
            if os.path.exists(p):
                return p
        return None

def download_video_for_analysis(video_url: str, output_path: str) -> Optional[str]:
    """下载视频并提取音频"""
    if not video_url:
        return None
    try:
        ffmpeg_cmd = find_ffmpeg()
        if not ffmpeg_cmd:
            print("  ⚠️ 未找到 ffmpeg，跳过音频提取")
            return None
        audio_path = output_path.replace('.mp4', '_audio.wav')
        subprocess.run([
            ffmpeg_cmd, '-i', video_url,
            '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
            audio_path, '-y'
        ], capture_output=True, timeout=60)
        if os.path.exists(audio_path):
            print(f"  🎵 音频已提取: {audio_path}")
            return audio_path
    except Exception as e:
        print(f"  ⚠️ 视频音频提取失败: {e}")
    return None

def transcribe_audio(audio_path: str) -> Optional[str]:
    """多级降级策略提取音频文案"""
    print("  🎙️ 尝试自动转录视频文案...")

    # 策略 1: 硅基流动
    sf_key = os.environ.get("SILICONFLOW_API_KEY")
    if sf_key:
        try:
            print("    [1/4] 尝试硅基流动 SenseVoice...")
            with open(audio_path, "rb") as f:
                resp = req_lib.post(
                    "https://api.siliconflow.cn/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {sf_key}"},
                    files={"file": ("audio.wav", f, "audio/wav")},
                    data={"model": "FunAudioLLM/SenseVoiceSmall"},
                    timeout=120
                )
            if resp.status_code == 200:
                text = resp.json().get("text", "")
                if text:
                    print("    ✅ 硅基流动转录成功！")
                    return text
        except Exception as e:
            print(f"    ⚠️ 硅基流动异常: {e}")

    # 策略 2: OpenAI Whisper
    api_key = os.environ.get("OPENAI_API_KEY")
    api_base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    if api_key:
        try:
            print("    [2/4] 尝试 OpenAI Whisper...")
            with open(audio_path, "rb") as f:
                resp = req_lib.post(
                    f"{api_base}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": ("audio.wav", f, "audio/wav")},
                    data={"model": "whisper-1"},
                    timeout=120
                )
            if resp.status_code == 200:
                text = resp.json().get("text", "")
                if text:
                    print("    ✅ OpenAI Whisper 转录成功！")
                    return text
        except Exception as e:
            print(f"    ⚠️ OpenAI API 异常: {e}")

    # 策略 3: 本地 whisper
    try:
        check = subprocess.run(["which", "whisper"], capture_output=True, text=True, timeout=5)
        if check.returncode == 0:
            print("    [3/4] 本地 whisper 离线转录...")
            subprocess.run(
                ["whisper", audio_path, "--model", "small", "--language", "zh",
                 "--output_format", "txt", "--output_dir", os.path.dirname(audio_path)],
                capture_output=True, text=True, timeout=300
            )
            txt_path = audio_path.rsplit(".", 1)[0] + ".txt"
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
                if text:
                    print("    ✅ 本地 whisper 转录成功！")
                    return text
    except Exception:
        pass

    # 策略 4: 强制要求
    print("    ❌ 未检测到可用的转录引擎！请配置 SILICONFLOW_API_KEY")
    return None

def extract_storyboard(video_path: str, output_dir: str, interval: int = 3) -> Optional[str]:
    """从视频截帧并拼接成九宫格故事板"""
    ffmpeg_cmd = find_ffmpeg()
    if not ffmpeg_cmd:
        print("  ⚠️ 未找到 ffmpeg，跳过故事版生成")
        return None

    import shutil
    frames_dir = os.path.join(output_dir, "_frames")
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)
    os.makedirs(frames_dir, exist_ok=True)
    storyboard_path = os.path.join(output_dir, "storyboard.jpg")

    try:
        probe = subprocess.run([ffmpeg_cmd, "-i", video_path], capture_output=True, text=True, timeout=10)
        duration = 60.0
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", probe.stderr)
        if match:
            h, m, s = match.groups()
            duration = int(h) * 3600 + int(m) * 60 + float(s)

        total_frames = max(1, int(duration / interval))
        print(f"  🎞️ 视频时长 {duration:.0f}s，每 {interval}s 截帧，预计 {total_frames} 帧")

        subprocess.run(
            [ffmpeg_cmd, '-i', video_path,
             '-vf', f'fps=1/{interval},scale=480:-1',
             '-q:v', '3',
             os.path.join(frames_dir, 'frame_%03d.jpg'), '-y'],
            capture_output=True, timeout=60
        )

        frame_files = sorted(glob.glob(os.path.join(frames_dir, 'frame_*.jpg')))
        if not frame_files:
            print("  ⚠️ 截帧失败")
            return None

        cols = min(5, len(frame_files))
        rows = math.ceil(len(frame_files) / cols)

        tile_filter = f"tile={cols}x{rows}:padding=4:color=white"
        cmd = [ffmpeg_cmd] + sum([['-i', f] for f in frame_files], []) + [
            '-filter_complex',
            ''.join([f'[{i}:v]' for i in range(len(frame_files))]) +
            f'concat=n={len(frame_files)}:v=1:a=0[merged];[merged]{tile_filter}',
            '-q:v', '2', storyboard_path, '-y'
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if os.path.exists(storyboard_path):
            size_kb = os.path.getsize(storyboard_path) / 1024
            print(f"  🖼️ 故事版已生成: {storyboard_path} ({size_kb:.0f}KB, {cols}×{rows})")
            return storyboard_path
        else:
            return frames_dir
    except Exception as e:
        print(f"  ⚠️ 故事版生成异常: {e}")
        return None

def _normalize_image_url(url: str) -> str:
    """将小红书 CDN 图片 URL 中的 HEIF 格式替换为 JPEG（Pillow 原生支持）。
    小红书 CDN 的 imageView2 接口支持 format 参数动态切换输出格式，
    只需把 format/heif 改成 format/jpg 即可获取标准 JPEG。"""
    import re as _re
    # 替换 format/heif 或 format/heic 为 format/jpg
    normalized = _re.sub(r'format/heif|format/heic', 'format/jpg', url)
    return normalized


def _download_image_with_fallback(url: str) -> "Image.Image | None":
    """下载单张图片，三级容错：
    1. URL 格式转 JPEG（最快最稳）
    2. 原始 URL + pillow-heif 解码
    3. 原始 URL + ffmpeg 转 JPEG"""
    from PIL import Image
    from io import BytesIO

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.xiaohongshu.com/",
    }

    # ── 策略 1: URL 格式转换 (format/heif → format/jpg) ──
    jpg_url = _normalize_image_url(url)
    try:
        resp = req_lib.get(jpg_url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 1000:
            img = Image.open(BytesIO(resp.content))
            return img
    except Exception:
        pass

    # ── 策略 2: 原始 URL + pillow-heif 解码 ──
    try:
        resp = req_lib.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 1000:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
                img = Image.open(BytesIO(resp.content))
                return img
            except ImportError:
                pass
            except Exception:
                pass
    except Exception:
        pass

    # ── 策略 3: 原始 URL + ffmpeg 强转 JPEG ──
    try:
        import tempfile
        resp = req_lib.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 1000:
            ffmpeg_cmd = find_ffmpeg()
            if ffmpeg_cmd:
                with tempfile.NamedTemporaryFile(suffix='.heif', delete=False) as tmp_in:
                    tmp_in.write(resp.content)
                    tmp_in_path = tmp_in.name
                tmp_out_path = tmp_in_path.replace('.heif', '.jpg')
                try:
                    subprocess.run(
                        [ffmpeg_cmd, '-i', tmp_in_path, '-q:v', '2', tmp_out_path, '-y'],
                        capture_output=True, timeout=10
                    )
                    if os.path.exists(tmp_out_path) and os.path.getsize(tmp_out_path) > 0:
                        img = Image.open(tmp_out_path)
                        img.load()  # 强制读入内存
                        return img
                finally:
                    for p in [tmp_in_path, tmp_out_path]:
                        try:
                            os.unlink(p)
                        except Exception:
                            pass
    except Exception:
        pass

    return None


def extract_image_board(image_urls: list, output_dir: str) -> Optional[str]:
    """下载图文笔记的图片并拼接成拼接卡（支持 HEIF/JPEG/WebP/PNG 多格式容错）"""
    try:
        from PIL import Image, ImageOps
        import shutil

        if not image_urls:
            return None

        print(f"  📸 下载 {len(image_urls)} 张配图，生成视觉拼接卡...")
        images = []

        frames_dir = os.path.join(output_dir, "_frames")
        if os.path.exists(frames_dir):
            shutil.rmtree(frames_dir)
        os.makedirs(frames_dir, exist_ok=True)

        for i, url in enumerate(image_urls):
            img = _download_image_with_fallback(url)
            if img is not None:
                try:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    images.append(img)
                    img.save(os.path.join(frames_dir, f"frame_{i+1:03d}.jpg"), quality=85)
                except Exception as e:
                    print(f"    ⚠️ 图片 {i+1} 转换失败: {e}")
            else:
                print(f"    ⚠️ 图片 {i+1}/{len(image_urls)} 所有下载策略均失败，跳过")

        if not images:
            print("  ❌ 所有图片下载失败")
            return None

        print(f"  ✅ 成功下载 {len(images)}/{len(image_urls)} 张图片")

        target_w, target_h = 400, 533
        cols = min(4, len(images))
        rows = math.ceil(len(images) / cols)

        collage = Image.new('RGB', (cols * target_w, rows * target_h), (255, 255, 255))
        for i, img in enumerate(images):
            thumb = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
            x = (i % cols) * target_w
            y = (i // cols) * target_h
            collage.paste(thumb, (x, y))

        board_path = os.path.join(output_dir, "storyboard.jpg")
        collage.save(board_path, quality=85)
        print(f"  🖼️ 图文拼接卡已生成: {board_path} (网格: {cols}x{rows})")
        return board_path
    except Exception as e:
        print(f"  ⚠️ 生成图文拼接卡失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# 3. 主流程
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="小红书单篇笔记数据抓取器（TikHub API 版）")
    parser.add_argument("--url", required=True, help="笔记详情页 URL 或笔记 ID")
    parser.add_argument("--output", "-o", default="outputs/note_data.json", help="输出文件路径")
    parser.add_argument("--max-comments", type=int, default=20, help="最多抓取评论数")
    args = parser.parse_args()

    api_key = os.environ.get("TIKHUB_API_KEY")
    if not api_key:
        print("❌ 错误: 未设置 TIKHUB_API_KEY 环境变量！")
        print("💡 配置方法: export TIKHUB_API_KEY=your_key")
        print("💡 注册地址: https://user.tikhub.io/")
        sys.exit(1)

    note_id = extract_note_id(args.url)
    xsec_token = extract_xsec_token(args.url)
    print(f"🔗 解析 Note ID: {note_id}")
    if xsec_token:
        print(f"🔑 提取到 xsec_token: {xsec_token[:15]}...")

    # ── 抓取笔记详情（自动容错链：app → web_v4）──
    print("📝 通过 TikHub API 获取笔记详情...")
    note_data = fetch_note_detail(note_id, api_key, xsec_token)
    print(f"  标题: {note_data.get('title', 'N/A')}")
    print(f"  作者: {note_data.get('authorName', 'N/A')}")
    print(f"  类型: {note_data.get('noteType', 'N/A')}")
    print(f"  图片数: {len(note_data.get('images', []))}")

    # ── 抓取评论（自动容错链：app → web）──
    print(f"💬 获取 TOP {args.max_comments} 条评论...")
    comments = fetch_comments(note_id, api_key, args.max_comments, xsec_token)
    print(f"  获取到 {len(comments)} 条评论")

    # ── 视觉处理 ──
    base_dir = os.path.dirname(args.output) or '.'
    os.makedirs(base_dir, exist_ok=True)

    if note_data.get('isVideo') and note_data.get('videoUrl'):
        print("🎬 检测到视频笔记，下载视频...")
        video_local_path = os.path.join(base_dir, "video.mp4")
        try:
            import requests
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.xiaohongshu.com/",
            }
            with requests.get(note_data['videoUrl'], headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(video_local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            print(f"  📥 视频下载成功: {video_local_path}")
            audio_path = download_video_for_analysis(video_local_path, video_local_path)
            if audio_path:
                note_data['audioLocalPath'] = audio_path
                audio_text = transcribe_audio(audio_path)
                if audio_text:
                    note_data['audioText'] = audio_text

            print("🎞️ 生成视频故事版...")
            storyboard = extract_storyboard(video_local_path, base_dir)
            if storyboard:
                note_data['storyboardPath'] = storyboard
        except Exception as e:
            print(f"  ⚠️ 视频处理失败: {e}")
    else:
        print("🖼️ 图文笔记，生成拼接图...")
        storyboard = extract_image_board(note_data.get('images', []), base_dir)
        if storyboard:
            note_data['storyboardPath'] = storyboard

    # ── 保存输出 ──
    output = {
        "note": note_data,
        "comments": comments,
        "scrapedAt": datetime.now().isoformat(),
        "sourceUrl": args.url
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 账单
    api_calls = 2  # note_info + comments
    cost_usd = api_calls * 0.001
    print(f"\n💾 笔记数据已保存到: {args.output}")
    print(f"💸 本次 API 调用: {api_calls} 次 (≈ ${cost_usd:.3f} USD)")


if __name__ == "__main__":
    main()

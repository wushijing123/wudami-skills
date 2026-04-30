#!/usr/bin/env python3
import sys
import os
import re
import json
import requests
import tempfile
import argparse
import io
import base64
import subprocess
import time
import shutil

try:
    from PIL import Image
except ImportError:
    Image = None

TIKHUB_BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
TIKHUB_TIMEOUT = float(os.environ.get("TIKHUB_TIMEOUT", "45"))
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"

def extract_xsec_token(url: str) -> str:
    m = re.search(r'xsec_token=([^&]+)', url)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    return ""

def _first_non_empty(*values):
    for value in values:
        if value:
            return value
    return ""

def _find_first_note(data):
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
        if cur.get("desc") is not None or cur.get("title") is not None or cur.get("display_title") is not None or cur.get("displayTitle") is not None or cur.get("video") or cur.get("video_info_v2") or cur.get("video_info"):
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

def _extract_cover_url(note: dict) -> str:
    for key in ("images_list", "image_list", "images"):
        images = note.get(key) if isinstance(note, dict) else None
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                return _first_non_empty(first.get("url"), first.get("original"), first.get("urlDefault"), first.get("url_default"))
            if isinstance(first, str):
                return first
    cover = note.get("cover") if isinstance(note, dict) else None
    if isinstance(cover, dict):
        return _first_non_empty(cover.get("urlDefault"), cover.get("urlPre"), cover.get("url"), cover.get("url_default"))
    if isinstance(cover, str):
        return cover
    return ""

def _html_video_fallback(note_id: str, xsec_token: str = "") -> str:
    note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token:
        note_url = f"{note_url}?xsec_token={xsec_token}"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        r = requests.get(note_url, headers=headers, timeout=20)
        html_text = r.text.replace("\\u002F", "/")
        vids = re.findall(r'https?://[^"\'\s]+\.mp4[^"\'\s]*', html_text)
        if vids:
            https_vids = [v for v in vids if v.startswith("https")]
            return https_vids[0] if https_vids else vids[0]
    except Exception as e:
        print(f"⚠️ HTML 视频兜底失败: {e}", file=sys.stderr)
    return ""

def fetch_note_detail_from_tikhub(note_id: str, url_or_id: str, api_key: str):
    headers = {"Authorization": f"Bearer {api_key}"}
    xsec_token = extract_xsec_token(url_or_id)
    share_url = url_or_id if url_or_id.startswith("http") else f"https://www.xiaohongshu.com/explore/{note_id}"
    endpoints = [
        ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", {"note_id": note_id}),
        ("/api/v1/xiaohongshu/app_v2/get_image_note_detail", {"note_id": note_id}),
        ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", {"share_text": share_url}),
        ("/api/v1/xiaohongshu/app_v2/get_image_note_detail", {"share_text": share_url}),
        ("/api/v1/xiaohongshu/app/get_note_info", {"note_id": note_id}),
        ("/api/v1/xiaohongshu/app/get_note_info", {"share_text": share_url}),
        ("/api/v1/xiaohongshu/web_v3/fetch_note_detail", {"note_id": note_id, "xsec_token": xsec_token}),
        ("/api/v1/xiaohongshu/web/get_note_info_v4", {"note_id": note_id}),
        ("/api/v1/xiaohongshu/web/get_note_info_v4", {"share_text": share_url}),
    ]
    for endpoint, params in endpoints:
        try:
            res = requests.get(f"{TIKHUB_BASE_URL}{endpoint}", params=params, headers=headers, timeout=TIKHUB_TIMEOUT)
            if res.status_code != 200:
                print(f"⚠️ {endpoint} 返回 HTTP {res.status_code}: {res.text[:200]}", file=sys.stderr)
                continue
            note = _find_first_note(res.json())
            if note:
                print(f"✅ TikHub 详情接口命中: {endpoint}", file=sys.stderr)
                return note, xsec_token
        except Exception as e:
            print(f"⚠️ {endpoint} 请求错误: {e}", file=sys.stderr)
    return {}, xsec_token

def get_sf_key() -> str:
    sf_key = os.environ.get("SILICONFLOW_API_KEY")
    if not sf_key:
        print(json.dumps({"error": "未设置 SILICONFLOW_API_KEY 环境变量"}, ensure_ascii=False))
        sys.exit(1)
    return sf_key

def _ffmpeg_convert_heif(raw_bytes: bytes):
    """用 ffmpeg 将 HEIF 字节流转为 PIL RGB Image（兜底方案）"""
    if Image is None:
        return None
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

def _url_to_base64_jpeg(cover_url: str) -> str:
    """下载图片并统一转为 JPEG base64 data URI（自动处理 HEIF/WebP/AVIF）。"""
    if Image is None:
        return "[图片处理依赖缺失] 请安装 Pillow (pip install Pillow)"
        
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
    headers = {"User-Agent": "Mozilla/5.0"}
    with requests.get(video_url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

def extract_audio(video_path: str) -> str:
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

def extract_single_note(url_or_id):
    # 提取 note_id
    note_id = url_or_id
    m = re.search(r'explore/([a-zA-Z0-9]+)', url_or_id)
    if m:
        note_id = m.group(1)
        
    print(f"🔄 开始独立抓取单篇笔记 (ID: {note_id})...", file=sys.stderr)
    
    tikhub_key = os.environ.get('TIKHUB_API_KEY')
    if not tikhub_key:
        print(json.dumps({"error": "未设置 TIKHUB_API_KEY 环境变量"}, ensure_ascii=False))
        return
        
    try:
        note, xsec_token = fetch_note_detail_from_tikhub(note_id, url_or_id, tikhub_key)
        if not note:
            print(json.dumps({"error": "TikHub API 异常或超时，且未获取到笔记数据"}, ensure_ascii=False))
            return

        title = note.get("displayTitle") or note.get("display_title") or note.get("title", "")
        desc = note.get("desc", "")
        n_type = str(note.get("type", ""))
        is_video = n_type == "video" or n_type == "2" or note.get("video")
        
        # 提取图片封面
        cover_url = _extract_cover_url(note)
                
        # 提取视频 URL
        video_url = ""
        if is_video:
            video_url = _extract_video_url(note) or _html_video_fallback(note_id, xsec_token)
            
        # 开始调用大模型提纯
        print(f"👁️‍🗨️ 开始提取封面文字排版...", file=sys.stderr)
        cover_text = analyze_cover_text_with_vlm(cover_url)
        
        spoken_text = ""
        if is_video and video_url:
            print(f"🎙️ 检测到视频，开始剥离音轨并生成 ASR...", file=sys.stderr)
            with tempfile.TemporaryDirectory() as temp_dir:
                v_path = os.path.join(temp_dir, "source.mp4")
                try:
                    download_video(video_url, v_path)
                    a_path = extract_audio(v_path)
                    spoken_text = transcribe_audio_with_sf(a_path)
                except Exception as e:
                    spoken_text = f"视频提取失败: {e}"
        
        result = {
            "title": title.replace('\n', ' '),
            "desc": desc,
            "cover_text": cover_text,
            "asr": spoken_text,
            "is_video": bool(is_video)
        }
        
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
    except Exception as e:
        print(json.dumps({"error": f"执行异常: {str(e)}"}, ensure_ascii=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser("wudami-xhs-viral-analyzer 单笔记深度萃取工具 (Self-contained)")
    parser.add_argument("url_or_id", help="小红书笔记的 URL 或 Note ID")
    args = parser.parse_args()
    
    extract_single_note(args.url_or_id)

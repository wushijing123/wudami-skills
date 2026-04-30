#!/usr/bin/env python3
import os
import sys
import re
import time
import json
import requests
import argparse
import tempfile
import subprocess
from urllib.parse import unquote

# ================= 鉴权阻断 =================
TIKHUB_API_KEY = os.environ.get("TIKHUB_API_KEY")
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY")
TIKHUB_BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
TIKHUB_TIMEOUT = float(os.environ.get("TIKHUB_TIMEOUT", "45"))

if not TIKHUB_API_KEY or not SILICONFLOW_API_KEY:
    print("❌ Error: 必须先在环境变量中配置 TIKHUB_API_KEY 和 SILICONFLOW_API_KEY，否则脚本拒止运行。", file=sys.stderr)
    print("无口播返回", file=sys.stdout)
    sys.exit(1)

# ================= 核心工具函数 =================
def extract_note_id(url: str) -> str:
    """提取小红书URL中的 note_id"""
    match = re.search(r'/explore/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/discovery/item/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/user/profile/[a-zA-Z0-9]+/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    
    # 尝试直接假设传入的就是 note_id (纯字母数字组合，长度大概在24位左右不固定，大于10位即可)
    if re.match(r'^[a-zA-Z0-9]{15,}$', url.strip()):
        return url.strip()
        
    print(f"❌ Error: 无法解析出正确的小红书 note_id: {url}", file=sys.stderr)
    return ""

def extract_xsec_token(url: str) -> str:
    match = re.search(r'xsec_token=([^&]+)', url)
    return unquote(match.group(1)) if match else ""

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
        if cur.get("desc") is not None or cur.get("title") is not None or cur.get("display_title") is not None or cur.get("video") or cur.get("video_info_v2") or cur.get("video_info"):
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

def _html_video_fallback(url: str, note_id: str, xsec_token: str) -> str:
    request_url = url if url.startswith("http") else f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token and "xsec_token=" not in request_url:
        request_url = f"{request_url}?xsec_token={xsec_token}"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        r = requests.get(request_url, headers=headers, timeout=20)
        html_text = r.text.replace("\\u002F", "/")
        vids = re.findall(r'https?://[^"\'\s]+\.mp4[^"\'\s]*', html_text)
        if vids:
            https_vids = [v for v in vids if v.startswith("https")]
            return https_vids[0] if https_vids else vids[0]
    except Exception as e:
        print(f"⚠️ HTML 视频兜底失败: {e}", file=sys.stderr)
    return ""

def get_video_url(url: str) -> str:
    """调用 TikHub 提取无水印视频直连"""
    note_id = extract_note_id(url)
    if not note_id: return ""
    
    xsec_token = extract_xsec_token(url)
    headers = {
        "Authorization": f"Bearer {TIKHUB_API_KEY}"
    }
        
    print(f"[DEBUG] get_video_url called with note_id: '{note_id}', xsec_token_length: {len(xsec_token)}", file=sys.stderr)

    note_params = {"note_id": note_id}
    share_params = {"share_text": url if url.startswith("http") else f"https://www.xiaohongshu.com/explore/{note_id}"}
    endpoints = [
        ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", note_params),
        ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", share_params),
        ("/api/v1/xiaohongshu/app/get_note_info", note_params),
        ("/api/v1/xiaohongshu/app/get_note_info", share_params),
        ("/api/v1/xiaohongshu/web_v3/fetch_note_detail", {"note_id": note_id, "xsec_token": xsec_token}),
        ("/api/v1/xiaohongshu/web/get_note_info_v4", note_params),
        ("/api/v1/xiaohongshu/web/get_note_info_v4", share_params),
    ]

    for endpoint, payload in endpoints:
        try:
            res = requests.get(f"{TIKHUB_BASE_URL}{endpoint}", headers=headers, params=payload, timeout=TIKHUB_TIMEOUT)
            if res.status_code != 200:
                print(f"⚠️ {endpoint} 返回 HTTP {res.status_code}: {res.text[:200]}", file=sys.stderr)
                continue
            note = _find_first_note(res.json())
            if not note:
                continue
            note_type = str(note.get("type", ""))
            if note_type and note_type not in ("video", "2", "normal_video") and not note.get("video") and not note.get("video_info_v2") and not note.get("video_info"):
                return ""
            video_url = _extract_video_url(note)
            if video_url:
                print(f"[DEBUG] TikHub endpoint hit: {endpoint}", file=sys.stderr)
                return video_url
        except Exception as e:
            print(f"⚠️ {endpoint} 请求错误: {e}", file=sys.stderr)
	            
    return _html_video_fallback(url, note_id, xsec_token)

def extract_audio_via_ffmpeg(video_url: str) -> str:
    """静默使用 ffmpeg 获取网络流中的音频到临时临时文件"""
    temp_dir = tempfile.gettempdir()
    output_wav = os.path.join(temp_dir, f"single_audio_{int(time.time())}.wav")
    
    if os.path.exists(output_wav):
        os.remove(output_wav)
        
    cmd = [
        "ffmpeg", "-i", video_url,
        "-q:a", "0", "-map", "a",
        "-ar", "16000", "-ac", "1",
        output_wav,
        "-y"
    ]
    try:
        # 只捕捉错误，正常进度条统统隐藏，防止污染大模型解析口
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_wav
    except subprocess.CalledProcessError:
        return ""

def transcribe_audio_sf(file_path: str) -> str:
    """投喂给物理接口获取转写结果"""
    sf_key = SILICONFLOW_API_KEY
    url = "https://api.siliconflow.cn/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {sf_key}"}
    data = {"model": "FunAudioLLM/SenseVoiceSmall"}
    
    try:
        with open(file_path, "rb") as f:
            files = {"file": f}
            res = requests.post(url, headers=headers, data=data, files=files, timeout=60)
            if res.status_code == 200:
                out = res.json().get("text", "")
                if out:
                    # 洗掉系统返回的一些机器注音角标符如 <|zh|>
                    out = re.sub(r'<[^>]+>', '', out)
                    return f"🎼 {out.strip()}"
    except Exception as e:
        pass
    return ""

def main():
    parser = argparse.ArgumentParser(description="提取单条小红书原声口播。结果通过标准输出(stdout)抛出，供机器人流读取。")
    parser.add_argument("--url", required=True, help="小红书分享链接或单纯的 note_id")
    args = parser.parse_args()

    # 1. 提取ID
    note_id = extract_note_id(args.url)
    if not note_id:
        print("", file=sys.stdout) # 失败吐出空串
        return
        
    # 2. 嗅探视频直连
    video_url = get_video_url(args.url)
    if not video_url:
        print("", file=sys.stdout) # 图文笔记无口播，返回空
        return
        
    # 3. 剥离无损音轨
    wav_path = extract_audio_via_ffmpeg(video_url)
    if not wav_path or not os.path.exists(wav_path):
        print("", file=sys.stdout)
        return
        
    # 4. SiliconFlow 大模型洗切
    transcript = transcribe_audio_sf(wav_path)
    
    # 5. 打扫战场，静默输出最终成就
    try:
        os.remove(wav_path)
    except:
        pass
        
    # ====== 【极其重要的唯一输出端】 ======
    # 直接给最干净的字符串，千万别带着任何杂质
    print(transcript, file=sys.stdout)

if __name__ == "__main__":
    main()

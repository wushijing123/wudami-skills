#!/usr/bin/env python3
import os
import sys
import re
import time
import json
import base64
import requests
import argparse
import tempfile
import subprocess
from datetime import datetime
from urllib.parse import unquote

# ================= 鉴权阻断 =================
TIKHUB_API_KEY = os.environ.get("TIKHUB_API_KEY")
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY")
TIKHUB_BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
TIKHUB_TIMEOUT = float(os.environ.get("TIKHUB_TIMEOUT", "45"))

if not SILICONFLOW_API_KEY:
    print("❌ Error: 必须先在环境变量中配置 SILICONFLOW_API_KEY 才能运行此风控诊断工具。", file=sys.stderr)
    sys.exit(1)

# ================= 核心工具函数 =================
def extract_note_id(url: str) -> str:
    match = re.search(r'/explore/([a-zA-Z0-9]+)', url)
    if match: return match.group(1)
    match = re.search(r'/discovery/item/([a-zA-Z0-9]+)', url)
    if match: return match.group(1)
    if re.match(r'^[a-zA-Z0-9]{15,}$', url.strip()): return url.strip()
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

def _html_video_fallback(url_or_id: str, note_id: str, xsec_token: str) -> str:
    request_url = url_or_id if url_or_id.startswith("http") else f"https://www.xiaohongshu.com/explore/{note_id}"
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

def get_video_url(url_or_id: str) -> str:
    if not TIKHUB_API_KEY:
        print("❌ Error: 解析小红书链接需要 TIKHUB_API_KEY。", file=sys.stderr)
        sys.exit(1)
    note_id = extract_note_id(url_or_id)
    xsec_token = extract_xsec_token(url_or_id)
    headers = {"Authorization": f"Bearer {TIKHUB_API_KEY}", "Content-Type": "application/json"}
    note_params = {"note_id": note_id}
    share_params = {"share_text": url_or_id if url_or_id.startswith("http") else f"https://www.xiaohongshu.com/explore/{note_id}"}
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
            video_url = _extract_video_url(note)
            if video_url:
                print(f"✅ TikHub 详情接口命中: {endpoint}", file=sys.stderr)
                return video_url
        except Exception as e:
            print(f"⚠️ {endpoint} 请求失败: {e}", file=sys.stderr)

    return _html_video_fallback(url_or_id, note_id, xsec_token)

def download_video(video_url: str, output_path: str):
    print("⬇️ 正在下载视频...", file=sys.stderr)
    res = requests.get(video_url, stream=True)
    with open(output_path, 'wb') as f:
        for chunk in res.iter_content(chunk_size=1024*1024):
            if chunk: f.write(chunk)
    return output_path

def get_video_duration(video_path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode('utf-8').strip()
        return float(out)
    except:
        return 0.0

def extract_audio(video_path: str) -> str:
    temp_dir = tempfile.gettempdir()
    output_wav = os.path.join(temp_dir, f"audio_{int(time.time())}.wav")
    cmd = ["ffmpeg", "-i", video_path, "-q:a", "0", "-map", "a", "-ar", "16000", "-ac", "1", output_wav, "-y"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_wav

def extract_keyframes(video_path: str, duration: float) -> list:
    temp_dir = tempfile.gettempdir()
    # 策略：0秒(首帧)、3秒(完播生死线)、5秒(硬广危险区)、15秒(中段)、结尾前1秒
    times = [0, 3, 5, 15, max(duration - 1, 0)]
    times = sorted(list(set([t for t in times if t <= duration])))
    
    frames = []
    print(f"🎬 正在抽取关键帧 (截取时间点: {times})...", file=sys.stderr)
    for t in times:
        out_jpg = os.path.join(temp_dir, f"frame_{t}s_{int(time.time())}.jpg")
        cmd = ["ffmpeg", "-ss", str(t), "-i", video_path, "-vframes", "1", "-q:v", "2", out_jpg, "-y"]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(out_jpg):
            frames.append({"time": t, "path": out_jpg})
    return frames

# ================= AI 引擎 =================

def transcribe_audio_sf(file_path: str) -> str:
    print("🎙️ 正在进行 ASR 语音识别...", file=sys.stderr)
    url = "https://api.siliconflow.cn/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {SILICONFLOW_API_KEY}"}
    data = {"model": "FunAudioLLM/SenseVoiceSmall"}
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with open(file_path, "rb") as f:
                res = requests.post(url, headers=headers, data=data, files={"file": f}, timeout=60)
                if res.status_code == 200:
                    out = res.json().get("text", "")
                    return re.sub(r'<[^>]+>', '', out).strip()
                else:
                    print(f"⚠️ ASR API 异常 (尝试 {attempt+1}/{max_retries}): {res.status_code} - {res.text}", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ ASR 请求报错 (尝试 {attempt+1}/{max_retries}): {e}", file=sys.stderr)
        
        if attempt < max_retries - 1:
            time.sleep(2)  # 等待2秒后重试
            
    print("❌ ASR 语音识别最终失败，放弃提取口播。", file=sys.stderr)
    return ""

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def analyze_frame_vlm(frame: dict) -> str:
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }
    b64 = encode_image(frame["path"])
    payload = {
        "model": "Qwen/Qwen2-VL-72B-Instruct",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": "请简短客观描述这张视频截图中的画面内容。画面里有没有特写展示具体产品？有没有出现明显的品牌Logo或二维码引流？"}
                ]
            }
        ],
        "max_tokens": 150
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return "视觉解析失败"

def generate_diagnostic_report(transcript: str, visual_context: list) -> str:
    print("🧠 正在进行 LLM 风控限流深度诊断...", file=sys.stderr)
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }
    
    vision_str = "\n".join([f"- 第 {f['time']} 秒镜头: {f['desc']} (图片代码: ![{f['time']}s]({f.get('rel_path', '')}))" for f in visual_context])
    
    prompt = f"""
你是一个小红书短视频风控与爆款诊断专家（吴大咪体系）。
我将给你一个视频的【口播文案】和【关键帧视觉描述】。请你进行深度拆解和限流风控诊断。

【口播文案】：
{transcript if transcript else "(无口播或提取失败)"}

【关键帧视觉特征】：
{vision_str}

请输出一份Markdown报告，必须严格包含以下结构，并使用 GitHub Alerts 样式突出警告（> [!WARNING], > [!CAUTION], > [!TIP]）：

# 📊 笔记深度拆解与限流诊断报告

## 🚫 限流风控深度诊断
结合文案和视觉，分析是否踩中以下红线（如果有，请用警告样式突出；如果安全，请说明）：
- **文案与广告法红线**：是否包含极限词（最、超级等）、绝对化用语、拉踩竞品、虚假夸大功效。
- **视觉与节奏红线（完播率杀手）**：产品是否在视频前3-5秒就硬性露出缺乏铺垫？是否像低质硬广？有无明显的站外引流/二维码。

## 🧩 8段式深度分析（带视觉推演）

### 一、选题与痛点洞察
分析击中的痛点、场景，提炼爆款公式。

### 二、标题钩子拆解
提炼口播开头的钩子结构与情绪价值。

### 三、视觉推演逐段解析
请用 Markdown 表格展示视觉画面描述及作用。表格需包含【时间段】【关键帧画面】【镜头类型】【画面描述推演与作用】。
对于【关键帧画面】列，请直接填入我为你提供的对应时间段的 图片代码（如 ![0s](frames/xxx.jpg)）。如果没有，填“无”。

### 四、正文逻辑与文案拆解
拆解口播节奏（如痛点代入 -> 解法 -> 视觉论证 -> 情绪拉升）。

### 五、评论区与用户心理
(若未抓取到评论，请根据文案推测用户可能产生的共鸣点或槽点)

### 六、算法与运营策略
(推测这类视频在分发上的优势与劣势)

### 七、商业价值拆解
变现路径判断，合作笔记与带货潜力。

### 八、可复刻方法论与避坑
总结核心爆点、可复刻动作（你写脚本时可以偷的招），以及针对限流的修改优化建议。
"""

    payload = {
        "model": "Qwen/Qwen2.5-72B-Instruct",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0.7
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=180)
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"LLM 诊断失败: {e}"

def main():
    parser = argparse.ArgumentParser(description="小红书短视频风控与限流深度诊断工具")
    parser.add_argument("--url", help="小红书视频链接")
    parser.add_argument("--file", help="本地视频文件路径")
    args = parser.parse_args()

    if not args.url and not args.file:
        print("❌ Error: 必须提供 --url 或 --file。", file=sys.stderr)
        sys.exit(1)

    video_path = args.file
    temp_video = False

    # 1. 获取视频资源
    if args.url:
        note_id = extract_note_id(args.url)
        if not note_id:
            print("❌ Error: 无法解析小红书链接。", file=sys.stderr)
            sys.exit(1)
        video_url = get_video_url(args.url)
        if not video_url:
            print("❌ Error: 未找到视频流。", file=sys.stderr)
            sys.exit(1)
        video_path = os.path.join(tempfile.gettempdir(), f"vid_{note_id}.mp4")
        download_video(video_url, video_path)
        temp_video = True
    elif not os.path.exists(video_path):
        print(f"❌ Error: 文件不存在 {video_path}", file=sys.stderr)
        sys.exit(1)

    # 2. 时长与双轨提取
    duration = get_video_duration(video_path)
    wav_path = extract_audio(video_path)
    frames = extract_keyframes(video_path, duration)

    # 3. API 交互 (ASR & VLM)
    transcript = transcribe_audio_sf(wav_path) if wav_path and os.path.exists(wav_path) else ""
    
    print("👁️ 正在进行 VLM 视觉理解分析...", file=sys.stderr)
    for f in frames:
        f["desc"] = analyze_frame_vlm(f)

    # 4. 准备交付目录并移动图片
    base_out_dir = "/Users/wushijing/Obsidian仓库/吴大咪一人公司/02-素材库/脚本库"
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_name = os.path.basename(video_path).split('.')[0] if video_path else "未命名视频"
    if len(base_name) > 30: base_name = base_name[:30]
    
    target_folder = os.path.join(base_out_dir, f"{date_str}-限流诊断与拆解_{base_name}")
    os.makedirs(target_folder, exist_ok=True)
    frames_dir = os.path.join(target_folder, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    import shutil
    for f in frames:
        new_path = os.path.join(frames_dir, os.path.basename(f["path"]))
        if os.path.exists(f["path"]):
            shutil.move(f["path"], new_path)
            f["path"] = new_path
        f["rel_path"] = f"frames/{os.path.basename(new_path)}"

    # 5. LLM 诊断
    report = generate_diagnostic_report(transcript, frames)

    # 6. 输出交付
    out_filename = os.path.join(target_folder, f"{date_str}-限流诊断与拆解_{base_name}.md")
    with open(out_filename, "w", encoding="utf-8") as f:
        f.write(report)
    
    # 清理战场
    if temp_video and os.path.exists(video_path): os.remove(video_path)
    if wav_path and os.path.exists(wav_path): os.remove(wav_path)

    print(f"\n✅ 诊断完成！报告及抽帧已存入文件夹: {os.path.abspath(target_folder)}", file=sys.stdout)
    
if __name__ == "__main__":
    main()

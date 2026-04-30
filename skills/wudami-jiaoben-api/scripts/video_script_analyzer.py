#!/usr/bin/env python3
"""
wudami-jiaoben-api 核心抓取与分析脚本。
职责：
1. 提取 TikHub 的视频数据。
2. 音频提取并调用硅基流动 SenseVoice 语音转写。
3. 文本抛入 LLM 进行超详细长篇脚本拆解。
4. 输出带故事板图文的 Markdown 至 Obsidian 知识库。
"""

import argparse
import json
import os
import re
import sys
import math
import glob
import subprocess
from datetime import datetime
from typing import Optional

def ensure_dependencies():
    required = {
        "httpx": "httpx",
        "requests": "requests",
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
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", *missing, "-q"])
            except subprocess.CalledProcessError:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--break-system-packages", *missing, "-q"])
        print("✅ 依赖安装完成！")

ensure_dependencies()

import httpx
import requests

TIKHUB_BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
TIKHUB_TIMEOUT = float(os.environ.get("TIKHUB_TIMEOUT", "45"))
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"

# === 帮助函数 ===

def find_ffmpeg() -> Optional[str]:
    import shutil
    ffmpeg_cmd = shutil.which("ffmpeg")
    if ffmpeg_cmd: return ffmpeg_cmd
    for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if os.path.exists(p): return p
    # 如果系统没有安装命令行中的 ffmpeg，尝试借助 imageio_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return None

def extract_platform_and_id(url: str):
    url = url.strip()
    xsec_token = ""
    m_token = re.search(r'xsec_token=([^&]+)', url)
    if m_token:
        from urllib.parse import unquote
        xsec_token = unquote(m_token.group(1))

    if 'xiaohongshu.com' in url or 'xhslink.com' in url:
        m = re.search(r'explore/([a-zA-Z0-9]+)', url)
        if m: return "xiaohongshu", m.group(1), url, xsec_token
        m = re.search(r'item/([a-zA-Z0-9]+)', url)
        if m: return "xiaohongshu", m.group(1), url, xsec_token
        if 'xhslink.com' in url:
            return "xiaohongshu", url, url, xsec_token
        return "xiaohongshu", url, url, xsec_token
    elif 'douyin.com' in url:
        return "douyin", url, url, xsec_token
    return "unknown", url, url, xsec_token

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
        has_note_shape = (
            cur.get("desc") is not None or cur.get("title") is not None or
            cur.get("display_title") is not None or cur.get("video") or
            cur.get("video_info_v2") or
            cur.get("video_info")
        )
        if has_note_shape:
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

# === TikHub API 阶段 ===

def get_video_from_tikhub(platform: str, item_id: str, url: str, xsec_token: str) -> dict:
    tikhub_key = os.environ.get("TIKHUB_API_KEY")
    if not tikhub_key:
        print("❌ 错误: 未设置 TIKHUB_API_KEY 环境变量！")
        sys.exit(1)
        
    headers = {"Authorization": f"Bearer {tikhub_key}"}
    
    with httpx.Client(timeout=TIKHUB_TIMEOUT) as client:
        if platform == "xiaohongshu":
            api_failed = False
            title = ""
            desc = ""
            video_url = ""

            note_params = {"note_id": item_id} if not item_id.startswith("http") else {"share_text": item_id}
            share_params = {"share_text": url}
            detail_endpoints = [
                ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", note_params),
                ("/api/v1/xiaohongshu/app_v2/get_video_note_detail", share_params),
                ("/api/v1/xiaohongshu/app/get_note_info", note_params),
                ("/api/v1/xiaohongshu/app/get_note_info", share_params),
                ("/api/v1/xiaohongshu/web_v3/fetch_note_detail", {"note_id": item_id, "xsec_token": xsec_token} if not item_id.startswith("http") else share_params),
                ("/api/v1/xiaohongshu/web/get_note_info_v4", note_params),
                ("/api/v1/xiaohongshu/web/get_note_info_v4", share_params),
            ]
            for endpoint, params in detail_endpoints:
                try:
                    res = client.get(f"{TIKHUB_BASE_URL}{endpoint}", params=params, headers=headers)
                    res.raise_for_status()
                    note = _find_first_note(res.json())
                    if not note:
                        print(f"  ⚠️ {endpoint} 未解析到笔记详情")
                        continue
                    title = note.get("display_title") or note.get("title", "")
                    desc = note.get("desc", "")
                    video_url = _extract_video_url(note)
                    if video_url:
                        print(f"  ✅ TikHub 详情接口命中: {endpoint}")
                        break
                    print(f"  ⚠️ {endpoint} 未返回视频 URL")
                except Exception as e:
                    print(f"  ⚠️ {endpoint} 获取失败: {e}")
            if not video_url:
                api_failed = True

            # ━━ HTML 直搜兜底机制 ━━
            if api_failed or not video_url:
                print("  ⚠️ TikHub API 视频地址缺失或彻底失败，尝试直接从 HTML 源码暴力提取...")
                try:
                    import requests
                    req_headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                    request_url = url
                    if xsec_token and "xsec_token" not in request_url:
                        request_url = f"{url}?xsec_token={xsec_token}"
                        
                    r = requests.get(request_url, headers=req_headers, timeout=10)
                    html_text = r.text.replace("\\u002F", "/")
                    
                    # 匹配视频
                    vids = re.findall(r'https?://[^"\'\s]+\.mp4[^"\'\s]*', html_text)
                    if vids:
                        https_vids = [v for v in vids if v.startswith("https")]
                        video_url = https_vids[0] if https_vids else vids[0]
                        print(f"  ✅ HTML 暴力提取 MP4 成功: {video_url[:60]}...")
                    
                    # 提取标题兜底
                    if not title:
                        m_title = re.search(r'<title>(.*?)</title>', html_text)
                        if m_title:
                            title = m_title.group(1).replace(" - 小红书", "")
                except Exception as ex:
                    print(f"  ⚠️ HTML 提取失败: {ex}")

            if video_url:
                return {
                    "id": item_id if not item_id.startswith("http") else "xhs_share",
                    "title": title or "未知标题",
                    "desc": desc,
                    "video_url": video_url,
                    "platform": "xiaohongshu"
                }

        elif platform == "douyin":
            params = {"share_url": url}
            res = client.get(f"{TIKHUB_BASE_URL}/api/v1/douyin/web/fetch_one_video_by_share_url", params=params, headers=headers)
            res.raise_for_status()
            d = res.json()
            aweme = d.get("data", {}).get("aweme_detail", {})
            if not aweme:
                res = client.get(f"{TIKHUB_BASE_URL}/api/v1/douyin/app/v3/fetch_one_video_by_share_url", params=params, headers=headers)
                res.raise_for_status()
                aweme = res.json().get("data", {}).get("aweme_list", [{}])[0]

            title = aweme.get("desc", "")
            video_url = ""
            video_info = aweme.get("video", {})
            if "play_addr" in video_info:
                urllist = video_info["play_addr"].get("url_list", [])
                if urllist: video_url = urllist[0]
            
            return {
                "id": aweme.get("aweme_id", ""),
                "title": title,
                "desc": title,
                "video_url": video_url,
                "platform": "douyin"
            }
            
    print("❌ 无法解析提取视频 URL 或者非视频格式。")
    return {}

# === 媒体处理阶段 ===

def download_video(video_url: str, save_path: str):
    print("  🎬 下载无水印原视频文件...")
    headers = {"User-Agent": "Mozilla/5.0"}
    with requests.get(video_url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print(f"  📥 视频下载完毕。({save_path})")

def extract_audio(video_path: str) -> str:
    print("  🎵 正在提取音频轨 (采样率: 16000Hz)...")
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("❌ 未安装 ffmpeg。")
        sys.exit(1)
    
    audio_path = video_path.replace(".mp4", ".wav")
    cmd = [
        ffmpeg, "-i", video_path, 
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", 
        audio_path, "-y"
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)
    print(f"  🎵 音频提取成功。({audio_path})")
    return audio_path

def extract_storyboard(video_path: str, output_dir: str, interval: int = 4) -> str:
    print("  🎞️ 抽取故事版原帧构建排版图...")
    ffmpeg = find_ffmpeg()
    import shutil
    frames_dir = os.path.join(output_dir, "_storyframes")
    os.makedirs(frames_dir, exist_ok=True)
    storyboard_path = os.path.join(output_dir, "storyboard.jpg")
    
    # 获取原始视频比例信息，为了计算适当的分辨率
    cmd = [
        ffmpeg, '-i', video_path,
        '-vf', f'fps=1/{interval},scale=480:-1',
        '-q:v', '3',
        os.path.join(frames_dir, 'frame_%03d.jpg'), '-y'
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)
    
    frame_files = sorted(glob.glob(os.path.join(frames_dir, 'frame_*.jpg')))
    if not frame_files:
        return ""
    
    cols = min(4, len(frame_files))
    rows = math.ceil(len(frame_files) / cols)
    tile_filter = f"tile={cols}x{rows}:padding=4:color=white"
    
    merge_cmd = [ffmpeg] + sum([['-i', f] for f in frame_files], []) + [
        '-filter_complex',
        ''.join([f'[{i}:v]' for i in range(len(frame_files))]) +
        f'concat=n={len(frame_files)}:v=1:a=0[merged];[merged]{tile_filter}',
        '-q:v', '2', storyboard_path, '-y'
    ]
    subprocess.run(merge_cmd, capture_output=True, timeout=30)
    shutil.rmtree(frames_dir)
    print(f"  🖼️ 故事版生成完毕。({storyboard_path})")
    return storyboard_path

# === 硅基流动交互阶段 ===

def get_sf_key() -> str:
    sf_key = os.environ.get("SILICONFLOW_API_KEY")
    if not sf_key:
        print("❌ 错误: 未设置 SILICONFLOW_API_KEY 环境变量！请前往硅基流动注册获取。")
        sys.exit(1)
    return sf_key

def transcribe_audio_with_sf(audio_path: str) -> str:
    print("  🎙️ 调用 SiliconFlow [SenseVoiceSmall] 提取精准逐字稿...")
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
        text = resp.json().get("text", "")
        print(f"  ✅ 提取到原文 {len(text)} 字。")
        return text.strip()
    except Exception as e:
        print(f"  ❌ 语音识别失败: {e}")
        try:
           print(resp.text)
        except: 
           pass
        sys.exit(1)

def analyze_script_with_llm(audio_text: str) -> str:
    print("  🧠 唤醒大语言模型进行【硬核深度拆解】...")
    sf_key = get_sf_key()
    url = f"{SILICONFLOW_BASE_URL}/chat/completions"
    
    # 查找Prompt文件
    prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "references", "script_prompt.md")
    system_prompt = "你是一个优秀的商业短视频分析师。"
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()

    payload = {
        "model": "deepseek-ai/DeepSeek-V3", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请针对以下这篇提取到的原生视频文案，进行细致到逐句级别的硬核分析，绝不能偷工减料：\n\n【原始文案】\n{audio_text}"}
        ],
        "temperature": 0.7,
        "max_tokens": 4096
    }
    
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {sf_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=180
        )
        resp.raise_for_status()
        result_text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        print("  ✅ 洞察报告生成完毕！")
        return result_text
    except Exception as e:
        print("  ⚠️ LLM 深度分段处理失败，尝试使用 Qwen2.5 降级备用...")
        # 降级备用
        payload["model"] = "Qwen/Qwen2.5-72B-Instruct"
        try:
            resp = requests.post(url, headers={"Authorization": f"Bearer {sf_key}", "Content-Type": "application/json"}, json=payload, timeout=180)
            resp.raise_for_status()
            result_text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return result_text
        except Exception as e2:
             print(f"  ❌ LLM 失败二连: {e2}")
             sys.exit(1)

# === 主控制流程 ===

def main():
    parser = argparse.ArgumentParser("wudami-jiaoben-api 视频处理引擎")
    parser.add_argument("--url", required=True, help="视频的URL链接，比如小红书或抖音分享链接")
    args = parser.parse_args()

    print(f"🔄 初始化 {args.url} 识别分析...")
    platform, item_id, url, xsec_token = extract_platform_and_id(args.url)
    
    metadata = get_video_from_tikhub(platform, item_id, url, xsec_token)
    if not metadata or not metadata.get("video_url"):
        print("❌ 无法获取视频链接（可能由于平台风控或链接问题），停止执行。")
        sys.exit(1)
        
    print(f"  📎 获取到视频源数据: {metadata.get('title')[:30]}...")
    
    # 创建专门的工作区
    override_dir = os.environ.get("_WUDAMI_BATCH_OVERRIDE_DIR")
    if override_dir:
        output_dir = override_dir
        os.makedirs(output_dir, exist_ok=True)
    else:
        obsidian_base_dir = "/Users/wushijing/Obsidian仓库/吴大咪一人公司/02-素材库/脚本库"
        os.makedirs(obsidian_base_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        article_title = metadata.get('title', '未知内容').replace('\n', '')[:20].replace(' ','_').replace('/','_')
        folder_name = f"{timestamp}-{platform}-脚本拆解-{article_title}"
        output_dir = os.path.join(obsidian_base_dir, folder_name)
        os.makedirs(output_dir, exist_ok=True)
        
    print(f"📂 工作流目录已锁定: \n{output_dir}")
    
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        v_path = os.path.join(temp_dir, "source.mp4")
        download_video(metadata["video_url"], v_path)
        
        # 为了防止批量模式下的资源覆盖，在图片名称中加入唯一标识
        safe_title = article_title if 'article_title' in locals() else metadata.get('title', '未知内容').replace('\n', '')[:20].replace(' ','_').replace('/','_')
        storyboard_path_target_name = f"{timestamp}-{platform}-{safe_title}-storyboard.jpg"
        
        storyboard_path = extract_storyboard(v_path, temp_dir) # 先生成到临时区
        
        # 转移故事板到最终输出区
        final_storyboard_path = ""
        if storyboard_path and os.path.exists(storyboard_path):
            import shutil
            final_storyboard_path = os.path.join(output_dir, storyboard_path_target_name)
            shutil.copy(storyboard_path, final_storyboard_path)
            
        audio_path = extract_audio(v_path)
        
        raw_text = transcribe_audio_with_sf(audio_path)
        analyze_md = analyze_script_with_llm(raw_text)
    
    # 拼接最终文档
    safe_title2 = metadata.get('title', '未知内容').replace('\n', '')[:20].replace(' ','_').replace('/','_')
    final_md_path = os.path.join(output_dir, f"{timestamp}-{safe_title2}-深度拆解.md")
    
    final_content = f"""---
source_url: {args.url}
platform: {platform}
extract_date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
---

# 视频信息锚定
- **平台来源**：{platform}
- **抓取原帖**：{metadata.get('title', 'N/A').replace(chr(10), ' ')}
- **跳转链接**：[直达网页端]({args.url})
"""
    if final_storyboard_path and os.path.exists(final_storyboard_path):
        final_content += f"\n## 🎞️ 视觉骨架（故事版分镜矩阵）\n\n![分镜截图](file://{os.path.abspath(final_storyboard_path)})\n\n"
        
    final_content += "\n" + analyze_md
    
    with open(final_md_path, "w", encoding="utf-8") as f:
        f.write(final_content)
        
    print(f"\n🎉 完美收工！全部解析数据已导入：")
    print(f"   【文档路径】 {final_md_path}")
    print(f"   【图片路径】 {final_storyboard_path}")

if __name__ == "__main__":
    main()

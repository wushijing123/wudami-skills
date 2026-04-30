#!/usr/bin/env python3
"""
小红书单篇笔记数据抓取脚本（CDP浏览器版）
连接独立Chrome(9333)，抓取笔记详情页的完整数据：
标题、正文、互动数据、评论区TOP、封面图、内页图、视频链接
"""

import argparse
import json
import os
import re
import sys
import time
import subprocess
from datetime import datetime
from typing import Optional

def ensure_dependencies():
    """保证所需依赖，如果缺失则自动安装（实现真正的跨平台开箱即用）"""
    required_pkgs = {
        "requests": "requests",
        "playwright": "playwright",
        "openai": "openai",
        "imageio_ffmpeg": "imageio-ffmpeg",
        "PIL": "Pillow"
    }
    missing = []
    
    for module_name, pip_name in required_pkgs.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)
            
    if missing:
        print(f"📦 初次运行，正在自动安装必要依赖: {', '.join(missing)}，请稍候...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing, "-q"])
            if "playwright" in missing:
                print("🌐 正在初始化 Playwright 浏览器依赖...")
                subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
            print("✅ 依赖自动安装完成！")
        except Exception as e:
            print(f"❌ 自动安装依赖失败，请尝试手动运行: pip install {' '.join(missing)}")
            print(f"错误信息: {e}")
            sys.exit(1)

ensure_dependencies()

import requests
from playwright.sync_api import sync_playwright


def connect_to_chrome(cdp_url: str) -> str:
    try:
        resp = requests.get(f"{cdp_url}/json/version", timeout=5, verify=False)
        resp.raise_for_status()
        return resp.json()["webSocketDebuggerUrl"]
    except Exception as e:
        print(f"无法连接到 Chrome: {e}")
        print(f"请确保独立 Chrome 已启动并监听 {cdp_url}")
        print("运行：python3 scripts/launch_chrome.py")
        sys.exit(1)


def get_or_create_page(playwright, ws_url: str, target_url: str):
    browser = playwright.chromium.connect_over_cdp(ws_url)
    context = browser.contexts[0]
    page = context.new_page()
    page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)
    return page, browser


def check_login(page) -> bool:
    """检查是否已登录"""
    is_logged = page.evaluate("""
        () => {
            const loginBtn = document.querySelector('[class*="login-btn"]');
            const signupBtn = document.querySelector('[class*="sign-up"]');
            return !(loginBtn || signupBtn);
        }
    """)
    return is_logged


def parse_count(text: str) -> int:
    if not text:
        return 0
    text = str(text).strip().replace(",", "").replace(" ", "")
    if "万" in text:
        try:
            return int(float(text.replace("万", "")) * 10000)
        except ValueError:
            return 0
    try:
        return int(text)
    except ValueError:
        return 0


def scrape_note_detail(page) -> dict:
    """抓取笔记详情页的完整数据"""
    time.sleep(2)

    # 等待笔记内容加载
    try:
        page.wait_for_selector('#noteContainer, .note-container, .note-detail', timeout=10000)
    except Exception:
        pass

    note_data = page.evaluate("""
        () => {
            const getText = (sel) => {
                const el = document.querySelector(sel);
                return el ? el.innerText.trim() : '';
            };
            const getAttr = (sel, attr) => {
                const el = document.querySelector(sel);
                return el ? el.getAttribute(attr) || '' : '';
            };

            // 标题
            const title = getText('#detail-title, .title, [class*="note-title"], [id*="title"]')
                || getText('.note-content .title');

            // 正文
            const descEl = document.querySelector('#detail-desc, .desc, [class*="note-text"], [class*="note-desc"]');
            let content = '';
            if (descEl) {
                // 保留换行，去掉多余空白
                content = descEl.innerText.trim();
            }

            // 话题标签
            const tags = [];
            document.querySelectorAll('a[href*="/search_result"], .tag, [class*="hash-tag"] a').forEach(el => {
                const t = el.innerText.trim();
                if (t && t.startsWith('#')) tags.push(t);
                else if (t) tags.push('#' + t);
            });

            // 互动数据
            let likeText = '';
            let collectText = '';
            let commentText = '';
            let shareText = '';
            
            try {
                const state = window.__INITIAL_STATE__;
                if (state && state.note && state.note.noteDetailMap) {
                    const keys = Object.keys(state.note.noteDetailMap);
                    if (keys.length > 0) {
                        const rootNote = state.note.noteDetailMap[keys[0]].note;
                        if (rootNote && rootNote.interactInfo) {
                            likeText = rootNote.interactInfo.likedCount || '';
                            collectText = rootNote.interactInfo.collectedCount || '';
                            commentText = rootNote.interactInfo.commentCount || '';
                            shareText = rootNote.interactInfo.shareCount || '';
                        }
                    }
                }
            } catch (e) {
                console.error("提取互动数据失败", e);
            }

            // Fallback to DOM if INITIAL_STATE failed
            if (!likeText) likeText = getText('[class*="like-wrapper"] span.count, [class*="like"] .count, .like-count, .interact-container .like');
            if (!collectText) collectText = getText('[class*="collect-wrapper"] span.count, [class*="collect"] .count, .collect-count, .interact-container .collect');
            if (!commentText) commentText = getText('[class*="chat-wrapper"] span.count, [class*="comment"] .count, .comment-count, .interact-container .chat');
            if (!shareText) shareText = getText('[class*="share-wrapper"] span.count, [class*="share"] .count, .share-count');

            // 作者信息
            const authorName = getText('.author-wrapper .username, [class*="author"] .name, .user-nickname');
            const authorAvatar = getAttr('.author-wrapper img, [class*="author"] img', 'src');

            // 发布时间
            const dateText = getText('.date, .publish-date, [class*="date"], [class*="time"]');

            // 封面/图片列表
            const images = [];
            
            // 优先从 __INITIAL_STATE__ 提取真实、按序的图片流（解决 DOM 轮播图克隆节点导致重复和乱序的问题）
            try {
                const state = window.__INITIAL_STATE__;
                if (state && state.note && state.note.noteDetailMap) {
                    const keys = Object.keys(state.note.noteDetailMap);
                    if (keys.length > 0) {
                        const rootNote = state.note.noteDetailMap[keys[0]].note;
                        if (rootNote && rootNote.imageList && rootNote.imageList.length > 0) {
                            rootNote.imageList.forEach(imgData => {
                                const url = imgData.urlDefault || imgData.url || imgData.infoList?.[0]?.url || '';
                                if (url) {
                                    let finalUrl = url;
                                    if (!finalUrl.startsWith('http')) {
                                        finalUrl = (finalUrl.startsWith('//') ? 'https:' : 'https://sns-webpic-qc.xhscdn.com/') + finalUrl;
                                    }
                                    images.push(finalUrl.replace('/format/heif/', '/format/webp/'));
                                }
                            });
                        }
                    }
                }
            } catch (e) {
                console.error("提取 INITIAL_STATE 图片失败", e);
            }

            // 如果 __INITIAL_STATE__ 失效，回退到 DOM 提取，使用 Set 去重
            if (images.length === 0) {
                const seenImages = new Set();
                document.querySelectorAll('.swiper-slide:not(.swiper-slide-duplicate) img, .carousel-item img, [class*="slide"] img, .note-slider img, .note-image img').forEach(img => {
                    const src = img.src || img.getAttribute('data-src') || '';
                    if (src && !src.includes('avatar') && !src.includes('emoji')) {
                        const cleanSrc = src.replace('/format/heif/', '/format/webp/');
                        if (!seenImages.has(cleanSrc)) {
                            seenImages.add(cleanSrc);
                            images.push(cleanSrc);
                        }
                    }
                });
                
                // fallback: 如果 slider 没有，尝试抓详情区的大图
                if (images.length === 0) {
                    document.querySelectorAll('#noteContainer img, .note-container img').forEach(img => {
                        const src = img.src || '';
                        if (src && src.includes('xhscdn') && !src.includes('avatar')) {
                            const cleanSrc = src.replace('/format/heif/', '/format/webp/');
                            if (!seenImages.has(cleanSrc)) {
                                seenImages.add(cleanSrc);
                                images.push(cleanSrc);
                            }
                        }
                    });
                }
            }

            // 视频检测
            let videoUrl = '';
            let isVideo = false;
            
            // 优先从 __INITIAL_STATE__ 提取真实视频流地址和类型
            try {
                const state = window.__INITIAL_STATE__;
                if (state && state.note && state.note.noteDetailMap) {
                    const keys = Object.keys(state.note.noteDetailMap);
                    if (keys.length > 0) {
                        const rootNote = state.note.noteDetailMap[keys[0]].note;
                        if (rootNote && rootNote.type === 'video') {
                            isVideo = true;
                            if (rootNote.video && rootNote.video.media && rootNote.video.media.stream) {
                                const streams = rootNote.video.media.stream.h264 || rootNote.video.media.stream.h265;
                                if (streams && streams.length > 0) {
                                    videoUrl = streams[0].masterUrl;
                                }
                            }
                        }
                    }
                }
            } catch (e) {
                console.error("提取视频真实地址失败", e);
            }
            
            if (!isVideo) {
                const videoEl = document.querySelector('video source, video');
                if (videoEl && (videoEl.src || videoEl.querySelector('source')?.src)) {
                    isVideo = true;
                    videoUrl = videoEl.src || videoEl.querySelector('source')?.src || '';
                }
            }

            // 笔记类型（图文/视频）
            const noteType = isVideo ? '视频' : '图文';

            return {
                title,
                content,
                tags,
                likes: likeText,
                collects: collectText,
                comments: commentText,
                shares: shareText,
                authorName,
                authorAvatar,
                dateText,
                images,
                videoUrl,
                isVideo,
                noteType,
                pageUrl: window.location.href
            };
        }
    """)
    return note_data


def scrape_comments(page, max_comments: int = 20) -> list:
    """抓取评论区 TOP 评论"""
    time.sleep(1)

    # 尝试滚动到评论区
    page.evaluate("document.querySelector('.comment, .comments-container, [class*=\"comment\"]')?.scrollIntoView()")
    time.sleep(1)

    comments = page.evaluate("""
        (maxComments) => {
            const comments = [];
            const seen = new Set();
            const commentEls = document.querySelectorAll(
                '.comment-item, .parent-comment, [class*="comment-item"], [class*="comment-inner"]'
            );
            for (let i = 0; i < commentEls.length; i++) {
                if (comments.length >= maxComments) break;
                
                const el = commentEls[i];
                const getText = (sel) => {
                    const child = el.querySelector(sel);
                    return child ? child.innerText.trim() : '';
                };

                const nickname = getText('.name, .nickname, [class*="nickname"], [class*="user-name"]');
                const content = getText('.content, .text, [class*="content"], [class*="comment-text"]');
                const likeText = getText('.like .count, [class*="like"] .count');
                
                const uniqueKey = nickname + '|' + content;

                if (content && !seen.has(uniqueKey)) {
                    seen.add(uniqueKey);
                    comments.push({
                        nickname,
                        content,
                        likes: likeText
                    });
                }
            }
            return comments;
        }
    """, max_comments)
    return comments


def find_ffmpeg() -> Optional[str]:
    """获取跨平台内置的 ffmpeg（真正的免安装开箱即用）"""
    try:
        import imageio_ffmpeg
        # 这个库自带跨平台的 ffmpeg 二进制文件！Windows 和 Mac 都不需要配置 PATH 了
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        print(f"⚠️ imageio-ffmpeg 无法获取路径，将降级尝试系统路径: {e}")
        import shutil
        ffmpeg_cmd = shutil.which("ffmpeg")
        if ffmpeg_cmd:
            return ffmpeg_cmd
        for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg", "C:\\ffmpeg\\bin\\ffmpeg.exe"]:
            if os.path.exists(p):
                return p
        return None


def download_video_for_analysis(video_url: str, output_path: str) -> Optional[str]:
    """从本地视频文件中提取音频（如果是视频笔记）"""
    if not video_url:
        return None
    try:
        import subprocess
        ffmpeg_cmd = find_ffmpeg()
        if not ffmpeg_cmd:
            print("  ⚠️ 未找到 ffmpeg，跳过音频提取。安装方法：brew install ffmpeg")
            return None
        # 使用 ffmpeg 提取音频用于语音转文字
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
    """
    多级降级策略提取音频文案 —— 完全开源友好，无特定客户端依赖。
    
    降级顺序：
    1. 硅基流动 SiliconFlow（免费 SenseVoice，注册即送额度）
    2. OpenAI Whisper API（通用标准，需付费 API Key）
    3. 本地 whisper CLI（pip install openai-whisper，完全离线免费）
    4. 优雅降级：跳过转录，不影响其余拆解流程
    
    环境变量配置（任选其一即可）:
    - SILICONFLOW_API_KEY: 硅基流动 API Key（推荐，免费）
    - OPENAI_API_KEY + OPENAI_BASE_URL: OpenAI 或兼容接口
    """
    import requests
    import subprocess
    import os

    print("  🎙️ 尝试自动转录视频文案...")

    # ── 策略 1: 硅基流动 SiliconFlow（免费 SenseVoice，推荐开源用户使用）──
    sf_key = os.environ.get("SILICONFLOW_API_KEY")
    if sf_key:
        try:
            print("    [1/4] 尝试硅基流动 SenseVoice（免费）...")
            with open(audio_path, "rb") as audio_file:
                resp = requests.post(
                    "https://api.siliconflow.cn/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {sf_key}"},
                    files={"file": ("audio.wav", audio_file, "audio/wav")},
                    data={"model": "FunAudioLLM/SenseVoiceSmall"},
                    timeout=120
                )
            if resp.status_code == 200:
                text = resp.json().get("text", "")
                if text:
                    print("    ✅ 硅基流动 SenseVoice 转录成功！")
                    return text
            else:
                print(f"    ⚠️ 硅基流动返回 {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"    ⚠️ 硅基流动异常: {e}")

    # ── 策略 2: OpenAI 兼容接口（Whisper / 第三方兼容服务）──
    api_key = os.environ.get("OPENAI_API_KEY")
    api_base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    if api_key:
        try:
            print("    [2/4] 尝试 OpenAI Whisper 接口...")
            with open(audio_path, "rb") as audio_file:
                resp = requests.post(
                    f"{api_base}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": ("audio.wav", audio_file, "audio/wav")},
                    data={"model": "whisper-1"},
                    timeout=120
                )
            if resp.status_code == 200:
                text = resp.json().get("text", "")
                if text:
                    print("    ✅ OpenAI Whisper 转录成功！")
                    return text
            else:
                print(f"    ⚠️ OpenAI API 返回 {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"    ⚠️ OpenAI API 异常: {e}")

    # ── 策略 3: 本地 whisper CLI（pip install openai-whisper，完全离线）──
    try:
        check = subprocess.run(["which", "whisper"], capture_output=True, text=True, timeout=5)
        if check.returncode == 0:
            print("    [3/4] 检测到本地 whisper，正在离线转录...")
            result = subprocess.run(
                ["whisper", audio_path, "--model", "small", "--language", "zh",
                 "--output_format", "txt", "--output_dir", os.path.dirname(audio_path)],
                capture_output=True, text=True, timeout=300
            )
            # whisper 会输出 {filename}.txt
            txt_path = audio_path.rsplit(".", 1)[0] + ".txt"
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
                if text:
                    print("    ✅ 本地 whisper 转录成功！")
                    return text
    except Exception as e:
        print(f"    ⚠️ 本地 whisper 异常: {e}")

    # ── 策略 4: 降级容错 ──
    print("    ❌ 未检测到可用的转录引擎！")
    print("    提示：配置 SILICONFLOW_API_KEY 可自动提取视频文案。本次将跳过转录继续生成视觉资产...")
    return None


def extract_storyboard(video_path: str, output_dir: str, interval: int = 3) -> Optional[str]:
    """
    从本地视频中每隔 N 秒截取一帧，自动拼接成九宫格故事版大图。
    
    纯 ffmpeg 实现，不需要 Pillow 或其他 Python 图像库。
    
    Args:
        video_path: 本地视频文件路径
        output_dir: 输出目录
        interval: 截帧间隔（秒），默认3秒
    
    Returns:
        故事版图片路径，失败返回 None
    """
    import subprocess
    import math
    import glob

    ffmpeg_cmd = find_ffmpeg()
    if not ffmpeg_cmd:
        print("  ⚠️ 未找到 ffmpeg，跳过故事版生成")
        return None

    frames_dir = os.path.join(output_dir, "_frames")
    import shutil
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)
    os.makedirs(frames_dir, exist_ok=True)
    storyboard_path = os.path.join(output_dir, "storyboard.jpg")

    try:
        # ── 第一步：获取视频时长 (改为 ffmpeg 以免丢失 ffprobe) ──
        # imageio-ffmpeg 并没有内置 ffprobe 包，所以这里直接用 ffmpeg -i 读取时长
        import re
        probe = subprocess.run([ffmpeg_cmd, "-i", video_path], capture_output=True, text=True, timeout=10)
        duration = 60.0
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", probe.stderr)
        if match:
            h, m, s = match.groups()
            duration = int(h) * 3600 + int(m) * 60 + float(s)
            
        total_frames = max(1, int(duration / interval))
        print(f"  🎞️ 视频时长 {duration:.0f}s，每 {interval}s 截帧，预计 {total_frames} 帧")

        # ── 第二步：截取关键帧 ──
        subprocess.run(
            [ffmpeg_cmd, '-i', video_path,
             '-vf', f'fps=1/{interval},scale=480:-1',
             '-q:v', '3',
             os.path.join(frames_dir, 'frame_%03d.jpg'),
             '-y'],
            capture_output=True, timeout=60
        )

        # 统计实际截出的帧数
        frame_files = sorted(glob.glob(os.path.join(frames_dir, 'frame_*.jpg')))
        actual_frames = len(frame_files)
        if actual_frames == 0:
            print("  ⚠️ 截帧失败，未生成任何帧")
            return None

        print(f"  📸 实际截取 {actual_frames} 帧")

        # ── 第三步：计算网格布局 ──
        # 目标：每行最多5张，自动计算行数
        cols = min(5, actual_frames)
        rows = math.ceil(actual_frames / cols)

        # ── 第四步：用 ffmpeg tile 滤镜拼接成九宫格 ──
        # 需要给每帧打上时间戳标注
        filter_parts = []
        for i in range(actual_frames):
            time_label = f"{i * interval // 60}:{i * interval % 60:02d}"
            filter_parts.append(
                f"[{i}:v]drawtext=text='{time_label}':fontsize=24:fontcolor=white:"
                f"borderw=2:bordercolor=black:x=10:y=10[t{i}]"
            )

        # 构建输入参数和滤镜链
        input_args = []
        for f in frame_files:
            input_args.extend(['-i', f])

        # 简化方案：先不加时间戳标注，直接用 tile 拼接（兼容性最强）
        tile_filter = f"tile={cols}x{rows}:padding=4:color=white"
        
        cmd = [ffmpeg_cmd] + input_args + [
            '-filter_complex',
            # 先把所有输入 concat 成一个流，然后 tile
            ''.join([f'[{i}:v]' for i in range(actual_frames)]) +
            f'concat=n={actual_frames}:v=1:a=0[merged];[merged]{tile_filter}',
            '-q:v', '2',
            storyboard_path, '-y'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if os.path.exists(storyboard_path):
            size_kb = os.path.getsize(storyboard_path) / 1024
            print(f"  🖼️ 故事版已生成: {storyboard_path} ({size_kb:.0f}KB, {cols}×{rows} 网格)")
            return storyboard_path
        else:
            # tile 滤镜兼容性问题时的降级方案：只保留单帧截图
            print(f"  ⚠️ 九宫格拼接失败，降级为关键帧目录: {frames_dir}")
            print(f"     stderr: {result.stderr[:300]}")
            return frames_dir

    except Exception as e:
        print(f"  ⚠️ 故事版生成异常: {e}")
        return None
    finally:
        # ⚠️ 临时关闭清理，保留 _frames 目录，以便在导出 HTML 时插入单帧截图
        # if os.path.exists(storyboard_path):
        #     import shutil
        #     shutil.rmtree(frames_dir, ignore_errors=True)
        pass


    return None

def _normalize_image_url(url: str) -> str:
    """将小红书 CDN 图片 URL 中的 HEIF 格式替换为 JPEG（Pillow 原生支持）。
    小红书 CDN 的 imageView2 接口支持 format 参数动态切换输出格式，
    只需把 format/heif 改成 format/jpg 即可获取标准 JPEG。"""
    import re as _re
    normalized = _re.sub(r'format/heif|format/heic', 'format/jpg', url)
    return normalized

def _download_image_with_fallback(url: str) -> "Image.Image | None":
    """下载单张图片，三级容错：
    1. URL 格式转 JPEG（最快最稳）
    2. 原始 URL + pillow-heif 解码
    3. 原始 URL + ffmpeg 转 JPEG"""
    from PIL import Image
    import requests
    from io import BytesIO
    import os

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.xiaohongshu.com/",
    }

    # ── 策略 1: URL 格式转换 (format/heif → format/jpg) ──
    jpg_url = _normalize_image_url(url)
    try:
        resp = requests.get(jpg_url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 1000:
            img = Image.open(BytesIO(resp.content))
            return img
    except Exception:
        pass

    # ── 策略 2: 原始 URL + pillow-heif 解码 ──
    try:
        resp = requests.get(url, headers=headers, timeout=15)
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
        import subprocess
        resp = requests.get(url, headers=headers, timeout=15)
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
    """
    自动下载多张图片并用 Pillow 拼接成拼接图（用于图文笔记的视觉分析）
    """
    try:
        from PIL import Image, ImageOps
        import math
        import os
        import shutil
        
        if not image_urls:
            return None
            
        print(f"  📸 开始下载 {len(image_urls)} 张笔记配图以生成视觉拼接卡...")
        images = []
        
        # 创建图片保存目录，以便后续 HTML 引用
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
                print(f"    ⚠️ 图片 {i+1}/{len(image_urls)} 下载极化崩溃，所有防线跌破，跳过")
                
        if not images:
            return None
            
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

def main():
    parser = argparse.ArgumentParser(description="小红书单篇笔记数据抓取器（CDP版）")
    parser.add_argument("--cdp", default="http://localhost:9333", help="Chrome CDP 地址")
    parser.add_argument("--url", required=True, help="笔记详情页 URL")
    parser.add_argument("--output", "-o", default="outputs/note_data.json", help="输出文件路径")
    parser.add_argument("--max-comments", type=int, default=20, help="最多抓取评论数")
    args = parser.parse_args()

    print(f"🔗 连接到 Chrome: {args.cdp}")
    ws_url = connect_to_chrome(args.cdp)

    with sync_playwright() as p:
        page, browser = get_or_create_page(p, ws_url, args.url)

        # 登录检测
        if not check_login(page):
            print("\n⚠️ 未检测到登录状态！")
            print("⏳ 脚本已挂起：请在弹出的 Chrome 窗口中完成扫码登录。")
            print("   登录完成后脚本将自动恢复执行...")
            while not check_login(page):
                time.sleep(3)
            print("✅ 登录成功！恢复执行...")

        print("📝 抓取笔记详情...")
        note_data = scrape_note_detail(page)
        
        # 验证防护：如果抓不到内容，极大概率是遇到了小红书的 xsec 滑块风控拦截
        while not note_data.get('title') and not note_data.get('content') and not note_data.get('images'):
            print("\n🚨 触发小红书风控拦截 (xsec 验证码) 或页面未加载！")
            print("👉 不要动！请保持标签页开启！立刻前往 Chrome 窗口手动完成滑块/点击验证。")
            print("⏳ 脚本将在后台默默等待，验证通过后会自动吸取数据...")
            time.sleep(5)
            note_data = scrape_note_detail(page)

        print(f"  标题: {note_data.get('title', 'N/A')}")
        print(f"  类型: {note_data.get('noteType', 'N/A')}")
        print(f"  图片数: {len(note_data.get('images', []))}")

        print(f"💬 抓取评论区 TOP {args.max_comments} 条...")
        comments = scrape_comments(page, args.max_comments)
        print(f"  获取到 {len(comments)} 条评论")

        video_local_path = None
        if note_data.get('isVideo') and note_data.get('videoUrl') and not note_data['videoUrl'].startswith('blob:'):
            # Try to download
            import requests
            print("🎬 检测到真实视频流，准备下载以供提取音频...")
            try:
                base_dir = os.path.dirname(args.output) or '.'
                video_local_path = os.path.join(base_dir, "video.mp4")
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
                # 生成视频故事版（截帧拼接九宫格）
                print("🎞️ 生成视频故事版 Storyboard...")
                base_dir = os.path.dirname(args.output) or '.'
                storyboard = extract_storyboard(video_local_path, base_dir)
                if storyboard:
                    note_data['storyboardPath'] = storyboard
            except Exception as e:
                print(f"  ⚠️ 视频处理失败: {e}")
        else:
            print("\n🖼️ 抓取图文笔记，准备生成正文拼接图...")
            base_dir = os.path.dirname(args.output) or '.'
            storyboard = extract_image_board(note_data.get('images', []), base_dir)
            if storyboard:
                note_data['storyboardPath'] = storyboard

        output = {
            "note": note_data,
            "comments": comments,
            "scrapedAt": datetime.now().isoformat(),
            "sourceUrl": args.url
        }

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"\n💾 笔记数据已保存到: {args.output}")
        page.close()
        browser.close()


if __name__ == "__main__":
    main()

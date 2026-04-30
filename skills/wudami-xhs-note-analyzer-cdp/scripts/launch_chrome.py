#!/usr/bin/env python3
import os
import subprocess
import time
import urllib.request
import urllib.error

CDP_PORT = 9333
PROFILE_DIR = os.path.expanduser("~/.xhs-chrome-profile")
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def is_chrome_running():
    try:
        response = urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        return response.getcode() == 200
    except (urllib.error.URLError, ConnectionError, Exception):
        return False

def launch_chrome():
    if is_chrome_running():
        print(f"✅ Chrome 已经在端口 {CDP_PORT} 运行，跳过启动。")
        return

    print(f"🚀 正在启动独立 Chrome (端口: {CDP_PORT}, Profile: {PROFILE_DIR})...")
    
    os.makedirs(PROFILE_DIR, exist_ok=True)
    
    if not os.path.exists(CHROME_PATH):
        print(f"❌ 找不到 Chrome 浏览器：{CHROME_PATH}")
        print("请确认您使用 macOS 并已安装 Google Chrome。")
        return
    
    # 启动命令
    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check"
    ]
    
    # 使用 subprocess.Popen 在后台启动，不阻塞
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    
    # 等待启动并检测
    max_retries = 10
    for i in range(max_retries):
        time.sleep(1)
        if is_chrome_running():
            print(f"✅ Chrome 启动成功并就绪 (端口 {CDP_PORT})")
            return
        print(f"⏳ 等待 Chrome 启动 ({i+1}/{max_retries})...")
        
    print("❌ Chrome 启动超时，请检查控制台或直接尝试重新运行。")

if __name__ == "__main__":
    launch_chrome()

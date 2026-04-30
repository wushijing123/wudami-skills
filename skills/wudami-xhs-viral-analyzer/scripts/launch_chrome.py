#!/usr/bin/env python3
import os
import subprocess
import time
import urllib.request
import urllib.error
import json

CDP_PORT = 9333
PROFILE_DIR = os.path.expanduser("~/.xhs-chrome-profile")
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def is_chrome_running():
    try:
        response = urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        return response.getcode() == 200
    except (urllib.error.URLError, ConnectionError, Exception):
        return False

def check_login_status():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("💡 未检测到 playwright，跳过登录状态检测。")
        return

    try:
        response = urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        data = json.loads(response.read())
        ws_url = data["webSocketDebuggerUrl"]
    except Exception as e:
        print(f"❌ 获取 Chrome websocket 地址失败: {e}")
        return

    print("🔍 正在检查小红书登录状态...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws_url)
        context = browser.contexts[0]
        
        # 获取或新建小红书页面
        pages = context.pages
        xhs_page = next((page for page in pages if "xiaohongshu.com" in page.url), None)
        
        if not xhs_page:
            xhs_page = context.new_page()
            
        xhs_page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
        xhs_page.bring_to_front()
        time.sleep(2)
        
        is_logged_in = False
        while not is_logged_in:
            cookies = context.cookies()
            if any(c["name"] == "web_session" for c in cookies):
                print("✅ 小红书已登录就绪！")
                is_logged_in = True
            else:
                print("⚠️  检测到尚未登录小红书！")
                print("👉 请在弹出的浏览器窗口中完成扫码登录...")
                
                # 尝试点击登录按钮调出弹窗
                try:
                    login_btn = xhs_page.query_selector('.login-btn')
                    if login_btn:
                        login_btn.click(timeout=1000)
                except Exception:
                    pass
                
                time.sleep(5)
                
        browser.close()

def launch_chrome():
    if is_chrome_running():
        print(f"✅ Chrome 已经在端口 {CDP_PORT} 运行。")
        check_login_status()
        return

    print(f"🚀 正在启动独立 Chrome (端口: {CDP_PORT}, Profile: {PROFILE_DIR})...")
    
    os.makedirs(PROFILE_DIR, exist_ok=True)
    
    if not os.path.exists(CHROME_PATH):
        print(f"❌ 找不到 Chrome 浏览器：{CHROME_PATH}")
        print("请确认您使用 macOS 并已安装 Google Chrome。")
        return
    
    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check"
    ]
    
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    
    max_retries = 10
    for i in range(max_retries):
        time.sleep(1)
        if is_chrome_running():
            print(f"✅ Chrome 启动成功并就绪 (端口 {CDP_PORT})")
            check_login_status()
            return
        print(f"⏳ 等待 Chrome 启动 ({i+1}/{max_retries})...")
        
    print("❌ Chrome 启动超时，请检查控制台或直接尝试重新运行。")

if __name__ == "__main__":
    launch_chrome()

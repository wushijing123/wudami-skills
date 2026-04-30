from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:9333")
    context = browser.contexts[0]
    page = context.pages[-1]
    with open("page.html", "w", encoding="utf-8") as f:
        f.write(page.content())

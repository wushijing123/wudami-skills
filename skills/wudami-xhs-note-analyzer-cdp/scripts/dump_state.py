from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:9333")
    context = browser.contexts[0]
    page = context.pages[0]
    state = page.evaluate("window.__INITIAL_STATE__")
    with open("state.json", "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

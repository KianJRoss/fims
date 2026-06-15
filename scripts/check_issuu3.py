import asyncio
import json
from playwright.async_api import async_playwright

CDN_ID = "260506140512-f077399ecfd86afa6eee7e4087f1bd81"
DOC_SLUG = "2026_world_class_fireworks_catalog"

async def check():
    requests_seen = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Capture all network requests
        page.on("request", lambda r: requests_seen.append(r.url))

        await page.goto(
            f"https://issuu.com/cloudsent/docs/{DOC_SLUG}",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)
        try:
            await page.locator("button:has-text('OK')").first.click()
            await page.wait_for_timeout(1000)
        except Exception:
            pass

        await page.wait_for_timeout(6000)

        print("=== Interesting network requests ===")
        for url in requests_seen:
            if any(x in url for x in ["text", "json", "api", "content", "page", "isu.pub", "data"]):
                print(" ", url)

        # Also try known Issuu text endpoints directly
        print("\n=== Probing known Issuu text endpoints ===")
        test_urls = [
            f"https://text.isu.pub/output/{CDN_ID}/page_text.json",
            f"https://text.isu.pub/{CDN_ID}/page_1.txt",
            f"https://issuu.com/call/backend/document/oembed?url=https://issuu.com/cloudsent/docs/{DOC_SLUG}",
            f"https://reader3.isu.pub/{CDN_ID}/reader3Content.json",
            f"https://reader3.isu.pub/cloudsent/{DOC_SLUG}/reader3Content.json",
        ]
        for url in test_urls:
            try:
                resp = await page.request.get(url, timeout=8000)
                print(f"  {resp.status} {url[:90]}")
                if resp.status == 200:
                    body = await resp.text()
                    print(f"    -> {len(body)} chars: {body[:200]}")
            except Exception as e:
                print(f"  ERR {url[:80]}: {e}")

        await browser.close()


asyncio.run(check())

import asyncio
from playwright.async_api import async_playwright

CDN_ID = "260506140512-f077399ecfd86afa6eee7e4087f1bd81"


async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for page_num in [11, 12, 13]:
            url = f"https://svg.issuu.com/{CDN_ID}/page_{page_num}.html"
            print(f"\n=== Page {page_num} ===")
            print(f"URL: {url}")
            try:
                resp = await page.goto(url, timeout=15000)
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    content = await page.content()
                    text = await page.inner_text("body")
                    print(f"HTML length: {len(content)}")
                    print(f"Text ({len(text)} chars):")
                    print(text[:600])
            except Exception as e:
                print(f"Error: {e}")

        await browser.close()


asyncio.run(check())

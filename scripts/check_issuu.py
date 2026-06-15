import asyncio
from playwright.async_api import async_playwright


async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(
            "https://issuu.com/cloudsent/docs/2026_world_class_fireworks_catalog",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        # Dismiss cookie wall
        for sel in [
            "button:has-text('Accept')",
            "button:has-text('OK')",
            "button:has-text('Agree')",
            "[class*=accept]",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.click()
                    print(f"Clicked: {sel}")
                    await page.wait_for_timeout(2000)
                    break
            except Exception:
                pass

        await page.wait_for_timeout(5000)

        # Check frames
        frames = page.frames
        print(f"Frames: {len(frames)}")
        for f in frames:
            print(f"  frame: {f.url[:100]}")

        # Check iframes
        iframes = await page.query_selector_all("iframe")
        print(f"iframes in DOM: {len(iframes)}")
        for iframe in iframes:
            src = await iframe.get_attribute("src")
            print(f"  src: {src}")

        # Check for text layers
        text_divs = await page.query_selector_all("[class*=textLayer], [class*=text-layer], span[class*=page]")
        print(f"Text layer elements: {len(text_divs)}")

        # Dump body
        body = await page.inner_text("body")
        print("\nBody (first 800):")
        print(body[:800])

        await browser.close()


asyncio.run(check())

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

        # Accept cookies
        try:
            await page.locator("button:has-text('OK')").first.click()
            await page.wait_for_timeout(2000)
        except Exception:
            pass

        await page.wait_for_timeout(5000)

        # Get the rd4 reader frame
        reader_frame = None
        for f in page.frames:
            if "rd4" in f.url or "reader" in f.url.lower():
                reader_frame = f
                print(f"Found reader frame: {f.url}")
                break

        if not reader_frame:
            print("No reader frame found")
            for f in page.frames:
                print(f"  {f.url}")
            await browser.close()
            return

        await reader_frame.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

        # Look for text inside the reader frame
        body_text = await reader_frame.inner_text("body")
        print(f"Reader frame body ({len(body_text)} chars):")
        print(body_text[:1500])

        # Look for specific elements
        for sel in ["[class*=text]", "span", "p", "[class*=page]", "[class*=layer]"]:
            els = await reader_frame.query_selector_all(sel)
            if els:
                print(f"\n{sel}: {len(els)} elements")
                if len(els) < 20:
                    for el in els[:5]:
                        t = await el.inner_text()
                        if t.strip():
                            print(f"  '{t[:100]}'")

        await browser.close()


asyncio.run(check())

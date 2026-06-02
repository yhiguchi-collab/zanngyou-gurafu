"""
エクスポート候補ページのスクリーンショットを撮る診断スクリプト。
debug_menu.py でログイン済みの状態で実行してください（同時起動不可）。
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BROWSER_PROFILE_DIR = Path(__file__).parent / ".browser_profile"

PAGES = [
    ("analysis_report", "https://attendance.moneyforward.com/admin/analysis_report/monthly_over_working_times"),
    ("export_histories", "https://attendance.moneyforward.com/admin/export_histories"),
    ("exporters",        "https://attendance.moneyforward.com/admin/settings/exporters"),
]


async def main():
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(BROWSER_PROFILE_DIR),
            headless=False,
        )
        page = await context.new_page()

        for name, url in PAGES:
            print(f"\n{url} へ移動中...")
            await page.goto(url)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)

            screenshot_path = f"debug_{name}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"  保存: {screenshot_path}")

            # ページ内リンクも出力
            links = await page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({ text: e.innerText.trim(), href: e.href }))"
            )
            for link in links:
                text = link["text"].replace("\n", " ").strip()[:50]
                href = link["href"]
                if text and "attendance.moneyforward.com" in href:
                    print(f"    [{text}]  {href}")

        input("\nEnter で終了: ")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())

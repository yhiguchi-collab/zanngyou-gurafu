"""日付フィールドのHTML構造を確認する診断スクリプト"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BROWSER_PROFILE_DIR = Path(__file__).parent / ".browser_profile"
BASE_URL = "https://attendance.moneyforward.com"
EXPORT_URL = f"{BASE_URL}/admin/settings/exporters/daily_attendance_item_csv_exporters/new"


async def main():
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(BROWSER_PROFILE_DIR), headless=False
        )
        page = await context.new_page()
        await page.goto(EXPORT_URL)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)

        # 日付フィールド周辺のHTML取得
        html = await page.evaluate("""
            () => {
                // 対象年月ラベルの近くにある要素を探す
                const labels = Array.from(document.querySelectorAll('label, th, td, div'));
                for (const el of labels) {
                    if (el.textContent.includes('対象年月')) {
                        const row = el.closest('tr') || el.closest('.form-group') || el.parentElement;
                        return row ? row.outerHTML : el.outerHTML;
                    }
                }
                return 'not found';
            }
        """)
        print("=== 対象年月フィールドのHTML ===")
        print(html[:3000])

        # すべての visible な input 一覧
        inputs = await page.evaluate("""
            () => Array.from(document.querySelectorAll('input')).map(i => ({
                type: i.type,
                name: i.name,
                id: i.id,
                value: i.value,
                placeholder: i.placeholder,
                class: i.className,
                visible: i.offsetParent !== null
            }))
        """)
        print("\n=== Input要素一覧 ===")
        for inp in inputs:
            print(inp)

        input("\nEnterで終了")
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())

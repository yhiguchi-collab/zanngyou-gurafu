"""
ログインしてダッシュボードのリンク一覧を取得する診断スクリプト。
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

EMAIL = os.getenv("MF_EMAIL")
PASSWORD = os.getenv("MF_PASSWORD")
BROWSER_PROFILE_DIR = Path(__file__).parent / ".browser_profile"
BASE_URL = "https://attendance.moneyforward.com"


async def main():
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(BROWSER_PROFILE_DIR),
            headless=False,
        )
        page = await context.new_page()

        print("ログイン中...")
        await page.goto(BASE_URL)
        await page.wait_for_load_state("domcontentloaded")

        # ログインページならログイン処理
        login_btn = page.locator('a:has-text("マネーフォワード IDでログイン"), button:has-text("マネーフォワード IDでログイン")')
        if await login_btn.count() > 0:
            await login_btn.click()
            await page.wait_for_selector('input[type="email"]', timeout=15000)
            await page.fill('input[type="email"]', EMAIL)
            await page.click('button:has-text("ログインする")')
            await page.wait_for_selector('input[type="password"]', timeout=15000)
            await page.fill('input[type="password"]', PASSWORD)
            await page.click('button:has-text("ログインする")')

            # 追加認証
            try:
                await page.wait_for_selector('input[placeholder="000000"]', timeout=8000)
                print("\n  [追加認証] メールに6桁コードが届きました")
                code = await asyncio.to_thread(input, "  認証コード(6桁): ")
                await page.fill('input[placeholder="000000"]', code.strip())
                await page.click('button:has-text("認証する")')
                print("  コードを送信しました。ブラウザでダッシュボードが表示されるまでお待ちください...")
            except PlaywrightTimeout:
                pass

        # ダッシュボードが表示されたらユーザーにEnterを押してもらう
        print("\n-----------------------------------------------")
        print("ブラウザに勤怠のダッシュボードが表示されたら")
        print("このターミナルで Enter キーを押してください")
        print("-----------------------------------------------")
        await asyncio.to_thread(input, "")

        current_url = page.url
        print(f"\n現在のURL: {current_url}")

        # スクリーンショット
        await page.screenshot(path="debug_top.png", full_page=True)
        print("スクリーンショット保存: debug_top.png")

        # リンク一覧
        links = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({ text: e.innerText.trim(), href: e.href }))"
        )
        print(f"\n--- ページ内リンク一覧 ({len(links)}件) ---")
        seen = set()
        for link in links:
            text = link["text"].replace("\n", " ").strip()[:40]
            href = link["href"]
            if text and "moneyforward.com" in href and href not in seen:
                seen.add(href)
                print(f"  [{text}]  {href}")

        print("\n-----------------------------------------------")
        print("上のリンク一覧をコピーしてClaude Codeに貼り付けてください")
        print("-----------------------------------------------")
        await asyncio.to_thread(input, "Enter で終了: ")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())

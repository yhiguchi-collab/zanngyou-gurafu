"""
Money Forward クラウド勤怠から勤怠データをExcelで自動ダウンロードする。

使用方法:
    python scraper.py                          # 今月分
    python scraper.py --year 2024 --month 5    # 指定月
    python scraper.py --headless               # ブラウザ非表示で実行

事前準備:
    pip install -r requirements.txt
    playwright install chromium
"""

import asyncio
import argparse
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

EMAIL = os.getenv("MF_EMAIL")
PASSWORD = os.getenv("MF_PASSWORD")
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
BASE_URL = "https://attendance.moneyforward.com"


# ---- ログイン ----

async def login(page, email: str, password: str) -> None:
    """Money Forward ID でログインする（2段階入力に対応）"""
    print("  ログインページへ移動中...")
    await page.goto(f"{BASE_URL}/")

    # メールアドレス入力
    await page.wait_for_selector('input[type="email"]', timeout=15000)
    await page.fill('input[type="email"]', email)
    await page.locator('input[type="submit"], button[type="submit"]').first.click()

    # パスワードページへ遷移後に入力
    await page.wait_for_selector('input[type="password"]', timeout=15000)
    await page.fill('input[type="password"]', password)
    await page.locator('input[type="submit"], button[type="submit"]').first.click()

    # 勤怠トップページへのリダイレクトを待つ
    await page.wait_for_url(f"{BASE_URL}/**", timeout=20000)
    print("  ログイン完了")


# ---- エクスポートページへの移動 ----

# Money Forward 勤怠のエクスポートURLは環境により異なるため複数試行する
_EXPORT_URL_CANDIDATES = [
    f"{BASE_URL}/report/attendances/export",
    f"{BASE_URL}/report/export",
    f"{BASE_URL}/attendances/export",
    f"{BASE_URL}/admin/attendances/export",
]

_EXPORT_BTN_SELECTOR = (
    'a[href*=".xlsx"], '
    'button:has-text("Excel"), a:has-text("Excel"), '
    'button:has-text("エクスポート"), a:has-text("エクスポート"), '
    'input[value*="Excel"], input[value*="エクスポート"]'
)


async def navigate_to_export(page) -> None:
    """エクスポートページを探して移動する"""
    for url in _EXPORT_URL_CANDIDATES:
        await page.goto(url)
        await page.wait_for_load_state("networkidle", timeout=10000)
        if await page.locator(_EXPORT_BTN_SELECTOR).count() > 0:
            print(f"  エクスポートページ: {url}")
            return

    # URLで見つからない場合はナビゲーションメニューから探す
    print("  メニューからエクスポートページを探しています...")
    nav_link = page.locator(
        'a:has-text("エクスポート"), a:has-text("レポート"), a:has-text("出力")'
    ).first
    if await nav_link.count() > 0:
        await nav_link.click()
        await page.wait_for_load_state("networkidle")
        return

    # 見つからない場合はスクリーンショットを撮って終了
    await page.screenshot(path="error_screenshot.png")
    raise RuntimeError(
        "エクスポートページが見つかりませんでした。\n"
        "error_screenshot.png を確認し、正しいURLを管理者に確認してください。"
    )


# ---- 年月選択 ----

async def select_period(page, year: int, month: int) -> None:
    """年月セレクトボックスがあれば選択する"""
    try:
        year_sel = page.locator('select[name*="year"], select[name*="nen"], select[id*="year"]')
        if await year_sel.count() > 0:
            await year_sel.first.select_option(str(year))

        month_sel = page.locator('select[name*="month"], select[name*="tsuki"], select[id*="month"]')
        if await month_sel.count() > 0:
            await month_sel.first.select_option(str(month))

        print(f"  期間: {year}年{month}月")
    except Exception:
        print(f"  期間設定スキップ（セレクトボックスなし）")


# ---- ダウンロード ----

async def download_excel(page, year: int, month: int, download_dir: Path) -> Path:
    """エクスポートボタンをクリックしてExcelを保存する"""
    download_dir.mkdir(exist_ok=True)

    export_btn = page.locator(_EXPORT_BTN_SELECTOR).first
    if await export_btn.count() == 0:
        await page.screenshot(path="error_screenshot.png")
        raise RuntimeError("ダウンロードボタンが見つかりませんでした。error_screenshot.png を確認してください。")

    print("  ダウンロード中...")
    async with page.expect_download(timeout=60000) as dl_info:
        await export_btn.click()

    download = await dl_info.value
    # サーバーが返すファイル名を優先、なければ自動命名
    filename = download.suggested_filename or f"attendance_{year}{month:02d}.xlsx"
    save_path = download_dir / filename
    await download.save_as(save_path)
    return save_path


# ---- メイン処理 ----

async def run(year: int, month: int, headless: bool) -> Path:
    if not EMAIL or not PASSWORD:
        raise EnvironmentError(".env ファイルに MF_EMAIL と MF_PASSWORD を設定してください")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        try:
            print("\n[1/3] ログイン中...")
            await login(page, EMAIL, PASSWORD)

            print("\n[2/3] エクスポートページへ移動中...")
            await navigate_to_export(page)
            await select_period(page, year, month)

            print("\n[3/3] Excelダウンロード中...")
            save_path = await download_excel(page, year, month, DOWNLOAD_DIR)
            return save_path

        except PlaywrightTimeout as e:
            await page.screenshot(path="error_screenshot.png")
            raise RuntimeError(f"タイムアウト: {e}\nerror_screenshot.png を確認してください。") from e
        finally:
            await browser.close()


def main():
    now = datetime.now()
    parser = argparse.ArgumentParser(description="Money Forward 勤怠データ自動ダウンロード")
    parser.add_argument("--year", type=int, default=now.year, help="対象年（デフォルト: 今年）")
    parser.add_argument("--month", type=int, default=now.month, help="対象月（デフォルト: 今月）")
    parser.add_argument("--headless", action="store_true", help="ブラウザを非表示で実行")
    args = parser.parse_args()

    print(f"対象期間: {args.year}年{args.month}月")
    save_path = asyncio.run(run(args.year, args.month, args.headless))
    print(f"\n完了: {save_path}")
    print(f"次のステップ: python main.py \"{save_path}\"")


if __name__ == "__main__":
    main()

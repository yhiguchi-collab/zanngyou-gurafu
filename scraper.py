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
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

EMAIL = os.getenv("MF_EMAIL")
PASSWORD = os.getenv("MF_PASSWORD")
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
COOKIES_FILE = Path(__file__).parent / ".mf_cookies.json"  # .gitignore の *.json で除外済み
BASE_URL = "https://attendance.moneyforward.com"


# ---- ログイン ----

async def login(page, email: str, password: str) -> None:
    """Money Forward ID でログインする（追加認証・クッキー復元対応）"""
    print("  ログインページへ移動中...")
    await page.goto(f"{BASE_URL}/")

    # Step1: 「マネーフォワード IDでログイン」ボタンをクリック
    await page.wait_for_selector(
        'a:has-text("マネーフォワード IDでログイン"), button:has-text("マネーフォワード IDでログイン")',
        timeout=15000,
    )
    await page.click(
        'a:has-text("マネーフォワード IDでログイン"), button:has-text("マネーフォワード IDでログイン")'
    )

    # Step2: メールアドレス入力
    await page.wait_for_selector('input[type="email"]', timeout=15000)
    await page.fill('input[type="email"]', email)
    await page.click('button:has-text("ログインする")')

    # Step3: パスワード入力
    await page.wait_for_selector('input[type="password"]', timeout=15000)
    await page.fill('input[type="password"]', password)
    await page.click('button:has-text("ログインする")')

    # Step4: 追加認証（新デバイス検知時のみ発生）
    try:
        await page.wait_for_selector('input[placeholder="000000"]', timeout=8000)
        print()
        print("  ========================================")
        print("  [追加認証] メールに6桁コードが届きました")
        print(f"  宛先: {email}")
        print("  メールを確認してコードを入力してください")
        print("  ========================================")
        code = await asyncio.to_thread(input, "  認証コード(6桁): ")
        await page.fill('input[placeholder="000000"]', code.strip())
        await page.click('button:has-text("認証する")')
        print("  認証コードを送信しました")
    except PlaywrightTimeout:
        pass  # 追加認証なし（2回目以降はクッキーで省略）

    # ログイン完了確認
    await page.wait_for_url(f"{BASE_URL}/**", timeout=30000)
    print("  ログイン完了")


# ---- クッキー管理（2回目以降の追加認証をスキップ） ----

async def load_cookies(context) -> bool:
    """保存済みクッキーを読み込む。成功したら True を返す。"""
    if not COOKIES_FILE.exists():
        return False
    try:
        cookies = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
        await context.add_cookies(cookies)
        return True
    except Exception:
        return False


async def save_cookies(context) -> None:
    """現在のクッキーをファイルに保存する。"""
    cookies = await context.cookies()
    COOKIES_FILE.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")


# ---- エクスポートページへの移動 ----

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

    print("  メニューからエクスポートページを探しています...")
    nav_link = page.locator(
        'a:has-text("エクスポート"), a:has-text("レポート"), a:has-text("出力")'
    ).first
    if await nav_link.count() > 0:
        await nav_link.click()
        await page.wait_for_load_state("networkidle")
        return

    await page.screenshot(path="error_screenshot.png")
    raise RuntimeError(
        "エクスポートページが見つかりませんでした。\n"
        "error_screenshot.png を確認してください。"
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
        print("  期間設定スキップ（セレクトボックスなし）")


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

        # 保存済みクッキーを読み込む（追加認証をスキップ）
        has_cookies = await load_cookies(context)
        if has_cookies:
            print("  前回のセッションを復元しました")

        page = await context.new_page()

        try:
            print("\n[1/3] ログイン中...")
            await login(page, EMAIL, PASSWORD)

            # ログイン成功後にクッキーを保存（次回の追加認証をスキップ）
            await save_cookies(context)

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

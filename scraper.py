"""
Money Forward クラウド勤怠から月別データをCSVで自動ダウンロードする。

フロー:
  1. ログイン（追加認証は初回のみ）
  2. 連携/エクスポートページで「月別データ」をエクスポート実行
  3. エクスポート履歴に現れたファイルをダウンロード

使用方法:
    python scraper.py                          # 今月分
    python scraper.py --year 2024 --month 5    # 指定月
    python scraper.py --headless               # ブラウザ非表示で実行（2回目以降）

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
BROWSER_PROFILE_DIR = Path(__file__).parent / ".browser_profile"
BASE_URL = "https://attendance.moneyforward.com"


# ---- ログイン ----

async def login(page, email: str, password: str) -> None:
    """Money Forward ID でログインする。セッション済みなら何もしない。"""
    await page.goto(f"{BASE_URL}/")
    await page.wait_for_load_state("domcontentloaded")

    login_btn = page.locator(
        'a:has-text("マネーフォワード IDでログイン"), button:has-text("マネーフォワード IDでログイン")'
    )
    if await login_btn.count() == 0:
        print("  セッション有効 - ログインをスキップ")
        return

    print("  ログイン中...")
    await login_btn.click()

    await page.wait_for_selector('input[type="email"]', timeout=15000)
    await page.fill('input[type="email"]', email)
    await page.click('button:has-text("ログインする")')

    await page.wait_for_selector('input[type="password"]', timeout=15000)
    await page.fill('input[type="password"]', password)
    await page.click('button:has-text("ログインする")')

    # 追加認証（新デバイス初回のみ）
    try:
        await page.wait_for_selector('input[placeholder="000000"]', timeout=8000)
        print()
        print("  ========================================")
        print("  [追加認証] メールに6桁コードが届きました")
        print(f"  宛先: {email}")
        print("  ========================================")
        code = await asyncio.to_thread(input, "  認証コード(6桁): ")
        await page.fill('input[placeholder="000000"]', code.strip())
        await page.click('button:has-text("認証する")')
        print("  コードを送信しました。リダイレクト待ち...")
    except PlaywrightTimeout:
        pass

    await page.wait_for_url(f"{BASE_URL}/**", timeout=60000)
    print("  ログイン完了")


# ---- エクスポート実行 ----

async def trigger_export(page, year: int, month: int) -> None:
    """
    連携/エクスポートページで「月別データ」のエクスポートをクリックする。
    ダイアログが出た場合は年月を設定して実行する。
    """
    export_url = f"{BASE_URL}/admin/settings/exporters"
    print(f"  エクスポートページへ移動: {export_url}")
    await page.goto(export_url)
    await page.wait_for_load_state("domcontentloaded")

    # 「月別データ」行のエクスポートボタンをクリック
    monthly_btn = page.locator('tr:has-text("月別データ") button, tr:has-text("月別データ") a').filter(
        has_text="エクスポート"
    )
    if await monthly_btn.count() == 0:
        # フォールバック: 2番目のエクスポートボタン（従業員・月別・出勤簿の順）
        monthly_btn = page.locator('button:has-text("エクスポート"), a:has-text("エクスポート")').nth(1)

    await monthly_btn.click()
    print("  「月別データ」エクスポートボタンをクリック")

    # ダイアログ/モーダルが出た場合：年月を設定して実行
    await asyncio.sleep(1)
    await page.screenshot(path="debug_export_dialog.png")

    # 年セレクト
    year_sel = page.locator('select[name*="year"], select[id*="year"], select:near(:text("年"))')
    if await year_sel.count() > 0:
        await year_sel.first.select_option(str(year))
        print(f"  年: {year}")

    # 月セレクト
    month_sel = page.locator('select[name*="month"], select[id*="month"], select:near(:text("月"))')
    if await month_sel.count() > 0:
        await month_sel.first.select_option(str(month))
        print(f"  月: {month}")

    # 実行ボタン（モーダル内）
    run_btn = page.locator('button:has-text("実行"), button:has-text("エクスポート"), input[value="実行"]')
    if await run_btn.count() > 0:
        await run_btn.first.click()
        print("  実行ボタンをクリック")

    await asyncio.sleep(2)


# ---- エクスポート履歴からダウンロード ----

async def download_from_history(page, download_dir: Path) -> Path:
    """
    エクスポート履歴ページを開き、最新ファイルのダウンロードボタンをクリックする。
    最大60秒ポーリングして完了を待つ。
    """
    history_url = f"{BASE_URL}/admin/export_histories"
    download_dir.mkdir(exist_ok=True)

    print(f"  エクスポート履歴を確認中...")
    for attempt in range(12):  # 最大60秒（5秒×12回）
        await page.goto(history_url)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1)

        # 最新行のダウンロードボタンを取得
        download_btn = page.locator('a:has-text("ダウンロード"), button:has-text("ダウンロード")').first
        if await download_btn.count() > 0:
            print(f"  ダウンロードボタンを発見（{attempt+1}回目）")
            async with page.expect_download(timeout=60000) as dl_info:
                await download_btn.click()
            download = await dl_info.value
            filename = download.suggested_filename or "attendance_monthly.csv"
            save_path = download_dir / filename
            await download.save_as(save_path)
            return save_path

        print(f"  エクスポート処理中... ({attempt+1}/12)")
        await asyncio.sleep(5)

    raise RuntimeError("エクスポートが60秒以内に完了しませんでした。エクスポート履歴を手動で確認してください。")


# ---- メイン処理 ----

async def run(year: int, month: int, headless: bool) -> Path:
    if not EMAIL or not PASSWORD:
        raise EnvironmentError(".env ファイルに MF_EMAIL と MF_PASSWORD を設定してください")

    BROWSER_PROFILE_DIR.mkdir(exist_ok=True)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(BROWSER_PROFILE_DIR),
            headless=headless,
            accept_downloads=True,
        )
        page = await context.new_page()

        try:
            print("\n[1/3] ログイン中...")
            await login(page, EMAIL, PASSWORD)

            print("\n[2/3] エクスポート実行中...")
            await trigger_export(page, year, month)

            print("\n[3/3] ダウンロード中...")
            save_path = await download_from_history(page, DOWNLOAD_DIR)
            return save_path

        except PlaywrightTimeout as e:
            await page.screenshot(path="error_screenshot.png")
            raise RuntimeError(f"タイムアウト: {e}\nerror_screenshot.png を確認してください。") from e
        finally:
            await context.close()


def main():
    now = datetime.now()
    parser = argparse.ArgumentParser(description="Money Forward 勤怠データ自動ダウンロード")
    parser.add_argument("--year", type=int, default=now.year)
    parser.add_argument("--month", type=int, default=now.month)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    print(f"対象期間: {args.year}年{args.month}月")
    save_path = asyncio.run(run(args.year, args.month, args.headless))
    print(f"\n完了: {save_path}")
    print(f"次のステップ: python main.py \"{save_path}\"")


if __name__ == "__main__":
    main()

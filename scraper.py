"""
Money Forward クラウド勤怠から出勤簿データをCSVで自動ダウンロードする。

フロー:
  1. ログイン（追加認証は初回のみ）
  2. 連携/エクスポート → CSVファイルの「出勤簿データ」をエクスポート
  3. 対象年月を前月に設定して実行
  4. エクスポート履歴から最新ファイルをダウンロード

使用方法:
    python scraper.py            # 前月分を自動ダウンロード
    python scraper.py --headless # ブラウザ非表示で実行
"""

import asyncio
import argparse
import os
import subprocess
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


def prev_month() -> tuple[int, int]:
    """前月の (year, month) を返す"""
    now = datetime.now()
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


# ---- ログイン ----

async def login(page, email: str, password: str) -> None:
    await page.goto(f"{BASE_URL}/")
    await page.wait_for_load_state("domcontentloaded")

    login_btn = page.locator(
        'a:has-text("マネーフォワード IDでログイン"), '
        'button:has-text("マネーフォワード IDでログイン")'
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
    連携/エクスポートページでCSVの「出勤簿データ」をエクスポートする。
    対象年月を指定月に設定し、「設定内容でエクスポート」ボタンをクリックする。
    """
    export_url = f"{BASE_URL}/admin/settings/exporters"
    print(f"  エクスポートページへ移動...")
    await page.goto(export_url)
    await page.wait_for_load_state("domcontentloaded")

    # CSVセクションの「出勤簿データ」ボタンをクリック（PDF側ではなくCSV側）
    shukkin_rows = page.locator('tr:has-text("出勤簿データ")')
    csv_export_btn = shukkin_rows.first.locator(
        'button:has-text("エクスポート"), a:has-text("エクスポート")'
    )
    await csv_export_btn.click()
    print("  「出勤簿データ」エクスポートをクリック")
    await page.wait_for_load_state("domcontentloaded")

    # 対象年月を前月に設定
    # × ボタンで現在の値をクリアしてから新しい値を入力する
    year_month_str = f"{year}/{month:02d}"

    clear_btn = page.locator('button[aria-label="削除"], button:has-text("×"), .clear-btn').first
    if await clear_btn.count() > 0:
        await clear_btn.click()
        await asyncio.sleep(0.3)

    # 日付入力欄を探して値をセット（"2026/05" 形式）
    date_input = page.locator(
        'input[type="month"], '
        'input[name*="year_month"], '
        'input[placeholder*="年月"]'
    ).first
    if await date_input.count() > 0:
        await date_input.fill(year_month_str)
    else:
        # フォールバック: 入力欄をクリックして直接入力
        await date_input.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.type(year_month_str)

    print(f"  対象年月: {year_month_str}")

    # 「設定内容でエクスポート」ボタンをクリック（他の設定はデフォルトのまま）
    await page.click('button:has-text("設定内容でエクスポート")')
    print("  「設定内容でエクスポート」をクリック")
    await asyncio.sleep(2)


# ---- エクスポート履歴からダウンロード ----

async def download_from_history(page, download_dir: Path) -> Path:
    """
    エクスポート履歴ページを開き、最新ファイルをダウンロードする。
    最大90秒ポーリングして完了を待つ。
    """
    history_url = f"{BASE_URL}/admin/export_histories"
    download_dir.mkdir(exist_ok=True)

    print("  エクスポート完了を待機中...")
    for attempt in range(18):  # 最大90秒（5秒×18回）
        await page.goto(history_url)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1)

        # 最新行のダウンロードリンクを取得
        download_btn = page.locator(
            'a:has-text("ダウンロード"), button:has-text("ダウンロード")'
        ).first
        if await download_btn.count() > 0:
            print(f"  ダウンロードリンクを発見")
            async with page.expect_download(timeout=60000) as dl_info:
                await download_btn.click()
            download = await dl_info.value
            filename = download.suggested_filename or f"attendance_{page.url}.csv"
            save_path = download_dir / filename
            await download.save_as(save_path)
            return save_path

        print(f"  処理中... ({attempt + 1}/18)")
        await asyncio.sleep(5)

    raise RuntimeError("エクスポートが90秒以内に完了しませんでした。")


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

            print(f"\n[2/3] {year}年{month}月のエクスポートを実行中...")
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
    prev_y, prev_m = prev_month()
    parser = argparse.ArgumentParser(description="Money Forward 勤怠データ自動ダウンロード")
    parser.add_argument("--year", type=int, default=prev_y, help=f"対象年（デフォルト: {prev_y}）")
    parser.add_argument("--month", type=int, default=prev_m, help=f"対象月（デフォルト: {prev_m}）")
    parser.add_argument("--headless", action="store_true", help="ブラウザ非表示で実行")
    args = parser.parse_args()

    print(f"対象期間: {args.year}年{args.month}月")
    save_path = asyncio.run(run(args.year, args.month, args.headless))
    print(f"\n完了: {save_path}")

    # ダウンロードしたファイルをExcelで開く
    print("Excelで開いています...")
    os.startfile(str(save_path))

    print(f"次のステップ: python main.py \"{save_path}\"")


if __name__ == "__main__":
    main()

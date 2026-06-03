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
    出勤簿データCSVエクスポート設定ページへ直接移動し、
    hidden input の年・月を前月に書き換えてフォームを送信する。
    """
    # 出勤簿データCSVエクスポートの設定ページへ直接移動
    export_url = f"{BASE_URL}/admin/settings/exporters/daily_attendance_item_csv_exporters/new"
    print(f"  エクスポート設定ページへ移動...")
    await page.goto(export_url)
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(1)

    # CSRF トークンを取得
    csrf_token = await page.evaluate(
        "document.querySelector('input[name=\"authenticity_token\"]').value"
    )

    # フォームを直接 POST（ブラウザのクッキーを自動使用）
    # Vue の dp__input_readonly 日付ピッカーをバイパスして正確に年月を指定できる
    form = "admin_settings_exporters_daily_attendance_item_csv_exporter_form"
    resp = await page.request.post(
        f"{BASE_URL}/admin/settings/exporters/daily_attendance_item_csv_exporters",
        form={
            "authenticity_token":                        csrf_token,
            f"{form}[period_type]":                      "single_month",
            f"{form}[year]":                             str(year),
            f"{form}[month]":                            str(month),
            f"{form}[filter_by]":                        "employee_ids",
            f"{form}[sort_order]":                       "employee_code",
            f"{form}[with_original_record_model_times]": "false",
            f"{form}[with_actual_working_time]":         "false",
            "commit":                                    "エクスポート",
        },
    )
    print(f"  エクスポートリクエスト送信（HTTP {resp.status}）")
    print(f"  対象年月: {year}年{month}月")
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

        # テーブル内の「ダウンロード」ボタンを取得（サイドバーの非表示リンクを除外）
        download_btn = page.get_by_role("button", name="ダウンロード").first
        if await download_btn.count() > 0 and await download_btn.is_visible():
            print(f"  ダウンロードボタンを発見")
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

# 残業グラフ プロジェクト

Money Forward クラウド勤怠のExcelエクスポートを読み込み、Google スプレッドシートへ
店舗ごとに残業時間を集計・グラフ化するツール。

## ファイル構成

```
zanngyou-gurafu/
├── main.py            # メインスクリプト（Excel読み込み → Sheets書き込み）
├── create_sample.py   # 動作確認用サンプルExcel生成
├── requirements.txt   # Python依存パッケージ
├── gas/
│   └── create_graph.gs  # GASスクリプト（グラフ作成）
└── credentials/       # サービスアカウントキー置き場（gitignore済み）
    └── service_account.json  ← ここに配置（コミット禁止）
```

## 処理の流れ

```
Money Forward → Excelエクスポート
      ↓
  main.py（Python）
      ↓
Google スプレッドシート（店舗別シート＋集計シート）
      ↓
  create_graph.gs（GAS）
      ↓
  グラフシート（棒グラフ）
```

## 技術スタック

- Python 3.11+
  - `openpyxl`：Excelファイル読み込み
  - `gspread`：Google Sheets API
  - `google-auth`：サービスアカウント認証
- GAS（Google Apps Script）：グラフ自動生成

## セットアップ手順

### 1. Python 環境

```bash
pip install -r requirements.txt
```

### 2. Google Cloud サービスアカウントの作成

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクト作成
2. 「APIとサービス」→「ライブラリ」で以下を有効化
   - Google Sheets API
   - Google Drive API
3. 「APIとサービス」→「認証情報」→「サービスアカウント」を作成
4. キーを JSON 形式でダウンロード → `credentials/service_account.json` に配置
5. スプレッドシートをサービスアカウントのメールアドレスで**編集者として共有**

### 3. main.py の設定変更

`main.py` の先頭にある以下を実際の値に変更：

```python
SPREADSHEET_ID = "YOUR_SPREADSHEET_ID"  # スプレッドシートのURLの /d/〇〇〇/edit の部分
```

### 4. GAS スクリプトの設置

1. 対象スプレッドシートを開く
2. 「拡張機能」→「Apps Script」
3. `gas/create_graph.gs` の内容をコピーして貼り付け
4. 保存して実行（初回は権限承認が必要）

## 動作確認（ステップ）

```bash
# Step 1: サンプルExcelを生成
python create_sample.py
# → sample_data.xlsx が作成される

# Step 2: スプレッドシートへ書き込み
python main.py sample_data.xlsx

# Step 3: GASエディタで createOvertimeGraphs() を実行
# → グラフシートにグラフが生成される
```

## Money Forward エクスポートの列名

`main.py` が期待する列名（変更が必要な場合はファイル先頭の定数を修正）:

| 定数名 | デフォルト値 | 説明 |
|---|---|---|
| `COL_STORE` | `所属` | 店舗・部署名 |
| `COL_NAME` | `氏名` | スタッフ氏名 |
| `COL_OVERTIME` | `時間外労働時間` | 残業時間（HH:MM形式） |

## Git 運用ルール

### 基本方針

**コードを変更するたびに、必ず GitHub へプッシュすること。**

ローカルコミットのみで作業を終わらせない。変更 → コミット → プッシュを 1 セットとする。

### 手順

```bash
git add <変更ファイル>
git commit -m "変更内容の説明"
git push origin main
```

### コミットメッセージ規約

- 日本語で記述してよい
- 変更の「何を」「なぜ」が伝わる内容にする
- 例: `グラフの表示スタイルを調整`、`バグ修正: 月次集計が正しく計算されない問題`

### 注意事項

- `credentials/` 以下のファイルは **絶対にコミットしない**（`.gitignore` で除外済み）
- `input.xlsx`、`sample_data.xlsx` もコミット不要（個人情報を含む可能性あり）

## リポジトリ

- GitHub: https://github.com/yhiguchi-collab/zanngyou-gurafu.git

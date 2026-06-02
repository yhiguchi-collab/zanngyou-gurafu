/**
 * 残業グラフ作成スクリプト
 *
 * 使用方法:
 *   1. このスクリプトをスプレッドシートのAppScriptエディタに貼り付ける
 *   2. createOvertimeGraphs() を実行する
 *
 * 前提:
 *   - Python スクリプト (main.py) で店舗別シートと「集計」シートが作成済みであること
 *   - 各店舗シートの形式: A列=氏名, B列=残業時間(HH:MM), C列=残業時間(分)
 */

// グラフを作成するシート名
const GRAPH_SHEET_NAME = "グラフ";
// 集計シート名
const SUMMARY_SHEET_NAME = "集計";
// グラフを作成しないシート名（除外リスト）
const EXCLUDED_SHEETS = [GRAPH_SHEET_NAME, SUMMARY_SHEET_NAME];


/**
 * メイン関数: 全店舗の残業グラフを「グラフ」シートに作成する
 */
function createOvertimeGraphs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // グラフシートを初期化（なければ作成、あればクリア）
  let graphSheet = ss.getSheetByName(GRAPH_SHEET_NAME);
  if (!graphSheet) {
    graphSheet = ss.insertSheet(GRAPH_SHEET_NAME);
  } else {
    // 既存グラフをすべて削除
    graphSheet.getCharts().forEach(chart => graphSheet.removeChart(chart));
    graphSheet.clear();
  }

  // 店舗シートを取得
  const storeSheets = ss.getSheets().filter(
    sheet => !EXCLUDED_SHEETS.includes(sheet.getName())
  );

  if (storeSheets.length === 0) {
    SpreadsheetApp.getUi().alert("店舗シートが見つかりません。\nまず main.py でデータを書き込んでください。");
    return;
  }

  // 店舗ごとにグラフを作成
  const chartWidth = 450;
  const chartHeight = 300;
  const cols = 2; // 横に並べる数

  storeSheets.forEach((sheet, index) => {
    const storeName = sheet.getName();
    const lastRow = sheet.getLastRow();

    if (lastRow < 2) return; // データなし

    // データ範囲: A列(氏名) と C列(残業時間分)
    const nameRange = sheet.getRange(2, 1, lastRow - 1, 1);
    const overtimeRange = sheet.getRange(2, 3, lastRow - 1, 1);

    // グラフの配置位置を計算
    const col = index % cols;
    const row = Math.floor(index / cols);
    const anchorCol = col * (chartWidth / 100) + 1;
    const anchorRow = row * (chartHeight / 21) + 1;

    const chart = graphSheet.newChart()
      .setChartType(Charts.ChartType.BAR)
      .addRange(nameRange)
      .addRange(overtimeRange)
      .setOption("title", `${storeName} 残業時間（分）`)
      .setOption("hAxis.title", "残業時間（分）")
      .setOption("legend", { position: "none" })
      .setOption("colors", ["#4472C4"])
      .setPosition(anchorRow, anchorCol, 0, 0)
      .setNumRows(chartHeight)
      .setNumColumns(chartWidth)
      .build();

    graphSheet.insertChart(chart);
    Logger.log(`グラフ作成: ${storeName}`);
  });

  // 全店舗比較グラフを集計シートに作成
  createSummaryChart(ss);

  SpreadsheetApp.getUi().alert(`グラフを ${storeSheets.length} 店舗分作成しました！`);
}


/**
 * 集計シートに全店舗の残業合計比較グラフを追加する
 */
function createSummaryChart(ss) {
  const summarySheet = ss.getSheetByName(SUMMARY_SHEET_NAME);
  if (!summarySheet) return;

  const lastRow = summarySheet.getLastRow();
  if (lastRow < 2) return;

  // 既存グラフを削除
  summarySheet.getCharts().forEach(chart => summarySheet.removeChart(chart));

  // 店舗別の残業合計を集計
  const data = summarySheet.getRange(2, 1, lastRow - 1, 4).getValues();
  const storeTotals = {};
  data.forEach(row => {
    const store = row[0];
    const minutes = Number(row[3]) || 0;
    storeTotals[store] = (storeTotals[store] || 0) + minutes;
  });

  // グラフ用データを集計シートの右側に書き込む
  const startCol = 6;
  summarySheet.getRange(1, startCol, 1, 2).setValues([["店舗", "残業合計（分）"]]);
  const sortedStores = Object.entries(storeTotals).sort((a, b) => b[1] - a[1]);
  summarySheet.getRange(2, startCol, sortedStores.length, 2).setValues(sortedStores);

  const chartRange = summarySheet.getRange(1, startCol, sortedStores.length + 1, 2);
  const chart = summarySheet.newChart()
    .setChartType(Charts.ChartType.COLUMN)
    .addRange(chartRange)
    .setOption("title", "店舗別 残業時間合計")
    .setOption("vAxis.title", "残業時間（分）")
    .setOption("legend", { position: "none" })
    .setOption("colors", ["#ED7D31"])
    .setPosition(2, startCol + 3, 0, 0)
    .setNumRows(300)
    .setNumColumns(500)
    .build();

  summarySheet.insertChart(chart);
  Logger.log("集計グラフ作成完了");
}

# ふるさと納税 市区町村分析ダッシュボード

総務省の「ふるさと納税に関する現況調査」を基に、市区町村ごとの寄附受入額、募集に要した費用、代理受入額、市町村民税・道府県民税控除額および年度推移を確認する、オフライン配布可能な分析ダッシュボードです。地図、金額分布、自治体の特徴、年度推移の既存機能を維持しています。

## 対象期間と最新データ

対象は令和2～7年度（2020～2025年度）の6年度、各年度1,741市区町村です。データ基準日は2026年8月21日です。最新年度は令和7年度で、総務省の令和8年7月31日公表資料に対応します。

- [総務省の現況調査・過去資料](https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/furusato/archive/)
- [令和8年度実施の概要 PDF](https://www.soumu.go.jp/main_content/001085011.pdf)
- 最新受入額等：[001084989.xlsx](https://www.soumu.go.jp/main_content/001084989.xlsx)
- 最新の市町村民税・道府県民税控除額：[001085012.xlsx](https://www.soumu.go.jp/main_content/001085012.xlsx)

最新2ファイルのSHA-256は、それぞれ `e6299d05a172f00472971f1684f250cb38da4fd596408f03f333a0c1bc5452e2`、`157ec580017313a607c34bd46899b77c9136485865548ded2ee7a3b6bed90b5b` です。全年度のURL、ファイル名、公表日、シート、列、SHA-256、件数は [`data/source_manifest.json`](data/source_manifest.json) が機械可読な出典台帳です。

令和5年度の受入額ファイルは総務省の現行URLから削除されているため、同一公式ファイルのウェブ保存版を使用し、URLとSHA-256を台帳に固定しています。

## 年度の意味

画面の年度は受入額の年度を基準にしています。受入額と税控除額は同じ寄附コホートではありません。

| データ | 定義 |
|---|---|
| `receipt_fiscal_year` | 4月1日から翌年3月31日までの寄附受入実績の年度 |
| `tax_donation_calendar_year` | 1月1日から12月31日までの寄附年 |
| `tax_assessment_fiscal_year` | その寄附に基づく翌年度課税の年度 |

たとえば令和7年度（2025年度）の受入額は2025年4月1日～2026年3月31日の受入実績であり、併記する市町村民税控除額は2025年1月1日～12月31日の寄附に基づく令和8年度課税額です。この期間差をサイドバー、詳細ポップアップ、年度推移画面に常時表示しています。

## 指標の定義

「実質収支」「実質収支額」は、地方公共団体の決算統計上の用語との混同を避けるため、画面の指標名として使用していません。画面の「財政影響参考額」は、次の機械的な比較指標です。

```text
A 交付税措置を考慮しない差引参考額
  = 寄附受入額 - 募集に要した費用 - 代理受入額 - 市町村民税控除額

B 財政影響参考額（75％制度参考値）
  = A + 市町村民税控除額 × 0.75
```

市町村民税控除額と道府県民税控除額は原表の別列として保持し、合計も表示します。Bの75％は、基準財政収入額の算定に関係する制度上の要素を、市町村民税控除額×0.75として機械的に仮置きした制度参考値です。実際の普通交付税増加額、国からの現金補填、自治体決算上の収支とは一致しません。基準財政需要額、他の税収、各種補正、調整、不交付団体等を含む普通交付税算定を本ダッシュボードでは再現していません。自治体別の「ふるさと納税単独分」の全国統一区分公表値も使用していません。

## データ生成

財政金額データについては、総務省XLSXを唯一の正本（Source of Truth）とし、次の流れで生成します。大量の値をHTMLへ手作業で転記していません。

```text
official XLSX
    ↓  scripts/download_sources.py / scripts/build_data.py
parser・SHA-256検証・コードマスタ結合
    ↓
data/processed/furusato_data.json
    ↓  scripts/validate_sources.py / scripts/validate_repository.py
index.html の内蔵JSON
```

更新時は、まず `data/source_manifest.json` に新年度の公式URL、ファイル名、公表日、対応年度、シート、列、件数、SHA-256を追加し、次を実行します。

```bash
python scripts/download_sources.py
python scripts/build_data.py
python scripts/validate_sources.py --no-download
python scripts/validate_repository.py
```

古い年度のコードや名称が原表ごとに異なる場合は、推測で置換せず、コードマスタと監査可能な join correction として処理します。欠損、重複、負数、非有限値、年度間コード集合差、原表行重複、join漏れ、金額単位の不整合は検証エラーにします。

## 検証とE2E

高速なネットワーク非依存検証は次です。

```bash
python scripts/validate_repository.py
```

公式XLSXを全件再読込する完全照合は次です。`validate_sources.py` は生成用の `join_year()` を呼び出さず、独立したセル読取・コードマスタ結合で各原表を再解析します。各年度1,741行、合計10,446自治体年度を対象に、受入額、費用、代理受入額、市町村民税控除額、道府県民税控除額、コード、名称、年度キー、原表行、派生式などを比較します。不一致は `year`、`municipality_code`、`municipality_name`、`field`、`official_value`、`embedded_value` 付きで出力します。

```bash
python scripts/validate_sources.py --no-download
```

ブラウザE2EはPlaywrightで実行します。

```bash
npm install
npx playwright install chromium
npm run test:e2e
```

E2Eでは、最新年度初期表示、全年度切替、自治体選択、詳細表示、受入額・財政影響参考額グラフ、年度別テーブル、前年度比・期間始点比、地図、複数自治体スポットチェック、JavaScriptエラー、`NaN`/`Infinity`のDOM混入を検証します。

GitHub Actionsの `.github/workflows/validate.yml` は、pushとpull requestでPython検証、JavaScript構文検証、Playwright E2Eを実行します。公式原表を再取得する完全照合はネットワーク依存を分離し、手動 workflow dispatch で実行します。

## オフライン利用と地図

金額・年度推移・グラフ・自治体属性は `index.html` に内蔵しているため、ファイルを直接開いても表示できます。地図だけはMapLibre、PMTiles、国土地理院タイル等の外部リソースを使用するため、外部通信がない環境では地図が利用できないことがあります。地図が利用できない場合も、金額分布・自治体の特徴・年度推移は利用できます。

分析グラフの描画ライブラリは Chart.js 4.4.7（MIT、`vendor/chart.umd.min.js`）を同梱しています。したがって、オフライン時に必要な外部通信は地図リソースに限られます。

Windowsでは [`open_dashboard.bat`](open_dashboard.bat) から起動できます。

## ファイル構成

- `index.html`：データを内蔵した配布用ダッシュボード
- `data/source_manifest.json`：年度対応、出典、列、SHA-256、制度定義
- `data/processed/furusato_data.json`：parserが生成する正規化データ
- `scripts/download_sources.py`：公式XLSXの取得とSHA-256検証
- `scripts/build_data.py`：XLSXから正規化JSONとindex.htmlを生成
- `scripts/validate_sources.py`：公式XLSXとの全件照合
- `scripts/validate_repository.py`：内蔵JSONと生成データの構造・値検証
- `requirements.txt`：XLSX parser依存関係の固定
- `tests/e2e/`：Playwrightブラウザテスト
- `reference/original.html`：変更しない原資料スナップショット

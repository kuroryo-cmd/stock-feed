# stock-feed

日本株の短期売買の情報源。公開データ（TDnetの適時開示、Yahoo Financeの株価）だけから作る。推奨ではない。

- **値動き:** 今日の値上がり上位のうち、出来高が急に増えた銘柄。直近1ヶ月に株数が増える開示（新株予約権・第三者割当・売出しなど）があれば印を付ける
- **出来事:** 直近3営業日の上方修正・増配・自社株買い。上方修正は開示PDFの表から営業利益の修正率を読む
- **株数の計算:** 買値と損切りの値段から、1回の損失を上限に収める株数を出す

## 仕組み

- `build.py` が `feedcore.py` でスキャンし、`docs/data/latest.json` と `docs/data/archive/<日付>.json` を書く
- `docs/index.html` がそのJSONを表示する（GitHub Pages、`docs` フォルダを公開）
- `.github/workflows/feed.yml` が平日 12:40・15:45・18:10（日本時間）に `build.py` を走らせ、結果をコミットする。手動でも実行できる（Actions → feed → Run workflow）

個人の保有や売買の記録はここに置かない。

"""情報源を作り直す: 値動きと出来事をスキャンし、docs/data/ に JSON を書く（docs/index.html がそれを表示する）

使い方: python build.py [--skip-scan] [--skip-hot]
定期実行: .github/workflows/feed.yml（平日 12:40・15:45・18:10、日本時間）
"""
import argparse, datetime, json, sys, traceback
from pathlib import Path

import feedcore as F

DOCS = Path(__file__).parent / "docs" / "data"
JST = datetime.timezone(datetime.timedelta(hours=9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-scan", action="store_true")
    ap.add_argument("--skip-hot", action="store_true")
    a = ap.parse_args()
    now = datetime.datetime.now(JST)
    DOCS.mkdir(parents=True, exist_ok=True)
    prev = json.loads((DOCS / "latest.json").read_text(encoding="utf-8")) if (DOCS / "latest.json").exists() else {}
    out = dict(updated=now.strftime("%Y-%m-%d %H:%M"), errors=[])

    disc = F.tdnet_days(35)  # 1ヶ月分の開示を一度だけ取り、両方で使う
    if a.skip_hot:
        out["hot"] = prev.get("hot")
    else:
        try:
            rows, n = F.hot_rows(disclosures=disc)
            out["hot"] = dict(at=now.strftime("%H:%M"), total=n, rows=rows)
        except Exception as e:  # 株価の取得に失敗しても、出来事は出す
            out["errors"].append(f"値動き: {e}")
            traceback.print_exc()
            out["hot"] = prev.get("hot")
    if a.skip_scan:
        out["events"] = prev.get("events")
    else:
        try:
            rows, nrows, nev = F.scan_rows(days=3, disclosures=disc)
            out["events"] = dict(at=now.strftime("%H:%M"), disclosures=nrows, events=nev, rows=rows)
        except Exception as e:
            out["errors"].append(f"出来事: {e}")
            traceback.print_exc()
            out["events"] = prev.get("events")

    text = json.dumps(out, ensure_ascii=False, default=float)
    (DOCS / "latest.json").write_text(text, encoding="utf-8")
    arc = DOCS / "archive"
    arc.mkdir(exist_ok=True)
    (arc / f"{now:%Y-%m-%d}.json").write_text(text, encoding="utf-8")  # その日の最後の結果を残す（後で答え合わせに使う）
    days = sorted((p.stem for p in arc.glob("*.json")), reverse=True)
    (DOCS / "archive.json").write_text(json.dumps(days), encoding="utf-8")
    hot, ev = out.get("hot") or {}, out.get("events") or {}
    print(f"{out['updated']} 値動き {len(hot.get('rows', []))}件 / 出来事 {len(ev.get('rows', []))}社 / エラー {len(out['errors'])}")
    if out["errors"] and not hot and not ev:
        sys.exit(1)


if __name__ == "__main__":
    main()

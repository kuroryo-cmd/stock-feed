"""公開データだけで作る短期売買の情報源（適時開示はTDnet、株価はYahoo Finance）

- hot_rows:  今日の値上がり上位のうち、出来高が急に増えた銘柄。直近1ヶ月に株数が増える開示があれば印を付ける
- scan_rows: 直近の適時開示から、上方修正・増配・自社株買いを拾う。上方修正は開示PDFの「増減率」の行から営業利益の修正率を読む

個人の保有や売買の記録は一切読まない。
"""
import datetime, html, io, re, warnings
from concurrent.futures import ThreadPoolExecutor

import requests

warnings.filterwarnings("ignore")
H = {"User-Agent": "Mozilla/5.0"}
TDNET = "https://www.release.tdnet.info/inbs/"
LOT_MAX = 200_000  # 100株の取得額の上限（これを超える銘柄は既定で除く）
DILUTE = ["新株予約権", "第三者割当", "行使価額修正", "行使価額の修正", "募集株式", "公募", "売出し", "立会外分売", "無償割当",
          "MSワラント", "転換社債", "新株式発行"]
EVENTS = [  # (種類, タイトルに含む語, 除く語)
    ("自社株買い", ["自己株式の取得に係る事項の決定", "自己株式取得に係る事項の決定", "自己株式の取得及び", "自己株式立会外買付取引"],
     ["結果", "状況", "終了", "処分", "消却のみ"]),
    ("増配", ["増配"], ["減配"]),
    ("業績修正", ["業績予想の修正", "業績予想値の修正", "業績予想及び", "予想値と実績値との差異", "予想と実績との差異", "上方修正"], ["下方修正"]),
]


def tdnet_day(d):
    out, p = [], 1
    while True:
        try:
            r = requests.get(f"{TDNET}I_list_{p:03d}_{d}.html", headers=H, timeout=30)
        except requests.RequestException:
            return out
        if r.status_code != 200:
            return out
        s = r.content.decode("utf-8", "ignore")
        rows = re.findall(r'kjTime" noWrap>([^<]*)</td>\s*<td[^>]*kjCode" noWrap>(\w+)</td>\s*<td[^>]*kjName" noWrap>([^<]*)</td>\s*'
                          r'<td[^>]*kjTitle"[^>]*><a href="([^"]+)"[^>]*>([^<]+)</a>', s)
        if not rows:
            return out
        out += [dict(date=d, time=t.strip(), code=c.strip()[:4], name=n.strip(), pdf=f, title=html.unescape(ti)) for t, c, n, f, ti in rows]
        if f"I_list_{p + 1:03d}_{d}.html" not in s:
            return out
        p += 1


def tdnet_days(n):
    today = datetime.date.today()
    ds = [(today - datetime.timedelta(i)).strftime("%Y%m%d") for i in range(n)]
    with ThreadPoolExecutor(6) as tp:
        return sum(tp.map(tdnet_day, ds), [])


def kind(title):
    if "公開買付" in title:
        return None
    for k, inc, exc in EVENTS:
        if any(w in title for w in inc) and not any(w in title for w in exc):
            if k == "業績修正" and not any(w in title for w in ("修正", "差異")):  # 新しい期の予想（前期比）は修正ではない
                continue
            return k
    return None


def dilution(rows):
    return [r for r in rows if any(k in r["title"] for k in DILUTE) and "行使状況" not in r["title"]]


def revision(pdf):
    """業績修正のPDFから、営業利益の修正率（%）を読む。読めなければ語の数で方向だけ出す"""
    from pypdf import PdfReader
    try:
        b = requests.get(TDNET + pdf, headers=H, timeout=30).content
        txt = "".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(b)).pages[:2])
    except Exception:
        return None, "PDF読めず"
    m = re.search(r"増減率[^\n]*", txt)
    if m:
        nums = re.findall(r"(△|▲|-|－)?\s?(\d+(?:\.\d+)?)", m.group(0)[3:])
        vals = [(-1 if s in ("△", "▲") else 1) * float(v) for s, v in nums if v]
        if len(vals) >= 2:
            return vals[1], "営業利益"
        if vals:
            return vals[0], "売上"
    up = len(re.findall("上方修正|上回る|上回り|上回った", txt))
    dn = len(re.findall("下方修正|下回る|下回り|下回った", txt))
    return (None, "上方（語から推定）") if up > dn else ((None, "下方（語から推定）") if dn > up else (None, "方向不明"))


def prices(codes, period="3mo"):
    import yfinance as yf
    if not codes:
        return {}
    d = yf.download([c + ".T" for c in codes], period=period, group_by="ticker", progress=False, auto_adjust=False, threads=True)
    out = {}
    for c in codes:
        try:
            x = d[c + ".T"] if c + ".T" in d.columns.get_level_values(0) else d
            x = x.dropna(subset=["Close"])
            if len(x) > 5:
                out[c] = x
        except KeyError:
            pass
    return out


def hot_rows(min_chg=5, min_vr=2, min_value=0.3, top=40, lot_max=LOT_MAX, disclosures=None):
    import yfinance as yf
    from yfinance import EquityQuery as Q
    q = Q("and", [Q("eq", ["region", "jp"]), Q("gt", ["percentchange", min_chg]), Q("gt", ["dayvolume", 50_000])])
    qs = yf.screen(q, size=250, sortField="percentchange", sortAsc=False).get("quotes", [])
    rows = []
    for x in qs:
        px, vol, avg = x.get("regularMarketPrice") or 0, x.get("regularMarketVolume") or 0, x.get("averageDailyVolume3Month") or 0
        vr = vol / avg if avg else 0
        value = px * avg / 1e8
        if vr < min_vr or value < min_value or px * 100 > lot_max:
            continue
        rows.append(dict(code=x["symbol"].replace(".T", ""), name=(x.get("longName") or x.get("shortName") or "")[:30], px=px,
                         chg=x.get("regularMarketChangePercent", 0), vr=vr, value=value, t=x.get("regularMarketTime", 0)))
    rows = rows[:top]
    disc = disclosures if disclosures is not None else tdnet_days(31)
    by = {}
    for r in disc:
        by.setdefault(r["code"], []).append(r)
    hist = prices([r["code"] for r in rows], "1y")
    for r in rows:
        ds = sorted(by.get(r["code"], []), key=lambda x: (x["date"], x["time"]), reverse=True)
        r["dil"] = [dict(date=x["date"], title=x["title"], url=TDNET + x["pdf"]) for x in dilution(ds)]
        r["news"] = [dict(date=x["date"], title=x["title"], url=TDNET + x["pdf"]) for x in ds[:3]]
        h = hist.get(r["code"])
        r["y1"] = (r["px"] / h["Close"].iloc[0] - 1) * 100 if h is not None else None
        r["rng"] = float(((h["High"] - h["Low"]) / h["Close"]).iloc[-20:].mean() * 100) if h is not None else None
    return rows, len(qs)


def scan_rows(days=3, min_rev=5, min_value=0.5, lot_max=LOT_MAX, disclosures=None):
    rows = disclosures if disclosures is not None else tdnet_days(days + 4)
    n = {}
    for r in rows:
        n[r["date"]] = n.get(r["date"], 0) + 1
    bdays = sorted((d for d, k in n.items() if k >= 20), reverse=True)[:days]  # 土曜などの数件だけの日は営業日に数えない
    ev = [dict(r, kind=kind(r["title"])) for r in rows if r["date"] in bdays]
    ev = [r for r in ev if r["kind"]]
    revs = [r for r in ev if r["kind"] == "業績修正"]
    with ThreadPoolExecutor(8) as tp:
        for r, (v, basis) in zip(revs, tp.map(lambda r: revision(r["pdf"]), revs)):
            r["rev"], r["basis"] = v, basis
    keep = [r for r in ev if r["kind"] != "業績修正" or (r["rev"] is not None and r["rev"] >= min_rev)
            or (r["rev"] is None and r["basis"].startswith("上方"))]
    by = {}  # 同じ会社の複数の出来事はまとめる
    for r in sorted(keep, key=lambda r: (r["date"], r["time"])):
        x = by.setdefault(r["code"], dict(code=r["code"], name=r["name"], date=r["date"], time=r["time"], kinds=[], links=[], rev=None))
        x["kinds"].append(r["kind"])
        x["links"].append(dict(title=r["title"], url=TDNET + r["pdf"]))
        if r.get("rev") is not None:
            x["rev"] = r["rev"] if x["rev"] is None else max(x["rev"], r["rev"])
    px = prices(list(by))
    out = []
    for c, x in by.items():
        h = px.get(c)
        if h is None:
            continue
        d = datetime.date(int(x["date"][:4]), int(x["date"][4:6]), int(x["date"][6:]))
        idx = [t.date() for t in h.index]
        pre = [i for i, t in enumerate(idx) if (t <= d if x["time"] >= "15:00" else t < d)]
        if not pre:
            continue
        p0, last = float(h["Close"].iloc[pre[-1]]), float(h["Close"].iloc[-1])
        vol25 = h["Volume"].iloc[max(0, pre[-1] - 24): pre[-1] + 1].mean()
        vr = float(h["Volume"].iloc[pre[-1] + 1] / vol25) if pre[-1] + 1 < len(h) and vol25 else None
        value = float((h["Close"] * h["Volume"]).iloc[-25:].mean() / 1e8)
        run = float((p0 / h["Close"].iloc[max(0, pre[-1] - 60)] - 1) * 100)  # 出来事の前、約3ヶ月の上昇率
        rng = float(((h["High"] - h["Low"]) / h["Close"]).iloc[-20:].mean() * 100)
        if value < min_value or last * 100 > lot_max:
            continue
        x["kinds"] = list(dict.fromkeys(x["kinds"]))
        out.append(dict(x, p0=p0, px=last, chg=(last / p0 - 1) * 100, vr=vr, value=value, run=run, rng=rng))
    order = {"業績修正": 0, "増配": 1, "自社株買い": 2}
    out.sort(key=lambda r: (min(order[k] for k in r["kinds"]), -(r["rev"] or 0)))
    return out, len(rows), len(ev)

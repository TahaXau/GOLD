"""Gold News Radar: builds docs/index.html (news, price, levels, calendar) every hour."""
import json, os, re, requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote

UA = {"User-Agent": "Mozilla/5.0"}
QUERIES = ["gold price", "gold Federal Reserve", "US inflation CPI", "US jobs report NFP",
           "dollar index treasury yields", "central bank gold buying", "war sanctions oil gold"]
IMPACT = {"fed": 2, "federal reserve": 2, "powell": 2, "warsh": 2, "rate cut": 3, "rate hike": 3,
          "interest rate": 2, "cpi": 3, "pce": 3, "inflation": 2, "nfp": 3, "jobs report": 3,
          "payrolls": 3, "dollar": 1, "yields": 1, "central bank": 2, "war": 2, "sanctions": 2,
          "tariff": 2, "gold": 1, "safe haven": 2, "record high": 2, "oil": 1}
BULL = ["rate cut", "dovish", "safe haven", "weaker dollar", "dollar falls", "dollar weakens", "record high",
        "central bank buying", "war", "tension", "yields fall", "soft inflation", "cooler inflation", "rally", "surge"]
BEAR = ["rate hike", "hawkish", "stronger dollar", "dollar rises", "dollar gains", "yields rise", "yields jump",
        "hot inflation", "hotter", "slump", "tumble", "drops", "falls", "slips", "lowest"]


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=25, **kw)
    r.raise_for_status()
    return r


def fetch_news(q):
    root = ET.fromstring(get("https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
                             % quote(q + " when:2d")).content)
    for it in root.iter("item"):
        try:
            when = parsedate_to_datetime(it.findtext("pubDate", ""))
        except Exception:
            continue
        src = it.findtext("source", "") or "News"
        title = re.sub(r"\s+-\s+" + re.escape(src) + r"$", "", it.findtext("title", ""))
        yield title, src, it.findtext("link", ""), when


def words(t):
    return set(re.findall(r"[a-z0-9$]+", t.lower()))


def build_news():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    items, seen = [], []
    for q in QUERIES:
        try:
            for title, src, link, when in fetch_news(q):
                w = words(title)
                if when < cutoff or any(len(w & s) / max(len(w | s), 1) > 0.6 for s in seen):
                    continue  # old or near-duplicate headline
                seen.append(w)
                t = title.lower()
                score = sum(v for k, v in IMPACT.items() if k in t)
                up, dn = sum(k in t for k in BULL), sum(k in t for k in BEAR)
                items.append({"title": title, "source": src, "link": link, "ts": when.isoformat(),
                              "tag": "HIGH" if score >= 4 else "MED" if score >= 2 else "LOW",
                              "dir": "bull" if up > dn else "bear" if dn > up else "flat", "s": score})
        except Exception as e:
            print("news error:", q, e)
    items.sort(key=lambda x: (x["s"], x["ts"]), reverse=True)
    return items[:24]


def market():
    for sym, label in (("XAUUSD=X", "Spot gold"), ("GC=F", "Gold futures")):
        try:
            res = get("https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=1d&range=3mo" % quote(sym)).json()["chart"]["result"][0]
            m, q = res["meta"], res["indicators"]["quote"][0]
            rows = [(h, l, c) for h, l, c in zip(q["high"], q["low"], q["close"]) if None not in (h, l, c)]
            return label, m, rows
        except Exception as e:
            print("market error:", sym, e)
    return None, None, []


def sma(v, n):
    return sum(v[-n:]) / n if len(v) >= n else None


def rsi(v, n=14):
    if len(v) <= n:
        return None
    d = [v[i] - v[i - 1] for i in range(len(v) - n, len(v))]
    g, l = sum(x for x in d if x > 0) / n, -sum(x for x in d if x < 0) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def analysis(price, pct, rows, news):
    closes = [r[2] for r in rows]
    s20, s50, r14 = sma(closes, 20), sma(closes, 50), rsi(closes)
    h, l, c = rows[-2] if len(rows) > 1 else (price, price, price)
    p = (h + l + c) / 3
    levels = {"R2": max(r[0] for r in rows[-20:]), "R1": 2 * p - l, "Pivot": p, "S1": 2 * p - h, "S2": min(r[1] for r in rows[-20:])}
    score, why = 0, []
    nb = sum(n["dir"] == "bull" for n in news[:15]) - sum(n["dir"] == "bear" for n in news[:15])
    if nb:
        score += 1 if nb > 0 else -1
        why.append("Recent headlines lean %s (%+d net)." % ("bullish" if nb > 0 else "bearish", nb))
    if s20:
        score += 1 if price > s20 else -1
        why.append("Price is %s the 20-day average ($%s)." % ("above" if price > s20 else "below", format(s20, ",.0f")))
    if r14:
        if r14 > 55: score += 1
        if r14 < 45: score -= 1
        why.append("RSI(14) is %.0f, %s." % (r14, "strong" if r14 > 55 else "weak" if r14 < 45 else "neutral"))
    if pct:
        why.append("Gold is %s %.2f%% today." % ("up" if pct > 0 else "down", abs(pct)))
    bias = "Bullish" if score >= 2 else "Bearish" if score <= -2 else "Neutral"
    inval = {"Bullish": "Bullish view weakens below S1 ($%s)." % format(levels["S1"], ",.0f"),
             "Bearish": "Bearish view weakens above R1 ($%s)." % format(levels["R1"], ",.0f")}.get(
        bias, "A close above R1 ($%s) or below S1 ($%s) would end the neutral view." % (format(levels["R1"], ",.0f"), format(levels["S1"], ",.0f")))
    return {"bias": bias, "why": why, "levels": levels, "inval": inval, "rsi": r14, "sma20": s20, "sma50": s50}


def calendar():
    try:
        out, now = [], datetime.now(timezone.utc)
        for e in get("https://nfs.faireconomy.media/ff_calendar_thisweek.json").json():
            if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium"):
                continue
            when = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
            if when > now - timedelta(hours=6):
                out.append({"title": e["title"], "ts": when.isoformat(), "impact": e["impact"],
                            "forecast": e.get("forecast") or "-", "previous": e.get("previous") or "-"})
        return sorted(out, key=lambda x: x["ts"])[:10]
    except Exception as e:
        print("calendar error:", e)
        return []


def main():
    news = build_news()
    label, m, rows = market()
    data = {"updated": datetime.now(timezone.utc).isoformat(), "news": news, "calendar": calendar(), "price": None}
    if m and rows:
        price, prev = m["regularMarketPrice"], m["chartPreviousClose"]
        pct = (price - prev) / prev * 100
        data["price"] = {"label": label, "value": price, "pct": pct, "prev": prev,
                         "high": m.get("regularMarketDayHigh") or rows[-1][0], "low": m.get("regularMarketDayLow") or rows[-1][1]}
        data["analysis"] = analysis(price, pct, rows, news)
    with open(os.path.join(os.path.dirname(__file__), "template.html"), encoding="utf-8") as f:
        page = f.read()
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page.replace("__DATA__", json.dumps(data).replace("</", "<\\/")))
    print("Done:", len(news), "news,", len(data["calendar"]), "events")


if __name__ == "__main__":
    main()

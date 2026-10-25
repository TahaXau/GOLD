"""Gold News Radar: har ghante news utha ke docs/index.html banata hai."""
import html
import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote

HOURS = 36
TOP_N = 20
UA = {"User-Agent": "Mozilla/5.0"}

QUERIES = [
    "gold price", "gold Federal Reserve", "US inflation CPI",
    "US jobs report NFP", "dollar index treasury yields",
    "central bank gold buying", "war sanctions oil gold",
]

# jitna zyada weight, utna high impact
IMPACT = {
    "fed": 2, "federal reserve": 2, "powell": 2, "warsh": 2, "rate cut": 3,
    "rate hike": 3, "interest rate": 2, "cpi": 3, "pce": 3, "inflation": 2,
    "nfp": 3, "jobs report": 3, "payrolls": 3, "dollar": 1, "yields": 1,
    "central bank": 2, "war": 2, "sanctions": 2, "tariff": 2, "gold": 1,
    "safe haven": 2, "record high": 2, "oil": 1,
}
BULL = ["rate cut", "dovish", "safe haven", "weaker dollar", "dollar falls",
        "dollar weakens", "record high", "central bank buying", "war",
        "tension", "yields fall", "soft inflation", "cooler inflation"]
BEAR = ["rate hike", "hawkish", "stronger dollar", "dollar rises",
        "dollar gains", "yields rise", "yields jump", "hot inflation",
        "hotter", "slump", "tumble", "drops", "falls", "slips", "lowest"]


def fetch(query):
    url = ("https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
           % quote(query + " when:2d"))
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        try:
            when = parsedate_to_datetime(it.findtext("pubDate", ""))
        except Exception:
            continue
        out.append((it.findtext("title", ""), it.findtext("link", ""), when))
    return out


def impact_score(t):
    t = t.lower()
    return sum(w for k, w in IMPACT.items() if k in t)


def direction(t):
    t = t.lower()
    up = sum(k in t for k in BULL)
    dn = sum(k in t for k in BEAR)
    if up > dn:
        return "up", "Gold ke liye bullish (upar)"
    if dn > up:
        return "dn", "Gold ke liye bearish (neeche)"
    return "", "Asar saaf nahi"


def get_price():
    try:
        u = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=5d"
        m = requests.get(u, headers=UA, timeout=20).json()["chart"]["result"][0]["meta"]
        p, prev = m["regularMarketPrice"], m["chartPreviousClose"]
        return p, (p - prev) / prev * 100
    except Exception as e:
        print("price error:", e)
        return None, None


def get_history():
    """Pichle 1 mahine ke daily gold futures prices."""
    try:
        u = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=1mo"
        res = requests.get(u, headers=UA, timeout=20).json()["chart"]["result"][0]
        closes = res["indicators"]["quote"][0]["close"]
        return [(t, c) for t, c in zip(res["timestamp"], closes) if c is not None]
    except Exception as e:
        print("history error:", e)
        return []


def make_chart(pts):
    """Bina kisi library ke SVG line chart banata hai."""
    if len(pts) < 2:
        return ""
    W, H, PL, PR, PT, PB = 600, 230, 12, 12, 22, 28
    vals = [c for _, c in pts]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or 1
    lo, hi = lo - pad, hi + pad
    n = len(pts)

    def x(i):
        return PL + i * (W - PL - PR) / (n - 1)

    def y(v):
        return PT + (hi - v) / (hi - lo) * (H - PT - PB)

    line = " ".join("%.1f,%.1f" % (x(i), y(c)) for i, (_, c) in enumerate(pts))
    area = "M%.1f,%d L%s L%.1f,%d Z" % (x(0), H - PB, line.replace(" ", " L"), x(n - 1), H - PB)
    imax, imin = vals.index(max(vals)), vals.index(min(vals))
    d0 = datetime.fromtimestamp(pts[0][0], timezone.utc).strftime("%d %b")
    d1 = datetime.fromtimestamp(pts[-1][0], timezone.utc).strftime("%d %b")
    col = "var(--up)" if vals[-1] >= vals[0] else "var(--dn)"
    chg = (vals[-1] - vals[0]) / vals[0] * 100
    return (
        '<div class="mut" style="margin-top:14px;font-size:13px">Pichla 1 mahina '
        '(<span style="color:%s;font-weight:600">%s%.1f%%</span>)</div>'
        '<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;display:block" role="img" aria-label="Gold chart">'
        '<path d="%s" style="fill:%s;opacity:.12"/>'
        '<polyline points="%s" style="fill:none;stroke:%s;stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round"/>'
        '<circle cx="%.1f" cy="%.1f" r="4.5" style="fill:%s"/>'
        '<text x="%.1f" y="%.1f" text-anchor="middle" style="fill:var(--mut);font-size:14px">$%s</text>'
        '<text x="%.1f" y="%.1f" text-anchor="middle" style="fill:var(--mut);font-size:14px">$%s</text>'
        '<text x="%d" y="%d" style="fill:var(--mut);font-size:14px">%s</text>'
        '<text x="%d" y="%d" text-anchor="end" style="fill:var(--mut);font-size:14px">%s</text>'
        '</svg>'
    ) % (
        col, "+" if chg >= 0 else "", chg, W, H, area, col, line, col,
        x(n - 1), y(vals[-1]), col,
        min(max(x(imax), 40), W - 40), y(max(vals)) - 8, format(max(vals), ",.0f"),
        min(max(x(imin), 40), W - 40), y(min(vals)) + 18, format(min(vals), ",.0f"),
        PL, H - 6, d0, W - PR, H - 6, d1,
    )


def main():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS)
    seen, news = set(), []
    for q in QUERIES:
        try:
            for title, link, when in fetch(q):
                if title in seen or when < cutoff:
                    continue
                seen.add(title)
                news.append((impact_score(title), when, title, link))
        except Exception as e:
            print("[%s] error: %s" % (q, e))
    news.sort(key=lambda x: (x[0], x[1]), reverse=True)

    cards = []
    for s, when, title, link in news[:TOP_N]:
        tag = "HIGH" if s >= 4 else "MED" if s >= 2 else "LOW"
        cls, label = direction(title)
        cards.append(
            '<a class="card" href="%s" target="_blank" rel="noopener">'
            '<span class="tag %s">%s</span>'
            '<h3>%s</h3>'
            '<div class="meta"><span class="t" data-ts="%s"></span>'
            '<span class="imp %s">%s</span></div></a>'
            % (html.escape(link), tag, tag, html.escape(title),
               when.isoformat(), cls, label))
    if not cards:
        cards.append('<div class="card">Abhi koi news nahi mili.</div>')

    price, pct = get_price()
    if price:
        c = "up" if pct >= 0 else "dn"
        price_html = ('<div class="n">$%s</div><div class="%s">%s%.2f%% (futures)</div>'
                      % (format(price, ",.2f"), c, "▲ " if pct >= 0 else "▼ ", abs(pct)))
    else:
        price_html = '<div class="n">--</div><div class="mut">Price abhi available nahi</div>'

    price_html += make_chart(get_history())

    with open(os.path.join(os.path.dirname(__file__), "template.html"), encoding="utf-8") as f:
        page = f.read()
    page = (page.replace("__CARDS__", "\n".join(cards))
                .replace("__PRICE__", price_html)
                .replace("__UPDATED__", datetime.now(timezone.utc).isoformat()))
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print("Done:", len(news), "news,", len(cards), "cards")


if __name__ == "__main__":
    main()

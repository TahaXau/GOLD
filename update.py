"""Gold News Radar: fetches news every hour and builds docs/index.html."""
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

# higher weight = higher impact
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
        return "up", "Bullish for gold"
    if dn > up:
        return "dn", "Bearish for gold"
    return "", "Impact unclear"


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
    """Daily OHLC candles of gold futures for the last 3 months."""
    try:
        u = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=3mo"
        res = requests.get(u, headers=UA, timeout=20).json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        out = []
        for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"]):
            if None not in (o, h, l, c):
                out.append((t, o, h, l, c))
        return out
    except Exception as e:
        print("history error:", e)
        return []


def make_chart(candles):
    """Candlestick chart as plain SVG (no libraries needed)."""
    if len(candles) < 2:
        return ""
    W, H, PL, PR, PT, PB = 600, 280, 8, 50, 14, 26
    n = len(candles)
    lo = min(c[3] for c in candles)
    hi = max(c[2] for c in candles)
    pad = (hi - lo) * 0.06 or 1
    lo, hi = lo - pad, hi + pad
    step = (W - PL - PR) / n
    bw = max(step * 0.62, 1.5)

    def x(i):
        return PL + (i + 0.5) * step

    def y(v):
        return PT + (hi - v) / (hi - lo) * (H - PT - PB)

    parts = []
    # horizontal grid lines with price labels
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        yy = y(v)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" style="stroke:var(--bd);stroke-width:1"/>'
                     % (PL, yy, W - PR, yy))
        parts.append('<text x="%d" y="%.1f" style="fill:var(--mut);font-size:13px">%s</text>'
                     % (W - PR + 5, yy + 4, format(v, ",.0f")))
    # candles
    for i, (_, o, h, l, c) in enumerate(candles):
        col = "var(--up)" if c >= o else "var(--dn)"
        top, bot = y(max(o, c)), y(min(o, c))
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" style="stroke:%s;stroke-width:1.2"/>'
                     % (x(i), y(h), x(i), y(l), col))
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" style="fill:%s"/>'
                     % (x(i) - bw / 2, top, bw, max(bot - top, 1), col))
    # date labels
    d0 = datetime.fromtimestamp(candles[0][0], timezone.utc).strftime("%d %b")
    d1 = datetime.fromtimestamp(candles[-1][0], timezone.utc).strftime("%d %b")
    parts.append('<text x="%d" y="%d" style="fill:var(--mut);font-size:13px">%s</text>' % (PL, H - 6, d0))
    parts.append('<text x="%d" y="%d" text-anchor="end" style="fill:var(--mut);font-size:13px">%s</text>'
                 % (W - PR, H - 6, d1))

    first, last = candles[0][1], candles[-1][4]
    chg = (last - first) / first * 100
    return (
        '<div class="mut" style="margin-top:14px;font-size:13px">Last 3 months, daily candles '
        '(<span class="%s" style="font-weight:600">%s%.1f%%</span>)</div>'
        '<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;display:block" role="img" '
        'aria-label="Gold candlestick chart">%s</svg>'
    ) % ("up" if chg >= 0 else "dn", "+" if chg >= 0 else "", chg, W, H, "".join(parts))


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
        cards.append('<div class="card">No news found right now.</div>')

    price, pct = get_price()
    if price:
        c = "up" if pct >= 0 else "dn"
        price_html = ('<div class="n">$%s</div><div class="%s">%s%.2f%% (futures)</div>'
                      % (format(price, ",.2f"), c, "▲ " if pct >= 0 else "▼ ", abs(pct)))
    else:
        price_html = '<div class="n">--</div><div class="mut">Price unavailable right now</div>'

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

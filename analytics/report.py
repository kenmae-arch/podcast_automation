"""store.json からデイリーダッシュボード HTML を生成する。

使い方: python analytics/report.py -o dashboard.html
"""
import argparse
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent / "data" / "store.json"
JST = timezone(timedelta(hours=9))

# プラットフォーム → 表示名とカテゴリカルスロット(CSS変数名)
PLATFORMS = [
    ("spotify", "Spotify", "--series-1"),
    ("apple", "Apple", "--series-2"),
    ("amazon", "Amazon", "--series-3"),
]
WEEKDAYS = "月火水木金土日"


def esc(s):
    return html.escape(str(s), quote=True)


def jdate(d):
    dt = datetime.strptime(d, "%Y-%m-%d")
    return f"{dt.month}/{dt.day}({WEEKDAYS[dt.weekday()]})"


def last_value(series):
    """{date: n} から (date, value) の最新を返す。空なら None。"""
    if not series:
        return None
    d = max(series)
    return d, series[d]


def date_range(end, days):
    return [(end - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def fmt(n):
    return f"{n:,}"


# ---------------------------------------------------------------- SVG charts

def stacked_bars_svg(dates, layers, width=560, height=120):
    """日別の積み上げバー。layers = [(label, cssvar, {date: n}), ...]"""
    pad_b = 18
    plot_h = height - pad_b
    n = len(dates)
    slot = width / n
    bar_w = max(4, min(28, slot - 4))
    totals = [sum(layer[2].get(d, 0) for layer in layers) for d in dates]
    vmax = max(totals) if any(totals) else 1
    parts = []
    for i, d in enumerate(dates):
        x = i * slot + (slot - bar_w) / 2
        y = plot_h
        tip_lines = [jdate(d)] + [
            f"{label}: {fmt(layer.get(d, 0))}" for label, _v, layer in layers if d in layer
        ]
        if totals[i] == 0:
            parts.append(
                f'<rect x="{x:.1f}" y="{plot_h - 1.5}" width="{bar_w:.1f}" height="1.5" '
                f'fill="var(--grid)"><title>{esc(jdate(d))}: データなし</title></rect>'
            )
        else:
            group = [f"<g>"]
            for label, cssvar, layer in layers:
                v = layer.get(d, 0)
                if v <= 0:
                    continue
                h = v / vmax * (plot_h - 8)
                y -= h
                group.append(
                    f'<rect x="{x:.1f}" y="{y + 1:.1f}" width="{bar_w:.1f}" '
                    f'height="{max(h - 2, 1):.1f}" rx="2" fill="var({cssvar})"/>'
                )
            group.append(f"<title>{esc(chr(10).join(tip_lines))}</title></g>")
            parts.append("".join(group))
        if i == 0 or i == n - 1 or (n > 8 and i == n // 2):
            dt = datetime.strptime(d, "%Y-%m-%d")
            anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
            tx = x if i == 0 else (x + bar_w if i == n - 1 else x + bar_w / 2)
            parts.append(
                f'<text x="{tx:.1f}" y="{height - 4}" text-anchor="{anchor}" '
                f'class="axis-label">{dt.month}/{dt.day}</text>'
            )
    parts.append(
        f'<line x1="0" y1="{plot_h}" x2="{width}" y2="{plot_h}" stroke="var(--baseline)" stroke-width="1"/>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'preserveAspectRatio="none" class="chart">{"".join(parts)}</svg>'
    )


def line_svg(dates, series, width=560, height=140, cssvar="--series-1"):
    """日次折れ線+エリア。series = {date: n}"""
    pad_b = 18
    plot_h = height - pad_b
    vals = [series.get(d) for d in dates]
    known = [v for v in vals if v is not None]
    if not known:
        return ""
    vmax = max(max(known), 1)
    n = len(dates)
    step = width / max(n - 1, 1)
    pts = []
    for i, v in enumerate(vals):
        if v is None:
            continue
        x = i * step
        y = plot_h - v / vmax * (plot_h - 12) - 2
        pts.append((x, y, dates[i], v))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, *_ in pts)
    area = f"0,{plot_h} " + poly + f" {pts[-1][0]:.1f},{plot_h}"
    hovers = "".join(
        f'<g><circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="transparent"/>'
        f'<title>{esc(jdate(d))}: {fmt(v)}</title></g>'
        for x, y, d, v in pts
    )
    lx, ly = pts[-1][0], pts[-1][1]
    labels = []
    for i in (0, len(dates) // 2, len(dates) - 1):
        dt = datetime.strptime(dates[i], "%Y-%m-%d")
        anchor = "start" if i == 0 else ("end" if i == len(dates) - 1 else "middle")
        labels.append(
            f'<text x="{i * step:.1f}" y="{height - 4}" text-anchor="{anchor}" '
            f'class="axis-label">{dt.month}/{dt.day}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" class="chart">'
        f'<line x1="0" y1="{plot_h}" x2="{width}" y2="{plot_h}" stroke="var(--baseline)" stroke-width="1"/>'
        f'<polygon points="{area}" fill="var({cssvar})" opacity="0.12"/>'
        f'<polyline points="{poly}" fill="none" stroke="var({cssvar})" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="var({cssvar})"/>'
        f"{hovers}{''.join(labels)}</svg>"
    )


# ---------------------------------------------------------------- sections

def delta_html(cur, prev, unit=""):
    if prev is None or prev == 0:
        return ""
    diff = cur - prev
    if diff == 0:
        return '<span class="delta flat">±0</span>'
    cls = "up" if diff > 0 else "down"
    sign = "+" if diff > 0 else "−"
    return f'<span class="delta {cls}">{sign}{fmt(abs(diff))}{unit}</span>'


def show_card(show_id, show, series, yesterday):
    title = esc(show.get("title", show_id))
    plats = series.get(show_id, {})
    dates14 = date_range(yesterday, 14)
    layers = []
    total_y = 0
    total_prev = 0
    any_plays = False
    for pid, plabel, cssvar in PLATFORMS:
        plays = plats.get(pid, {}).get("plays", {})
        if plays:
            any_plays = True
        layers.append((plabel, cssvar, plays))
        total_y += plays.get(yesterday.isoformat(), 0)
        total_prev += plays.get((yesterday - timedelta(days=1)).isoformat(), 0)

    if not any_plays:
        body = (
            '<p class="empty">再生データはまだありません。'
            "各プラットフォームの CSV を Drive の <code>podcast-analytics-inbox</code> "
            "に入れると翌朝ここに反映されます。</p>"
        )
    else:
        has_y = any(l[2].get(yesterday.isoformat()) is not None for l in layers)
        hero_num = fmt(total_y) if has_y else "—"
        hero_note = "昨日の再生" if has_y else "昨日の再生(未着)"
        delta = delta_html(total_y, total_prev or None) if has_y else ""
        legend = "".join(
            f'<span class="key"><i style="background:var({v})"></i>{esc(l)}</span>'
            for l, v, layer in layers
            if layer
        )
        body = (
            f'<div class="hero-row"><div><div class="hero-num">{hero_num}</div>'
            f'<div class="hero-label">{hero_note} {delta}</div></div>'
            f'<div class="legend">{legend}</div></div>'
            + stacked_bars_svg(dates14, [l for l in layers if l[2]])
        )

    chips = []
    for pid, plabel, cssvar in PLATFORMS:
        f_latest = last_value(plats.get(pid, {}).get("followers", {}))
        if f_latest:
            chips.append(
                f'<span class="chip"><i style="background:var({cssvar})"></i>'
                f"{esc(plabel)} フォロワー {fmt(f_latest[1])}</span>"
            )
    chip_html = f'<div class="chips">{"".join(chips)}</div>' if chips else ""
    return (
        f'<article class="card"><h3>{title}</h3>{body}{chip_html}</article>'
    )


def web_section(web, yesterday):
    ga4 = web.get("ga4", {})
    y = yesterday.isoformat()
    prev = (yesterday - timedelta(days=1)).isoformat()
    if not ga4.get("users"):
        return (
            '<article class="card wide"><h3>albumatlas.jp(GA4)</h3>'
            '<p class="empty">GA4 連携待ちです。サービスアカウントの設定が済むと、'
            "ユーザー数・ページビュー・流入元がここに載ります。</p></article>"
        )
    tiles = []
    for key, label in [("users", "ユーザー"), ("sessions", "セッション"), ("pageviews", "ページビュー")]:
        s = ga4.get(key, {})
        cur = s.get(y)
        tiles.append(
            '<div class="tile"><div class="tile-num">'
            + (fmt(cur) if cur is not None else "—")
            + f'</div><div class="tile-label">{label} '
            + (delta_html(cur, s.get(prev)) if cur is not None else "")
            + "</div></div>"
        )
    dates28 = date_range(yesterday, 28)
    chart = line_svg(dates28, ga4.get("users", {}))
    chart_html = (
        f'<div class="chart-block"><div class="chart-title">ユーザー数(28日)</div>{chart}</div>'
        if chart
        else ""
    )

    def table(key, head):
        rows = ga4.get(key, {}).get(y) or []
        if not rows:
            return ""
        trs = "".join(
            f'<tr><td>{esc(name)}</td><td class="num">{fmt(v)}</td></tr>' for name, v in rows[:6]
        )
        return (
            f'<div class="mini-table"><div class="chart-title">{head}(昨日)</div>'
            f"<table>{trs}</table></div>"
        )

    return (
        '<article class="card wide"><h3>albumatlas.jp(GA4)</h3>'
        f'<div class="tiles">{"".join(tiles)}</div>{chart_html}'
        f'<div class="tables">{table("topPages", "よく見られたページ")}'
        f'{table("channels", "流入チャネル")}</div></article>'
    )


def status_section(meta):
    conns = meta.get("connections", {})
    labels = {
        "ga4": "GA4(albumatlas.jp)",
        "spotify": "Spotify for Creators",
        "apple": "Apple Podcasts Connect",
        "amazon": "Amazon Music",
    }
    state_label = {"ok": "接続済み", "csv": "CSV取込", "pending": "未連携", "error": "エラー"}
    rows = []
    for key, label in labels.items():
        c = conns.get(key, {"state": "pending"})
        st = c.get("state", "pending")
        note = esc(c.get("note", "")) or (
            f'最終データ {esc(c["lastData"])}' if c.get("lastData") else ""
        )
        rows.append(
            f'<tr><td>{label}</td><td><span class="pill {st}">{state_label.get(st, st)}</span></td>'
            f'<td class="note">{note}</td></tr>'
        )
    return (
        '<section class="status"><h2>連携ステータス</h2>'
        f'<table>{"".join(rows)}</table></section>'
    )


# ---------------------------------------------------------------- page

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --baseline: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
  --good: #006300; --bad: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --baseline: #383835;
    --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
    --good: #0ca30c; --bad: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --baseline: #383835;
  --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
  --good: #0ca30c; --bad: #e66767;
}
body {
  background: var(--page); color: var(--ink); margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", "Hiragino Sans",
    "Noto Sans JP", "Yu Gothic UI", sans-serif;
  font-size: 14px; line-height: 1.6;
}
.wrap { max-width: 1020px; margin: 0 auto; padding: 28px 20px 48px; }
header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 16px; margin-bottom: 20px; }
header h1 { font-size: 21px; margin: 0; letter-spacing: 0.01em; }
header .date { color: var(--ink-2); }
header .updated { color: var(--muted); font-size: 12px; margin-left: auto; }
h2 { font-size: 13px; color: var(--muted); text-transform: uppercase;
     letter-spacing: 0.08em; margin: 28px 0 10px; font-weight: 600; }
.grid { display: grid; gap: 14px; }
.card { background: var(--surface); border: 1px solid var(--border);
        border-radius: 10px; padding: 16px 18px; }
.card h3 { margin: 0 0 10px; font-size: 15px; }
.empty { color: var(--ink-2); margin: 4px 0; }
.empty code { background: var(--page); border: 1px solid var(--border);
              border-radius: 4px; padding: 0 4px; font-size: 12px; }
.hero-row { display: flex; align-items: flex-end; justify-content: space-between;
            gap: 12px; margin-bottom: 10px; }
.hero-num { font-size: 32px; font-weight: 650; line-height: 1.1; }
.hero-label { color: var(--ink-2); font-size: 12px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
         gap: 10px; margin-bottom: 14px; }
.tile { background: var(--page); border: 1px solid var(--border);
        border-radius: 8px; padding: 10px 12px; }
.tile-num { font-size: 24px; font-weight: 650; }
.tile-label { color: var(--ink-2); font-size: 12px; }
.delta { font-size: 12px; font-variant-numeric: tabular-nums; }
.delta.up { color: var(--good); }
.delta.down { color: var(--bad); }
.delta.flat { color: var(--muted); }
.legend, .chips { display: flex; flex-wrap: wrap; gap: 6px 12px; }
.key, .chip { display: inline-flex; align-items: center; gap: 6px;
              color: var(--ink-2); font-size: 12px; }
.key i, .chip i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.chips { margin-top: 10px; }
.chart { width: 100%; height: auto; display: block; margin-top: 4px; }
.axis-label { fill: var(--muted); font-size: 10px; }
.chart-title { color: var(--muted); font-size: 12px; margin: 10px 0 2px; }
.tables { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
table { border-collapse: collapse; width: 100%; }
td { padding: 5px 8px 5px 0; border-bottom: 1px solid var(--grid); vertical-align: top; }
td.num { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-2); }
td.note { color: var(--muted); font-size: 12px; }
.pill { display: inline-block; border-radius: 99px; padding: 1px 10px;
        font-size: 12px; border: 1px solid var(--border); color: var(--ink-2); }
.pill.ok, .pill.csv { color: var(--good); border-color: currentColor; }
.pill.error { color: var(--bad); border-color: currentColor; }
footer { color: var(--muted); font-size: 12px; margin-top: 28px; }
"""


def build(store):
    now = datetime.now(JST)
    yesterday = (now - timedelta(days=1)).date()
    shows = store.get("shows", {})
    series = store.get("series", {})
    cards = "".join(show_card(sid, s, series, yesterday) for sid, s in shows.items())
    updated = store.get("meta", {}).get("lastUpdated") or ""
    if updated:
        updated = "データ更新 " + esc(updated[:16].replace("T", " "))
    return f"""<title>ポッドキャスト計器盤</title>
<style>{CSS}</style>
<div class="wrap">
<header><h1>ポッドキャスト計器盤</h1>
<span class="date">{now.month}月{now.day}日({WEEKDAYS[now.weekday()]})の朝刊 — 昨日 {jdate(yesterday.isoformat())} の数字</span>
<span class="updated">{updated}</span></header>
<h2>番組</h2>
<div class="grid">{cards}</div>
<h2>Web</h2>
<div class="grid">{web_section(store.get("web", {}), yesterday)}</div>
{status_section(store.get("meta", {}))}
<footer>再生数は各プラットフォーム公式エクスポートの取込値(公式APIがないため取込日まで数日の遅れあり)。GA4 は API 自動取得。</footer>
</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="dashboard.html")
    args = ap.parse_args()
    store = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    Path(args.output).write_text(build(store), encoding="utf-8")
    print(f"書き出しました: {args.output}")


if __name__ == "__main__":
    main()

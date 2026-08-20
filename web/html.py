"""Render the collected brief as a self-contained mobile-first HTML page."""

import html as _h

from trader import config

VERDICT = {
    'call': ('▲', 'ซื้อ CALL DW', 'up'),
    'put':  ('▼', 'ซื้อ PUT DW', 'down'),
    'buy':  ('▲', 'ซื้อ', 'up'),
    'wait': ('■', 'ไม่เข้า', 'flat'),
    'none': ('✕', 'ไม่มีของให้ซื้อ', 'off'),
    'stop': ('✕', 'หยุดเทรดวันนี้', 'down'),
}

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#f4f5f7; --card:#fff; --ink:#14161a; --muted:#6b7280; --line:#e3e6ea;
  --up:#0d9e5e; --up-bg:#d8f5e6; --down:#d92d20; --down-bg:#fde4e2;
  --flat:#b45309; --flat-bg:#fdf0d5; --off:#4b5563; --off-bg:#e5e7eb;
  --accent:#2563eb; --track:#e7eaee;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans Thai",sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,"Cascadia Mono",monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0e1116; --card:#161b22; --ink:#e6edf3; --muted:#8b949e; --line:#272e38;
  --up:#3fb950; --up-bg:#0f2e1c; --down:#f85149; --down-bg:#3a1614;
  --flat:#e3b341; --flat-bg:#33280c; --off:#9ca3af; --off-bg:#21262d;
  --accent:#58a6ff; --track:#21262d;
}}
:root[data-theme="dark"]{
  --bg:#0e1116; --card:#161b22; --ink:#e6edf3; --muted:#8b949e; --line:#272e38;
  --up:#3fb950; --up-bg:#0f2e1c; --down:#f85149; --down-bg:#3a1614;
  --flat:#e3b341; --flat-bg:#33280c; --off:#9ca3af; --off-bg:#21262d;
  --accent:#58a6ff; --track:#21262d;
}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);
  font-size:15px;line-height:1.5;-webkit-text-size-adjust:100%}
.wrap{max-width:860px;margin:0 auto;padding:16px 14px 48px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;margin-bottom:6px}
h1{font-size:19px;margin:0;letter-spacing:-.01em}
.stamp{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.alloc{display:flex;flex-wrap:wrap;gap:14px;margin:10px 0 22px;font-size:13px;
  color:var(--muted)}
.alloc b{color:var(--ink);font-variant-numeric:tabular-nums}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:16px;margin-bottom:16px}
.card>h2{font-size:15px;margin:0 0 12px;display:flex;flex-wrap:wrap;gap:8px;
  align-items:baseline}
.card>h2 small{color:var(--muted);font-weight:400;font-size:12.5px}
.badge{display:flex;align-items:center;gap:10px;border-radius:10px;
  padding:13px 16px;font-weight:700;font-size:17px;margin:4px 0 16px}
.badge .sym{font-size:20px;line-height:1}
.badge .tail{margin-left:auto;font-family:var(--mono);font-size:14px;
  font-weight:600;opacity:.85}
.up{background:var(--up-bg);color:var(--up)}
.down{background:var(--down-bg);color:var(--down)}
.flat{background:var(--flat-bg);color:var(--flat)}
.off{background:var(--off-bg);color:var(--off)}
.rows{display:grid;grid-template-columns:auto 1fr;gap:5px 14px;font-size:13.5px;
  margin-bottom:14px}
.rows dt{color:var(--muted)}
.rows dd{margin:0;font-variant-numeric:tabular-nums}
.gauge{position:relative;height:12px;background:var(--track);border-radius:6px;
  overflow:hidden;min-width:130px}
.gauge i{position:absolute;top:0;bottom:0;display:block}
.gauge .mid{left:calc(50% - 1px);width:2px;background:var(--muted);opacity:.55}
.gauge .thr{width:2px;background:var(--ink);opacity:.35}
.meter{height:8px;background:var(--track);border-radius:4px;overflow:hidden;
  min-width:64px}
.meter i{display:block;height:100%;background:var(--accent)}
.ladder{position:relative;height:16px;background:var(--track);border-radius:8px;
  margin:6px 0}
.ladder i{position:absolute;top:0;bottom:0}
.ladder .spread{background:var(--flat);opacity:.7}
.ladder .sl{width:3px;background:var(--down)}
.ladder .tp{width:3px;background:var(--up)}
.ladder .entry{width:3px;background:var(--ink)}
.rr{display:flex;height:12px;border-radius:6px;overflow:hidden;margin:6px 0}
.rr .risk{background:var(--down)}.rr .reward{background:var(--up)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -4px}
table{border-collapse:collapse;width:100%;font-size:13px;
  font-variant-numeric:tabular-nums}
th,td{padding:7px 8px;text-align:right;white-space:nowrap}
th{color:var(--muted);font-weight:500;border-bottom:1px solid var(--line);
  font-size:12px}
td{border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
tr.pick td{background:color-mix(in srgb,var(--accent) 8%,transparent)}
.tag{font-family:var(--mono);font-weight:600}
.tag.c{color:var(--up)}.tag.p{color:var(--down)}
details{margin-top:12px}
summary{cursor:pointer;color:var(--muted);font-size:13px}
.cut{margin:8px 0 0;padding:0;list-style:none;font-size:12.5px;color:var(--muted)}
.cut li{padding:3px 0;display:flex;gap:10px}
.cut code{font-family:var(--mono);min-width:104px;color:var(--ink);opacity:.75}
.err{background:var(--down-bg);color:var(--down);border-radius:10px;
  padding:12px 14px;font-size:13.5px;margin-bottom:14px}
.stale{background:var(--flat-bg);color:var(--flat);border-radius:10px;
  padding:12px 14px;font-size:13.5px;margin-bottom:14px}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:26px;
  line-height:1.7}
"""


def e(x) -> str:
    return _h.escape(str(x), quote=True)


def n(x, dp=2, dash='—') -> str:
    if x is None:
        return dash
    try:
        if x != x:
            return dash
        return f'{x:,.{dp}f}'
    except (TypeError, ValueError):
        return dash


def _pct(v, lo, hi) -> float:
    if v is None or hi <= lo:
        return 0.0
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100.0))


def badge(kind: str, tail: str = '') -> str:
    sym, label, tone = VERDICT[kind]
    tail_html = f'<span class="tail">{e(tail)}</span>' if tail else ''
    return (f'<div class="badge {tone}"><span class="sym">{sym}</span>'
            f'<span>{e(label)}</span>{tail_html}</div>')


def gauge(value, vmax=100.0, threshold=None) -> str:
    """Centre-zero bar: green right of centre, red left."""
    if value is None:
        return '<div class="gauge"></div>'
    frac = max(-1.0, min(1.0, value / vmax))
    half = abs(frac) * 50.0
    colour = 'var(--up)' if frac >= 0 else 'var(--down)'
    left = 50.0 if frac >= 0 else 50.0 - half
    marks = ''
    if threshold is not None:
        t = threshold / vmax * 50.0
        marks = (f'<i class="thr" style="left:calc({50 - t}% - 1px)"></i>'
                 f'<i class="thr" style="left:calc({50 + t}% - 1px)"></i>')
    return (f'<div class="gauge"><i style="left:{left}%;width:{half}%;'
            f'background:{colour}"></i><i class="mid"></i>{marks}</div>')


def meter(value, vmax, colour='var(--accent)') -> str:
    w = 0.0 if not vmax or value is None else max(0.0, min(100.0, value / vmax * 100.0))
    return f'<div class="meter"><i style="width:{w:.1f}%;background:{colour}"></i></div>'


def ladder(bid, ask, sl, tp) -> str:
    pts = [p for p in (bid, ask, sl, tp) if p is not None]
    if len(pts) < 4:
        return ''
    lo, hi = min(pts), max(pts)
    b, a = _pct(bid, lo, hi), _pct(ask, lo, hi)
    return ('<div class="ladder">'
            f'<i class="spread" style="left:{b:.1f}%;width:{max(a - b, 1.5):.1f}%"></i>'
            f'<i class="sl" style="left:{_pct(sl, lo, hi):.1f}%"></i>'
            f'<i class="tp" style="left:calc({_pct(tp, lo, hi):.1f}% - 3px)"></i>'
            f'<i class="entry" style="left:{a:.1f}%"></i></div>')


def rr_bar(sl, entry, tp) -> str:
    if None in (sl, entry, tp) or tp <= sl:
        return ''
    risk = (entry - sl) / (tp - sl) * 100.0
    risk = max(2.0, min(98.0, risk))
    return (f'<div class="rr"><span class="risk" style="width:{risk:.1f}%"></span>'
            f'<span class="reward" style="width:{100 - risk:.1f}%"></span></div>')


def cut_list(rejected: list, limit: int = 10) -> str:
    if not rejected:
        return ''
    items = ''.join(f'<li><code>{e(r["symbol"])}</code><span>{e(r["reject"])}</span></li>'
                    for r in rejected[:limit])
    more = ('' if len(rejected) <= limit
            else f'<li><code></code><span>… อีก {len(rejected) - limit} ตัว</span></li>')
    return (f'<details><summary>ตัดทิ้ง {len(rejected)} ตัว — กดดูเหตุผล</summary>'
            f'<ul class="cut">{items}{more}</ul></details>')


def table(headers: list, rows: list, pick_first: bool = True) -> str:
    head = ''.join(f'<th>{e(h)}</th>' for h in headers)
    body = ''
    for i, r in enumerate(rows):
        cls = ' class="pick"' if (pick_first and i == 0) else ''
        body += f'<tr{cls}>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>'
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

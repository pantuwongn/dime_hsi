"""Assemble the full HTML page from a collected brief."""

from trader import config, review, risk, session
from .html import (CSS, badge, cut_list, e, gauge, ladder, meter, n, rr_bar,
                   table)


def _held_card(held: list) -> str:
    """What is already on the table, at the price you could exit for."""
    if not held:
        return ''
    rows, total = [], 0.0
    for m in held:
        pnl = m.get('pnl_thb')
        total += pnl or 0.0
        colour = ('var(--up)' if (pnl or 0) > 0
                  else 'var(--down)' if (pnl or 0) < 0 else 'var(--muted)')
        rows.append([
            f'<b>{e(m["symbol"])}</b>', e(m.get('bucket', '?')),
            f'{float(m.get("entry") or 0):.2f}', n(m.get('now')),
            f'<span style="color:{colour}">{n(m.get("pnl_pct"), 1)}%</span>',
            f'<span style="color:{colour}">{n(pnl, 0)}</span>',
            m.get('days_held', 0),
            f'{float(m.get("sl") or 0):.2f}', f'{float(m.get("tp") or 0):.2f}'])
    alerts = ''.join(
        f'<li><code>{e(m["symbol"])}</code><span>{e(m["alert"])}</span></li>'
        for m in held if m.get('alert'))
    colour = 'var(--up)' if total > 0 else 'var(--down)' if total < 0 else 'var(--muted)'
    return ('<section class="card"><h2>สถานะที่ถืออยู่ '
            f'<small>ยังไม่ปิด · ราคาที่ขายออกได้</small></h2>'
            + table(['', 'ก้อน', 'ซื้อ', 'ตอนนี้', 'กำไร%', 'กำไร฿', 'วัน', 'SL', 'TP'],
                    rows, pick_first=False)
            + (f'<ul class="cut">{alerts}</ul>' if alerts else '')
            + f'<dl class="rows" style="margin-top:12px"><dt>รวมยังไม่ปิด</dt>'
              f'<dd style="color:{colour}"><b>{n(total, 0)}฿</b></dd></dl>'
            + '</section>')


def _score_card(s: dict) -> str:
    """The scoreboard. Guessed thresholds stay guesses until this is read."""
    if not s or not s['overall']['n']:
        return ''
    label = {'dw': 'A · DW', 'cheap': 'B · หุ้น', 'dr': 'C · DR'}
    rows = []
    for b in ('dw', 'cheap', 'dr'):
        st = s['by_bucket'][b]
        colour = ('var(--up)' if st['net'] > 0
                  else 'var(--down)' if st['net'] < 0 else 'var(--muted)')
        rows.append([f'<b>{label[b]}</b>', st['n'], st['wins'],
                     (f"{n(st['hit_rate'], 0)}%" if st['hit_rate'] is not None else '—'),
                     n(st['fees'], 0),
                     f'<span style="color:{colour}">{n(st["net"], 0)}</span>',
                     f'<span style="color:{colour}">{n(st["expectancy"], 0)}</span>',
                     f'<span style="opacity:.75">{e(st["verdict"])}</span>'])
    o = s['overall']
    colour = 'var(--up)' if o['net'] > 0 else 'var(--down)'
    return ('<section class="card"><h2>ผลจริงจาก journal '
            f'<small>ปิดไปแล้ว {o["n"]} ไม้ · เก็บมา {s["days"]} วัน</small></h2>'
            + table(['ก้อน', 'ไม้', 'ชนะ', '%ชนะ', 'ค่าธรรมเนียม', 'สุทธิ฿',
                     'ต่อไม้฿', 'ควรทำอะไรต่อ'], rows, pick_first=False)
            + f'<dl class="rows" style="margin-top:12px"><dt>รวมทุกก้อน</dt>'
              f'<dd style="color:{colour}"><b>{n(o["net"], 0)}฿</b> '
              f'<span style="opacity:.7">({n(o["expectancy"], 0)}฿/ไม้ · '
              f'ค่าธรรมเนียมไปแล้ว {n(o["fees"], 0)}฿)</span></dd></dl>'
            + '</section>')


def _dw_card(d: dict) -> str:
    if d is None:
        return ''
    sig, fut = d['signal'], d['futures']
    up = (sig['change'] or 0) >= 0
    arrow = '▲' if up else '▼'
    colour = 'var(--up)' if up else 'var(--down)'

    tail = ''
    if d['pick']:
        tail = f"{d['pick']['symbol']} @ {d['pick']['ask']:.2f}"
    elif d['verdict'] == 'wait':
        tail = f"สัญญาณ {sig['composite']:+.0f} · ต้องถึง ±{config.DW_SIGNAL_ENTER}"

    rows = [
        ('HSI (spot)', f'<span style="color:{colour};font-weight:600">'
                       f"{n(sig['close'], 0)} {arrow} {n(sig['change'])}%</span>"),
        ('HSIc1 futures', f"{n(fut['bid'], 0)} / {n(fut['ask'], 0)} "
                          f"<span style='opacity:.6'>· {e(fut['update_time'])} · "
                          'DW อ้างอิงตัวนี้</span>'),
        ('ช่วงวันนี้', f"{n(sig['low'], 0)} – {n(sig['high'], 0)}"
                       f"  <span style='opacity:.6'>ATR15m {n(sig['atr'], 0)}</span>"),
        ('สัญญาณรวม', gauge(sig['composite'], 100.0, config.DW_SIGNAL_ENTER)
                      + f"<div style='margin-top:4px'>{sig['composite']:+.0f} · "
                        f"{e(sig['bias'])}</div>"),
    ]
    for tf in sorted(sig['per_tf'], key=int):
        p = sig['per_tf'][tf]
        rows.append((f'{tf}m · น้ำหนัก {p["weight"]:.0%}',
                     meter(p['rsi'], 100.0) + f"<div style='margin-top:3px;opacity:.75'>"
                     f"RSI {p['rsi']:.0f} · คะแนน {p['score']:+.0f}</div>"))

    dl = ''.join(f'<dt>{e(k)}</dt><dd>{v}</dd>' for k, v in rows)
    out = [f'<h2>ก้อน A · HSI DW <small>ผู้ออก 18 KTX + 28 MACQ · เดย์เทรด</small></h2>',
           badge(d['verdict'], tail), f'<dl class="rows">{dl}</dl>']

    if d['passed']:
        max_eg = max((w['gearing'] for w in d['passed'][:6]
                      if w['gearing'] == w['gearing']), default=1.0)
        rows_html = []
        for w in d['passed'][:6]:
            cls = 'c' if w['side'] == 'C' else 'p'
            rows_html.append([
                f'<span class="tag {cls}">{e(w["symbol"])}</span>',
                n(w['strike'], 0), f"{w['bid']:.2f} / {w['ask']:.2f}",
                f"{n(w['spread_pct'], 1)}%", n(w['breakeven_pts'], 0),
                n(w['theta'], 1),
                meter(w['gearing'], max_eg) + f"<div style='opacity:.7'>{n(w['gearing'], 0)}x</div>",
                w['lots'], n(w['cost'], 0)])
        out.append(table(['DW', 'strike', 'bid / ask', 'spread', 'BE จุด', 'θ/วัน',
                          'gearing', 'lot', 'ทุน ฿'], rows_html))

    if d['plan']:
        p, pick = d['plan'], d['pick']
        out.append('<dl class="rows" style="margin-top:14px">'
                   f'<dt>สั่งซื้อ</dt><dd><b>{e(pick["symbol"])}</b> · {pick["lots"]} lot '
                   f'({pick["units"]:,} หน่วย) @ {pick["ask"]:.2f} = {n(pick["cost"], 0)} ฿</dd>'
                   f'<dt>ราคา DW</dt><dd>{ladder(pick["bid"], pick["ask"], p["sl_price"], p["tp_price"])}'
                   f'<span style="opacity:.7">SL {p["sl_price"]:.2f} · เข้า {pick["ask"]:.2f} '
                   f'· TP {p["tp_price"]:.2f}</span></dd>'
                   f'<dt>เสี่ยง : ได้</dt><dd>{rr_bar(p["sl_price"], pick["ask"], p["tp_price"])}'
                   f'RR {p["rr"]:.1f} · เสียมากสุด {n(p["max_loss_thb"], 0)} ฿</dd>'
                   f'<dt>ถ้าถึง TP</dt><dd><span style="color:var(--up)">'
                   f'+{p["tp_gain_pct"]:.0f}%</span> (สุทธิ +{p["tp_net_pct"]:.0f}%) '
                   f'· HSI ต้องถึง {n(p["index_tp"], 0)}</dd>'
                   f'<dt>ถ้าโดน SL</dt><dd><span style="color:var(--down)">'
                   f'{p["sl_loss_pct"]:.0f}%</span> · HSI หลุด {n(p["index_sl"], 0)}</dd>'
                   f'<dt>ค่าเข้าออก</dt><dd>spread {pick["spread_pct"]:.1f}% + คอม '
                   f'{pick["fee_pct"]:.2f}% · ดัชนีต้องวิ่ง {n(pick["breakeven_pts"], 0)} '
                   'จุดถึงเสมอตัว</dd>'
                   f'<dt>ปิดสถานะ</dt><dd>ไม่เกิน {config.SESSIONS["eod_close"]} น. '
                   '— ห้ามถือข้ามคืน</dd></dl>')

    out.append(cut_list(d['rejected']))
    return '<section class="card">' + ''.join(out) + '</section>'


def _swing_card(d: dict) -> str:
    if d is None:
        return ''
    tail = ' + '.join(m['symbol'] for m in d['passed'][:2]) or 'ถือเงินสด'
    out = [f'<h2>ก้อน B · หุ้นไทย &lt; {config.CHEAP_MAX_PRICE:.0f} บาท '
           f'<small>สวิง {config.CHEAP_HOLD_DAYS} วัน</small></h2>',
           badge(d['verdict'], tail),
           f'<p class="stamp">ผ่านด่านสภาพคล่อง {d["universe"]} ตัว จาก ~430 ตัว '
           f'(ต้องซื้อขาย &gt; {config.CHEAP_MIN_VALUE / 1e6:.0f} ลบ./วัน)</p>']

    if d['passed']:
        max_val = max(m['value_mb'] for m in d['passed'][:6])
        rows = [[f'<b>{e(m["symbol"])}</b>', n(m['close']), f"{n(m['change'], 1)}%",
                 meter(m['value_mb'], max_val) + f"<div style='opacity:.7'>{n(m['value_mb'], 0)}</div>",
                 meter(m['rvol'], 4.0, 'var(--flat)') + f"<div style='opacity:.7'>{n(m['rvol'], 1)}</div>",
                 n(m['rsi'], 0), f"{n(m['perf_w'], 1)}%", m['lots'], n(m['cost'], 0)]
                for m in d['passed'][:6]]
        out.append(table(['หุ้น', 'ราคา', 'chg', 'มูลค่า ลบ.', 'RVOL', 'RSI',
                          'สัปดาห์', 'lot', 'ทุน ฿'], rows))
        out.append(''.join(_entry_rows(m, m['plan'],
                                       f"ถือไม่เกิน {m['plan']['hold_days']} วัน")
                           for m in d['passed'][:2]))
    out.append(cut_list(d['rejected']))
    return '<section class="card">' + ''.join(out) + '</section>'


def _dr_card(d: dict) -> str:
    if d is None:
        return ''
    tail = d['passed'][0]['symbol'] if d['passed'] else 'ถือเงินสด'
    out = [f'<h2>ก้อน C · DR <small>เทรดตาม gap เปิดตลาด</small></h2>',
           badge(d['verdict'], tail),
           f'<p class="stamp">DR ที่มีสภาพคล่อง {d["universe"]} ตัว · '
           f'กรอง NVDR ออก {d["nvdr_filtered"]} รายการ</p>']

    if d['passed']:
        rows = [[f'<b>{e(m["symbol"])}</b>', e(m['name'][:24]), n(m['close']),
                 f"{n(m['gap'], 1)}%",
                 meter(m['rvol'], 4.0, 'var(--flat)') + f"<div style='opacity:.7'>{n(m['rvol'], 1)}</div>",
                 n(m['rsi'], 0), f"{n(m['tick_pct'], 2)}%", m['lots'], n(m['cost'], 0)]
                for m in d['passed'][:6]]
        out.append(table(['DR', 'หุ้นแม่', 'ราคา', 'gap', 'RVOL', 'RSI',
                          '1 ช่อง', 'lot', 'ทุน ฿'], rows))
        m = d['passed'][0]
        out.append(_entry_rows(m, m['plan'], e(m['name'])))
    out.append(cut_list(d['rejected']))
    return '<section class="card">' + ''.join(out) + '</section>'


def _entry_rows(m: dict, p: dict, note: str) -> str:
    return ('<dl class="rows" style="margin-top:14px">'
            f'<dt>สั่งซื้อ</dt><dd><b>{e(m["symbol"])}</b> · {m["lots"]} lot @ '
            f'{p["entry"]:.2f} = {n(m["cost"], 0)} ฿ '
            f'<span style="opacity:.6">· {note}</span></dd>'
            f'<dt>เสี่ยง : ได้</dt><dd>{rr_bar(p["sl"], p["entry"], p["tp"])}'
            f'<span style="color:var(--down)">SL {p["sl"]:.2f} ({p["sl_pct"]:.0f}%)</span> · '
            f'<span style="color:var(--up)">TP {p["tp"]:.2f} (+{p["tp_pct"]:.0f}%)</span> · '
            f'RR {p["rr"]:.1f} · เสียมากสุด {n(p["max_loss_thb"], 0)} ฿</dd></dl>')


def render(brief: dict) -> str:
    ts = brief['generated_at']
    alloc = ''.join(
        f'<span>{label} <b>{brief["budget"][k]:,.0f}฿</b></span>'
        for k, label in (('dw', 'DW'), ('dr', 'DR'), ('cheap', 'หุ้นถูก')))
    errors = ''.join(
        f'<div class="err">ก้อน {e(k)} ดึงข้อมูลไม่ได้ — {e(v)}</div>'
        for k, v in brief['errors'].items())

    sess = brief.get('session') or session.state()
    # The page is cached for 45s and reachable from a phone at any hour, so
    # "this is not live" has to be on the page, not implied by the clock.
    stale = (f'<div class="stale">⚠ {e(sess["note"])}</div>'
             if sess['note'] else '')

    st = brief.get('risk') or risk.state()
    # The web view still shows the market when the day is spent — it is a
    # glance from a phone, not an order slip — but it says so first and loudly.
    stop = (f'<div class="err"><b>✕ หยุดเทรดวันนี้</b> — {e(st["reason"])}</div>'
            if st['blocked'] else '')
    # The rules are config and always true. The running totals come from a
    # journal this page may not have — showing "0/2 ไม้" without one is not an
    # empty state, it is a claim that nothing has been traded today.
    ledger = (f'<span>{e(risk.headline(st))}</span>' if brief.get('has_ledger')
              else '<span style="opacity:.75">โควตาที่เหลือกับสถานะที่ถืออยู่ '
                   'อยู่ในสมุดบน terminal — หน้านี้อ่านไม่ได้</span>')
    quota = (f'<div class="alloc"><span>เสี่ยงได้ต่อไม้ '
             f'<b>{n(config.risk_thb(), 0)}฿</b></span>'
             f'<span>เพดานขาดทุน/วัน <b>{n(st["limit"], 0)}฿</b></span>'
             f'<span>สูงสุด <b>{config.MAX_DAILY_TRADES}</b> ไม้/วัน</span>'
             f'{ledger}</div>')
    held = ''.join(
        f'<span>{e(p.get("bucket", "?"))} <b>{e(p.get("symbol", "?"))}</b> '
        f'{p.get("lots", 0)} lot @ {float(p.get("entry") or 0):.2f}</span>'
        for p in st['open'][:4])
    holding = f'<div class="alloc"><span>ถืออยู่</span>{held}</div>' if held else ''

    return f"""<!doctype html>
<html lang="th"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>แผนเทรดวันนี้ · {ts:%d/%m}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='13' font-size='13'>📈</text></svg>">
<style>{CSS}</style>
</head><body><div class="wrap">
<header><h1>แผนเทรดวันนี้</h1>
<span class="stamp">{ts:%d/%m/%Y} · {ts:%H:%M} น. (กรุงเทพ)</span></header>
<div class="alloc"><span>ทุนรวม <b>{brief['total']:,.0f}฿</b></span>{alloc}</div>
{stale}
{quota}
{holding}
{stop}
{errors}
{_held_card(brief.get('held') or [])}
{_dw_card(brief.get('dw'))}
{_swing_card(brief.get('cheap'))}
{_dr_card(brief.get('dr'))}
{_score_card(brief.get('review'))}
<footer>ข้อมูลจาก TradingView และ thaidw.com · หน้านี้คำนวณสดตอนเปิด<br>
หน้านี้ดูอย่างเดียว — ซื้อขายแล้วบันทึกที่ terminal ด้วย
<code>run.py --took</code> / <code>--close</code><br>
ตัวเลขทั้งหมดเป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน</footer>
</div></body></html>"""

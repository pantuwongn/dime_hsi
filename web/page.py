"""Assemble the full HTML page from a collected brief."""

from trader import config
from .html import (CSS, badge, cut_list, e, gauge, ladder, meter, n, rr_bar,
                   table)


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
{errors}
{_dw_card(brief.get('dw'))}
{_swing_card(brief.get('cheap'))}
{_dr_card(brief.get('dr'))}
<footer>ข้อมูลจาก TradingView และ thaidw.com · หน้านี้คำนวณสดตอนเปิด<br>
ตัวเลขทั้งหมดเป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน</footer>
</div></body></html>"""

#!/usr/bin/env python3
"""
Morning trading brief — run it, place the orders, go to work.

    python3 run.py              # all three buckets
    python3 run.py --bucket dw  # just the HSI warrants
    python3 run.py --plain      # no boxes or bars, for piping into a file

Standard library only: no pandas, no yfinance, no rich to install.
"""

import argparse
import sys

from trader import cache, config, graph, journal, ui
from trader.feeds import tv
from trader.buckets import dw_hsi, cheap, dr
from trader.graph import (bar, big_badge, pad, panel, rr_bar, rsi_gauge,
                          signed_gauge, sparkline)

W = 94                      # panel width in terminal cells
PLAIN = False               # set by --plain


def _panel(title, lines, tone='cyan'):
    if PLAIN:
        print(f'--- {title} ---')
        for ln in lines:
            print(ln)
        print()
    else:
        panel(title, lines, width=W, tone=tone)
        print()


def _fit(widths: list, name: str) -> list:
    """A column set that cannot fit the panel is a bug, not a display quirk."""
    used = sum(widths) + len(widths) - 1
    if used > W - 3:
        raise ValueError(f'{name}: คอลัมน์รวม {used} เกินพื้นที่ในกรอบ {W - 3}')
    return widths


def _row(cells, widths, aligns=None):
    aligns = aligns or ('<' + '>' * (len(cells) - 1))
    return ' '.join(pad(str(v), widths[i], aligns[i]) for i, v in enumerate(cells))


# ------------------------------------------------------------------------------
# BUCKET A — HSI DW
# ------------------------------------------------------------------------------

_DW_W = [12, 8, 12, 12, 7, 6, 14, 5, 7]
_DW_H = ['symbol', 'strike', 'bid/ask', 'spread', 'BE จุด', 'θ/วัน', 'gearing', 'lot', 'ทุน฿']
_fit(_DW_W, 'ตาราง DW')


def show_dw(record: bool) -> None:
    try:
        sig = dw_hsi.index_signal()
        fut = dw_hsi.thaidw.hsi_futures()
    except tv.FeedError as e:
        _panel('ก้อน A · HSI DW', [ui.c(f'✗ ดึงข้อมูลไม่ได้: {e}', 'bright_red')], 'red')
        return

    cache.append('HSI', sig['close'])
    lines = _index_block(sig, fut)

    if sig['side'] is None:
        lines += [''] + big_badge('wait', f"สัญญาณ {sig['composite']:+.0f} "
                                          f"(ต้องถึง ±{config.DW_SIGNAL_ENTER})")
        lines += ['', ui.c('   DW เสีย theta ทุกวัน — วันที่สัญญาณไม่ชัด การอยู่เฉยคือกำไร',
                           'yellow')]
        _panel('ก้อน A · HSI DW · เดย์เทรด', lines, 'bright_yellow')
        if record:
            journal.record('dw', {'action': 'NO_TRADE', 'composite': sig['composite'],
                                  'hsi': sig['close']})
        return

    res = dw_hsi.screen_warrants(sig['side'])
    tone = 'bright_green' if sig['side'] == 'C' else 'bright_red'

    if not res['passed']:
        lines += [''] + big_badge('none', f"สัญญาณ {sig['bias']} แต่ DW ทุกตัวติดเกณฑ์")
        lines += _rejects(res['rejected'])
        _panel('ก้อน A · HSI DW · เดย์เทรด', lines, 'red')
        if record:
            journal.record('dw', {'action': 'NO_INSTRUMENT', 'side': sig['side'],
                                  'composite': sig['composite']})
        return

    lines += [''] + big_badge('call' if sig['side'] == 'C' else 'put',
                              f"{res['passed'][0]['symbol']}  @ {res['passed'][0]['ask']:.2f}")
    lines += ['', graph.divider(W, 'DW ที่เข้าได้จริง')]
    lines.append(ui.c(_row(_DW_H, _DW_W), 'bold'))
    max_eg = max((w['gearing'] for w in res['passed'][:6]
                  if w['gearing'] == w['gearing']), default=1.0)
    for w in res['passed'][:6]:
        lines.append(_row([
            ui.c(w['symbol'], 'bright_green' if w['side'] == 'C' else 'bright_red'),
            ui.fmt(w['strike'], 0), f"{w['bid']:.2f}/{w['ask']:.2f}",
            bar(w['spread_pct'], config.DW_MAX_SPREAD, 7, 'yellow') + f" {w['spread_pct']:.0f}%",
            ui.fmt(w['breakeven_pts'], 0), ui.fmt(w['theta'], 1),
            bar(w['gearing'], max_eg, 9, 'cyan') + f" {w['gearing']:.0f}x",
            w['lots'], ui.fmt(w['cost'], 0)], _DW_W))
    lines += _rejects(res['rejected'])

    pick = res['passed'][0]
    plan = dw_hsi.build_plan(pick, sig)
    lines += ['', graph.divider(W, 'สั่งซื้อ')]
    lines.append('  ' + ui.c(f"{pick['symbol']}   {pick['lots']} lot "
                             f"({pick['units']:,} หน่วย) @ {pick['ask']:.2f}", 'bold', tone)
                 + ui.c(f"   ใช้เงิน {pick['cost']:,.0f}฿", 'dim'))
    lines.append('  ' + pad('ราคา DW', 16)
                 + graph.dw_ladder(pick['bid'], pick['ask'],
                                   plan['tp_price'], plan['sl_price'], width=38)
                 + ui.c(f"  ┫{plan['sl_price']:.2f}  ◆{pick['ask']:.2f}  "
                        f"┣{plan['tp_price']:.2f}", 'dim'))
    lines.append('  ' + pad('เสี่ยง : ได้', 16)
                 + rr_bar(plan['sl_price'], pick['ask'], plan['tp_price'])
                 + ui.c(f"   RR {plan['rr']:.1f}", 'bold'))
    lines.append('  ' + pad('กำไรถ้าถึง TP', 16)
                 + ui.c(f"+{plan['tp_gain_pct']:.0f}%", 'bright_green')
                 + ui.c(f"  (สุทธิหลังค่าเข้าออก +{plan['tp_net_pct']:.0f}%)  "
                        f"HSI ต้องถึง {ui.fmt(plan['index_tp'], 0)}", 'dim'))
    lines.append('  ' + pad('ขาดทุนถ้าโดน SL', 16)
                 + ui.c(f"{plan['sl_loss_pct']:.0f}%", 'bright_red')
                 + ui.c(f"  = {plan['max_loss_thb']:,.0f}฿  "
                        f"HSI หลุด {ui.fmt(plan['index_sl'], 0)}", 'dim'))
    lines.append('  ' + ui.c(f"ค่าเข้าออก spread {pick['spread_pct']:.1f}% + คอม "
                             f"{pick['fee_pct']:.2f}% — ดัชนีต้องวิ่ง "
                             f"{pick['breakeven_pts']:.0f} จุดถึงเสมอตัว", 'dim'))
    lines.append('  ' + ui.c(f"⚠  ปิดสถานะไม่เกิน {config.SESSIONS['eod_close']} น. "
                             '— ห้ามถือ DW ข้ามคืน', 'yellow'))

    _panel('ก้อน A · HSI DW · เดย์เทรด', lines, tone)
    if record:
        journal.record('dw', {'action': 'ENTER', 'symbol': pick['symbol'],
                              'side': pick['side'], 'entry': pick['ask'],
                              'lots': pick['lots'], 'cost': pick['cost'],
                              'tp': plan['tp_price'], 'sl': plan['sl_price'],
                              'composite': sig['composite'], 'hsi': sig['close']})


def _index_block(sig, fut) -> list:
    up = (sig['change'] or 0) >= 0
    tone = 'bright_green' if up else 'bright_red'
    lines = []
    lines.append('  ' + pad('HSI (spot)', 16)
                 + ui.c(pad(f"{ui.fmt(sig['close'], 0)}  {'▲' if up else '▼'} "
                            f"{ui.fmt(sig['change'])}%", 18), 'bold', tone)
                 + sparkline(cache.series('HSI'))
                 + ui.c('   ← สะสมจากรอบก่อน ๆ', 'dim'))
    lines.append('  ' + pad('HSIc1 (futures)', 16)
                 + pad(f"{ui.fmt(fut['bid'], 0)} / {ui.fmt(fut['ask'], 0)}", 18)
                 + ui.c(f"อัปเดต {fut['update_time']} — DW อ้างอิงตัวนี้ ไม่ใช่ spot", 'dim'))
    lines.append('  ' + pad('ช่วงราคาวันนี้', 16)
                 + pad(ui.fmt(sig['low'], 0), 8)
                 + graph.range_position(sig['low'], sig['high'], sig['close'])
                 + ' ' + ui.fmt(sig['high'], 0)
                 + ui.c(f"   ATR15m {ui.fmt(sig['atr'], 0)}", 'dim'))

    lines += ['', graph.divider(W, 'สัญญาณ')]
    gauge = signed_gauge(sig['composite'], 100.0, 30, enter=config.DW_SIGNAL_ENTER)
    head, marks = gauge.split('\n')
    bias_tone = ('bright_green' if sig['side'] == 'C'
                 else 'bright_red' if sig['side'] == 'P' else 'yellow')
    lines.append('  ' + pad('รวมถ่วงน้ำหนัก', 16) + head
                 + ui.c(pad(f"  {sig['composite']:+.0f}", 7), 'bold', bias_tone)
                 + ui.c(f"  {sig['bias']}", 'bold', bias_tone))
    lines.append('  ' + pad('', 16) + marks + ui.c('   ▲ = เกณฑ์เข้า ±'
                                                   f"{config.DW_SIGNAL_ENTER}", 'dim'))
    for tf in sorted(sig['per_tf'], key=int):
        p = sig['per_tf'][tf]
        lines.append('  ' + pad(f'{tf}m', 6) + pad(f"น้ำหนัก {p['weight']:.0%}", 12)
                     + rsi_gauge(p['rsi']) + pad(f"  RSI {p['rsi']:.0f}", 10)
                     + ui.c(pad(f"{p['score']:+.0f}", 6, '>'),
                            'green' if p['score'] > 0 else 'red'))
    if sig['missing_tf']:
        lines.append('  ' + ui.c(f"⚠ ไม่มีข้อมูล {', '.join(sig['missing_tf'])} "
                                 '— คะแนนคิดจากที่เหลือ', 'yellow'))
    lines.append('  ' + ui.c(f"EMA stack (15m): {sig['aligned']}", 'dim'))
    return lines


def _rejects(rejected: list, limit: int = 8) -> list:
    if not rejected:
        return []
    out = ['', ui.c('  ตัดทิ้ง', 'dim')]
    for r in rejected[:limit]:
        out.append('    ' + ui.c(pad(r['symbol'], 14) + r['reject'], 'dim'))
    if len(rejected) > limit:
        out.append('    ' + ui.c(f'... อีก {len(rejected) - limit} ตัว', 'dim'))
    return out


# ------------------------------------------------------------------------------
# BUCKET B — cheap SET stocks
# ------------------------------------------------------------------------------

_CH_W = [9, 7, 7, 13, 13, 13, 8, 5, 7]
_CH_H = ['symbol', 'ราคา', 'chg%', 'มูลค่า ลบ.', 'RVOL', 'RSI', 'สัปดาห์%', 'lot', 'ทุน฿']
_fit(_CH_W, 'ตารางหุ้นถูก')


def show_cheap(record: bool) -> None:
    try:
        res = cheap.scan()
    except tv.FeedError as e:
        _panel('ก้อน B · หุ้นไทยราคาต่ำ', [ui.c(f'✗ ดึงข้อมูลไม่ได้: {e}', 'bright_red')], 'red')
        return

    lines = ['  ' + ui.c(f"ผ่านด่านสภาพคล่อง {res['universe']} ตัว", 'bold')
             + ui.c(f"  จาก ~430 ตัวที่ราคา < {config.CHEAP_MAX_PRICE:.0f}฿ "
                    f"(ต้องซื้อขาย > {config.CHEAP_MIN_VALUE / 1e6:.0f} ลบ./วัน)", 'dim')]

    if not res['passed']:
        lines += [''] + big_badge('wait', 'ไม่มีตัวไหนผ่านเกณฑ์โมเมนตัม → ถือเงินสด')
        lines += _rejects(res['rejected'])
        _panel('ก้อน B · หุ้นไทย < 3฿ · สวิง', lines, 'yellow')
        return

    lines += [''] + big_badge('buy', ' + '.join(m['symbol'] for m in res['passed'][:2]))

    lines += ['', ui.c(_row(_CH_H, _CH_W), 'bold')]
    max_val = max(m['value_mb'] for m in res['passed'][:6])
    for m in res['passed'][:6]:
        lines.append(_row([
            m['symbol'], ui.fmt(m['close']), ui.fmt(m['change'], 1),
            bar(m['value_mb'], max_val, 8, 'blue') + f" {m['value_mb']:.0f}",
            bar(m['rvol'], 4.0, 8, 'magenta') + f" {ui.fmt(m['rvol'], 1)}",
            rsi_gauge(m['rsi'], 8) + f" {ui.fmt(m['rsi'], 0)}",
            ui.fmt(m['perf_w'], 1), m['lots'], ui.fmt(m['cost'], 0)], _CH_W))
    lines += _rejects(res['rejected'])

    lines += ['', graph.divider(W, 'สั่งซื้อ')]
    for m in res['passed'][:2]:
        lines += _entry_block(m, m['plan'],
                              note=f"ถือไม่เกิน {m['plan']['hold_days']} วัน")
        if record:
            journal.record('cheap', {'action': 'ENTER', 'symbol': m['symbol'],
                                     'entry': m['plan']['entry'], 'lots': m['lots'],
                                     'cost': m['cost'], 'tp': m['plan']['tp'],
                                     'sl': m['plan']['sl']})
    _panel(f"ก้อน B · หุ้นไทย < {config.CHEAP_MAX_PRICE:.0f}฿ · "
           f"สวิง {config.CHEAP_HOLD_DAYS} วัน", lines, 'green')


# ------------------------------------------------------------------------------
# BUCKET C — DR
# ------------------------------------------------------------------------------

_DR_W = [10, 15, 7, 6, 12, 12, 7, 5, 7]
_DR_H = ['symbol', 'ชื่อ', 'ราคา', 'gap%', 'RVOL', 'RSI', '1 ช่อง%', 'lot', 'ทุน฿']
_fit(_DR_W, 'ตาราง DR')


def show_dr(record: bool) -> None:
    try:
        res = dr.scan()
    except tv.FeedError as e:
        _panel('ก้อน C · DR', [ui.c(f'✗ ดึงข้อมูลไม่ได้: {e}', 'bright_red')], 'red')
        return

    lines = ['  ' + ui.c(f"DR ที่มีสภาพคล่อง {res['universe']} ตัว", 'bold')
             + ui.c(f"  กรอง NVDR ออก {res['nvdr_filtered']} รายการ", 'dim')]
    if res.get('dupes'):
        dupe_txt = ', '.join(f'{a}→{b}' for a, b in res['dupes'][:4])
        lines.append('  ' + ui.c(f'รวมหุ้นแม่ซ้ำ: {dupe_txt}', 'dim'))

    if not res['passed']:
        lines += [''] + big_badge('wait', 'ไม่มี DR ตัวไหนผ่านเกณฑ์ → ถือเงินสด')
        lines += _rejects(res['rejected'])
        _panel('ก้อน C · DR', lines, 'yellow')
        return

    lines += [''] + big_badge('buy', res['passed'][0]['symbol'])

    lines += ['', ui.c(_row(_DR_H, _DR_W), 'bold')]
    for m in res['passed'][:6]:
        lines.append(_row([
            m['symbol'], m['name'][:14], ui.fmt(m['close']), ui.fmt(m['gap'], 1),
            bar(m['rvol'], 4.0, 8, 'magenta') + f" {ui.fmt(m['rvol'], 1)}",
            rsi_gauge(m['rsi'], 8) + f" {ui.fmt(m['rsi'], 0)}",
            ui.fmt(m['tick_pct'], 2), m['lots'], ui.fmt(m['cost'], 0)], _DR_W))

    lines += ['', graph.divider(W, 'สั่งซื้อ')]
    m = res['passed'][0]
    lines += _entry_block(m, m['plan'], note=m['name'])
    _panel('ก้อน C · DR · เทรดตาม gap เปิดตลาด', lines, 'blue')
    if record:
        journal.record('dr', {'action': 'ENTER', 'symbol': m['symbol'],
                              'entry': m['plan']['entry'], 'lots': m['lots'],
                              'cost': m['cost'], 'tp': m['plan']['tp'],
                              'sl': m['plan']['sl']})


def _entry_block(m: dict, p: dict, note: str = '') -> list:
    return [
        '  ' + ui.c(f"{m['symbol']}   {m['lots']} lot @ {p['entry']:.2f}", 'bold', 'green')
        + ui.c(f"   = {m['cost']:,.0f}฿   เสียมากสุด {p['max_loss_thb']:,.0f}฿   {note}", 'dim'),
        '  ' + pad('', 16) + rr_bar(p['sl'], p['entry'], p['tp'], 24)
        + ui.c(f"  SL {p['sl']:.2f} ({p['sl_pct']:.0f}%)", 'bright_red')
        + ui.c(f"  TP {p['tp']:.2f} (+{p['tp_pct']:.0f}%)", 'bright_green')
        + ui.c(f"  RR {p['rr']:.1f}", 'bold'),
    ]


# ------------------------------------------------------------------------------

def header() -> None:
    now = journal.now_bkk()
    total = config.BUDGET_TOTAL
    lines = ['  ' + ui.c(f"{now:%A %d/%m/%Y}  ·  {now:%H:%M} น. (กรุงเทพ)", 'bold')]
    alloc = '  ' + pad(f'ทุนรวม {total:,.0f}฿', 18)
    for key, label, tone in (('dw', 'DW', 'red'), ('dr', 'DR', 'blue'),
                             ('cheap', 'หุ้นถูก', 'green')):
        alloc += f"{label} " + bar(config.ALLOC[key], total, 10, tone) \
                 + f" {config.ALLOC[key]:,.0f}   "
    lines.append(alloc)
    if config.MIN_COMM > 0:
        lines.append('  ' + ui.c(f"⚠ ค่าคอมขั้นต่ำ {config.MIN_COMM:.0f}฿/วัน "
                                 '— ไม้เล็กจะโดนค่าธรรมเนียมกิน', 'yellow'))
    _panel('แผนเทรดวันนี้', lines, 'magenta')


def main() -> int:
    global PLAIN
    ap = argparse.ArgumentParser(description='แผนเทรดรายวัน 3 ก้อน: DW HSI / หุ้นไทยถูก / DR')
    ap.add_argument('--bucket', default='all', choices=['all', 'dw', 'cheap', 'dr'])
    ap.add_argument('--no-journal', action='store_true', help='ไม่บันทึกลง journal.jsonl')
    ap.add_argument('--plain', action='store_true', help='ปิดกรอบและแถบกราฟ')
    ap.add_argument('--color', action='store_true',
                    help='บังคับใช้สีแม้ pipe ออกไฟล์ (คู่กับ less -R)')
    ap.add_argument('--html', metavar='FILE',
                    help='สร้างหน้าเว็บแบบเดียวกับที่ deploy แล้วเขียนลงไฟล์')
    args = ap.parse_args()

    PLAIN = args.plain
    if args.color:
        ui.force_color(True)

    if args.html:
        from web.page import render
        from web.report import collect
        with open(args.html, 'w', encoding='utf-8') as fh:
            fh.write(render(collect(
                ('dw', 'cheap', 'dr') if args.bucket == 'all' else (args.bucket,))))
        print(f'เขียน {args.html} แล้ว — เปิดด้วยเบราว์เซอร์เพื่อดูหน้าเว็บ')
        return 0
    rec = not args.no_journal
    print()
    header()
    if args.bucket in ('all', 'dw'):
        show_dw(rec)
    if args.bucket in ('all', 'cheap'):
        show_cheap(rec)
    if args.bucket in ('all', 'dr'):
        show_dr(rec)
    print(ui.c('  ตัวเลขทั้งหมดเป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน\n', 'dim'))
    return 0


if __name__ == '__main__':
    sys.exit(main())

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

from trader import (cache, config, graph, journal, marks, review, risk,
                    session, sizing, ui)
from trader.feeds import tv
from trader.buckets import dw, cheap, dr
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
# BUCKETS A and D — DW, one panel per series (HSI, SET50)
# ------------------------------------------------------------------------------

_DW_W = [12, 8, 12, 12, 7, 6, 14, 5, 7]
_DW_H = ['symbol', 'strike', 'bid/ask', 'spread', 'BE จุด', 'θ/วัน', 'gearing', 'lot', 'ทุน฿']
_fit(_DW_W, 'ตาราง DW')


def show_dw(record: bool, key: str = 'dw') -> None:
    sr = dw.series(key)
    title = f"ก้อน {config.BUCKET_LABEL[key]}"
    try:
        sig = dw.index_signal(key)
        # The future is a nice-to-have: it labels what the DW really tracks.
        # Losing it is not losing the bucket, so it is fetched separately.
        try:
            fut = dw.thaidw.futures(sr['futures']) if sr['futures'] else None
        except tv.FeedError:
            fut = None
    except tv.FeedError as e:
        _panel(title, [ui.c(f'✗ ดึงข้อมูลไม่ได้: {e}', 'bright_red')], 'red')
        return

    cache.append(sr['name'], sig['close'])
    lines = _stale_line(key) + _index_block(sig, fut, sr)

    if sig['side'] is None:
        veto = sig.get('vetoed_by_align')
        if veto:
            tail = (f"สัญญาณ {sig['composite']:+.0f} ผ่านเกณฑ์ "
                    f"แต่ EMA 15m ยัง {veto}")
            why = '   คะแนนพุ่งตอนราคายังพันกับเส้นค่าเฉลี่ยตัวเอง — spread จ่ายจริง แต่ move ไม่มา'
        else:
            tail = f"สัญญาณ {sig['composite']:+.0f} (ต้องถึง ±{config.DW_SIGNAL_ENTER})"
            why = '   DW เสีย theta ทุกวัน — วันที่สัญญาณไม่ชัด การอยู่เฉยคือกำไร'
        lines += [''] + big_badge('wait', tail)
        lines += ['', ui.c(why, 'yellow')]
        _panel(f'{title} · เดย์เทรด', lines, 'bright_yellow')
        if record:
            journal.record(key, {'action': 'NO_TRADE', 'composite': sig['composite'],
                                 'index': sig['close']})
        return

    res = dw.screen_warrants(sig['side'], sig, key=key)
    tone = 'bright_green' if sig['side'] == 'C' else 'bright_red'

    if not res['passed']:
        lines += [''] + big_badge('none', f"สัญญาณ {sig['bias']} แต่ DW ทุกตัวติดเกณฑ์")
        lines += _rejects(res['rejected'])
        _panel(f'{title} · เดย์เทรด', lines, 'red')
        if record:
            journal.record(key, {'action': 'NO_INSTRUMENT', 'side': sig['side'],
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
    plan = pick['plan']
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
                        f"{sr['name']} ต้องถึง {ui.fmt(plan['index_tp'], 0)}", 'dim'))
    lines.append('  ' + pad('ขาดทุนถ้าโดน SL', 16)
                 + ui.c(f"{plan['sl_loss_pct']:.0f}%", 'bright_red')
                 + ui.c(f"  = {plan['max_loss_thb']:,.0f}฿  "
                        f"{sr['name']} หลุด {ui.fmt(plan['index_sl'], 0)}", 'dim'))
    lines.append('  ' + ui.c(f"ค่าเข้าออก spread {pick['spread_pct']:.1f}% + คอม "
                             f"{pick['fee_pct']:.2f}% — ดัชนีต้องวิ่ง "
                             f"{pick['breakeven_pts']:.0f} จุดถึงเสมอตัว", 'dim'))
    lines.append('  ' + pad('เสี่ยงไม้นี้', 16)
                 + ui.c(f"{plan['max_loss_thb']:,.0f}฿", 'bold')
                 + ui.c(f"  = {plan['risk_pct_account']:.1f}% ของพอร์ต "
                        f"(เพดาน {config.RISK_PER_TRADE:.1%})  "
                        f"ขนาดไม้ถูกจำกัดด้วย{pick.get('capped_by') or '—'}", 'dim'))
    lines.append('  ' + ui.c(f"⚠  ปิดสถานะไม่เกิน {config.SESSIONS['eod_close']} น. "
                             '— ห้ามถือ DW ข้ามคืน', 'yellow'))
    lines.append('  ' + ui.c(f"ซื้อจริงแล้วยืนยันด้วย  python3 run.py --took "
                             f"{pick['symbol']} --bucket {key}"
                             '  เพื่อให้เบรกเกอร์นับไม้นี้', 'dim'))

    _panel(f'{title} · เดย์เทรด', lines, tone)
    if record:
        journal.record(key, {'action': 'SIGNAL', 'symbol': pick['symbol'],
                             'side': pick['side'], 'entry': pick['ask'],
                             'lots': pick['lots'], 'cost': pick['cost'],
                             'tp': plan['tp_price'], 'sl': plan['sl_price'],
                             'risk_thb': plan['max_loss_thb'],
                             'composite': sig['composite'], 'index': sig['close']})


def _index_block(sig, fut, sr: dict) -> list:
    name = sr['name']
    up = (sig['change'] or 0) >= 0
    tone = 'bright_green' if up else 'bright_red'
    lines = []
    lines.append('  ' + pad(f'{name} (spot)', 16)
                 + ui.c(pad(f"{ui.fmt(sig['close'], 0)}  {'▲' if up else '▼'} "
                            f"{ui.fmt(sig['change'])}%", 18), 'bold', tone)
                 + sparkline(cache.series(name))
                 + ui.c('   ← สะสมจากรอบก่อน ๆ', 'dim'))
    if fut:
        label = f"{fut['symbol']} (futures)"
        if len(label) >= 16:            # long future codes keep the short form
            label = f"{fut['symbol']} (fut)"
        lines.append('  ' + pad(label, 16)
                     + pad(f"{ui.fmt(fut['bid'], 0)} / {ui.fmt(fut['ask'], 0)}", 18)
                     + ui.c(f"อัปเดต {fut['update_time']} — DW อ้างอิงตัวนี้ ไม่ใช่ spot",
                            'dim'))
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
    held = [p for p in risk.open_positions() if p.get('bucket') == 'cheap']
    cash = max(0.0, config.ALLOC['cheap'] - sum(float(p.get('cost') or 0) for p in held))
    try:
        res = cheap.scan(cash=cash, exclude=_exclude('cheap', held))
    except tv.FeedError as e:
        _panel('ก้อน B · หุ้นไทยราคาต่ำ', [ui.c(f'✗ ดึงข้อมูลไม่ได้: {e}', 'bright_red')], 'red')
        return

    lines = _stale_line('cheap')
    lines += ['  ' + ui.c(f"ผ่านด่านสภาพคล่อง {res['universe']} ตัว", 'bold')
             + ui.c(f"  จาก ~430 ตัวที่ราคา < {config.CHEAP_MAX_PRICE:.0f}฿ "
                    f"(ต้องซื้อขาย > {config.CHEAP_MIN_VALUE / 1e6:.0f} ลบ./วัน)", 'dim')]
    lines += _cash_line(held, cash, config.ALLOC['cheap'])

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
            journal.record('cheap', {'action': 'SIGNAL', 'symbol': m['symbol'],
                                     'entry': m['plan']['entry'], 'lots': m['lots'],
                                     'cost': m['cost'], 'tp': m['plan']['tp'],
                                     'sl': m['plan']['sl'],
                                     'risk_thb': m['plan']['max_loss_thb']})
    _panel(f"ก้อน B · หุ้นไทย < {config.CHEAP_MAX_PRICE:.0f}฿ · "
           f"สวิง {config.CHEAP_HOLD_DAYS} วัน", lines, 'green')


# ------------------------------------------------------------------------------
# BUCKET C — DR
# ------------------------------------------------------------------------------

_DR_W = [10, 15, 7, 6, 12, 12, 7, 5, 7]
_DR_H = ['symbol', 'ชื่อ', 'ราคา', 'gap%', 'RVOL', 'RSI', '1 ช่อง%', 'lot', 'ทุน฿']
_fit(_DR_W, 'ตาราง DR')


def show_dr(record: bool) -> None:
    held = [p for p in risk.open_positions() if p.get('bucket') == 'dr']
    cash = max(0.0, config.ALLOC['dr'] - sum(float(p.get('cost') or 0) for p in held))
    try:
        res = dr.scan(cash=cash, exclude=_exclude('dr', held))
    except tv.FeedError as e:
        _panel('ก้อน C · DR', [ui.c(f'✗ ดึงข้อมูลไม่ได้: {e}', 'bright_red')], 'red')
        return

    lines = _stale_line('dr')
    lines += ['  ' + ui.c(f"DR ที่มีสภาพคล่อง {res['universe']} ตัว", 'bold')
             + ui.c(f"  กรอง NVDR ออก {res['nvdr_filtered']} รายการ", 'dim')]
    lines += _cash_line(held, cash, config.ALLOC['dr'])
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
        journal.record('dr', {'action': 'SIGNAL', 'symbol': m['symbol'],
                              'entry': m['plan']['entry'], 'lots': m['lots'],
                              'cost': m['cost'], 'tp': m['plan']['tp'],
                              'sl': m['plan']['sl'],
                              'risk_thb': m['plan']['max_loss_thb']})


def _stale_line(bucket: str) -> list:
    """Say it in the panel too — the header scrolls off, the badge does not."""
    note = session.bucket_note(bucket)
    return ['  ' + ui.c(f'⚠  {note}', 'bright_yellow'), ''] if note else []


def _exclude(bucket: str, held: list) -> dict:
    """Symbols this bucket must not recommend today, each with its reason."""
    out = {p['symbol']: 'ถืออยู่แล้ว — เงินก้อนนี้ยังไม่ว่าง' for p in held}
    for sym in risk.stopped_today(bucket):
        out.setdefault(sym, 'เพิ่งโดน SL วันนี้ — ไม่เข้าซ้ำในวันเดียวกัน')
    return out


def _cash_line(held: list, cash: float, alloc: float) -> list:
    """Money already in the market is not money you can size against."""
    if not held:
        return []
    txt = ', '.join(f"{p['symbol']} {p.get('lots', 0)} lot" for p in held[:3])
    return ['  ' + ui.c(f"ถืออยู่ {txt}", 'bold')
            + ui.c(f"   เงินว่างจริง {cash:,.0f}฿ จาก {alloc:,.0f}฿ "
                   '— คิดขนาดไม้จากเงินว่าง ไม่ใช่จากงบเต็ม', 'dim')]


def _entry_block(m: dict, p: dict, note: str = '') -> list:
    return [
        '  ' + ui.c(f"{m['symbol']}   {m['lots']} lot @ {p['entry']:.2f}", 'bold', 'green')
        + ui.c(f"   = {m['cost']:,.0f}฿   เสี่ยง {p['max_loss_thb']:,.0f}฿ "
               f"({p['risk_pct_account']:.1f}%)   {note[:20]}", 'dim'),
        '  ' + pad('', 16) + rr_bar(p['sl'], p['entry'], p['tp'], 24)
        + ui.c(f"  SL {p['sl']:.2f} ({p['sl_pct']:.0f}%)", 'bright_red')
        + ui.c(f"  TP {p['tp']:.2f} (+{p['tp_pct']:.0f}%)", 'bright_green')
        + ui.c(f"  RR {p['rr']:.1f}", 'bold'),
    ]


# ------------------------------------------------------------------------------

_POS_W = [13, 6, 8, 8, 9, 9, 5, 7, 7]
_POS_H = ['symbol', 'ก้อน', 'ซื้อ', 'ตอนนี้', 'กำไร%', 'กำไร฿', 'วัน', 'SL', 'TP']
_fit(_POS_W, 'ตารางสถานะ')


def show_positions(st: dict) -> None:
    """What is already on the table, priced at what you could exit for."""
    if not st['open']:
        return
    try:
        held = marks.mark(st['open'])
    except Exception as e:                      # a dead feed must not hide them
        held = [dict(p, now=None, pnl_pct=None, pnl_thb=None, days_held=0,
                     alert=f'ดึงราคาไม่ได้: {e}') for p in st['open']]

    lines = [ui.c(_row(_POS_H, _POS_W), 'bold')]
    total = 0.0
    for m in held:
        pnl = m.get('pnl_thb')
        total += pnl or 0.0
        tone = ('bright_green' if (pnl or 0) > 0
                else 'bright_red' if (pnl or 0) < 0 else 'dim')
        lines.append(_row([
            ui.c(m['symbol'], 'bold'), m.get('bucket', '?'),
            f"{float(m.get('entry') or 0):.2f}",
            ui.fmt(m.get('now')), 
            ui.c(ui.fmt(m.get('pnl_pct'), 1), tone),
            ui.c(ui.fmt(pnl, 0), tone),
            m.get('days_held', 0),
            f"{float(m.get('sl') or 0):.2f}", f"{float(m.get('tp') or 0):.2f}",
        ], _POS_W))
    for m in held:
        if m.get('alert'):
            hot = m['hit_sl'] or m['hit_tp'] or m['stale']
            lines.append('  ' + ui.c(f"{'▲' if hot else '·'} {m['symbol']}  "
                                     f"{m['alert']}", 'bright_yellow' if hot else 'dim'))
    tone = 'bright_green' if total > 0 else 'bright_red' if total < 0 else 'dim'
    lines.append('')
    lines.append('  ' + pad('รวมยังไม่ปิด', 18)
                 + ui.c(f"{total:+,.0f}฿", 'bold', tone)
                 + ui.c(f"   ทุนที่จมอยู่ {sum(float(p.get('cost') or 0) for p in held):,.0f}฿",
                        'dim'))
    _panel('สถานะที่ถืออยู่', lines, 'cyan')


# Short enough that four buckets still fit one line of the header.
_ALLOC_LABEL = {'dw': ('HSI', 'red'), 's50': ('S50', 'magenta'),
                'cheap': ('หุ้น', 'green'), 'dr': ('DR', 'blue')}


def header(st: dict = None) -> None:
    now = journal.now_bkk()
    total = config.BUDGET_TOTAL
    st = risk.state() if st is None else st
    lines = ['  ' + ui.c(f"{now:%A %d/%m/%Y}  ·  {now:%H:%M} น. (กรุงเทพ)", 'bold')]
    alloc = '  ' + pad(f'ทุนรวม {total:,.0f}฿', 18)
    for key in config.BUCKET_ORDER:
        label, tone = _ALLOC_LABEL[key]
        if config.ALLOC.get(key, 0.0) <= 0:   # paused — no empty bar, just say so
            alloc += ui.c(f"{label} พัก  ", 'dim')
            continue
        alloc += f"{label} " + bar(config.ALLOC[key], total, 7, tone) \
                 + f" {config.ALLOC[key]:,.0f}  "
    lines.append(alloc)
    lines.append('  ' + pad('เสี่ยงได้ต่อไม้', 18)
                 + ui.c(f"{config.risk_thb():,.0f}฿", 'bold')
                 + ui.c(f" ({config.RISK_PER_TRADE:.1%})   เพดานขาดทุน/วัน "
                        f"{config.daily_loss_limit():,.0f}฿ "
                        f"({config.MAX_DAILY_LOSS:.0%})   สูงสุด "
                        f"{config.MAX_DAILY_TRADES} ไม้/วัน", 'dim'))
    quota = bar(st['remaining'], st['limit'], 12,
                'green' if st['remaining'] > st['limit'] / 2 else 'yellow')
    lines.append('  ' + pad('โควตาวันนี้', 18) + quota
                 + ui.c(f"  {risk.headline(st)}", 'dim'))
    for pos in st['open'][:3]:
        lines.append('    ' + ui.c(f"ถืออยู่ · {pos.get('bucket', '?')} "
                                   f"{pos.get('symbol', '?')} {pos.get('lots', 0)} lot "
                                   f"@ {float(pos.get('entry') or 0):.2f} "
                                   f"· SL {float(pos.get('sl') or 0):.2f} "
                                   f"· เสี่ยง {float(pos.get('risk_thb') or 0):,.0f}฿", 'dim'))
    sess = session.state(now)
    if sess['note']:
        lines.append('  ' + ui.c(f"⚠  {sess['note']}", 'bright_yellow'))
    if config.MIN_COMM > 0:
        lines.append('  ' + ui.c(f"⚠ ค่าคอมขั้นต่ำ {config.MIN_COMM:.0f}฿/วัน "
                                 '— ไม้เล็กจะโดนค่าธรรมเนียมกิน', 'yellow'))
    _panel('แผนเทรดวันนี้', lines, 'red' if st['blocked'] else 'magenta')


_REV_W = [10, 5, 5, 7, 10, 10, 11, 10, 9]
_REV_H = ['ก้อน', 'ไม้', 'ชนะ', '%ชนะ', 'ได้เฉลี่ย', 'เสียเฉลี่ย', 'ค่าธรรมเนียม',
          'สุทธิ฿', 'ต่อไม้฿']
_fit(_REV_W, 'ตารางสรุปผล')

_BUCKET_LABEL = config.BUCKET_LABEL


def cmd_review() -> int:
    """
    Read the journal back. Every threshold in config.py is a guess until this
    says otherwise, and the point of measuring is to be willing to close a
    bucket that does not earn — which is why the verdict is blunt.
    """
    s = review.summarise()
    if not s['trades'] and not s['signals']:
        ui.fail('journal ยังว่าง — ต้อง --took ตอนซื้อ และ --close ตอนขาย ถึงจะวัดได้')
        return 1

    lines = ['  ' + ui.c(f"ปิดไปแล้ว {s['overall']['n']} ไม้", 'bold')
             + ui.c(f"   สัญญาณ {s['signals']} ครั้ง เข้าจริง {s['entered']} ครั้ง"
                    + (f" ({s['taken_pct']:.0f}%)" if s['taken_pct'] else '')
                    + f"   เก็บข้อมูลมา {s['days']} วัน", 'dim'),
             '']
    lines.append(ui.c(_row(_REV_H, _REV_W), 'bold'))
    for b in config.BUCKET_ORDER:
        st = s['by_bucket'][b]
        tone = ('bright_green' if st['net'] > 0
                else 'bright_red' if st['net'] < 0 else 'dim')
        lines.append(_row([
            _BUCKET_LABEL[b], st['n'], st['wins'],
            ui.fmt(st['hit_rate'], 0) + ('%' if st['hit_rate'] is not None else ''),
            ui.fmt(st['avg_win'], 0), ui.fmt(st['avg_loss'], 0),
            ui.fmt(st['fees'], 0),
            ui.c(f"{st['net']:+,.0f}", tone),
            ui.c(f"{st['expectancy']:+,.0f}", tone)], _REV_W))

    lines += ['', graph.divider(W, 'ควรทำอะไรต่อ')]
    for b in config.BUCKET_ORDER:
        st = s['by_bucket'][b]
        tone = ('dim' if st['n'] < review.MIN_SAMPLE
                else 'bright_green' if st['expectancy'] > 0 else 'bright_red')
        lines.append('  ' + pad(_BUCKET_LABEL[b], 12) + ui.c(st['verdict'], tone))

    o = s['overall']
    if o['n']:
        tone = 'bright_green' if o['net'] > 0 else 'bright_red'
        lines += ['', '  ' + pad('รวมทุกก้อน', 18)
                  + ui.c(f"{o['net']:+,.0f}฿", 'bold', tone)
                  + ui.c(f"   ({o['expectancy']:+,.0f}฿/ไม้ · ชนะ "
                         f"{ui.fmt(o['hit_rate'], 0)}% · ค่าธรรมเนียมไปแล้ว "
                         f"{o['fees']:,.0f}฿)", 'dim')]
        lines.append('  ' + ui.c(f"ดีสุด {o['best']:+,.0f}฿ · แย่สุด {o['worst']:+,.0f}฿ "
                                 f"· เทียบทุน {config.BUDGET_TOTAL:,.0f}฿ = "
                                 f"{o['net'] / config.BUDGET_TOTAL * 100:+.1f}%", 'dim'))

    if s['trades']:
        lines += ['', graph.divider(W, 'ไม้ล่าสุด')]
        for t in s['trades'][-6:]:
            tone = 'bright_green' if t['pnl'] > 0 else 'bright_red'
            lines.append('  ' + pad(str(t['symbol']), 14)
                         + pad(_BUCKET_LABEL.get(t['bucket'], '?'), 12)
                         + pad(f"{t['entry']:.2f} → {t['exit']:.2f}", 13)
                         + ui.c(pad(f"{t['pnl']:+,.0f}฿", 10, '>'), tone)
                         + ui.c(f"   {t['pnl_pct']:+.1f}%   ถือ {t['days']} วัน", 'dim'))

    _panel('ผลจริงจาก journal', lines, 'magenta')
    return 0


def cmd_took(symbol: str, price: float = None, lots: int = None,
             sl: float = None, tp: float = None, bucket: str = None) -> int:
    """
    Confirm that a recommendation actually became a position.

    The journal used to write ENTER every time the script produced a
    recommendation, which made "how many trades today" the same number as "how
    many times did I run this" — useless as a limit. Recommendations are SIGNAL
    now, and only this turns one into a trade the breaker counts.

    The suggestion is a default, never the record. Partial fills, a different
    price, a smaller size because you had second thoughts, or a name the tool
    never mentioned — all of it has to be writable, because a ledger that only
    accepts what was predicted is a ledger of predictions, not of trades.
    """
    symbol = symbol.upper()
    sig = None
    for r in journal.load():
        if r.get('action') == 'SIGNAL' and str(r.get('symbol', '')).upper() == symbol:
            sig = r

    if sig is None and (sl is None or not price or not lots):
        ui.fail(f'ไม่เจอสัญญาณของ {symbol} ใน journal')
        print(ui.c('  ถ้าซื้อเองโดยสคริปต์ไม่ได้แนะนำ ต้องบอกให้ครบ:', 'dim'))
        print(ui.c(f'  run.py --took {symbol} --price 1.54 --lots 8 --sl 1.49 '
                   '--tp 1.59 --bucket cheap', 'dim'))
        return 1

    sig = sig or {}
    entry = price if price else float(sig.get('entry') or 0)
    lots = int(lots if lots else (sig.get('lots') or 0))
    sl = float(sl if sl is not None else (sig.get('sl') or 0))
    tp = float(tp if tp is not None else (sig.get('tp') or 0))
    bucket = bucket or sig.get('bucket') or '?'

    if entry <= 0 or lots < 1:
        ui.fail(f'{symbol}: ต้องมีราคาและจำนวน lot — ใส่ --price / --lots')
        return 1
    if sl and sl >= entry:
        ui.fail(f'SL {sl:.2f} ไม่ต่ำกว่าราคาซื้อ {entry:.2f} — ตรวจตัวเลขอีกที')
        return 1

    cost = entry * lots * config.BOARD_LOT
    risk_thb = max(0.0, entry - sl) * lots * config.BOARD_LOT
    journal.record(bucket, {
        'action': 'ENTER', 'symbol': symbol, 'entry': entry, 'lots': lots,
        'cost': cost, 'sl': sl, 'tp': tp, 'risk_thb': risk_thb})

    if sig and (price or lots != int(sig.get('lots') or 0)):
        print(ui.c(f"  (สคริปต์แนะนำ {sig.get('lots')} lot @ "
                   f"{float(sig.get('entry') or 0):.2f} — บันทึกตามที่ซื้อจริง)", 'dim'))

    st = risk.state()
    print()
    print(ui.c(f'  บันทึกแล้ว: ซื้อ {symbol} {lots} lot @ {entry:.2f} '
               f'= {cost:,.0f}฿', 'bold', 'green'))
    print(ui.c(f'  เสี่ยง {risk_thb:,.0f}฿ ถ้าโดน SL {sl:.2f}', 'dim'))
    print(ui.c('  ' + risk.headline(st), 'dim'))
    if st['blocked']:
        print(ui.c(f'  ✋ {st["reason"]} — พอแล้วสำหรับวันนี้', 'bright_red'))
    print()
    return 0


def cmd_close(symbol: str, price: float, lots: int = None) -> int:
    """Close a position and book the result, fees included."""
    symbol = symbol.upper()
    pos = next((p for p in risk.open_positions()
                if str(p.get('symbol', '')).upper() == symbol), None)
    if pos is None:
        ui.fail(f'ไม่มีสถานะเปิดของ {symbol} — ยืนยันตอนซื้อด้วย --took หรือยัง')
        return 1
    if not price or price <= 0:
        ui.fail('ต้องระบุราคาขายด้วย --price')
        return 1

    lots = int(lots) if lots else int(pos.get('lots') or 0)
    if lots > int(pos.get('lots') or 0):
        ui.fail(f"ถือ {symbol} อยู่ {pos.get('lots')} lot ขายมากกว่านั้นไม่ได้")
        return 1
    entry = float(pos.get('entry') or 0)
    units = lots * config.BOARD_LOT
    cost = entry * units
    proceeds = price * units
    fees = sizing.commission(cost) + sizing.commission(proceeds)
    pnl = proceeds - cost - fees

    journal.record(pos.get('bucket', '?'), {
        'action': 'EXIT', 'symbol': symbol, 'entry': entry, 'exit': price,
        'lots': lots, 'cost': cost, 'proceeds': proceeds, 'fees': fees,
        'pnl': pnl})

    st = risk.state()
    tone = 'bright_green' if pnl >= 0 else 'bright_red'
    print()
    print(ui.c(f'  ปิด {symbol} {lots} lot  {entry:.2f} → {price:.2f}   '
               f'{pnl:+,.0f}฿ (หักค่าธรรมเนียม {fees:,.0f}฿ แล้ว)', 'bold', tone))
    print(ui.c('  ' + risk.headline(st), 'dim'))
    if st['blocked']:
        print(ui.c(f'  ✋ {st["reason"]}', 'bright_red'))
    print()
    return 0


def main() -> int:
    global PLAIN
    ap = argparse.ArgumentParser(description='แผนเทรดรายวัน 3 ก้อน: DW HSI / หุ้นไทยถูก / DR')
    ap.add_argument('--bucket', default='all',
                    choices=['all'] + list(config.BUCKET_ORDER))
    ap.add_argument('--no-journal', action='store_true', help='ไม่บันทึกลง journal.jsonl')
    ap.add_argument('--plain', action='store_true', help='ปิดกรอบและแถบกราฟ')
    ap.add_argument('--color', action='store_true',
                    help='บังคับใช้สีแม้ pipe ออกไฟล์ (คู่กับ less -R)')
    ap.add_argument('--html', metavar='FILE',
                    help='สร้างหน้าเว็บแบบเดียวกับที่ deploy แล้วเขียนลงไฟล์')
    ap.add_argument('--took', metavar='SYMBOL',
                    help='ยืนยันว่าซื้อจริงแล้ว — นับเป็น 1 ไม้ของวันนี้')
    ap.add_argument('--close', metavar='SYMBOL', dest='close_sym',
                    help='ปิดสถานะและบันทึกกำไร/ขาดทุน (ใช้คู่กับ --price)')
    ap.add_argument('--price', type=float, help='ราคาที่ซื้อ/ขายได้จริง')
    ap.add_argument('--lots', type=int, help='จำนวน lot ที่ซื้อ/ขายจริง ถ้าไม่เท่าที่แนะนำ')
    ap.add_argument('--sl', type=float, help='จุดตัดขาดทุน (ตัวที่สคริปต์ไม่ได้แนะนำ)')
    ap.add_argument('--tp', type=float, help='เป้าทำกำไร (ตัวที่สคริปต์ไม่ได้แนะนำ)')
    ap.add_argument('--status', action='store_true',
                    help='ดูโควตาความเสี่ยงวันนี้กับสถานะที่ถืออยู่ ไม่ต้องสแกนตลาด')
    ap.add_argument('--review', action='store_true',
                    help='สรุปจาก journal ว่าก้อนไหนทำเงินจริง ก้อนไหนควรตัดทิ้ง')
    ap.add_argument('--force', action='store_true',
                    help='สแกนต่อแม้ชนเบรกเกอร์ประจำวันแล้ว')
    args = ap.parse_args()

    PLAIN = args.plain
    if args.color:
        ui.force_color(True)

    if args.review:
        return cmd_review()
    if args.took:
        return cmd_took(args.took, args.price, args.lots, args.sl, args.tp,
                        args.bucket if args.bucket != 'all' else None)
    if args.close_sym:
        return cmd_close(args.close_sym, args.price, args.lots)

    if args.html:
        from web.page import render
        from web.report import collect
        with open(args.html, 'w', encoding='utf-8') as fh:
            fh.write(render(collect(config.active_buckets(
                None if args.bucket == 'all' else (args.bucket,)))))
        print(f'เขียน {args.html} แล้ว — เปิดด้วยเบราว์เซอร์เพื่อดูหน้าเว็บ')
        return 0

    st = risk.state()
    print()
    header(st)
    show_positions(st)
    if args.status:
        return 0

    # The breaker stops the scan, not just the recommendation. Looking at a
    # screen full of setups you are not allowed to take is how the rule gets
    # broken, so on a day that is already spent there is nothing to look at.
    if st['blocked'] and not args.force:
        lines = big_badge('stop', st['reason'])
        lines += ['', ui.c('  พรุ่งนี้โควตาจะรีเซ็ตเอง ถ้าจะดูตลาดเฉย ๆ ใช้ --force',
                           'yellow')]
        lines += ['', ui.c('  ปิดสถานะที่ค้างอยู่:  python3 run.py --close SYMBOL '
                           '--price 2.15', 'dim')]
        _panel('หยุดเทรดวันนี้', lines, 'bright_red')
        print(ui.c('  ตัวเลขทั้งหมดเป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน\n', 'dim'))
        return 0

    rec = not args.no_journal
    scan = config.active_buckets(
        None if args.bucket == 'all' else (args.bucket,))
    # Asking for a paused bucket by name is answered, not silently ignored.
    if args.bucket != 'all' and not scan:
        ui.fail(f"ก้อน {_BUCKET_LABEL.get(args.bucket, args.bucket)} พักอยู่ "
                '— ตั้งงบใน config.ALLOC ก่อนถึงจะสแกนให้')
    for b in scan:
        if b in config.DW_SERIES:
            show_dw(rec, b)
        elif b == 'cheap':
            show_cheap(rec)
        elif b == 'dr':
            show_dr(rec)
    print(ui.c('  ตัวเลขทั้งหมดเป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน\n', 'dim'))
    return 0


if __name__ == '__main__':
    sys.exit(main())

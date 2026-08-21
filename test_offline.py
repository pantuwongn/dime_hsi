#!/usr/bin/env python3
"""
Offline checks for the parts that decide money.

selftest.py proves the boxes line up, but it needs live feeds and it only
looks at widths. These are the rules that quietly stop being true when a
threshold moves: sizing, the gates, the daily breaker, and the journal
arithmetic. No network, so it runs on a plane and in CI.

    python3 test_offline.py
"""

import os
import sys
import tempfile

os.environ['NO_COLOR'] = '1'
os.environ.setdefault('DIME_JOURNAL', os.path.join(tempfile.mkdtemp(), 'j.jsonl'))

from trader import config, marks, review, risk, session, sizing   # noqa: E402
from trader.buckets import cheap, dw, intraday             # noqa: E402
from trader.feeds import thaidw                            # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f'{name}: ได้ {got!r} ควรเป็น {want!r}')
    print(f"  {'✓' if ok else '✗'} {name}")


# ------------------------------------------------------------------------------
print('sizing — ขนาดไม้คิดจากระยะ SL')

s = sizing.size_by_risk(0.48, 0.42, risk_thb=75.0, cap=1200.0)
check('DW 0.48/SL 0.42 → 12 lot', s['lots'], 12)
check('  เสี่ยงจริง 72฿ ไม่เกินโควตา', s['risk_thb'] <= 75.0, True)
check('  จำกัดด้วยความเสี่ยง', s['capped_by'], 'ความเสี่ยง')

s = sizing.size_by_risk(12.0, 11.7, risk_thb=75.0, cap=1300.0)
check('DR 12.00 แพงจนงบบีบก่อน', s['capped_by'], 'งบ')

check('SL เท่ากับราคาเข้า → 0 lot', sizing.size_by_risk(1.0, 1.0)['lots'], 0)
check('SL เหนือราคาเข้า → 0 lot', sizing.size_by_risk(1.0, 1.2)['lots'], 0)
check('ราคาเป็น NaN → 0 lot', sizing.size_by_risk(float('nan'), 0.5)['lots'], 0)
check('ทุก branch คืน key ครบ',
      set(sizing.size_by_risk(0, 0)) == set(sizing.size_by_risk(2.0, 1.9)), True)

check('ปัด SL ลงช่องราคา', sizing.to_tick(1.874, 'down'), 1.87)
check('ปัด TP ขึ้นช่องราคา', sizing.to_tick(2.171, 'up'), 2.18)
check('ช่องราคา 5-10 บาท = 0.05', sizing.tick(6.0), 0.05)


# ------------------------------------------------------------------------------
print('\ndw — ด่านคัด DW')

SIG = {'close': 25830.0, 'atr': 120.0, 'side': 'C'}


def warrant(sym, bid, ask, sens, lt='29 Sep 26', gear=18.0):
    return {'symbol': sym, 'issuer_code': sym[3:5], 'issuer': 'MACQ', 'side': 'C',
            'strike': 27600.0, 'bid': bid, 'ask': ask, 'gearing': gear,
            'sensitivity': sens, 'theta': 0.9, 'iv': 22.0, 'moneyness_pct': 6.8,
            'last_trade_date': lt, 'dwps': 1.0}


FIXTURE = [
    warrant('HSI28C2610A', 0.20, 0.21, 0.015),                    # ผ่าน
    warrant('HSI18C2609X', 0.03, 0.04, 0.004, gear=40.0),         # spread 25%
    warrant('HSI18C2608Q', 0.50, 0.52, 0.030, '25 Aug 26'),       # theta cliff
    warrant('HSI28C2612Z', 0.60, 0.63, 0.040, 'ไม่รู้'),             # อ่านวันไม่ออก
    warrant('HSI28C2611Y', 14.00, 14.50, 0.900, '27 Nov 26'),     # 1 lot เกินงบ
    warrant('HSI28C2701D', 0.92, 1.00, 0.0387, '28 Jan 27', 10.0),  # เป้าไม่คุ้ม
    warrant('HSI28C2609N', 0.00, 0.05, 0.010),                    # ไม่มี bid
]
# SET50 sits near 1,000 points, not 25,000, so a DW on it moves a lot more
# baht per index point than an HSI one — sensitivity is per 100 index points.
S50_FIXTURE = [
    # issuer 13 — not one of the two that make the HSI market
    {**warrant('S5013C2512A', 0.60, 0.62, 0.60, '26 Dec 26'), 'strike': 1_050.0},
    {**warrant('S5028C2511B', 0.10, 0.13, 0.20, '27 Nov 26'), 'strike': 1_100.0},
]
BOOKS = {'HSI': FIXTURE, 'S50': S50_FIXTURE}
thaidw.warrants = lambda underlying='HSI': BOOKS[underlying]

# ทั้งสองก้อน DW ถูกพักอยู่ (งบ 0) จึงต้องบอกงบตรง ๆ ไม่งั้นไม่มีอะไรให้คัด
DW_BUDGET = 800.0
res = dw.screen_warrants('C', SIG, budget=DW_BUDGET)
check('ผ่านเฉพาะตัวที่เทรดได้จริง',
      [w['symbol'] for w in res['passed']], ['HSI28C2610A'])
why = {r['symbol']: r['reject'] for r in res['rejected']}
check('  ไม่มี bid ถูกตัด', 'bid' in why.get('HSI28C2609N', ''), True)
check('  spread กว้างถูกตัด', 'spread' in why.get('HSI18C2609X', ''), True)
check('  ใกล้หมดอายุถูกตัด', 'theta' in why.get('HSI18C2608Q', ''), True)
check('  อ่านวันหมดอายุไม่ออกถูกตัด (เดิมรอดด่าน)',
      'หมดอายุ' in why.get('HSI28C2612Z', ''), True)
check('  1 lot เกินงบถูกตัด', 'ไม่พอ 1 lot' in why.get('HSI28C2611Y', ''), True)
check('  เป้าไม่คุ้มต้นทุนถูกตัด', 'ค่าเข้าออก' in why.get('HSI28C2701D', ''), True)

plan = res['passed'][0]['plan']
gross = (plan['tp_price'] - plan['entry']) / plan['entry'] * 100.0
check('สุทธิหัก "คอม" อย่างเดียว ไม่หัก spread ซ้ำ',
      round(plan['tp_net_pct'], 2) == round(gross - res['passed'][0]['fee_pct'], 2), True)
check('SL ต่ำกว่าราคาเข้าเสมอ', plan['sl_price'] < plan['entry'], True)

no_atr = dw.plan_prices(res['passed'][0], {'close': 25830.0, 'atr': None})
check('ATR หาย → ถอยไปใช้จุดคุ้มทุน ไม่ใช่ crash', no_atr is not None and
      no_atr['tp_price'] > no_atr['entry'], True)
check('sensitivity 0 → ไม่มีแผน',
      dw.plan_prices({**warrant('X', 0.4, 0.5, 0.0), 'ask': 0.5}, SIG), None)


# ------------------------------------------------------------------------------
print('\ndw — SET50 ใช้เครื่องเดียวกับ HSI คนละชุดข้อมูล')

S50_SIG = {'close': 1_020.0, 'atr': 6.0, 'side': 'C', 'bucket': 's50'}

check('ก้อน s50 ยิงไปที่ underlying ของตัวเอง',
      [w['symbol'] for w in dw.screen_warrants(
          'C', S50_SIG, budget=DW_BUDGET)['passed']],
      ['S5013C2512A'])
check('  ผู้ออกนอกลิสต์ HSI ยังผ่านได้ในก้อน SET50',
      dw.series('s50')['issuers'], None)
check('  แต่ถูกกรองทิ้งในก้อน HSI',
      [w for w in dw.screen_warrants('C', {**SIG, 'bucket': 'dw'},
                                     budget=DW_BUDGET)['passed']
       if w['symbol'].startswith('S50')], [])
check('  แถวที่ผ่านรู้ว่าตัวเองอยู่ก้อนไหน',
      dw.screen_warrants('C', S50_SIG, budget=DW_BUDGET)['passed'][0]['bucket'],
      's50')
check('  ขนาดไม้ไม่เกินงบที่ให้ไป',
      dw.screen_warrants('C', S50_SIG, budget=DW_BUDGET)['passed'][0]['cost']
      <= DW_BUDGET, True)

_asked = {}


def _fake_quote(tickers, columns, market='thailand'):
    _asked['tickers'], _asked['market'] = tickers, market
    row = {'close': 1_020.0, 'change': 0.8, 'ATR|15': 6.0,
           'EMA9|15': 1_015.0, 'EMA21|15': 1_010.0, 'EMA50|15': 1_000.0,
           'high': 1_025.0, 'low': 1_012.0}
    for tf in ('5', '15', '60'):
        row[f'RSI|{tf}'] = 62.0
        row[f'Recommend.All|{tf}'] = 0.9
    return [row]


_real_quote = dw.tv.quote
dw.tv.quote = _fake_quote
s50_sig = dw.index_signal('s50')
dw.tv.quote = _real_quote
check('สัญญาณ SET50 ถามตลาดไทย ไม่ใช่ตลาดโลก',
      (_asked['tickers'], _asked['market']),
      ([config.DW_SERIES['s50']['ticker']], config.DW_SERIES['s50']['market']))
check('  ติดป้ายก้อนและชื่อดัชนีมาด้วย',
      (s50_sig['bucket'], s50_sig['series']), ('s50', 'SET50'))
check('  EMA เรียงขึ้น + คะแนนถึงเกณฑ์ → เข้า call', s50_sig['side'], 'C')

check('SET50 DW เดินตามเวลา SET ไม่ใช่ HKEX',
      (session.BUCKET_MARKET['s50'], session.BUCKET_MARKET['dw']), ('set', 'hkex'))
check('  ถือ DW ข้ามคืนเตือนทุกก้อน DW',
      marks._alert({'bucket': 's50', 'days_held': 1, 'hit_sl': False,
                    'hit_tp': False, 'stale': False, 'now': 0.5}),
      'DW ถือข้ามคืน — เสีย theta ทุกวัน ปิดวันนี้')

LIVE = {'keys': ['HSIc1', 'S50U26'], 'update_time': '10:15',
        'HSIc1': [{'bid': '25,800', 'ask': '25,810'}],
        'S50U26': [{'bid': '1,019.5', 'ask': '1,020.0'}]}
_real_get = thaidw._get
thaidw._get = lambda path: LIVE
check('futures เลือกคีย์ตาม underlying ไม่ใช่ตัวแรกในลิสต์',
      (thaidw.futures('S50')['symbol'], thaidw.futures('HSI')['symbol']),
      ('S50U26', 'HSIc1'))
check('  ไม่มีคีย์ที่ตรง → None ไม่ใช่ดัชนีตัวอื่น', thaidw.futures('XYZ'), None)
thaidw._get = _real_get


# ------------------------------------------------------------------------------
print('\nrisk — เบรกเกอร์รายวัน')

TODAY = risk.now_bkk().isoformat(timespec='seconds')


def row(action, sym, bucket='cheap', **kw):
    return dict(ts=TODAY, bucket=bucket, action=action, symbol=sym, **kw)


sig3 = [row('SIGNAL', 'SIRI')] * 3
check('รันซ้ำ 3 รอบไม่นับเป็นไม้', risk.state(sig3)['trades'], 0)
check('  ยังไม่บล็อก', risk.state(sig3)['blocked'], False)

one = sig3 + [row('ENTER', 'SIRI', entry=2.0, lots=6, cost=1200.0, risk_thb=72.0)]
check('ยืนยันแล้วนับ 1 ไม้', risk.state(one)['trades'], 1)
check('  เงินที่จมถูกหักออกจากก้อน', risk.committed('cheap', one), 1200.0)

two = one + [row('ENTER', 'HSI28C1', bucket='dw', entry=0.48, lots=12,
                 cost=576.0, risk_thb=72.0)]
check('ครบ 2 ไม้ → บล็อก', risk.state(two)['blocked'], True)

big = sig3 + [row('ENTER', 'X', entry=2.0, lots=6, cost=1200.0, risk_thb=210.0)]
check('ไม้เดียวกินโควตาทั้งวัน → บล็อก', risk.state(big)['blocked'], True)

lost = two + [row('EXIT', 'SIRI', exit=1.88, cost=1200.0, fees=4.0, pnl=-76.0)]
check('ปิดแล้วเหลือสถานะเดียว', len(risk.open_positions(lost)), 1)

part = [row('ENTER', 'P', entry=2.0, lots=5, cost=1000.0, sl=1.9, risk_thb=50.0),
        row('EXIT', 'P', exit=2.1, lots=2, cost=400.0, fees=2.0, pnl=18.0)]
held = risk.open_positions(part)
check('ขาย 2 จาก 5 lot → ยังถือ 3 lot', held[0]['lots'], 3)
check('  ทุนที่เหลือคิดตาม 3 lot', held[0]['cost'], 600.0)
check('  ความเสี่ยงลดตามส่วน', round(held[0]['risk_thb'], 6), 30.0)
check('  ไม้ที่ปิดนับแค่ 2 lot', review.closed_trades(part)[0]['lots'], 2)

avg = [row('ENTER', 'Q', entry=2.0, lots=5, cost=1000.0, sl=1.9),
       row('ENTER', 'Q', entry=3.0, lots=5, cost=1500.0, sl=1.9)]
check('ซื้อสองรอบ → รวมเป็นก้อนเดียว', len(risk.open_positions(avg)), 1)
check('  ต้นทุนเฉลี่ย 2.50', risk.open_positions(avg)[0]['entry'], 2.5)
check('ตัวที่เพิ่งโดน SL วันนี้ถูกกัน', risk.stopped_today('cheap', lost), ['SIRI'])
won = two + [row('EXIT', 'SIRI', exit=2.18, cost=1200.0, fees=4.0, pnl=104.0)]
check('  ตัวที่ปิดได้กำไรไม่ถูกกัน', risk.stopped_today('cheap', won), [])


# ------------------------------------------------------------------------------
print('\nbuckets — เงินว่างและตัวที่ห้ามแตะ')


def scan_rows(rows):
    """Stand in for the TradingView scanner."""
    return lambda **kw: rows


CHEAP_ROWS = [{
    '_ticker': 'SET:SIRI', 'name': 'SIRI', 'description': 'Sansiri',
    'close': 2.00, 'change': 1.0, 'Value.Traded': 6e7,
    'relative_volume_10d_calc': 1.4, 'RSI': 60.0, 'MACD.macd': 0.02,
    'MACD.signal': 0.01, 'EMA9': 1.98, 'EMA21': 1.90, 'EMA50': 1.85,
    'ATR': 0.09, 'Perf.W': 3.0, 'Recommend.All': 0.4,
    'High.1M': 2.40, 'Low.1M': 1.70,
}]
cheap.tv.screen = scan_rows(CHEAP_ROWS)

r = cheap.scan(cash=2500.0)
check('หุ้นที่เข้าเกณฑ์ผ่าน', [m['symbol'] for m in r['passed']], ['SIRI'])
check('  ขนาดไม้ไม่เกินโควตาเสี่ยง', r['passed'][0]['risk_thb'] <= config.risk_thb(), True)
check('  TP/SL อยู่บนช่องราคา',
      (r['passed'][0]['plan']['tp'], r['passed'][0]['plan']['sl'])
      == (sizing.to_tick(r['passed'][0]['plan']['tp']),
          sizing.to_tick(r['passed'][0]['plan']['sl'])), True)

r = cheap.scan(cash=2500.0, exclude={'SIRI': 'ถืออยู่แล้ว'})
check('ตัวที่ถืออยู่ไม่ถูกแนะนำซ้ำ', [m['symbol'] for m in r['passed']], [])
check('  และบอกเหตุผลที่ส่งเข้าไป',
      [x['reject'] for x in r['rejected']], ['ถืออยู่แล้ว'])

r = cheap.scan(cash=100.0)
check('เงินว่างไม่พอ 1 lot → ไม่แนะนำ', [m['symbol'] for m in r['passed']], [])
check('  เหตุผลอ้างเงินว่าง ไม่ใช่งบเต็ม',
      'เงินว่าง' in r['rejected'][0]['reject'], True)

# ------------------------------------------------------------------------------
print('\nday — หุ้นซิ่ง: ต้องกำลังวิ่งจริง ไม่ใช่แค่เขียว')


def stock(sym, close, rvol=5.0, value=3e8, chg=6.0, hi=None, lo=None, rsi=62.0):
    """แถวจาก TradingView หนึ่งตัว — ค่าเริ่มต้นคือตัวที่ผ่านทุกด่าน"""
    hi = close if hi is None else hi
    lo = (close * 0.94) if lo is None else lo
    return {'_ticker': f'SET:{sym}', 'name': sym, 'description': f'{sym} pcl',
            'close': close, 'change': chg, 'gap': chg / 2.0, 'high': hi, 'low': lo,
            'Value.Traded': value, 'relative_volume_10d_calc': rvol,
            'RSI': rsi, 'MACD.macd': 0.0, 'MACD.signal': 0.0,
            'EMA9': close * 0.99, 'EMA21': close * 0.98,
            'ATR': close * 0.05, 'Perf.W': 8.0, 'Recommend.All': 0.4}


# ช่องราคา SET เป็นขั้นบันได ราคาที่อยู่เหนือขอบขั้นนิดเดียวจึงแพงต่อช่องที่สุด
# (2.02 เสีย 0.02 = 1.0% ต่อช่อง ส่วน 4.98 เสีย 0.02 = 0.4%) — ด่านนี้คัดตรงนั้น
DAY_ROWS = [
    stock('RUN', 4.98),                             # วิ่ง +6% ยืนบนยอด — ผ่าน
    stock('SLOW', 4.96, chg=1.0),                   # +1% ยังไม่วิ่ง
    stock('BLOWOFF', 4.94, chg=22.0),               # +22% รับของจากคนซื้อก่อน
    stock('QUIET', 4.92, rvol=1.2),                 # ขึ้นแต่ไม่มีคนเข้า
    stock('FADED', 4.90, hi=5.30, lo=4.85),         # ขึ้นแล้วโดนขายลงมา
    stock('COARSE', 2.02),                          # 1 ช่อง = 1% หยาบเกิน
    stock('THIN', 4.88, value=2e7),                 # สภาพคล่องต่ำ (ตกตั้งแต่ฟีด)
]
_asked_filter = {}


def _spy_screen(filters, columns, market='thailand', **kw):
    _asked_filter['f'] = {f['left']: f['right'] for f in filters}
    keep = _asked_filter['f'].get('Value.Traded', 0)
    return [r for r in DAY_ROWS if r['Value.Traded'] > keep]


intraday.tv.screen = _spy_screen
day = intraday.scan('day', cash=config.ALLOC['day'])

check('ยิงหา type=stock ไม่ใช่ dr', _asked_filter['f']['type'], 'stock')
check('  ด่านสภาพคล่องของก้อนซิ่งสูงกว่าก้อนสวิง',
      (_asked_filter['f']['Value.Traded'] > config.CHEAP_MIN_VALUE,
       _asked_filter['f']['Value.Traded']), (True, config.DAY_MIN_VALUE))
check('  เพดานราคาคิดจากเงินที่ซื้อ 1 lot ได้จริง',
      _asked_filter['f']['close'], config.ALLOC['day'] / config.BOARD_LOT)
check('  งบ 0 → ไม่ต้องยิงฟีดเลย',
      intraday.scan('day', cash=0.0)['passed'], [])

check('ผ่านเฉพาะตัวที่วิ่งอยู่จริงและยังถูกไล่ซื้อ',
      [m['symbol'] for m in day['passed']], ['RUN'])
why = {r['symbol']: r['reject'] for r in day['rejected']}
check('  ยังไม่วิ่งถูกตัด', 'ยังไม่วิ่ง' in why.get('SLOW', ''), True)
check('  วิ่งจนสุดแล้วถูกตัด', 'ซื้อก่อน' in why.get('BLOWOFF', ''), True)
check('  ราคาขึ้นแต่ไม่มีวอลุ่มถูกตัด', 'RVOL' in why.get('QUIET', ''), True)
check('  ขึ้นแล้วโดนขายลงมาถูกตัด (ยืนไม่ถึงกรอบวัน)',
      'กรอบวัน' in why.get('FADED', ''), True)
check('  1 ช่องราคาหยาบถูกตัด', '1 ช่องราคา' in why.get('COARSE', ''), True)
check('  สภาพคล่องต่ำไม่ถูกดึงมาตั้งแต่ฟีด', 'THIN' in why, False)

check('ยืนบนยอดกรอบวัน = 1.0 · ครึ่งกรอบ = 0.5',
      (intraday._range_pos({'close': 5.0, 'high': 5.0, 'low': 4.0}),
       intraday._range_pos({'close': 4.5, 'high': 5.0, 'low': 4.0})), (1.0, 0.5))
check('  ฟีดยังไม่มีกรอบวัน → ไม่ตัดทิ้ง',
      intraday._range_pos({'close': 5.0, 'high': None, 'low': None}), None)

hot = intraday._score({'rvol': 8.0, 'change': 9.0, 'range_pos': 1.0,
                       'value_mb': 400.0, 'tick_pct': 0.4, 'rsi': 68.0})
cool = intraday._score({'rvol': 3.1, 'change': 3.2, 'range_pos': 0.65,
                        'value_mb': 160.0, 'tick_pct': 0.8, 'rsi': 60.0})
check('เรียงให้ตัวแรงกว่าขึ้นก่อน', hot > cool, True)

check('  ไม้เดียวไม่เกินงบก้อนและไม่เกินโควตาเสี่ยง',
      (day['passed'][0]['cost'] <= config.ALLOC['day'],
       day['passed'][0]['risk_thb'] <= config.risk_thb()), (True, True))
check('  แถวที่ผ่านรู้ว่าตัวเองอยู่ก้อนไหน', day['passed'][0]['bucket'], 'day')
check('ก้อนซิ่งยึดเวลา SET', session.BUCKET_MARKET['day'], 'set')
check('  ค้างข้ามคืนมีคำเตือน',
      'วันเดียว' in marks._alert({'bucket': 'day', 'days_held': 1, 'hit_sl': False,
                                  'hit_tp': False, 'stale': False, 'now': 5.0}), True)
check('ตัวที่เพิ่งโดน SL วันนี้ถูกกันไว้',
      [m['symbol'] for m in intraday.scan(
          'day', cash=config.ALLOC['day'],
          exclude={'RUN': 'เพิ่งโดน SL'})['passed']], [])


# ------------------------------------------------------------------------------
print('\nsession — รู้ว่าตลาดเปิดอยู่หรือเปล่า')

from datetime import datetime, timedelta, timezone                # noqa: E402
from trader import session                                        # noqa: E402

BKK = timezone(timedelta(hours=7))


def at(text):
    return datetime.strptime(text, '%Y-%m-%d %H:%M').replace(tzinfo=BKK)


check('อังคาร 10:30 เปิดทั้งคู่', session.state(at('2026-08-18 10:30'))['live'], True)
check('อังคาร 09:00 SET ยังไม่เปิด', session.is_open('set', at('2026-08-18 09:00')), False)
check('  แต่ HKEX เปิดแล้ว', session.is_open('hkex', at('2026-08-18 09:00')), True)
check('พักเที่ยง SET 13:00 ปิด', session.is_open('set', at('2026-08-18 13:00')), False)
check('15:30 HKEX ปิดแล้ว', session.is_open('hkex', at('2026-08-18 15:30')), False)
check('สี่ทุ่มไม่ใช่ราคาสด', session.state(at('2026-08-18 22:00'))['live'], False)
check('เสาร์ปิดหมด', session.state(at('2026-08-22 11:00'))['weekend'], True)
check('  และบอกว่าเป็นราคาปิดวันศุกร์',
      'ศุกร์' in session.state(at('2026-08-22 11:00'))['note'], True)
check('ตอนเปิดจริงไม่มีคำเตือนรก',
      session.bucket_note('cheap', session.state(at('2026-08-18 10:30'))), '')
check('ตอนปิดเตือนพร้อมรอบถัดไป',
      '10:15' in session.bucket_note('day', session.state(at('2026-08-18 22:00'))), True)


# ------------------------------------------------------------------------------
print('\nnet — feed พังครั้งเดียวต้องไม่ทำให้ก้อนนั้นหายทั้งก้อน')

import urllib.error                                               # noqa: E402
from trader.feeds import net                                      # noqa: E402


def http(code):
    def raise_it(timeout):
        raise urllib.error.HTTPError('u', code, 'x', {}, None)
    return raise_it


tries = {'n': 0}


def flaky(timeout):
    tries['n'] += 1
    if tries['n'] < 2:
        raise urllib.error.HTTPError('u', 503, 'Busy', {}, None)
    return {'ok': True}


check('503 แล้วลองใหม่จนสำเร็จ', net.fetch(flaky, 'x'), {'ok': True})
check('  ลองไป 2 ครั้ง', tries['n'], 2)

for code, retried in ((403, False), (404, False), (429, True), (502, True)):
    calls = {'n': 0}

    def counted(timeout, c=code, k=calls):
        k['n'] += 1
        raise urllib.error.HTTPError('u', c, 'x', {}, None)

    try:
        net.fetch(counted, 'x')
    except net.FeedError:
        pass
    check(f'  HTTP {code} {"ลองใหม่" if retried else "เลิกทันที"}',
          calls['n'] > 1, retried)

check('ยังโยน FeedError เดิมให้ caller จับได้',
      dw.tv.FeedError is net.FeedError, True)


# ------------------------------------------------------------------------------
print('\nreview — จับคู่ ENTER/EXIT')

rows = [
    row('ENTER', 'A', entry=2.0, lots=6, cost=1200.0),
    row('EXIT', 'A', exit=2.2, cost=1200.0, fees=8.0, pnl=112.0),
    row('ENTER', 'B', bucket='dw', entry=0.5, lots=10, cost=500.0),
    row('EXIT', 'B', bucket='dw', exit=0.44, cost=500.0, fees=4.0, pnl=-64.0),
    row('ENTER', 'C', entry=1.0, lots=5, cost=500.0),      # ยังไม่ปิด
]
s = review.summarise(rows)
check('นับเฉพาะไม้ที่ปิดแล้ว', s['overall']['n'], 2)
check('  แยกตามก้อนถูก', (s['by_bucket']['cheap']['n'], s['by_bucket']['dw']['n']), (1, 1))
check('  สุทธิรวม 48฿', round(s['overall']['net']), 48)
check('  ตัวอย่างน้อยเกินสรุป', 'ยังน้อยเกินสรุป' in s['overall']['verdict'], True)

many = []
for i in range(12):
    many += [row('ENTER', f'S{i}', entry=2.0, lots=6, cost=1200.0),
             row('EXIT', f'S{i}', exit=1.9, cost=1200.0, fees=8.0, pnl=-68.0)]
check('พอครบตัวอย่าง กล้าบอกให้ตัดทิ้ง',
      'ตัดก้อนนี้ทิ้ง' in review.summarise(many)['by_bucket']['cheap']['verdict'], True)

old = [row('ENTER', 'BIDU01', bucket='dr', entry=8.85, lots=1, cost=885.0),
       row('EXIT', 'BIDU01', bucket='dr', exit=9.10, lots=1, cost=885.0,
           fees=3.0, pnl=22.0)]
retired = review.summarise(old)
check('ก้อนที่ถูกตัดออกไปแล้ว ยังอยู่ในตารางผลงาน', 'dr' in retired['by_bucket'], True)
check('  และตัวเลขไม่หายไปจากยอดรวม', round(retired['overall']['net']), 22)


# ------------------------------------------------------------------------------
print('\nงบ — ก้อนที่พักต้องไม่ถูกสแกน')

check('ALLOC รวมไม่เกินทุน', sum(config.ALLOC.values()) <= config.BUDGET_TOTAL, True)
check('ก้อนที่มีงบเท่านั้นที่ทำงาน', config.active_buckets(),
      tuple(b for b in config.BUCKET_ORDER if config.ALLOC[b] > 0))
check('  ก้อน DW ที่พักไว้ ไม่ถูกสแกน', config.active_buckets(('dw', 's50')), ())
_saved = dict(config.ALLOC)
config.ALLOC.update({k: 0.0 for k in config.ALLOC})
check('  ก้อนงบ 0 ถูกตัดออก แม้ขอมาตรง ๆ', config.active_buckets(('cheap',)), ())
config.ALLOC.update({'cheap': 1_000.0, 'day': 500.0})
check('  ปิด/เปิดก้อนได้จาก ALLOC อย่างเดียว', config.active_buckets(),
      ('day', 'cheap'))
config.ALLOC.clear()
config.ALLOC.update(_saved)


# ------------------------------------------------------------------------------
print()
if FAILED:
    for f in FAILED:
        print(f'  ✗ {f}')
    print(f'\nไม่ผ่าน {len(FAILED)} ข้อ')
    sys.exit(1)
print('ผ่านทั้งหมด')

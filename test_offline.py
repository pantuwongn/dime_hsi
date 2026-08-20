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

from trader import config, review, risk, sizing            # noqa: E402
from trader.buckets import cheap, dr, dw_hsi               # noqa: E402

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
dw_hsi.thaidw.hsi_warrants = lambda: FIXTURE

res = dw_hsi.screen_warrants('C', SIG)
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

no_atr = dw_hsi.plan_prices(res['passed'][0], {'close': 25830.0, 'atr': None})
check('ATR หาย → ถอยไปใช้จุดคุ้มทุน ไม่ใช่ crash', no_atr is not None and
      no_atr['tp_price'] > no_atr['entry'], True)
check('sensitivity 0 → ไม่มีแผน',
      dw_hsi.plan_prices({**warrant('X', 0.4, 0.5, 0.0), 'ask': 0.5}, SIG), None)


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

DR_ROWS = [{
    '_ticker': 'SET:BIDU01', 'name': 'BIDU01', 'description': 'Baidu Shs',
    'close': 8.85, 'change': 0.6, 'gap': 0.6, 'Value.Traded': 2e7,
    'relative_volume_10d_calc': 5.4, 'RSI': 55.0, 'MACD.macd': 0.0,
    'MACD.signal': 0.0, 'EMA9': 8.8, 'EMA21': 8.6, 'ATR': 0.35,
    'Perf.W': 1.0, 'Recommend.All': 0.3,
}, {
    '_ticker': 'SET:TTB.R', 'name': 'TTB.R', 'description': 'NVDR line',
    'close': 1.80, 'change': 0.0, 'gap': 0.0, 'Value.Traded': 9e7,
    'relative_volume_10d_calc': 1.0, 'RSI': 50.0, 'ATR': 0.03,
    'Perf.W': 0.0, 'Recommend.All': 0.1,
}]
dr.tv.screen = scan_rows(DR_ROWS)

r = dr.scan(cash=1300.0)
check('NVDR ถูกกรองออกจากจักรวาล DR', r['nvdr_filtered'], 1)
check('  เหลือ DR จริง', r['universe'], 1)
check('DR ที่เพิ่งโดน SL วันนี้ถูกกัน',
      [m['symbol'] for m in dr.scan(
          cash=1300.0, exclude={'BIDU01': 'เพิ่งโดน SL'})['passed']], [])


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


# ------------------------------------------------------------------------------
print()
if FAILED:
    for f in FAILED:
        print(f'  ✗ {f}')
    print(f'\nไม่ผ่าน {len(FAILED)} ข้อ')
    sys.exit(1)
print('ผ่านทั้งหมด')

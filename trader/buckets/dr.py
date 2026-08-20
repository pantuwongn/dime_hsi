"""
Bucket C — Thai Depositary Receipts. Day trade / overnight-gap trade.

A DR tracks a foreign share that trades while SET is shut, so by the time
you can act, the news is already in the price: the opening gap IS the move.
That makes the useful question 'is the gap still being bought at 10:15, or
has it already been sold into?' rather than anything a 5-minute chart says.

Two traps this bucket has to handle:
  * SET tags NVDRs as type 'dr' too. Of 1,353 rows, only ~115 are real DRs;
    the rest are the '.R' shadow lines of ordinary Thai stocks.
  * DR symbols go stale fast. Issuers delist and relist under new codes, so
    the universe is always fetched live and never hardcoded.
"""

from .. import config, sizing
from ..feeds import tv
from ..feeds.tv import num

_COLS = [
    'name', 'description', 'close', 'change', 'gap',
    'Value.Traded', 'relative_volume_10d_calc',
    'RSI', 'MACD.macd', 'MACD.signal', 'EMA9', 'EMA21', 'ATR',
    'Perf.W', 'Recommend.All',
]


def scan(budget: float = None) -> dict:
    budget = config.ALLOC['dr'] if budget is None else budget

    rows = tv.screen(
        filters=[
            {'left': 'type', 'operation': 'equal', 'right': 'dr'},
            {'left': 'Value.Traded', 'operation': 'greater', 'right': config.DR_MIN_VALUE},
            {'left': 'close', 'operation': 'less', 'right': config.DR_MAX_PRICE},
        ],
        columns=_COLS, market='thailand', limit=300,
    )

    passed, rejected, nvdr = [], [], 0
    for r in rows:
        sym = r.get('name') or r['_ticker'].split(':')[-1]
        if sym.endswith('.R'):          # NVDR line of a Thai stock, not a DR
            nvdr += 1
            continue

        close = num(r, 'close')
        if close is None:
            continue

        m = {
            'symbol': sym,
            'name': (r.get('description') or '').split(' Units')[0].split(' Shs')[0][:30],
            'close': close,
            'change': num(r, 'change'),
            'gap': num(r, 'gap'),
            'value_mb': (num(r, 'Value.Traded') or 0) / 1e6,
            'rvol': num(r, 'relative_volume_10d_calc'),
            'rsi': num(r, 'RSI'),
            'atr': num(r, 'ATR'),
            'perf_w': num(r, 'Perf.W'),
            'rec': num(r, 'Recommend.All'),
            'issuer': ''.join(ch for ch in sym[-2:] if ch.isdigit()),
        }
        m['tick_pct'] = sizing.tick(close) / close * 100.0
        m.update(sizing.size(close, budget))

        reason = None
        if m['rsi'] is None:
            reason = 'อินดิเคเตอร์ไม่ครบ — DR เพิ่งเข้าเทรด'
        elif m['lots'] < 1:
            reason = f'งบ {budget:,.0f}฿ ไม่พอ 1 lot (ต้อง {close * config.BOARD_LOT:,.0f}฿)'
        elif m['tick_pct'] > config.DR_MAX_TICK_PCT:
            reason = f"1 ช่องราคา = {m['tick_pct']:.1f}% — หยาบเกินเดย์เทรด"
        elif m['gap'] is not None and m['gap'] > config.DR_MAX_GAP:
            reason = f"gap +{m['gap']:.0f}% — ไล่ราคาที่วิ่งไปแล้ว"
        elif m['change'] is not None and m['gap'] is not None and m['gap'] > 0 > m['change']:
            reason = 'เปิด gap ขึ้นแล้วโดนขายทิ้ง — gap fade'

        if reason:
            m['reject'] = reason
            rejected.append(m)
        else:
            m['score'] = _score(m)
            m['plan'] = _plan(m)
            passed.append(m)

    passed.sort(key=lambda x: -x['score'])
    passed, dupes = _dedupe_underlying(passed)
    return {'passed': passed, 'rejected': rejected, 'dupes': dupes,
            'universe': len(rows) - nvdr, 'nvdr_filtered': nvdr}


def _dedupe_underlying(ranked: list) -> tuple:
    """
    The same foreign share is often listed by several issuers — MRVL06 and
    MRVL80 are both Marvell. Recommending both is one position pretending to
    be two, so keep the best-scoring line per underlying and note the rest.
    """
    seen, keep, dropped = {}, [], []
    for m in ranked:
        base = m['symbol'][:-len(m['issuer'])] if m['issuer'] else m['symbol']
        if base in seen:
            dropped.append((m['symbol'], seen[base]))
            continue
        seen[base] = m['symbol']
        keep.append(m)
    return keep, dropped


def _score(m: dict) -> float:
    s = 0.0
    if m['rec'] is not None:
        s += m['rec'] * 30.0
    if m['gap'] is not None and m['change'] is not None:
        # Gap that is still being bought after the open, not faded.
        s += 12.0 if (m['gap'] > 0 and m['change'] >= m['gap']) else -6.0
    if m['rvol'] is not None:
        s += min(m['rvol'], 4.0) * 10.0
    s -= m['tick_pct'] * 12.0           # granularity is a real, recurring cost
    if m['rsi'] is not None:
        s -= abs(m['rsi'] - 58.0) * 0.35
    return s


def _plan(m: dict) -> dict:
    atr = m['atr'] or (m['close'] * 0.03)
    tick = sizing.tick(m['close'])
    tp = m['close'] + max(atr * 0.8, tick * 3)
    sl = max(tick, m['close'] - max(atr * 0.6, tick * 2))
    risk, reward = max(m['close'] - sl, tick), tp - m['close']
    return {
        'entry': round(m['close'], 2),
        'tp': round(tp, 2),
        'sl': round(sl, 2),
        'tp_pct': reward / m['close'] * 100.0,
        'sl_pct': -risk / m['close'] * 100.0,
        'rr': reward / risk,
        'max_loss_thb': m['cost'] * risk / m['close'],
    }

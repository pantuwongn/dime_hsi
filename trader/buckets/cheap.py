"""
Bucket B — SET stocks under 3 THB, swing held a few days.

The filter matters more than the signal here. There are ~430 SET stocks
under 3 THB and almost all of them are untradeable: a stock at 0.02 THB moves
one tick and you are down 50%, and a stock turning over 2 MB a day cannot be
exited in size that matters even on a 5,000 THB account.

So: liquidity gate first, momentum second.
"""

from .. import config, sizing
from ..feeds import tv
from ..feeds.tv import num

_COLS = [
    'name', 'description', 'close', 'change', 'gap',
    'Value.Traded', 'relative_volume_10d_calc', 'average_volume_10d_calc',
    'RSI', 'MACD.macd', 'MACD.signal',
    'EMA9', 'EMA21', 'EMA50', 'ATR',
    'Perf.W', 'Recommend.All', 'High.1M', 'Low.1M',
]


def scan(budget: float = None) -> dict:
    budget = config.ALLOC['cheap'] if budget is None else budget

    rows = tv.screen(
        filters=[
            {'left': 'close', 'operation': 'less', 'right': config.CHEAP_MAX_PRICE},
            {'left': 'type', 'operation': 'equal', 'right': 'stock'},
            {'left': 'Value.Traded', 'operation': 'greater', 'right': config.CHEAP_MIN_VALUE},
        ],
        columns=_COLS, market='thailand', limit=100,
    )

    passed, rejected = [], []
    for r in rows:
        close = num(r, 'close')
        if close is None:
            continue

        m = {
            'symbol': r.get('name') or r['_ticker'].split(':')[-1],
            'name': (r.get('description') or '')[:34],
            'close': close,
            'change': num(r, 'change'),
            'value_mb': (num(r, 'Value.Traded') or 0) / 1e6,
            'rvol': num(r, 'relative_volume_10d_calc'),
            'rsi': num(r, 'RSI'),
            'macd_diff': _macd_diff(r),
            'ema9': num(r, 'EMA9'), 'ema21': num(r, 'EMA21'), 'ema50': num(r, 'EMA50'),
            'atr': num(r, 'ATR'),
            'perf_w': num(r, 'Perf.W'),
            'rec': num(r, 'Recommend.All'),
            'high_1m': num(r, 'High.1M'), 'low_1m': num(r, 'Low.1M'),
        }
        m.update(sizing.size(close, budget / 2))   # plan for up to 2 concurrent names

        reason = None
        if m['rsi'] is None or m['ema21'] is None:
            reason = 'อินดิเคเตอร์ไม่ครบ — หุ้นใหม่หรือถูกพักการซื้อขาย'
        elif m['rvol'] is not None and m['rvol'] < config.CHEAP_MIN_RVOL:
            reason = f"RVOL {m['rvol']:.2f} — ไม่มีแรงซื้อผิดปกติ"
        elif close < m['ema21']:
            reason = 'ต่ำกว่า EMA21 — ยังไม่กลับเป็นขาขึ้น'
        elif m['rsi'] > 78:
            reason = f"RSI {m['rsi']:.0f} — ร้อนเกินไล่"
        elif m['lots'] < 1:
            reason = 'งบไม่พอ 1 lot'

        if not reason:
            m['plan'] = _plan(m)
            if m['plan']['rr'] < config.CHEAP_MIN_RR:
                reason = (f"risk/reward {m['plan']['rr']:.1f} — "
                          f"เสี่ยงมากกว่าที่ได้")

        if reason:
            m['reject'] = reason
            rejected.append(m)
        else:
            m['score'] = _score(m)
            passed.append(m)

    passed.sort(key=lambda x: -x['score'])
    return {'passed': passed, 'rejected': rejected, 'universe': len(rows)}


def _macd_diff(r):
    macd, sig = num(r, 'MACD.macd'), num(r, 'MACD.signal')
    if macd is None or sig is None:
        return None
    return macd - sig


def _score(m: dict) -> float:
    s = 0.0
    if m['rec'] is not None:
        s += m['rec'] * 40.0
    if m['rvol'] is not None:
        s += min(m['rvol'], 4.0) * 8.0
    if m['macd_diff'] is not None:
        s += 15.0 if m['macd_diff'] > 0 else -15.0
    if m['ema50'] and m['close'] > m['ema50']:
        s += 10.0
    if m['rsi'] is not None:
        s -= abs(m['rsi'] - 60.0) * 0.4          # sweet spot: trending, not blown off
    if m['perf_w'] is not None:
        s -= max(0.0, m['perf_w'] - 15.0) * 0.6  # already ran 15% this week
    return s


def _plan(m: dict) -> dict:
    """
    Stop first, target second.

    The stop is ATR-based and EMA21 may only *tighten* it, never widen it —
    an EMA sitting 12% below the price is not a stop, it is a hope. The target
    then has to clear that risk by 1.8x or the trade is not worth taking, and
    the 1-month high only caps the target when it is genuinely overhead
    resistance rather than the level price just broke out through.
    """
    atr = m['atr'] or (m['close'] * 0.03)

    sl = m['close'] - atr * 1.3
    if m['ema21'] and m['ema21'] * 0.985 > sl:
        sl = m['ema21'] * 0.985
    sl = max(0.01, sl)

    risk = max(m['close'] - sl, 0.01)
    tp = m['close'] + max(atr * 2.0, risk * 1.8)
    if m['high_1m'] and m['high_1m'] > m['close'] * 1.02:
        tp = min(tp, m['high_1m'])

    reward = tp - m['close']
    return {
        'entry': round(m['close'], 2),
        'tp': round(tp, 2),
        'sl': round(sl, 2),
        'tp_pct': reward / m['close'] * 100.0,
        'sl_pct': -risk / m['close'] * 100.0,
        'rr': reward / risk,
        'hold_days': config.CHEAP_HOLD_DAYS,
        'max_loss_thb': m['cost'] * risk / m['close'],
    }

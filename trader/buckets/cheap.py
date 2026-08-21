"""
Bucket B — SET stocks under 3 THB, swing held a few days.

The filter matters more than the signal here. There are ~430 SET stocks
under 3 THB and almost all of them are untradeable: a stock at 0.02 THB moves
one tick and you are down 50%, and a stock turning over 2 MB a day cannot be
exited in size that matters even on a 3,000 THB account.

So: liquidity gate first, momentum second, and the stop before the size —
the allocation is a ceiling, not an amount to spend.
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

# Two concurrent names at most, so the per-name ceiling is half the bucket.
_MAX_NAMES = 2


def scan(budget: float = None, risk_thb: float = None, cash: float = None,
         exclude=()) -> dict:
    """
    `cash` is what is actually free after open positions — a five-day hold
    means that on day two the money is still committed, and sizing against the
    full allocation would be spending it twice.
    """
    budget = config.ALLOC['cheap'] if budget is None else budget
    risk_thb = config.risk_thb() if risk_thb is None else risk_thb
    cash = budget if cash is None else max(0.0, min(cash, budget))
    cap = cash / _MAX_NAMES
    # Either a plain list of symbols or {symbol: why} — a name held and a
    # name just stopped out are both untouchable, for different reasons.
    exclude = {str(k).upper(): (exclude[k] if isinstance(exclude, dict)
                                else 'ถืออยู่แล้ว — เงินก้อนนี้ยังไม่ว่าง')
               for k in exclude}

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
            'lots': 0, 'cost': 0.0, 'risk_thb': 0.0,
        }

        # Gates that need no plan first, so the plan is only built for names
        # that could actually be bought.
        reason = None
        if m['symbol'].upper() in exclude:
            reason = exclude[m['symbol'].upper()]
        elif m['rsi'] is None or m['ema21'] is None:
            reason = 'อินดิเคเตอร์ไม่ครบ — หุ้นใหม่หรือถูกพักการซื้อขาย'
        elif m['rvol'] is not None and m['rvol'] < config.CHEAP_MIN_RVOL:
            reason = f"RVOL {m['rvol']:.2f} — ไม่มีแรงซื้อผิดปกติ"
        elif close < m['ema21']:
            reason = 'ต่ำกว่า EMA21 — ยังไม่กลับเป็นขาขึ้น'
        elif m['rsi'] > 78:
            reason = f"RSI {m['rsi']:.0f} — ร้อนเกินไล่"

        if not reason:
            plan = _plan_prices(m)
            if plan['rr'] < config.CHEAP_MIN_RR:
                reason = f"risk/reward {plan['rr']:.1f} — เสี่ยงมากกว่าที่ได้"
            else:
                m.update(sizing.size_by_risk(close, plan['sl'], risk_thb, cap=cap))
                cost = _cost_pct(m)
                if m['lots'] < 1:
                    reason = _no_lot_reason(m, plan, risk_thb, cap)
                elif plan['tp_pct'] < cost * config.MIN_EDGE_MULTIPLE:
                    reason = (f"เป้า +{plan['tp_pct']:.1f}% แต่ค่าเข้าออก {cost:.2f}% — "
                              f"ต้องได้อย่างน้อย {cost * config.MIN_EDGE_MULTIPLE:.1f}%")
                else:
                    plan['max_loss_thb'] = m['risk_thb']
                    plan['risk_pct_account'] = m['risk_pct']
                    m['plan'] = plan

        if reason:
            m['reject'] = reason
            rejected.append(m)
        else:
            m['score'] = _score(m)
            passed.append(m)

    passed.sort(key=lambda x: -x['score'])
    return {'passed': passed, 'rejected': rejected, 'universe': len(rows),
            'cash': cash, 'max_names': _MAX_NAMES}


def _cost_pct(m: dict) -> float:
    """Round-trip commission. Held for days, so one tick of slip is noise."""
    fee = m.get('fee_pct')
    return 0.0 if fee is None or fee != fee else fee


def _no_lot_reason(m: dict, plan: dict, risk_thb: float, cap: float) -> str:
    per_lot_cost = m['close'] * config.BOARD_LOT
    per_lot_risk = (m['close'] - plan['sl']) * config.BOARD_LOT
    if per_lot_cost > cap:
        return f"เงินว่าง {cap:,.0f}฿ ไม่พอ 1 lot (ต้อง {per_lot_cost:,.0f}฿)"
    return f"1 lot เสี่ยง {per_lot_risk:,.0f}฿ — เกินโควตา {risk_thb:,.0f}฿/ไม้"


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


def _plan_prices(m: dict) -> dict:
    """
    Stop first, target second, both snapped onto the SET tick grid so they can
    be typed into an order slip unchanged.

    The stop is ATR-based and EMA21 may only *tighten* it, never widen it — an
    EMA sitting 12% below the price is not a stop, it is a hope. The target
    then has to clear that risk by CHEAP_MIN_RR or the trade is not worth
    taking, and the 1-month high only caps the target when it is genuinely
    overhead resistance rather than the level price just broke out through.
    """
    atr = m['atr'] or (m['close'] * 0.03)

    sl = m['close'] - atr * 1.3
    if m['ema21'] and m['ema21'] * 0.985 > sl:
        sl = m['ema21'] * 0.985
    sl = max(0.01, sizing.to_tick(sl, 'down'))

    risk = max(m['close'] - sl, sizing.tick(m['close']))
    tp = m['close'] + max(atr * 2.0, risk * config.CHEAP_MIN_RR)
    if m['high_1m'] and m['high_1m'] > m['close'] * 1.02:
        tp = min(tp, m['high_1m'])
    tp = sizing.to_tick(tp, 'up')

    reward = tp - m['close']
    return {
        'entry': round(m['close'], 2),
        'tp': tp,
        'sl': sl,
        'tp_pct': reward / m['close'] * 100.0,
        'sl_pct': -risk / m['close'] * 100.0,
        'rr': reward / risk,
        'hold_days': config.CHEAP_HOLD_DAYS,
        'max_loss_thb': 0.0,
        'risk_pct_account': 0.0,
    }

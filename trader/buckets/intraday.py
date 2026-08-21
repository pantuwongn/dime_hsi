"""
The intraday engine — bucket D, SET stocks bought and sold inside one session.

The screen has one question to answer: is this still being bought right now,
and is what it is reaching for bigger than one tick plus commission by enough
to be worth the ticket? Momentum is the easy half; the gates that cost money
are liquidity and the tick grid.

Two things this has to get right:
  * A board lot is 100 units, so the money in the bucket — not the price
    ceiling in config — is what really decides how expensive a name may be.
    The screen is capped at what one lot can buy, and says so, rather than
    listing names and rejecting them one at a time.
  * SET's tick grid is a staircase, so a stock just above a step pays the most
    per tick: 2.02 THB moves 0.02 (1.0%) while 4.98 THB moves the same 0.02
    (0.4%). The tick gate is what keeps the cheap-looking, expensive-to-trade
    names out.

It stays keyed by config.INTRADAY_SERIES: a second intraday universe (Thai DR
was one until the account got too small for a 100-unit lot of it) is an entry
in that table, not a second scanner to keep in sync.
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


def series(key: str = 'day') -> dict:
    """The config entry for one intraday series, by bucket key."""
    try:
        return config.INTRADAY_SERIES[key]
    except KeyError:
        raise KeyError(f"ไม่รู้จักก้อน intraday {key!r} — "
                       f"มีแค่ {', '.join(config.INTRADAY_SERIES)}")


def scan(key: str = 'day', budget: float = None, risk_thb: float = None,
         cash: float = None, exclude=()) -> dict:
    sr = series(key)
    budget = config.ALLOC[key] if budget is None else budget
    risk_thb = config.risk_thb() if risk_thb is None else risk_thb
    cap = budget if cash is None else max(0.0, min(cash, budget))
    # What one board lot may cost is the real price ceiling. Screening above it
    # only produces rows that exist to be rejected.
    price_cap = min(sr['max_price'], cap / config.BOARD_LOT)
    # Either a plain list of symbols or {symbol: why} — a name held and a
    # name just stopped out are both untouchable, for different reasons.
    exclude = {str(k).upper(): (exclude[k] if isinstance(exclude, dict)
                                else 'ถืออยู่แล้ว — เงินก้อนนี้ยังไม่ว่าง')
               for k in exclude}

    empty = {'passed': [], 'rejected': [], 'universe': 0, 'cash': cap,
             'price_cap': price_cap, 'series': sr['name']}
    if price_cap <= 0:
        return empty

    rows = tv.screen(
        filters=[
            {'left': 'type', 'operation': 'equal', 'right': sr['tv_type']},
            {'left': 'Value.Traded', 'operation': 'greater',
             'right': sr['min_value']},
            {'left': 'close', 'operation': 'less', 'right': price_cap},
        ],
        columns=_COLS, market='thailand', limit=300,
    )

    passed, rejected = [], []
    for r in rows:
        sym = r.get('name') or r['_ticker'].split(':')[-1]
        close = num(r, 'close')
        if close is None:
            continue

        m = {
            'symbol': sym,
            'bucket': key,
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
            'lots': 0, 'cost': 0.0, 'risk_thb': 0.0,
        }
        m['tick_pct'] = sizing.tick(close) / close * 100.0

        reason = None
        if m['symbol'].upper() in exclude:
            reason = exclude[m['symbol'].upper()]
        elif m['rsi'] is None:
            reason = 'อินดิเคเตอร์ไม่ครบ — เพิ่งเข้าเทรด'
        elif m['tick_pct'] > sr['max_tick_pct']:
            reason = f"1 ช่องราคา = {m['tick_pct']:.1f}% — หยาบเกินเดย์เทรด"
        elif sr['min_rvol'] and (m['rvol'] or 0) < sr['min_rvol']:
            reason = (f"RVOL {m['rvol'] or 0:.1f} — วันนี้ไม่ได้คึกกว่าปกติ "
                      f"(ต้อง {sr['min_rvol']:.1f})")
        elif m['gap'] is not None and m['gap'] > sr['max_gap']:
            reason = f"gap +{m['gap']:.0f}% — ไล่ราคาที่วิ่งไปแล้ว"
        elif m['change'] is not None and m['gap'] is not None and m['gap'] > 0 > m['change']:
            reason = 'เปิด gap ขึ้นแล้วโดนขายทิ้ง — gap fade'

        if not reason:
            plan = _plan_prices(m)
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
    return {**empty, 'passed': passed, 'rejected': rejected,
            'universe': len(rows)}


def _cost_pct(m: dict) -> float:
    """Commission plus one tick: in and out inside a session, the grid is paid."""
    fee = m.get('fee_pct')
    fee = 0.0 if fee is None or fee != fee else fee
    return fee + m['tick_pct']


def _no_lot_reason(m: dict, plan: dict, risk_thb: float, cap: float) -> str:
    per_lot_cost = m['close'] * config.BOARD_LOT
    per_lot_risk = (m['close'] - plan['sl']) * config.BOARD_LOT
    if per_lot_cost > cap:
        return f"เงินว่าง {cap:,.0f}฿ ไม่พอ 1 lot (ต้อง {per_lot_cost:,.0f}฿)"
    return f"1 lot เสี่ยง {per_lot_risk:,.0f}฿ — เกินโควตา {risk_thb:,.0f}฿/ไม้"


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


def _plan_prices(m: dict) -> dict:
    """Intraday levels, snapped onto the tick grid so they are placeable."""
    atr = m['atr'] or (m['close'] * 0.03)
    t = sizing.tick(m['close'])
    tp = sizing.to_tick(m['close'] + max(atr * 0.8, t * 3), 'up')
    sl = max(t, sizing.to_tick(m['close'] - max(atr * 0.6, t * 2), 'down'))
    risk, reward = max(m['close'] - sl, t), tp - m['close']
    return {
        'entry': round(m['close'], 2),
        'tp': tp,
        'sl': sl,
        'tp_pct': reward / m['close'] * 100.0,
        'sl_pct': -risk / m['close'] * 100.0,
        'rr': reward / risk,
        'max_loss_thb': 0.0,
        'risk_pct_account': 0.0,
    }

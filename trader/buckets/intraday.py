"""
The intraday engine — bucket A, SET stocks bought and sold inside one session.

It looks for what is running today, which is a different question from what
looks cheap: a stock that has not moved in a month can stay that way for
another month, and the account cannot afford to find out. So the screen wants
a move already under way, real volume behind it, and a price still sitting
near the top of its own day — then asks whether what is left of the move is
bigger than one tick plus commission by enough to be worth the ticket.

Where in today's range the price sits is the gate that does the most work.
The same +6% day, closing at the high or closing at the low, is two completely
different trades: one is still being bought, the other is being handed to you
by whoever bought it first.

Two more things this has to get right:
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
    'name', 'description', 'close', 'change', 'gap', 'high', 'low',
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
            'high': num(r, 'high'),
            'low': num(r, 'low'),
            'value_mb': (num(r, 'Value.Traded') or 0) / 1e6,
            'rvol': num(r, 'relative_volume_10d_calc'),
            'rsi': num(r, 'RSI'),
            'atr': num(r, 'ATR'),
            'perf_w': num(r, 'Perf.W'),
            'rec': num(r, 'Recommend.All'),
            'lots': 0, 'cost': 0.0, 'risk_thb': 0.0,
        }
        m['tick_pct'] = sizing.tick(close) / close * 100.0
        m['range_pos'] = _range_pos(m)

        chg = m['change'] if m['change'] is not None else 0.0
        reason = None
        if m['symbol'].upper() in exclude:
            reason = exclude[m['symbol'].upper()]
        elif m['rsi'] is None:
            reason = 'อินดิเคเตอร์ไม่ครบ — เพิ่งเข้าเทรด'
        elif m['tick_pct'] > sr['max_tick_pct']:
            reason = f"1 ช่องราคา = {m['tick_pct']:.1f}% — หยาบเกินเดย์เทรด"
        elif chg < sr['min_change']:
            reason = (f"วันนี้ {chg:+.1f}% — ยังไม่วิ่ง "
                      f"(ต้อง +{sr['min_change']:.0f}% ขึ้นไป)")
        elif chg > sr['max_change']:
            reason = f"วันนี้ {chg:+.0f}% แล้ว — เข้าตอนนี้คือรับของจากคนที่ซื้อก่อน"
        elif (m['rvol'] or 0) < sr['min_rvol']:
            reason = (f"RVOL {m['rvol'] or 0:.1f} — ราคาขึ้นแต่คนไม่ได้เข้า "
                      f"(ต้อง {sr['min_rvol']:.1f})")
        elif m['range_pos'] is not None and m['range_pos'] < sr['min_range_pos']:
            # Up on the day but sitting near the low of it: the buying that
            # made the move has already stopped, and the exit is someone else's.
            reason = (f"อยู่ที่ {m['range_pos'] * 100:.0f}% ของกรอบวัน — "
                      'ขึ้นแล้วโดนขายลงมา ไม่ใช่กำลังถูกไล่ซื้อ')

        if not reason:
            plan = _plan_prices(m, sr)
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


def _range_pos(m: dict):
    """Where the price sits between today's low and high, 0..1.

    None when the feed has no range yet — the first minutes of a session, or a
    stock that has not traded. A missing number is not a reason to reject.
    """
    hi, lo, close = m.get('high'), m.get('low'), m['close']
    if hi is None or lo is None or hi <= lo:
        return None
    return max(0.0, min(1.0, (close - lo) / (hi - lo)))


def _score(m: dict) -> float:
    """
    Rank by how hard it is running, discounted by what it costs to ride.

    Volume is the leading term because price without volume is one buyer, and
    one buyer is who you sell to. The tick charge is subtracted the same way it
    is paid: on the way in and on the way out.
    """
    s = 0.0
    if m['rvol'] is not None:
        s += min(m['rvol'], 8.0) * 12.0
    if m['change'] is not None:
        s += min(m['change'], 12.0) * 3.0
    if m['range_pos'] is not None:
        s += m['range_pos'] * 25.0      # still at the high beats fading
    if m['value_mb']:
        # Getting out matters as much as getting in, but with a flat ceiling:
        # past a few hundred million a day, more does not help this size.
        s += min(m['value_mb'] / 100.0, 5.0) * 4.0
    s -= m['tick_pct'] * 20.0
    if m['rsi'] is not None and m['rsi'] > 85:
        s -= (m['rsi'] - 85) * 1.5      # vertical and out of buyers
    return s


def _plan_prices(m: dict, sr: dict = None) -> dict:
    """Intraday levels, snapped onto the tick grid so they are placeable."""
    sr = sr or series()
    atr = m['atr'] or (m['close'] * 0.03)
    t = sizing.tick(m['close'])
    tp = sizing.to_tick(m['close'] + max(atr * sr['tp_atr'], t * 3), 'up')
    sl = max(t, sizing.to_tick(m['close'] - max(atr * sr['sl_atr'], t * 2), 'down'))
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

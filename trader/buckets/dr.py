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


def scan(budget: float = None, risk_thb: float = None, cash: float = None,
         exclude=()) -> dict:
    budget = config.ALLOC['dr'] if budget is None else budget
    risk_thb = config.risk_thb() if risk_thb is None else risk_thb
    cap = budget if cash is None else max(0.0, min(cash, budget))
    # Either a plain list of symbols or {symbol: why} — a name held and a
    # name just stopped out are both untouchable, for different reasons.
    exclude = {str(k).upper(): (exclude[k] if isinstance(exclude, dict)
                                else 'ถืออยู่แล้ว — เงินก้อนนี้ยังไม่ว่าง')
               for k in exclude}

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
            'lots': 0, 'cost': 0.0, 'risk_thb': 0.0,
        }
        m['tick_pct'] = sizing.tick(close) / close * 100.0

        reason = None
        if m['symbol'].upper() in exclude:
            reason = exclude[m['symbol'].upper()]
        elif m['rsi'] is None:
            reason = 'อินดิเคเตอร์ไม่ครบ — DR เพิ่งเข้าเทรด'
        elif m['tick_pct'] > config.DR_MAX_TICK_PCT:
            reason = f"1 ช่องราคา = {m['tick_pct']:.1f}% — หยาบเกินเดย์เทรด"
        elif m['gap'] is not None and m['gap'] > config.DR_MAX_GAP:
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
    passed, dupes = _dedupe_underlying(passed)
    return {'passed': passed, 'rejected': rejected, 'dupes': dupes,
            'universe': len(rows) - nvdr, 'nvdr_filtered': nvdr, 'cash': cap}


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

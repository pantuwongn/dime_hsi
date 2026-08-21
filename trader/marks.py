"""
Mark open positions to the market.

A ledger that only remembers what you paid is a filing cabinet. The question
you actually have at 10am on day three of a five-day swing is whether the
thing is working, whether it has quietly gone through the stop while you were
in a meeting, and whether the hold window has run out — none of which the
entry price can answer.

Exits are marked at the bid, not the last trade: on a DW quoted 0.45/0.48 the
last print is not what you can get out at, and pretending otherwise is how a
position looks fine right up until you try to sell it.
"""

from . import config
from .feeds import tv, thaidw
from .journal import now_bkk


def _stock_marks(symbols: list) -> dict:
    if not symbols:
        return {}
    rows = tv.quote([f'SET:{s}' for s in symbols], ['close', 'change'],
                    market='thailand')
    out = {}
    for r in rows:
        sym = r['_ticker'].split(':')[-1]
        px = tv.num(r, 'close')
        if px is not None:
            out[sym] = {'price': px, 'change': tv.num(r, 'change')}
    return out


def _dw_marks(symbols: list, underlying: str = 'HSI') -> dict:
    if not symbols:
        return {}
    want = {s.upper() for s in symbols}
    out = {}
    for w in thaidw.warrants(underlying):
        if w['symbol'].upper() in want:
            bid = w['bid']
            if bid == bid and bid > 0:      # exit price, not last print
                out[w['symbol']] = {'price': bid, 'change': None}
    return out


def _days_held(ts: str) -> int:
    from datetime import datetime
    try:
        return (now_bkk().date() - datetime.fromisoformat(str(ts)).date()).days
    except (ValueError, TypeError):
        return 0


def mark(positions: list) -> list:
    """
    Positions decorated with where they stand now. Feed failures degrade to
    'unknown' per bucket rather than taking the whole brief down — not knowing
    today's price is a reason to say so, not a reason to show nothing.
    """
    # One screener call per DW series that actually has something open in it,
    # and one TradingView call for everything else.
    jobs = [(_stock_marks, [p['symbol'] for p in positions
                            if p.get('bucket') not in config.DW_SERIES])]
    for key, sr in config.DW_SERIES.items():
        held = [p['symbol'] for p in positions if p.get('bucket') == key]
        if held:
            jobs.append((lambda syms, u=sr['underlying']: _dw_marks(syms, u), held))

    prices = {}
    for fetch, syms in jobs:
        try:
            prices.update(fetch(syms))
        except tv.FeedError:
            pass

    out = []
    for p in positions:
        m = dict(p)
        mark = prices.get(p['symbol'])
        entry = float(p.get('entry') or 0)
        lots = int(p.get('lots') or 0)
        units = lots * config.BOARD_LOT
        m['days_held'] = _days_held(p.get('ts'))
        m['now'] = mark['price'] if mark else None

        if mark and entry > 0:
            m['pnl_pct'] = (mark['price'] - entry) / entry * 100.0
            m['pnl_thb'] = (mark['price'] - entry) * units
            sl, tp = float(p.get('sl') or 0), float(p.get('tp') or 0)
            m['hit_sl'] = bool(sl and mark['price'] <= sl)
            m['hit_tp'] = bool(tp and mark['price'] >= tp)
        else:
            m['pnl_pct'] = m['pnl_thb'] = None
            m['hit_sl'] = m['hit_tp'] = False

        m['stale'] = (p.get('bucket') == 'cheap'
                      and m['days_held'] > config.CHEAP_HOLD_DAYS)
        m['alert'] = _alert(m)
        out.append(m)
    return out


def _alert(m: dict) -> str:
    if m['hit_sl']:
        return 'หลุด SL แล้ว — ขายทิ้ง แล้ว --close'
    if m['hit_tp']:
        return 'ถึง TP แล้ว — ขายเก็บกำไร แล้ว --close'
    if m['stale']:
        return f"ถือมา {m['days_held']} วัน เกิน {config.CHEAP_HOLD_DAYS} — ปิดได้แล้ว"
    if m.get('bucket') in config.DW_SERIES and m['days_held'] >= 1:
        return 'DW ถือข้ามคืน — เสีย theta ทุกวัน ปิดวันนี้'
    if config.is_intraday(m.get('bucket')) and m['days_held'] >= 1:
        return 'ค้างข้ามคืน — แผนนี้คิดมาสำหรับวันเดียว ปิดแล้วเริ่มใหม่'
    if m['now'] is None:
        return 'ไม่รู้ราคาปัจจุบัน — เช็คเองในแอปโบรก'
    return ''

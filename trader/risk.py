"""
Daily risk state, read back out of the journal.

Position sizing decides what one mistake costs. This decides how many mistakes
a day is allowed to contain, which on an account this size matters more: 5,000
THB does not disappear on one bad trade, it disappears on the third trade taken
to win back the first two. So the limit is enforced by the tool rather than by
remembering to be disciplined at 10am with a red screen in front of you.

Recommendations are written as SIGNAL and never count here — running the script
twice before lunch is not two trades. Only an entry confirmed with `--took`,
and the `--close` that ends it, move these numbers.
"""

from datetime import datetime

from . import config
from .journal import load, now_bkk


def _day(ts: str):
    try:
        return datetime.fromisoformat(str(ts)).date()
    except (ValueError, TypeError):
        return None


def open_positions(rows: list = None) -> list:
    """
    Entries with no exit yet, oldest first.

    Needed for more than reporting: a 5-day swing means that on day two the
    money is still committed, and a tool that forgets it will happily size a
    fresh position against cash it does not have.
    """
    rows = load() if rows is None else rows
    live = {}
    for r in rows:
        key = (r.get('bucket'), r.get('symbol'))
        if r.get('action') == 'ENTER':
            live.setdefault(key, []).append(r)
        elif r.get('action') == 'EXIT' and live.get(key):
            live[key].pop(0)
    out = [r for lot in live.values() for r in lot]
    return sorted(out, key=lambda r: str(r.get('ts', '')))


def committed(bucket: str = None, rows: list = None) -> float:
    """Capital currently locked in open positions, optionally one bucket."""
    return sum(float(p.get('cost') or 0.0) for p in open_positions(rows)
               if bucket is None or p.get('bucket') == bucket)


def stopped_today(bucket: str = None, rows: list = None) -> list:
    """
    Names closed at a loss today.

    Buying back into something that just took your stop, on the same day, is
    the revenge trade wearing the clothes of a fresh signal — and the screen
    will show it as a fresh signal, because nothing about the indicators knows
    what happened to you an hour ago.
    """
    rows = load() if rows is None else rows
    today = now_bkk().date()
    return sorted({str(r.get('symbol') or '') for r in rows
                   if r.get('action') == 'EXIT'
                   and _day(r.get('ts')) == today
                   and float(r.get('pnl') or 0.0) < 0
                   and (bucket is None or r.get('bucket') == bucket)} - {''})


def state(rows: list = None) -> dict:
    rows = load() if rows is None else rows
    today = now_bkk().date()
    todays = [r for r in rows if _day(r.get('ts')) == today]

    entries = [r for r in todays if r.get('action') == 'ENTER']
    realised = sum(float(r.get('pnl') or 0.0)
                   for r in todays if r.get('action') == 'EXIT')
    live = open_positions(rows)
    at_risk = sum(float(p.get('risk_thb') or 0.0) for p in live)

    limit = config.daily_loss_limit()
    # What today can still cost in the worst case: everything already booked
    # against you, plus every stop still sitting out there waiting to be hit.
    exposure = max(0.0, -realised) + at_risk

    blocked, reason = False, ''
    if realised <= -limit:
        blocked = True
        reason = f'ขาดทุนวันนี้ {-realised:,.0f}฿ ถึงเพดาน {limit:,.0f}฿ แล้ว'
    elif len(entries) >= config.MAX_DAILY_TRADES:
        blocked = True
        reason = f'เข้าไปแล้ว {len(entries)} ไม้วันนี้ (เพดาน {config.MAX_DAILY_TRADES})'
    elif exposure >= limit:
        blocked = True
        reason = (f'ความเสี่ยงที่ค้างอยู่ {exposure:,.0f}฿ เต็มโควตา {limit:,.0f}฿ '
                  '— ปิดไม้เดิมก่อนถึงจะเปิดใหม่ได้')

    return {
        'trades': len(entries),
        'max_trades': config.MAX_DAILY_TRADES,
        'realised': realised,
        'at_risk': at_risk,
        'exposure': exposure,
        'limit': limit,
        'remaining': max(0.0, limit - exposure),
        'open': live,
        'blocked': blocked,
        'reason': reason,
    }


def headline(st: dict) -> str:
    """One line of plain text — the same sentence for terminal and web."""
    return (f"{st['trades']}/{st['max_trades']} ไม้ · "
            f"ขาดทุน {max(0.0, -st['realised']):,.0f}฿ · "
            f"เสี่ยงค้าง {st['at_risk']:,.0f}฿ · "
            f"เหลือ {st['remaining']:,.0f}฿")

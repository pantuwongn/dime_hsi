"""
Daily risk state, read back out of the journal.

Position sizing decides what one mistake costs. This decides how many mistakes
a day is allowed to contain, which on an account this size matters more: 3,000
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


def walk(rows: list = None) -> tuple:
    """
    Match exits against entries FIFO, lot by lot.

    Lot by lot matters: selling 2 of 5 lots is the ordinary way out of a
    position that is half working, and matching whole tickets would erase the
    other 3 from the ledger — the tool would report flat while the broker
    reports otherwise, which is the one disagreement that must never happen.

    Returns (open_chunks, closures) where a closure is (exit_row, [(entry_row,
    lots), ...]) — the entries that exit actually consumed.
    """
    rows = load() if rows is None else rows
    books, closures = {}, []
    for r in rows:
        key = (r.get('bucket'), r.get('symbol'))
        action = r.get('action')
        if action == 'ENTER':
            n = int(r.get('lots') or 0)
            if n > 0:
                books.setdefault(key, []).append([r, n])
        elif action == 'EXIT':
            book = books.get(key) or []
            want = int(r.get('lots') or 0) or sum(b[1] for b in book)
            taken = []
            while want > 0 and book:
                chunk = book[0]
                n = min(want, chunk[1])
                taken.append((chunk[0], n))
                chunk[1] -= n
                want -= n
                if chunk[1] <= 0:
                    book.pop(0)
            if taken:
                closures.append((r, taken))
    open_chunks = [(row, n) for book in books.values() for row, n in book if n > 0]
    return open_chunks, closures


def open_positions(rows: list = None) -> list:
    """
    What is still held, oldest first, averaged the way a broker averages it.

    Needed for more than reporting: a 5-day swing means that on day two the
    money is still committed, and a tool that forgets it will happily size a
    fresh position against cash it does not have.
    """
    chunks, _ = walk(rows)
    merged = {}
    for row, n in chunks:
        key = (row.get('bucket'), row.get('symbol'))
        entry = float(row.get('entry') or 0)
        units = n * config.BOARD_LOT
        risk = max(0.0, entry - float(row.get('sl') or 0)) * units
        pos = merged.get(key)
        if pos is None:
            merged[key] = dict(row, lots=n, units=units, entry=entry,
                               cost=entry * units, risk_thb=risk)
            continue
        total = pos['units'] + units
        pos['entry'] = (pos['entry'] * pos['units'] + entry * units) / total
        pos['lots'] += n
        pos['units'] = total
        pos['cost'] += entry * units
        pos['risk_thb'] += risk
        pos['ts'] = min(str(pos.get('ts') or ''), str(row.get('ts') or ''))
    return sorted(merged.values(), key=lambda p: str(p.get('ts', '')))


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

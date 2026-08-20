"""
What the signals actually did.

The journal was write-only: every recommendation went in and nothing ever came
back out, which meant DW_SIGNAL_ENTER, CHEAP_MIN_RR and the timeframe weights
were guesses that could never be checked. This is the read side.

The number that decides whether a bucket stays is expectancy after costs —
average THB per trade, fees and spread already paid. A bucket can win 60% of
its trades and still bleed, if the 40% are bigger or if it pays a round trip
often enough. On an account this small, running three strategies at once
probably spreads it too thin to matter; this is how you find out which one to
keep instead of deciding by feel.
"""

from datetime import datetime

from .journal import load, now_bkk

# Below this, a bucket's record is anecdote. Say so rather than ranking noise.
MIN_SAMPLE = 10


def _days(a: str, b: str) -> int:
    try:
        return (datetime.fromisoformat(str(b)).date()
                - datetime.fromisoformat(str(a)).date()).days
    except (ValueError, TypeError):
        return 0


def closed_trades(rows: list = None) -> list:
    """Pair each ENTER with the EXIT that ended it, oldest first."""
    rows = load() if rows is None else rows
    live, done = {}, []
    for r in rows:
        key = (r.get('bucket'), r.get('symbol'))
        if r.get('action') == 'ENTER':
            live.setdefault(key, []).append(r)
        elif r.get('action') == 'EXIT' and live.get(key):
            entry = live[key].pop(0)
            cost = float(r.get('cost') or entry.get('cost') or 0.0)
            pnl = float(r.get('pnl') or 0.0)
            done.append({
                'bucket': r.get('bucket'),
                'symbol': r.get('symbol'),
                'opened': entry.get('ts'),
                'closed': r.get('ts'),
                'entry': float(entry.get('entry') or 0.0),
                'exit': float(r.get('exit') or 0.0),
                'lots': int(entry.get('lots') or 0),
                'cost': cost,
                'fees': float(r.get('fees') or 0.0),
                'pnl': pnl,
                'pnl_pct': (pnl / cost * 100.0) if cost else 0.0,
                'days': _days(entry.get('ts'), r.get('ts')),
            })
    return done


def _stats(trades: list) -> dict:
    n = len(trades)
    if not n:
        return {'n': 0, 'wins': 0, 'hit_rate': None, 'avg_win': 0.0,
                'avg_loss': 0.0, 'expectancy': 0.0, 'fees': 0.0, 'net': 0.0,
                'best': 0.0, 'worst': 0.0, 'verdict': 'ยังไม่มีไม้ที่ปิดแล้ว'}
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    net = sum(t['pnl'] for t in trades)
    st = {
        'n': n,
        'wins': len(wins),
        'hit_rate': len(wins) / n * 100.0,
        'avg_win': (sum(t['pnl'] for t in wins) / len(wins)) if wins else 0.0,
        'avg_loss': (sum(t['pnl'] for t in losses) / len(losses)) if losses else 0.0,
        'expectancy': net / n,
        'fees': sum(t['fees'] for t in trades),
        'net': net,
        'best': max(t['pnl'] for t in trades),
        'worst': min(t['pnl'] for t in trades),
    }
    st['verdict'] = _verdict(st)
    return st


def _verdict(st: dict) -> str:
    """
    Deliberately blunt. The whole point of measuring is to be willing to stop
    doing something, and a hedged sentence never made anyone close a bucket.
    """
    if st['n'] < MIN_SAMPLE:
        return f"ยังน้อยเกินสรุป ({st['n']}/{MIN_SAMPLE} ไม้)"
    if st['expectancy'] > 0:
        return f"ได้ {st['expectancy']:+,.0f}฿/ไม้ — เก็บก้อนนี้ไว้"
    return f"เสีย {st['expectancy']:+,.0f}฿/ไม้ — ตัดก้อนนี้ทิ้ง เอาทุนไปก้อนที่ได้"


def summarise(rows: list = None) -> dict:
    rows = load() if rows is None else rows
    trades = closed_trades(rows)

    by_bucket = {}
    for b in ('dw', 'cheap', 'dr'):
        by_bucket[b] = _stats([t for t in trades if t['bucket'] == b])

    signals = sum(1 for r in rows if r.get('action') == 'SIGNAL')
    entered = sum(1 for r in rows if r.get('action') == 'ENTER')
    # min, not first: a journal can be appended to out of order once
    # historical rows are backfilled or two runs race.
    stamps = sorted(str(r.get('ts')) for r in rows if r.get('ts'))
    first = stamps[0] if stamps else None

    return {
        'trades': trades,
        'by_bucket': by_bucket,
        'overall': _stats(trades),
        'signals': signals,
        'entered': entered,
        'taken_pct': (entered / signals * 100.0) if signals else None,
        'since': first,
        'days': _days(first, now_bkk().isoformat()) if first else 0,
    }

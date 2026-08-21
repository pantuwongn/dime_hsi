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

from . import config, risk
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
    """
    One record per exit, oldest first, priced against the lots it consumed.

    A partial sale is its own trade: closing 2 of 5 lots books the result on
    those 2, and the remaining 3 stay open until they are sold. Averaging the
    exit over the whole original ticket would credit it with a result it has
    not had yet.
    """
    rows = load() if rows is None else rows
    done = []
    for ex, taken in risk.walk(rows)[1]:
        lots = sum(n for _, n in taken)
        units = lots * config.BOARD_LOT
        entry = sum(float(e.get('entry') or 0.0) * n for e, n in taken) / lots
        cost = entry * units
        pnl = float(ex.get('pnl') or 0.0)
        opened = min(str(e.get('ts') or '') for e, _ in taken)
        done.append({
            'bucket': ex.get('bucket'),
            'symbol': ex.get('symbol'),
            'opened': opened,
            'closed': ex.get('ts'),
            'entry': entry,
            'exit': float(ex.get('exit') or 0.0),
            'lots': lots,
            'cost': cost,
            'fees': float(ex.get('fees') or 0.0),
            'pnl': pnl,
            'pnl_pct': (pnl / cost * 100.0) if cost else 0.0,
            'days': _days(opened, ex.get('ts')),
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

    # Every configured bucket, plus any the journal remembers that config no
    # longer lists. A bucket that was removed still traded real money, and a
    # scoreboard that silently drops its rows is a scoreboard you cannot trust.
    retired = [b for b in dict.fromkeys(t['bucket'] for t in trades)
               if b and b not in config.BUCKET_ORDER]
    by_bucket = {}
    for b in tuple(config.BUCKET_ORDER) + tuple(retired):
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

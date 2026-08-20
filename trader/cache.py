"""
Local price history.

No free feed reachable from here serves intraday candles: Yahoo answers
HTTP 429, set.or.th and settrade.com sit behind Imperva, and thaidw only
publishes chart images. TradingView's scanner returns the current value of an
indicator, never a series.

So the series is built the only honest way available — every run appends what
it saw, and sparklines fill in as the file grows. Until then they render as
dots rather than as an invented line.
"""

import json
import os

from .journal import now_bkk

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.cache')
_PATH = os.path.join(_DIR, 'series.jsonl')
_MAX_ROWS = 4000


def append(symbol: str, price: float) -> None:
    """
    Best effort. Serverless filesystems are read-only outside /tmp, and a
    missing sparkline is never a reason to fail a page that is otherwise fine.
    """
    if price is None:
        return
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps({'t': now_bkk().isoformat(timespec='minutes'),
                                 's': symbol, 'p': round(float(price), 4)}) + '\n')
        _trim()
    except OSError:
        pass


def series(symbol: str, limit: int = 30) -> list:
    try:
        if not os.path.exists(_PATH):
            return []
    except OSError:
        return []
    out = []
    with open(_PATH, encoding='utf-8') as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get('s') == symbol:
                out.append(row.get('p'))
    return out[-limit:]


def _trim() -> None:
    try:
        with open(_PATH, encoding='utf-8') as fh:
            lines = fh.readlines()
    except OSError:
        return
    if len(lines) <= _MAX_ROWS:
        return
    with open(_PATH, 'w', encoding='utf-8') as fh:
        fh.writelines(lines[-_MAX_ROWS:])

"""
TradingView scanner client.

One POST returns the whole market (or a named ticker list) with indicators
already computed server-side, on any timeframe. This replaces the entire
yfinance + pandas indicator pipeline: no API key, no per-symbol requests,
no rate limit to trip over.

Timeframe suffixes on a column: "RSI|5", "MACD.macd|15", "EMA9|60".
No suffix == daily.
"""

import json
import urllib.request
import urllib.error

_URL = 'https://scanner.tradingview.com/{market}/scan'
_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Content-Type': 'application/json',
    'Origin': 'https://www.tradingview.com',
    'Referer': 'https://www.tradingview.com/',
}


class FeedError(RuntimeError):
    """Raised when a feed cannot be trusted — never swallowed silently."""


def _post(market: str, payload: dict, timeout: int = 30) -> dict:
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(_URL.format(market=market), data=body,
                                 headers=_HEADERS, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise FeedError(f'TradingView {market} HTTP {e.code}: {e.reason}') from e
    except Exception as e:
        raise FeedError(f'TradingView {market} unreachable: {e}') from e


def _rows(raw: dict, columns: list) -> list:
    out = []
    for item in raw.get('data', []):
        row = dict(zip(columns, item.get('d', [])))
        row['_ticker'] = item.get('s', '')
        out.append(row)
    return out


def quote(tickers: list, columns: list, market: str = 'thailand') -> list:
    """Fetch a named list of symbols, e.g. ['SET:TTB', 'SET:BABA80']."""
    raw = _post(market, {'symbols': {'tickers': tickers}, 'columns': columns})
    return _rows(raw, columns)


def screen(filters: list, columns: list, market: str = 'thailand',
           sort_by: str = 'Value.Traded', desc: bool = True,
           limit: int = 300) -> list:
    """
    Filter the whole market. `filters` is a list of
    {'left': col, 'operation': 'less'|'greater'|'equal', 'right': value}.
    """
    payload = {
        'filter': filters,
        'options': {'lang': 'en'},
        'columns': columns,
        'sort': {'sortBy': sort_by, 'sortOrder': 'desc' if desc else 'asc'},
        'range': [0, limit],
    }
    raw = _post(market, payload)
    return _rows(raw, columns)


def num(row: dict, key: str, default=None):
    """
    TradingView returns null for any column it could not compute — a fresh
    listing, a halted symbol, an indicator without enough history. Callers
    must decide what a missing value means, so this never invents one.
    """
    v = row.get(key)
    if v is None or isinstance(v, str):
        return default
    return float(v)

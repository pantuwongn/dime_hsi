"""
thaidw.com feed — the only public source that carries the Thai-listed
HSI derivative warrants with their live bid/ask and greeks.

TradingView does not list DW symbols at all (SET:HSI28C2610A returns
totalCount 0), and set.or.th / settrade.com sit behind Imperva and reject
non-browser clients, so this is the feed the DW bucket depends on.
"""

import json
import urllib.request

from .net import FeedError, fetch

_BASE = 'https://www.thaidw.com/apimqth/'
_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Referer': 'https://www.thaidw.com/',
}


def _get(path: str) -> dict:
    def attempt(timeout):
        req = urllib.request.Request(_BASE + path, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))

    return fetch(attempt, 'thaidw')


def num(value, default=float('nan')) -> float:
    """thaidw ships numbers as strings with commas, and 'N/A' for unpriced DWs."""
    try:
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return default


def hsi_futures() -> dict:
    """
    Live HSI front-month future (HSIc1) — the actual underlying of every
    Thai HSI DW. Not the same thing as the ^HSI spot index: the two carry
    a basis of a few dozen points and the future trades outside cash hours.
    """
    d = _get('LiveIndexJSON')
    keys = d.get('keys') or []
    if not keys:
        raise FeedError('LiveIndexJSON returned no index keys')
    row = d[keys[0]][0]
    return {
        'symbol': keys[0],
        'bid': num(row.get('bid')),
        'ask': num(row.get('ask')),
        'net': num(row.get('net')),
        'pct': num(row.get('pct')),
        'update_time': d.get('update_time', ''),
    }


def hsi_warrants() -> list:
    """Every Thai-listed DW on HSI, all issuers, with live bid/ask and greeks."""
    q = ('ScreenerJSONServlet?underlying=HSI&type=all&issuer=all&maturity=all'
         '&moneyness=all&moneynessPercent=all&effectiveGearing=all&expiry=all'
         '&indicator=all&sortBy=&sortOrder=&qid=1')
    rows = _get(q).get('data', [])
    if not rows:
        raise FeedError('HSI DW screener returned no rows')

    out = []
    for r in rows:
        sym = r.get('dwSymbol', '')
        out.append({
            'symbol': sym,
            'issuer_code': sym[3:5] if len(sym) > 5 else '',
            'issuer': r.get('issuer', ''),
            'side': r.get('type', ''),                  # 'C' or 'P'
            'strike': num(r.get('exercisePrice')),
            'bid': num(r.get('bidPrice')),
            'ask': num(r.get('askPrice')),
            'bid_vol': num(r.get('bidVolume'), 0.0),
            'ask_vol': num(r.get('askVolume'), 0.0),
            'volume': num(r.get('tradeVolume'), 0.0),
            'gearing': num(r.get('effectiveGearing')),
            # THB the DW moves per 100 index points (already FX-adjusted)
            'sensitivity': num(r.get('sensitivity_cal')),
            'delta': num(r.get('delta')),
            'theta': num(r.get('time_decay')),          # % lost per day
            'iv': num(r.get('impliedVolalitiy')),
            'moneyness_pct': num(r.get('moneyness_percent')),
            'last_trade_date': r.get('ltDate', ''),
            'dwps': num(r.get('dwps')),
        })
    return out

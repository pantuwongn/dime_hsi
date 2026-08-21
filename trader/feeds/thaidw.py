"""
thaidw.com feed — the only public source that carries the Thai-listed
derivative warrants (HSI, SET50, …) with their live bid/ask and greeks.

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


def futures(code: str = 'HSI') -> dict:
    """
    Live front-month future for one underlying — HSIc1 for the HSI series,
    S50 for the SET50 series. That future, not the spot index, is what the DW
    actually tracks: the two carry a basis and the future keeps trading when
    the cash market is shut.

    Returns None when the feed carries no future for this underlying, because
    a missing side-panel number is not a reason to lose the whole bucket.
    """
    d = _get('LiveIndexJSON')
    keys = d.get('keys') or []
    if not keys:
        raise FeedError('LiveIndexJSON returned no index keys')

    want = code.upper()
    key = next((k for k in keys if want in str(k).upper()), None)
    if key is None:
        # One key and no match used to be the normal case: the feed carried
        # HSI alone and this read keys[0] blindly. Keep that working, but do
        # not hand back some other index under a name it does not have.
        if len(keys) == 1 and want == 'HSI':
            key = keys[0]
        else:
            return None

    rows = d.get(key) or []
    if not rows:
        return None
    row = rows[0]
    return {
        'symbol': key,
        'bid': num(row.get('bid')),
        'ask': num(row.get('ask')),
        'net': num(row.get('net')),
        'pct': num(row.get('pct')),
        'update_time': d.get('update_time', ''),
    }


def hsi_futures() -> dict:
    """The HSI future, or a FeedError — the HSI bucket has always had one."""
    fut = futures('HSI')
    if fut is None:
        raise FeedError('LiveIndexJSON carries no HSI future')
    return fut


def warrants(underlying: str = 'HSI') -> list:
    """
    Every Thai-listed DW on one underlying, all issuers, with live bid/ask
    and greeks. `underlying` is thaidw's own code for the series — 'HSI' for
    Hang Seng, 'S50' for SET50 — and is the only thing that changes between
    them, screener columns included.
    """
    q = (f'ScreenerJSONServlet?underlying={underlying}&type=all&issuer=all'
         '&maturity=all&moneyness=all&moneynessPercent=all&effectiveGearing=all'
         '&expiry=all&indicator=all&sortBy=&sortOrder=&qid=1')
    rows = _get(q).get('data', [])
    if not rows:
        raise FeedError(f'DW screener returned no rows for underlying '
                        f'{underlying} — เช็คค่า underlying ใน config.DW_SERIES')

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


def hsi_warrants() -> list:
    """The HSI series, by the name the DW bucket used before it had two."""
    return warrants('HSI')

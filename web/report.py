"""
Collect all three buckets once, as plain data.

The terminal renderer and the web page need exactly the same numbers, so the
gathering lives here and neither renderer computes anything of its own. Each
bucket is fetched on its own thread: a serverless request has a hard timeout
and the three buckets touch four independent endpoints, so doing them in
sequence spends the budget on waiting.
"""

from concurrent.futures import ThreadPoolExecutor

from trader import cache, config
from trader.buckets import cheap, dr, dw_hsi
from trader.feeds import thaidw
from trader.journal import now_bkk


def _dw() -> dict:
    sig = dw_hsi.index_signal()
    fut = thaidw.hsi_futures()
    cache.append('HSI', sig['close'])

    out = {'signal': sig, 'futures': fut, 'passed': [], 'rejected': [],
           'pick': None, 'plan': None}
    if sig['side'] is None:
        out['verdict'] = 'wait'
        return out

    res = dw_hsi.screen_warrants(sig['side'])
    out['passed'], out['rejected'] = res['passed'], res['rejected']
    if not res['passed']:
        out['verdict'] = 'none'
        return out

    out['verdict'] = 'call' if sig['side'] == 'C' else 'put'
    out['pick'] = res['passed'][0]
    out['plan'] = dw_hsi.build_plan(out['pick'], sig)
    return out


def _cheap() -> dict:
    res = cheap.scan()
    res['verdict'] = 'buy' if res['passed'] else 'wait'
    return res


def _dr() -> dict:
    res = dr.scan()
    res['verdict'] = 'buy' if res['passed'] else 'wait'
    return res


def collect(buckets=('dw', 'cheap', 'dr')) -> dict:
    """Returns {bucket: result} plus an 'errors' map for whatever failed."""
    jobs = {'dw': _dw, 'cheap': _cheap, 'dr': _dr}
    out = {'generated_at': now_bkk(), 'errors': {},
           'budget': dict(config.ALLOC), 'total': config.BUDGET_TOTAL}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(jobs[name]) for name in buckets}
        for name, fut in futures.items():
            try:
                out[name] = fut.result()
            except Exception as e:                    # a dead feed is reportable
                out[name] = None
                out['errors'][name] = f'{type(e).__name__}: {e}'
    return out

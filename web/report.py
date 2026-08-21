"""
Collect every active bucket once, as plain data.

The terminal renderer and the web page need exactly the same numbers, so the
gathering lives here and neither renderer computes anything of its own. Each
bucket is fetched on its own thread: a serverless request has a hard timeout
and the buckets touch independent endpoints, so doing them in sequence spends
the budget on waiting.
"""

from concurrent.futures import ThreadPoolExecutor

from trader import cache, config, marks, review, risk, session
from trader.buckets import cheap, dw, intraday
from trader.feeds import thaidw
from trader.feeds.net import FeedError
from trader.journal import load as load_journal, now_bkk


def _dw(key: str = 'dw') -> dict:
    sr = dw.series(key)
    sig = dw.index_signal(key)
    try:
        fut = thaidw.futures(sr['futures']) if sr['futures'] else None
    except FeedError:
        fut = None                      # the panel line, not the bucket
    cache.append(sr['name'], sig['close'])

    out = {'bucket': key, 'series': sr['name'], 'note': sr['note'],
           'label': config.BUCKET_LABEL[key],
           'signal': sig, 'futures': fut, 'passed': [], 'rejected': [],
           'pick': None, 'plan': None}
    if sig['side'] is None:
        out['verdict'] = 'wait'
        return out

    res = dw.screen_warrants(sig['side'], sig, key=key)
    out['passed'], out['rejected'] = res['passed'], res['rejected']
    if not res['passed']:
        out['verdict'] = 'none'
        return out

    out['verdict'] = 'call' if sig['side'] == 'C' else 'put'
    out['pick'] = res['passed'][0]
    out['plan'] = out['pick']['plan']
    return out


def _free(bucket: str) -> tuple:
    """Cash and untouchable names for one bucket — open positions are not
    spendable, and something stopped out this morning is not a fresh idea."""
    held = [p for p in risk.open_positions() if p.get('bucket') == bucket]
    cash = max(0.0, config.ALLOC[bucket]
               - sum(float(p.get('cost') or 0) for p in held))
    blocked = {p['symbol']: 'ถืออยู่แล้ว — เงินก้อนนี้ยังไม่ว่าง' for p in held}
    for sym in risk.stopped_today(bucket):
        blocked.setdefault(sym, 'เพิ่งโดน SL วันนี้ — ไม่เข้าซ้ำในวันเดียวกัน')
    return cash, blocked


def _cheap() -> dict:
    cash, held = _free('cheap')
    res = cheap.scan(cash=cash, exclude=held)
    res['held'] = sorted(held)
    res['verdict'] = 'buy' if res['passed'] else 'wait'
    return res


def _intraday(key: str = 'day') -> dict:
    sr = intraday.series(key)
    cash, held = _free(key)
    res = intraday.scan(key, cash=cash, exclude=held)
    res['held'] = sorted(held)
    res['verdict'] = 'buy' if res['passed'] else 'wait'
    res['bucket'] = key
    res['label'] = config.BUCKET_LABEL[key]
    res['note'] = sr['note']
    res['min_value_mb'] = sr['min_value'] / 1e6
    return res


def collect(buckets=None) -> dict:
    """Returns {bucket: result} plus an 'errors' map for whatever failed.

    Buckets defaults to the ones with money behind them: a bucket at 0 THB in
    ALLOC is paused, and a card recommending trades it has no budget for is
    worse than no card.
    """
    buckets = config.active_buckets(buckets)
    jobs = {'cheap': _cheap}
    jobs.update({k: (lambda key=k: _dw(key)) for k in config.DW_SERIES})
    jobs.update({k: (lambda key=k: _intraday(key))
                 for k in config.INTRADAY_SERIES})
    # The journal is a local file and is deliberately not deployed, so on
    # Vercel this is empty and every ledger number would be a zero pretending
    # to be a measurement. Read it once, and let the page know which it has.
    rows = load_journal()
    st = risk.state(rows)
    out = {'generated_at': now_bkk(), 'errors': {},
           'budget': dict(config.ALLOC), 'total': config.BUDGET_TOTAL,
           'risk': st, 'held': [], 'review': review.summarise(rows),
           'session': session.state(), 'has_ledger': bool(rows)}

    # Marking open positions is a fourth independent call, so it rides along
    # in the same pool rather than adding its latency to the request.
    jobs['_held'] = lambda: marks.mark(st['open']) if st['open'] else []

    names = tuple(buckets) + ('_held',)
    with ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
        futures = {name: pool.submit(jobs[name]) for name in names}
        for name, fut in futures.items():
            try:
                result = fut.result()
            except Exception as e:                    # a dead feed is reportable
                if name == '_held':
                    continue
                out[name] = None
                out['errors'][name] = f'{type(e).__name__}: {e}'
                continue
            if name == '_held':
                out['held'] = result
            else:
                out[name] = result
    return out

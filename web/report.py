"""
Collect all three buckets once, as plain data.

The terminal renderer and the web page need exactly the same numbers, so the
gathering lives here and neither renderer computes anything of its own. Each
bucket is fetched on its own thread: a serverless request has a hard timeout
and the three buckets touch four independent endpoints, so doing them in
sequence spends the budget on waiting.
"""

from concurrent.futures import ThreadPoolExecutor

from trader import cache, config, marks, review, risk, session
from trader.buckets import cheap, dr, dw_hsi
from trader.feeds import thaidw
from trader.journal import load as load_journal, now_bkk


def _dw() -> dict:
    sig = dw_hsi.index_signal()
    fut = thaidw.hsi_futures()
    cache.append('HSI', sig['close'])

    out = {'signal': sig, 'futures': fut, 'passed': [], 'rejected': [],
           'pick': None, 'plan': None}
    if sig['side'] is None:
        out['verdict'] = 'wait'
        return out

    res = dw_hsi.screen_warrants(sig['side'], sig)
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


def _dr() -> dict:
    cash, held = _free('dr')
    res = dr.scan(cash=cash, exclude=held)
    res['held'] = sorted(held)
    res['verdict'] = 'buy' if res['passed'] else 'wait'
    return res


def collect(buckets=('dw', 'cheap', 'dr')) -> dict:
    """Returns {bucket: result} plus an 'errors' map for whatever failed."""
    jobs = {'dw': _dw, 'cheap': _cheap, 'dr': _dr}
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

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(jobs[name])
                   for name in tuple(buckets) + ('_held',)}
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

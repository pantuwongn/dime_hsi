"""
Is the market actually open?

SESSIONS in config listed four times and nothing ever compared them to the
clock, so a run at 22:00 on a Saturday produced the same screen as one at
10:15 on a Tuesday — same green badge, same "▲ ซื้อ", built entirely out of
Friday's closing prices. On the web view it is worse, because s-maxage makes
the page look live no matter when you open it.

Nothing here blocks a run: reading the market at night to plan tomorrow is a
real thing to do. It just refuses to let the screen imply the numbers are
current when they are not.
"""

from . import config
from .journal import now_bkk

# Local trading hours in Bangkok time. HKEX runs an hour behind Bangkok, so
# its 09:30 open is 08:30 here — which is why bucket A runs before SET opens.
HOURS = {
    'set':  (('10:00', '12:30'), ('14:30', '16:30')),
    'hkex': (('08:30', '11:00'), ('12:00', '15:00')),
}

# DW series bring their own market with them (HSI trades on HKEX hours,
# SET50 DW on SET hours), so the map is built rather than typed twice.
BUCKET_MARKET = {'cheap': 'set', 'dr': 'set'}
BUCKET_MARKET.update({k: sr['session'] for k, sr in config.DW_SERIES.items()})
_LABEL = {'set': 'SET', 'hkex': 'HKEX'}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def is_open(market: str, now=None) -> bool:
    now = now_bkk() if now is None else now
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return any(_minutes(a) <= mins < _minutes(b) for a, b in HOURS[market])


def state(now=None) -> dict:
    now = now_bkk() if now is None else now
    weekend = now.weekday() >= 5
    open_now = {m: is_open(m, now) for m in HOURS}

    if weekend:
        note = 'สุดสัปดาห์ — ตัวเลขทุกตัวคือราคาปิดวันศุกร์ ไม่ใช่ราคาสด'
    elif not any(open_now.values()):
        note = 'นอกเวลาทำการทั้ง SET และ HKEX — ราคานี้คือราคาปิดล่าสุด'
    elif not all(open_now.values()):
        shut = ', '.join(_LABEL[m] for m, v in open_now.items() if not v)
        note = f'{shut} ปิดอยู่ — ก้อนที่อ้างอิงตลาดนี้เป็นราคาปิด ไม่ใช่ราคาสด'
    else:
        note = ''

    return {'open': open_now, 'weekend': weekend, 'note': note,
            'live': not note, 'now': now}


def bucket_note(bucket: str, st: dict = None) -> str:
    """One line for a bucket whose market is shut right now."""
    st = state() if st is None else st
    market = BUCKET_MARKET.get(bucket)
    if not market or st['open'].get(market):
        return ''
    when = config.SESSIONS.get(
        'dw_morning' if market == 'hkex' else 'set_morning', '')
    return (f"{_LABEL[market]} ปิดอยู่ — ราคาปิดล่าสุด ไม่ใช่ราคาสด "
            f"(รอบถัดไป {when} น.)")

"""
Bucket A — Hang Seng Index DW (issuers 18 = KTX, 28 = MACQ). Day trade,
flat by the close.

Two independent questions, answered in order:
  1. Direction — what is the index doing? (TradingView, multi-timeframe)
  2. Instrument — which of the ~31 listed DWs can actually be traded today?

Step 2 is the one the old code never did, and it is the one that decides
whether a correct call makes money. A DW quoted 0.03/0.04 costs 33% to enter
and exit: the index has to move a long way before you are back to flat.
"""

from .. import config, sizing
from ..feeds import tv, thaidw
from ..feeds.tv import num

HSI_TICKER = 'HSI:HSI'

_COLS = [
    'close', 'change', 'open', 'high', 'low',
    'RSI|5', 'RSI|15', 'RSI|60',
    'MACD.macd|15', 'MACD.signal|15',
    'EMA9|15', 'EMA21|15', 'EMA50|15', 'ATR|15',
    'Recommend.All|5', 'Recommend.All|15', 'Recommend.All|60',
]

# Weights per timeframe. 15m carries the most weight: it is slow enough to
# survive the opening spread and fast enough to close inside the session.
_TF_WEIGHT = {'5': 0.25, '15': 0.45, '60': 0.30}


def index_signal() -> dict:
    rows = tv.quote([HSI_TICKER], _COLS, market='global')
    if not rows:
        raise tv.FeedError('TradingView returned no data for HSI')
    r = rows[0]

    close = num(r, 'close')
    atr = num(r, 'ATR|15')
    if close is None:
        raise tv.FeedError('HSI close price missing — refusing to guess')

    parts, missing = {}, []
    for tf, weight in _TF_WEIGHT.items():
        rsi = num(r, f'RSI|{tf}')
        rec = num(r, f'Recommend.All|{tf}')
        if rsi is None or rec is None:
            missing.append(f'{tf}m')
            continue
        # Recommend.All is TradingView's own -1..+1 aggregate of ~26 indicators.
        sub = rec * 70.0
        # RSI adds conviction, and pulls back at the extremes where DWs are
        # the worst thing to be holding.
        if rsi > 70:
            sub -= (rsi - 70) * 1.5
        elif rsi < 30:
            sub += (30 - rsi) * 1.5
        else:
            sub += (rsi - 50) * 0.8
        parts[tf] = {'score': max(-100.0, min(100.0, sub)), 'rsi': rsi,
                     'rec': rec, 'weight': weight}

    if not parts:
        raise tv.FeedError('No timeframe produced a usable signal')

    total_w = sum(p['weight'] for p in parts.values())
    composite = sum(p['score'] * p['weight'] for p in parts.values()) / total_w

    ema9, ema21 = num(r, 'EMA9|15'), num(r, 'EMA21|15')
    aligned = None
    if ema9 is not None and ema21 is not None:
        aligned = 'up' if close > ema9 > ema21 else 'down' if close < ema9 < ema21 else 'mixed'

    if composite >= config.DW_SIGNAL_ENTER:
        side, bias = 'C', 'BULLISH'
    elif composite <= -config.DW_SIGNAL_ENTER:
        side, bias = 'P', 'BEARISH'
    else:
        side, bias = None, 'CHOP / NO TRADE'

    return {
        'close': close, 'change': num(r, 'change'), 'atr': atr,
        'ema9': ema9, 'ema21': ema21, 'ema50': num(r, 'EMA50|15'),
        'high': num(r, 'high'), 'low': num(r, 'low'),
        'composite': composite, 'side': side, 'bias': bias,
        'aligned': aligned, 'per_tf': parts, 'missing_tf': missing,
    }


def _days_to_expiry(lt_date: str) -> int:
    """thaidw ships '29 Sep 26'. Returns -1 when it cannot be parsed."""
    from datetime import datetime
    from ..journal import now_bkk
    try:
        d = datetime.strptime(lt_date.strip(), '%d %b %y').date()
    except (ValueError, AttributeError):
        return -1
    return (d - now_bkk().date()).days


def screen_warrants(side: str, budget: float = None) -> dict:
    """
    Rank every listed HSI DW on the requested side. Returns both the tradeable
    shortlist and the rejects with the reason, because 'why was nothing
    recommended' is as important as the recommendation.
    """
    budget = config.ALLOC['dw'] if budget is None else budget
    warrants = thaidw.hsi_warrants()

    passed, rejected = [], []
    for w in warrants:
        if w['issuer_code'] not in config.DW_ISSUERS:
            continue
        if side and w['side'] != side:
            continue

        m = dict(w)
        m['days'] = _days_to_expiry(w['last_trade_date'])
        m['spread_pct'] = sizing.spread_pct(w['bid'], w['ask'])
        m['breakeven_pts'] = sizing.breakeven_points(w['bid'], w['ask'], w['sensitivity'])
        m.update(sizing.size(w['ask'], budget))

        reason = None
        if not (w['bid'] > 0):
            reason = 'ไม่มี bid — ซื้อแล้วขายไม่ออก'
        elif not (w['sensitivity'] > 0):
            reason = 'sensitivity เป็น 0 — ราคาไม่ขยับตามดัชนี'
        elif 0 <= m['days'] < config.DW_MIN_DAYS:
            reason = f"เหลือ {m['days']} วัน — theta cliff"
        elif m['spread_pct'] > config.DW_MAX_SPREAD:
            reason = f"spread {m['spread_pct']:.0f}% — ค่าเข้าออกแพงเกิน"
        elif m['lots'] < 1:
            reason = f"งบ {budget:,.0f}฿ ไม่พอ 1 lot (ต้อง {w['ask'] * config.BOARD_LOT:,.0f}฿)"

        if reason:
            m['reject'] = reason
            rejected.append(m)
        else:
            m['score'] = _score(m)
            passed.append(m)

    passed.sort(key=lambda x: -x['score'])
    return {'passed': passed, 'rejected': rejected}


def _score(m: dict) -> float:
    """
    Gearing is what you are paying for, spread and theta are what you pay,
    and distance from the money is how likely the gearing is to be real by
    the time you exit.
    """
    gearing = m['gearing'] if m['gearing'] == m['gearing'] else 0.0
    theta = m['theta'] if m['theta'] == m['theta'] else 0.0
    money = m['moneyness_pct'] if m['moneyness_pct'] == m['moneyness_pct'] else 0.0
    spread = m['spread_pct'] if m['spread_pct'] == m['spread_pct'] else 99.0
    return (gearing / (1.0 + spread / 2.0)
            - theta * 1.5
            - max(0.0, money - config.DW_SOFT_MONEY) * 0.35)


def build_plan(pick: dict, signal: dict) -> dict:
    """
    Turn an index-level stop and target into DW prices you can actually type
    into an order slip.

    Two corrections the naive version gets wrong:

    * The move has to be scaled against the DW's own cost, not just ATR. A
      target 59 index points away looks fine until you notice the spread alone
      needs 29 points to break even — you would be risking 18x gearing for 2%
      net. So the target is floored at 3x the breakeven distance.
    * A stop one tick under the bid is not a stop, it is a coin flip on the
      next quote refresh. The stop is floored at 1.5x breakeven too.
    """
    atr = signal.get('atr')
    direction = 1.0 if pick['side'] == 'C' else -1.0
    entry = pick['ask']
    be = pick.get('breakeven_pts') or 0.0

    if not atr:
        return {'entry': entry, 'note': 'ATR ไม่มา — ตั้ง TP/SL เองจากกราฟ'}

    tp_move = max(atr * config.DW_TP_ATR, be * 3.0)
    sl_move = max(atr * config.DW_SL_ATR, be * 1.5)
    per_point = pick['sensitivity'] / 100.0    # THB per 1 index point

    tp_price = sizing.to_tick(entry + tp_move * per_point, 'up')
    sl_price = max(0.01, sizing.to_tick(entry - sl_move * per_point, 'down'))

    gross = (tp_price - entry) / entry * 100.0
    cost_pct = pick['spread_pct'] + pick.get('fee_pct', 0.0)
    risk = entry - sl_price

    return {
        'entry': entry,
        'index_now': signal['close'],
        'index_tp': signal['close'] + direction * tp_move,
        'index_sl': signal['close'] - direction * sl_move,
        'tp_price': tp_price,
        'sl_price': sl_price,
        'tp_gain_pct': gross,
        'tp_net_pct': gross - cost_pct,
        'sl_loss_pct': -risk / entry * 100.0,
        'rr': (tp_price - entry) / risk if risk > 0 else float('nan'),
        'max_loss_thb': pick['cost'] * risk / entry,
    }

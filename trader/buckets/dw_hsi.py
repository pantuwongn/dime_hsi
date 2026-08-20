"""
Bucket A — Hang Seng Index DW (issuers 18 = KTX, 28 = MACQ). Day trade,
flat by the close.

Three questions, answered in order:
  1. Direction — what is the index doing? (TradingView, multi-timeframe)
  2. Instrument — which of the ~31 listed DWs can actually be traded today?
  3. Size — how many lots put exactly one unit of risk on the table?

Step 2 is what decides whether a correct call makes money: a DW quoted
0.03/0.04 costs 33% to enter and exit. Step 3 is what decides whether being
wrong three days running is a bad week or the end of the account — which is
why the stop is now computed before the size, not after it.
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

    # The EMA stack was computed and then only printed. As a gate it costs
    # nothing — no extra request, no extra column — and it throws out the
    # score that spiked while price is still tangled in its own averages,
    # which is the trade whose spread you pay for and whose move never comes.
    vetoed = None
    if side and config.DW_REQUIRE_ALIGN:
        want = 'up' if side == 'C' else 'down'
        if aligned != want:
            vetoed = aligned or 'ไม่รู้'
            side = None
            bias = f'สัญญาณ{"ขึ้น" if want == "up" else "ลง"} แต่ EMA ยังไม่เรียง ({vetoed})'

    return {
        'close': close, 'change': num(r, 'change'), 'atr': atr,
        'ema9': ema9, 'ema21': ema21, 'ema50': num(r, 'EMA50|15'),
        'high': num(r, 'high'), 'low': num(r, 'low'),
        'composite': composite, 'side': side, 'bias': bias,
        'aligned': aligned, 'vetoed_by_align': vetoed,
        'per_tf': parts, 'missing_tf': missing,
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


def plan_prices(w: dict, signal: dict) -> dict:
    """
    Where the stop and the target sit, in DW price terms. No position size —
    the size is derived from the stop, so this has to come first.

    Two corrections a naive version gets wrong:

    * The move has to be scaled against the DW's own cost, not just ATR. A
      target 59 index points away looks fine until you notice the spread alone
      needs 29 points to break even. So the target is floored at 3x breakeven.
    * A stop one tick under the bid is not a stop, it is a coin flip on the
      next quote refresh. It is floored at 1.5x breakeven too.

    When ATR is missing the breakeven floors carry the whole thing rather than
    the plan collapsing — a DW with a known spread always has a worst case.
    """
    per_point = (w.get('sensitivity') or 0.0) / 100.0    # THB per index point
    if per_point <= 0:
        return None

    atr = signal.get('atr') or 0.0
    be = w.get('breakeven_pts')
    be = be if (be is not None and be == be) else 0.0

    tp_move = max(atr * config.DW_TP_ATR, be * 3.0)
    sl_move = max(atr * config.DW_SL_ATR, be * 1.5)
    if tp_move <= 0 or sl_move <= 0:
        return None

    entry = w['ask']
    direction = 1.0 if w['side'] == 'C' else -1.0
    tp_price = sizing.to_tick(entry + tp_move * per_point, 'up')
    sl_price = max(0.01, sizing.to_tick(entry - sl_move * per_point, 'down'))
    if sl_price >= entry or tp_price <= entry:
        return None

    return {
        'entry': entry,
        'tp_price': tp_price,
        'sl_price': sl_price,
        'index_now': signal.get('close'),
        'index_tp': (signal.get('close') or 0.0) + direction * tp_move,
        'index_sl': (signal.get('close') or 0.0) - direction * sl_move,
        'note': '' if atr else 'ATR ไม่มา — TP/SL คิดจากจุดคุ้มทุนแทน',
    }


def _finish_plan(m: dict, pr: dict) -> dict:
    """Attach the numbers that only exist once the position size is known."""
    entry = pr['entry']
    risk = entry - pr['sl_price']
    gross = (pr['tp_price'] - entry) / entry * 100.0

    fee_pct = m.get('fee_pct')
    fee_pct = 0.0 if fee_pct is None or fee_pct != fee_pct else fee_pct
    # Only the commission comes off here. The spread is already inside `gross`:
    # entry IS the ask, and the exit is a limit sell at tp_price, not a market
    # order into the bid. Subtracting it again understated a wide DW by its
    # whole spread — up to 8% — which is the wrong direction to be wrong in,
    # because it talks you out of trades that do clear their costs.
    plan = dict(pr)
    plan.update({
        'tp_gain_pct': gross,
        'tp_net_pct': gross - fee_pct,
        'sl_loss_pct': -risk / entry * 100.0,
        'rr': (pr['tp_price'] - entry) / risk if risk > 0 else float('nan'),
        'max_loss_thb': m.get('risk_thb', m.get('cost', 0.0) * risk / entry),
        'risk_pct_account': m.get('risk_pct', 0.0),
    })
    return plan


def _edge_reason(m: dict, pr: dict):
    """
    Reject a target that does not clear its own round trip by enough to be
    worth the ticket. DW_MAX_SPREAD is an absolute bar — 8% of what? — while
    this compares the cost to what the trade is actually reaching for.
    """
    gross = (pr['tp_price'] - pr['entry']) / pr['entry'] * 100.0
    fee = m.get('fee_pct')
    fee = 0.0 if fee is None or fee != fee else fee
    spread = m.get('spread_pct')
    spread = 0.0 if spread is None or spread != spread else spread
    cost = spread + fee
    if cost > 0 and gross < cost * config.MIN_EDGE_MULTIPLE:
        return (f"เป้า +{gross:.0f}% แต่ค่าเข้าออก {cost:.1f}% — "
                f"ต้องได้อย่างน้อย {cost * config.MIN_EDGE_MULTIPLE:.0f}%")
    return None


def _no_lot_reason(w: dict, pr: dict, risk_thb: float, budget: float) -> str:
    """'Nothing fits' has two different causes and two different answers."""
    per_lot_cost = w['ask'] * config.BOARD_LOT
    per_lot_risk = (w['ask'] - pr['sl_price']) * config.BOARD_LOT
    if per_lot_cost > budget:
        return f"งบ {budget:,.0f}฿ ไม่พอ 1 lot (ต้อง {per_lot_cost:,.0f}฿)"
    return (f"1 lot เสี่ยง {per_lot_risk:,.0f}฿ — เกินโควตา {risk_thb:,.0f}฿/ไม้")


def screen_warrants(side: str, signal: dict, budget: float = None,
                    risk_thb: float = None) -> dict:
    """
    Rank every listed HSI DW on the requested side. Returns both the tradeable
    shortlist and the rejects with the reason, because 'why was nothing
    recommended' is as important as the recommendation.
    """
    budget = config.ALLOC['dw'] if budget is None else budget
    risk_thb = config.risk_thb() if risk_thb is None else risk_thb
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
        m['lots'], m['cost'], m['risk_thb'] = 0, 0.0, 0.0

        reason, prices = None, None
        if not (w['bid'] > 0):
            reason = 'ไม่มี bid — ซื้อแล้วขายไม่ออก'
        elif not (w['sensitivity'] > 0):
            reason = 'sensitivity เป็น 0 — ราคาไม่ขยับตามดัชนี'
        elif m['days'] < 0:
            # An unreadable last-trading-day used to sail straight through the
            # theta gate, because -1 is not in [0, DW_MIN_DAYS). Unknown expiry
            # on a decaying instrument is a reason to skip it, not to assume.
            reason = f"อ่านวันหมดอายุไม่ออก ({w['last_trade_date'] or '—'}) — ไม่เดา"
        elif m['days'] < config.DW_MIN_DAYS:
            reason = f"เหลือ {m['days']} วัน — theta cliff"
        elif m['spread_pct'] > config.DW_MAX_SPREAD:
            reason = f"spread {m['spread_pct']:.0f}% — ค่าเข้าออกแพงเกิน"
        else:
            prices = plan_prices(m, signal)
            if prices is None:
                reason = 'ตั้ง TP/SL ไม่ได้ — ไม่มีทั้ง ATR และจุดคุ้มทุน'
            else:
                m.update(sizing.size_by_risk(w['ask'], prices['sl_price'],
                                             risk_thb, cap=budget))
                if m['lots'] < 1:
                    reason = _no_lot_reason(w, prices, risk_thb, budget)
                else:
                    reason = _edge_reason(m, prices)

        if reason:
            m['reject'] = reason
            rejected.append(m)
        else:
            m['plan'] = _finish_plan(m, prices)
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
    """The plan is attached during screening; this serves callers holding a
    bare pick. Returns None when no honest stop can be placed."""
    if pick.get('plan'):
        return pick['plan']
    pr = plan_prices(pick, signal)
    return None if pr is None else _finish_plan(pick, pr)

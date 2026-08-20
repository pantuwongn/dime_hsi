"""Position sizing and cost maths for a small account."""

from . import config


def commission(value: float) -> float:
    return max(value * config.COMM_RATE, config.MIN_COMM if value > 0 else 0.0)


def _nan(x) -> bool:
    return x is None or x != x


def size_by_risk(entry: float, stop: float, risk_thb: float = None,
                 cap: float = None) -> dict:
    """
    How many board lots put exactly `risk_thb` between the entry and the stop,
    never spending more than `cap` THB of capital.

    This is the inversion that matters on a small account. Sizing off the
    budget answers "how much can I buy", which makes every trade a different
    bet — a stop 40% away costs four times what one 10% away does on the same
    ticket. Sizing off the stop answers "how much can I afford to be wrong by",
    so a losing streak subtracts a predictable amount instead of whatever the
    chart happened to hand you.

    `cap` still binds: the allocation is a ceiling, and lots are whole.
    """
    risk_thb = config.risk_thb() if risk_thb is None else risk_thb
    cap = config.BUDGET_TOTAL if cap is None else cap

    dead = {'lots': 0, 'units': 0, 'cost': 0.0, 'fee': 0.0,
            'fee_pct': float('nan'), 'risk_thb': 0.0, 'risk_pct': 0.0,
            'capped_by': None}
    if _nan(entry) or entry <= 0 or _nan(stop) or stop >= entry:
        return dead

    per_lot_cost = entry * config.BOARD_LOT
    per_lot_risk = (entry - stop) * config.BOARD_LOT
    if per_lot_risk <= 0 or per_lot_cost <= 0:
        return dead

    by_risk = int(risk_thb // per_lot_risk)
    by_cap = int(cap // per_lot_cost)
    lots = max(0, min(by_risk, by_cap))

    cost = lots * per_lot_cost
    fee = commission(cost) * 2 if cost else 0.0
    return {
        'lots': lots,
        'units': lots * config.BOARD_LOT,
        'cost': cost,
        'fee': fee,
        'fee_pct': (fee / cost * 100) if cost else float('nan'),
        'risk_thb': lots * per_lot_risk,
        'risk_pct': lots * per_lot_risk / config.BUDGET_TOTAL * 100.0,
        # Which limit actually decided the size — worth showing, because
        # "the allocation was too small" and "one lot already risks too much"
        # are different problems with different fixes.
        'capped_by': 'งบ' if by_cap < by_risk else 'ความเสี่ยง',
    }


def spread_pct(bid: float, ask: float) -> float:
    if not ask or ask <= 0 or bid is None or bid <= 0:
        return float('nan')
    return (ask - bid) / ask * 100.0


def breakeven_points(bid: float, ask: float, sensitivity: float) -> float:
    """
    Index points the underlying must travel before you can exit at your entry
    price. Buying at ask and selling at bid means the spread is paid up front —
    for a wide DW this is a bigger hurdle than anything the chart is saying.
    """
    if not sensitivity or sensitivity <= 0:
        return float('nan')
    return (ask - bid) / sensitivity * 100.0


def tick(price: float) -> float:
    """
    SET tick table. Any order you place must sit on one of these increments,
    so every computed target has to be rounded onto the grid before it can be
    used as an actual limit price.
    """
    if price < 2:    return 0.01
    if price < 5:    return 0.02
    if price < 10:   return 0.05
    if price < 25:   return 0.10
    if price < 100:  return 0.25
    return 0.50


def to_tick(price: float, direction: str = 'nearest') -> float:
    """Snap a price onto the tick grid. 'down' for stops, 'up' for targets."""
    t = tick(price)
    n = price / t
    if direction == 'up':
        n = -(-n // 1)
    elif direction == 'down':
        n = n // 1
    else:
        n = round(n)
    return round(n * t, 2)

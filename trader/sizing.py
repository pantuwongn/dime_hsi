"""Position sizing and cost maths for a small account."""

from . import config


def commission(value: float) -> float:
    return max(value * config.COMM_RATE, config.MIN_COMM if value > 0 else 0.0)


def size(ask: float, budget: float) -> dict:
    """
    How many board lots fit in `budget`, and what the round trip really costs.

    On a 5,000 THB account the fee floor matters more than the signal: a broker
    with a 50 THB daily minimum turns a 1,200 THB position into a 8.3% round
    trip, which no intraday edge survives.
    """
    if not ask or ask <= 0:
        return {'lots': 0, 'units': 0, 'cost': 0.0, 'fee_pct': float('nan')}

    per_lot = ask * config.BOARD_LOT
    lots = int(budget // per_lot)
    cost = lots * per_lot
    fee = commission(cost) * 2 if cost else 0.0
    return {
        'lots': lots,
        'units': lots * config.BOARD_LOT,
        'cost': cost,
        'fee': fee,
        'fee_pct': (fee / cost * 100) if cost else float('nan'),
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

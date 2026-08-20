"""
Central configuration for the 3-bucket day/swing trading assistant.

Everything that is a policy decision (how much money, what counts as
"too illiquid", when to bail out) lives here so the bucket modules stay
pure logic.
"""

# ------------------------------------------------------------------------------
# CAPITAL — total account is intentionally small, so allocation is a hard gate
# ------------------------------------------------------------------------------
BUDGET_TOTAL = 5_000.0

ALLOC = {
    'dw':    1_200.0,   # HSI DW, day trade, capital recycles daily
    'dr':    1_300.0,   # Thai DR, day trade / overnight-gap trade
    'cheap': 2_500.0,   # SET stocks < 3 THB, swing 1-5 days (capital is locked)
}

BOARD_LOT = 100         # SET board lot for stocks, DW and DR alike

# Round-trip cost assumption.
#
# Set to your own broker's rate — this is the one number here that is not a
# strategy choice but a fact about your account. MIN_COMM is the daily floor:
# a 50 THB minimum turns a 1,200 THB position into an 8% round trip, which no
# intraday edge survives, so brokers that charge one are unusable at this size.
#
#   Finansia Syrus (current)  0.157%   no minimum
#   SBITO                     0.075%   no minimum
COMM_RATE = 0.00157     # Finansia Syrus, online cash balance
MIN_COMM  = 0.0         # Finansia removed its daily minimum in 2017


# ------------------------------------------------------------------------------
# BUCKET A — HSI DW (issuers 18 = KTX, 28 = MACQ)
# ------------------------------------------------------------------------------
DW_ISSUERS       = ('18', '28')
DW_MAX_SPREAD    = 8.0    # % of ask. Above this the round trip eats the edge
DW_MIN_DAYS      = 10     # calendar days to last trading day (theta cliff)
DW_SOFT_MONEY    = 5.0    # moneyness % beyond which we start penalising
DW_SIGNAL_ENTER  = 45     # |composite| needed to take a trade at all
DW_TP_ATR        = 2.5    # take profit at N x ATR(15m) — a session move, not a scalp
DW_SL_ATR        = 1.5    # stop at N x ATR(15m), floored above the spread

# ------------------------------------------------------------------------------
# BUCKET B — SET stocks under 3 THB, swing
# ------------------------------------------------------------------------------
CHEAP_MAX_PRICE  = 3.0
CHEAP_MIN_VALUE  = 30_000_000.0   # THB traded today; below this you cannot exit
CHEAP_MIN_RVOL   = 0.8
CHEAP_HOLD_DAYS  = 5
CHEAP_MIN_RR     = 1.5            # target must clear the stop by 1.5x

# ------------------------------------------------------------------------------
# BUCKET C — Thai DR
# ------------------------------------------------------------------------------
DR_MIN_VALUE     = 5_000_000.0
DR_MAX_PRICE     = 40.0
DR_MAX_GAP       = 9.0            # % — beyond this you are chasing, not trading
DR_MAX_TICK_PCT  = 1.5            # one tick as % of price

# ------------------------------------------------------------------------------
# SESSIONS (Asia/Bangkok)
# ------------------------------------------------------------------------------
SESSIONS = {
    'dw_morning':   '08:35',   # HKEX 09:30 HKT + 5 min for the spread to settle
    'dw_afternoon': '12:05',   # HKEX 13:00 HKT
    'set_morning':  '10:15',   # SET has been open ~25 min
    'eod_close':    '15:45',   # close every day-trade position
}

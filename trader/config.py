"""
Central configuration for the 3-bucket day/swing trading assistant.

Everything that is a policy decision (how much money, what counts as
"too illiquid", when to bail out) lives here so the bucket modules stay
pure logic.
"""

# ------------------------------------------------------------------------------
# CAPITAL — total account is intentionally small, so allocation is a hard gate
# ------------------------------------------------------------------------------
BUDGET_TOTAL = 3_000.0

ALLOC = {
    'dw':      500.0,   # HSI DW, day trade, capital recycles daily
    'cheap': 2_000.0,   # SET stocks < 3 THB, swing 1-5 days (capital is locked)
    'dr':        0.0,   # Thai DR — paused, see below
    's50':     500.0,   # SET50 DW, day trade, same engine as HSI DW
}

# A bucket at 0 THB is paused, not deleted. Nothing scans it and no card asks
# to be traded, but the journal keeps its history and --review still scores it,
# so turning it back on is one number here rather than a code change.
#
# DR is paused because it does not fit this account any more: a board lot is
# 100 units, so a DR at 12 THB is a 1,200 THB ticket — most of the account in
# one day trade. Give it money back only alongside a DR_MAX_PRICE that a lot
# of the allocation can actually buy.
BUCKET_ORDER = ('dw', 'cheap', 'dr', 's50')

# Kept to 10 terminal cells: these are table cells as well as panel titles.
BUCKET_LABEL = {'dw': 'A · DW HSI', 'cheap': 'B · หุ้น', 'dr': 'C · DR',
                's50': 'D · DW S50'}


def active_buckets(want=None) -> tuple:
    """Buckets with money behind them, in display order."""
    return tuple(b for b in (BUCKET_ORDER if want is None else want)
                 if ALLOC.get(b, 0.0) > 0)


BOARD_LOT = 100         # SET board lot for stocks, DW and DR alike

# ------------------------------------------------------------------------------
# RISK — the binding constraint on an account this size
#
# ALLOC above is a ceiling, not a target. What decides position size is how far
# away the stop is, because "spend the whole allocation every time" makes every
# trade a different bet: a DW stopped 40% away risks four times what one
# stopped 10% away does on the same ticket. Risking a fixed slice of the
# account instead makes them the same bet, which is the only way a losing
# streak stays survivable here — at 1.5% you can lose thirty in a row and still
# hold two thirds of the account.
#
# The daily limits exist because the way a small account actually dies is not
# one bad trade. It is the third trade, taken to win back the first two.
# ------------------------------------------------------------------------------
RISK_PER_TRADE   = 0.015   # of BUDGET_TOTAL, between entry and stop
MAX_DAILY_LOSS   = 0.04    # realised + still-open risk that ends the day
MAX_DAILY_TRADES = 2       # confirmed entries per day, all buckets together

# Costs are paid per trade, so trading often is itself a strategy — a losing
# one here. A 6% DW spread on a 1,000 THB ticket is 60 THB each way; taken
# daily that is 1,200 THB a month, 40% of the whole account, before being
# right or wrong about anything. So a setup has to promise a multiple of what
# it costs, or it is not a setup, it is a fee.
MIN_EDGE_MULTIPLE = 3.0    # target must be N x the round trip it has to clear


def risk_thb() -> float:
    """THB put at risk between entry and stop on a single position."""
    return BUDGET_TOTAL * RISK_PER_TRADE


def daily_loss_limit() -> float:
    """THB of loss — booked or still on the table — that closes the day."""
    return BUDGET_TOTAL * MAX_DAILY_LOSS


# Round-trip cost assumption.
#
# Set to your own broker's rate — this is the one number here that is not a
# strategy choice but a fact about your account. MIN_COMM is the daily floor:
# a 50 THB minimum turns a 1,000 THB position into a 10% round trip, which no
# intraday edge survives, so brokers that charge one are unusable at this size.
#
#   Finansia Syrus (current)  0.157%   no minimum
#   SBITO                     0.075%   no minimum
COMM_RATE = 0.00157     # Finansia Syrus, online cash balance
MIN_COMM  = 0.0         # Finansia removed its daily minimum in 2017


# ------------------------------------------------------------------------------
# BUCKETS A and D — DW, one entry per underlying
#
# The gates below (spread, theta, moneyness, signal) are the same for every DW
# series, because they are facts about warrants, not about an index. What
# changes per series is where the quotes come from and when the market is
# open, so that is all this table holds. Adding another underlying — SET50 was
# the second — is an entry here plus a budget line in ALLOC, no new code.
#
#   underlying  thaidw's screener code for the series
#   ticker      TradingView symbol for the index the DW tracks
#   market      which TradingView scanner serves that symbol
#   issuers     issuer codes to accept, or None for every issuer on the board
#   futures     thaidw code of the future the DW really tracks, or None
#
# The HSI issuer filter (18 = KTX, 28 = MACQ) is there because those two make
# the market on HSI. SET50 DW is issued by a lot more houses and none of them
# dominates, so it takes every issuer and lets the spread gate do the culling.
# ------------------------------------------------------------------------------
DW_SERIES = {
    'dw': {
        'name': 'HSI', 'underlying': 'HSI', 'ticker': 'HSI:HSI',
        'market': 'global', 'issuers': ('18', '28'), 'session': 'hkex',
        'futures': 'HSI', 'note': 'ผู้ออก 18 KTX + 28 MACQ',
    },
    's50': {
        'name': 'SET50', 'underlying': 'S50', 'ticker': 'SET:SET50',
        'market': 'thailand', 'issuers': None, 'session': 'set',
        'futures': 'S50', 'note': 'ทุกผู้ออก',
    },
}

DW_ISSUERS       = DW_SERIES['dw']['issuers']   # kept for the HSI series
DW_MAX_SPREAD    = 8.0    # % of ask. Above this the round trip eats the edge
DW_MIN_DAYS      = 10     # calendar days to last trading day (theta cliff)
DW_SOFT_MONEY    = 5.0    # moneyness % beyond which we start penalising
DW_SIGNAL_ENTER  = 60     # |composite| needed to take a trade at all
DW_REQUIRE_ALIGN = True   # the 15m EMA stack has to agree with the score
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

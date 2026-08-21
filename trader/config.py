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
    'day':   3_500.0,   # SET stocks that are running today, flat by the close
    'cheap': 1_500.0,   # SET stocks < 3 THB, swing 1-5 days (capital is locked)
    'dw':        0.0,   # HSI DW — paused, see below
    's50':       0.0,   # SET50 DW — paused, see below
}

# A bucket at 0 THB is paused, not deleted. Nothing scans it and no card asks
# to be traded, but the journal keeps its history and --review still scores it,
# so pausing or resuming one is a number here rather than a code change.
#
# Seventy percent of the account is in the bucket that chases what is moving
# today and is flat by the close, because that is what this account is for.
# Waiting several days for a cheap stock to wake up is the smaller half now.
#
# Both DW buckets are paused rather than deleted: the engine and the thaidw
# feed still work, and DW may come back if the broker turns out to carry it.
# Until then a DW ticket pays 3-8% of spread before it is right about
# anything, which is the wrong instrument for chasing a move that is already
# under way.
BUCKET_ORDER = ('day', 'cheap', 'dw', 's50')

# Kept to 10 terminal cells: these are table cells as well as panel titles.
# The letters follow display order — the journal keys (dw, s50, cheap, day)
# are what history is written under and never change.
BUCKET_LABEL = {'day': 'A · หุ้นซิ่ง', 'cheap': 'B · หุ้นสวิง',
                'dw': 'C · DW HSI', 's50': 'D · DW S50'}


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
# one here. A 6% DW spread on an 800 THB ticket is 48 THB each way; taken
# daily that is 960 THB a month, 19% of the whole account, before being
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
# a 50 THB minimum turns an 800 THB position into a 12% round trip, which no
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
# BUCKET A — หุ้นซิ่ง, bought and sold inside the session
#
# The bet is momentum that is happening right now, not momentum that might
# start next week. So the screen asks four things in order, and all four have
# to be true at the same moment:
#
#   1. Is it moving?      change >= min_change, and not so far that the move
#                         is already spent (max_change)
#   2. Is anyone there?   RVOL >= min_rvol and min_value THB traded today —
#                         a runner you cannot get out of is not a runner
#   3. Is it still bid?   close in the top of today's range (min_range_pos).
#                         Same +6% day, closing at the high or at the low, is
#                         two completely different trades
#   4. Can it pay?        one tick <= max_tick_pct, so the grid does not eat
#                         the move before the move happens
#
#   tv_type        TradingView's `type` for the instrument
#   min_value      THB traded today, below which you cannot get out inside a day
#   max_price      price ceiling, further capped by what one board lot costs
#   max_tick_pct   one tick as % of price — the floor under every round trip
#   min_rvol       volume vs its own 10-day normal
#   min_change     % up on the day before it is worth looking at
#   max_change     % up on the day past which you are buying someone's exit
#   min_range_pos  0..1, where the price sits between today's low and high
#   tp1_atr        first target, as a multiple of today's ATR — sell half here
#   tp2_atr        second target for the half left running
#   sl_atr         stop, also in ATR. A stock that is running has a big ATR
#                  already, so this is wider than a quiet-market scalp would
#                  use: a stop inside the noise gets hit by the noise
# ------------------------------------------------------------------------------
DAY_MIN_VALUE    = 150_000_000.0  # a runner you cannot exit is not a runner
DAY_MAX_PRICE    = 60.0           # further capped by what one board lot costs
DAY_MAX_TICK_PCT = 0.8            # 0.8% a tick + 0.31% commission is the floor
DAY_MIN_RVOL     = 3.0            # today has to be 3x its own normal volume
DAY_MIN_CHANGE   = 3.0            # % up on the day — it has to be moving NOW
DAY_MAX_CHANGE   = 15.0           # past this you are the exit, not the entry
DAY_MIN_RANGE_POS = 0.6           # where in today's range it sits, 1.0 = at high
DAY_TP1_ATR      = 1.0            # first target — where half the position goes
DAY_TP2_ATR      = 2.0            # second target for the half that runs
DAY_SL_ATR       = 0.7            # stop, wide enough not to be noise

# SET halts a stock at +/- 30% of yesterday's close. On a runner that is not
# trivia: it is the highest price the day can print, so a target above it is a
# target that cannot be filled, and a stock already near it has nothing left
# to give today.
SET_CEILING_PCT  = 30.0

INTRADAY_SERIES = {
    'day': {
        'name': 'หุ้นซิ่ง', 'tv_type': 'stock', 'min_value': DAY_MIN_VALUE,
        'max_price': DAY_MAX_PRICE, 'max_tick_pct': DAY_MAX_TICK_PCT,
        'min_rvol': DAY_MIN_RVOL, 'min_change': DAY_MIN_CHANGE,
        'max_change': DAY_MAX_CHANGE, 'min_range_pos': DAY_MIN_RANGE_POS,
        'tp1_atr': DAY_TP1_ATR, 'tp2_atr': DAY_TP2_ATR, 'sl_atr': DAY_SL_ATR,
        'note': 'ไล่ตัวที่กำลังวิ่งวันนี้ ปิดก่อนตลาดปิด',
    },
}


def is_intraday(bucket: str) -> bool:
    """Buckets whose plan expires with the session — nothing here is a hold."""
    return bucket in DW_SERIES or bucket in INTRADAY_SERIES

# ------------------------------------------------------------------------------
# SESSIONS (Asia/Bangkok)
# ------------------------------------------------------------------------------
SESSIONS = {
    'dw_morning':   '08:35',   # HKEX 09:30 HKT + 5 min for the spread to settle
    'dw_afternoon': '12:05',   # HKEX 13:00 HKT
    'set_morning':  '10:15',   # SET has been open ~25 min — the day has a shape
    'set_midday':   '11:30',   # second look if the morning had nothing
    'set_afternoon': '14:45',  # what held its high all day is the real one
    'eod_close':    '15:45',   # close every day-trade position
}

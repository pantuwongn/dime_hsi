"""
Terminal graphics from the standard library only.

Everything here is width-aware: Thai text mixes zero-width combining vowels
and tone marks with normal letters, and a naive len() pads those cells twice,
which is why plain f-string tables drift out of alignment as soon as a Thai
header appears.
"""

import unicodedata

from . import ui
from .ui import c, ansi_enabled as _ansi

# Box drawing
TL, TR, BL, BR, H, V = '╭', '╮', '╰', '╯', '─', '│'
TEE_L, TEE_R = '├', '┤'


def dwidth(s: str) -> int:
    """Display width of a string in terminal cells."""
    w = 0
    for ch in s:
        # Thai above/below vowels and tone marks occupy no cell of their own.
        # unicodedata.combining() is not enough: U+0E31 MAI HAN AKAT reports a
        # combining class of 0 while still being a nonspacing mark, so the
        # general category is what has to be tested.
        if unicodedata.category(ch) in ('Mn', 'Me', 'Cf'):
            continue
        if unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += 2                                    # CJK, some emoji
        else:
            w += 1
    return w


def _visible(s: str) -> str:
    """Strip ANSI escapes so padding measures text, not colour codes."""
    out, i = [], 0
    while i < len(s):
        if s[i] == '\033':
            j = s.find('m', i)
            i = len(s) if j < 0 else j + 1
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def clip(s: str, width: int) -> str:
    """Truncate to `width` display cells, keeping ANSI codes balanced."""
    if dwidth(_visible(s)) <= width:
        return s
    out, w, i = [], 0, 0
    while i < len(s):
        if s[i] == '\033':
            j = s.find('m', i)
            j = len(s) - 1 if j < 0 else j
            out.append(s[i:j + 1])
            i = j + 1
            continue
        cw = dwidth(s[i])
        if w + cw > width - 1:
            break
        out.append(s[i])
        w += cw
        i += 1
    return ''.join(out) + '…' + ('\033[0m' if _ansi() else '')


def pad(s: str, width: int, align: str = '<') -> str:
    """Pad to `width` display cells, ignoring ANSI colour codes."""
    gap = width - dwidth(_visible(s))
    if gap <= 0:
        return s
    if align == '>':
        return ' ' * gap + s
    if align == '^':
        left = gap // 2
        return ' ' * left + s + ' ' * (gap - left)
    return s + ' ' * gap


# ------------------------------------------------------------------------------
# PANELS
# ------------------------------------------------------------------------------

def panel(title: str, lines: list, width: int = 92, tone: str = 'cyan') -> None:
    """A box whose border carries the verdict: green box == long, red == short."""
    head = f'{TL}{H} {title} '
    fill = H * max(0, width - dwidth(head) - 1)
    print(c(f'{TL}{H} ', tone) + c(title, 'bold', tone) + c(' ' + fill + TR, tone))
    for ln in lines:
        print(c(V, tone) + ' ' + pad(clip(ln, width - 3), width - 3) + c(V, tone))
    print(c(BL + H * (width - 2) + BR, tone))


_BADGE_TONE = {
    'call':  ('on_green',  'ซื้อ CALL DW', '▲'),
    'put':   ('on_red',    'ซื้อ PUT DW',  '▼'),
    'buy':   ('on_green',  'ซื้อ',          '▲'),
    'wait':  ('on_yellow', 'ไม่เข้า',        '■'),
    'none':  ('on_grey',   'ไม่มีของให้ซื้อ',  '✕'),
}


def big_badge(kind: str, extra: str = '', width: int = 30) -> list:
    """
    Three lines of solid background colour. A one-word verdict has to survive
    being glanced at on a phone screenshot at 7am, which a coloured word in a
    wall of text does not.
    """
    bg, label, mark = _BADGE_TONE[kind]
    text = f'{mark}  {label}'
    if extra:
        text += f'   {extra}'
    width = max(width, dwidth(text) + 6)
    body = pad(f'   {text}', width)
    if not ui.ansi_enabled():
        return ['', f'  >>> {text.strip()} <<<', '']
    blank = c(' ' * width, bg)
    return ['  ' + blank,
            '  ' + c(body, bg, 'black', 'bold'),
            '  ' + blank]


def divider(width: int = 92, label: str = '') -> str:
    if not label:
        return c(H * (width - 3), 'dim')
    left = c(H * 2 + ' ', 'dim')
    text = c(label, 'dim')
    used = dwidth(_visible(left + text)) + 1
    return left + text + ' ' + c(H * max(0, width - 3 - used), 'dim')


# ------------------------------------------------------------------------------
# GAUGES AND BARS
# ------------------------------------------------------------------------------

_BLOCKS = ' ▏▎▍▌▋▊▉█'


def bar(value: float, vmax: float, width: int = 14, tone: str = 'cyan') -> str:
    """Horizontal bar with sub-cell resolution."""
    if value is None or vmax <= 0:
        return c('·' * width, 'dim')
    frac = max(0.0, min(1.0, value / vmax))
    full = int(frac * width)
    rem = int((frac * width - full) * 8)
    s = '█' * full + (_BLOCKS[rem] if rem and full < width else '')
    return c(s, tone) + c('·' * (width - dwidth(s)), 'dim')


def signed_gauge(value: float, vmax: float = 100.0, width: int = 30,
                 enter: float = None) -> str:
    """
    A centre-zero gauge: bearish fills left of centre, bullish fills right.
    `enter` marks the threshold the signal has to clear to become a trade,
    so 'close but not enough' is visible instead of just being a number.
    """
    half = width // 2
    cells = [' '] * width
    frac = max(-1.0, min(1.0, (value or 0.0) / vmax))
    n = int(abs(frac) * half)

    if frac >= 0:
        for i in range(half, min(width, half + n)):
            cells[i] = '█'
        tone = 'bright_green'
    else:
        for i in range(max(0, half - n), half):
            cells[i] = '█'
        tone = 'bright_red'

    body = ''.join(cells)
    left, right = body[:half], body[half:]
    out = c(left.replace(' ', '·'), tone if frac < 0 else 'dim')
    out += c('┃', 'bold')
    out += c(right.replace(' ', '·'), tone if frac >= 0 else 'dim')

    if enter is not None:
        e = int(enter / vmax * half)
        marks = [' '] * (width + 1)
        for pos in (half - e, half + e + 1):
            if 0 <= pos < len(marks):
                marks[pos] = '▲'
        out += '\n' + c(''.join(marks), 'dim')
    return out


def rsi_gauge(rsi: float, width: int = 20) -> str:
    """RSI 0-100 with the 30/70 bands shaded and a marker at the value."""
    if rsi is None:
        return c('·' * width, 'dim')
    pos = int(max(0.0, min(100.0, rsi)) / 100.0 * (width - 1))
    cells = []
    for i in range(width):
        v = i / (width - 1) * 100
        if i == pos:
            cells.append(c('●', 'bright_green' if 45 <= rsi <= 72
                           else 'bright_red' if rsi > 72 or rsi < 30 else 'yellow'))
        elif v < 30 or v > 70:
            cells.append(c('▒', 'dim'))
        else:
            cells.append(c('─', 'dim'))
    return ''.join(cells)


def range_position(low: float, high: float, value: float, width: int = 28) -> str:
    """Where the current price sits inside the day's range."""
    if None in (low, high, value) or high <= low:
        return c('·' * width, 'dim')
    frac = (value - low) / (high - low)
    pos = int(max(0.0, min(1.0, frac)) * (width - 1))
    tone = 'bright_green' if frac > 0.66 else 'bright_red' if frac < 0.33 else 'yellow'
    return (c('└', 'dim') + c('─' * pos, 'dim') + c('●', tone)
            + c('─' * (width - pos - 2), 'dim') + c('┘', 'dim'))


def rr_bar(sl: float, entry: float, tp: float, width: int = 34) -> str:
    """
    Stop / entry / target drawn to scale, so a lopsided trade looks lopsided.
    """
    if None in (sl, entry, tp) or tp <= sl:
        return c('·' * width, 'dim')
    span = tp - sl
    e = int((entry - sl) / span * width)
    e = max(1, min(width - 1, e))
    return (c('▄' * e, 'red') + c('▄' * (width - e), 'green'))


def sparkline(values: list, width: int = 24) -> str:
    """Braille-free sparkline; returns dots when there is not enough history."""
    vals = [v for v in (values or []) if v is not None]
    if len(vals) < 2:
        return c('·' * width, 'dim')
    vals = vals[-width:]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return c('─' * len(vals), 'dim')
    chars = '▁▂▃▄▅▆▇█'
    tone = 'bright_green' if vals[-1] >= vals[0] else 'bright_red'
    return c(''.join(chars[int((v - lo) / (hi - lo) * (len(chars) - 1))]
                     for v in vals), tone)


def dw_ladder(bid: float, ask: float, tp: float, sl: float, width: int = 46) -> str:
    """
    The DW's own price axis: stop, bid, ask (your fill), and target, to scale.
    The gap between bid and ask is the money you hand over on entry — seeing it
    next to the target is the whole point.
    """
    pts = [p for p in (sl, bid, ask, tp) if p is not None]
    if len(pts) < 4:
        return c('·' * width, 'dim')
    lo, hi = min(pts), max(pts)
    if hi <= lo:
        return c('·' * width, 'dim')

    def at(p):
        return max(0, min(width - 1, int((p - lo) / (hi - lo) * (width - 1))))

    row = [c('·', 'dim')] * width
    for i in range(at(bid), at(ask) + 1):
        row[i] = c('▓', 'yellow')                 # the spread you pay
    row[at(sl)] = c('┫', 'bright_red')
    row[at(tp)] = c('┣', 'bright_green')
    row[at(ask)] = c('◆', 'bold')
    return ''.join(row)

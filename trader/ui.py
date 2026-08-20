"""Plain-ANSI terminal rendering. No third-party UI dependency."""

import os
import sys

_TTY = sys.stdout.isatty() and os.environ.get('NO_COLOR') is None


def force_color(on: bool = True) -> None:
    """Keep ANSI on when piping into `less -R` or a colour-aware log."""
    global _TTY
    _TTY = on

_C = {
    'reset': '\033[0m', 'bold': '\033[1m', 'dim': '\033[2m',
    'black': '\033[30m', 'white': '\033[97m',
    'red': '\033[31m', 'green': '\033[32m', 'yellow': '\033[33m',
    'blue': '\033[34m', 'magenta': '\033[35m', 'cyan': '\033[36m',
    'bright_green': '\033[92m', 'bright_red': '\033[91m',
    'bright_yellow': '\033[93m', 'bright_cyan': '\033[96m',
    # backgrounds — for badges that must be impossible to misread
    'on_green': '\033[42m', 'on_red': '\033[41m', 'on_yellow': '\033[43m',
    'on_blue': '\033[44m', 'on_magenta': '\033[45m', 'on_grey': '\033[100m',
}


def ansi_enabled() -> bool:
    return _TTY


def c(text, *styles) -> str:
    if not _TTY:
        return str(text)
    return ''.join(_C[s] for s in styles if s in _C) + str(text) + _C['reset']


def rule(title: str = '', width: int = 96) -> None:
    if not title:
        print(c('─' * width, 'dim'))
        return
    pad = width - len(title) - 3
    print(c('─── ', 'dim') + c(title, 'bold', 'cyan') + ' ' + c('─' * max(0, pad - len(title)), 'dim'))


def table(headers: list, rows: list, aligns: str = '') -> None:
    """
    headers: [(title, width), ...]
    rows:    list of lists of already-formatted strings
    aligns:  one char per column, '<' or '>' (default '>' except column 0)
    """
    if not aligns:
        aligns = '<' + '>' * (len(headers) - 1)
    head = ''.join(f'{t:{aligns[i]}{w}}' for i, (t, w) in enumerate(headers))
    print(c(head, 'bold'))
    print(c('─' * len(head), 'dim'))
    for r in rows:
        print(''.join(f'{str(v):{aligns[i]}{headers[i][1]}}' for i, v in enumerate(r)))


def kv(label: str, value, note: str = '') -> None:
    line = f'  {label:<22}{value}'
    if note:
        line += c(f'   {note}', 'dim')
    print(line)


def warn(msg: str) -> None:
    print(c(f'  ⚠  {msg}', 'yellow'))


def fail(msg: str) -> None:
    print(c(f'  ✗  {msg}', 'bright_red'))


def fmt(x, dp: int = 2, dash: str = '-') -> str:
    """Format a number, but never disguise a missing value as a real one."""
    if x is None:
        return dash
    try:
        if x != x:          # NaN
            return dash
        return f'{x:,.{dp}f}'
    except (TypeError, ValueError):
        return dash

#!/usr/bin/env python3
"""
Layout regression check: every rendered line must fit its panel exactly.

Terminal boxes break silently — a column added months from now pushes the
right border out on one row and nothing errors. This asserts on real live
output instead.
"""

import io
import sys
from contextlib import redirect_stdout

import run
from trader import ui
from trader.graph import dwidth, _visible


def render(color: bool) -> list:
    ui.force_color(color)
    buf = io.StringIO()
    with redirect_stdout(buf):
        run.header()
        run.show_dw(False)
        run.show_cheap(False)
        run.show_dr(False)
    return [ln for ln in buf.getvalue().split('\n') if ln.strip()]


if __name__ == '__main__':
    # Both paths matter: badges and bars take a different branch when colour is
    # off, so checking only the piped output would miss the one you actually see.
    lines = render(color=True) + render(color=False)
    wrong = [(dwidth(_visible(ln)), _visible(ln)) for ln in lines
             if dwidth(_visible(ln)) != run.W]
    clipped = [_visible(ln) for ln in lines if '…' in ln]

    print(f'ตรวจ {len(lines)} บรรทัด')
    for w, ln in wrong:
        print(f'  ✗ กว้าง {w} (ควรเป็น {run.W}): {ln[:78]}')
    for ln in clipped:
        print(f'  ✗ โดน clip: {ln[:78]}')
    ok = not wrong and not clipped
    print('  ✓ ทุกบรรทัดพอดีกรอบ' if ok else '')
    sys.exit(0 if ok else 1)

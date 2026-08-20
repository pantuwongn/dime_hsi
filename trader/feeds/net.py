"""
One retry policy, shared by both feeds.

The tool is used once in the morning and then you leave. A single TCP reset at
08:35 used to take a whole bucket down for the day, with no second chance
short of noticing and running it again — which is the one thing the workflow
assumes you will not do.

Retries are bounded by a wall-clock deadline rather than a count, because the
serverless function has a hard 20s budget (vercel.json) and three buckets run
concurrently inside it. A retry policy that can outlive the request it serves
is not resilience, it is a timeout with extra steps.
"""

import random
import time
import urllib.error


class FeedError(RuntimeError):
    """Raised when a feed cannot be trusted — never swallowed silently."""


TIMEOUT = 8.0        # one attempt
DEADLINE = 14.0      # everything, retries included
ATTEMPTS = 3

# Worth trying again: the server said "busy" or the connection died mid-flight.
# 403 is not here on purpose — Imperva has decided about us, and hammering it
# spends the request budget to be told the same thing three times.
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def fetch(attempt, label: str):
    """
    Call `attempt(timeout)` until it returns, the deadline passes, or the
    failure is one that will not change by asking again.
    """
    started = time.monotonic()
    last = None

    for i in range(ATTEMPTS):
        left = DEADLINE - (time.monotonic() - started)
        if left <= 0.5:
            break
        try:
            return attempt(min(TIMEOUT, left))
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}: {e.reason}'
            if e.code not in _RETRY_STATUS:
                raise FeedError(f'{label} {last}') from e
        except Exception as e:                    # timeout, reset, DNS, bad JSON
            last = f'{type(e).__name__}: {e}'

        if i < ATTEMPTS - 1:
            # Jitter so two buckets that failed together do not retry together.
            time.sleep(min(0.4 * (2 ** i) + random.uniform(0, 0.2),
                           max(0.0, DEADLINE - (time.monotonic() - started))))

    raise FeedError(f'{label} ล้มเหลวหลังลอง {ATTEMPTS} ครั้ง — {last}')

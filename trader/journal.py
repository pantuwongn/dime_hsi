"""
Append-only trade journal.

Every recommendation the tool prints is also written here, so that after a
few weeks you can measure whether the signal actually made money instead of
relying on memory.
"""

import json
import os
from datetime import datetime, timezone, timedelta

BKK = timezone(timedelta(hours=7))
PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'journal.jsonl')


def now_bkk() -> datetime:
    return datetime.now(BKK)


def record(bucket: str, payload: dict, path: str = PATH) -> None:
    entry = {'ts': now_bkk().isoformat(timespec='seconds'), 'bucket': bucket}
    entry.update(payload)
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')


def load(path: str = PATH) -> list:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out

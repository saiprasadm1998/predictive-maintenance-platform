"""Live replay: the simulator plays the OT gateway (plan 1.4 -> 1.2).

Sends one batch per gateway source per minute to POST /api/v1/ingest/samples. Starting
in the past catches up at `speed` minutes per real minute, then continues in real time
(timestamps are never sent ahead of the clock, which ingestion would reject).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from pmp.demo.generator import PlantSimulator, batches_for_minute

Poster = Callable[[str, str, dict[str, object]], tuple[int, dict[str, object]]]


def post_json(url: str, key: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"ApiKey {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        body = error.read()
        return error.code, json.loads(body) if body else {}


@dataclass
class ReplayStats:
    minutes: int = 0
    accepted: int = 0
    rejected: int = 0
    failed_batches: int = 0


def replay(
    simulator: PlantSimulator,
    *,
    url: str,
    key: str,
    start: datetime | None = None,
    speed: float = 1.0,
    minutes: int | None = None,
    post: Poster = post_json,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> ReplayStats:
    stats = ReplayStats()
    t = float(np.floor((start.timestamp() if start else clock()) / 60.0) * 60.0)
    while minutes is None or stats.minutes < minutes:
        ahead = t - clock()
        if ahead > 0:
            sleep(ahead)  # caught up: continue in real time
        frame = simulator.samples_at(np.array([t]))
        for batch in batches_for_minute(frame):
            status, body = post(url, key, batch)
            if status == 202:
                stats.accepted += int(body.get("accepted", 0))  # type: ignore[call-overload]
                stats.rejected += len(body.get("rejected", []))  # type: ignore[arg-type]
            else:
                stats.failed_batches += 1
                log(f"{batch['source']}: HTTP {status} {body.get('title', '')}")
        stats.minutes += 1
        stamp = datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M")
        log(f"{stamp} UTC  sent {len(frame)} samples")
        t += 60.0
        if t <= clock():  # still catching up
            sleep(60.0 / speed)
    return stats

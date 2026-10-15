"""Turn the model and scenarios into samples (long format: ts, source, tag, value, quality)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from functools import partial

import numpy as np
import pandas as pd

from pmp.demo import scenarios
from pmp.demo.model import (
    DemoTag,
    FloatArray,
    anchor_seconds,
    base_signal,
    load_profile,
    minute_grid,
    quiet_period_start,
)

DEFAULT_SEED = 42
COLUMNS = ["ts", "source", "tag", "value", "quality"]


def default_anchor() -> datetime:
    """Today 00:00 UTC: history ends here and the scenarios are timed from it."""
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class PlantSimulator:
    def __init__(
        self, tags: Sequence[DemoTag], *, seed: int = DEFAULT_SEED, anchor: datetime | None = None
    ) -> None:
        if not tags:
            raise ValueError("No tags to simulate: import the demo registry first")
        self.tags = list(tags)
        self.seed = seed
        self.anchor = anchor or default_anchor()
        self._anchor_s = anchor_seconds(self.anchor)
        self._quiet_s = quiet_period_start(self.anchor)

    def samples_at(self, t: FloatArray) -> pd.DataFrame:
        """All samples the gateway would send at the given epoch seconds."""
        frames = []
        loads: dict[str, FloatArray] = {}
        for tag in self.tags:
            if tag.asset_code not in loads:
                loads[tag.asset_code] = load_profile(self.seed, tag.asset_code, t, self._quiet_s)
            value = base_signal(self.seed, tag, t, loads[tag.asset_code])
            effects = scenarios.apply(
                self.seed, tag, t, value, self._anchor_s, partial(self._healthy, tag)
            )
            keep = effects.sent
            if not keep.any():
                continue
            frames.append(
                pd.DataFrame(
                    {
                        "ts": pd.to_datetime(t[keep], unit="s", utc=True),
                        "source": tag.source,
                        "tag": tag.source_name,
                        "value": np.round(effects.value[keep], 4),
                        "quality": np.where(effects.bad[keep], "Bad", "Good"),
                    }
                )
            )
        if not frames:
            return pd.DataFrame(columns=COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def _healthy(self, tag: DemoTag, t: FloatArray) -> FloatArray:
        load = load_profile(self.seed, tag.asset_code, t, self._quiet_s)
        return base_signal(self.seed, tag, t, load)

    def samples_between(self, start: datetime, end: datetime) -> pd.DataFrame:
        return self.samples_at(minute_grid(start, end))

    def sources(self) -> list[str]:
        return sorted({t.source for t in self.tags})


def batches_for_minute(frame: pd.DataFrame) -> Iterable[dict[str, object]]:
    """Group one minute of samples into ingestion payloads, one per gateway source."""
    for source, group in frame.groupby("source", sort=True):
        yield {
            "source": str(source),
            "samples": [
                {"tag": tag, "ts": ts.isoformat(), "v": float(v), "q": q}
                for ts, tag, v, q in zip(
                    group["ts"], group["tag"], group["value"], group["quality"], strict=True
                )
            ],
        }

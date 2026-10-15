"""Generate the FR-ING-03 acceptance file: 12 months of 1-minute data for 50 tags.

Wide Parquet (ts + one column per tag), using the first 50 Site A tags of the demo
registry (data/demo/registry/tags.csv). Values are smooth daily cycles plus noise inside
each tag's instrument range; realistic plant behaviour comes with the seeder in 1.4.
Written one month at a time to keep memory small. Skips work if the file exists.

    uv run python tools/make_history_file.py ../data/perf/history_12m_50tags.parquet
"""

from __future__ import annotations

import csv
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

TAGS_CSV = Path(__file__).resolve().parents[2] / "data" / "demo" / "registry" / "tags.csv"
N_TAGS = 50
DAYS = 365


def main(out: Path) -> None:
    if out.exists():
        print(f"{out} exists; delete it to regenerate")
        return
    with TAGS_CSV.open() as handle:
        tags = [row for row in csv.DictReader(handle) if row["source"] == "gw-site-a-01"]
    tags = tags[:N_TAGS]
    if len(tags) < N_TAGS:
        sys.exit(f"Only {len(tags)} Site A tags in the demo registry")

    rng = np.random.default_rng(2026)
    end = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(days=1)
    start = end - timedelta(days=DAYS)
    out.parent.mkdir(parents=True, exist_ok=True)
    writer: pq.ParquetWriter | None = None
    month_start = start
    while month_start < end:
        month_end = min(month_start + timedelta(days=30), end)
        ts = pd.date_range(month_start, month_end, freq="min", inclusive="left", tz="UTC")
        hours = (ts - ts[0]).total_seconds().to_numpy() / 3600.0
        columns = {"ts": pa.array(ts)}
        for tag in tags:
            lo, hi = float(tag["range_lo"]), float(tag["range_hi"])
            mid, span = lo + 0.5 * (hi - lo), 0.1 * (hi - lo)
            daily = np.sin(2 * np.pi * hours / 24.0)
            columns[tag["source_name"]] = mid + span * daily + rng.normal(0, 0.01 * span, len(ts))
        table = pa.table(columns)
        if writer is None:
            writer = pq.ParquetWriter(out, table.schema)
        writer.write_table(table)
        month_start = month_end
    assert writer is not None
    writer.close()
    rows = pq.ParquetFile(out).metadata.num_rows
    print(f"Wrote {out}: {rows:,} rows x {N_TAGS} tags = {rows * N_TAGS:,} samples")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

"""Coverage gate for the analytics modules (NFR-MAIN-01: at least 80% line coverage).

Run after `pytest --cov=pmp`. Coverage is measured for the whole package, so files
no test imports still count as uncovered. The gate passes while the analytics
modules contain no code yet.
"""

from __future__ import annotations

import sys

import coverage
from coverage.exceptions import NoDataError

ANALYTICS = ("dataquality", "modelling", "scoring", "alerting", "diagnostics", "prognostics")
THRESHOLD = 80.0


def main() -> int:
    cov = coverage.Coverage()
    cov.load()
    include = [f"*/pmp/{module}/*" for module in ANALYTICS]
    print(f"Coverage gate: analytics modules must reach {THRESHOLD:.0f}%")
    try:
        total = cov.report(include=include, show_missing=True, skip_empty=True)
    except NoDataError:
        print("No analytics code to measure yet; gate passes.")
        return 0
    if total < THRESHOLD:
        print(f"FAILED: analytics coverage {total:.1f}% is below {THRESHOLD:.0f}%")
        return 1
    print(f"Passed: analytics coverage {total:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())

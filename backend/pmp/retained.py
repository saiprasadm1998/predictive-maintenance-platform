"""What the nightly clean-up looks after, gathered from the modules that own it (ARC §4:
core never names another module's tables)."""

from __future__ import annotations

from pathlib import Path

from pmp.alerting import ALERT_RECORDS
from pmp.cases import CASE_RECORDS
from pmp.core import RetainedFiles, RetainedRecords, RetentionPlan
from pmp.ingestion import SAMPLES
from pmp.notifications import NOTIFICATION_RECORDS
from pmp.prognostics import FORECAST_RECORDS
from pmp.scoring import SCORE_TABLES

AUDIT_RECORDS = RetainedRecords("audit", "audit_log", "ts")


def retention_plan(artefact_dir: Path) -> RetentionPlan:
    return RetentionPlan(
        tables=(SAMPLES,),
        scores=SCORE_TABLES,
        records=(
            FORECAST_RECORDS,
            ALERT_RECORDS,
            CASE_RECORDS,
            NOTIFICATION_RECORDS,
            AUDIT_RECORDS,
        ),
        files=(RetainedFiles("uploads", Path(artefact_dir) / "uploads"),),
    )

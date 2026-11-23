"""MQTT subscription (PHI-001 §5.1): topic to source, one transaction per message, and every
refused message or sample kept in the reject log with its reason."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest

from pmp.ingestion import list_rejections
from pmp.ingestion.mqtt import BrokerConfig, handle_message, source_of
from tests.integration.test_ingest_api import SOURCE, _count, setup  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration
CONFIG = BrokerConfig(url="mqtts://broker.test:8883")
TOPIC = f"pmp/v1/{SOURCE}/samples"


def test_the_source_is_read_from_the_topic() -> None:
    assert source_of(TOPIC, "pmp/v1") == SOURCE
    assert source_of("pmp/v1/a/b/samples", "pmp/v1") is None
    assert source_of("other/gw/samples", "pmp/v1") is None
    assert CONFIG.topic == "pmp/v1/+/samples"


def test_a_message_is_stored_and_a_bad_one_is_logged(setup: dict[str, Any]) -> None:  # noqa: F811
    now = setup["now"]
    body = {
        "source": SOURCE,
        "samples": [
            {"tag": "K101.TI1012.PV", "ts": now.isoformat(), "v": 78.4, "q": "Good"},
            {"tag": "K101.TI1012.PV", "ts": (now + timedelta(hours=1)).isoformat(), "v": 1},
        ],
    }
    late = timedelta(days=7)
    accepted, rejected = handle_message(
        setup["db"], CONFIG, TOPIC, json.dumps(body).encode(), now=now, late_window=late
    )
    assert (accepted, rejected) == (1, 1)  # the second sample is more than 5 min ahead
    assert _count(setup) == 1
    assert handle_message(setup["db"], CONFIG, TOPIC, b"not json", now=now, late_window=late) == (
        0,
        1,
    )
    with setup["db"].session() as s:
        reasons = [r.reason for r in list_rejections(s)]
    assert "malformed" in reasons
    assert len(reasons) >= 2

"""Detector registry: built-ins and `pmp.algorithms` entry-point plug-ins (ADR-09)."""

from __future__ import annotations

from collections.abc import Iterator
from importlib.metadata import EntryPoint

import pandas as pd
import pytest

from pmp import cli
from pmp.core import get_settings
from pmp.modelling import (
    DEFAULT_DETECTOR,
    ENTRY_POINT_GROUP,
    DetectorError,
    MedianDetector,
    available_detectors,
    get_detector,
)
from pmp.modelling.algorithms import registry


class GoodPlugin(MedianDetector):
    name = "good"
    version = "1.2.0"


class BadPlugin(MedianDetector):
    name = "bad"
    version = "0.0.1"

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        return super().predict(X).iloc[:5]


def _point(name: str, target: str) -> EntryPoint:
    return EntryPoint(name=name, value=target, group=ENTRY_POINT_GROUP)


@pytest.fixture
def plugins(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    here = __name__
    points = [
        _point("good", f"{here}:GoodPlugin"),
        _point("bad", f"{here}:BadPlugin"),
        _point("misnamed", f"{here}:GoodPlugin"),
        _point("missing", "no_such_package.detector:Thing"),
        _point("median", "evil_pkg:Median"),  # tries to replace a built-in
    ]
    monkeypatch.setattr(registry, "_plugin_entry_points", lambda: points)
    available_detectors(refresh=True)
    yield
    monkeypatch.undo()
    available_detectors(refresh=True)


def test_the_placeholder_is_the_default_and_enabled() -> None:
    assert DEFAULT_DETECTOR == "median"
    assert get_detector() is MedianDetector
    median = next(d for d in available_detectors() if d.name == "median")
    assert median.enabled
    assert median.source == "built-in"


@pytest.mark.usefixtures("plugins")
def test_plugins_that_pass_are_enabled_and_others_refused() -> None:
    found = {d.name: d for d in available_detectors()}
    assert set(found) == {"median", "good", "bad", "misnamed", "missing"}
    assert found["good"].enabled
    assert found["good"].version == "1.2.0"
    assert get_detector("good") is GoodPlugin
    assert not found["bad"].enabled
    assert any("output shape" in f for f in found["bad"].failures)
    assert found["misnamed"].failures == ["declares name 'good', registered as 'misnamed'"]
    assert found["missing"].failures[0].startswith("could not be loaded")
    assert get_detector("median") is MedianDetector  # a plug-in cannot replace a built-in


@pytest.mark.usefixtures("plugins")
@pytest.mark.parametrize(
    ("name", "message"), [("bad", "failed the contract"), ("missing", "failed")]
)
def test_refused_detectors_cannot_be_used(name: str, message: str) -> None:
    with pytest.raises(DetectorError, match=message):
        get_detector(name)


def test_unknown_detectors_are_refused() -> None:
    with pytest.raises(DetectorError, match="No detector named 'aakr'"):
        get_detector("aakr")


@pytest.mark.usefixtures("plugins")
def test_algorithms_list_shows_each_detector(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PMP_DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    get_settings.cache_clear()
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["algorithms", "list"])
    get_settings.cache_clear()
    out = capsys.readouterr().out
    assert exit_info.value.code == 1  # some plug-ins were refused
    assert "median" in out
    assert "enabled" in out
    assert "REFUSED" in out

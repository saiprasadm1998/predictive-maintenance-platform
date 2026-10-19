"""Alert rule checks (UCS §6.6, FR-ALM-01)."""

from __future__ import annotations

import pytest

from pmp.alerting import AlertRuleError, AlertRuleSpec, RuleKind


def test_defaults_follow_the_spec() -> None:
    rule = AlertRuleSpec(RuleKind.DI, 15, 25)
    assert (rule.persistence_n, rule.persistence_m) == (3, 5)
    assert (rule.on_delay_s, rule.deadband, rule.clear_cycles) == (0, 0.10, 5)
    assert rule.enabled
    assert rule.key == (RuleKind.DI, None)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"kind": RuleKind.DI, "tag_id": 3}, "DI rule has no tag"),
        ({"kind": RuleKind.SENSOR}, "sensor rule needs one"),
        ({"warning": 25, "alert": 15}, "warning < alert"),
        ({"warning": 0}, "warning < alert"),
        ({"warning": float("nan")}, "must be numbers"),
        ({"persistence_n": 6}, "1 <= n <= m"),
        ({"persistence_n": 0}, "1 <= n <= m"),
        ({"on_delay_s": -1}, "on-delay"),
        ({"deadband": 1.0}, "deadband"),
        ({"deadband": -0.1}, "deadband"),
        ({"clear_cycles": 0}, "at least 1 cycle"),
    ],
)
def test_invalid_rules_are_refused(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {"kind": RuleKind.DI, "warning": 15.0, "alert": 25.0}
    values.update(kwargs)
    with pytest.raises(AlertRuleError, match=message):
        AlertRuleSpec(**values)  # type: ignore[arg-type]

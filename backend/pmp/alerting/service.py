"""Alert rule services: set and list a model's rules (FR-ALM-01, UC-05 step 9).

Rules belong to the model, not to a version, so the active limits stay editable after a
version is Validated (implementation plan, decision on alert limits). Every created,
changed or removed rule is audited.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pmp.alerting.domain import AlertRuleError, AlertRuleSpec, RuleKind
from pmp.alerting.models import AlertRule
from pmp.core import Actor, Permission, audit_change, authorize
from pmp.modelling import ModelError, asset_path, get_model_by_id

_FIELDS = (
    "warning",
    "alert",
    "persistence_n",
    "persistence_m",
    "on_delay_s",
    "deadband",
    "clear_cycles",
    "enabled",
)


@dataclass(frozen=True)
class AlertRuleView:
    id: int
    model_id: int
    spec: AlertRuleSpec


def _spec(row: AlertRule) -> AlertRuleSpec:
    return AlertRuleSpec(
        kind=RuleKind(row.kind),
        tag_id=row.tag_id,
        **{name: getattr(row, name) for name in _FIELDS},
    )


def _snapshot(spec: AlertRuleSpec) -> dict[str, Any]:
    data = asdict(spec)
    data["kind"] = spec.kind.value
    return data


def list_alert_rules(session: Session, model_id: int) -> list[AlertRuleView]:
    """The DI rule first, then sensor rules by tag."""
    rows = session.scalars(
        select(AlertRule)
        .where(AlertRule.model_id == model_id)
        .order_by(AlertRule.kind, AlertRule.tag_id)
    ).all()
    return [AlertRuleView(r.id, r.model_id, _spec(r)) for r in rows]


def set_alert_rules(
    session: Session, actor: Actor, model_id: int, rules: Sequence[AlertRuleSpec]
) -> list[AlertRuleView]:
    """Replace a model's rules: create, change or remove so they match `rules`."""
    try:
        model = get_model_by_id(session, model_id)
    except ModelError as error:
        raise AlertRuleError(str(error)) from None
    authorize(
        actor,
        Permission.MODELS,
        asset_path(session, model.asset_code),
        what=f"alert limits on {model.asset_code}",
    )
    keys = [r.key for r in rules]
    if sum(1 for r in rules if r.kind is RuleKind.DI) > 1:
        raise AlertRuleError("A model has at most one DI rule")
    if len(set(keys)) != len(keys):
        raise AlertRuleError("Two sensor rules for the same tag")
    sensors = {s.tag_id: s.source_name for s in model.latest.sensors}
    foreign = [r.tag_id for r in rules if r.kind is RuleKind.SENSOR and r.tag_id not in sensors]
    if foreign:
        raise AlertRuleError(f"Sensor rules on tags that are not model sensors: {foreign}")

    existing = {
        (RuleKind(r.kind), r.tag_id): r
        for r in session.scalars(select(AlertRule).where(AlertRule.model_id == model_id)).all()
    }
    wanted = {r.key: r for r in rules}

    def audit(action: str, key: tuple[RuleKind, int | None], before: Any, after: Any) -> None:
        kind, tag_id = key
        entity_id = f"{model_id}:{kind.value}" + (f":{tag_id}" if tag_id is not None else "")
        audit_change(
            session,
            actor,
            entity="alert_rule",
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
        )

    for key, row in existing.items():
        if key not in wanted:
            audit("remove", key, _snapshot(_spec(row)), None)
            session.delete(row)
    for key, spec in wanted.items():
        current = existing.get(key)
        if current is None:
            session.add(
                AlertRule(
                    model_id=model_id,
                    kind=spec.kind.value,
                    tag_id=spec.tag_id,
                    **{name: getattr(spec, name) for name in _FIELDS},
                )
            )
            audit("create", key, None, _snapshot(spec))
        elif _spec(current) != spec:
            before = _snapshot(_spec(current))
            for name in _FIELDS:
                setattr(current, name, getattr(spec, name))
            audit("update", key, before, _snapshot(spec))
    session.flush()
    return list_alert_rules(session, model_id)


def require_di_rule(session: Session, model_id: int) -> None:
    """Deploy check: the Health Score needs the DI alert limit (DIref = 2 x alert)."""
    rules = list_alert_rules(session, model_id)
    if not any(r.spec.kind is RuleKind.DI and r.spec.enabled for r in rules):
        raise ModelError(
            "Set the DI alert rule first: the Health Score is measured against its alert limit"
        )

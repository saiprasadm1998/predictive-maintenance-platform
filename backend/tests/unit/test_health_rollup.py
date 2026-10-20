"""Health roll-up rules (UCS §6.5, FR-HLT-01, plan 4.3), on a demo-shaped hierarchy."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from pmp.registry import AssetLevel, AssetView, Criticality
from pmp.scoring import Band, ModelHealth, NodeHealth, RuntimeStatus, roll_up, worst_band

L = AssetLevel
# code, level, parent
TREE = [
    ("PLANT", L.ENTERPRISE, None),
    ("SITE-A", L.SITE, "PLANT"),
    ("U-100", L.UNIT, "SITE-A"),
    ("K-101", L.EQUIPMENT, "U-100"),
    ("P-101", L.EQUIPMENT, "U-100"),
    ("P-102", L.EQUIPMENT, "U-100"),
    ("U-200", L.UNIT, "SITE-A"),
    ("E-201", L.EQUIPMENT, "U-200"),
    ("SITE-B", L.SITE, "PLANT"),
    ("U-300", L.UNIT, "SITE-B"),
    ("C-301", L.EQUIPMENT, "U-300"),
]
IDS = {code: i + 1 for i, (code, _, _) in enumerate(TREE)}


def assets() -> list[AssetView]:
    out = []
    for code, level, parent in TREE:
        path = code if parent is None else f"{_path(parent)}.{code}"
        out.append(
            AssetView(
                id=IDS[code],
                code=code,
                name=code,
                level=level,
                path=path,
                parent_id=IDS[parent] if parent else None,
                criticality=Criticality.A if level is L.EQUIPMENT else None,
                asset_type_code=None,
                description="",
            )
        )
    return out


def _path(code: str) -> str:
    parent = next(p for c, _, p in TREE if c == code)
    return code if parent is None else f"{_path(parent)}.{code}"


def model(code: str, band: Band, health: float | None = None, n: int = 1) -> ModelHealth:
    status = RuntimeStatus.RUNNING if health is not None else RuntimeStatus.INSUFFICIENT_DATA
    return ModelHealth(IDS[code] * 10 + n, IDS[code], f"m{n}", band, health, status)


def nodes(*models: ModelHealth) -> dict[str, NodeHealth]:
    (root,) = roll_up(assets(), models)
    return {n.code: n for n in root.walk()}


def test_band_order() -> None:
    assert worst_band([Band.HEALTHY, Band.UNKNOWN]) is Band.UNKNOWN
    assert worst_band([Band.UNKNOWN, Band.WATCH]) is Band.WATCH
    assert worst_band([Band.WATCH, Band.ALERT, Band.HEALTHY]) is Band.ALERT
    assert worst_band([]) is None


def test_worst_band_and_lowest_health_roll_up() -> None:
    tree = nodes(
        model("K-101", Band.WATCH, 62),
        model("P-101", Band.HEALTHY, 91),
        model("P-102", Band.HEALTHY, 55),  # healthy but the lowest figure
        model("E-201", Band.HEALTHY, 88),
        model("C-301", Band.ALERT, 20),
    )
    assert (tree["U-100"].band, tree["U-100"].health) == (Band.WATCH, 55)
    assert tree["U-100"].worst == "K-101"  # the band, not the lowest number, picks it
    assert (tree["SITE-A"].band, tree["SITE-A"].health) == (Band.WATCH, 55)
    assert (tree["SITE-B"].band, tree["SITE-B"].health) == (Band.ALERT, 20)
    assert (tree["PLANT"].band, tree["PLANT"].health, tree["PLANT"].worst) == (
        Band.ALERT,
        20,
        "C-301",
    )
    assert tree["PLANT"].counts == {Band.HEALTHY: 3, Band.WATCH: 1, Band.ALERT: 1}
    assert tree["SITE-A"].counts == {Band.HEALTHY: 3, Band.WATCH: 1}


def test_an_asset_takes_its_worst_model() -> None:
    tree = nodes(model("K-101", Band.HEALTHY, 80, n=1), model("K-101", Band.ALERT, 30, n=2))
    k101 = tree["K-101"]
    assert (k101.band, k101.health, len(k101.models)) == (Band.ALERT, 30, 2)
    assert k101.counts == {Band.ALERT: 1}  # one asset, however many models


def test_unknown_outranks_healthy_but_not_watch() -> None:
    tree = nodes(model("K-101", Band.UNKNOWN), model("P-101", Band.HEALTHY, 90))
    assert (tree["U-100"].band, tree["U-100"].health) == (Band.UNKNOWN, 90)
    tree = nodes(model("K-101", Band.UNKNOWN), model("P-101", Band.WATCH, 70))
    assert tree["U-100"].band is Band.WATCH


def test_unknown_alone_has_no_health() -> None:
    tree = nodes(model("E-201", Band.UNKNOWN))
    assert (tree["E-201"].band, tree["E-201"].health) == (Band.UNKNOWN, None)
    assert (tree["SITE-A"].band, tree["SITE-A"].health) == (Band.UNKNOWN, None)


def test_assets_without_models_in_service_are_not_monitored() -> None:
    tree = nodes(model("K-101", Band.HEALTHY, 95))
    for code in ("P-101", "U-200", "E-201", "SITE-B", "U-300", "C-301"):
        assert tree[code].band is None
        assert tree[code].health is None
        assert not tree[code].monitored
        assert tree[code].counts == {}
    assert (tree["PLANT"].band, tree["PLANT"].counts) == (Band.HEALTHY, {Band.HEALTHY: 1})


def test_nothing_in_service() -> None:
    tree = nodes()
    assert all(n.band is None and n.worst is None for n in tree.values())


def test_a_subtree_starts_at_its_root() -> None:
    sub = [a for a in assets() if a.path.startswith("PLANT.SITE-A.U-100")]
    (root,) = roll_up(sub, [model("K-101", Band.WATCH, 60), model("C-301", Band.ALERT, 1)])
    assert (root.code, root.band, root.health) == ("U-100", Band.WATCH, 60)


bands = st.sampled_from(list(Band))
equipment = [c for c, level, _ in TREE if level is L.EQUIPMENT]


@given(st.lists(st.tuples(st.sampled_from(equipment), bands, st.floats(0, 100)), max_size=12))
def test_a_parent_is_never_better_than_any_child(
    entries: list[tuple[str, Band, float]],
) -> None:
    models = [
        model(code, band, None if band is Band.UNKNOWN else health, n=i)
        for i, (code, band, health) in enumerate(entries)
    ]
    rank = {Band.HEALTHY: 0, Band.UNKNOWN: 1, Band.WATCH: 2, Band.ALERT: 3}
    for node in nodes(*models).values():
        for child in node.children:
            if child.band is not None:
                assert node.band is not None
                assert rank[node.band] >= rank[child.band]
            if child.health is not None:
                assert node.health is not None
                assert node.health <= child.health
        assert sum(node.counts.values()) == sum(1 for n in node.walk() if n.models)

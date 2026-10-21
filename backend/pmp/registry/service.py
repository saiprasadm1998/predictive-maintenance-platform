"""Registry application services (UC-03, FR-REG-01 to -04, FR-AUD-01).

Every write takes the caller's session (one transaction) and an Actor, and writes an
audit entry in the same transaction. Reads return frozen views, never ORM objects, so
other modules cannot depend on the registry's tables.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pmp.core import Actor, Permission, audit_change, authorize
from pmp.registry.domain import (
    AssetLevel,
    Criticality,
    RegistryError,
    TagSpec,
    check_code,
    check_criticality,
    check_name,
    check_parent_level,
    check_role_code,
    is_descendant_path,
)
from pmp.registry.models import Asset, AssetType, Tag, TagRoleMap, TypeRole


class Change(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


# ------------------------------------------------------------------ inputs and views


@dataclass(frozen=True)
class AssetSpec:
    code: str
    name: str
    level: AssetLevel
    parent_code: str | None = None
    criticality: Criticality | None = None
    asset_type_code: str | None = None
    description: str = ""


@dataclass(frozen=True)
class RoleSpec:
    code: str
    name: str
    unit: str = ""


@dataclass(frozen=True)
class AssetView:
    id: int
    code: str
    name: str
    level: AssetLevel
    path: str
    parent_id: int | None
    criticality: Criticality | None
    asset_type_code: str | None
    description: str

    @property
    def depth(self) -> int:
        return self.path.count(".") + 1


@dataclass(frozen=True)
class TagView:
    id: int
    source: str
    source_name: str
    asset_id: int
    asset_code: str
    description: str
    unit: str
    range_lo: float
    range_hi: float
    interval_s: int
    role_code: str | None
    asset_type_code: str | None = None


@dataclass(frozen=True)
class AssetTypeView:
    id: int
    code: str
    name: str
    description: str
    roles: tuple[RoleSpec, ...]


# ------------------------------------------------------------------ helpers


def _asset_snapshot(asset: Asset, type_code: str | None) -> dict[str, Any]:
    return {
        "code": asset.code,
        "name": asset.name,
        "level": AssetLevel(asset.level).label,
        "parent_id": asset.parent_id,
        "path": asset.path,
        "criticality": asset.criticality,
        "asset_type": type_code,
        "description": asset.description,
    }


def _tag_snapshot(tag: Tag, asset_code: str, role_code: str | None) -> dict[str, Any]:
    return {
        "source": tag.source,
        "source_name": tag.source_name,
        "asset": asset_code,
        "description": tag.description,
        "unit": tag.unit,
        "range_lo": tag.range_lo,
        "range_hi": tag.range_hi,
        "interval_s": tag.interval_s,
        "role": role_code,
    }


def _find_asset(session: Session, code: str) -> Asset | None:
    return session.scalars(select(Asset).where(Asset.code == code)).one_or_none()


def _require_asset(session: Session, code: str) -> Asset:
    asset = _find_asset(session, code)
    if asset is None:
        raise RegistryError(f"Asset {code!r} does not exist")
    return asset


def _find_type(session: Session, code: str) -> AssetType | None:
    return session.scalars(select(AssetType).where(AssetType.code == code)).one_or_none()


def _require_type(session: Session, code: str) -> AssetType:
    asset_type = _find_type(session, code)
    if asset_type is None:
        raise RegistryError(f"Asset type {code!r} does not exist")
    return asset_type


def _type_code(session: Session, type_id: int | None) -> str | None:
    if type_id is None:
        return None
    return session.get_one(AssetType, type_id).code


def _role_code_of_tag(session: Session, tag_id: int) -> str | None:
    return session.scalar(
        select(TypeRole.code)
        .join(TagRoleMap, TagRoleMap.type_role_id == TypeRole.id)
        .where(TagRoleMap.tag_id == tag_id)
    )


def _asset_view(session: Session, asset: Asset) -> AssetView:
    return AssetView(
        id=asset.id,
        code=asset.code,
        name=asset.name,
        level=AssetLevel(asset.level),
        path=asset.path,
        parent_id=asset.parent_id,
        criticality=Criticality(asset.criticality) if asset.criticality else None,
        asset_type_code=_type_code(session, asset.asset_type_id),
        description=asset.description,
    )


def _tag_views(session: Session, tags: Sequence[Tag]) -> list[TagView]:
    """Views for many tags with three queries in total (scoring reads thousands per cycle)."""
    if not tags:
        return []
    asset_ids = {t.asset_id for t in tags}
    assets = {
        a.id: (a.code, a.asset_type_id)
        for a in session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
    }
    type_ids = {type_id for _, type_id in assets.values() if type_id is not None}
    type_codes = (
        dict(
            session.execute(
                select(AssetType.id, AssetType.code).where(AssetType.id.in_(type_ids))
            ).all()
        )
        if type_ids
        else {}
    )
    roles = dict(
        session.execute(
            select(TagRoleMap.tag_id, TypeRole.code)
            .join(TypeRole, TagRoleMap.type_role_id == TypeRole.id)
            .where(TagRoleMap.tag_id.in_([t.id for t in tags]))
        ).all()
    )
    views = []
    for tag in tags:
        asset_code, type_id = assets[tag.asset_id]
        views.append(
            TagView(
                id=tag.id,
                source=tag.source,
                source_name=tag.source_name,
                asset_id=tag.asset_id,
                asset_code=asset_code,
                description=tag.description,
                unit=tag.unit,
                range_lo=tag.range_lo,
                range_hi=tag.range_hi,
                interval_s=tag.interval_s,
                role_code=roles.get(tag.id),
                asset_type_code=type_codes.get(type_id) if type_id is not None else None,
            )
        )
    return views


def _tag_view(session: Session, tag: Tag) -> TagView:
    asset = session.get_one(Asset, tag.asset_id)
    return TagView(
        id=tag.id,
        source=tag.source,
        source_name=tag.source_name,
        asset_id=tag.asset_id,
        asset_code=asset.code,
        description=tag.description,
        unit=tag.unit,
        range_lo=tag.range_lo,
        range_hi=tag.range_hi,
        interval_s=tag.interval_s,
        role_code=_role_code_of_tag(session, tag.id),
        asset_type_code=_type_code(session, asset.asset_type_id),
    )


# ------------------------------------------------------------------ asset types and roles


def upsert_asset_type(
    session: Session, actor: Actor, *, code: str, name: str, description: str = ""
) -> Change:
    authorize(actor, Permission.REGISTRY, what="asset types")
    code = check_code(code, "Asset type code")
    name = check_name(name, "Asset type name")
    description = description.strip()
    existing = _find_type(session, code)
    if existing is None:
        asset_type = AssetType(code=code, name=name, description=description)
        session.add(asset_type)
        session.flush()
        audit_change(
            session,
            actor,
            entity="asset_type",
            entity_id=asset_type.id,
            action="create",
            after={"code": code, "name": name, "description": description},
        )
        return Change.CREATED
    before = {"code": existing.code, "name": existing.name, "description": existing.description}
    after = {"code": code, "name": name, "description": description}
    if before == after:
        return Change.UNCHANGED
    existing.name, existing.description = name, description
    audit_change(
        session,
        actor,
        entity="asset_type",
        entity_id=existing.id,
        action="update",
        before=before,
        after=after,
    )
    return Change.UPDATED


def upsert_role(session: Session, actor: Actor, type_code: str, role: RoleSpec) -> Change:
    authorize(actor, Permission.REGISTRY, what="asset-type roles")
    asset_type = _require_type(session, type_code)
    code = check_role_code(role.code)
    name = check_name(role.name, "Role name")
    unit = role.unit.strip()
    existing = session.scalars(
        select(TypeRole).where(TypeRole.asset_type_id == asset_type.id, TypeRole.code == code)
    ).one_or_none()
    after = {"asset_type": asset_type.code, "code": code, "name": name, "unit": unit}
    if existing is None:
        new_role = TypeRole(asset_type_id=asset_type.id, code=code, name=name, unit=unit)
        session.add(new_role)
        session.flush()
        audit_change(
            session, actor, entity="type_role", entity_id=new_role.id, action="create", after=after
        )
        return Change.CREATED
    before = {
        "asset_type": asset_type.code,
        "code": existing.code,
        "name": existing.name,
        "unit": existing.unit,
    }
    if before == after:
        return Change.UNCHANGED
    existing.name, existing.unit = name, unit
    audit_change(
        session,
        actor,
        entity="type_role",
        entity_id=existing.id,
        action="update",
        before=before,
        after=after,
    )
    return Change.UPDATED


def get_asset_type(session: Session, code: str) -> AssetTypeView:
    asset_type = _require_type(session, code)
    roles = session.scalars(
        select(TypeRole).where(TypeRole.asset_type_id == asset_type.id).order_by(TypeRole.code)
    ).all()
    return AssetTypeView(
        id=asset_type.id,
        code=asset_type.code,
        name=asset_type.name,
        description=asset_type.description,
        roles=tuple(RoleSpec(r.code, r.name, r.unit) for r in roles),
    )


def list_asset_types(session: Session) -> list[AssetTypeView]:
    types = session.scalars(select(AssetType).order_by(AssetType.code)).all()
    return [get_asset_type(session, t.code) for t in types]


# ------------------------------------------------------------------ assets


def upsert_asset(session: Session, actor: Actor, spec: AssetSpec) -> Change:
    """Create an asset, or update it (including moving it) if the code already exists."""
    code = check_code(spec.code, "Asset code")
    name = check_name(spec.name, "Asset name")
    check_criticality(spec.level, spec.criticality)
    parent = _require_asset(session, spec.parent_code) if spec.parent_code else None
    existing_asset = _find_asset(session, code)
    authorize(actor, Permission.REGISTRY, parent.path if parent else None, what=f"asset {code}")
    if existing_asset is not None:  # moving or changing it also needs rights where it is
        authorize(actor, Permission.REGISTRY, existing_asset.path, what=f"asset {code}")
    check_parent_level(spec.level, AssetLevel(parent.level) if parent else None)
    type_id = _require_type(session, spec.asset_type_code).id if spec.asset_type_code else None
    criticality = spec.criticality.value if spec.criticality else None

    existing = _find_asset(session, code)
    if existing is None:
        new_id = session.scalar(text("SELECT nextval(pg_get_serial_sequence('asset', 'id'))"))
        assert new_id is not None
        asset = Asset(
            id=new_id,
            parent_id=parent.id if parent else None,
            code=code,
            name=name,
            level=int(spec.level),
            path=f"{parent.path}.{new_id}" if parent else str(new_id),
            asset_type_id=type_id,
            criticality=criticality,
            description=spec.description.strip(),
        )
        session.add(asset)
        session.flush()
        audit_change(
            session,
            actor,
            entity="asset",
            entity_id=asset.id,
            action="create",
            after=_asset_snapshot(asset, spec.asset_type_code),
        )
        return Change.CREATED

    if existing.level != int(spec.level):
        raise RegistryError(
            f"Asset {code!r} is a {AssetLevel(existing.level).label}; its level cannot change"
        )
    changed = False
    if (existing.parent_id or None) != (parent.id if parent else None):
        move_asset(session, actor, code, spec.parent_code)
        session.refresh(existing)
        changed = True
    before = _asset_snapshot(existing, _type_code(session, existing.asset_type_id))
    existing.name = name
    existing.asset_type_id = type_id
    existing.criticality = criticality
    existing.description = spec.description.strip()
    after = _asset_snapshot(existing, spec.asset_type_code)
    if before != after:
        session.flush()
        audit_change(
            session,
            actor,
            entity="asset",
            entity_id=existing.id,
            action="update",
            before=before,
            after=after,
        )
        changed = True
    return Change.UPDATED if changed else Change.UNCHANGED


def move_asset(session: Session, actor: Actor, code: str, new_parent_code: str | None) -> None:
    """Move an asset and its whole subtree under a new parent (or to the top)."""
    asset = _require_asset(session, code)
    new_parent = _require_asset(session, new_parent_code) if new_parent_code else None
    authorize(actor, Permission.REGISTRY, asset.path, what=f"asset {code}")
    authorize(
        actor, Permission.REGISTRY, new_parent.path if new_parent else None, what=f"asset {code}"
    )
    if new_parent is not None and is_descendant_path(new_parent.path, asset.path):
        raise RegistryError(
            f"Cannot move {code!r} under {new_parent.code!r}: that is the asset itself "
            "or one of its descendants"
        )
    check_parent_level(
        AssetLevel(asset.level), AssetLevel(new_parent.level) if new_parent else None
    )
    if asset.parent_id == (new_parent.id if new_parent else None):
        return

    old_path = asset.path
    new_path = f"{new_parent.path}.{asset.id}" if new_parent else str(asset.id)
    before = {"parent_id": asset.parent_id, "path": old_path}
    session.flush()
    session.execute(
        text(
            "UPDATE asset"
            " SET path = CAST(:new AS ltree) || subpath(path, nlevel(CAST(:old AS ltree))),"
            " updated_at = now()"
            " WHERE path <@ CAST(:old AS ltree) AND path <> CAST(:old AS ltree)"
        ),
        {"new": new_path, "old": old_path},
    )
    session.execute(
        text(
            "UPDATE asset SET path = CAST(:new AS ltree), parent_id = :parent, updated_at = now()"
            " WHERE id = :id"
        ),
        {"new": new_path, "parent": new_parent.id if new_parent else None, "id": asset.id},
    )
    session.expire_all()
    audit_change(
        session,
        actor,
        entity="asset",
        entity_id=asset.id,
        action="move",
        before=before,
        after={"parent_id": new_parent.id if new_parent else None, "path": new_path},
    )


def get_asset(session: Session, code: str) -> AssetView:
    return _asset_view(session, _require_asset(session, code))


def get_asset_by_id(session: Session, asset_id: int) -> AssetView:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise RegistryError(f"Asset {asset_id} does not exist")
    return _asset_view(session, asset)


def find_asset(session: Session, code: str) -> AssetView | None:
    asset = _find_asset(session, code)
    return _asset_view(session, asset) if asset else None


def list_subtree(session: Session, code: str | None = None) -> list[AssetView]:
    """The asset and everything under it, in tree order (all assets if code is None)."""
    query = select(Asset)
    if code is not None:
        root = _require_asset(session, code)
        query = query.where(text("path <@ CAST(:root AS ltree)").bindparams(root=root.path))
    assets = session.scalars(query.order_by(Asset.path)).all()
    type_ids = {a.asset_type_id for a in assets if a.asset_type_id is not None}
    codes: dict[int, str] = {}
    if type_ids:
        rows = session.execute(
            select(AssetType.id, AssetType.code).where(AssetType.id.in_(type_ids))
        ).all()
        codes = {row.id: row.code for row in rows}
    return [
        AssetView(
            id=a.id,
            code=a.code,
            name=a.name,
            level=AssetLevel(a.level),
            path=a.path,
            parent_id=a.parent_id,
            criticality=Criticality(a.criticality) if a.criticality else None,
            asset_type_code=codes.get(a.asset_type_id) if a.asset_type_id is not None else None,
            description=a.description,
        )
        for a in assets
    ]


def list_ancestors(session: Session, code: str) -> list[AssetView]:
    """Ancestors from the top down, excluding the asset itself."""
    asset = _require_asset(session, code)
    assets = session.scalars(
        select(Asset)
        .where(text("path @> CAST(:p AS ltree)").bindparams(p=asset.path))
        .where(Asset.id != asset.id)
        .order_by(func.nlevel(Asset.path))
    ).all()
    return [_asset_view(session, a) for a in assets]


def count_assets(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Asset)) or 0


# ------------------------------------------------------------------ tags


def upsert_tag(
    session: Session, actor: Actor, spec: TagSpec, *, role_code: str | None = None
) -> Change:
    """Create or update a tag keyed on (source, source_name), and set its role if given."""
    spec = spec.validated()
    asset = _require_asset(session, spec.asset_code)
    authorize(actor, Permission.REGISTRY, asset.path, what=f"tags of {asset.code}")
    role: TypeRole | None = None
    if role_code:
        role = _resolve_role(session, asset, check_role_code(role_code))

    tag = session.scalars(
        select(Tag).where(Tag.source == spec.source, Tag.source_name == spec.source_name)
    ).one_or_none()
    if tag is None:
        tag = Tag(
            source=spec.source,
            source_name=spec.source_name,
            asset_id=asset.id,
            description=spec.description,
            unit=spec.unit,
            range_lo=spec.range_lo,
            range_hi=spec.range_hi,
            interval_s=spec.interval_s,
        )
        session.add(tag)
        session.flush()
        _set_role(session, tag, asset, role)
        audit_change(
            session,
            actor,
            entity="tag",
            entity_id=tag.id,
            action="create",
            after=_tag_snapshot(tag, asset.code, role.code if role else None),
        )
        return Change.CREATED

    old_asset_code = session.get_one(Asset, tag.asset_id).code
    before = _tag_snapshot(tag, old_asset_code, _role_code_of_tag(session, tag.id))
    tag.asset_id = asset.id
    tag.description = spec.description
    tag.unit = spec.unit
    tag.range_lo = spec.range_lo
    tag.range_hi = spec.range_hi
    tag.interval_s = spec.interval_s
    session.flush()
    _set_role(session, tag, asset, role)
    after = _tag_snapshot(tag, asset.code, role.code if role else None)
    if before == after:
        return Change.UNCHANGED
    audit_change(
        session, actor, entity="tag", entity_id=tag.id, action="update", before=before, after=after
    )
    return Change.UPDATED


def _resolve_role(session: Session, asset: Asset, role_code: str) -> TypeRole:
    if asset.asset_type_id is None:
        raise RegistryError(
            f"Asset {asset.code!r} has no asset type, so its tags cannot be given roles"
        )
    role = session.scalars(
        select(TypeRole).where(
            TypeRole.asset_type_id == asset.asset_type_id, TypeRole.code == role_code
        )
    ).one_or_none()
    if role is None:
        type_code = _type_code(session, asset.asset_type_id)
        raise RegistryError(f"Asset type {type_code!r} has no role {role_code!r}")
    return role


def _set_role(session: Session, tag: Tag, asset: Asset, role: TypeRole | None) -> None:
    current = session.scalars(select(TagRoleMap).where(TagRoleMap.tag_id == tag.id)).one_or_none()
    if role is None:
        if current is not None:
            session.delete(current)
            session.flush()
        return
    if current is not None and current.type_role_id == role.id and current.asset_id == asset.id:
        return
    holder = session.scalars(
        select(TagRoleMap).where(
            TagRoleMap.asset_id == asset.id, TagRoleMap.type_role_id == role.id
        )
    ).one_or_none()
    if holder is not None and holder.tag_id != tag.id:
        other = session.get_one(Tag, holder.tag_id)
        raise RegistryError(
            f"Role {role.code!r} on asset {asset.code!r} is already filled by tag "
            f"{other.source_name!r}"
        )
    if current is not None:
        session.delete(current)
        session.flush()
    session.add(TagRoleMap(asset_id=asset.id, type_role_id=role.id, tag_id=tag.id))
    session.flush()


def find_tag(session: Session, source: str, source_name: str) -> TagView | None:
    tag = session.scalars(
        select(Tag).where(Tag.source == source, Tag.source_name == source_name)
    ).one_or_none()
    return _tag_view(session, tag) if tag else None


def list_tags(session: Session, asset_code: str | None = None) -> list[TagView]:
    query = select(Tag)
    if asset_code is not None:
        query = query.where(Tag.asset_id == _require_asset(session, asset_code).id)
    tags = session.scalars(query.order_by(Tag.source, Tag.source_name)).all()
    return _tag_views(session, tags)


def get_tags(session: Session, tag_ids: Iterable[int]) -> list[TagView]:
    """Tags by ID, ordered by source and name; unknown IDs are left out."""
    ids = list(set(tag_ids))
    if not ids:
        return []
    tags = session.scalars(
        select(Tag).where(Tag.id.in_(ids)).order_by(Tag.source, Tag.source_name)
    ).all()
    return _tag_views(session, tags)


def role_gaps(session: Session, asset_code: str) -> Sequence[str]:
    """Roles of the asset's type that no tag fills yet (reported by templates, FR-REG-04)."""
    asset = _require_asset(session, asset_code)
    if asset.asset_type_id is None:
        return []
    filled = select(TagRoleMap.type_role_id).where(TagRoleMap.asset_id == asset.id)
    return session.scalars(
        select(TypeRole.code)
        .where(TypeRole.asset_type_id == asset.asset_type_id, TypeRole.id.not_in(filled))
        .order_by(TypeRole.code)
    ).all()


def resolve_tag_ids(session: Session, source: str, source_names: Iterable[str]) -> dict[str, int]:
    """Map a source's tag names to tag IDs in one query; unknown names are left out."""
    names = list(set(source_names))
    if not names:
        return {}
    rows = session.execute(
        select(Tag.source_name, Tag.id).where(Tag.source == source, Tag.source_name.in_(names))
    )
    return {str(name): int(tag_id) for name, tag_id in rows}


def tag_exists(session: Session, source: str, source_name: str) -> bool:
    return bool(resolve_tag_ids(session, source, [source_name]))

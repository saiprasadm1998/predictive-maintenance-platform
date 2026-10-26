"""Registry changes: assets, tags, asset types and roles, imports, unmapped tags
(ARC §7.3; UC-02, UC-03, FR-REG-01 to -04, FR-ING-06). The registry services check the
user's role and scope (ARC §9.2: Model Engineer or Administrator)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pmp.api.assets import (
    AssetOut,
    AssetTypeOut,
    TagOut,
    asset_out,
    get_asset_types,
    tag_out,
)
from pmp.api.common import MAX_LIMIT, Page, can_see, not_found, page
from pmp.api.deps import SignedIn, database_of, signed_in
from pmp.api.problems import ProblemError
from pmp.core import Permission, authorize
from pmp.ingestion import list_unmapped_tags, promote_unmapped_tag
from pmp.registry import (
    AssetLevel,
    AssetSpec,
    Criticality,
    RegistryError,
    RoleSpec,
    TagSpec,
    find_asset,
    find_tag,
    get_asset_by_id,
    get_tags,
    import_files,
    upsert_asset,
    upsert_asset_type,
    upsert_role,
    upsert_tag,
)

router = APIRouter(prefix="/api/v1", tags=["registry"])
User = Annotated[SignedIn, Depends(signed_in)]
LEVELS = {level.label: level for level in AssetLevel}


def _refused(error: Exception) -> ProblemError:
    return ProblemError(400, "registry_refused", "Registry change refused", str(error))


# ------------------------------------------------------------------ assets


class AssetIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    level: str = Field(description="enterprise, site, area, unit or equipment")
    parent: str | None = Field(default=None, description="parent asset code")
    criticality: Criticality | None = None
    asset_type: str | None = Field(default=None, description="asset type code")
    description: str = ""


class AssetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent: str | None = Field(default=None, description="move under this asset code")
    criticality: Criticality | None = None
    asset_type: str | None = None
    description: str | None = None


def _level(label: str) -> AssetLevel:
    if label not in LEVELS:
        raise ProblemError(
            400, "invalid_level", "Unknown level", f"Use one of {', '.join(LEVELS)}."
        )
    return LEVELS[label]


@router.post("/assets", status_code=201, response_model=AssetOut, summary="Create an asset")
def post_asset(request: Request, user: User, body: AssetIn) -> AssetOut:
    try:
        with database_of(request).session() as session:
            parent = find_asset(session, body.parent) if body.parent else None
            # ARC §9.2 before anything else, so the answer says nothing to others
            authorize(user.actor, Permission.REGISTRY, parent.path if parent else None)
            if find_asset(session, body.code) is not None:
                raise ProblemError(409, "exists", "Asset exists", f"Asset {body.code} exists.")
            upsert_asset(
                session,
                user.actor,
                AssetSpec(
                    body.code,
                    body.name,
                    _level(body.level),
                    body.parent,
                    body.criticality,
                    body.asset_type,
                    body.description,
                ),
            )
            asset = find_asset(session, body.code)
            assert asset is not None
            return asset_out(asset)
    except RegistryError as error:
        raise _refused(error) from None


@router.patch("/assets/{asset_id}", response_model=AssetOut, summary="Change or move an asset")
def patch_asset(request: Request, user: User, asset_id: int, body: AssetPatch) -> AssetOut:
    try:
        with database_of(request).session() as session:
            try:
                asset = get_asset_by_id(session, asset_id)
            except RegistryError:
                raise not_found("Asset") from None
            if not can_see(user, asset.path):
                raise not_found("Asset")
            parent_code = (
                get_asset_by_id(session, asset.parent_id).code if asset.parent_id else None
            )
            fields = body.model_fields_set
            upsert_asset(
                session,
                user.actor,
                AssetSpec(
                    asset.code,
                    body.name if body.name is not None else asset.name,
                    asset.level,
                    body.parent if "parent" in fields else parent_code,
                    body.criticality if "criticality" in fields else asset.criticality,
                    body.asset_type if "asset_type" in fields else asset.asset_type_code,
                    body.description if body.description is not None else asset.description,
                ),
            )
            return asset_out(get_asset_by_id(session, asset_id))
    except RegistryError as error:
        raise _refused(error) from None


# ------------------------------------------------------------------ tags


class TagIn(BaseModel):
    source: str = Field(min_length=1, max_length=100)
    source_name: str = Field(min_length=1, max_length=200)
    asset: str = Field(description="asset code")
    unit: str = Field(min_length=1, max_length=50)
    range_lo: float
    range_hi: float
    interval_s: int = Field(gt=0)
    description: str = ""
    role: str | None = Field(default=None, description="role code of the asset's type")


def _tag_by_id(session: Session, tag_id: int) -> TagOut:
    (tag,) = get_tags(session, [tag_id])
    return tag_out(tag)


@router.post("/tags", status_code=201, response_model=TagOut, summary="Register a tag")
def post_tag(request: Request, user: User, body: TagIn) -> TagOut:
    try:
        with database_of(request).session() as session:
            target = find_asset(session, body.asset)
            authorize(user.actor, Permission.REGISTRY, target.path if target else None)
            if find_tag(session, body.source, body.source_name) is not None:
                raise ProblemError(409, "exists", "Tag exists", f"{body.source_name} exists.")
            spec = TagSpec(
                body.source,
                body.source_name,
                body.asset,
                body.unit,
                body.range_lo,
                body.range_hi,
                body.interval_s,
                body.description,
            )
            upsert_tag(session, user.actor, spec, role_code=body.role)
            tag = find_tag(session, body.source, body.source_name)
            assert tag is not None
            return _tag_by_id(session, tag.id)
    except RegistryError as error:
        raise _refused(error) from None


class TagPatch(BaseModel):
    asset: str | None = None
    unit: str | None = None
    range_lo: float | None = None
    range_hi: float | None = None
    interval_s: int | None = Field(default=None, gt=0)
    description: str | None = None
    role: str | None = None


@router.patch("/tags/{tag_id}", response_model=TagOut, summary="Change a tag")
def patch_tag(request: Request, user: User, tag_id: int, body: TagPatch) -> TagOut:
    try:
        with database_of(request).session() as session:
            found = get_tags(session, [tag_id])
            if not found:
                raise not_found("Tag")
            t = found[0]
            if not can_see(user, get_asset_by_id(session, t.asset_id).path):
                raise not_found("Tag")
            spec = TagSpec(
                t.source,
                t.source_name,
                body.asset or t.asset_code,
                body.unit if body.unit is not None else t.unit,
                body.range_lo if body.range_lo is not None else t.range_lo,
                body.range_hi if body.range_hi is not None else t.range_hi,
                body.interval_s or t.interval_s,
                body.description if body.description is not None else t.description,
            )
            role = body.role if "role" in body.model_fields_set else t.role_code
            upsert_tag(session, user.actor, spec, role_code=role)
            return _tag_by_id(session, tag_id)
    except RegistryError as error:
        raise _refused(error) from None


class ImportProblem(BaseModel):
    sheet: str
    line: int
    column: str
    message: str


class ImportOut(BaseModel):
    committed: bool
    dry_run: bool
    counts: dict[str, dict[str, int]]
    problems: list[ImportProblem]


@router.post(
    "/tags/import",
    response_model=ImportOut,
    summary="Import the registry from CSV files or one Excel workbook (UC-03)",
)
def post_import(
    request: Request,
    user: User,
    files: Annotated[list[UploadFile], File(description="assets.csv, tags.csv ... or a .xlsx")],
    dry_run: Annotated[bool, Query(description="validate only")] = False,
) -> ImportOut:
    folder = Path(tempfile.mkdtemp(prefix="pmp-import-"))
    try:
        paths = []
        for upload in files:
            name = Path(upload.filename or "upload").name
            target = folder / name
            with target.open("wb") as out:
                shutil.copyfileobj(upload.file, out)
            paths.append(target)
        with database_of(request).session() as session:
            report = import_files(session, user.actor, paths, dry_run=dry_run)
            if report.problems:
                session.rollback()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return ImportOut(
        committed=report.ok and not dry_run,
        dry_run=dry_run,
        counts={sheet: dict(c) for sheet, c in report.counts.items()},
        problems=[ImportProblem(**vars(p)) for p in report.problems],
    )


# ------------------------------------------------------------------ asset types and roles


class AssetTypeIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class RoleIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    unit: str = ""


def _type_out(request: Request, user: SignedIn, code: str) -> AssetTypeOut:
    return next(t for t in get_asset_types(request, user) if t.code == code)


@router.post(
    "/asset-types", status_code=201, response_model=AssetTypeOut, summary="Create an asset type"
)
def post_asset_type(request: Request, user: User, body: AssetTypeIn) -> AssetTypeOut:
    try:
        with database_of(request).session() as session:
            upsert_asset_type(
                session, user.actor, code=body.code, name=body.name, description=body.description
            )
    except RegistryError as error:
        raise _refused(error) from None
    return _type_out(request, user, body.code)


@router.post(
    "/asset-types/{type_id}/roles",
    status_code=201,
    response_model=AssetTypeOut,
    summary="Add or change a role of an asset type",
)
def post_role(request: Request, user: User, type_id: int, body: RoleIn) -> AssetTypeOut:
    types = {t.id: t.code for t in get_asset_types(request, user)}
    if type_id not in types:
        raise not_found("Asset type")
    try:
        with database_of(request).session() as session:
            upsert_role(
                session, user.actor, types[type_id], RoleSpec(body.code, body.name, body.unit)
            )
    except RegistryError as error:
        raise _refused(error) from None
    return _type_out(request, user, types[type_id])


# ------------------------------------------------------------------ unmapped tags


class UnmappedOut(BaseModel):
    source: str
    source_name: str
    first_seen: str
    last_seen: str
    count: int


@router.get("/unmapped-tags", response_model=Page[UnmappedOut], summary="FR-ING-06")
def get_unmapped(
    request: Request,
    user: User,
    source: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 500,
) -> Page[UnmappedOut]:
    with database_of(request).session() as session:
        rows = list_unmapped_tags(session, source)
    items, next_cursor = page(rows, lambda r: [r.source, r.source_name], cursor, limit)
    return Page[UnmappedOut](
        items=[
            UnmappedOut(
                source=r.source,
                source_name=r.source_name,
                first_seen=r.first_seen.isoformat(),
                last_seen=r.last_seen.isoformat(),
                count=r.count,
            )
            for r in items
        ],
        next_cursor=next_cursor,
    )


@router.post(
    "/unmapped-tags/promote",
    status_code=201,
    response_model=TagOut,
    summary="Register an unmapped tag (UC-03 2a)",
)
def post_promote(request: Request, user: User, body: TagIn) -> TagOut:
    try:
        with database_of(request).session() as session:
            spec = TagSpec(
                body.source,
                body.source_name,
                body.asset,
                body.unit,
                body.range_lo,
                body.range_hi,
                body.interval_s,
                body.description,
            )
            promote_unmapped_tag(session, user.actor, spec, role_code=body.role)
            tag = find_tag(session, body.source, body.source_name)
            assert tag is not None
            return _tag_by_id(session, tag.id)
    except RegistryError as error:
        raise _refused(error) from None

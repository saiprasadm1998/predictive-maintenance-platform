"""registry.

Asset hierarchy, tags, asset types, roles, tag-role maps and imports.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.registry.domain import AssetLevel, Criticality, RegistryError, TagSpec
from pmp.registry.importer import ImportFailedError, ImportReport, Problem, import_files
from pmp.registry.service import (
    AssetSpec,
    AssetTypeView,
    AssetView,
    Change,
    RoleSpec,
    TagView,
    count_assets,
    find_asset,
    find_tag,
    get_asset,
    get_asset_by_id,
    get_asset_type,
    get_tags,
    list_ancestors,
    list_asset_types,
    list_subtree,
    list_tags,
    move_asset,
    resolve_tag_ids,
    role_gaps,
    tag_exists,
    upsert_asset,
    upsert_asset_type,
    upsert_role,
    upsert_tag,
)

__all__ = [
    "AssetLevel",
    "AssetSpec",
    "AssetTypeView",
    "AssetView",
    "Change",
    "Criticality",
    "ImportFailedError",
    "ImportReport",
    "Problem",
    "RegistryError",
    "RoleSpec",
    "TagSpec",
    "TagView",
    "count_assets",
    "find_asset",
    "find_tag",
    "get_asset",
    "get_asset_by_id",
    "get_asset_type",
    "get_tags",
    "import_files",
    "list_ancestors",
    "list_asset_types",
    "list_subtree",
    "list_tags",
    "move_asset",
    "resolve_tag_ids",
    "role_gaps",
    "tag_exists",
    "upsert_asset",
    "upsert_asset_type",
    "upsert_role",
    "upsert_tag",
]

"""Model artefact folders (ARC-001 §8.2): <artefact-dir>/models/<model_id>/<version>/.

Contents: the algorithm's own files (written by Detector.save into `algorithm/`),
scaling.json, manifest.json and validation.json. The SHA-256 of the folder is stored with
the version; verifying it on every load arrives with the lifecycle in 3.3.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from pmp.modelling.algorithms.contract import Detector

ALGORITHM_DIR = "algorithm"


def artefact_dir(base: Path, model_id: int, version: int) -> Path:
    return base / "models" / str(model_id) / str(version)


def folder_digest(folder: Path) -> str:
    """SHA-256 over every file's relative path and content, in a fixed order."""
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(path.relative_to(folder).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_artefact(
    target: Path,
    detector: Detector,
    *,
    scaling: dict[str, Any],
    manifest: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    """Write the folder atomically (a retried job replaces it) and return its SHA-256."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    detector.save(staging / ALGORITHM_DIR)
    _write_json(staging / "scaling.json", scaling)
    _write_json(staging / "manifest.json", manifest)
    _write_json(staging / "validation.json", validation)
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    return folder_digest(target)

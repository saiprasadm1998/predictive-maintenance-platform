"""Model artefact folders (ARC-001 §8.2): <artefact-dir>/models/<model_id>/<version>/.

Contents: the algorithm's own files (written by Detector.save into `algorithm/`),
scaling.json, manifest.json and validation.json. The SHA-256 of the folder is stored with
the version and checked on every load, before any file is read: the algorithm formats
can execute code when loaded, so only artefacts PMP wrote and that still match their
checksum are ever loaded (ARC §8.2).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from pmp.modelling.algorithms.contract import Detector
from pmp.modelling.definitions import ModelError

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


class ArtefactError(ModelError):
    """An artefact that is missing, changed since training, or unreadable."""


def read_artefact(
    folder: Path, expected_sha256: str
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Verify the folder's SHA-256, then read scaling.json and manifest.json.

    Returns the algorithm folder (for Detector.load), the scaling and the manifest.
    """
    if not folder.is_dir():
        raise ArtefactError(f"Artefact folder {folder} is missing")
    actual = folder_digest(folder)
    if actual != expected_sha256:
        raise ArtefactError(
            f"Artefact {folder} does not match its checksum (expected {expected_sha256[:12]}…, "
            f"found {actual[:12]}…); it was changed after training and will not be loaded"
        )
    try:
        scaling = json.loads((folder / "scaling.json").read_text(encoding="utf-8"))
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ArtefactError(f"Artefact {folder} is unreadable: {error}") from None
    return folder / ALGORITHM_DIR, scaling, manifest

"""Module boundary contracts (ARC-001 §4.1, NFR-MAIN-01).

Each test copies the package and the import-linter configuration into a temporary
folder, optionally plants a forbidden import, and runs lint-imports there. This
proves the contracts pass on clean code and fail when a boundary is broken.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


def _lint_imports(root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(root)}
    lint_imports = Path(sys.executable).with_name("lint-imports")
    return subprocess.run(
        [str(lint_imports), "--config", str(root / "pyproject.toml"), "--no-cache"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    shutil.copytree(BACKEND / "pmp", tmp_path / "pmp", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(BACKEND / "pyproject.toml", tmp_path / "pyproject.toml")
    return tmp_path


def _plant(root: Path, path: str, source: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)


def test_clean_code_keeps_all_contracts(workspace: Path) -> None:
    result = _lint_imports(workspace)
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_of_another_modules_internals_is_rejected(workspace: Path) -> None:
    _plant(workspace, "pmp/registry/service.py", "VALUE = 1\n")
    _plant(workspace, "pmp/ingestion/service.py", "from pmp.registry import service\n")

    result = _lint_imports(workspace)

    assert result.returncode != 0
    assert "ingestion uses other modules only through their public interface" in result.stdout


def test_import_through_public_interface_is_allowed(workspace: Path) -> None:
    _plant(workspace, "pmp/registry/service.py", "VALUE = 1\n")
    _plant(workspace, "pmp/registry/__init__.py", "from pmp.registry.service import VALUE\n")
    _plant(workspace, "pmp/ingestion/service.py", "from pmp.registry import VALUE\n")

    result = _lint_imports(workspace)

    assert result.returncode == 0, result.stdout + result.stderr


def test_core_may_not_import_a_feature_module(workspace: Path) -> None:
    _plant(workspace, "pmp/core/config.py", "import pmp.scoring\n")

    result = _lint_imports(workspace)

    assert result.returncode != 0
    assert "Layers" in result.stdout


def test_feature_module_may_not_import_api(workspace: Path) -> None:
    _plant(workspace, "pmp/alerting/service.py", "import pmp.api\n")

    result = _lint_imports(workspace)

    assert result.returncode != 0
    assert "Layers" in result.stdout

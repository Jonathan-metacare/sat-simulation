from __future__ import annotations

import re
from pathlib import Path

from sat_simulation import __version__


def test_runtime_version_matches_project_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    project_version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert project_version is not None
    assert __version__ == project_version.group(1)

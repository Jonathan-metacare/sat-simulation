from __future__ import annotations

import io
import stat
import zipfile

import pytest

from sat_simulation.common.models import ProcessorStage
from sat_simulation.processors import ProcessorBundleError, inspect_processor_bundle


def bundle(manifest: str, files: dict[str, bytes] | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("processor.yaml", manifest)
        for name, content in (files or {"processor.py": b"print('ok')"}).items():
            archive.writestr(name, content)
    return output.getvalue()


MANIFEST = """\
schema_version: 1
id: customer-l0
name: Customer L0
version: 1.0.0
stage: l0
entrypoint: processor.py
timeout_seconds: 60
cpu_limit: 1
memory_mb: 512
output_limit_mb: 64
"""


def test_processor_bundle_is_strict_and_stage_is_frozen() -> None:
    definition, digest = inspect_processor_bundle(bundle(MANIFEST))
    assert definition.stage == ProcessorStage.L0
    assert definition.entrypoint == "processor.py"
    assert len(digest) == 64

    with pytest.raises(ProcessorBundleError, match="unexpected"):
        inspect_processor_bundle(bundle(MANIFEST + "unexpected: true\n"))


def test_processor_bundle_rejects_traversal_and_symlink() -> None:
    with pytest.raises(ProcessorBundleError, match="unsafe bundle path"):
        inspect_processor_bundle(bundle(MANIFEST, {"processor.py": b"", "../escape.py": b""}))

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("processor.yaml", MANIFEST)
        link = zipfile.ZipInfo("processor.py")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "target.py")
    with pytest.raises(ProcessorBundleError, match="Symbolic|symbolic"):
        inspect_processor_bundle(output.getvalue())

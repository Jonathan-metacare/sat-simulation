from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import pytest

from sat_simulation.common.models import ProcessorStage
from sat_simulation.processors import ProcessorBundleError, ProcessorRunner, inspect_processor_bundle
from sat_simulation.processors.templates import builtin_template, source_from_bundle, workspace_bundle


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

    with pytest.raises(ProcessorBundleError, match="wheels"):
        inspect_processor_bundle(bundle(MANIFEST, {"processor.py": b"", "wheels/foo.whl": b"x"}))


@pytest.mark.parametrize("stage", [ProcessorStage.L0, ProcessorStage.L1])
def test_builtin_workspace_templates_are_readonly_reference_bundles(stage: ProcessorStage) -> None:
    template = builtin_template(stage)
    assert "def main()" in template.source
    assert "# to be implemented" in template.source
    assert "NotImplementedError" in template.source
    content = workspace_bundle(template.definition, template.source)
    definition, _digest = inspect_processor_bundle(content)
    assert definition.stage == stage


def test_workspace_bundle_rejects_invalid_python_and_round_trips_source(tmp_path: Path) -> None:
    template = builtin_template(ProcessorStage.L0)
    with pytest.raises(ProcessorBundleError, match="syntax error"):
        workspace_bundle(template.definition, "def broken(:\n")
    bundle_path = tmp_path / "processor.zip"
    bundle_path.write_bytes(workspace_bundle(template.definition, template.source))
    manifest, source = source_from_bundle(str(bundle_path), template.definition)
    assert "stage: l0" in manifest
    assert source == template.source


@pytest.mark.asyncio
async def test_macos_desktop_runner_executes_only_inside_seatbelt(tmp_path: Path) -> None:
    runner = ProcessorRunner(runtime="desktop-sandbox")
    if not await runner.available():
        pytest.skip("macOS Seatbelt is unavailable on this platform")
    definition = builtin_template(ProcessorStage.L0).definition.model_copy(
        update={"id": "seatbelt-smoke", "timeout_seconds": 10, "memory_mb": 2048}
    )
    source = builtin_template(ProcessorStage.L0).source
    source = source.replace(
        '    # to be implemented\n    raise NotImplementedError("Implement RAW packet validation")',
        "    return None",
    ).replace(
        '    # to be implemented\n    raise NotImplementedError("Implement RAW to L0 reconstruction")',
        "    return np.zeros((1, 1, 1), dtype=np.uint16)",
    )
    bundle_path = tmp_path / "processor.zip"
    bundle_path.write_bytes(workspace_bundle(definition, source))
    raw_path = tmp_path / "raw.bin"
    raw_path.write_bytes(b"raw")
    result = await runner.run(
        bundle_path=bundle_path,
        request={"schema_version": 1},
        input_files={"raw": raw_path},
        execution_dir=tmp_path / "execution",
    )
    assert (result.output_dir / "l0.npy").is_file()

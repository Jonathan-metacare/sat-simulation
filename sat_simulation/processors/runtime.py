from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import yaml
from pydantic import ValidationError

from sat_simulation.common.models import ProcessorDefinition

MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization)(\s*[:=]\s*)([^\s,;]+)"
)


class ProcessorBundleError(ValueError):
    pass


class ProcessorBlocked(RuntimeError):
    code = "processor_runtime_unavailable"


@dataclass(frozen=True)
class ProcessorRunResult:
    definition: ProcessorDefinition
    result: dict[str, Any]
    output_dir: Path
    stdout: str
    stderr: str
    exit_code: int


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    seen: set[str] = set()
    expanded = 0
    members: list[zipfile.ZipInfo] = []
    for member in archive.infolist():
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ProcessorBundleError(f"unsafe bundle path: {member.filename}")
        normalized = path.as_posix()
        if normalized.lower().endswith(".whl"):
            raise ProcessorBundleError(
                "desktop processor bundles cannot include wheels; use only application-provided dependencies"
            )
        if normalized in seen:
            raise ProcessorBundleError(f"duplicate bundle path: {normalized}")
        seen.add(normalized)
        expanded += member.file_size
        if expanded > MAX_EXPANDED_BYTES:
            raise ProcessorBundleError("expanded processor bundle exceeds 256 MiB")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ProcessorBundleError(f"symbolic links are not allowed: {normalized}")
        members.append(member)
    return members


def inspect_processor_bundle(content: bytes) -> tuple[ProcessorDefinition, str]:
    if len(content) > MAX_BUNDLE_BYTES:
        raise ProcessorBundleError("processor bundle exceeds 64 MiB")
    digest = hashlib.sha256(content).hexdigest()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = _safe_members(archive)
            names = {item.filename.rstrip("/") for item in members}
            if "processor.yaml" not in names:
                raise ProcessorBundleError("processor.yaml is required")
            payload = yaml.safe_load(archive.read("processor.yaml").decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProcessorBundleError(f"invalid processor bundle: {exc}") from exc
    try:
        definition = ProcessorDefinition.model_validate(payload)
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors()
        )
        raise ProcessorBundleError(detail) from exc
    entrypoint = PurePosixPath(definition.entrypoint)
    if entrypoint.is_absolute() or ".." in entrypoint.parts:
        raise ProcessorBundleError("entrypoint must be a relative bundle path")
    if entrypoint.as_posix() not in names:
        raise ProcessorBundleError(f"entrypoint not found: {definition.entrypoint}")
    if entrypoint.suffix != ".py":
        raise ProcessorBundleError("V1 entrypoint must be a Python file")
    return definition, digest


def extract_processor_bundle(bundle_path: Path, destination: Path) -> ProcessorDefinition:
    content = bundle_path.read_bytes()
    definition, _digest = inspect_processor_bundle(content)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path) as archive:
        for member in _safe_members(archive):
            if member.is_dir():
                continue
            target = (destination / member.filename).resolve()
            if destination.resolve() not in target.parents:
                raise ProcessorBundleError(f"unsafe extraction path: {member.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    return definition


class ProcessorRunner:
    def __init__(
        self,
        *,
        runtime: str = "docker",
        image: str = "spacezenith/processor-python:3.12",
    ) -> None:
        self.runtime = runtime
        self.image = image

    async def available(self) -> bool:
        if self.runtime == "desktop-sandbox":
            if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
                return False
            try:
                probe = await asyncio.create_subprocess_exec(
                    "/usr/bin/sandbox-exec",
                    "-p",
                    "(version 1) (deny default) (allow process-exec) (allow file-read*)",
                    "/usr/bin/true",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                return await asyncio.wait_for(probe.wait(), timeout=3) == 0
            except (FileNotFoundError, TimeoutError, OSError):
                return False
        try:
            process = await asyncio.create_subprocess_exec(
                self.runtime,
                "version",
                "--format",
                "{{.Server.Version}}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return await asyncio.wait_for(process.wait(), timeout=3) == 0
        except (FileNotFoundError, TimeoutError, OSError):
            return False

    async def immutable_image(self) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self.runtime,
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                self.image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        except (FileNotFoundError, TimeoutError, OSError) as exc:
            raise ProcessorBlocked(f"处理器基础镜像不可用: {self.image}") from exc
        image_id = stdout.decode("utf-8", errors="replace").strip()
        if process.returncode or not image_id.startswith("sha256:"):
            raise ProcessorBlocked(f"处理器基础镜像不可用: {self.image}")
        return image_id

    async def run(
        self,
        *,
        bundle_path: Path,
        request: dict[str, Any],
        input_files: dict[str, Path],
        execution_dir: Path,
    ) -> ProcessorRunResult:
        if self.runtime == "desktop-sandbox":
            return await self._run_desktop_sandbox(
                bundle_path=bundle_path,
                request=request,
                input_files=input_files,
                execution_dir=execution_dir,
            )
        return await self._run_oci(
            bundle_path=bundle_path,
            request=request,
            input_files=input_files,
            execution_dir=execution_dir,
        )

    async def _run_oci(
        self,
        *,
        bundle_path: Path,
        request: dict[str, Any],
        input_files: dict[str, Path],
        execution_dir: Path,
    ) -> ProcessorRunResult:
        definition, _digest = inspect_processor_bundle(bundle_path.read_bytes())
        if not await self.available():
            raise ProcessorBlocked(
                "自定义处理器需要 Docker/OCI Runtime；安装并启动后可重试当前阶段"
            )
        immutable_image = await self.immutable_image()
        input_dir = execution_dir / "input"
        bundle_dir = input_dir / "bundle"
        files_dir = input_dir / "files"
        output_dir = execution_dir / "output"
        if execution_dir.exists():
            shutil.rmtree(execution_dir)
        files_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        # The bind mount contains only this execution's disposable output. The
        # sandbox UID must be able to create files without gaining access to any
        # other host directory.
        output_dir.chmod(0o777)
        extract_processor_bundle(bundle_path, bundle_dir)
        mounted_files: dict[str, str] = {}
        for logical_name, source in input_files.items():
            target = files_dir / source.name
            shutil.copyfile(source, target)
            target.chmod(0o444)
            mounted_files[logical_name] = f"/workspace/input/files/{target.name}"
        request_path = input_dir / "request.json"
        request_path.write_text(
            json.dumps({**request, "files": mounted_files}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        request_path.chmod(0o444)
        container_name = f"sat-sim-processor-{uuid4().hex}"
        command = [
            self.runtime,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--read-only",
            "--user",
            "65532:65532",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--pids-limit",
            "128",
            "--cpus",
            str(definition.cpu_limit),
            "--memory",
            f"{definition.memory_mb}m",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m",
            "--mount",
            f"type=bind,src={input_dir.resolve()},dst=/workspace/input,readonly",
            "--mount",
            f"type=bind,src={output_dir.resolve()},dst=/workspace/output",
            immutable_image,
            "python",
            f"/workspace/input/bundle/{definition.entrypoint}",
            "--input",
            "/workspace/input/request.json",
            "--output",
            "/workspace/output/result.json",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": os.environ.get("PATH", "")},
        )
        quota_exceeded = asyncio.Event()

        async def monitor_output() -> None:
            limit = definition.output_limit_mb * 1024 * 1024
            while process.returncode is None:
                total = sum(path.stat().st_size for path in output_dir.rglob("*") if path.is_file())
                if total > limit:
                    quota_exceeded.set()
                    process.kill()
                    return
                await asyncio.sleep(0.1)

        monitor = asyncio.create_task(monitor_output())
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=definition.timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            await self._remove_container(container_name)
            raise ProcessorBlocked(f"处理器超过 {definition.timeout_seconds} 秒执行上限") from exc
        finally:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor
        if quota_exceeded.is_set():
            await self._remove_container(container_name)
            raise ProcessorBlocked("处理器输出超过配置上限")
        stdout = SECRET_PATTERN.sub(
            r"\1\2[REDACTED]", stdout_bytes[-MAX_LOG_BYTES:].decode("utf-8", errors="replace")
        )
        stderr = SECRET_PATTERN.sub(
            r"\1\2[REDACTED]", stderr_bytes[-MAX_LOG_BYTES:].decode("utf-8", errors="replace")
        )
        if process.returncode != 0:
            raise ProcessorBlocked(f"处理器退出码 {process.returncode}: {stderr[-1000:]}")
        total = sum(path.stat().st_size for path in output_dir.rglob("*") if path.is_file())
        if total > definition.output_limit_mb * 1024 * 1024:
            raise ProcessorBlocked("处理器输出超过配置上限")
        result_path = output_dir / "result.json"
        if not result_path.is_file():
            raise ProcessorBlocked("处理器未生成 result.json")
        result = json.loads(result_path.read_text("utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("outputs"), dict):
            raise ProcessorBlocked("result.json 必须包含 outputs 对象")
        for name in result["outputs"].values():
            candidate = (output_dir / str(name)).resolve()
            if output_dir.resolve() not in candidate.parents or not candidate.is_file():
                raise ProcessorBlocked(f"处理器输出文件无效: {name}")
        return ProcessorRunResult(
            definition=definition,
            result=result,
            output_dir=output_dir,
            stdout=stdout,
            stderr=stderr,
            exit_code=process.returncode or 0,
        )

    @staticmethod
    def _seatbelt_literal(path: Path) -> str:
        return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')

    def _desktop_profile(self, input_dir: Path, output_dir: Path) -> str:
        """A deny-by-default profile for one disposable processor execution."""
        app_root = Path(__file__).resolve().parents[2]
        executable = Path(sys.executable).resolve()
        invoked_executable = Path(sys.executable)
        allow_read = [
            "/private/var/db",
            str(Path(sys.prefix).resolve()),
            # A uv/pyinstaller interpreter can resolve its standard library
            # from its base prefix rather than sys.prefix.
            str(Path(sys.base_prefix).resolve()),
            str(executable.parent),
            # Python resolves its current working directory while importing
            # the frozen worker. In a packaged app this is the application
            # resource root, not the user's home or data directory.
            str(app_root),
            str(input_dir.resolve()),
        ]
        read_rules = "\n".join(
            f'  (allow file-read* (subpath "{self._seatbelt_literal(Path(value))}"))'
            for value in allow_read
        )
        return "\n".join(
            [
                "(version 1)",
                "(deny default)",
                "(allow process-info*)",
                # NumPy reads OS/kernel identity during import; this exposes
                # no user data and is distinct from network access.
                "(allow sysctl-read)",
                # Permit macOS runtime reads, then immediately deny all user
                # and disposable data roots. More-specific allow rules below
                # re-open only the frozen interpreter, app resource root and
                # this execution's input directory.
                '(allow file-read* (subpath "/"))',
                f'  (deny file-read* (subpath "{self._seatbelt_literal(Path.home())}"))',
                '  (deny file-read* (subpath "/private/var"))',
                '  (deny file-read* (subpath "/private/tmp"))',
                # sandbox-exec still needs permission to launch the single,
                # application-owned Python worker. The profile grants no
                # process-fork permission, so user code cannot spawn helpers.
                f'  (allow process-exec (literal "{self._seatbelt_literal(executable)}"))',
                f'  (allow process-exec (literal "{self._seatbelt_literal(invoked_executable)}"))',
                # exec may replace the worker but cannot fork a child process;
                # the file and network policy remains deny-by-default.
                "(allow process-exec)",
                read_rules,
                f'  (allow file-write* (subpath "{self._seatbelt_literal(output_dir)}"))',
                # Python uses these device files for ordinary interpreter IO;
                # no user directory, socket or network permission is granted.
                '  (allow file-read* (literal "/dev/null"))',
                '  (allow file-write* (literal "/dev/null"))',
            ]
        )

    async def _run_desktop_sandbox(
        self,
        *,
        bundle_path: Path,
        request: dict[str, Any],
        input_files: dict[str, Path],
        execution_dir: Path,
    ) -> ProcessorRunResult:
        definition, _digest = inspect_processor_bundle(bundle_path.read_bytes())
        if sys.platform == "win32":
            raise ProcessorBlocked("Windows 原生安全执行器尚未提供；自定义处理器不可用")
        if not await self.available():
            raise ProcessorBlocked("桌面安全执行器不可用；macOS 需要 sandbox-exec")
        input_dir = execution_dir / "input"
        bundle_dir = input_dir / "bundle"
        files_dir = input_dir / "files"
        output_dir = execution_dir / "output"
        if execution_dir.exists():
            shutil.rmtree(execution_dir)
        files_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        output_dir.chmod(0o700)
        extract_processor_bundle(bundle_path, bundle_dir)
        mounted_files: dict[str, str] = {}
        for logical_name, source in input_files.items():
            target = files_dir / source.name
            shutil.copyfile(source, target)
            target.chmod(0o444)
            mounted_files[logical_name] = str(target)
        request_path = input_dir / "request.json"
        request_path.write_text(
            json.dumps({**request, "files": mounted_files}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        request_path.chmod(0o444)
        profile_path = execution_dir / "seatbelt.sb"
        profile_path.write_text(self._desktop_profile(input_dir, output_dir), encoding="utf-8")
        profile_path.chmod(0o400)
        if getattr(sys, "frozen", False):
            worker = [sys.executable, "processor-worker"]
        else:
            worker = [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "desktop" / "python_service.py"),
                "processor-worker",
            ]
        command = [
            "/usr/bin/sandbox-exec", "-f", str(profile_path), *worker,
            "--entrypoint", str(bundle_dir / definition.entrypoint),
            "--input", str(request_path), "--output", str(output_dir / "result.json"),
            "--cpu-seconds", str(max(1, definition.timeout_seconds)),
            "--memory-mb", str(definition.memory_mb),
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Python's importer may create a small temporary file before the
            # Worker clears its environment. Keep it inside the only writable
            # per-execution output directory.
            env={"PATH": "/usr/bin:/bin", "TMPDIR": str(output_dir)},
        )
        quota_exceeded = asyncio.Event()
        memory_exceeded = asyncio.Event()

        async def monitor_output() -> None:
            limit = definition.output_limit_mb * 1024 * 1024
            while process.returncode is None:
                total = sum(path.stat().st_size for path in output_dir.rglob("*") if path.is_file())
                if total > limit:
                    quota_exceeded.set()
                    process.kill()
                    return
                await asyncio.sleep(0.1)

        async def monitor_memory() -> None:
            # Seatbelt forbids child process creation, so this PID is the sole
            # untrusted process. macOS rejects RLIMIT_AS for this Python
            # runtime; the trusted parent therefore enforces the RSS cap.
            limit_kib = definition.memory_mb * 1024
            while process.returncode is None:
                try:
                    probe = await asyncio.create_subprocess_exec(
                        "/bin/ps", "-o", "rss=", "-p", str(process.pid),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    stdout, _ = await probe.communicate()
                    if int(stdout.decode("ascii", errors="ignore").strip() or "0") > limit_kib:
                        memory_exceeded.set()
                        process.kill()
                        return
                except (OSError, ValueError):
                    # A missed sample never provides a host-execution path;
                    # the timeout and all following samples still apply.
                    pass
                await asyncio.sleep(0.1)

        monitor = asyncio.create_task(monitor_output())
        memory_monitor = asyncio.create_task(monitor_memory())
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=definition.timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ProcessorBlocked(f"处理器超过 {definition.timeout_seconds} 秒执行上限") from exc
        finally:
            monitor.cancel()
            memory_monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor
            with suppress(asyncio.CancelledError):
                await memory_monitor
        if quota_exceeded.is_set():
            raise ProcessorBlocked("处理器输出超过配置上限")
        if memory_exceeded.is_set():
            raise ProcessorBlocked("处理器超过配置内存上限")
        stdout = SECRET_PATTERN.sub(r"\1\2[REDACTED]", stdout_bytes[-MAX_LOG_BYTES:].decode("utf-8", errors="replace"))
        stderr = SECRET_PATTERN.sub(r"\1\2[REDACTED]", stderr_bytes[-MAX_LOG_BYTES:].decode("utf-8", errors="replace"))
        if process.returncode != 0:
            raise ProcessorBlocked(f"桌面安全执行器退出码 {process.returncode}: {stderr[-1000:]}")
        total = sum(path.stat().st_size for path in output_dir.rglob("*") if path.is_file())
        if total > definition.output_limit_mb * 1024 * 1024:
            raise ProcessorBlocked("处理器输出超过配置上限")
        result_path = output_dir / "result.json"
        if not result_path.is_file():
            raise ProcessorBlocked("处理器未生成 result.json")
        result = json.loads(result_path.read_text("utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("outputs"), dict):
            raise ProcessorBlocked("result.json 必须包含 outputs 对象")
        for name in result["outputs"].values():
            candidate = (output_dir / str(name)).resolve()
            if output_dir.resolve() not in candidate.parents or not candidate.is_file():
                raise ProcessorBlocked(f"处理器输出文件无效: {name}")
        return ProcessorRunResult(
            definition=definition,
            result=result,
            output_dir=output_dir,
            stdout=stdout,
            stderr=stderr,
            exit_code=process.returncode or 0,
        )

    async def _remove_container(self, name: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                self.runtime,
                "rm",
                "--force",
                name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=5)
        except (FileNotFoundError, TimeoutError, OSError):
            return

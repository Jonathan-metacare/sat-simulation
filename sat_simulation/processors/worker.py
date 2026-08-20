"""Entry point executed inside the desktop Seatbelt sandbox."""

from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path

try:  # This runner is deliberately available only for the macOS desktop app.
    import resource
except ImportError:  # pragma: no cover - Windows is fail-closed before execution
    resource = None  # type: ignore[assignment]


def main() -> None:
    parser = argparse.ArgumentParser(description="SpaceZenith processor sandbox worker")
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cpu-seconds", type=int, required=True)
    parser.add_argument("--memory-mb", type=int, required=True)
    parser.add_argument("--pids", type=int, default=32)
    args = parser.parse_args()

    if resource is None:
        raise RuntimeError("desktop processor worker is supported only on macOS")
    # Hard limits are set before loading untrusted code. Child code may lower
    # them, but cannot increase the hard ceiling. Do not attempt to raise a
    # stricter outer launcher limit (common for test runners and managed apps).
    def restrict(limit: int, value: int) -> None:
        _soft, inherited_hard = resource.getrlimit(limit)
        hard = value if inherited_hard == resource.RLIM_INFINITY else min(value, inherited_hard)
        resource.setrlimit(limit, (hard, hard))

    restrict(resource.RLIMIT_CPU, args.cpu_seconds)
    # macOS exposes RLIMIT_AS but rejects setting it for hardened interpreter
    # processes. The parent runner samples RSS and kills on this same limit;
    # keep the ceiling outside the untrusted process rather than weakening the
    # execution path with a best-effort host fallback.
    if hasattr(resource, "RLIMIT_NPROC"):
        restrict(resource.RLIMIT_NPROC, args.pids)
    # The parent derives these paths from packaged resources and this
    # execution's disposable directories. Preserve no other inherited
    # environment state for customer code.
    runtime_environment = {
        key: os.environ[key]
        for key in (
            "PROJ_DATA",
            "PROJ_LIB",
            "GDAL_DATA",
            "TMPDIR",
            "CPL_TMPDIR",
            "SQLITE_TMPDIR",
        )
        if key in os.environ
    }
    os.environ.clear()
    os.environ.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            **runtime_environment,
        }
    )
    entrypoint = Path(args.entrypoint).resolve()
    if not entrypoint.is_file():
        raise FileNotFoundError("processor entrypoint is missing")
    sys.argv = [str(entrypoint), "--input", args.input, "--output", args.output]
    runpy.run_path(str(entrypoint), run_name="__main__")


if __name__ == "__main__":
    main()

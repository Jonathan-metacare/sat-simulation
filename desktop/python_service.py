"""Frozen desktop entry point for the four local simulation services."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Satellite SIL desktop service")
    parser.add_argument("service", choices=("ground", "platform", "optical", "gpu", "processor-worker"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--entrypoint")
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--cpu-seconds", type=int)
    parser.add_argument("--memory-mb", type=int)
    arguments = parser.parse_args()

    if arguments.service == "processor-worker":
        from sat_simulation.processors.worker import main as worker_main

        required = ("entrypoint", "input", "output", "cpu_seconds", "memory_mb")
        if any(getattr(arguments, item) is None for item in required):
            parser.error("processor-worker requires entrypoint, input, output, cpu and memory limits")
        import sys

        sys.argv = [
            sys.argv[0], "--entrypoint", arguments.entrypoint, "--input", arguments.input,
            "--output", arguments.output, "--cpu-seconds", str(arguments.cpu_seconds),
            "--memory-mb", str(arguments.memory_mb),
        ]
        worker_main()
        return

    if arguments.port is None:
        parser.error("service port is required")
    # Keep imports after argument parsing: Settings reads the environment when
    # service modules are imported, and Electron supplies per-run addresses.
    if arguments.service == "ground":
        from sat_simulation.services.ground import app
    elif arguments.service == "platform":
        from sat_simulation.services.platform import app
    elif arguments.service == "optical":
        from sat_simulation.services.optical import app
    else:
        from sat_simulation.services.gpu import app

    import uvicorn

    uvicorn.run(app, host=arguments.host, port=arguments.port, log_level="info")


if __name__ == "__main__":
    main()

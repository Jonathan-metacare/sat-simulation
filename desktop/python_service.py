"""Frozen desktop entry point for the three local simulation services."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Satellite SIL desktop service")
    parser.add_argument("service", choices=("ground", "platform", "gpu"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    arguments = parser.parse_args()

    # Keep imports after argument parsing: Settings reads the environment when
    # service modules are imported, and Electron supplies per-run addresses.
    if arguments.service == "ground":
        from sat_simulation.services.ground import app
    elif arguments.service == "platform":
        from sat_simulation.services.platform import app
    else:
        from sat_simulation.services.gpu import app

    import uvicorn

    uvicorn.run(app, host=arguments.host, port=arguments.port, log_level="info")


if __name__ == "__main__":
    main()

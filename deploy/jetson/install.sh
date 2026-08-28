#!/usr/bin/env bash
set -euo pipefail

root="${1:-/opt/spacezenith-sim}"
[[ "$(uname -m)" == "aarch64" ]] || { echo "Jetson install requires aarch64" >&2; exit 1; }
command -v python3.12 >/dev/null || { echo "Python 3.12 is required" >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker is required for custom L1 processors" >&2; exit 1; }
command -v ollama >/dev/null || { echo "Ollama is required" >&2; exit 1; }
[[ -d "$root" ]] || { echo "Project checkout is missing: $root" >&2; exit 1; }
avail_kb="$(df -Pk "$root" | awk 'NR==2 {print $4}')"
[[ "$avail_kb" -ge 10485760 ]] || { echo "At least 10 GiB free disk is required" >&2; exit 1; }

sudo install -d -o spacezenith -g spacezenith /var/lib/spacezenith-sim/gpu
python3.12 -m venv "$root/.venv"
"$root/.venv/bin/pip" install --upgrade pip
"$root/.venv/bin/pip" install "$root"
sudo install -m 0640 deploy/jetson/spacezenith-gpu.env.example /etc/spacezenith-gpu.env
sudo install -m 0644 deploy/jetson/spacezenith-gpu.service /etc/systemd/system/spacezenith-gpu.service
sudo systemctl daemon-reload
sudo systemctl enable --now spacezenith-gpu
deploy/jetson/healthcheck.sh
echo "Build the ARM64 custom processor image before accepting custom L1 ZIPs:"
echo "  docker build -t spacezenith/processor-python:3.12 processor-runtime"

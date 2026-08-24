#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 [image-archive]"
  exit 0
fi

bundle_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
archive="${1:-$(find "$bundle_dir" -maxdepth 1 -name 'spacezenith-sim-*-linux-arm64.tar' -print -quit)}"

[[ "$(uname -m)" == "aarch64" ]] || { echo "Jetson deployment requires aarch64" >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
[[ -n "$archive" && -f "$archive" ]] || { echo "Image archive not found" >&2; exit 1; }
[[ -f "$bundle_dir/spacezenith-gpu.env" ]] || { echo "Missing $bundle_dir/spacezenith-gpu.env" >&2; exit 1; }

sudo install -d -m 0755 /var/lib/spacezenith-sim
docker load -i "$archive"
docker compose -f "$bundle_dir/docker-compose.yml" --env-file "$bundle_dir/spacezenith-gpu.env" up -d --force-recreate
"$bundle_dir/healthcheck.sh"

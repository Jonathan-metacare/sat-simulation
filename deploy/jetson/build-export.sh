#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 [version] [output-directory]"
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
version="${1:-$(python3 -c 'from pathlib import Path; import re, sys; print(re.search(r"version = \"([^\"]+)\"", Path(sys.argv[1]).read_text()).group(1))' "$root/pyproject.toml")}" 
output_dir="${2:-$root/release/jetson-${version}-linux-arm64}"
api_image="spacezenith/sim-gpu-api:${version}"
processor_image="spacezenith/processor-python:3.12"

command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
mkdir -p "$output_dir"

docker buildx build --platform linux/arm64 --load \
  -f "$root/deploy/jetson/gpu-api.Dockerfile" \
  -t "$api_image" "$root"
docker buildx build --platform linux/arm64 --load \
  -f "$root/processor-runtime/Dockerfile" \
  -t "$processor_image" "$root/processor-runtime"

architecture="$(docker image inspect "$api_image" --format '{{.Os}}/{{.Architecture}}')"
[[ "$architecture" == "linux/arm64" ]] || { echo "Expected linux/arm64 image, got $architecture" >&2; exit 1; }

docker save -o "$output_dir/spacezenith-sim-${version}-linux-arm64.tar" "$api_image" "$processor_image"
install -m 0644 "$root/deploy/jetson/docker-compose.yml" "$output_dir/docker-compose.yml"
sed "s#^SAT_SIM_GPU_API_IMAGE=.*#SAT_SIM_GPU_API_IMAGE=$api_image#" \
  "$root/deploy/jetson/spacezenith-gpu.env.example" > "$output_dir/spacezenith-gpu.env"
# The embedded payload is read from the installed desktop App. It contains no
# credentials, so it must remain readable after the DMG is installed by a
# different macOS user.
chmod 0644 "$output_dir/spacezenith-gpu.env"
install -m 0755 "$root/deploy/jetson/import-run.sh" "$output_dir/import-run.sh"
install -m 0755 "$root/deploy/jetson/healthcheck.sh" "$output_dir/healthcheck.sh"
python3 - "$output_dir/payload.json" "$version" "$api_image" "$processor_image" <<'PY'
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text(json.dumps({
    "version": sys.argv[2],
    "architecture": "linux/arm64",
    "api_image": sys.argv[3],
    "processor_image": sys.argv[4],
}, indent=2) + "\n")
PY
(
  cd "$output_dir"
  if command -v sha256sum >/dev/null; then
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print | sort | xargs sha256sum > SHA256SUMS
  else
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print | sort | while IFS= read -r file; do shasum -a 256 "$file"; done > SHA256SUMS
  fi
)

echo "Jetson offline bundle created: $output_dir"

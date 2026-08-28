#!/usr/bin/env bash
set -euo pipefail

# Publish the two ARM64 images required by the Jetson GPU payload.
#
# Prerequisite:
#   docker login crpi-c6dvreur2lrd29ve.cn-beijing.personal.cr.aliyuncs.com
#
# Usage:
#   ./deploy/jetson/publish-images.sh [version] [gpu-api-image-name] [processor-image-name]
#
# Example:
#   ./deploy/jetson/publish-images.sh 0.1.2 spacezenith-sim-gpu-api spacezenith-processor-python
#
# The optional image-name arguments are the names after the `deepagent/` path.
# Override REGISTRY_NAMESPACE when publishing to a different registry namespace.
# Aliyun Personal Edition does not accept Buildx OCI attestation manifests, so
# this script intentionally disables provenance/SBOM and publishes Docker v2
# compatible image media types.

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '3,16p' "$0"
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
registry_namespace="${REGISTRY_NAMESPACE:-crpi-c6dvreur2lrd29ve.cn-beijing.personal.cr.aliyuncs.com/deepagent}"
version="${1:-$(python3 -c 'from pathlib import Path; import re, sys; print(re.search(r"version = \"([^\"]+)\"", Path(sys.argv[1]).read_text()).group(1))' "$root/pyproject.toml")}"
api_name="${2:-spacezenith-sim-gpu-api}"
processor_name="${3:-spacezenith-processor-python}"
processor_tag="${PROCESSOR_TAG:-3.12-${version}}"

[[ "$version" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "Invalid version: $version" >&2; exit 1; }
[[ "$api_name" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || { echo "Invalid GPU API image name: $api_name" >&2; exit 1; }
[[ "$processor_name" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || { echo "Invalid processor image name: $processor_name" >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
docker buildx version >/dev/null || { echo "Docker Buildx is required" >&2; exit 1; }

api_image="${registry_namespace}/${api_name}:${version}"
processor_image="${registry_namespace}/${processor_name}:${processor_tag}"

echo "Publishing linux/arm64 GPU API image: $api_image"
docker buildx build --platform linux/arm64 \
  --provenance=false --sbom=false \
  --output type=image,push=true,oci-mediatypes=false \
  -f "$root/deploy/jetson/gpu-api.Dockerfile" \
  -t "$api_image" \
  "$root"

echo "Publishing linux/arm64 L1 processor image: $processor_image"
docker buildx build --platform linux/arm64 \
  --provenance=false --sbom=false \
  --output type=image,push=true,oci-mediatypes=false \
  -f "$root/processor-runtime/Dockerfile" \
  -t "$processor_image" \
  "$root/processor-runtime"

cat <<EOF

Published successfully. For a registry-based Jetson deployment, set these in
spacezenith-gpu.env, then run docker compose pull && docker compose up -d:

SAT_SIM_GPU_API_IMAGE=$api_image
SAT_SIM_PROCESSOR_IMAGE=$processor_image
EOF

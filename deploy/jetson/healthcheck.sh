#!/usr/bin/env bash
set -euo pipefail
endpoint="${1:-http://127.0.0.1:8002}"
health="$(curl --fail --silent --show-error "$endpoint/health")"
python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"] == "ok"; assert value["processor_runtime"] == "ready"' <<<"$health"
echo "$health"

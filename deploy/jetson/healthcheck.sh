#!/usr/bin/env bash
set -euo pipefail

endpoint="${1:-http://127.0.0.1:8002}"
attempts="${SAT_SIM_HEALTHCHECK_ATTEMPTS:-30}"
interval_seconds="${SAT_SIM_HEALTHCHECK_INTERVAL_SECONDS:-1}"

for ((attempt = 1; attempt <= attempts; attempt++)); do
  if health="$(curl --fail --silent "$endpoint/health" 2>/dev/null)"; then
    if python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"] == "ok"; assert value["processor_runtime"] == "ready"' <<<"$health"; then
      echo "$health"
      exit 0
    fi
  fi

  if ((attempt < attempts)); then
    sleep "$interval_seconds"
  fi
done

echo "GPU API did not become healthy at $endpoint after $attempts attempts." >&2
exit 1

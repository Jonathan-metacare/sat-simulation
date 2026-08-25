# Jetson Orin GPU Payload

Jetson runs one persistent `gpu-api` Docker container. Ollama remains a
host-managed service on `127.0.0.1:11434`. For each custom L1 request, the API
uses the host Docker daemon to create a separate, restricted code-run container.
The Mac sends `L1_JOB` and `AI_EXECUTE` to Jetson port `9101`; a custom L1 ZIP is
included in its `L1_JOB` GTX payload, verified by SHA-256, and used only for that
mission. The API listens on `8002` only for health and model discovery and returns
products to the callback address embedded in every job.

## Build and export on an Apple Silicon Mac

Docker Desktop must be running. Build a Linux ARM64 offline bundle:

```bash
./deploy/jetson/build-export.sh
```

The bundle is written to `release/jetson-<version>-linux-arm64/` and contains
both images, Compose configuration, runtime environment file, checksum and the
Jetson import script. Copy this entire directory to Jetson.

## Import and run on Jetson

Jetson needs only Docker Engine with the Compose plugin, Docker running, and
host-managed Ollama. It does not need a project checkout, Python, a venv, a
`spacezenith` user or the legacy systemd service.

1. Install and start Ollama, then pull the configured vision model, for example
   `ollama pull qwen3-vl:8b`. Do not expose Ollama to the LAN.
2. In the transferred bundle, edit `spacezenith-gpu.env` if the model, image tag
   or timeout needs changing.
3. Run `./import-run.sh`. It imports both ARM64 images, creates
   `/var/lib/spacezenith-sim`, force-recreates `gpu-api` with restart policy,
   then waits for `http://127.0.0.1:8002/health` to be ready (30 one-second
   attempts by default).
4. On the Mac choose **Jetson GPU**, enter the Jetson LAN address and the Mac
   LAN address that Jetson can call back. Select a visual model after saving.

The GPU API container mounts `/var/run/docker.sock` to launch restricted custom
L1 code-run containers. It also mounts `/var/lib/spacezenith-sim` at exactly the
same path as the Jetson host; do not change only one side of this mapping.

Firewall policy: allow Jetson `8002/tcp` and `9101/tcp` only from the Mac LAN
address; allow Mac `9102/tcp` only from the Jetson. Do not expose either port to
the public internet. The desktop App and GPU API image versions must match.

`install.sh` and `spacezenith-gpu.service` remain only for migration reference;
new deployments use the offline Docker bundle.

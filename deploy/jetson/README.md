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
both images, Compose configuration, runtime environment file, payload metadata,
a complete checksum manifest and the Jetson import script. It can be used for
manual air-gapped deployment or embedded into the macOS desktop DMG.

## Desktop offline deployment

The macOS Apple Silicon production DMG embeds the matching ARM64 offline bundle.
In **Settings → AI → Jetson GPU**, the deployment wizard uploads the bundle,
checks every SHA-256 digest on Jetson, imports the images with `docker load`,
starts the GPU API and verifies the GTX callback. No registry address, Docker
login or Jetson image download is used. The DMG increases by roughly 380–400 MB.

Docker, Compose and Ollama remain Jetson host dependencies. **Initialize +
deploy** may install them from the network; Ollama models are also not embedded
and are downloaded when first selected.

## Publish ARM64 images to Aliyun Container Registry

Publish the GPU API and its matching L1 processor runtime together:

```bash
./deploy/jetson/publish-images.sh 0.1.2 spacezenith-sim-gpu-api spacezenith-processor-python
```

The two optional names become the image names below `deepagent/`. This is an
internal publishing tool and is not used by the customer desktop deployment.

## Import and run on Jetson

Jetson needs only Docker Engine with the Compose plugin, Docker running, and
host-managed Ollama. It does not need a project checkout, Python, a venv, a
`spacezenith` user or the legacy systemd service.

1. Install and start Ollama. Do not expose Ollama to the LAN. After the desktop
   has deployed, use Settings → AI to install and select a vision model (for
   example `qwen3-vl:8b`).
2. In the transferred bundle, edit `spacezenith-gpu.env` if the model or timeout
   needs changing.
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

`install.sh` and `spacezenith-gpu.service` remain only for migration reference.
New normal deployments use the DMG's embedded offline payload.

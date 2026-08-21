# Jetson Orin GPU Payload

Run this service only on a trusted LAN.  The Mac sends `L1_JOB` and `AI_EXECUTE`
to Jetson port `9101`; Jetson returns products to the callback address embedded
in each job.  The Jetson API listens on `8002`.

1. Create the `spacezenith` system user, clone this exact application version to
   `/opt/spacezenith-sim`, and build the ARM64 processor runtime image:
   `docker build -t spacezenith/processor-python:3.12 processor-runtime`.
2. Copy and edit `spacezenith-gpu.env.example`.  Keep Ollama at
   `127.0.0.1:11434`; do not expose it to the LAN.
3. From the checkout run `deploy/jetson/install.sh`.
4. On the Mac choose **Jetson GPU**, enter the Jetson LAN address and the Mac
   LAN address that Jetson can call back.  Select a visual model after saving.

Firewall policy: allow Jetson `8002/tcp` and `9101/tcp` only from the Mac LAN
address; allow Mac `9102/tcp` only from the Jetson.  Do not expose either port
to the public internet.  The desktop version and Jetson service version must
match exactly; remote use should be blocked if they differ.

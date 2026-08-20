# Python processor SDK v1

A customer processor is a ZIP containing `processor.yaml` and a Python 3.12 entrypoint.
The Optical/GPU processor workspace exposes the same executable SDK source used by the
read-only built-in defaults. Creating a custom version clones that working default, so it
can run unchanged or be modified by replacing helper functions. The application owns
`main()` and the manifest contract. Third-party wheels are not accepted in desktop custom
versions. ZIP paths must be relative; symlinks, duplicate
members, traversal, unknown manifest fields and bundles over the configured limits
are rejected before the bundle reaches Optical or GPU.

```yaml
schema_version: 1
id: customer-l0
name: Customer L0 reconstruction
version: 1.0.0
stage: l0 # or l1
entrypoint: processor.py
timeout_seconds: 120
cpu_limit: 1.0
memory_mb: 1024
output_limit_mb: 1024
```

The entrypoint is invoked as:

```text
python processor.py --input /workspace/input/request.json \
  --output /workspace/output/result.json
```

`request.json` contains stage metadata and a `files` object whose values point to
read-only files in the per-execution input directory. The program may write only under
the per-execution output directory. It must atomically finish by writing `result.json`:

```json
{"outputs":{"l0":"l0.npy"}}
```

L0 receives the OPTR packet stream, packet layout, frozen sensor parameters and
capture metadata; `l0.npy` must be a `uint16` array shaped `[bands,height,width]`.
Each packet uses network-order `!4sHHII` (`OPTR`, band, row, payload bytes, CRC32C)
followed by big-endian uint16 row samples.

L1 receives `l0.npy` plus an ancillary JSON file with capture time, orbit, attitude,
quaternion, pointing error, CRS, affine transform, dimensions and sensor settings.
It must return `l1a` and `l1b` GeoTIFF paths:

```json
{"outputs":{"l1a":"l1a.tif","l1b":"l1b.tif"}}
```

The host ignores processor-provided checksums and manifests. It validates files,
recomputes SHA-256, creates lineage/quality manifests, thumbnail and STAC, and then
transmits products on the simulated link. stdout/stderr are truncated and fields
that resemble keys, tokens, secrets, authorization or passwords are redacted.

On macOS desktop, the app launches this code with a Seatbelt profile: networking,
the home directory, application data, Docker sockets and child-process creation are
denied. The only writable location is the execution output directory; timeout, output
quota and parent-enforced RSS limits are applied. If the app-managed runner fails its
self-check, the mission blocks rather than executing the ZIP with host privileges.

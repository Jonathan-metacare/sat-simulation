# Custom processing validation assets

Run from the repository root:

```bash
uv run python scripts/generate_custom_processing_examples.py
```

It writes the following import-ready files to `examples/custom-processing/dist/`:

- `demo-seattle-custom-input-16bit.tif`: deterministic 384 × 384, three-band,
  uint16 GeoTIFF in EPSG:4326.
- `demo-custom-l0-processor.zip`: validates and reconstructs OPTR RAW packets
  into `uint16 [band, height, width]` L0 NumPy data.
- `demo-custom-l1-processor.zip`: creates L1A DN GeoTIFF and calibrated L1B
  GeoTIFF from L0 plus frozen ancillary data.

Import the GeoTIFF from **Optical → Optical Scene Input**. Upload the L0 ZIP in
**Optical → L0 Processor → Customized Processing**, and the L1 ZIP in
**GPU Payload → L1 Processor → Customized Processing**. Each ZIP requires the
local OCI runtime and `spacezenith/processor-python:3.12` image.

# Optical product definitions

- RAW: row/band detector packets with synchronization, sequence, length and CRC.
- L0: reconstructed full-resolution detector DN with communication artifacts and
  duplicate packets removed.
- L1A: L0 pixels plus UTC capture time, calibration parameters, CRS, transform,
  orbit and attitude metadata; calibration is not applied.
- L1B: dark/offset/gain and bad-pixel correction applied, expressed as normalized
  sensor radiance in a georeferenced Cloud Optimized GeoTIFF.

Each product has SHA-256, lineage, processing parameters and quality fields. The
STAC 1.1 Item connects RAW, L0, L1A, L1B and the PNG browse image. The generated
fixture is deterministic and contains no third-party imagery.

RAW/L0/L1A/L1B are spacecraft products and are not automatically copied to the
ground. After AI completes, the next ground pass sends one result ZIP containing
AI JSON, mission summary and product catalog, STAC and thumbnail. The ZIP has an
outer SHA-256; `checksums.json` verifies every member before Ground publishes it.

# Custom processor source examples

This directory contains minimal L0 and L1 source examples for people extending
the App. The normal App workflow does not need these files: create a custom
processor from the in-app processor workspace, edit it there, then select it
for a scenario.

`l0_demo/` reconstructs OPTR RAW packets into `uint16 [band, height, width]`
L0 NumPy data. `l1_demo/` writes L1A DN GeoTIFF and calibrated L1B GeoTIFF from
L0 plus frozen ancillary data. The processor contract is documented in
[Processor SDK](../../docs/PROCESSOR_SDK.md).

Desktop custom processors use the built-in macOS Seatbelt runner. In Jetson
mode custom L1 uses the `spacezenith/processor-python:3.12` Docker runtime.

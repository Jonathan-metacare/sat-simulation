"""Reference custom L0 processor for SpaceZenith-Sim.

It reconstructs the OPTR RAW packet stream, validates CRC32C for every row,
deduplicates repeated packets, and writes the required uint16 NumPy product.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np


HEADER = struct.Struct("!4sHHII")
MAGIC = b"OPTR"


def crc32c(data: bytes) -> int:
    """CRC-32C (Castagnoli), matching the Optical RAW packet envelope."""
    value = 0xFFFFFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0x82F63B78 if value & 1 else 0)
    return value ^ 0xFFFFFFFF


def reconstruct(raw_path: Path, shape: tuple[int, int, int]) -> np.ndarray:
    output = np.zeros(shape, dtype=np.uint16)
    seen: set[tuple[int, int]] = set()
    with raw_path.open("rb") as stream:
        while header := stream.read(HEADER.size):
            if len(header) != HEADER.size:
                raise ValueError("truncated OPTR header")
            magic, band, row, size, checksum = HEADER.unpack(header)
            if magic != MAGIC:
                raise ValueError("invalid OPTR sync marker")
            if band >= shape[0] or row >= shape[1] or size != shape[2] * 2:
                raise ValueError(f"invalid packet coordinates or size: band={band}, row={row}")
            payload = stream.read(size)
            if len(payload) != size or crc32c(payload) != checksum:
                raise ValueError(f"CRC32C failure: band={band}, row={row}")
            key = (band, row)
            if key in seen:
                continue
            output[band, row] = np.frombuffer(payload, dtype=">u2").astype(np.uint16)
            seen.add(key)
    expected = shape[0] * shape[1]
    if len(seen) != expected:
        raise ValueError(f"incomplete RAW reconstruction: {len(seen)}/{expected} rows")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    shape = tuple(int(value) for value in request["raw_layout"]["shape"])
    raw_path = Path(request["files"]["raw"])
    output_path = Path(args.output).parent
    l0_name = "custom_l0.npy"
    np.save(output_path / l0_name, reconstruct(raw_path, shape), allow_pickle=False)
    Path(args.output).write_text(json.dumps({"outputs": {"l0": l0_name}}), encoding="utf-8")


if __name__ == "__main__":
    main()

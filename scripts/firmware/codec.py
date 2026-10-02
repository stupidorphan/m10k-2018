"""Codec and validation helpers for the M10K 2018 T17b image.

The vendor download is a byte-substituted representation of the raw Cortex-M
application. The substitution is a permutation, so decoding and encoding are
lossless. The packed SRAM initializer at the end of the image is also decoded
here so builders can validate endpoint descriptors without relying on IDA.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


IMAGE_LENGTH = 0x861C
APPLICATION_BASE = 0x08004000
SRAM_STREAM_OFFSET = 0x8360
SRAM_LENGTH = 0x898
PEN_INTERVAL_FILE_OFFSET = 0x83D1
PEN_INTERVAL_SRAM_OFFSET = 0x9F
STOCK_SHA256 = "A63A31E79FE556EA2E481046C5A536B1080E6673D0A6628E7A8DEDA3D3819504"
STOCK_MD5 = "C42DF3D2456A0B9DB13C106665B8337F"
MAP_PATH = Path(__file__).with_name("substitution_map.json")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest().upper()


def substitution_map(path: Path = MAP_PATH) -> tuple[int, ...]:
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or len(values) != 256:
        raise ValueError("the substitution map must contain 256 values")
    result = tuple(int(value) for value in values)
    if sorted(result) != list(range(256)):
        raise ValueError("the substitution map must be a permutation of 0..255")
    return result


def decode_image(raw: bytes, table: tuple[int, ...] | None = None) -> bytes:
    table = substitution_map() if table is None else table
    inverse = [0] * 256
    for plain, encoded in enumerate(table):
        inverse[encoded] = plain
    return bytes(inverse[value] for value in raw)


def encode_image(plain: bytes, table: tuple[int, ...] | None = None) -> bytes:
    table = substitution_map() if table is None else table
    return bytes(table[value] for value in plain)


def unpack_sram(image: bytes) -> bytes:
    """Expand the packed initializer stored at the end of the app image."""

    position = SRAM_STREAM_OFFSET
    output = bytearray()
    while len(output) < SRAM_LENGTH:
        if position >= len(image):
            raise ValueError("packed SRAM stream ended before reaching its output size")
        token = image[position]
        position += 1
        literal_count = token & 7
        if literal_count == 0:
            if position >= len(image):
                raise ValueError("missing extended literal count")
            literal_count = image[position]
            position += 1
        run_count = token >> 4
        if run_count == 0:
            if position >= len(image):
                raise ValueError("missing extended run count")
            run_count = image[position]
            position += 1
        if literal_count < 1 or position + literal_count - 1 > len(image):
            raise ValueError("invalid packed SRAM literal count")
        output.extend(image[position : position + literal_count - 1])
        position += literal_count - 1
        if token & 8:
            if position >= len(image):
                raise ValueError("missing packed SRAM back-reference distance")
            distance = image[position]
            position += 1
            if distance == 0 or distance > len(output):
                raise ValueError("invalid packed SRAM back-reference distance")
            for _ in range(run_count + 2):
                output.append(output[-distance])
        else:
            output.extend(bytes(run_count))
        if len(output) > SRAM_LENGTH:
            raise ValueError("packed SRAM output exceeds the expected size")
    if len(output) != SRAM_LENGTH or position != len(image):
        raise ValueError(
            f"packed SRAM consumed 0x{position:X} of 0x{len(image):X}, "
            f"producing 0x{len(output):X} bytes"
        )
    return bytes(output)


def vector_table(decoded: bytes) -> tuple[int, int]:
    if len(decoded) < 8:
        raise ValueError("image is shorter than the Cortex-M vector table")
    stack_pointer, reset_handler = struct.unpack_from("<II", decoded)
    if not 0x20000000 <= stack_pointer <= 0x20040000:
        raise ValueError(f"unexpected initial stack pointer 0x{stack_pointer:08X}")
    if not 0x08004000 <= reset_handler < 0x08020000:
        raise ValueError(f"unexpected reset handler 0x{reset_handler:08X}")
    return stack_pointer, reset_handler


def validate_stock(raw: bytes, *, require_hash: bool = True) -> bytes:
    if len(raw) != IMAGE_LENGTH:
        raise ValueError(f"expected {IMAGE_LENGTH} bytes, got {len(raw)}")
    if require_hash and (sha256(raw) != STOCK_SHA256 or md5(raw) != STOCK_MD5):
        raise ValueError(
            "input is not the verified official T17b 241030 image "
            f"(SHA-256 {sha256(raw)}, MD5 {md5(raw)})"
        )
    decoded = decode_image(raw)
    vector_table(decoded)
    if decoded[PEN_INTERVAL_FILE_OFFSET] != 2:
        raise ValueError("official EP82 bInterval byte is not 2 ms")
    sram = unpack_sram(decoded)
    expected = bytes.fromhex("07 05 82 03 10 00 02")
    if sram[0x99 : 0xA0] != expected:
        raise ValueError("official EP82 descriptor was not found in the packed initializer")
    return decoded

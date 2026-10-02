"""Build and validate the two documented T17b timing experiments.

The input must be the locally obtained official 241030 image. Generated
firmware is written to firmware/build by default, which is ignored by Git.
No firmware blob is downloaded or redistributed by this script.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.firmware.codec import (  # noqa: E402
    APPLICATION_BASE,
    PEN_INTERVAL_FILE_OFFSET,
    PEN_INTERVAL_SRAM_OFFSET,
    STOCK_SHA256,
    decode_image,
    encode_image,
    md5,
    sha256,
    substitution_map,
    unpack_sram,
    validate_stock,
    vector_table,
)


PROFILES = {
    "max-safe-retrack": {
        "stem": "M10K_2018_T17b_241030_MAX_SAFE_RETRACK_SKIP_EP82_1MS",
        "delays": (10, 10, 30, 60, 15),
        "branches": {
            0x0A76: (bytes.fromhex("00 F0"), bytes.fromhex("00 E0"), "IRQ debug path"),
            0x0C1E: (bytes.fromhex("62 78"), bytes.fromhex("30 E0"), "active-scan debug path"),
            0x2FFA: (bytes.fromhex("06 A1"), bytes.fromhex("03 E0"), "frequency debug path"),
            0x16D6: (bytes.fromhex("72 B6"), bytes.fromhex("04 E0"), "barrel-band redundant retrack"),
            0x1754: (bytes.fromhex("72 B6"), bytes.fromhex("04 E0"), "eraser-band redundant retrack"),
        },
    },
    "balanced": {
        "stem": "M10K_2018_T17b_241030_MAX_SAFE_RETRACK_SKIP_BALANCED_P7_M7_S20_W40_R10_EP82_1MS",
        "delays": (7, 7, 20, 40, 10),
        "branches": {
            0x0A76: (bytes.fromhex("00 F0"), bytes.fromhex("00 E0"), "IRQ debug path"),
            0x0C1E: (bytes.fromhex("62 78"), bytes.fromhex("30 E0"), "active-scan debug path"),
            0x2FFA: (bytes.fromhex("06 A1"), bytes.fromhex("03 E0"), "frequency debug path"),
            0x16D6: (bytes.fromhex("72 B6"), bytes.fromhex("04 E0"), "barrel-band redundant retrack"),
            0x1754: (bytes.fromhex("72 B6"), bytes.fromhex("04 E0"), "eraser-band redundant retrack"),
        },
    },
}


DELAY_PATCHES = (
    ("pre-acquisition", 0x0CDA, 0x1B),
    ("optional-pressure", 0x0CE8, 0x14),
    ("switch-settle", 0x0CF8, 0x42),
    ("wide-recovery", 0x0D38, 0x78),
    ("normal-recovery", 0x0D40, 0x1E),
)


def apply_profile(stock: bytes, profile_name: str) -> tuple[bytes, list[str]]:
    profile = PROFILES[profile_name]
    patched = bytearray(stock)
    changes: list[str] = []

    if patched[PEN_INTERVAL_FILE_OFFSET] != 2:
        raise ValueError("expected stock EP82 bInterval 2 ms")
    patched[PEN_INTERVAL_FILE_OFFSET] = 1
    changes.append(f"0x{PEN_INTERVAL_FILE_OFFSET:04X}: EP82 bInterval 2 -> 1")

    for (label, offset, expected), value in zip(DELAY_PATCHES, profile["delays"]):
        if patched[offset : offset + 2] != bytes((expected, 0x20)):
            actual = patched[offset : offset + 2].hex(" ")
            raise ValueError(f"unexpected {label} instruction at 0x{offset:04X}: {actual}")
        if not 1 <= value <= 0xFF:
            raise ValueError(f"{label} value does not fit a Thumb MOVS immediate")
        patched[offset] = value
        changes.append(f"0x{offset:04X}: {label} {expected:#04x} -> {value:#04x}")

    for offset, (old, new, label) in profile["branches"].items():
        if patched[offset : offset + len(old)] != old:
            actual = patched[offset : offset + len(old)].hex(" ")
            raise ValueError(f"unexpected {label} instruction at 0x{offset:04X}: {actual}")
        patched[offset : offset + len(new)] = new
        changes.append(f"0x{offset:04X}: {label}")

    return bytes(patched), changes


def validate_candidate(stock: bytes, candidate: bytes, profile_name: str) -> None:
    if len(candidate) != len(stock):
        raise ValueError("candidate length changed")
    changed = [index for index, pair in enumerate(zip(stock, candidate)) if pair[0] != pair[1]]
    allowed = {PEN_INTERVAL_FILE_OFFSET}
    allowed.update(offset for _, offset, _ in DELAY_PATCHES)
    for offset, (old, new, _) in PROFILES[profile_name]["branches"].items():
        allowed.update(range(offset, offset + len(new)))
    if not set(changed).issubset(allowed):
        unexpected = sorted(set(changed) - allowed)
        raise ValueError(f"unexpected decoded changes: {unexpected}")

    stock_sram = unpack_sram(stock)
    candidate_sram = unpack_sram(candidate)
    sram_changed = [
        index for index, pair in enumerate(zip(stock_sram, candidate_sram)) if pair[0] != pair[1]
    ]
    if sram_changed != [PEN_INTERVAL_SRAM_OFFSET]:
        raise ValueError(f"unexpected packed-SRAM changes: {sram_changed}")
    if candidate_sram[0x99 : 0xA0] != bytes.fromhex("07 05 82 03 10 00 01"):
        raise ValueError("candidate EP82 descriptor did not become 1 ms")
    vector_table(candidate)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="official 241030 image")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="max-safe-retrack",
        help="documented experiment to build",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("firmware/build"))
    args = parser.parse_args()

    raw = args.input.read_bytes()
    if sha256(raw) != STOCK_SHA256:
        raise SystemExit(
            "Refusing input: expected official SHA-256 "
            f"{STOCK_SHA256}, got {sha256(raw)}"
        )
    stock = validate_stock(raw)
    candidate_plain, changes = apply_profile(stock, args.profile)
    candidate_raw = encode_image(candidate_plain, substitution_map())
    round_trip = decode_image(candidate_raw, substitution_map())
    if round_trip != candidate_plain:
        raise SystemExit("encode/decode round-trip failed")
    validate_candidate(stock, candidate_plain, args.profile)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = PROFILES[args.profile]["stem"]
    raw_path = args.output_dir / f"{stem}.bin"
    plain_path = args.output_dir / f"{stem}.decrypted.bin"
    raw_path.write_bytes(candidate_raw)
    plain_path.write_bytes(candidate_plain)

    stack, reset = vector_table(candidate_plain)
    print(f"Profile: {args.profile}")
    print(f"Input SHA-256: {sha256(raw)}")
    print(f"Application base: 0x{APPLICATION_BASE:08X}")
    print(f"Vector table: SP=0x{stack:08X}, Reset=0x{reset:08X}")
    print(f"Encrypted output: {raw_path}")
    print(f"  size={len(candidate_raw)} md5={md5(candidate_raw)} sha256={sha256(candidate_raw)}")
    print(f"Decoded output: {plain_path}")
    print(f"  size={len(candidate_plain)} md5={md5(candidate_plain)} sha256={sha256(candidate_plain)}")
    print("Validated changes:")
    for change in changes:
        print(f"  {change}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

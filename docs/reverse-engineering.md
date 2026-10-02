# Reverse-engineering notes

These notes describe the 2026-09-28 analysis of the Gaomon M10K 2018 image
whose vendor filename is M10K 2018 OEM02 T17b_241030.bin.

## IDA configuration

Load the image as a raw ARM little-endian binary:

* Processor: ARM 32-bit, Cortex-M4 class
* Instruction set: Thumb / Thumb-2
* Load address: 0x08004000
* Initial stack pointer: 0x20000E58
* Reset vector: 0x08004165 (Thumb state)

Opening this application as x64, x86 code, or 16-bit code produces misleading
cross-references. The image is the application after a 16 KiB bootloader, not
the complete flash contents.

The 12 MHz crystal is configured to a 72 MHz system clock. USB full-speed is
derived at 48 MHz. The vendor file is 34,332 bytes (0x861C) and has these
hashes:

* MD5: C42DF3D2456A0B9DB13C106665B8337F
* SHA-256: A63A31E79FE556EA2E481046C5A536B1080E6673D0A6628E7A8DEDA3D3819504

## Byte substitution

The downloaded file is a byte-substituted image. Each byte is mapped through
a 256-value permutation. Applying its inverse exposes the ARM vector table and
application code. Applying the forward map reproduces the vendor form exactly.
The project keeps the map in scripts/firmware/substitution_map.json and tests
that it is a complete permutation.

The last 0x2BC bytes, file offsets 0x8360 through 0x861B, contain a packed
initializer that the reset code expands to 0x898 bytes at SRAM address
0x20000000. The codec validates token bounds and exact output size before a
candidate can be written.

The token format observed in this image is:

* low three bits: literal count minus one; zero takes an extended count byte
* high nibble: run count; zero takes an extended count byte
* bit 3 clear: append zero bytes
* bit 3 set: append a one-byte-distance back-reference

Important expanded endpoint records are:

| SRAM offset | Bytes | Meaning |
| ---: | --- | --- |
| 0x79 | 07 05 81 03 40 00 02 | endpoint 0x81, 64-byte digitizer path, 2 ms |
| 0x80 | 07 05 01 03 08 00 01 | endpoint 0x01, 8-byte output path, 1 ms |
| 0x99 | 07 05 82 03 10 00 02 | endpoint 0x82, 16-byte pen/vendor path, 2 ms |

The final experiments change only the last record's interval byte, from 2 to 1.
The packed image therefore changes at file offset 0x83D1, flash address
0x0800C3D1, and expanded SRAM offset 0x9F.

## Report-production path

The steady loop begins around flash address 0x08007B04 (file offset 0x3B04).
The relevant calls identified in IDA are:

1. 0x08006C08 performs the pen and sensor sampling tick.
2. 0x0800793C handles mode transitions and conditional or keepalive reports.
3. 0x0800560C formats the HID packet.

There is no fixed delay corresponding to the old roughly 233 Hz observation.
The acquisition workload and USB scheduling dominate the observed rate.

The main acquisition work remains:

* five samples in the resonant-frequency tracker at 0x08006EE4
* seven-element Y window around 0x080071B0
* seven-element X window around 0x08007298
* seven-point peak searches and edge/center remapping

Changing scan counts without also changing the peak interpolation, edge
handling, and buffers would leave inconsistent state. The published builders
leave those structures and the HID report packing unchanged.

## Timing patches

sub_8004CC4 programs waits through a 72 MHz SysTick helper. The five immediate
values are therefore microseconds:

| Flash address | File offset | Stock | Conservative | Balanced |
| ---: | ---: | ---: | ---: | ---: |
| 0x08004CDA | 0x0CDA | 27 | 10 | 7 |
| 0x08004CE8 | 0x0CE8 | 20 | 10 | 7 |
| 0x08004CF8 | 0x0CF8 | 66 | 30 | 20 |
| 0x08004D38 | 0x0D38 | 120 | 60 | 40 |
| 0x08004D40 | 0x0D40 | 30 | 15 | 10 |

The conservative and balanced builders also replace three confirmed no-op
debug branches and skip two pressure-band resonance retracks that returned
without producing a report. These changes reduce repeated work while keeping
the five/seven/seven sampling topology.

The shorter 5/5/15/30/5 profile produced invalid coordinates and phantom
events on the test unit. It is intentionally absent from the supported build
profiles.

## What the interval change means

USB full-speed interrupt scheduling uses one-millisecond frames at the 1 ms
setting. That is a host polling ceiling. It does not create sensor samples and
does not prove a 700 Hz mode. The rate seen by an application also depends on
the sensor workload, packet availability, host batching, and the parser.

## Firmware identity

The tablet used for testing initially identified an older OEM02_T17b_190119
revision, while the downloaded target was OEM02_T17b_241030. The two should be
treated as separate firmware revisions until their compatibility is established
on the same hardware. This repository records the distinction so a future
experiment does not silently mix them.

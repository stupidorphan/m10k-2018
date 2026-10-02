# Gaomon M10K 2018 / T17b firmware research

This repository contains reproducible notes and tools from a reverse-engineering
session on one Gaomon M10K 2018 tablet. The target image identifies itself as
OEM02 / T17b / 241030 and runs on a GD32F350-class Cortex-M4.

The work is experimental. It documents how the image is decoded, how the
GD32 DFU interface was read and written, and how small binary patches affected
the measured report rate. It does not claim an official firmware, a universal
700 Hz mode, or a guaranteed fix for phantom input.

## Results at a glance

* The official application image is 34,332 bytes and loads at flash address
  0x08004000 after a 16 KiB bootloader.
* The vendor download uses a reversible 256-byte substitution permutation. It
  is not compression; decoding exposes a normal ARM vector table and code.
* The pen/vendor report path is interrupt endpoint 0x82. Its packed descriptor
  has a 2 ms interval in the stock image. Changing it to 1 ms raises the
  full-speed USB host scheduling ceiling to one frame, about 1 kHz.
* The sensor loop still performs five resonance samples and seven-sample X/Y
  windows. USB interval changes alone cannot make the MCU produce 700 or
 1000 fresh measurements per second.
* On the test unit, the conservative profile reached roughly 237–312 Hz and
  the shorter balanced profile reached roughly 312–350 Hz in
  OpenTabletDriver. These are single-device observations, not guarantees.
* The strongest phantom-input evidence came from an unresolved host/firmware
  interaction: the standard
  digitizer collection was silent while the vendor collection emitted
  zero-pressure packets that OpenTabletDriver's UCLogic parser classified as
  normal tablet reports. This needs a host-side fix investigation and
  controlled stock-versus-patched testing.

## Safety

Writing firmware can permanently disable the tablet. A failed write, wrong
hardware revision, power loss, or incompatible image may require hardware
recovery. Use the following safeguards:

1. Confirm that the tablet is an M10K 2018 / T17b unit.
2. Obtain the official image yourself and verify its hash.
3. Enter DFU mode and run the read-only probe before writing.
4. Save a full application backup before every write.
5. Keep the original vendor image and the verified readback offline.
6. Read the full recovery procedure before using the write switch.

The repository intentionally excludes vendor firmware, installers, drivers,
IDA databases, certificates, and machine-specific logs. It publishes hashes
and builders so another researcher can reproduce the work with files obtained
from a lawful source.

## Repository layout

* docs/reverse-engineering.md — image format, IDA setup, report path, and patch
  rationale.
* docs/dfu-protocol.md — the direct WinUSB/GD32 DFU transaction sequence.
* docs/experiments.md — dated profiles, hashes, observations, and reversions.
* docs/diagnostics.md — Raw Input and phantom-input investigation.
* firmware/ — ignored local input, generated candidates, and DFU backups.
* scripts/firmware/ — codec, packed-SRAM validator, manifest, and builders.
* scripts/flash/ — one hash-allow-listed PowerShell WinUSB flasher.
* scripts/diagnostics/ — read-only Windows Raw Input tools.
* tests/ — offline tests that use synthetic data and the substitution map.

## Quick start

The builder and codec run on Python 3.10 or newer. Raw Input diagnostics and
the flasher require Windows. Install the optional Windows dependency with:

~~~powershell
py -m pip install -r requirements.txt
~~~

Place the locally obtained official image in firmware/input and verify it:

~~~powershell
Get-FileHash firmware/input/M10K_2018_OEM02_T17b_241030.bin -Algorithm SHA256
~~~

The expected SHA-256 is
<code>A63A31E79FE556EA2E481046C5A536B1080E6673D0A6628E7A8DEDA3D3819504</code>.
The expected MD5 is
<code>C42DF3D2456A0B9DB13C106665B8337F</code>.

Build a candidate into the ignored firmware/build directory:

~~~powershell
python scripts/firmware/build_candidate.py --input firmware/input/M10K_2018_OEM02_T17b_241030.bin --profile max-safe-retrack
~~~

Use the balanced profile only as a research experiment:

~~~powershell
python scripts/firmware/build_candidate.py --input firmware/input/M10K_2018_OEM02_T17b_241030.bin --profile balanced
~~~

The builder refuses a wrong input hash, checks the decoded vector table,
decodes and re-encodes the image, checks the packed SRAM descriptor, and
asserts that only the documented offsets changed.

## Flashing

The flasher defaults to a read-only operation. It requires a local WinUSB
binding for the GD32 DFU interface and the device must enumerate as
VID_28E9&PID_0189. Driver installation is deliberately left as a user-reviewed
step; this repository does not ship a self-signed certificate or an old
GDDFU kernel driver.

Probe first:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/flash/flash_m10k.ps1 -FirmwarePath firmware/build/M10K_2018_T17b_241030_MAX_SAFE_RETRACK_SKIP_EP82_1MS.bin -ProbeOnly
~~~

Only after checking the probe output, use the explicit write switch:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/flash/flash_m10k.ps1 -FirmwarePath firmware/build/M10K_2018_T17b_241030_MAX_SAFE_RETRACK_SKIP_EP82_1MS.bin -Write
~~~

The script allow-lists image hashes from
scripts/firmware/image_manifest.json, validates the decoded vector table,
reads a full 0x861C-byte application backup, erases and writes only the
application range, and reads the complete range back before reporting success.
Reconnect the tablet normally only after the readback hash matches.

## Measuring reports

With the tablet in normal mode and the pen moving continuously:

~~~powershell
python scripts/diagnostics/inspect_m10k_raw_input.py
python scripts/diagnostics/measure_m10k_raw_input.py --seconds 15
~~~

For an idle/hover investigation, capture both Windows collections:

~~~powershell
python scripts/diagnostics/measure_m10k_collections.py --seconds 20
~~~

An idle standard digitizer collection can legitimately produce zero reports.
Use the vendor-collection result and OpenTabletDriver logs when diagnosing
phantom movement.

## Recovery

To recover, re-enter DFU with the tablet's upper-column keys 1 and 5 held while
reconnecting USB. Confirm VID_28E9&PID_0189, select the official image or a
previously verified candidate from your own local files, run the probe, and
write only after a full backup path has been chosen. Keep the resulting
readback and SHA-256 in your private recovery archive.

## Limitations and legal status

The measurements came from one unit and several firmware states. The
connected unit initially identified an older OEM02_T17b_190119 build while
the researched vendor image is OEM02_T17b_241030. A binary patch is not a
T17b source rebuild and does not establish compatibility with other revisions.
Report rates depend on sensor position, USB scheduling, host drivers, and the
tablet application.

This project is independent and unaffiliated with Gaomon Technology Co.,
Limited. See NOTICE.md for third-party and trademark notices, and
docs/experiments.md for the complete status of each tested profile.

# Experiment history

All rates below were measured on one M10K 2018 unit with OpenTabletDriver.
They describe observations during the 2026-09-28 session and are not
guarantees for other tablets, firmware revisions, USB hosts, or applications.

| Profile | Firmware changes | Observed result | Status |
| --- | --- | --- | --- |
| Official 241030 | Stock 2 ms EP82; 27/20/66/120/30 us waits | Around 160 Hz baseline in the original setup | Recovery input; hash in manifest |
| Aggressive | 1 ms EP82; 5/5/15/30/5 us waits | Invalid coordinates, clicks, and phantom movement | Rejected |
| Conservative retrack-skip | 1 ms EP82; 10/10/30/60/15 us waits; debug and redundant retrack skips | Roughly 237–312 Hz across runs | Last verified recovery image |
| Balanced retrack-skip | 1 ms EP82; 7/7/20/40/10 us waits; same skips | Roughly 312–350 Hz across runs | Experimental; restored |
| No-pen guard diagnostic | Balanced image plus a no-pen branch change at 0x0800C0C4 | Temporary diagnostic; not a validated fix | Flashed temporarily, then reverted |

## Hashes

The full image records are in scripts/firmware/image_manifest.json. The
official vendor input is 34,332 bytes:

* official encrypted SHA-256:
  A63A31E79FE556EA2E481046C5A536B1080E6673D0A6628E7A8DEDA3D3819504
* conservative encrypted SHA-256:
  F3728033BB43FD6D3B8B6B8076C67B832642B80E4FA40B5A75D4F05DA5DF1B2F
* conservative decoded SHA-256:
  CEDB64E12F5F10F0E21A511F81F0215D57C1CFF5EF7C5AE4229C4A2D63C25CE6
* balanced encrypted SHA-256:
  80DEA575ED96CD9B91970DB80F74649CA45369601F9DAF524DCA16BABE5EA8C4
* balanced decoded SHA-256:
  FF78291419F2B9538BFCA038B8581C52CB31C07B176DBE9B54450C8ABCCF4D32

The binary files are deliberately excluded from Git. They can be rebuilt from
the official image or kept in a private recovery archive.

## Reversion record

The balanced image was replaced with the conservative image through the direct
DFU path. The flasher saved the previous application before erasing and
verified the complete decoded readback after writing. The tablet was then
left in DFU until it was manually reconnected normally.

The measured phantom symptoms did not establish a firmware-only cause. A host
capture showed activity on OpenTabletDriver's vendor collection while the
standard digitizer collection was quiet. After the separate wireless mouse
receiver was switched off, the user still reported phantom movement; no
single capture proved the remaining source.

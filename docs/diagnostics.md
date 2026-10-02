# Diagnostics and phantom-input investigation

The diagnostics are read-only. They do not bind drivers, alter Windows Ink
settings, or write firmware.

## Collections

The M10K exposes two relevant HID collections in normal mode:

* MI_01, usage page 0x000D / usage 0x0002: standard Windows digitizer
* MI_00&Col01, usage page 0xFF00 / usage 0x0001: vendor collection opened by
  OpenTabletDriver

The tools recognize the normal M10K PIDs 0x006E and 0x006F. The standard
digitizer collection is not a complete measure of tablet activity.
An idle pen can produce zero MI_01 reports while the vendor collection continues
to emit reports.

Run the combined capture with the pen away:

~~~powershell
python scripts/diagnostics/measure_m10k_collections.py --seconds 20
~~~

Move the pen continuously for a rate measurement:

~~~powershell
python scripts/diagnostics/measure_m10k_raw_input.py --seconds 15
~~~

## Observed idle packet

One clean idle capture found approximately 0.4–0.47 vendor reports per second
with repeated 12-byte data such as:

    08 80 15 8b ac 63 00 00 00 00 00 00

The normal digitizer collection reported zero packets in the same interval.
OpenTabletDriver's UCLogic parser checks byte 1 for 0xC0 as out-of-range,
checks bit 6 for an auxiliary report, and otherwise constructs a normal
TabletReport. The 0x80 packet therefore falls through as a zero-pressure report
with coordinates 0x8B15 and 0x63AC. That is a plausible cause of a pointer
snapping to a previous location, but it remains a parser-level hypothesis until
the same test is run with the stock firmware and a parser filter.

The host-side captures also showed auxiliary or legacy absolute mouse events
while OpenTabletDriver was active. This means the firmware rate alone cannot
explain the pointer behavior. A future fix should classify confirmed no-pen
packets as out-of-range before absolute output.

## Confounders

One capture also found a separate 2.4 GHz HID receiver with VID 0x1D57 and
PID 0xFA60 generating mouse reports. It was later switched off, while phantom
movement still occurred. External HID devices should still be disconnected
when reproducing the issue.

Windows Ink and TabletInputService were disabled during the investigation, but
that did not validate an Ink-related cause. OpenTabletDriver reads the vendor
HID collection directly.

## Reproduction checklist

1. Disconnect or switch off other mice and game controllers.
2. Record the tablet PID and OpenTabletDriver version.
3. Run the collection monitor with the pen away.
4. Record cursor movement separately from Raw Input reports.
5. Repeat with the official firmware.
6. Repeat with a parser change that ignores a confirmed zero-pressure 0x80
   packet.
7. Compare reports, cursor events, and button events before testing another
   firmware image.

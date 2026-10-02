# WinUSB flasher

flash_m10k.ps1 is the only maintained writer in this repository. It uses the
GD32 USB DFU control requests directly through WinUSB, defaults to a
read-only probe, and requires the explicit Write switch before erasing flash.

The script expects a local firmware image and verifies its size, substitution
map, decoded Cortex-M vector table, and SHA-256 against the image manifest.
It saves a full application backup and compares a full post-write readback.

Driver binding is intentionally not automated here. Do not install an old
GDDFU kernel driver or trust an arbitrary self-signed certificate. If WinUSB
is already bound to VID_28E9&PID_0189, the probe can run without any driver
files from this repository.

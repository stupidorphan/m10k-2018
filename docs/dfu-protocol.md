# Direct GD32 DFU protocol

The maintained flasher uses WinUSB and the standard GD32 USB DFU control
requests. It does not use the older GDDFU kernel driver.

## Device and interface

* DFU mode: VID 0x28E9, PID 0x0189
* WinUSB interface class GUID:
  573E8C73-0CB4-4471-A1BF-FAB26C31D384
* Application base: 0x08004000
* Application length: 0x861C bytes
* Normal application PIDs observed across revisions: 0x006E and 0x006F

Entering DFU on the tested M10K 2018 required holding the upper-column keys 1
and 5 while reconnecting USB. Confirm the VID/PID in Device Manager or with
PowerShell before sending a write request.

## Control requests

| Direction | Request | Request type | Purpose |
| --- | ---: | ---: | --- |
| IN | 3 | 0xA1 | GETSTATUS, six bytes |
| OUT | 1 | 0x21 | DNLOAD |
| IN | 2 | 0xA1 | UPLOAD |
| OUT | 4 | 0x21 | CLRSTATUS |
| OUT | 6 | 0x21 | ABORT |

The bootloader uses DFU states 2 (dfuIDLE), 4 (dfuDNLOAD-SYNC), and 5
(dfuDNLOAD-IDLE). State 10 is the error state and is rejected. The flasher
waits for the reported poll timeout after commands and refuses to continue
after a non-zero status.

## Read-only probe

Before every write, the script:

1. gets status and clears a previous error if needed;
2. sets the address pointer to 0x1FFFF800;
3. aborts back to dfuIDLE;
4. uploads option bytes from block 2;
5. checks for the GD32 signature A5 5A;
6. aborts back to dfuIDLE again.

This sequence performs no erase and no application write.

## Backup and write

The bootloader accepts block-0 commands:

* SET_ADDRESS_POINTER: 21 followed by a little-endian 32-bit address
* ERASE: 41 followed by a little-endian 32-bit address

The tested bootloader erases 0x400-byte sectors and accepts 0x400-byte
DNLOAD payloads. UPLOAD/readback uses 0x800-byte transfers. The maintained
flasher reads the complete 0x861C-byte application before erasing, writes only
0x08004000 through 0x0800C61B, then reads the same range back and compares its
SHA-256 to the decoded candidate. It tells the user to reconnect normally only
after that comparison succeeds.

The WinUSB binding is intentionally outside this repository's write path.
Do not install an unreviewed self-signed certificate or a legacy kernel driver
just to make the script run. A user who chooses to bind WinUSB should record
how to remove that binding afterward.

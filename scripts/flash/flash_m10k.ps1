[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FirmwarePath,
    [string]$BackupPath,
    [string]$ManifestPath,
    [int]$BackupLength = 34332,
    [switch]$Write,
    [switch]$ProbeOnly
)

$ErrorActionPreference = 'Stop'

if (-not $ManifestPath) {
    $ManifestPath = Join-Path $PSScriptRoot '..\firmware\image_manifest.json'
}

if ($Write -and $ProbeOnly) {
    throw 'Use either -Write or -ProbeOnly, not both.'
}
if ($BackupLength -lt 1 -or $BackupLength -gt 0x100000) {
    throw "BackupLength must be between 1 and 0x100000 bytes (got $BackupLength)."
}

# A write always takes a fresh readback first.  Keep the default beside the
# script so that an invocation cannot accidentally erase the only copy of the
# old application.
if ($Write -and [string]::IsNullOrWhiteSpace($BackupPath)) {
    $BackupPath = Join-Path $PSScriptRoot '..\..\firmware\backups\M10K_T17b_before_write_0x861C.bin'
}

# The local WinUSB INF registers the same interface GUID used by the GD32
# DFU driver.  This script talks to the DFU interface directly and does not
# depend on the revoked legacy GDDFUDriver.sys service.
if (-not ('GaomonWinUsbFlasherNative' -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class GaomonWinUsbFlasherNative
{
    private const uint DIGCF_PRESENT = 0x00000002;
    private const uint DIGCF_DEVICEINTERFACE = 0x00000010;
    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint OPEN_EXISTING = 3;
    private const uint FILE_FLAG_OVERLAPPED = 0x40000000;

    private static readonly Guid DfuInterfaceGuid =
        new Guid("573E8C73-0CB4-4471-A1BF-FAB26C31D384");

    [StructLayout(LayoutKind.Sequential)]
    private struct SP_DEVICE_INTERFACE_DATA
    {
        public int cbSize;
        public Guid InterfaceClassGuid;
        public int Flags;
        public IntPtr Reserved;
    }

    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    private struct WINUSB_SETUP_PACKET
    {
        public byte RequestType;
        public byte Request;
        public ushort Value;
        public ushort Index;
        public ushort Length;
    }

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr SetupDiGetClassDevs(
        ref Guid ClassGuid, string Enumerator, IntPtr hwndParent, uint Flags);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiEnumDeviceInterfaces(
        IntPtr DeviceInfoSet, IntPtr DeviceInfoData, ref Guid InterfaceClassGuid,
        uint MemberIndex, ref SP_DEVICE_INTERFACE_DATA DeviceInterfaceData);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiGetDeviceInterfaceDetail(
        IntPtr DeviceInfoSet, ref SP_DEVICE_INTERFACE_DATA DeviceInterfaceData,
        IntPtr DeviceInterfaceDetailData, int DeviceInterfaceDetailDataSize,
        out int RequiredSize, IntPtr DeviceInfoData);

    [DllImport("setupapi.dll", SetLastError = true)]
    private static extern bool SetupDiDestroyDeviceInfoList(IntPtr DeviceInfoSet);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFile(
        string lpFileName, uint dwDesiredAccess, uint dwShareMode,
        IntPtr lpSecurityAttributes, uint dwCreationDisposition,
        uint dwFlagsAndAttributes, IntPtr hTemplateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [DllImport("winusb.dll", SetLastError = true)]
    private static extern bool WinUsb_Initialize(
        IntPtr DeviceHandle, out IntPtr InterfaceHandle);

    [DllImport("winusb.dll", SetLastError = true)]
    private static extern bool WinUsb_Free(IntPtr InterfaceHandle);

    [DllImport("winusb.dll", SetLastError = true)]
    private static extern bool WinUsb_ControlTransfer(
        IntPtr InterfaceHandle, WINUSB_SETUP_PACKET SetupPacket,
        [In, Out] byte[] Buffer, uint BufferLength,
        out uint LengthTransferred, IntPtr Overlapped);

    public static bool IsInvalid(IntPtr handle)
    {
        return handle == IntPtr.Zero || handle.ToInt64() == -1;
    }

    public static string[] EnumerateDfuPaths()
    {
        var paths = new List<string>();
        Guid guid = DfuInterfaceGuid;
        IntPtr info = SetupDiGetClassDevs(ref guid, null, IntPtr.Zero,
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
        if (IsInvalid(info))
            return paths.ToArray();

        try
        {
            uint index = 0;
            while (true)
            {
                var data = new SP_DEVICE_INTERFACE_DATA();
                data.cbSize = Marshal.SizeOf(typeof(SP_DEVICE_INTERFACE_DATA));
                if (!SetupDiEnumDeviceInterfaces(info, IntPtr.Zero, ref guid,
                    index, ref data))
                    break;

                int required;
                SetupDiGetDeviceInterfaceDetail(info, ref data, IntPtr.Zero, 0,
                    out required, IntPtr.Zero);
                if (required <= 0)
                    break;

                IntPtr detail = Marshal.AllocHGlobal(required);
                try
                {
                    // SetupAPI expects 8 on x64 and 6 on x86, while its
                    // variable-length path is packed immediately after the
                    // four-byte cbSize field on both architectures.
                    Marshal.WriteInt32(detail, IntPtr.Size == 8 ? 8 : 6);
                    if (SetupDiGetDeviceInterfaceDetail(info, ref data, detail,
                        required, out required, IntPtr.Zero))
                    {
                        string path = Marshal.PtrToStringUni(
                            IntPtr.Add(detail, 4));
                        if (!String.IsNullOrEmpty(path))
                            paths.Add(path);
                    }
                }
                finally
                {
                    Marshal.FreeHGlobal(detail);
                }
                index++;
            }
        }
        finally
        {
            SetupDiDestroyDeviceInfoList(info);
        }
        return paths.ToArray();
    }

    public static IntPtr Open(string path, out IntPtr interfaceHandle,
        out int error)
    {
        interfaceHandle = IntPtr.Zero;
        // Keep the SetupAPI path unchanged.  Replacing \\?\ with \\.\
        // makes CreateFile fail with ERROR_PATH_NOT_FOUND for this device.
        IntPtr device = CreateFile(path, GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE, IntPtr.Zero, OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED, IntPtr.Zero);
        if (IsInvalid(device))
        {
            error = unchecked((int)0x10000000) | Marshal.GetLastWin32Error();
            return device;
        }
        if (!WinUsb_Initialize(device, out interfaceHandle))
        {
            error = unchecked((int)0x20000000) | Marshal.GetLastWin32Error();
            CloseHandle(device);
            return IntPtr.Zero;
        }
        error = 0;
        return device;
    }

    public static void Close(IntPtr device, IntPtr interfaceHandle)
    {
        if (!IsInvalid(interfaceHandle))
            WinUsb_Free(interfaceHandle);
        if (!IsInvalid(device))
            CloseHandle(device);
    }

    public static bool Control(IntPtr interfaceHandle, byte requestType,
        byte request, ushort value, ushort index, byte[] data, bool read,
        out byte[] result, out int error)
    {
        if (data == null)
            data = new byte[0];

        var setup = new WINUSB_SETUP_PACKET {
            RequestType = requestType,
            Request = request,
            Value = value,
            Index = index,
            Length = (ushort)data.Length
        };
        uint transferred;
        bool ok = WinUsb_ControlTransfer(interfaceHandle, setup, data,
            (uint)data.Length, out transferred, IntPtr.Zero);
        error = ok ? 0 : Marshal.GetLastWin32Error();
        if (read && transferred < data.Length)
        {
            result = new byte[transferred];
            Array.Copy(data, result, transferred);
        }
        else
        {
            result = data;
        }
        return ok;
    }
}
"@
}

$expectedSize = 34332
if (-not (Test-Path -LiteralPath $FirmwarePath -PathType Leaf)) {
    throw "Firmware file not found: $FirmwarePath"
}
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Image manifest not found: $ManifestPath"
}
$resolvedFirmware = (Resolve-Path -LiteralPath $FirmwarePath).Path
$raw = [IO.File]::ReadAllBytes($resolvedFirmware)
$md5 = (Get-FileHash -LiteralPath $resolvedFirmware -Algorithm MD5).Hash.ToUpperInvariant()
$sha256 = (Get-FileHash -LiteralPath $resolvedFirmware -Algorithm SHA256).Hash.ToUpperInvariant()
$manifest = Get-Content -Raw -LiteralPath (Resolve-Path -LiteralPath $ManifestPath) | ConvertFrom-Json
$imageRecord = @($manifest.images | Where-Object { $_.sha256 -eq $sha256 }) | Select-Object -First 1
if ($raw.Length -ne $expectedSize) {
    throw "Refusing image: expected $expectedSize bytes, got $($raw.Length) bytes."
}
if (-not $imageRecord) {
    throw "Refusing unlisted image SHA-256 $sha256. Add a reviewed image record to the manifest before flashing."
}
if ($imageRecord -and $imageRecord.md5.ToUpperInvariant() -ne $md5) {
    throw "Manifest MD5 does not match the image SHA-256 record."
}

# The CDN image is byte-substituted.  The raw bytes sent over DFU are the
# inverse-map bytes; no extra XOR is applied when using direct WinUSB.
$mapPath = Join-Path $PSScriptRoot '..\firmware\substitution_map.json'
if (-not (Test-Path -LiteralPath $mapPath -PathType Leaf)) {
    throw "Firmware substitution table not found: $mapPath"
}
$mapJson = Get-Content -Raw -LiteralPath (Resolve-Path -LiteralPath $mapPath) |
    ConvertFrom-Json
$mapValues = New-Object byte[] $mapJson.Count
for ($mapIndex = 0; $mapIndex -lt $mapJson.Count; $mapIndex++) {
    $mapValues[$mapIndex] = [Convert]::ToByte([int]$mapJson[$mapIndex])
}
if ($mapValues.Count -ne 256) {
    throw "Expected 256 substitution-table bytes, found $($mapValues.Count)."
}
if (@($mapValues | Sort-Object -Unique).Count -ne 256) {
    throw "The substitution table is not a 256-byte permutation."
}
$map = [byte[]]$mapValues
$inverse = New-Object byte[] 256
for ($i = 0; $i -lt 256; $i++) {
    $inverse[$map[$i]] = [byte]$i
}
$plain = New-Object byte[] $raw.Length
for ($i = 0; $i -lt $raw.Length; $i++) {
    $plain[$i] = $inverse[$raw[$i]]
}

$vector = [BitConverter]::ToUInt32($plain, 0)
$reset = [BitConverter]::ToUInt32($plain, 4)
if ($vector -lt 0x20000000 -or $vector -gt 0x20040000 -or
    $reset -lt 0x08004000 -or $reset -ge 0x08020000) {
    throw ('Refusing image: decoded ARM vector table is not an M10K app ' +
        '(SP=0x{0:X8}, Reset=0x{1:X8})' -f $vector, $reset)
}
Write-Host ('Image verified: {0} ({1} bytes, MD5 {2}, SHA256 {3})' -f
    $imageRecord.id, $raw.Length, $md5, $sha256)
Write-Host ('Decoded vector table: SP=0x{0:X8}, Reset=0x{1:X8}' -f $vector, $reset)

$paths = @([GaomonWinUsbFlasherNative]::EnumerateDfuPaths() |
    Where-Object { $_ -match '(?i)vid_28e9&pid_0189' })
if (-not $paths) {
    throw 'No WinUSB DFU interface was found for VID_28E9&PID_0189. Re-enter DFU mode and bind the local WinUSB INF.'
}

Write-Host 'WinUSB DFU interface candidate(s):'
$paths | ForEach-Object { Write-Host "  $_" }

# SetupAPI can expose a reference-string variant such as \GD32-1 in addition
# to the base interface.  Try each enumerated path exactly as returned, then
# try that suffix as a fallback.  The first path that WinUsb_Initialize accepts
# is retained for the session.
$candidates = New-Object System.Collections.Generic.List[string]
foreach ($path in $paths) {
    if (-not $candidates.Contains($path)) { [void]$candidates.Add($path) }
    if ($path -notmatch '(?i)\\GD32-1$') {
        $suffixPath = "$path\GD32-1"
        if (-not $candidates.Contains($suffixPath)) { [void]$candidates.Add($suffixPath) }
    }
}

[IntPtr]$deviceHandle = [IntPtr]::Zero
[IntPtr]$interfaceHandle = [IntPtr]::Zero
$openFailures = New-Object System.Collections.Generic.List[string]
foreach ($candidate in $candidates) {
    [int]$openError = 0
    [IntPtr]$candidateInterface = [IntPtr]::Zero
    $candidateDevice = [GaomonWinUsbFlasherNative]::Open($candidate,
        [ref]$candidateInterface, [ref]$openError)
    if (-not [GaomonWinUsbFlasherNative]::IsInvalid($candidateDevice) -and
        -not [GaomonWinUsbFlasherNative]::IsInvalid($candidateInterface)) {
        $deviceHandle = $candidateDevice
        $interfaceHandle = $candidateInterface
        Write-Host "Opened WinUSB interface: $candidate"
        break
    }
    $openFailures.Add("$candidate (error $openError)")
}
if ([GaomonWinUsbFlasherNative]::IsInvalid($deviceHandle) -or
    [GaomonWinUsbFlasherNative]::IsInvalid($interfaceHandle)) {
    throw ('Could not open any WinUSB DFU interface: ' + ($openFailures -join '; '))
}

function Invoke-DfuControl {
    param(
        [byte]$RequestType,
        [byte]$Request,
        [UInt16]$Value,
        [byte[]]$Data,
        [switch]$Read
    )
    [byte[]]$result = $null
    [int]$error = 0
    Write-Host ('DEBUG transfer: type={0:X2} request={1} value={2} length={3} read={4}' -f
        $RequestType,$Request,$Value,$Data.Length,[bool]$Read)
    if (-not [GaomonWinUsbFlasherNative]::Control($interfaceHandle,
        $RequestType, $Request, $Value, 0, $Data, [bool]$Read,
        [ref]$result, [ref]$error)) {
        throw ('USB control transfer 0x{0:X2}/{1} value {2} failed (Win32 error {3})' -f
            $RequestType, $Request, $Value, $error)
    }
    return $result
}

function Get-DfuStatus {
    [byte[]]$status = Invoke-DfuControl 0xA1 3 0 (New-Object byte[] 6) -Read
    if ($status.Length -lt 6) {
        throw "GETSTATUS returned only $($status.Length) bytes."
    }
    $poll = [int]$status[1] -bor ([int]$status[2] -shl 8) -bor
        ([int]$status[3] -shl 16)
    [pscustomobject]@{
        Status = [int]$status[0]
        PollTimeout = $poll
        State = [int]$status[4]
        Raw = $status
    }
}

function Send-DfuAbort {
    [void](Invoke-DfuControl 0x21 6 0 ([byte[]]@()))
}

function Send-DfuClearStatus {
    [void](Invoke-DfuControl 0x21 4 0 ([byte[]]@()))
}

function Wait-DfuState {
    param(
        [int[]]$States,
        [int]$TimeoutMilliseconds = 10000
    )
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $status = Get-DfuStatus
        if ($status.Status -ne 0) {
            throw ('DFU status error 0x{0:X2} in state {1}' -f
                $status.Status, $status.State)
        }
        if ($status.State -eq 10) {
            throw 'DFU entered the error state (10).'
        }
        if ($States -contains $status.State) {
            return $status
        }
        $delay = [Math]::Max(2, [Math]::Min(1000, $status.PollTimeout + 2))
        Start-Sleep -Milliseconds $delay
    }
    throw ('Timed out waiting for DFU state(s) {0}; last state was {1}' -f
        ($States -join ','), (Get-DfuStatus).State)
}

function Ensure-DfuReady {
    $status = Get-DfuStatus
    if ($status.State -eq 10) {
        # CLRSTATUS is only sent while the bootloader is in dfuERROR.  It is
        # useful after an interrupted read/probe and is harmless here because
        # the device has not started an erase or download.
        Send-DfuClearStatus
        $status = Wait-DfuState @(2)
    }
    if ($status.Status -ne 0) {
        throw ('DFU is reporting status 0x{0:X2}, state {1}' -f
            $status.Status, $status.State)
    }
    if ($status.State -eq 2 -or $status.State -eq 5) {
        return $status
    }
    # ABORT only resets the DFU transaction state; it does not erase or write
    # flash.  It lets a prior probe or interrupted read return to idle.
    Send-DfuAbort
    return Wait-DfuState @(2)
}

function Send-DfuDownload {
    param([UInt16]$Block, [byte[]]$Payload)
    if ($null -eq $Payload) { $Payload = [byte[]]@() }
    if ($Payload.Length -gt 0x400) {
        throw "DFU payload is limited to 0x400 bytes (got $($Payload.Length))."
    }
    [void](Invoke-DfuControl 0x21 1 $Block $Payload)
}

function Send-DfuUpload {
    param([UInt16]$Block, [int]$Length)
    if ($Length -lt 0 -or $Length -gt 0x800) {
        throw "DFU upload length must be between 0 and 0x800 bytes (got $Length)."
    }
    return Invoke-DfuControl 0xA1 2 $Block (New-Object byte[] $Length) -Read
}

function Send-DfuCommand {
    param([byte[]]$Command)
    [void](Ensure-DfuReady)
    Write-Host ('Sending DFU command: {0}' -f (($Command | ForEach-Object { $_.ToString('X2') }) -join ' '))
    Send-DfuDownload 0 $Command
    $status = Wait-DfuState @(4, 5)
    Write-Host ('After command status: {0}' -f (($status.Raw | ForEach-Object { $_.ToString('X2') }) -join ' '))
    if ($status.State -eq 4) {
        Start-Sleep -Milliseconds ([Math]::Max(50, $status.PollTimeout))
    }
    $after = Wait-DfuState @(5)
    Write-Host ('After command wait status: {0}' -f (($after.Raw | ForEach-Object { $_.ToString('X2') }) -join ' '))
}

function Send-SetAddress {
    param([UInt32]$Address)
    $command = [byte[]](0x21,
        [byte]($Address -band 0xff),
        [byte](($Address -shr 8) -band 0xff),
        [byte](($Address -shr 16) -band 0xff),
        [byte](($Address -shr 24) -band 0xff))
    [void](Send-DfuCommand $command)
}

function Send-Erase {
    param([UInt32]$Address)
    $command = [byte[]](0x41,
        [byte]($Address -band 0xff),
        [byte](($Address -shr 8) -band 0xff),
        [byte](($Address -shr 16) -band 0xff),
        [byte](($Address -shr 24) -band 0xff))
    [void](Send-DfuCommand $command)
}

function Invoke-ReadOnlyProbe {
    [void](Ensure-DfuReady)
    $status = Get-DfuStatus
    Write-Host ('GETSTATUS: {0} (state {1}, poll {2} ms)' -f
        (($status.Raw | ForEach-Object { $_.ToString('X2') }) -join ' '),
        $status.State, $status.PollTimeout)

    Send-SetAddress 0x1FFFF800
    # GD32 leaves a completed SET_ADDRESS_POINTER in dfuDNLOAD-IDLE (state 5).
    # The UPLOAD request is accepted only after an ABORT returns it to
    # dfuIDLE.  This is also the sequence used by the stock updater.
    Send-DfuAbort
    [void](Wait-DfuState @(2))
    $beforeUpload = Get-DfuStatus
    Write-Host ('Before option UPLOAD: {0}' -f
        (($beforeUpload.Raw | ForEach-Object { $_.ToString('X2') }) -join ' '))
    $option = Send-DfuUpload 2 16
    Write-Host ('UPLOAD option bytes ({0} bytes): {1}' -f $option.Length,
        (($option | ForEach-Object { $_.ToString('X2') }) -join ' '))
    if ($option.Length -lt 2 -or $option[0] -ne 0xA5 -or $option[1] -ne 0x5A) {
        throw 'DFU option-byte read did not return the expected GD32 signature (A5 5A).'
    }
    Send-DfuAbort
    [void](Wait-DfuState @(2))
    Write-Host 'Read-only WinUSB DFU probe succeeded; no flash erase or firmware write was performed.'
}

function Read-CurrentFlash {
    param([UInt32]$Address, [int]$Length, [string]$Path)
    Write-Host ('Reading {0} bytes from 0x{1:X8} to {2}' -f $Length, $Address, $Path)
    [byte[]]$backup = New-Object byte[] $Length
    $ready = Ensure-DfuReady
    if ($ready.State -ne 2) {
        Send-DfuAbort
        [void](Wait-DfuState @(2))
    }
    # The DFU functional descriptor reports a 0x800-byte transfer size.  The
    # bootloader advances the upload address by that size for each block;
    # set it once, abort back to dfuIDLE, then use sequential block numbers.
    Send-SetAddress $Address
    Send-DfuAbort
    [void](Wait-DfuState @(2))
    for ($offset = 0; $offset -lt $Length; $offset += 0x800) {
        $count = [Math]::Min(0x800, $Length - $offset)
        $block = [UInt16](2 + [int]($offset / 0x800))
        [byte[]]$chunk = Send-DfuUpload $block $count
        if ($chunk.Length -ne $count) {
            throw "UPLOAD block $block returned $($chunk.Length) bytes; expected $count."
        }
        [Array]::Copy($chunk, 0, $backup, $offset, $count)
        Write-Host ('Read 0x{0:X8} ({1} bytes, {2}%)' -f
            ($Address + [UInt32]$offset), $count,
            [int](100 * ($offset + $count) / $Length))
    }
    Send-DfuAbort
    [void](Wait-DfuState @(2))
    $fullPath = [IO.Path]::GetFullPath($Path)
    [IO.File]::WriteAllBytes($fullPath, $backup)
    return $fullPath
}

try {
    Invoke-ReadOnlyProbe

    if ($BackupPath) {
        $backupDirectory = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($BackupPath))
        if ($backupDirectory) {
            New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
        }
        $savedBackup = Read-CurrentFlash 0x08004000 $BackupLength $BackupPath
        $backupHash = (Get-FileHash -LiteralPath $savedBackup -Algorithm SHA256).Hash.ToUpperInvariant()
        Write-Host "Current application backup saved to $savedBackup (SHA256 $backupHash)."
        if ($Write -and $BackupLength -ne $plain.Length) {
            throw "Refusing to write with BackupLength $BackupLength; expected the full $($plain.Length)-byte application backup."
        }
    }

    if (-not $Write) {
        Write-Host 'Probe complete. No flash erase or firmware write was performed.'
        return
    }

    $start = [UInt32]0x08004000
    $end = $start + [UInt32]$plain.Length
    $imageLabel = if ($imageRecord) { $imageRecord.id } else { $resolvedFirmware }
    Write-Host ('Beginning M10K 2018 update ({0}): 0x{1:X8}-0x{2:X8} ({3} bytes).' -f
        $imageLabel, $start, $end, $plain.Length)

    # The GD32 DFU bootloader erases 1 KiB sectors using block 0 command
    # 0x41.  The image is sent as 0x400-byte block 2 transfers after a
    # block-0 set-address command (0x21) for each chunk.
    for ([UInt32]$address = $start; $address -lt $end; $address += 0x400) {
        Send-Erase $address
        Write-Host ('Erased 0x{0:X8}' -f $address)
    }

    for ($offset = 0; $offset -lt $plain.Length; $offset += 0x400) {
        $length = [Math]::Min(0x400, $plain.Length - $offset)
        $chunk = New-Object byte[] $length
        [Array]::Copy($plain, $offset, $chunk, 0, $length)
        $address = [UInt32]($start + [UInt32]$offset)
        Send-SetAddress $address
        Send-DfuDownload 2 $chunk
        $status = Wait-DfuState @(4, 5)
        if ($status.State -eq 4) {
            Start-Sleep -Milliseconds ([Math]::Max(50, $status.PollTimeout))
            [void](Wait-DfuState @(5))
        }
        Write-Host ('Wrote 0x{0:X8} ({1} bytes, {2}%)' -f
            $address, $length,
            [int](100 * ($offset + $length) / $plain.Length))
    }

    # Read the programmed range back while the tablet is still in DFU mode and
    # compare it to the decoded payload.  This catches an address/block error
    # before the user reconnects the tablet normally.
    $verifyPath = Join-Path $PSScriptRoot '..\..\firmware\backups\M10K_T17b_after_write_DFU_readback_0x800.bin'
    $verifyDirectory = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($verifyPath))
    if ($verifyDirectory) {
        New-Item -ItemType Directory -Force -Path $verifyDirectory | Out-Null
    }
    $null = Read-CurrentFlash $start $plain.Length $verifyPath
    $verifyHash = (Get-FileHash -LiteralPath $verifyPath -Algorithm SHA256).Hash.ToUpperInvariant()
    $plainHash = ([Security.Cryptography.SHA256]::Create().ComputeHash($plain) |
        ForEach-Object { $_.ToString('X2') }) -join ''
    if ($verifyHash -ne $plainHash) {
        throw "Post-write readback hash mismatch: expected $plainHash, got $verifyHash"
    }
    Write-Host "Firmware payload accepted and read back successfully (SHA256 $verifyHash)."
    Write-Host 'Unplug and reconnect the tablet normally to boot the updated firmware.'
}
finally {
    [GaomonWinUsbFlasherNative]::Close($deviceHandle, $interfaceHandle)
}

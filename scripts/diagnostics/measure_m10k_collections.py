"""Capture both M10K Raw Input collections without changing any drivers.

The M10K exposes a vendor collection used by OpenTabletDriver and a standard
digitizer-pen collection used by Windows. This tool counts both separately.
Run while the tablet is in normal mode, with the pen away from the surface.
"""

from __future__ import annotations

import argparse
import ctypes
import time
from collections import defaultdict
from ctypes import wintypes

import win32api
import win32con
import win32event
import win32gui


WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIDEV_INPUTSINK = 0x00000100
RIDEV_REMOVE = 0x00000001
RIM_TYPEHID = 2
GAOMON_PIDS = ("VID_256C&PID_006E", "VID_256C&PID_006F")


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterRawInputDevices.argtypes = (ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT)
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.GetRawInputData.argtypes = (wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                   ctypes.POINTER(wintypes.UINT), wintypes.UINT)
user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputDeviceInfoW.argtypes = (wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                          ctypes.POINTER(wintypes.UINT))
user32.GetRawInputDeviceInfoW.restype = wintypes.UINT


def device_name(handle):
    size = wintypes.UINT(0)
    user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(size))
    if not size.value:
        return ""
    buf = ctypes.create_unicode_buffer(size.value + 1)
    result = user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, buf, ctypes.byref(size))
    return buf.value if result != 0xFFFFFFFF else ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=20.0)
    args = parser.parse_args()
    counts = defaultdict(int)
    messages = defaultdict(int)
    examples = {}

    def wndproc(hwnd, msg, wparam, lparam):
        if msg != WM_INPUT:
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
        size = wintypes.UINT(0)
        header_size = ctypes.sizeof(RAWINPUTHEADER)
        user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), header_size)
        if not size.value:
            return 0
        buf = ctypes.create_string_buffer(size.value)
        if user32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size), header_size) == 0xFFFFFFFF:
            return 0
        header = RAWINPUTHEADER.from_buffer_copy(buf)
        if header.dwType != RIM_TYPEHID:
            return 0
        name = device_name(header.hDevice).upper()
        if not any(pid in name for pid in GAOMON_PIDS):
            return 0
        off = header_size
        report_size = int.from_bytes(buf[off:off + 4], "little")
        report_count = int.from_bytes(buf[off + 4:off + 8], "little")
        if not report_size or not report_count:
            return 0
        collection = "digitizer_MI01" if "MI_01" in name else "vendor_MI00"
        counts[collection] += report_count
        messages[collection] += 1
        examples.setdefault(collection, bytes(buf[off + 8:off + 8 + min(report_size, 16)]).hex(" "))
        return 0

    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "GaomonAllCollectionCounter"
    wc.lpfnWndProc = wndproc
    wc.hInstance = win32api.GetModuleHandle(None)
    atom = win32gui.RegisterClass(wc)
    hwnd = win32gui.CreateWindow(atom, wc.lpszClassName, win32con.WS_OVERLAPPED, 0, 0, 1, 1,
                                 0, 0, wc.hInstance, None)
    devices = (RAWINPUTDEVICE * 2)(
        RAWINPUTDEVICE(0x0D, 0x02, RIDEV_INPUTSINK, hwnd),
        RAWINPUTDEVICE(0xFF00, 0x01, RIDEV_INPUTSINK, hwnd),
    )
    if not user32.RegisterRawInputDevices(devices, 2, ctypes.sizeof(RAWINPUTDEVICE)):
        raise ctypes.WinError(ctypes.get_last_error())
    print("Capturing M10K digitizer and vendor collections; keep the pen away for the idle test.")
    start = time.perf_counter()
    try:
        while time.perf_counter() - start < args.seconds:
            win32gui.PumpWaitingMessages()
            remain = max(1, min(100, int(1000 * (args.seconds - (time.perf_counter() - start)))))
            win32event.MsgWaitForMultipleObjects([], False, remain, win32con.QS_ALLINPUT)
        win32gui.PumpWaitingMessages()
    finally:
        removes = (RAWINPUTDEVICE * 2)(
            RAWINPUTDEVICE(0x0D, 0x02, RIDEV_REMOVE, 0),
            RAWINPUTDEVICE(0xFF00, 0x01, RIDEV_REMOVE, 0),
        )
        user32.RegisterRawInputDevices(removes, 2, ctypes.sizeof(RAWINPUTDEVICE))
        win32gui.DestroyWindow(hwnd)
        win32gui.UnregisterClass(wc.lpszClassName, wc.hInstance)
    elapsed = time.perf_counter() - start
    print(f"Elapsed: {elapsed:.3f} s")
    for collection in ("digitizer_MI01", "vendor_MI00"):
        print(f"{collection}: {counts[collection]} reports, {messages[collection]} messages, "
              f"{counts[collection] / elapsed:.1f} Hz")
        if collection in examples:
            print(f"  first report bytes: {examples[collection]}")
    if not any(counts.values()):
        print("No M10K Raw Input reports arrived while idle.")


if __name__ == "__main__":
    main()

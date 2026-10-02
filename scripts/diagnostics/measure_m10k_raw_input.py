"""Count M10K 2018 pen reports exposed through Windows Raw Input.

Run: python scripts/diagnostics/measure_m10k_raw_input.py --seconds 15
Move the pen continuously on the tablet during the sample. This is read-only.
"""

import argparse
import ctypes
import statistics
import time
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
GAOMON_PEN_PATHS = (
    "VID_256C&PID_006E&MI_01",
    "VID_256C&PID_006F&MI_01",
)


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [
        ("hDevice", wintypes.HANDLE),
        ("dwType", wintypes.DWORD),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterRawInputDevices.argtypes = (
    ctypes.POINTER(RAWINPUTDEVICE),
    wintypes.UINT,
    wintypes.UINT,
)
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.GetRawInputData.argtypes = (
    wintypes.HRAWINPUT if hasattr(wintypes, "HRAWINPUT") else wintypes.HANDLE,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.UINT),
    wintypes.UINT,
)
user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputDeviceInfoW.argtypes = (
    wintypes.HANDLE,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.UINT),
)
user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
user32.GetRawInputDeviceList.argtypes = (
    ctypes.POINTER(RAWINPUTDEVICELIST),
    ctypes.POINTER(wintypes.UINT),
    wintypes.UINT,
)
user32.GetRawInputDeviceList.restype = wintypes.UINT


def device_name(handle):
    count = wintypes.UINT(0)
    user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(count))
    if not count.value:
        return ""
    buffer = ctypes.create_unicode_buffer(count.value + 1)
    result = user32.GetRawInputDeviceInfoW(
        handle, RIDI_DEVICENAME, buffer, ctypes.byref(count)
    )
    return buffer.value if result != 0xFFFFFFFF else ""


def attached_pen_collections():
    count = wintypes.UINT(0)
    result = user32.GetRawInputDeviceList(
        None, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST)
    )
    if result != 0:
        raise ctypes.WinError(ctypes.get_last_error())
    devices = (RAWINPUTDEVICELIST * count.value)()
    result = user32.GetRawInputDeviceList(
        devices, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST)
    )
    if result == 0xFFFFFFFF:
        raise ctypes.WinError(ctypes.get_last_error())
    return [
        device_name(item.hDevice)
        for item in devices[: count.value]
        if item.dwType == RIM_TYPEHID
        and any(
            path in device_name(item.hDevice).upper() for path in GAOMON_PEN_PATHS
        )
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=15.0)
    args = parser.parse_args()
    arrivals = []
    reports = 0
    messages = 0
    devices_seen = set()
    attached = attached_pen_collections()
    print(f"Attached M10K pen Raw Input collections: {len(attached)}")
    for name in attached:
        print(f"  {name}")
    if not attached:
        print("The tablet is not exposing the normal HID pen collection; check DFU/USB state.")

    def wndproc(hwnd, msg, wparam, lparam):
        nonlocal reports, messages
        if msg == WM_INPUT:
            size = wintypes.UINT(0)
            header_size = ctypes.sizeof(RAWINPUTHEADER)
            user32.GetRawInputData(
                lparam, RID_INPUT, None, ctypes.byref(size), header_size
            )
            if size.value:
                buffer = ctypes.create_string_buffer(size.value)
                result = user32.GetRawInputData(
                    lparam, RID_INPUT, buffer, ctypes.byref(size), header_size
                )
                if result != 0xFFFFFFFF:
                    header = RAWINPUTHEADER.from_buffer_copy(buffer)
                    if header.dwType == RIM_TYPEHID:
                        name = device_name(header.hDevice).upper()
                        if any(path in name for path in GAOMON_PEN_PATHS):
                            devices_seen.add(name)
                            offset = header_size
                            hid_size = int.from_bytes(buffer[offset : offset + 4], "little")
                            hid_count = int.from_bytes(
                                buffer[offset + 4 : offset + 8], "little"
                            )
                            if hid_size and hid_count:
                                messages += 1
                                reports += hid_count
                                arrivals.extend([time.perf_counter()] * hid_count)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "GaomonRawInputCounter"
    wc.lpfnWndProc = wndproc
    wc.hInstance = win32api.GetModuleHandle(None)
    atom = win32gui.RegisterClass(wc)
    hwnd = win32gui.CreateWindow(
        atom,
        "Gaomon Raw Input Counter",
        win32con.WS_OVERLAPPED,
        0,
        0,
        1,
        1,
        0,
        0,
        wc.hInstance,
        None,
    )
    rid = RAWINPUTDEVICE(0x0D, 0x02, RIDEV_INPUTSINK, hwnd)
    if not user32.RegisterRawInputDevices(
        ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    print("Keep the pen in range and move it continuously during this sample.")
    begin = time.perf_counter()
    try:
        while time.perf_counter() - begin < args.seconds:
            win32gui.PumpWaitingMessages()
            remaining_ms = max(1, min(100, int(1000 * (args.seconds - (time.perf_counter() - begin)))))
            win32event.MsgWaitForMultipleObjects([], False, remaining_ms, win32con.QS_ALLINPUT)
        win32gui.PumpWaitingMessages()
    finally:
        remove = RAWINPUTDEVICE(0x0D, 0x02, RIDEV_REMOVE, 0)
        user32.RegisterRawInputDevices(
            ctypes.byref(remove), 1, ctypes.sizeof(RAWINPUTDEVICE)
        )
        win32gui.DestroyWindow(hwnd)
        win32gui.UnregisterClass(wc.lpszClassName, wc.hInstance)

    duration = time.perf_counter() - begin
    print(f"Pen devices that sent reports: {len(devices_seen)}")
    print(f"Raw Input messages: {messages}")
    print(f"Reports: {reports} over {duration:.3f} s ({reports / duration:.1f} Hz)")
    if reports > messages:
        print("Windows batched some reports; message arrival gaps do not equal USB report gaps.")
    if len(arrivals) >= 2:
        gaps = [
            1000 * (later - earlier)
            for earlier, later in zip(arrivals, arrivals[1:])
            if later > earlier
        ]
        if gaps:
            print(
                "Positive interarrival gaps: "
                f"median {statistics.median(gaps):.2f} ms, "
                f"min {min(gaps):.2f} ms, max {max(gaps):.2f} ms"
            )
    if not arrivals:
        print("No pen reports captured. Keep the pen in range and moving throughout the run.")


if __name__ == "__main__":
    main()

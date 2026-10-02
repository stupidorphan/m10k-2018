"""Read-only inventory of Windows Raw Input device collections for the M10K.

Run: python scripts/diagnostics/inspect_m10k_raw_input.py
"""

import ctypes
from ctypes import wintypes


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]


class RID_DEVICE_INFO_HID(ctypes.Structure):
    _fields_ = [
        ("dwVendorId", wintypes.DWORD),
        ("dwProductId", wintypes.DWORD),
        ("dwVersionNumber", wintypes.DWORD),
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
    ]


class RID_DEVICE_INFO_UNION(ctypes.Union):
    _fields_ = [("hid", RID_DEVICE_INFO_HID), ("padding", ctypes.c_byte * 24)]


class RID_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwType", wintypes.DWORD), ("data", RID_DEVICE_INFO_UNION)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetRawInputDeviceList.argtypes = (
    ctypes.POINTER(RAWINPUTDEVICELIST),
    ctypes.POINTER(wintypes.UINT),
    wintypes.UINT,
)
user32.GetRawInputDeviceList.restype = wintypes.UINT
user32.GetRawInputDeviceInfoW.argtypes = (
    wintypes.HANDLE,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.UINT),
)
user32.GetRawInputDeviceInfoW.restype = wintypes.UINT


def get_name(handle):
    count = wintypes.UINT(0)
    user32.GetRawInputDeviceInfoW(handle, 0x20000007, None, ctypes.byref(count))
    if not count.value:
        return ""
    buffer = ctypes.create_unicode_buffer(count.value + 1)
    result = user32.GetRawInputDeviceInfoW(handle, 0x20000007, buffer, ctypes.byref(count))
    if result == 0xFFFFFFFF:
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def get_info(handle):
    info = RID_DEVICE_INFO()
    info.cbSize = ctypes.sizeof(info)
    size = wintypes.UINT(ctypes.sizeof(info))
    result = user32.GetRawInputDeviceInfoW(handle, 0x2000000B, ctypes.byref(info), ctypes.byref(size))
    if result == 0xFFFFFFFF:
        raise ctypes.WinError(ctypes.get_last_error())
    return info


def main():
    count = wintypes.UINT(0)
    result = user32.GetRawInputDeviceList(None, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST))
    if result != 0:
        raise ctypes.WinError(ctypes.get_last_error())
    print(f"Windows Raw Input collections: {count.value}")
    devices = (RAWINPUTDEVICELIST * count.value)()
    result = user32.GetRawInputDeviceList(devices, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST))
    if result == 0xFFFFFFFF:
        raise ctypes.WinError(ctypes.get_last_error())
    found = 0
    for device in devices[:count.value]:
        name = get_name(device.hDevice)
        info = get_info(device.hDevice)
        is_gaomon = any(
            f"VID_256C&PID_{pid:04X}" in name.upper() for pid in (0x006E, 0x006F)
        ) or (
            info.dwType == 2
            and info.data.hid.dwVendorId == 0x256C
            and info.data.hid.dwProductId in (0x006E, 0x006F)
        )
        if not is_gaomon:
            continue
        found += 1
        print(f"type={device.dwType}, path={name}")
        if info.dwType == 2:
            print(
                f"  VID={info.data.hid.dwVendorId:04X} PID={info.data.hid.dwProductId:04X} "
                f"usage_page=0x{info.data.hid.usUsagePage:04X} usage=0x{info.data.hid.usUsage:04X}"
            )
    print(f"M10K collections: {found}")


if __name__ == "__main__":
    main()

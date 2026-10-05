"""Resident memory of this process, without psutil (one fewer native wheel to vet)."""

from __future__ import annotations

import sys


def rss_mb() -> float:
    if sys.platform.startswith("linux"):
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
        return float("nan")
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        # Without these, ctypes truncates the pseudo-handle to a C int and the call
        # silently fails, reporting 0 MB.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return float("nan")
        return counters.WorkingSetSize / (1024 * 1024)
    return float("nan")

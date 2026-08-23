"""How hard the disk is working, so a long job visibly stays a job.

A sort moves tens of gigabytes and a verify pass reads every byte back. Both
spend minutes doing nothing a person can see, and "is this still running or has
it wedged?" is a fair question to ask of a window that has not changed.

Windows keeps per-process I/O totals, and the difference between two readings
is the throughput. That is more honest than a whole-disk figure: it reports the
work *this* program is doing, so an idle number really does mean idle.

ctypes only - no psutil, in keeping with the rest of esdeck.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


def _counters() -> tuple | None:
    """(bytes read, bytes written) by this process, or None if unavailable."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return None                      # not Windows
    try:
        kernel32.GetProcessIoCounters.argtypes = [wintypes.HANDLE,
                                                  ctypes.POINTER(_IoCounters)]
        kernel32.GetProcessIoCounters.restype = wintypes.BOOL
        buf = _IoCounters()
        if not kernel32.GetProcessIoCounters(kernel32.GetCurrentProcess(),
                                             ctypes.byref(buf)):
            return None
        return int(buf.ReadTransferCount), int(buf.WriteTransferCount)
    except (AttributeError, OSError, ValueError):
        return None


class DiskMeter:
    """Read and write throughput, sampled between calls to `sample()`.

    Rates are smoothed a little. Copying alternates between reading a file and
    writing it, so an unsmoothed reading swings between "all read" and "all
    write" and is harder to read than it is informative.
    """

    SMOOTHING = 0.6                      # weight given to the newest sample

    def __init__(self) -> None:
        self.available = _counters() is not None
        self.read_rate = 0.0
        self.write_rate = 0.0
        self._last = _counters()
        self._at = time.monotonic()

    def sample(self) -> None:
        if not self.available:
            return
        now = time.monotonic()
        gap = now - self._at
        if gap < 0.2:                    # too short to divide by meaningfully
            return
        current = _counters()
        if current is None or self._last is None:
            self._last, self._at = current, now
            return
        read = max(0, current[0] - self._last[0]) / gap
        write = max(0, current[1] - self._last[1]) / gap
        k = self.SMOOTHING
        self.read_rate = k * read + (1 - k) * self.read_rate
        self.write_rate = k * write + (1 - k) * self.write_rate
        self._last, self._at = current, now

    @property
    def busy(self) -> bool:
        """Whether anything is actually moving, at a threshold above noise."""
        return (self.read_rate + self.write_rate) > 64 * 1024

    def describe(self, human) -> str:
        """A compact 'disk R .. W ..', given a byte formatter."""
        if not self.available:
            return ""
        return f"disk R {human(self.read_rate)}/s W {human(self.write_rate)}/s"

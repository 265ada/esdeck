"""Run child processes without conjuring console windows.

The desktop application has no console of its own. On Windows that means every
console program it starts - 7-Zip, winget, tasklist, pip - is given a brand new
console window, which flashes up over whatever you were doing and can be closed
mid-extraction by a stray click. Passing CREATE_NO_WINDOW stops that; the child
still writes to the pipes we hand it, so nothing is lost from the log.

Everything in esdeck that starts a program goes through here, so there is one
place for this rather than nine places to forget it.
"""

from __future__ import annotations

import subprocess

#: Documented in the Win32 process creation flags. Absent off Windows.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(cmd, **kwargs):
    """subprocess.run, minus the window."""
    if CREATE_NO_WINDOW and "creationflags" not in kwargs:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def popen(cmd, **kwargs):
    """subprocess.Popen, minus the window."""
    if CREATE_NO_WINDOW and "creationflags" not in kwargs:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)

"""Progress, throughput and a time estimate for long sorts.

Filing a few thousand games moves tens of gigabytes and takes minutes. Without
feedback that is indistinguishable from a hung program, so this reports what is
happening, how far along it is and how much longer it is likely to take.

The estimate is based on bytes copied rather than files finished, because game
files vary from 32 KB to 4 GB and counting files would swing wildly.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

BAR_WIDTH = 28


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:          # negative or NaN
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


@dataclass
class Progress:
    """Tracks work done and prints a single updating status line."""

    total_items: int = 0
    total_bytes: int = 0
    log = None                       # falls back to writing to stdout
    min_interval: float = 0.25       # seconds between redraws
    enabled: bool = True

    items_done: int = 0
    bytes_done: int = 0
    started: float = field(default_factory=time.monotonic)
    _last_draw: float = 0.0
    _last_len: int = 0
    _label: str = ""

    @property
    def fraction(self) -> float:
        """How far along, by bytes when known, else by item count."""
        if self.total_bytes:
            return min(1.0, self.bytes_done / self.total_bytes)
        if self.total_items:
            return min(1.0, self.items_done / self.total_items)
        return 0.0

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def rate(self) -> float:
        """Bytes per second so far, 0 until something has actually moved."""
        el = self.elapsed
        return self.bytes_done / el if el > 0.5 and self.bytes_done else 0.0

    @property
    def eta(self) -> float:
        """Seconds remaining, or -1 when there is not enough data to say."""
        frac = self.fraction
        if frac <= 0.01 or self.elapsed < 1:
            return -1
        return self.elapsed * (1 - frac) / frac

    def advance(self, items: int = 0, nbytes: int = 0, label: str = "") -> None:
        self.items_done += items
        self.bytes_done += nbytes
        if label:
            self._label = label
        self.draw()

    def bar(self) -> str:
        filled = int(self.fraction * BAR_WIDTH)
        return "#" * filled + "-" * (BAR_WIDTH - filled)

    def line(self) -> str:
        parts = [f"[{self.bar()}] {self.fraction * 100:5.1f}%"]
        if self.total_items:
            parts.append(f"{self.items_done}/{self.total_items}")
        if self.total_bytes:
            parts.append(f"{human_bytes(self.bytes_done)}/{human_bytes(self.total_bytes)}")
        if self.rate:
            parts.append(f"{human_bytes(self.rate)}/s")
        parts.append(f"elapsed {human_time(self.elapsed)}")
        eta = self.eta
        parts.append(f"left {human_time(eta)}" if eta >= 0 else "left --")
        line = "  ".join(parts)
        if self._label:
            room = max(0, 110 - len(line))
            if room > 12:
                label = self._label
                if len(label) > room - 3:
                    label = label[:room - 4] + "..."
                line += "  " + label
        return line

    def draw(self, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and now - self._last_draw < self.min_interval:
            return
        self._last_draw = now
        text = self.line()
        pad = " " * max(0, self._last_len - len(text))
        self._last_len = len(text)
        try:
            sys.stdout.write("\r" + text + pad)
            sys.stdout.flush()
        except (OSError, ValueError):
            self.enabled = False

    def finish(self, message: str = "") -> None:
        """Close the status line so ordinary output resumes on a fresh line."""
        if not self.enabled:
            if message:
                print(message)
            return
        self._label = ""
        self.draw(force=True)
        try:
            sys.stdout.write("\n")
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        if message:
            print(message)


def plan_totals(plans) -> tuple[int, int]:
    """(files, bytes) a set of plans will actually move, for the estimate."""
    items = nbytes = 0
    for pl in plans:
        for a in pl.get("actions", []):
            if a.get("needs_review"):
                continue
            if a["type"] in ("copy", "copy_tree", "extract", "patch"):
                items += 1
                nbytes += int(a.get("size") or 0)
    return items, nbytes

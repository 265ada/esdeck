"""Progress, throughput and a time estimate for long sorts.

Filing a few thousand games moves tens of gigabytes and takes minutes. Without
feedback that is indistinguishable from a hung program, so this reports what is
happening, how far along it is and how much longer it is likely to take.

The estimate is based on bytes copied rather than files finished, because game
files vary from 32 KB to 4 GB and counting files would swing wildly.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field

from .activity import DiskMeter

BAR_WIDTH = 28

#: How long a job has to run before the disk readout is worth the space. Short
#: jobs finish before anyone wonders whether they are stuck.
DISK_AFTER = 30.0

#: Turns whenever the display is redrawn, so a job with nothing measurable to
#: report still visibly ticks over rather than sitting there looking hung.
SPINNER = "|/-\\"


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
    _spin: int = 0

    #: Throughput over the last few seconds rather than over the whole run.
    #: A job that starts on a hundred tiny ROMs and moves on to a 4 GB disc
    #: image has a lifetime average that describes neither, and an estimate
    #: built on it stays wrong in the same direction for minutes.
    _recent: float = 0.0
    _mark_at: float = 0.0
    _mark_bytes: int = 0

    _disk: object = None
    _lock: object = None
    _beat: object = None

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

    #: Weight given to the newest throughput sample. High enough to follow a
    #: real change in pace within seconds, low enough that one slow file does
    #: not make the estimate jump about.
    SMOOTHING = 0.3

    def _sample_rate(self) -> None:
        """Fold the throughput since the last redraw into the running figure."""
        now = time.monotonic()
        if not self._mark_at:
            self._mark_at, self._mark_bytes = now, self.bytes_done
            return
        gap = now - self._mark_at
        if gap < 0.5:
            return
        moved = (self.bytes_done - self._mark_bytes) / gap
        self._recent = (self.SMOOTHING * moved
                        + (1 - self.SMOOTHING) * self._recent
                        if self._recent else moved)
        self._mark_at, self._mark_bytes = now, self.bytes_done

    @property
    def rate(self) -> float:
        """Bytes per second, recent rather than lifetime where possible."""
        if self._recent > 0:
            return self._recent
        el = self.elapsed
        return self.bytes_done / el if el > 0.5 and self.bytes_done else 0.0

    @property
    def eta(self) -> float:
        """Seconds remaining, or -1 when there is not enough data to say."""
        # Bytes left divided by what we are managing right now beats scaling
        # elapsed time by the fraction done, which quietly assumes the rest of
        # the job will go at the average pace of the part already finished.
        if self.total_bytes and self.rate > 0:
            left = max(0, self.total_bytes - self.bytes_done)
            return left / self.rate
        frac = self.fraction
        if frac <= 0.01 or self.elapsed < 1:
            return -1
        return self.elapsed * (1 - frac) / frac

    @property
    def disk(self):
        """The disk meter, created on first use so short jobs never pay for it."""
        if self._disk is None:
            self._disk = DiskMeter()
        return self._disk

    def _disk_text(self) -> str:
        if self.elapsed < DISK_AFTER:
            return ""
        meter = self.disk
        meter.sample()
        return meter.describe(human_bytes)

    def advance(self, items: int = 0, nbytes: int = 0, label: str = "") -> None:
        self.items_done += items
        self.bytes_done += nbytes
        if label:
            self._label = label
        self.draw()

    # ----------------------------------------------------------- heartbeat
    #
    # Some steps go quiet for a long time: hashing one 4 GB disc image, or
    # waiting on 7-Zip to finish a 47-part archive. Nothing calls advance()
    # during those, so without a beat of its own the display freezes and the
    # only honest reading of a frozen display is "it has hung".

    def start(self, every: float = 0.0) -> "Progress":
        """Begin redrawing on a timer. Returns self, so it can be chained."""
        if self._beat is not None or not self.enabled:
            return self
        if not every:
            # A terminal redraws one line in place, so it can beat quickly. A
            # captured log gains a whole line each time, and a two-hour sort
            # does not need four thousand of them.
            every = 2.0 if self.interactive else 5.0
        self._lock = threading.Lock()
        stop = threading.Event()

        def beat():
            while not stop.wait(every):
                self.draw(force=True)

        thread = threading.Thread(target=beat, daemon=True)
        self._beat = (thread, stop)
        thread.start()
        return self

    def stop(self) -> None:
        if self._beat is None:
            return
        thread, stop = self._beat
        self._beat = None
        stop.set()
        thread.join(timeout=1.0)

    def __enter__(self) -> "Progress":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.finish()

    def bar(self) -> str:
        filled = int(self.fraction * BAR_WIDTH)
        return "#" * filled + "-" * (BAR_WIDTH - filled)

    @property
    def has_total(self) -> bool:
        """Whether the size of the job is known, and a percentage meaningful."""
        return bool(self.total_items or self.total_bytes)

    def line(self) -> str:
        if not self.has_total:
            # Nothing to measure against - a bar frozen at 0% would suggest no
            # progress at all, so report the running count instead.
            line = (f"  {SPINNER[self._spin % len(SPINNER)]} working"
                    f"  {self.items_done} done"
                    f"  elapsed {human_time(self.elapsed)}")
            disk = self._disk_text()
            if disk:
                line += "  " + disk
            if self._label:
                line += f"  {self._label[:70]}"
            return line
        parts = [f"{SPINNER[self._spin % len(SPINNER)]} [{self.bar()}] "
                 f"{self.fraction * 100:5.1f}%"]
        if self.total_items:
            parts.append(f"{self.items_done}/{self.total_items}")
        if self.total_bytes:
            parts.append(f"{human_bytes(self.bytes_done)}/{human_bytes(self.total_bytes)}")
        if self.rate:
            parts.append(f"{human_bytes(self.rate)}/s")
        parts.append(f"elapsed {human_time(self.elapsed)}")
        eta = self.eta
        parts.append(f"left {human_time(eta)}" if eta >= 0 else "left --")
        disk = self._disk_text()
        if disk:
            parts.append(disk)
        line = "  ".join(parts)
        if self._label:
            room = max(0, 130 - len(line))
            if room > 12:
                label = self._label
                if len(label) > room - 3:
                    label = label[:room - 4] + "..."
                line += "  " + label
        return line

    @property
    def interactive(self) -> bool:
        """Whether we are drawing to a terminal that understands \\r.

        When output is captured - piped to a file, or read by the desktop app -
        carriage returns produce one unreadable smear, so a plain line every
        few seconds is printed instead.
        """
        try:
            return bool(sys.stdout.isatty())
        except (AttributeError, ValueError):
            return False

    def draw(self, force: bool = False) -> None:
        if not self.enabled:
            return
        lock = self._lock
        if lock is not None:
            with lock:
                self._draw_locked(force)
        else:
            self._draw_locked(force)

    def _draw_locked(self, force: bool = False) -> None:
        now = time.monotonic()
        interval = self.min_interval if self.interactive else 3.0
        if not force and now - self._last_draw < interval:
            return
        self._last_draw = now
        self._sample_rate()
        self._spin += 1
        text = self.line()
        try:
            if self.interactive:
                pad = " " * max(0, self._last_len - len(text))
                self._last_len = len(text)
                sys.stdout.write("\r" + text + pad)
            else:
                sys.stdout.write(text + "\n")
            sys.stdout.flush()
        except (OSError, ValueError):
            self.enabled = False

    def finish(self, message: str = "") -> None:
        """Close the status line so ordinary output resumes on a fresh line."""
        self.stop()
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

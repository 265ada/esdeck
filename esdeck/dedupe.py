"""Pick one copy of a game when a messy collection holds several.

Dumps accumulate variants of the same title - "Sonic (USA) [!].md",
"Sonic (USA) [h1].md", "Sonic (U) [f1].md" - and filing all of them makes a
library where every game appears four times.

The bracket tags are a long-standing convention (GoodTools), so the choice is
not arbitrary: [!] marks a verified good dump, [h] a hack, [f] a fix, [b] a bad
dump, [o] an overdump, and (Beta)/(Proto)/(Demo) mark unfinished releases. This
ranks by those, then prefers the larger file as a tie-break.

Nothing is ever deleted here. Duplicates are simply not copied, and are
reported so the choice can be overridden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .scan import base_stem

#: Quality tags. Lower wins. Where several apply the *worst* one decides: a
#: file marked "(USA) [h1]" is a hack that happens to be American, and calling
#: it a US release would pick a hacked ROM over a clean one.
_QUALITY = (
    (re.compile(r"\[!\]"), 0, "verified good dump"),
    (re.compile(r"\[a\d*\]", re.I), 40, "alternate dump"),
    (re.compile(r"\[f\d*\]", re.I), 50, "fixed dump"),
    (re.compile(r"\[t[\d+-]*\]", re.I), 55, "translation"),
    (re.compile(r"\[h\d*\]", re.I), 60, "hack"),
    (re.compile(r"\[o\d*\]", re.I), 70, "overdump"),
    (re.compile(r"\(Beta\)|\(Proto\)|\(Demo\)|\(Sample\)|pre-?release", re.I),
     75, "unfinished release"),
    (re.compile(r"\[b\d*\]", re.I), 90, "bad dump"),
)

#: Region, used only to separate copies of equal quality.
_REGION = (
    (re.compile(r"\(U\)|\(USA\)|\(World\)|\(UE\)", re.I), 0, "US/World"),
    (re.compile(r"\(E\)|\(Europe\)", re.I), 1, "Europe"),
    (re.compile(r"\(J\)|\(Japan\)", re.I), 2, "Japan"),
)
_NEUTRAL = 30


@dataclass
class Skipped:
    name: str            # the actual filename, not the cleaned-up title
    system: str
    kept: str
    why: str

    def describe(self) -> str:
        return f"{self.system}: kept {self.kept}  |  skipped {self.name} ({self.why})"


def rank(name: str) -> tuple:
    """(quality, region, reason) for a filename - lower sorts better.

    The worst quality tag present decides, so "(USA) [h1]" ranks as a hack
    rather than as a US release.
    """
    quality, why = _NEUTRAL, "untagged"
    for pattern, score, label in _QUALITY:
        if pattern.search(name) and score > quality:
            quality, why = score, label
    for pattern, score, label in _QUALITY:          # [!] is better than neutral
        if score == 0 and pattern.search(name) and quality == _NEUTRAL:
            quality, why = 0, label

    region = 3
    for pattern, score, _label in _REGION:
        if pattern.search(name):
            region = min(region, score)
    return quality, region, why


def title_key(item) -> tuple:
    """What counts as "the same game": its system and its cleaned-up title."""
    return (item.system or "", base_stem(item.name))


def pick_best(items) -> tuple[list, list[Skipped]]:
    """Keep one item per title, returning (kept, skipped).

    Items without a system are always kept - they need a human decision, and
    silently dropping one as a "duplicate" would hide it.
    """
    groups: dict[tuple, list] = {}
    order: list = []
    passthrough = []

    for item in items:
        if not item.system:
            passthrough.append(item)
            continue
        key = title_key(item)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    kept, skipped = [], []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            kept.append(group[0])
            continue
        def sort_key(i):
            quality, region, _why = rank(i.raw_name or i.name)
            return (quality, region, -i.total_size, i.raw_name or i.name)

        scored = sorted(group, key=sort_key)
        winner = scored[0]
        kept.append(winner)
        win_name = winner.raw_name or winner.name
        for loser in scored[1:]:
            _q, _r, why = rank(loser.raw_name or loser.name)
            skipped.append(Skipped(loser.raw_name or loser.name, loser.system,
                                   win_name, why))
    return kept + passthrough, skipped

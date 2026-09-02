"""The comparator: match / mismatch, plus a legible unified diff.

Diffing normalised statutory text line-by-line is useless, because after
whitespace collapse there is exactly one line.  So the diff view re-segments both
sides into sentence-ish lines *purely for display* and diffs those.  The
segmentation never affects the match decision -- that is made on the normalised
strings themselves.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .normalize import ALL_RULES, normalize

# Split after sentence-ending punctuation followed by a capital or an open
# bracket.  Deliberately conservative: it must not split 'Sec. 28-1.' or
# 'P.A. 102-839' or '5-13-22.' mid-citation.
_SEGMENT_RE = re.compile(r"(?<=[.;:])\s+(?=[A-Z(\"'])")


# A segment that is nothing but a catchline ('Sec. 28-1.') is rejoined to the
# text that follows it, so a diff never shows the section number alone on a line.
_CATCHLINE_ONLY_RE = re.compile(r"^Sec\.\s*\S+\.$")


def segment(text: str) -> list[str]:
    """Break normalised text into display lines for diffing."""
    raw = [p.strip() for p in _SEGMENT_RE.split(text) if p.strip()]
    parts: list[str] = []
    for part in raw:
        if parts and _CATCHLINE_ONLY_RE.match(parts[-1]):
            parts[-1] = f"{parts[-1]} {part}"
        else:
            parts.append(part)
    out: list[str] = []
    for part in parts:
        # Very long segments still make an unreadable diff line; wrap them at a
        # word boundary near 100 chars.
        while len(part) > 120:
            cut = part.rfind(" ", 0, 100)
            if cut <= 0:
                break
            out.append(part[:cut])
            part = part[cut + 1 :]
        out.append(part)
    return out


def unified(published: str, replayed: str, *, label: str, context: int = 1) -> str:
    """A unified diff of the two normalised texts.

    ``published`` is the compiled ILCS section (what ILGA says the law is);
    ``replayed`` is the section as reprinted by its own source Public Act with
    strike-through removed and underscored text kept.
    """
    return "\n".join(
        difflib.unified_diff(
            segment(published),
            segment(replayed),
            fromfile=f"{label} (ILCS compilation)",
            tofile=f"{label} (as printed in its source Public Act)",
            lineterm="",
            n=context,
        )
    )


def word_changes(published: str, replayed: str, limit: int = 12) -> list[str]:
    """Compact word-level summary of what differs -- the triage view."""
    a = published.split()
    b = replayed.split()
    out: list[str] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        left = " ".join(a[i1:i2])
        right = " ".join(b[j1:j2])
        if tag == "replace":
            out.append(f"replace {left!r} -> {right!r}")
        elif tag == "delete":
            out.append(f"only in compilation: {left!r}")
        elif tag == "insert":
            out.append(f"only in Act: {right!r}")
        if len(out) >= limit:
            out.append("...")
            break
    return out


@dataclass
class Comparison:
    label: str
    exact_match: bool
    normalized_match: bool
    published_norm: str
    replayed_norm: str
    diff: str = ""
    changes: list[str] = field(default_factory=list)
    similarity: float = 0.0


def compare(
    published_text: str,
    replayed_text: str,
    *,
    label: str,
    enabled: tuple[str, ...] = ALL_RULES,
) -> Comparison:
    exact = published_text == replayed_text
    p = normalize(published_text, enabled)
    r = normalize(replayed_text, enabled)
    matched = p == r
    comparison = Comparison(
        label=label,
        exact_match=exact,
        normalized_match=matched,
        published_norm=p,
        replayed_norm=r,
    )
    if not matched:
        comparison.diff = unified(p, r, label=label)
        comparison.changes = word_changes(p, r)
        comparison.similarity = difflib.SequenceMatcher(
            a=p.split(), b=r.split(), autojunk=False
        ).ratio()
    else:
        comparison.similarity = 1.0
    return comparison

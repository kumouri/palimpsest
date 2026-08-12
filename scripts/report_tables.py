#!/usr/bin/env python3
"""Emit the Markdown tables for docs/oracle-0-baseline.md from a run's results.

The prose in the report is written by hand; the numbers in it are not. Run::

    PYTHONPATH=src python scripts/report_tables.py out/results.json

and paste the output, so a reader can regenerate every table in the report from
the run artifact rather than taking the figures on trust.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.normalize import rules_table  # noqa: E402

CLASS_MEANING = {
    "MATCH": "The compiled section and the Act's reprint agree.",
    "NORMALIZE": (
        "Normalisation artefact -- the two differ only in punctuation, case or "
        "whitespace. Counted as a **failure**, not an excuse."
    ),
    "TARGET_RESOLUTION": "Target-resolution failure -- the Act is online but we could not locate the section in it.",
    "REPEALED_STUB": "The compiled section is a repeal tombstone; a repealing Act reprints no text.",
    "MULTI_VERSION": "The section has more than one published version (ILGA's own conflict marker).",
    "MULTI_ACT": "The section's Source line names more than one Public Act.",
    "DIVERGENCE": "Candidate finding -- single Act, single version, and the words differ.",
    "ACT_NOT_ONLINE": "Excluded: the source Public Act is not published on ilga.gov.",
    "UNRECONSTRUCTABLE": "Excluded: the Source line names no Public Act at all.",
}


def pct(n: int, d: int) -> str:
    return f"{n / d:.1%}" if d else "n/a"


def main(path: str) -> int:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    s, cases = data["summary"], data["cases"]

    print("### Headline\n")
    print("| | |")
    print("|---|---|")
    print(f"| Sections sampled | {s['sampled']} |")
    print(f"| Excluded: Source names no Public Act | {s['excluded_no_public_act']} |")
    print(f"| Excluded: source Act not published online | {s['excluded_act_not_online']} |")
    print(f"| **Attempted (the denominator)** | **{s['attempted']}** |")
    print(
        f"| **Match rate, normalised** | **{s['match_rate_normalized']:.1%}** "
        f"({s['matched_normalized']}/{s['attempted']}) |"
    )
    print(
        f"| Match rate, exact bytes | {s['match_rate_exact']:.1%} "
        f"({s['matched_exact']}/{s['attempted']}) |"
    )

    print("\n### Classification of every sampled section\n")
    print("| Class | n | % of attempted | Meaning |")
    print("|---|---:|---:|---|")
    for cls, n in sorted(s["classes"].items(), key=lambda kv: -kv[1]):
        share = (
            "excluded" if cls in ("ACT_NOT_ONLINE", "UNRECONSTRUCTABLE") else pct(n, s["attempted"])
        )
        print(f"| `{cls}` | {n} | {share} | {CLASS_MEANING.get(cls, '')} |")

    print("\n### By ILCS Act\n")
    print("| ILCS Act | attempted | matched | rate | excluded |")
    print("|---|---:|---:|---:|---:|")
    for act, d in s["by_act"].items():
        print(
            f"| {act} | {d['attempted']} | {d['matched']} | "
            f"{pct(d['matched'], d['attempted'])} | {d['excluded']} |"
        )

    print("\n### By stratum\n")
    print("| Stratum | attempted | matched | rate | excluded |")
    print("|---|---:|---:|---:|---:|")
    for stratum, d in s["by_stratum"].items():
        print(
            f"| {stratum} | {d['attempted']} | {d['matched']} | "
            f"{pct(d['matched'], d['attempted'])} | {d['excluded']} |"
        )

    print("\n### Public Act availability by General Assembly\n")
    print("| GA | online | not online |")
    print("|---:|---:|---:|")
    for ga, d in s["ga_availability"].items():
        print(f"| {ga} | {d['online']} | {d['not_online']} |")

    print("\n### Normalisation ablation\n")
    print("| Rules enabled | matched | rate | marginal |")
    print("|---|---:|---:|---:|")
    for row in s.get("ablation", []):
        marginal = "--" if row["marginal"] is None else f"+{row['marginal']}"
        print(
            f"| {row['rules']} ({row['title']}) | {row['matched']}/{row['of']} | {row['rate']:.1%} | {marginal} |"
        )

    print("\n### Normalisation rules\n")
    print(rules_table())

    print("\n### Mismatches, most similar first\n")
    fails = [
        c
        for c in cases
        if c["classification"] not in ("MATCH", "ACT_NOT_ONLINE", "UNRECONSTRUCTABLE")
    ]
    fails.sort(key=lambda c: -c["similarity"])
    print("| Section | class | similarity | source line |")
    print("|---|---|---:|---|")
    for c in fails:
        print(
            f"| `{c['citation']}` | `{c['classification']}` | {c['similarity']:.3f} | "
            f"{c['source_line'][:70]} |"
        )

    print(
        f"\n<!-- distinct source Acts fetched: {len(Counter(c['terminal_pa'] for c in cases))} -->"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "out/results.json"))

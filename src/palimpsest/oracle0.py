"""Oracle-0: the single-hop match.

Spec §4.2, implemented literally:

    for each ILCS section version V:
        P := terminal Public Act in V's (Source: ...) line
        T := the text of that section as printed in Public Act P, with
             struck-through text removed and underscored text retained
        compare normalize(T) with normalize(V.text)

No history reconstruction, no chain, no effective-date reasoning, no patch
engine.  Just: the compilation says this Act last set this section, the Act
reprints the section, do they agree.

Run it::

    python -m palimpsest.oracle0 --out out

The first run crawls (at 10 s/request, per robots.txt); every run after that is
served from the on-disk cache and costs nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .compare import Comparison, compare
from .extract import extract
from .fetch import Fetcher, is_soft_404, public_act_url
from .normalize import NORMALIZER_VERSION, RULES, normalize
from .sample import (
    ActRef,
    list_acts,
    list_chapters,
    sections_of_act,
    stratify,
    take_evenly,
)
from .sections import SectionBlock, find_blocks_for, normalise_pa_number, parse_blocks

PIPELINE_VERSION = "oracle0/0.1.0"

# --- the sample --------------------------------------------------------------
#
# Declared here rather than passed in, so the run is reproducible from the source
# alone.  Chapters were chosen for subject-matter spread and for a mix of section
# lengths: chapter 5 is short and definitional, the Election Code and Property
# Tax Code contain some of the longest sections in Illinois law, and the Criminal
# Code and Vehicle Code are amended constantly.

SAMPLE_ACTS: tuple[tuple[str, str, str], ...] = (
    # (ILCS chapter number, ILCS act number, human label)
    ("5", "70", "Statute on Statutes"),
    ("5", "140", "Freedom of Information Act"),
    ("10", "5", "Election Code"),
    ("35", "200", "Property Tax Code"),
    ("625", "5", "Illinois Vehicle Code"),
    ("720", "5", "Criminal Code of 2012"),
    ("820", "305", "Workers' Compensation Act"),
)

QUOTAS: dict[str, int] = {
    # stratum -> sections drawn per ILCS Act
    "recent": 10,  # last set by the 103rd GA or later (2023+)
    "modern": 10,  # last set by the 90th-102nd GA (the expected online window)
    "pre_corpus": 2,  # last set before the 90th GA -- drawn to measure the floor
}

RECENT_GA = 103
CORPUS_FLOOR_GA = 90


# --- classification ----------------------------------------------------------

CLASS_MATCH = "MATCH"
CLASS_UNRECONSTRUCTABLE = "UNRECONSTRUCTABLE"
CLASS_ACT_NOT_ONLINE = "ACT_NOT_ONLINE"
CLASS_TARGET_RESOLUTION = "TARGET_RESOLUTION"
CLASS_REPEALED_STUB = "REPEALED_STUB"
CLASS_RENUMBERED = "RENUMBERED"
CLASS_NORMALIZE = "NORMALIZE"
CLASS_MULTI_VERSION = "MULTI_VERSION"
CLASS_MULTI_ACT = "MULTI_ACT"
CLASS_DIVERGENCE = "DIVERGENCE"

_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")


def reduce_to_alnum(text: str) -> str:
    """The punitive comparison used only to *classify* a mismatch.

    If two texts are equal once every character that is not a letter or digit is
    removed, then whatever differs between them is punctuation or whitespace --
    a normalisation artifact rather than a difference in words.  This never
    decides a match; it only sorts failures.

    **Case is deliberately preserved.**  Lowercasing here would be the quiet
    kind of mistake this whole project is built to avoid: the normaliser does
    not fold case (there is a test asserting it must not), so a case-only
    difference is a real difference in the text, and excusing it as "cosmetic"
    at classification time would bury it.  It buried a real one -- P.A. 97-81
    prints "Unless **An** Act otherwise specifically provides" while the
    compilation reads "Unless **an** Act".
    """
    return _ALNUM_RE.sub("", text)


_REPEALED_RE = re.compile(r"^Sec\.?\s*\S*\s*\.?\s*\(\s*Repealed\s*\)\.?$", re.I)


def is_repeal_stub(body: str) -> bool:
    """True if the compiled section is a repeal tombstone: ``Sec. 1-25. (Repealed).``

    Oracle-0 structurally cannot match these, and it is important that it says
    so rather than filing them as parser failures.  Spec §2.5: *"Repeals do not
    reprint text -- they name the act and list the repealed section numbers."*
    So the Act named in the Source line really does not contain the section, and
    no amount of better target resolution will find it.
    """
    return bool(_REPEALED_RE.match(" ".join(body.split())))


_RENUMBERED_RE = re.compile(r"\bRenumbered\s+by\b", re.I)


def is_renumbered(source_line: str) -> bool:
    """True if the compiled Source line says the section was renumbered away.

    ``(Source: P.A. 88-392. Renumbered by P.A. 96-1551, eff. 7-1-11.)`` -- the
    text moved to a new address and the old address is a tombstone.  The Act
    prints the section under its *new* citation with a ``(was 720 ILCS 5/12-31)``
    marker, so searching it for the old citation correctly finds nothing.  This
    is the resectioning case of spec §2.5, and it is a limit of the single-hop
    oracle rather than a failure of target resolution.
    """
    return bool(_RENUMBERED_RE.search(source_line))


@dataclass
class Case:
    citation: str
    act_label: str
    stratum: str
    source_line: str
    terminal_pa: str | None
    all_pas: list[str] = field(default_factory=list)
    published_chars: int = 0
    replayed_chars: int = 0
    candidates_in_act: int = 0
    added_by_this_act: bool = False
    carried_amendment_markup: bool = False
    """True if this section's reprint actually contained strike/underscore, so
    the match depended on resolving it rather than on copying clean text."""
    published_version_marker: str | None = None
    matched_version_marker: str | None = None
    strike_spans_in_act: int = 0
    insert_spans_in_act: int = 0
    exact_match: bool = False
    normalized_match: bool = False
    similarity: float = 0.0
    classification: str = ""
    note: str = ""
    changes: list[str] = field(default_factory=list)
    diff: str = ""


def classify(case: Case, published_norm: str, replayed_norm: str) -> str:
    if case.normalized_match:
        return CLASS_MATCH
    if is_repeal_stub(published_norm):
        return CLASS_REPEALED_STUB
    if case.candidates_in_act == 0:
        return CLASS_TARGET_RESOLUTION
    if reduce_to_alnum(published_norm) == reduce_to_alnum(replayed_norm):
        return CLASS_NORMALIZE
    if case.candidates_in_act > 1 or case.published_version_marker:
        return CLASS_MULTI_VERSION
    if len(case.all_pas) > 1:
        return CLASS_MULTI_ACT
    return CLASS_DIVERGENCE


# --- the run -----------------------------------------------------------------


def resolve_acts(fetcher: Fetcher) -> list[tuple[ActRef, str]]:
    """Turn the declared (chapter, act) pairs into ActIDs via the index walk."""
    chapters = {c.chapter_number: c for c in list_chapters(fetcher)}
    resolved: list[tuple[ActRef, str]] = []
    for chapter_number, act_number, label in SAMPLE_ACTS:
        chapter = chapters.get(chapter_number)
        if chapter is None:
            print(f"  !! chapter {chapter_number} not found in the index", flush=True)
            continue
        wanted = f"{chapter_number} ILCS {act_number}/"
        for act in list_acts(fetcher, chapter.chapter_id):
            if act.short.startswith(wanted):
                resolved.append((act, label))
                break
        else:
            print(f"  !! {wanted} not found in chapter {chapter_number}", flush=True)
    return resolved


def select_sample(fetcher: Fetcher) -> list[tuple[SectionBlock, str, str]]:
    """(block, act label, stratum) for every section in the sample."""
    selected: list[tuple[SectionBlock, str, str]] = []
    for act_ref, label in resolve_acts(fetcher):
        blocks = sections_of_act(fetcher, act_ref.act_id, act_ref.chapter_id)
        strata = stratify(blocks, recent_ga=RECENT_GA, corpus_floor_ga=CORPUS_FLOOR_GA)
        print(
            f"  {label}: {len(blocks)} sections ("
            + ", ".join(f"{len(v)} {k}" for k, v in strata.items())
            + ")",
            flush=True,
        )
        for stratum, quota in QUOTAS.items():
            for block in take_evenly(strata[stratum], quota):
                selected.append((block, label, stratum))
    return selected


def best_candidate(published: SectionBlock, candidates: list[SectionBlock]) -> SectionBlock | None:
    """Pick which reprint in the Act to compare against.

    An Act can print the same section twice -- once "before amendment by P.A. X"
    and once "after" (spec §2.3).  Prefer the one whose version marker matches
    the compiled block's; otherwise take the closest by normalised text, which is
    the honest reading of "did we manage to locate it".
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if published.version_marker:
        for c in candidates:
            if c.version_marker == published.version_marker:
                return c
    target = normalize(published.body)
    return max(
        candidates,
        key=lambda c: _ratio(target, normalize(c.body)),
    )


def _ratio(a: str, b: str) -> float:
    import difflib

    return difflib.SequenceMatcher(a=a.split(), b=b.split(), autojunk=False).ratio()


def run(out_dir: Path, *, cache_dir: Path, offline: bool = False, limit: int | None = None) -> dict:
    fetcher = Fetcher(cache_dir, offline=offline)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Selecting the sample (index walk; no /search, no /api) ...", flush=True)
    selected = select_sample(fetcher)
    if limit:
        selected = selected[:limit]
    print(f"\nSample: {len(selected)} sections\n", flush=True)

    # Distinct Public Acts first, so the cost of the crawl is visible up front.
    wanted_pas = sorted(
        {b.source.terminal_pa for b, _, _ in selected if b.source and b.source.terminal_pa}
    )
    print(f"Distinct source Public Acts to fetch: {len(wanted_pas)}", flush=True)

    act_cache: dict[str, list[SectionBlock] | None] = {}
    act_markup: dict[str, tuple[int, int]] = {}
    act_pre: dict[str, list[SectionBlock]] = {}
    """The same Acts parsed as they read *before* the amendment (struck text
    kept, underscored text dropped). Comparing a section's pre- and
    post-amendment bodies says whether that section actually carried amendatory
    markup -- which is what separates "we applied the markup correctly" from "we
    copied a clean reprint"."""

    def load_act(pa: str) -> tuple[list[SectionBlock], tuple[int, int]] | None:
        """Blocks of a Public Act; ``None`` means the Act is not online at all."""
        if pa in act_cache:
            cached = act_cache[pa]
            return None if cached is None else (cached, act_markup[pa])
        url = public_act_url(normalise_pa_number(pa))
        try:
            page = fetcher.get(url)
        except Exception as exc:  # noqa: BLE001 - a dead Act must not kill the run
            print(f"    !! {pa}: {exc}", flush=True)
            return None
        if page.status != 200 or not page.body.strip() or is_soft_404(page.body):
            act_cache[pa] = None
            return None
        ex = extract(page.body)
        blocks = parse_blocks(ex.text)
        act_cache[pa] = blocks
        act_markup[pa] = (ex.strike_spans, ex.insert_spans)
        act_pre[pa] = parse_blocks(extract(page.body, drop_strike=False, drop_insert=True).text)
        return blocks, act_markup[pa]

    cases: list[Case] = []
    pairs: list[tuple[str, str]] = []
    """(published body, replayed body) for every case that got as far as a
    comparison -- the input to the normalisation ablation."""
    for i, (block, label, stratum) in enumerate(selected, 1):
        src = block.source
        case = Case(
            citation=str(block.citation),
            act_label=label,
            stratum=stratum,
            source_line=src.raw if src else "",
            terminal_pa=src.terminal_pa if src else None,
            all_pas=list(src.pa_numbers) if src else [],
            published_chars=len(block.body),
            published_version_marker=block.version_marker,
        )
        if not src or not src.is_reconstructable:
            case.classification = CLASS_UNRECONSTRUCTABLE
            case.note = "source line names no Public Act (pre-1997 provenance)"
            cases.append(case)
            continue

        print(f"[{i}/{len(selected)}] {case.citation}  <- P.A. {case.terminal_pa}", flush=True)
        loaded = load_act(src.terminal_pa)
        if loaded is None:
            case.classification = CLASS_ACT_NOT_ONLINE
            case.note = (
                f"P.A. {src.terminal_pa} is not published on ilga.gov "
                "(HTTP 200, 'Document ... is not currently available')"
            )
            cases.append(case)
            continue
        act_blocks, (strikes, inserts) = loaded
        case.strike_spans_in_act = strikes
        case.insert_spans_in_act = inserts

        found = find_blocks_for(act_blocks, block.citation)
        # A '(... rep.)' header names a section the Act repeals. It carries no
        # statutory text, so it can never be the thing to compare against.
        repealed_here = [b for b in found if b.is_repealed_here]
        candidates = [b for b in found if not b.is_repealed_here]
        case.candidates_in_act = len(candidates)
        case.added_by_this_act = any(b.is_added for b in candidates)
        chosen = best_candidate(block, candidates)
        if chosen is None:
            if repealed_here:
                case.classification = CLASS_REPEALED_STUB
                case.note = (
                    f"the Act repeals this section -- it appears as "
                    f"'({block.citation} rep.)' and reprints no text"
                )
            elif is_repeal_stub(block.body):
                case.classification = CLASS_REPEALED_STUB
                case.note = (
                    "the compiled section is a repeal tombstone; a repealing Act "
                    "does not reprint text, so single-hop comparison cannot apply"
                )
            elif is_renumbered(case.source_line):
                case.classification = CLASS_RENUMBERED
                case.note = (
                    "the compiled Source line says this section was renumbered; "
                    "the Act prints it under its new citation with a '(was ...)' marker"
                )
            else:
                case.classification = CLASS_TARGET_RESOLUTION
                case.note = (
                    "the Act does not reprint this citation "
                    f"({len(act_blocks)} section blocks found in the Act)"
                    if act_blocks
                    else "no section blocks parsed out of the Act document"
                )
            cases.append(case)
            continue

        case.matched_version_marker = chosen.version_marker
        case.replayed_chars = len(chosen.body)
        pre_blocks = find_blocks_for(act_pre.get(src.terminal_pa, []), block.citation)
        if pre_blocks:
            case.carried_amendment_markup = normalize(pre_blocks[0].body) != normalize(chosen.body)
        pairs.append((block.body, chosen.body))
        cmp_: Comparison = compare(block.body, chosen.body, label=case.citation)
        case.exact_match = cmp_.exact_match
        case.normalized_match = cmp_.normalized_match
        case.similarity = round(cmp_.similarity, 4)
        case.classification = classify(case, cmp_.published_norm, cmp_.replayed_norm)
        case.changes = cmp_.changes
        case.diff = cmp_.diff
        cases.append(case)

    summary = summarise(cases, fetcher)
    summary["ablation"] = ablation(pairs)
    write_outputs(out_dir, cases, summary)
    return summary


# Classes excluded from the denominator, per spec §4.7. Both mean "we cannot
# see the answer", never "we looked and got it wrong".
EXCLUDED_CLASSES = frozenset({CLASS_UNRECONSTRUCTABLE, CLASS_ACT_NOT_ONLINE})


def summarise(cases: list[Case], fetcher: Fetcher | None = None) -> dict:
    attempted = [c for c in cases if c.classification not in EXCLUDED_CLASSES]
    matched = [c for c in attempted if c.normalized_match]
    exact = [c for c in attempted if c.exact_match]
    classes = Counter(c.classification for c in cases)

    def tally(key) -> dict[str, dict]:  # noqa: ANN001
        out: dict[str, dict] = {}
        for c in cases:
            d = out.setdefault(key(c), {"attempted": 0, "matched": 0, "excluded": 0})
            if c.classification in EXCLUDED_CLASSES:
                d["excluded"] += 1
            else:
                d["attempted"] += 1
                d["matched"] += int(c.normalized_match)
        return out

    by_act = tally(lambda c: c.act_label)
    by_stratum = tally(lambda c: c.stratum)

    # The corpus floor, measured rather than assumed (spec §2.9, Appendix A).
    ga_availability: dict[str, dict] = {}
    for c in cases:
        if not c.terminal_pa:
            continue
        ga = c.terminal_pa.split("-", 1)[0]
        d = ga_availability.setdefault(ga, {"online": 0, "not_online": 0})
        if c.classification == CLASS_ACT_NOT_ONLINE:
            d["not_online"] += 1
        else:
            d["online"] += 1

    with_markup = [c for c in attempted if c.carried_amendment_markup]
    added = [c for c in attempted if c.added_by_this_act]
    # Cases Oracle-0 cannot address by construction: a repealing Act reprints no
    # text (spec §2.5) and a renumbering moves the text to another citation.
    structural = [
        c for c in attempted if c.classification in (CLASS_REPEALED_STUB, CLASS_RENUMBERED)
    ]

    return {
        "ga_availability": dict(sorted(ga_availability.items(), key=lambda kv: int(kv[0]))),
        "with_amendment_markup": len(with_markup),
        "with_amendment_markup_matched": sum(1 for c in with_markup if c.normalized_match),
        "added_by_source_act": len(added),
        "added_by_source_act_matched": sum(1 for c in added if c.normalized_match),
        "structurally_out_of_reach": len(structural),
        "pipeline_version": PIPELINE_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "sampled": len(cases),
        "attempted": len(attempted),
        "excluded_total": len(cases) - len(attempted),
        "excluded_no_public_act": classes.get(CLASS_UNRECONSTRUCTABLE, 0),
        "excluded_act_not_online": classes.get(CLASS_ACT_NOT_ONLINE, 0),
        "matched_normalized": len(matched),
        "matched_exact": len(exact),
        "match_rate_normalized": (len(matched) / len(attempted)) if attempted else 0.0,
        "match_rate_exact": (len(exact) / len(attempted)) if attempted else 0.0,
        "classes": dict(classes),
        "by_act": by_act,
        "by_stratum": by_stratum,
        "fetches": None if fetcher is None else fetcher.fetched,
        "cache_hits": None if fetcher is None else fetcher.served_from_cache,
    }


def ablation(pairs: list[tuple[str, str]]) -> list[dict]:
    """Match rate with normalisation rules switched on cumulatively.

    The anti-self-deception device.  Row 0 is the raw extracted text compared
    byte for byte; each subsequent row adds one rule.  The ``marginal`` column is
    how many matches that single rule bought.  A rule with a large marginal is a
    rule to interrogate, not to celebrate: it means a large fraction of the
    headline number rests on that one transformation being legitimate.
    """
    rows: list[dict] = []
    prev: int | None = None
    for i in range(len(RULES) + 1):
        enabled = tuple(r.key for r in RULES[:i])
        n = sum(1 for p, r in pairs if normalize(p, enabled) == normalize(r, enabled))
        rows.append(
            {
                "rules": "none (raw extracted text)" if i == 0 else f"+ {RULES[i - 1].key}",
                "title": "raw" if i == 0 else RULES[i - 1].title,
                "enabled": list(enabled),
                "matched": n,
                "of": len(pairs),
                "rate": n / len(pairs) if pairs else 0.0,
                "marginal": None if prev is None else n - prev,
            }
        )
        prev = n
    return rows


def write_outputs(out_dir: Path, cases: list[Case], summary: dict) -> None:
    (out_dir / "results.json").write_text(
        json.dumps({"summary": summary, "cases": [asdict(c) for c in cases]}, indent=2),
        encoding="utf-8",
    )
    diffs = [
        f"=== {c.citation}  [{c.classification}]  (source: {c.source_line})\n"
        f"    similarity {c.similarity:.3f}; "
        f"{c.published_chars} chars published vs {c.replayed_chars} replayed\n"
        + (f"    note: {c.note}\n" if c.note else "")
        + (("\n".join("    * " + ch for ch in c.changes) + "\n") if c.changes else "")
        + c.diff
        for c in cases
        if c.diff or c.classification not in (CLASS_MATCH, *EXCLUDED_CLASSES)
    ]
    (out_dir / "mismatches.diff").write_text("\n\n".join(diffs), encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"ORACLE-0  ({summary['pipeline_version']}, normaliser {summary['normalizer_version']})")
    print("=" * 72)
    print(f"  sampled                 {summary['sampled']}")
    print(f"  excluded: no P.A. source     {summary['excluded_no_public_act']}")
    print(f"  excluded: Act not online     {summary['excluded_act_not_online']}")
    print(f"  attempted               {summary['attempted']}")
    print(
        f"  MATCH RATE (normalised) {summary['match_rate_normalized']:.1%}  "
        f"({summary['matched_normalized']}/{summary['attempted']})"
    )
    print(
        f"  match rate (exact bytes){summary['match_rate_exact']:.1%}  "
        f"({summary['matched_exact']}/{summary['attempted']})"
    )
    print("  classes:")
    for k, v in sorted(summary["classes"].items(), key=lambda kv: -kv[1]):
        print(f"      {k:22s} {v}")
    print(f"  fetches this run: {summary['fetches']}  (cache hits: {summary['cache_hits']})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run Oracle-0 over a sample of ILCS sections.")
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument("--offline", action="store_true", help="fail rather than fetch")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    run(args.out, cache_dir=args.cache, offline=args.offline, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())

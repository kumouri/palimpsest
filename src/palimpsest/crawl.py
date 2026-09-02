"""The bulk mirror: a resumable, rate-limited, content-addressed crawl of ilga.gov.

Run it with ``python -m palimpsest.crawl`` (see :func:`main` for the flags).

Read this before changing anything here
=======================================

**One request in flight, ten seconds apart, forever.**  ``robots.txt`` says
``Crawl-delay: 10`` and this crawler has no parallelism to remove -- there is no
thread pool, no ``asyncio``, no batching.  That is not an oversight to be
optimised later.  ilga.gov is the *only* publisher of this data; there is no
mirror and no second source.  The crawl being slow is the cheapest constraint in
the project, and it is the one that keeps the project possible.

**Any hint of throttling ends the run.**  :class:`~palimpsest.fetch.RateLimited`
propagates out of here uncaught, on purpose (see its docstring).

What the crawl is actually for, and why the order is what it is
---------------------------------------------------------------

The naive reading of spec §2.1 is "fetch 30,000 sections one at a time, 83
hours".  Two findings collapse that:

1. **The Act is the fetch unit, not the section.**  An Act's ``Articles`` page
   embeds the full text of every section in it, and for the Acts too large for
   that, one ``ChapAct=FullText`` link returns the whole Act in a single
   document (``sample.sections_of_act``).  The Election Code is 963 sections in
   one fetch.  Measured by the index walk: **3,479 Acts across 68 chapters**, so
   the compiled-statute side costs 3,479-6,958 requests -- roughly 10-19 hours
   -- rather than 30,000 requests and 83.
2. **The compiled side of the Oracle-0 sample is already mirrored.**  Oracle-0
   fetched seven Acts to sample 112 sections out of them -- but those seven
   fetches brought back **4,600 sections**, all still sitting in the cache.  The
   only thing stopping the oracle from running over them is the *other* side of
   each pair: the Public Act each section names as its source.

   **Of those 4,600, 2,540 are checkable** -- and the gap is the finding.  1,798
   (39.1 %) name a source Act below the corpus floor and can never be checked
   against it; 262 (5.7 %) name no Public Act at all.  Oracle-0 measured that
   exclusion at 16 %, but its sample was *stratified* (ten recent, ten modern,
   two pre-corpus per Act), which deliberately under-drew the pre-corpus
   stratum.  Against the unstratified population the true rate is **39 %**.  A
   sample designed for coverage of the strata is not a sample that estimates
   their sizes, and reading one as the other understates the corpus-coverage
   problem by a factor of two and a half.

So the queue is ordered by what buys the next oracle run the most, per request:

===== ================================================================
Tier  What, and why it is where it is
===== ================================================================
0     The Public Acts cited by those already-mirrored sections.  ~600
      requests takes the oracle from 94 attempted sections to a
      ceiling of 2,540 -- 27x -- with no new ILCS fetching at all.
      Nothing else in the corpus comes close to that ratio, so
      nothing else goes first.
1     A probe of Public Acts *below* the measured corpus floor.  Ten
      requests to re-measure a boundary the rest of the queue assumes
      (see `FLOOR_GA`).  Cheap, and it stops an assumption from
      hardening into a fact.
2     Every remaining ILCS Act in a chapter the sample already touches
      -- so the corpus grows around a core that is already
      oracle-checkable rather than as scattered islands.
3     Every other ILCS Act, by chapter number.
4     Public Acts discovered from tiers 2-3, as they are uncovered.
===== ================================================================

Tiers 0-3 are **materialised up front**, before the first tier-0 request: the
chapter/act index walk that enumerates them is part of ``build``, so the run is
a known-size job with a real ETA rather than a discovery process that finds out
how big it is by finishing.  Tier 4 cannot be -- a Public Act's number is only
knowable by reading a section's Source line -- so it is appended as it is
found, and the status file reports it separately rather than quietly inflating
the denominator.

Resumability
------------

There is no progress ledger to corrupt or to fall out of sync.  **The cache is
the ledger**: an item is done when its URL is in the cache, which
:meth:`~palimpsest.fetch.Fetcher.get` answers from disk without a request.  A
resumed run re-walks the whole queue, skips what it already has at memory speed,
and picks up at the first gap.  Killing this process at any moment, by any
means, loses at most the one page in flight.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .fetch import (
    CRAWL_DELAY,
    Fetcher,
    FetchError,
    RateLimited,
    ilcs_articles_url,
    is_soft_404,
    public_act_url,
)
from .oracle0 import SAMPLE_ACTS
from .sample import ActRef, ga_of, list_acts, list_chapters, sections_of_act
from .sections import normalise_pa_number

FLOOR_GA = 93
"""The General Assembly at which Public Act text starts being published.

**Measured, not assumed** (``docs/oracle-0-baseline.md`` §6): 090-0001,
091-0001, 091-0500 and 092-0001 all return ilga.gov's "not currently available"
placeholder, and 093-0001 onward all return the Act.  The queue skips Public
Acts below this line because fetching them costs ten seconds each to learn
nothing -- 456 of them in the sample Acts alone, over an hour of the budget.

A skip is only honest if it is counted and re-checked, so: the number skipped is
reported in the status file, and tier 1 re-probes the boundary every run.
"""

FLOOR_PROBE = (
    "090-0001",
    "091-0001",
    "091-0500",
    "092-0001",
    "092-0500",
    "092-0900",
    "093-0001",
    "093-0002",
    "093-0500",
    "094-0001",
)
"""Ten Acts straddling ``FLOOR_GA``, fetched every run to re-measure the floor.

Six below the line and four at or above it.  If the ones below ever start
returning text, the corpus floor has moved and tier 0's skip is leaving data on
the table; if the ones above ever stop, something has broken.  Either way the
run reports it instead of assuming the boundary held.
"""

STATUS_EVERY = 300.0
"""Seconds between status-file writes. The brief asks for five minutes."""

KIND_ILCS_ACT = "ilcs_act"
KIND_PUBLIC_ACT = "public_act"


@dataclass
class Item:
    """One unit of work: exactly one page to have in the mirror."""

    kind: str
    url: str
    tier: int
    label: str
    act_id: str = ""
    chapter_id: str = ""
    pa_number: str = ""


@dataclass
class Queue:
    built_at: float
    items: list[Item] = field(default_factory=list)
    skipped_below_floor: int = 0
    """Public Acts left out of tier 0 because they predate ``FLOOR_GA``.
    Recorded so that "we fetched everything in the queue" can never be mistaken
    for "we fetched everything there is"."""
    sample_sections: int = 0
    """Sections mirrored in the seven Oracle-0 sample Acts."""
    sample_checkable: int = 0
    """How many of those the oracle can actually check once tier 0 lands.

    Deliberately a separate number from ``sample_sections``.  A section is only
    checkable if the Public Act its Source line names is published, and 45 % of
    these are not -- so quoting the mirrored count as the oracle's reach would
    overstate it by nearly a factor of two."""
    sample_below_floor: int = 0
    sample_no_public_act: int = 0
    chapters: int = 0

    def to_json(self) -> str:
        payload = asdict(self)
        payload["items"] = [asdict(i) for i in self.items]
        return json.dumps(payload, indent=2)

    @classmethod
    def from_json(cls, text: str) -> Queue:
        raw = json.loads(text)
        items = [Item(**i) for i in raw.pop("items", [])]
        return cls(items=items, **raw)


# -- building the queue -------------------------------------------------------


def _act_key(label: str) -> tuple[str, str] | None:
    """'10 ILCS 5/ Election Code.' -> ('10', '5')."""
    head, sep, tail = label.partition(" ILCS ")
    if not sep:
        return None
    chapter = head.strip()
    act = tail.split("/")[0].strip()
    if not chapter or not act:
        return None
    return chapter, act


def sample_public_acts(
    fetcher: Fetcher, acts_by_key: dict[tuple[str, str], ActRef]
) -> tuple[list[str], int, tuple[int, int, int, int]]:
    """Terminal Public Acts of every section in the Oracle-0 sample Acts.

    Returns ``(pa_numbers_at_or_above_floor, skipped_below_floor, counts)`` where
    ``counts`` is ``(sections_seen, checkable, below_floor, no_public_act)``.

    Reads only the cache -- these seven Acts were mirrored by the Oracle-0 run,
    so enumerating roughly six hundred high-value fetches costs zero requests.
    An Act that is somehow *not* cached is fetched, which is correct but should
    not normally happen.
    """
    at_floor: dict[str, None] = {}
    below = set()
    sections = checkable = below_floor = no_pa = 0
    for chapter, act, _label in SAMPLE_ACTS:
        ref = acts_by_key.get((chapter, act))
        if ref is None:
            continue
        try:
            blocks = sections_of_act(fetcher, ref.act_id, ref.chapter_id)
        except FetchError:
            continue
        sections += len(blocks)
        for block in blocks:
            if not (block.source and block.source.terminal_pa):
                no_pa += 1
                continue
            raw = block.source.terminal_pa
            if ga_of(raw) >= FLOOR_GA:
                at_floor.setdefault(normalise_pa_number(raw), None)
                checkable += 1
            else:
                below.add(normalise_pa_number(raw))
                below_floor += 1
    return list(at_floor), len(below), (sections, checkable, below_floor, no_pa)


def build_queue(fetcher: Fetcher, *, deadline: float | None = None) -> Queue:
    """Walk the chapter/act index and materialise the whole job.

    This is the part that makes the crawl a known-size job.  It costs one fetch
    per ILCS chapter (68 of them, ~11 minutes at the crawl delay) and yields
    every Act in the compilation -- 3,479 of them, the complete tier-2 and
    tier-3 work list.  Both index levels are ordinary cached fetches, so a
    rebuild after a resumed run is free and can be run ``--offline``.
    """
    chapters = list_chapters(fetcher)
    print(f"[build] {len(chapters)} ILCS chapters", flush=True)

    sample_chapters = {chapter for chapter, _act, _label in SAMPLE_ACTS}
    sample_keys = {(chapter, act) for chapter, act, _label in SAMPLE_ACTS}

    acts_by_key: dict[tuple[str, str], ActRef] = {}
    ordered: list[tuple[int, str, ActRef]] = []
    for index, chapter in enumerate(chapters, 1):
        if deadline is not None and time.time() > deadline:
            print("[build] deadline reached during the index walk", flush=True)
            break
        try:
            acts = list_acts(fetcher, chapter.chapter_id)
        except FetchError as exc:
            print(f"[build] chapter {chapter.chapter_number}: {exc}", flush=True)
            continue
        print(
            f"[build] {index}/{len(chapters)} chapter {chapter.chapter_number}: {len(acts)} Acts",
            flush=True,
        )
        for act in acts:
            key = _act_key(act.short)
            if key is not None:
                acts_by_key[key] = act
            # Acts in a chapter the sample already touches come first in tier 2,
            # so the mirror grows outward from oracle-checkable ground.
            near = key is not None and key[0] in sample_chapters
            ordered.append((0 if near else 1, chapter.chapter_number, act))

    pas, skipped, counts = sample_public_acts(fetcher, acts_by_key)
    sections, checkable, below_floor, no_pa = counts
    print(
        f"[build] sample Acts hold {sections} sections citing {len(pas)} Public Acts "
        f"at or above the {FLOOR_GA}rd GA ({skipped} older ones skipped)",
        flush=True,
    )
    print(
        f"[build] of those {sections} sections, {checkable} are checkable; "
        f"{below_floor} name a source Act below the floor and {no_pa} name none",
        flush=True,
    )

    items: list[Item] = []
    for pa in pas:
        items.append(
            Item(
                kind=KIND_PUBLIC_ACT,
                url=public_act_url(pa),
                tier=0,
                label=f"P.A. {pa}",
                pa_number=pa,
            )
        )
    for pa in FLOOR_PROBE:
        items.append(
            Item(
                kind=KIND_PUBLIC_ACT,
                url=public_act_url(pa),
                tier=1,
                label=f"floor probe P.A. {pa}",
                pa_number=pa,
            )
        )
    for near, _chapter_number, act in sorted(ordered, key=lambda t: (t[0], _sort_key(t[1]))):
        key = _act_key(act.short)
        if key in sample_keys:
            continue  # already mirrored by the Oracle-0 run
        items.append(
            Item(
                kind=KIND_ILCS_ACT,
                url="",  # sections_of_act builds and follows its own URLs
                tier=2 if near == 0 else 3,
                label=act.short,
                act_id=act.act_id,
                chapter_id=act.chapter_id,
            )
        )

    return Queue(
        built_at=time.time(),
        items=items,
        skipped_below_floor=skipped,
        sample_sections=sections,
        sample_checkable=checkable,
        sample_below_floor=below_floor,
        sample_no_public_act=no_pa,
        chapters=len(chapters),
    )


def _sort_key(chapter_number: str) -> tuple[int, str]:
    """Chapter numbers sort numerically where they can ('5' before '35')."""
    try:
        return (int(chapter_number), "")
    except ValueError:
        return (10**9, chapter_number)


# -- running ------------------------------------------------------------------


@dataclass
class Progress:
    started: float
    total: int
    done: int = 0
    requests: int = 0
    cached: int = 0
    soft_404: int = 0
    errors: int = 0
    sections: int = 0
    discovered_pas: int = 0
    floor_probed: int = 0
    """Floor-probe items actually fetched this run.

    Kept separate from ``floor_moved`` because "the probe found nothing wrong"
    and "the probe has not run yet" are the same empty list, and reporting the
    second as the first would be claiming a measurement that never happened.
    """
    floor_moved: list[str] = field(default_factory=list)
    stopped_because: str = "running"

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    @property
    def rate(self) -> float:
        """Seconds per network request actually observed."""
        return self.elapsed / self.requests if self.requests else 0.0

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.done)


def _is_done(fetcher: Fetcher, item: Item) -> bool:
    """Is this item already mirrored? The cache is the ledger.

    Tests the metadata file's *existence* rather than parsing it, because the
    metadata is written last -- after the body object is in place -- so its
    presence is exactly the signal that the entry is complete.  It is also cheap
    enough to re-run over the whole queue on every status write.
    """
    url = (
        item.url
        if item.kind == KIND_PUBLIC_ACT
        else ilcs_articles_url(item.act_id, item.chapter_id)
    )
    return fetcher._meta_path(url).exists()


def run(
    fetcher: Fetcher,
    queue: Queue,
    *,
    deadline: float,
    status_paths: list[Path],
    queue_path: Path,
    stop_file: Path,
) -> Progress:
    """Drain the queue until it is empty, the deadline passes, or we are asked to stop.

    :class:`RateLimited` is **not** caught: it aborts the run with the status
    file written and the queue intact.
    """
    progress = Progress(started=time.time(), total=len(queue.items))
    last_status = 0.0
    index = 0

    while index < len(queue.items):
        item = queue.items[index]
        index += 1

        if time.time() - last_status >= STATUS_EVERY:
            _write_status(progress, queue, status_paths, deadline, tier_breakdown(fetcher, queue))
            last_status = time.time()

        if _is_done(fetcher, item):
            progress.done += 1
            progress.cached += 1
            continue

        if time.time() >= deadline:
            progress.stopped_because = "the four-hour fetch budget was spent"
            break
        if stop_file.exists():
            progress.stopped_because = f"the stop file {stop_file.name} appeared"
            break

        try:
            new_pas = _fetch_item(fetcher, item, progress)
        except RateLimited:
            progress.stopped_because = "RATE LIMITED -- see the report"
            _write_status(progress, queue, status_paths, deadline, tier_breakdown(fetcher, queue))
            _save_run_summary(fetcher.cache_dir, progress)
            raise
        except FetchError as exc:
            progress.errors += 1
            print(f"  [error] {item.label}: {exc}", flush=True)
            new_pas = []

        progress.done += 1
        if new_pas:
            for pa in new_pas:
                queue.items.append(
                    Item(
                        kind=KIND_PUBLIC_ACT,
                        url=public_act_url(pa),
                        tier=4,
                        label=f"P.A. {pa}",
                        pa_number=pa,
                    )
                )
            progress.discovered_pas += len(new_pas)
            progress.total = len(queue.items)
            queue_path.write_text(queue.to_json(), encoding="utf-8")
    else:
        progress.stopped_because = "the queue was drained"

    _write_status(
        progress,
        queue,
        status_paths,
        deadline,
        tier_breakdown(fetcher, queue),
        probe_floor(fetcher),
    )
    _save_run_summary(fetcher.cache_dir, progress)
    return progress


def _save_run_summary(cache_dir: Path, progress: Progress) -> None:
    """Persist the figures only a run can know, for ``--report-only`` to reuse.

    Counts of what is mirrored can always be recomputed from the cache; wall
    clock, requests issued and the observed rate cannot, and losing them would
    make a later report quietly understate what the crawl cost.
    """
    payload = asdict(progress)
    payload["elapsed_seconds"] = round(progress.elapsed, 1)
    try:
        (cache_dir / "last-run.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def _fetch_item(fetcher: Fetcher, item: Item, progress: Progress) -> list[str]:
    """Mirror one item. Returns Public Act numbers newly discovered by it."""
    before = fetcher.fetched
    if item.kind == KIND_PUBLIC_ACT:
        response = fetcher.get(item.url)
        progress.requests += fetcher.fetched - before
        if item.tier == 1:
            progress.floor_probed += 1
        if response.status == 404 or is_soft_404(response.body):
            progress.soft_404 += 1
            if ga_of(item.pa_number) >= FLOOR_GA and item.tier == 1:
                progress.floor_moved.append(f"{item.pa_number} unavailable (expected available)")
        elif item.tier == 1 and ga_of(item.pa_number) < FLOOR_GA:
            # A pre-floor Act that *does* return text: the floor has moved.
            progress.floor_moved.append(f"{item.pa_number} available (expected unavailable)")
        return []

    blocks = sections_of_act(fetcher, item.act_id, item.chapter_id)
    progress.requests += fetcher.fetched - before
    progress.sections += len(blocks)
    print(f"  [act] {item.label[:64]}  sections={len(blocks)}", flush=True)
    found: dict[str, None] = {}
    for block in blocks:
        if block.source and block.source.terminal_pa:
            raw = block.source.terminal_pa
            if ga_of(raw) >= FLOOR_GA:
                number = normalise_pa_number(raw)
                if fetcher._read_meta(public_act_url(number)) is None:
                    found.setdefault(number, None)
    return list(found)


# -- the status file ----------------------------------------------------------


def _fmt_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


TIER_NAMES = {
    0: "Public Acts cited by the Oracle-0 sample Acts",
    1: "Corpus-floor probe",
    2: "ILCS Acts in chapters the sample touches",
    3: "ILCS Acts elsewhere in the compilation",
    4: "Public Acts discovered while crawling tiers 2-3",
}

RESUME_COMMAND = (
    "PYTHONPATH=src python -m palimpsest.crawl \\\n"
    "  --cache /path/to/cache \\\n"
    "  --max-hours 4 \\\n"
    "  --status docs/crawl-status.md --status out/crawl-status.json"
)
"""The exact command that picks the crawl up where it stopped.

Note what is *absent*: ``--rebuild-queue``.  Leaving it off is what makes this a
resume rather than a restart -- the materialised queue is reused, and every item
already in the mirror is skipped without a request.  There is no other state to
restore and no ``--from`` offset to get wrong.
"""


def probe_floor(fetcher: Fetcher) -> tuple[int, list[str]]:
    """Re-measure the corpus floor from the mirror. Returns ``(probed, disagreements)``.

    Derived from the cache rather than from a counter the run kept, for the same
    reason resumability is: **the mirror is the ledger.**  A run counter only
    knows what *this* process fetched, so a resumed run, or a report generated
    after the crawl exited, would read "the probe has not run" for a probe that
    is sitting complete on disk -- turning a real measurement into a false
    negative.  Reading the answer off the mirror is true whenever it is asked.
    """
    probed = 0
    disagreements: list[str] = []
    for pa in FLOOR_PROBE:
        url = public_act_url(pa)
        meta = fetcher._read_meta(url)
        if meta is None:
            continue
        probed += 1
        body = fetcher._read_body(url, meta) or ""
        available = meta.get("status") == 200 and not is_soft_404(body) and len(body) > 500
        expected = ga_of(pa) >= FLOOR_GA
        if available and not expected:
            disagreements.append(f"{pa} is available, but predates the {FLOOR_GA}rd GA")
        elif expected and not available:
            disagreements.append(f"{pa} is unavailable, but is at or above the {FLOOR_GA}rd GA")
    return probed, disagreements


def tier_breakdown(fetcher: Fetcher, queue: Queue) -> list[tuple[int, int, int]]:
    """``(tier, done, total)`` per tier, counted against the cache.

    This is what "what remains" actually means, and it is worth spelling out by
    tier rather than as one number: the tiers are ordered by value, so 100 items
    left in tier 0 and 100 left in tier 3 are very different situations.
    """
    counts: dict[int, list[int]] = {}
    for item in queue.items:
        row = counts.setdefault(item.tier, [0, 0])
        row[1] += 1
        if _is_done(fetcher, item):
            row[0] += 1
    return [(tier, done, total) for tier, (done, total) in sorted(counts.items())]


def status_markdown(
    progress: Progress,
    queue: Queue,
    deadline: float | None = None,
    breakdown: list[tuple[int, int, int]] | None = None,
    floor: tuple[int, list[str]] | None = None,
) -> str:
    """The human-readable status file, regenerated in full every five minutes.

    It is regenerated rather than appended to because a status file that can
    disagree with itself is worse than none: every number here describes the
    same instant.
    """
    eta = progress.remaining * progress.rate if progress.rate else 0.0
    floor_probed, floor_moved = (
        floor
        if floor is not None
        else (
            progress.floor_probed,
            progress.floor_moved,
        )
    )
    stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
    pct = (100.0 * progress.done / progress.total) if progress.total else 0.0

    lines = [
        "# Crawl status",
        "",
        f"*Generated by `palimpsest.crawl` at {stamp}. Regenerated in full every five minutes;",
        "every figure below describes the same instant.*",
        "",
        f"**{progress.stopped_because}.**",
        "",
        "## Where the mirror is",
        "",
        "| | |",
        "|---|---:|",
        f"| Queue items mirrored | {progress.done:,} of {progress.total:,} ({pct:.1f} %) |",
        f"| Remaining in the queue | {progress.remaining:,} |",
        f"| Network requests, last crawl run | {progress.requests:,} |",
        f"| Wall clock, last crawl run | {_fmt_duration(progress.elapsed)} |",
        f"| Observed rate | {progress.rate:.1f} s/request (floor is {CRAWL_DELAY:.0f}) |",
        f"| ETA for the rest of the queue | {_fmt_duration(eta)} |",
        "",
        "## What came back",
        "",
        "| | |",
        "|---|---:|",
        f"| ILCS sections mirrored this run | {progress.sections:,} |",
        f"| Sections mirrored in the seven Oracle-0 sample Acts | {queue.sample_sections:,} |",
        f"| ... of those, checkable against their own source Act | {queue.sample_checkable:,} |",
        f"| ... source Act predates the corpus floor, never checkable | {queue.sample_below_floor:,} |",
        f"| ... Source line names no Public Act at all | {queue.sample_no_public_act:,} |",
        f"| Public Acts newly discovered (tier 4) | {progress.discovered_pas:,} |",
        f"| Documents not published online (soft 404) | {progress.soft_404:,} |",
        f"| Fetch errors | {progress.errors:,} |",
        "",
        "## What is deliberately *not* in the queue",
        "",
        f"**{queue.skipped_below_floor:,} Public Acts predating the {FLOOR_GA}rd General Assembly.**",
        "ilga.gov does not publish their text (measured, `docs/oracle-0-baseline.md` §6), so each",
        "would cost ten seconds to confirm a known absence. They are excluded from the counts above,",
        "not silently folded into them.",
        "",
    ]
    if floor_moved:
        lines += [
            "> **The floor probe disagrees with the recorded floor.** "
            "The queue's skip may be wrong:",
            "",
        ]
        lines += [f"> - {note}" for note in floor_moved]
        lines.append("")
    elif floor_probed:
        lines += [
            f"**The floor probe re-measured the boundary and it held**, {floor_probed} of "
            f"{len(FLOOR_PROBE)} Acts checked against the mirror: every Act below the "
            f"{FLOOR_GA}rd GA",
            f"returns the placeholder and every Act at or above it returns text. The {FLOOR_GA}rd",
            "remains the earliest General Assembly with published Public Act text, and the",
            "queue's skip of the older ones is therefore still correct.",
            "",
        ]
    else:
        lines += [
            "**The floor probe has not run**, so nothing here re-measures the corpus floor —",
            f"the {FLOOR_GA}rd GA is the *previously recorded* boundary, carried forward rather",
            "than confirmed.",
            "",
        ]

    if breakdown:
        lines += [
            "## What remains, by tier",
            "",
            "The tiers are ordered by what each buys the next oracle run per request, so where the",
            "remaining work sits matters as much as how much of it there is.",
            "",
            "| Tier | | Done | Total | Remaining |",
            "|---:|---|---:|---:|---:|",
        ]
        for tier, done, total in breakdown:
            name = TIER_NAMES.get(tier, f"tier {tier}")
            lines.append(f"| {tier} | {name} | {done:,} | {total:,} | {total - done:,} |")
        lines.append("")

    lines += [
        "## Resuming",
        "",
        "The crawl is resumable at any point, by design: **the mirror is the ledger.** An item is",
        "done when its URL is in the cache, so a resumed run re-walks the queue, skips what it",
        "already has at memory speed, and continues at the first gap. Killing the process at any",
        "moment loses at most the single page in flight.",
        "",
        "```bash",
        RESUME_COMMAND,
        "```",
        "",
        "`--rebuild-queue` is deliberately **not** in that command: omitting it reuses the",
        "materialised queue, which is what makes this a resume rather than a restart. Pass it only",
        "to re-walk the chapter/act index after the compilation itself has changed.",
        "",
        "To stop a running crawl cleanly, create the file `STOP-CRAWL` in the cache directory; the",
        "crawler notices before its next request and exits having written this file.",
        "",
    ]
    return "\n".join(lines)


def _write_status(
    progress: Progress,
    queue: Queue,
    paths: list[Path],
    deadline: float | None = None,
    breakdown: list[tuple[int, int, int]] | None = None,
    floor: tuple[int, list[str]] | None = None,
) -> None:
    markdown = status_markdown(progress, queue, deadline, breakdown, floor)
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".json":
                payload = asdict(progress)
                payload.update(
                    {
                        "remaining": progress.remaining,
                        "rate_seconds_per_request": round(progress.rate, 2),
                        "elapsed_seconds": round(progress.elapsed, 1),
                        "skipped_below_floor": queue.skipped_below_floor,
                        "floor_probed": (floor or (progress.floor_probed, []))[0],
                        "floor_moved": (floor or (0, progress.floor_moved))[1],
                        "tiers": [
                            {"tier": t, "done": d, "total": n, "remaining": n - d}
                            for t, d, n in (breakdown or [])
                        ],
                        "generated_at": time.time(),
                    }
                )
                path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            else:
                path.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            print(f"  [status] could not write {path}: {exc}", flush=True)


# -- entry point --------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Mirror ilga.gov: one request in flight, "
        f"{CRAWL_DELAY:.0f}s apart, resumable, stops on any sign of throttling.",
    )
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument(
        "--max-hours",
        type=float,
        default=4.0,
        help="hard ceiling on fetching, index walk included (default: 4)",
    )
    ap.add_argument(
        "--status",
        type=Path,
        action="append",
        default=None,
        help="status file to regenerate every five minutes; repeatable (.md or .json)",
    )
    ap.add_argument("--rebuild-queue", action="store_true", help="re-walk the index")
    ap.add_argument(
        "--build-only", action="store_true", help="materialise the queue, fetch nothing"
    )
    ap.add_argument(
        "--report-only",
        action="store_true",
        help="regenerate the status files from the mirror on disk and exit; fetches nothing",
    )
    ap.add_argument("--offline", action="store_true", help="fail rather than fetch")
    args = ap.parse_args(argv)

    deadline = time.time() + args.max_hours * 3600.0
    fetcher = Fetcher(args.cache, offline=args.offline, verbose=True)
    queue_path = Path(args.cache) / "crawl-queue.json"
    stop_file = Path(args.cache) / "STOP-CRAWL"
    status_paths = args.status or [Path("docs/crawl-status.md"), Path("out/crawl-status.json")]

    if queue_path.exists() and not args.rebuild_queue:
        queue = Queue.from_json(queue_path.read_text(encoding="utf-8"))
        print(f"[queue] resuming an existing queue of {len(queue.items):,} items", flush=True)
    else:
        queue = build_queue(fetcher, deadline=deadline)
        queue_path.write_text(queue.to_json(), encoding="utf-8")
        print(f"[queue] materialised {len(queue.items):,} items", flush=True)

    if args.build_only:
        return 0

    if args.report_only:
        # The mirror is the ledger, so a truthful status needs no running crawl:
        # walk the queue against the cache and report what is actually there.
        breakdown = tier_breakdown(fetcher, queue)
        done = sum(d for _tier, d, _n in breakdown)
        progress = Progress(started=time.time(), total=len(queue.items), done=done, cached=done)
        progress.stopped_because = "not running -- this is a report of the mirror on disk"
        # Fold in the figures only the run itself can know (requests made, wall
        # clock, observed rate) so the two halves cannot disagree.  Prefer the
        # end-of-run summary; fall back to the last five-minute JSON status,
        # which carries the same fields and exists even if the run was killed
        # before it could write a summary.
        candidates = [Path(args.cache) / "last-run.json"]
        candidates += [Path(p) for p in status_paths if Path(p).suffix == ".json"]
        for last in candidates:
            if not last.exists():
                continue
            try:
                previous = json.loads(last.read_text(encoding="utf-8"))
                progress.requests = previous.get("requests", 0)
                progress.started = time.time() - previous.get("elapsed_seconds", 0.0)
                progress.sections = previous.get("sections", 0)
                progress.soft_404 = previous.get("soft_404", 0)
                progress.errors = previous.get("errors", 0)
                progress.discovered_pas = previous.get("discovered_pas", 0)
                progress.floor_probed = previous.get("floor_probed", 0)
                progress.floor_moved = previous.get("floor_moved", [])
                progress.stopped_because = previous.get("stopped_because", progress.stopped_because)
                break  # first candidate that parses wins; last-run.json is preferred
            except (OSError, ValueError):
                continue
        _write_status(
            progress,
            queue,
            [Path(p) for p in status_paths],
            None,
            breakdown,
            probe_floor(fetcher),
        )
        print(f"[report] {done:,}/{len(queue.items):,} items mirrored", flush=True)
        return 0

    if stop_file.exists():
        print(f"[stop] {stop_file} exists; remove it to crawl", flush=True)
        return 0

    try:
        progress = run(
            fetcher,
            queue,
            deadline=deadline,
            status_paths=[Path(p) for p in status_paths],
            queue_path=queue_path,
            stop_file=stop_file,
        )
    except RateLimited as exc:
        print(f"\n!! {exc}\n!! The queue is intact. Do not restart without a human decision.")
        return 3

    print(
        f"\n[done] {progress.stopped_because}: {progress.done:,}/{progress.total:,} items, "
        f"{progress.requests:,} requests in {_fmt_duration(progress.elapsed)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

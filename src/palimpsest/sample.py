"""Enumerating ILCS sections without touching /search or /api.

robots.txt disallows both of those paths for all agents, which rules out the
obvious way to find things.  The permitted route is a three-level index walk:

    /Legislation/ILCS/Chapters              -> ChapterIDs
    /Legislation/ILCS/Acts?ChapterID=N      -> ActIDs + the '5 ILCS 70/' label
    /Legislation/ILCS/Articles?ActID=N      -> the full text of every section

The third level is the useful discovery, and it changes the crawl budget by an
order of magnitude: **the Articles page for an ILCS Act embeds the complete text
of every section in that Act**, each with its citation header and its
``(Source: ...)`` trailer, in the same markup as the single-section static route.
So one fetch yields a whole Act's worth of test cases *and* their source lines,
which means the sample can be stratified on "when was this last amended" for free
-- before spending a single fetch on a Public Act.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extract import extract
from .fetch import Fetcher, ilcs_acts_url, ilcs_articles_url
from .sections import SectionBlock, parse_blocks

CHAPTERS_URL = "https://www.ilga.gov/Legislation/ILCS/Chapters"

_CHAPTER_LINK_RE = re.compile(
    r'href="/Legislation/ILCS/Acts\?ChapterID=(?P<chapter_id>\d+)'
    r"&ChapterNumber=(?P<chapter_number>[0-9A-Za-z]+)"
    r'&Chapter=(?P<chapter_name>[^&"]*)'
)

_ACT_LINK_RE = re.compile(
    r'href="/Legislation/ILCS/Articles\?ActID=(?P<act_id>\d+)[^"]*"[^>]*>' r"(?P<label>.*?)</a>",
    re.S,
)


@dataclass(frozen=True)
class ChapterRef:
    chapter_id: str
    chapter_number: str
    name: str


@dataclass(frozen=True)
class ActRef:
    act_id: str
    chapter_id: str
    label: str
    """e.g. '5 ILCS 70/   Statute on Statutes.'"""

    @property
    def short(self) -> str:
        return " ".join(self.label.split())


def list_chapters(fetcher: Fetcher) -> list[ChapterRef]:
    body = fetcher.get(CHAPTERS_URL).body
    seen: dict[str, ChapterRef] = {}
    for m in _CHAPTER_LINK_RE.finditer(body):
        cid = m.group("chapter_id")
        if cid not in seen:
            seen[cid] = ChapterRef(
                chapter_id=cid,
                chapter_number=m.group("chapter_number"),
                name=m.group("chapter_name").strip(),
            )
    return list(seen.values())


def list_acts(fetcher: Fetcher, chapter_id: str | int) -> list[ActRef]:
    body = fetcher.get(ilcs_acts_url(chapter_id)).body
    acts: list[ActRef] = []
    seen: set[str] = set()
    for m in _ACT_LINK_RE.finditer(body):
        act_id = m.group("act_id")
        if act_id in seen:
            continue
        seen.add(act_id)
        label = re.sub(r"<[^>]+>", "", m.group("label"))
        label = label.replace("&nbsp;", " ").replace("\xa0", " ")
        acts.append(
            ActRef(act_id=act_id, chapter_id=str(chapter_id), label=" ".join(label.split()))
        )
    return acts


_FULLTEXT_HREF_RE = re.compile(
    r'href="(?P<href>/legislation/ILCS/details\?[^"]*ChapAct=FullText[^"]*)"', re.I
)


def _unescape_href(href: str) -> str:
    return href.replace("&amp;", "&").replace("&#x2B;", "+").replace(" ", "%20")


def sections_of_act(
    fetcher: Fetcher, act_id: str | int, chapter_id: str | int = 0
) -> list[SectionBlock]:
    """Every section of one ILCS Act, parsed.

    Small Acts embed their whole text in the Articles page, so one fetch is
    enough.  **Large Acts do not**: the Articles page for the Election Code or
    the Vehicle Code is an index of ``details?...SeqStart=...&SeqEnd=...``
    chunks, and parsing it yields zero sections.  A crawler that stopped there
    would silently see nothing in exactly the Acts with the most sections in
    them.

    So when the Articles page yields no sections, follow its own
    ``ChapAct=FullText`` link, which returns the entire Act in a single
    document -- 1,009 sections and about 4 MB for the Election Code.  One large
    fetch is also the politer choice than twenty chunk fetches under a 10-second
    crawl delay.
    """
    page = fetcher.get(ilcs_articles_url(act_id, chapter_id))
    if page.status != 200 or not page.body:
        return []
    blocks = [b for b in parse_blocks(extract(page.body).text) if not b.citation.is_heading]
    if blocks:
        return blocks

    m = _FULLTEXT_HREF_RE.search(page.body)
    if not m:
        return []
    url = "https://www.ilga.gov" + _unescape_href(m.group("href"))
    full = fetcher.get(url)
    if full.status != 200 or not full.body:
        return []
    return [b for b in parse_blocks(extract(full.body).text) if not b.citation.is_heading]


def ga_of(pa_number: str) -> int:
    """'103-274' -> 103."""
    try:
        return int(pa_number.split("-", 1)[0])
    except (ValueError, IndexError):
        return 0


def stratify(
    blocks: list[SectionBlock], *, recent_ga: int = 103, corpus_floor_ga: int = 90
) -> dict[str, list[SectionBlock]]:
    """Split an Act's sections into the strata the sample draws from.

    * ``recent``   -- last set by the 103rd GA or later (2023+)
    * ``modern``   -- last set by a Public Act from the 90th-102nd GA, i.e.
      inside the window where ilga.gov is expected to hold full Act text
    * ``pre_corpus`` -- last set by a Public Act older than the 90th GA. The
      spec (§2.9) expects these to be unavailable online; the sample draws a few
      deliberately so the corpus floor is *measured* rather than assumed.
    * ``no_public_act`` -- pre-Public-Act provenance (R.S. 1874, Laws 1945)
    """
    out: dict[str, list[SectionBlock]] = {
        "recent": [],
        "modern": [],
        "pre_corpus": [],
        "no_public_act": [],
    }
    for b in blocks:
        if b.source is None or not b.source.is_reconstructable:
            out["no_public_act"].append(b)
            continue
        ga = ga_of(b.source.terminal_pa or "")
        if ga >= recent_ga:
            out["recent"].append(b)
        elif ga >= corpus_floor_ga:
            out["modern"].append(b)
        else:
            out["pre_corpus"].append(b)
    return out


def take_evenly(items: list[SectionBlock], n: int) -> list[SectionBlock]:
    """Deterministic spread-out sample of ``n`` items.

    Evenly spaced rather than random so the sample is reproducible from the
    description alone, with no seed to record, and so it spans the whole Act
    rather than clustering at the front (where sections are short and
    definitional).
    """
    if n <= 0 or not items:
        return []
    if n >= len(items):
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]

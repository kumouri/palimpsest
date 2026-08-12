"""Parsers for the two things Oracle-0 needs to read.

Both of them turn out to be the *same* parser, which is the pleasant surprise of
spec §2.5: because an Illinois amendatory Act **reprints the whole section it
amends**, a section block looks identical whether it appears in the compiled
ILCS or inside a Public Act:

    (10 ILCS 5/28-1)  (from Ch. 46, par. 28-1)
    (Text of Section before amendment by P.A. 103-274)
    Sec. 28-1. The initiation and submission of all public questions ...
    (Source: P.A. 100-107, eff. 1-1-18.)

So one block parser serves both sides, and "locate the restated section inside
the Act" reduces to "find the block whose ILCS citation matches".

**The one asymmetry, and it is load-bearing:** the Source trailer printed inside
a Public Act is the section's *pre*-amendment source -- the Act shows what the
section's provenance was when the bill was drafted, not what it will be once the
Act itself is codified.  P.A. 103-0565 reprints 10 ILCS 5/28-1 under
``(Source: P.A. 100-107, eff. 1-1-18.)``, while the compiled section now reads
``(Source: P.A. 103-565, ...)``.  The trailer is therefore guaranteed to differ
and is excluded from the compared text (see ``normalize.RULES``, rule S1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- the ILCS citation header ------------------------------------------------
#
# '(10 ILCS 5/28-1)', '(5 ILCS 70/4)', '(215 ILCS 5/143.13a)',
# '(720 ILCS 5/Art. 11 heading)'.  Newlines are permitted inside because the
# printer layout can wrap a long header across two printed lines.
HEADER_RE = re.compile(
    r"\(\s*(?P<chapter>\d+)\s+ILCS\s+(?P<act>[0-9A-Za-z.\-]+)\s*/\s*(?P<section>[^)]*?)\s*\)",
    re.S,
)

# '(from Ch. 46, par. 28-1)' -- the pre-1993 Illinois Revised Statutes cross-ref.
LEGACY_RE = re.compile(r"\(\s*from\s+Ch\.\s*(?P<legacy>[^)]+?)\s*\)", re.S | re.I)

# '(Text of Section before amendment by P.A. 103-274)' -- ILGA's own published
# conflict marker (spec §2.3).
VERSION_MARKER_RE = re.compile(r"\(\s*Text of (?:Section|Sec\.)[^)]*?\)", re.S | re.I)

# '(Source: P.A. 102-839, eff. 5-13-22; 103-274, eff. 1-1-24.)'
SOURCE_RE = re.compile(r"\(\s*Source:\s*(?P<body>[^)]*?)\s*\)", re.S | re.I)

# The catchline that opens the operative text: 'Sec. 28-1.'
CATCHLINE_RE = re.compile(r"\bSec\.\s*(?P<num>[0-9A-Za-z.\-]+)\s*\.", re.S)

# A Public Act number as it appears in a Source line: '102-839', '103-0565'.
PA_IN_SOURCE_RE = re.compile(r"\bP\.?\s?A\.?\s*(?P<num>\d{2,3}-\d{1,4})", re.I)
# Continuation entries in a multi-Act source line omit the 'P.A.' prefix:
# '(Source: P.A. 102-839, eff. 5-13-22; 102-935, eff. 7-1-22.)'
BARE_PA_RE = re.compile(r"(?<![\w.\-])(?P<num>\d{2,3}-\d{1,4})(?![\w\-])")

# Provenance that predates machine-readable Public Acts.  A section whose source
# is one of these is UNRECONSTRUCTABLE and is excluded from the denominator.
NON_PA_PROVENANCE_RE = re.compile(
    r"\b(R\.S\.|Laws\s+\d{4}|Rev\.\s*Stat\.|P\.\s*A\.\s*77-2500|Code\s+\d{4})", re.I
)


def normalise_pa_number(num: str) -> str:
    """'97-81' -> '097-0081', the shape the Public Act URL routes want.

    **Both halves are zero-padded**: the General Assembly number to three digits
    and the serial to four.  This is not cosmetic.  ``PrinterFriendly/97-0081``
    returns HTTP 200 with ilga.gov's "not currently available" placeholder,
    while ``PrinterFriendly/097-0081`` returns the Act -- so an unpadded GA
    number makes every Public Act before the 100th General Assembly look as
    though it had been withdrawn from the site.  ``103-0565`` already has three
    digits and survives unchanged.
    """
    ga, _, serial = num.partition("-")
    return f"{int(ga):03d}-{int(serial):04d}"


@dataclass(frozen=True)
class Citation:
    chapter: str
    act: str
    section: str

    def __str__(self) -> str:
        return f"{self.chapter} ILCS {self.act}/{self.section}"

    @property
    def is_heading(self) -> bool:
        """Article/part headings are structural, not sections of text."""
        return "heading" in self.section.lower()

    @property
    def doc_name(self) -> str | None:
        """ILGA's DocName key: 4-digit chapter + 5-digit act field + 'K' + section.

        The act field is **not** the act number zero-padded -- it is the act
        number carried to one decimal place, i.e. multiplied by ten.  The spec's
        own worked examples show it::

            5 ILCS 70/4        -> 0005 00700 K 4         (70  -> 00700)
            720 ILCS 5/11-501  -> 0720 00050 K 11-501    (5   -> 00050)
            25 ILCS 135/5.04   -> 0025 01350 K 5.04      (135 -> 01350)

        Returns ``None`` where the act number is not numeric and the key shape
        is therefore not derivable.
        """
        try:
            act_field = round(float(self.act) * 10)
        except ValueError:
            return None
        return f"{int(self.chapter):04d}{act_field:05d}K{self.section}"


@dataclass
class SourceLine:
    """A parsed ``(Source: ...)`` trailer -- the spec's 'git log with no git show'."""

    raw: str
    pa_numbers: list[str] = field(default_factory=list)
    has_non_pa_provenance: bool = False

    @property
    def terminal_pa(self) -> str | None:
        """The last Public Act listed: the one that last set this text."""
        return self.pa_numbers[-1] if self.pa_numbers else None

    @property
    def is_reconstructable(self) -> bool:
        return bool(self.pa_numbers)

    @property
    def multi_act(self) -> bool:
        return len(self.pa_numbers) > 1


def parse_source_line(raw: str) -> SourceLine:
    """Parse the body of a ``(Source: ...)`` trailer.

    Handles the multi-Act form, where only the first entry carries the ``P.A.``
    prefix and the rest are bare numbers separated by semicolons, and the
    pre-Public-Act forms (``R.S. 1874, p. 1011``, ``Laws 1945, p. 1717``).
    """
    body = " ".join(raw.split())
    non_pa = bool(NON_PA_PROVENANCE_RE.search(body))
    numbers: list[str] = []
    if PA_IN_SOURCE_RE.search(body):
        # Once we know the line is Public-Act shaped, every '<ga>-<serial>' token
        # in it is an Act.  Effective dates ('eff. 5-13-22') do not match because
        # BARE_PA_RE requires the token to be bounded and dates have three parts.
        for m in BARE_PA_RE.finditer(body):
            num = m.group("num")
            if num not in numbers:
                numbers.append(num)
    return SourceLine(raw=body, pa_numbers=numbers, has_non_pa_provenance=non_pa)


@dataclass
class SectionBlock:
    """One reprinted section, from either the compilation or a Public Act."""

    citation: Citation
    raw: str
    """The whole block as extracted, header through Source trailer."""
    body: str
    """Operative text only: from the ``Sec. N.`` catchline up to ``(Source:``."""
    legacy_cite: str | None = None
    version_marker: str | None = None
    source: SourceLine | None = None
    catchline: str | None = None

    @property
    def has_version_marker(self) -> bool:
        return self.version_marker is not None


def _make_block(citation: Citation, segment: str, src_match: re.Match | None) -> SectionBlock:
    legacy = LEGACY_RE.search(segment)
    marker = VERSION_MARKER_RE.search(segment)
    catch = CATCHLINE_RE.search(segment)

    body_end = src_match.start() if src_match else len(segment)
    if catch:
        body_start = catch.start()
    else:
        # No catchline (article headings, repealed stubs): the body starts after
        # whatever metadata parentheticals opened the segment.
        body_start = max(
            (m.end() for m in (legacy, marker) if m and m.end() <= body_end),
            default=0,
        )
    return SectionBlock(
        citation=citation,
        raw=segment[: src_match.end()] if src_match else segment,
        body=segment[body_start:body_end],
        legacy_cite=legacy.group("legacy").strip() if legacy else None,
        version_marker=" ".join(marker.group(0).split()) if marker else None,
        source=parse_source_line(src_match.group("body")) if src_match else None,
        catchline=catch.group("num") if catch else None,
    )


def parse_blocks(text: str) -> list[SectionBlock]:
    """Split extracted page text into section blocks.

    A block starts at an ILCS citation header and ends at the ``(Source:)``
    trailer that follows it.  Ending at the trailer is what keeps a Public Act's
    *next* amendatory instruction -- "Section 20. The Counties Code is amended by
    ..." -- out of the previous section's body.

    **Multiple versions of one section do not repeat the header.**  Where ILGA
    publishes both a before- and an after-amendment text (spec §2.3), the second
    version follows the first version's Source trailer with only a
    ``(Text of Section after amendment by P.A. X)`` marker to introduce it -- no
    second ``(405 ILCS 20/3a)`` header.  So one header window can hold several
    versions, and they are split on the Source trailers within it.  Missing this
    silently drops every second version in the corpus, and the dropped ones are
    exactly the multi-version cases the oracle most needs to see.
    """
    headers = list(HEADER_RE.finditer(text))
    blocks: list[SectionBlock] = []
    for i, m in enumerate(headers):
        hard_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        window = text[m.start() : hard_end]

        citation = Citation(
            chapter=m.group("chapter").strip(),
            act=m.group("act").strip(),
            section=" ".join(m.group("section").split()),
        )
        if not citation.section:
            # An act-level header such as '(5 ILCS 70/)', which introduces the
            # Act rather than a section.
            continue

        sources = list(SOURCE_RE.finditer(window))
        if not sources:
            blocks.append(_make_block(citation, window, None))
            continue
        cursor = 0
        for src in sources:
            segment = window[cursor : src.end()]
            local = SOURCE_RE.search(segment)
            blocks.append(_make_block(citation, segment, local))
            cursor = src.end()
    return blocks


def find_blocks_for(blocks: list[SectionBlock], citation: Citation) -> list[SectionBlock]:
    """All blocks in a document matching one ILCS citation.

    More than one is not an error: it is the multi-version case of spec §2.3,
    where the Act prints both the before- and after-amendment texts.
    """
    return [
        b
        for b in blocks
        if b.citation.chapter == citation.chapter
        and b.citation.act == citation.act
        and b.citation.section == citation.section
    ]

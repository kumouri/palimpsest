"""HTML -> text, with the amendatory markup resolved.

This is the step the spec (§2.5, Appendix A) flags as the largest schedule risk
in Phase 0: *does the Public Act HTML actually carry strike-through and
underscore, or does it flatten them?*

**Answered, 2026-08-11: it carries them, as real tags.** A printer-friendly
Public Act page uses literal ``<strike>`` and ``<u>`` elements wrapping ``<code>``
runs.  P.A. 103-0565 contains 10 ``<strike>`` and 37 ``<u>`` elements.  The HTML
route is therefore viable and the PDF pipeline is not needed.

Two structural facts about the Act HTML drive the design here:

1. The page is a fixed-width printer layout.  **Every printed line is its own
   ``<tr><td>``**, hard-wrapped at roughly 60 characters, and a paragraph's
   leading indent is four ``&nbsp;`` entities.  So ``</tr>`` is a line boundary.
2. **A ``<strike>`` or ``<u>`` span may begin on one printed line and end on the
   next**, because the wrapper is applied to the rendered text, not to the
   logical phrase.  Any regex-per-line approach breaks on this; a real parser
   does not.

The compiled ILCS pages use a different, older layout (``<code><font>`` blocks
with literal newlines and ``<br>``), which is why extraction emits a line-based
text form that the normaliser then reflows.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

# Tags whose textual content is a *deletion* in an enrolled amendatory Act.
# Struck text is what the Act removes, so it must not survive into the
# post-amendment section.
STRIKE_TAGS = frozenset({"strike", "s", "del"})

# Tags whose textual content is an *insertion*.  Underscored text is new law and
# is kept.  (Nothing is done to it beyond keeping it -- the point of recording
# the tag set is that we know we saw it and did not silently drop it.)
INSERT_TAGS = frozenset({"u", "ins"})

# Tags that end a line in either layout.  Every block-level element belongs
# here, and leaving one out is a silent corruption rather than a visible error:
# ``<center>`` was initially missing, and because the compiled ILCS page wraps
# indented block quotes in it, the text either side of the quote ran together
# with no separator at all -- "...the following verification:"VERIFICATION:" --
# which then showed up as a one-space "divergence" from the Public Act.  The fix
# belongs in the extractor, not in a looser normalisation rule.
LINE_BREAK_TAGS = frozenset(
    {
        "br",
        "tr",
        "td",
        "p",
        "div",
        "table",
        "center",
        "blockquote",
        "li",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
    }
)

# Tags whose content is never document text.
SKIP_TAGS = frozenset({"style", "script", "title", "head"})

DELETION_MARK = "\x00"
"""Internal sentinel marking where struck-through text was removed.

Never appears in returned text: :func:`_close_deletions` consumes every one.
"""

# A run of deletion marks together with whatever whitespace surrounds them.
_DELETION_RUN_RE = re.compile(r"[ \t\r\n]*(?:\x00[ \t\r\n]*)+")

# Punctuation that closes a clause. If a deletion sits immediately before one of
# these, the space that joined the deleted phrase to its neighbours goes with it.
_CLOSING_PUNCT = ",;:.)]}!?"


def _close_deletions(text: str) -> str:
    """Resolve the whitespace left behind where struck-through text was removed.

    An enrolled Illinois Act marks a deletion around the *phrase*, and the space
    that separated that phrase from what follows is inside the deletion or beside
    it.  So removing::

        the effective date <u>of ... 103rd</u> <strike>of ... 102nd</strike>, the

    leaves ``...103rd , the`` -- with a space before the comma that the compiled
    text does not have.

    The obvious fix is a global "strip whitespace before punctuation" rule, and
    it works.  It is also the wrong fix, and measurably so: run as a blanket
    normalisation rule over both texts it accounted for **18 of 83 matches**, a
    fifth of the headline number resting on a transformation applied everywhere
    rather than where the deletion actually happened.  A rule that large has to
    earn its place at the site it belongs to.

    Doing it here instead means the repair is applied **only where text was
    removed**, on one side only, and can therefore never manufacture agreement
    between two texts that merely happen to be punctuated differently.
    """

    def repair(m: re.Match) -> str:
        following = text[m.end() : m.end() + 1]
        if following and following in _CLOSING_PUNCT:
            return ""
        return " " if any(c.isspace() for c in m.group(0)) else ""

    return _DELETION_RUN_RE.sub(repair, text)


class _TextExtractor(HTMLParser):
    def __init__(self, *, drop_strike: bool, drop_insert: bool) -> None:
        super().__init__(convert_charrefs=False)
        self.drop_strike = drop_strike
        self.drop_insert = drop_insert
        self.out: list[str] = []
        self._strike_depth = 0
        self._insert_depth = 0
        self._skip_depth = 0
        self.strike_spans = 0
        self.insert_spans = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in STRIKE_TAGS:
            self._strike_depth += 1
            self.strike_spans += 1
        elif tag in INSERT_TAGS:
            self._insert_depth += 1
            self.insert_spans += 1
        if tag in LINE_BREAK_TAGS:
            self.out.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() in LINE_BREAK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in STRIKE_TAGS:
            self._strike_depth = max(0, self._strike_depth - 1)
            if self.drop_strike and not self._strike_depth:
                # Mark where text was removed, so the whitespace the deletion
                # took with it can be resolved at exactly this site and nowhere
                # else. See _close_deletions.
                self.out.append(DELETION_MARK)
        elif tag in INSERT_TAGS:
            self._insert_depth = max(0, self._insert_depth - 1)
            if self.drop_insert and not self._insert_depth:
                self.out.append(DELETION_MARK)
        if tag in LINE_BREAK_TAGS:
            self.out.append("\n")

    def _emit(self, text: str) -> None:
        if self._skip_depth:
            return
        if self._strike_depth and self.drop_strike:
            return
        if self._insert_depth and self.drop_insert:
            return
        self.out.append(text)

    def handle_data(self, data: str) -> None:
        self._emit(data)

    def handle_entityref(self, name: str) -> None:
        self._emit(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self._emit(html.unescape(f"&#{name};"))


class Extraction:
    """The text of a document plus what the extractor saw while producing it."""

    __slots__ = ("text", "strike_spans", "insert_spans")

    def __init__(self, text: str, strike_spans: int, insert_spans: int) -> None:
        self.text = text
        self.strike_spans = strike_spans
        self.insert_spans = insert_spans

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Extraction(len={len(self.text)}, strike={self.strike_spans}, "
            f"insert={self.insert_spans})"
        )


def extract(html_text: str, *, drop_strike: bool = True, drop_insert: bool = False) -> Extraction:
    """Turn an ilga.gov page into line-oriented text.

    The two useful settings:

    * ``drop_strike=True, drop_insert=False`` (the default, and what Oracle-0
      uses) -- remove struck-through text, keep underscored text.  This *is* the
      "apply the amendment" step for Illinois' whole-section-restatement format.
    * ``drop_strike=False, drop_insert=True`` -- keep struck text, drop
      underscored text, recovering the section as it read **before** this Act.
      That is the base text of spec §5.2, whose hash is what lets you tell
      whether two Acts were drafted from the same predecessor.
    """
    parser = _TextExtractor(drop_strike=drop_strike, drop_insert=drop_insert)
    parser.feed(html_text)
    parser.close()
    raw = "".join(parser.out)
    # Non-breaking spaces are layout, not content.  The four-nbsp run that marks
    # a paragraph indent is the single most common one.
    raw = raw.replace("\xa0", " ")
    raw = _close_deletions(raw)
    # Collapse the many empty lines the table layout produces, but keep single
    # line boundaries -- the normaliser decides what to do with them.
    lines = [line.rstrip() for line in raw.split("\n")]
    return Extraction(
        text="\n".join(line for line in lines if line.strip()),
        strike_spans=parser.strike_spans,
        insert_spans=parser.insert_spans,
    )


_LINE_NUMBER_ONLY = re.compile(r"^\s*\d{1,3}\s*$")


def drop_line_numbers(text: str) -> str:
    """Remove printer line-number artifacts (lines consisting only of digits).

    The printer-friendly Public Act view emits ``<td class="lineNum">`` cells
    which are empty in the pages observed, but the legacy ``legisnet`` bill views
    do carry rendered line numbers.  Dropping a line that is nothing but a small
    integer is safe: no line of statutory text is a bare number.
    """
    return "\n".join(line for line in text.split("\n") if not _LINE_NUMBER_ONLY.match(line))

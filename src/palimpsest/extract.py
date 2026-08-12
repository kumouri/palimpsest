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


class _TextExtractor(HTMLParser):
    def __init__(self, *, drop_strike: bool) -> None:
        super().__init__(convert_charrefs=False)
        self.drop_strike = drop_strike
        self.out: list[str] = []
        self._strike_depth = 0
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
        if tag in LINE_BREAK_TAGS:
            self.out.append("\n")

    def _emit(self, text: str) -> None:
        if self._skip_depth:
            return
        if self._strike_depth and self.drop_strike:
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


def extract(html_text: str, *, drop_strike: bool = True) -> Extraction:
    """Turn an ilga.gov page into line-oriented text.

    ``drop_strike=True`` (the default, and what Oracle-0 uses) removes
    struck-through text and keeps underscored text, which is exactly the
    "apply the amendment" step for Illinois' whole-section-restatement format.
    Pass ``drop_strike=False`` to recover the *pre*-amendment reading, which is
    useful for the base-text hash described in spec §5.2.
    """
    parser = _TextExtractor(drop_strike=drop_strike)
    parser.feed(html_text)
    parser.close()
    raw = "".join(parser.out)
    # Non-breaking spaces are layout, not content.  The four-nbsp run that marks
    # a paragraph indent is the single most common one.
    raw = raw.replace("\xa0", " ")
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

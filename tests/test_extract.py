"""Tests for HTML -> text extraction.

The fixtures are hand-written miniatures of the real markup shapes observed on
ilga.gov on 2026-08-11, not copies of statutory text.
"""

from __future__ import annotations

import unittest

from palimpsest.extract import drop_line_numbers, extract


class TestStrikeAndUnderscore(unittest.TestCase):
    def test_struck_text_is_removed_and_underscored_text_is_kept(self):
        html = (
            "<td><code>the effective date </code>"
            "<u><code>of this amendatory Act of the 103rd</code></u>"
            "<code> </code>"
            "<strike><code>of this amendatory Act of the 102nd</code></strike>"
            "<code>, the provisions</code></td>"
        )
        out = extract(html)
        self.assertIn("103rd", out.text)
        self.assertNotIn("102nd", out.text)
        self.assertEqual(out.strike_spans, 1)
        self.assertEqual(out.insert_spans, 1)

    def test_strike_span_crossing_a_printed_line_boundary(self):
        # The real failure mode: the wrapper opens on one <tr> and closes on the
        # next, so anything that works line-by-line keeps half the deletion.
        html = (
            "<tr><td><code>text </code><strike><code>delete this </code></strike></td></tr>"
            "<tr><td><strike><code>and this too</code></strike><code> kept</code></td></tr>"
        )
        out = extract(html)
        self.assertNotIn("delete this", out.text)
        self.assertNotIn("and this too", out.text)
        self.assertIn("text", out.text)
        self.assertIn("kept", out.text)

    def test_drop_strike_false_recovers_the_pre_amendment_reading(self):
        html = "<code>a </code><strike><code>old</code></strike><u><code>new</code></u>"
        self.assertIn("old", extract(html, drop_strike=False).text)
        self.assertNotIn("old", extract(html, drop_strike=True).text)

    def test_s_and_del_are_treated_as_deletions(self):
        for tag in ("s", "del"):
            with self.subTest(tag=tag):
                out = extract(f"<p>keep <{tag}>drop</{tag}></p>")
                self.assertNotIn("drop", out.text)
                self.assertIn("keep", out.text)


class TestBlockElements(unittest.TestCase):
    def test_center_is_a_line_boundary(self):
        # Regression: <center> wraps indented block quotes on the compiled ILCS
        # page.  Without it in LINE_BREAK_TAGS the text either side ran together
        # with no separator, which read as a one-space divergence from the Act.
        html = (
            "<code>the following verification:</code>"
            '<center><code>"VERIFICATION: </code></center>'
            "<code>I declare that</code>"
        )
        text = extract(html).text
        self.assertNotIn('verification:"VERIFICATION', text)
        self.assertIn("verification:", text)
        self.assertIn('"VERIFICATION:', text)

    def test_br_and_tr_break_lines(self):
        out = extract("<tr><td>one</td></tr><tr><td>two</td></tr>")
        self.assertEqual(out.text.split("\n"), ["one", "two"])


class TestEntitiesAndWhitespace(unittest.TestCase):
    def test_nbsp_becomes_an_ordinary_space(self):
        out = extract("<code>&nbsp;&nbsp;&nbsp;&nbsp;</code><code>Sec. 4.</code>")
        self.assertNotIn("\xa0", out.text)
        self.assertIn("Sec. 4.", out.text)

    def test_entities_are_decoded(self):
        out = extract("<p>Smith &amp; Wesson &quot;quoted&quot; &#39;x&#39;</p>")
        self.assertIn("Smith & Wesson", out.text)
        self.assertIn('"quoted"', out.text)

    def test_style_and_script_content_is_dropped(self):
        out = extract("<style>td.xsl { font-size: 10pt; }</style><p>real text</p>")
        self.assertNotIn("font-size", out.text)
        self.assertIn("real text", out.text)

    def test_blank_lines_are_dropped(self):
        out = extract("<p>a</p><p></p><p>   </p><p>b</p>")
        self.assertEqual(out.text.split("\n"), ["a", "b"])


class TestDropLineNumbers(unittest.TestCase):
    def test_bare_numbers_are_removed_but_text_lines_survive(self):
        text = "1\nSec. 4. No new law\n2\nshall be construed"
        out = drop_line_numbers(text)
        self.assertEqual(out.split("\n"), ["Sec. 4. No new law", "shall be construed"])

    def test_four_digit_numbers_are_kept(self):
        # Printed line numbers on a legislative page do not reach four digits,
        # but paragraph numbers ('par. 1103') and years do. Keeping them is the
        # conservative choice: dropping content is worse than keeping noise.
        self.assertEqual(drop_line_numbers("1103"), "1103")

    def test_a_line_with_a_number_and_words_is_kept(self):
        self.assertEqual(drop_line_numbers("28-1 is amended"), "28-1 is amended")


if __name__ == "__main__":
    unittest.main()

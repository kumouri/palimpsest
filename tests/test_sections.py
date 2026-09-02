"""Tests for the source-line parser and the section-block parser."""

from __future__ import annotations

import unittest

from palimpsest.sections import (
    Citation,
    find_blocks_for,
    normalise_pa_number,
    parse_blocks,
    parse_source_line,
)


class TestSourceLine(unittest.TestCase):
    def test_single_act(self):
        s = parse_source_line("P.A. 102-839, eff. 5-13-22.")
        self.assertEqual(s.pa_numbers, ["102-839"])
        self.assertEqual(s.terminal_pa, "102-839")
        self.assertTrue(s.is_reconstructable)
        self.assertFalse(s.multi_act)

    def test_multi_act_line_where_only_the_first_carries_the_prefix(self):
        s = parse_source_line(
            "P.A. 102-839, eff. 5-13-22; 102-935, eff. 7-1-22; "
            "103-154, eff. 6-30-23; 103-274, eff. 1-1-24."
        )
        self.assertEqual(s.pa_numbers, ["102-839", "102-935", "103-154", "103-274"])
        self.assertEqual(s.terminal_pa, "103-274")
        self.assertTrue(s.multi_act)

    def test_effective_dates_are_not_mistaken_for_act_numbers(self):
        s = parse_source_line("P.A. 100-107, eff. 1-1-18.")
        self.assertEqual(s.pa_numbers, ["100-107"])

    def test_pre_public_act_provenance_is_not_reconstructable(self):
        for raw in ("R.S. 1874, p. 1011.", "Laws 1945, p. 1717."):
            with self.subTest(raw=raw):
                s = parse_source_line(raw)
                self.assertEqual(s.pa_numbers, [])
                self.assertFalse(s.is_reconstructable)
                self.assertIsNone(s.terminal_pa)
                self.assertTrue(s.has_non_pa_provenance)

    def test_wrapped_source_line_is_joined(self):
        s = parse_source_line("P.A. 102-839, eff. 5-13-22;\n103-154, eff.\n6-30-23.")
        self.assertEqual(s.pa_numbers, ["102-839", "103-154"])


class TestPaNumberPadding(unittest.TestCase):
    def test_both_halves_are_padded(self):
        # PrinterFriendly/97-0081 returns a "not currently available" placeholder
        # with HTTP 200; PrinterFriendly/097-0081 returns the Act.
        self.assertEqual(normalise_pa_number("97-81"), "097-0081")
        self.assertEqual(normalise_pa_number("86-451"), "086-0451")

    def test_three_digit_ga_is_unchanged(self):
        self.assertEqual(normalise_pa_number("103-565"), "103-0565")
        self.assertEqual(normalise_pa_number("103-0565"), "103-0565")


ONE_SECTION = """
    (5 ILCS 70/4) (from Ch. 1, par. 1103)
    Sec. 4. No new law shall be construed to repeal a former law, whether
such former law is expressly repealed or not.
(Source: R.S. 1874, p. 1011.)
"""

TWO_VERSIONS = """
    (405 ILCS 20/3a) (from Ch. 91 1/2, par. 303a)
    (Text of Section before amendment by P.A. 103-274)
    Sec. 3a. Every governmental unit shall do the first thing.
(Source: P.A. 95-336, eff. 8-21-07.)
    (Text of Section after amendment by P.A. 103-274)
    Sec. 3a. Every governmental unit shall do the second thing.
(Source: P.A. 103-274, eff. 1-1-24.)
    (405 ILCS 20/5) (from Ch. 91 1/2, par. 305)
    Sec. 5. Something else entirely.
(Source: P.A. 102-839, eff. 5-13-22.)
"""

ACT_WITH_INSTRUCTION = """
    Section 5. The Election Code is amended by changing Section 28-1 as follows:
    (10 ILCS 5/28-1) (from Ch. 46, par. 28-1)
    Sec. 28-1. The initiation and submission of all public questions.
(Source: P.A. 100-107, eff. 1-1-18.)
    Section 20. The Counties Code is amended by changing Section 5-25025 as follows:
    (55 ILCS 5/5-25025)
    Sec. 5-25025. County boards may do a thing.
(Source: P.A. 102-839, eff. 5-13-22.)
"""


class TestParseBlocks(unittest.TestCase):
    def test_single_section(self):
        (block,) = parse_blocks(ONE_SECTION)
        self.assertEqual(str(block.citation), "5 ILCS 70/4")
        self.assertEqual(block.legacy_cite, "1, par. 1103")
        self.assertEqual(block.catchline, "4")
        self.assertTrue(block.body.startswith("Sec. 4."))
        self.assertNotIn("(Source:", block.body)
        self.assertIsNotNone(block.source)
        self.assertFalse(block.source.is_reconstructable)

    def test_two_versions_under_one_header(self):
        # The regression that matters: the second version is introduced only by
        # its '(Text of Section after amendment ...)' marker, with no repeated
        # ILCS header.  Splitting on headers alone loses it silently.
        blocks = parse_blocks(TWO_VERSIONS)
        self.assertEqual(len(blocks), 3)
        a, b, c = blocks
        self.assertEqual(str(a.citation), "405 ILCS 20/3a")
        self.assertEqual(str(b.citation), "405 ILCS 20/3a")
        self.assertEqual(str(c.citation), "405 ILCS 20/5")
        self.assertIn("before amendment", a.version_marker)
        self.assertIn("after amendment", b.version_marker)
        self.assertIn("first thing", a.body)
        self.assertIn("second thing", b.body)
        self.assertNotIn("second thing", a.body)
        self.assertEqual(a.source.terminal_pa, "95-336")
        self.assertEqual(b.source.terminal_pa, "103-274")

    def test_amendatory_instruction_is_not_part_of_the_section_body(self):
        blocks = parse_blocks(ACT_WITH_INSTRUCTION)
        self.assertEqual(len(blocks), 2)
        first = blocks[0]
        self.assertNotIn("Counties Code is amended", first.body)
        self.assertNotIn("Section 20.", first.body)
        self.assertTrue(first.body.strip().startswith("Sec. 28-1."))

    def test_act_level_header_without_a_section_is_skipped(self):
        self.assertEqual(parse_blocks("(5 ILCS 70/)\nSome preamble.\n"), [])

    def test_headings_are_identified(self):
        blocks = parse_blocks("(720 ILCS 5/Art. 11 heading)\nARTICLE 11.\n")
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].citation.is_heading)

    def test_find_blocks_for(self):
        blocks = parse_blocks(TWO_VERSIONS)
        found = find_blocks_for(blocks, Citation("405", "20", "3a"))
        self.assertEqual(len(found), 2)
        self.assertEqual(find_blocks_for(blocks, Citation("5", "70", "4")), [])


class TestCitation(unittest.TestCase):
    def test_doc_name(self):
        # The three worked examples from spec §2.1. Note the act field is the
        # act number times ten, not the act number zero-padded.
        self.assertEqual(Citation("5", "70", "4").doc_name, "000500700K4")
        self.assertEqual(Citation("720", "5", "11-501").doc_name, "072000050K11-501")
        self.assertEqual(Citation("25", "135", "5.04").doc_name, "002501350K5.04")

    def test_doc_name_is_none_for_non_numeric_acts(self):
        self.assertIsNone(Citation("5", "70a", "4").doc_name)


if __name__ == "__main__":
    unittest.main()

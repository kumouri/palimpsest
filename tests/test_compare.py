"""Tests for the comparator and for the mismatch classifier."""

from __future__ import annotations

import unittest

from palimpsest.compare import compare, segment, unified, word_changes
from palimpsest.normalize import normalize
from palimpsest.oracle0 import (
    CLASS_DIVERGENCE,
    CLASS_MATCH,
    CLASS_MULTI_ACT,
    CLASS_MULTI_VERSION,
    CLASS_NORMALIZE,
    CLASS_REPEALED_STUB,
    CLASS_TARGET_RESOLUTION,
    Case,
    classify,
    is_repeal_stub,
    reduce_to_alnum,
)


class TestCompare(unittest.TestCase):
    def test_identical_text_matches_both_ways(self):
        c = compare("Sec. 4. The text.", "Sec. 4. The text.", label="x")
        self.assertTrue(c.exact_match)
        self.assertTrue(c.normalized_match)
        self.assertEqual(c.similarity, 1.0)
        self.assertEqual(c.diff, "")

    def test_wrapping_difference_matches_normalised_but_not_exactly(self):
        c = compare("Sec. 4. The\ntext here.", "Sec. 4. The text\nhere.", label="x")
        self.assertFalse(c.exact_match)
        self.assertTrue(c.normalized_match)

    def test_a_real_word_difference_does_not_match(self):
        c = compare("the board shall act", "the board must act", label="x")
        self.assertFalse(c.normalized_match)
        self.assertIn("shall", c.diff)
        self.assertIn("must", c.diff)
        self.assertLess(c.similarity, 1.0)

    def test_diff_is_unified_format_with_both_labels(self):
        c = compare("A thing. B thing.", "A thing. C thing.", label="10 ILCS 5/28-1")
        self.assertTrue(c.diff.startswith("---"))
        self.assertIn("ILCS compilation", c.diff)
        self.assertIn("source Public Act", c.diff)
        self.assertIn("+++", c.diff)


class TestWordChanges(unittest.TestCase):
    def test_replacement_is_described(self):
        changes = word_changes("the board shall act", "the board must act")
        self.assertEqual(len(changes), 1)
        self.assertIn("shall", changes[0])
        self.assertIn("must", changes[0])

    def test_insertion_and_deletion_are_labelled_by_side(self):
        self.assertIn("only in Act", word_changes("a c", "a b c")[0])
        self.assertIn("only in compilation", word_changes("a b c", "a c")[0])

    def test_output_is_capped(self):
        a = " ".join(f"w{i}" for i in range(200))
        b = " ".join(f"x{i}" for i in range(200))
        self.assertLessEqual(len(word_changes(a, b, limit=5)), 6)


class TestSegment(unittest.TestCase):
    def test_it_does_not_split_a_section_citation(self):
        self.assertEqual(len(segment("Sec. 28-1. Text follows here.")), 1)

    def test_it_does_not_split_a_public_act_number(self):
        self.assertEqual(len(segment("As set by P.A. 102-839, eff. 5-13-22.")), 1)

    def test_it_splits_between_sentences(self):
        self.assertEqual(len(segment("First sentence. Second sentence.")), 2)

    def test_long_segments_are_wrapped(self):
        for line in segment("word " * 200):
            self.assertLessEqual(len(line), 120)

    def test_unified_of_equal_text_is_empty(self):
        self.assertEqual(unified("same text.", "same text.", label="x"), "")


class TestReduceToAlnum(unittest.TestCase):
    def test_punctuation_and_case_and_space_are_erased(self):
        self.assertEqual(
            reduce_to_alnum("Assembly , the provisions"),
            reduce_to_alnum("assembly, the provisions"),
        )

    def test_a_word_difference_survives(self):
        self.assertNotEqual(reduce_to_alnum("shall act"), reduce_to_alnum("must act"))


class TestRepealStub(unittest.TestCase):
    def test_repeal_tombstones_are_recognised(self):
        for body in (
            "Sec. 1-25. (Repealed).",
            "Sec. 11-501.9. (Repealed)",
            "  Sec. 5.04.  (Repealed).  ",
        ):
            with self.subTest(body=body):
                self.assertTrue(is_repeal_stub(body))

    def test_real_sections_are_not_repeal_stubs(self):
        self.assertFalse(is_repeal_stub("Sec. 4. No new law shall be construed"))
        self.assertFalse(is_repeal_stub("Sec. 9. The provision on repealed instruments is void."))


def _case(**kw) -> Case:
    base = {
        "citation": "10 ILCS 5/1-1",
        "act_label": "Election Code",
        "stratum": "recent",
        "source_line": "P.A. 103-467, eff. 8-4-23.",
        "terminal_pa": "103-467",
        "all_pas": ["103-467"],
        "candidates_in_act": 1,
    }
    base.update(kw)
    return Case(**base)


class TestClassify(unittest.TestCase):
    def test_a_match_is_a_match(self):
        c = _case(normalized_match=True)
        self.assertEqual(classify(c, "x", "x"), CLASS_MATCH)

    def test_missing_from_the_act_is_a_target_resolution_failure(self):
        c = _case(candidates_in_act=0)
        self.assertEqual(classify(c, "Sec. 1. Text", ""), CLASS_TARGET_RESOLUTION)

    def test_a_repeal_stub_is_classified_before_target_resolution(self):
        c = _case(candidates_in_act=0)
        self.assertEqual(classify(c, "Sec. 1-25. (Repealed).", ""), CLASS_REPEALED_STUB)

    def test_a_punctuation_only_difference_is_a_normalisation_artefact(self):
        c = _case()
        self.assertEqual(
            classify(c, "Assembly, the provisions", "Assembly , the  provisions"),
            CLASS_NORMALIZE,
        )

    def test_multiple_reprints_in_the_act_is_the_multi_version_case(self):
        c = _case(candidates_in_act=2)
        self.assertEqual(classify(c, "alpha text", "beta text"), CLASS_MULTI_VERSION)

    def test_a_published_version_marker_is_the_multi_version_case(self):
        c = _case(published_version_marker="(Text of Section after amendment by P.A. 103-274)")
        self.assertEqual(classify(c, "alpha text", "beta text"), CLASS_MULTI_VERSION)

    def test_several_acts_in_the_source_line_outrank_a_divergence_claim(self):
        c = _case(all_pas=["103-154", "103-467"])
        self.assertEqual(classify(c, "alpha text", "beta text"), CLASS_MULTI_ACT)

    def test_a_single_act_single_version_mismatch_is_a_candidate_divergence(self):
        c = _case()
        self.assertEqual(classify(c, "alpha text", "beta text"), CLASS_DIVERGENCE)

    def test_divergence_requires_a_genuine_word_difference(self):
        # A case classified DIVERGENCE must not be explainable by punctuation --
        # that is what keeps the finding bar high.
        c = _case()
        published, replayed = "the officer shall act", "the officer must act"
        self.assertEqual(classify(c, published, replayed), CLASS_DIVERGENCE)
        self.assertNotEqual(reduce_to_alnum(published), reduce_to_alnum(replayed))


class TestEndToEndOnMiniatureDocuments(unittest.TestCase):
    """The whole Oracle-0 comparison, on the real markup shapes."""

    def test_an_act_reprint_matches_the_compilation_after_applying_the_markup(self):
        from palimpsest.extract import extract
        from palimpsest.sections import find_blocks_for, parse_blocks

        # The Act, wrapped at a narrow column, with an amendment marked up.
        act_html = (
            "<tr><td><code>&nbsp;&nbsp;&nbsp;&nbsp;</code><code>Section 5. </code>"
            "<code>The Election Code is amended by changing </code></td></tr>"
            "<tr><td><code>Section 28-1 as follows:</code></td></tr>"
            "<tr><td><code>&nbsp;&nbsp;&nbsp;&nbsp;</code><code>(10 ILCS 5/28-1)</code></td></tr>"
            "<tr><td><code>&nbsp;&nbsp;&nbsp;&nbsp;</code><code>Sec. 28-1. </code>"
            "<code>The initiation of all public questions </code></td></tr>"
            "<tr><td><u><code>and advisory questions</code></u><code> </code>"
            "<strike><code>and nothing else</code></strike><code>, shall be </code></td></tr>"
            "<tr><td><code>subject to this Article.</code></td></tr>"
            "<tr><td><code>(Source: P.A. 100-107, eff. 1-1-18.)</code></td></tr>"
        )
        # The compilation, wrapped at a wider column, with the amendment applied.
        ilcs_html = (
            "<code>&nbsp;&nbsp;&nbsp;&nbsp;</code><code><font>(10 ILCS 5/28-1)</font></code>"
            "<br><code>&nbsp;&nbsp;&nbsp;&nbsp;</code><code><font>Sec. 28-1. </font></code>"
            "<code><font>The initiation of all public questions and advisory\n"
            "questions, shall be subject to this Article.</font></code>"
            "<br><code><font>(Source: P.A. 103-565, eff. 1-1-24.)</font></code>"
        )

        act_blocks = parse_blocks(extract(act_html).text)
        ilcs_blocks = parse_blocks(extract(ilcs_html).text)
        (published,) = ilcs_blocks
        (replayed,) = find_blocks_for(act_blocks, published.citation)

        result = compare(published.body, replayed.body, label=str(published.citation))
        self.assertTrue(result.normalized_match, msg=result.diff)
        self.assertFalse(result.exact_match)

        # And the asymmetry that makes excluding the trailer necessary: the Act
        # prints the *pre*-amendment source, the compilation the post-amendment.
        self.assertEqual(replayed.source.terminal_pa, "100-107")
        self.assertEqual(published.source.terminal_pa, "103-565")

    def test_a_genuine_divergence_survives_normalisation(self):
        from palimpsest.extract import extract
        from palimpsest.sections import parse_blocks

        act = parse_blocks(
            extract(
                "<p>(10 ILCS 5/1-1)</p><p>Sec. 1-1. Thirty days.</p><p>(Source: P.A. 103-1.)</p>"
            ).text
        )[0]
        ilcs = parse_blocks(
            extract(
                "<p>(10 ILCS 5/1-1)</p><p>Sec. 1-1. Sixty days.</p><p>(Source: P.A. 103-1.)</p>"
            ).text
        )[0]
        result = compare(ilcs.body, act.body, label="10 ILCS 5/1-1")
        self.assertFalse(result.normalized_match)
        self.assertNotEqual(
            reduce_to_alnum(normalize(ilcs.body)), reduce_to_alnum(normalize(act.body))
        )


if __name__ == "__main__":
    unittest.main()

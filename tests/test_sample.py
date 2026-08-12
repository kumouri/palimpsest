"""Tests for sample selection and for the normalisation ablation."""

from __future__ import annotations

import unittest

from palimpsest.oracle0 import ablation
from palimpsest.sample import ga_of, stratify, take_evenly
from palimpsest.sections import parse_blocks


def _blocks(*sources: str):
    text = "\n".join(
        f"(10 ILCS 5/{i})\nSec. {i}. Body text {i}.\n(Source: {src})"
        for i, src in enumerate(sources, 1)
    )
    return parse_blocks(text)


class TestGaOf(unittest.TestCase):
    def test_parses_the_general_assembly_number(self):
        self.assertEqual(ga_of("103-274"), 103)
        self.assertEqual(ga_of("86-451"), 86)

    def test_garbage_is_zero_rather_than_an_exception(self):
        self.assertEqual(ga_of(""), 0)
        self.assertEqual(ga_of("nonsense"), 0)


class TestStratify(unittest.TestCase):
    def test_sections_land_in_the_right_stratum(self):
        blocks = _blocks(
            "P.A. 103-274, eff. 1-1-24.",  # recent
            "P.A. 104-1, eff. 1-1-26.",  # recent
            "P.A. 96-542, eff. 1-1-10.",  # modern
            "P.A. 86-451.",  # pre_corpus
            "R.S. 1874, p. 1011.",  # no public act
        )
        strata = stratify(blocks, recent_ga=103, corpus_floor_ga=90)
        self.assertEqual(len(strata["recent"]), 2)
        self.assertEqual(len(strata["modern"]), 1)
        self.assertEqual(len(strata["pre_corpus"]), 1)
        self.assertEqual(len(strata["no_public_act"]), 1)

    def test_every_block_lands_in_exactly_one_stratum(self):
        blocks = _blocks("P.A. 103-1.", "Laws 1945, p. 1717.", "P.A. 92-1.")
        strata = stratify(blocks)
        self.assertEqual(sum(len(v) for v in strata.values()), len(blocks))

    def test_boundaries_are_inclusive_on_the_lower_edge(self):
        strata = stratify(_blocks("P.A. 103-1.", "P.A. 102-1.", "P.A. 90-1.", "P.A. 89-1."))
        self.assertEqual(len(strata["recent"]), 1)
        self.assertEqual(len(strata["modern"]), 2)  # 102 and 90
        self.assertEqual(len(strata["pre_corpus"]), 1)  # 89


class TestTakeEvenly(unittest.TestCase):
    def test_it_is_deterministic(self):
        items = list(range(100))
        self.assertEqual(take_evenly(items, 7), take_evenly(items, 7))

    def test_it_spans_the_whole_list_rather_than_the_front(self):
        picked = take_evenly(list(range(100)), 5)
        self.assertEqual(picked[0], 0)
        self.assertGreater(picked[-1], 50)
        self.assertEqual(len(picked), 5)
        self.assertEqual(len(set(picked)), 5)

    def test_asking_for_more_than_there_are_returns_all(self):
        self.assertEqual(take_evenly([1, 2, 3], 10), [1, 2, 3])

    def test_degenerate_inputs(self):
        self.assertEqual(take_evenly([], 5), [])
        self.assertEqual(take_evenly([1, 2], 0), [])


class TestAblation(unittest.TestCase):
    def test_rows_are_cumulative_and_monotonic(self):
        pairs = [
            ("Sec. 1. Same text.", "Sec. 1. Same text."),  # matches raw
            ("Sec. 2. Wrapped\ntext.", "Sec. 2. Wrapped text."),  # needs N3
            ("Sec. 3. Alpha.", "Sec. 3. Beta."),  # never matches
        ]
        rows = ablation(pairs)
        self.assertEqual(rows[0]["rules"], "none (raw extracted text)")
        self.assertEqual(rows[0]["matched"], 1)
        counts = [r["matched"] for r in rows]
        self.assertEqual(counts, sorted(counts), "adding a rule must never lose a match")
        self.assertEqual(rows[-1]["matched"], 2)
        self.assertEqual(rows[-1]["of"], 3)

    def test_the_marginal_column_attributes_matches_to_the_rule_that_bought_them(self):
        rows = ablation([("a\nb", "a b")])
        by_rule = {r["rules"]: r["marginal"] for r in rows if r["marginal"] is not None}
        self.assertEqual(by_rule["+ N3"], 1)
        self.assertEqual(by_rule["+ N1"], 0)

    def test_empty_input_does_not_divide_by_zero(self):
        for row in ablation([]):
            self.assertEqual(row["rate"], 0.0)


if __name__ == "__main__":
    unittest.main()

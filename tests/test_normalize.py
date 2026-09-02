"""Tests for the normaliser.

Two kinds of test here, and the second kind matters more:

1. each rule does what it claims;
2. **the normaliser does not do what it must never do.** A normaliser that
   quietly folded "shall" into "must", or collapsed a cross-reference, would
   raise the match rate and destroy the measurement. Those are asserted
   explicitly so that loosening a rule breaks a test rather than improving a
   number.
"""

from __future__ import annotations

import unittest

from palimpsest.normalize import ALL_RULES, RULES, RULES_BY_KEY, normalize, rules_table


class TestIndividualRules(unittest.TestCase):
    def test_n3_collapses_wrapping_from_two_different_column_widths(self):
        compiled = "No new law shall be construed to repeal a former law,\nwhether such former law"
        act = "No new law shall be construed to repeal\na former law, whether such former law"
        self.assertEqual(normalize(compiled), normalize(act))

    def test_n3_collapses_the_four_space_paragraph_indent(self):
        self.assertEqual(normalize("    Sec. 4. Text"), normalize("Sec. 4.\nText"))

    def test_n2_straightens_quotes(self):
        self.assertEqual(normalize("“quoted”"), '"quoted"')
        self.assertEqual(normalize("the committee’s"), "the committee's")

    def test_n2_drops_soft_hyphens_and_bom(self):
        self.assertEqual(normalize("juris­diction"), "jurisdiction")
        self.assertEqual(normalize("﻿Sec. 4."), "Sec. 4.")

    def test_n4_removes_the_space_a_deleted_span_leaves_behind(self):
        # "...Assembly <strike>of the 102nd</strike>, the provisions" leaves
        # "Assembly , the provisions" once the deletion is applied.
        self.assertEqual(
            normalize("of the 103rd General Assembly , the provisions"),
            "of the 103rd General Assembly, the provisions",
        )

    def test_n5_removes_the_space_after_an_opening_bracket(self):
        self.assertEqual(normalize("( a) To the extent"), "(a) To the extent")

    def test_n1_normalises_unicode_composition(self):
        self.assertEqual(normalize("é"), normalize("é"))


class TestWhatTheNormaliserMustNotDo(unittest.TestCase):
    """Guard rails. Each of these would inflate the match rate if it broke."""

    def test_it_does_not_change_words(self):
        self.assertNotEqual(normalize("the board shall act"), normalize("the board must act"))

    def test_it_does_not_fold_singular_and_plural(self):
        self.assertNotEqual(normalize("the officer"), normalize("the officers"))

    def test_it_does_not_alter_cross_references(self):
        self.assertNotEqual(normalize("Section 5-1"), normalize("Section 5.1"))
        self.assertNotEqual(normalize("Section 28-1"), normalize("Section 28-2"))

    def test_it_does_not_change_case(self):
        self.assertNotEqual(normalize("Act"), normalize("act"))

    def test_it_does_not_remove_meaningful_punctuation(self):
        self.assertNotEqual(normalize("a, b and c"), normalize("a b and c"))
        self.assertNotEqual(normalize("$500."), normalize("$500"))

    def test_it_does_not_touch_numbers(self):
        self.assertNotEqual(normalize("0.15%"), normalize("0.15 %"))
        self.assertNotEqual(normalize("January 1, 1994"), normalize("January 1, 1995"))

    def test_it_does_not_reorder_or_drop_text(self):
        text = "  Sec. 4.  No new law shall be construed  "
        self.assertEqual(normalize(text).split(), text.split())


class TestRuleRegistry(unittest.TestCase):
    def test_every_rule_is_documented_with_a_rationale_and_a_risk(self):
        for rule in RULES:
            with self.subTest(rule=rule.key):
                self.assertTrue(rule.title.strip())
                self.assertTrue(len(rule.rationale) > 40, "rationale must be a real one")
                self.assertTrue(len(rule.risk) > 20, "every rule must state its risk")

    def test_rule_keys_are_unique(self):
        keys = [r.key for r in RULES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_all_rules_matches_the_registry(self):
        self.assertEqual(set(ALL_RULES), set(RULES_BY_KEY))

    def test_rules_table_lists_every_rule(self):
        table = rules_table()
        for rule in RULES:
            self.assertIn(f"`{rule.key}`", table)

    def test_disabling_rules_is_honoured(self):
        self.assertEqual(normalize("a\n b", enabled=()), "a\n b")
        self.assertEqual(normalize("a\n b", enabled=("N3",)), "a b")

    def test_normalisation_is_idempotent(self):
        for text in ("  a\n\nb ", "x , y", "( a) b", "“q”"):
            with self.subTest(text=text):
                once = normalize(text)
                self.assertEqual(once, normalize(once))


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _stage_loader import load_stage  # noqa: E402

synthesis = load_stage("03_synthesis")


def ok(name, value, detail="", extra=None):
    return SimpleNamespace(name=name, status="ok", value=value, detail=detail, extra=extra or {})


def failed(name, detail):
    return SimpleNamespace(name=name, status="failed", value=None, detail=detail, extra={})


class TestValuesAgree(unittest.TestCase):
    def test_string_case_insensitive(self):
        self.assertTrue(synthesis.values_agree("Paris", "paris", "capital"))
        self.assertFalse(synthesis.values_agree("Paris", "Lyon", "capital"))

    def test_numeric_within_tolerance(self):
        self.assertTrue(synthesis.values_agree("40000000", "41500000", "population"))

    def test_numeric_outside_tolerance(self):
        self.assertFalse(synthesis.values_agree("10000000", "20000000", "population"))


class TestReconcile(unittest.TestCase):
    def test_all_three_agree_is_high_confidence(self):
        wd = ok("wikidata", "Tokyo")
        csv = ok("local_csv", "Tokyo")
        wiki = ok("wikipedia", "match", extra={"corroborated": ["wikidata", "local_csv"]})
        v = synthesis.reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "answered")
        self.assertEqual(v.answer, "Tokyo")
        self.assertEqual(v.confidence, "HIGH")
        self.assertIn("wikipedia", v.sources_used)

    def test_csv_failure_degrades_to_medium_confidence_when_wikipedia_corroborates(self):
        wd = ok("wikidata", "Paris")
        csv = failed("local_csv", "file not found: references/local_facts.csv")
        wiki = ok("wikipedia", "match", extra={"corroborated": ["wikidata"]})
        v = synthesis.reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "answered")
        self.assertEqual(v.answer, "Paris")
        self.assertEqual(v.confidence, "MEDIUM")
        self.assertEqual(v.sources_used, ["wikidata", "wikipedia"])
        self.assertTrue(any(name == "local_csv" for name, _ in v.sources_skipped))

    def test_single_source_with_no_corroboration_declines(self):
        wd = ok("wikidata", "Paris")
        csv = failed("local_csv", "file not found")
        wiki = failed("wikipedia", "timed out after 6s")
        v = synthesis.reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "declined")
        self.assertIsNone(v.confidence)
        self.assertEqual(v.sources_used, [])

    def test_conflict_with_tiebreak_answers_with_medium_confidence_and_discloses_conflict(self):
        wd = ok("wikidata", "Berlin")
        csv = ok("local_csv", "Munich")
        wiki = ok("wikipedia", "match", extra={"corroborated": ["wikidata"]})
        v = synthesis.reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "answered")
        self.assertEqual(v.answer, "Berlin")
        self.assertEqual(v.confidence, "MEDIUM")
        self.assertIn("wikidata=Berlin", v.reason)
        self.assertIn("local_csv=Munich", v.reason)

    def test_conflict_without_tiebreak_declines(self):
        wd = ok("wikidata", "Ottawa")
        csv = ok("local_csv", "Toronto")
        wiki = failed("wikipedia", "simulated failure")
        v = synthesis.reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "declined")
        self.assertIsNone(v.answer)
        self.assertEqual(v.sources_used, [])

    def test_all_sources_fail_declines_with_reasons(self):
        wd = failed("wikidata", "no Wikidata entity found for 'Zzzznotreal'")
        csv = failed("local_csv", "no row for entity='Zzzznotreal'")
        wiki = failed("wikipedia", "no candidate values to corroborate (wikidata and local_csv both failed)")
        v = synthesis.reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "declined")
        self.assertIn("Zzzznotreal", v.reason)


if __name__ == "__main__":
    unittest.main()

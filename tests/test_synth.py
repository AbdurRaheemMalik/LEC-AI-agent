import unittest

from factchecker.sources import SourceResult
from factchecker.synth import reconcile, values_agree


def ok(name, value, detail="", extra=None):
    return SourceResult(name=name, status="ok", value=value, detail=detail, extra=extra or {})


def failed(name, detail):
    return SourceResult(name=name, status="failed", value=None, detail=detail)


class TestValuesAgree(unittest.TestCase):
    def test_string_case_insensitive(self):
        self.assertTrue(values_agree("Paris", "paris", "capital"))
        self.assertFalse(values_agree("Paris", "Lyon", "capital"))

    def test_numeric_within_tolerance(self):
        self.assertTrue(values_agree("40000000", "41500000", "population"))  # ~3.6% apart

    def test_numeric_outside_tolerance(self):
        self.assertFalse(values_agree("10000000", "20000000", "population"))


class TestReconcile(unittest.TestCase):
    def test_all_three_agree_is_high_confidence(self):
        wd = ok("wikidata", "Tokyo")
        csv = ok("local_csv", "Tokyo")
        wiki = ok("wikipedia", "wikidata:match; local_csv:match", extra={"corroborated": ["wikidata", "local_csv"]})
        v = reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "answered")
        self.assertEqual(v.answer, "Tokyo")
        self.assertEqual(v.confidence, "HIGH")
        self.assertIn("wikipedia", v.sources_used)

    def test_csv_failure_degrades_to_medium_confidence_when_wikipedia_corroborates(self):
        wd = ok("wikidata", "Paris")
        csv = failed("local_csv", "file not found: data/local_facts.csv")
        wiki = ok("wikipedia", "wikidata:match", extra={"corroborated": ["wikidata"]})
        v = reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "answered")
        self.assertEqual(v.answer, "Paris")
        self.assertEqual(v.confidence, "MEDIUM")
        self.assertEqual(v.sources_used, ["wikidata", "wikipedia"])
        self.assertTrue(any(name == "local_csv" for name, _ in v.sources_skipped))

    def test_single_source_with_no_corroboration_declines(self):
        wd = ok("wikidata", "Paris")
        csv = failed("local_csv", "file not found")
        wiki = failed("wikipedia", "timed out after 6s")
        v = reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "declined")
        self.assertIsNone(v.confidence)
        self.assertEqual(v.sources_used, [])

    def test_conflict_with_tiebreak_answers_with_medium_confidence_and_discloses_conflict(self):
        wd = ok("wikidata", "Berlin")
        csv = ok("local_csv", "Munich")
        wiki = ok("wikipedia", "...", extra={"corroborated": ["wikidata"]})
        v = reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "answered")
        self.assertEqual(v.answer, "Berlin")
        self.assertEqual(v.confidence, "MEDIUM")
        self.assertIn("wikidata=Berlin", v.reason)
        self.assertIn("local_csv=Munich", v.reason)

    def test_conflict_without_tiebreak_declines(self):
        wd = ok("wikidata", "Ottawa")
        csv = ok("local_csv", "Toronto")
        wiki = failed("wikipedia", "simulated failure")
        v = reconcile(wd, csv, wiki, "capital")
        self.assertEqual(v.status, "declined")
        self.assertIsNone(v.answer)
        self.assertEqual(v.sources_used, [])

    def test_all_sources_fail_declines_with_reasons(self):
        wd = failed("wikidata", "no Wikidata entity found for 'Zzzznotreal'")
        csv = failed("local_csv", "no row for entity='Zzzznotreal'")
        v = reconcile(wd, csv, None, "capital")
        self.assertEqual(v.status, "declined")
        self.assertIn("Zzzznotreal", v.reason)


if __name__ == "__main__":
    unittest.main()

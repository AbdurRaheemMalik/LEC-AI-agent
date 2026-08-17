import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _stage_loader import load_stage  # noqa: E402

planning = load_stage("01_planning")


class TestPlanning(unittest.TestCase):
    def test_capital_question(self):
        plan = planning.make_plan("What is the capital of Japan?")
        self.assertEqual(plan.entity, "Japan")
        self.assertEqual(plan.attribute, "capital")

    def test_population_question_strips_article(self):
        plan = planning.make_plan("What is the population of the United States?")
        self.assertEqual(plan.entity, "United States")
        self.assertEqual(plan.attribute, "population")

    def test_currency_question(self):
        plan = planning.make_plan("What is the currency of France?")
        self.assertEqual(plan.attribute, "currency")
        self.assertEqual(plan.entity, "France")

    def test_who_wrote_question(self):
        plan = planning.make_plan("Who wrote Hamlet?")
        self.assertEqual(plan.attribute, "author")
        self.assertEqual(plan.entity, "Hamlet")

    def test_founded_question(self):
        plan = planning.make_plan("When was Google founded?")
        self.assertEqual(plan.attribute, "founded")
        self.assertEqual(plan.entity, "Google")

    def test_born_question(self):
        plan = planning.make_plan("When was Albert Einstein born?")
        self.assertEqual(plan.attribute, "birth_date")
        self.assertEqual(plan.entity, "Albert Einstein")

    def test_out_of_scope_question_produces_no_plan(self):
        plan = planning.make_plan("What is the meaning of life?")
        self.assertIsNone(plan.attribute)
        self.assertIsNone(plan.entity)
        self.assertTrue(plan.reason)

        plan2 = planning.make_plan("How do I bake bread?")
        self.assertIsNone(plan2.attribute)


if __name__ == "__main__":
    unittest.main()

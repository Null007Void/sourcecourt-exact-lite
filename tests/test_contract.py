import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sourcecourt.contracts import AnswerResult, Evidence, ResultStatus
from sourcecourt.question import QuestionKind, interpret_question


class ResultContractTests(unittest.TestCase):
    def test_answered_result_requires_verified_source_evidence(self):
        evidence = Evidence(source_url="https://example.test/facts", quote="Launch date: October 27, 2026.")
        result = AnswerResult(
            status=ResultStatus.ANSWERED,
            answer="Launch date: October 27, 2026.",
            source_url=evidence.source_url,
            evidence=(evidence,),
            visited_urls=("https://example.test/", evidence.source_url),
        )
        self.assertEqual(result.status, ResultStatus.ANSWERED)
        self.assertEqual(result.evidence[0].source_url, result.source_url)

    def test_answered_result_rejects_missing_evidence(self):
        with self.assertRaises(ValueError):
            AnswerResult(
                status=ResultStatus.ANSWERED,
                answer="October 27, 2026",
                source_url="https://example.test/facts",
            )

    def test_refusal_has_no_answer(self):
        result = AnswerResult(status=ResultStatus.UNSUPPORTED, diagnostic="No supported answer")
        self.assertIsNone(result.answer)
        self.assertIsNone(result.source_url)


class QuestionInterpretationTests(unittest.TestCase):
    def test_interprets_natural_language_question(self):
        intent = interpret_question("When is the SourceCourt launch date?")
        self.assertEqual(intent.kind, QuestionKind.WHEN)
        self.assertEqual(intent.keywords, ("sourcecourt", "launch", "date"))

    def test_interprets_how_many_question(self):
        intent = interpret_question("How many retrieval pages are allowed?")
        self.assertEqual(intent.kind, QuestionKind.HOW_MANY)
        self.assertIn("retrieval", intent.keywords)

    def test_rejects_blank_or_oversized_question(self):
        for question in ("   ", "x" * 501):
            with self.subTest(question_length=len(question)):
                with self.assertRaises(ValueError):
                    interpret_question(question)

    def test_rejects_non_string_and_control_characters(self):
        for question in (None, 12, "What is this?\x00"):
            with self.subTest(question=repr(question)):
                with self.assertRaises((TypeError, ValueError)):
                    interpret_question(question)


if __name__ == "__main__":
    unittest.main()

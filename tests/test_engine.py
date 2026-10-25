import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sourcecourt.contracts import ResultStatus
from sourcecourt.engine import EngineLimits, RetrievalEngine, verify_model_candidate
from sourcecourt.fetch import RetrievedPage, RetrievalError
from sourcecourt.model import ModelCandidate


class FixtureFetcher:
    def __init__(self, pages, failures=()):
        self.pages = pages
        self.failures = set(failures)
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        if url in self.failures:
            raise RetrievalError("synthetic failure")
        if url not in self.pages:
            raise RetrievalError("missing synthetic page")
        return RetrievedPage(url, url, 200, "text/html", self.pages[url])


class InvalidModelAdapter:
    name = "synthetic-invalid-adapter"

    def extract(self, intent, documents):
        return ModelCandidate(
            answer="Invented answer",
            source_url="https://example.test/facts",
            evidence_quote="This quote does not exist.",
        )


class ValidModelAdapter:
    name = "synthetic-valid-adapter"

    def extract(self, intent, documents):
        return ModelCandidate(
            answer="October 27, 2026",
            source_url="https://example.test/facts",
            evidence_quote="The SourceCourt launch date is October 27, 2026.",
        )


class RetrievalEngineTests(unittest.TestCase):
    def test_navigates_relevant_link_and_extracts_supported_answer(self):
        pages = {
            "https://example.test/": "<a href='/team'>Team</a><a href='/facts'>Official SourceCourt launch details</a>",
            "https://example.test/team": "<p>Ada leads the team.</p>",
            "https://example.test/facts": "<p>The SourceCourt launch date is October 27, 2026.</p>",
        }
        result = RetrievalEngine(FixtureFetcher(pages), limits=EngineLimits(max_pages=2)).answer(
            "When is the SourceCourt launch date?", "https://example.test/"
        )
        self.assertEqual(result.status, ResultStatus.ANSWERED)
        self.assertEqual(result.answer, "The SourceCourt launch date is October 27, 2026.")
        self.assertEqual(result.source_url, "https://example.test/facts")
        self.assertEqual(result.evidence[0].quote, result.answer)
        self.assertEqual(result.visited_urls, ("https://example.test/", "https://example.test/facts"))

    def test_refuses_unsupported_answer(self):
        pages = {"https://example.test/": "<p>This site discusses weather.</p>"}
        result = RetrievalEngine(FixtureFetcher(pages)).answer(
            "Who founded SourceCourt?", "https://example.test/"
        )
        self.assertEqual(result.status, ResultStatus.UNSUPPORTED)
        self.assertIsNone(result.answer)

    def test_reports_ambiguity_for_equally_supported_conflicting_answers(self):
        pages = {
            "https://example.test/": "<a href='/a'>SourceCourt launch date A</a><a href='/b'>SourceCourt launch date B</a>",
            "https://example.test/a": "<p>The SourceCourt launch date is October 27, 2026.</p>",
            "https://example.test/b": "<p>The SourceCourt launch date is October 28, 2026.</p>",
        }
        result = RetrievalEngine(FixtureFetcher(pages), limits=EngineLimits(max_pages=3)).answer(
            "When is the SourceCourt launch date?", "https://example.test/"
        )
        self.assertEqual(result.status, ResultStatus.AMBIGUOUS)
        self.assertIsNone(result.answer)
        self.assertEqual(len(result.evidence), 2)

    def test_recovers_from_failed_relevant_link(self):
        pages = {
            "https://example.test/": "<a href='/broken'>SourceCourt launch date details</a><a href='/facts'>SourceCourt launch date facts</a>",
            "https://example.test/facts": "<p>The SourceCourt launch date is October 27, 2026.</p>",
        }
        fetcher = FixtureFetcher(pages, failures={"https://example.test/broken"})
        result = RetrievalEngine(fetcher, limits=EngineLimits(max_pages=3)).answer(
            "When is the SourceCourt launch date?", "https://example.test/"
        )
        self.assertEqual(result.status, ResultStatus.ANSWERED)
        self.assertIn("https://example.test/broken", fetcher.calls)
        self.assertIn("https://example.test/facts", fetcher.calls)

    def test_reports_start_page_retrieval_failure(self):
        result = RetrievalEngine(FixtureFetcher({}, failures={"https://example.test/"})).answer(
            "When is launch?", "https://example.test/"
        )
        self.assertEqual(result.status, ResultStatus.RETRIEVAL_FAILED)

    def test_does_not_follow_cross_origin_links_by_default(self):
        pages = {
            "https://example.test/": "<a href='https://evil.test/facts'>SourceCourt launch date</a>",
            "https://evil.test/facts": "<p>The SourceCourt launch date is October 27, 2026.</p>",
        }
        fetcher = FixtureFetcher(pages)
        result = RetrievalEngine(fetcher).answer(
            "When is the SourceCourt launch date?", "https://example.test/"
        )
        self.assertEqual(result.status, ResultStatus.UNSUPPORTED)
        self.assertNotIn("https://evil.test/facts", fetcher.calls)

    def test_invalid_model_evidence_cannot_create_answer(self):
        pages = {"https://example.test/": "<p>No launch facts are present.</p>"}
        result = RetrievalEngine(FixtureFetcher(pages), model=InvalidModelAdapter()).answer(
            "When is the SourceCourt launch date?", "https://example.test/"
        )
        self.assertEqual(result.status, ResultStatus.UNSUPPORTED)

    def test_verified_model_candidate_is_accepted(self):
        pages = {"https://example.test/facts": "<p>The SourceCourt launch date is October 27, 2026.</p>"}
        result = RetrievalEngine(FixtureFetcher(pages), model=ValidModelAdapter()).answer(
            "When is the SourceCourt launch date?", "https://example.test/facts"
        )
        self.assertEqual(result.status, ResultStatus.ANSWERED)
        self.assertEqual(result.answer, "October 27, 2026")

    def test_source_verifier_rejects_wrong_url_or_quote(self):
        pages = {"https://example.test/facts": "The launch date is October 27, 2026."}
        docs = RetrievalEngine(FixtureFetcher(pages)).retrieve(
            "When is the launch date?", "https://example.test/facts"
        )
        self.assertFalse(verify_model_candidate(
            ModelCandidate("October 27", "https://other.test/", "The launch date is October 27, 2026."), docs.documents
        ))
        self.assertFalse(verify_model_candidate(
            ModelCandidate("October 27", "https://example.test/facts", "fabricated quote"), docs.documents
        ))

    def test_malformed_retrieved_link_does_not_abort_a_valid_answer(self):
        # M4-022C: the page author's broken href must cost that link only. The
        # user's question and URL are valid; the answer must survive.
        pages = {
            "https://example.test/facts": (
                '<a href="http://[bad">broken</a>'
                "<p>The server port is 8443 and accepts requests.</p>"
            )
        }
        result = RetrievalEngine(FixtureFetcher(pages)).answer(
            "What is the server port?", "https://example.test/facts"
        )
        self.assertEqual(result.status, ResultStatus.ANSWERED)
        self.assertEqual(result.answer, "8443")
        self.assertIn("8443", result.evidence[0].quote)

    def test_retrieved_link_with_unusable_port_is_skipped_not_fatal(self):
        pages = {
            "https://example.test/facts": (
                '<a href="http://example.test:99999/x">bad port</a>'
                "<p>The server port is 8443.</p>"
            )
        }
        result = RetrievalEngine(FixtureFetcher(pages)).answer(
            "What is the server port?", "https://example.test/facts"
        )
        self.assertEqual(result.status, ResultStatus.ANSWERED)
        self.assertEqual(result.answer, "8443")

    def test_malformed_start_url_is_still_refused_without_an_answer(self):
        # The robustness fix must not make a bad USER url answerable. The
        # fetcher rejects it before any connection (RETRIEVAL_FAILED, exit 2).
        pages = {"https://example.test/facts": "<p>The server port is 8443.</p>"}
        result = RetrievalEngine(FixtureFetcher(pages)).answer(
            "What is the server port?", "http://[bad"
        )
        self.assertEqual(result.status, ResultStatus.RETRIEVAL_FAILED)
        self.assertIsNone(result.answer)

    def test_invalid_question_returns_invalid_input(self):
        result = RetrievalEngine(FixtureFetcher({})).answer("\x00", "https://example.test/")
        self.assertEqual(result.status, ResultStatus.INVALID_INPUT)


if __name__ == "__main__":
    unittest.main()

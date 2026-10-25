import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sourcecourt.document import parse_document, rank_links
from sourcecourt.question import interpret_question


class DocumentParsingTests(unittest.TestCase):
    def test_extracts_visible_text_and_resolved_links(self):
        doc = parse_document(
            "https://example.test/start",
            """<html><head><title>Home</title><script>secret()</script></head>
            <body><p>Welcome to SourceCourt.</p>
            <a href='/facts'>Launch facts</a><a href='mailto:x@y'>Email</a></body></html>""",
        )
        self.assertIn("Welcome to SourceCourt.", doc.text)
        self.assertNotIn("secret", doc.text)
        self.assertEqual(doc.links[0].url, "https://example.test/facts")
        self.assertEqual(len(doc.links), 1)

    def test_ranks_relevant_links_deterministically(self):
        doc = parse_document(
            "https://example.test/",
            "<a href='/team'>Team</a><a href='/launch'>SourceCourt launch date</a>",
        )
        ranked = rank_links(interpret_question("When is the SourceCourt launch date?"), doc.links)
        self.assertEqual(ranked[0].url, "https://example.test/launch")

    def test_tolerates_malformed_html(self):
        doc = parse_document("https://example.test/", "<p>Launch date: October 27<div>open")
        self.assertIn("Launch date: October 27", doc.text)


class LinkRobustnessTests(unittest.TestCase):
    """M4-022C: one broken href must not cost the page."""

    def test_malformed_links_are_dropped_and_valid_links_and_text_kept(self):
        doc = parse_document(
            "https://example.test/start",
            '<a href="http://[bad">broken</a>'
            "<a href='/facts'>Facts</a>"
            '<a href="http://example.test:99999/x">bad port</a>'
            "<p>The server port is 8443.</p>",
        )
        urls = [link.url for link in doc.links]
        self.assertNotIn("http://[bad", urls)
        self.assertIn("https://example.test/facts", urls)
        self.assertIn("The server port is 8443.", doc.text)

    def test_only_malformed_links_leaves_an_empty_link_list(self):
        doc = parse_document(
            "https://example.test/start",
            '<a href="http://[bad">one</a><a href="http://[also">two</a><p>Text.</p>',
        )
        self.assertEqual(doc.links, ())
        self.assertIn("Text.", doc.text)


class SegmentationTests(unittest.TestCase):
    """V1.1: paragraphs and sentences are separate ideas.

    The 1.0.0 splitter treated every newline as a sentence boundary, so any
    hard-wrapped page (RFC text, console output, hand-wrapped HTML) produced
    mid-sentence fragments and the engine answered with one.
    """

    WRAPPED = (
        "   The use of domain names that end in .test is recommended for\n"
        "   use in testing of current or new DNS related code.  It is\n"
        "   reserved for that purpose.\n"
    )

    def test_hard_wrapped_plain_text_is_joined_into_whole_sentences(self):
        doc = parse_document("https://example.test/rfc.txt", self.WRAPPED)
        self.assertIn(
            "The use of domain names that end in .test is recommended for use in "
            "testing of current or new DNS related code.",
            doc.sentences,
        )
        self.assertIn("It is reserved for that purpose.", doc.sentences)
        for sentence in doc.sentences:
            self.assertFalse(sentence.endswith(" as an"), sentence)

    def test_dotted_identifiers_decimals_and_abbreviations_are_not_boundaries(self):
        doc = parse_document(
            "https://example.test/notes.txt",
            "Version 1.1.0 supports example.com and .test names, i.e. 3.5 times "
            "faster than before.",
        )
        self.assertEqual(
            doc.sentences,
            (
                "Version 1.1.0 supports example.com and .test names, i.e. 3.5 "
                "times faster than before.",
            ),
        )

    def test_blank_lines_and_block_tags_separate_paragraphs(self):
        plain = parse_document(
            "https://example.test/p.txt",
            "First paragraph wraps here\nand continues here.\n\nSecond paragraph.",
        )
        self.assertEqual(
            plain.sentences,
            ("First paragraph wraps here and continues here.", "Second paragraph."),
        )
        html = parse_document(
            "https://example.test/", "<p>One.</p><p>Two.</p><li>Three</li>"
        )
        self.assertEqual(html.sentences, ("One.", "Two.", "Three"))

    def test_sentence_after_terminal_quote_still_splits(self):
        doc = parse_document(
            "https://example.test/q.txt",
            'The name ".test" is reserved. "Use it in tests." That is all.',
        )
        self.assertEqual(
            doc.sentences,
            (
                'The name ".test" is reserved.',
                '"Use it in tests."',
                "That is all.",
            ),
        )



if __name__ == "__main__":
    unittest.main()

"""HTML-to-text parsing and deterministic relevant-link ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from .question import QuestionIntent


@dataclass(frozen=True)
class Link:
    url: str
    text: str


@dataclass(frozen=True)
class Document:
    url: str
    text: str
    sentences: tuple[str, ...]
    links: tuple[Link, ...]


_SPACE = re.compile(r"\s+")
# A sentence ends at terminal punctuation followed by whitespace and the start
# of a new sentence (uppercase letter, digit, or an opening quote/bracket). The
# lookahead keeps abbreviations, decimals, version numbers, hostnames and
# dotted identifiers ("e.g.", "3.5", ".test", "example.com") inside one
# sentence instead of shredding them at every period.
_SENTENCE_END = re.compile(
    r"(?<=[.!?])\s+(?=[\"'(\[\u201c\u2018A-Z0-9])"
    r"|(?<=[.!?][\"')\]])\s+(?=[\"'(\[\u201c\u2018A-Z0-9])"
)
# Blank lines separate paragraphs; a single newline inside a paragraph is a
# hard wrap (RFC text, console output, hand-wrapped HTML source), not a
# sentence boundary.
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
# Abbreviations that end in a period but do not end a sentence.
_ABBREVIATIONS = frozenset(
    {"e.g.", "i.e.", "cf.", "vs.", "etc.", "al.", "mr.", "dr.", "ms.", "no.", "fig.", "approx."}
)
_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_BLOCK_TAGS = frozenset(
    {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "title", "pre", "blockquote", "tr", "td"}
)



class _PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.hidden_depth = 0
        self.text_parts: list[str] = []
        self.links: list[Link] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden_depth += 1
            return
        if self.hidden_depth:
            return
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor_parts = []
        elif tag in _BLOCK_TAGS:
            self.text_parts.append("\n\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"}:
            if self.hidden_depth:
                self.hidden_depth -= 1
            return
        if self.hidden_depth:
            return
        if tag == "a" and self._href is not None:
            self._add_link(self._href)
            self._href = None
            self._anchor_parts = []
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n\n")

    def handle_data(self, data: str):
        if self.hidden_depth:
            return
        self.text_parts.append(data)
        if self._href is not None:
            self._anchor_parts.append(data)

    def _add_link(self, href: str) -> None:
        """Record one link, discarding hrefs that cannot be parsed.

        A malformed href inside retrieved content (for example ``http://[bad``)
        is the page author's mistake, not the user's. It must cost that one link
        and nothing else: the page text and every other link stay usable.
        """
        try:
            absolute, _fragment = urldefrag(urljoin(self.base_url, href))
            parsed = urlsplit(absolute)
            scheme = parsed.scheme.lower()
            hostname = parsed.hostname  # raises ValueError for malformed IPv6 hosts
            username = parsed.username
        except (ValueError, UnicodeError):
            return
        if scheme in {"http", "https"} and hostname and not username:
            label = _SPACE.sub(" ", " ".join(self._anchor_parts)).strip()
            self.links.append(Link(absolute, label))


def _split_sentences(paragraph: str) -> list[str]:
    """Split one paragraph into sentences, keeping dotted tokens intact."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(paragraph):
        candidate = paragraph[start : match.start()].strip()
        if not candidate:
            start = match.end()
            continue
        if candidate.split()[-1].lower() in _ABBREVIATIONS:
            continue
        sentences.append(candidate)
        start = match.end()
    tail = paragraph[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def parse_document(url: str, html: str) -> Document:
    parser = _PageParser(url)
    parser.feed(html)
    parser.close()
    paragraphs = tuple(
        text
        for text in (
            _SPACE.sub(" ", block).strip()
            for block in _PARAGRAPH_BREAK.split("".join(parser.text_parts))
        )
        if text
    )
    text = "\n".join(paragraphs)
    sentences = tuple(
        sentence for paragraph in paragraphs for sentence in _split_sentences(paragraph)
    )
    seen: set[str] = set()
    links: list[Link] = []
    for link in parser.links:
        if link.url not in seen:
            seen.add(link.url)
            links.append(link)
    return Document(url=url, text=text, sentences=sentences, links=tuple(links))


def rank_links(intent: QuestionIntent, links: tuple[Link, ...]) -> tuple[Link, ...]:
    keywords = set(intent.keywords)

    def key(link: Link):
        words = set(_WORD.findall(f"{link.text} {urlsplit(link.url).path}".lower()))
        overlap = len(keywords & words)
        return (-overlap, link.url)

    return tuple(sorted(links, key=key))

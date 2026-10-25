# Known limitations

Every item below is measured against the 1.1.2 code, not inferred from intent.
The three documentation defects that existed inside the frozen 1.0.0 artifact
(exit-code claim, "wheel carries tests" claim, `User-Agent 0.1`) were fixed in
1.1.0 and are not listed as open issues; see
[`ACCEPTANCE.md`](ACCEPTANCE.md) for the change record.

## Answering behaviour

1. **Extraction is deterministic, not semantic QA.** Sentence answers still
   require the configured keyword overlap and a question-type cue. There is no
   language model: an answer is a value or a sentence that literally appears in
   the retrieved text.
2. **Typed value answers cover four value kinds only** — domain/TLD/host, port,
   version, percentage. A question that asks for something else (a person, a
   place, a date, a count, a price) is answered with the supporting sentence.
3. **A typed question with no value of the requested kind refuses.** It never
   falls back to a topically related sentence. That is deliberate, but it means
   a page that states the value in words ("the port is eighty-four") is not
   answered.
4. **A passage containing two different values of the requested kind returns
   the passage, not one of the values.** No coin flip, but also no
   disambiguation.
5. **The relation phrase is used as a relevance signal, not as a parser.** For
   `"… the top-level domain for testing"` the phrase `for testing` (allowing
   function words such as "use in") selects the passage. Unusual phrasings fall
   back to keyword overlap, and a question with no prepositional phrase at all
   relies on overlap alone.
6. **Ties are refusals.** Two equally scored, differently worded passages
   produce `AMBIGUOUS` with both quotes.
7. **Question length is bounded at 500 characters**; longer input is invalid.
8. **Same-origin navigation only**, at most 3 pages, 2 hops, 8 ranked links per
   page, and only links sharing a keyword with the question are followed. These
   are library-settable (`EngineLimits`), not CLI flags.
9. **`max_pages` bounds retrieved documents, not fetch attempts.** A page with
   several relevant but broken links can cause more outbound attempts than the
   page count suggests, because each attempt happens before the page budget is
   consumed. The total stays finite (`max_links_per_page` per page, bounded by
   depth), but an operator counting requests should read it as attempts, not
   pages.

## Segmentation

10. **Sentence splitting is heuristic.** A period only ends a sentence when it is
   followed by whitespace and an upper-case letter, digit, quote or bracket, and
   a short abbreviation list (`e.g.`, `i.e.`, `vs.`, …) is exempted. A sentence
   that begins with a lower-case word after a full stop, or a rare abbreviation
   outside that list, will be mis-segmented.
11. **A single newline inside a paragraph is treated as a hard wrap** (correct
   for RFC text and console output), so HTML that uses raw newlines to separate
    list items without block tags will merge them. Well-formed HTML uses block
    tags, which are treated as paragraph boundaries.

## Retrieval and protocol

12. **No JavaScript, iframes, cookies, sessions, authentication, robots.txt
   handling, HTTP/2, or PDF/image/audio/video.** Only `text/html` and
    `text/plain` count as source material.
13. **No compression support.** The client sends `Accept-Encoding: identity`. A
   server that compresses anyway is not decompressed; the body is decoded as
    text and usually fails or yields no supported sentence.
14. **Strict decoding.** A declared charset that does not decode cleanly is a
   `RETRIEVAL_FAILED`, not a best-effort answer.
15. **One overall deadline, default 5.0 s** (`FetchLimits.timeout_seconds`),
   covering DNS, connect, TLS, redirects, headers and body. The CLI exposes no
    timeout flag; library callers can set it.
16. **Hard resource caps:** 1,000,000 bytes per response, 3 redirects,
   2048-character URLs. Exceeding any is a refusal, never a partial answer.
17. **Some sites refuse non-browser clients** (403) or return content types the
   product does not accept. Those fail honestly as `RETRIEVAL_FAILED`.

## Output contract

18. **The JSON record has no schema identifier, version, request id, timestamp,
   or reason code.** Fields are `status`, `answer`, `source_url`, `evidence`,
    `visited_urls`, `diagnostic`. Consumers must key on `status` plus
    `diagnostic` text.
19. **There is no receipt, ledger, or tamper-evidence mechanism** in this
   product line. An earlier internal experiment explored durable receipts and a
    different operator CLI; it never shipped and is not in this repository (see
    [`PROVENANCE.md`](PROVENANCE.md)).

## Environment and scope

20. **Verified on Windows with CPython 3.11.16 and 3.13.2.** The code is pure
   standard library; other interpreters and operating systems are expected to
    work but have not been measured for this release.
21. **The official AMD AI League Match 4 grader and submission contract are not
   public and were not available.** Nothing here maps to a grader schema, a
    container contract, a ROCm requirement, or a model interface, and no
    compatibility with any of them is claimed. Mapping is deferred until the
    organizer publishes authoritative requirements.
22. **This is not a general web-research agent.** It does not discover sources,
   aggregate sites, or answer from model knowledge. It answers from one
    operator-supplied origin, or it refuses.

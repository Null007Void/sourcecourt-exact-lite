# Acceptance record — SourceCourt Exact Lite 1.1.2

This document states exactly what is accepted, what changed in 1.1.0 and
1.1.2, and what
is not claimed. It supersedes the 1.0.0 record; the 1.0.0 artifacts and their
acceptance record are preserved unchanged in the maintainers' custody area.

## The exact claim

SourceCourt Exact Lite accepts a natural-language question plus a starting
HTTP/HTTPS URL on one website, retrieves a bounded set of static HTML or plain
text pages from that origin, and returns either:

- a **source-bound answer** — an identifier-like value (domain/TLD, port,
  version, percentage) when the question asks for one and exactly one appears
  in the supporting passage, otherwise the supporting sentence — with the
  verbatim quote that supports it, or
- an **explicit typed refusal** (`UNSUPPORTED`, `AMBIGUOUS`,
  `RETRIEVAL_FAILED`, `INVALID_INPUT`).

It never fabricates an answer because a page could not be retrieved, never
returns an answer that is not present in a retrieved page, and never returns an
identifier value that is not a substring of its own evidence quote.

## Acceptance layers (never collapsed)

| Layer | State | Meaning |
| --- | --- | --- |
| Engineering (retrieval/security core) | **accepted** | The SSRF/DNS/redirect/TLS/deadline/size behaviour accepted at checkpoint M4-019G is unchanged in 1.1.0 and is re-verified on every run by `tests/test_fetch.py` (23 tests) and `tests/test_integration_http.py`. |
| Product 1.1.2 | **accepted locally** | Typed value answers, paragraph-aware segmentation, port lexical boundaries and malformed-link robustness. 99/99 warning-strict tests, clean-room install from the wheel and from source, and live product workflows reproduced from the artifacts. |
| Release | **candidate, unpublished** | Repository and artifacts are publication-ready. No publication, push, tag, or competition submission was performed. |

A green suite is not an acceptance verdict by itself; the layers above rest on
the evidence in [`VERIFICATION.md`](VERIFICATION.md) and the artifact identities
in [`RELEASE_MANIFEST.md`](RELEASE_MANIFEST.md).

## What changed in 1.1.0 (and why)

| Change | Reason |
| --- | --- |
| `document.py`: paragraph-aware segmentation; a single newline is a hard wrap, blank lines and block tags are paragraph boundaries; the splitter no longer breaks at periods inside `.test`, `example.com`, `1.1.0`, `3.5`, or `i.e.` | 1.0.0 split on every newline, so any hard-wrapped page (RFC text, console output, hand-wrapped HTML) produced mid-sentence fragments and the engine answered with one. |
| `question.py`: declared value-type lexicon (`domain`, `host`, `tld`, `suffix`, `extension`, `port`, `version`, `percentage`) and relation-phrase extraction (`… for testing`) | Needed to recognise what kind of value a question asks for, and which passage satisfies the question's condition. |
| `engine.py`: typed candidate selection and value answers | Returns `.test` rather than a sentence that merely mentions testing. |
| `fetch.py`: `User-Agent` built from the package version | 1.0.0 sent `SourceCourt-Exact-Lite/0.1`, contradicting its own version. |
| `cli.py`: exit-code documentation corrected, dead usage-code branch removed, `--help` epilog states exit codes and answer shapes | 1.0.0 documented an exit code 1 that argparse never produces. |
| `MANIFEST.in`, `tools/build_release.py` | Reproducible, audited builds; the repository-only integrity test is excluded from the sdist. |

The 1.0.0 core was byte-frozen at M4-019G. 1.1.0 deliberately supersedes that
freeze for four modules, and `tests/test_release.py` pins the **current release**
hashes (1.1.2), in literal form and again through `release_manifest.json`.
The security tests were not adjusted to accommodate the change: they pass on
their original assertions.

## What changed in 1.1.1 (M4-022C)

Three release blockers from the independent M4-022B review were reproduced and
corrected:

| Change | Reason |
| --- | --- |
| `engine.py`: port pattern accepts ordinary sentence punctuation (`.`, `,`, `)`) while still rejecting decimal, version, thousands, percent, out-of-range and zero fragments | 1.1.0 rejected `the server port is 8443.`, a documented supported answer shape. |
| `document.py`, `engine.py`: malformed hrefs and unusable link hosts/ports are dropped per link; an unparseable retrieved page is a per-page retrieval error | 1.1.0 translated a page author's broken href into `INVALID_INPUT` and discarded a supported answer. |
| Documentation and docstrings reconciled (test counts, artifact hash, historical user-agent name, `AUTH-REFUSED` wording, release-test docstring) | Published evidence disagreed with the released artifact. |

## Frozen surface

- **Core (pinned in `tests/test_release.py`):** `contracts.py`, `question.py`,
  `document.py`, `model.py`, `fetch.py`, `engine.py`.
- **Product surface:** `__init__.py`, `cli.py`, `demo.py`, `pyproject.toml`,
  `setup.cfg`, `MANIFEST.in`, `LICENSE`, `examples/answer_one.py`.
- Any change to these requires a new version and a new acceptance record.

## Reusable vs demo-only

- **Reusable product:** the `sourcecourt` package, the `sourcecourt ask` CLI,
  and the Python API `RetrievalEngine(HttpFetcher()).answer(question, url)`.
- **Demo-only:** `sourcecourt-demo`. It starts a loopback fixture site and
  drives the real CLI through the documented test/demo fetcher seam. It is
  labelled a demo everywhere and is never presented as proof of the production
  claim.

## Credentials and private infrastructure

None required, embedded, or contacted. The product performs only its own
bounded HTTP/HTTPS retrieval: no third-party APIs, paid or free, no API keys,
no telemetry, no accounts.

## Deliberately unsupported

JavaScript-rendered pages; authenticated or paywalled content; PDF, image,
audio, or video; cross-origin navigation; search-engine discovery; general
question answering; paraphrased or normalised answers; entity linking; receipts
or tamper-evident ledgers (not part of this product line); and any claim of
compatibility with an unpublished official competition grader.

## Independent reproduction

Reproducible from a clone with Python 3.11+ and no network access except the
live commands a user chooses to run. Measured evidence — clean-install results,
live workflow outputs, refusal behaviour, unsafe-destination probes, deadline
measurements, reproducibility checks, and test counts — is in
[`VERIFICATION.md`](VERIFICATION.md).

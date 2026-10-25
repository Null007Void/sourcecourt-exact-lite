# SourceCourt Exact Lite

**Bounded, source-grounded question answering.** You give it one question and
one starting link on a website you choose. It retrieves a small, same-origin
set of pages and returns an answer bound to the exact page it came from — a
value such as `.test` or `8443` when the question asks for one, otherwise the
supporting sentence — with the verbatim quote as evidence. If the pages do not
support an answer, it refuses and says why. It never invents one.

Pure Python standard library. No GPU, no model inference, no third-party
dependencies, no API keys, no network account.

**Version 1.1.2** · MIT · Python 3.11+

## Why this exists

Most "ask a website" tools optimise for always producing an answer. That is the
wrong objective when the answer is supposed to be verifiable. SourceCourt Exact
Lite is built around the opposite constraint: **an answer is only ever emitted
together with exact source evidence, and the product refuses whenever the
evidence is missing, ambiguous, or the retrieval did not genuinely happen.**

It was built for AMD AI League Match 4 (project `amd-match-4`) under a rule the
maintainers still apply: no claim may exceed what the shipped artifact does.

## Status

- **Product:** SourceCourt Exact Lite **1.1.2**. Installable wheel and source
  distribution, warning-strict suite, verified end to end on a clean install.
- **Release:** release-candidate ready for publication. Not published by the
  authors of this repository.
- **Official Match 4 submission contract:** **not public and not verified.**
  No grader, container, model, or ROCm compatibility is claimed, implied, or
  implemented. This repository is the product; it is not a submission adapter.

## What it actually does

- Takes one natural-language question (≤ 500 characters) and one absolute
  `http`/`https` starting URL.
- Fetches that page, then follows up to 2 same-origin hops, visiting at most
  3 pages in total (defaults).
- Splits retrieved text into paragraphs and sentences — a hard-wrapped page is
  one paragraph, not dozens of fragments — and scores sentences
  deterministically against the question.
- Returns **either** an identifier-like value (a domain or TLD such as `.test`,
  a port, a version, a percentage) when the question asks for that kind of
  value and exactly one appears in the supporting passage, **or** the
  supporting sentence verbatim.
- Binds every answer to its page and to the exact quote that supports it.
- Refuses with `UNSUPPORTED` when nothing supports an answer, `AMBIGUOUS` when
  two equally supported passages disagree, and `RETRIEVAL_FAILED` when no page
  could be retrieved for a real reason.

### Answer shapes (the 1.1 contract)

| Question asks for | Answer is |
| --- | --- |
| a domain / TLD / host (`domain`, `host`, `tld`, `suffix`, `extension`) | the value, e.g. `.test`, `docs.example.org` |
| a port | the number, e.g. `8443` (validated 1–65535) |
| a version | the value, e.g. `1.1.0` |
| a percentage | the value, e.g. `99.95%` |
| a date, a count, an amount of money | the supporting sentence (unchanged from 1.0.0) |
| anything else (`who`, `where`, `what …` questions) | the supporting sentence |

Two rules keep this honest:

- A passage with **two different values** of the requested kind is answered
  with the passage itself, not with a coin flip between them.
- A typed question with **no value of the requested kind** anywhere is a
  refusal, not a sentence about the topic. "What is the port?" is never
  answered with a paragraph that merely mentions ports.

Evidence is always the verbatim passage that contains the answer; for a typed
answer the value is a substring of the quoted evidence.

## What it deliberately does not do

- No JavaScript rendering, no browser automation, no headless Chrome.
- No authentication, cookies, sessions, or paywalled content.
- No PDF, image, audio, or video understanding — HTML and plain text only.
- No search-engine discovery. You supply the starting URL; it navigates only
  that origin.
- No generative model in the default configuration. A provider-neutral
  `ModelAdapter` protocol exists for integrators, and any model candidate must
  pass exact source/quote verification before it can be returned.
- No general question answering. If the page does not state the answer, the
  product refuses.

## Install

Requires **Python 3.11+**. No third-party packages.

From the shipped wheel:

```bash
python -m pip install dist/sourcecourt_exact_lite-1.1.2-py3-none-any.whl
```

From a clone (source install):

```bash
python -m pip install .
```

Either install provides two console commands:

| Command | Purpose |
| --- | --- |
| `sourcecourt` | the product CLI |
| `sourcecourt-demo` | offline demo, clearly labelled as a demo |

Uninstalled, the package lives under `src/`, so the interpreter needs that
directory on its import path. Run from the repository root:

```bash
# POSIX shell, Git Bash
PYTHONPATH=src python -m sourcecourt.cli --version

# Windows cmd.exe
set PYTHONPATH=src && python -m sourcecourt.cli --version

# PowerShell
$env:PYTHONPATH="src"; python -m sourcecourt.cli --version
```

Without that setting the command fails with `No module named 'sourcecourt'` —
install the package, or set `PYTHONPATH`, before running it.

## Quickstart

```bash
sourcecourt --version                  # sourcecourt 1.1.2
sourcecourt ask --help
```

Offline self-check (starts a temporary loopback fixture site; no network):

```bash
sourcecourt-demo
```

Real retrieval against a public text page:

```bash
sourcecourt ask "What is the reserved top-level domain for testing?" \
  "https://www.rfc-editor.org/rfc/rfc2606.txt" --json
```

Measured output of that exact command on 1.1.2:

```json
{
  "status": "ANSWERED",
  "answer": ".test",
  "source_url": "https://www.rfc-editor.org/rfc/rfc2606.txt",
  "evidence": [
    {
      "source_url": "https://www.rfc-editor.org/rfc/rfc2606.txt",
      "quote": "\".test\" is recommended for use in testing of current or new DNS related code."
    }
  ],
  "visited_urls": ["https://www.rfc-editor.org/rfc/rfc2606.txt"],
  "diagnostic": null
}
```

Human-readable mode (omit `--json`):

```text
status: ANSWERED
answer: .test
source: https://www.rfc-editor.org/rfc/rfc2606.txt
evidence: ".test" is recommended for use in testing of current or new DNS related code.
```

Refusal on the same page for a question it does not answer:

```text
status: UNSUPPORTED
diagnostic: no retrieved sentence sufficiently supports an answer
```

A typed question with no value on the page refuses with a type-specific reason:

```text
status: UNSUPPORTED
diagnostic: no retrieved passage states a port value that the question asks for
```

Retrieval failure (a page that does not exist) — no answer is produced:

```text
status: RETRIEVAL_FAILED
diagnostic: https://www.rfc-editor.org/rfc/rfc99999999.txt: HTTP 404 retrieval failure
```

Python API:

```python
from sourcecourt import HttpFetcher, RetrievalEngine

engine = RetrievalEngine(HttpFetcher())
result = engine.answer(
    "What is the reserved top-level domain for testing?",
    "https://www.rfc-editor.org/rfc/rfc2606.txt",
)
print(result.status.value)   # ANSWERED
print(result.answer)         # ".test"
print(result.source_url)     # exact page the answer came from
print(result.evidence)       # tuple of Evidence(source_url, quote)
```

## Output record

`--json` prints exactly these fields (no confidence scores, no invented
fields):

| Field | Meaning |
| --- | --- |
| `status` | `ANSWERED`, `UNSUPPORTED`, `AMBIGUOUS`, `RETRIEVAL_FAILED`, `INVALID_INPUT`, or `UNEXPECTED_ERROR` |
| `answer` | the value or supporting sentence; non-null only for `ANSWERED` |
| `source_url` | page the answer came from; non-null only for `ANSWERED` |
| `evidence` | list of `{source_url, quote}`; quotes occur verbatim in that source |
| `visited_urls` | pages actually retrieved |
| `diagnostic` | refusal/failure explanation; `null` when answered |

A typed answer is always a substring of its own evidence quote. There is no
schema identifier, request id, timestamp or reason code in the record; `status`
plus `diagnostic` is the contract (see `docs/LIMITATIONS.md`).

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | `ANSWERED`, or an explicit refusal (`UNSUPPORTED`, `AMBIGUOUS`) — the product worked |
| `2` | `RETRIEVAL_FAILED`, `INVALID_INPUT`, unexpected error, or usage error (argparse) |

There is no exit code `1`. `sourcecourt --help` prints the same table, and the
suite asserts that the help text, the module docstring and the observed process
exit codes agree.

## Safety model

The fetcher is the security boundary, and it fails closed:

- Only absolute `http`/`https` URLs. Credentialed URLs (`user:pass@host`) are
  rejected, as are `file:`, `ftp:`, and every other scheme.
- Every destination — the start URL **and every redirect hop** — must resolve
  to public Internet addresses. Loopback, private, link-local, multicast,
  reserved, unspecified, IPv6 loopback, IPv4-mapped loopback, and
  metadata-service addresses are refused before a connection is made.
- Every DNS answer for a host must be public. The connection is pinned to the
  validated address; there is no re-resolution at connect time.
- HTTPS uses the original hostname for SNI and standard certificate and
  hostname verification.
- Environment/system proxies are ignored; requests go direct.
- One monotonic deadline covers DNS, connect, TLS, redirects, response
  headers, and body reads. Expiry is a `RETRIEVAL_FAILED`, never a partial
  answer.
- Bounded resources: 1,000,000 bytes per response, 3 redirects, 2048-character
  URLs, `text/html` or `text/plain` only, strict decoding.

The demo and the test fixtures reach loopback through an explicit,
non-default fetcher mode (`HttpFetcher.for_local_fixture_tests`). The
production path cannot.

## Tests

```bash
python -m unittest discover -s tests -v
python -W error -m unittest discover -s tests -v     # warning-strict
```

The suite covers the retrieval/security core (SSRF destination policy, DNS
mixed-answer rejection, pinned connections, hostname verification, redirect
revalidation, proxy isolation, deadlines across slow headers and bodies,
size/type/encoding limits), engine extraction and ambiguity, text segmentation
including hard-wrapped and dotted-token cases, typed value answers across four
value kinds, CLI exit codes and help text, packaging, and release integrity
(artifact hashes, module inventory, private-content scan with a vacuity
control). The exact count is recorded in `docs/RELEASE_MANIFEST.md` and
`release_manifest.json`, where a test derives it from the modules themselves.

No test is skipped, marked expected-failure, or conditioned on an environment
variable.

## Repository layout

```text
src/sourcecourt/       the package (9 modules)
tests/                 the suite
examples/              one runnable example
dist/                  release artifacts (wheel + sdist) with recorded hashes
docs/                  acceptance record, verification evidence, provenance, limitations
pyproject.toml         package metadata and console entry points
release_manifest.json  machine-readable release inventory (hashes, counts)
```

## Known limitations

Deterministic extraction, not semantic QA: a page without a clean answer
sentence yields `UNSUPPORTED` or `AMBIGUOUS` by design. Typed answers cover
four value kinds only. No JavaScript, cookies, PDF, gzip, or HTTP/2. Sites that
block non-browser clients fail honestly. The full list is in
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Documentation

| File | Contents |
| --- | --- |
| [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md) | what is accepted, and what was explicitly not claimed |
| [`docs/RELEASE_MANIFEST.md`](docs/RELEASE_MANIFEST.md) | artifact hashes, build and reproduction instructions |
| [`docs/VERIFICATION.md`](docs/VERIFICATION.md) | clean-install, product and security evidence with commands |
| [`docs/PROVENANCE.md`](docs/PROVENANCE.md) | source lineage and custody record |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | honest boundaries and known defects |

## License

MIT. See [`LICENSE`](LICENSE).

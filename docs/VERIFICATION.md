# Verification — SourceCourt Exact Lite 1.1.2

All results below were executed on 2026-10-24 against the source and artifacts
identified in [`RELEASE_MANIFEST.md`](RELEASE_MANIFEST.md). Environment:
Windows, CPython 3.11.16, isolated virtual environments in empty temporary
directories outside the repository. No GPU, no paid service, no external
account, no credentials.

Outbound network for the 1.1.0 pass: nine bounded HTTPS requests, all issued by
the product itself against `www.rfc-editor.org`. The 1.1.1 correction pass added
no live requests beyond one re-run of the documented command to confirm the
unchanged answer path. Everything else ran offline.

## 1. Baseline audit (before any change)

| Check | Result |
| --- | --- |
| Private repository HEAD / tree at start | `0637ae1ee21e0a972818e33defff493023fbf86f` / `29f64c764052b261410edcceb965a90b1ce9e9d1` |
| Public candidate at start | `f64a22fc1ca9350038838077b8447147b97b14bb`, tree `85d748c0c5ff6d87fe49a078ac67ea21bc83cc65` |
| Worktrees | clean, no remotes, no tags |
| 1.1.0 artifacts | wheel `49976a81…145bc`, sdist `4650a02e…8a553` — preserved unchanged in custody |

## 2. The 1.1.0 answer defect (context, fixed in 1.1.0)

Reproduced against the 1.0.0 wheel with the published question: it returned
`"domain names are reserved for use in private testing, as examples in"`, a
physical line of the RFC cut mid-sentence. 1.1.0 fixed both causes (line-based
segmentation and keyword-only passage selection) and returns `.test` with the
verbatim supporting sentence. That behaviour is unchanged in 1.1.1.

## 3. M4-022C corrections

### 3.1 Port followed by ordinary punctuation (B1)

The 1.1.0 port pattern used `(?![\d.,%])`, which rejected a port followed by `.`
or `,`. Measured on the 1.1.0 wheel and re-measured on 1.1.1:

| Fetched page text | 1.1.0 | 1.1.1 |
| --- | --- | --- |
| `The server port is 8443` | ANSWERED `8443` | ANSWERED `8443` |
| `The server port is 8443.` | UNSUPPORTED | **ANSWERED `8443`** |
| `The server port is 8443, and connections are encrypted.` | UNSUPPORTED | **ANSWERED `8443`** |
| `The server port is 8443; it is used for TLS.` | ANSWERED `8443` | ANSWERED `8443` |
| `The server port is 8443)` | UNSUPPORTED | **ANSWERED `8443`** |

Still refused, so no fragment is ever accepted as a port: `8443.5`, `1,000`,
`8443%`, `1.1.0`, `99999999`, `0`, `65536`. The number must not be preceded by a
digit, dot or comma, must not be followed by a digit or percent sign, and must
not be followed by a decimal continuation or a thousands group; ordinary
sentence punctuation is a legal boundary. Range validation (1–65535) is
unchanged.

### 3.2 Malformed retrieved link (B2)

Measured on the 1.1.0 wheel with a valid start URL and the page
`<a href="http://[bad">broken</a><p>The server port is 8443 and accepts requests.</p>`:
result `INVALID_INPUT` with `diagnostic='Invalid IPv6 URL'` — the page author's
broken href was reported as the user's input error and a supported answer was
lost.

1.1.1 fixes this at three levels:

- `document.py` parses each href inside `try/except (ValueError, UnicodeError)`;
  an unusable link is dropped and the page text plus every other link survive.
- `engine.py` skips a retrieved link whose host or port cannot be parsed,
  instead of letting it abort navigation.
- `engine.py` treats an unparseable retrieved page as a retrieval problem for
  that page rather than a user-input error.

Measured after the fix: the review's fixture returns `ANSWERED` / `8443`; the
same page with an unusable port link (`http://example.test:99999/x`) returns
`ANSWERED` / `8443`; a malformed **user** URL (`http://[bad`) is still refused
(`RETRIEVAL_FAILED`, no answer). URL security enforcement is untouched: the
fetcher still refuses every non-public destination and every credentialled or
non-HTTP(S) URL before a connection is made.

### 3.3 Documentation reconciliation (B3)

| Reported inconsistency | Resolution |
| --- | --- |
| Test counts "74 shipped + 9 integrity" in `PROVENANCE.md` | Corrected to the measured 83 shipped + 11 integrity = 94, derived from the test modules. |
| Stale sdist hash `670b9a00…` in `VERIFICATION.md` | Removed; this document and the manifest now carry the shipped hash in the manifest. |
| Historical `User-Agent` typo `SourceCourt-Eth-Lite/0.1` | Corrected to `SourceCourt-Exact-Lite/0.1`. |
| `tests/test_release.py` docstring said "certified 1.0.0 artifact" | Now describes the artifacts the test actually pins. |
| `__init__.py` docstring referenced `AUTH-REFUSED` | Now names the real statuses, `UNSUPPORTED` and `AMBIGUOUS`. |

## 3.4 M4-022E corrections (1.1.2)

| Finding | Reproduced | Correction |
| --- | --- | --- |
| P1 private identifiers in public scanners | 10 occurrences of internal agent/workspace names in `tests/test_release.py` and `tools/build_release.py` | Both scanners now carry only generic rules (user-profile paths, credential shapes). No file is exempt — the scanners scan themselves. Private terms reach an audit from outside the repository through `SOURCECOURT_PRIVATE_TERMS`. |
| P2 README installed a missing wheel | README named `…1.1.0….whl` while `dist/` shipped a different version | The example names the shipped artifact, and a test parses the README command and asserts the file exists. |
| P3 no-install command failed | `python -m sourcecourt.cli --version` raised `ModuleNotFoundError` in an uninstalled checkout | README documents `PYTHONPATH=src` for POSIX, cmd.exe and PowerShell, states the failure mode, and a test runs the documented invocation in a subprocess. |
| P4 negative port answered | `The server port is -8443.` → ANSWERED `8443` (also for U+2212) | The port rule rejects a sign attached to the number: `-8443`, `−8443`, `+8443` and `-1` refuse; punctuation, decimal, thousands, version, zero and range rules are unchanged. |
| P5 acceptance-record drift | `ACCEPTANCE.md` claimed the test pins 1.1.0 hashes | Now describes the current release identity, re-derived from the manifest on every run. |

## 4. Build integrity

```text
$ python tools/build_release.py
98984b22f2df9f94d6da7102d4fd1e8fe553725ff940ad1881464854f08dddc6    26757  sourcecourt_exact_lite-1.1.2-py3-none-any.whl
eb69500817e92f12d8a03df8e2588b86199613aa8a1d6c001d9068f7901dfb92    38938  sourcecourt_exact_lite-1.1.2.tar.gz
version 1.1.2: verified 2 artifacts
```

The build is offline (`PIP_NO_INDEX=1`, `--no-build-isolation`), pins
`SOURCE_DATE_EPOCH`, normalises the sdist, and audits both archives (nine
modules, 15 wheel entries, no bytecode, no private-marker string). A second
independent build into a different directory produced byte-identical files.

Cross-toolchain byte identity is **not** claimed: the independent 1.1.0 review
measured that a different setuptools version produces different packaging
metadata. Reproduction is guaranteed only with the recorded toolchain
(CPython 3.11.16, setuptools 79.0.1).

## 5. Clean-room installs

Fresh virtual environments, empty directories outside any repository.

| Check | Result |
| --- | --- |
| wheel install (`--no-index`) | `Successfully installed sourcecourt-exact-lite-1.1.2` |
| `sourcecourt --version` | `sourcecourt 1.1.2`, exit 0 |
| `sourcecourt ask --help` | usage, answer-shape note, exit-code table, exit 0 |
| `sourcecourt-demo` | `DEMO COMPLETE: ANSWERED end-to-end confirmed`, exit 0 |
| metadata | version 1.1.2, no `Requires-Dist` |
| source install (`--no-index --no-build-isolation .`) | installed, version 1.1.1, import from site-packages |
| live grounded answer | `ANSWERED`, `.test`, exit 0 |
| unsupported question (live) | `UNSUPPORTED`, exit 0 |
| typed question with no such value (live) | `UNSUPPORTED`, exit 0 |
| retrieval failure (live 404) | `RETRIEVAL_FAILED`, exit 2 |
| usage error | exit 2 |

Repeated from a fresh clone of the public snapshot with `core.autocrlf=true` in
effect: all manifest-pinned files matched, so the pinned hashes survive a normal
Windows clone.

## 6. Security regression

The 23 fetcher tests are unchanged and green: production fetcher blocking
non-public destinations, mixed public/private DNS answers, pinned connections
without re-resolution, HTTPS hostname verification, redirect revalidation and
URL-length limits, proxy isolation, the overall deadline across DNS, redirect
chains, slow trickling headers and slow streaming bodies, socket-close-once
semantics, and size/type/encoding refusals.

Unsafe-destination probe against the installed wheel, with `socket.connect` and
`socket.create_connection` patched to deny:

```text
targets probed: 14
failures: 0
network attempts observed: 0
```

Refused: `127.0.0.1`, `127.1.2.3`, `localhost`, `10.0.0.1`, `192.168.1.1`,
`172.16.0.1`, `169.254.169.254`, `0.0.0.0`, `[::1]`, `[::ffff:127.0.0.1]`,
`user:pass@` URLs, `file:`, `ftp:`, and an unresolvable internal name.

## 7. Test suite

```text
python -m unittest discover -s tests -v            # 99 tests
python -W error -m unittest discover -s tests -v   # warning-strict, 99 tests
python -m compileall -q src tests examples         # exit 0
```

Composition: 83 tests shipped in the sdist (45 retrieval/security core, 10
product-mode, 4 segmentation, 19 typed-value including the port-boundary matrix,
2 link-robustness, 3 engine robustness) plus 11 release-integrity tests. No test
is skipped, expected-failure, or environment-gated.

### 7.1 Mutation controls

Run on a full copy of the tree with the manifest regenerated after each
mutation, so only behavioural failures remain visible:

| Mutation | Result |
| --- | --- |
| Baseline copy | 99 tests, OK |
| Drop the relation-phrase bonus | failures including the near-miss decoy test |
| Restore newline-as-paragraph (the 1.0.0 defect) | failures including both segmentation tests |
| Plant a private owner path in `README.md` | the private-content scan fails |
| Restored copy | 99 tests, OK |

## 8. Bounded observation carried forward

`EngineLimits(max_pages=3)` bounds **successfully retrieved documents**, not
outbound fetch attempts: a page with several relevant-but-broken links can
produce more attempts than retrieved pages. The bound remains finite
(`max_links_per_page` × depth), and the distinction is now stated in
[`LIMITATIONS.md`](LIMITATIONS.md) rather than left implicit.

## 9. Not done

- No publication, push, remote, tag, release, or competition submission.
- No GPU, ROCm, AMD inference, paid API, or external model.
- No independent reviewer verdict for 1.1.1: this is the builder's evidence. The
  public snapshot identifies the exact commit for an independent re-review.

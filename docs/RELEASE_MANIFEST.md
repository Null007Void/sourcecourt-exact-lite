# Release manifest — SourceCourt Exact Lite 1.1.2

The machine-readable form of this manifest is [`../release_manifest.json`](../release_manifest.json);
`tests/test_release.py` verifies every entry in it against the tree on every
test run, and fails — it never skips — if a declared file is missing or has
drifted.

## Artifacts

| Artifact | SHA-256 | Size |
| --- | --- | --- |
| `dist/sourcecourt_exact_lite-1.1.2-py3-none-any.whl` | `98984b22f2df9f94d6da7102d4fd1e8fe553725ff940ad1881464854f08dddc6` | 26,757 B |
| `dist/sourcecourt_exact_lite-1.1.2.tar.gz` | `eb69500817e92f12d8a03df8e2588b86199613aa8a1d6c001d9068f7901dfb92` | 38,938 B |

The wheel contains exactly 15 entries: the nine package modules, `METADATA`,
`WHEEL`, `entry_points.txt`, `top_level.txt`, `licenses/LICENSE`, and `RECORD`.
Zero bytecode entries; `RECORD` hashes are consistent with the member contents.
The sdist contains the package, the shipped test suite (the repository-only
integrity test is excluded), the example, `LICENSE`, `README.md` and packaging
metadata — no bytecode, no build records.

Console entry points:

```text
sourcecourt       = sourcecourt.cli:main
sourcecourt-demo  = sourcecourt.demo:main
```

## Build and reproducibility

```bash
python tools/build_release.py           # builds into dist/ and audits both archives
```

Offline (`PIP_NO_INDEX=1`, `--no-build-isolation`), with
`SOURCE_DATE_EPOCH=1792800000` (2026-10-24T00:00:00Z) and a normalised sdist
(sorted members, fixed uid/gid/mtime, `gzip` mtime 0). The script audits both
archives: exactly nine modules in the wheel, 15 wheel entries, no bytecode, no
private-marker string in any text member.

Measured: two consecutive builds from the same tree produced **byte-identical**
artifacts. That reproducibility is **toolchain-scoped** — CPython 3.11.16 with
setuptools 79.0.1. The independent 1.1.0 review established that a different
setuptools version changes packaging metadata, so cross-toolchain byte identity
is not claimed.

## Package modules (1.1.2 identity)

| Module | SHA-256 | Size |
| --- | --- | --- |
| `src/sourcecourt/__init__.py` | `75d822c6c73efd4fbb86edb9f3fc9152fa674513146b75b74d7430e04218ab2e` | 1,597 B |
| `src/sourcecourt/cli.py` | `b96eaa8f52b0f53e01f6a745ab96ae927968b1e45681c8cbdb7477c165daa246` | 4,447 B |
| `src/sourcecourt/contracts.py` | `65e902eb7c4fa57f4f08186e60e304dbcaa227321b10c03db301d5b28faa37c4` | 1,405 B |
| `src/sourcecourt/demo.py` | `140c4f5d8eb43a4618920a52448e25bd2700449f15ce42e95ac8d8aa86043cbd` | 3,720 B |
| `src/sourcecourt/document.py` | `a573ac3b9da187974b36c5e1a95d0e497144444444b12193c67d34275a748fc3` | 5,683 B |
| `src/sourcecourt/engine.py` | `c481bcfd14909075d941c336f143e24c34a41a7acb8c7512b285e30d819778f7` | 16,425 B |
| `src/sourcecourt/fetch.py` | `d92f04983796f22c5dfe62d9f9fb5aa1e4b1d7bed26e8134b0fd0d70ccf6751e` | 15,973 B |
| `src/sourcecourt/model.py` | `4cbeb0ff03750e3e10e446669c63514cac334ad30504a41b0efb90f55cdc341d` | 962 B |
| `src/sourcecourt/question.py` | `27fcc8b3f670c268c739eceb7a0063d5ea4f8112a01b32fcff96ae123724f569` | 4,389 B |

The six core modules are additionally pinned as literals inside
`tests/test_release.py`, so a silent edit fails the suite even if the manifest is
regenerated.

## Test inventory

- **Shipped in the sdist:** 85 tests — 45 retrieval/security core, 10
  product-mode, 4 segmentation, 21 typed-value (port-boundary and sign
  matrices), 2 link-robustness, 3 engine robustness.
- **Repository total:** 99 tests — the same 85 plus 14 release-integrity tests in
  `tests/test_release.py` (manifest identity, module inventory, version
  agreement, derived test counts, wheel cleanliness and payload equality,
  user-agent/version agreement, help-text and README exit-code agreement,
  private-content scan, and a vacuity control for that scan).

`release_manifest.json` declares these counts and the test derives them again
from the test modules. Counts in prose have drifted twice during review
(74+9 and later 83+11); both are recorded in the project ledger, which is why
the derived value, not the sentence, is the authority.

```bash
python -m unittest discover -s tests -v          # 99 tests
python -W error -m unittest discover -s tests -v # warning-strict, same 99
python -m compileall -q src tests examples
```

## Superseded artifacts (never published)

| Version | Wheel SHA-256 | Sdist SHA-256 | State |
| --- | --- | --- | --- |
| 1.0.0 | `769e8969…7814` (19,813 B) | `38e7905a…d757` (60,847 B) | custody only |
| 1.1.0 | `49976a81…145bc` (25,884 B) | `4650a02e…8a553` (36,617 B) | custody only |
| 1.1.1 | `d8164d96…e66e1` (26,534 B) | `d72a2ae2…65ee` (38,365 B) | custody only, superseded by 1.1.2 |

Both older sets are preserved unmodified as accepted history. The 1.0.0 sdist is
never published: it embeds the original private build lane's acceptance records
verbatim.

## Freeze statement

The 1.1.2 core and product surface are frozen at the commit carrying this
manifest. Any change to a module requires a new version, fresh artifacts and a
new acceptance record.

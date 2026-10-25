"""Generate release_manifest.json for the public SourceCourt Exact Lite tree.

Run from the repository root:

    python tools/generate_release_manifest.py

The manifest records the exact identity of every file that ships in the
repository, the certified wheel, and the declared test counts. Test counts are
derived from the test modules themselves, never typed twice:
`tests/test_release.py` recomputes them and fails on disagreement.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_FILES = [
    ".gitattributes",
    ".gitignore",
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "pyproject.toml",
    "setup.cfg",
    "examples/answer_one.py",
    "docs/ACCEPTANCE.md",
    "docs/LIMITATIONS.md",
    "docs/PROVENANCE.md",
    "docs/RELEASE_MANIFEST.md",
    "docs/VERIFICATION.md",
    "tools/generate_release_manifest.py",
    "tools/build_release.py",
]

SHIPPED_TESTS = [
    "test_contract.py",
    "test_document.py",
    "test_engine.py",
    "test_fetch.py",
    "test_integration_http.py",
    "test_package.py",
    "test_product_modes.py",
    "test_value_answers.py",
]
REPO_ONLY_TESTS = ["test_release.py"]

ARTIFACTS = [
    "dist/sourcecourt_exact_lite-1.1.2-py3-none-any.whl",
    "dist/sourcecourt_exact_lite-1.1.2.tar.gz",
]

CERTIFIED_SDIST = {
    "superseded": {
        "filename": "sourcecourt_exact_lite-1.0.0.tar.gz",
        "sha256": "38e7905af272d2b97069e9c27596651b2b5e2ad1e1156920c2a2b8322350d757",
        "size": 60847,
        "published": False,
        "reason": (
            "The 1.0.0 source distribution embeds the original private build lane's "
            "acceptance records verbatim and is never published. The 1.1.0 sdist is "
            "built from this public tree and is audited by tools/build_release.py."
        ),
    },
}

_TEST_DEF = re.compile(r"^\s*def test_", re.MULTILINE)


def entry(rel: str) -> dict:
    path = ROOT / rel
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def defined_tests(rel: str) -> int:
    return len(_TEST_DEF.findall((ROOT / rel).read_text(encoding="utf-8")))


def build() -> dict:
    modules = sorted(p.name for p in (ROOT / "src" / "sourcecourt").glob("*.py"))
    shipped = {f"tests/{n}": entry(f"tests/{n}") for n in SHIPPED_TESTS}
    repo_only = {f"tests/{n}": entry(f"tests/{n}") for n in REPO_ONLY_TESTS}

    shipped_count = sum(defined_tests(rel) for rel in shipped)
    repo_count = shipped_count + sum(defined_tests(rel) for rel in repo_only)

    return {
        "schema": "sourcecourt-exact-lite-release-manifest",
        "schema_version": 1,
        "name": "sourcecourt-exact-lite",
        "version": "1.1.2",
        "license": "MIT",
        "python_requires": ">=3.11",
        "package_modules": {
            f"src/sourcecourt/{n}": entry(f"src/sourcecourt/{n}") for n in modules
        },
        "tests": {
            "shipped_in_sdist": shipped,
            "repository_only": repo_only,
            "counts": {
                "shipped_sdist_tests": shipped_count,
                "repository_total_tests": repo_count,
            },
        },
        "artifacts": {rel: entry(rel) for rel in ARTIFACTS},
        "certified_source_distribution": CERTIFIED_SDIST,
        "public_files": {rel: entry(rel) for rel in PUBLIC_FILES},
    }


def main() -> int:
    manifest = build()
    out = ROOT / "release_manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(
        "modules: {m}  shipped tests: {s}  repository tests: {r}".format(
            m=len(manifest["package_modules"]),
            s=manifest["tests"]["counts"]["shipped_sdist_tests"],
            r=manifest["tests"]["counts"]["repository_total_tests"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

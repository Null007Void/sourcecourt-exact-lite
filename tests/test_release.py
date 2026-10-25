"""Release-integrity tests for the public SourceCourt Exact Lite repository.

These tests bind the repository to the release artifacts it ships:

* every declared file exists and has its recorded SHA-256 (missing file = FAIL,
  never a skip);
* the package module inventory is exactly the nine shipped modules;
* the declared versions agree (`pyproject.toml`, `sourcecourt.__version__`,
  release manifest);
* the shipped wheel is clean (no bytecode), self-consistent per its RECORD, and
  byte-identical to `src/sourcecourt/` for every module;
* no private path, internal identifier, or credential appears in any shipped
  text file;
* the declared test totals match the tests actually defined in `tests/`.

The scan is deliberately exact rather than heuristic: a new file must be added
to `release_manifest.json` (via `tools/generate_release_manifest.py`), which
forces the inventory to be refreshed instead of silently drifting.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import tomllib
import unittest
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST_PATH = _ROOT / "release_manifest.json"

if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import sourcecourt  # noqa: E402

# Public scans use GENERIC patterns only. Private identifiers (agent names,
# workspace labels, operator paths) are never listed in publishable source: a
# public file that enumerates them leaks exactly what it is meant to catch.
# Private audits pass their own terms through SOURCECOURT_PRIVATE_TERMS, which
# keeps that list outside the repository.
_PRIVATE_PATH_PATTERNS = (
    (r"[A-Za-z]:[\/]Users[\/]", "windows user-profile path"),
    (r"[A-Za-z]:[\/]Documents and Settings[\/]", "legacy windows user path"),
    (r"(?<![\w.])/(?:home|Users)/[A-Za-z0-9._-]+/", "posix user-profile path"),
    (r"[\/](?:\.ssh|\.aws|\.gnupg)[\/]", "credential directory"),
)

_CREDENTIAL_PATTERNS = (
    (r"ghp_[A-Za-z0-9]{20,}", "github token"),
    (r"sk-[A-Za-z0-9]{20,}", "api key"),
    (r"AKIA[0-9A-Z]{16}", "aws access key id"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
    # Split so the rule text does not match itself; the compiled pattern still
    # matches the credential name.
    (r"(?i)aws_secret" + "_access_key", "aws secret key name"),
)

_TEXT_SCAN_EXTRA = (
    "README.md",
    "release_manifest.json",
    ".gitignore",
    "tools/generate_release_manifest.py",
)

def _extra_terms() -> tuple[str, ...]:
    """Private terms supplied by an out-of-tree audit (never committed)."""
    raw = os.environ.get("SOURCECOURT_PRIVATE_TERMS", "")
    return tuple(term.strip() for term in raw.split(",") if term.strip())


def _scan_text(rel: str, text: str) -> list[str]:
    """Generic private-path and credential findings for one file.

    No file is exempt: every published file, including this scanner and the
    build script, is scanned with the same rules.
    """
    findings: list[str] = []
    for pattern, label in _PRIVATE_PATH_PATTERNS:
        if re.search(pattern, text):
            findings.append(f"{label} in {rel}")
    for pattern, label in _CREDENTIAL_PATTERNS:
        if re.search(pattern, text):
            findings.append(f"{label} in {rel}")
    for term in _extra_terms():
        if term in text:
            findings.append(f"supplied private term in {rel}")
    return findings


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest() -> dict:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _declared_files(manifest: dict) -> dict[str, dict]:
    declared: dict[str, dict] = {}
    declared.update(manifest["package_modules"])
    declared.update(manifest["tests"]["shipped_in_sdist"])
    declared.update(manifest["tests"]["repository_only"])
    declared.update(manifest["artifacts"])
    declared.update(manifest["public_files"])
    return declared


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(
            _MANIFEST_PATH.is_file(),
            "release_manifest.json is required; generate it with "
            "tools/generate_release_manifest.py",
        )
        self.manifest = _load_manifest()

    def test_manifest_schema_version_and_identity(self) -> None:
        self.assertEqual(
            self.manifest["schema"], "sourcecourt-exact-lite-release-manifest"
        )
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(self.manifest["name"], "sourcecourt-exact-lite")
        self.assertEqual(self.manifest["version"], "1.1.2")
        self.assertEqual(self.manifest["license"], "MIT")
        self.assertEqual(self.manifest["version"], sourcecourt.__version__)

    def test_pyproject_version_matches_package_version(self) -> None:
        project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["name"], "sourcecourt-exact-lite")
        self.assertEqual(project["project"]["version"], sourcecourt.__version__)
        self.assertEqual(project["project"]["dependencies"], [])
        self.assertEqual(
            project["project"]["scripts"],
            {
                "sourcecourt": "sourcecourt.cli:main",
                "sourcecourt-demo": "sourcecourt.demo:main",
            },
        )

    def test_every_declared_file_exists_with_recorded_hash(self) -> None:
        declared = _declared_files(self.manifest)
        self.assertGreaterEqual(
            len(declared), 20, "manifest inventory is implausibly small"
        )
        for rel, meta in declared.items():
            with self.subTest(path=rel):
                path = _ROOT / rel
                self.assertTrue(path.is_file(), f"required file missing: {rel}")
                self.assertEqual(
                    _sha256(path), meta["sha256"], f"content drifted: {rel}"
                )
                self.assertEqual(path.stat().st_size, meta["size"], f"size drifted: {rel}")

    def test_package_module_inventory_is_exactly_the_shipped_set(self) -> None:
        on_disk = {p.name for p in (_ROOT / "src" / "sourcecourt").glob("*.py")}
        declared = {
            Path(rel).name
            for rel in self.manifest["package_modules"]
            if rel.startswith("src/sourcecourt/")
        }
        self.assertEqual(on_disk, declared)
        self.assertEqual(len(declared), 9)

    def test_core_modules_keep_the_frozen_certificate(self) -> None:
        # 1.1.0 identity. The 1.0.0 core was byte-frozen at M4-019G; 1.1.0
        # deliberately changes document.py (segmentation), engine.py (typed
        # values), question.py (value lexicon) and fetch.py (user agent), and
        # records fresh hashes here. tests/test_fetch.py still pins the accepted
        # security behaviour, which is unchanged.
        frozen = {
            "contracts.py": "65e902eb7c4fa57f4f08186e60e304dbcaa227321b10c03db301d5b28faa37c4",
            "question.py": "27fcc8b3f670c268c739eceb7a0063d5ea4f8112a01b32fcff96ae123724f569",
            "document.py": "a573ac3b9da187974b36c5e1a95d0e497144444444b12193c67d34275a748fc3",
            "model.py": "4cbeb0ff03750e3e10e446669c63514cac334ad30504a41b0efb90f55cdc341d",
            "fetch.py": "d92f04983796f22c5dfe62d9f9fb5aa1e4b1d7bed26e8134b0fd0d70ccf6751e",
            "engine.py": "c481bcfd14909075d941c336f143e24c34a41a7acb8c7512b285e30d819778f7",
        }
        for name, digest in frozen.items():
            with self.subTest(module=name):
                self.assertEqual(
                    _sha256(_ROOT / "src" / "sourcecourt" / name),
                    digest,
                    f"frozen core module changed: {name}",
                )

    def test_declared_test_totals_match_defined_tests(self) -> None:
        shipped = self.manifest["tests"]["shipped_in_sdist"]
        repo_only = self.manifest["tests"]["repository_only"]
        pattern = re.compile(r"^\s*def test_", re.MULTILINE)

        shipped_defined = 0
        for rel in shipped:
            shipped_defined += len(pattern.findall((_ROOT / rel).read_text(encoding="utf-8")))
        repo_defined = 0
        for rel in repo_only:
            repo_defined += len(pattern.findall((_ROOT / rel).read_text(encoding="utf-8")))

        counts = self.manifest["tests"]["counts"]
        self.assertEqual(counts["shipped_sdist_tests"], shipped_defined)
        self.assertEqual(counts["repository_total_tests"], shipped_defined + repo_defined)

        on_disk = {p.name for p in (_ROOT / "tests").glob("test_*.py")}
        declared = {Path(rel).name for rel in list(shipped) + list(repo_only)}
        self.assertEqual(on_disk, declared, "test inventory drifted from the manifest")

    def test_shipped_wheel_is_clean_and_self_consistent(self) -> None:
        wheel_rel = "dist/sourcecourt_exact_lite-1.1.2-py3-none-any.whl"
        self.assertIn(wheel_rel, self.manifest["artifacts"])
        with zipfile.ZipFile(_ROOT / wheel_rel) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), 15)
            self.assertFalse([n for n in names if "__pycache__" in n or n.endswith(".pyc")])
            modules = sorted(n for n in names if n.startswith("sourcecourt/"))
            self.assertEqual(
                modules,
                [
                    "sourcecourt/__init__.py",
                    "sourcecourt/cli.py",
                    "sourcecourt/contracts.py",
                    "sourcecourt/demo.py",
                    "sourcecourt/document.py",
                    "sourcecourt/engine.py",
                    "sourcecourt/fetch.py",
                    "sourcecourt/model.py",
                    "sourcecourt/question.py",
                ],
            )
            for name in modules:
                with self.subTest(module=name):
                    self.assertEqual(
                        archive.read(name),
                        (_ROOT / "src" / name).read_bytes(),
                        f"wheel payload differs from source: {name}",
                    )

            record_name = "sourcecourt_exact_lite-1.1.2.dist-info/RECORD"
            record = archive.read(record_name).decode("utf-8")
            recorded: dict[str, tuple[str, int]] = {}
            for line in record.splitlines():
                if not line.strip():
                    continue
                path, digest, size = line.split(",")
                recorded[path] = (digest, int(size) if size else 0)
            self.assertEqual(set(recorded), set(names))
            for name in names:
                if name == record_name:
                    self.assertEqual(recorded[name], ("", 0))
                    continue
                with self.subTest(record=name):
                    payload = archive.read(name)
                    digest_b64 = (
                        base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
                        .decode("ascii")
                        .rstrip("=")
                    )
                    self.assertEqual(recorded[name], (f"sha256={digest_b64}", len(payload)))

    def test_user_agent_carries_package_version(self) -> None:
        from sourcecourt import fetch as fetch_module

        self.assertEqual(
            fetch_module._user_agent(), f"SourceCourt-Exact-Lite/{sourcecourt.__version__}"
        )

    def test_help_text_and_module_docstring_agree_on_exit_codes(self) -> None:
        import contextlib
        import io

        from sourcecourt import cli as cli_module

        self.assertIn("There is no exit code 1", cli_module.__doc__ or "")
        self.assertNotIn("_USAGE_CODE", (_ROOT / "src/sourcecourt/cli.py").read_text(encoding="utf-8"))

        parser = cli_module.build_parser()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            help_text = parser.format_help()
        ask_help = parser._subparsers._group_actions[0].choices["ask"].format_help()
        for text in (buffer.getvalue() or help_text, ask_help):
            self.assertIn("0  ANSWERED", text)
            self.assertIn("2  RETRIEVAL_FAILED", text)
        self.assertIn("There is no exit code `1`", (_ROOT / "README.md").read_text(encoding="utf-8"))

    def test_readme_install_command_references_a_shipped_artifact(self) -> None:
        # A version in prose is not evidence; the documented path must exist.
        readme = (_ROOT / "README.md").read_text(encoding="utf-8")
        commands = re.findall(r"pip install (dist/[A-Za-z0-9._-]+\.whl)", readme)
        self.assertTrue(commands, "README documents no wheel install command")
        for rel in commands:
            with self.subTest(artifact=rel):
                path = _ROOT / rel
                self.assertTrue(path.is_file(), f"README installs a missing file: {rel}")
                self.assertIn(sourcecourt.__version__, path.name)

    def test_documented_pythonpath_command_runs(self) -> None:
        # The README tells an uninstalled user to run the CLI with src on the
        # import path. Run exactly that, in a subprocess, from a neutral cwd.
        import subprocess
        import tempfile

        env = dict(os.environ)
        env["PYTHONPATH"] = str(_ROOT / "src")
        env.pop("PYTHONHOME", None)
        with tempfile.TemporaryDirectory() as cwd:
            proc = subprocess.run(
                [sys.executable, "-m", "sourcecourt.cli", "--version"],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f"sourcecourt {sourcecourt.__version__}", proc.stdout)

    def test_no_private_paths_or_credentials_in_shipped_text(self) -> None:
        manifest = self.manifest
        text_files: list[str] = list(manifest["package_modules"])
        text_files += list(manifest["tests"]["shipped_in_sdist"])
        text_files += list(manifest["tests"]["repository_only"])
        text_files += list(manifest["public_files"])
        text_files += list(_TEXT_SCAN_EXTRA)

        checked = 0
        findings: list[str] = []
        for rel in sorted(set(text_files)):
            path = _ROOT / rel
            self.assertTrue(path.is_file(), f"required text file missing: {rel}")
            findings.extend(_scan_text(rel, path.read_text(encoding="utf-8")))
            checked += 1

        self.assertGreaterEqual(checked, 25, "text scan coverage is implausibly small")
        self.assertEqual(findings, [], "private content found in shipped files")

    def test_private_content_scan_actually_detects_a_planted_marker(self) -> None:
        # Vacuity control: the scan above must be able to fail. If this control
        # ever passes with no finding, the real scan is vacuous.
        # Assembled at runtime so this control does not itself contain the
        # pattern it is testing for.
        planted = "workspace: " + "C" + ":" + "/" + "Users/someone/private/project"
        self.assertTrue(_scan_text("planted.txt", planted))
        self.assertEqual(_scan_text("clean.txt", "nothing private here"), [])

    def test_scanner_files_are_scanned_like_every_other_file(self) -> None:
        # No file is exempt: the scanner and the build script are in the
        # inventory and take part in the same scan.
        declared = _declared_files(self.manifest)
        for rel in ("tests/test_release.py", "tools/build_release.py"):
            with self.subTest(path=rel):
                self.assertIn(rel, declared)
                self.assertEqual(
                    _scan_text(rel, (_ROOT / rel).read_text(encoding="utf-8")), []
                )


if __name__ == "__main__":
    unittest.main()

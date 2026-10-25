"""Build the release artifacts (wheel + sdist) offline and verify them.

Usage:
    python tools/build_release.py [--out dist]

Requires setuptools in the running interpreter. Builds with no network access
(``PIP_NO_INDEX=1``), then checks:

* the wheel contains exactly the nine package modules plus six metadata files;
* no bytecode or cache entries are present in either artifact;
* the artifacts are named for the version declared in ``pyproject.toml``;
* no private-identifier string appears in any text member.

Prints the SHA-256 of each artifact so a release record can pin them.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Generic private-path and credential rules. Private identifiers are supplied
# by an out-of-tree audit through SOURCECOURT_PRIVATE_TERMS (comma separated)
# rather than listed here: a published deny list leaks what it protects.
PRIVATE_PATH_PATTERNS = (
    (r"[A-Za-z]:[\\/]Users[\\/]", "windows user-profile path"),
    (r"[A-Za-z]:[\\/]Documents and Settings[\\/]", "legacy windows user path"),
    (r"(?<![\w.])/(?:home|Users)/[A-Za-z0-9._-]+/", "posix user-profile path"),
)
CREDENTIAL_PATTERNS = (
    (r"ghp_[A-Za-z0-9]{20,}", "github token"),
    (r"sk-[A-Za-z0-9]{20,}", "api key"),
    (r"AKIA[0-9A-Z]{16}", "aws access key id"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
    (r"(?i)aws_secret" + "_access_key", "aws secret key name"),
)


def _extra_terms() -> tuple[str, ...]:
    raw = os.environ.get("SOURCECOURT_PRIVATE_TERMS", "")
    return tuple(term.strip() for term in raw.split(",") if term.strip())


def _findings(text: str) -> list[str]:
    found = [
        label
        for pattern, label in PRIVATE_PATH_PATTERNS + CREDENTIAL_PATTERNS
        if re.search(pattern, text)
    ]
    found.extend("supplied private term" for term in _extra_terms() if term in text)
    return found
# 2026-10-24T00:00:00Z, written as an epoch so archive timestamps are stable.
RELEASE_EPOCH = "1792800000"


def _version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return project["project"]["version"]


def _module_names() -> list[str]:
    return sorted(p.name for p in (ROOT / "src" / "sourcecourt").glob("*.py"))


def _normalize_sdist(path: Path, epoch: int) -> None:
    """Rewrite a .tar.gz deterministically (sorted members, fixed metadata).

    setuptools does not honour SOURCE_DATE_EPOCH for sdist member timestamps, so
    two builds of identical sources differ in bytes. Normalising here makes the
    archive reproducible: same source -> same bytes -> same SHA-256.
    """
    import gzip
    import io
    import tarfile

    with tarfile.open(path, "r:gz") as source:
        members = []
        for member in source.getmembers():
            payload = source.extractfile(member).read() if member.isfile() else None
            members.append((member, payload))

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as target:
        for member, payload in sorted(members, key=lambda item: item[0].name):
            info = tarfile.TarInfo(member.name)
            info.size = member.size
            info.mode = member.mode
            info.type = member.type
            info.mtime = epoch
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.pax_headers = {}
            if payload is None:
                target.addfile(info)
            else:
                target.addfile(info, io.BytesIO(payload))

    with open(path, "wb") as raw_file:
        with gzip.GzipFile(fileobj=raw_file, mode="wb", mtime=0) as compressed:
            compressed.write(buffer.getvalue())


def build(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            # Pin archive timestamps so two builds of the same source produce
            # byte-identical artifacts.
            "SOURCE_DATE_EPOCH": RELEASE_EPOCH,
        }
    )
    with tempfile.TemporaryDirectory() as wheel_dir:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--no-cache-dir",
                "-w",
                wheel_dir,
                str(ROOT),
            ],
            check=True,
            env=env,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        wheels = sorted(Path(wheel_dir).glob("*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"expected one wheel, got {wheels}")
        shutil.copy2(wheels[0], out / wheels[0].name)

    sys.path.insert(0, str(ROOT))
    import setuptools.build_meta as build_meta  # noqa: PLC0415

    name = build_meta.build_sdist(str(out))
    sdist_path = out / name
    _normalize_sdist(sdist_path, int(RELEASE_EPOCH))
    return [out / wheels[0].name, sdist_path]


def verify(artifacts: list[Path], version: str) -> None:
    problems: list[str] = []
    wheel = next(p for p in artifacts if p.suffix == ".whl")
    sdist = next(p for p in artifacts if p.name.endswith(".tar.gz"))
    if version not in wheel.name:
        problems.append(f"wheel name does not carry version {version}: {wheel.name}")

    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        modules = sorted(n for n in names if n.startswith("sourcecourt/"))
        expected = [f"sourcecourt/{name}" for name in _module_names()]
        if modules != expected:
            problems.append(f"wheel modules differ from source: {modules} != {expected}")
        if len(names) != 15:
            problems.append(f"wheel has {len(names)} entries, expected 15")
        for name in names:
            if "__pycache__" in name or name.endswith((".pyc", ".pyo")):
                problems.append(f"bytecode entry in wheel: {name}")
            if name.endswith((".py", ".txt", ".md", "METADATA", "WHEEL")):
                text = archive.read(name).decode("utf-8", "replace")
                for finding in _findings(text):
                    problems.append(f"{finding} in wheel member {name}")

    with tarfile.open(sdist) as archive:
        members = archive.getnames()
        for name in members:
            if "__pycache__" in name or name.endswith((".pyc", ".pyo")):
                problems.append(f"bytecode entry in sdist: {name}")
        for member in archive.getmembers():
            if not member.isfile() or not member.name.endswith((".py", ".md", ".txt", ".cfg", ".toml", ".in")):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            text = extracted.read().decode("utf-8", "replace")
            for finding in _findings(text):
                problems.append(f"{finding} in sdist member {member.name}")

    if problems:
        for problem in problems:
            print("PROBLEM:", problem)
        raise SystemExit(1)


def main() -> int:
    out = ROOT / "dist"
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    version = _version()
    artifacts = build(out)
    verify(artifacts, version)
    for artifact in artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        print(f"{digest}  {artifact.stat().st_size:>7}  {artifact.name}")
    print(f"version {version}: verified {len(artifacts)} artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

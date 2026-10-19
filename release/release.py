"""Assemble a signed release directory from the verified ISO (docs/BUILD_CONTRACT.md, "Release").

Usage (normally via ``make release``):

    python -m release.release [--root DIR]

Environment variables (also read from .env.example / .env, environment wins):

    RELEASE_GPG_KEY       id/fingerprint/e-mail of the signing key (required, never generated)
    RELEASE_ALLOW_DIRTY   "1" permits a dirty tree / untagged HEAD for a dry run; the
                          notes are then marked as an unofficial build
    DISTRO_NAME, ARCH_ARCHIVE_DATE   as everywhere else in the project

Why Python: every rule here (exactly one ISO, clean tree, tag matches VERSION, key
present) is a way for a release to go wrong silently, so each is a small function
with a unit test. The ISO is NEVER rebuilt here: the release must describe the exact
file that was verified.

Exit codes: 0 = release written, 1 = refused or failed (message on stderr).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import shutil
import string
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DISTRO_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# WHY strict: the value is passed to gpg as an argument; a leading "-" would be read as an
# option. Key ids, fingerprints and e-mail addresses all fit this pattern.
GPG_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._+-]*$")

TEMPLATE_PATH = Path(__file__).resolve().parent / "RELEASE_NOTES.md.tmpl"
# Documents copied into the release: (source relative to the root, name in the release).
INCLUDED_DOCS = (
    ("LICENSE", "LICENSE"),
    ("TRADEMARKS.md", "TRADEMARKS.md"),
    ("docs/ASSETS.md", "ASSETS.md"),
)


class ReleaseError(Exception):
    """A release precondition failed; the message is safe to show to the user."""


def _run(cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """
    Run an external command (git, gpg) with an argument list, never through a shell.

    This is the single subprocess boundary of the module, which tests replace.

    Args:
        cmd: Program and arguments.
        cwd: Working directory.

    Returns:
        The completed process with captured text output.
    """
    return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, check=False)


def parse_env_file(text: str) -> dict[str, str]:
    """
    Parse simple ``KEY=value`` lines like the Makefile / shell scripts do.

    Args:
        text: File content; ``#`` lines, blank lines and CRs are ignored.

    Returns:
        Mapping of names to raw values (surrounding whitespace stripped).
    """
    values: dict[str, str] = {}
    for line in text.replace("\r", "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def load_config(root: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """
    Merge .env.example, .env and the process environment (later wins).

    Args:
        root: Repository root.
        environ: Process environment.

    Returns:
        Merged configuration.
    """
    config: dict[str, str] = {}
    for name in (".env.example", ".env"):
        path = root / name
        if path.is_file():
            config.update(parse_env_file(path.read_text(encoding="utf-8")))
    # WHY skip empty: make exports empty defaults (e.g. RELEASE_GPG_KEY=) that must not
    # wipe a value the user put in .env; a non-empty environment value overrides files.
    config.update({k: v for k, v in environ.items() if v != "" or k not in config})
    return config


def read_version(path: Path) -> str:
    """
    Read the single-source release version.

    Args:
        path: The VERSION file.

    Returns:
        ``MAJOR.MINOR.PATCH``.

    Raises:
        ReleaseError: the file is missing or does not hold exactly such a version.
    """
    if not path.is_file():
        raise ReleaseError(f"{path.name} is missing; it holds the release version (e.g. 0.1.0)")
    version = path.read_text(encoding="utf-8").strip()
    if not VERSION_RE.match(version):
        raise ReleaseError(f"{path.name} must contain MAJOR.MINOR.PATCH, got {version!r}")
    return version


def select_iso(iso_dir: Path) -> Path:
    """
    Pick the one ISO to release.

    Args:
        iso_dir: Directory the ISO build wrote to.

    Returns:
        Path of the single ``*.iso`` file.

    Raises:
        ReleaseError: zero or several ISOs (guessing would risk releasing a stale image).
    """
    isos = sorted(iso_dir.glob("*.iso")) if iso_dir.is_dir() else []
    if not isos:
        raise ReleaseError(f"no ISO in {iso_dir}; run 'make iso-host' (or 'make iso') first")
    if len(isos) > 1:
        names = ", ".join(p.name for p in isos)
        raise ReleaseError(f"expected exactly one ISO in {iso_dir}, found {len(isos)}: {names}")
    return isos[0]


def sha256_file(path: Path) -> str:
    """
    Hash a file in chunks (ISOs are gigabytes).

    Args:
        path: File to hash.

    Returns:
        Lowercase hex SHA-256.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_sha256sums(entries: Mapping[str, str]) -> str:
    """
    Render ``sha256sum``-compatible text: ``<hash>  <name>`` (two spaces = text mode).

    Args:
        entries: File name to hex digest.

    Returns:
        One line per file sorted by name, newline-terminated.
    """
    return "".join(f"{digest}  {name}\n" for name, digest in sorted(entries.items()))


def parse_versions_md(text: str) -> dict[str, str]:
    """
    Extract ``| package | version |`` rows from docs/VERSIONS.md.

    Args:
        text: Markdown content.

    Returns:
        Package name to version (header and separator rows are harmless extras).
    """
    versions: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2:
            versions[cells[0]] = cells[1]
    return versions


def check_git_state(root: Path, version: str, allow_dirty: bool) -> tuple[str, bool]:
    """
    Verify the tree is clean and HEAD is tagged ``v<version>``.

    Args:
        root: Repository root.
        version: Release version.
        allow_dirty: Dry-run override (RELEASE_ALLOW_DIRTY=1).

    Returns:
        (HEAD commit hash, official) where official is False if an override was needed.

    Raises:
        ReleaseError: git failed, or a check failed without the override.
    """
    head = _run(["git", "rev-parse", "HEAD"], root)
    if head.returncode != 0:
        raise ReleaseError("cannot read the git commit (is this a git checkout?)")
    commit = head.stdout.strip()
    # WHY ignore untracked files: build outputs and logs live there, and what the ISO
    # contains is decided by tracked files.
    status = _run(["git", "status", "--porcelain", "--untracked-files=no"], root)
    tags = _run(["git", "tag", "--points-at", "HEAD"], root)
    if status.returncode != 0 or tags.returncode != 0:
        raise ReleaseError("git status/tag query failed")
    problems = []
    if status.stdout.strip():
        problems.append("the git tree has uncommitted changes")
    if f"v{version}" not in tags.stdout.split():
        problems.append(f"HEAD is not tagged v{version}")
    if problems and not allow_dirty:
        raise ReleaseError(
            "; ".join(problems) + ". Commit and tag, or set RELEASE_ALLOW_DIRTY=1 for an unofficial dry run"
        )
    return commit, not problems


def human_size(num_bytes: int) -> str:
    """
    Format a byte count in binary units.

    Args:
        num_bytes: Size in bytes.

    Returns:
        E.g. ``2.2 GiB``.
    """
    if num_bytes < 1024:
        return f"{num_bytes} B"
    size = float(num_bytes)
    for unit in ("KiB", "MiB", "GiB"):
        size /= 1024
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
    raise AssertionError("unreachable")


def render_notes(template: str, fields: Mapping[str, str]) -> str:
    """
    Fill the release-notes template.

    Args:
        template: ``string.Template`` text.
        fields: Placeholder values.

    Returns:
        Rendered Markdown.

    Raises:
        ReleaseError: the template uses a placeholder with no value.
    """
    try:
        return string.Template(template).substitute(fields)
    except KeyError as exc:
        raise ReleaseError(f"release notes template uses unknown field {exc}") from exc


def sign_file(root: Path, key: str, target: Path, signature: Path) -> None:
    """
    Create a detached GPG signature with an existing key and verify it.

    Args:
        root: Working directory for gpg.
        key: Key id/fingerprint/e-mail; the key must already be in the keyring.
        target: File to sign.
        signature: Where to write the signature.

    Raises:
        ReleaseError: signing or verification failed.
    """
    sign = _run(
        ["gpg", "--batch", "--yes", "--local-user", key, "--output", str(signature), "--detach-sign", str(target)],
        root,
    )
    if sign.returncode != 0:
        raise ReleaseError("gpg could not sign SHA256SUMS (is the key in the keyring and unlocked?)")
    verify = _run(["gpg", "--batch", "--verify", str(signature), str(target)], root)
    if verify.returncode != 0:
        raise ReleaseError("the new signature does not verify")


def build_release(root: Path, environ: Mapping[str, str], now: datetime.datetime | None = None) -> Path:
    """
    Check every precondition, then assemble and sign the release directory.

    Args:
        root: Repository root.
        environ: Process environment.
        now: Release time (injectable for tests); defaults to the current UTC time.

    Returns:
        The finished release directory ``.build/release/<distro>-<version>``.

    Raises:
        ReleaseError: any precondition or step failed; nothing partial is left behind.
    """
    config = load_config(root, environ)
    distro = config.get("DISTRO_NAME", "")
    if not DISTRO_RE.match(distro):
        raise ReleaseError("DISTRO_NAME is missing or invalid")
    key = config.get("RELEASE_GPG_KEY", "")
    if not key:
        raise ReleaseError("RELEASE_GPG_KEY is not set; set it in .env to the id of the release signing key")
    if not GPG_KEY_RE.match(key):
        raise ReleaseError("RELEASE_GPG_KEY has an invalid format (use a key id, fingerprint or e-mail)")
    archive_date = config.get("ARCH_ARCHIVE_DATE", "")
    if not archive_date:
        raise ReleaseError("ARCH_ARCHIVE_DATE is not set")

    version = read_version(root / "VERSION")
    commit, official = check_git_state(root, version, config.get("RELEASE_ALLOW_DIRTY") == "1")

    iso = select_iso(root / ".build" / "iso")
    for src, _ in INCLUDED_DOCS:
        if not (root / src).is_file():
            raise ReleaseError(f"{src} is missing; it must exist at release time")
    versions_path = root / "docs" / "VERSIONS.md"
    if not versions_path.is_file():
        raise ReleaseError("docs/VERSIONS.md is missing")
    versions = parse_versions_md(versions_path.read_text(encoding="utf-8"))
    for pkg in ("plasma-desktop", "kwin"):
        if pkg not in versions:
            raise ReleaseError(f"docs/VERSIONS.md has no row for {pkg}")

    release_root = root / ".build" / "release"
    final = release_root / f"{distro}-{version}"
    partial = release_root / f"{distro}-{version}.partial"
    release_root.mkdir(parents=True, exist_ok=True)
    # Safe to delete: both paths are fixed children of .build/release built from validated names.
    for stale in (partial, final):
        if stale.exists():
            shutil.rmtree(stale)
    partial.mkdir()
    try:
        iso_hash = sha256_file(iso)
        shutil.copyfile(iso, partial / iso.name)
        if sha256_file(partial / iso.name) != iso_hash:
            raise ReleaseError("the copied ISO differs from the source (disk or copy error)")
        for src, dest in INCLUDED_DOCS:
            shutil.copyfile(root / src, partial / dest)

        banner = (
            ""
            if official
            else "\n**UNOFFICIAL BUILD: made from a dirty tree or an untagged commit; do not distribute.**\n"
        )
        when = now or datetime.datetime.now(datetime.timezone.utc)
        size = iso.stat().st_size
        notes = render_notes(
            TEMPLATE_PATH.read_text(encoding="utf-8"),
            {
                "distro": distro,
                "version": version,
                "unofficial_banner": banner,
                "date": when.strftime("%Y-%m-%d"),
                "iso_name": iso.name,
                "iso_size_bytes": str(size),
                "iso_size_human": human_size(size),
                "iso_sha256": iso_hash,
                "git_commit": commit,
                "archive_date": archive_date,
                "plasma_version": versions["plasma-desktop"],
                "kwin_version": versions["kwin"],
                "signing_key": key,
            },
        )
        (partial / "RELEASE_NOTES.md").write_text(notes, encoding="utf-8", newline="\n")

        entries = {p.name: sha256_file(p) for p in partial.iterdir() if p.is_file()}
        sums = partial / "SHA256SUMS"
        sums.write_text(format_sha256sums(entries), encoding="utf-8", newline="\n")
        sign_file(root, key, sums, partial / "SHA256SUMS.sig")
        partial.rename(final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return final


def main(argv: Sequence[str] | None = None) -> int:
    """
    Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description="Assemble and sign a release directory.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        out = build_release(args.root.resolve(), os.environ)
    except ReleaseError as exc:
        print(f"release: error: {exc}", file=sys.stderr)
        return 1
    print(f"release: written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

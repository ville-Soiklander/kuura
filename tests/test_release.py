"""Tests for release/release.py: preconditions, checksum format, notes and signing flow.

Git is real (a throwaway repository under tmp_path); only gpg is faked, at the
module's single subprocess boundary (release._run), because no signing key exists
in a test environment.
"""

from __future__ import annotations

import datetime
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from release import release

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")

VERSIONS_MD = """# Pinned versions

| Package | Version |
|---|---|
| plasma-desktop | 6.7.5-1 |
| kwin | 6.7.5-1 |
"""


def _git(root: Path, *args: str) -> None:
    """Run a git command in the test repository, failing the test on error."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed, tagged v0.1.0 repository with one ISO and all documents present."""
    root = tmp_path
    (root / "VERSION").write_text("0.1.0\n")
    (root / ".env.example").write_text("DISTRO_NAME=kuura\nARCH_ARCHIVE_DATE=2026/09/24\nRELEASE_GPG_KEY=\n")
    (root / "LICENSE").write_text("license text\n")
    (root / "TRADEMARKS.md").write_text("trademarks\n")
    (root / "docs").mkdir()
    (root / "docs" / "ASSETS.md").write_text("assets\n")
    (root / "docs" / "VERSIONS.md").write_text(VERSIONS_MD)
    (root / ".gitignore").write_text(".build/\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "tag", "v0.1.0")
    (root / ".build" / "iso").mkdir(parents=True)
    (root / ".build" / "iso" / "kuura-test.iso").write_bytes(b"iso-bytes" * 1000)
    return root


@pytest.fixture
def fake_gpg(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Replace gpg at the subprocess boundary; git still runs for real. Returns the gpg calls."""
    calls: list[list[str]] = []
    real_run = release._run

    def fake_run(cmd, cwd=None):  # noqa: ANN001
        if cmd[0] != "gpg":
            return real_run(cmd, cwd)
        calls.append(list(cmd))
        if "--detach-sign" in cmd:
            Path(cmd[cmd.index("--output") + 1]).write_bytes(b"SIGNATURE")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(release, "_run", fake_run)
    return calls


ENV = {"RELEASE_GPG_KEY": "ABCD1234"}


# --- version -----------------------------------------------------------------------------


def test_read_version_ok(tmp_path: Path) -> None:
    """A well-formed version file is returned without whitespace."""
    (tmp_path / "VERSION").write_text("1.2.3\n")
    assert release.read_version(tmp_path / "VERSION") == "1.2.3"


@pytest.mark.parametrize("text", ["", "1.2", "v1.2.3", "1.2.3-rc1", "1.2.3\n4.5.6"])
def test_read_version_rejects_malformed(tmp_path: Path, text: str) -> None:
    """Anything but MAJOR.MINOR.PATCH is refused."""
    (tmp_path / "VERSION").write_text(text)
    with pytest.raises(release.ReleaseError):
        release.read_version(tmp_path / "VERSION")


def test_read_version_missing(tmp_path: Path) -> None:
    """A missing VERSION file is a clear error."""
    with pytest.raises(release.ReleaseError, match="VERSION"):
        release.read_version(tmp_path / "VERSION")


# --- ISO selection -----------------------------------------------------------------------


def test_select_iso_zero(tmp_path: Path) -> None:
    """No ISO (or no directory) fails with a hint at the build target."""
    with pytest.raises(release.ReleaseError, match="no ISO"):
        release.select_iso(tmp_path)
    with pytest.raises(release.ReleaseError, match="no ISO"):
        release.select_iso(tmp_path / "missing")


def test_select_iso_one(tmp_path: Path) -> None:
    """Exactly one ISO is returned; other files are ignored."""
    (tmp_path / "a.iso").write_bytes(b"x")
    (tmp_path / "a.iso.sha256").write_text("x")
    assert release.select_iso(tmp_path) == tmp_path / "a.iso"


def test_select_iso_two(tmp_path: Path) -> None:
    """Several ISOs are ambiguous and name the candidates."""
    (tmp_path / "a.iso").write_bytes(b"x")
    (tmp_path / "b.iso").write_bytes(b"y")
    with pytest.raises(release.ReleaseError, match="a.iso, b.iso"):
        release.select_iso(tmp_path)


# --- checksums and parsing ---------------------------------------------------------------


def test_sha256sums_format_is_sha256sum_compatible(tmp_path: Path) -> None:
    """Lines are '<hash>  <name>', sorted, and the real sha256sum-style check passes."""
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello")
    digest = release.sha256_file(f)
    assert digest == hashlib.sha256(b"hello").hexdigest()
    text = release.format_sha256sums({"b": "2" * 64, "a": digest})
    assert text == f"{digest}  a\n{'2' * 64}  b\n"


def test_parse_versions_md() -> None:
    """Table rows are read; prose is ignored."""
    versions = release.parse_versions_md(VERSIONS_MD)
    assert versions["kwin"] == "6.7.5-1"
    assert versions["plasma-desktop"] == "6.7.5-1"


@pytest.mark.parametrize(("n", "text"), [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KiB"), (2356527104, "2.2 GiB")])
def test_human_size(n: int, text: str) -> None:
    """Sizes switch unit exactly at 1024."""
    assert release.human_size(n) == text


def test_render_notes_unknown_field() -> None:
    """A template placeholder without a value is an error, not a blank."""
    with pytest.raises(release.ReleaseError):
        release.render_notes("$missing", {})


# --- git state ---------------------------------------------------------------------------


def test_git_state_clean_and_tagged(repo: Path) -> None:
    """Clean tree with the matching tag is official."""
    commit, official = release.check_git_state(repo, "0.1.0", allow_dirty=False)
    assert official and len(commit) == 40


def test_git_state_dirty_refused_then_overridden(repo: Path) -> None:
    """A modified tracked file refuses the release unless the override is set."""
    (repo / "LICENSE").write_text("changed\n")
    with pytest.raises(release.ReleaseError, match="uncommitted"):
        release.check_git_state(repo, "0.1.0", allow_dirty=False)
    _, official = release.check_git_state(repo, "0.1.0", allow_dirty=True)
    assert not official


def test_git_state_untracked_files_are_ignored(repo: Path) -> None:
    """Untracked files (build logs) do not make the tree dirty."""
    (repo / "scratch.log").write_text("x")
    assert release.check_git_state(repo, "0.1.0", allow_dirty=False)[1]


def test_git_state_missing_tag(repo: Path) -> None:
    """HEAD without v<version> is refused, and accepted as unofficial with the override."""
    with pytest.raises(release.ReleaseError, match="v0.2.0"):
        release.check_git_state(repo, "0.2.0", allow_dirty=False)
    assert not release.check_git_state(repo, "0.2.0", allow_dirty=True)[1]


def test_git_state_not_a_repo(tmp_path: Path) -> None:
    """Outside a git checkout the error is clear."""
    with pytest.raises(release.ReleaseError):
        release.check_git_state(tmp_path, "0.1.0", allow_dirty=False)


# --- whole release -----------------------------------------------------------------------


def test_release_happy_path(repo: Path, fake_gpg: list[list[str]]) -> None:
    """All files are produced, the sums verify, the notes carry the facts, gpg gets the key."""
    now = datetime.datetime(2026, 10, 20, tzinfo=datetime.timezone.utc)
    out = release.build_release(repo, ENV, now=now)
    assert out == repo / ".build" / "release" / "kuura-0.1.0"
    names = {p.name for p in out.iterdir()}
    assert names == {"LICENSE", "RELEASE_NOTES.md", "SHA256SUMS", "SHA256SUMS.sig", "TRADEMARKS.md", "ASSETS.md", "kuura-test.iso"}

    # Every listed file's checksum is right and the signature file is not listed.
    for line in (out / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert release.sha256_file(out / name) == digest
    assert "SHA256SUMS.sig" not in (out / "SHA256SUMS").read_text()

    notes = (out / "RELEASE_NOTES.md").read_text()
    iso_hash = hashlib.sha256(b"iso-bytes" * 1000).hexdigest()
    for expected in ("kuura 0.1.0", "2026-10-20", iso_hash, "2026/09/24", "6.7.5-1", "9000 bytes", "ABCD1234"):
        assert expected in notes
    assert "UNOFFICIAL" not in notes

    sign = next(c for c in fake_gpg if "--detach-sign" in c)
    assert sign[sign.index("--local-user") + 1] == "ABCD1234"
    assert any("--verify" in c for c in fake_gpg)
    assert not (out.parent / "kuura-0.1.0.partial").exists()


def test_release_unset_gpg_key(repo: Path, fake_gpg: list[list[str]]) -> None:
    """Without RELEASE_GPG_KEY nothing is written and gpg is never called."""
    with pytest.raises(release.ReleaseError, match="RELEASE_GPG_KEY"):
        release.build_release(repo, {})
    assert fake_gpg == []
    assert not (repo / ".build" / "release").exists()


@pytest.mark.parametrize("key", ["-bad", "a b", "k;rm", "$(x)"])
def test_release_rejects_odd_gpg_key(repo: Path, fake_gpg: list[list[str]], key: str) -> None:
    """A key value that could be read as an option or contains odd characters is refused."""
    with pytest.raises(release.ReleaseError, match="invalid"):
        release.build_release(repo, {"RELEASE_GPG_KEY": key})


def test_release_dirty_refused_and_override_marks_unofficial(repo: Path, fake_gpg: list[list[str]]) -> None:
    """A dirty tree stops the release; with the override the notes say UNOFFICIAL."""
    (repo / "LICENSE").write_text("changed\n")
    with pytest.raises(release.ReleaseError, match="uncommitted"):
        release.build_release(repo, ENV)
    out = release.build_release(repo, {**ENV, "RELEASE_ALLOW_DIRTY": "1"})
    assert "UNOFFICIAL BUILD" in (out / "RELEASE_NOTES.md").read_text()


def test_release_requires_exactly_one_iso(repo: Path, fake_gpg: list[list[str]]) -> None:
    """Zero or two ISOs fail the release; it never rebuilds."""
    (repo / ".build" / "iso" / "second.iso").write_bytes(b"z")
    with pytest.raises(release.ReleaseError, match="exactly one"):
        release.build_release(repo, ENV)
    for iso in (repo / ".build" / "iso").glob("*.iso"):
        iso.unlink()
    with pytest.raises(release.ReleaseError, match="no ISO"):
        release.build_release(repo, ENV)


def test_release_missing_trademarks(repo: Path, fake_gpg: list[list[str]]) -> None:
    """A missing document fails clearly before anything is written."""
    (repo / "TRADEMARKS.md").unlink()
    _git(repo, "commit", "-q", "-am", "rm")
    _git(repo, "tag", "-f", "v0.1.0")
    with pytest.raises(release.ReleaseError, match="TRADEMARKS.md"):
        release.build_release(repo, ENV)
    assert not (repo / ".build" / "release").exists()


def test_release_signing_failure_leaves_no_partial_dir(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If gpg fails, no release directory (final or partial) remains."""
    real_run = release._run

    def failing(cmd, cwd=None):  # noqa: ANN001
        if cmd[0] == "gpg":
            return subprocess.CompletedProcess(cmd, 2, "", "no secret key")
        return real_run(cmd, cwd)

    monkeypatch.setattr(release, "_run", failing)
    with pytest.raises(release.ReleaseError, match="sign"):
        release.build_release(repo, ENV)
    assert list((repo / ".build" / "release").iterdir()) == []


def test_release_is_idempotent(repo: Path, fake_gpg: list[list[str]]) -> None:
    """Running twice replaces the previous release directory."""
    release.build_release(repo, ENV)
    out = release.build_release(repo, ENV)
    assert (out / "SHA256SUMS").is_file()


def test_main_returns_1_with_message(repo: Path, fake_gpg: list[list[str]], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI prints a one-line error without a traceback and exits 1."""
    monkeypatch.delenv("RELEASE_GPG_KEY", raising=False)
    assert release.main(["--root", str(repo)]) == 1
    assert "RELEASE_GPG_KEY" in capsys.readouterr().err

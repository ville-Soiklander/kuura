"""
Behaviour tests for harness.install.testpackages.

The host's pacman is replaced by a fake ``run`` callable and the guest agent by a
recording fake; the code under test runs unmodified.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.install.testpackages import (
    ArchiveFetcher,
    PackageRef,
    TestPackageError,
    install_test_only_packages,
)
from harness.shots.guest import ExecResult

DATE = "2026/09/24"
BASE = "https://archive.archlinux.org/repos/2026/09/24/extra/os/x86_64/"
CLOSURE_OUT = (
    f"libnotify|0.8.6-1|{BASE}libnotify-0.8.6-1-x86_64.pkg.tar.zst\n"
    f"mousepad|0.6.3-1|{BASE}mousepad-0.6.3-1-x86_64.pkg.tar.zst\n"
    f"gtk4-demos|4.16.1-1|{BASE}gtk4-demos-4.16.1-1-x86_64.pkg.tar.zst\n"
    f"glib2|2.82.0-1|{BASE}glib2-2.82.0-1-x86_64.pkg.tar.zst\n"
    f"gtksourceview4|1:4.8.4-3|{BASE}gtksourceview4-1%3A4.8.4-3-x86_64.pkg.tar.zst\n"
)
CLOSURE = [
    PackageRef("libnotify", "0.8.6-1", "libnotify-0.8.6-1-x86_64.pkg.tar.zst"),
    PackageRef("mousepad", "0.6.3-1", "mousepad-0.6.3-1-x86_64.pkg.tar.zst"),
    PackageRef("gtk4-demos", "4.16.1-1", "gtk4-demos-4.16.1-1-x86_64.pkg.tar.zst"),
    PackageRef("glib2", "2.82.0-1", "glib2-2.82.0-1-x86_64.pkg.tar.zst"),
    PackageRef("gtksourceview4", "1:4.8.4-3", "gtksourceview4-1:4.8.4-3-x86_64.pkg.tar.zst"),
]


class FakeRun:
    """Stands in for subprocess.run; records argv and answers per pacman operation."""

    def __init__(self, cache_dir: Path, closure_out: str = CLOSURE_OUT, fail_op: str | None = None,
                 write_files: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.cache_dir = cache_dir
        self.closure_out = closure_out
        self.fail_op = fail_op
        self.write_files = write_files

    def __call__(self, argv: list[str], **kwargs: object) -> SimpleNamespace:
        self.calls.append(argv)
        op = argv[3]  # pacman --config <file> <op> ...
        if op == self.fail_op:
            return SimpleNamespace(returncode=1, stdout="", stderr="/secret/host/path")
        if op == "-Sp":
            return SimpleNamespace(returncode=0, stdout=self.closure_out, stderr="")
        if op == "-Sw" and self.write_files:
            for name in argv[argv.index("--") + 1:]:
                ref = next(r for r in CLOSURE if r.name == name)
                (self.cache_dir / ref.filename).write_bytes(f"data-{name}".encode())
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class FakeAgent:
    """Records writes and commands; answers `pacman -Q` from a fixed list."""

    def __init__(self, installed: str = "glib2 2.82.0-1\nbash 5.2-1\n", fail_install: bool = False) -> None:
        self.writes: dict[str, bytes] = {}
        self.commands: list[list[str]] = []
        self.installed = installed
        self.fail_install = fail_install

    def write_file(self, path: str, data: bytes) -> None:
        self.writes[path] = data

    def exec(self, argv: list[str], timeout: float = 20.0) -> ExecResult:
        self.commands.append(argv)
        if argv[1:] == ["-Q"]:
            return ExecResult(exit_code=0, stdout=self.installed, stderr="")
        if "-U" in argv and self.fail_install:
            return ExecResult(exit_code=1, stdout="", stderr="secret detail")
        return ExecResult(exit_code=0, stdout="", stderr="")


class FakeFetcher:
    """Resolver/downloader double for the guest-side function."""

    def __init__(self, tmp_path: Path, closure: list[PackageRef] = CLOSURE) -> None:
        self.closure = closure
        self.tmp_path = tmp_path
        self.downloaded: list[str] = []

    def resolve(self, targets: tuple[str, ...]) -> list[PackageRef]:
        return self.closure

    def download(self, refs: list[PackageRef]) -> dict[str, Path]:
        out = {}
        for ref in refs:
            path = self.tmp_path / ref.filename
            path.write_bytes(f"data-{ref.name}".encode())
            out[ref.name] = path
            self.downloaded.append(ref.name)
        return out


# ---- ArchiveFetcher (host side) ---------------------------------------------------


def test_resolve_returns_the_closure_with_decoded_file_names(tmp_path: Path) -> None:
    """The epoch escape in the URL becomes the real file name."""
    fake = FakeRun(tmp_path)
    refs = ArchiveFetcher(DATE, tmp_path, run=fake).resolve(("libnotify", "mousepad", "gtk4-demos"))
    assert refs == CLOSURE


def test_resolve_syncs_the_snapshot_then_lists_urls_without_a_shell(tmp_path: Path) -> None:
    """Sync comes first, targets follow `--`, and the config points at the dated archive."""
    fake = FakeRun(tmp_path)
    fetcher = ArchiveFetcher(DATE, tmp_path, run=fake)
    fetcher.resolve(("libnotify", "mousepad", "gtk4-demos"))
    assert [c[3] for c in fake.calls] == ["-Sy", "-Sp"]
    assert fake.calls[1][-4:] == ["--", "libnotify", "mousepad", "gtk4-demos"]
    config = Path(fake.calls[0][2]).read_text(encoding="utf-8")
    assert "repos/2026/09/24/$repo/os/$arch" in config
    assert "SigLevel = Required" in config


def test_the_database_is_synced_only_once(tmp_path: Path) -> None:
    """resolve + download share one -Sy."""
    fake = FakeRun(tmp_path)
    fetcher = ArchiveFetcher(DATE, tmp_path, run=fake)
    fetcher.resolve(("libnotify", "mousepad", "gtk4-demos"))
    fetcher.download([CLOSURE[0]])
    assert [c[3] for c in fake.calls].count("-Sy") == 1


@pytest.mark.parametrize("date", ["2026-09-24", "2026/9/24", "", "2026/09/24/../x", "2026/09/24\n"])
def test_a_malformed_archive_date_is_rejected(date: str, tmp_path: Path) -> None:
    """The date goes into a URL, so only YYYY/MM/DD is accepted."""
    with pytest.raises(TestPackageError, match="YYYY/MM/DD"):
        ArchiveFetcher(date, tmp_path, run=FakeRun(tmp_path))


def test_a_target_missing_from_the_snapshot_is_an_error(tmp_path: Path) -> None:
    """If a requested package is absent from the output, resolving fails."""
    fake = FakeRun(tmp_path, closure_out=CLOSURE_OUT.replace("mousepad|", "other|"))
    with pytest.raises(TestPackageError, match="missing from the archive"):
        ArchiveFetcher(DATE, tmp_path, run=fake).resolve(("libnotify", "mousepad", "gtk4-demos"))


@pytest.mark.parametrize("line", ["onlyone", "a|b", "bad name|1-1|http://x/y-1-1-x86_64.pkg.tar.zst",
                                  "pkg|1.0-1|http://x/..%2Fevil.txt"])
def test_unexpected_pacman_output_is_rejected(line: str, tmp_path: Path) -> None:
    """Malformed metadata never reaches the guest."""
    fake = FakeRun(tmp_path, closure_out=line + "\n")
    with pytest.raises(TestPackageError):
        ArchiveFetcher(DATE, tmp_path, run=fake).resolve(("libnotify",))


def test_a_pacman_failure_is_generic_and_hides_output(tmp_path: Path) -> None:
    """A non-zero host pacman exit raises without echoing its stderr."""
    fake = FakeRun(tmp_path, fail_op="-Sy")
    with pytest.raises(TestPackageError) as info:
        ArchiveFetcher(DATE, tmp_path, run=fake).resolve(("libnotify",))
    assert "secret" not in str(info.value)


def test_a_missing_pacman_binary_is_reported(tmp_path: Path) -> None:
    """OSError from the runner becomes a TestPackageError."""
    def broken(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("pacman")

    with pytest.raises(TestPackageError, match="could not run pacman"):
        ArchiveFetcher(DATE, tmp_path, run=broken).resolve(("libnotify",))


def test_a_timeout_is_reported(tmp_path: Path) -> None:
    """A hung pacman does not hang the harness forever."""
    def slow(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("pacman", 1)

    with pytest.raises(TestPackageError):
        ArchiveFetcher(DATE, tmp_path, run=slow).resolve(("libnotify",))


def test_resolve_rejects_option_like_names(tmp_path: Path) -> None:
    """A name starting with `-` could become a pacman option."""
    with pytest.raises(TestPackageError, match="invalid package name"):
        ArchiveFetcher(DATE, tmp_path, run=FakeRun(tmp_path)).resolve(("--root=/",))


def test_download_returns_the_files_and_skips_dependency_expansion(tmp_path: Path) -> None:
    """-Sw runs with -dd on exactly the named packages and returns their cached files."""
    fake = FakeRun(tmp_path)
    files = ArchiveFetcher(DATE, tmp_path, run=fake).download(CLOSURE[:2])
    assert set(files) == {"libnotify", "mousepad"}
    assert files["libnotify"].read_bytes() == b"data-libnotify"
    sw = next(c for c in fake.calls if c[3] == "-Sw")
    assert "-dd" in sw and sw[-3:] == ["--", "libnotify", "mousepad"]


def test_download_of_nothing_runs_nothing(tmp_path: Path) -> None:
    """An empty request does no network work."""
    fake = FakeRun(tmp_path)
    assert ArchiveFetcher(DATE, tmp_path, run=fake).download([]) == {}
    assert fake.calls == []


def test_a_file_missing_after_download_is_an_error(tmp_path: Path) -> None:
    """pacman exiting 0 without producing the file is not trusted."""
    fake = FakeRun(tmp_path, write_files=False)
    with pytest.raises(TestPackageError, match="missing after the download"):
        ArchiveFetcher(DATE, tmp_path, run=fake).download([CLOSURE[0]])


# ---- install_test_only_packages (guest side) -------------------------------------


def test_only_missing_packages_are_downloaded_copied_and_installed(tmp_path: Path) -> None:
    """glib2 is present at the snapshot version, so it is skipped everywhere."""
    agent, fetcher = FakeAgent(), FakeFetcher(tmp_path)
    names = install_test_only_packages(agent, fetcher)
    assert names == ["libnotify", "mousepad", "gtk4-demos", "gtksourceview4"]
    assert "glib2" not in fetcher.downloaded
    staged = {p for p in agent.writes if p.endswith(".pkg.tar.zst")}
    assert "/tmp/harness-testpkgs/gtksourceview4-1:4.8.4-3-x86_64.pkg.tar.zst" in staged
    assert len(staged) == 4
    install = next(c for c in agent.commands if "-U" in c)
    assert install[:2] == ["/usr/bin/pacman", "--config"]
    assert set(install[install.index("--") + 1:]) == staged
    assert agent.writes["/tmp/harness-testpkgs/pacman.conf"] == b"[options]\nLocalFileSigLevel = Never\n"


def test_the_stage_directory_is_removed_even_when_the_install_fails(tmp_path: Path) -> None:
    """Cleanup runs on the failure path too."""
    agent = FakeAgent(fail_install=True)
    with pytest.raises(TestPackageError, match="exit 1") as info:
        install_test_only_packages(agent, FakeFetcher(tmp_path))
    assert "secret detail" not in str(info.value)
    assert ["/usr/bin/rm", "-rf", "--", "/tmp/harness-testpkgs"] in agent.commands


def test_nothing_is_done_when_everything_is_already_installed(tmp_path: Path) -> None:
    """No download, no copy, no pacman -U."""
    installed = "".join(f"{r.name} {r.version}\n" for r in CLOSURE)
    agent, fetcher = FakeAgent(installed=installed), FakeFetcher(tmp_path)
    assert install_test_only_packages(agent, fetcher) == []
    assert fetcher.downloaded == []
    assert agent.writes == {}
    assert not any("-U" in c for c in agent.commands)


def test_a_dependency_with_another_version_than_the_snapshot_is_an_error(tmp_path: Path) -> None:
    """The ISO must come from the same snapshot; a mismatch is not silently upgraded."""
    agent = FakeAgent(installed="glib2 2.81.0-1\n")
    with pytest.raises(TestPackageError, match="glib2"):
        install_test_only_packages(agent, FakeFetcher(tmp_path))
    assert agent.writes == {}


def test_a_failing_package_query_is_reported(tmp_path: Path) -> None:
    """A non-zero `pacman -Q` aborts before anything is copied."""
    class Broken(FakeAgent):
        def exec(self, argv: list[str], timeout: float = 20.0) -> ExecResult:
            return ExecResult(exit_code=2, stdout="", stderr="")

    with pytest.raises(TestPackageError, match="listing"):
        install_test_only_packages(Broken(), FakeFetcher(tmp_path))


def test_a_lost_agent_connection_is_reported_and_cleanup_is_attempted(tmp_path: Path) -> None:
    """A ConnectionError during a copy becomes a TestPackageError."""
    class Dropping(FakeAgent):
        def write_file(self, path: str, data: bytes) -> None:
            raise ConnectionError("gone")

    with pytest.raises(TestPackageError, match="could not install"):
        install_test_only_packages(Dropping(), FakeFetcher(tmp_path))


def test_an_unreasonable_number_of_missing_packages_is_rejected(tmp_path: Path) -> None:
    """The agent limits the argument count; fail clearly instead of truncating."""
    many = [PackageRef(f"p{i}", "1-1", f"p{i}-1-1-x86_64.pkg.tar.zst") for i in range(60)]
    with pytest.raises(TestPackageError, match="too many"):
        install_test_only_packages(FakeAgent(installed=""), FakeFetcher(tmp_path, many))

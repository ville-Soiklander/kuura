"""
Test-only programs for the installed system under install-verify.

The shipped product deliberately does not contain the programs some verification
states run (``notify-send`` for the `notification` state, ``mousepad`` for
`app-menu-gtk`, ``gtk4-widget-factory`` for `gtk4-widget-factory`). The screenshot
image installs them itself; a real Calamares install copies the live ISO's
squashfs, which has no network and no test tools. So install-verify brings them
along: the HOST (which has network) resolves and downloads the exact package files
of the pinned Arch Archive snapshot the ISO was built from, and the guest agent
copies them into the installed target, where ``pacman -U`` installs them.

WHY the snapshot and not the host's current mirrors: a dependency of a test tool
that is already in the ISO (gtk4, glib2, ...) must be the very version the ISO
carries; a newer one would silently change the product under test.

Two halves, split so that each is testable with a fake:

* ``ArchiveFetcher`` - host side, runs the host's pacman against a throw-away
  configuration (own database directory, own cache) that points at the snapshot;
* ``install_test_only_packages`` - guest side, works through the guest agent.

Nothing here is shipped by any package.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

#: The programs the verification states need that the product does not ship.
#: Their dependencies already present in the target are skipped at install time.
TEST_ONLY_PACKAGES: tuple[str, ...] = ("libnotify", "mousepad", "gtk4-demos")

#: Snapshot date format, same as ARCH_ARCHIVE_DATE (it ends up in a URL, so it is
#: validated strictly before use).
ARCHIVE_DATE_PATTERN = re.compile(r"^\d{4}/\d{2}/\d{2}\Z")

#: Package names as pacman allows them (also a defence against option injection).
_PACKAGE_NAME_PATTERN = re.compile(r"^[a-z0-9@._+][a-z0-9@._+-]*$")
#: Version strings (epoch ``1:`` allowed).
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._+:~]+-[A-Za-z0-9._+]+$")
#: Package file names; no path separator can occur.
_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9@._+:~-]+\.pkg\.tar\.(zst|xz)$")

_HOST_PACMAN = "pacman"
_HOST_TIMEOUT_S = 1800.0

_GUEST_PACMAN = "/usr/bin/pacman"
_GUEST_RM = "/usr/bin/rm"
#: Staging directory in the guest (the agent's file API can create it as the user;
#: pacman runs as root and can read it). Removed again afterwards.
_GUEST_PKG_DIR = "/tmp/harness-testpkgs"
#: Most packages one ``pacman -U`` call may carry (the agent limits the argument count).
_MAX_PACKAGES_PER_CALL = 48
_GUEST_INSTALL_TIMEOUT_S = 600.0


class TestPackageError(Exception):
    """Resolving, fetching or installing the test-only packages failed (generic text)."""

    # pytest must not try to collect this class because of its "Test" prefix.
    __test__ = False


@dataclass(frozen=True)
class PackageRef:
    """
    One package of the resolved dependency closure.

    Attributes:
        name: Package name.
        version: Full version string including pkgrel (and epoch if any).
        filename: Package file name inside the archive (no directory part).
    """

    name: str
    version: str
    filename: str


class ArchiveFetcher:
    """
    Resolves and downloads packages of one Arch Archive snapshot with the host's pacman.

    A private pacman configuration (database directory, cache directory, log file)
    is written to a temporary directory so the host's own pacman state is never
    touched. Package signatures are verified by pacman against the host keyring
    during the download; that verification is what the guest relies on.

    Args:
        archive_date: Snapshot date ``YYYY/MM/DD`` (ARCH_ARCHIVE_DATE).
        cache_dir: Directory that receives (and caches) the downloaded files.
        run: Process runner with ``subprocess.run`` semantics (tests inject a fake).

    Raises:
        TestPackageError: the date is malformed.
    """

    def __init__(
        self,
        archive_date: str,
        cache_dir: Path,
        run: Callable[..., Any] = subprocess.run,
    ) -> None:
        if not ARCHIVE_DATE_PATTERN.match(archive_date):
            raise TestPackageError("the archive date must have the form YYYY/MM/DD")
        self._date = archive_date
        self._cache_dir = cache_dir
        self._run = run
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._config: Path | None = None
        self._synced = False

    def _pacman(self, args: list[str]) -> str:
        """
        Run the host pacman against the snapshot configuration.

        Args:
            args: Arguments after ``--config <file>`` (never built from a shell string).

        Returns:
            Captured standard output.

        Raises:
            TestPackageError: pacman is missing, times out or exits non-zero. The
                message is generic; pacman's output is not echoed (it holds host paths).
        """
        if self._config is None:
            # WHY a temporary database directory: the snapshot's databases must not
            # overwrite the host's own sync databases, and an empty local database
            # makes -Sp list the FULL closure, which is what the caller wants to
            # compare with the guest's installed packages.
            self._tmp = tempfile.TemporaryDirectory(prefix="harness-archive-")
            root = Path(self._tmp.name)
            (root / "db" / "local").mkdir(parents=True)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            server = f"https://archive.archlinux.org/repos/{self._date}/$repo/os/$arch"
            self._config = root / "pacman.conf"
            self._config.write_text(
                "[options]\n"
                f"DBPath = {root / 'db'}\n"
                f"CacheDir = {self._cache_dir}\n"
                f"LogFile = {root / 'pacman.log'}\n"
                f"HookDir = {root / 'hooks'}\n"
                "GPGDir = /etc/pacman.d/gnupg\n"
                "Architecture = x86_64\n"
                # Signatures are mandatory: the guest installs these files unchecked.
                "SigLevel = Required DatabaseOptional\n"
                f"[core]\nServer = {server}\n"
                f"[extra]\nServer = {server}\n",
                encoding="utf-8",
            )
        try:
            done = self._run(
                [_HOST_PACMAN, "--config", str(self._config), *args],
                capture_output=True,
                text=True,
                timeout=_HOST_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TestPackageError("could not run pacman on the host") from exc
        if done.returncode != 0:
            raise TestPackageError(
                f"host pacman failed (exit {done.returncode}) while fetching the test-only packages "
                f"from the {self._date} archive snapshot; it needs root and network access"
            )
        return done.stdout

    def _sync(self) -> None:
        """Sync the snapshot's package databases once per fetcher."""
        if not self._synced:
            self._pacman(["-Sy"])
            self._synced = True

    def resolve(self, targets: tuple[str, ...] = TEST_ONLY_PACKAGES) -> list[PackageRef]:
        """
        Resolve the targets and all their dependencies at the snapshot.

        Args:
            targets: Package names to resolve.

        Returns:
            Every package of the closure (nothing is assumed installed).

        Raises:
            TestPackageError: a name is malformed, a target does not exist in the
                snapshot or the output cannot be understood.
        """
        _check_names(targets)
        self._sync()
        out = self._pacman(["-Sp", "--print-format", "%n|%v|%l", "--", *targets])
        refs: list[PackageRef] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.strip().split("|")
            if len(parts) != 3:
                raise TestPackageError("unexpected pacman output while resolving the test-only packages")
            name, version, url = parts
            # The URL is only used for its last path segment (the archive's file name).
            filename = unquote(Path(urlparse(url).path).name)
            if (
                not _PACKAGE_NAME_PATTERN.match(name)
                or not _VERSION_PATTERN.match(version)
                or not _FILENAME_PATTERN.match(filename)
            ):
                raise TestPackageError("unexpected package metadata while resolving the test-only packages")
            refs.append(PackageRef(name=name, version=version, filename=filename))
        resolved = {ref.name for ref in refs}
        if not set(targets) <= resolved:
            raise TestPackageError("a test-only package is missing from the archive snapshot")
        return refs

    def download(self, refs: list[PackageRef]) -> dict[str, Path]:
        """
        Download exactly the given packages (no dependency expansion) and check them.

        Args:
            refs: Packages from ``resolve``.

        Returns:
            Package name to the downloaded file.

        Raises:
            TestPackageError: the download fails or a file is missing afterwards.
        """
        if not refs:
            return {}
        _check_names(tuple(ref.name for ref in refs))
        self._sync()
        # --nodeps (twice: also skip version checks): the caller already chose the
        # exact set; pacman would otherwise re-add everything the guest already has.
        self._pacman(["-Sw", "--noconfirm", "-dd", "--", *(ref.name for ref in refs)])
        files: dict[str, Path] = {}
        for ref in refs:
            path = self._cache_dir / ref.filename
            if not path.is_file():
                raise TestPackageError(f"package file for {ref.name!r} is missing after the download")
            files[ref.name] = path
        return files


def _check_names(names: tuple[str, ...]) -> None:
    """
    Reject names pacman could mistake for options.

    Args:
        names: Package names to check.

    Raises:
        TestPackageError: a name does not look like a package name.
    """
    for name in names:
        if not _PACKAGE_NAME_PATTERN.match(name):
            raise TestPackageError("invalid package name")


def _installed_in_guest(agent: Any) -> dict[str, str]:
    """
    Ask the guest which packages (and versions) are installed.

    Args:
        agent: The connected guest agent.

    Returns:
        Package name to version.

    Raises:
        TestPackageError: the query failed.
    """
    try:
        listed = agent.exec([_GUEST_PACMAN, "-Q"], timeout=60.0)
    except (TimeoutError, ConnectionError, RuntimeError, OSError, ValueError) as exc:
        raise TestPackageError("could not list the packages installed in the guest") from exc
    if listed.exit_code != 0:
        raise TestPackageError(f"listing the guest's packages failed (exit {listed.exit_code})")
    installed: dict[str, str] = {}
    for line in listed.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            installed[parts[0]] = parts[1]
    return installed


def install_test_only_packages(
    agent: Any,
    fetcher: ArchiveFetcher,
    targets: tuple[str, ...] = TEST_ONLY_PACKAGES,
    log: Callable[[str], None] = lambda line: None,
) -> list[str]:
    """
    Install the test-only programs (and the dependencies the target lacks) offline.

    Steps: resolve the closure at the snapshot (host); ask the guest what it has;
    download only what is missing (host); copy the files into the guest; run
    ``pacman -U`` there as root.

    Dependencies that ARE installed are left alone when their version equals the
    snapshot's. A different version means the ISO was not built from this snapshot;
    installing the test tools next to it could change the product under test, so
    that is an error rather than a silent upgrade.

    The guest's pacman is told to skip signature checks (``LocalFileSigLevel =
    Never`` in a throw-away configuration) because the installed system's keyring
    is not guaranteed to be initialised; the host's pacman already verified every
    signature during the download.

    Args:
        agent: The connected guest agent (``write_file``, ``exec``).
        fetcher: Host-side resolver/downloader for the pinned snapshot.
        targets: Packages to install.
        log: Progress callback, one line per step.

    Returns:
        Names of the packages installed (empty if everything was present).

    Raises:
        TestPackageError: resolving, downloading, copying or installing failed, or
            an installed dependency differs from the snapshot's version.
    """
    closure = fetcher.resolve(targets)
    installed = _installed_in_guest(agent)

    missing: list[PackageRef] = []
    for ref in closure:
        have = installed.get(ref.name)
        if have is None:
            missing.append(ref)
        elif have != ref.version:
            raise TestPackageError(
                f"installed package {ref.name!r} has version {have}, the archive snapshot has "
                f"{ref.version}: the ISO was not built from this snapshot"
            )
    if not missing:
        log("test-only packages already present")
        return []
    if len(missing) > _MAX_PACKAGES_PER_CALL:
        raise TestPackageError("too many test-only packages are missing from the target")

    files = fetcher.download(missing)
    config = b"[options]\nLocalFileSigLevel = Never\n"
    config_path = f"{_GUEST_PKG_DIR}/pacman.conf"
    guest_paths: list[str] = []
    try:
        try:
            agent.write_file(config_path, config)
            for ref in missing:
                dest = f"{_GUEST_PKG_DIR}/{ref.filename}"
                try:
                    data = files[ref.name].read_bytes()
                except OSError as exc:
                    raise TestPackageError(f"could not read the package file for {ref.name!r}") from exc
                agent.write_file(dest, data)
                guest_paths.append(dest)
            log(f"copied {len(missing)} test-only package file(s) into the guest")
            done = agent.exec(
                [_GUEST_PACMAN, "--config", config_path, "-U", "--noconfirm", "--needed", "--", *guest_paths],
                timeout=_GUEST_INSTALL_TIMEOUT_S,
            )
        except (TimeoutError, ConnectionError, RuntimeError, OSError, ValueError) as exc:
            raise TestPackageError("could not install the test-only packages in the guest") from exc
        if done.exit_code != 0:
            raise TestPackageError(f"installing the test-only packages failed (exit {done.exit_code})")
    finally:
        # Best effort: a leftover directory is harmless in a throw-away VM.
        try:
            agent.exec([_GUEST_RM, "-rf", "--", _GUEST_PKG_DIR])
        except (TimeoutError, ConnectionError, RuntimeError, OSError, ValueError):
            pass
    names = [ref.name for ref in missing]
    log("installed test-only packages: " + ", ".join(names))
    return names

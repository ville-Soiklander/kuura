"""
Tests for harness.install.run's genuinely pure/testable pieces: find_single_iso,
_parse_firmwares and the command-line option validation in main() (bad --name,
output outside the project tree, unknown firmware). The full install -> reboot ->
diff-pass orchestration in run_installed_verify needs a real QEMU/KVM/Calamares
session and is out of scope here, matching harness/tests/test_install_boot.py and
harness/tests/test_install_wizard.py's own "no full QEMU mocking" precedent.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.install import run as run_module
from harness.install.boot import Firmware
from harness.install.run import EnvironmentProblem, find_single_iso

PROJECT_ROOT = run_module.PROJECT_ROOT


# --- find_single_iso ---------------------------------------------------------------------


def test_find_single_iso_returns_the_one_file(tmp_path: Path) -> None:
    """Exactly one *.iso is the success case."""
    iso = tmp_path / "kuura-2026.09.24-x86_64.iso"
    iso.write_bytes(b"")
    assert find_single_iso(tmp_path) == iso


def test_find_single_iso_rejects_zero_isos(tmp_path: Path) -> None:
    """An empty (but existing) directory names "none", not a bare count."""
    with pytest.raises(EnvironmentProblem, match="none"):
        find_single_iso(tmp_path)


def test_find_single_iso_rejects_more_than_one_and_names_them(tmp_path: Path) -> None:
    """Two ISOs: the error names both files, not just "2 found"."""
    (tmp_path / "a.iso").write_bytes(b"")
    (tmp_path / "b.iso").write_bytes(b"")
    with pytest.raises(EnvironmentProblem) as caught:
        find_single_iso(tmp_path)
    assert "a.iso" in str(caught.value) and "b.iso" in str(caught.value)


def test_find_single_iso_rejects_a_missing_directory(tmp_path: Path) -> None:
    """A --iso-dir that does not exist at all is an EnvironmentProblem, not an OSError."""
    with pytest.raises(EnvironmentProblem):
        find_single_iso(tmp_path / "does-not-exist")


# --- _parse_firmwares ----------------------------------------------------------------------


def test_parse_firmwares_defaults_to_both_in_a_stable_order() -> None:
    """No --firmware given: both, BIOS before UEFI regardless of how the enum iterates."""
    assert run_module._parse_firmwares(None) == [Firmware.BIOS, Firmware.UEFI]


def test_parse_firmwares_accepts_a_single_choice() -> None:
    """A single firmware name selects only that one."""
    assert run_module._parse_firmwares("uefi") == [Firmware.UEFI]
    assert run_module._parse_firmwares("bios") == [Firmware.BIOS]


def test_parse_firmwares_accepts_both_in_either_written_order() -> None:
    """Writing them in either order still produces the same stable (bios, uefi) result."""
    assert run_module._parse_firmwares("uefi,bios") == [Firmware.BIOS, Firmware.UEFI]
    assert run_module._parse_firmwares("bios,uefi") == [Firmware.BIOS, Firmware.UEFI]


def test_parse_firmwares_rejects_an_unknown_name() -> None:
    """A typo'd firmware name is a ValueError naming the option, not a silent no-op."""
    with pytest.raises(ValueError, match="--firmware"):
        run_module._parse_firmwares("efi")


# --- main(): option validation (exit code 2, no absolute paths leaked) --------------------


@pytest.fixture
def project_out() -> Iterator[Path]:
    """Provide an output directory inside the project tree, removed afterwards."""
    path = PROJECT_ROOT / ".build" / f"pytest-install-run-{uuid.uuid4().hex[:8]}"
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_main_rejects_output_outside_the_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--out outside the project tree is exit code 2 with an "error:" message and no leaked path."""
    assert run_module.main(["--out", str(tmp_path / "out")]) == run_module.EXIT_ENVIRONMENT
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert str(tmp_path) not in captured.err


def test_main_rejects_a_bad_name(project_out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--name with characters outside [a-z0-9_-] is rejected before any ISO lookup."""
    assert run_module.main(["--out", str(project_out), "--name", "Not Valid"]) == run_module.EXIT_ENVIRONMENT
    assert "error:" in capsys.readouterr().err


def test_main_rejects_an_unknown_firmware(project_out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A bad --firmware value is caught by argument validation, not a crash deep in the run."""
    assert run_module.main(["--out", str(project_out), "--firmware", "efi"]) == run_module.EXIT_ENVIRONMENT
    assert "firmware" in capsys.readouterr().err


def test_main_reports_a_missing_iso_directory_as_environment_problem(
    tmp_path: Path, project_out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A --iso-dir that does not exist is exit code 2 (checked before any slow boot)."""
    code = run_module.main(["--out", str(project_out), "--iso-dir", str(tmp_path / "no-such-dir")])
    assert code == run_module.EXIT_ENVIRONMENT
    assert "error:" in capsys.readouterr().err


def test_main_help_exits_zero() -> None:
    """--help prints usage and exits 0 (argparse's own behaviour, worth locking in)."""
    with pytest.raises(SystemExit) as caught:
        run_module.main(["--help"])
    assert caught.value.code == 0


# --- DEFAULT_CREDENTIALS ---------------------------------------------------------------


def test_default_credentials_match_guest_user_defaults() -> None:
    """DEFAULT_CREDENTIALS.username is "desktop", matching harness.shots.guest.GuestUser()'s own default name."""
    from harness.shots.guest import GuestUser

    assert run_module.DEFAULT_CREDENTIALS.username == GuestUser().name

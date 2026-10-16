"""
Tests for harness.install.boot's genuinely pure/testable pieces: InstallVmConfig
validation and build_command's argument assembly, plus InstallVm's process-control
behaviour against a fake QEMU binary (same technique harness/tests/test_capture.py
already uses for harness.shots.vm.Vm - a real subprocess, not a mock, standing in
for QEMU). Full QEMU/KVM boot behaviour (real guest, real screen) is out of scope
here, matching that same precedent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from harness.install.boot import (
    DEFAULT_OVMF_CODE_PATH,
    DEFAULT_OVMF_VARS_TEMPLATE_PATH,
    Firmware,
    InstallVm,
    InstallVmBootError,
    InstallVmConfig,
    InstallVmEnvironmentError,
    build_command,
)

ON_WINDOWS = os.name == "nt"


# --- InstallVmConfig.validate ---------------------------------------------------------


def _config(tmp_path: Path, **overrides: Any) -> InstallVmConfig:
    base: dict[str, Any] = {
        "disk_path": tmp_path / "disk.qcow2",
        "iso_path": tmp_path / "live.iso",
        "firmware": Firmware.BIOS,
    }
    base.update(overrides)
    return InstallVmConfig(**base)


def test_validate_accepts_the_defaults(tmp_path: Path) -> None:
    """The default configuration (only disk_path/iso_path/firmware given) validates cleanly."""
    _config(tmp_path).validate()


@pytest.mark.parametrize(
    "change",
    [
        {"resolution": (100, 100)},
        {"resolution": (99999, 1080)},
        {"memory_mib": 16},
        {"memory_mib": 999999},
        {"cpus": 0},
        {"cpus": 999},
        {"disk_size_gib": 0},
        {"disk_size_gib": 5000},
        {"boot_timeout_s": 0.0},
        {"boot_timeout_s": 999999.0},
    ],
)
def test_validate_rejects_out_of_range_values(tmp_path: Path, change: dict[str, Any]) -> None:
    """Every value that reaches the QEMU command line or a filesystem call is range-checked."""
    with pytest.raises(ValueError):
        _config(tmp_path, **change).validate()


def test_validate_accepts_boundary_values(tmp_path: Path) -> None:
    """The documented inclusive ranges accept their own edges."""
    _config(tmp_path, resolution=(640, 480)).validate()
    _config(tmp_path, resolution=(7680, 4320)).validate()
    _config(tmp_path, memory_mib=512, cpus=1).validate()
    _config(tmp_path, memory_mib=65536, cpus=64).validate()
    _config(tmp_path, disk_size_gib=1).validate()
    _config(tmp_path, disk_size_gib=2000).validate()
    _config(tmp_path, boot_timeout_s=1.0).validate()
    _config(tmp_path, boot_timeout_s=3600.0).validate()


# --- build_command ---------------------------------------------------------------------


def test_build_command_bios_phase1_has_cdrom_no_pflash_no_snapshot(tmp_path: Path) -> None:
    """Phase 1 BIOS: -cdrom present, no pflash, no -snapshot anywhere, no guest-agent device."""
    config = _config(tmp_path, firmware=Firmware.BIOS)
    command = build_command(config, tmp_path, attach_guest_agent=False)
    assert all(isinstance(part, str) for part in command)
    joined = " ".join(command)
    assert "-cdrom" in command
    assert "-snapshot" not in command
    assert "if=pflash" not in joined
    assert "qga.sock" not in joined
    assert "virtserialport" not in joined
    for expected in ("-accel kvm", "-cpu host", "-machine q35", "-nic none", "-display none", "-no-reboot", "order=dc,menu=off"):
        assert expected in joined, expected
    assert "VGA,xres=1920,yres=1080" in joined
    assert "virtio-vga" not in joined


def test_build_command_phase2_omits_cdrom_flag_entirely(tmp_path: Path) -> None:
    """Phase 2 (iso_path=None): the -cdrom flag itself is absent, not merely empty."""
    config = _config(tmp_path, iso_path=None)
    command = build_command(config, tmp_path, attach_guest_agent=True)
    assert "-cdrom" not in command
    joined = " ".join(command)
    assert "qga.sock" in joined and "virtserialport" in joined and "virtio-serial-pci" in joined


def test_build_command_uefi_copies_vars_and_adds_split_pflash(tmp_path: Path) -> None:
    """UEFI: a fresh, writable per-run VARS copy is made; CODE stays read-only and shared."""
    code = tmp_path / "OVMF_CODE.fd"
    vars_template = tmp_path / "OVMF_VARS.fd"
    code.write_bytes(b"CODE")
    vars_template.write_bytes(b"VARS-TEMPLATE")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = _config(tmp_path, firmware=Firmware.UEFI, ovmf_code_path=code, ovmf_vars_template_path=vars_template)

    command = build_command(config, run_dir, attach_guest_agent=False)

    vars_copy = run_dir / "OVMF_VARS.fd"
    assert vars_copy.is_file() and vars_copy.read_bytes() == b"VARS-TEMPLATE"
    joined = " ".join(command)
    assert f"readonly=on,file={code}" in joined
    assert f"if=pflash,format=raw,file={vars_copy}" in joined
    # The template itself must never be the file QEMU is told to write to.
    assert f"file={vars_template}," not in joined.replace(f"file={vars_copy}", "")


def test_build_command_uefi_vars_copy_is_independent_per_run(tmp_path: Path) -> None:
    """Two runs from the same template get two distinct, independently writable copies."""
    code = tmp_path / "OVMF_CODE.fd"
    vars_template = tmp_path / "OVMF_VARS.fd"
    code.write_bytes(b"CODE")
    vars_template.write_bytes(b"TEMPLATE")
    run_a, run_b = tmp_path / "run-a", tmp_path / "run-b"
    run_a.mkdir()
    run_b.mkdir()
    config = _config(tmp_path, firmware=Firmware.UEFI, ovmf_code_path=code, ovmf_vars_template_path=vars_template)

    build_command(config, run_a, attach_guest_agent=False)
    build_command(config, run_b, attach_guest_agent=False)
    (run_a / "OVMF_VARS.fd").write_bytes(b"MUTATED-BY-A")

    assert (run_b / "OVMF_VARS.fd").read_bytes() == b"TEMPLATE"


def test_build_command_escapes_commas_in_paths(tmp_path: Path) -> None:
    """A comma in a path would end a QEMU option value early; it is doubled (QEMU's own escape)."""
    config = _config(tmp_path, disk_path=tmp_path / "a,b.qcow2")
    command = build_command(config, tmp_path, attach_guest_agent=False)
    drive = next(part for part in command if part.startswith("file=") and "if=virtio" in part)
    assert "a,,b.qcow2" in drive


# --- InstallVm: preflight and construction ----------------------------------------------


def test_init_requires_guest_user_when_attach_guest_agent(tmp_path: Path) -> None:
    """Constructing with attach_guest_agent=True and no guest_user is a ValueError, before any boot."""
    with pytest.raises(ValueError, match="guest_user"):
        InstallVm(_config(tmp_path), attach_guest_agent=True)


def test_preflight_names_the_missing_disk_without_a_directory(tmp_path: Path) -> None:
    """A disk that was never created (this class never creates one itself) is a named InstallVmEnvironmentError."""
    secret = tmp_path / "secret-dir"
    secret.mkdir()
    config = _config(tmp_path, disk_path=secret / "missing.qcow2", qemu_binary=sys.executable, require_kvm=False)
    machine = InstallVm(config)
    with pytest.raises(InstallVmEnvironmentError, match="missing.qcow2") as caught:
        machine._preflight()
    assert "secret-dir" not in str(caught.value)


def test_preflight_names_the_missing_iso(tmp_path: Path) -> None:
    """A missing ISO is named (file only) and distinct from a missing disk."""
    disk = tmp_path / "disk.qcow2"
    disk.write_bytes(b"")
    config = _config(tmp_path, disk_path=disk, iso_path=tmp_path / "nope.iso", qemu_binary=sys.executable, require_kvm=False)
    with pytest.raises(InstallVmEnvironmentError, match="nope.iso"):
        InstallVm(config)._preflight()


def test_preflight_names_a_missing_ovmf_file_for_uefi_only(tmp_path: Path) -> None:
    """UEFI with missing firmware files fails preflight; BIOS never looks at OVMF paths at all."""
    disk = tmp_path / "disk.qcow2"
    disk.write_bytes(b"")
    iso = tmp_path / "live.iso"
    iso.write_bytes(b"")
    bad_code = tmp_path / "no-such-code.fd"
    config = _config(
        tmp_path, disk_path=disk, iso_path=iso, firmware=Firmware.UEFI,
        ovmf_code_path=bad_code, qemu_binary=sys.executable, require_kvm=False,
    )
    with pytest.raises(InstallVmEnvironmentError, match="no-such-code.fd"):
        InstallVm(config)._preflight()

    # The same missing file is irrelevant on BIOS.
    bios_config = _config(
        tmp_path, disk_path=disk, iso_path=iso, firmware=Firmware.BIOS,
        ovmf_code_path=bad_code, qemu_binary=sys.executable, require_kvm=False,
    )
    InstallVm(bios_config)._preflight()


def test_preflight_names_a_missing_qemu_binary(tmp_path: Path) -> None:
    """A missing QEMU executable is reported by name."""
    disk = tmp_path / "disk.qcow2"
    disk.write_bytes(b"")
    config = _config(tmp_path, disk_path=disk, qemu_binary="no-such-qemu-binary-anywhere", require_kvm=False)
    with pytest.raises(InstallVmEnvironmentError, match="no-such-qemu-binary-anywhere"):
        InstallVm(config)._preflight()


def test_default_ovmf_paths_are_plausible_absolute_paths() -> None:
    """The documented default OVMF locations are absolute POSIX paths (never relative to CWD).

    Checked as a POSIX string rather than Path.is_absolute(): these paths are
    meant for this module's Linux-only runtime (module docstring), and
    pathlib.Path.is_absolute() considers a leading-"/"-but-no-drive-letter path
    "not absolute" on Windows, which is where this test suite itself also runs.
    """
    assert DEFAULT_OVMF_CODE_PATH.as_posix().startswith("/")
    assert DEFAULT_OVMF_VARS_TEMPLATE_PATH.as_posix().startswith("/")
    assert DEFAULT_OVMF_CODE_PATH != DEFAULT_OVMF_VARS_TEMPLATE_PATH


# --- InstallVm: process lifecycle (fake QEMU binary, real subprocess) -------------------


def write_fake_qemu(tmp_path: Path, body: str) -> Path:
    """Create a shell script that stands in for QEMU (same technique as test_capture.py)."""
    script = tmp_path / "fake-qemu"
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(0o755)
    return script


def process_exists(pid: int) -> bool:
    """Tell whether a process still exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(ON_WINDOWS, reason="needs POSIX processes and UNIX sockets")
def test_a_boot_that_times_out_leaves_no_process_and_no_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """QEMU that starts but never opens its QMP socket: InstallVmBootError, process and run_dir both gone."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    disk = tmp_path / "disk.qcow2"
    disk.write_bytes(b"")
    pid_file = tmp_path / "pid"
    script = write_fake_qemu(tmp_path, f'echo $$ > "{pid_file}"\nexec sleep 60\n')
    config = _config(tmp_path, disk_path=disk, qemu_binary=str(script), require_kvm=False, boot_timeout_s=1.0)
    with pytest.raises(InstallVmBootError):
        with InstallVm(config):
            pytest.fail("the body must not run when the boot fails")
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while process_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not process_exists(pid)
    assert list(scratch.glob("install-vm-*")) == []


@pytest.mark.skipif(ON_WINDOWS, reason="needs POSIX processes and UNIX sockets")
def test_a_qemu_that_exits_at_once_is_reported_quickly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """QEMU that dies immediately does not make the harness wait out the full timeout."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    disk = tmp_path / "disk.qcow2"
    disk.write_bytes(b"")
    script = write_fake_qemu(tmp_path, "echo 'qemu: bad option' >&2\nexit 3\n")
    config = _config(tmp_path, disk_path=disk, qemu_binary=str(script), require_kvm=False, boot_timeout_s=120.0)
    started = time.monotonic()
    with pytest.raises(InstallVmBootError, match="did not come up"):
        InstallVm(config).__enter__()
    assert time.monotonic() - started < 20
    assert list(scratch.glob("install-vm-*")) == []


@pytest.mark.skipif(ON_WINDOWS, reason="needs POSIX processes")
def test_an_exception_in_the_body_still_stops_the_vm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever ends the `with` block, QEMU's whole process group is killed and run_dir removed."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    pids: list[int] = []

    class StartedVm(InstallVm):
        """An InstallVm whose _start runs a plain `sleep` instead of QEMU."""

        def _start(self) -> None:
            self._make_run_dir()
            self._process = subprocess.Popen(["sleep", "60"], start_new_session=True)
            pids.append(self._process.pid)

    with pytest.raises(RuntimeError, match="body failed"):
        with StartedVm(_config(tmp_path)):
            assert process_exists(pids[0])
            raise RuntimeError("body failed")
    assert not process_exists(pids[0])
    assert list(scratch.glob("install-vm-*")) == []


def test_stop_is_safe_before_start_and_twice(tmp_path: Path) -> None:
    """stop() on a VM that never started, and a second stop(), do nothing and do not fail."""
    machine = InstallVm(_config(tmp_path))
    machine.stop()
    machine.stop()
    assert machine.is_alive() is False
    assert machine.serial_tail() == []


def test_reboot_to_disk_only_rejects_a_phase2_instance(tmp_path: Path) -> None:
    """Calling reboot_to_disk_only a second time (iso_path already None) is a ValueError, no QEMU involved."""
    machine = InstallVm(_config(tmp_path, iso_path=None))
    with pytest.raises(ValueError, match="phase-1"):
        machine.reboot_to_disk_only()


def test_reboot_to_disk_only_requires_guest_user_when_requested(tmp_path: Path) -> None:
    """attach_guest_agent=True without guest_user is rejected before any QMP call."""
    machine = InstallVm(_config(tmp_path))
    with pytest.raises(ValueError, match="guest_user"):
        machine.reboot_to_disk_only(attach_guest_agent=True)

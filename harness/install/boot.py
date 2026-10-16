"""
Real-firmware QEMU boot for the live ISO and the disk Calamares installs onto.

LOCKED INTERFACE (docs/ISO_CONTRACT.md "Installed-system verification", 2026-10-13).
This file defines the contract; implementation bodies are intentionally
``raise NotImplementedError`` for the delegated implementation pass to fill in
against real QEMU runs, not guessed.

This is deliberately a SEPARATE class from harness/shots/vm.py's ``Vm``, not a
variant of it: that class boots a pre-built guest directly via ``-kernel``/
``-initrd``, bypassing any bootloader entirely, and always starts from the exact
same ``-snapshot`` overlay so every capture begins from identical state. Satisfying
docs/ISO_CONTRACT.md's own DoD line ("ISO bootaa UEFI + BIOS, asentuu VM:aan...
asennettu jarjestelma lapaisee vaiheiden 3-6 diffit") needs the opposite on every
count: a REAL firmware boot (BIOS/SeaBIOS or UEFI/OVMF, exercising the ISO's own
El Torito/removable-boot path and, after install, the installed disk's own GRUB),
and a disk whose writes PERSIST across the whole install -> reboot -> verify
sequence (no ``-snapshot`` - the installed system must still be there on the second
boot).

Two phases share this one class:
  1. Boot the ISO (with a blank target disk attached) under either firmware, drive
     the live session and Calamares entirely over QMP (screendump + synthetic
     keyboard/mouse - the live session has no guest agent connected yet; see
     harness/install/wizard.py, which drives this phase).
  2. Reboot the SAME disk alone (no ISO/cdrom attached) to verify it is
     independently bootable via the real bootloader Calamares installed. Once up,
     the installed target DOES have a connectable guest agent
     (``qemu-guest-agent.service`` is deliberately enabled there - see
     packages/kuura-installer-config/calamares-defaults/modules/services-systemd.conf
     and docs/ISO_CONTRACT.md), so this phase hands off to
     ``harness.shots.guest.GuestAgent`` and from there to
     ``harness.shots.runner.Runner`` + ``harness/states.toml`` UNCHANGED for the
     real vaiheet 3-6 diff-pass (see harness/install/run.py).

QEMU command-line choices below are carried over from this project's own real,
proven install-verification sessions this phase (docs/ISO_CONTRACT.md / project
memory), not re-derived from scratch:
  - q35 + KVM + ``-cpu host``, like harness/shots/vm.py.
  - ``-vga none -device VGA,xres=...,yres=...`` - NOT ``virtio-vga``: its legacy VGA
    BIOS ROM segfaults ``qemu-system-x86_64`` on a cold BIOS/``-cdrom`` boot on this
    project's own build hosts. harness/shots/vm.py boots via ``-kernel``/``-initrd``
    and never executes a VGA BIOS ROM at all, so it never hits this; this class
    does, every time, so the workaround is load-bearing here, not optional.
  - 1920x1080, not harness/shots/vm.py's 2560x1440: unrelated images/use cases, no
    reason to match; this value is what this project's own recon sessions already
    used and sized their screenshots against.
  - UEFI firmware is OVMF, split pflash: a per-run COPY of the read-only CODE image
    plus a fresh, writable VARS image (never share one VARS image between runs -
    two concurrent/sequential boots would corrupt each other's NVRAM state).
    ``ubuntu-24.04``'s ``ovmf`` package (already installed by the existing
    ``screenshot-harness`` CI job, see .github/workflows/ci.yml) provides the
    default paths below.
  - No guest-agent channel is attached by default: phase 1 has nothing to connect
    it to (see module docstring). ``attach_guest_agent=True`` is for phase 2 only.
  - Full detachment matters: a plain ``subprocess.Popen(..., start_new_session=True)``
    (harness/shots/vm.py's own pattern) is sufficient and already proven here -
    the pitfall this note exists to rule out is launching QEMU via a *shell*
    background job (``cmd &`` + ``disown``) from an *already non-interactive*
    parent, which was observed THIS SESSION to still deliver SIGHUP to the QEMU
    process once that parent exited ("terminating on signal 1"), despite
    ``disown``. ``Popen(start_new_session=True)`` does not have this problem (it
    is a real ``setsid``, done at the syscall level, not a shell job-control
    trick) - do not regress to a shell ``&``.

Standard library only (``GuestAgent``/``Qmp`` are themselves standard-library only).
Linux only at run time (KVM, ``/proc``, process groups), like harness/shots/vm.py.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from harness.shots.guest import GuestAgent, GuestUser
from harness.shots.qmp import Qmp
from harness.shots.vm import RTC_BASE_PATTERN

DEFAULT_OVMF_CODE_PATH = Path("/usr/share/OVMF/OVMF_CODE.fd")
DEFAULT_OVMF_VARS_TEMPLATE_PATH = Path("/usr/share/OVMF/OVMF_VARS.fd")


class Firmware(str, Enum):
    """Which firmware path to boot. Real archiso hybrid media supports both; the DoD requires both be exercised."""

    BIOS = "bios"
    UEFI = "uefi"


class InstallVmEnvironmentError(RuntimeError):
    """The host cannot run this VM at all (no KVM, no QEMU, no OVMF for uefi, ISO or disk path problem)."""


class InstallVmBootError(RuntimeError):
    """QEMU was started but did not come up (exited, sockets or the guest agent timed out)."""


@dataclass(frozen=True)
class InstallVmConfig:
    """
    Everything that decides how one install/boot VM is built.

    Attributes:
        disk_path: The persistent target disk (qcow2). Created by the caller with
            `qemu-img create -f qcow2 <path> <size>G` before phase 1 if it does not
            exist yet; reused UNMODIFIED for phase 2 (never recreated between
            phases - that would erase the install just performed).
        iso_path: The live ISO to attach as a CD-ROM for phase 1. None boots the
            disk alone (phase 2) - this is what makes the boot a genuine test of
            the installed bootloader rather than of the ISO's own boot menu again.
        firmware: BIOS or UEFI.
        disk_size_gib: Size to create disk_path at, if it does not exist yet.
            20 (this project's own proven-sufficient recon value) is the default.
        resolution: Display size in physical pixels (width, height).
        rtc_base: Initial guest clock (UTC), ``YYYY-MM-DDTHH:MM:SS`` - same
            meaning and same default as harness.shots.vm.VmConfig.rtc_base.
            Added 2026-10-16 after the first real diff-pass against goldens
            surfaced a determinism gap: this class had no ``-rtc`` flag at
            all (an oversight from the original interface lock, not a
            deliberate choice - unlike the resolution difference, there was
            never a reason for this one to differ from harness.shots.vm.Vm's
            own pinned clock), so every install-verify screenshot showed the
            real host wall-clock time in the panel instead of the fixed time
            the goldens were captured at.
        memory_mib: Guest RAM in MiB.
        cpus: Number of virtual CPUs.
        qemu_binary: QEMU executable name or path.
        boot_timeout_s: Seconds allowed for QEMU to come up (and, if
            attach_guest_agent was requested by the caller of InstallVm, for the
            guest agent to answer too).
        require_kvm: Check /dev/kvm before starting (tests switch this off, same
            convention as harness.shots.vm.VmConfig.require_kvm).
        ovmf_code_path: Read-only UEFI firmware code image (UEFI only).
        ovmf_vars_template_path: Template UEFI NVRAM vars image (UEFI only) - copied
            to a fresh, writable file per run, never used directly as -drive target.
    """

    disk_path: Path
    iso_path: Path | None
    firmware: Firmware
    disk_size_gib: int = 20
    resolution: tuple[int, int] = (1920, 1080)
    rtc_base: str = "2026-09-25T12:00:00"
    memory_mib: int = 4096
    cpus: int = 4
    qemu_binary: str = "qemu-system-x86_64"
    boot_timeout_s: float = 180.0
    require_kvm: bool = True
    ovmf_code_path: Path = DEFAULT_OVMF_CODE_PATH
    ovmf_vars_template_path: Path = DEFAULT_OVMF_VARS_TEMPLATE_PATH

    def validate(self) -> None:
        """
        Check the values that end up on the QEMU command line or a filesystem call.

        Raises:
            ValueError: an out-of-range size, memory or CPU count, a malformed
                resolution or a malformed rtc_base (same ranges/pattern as
                harness.shots.vm.VmConfig.validate).
        """
        width, height = self.resolution
        if not (640 <= width <= 7680 and 480 <= height <= 4320):
            raise ValueError("resolution is out of range")
        if not RTC_BASE_PATTERN.match(self.rtc_base):
            raise ValueError("rtc_base must look like 2026-09-25T12:00:00")
        if not (512 <= self.memory_mib <= 65536 and 1 <= self.cpus <= 64):
            raise ValueError("memory or CPU count is out of range")
        if not (1 <= self.disk_size_gib <= 2000):
            raise ValueError("disk_size_gib is out of range")
        if not (1.0 <= self.boot_timeout_s <= 3600.0):
            raise ValueError("boot_timeout_s is out of range")


def _escape(path: Path) -> str:
    """
    Escape a path for use inside a comma-separated QEMU option.

    Args:
        path: Any path.

    Returns:
        The path text with every comma doubled (QEMU's escape for ``,`` in values).
    """
    return str(path).replace(",", ",,")


def build_command(config: InstallVmConfig, run_dir: Path, *, attach_guest_agent: bool) -> list[str]:
    """
    Assemble the QEMU command line as a list (never a shell string).

    Args:
        config: The VM configuration.
        run_dir: Private runtime directory that receives the sockets, the serial
            log and (UEFI only) the per-run copy of the VARS image.
        attach_guest_agent: Whether to add the virtio-serial guest-agent device
            (phase 2 only - see module docstring).

    Returns:
        The argument list, program first. Omits ``-cdrom`` entirely when
        config.iso_path is None (phase 2) - not an empty/absent value, the flag
        itself must not be present, so QEMU's own default boot order has nothing
        to compete with the disk.
    """
    width, height = config.resolution
    command: list[str] = [
        config.qemu_binary,
        "-name", "install-vm",
        "-machine", "q35", "-accel", "kvm", "-cpu", "host",
        "-smp", str(config.cpus), "-m", str(config.memory_mib),
    ]

    if config.firmware == Firmware.UEFI:
        # Split pflash: the CODE image stays read-only and shared; VARS is a fresh,
        # per-run writable copy (see module docstring - never share one VARS file
        # between runs, it would let two boots corrupt each other's NVRAM state).
        vars_copy = run_dir / "OVMF_VARS.fd"
        shutil.copyfile(config.ovmf_vars_template_path, vars_copy)
        os.chmod(vars_copy, 0o600)
        command += [
            "-drive", f"if=pflash,format=raw,readonly=on,file={_escape(config.ovmf_code_path)}",
            "-drive", f"if=pflash,format=raw,file={_escape(vars_copy)}",
        ]

    # No -snapshot: this disk's writes must persist across install -> reboot -> verify.
    command += ["-drive", f"file={_escape(config.disk_path)},if=virtio,format=qcow2"]
    if config.iso_path is not None:
        command += ["-cdrom", _escape(config.iso_path)]
    # "order=dc": try the CD-ROM first, then the first hard disk. Harmless and
    # correct in both phases - phase 1's disk is blank (nothing to compete with the
    # ISO), phase 2 has no CD-ROM attached at all (the "d" entry simply does not
    # exist, so QEMU falls straight through to "c"). SeaBIOS and OVMF (via the
    # QEMU_EFI "QemuBootOrder" fw_cfg driver) both honour this legacy option.
    command += ["-boot", "order=dc,menu=off"]

    command += [
        # NOT virtio-vga: see module docstring - its legacy VGA BIOS ROM segfaults
        # qemu-system-x86_64 on a cold BIOS/-cdrom boot on this project's hosts.
        "-vga", "none",
        "-device", f"VGA,xres={width},yres={height}",
        # Pin the guest clock the same way harness.shots.vm.Vm does, for the same
        # reason: the Runner diff-pass compares against goldens captured at a fixed
        # time, so the panel clock must show that same fixed time, not whatever the
        # real host's wall clock happens to read on a given CI/dev-machine run.
        "-rtc", f"base={config.rtc_base},clock=vm",
        "-device", "usb-ehci", "-device", "usb-tablet",
        "-nic", "none",
        "-display", "none",
        "-serial", f"file:{_escape(run_dir / 'serial.log')}",
        "-qmp", f"unix:{_escape(run_dir / 'qmp.sock')},server=on,wait=off",
    ]

    if attach_guest_agent:
        command += [
            "-chardev", f"socket,id=qga0,path={_escape(run_dir / 'qga.sock')},server=on,wait=off",
            "-device", "virtio-serial-pci",
            "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
        ]

    command += ["-no-reboot"]
    return command


class InstallVm:
    """
    Context manager around one QEMU/KVM real-firmware boot.

    Usage, phase 1 (install)::

        config = InstallVmConfig(disk_path=disk, iso_path=iso, firmware=Firmware.BIOS)
        with InstallVm(config) as vm:
            vm.qmp.screendump(Path("welcome.png"))
            ...

    Usage, phase 2 (verify), reusing the SAME disk_path from phase 1::

        config = InstallVmConfig(disk_path=disk, iso_path=None, firmware=Firmware.BIOS)
        with InstallVm(config, attach_guest_agent=True, guest_user=GuestUser()) as vm:
            assert vm.agent is not None
            ...

    On entry QEMU is started (and, if requested, the guest agent has answered); on
    every exit path (normal end, exception, Ctrl-C, failed boot) QEMU is stopped,
    its whole process group killed and its private runtime directory removed -
    identical contract to harness.shots.vm.Vm, deliberately, so a caller that
    already knows that class has nothing new to learn here.

    Args:
        config: The VM configuration.
        attach_guest_agent: Wait for and connect a GuestAgent after boot. Only
            meaningful (and only to be set True) for a phase-2 config
            (config.iso_path is None) - the default account created by Calamares'
            own user-creation step (WizardCredentials, see wizard.py) determines
            `guest_user`'s name/uid, not a value this class invents.
        guest_user: Required when attach_guest_agent is True. Using the username
            "desktop" for the test account (WizardCredentials) lets the caller pass
            the existing harness.shots.guest.GuestUser()'s own defaults unchanged
            here (name="desktop", uid=1000, group="desktop" - a fresh Arch install's
            first regular user already lands on uid 1000 with a same-named primary
            group under Calamares' real useradd defaults) - a deliberate
            convenience, not a coincidence to re-derive.

    Attributes:
        qmp: The QMP client (after start), always present.
        agent: The guest-agent client; present only when attach_guest_agent was True.
        timings: Boot milestones in seconds since QEMU started. At least
            ``qmp_connected_s``; also ``agent_up_s`` when attach_guest_agent is True
            (same keys harness.shots.vm.Vm.timings uses, for a familiar manifest
            shape in harness/install/run.py's own output).
        final_serial_tail: The last serial console lines, saved when the VM stops.
    """

    def __init__(
        self,
        config: InstallVmConfig,
        *,
        attach_guest_agent: bool = False,
        guest_user: GuestUser | None = None,
    ) -> None:
        if attach_guest_agent and guest_user is None:
            raise ValueError("guest_user is required when attach_guest_agent is True")
        self.config = config
        self.qmp: Qmp | None = None
        self.agent: GuestAgent | None = None
        self.timings: dict[str, float] = {}
        self.final_serial_tail: list[str] = []
        self._attach_guest_agent = attach_guest_agent
        self._guest_user = guest_user
        self._process: subprocess.Popen[bytes] | None = None
        self._run_dir: Path | None = None
        self._log_file: Any = None
        self._t0 = 0.0

    def __enter__(self) -> InstallVm:
        """
        Start the VM.

        Returns:
            This object, with ``qmp`` connected (and ``agent`` too, if requested).

        Raises:
            InstallVmEnvironmentError: no KVM, no QEMU, or a disk/ISO/OVMF file missing.
            InstallVmBootError: the guest did not come up in time or QEMU exited.
        """
        try:
            self._start()
        except BaseException:
            self.stop()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Stop the VM on every exit path; exceptions from the body propagate unchanged."""
        self.stop()

    def is_alive(self) -> bool:
        """
        Returns:
            True while the QEMU process is still running.
        """
        return self._process is not None and self._process.poll() is None

    def _preflight(self) -> None:
        """
        Check that the host can run this VM before spending any time starting it.

        Raises:
            InstallVmEnvironmentError: KVM is not usable, QEMU is missing, the disk
                (must already exist - this class never creates it, see
                InstallVmConfig.disk_path's own docstring), the ISO, or (UEFI only)
                an OVMF firmware file is missing. Messages name only the file, never
                a directory, matching harness.shots.vm.Vm's own convention.
            ValueError: the configuration is malformed.
        """
        self.config.validate()
        if self.config.require_kvm and not (os.access("/dev/kvm", os.R_OK) and os.access("/dev/kvm", os.W_OK)):
            raise InstallVmEnvironmentError("/dev/kvm is not accessible (is this user in the kvm group?)")
        if shutil.which(self.config.qemu_binary) is None:
            raise InstallVmEnvironmentError(f"{self.config.qemu_binary} was not found in PATH")
        if not self.config.disk_path.is_file():
            raise InstallVmEnvironmentError(
                f"disk image {self.config.disk_path.name!r} is missing; create it first "
                f"(qemu-img create -f qcow2 ... {self.config.disk_size_gib}G)"
            )
        if self.config.iso_path is not None and not self.config.iso_path.is_file():
            raise InstallVmEnvironmentError(f"ISO {self.config.iso_path.name!r} is missing")
        if self.config.firmware == Firmware.UEFI:
            for path in (self.config.ovmf_code_path, self.config.ovmf_vars_template_path):
                if not path.is_file():
                    raise InstallVmEnvironmentError(
                        f"OVMF firmware file {path.name!r} is missing; install the ovmf package"
                    )

    def _make_run_dir(self) -> Path:
        """
        Create the private runtime directory.

        Returns:
            A new directory that only this user can enter (mode 0700); it holds the
            sockets, the serial log and (UEFI only) the per-run VARS copy.
        """
        run_dir = Path(tempfile.mkdtemp(prefix="install-vm-"))
        # mkdtemp already creates it with mode 0700; the explicit chmod documents and
        # enforces the requirement even if that ever changes (see harness.shots.vm.Vm's
        # identical comment - 0700 is the restrictive end of the permission range, not
        # the permissive one that a generic insecure-permissions linter heuristic expects).
        os.chmod(run_dir, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        self._run_dir = run_dir
        return run_dir

    def _start(self) -> None:
        """
        Start QEMU and connect (and, if requested, wait for the guest agent).

        Raises:
            InstallVmEnvironmentError: see ``_preflight``.
            InstallVmBootError: the guest did not come up.
        """
        self._preflight()
        run_dir = self._make_run_dir()
        command = build_command(self.config, run_dir, attach_guest_agent=self._attach_guest_agent)
        self._log_file = open(run_dir / "qemu.log", "wb")  # noqa: SIM115 - closed in stop()
        self._t0 = time.monotonic()
        # start_new_session: a real setsid at the syscall level, so stop() can kill
        # QEMU's whole process group in one call. Deliberately NOT a shell background
        # job (`cmd &` + `disown`) - see module docstring, that pattern was observed
        # this project to still deliver SIGHUP to QEMU once the launching shell exited.
        self._process = subprocess.Popen(
            command, stdout=self._log_file, stderr=subprocess.STDOUT, start_new_session=True
        )
        deadline_s = self.config.boot_timeout_s
        socket_wait = min(30.0, deadline_s)
        try:
            self.qmp = Qmp.connect(
                run_dir / "qmp.sock", self.config.resolution, timeout=socket_wait, alive=self.is_alive
            )
            self.timings["qmp_connected_s"] = round(time.monotonic() - self._t0, 1)
            if self._attach_guest_agent:
                assert self._guest_user is not None  # enforced in __init__
                self.agent = GuestAgent.connect(run_dir / "qga.sock", self._guest_user, socket_wait, self.is_alive)
                self.agent.wait_ready(deadline_s, alive=self.is_alive)
                self.timings["agent_up_s"] = round(time.monotonic() - self._t0, 1)
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise InstallVmBootError(f"the VM did not come up: {exc}") from exc

    def reboot_to_disk_only(
        self,
        *,
        attach_guest_agent: bool = False,
        guest_user: GuestUser | None = None,
        resolution: tuple[int, int] | None = None,
    ) -> None:
        """
        Only valid on a phase-1 instance (config.iso_path was set): the transition
        from "just finished installing" to phase 2 in the SAME disk's lifetime.

        Asks the guest to shut down cleanly first (QMP ``system_powerdown``, with a
        bounded wait), falling back to a hard stop if it does not respond - mirrors
        harness.shots.vm.Vm.stop()'s own "ask nicely, then kill the group" order.
        Then relaunches the identical disk_path with no ISO attached (so the real
        bootloader is what responds this time) and, per this call's own
        ``attach_guest_agent``/``guest_user`` arguments, optionally waits for the
        guest agent.

        Mutates this instance in place (new run_dir, new qmp/process/agent) rather
        than requiring the caller to open a second ``with InstallVm(...)`` block -
        the one thing that must NOT happen between phases is disk_path being
        recreated, and keeping it to one instance makes that a non-issue instead of
        a caller discipline the type cannot enforce.

        NOTE on this method's own signature: the locked interface's stub originally
        carried no parameters ("Takes no new config: firmware stays what
        config.firmware already was"), yet its own prose says the guest-agent wait
        is "per this call's own attach_guest_agent/guest_user arguments" - two
        claims that cannot both be literally true, since InstallVm.__init__'s own
        attach_guest_agent is fixed at construction time (phase 1 is always built
        with the default attach_guest_agent=False, per the class docstring's own
        phase-1 usage example) and this method is what performs the actual
        transition into phase 2. Resolved by keeping "no new config" literally (no
        InstallVmConfig replacement - firmware, resolution etc. are unchanged BY
        DEFAULT) while adding the two keyword arguments the prose unambiguously
        requires; flagged here rather than silently picking one reading, per this
        project's own standing "escalate the contradiction" rule.

        NOTE on ``resolution`` (added after the first real diff-pass run against
        harness/goldens/, 2026-10-14): phase 1 (the Calamares wizard, driven by
        harness.install.wizard.run_install) and phase 2 (this reboot, SDDM login,
        then harness.shots.runner.Runner's own diff-pass) are two SEPARATE QEMU
        processes already (see this method's own body below) - resolution has
        never actually had to be one VM-wide constant, only the module docstring's
        "unrelated images/use cases" note assumed it did. The diff-pass compares
        against goldens captured by harness.shots.vm.Vm at ITS OWN resolution
        (2560x1440 by default), so phase 2 needs to match that, while phase 1's
        own wizard automation (every Calamares screen coordinate in wizard.py)
        stays calibrated at whatever resolution phase 1 already used - this
        parameter lets the caller (harness.install.run, the one place that
        actually cares about matching harness.shots.vm's resolution) make that
        choice explicitly, without this class hardcoding an assumption about why
        phase 2 would want a different resolution than phase 1.

        Args:
            attach_guest_agent: Wait for and connect a GuestAgent once the disk is
                back up. Same meaning as the constructor's own argument.
            guest_user: Required when attach_guest_agent is True.
            resolution: Override the display resolution for phase 2 only (phase 1
                already shut down by the time this takes effect). ``None`` (the
                default) keeps ``config.resolution`` - i.e. true "nothing but
                iso_path changed" behaviour. Validated the same way the
                constructor validates ``InstallVmConfig.resolution``.

        Raises:
            ValueError: called on a phase-2 instance (iso_path is already None), or
                attach_guest_agent is True without a guest_user.
            InstallVmBootError: the disk did not come back up (GRUB missing/broken,
                boot hung, or - if requested - the guest agent never answered).
        """
        if self.config.iso_path is None:
            raise ValueError("reboot_to_disk_only is only valid on a phase-1 instance (iso_path was set)")
        if attach_guest_agent and guest_user is None:
            raise ValueError("guest_user is required when attach_guest_agent is True")

        new_config = dataclasses.replace(
            self.config,
            iso_path=None,
            **({"resolution": resolution} if resolution is not None else {}),
        )
        new_config.validate()  # same out-of-range check InstallVmConfig() itself gets at construction

        if self.qmp is not None and self.is_alive():
            try:
                self.qmp.execute("system_powerdown", timeout=5.0)
            except (TimeoutError, ConnectionError, RuntimeError, OSError):
                pass  # falls through to the hard stop below
            deadline = time.monotonic() + 60.0
            while self.is_alive() and time.monotonic() < deadline:
                time.sleep(0.5)
        self.stop()

        self.config = new_config
        self._attach_guest_agent = attach_guest_agent
        self._guest_user = guest_user
        self.timings = {}
        self.final_serial_tail = []
        try:
            self._start()
        except BaseException:
            self.stop()
            raise

    def serial_tail(self, lines: int = 30) -> list[str]:
        """
        Returns:
            The last `lines` lines of the guest's serial console; empty when there
            is no log (yet, or any more). Same contract as harness.shots.vm.Vm's
            equivalent method.
        """
        if self._run_dir is None:
            return []
        try:
            text = (self._run_dir / "serial.log").read_text(errors="replace")
        except OSError:
            return []
        return text.splitlines()[-lines:]

    def stop(self) -> None:
        """
        Stop the VM and remove everything it left behind. Safe to call repeatedly
        and from a half-started state. Same order/contract as
        harness.shots.vm.Vm.stop(): ask QEMU to quit, wait briefly, kill the whole
        process group regardless, close channels, delete the runtime directory.
        """
        asked_to_quit = False
        if self.qmp is not None and self.is_alive():
            try:
                self.qmp.quit()
                asked_to_quit = True
            except (TimeoutError, ConnectionError, RuntimeError, OSError):
                pass  # falls through to the kill below
        process = self._process
        if process is not None:
            if asked_to_quit:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, AttributeError):
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL cannot be ignored
                pass
        for channel in (self.qmp, self.agent):
            if channel is not None:
                channel.close()
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        if self._run_dir is not None:
            self.final_serial_tail = self.serial_tail()
            shutil.rmtree(self._run_dir, ignore_errors=True)
            self._run_dir = None
        self._process = None
        self.qmp = None
        self.agent = None

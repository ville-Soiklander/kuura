"""
The virtual machine of the screenshot harness.

``Vm`` is a context manager that boots the guest image under QEMU/KVM, connects the
QMP and guest-agent channels, waits until the agent inside the guest answers and, on
EVERY exit path (normal end, exception, Ctrl-C, failed boot), stops QEMU, kills its
whole process group and removes the private runtime directory.

Design decisions (all inherited from the feasibility spike, see harness/spike/README.md):

* KVM with ``-cpu host``: software emulation of a Plasma boot is far too slow.
* ``virtio-vga`` at the configured resolution, no ``-display`` and no GL: the guest
  renders in software and QEMU only receives finished frames; there is no host GPU
  involved anywhere.
* ``usb-tablet`` (absolute pointer) so cursor positions are well defined.
* ``-nic none``: the guest has no network.
* ``-snapshot``: all writes go to a throw-away overlay, so the image is never modified
  and every boot starts from exactly the same disk state.
* ``-rtc base=...,clock=vm``: the guest wall clock starts at a fixed date.
* Sockets and the overlay live in a private (mode 0700) temporary directory that only
  this user can enter. The command line is always a list, never a shell string.

Standard library only. Linux only at run time (KVM, ``/proc``, process groups); the
module itself imports everywhere so the pure helpers can be unit-tested anywhere.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.shots.guest import GuestAgent, GuestUser
from harness.shots.qmp import Qmp

# The initial guest clock must look like a second-resolution ISO timestamp (QEMU's
# -rtc base= syntax).
RTC_BASE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

# Kernel command line. root=/dev/vda: the only disk. No "quiet": the serial log is the
# evidence when a boot fails.
KERNEL_CMDLINE = "root=/dev/vda rw console=ttyS0,115200 loglevel=4 net.ifnames=0 systemd.show_status=1"

IMAGE_FILES = ("root.img", "vmlinuz", "initramfs.img")


class VmEnvironmentError(RuntimeError):
    """The machine cannot run the VM at all (no KVM, no QEMU, image files missing)."""


class VmBootError(RuntimeError):
    """The VM was started but did not come up (QEMU exited, sockets or agent timed out)."""


@dataclass(frozen=True)
class VmConfig:
    """
    Everything that decides how the VM is built.

    Attributes:
        image_dir: Directory holding ``root.img``, ``vmlinuz`` and ``initramfs.img``.
        resolution: Display size in physical pixels (width, height).
        rtc_base: Initial guest clock (UTC), ``YYYY-MM-DDTHH:MM:SS``.
        memory_mib: Guest RAM in MiB.
        cpus: Number of virtual CPUs.
        qemu_binary: QEMU executable name or path.
        boot_timeout_s: Seconds allowed for QEMU to come up and the guest agent to answer.
        require_kvm: Check ``/dev/kvm`` before starting (tests switch this off).
        user: The desktop user of the image.
    """

    image_dir: Path
    resolution: tuple[int, int] = (2560, 1440)
    rtc_base: str = "2026-09-25T12:00:00"
    memory_mib: int = 4096
    cpus: int = 4
    qemu_binary: str = "qemu-system-x86_64"
    boot_timeout_s: float = 180.0
    require_kvm: bool = True
    user: GuestUser = field(default_factory=GuestUser)

    def validate(self) -> None:
        """
        Check the values that end up on the QEMU command line.

        Raises:
            ValueError: on a malformed RTC base or an out-of-range size, memory or CPU count.
        """
        if not RTC_BASE_PATTERN.match(self.rtc_base):
            raise ValueError("rtc_base must look like 2026-09-25T12:00:00")
        width, height = self.resolution
        if not (640 <= width <= 7680 and 480 <= height <= 4320):
            raise ValueError("resolution is out of range")
        if not (512 <= self.memory_mib <= 65536 and 1 <= self.cpus <= 64):
            raise ValueError("memory or CPU count is out of range")


def _escape(path: Path) -> str:
    """
    Escape a path for use inside a comma-separated QEMU option.

    Args:
        path: Any path.

    Returns:
        The path text with every comma doubled (QEMU's escape for ``,`` in values).
    """
    return str(path).replace(",", ",,")


def build_command(config: VmConfig, run_dir: Path) -> list[str]:
    """
    Assemble the QEMU command line as a list (never a shell string).

    Args:
        config: The VM configuration.
        run_dir: Private runtime directory that receives the sockets and the serial log.

    Returns:
        The argument list, program first.
    """
    image = config.image_dir
    width, height = config.resolution
    return [
        config.qemu_binary,
        "-name", "harness-vm",
        "-machine", "q35", "-accel", "kvm", "-cpu", "host",
        "-smp", str(config.cpus), "-m", str(config.memory_mib),
        "-kernel", str(image / "vmlinuz"), "-initrd", str(image / "initramfs.img"),
        "-append", KERNEL_CMDLINE,
        # -snapshot: writes go to a temporary overlay; the image never changes.
        "-snapshot",
        "-drive", f"file={_escape(image / 'root.img')},if=virtio,format=raw",
        "-vga", "none",
        "-device", f"virtio-vga,xres={width},yres={height}",
        "-device", "usb-ehci", "-device", "usb-tablet",
        "-nic", "none",
        "-display", "none",
        "-rtc", f"base={config.rtc_base},clock=vm",
        "-serial", f"file:{_escape(run_dir / 'serial.log')}",
        "-qmp", f"unix:{_escape(run_dir / 'qmp.sock')},server=on,wait=off",
        "-chardev", f"socket,id=qga0,path={_escape(run_dir / 'qga.sock')},server=on,wait=off",
        "-device", "virtio-serial-pci",
        "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
        "-no-reboot",
    ]


class Sampler(threading.Thread):
    """
    Samples the CPU time and resident memory of the QEMU process (and the machine's
    busy time and free memory) once per second, so the cost of a run can be reported.

    Args:
        pid: Process id of QEMU.
    """

    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True)
        self.pid = pid
        self.stop_flag = threading.Event()
        self.samples: list[dict[str, float]] = []
        self._ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

    def _read(self) -> dict[str, float] | None:
        """
        Take one sample.

        Returns:
            The sample, or None when the process (or ``/proc``) is gone.
        """
        try:
            stat = Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()
            # After the command name, utime is field index 11 and stime index 12.
            proc_seconds = (int(stat[11]) + int(stat[12])) / self._ticks
            rss_kb = 0
            for line in Path(f"/proc/{self.pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
            cpu = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
            idle = cpu[3] + cpu[4]  # idle + iowait
            avail_kb = 0
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
        except (OSError, IndexError, ValueError):
            return None
        return {
            "t": time.monotonic(),
            "proc_cpu_s": proc_seconds,
            "rss_mb": rss_kb / 1024,
            "sys_busy": float(sum(cpu) - idle),
            "sys_total": float(sum(cpu)),
            "mem_avail_mb": avail_kb / 1024,
        }

    def run(self) -> None:
        """Thread body: sample until asked to stop or the process disappears."""
        while not self.stop_flag.is_set():
            sample = self._read()
            if sample is None:
                return
            self.samples.append(sample)
            self.stop_flag.wait(1.0)


def summarise_resources(samples: list[dict[str, float]], t_start: float, t_end: float) -> dict[str, float]:
    """
    Reduce raw samples to the numbers reported for a run.

    Args:
        samples: Output of ``Sampler``.
        t_start: Monotonic time of the start of the window.
        t_end: Monotonic time of the end of the window.

    Returns:
        Average CPU use (in cores and as percent of the whole machine), CPU seconds,
        peak resident memory of QEMU and the lowest free host memory inside the window;
        empty when fewer than two samples fall in it.
    """
    window = [s for s in samples if t_start <= s["t"] <= t_end]
    if len(window) < 2:
        return {}
    first, last = window[0], window[-1]
    wall = last["t"] - first["t"]
    if wall <= 0:
        return {}
    sys_delta = last["sys_total"] - first["sys_total"]
    return {
        "window_s": round(wall, 1),
        "qemu_avg_cores": round((last["proc_cpu_s"] - first["proc_cpu_s"]) / wall, 2),
        "qemu_cpu_seconds": round(last["proc_cpu_s"] - first["proc_cpu_s"], 1),
        "system_busy_pct": round(100 * (last["sys_busy"] - first["sys_busy"]) / max(sys_delta, 1), 1),
        "qemu_peak_rss_mb": round(max(s["rss_mb"] for s in window)),
        "host_mem_available_min_mb": round(min(s["mem_avail_mb"] for s in window)),
        "host_mem_available_start_mb": round(first["mem_avail_mb"]),
    }


def host_summary() -> dict[str, Any]:
    """
    Describe the machine that runs the capture (for the manifest).

    Returns:
        CPU model, logical CPU count and total memory in MiB; fields that cannot be
        read (non-Linux host) are left out.
    """
    info: dict[str, Any] = {"cpu_count": os.cpu_count()}
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                info["mem_total_mb"] = round(int(line.split()[1]) / 1024)
                break
    except (OSError, ValueError, IndexError):
        pass
    return info


class Vm:
    """
    Context manager around one QEMU/KVM guest.

    Usage::

        with Vm(VmConfig(image_dir=Path(".build/vm"))) as vm:
            vm.qmp.screendump(Path("shot.png"))
            vm.agent.run_as_user(["dolphin"])

    On entry QEMU is started and the guest agent has answered; on exit (whatever the
    reason) QEMU is stopped and its runtime directory is deleted.

    Args:
        config: The VM configuration.

    Attributes:
        qmp: The QMP client (after start).
        agent: The guest-agent client (after start).
        timings: Boot milestones in seconds since QEMU started (``qmp_connected_s``,
            ``agent_up_s``).
        final_serial_tail: The last serial console lines, saved when the VM stops (the
            runtime directory is deleted then), for error reports after the fact.
    """

    def __init__(self, config: VmConfig) -> None:
        self.config = config
        self.qmp: Qmp | None = None
        self.agent: GuestAgent | None = None
        self.timings: dict[str, float] = {}
        self.final_serial_tail: list[str] = []
        self._process: subprocess.Popen[bytes] | None = None
        self._run_dir: Path | None = None
        self._sampler: Sampler | None = None
        self._log_file: Any = None
        self._t0 = 0.0

    def __enter__(self) -> Vm:
        """
        Start the VM.

        Returns:
            This object, with ``qmp`` and ``agent`` connected.

        Raises:
            VmEnvironmentError: no KVM, no QEMU or missing image files.
            VmBootError: the guest did not come up in time or QEMU exited.
        """
        try:
            self.start()
        except BaseException:
            self.stop()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Stop the VM on every exit path; exceptions from the body propagate unchanged."""
        self.stop()

    @property
    def t0(self) -> float:
        """Monotonic time at which QEMU was started."""
        return self._t0

    def is_alive(self) -> bool:
        """
        Tell whether the QEMU process is still running.

        Returns:
            True while it runs.
        """
        return self._process is not None and self._process.poll() is None

    def _preflight(self) -> None:
        """
        Check that the host can run the VM.

        Raises:
            VmEnvironmentError: KVM is not usable, QEMU is not installed or an image
                file is missing (names the file, never the directory).
            ValueError: the configuration is malformed.
        """
        self.config.validate()
        if self.config.require_kvm and not (os.access("/dev/kvm", os.R_OK) and os.access("/dev/kvm", os.W_OK)):
            raise VmEnvironmentError("/dev/kvm is not accessible (is this user in the kvm group?)")
        if shutil.which(self.config.qemu_binary) is None:
            raise VmEnvironmentError(f"{self.config.qemu_binary} was not found in PATH")
        for name in IMAGE_FILES:
            if not (self.config.image_dir / name).is_file():
                raise VmEnvironmentError(f"image file {name} is missing; build the guest image first")

    def _make_run_dir(self) -> Path:
        """
        Create the private runtime directory.

        Returns:
            A new directory that only this user can enter (mode 0700); it holds the
            sockets, the serial log and QEMU's snapshot overlay.
        """
        run_dir = Path(tempfile.mkdtemp(prefix="vm-"))
        # mkdtemp already creates it with mode 0700; the explicit chmod documents and
        # enforces the requirement even if that ever changes. 0700 (owner-only) is the
        # restrictive end of the permission range, not the permissive one - Semgrep's
        # generic insecure-file-permissions rule reads 0700 as "too open" using a
        # heuristic tuned for regular files, which does not apply to a directory that
        # must deny group/other access entirely; the 0o644 it suggests would not even
        # be traversable.
        os.chmod(run_dir, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        self._run_dir = run_dir
        return run_dir

    def start(self) -> None:
        """
        Start QEMU and connect. Prefer the ``with`` statement, which also guarantees cleanup.

        Raises:
            VmEnvironmentError: see ``_preflight``.
            VmBootError: the guest did not come up.
        """
        self._preflight()
        run_dir = self._make_run_dir()
        command = build_command(self.config, run_dir)
        # -snapshot puts its overlay file in $TMPDIR; pointing that at the private
        # directory means removing the directory removes the overlay too.
        env = dict(os.environ, TMPDIR=str(run_dir))
        self._log_file = open(run_dir / "qemu.log", "wb")  # noqa: SIM115 - closed in stop()
        self._t0 = time.monotonic()
        # start_new_session: QEMU leads its own process group, so stop() can kill it and
        # anything it spawned in one call, and a Ctrl-C at the terminal does not reach it
        # before our own cleanup ran.
        self._process = subprocess.Popen(
            command, stdout=self._log_file, stderr=subprocess.STDOUT, env=env, start_new_session=True
        )
        self._sampler = Sampler(self._process.pid)
        self._sampler.start()

        deadline_s = self.config.boot_timeout_s
        # QEMU creates its sockets within a second or two; a short configured boot
        # timeout must also bound this wait.
        socket_wait = min(30.0, deadline_s)
        try:
            self.qmp = Qmp.connect(
                run_dir / "qmp.sock",
                self.config.resolution,
                timeout=socket_wait,
                alive=self.is_alive,
            )
            self.timings["qmp_connected_s"] = round(time.monotonic() - self._t0, 1)
            self.agent = GuestAgent.connect(run_dir / "qga.sock", self.config.user, socket_wait, self.is_alive)
            self.agent.wait_ready(deadline_s, alive=self.is_alive)
            self.timings["agent_up_s"] = round(time.monotonic() - self._t0, 1)
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise VmBootError(f"the VM did not come up: {exc}") from exc

    def serial_tail(self, lines: int = 30) -> list[str]:
        """
        Return the last lines of the guest's serial console (boot diagnostics).

        Args:
            lines: How many lines to return.

        Returns:
            The lines; empty when there is no log (yet or any more).
        """
        if self._run_dir is None:
            return []
        try:
            text = (self._run_dir / "serial.log").read_text(errors="replace")
        except OSError:
            return []
        return text.splitlines()[-lines:]

    def resources(self, t_start: float | None = None, t_end: float | None = None) -> dict[str, float]:
        """
        Summarise CPU and memory use of the QEMU process.

        Args:
            t_start: Monotonic start of the window (QEMU start when None).
            t_end: Monotonic end of the window (now when None).

        Returns:
            The summary (see ``summarise_resources``); empty without samples.
        """
        if self._sampler is None:
            return {}
        return summarise_resources(
            self._sampler.samples,
            self._t0 if t_start is None else t_start,
            time.monotonic() if t_end is None else t_end,
        )

    def stop(self) -> None:
        """
        Stop the VM and remove everything it left behind. Safe to call repeatedly and
        from a half-started state.

        Order: ask QEMU to quit (clean), wait briefly, then kill the whole process
        group (nothing survives), close the channels, delete the runtime directory.
        """
        if self._sampler is not None:
            self._sampler.stop_flag.set()
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
                # Give QEMU a moment to exit by itself (it flushes its state); a
                # process that was never asked to quit is killed at once.
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            # Always kill the group, even after a clean exit: it removes any straggler
            # that QEMU spawned. A vanished group is not an error.
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

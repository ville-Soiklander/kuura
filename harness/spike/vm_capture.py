#!/usr/bin/env python3
"""
Boot the guest image under QEMU/KVM without a host GPU and take a screenshot
from the HOST once the desktop is stable.

WHY host-side: the screenshot comes from the QEMU monitor command `screendump`,
i.e. from the emulated display device, so nothing runs inside the guest to
produce it and the guest cannot influence how it is captured.

What it does, in order:
  1. Starts QEMU (direct kernel boot, virtio-vga, no network, no display window)
     with a QMP control socket, a guest-agent socket and a serial log file.
  2. Every --interval seconds takes a `screendump` (PNG) and hashes it.
  3. Declares the desktop "stable" when (a) the guest agent reports that the
     Plasma shell process is running, (b) the frame is not blank (PNG size above
     --min-png-bytes) and (c) --identical consecutive frames are byte-identical.
  4. Keeps the last frame as <tag>.png, writes <tag>-summary.json (timings, host
     CPU and memory use, frame history) and quits the VM.

The disk is opened with -snapshot: all writes go to a temporary overlay, so the
image is never modified and every boot starts from exactly the same disk state.

Only the Python standard library is used. Exit status: 0 = stable screenshot
taken, 1 = timeout / QEMU died (partial evidence is still written), 2 = bad input.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import select
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# Tags become part of file names and of the QEMU process name.
TAG_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
# Second-resolution ISO timestamp accepted by QEMU's -rtc base=.
RTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


class LineSocket:
    """
    Newline-delimited JSON over a UNIX socket (used for QMP and the guest agent).

    Args:
        path: Filesystem path of the UNIX socket to connect to.
        timeout: Seconds to wait for the socket file to appear.

    Raises:
        TimeoutError: if the socket does not accept a connection in time.
    """

    def __init__(self, path: Path, timeout: float) -> None:
        self.buf = b""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.sock.connect(str(path))
                return
            except (FileNotFoundError, ConnectionRefusedError):
                # QEMU creates the socket a moment after it starts.
                if time.monotonic() > deadline:
                    raise TimeoutError(f"socket {path.name} did not come up")
                time.sleep(0.1)

    def send(self, obj: dict) -> None:
        """Send one JSON object followed by a newline."""
        self.sock.sendall(json.dumps(obj).encode() + b"\n")

    def recv(self, timeout: float) -> dict | None:
        """
        Read one JSON line.

        Returns:
            The decoded object, or None if no complete line arrived in `timeout`
            seconds (the connection stays usable).
        """
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([self.sock], [], [], left)
            if not ready:
                return None
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("socket closed by peer")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        line = line.strip(b"\xff")  # guest-sync-delimited marker, harmless otherwise
        return json.loads(line) if line else self.recv(timeout)

    def close(self) -> None:
        """Close the socket, ignoring errors."""
        try:
            self.sock.close()
        except OSError:
            pass


class Qmp:
    """QEMU Machine Protocol client: just enough for screendump and quit."""

    def __init__(self, path: Path) -> None:
        self.conn = LineSocket(path, 30)
        greeting = self.conn.recv(10)
        if not greeting or "QMP" not in greeting:
            raise RuntimeError("no QMP greeting")
        self.execute("qmp_capabilities")

    def execute(self, command: str, **arguments: object) -> dict:
        """
        Run one QMP command and wait for its reply (events are skipped).

        Raises:
            RuntimeError: if QEMU answers with an error object.
        """
        message: dict = {"execute": command}
        if arguments:
            message["arguments"] = arguments
        self.conn.send(message)
        while True:
            reply = self.conn.recv(30)
            if reply is None:
                raise TimeoutError(f"no reply to {command}")
            if "return" in reply:
                return reply["return"]
            if "error" in reply:
                raise RuntimeError(reply["error"].get("desc", "QMP error"))


class GuestAgent:
    """
    Client for the guest agent channel. Every call is best-effort: while the
    guest has not started the agent yet, calls simply report failure.
    """

    def __init__(self, path: Path) -> None:
        self.conn = LineSocket(path, 30)
        self.synced = False
        self.counter = int(time.time()) & 0xFFFFFF

    def _sync(self) -> bool:
        """Discard stale replies until the agent echoes a fresh sync id."""
        self.counter += 1
        self.conn.send({"execute": "guest-sync", "arguments": {"id": self.counter}})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            reply = self.conn.recv(1)
            if reply and reply.get("return") == self.counter:
                return True
        return False

    def call(self, command: str, **arguments: object) -> dict | None:
        """Run one agent command; None if the agent does not answer."""
        if not self._sync():
            return None
        message: dict = {"execute": command}
        if arguments:
            message["arguments"] = arguments
        self.conn.send(message)
        reply = self.conn.recv(10)
        if reply and "return" in reply:
            return reply["return"]
        return None

    def run(self, argv: list[str], timeout: float = 20.0) -> tuple[int, str] | None:
        """
        Execute a program in the guest and capture its output.

        Args:
            argv: Program path and arguments (no shell is involved).
            timeout: Seconds to wait for the program to finish.

        Returns:
            (exit code, decoded stdout) or None if the agent is not reachable
            or the program did not finish in time.
        """
        started = self.call("guest-exec", path=argv[0], arg=argv[1:], **{"capture-output": True})
        if not started:
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.call("guest-exec-status", pid=started["pid"])
            if status and status.get("exited"):
                out = base64.b64decode(status.get("out-data", "")).decode("utf-8", "replace")
                return status.get("exitcode", -1), out
            time.sleep(0.5)
        return None


class Sampler(threading.Thread):
    """
    Samples CPU time and resident memory of the QEMU process (and system-wide
    busy time) once per second, so the cost of the run can be reported.
    """

    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True)
        self.pid = pid
        self.stop_flag = threading.Event()
        self.samples: list[dict] = []
        self.ticks = os.sysconf("SC_CLK_TCK")

    def _read(self) -> dict | None:
        """One sample, or None if the process has gone."""
        try:
            stat = Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()
            # Fields after the command name: utime is index 11, stime index 12.
            proc_seconds = (int(stat[11]) + int(stat[12])) / self.ticks
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
        except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
            return None
        return {
            "t": time.monotonic(),
            "proc_cpu_s": proc_seconds,
            "rss_mb": rss_kb / 1024,
            "sys_busy": sum(cpu) - idle,
            "sys_total": sum(cpu),
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


def summarise_resources(samples: list[dict], t_start: float, t_end: float) -> dict:
    """
    Reduce raw samples to the numbers reported for a run.

    Args:
        samples: Output of Sampler.
        t_start: monotonic time of the first sample window (QEMU start).
        t_end: monotonic time of the end of the window (stable screenshot).

    Returns:
        Average and peak CPU use (in cores and as percent of the whole machine)
        and peak resident memory of the QEMU process, all within the window.
    """
    window = [s for s in samples if t_start <= s["t"] <= t_end]
    if len(window) < 2:
        return {}
    first, last = window[0], window[-1]
    wall = last["t"] - first["t"]
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


def build_qemu_command(args: argparse.Namespace, run_dir: Path) -> list[str]:
    """
    Assemble the QEMU command line as a list (never through a shell).

    Every option is here for a reason:
      -accel kvm -cpu host  hardware virtualisation; software emulation is far too slow
      virtio-vga            KMS/DRM device with a settable native resolution; there is
                            NO host GPU involved (no -display, no GL), the guest renders
                            in software and QEMU only receives the finished frame
      usb-tablet            absolute pointer so the cursor position is well defined
      -nic none             the guest has no network
      -snapshot             writes go to a throw-away overlay: the image never changes
      -rtc clock=vm         guest wall clock starts at a fixed date and is driven by
                            the VM clock
    """
    tag = args.tag
    return [
        args.qemu,
        "-name", f"kuura-spike-{tag}",
        "-machine", "q35", "-accel", "kvm", "-cpu", "host",
        "-smp", str(args.smp), "-m", str(args.mem),
        "-kernel", str(args.kernel), "-initrd", str(args.initrd),
        "-append", args.cmdline,
        "-snapshot",
        "-drive", f"file={args.image},if=virtio,format=raw",
        "-vga", "none",
        "-device", f"virtio-vga,xres={args.xres},yres={args.yres}",
        "-device", "usb-ehci", "-device", "usb-tablet",
        "-nic", "none",
        "-display", "none",
        "-rtc", f"base={args.rtc_base},clock=vm",
        "-serial", f"file:{run_dir / (tag + '-serial.log')}",
        "-qmp", f"unix:{run_dir / 'qmp.sock'},server=on,wait=off",
        "-chardev", f"socket,id=qga0,path={run_dir / 'qga.sock'},server=on,wait=off",
        "-device", "virtio-serial-pci",
        "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
        "-no-reboot",
    ]


def parse_args() -> argparse.Namespace:
    """Parse and validate the command line; exits with status 2 on bad input."""
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--build-dir", type=Path, required=True, help="directory with root.img, vmlinuz, initramfs.img")
    p.add_argument("--tag", required=True, help="run name; used in output file names")
    p.add_argument("--out-dir", type=Path, help="output directory (default: <build-dir>/runs)")
    p.add_argument("--qemu", default="qemu-system-x86_64")
    p.add_argument("--xres", type=int, default=2560)
    p.add_argument("--yres", type=int, default=1440)
    p.add_argument("--mem", type=int, default=4096, help="guest RAM in MiB")
    p.add_argument("--smp", type=int, default=4)
    p.add_argument("--rtc-base", default="2026-09-25T12:00:00", help="initial guest clock (UTC)")
    p.add_argument("--timeout", type=float, default=420, help="give up after this many seconds")
    p.add_argument("--interval", type=float, default=5, help="seconds between screenshots")
    p.add_argument("--identical", type=int, default=2, help="consecutive identical frames required")
    p.add_argument("--min-png-bytes", type=int, default=150_000, help="smaller PNGs count as blank")
    p.add_argument("--ready-process", default="plasmashell", help="guest process that must exist (empty: skip)")
    p.add_argument("--extra-cmdline", default="", help="extra kernel command line words")
    p.add_argument("--diag", action="store_true", help="also fetch the guest journal through the agent")
    p.add_argument("--guest-cmd", action="append", default=[], metavar="CMD",
                   help="command to run in the guest after the stable point (repeatable; split like a shell "
                        "would, but run without one)")
    p.add_argument("--after-delay", type=float, default=6, help="seconds to wait before the -after screenshot")
    args = p.parse_args()

    if not TAG_RE.match(args.tag):
        p.error("--tag must match [A-Za-z0-9_-]{1,32}")
    if not RTC_RE.match(args.rtc_base):
        p.error("--rtc-base must look like 2026-09-25T12:00:00")
    if not (640 <= args.xres <= 7680 and 480 <= args.yres <= 4320):
        p.error("resolution out of range")
    if not (512 <= args.mem <= 65536 and 1 <= args.smp <= 64):
        p.error("--mem / --smp out of range")
    if not (1 <= args.interval <= 60 and 30 <= args.timeout <= 3600 and 1 <= args.identical <= 10):
        p.error("--interval / --timeout / --identical out of range")
    if args.ready_process and not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", args.ready_process):
        p.error("--ready-process must be a plain process name (max 15 characters)")
    if not re.fullmatch(r"[A-Za-z0-9_=.,: /-]{0,200}", args.extra_cmdline):
        p.error("--extra-cmdline contains unsupported characters")

    args.build_dir = args.build_dir.resolve()
    for name in ("root.img", "vmlinuz", "initramfs.img"):
        if not (args.build_dir / name).is_file():
            p.error(f"{args.build_dir / name} is missing; run build_rootfs.sh first")
    args.image = args.build_dir / "root.img"
    args.kernel = args.build_dir / "vmlinuz"
    args.initrd = args.build_dir / "initramfs.img"
    args.out_dir = (args.out_dir or args.build_dir / "runs").resolve()
    if shutil.which(args.qemu) is None:
        p.error(f"{args.qemu} not found in PATH")
    # root=/dev/vda: the only disk. quiet is not used, the serial log is evidence.
    args.cmdline = ("root=/dev/vda rw console=ttyS0,115200 loglevel=4 "
                    "net.ifnames=0 systemd.show_status=1 " + args.extra_cmdline).strip()
    return args


def main() -> int:
    """Run one boot-and-capture cycle; see the module docstring."""
    args = parse_args()
    tag = args.tag
    run_dir = args.out_dir / tag
    # A previous run with the same tag is replaced completely.
    shutil.rmtree(run_dir, ignore_errors=True)
    (run_dir / "frames").mkdir(parents=True)

    # -snapshot puts its overlay file in $TMPDIR; keep it next to the other artefacts.
    env = dict(os.environ, TMPDIR=str(run_dir))
    cmd = build_qemu_command(args, run_dir)
    qemu_log = open(run_dir / f"{tag}-qemu.log", "wb")
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=qemu_log, stderr=subprocess.STDOUT, env=env,
                            start_new_session=True)
    sampler = Sampler(proc.pid)
    sampler.start()

    summary: dict = {"tag": tag, "cmdline": args.cmdline, "resolution": f"{args.xres}x{args.yres}",
                     "outcome": "unknown", "events": {}, "frames": []}
    events = summary["events"]
    qmp = qga = None
    poll_png = run_dir / f"{tag}-poll.png"
    prev_hash, identical_run, ready = None, 1, not args.ready_process
    distinct = 0

    try:
        qmp = Qmp(run_dir / "qmp.sock")
        qga = GuestAgent(run_dir / "qga.sock")
        events["qmp_connected_s"] = round(time.monotonic() - t0, 1)
        while True:
            loop_start = time.monotonic()
            elapsed = loop_start - t0
            if elapsed > args.timeout:
                summary["outcome"] = "timeout"
                break
            if proc.poll() is not None:
                summary["outcome"] = f"qemu-exited-{proc.returncode}"
                break

            # Guest side readiness: is the shell process there? (best effort)
            if not ready:
                res = qga.run(["/usr/bin/pgrep", "-x", args.ready_process], timeout=5)
                if res is not None and "agent_up_s" not in events:
                    events["agent_up_s"] = round(time.monotonic() - t0, 1)
                if res is not None and res[0] == 0:
                    ready = True
                    events["ready_process_seen_s"] = round(time.monotonic() - t0, 1)

            # Host side screenshot: QEMU renders the guest display into a PNG.
            size, digest = 0, None
            try:
                qmp.execute("screendump", filename=str(poll_png), format="png")
                data = poll_png.read_bytes()
                size, digest = len(data), hashlib.sha256(data).hexdigest()
            except (RuntimeError, OSError):
                pass  # no display surface yet
            now = round(time.monotonic() - t0, 1)
            if digest and size >= args.min_png_bytes and "first_nonblank_frame_s" not in events:
                events["first_nonblank_frame_s"] = now
            if digest and digest != prev_hash:
                distinct += 1
                identical_run = 1
                if distinct <= 60:
                    shutil.copyfile(poll_png, run_dir / "frames" / f"{distinct:03d}-t{int(now):04d}.png")
            elif digest:
                identical_run += 1
            summary["frames"].append({"t": now, "bytes": size, "sha256": (digest or "")[:12],
                                      "identical_run": identical_run, "ready": ready})
            prev_hash = digest

            if (digest and ready and size >= args.min_png_bytes
                    and identical_run >= args.identical):
                summary["outcome"] = "stable"
                events["stable_screenshot_s"] = now
                break
            time.sleep(max(0.0, args.interval - (time.monotonic() - loop_start)))

        t_end = time.monotonic()
        if poll_png.exists():
            final = run_dir / (f"{tag}.png" if summary["outcome"] == "stable" else f"{tag}-last.png")
            shutil.copyfile(poll_png, final)
            summary["final_png"] = final.name
        summary["resources"] = summarise_resources(sampler.samples, t0, t_end)

        # Optional commands in the guest (through the agent, no shell involved) after the
        # measurement window: used to inspect the session, or to try a setting and see
        # its effect in <tag>-after.png. Their output goes to <tag>-guest-exec.txt.
        if args.guest_cmd and qga is not None:
            report = []
            for text in args.guest_cmd:
                res = qga.run(shlex.split(text), timeout=60)
                report.append(f"$ {text}\n[exit {res[0] if res else 'no result'}]\n{res[1] if res else ''}\n")
            (run_dir / f"{tag}-guest-exec.txt").write_text("\n".join(report))
            time.sleep(args.after_delay)
            try:
                qmp.execute("screendump", filename=str(run_dir / f"{tag}-after.png"), format="png")
            except (RuntimeError, OSError):
                pass

        # Diagnostics after the measurement window so they do not disturb it.
        if args.diag and qga is not None:
            res = qga.run(["/usr/bin/journalctl", "-b", "--no-pager", "-o", "short-monotonic"], timeout=30)
            if res is not None:
                (run_dir / f"{tag}-journal.txt").write_text(res[1])
                summary["journal_file"] = f"{tag}-journal.txt"
    except (TimeoutError, ConnectionError, RuntimeError) as exc:
        summary["outcome"] = f"error: {exc}"
    finally:
        sampler.stop_flag.set()
        try:
            if qmp is not None:
                qmp.execute("quit")
        except (TimeoutError, ConnectionError, RuntimeError, OSError):
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        qemu_log.close()
        for c in (qmp, qga):
            if c is not None:
                c.conn.close()
        # Remove the (large, sparse) snapshot overlay if QEMU left one behind.
        for pattern in ("qemu_*", "vl.*"):
            for leftover in run_dir.glob(pattern):
                leftover.unlink(missing_ok=True)
        poll_png.unlink(missing_ok=True)
        (run_dir / f"{tag}-summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps({k: summary[k] for k in ("outcome", "events", "resources") if k in summary}, indent=2))
    return 0 if summary["outcome"] == "stable" else 1


if __name__ == "__main__":
    sys.exit(main())

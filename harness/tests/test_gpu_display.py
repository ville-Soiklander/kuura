"""
Tests for the optional gpu display mode: QEMU argument construction per mode, render-node
validation, the RFB client (against a fake in-process server on a unix socket) and the
screenshot routing. No VM is booted and no GPU is needed.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import struct
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.shots import capture, vm, vnc
from harness.shots.pngio import read_png
from harness.shots.vm import Vm, VmConfig, VmEnvironmentError
from harness.shots.vnc import VncError, VncScreen

needs_unix = pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="unix sockets required")


# --- QEMU arguments -------------------------------------------------------------------------------


def test_software_command_is_pinned(tmp_path: Path) -> None:
    """
    The default (software) command line is exactly the historic one, so CI behaviour
    cannot change by accident.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    img = tmp_path / "img"
    run = tmp_path / "run"
    config = VmConfig(image_dir=img, resolution=(2560, 1440), rtc_base="2026-09-25T12:00:00")
    assert vm.build_command(config, run) == [
        "qemu-system-x86_64", "-name", "harness-vm",
        "-machine", "q35", "-accel", "kvm", "-cpu", "host",
        "-smp", "4", "-m", "4096",
        "-kernel", str(img / "vmlinuz"), "-initrd", str(img / "initramfs.img"),
        "-append", vm.KERNEL_CMDLINE,
        "-snapshot",
        "-drive", f"file={img / 'root.img'},if=virtio,format=raw",
        "-vga", "none",
        "-device", "VGA,xres=2560,yres=1440",
        "-device", "usb-ehci", "-device", "usb-tablet",
        "-nic", "none",
        "-display", "none",
        "-rtc", "base=2026-09-25T12:00:00,clock=vm",
        "-serial", f"file:{run / 'serial.log'}",
        "-qmp", f"unix:{run / 'qmp.sock'},server=on,wait=off",
        "-chardev", f"socket,id=qga0,path={run / 'qga.sock'},server=on,wait=off",
        "-device", "virtio-serial-pci",
        "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
        "-no-reboot",
    ]


def test_gpu_command_swaps_device_display_and_adds_vnc(tmp_path: Path) -> None:
    """
    In gpu mode only the display device, the -display value and the -vnc socket differ.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    run = tmp_path / "run"
    soft = vm.build_command(VmConfig(image_dir=tmp_path), run)
    node = Path("/dev/dri/renderD129")
    gpu = vm.build_command(VmConfig(image_dir=tmp_path, display="gpu", render_node=node), run)
    expected = list(soft)
    expected[expected.index("VGA,xres=2560,yres=1440")] = "virtio-vga-gl,xres=2560,yres=1440"
    i = expected.index("-display")
    expected[i + 1 : i + 2] = [f"egl-headless,rendernode={node}", "-vnc", f"unix:{run / 'vnc.sock'}"]
    assert gpu == expected


def test_unknown_display_mode_is_rejected(tmp_path: Path) -> None:
    """
    A display mode outside software/gpu fails validation; both valid modes pass.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    with pytest.raises(ValueError, match="display"):
        VmConfig(image_dir=tmp_path, display="opengl").validate()  # type: ignore[arg-type]
    VmConfig(image_dir=tmp_path, display="gpu").validate()
    VmConfig(image_dir=tmp_path).validate()


def test_gpu_mode_requires_the_render_node(tmp_path: Path) -> None:
    """
    A missing render node is a clear environment error before QEMU starts; an existing
    one passes that check.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    for name in vm.IMAGE_FILES:
        (tmp_path / name).write_bytes(b"x")
    missing = Vm(VmConfig(image_dir=tmp_path, display="gpu", render_node=tmp_path / "nope",
                          require_kvm=False, qemu_binary=sys.executable))
    with pytest.raises(VmEnvironmentError, match="render node"):
        missing._preflight()
    node = tmp_path / "renderD128"
    node.write_bytes(b"")
    Vm(VmConfig(image_dir=tmp_path, display="gpu", render_node=node,
                require_kvm=False, qemu_binary=sys.executable))._preflight()


# --- RFB client against a fake server -------------------------------------------------------------


def _rect_header(x: int, y: int, w: int, h: int, encoding: int = 0) -> bytes:
    """
    Build a FramebufferUpdate header with one rectangle.

    Args:
        x: Rectangle x.
        y: Rectangle y.
        w: Rectangle width.
        h: Rectangle height.
        encoding: RFB encoding number.

    Returns:
        The wire bytes up to (not including) the pixel data.
    """
    return struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", x, y, w, h, encoding)


def _pixels(width: int, height: int, y0: int = 0) -> bytes:
    """
    Raw 32 bpp little-endian pixels (B, G, R, X) with a position-dependent colour.

    Args:
        width: Width in pixels.
        height: Rows to produce.
        y0: Absolute y of the first row.

    Returns:
        The pixel bytes.
    """
    out = bytearray()
    for y in range(y0, y0 + height):
        for x in range(width):
            out += bytes((77, y * 20 % 256, x * 10 % 256, 0))
    return bytes(out)


class FakeServer(threading.Thread):
    """Single-connection RFB server on a unix socket; behaviour chosen by ``mode``."""

    def __init__(self, path: Path, width: int, height: int, mode: str = "ok", version: bytes = b"RFB 003.008\n") -> None:
        """
        Args:
            path: Unix socket path.
            width: Reported frame width.
            height: Reported frame height.
            mode: ``ok``, ``silent`` (accept, never speak), ``refuse``, ``split`` (frame in
                two updates), ``bad-encoding`` or ``cut-before-frame``.
            version: Greeting bytes.
        """
        super().__init__(daemon=True)
        self.width, self.height, self.mode, self.version = width, height, mode, version
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        self.listener.listen(1)
        self.start()

    @staticmethod
    def _read(conn: socket.socket, n: int) -> bytes:
        """Read exactly n bytes from the client."""
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("client closed")
            buf += chunk
        return buf

    def run(self) -> None:
        """Serve one client, ignoring client disconnects."""
        try:
            conn, _ = self.listener.accept()
            with conn:
                self._serve(conn)
        except OSError:
            pass
        finally:
            self.listener.close()

    def _serve(self, conn: socket.socket) -> None:
        """Play the server side of the exchange."""
        if self.mode == "silent":
            threading.Event().wait(3)
            return
        conn.sendall(self.version)
        self._read(conn, 12)
        if self.mode == "refuse":
            conn.sendall(b"\x00")
            return
        conn.sendall(b"\x01\x01")
        self._read(conn, 1)
        conn.sendall(struct.pack(">I", 0))
        self._read(conn, 1)
        conn.sendall(struct.pack(">HH", self.width, self.height) + bytes(16) + struct.pack(">I", 4) + b"test")
        self._read(conn, 20 + 8 + 10)  # SetPixelFormat, SetEncodings (1 encoding), update request
        w, h = self.width, self.height
        if self.mode == "bad-encoding":
            conn.sendall(_rect_header(0, 0, 1, 1, 7))
        elif self.mode == "split":
            conn.sendall(_rect_header(0, 0, w, 1) + _pixels(w, 1))
            conn.sendall(_rect_header(0, 1, w, h - 1) + _pixels(w, h - 1, 1))
        else:
            if self.mode == "cut-before-frame":
                conn.sendall(b"\x02" + b"\x03\x00\x00\x00" + struct.pack(">I", 2) + b"hi")
            conn.sendall(_rect_header(0, 0, w, h) + _pixels(w, h))


@pytest.fixture
def sock_dir() -> Iterator[Path]:
    """
    A short temporary directory (unix socket paths are length-limited).

    Returns:
        Iterator yielding the directory.
    """
    path = Path(tempfile.mkdtemp(prefix="vnc-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@needs_unix
@pytest.mark.parametrize("mode", ["ok", "split", "cut-before-frame"])
def test_grab_decodes_a_raw_frame_into_a_png(sock_dir: Path, mode: str) -> None:
    """
    The client completes the handshake, decodes Raw pixels (B,G,R,X to RGB), also when the
    frame arrives in two updates or after bell/cut-text messages, and writes a PNG.

    Args:
        sock_dir: Short temp directory.
        mode: Server behaviour variant.

    Returns:
        None.
    """
    FakeServer(sock_dir / "v.sock", 5, 3, mode)
    out = sock_dir / "shot.png"
    assert vnc.grab(sock_dir / "v.sock", out, timeout=5) == (5, 3)
    width, height, rgb = read_png(out)
    assert (width, height) == (5, 3)
    assert rgb[:3] == bytes((0, 0, 77))
    i = (2 * 5 + 3) * 3  # pixel x=3, y=2
    assert rgb[i : i + 3] == bytes((30, 40, 77))


@needs_unix
def test_silent_server_times_out_quickly(sock_dir: Path) -> None:
    """
    A server that accepts but never speaks fails with VncError within the timeout.

    Args:
        sock_dir: Short temp directory.

    Returns:
        None.
    """
    FakeServer(sock_dir / "v.sock", 2, 2, "silent")
    with pytest.raises(VncError, match="timeout|deadline"):
        vnc.grab_rgb(sock_dir / "v.sock", timeout=0.3, deadline_s=1.0)


@needs_unix
@pytest.mark.parametrize(
    ("mode", "version", "message"),
    [
        ("ok", b"RFB 003.003\n", "version"),
        ("ok", b"HTTP/1.1 200 OK", "version"),
        ("refuse", b"RFB 003.008\n", "refused"),
        ("bad-encoding", b"RFB 003.008\n", "encoding"),
    ],
)
def test_bad_server_behaviour_is_a_vnc_error(sock_dir: Path, mode: str, version: bytes, message: str) -> None:
    """
    An unsupported greeting, a refused connection and a non-Raw rectangle all raise VncError.

    Args:
        sock_dir: Short temp directory.
        mode: Server behaviour variant.
        version: Greeting the fake server sends.
        message: Expected error text fragment.

    Returns:
        None.
    """
    FakeServer(sock_dir / "v.sock", 2, 2, mode, version)
    with pytest.raises(VncError, match=message):
        vnc.grab_rgb(sock_dir / "v.sock", timeout=2, deadline_s=5)


@needs_unix
def test_missing_socket_is_a_connection_error(tmp_path: Path) -> None:
    """
    Connecting to a socket that does not exist raises VncError (a ConnectionError).

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    with pytest.raises(ConnectionError):
        vnc.grab_rgb(tmp_path / "absent.sock", timeout=1)


# --- capture routing ------------------------------------------------------------------------------


class _FakeQmp:
    """Stands in for Qmp: records calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def screendump(self, path: Path) -> None:
        """Record a QMP screendump."""
        self.calls.append("qmp-screendump")

    def send_keys(self, chord: str) -> None:
        """Record a key press."""
        self.calls.append(f"keys:{chord}")


@needs_unix
def test_vnc_screen_routes_screendump_to_vnc_and_input_to_qmp(sock_dir: Path) -> None:
    """
    VncScreen takes screenshots over VNC but forwards input to QMP untouched.

    Args:
        sock_dir: Short temp directory.

    Returns:
        None.
    """
    FakeServer(sock_dir / "v.sock", 4, 2)
    qmp = _FakeQmp()
    screen = VncScreen(qmp, sock_dir / "v.sock", timeout=5)
    screen.screendump(sock_dir / "a.png")
    screen.send_keys("ctrl-c")
    assert (sock_dir / "a.png").stat().st_size > 0
    assert qmp.calls == ["keys:ctrl-c"]


def test_default_runner_uses_the_vm_screen_when_present(tmp_path: Path) -> None:
    """
    The runner gets ``vm.screen`` (VNC in gpu mode); a VM without that attribute falls
    back to its QMP client, which keeps software mode and existing fakes unchanged.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """

    class FakeAgent:
        cpu_sample = staticmethod(lambda: (0, 0))

    class WithScreen:
        qmp, screen, agent = object(), object(), FakeAgent()

    class WithoutScreen:
        qmp, agent = object(), FakeAgent()

    runner = capture._default_runner(WithScreen(), None, tmp_path, lambda line: None)  # type: ignore[arg-type]
    assert runner._screen is WithScreen.screen
    runner = capture._default_runner(WithoutScreen(), None, tmp_path, lambda line: None)  # type: ignore[arg-type]
    assert runner._screen is WithoutScreen.qmp


def test_display_option_defaults_to_software_and_reaches_the_options(tmp_path: Path) -> None:
    """
    ``--display`` defaults to software; ``gpu`` is carried into the capture options and
    an unknown value is rejected by the parser.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    out = capture.PROJECT_ROOT / ".build" / "unit-test-out"  # the path guard wants the project tree
    parser = argparse.ArgumentParser()
    capture.add_selection_arguments(parser)
    assert capture.build_options(parser.parse_args([]), out).display == "software"
    assert capture.build_options(parser.parse_args(["--display", "gpu"]), out).display == "gpu"
    with pytest.raises(SystemExit):
        parser.parse_args(["--display", "vulkan"])

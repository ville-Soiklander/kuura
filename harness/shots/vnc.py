"""
Minimal RFB (VNC) client used to take screenshots in the harness's gpu display mode.

WHY: while the guest scans out a GL texture (virtio-gpu with virgl), QMP ``screendump``
fails with "no surface". QEMU's ``egl-headless`` display reads every GL frame back for
its VNC server, so the harness asks VNC for one full frame instead.

Scope is deliberately tiny: unix socket only, RFB 3.7/3.8, security type None, the Raw
encoding, one non-incremental full-framebuffer request per connection. That is all
QEMU's ``-vnc unix:...`` without a password speaks. Every socket operation is bounded
by a per-call timeout AND an overall deadline, so a hung QEMU fails the capture with a
clear error instead of blocking forever.

Standard library only.
"""

from __future__ import annotations

import re
import socket
import struct
import time
from pathlib import Path
from typing import Any

from harness.shots.pngio import write_png

# Server greeting: "RFB xxx.yyy\n". Only 3.7 and 3.8 share the security handshake we use.
_VERSION_PATTERN = re.compile(rb"^RFB (\d{3})\.(\d{3})\n$")
_SUPPORTED_MINORS = (7, 8)

# Upper bound for a framebuffer, in pixels (8K). A corrupt header must not make us
# allocate gigabytes.
_MAX_PIXELS = 7680 * 4320

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_DEADLINE_S = 60.0


class VncError(ConnectionError):
    """
    The VNC exchange failed (refused, malformed, timed out).

    Subclasses ``ConnectionError`` so the runner treats it like a lost VM connection.
    """


class _Reader:
    """Reads exact byte counts from a socket within a per-call timeout and an overall deadline."""

    def __init__(self, sock: socket.socket, timeout: float, deadline: float) -> None:
        """
        Args:
            sock: Connected socket.
            timeout: Per-``recv`` timeout in seconds.
            deadline: Absolute ``time.monotonic()`` value after which reading fails.
        """
        self._sock = sock
        self._timeout = timeout
        self._deadline = deadline

    def read(self, count: int) -> bytes:
        """
        Read exactly ``count`` bytes.

        Args:
            count: Number of bytes.

        Returns:
            The bytes.

        Raises:
            VncError: timeout, deadline exceeded or the peer closed the socket.
        """
        buf = bytearray()
        while len(buf) < count:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise VncError("VNC frame grab exceeded its overall deadline")
            self._sock.settimeout(min(self._timeout, remaining))
            try:
                chunk = self._sock.recv(min(count - len(buf), 1 << 20))
            except TimeoutError:
                raise VncError("VNC server stopped answering (timeout)") from None
            except OSError as exc:
                raise VncError(f"VNC socket error: {exc.__class__.__name__}") from None
            if not chunk:
                raise VncError("VNC socket closed by the server")
            buf += chunk
        return bytes(buf)


def _send(sock: socket.socket, data: bytes, timeout: float) -> None:
    """
    Send all bytes with a timeout.

    Args:
        sock: Connected socket.
        data: Bytes to send.
        timeout: Timeout in seconds.

    Raises:
        VncError: timeout or socket failure.
    """
    sock.settimeout(timeout)
    try:
        sock.sendall(data)
    except TimeoutError:
        raise VncError("VNC server stopped answering (send timeout)") from None
    except OSError as exc:
        raise VncError(f"VNC socket error: {exc.__class__.__name__}") from None


def _handshake(sock: socket.socket, reader: _Reader, timeout: float) -> tuple[int, int]:
    """
    Run version, security (None) and init messages.

    Args:
        sock: Connected socket.
        reader: Reader bound to the same socket.
        timeout: Send timeout in seconds.

    Returns:
        Framebuffer ``(width, height)``.

    Raises:
        VncError: unsupported server version, refusal, no None security, or bad size.
    """
    match = _VERSION_PATTERN.match(reader.read(12))
    if match is None or int(match.group(2)) not in _SUPPORTED_MINORS or int(match.group(1)) != 3:
        raise VncError("unsupported VNC server version")
    _send(sock, b"RFB 003.008\n", timeout)
    count = reader.read(1)[0]
    if count == 0:
        raise VncError("VNC server refused the connection")
    if 1 not in reader.read(count):
        raise VncError("VNC server does not offer security type None")
    _send(sock, b"\x01", timeout)
    if struct.unpack(">I", reader.read(4))[0] != 0:
        raise VncError("VNC security handshake failed")
    _send(sock, b"\x01", timeout)  # ClientInit: shared
    width, height = struct.unpack(">HH", reader.read(4))
    reader.read(16)  # server pixel format; we override it below
    reader.read(struct.unpack(">I", reader.read(4))[0] & 0xFFFF)  # desktop name, capped
    if not (0 < width * height <= _MAX_PIXELS):
        raise VncError("VNC server reported an invalid framebuffer size")
    return width, height


def grab_rgb(sock_path: Path, timeout: float = DEFAULT_TIMEOUT_S, deadline_s: float = DEFAULT_DEADLINE_S) -> tuple[int, int, bytes]:
    """
    Connect, request one non-incremental full update and return it as packed RGB.

    Args:
        sock_path: QEMU's ``-vnc unix:`` socket.
        timeout: Per-operation socket timeout in seconds.
        deadline_s: Overall time limit for the whole grab in seconds.

    Returns:
        ``(width, height, rgb)`` with ``rgb`` being ``width * height * 3`` bytes.

    Raises:
        VncError: the server is missing, hangs, or speaks something unsupported.
    """
    deadline = time.monotonic() + deadline_s
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        try:
            sock.connect(str(sock_path))
        except OSError as exc:
            raise VncError(f"cannot connect to the VNC socket: {exc.__class__.__name__}") from None
        reader = _Reader(sock, timeout, deadline)
        width, height = _handshake(sock, reader, timeout)
        # 32 bpp, depth 24, little endian, true colour, 8 bits per channel, R<<16 G<<8 B.
        pixel_format = struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        _send(sock, b"\x00\x00\x00\x00" + pixel_format, timeout)  # SetPixelFormat
        _send(sock, struct.pack(">BxHi", 2, 1, 0), timeout)  # SetEncodings: Raw only
        _send(sock, struct.pack(">BBHHHH", 3, 0, 0, 0, width, height), timeout)  # full, non-incremental
        return width, height, _read_frame(reader, width, height)
    finally:
        sock.close()


def _read_frame(reader: _Reader, width: int, height: int) -> bytes:
    """
    Read FramebufferUpdate messages until the whole frame is covered.

    Args:
        reader: Reader bound to the connected socket.
        width: Framebuffer width.
        height: Framebuffer height.

    Returns:
        Packed RGB bytes.

    Raises:
        VncError: unexpected message or encoding, or a rectangle outside the frame.
    """
    frame = bytearray(width * height * 3)
    covered = 0
    while covered < width * height:
        msg = reader.read(1)[0]
        if msg == 2:  # Bell
            continue
        if msg == 3:  # ServerCutText
            reader.read(3)
            reader.read(struct.unpack(">I", reader.read(4))[0] & 0xFFFFFF)
            continue
        if msg != 0:
            raise VncError(f"unexpected VNC message type {msg}")
        reader.read(1)  # padding
        rect_count = struct.unpack(">H", reader.read(2))[0]
        for _ in range(rect_count):
            x, y, rw, rh, encoding = struct.unpack(">HHHHi", reader.read(12))
            if encoding != 0:
                raise VncError(f"unexpected VNC encoding {encoding}")
            if x + rw > width or y + rh > height:
                raise VncError("VNC rectangle lies outside the framebuffer")
            data = reader.read(rw * rh * 4)
            for row in range(rh):
                src = data[row * rw * 4 : (row + 1) * rw * 4]
                dst = ((y + row) * width + x) * 3
                # WHY the slicing: little-endian 32 bpp pixels arrive as B, G, R, X.
                line = bytearray(rw * 3)
                line[0::3] = src[2::4]
                line[1::3] = src[1::4]
                line[2::3] = src[0::4]
                frame[dst : dst + rw * 3] = line
            covered += rw * rh
    return bytes(frame)


def grab(sock_path: Path, out: Path, timeout: float = DEFAULT_TIMEOUT_S, deadline_s: float = DEFAULT_DEADLINE_S) -> tuple[int, int]:
    """
    Grab one frame and write it as a PNG in the harness's own format.

    Args:
        sock_path: QEMU's ``-vnc unix:`` socket.
        out: Destination PNG (replaced if present).
        timeout: Per-operation socket timeout in seconds.
        deadline_s: Overall time limit in seconds.

    Returns:
        ``(width, height)`` of the frame.

    Raises:
        VncError: see ``grab_rgb``.
    """
    width, height, rgb = grab_rgb(sock_path, timeout, deadline_s)
    write_png(out, width, height, rgb)
    return width, height


class VncScreen:
    """
    Drop-in for the ``Qmp`` object the runner uses, taking screenshots over VNC.

    Everything except ``screendump`` (keys, pointer, text) is forwarded to the wrapped
    QMP client, so input is unchanged and only the capture seam differs by display mode.

    Args:
        qmp: The connected QMP client.
        sock_path: QEMU's ``-vnc unix:`` socket.
        timeout: Per-operation socket timeout in seconds.
        deadline_s: Overall time limit per screenshot in seconds.
    """

    def __init__(self, qmp: Any, sock_path: Path, timeout: float = DEFAULT_TIMEOUT_S, deadline_s: float = DEFAULT_DEADLINE_S) -> None:
        self._qmp = qmp
        self._sock_path = sock_path
        self._timeout = timeout
        self._deadline_s = deadline_s

    def screendump(self, path: Path) -> None:
        """
        Write the current guest display to a PNG file via VNC.

        Args:
            path: Destination file.

        Raises:
            VncError: the grab failed or timed out.
        """
        grab(self._sock_path, path, self._timeout, self._deadline_s)

    def __getattr__(self, name: str) -> Any:
        """
        Forward every other attribute (input helpers) to the QMP client.

        Args:
            name: Attribute name.

        Returns:
            The QMP client's attribute.
        """
        return getattr(self._qmp, name)

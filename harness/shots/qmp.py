"""
QEMU Machine Protocol (QMP) client for the screenshot harness.

QMP is newline-delimited JSON over a UNIX socket. This module contains the small
transport class shared with the guest-agent client (``JsonLineChannel``) and the
client itself (``Qmp``): screenshots (``screendump``), keyboard input and absolute
pointer input, all sent from the HOST through ``input-send-event`` so that nothing in
the guest produces the picture or the input.

Every wait has a timeout and every failure has a specific exception:

* ``TimeoutError``     no answer within the allowed time
* ``ConnectionError``  the peer closed the socket or sent something that is not JSON
* ``QmpError``         QEMU answered with an error object (the message carries its text)
* ``ValueError``       the caller passed something impossible (a coordinate off the
                       screen, an unknown key)

Messages never contain absolute host paths: sockets and files are named by file name.
Standard library only.
"""

from __future__ import annotations

import itertools
import json
import select
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness.shots import keys

# The usb-tablet reports absolute coordinates on an axis of 0..32767 (0x7FFF) regardless
# of the screen size; QEMU scales that range to the display.
ABS_AXIS_MAX = 32767

# The kernel refuses UNIX socket paths of 108 bytes or more (including the NUL byte).
_MAX_SOCKET_PATH = 107


class QmpError(RuntimeError):
    """QEMU replied to a command with an error object (the text is QEMU's description)."""


class JsonLineChannel:
    """
    Newline-delimited JSON over a connected stream socket.

    Used for QMP and for the guest agent. It keeps a receive buffer so that a partial
    line survives a timeout and is completed by the next ``recv``.

    Args:
        sock: A connected stream socket (a UNIX socket in production, a socket pair
            in tests). The channel owns it and closes it in ``close``.
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buffer = b""

    @classmethod
    def connect(
        cls,
        path: Path,
        timeout: float,
        alive: Callable[[], bool] | None = None,
    ) -> JsonLineChannel:
        """
        Connect to a UNIX socket that the peer creates a moment after it starts.

        Args:
            path: Filesystem path of the socket.
            timeout: Seconds to keep retrying while the socket does not exist yet.
            alive: Optional check that the peer process is still running; when it
                returns False the wait is abandoned at once instead of running out
                the timeout.

        Returns:
            The connected channel.

        Raises:
            ValueError: if the path is too long for a UNIX socket.
            TimeoutError: if no connection could be made in time.
            ConnectionError: if ``alive`` reports that the peer has died.
        """
        text = str(path)
        if len(text.encode()) > _MAX_SOCKET_PATH:
            raise ValueError(f"socket path for {path.name!r} is too long for a UNIX socket")
        deadline = time.monotonic() + timeout
        while True:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(text)
                return cls(sock)
            except (FileNotFoundError, ConnectionRefusedError):
                # The peer creates the socket shortly after it starts; retry until it does.
                sock.close()
                if alive is not None and not alive():
                    raise ConnectionError(f"peer exited before socket {path.name!r} came up") from None
                if time.monotonic() > deadline:
                    raise TimeoutError(f"socket {path.name!r} did not come up in {timeout:g} s") from None
                time.sleep(0.1)
            except OSError:
                sock.close()
                raise

    def send(self, message: dict[str, Any]) -> None:
        """
        Send one JSON object followed by a newline.

        Args:
            message: JSON-serialisable dictionary.

        Raises:
            ConnectionError: if the peer has closed the socket.
        """
        try:
            self._sock.sendall(json.dumps(message).encode() + b"\n")
        except OSError as exc:
            raise ConnectionError("connection to the peer was lost while sending") from exc

    def recv(self, timeout: float) -> dict[str, Any] | None:
        """
        Read one JSON line.

        Args:
            timeout: Seconds to wait for a complete line.

        Returns:
            The decoded object, or None if no complete line arrived in time (the
            channel stays usable and keeps any partial line).

        Raises:
            ConnectionError: if the peer closed the socket or sent malformed JSON.
        """
        deadline = time.monotonic() + timeout
        while True:
            while b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                # WHY strip 0xFF: a guest agent in "delimited" mode prefixes replies with
                # it; it is harmless here and blank lines are simply skipped.
                line = line.strip(b"\xff").strip()
                if not line:
                    continue
                try:
                    decoded = json.loads(line)
                except ValueError as exc:
                    raise ConnectionError("peer sent a line that is not valid JSON") from exc
                if not isinstance(decoded, dict):
                    raise ConnectionError("peer sent JSON that is not an object")
                return decoded
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                ready, _, _ = select.select([self._sock], [], [], remaining)
                if not ready:
                    return None
                chunk = self._sock.recv(65536)
            except OSError as exc:
                raise ConnectionError("connection to the peer was lost while receiving") from exc
            if not chunk:
                raise ConnectionError("peer closed the connection")
            self._buffer += chunk

    def close(self) -> None:
        """Close the socket; closing twice or a broken socket is not an error."""
        try:
            self._sock.close()
        except OSError:
            pass


def abs_value(coordinate: int, size: int) -> int:
    """
    Map a physical pixel coordinate to the 0..32767 axis of the usb-tablet.

    The first pixel (0) maps to 0 and the last pixel (``size - 1``) maps to 32767, with
    linear rounding in between. One pixel is about 12 axis units at 2560 wide, so the
    rounding error is far below a pixel.

    Args:
        coordinate: Pixel index, 0 <= coordinate < size.
        size: Number of physical pixels along the axis (at least 2).

    Returns:
        The axis value, 0..32767.

    Raises:
        ValueError: if ``size`` is below 2, or the coordinate is not an integer or lies
            outside the screen.
    """
    if isinstance(coordinate, bool) or not isinstance(coordinate, int):
        raise ValueError(f"pointer coordinate must be an integer, got {coordinate!r}")
    if size < 2:
        raise ValueError("screen size must be at least 2 pixels")
    if not 0 <= coordinate < size:
        raise ValueError(f"pointer coordinate {coordinate} is outside the screen (0..{size - 1})")
    return round(coordinate * ABS_AXIS_MAX / (size - 1))


class Qmp:
    """
    QMP client with screendump and input helpers.

    Args:
        channel: A connected channel to QEMU's QMP socket. The constructor reads the
            greeting and negotiates capabilities.
        resolution: Screen size in physical pixels (width, height); used to map
            pointer coordinates to the tablet axis.
        reply_timeout: Default seconds to wait for a command's reply.
        hold_s: Seconds a key or mouse button stays down.
        sleep: Sleep function (replaced in tests so they run instantly).
        greeting_timeout: Seconds to wait for QEMU's greeting.

    Raises:
        TimeoutError: if QEMU does not send its greeting.
        ConnectionError: if the greeting is not a QMP greeting.
    """

    def __init__(
        self,
        channel: JsonLineChannel,
        resolution: tuple[int, int],
        reply_timeout: float = 30.0,
        hold_s: float = 0.05,
        sleep: Callable[[float], None] = time.sleep,
        greeting_timeout: float = 10.0,
    ) -> None:
        self._channel = channel
        self.resolution = resolution
        self._reply_timeout = reply_timeout
        self._hold_s = hold_s
        self._sleep = sleep
        self._ids = itertools.count(1)
        greeting = channel.recv(greeting_timeout)
        if greeting is None:
            raise TimeoutError("QEMU did not send a QMP greeting")
        if "QMP" not in greeting:
            raise ConnectionError("peer did not send a QMP greeting")
        self.execute("qmp_capabilities")

    @classmethod
    def connect(
        cls,
        path: Path,
        resolution: tuple[int, int],
        timeout: float = 30.0,
        alive: Callable[[], bool] | None = None,
    ) -> Qmp:
        """
        Connect to a QMP socket and negotiate.

        Args:
            path: QMP socket path.
            resolution: Screen size in physical pixels.
            timeout: Seconds to wait for the socket to appear.
            alive: Optional "QEMU is still running" check (see ``JsonLineChannel.connect``).

        Returns:
            A ready client.

        Raises:
            TimeoutError, ConnectionError, ValueError: see ``JsonLineChannel.connect``
                and the constructor.
        """
        channel = JsonLineChannel.connect(path, timeout, alive)
        try:
            return cls(channel, resolution)
        except BaseException:
            channel.close()
            raise

    def execute(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """
        Run one QMP command and wait for its reply.

        Events (asynchronous notifications) and replies to other commands are skipped.

        Args:
            command: QMP command name, for example ``"screendump"``.
            arguments: Command arguments, or None.
            timeout: Seconds to wait; the client default when None.

        Returns:
            The ``return`` member of the reply.

        Raises:
            QmpError: QEMU answered with an error.
            TimeoutError: no reply in time.
            ConnectionError: the connection broke.
        """
        request_id = next(self._ids)
        message: dict[str, Any] = {"execute": command, "id": request_id}
        if arguments:
            message["arguments"] = arguments
        self._channel.send(message)

        wait = self._reply_timeout if timeout is None else timeout
        deadline = time.monotonic() + wait
        while True:
            reply = self._channel.recv(max(0.0, deadline - time.monotonic()))
            if reply is None:
                raise TimeoutError(f"no reply to QMP command {command!r} within {wait:g} s")
            if reply.get("id") != request_id:
                continue  # an event or a reply that belongs to an earlier, abandoned request
            if "error" in reply:
                error = reply["error"] if isinstance(reply["error"], dict) else {}
                raise QmpError(f"QMP command {command!r} failed: {error.get('desc', 'unknown error')}")
            return reply.get("return")

    def screendump(self, path: Path) -> None:
        """
        Write the current guest display to a PNG file (host-side screenshot).

        Args:
            path: Destination file; its directory must exist. An existing file is
                replaced.

        Raises:
            QmpError: QEMU could not produce the image (for example no display yet)
                or wrote no file.
            TimeoutError, ConnectionError: see ``execute``.
        """
        self.execute("screendump", {"filename": str(path), "format": "png"})
        # WHY check: an empty or missing file would otherwise surface much later as a
        # confusing image-decoder error.
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size == 0:
            raise QmpError(f"screendump wrote no image to {path.name!r}")

    def _send_events(self, events: list[dict[str, Any]]) -> None:
        """
        Send a list of input events with ``input-send-event``.

        No ``device`` argument is given: in QMP it names a DISPLAY device (for multi-head
        setups), not an input device - naming the tablet there makes QEMU abort. QEMU
        routes absolute-axis events to the only handler that accepts them, the tablet.

        Args:
            events: QMP InputEvent objects.
        """
        self.execute("input-send-event", {"events": events})

    @staticmethod
    def key_event(qcode: str, down: bool) -> dict[str, Any]:
        """
        Build the InputEvent for one key press or release.

        Args:
            qcode: QEMU key code, for example ``"meta_l"``.
            down: True for press, False for release.

        Returns:
            The event dictionary.
        """
        return {"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": qcode}}}

    def _press(self, qcodes: tuple[str, ...]) -> None:
        """
        Press all keys in order, hold, then release them in reverse order.

        Args:
            qcodes: Keys in press order (modifiers first).
        """
        self._send_events([self.key_event(code, True) for code in qcodes])
        self._sleep(self._hold_s)
        self._send_events([self.key_event(code, False) for code in reversed(qcodes)])

    def send_keys(self, chord: str) -> None:
        """
        Press and release a key chord such as ``"meta+w"``.

        Args:
            chord: See ``harness.shots.keys.parse_chord``.

        Raises:
            ValueError: the chord is invalid.
            QmpError, TimeoutError, ConnectionError: see ``execute``.
        """
        self._press(keys.parse_chord(chord))

    def type_text(self, text: str, delay_s: float = 0.06) -> None:
        """
        Type text as key events, one press per character.

        Args:
            text: Letters, digits and spaces (see ``harness.shots.keys.text_to_chords``).
            delay_s: Pause after every character so the guest keeps up.

        Raises:
            ValueError: the text contains something that cannot be typed.
            QmpError, TimeoutError, ConnectionError: see ``execute``.
        """
        # Validate the whole text first so a bad character cannot leave half of it typed.
        chords = keys.text_to_chords(text)
        for chord in chords:
            self._press(chord)
            self._sleep(delay_s)

    def pointer_move(self, x: int, y: int) -> None:
        """
        Move the pointer to an absolute position.

        Args:
            x: Physical pixel column, 0 <= x < width.
            y: Physical pixel row, 0 <= y < height.

        Raises:
            ValueError: the position is outside the screen.
            QmpError, TimeoutError, ConnectionError: see ``execute``.
        """
        width, height = self.resolution
        events = [
            {"type": "abs", "data": {"axis": "x", "value": abs_value(x, width)}},
            {"type": "abs", "data": {"axis": "y", "value": abs_value(y, height)}},
        ]
        self._send_events(events)

    def pointer_click(self, x: int, y: int) -> None:
        """
        Move to a position and click the left button.

        Args:
            x: Physical pixel column.
            y: Physical pixel row.

        Raises:
            ValueError: the position is outside the screen.
            QmpError, TimeoutError, ConnectionError: see ``execute``.
        """
        self.pointer_move(x, y)
        # WHY pause: the compositor must see the pointer at the target (and update the
        # hover state) before the button goes down, or the click can land on the old spot.
        self._sleep(self._hold_s * 2)
        self._send_events([{"type": "btn", "data": {"down": True, "button": "left"}}])
        self._sleep(self._hold_s)
        self._send_events([{"type": "btn", "data": {"down": False, "button": "left"}}])

    def quit(self) -> None:
        """
        Ask QEMU to exit.

        Raises:
            TimeoutError, ConnectionError, QmpError: see ``execute``. A caller that is
                shutting down normally ignores them.
        """
        self.execute("quit", timeout=5.0)

    def close(self) -> None:
        """Close the connection (QEMU keeps running)."""
        self._channel.close()

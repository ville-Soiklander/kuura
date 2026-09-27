"""
Tests for harness.shots.qmp and harness.shots.guest against fake servers.

No VM is involved: a tiny server thread on one end of ``socket.socketpair()`` plays QEMU
(or the guest agent) and records every message it receives.
"""

from __future__ import annotations

import base64
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from harness.shots.guest import ExecResult, GuestAgent, GuestAgentError, GuestUser
from harness.shots.qmp import ABS_AXIS_MAX, JsonLineChannel, Qmp, QmpError, abs_value

Handler = Callable[[dict[str, Any]], "list[dict[str, Any]] | None"]

GREETING = {"QMP": {"version": {}, "capabilities": []}}


class FakeServer(threading.Thread):
    """
    A line-oriented JSON server on one end of a socket pair.

    Args:
        sock: The server's end of the pair.
        handler: Called with every received message; returns the replies to send
            (an empty list or None sends nothing).
        greeting: A message sent first, or None.

    Attributes:
        received: Every message received, in order.
    """

    def __init__(self, sock: socket.socket, handler: Handler, greeting: dict[str, Any] | None = None) -> None:
        super().__init__(daemon=True)
        self.sock = sock
        self.handler = handler
        self.greeting = greeting
        self.received: list[dict[str, Any]] = []
        self._buffer = b""

    def send(self, message: dict[str, Any]) -> None:
        """
        Send one JSON line.

        Args:
            message: The object to send.
        """
        self.sock.sendall(json.dumps(message).encode() + b"\n")

    def run(self) -> None:
        """Thread body: greet, then answer every received line until the peer closes."""
        try:
            if self.greeting is not None:
                self.send(self.greeting)
            while True:
                data = self.sock.recv(65536)
                if not data:
                    return
                self._buffer += data
                while b"\n" in self._buffer:
                    line, self._buffer = self._buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    message = json.loads(line)
                    self.received.append(message)
                    for reply in self.handler(message) or []:
                        self.send(reply)
        except OSError:
            return


def ok_handler(message: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Answer every QMP command with an empty success reply.

    Args:
        message: The received command.

    Returns:
        The reply carrying the command's id.
    """
    return [{"return": {}, "id": message.get("id")}]


@pytest.fixture
def make_qmp() -> Iterator[Callable[..., tuple[Qmp, FakeServer]]]:
    """
    Provide a factory for a ``Qmp`` connected to a fake QEMU.

    Yields:
        A function ``(handler=ok_handler, greeting=GREETING, **qmp_kwargs)`` returning
        the client and the server; everything is closed after the test.
    """
    opened: list[Any] = []

    def factory(handler: Handler = ok_handler, greeting: dict[str, Any] | None = GREETING, **kwargs: Any) -> tuple[Qmp, FakeServer]:
        client_sock, server_sock = socket.socketpair()
        server = FakeServer(server_sock, handler, greeting)
        server.start()
        opened.extend([client_sock, server_sock])
        kwargs.setdefault("resolution", (2560, 1440))
        kwargs.setdefault("sleep", lambda seconds: None)
        qmp = Qmp(JsonLineChannel(client_sock), **kwargs)
        return qmp, server

    yield factory
    for sock in opened:
        try:
            sock.close()
        except OSError:
            pass


def input_events(server: FakeServer) -> list[list[dict[str, Any]]]:
    """
    Collect the event lists of every ``input-send-event`` the server received.

    Args:
        server: The fake server.

    Returns:
        One list of events per command.
    """
    return [m["arguments"]["events"] for m in server.received if m["execute"] == "input-send-event"]


# --- absolute pointer mapping -------------------------------------------------------


def test_abs_value_corners_map_to_zero_and_max() -> None:
    """
    The first pixel maps to 0 and the last pixel to 32767 on both axes.

    Returns:
        None.
    """
    assert abs_value(0, 2560) == 0
    assert abs_value(2559, 2560) == ABS_AXIS_MAX == 32767
    assert abs_value(0, 1440) == 0
    assert abs_value(1439, 1440) == 32767


def test_abs_value_is_monotonic_and_stays_in_range() -> None:
    """
    Every pixel maps into 0..32767 and a larger pixel never maps to a smaller value; the
    middle lands within one axis unit of the exact middle.

    Returns:
        None.
    """
    values = [abs_value(x, 2560) for x in range(2560)]
    assert values == sorted(values)
    assert min(values) == 0 and max(values) == 32767
    assert abs(abs_value(1280, 2560) - 32767 * 1280 / 2559) <= 1


@pytest.mark.parametrize("coordinate, size", [(-1, 2560), (2560, 2560), (5, 5), (10**6, 100)])
def test_abs_value_rejects_coordinates_off_the_screen(coordinate: int, size: int) -> None:
    """
    A pixel outside ``0 <= c < size`` is a ValueError.

    Args:
        coordinate: The bad pixel.
        size: The axis length.

    Returns:
        None.
    """
    with pytest.raises(ValueError, match="outside the screen"):
        abs_value(coordinate, size)


@pytest.mark.parametrize("coordinate", [1.5, "3", None, True])
def test_abs_value_rejects_non_integers(coordinate: Any) -> None:
    """
    Floats, strings, None and booleans are not pixel coordinates.

    Args:
        coordinate: The bad value.

    Returns:
        None.
    """
    with pytest.raises(ValueError, match="integer"):
        abs_value(coordinate, 100)


def test_abs_value_rejects_degenerate_axis() -> None:
    """
    An axis of fewer than two pixels cannot be mapped (division by zero otherwise).

    Returns:
        None.
    """
    with pytest.raises(ValueError, match="at least 2"):
        abs_value(0, 1)


# --- JSON line channel ----------------------------------------------------------------


def test_channel_keeps_partial_lines_across_timeouts() -> None:
    """
    A line that arrives in two pieces is returned once complete; the timeout in between
    returns None without losing the first piece.

    Returns:
        None.
    """
    a, b = socket.socketpair()
    channel = JsonLineChannel(a)
    try:
        b.sendall(b'{"a":')
        assert channel.recv(0.1) is None
        b.sendall(b"1}\n")
        assert channel.recv(1) == {"a": 1}
    finally:
        a.close()
        b.close()


def test_channel_splits_several_messages_and_skips_markers() -> None:
    """
    Two messages in one chunk come out one at a time; blank lines and the 0xFF marker of
    a delimited agent are ignored.

    Returns:
        None.
    """
    a, b = socket.socketpair()
    channel = JsonLineChannel(a)
    try:
        b.sendall(b'\xff{"x": 1}\n\n{"y": 2}\n')
        assert channel.recv(1) == {"x": 1}
        assert channel.recv(1) == {"y": 2}
        assert channel.recv(0.05) is None
    finally:
        a.close()
        b.close()


@pytest.mark.parametrize("payload", [b"not json\n", b"[1, 2]\n", b'"text"\n'])
def test_channel_rejects_malformed_messages(payload: bytes) -> None:
    """
    Text that is not a JSON object is a ConnectionError, not a crash.

    Args:
        payload: What the peer sends.

    Returns:
        None.
    """
    a, b = socket.socketpair()
    channel = JsonLineChannel(a)
    try:
        b.sendall(payload)
        with pytest.raises(ConnectionError):
            channel.recv(1)
    finally:
        a.close()
        b.close()


def test_channel_reports_a_closed_peer() -> None:
    """
    A peer that closes the connection is a ConnectionError on receive; sending to a
    closed peer eventually fails the same way.

    Returns:
        None.
    """
    a, b = socket.socketpair()
    channel = JsonLineChannel(a)
    b.close()
    try:
        with pytest.raises(ConnectionError, match="closed"):
            channel.recv(1)
    finally:
        channel.close()
        channel.close()  # closing twice is harmless


def test_channel_connect_rejects_overlong_socket_paths(tmp_path: Path) -> None:
    """
    A UNIX socket path the kernel would refuse is reported before any connection attempt,
    naming only the file.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    long_path = tmp_path / ("x" * 120) / "qmp.sock"
    with pytest.raises(ValueError, match="too long") as caught:
        JsonLineChannel.connect(long_path, 0.1)
    assert str(tmp_path) not in str(caught.value)


# --- QMP client -----------------------------------------------------------------------


def test_handshake_negotiates_capabilities(make_qmp: Any) -> None:
    """
    The constructor reads the greeting and sends ``qmp_capabilities`` first.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    _qmp, server = make_qmp()
    assert [m["execute"] for m in server.received] == ["qmp_capabilities"]


def test_missing_or_wrong_greeting_is_an_error(make_qmp: Any) -> None:
    """
    No greeting is a TimeoutError; something other than a QMP greeting is a ConnectionError.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    with pytest.raises(TimeoutError, match="greeting"):
        make_qmp(greeting=None, greeting_timeout=0.2)
    with pytest.raises(ConnectionError, match="greeting"):
        make_qmp(greeting={"hello": 1})


def test_execute_returns_result_and_skips_events(make_qmp: Any) -> None:
    """
    Events and replies to other ids are skipped; the matching reply's ``return`` is given.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """

    def handler(message: dict[str, Any]) -> list[dict[str, Any]]:
        if message["execute"] == "query-status":
            return [
                {"event": "RTC_CHANGE", "data": {}},
                {"return": {"stale": True}, "id": 999},
                {"return": {"status": "running"}, "id": message["id"]},
            ]
        return ok_handler(message)

    qmp, _server = make_qmp(handler)
    assert qmp.execute("query-status") == {"status": "running"}


def test_execute_error_reply_raises_qmp_error(make_qmp: Any) -> None:
    """
    An error object becomes ``QmpError`` carrying QEMU's description and the command name.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """

    def handler(message: dict[str, Any]) -> list[dict[str, Any]]:
        if message["execute"] == "boom":
            return [{"error": {"class": "GenericError", "desc": "it broke"}, "id": message["id"]}]
        return ok_handler(message)

    qmp, _server = make_qmp(handler)
    with pytest.raises(QmpError, match="boom.*it broke"):
        qmp.execute("boom")


def test_execute_times_out_without_a_reply(make_qmp: Any) -> None:
    """
    A silent server makes ``execute`` raise TimeoutError after the given time.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """

    def handler(message: dict[str, Any]) -> list[dict[str, Any]]:
        return ok_handler(message) if message["execute"] == "qmp_capabilities" else []

    qmp, _server = make_qmp(handler)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="no reply"):
        qmp.execute("query-status", timeout=0.3)
    assert time.monotonic() - started < 3


def test_execute_reports_a_dropped_connection(make_qmp: Any) -> None:
    """
    If QEMU closes the socket while a command is pending, ``execute`` raises ConnectionError.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    holder: dict[str, FakeServer] = {}

    def handler(message: dict[str, Any]) -> list[dict[str, Any]]:
        if message["execute"] == "qmp_capabilities":
            return ok_handler(message)
        holder["server"].sock.close()
        return []

    qmp, server = make_qmp(handler)
    holder["server"] = server
    with pytest.raises(ConnectionError):
        qmp.execute("query-status", timeout=2)


def test_screendump_asks_for_png_and_checks_the_file(make_qmp: Any, tmp_path: Path) -> None:
    """
    ``screendump`` sends the file name and the PNG format, and a reply without a written
    file is an error.

    Args:
        make_qmp: Factory fixture.
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    writes: list[bool] = [True]

    def handler(message: dict[str, Any]) -> list[dict[str, Any]]:
        if message["execute"] == "screendump" and writes[0]:
            Path(message["arguments"]["filename"]).write_bytes(b"\x89PNG fake")
        return ok_handler(message)

    qmp, server = make_qmp(handler)
    target = tmp_path / "shot.png"
    qmp.screendump(target)
    assert target.read_bytes().startswith(b"\x89PNG")
    dump = [m for m in server.received if m["execute"] == "screendump"][0]
    assert dump["arguments"] == {"filename": str(target), "format": "png"}

    writes[0] = False
    with pytest.raises(QmpError, match="no image") as caught:
        qmp.screendump(tmp_path / "missing.png")
    assert str(tmp_path) not in str(caught.value)


def test_send_keys_presses_in_order_and_releases_in_reverse(make_qmp: Any) -> None:
    """
    A chord sends one command with all key-down events, then one with the key-up events in
    reverse order, in the exact QMP event shape.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    qmp, server = make_qmp()
    qmp.send_keys("meta+w")
    down = [{"type": "key", "data": {"down": True, "key": {"type": "qcode", "data": code}}} for code in ("meta_l", "w")]
    up = [{"type": "key", "data": {"down": False, "key": {"type": "qcode", "data": code}}} for code in ("w", "meta_l")]
    assert input_events(server) == [down, up]


def test_send_keys_rejects_a_bad_chord_without_sending(make_qmp: Any) -> None:
    """
    An invalid chord is a ValueError and nothing reaches QEMU.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    qmp, server = make_qmp()
    with pytest.raises(ValueError):
        qmp.send_keys("meta+banana")
    assert input_events(server) == []


def test_type_text_sends_one_press_per_character(make_qmp: Any) -> None:
    """
    Every character is its own down/up pair; a capital adds shift.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    qmp, server = make_qmp()
    qmp.type_text("aB")
    codes = [[(e["data"]["down"], e["data"]["key"]["data"]) for e in events] for events in input_events(server)]
    assert codes == [
        [(True, "a")],
        [(False, "a")],
        [(True, "shift"), (True, "b")],
        [(False, "b"), (False, "shift")],
    ]


def test_type_text_validates_everything_before_typing(make_qmp: Any) -> None:
    """
    Text with one untypeable character types nothing at all.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    qmp, server = make_qmp()
    with pytest.raises(ValueError):
        qmp.type_text("abc!")
    assert input_events(server) == []


def test_pointer_move_payload_shape_and_corners(make_qmp: Any) -> None:
    """
    Moves are absolute x/y events on the 0..32767 axis; the screen corners give 0 and
    32767; no ``device`` argument is sent (QMP would read it as a display device).

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    qmp, server = make_qmp()
    qmp.pointer_move(0, 0)
    qmp.pointer_move(2559, 1439)
    assert input_events(server) == [
        [{"type": "abs", "data": {"axis": "x", "value": 0}}, {"type": "abs", "data": {"axis": "y", "value": 0}}],
        [
            {"type": "abs", "data": {"axis": "x", "value": 32767}},
            {"type": "abs", "data": {"axis": "y", "value": 32767}},
        ],
    ]
    for message in server.received:
        if message["execute"] == "input-send-event":
            assert set(message["arguments"]) == {"events"}


def test_pointer_move_outside_the_screen_sends_nothing(make_qmp: Any) -> None:
    """
    A position off the screen is a ValueError and no event is sent.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    qmp, server = make_qmp()
    for x, y in [(2560, 0), (0, 1440), (-1, 5)]:
        with pytest.raises(ValueError):
            qmp.pointer_move(x, y)
    assert input_events(server) == []


def test_pointer_click_moves_then_presses_and_releases_the_left_button(make_qmp: Any) -> None:
    """
    A click is move, left button down, left button up, in that order.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    pauses: list[float] = []
    qmp, server = make_qmp(sleep=pauses.append)
    qmp.pointer_click(1280, 720)
    events = input_events(server)
    assert [e[0]["type"] for e in events] == ["abs", "btn", "btn"]
    assert events[1] == [{"type": "btn", "data": {"down": True, "button": "left"}}]
    assert events[2] == [{"type": "btn", "data": {"down": False, "button": "left"}}]
    assert len(pauses) == 2 and all(p > 0 for p in pauses)  # a pause before and during the click


def test_quit_sends_the_quit_command(make_qmp: Any) -> None:
    """
    ``quit`` asks QEMU to exit.

    Args:
        make_qmp: Factory fixture.

    Returns:
        None.
    """
    qmp, server = make_qmp()
    qmp.quit()
    assert server.received[-1]["execute"] == "quit"


# --- guest agent -----------------------------------------------------------------------


class AgentState:
    """
    Behaviour and record of a fake guest agent.

    Attributes:
        commands: Every command received (name, arguments) except sync.
        execs: Arguments of every ``guest-exec``.
        results: Maps the program path of a ``guest-exec`` to ``(exit code, stdout)``;
            missing paths succeed with no output.
        errors: Maps a command name to an error description to answer with.
    """

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.execs: list[dict[str, Any]] = []
        self.results: dict[str, tuple[int, str]] = {}
        self.errors: dict[str, str] = {}
        self.silent = False
        self._pids: dict[int, dict[str, Any]] = {}

    def handle(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Answer one message like the guest agent would.

        Args:
            message: The received command.

        Returns:
            The replies to send.
        """
        if self.silent:
            return []
        command, arguments = message["execute"], message.get("arguments", {})
        if command == "guest-sync":
            return [{"return": arguments["id"]}]
        self.commands.append((command, arguments))
        if command in self.errors:
            return [{"error": {"class": "GenericError", "desc": self.errors[command]}}]
        if command == "guest-ping":
            return [{"return": {}}]
        if command == "guest-exec":
            pid = 100 + len(self.execs)
            self.execs.append(arguments)
            self._pids[pid] = arguments
            return [{"return": {"pid": pid}}]
        if command == "guest-exec-status":
            arguments_of_exec = self._pids[arguments["pid"]]
            code, out = self.results.get(arguments_of_exec["path"], (0, ""))
            return [{"return": {"exited": True, "exitcode": code, "out-data": base64.b64encode(out.encode()).decode()}}]
        if command == "guest-file-open":
            return [{"return": 7}]
        return [{"return": {}}]


@pytest.fixture
def make_agent() -> Iterator[Callable[..., tuple[GuestAgent, AgentState]]]:
    """
    Provide a factory for a ``GuestAgent`` connected to a fake agent.

    Yields:
        A function returning the client and the behaviour/record object; sockets are
        closed after the test.
    """
    opened: list[socket.socket] = []

    def factory() -> tuple[GuestAgent, AgentState]:
        client_sock, server_sock = socket.socketpair()
        state = AgentState()
        FakeServer(server_sock, state.handle).start()
        opened.extend([client_sock, server_sock])
        return GuestAgent(JsonLineChannel(client_sock), sleep=lambda seconds: None), state

    yield factory
    for sock in opened:
        try:
            sock.close()
        except OSError:
            pass


SHOW_ENVIRONMENT = "WAYLAND_DISPLAY=wayland-0\nXDG_MENU_PREFIX=plasma-\nDEBUGINFOD_URLS=$'a b'\nFOO=bar\n"


def test_call_times_out_when_the_agent_is_silent(make_agent: Any) -> None:
    """
    An agent that never answers the sync request is a TimeoutError naming the command.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    state.silent = True
    with pytest.raises(TimeoutError, match="guest-ping"):
        agent.call("guest-ping", timeout=0.3)


def test_call_error_reply_raises_guest_agent_error(make_agent: Any) -> None:
    """
    An error object from the agent becomes ``GuestAgentError`` with its description.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    state.errors["guest-info"] = "command disabled"
    with pytest.raises(GuestAgentError, match="guest-info.*command disabled"):
        agent.call("guest-info")


def test_wait_ready_returns_when_the_agent_answers_and_times_out_otherwise(make_agent: Any) -> None:
    """
    ``wait_ready`` returns the waiting time once the agent answers, raises TimeoutError
    when it never does, and stops with ConnectionError when the VM is reported dead.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    assert agent.wait_ready(5) >= 0
    with pytest.raises(ConnectionError, match="exited"):
        agent.wait_ready(5, alive=lambda: False)
    state.silent = True
    with pytest.raises(TimeoutError, match="did not come up"):
        agent.wait_ready(0.4)


def test_run_as_user_wraps_the_command_in_the_session_environment(make_agent: Any) -> None:
    """
    The program is started through ``runuser`` and ``env -C <home>`` with the defaults and
    the session's plain variables; the quoted variable is skipped; the program's own
    arguments come last; nothing is waited for.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    state.results["/usr/bin/runuser"] = (0, SHOW_ENVIRONMENT)  # the environment lookup
    assert agent.run_as_user(["dolphin", "Documents"]) is None
    lookup, started = state.execs
    assert lookup["arg"][-3:] == ["/usr/bin/systemctl", "--user", "show-environment"]
    assert started["path"] == "/usr/bin/runuser"
    assert started["capture-output"] is False
    args = started["arg"]
    assert args[:6] == ["-u", "desktop", "--", "/usr/bin/env", "-C", "/home/desktop"]
    assert args[-2:] == ["dolphin", "Documents"]
    assert "XDG_RUNTIME_DIR=/run/user/1000" in args
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus" in args
    assert "WAYLAND_DISPLAY=wayland-0" in args
    assert "XDG_MENU_PREFIX=plasma-" in args
    assert not any(a.startswith("DEBUGINFOD_URLS") for a in args)
    # Not waiting: no status query for the started program (only the lookup was waited for).
    assert [c for c, _ in state.commands].count("guest-exec-status") == 1


def test_run_as_user_can_wait_and_returns_the_result(make_agent: Any) -> None:
    """
    With ``wait_exit`` the exit code and output of the program are returned.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    state.results["/usr/bin/runuser"] = (3, "hello")
    result = agent.run_as_user(["tool"], wait_exit=True)
    assert result == ExecResult(exit_code=3, stdout="hello", stderr="")


def test_session_environment_is_cached_only_once_the_session_was_seen(make_agent: Any) -> None:
    """
    A lookup that did not see the session (no Wayland display yet) is repeated next time;
    one that did is remembered.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    state.results["/usr/bin/runuser"] = (1, "")  # session not up: systemctl fails
    first = agent.session_environment()
    assert "XDG_RUNTIME_DIR=/run/user/1000" in first  # the defaults still work
    assert len(state.execs) == 1
    agent.session_environment()
    assert len(state.execs) == 2  # asked again

    state.results["/usr/bin/runuser"] = (0, SHOW_ENVIRONMENT)
    agent.session_environment()
    agent.session_environment()
    assert len(state.execs) == 3  # one successful lookup, then cached


@pytest.mark.parametrize(
    "argv",
    [[], [""], ["a", ""], ["a\x00b"], ["x"] * 65, ["A=b"], [5], "dolphin"],
)
def test_run_as_user_rejects_bad_argument_lists(make_agent: Any, argv: Any) -> None:
    """
    Empty lists, empty or NUL-containing items, too many items, a program name with ``=``
    and non-lists are ValueErrors and nothing is executed.

    Args:
        make_agent: Factory fixture.
        argv: The bad argument list.

    Returns:
        None.
    """
    agent, state = make_agent()
    with pytest.raises(ValueError):
        agent.run_as_user(argv)
    assert state.execs == []


def test_write_file_creates_the_directory_writes_and_hands_the_file_over(make_agent: Any) -> None:
    """
    Sequence: mkdir as the desktop user, open/write/close with the base64 content, then
    chown to the desktop user.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    agent._session_env = ["XDG_RUNTIME_DIR=/run/user/1000"]  # skip the environment lookup
    target = "/home/desktop/.local/share/color-schemes/x.colors"
    agent.write_file(target, b"[General]\nName=x\n")

    names = [c for c, _ in state.commands]
    assert names == [
        "guest-exec", "guest-exec-status",      # mkdir -p
        "guest-file-open", "guest-file-write", "guest-file-close",
        "guest-exec", "guest-exec-status",      # chown
    ]
    mkdir, chown = state.execs
    assert mkdir["path"] == "/usr/bin/runuser" and "/usr/bin/mkdir" in mkdir["arg"]
    assert mkdir["arg"][-2:] == ["-p", "/home/desktop/.local/share/color-schemes"]
    assert chown == {"path": "/usr/bin/chown", "arg": ["desktop:desktop", target], "capture-output": True}
    by_name = {c: a for c, a in state.commands if c.startswith("guest-file")}
    assert by_name["guest-file-open"] == {"path": target, "mode": "w"}
    assert base64.b64decode(by_name["guest-file-write"]["buf-b64"]) == b"[General]\nName=x\n"
    assert by_name["guest-file-close"] == {"handle": 7}


def test_write_file_closes_the_handle_when_writing_fails(make_agent: Any) -> None:
    """
    A failed write still closes the guest file handle and reports the error.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    agent._session_env = []
    state.errors["guest-file-write"] = "disk full"
    with pytest.raises(GuestAgentError, match="disk full"):
        agent.write_file("/home/desktop/a.txt", b"data")
    assert "guest-file-close" in [c for c, _ in state.commands]


def test_write_file_reports_a_failed_chown_without_paths(make_agent: Any) -> None:
    """
    If handing the file over fails, the error names only the file, not its directory.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    agent._session_env = []
    state.results["/usr/bin/chown"] = (1, "")
    with pytest.raises(GuestAgentError, match="a.txt") as caught:
        agent.write_file("/home/desktop/secret-dir/a.txt", b"data")
    assert "secret-dir" not in str(caught.value)


@pytest.mark.parametrize("path", ["relative.txt", "", "/tmp/a\x00b"])
def test_write_file_rejects_bad_paths_and_data(make_agent: Any, path: str) -> None:
    """
    Only absolute paths without NUL are accepted, and the data must be bytes.

    Args:
        make_agent: Factory fixture.
        path: The bad path.

    Returns:
        None.
    """
    agent, state = make_agent()
    with pytest.raises(ValueError):
        agent.write_file(path, b"x")
    with pytest.raises(ValueError):
        agent.write_file("/tmp/ok.txt", "text")  # type: ignore[arg-type]
    assert state.commands == []


def test_process_running_uses_pgrep_exit_status(make_agent: Any) -> None:
    """
    ``pgrep`` exit 0 means the process exists, 1 means it does not; odd names are rejected.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    state.results["/usr/bin/pgrep"] = (0, "")
    assert agent.process_running("plasmashell") is True
    state.results["/usr/bin/pgrep"] = (1, "")
    assert agent.process_running("plasmashell") is False
    for bad in ["", "a b", "x" * 16, "a;b"]:
        with pytest.raises(ValueError):
            agent.process_running(bad)


def test_cpu_sample_reads_busy_and_idle_jiffies(make_agent: Any) -> None:
    """
    The first ``cpu`` line of ``/proc/stat`` becomes ``(busy, idle)``: user, nice, system,
    irq and softirq are busy, idle and iowait are idle, stolen time is ignored; damaged
    output is a ``GuestAgentError``.

    Args:
        make_agent: Factory fixture.

    Returns:
        None.
    """
    agent, state = make_agent()
    state.results["/usr/bin/cat"] = (0, "cpu  100 5 50 800 50 3 2 7 0 0\ncpu0 25 1 12 200 12 1 0 2 0 0\n")
    assert agent.cpu_sample() == (100 + 5 + 50 + 3 + 2, 850)
    for bad in ((0, "garbage\n"), (0, ""), (1, "cpu  1 2 3 4 5 6 7\n"), (0, "cpu  a b c d e f g\n")):
        state.results["/usr/bin/cat"] = bad
        with pytest.raises(GuestAgentError, match="CPU counters"):
            agent.cpu_sample()


def test_guest_user_defaults_describe_the_image_session() -> None:
    """
    The default user maps to the paths and variables of the session.

    Returns:
        None.
    """
    user = GuestUser()
    assert user.home == "/home/desktop"
    assert user.runtime_dir == "/run/user/1000"
    environment = user.environment()
    assert "HOME=/home/desktop" in environment
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus" in environment
    assert "WAYLAND_DISPLAY=wayland-0" in environment

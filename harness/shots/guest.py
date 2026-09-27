"""
QEMU guest-agent client for the screenshot harness.

The guest agent (a small daemon that runs as root in the guest and talks over a
virtio-serial port) is used for exactly three things: finding out whether the desktop
session is up, starting programs AS THE DESKTOP USER, and writing files into that
user's home. It never produces the screenshot and never sends input - those go
through QMP from the host.

Why programs must start "as the desktop user with the session's environment": the
agent itself runs as root outside the graphical session. A GUI program started that
way would fail (no Wayland socket, no session bus) or, worse, run as root. The trick
is ``runuser -u <user> -- env VAR=... program``: it switches to the desktop user and
hands over the runtime directory, the session DBus address and the Wayland display,
which is all a Qt/KDE program needs to find the running session.

Timeouts and errors mirror ``harness.shots.qmp``: ``TimeoutError``, ``ConnectionError``,
``GuestAgentError`` (the agent answered with an error) and ``ValueError`` (bad input).
Standard library only.
"""

from __future__ import annotations

import base64
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.shots.qmp import JsonLineChannel

# Programs the agent starts by absolute path so that the lookup does not depend on the
# agent's own PATH.
RUNUSER = "/usr/bin/runuser"
ENV = "/usr/bin/env"
CHOWN = "/usr/bin/chown"
MKDIR = "/usr/bin/mkdir"
PGREP = "/usr/bin/pgrep"
CAT = "/usr/bin/cat"
SYSTEMCTL = "/usr/bin/systemctl"

# Largest chunk written with one guest-file-write call. The agent limits a single
# request to a few megabytes; colour scheme files are a few kilobytes, so this only
# matters for correctness with larger data.
_WRITE_CHUNK = 256 * 1024

# A line of `systemctl --user show-environment` that is a plain NAME=value pair. The
# quoted form NAME=$'...' (used for values with spaces) is not parsed and is skipped.
_PLAIN_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=[^$]")

# Sanity limits for programs started in the guest. A caller's own command may have at
# most _MAX_ARGS arguments; the command the agent really receives is longer, because
# run_as_user prefixes it with runuser and the session's environment (about fifty
# NAME=value words), so the internal limit is higher.
_MAX_ARGS = 64
_MAX_WRAPPED_ARGS = 512
_MAX_ARG_LENGTH = 4096


class GuestAgentError(RuntimeError):
    """The guest agent answered a command with an error object."""


@dataclass(frozen=True)
class GuestUser:
    """
    The desktop user of the guest image and the session it is logged in to.

    The defaults describe the feasibility-spike image (fixed account, automatic login
    into the Wayland Plasma session). They are values of the IMAGE, kept in one place
    so a change of the image touches one class.

    Attributes:
        name: Login name of the desktop user.
        uid: Numeric user id (defines the runtime directory ``/run/user/<uid>``).
        group: Primary group name used when giving files to the user.
        wayland_display: Name of the compositor's Wayland socket in the runtime dir.
        extra_env: Further ``(name, value)`` pairs the session exports and that KDE
            programs read (session type and desktop name select the platform theme).
    """

    name: str = "desktop"
    uid: int = 1000
    group: str = "desktop"
    wayland_display: str = "wayland-0"
    extra_env: tuple[tuple[str, str], ...] = (
        ("XDG_SESSION_TYPE", "wayland"),
        ("XDG_CURRENT_DESKTOP", "KDE"),
        ("XDG_SESSION_DESKTOP", "KDE"),
        ("KDE_FULL_SESSION", "true"),
        ("KDE_SESSION_VERSION", "6"),
    )

    @property
    def home(self) -> str:
        """Guest path of the user's home directory."""
        return f"/home/{self.name}"

    @property
    def runtime_dir(self) -> str:
        """Guest path of the user's runtime directory (holds the Wayland and bus sockets)."""
        return f"/run/user/{self.uid}"

    def environment(self) -> list[str]:
        """
        The ``NAME=value`` assignments that make a program find the running session.

        These are the DEFAULTS; the running session's own environment (read by
        ``GuestAgent.session_environment``) is layered on top of them.

        Returns:
            The assignments for ``env``: user identity, runtime directory, session bus
            address, Wayland display and ``extra_env``.
        """
        pairs = [
            ("HOME", self.home),
            ("USER", self.name),
            ("LOGNAME", self.name),
            ("XDG_RUNTIME_DIR", self.runtime_dir),
            ("DBUS_SESSION_BUS_ADDRESS", f"unix:path={self.runtime_dir}/bus"),
            ("WAYLAND_DISPLAY", self.wayland_display),
            *self.extra_env,
        ]
        return [f"{name}={value}" for name, value in pairs]


@dataclass(frozen=True)
class ExecResult:
    """
    Outcome of a program that ran to completion in the guest.

    Attributes:
        exit_code: Exit status (negative when the program was killed by a signal).
        stdout: Captured standard output, decoded leniently as UTF-8.
        stderr: Captured standard error, decoded leniently as UTF-8.
    """

    exit_code: int
    stdout: str
    stderr: str


def _check_argv(argv: list[str], max_args: int = _MAX_ARGS) -> None:
    """
    Reject argument lists that cannot be a sane program invocation.

    Args:
        argv: Program followed by its arguments.
        max_args: Longest list accepted.

    Raises:
        ValueError: if the list is empty or too long, holds a non-string, an empty or
            NUL-containing or oversized item, or if the program name contains ``=``
            (``env`` would read it as a variable assignment).
    """
    if not isinstance(argv, (list, tuple)) or not argv:
        raise ValueError("a guest command needs a non-empty argument list")
    if len(argv) > max_args:
        raise ValueError(f"a guest command may have at most {_MAX_ARGS} arguments")
    for item in argv:
        if not isinstance(item, str) or not item or "\x00" in item or len(item) > _MAX_ARG_LENGTH:
            raise ValueError("guest command arguments must be non-empty strings without NUL")
    if "=" in argv[0]:
        raise ValueError("the program name of a guest command must not contain '='")


class GuestAgent:
    """
    Client for the guest-agent channel.

    Every request is preceded by ``guest-sync`` so that stale replies from an earlier,
    abandoned request cannot be mistaken for the answer.

    Args:
        channel: Connected channel to the agent's socket.
        user: The desktop user (see ``GuestUser``).
        sleep: Sleep function (replaced in tests).
    """

    def __init__(
        self,
        channel: JsonLineChannel,
        user: GuestUser | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._channel = channel
        self.user = user or GuestUser()
        self._sleep = sleep
        # WHY seeded from the clock: a fresh client must not reuse ids a previous
        # client already sent, or its own stale replies would look valid.
        self._sync_id = int(time.time()) & 0xFFFFFF
        self._session_env: list[str] | None = None

    @classmethod
    def connect(
        cls,
        path: Path,
        user: GuestUser | None = None,
        timeout: float = 30.0,
        alive: Callable[[], bool] | None = None,
    ) -> GuestAgent:
        """
        Connect to the agent socket (does not wait for the agent inside the guest).

        Args:
            path: Socket path.
            user: The desktop user; the image default when None.
            timeout: Seconds to wait for the socket to appear.
            alive: Optional "QEMU is still running" check.

        Returns:
            The client.

        Raises:
            TimeoutError, ConnectionError, ValueError: see ``JsonLineChannel.connect``.
        """
        return cls(JsonLineChannel.connect(path, timeout, alive), user)

    def _sync(self, timeout: float) -> bool:
        """
        Discard stale replies until the agent echoes a fresh sync id.

        Args:
            timeout: Seconds to wait for the echo.

        Returns:
            True when the agent is synchronised, False when it did not answer.
        """
        self._sync_id += 1
        self._channel.send({"execute": "guest-sync", "arguments": {"id": self._sync_id}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reply = self._channel.recv(min(1.0, max(0.0, deadline - time.monotonic())))
            if reply is not None and reply.get("return") == self._sync_id:
                return True
        return False

    def call(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> Any:
        """
        Run one agent command.

        Args:
            command: Agent command name, for example ``"guest-exec"``.
            arguments: Command arguments, or None.
            timeout: Seconds to wait for the synchronisation and again for the reply.

        Returns:
            The ``return`` member of the reply.

        Raises:
            TimeoutError: the agent did not answer (it may not have started yet).
            GuestAgentError: the agent answered with an error.
            ConnectionError: the connection broke.
        """
        if not self._sync(timeout):
            raise TimeoutError(f"guest agent did not answer (command {command!r})")
        message: dict[str, Any] = {"execute": command}
        if arguments:
            message["arguments"] = arguments
        self._channel.send(message)
        reply = self._channel.recv(timeout)
        if reply is None:
            raise TimeoutError(f"no reply from the guest agent to {command!r} within {timeout:g} s")
        if "error" in reply:
            error = reply["error"] if isinstance(reply["error"], dict) else {}
            raise GuestAgentError(f"guest command {command!r} failed: {error.get('desc', 'unknown error')}")
        return reply.get("return")

    def wait_ready(self, timeout: float, alive: Callable[[], bool] | None = None) -> float:
        """
        Wait until the agent inside the guest answers.

        Args:
            timeout: Seconds to wait in total.
            alive: Optional "QEMU is still running" check.

        Returns:
            Seconds that the wait took.

        Raises:
            TimeoutError: the agent never answered.
            ConnectionError: QEMU died while waiting.
        """
        start = time.monotonic()
        while True:
            if alive is not None and not alive():
                raise ConnectionError("the VM exited while waiting for the guest agent")
            try:
                self.call("guest-ping", timeout=min(2.0, timeout))
                return time.monotonic() - start
            except TimeoutError:
                if time.monotonic() - start > timeout:
                    raise TimeoutError(f"guest agent did not come up within {timeout:g} s") from None

    def start(self, argv: list[str]) -> int:
        """
        Start a program as root (the agent's own user) without waiting for it.

        Args:
            argv: Program (absolute path) and arguments.

        Returns:
            The process id inside the guest.

        Raises:
            ValueError: bad argument list.
            GuestAgentError, TimeoutError, ConnectionError: see ``call``.
        """
        _check_argv(argv, _MAX_WRAPPED_ARGS)
        started = self.call("guest-exec", {"path": argv[0], "arg": list(argv[1:]), "capture-output": False})
        return int(started["pid"])

    def exec(self, argv: list[str], timeout: float = 20.0) -> ExecResult:
        """
        Run a program as root and wait for it, capturing its output.

        Args:
            argv: Program (absolute path) and arguments; no shell is involved.
            timeout: Seconds to wait for the program to finish.

        Returns:
            Exit code and output.

        Raises:
            ValueError: bad argument list.
            TimeoutError: the program did not finish in time.
            GuestAgentError, ConnectionError: see ``call``.
        """
        _check_argv(argv, _MAX_WRAPPED_ARGS)
        started = self.call("guest-exec", {"path": argv[0], "arg": list(argv[1:]), "capture-output": True})
        pid = started["pid"]
        deadline = time.monotonic() + timeout
        while True:
            status = self.call("guest-exec-status", {"pid": pid})
            if status.get("exited"):
                return ExecResult(
                    exit_code=int(status.get("exitcode", -1 if "signal" in status else 0)),
                    stdout=base64.b64decode(status.get("out-data", "")).decode("utf-8", "replace"),
                    stderr=base64.b64decode(status.get("err-data", "")).decode("utf-8", "replace"),
                )
            if time.monotonic() > deadline:
                raise TimeoutError(f"guest program {Path(argv[0]).name!r} did not finish within {timeout:g} s")
            self._sleep(0.2)

    def session_environment(self) -> list[str]:
        """
        The environment a program needs to live inside the running desktop session.

        The session exports its variables (Wayland display, desktop name, menu prefix,
        rendering switches, ...) to the user's systemd manager, and
        ``systemctl --user show-environment`` lists them. They are layered over the
        ``GuestUser`` defaults, so a variable the session does not export still has a
        sane value. The result is cached once the session variables were really seen
        (a lookup before the session is up would otherwise be remembered).

        Returns:
            ``NAME=value`` assignments for ``env``.

        Raises:
            GuestAgentError, TimeoutError, ConnectionError: see ``call`` (a failing
                ``systemctl`` is NOT an error: the defaults are returned).
        """
        if self._session_env is not None:
            return self._session_env
        defaults = self.user.environment()
        lookup = [
            RUNUSER, "-u", self.user.name, "--", ENV,
            f"XDG_RUNTIME_DIR={self.user.runtime_dir}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path={self.user.runtime_dir}/bus",
            SYSTEMCTL, "--user", "show-environment",
        ]
        result = self.exec(lookup, timeout=20.0)
        discovered = []
        if result.exit_code == 0:
            discovered = [line for line in result.stdout.splitlines() if _PLAIN_ASSIGNMENT.match(line)]
        # env(1) lets later assignments win: the running session overrides the defaults.
        merged = [*defaults, *discovered]
        if any(line.startswith("WAYLAND_DISPLAY=") for line in discovered):
            self._session_env = merged
        return merged

    def run_as_user(
        self,
        argv: list[str],
        wait_exit: bool = False,
        timeout: float = 30.0,
    ) -> ExecResult | None:
        """
        Run a program as the desktop user, inside the running desktop session.

        The program is wrapped in ``runuser -u <user> -- env -C <home> <session variables>``,
        so it sees the session's runtime directory, DBus session bus and Wayland display
        (see the module docstring) and starts in the user's home directory (relative
        paths in ``argv`` are relative to it).

        Args:
            argv: Program and arguments; the program is looked up on the user's PATH.
            wait_exit: True to wait for the program and return its result; False
                (default) to return as soon as it has been started. A GUI program
                that keeps running must use False.
            timeout: Seconds to wait when ``wait_exit`` is True.

        Returns:
            The ``ExecResult`` when ``wait_exit`` is True, otherwise None.

        Raises:
            ValueError: bad argument list.
            TimeoutError: ``wait_exit`` and the program did not finish in time.
            GuestAgentError, ConnectionError: see ``call``.
        """
        _check_argv(argv)
        wrapped = [RUNUSER, "-u", self.user.name, "--", ENV, "-C", self.user.home, *self.session_environment(), *argv]
        if wait_exit:
            return self.exec(wrapped, timeout=timeout)
        self.start(wrapped)
        return None

    def write_file(self, path: str, data: bytes) -> None:
        """
        Write a file into the guest and give it to the desktop user.

        The parent directory is created (as the desktop user, so it is theirs), the
        content is written with the agent's file API, and the file is then handed over
        with ``chown``: the agent runs as root, so the file would otherwise belong to
        root and the desktop user's programs could not replace it.

        Args:
            path: Absolute guest path.
            data: File content.

        Raises:
            ValueError: the path is not absolute or contains NUL, or ``data`` is not bytes.
            GuestAgentError: the agent refused a command or ``mkdir``/``chown`` failed.
            TimeoutError, ConnectionError: see ``call``.
        """
        if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
            raise ValueError("a guest file path must be absolute")
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("file data must be bytes")

        parent = path.rsplit("/", 1)[0] or "/"
        made = self.run_as_user([MKDIR, "-p", parent], wait_exit=True)
        if made is None or made.exit_code != 0:
            raise GuestAgentError(f"could not create the guest directory for {path.rsplit('/', 1)[-1]!r}")

        handle = self.call("guest-file-open", {"path": path, "mode": "w"})
        try:
            for offset in range(0, max(len(data), 1), _WRITE_CHUNK):
                chunk = bytes(data[offset : offset + _WRITE_CHUNK])
                self.call("guest-file-write", {"handle": handle, "buf-b64": base64.b64encode(chunk).decode()})
        finally:
            self.call("guest-file-close", {"handle": handle})

        owned = self.exec([CHOWN, f"{self.user.name}:{self.user.group}", path])
        if owned.exit_code != 0:
            raise GuestAgentError(f"could not give {path.rsplit('/', 1)[-1]!r} to the desktop user")

    def cpu_sample(self) -> tuple[int, int]:
        """
        Read the guest's CPU time counters.

        Two samples taken some time apart tell how busy the guest was in between. Time
        stolen by the host is ignored (it is neither guest work nor guest idleness).

        Returns:
            ``(busy, idle)`` jiffies summed over all CPUs: busy is user, nice, system,
            irq and softirq time; idle includes I/O wait.

        Raises:
            GuestAgentError: the counters could not be read or parsed.
            TimeoutError, ConnectionError: see ``call``.
        """
        result = self.exec([CAT, "/proc/stat"], timeout=10.0)
        try:
            if result.exit_code != 0:
                raise ValueError("cat failed")
            fields = result.stdout.splitlines()[0].split()
            if fields[0] != "cpu":
                raise ValueError("no aggregate cpu line")
            user, nice, system, idle, iowait, irq, softirq = (int(v) for v in fields[1:8])
        except (ValueError, IndexError):
            raise GuestAgentError("could not read the guest CPU counters") from None
        return user + nice + system + irq + softirq, idle + iowait

    def process_running(self, name: str) -> bool:
        """
        Tell whether a process with exactly this name exists in the guest.

        Args:
            name: Process name as ``pgrep -x`` matches it (at most 15 characters).

        Returns:
            True when at least one such process exists.

        Raises:
            ValueError: the name is empty or not a plain process name.
            GuestAgentError, TimeoutError, ConnectionError: see ``call``.
        """
        if not name or len(name) > 15 or not all(c.isalnum() or c in "_.-" for c in name):
            raise ValueError("process name must be 1..15 letters, digits, '_', '.' or '-'")
        return self.exec([PGREP, "-x", name], timeout=10.0).exit_code == 0

    def close(self) -> None:
        """Close the connection to the agent."""
        self._channel.close()

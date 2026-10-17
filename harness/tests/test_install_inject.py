"""
Behaviour tests for harness.install.wizard.inject_test_only_session_config.

The guest agent is replaced by a small recording fake that offers the two methods the
function uses (write_file, exec); the function under test itself runs unmodified.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import skelmerge
from harness.install import wizard
from harness.install.wizard import WizardError, inject_test_only_session_config
from harness.shots.guest import ExecResult, GuestUser

USER = GuestUser(name="tester", group="tester")


class FakeAgent:
    """Records writes and commands; can be told to fail a command or a write."""

    def __init__(self, fail_argv_containing: str | None = None, fail_write: bool = False) -> None:
        self.writes: dict[str, bytes] = {}
        self.commands: list[list[str]] = []
        self.fail_argv_containing = fail_argv_containing
        self.fail_write = fail_write

    def write_file(self, path: str, data: bytes) -> None:
        if self.fail_write:
            raise ConnectionError("agent gone")
        self.writes[path] = data

    def exec(self, argv: list[str], timeout: float = 20.0) -> ExecResult:
        self.commands.append(argv)
        failed = self.fail_argv_containing is not None and self.fail_argv_containing in argv
        return ExecResult(exit_code=1 if failed else 0, stdout="", stderr="secret detail")


def make_vm(agent: FakeAgent | None) -> SimpleNamespace:
    """Build the minimal InstallVm stand-in (only ``agent`` is read)."""
    return SimpleNamespace(agent=agent)


@pytest.fixture
def skel(tmp_path: Path) -> Path:
    """A tiny skeleton tree with a nested file."""
    root = tmp_path / "skel"
    (root / ".config/environment.d").mkdir(parents=True)
    (root / ".config/kwinrulesrc").write_bytes(b"rules")
    (root / ".config/environment.d/10-x.conf").write_bytes(b"env")
    (root / ".config/user-dirs.dirs").write_bytes(b"dirs")
    return root


ENTRIES = [
    skelmerge.ConfigEntry(".config/kdeglobals", ("KDE",), "AnimationDurationFactor", "0"),
    skelmerge.ConfigEntry(".config/kdeglobals", ("KDE",), "CursorBlinkRate", "0"),
]


def test_every_skel_file_is_written_under_the_users_home(skel: Path) -> None:
    """All files, including nested ones, land at the same relative path in the home."""
    agent = FakeAgent()
    inject_test_only_session_config(make_vm(agent), USER, skel_dir=skel, merge_entries=[])
    assert agent.writes == {
        "/home/tester/.config/environment.d/10-x.conf": b"env",
        "/home/tester/.config/kwinrulesrc": b"rules",
        "/home/tester/.config/user-dirs.dirs": b"dirs",
    }


def test_merge_entries_run_as_the_desktop_user_with_exact_argv(skel: Path) -> None:
    """Each entry becomes runuser -u <user> -- <kwriteconfig argv>, in order."""
    agent = FakeAgent()
    inject_test_only_session_config(make_vm(agent), USER, skel_dir=skel, merge_entries=ENTRIES)
    expected = [
        ["/usr/bin/runuser", "-u", "tester", "--", *skelmerge.kwriteconfig_argv(e, "/home/tester")]
        for e in ENTRIES
    ]
    assert agent.commands[:2] == expected
    assert expected[0][4:] == [
        "kwriteconfig6", "--file", "/home/tester/.config/kdeglobals",
        "--group", "KDE", "--key", "AnimationDurationFactor", "0",
    ]


def test_timezone_is_linked_to_utc_last(skel: Path) -> None:
    """The UTC symlink command runs as root (no runuser) after the merges."""
    agent = FakeAgent()
    inject_test_only_session_config(make_vm(agent), USER, skel_dir=skel, merge_entries=ENTRIES)
    assert agent.commands[-1] == ["/usr/bin/ln", "-sfn", "../usr/share/zoneinfo/UTC", "/etc/localtime"]
    assert len(agent.commands) == len(ENTRIES) + 1


def test_a_failing_kwriteconfig_raises_with_the_key_but_no_agent_output(skel: Path) -> None:
    """Non-zero exit is an error naming file and key; stderr is not echoed."""
    agent = FakeAgent(fail_argv_containing="CursorBlinkRate")
    with pytest.raises(WizardError, match="CursorBlinkRate") as info:
        inject_test_only_session_config(make_vm(agent), USER, skel_dir=skel, merge_entries=ENTRIES)
    assert "secret detail" not in str(info.value)


def test_a_failing_timezone_command_raises(skel: Path) -> None:
    """A non-zero ln exit is reported."""
    agent = FakeAgent(fail_argv_containing="/etc/localtime")
    with pytest.raises(WizardError, match="timezone"):
        inject_test_only_session_config(make_vm(agent), USER, skel_dir=skel, merge_entries=[])


def test_an_unreadable_skel_file_raises_without_the_host_path(skel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An OSError while reading a source file becomes a WizardError naming the relative file."""
    original = Path.read_bytes

    def broken(self: Path) -> bytes:
        if self.name == "kwinrulesrc":
            raise PermissionError(str(self))
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", broken)
    with pytest.raises(WizardError, match="kwinrulesrc") as info:
        inject_test_only_session_config(make_vm(FakeAgent()), USER, skel_dir=skel, merge_entries=[])
    assert str(skel) not in str(info.value)


def test_a_failed_guest_write_raises(skel: Path) -> None:
    """A connection error from the agent becomes a WizardError."""
    with pytest.raises(WizardError, match="could not write"):
        inject_test_only_session_config(make_vm(FakeAgent(fail_write=True)), USER, skel_dir=skel, merge_entries=[])


def test_missing_agent_is_rejected(skel: Path) -> None:
    """Without a connected agent nothing can be injected."""
    with pytest.raises(WizardError, match="guest agent"):
        inject_test_only_session_config(make_vm(None), USER, skel_dir=skel, merge_entries=[])


def test_missing_skel_directory_is_rejected(tmp_path: Path) -> None:
    """A moved/missing source tree fails loudly instead of injecting nothing."""
    with pytest.raises(WizardError, match="skeleton"):
        inject_test_only_session_config(make_vm(FakeAgent()), USER, skel_dir=tmp_path / "nope", merge_entries=[])


def test_defaults_cover_the_real_skel_tree_and_real_fragments() -> None:
    """With no overrides the real directory and real fragments are used."""
    agent = FakeAgent()
    inject_test_only_session_config(make_vm(agent), USER)
    expected_files = sorted(
        p.relative_to(wizard._GUEST_SKEL_DIR).as_posix() for p in wizard._GUEST_SKEL_DIR.rglob("*") if p.is_file()
    )
    assert sorted(w.removeprefix("/home/tester/") for w in agent.writes) == expected_files
    assert len(agent.commands) == len(skelmerge.load_fragments()) + 1

"""
Behaviour tests for pulling Calamares' own logs out of a live guest after a failed
install: harness.install.wizard.collect_install_failure_logs,
harness.install.run._pull_failure_logs and the phase-1 agent channel in
harness.install.boot.

The guest agent is replaced by a small scripted fake offering the one method the
code uses (``exec``); the functions under test run unmodified.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from harness.install import run as run_module
from harness.install.boot import Firmware, InstallVm, InstallVmConfig, build_command
from harness.install.wizard import FAILURE_LOGS, collect_install_failure_logs
from harness.shots.guest import ExecResult


class ScriptedAgent:
    """Answers each guest command by the program name; records every command."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.commands: list[list[str]] = []

    def exec(self, argv: list[str], timeout: float = 20.0) -> ExecResult:
        self.commands.append(argv)
        answer = self.answers[argv[0]]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _ok(text: str) -> ExecResult:
    return ExecResult(exit_code=0, stdout=text, stderr="")


def test_collect_saves_session_log_and_journal(tmp_path: Path) -> None:
    """Both logs are written under dest_dir with the documented names and content."""
    agent = ScriptedAgent({"/usr/bin/tail": _ok("Traceback: boom\n"), "/usr/bin/journalctl": _ok("kernel line\n")})
    dest = tmp_path / "uefi"
    written = collect_install_failure_logs(agent, dest)
    assert written == [dest / "calamares-session.log", dest / "journal-tail.log"]
    assert (dest / "calamares-session.log").read_text(encoding="utf-8") == "Traceback: boom\n"
    assert (dest / "journal-tail.log").read_text(encoding="utf-8") == "kernel line\n"


def test_collect_reads_roots_calamares_session_log_without_a_shell(tmp_path: Path) -> None:
    """Calamares runs as root via pkexec: the log path is root's cache; argv lists only, no shell."""
    agent = ScriptedAgent({"/usr/bin/tail": _ok("x"), "/usr/bin/journalctl": _ok("y")})
    collect_install_failure_logs(agent, tmp_path)
    assert agent.commands[0][-1] == "/root/.cache/calamares/session.log"
    for argv in agent.commands:
        assert argv[0].startswith("/usr/bin/")
        assert "|" not in argv and "sh" not in Path(argv[0]).name
    assert [name for name, _ in FAILURE_LOGS] == ["calamares-session.log", "journal-tail.log"]


def test_collect_skips_a_missing_log_and_keeps_the_other(tmp_path: Path) -> None:
    """A non-zero exit (log absent) writes nothing for that log but still pulls the journal."""
    agent = ScriptedAgent(
        {
            "/usr/bin/tail": ExecResult(exit_code=1, stdout="", stderr="No such file"),
            "/usr/bin/journalctl": _ok("journal"),
        }
    )
    lines: list[str] = []
    written = collect_install_failure_logs(agent, tmp_path, log=lines.append)
    assert written == [tmp_path / "journal-tail.log"]
    assert not (tmp_path / "calamares-session.log").exists()
    assert any("unavailable" in line for line in lines)


def test_collect_treats_empty_output_as_unavailable(tmp_path: Path) -> None:
    """Exit 0 with no output (edge case: empty log) is not saved as an empty evidence file."""
    agent = ScriptedAgent({"/usr/bin/tail": _ok(""), "/usr/bin/journalctl": _ok("")})
    assert collect_install_failure_logs(agent, tmp_path) == []
    assert list(tmp_path.iterdir()) == []


def test_collect_never_raises_when_the_agent_breaks(tmp_path: Path) -> None:
    """Diagnostics are best effort: agent errors are logged, not raised over the real failure."""
    agent = ScriptedAgent({"/usr/bin/tail": TimeoutError("slow"), "/usr/bin/journalctl": ConnectionError("gone")})
    lines: list[str] = []
    assert collect_install_failure_logs(agent, tmp_path, log=lines.append) == []
    assert len(lines) == 2


def test_pull_failure_logs_survives_an_unreachable_agent(tmp_path: Path) -> None:
    """When the live agent cannot be reached, nothing is written and nothing is raised."""

    def refuse() -> None:
        raise TimeoutError("agent never answered")

    lines: list[str] = []
    assert run_module._pull_failure_logs(SimpleNamespace(connect_live_agent=refuse), tmp_path, lines.append) == []
    assert any("unreachable" in line for line in lines)


def test_pull_failure_logs_uses_the_connected_agent(tmp_path: Path) -> None:
    """A reachable agent's logs land in the firmware directory."""
    agent = ScriptedAgent({"/usr/bin/tail": _ok("trace"), "/usr/bin/journalctl": _ok("journal")})
    vm = SimpleNamespace(connect_live_agent=lambda: agent)
    written = run_module._pull_failure_logs(vm, tmp_path, lambda line: None)
    assert (tmp_path / "calamares-session.log") in written


def _config(tmp_path: Path, **overrides: Any) -> InstallVmConfig:
    base: dict[str, Any] = {
        "disk_path": tmp_path / "disk.qcow2",
        "iso_path": tmp_path / "live.iso",
        "firmware": Firmware.BIOS,
    }
    base.update(overrides)
    return InstallVmConfig(**base)


def test_build_command_agent_channel_adds_the_device_in_phase1(tmp_path: Path) -> None:
    """agent_channel=True adds the guest-agent port without needing attach_guest_agent."""
    joined = " ".join(build_command(_config(tmp_path), tmp_path, attach_guest_agent=False, agent_channel=True))
    assert "-cdrom" in joined
    assert "qga.sock" in joined and "virtserialport" in joined and "virtio-serial-pci" in joined


def test_build_command_agent_channel_defaults_off(tmp_path: Path) -> None:
    """Default stays without the device, so existing callers see no change."""
    joined = " ".join(build_command(_config(tmp_path), tmp_path, attach_guest_agent=False))
    assert "qga.sock" not in joined


def test_connect_live_agent_requires_the_channel(tmp_path: Path) -> None:
    """Without live_agent_channel=True (or before start) there is nothing to connect to."""
    with pytest.raises(RuntimeError, match="channel"):
        InstallVm(_config(tmp_path)).connect_live_agent(timeout_s=1.0)
    with pytest.raises(RuntimeError, match="channel"):
        InstallVm(_config(tmp_path), live_agent_channel=True).connect_live_agent(timeout_s=1.0)

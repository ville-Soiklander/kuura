"""
Behaviour tests of the welcome window launcher (docs/WELCOME_CONTRACT.md, "Tests").

The launcher template is rendered the way the package build renders it, then run with
bash against a throw-away home directory, a fake root for system files and stub
programs (QML runtime, colour scheme tool, config writer, System Settings) that only
record how they were called. No QML runtime, desktop or network is needed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "packages" / "kuura-welcome" / "welcome.sh.in"
DEFAULTS = PROJECT_ROOT / "packages" / "kuura-welcome" / "shortcut-defaults.conf"
NAME = "kuura"


def _find_bash() -> str | None:
    """
    Locate a bash that runs scripts on THIS machine's file system.

    WHY not plain shutil.which("bash"): on Windows that can return the WSL launcher,
    which runs in a different file system. Git for Windows' bash is preferred there.

    Returns:
        Path of a usable bash, or None when there is none.
    """
    candidates = []
    git = shutil.which("git")
    if git:
        candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
    found = shutil.which("bash")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.parent.name.lower() in ("system32", "windowsapps") or not candidate.is_file():
            continue
        return str(candidate)
    return None


BASH = _find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="no native bash available")


def posix(path: Path) -> str:
    """
    Spell a path the way bash expects it (``C:\\x`` becomes ``/c/x`` on Windows).

    Args:
        path: Any path.

    Returns:
        The POSIX spelling.
    """
    text = path.resolve().as_posix()
    if len(text) > 1 and text[1] == ":":
        text = "/" + text[0].lower() + text[2:]
    return text


@dataclass
class Launcher:
    """A rendered launcher plus the fake environment it runs in."""

    script: Path
    home: Path
    config: Path
    root: Path
    stubs: Path
    log: Path

    def run(self, *args: str, output: str = "", status: int = 0) -> subprocess.CompletedProcess:
        """
        Run the launcher.

        Args:
            *args: Command line arguments.
            output: Text the fake QML runtime prints (printf %b escapes allowed).
            status: Exit status of the fake QML runtime.

        Returns:
            The finished process (stdout/stderr captured as text).
        """
        env = {
            "PATH": f"{posix(self.stubs)}:/usr/bin:/bin",
            "HOME": posix(self.home),
            "XDG_CONFIG_HOME": posix(self.config),
            "WELCOME_ROOT": posix(self.root),
            "WELCOME_QML_RUNNER": posix(self.stubs / "fake-runner"),
            "STUB_LOG": posix(self.log),
            "FAKE_RUNNER_OUTPUT": output,
            "FAKE_RUNNER_STATUS": str(status),
        }
        for var in ("SYSTEMROOT", "TEMP", "TMP"):
            if var in os.environ:
                env[var] = os.environ[var]
        return subprocess.run(
            [BASH, posix(self.script), *args], env=env, capture_output=True, text=True, timeout=60
        )

    def calls(self, wait_for: str | None = None) -> list[str]:
        """
        Read the recorded stub calls.

        Args:
            wait_for: When given, wait up to two seconds until a call line starts with
                this text (the detached System Settings stub finishes after the
                launcher has exited).

        Returns:
            One line per call, "<program> <arguments>".
        """
        deadline = time.monotonic() + 2
        while True:
            lines = [x.rstrip() for x in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []
            if wait_for is None or any(line.startswith(wait_for) for line in lines):
                return lines
            if time.monotonic() > deadline:
                return lines
            time.sleep(0.05)

    def runner_args(self) -> dict[str, str]:
        """
        Arguments the fake runtime received, as a name -> value mapping.

        Returns:
            Mapping of "--name=value" pairs; empty when the runtime was not started.
        """
        out: dict[str, str] = {}
        for line in self.calls():
            if line.startswith("runner "):
                for part in line[len("runner ") :].split(" ARG ")[1:]:
                    if part.startswith("--") and "=" in part:
                        key, _, value = part[2:].partition("=")
                        out[key] = value
        return out


def _stub(path: Path, body: str) -> None:
    """Write an executable stub script."""
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


@pytest.fixture
def launcher(tmp_path: Path) -> Launcher:
    """A rendered launcher, an empty fake home/root and recording stubs."""
    text = TEMPLATE.read_text(encoding="utf-8").replace("@NAME_CAP@", "Kuura").replace("@NAME@", NAME)
    script = tmp_path / "bin" / f"{NAME}-welcome"
    script.parent.mkdir()
    script.write_text(text, encoding="utf-8", newline="\n")
    home = tmp_path / "home"
    config = home / ".config"
    root = tmp_path / "root"
    stubs = tmp_path / "stubs"
    for directory in (config, root, stubs):
        directory.mkdir(parents=True)
    log = tmp_path / "calls.log"
    for tool in ("plasma-apply-colorscheme", "kwriteconfig6", "systemsettings"):
        _stub(stubs / tool, f'printf \'%s %s\\n\' "{tool}" "$*" >> "$STUB_LOG"\n')
    # The fake runtime records every argument on its own marker, then prints the
    # scripted output and exits with the scripted status.
    _stub(
        stubs / "fake-runner",
        'line="runner"\nfor a in "$@"; do line="$line ARG $a"; done\n'
        'printf \'%s\\n\' "$line" >> "$STUB_LOG"\n'
        "printf '%b' \"$FAKE_RUNNER_OUTPUT\"\n"
        'exit "$FAKE_RUNNER_STATUS"\n',
    )
    return Launcher(script, home, config, root, stubs, log)


def write_rc(launcher: Launcher, content: str | bytes) -> None:
    """Write the user's welcome settings file."""
    path = launcher.config / f"{NAME}-welcomerc"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="\n")


def started(launcher: Launcher) -> bool:
    """Whether the QML runtime was started."""
    return any(line.startswith("runner ") for line in launcher.calls())


# ---------------------------------------------------------------- --autostart


@pytest.mark.parametrize(
    ("content", "expect_window"),
    [
        ("[General]\nShowAtLogin=false\n", False),
        ("[General]\nShowAtLogin=False\n", False),
        ("[General]\r\nShowAtLogin=false\r\n", False),
        ("[General]\nShowAtLogin = false\n", False),
        ("[Other]\nShowAtLogin=false\n[General]\nShowAtLogin=true\n", True),
        ("[General]\nShowAtLogin=true\n", True),
        ("[General]\nSomethingElse=false\n", True),  # missing key
        ("[General]\nShowAtLogin=false\nShowAtLogin=true\n", True),  # last entry wins
        ("[Other]\nShowAtLogin=false\n", True),  # key in another group
    ],
)
def test_autostart_honours_the_setting(launcher: Launcher, content: str, expect_window: bool) -> None:
    """Only an explicit ShowAtLogin=false in [General] suppresses the autostart window."""
    write_rc(launcher, content)
    result = launcher.run("--autostart")
    assert result.returncode == 0
    assert started(launcher) is expect_window


def test_autostart_without_a_settings_file_shows_the_window(launcher: Launcher) -> None:
    """A first login has no file at all."""
    assert launcher.run("--autostart").returncode == 0
    assert started(launcher)


@pytest.mark.parametrize(
    "content",
    [b"\x00\xff\xfe[[=\x00", b"ShowAtLogin=false\n", b"[General\nShowAtLogin=false\n", b"=\n=false\n[\n", b""],
)
def test_autostart_treats_a_malformed_file_as_show(launcher: Launcher, content: bytes) -> None:
    """Garbage, a key outside any group, an unterminated group or an empty file mean show."""
    write_rc(launcher, content)
    result = launcher.run("--autostart")
    assert result.returncode == 0
    assert started(launcher)


def _mark_live(launcher: Launcher) -> None:
    """Create the marker of a live (archiso) boot inside the fake root."""
    (launcher.root / "run" / "archiso").mkdir(parents=True)


@pytest.mark.parametrize("content", [None, "[General]\nShowAtLogin=true\n", "[General]\nShowAtLogin=false\n"])
def test_autostart_on_the_live_medium_opens_nothing(launcher: Launcher, content: str | None) -> None:
    """On a live boot --autostart exits 0 without a window, whatever the setting says."""
    if content is not None:
        write_rc(launcher, content)
    _mark_live(launcher)
    result = launcher.run("--autostart")
    assert result.returncode == 0
    assert not started(launcher)


def test_autostart_without_the_live_marker_is_unchanged(launcher: Launcher) -> None:
    """An installed system (no marker) still shows the window at autostart."""
    assert launcher.run("--autostart").returncode == 0
    assert started(launcher)


def test_menu_start_on_the_live_medium_opens_the_window(launcher: Launcher) -> None:
    """The application-menu entry (no --autostart) still works in the live session."""
    _mark_live(launcher)
    assert launcher.run().returncode == 0
    assert started(launcher)


def test_menu_start_ignores_the_setting(launcher: Launcher) -> None:
    """Without --autostart the window always opens."""
    write_rc(launcher, "[General]\nShowAtLogin=false\n")
    assert launcher.run().returncode == 0
    assert started(launcher)


def test_current_setting_is_passed_to_the_window(launcher: Launcher) -> None:
    """The checkbox starts in the state of the stored setting."""
    launcher.run()
    assert launcher.runner_args()["show-at-login"] == "true"
    launcher.log.unlink()
    write_rc(launcher, "[General]\nShowAtLogin=false\n")
    launcher.run()
    assert launcher.runner_args()["show-at-login"] == "false"


def test_unknown_arguments_are_rejected(launcher: Launcher) -> None:
    """Anything but --autostart is a usage error and starts nothing."""
    for args in (["--bogus"], ["--autostart", "extra"], ["x"]):
        result = launcher.run(*args)
        assert result.returncode == 2
        assert "Usage" in result.stderr
    assert not started(launcher)


def test_title_uses_the_capitalised_name(launcher: Launcher) -> None:
    """The title is "Welcome to <Name>" with the name capitalised."""
    launcher.run()
    assert launcher.runner_args()["title"] == "Welcome to Kuura"


# ------------------------------------------------------------ mode detection


def write_kdeglobals(launcher: Launcher, scheme: str | None, where: str = "user") -> None:
    """Write a kdeglobals with the given ColorScheme (None writes no ColorScheme key)."""
    body = "[General]\n" + (f"ColorScheme={scheme}\n" if scheme is not None else "") + "[KDE]\nwidgetStyle=Breeze\n"
    if where == "user":
        path = launcher.config / "kdeglobals"
    else:
        path = launcher.root / "etc" / "xdg" / "kdeglobals"
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


@pytest.mark.parametrize(
    ("scheme", "mode"),
    [
        (f"{NAME}-dark", "dark"),
        (f"{NAME}-light", "light"),
        ("BreezeDark", "light"),  # unknown scheme falls back to light
        ("", "light"),
        (f"{NAME}-darker", "light"),  # exact match only
        (None, "light"),  # no key
    ],
)
def test_mode_detection(launcher: Launcher, scheme: str | None, mode: str) -> None:
    """The mode follows the product's own colour scheme ids; anything else is light."""
    write_kdeglobals(launcher, scheme)
    launcher.run()
    assert launcher.runner_args()["mode"] == mode


def test_mode_defaults_to_light_without_any_kdeglobals(launcher: Launcher) -> None:
    """A missing file is the unknown case."""
    launcher.run()
    assert launcher.runner_args()["mode"] == "light"


def test_mode_falls_back_to_the_system_wide_file(launcher: Launcher) -> None:
    """A scheme set system-wide counts when the user's file does not name one."""
    write_kdeglobals(launcher, None)
    write_kdeglobals(launcher, f"{NAME}-dark", where="system")
    launcher.run()
    assert launcher.runner_args()["mode"] == "dark"


def test_users_scheme_beats_the_system_wide_one(launcher: Launcher) -> None:
    """The user's choice wins over the system default."""
    write_kdeglobals(launcher, f"{NAME}-light")
    write_kdeglobals(launcher, f"{NAME}-dark", where="system")
    launcher.run()
    assert launcher.runner_args()["mode"] == "light"


# ------------------------------------------------------------------ shortcuts

KRUNNER_DESKTOP = (
    "[Desktop Entry]\nExec=/usr/bin/krunner\nX-KDE-Shortcuts=Alt+Space,Alt+F2,Search\n"
    "[Desktop Action RunClipboard]\nX-KDE-Shortcuts=Alt+Shift+F2\n"
)


def install_upstream_files(launcher: Launcher) -> None:
    """Place the files the launcher reads from the installed system into the fake root."""
    desktop = launcher.root / "usr" / "share" / "kglobalaccel" / "org.kde.krunner.desktop"
    desktop.parent.mkdir(parents=True)
    desktop.write_text(KRUNNER_DESKTOP, encoding="utf-8", newline="\n")
    data = launcher.root / "usr" / "share" / f"{NAME}-welcome"
    data.mkdir(parents=True)
    shutil.copyfile(DEFAULTS, data / "shortcut-defaults.conf")


def test_shortcuts_come_from_the_upstream_defaults(launcher: Launcher) -> None:
    """Search is KRunner's declared default, overview the recorded upstream default."""
    install_upstream_files(launcher)
    launcher.run()
    args = launcher.runner_args()
    assert args["search"] == "Alt+Space"
    assert args["overview"] == "Meta+W"


def test_shortcuts_prefer_the_users_configuration(launcher: Launcher) -> None:
    """A user's own binding (active<TAB>default,default,label) is shown, not the default."""
    install_upstream_files(launcher)
    (launcher.config / "kglobalshortcutsrc").write_text(
        "[kwin]\nOverview=Meta+Tab\tMeta+Q,Meta+W,Toggle Overview\n"
        "[services][org.kde.krunner.desktop]\n_launch=Meta+Space,Alt+Space,Search\n",
        encoding="utf-8",
        newline="\n",
    )
    launcher.run()
    args = launcher.runner_args()
    assert args["overview"] == "Meta+Tab"
    assert args["search"] == "Meta+Space"


def test_shortcuts_use_the_products_shipped_file(launcher: Launcher) -> None:
    """The kglobalshortcutsrc shipped in /etc/skel counts before the upstream default."""
    install_upstream_files(launcher)
    skel = launcher.root / "etc" / "skel" / ".config"
    skel.mkdir(parents=True)
    (skel / "kglobalshortcutsrc").write_text("[kwin]\nOverview=Meta+O,Meta+O,x\n", encoding="utf-8", newline="\n")
    launcher.run()
    assert launcher.runner_args()["overview"] == "Meta+O"


def test_unbound_shortcut_is_not_replaced_by_the_default(launcher: Launcher) -> None:
    """A deliberately unbound shortcut ("none") shows as empty, not as the default."""
    install_upstream_files(launcher)
    (launcher.config / "kglobalshortcutsrc").write_text(
        "[kwin]\nOverview=none,Meta+W,Toggle Overview\n", encoding="utf-8", newline="\n"
    )
    launcher.run()
    assert launcher.runner_args()["overview"] == ""


def test_missing_sources_give_empty_shortcuts(launcher: Launcher) -> None:
    """Nothing readable means the window shows "Not set"; the launcher still starts it."""
    result = launcher.run()
    assert result.returncode == 0
    args = launcher.runner_args()
    assert args["search"] == ""
    assert args["overview"] == ""


def test_hostile_shortcut_values_are_reduced_to_safe_characters(launcher: Launcher) -> None:
    """Command-line metacharacters in a config value never reach the window or a shell."""
    install_upstream_files(launcher)
    (launcher.config / "kglobalshortcutsrc").write_text(
        "[kwin]\nOverview=Meta+W;$(touch pwned)`id`\"'\\|&<>,x,y\n", encoding="utf-8", newline="\n"
    )
    launcher.run()
    value = launcher.runner_args()["overview"]
    assert not set(value) & set(";$`\"'\\|&<>()")
    assert not (launcher.home / "pwned").exists()


# -------------------------------------------------------------------- actions


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("WELCOME_ACTION scheme dark", f"plasma-apply-colorscheme {NAME}-dark"),
        ("WELCOME_ACTION scheme light", f"plasma-apply-colorscheme {NAME}-light"),
        (
            "WELCOME_ACTION show-at-login false",
            f"kwriteconfig6 --file {NAME}-welcomerc --group General --key ShowAtLogin false",
        ),
        (
            "WELCOME_ACTION show-at-login true",
            f"kwriteconfig6 --file {NAME}-welcomerc --group General --key ShowAtLogin true",
        ),
        ("qml: WELCOME_ACTION scheme dark", f"plasma-apply-colorscheme {NAME}-dark"),
        ("WELCOME_ACTION settings", "systemsettings"),
    ],
)
def test_actions_run_the_matching_command(launcher: Launcher, line: str, expected: str) -> None:
    """Each reported action performs exactly its command."""
    result = launcher.run(output=line + "\\n")
    assert result.returncode == 0
    program = expected.split()[0]
    calls = [c for c in launcher.calls(wait_for=program) if not c.startswith("runner ")]
    assert calls == [expected]


def test_several_actions_are_all_performed_in_order(launcher: Launcher) -> None:
    """A command must not swallow the lines that follow it."""
    launcher.run(
        output="WELCOME_ACTION scheme dark\\nWELCOME_ACTION show-at-login false\\nWELCOME_ACTION scheme light\\n"
    )
    calls = [c for c in launcher.calls() if not c.startswith("runner ")]
    assert [c.split()[0] for c in calls] == ["plasma-apply-colorscheme", "kwriteconfig6", "plasma-apply-colorscheme"]


@pytest.mark.parametrize(
    "line",
    [
        "WELCOME_ACTION scheme ; touch pwned",
        "WELCOME_ACTION scheme darkest",
        "WELCOME_ACTION show-at-login maybe",
        "WELCOME_ACTION rm -rf x",
        "WELCOME_ACTION",
        "WELCOME_ACTION settings extra",
        "something else entirely",
    ],
)
def test_unknown_actions_are_ignored(launcher: Launcher, line: str) -> None:
    """Only the exact verbs are honoured; nothing else runs."""
    result = launcher.run(output=line + "\\n")
    assert result.returncode == 0
    assert [c for c in launcher.calls() if not c.startswith("runner ")] == []
    assert not (launcher.home / "pwned").exists()


def test_other_output_is_passed_to_stderr(launcher: Launcher) -> None:
    """Qt warnings stay visible to whoever started the launcher."""
    result = launcher.run(output="a warning from Qt\\n")
    assert "a warning from Qt" in result.stderr


def test_runner_exit_status_is_the_launchers(launcher: Launcher) -> None:
    """A failing window is a failing launcher."""
    assert launcher.run(status=0).returncode == 0
    assert launcher.run(status=3).returncode == 3


def test_missing_runner_fails_cleanly(launcher: Launcher) -> None:
    """A runtime that cannot start gives a non-zero status."""
    (launcher.stubs / "fake-runner").unlink()
    assert launcher.run().returncode != 0


# ------------------------------------------------------------- application id


def test_launcher_passes_the_application_domain(launcher: Launcher) -> None:
    """
    The window gets the domain that makes Qt announce this app's own application id.

    WHY: Qt Wayland builds the id from the reversed organisation domain plus the
    runtime's executable name ("qml"); the QML sets the domain from this argument.
    """
    launcher.run()
    assert launcher.runner_args()["app-domain"] == f"{NAME}-welcome"

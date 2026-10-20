"""
Tests of the welcome window package (docs/WELCOME_CONTRACT.md, "Package", "Look",
"Autostart", "Test harness" and "Tests").

The PKGBUILD's own build() and package() functions are run with bash against a copy of
the repository, so the file list checked here is the one the real package gets.
"""

from __future__ import annotations

import configparser
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tests.test_welcome_launcher import BASH, posix
from tools import check_forbidden_terms

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = PROJECT_ROOT / "packages" / "kuura-welcome"
NAME = "kuura"
QML_FILE = PACKAGE_DIR / "qml" / "Welcome.qml"
GUEST_SKEL = PROJECT_ROOT / "harness" / "vm" / "guest" / "skel" / ".config"


def _ini(path: Path) -> configparser.ConfigParser:
    """Parse a KConfig-style file (case-sensitive keys, '#' comments)."""
    parser = configparser.ConfigParser(interpolation=None, comment_prefixes=("#",), strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


# ----------------------------------------------------------- built package layout


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Run build() and package() of the real PKGBUILD in a copy of the repository.

    Returns:
        The package root directory ($pkgdir).
    """
    if BASH is None:
        pytest.skip("no native bash available")
    work = tmp_path_factory.mktemp("welcome-build")
    shutil.copytree(PROJECT_ROOT / "design", work / "design", ignore=shutil.ignore_patterns("__pycache__", "tests"))
    package = work / "packages" / "kuura-welcome"
    shutil.copytree(PACKAGE_DIR, package)
    # build() calls python3; on machines where that name is not the project's
    # interpreter a shim points it at the interpreter running this test.
    shim = work / "shim"
    shim.mkdir()
    (shim / "python3").write_text(f'#!/bin/sh\nexec "{posix(Path(sys.executable))}" "$@"\n', newline="\n")
    (shim / "python3").chmod(0o755)
    srcdir = package / "src"
    srcdir.mkdir()
    pkgdir = work / "pkg"
    script = (
        "set -eu\n"
        f"export PATH='{posix(shim)}':\"$PATH\" DISTRO_NAME={NAME}\n"
        f"srcdir='{posix(srcdir)}'; pkgdir='{posix(pkgdir)}'\n"
        f". '{posix(package / 'PKGBUILD')}'\n"
        "build\npackage\n"
    )
    result = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]
    return pkgdir


def _files(root: Path) -> set[str]:
    """All regular files below root as POSIX paths relative to it."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_files_land_at_the_contracted_paths(built: Path) -> None:
    """Launcher, QML tree, autostart entry and menu entry are where the contract says."""
    assert _files(built) == {
        f"usr/bin/{NAME}-welcome",
        f"usr/share/{NAME}-welcome/Welcome.qml",
        f"usr/share/{NAME}-welcome/shortcut-defaults.conf",
        f"usr/share/{NAME}-welcome/tokens/light/Tokens.qml",
        f"usr/share/{NAME}-welcome/tokens/light/qmldir",
        f"usr/share/{NAME}-welcome/tokens/dark/Tokens.qml",
        f"usr/share/{NAME}-welcome/tokens/dark/qmldir",
        f"etc/xdg/autostart/{NAME}-welcome.desktop",
        f"usr/share/applications/{NAME}-welcome.desktop",
    }


def test_no_template_placeholder_is_left(built: Path) -> None:
    """Every @NAME@ / @NAME_CAP@ was substituted."""
    for rel in _files(built):
        assert "@NAME" not in (built / rel).read_text(encoding="utf-8"), rel


def test_launcher_is_a_posix_sh_script_for_this_distribution(built: Path) -> None:
    """The launcher starts with a POSIX sh shebang and carries the distribution name."""
    text = (built / "usr" / "bin" / f"{NAME}-welcome").read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert f"NAME='{NAME}'" in text
    assert "NAME_CAP='Kuura'" in text


def test_autostart_entry_passes_autostart(built: Path) -> None:
    """The autostart entry runs the launcher with --autostart."""
    entry = _ini(built / "etc" / "xdg" / "autostart" / f"{NAME}-welcome.desktop")["Desktop Entry"]
    assert entry["Exec"] == f"{NAME}-welcome --autostart"
    assert entry["Type"] == "Application"


def test_menu_entry_does_not_pass_autostart(built: Path) -> None:
    """The application menu entry always opens the window."""
    entry = _ini(built / "usr" / "share" / "applications" / f"{NAME}-welcome.desktop")["Desktop Entry"]
    assert entry["Exec"] == f"{NAME}-welcome"
    assert entry.get("NoDisplay", "false") == "false"


def test_menu_entry_matches_the_announced_application_id(built: Path) -> None:
    """
    StartupWMClass equals the Wayland application id the window announces.

    Qt derives that id as the reversed organisation domain plus ".qml" (the runtime's
    executable name); the launcher hands the domain to the QML, a dot-free value, so
    the id is the domain followed by ".qml". The shelf matches the window to the menu
    entry through this key and shows the entry's icon.
    """
    launcher = (built / "usr" / "bin" / f"{NAME}-welcome").read_text(encoding="utf-8")
    domain = re.search(r'"--app-domain=([^"]+)"', launcher)
    assert domain is not None
    domain_value = domain.group(1).replace("$NAME", NAME)
    assert "." not in domain_value
    entry = _ini(built / "usr" / "share" / "applications" / f"{NAME}-welcome.desktop")["Desktop Entry"]
    assert entry["StartupWMClass"] == f"{domain_value}.qml"


def test_menu_entry_icon_is_a_theme_icon_name(built: Path) -> None:
    """The menu entry names a theme icon (no path, no extension)."""
    entry = _ini(built / "usr" / "share" / "applications" / f"{NAME}-welcome.desktop")["Desktop Entry"]
    assert entry["Icon"] and "/" not in entry["Icon"] and not entry["Icon"].endswith((".svg", ".png"))


def test_qml_applies_the_application_domain_before_showing(built: Path) -> None:
    """The window starts hidden and shows itself only after setting the domain."""
    qml = (PROJECT_ROOT / "packages" / "kuura-welcome" / "qml" / "Welcome.qml").read_text(encoding="utf-8")
    assert 'arg("app-domain"' in qml
    assert re.search(r"visible: false", qml)
    assert qml.index("Qt.application.domain") < qml.index("visible = true")


def test_token_singletons_are_generated_for_both_modes(built: Path) -> None:
    """Each mode directory holds the generated singleton of that mode and the qmldir."""
    share = built / "usr" / "share" / f"{NAME}-welcome" / "tokens"
    for mode in ("light", "dark"):
        text = (share / mode / "Tokens.qml").read_text(encoding="utf-8")
        assert 'readonly property string mode: "%s"' % mode in text
        assert "pragma Singleton" in text
        assert (share / mode / "qmldir").read_text(encoding="utf-8").strip() == "singleton Tokens 1.0 Tokens.qml"
    light = (share / "light" / "Tokens.qml").read_text(encoding="utf-8")
    dark = (share / "dark" / "Tokens.qml").read_text(encoding="utf-8")
    assert re.search(r"colorWindow: \"#", light) and light != dark


def test_package_metadata() -> None:
    """Name from DISTRO_NAME, arch any, GPL-3.0-or-later, no compiled code, new deps none."""
    text = (PACKAGE_DIR / "PKGBUILD").read_text(encoding="utf-8")
    assert 'pkgname="${DISTRO_NAME:?DISTRO_NAME must be set}-welcome"' in text
    assert "arch=('any')" in text
    assert "license=('GPL-3.0-or-later')" in text
    depends = re.search(r"^depends=\((.*?)\)", text, re.M | re.S)
    assert depends is not None
    deps = set(re.findall(r"'([^']+)'", depends.group(1)))
    assert "qt6-declarative" in deps
    # Only packages the desktop already pulls in; none of the forbidden-licence kind.
    assert deps <= {"qt6-declarative", "qt6-wayland", "kconfig", "plasma-workspace", "systemsettings"}


def test_pulled_in_by_the_metapackage() -> None:
    """kuura-desktop depends on the welcome package."""
    text = (PROJECT_ROOT / "packages" / "kuura-desktop" / "PKGBUILD").read_text(encoding="utf-8")
    assert '"${DISTRO_NAME}-welcome"' in text


def test_launcher_runs_the_runtime_the_pinned_package_ships() -> None:
    """The default runner is qml6, which qt6-declarative installs as /usr/bin/qml6."""
    text = (PACKAGE_DIR / "welcome.sh.in").read_text(encoding="utf-8")
    assert 'RUNNER="${WELCOME_QML_RUNNER:-qml6}"' in text


# --------------------------------------------------------- shortcuts and harness


def test_recorded_overview_default_matches_what_the_harness_presses() -> None:
    """The fallback for Overview equals the key the screenshot harness uses to open it."""
    recorded = _ini(PACKAGE_DIR / "shortcut-defaults.conf")["kwin"]["Overview"]
    states = tomllib.loads((PROJECT_ROOT / "harness" / "states.toml").read_text(encoding="utf-8"))
    overview = next(s for s in states["state"] if s["name"] == "overview")
    keys = [step["key"] for step in overview["steps"] if "key" in step]
    assert keys == [recorded.lower()]


def test_products_shipped_shortcut_file_does_not_contradict_the_fallbacks() -> None:
    """If the product ever binds Overview itself, the launcher reads that (it is looked up first)."""
    shipped = _ini(PROJECT_ROOT / "packages" / "kuura-shell" / "skel" / ".config" / "kglobalshortcutsrc")
    if shipped.has_option("kwin", "Overview"):
        assert shipped["kwin"]["Overview"]  # picked up by lookup_binding before the fallback


def test_state_welcome_window_starts_the_launcher_without_autostart() -> None:
    """The harness state runs the launcher, never with --autostart, in both modes."""
    states = tomllib.loads((PROJECT_ROOT / "harness" / "states.toml").read_text(encoding="utf-8"))
    state = next(s for s in states["state"] if s["name"] == "welcome-window")
    runs = [step["run"] for step in state["steps"] if "run" in step]
    assert len(runs) == 1
    assert "welcome" in " ".join(runs[0])
    assert "--autostart" not in " ".join(runs[0])
    assert "modes" not in state  # no restriction: runs in every mode


def test_reset_step_stops_the_welcome_window() -> None:
    """Without this the window would stay open in every later state."""
    states = tomllib.loads((PROJECT_ROOT / "harness" / "states.toml").read_text(encoding="utf-8"))
    reset = " ".join(" ".join(step["run"]) for step in states["settings"]["reset"] if "run" in step)
    assert "[-]welcome" in reset


def test_guest_skel_switches_the_window_off_for_every_state() -> None:
    """The test-only settings file hides the autostart window; the product ships none."""
    rc = _ini(GUEST_SKEL / f"{NAME}-welcomerc")
    assert rc["General"]["ShowAtLogin"] == "false"
    for path in (PROJECT_ROOT / "packages").rglob("*welcomerc*"):
        pytest.fail(f"a package ships a welcome settings file: {path}")


def test_window_rule_fixes_the_welcome_window_position() -> None:
    """kwinrulesrc counts and lists the new rule and matches the window by title."""
    rules = _ini(GUEST_SKEL / "kwinrulesrc")
    listed = rules["General"]["rules"].split(",")
    assert int(rules["General"]["count"]) == len(listed)
    assert set(listed) == set(rules.sections()) - {"General"}
    welcome = [rules[s] for s in listed if rules[s].get("title")]
    assert len(welcome) == 1
    rule = welcome[0]
    assert rule["title"] == "Welcome to"
    assert rule["titlematch"] == "2"
    assert rule["positionrule"] == "2"


# ------------------------------------------------------------------- QML source

_COLOUR_LITERALS = re.compile(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(|\bQt\.(rgba|hsla|darker|lighter|tint)\b")
_NAMED_COLOUR = re.compile(r"\bcolor\s*:\s*\"")


def _code_lines(text: str) -> list[tuple[int, str]]:
    """Source lines without comments (block and line) and without string contents."""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    lines = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = re.sub(r"//.*$", "", line)
        line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
        lines.append((number, line))
    return lines


def test_qml_has_no_literal_colours() -> None:
    """Every colour comes from the token singleton."""
    for number, line in _code_lines(QML_FILE.read_text(encoding="utf-8")):
        assert not _COLOUR_LITERALS.search(line), f"line {number}: {line.strip()}"
    raw = QML_FILE.read_text(encoding="utf-8")
    assert not _NAMED_COLOUR.search(raw)
    assert not re.search(r'color\s*:\s*"?(white|black|red|green|blue|gray|grey|transparent)\b', raw)


def test_qml_has_no_literal_sizes() -> None:
    """Numbers greater than one appear only as multiples of a token (layout structure)."""
    for number, line in _code_lines(QML_FILE.read_text(encoding="utf-8")):
        # "/ 2" is the centring idiom (layout structure), not a size.
        line = re.sub(r"/\s*2(?![\w.])", "", line)
        for match in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])", line):
            if float(match.group(1)) <= 1:
                continue
            assert "tk." in line, f"line {number}: literal {match.group(1)} outside a token expression: {line.strip()}"


def test_qml_takes_no_fonts_or_durations_from_literals() -> None:
    """Font family names and animation durations are token reads, not strings or numbers."""
    for number, line in _code_lines(QML_FILE.read_text(encoding="utf-8")):
        if "font.family" in line:
            assert "tk.typeFamily" in line, f"line {number}"
        if "duration" in line:
            assert "tk.motionDuration" in line, f"line {number}"


def test_qml_reads_both_token_singletons() -> None:
    """The window imports the light and dark singletons so it can follow a mode change."""
    text = QML_FILE.read_text(encoding="utf-8")
    assert 'import "tokens/light" as Light' in text
    assert 'import "tokens/dark" as Dark' in text


def _qmllint() -> str | None:
    """Find the Qt linter (name differs between distributions)."""
    for name in ("qmllint6", "qmllint"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (Path("/usr/lib/qt6/bin/qmllint"),):
        if candidate.is_file():
            return str(candidate)
    return None


@pytest.mark.skipif(_qmllint() is None, reason="Qt's qmllint is not available (checked in the build image)")
def test_qml_passes_qmllint(built: Path) -> None:
    """The window lints clean against the generated singletons (warnings are failures)."""
    share = built / "usr" / "share" / f"{NAME}-welcome"
    result = subprocess.run(
        [_qmllint(), "--max-warnings", "0", str(share / "Welcome.qml")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ------------------------------------------------------------- forbidden terms


def test_package_files_contain_no_forbidden_names() -> None:
    """The forbidden-terms check passes on every file of the package and its harness files."""
    paths = [p for p in PACKAGE_DIR.rglob("*") if p.is_file()]
    paths += [GUEST_SKEL / f"{NAME}-welcomerc", GUEST_SKEL / "kwinrulesrc"]
    assert paths
    assert check_forbidden_terms.main([str(p) for p in paths]) == 0

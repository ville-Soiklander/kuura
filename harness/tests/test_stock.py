"""
Tests for harness.shots.stock: the revert plan, its execution, the read-back checks and
the run around them.

No VM is involved. ``FakeGuest`` answers the desktop-user commands the tool runs
(kwriteconfig6, kreadconfig6, gdbus, plasma-apply-lookandfeel) from small tables, and the
run tests reuse the fake VM/runner pattern of test_capture.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from harness.shots.capture import EnvironmentProblem
from harness.shots.guest import ExecResult, GuestUser
from harness.shots.runner import SettleResult, StateResult
from harness.shots.states import load_states, parse_states
from harness.shots.stock import (
    COMPARABLE_STATES,
    DEFAULT_STATES,
    EXCLUDED_STATES,
    STOCK_DECORATION,
    STOCK_LOOK_AND_FEEL,
    StockEvidence,
    StockOptions,
    StockRevertError,
    _gdbus_text,
    build_options,
    build_revert_plan,
    check_stock_evidence,
    frost_effect_id,
    parse_decoration,
    read_stock_evidence,
    revert_to_stock,
    run_stock,
    select_states,
)
from harness.shots.vm import VmBootError, VmConfig

NAME = "kuura"
REAL_STATES = Path(__file__).resolve().parents[1] / "states.toml"

SUPPORT_INFO_STOCK = "KWin Support Information:\n...\nDecoration\n==========\nPlugin: org.kde.breeze\nTheme: \n"
SUPPORT_INFO_PRODUCT = "Decoration\n==========\nPlugin: kuura.decoration\n"

STOCK_LAYOUT = {
    "panels": [
        {
            "location": "bottom",
            "height": 44,
            "widgets": [
                "org.kde.plasma.kickoff",
                "org.kde.plasma.pager",
                "org.kde.plasma.icontasks",
                "org.kde.plasma.marginsseparator",
                "org.kde.plasma.systemtray",
                "org.kde.plasma.digitalclock",
                "org.kde.plasma.showdesktop",
            ],
        }
    ],
    "wallpaper": "org.kde.image",
    "image": "",
}

PRODUCT_LAYOUT = {
    "panels": [
        {"location": "top", "height": 26, "widgets": ["org.kde.plasma.kickoff", "org.kde.plasma.appmenu", "org.kde.plasma.systemtray", "org.kde.plasma.digitalclock"]},
        {"location": "bottom", "height": 52, "widgets": ["org.kde.plasma.icontasks"]},
    ],
    "wallpaper": "org.kde.image",
    "image": "",
}


def gvariant_string(text: str) -> str:
    """
    Print a string the way gdbus prints a single-string reply.

    Args:
        text: The string.

    Returns:
        ``('...',)`` with gdbus's escapes.
    """
    escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    return f"('{escaped}',)\n"


class FakeGuest:
    """
    A guest agent that answers the tool's commands from tables.

    Attributes:
        user: The desktop user.
        calls: Every ``run_as_user`` argument list in order.
        config: ``(file, groups..., key)`` to value, answered by kreadconfig6.
        fail_program: Programs (first argument) that exit with 1.
        fail_contains: Commands containing this word exit with 1.
        raise_on: Commands containing this word raise TimeoutError.
        support: KWin support information text.
        loaded: Effect ids KWin reports loaded.
        layout: The shell's layout report (dict) or raw text.
        installed: Whether ``pacman -Q <name>-desktop`` succeeds.
    """

    def __init__(self) -> None:
        self.user = GuestUser()
        self.calls: list[list[str]] = []
        self.config: dict[tuple[str, ...], str] = {
            ("kdeglobals", "KDE", "LookAndFeelPackage"): STOCK_LOOK_AND_FEEL,
            ("kdeglobals", "General", "ColorScheme"): "BreezeLight",
            ("kdeglobals", "Icons", "Theme"): "breeze",
            ("kdeglobals", "KDE", "widgetStyle"): "Breeze",
            ("kwinrc", "org.kde.kdecoration2", "library"): STOCK_DECORATION,
        }
        self.fail_program: set[str] = set()
        self.fail_contains = ""
        self.raise_on = ""
        self.support = SUPPORT_INFO_STOCK
        self.loaded: set[str] = {"blur"}
        self.layout: Any = STOCK_LAYOUT
        self.installed = True

    def run_as_user(self, argv: list[str], wait_exit: bool = False, timeout: float = 30.0) -> ExecResult | None:
        """
        Answer one desktop-user command.

        Args:
            argv: The command.
            wait_exit: Must be True (the tool always waits).
            timeout: Ignored.

        Returns:
            The fake result.

        Raises:
            TimeoutError: for a command containing ``raise_on``.
        """
        assert wait_exit
        self.calls.append(list(argv))
        joined = " ".join(argv)
        if self.raise_on and self.raise_on in joined:
            raise TimeoutError("guest agent did not answer")
        if argv[0] in self.fail_program or (self.fail_contains and self.fail_contains in joined):
            return ExecResult(1, "", "error")
        if argv[0] == "kreadconfig6":
            groups = [argv[i + 1] for i, item in enumerate(argv) if item == "--group"]
            key = argv[argv.index("--key") + 1]
            file = argv[argv.index("--file") + 1]
            return ExecResult(0, self.config.get((file, *groups, key), "") + "\n", "")
        if argv[0] == "gdbus":
            method = argv[argv.index("--method") + 1]
            if method.endswith("supportInformation"):
                return ExecResult(0, gvariant_string(self.support), "")
            if method.endswith("isEffectLoaded"):
                return ExecResult(0, "(true,)\n" if argv[-1] in self.loaded else "(false,)\n", "")
            if method.endswith("evaluateScript"):
                text = self.layout if isinstance(self.layout, str) else json.dumps(self.layout)
                return ExecResult(0, gvariant_string(text + "\n"), "")
            return ExecResult(0, "()\n", "")
        return ExecResult(0, "", "")

    def exec(self, argv: list[str], timeout: float = 20.0) -> ExecResult:
        """
        Answer a root command (only the package query is expected).

        Args:
            argv: The command.
            timeout: Ignored.

        Returns:
            Exit 0 when the product is installed, else 1.
        """
        return ExecResult(0 if self.installed else 1, "", "")


# --- the plan --------------------------------------------------------------------------


def test_plan_reverts_every_product_setting_in_a_safe_order() -> None:
    plan = build_revert_plan(NAME, "/home/desktop")
    joined = [" ".join(command.argv) for command in plan]
    descriptions = [command.description for command in plan]

    def index(fragment: str) -> int:
        return next(i for i, text in enumerate(joined) if fragment in text)

    lookandfeel = index("plasma-apply-lookandfeel")
    assert plan[lookandfeel].argv == ("plasma-apply-lookandfeel", "--apply", STOCK_LOOK_AND_FEEL, "--resetLayout")
    # Config keys are deleted BEFORE the look-and-feel writes its own values.
    assert index("--key library --delete") < lookandfeel
    assert index("ButtonsOnLeft --delete") < lookandfeel
    # Stale panel view settings go before the layout reset.
    assert index("plasmashellrc --group PlasmaViews --group Panel 2 --group Defaults --key thickness --delete") < lookandfeel
    # The crossfade is unloaded right before the switch, KWin reloads afterwards.
    assert index("unloadEffect blendchanges") == lookandfeel - 1
    assert index("org.kde.KWin.reconfigure") > lookandfeel
    # The glass effect is switched off explicitly AND unloaded after the reload.
    assert "kwriteconfig6 --file kwinrc --group Plugins --key kuura_frostEnabled false" in joined
    assert index("unloadEffect kuura_frost") > index("org.kde.KWin.reconfigure")
    assert any("FreeFloating" in d for d in descriptions)
    assert any("/home/desktop/.config/gtk-4.0/settings.ini" in text for text in joined)
    # Every command is a plain argument list: no shell anywhere.
    assert all(command.argv[0] not in ("sh", "bash") for command in plan)


@pytest.mark.parametrize(("name", "home"), [("Kuura", "/home/desktop"), ("a b", "/home/desktop"), ("", "/home/desktop"), (NAME, "home/desktop"), (NAME, "/home/\x00x")])
def test_plan_rejects_bad_names_and_homes(name: str, home: str) -> None:
    with pytest.raises(ValueError):
        build_revert_plan(name, home)


def test_frost_effect_id_follows_the_plugin_file_name() -> None:
    assert frost_effect_id("kuura") == "kuura_frost"


# --- running the plan ------------------------------------------------------------------------


def test_revert_runs_every_command_in_order() -> None:
    guest = FakeGuest()
    plan = build_revert_plan(NAME, guest.user.home)
    lines: list[str] = []
    revert_to_stock(guest, plan, lines.append)
    assert guest.calls == [list(command.argv) for command in plan]
    assert len(lines) == len(plan)


def test_a_failing_revert_command_stops_with_a_clear_error() -> None:
    guest = FakeGuest()
    guest.fail_program = {"plasma-apply-lookandfeel"}
    plan = build_revert_plan(NAME, guest.user.home)
    with pytest.raises(StockRevertError, match=r"revert step failed: apply the Breeze look-and-feel .*\(exit 1\)"):
        revert_to_stock(guest, plan)
    # Nothing after the failing step ran.
    assert guest.calls[-1][0] == "plasma-apply-lookandfeel"


def test_a_revert_command_that_times_out_is_a_revert_error() -> None:
    guest = FakeGuest()
    guest.raise_on = "krunnerrc"
    with pytest.raises(StockRevertError, match="FreeFloating"):
        revert_to_stock(guest, build_revert_plan(NAME, guest.user.home))


def test_a_revert_command_without_a_result_is_a_revert_error() -> None:
    class Silent(FakeGuest):
        def run_as_user(self, argv: list[str], wait_exit: bool = False, timeout: float = 30.0) -> ExecResult | None:
            return None

    with pytest.raises(StockRevertError, match="no result"):
        revert_to_stock(Silent(), build_revert_plan(NAME, "/home/desktop"))


# --- parsing helpers -----------------------------------------------------------------------


def test_parse_decoration_reads_the_loaded_plugin() -> None:
    assert parse_decoration(SUPPORT_INFO_STOCK) == "org.kde.breeze"
    assert parse_decoration(SUPPORT_INFO_PRODUCT) == "kuura.decoration"


def test_parse_decoration_without_the_section_is_empty() -> None:
    assert parse_decoration("Plugin: something\nno decoration header before") == ""
    assert parse_decoration("") == ""


def test_gdbus_text_undoes_the_escapes() -> None:
    assert _gdbus_text(gvariant_string("a 'b'\nc\\d")) == "a 'b'\nc\\d"
    assert _gdbus_text("('',)") == ""


@pytest.mark.parametrize("reply", ["", "()", "(true,)", "'text'", "(42,)"])
def test_gdbus_text_rejects_non_string_replies(reply: str) -> None:
    with pytest.raises(StockRevertError):
        _gdbus_text(reply)


# --- read-back and its checks ---------------------------------------------------------------


def test_read_back_of_a_stock_session_passes_the_checks() -> None:
    evidence = read_stock_evidence(FakeGuest(), NAME)
    assert evidence.decoration == STOCK_DECORATION
    assert evidence.effect_loaded == {"kuura_frost": False, "blur": True}
    assert evidence.panels[0]["location"] == "bottom"
    assert check_stock_evidence(evidence, NAME) == []


def test_read_back_of_the_product_session_fails_on_every_product_item() -> None:
    guest = FakeGuest()
    guest.config[("kdeglobals", "KDE", "LookAndFeelPackage")] = "kuura"
    guest.config[("kwinrc", "org.kde.kdecoration2", "library")] = "kuura.decoration"
    guest.config[("kwinrc", "org.kde.kdecoration2", "ButtonsOnLeft")] = "XIA"
    guest.config[("krunnerrc", "General", "FreeFloating")] = "true"
    guest.support = SUPPORT_INFO_PRODUCT
    guest.loaded.add("kuura_frost")
    guest.layout = PRODUCT_LAYOUT
    problems = "\n".join(check_stock_evidence(read_stock_evidence(guest, NAME), NAME))
    for fragment in ("LookAndFeelPackage", "library", "ButtonsOnLeft", "FreeFloating", "decoration 'kuura.decoration'", "kuura_frost loaded", "2 panels", "at 'top'", "global menu", "mentions 'kuura'"):
        assert fragment in problems


def test_unset_values_count_as_plasma_defaults() -> None:
    evidence = StockEvidence(
        config={"kdeglobals/KDE/LookAndFeelPackage": STOCK_LOOK_AND_FEEL},
        decoration=STOCK_DECORATION,
        effect_loaded={"kuura_frost": False},
        panels=list(STOCK_LAYOUT["panels"]),
        wallpaper="org.kde.image",
    )
    assert check_stock_evidence(evidence, NAME) == []


def test_a_missing_effect_answer_counts_as_loaded() -> None:
    evidence = read_stock_evidence(FakeGuest(), NAME)
    evidence.effect_loaded = {}
    assert any("kuura_frost" in problem for problem in check_stock_evidence(evidence, NAME))


@pytest.mark.parametrize(
    ("image", "ok"),
    [
        ("", True),
        ("file:///usr/share/wallpapers/Next/contents/images/5120x2880.png", True),
        ("/usr/share/wallpapers/Next/", True),
        ("file:///usr/share/backgrounds/kuura/kuura-radial-glow-light.png", False),
        ("file:///home/desktop/picture.png", False),
    ],
)
def test_only_the_default_wallpaper_is_stock(image: str, ok: bool) -> None:
    evidence = read_stock_evidence(FakeGuest(), NAME)
    evidence.image = image
    assert (check_stock_evidence(evidence, NAME) == []) is ok


def test_a_panel_missing_stock_applets_or_without_panels_fails() -> None:
    evidence = read_stock_evidence(FakeGuest(), NAME)
    evidence.panels = [{"location": "bottom", "height": 44, "widgets": ["org.kde.plasma.kickoff"]}]
    assert any("lacks stock applets" in p for p in check_stock_evidence(evidence, NAME))
    evidence.panels = []
    assert any("0 panels" in p for p in check_stock_evidence(evidence, NAME))


def test_an_unreadable_layout_report_is_a_revert_error() -> None:
    guest = FakeGuest()
    guest.layout = "ReferenceError: panels is not defined"
    with pytest.raises(StockRevertError, match="layout report"):
        read_stock_evidence(guest, NAME)


def test_a_failing_query_is_a_revert_error() -> None:
    guest = FakeGuest()
    guest.fail_program = {"kreadconfig6"}
    with pytest.raises(StockRevertError, match="read back"):
        read_stock_evidence(guest, NAME)


# --- state selection -----------------------------------------------------------------------------


def test_default_selection_is_the_four_readme_states_in_file_order() -> None:
    parsed = load_states(REAL_STATES)
    chosen = [state.name for state in select_states(parsed, None)]
    assert sorted(chosen) == sorted(DEFAULT_STATES)
    order = [state.name for state in parsed.states]
    assert chosen == sorted(chosen, key=order.index)


def test_every_state_of_states_toml_is_either_offered_or_excluded_with_a_reason() -> None:
    names = {state.name for state in load_states(REAL_STATES).states}
    assert names == set(COMPARABLE_STATES) | set(EXCLUDED_STATES)
    assert not set(COMPARABLE_STATES) & set(EXCLUDED_STATES)
    assert all(reason for reason in EXCLUDED_STATES.values())


def test_an_excluded_state_is_refused_with_its_reason() -> None:
    with pytest.raises(ValueError, match="app-menu-gtk.*Breeze GTK theme"):
        select_states(load_states(REAL_STATES), ["desktop-empty", "app-menu-gtk"])


def test_unknown_and_dark_only_states_are_refused() -> None:
    with pytest.raises(ValueError, match="not offered"):
        select_states(load_states(REAL_STATES), ["no-such-state"])
    dark_only = parse_states(
        {
            "settings": {"resolution": [2560, 1440], "settle_frames": 2, "settle_interval_s": 1.0, "settle_timeout_s": 45, "rtc_base": "2026-09-25T12:00:00", "reset": []},
            "modes": {"light": {"scheme": "light"}, "dark": {"scheme": "dark"}},
            "state": [{"name": "overview", "description": "x", "steps": [], "modes": ["dark"]}],
        }
    )
    with pytest.raises(ValueError, match="light mode"):
        select_states(dark_only, ["overview"])
    with pytest.raises(ValueError, match="not defined"):
        select_states(dark_only, ["desktop-empty"])


# --- the run --------------------------------------------------------------------------------------


class FakeVm:
    """
    A VM that never boots, carrying a ``FakeGuest`` as its agent.

    Args:
        config: The configuration the factory received.
        guest: The guest agent fake.
        enter_error: Raised when entering (failed boot), or None.
    """

    def __init__(self, config: VmConfig, guest: FakeGuest, enter_error: Exception | None = None) -> None:
        self.config = config
        self.agent = guest
        self.enter_error = enter_error
        self.timings = {"agent_up_s": 5.0}
        self.t0 = time.monotonic()
        self.screen = self
        self.dumps: list[Path] = []

    def __enter__(self) -> FakeVm:
        """
        Enter the context.

        Returns:
            This object.

        Raises:
            Exception: the configured boot error.
        """
        if self.enter_error is not None:
            raise self.enter_error
        return self

    def __exit__(self, *exc: object) -> None:
        """Nothing to stop."""

    def screendump(self, path: Path) -> None:
        """
        Record a screenshot request and write a stand-in file.

        Args:
            path: Destination.
        """
        self.dumps.append(path)
        path.write_bytes(b"frame")

    def resources(self) -> dict[str, float]:
        """
        Return fixed numbers.

        Returns:
            A small summary.
        """
        return {"qemu_avg_cores": 1.0}


class FakeRunner:
    """
    Records settles and states; ``settle_ok`` decides the post-revert settle.

    Args:
        fail_states: States that fail.
        settle_ok: Whether ``settle`` reports a stable screen.
    """

    def __init__(self, fail_states: set[str] | None = None, settle_ok: bool = True) -> None:
        self.fail_states = fail_states or set()
        self.settle_ok = settle_ok
        self.calls: list[str] = []
        self.references: list[Path | None] = []

    def wait_for_desktop(self, masks: Any) -> SettleResult:
        """
        Pretend the desktop came up.

        Args:
            masks: Ignored.

        Returns:
            A stable result.
        """
        self.calls.append("boot")
        return SettleResult(True, 1.0, 3)

    def settle(self, masks: Any, reference: Path | None = None) -> SettleResult:
        """
        Pretend to settle.

        Args:
            masks: Ignored.
            reference: The frame the screen must differ from.

        Returns:
            Stable or a timeout, per ``settle_ok``.
        """
        self.calls.append("settle")
        self.references.append(reference)
        return SettleResult(self.settle_ok, 2.0, 2, "" if self.settle_ok else "timeout")

    def run_state(self, state: Any, mode: Any, masks: Any, shot: Path, rel: str) -> StateResult:
        """
        Pretend to capture a state.

        Args:
            state: The state.
            mode: The mode.
            masks: Ignored.
            shot: Destination.
            rel: Relative destination.

        Returns:
            The result.
        """
        self.calls.append(state.name)
        if state.name in self.fail_states:
            return StateResult(state.name, mode.name, "failed", error="timeout")
        shot.write_bytes(b"\x89PNG fake")
        return StateResult(state.name, mode.name, shot=rel)


@pytest.fixture
def stock_options(tmp_path: Path) -> StockOptions:
    """
    Options writing into a temporary directory, using the real states.toml.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        The options.
    """
    return StockOptions(out_dir=tmp_path / "out", states=DEFAULT_STATES, name=NAME, image_dir=tmp_path / "image", display="gpu", states_file=REAL_STATES)


def run_with(options: StockOptions, guest: FakeGuest, runner: FakeRunner, enter_error: Exception | None = None) -> tuple[int, dict[str, Any], list[FakeVm]]:
    """
    Run ``run_stock`` with the fakes.

    Args:
        options: The options.
        guest: The guest fake.
        runner: The runner fake.
        enter_error: Boot error, or None.

    Returns:
        Exit code, manifest and the created VMs.
    """
    created: list[FakeVm] = []

    def factory(config: VmConfig) -> FakeVm:
        created.append(FakeVm(config, guest, enter_error))
        return created[-1]

    code, manifest = run_stock(options, vm_factory=factory, runner_factory=lambda *args: runner, log=lambda line: None)
    return code, manifest, created


def test_a_clean_run_reverts_proves_and_captures(stock_options: StockOptions) -> None:
    stale = stock_options.out_dir / "light" / "overview.FAILED.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    guest, runner = FakeGuest(), FakeRunner()
    code, manifest, created = run_with(stock_options, guest, runner)
    assert code == 0
    assert created[0].config.display == "gpu"
    # Boot, the post-revert settle (against the pre-revert frame), then the states.
    assert runner.calls[:2] == ["boot", "settle"]
    assert runner.references[0] is not None
    assert runner.calls[2:] == [s for s in ("desktop-empty", "overview", "files-window", "settings-window") if s in runner.calls]
    assert sorted(runner.calls[2:]) == sorted(DEFAULT_STATES)
    assert any(call[0] == "plasma-apply-lookandfeel" for call in guest.calls)
    for state in DEFAULT_STATES:
        assert (stock_options.out_dir / "light" / f"{state}.png").is_file()
    assert not stale.exists()
    written = json.loads((stock_options.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert written["outcome"] == "ok"
    assert written["kind"] == "stock-plasma"
    assert written["evidence"]["decoration"] == STOCK_DECORATION
    assert any("look-and-feel" in item for item in written["reverted"])
    assert manifest["summary"] == {"total": 4, "ok": 4, "failed": 0}


def test_a_failing_revert_captures_nothing_and_is_an_environment_problem(stock_options: StockOptions) -> None:
    guest, runner = FakeGuest(), FakeRunner()
    guest.fail_contains = "kuura_frostEnabled"
    with pytest.raises(EnvironmentProblem, match="revert step failed: set kwinrc"):
        run_with(stock_options, guest, runner)
    assert runner.calls == ["boot"]
    written = json.loads((stock_options.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert written["outcome"] == "environment-error"
    assert "kuura_frostEnabled" in written["error"]
    assert not list((stock_options.out_dir / "light").glob("*.png"))


def test_a_session_that_is_not_stock_after_the_revert_captures_nothing(stock_options: StockOptions) -> None:
    guest, runner = FakeGuest(), FakeRunner()
    guest.support = SUPPORT_INFO_PRODUCT
    with pytest.raises(EnvironmentProblem, match="not stock after the revert.*kuura.decoration"):
        run_with(stock_options, guest, runner)
    assert runner.calls == ["boot", "settle"]


def test_a_screen_that_does_not_settle_after_the_revert_is_an_error(stock_options: StockOptions) -> None:
    with pytest.raises(EnvironmentProblem, match="did not settle after the revert"):
        run_with(stock_options, FakeGuest(), FakeRunner(settle_ok=False))


def test_a_wrong_product_name_is_refused_before_any_change(stock_options: StockOptions) -> None:
    guest = FakeGuest()
    guest.installed = False
    with pytest.raises(EnvironmentProblem, match="not built as 'kuura'"):
        run_with(stock_options, guest, FakeRunner())
    assert guest.calls == []


def test_a_failed_state_gives_exit_code_1_and_later_states_still_run(stock_options: StockOptions) -> None:
    runner = FakeRunner(fail_states={"desktop-empty"})
    code, manifest, _ = run_with(stock_options, FakeGuest(), runner)
    assert code == 1
    assert manifest["summary"] == {"total": 4, "ok": 3, "failed": 1}
    assert "settings-window" in runner.calls


def test_a_boot_failure_is_an_environment_problem_with_a_manifest(stock_options: StockOptions) -> None:
    with pytest.raises(EnvironmentProblem, match="kernel"):
        run_with(stock_options, FakeGuest(), FakeRunner(), enter_error=VmBootError("kernel panic"))
    assert json.loads((stock_options.out_dir / "manifest.json").read_text(encoding="utf-8"))["outcome"] == "environment-error"


# --- options ---------------------------------------------------------------------------------------


def _args(**overrides: Any) -> Any:
    """
    Build a parsed-arguments stand-in.

    Args:
        **overrides: Values to change.

    Returns:
        An object with the CLI's attributes.
    """
    import argparse

    values = {"out": None, "states": None, "name": NAME, "image_dir": Path("image"), "display": "software"}
    values.update(overrides)
    return argparse.Namespace(**values)


def test_default_output_directory_depends_on_the_display() -> None:
    assert build_options(_args()).out_dir.name == "shots-stock"
    assert build_options(_args(display="gpu")).out_dir.name == "shots-stock-gpu"
    assert build_options(_args(states="overview,files-window")).states == ("overview", "files-window")


@pytest.mark.parametrize("overrides", [{"name": "Bad Name"}, {"states": "a,,b"}, {"out": Path("/")}])
def test_bad_options_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        build_options(_args(**overrides))

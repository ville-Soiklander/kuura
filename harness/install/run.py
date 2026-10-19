"""
Command line tool: prove the ISO's own real install end to end, both firmware paths.

    python3 -m harness.install.run --iso-dir DIR [--firmware bios,uefi]
                                    [--states a,b] [--modes light,dark]
                                    [--name NAME] [--generated DIR]
                                    [--out DIR] [--disk-dir DIR]

LOCKED INTERFACE (docs/ISO_CONTRACT.md "Installed-system verification", 2026-10-13).
This file defines the CLI/exit-code contract and orchestration shape; the
implementation bodies are intentionally ``raise NotImplementedError``/omitted for
the delegated implementation pass to fill in against real QEMU runs, not guessed.
Deliberately mirrors harness/shots/capture.py's own shape throughout (options
dataclass, ``run_x`` returning ``(exit code, manifest)``, a ``main()`` using it) so
a maintainer who already knows that module has nothing new to learn about this
one's structure - only what is actually different (see below) needed a design
decision at all.

For every selected firmware (default: both - docs/ISO_CONTRACT.md's own DoD line
requires "ISO bootaa UEFI + BIOS", not either):
  1. Create a fresh disk (``qemu-img create``, overwriting any stale one from an
     earlier run of this tool - never reused, unlike harness/shots/vm.py's
     ``-snapshot`` overlay, because this tool's whole point is proving a REAL,
     persistent install).
  2. Boot the one ``*.iso`` found in ``--iso-dir`` (exactly one is expected there;
     zero or more than one is an environment error, checked before any slow boot -
     same "fail fast on bad input" principle as capture.py's own colour-scheme
     pre-check) via harness.install.boot.InstallVm, phase 1.
  3. Drive harness.install.wizard.run_install to Finish.
  4. harness.install.boot.InstallVm.reboot_to_disk_only() - phase 2: the SAME disk,
     no ISO, proving it is independently bootable
     (docs/ISO_CONTRACT.md "Installed-system verification").
  5. Drive harness.install.wizard.log_into_sddm (added 2026-10-14, same real-run
     audit): Calamares' own ``doAutologin: false`` means the installed system
     always reaches an SDDM greeter, never an already-running session, so nothing
     past this point could ever see a desktop without actually logging in first.
  6. Connect the now-running qemu-guest-agent (``attach_guest_agent=True``,
     ``guest_user=GuestUser()`` when WizardCredentials.username was "desktop" - see
     wizard.py's own docstring) and hand off to the EXISTING
     ``harness.shots.runner.Runner`` + ``harness/states.toml`` +
     ``harness.shots.compare`` machinery UNCHANGED to run the real vaiheet 3-6
     diff-pass against this real installed system - not a reimplementation, the
     literal same comparison this project's CI already trusts for the desktop
     image (harness/vm/'s pre-baked one), now pointed at a real Calamares-installed
     disk instead. Writes shots the same way capture.py does
     (``out_dir/<firmware>/<mode>/<state>.png``) so ``harness.shots.compare`` can be
     invoked against them completely unchanged too (one extra path segment,
     firmware, versus capture.py's own ``out_dir/<mode>/<state>.png`` - the only
     structural difference, because this tool must keep bios and uefi results
     apart within one run).

Exit codes mirror harness/shots/capture.py's own convention (docs/HARNESS_CONTRACT.md):
    0  every selected firmware path installed, booted standalone and passed every
       selected state
    1  an install, reboot or a state's diff failed for some firmware path (the run
       continues to the next firmware path rather than stopping there - same
       "a failure does not stop the rest of the plan" principle as capture.py)
    2  environment or usage problem (no KVM, no OVMF for uefi, ISO missing or
       ambiguous in --iso-dir, bad options) - checked before any slow boot

Defaults come from the same places capture.py's do: ``DISTRO_NAME`` env var for
``--name``, generated dir ``.build/generated``, plus this tool's own
``--iso-dir`` default ``.build/iso`` (iso/build_iso.sh's own ``ISO_BUILD_DIR``
default) and ``--disk-dir`` default ``.build/install-disks`` (scratch, already
covered by .gitignore's blanket ``.build/`` entry - not the same thing as
harness/shots' own ``.build/vm``).

Make target: ``installed-verify`` (depends on ``iso``, which depends on ``repo`` -
Makefile; name deliberately distinct from the existing, unrelated
``verify-install`` target, which checks that `make repo`'s own package repository
installs cleanly into a plain chroot - nothing to do with Calamares or the ISO).

CI: a new ``install-harness`` job in .github/workflows/ci.yml, copied from the
existing ``screenshot-harness`` job's own "skip without a usable /dev/kvm" pattern
(docs/HARNESS_CONTRACT.md "Limits" - GitHub-hosted ubuntu-24.04 runners are
confirmed to have none, so this job will, in practice, always skip itself there
too right now, exactly like screenshot-harness already does; it exists for a
self-hosted runner or a future hosted runner with KVM, not as dead weight) -
``apt-get install -y qemu-system-x86 qemu-utils ovmf`` (ovmf already proven to
work by that same existing job).

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.install.boot import (
    DEFAULT_OVMF_CODE_PATH,
    DEFAULT_OVMF_VARS_TEMPLATE_PATH,
    Firmware,
    InstallVm,
    InstallVmBootError,
    InstallVmConfig,
    InstallVmEnvironmentError,
)
from harness.install.testpackages import (
    ARCHIVE_DATE_PATTERN,
    ArchiveFetcher,
    TestPackageError,
    install_test_only_packages,
)
from harness.install.wizard import (
    WizardCredentials,
    WizardError,
    inject_test_only_session_config,
    log_into_sddm,
    run_install,
)
from harness.shots import states as states_module
from harness.shots.capture import guard_output_dir, split_names
from harness.shots.compare import StateRules, load_rules
from harness.shots.diff import compare_images, write_diff_image
from harness.shots.guest import GuestUser
from harness.shots.review import render_report
from harness.shots.runner import Runner, StateResult, StepError

NAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDENS_DIR = PROJECT_ROOT / "harness" / "goldens"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ENVIRONMENT = 2

#: Matches harness.shots.guest.GuestUser()'s own defaults exactly - see
#: harness/install/wizard.py's WizardCredentials.username docstring for why that
#: is deliberate, not incidental.
DEFAULT_CREDENTIALS = WizardCredentials(full_name="Kuura Test", username="desktop", password="kuura123test")


class EnvironmentProblem(Exception):
    """Something outside the install/boot itself prevents the run (exit code 2)."""


@dataclass(frozen=True)
class InstalledVerifyOptions:
    """
    Everything ``run_installed_verify`` needs, already validated.

    Attributes:
        out_dir: Output directory (inside the project tree) for screenshots and
            the manifest - same tree-containment rule as
            harness.shots.capture.guard_output_dir (reuse that function; do not
            reimplement it).
        firmwares: Firmware paths to exercise.
        states: State names to verify, or None for all (same states.toml the
            desktop harness uses).
        modes: Mode names to verify, or None for all.
        name: Theme name of the generated colour schemes.
        generated_dir: Directory produced by ``python -m design.generate``.
        iso_dir: Directory expected to contain exactly one ``*.iso``.
        disk_dir: Scratch directory for the per-firmware qcow2 disks.
        credentials: The test account the install creates (DEFAULT_CREDENTIALS
            unless a caller overrides it).
        states_file: Same meaning as harness.shots.capture.CaptureOptions.states_file.
        archive_date: Arch Archive snapshot (``YYYY/MM/DD``, ARCH_ARCHIVE_DATE) the
            ISO was built from. The test-only programs (notify-send, mousepad,
            gtk4-widget-factory) are fetched from exactly that snapshot and installed
            into the target, because the shipped product does not contain them.
        package_cache: Host directory caching the downloaded package files.
    """

    out_dir: Path
    firmwares: list[Firmware]
    states: list[str] | None
    modes: list[str] | None
    name: str
    generated_dir: Path
    iso_dir: Path
    disk_dir: Path
    credentials: WizardCredentials = DEFAULT_CREDENTIALS
    states_file: Path = PROJECT_ROOT / "harness" / "states.toml"
    archive_date: str = ""
    package_cache: Path = PROJECT_ROOT / ".build" / "install-verify-pkgs"


def find_single_iso(iso_dir: Path) -> Path:
    """
    Args:
        iso_dir: Directory expected to contain exactly one ``*.iso``.

    Returns:
        That file's path.

    Raises:
        EnvironmentProblem: zero or more than one ``*.iso`` found (named ones, not
            counts, in the message - an agent or a human fixing this needs to know
            WHICH files are there).
    """
    if not iso_dir.is_dir():
        raise EnvironmentProblem(f"ISO directory {iso_dir.name!r} does not exist; run `make iso` first")
    isos = sorted(iso_dir.glob("*.iso"))
    if len(isos) != 1:
        found = ", ".join(repr(p.name) for p in isos) if isos else "none"
        raise EnvironmentProblem(f"expected exactly one *.iso in {iso_dir.name!r}, found: {found}")
    return isos[0]


def _load_rules(states_file: Path) -> dict[str, StateRules]:
    """
    Load comparison rules through the comparison side's real loader.

    Args:
        states_file: Path of ``states.toml``.

    Returns:
        State name to its StateRules (tolerance, ratio, masks, modes).

    Raises:
        EnvironmentProblem: the rules cannot be loaded.
    """
    try:
        return load_rules(states_file)
    except (ValueError, TypeError, KeyError) as exc:
        raise EnvironmentProblem(f"comparison rules: {exc}") from None


def _run_states(
    runner: Runner,
    plan: list[tuple[Any, Any]],
    rules: dict[str, StateRules],
    generated_dir: Path,
    name: str,
    out_dir: Path,
    results: list[StateResult],
    log: Any,
) -> str:
    """
    Run every (mode, state) pair of the plan against one already-booted, already
    guest-agent-connected target - same orchestration shape as
    harness.shots.capture's own private per-plan loop (not imported from there:
    that helper is private to that module, and this tool's own plan is grouped
    per firmware rather than per capture run, so it needed its own small copy of
    the same "apply each mode once, then its states" orchestration; the actual
    settle/comparison LOGIC it calls into - Runner.apply_mode/run_state,
    diff.compare_images - is the unchanged original, not reimplemented).

    Args:
        runner: Runner bound to the booted, reachable installed target.
        plan: ``(mode, state)`` pairs in run order.
        rules: Comparison rules per state name (also carries the settle masks).
        generated_dir: Directory produced by ``python -m design.generate``.
        name: Theme name of the generated colour schemes.
        out_dir: ``<out_dir>/<firmware>`` - where shots are written.
        results: Output list that receives one StateResult per planned pair.
        log: Progress callback.

    Returns:
        The empty string, or a description if the VM connection was lost.
    """
    current_mode = None
    mode_error = ""
    lost = ""
    for mode, state in plan:
        rel = f"{mode.name}/{state.name}.png"
        masks = rules[state.name].masks if state.name in rules else []
        if lost:
            results.append(StateResult(state.name, mode.name, "failed", error=f"not run: {lost}"))
            continue
        try:
            if mode is not current_mode:
                current_mode = mode
                mode_error = ""
                log(f"applying mode {mode.name}")
                try:
                    runner.apply_mode(mode, generated_dir, name, masks)
                except StepError as exc:
                    mode_error = f"mode {mode.name} could not be applied: {exc}"
            if mode_error:
                results.append(StateResult(state.name, mode.name, "failed", error=mode_error))
                continue
            results.append(runner.run_state(state, mode, masks, out_dir / rel, rel))
        except ConnectionError as exc:
            lost = f"the VM connection was lost ({exc})"
            results.append(StateResult(state.name, mode.name, "failed", error=lost))
    return lost


def _compare_state(
    result: StateResult, rules: dict[str, StateRules], fw_dir: Path, goldens_dir: Path
) -> dict[str, Any]:
    """
    Compare one captured state's shot against its golden, through
    harness.shots.diff.compare_images - the SAME function
    harness.shots.compare's own CLI uses, called directly as a library rather
    than shelling out to that CLI (which only accepts ``sys.argv``), so this is
    reuse of the real comparison, not a second implementation of it.

    Args:
        result: The capture outcome for this (mode, state) pair.
        rules: Comparison rules per state name.
        fw_dir: ``<out_dir>/<firmware>`` - where the shot (and, on failure, the
            diff image) live.
        goldens_dir: ``harness/goldens``.

    Returns:
        A dict in the same shape harness.shots.compare's own CLI produces (mode,
        state, status, differing_pixels, ratio, max_delta, bbox, ...), status one
        of "pass", "fail", "missing-golden" or "failed" (the capture itself
        failed - never reached comparison).
    """
    entry: dict[str, Any] = {
        "mode": result.mode, "state": result.state, "differing_pixels": None,
        "ratio": None, "max_delta": None, "bbox": None,
    }
    if result.status != "ok":
        entry["status"] = "failed"
        entry["error"] = result.error
        return entry

    golden_path = goldens_dir / result.mode / f"{result.state}.png"
    shot_path = fw_dir / result.mode / f"{result.state}.png"
    if not golden_path.is_file():
        entry["status"] = "missing-golden"
        return entry

    rule = rules.get(result.state)
    tolerance = rule.tolerance if rule else 3
    max_diff_ratio = rule.max_diff_ratio if rule else 0.0005
    masks = rule.masks if rule else []
    try:
        diff_result = compare_images(shot_path, golden_path, tolerance, max_diff_ratio, masks)
    except (OSError, ValueError) as exc:
        entry["status"] = "failed"
        entry["error"] = f"comparison failed: {exc}"
        return entry

    entry["status"] = "pass" if diff_result.passed else "fail"
    entry["differing_pixels"] = diff_result.differing_pixels
    entry["ratio"] = diff_result.ratio
    entry["max_delta"] = diff_result.max_delta
    entry["bbox"] = diff_result.bbox
    if not diff_result.passed:
        diff_path = fw_dir / result.mode / f"{result.state}-diff.png"
        try:
            write_diff_image(shot_path, golden_path, diff_path, tolerance, masks)
        except (OSError, ValueError):
            pass  # the verdict still stands without a visual diff
    return entry


def run_installed_verify(
    options: InstalledVerifyOptions,
    log: Any = lambda line: print(line, flush=True),
) -> tuple[int, dict[str, Any]]:
    """
    Run the full install -> reboot -> diff-pass sequence for every selected firmware.

    Args:
        options: The validated options.
        log: Progress callback (one line of text) - same convention as
            harness.shots.capture.run_capture's own ``log`` parameter.

    Returns:
        ``(exit code, manifest)``. The manifest is also written to
        ``<out_dir>/manifest.json``. Shape mirrors
        harness.shots.capture.run_capture's manifest (``schema``, ``outcome``,
        ``results``, ``summary``, ``host``, ``total_seconds``) with one added top
        level: results are grouped per firmware first, since a BIOS failure must
        not hide whether UEFI separately passed.

    Raises:
        EnvironmentProblem: states.toml is invalid, a colour scheme file, KVM, the
            ISO (missing/ambiguous), OVMF (uefi selected but not installed) or the
            comparison module is missing.
    """
    started = time.monotonic()

    # ---- Fail fast on bad input, before any slow boot (capture.py's own principle). ----
    iso_path = find_single_iso(options.iso_dir)
    try:
        parsed = states_module.load_states(options.states_file)
        modes, chosen_states = states_module.select(parsed, options.states, options.modes)
    except ValueError as exc:
        raise EnvironmentProblem(str(exc)) from None
    plan = [(mode, state) for mode in modes for state in chosen_states if mode.name in state.modes]
    if not plan:
        raise EnvironmentProblem("nothing to verify: the selection matches no state in any mode")
    rules = _load_rules(options.states_file)

    for mode in modes:
        scheme_file = options.generated_dir / "plasma" / f"{options.name}-{mode.scheme}.colors"
        if not scheme_file.is_file():
            raise EnvironmentProblem(
                f"generated colour scheme {scheme_file.name} is missing; run `python -m design.generate`"
            )

    if not (os.access("/dev/kvm", os.R_OK) and os.access("/dev/kvm", os.W_OK)):
        raise EnvironmentProblem("/dev/kvm is not accessible (is this user in the kvm group?)")
    if Firmware.UEFI in options.firmwares:
        for firmware_path in (DEFAULT_OVMF_CODE_PATH, DEFAULT_OVMF_VARS_TEMPLATE_PATH):
            if not firmware_path.is_file():
                raise EnvironmentProblem(f"OVMF firmware file {firmware_path.name!r} is missing; install the ovmf package")

    # Resolve the test-only programs now (needs the host's pacman and network): a
    # problem here should stop the run before the first slow install, not after it.
    try:
        package_fetcher = ArchiveFetcher(options.archive_date, options.package_cache)
        package_fetcher.resolve()
    except TestPackageError as exc:
        raise EnvironmentProblem(str(exc)) from None

    options.disk_dir.mkdir(parents=True, exist_ok=True)
    options.out_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "schema": 1,
        "name": options.name,
        "outcome": "incomplete",
        "firmwares": [firmware.value for firmware in options.firmwares],
        "results": {},
    }
    overall_ok = True

    for firmware in options.firmwares:
        log(f"=== firmware: {firmware.value} ===")
        fw_dir = options.out_dir / firmware.value
        for mode in modes:
            target = fw_dir / mode.name
            target.mkdir(parents=True, exist_ok=True)
            for state in chosen_states:
                (target / f"{state.name}.png").unlink(missing_ok=True)
                (target / f"{state.name}.FAILED.png").unlink(missing_ok=True)
                (target / f"{state.name}-diff.png").unlink(missing_ok=True)

        fw_entry: dict[str, Any] = {"firmware": firmware.value, "install": None, "reboot": None, "states": []}
        disk_path = options.disk_dir / f"{firmware.value}.qcow2"
        disk_path.unlink(missing_ok=True)
        capture_results: list[StateResult] = []
        try:
            config = InstallVmConfig(disk_path=disk_path, iso_path=iso_path, firmware=firmware)
            config.validate()
            made = subprocess.run(
                ["qemu-img", "create", "-f", "qcow2", str(disk_path), f"{config.disk_size_gib}G"],
                capture_output=True, text=True,
            )
            if made.returncode != 0:
                raise InstallVmEnvironmentError(f"qemu-img create failed: {made.stderr.strip()}")

            with InstallVm(config) as vm:
                log("driving the Calamares wizard")
                wizard_result = run_install(vm, options.credentials, fw_dir / "wizard", log=log)
                fw_entry["install"] = {"finished": wizard_result.finished, "duration_s": wizard_result.duration_s}

                log("rebooting the installed disk, no ISO attached")
                guest_user = GuestUser(name=options.credentials.username, group=options.credentials.username)
                # Phase 2 only: match harness.shots.vm.VmConfig's own resolution default
                # (2560, 1440), NOT phase 1's 1920x1080 - the diff-pass below compares
                # against harness/goldens/, which were captured at that resolution by
                # that module. Phase 1's own Calamares-wizard automation (every
                # coordinate in harness.install.wizard) is untouched and stays at
                # 1920x1080 (see harness.install.boot.InstallVm.reboot_to_disk_only's
                # own "resolution" note, added 2026-10-14 after the first real
                # diff-pass run surfaced this exact size mismatch).
                vm.reboot_to_disk_only(
                    attach_guest_agent=True, guest_user=guest_user, resolution=(2560, 1440)
                )
                fw_entry["reboot"] = dict(vm.timings)
                assert vm.agent is not None  # guaranteed by attach_guest_agent=True above

                # Before login: systemd --user reads ~/.config/environment.d/*.conf
                # once, when the user manager starts for this login
                # (docs/ISO_CONTRACT.md "Installed-system verification", decided
                # 2026-10-16) - writing it after log_into_sddm() would be too late
                # for this same boot.
                log("staging test-only session configuration")
                inject_test_only_session_config(vm, guest_user, log=log)
                # The programs some states run are not in the product: bring them
                # from the same archive snapshot as the ISO (offline in the guest).
                install_test_only_packages(vm.agent, package_fetcher, log=log)

                # Calamares' own users.conf has doAutologin: false (deliberate security
                # default) - the installed system always reaches an SDDM greeter, never an
                # already-running session, so Runner.wait_for_desktop() below could never
                # see "plasmashell" without this (docs/ISO_CONTRACT.md "Installed-system
                # verification", decided 2026-10-14: drive a real login rather than
                # special-case autologin into a test-only build).
                login_started = time.monotonic()
                log_into_sddm(vm, options.credentials, fw_dir / "sddm", log=log)
                fw_entry["sddm_login_s"] = round(time.monotonic() - login_started, 1)

                work_dir = Path(tempfile.mkdtemp(prefix="install-verify-work-"))
                try:
                    runner = Runner(vm.qmp, vm.agent, parsed.settings, work_dir, log=log, cpu_probe=vm.agent.cpu_sample)
                    log("waiting for the installed desktop")
                    ready = runner.wait_for_desktop(rules[plan[0][1].name].masks if plan[0][1].name in rules else [])
                    fw_entry["desktop_ready_s"] = round(ready.seconds, 1)
                    vm_error = _run_states(
                        runner, plan, rules, options.generated_dir, options.name, fw_dir, capture_results, log
                    )
                    if vm_error:
                        fw_entry["vm_error"] = vm_error
                finally:
                    shutil.rmtree(work_dir, ignore_errors=True)
        except (
            InstallVmEnvironmentError,
            InstallVmBootError,
            WizardError,
            TestPackageError,
            StepError,
            ValueError,
            OSError,
        ) as exc:
            fw_entry["error"] = str(exc)

        states_out = [_compare_state(result, rules, fw_dir, GOLDENS_DIR) for result in capture_results]
        fw_entry["states"] = states_out
        failed = [s for s in states_out if s["status"] != "pass"]
        fw_entry["summary"] = {"total": len(states_out), "pass": len(states_out) - len(failed), "failed": len(failed)}
        fw_ok = (
            "error" not in fw_entry
            and bool(fw_entry["install"])
            and fw_entry["install"]["finished"]
            and len(states_out) == len(plan)
            and not failed
        )
        fw_entry["outcome"] = "ok" if fw_ok else "failed"
        if not fw_ok:
            overall_ok = False
        try:
            (fw_dir).mkdir(parents=True, exist_ok=True)
            (fw_dir / "summary.json").write_text(json.dumps(fw_entry, indent=2) + "\n", encoding="utf-8")
            (fw_dir / "report.md").write_text(render_report(states_out), encoding="utf-8")
        except OSError:
            pass  # evidence files are best-effort; the manifest below is authoritative
        manifest["results"][firmware.value] = fw_entry

    manifest["outcome"] = "ok" if overall_ok else "failed"
    manifest["total_seconds"] = round(time.monotonic() - started, 1)
    (options.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return (EXIT_OK if overall_ok else EXIT_FAILED), manifest


def _parse_firmwares(text: str | None) -> list[Firmware]:
    """
    Parse ``--firmware``.

    Args:
        text: Comma separated firmware names, or None for both.

    Returns:
        The selected firmwares, in a stable (bios, uefi) order regardless of the
        order the caller wrote them in.

    Raises:
        ValueError: an entry is empty or not "bios"/"uefi".
    """
    if text is None:
        return [Firmware.BIOS, Firmware.UEFI]
    names = set(split_names(text, "--firmware"))
    try:
        selected = {Firmware(name) for name in names}
    except ValueError:
        raise ValueError("--firmware must be a comma separated list of 'bios' and/or 'uefi'") from None
    return [f for f in (Firmware.BIOS, Firmware.UEFI) if f in selected]


def print_summary(manifest: dict[str, Any]) -> None:
    """
    Print a compact per-firmware summary table.

    Args:
        manifest: The manifest returned by ``run_installed_verify``.
    """
    print()
    for firmware_name, fw_entry in manifest["results"].items():
        install = fw_entry.get("install") or {}
        print(f"--- {firmware_name} ---")
        print(f"  install finished: {install.get('finished', False)}")
        if "error" in fw_entry:
            print(f"  error: {fw_entry['error']}")
        summary = fw_entry.get("summary", {})
        print(f"  states: {summary.get('pass', 0)}/{summary.get('total', 0)} passed")
        for state in fw_entry.get("states", []):
            if state["status"] != "pass":
                print(f"    {state['mode']}/{state['state']}: {state['status']}" + (f" - {state['error']}" if state.get("error") else ""))
    print(f"\noutcome: {manifest['outcome']} in {manifest['total_seconds']} s")


def main(argv: list[str] | None = None) -> int:
    """
    Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        The exit code (0, 1 or 2; see the module docstring).
    """
    parser = argparse.ArgumentParser(prog="python3 -m harness.install.run", description=__doc__.split("\n\n")[0])
    parser.add_argument("--iso-dir", type=Path, default=PROJECT_ROOT / ".build" / "iso")
    parser.add_argument("--disk-dir", type=Path, default=PROJECT_ROOT / ".build" / "install-disks")
    parser.add_argument("--firmware", help="comma separated: bios,uefi (default: both)")
    parser.add_argument("--states", help="comma separated state names (default: all)")
    parser.add_argument("--modes", help="comma separated mode names (default: all)")
    parser.add_argument("--name", default=os.environ.get("DISTRO_NAME", "theme"))
    parser.add_argument("--generated", type=Path, default=PROJECT_ROOT / ".build" / "generated")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--archive-date",
        default=os.environ.get("ARCH_ARCHIVE_DATE", ""),
        help="Arch Archive snapshot YYYY/MM/DD the ISO was built from (default: $ARCH_ARCHIVE_DATE)",
    )
    args = parser.parse_args(argv)
    try:
        if not NAME_PATTERN.match(args.name):
            raise ValueError("--name may only contain lowercase letters, digits, '_' and '-'")
        options = InstalledVerifyOptions(
            out_dir=guard_output_dir(args.out),
            firmwares=_parse_firmwares(args.firmware),
            states=split_names(args.states, "--states"),
            modes=split_names(args.modes, "--modes"),
            name=args.name,
            generated_dir=args.generated,
            iso_dir=args.iso_dir,
            disk_dir=args.disk_dir,
            archive_date=args.archive_date,
        )
        # Checked after the other arguments so a bad firmware/state name is reported first.
        if not ARCHIVE_DATE_PATTERN.match(args.archive_date):
            raise ValueError("set ARCH_ARCHIVE_DATE (or --archive-date) to the snapshot date YYYY/MM/DD")
        code, manifest = run_installed_verify(options)
    except (ValueError, EnvironmentProblem) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENVIRONMENT
    print_summary(manifest)
    return code


if __name__ == "__main__":
    sys.exit(main())

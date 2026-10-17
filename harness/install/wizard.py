"""
Drives Calamares' own installer wizard to completion over QMP alone, and (added
2026-10-14, same real-run audit) the SDDM login that follows a real reboot of the
installed disk - see log_into_sddm()'s own docstring.

LOCKED INTERFACE (docs/ISO_CONTRACT.md "Installed-system verification", 2026-10-13).
This file defines the contract; the implementation body is intentionally
``raise NotImplementedError`` for the delegated implementation pass to fill in
against a real QEMU run, not guessed.

Calamares has no built-in unattended-install mode: no CLI flag, no GlobalStorage
preseed file, and its OEM/phase-0 mode is documented upstream as "not yet planned"
(confirmed from Calamares' own source/CI during this project's Vaihe 7 research -
see project memory). The only way to drive it is the same way a person would -
screen, keyboard, mouse - which on a live ISO with no guest agent running (see
harness/install/boot.py's own docstring) means QMP screendump + synthetic input,
through the harness.install.boot.InstallVm this module expects to receive already
booted.

This module promotes the UI sequence this project's own manual and delegated-agent
recon sessions already proved reliable (docs/ISO_CONTRACT.md, project memory) from
throwaway scratch tooling (the now-superseded ``install_test.py`` one-command-per-
invocation recon tool) into a permanent, parametrized, tested, single-call driver:

    Welcome -> Location -> Keyboard -> Partitions (Erase disk) -> Users -> Summary
    -> Install -> Finish

Reuses harness/shots/qmp.py and harness/shots/keys.py UNCHANGED for every
screendump/click/keypress (letters/digits/space via keys.py's own type_text();
punctuation a username/password needs but keys.py's type_text() does not accept -
confirmed this project's own recon sessions needed at least "/ . - _ : = @ , |" and
could not even reach "+ $ ? ' \" ( ) [ ] ; *" that way either - goes through the
small qcode-chord map the now-superseded install_test.py already proved out; port
that map here rather than re-deriving it).

Progress is tracked by SCREENSHOT SETTLE, the same idea harness/shots/runner.py
already uses for the desktop harness (poll, compare consecutive frames, declare
settled once stable) - not a fixed sleep, because install duration is inherently
variable (package count actually transacted, host speed, disk I/O). There is no
guest agent to also probe CPU busyness with in this phase (see boot.py's own
docstring: the live session has not been asked to run one), so settle here is frame
stability alone, polled at a coarser interval than the desktop-mode harness since
Calamares' own pages change far less often than a running desktop does.

Standard library only.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.install.boot import InstallVm
from harness import skelmerge
from harness.shots.guest import RUNUSER, GuestUser
from harness.shots.pngio import read_png

#: Project root, two directories up from this file (harness/install/wizard.py ->
#: harness/install -> harness -> repo root) - same convention harness/install/run.py
#: and harness/shots/capture.py already use for their own PROJECT_ROOT constants.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Test-only files the screenshot harness image copies wholesale into /etc/skel
#: (harness/vm/Containerfile ``COPY guest/skel/``). By rule it holds ONLY files the
#: product does not ship itself (enforced by harness/tests/test_guest_skel.py), so
#: writing every file in it to the desktop user's home reproduces the image. The
#: file list is derived from the directory at call time so it cannot drift.
_GUEST_SKEL_DIR = _PROJECT_ROOT / "harness" / "vm" / "guest" / "skel"

#: The script the shots image build runs to create the fixed sample folder tree
#: (Desktop, Documents, ... with fixed content and modification times).
_SAMPLE_TREE_SCRIPT = _PROJECT_ROOT / "harness" / "vm" / "guest" / "make-sample-tree.sh"

#: Where the script is staged in the guest while it runs (removed right after).
_GUEST_SAMPLE_SCRIPT = "/tmp/make-sample-tree.sh"

#: Absolute paths of bash and rm in the guest (the agent's exec does no PATH lookup).
_BASH = "/usr/bin/bash"
_RM = "/usr/bin/rm"

#: Absolute path of ln in the guest (the agent's exec does no PATH lookup itself).
_LN = "/usr/bin/ln"

#: Login-name shape Calamares' own users module enforces (lowercase ASCII letters,
#: digits, "-"/"_", starting with a letter) - checked here too so a bad value fails
#: before a slow boot, not mid-wizard (WizardCredentials.__post_init__).
_USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")

#: Button/field pixel positions at the locked 1920x1080 resolution, measured
#: directly against this project's own real, running Calamares build this phase
#: (screendumps saved and inspected, not guessed) - the Welcome/Location/Keyboard/
#: Partitions/Users pages all share one window height (Back/Next/Cancel centred at
#: y=780); the Summary page's own longer content grows the window, so its button
#: row sits lower (y=876). Re-verified live immediately before being encoded here.
_NEXT_BUTTON = (1328, 780)
_INSTALL_BUTTON = (1333, 876)
_ERASE_DISK_RADIO = (655, 349)
_FULL_NAME_FIELD = (746, 329)
_USERNAME_FIELD = (746, 389)
_PASSWORD_FIELD = (746, 509)
_REPEAT_PASSWORD_FIELD = (951, 509)

#: Sidebar page-identity signal (see run_install()'s own module-level discussion
#: below `_page_at`): the nine-row (eight before Finish's own index 7) page list
#: down the left side of the Calamares window highlights the active page with a
#: fixed teal fill, confirmed by direct pixel sampling of real screenshots this
#: phase - RGB (79, 179, 200), rows evenly spaced 39 physical pixels apart,
#: sampled at a column (x=460) that is always inside the fill and never over an
#: icon or glyph. The vocabulary order below matches settings.conf.in's own show
#: sequence (docs/ISO_CONTRACT.md "Calamares configuration").
_SIDEBAR_X = 460
_SIDEBAR_ROW_HEIGHT = 39
_SIDEBAR_HIGHLIGHT_RGB = (79, 179, 200)
_SIDEBAR_COLOR_TOLERANCE = 24
_PAGE_NAMES = ("welcome", "location", "keyboard", "partitions", "users", "summary", "install", "finish")

#: Lower bound (y) for the _highlighted_row_y scan. REQUIRED, not cosmetic:
#: confirmed live this session that the product icon above the page list (a
#: circular logo, roughly y=256..273 at x=460) is close enough to
#: _SIDEBAR_HIGHLIGHT_RGB (within _SIDEBAR_COLOR_TOLERANCE on every channel -
#: measured directly: (59, 173, 194) against (79, 179, 200)) to false-match as
#: "the Welcome row" before the scan ever reaches the real page list, which
#: starts no earlier than y=359. A real run reached Location correctly (visibly,
#: in its own saved screenshot) but kept reporting "welcome" because the icon's
#: false match was found FIRST on every single frame, including Location's own -
#: since the false match is identical in both frames, anchor_y and every later
#: lookup silently agreed with each other and never surfaced as "not found" at
#: all. Starting the scan at 300 (comfortably below the icon, comfortably above
#: the first real row) removes the false match without narrowing the real one.
_SIDEBAR_SCAN_Y_START = 300

#: Upper bound on how long the real install (unpackfs + shellprocess + packages +
#: bootloader, ...) may run before this is treated as a hang rather than real,
#: still-progressing work - generous (this project's own measured real installs
#: take low-single-digit minutes, but a slow host or heavier package churn should
#: not be mistaken for a hang well short of that).
INSTALL_TIMEOUT_S = 2400.0

#: Pause after sending a click/keypress and before the first settle() poll that
#: follows it, used everywhere a settle() call is given ``frames=1`` (see
#: click_and_advance's own docstring for the real failure this fixes: without
#: it, the very first poll can catch a transient frame - the mouse pointer
#: having moved, or an animation mid-slide - and wrongly accept it as "the
#: action's result" before the actual change has rendered).
_ACTION_SETTLE_GUARD_S = 0.3

#: SDDM greeter's password field + "Log In" button, Breeze theme at 1920x1080 -
#: measured directly against a real post-install boot this phase (same "measured,
#: not guessed" discipline as every Calamares coordinate above), by pixel-scanning
#: a saved screendump for the white login-box's own borders. The box is centred on
#: screen by the theme itself, independent of which user it is showing (only the
#: name labels above it change) - confirmed stable before, and expected to remain
#: stable after, packages/kuura-installer-config/.../shellprocess.conf's own
#: ``userdel -r liveuser`` fix removes the second account (docs/ISO_CONTRACT.md
#: "Installed-system verification").
#:
#: CORRECTED 2026-10-14 against a real end-to-end run (harness.install.run,
#: BIOS): the original y values (536, 571) were never actually on either
#: widget - both landed in the dark gap between them. A fine-grained pixel
#: scan of a real greeter screendump (desktop ready, password field empty)
#: found the field's own solid-white fill spans y=505..524 at x=960 (used
#: y=515) and the button's spans y=540..562 at the same x (used y=550, clear
#: of the "Log In" label glyphs' anti-aliased pixels around y=547-561 - not
#: that it matters for a click, only for readability of this constant).
#: This silently broke every real SDDM-login attempt since this code was
#: added (``wait_until(True, ...)`` always read the gap's background colour,
#: never white, so it timed out every time with no visible sign of a
#: genuine hang - confirmed independently: a standalone diagnostic boot of
#: the same disk showed a fully rendered, idle greeter at this exact pixel
#: the whole time, clock ticking normally).
#:
#: NOTE: these two constants, and _SDDM_USER_TILE below, are phase-1/phase-2
#: SHARED in name only - see the PHASE 2 ONLY block further down for the real,
#: currently-used values. Kept here unchanged as the historical record of the
#: 1920x1080 measurement this project's own install-verify pipeline no longer
#: boots phase 2 at (see harness.install.boot.InstallVm.reboot_to_disk_only's
#: own "resolution" note, 2026-10-14) - not deleted, since a future caller that
#: ever needs phase 2 back at 1920x1080 (matching phase 1) would otherwise have
#: to re-measure these from scratch.
_SDDM_PASSWORD_FIELD_1920X1080 = (960, 515)
_SDDM_LOGIN_BUTTON_1920X1080 = (960, 550)

#: The single user tile ("Kuura Test"), teal fill rgb(79,179,200), measured the same
#: way: y=452..490, x=805..1115 at 1920x1080, centre (960, 470).
#:
#: ADDED 2026-10-14, same real-run audit as the coordinate fix above: with the two
#: coordinates above corrected, every login attempt still failed, now with SDDM's
#: own greeter showing "Login failed" instead of timing out. The journal pulled
#: live from the guest over the already-connected qemu-guest-agent (authoritative -
#: not another pixel guess) named the real cause precisely:
#: ``pam_unix(sddm:auth): check pass; user unknown`` /
#: ``Authentication for user  ""  failed`` - SDDM submitted an EMPTY username, not
#: a wrong password (independently confirmed correct: the stored yescrypt hash on
#: a real installed disk was recomputed from "kuura123test" with its own salt via
#: libcrypt and matched byte for byte). The tile's teal fill is theme styling for
#: the *default-highlighted* user shown on screen - it is not the same thing as
#: SDDM's own internal "current user" model selection, which this code was never
#: actually setting; nothing before this fill_field()/click sequence had clicked
#: the tile itself. One real click on it, before typing the password, is required
#: to give the greeter's Login request an actual username.
_SDDM_USER_TILE_1920X1080 = (960, 470)

#: PHASE 2 ONLY, at 2560x1440 - added 2026-10-14, after the project owner chose
#: option (A) (AskUserQuestion) in response to the first real diff-pass run
#: against harness/goldens/ failing 22/22, overwhelmingly on
#: "image size mismatch: 1920x1080 vs 2560x1440": phase 2 (this reboot + SDDM
#: login + the Runner diff-pass that follows, a SEPARATE QEMU process from phase
#: 1 - see harness.install.boot.InstallVm.reboot_to_disk_only's own "resolution"
#: note) now boots at 2560x1440 to exactly match harness.shots.vm.VmConfig's own
#: default resolution, which is what every file under harness/goldens/ was
#: actually captured at. Phase 1's own Calamares-wizard coordinates above this
#: point in the file (_NEXT_BUTTON, _SDDM_*_1920X1080, etc.) are UNCHANGED and
#: stay at 1920x1080 - only run_install()'s own screen never changes resolution
#: mid-run; log_into_sddm() always runs against a vm that has already gone
#: through reboot_to_disk_only(resolution=(2560, 1440)) by the time
#: harness/install/run.py calls it, so these are the only SDDM coordinates this
#: module actually uses today (the call sites below reference these names, not
#: the _1920X1080 ones).
#:
#: Measured the same "measured, not guessed" way as every coordinate in this
#: file: booted the EXISTING already-installed disk
#: (.build/install-disks/bios.qcow2 from the prior 1920x1080 run - its
#: filesystem content does not depend on display resolution, so no fresh
#: ~350s Calamares install was needed to get fresh greeter pixels) directly at
#: 2560x1440 via InstallVmConfig(iso_path=None, resolution=(2560, 1440)),
#: screendumped the resulting greeter, and pixel-scanned it with
#: harness.shots.pngio.read_png (same primitive _highlighted_row_y above uses).
#: Confirmed real, not scaled from the 1920x1080 values above: the Breeze SDDM
#: theme renders every widget at a FIXED pixel size regardless of screen
#: resolution (the user tile measured 311x39 physical pixels at 2560x1440,
#: against 310x38 at 1920x1080 - effectively identical, not the ~1.33x-larger
#: size naive linear scaling would predict) and simply re-centres the whole
#: login box on the bigger screen - confirmed independently on two separate
#: screendumps taken several seconds apart (identical bounding boxes both
#: times, pixel for pixel). Real measured bounding boxes (all three widgets
#: share the same left/right edges, x=1124..1435 - "Kuura Test" and the
#: "Password" placeholder are left-aligned text inside that span, so the
#: click x below is deliberately the shared horizontal centre, clear of any
#: text, rather than each widget's own narrower free-of-text sub-range):
#: user tile y=631..670 (centre 650), password field y=684..705 (centre
#: ~694), Login button y=719..744 (centre ~731, inside the button's full
#: fill even though "Login" text crosses that exact row - a click anywhere
#: within a button's bounds activates it, so this does not need to dodge
#: the label the way the field centres above deliberately dodge placeholder
#: text).
_SDDM_USER_TILE = (1280, 650)
_SDDM_PASSWORD_FIELD = (1280, 694)
_SDDM_LOGIN_BUTTON = (1280, 731)

#: Characters a username/password needs that harness.shots.keys.type_text() does not
#: accept, mapped the same way that module builds a chord (a tuple of qcodes) - port
#: of the now-superseded install_test.py's own _EXTRA_CHARS map (see this module's
#: own docstring for the "why" and its known limits).
EXTRA_CHARS: dict[str, tuple[str, ...]] = {
    "/": ("slash",),
    ".": ("dot",),
    "-": ("minus",),
    "_": ("shift", "minus"),
    ":": ("shift", "semicolon"),
    "=": ("equal",),
    "@": ("shift", "2"),
    ",": ("comma",),
}


class WizardError(RuntimeError):
    """
    Calamares did not reach Finish: a page's own expected element never appeared or
    settled within its own timeout, or the QMP connection was lost mid-install.
    """


@dataclass(frozen=True)
class WizardCredentials:
    """
    The one test account this run's install creates. Always chosen by the CALLER,
    never a fixed constant inside this module - an earlier ad-hoc recon run (before
    this permanent harness existed) left an installed disk with an account whose
    password nobody had recorded anywhere, which made that disk useless for a later
    login-based check; this interface design rules that mistake out structurally.

    Attributes:
        full_name: Real-name field on the Users page. Free text; Calamares does not
            validate it beyond non-empty.
        username: Login-name field. "desktop" is the recommended default: it makes
            the resulting installed account match harness.shots.guest.GuestUser()'s
            own built-in defaults exactly (name, uid 1000, same-named primary group
            - a fresh Arch install's first regular user already lands there under
            Calamares' real useradd defaults), so harness/install/run.py's phase-2
            GuestAgent connection needs no bespoke GuestUser construction. Validated
            the same shape Calamares' own username field requires: lowercase ASCII
            letters/digits/``-``/``_``, starting with a letter.
        password: Must pass libpwquality under Calamares' own default policy (the
            same constraint this project's own recon sessions already met in
            practice - see project memory for a password already proven to pass, to
            avoid re-discovering the policy's exact thresholds by trial and error).

    Raises:
        ValueError: username does not match the shape above (checked in
            ``__post_init__``, so a bad value fails before a slow boot, not mid-wizard).
    """

    full_name: str
    username: str
    password: str

    def __post_init__(self) -> None:
        # full_name/password get the same "could this real value ever be right"
        # scrutiny CLAUDE.md requires of every human-entered field, even though the
        # locked Raises: section above only names the username shape explicitly -
        # both still raise ValueError, so no caller-visible contract changes.
        if not isinstance(self.full_name, str) or not self.full_name.strip():
            raise ValueError("full_name must not be empty")
        if not isinstance(self.username, str) or not _USERNAME_PATTERN.match(self.username):
            raise ValueError(
                "username must start with a lowercase letter and contain only "
                "lowercase letters, digits, '-' or '_'"
            )
        if not isinstance(self.password, str) or not self.password:
            raise ValueError("password must not be empty")


@dataclass(frozen=True)
class WizardResult:
    """
    Outcome of one full wizard run.

    Attributes:
        finished: True only if the Finish page was actually seen (never inferred
            from elapsed time or the mere absence of an error).
        screenshots: Every screenshot taken along the way, in order - same "evidence,
            not just a verdict" spirit as harness/shots/capture.py's own manifest.
        duration_s: Wall time from the first Welcome screenshot to Finish.
        credentials: Echoes the input WizardCredentials, so a caller does not have to
            keep its own separate copy alive once the install phase has moved on.
    """

    finished: bool
    screenshots: list[Path]
    duration_s: float
    credentials: WizardCredentials


def _press_qcodes(screen: Any, qcodes: tuple[str, ...], hold_s: float = 0.05) -> None:
    """
    Press and release a sequence of raw QEMU qcodes (modifiers first), through
    ``harness.shots.qmp.Qmp``'s own PUBLIC primitives only (``key_event`` and
    ``execute``) - this is how EXTRA_CHARS' punctuation reaches the guest, since
    those qcodes (e.g. "semicolon") are not all names ``harness.shots.keys``
    accepts as a chord token (see this module's own docstring).

    Args:
        screen: The QMP client.
        qcodes: Keys in press order (modifiers first); same shape as one
            EXTRA_CHARS value.
        hold_s: Seconds the keys stay down.
    """
    screen.execute("input-send-event", {"events": [screen.key_event(code, True) for code in qcodes]})
    time.sleep(hold_s)
    screen.execute(
        "input-send-event", {"events": [screen.key_event(code, False) for code in reversed(qcodes)]}
    )


def _type_mixed(screen: Any, text: str, delay_s: float = 0.05) -> None:
    """
    Type text that may contain EXTRA_CHARS punctuation in addition to what
    ``harness.shots.keys.type_text()`` accepts on its own (letters, digits, spaces).

    Args:
        screen: The QMP client.
        text: The text to type, one character at a time.
        delay_s: Pause after every character so the guest keeps up.

    Raises:
        ValueError: a character is in neither keys.text_to_chords's alphabet nor
            EXTRA_CHARS.
    """
    for char in text:
        if char in EXTRA_CHARS:
            _press_qcodes(screen, EXTRA_CHARS[char])
        else:
            screen.type_text(char)
        time.sleep(delay_s)


def _fill_field(screen: Any, position: tuple[int, int], text: str) -> None:
    """
    Click a text field, select any existing content and replace it.

    Calamares pre-fills the login-name and computer-name fields from the full
    name as it is typed (confirmed live this phase); ``ctrl+a`` before typing is
    what makes this function correct for an already-populated field and a no-op
    (harmless) for an empty one, so every field can be filled the same way.

    Args:
        screen: The QMP client.
        position: Physical pixel coordinates inside the field.
        text: The replacement content.
    """
    screen.pointer_click(*position)
    time.sleep(0.2)
    screen.send_keys("ctrl+a")
    time.sleep(0.1)
    _type_mixed(screen, text)


def _settle_screen(
    screen: Any,
    work_dir: Path,
    *,
    interval_s: float,
    frames: int,
    timeout_s: float,
    reference: bytes | None = None,
) -> Path | None:
    """
    Poll screendumps until `frames` consecutive ones are byte-identical.

    Simplified relative of harness.shots.runner.Runner.settle (see this module's
    own docstring): frame stability alone, no guest-CPU-quiet probe (phase 1 has
    no guest agent to ask) and a coarser poll interval, since a Calamares page
    changes far less often than a running desktop does.

    Args:
        screen: The QMP client.
        work_dir: Scratch directory for the two alternating frame files.
        interval_s: Seconds between polls.
        frames: Consecutive identical frames required to call it stable.
        timeout_s: Seconds to wait in total.
        reference: Raw bytes of the frame from just before an action (a click, a
            key), if any. Guards against the same "startup trap"
            harness.shots.runner.Runner.settle documents: a page transition is not
            instantaneous, so without this, two polls taken before Calamares has
            finished redrawing would see the OLD page twice and report "settled"
            on it. When given, polls that still match `reference` do not count
            towards stability at all; the count only starts once a poll differs
            from it. None (the default) means no change is expected first (used
            for polls during the long install step, where the page is already
            mid-transition and "unstable" has a different cause: real work, not a
            not-yet-rendered click).

    Returns:
        The path of the last (stable) frame, or None if it never stabilised within
        timeout_s - NOT an exception, because during the real install this is the
        routine, expected outcome of one polling round (the caller loops).
    """
    start = time.monotonic()
    paths = (work_dir / "wizard-settle-a.png", work_dir / "wizard-settle-b.png")
    slot = 0
    previous: bytes | None = None
    stable = 0
    changed = reference is None
    while True:
        path = paths[slot]
        screen.screendump(path)
        data = path.read_bytes()
        if not changed:
            if data == reference:
                if time.monotonic() - start > timeout_s:
                    return None
                time.sleep(interval_s)
                continue
            changed = True
        stable = stable + 1 if previous is not None and data == previous else 1
        if stable >= frames:
            return path
        if time.monotonic() - start > timeout_s:
            return None
        previous = data
        time.sleep(interval_s)
        slot = 1 - slot


def _highlighted_row_y(frame: Path) -> int | None:
    """
    Find the vertical centre of the sidebar's highlighted row in a screenshot.

    Args:
        frame: A PNG screenshot of the full 1920x1080 screen.

    Returns:
        The physical-pixel y coordinate of the first (and normally only)
        contiguous run of rows at x=_SIDEBAR_X whose colour matches
        _SIDEBAR_HIGHLIGHT_RGB within _SIDEBAR_COLOR_TOLERANCE, or None if no such
        run exists (the Calamares window is not on screen, or is not at its
        expected horizontal position). The scan deliberately starts at
        _SIDEBAR_SCAN_Y_START, not 0 - see that constant's own docstring for the
        real, confirmed false-match this skips (the product icon above the page
        list).
    """
    width, height, rgb = read_png(frame)
    if _SIDEBAR_X >= width or _SIDEBAR_SCAN_Y_START >= height:
        return None
    start: int | None = None
    for y in range(_SIDEBAR_SCAN_Y_START, height):
        offset = (y * width + _SIDEBAR_X) * 3
        r, g, b = rgb[offset], rgb[offset + 1], rgb[offset + 2]
        match = (
            abs(r - _SIDEBAR_HIGHLIGHT_RGB[0]) <= _SIDEBAR_COLOR_TOLERANCE
            and abs(g - _SIDEBAR_HIGHLIGHT_RGB[1]) <= _SIDEBAR_COLOR_TOLERANCE
            and abs(b - _SIDEBAR_HIGHLIGHT_RGB[2]) <= _SIDEBAR_COLOR_TOLERANCE
        )
        if match and start is None:
            start = y
        elif not match and start is not None:
            return (start + y - 1) // 2
    return None if start is None else (start + height - 1) // 2


def _looks_like_desktop(frame: Path) -> bool:
    """
    Cheap, coarse check that a screenshot shows real desktop content (this
    project's own colourful wallpaper + panel) rather than a still-black boot or
    SDDM-splash frame.

    CONFIRMED NECESSARY against a real run this session, not a defensive guess:
    the initial "wait for the live desktop" step used to accept the first frame
    that simply stopped CHANGING for a few consecutive polls - but the SDDM boot
    splash's own loop animation has momentary pauses between cycles that are
    themselves perfectly stable for several seconds. A real run's own saved
    evidence screenshot (000-desktop.png) showed exactly this: a settle() that
    had already been accepted as "the desktop" was almost entirely black with
    only a thin cursor mark, and the wizard went on to send "alt+space" and type
    into a KRunner session that was never actually there to receive it - the
    next settle() then failed for an opaque reason (nothing was ever going to
    change, because nothing real had happened). Sampling roughly 2000 evenly
    spaced pixels and requiring a meaningful fraction of them to be non-near-
    black distinguishes "real wallpaper is on screen" from "still black/
    splash" cheaply, without needing the guest agent this phase does not have.

    Args:
        frame: A PNG screenshot of the full screen.

    Returns:
        True if enough of the sampled pixels are not near-black.
    """
    width, height, rgb = read_png(frame)
    total_pixels = width * height
    if total_pixels == 0:
        return False
    sample_step = max(1, total_pixels // 2000)
    bright = 0
    samples = 0
    for pixel_index in range(0, total_pixels, sample_step):
        offset = pixel_index * 3
        r, g, b = rgb[offset], rgb[offset + 1], rgb[offset + 2]
        samples += 1
        if r > 24 or g > 24 or b > 24:
            bright += 1
    return samples > 0 and (bright / samples) > 0.10


def _page_at(frame: Path, anchor_y: int) -> str | None:
    """
    Identify which Calamares page is active in a screenshot.

    Args:
        frame: A PNG screenshot.
        anchor_y: The y coordinate the Welcome page's own highlight was measured
            at THIS run (see run_install - calibrated once, right after Calamares
            launches, rather than trusting a hard-coded absolute value forever;
            the row spacing itself, _SIDEBAR_ROW_HEIGHT, is stable regardless).

    Returns:
        One of _PAGE_NAMES, or None if no sidebar highlight was found or it does
        not line up with any known row.
    """
    y = _highlighted_row_y(frame)
    if y is None:
        return None
    index = round((y - anchor_y) / _SIDEBAR_ROW_HEIGHT)
    if 0 <= index < len(_PAGE_NAMES):
        return _PAGE_NAMES[index]
    return None


def _sddm_password_field_visible(frame: Path) -> bool:
    """
    Cheap check: does this screenshot show SDDM's own password field?

    Args:
        frame: A PNG screenshot of the full screen, at whatever resolution
            phase 2 is currently booting at (2560x1440 - see _SDDM_PASSWORD_FIELD's
            own "PHASE 2 ONLY" comment; this function does not hardcode a
            resolution itself, only the coordinate constant it samples does).

    Returns:
        True if the pixel at the measured centre of SDDM's password field
        (_SDDM_PASSWORD_FIELD) is white - the field's own fill colour, confirmed
        by direct pixel sampling of a real post-install boot this phase (same
        "measured, not guessed" discipline as _SIDEBAR_HIGHLIGHT_RGB above).
        False once the greeter has been dismissed (the boot-progress screen or
        the real desktop occupies that pixel instead) or before it has rendered
        yet (still a plain dark background).
    """
    width, height, rgb = read_png(frame)
    x, y = _SDDM_PASSWORD_FIELD
    if x >= width or y >= height:
        return False
    offset = (y * width + x) * 3
    r, g, b = rgb[offset], rgb[offset + 1], rgb[offset + 2]
    return r > 240 and g > 240 and b > 240


def _list_skel_files(skel_dir: Path) -> list[str]:
    """
    List every regular file below ``skel_dir`` as a POSIX path relative to it.

    Args:
        skel_dir: Root of the test-only skeleton tree.

    Returns:
        Sorted relative paths (deterministic write order).

    Raises:
        WizardError: the directory is missing or contains a symlink or a special
            file (a link could make the harness read arbitrary host files).
    """
    if skel_dir.is_symlink() or not skel_dir.is_dir():
        raise WizardError("the test-only skeleton directory is missing")
    found: list[str] = []
    for path in skel_dir.rglob("*"):
        rel = path.relative_to(skel_dir).as_posix()
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise WizardError(f"unsupported entry in the test-only skeleton: {rel!r}")
        if path.is_file():
            found.append(rel)
    return sorted(found)


def inject_test_only_session_config(
    vm: InstallVm,
    guest_user: GuestUser,
    log: Callable[[str], None] = lambda line: None,
    skel_dir: Path = _GUEST_SKEL_DIR,
    merge_entries: list[skelmerge.ConfigEntry] | None = None,
    sample_tree_script: Path = _SAMPLE_TREE_SCRIPT,
) -> None:
    """
    Give a freshly installed target EXACTLY the test-only session configuration the
    screenshot harness image carries, so the diff-pass compares real product
    differences only.

    The shots image (harness/vm/Containerfile) is the real product plus three
    test-only layers plus a fixed sample folder tree; this function applies the same
    to the installed system:

    0. the fixed sample folder tree (Desktop, Documents, ... and their files) is
       created with the very script the image build runs. WHY: user-dirs.dirs (step 1)
       points the places at those folders, but a real install creates none of them, so
       the file manager showed "does not exist" errors and the desktop view did not
       show the empty Desktop folder the goldens have. Runs first because the script
       needs the home directory only, and as root (it chowns to the user);
    1. every regular file under ``harness/vm/guest/skel/`` is written to the same
       relative path in the desktop user's home (kwinrulesrc fixed window sizes,
       10-vm-rendering.conf software rendering, kwinoutputconfig.json output scale 2,
       and the determinism files such as powerdevilrc, kwalletrc, ksplashrc,
       plasmanotifyrc, baloofilerc, kxkbrc, plasma-localerc and user-dirs.dirs -
       whatever the directory holds). The list is derived from the directory, never
       hand-written, so it cannot drift from the image. By project rule that
       directory holds only files the product does not ship (a file the product
       also ships would replace the product's own version);
    2. every ``harness/vm/guest/skel-merge/`` entry (skelmerge.load_fragments) is
       merged key by key into the product's own file with kwriteconfig6, run AS THE
       DESKTOP USER (a root run would leave a root-owned file in the home). This
       runs after step 1 so a merge never races a wholesale copy;
    3. the target's timezone is set to UTC. TEST-ONLY: the goldens were captured
       with a UTC clock (the shots image links /etc/localtime to UTC), while a real
       install keeps the timezone Calamares picked, which made the clock read 08:00
       instead of 12:00. A real user must keep their own timezone, so this belongs
       to verification only. It must happen before login because the session reads
       the timezone when it starts.

    Why this exists (finding of 2026-10-17): the first full install-verify run failed
    all 22 states because the shots image and the real install differed in exactly
    this configuration (output scale, animations, timezone, determinism files), not
    in the product. Earlier (2026-10-16) only kwinrulesrc and 10-vm-rendering.conf
    were injected; the latter lives in environment.d (read by systemd itself before
    any user unit) because plasma-workspace/env scripts never reached the session of
    a crash-looping kwin_wayland - see docs/ISO_CONTRACT.md "Installed-system
    verification". All of it happens after the guest agent is reachable and BEFORE
    the SDDM login, because session configuration is read at login. Nothing here is
    shipped by any package.

    Ownership: GuestAgent.write_file creates parent directories as the desktop user
    and chowns each file to ``agent.user`` (name and group); the agent is created
    with this same ``guest_user`` (harness/install/boot.py), so the files belong to
    the installed account. kwriteconfig6 runs as that user too.

    Args:
        vm: A phase-2 InstallVm with a connected guest agent (the caller's own
            responsibility - this function does not start or wait for one).
        guest_user: The account whose home directory receives the configuration
            (the one run_install() created and log_into_sddm() logs into next).
        log: Progress callback, one line per step (same convention as this
            module's other public functions).
        skel_dir: Source tree for step 1 (tests only; defaults to the real one).
        merge_entries: Entries for step 2; None loads the real fragments (tests only).
        sample_tree_script: Script for step 0 (tests only; defaults to the real one).

    Raises:
        WizardError: vm.agent is None, a source file cannot be read, a fragment is
            malformed, a guest write or command fails, or a command exits non-zero.
            Messages are generic (relative file and key names only, no host paths).
    """
    agent = vm.agent
    if agent is None:
        raise WizardError("inject_test_only_session_config requires a connected guest agent")

    # --- 0. fixed sample folder tree (same script as the image build) ---------------
    try:
        script = sample_tree_script.read_bytes()
    except OSError as exc:
        raise WizardError("could not read the sample folder tree script") from exc
    try:
        agent.write_file(_GUEST_SAMPLE_SCRIPT, script)
        # The script validates /home/<user> itself; bash is run explicitly so the file
        # needs no execute bit. The script is deleted again so nothing is left behind.
        built = agent.exec([_BASH, _GUEST_SAMPLE_SCRIPT, guest_user.home, guest_user.name], timeout=60.0)
        agent.exec([_RM, "-f", "--", _GUEST_SAMPLE_SCRIPT])
    except (TimeoutError, ConnectionError, RuntimeError, OSError, ValueError) as exc:
        raise WizardError("could not create the sample folder tree in the guest") from exc
    if built.exit_code != 0:
        raise WizardError(f"creating the sample folder tree failed (exit {built.exit_code})")
    log("created the sample folder tree")

    # --- 1. wholesale test-only files ---------------------------------------------
    for rel in _list_skel_files(skel_dir):
        try:
            data = (skel_dir / rel).read_bytes()
        except OSError as exc:
            raise WizardError(f"could not read test-only session file {rel!r}") from exc
        dest = f"{guest_user.home}/{rel}"
        try:
            agent.write_file(dest, data)
        except (TimeoutError, ConnectionError, RuntimeError, OSError, ValueError) as exc:
            raise WizardError(f"could not write test-only session file {rel!r} to the guest") from exc
        log(f"injected test-only session file: {rel}")

    # --- 2. key-by-key merges into files the product ships -----------------------
    if merge_entries is None:
        try:
            merge_entries = skelmerge.load_fragments()
        except skelmerge.FragmentError as exc:
            raise WizardError("the test-only skel-merge fragments are invalid") from exc
    for entry in merge_entries:
        label = f"{entry.file} [{']['.join(entry.groups)}] {entry.key}"
        try:
            argv = skelmerge.kwriteconfig_argv(entry, guest_user.home)
            merged = agent.exec([RUNUSER, "-u", guest_user.name, "--", *argv])
        except (TimeoutError, ConnectionError, RuntimeError, OSError, ValueError) as exc:
            raise WizardError(f"could not apply test-only setting {label}") from exc
        if merged.exit_code != 0:
            raise WizardError(f"applying test-only setting {label} failed (exit {merged.exit_code})")
    log(f"merged {len(merge_entries)} test-only setting(s)")

    # --- 3. golden clock: UTC ------------------------------------------------------
    try:
        linked = agent.exec([_LN, "-sfn", "../usr/share/zoneinfo/UTC", "/etc/localtime"])
    except (TimeoutError, ConnectionError, RuntimeError, OSError) as exc:
        raise WizardError("could not set the target timezone to UTC") from exc
    if linked.exit_code != 0:
        raise WizardError(f"setting the target timezone to UTC failed (exit {linked.exit_code})")
    log("set target timezone to UTC")


def log_into_sddm(
    vm: InstallVm,
    credentials: WizardCredentials,
    screenshots_dir: Path,
    log: Callable[[str], None] = lambda line: None,
    timeout_s: float = 150.0,
    poll_interval_s: float = 1.0,
) -> Path:
    """
    Log into SDDM on a just-rebooted, just-installed target.

    Calamares' own users.conf has ``doAutologin: false`` (a deliberate security
    default, confirmed in that file - docs/ISO_CONTRACT.md "Installed-system
    verification") - a real install always reaches an SDDM greeter, never an
    already-running desktop session, so nothing downstream
    (harness.shots.runner.Runner.wait_for_desktop in particular, which only
    polls for a "plasmashell" process over the guest agent) can ever see a
    desktop without this step actually logging in first. Confirmed live this
    phase: a real install's own disk, booted standalone, sat at exactly this
    greeter for over a minute with nothing happening until something typed the
    password.

    Reuses this module's own primitives unchanged (_fill_field for the
    click+select-all+type sequence, WizardError for the failure type, the
    NNN-name.png screenshot-evidence convention) rather than inventing a
    parallel mechanism - this is "one more screen to get through with
    synthetic input", not a new category of thing.

    Args:
        vm: A started InstallVm, phase 2 (iso_path is None - the disk already
            installed and rebooted standalone via
            harness.install.boot.InstallVm.reboot_to_disk_only()). Needs no
            guest agent for this step itself (SDDM renders and accepts input
            long before any agent inside a not-yet-started session could be
            reachable); whether one is attached is entirely the caller's own
            concern, for whatever runs after this function returns.
        credentials: The very same account run_install() created on this disk
            earlier in phase 1; its password is what gets typed here.
        screenshots_dir: Where to save the milestone screenshots (created if
            missing) - same ``NNN-page-name.png`` convention run_install's own
            screenshots_dir uses.
        log: Progress callback, one line per milestone (same convention as
            run_install's own ``log`` parameter).
        timeout_s: Seconds to wait for the greeter to render before typing,
            and separately, after submitting, for it to be dismissed. 150s
            default: generous relative to every boot this phase has actually
            measured (guest agent alone was up within ~11s of QMP connecting;
            a fully rendered, settled greeter was confirmed within 75s), to
            absorb a slower host without being mistaken for a real hang.
        poll_interval_s: Seconds between polls in both waits.

    Returns:
        The first screenshot, after submitting the password, in which the
        greeter's own password field is no longer visible (i.e. the login
        actually succeeded - not inferred from elapsed time alone).

    Raises:
        WizardError: the greeter's password field never appeared within
            timeout_s, or still showed it timeout_s after submitting (wrong
            password, or the session failed to start) - this surfaces as a
            specific, named failure here rather than the opaque
            "the desktop shell did not start" a caller would otherwise only
            see much later, from wait_for_desktop(), with no way to tell a
            login failure apart from the session itself failing to start.
    """
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="sddm-work-"))
    counter = 0

    def shot(name: str) -> Path:
        nonlocal counter
        path = screenshots_dir / f"{counter:03d}-{name}.png"
        try:
            vm.qmp.screendump(path)
        except (TimeoutError, ConnectionError, RuntimeError, OSError) as exc:
            raise WizardError(f"could not take a screenshot ({name}): {exc}") from exc
        counter += 1
        return path

    poll_path = work_dir / "sddm-poll.png"

    def wait_until(expect_password_field: bool, budget_s: float, timeout_message: str) -> None:
        """Poll a throwaway screendump (not saved as evidence) until the password field's visibility matches."""
        deadline = time.monotonic() + budget_s
        while True:
            vm.qmp.screendump(poll_path)
            if _sddm_password_field_visible(poll_path) == expect_password_field:
                return
            if time.monotonic() > deadline:
                raise WizardError(timeout_message)
            time.sleep(poll_interval_s)

    try:
        log("waiting for the SDDM login screen")
        wait_until(True, timeout_s, f"the SDDM greeter's password field never appeared within {timeout_s:g}s")
        shot("sddm-greeter")

        log("logging into SDDM")
        # Select the user tile first - its teal highlight is theme styling, not
        # SDDM's own "current user" model state (see _SDDM_USER_TILE's own
        # comment: without this click, the Login request carries an empty
        # username and PAM rejects it as "user unknown", not as a bad password).
        vm.qmp.pointer_click(*_SDDM_USER_TILE)
        time.sleep(_ACTION_SETTLE_GUARD_S)
        _fill_field(vm.qmp, _SDDM_PASSWORD_FIELD, credentials.password)
        time.sleep(_ACTION_SETTLE_GUARD_S)
        shot("sddm-password-entered")
        # A real click on the measured "Log In" button, not Enter: the same
        # "click the real element, do not assume a keyboard shortcut" preference
        # this module's own _NEXT_BUTTON/_INSTALL_BUTTON clicks already follow for
        # Calamares, now that a real coordinate for this button has been measured
        # too (see _SDDM_LOGIN_BUTTON's own comment) - one fewer assumption on a
        # screen this module has not driven before.
        vm.qmp.pointer_click(*_SDDM_LOGIN_BUTTON)

        log("waiting for the SDDM greeter to be dismissed")
        try:
            wait_until(
                False,
                timeout_s,
                f"SDDM still shows its password field {timeout_s:g}s after submitting "
                "(wrong password, or the session failed to start)",
            )
        except WizardError:
            shot("sddm-login-timeout")
            raise
        frame = shot("sddm-dismissed")
        log("SDDM greeter dismissed")
        return frame
    except WizardError:
        raise
    except (TimeoutError, ConnectionError, RuntimeError, OSError, ValueError) as exc:
        raise WizardError(f"could not log into SDDM: {exc}") from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_install(
    vm: InstallVm,
    credentials: WizardCredentials,
    screenshots_dir: Path,
    log: Callable[[str], None] = lambda line: None,
) -> WizardResult:
    """
    Drive one already-booted live-ISO InstallVm through the entire wizard.

    Args:
        vm: A started InstallVm (harness/install/boot.py), phase 1 (iso_path was
            set, a blank disk attached) - this function neither starts nor stops it;
            the caller owns that (normally a ``with InstallVm(...) as vm:`` block).
        credentials: The account to create (see WizardCredentials - "desktop" as the
            username is recommended, not required).
        screenshots_dir: Where to write every intermediate screenshot (created if
            missing). Naming: ``NNN-page-name.png`` in wizard order, so a failure
            report sorts correctly without reading manifest metadata first.
        log: Progress callback, one line per page reached (same convention as
            harness/shots/capture.py's own ``log`` parameter).

    Returns:
        The result (see WizardResult).

    Raises:
        WizardError: a page's expected element never appeared/settled within its
            own budget, or the QMP connection was lost. A non-fatal-looking
            per-page issue is still raised here, not swallowed into
            ``finished=False`` - this is driving an installer, where "probably
            fine, keep going" is not an acceptable stance the way it can be for a
            single cosmetic screenshot state in the desktop harness.
    """
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="wizard-work-"))
    started = time.monotonic()
    screenshots: list[Path] = []
    counter = 0

    def shot(name: str) -> Path:
        nonlocal counter
        path = screenshots_dir / f"{counter:03d}-{name}.png"
        try:
            vm.qmp.screendump(path)
        except (TimeoutError, ConnectionError, RuntimeError, OSError) as exc:
            raise WizardError(f"could not take a screenshot ({name}): {exc}") from exc
        screenshots.append(path)
        counter += 1
        return path

    def settle(timeout_s: float, *, interval_s: float = 1.0, frames: int = 2, reference: Path | None = None) -> Path:
        ref_bytes = reference.read_bytes() if reference is not None else None
        frame = _settle_screen(
            vm.qmp, work_dir, interval_s=interval_s, frames=frames, timeout_s=timeout_s, reference=ref_bytes
        )
        if frame is None:
            # Evidence, not just a verdict (same spirit as harness/shots/capture.py's
            # own .FAILED.png): a plain "did not settle" message alone left no way to
            # tell, after the fact, WHAT was actually on screen when it happened - a
            # real gap found diagnosing this phase's own krunner-launch failures.
            try:
                shot("TIMEOUT-last-frame-seen")
            except WizardError:
                pass  # the timeout itself is the reportable failure either way
            raise WizardError(f"the screen did not settle within {timeout_s:g}s")
        return frame

    def wait_for_page(expected_page: str, current: Path, timeout_s: float) -> Path:
        """
        Poll (one new frame at a time, frames=1) until a frame's sidebar
        highlight identifies `expected_page`, or raise on timeout.

        frames=1 deliberately, not the usual 2-consecutive-identical default:
        Calamares pages commonly land with a text field already focused (Users'
        "Your Full Name", for instance), whose blinking caret alternates the
        screen between two states forever and can never produce two identical
        polls back to back - confirmed live this session (a settle() stuck on
        exactly this at the KRunner step, see run_install's own krunner-launch
        comment below for the full story). A single post-change frame is enough
        on its own merits too: _page_at's own sidebar-colour check, not pixel
        stability, is what actually verifies the right page was reached.

        This is a RETRY LOOP, not one settle() call, for a second real failure
        this session: the very first post-change frame is not always the final
        one - it can be a transient partial-render (confirmed live: a run
        reached "welcome" correctly, clicked Next, and the very next settled
        frame matched no page at all, "sidebar shows None" - an in-between
        repaint, not a bad click). Each failed recognition becomes the new
        reference for one more "wait for the next change" poll, so a short
        transition animation is simply walked through frame by frame rather
        than accepted or rejected on the first sample.

        Args:
            expected_page: The page name that must eventually be seen.
            current: The frame from just before whatever action (click, Enter)
                is expected to lead to `expected_page`.
            timeout_s: Total seconds allowed across every retry.

        Returns:
            The first frame recognized as `expected_page`.

        Raises:
            WizardError: `expected_page` was never recognized in time (message
                names the last page that WAS recognized, if any, or None).
        """
        deadline = time.monotonic() + timeout_s
        reference = current
        last_page: str | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                try:
                    shot(f"TIMEOUT-expected-{expected_page}")
                except WizardError:
                    pass
                raise WizardError(
                    f"expected the {expected_page!r} page within {timeout_s:g}s "
                    f"(last recognized page: {last_page!r})"
                )
            time.sleep(_ACTION_SETTLE_GUARD_S)
            polled = _settle_screen(
                vm.qmp, work_dir, interval_s=0.5, frames=1, timeout_s=remaining, reference=reference.read_bytes()
            )
            if polled is None:
                continue  # no further change at all before the deadline; loop will report it above
            page = _page_at(polled, anchor_y)
            if page == expected_page:
                return polled
            last_page = page
            reference = polled

    def click_and_advance(position: tuple[int, int], expected_page: str, current: Path, *, timeout_s: float = 30.0) -> Path:
        """Click a point known to change the page, then wait_for_page() it."""
        vm.qmp.pointer_click(*position)
        return wait_for_page(expected_page, current, timeout_s)

    try:
        log("waiting for the live desktop")
        # No guest agent in phase 1 (see module docstring): the only available
        # signal that the live session has finished booting is the screen
        # settling - but "stopped changing" alone is not enough (confirmed live
        # this session: it can false-positive on a momentary pause inside the
        # SDDM boot splash's own loop animation, long before Plasma is actually
        # up). Keep settling, each time requiring a further CHANGE from the
        # previous attempt, until a settled frame also looks like real desktop
        # content (_looks_like_desktop), bounded by the overall boot timeout.
        boot_deadline = time.monotonic() + vm.config.boot_timeout_s
        frame = None
        while True:
            remaining = boot_deadline - time.monotonic()
            if remaining <= 0:
                raise WizardError(
                    f"the live desktop never showed real content within {vm.config.boot_timeout_s:g}s "
                    "(still black/splash on every settled frame)"
                )
            frame = settle(remaining, interval_s=3.0, frames=3, reference=frame)
            if _looks_like_desktop(frame):
                break
            log("waiting for the live desktop: screen settled but still looks like boot/splash, continuing to wait")
        frame = shot("desktop")

        log("launching Calamares (KRunner -> pkexec calamares)")
        # frames=1 on both of these: confirmed live this session that KRunner's own
        # search box has a blinking text caret once it has focus (present as soon
        # as the box itself opens, and again as soon as typing starts) - exact
        # 2-consecutive-identical-frame stability can alias against a poll
        # interval close to the blink's own period and never resolve at all (a
        # real run reproduced this exactly: two screendumps one second apart came
        # back byte-identical to EACH OTHER at the 1s and 4s marks, but a 2s-mark
        # screendump in between did not match either - the classic on/off blink
        # signature, confirmed by comparing sha256 across three captured frames).
        # One frame that differs from the pre-action reference is sufficient here;
        # nothing downstream needs pixel-perfect settling of a blinking cursor.
        vm.qmp.send_keys("alt+space")
        time.sleep(_ACTION_SETTLE_GUARD_S)
        frame = settle(10.0, frames=1, reference=frame)
        vm.qmp.type_text("pkexec calamares")
        time.sleep(_ACTION_SETTLE_GUARD_S)
        frame = settle(5.0, frames=1, reference=frame)
        vm.qmp.send_keys("enter")
        # Retry loop, same shape as wait_for_page below (anchor_y does not exist
        # yet - THIS frame is what calibrates it, see _page_at's own docstring -
        # so wait_for_page itself cannot be used here): keep requiring a further
        # change past any frame that is not yet a recognizable Calamares sidebar,
        # so a transient partial repaint during Calamares' own startup (pkexec
        # authentication + QML loading) cannot be mistaken for "it never launched".
        calamares_deadline = time.monotonic() + 60.0
        reference = frame
        anchor_y: int | None = None
        while True:
            remaining = calamares_deadline - time.monotonic()
            if remaining <= 0:
                shot("calamares-launch-failed")
                raise WizardError("Calamares did not launch (no sidebar highlight found) within 60s")
            frame = settle(remaining, interval_s=2.0, frames=2, reference=reference)
            anchor_y = _highlighted_row_y(frame)
            if anchor_y is not None:
                break
            reference = frame
        frame = shot("welcome")
        log("welcome")

        for page in ("location", "keyboard"):
            frame = click_and_advance(_NEXT_BUTTON, page, frame)
            frame = shot(page)
            log(page)

        frame = click_and_advance(_NEXT_BUTTON, "partitions", frame)
        frame = shot("partitions")
        log("partitions")

        vm.qmp.pointer_click(*_ERASE_DISK_RADIO)
        frame = settle(10.0, reference=frame)
        frame = shot("partitions-erase-selected")

        frame = click_and_advance(_NEXT_BUTTON, "users", frame)
        frame = shot("users")
        log("users")

        _fill_field(vm.qmp, _FULL_NAME_FIELD, credentials.full_name)
        _fill_field(vm.qmp, _USERNAME_FIELD, credentials.username)
        _fill_field(vm.qmp, _PASSWORD_FIELD, credentials.password)
        _fill_field(vm.qmp, _REPEAT_PASSWORD_FIELD, credentials.password)
        # frames=1: the repeat-password field still has a blinking caret at the
        # end of the masked text after the last keystroke - same blink-aliasing
        # risk _NEXT_BUTTON clicks already guard against via click_and_advance.
        time.sleep(_ACTION_SETTLE_GUARD_S)
        frame = settle(10.0, frames=1, reference=frame)
        frame = shot("users-filled")

        frame = click_and_advance(_NEXT_BUTTON, "summary", frame)
        frame = shot("summary")
        log("summary")

        vm.qmp.pointer_click(*_INSTALL_BUTTON)
        time.sleep(_ACTION_SETTLE_GUARD_S)
        # frames=1: only confirming the Install page itself has appeared: its own
        # progress bar/log text then changes continuously and for real (not a
        # blink) while the install runs, which the long poll loop below handles
        # with its own, deliberately stricter settle.
        frame = settle(30.0, frames=1, reference=frame)
        shot("install-started")
        log("install started")

        deadline = time.monotonic() + INSTALL_TIMEOUT_S
        finished_frame: Path | None = None
        nudge_toggle = False
        while time.monotonic() < deadline:
            # REAL, CONFIRMED FINDING this session (not theoretical): the live
            # session's idle timeout locks the screen (KScreenLocker) after a few
            # minutes of no input - observed directly during a real, otherwise
            # untouched install wait. The live user's password is deliberately
            # LOCKED (passwd -l, docs/ISO_CONTRACT.md "Live session"), so once that
            # lock screen appears there is no password that can ever dismiss it -
            # every subsequent screendump would show the lock screen forever
            # instead of Calamares, and this loop would correctly but uselessly
            # time out. A harmless, tiny pointer move resets the idle timer without
            # clicking anything or disturbing Calamares' own state; sent once per
            # iteration here (well under the observed lock delay) is enough to
            # prevent the lock from ever triggering during a real install wait.
            nudge_toggle = not nudge_toggle
            vm.qmp.pointer_move(10, 10 if nudge_toggle else 11)
            remaining = deadline - time.monotonic()
            frame = _settle_screen(vm.qmp, work_dir, interval_s=4.0, frames=2, timeout_s=min(90.0, remaining))
            if frame is None:
                log("install: still in progress")
                continue
            page = _page_at(frame, anchor_y)
            log(f"install: sidebar shows {page!r}")
            if page == "finish":
                finished_frame = frame
                break
        if finished_frame is None:
            shot("install-timeout")
            raise WizardError(f"Calamares did not reach the Finish page within {INSTALL_TIMEOUT_S:g}s")
        shot("finish")
        log("finish")

        return WizardResult(
            finished=True,
            screenshots=list(screenshots),
            duration_s=round(time.monotonic() - started, 1),
            credentials=credentials,
        )
    except WizardError:
        raise
    except (TimeoutError, ConnectionError, RuntimeError, OSError, ValueError) as exc:
        raise WizardError(f"the wizard could not continue: {exc}") from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

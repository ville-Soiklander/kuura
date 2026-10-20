"""
Tests for harness.install.wizard's genuinely pure/testable pieces:
WizardCredentials.__post_init__ validation, and the sidebar pixel-identity
helpers (_highlighted_row_y/_page_at) against small, synthetically built PNGs
(harness.shots.pngio, stdlib only - no QEMU, no real Calamares screenshot
needed to exercise the pixel logic itself). Driving a real wizard run end to
end needs a real QEMU/Calamares session and is out of scope here, matching the
same "do not mock full QEMU subprocess behaviour" precedent as
harness/tests/test_install_boot.py and the existing harness/shots/vm.py tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.install.wizard import (
    EXTRA_CHARS,
    _SDDM_PASSWORD_FIELD,
    WizardCredentials,
    WizardError,
    _click_install_and_confirm,
    _highlighted_row_y,
    _looks_like_desktop,
    _page_at,
    _press_qcodes,
    _sddm_password_field_visible,
    _settle_screen,
    _type_mixed,
)
from harness.shots.pngio import write_png

DARK = (21, 24, 28)
HIGHLIGHT = (79, 179, 200)


def make_sidebar_png(path: Path, width: int, height: int, highlight_rows: tuple[int, int] | None) -> None:
    """
    Build a small PNG that is uniformly dark except one highlighted row band, the
    same shape _highlighted_row_y scans for in a real Calamares screenshot.

    Args:
        path: Where to write the PNG.
        width: Image width (must be > the module's _SIDEBAR_X for the highlight
            to be visible to the scan).
        height: Image height.
        highlight_rows: (y0, y1) inclusive band to paint HIGHLIGHT, or None for a
            plain dark image with no highlight anywhere.
    """
    pixels = bytearray(width * height * 3)
    for y in range(height):
        color = HIGHLIGHT if highlight_rows and highlight_rows[0] <= y <= highlight_rows[1] else DARK
        row_start = y * width * 3
        pixels[row_start : row_start + width * 3] = bytes(color) * width
    write_png(path, width, height, bytes(pixels))


# --- WizardCredentials ------------------------------------------------------------------


def test_wizard_credentials_accepts_a_sane_account() -> None:
    """The documented recommended account (full name, "desktop", a real password) is accepted."""
    creds = WizardCredentials(full_name="Kuura Test", username="desktop", password="kuura123test")
    assert creds.username == "desktop"


@pytest.mark.parametrize("username", ["", "Desktop", "1desktop", "desk top", "desk.top", "désktop"])
def test_wizard_credentials_rejects_bad_usernames(username: str) -> None:
    """Anything that is not lowercase-letter-first, then letters/digits/-/_, is a ValueError."""
    with pytest.raises(ValueError, match="username"):
        WizardCredentials(full_name="Kuura Test", username=username, password="kuura123test")


@pytest.mark.parametrize("username", ["desktop", "d", "d-e_sk2top", "a1"])
def test_wizard_credentials_accepts_the_shape_boundary(username: str) -> None:
    """A single letter, and a name mixing every allowed character class, both validate."""
    WizardCredentials(full_name="X", username=username, password="pw")


def test_wizard_credentials_rejects_an_empty_full_name() -> None:
    """A blank or whitespace-only full name is rejected (it ends up as a real account's display name)."""
    with pytest.raises(ValueError, match="full_name"):
        WizardCredentials(full_name="   ", username="desktop", password="pw")


def test_wizard_credentials_rejects_an_empty_password() -> None:
    """No password at all is rejected before any boot, not mid-wizard."""
    with pytest.raises(ValueError, match="password"):
        WizardCredentials(full_name="X", username="desktop", password="")


# --- EXTRA_CHARS / _type_mixed / _press_qcodes ------------------------------------------


class FakeScreen:
    """Records every key_event/execute/type_text call, standing in for Qmp."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.typed: list[str] = []

    def key_event(self, qcode: str, down: bool) -> dict:
        return {"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": qcode}}}

    def execute(self, command: str, arguments: dict) -> None:
        assert command == "input-send-event"
        self.events.append(arguments)

    def type_text(self, text: str) -> None:
        if len(text) != 1 or not (text.isalnum() or text == " "):
            raise ValueError(f"would not reach keys.type_text's own alphabet: {text!r}")
        self.typed.append(text)


def test_extra_chars_covers_the_documented_punctuation() -> None:
    """The ported map still has exactly the characters the module docstring promises."""
    assert set(EXTRA_CHARS) == set("/.-_:=@,")


def test_press_qcodes_sends_down_then_up_in_press_then_reverse_order() -> None:
    """A chord like EXTRA_CHARS["_"] = ("shift", "minus") presses shift then minus, releases minus then shift."""
    screen = FakeScreen()
    _press_qcodes(screen, ("shift", "minus"), hold_s=0.0)
    down, up = screen.events
    assert [e["data"]["key"]["data"] for e in down["events"]] == ["shift", "minus"]
    assert all(e["data"]["down"] for e in down["events"])
    assert [e["data"]["key"]["data"] for e in up["events"]] == ["minus", "shift"]
    assert not any(e["data"]["down"] for e in up["events"])


def test_type_mixed_routes_plain_characters_through_type_text_and_the_rest_through_extra_chars() -> None:
    """A username-shaped string mixing letters/digits with EXTRA_CHARS punctuation is fully consumed."""
    screen = FakeScreen()
    _type_mixed(screen, "a1_b", delay_s=0.0)
    assert screen.typed == ["a", "1", "b"]
    # "_" is EXTRA_CHARS["_"] = ("shift", "minus") -> one down event, one up event.
    assert len(screen.events) == 2


def test_type_mixed_rejects_a_character_in_neither_alphabet() -> None:
    """A character this module has no mapping for at all surfaces as a ValueError, not silently dropped."""
    screen = FakeScreen()
    with pytest.raises(ValueError):
        _type_mixed(screen, "a$b", delay_s=0.0)


# --- _settle_screen ----------------------------------------------------------------------


class FakeSettleScreen:
    """Returns pre-scripted frame bytes on each screendump() call, in order."""

    def __init__(self, frames: list[bytes]) -> None:
        self._frames = list(frames)

    def screendump(self, path: Path) -> None:
        path.write_bytes(self._frames.pop(0))


def test_settle_screen_returns_the_frame_once_stable(tmp_path: Path) -> None:
    """Two consecutive identical frames (no reference) count as settled."""
    screen = FakeSettleScreen([b"A", b"B", b"B"])
    frame = _settle_screen(screen, tmp_path, interval_s=0.0, frames=2, timeout_s=5.0)
    assert frame is not None and frame.read_bytes() == b"B"


def test_settle_screen_times_out_returning_none_not_an_exception(tmp_path: Path) -> None:
    """Perpetually changing frames never settle; the caller gets None, not a raised error."""
    # interval_s/timeout_s bound the loop to only a handful of iterations; the frame
    # list is generously sized so a timing jitter cannot ever exhaust it first.
    screen = FakeSettleScreen([f"frame-{i}".encode() for i in range(100)])
    frame = _settle_screen(screen, tmp_path, interval_s=0.01, frames=2, timeout_s=0.03)
    assert frame is None


def test_settle_screen_ignores_frames_that_still_match_the_reference(tmp_path: Path) -> None:
    """The 'startup trap': polls that still match the pre-action reference never count towards stability."""
    # OLD stays on screen for two polls (would wrongly look "stable" without the
    # reference guard), then changes to NEW and settles.
    screen = FakeSettleScreen([b"OLD", b"OLD", b"NEW", b"NEW"])
    frame = _settle_screen(screen, tmp_path, interval_s=0.0, frames=2, timeout_s=5.0, reference=b"OLD")
    assert frame is not None and frame.read_bytes() == b"NEW"


# --- _looks_like_desktop ------------------------------------------------------------------


def make_solid_png(path: Path, width: int, height: int, color: tuple[int, int, int]) -> None:
    """Build a uniformly coloured PNG (stand-in for a boot splash or a real wallpaper)."""
    write_png(path, width, height, bytes(color) * (width * height))


def test_looks_like_desktop_rejects_a_black_splash_frame(tmp_path: Path) -> None:
    """A still-black boot/SDDM-splash frame (confirmed live this session, see the
    function's own docstring) must NOT be mistaken for a real, settled desktop."""
    path = tmp_path / "black.png"
    make_solid_png(path, 200, 200, (0, 0, 0))
    assert _looks_like_desktop(path) is False


def test_looks_like_desktop_accepts_a_colourful_frame(tmp_path: Path) -> None:
    """A frame that is mostly a vivid, non-near-black colour (the real wallpaper's own shape) passes."""
    path = tmp_path / "wallpaper.png"
    make_solid_png(path, 200, 200, (60, 90, 180))
    assert _looks_like_desktop(path) is True


def test_looks_like_desktop_rejects_a_mostly_black_frame_with_a_small_bright_spot(tmp_path: Path) -> None:
    """A small bright logo/spinner on an otherwise black splash is not enough to pass (matches the
    real SDDM splash shape: a small centred icon, nowhere near 10% of the screen)."""
    width, height = 200, 200
    pixels = bytearray(width * height * 3)
    # Paint a small 10x10 bright square (100 px, 0.25% of the 40000-pixel image).
    for y in range(10):
        for x in range(10):
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = bytes((255, 255, 255))
    path = tmp_path / "splash-with-spinner.png"
    write_png(path, width, height, bytes(pixels))
    assert _looks_like_desktop(path) is False


# --- _highlighted_row_y / _page_at --------------------------------------------------------


def test_highlighted_row_y_finds_the_band_centre(tmp_path: Path) -> None:
    """A single highlighted band's reported y is its own true vertical centre."""
    path = tmp_path / "frame.png"
    make_sidebar_png(path, width=700, height=700, highlight_rows=(310, 348))
    assert _highlighted_row_y(path) == 329


def test_highlighted_row_y_returns_none_without_any_highlight(tmp_path: Path) -> None:
    """A plain, uniformly dark frame (no sidebar at all, e.g. the bare desktop) finds nothing."""
    path = tmp_path / "frame.png"
    make_sidebar_png(path, width=700, height=700, highlight_rows=None)
    assert _highlighted_row_y(path) is None


def test_highlighted_row_y_returns_none_when_the_sidebar_column_is_off_frame(tmp_path: Path) -> None:
    """A frame narrower than the sidebar's own sample column cannot be scanned; None, not an IndexError."""
    path = tmp_path / "frame.png"
    make_sidebar_png(path, width=100, height=700, highlight_rows=(310, 320))
    assert _highlighted_row_y(path) is None


def test_highlighted_row_y_ignores_a_highlight_before_the_scan_start(tmp_path: Path) -> None:
    """
    REGRESSION TEST for a real, confirmed bug this session: Calamares' own
    circular product-icon logo sits above the page list and happens to fall
    within _SIDEBAR_COLOR_TOLERANCE of _SIDEBAR_HIGHLIGHT_RGB at x=_SIDEBAR_X
    (measured directly from a real screenshot: (59, 173, 194) against
    (79, 179, 200)) - scanning from y=0 found the icon FIRST on every single
    frame and returned the same wrong-but-consistent y every time, so a real
    install run reached the Location page (confirmed by its own saved
    screenshot) while _page_at kept reporting "welcome" and the wizard timed
    out. A highlight band placed entirely above _SIDEBAR_SCAN_Y_START must
    be invisible to the scan.
    """
    path = tmp_path / "icon-only.png"
    make_sidebar_png(path, width=700, height=700, highlight_rows=(256, 273))
    assert _highlighted_row_y(path) is None


def test_page_at_maps_offsets_to_the_right_named_page(tmp_path: Path) -> None:
    """Welcome (index 0) through finish (index 7), each 39px apart from a measured anchor, resolve by name."""
    anchor = 350
    names = ("welcome", "location", "keyboard", "partitions", "users", "summary", "install", "finish")
    for index, name in enumerate(names):
        path = tmp_path / f"{name}.png"
        center = anchor + index * 39
        make_sidebar_png(path, width=700, height=900, highlight_rows=(center - 19, center + 19))
        assert _page_at(path, anchor) == name, name


def test_page_at_returns_none_for_an_offset_outside_every_known_row(tmp_path: Path) -> None:
    """A highlight far below the last row (e.g. a stray match) does not get attributed to "finish" by accident."""
    path = tmp_path / "frame.png"
    make_sidebar_png(path, width=700, height=900, highlight_rows=(850, 870))
    assert _page_at(path, anchor_y=350) is None


# --- _sddm_password_field_visible --------------------------------------------------------


def test_sddm_password_field_visible_true_when_white(tmp_path: Path) -> None:
    """A screenshot white at the measured field centre reads as "the greeter's password field is showing"."""
    path = tmp_path / "greeter.png"
    make_solid_png(path, width=1920, height=1080, color=(255, 255, 255))
    assert _sddm_password_field_visible(path) is True


def test_sddm_password_field_visible_false_on_dark_background(tmp_path: Path) -> None:
    """Still on a plain dark boot screen (greeter not rendered yet) reads as not-visible, not a crash."""
    path = tmp_path / "boot.png"
    make_solid_png(path, width=1920, height=1080, color=(28, 32, 37))
    assert _sddm_password_field_visible(path) is False


def test_sddm_password_field_visible_false_on_bright_but_non_white_desktop(tmp_path: Path) -> None:
    """A bright but not-white pixel (e.g. real desktop wallpaper/content) must not false-match the white field."""
    path = tmp_path / "desktop.png"
    make_solid_png(path, width=1920, height=1080, color=(200, 120, 60))
    assert _sddm_password_field_visible(path) is False


def test_sddm_password_field_visible_false_when_frame_too_small(tmp_path: Path) -> None:
    """A frame smaller than the measured coordinate cannot be sampled; False, not an IndexError."""
    path = tmp_path / "tiny.png"
    make_solid_png(path, width=100, height=100, color=(255, 255, 255))
    assert _sddm_password_field_visible(path) is False


def test_sddm_password_field_coordinate_is_within_full_hd() -> None:
    """Sanity check on the measured constant itself: it must sit inside the locked 1920x1080 frame."""
    x, y = _SDDM_PASSWORD_FIELD
    assert 0 <= x < 1920
    assert 0 <= y < 1080


# --- _click_install_and_confirm -----------------------------------------------------------

_ANCHOR = 350


class FakeInstallScreen:
    """
    Screen that shows the Summary page until an Install click is accepted.

    The first `lost_clicks` clicks are dropped (the screen only gets an unrelated
    pointer-redraw change), later ones switch to the Install page.
    """

    def __init__(self, tmp_path: Path, lost_clicks: int, accept: bool = True) -> None:
        self.clicks = 0
        self._lost = lost_clicks
        self._accept = accept
        self._tmp = tmp_path
        self._noise = 0
        self.summary = self._page_bytes("summary", 0)
        self.install = self._page_bytes("install", 0)

    def _page_bytes(self, name: str, variant: int) -> bytes:
        center = _ANCHOR + _PAGE_ORDER.index(name) * 39
        path = self._tmp / f"fake-{name}-{variant}.png"
        make_sidebar_png(path, width=700, height=900 + variant, highlight_rows=(center - 19, center + 19))
        return path.read_bytes()

    def pointer_click(self, x: int, y: int) -> None:
        self.clicks += 1
        self._noise += 1  # an unrelated change (pointer redraw) follows every click

    def screendump(self, path: Path) -> None:
        if self._accept and self.clicks > self._lost:
            path.write_bytes(self.install)
        else:
            path.write_bytes(self._page_bytes("summary", self._noise))


_PAGE_ORDER = ("welcome", "location", "keyboard", "partitions", "users", "summary", "install", "finish")


def _summary_frame(screen: FakeInstallScreen, tmp_path: Path) -> Path:
    frame = tmp_path / "summary-ref.png"
    frame.write_bytes(screen.summary)
    return frame


def test_install_click_succeeds_first_time(tmp_path: Path) -> None:
    """An accepted click returns the frame showing the Install page after one click."""
    screen = FakeInstallScreen(tmp_path, lost_clicks=0)
    frame = _click_install_and_confirm(
        screen, tmp_path, _ANCHOR, _summary_frame(screen, tmp_path), wait_s=2.0, guard_s=0.0
    )
    assert _page_at(frame, _ANCHOR) == "install"
    assert screen.clicks == 1


def test_install_click_lost_once_is_retried_and_succeeds(tmp_path: Path) -> None:
    """
    REGRESSION: a dropped click plus an unrelated screen change used to count as
    "install started". The click is now repeated until the sidebar leaves Summary.
    """
    screen = FakeInstallScreen(tmp_path, lost_clicks=1)
    frame = _click_install_and_confirm(
        screen, tmp_path, _ANCHOR, _summary_frame(screen, tmp_path), wait_s=1.5, guard_s=0.0
    )
    assert _page_at(frame, _ANCHOR) == "install"
    assert screen.clicks == 2


def test_install_click_never_taking_effect_fails_fast_after_bounded_attempts(tmp_path: Path) -> None:
    """A click that never works raises WizardError after exactly `attempts` clicks, not after 2400 s."""
    screen = FakeInstallScreen(tmp_path, lost_clicks=0, accept=False)
    with pytest.raises(WizardError, match="3 attempts"):
        _click_install_and_confirm(
            screen, tmp_path, _ANCHOR, _summary_frame(screen, tmp_path), attempts=3, wait_s=0.6, guard_s=0.0
        )
    assert screen.clicks == 3

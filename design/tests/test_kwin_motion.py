"""
Tests for the KWin sliding-popups motion generator (design.generators.kwin_motion).

The golden text below is written out by hand from the module's own locked output
spec (design/generators/kwin_motion.py's docstring), not computed with the
generator itself - a wrong section name, a wrong key or a dropped/leaked value
cannot hide behind shared code, matching design/tests/test_cpp_header.py's and
design/tests/test_fontconfig.py's own convention.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from design.generators.kwin_motion import render_slidingpopups_fragment

# The real design tokens live next to the tests' parent package (design/).
REAL_TOKENS_PATH = Path(__file__).resolve().parent.parent / "tokens.json"

# A small synthetic token tree with a distinct, easy-to-spot duration value, so a
# test cannot pass by coincidentally matching the real tokens.json's own value.
SYNTHETIC_TOKENS = {"motion": {"duration": {"fast": 222}}}

SYNTHETIC_GOLDEN = "[Effect-slidingpopups]\nSlideInTime=222\nSlideOutTime=222\n"


def test_golden_output_synthetic_tokens() -> None:
    """The entire ini fragment equals the hand-written golden text above."""
    assert render_slidingpopups_fragment(SYNTHETIC_TOKENS) == SYNTHETIC_GOLDEN


def test_output_has_exactly_one_section_header() -> None:
    """Exactly one `[Effect-slidingpopups]` header - this is a fragment, not a full ini."""
    text = render_slidingpopups_fragment(SYNTHETIC_TOKENS)
    assert text.count("[Effect-slidingpopups]") == 1
    assert text.startswith("[Effect-slidingpopups]\n")


def test_slide_in_and_slide_out_share_the_same_value() -> None:
    """
    Both keys read from the single `fast` bucket - this project's tokens.json has no
    separate enter/exit duration, see the module docstring for why both keys
    intentionally share one value.
    """
    text = render_slidingpopups_fragment(SYNTHETIC_TOKENS)
    assert "SlideInTime=222" in text
    assert "SlideOutTime=222" in text


def test_output_ends_with_single_trailing_newline() -> None:
    """Exactly one trailing newline, no CR (matches the other generators' convention)."""
    text = render_slidingpopups_fragment(SYNTHETIC_TOKENS)
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "\r" not in text


def test_missing_fast_key_raises_keyerror() -> None:
    """A tokens dict missing motion.duration.fast must raise KeyError, not silently
    default or crash with a different exception, per the function's own docstring."""
    with pytest.raises(KeyError):
        render_slidingpopups_fragment({"motion": {"duration": {}}})


def test_missing_duration_key_raises_keyerror() -> None:
    """Same as above, one level higher up the path."""
    with pytest.raises(KeyError):
        render_slidingpopups_fragment({"motion": {}})


def test_missing_motion_key_raises_keyerror() -> None:
    """Same as above, at the top-level key itself."""
    with pytest.raises(KeyError):
        render_slidingpopups_fragment({})


def test_output_is_deterministic() -> None:
    """Identical inputs (even from a deep copy) give byte-identical output."""
    first = render_slidingpopups_fragment(SYNTHETIC_TOKENS)
    second = render_slidingpopups_fragment(copy.deepcopy(SYNTHETIC_TOKENS))
    assert first == second


def test_real_tokens_produce_the_real_fast_value() -> None:
    """
    Sanity check against the real, committed tokens.json: today's real
    motion.duration.fast value (180ms) shows up in both keys, proving this
    reads the real token rather than being a no-op or a hard-coded constant.
    """
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    fast_ms = real_tokens["motion"]["duration"]["fast"]
    text = render_slidingpopups_fragment(real_tokens)
    assert text == f"[Effect-slidingpopups]\nSlideInTime={fast_ms}\nSlideOutTime={fast_ms}\n"


def test_changing_fast_duration_changes_both_keys_identically() -> None:
    """Mutating motion.duration.fast changes both SlideInTime and SlideOutTime to the
    new value - they must never drift apart from each other."""
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    changed = copy.deepcopy(real_tokens)
    changed["motion"]["duration"]["fast"] = 999

    text = render_slidingpopups_fragment(changed)
    assert text == "[Effect-slidingpopups]\nSlideInTime=999\nSlideOutTime=999\n"


def test_changing_other_duration_buckets_does_not_affect_output() -> None:
    """instant/base/slow are never read by this generator - only `fast` matters."""
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    original = render_slidingpopups_fragment(real_tokens)

    changed = copy.deepcopy(real_tokens)
    changed["motion"]["duration"]["instant"] = 1
    changed["motion"]["duration"]["base"] = 2
    changed["motion"]["duration"]["slow"] = 3

    assert render_slidingpopups_fragment(changed) == original

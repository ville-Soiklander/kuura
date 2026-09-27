"""Tests for harness.shots.keys: chord parsing and typed text (no VM involved)."""

from __future__ import annotations

import pytest

from harness.shots.keys import MAX_TEXT_LENGTH, parse_chord, text_to_chords


def test_parse_chord_examples_from_the_contract() -> None:
    """
    The four example chords of the contract map to the expected qcodes.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: if a chord maps to something else.
    """
    assert parse_chord("meta+w") == ("meta_l", "w")
    assert parse_chord("alt+space") == ("alt", "spc")
    assert parse_chord("escape") == ("esc",)
    assert parse_chord("ctrl+shift+f") == ("ctrl", "shift", "f")


def test_parse_chord_ignores_case_and_spaces() -> None:
    """
    Names are case-insensitive and padding around ``+`` does not matter.

    Returns:
        None.
    """
    assert parse_chord(" Meta + W ") == ("meta_l", "w")
    assert parse_chord("ALT+SPACE") == ("alt", "spc")


@pytest.mark.parametrize("alias", ["meta", "super", "win"])
def test_super_key_aliases_and_lone_modifier(alias: str) -> None:
    """
    All names of the Super key give ``meta_l``, and a modifier alone is a valid tap.

    Args:
        alias: One of the aliases.

    Returns:
        None.
    """
    assert parse_chord(alias) == ("meta_l",)
    assert parse_chord(f"{alias}+d") == ("meta_l", "d")


def test_parse_chord_function_digit_and_arrow_keys() -> None:
    """
    Function keys, digits and named keys are accepted.

    Returns:
        None.
    """
    assert parse_chord("alt+f4") == ("alt", "f4")
    assert parse_chord("ctrl+1") == ("ctrl", "1")
    assert parse_chord("shift+left") == ("shift", "left")
    assert parse_chord("return") == ("ret",)


@pytest.mark.parametrize(
    "chord",
    [
        "",
        "   ",
        "+",
        "meta+",
        "+w",
        "meta++w",
        "meta+banana",
        "banana",
        "a+b",  # two keys
        "w+meta",  # modifier after the key
        "ctrl+ctrl+a",  # repeated modifier
        "ctrl+shift",  # modifiers only, more than one
        "meta+f13",
    ],
)
def test_parse_chord_rejects_invalid_chords(chord: str) -> None:
    """
    Every malformed or unknown chord is a ValueError naming the chord.

    Args:
        chord: A chord that must be rejected.

    Returns:
        None.
    """
    with pytest.raises(ValueError):
        parse_chord(chord)


def test_parse_chord_error_names_the_unknown_key() -> None:
    """
    The message tells which part of the chord is unknown.

    Returns:
        None.
    """
    with pytest.raises(ValueError, match="banana"):
        parse_chord("meta+banana")


@pytest.mark.parametrize("value", [None, 5, ["a"]])
def test_parse_chord_rejects_non_strings(value: object) -> None:
    """
    Anything that is not a string is a ValueError, not a TypeError.

    Args:
        value: A non-string.

    Returns:
        None.
    """
    with pytest.raises(ValueError):
        parse_chord(value)  # type: ignore[arg-type]


def test_text_to_chords_letters_digits_space() -> None:
    """
    Letters, digits and spaces become one chord each; capitals add shift.

    Returns:
        None.
    """
    assert text_to_chords("files") == [("f",), ("i",), ("l",), ("e",), ("s",)]
    assert text_to_chords("a 1") == [("a",), ("spc",), ("1",)]
    assert text_to_chords("Ab") == [("shift", "a"), ("b",)]


@pytest.mark.parametrize("text", ["", "hello!", "café", "a\nb", "٣"])
def test_text_to_chords_rejects_untypeable_text(text: str) -> None:
    """
    Empty text and any other character are rejected.

    Args:
        text: Text that must be rejected.

    Returns:
        None.
    """
    with pytest.raises(ValueError):
        text_to_chords(text)


def test_text_to_chords_error_names_character_and_position() -> None:
    """
    The message points at the offending character.

    Returns:
        None.
    """
    with pytest.raises(ValueError, match=r"'!'.*position 3"):
        text_to_chords("abc!")


def test_text_to_chords_length_limit_and_type() -> None:
    """
    Text at the limit passes, one character more fails, non-strings fail.

    Returns:
        None.
    """
    assert len(text_to_chords("a" * MAX_TEXT_LENGTH)) == MAX_TEXT_LENGTH
    with pytest.raises(ValueError):
        text_to_chords("a" * (MAX_TEXT_LENGTH + 1))
    with pytest.raises(ValueError):
        text_to_chords(None)  # type: ignore[arg-type]

"""
Key chord parsing for the screenshot harness.

A chord is written the way it is spoken: ``"meta+w"``, ``"alt+space"``, ``"escape"``,
``"ctrl+shift+f"``. This module turns such a string into the ordered list of QEMU key
codes ("qcodes") that QMP ``input-send-event`` expects, and validates it: an unknown
key name is a ``ValueError`` so that a typo in ``states.toml`` fails when the file is
loaded, not half way through a boot.

Typing text works the same way: every letter, digit and space becomes one key press
(an upper-case letter is ``shift`` + the letter). Nothing else is accepted, because the
harness only ever types short search words.

Standard library only; no I/O, so everything here is unit-testable without a VM.
"""

from __future__ import annotations

# Modifier names accepted in a chord, mapped to the QEMU qcode that is pressed.
# The Super key is "meta_l" in QEMU's key code list; "super" and "win" are aliases
# because they are the names people use for it.
MODIFIERS: dict[str, str] = {
    "meta": "meta_l",
    "super": "meta_l",
    "win": "meta_l",
    "alt": "alt",
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
}

# Non-modifier keys by the name used in a chord. Letters, digits and F1..F12 are added
# programmatically below so the table stays readable.
NAMED_KEYS: dict[str, str] = {
    "escape": "esc",
    "esc": "esc",
    "space": "spc",
    "enter": "ret",
    "return": "ret",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "pageup": "pgup",
    "pagedown": "pgdn",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "menu": "menu",
    "minus": "minus",
    "equal": "equal",
    "comma": "comma",
    "period": "dot",
    "slash": "slash",
}

# One entry per printable key so a chord like "meta+w" or "ctrl+1" needs no special case.
_PLAIN_KEYS: dict[str, str] = {c: c for c in "abcdefghijklmnopqrstuvwxyz0123456789"}
_FUNCTION_KEYS: dict[str, str] = {f"f{n}": f"f{n}" for n in range(1, 13)}

# Every non-modifier chord token that is understood.
KEYS: dict[str, str] = {**NAMED_KEYS, **_PLAIN_KEYS, **_FUNCTION_KEYS}

# Upper bound for typed text: the harness types search words, not documents. A cap keeps
# a typo in states.toml (or a hostile file) from queueing thousands of key events.
MAX_TEXT_LENGTH = 200


def parse_chord(chord: str) -> tuple[str, ...]:
    """
    Parse a key chord into the QEMU key codes to press, in press order.

    The chord is a ``+`` separated list of names: any number of distinct modifiers
    followed by exactly one key, or a single modifier on its own (a tap of the Super
    key is a legitimate chord). Names are case-insensitive and surrounding spaces are
    ignored.

    Args:
        chord: For example ``"meta+w"``, ``"alt+space"``, ``"escape"``, ``"ctrl+shift+f"``.

    Returns:
        The qcodes in the order they are pressed (modifiers first, in the order they
        were written, then the key). Release order is the reverse; that is the
        caller's business.

    Raises:
        ValueError: if the chord is not a string, is empty, has an empty part
            (``"meta++w"``), names an unknown key, repeats a modifier, has more than
            one non-modifier key, or has a modifier after the key.
    """
    if not isinstance(chord, str):
        raise ValueError(f"key chord must be a string, got {type(chord).__name__}")
    if not chord.strip():
        raise ValueError("key chord is empty")

    parts = [part.strip().lower() for part in chord.split("+")]
    if any(not part for part in parts):
        raise ValueError(f"key chord {chord!r} has an empty part")

    modifiers: list[str] = []
    key: str | None = None
    for part in parts:
        if part in MODIFIERS:
            if key is not None:
                # WHY: "w+meta" is almost certainly a typo, and pressing the
                # modifier after the key would not act as a modifier anyway.
                raise ValueError(f"key chord {chord!r}: modifier {part!r} must come before the key")
            qcode = MODIFIERS[part]
            if qcode in modifiers:
                raise ValueError(f"key chord {chord!r}: modifier {part!r} is given twice")
            modifiers.append(qcode)
        elif part in KEYS:
            if key is not None:
                raise ValueError(f"key chord {chord!r} has more than one key ({key!r} and {part!r})")
            key = KEYS[part]
        else:
            raise ValueError(f"key chord {chord!r}: unknown key {part!r}")

    if key is None:
        # Only modifiers were given. A single one is a plain tap of that key.
        if len(modifiers) != 1:
            raise ValueError(f"key chord {chord!r} has no key")
        return (modifiers[0],)
    return (*modifiers, key)


def text_to_chords(text: str) -> list[tuple[str, ...]]:
    """
    Translate text into one chord (tuple of qcodes) per character.

    Args:
        text: Letters (either case), digits and spaces only, at most
            ``MAX_TEXT_LENGTH`` characters, at least one.

    Returns:
        One entry per character; an upper-case letter is ``("shift", letter)``, a
        space is ``("spc",)``.

    Raises:
        ValueError: if the text is not a string, is empty or too long, or contains
            any character other than an ASCII letter, digit or space (the message
            names the character and its position).
    """
    if not isinstance(text, str):
        raise ValueError(f"typed text must be a string, got {type(text).__name__}")
    if not text:
        raise ValueError("typed text is empty")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"typed text is longer than {MAX_TEXT_LENGTH} characters")

    chords: list[tuple[str, ...]] = []
    for position, char in enumerate(text):
        if char == " ":
            chords.append(("spc",))
        elif char.isascii() and char.isdigit():
            chords.append((char,))
        elif char.isascii() and char.isalpha():
            # WHY isascii: str.isalpha() is true for letters QEMU has no qcode for.
            chords.append((char.lower(),) if char.islower() else ("shift", char.lower()))
        else:
            raise ValueError(f"typed text: character {char!r} at position {position} cannot be typed")
    return chords

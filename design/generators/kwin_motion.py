"""
LOCKED INTERFACE: implement the body below without changing the signature.
Standard library only.

Renders the one real, non-approximated motion-token lever this project's own
research (Vaihe 6, "animaatiokayrien yhtenaistaminen") confirmed exists beyond
the stock defaults: KWin's SlidingPopups effect,
`kwinrc [Effect-slidingpopups] SlideInTime=` / `SlideOutTime=`, a real,
absolute-millisecond config key - confirmed live against the pinned KWin
6.7.5 source (`slidingpopups.cpp`: `m_slideInDuration = ... slideInTime() != 0
? ms(slideInTime()) : 200ms`), not approximated.

This is deliberately the ONLY motion lever this project wires up as a config
value, and it is accepted specifically BECAUSE it is an exact, lossless
mapping: `design/tokens.json`'s `motion.duration.*` values are absolute
millisecond counts already, so writing one of them into an absolute-
millisecond config key changes nothing about its meaning.

Two confirmed real levers that LOOK similar but are NOT implemented here,
on purpose - see `packages/kuura-shell/skel/.config/kwinrc`'s own
"Effect-overview" header comment and `docs/SHELL_CONTRACT.md`'s own
"Animation curves" section for the full reasoning:

1. `kdeglobals [KDE] AnimationDurationFactor` - a real, confirmed, UNITLESS
   multiplier applied to every Plasma/KWin effect's own hard-coded duration.
   `design/tokens.json`'s `motion.duration` has FOUR separate absolute-
   millisecond buckets (instant/fast/base/slow); one global scalar cannot
   reproduce all four at once (the real base durations it scales have fixed
   1:2:4:8 ratios - 50/100/200/400ms - which do not match this project's own
   100/180/260/400ms buckets). Picking any one bucket to match exactly means
   the other three drift by 30-100%. That is an approximation dressed up as
   a real mapping, which this project's own standing rule (see the Effect-
   overview comment above) declines to ship.
2. `motion.easing_standard` (the cubic-bezier curve shape) and
   `motion.easing_spring` (mass/stiffness/damping) have NO config surface
   anywhere in the real KDE/Qt stack surveyed - every real KWin effect and
   Kirigami's own `Units` class specify their easing as either a literal
   named Qt enum (`Easing.OutCubic`) or hardcoded C++ control points, never
   read from any config file. Reaching either would mean patching and
   recompiling upstream KWin/Kirigami, out of scope for a config-only
   package.

Output is a single ini FRAGMENT, not a complete kwinrc: the existing
`packages/kuura-shell/skel/.config/kwinrc` is a carefully-documented static
file with no other token-derived values, so it is left untouched on disk.
`packages/kuura-shell/PKGBUILD`'s own `package()` step concatenates this
fragment onto that static file's content at package-build time (plain
concatenation, not a merge library) - ini files merge cleanly by distinct
section, the same fact `kdeglobals`'s own header comment already relies on
for its own future `[General]` section.

Uses `motion.duration.fast` (180ms in the shipped tokens) for BOTH
SlideInTime and SlideOutTime: "fast" is already the only duration bucket
every other motion-consuming generator in this repo uses (gtk_css.py,
firefox_theme.py, sddm_theme.py, lookandfeel_theme.py, qml_singleton.py),
so this keeps KWin's own slide-popup animation consistent with the
project's one already-established transition speed rather than inventing a
second, uncoordinated duration choice. `design/tokens.json` has no separate
enter/exit distinction, so both keys intentionally share the same value.
"""

from __future__ import annotations


def render_slidingpopups_fragment(tokens: dict) -> str:
    """
    Render the `[Effect-slidingpopups]` kwinrc ini fragment from tokens.

    Args:
        tokens: The parsed design/tokens.json dict. Must contain
            tokens["motion"]["duration"]["fast"], an int in 1..5000 per
            design/validate.py's own schema (validated there, not re-checked
            here - this function trusts its caller the same way every other
            generator in this package does).

    Returns:
        The ini-format fragment as a string, ending in a trailing newline,
        containing exactly one section header ("[Effect-slidingpopups]")
        and the two keys SlideInTime/SlideOutTime, both set to
        tokens["motion"]["duration"]["fast"] (see this module's own
        docstring for why both keys share one value and why "fast" is the
        bucket used). Ready to be appended as-is to an existing kwinrc
        file's content - not a complete kwinrc by itself.

    Raises:
        KeyError: if tokens["motion"]["duration"]["fast"] is missing.
    """
    # WHY: "fast" is deliberately the only bucket read here - see the module
    # docstring for why both SlideInTime and SlideOutTime share this single
    # value instead of distinguishing enter/exit speeds.
    fast_ms = tokens["motion"]["duration"]["fast"]
    return f"[Effect-slidingpopups]\nSlideInTime={fast_ms}\nSlideOutTime={fast_ms}\n"

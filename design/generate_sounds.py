"""
Command line tool that SYNTHESIZES design/tokens.json-derived UI sounds as real,
playable PCM WAV files -- no recorded/sampled audio, no third-party audio library.

WHY code synthesis instead of a recorded/CC0 sample pack (Vaihe 5 of the working brief,
"Omat assetit", brief text: "Aanet: 6-8 lyhytta UI-aanta, oma tuotanto tai CC0"): the
orchestrator chose "oma tuotanto" (own production) via pure math, using ONLY the
standard library (`wave`, `math`, `array`, `sys`, `os`, `re`, `struct` are all that a
tone/click/chime needs) -- this avoids a new runtime dependency (no numpy/scipy/pydub)
and the license-review cycle that would come with bundling someone else's recorded
CC0 samples, for a set of sounds simple enough that stdlib math is entirely sufficient.

WAV FORMAT (every file, no exceptions): mono, 16-bit signed little-endian PCM
(`SAMPLE_WIDTH_BYTES = 2`), 44100 Hz (`SAMPLE_RATE`) -- written through the standard
library's own `wave` module, which already emits a correct, minimal canonical RIFF/WAVE
header for these parameters, so no header bytes are hand assembled here.

DESIGN ANCHOR -- durations come from design/tokens.json's own motion.duration.*, not
from hand-picked millisecond literals (the same "tokens.json is the one source numeric
values may come from" rule design/generators/cpp_header.py and plasma_layout.py already
follow for their own domains). Every one of the 8 sounds below is exactly as long, in
milliseconds, as one of `tokens["motion"]["duration"]`'s four values (instant=100,
fast=180, base=260, slow=400 in the committed tokens.json; a future edit to tokens.json
regenerates matching-length sounds automatically, the same way it already regenerates
matching CSS transition durations). The grouping is a deliberate perceptual mapping, not
an arbitrary round-robin assignment:
  - `instant` backs the three sounds that are momentary feedback ticks, plausibly fired
    in rapid succession (a click, a volume drag, a screenshot) -- the same duration class
    tokens.json already anchors its OWN fastest UI transitions to.
  - `fast` backs the two sounds that need slightly more room to say something in one
    clip without being a plain tick (an error's 3-phase envelope; a menu tick's full
    pitch sweep).
  - `base` backs the two "something happened, here are two distinct notes/a full sweep"
    confirmations (success's two-note chime; trash's falling sweep).
  - `slow` backs the one sound meant to be heard once per session, not fired repeatedly
    (the login chime's three-note arpeggio) -- the fullest, longest sound in the set.

AMPLITUDE / CLIPPING SAFETY -- every synthesis function below (`_click`, `_chirp`,
`_dissonant_tone`, `_chime`, `_double_click`) builds a stream of plain floats
mathematically bounded to [-1.0, 1.0]: every envelope used is bounded to [0, 1], every
waveform sampled is a sine (bounded to [-1, 1]), and the one function that sums two
sines (`_dissonant_tone`) immediately multiplies the sum by 0.5 so the result stays in
[-1, 1] even at the (rare) instant both sines peak in phase. Quantization
(`_quantize_to_pcm16`) is the ONE place amplitude is scaled to real int16 sample values,
by `PEAK_AMPLITUDE * INT16_MAX` where `PEAK_AMPLITUDE = 0.85` and `INT16_MAX = 32767` --
so every quantized sample's magnitude is at most floor(0.85 * 32767) = 27852, roughly
15% of headroom below BOTH int16 extremes (+32767 and -32768). No synthesis function
needs to reason about clipping itself; centralizing the scale in one function is also
why `_quantize_to_pcm16` additionally clamps defensively to [-1.0, 1.0] before scaling,
as a belt-and-suspenders guard against a future synthesis bug, not because any function
in this file is currently expected to exceed that range.

ENVELOPE SHAPES -- the exact math, precise enough to reproduce every sample by hand:

1. Exponential decay (`_exp_decay_envelope`, used by `_click` and `_chirp`), the
   "very short burst with a fast exponential decay" shape the working brief itself
   names: env(t) = exp(-t / tau), where tau = -decay_span_s / ln(ENVELOPE_FLOOR) and
   ENVELOPE_FLOOR = 0.01. This makes env(decay_span_s) exactly 0.01 (1% of peak) by
   construction, continuing to decay smoothly (never hard-clipped to exactly 0) for
   t beyond decay_span_s. `decay_span_s` is `decay_fraction * duration_s`: at
   decay_fraction=1.0 the sound decays to 1% of peak exactly at the clip's own last
   sample (click.wav, the falling/rising sweeps, every chime note); at
   decay_fraction<1.0 (volume_tick.wav 0.4, menu_tick.wav 0.6) the audible transient
   is concentrated in the first part of the clip and the remainder is near-silent
   padding, giving a punchier, shorter-feeling tick without shortening the clip's own
   token-derived length. WHY this never clicks/pops at either edge: every waveform
   multiplied by this envelope is a plain sine whose phase is exactly 0 at t=0 (see
   point 2), so the very first sample is always exactly 0 regardless of envelope value;
   there is nothing before sample 0 in a freshly opened WAV file, so starting at the
   envelope's own maximum (env(0)=1) is not a discontinuity; and decaying smoothly
   toward (not snapping to) silence means the file never ends on an abrupt jump either.

2. Linear frequency sweep ("chirp") phase (`_chirp_phase`, used by `_chirp` for
   menu_tick.wav and trash_delete.wav): a tone whose instantaneous frequency changes
   LINEARLY from f0 to f1 over the clip's duration T must NOT be sampled as
   sin(2*pi*f(t)*t) with f(t) = f0 + (f1-f0)*t/T -- that formula is only correct for a
   CONSTANT frequency; used with a time-varying f(t) it integrates the wrong pitch
   trajectory and produces audible phase glitches. The correct instantaneous phase is
   the time integral of the instantaneous angular frequency 2*pi*f(t):
       phase(t) = 2*pi * integral_0^t f(u) du
                = 2*pi * [f0*t + (f1-f0)*t^2 / (2*T)]
   `_chirp_phase(t_s, f0_hz, f1_hz, duration_s)` returns exactly this closed form;
   `_chirp` then samples sin(phase(t)) at every sample instant and multiplies by the
   SAME exponential-decay envelope as `_click` (so the "no click at either edge"
   reasoning above applies unchanged: phase(0) = 0, so sin(phase(0)) = 0 too).

3. Trapezoid (attack-sustain-release) envelope (`_trapezoid_envelope`, used only by
   `_dissonant_tone` for error.wav): env(t) = t/attack_s for t < attack_s;
   (duration_s - t)/release_s for t > duration_s - release_s; 1.0 in between. Error.wav
   is the ONE sound in this set meant to be heard at a clearly sustained, undamped
   loudness rather than as a decaying transient, so unlike every exponential-decay
   envelope above (which already starts at its own maximum, env(0)=1), this envelope
   must ALSO ramp up from 0 -- a hard on/off gate at full amplitude would leave the
   very first and last sample far from zero, an audible click at BOTH ends of the clip
   (not just the end, the way a decaying-transient envelope's own end already handles).

4. Chime note concatenation (`_chime`, used by success.wav and login_chime.wav): plays
   each of its frequencies as an independent `_click`-style exponential-decay tone,
   sized to its own equal share of the requested total duration (the last note absorbs
   the integer-division remainder so the concatenation always totals exactly the
   token-derived sample count), one after another with no gap. Because each note's own
   envelope has already decayed near ENVELOPE_FLOOR before its own slice ends and the
   next note's envelope restarts at 1.0 (not from wherever the previous note left off),
   concatenating them produces no audible seam between notes.

5. Two-click concatenation (`_double_click`, used only by screenshot_shutter.wav):
   click, then silence, then a second click at a different pitch, then (if any
   milliseconds remain) trailing silence padding out to the requested total duration --
   mimicking a mechanical shutter's two-stage "clack-clack" open/close.

THE 8 SOUNDS (name -> file `<out-dir>/sounds/<name>.wav`; frequencies are the exact
floats the code uses, not rounded for the table):

| name               | purpose                        | token (ms)     | synthesis                                                                                     |
|--------------------|---------------------------------|----------------|------------------------------------------------------------------------------------------------|
| click              | generic button/control click    | instant (100)  | `_click`: single 1000 Hz sine, decay_fraction=1.0 (decays to 1% by the clip's own last sample) |
| volume_tick        | volume slider step tick         | instant (100)  | `_click`: single 1800 Hz sine (brighter than click), decay_fraction=0.4 (punchier, ~40 ms audible transient so rapid repeats do not smear) |
| menu_tick          | menu open/close tick             | fast (180)     | `_chirp`: rising sweep 700 -> 1100 Hz, decay_fraction=0.6 -- the upward sweep (vs. click/volume_tick's flat pitch) is what makes this one distinguishable by ear alone |
| screenshot_shutter | screenshot captured feedback    | instant (100)  | `_double_click`: 2600 Hz click (40 ms) + 20 ms silence + 1700 Hz click (40 ms) = 100 ms exactly, no padding needed |
| error              | action failed / invalid input   | fast (180)     | `_dissonant_tone`: A4 (440 Hz) + A#4 (440 * 2**(1/12) =~ 466.16 Hz) summed and halved -- one semitone apart, so the ~26 Hz beat between them reads as dissonant/buzzy, not a clean chord; trapezoid envelope, 20 ms attack / 120 ms sustain / 40 ms release |
| success            | action completed                | base (260)     | `_chime`: A5 (880 Hz) then E6 (1318.51 Hz) -- a perfect fifth (7 semitones) rising, the classic "pleasant confirmation" interval; 130 ms + 130 ms, decay_fraction=1.0 each |
| trash_delete       | empty trash / delete confirmed  | base (260)     | `_chirp`: falling sweep 600 -> 120 Hz, decay_fraction=1.0 -- pitch dropping away reads as something being discarded |
| login_chime        | session start / login greeting  | slow (400)     | `_chime`: C5, E5, G5 (523.25 / 659.25 / 783.99 Hz, a C-major triad arpeggio) -- the fullest, longest sound in the set, meant to be heard once per session, not fired repeatedly |

Usage (from the project root):
    python -m design.generate_sounds [--tokens FILE] [--out-dir DIR] [--name NAME]

Output: `<out-dir>/sounds/<name>.wav`, one file per sound listed above (`SOUND_NAMES`
gives the exact, sorted set of stems). `--tokens`/`--out-dir` behave exactly like
design/generate.py's own flags (same defaults, same path-traversal guard: `--out-dir`
must resolve inside the project root). `--name` is accepted only for command-line shape
parity with design/generate.py (so every `design.generate*` tool takes the same three
flags) -- UI sounds have no light/dark mode and no per-theme branding difference the way
a `.colors`/`.css` file does, so `--name` is validated (same lowercase/digits/"_"/"-"
rule) but does not affect sound content or file names; `generate()`'s own `name`
parameter is kept for the same reason design/generators/plasma_layout.py keeps an
unused `tokens` parameter on `render_activities()` -- interface stability for whatever
calls it, not because today's output depends on it.
"""

from __future__ import annotations

import array
import math
import os
import re
import sys
import wave
from pathlib import Path

# Generated files must stay inside the project tree (path traversal guard, identical
# to design/generate.py's own PROJECT_ROOT/guard).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---- WAV format (fixed for every sound; see module docstring) ----
SAMPLE_RATE = 44100
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2  # 16-bit PCM

# ---- Amplitude scale (see module docstring's "AMPLITUDE / CLIPPING SAFETY") ----
INT16_MAX = 32767
PEAK_AMPLITUDE = 0.85

# Exponential-decay envelopes reach this fraction of peak at their own decay_span_s
# (see module docstring, envelope shape 1).
ENVELOPE_FLOOR = 0.01

# ---- Per-sound synthesis constants (see module docstring's table for the "why" of
# each number) ----
_CLICK_HZ = 1000.0
_VOLUME_TICK_HZ = 1800.0
_MENU_TICK_START_HZ = 700.0
_MENU_TICK_END_HZ = 1100.0
_SHUTTER_CLICK1_HZ = 2600.0
_SHUTTER_CLICK2_HZ = 1700.0
_SHUTTER_CLICK_MS = 40.0
_SHUTTER_GAP_MS = 20.0
_ERROR_TONE_LOW_HZ = 440.0  # A4
_ERROR_TONE_HIGH_HZ = 440.0 * 2 ** (1 / 12)  # A#4, one semitone above A4 (~466.16 Hz)
_ERROR_ATTACK_MS = 20.0
_ERROR_RELEASE_MS = 40.0
_SUCCESS_NOTES_HZ = (880.0, 1318.51)  # A5, E6 (perfect fifth, 7 semitones up)
_TRASH_START_HZ = 600.0
_TRASH_END_HZ = 120.0
_LOGIN_NOTES_HZ = (523.25, 659.25, 783.99)  # C5, E5, G5 (C major triad arpeggio)

# The exact, sorted set of sound stems generate() writes -- exposed so tests (and any
# future caller) never have to hand-copy this list.
SOUND_NAMES = (
    "click",
    "error",
    "login_chime",
    "menu_tick",
    "screenshot_shutter",
    "success",
    "trash_delete",
    "volume_tick",
)


def _n_samples(duration_ms: float) -> int:
    """
    Convert a duration in milliseconds to a sample count at SAMPLE_RATE.

    Args:
        duration_ms: Duration in milliseconds (must be > 0).

    Returns:
        round(SAMPLE_RATE * duration_ms / 1000), the number of samples that many
        milliseconds occupy at 44100 Hz.
    """
    return round(SAMPLE_RATE * duration_ms / 1000.0)


def _exp_decay_envelope(elapsed_s: float, decay_span_s: float) -> float:
    """
    Exponential-decay envelope value at `elapsed_s` seconds (see module docstring,
    envelope shape 1, for the full derivation and why this never clicks/pops).

    Args:
        elapsed_s: Seconds since the sound started (>= 0).
        decay_span_s: Seconds at which the envelope reaches ENVELOPE_FLOOR (must be
            > 0).

    Returns:
        exp(-elapsed_s / tau), where tau = -decay_span_s / ln(ENVELOPE_FLOOR); equals
        1.0 at elapsed_s=0 and exactly ENVELOPE_FLOOR at elapsed_s=decay_span_s.

    Raises:
        ValueError: if decay_span_s <= 0.
    """
    if decay_span_s <= 0:
        raise ValueError("decay_span_s must be > 0")
    tau = -decay_span_s / math.log(ENVELOPE_FLOOR)
    return math.exp(-elapsed_s / tau)


def _trapezoid_envelope(elapsed_s: float, attack_s: float, release_s: float, duration_s: float) -> float:
    """
    Attack-sustain-release envelope value at `elapsed_s` seconds (see module
    docstring, envelope shape 3).

    Args:
        elapsed_s: Seconds since the sound started (>= 0).
        attack_s: Seconds of the initial linear ramp from 0 to 1.
        release_s: Seconds of the final linear ramp from 1 to 0.
        duration_s: Total sound duration in seconds (must be >= attack_s + release_s).

    Returns:
        elapsed_s/attack_s while elapsed_s < attack_s; (duration_s-elapsed_s)/release_s
        while elapsed_s > duration_s-release_s; 1.0 in between.
    """
    if elapsed_s < attack_s:
        return elapsed_s / attack_s
    if elapsed_s > duration_s - release_s:
        return max(0.0, (duration_s - elapsed_s) / release_s)
    return 1.0


def _chirp_phase(t_s: float, f0_hz: float, f1_hz: float, duration_s: float) -> float:
    """
    Exact instantaneous phase of a linear frequency sweep (see module docstring,
    envelope shape 2, for why this closed form -- not sin(2*pi*f(t)*t) -- is required).

    Args:
        t_s: Elapsed time in seconds since the sweep started.
        f0_hz: Frequency at t_s=0.
        f1_hz: Frequency at t_s=duration_s.
        duration_s: Total sweep duration in seconds (must be > 0).

    Returns:
        2*pi * (f0_hz*t_s + (f1_hz-f0_hz)*t_s**2 / (2*duration_s)), the time integral
        of the instantaneous angular frequency 2*pi*f(t).
    """
    return 2 * math.pi * (f0_hz * t_s + (f1_hz - f0_hz) * t_s**2 / (2 * duration_s))


def _click(freq_hz: float, duration_ms: float, decay_fraction: float = 1.0) -> list[float]:
    """
    A single sine tone with a pure exponential-decay envelope.

    Args:
        freq_hz: Tone frequency in Hz.
        duration_ms: Total clip duration in milliseconds.
        decay_fraction: Fraction of duration_ms at which the envelope reaches
            ENVELOPE_FLOOR (1.0 = decays to 1% exactly at the clip's last sample;
            < 1.0 = a punchier, shorter-feeling transient within the same clip length).

    Returns:
        A list of floats in [-1.0, 1.0], one per sample, of length
        _n_samples(duration_ms).
    """
    n = _n_samples(duration_ms)
    duration_s = duration_ms / 1000.0
    decay_span_s = duration_s * decay_fraction
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = _exp_decay_envelope(t, decay_span_s)
        samples.append(env * math.sin(2 * math.pi * freq_hz * t))
    return samples


def _chirp(f0_hz: float, f1_hz: float, duration_ms: float, decay_fraction: float = 1.0) -> list[float]:
    """
    A linear frequency sweep ("chirp") with a pure exponential-decay envelope.

    Args:
        f0_hz: Frequency at the start of the clip.
        f1_hz: Frequency at the end of the clip.
        duration_ms: Total clip duration in milliseconds.
        decay_fraction: Same meaning as `_click`'s own parameter.

    Returns:
        A list of floats in [-1.0, 1.0], one per sample, of length
        _n_samples(duration_ms).
    """
    n = _n_samples(duration_ms)
    duration_s = duration_ms / 1000.0
    decay_span_s = duration_s * decay_fraction
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = _exp_decay_envelope(t, decay_span_s)
        phase = _chirp_phase(t, f0_hz, f1_hz, duration_s)
        samples.append(env * math.sin(phase))
    return samples


def _dissonant_tone(
    f1_hz: float, f2_hz: float, duration_ms: float, attack_ms: float, release_ms: float
) -> list[float]:
    """
    Two simultaneous sine tones, summed and halved, under a trapezoid envelope (see
    module docstring, envelope shape 3, and the error.wav row of the sound table).

    Args:
        f1_hz: First tone's frequency in Hz.
        f2_hz: Second tone's frequency in Hz (close to f1_hz to produce audible
            beating/roughness).
        duration_ms: Total clip duration in milliseconds.
        attack_ms: Milliseconds of the initial linear ramp from 0 to 1.
        release_ms: Milliseconds of the final linear ramp from 1 to 0.

    Returns:
        A list of floats in [-1.0, 1.0], one per sample, of length
        _n_samples(duration_ms).

    Raises:
        ValueError: if attack_ms + release_ms > duration_ms.
    """
    if attack_ms + release_ms > duration_ms:
        raise ValueError("attack_ms + release_ms must not exceed duration_ms")
    n = _n_samples(duration_ms)
    duration_s = duration_ms / 1000.0
    attack_s = attack_ms / 1000.0
    release_s = release_ms / 1000.0
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = _trapezoid_envelope(t, attack_s, release_s, duration_s)
        combined = 0.5 * (math.sin(2 * math.pi * f1_hz * t) + math.sin(2 * math.pi * f2_hz * t))
        samples.append(env * combined)
    return samples


def _chime(freqs_hz: tuple[float, ...], total_duration_ms: float, decay_fraction: float = 1.0) -> list[float]:
    """
    Concatenate one `_click`-style exponential-decay tone per frequency, each sized to
    its own equal share of `total_duration_ms` (see module docstring, envelope shape 4).

    Args:
        freqs_hz: The note frequencies, in playback order (2 for success.wav, 3 for
            login_chime.wav).
        total_duration_ms: Total clip duration in milliseconds; divided as evenly as
            possible among the notes, with any integer-division remainder absorbed by
            the LAST note so the concatenation always totals exactly
            _n_samples(total_duration_ms) samples.
        decay_fraction: Passed through to every note's own `_click` call.

    Returns:
        A list of floats in [-1.0, 1.0], one per sample, of length
        _n_samples(total_duration_ms).
    """
    total_n = _n_samples(total_duration_ms)
    note_count = len(freqs_hz)
    base_n = total_n // note_count
    samples: list[float] = []
    for index, freq_hz in enumerate(freqs_hz):
        note_n = base_n if index < note_count - 1 else total_n - base_n * (note_count - 1)
        note_ms = note_n / SAMPLE_RATE * 1000.0
        samples.extend(_click(freq_hz, note_ms, decay_fraction))
    return samples


def _silence(duration_ms: float) -> list[float]:
    """
    A run of zero-amplitude samples.

    Args:
        duration_ms: Duration in milliseconds.

    Returns:
        A list of `_n_samples(duration_ms)` zeros.
    """
    return [0.0] * _n_samples(duration_ms)


def _double_click(
    freq1_hz: float,
    freq2_hz: float,
    click_ms: float,
    gap_ms: float,
    total_ms: float,
    decay_fraction: float = 1.0,
) -> list[float]:
    """
    Two `_click`-style tones separated by silence, padded with trailing silence out to
    `total_ms` (see module docstring, envelope shape 5, and screenshot_shutter.wav).

    Args:
        freq1_hz: First click's frequency in Hz.
        freq2_hz: Second click's frequency in Hz.
        click_ms: Duration of EACH click in milliseconds.
        gap_ms: Silence between the two clicks, in milliseconds.
        total_ms: Total clip duration in milliseconds (must be >= 2*click_ms + gap_ms).
        decay_fraction: Passed through to both `_click` calls.

    Returns:
        A list of floats in [-1.0, 1.0], one per sample, of length
        _n_samples(total_ms).

    Raises:
        ValueError: if 2*click_ms + gap_ms exceeds total_ms.
    """
    total_n = _n_samples(total_ms)
    samples = _click(freq1_hz, click_ms, decay_fraction) + _silence(gap_ms) + _click(freq2_hz, click_ms, decay_fraction)
    pad_n = total_n - len(samples)
    if pad_n < 0:
        raise ValueError("2*click_ms + gap_ms must not exceed total_ms")
    samples.extend([0.0] * pad_n)
    return samples


def _quantize_to_pcm16(samples: list[float]) -> bytes:
    """
    Scale normalized float samples to signed 16-bit PCM bytes (see module docstring's
    "AMPLITUDE / CLIPPING SAFETY" -- the ONE place amplitude is scaled to real int16
    values).

    Args:
        samples: Floats mathematically bounded to [-1.0, 1.0] by every synthesis
            function above; also clamped defensively here before scaling.

    Returns:
        Little-endian signed 16-bit PCM bytes, one sample per 2 bytes, each sample's
        magnitude at most floor(PEAK_AMPLITUDE * INT16_MAX) = 27852.
    """
    peak = PEAK_AMPLITUDE * INT16_MAX
    ints = array.array("h", (int(round(max(-1.0, min(1.0, s)) * peak)) for s in samples))
    # WHY byteswap on big-endian hosts: `array` uses the host's native byte order, but
    # WAV's data chunk is always little-endian - this project's own target hosts
    # (Windows/x86, the Arch Linux guest image) are little-endian already, but this
    # keeps the output format-correct regardless of host, the same defensive stance
    # design/generators/cpp_header.py takes for its own numeric formatting.
    if sys.byteorder == "big":
        ints.byteswap()
    return ints.tobytes()


def _write_wav(path: Path, samples: list[float]) -> None:
    """
    Write one mono/16-bit/44100 Hz PCM WAV file.

    Args:
        path: Destination file path; overwritten if it already exists.
        samples: Floats in [-1.0, 1.0] as produced by this module's synthesis
            functions.

    Returns:
        None. The file is written as a side effect.
    """
    pcm_bytes = _quantize_to_pcm16(samples)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm_bytes)


def generate(tokens: dict, out_dir: Path, name: str) -> list[Path]:  # noqa: ARG001 - kept for interface parity with design.generate.generate(); see module docstring for why sound content never depends on it.
    """
    Synthesize all 8 UI sounds and write them under `<out_dir>/sounds/`.

    Args:
        tokens: Validated token dictionary (see design/validate.py). Only
            tokens["motion"]["duration"]["instant"/"fast"/"base"/"slow"] is read (see
            module docstring's "DESIGN ANCHOR" for exactly which sound uses which key).
        out_dir: Directory that receives the "sounds" subdirectory (created as needed).
            Existing files of the same name are overwritten.
        name: Unused by sound content (see module docstring); kept only so this
            function's signature mirrors design.generate.generate()'s own
            (tokens, out_dir, name) -> list[Path] shape.

    Returns:
        The paths of all 8 written files, sorted (matching design.generate.generate()'s
        own sorted-return convention) -- always exactly `len(SOUND_NAMES)` entries.
    """
    durations = tokens["motion"]["duration"]
    instant_ms = durations["instant"]
    fast_ms = durations["fast"]
    base_ms = durations["base"]
    slow_ms = durations["slow"]

    sounds: dict[str, list[float]] = {
        "click": _click(_CLICK_HZ, instant_ms, decay_fraction=1.0),
        "volume_tick": _click(_VOLUME_TICK_HZ, instant_ms, decay_fraction=0.4),
        "menu_tick": _chirp(_MENU_TICK_START_HZ, _MENU_TICK_END_HZ, fast_ms, decay_fraction=0.6),
        "screenshot_shutter": _double_click(
            _SHUTTER_CLICK1_HZ, _SHUTTER_CLICK2_HZ, _SHUTTER_CLICK_MS, _SHUTTER_GAP_MS, instant_ms
        ),
        "error": _dissonant_tone(
            _ERROR_TONE_LOW_HZ, _ERROR_TONE_HIGH_HZ, fast_ms, _ERROR_ATTACK_MS, _ERROR_RELEASE_MS
        ),
        "success": _chime(_SUCCESS_NOTES_HZ, base_ms),
        "trash_delete": _chirp(_TRASH_START_HZ, _TRASH_END_HZ, base_ms),
        "login_chime": _chime(_LOGIN_NOTES_HZ, slow_ms),
    }

    sounds_dir = out_dir / "sounds"
    sounds_dir.mkdir(parents=True, exist_ok=True)

    written_paths = []
    for sound_name, samples in sounds.items():
        path = sounds_dir / f"{sound_name}.wav"
        _write_wav(path, samples)
        written_paths.append(path)

    return sorted(written_paths)


def main(argv: list[str] | None = None) -> int:
    """
    Entry point.

    Args:
        argv: Command line arguments, defaults to sys.argv[1:].

    Returns:
        0 on success; 1 when the tokens are invalid (problems printed to stderr,
        nothing written); 2 when --out-dir would be outside PROJECT_ROOT or --name is
        invalid.
    """
    import argparse

    from design.validate import TokenError, load_tokens

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Synthesize UI sounds from design tokens")
    parser.add_argument(
        "--tokens",
        type=Path,
        default=Path(__file__).parent / "tokens.json",
        help="Path to tokens.json (default: design/tokens.json)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / ".build" / "generated",
        help="Output directory (default: .build/generated)",
    )
    parser.add_argument(
        "--name",
        default=os.getenv("DISTRO_NAME", "theme"),
        help="Theme name (default: DISTRO_NAME env var or 'theme'); accepted for CLI "
        "shape parity with design.generate, does not affect sound output",
    )

    args = parser.parse_args(argv)

    # Validate name (same rule as design.generate, kept for CLI parity even though
    # sound file names never include it).
    if not re.fullmatch(r"[a-z0-9_-]+", args.name):
        print(f"error: name must be lowercase letters, digits, '_' or '-', got {args.name!r}", file=sys.stderr)
        return 2

    # Validate out_dir is within PROJECT_ROOT (identical guard to design.generate.main).
    try:
        out_dir_resolved = args.out_dir.resolve()
        project_root_resolved = PROJECT_ROOT.resolve()
        if out_dir_resolved != project_root_resolved and project_root_resolved not in out_dir_resolved.parents:
            print("error: --out-dir must stay inside the project directory", file=sys.stderr)
            return 2
    except (ValueError, RuntimeError):
        print("error: invalid out-dir path", file=sys.stderr)
        return 2

    # Load and validate tokens
    try:
        tokens = load_tokens(args.tokens)
    except TokenError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    generate(tokens, args.out_dir, args.name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

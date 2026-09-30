"""Tests for design.generate_sounds (Vaihe 5, "Omat assetit" - own-production UI sounds)."""

from __future__ import annotations

import array
import math
import os
import sys
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

from design.generate_sounds import (
    ENVELOPE_FLOOR,
    INT16_MAX,
    PEAK_AMPLITUDE,
    SAMPLE_RATE,
    SOUND_NAMES,
    _chirp_phase,
    _exp_decay_envelope,
    _n_samples,
    _trapezoid_envelope,
    generate,
    main,
)
from design.validate import load_tokens

REAL_TOKENS_PATH = Path(__file__).resolve().parent.parent / "tokens.json"

# The real design tokens' four motion durations, read once so tests can assert each
# sound's actual clip length against the exact token value it is pinned to (see
# design/generate_sounds.py's own module docstring, "DESIGN ANCHOR").
_REAL_TOKENS = load_tokens(REAL_TOKENS_PATH)
_DURATIONS = _REAL_TOKENS["motion"]["duration"]

# Which sound is pinned to which motion.duration.* key (module docstring's table).
_SOUND_DURATION_KEY = {
    "click": "instant",
    "volume_tick": "instant",
    "screenshot_shutter": "instant",
    "menu_tick": "fast",
    "error": "fast",
    "success": "base",
    "trash_delete": "base",
    "login_chime": "slow",
}


def _read_wav_samples(path: Path) -> array.array:
    """
    Read a WAV file's raw samples back as a signed 16-bit int array.

    Args:
        path: Path to a mono/16-bit PCM WAV file.

    Returns:
        An `array.array("h", ...)` of every sample, in native host byte order
        (byte-swapped from the file's own little-endian storage on a big-endian host,
        mirroring the byte-order handling design.generate_sounds._quantize_to_pcm16
        does on write).
    """
    with wave.open(str(path), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


class TestSynthesisHelpers:
    """Direct checks of the core math, independent of any file I/O."""

    def test_exp_decay_envelope_starts_at_one(self):
        """The envelope's own maximum is at elapsed_s=0, matching the module docstring."""
        assert _exp_decay_envelope(0.0, 0.1) == pytest.approx(1.0)

    def test_exp_decay_envelope_reaches_floor_at_decay_span(self):
        """By construction, env(decay_span_s) equals ENVELOPE_FLOOR exactly."""
        assert _exp_decay_envelope(0.1, 0.1) == pytest.approx(ENVELOPE_FLOOR, rel=1e-9)

    def test_exp_decay_envelope_rejects_non_positive_span(self):
        """A zero/negative decay_span_s would divide by zero in the tau formula."""
        with pytest.raises(ValueError, match="decay_span_s"):
            _exp_decay_envelope(0.0, 0.0)

    def test_chirp_phase_is_zero_at_start(self):
        """phase(0) = 0 for every sweep - this is WHY no synthesis function here ever
        produces a click at t=0 (sin(0) = 0 regardless of frequency, see module
        docstring's envelope-shape-1 reasoning)."""
        assert _chirp_phase(0.0, 700.0, 1100.0, 0.1) == 0.0

    def test_chirp_phase_matches_constant_frequency_case(self):
        """When f0 == f1 (no sweep), the closed-form phase must reduce to the plain
        constant-frequency phase 2*pi*f*t."""
        f = 500.0
        t = 0.037
        assert _chirp_phase(t, f, f, 0.2) == pytest.approx(2 * math.pi * f * t)

    def test_trapezoid_envelope_shape(self):
        """0 at t=0, 1.0 through the sustain span, 0 at the very last instant."""
        attack_s, release_s, duration_s = 0.02, 0.04, 0.18
        assert _trapezoid_envelope(0.0, attack_s, release_s, duration_s) == pytest.approx(0.0)
        assert _trapezoid_envelope(duration_s / 2, attack_s, release_s, duration_s) == pytest.approx(1.0)
        assert _trapezoid_envelope(duration_s, attack_s, release_s, duration_s) == pytest.approx(0.0)

    def test_n_samples_matches_sample_rate(self):
        """100 ms at 44100 Hz is exactly 4410 samples (no rounding involved)."""
        assert _n_samples(100.0) == 4410


class TestGenerate:
    """Tests for generate() using the real, committed design/tokens.json."""

    def test_generate_writes_expected_file_count(self, tmp_path):
        """Between 6 and 8 short UI sounds are produced, exactly matching SOUND_NAMES."""
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        assert 6 <= len(SOUND_NAMES) <= 8
        assert len(result) == len(SOUND_NAMES)

    def test_generate_file_stems_match_sound_names(self, tmp_path):
        """Every written file's stem is one of the documented sound names, and vice versa."""
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        assert {p.stem for p in result} == set(SOUND_NAMES)

    def test_generate_writes_under_sounds_subdirectory(self, tmp_path):
        """All files land under <out_dir>/sounds/, not directly in out_dir."""
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        for path in result:
            assert path.parent == tmp_path / "sounds"
            assert path.suffix == ".wav"

    def test_generate_returns_sorted_paths(self, tmp_path):
        """Matches design.generate.generate()'s own sorted-return convention."""
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        assert result == sorted(result)

    def test_generate_all_files_exist_and_are_non_empty(self, tmp_path):
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        for path in result:
            assert path.exists()
            assert path.stat().st_size > 0

    def test_generate_files_are_valid_pcm16_mono_44100(self, tmp_path):
        """Every file must be readable back as mono/16-bit/44100 Hz uncompressed PCM."""
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        for path in result:
            with wave.open(str(path), "rb") as wav_file:
                assert wav_file.getnchannels() == 1, f"{path.name}: expected mono"
                assert wav_file.getsampwidth() == 2, f"{path.name}: expected 16-bit samples"
                assert wav_file.getframerate() == SAMPLE_RATE, f"{path.name}: expected {SAMPLE_RATE} Hz"
                assert wav_file.getcomptype() == "NONE", f"{path.name}: expected uncompressed PCM"

    def test_generate_durations_within_sane_ui_sound_range(self, tmp_path):
        """Every clip's real duration, read back from its own WAV header, is a short
        UI-sound length: 50-500 ms."""
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        for path in result:
            with wave.open(str(path), "rb") as wav_file:
                duration_ms = wav_file.getnframes() / wav_file.getframerate() * 1000.0
            assert 50 <= duration_ms <= 500, f"{path.name}: duration {duration_ms} ms out of range"

    def test_generate_durations_match_their_pinned_motion_token(self, tmp_path):
        """Each sound's real, read-back duration equals the exact motion.duration.*
        value (in ms) design/generate_sounds.py's module docstring pins it to - the
        "DESIGN ANCHOR" this generator is built around, not an incidental coincidence."""
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        by_stem = {p.stem: p for p in result}
        for sound_name, duration_key in _SOUND_DURATION_KEY.items():
            path = by_stem[sound_name]
            with wave.open(str(path), "rb") as wav_file:
                duration_ms = wav_file.getnframes() / wav_file.getframerate() * 1000.0
            expected_ms = _DURATIONS[duration_key]
            assert duration_ms == pytest.approx(expected_ms, abs=1.0), (
                f"{sound_name}.wav: expected ~{expected_ms} ms (motion.duration.{duration_key}), got {duration_ms}"
            )

    def test_generate_no_sample_reaches_int16_extreme(self, tmp_path):
        """No sample is ever the extreme int16 boundary value (+32767 or -32768), which
        would indicate a synthesis/envelope bug that let amplitude reach full scale
        (PEAK_AMPLITUDE=0.85 leaves ~15% headroom below both extremes by design)."""
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        for path in result:
            samples = _read_wav_samples(path)
            assert len(samples) > 0, f"{path.name}: no samples read"
            peak_magnitude = max(abs(min(samples)), abs(max(samples)))
            assert peak_magnitude < INT16_MAX, f"{path.name}: sample reached/exceeded int16 extreme"
            # Sanity check the intended headroom is actually being used, not just
            # "happens to not clip" - the real peak should be close to the designed
            # ceiling (some margin allowed for envelope shape/decay).
            assert peak_magnitude <= round(PEAK_AMPLITUDE * INT16_MAX)

    def test_generate_is_deterministic(self, tmp_path):
        """Regenerating from the same tokens produces byte-identical WAV files -
        no hidden randomness anywhere in the synthesis path."""
        first_dir = tmp_path / "first"
        second_dir = tmp_path / "second"
        first = generate(_REAL_TOKENS, first_dir, "test_theme")
        second = generate(_REAL_TOKENS, second_dir, "test_theme")
        for path_a, path_b in zip(first, second, strict=True):
            assert path_a.read_bytes() == path_b.read_bytes()

    def test_generate_overwrites_existing_files(self, tmp_path):
        """A second call must overwrite, not append to or fail on, existing sounds."""
        generate(_REAL_TOKENS, tmp_path, "test_theme")
        result = generate(_REAL_TOKENS, tmp_path, "test_theme")
        assert len(result) == len(SOUND_NAMES)


class TestMain:
    """Tests for main(), mirroring design.generate's own CLI test conventions."""

    def test_main_success_exit_code_zero(self, tmp_path):
        out_dir = tmp_path / "generated"
        with patch("design.generate_sounds.PROJECT_ROOT", tmp_path):
            exit_code = main(["--tokens", str(REAL_TOKENS_PATH), "--out-dir", str(out_dir), "--name", "test_theme"])
        assert exit_code == 0

    def test_main_writes_sound_files(self, tmp_path):
        out_dir = tmp_path / "generated"
        with patch("design.generate_sounds.PROJECT_ROOT", tmp_path):
            exit_code = main(["--tokens", str(REAL_TOKENS_PATH), "--out-dir", str(out_dir), "--name", "test_theme"])
        assert exit_code == 0
        wav_files = sorted((out_dir / "sounds").glob("*.wav"))
        assert {p.stem for p in wav_files} == set(SOUND_NAMES)

    def test_main_invalid_tokens_exit_code_one(self, tmp_path):
        broken_tokens_file = tmp_path / "broken.json"
        broken_tokens_file.write_text('{"invalid": "tokens"}')
        out_dir = tmp_path / "generated"

        with patch("design.generate_sounds.PROJECT_ROOT", tmp_path):
            exit_code = main(["--tokens", str(broken_tokens_file), "--out-dir", str(out_dir), "--name", "test_theme"])

        assert exit_code == 1
        assert not out_dir.exists(), "Nothing should be written on token error"

    def test_main_invalid_name_exit_code_two(self, tmp_path):
        out_dir = tmp_path / "generated"
        exit_code = main(
            ["--tokens", str(REAL_TOKENS_PATH), "--out-dir", str(out_dir), "--name", "InvalidName"]
        )
        assert exit_code == 2
        assert not out_dir.exists()

    def test_main_out_dir_outside_project_root_exit_code_two(self, tmp_path):
        outside_dir = tmp_path.parent / "outside_sounds_test"
        with patch("design.generate_sounds.PROJECT_ROOT", tmp_path):
            exit_code = main(
                ["--tokens", str(REAL_TOKENS_PATH), "--out-dir", str(outside_dir), "--name", "test_theme"]
            )
        assert exit_code == 2
        assert not outside_dir.exists()

    def test_main_sibling_directory_attack_prevented(self, tmp_path):
        """Regression: a sibling directory with a shared name prefix must be rejected
        (same attack design.generate's own test suite guards against)."""
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        proj_evil = tmp_path / "proj_evil"
        proj_evil.mkdir()

        with patch("design.generate_sounds.PROJECT_ROOT", proj_root):
            exit_code = main(
                ["--tokens", str(REAL_TOKENS_PATH), "--out-dir", str(proj_evil / "out"), "--name", "test_theme"]
            )

        assert exit_code == 2
        assert not (proj_evil / "out").exists()

    def test_main_parent_traversal_prevented(self, tmp_path):
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        evil_path = proj_root / "subdir" / ".." / ".." / "evil"

        with patch("design.generate_sounds.PROJECT_ROOT", proj_root):
            exit_code = main(
                ["--tokens", str(REAL_TOKENS_PATH), "--out-dir", str(evil_path), "--name", "test_theme"]
            )

        assert exit_code == 2

    def test_main_normal_subdirectory_allowed(self, tmp_path):
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        out_dir = proj_root / "build" / "generated"

        with patch("design.generate_sounds.PROJECT_ROOT", proj_root):
            exit_code = main(
                ["--tokens", str(REAL_TOKENS_PATH), "--out-dir", str(out_dir), "--name", "test_theme"]
            )

        assert exit_code == 0
        assert (out_dir / "sounds").exists()

    def test_main_default_tokens_path(self, tmp_path):
        """With no --tokens flag, the real design/tokens.json next to this module is used."""
        out_dir = tmp_path / "generated"
        with patch("design.generate_sounds.PROJECT_ROOT", tmp_path):
            exit_code = main(["--out-dir", str(out_dir), "--name", "test_theme"])
        assert exit_code == 0
        assert len(list((out_dir / "sounds").glob("*.wav"))) == len(SOUND_NAMES)

    def test_main_default_name_from_env(self, tmp_path):
        out_dir = tmp_path / "generated"
        with patch("design.generate_sounds.PROJECT_ROOT", tmp_path), patch.dict(os.environ, {"DISTRO_NAME": "my_distro"}):
            exit_code = main(["--tokens", str(REAL_TOKENS_PATH), "--out-dir", str(out_dir)])
        assert exit_code == 0

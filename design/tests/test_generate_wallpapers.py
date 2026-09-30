"""Tests for design.generate_wallpapers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from design.generate_wallpapers import (
    COMPOSITIONS,
    HEIGHT,
    WIDTH,
    generate_wallpapers,
    main,
    render,
)
from design.validate import load_tokens

TOKENS_PATH = Path(__file__).parent.parent / "tokens.json"


@pytest.fixture(scope="module")
def tokens() -> dict:
    """Real, validated project tokens (never a hand-built stub, per project style)."""
    return load_tokens(TOKENS_PATH)


@pytest.fixture(scope="module")
def generated(tokens, tmp_path_factory) -> tuple[Path, list[Path]]:
    """
    Run generate_wallpapers() exactly ONCE for the whole module and hand the
    result to every read-only assertion test below. Rendering all 5
    compositions in both modes is deterministic (design/generate_wallpapers.py's
    own docstring), so many tests can safely share one run instead of each
    paying its own full render cost again.
    """
    out_dir = tmp_path_factory.mktemp("wallpapers_out")
    result = generate_wallpapers(tokens, out_dir, "kuura")
    return out_dir, result


class TestRender:
    """Tests for render() -- one (composition, mode) pair at a time."""

    @pytest.mark.parametrize("composition", COMPOSITIONS)
    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_render_returns_expected_size_and_mode(self, tokens, composition, mode):
        """Every composition/mode pair must render as an RGB WIDTHxHEIGHT image."""
        image = render(tokens, composition, mode)
        assert image.size == (WIDTH, HEIGHT)
        assert image.mode == "RGB"

    def test_render_invalid_mode_raises(self, tokens):
        """render() must reject a mode that is neither 'light' nor 'dark'."""
        with pytest.raises(ValueError, match="mode must be"):
            render(tokens, COMPOSITIONS[0], "sepia")

    def test_render_invalid_composition_raises(self, tokens):
        """render() must reject a composition name outside COMPOSITIONS."""
        with pytest.raises(ValueError, match="composition must be"):
            render(tokens, "not-a-real-composition", "light")

    @pytest.mark.parametrize("composition", COMPOSITIONS)
    def test_light_and_dark_differ(self, tokens, composition):
        """
        Light and dark use different palettes (color.light vs color.dark in
        tokens.json), so every composition's rendered pixels must differ
        between the two modes -- mirrors design/tests/test_dod.py's own
        "mutating the input changes the output" principle, applied here to
        the light/dark mode switch instead of a token mutation.
        """
        light_image = render(tokens, composition, "light")
        dark_image = render(tokens, composition, "dark")
        assert light_image.tobytes() != dark_image.tobytes()

    def test_compositions_count_is_within_brief_range(self):
        """The working brief asks for 4-6 wallpaper designs."""
        assert 4 <= len(COMPOSITIONS) <= 6

    def test_render_is_deterministic(self, tokens):
        """The same tokens must always produce the exact same pixels."""
        first = render(tokens, "radial-glow", "light")
        second = render(tokens, "radial-glow", "light")
        assert first.tobytes() == second.tobytes()


class TestGenerateWallpapers:
    """Tests for generate_wallpapers(), reusing the shared `generated` fixture."""

    def test_writes_two_files_per_composition(self, generated):
        """generate_wallpapers() must write exactly len(COMPOSITIONS) * 2 files."""
        _out_dir, result = generated
        assert len(result) == len(COMPOSITIONS) * 2
        assert 8 <= len(result) <= 12

    def test_all_files_exist_under_wallpapers_subdir(self, generated):
        """Every written file must live directly under <out_dir>/wallpapers/."""
        out_dir, result = generated
        expected_dir = out_dir / "wallpapers"
        for path in result:
            assert path.exists()
            assert path.parent == expected_dir

    def test_result_is_sorted(self, generated):
        """generate_wallpapers() must return sorted paths (matches generate.py)."""
        _out_dir, result = generated
        assert result == sorted(result)

    def test_every_file_is_a_valid_png_of_expected_size(self, generated):
        """Every written file must be a real, openable PNG of exactly WIDTHxHEIGHT."""
        _out_dir, result = generated
        for path in result:
            with Image.open(path) as image:
                image.verify()
            # verify() can leave the file object unusable afterwards, so
            # re-open to actually check format/size/mode.
            with Image.open(path) as image:
                assert image.format == "PNG"
                assert image.size == (WIDTH, HEIGHT)
                assert image.mode == "RGB"

    def test_filenames_contain_name_composition_and_mode(self, generated):
        """File names must be self-explanatory: <name>-<composition>-<mode>.png."""
        _out_dir, result = generated
        names = {path.name for path in result}
        for composition in COMPOSITIONS:
            for mode in ("light", "dark"):
                assert f"kuura-{composition}-{mode}.png" in names

    def test_light_dark_pair_exists_for_every_composition(self, generated):
        """Every composition must have both a light and a dark file (a real pair)."""
        _out_dir, result = generated
        names = {path.name for path in result}
        for composition in COMPOSITIONS:
            assert f"kuura-{composition}-light.png" in names
            assert f"kuura-{composition}-dark.png" in names

    def test_at_least_one_composition_light_dark_pixels_differ(self, generated):
        """
        Direct file-based check (complementary to TestRender's in-memory
        check): read back the written PNGs for one composition and confirm
        light and dark are not byte-identical images.
        """
        _out_dir, result = generated
        by_name = {path.name: path for path in result}
        light_path = by_name["kuura-vertical-dawn-light.png"]
        dark_path = by_name["kuura-vertical-dawn-dark.png"]

        with Image.open(light_path) as light_image, Image.open(dark_path) as dark_image:
            assert light_image.tobytes() != dark_image.tobytes()

    def test_invalid_name_raises_before_writing(self, tokens, tmp_path):
        """An invalid theme name must raise and must not write any file."""
        with pytest.raises(ValueError, match="name.*lowercase"):
            generate_wallpapers(tokens, tmp_path, "Kuura Invalid!")
        assert not (tmp_path / "wallpapers").exists()

    def test_existing_files_are_overwritten(self, tokens, tmp_path):
        """A second run with the same name/out_dir must overwrite, not duplicate."""
        generate_wallpapers(tokens, tmp_path, "kuura")
        result = generate_wallpapers(tokens, tmp_path, "kuura")
        assert len(result) == len(COMPOSITIONS) * 2


class TestMain:
    """Tests for main() -- the CLI entry point, mirroring test_generate.py's own checks."""

    def test_main_success_exit_code_zero_and_writes_files(self, tmp_path):
        """main() should return 0 and write the expected files on success."""
        out_dir = tmp_path / "generated"

        # PROJECT_ROOT must be patched to tmp_path so the real out_dir (under
        # the OS temp directory) is accepted by the path-traversal guard --
        # mirrors design/tests/test_generate.py's own equivalent tests.
        with patch("design.generate_wallpapers.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
                "--name", "kuura",
            ])

        assert exit_code == 0
        wallpapers_dir = out_dir / "wallpapers"
        files = [p for p in wallpapers_dir.iterdir() if p.is_file()]
        assert len(files) == len(COMPOSITIONS) * 2

    def test_main_invalid_tokens_exit_code_one(self, tmp_path):
        """main() should return 1 when tokens are invalid and write nothing."""
        broken_tokens_file = tmp_path / "broken.json"
        broken_tokens_file.write_text('{"invalid": "tokens"}')
        out_dir = tmp_path / "generated"

        with patch("design.generate_wallpapers.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(broken_tokens_file),
                "--out-dir", str(out_dir),
                "--name", "kuura",
            ])

        assert exit_code == 1
        assert not out_dir.exists()

    def test_main_invalid_name_exit_code_two(self, tmp_path):
        """main() should return 2 when --name is invalid and write nothing."""
        out_dir = tmp_path / "generated"
        exit_code = main([
            "--tokens", str(TOKENS_PATH),
            "--out-dir", str(out_dir),
            "--name", "InvalidName",
        ])
        assert exit_code == 2
        assert not out_dir.exists()

    def test_main_out_dir_outside_project_root_exit_code_two(self, tmp_path):
        """main() should return 2 when --out-dir escapes PROJECT_ROOT."""
        outside_dir = tmp_path.parent / "outside_wallpapers"

        with patch("design.generate_wallpapers.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(outside_dir),
                "--name", "kuura",
            ])

        assert exit_code == 2
        assert not outside_dir.exists()

    def test_main_parent_traversal_prevented(self, tmp_path):
        """Regression: '..' traversal out of PROJECT_ROOT must be rejected."""
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        evil_path = proj_root / "subdir" / ".." / ".." / "evil"

        with patch("design.generate_wallpapers.PROJECT_ROOT", proj_root):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(evil_path),
                "--name", "kuura",
            ])

        assert exit_code == 2

    def test_main_default_name_from_env(self, tmp_path, monkeypatch):
        """main() should use DISTRO_NAME environment variable for default name."""
        out_dir = tmp_path / "generated"
        monkeypatch.setenv("DISTRO_NAME", "envtheme")

        with patch("design.generate_wallpapers.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
            ])

        assert exit_code == 0
        names = {p.name for p in (out_dir / "wallpapers").iterdir()}
        assert any(name.startswith("envtheme-") for name in names)

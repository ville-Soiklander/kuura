"""Tests for the pure parts of release/build_iso_host.sh (staging and safety checks).

The script is copied into a throwaway project tree so that PROJECT_DIR (derived from
the script location) points at synthetic inputs; mkarchiso, pacman-key and root are
never needed because only load_config / stage_profile / check_host's refusals run.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "release" / "build_iso_host.sh"


def _find_bash() -> str | None:
    """
    Locate a bash that runs scripts on THIS machine's file system.

    WHY not plain shutil.which("bash"): on Windows that can return the WSL launcher
    (System32\\bash.exe or a WindowsApps alias), which runs inside the default WSL
    distribution - a different file system, and broken whenever that distribution
    does not start. Git for Windows' bash is preferred there; other platforms use
    the bash on PATH.

    Returns:
        Path of a usable bash, or None when there is none.
    """
    candidates = []
    git = shutil.which("git")
    if git:
        # <git root>/cmd/git.exe or <git root>/bin/git.exe -> <git root>/bin/bash.exe
        candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
    found = shutil.which("bash")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        parent = candidate.parent.name.lower()
        if parent in ("system32", "windowsapps") or not candidate.is_file():
            continue
        return str(candidate)
    return None


BASH = _find_bash()

pytestmark = pytest.mark.skipif(BASH is None, reason="no native bash available")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal project tree: the script, a tiny profile, a fake repository, .env.example."""
    proj = tmp_path / "proj"
    (proj / "release").mkdir(parents=True)
    shutil.copyfile(SCRIPT, proj / "release" / "build_iso_host.sh")
    (proj / ".env.example").write_text("DISTRO_NAME=kuura\nARCH_ARCHIVE_DATE=2026/09/24\nREPO_DIR=.build/repo\n")
    profile = proj / "iso" / "profile"
    (profile / "airootfs" / "etc").mkdir(parents=True)
    (profile / "airootfs" / "root").mkdir()
    (profile / "airootfs" / "root" / "customize_airootfs.sh").write_text("#!/bin/sh\n")
    (profile / "airootfs" / "etc" / "pacman.conf").write_text("[@DISTRO_NAME@]\n")
    (profile / "packages.x86_64").write_text("@DISTRO_NAME@-meta\n")
    (profile / "pacman.conf").write_text("[@DISTRO_NAME@]\nServer = file:///home/builder/repo-src/x86_64\n")
    repo = proj / ".build" / "repo"
    (repo / "x86_64").mkdir(parents=True)
    (repo / "kuura.pub").write_text("pub\n")
    (repo / "x86_64" / "kuura.db.tar.zst").write_text("db\n")
    return proj


def _run(project: Path, snippet: str, work: Path, home: Path) -> subprocess.CompletedProcess[str]:
    """Source the staged script and run a snippet; HOME and HOST_BUILD_DIR are controlled."""
    script = project / "release" / "build_iso_host.sh"
    cmd = f'source "{script.as_posix()}"; {snippet}'
    env = {"PATH": str(Path(BASH).parent), "HOME": home.as_posix(), "HOST_BUILD_DIR": work.as_posix()}
    return subprocess.run([BASH, "-c", cmd], capture_output=True, text=True, env=env, check=False)


def test_stage_profile_substitutes_and_rewrites_server(project: Path, tmp_path: Path) -> None:
    """Template tokens are replaced and the Server line names the staged repo copy."""
    work = tmp_path / "work"
    result = _run(project, "load_config; fresh_dir; stage_profile", work, tmp_path)
    assert result.returncode == 0, result.stderr
    ctx = work / "ctx" / "profile"
    assert "@DISTRO_NAME@" not in (ctx / "pacman.conf").read_text()
    assert f"Server = file://{(work / 'ctx').as_posix()}/repo-src/x86_64" in (ctx / "pacman.conf").read_text()
    assert (ctx / "packages.x86_64").read_text() == "kuura-meta\n"
    assert (ctx / "airootfs" / "srv" / "repo" / "x86_64" / "kuura.db.tar.zst").is_file()
    assert (work / ".kuura-host-build").is_file()


def test_stage_profile_requires_built_repository(project: Path, tmp_path: Path) -> None:
    """Without the repository database the script stops and says to run make repo."""
    (project / ".build" / "repo" / "x86_64" / "kuura.db.tar.zst").unlink()
    result = _run(project, "load_config; fresh_dir; stage_profile", tmp_path / "work", tmp_path)
    assert result.returncode != 0
    assert "make repo" in result.stderr


def test_stage_profile_fails_when_server_line_missing(project: Path, tmp_path: Path) -> None:
    """A profile without the container Server line is an error, not a silent host-repo build."""
    (project / "iso" / "profile" / "pacman.conf").write_text("[@DISTRO_NAME@]\nServer = file:///elsewhere\n")
    result = _run(project, "load_config; fresh_dir; stage_profile", tmp_path / "work", tmp_path)
    assert result.returncode != 0
    assert "Server line" in result.stderr


def test_load_config_rejects_bad_distro(project: Path, tmp_path: Path) -> None:
    """DISTRO_NAME ends up in paths and globs, so odd values are refused."""
    (project / ".env.example").write_text("DISTRO_NAME=Bad_Name\nARCH_ARCHIVE_DATE=2026/09/24\nREPO_DIR=.build/repo\n")
    result = _run(project, "load_config", tmp_path / "work", tmp_path)
    assert result.returncode != 0
    assert "DISTRO_NAME" in result.stderr


def test_load_config_derives_source_date_epoch(project: Path, tmp_path: Path) -> None:
    """SOURCE_DATE_EPOCH defaults to midnight UTC of the archive date (2026-09-24 = 1790208000)."""
    result = _run(project, 'load_config; echo "$SOURCE_DATE_EPOCH"', tmp_path / "work", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1790208000"


def test_script_refuses_to_run_as_non_root(project: Path, tmp_path: Path) -> None:
    """Executed directly (not sourced) as a normal user the script fails before touching anything."""
    script = project / "release" / "build_iso_host.sh"
    work = tmp_path / "work"
    env = {"PATH": str(Path(BASH).parent), "HOME": tmp_path.as_posix(), "HOST_BUILD_DIR": work.as_posix()}
    result = subprocess.run([BASH, str(script)], capture_output=True, text=True, env=env, check=False)
    assert result.returncode != 0
    assert not work.exists()

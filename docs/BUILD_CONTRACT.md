# Build contract

This document is the locked interface for the reproducible package build.
Implementations (Containerfile, scripts, Makefile, CI) must follow it exactly;
change it only deliberately, and update every implementation in the same change.

## Goals

- `make repo` produces a **signed pacman repository** in a clean container.
- The result does not depend on the state of the developer machine.
- The metapackage installs into a fresh Arch container from that repository.

## Configuration (environment variables, see `.env.example`)

| Variable | Meaning |
|---|---|
| `DISTRO_NAME` | Codename used in package, repository and image names. |
| `CONTAINER_ENGINE` | `podman` (default) or `docker`. |
| `ARCH_ARCHIVE_DATE` | `YYYY/MM/DD` snapshot of the Arch Linux Archive that pins every package version. |
| `REPO_DIR` | Output directory of the repository, relative to the project root. |
| `GPG_KEY_ID` | Fingerprint of the signing key. Empty means "generate a throwaway development key". |

No script may hard code any of these values or any absolute path.

## Make targets

| Target | Behaviour |
|---|---|
| `make image` | Build the build image `localhost/$(DISTRO_NAME)-build` from `build/Containerfile`. |
| `make repo` | Depends on `image`. Builds every `packages/*/PKGBUILD` in the container, signs the packages and the repository database, writes the result to `$(REPO_DIR)/x86_64/`. |
| `make verify-install` | Depends on `repo`. Starts a **fresh** Arch container, trusts the repository key, enables the repository with `SigLevel = Required`, runs `pacman -Syu` and installs `$(DISTRO_NAME)-desktop`. Exit code 0 only if every step succeeds. |
| `make check` | Runs `tools/check_forbidden_terms.py` and `ruff check .`. |
| `make test` | Runs `pytest`. |
| `make clean` | Removes `.build/` and the build image. |

Every target fails with a non-zero exit code on the first error (`set -euo pipefail` in shell scripts).

Configuration precedence: the Makefile includes `.env.example` and then `.env`, so
assignments in those files override variables that are only set in the process
environment. Override a value for one run with `make VAR=value`, which beats both.

Container engine: builds must also work with a **rootless** Podman (the default
on CI runners); the build never needs a root-owned container engine.

## Container

- Base image: `docker.io/library/archlinux:base` (fully qualified name).
- The pacman mirror list inside the image points at
  `https://archive.archlinux.org/repos/$ARCH_ARCHIVE_DATE/$repo/os/$arch`, so all
  package versions are frozen to that day. The Plasma and KWin versions this
  yields are recorded in `docs/VERSIONS.md`.
- `makepkg` refuses to run as root: builds run as the unprivileged user `builder`.
- Set `SOURCE_DATE_EPOCH` for reproducible timestamps.
- Sources are copied into the container, never bind-mounted from a Windows drive
  (ownership and permissions of such mounts are unreliable). On Windows, build
  from a checkout on the WSL filesystem.

## Signing

- `GPG_KEY_ID` empty: generate a passphrase-less throwaway key in a `GNUPGHOME`
  under the home directory of the unprivileged build user **inside the build
  container** (never on a mounted path), export its public key to
  `$(REPO_DIR)/$(DISTRO_NAME).pub`. The key dies with the container.
- `GPG_KEY_ID` set: use that key from the environment's GnuPG home (CI imports it
  from a secret before the build).
- Packages are signed by `makepkg --sign`, the database by `repo-add --sign`.
- **The private key is never written into the repository or the image.**

## Package conventions

- One directory per package: `packages/<name>/PKGBUILD`.
- The metapackage is `$(DISTRO_NAME)-desktop`: `arch=(any)`, no sources, only
  `depends`. Its dependency list is limited to the Plasma session, the KWin
  compositor, the display manager, the file manager, the terminal, Kvantum,
  audio and network applets, the PipeWire audio stack (PulseAudio and JACK
  compatibility layers; `pipewire-jack` is listed explicitly and FIRST, because
  pacman resolves dependencies depth first in list order and would otherwise pick
  the unrelated `jack2` server as the `jack` provider), Wayland support,
  the two font packages (Inter, JetBrains Mono), the cursor theme
  (Capitaine, chosen over KDE's default Breeze cursors for a distinct look
  fitting this project's own visual language - see `docs/ASSETS.md`), and
  `$(DISTRO_NAME)-assets` (a package of this monorepo: the own-production
  icon set, wallpapers and UI sounds, Vaihe 5 - see
  `packages/kuura-assets/PKGBUILD`'s own SCOPE comment for exactly what is
  and is not live-verified yet), `$(DISTRO_NAME)-firefox` (a package of
  this monorepo: Firefox with a preinstalled, token-themed default profile
  and about:config defaults, Vaihe 6 - the profile pre-seeding mechanism was
  independently verified against a real, fresh Firefox boot before this
  package was added here, not merely documented), and `$(DISTRO_NAME)-sddm`
  (a package of this monorepo: the SDDM login-screen theme, Vaihe 6 - the
  generated greeter was independently verified with a real
  `sddm-greeter-qt6 --test-mode` boot under Xvfb before this package was
  added here).
- Every PKGBUILD passes `namcap` without errors.
- Third-party assets (fonts, icons) are listed in `docs/ASSETS.md` before merge.
- `packages/calamares/PKGBUILD` is the one exception to "one directory, one
  first-party package" above: it is vendored, not authored by this project
  (see its own header comment for the exact AUR commit and the reasoning).
  Calamares (the Vaihe 7 KDE installer) is AUR-only, and the Arch Linux
  Archive only mirrors the official repos, so `ARCH_ARCHIVE_DATE` cannot pin
  it the way it pins everything else here; the AUR package's own PKGBUILD is
  instead pinned by vendoring it at an exact, recorded git commit of
  `https://aur.archlinux.org/calamares.git`. This also makes it the first
  package in this monorepo whose `source=()` is non-empty: every other
  PKGBUILD here ships pure local config/skel files and fetches nothing over
  the network, while Calamares' build downloads its release tarball from
  Codeberg (upstream's own host) at build time, verified only by the
  `sha256sums` the AUR PKGBUILD itself carries - a real, if narrow, gap in
  this project's otherwise fully archive-pinned supply chain.

## Repository layout produced by `make repo`

```
$(REPO_DIR)/x86_64/
  $(DISTRO_NAME).db.tar.zst   (+ .sig, and the plain `.db` symlink)
  $(DISTRO_NAME).files.tar.zst
  <package>.pkg.tar.zst       (+ .sig)
$(REPO_DIR)/$(DISTRO_NAME).pub   public key
```

## Release

Vaihe 8 produces a signed release **locally**; nothing is uploaded or published by any
target. Two steps, deliberately separate so a release never rebuilds the image it
describes:

### `make iso-host` - ISO on an Arch build host

Runs `release/build_iso_host.sh`: `mkarchiso` directly on an Arch Linux host, **as
root** (e.g. the `kuura-arch-build` WSL distribution). It consumes the repository from
`make repo` and does the following, failing loudly (`set -euo pipefail`) at the first
problem:

1. Stage `iso/profile/` and a copy of `$(REPO_DIR)` in `$HOST_BUILD_DIR/ctx` (default
   `$HOME/$(DISTRO_NAME)_iso_build`, must be on a native Linux filesystem; it is only
   deleted if it carries the script's marker file). `@DISTRO_NAME@` is substituted and
   the build-time `[$(DISTRO_NAME)]` `Server` line is pointed at the staged copy.
   The staged `pacman.conf` (never a file under `/etc`) is **pinned to the archive
   snapshot**: every uncommented `Include = /etc/pacman.d/mirrorlist` (`[core]`,
   `[extra]`) becomes `Server = https://archive.archlinux.org/repos/$(ARCH_ARCHIVE_DATE)/$repo/os/$arch`,
   the same URL the Podman path uses. Without this the host's rolling mirrorlist was
   used and the ISO carried newer packages than `docs/VERSIONS.md` states. A missing or
   malformed `ARCH_ARCHIVE_DATE`, or a profile with no mirrorlist `Include` to pin,
   stops the build. The staged conf also sets `CacheDir` to `$HOST_BUILD_DIR/pkgcache`:
   mkarchiso's pacstrap runs with `-c` (host cache) and the cache is keyed by file name,
   so a dedicated, freshly created cache keeps host leftovers out (packages are
   downloaded on every run).
2. Import the repository key into the host keyring and `--lsign-key` it.
3. Delete stale `/var/cache/pacman/pkg/$(DISTRO_NAME)-*.pkg.tar.zst*`. This is
   mandatory: pacman's cache is keyed by file name and has served stale packages when a
   rebuilt package kept its name and version.
4. Fresh `work/` and `out/`, then `mkarchiso -v` with `SOURCE_DATE_EPOCH` (derived from
   `ARCH_ARCHIVE_DATE` unless set).
5. Replace the ISO in `.build/iso/` (older ISOs are removed) and compare the SHA-256 of
   the copy with mkarchiso's output.

The staging steps duplicate `stage_context()` in `iso/build_iso.sh` (that script runs
its `main` when sourced, so the logic cannot be shared without editing it): keep the
two in sync when the profile layout changes.

### `make release` - signed release directory

Runs `python3 -m release.release` (`release/release.py`, unit-tested in
`tests/test_release.py`) and writes `.build/release/$(DISTRO_NAME)-<version>/`:

| File | Content |
|---|---|
| `<name>.iso` | The single ISO from `.build/iso/` (zero or several: error) |
| `SHA256SUMS` | `sha256sum` format, every file below except the signature |
| `SHA256SUMS.sig` | Detached GPG signature by `RELEASE_GPG_KEY`, verified after creation |
| `RELEASE_NOTES.md` | Version, date, ISO size and SHA-256, `ARCH_ARCHIVE_DATE`, Plasma and KWin versions from `docs/VERSIONS.md`, git commit |
| `LICENSE`, `TRADEMARKS.md`, `ASSETS.md` | Copies; a missing source file is an error |

Rules:

- The version comes from the `VERSION` file only (`MAJOR.MINOR.PATCH`).
- `RELEASE_GPG_KEY` (key id, fingerprint or e-mail of a key already in the GPG keyring;
  empty in `.env.example`, set it in `.env`) is required. The target never creates or
  falls back to another key.
- The git tree must have no changes to tracked files and `HEAD` must be tagged
  `v<version>`. `RELEASE_ALLOW_DIRTY=1` overrides both for a dry run and marks the notes
  "UNOFFICIAL BUILD".
- The directory is built as `<name>.partial` and renamed on success, so a failed run
  leaves no half-finished release; running again replaces the previous result.

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
  the unrelated `jack2` server as the `jack` provider), Wayland support
  and the two font packages (Inter, JetBrains Mono).
- Every PKGBUILD passes `namcap` without errors.
- Third-party assets (fonts, icons) are listed in `docs/ASSETS.md` before merge.

## Repository layout produced by `make repo`

```
$(REPO_DIR)/x86_64/
  $(DISTRO_NAME).db.tar.zst   (+ .sig, and the plain `.db` symlink)
  $(DISTRO_NAME).files.tar.zst
  <package>.pkg.tar.zst       (+ .sig)
$(REPO_DIR)/$(DISTRO_NAME).pub   public key
```

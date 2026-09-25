# kuura

A desktop distribution built **on top of** Arch Linux: KDE Plasma 6 on Wayland with
a calm, glass-like visual language of its own.

**Status: early.** The reproducible package build and the design-token pipeline
exist. The compositor material effect, icons, wallpapers, installer and ISO do not.

## What is here

- **Reproducible package build** - a signed pacman repository and the metapackage
  `kuura-desktop`, built in a clean container from a frozen snapshot of the Arch
  Linux Archive (see `docs/VERSIONS.md`). The contract is in `docs/BUILD_CONTRACT.md`.
- **Design tokens** - `design/tokens.json` is the single source of truth for
  radii, spacing, type, motion, material parameters and colours. Generators turn it
  into a KDE colour scheme, a Kvantum configuration, GTK CSS and a QML singleton.
- **Guard rails** - a hash based checker keeps forbidden product names out of the
  repository, and CI builds the repository and installs the metapackage from it.

## Quick start

Requirements: Linux (on Windows use WSL2), Podman or Docker, GNU make, Python 3.11.

```sh
cp .env.example .env          # optional local overrides; defaults live in .env.example
pip install -r requirements.txt
make check                    # forbidden-name check and linter
make test                     # unit tests
make repo                     # build and sign the package repository into .build/repo
make verify-install           # install the metapackage from it into a fresh container
python -m design.generate     # write theme files for both modes into .build/generated
```

Builds run as an unprivileged user; rootless Podman is supported and recommended.
The build uses a throwaway signing key that exists only inside the build container.

## Layout

| Path | Content |
|---|---|
| `design/` | tokens, validator, generators and their tests |
| `packages/` | PKGBUILDs, including the metapackage |
| `build/` | container image, build, signing and install-verification scripts |
| `tools/` | repository guard rails |
| `docs/` | build contract, pinned versions, glossary, third-party assets, licenses |

## Rules of the project

- Everything visual is derived from `design/tokens.json`; nothing is hard coded.
- Every third-party asset is listed in `docs/ASSETS.md` before it is merged.
- The project uses its own names for every component (see `docs/GLOSSARY.md`).

## License

GPL-3.0-or-later for themes, configuration and scripts (see `LICENSE`). Other
components are licensed as described in `docs/LICENSES/README.md`.

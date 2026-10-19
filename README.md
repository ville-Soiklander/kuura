# kuura

kuura is a desktop distribution built **on top of** Arch Linux: KDE Plasma 6 on
Wayland, with a calm, glass-like visual language of its own. Everything visual
(colours, radii, spacing, type, motion, the glass material) is derived from one
file, `design/tokens.json`, and the icons, wallpapers and sounds are generated
by this repository.

**Status: first release, early.** There is a live ISO that boots under BIOS and
UEFI, a graphical installer (Calamares) and a screenshot test harness that
checks both the live desktop and a freshly installed system. Expect rough edges;
see [Known limits](#known-limits).

## Get it

Download the ISO from the release page together with its checksum file
(`SHA256SUMS`) and the GPG signature of that file, then verify before writing
the image to a medium:

```sh
sha256sum --check --ignore-missing SHA256SUMS      # the ISO must report: OK
gpg --verify <signature-file> SHA256SUMS           # needs the project's public key
```

The release artefacts are produced by `make release`. The public signing key and
its fingerprint are published with the release; compare the fingerprint that
`gpg --verify` prints with the published one.

## Install

See [docs/INSTALL.md](docs/INSTALL.md): requirements, writing the ISO to a USB
stick, the live session and the installer pages.

## Known limits

- kuura has no package server of its own yet. kuura's own packages are updated
  only by installing a newer release.
- The automated tests run in virtual machines; behaviour on physical hardware is
  that of the stock Arch kernel and firmware packages.

## Build from source

Requirements: Linux (on Windows use WSL2), Podman or Docker, GNU make, Python 3.11.

```sh
cp .env.example .env          # optional local overrides; defaults live in .env.example
pip install -r requirements.txt
make check                    # forbidden-name check and linter
make test                     # unit tests
make repo                     # build and sign the package repository into .build/repo
make verify-install           # install the metapackage from it into a fresh container
make iso                      # build the live ISO into .build/iso
python -m design.generate     # write theme files for both modes into .build/generated
```

Builds run as an unprivileged user; rootless Podman is supported and recommended.
The build uses a throwaway signing key that exists only inside the build container.

Screenshot harness (boots virtual machines; needs QEMU):

| Target | What it does |
|---|---|
| `make vm-image` | build the guest image the harness boots |
| `make shots` | capture every state and compare with the goldens |
| `make goldens-review` | capture and produce a side-by-side review report |
| `make goldens-accept` | accept the captured shots as the new goldens (a human decision) |
| `make installed-verify` | boot the ISO, run a real install and diff the installed system |

The contracts behind these steps are in `docs/BUILD_CONTRACT.md`,
`docs/HARNESS_CONTRACT.md` and `docs/ISO_CONTRACT.md`.

## Layout

| Path | Content |
|---|---|
| `design/` | tokens, validator, generators (theme files, icons, wallpapers, sounds) and their tests |
| `packages/` | PKGBUILDs: the metapackage, the Frost compositor effect, shell, login screen, installer configuration, assets, browser policies |
| `build/` | container image, build, signing and install-verification scripts |
| `iso/` | the archiso profile and the ISO build scripts |
| `harness/` | screenshot and install-verification harness, goldens |
| `tools/` | repository guard rails (forbidden-name checker) |
| `tests/` | repository-level tests |
| `docs/` | contracts, pinned versions, glossary, install guide, third-party assets |
| `LICENSES/` | license texts and the component-to-license mapping |

## Rules of the project

- Everything visual is derived from `design/tokens.json`; nothing is hard coded.
- Every third-party asset is listed in `docs/ASSETS.md` before it is merged.
- The project uses its own names for every component (see `docs/GLOSSARY.md`).

## License

Themes, configuration and scripts are GPL-3.0-or-later (see `LICENSE`). The
license texts and the per-component summary are in [`LICENSES/`](LICENSES/README.md);
third-party assets and their licenses are listed in [`docs/ASSETS.md`](docs/ASSETS.md).
Packages installed from Arch Linux keep their own licenses.

The name kuura and the project's marks are covered separately, see
[TRADEMARKS.md](TRADEMARKS.md).

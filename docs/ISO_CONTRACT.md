# ISO contract

This document is the locked interface for Vaihe 7 (the live ISO and the
Calamares installer). Implementations (the archiso profile, the Makefile, the
Calamares configuration package, the harness extension that boots and
installs from the ISO) must follow it exactly; change it only deliberately,
and update every implementation in the same change. See also
`docs/BUILD_CONTRACT.md` (package build), `docs/HARNESS_CONTRACT.md`
(screenshot/VM harness) and `distro-tyonkulku.md` §3 Vaihe 7 (the brief).

## Goals

- `make iso` produces a hybrid UEFI+BIOS-bootable ISO containing kuura's own
  signed package repository, buildable and bootable without any network
  access beyond fetching packages.
- Booting the ISO lands directly in the same themed KDE Plasma desktop that
  `make vm-image`/`make shots` already produce and verify — no new theming
  work, no separate "live" visual identity.
- Calamares, themed and pre-configured with sensible defaults, installs that
  same system to a target disk.
- Definition of Done for this project (interpreted concretely, see "DoD" below):
  the VM half is fully automated and enforced by this repository's own tests;
  the physical-hardware half is the project owner's own manual, one-time,
  untracked verification step — it is explicitly not something this
  repository's automation claims to prove.

## Package sources: two mirrors, two different lifetimes — do not conflate them

This project pins every official-repo package to one Arch Linux Archive
snapshot (`ARCH_ARCHIVE_DATE`) for reproducible **building**. The ISO must
**not** carry that pin into the product it ships:

- **Build-time mirror (pinned, container-local only):** exactly the existing
  mechanism in `build/Containerfile` — `/etc/pacman.d/mirrorlist` inside the
  *build* container points at
  `https://archive.archlinux.org/repos/$ARCH_ARCHIVE_DATE/...`. `mkarchiso`
  runs inside a container built the same way, so the packages it selects for
  the squashfs are exactly the ones `make repo`/`make vm-image` already use.
- **Shipped mirror (unpinned, inside the ISO and the installed system):** the
  profile's own `pacman.conf` (the file `mkarchiso` copies into the live
  image's `/etc/pacman.conf`, and from there into every install Calamares
  performs) must keep the upstream `releng` reference profile's
  `Include = /etc/pacman.d/mirrorlist` line for `[core]`/`[extra]`, resolved
  live by `reflector`/`choose-mirror.service` at boot the same way upstream
  Arch does it. **Never replace this with the archive URL.** A shipped system
  permanently frozen to one historical snapshot could never receive a
  security update after installation — that would be a serious, silent
  defect, not a simplification.

kuura's own packages reach the live image through a **third**, separate
repository entry, `[$DISTRO_NAME]`, added to the profile's `pacman.conf`
pointing at a `file://` path where the ISO carries a full copy of
`$(REPO_DIR)` (produced by `make repo`, including the signed database and the
public key). This entry exists so the live session and Calamares can install
`$(DISTRO_NAME)-desktop` and `$(DISTRO_NAME)-installer-config` from local
media, with no network dependency and no change to the archive-pin
discipline above. **Scope boundary, deliberately out for Vaihe 7:** whether
an *installed* kuura system keeps this repository entry afterwards (pointing
at media that is no longer present) or has it stripped post-install is an
open question for Vaihe 8 (kuura does not yet have any real ongoing package
server to point it at instead) — note it in `packages.x86_64`'s own comments,
do not silently decide it either way by accident.

## Directory layout

```
iso/
  profile/            archiso profile, based on upstream releng
    profiledef.sh      iso_name/iso_label/iso_version read from $DISTRO_NAME
                        and $SOURCE_DATE_EPOCH (never hard coded); bootmodes
                        kept as releng's bios.syslinux + uefi.systemd-boot
    pacman.conf         releng's own file plus the [$DISTRO_NAME] file:// entry
    packages.x86_64     releng's base-live-system packages, plus
                        $(DISTRO_NAME)-desktop, calamares,
                        $(DISTRO_NAME)-installer-config
    airootfs/            overlay files; see "Live session" below
packages/
  calamares/           already done (vendored, see its own header)
  kuura-installer-config/   NEW first-party package: settings.conf,
                        modules/*.conf, branding/$(DISTRO_NAME)/ — depends on
                        calamares; see "Calamares configuration" below
design/
  generators/
    calamares_branding.py   NEW 6th token-driven generator (see below)
```

## Make targets (additions)

| Target | Behaviour |
|---|---|
| `make iso` | Depends on `repo`. Copies `$(REPO_DIR)` into the profile's local repo path, runs `mkarchiso` inside a container built from the pinned snapshot (same image family as `make repo`), writes the resulting `.iso` to `.build/iso/`. |

## Live session: reuse the harness's own, already-verified autologin — do not re-derive it

`harness/vm/Containerfile` already solves "boot straight into a themed
Plasma Wayland session with no login prompt," and it is already trusted
(every golden screenshot in `harness/goldens/` was captured through it). The
ISO's `airootfs` overlay must reuse the identical mechanism, not a new one:

- A fixed unprivileged live user (`useradd ... --groups video,render,input,audio`,
  password locked with `passwd -l`, matching `harness/vm/Containerfile`'s
  `DESKTOP_USER` pattern), and
- `/etc/sddm.conf.d/10-autologin.conf`:
  ```
  [General]
  DisplayServer=wayland

  [Autologin]
  User=<live user>
  Session=plasma
  Relogin=false
  ```
- `systemctl set-default graphical.target` and `systemctl enable sddm.service`
  applied via `iso/profile/airootfs/root/customize_airootfs.sh` — confirmed
  real and current for the pinned `archiso 90-1` by reading `mkarchiso`
  itself (it calls `arch-chroot ... /root/customize_airootfs.sh` late in the
  build, after packages are installed, then deletes the script; the symlink
  `systemctl enable` creates works without a running systemd exactly as
  `harness/vm/Containerfile` already relies on).

**Rootless build, confirmed from `mkarchiso`'s own source (not assumed):**
this exact pinned version explicitly supports `EUID != 0`: every privileged
operation is wrapped in `_unshare()`, which runs `unshare --map-auto
--map-root-user -- "$@"` whenever not already root, and `pacstrap`/
`arch-chroot` both take a `-N` flag for the same unprivileged case. `make iso`
should therefore be able to reuse the existing rootless-podman/`builder`-user
pattern `make repo` already uses, rather than needing a privileged
container — but confirm this empirically (does nested unprivileged
user-namespace creation actually work inside *this* podman setup?) before
relying on it; fall back to `--privileged` only if that genuinely fails, and
say so plainly rather than reaching for it by default.

## Calamares configuration (`packages/kuura-installer-config`)

A new first-party package, `depends=('calamares')`, built and tested through
the existing pipeline exactly like `packages/kuura-shell`
(`docs/SHELL_CONTRACT.md` is the precedent to follow for structure). Its
`build()` runs `design/generators/calamares_branding.py` against
`design/tokens.json` (the same `python3 -m design.generate`-style call
`kuura-shell` already makes) to produce `branding/$(DISTRO_NAME)/branding.desc`
from real token values — colors are never hand-written hex literals here, the
same rule every other generator already follows.

Locked product decisions (confirmed with the project owner 2026-10-08, do not
re-ask):

- **No separate root password.** `modules/users.conf`: `setRootPassword: false`,
  a `sudoersGroup` entry, no root login — sudo-only, matching common current
  desktop-distro practice.
- **ext4 default, LUKS available but not forced.** `modules/partition.conf`:
  `defaultFileSystemType: ext4`; `luksGeneration` present as an offered
  choice; `initialPartitioningChoice`/`initialSwapChoice` must not force
  encryption or a particular swap scheme on the user.
- **Branding: sidebar/icon only, no slideshow, no new artwork.** Checked:
  this project has **no dedicated wordmark/logo asset** — `kuura-assets` only
  generates functional UI icons (file manager, settings, terminal, browser,
  folder, mimetypes, the systray glyph) plus wallpapers and sounds, none of
  them a brand mark. Do not invent a new logo for this — that is a real
  visual-design decision, out of scope for a config-only phase. Instead:
  `productIcon`/`productLogo` reuse the existing systray glyph (`design/icons/glyphs.py`'s
  `"systray"` entry, rendered the same way `packages/kuura-assets` already
  renders it via `design/generators/icon_svg.py`'s `render_icon()`), and
  `productWelcome` reuses one of the existing generated wallpapers (pick
  whichever one `kuura-assets` already stages, do not generate a new image).
  The `productName` **text** string ("Kuura") carries the actual branding.
  **REVISED 2026-10-08** (real live-boot testing found this wrong): Calamares
  3.4.2 treats `slideshow:` as a REQUIRED top-level `branding.desc` key —
  omitting it entirely causes a fatal `bail()` at launch (confirmed directly:
  `Branding.cpp`'s `get()` helper throws `YAML::KeyNotFound` with no
  fallback; confirmed live on a booted ISO: `FATAL in ".../branding.desc":
  key not found: slideshow`). The correct way to express "no slideshow" is
  an **empty sequence**, `slideshow: []` — confirmed from the same source
  that the sequence-processing loop performs no nonzero-count check, so zero
  items is accepted silently. This does not change the underlying decision
  (still no new artwork, still no slideshow), only the YAML form of
  expressing it — see `design/generators/calamares_branding.py`'s own
  docstring for the full correction.

Module sequence (confirmed from Calamares' own real `settings.conf` for the
pinned 3.4.2 build, see `packages/calamares/PKGBUILD`'s header for the
source): show phase `welcome, locale, keyboard, partition, users, summary`;
exec phase `partition, mount, unpackfs, machineid, locale, keyboard,
localecfg, fstab, initcpiocfg, initcpio, users, displaymanager, networkcfg,
hwclock, services-systemd, initramfs, bootloader, umount`; final show
`finished`. Start from Calamares' own real default `modules/*.conf` for every
module not listed above (do not invent config for modules this project has
no opinion about) — fetch them from the same source the vendoring task used
(`https://codeberg.org/Calamares/calamares`, tag `v3.4.2`), not from memory.

**REVISED 2026-10-12** (real live-boot testing found this exec list, as
shipped upstream, does not actually work with this project's own Calamares
build): `initramfs` must be **commented out** of the actual shipped
`settings.conf` — `packages/calamares/PKGBUILD`'s own `_skip_modules`
deliberately never builds that generic module for an Arch target (only
`initcpio`+`initcpiocfg`, the Arch/mkinitcpio-specific pair, are built and
already cover this responsibility), so leaving `initramfs` enabled makes
Calamares fatally bail at launch with "could not be loaded: initramfs@
initramfs" — confirmed directly on a real QEMU-booted ISO. The sequence list
above still documents the real, unmodified upstream default (useful context
for what Calamares ships generically); `settings.conf.in`'s own header
comment is the authoritative record of the one line actually commented out
in the shipped file.

## Live-only cleanup (locked 2026-10-12 — real, confirmed install-blocking findings)

`unpackfs` copies the **entire live rootfs verbatim** onto the target disk —
every file, whether it came from a pacman package or was written directly by
archiso's own build process or by this project's `airootfs/` overlay, with no
distinction between "meant for the live medium" and "meant for the installed
product." This was discovered by actually running a real install through to
completion on a real QEMU target disk (not assumed) and finding it fails.
Two concrete, confirmed-from-source bugs, both the same root cause:

- **`/etc/mkinitcpio.conf.d/archiso.conf`** — owned by no package (`pacman -Qo`
  confirms this), written directly into the live rootfs by archiso's own
  build process. Its real content:
  `HOOKS=(base udev microcode modconf kms memdisk archiso archiso_loop_mnt
  archiso_pxe_common archiso_pxe_nbd archiso_pxe_http archiso_pxe_nfs block
  filesystems keyboard)` — hooks that only make sense booting from a
  loop-mounted ISO or PXE, never on an installed disk. Left in place, the
  `initcpio` module's `mkinitcpio -P` run inside the target chroot fails
  outright (`Command <i>mkinitcpio</i> finished with exit code 1`, confirmed
  live) — **this blocks every install**, automated or manual, until removed.
- **`/etc/sddm.conf.d/10-autologin.conf`** — also owned by no package (this
  project's own file, from `iso/profile/airootfs/`, documented in its own
  header as the live-session mechanism — see "Live session" above). Hardcodes
  `User=liveuser`, an account that only exists on the live medium. Left in
  place on the target, SDDM on the installed system would try to autologin as
  a nonexistent user regardless of what the real user's own `users.conf`
  autologin choice was — confirmed present and unowned the same way.

Both must be deleted from the target chroot. There may be other untracked,
live-only files following the same pattern (`pacman -Qo` returns "No package
owns..." for them) — whoever implements this must check for more, not assume
these two are the only ones, by diffing `pacman -Qlq` (all files owned by any
package) against the live rootfs's real file list, or an equivalent real
check, rather than guessing.

**IMPLEMENTED 2026-10-12 — real diff run, more found.** The diff this
section asks for was actually run (`pacman -Qlq` vs. `find / -xdev -type f
-o -type l`, scoped to exclude `/proc /sys /run /tmp /home /root`) against
the real built ISO, using a full `unsquashfs` extraction rather than a
kernel loop mount — the kernel squashfs driver in the recon environment
could not reliably decode this image's xz+BCJ-filtered fragments
(`SQUASHFS error: Unable to read fragment cache entry`, confirmed
reproducible in `dmesg` against two independent copies of the same file,
byte-identical by `sha256sum`); `unsquashfs` (full userspace liblzma)
decoded every file correctly. This is a recon-environment limitation, not a
kuura bug — noted here in case a future session hits the same thing.

The two files above were confirmed present and unowned. The diff also found:

- **`/etc/mkinitcpio.d/linux.preset`** — unowned (confirmed: `pacman -Qo`
  says "No package owns" it; neither the `linux` nor `mkinitcpio` package's
  own real `files` list mentions it — on stock Arch this file is generated
  by a pacman hook, `/usr/share/libalpm/hooks/90-mkinitcpio-install.hook`
  calling `/usr/share/libalpm/scripts/mkinitcpio install`, never shipped
  directly by a package). Its content on this ISO is `PRESETS=('archiso')`
  / `archiso_config='/etc/mkinitcpio.conf.d/archiso.conf'` — pointing
  straight at the file deleted above. **Deleting only `archiso.conf` is
  necessary but not sufficient**: with it gone, Calamares' `initcpio`
  module (`initcpio.conf`'s `kernel: linux`, i.e. `mkinitcpio -p linux`)
  would still fail, now looking for a preset config that no longer exists.
  The fix deletes this file too, then regenerates it the real way:
  `echo mkinitcpio | /usr/share/libalpm/scripts/mkinitcpio install` — the
  literal command pacman's own hook runs on a real kernel package
  install/upgrade (confirmed from that script's own source: its main loop
  reads trigger-target names from stdin, and a line reading exactly
  `mkinitcpio` with `install` as `$1` regenerates
  `/etc/mkinitcpio.d/<pkgbase>.preset` for every kernel from the package's
  own real template, `/usr/share/mkinitcpio/hook.preset`), not hand-written
  content.
- **`/etc/systemd/system/getty@tty1.service.d/autologin.conf`** — unowned,
  and **unconditionally** (unlike the two bugs above, not even gated by a
  kernel command-line condition) configures tty1's getty to
  `agetty --autologin root`, no password. The most severe finding of this
  audit: left in place, local console access to the installed target (e.g.
  Ctrl+Alt+F1, or a graphical-session crash) grants an unauthenticated root
  shell, directly contradicting this project's own locked "no root
  password, sudo-only" decision (`modules/users.conf`'s
  `setRootPassword: false`).
- **`/etc/systemd/system/etc-pacman.d-gnupg.mount`** — unowned; tmpfs-mounts
  `/etc/pacman.d/gnupg` so the live session's throwaway GPG trust store
  never persists to the read-only squashfs. On an installed target (a
  normal writable disk), this would silently wipe pacman-key's trust
  database on every reboot.
- **`/etc/ssh/sshd_config.d/10-archiso.conf`** — this project's own live-
  session file (`iso/profile/airootfs/`), enabling root+password SSH login
  as a developer-recon convenience (used throughout this project's own
  session) with no legitimate purpose on an installed desktop.
- **`/etc/motd`** — unowned; tells the reader to "install Arch Linux" and
  points at the live-only tools below — actively misleading once the
  system is already installed.
- **Dead live/PXE-only mirror machinery**: `/usr/local/bin/choose-mirror`
  plus its `.service` and enablement symlink — unowned, gated by
  `ConditionKernelCommandLine=mirror`, never true for a Calamares-installed
  target's own grub-generated kernel command line.
- **Dead accessibility-boot-flag-only live sound/speech helper**:
  `/usr/local/bin/livecd-sound` (+ `/usr/local/share/livecd-sound`) plus
  `livecd-talk.service`/`livecd-alsa-unmuter.service` and their enablement
  symlinks — unowned, gated by `ConditionKernelCommandLine=accessibility=on`.
  The real accessibility screen reader itself, `espeakup` (kept, see below),
  is independent of these and unaffected.
- **`/usr/local/bin/Installation_guide`** — unowned; a one-line live-only
  launcher (`exec xdg-open .../Installation_guide`) with no purpose once a
  system is already installed.
- **`/etc/nvme/{hostid,hostnqn}`** and **`/etc/brlapi.key`** — unowned,
  per-machine identity/secret material archiso's build baked into the
  squashfs once. Unlike SSH host keys (confirmed absent from this image —
  openssh generates those fresh on first real boot, the correct pattern),
  these would otherwise be IDENTICAL across every kuura install made from
  this one ISO build. Both are regenerated automatically by their own
  packages the next time they are needed if the file is absent.

Reviewed and deliberately left alone (not live-only, or already handled
elsewhere): `/var/lib/pacman/local/**` (pacman's own required state);
`/etc/machine-id`, `/var/lib/dbus/machine-id` (already handled by
Calamares' own `machineid` exec module); `/usr/share/mime/**`,
`/usr/share/icons/**/*.cache`, `/etc/ca-certificates/**`,
`/etc/ssl/certs/**`, `/etc/fonts/conf.d/*`, `/var/cache/{fontconfig,
ldconfig,swcatalog}/**`, `/usr/lib/modules/*/modules.*`,
`/usr/lib/udev/hwdb.bin` (all standard regenerable Arch-system caches,
present and unowned on every Arch install, not archiso-specific);
`/srv/repo/**` (the ISO's own staged local repository — this section's own
earlier text already explicitly defers the question of whether an
installed system keeps it to Vaihe 8; removing it here would be silently
deciding that question by accident, which is exactly what was to be
avoided); `/etc/systemd/resolved.conf.d/archiso.conf` (content is a
generically-fine mDNS preference despite its filename, not live-specific in
effect); `/etc/modprobe.d/broadcom-wl.conf` (a standard upstream-releng
driver preference, not kuura- or live-specific, equally valid installed);
`/etc/os-release` (factually accurate Arch-based identity plus
IMAGE_ID=kuura/IMAGE_VERSION metadata; no branding decision anywhere else
in this project renames the installed system away from "Arch Linux", so
this is not this task's call to make); `/etc/{hostname,locale.conf,
localtime,ld.so.cache}` (overwritten later in the same exec sequence by
`networkcfg`/`locale`/`hwclock`, already-locked modules); `/etc/{shadow-,
passwd-,group-,gshadow-,subuid-,subgid-}` (harmless `useradd` backup files,
superseded when Calamares' own later `users` exec module creates the real
target account); `/etc/.pwd.lock` (harmless stale lock marker).

Separately — not a bug, a real scope question the project owner decided
explicitly: `iso/profile/packages.x86_64` is releng's own full rescue-medium
package list (clonezilla, testdisk, partimage, partclone, memtest86+,
memtest86+-efi, gpart, ddrescue, fsarchiver, mkinitcpio-archiso,
mkinitcpio-nfs-utils, archinstall, dmraid, grml-zsh-config, and more — see
the list `iso/profile/packages.x86_64` itself, releng's portion above the
"kuura additions" comment) plus kuura's own three additions. Every one of
those releng packages ends up installed on every kuura system via the same
unpackfs copy, not just available on the live medium. **Locked decision
(2026-10-12, project owner chose the thorough option over a minimal
one-file fix): give the installed system a properly, deliberately scoped
package set**, not whatever releng's rescue-medium default happens to
include.

**Classification rule** for whoever audits the full package list: REMOVE a
package from the installed target if its real purpose (confirmed from its
actual Arch package description — `pacman -Si <pkg>` or the Arch wiki, never
guessed from the name alone) is rescue-media/live-boot/diagnostic-only: disk
cloning/imaging/partition-recovery tools, memory testers, PXE/NFS-network-boot
machinery, the archiso-specific initramfs tooling itself, and Arch's own
competing interactive installer (`archinstall` — redundant once Calamares has
already installed the system). KEEP a package if it is a general-purpose tool
plausibly useful on an ordinary installed desktop even though releng also
ships it for the rescue case — network/VPN connectivity tools, TPM utilities,
VM-guest-integration tools (relevant since kuura can itself be installed
inside a VM), accessibility tools (screen reader / braille display support).
Also decide deliberately (don't default silently either way) whether
`calamares`/`calamares-debug` themselves should be removed post-install, the
same logic as `archinstall` — document whichever choice is made and why.

**Locked mechanism**: two new modules added to the exec sequence (neither
used anywhere in this project before), both real Calamares modules — fetch
their real default `module.desc`/config schema from the same pinned v3.4.2
source every other module config in this project came from, don't invent
their config shape:

- `shellprocess` — runs a command against the target (`chroot: true`).
  Removes the confirmed untracked live-only files (and any more a real
  pacman-file-list diff turns up). Position: immediately after `unpackfs` in
  the exec sequence — as early as possible, before any later module might
  depend on the target's state being clean.
- `packages` — Calamares' real module for installing/removing packages on the
  target, `operations: - remove: [...]`. Position: also early in the exec
  sequence, after `shellprocess`.

Update `settings.conf.in`'s own header (now a third flagged change) and
`packages/kuura-installer-config/PKGBUILD`'s header count to match once
implemented.

**IMPLEMENTED 2026-10-12 — real schema confirmed from source, real
classification run, real build+install tested end to end.**

Real key names confirmed from the real v3.4.2 source (both modules'
upstream default config is a non-functional dummy/example — fetched and
read, not guessed; see `modules/shellprocess.conf`/`modules/packages.conf`'s
own headers for the full detail): `shellprocess`'s chroot toggle is
actually named **`dontChroot`** (boolean, default `false` — already means
"run in the target chroot", so this project's config states it explicitly
but needn't invert anything; the brief's own working name `chroot: true`
above was a placeholder, not the real key). `packages` needs an explicit
`backend: pacman` (default is `backend: dummy`, which only logs). Both
confirmed by fetching the real files from
`https://codeberg.org/Calamares/calamares` at tag `v3.4.2`, the same
source every other vendored module config in this package came from.

**Final package-removal list** (`packages.conf`'s `operations: - remove:`),
after a full `pacman -Si`-sourced classification pass over every releng
package in `iso/profile/packages.x86_64` plus a real reverse-dependency
check (`pacman -Qi <pkg>`'s "Required By") against the live rootfs, which
caught one real mistake before it shipped (see below): `archinstall`,
`calamares`, `kuura-installer-config`, `clonezilla`, `cloud-init`,
`ddrescue`, `dmraid`, `edk2-shell`, `fsarchiver`, `gpart`,
`grml-zsh-config`, `livecd-sounds`, `memtest86+`, `memtest86+-efi`,
`mkinitcpio-archiso`, `mkinitcpio-nfs-utils`, `partclone`, `partimage`,
`refind`, `syslinux`, `testdisk`.

Beyond the packages the classification rule's own examples already name
(`clonezilla`, `testdisk`, `partimage`, `partclone`, `memtest86+`/
`memtest86+-efi`, `fsarchiver`, `gpart`, `ddrescue`, `mkinitcpio-archiso`,
`mkinitcpio-nfs-utils`, `archinstall`, `dmraid`, `grml-zsh-config`), real
`pacman -Si` descriptions justified three more removals not named by the
brief but matching the same rule: `edk2-shell` ("EDK2 UEFI Shell" — a
bootable firmware-shell boot-menu entry, live-medium-only, never invoked by
this project's exclusively-`grub` `bootloader.conf`); `refind` ("An EFI
boot manager" — a competing bootloader this project's locked
`bootloader.conf` never configures or installs, redundant the same way
`archinstall` is); `syslinux` ("...boot loaders that boot from FAT,
ext2/3/4 and btrfs filesystems, from CDs and via PXE" — the live medium's
own BIOS bootloader per `profiledef.sh`'s `bios.syslinux` bootmode, with
PXE support in its own description; the installed target exclusively uses
GRUB). `cloud-init` ("Cloud instance initialization") was also added:
its only role on this ISO is letting the live medium double as a
cloud/VM-image boot target that self-configures from a cloud metadata
service on first boot — boot-time provisioning machinery with the same
"only makes sense before/during the live boot, not after" shape as the
PXE/NFS tools the rule already names, not anything an ordinary installed
desktop uses; left enabled it would run several no-op systemd services
every single boot searching for a nonexistent datasource.

**One real mistake caught by the reverse-dependency check, not shipped**:
`gpm` ("A mouse server for the console and xterm") looked, by name alone,
like another console/live-rescue-only tool and was initially classified
for removal. `pacman -Qi gpm`'s real `Required By` on the live rootfs says
otherwise: `brltty libnewt mc vim` — three kept general-purpose packages
(`mc`, `vim`) plus this project's own explicitly-kept accessibility tool
(`brltty`) all have a hard package dependency on it. Removing it would
have broken all three. `gpm` is **kept**; this is exactly the kind of
name-sounds-rescue-y-but-check-anyway case the classification rule itself
warns about ("Obvious candidates for removal based on name alone still
need their real description checked").

**`calamares`/`calamares-debug` decision**: removed, by the same logic as
`archinstall` — once Calamares has installed the system, neither the
installer nor its own configuration package has any further role on the
*target* (reinstalling means booting the live medium again, where a fresh
copy already lives). `kuura-installer-config` must be removed in the same
operation as `calamares`: it `depends=('calamares')` (confirmed from its
own installed `%DEPENDS%` record on the live rootfs), so removing
`calamares` alone fails with an unsatisfied-dependency error; listing both
in one `packages` module operation resolves them as a single pacman
transaction, with no cascade needed (this module's `remove` is already
non-cascading, so unrelated shared dependencies like `qt6-declarative` or
`python` are correctly left alone). `calamares-debug` needed no action:
confirmed (`pacman -Q` against the live rootfs) that only `calamares`
itself is actually installed on the live medium at all —
`packages.x86_64` never lists the `-debug` package, so there is nothing to
remove. Removing Calamares' own package from the target chroot while
Calamares itself keeps running is safe: Calamares executes from the live
squashfs (mounted read-only, independent of the target), never from the
target mount `pacman -R` here operates against via `arch-chroot` — the
same reasoning this project already relies on for `shellprocess` deleting
other live-session files out from under a still-running live session.

**Real build + real install result (REVISED 2026-10-13 — the first full
end-to-end run found a fourth, real bug; not the success this section
originally assumed).** The build was confirmed correct (package contents,
`shellprocess`/`packages` module config, all directly verified by
extracting the real built `.pkg.tar.zst` and reading its bytes, not trusted
from a build log). A real Calamares install was driven through Welcome →
Location → Keyboard → Partitions → Users → Summary → Install, past
`unpackfs` (target fully populated) and the first two `shellprocess`
deletions — then failed, for real, on the exec sequence's own
`echo mkinitcpio | /usr/share/libalpm/scripts/mkinitcpio install` line
(`modules/shellprocess.conf`, see its own header): Calamares' own "Installation
Failed" dialog showed `==> ERROR: Invalid option -k -- '/boot/vmlinuz-linux'
must be readable`. Confirmed by direct inspection (mounting the target
partition read-only): the target's `/boot/` was completely empty — and so,
confirmed separately, was the **live** system's own `/boot/` (`ls -la
/boot/` → just `.`/`..`). The real kernel and initramfs exist only at
`/run/archiso/bootmnt/arch/boot/x86_64/{vmlinuz-linux,initramfs-linux.img}`
— the ISO9660 media itself, not anywhere `unpackfs`'s squashfs source ever
contained them. This is a real, confirmed, well-known archiso build
behavior, not a kuura bug in `unpackfs.conf`: `mkarchiso`'s own build
process relocates the kernel+initramfs out of `airootfs` and into the ISO's
own `/arch/boot/x86_64/` directory before squashing it (the live medium's
bootloader — ISOLINUX/systemd-boot per `profiledef.sh`'s `bootmodes` — loads
them directly from the ISO9660 filesystem, never from inside the squashfs),
which is exactly why neither the live session's own `/boot` nor a
squashfs-sourced `unpackfs` target ever has them. Because this
`mkinitcpio install` line (unlike every sibling line in
`shellprocess.conf`) carries no `-` non-fatal prefix, its failure aborted
the whole exec sequence on the spot: the `packages` module (and everything
after it — `machineid`, `users`, `bootloader`, ...) never ran at all,
confirmed by the removal-list packages (`mkinitcpio-archiso`,
`memtest86+`, ...) still being present in the target's own
`/var/lib/pacman/local/`.

**Fix, locked 2026-10-13 (project owner's explicit choice over reinstalling
the `linux` package via pacman):** restore the two files from the live ISO
media (`/run/archiso/bootmnt/arch/boot/x86_64/`) before anything downstream
needs them — **not** via `shellprocess` (first implementation attempt,
caught and reverted before rebuilding: `shellprocess` runs chrooted into
the target, whose `/run` is a *fresh tmpfs* per the already-vendored,
unchanged `modules/mount.conf`'s `extraMounts` — only `/run/udev` is
bind-mounted from the host, so `/run/archiso/bootmnt` is simply not visible
from inside that chroot; a `cp` there would have failed silently). The real
fix is a **second `unpack:` entry in `unpackfs.conf`**, run immediately
after the existing squashfs entry (upstream's own real docs for this module
explicitly describe this ordering as supported: create directories with one
unsquash, then target those directories from a second entry), with
`sourcefs: file` (copies a directory's contents into `destination`, no
nested subdirectory — confirmed from the real v3.4.2 module source) pointing
at `/run/archiso/bootmnt/arch/boot/x86_64` with `destination: "/boot"`.
`unpackfs` runs **unchrooted**, directly in the live environment, so it has
the same real access to `/run/archiso/bootmnt` that its existing squashfs
entry already depends on — this is not a workaround, it is a bit-identical
restoration of the exact two files `mkarchiso`'s own build process moved out
of the squashfs for ISO-size reasons, put back where an installed system
(not a loop-mounted ISO) actually needs them. `shellprocess`'s own
`mkinitcpio install` line then finds a readable `/boot/vmlinuz-linux` and
correctly regenerates `initramfs-linux.img` against the target's own real
hooks (the already-locked `archiso.conf` deletion earlier in the same
script means `/etc/mkinitcpio.conf.d/` is clean by the time it runs). See
`modules/unpackfs.conf`'s own header (second flagged change) and
`modules/shellprocess.conf`'s own header (points at `unpackfs.conf` instead
of duplicating the explanation) for the exact implementation.

**Fifth bug, found+fixed 2026-10-13: the `packages` module never actually
ran in any real install, offline or not.** With the `/boot` bug above fixed,
a real install reached the Finish page for the first time in this project's
history — but direct inspection of the installed target (mounting its
partition read-only and reading `/var/lib/pacman/local/` directly) showed
every one of the 21 packages `modules/packages.conf`'s own `remove:` list
names were still present. Root cause, confirmed from two independent real
sources, not guessed: (1) Calamares' real `src/modules/packages/main.py`
(`run()`) checks `skip_if_no_internet` *before* it ever reads the
`operations` list — `if skip_this and not hasInternet: return None` — so a
`true` here (this file's own value, set on the mistaken assumption that it
only gated *install* operations) skips the module's entire body, including
a remove-only operation that itself needs no network at all; (2) two
separate real install runs' own Calamares `session.log` (captured for the
first time this session, copied onto the target's own filesystem before
quitting QEMU since the live session has no other channel to export it)
both show job 12/31 ("packages") consisting of exactly one line —
`WARNING: [PYTHON JOB]: "Package installation has been skipped: no
internet"` — and nothing else; no `pacman` invocation at all. This project's
own offline QEMU test harness (`-nic none`, deliberate — the goal is an
install flow with no network dependency) triggers this on every single
test run. Fixed by setting `skip_if_no_internet: false` (the real upstream
default) in `modules/packages.conf` — the original reasoning was correct,
it just needed to be expressed by *not* requesting the skip at all, rather
than by requesting it and assuming it was narrower than it really is.

A side-effect of chasing this bug is worth recording: the first real
install's target looked, on initial inspection, like a *partial* removal
(9 of 20 named packages gone, plus the sanity-kept `mc` unexpectedly
missing) — a meaningfully different and more alarming shape than "nothing
ran at all". That result came from this task's own throwaway
`verify_target.sh` recon script (not part of this repository's permanent
test suite), which was independently proven non-deterministic: run three
times in a row against the same unchanging read-only mount, with no writes
in between, it gave three different pass/fail counts each time. A stable
re-check (`ls /var/lib/pacman/local | sort` captured to a file once, then
grepped against that static snapshot, rather than re-`ls`ing per package in
a loop) gave the same, consistent 21/21-still-present result on **both**
real targets — confirming the simpler "skipped entirely" explanation is the
true and only one, and the "partial removal" shape was a measurement
artifact, not a second real bug. Left as an open question for whoever next
touches QEMU/NBD-backed verification in this project: the flakiness itself
was not root-caused (plausible culprits include rapid repeated small reads
racing against the NBD backend, or the script's own `ls | grep -q`
per-package loop), only worked around.

**Settled by a real Calamares run, 2026-10-13: it really does remove 79
packages, not 21.** With the skip bug fixed, a full rebuild (fresh
`kuura-installer-config` package, fresh signed repo, fresh ISO — confirmed
byte-level at every stage, not trusted from a green build log) and a fresh
real install were run end to end. Calamares' own `session.log`, job 12/31,
shows the real, unmodified invocation: `pacman -Rs --noconfirm archinstall
calamares kuura-installer-config clonezilla cloud-init ddrescue dmraid
edk2-shell fsarchiver gpart grml-zsh-config livecd-sounds memtest86+
memtest86+-efi mkinitcpio-archiso mkinitcpio-nfs-utils partclone partimage
refind syslinux testdisk` — completing in 8 seconds with no error, followed
by job 13/31. No "target not found" abort occurred (a real risk given
`remove`, unlike `try_remove`, aborts the whole transaction on any single
unsatisfiable target) — all 21 names were genuinely installed, confirmed
separately via `packages.x86_64`, a live `pacman -Q`, and the running
`pacstrap` command line itself.

The real, measured result, independently reproduced twice (once by the
agent that ran the install, once again from scratch by the orchestrator
using a *different* baseline source — the agent's own live tty2 capture vs.
a separately-extracted airootfs pacman database — both giving the same
numbers): **857 packages on the live baseline, 778 on the installed
target, a diff of exactly 79** (`comm -23` of two `ls
/var/lib/pacman/local | sort` snapshots — the only reliable way to check
this, see `verify_target.sh`'s own flakiness note above). All 21 named
packages confirmed absent; all 6 sanity-kept packages (`gpm mc vim brltty
kuura-desktop kuura-shell`) confirmed present; the two earlier fixes
(`/boot` restoration, live-only-file cleanup) re-confirmed still holding on
this same fresh target. The 58 cascaded packages beyond the named 21
include `ntfs-3g`, `python-cryptography`, `boost-libs`, `sshfs`, `cracklib`,
`libpwquality`, `kpmcore`, `drbl`, `ecryptfs-utils`, several compression
tools (`pbzip2`, `pigz`, `pixz`, `lbzip2`, `lrzip`, `lzop`), and others not
yet individually reviewed by this project's own per-package audit.

**Decided, 2026-10-13 (project owner's explicit choice):** the 79-package
cascade is accepted as-is. Every package `-Rs` additionally removes is a
real, now-unneeded dependency of something already in the deliberately-
removed 21 (Calamares/archinstall's own libraries, rescue-tool
dependencies like `boost-libs`/`kpmcore`/`cracklib`, compression tools
`clonezilla`/`partimage`/`partclone` pulled in — not anything this product
independently ships or depends on elsewhere), and scoping removal to
exactly the named 21 would need a materially bigger implementation change
(a custom non-cascading removal mechanism) for a risk that direct
measurement shows is not real: the installed target still has `kuura-
desktop`/`kuura-shell` and every sanity-kept package (`gpm mc vim brltty`)
intact, confirmed twice independently. No further action needed here — the
removal list and its real, measured effect are both locked.

## Installed-system verification

Decided, 2026-10-13 (project owner's explicit choice, `AskUserQuestion`):
the DoD line below ("asennettu järjestelmä läpäisee vaiheiden 3–6
diffit") is satisfied by reusing the *existing* `harness/shots/runner.py`
`Runner` + `harness/states.toml` + `harness/shots/compare.py` machinery
against a real Calamares-installed target, unchanged — not by a second,
parallel QMP-only reimplementation of the same step/settle logic. That
machinery drives the guest over `harness/shots/guest.py`'s `GuestAgent`
(command execution, CPU-busy probing for settle detection), so the
installed target needs a running guest agent to be reachable the same way
the desktop harness's own pre-built image already is.

`qemu-guest-agent` is already part of the live medium
(`iso/profile/packages.x86_64`, inherited from archiso's own `releng`
default — this project did not add it), but its systemd service was not
enabled anywhere (no live-session `.wants/` symlink, and
`packages/kuura-installer-config/calamares-defaults/modules/
services-systemd.conf`'s own `units:` list was empty). **Decided:**
`services-systemd.conf` now enables `qemu-guest-agent.service` on the
installed target (one `units:` entry, `mandatory: true`). The service is a
no-op on real hardware (it waits on a QEMU-specific virtio-serial channel
that does not exist there) and is a narrower, more generic virtualisation
convenience than `cloud-init` (removed earlier in this same document as
genuinely VM/cloud-only dead weight on a desktop install) — it is also
useful to any end user who happens to run kuura itself inside a VM
(VirtualBox/VMware/Hyper-V clipboard/resize integration), not purely a
testing artifact.

**New permanent harness module, `harness/install/`** (peer to
`harness/shots/` and `harness/vm/`), interface locked by the orchestrator
2026-10-13 before delegating implementation (`boot.py`, `wizard.py`,
`run.py` — full docstrings, `NotImplementedError` bodies):

- `boot.py`'s `InstallVm`: real BIOS/UEFI QEMU boot (via `-cdrom`/`-drive`,
  no `-kernel`/`-initrd`, no `-snapshot` — writes must persist across the
  install), distinct from `harness/shots/vm.py`'s `Vm` for that reason.
  Phase 1 boots the ISO with a blank disk and drives the install over QMP
  only (no guest agent yet). `reboot_to_disk_only()` moves the SAME disk
  into phase 2 (no ISO attached, proving the installed bootloader works)
  and optionally attaches the now-running guest agent.
- `wizard.py`'s `run_install()`: promotes this phase's own proven, ad-hoc
  `isorecon/install_test.py` UI-automation sequence (Welcome → Location →
  Keyboard → Partitions → Users → Summary → Install → Finish) into a
  permanent, parametrized driver, reusing `harness/shots/qmp.py` and
  `harness/shots/keys.py` unchanged. `WizardCredentials.username`
  defaulting to `"desktop"` was meant to deliberately match
  `harness.shots.guest.GuestUser()`'s own built-in default uid (1000) —
  disproven by real evidence below; see the `liveuser` finding for the fix
  that restores this assumption.
- `run.py`: CLI entry point (`python3 -m harness.install.run`), exit codes
  0/1/2 mirroring `harness/shots/capture.py`'s own convention. New Make
  target `installed-verify` (depends on `iso`; deliberately not named
  `verify-install`, which already means something unrelated — see that
  target's own recipe). New CI job `install-harness`
  (`.github/workflows/ci.yml`), copied from the existing
  `screenshot-harness` job's "skip without a usable `/dev/kvm`" pattern.

**First real end-to-end run, 2026-10-13/14 — wizard navigation confirmed
working, two new findings beyond the original scope.** The delegated
implementation hit a real bug first: `_highlighted_row_y`'s sidebar-colour
scan false-matched Calamares' own product-icon logo (measured
`(59,173,194)` against a `(79,179,200)` target, inside the comparison
tolerance), making every page look like "still on Welcome" forever. Fixed
with `_SIDEBAR_SCAN_Y_START = 300` (scan starts below the logo); confirmed
by a real BIOS install run reaching Finish with a clean, non-repeating
page sequence — not by unit tests alone.

That same real run surfaced two things past Finish that the original
interface design had not accounted for, both confirmed independently (the
orchestrator mounted the resulting disk directly, not just trusted the
agent's report):

- **No autologin means the harness never sees a desktop.**
  `modules/users.conf`'s `doAutologin: false` is a deliberate security
  default (confirmed in that file) — so `Runner.wait_for_desktop()`
  timed out waiting for `plasmashell`, which can never start with nobody
  logged in. **Decided (project owner, `AskUserQuestion`, recommended
  option): the harness drives a real SDDM login** (the same QMP
  keyboard/mouse primitives `wizard.py` already has, typing the same
  password `WizardCredentials` gave Calamares), rather than special-casing
  autologin into a test-only build — the DoD's own wording ("asennettu
  järjestelmä läpäisee...") means the system as actually shipped, not a
  test-convenience variant of it.
- **The live session's own `liveuser` account (uid 1000) survives every
  install**, confirmed by mounting a real installed disk directly:
  `/etc/passwd`/`shadow`/`group` entries and a ~150K home directory, all
  present. `/etc/shadow` shows `liveuser:!:...` (locked, no valid password
  hash, not in `wheel`) — not a privilege-escalation path — but a real UX
  defect (visible in SDDM's own user list) that also pushes the real
  installed account to uid 1001, breaking the `GuestUser()` uid-1000
  assumption two paragraphs up. Same category of gap as every other
  finding in `shellprocess.conf` (unpackfs copies it unconditionally, no
  package owns it, nothing before this project's own audit ever removed
  it). **Decided (project owner, `AskUserQuestion`, recommended option):
  `shellprocess.conf` now also runs `-userdel -r liveuser`**, restoring
  the real account to uid 1000.

**Resolution mismatch, found and fixed 2026-10-14.** The first full diff-pass
run (above) reached `Runner`/`compare` for real but failed 22/22, mostly with
`image size mismatch: 1920x1080 vs 2560x1440`: `harness/install/boot.py`'s
`InstallVm` boots at 1920x1080 (the module's own original docstring said
"unrelated images/use cases, no reason to match" `harness/shots/vm.py`),
while every file under `harness/goldens/` was captured by
`harness/shots/vm.py`'s `Vm` at its own default, 2560x1440 — the two had
simply never been made to agree. Presented to the project owner as an
explicit choice (`AskUserQuestion`, this project's own standing "escalate
rather than silently pick" rule): (A) make only phase 2 (the reboot + SDDM
login + diff-pass — already a separate QEMU process from phase 1's Calamares
install, confirmed from `reboot_to_disk_only`'s own implementation) boot at
2560x1440 to match the goldens, leaving phase 1's already-calibrated
Calamares wizard automation at 1920x1080 untouched; (B) recalibrate the
entire harness (both phases, every Calamares coordinate) to 2560x1440; (C)
capture a brand-new, separate set of 22 goldens at 1920x1080 just for
install-verify. **The project owner chose (A).** Implemented: `boot.py`'s
`reboot_to_disk_only()` gained an optional `resolution` keyword (default
`None`, preserving old behaviour exactly); `run.py`'s call site passes
`resolution=(2560, 1440)` explicitly; `wizard.py`'s three SDDM greeter
constants (`_SDDM_USER_TILE`, `_SDDM_PASSWORD_FIELD`, `_SDDM_LOGIN_BUTTON`)
were re-measured from scratch at 2560x1440 (not scaled from the 1920x1080
values — confirmed live that the Breeze SDDM theme renders every widget at a
**fixed physical pixel size** regardless of screen resolution and simply
re-centres the login box on the bigger screen, so naive linear scaling would
have been wrong) by booting the already-installed disk directly at the new
resolution and pixel-scanning a real screendump, the same method every other
coordinate in that file already uses. The old 1920x1080 SDDM constants were
kept, renamed `_..._1920X1080`, as the historical record of that measurement
rather than deleted. See `wizard.py`'s own comments for the exact measured
bounding boxes.

A full rebuilt-from-fresh-install re-run (`harness.install.run --firmware
bios`, 1250s total) confirmed the resolution fix itself worked exactly as
intended: **zero** `image size mismatch` or `pointer coordinate ... outside
the screen` errors across all 22 states (previously 16 and 2 respectively).
Phase 1 (fresh Calamares install from the existing ISO) and phase 2 (reboot
to disk only, now at 2560x1440, SDDM login with the newly-measured
coordinates) both completed cleanly — install finished in 352.5s, SDDM login
in 10.9s. **However the diff-pass result is 0/22 passing, for reasons that
are real and unrelated to resolution, not an artifact of the fix.** Each is
reported honestly below rather than folded into "fixed":

1. **8/22 (`notification`, `browser-window`, `app-menu-gtk`,
   `gtk4-widget-factory`, each mode) still "the screen did not settle" —
   root-caused, not just suspected, and NOT the same bug as the earlier
   resolution-mismatch symptom.** Confirmed by directly mounting the fresh
   install disk read-only (`qemu-nbd` + `mount -o ro,noload`, this project's
   own standard technique) and checking for the binaries these states'
   `states.toml` steps `run`: `notify-send`, `mousepad`, `gtk4-widget-factory`
   and `harness-browser` are **all absent** from the installed target, and no
   matching package (`libnotify`, `mousepad`, `gtk4-demos`) is in its pacman
   local database at all. Cross-checked against `harness/vm/Containerfile`
   (the pre-baked image goldens and vaiheet 3–6 are captured from): it
   explicitly installs `libnotify firefox dolphin systemsettings mousepad
   appmenu-gtk-module gtk4-demos chromium` as **test-only** packages for that
   image, separate from the real product's package list
   (`iso/profile/packages.x86_64`, `kuura-desktop`, `kuura-shell`). These
   four states were never going to pass against a real Calamares install —
   the commands silently do nothing (confirmed visually: the captured
   `notification` frame is a plain, unchanged desktop, no popup ever
   appeared), so `settle()` correctly times out waiting for a change that
   can never come. This is a real gap in how `install-verify` reuses
   `states.toml` (built for the harness's own fully-loaded test image)
   against a genuinely bare install, not a bug in the resolution fix or in
   `settle()` itself. **Not yet decided**, and deliberately left undecided
   here rather than silently picked: ship the relevant test tools as part of
   the real product so these states are meaningful post-install too, exclude
   these 4 states from `install-verify`'s own selection (`--states`) as
   structurally inapplicable to a bare install, or something else — a product
   decision, not an implementation one.
2. **14/22 (`desktop-empty`, `menubar-open`, `shelf-hover`, `overview`,
   `search-open`, `files-window`, `settings-window`, each mode) status
   `fail` — genuine pixel differences against the goldens, confirmed by
   visual inspection of the actual diff images, with at least two distinct,
   real contributing causes identified (not exhaustively root-caused further
   than this):
   - **Window/overview sizing differs substantially** between the freshly
     installed target and the goldens — confirmed by side-by-side comparison
     of `settings-window` (System Settings opens dramatically smaller on the
     fresh install, cutting off content the golden shows in full) and
     `overview` (the desktop thumbnail is smaller and lacks the golden's
     teal selection border). This is the dominant contributor to the large
     diff ratios (up to 81% of pixels) on every state that opens a window or
     the overview effect. Most likely cause (plausible, not yet confirmed by
     inspecting both images' saved KDE config directly): the pre-baked
     `harness/vm/` image carries persisted per-app window geometry from
     however it was built/baked, while a genuinely fresh Calamares-installed
     user profile has no such saved state and falls back to each app's own
     hard-coded first-run default size — flagged here as the leading
     hypothesis, not a confirmed root cause.
   - **`InstallVm`'s `build_command` (`boot.py`) never sets `-rtc
     base=...,clock=vm`**, unlike `harness/shots/vm.py`'s `Vm` (which pins
     the guest clock to `rtc_base` from `states.toml`, `2026-09-25T12:00:00`
     by default). Confirmed directly from both modules' source: install-verify
     captures the real host wall-clock time instead, so the panel clock glyph
     will never match a golden's pinned time on any run — a real, independent
     determinism gap in the install harness, confirmed but likely a
     second-order contributor next to the window-sizing issue above (the
     panel clock itself sits inside `states.toml`'s own `mask = [[2420, 0,
     2560, 55]]`, which is correctly positioned over it — the mask is not the
     bug).
   - Separately confirmed via the diff images: in the simplest state with no
     window open (`desktop-empty`), the differing pixels are cleanly isolated
     to the top panel strip and the bottom dock (the wallpaper itself matches
     pixel-for-pixel) — plausibly explained by `InstallVm` using a plain
     `-device VGA,...` display adapter (required — see `boot.py`'s own
     docstring on why `virtio-vga` segfaults QEMU on a cold BIOS/`-cdrom`
     boot on this project's hosts) where `harness/shots/vm.py` uses
     `virtio-vga`, which could plausibly render the project's own
     translucent/frosted panel and dock material differently. This is a
     plausible, source-confirmed-as-different-device hypothesis, not a
     pixel-isolated proof of causation.

None of the four options originally presented to the project owner (A/B/C
above, or doing nothing) are affected by this — the resolution fix is
confirmed working on its own terms. What remains (the two groups of
failures above) is new scope the project owner has not yet been asked to
decide on, consistent with this project's own standing rule not to let an
implementation pass quietly narrow or reinterpret a DoD line. `harness/goldens/`
was **not** touched, read, or re-approved by any part of this work — any
`goldens-accept` decision remains the project owner's alone.

**The two groups of failures above were decided, 2026-10-15 (project owner's
explicit choice, `AskUserQuestion`, two rounds):**

1. The 8 "did not settle" states (`notification`, `app-menu-gtk`,
   `gtk4-widget-factory`, `browser-window`, each mode) are fixed by shipping
   the real tools those states run, rather than excluding the states from
   `install-verify`'s own selection. `packages/kuura-desktop/PKGBUILD`'s
   `depends` gained `libnotify` (`notify-send`), `mousepad` and `gtk4-demos`
   (`gtk4-widget-factory`) directly, plus a new, dedicated package,
   `packages/kuura-harness-support/` (`${DISTRO_NAME}-harness-support`),
   which ships the `browser-window` state's own `harness-browser` wrapper
   script, its static test page and its throwaway browser-profile template —
   byte-identical copies of `harness/vm/guest/overlay/`'s own files (see that
   new PKGBUILD's own header comment for why these are maintained as their
   own copies rather than reached across the repo at build time, and for the
   full reasoning behind every choice below). Investigated and flagged
   before implementing, not silently picked: `gtk4-demos` pulls in ~28.5 MiB
   of GStreamer/Vulkan/colour-management dependencies purely for a demo app
   (confirmed via `pacman -Si`), and `harness-browser` is not a real browser
   at all (a wrapper that resets to a fresh profile and opens a fixed local
   page every launch) — the project owner chose to ship both as-is anyway
   after seeing these costs stated plainly.
2. `harness-browser` needs a system-wide Firefox `policies.json`
   (`/usr/lib/firefox/distribution/policies.json`) to be fully deterministic,
   but `packages/kuura-firefox/PKGBUILD` already owns that exact path with a
   deliberately lighter policy (does not disable telemetry, Pocket, Firefox
   Accounts or the password manager for a real end user). **Decided: leave
   `kuura-firefox`'s own `policies.json` untouched.**
   `packages/kuura-harness-support/`'s own `user.js` (profile-scoped, no
   conflict — applies only to `harness-browser`'s own throwaway profile, never
   a real user's actual Firefox profile) still ships, so first-run pages,
   restore prompts, animations and forced software rendering are still
   guaranteed deterministic on a real install; only the subset of
   determinism that depended on the system-wide policy (telemetry/Pocket/
   password-manager/accounts suppression) does not carry over to a real
   install the way it does on the test image. Accepted as the cost of not
   changing every real end user's actual Firefox privacy/feature defaults
   just to serve this harness.

Verified before this was considered done: `pytest -q` (938 passed, 7
skipped), `ruff check .` (clean), `python tools/check_forbidden_terms.py`
(clean, exit 0), `bash -n` on the new PKGBUILD and script (syntax only — a
real `make repo`/ISO rebuild and a full `harness.install.run` pass against
the rebuilt ISO is the next step, to confirm `pacman` actually resolves and
installs the four new packages on a real target and that the four
previously-"did not settle" states now execute their `run` step
successfully; this does **not** by itself fix the separate, still-undecided
14-state pixel-diff findings documented above).

**A real end-to-end run against the fixed packages, 2026-10-15/16, then
surfaced a third, real, unrelated blocker and, once past it, root-caused the
14/22+8/22 pixel-diff split above with certainty:**

1. **New blocker, found and root-caused by the orchestrator directly (not a
   subagent guess):** the package-fix verification run's SDDM login timed
   out - a regression, since the identical code had logged in successfully
   the run before. Booting the installed disk standalone and screendumping
   repeatedly through the wait window showed the SDDM greeter rendering TWO
   user rows ("Kuura Test" and, below it, "liveuser") instead of one - the
   extra row pushes the password field below the fixed pixel coordinate
   `_sddm_password_field_visible()` checks. Confirmed directly on the disk
   (`qemu-nbd` + `mount -o ro,noload`): `liveuser` was back in `/etc/passwd`
   and `desktop` was pushed to uid 1001 - the exact same bug the
   `userdel -r liveuser` fix (above, "Live-only cleanup") already fixed once.
   Confirmed via `tar -xOf`/`mount -o loop,ro` on both the built
   `kuura-installer-config` package and the built ISO's own
   `airootfs.sfs`: the `userdel -r liveuser` line was missing from BOTH,
   despite being present in the real source file - **Podman's own
   COPY-layer cache had silently served a pre-fix version of
   `kuura-installer-config` despite `make repo` exiting 0**, the third
   confirmed occurrence of this project's own documented cache-staleness
   bug class (see memory `feedback_podman_copy_cache_staleness.md`), this
   time hitting a package that was not touched by the current change (the
   two brand-new packages added for the tool fix above had no stale layer
   to collide with, which is why they were unaffected and why this was not
   caught sooner). Fixed by rebuilding with Podman's cache disabled and
   independently re-confirming the rebuilt package's and the rebuilt ISO's
   own `shellprocess.conf` content directly (not trusted from any exit
   code) before re-running install-verify. SDDM login then succeeded
   (12.1s) and the run reached the Runner diff-pass for the first time.
2. **All 22 states then failed the pixel-diff, by large, whole-frame-sized
   margins** (5.5% to 81.5% of pixels differing, bounding boxes spanning
   nearly the full 2560x1440 frame on every state) - not the narrow,
   anti-aliasing-only differences a real visual regression against a
   correctly-configured install would show. Comparing this run's 14
   previously-measured states against the immediately prior (SDDM-blocked)
   run's own numbers found them **numerically identical to several decimal
   places** (e.g. `overview`: 0.7486537000868055 both times) - strong
   evidence the harness is genuinely deterministic and that this is one
   consistent, structural cause, not fresh per-run noise, and that the
   newly-reachable 8 states are hitting the exact same underlying cause as
   the already-known 14, not a new, different problem.
3. **Root-caused with certainty** (orchestrator's own direct investigation:
   diffed `harness/vm/guest/skel/` - the screenshot harness's own pre-baked
   test image's per-user config, the one the goldens were captured against -
   file by file against `packages/kuura-shell/skel/`, the real product's
   own `/etc/skel`):
   - `harness/vm/guest/skel/.config/kwinrulesrc` forces the file manager,
     System Settings, browser and GTK text editor windows to a fixed
     1000x600 geometry - present only on the test image, confirmed absent
     from the real product's skel. A real install's apps open at their own
     natural default size instead, explaining the largest ratios
     (`files-window`/`settings-window`/`gtk4-widget-factory` ~74-75%,
     `browser-window` ~57%, `app-menu-gtk` ~53%).
   - `harness/vm/guest/skel/.config/plasma-workspace/env/10-vm-rendering.sh`
     forces `LIBGL_ALWAYS_SOFTWARE=1` (the software Mesa rasteriser) for the
     whole Plasma session - also test-image only. Orchestrator's own
     screenshot comparison on the simplest state (`desktop-empty`, no window
     open) found the differing pixels cleanly isolated to the top panel and
     bottom dock, which render fully OPAQUE on the real install instead of
     this project's own translucent "frost" material (correct on the
     golden) - consistent with KWin's blur/translucency effect depending on
     this explicit software-GL request, not available by default on
     `-device VGA` (required here, see `boot.py`'s own docstring) without it.
   - `harness/vm/guest/skel/.config/plasma-workspace/env/20-gtk-appmenu.sh`
     (`GTK_MODULES=appmenu-gtk-module`) explained the remainder of
     `app-menu-gtk`'s own difference (Mousepad's menu never reaching the
     panel's Global Menu widget) - but investigating it surfaced that the
     `appmenu-gtk-module` package itself is ALSO missing from the real
     product entirely (not merely the env var), a find with its own decision
     attached, below.

**Decided, 2026-10-16 (project owner's explicit choice, `AskUserQuestion`,
two rounds):**

1. **`kwinrulesrc` and `10-vm-rendering.sh` are injected directly onto the
   installed disk by the install-verify harness itself, never shipped in any
   package.** Both files are explicitly documented, in their own source,
   as test-image-only, predating this harness - promoting either to a real
   product file would be a real regression for real users (forcing every
   Dolphin window into a fixed 1000x600 box; forcing software rendering on
   hardware that may have a perfectly good GPU). `harness/install/wizard.py`'s
   new `inject_test_only_session_config()` reads both files directly from
   `harness/vm/guest/skel/` (this repository's own single source of truth
   for them - no duplicate copies to drift) and writes them onto the real
   target via `GuestAgent.write_file()` (already handles correct ownership),
   called from `run.py` after the guest agent connects but BEFORE
   `log_into_sddm()` - required timing, since Plasma's `env/` scripts are
   only sourced once, at session start, so writing them after login would be
   one boot too late. Reuses the exact existing goldens; no new golden
   approval round needed.
2. **`appmenu-gtk-module` (the package) and `GTK_MODULES=appmenu-gtk-module`
   (the env export) are promoted to real, permanently-shipped product files**
   instead of also being injected - project owner's choice: working global
   menu for classic GTK3 `GtkMenuBar` apps is a real, desired feature of this
   project's own macOS-inspired desktop (the whole point of the panel's
   Global Menu widget), not a test-only convenience that merely happened to
   live on the test image, unlike the other two. `packages/kuura-desktop/
   PKGBUILD` gained the `appmenu-gtk-module` dependency;
   `packages/kuura-shell/skel/.config/plasma-workspace/env/20-gtk-appmenu.sh`
   (a plain static file, no `@NAME@` templating needed) ships the env export
   to every real new account via `kuura-shell`'s own `package()`. Because
   this one is now a real product file, `inject_test_only_session_config()`
   deliberately does NOT inject it too (would be redundant, not wrong).

Verified before this was considered done: `pytest -q` (938 passed, 7
skipped, no regression), `ruff check .` (clean),
`python tools/check_forbidden_terms.py` (clean, exit 0). A real
`make repo`/ISO rebuild and a full `harness.install.run` pass against the
rebuilt ISO, to see the actual effect on all 22 states' pixel-diff ratios,
is the next step - not yet run as of this paragraph.

### 2026-10-16, continued: a real rebuild found a NEW blocker past this point

A full `make repo` + ISO rebuild + `harness.install.run` against it (run by a
delegated agent, independently re-verified by the orchestrator at each step
per this project's standing "trust but verify" discipline) confirmed all
three fixes above are genuinely present and took effect: `rtc` fix present
in `boot.py`; `inject_test_only_session_config()` ran and wrote both files
with correct, byte-identical content and correct ownership; the built
`kuura-desktop`/`kuura-shell` packages really contain the `appmenu-gtk-module`
dependency and the shipped env file; the real installed disk really has
`appmenu-gtk-module` installed and the skel file propagated to the new
account; `liveuser` still absent, `desktop` still uid 1000. Two unrelated
infrastructure bugs were found and fixed along the way (both now in
`feedback_wsl_background_process_dies_with_invocation.md` and the expanded
`feedback_podman_copy_cache_staleness.md` in project memory): a WSL2
background-process-lifetime gotcha, and a FOURTH confirmed location of this
project's cache-staleness bug class (the native `pacman` package cache on
the `kuura-arch-build` host, keyed by filename/version like the other three,
not content).

**But the install-verify run itself then failed with a genuinely new
problem, past the point anything had ever reached before:** `0/22` states
captured - `runner.wait_for_desktop()` raised "the desktop did not settle
after boot" even though SDDM login itself succeeded (12.0s) and the
test-only injection ran correctly. Root-caused via direct, read-only
diagnosis (reboot the same disk standalone 3x, reusing this project's own
unmodified `InstallVm`/`inject_test_only_session_config`/`log_into_sddm`, no
code changed): `plasmashell` never starts at all; `kwin_wayland` starts,
crashes (`eglInitialize failed` / `EGL_NOT_INITIALIZED` /
`"Opening render device for /dev/dri/card0 failed"`, a real coredump every
time) and is auto-restarted 5+ times in under 7 seconds, then stops being
restarted and never comes back. The journal also shows a separate, real
systemd transaction conflict mid-startup ("destructive transaction" errors
on `plasma-workspace-wayland.target`/`plasma-kwin_wayland.service`).

Checked, and found identically absent regardless of source: `systemctl
--user show-environment` 5-8s after a successful login contains NONE of
`LIBGL_ALWAYS_SOFTWARE`/`MESA_LOADER_DRIVER_OVERRIDE` (this run's own
injected vars) NOR `GTK_THEME`/`GTK_MODULES` (the REAL product's own
`15-gtk-theme.sh`/`20-gtk-appmenu.sh`, shipped via `/etc/skel` since before
today, unrelated to anything injected). Two explanations could not be fully
distinguished from read-only evidence alone: (a) the
`~/.config/plasma-workspace/env/*.sh` sourcing-into-systemd-environment
mechanism is broken in general on this build (would affect every real
user's global menu and GTK theming, not just this harness), or (b) the
missing vars are downstream collateral of the same session-startup sequence
already being wrecked by kwin's own crash-loop. One side investigation
(whether these `.sh` files need the executable bit - `harness/vm/
build_rootfs.sh` had, oddly, always `chmod 0755`'d them specifically, unlike
every other skel file) was checked against public KDE/Gentoo documentation
and forum reports and found NOT to be the cause: these files are sourced,
not executed, and the executable bit is not required for that - ruled out,
not left open.

**Decided, 2026-10-16 (project owner's explicit choice, `AskUserQuestion`,
among three options including "pin mkarchiso's build for reproducibility
first" and "stop for the day"): move all three files' environment-variable
delivery off `~/.config/plasma-workspace/env/*.sh` entirely, onto systemd's
own `~/.config/environment.d/*.conf` mechanism (`environment.d(5)`).**
`environment.d` is read directly by the `systemd --user` manager before ANY
user unit (including `plasma-kwin_wayland.service`) starts, independent of
Plasma's own ad-hoc startup script and whatever timing or sequencing issue
(a) or (b) above actually was - this fixes the problem regardless of which
hypothesis is true, and if (a), also restores the real product's own
global-menu and GTK-theming features for real users, not only this harness.

Implemented: `packages/kuura-shell/skel/.config/plasma-workspace/env/
15-gtk-theme.sh.in` and `20-gtk-appmenu.sh` moved to
`.config/environment.d/15-gtk-theme.conf.in` and `20-gtk-appmenu.conf`
(plain `KEY=VALUE`, no `export`, per `environment.d(5)` syntax);
`packages/kuura-shell/PKGBUILD`'s install block updated to match.
`harness/vm/guest/skel/.config/plasma-workspace/env/10-vm-rendering.sh` and
`20-gtk-appmenu.sh` (the pre-baked screenshot-harness image's own copies)
moved the same way to `.config/environment.d/10-vm-rendering.conf` and
`20-gtk-appmenu.conf`; `harness/vm/build_rootfs.sh`'s now-unnecessary
`chmod 0755` on the old `env/*.sh` glob removed (`environment.d` files are
parsed as data, never sourced or executed). `harness/install/wizard.py`'s
`_TEST_ONLY_SESSION_FILES` and `inject_test_only_session_config()`'s
docstring updated to the new destination path and this incident.

Verified: `pytest -q` (938 passed, 7 skipped, no regression), `ruff check .`
(clean), `python tools/check_forbidden_terms.py` (clean, exit 0). A real
rebuild + `harness.install.run` pass to confirm this actually fixes the
`kwin_wayland` crash-loop (or at least restores the environment variables,
which may or may not be sufficient on its own if the crash's real cause
turns out to be something else, e.g. the separately-flagged, unconfirmed
package-version-drift concern below) is the next step - not yet run as of
this paragraph.

**Separate, standing concern raised alongside this finding, not yet acted
on:** `mkarchiso` in the `kuura-arch-build` environment runs bare-metal on
the host, against that host's own system `pacman.conf`/mirror, NOT inside
the archive-pinned build image this document otherwise describes for
reproducibility. Today's rebuild was a genuinely fresh, from-scratch package
resolution (869 packages, forced by clearing caches to fix the two
infrastructure bugs above), so if that host's mirror is a live/rolling one
rather than the pinned archive snapshot, package versions (confirmed via
`pacman -Q` on the installed disk: `mesa 1:26.2.3-1`, `kwin 6.7.5-1`, kernel
`7.2.6.arch2-1`) could differ from whatever combination last booted without
crashing - plausible but NOT confirmed as the actual cause of the
`kwin_wayland` crash (no prior run's exact package versions were available
to diff against). Flagged for the project owner as a real, independent gap
between this document's reproducibility claim and this one environment's
actual practice, regardless of whether it turns out to be related to
today's crash.

### 2026-10-16, continued again: the environment.d fix confirmed, but exposed a worse crash

A rebuild with the `environment.d` fix above confirmed it works exactly as
designed: `systemctl --user show-environment` on the real failing disk now
genuinely shows all four variables (`LIBGL_ALWAYS_SOFTWARE`,
`MESA_LOADER_DRIVER_OVERRIDE`, `GTK_THEME`, `GTK_MODULES`) - resolving
hypothesis (a) vs (b) from the previous entry in favour of (a): this
confirms the old `~/.config/plasma-workspace/env/*.sh` mechanism really was
failing in general on this build, not just as kwin-crash collateral.

But the install-verify run that followed failed WORSE than before:
`"the desktop shell did not start"`, `0/0` states, past even the
`120s wait_for_desktop` timeout - previously (with the vars not landing at
all) `plasmashell` eventually came up despite the crash-loop; now it never
does. Root-caused via the same read-only diagnostic technique (reboot the
same disk standalone, no code changes, pull `journalctl`/`systemctl --user
show-environment` via the guest agent): `kwin_wayland` starts and segfaults
on a tight, continuous respawn loop for the full observation window, always
at the identical spot (`eglInitialize failed "EGL_NOT_INITIALIZED"` ->
`Opening render device for /dev/dri/card0 failed` ->
`KWin::RenderDevice::eglDisplay()` -> SIGSEGV), with `plasmashell`/
`startplasma` never once appearing in `pgrep` during the whole window.

**Orchestrator's own analysis (research, not guessed) before bringing this
back to the project owner:** the very first successful install-verify run,
long before this file (or any rendering override) existed, already reached
a working desktop via `kwin_wayland`'s own default hardware/software
fallback on this exact `-device VGA`/bochs-drm QEMU configuration - the
*only* defect that run had was cosmetic (opaque panel/dock instead of this
project's translucent "frost" material), never a crash. That is direct
evidence kwin's own default fallback already handles "no GPU here"
correctly on this VM without any override at all. The thing that is new
today, and that was never present during that first working run, is
`MESA_LOADER_DRIVER_OVERRIDE=kms_swrast` forcing Mesa's DRI loader to one
specific driver - plausibly bypassing whatever auto-detection path
`kwin_wayland`'s own default behaviour relies on, in a way this kwin/Mesa
version combination (kwin 6.7.5, mesa 1:26.2.3-1) cannot recover from
(it segfaults instead of falling back, which may itself be a KWin
regression/bug independent of this project, but is not something this
project can fix upstream).

**Decided, 2026-10-16 (project owner's explicit choice, `AskUserQuestion`,
among four options including "add permanent journal/kwin-log diagnostics to
the harness first" and "stop for the day"): drop
`MESA_LOADER_DRIVER_OVERRIDE=kms_swrast` from
`harness/vm/guest/skel/.config/environment.d/10-vm-rendering.conf`, keep
only `LIBGL_ALWAYS_SOFTWARE=1`** - the cheaper, better-evidenced experiment,
on the reasoning above. Implemented (small, mechanical, done directly by the
orchestrator rather than delegated - see that file's own updated header
comment for the full reasoning).

**CONFIRMED FIXED**, independently re-verified by the orchestrator (not
just the delegated agent's claim): a fresh `harness.install.run` reached
all 22 states with real captured frames and `error: None` - no crash, no
timeout, `wait_for_desktop()` succeeded. The orchestrator independently
viewed the actual `light/desktop-empty.png` output, its golden, and the
diff image directly: the panel and dock genuinely render as soft,
translucent "frost" material in both - the original defect this override
existed to fix is also confirmed gone, not just "no crash."

**Remaining 0/22 pixel-diff pass rate is a separate, pre-existing issue,
not a new regression from this incident.** Visual inspection of the diff
image found the large red panel/dock region is driven by two concrete,
measurable default-state differences between a real Calamares install and
the pre-baked screenshot-harness test image: the golden's system tray has
one more icon (a screen/share-type indicator absent on the real install)
and its volume icon shows muted, where the real install's is unmuted. This
matches the project's own 2026-10-15 memory note ("14/22 pikseliero
avoinna") recorded before this crash investigation ever started - this is
the project's already-known, separately-tracked pixel-diff backlog
resurfacing now that the harness can reach the diff-pass again, not
something this incident introduced. Treat it as its own follow-up task
(tray/indicator default-state inventory between a real install and the test
image), not a blocker on this incident being closed.

## DoD (this project's concrete interpretation)

From `distro-tyonkulku.md` §3: "ISO bootaa UEFI + BIOS, asentuu VM:ään ja
fyysiselle raudalle, asennettu järjestelmä läpäisee vaiheiden 3–6 diffit."

- **UEFI + BIOS boot, VM install, installed-system diff-pass:** fully
  automated, enforced by this repository's own harness (extended in a later
  piece of this phase — boot the ISO under both firmware paths in QEMU, drive
  a real Calamares install via synthetic UI input since Calamares has no
  built-in unattended-install mode (confirmed, see memory/commit history of
  this phase), then boot the installed disk and run the existing
  `harness/shots/capture`+`compare` against the same `harness/goldens/` used
  for vaiheet 3–6).
- **Physical hardware:** explicitly **not** automated and not claimed by any
  test in this repository. The project owner performs this manually once a
  real ISO exists and reports the result back; this repository only has to
  make that manual step possible (a working, correctly-sized ISO), not prove
  it by itself.

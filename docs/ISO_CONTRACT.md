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

# Guest image of the screenshot harness

The desktop that the harness photographs runs in a virtual machine (QEMU/KVM, no host GPU).
This directory builds the disk image of that machine. The contract for everything around it
(states, capture, comparison, goldens) is `docs/HARNESS_CONTRACT.md`; the feasibility spike
this grew out of is `harness/spike/`.

## Files

| Path | Purpose |
|---|---|
| `Containerfile` | The guest system: the pinned archive snapshot, the metapackage from the signed repository, test-only packages, deterministic configuration. |
| `build_rootfs.sh` | Podman build, `podman export`, `mke2fs -d` in a helper container. Produces `root.img`, `vmlinuz`, `initramfs.img` in `.build/vm/`. No mounts, no root. |
| `guest/mkinitcpio-vm.conf` | Initramfs modules for direct kernel boot (no `autodetect`, so the result does not depend on the build machine). |
| `guest/skel/` | Configuration files of the desktop user (copied to `/etc/skel`, hence to the home directory). Plain data files. |
| `guest/templates/` | Data files that need the home directory of the user; the Containerfile fills in `@HOME@`. |
| `guest/overlay/` | System files copied onto `/`: helper programs, the browser policy, the test page. |
| `guest/make-sample-tree.sh` | Creates the fixed sample folders and files (fixed modification times) at build time. |

## Build

```bash
make vm-image                 # rebuilds the signed repository, then the image
make -o repo vm-image         # the same, but keeps the repository that is already in .build/repo
harness/vm/build_rootfs.sh    # the image only, from the repository in .build/repo
```

Run it in the Linux checkout as an unprivileged user with rootless Podman. Outputs go to
`.build/vm/` (override with `VM_BUILD_DIR`, size of the sparse image with `VM_IMAGE_SIZE`).
Each output is first written as `*.new` and then renamed, so a program that boots the image
while a build runs never sees a half-written file. Only one build at a time (a lock file
enforces it).

Layer design, because the repository is signed anew on every `make repo`: the system and
**all dependencies of the metapackage** are installed in an early layer that does not
depend on the repository (the list is read from the PKGBUILD by `build_rootfs.sh` and
passed as a build argument). The repository is copied in afterwards and only the metapackage
itself is installed from it, so a rebuild after `make repo` repeats only the small layers at
the end. The result is the same set of packages as installing the metapackage in one step.

The archive server answers many parallel downloads with stalls ("Operation too slow"); the
image therefore downloads with two connections, no speed limit, and retries each big
install three times.

Measured on the development machine (4 cores, WSL2): see the end of this file.

## What is in the image

* Arch Linux frozen to `ARCH_ARCHIVE_DATE`, kernel, `mesa` (software renderer), the QEMU guest
  agent, SDDM with autologin into the Wayland Plasma session, and the metapackage.
* **Test image only** (not part of the shipped metapackage, installed in a separate layer):
  `libnotify` (`notify-send`), `firefox` (the `browser-window` state), and `dolphin` and
  `systemsettings` (also required by the states; already pulled in by the metapackage today).
  KRunner is part of the shell package. The build fails if any of these programs is missing.
* One user: `desktop`, uid 1000, password locked, home `/home/desktop`, logged in
  automatically. The Wayland socket is `wayland-0`, the session bus is
  `/run/user/1000/bus`.
* Helper programs in `/usr/local/bin`:
  * `desktop-run [--wait] PROGRAM [ARGS...]` starts a program as the desktop user inside the
    running session: an empty environment plus the environment that the running session
    exported (session bus, Wayland display, desktop variables) and the software rendering
    variables. The guest agent runs as root outside the session, so this is how a state
    starts a GUI program. It returns at once; `--wait` runs in the foreground and passes the
    exit status. (Starting a program with `runuser -u desktop -- env XDG_RUNTIME_DIR=...
    DBUS_SESSION_BUS_ADDRESS=... WAYLAND_DISPLAY=wayland-0 ...` works too; both ways were
    tried with the file manager, System Settings and the browser.)
  * `harness-browser [FILE]` opens the fixed page `/usr/local/share/harness/browser-page.html`
    in a brand new browser profile (copied from the template with the preferences that turn
    off first-run pages, updates, telemetry and restore prompts) so that every launch is a
    first launch.

### The browser

`firefox` was stable and deterministic with a fresh profile, a policy file, software
rendering and a local static page, so `konqueror` (which would need a whole web engine,
about 400 MB more) was not needed. Two measured details: the browser opens at its own
1204x700 unless it is given `--width/--height` (the window rule alone cannot resize it),
and its application id is `firefox`.

## Boot it by hand

With the spike tooling (screenshots and a command channel into the guest):

```bash
harness/spike/boot_capture.sh dbg1 --diag --min-png-bytes 20000
harness/spike/boot_capture.sh dbg2 --min-png-bytes 20000 --guest-cmd 'desktop-run dolphin' --after-delay 10
```

`--min-png-bytes 20000` is needed with this image: the spike treats a screenshot smaller
than 150,000 bytes as blank, and the solid wallpaper makes a healthy screenshot about
35,000 bytes. Results are in `.build/vm/runs/<tag>/` (`<tag>.png`, `<tag>-after.png`,
serial log, journal).

To look at the desktop with your own eyes, start QEMU with a VNC server and connect a VNC
viewer to `127.0.0.1:5900`. `-snapshot` keeps the image unchanged:

```bash
qemu-system-x86_64 -machine q35 -accel kvm -cpu host -smp 4 -m 4096 \
    -kernel .build/vm/vmlinuz -initrd .build/vm/initramfs.img \
    -append "root=/dev/vda rw console=ttyS0 net.ifnames=0" \
    -snapshot -drive file=.build/vm/root.img,if=virtio,format=raw \
    -vga none -device virtio-vga,xres=2560,yres=1440 -device usb-ehci -device usb-tablet \
    -nic none -rtc base=2026-09-25T12:00:00,clock=vm -vnc 127.0.0.1:0 -serial stdio
```

The screen must be 2560x1440: the output scale is stored for exactly that monitor.

## Determinism settings and why

Everything here is a data file under `guest/`; nothing is a script that runs at boot.
Each setting was checked in the running guest: the ones marked "control" were also
switched off once to see the difference.

| Setting | Where | Why |
|---|---|---|
| Solid wallpaper, colour `128,128,128` (`org.kde.color` plugin) | `skel/.config/plasma-org.kde.plasma.desktop-appletsrc` | A picture would pull the comparison towards the wallpaper. A neutral grey works in both colour modes. |
| Complete desktop layout shipped instead of generated | same file, `plasmashellrc`, `kactivitymanagerdrc` | The wallpaper plugin can only be chosen in the layout. The layout is the generated default with these changes: wallpaper, fixed task manager launchers, fixed launcher favourites, no network applet. The activity id is fixed and must be equal in both files. `plasmashellrc` marks the layout migrations as done. |
| Fixed task manager launchers and launcher favourites (System Settings, Dolphin, Konsole) | same file (`launchers=`, `favorites=`) | The default has a "preferred browser" entry, so the panel and the launcher would differ with and without the test-only browser. |
| No network applet in the tray | same file (`extraItems`) | The guest has no network; the applet's state is noise. |
| Animations off | `skel/.config/kdeglobals` (`AnimationDurationFactor=0`) | Frames are compared; a state must not be caught mid-animation. |
| Text cursor does not blink | `kdeglobals` (`CursorBlinkRate=0`) | Control: with the value 1000 two consecutive screenshots of the search field alternate between two pictures. |
| No screen locker | `kscreenlockerrc` | A locked screen is not the desktop. |
| Never dim, blank or suspend | `powerdevilrc` | A capture session can outlast the default idle timeouts. The Power Management page of System Settings shows "Do nothing", "Never", "Never". |
| No file indexer | `baloofilerc` | Background CPU load and index-dependent results. |
| No splash screen | `ksplashrc` | One less moving part at start-up. |
| No wallet prompts | `kwalletrc` | A first-use dialog would appear over the desktop. |
| Notification pop-ups stay until closed | `plasmanotifyrc` (`PopupTimeout=0`) | Control: without the key the pop-up is gone after about 5 seconds, with it it is still there after 17 seconds. The key is only read at start of the shell, so it works from the image, not when changed in a running session. |
| Fixed window geometry (1000x600 at 140,50 logical px) for the file manager, System Settings and the browser | `skel/.config/kwinrulesrc`, `--width/--height` in `harness-browser` | Window size and place would otherwise be remembered from the previous run or chosen by the application. The values keep the window above the floating panel of the 1280x720 logical screen (the 1000x650 at 140,90 of the contract's example would end at y = 740, below the screen). The rules match the application ids the programs announce: `org.kde.dolphin`, `systemsettings`, `firefox`. |
| Output scale 2 on the virtual 2560x1440 monitor | `skel/.config/kwinoutputconfig.json` | See the spike; matched by the monitor's EDID hash, hence valid for this resolution only. |
| Software rendering variables | `skel/.config/plasma-workspace/env/10-vm-rendering.sh` | No GPU; explicit instead of probing. |
| English locale (`en_US.UTF-8`), UTC, US keyboard | `Containerfile`, `plasma-localerc`, `kxkbrc` | Dates, number formats and key mapping must not depend on anything. |
| Fixed host name (`<distro>-vm`), machine id, file system uuid | `build_rootfs.sh` | Name-derived state is identical between builds. |
| Fixed sample folder tree, fixed modification times, empty Desktop | `make-sample-tree.sh`, `skel/.config/user-dirs.dirs`, `overlay/etc/xdg/user-dirs.conf` | The file manager shows real content that never changes; the desktop shows the Desktop folder, so it stays empty. The tool that would create folders at login is switched off. |
| Fixed places panel, disk section hidden | `templates/user-places.xbel` | The disk entry shows a usage bar that follows the size of the image. |
| Kickoff (application launcher) popup height raised from the shell default of 400 to 900 | `skel/.config/plasma-org.kde.plasma.desktop-appletsrc`, `[Containments][2][Applets][3][Configuration]` | Control: the popup's actual height is `max(popupHeight, content implicit height)`, and the content's own implicit height varies by a few logical pixels from boot to boot (identical image, identical steps), which used to shift the bottom tab/power-button bar and fail two-boot determinism (`menubar-open`, ~17,000 differing pixels). Confirmed narrow: unaffected by restarting `plasmashell` or reopening the popup within one boot, and unaffected by waiting longer before the first open - only a fresh boot reproduces the variance, so it is decided once, early, per boot. A smaller margin (450) removed the flip when `menubar-open` was captured alone but still failed intermittently in the full 9-state sequence (the variance is bigger, or hit more often, once `desktop-empty`'s own reset/settle cycle has run first). 900 exceeds the space available above the panel, so the popup is clamped to the largest size that fits the screen - governed by fixed screen geometry instead of the variable content height - which held over repeated fresh boots in both the isolated and full-sequence cases. Trade-off accepted deliberately: the popup shows more empty space below the favourites grid than the 400 default did. |
| Browser profile made fresh on every start; first-run, update, telemetry, restore and notification prompts off; caret and animations off; software rendering | `overlay/usr/local/share/harness/firefox-profile/user.js`, `overlay/usr/lib/firefox/distribution/policies.json`, `harness-browser` | A first launch is the only launch that is always the same. |

The clock in the panel is not made deterministic (the VM clock starts at a fixed date, but
it advances): the comparison masks it (`docs/HARNESS_CONTRACT.md`). Two clean boots differ
only there.

## Regenerating the desktop layout

`plasma-org.kde.plasma.desktop-appletsrc` and `plasmashellrc` are copies of what the shell
generates on the first login, edited as described above. After changing `ARCH_ARCHIVE_DATE`
(a new Plasma version) check that they are still valid: boot the image, take a screenshot,
and compare the shipped layout with the one the new shell generates for a user without one
(`~/.config/plasma-org.kde.plasma.desktop-appletsrc` after a login with an empty `~/.config`).

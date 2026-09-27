# Screenshot harness feasibility spike

Question: can a QEMU/KVM guest running `kuura-desktop` (KDE Plasma 6, Wayland) boot to
a rendered, logged-in desktop **without a host GPU**, and is a host-side screenshot of
it reproducible? Answer on the test machine (WSL2, 4 cores, no GPU passthrough): **yes**.

Everything here is a spike, not the final harness. Build artefacts live in
`.build/vm/` (git-ignored), never in the source tree.

## Files

| File | Purpose |
|---|---|
| `Containerfile` | Guest system: pinned archive snapshot, signed repository trusted as in `build/verify_install.sh`, kernel, `kuura-desktop`, SDDM autologin. |
| `guest/` | Small guest configuration files copied into the image (initramfs modules, session environment, output scale 2). |
| `build_rootfs.sh` | Podman build, `podman export`, and `mke2fs -d` inside a helper container: produces `root.img`, `vmlinuz`, `initramfs.img`. No mounts, no root. |
| `boot_capture.sh` / `vm_capture.py` | Boots the image, takes host-side `screendump` PNGs through QMP until the desktop is stable, records timings and host CPU/RAM. |
| `compare_png.py` | Pixel-by-pixel comparison of two PNGs (standard library only). |
| `determinism_check.sh` | Boots N times and compares the screenshots. |

## Reproduce

Run inside the Linux checkout (see `docs/BUILD_CONTRACT.md`), as an unprivileged user
with rootless Podman, QEMU and `/dev/kvm`:

```bash
make repo                                # signed repository in .build/repo
harness/spike/build_rootfs.sh            # ~5 min the first time, ~1 min with a warm cache
harness/spike/boot_capture.sh run1 --diag        # one boot + screenshot
harness/spike/determinism_check.sh 2             # two boots + pixel comparison
```

Results of a run are in `.build/vm/runs/<tag>/`: `<tag>.png` (the screenshot),
`<tag>-summary.json` (timings, resources, frame history), `<tag>-serial.log` (kernel
and systemd log), `frames/` (every distinct frame seen while waiting), and with
`--diag` `<tag>-journal.txt`. `--guest-cmd CMD` (repeatable) runs a command in the
guest through the guest agent after the stable point and writes a second screenshot
`<tag>-after.png`; that is how the output scale was found.

## Design

* **Rootfs without loop mounts**: `podman build` -> `podman export` -> helper container
  extracts the tar and runs `mke2fs -d`. Files stay owned by root. 12 GiB sparse image,
  2.7 GiB actually used.
* **Direct kernel boot**: kernel and initramfs are taken from the image; no bootloader,
  no UEFI. A `mkinitcpio` drop-in without `autodetect` keeps the initramfs independent
  of the machine that built it (autodetect would inspect the build host's modules).
* **Display**: `virtio-vga` (KMS device, no GL, no host GPU). KWin renders with
  OpenGL on Mesa **llvmpipe** (software); the guest journal confirms it. The session
  environment sets `LIBGL_ALWAYS_SOFTWARE=1` and `MESA_LOADER_DRIVER_OVERRIDE=kms_swrast`
  (whether the defaults would also work was not tested).
* **Scale 2x**: `guest/skel/.config/kwinoutputconfig.json` (2560x1440, logical
  1280x720). It is matched by the EDID hash of the virtual monitor, which QEMU derives
  from the resolution, so it only applies to 2560x1440.
* **Screenshot**: QMP `screendump` (PNG) from the host; nothing runs in the guest for it.
* **Trigger**: the guest agent reports the `plasmashell` process AND two consecutive
  frames (5 s apart) are byte-identical AND the frame is not blank.
* **Isolation**: `-snapshot` (the image is never written), `-nic none`, fixed RTC.

## Deviations from the suggested design

* The RTC base defaults to `2026-09-25T12:00:00` (after the archive snapshot date), not
  `2026-01-01`. Tested: with `--rtc-base 2026-01-01T12:00:00` the guest reported
  `Thu Sep 10 20:41 UTC 2026`, i.e. systemd advanced the clock to its own build time,
  so the visible date and time would depend on the package versions and on boot speed.
  Any base date after the snapshot date avoids this.
* `-snapshot` is added, otherwise the second boot would start from the state left by the
  first (journal, session caches).
* The guest agent is used only to decide *when* to take the screenshot and for
  diagnostics, never to produce it.

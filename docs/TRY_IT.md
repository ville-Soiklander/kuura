# Try kuura

The quickest way to try kuura is a virtual machine: nothing on your computer
changes, and the live session starts straight into the desktop. This page covers
downloading and checking the ISO, running it in a virtual machine on Windows or
Linux, and trying it on a real computer.

The project's own automated tests boot the ISO in QEMU/KVM (BIOS and UEFI,
including a full install). The VirtualBox steps below are the recommended
settings for that hypervisor, not part of the automated tests.

## 1. Download

From the [release page](https://github.com/ville-Soiklander/kuura/releases)
download:

| File | What it is |
|---|---|
| `kuura-2026.09.24-x86_64.iso.001`, `kuura-2026.09.24-x86_64.iso.002` | the ISO in two parts (GitHub limits one file to 2 GiB) |
| `SHA256SUMS`, `SHA256SUMS.sig` | checksum of the whole ISO and its signature |
| `kuura-release-signing-key.asc` | the public release key |

### Join the two parts

Windows, in Command Prompt (`cmd`) in the download folder:

```bat
copy /b kuura-2026.09.24-x86_64.iso.001 + kuura-2026.09.24-x86_64.iso.002 kuura-2026.09.24-x86_64.iso
```

(Or with 7-Zip: right-click the `.001` file and choose "Combine files".)

Linux:

```sh
cat kuura-2026.09.24-x86_64.iso.001 kuura-2026.09.24-x86_64.iso.002 > kuura-2026.09.24-x86_64.iso
```

### Check the download

The checksum proves the joined ISO is intact; the signature proves the checksum
file comes from the project.

Windows (PowerShell):

```powershell
Get-FileHash .\kuura-2026.09.24-x86_64.iso -Algorithm SHA256
Get-Content .\SHA256SUMS
```

The two hashes for the ISO must be identical. To check the signature, install
[Gpg4win](https://www.gpg4win.org/) and run the Linux commands below in a new
terminal.

Linux:

```sh
sha256sum --check --ignore-missing SHA256SUMS      # the ISO must report: OK
gpg --import kuura-release-signing-key.asc
gpg --verify SHA256SUMS.sig SHA256SUMS             # must report: Good signature
```

The release key's fingerprint is
`D443 8A0A 671E EFC3 7A01  9E73 A803 7E12 7876 7385`; compare it with the one
`gpg --verify` prints.

## 2. Run it in a virtual machine

### Windows: VirtualBox

[VirtualBox](https://www.virtualbox.org/) is free and runs on every Windows
edition (Hyper-V is not available on Home editions). Virtualization must be
enabled in the computer's firmware settings; if WSL2 already works on the
machine, it is.

1. **New** virtual machine: name `kuura`, ISO image: the joined ISO, type
   **Linux**, version **Arch Linux (64-bit)**. Tick "Skip unattended
   installation" if it is offered.
2. **Hardware**: memory **4096 MB** or more, processors **2-4**, and tick
   **Enable EFI** (BIOS also works; UEFI matches modern computers).
3. **Hard disk**: create a new disk of **30 GB** (5.5 GB is the minimum the
   installer accepts). Only needed if you want to try the installer.
4. Finish, then open **Settings > Display**: video memory **128 MB**, graphics
   controller **VMSVGA**, tick **Enable 3D Acceleration**. The glass effects
   (blur behind the top bar, the shelf and the menus) need 3D acceleration; if
   the desktop shows drawing errors, turn it off: everything still works, only
   without the blur.
5. **Start**. Pick the first boot menu entry. The live session signs in by itself
   to the kuura desktop; nothing is installed.

To try the installer, start it from the application menu and follow
[INSTALL.md](INSTALL.md#run-the-installer). Before the restart at the end, remove
the ISO from the virtual optical drive (**Devices > Optical Drives**) so the
machine boots the installed system.

### Linux: QEMU/KVM

With `virt-manager`, create a new virtual machine from the ISO (operating system:
Arch Linux), 4 GiB memory, 2-4 CPUs, and enable 3D acceleration for the display
(Video: Virtio, Display: Spice with OpenGL) to get the blur.

Or directly with QEMU, without a disk (live session only):

```sh
qemu-system-x86_64 -enable-kvm -cpu host -m 4096 -smp 4 \
    -device virtio-vga-gl -display gtk,gl=on \
    -cdrom kuura-2026.09.24-x86_64.iso
```

## 3. Try it on a real computer

Write the ISO to a USB stick and boot from it; the live session changes nothing
on the computer until you run the installer. The steps, requirements and the
installer pages are in [INSTALL.md](INSTALL.md).

## What to look at

- **Light and dark**: the welcome window at login switches the mode; the top
  bar, shelf, window title bars and applications follow it at once.
- **The glass**: the top bar, the shelf and menus are frosted glass over the
  wallpaper (needs 3D acceleration).
- **Window buttons**: round close, minimize and maximize on the left of every
  title bar; the symbols appear when the pointer is over them.
- **Search**: `Alt+Space`. **Overview of windows**: `Meta+W`.

Found something? Open an issue on the
[issue tracker](https://github.com/ville-Soiklander/kuura/issues) with what you
did, what you expected and, if possible, a screenshot.

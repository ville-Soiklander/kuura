# Installing kuura

This guide takes you from the downloaded ISO to a first login.

## Before you start

Verify the download as described in the README (`SHA256SUMS` and its GPG
signature). Back up anything you care about on the target disk: the installer
can erase it.

### System requirements

| | |
|---|---|
| CPU | 64-bit x86 (x86_64) |
| Memory | 1 GiB is the minimum the installer enforces; a graphical Plasma session is far more comfortable with 4 GiB or more |
| Disk | at least 5.5 GiB on the target disk (the installer warns below this); more for your own data |
| Firmware | BIOS or UEFI; the ISO boots in both modes |
| Medium | a USB stick (the ISO is about 2.3 GiB) or a virtual optical drive |
| Graphics | a GPU supported by the open Linux drivers; the live session runs Plasma on Wayland |

An internet connection is not needed to install: the ISO carries kuura's own
packages and the installer installs from the medium.

## Write the ISO to a USB stick

Writing the image **erases everything on the stick**. Make sure you name the
right device.

On Linux, find the stick with `lsblk` and write the image to the whole device
(not a partition such as `sdX1`):

```sh
sudo dd if=kuura-<version>-x86_64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

Any tool that writes a raw image to a device also works, on any operating
system. Choose the "DD image" / "write in raw mode" option if the tool asks.

## Boot the live session

1. Insert the stick and restart the computer.
2. Open the firmware's boot menu (commonly F12, F11, F10, F8 or Esc during
   start-up) and choose the stick. If the firmware lists the stick twice, the
   entry marked UEFI starts the UEFI boot path, the other the BIOS path.
3. The live session starts and signs in by itself to a Plasma desktop. Nothing
   is installed until you run the installer.

If the stick does not appear in the boot menu, check that it was written as a
raw image and, on a UEFI computer, try another USB port.

## Run the installer

Start the installer (Calamares) from the live desktop's application menu. It
walks through these pages:

1. **Welcome** - choose the language. The installer checks the machine here and
   will not continue with less than 1 GiB of memory; it also checks the disk
   size (5.5 GiB).
2. **Location** - region and time zone.
3. **Keyboard** - keyboard model and layout, with a field to test the layout.
4. **Partitions** - choose where to install. The default file system is ext4.
   Disk encryption (LUKS) is available but not forced, and no particular swap
   scheme is forced either: the default is no swap, and you can pick a small
   swap, a swap sized for suspend, or a swap file. On a UEFI computer the
   installer creates an EFI system partition (recommended size 300 MiB). Choose
   "Erase disk" only if the whole disk may be wiped; use manual partitioning to
   keep other systems.
5. **Users** - your name, login name, computer name and password. There is no
   separate root password: your account is an administrator and uses `sudo`.
6. **Summary** - review every change. Nothing is written to the disk before you
   confirm here.
7. The installation runs and shows its progress.
8. **Finish** - when it is done you can restart straight away (the option is
   off by default). Remove the USB stick when the computer restarts.

The boot loader (GRUB) is installed for the firmware mode you booted in, BIOS or
UEFI.

## First login

After the restart the login screen appears. Sign in with the account you
created. A welcome window opens at the first login. The installed system has the
same desktop as the live session, without the live-only rescue tools.

## Updates

kuura's own packages come from the ISO and there is no kuura package server
yet, so they are updated by installing a newer release. The Arch Linux packages
in the system are handled by `pacman` as on any Arch-based system.

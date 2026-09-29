#!/bin/sh
# Sourced by the Plasma session at start-up (before KWin), see
# ~/.config/plasma-workspace/env/ (same mechanism as 10-vm-rendering.sh).
#
# TEST IMAGE ONLY. Loads appmenu-gtk-module (also test-image only, see
# harness/vm/Containerfile) for every GTK3 app in this session, the same way a real
# desktop environment that ships global-menu support turns it on system-wide (some
# distributions do this through /etc/gtk-3.0/gtkrc's gtk-modules= key instead; this
# project uses the same env/ mechanism it already uses for rendering, so there is only
# one place session-wide environment is set). Needed by the `app-menu-gtk` state
# (docs/SHELL_CONTRACT.md's "Verification" section, point 1): a classic GtkMenuBar
# app's menu (Mousepad, this test image's app-menu-gtk state) is exported to KDE's
# global-menu registrar ONLY when this module is loaded into the app's own process -
# without it, com.canonical.AppMenu.Registrar's D-Bus name still gets activated by
# kappmenu itself (it is always-activatable), which can look like something worked
# when reading busctl output alone, but no window ever actually registers a menu with
# it and the panel's Global Menu widget stays empty. Confirmed live both ways: absent,
# the registrar name appears but the panel shows nothing for Mousepad; present, see
# the implementing agent's report for the screenshot.
export GTK_MODULES=appmenu-gtk-module

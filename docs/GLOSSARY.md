# Glossary

The project's own vocabulary. User-visible text, package names, file names and
documentation use these names and nothing else.

**Status: approved by the owner on 2026-09-25**, including the project name. The
name still lives in one variable (`DISTRO_NAME`), so a later rename stays a
one-line change, but it is no longer provisional.

| Function | Name |
|---|---|
| Distribution name | `kuura` |
| Quick search launcher | Beacon |
| File manager | Files |
| Application shelf (floating icon bar) | Shelf |
| Window overview | Overview |
| Glass-like surface material (blur, edge refraction, highlight, grain) | Frost |
| UI font family alias (Inter based) | `<DISTRO_NAME> Sans` |
| Top bar with global menu, system tray and clock | Menubar |

Rules:

- New components get their own names and are added to this table first.
- The trademark check of the name was done by the owner before approval.
  `tools/check_forbidden_terms.py` enforces the list of names that must never
  appear anywhere in the repository.
- The project logo is an asset: it needs human approval and an entry in
  `docs/ASSETS.md` before it is added.

# Glossary

The project's own vocabulary. User-visible text, package names, file names and
documentation use these names and nothing else.

**Status: proposed.** The names become final when the owner approves them; until
then the codename can still change (it lives in one variable, `DISTRO_NAME`).

| Function | Name |
|---|---|
| Distribution codename | `kuura` (temporary) |
| Quick search launcher | Beacon |
| File manager | Files |
| Application shelf (floating icon bar) | Shelf |
| Window overview | Overview |
| Glass-like surface material (blur, edge refraction, highlight, grain) | Frost |
| UI font family alias (Inter based) | `<DISTRO_NAME> Sans` |
| Top bar with global menu, system tray and clock | Menubar |

Rules:

- New components get their own names and are added to this table first.
- Names must be checked for trademark conflicts by a human before the codename is
  made final. `tools/check_forbidden_terms.py` enforces the list of names that
  must never appear anywhere in the repository.
- The project logo is an asset: it needs human approval and an entry in
  `docs/ASSETS.md` before it is added.

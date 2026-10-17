"""
Invariant: harness/vm/guest/skel/ holds ONLY files the product does not ship.

Why: the shots image copies guest/skel/ wholesale over /etc/skel, so a file that the
product also ships (packages/kuura-shell/skel/) would REPLACE the product's version and
hide real product behaviour from the goldens (this happened with kdeglobals and
kscreenlockerrc). Files the product also ships belong in guest/skel-merge/ instead.
"""

from __future__ import annotations

from pathlib import Path

from harness.install import wizard

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUEST_SKEL = PROJECT_ROOT / "harness" / "vm" / "guest" / "skel"
PRODUCT_SKEL = PROJECT_ROOT / "packages" / "kuura-shell" / "skel"


def shadowed_by_product(guest_dir: Path, product_dir: Path) -> list[str]:
    """
    Find guest skeleton files that the product also ships.

    Args:
        guest_dir: The test-only skeleton tree.
        product_dir: The product's skeleton tree.

    Returns:
        Sorted relative POSIX paths present in both trees. A product template
        ``X.in`` counts as shipping ``X`` (it is rendered at package build time).
    """
    shipped: set[str] = set()
    for path in product_dir.rglob("*"):
        if path.is_file():
            rel = path.relative_to(product_dir).as_posix()
            shipped.add(rel)
            if rel.endswith(".in"):
                shipped.add(rel[: -len(".in")])
    return sorted(
        rel
        for rel in (p.relative_to(guest_dir).as_posix() for p in guest_dir.rglob("*") if p.is_file())
        if rel in shipped
    )


def test_guest_skel_has_no_file_the_product_ships() -> None:
    """The real trees never overlap."""
    assert shadowed_by_product(GUEST_SKEL, PRODUCT_SKEL) == []


def test_real_trees_exist_and_are_not_empty() -> None:
    """Guard against the invariant passing vacuously on a moved directory."""
    assert any(p.is_file() for p in GUEST_SKEL.rglob("*"))
    assert any(p.is_file() for p in PRODUCT_SKEL.rglob("*"))
    assert wizard._GUEST_SKEL_DIR == GUEST_SKEL


def test_detector_catches_a_plain_overlap(tmp_path: Path) -> None:
    """The check would have caught kdeglobals / kscreenlockerrc / 20-gtk-appmenu.conf."""
    guest, product = tmp_path / "g", tmp_path / "p"
    for rel in (".config/kdeglobals", ".config/environment.d/20-gtk-appmenu.conf"):
        for root in (guest, product):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("x")
    (guest / ".config/only-test").write_text("x")
    assert shadowed_by_product(guest, product) == [
        ".config/environment.d/20-gtk-appmenu.conf",
        ".config/kdeglobals",
    ]


def test_detector_treats_a_product_template_as_shipping_its_output(tmp_path: Path) -> None:
    """A product ``X.in`` ships ``X``, so the same name in the guest tree is an overlap."""
    guest, product = tmp_path / "g", tmp_path / "p"
    (guest / "d").mkdir(parents=True)
    (product / "d").mkdir(parents=True)
    (guest / "d/15-gtk-theme.conf").write_text("x")
    (product / "d/15-gtk-theme.conf.in").write_text("x")
    assert shadowed_by_product(guest, product) == ["d/15-gtk-theme.conf"]

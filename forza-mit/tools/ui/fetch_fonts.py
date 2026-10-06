"""Download the UI fonts (all SIL OFL 1.1, from github.com/google/fonts) into CambridgeRacer/UI/Fonts.

    cd tools/ui && uv run fetch_fonts.py

  Silkscreen-Regular/Bold.ttf  pixel UI font (titles, buttons, labels)      as published
  PressStart2P-Regular.ttf     pixel digits (timer, speed, countdown)       as published (Reserved Font Name: unmodified)
  Doto-Black/Bold.ttf          dot-matrix digits (modern accents)           static instances of the variable font, Latin subset
  OpenSans-Regular/Bold.ttf    body text (descriptions, hints)              static instances of the variable font, Latin subset

Slate (FreeType) renders the default instance of a variable font, so the variable fonts are cut into
static instances here. Doto and Open Sans have no Reserved Font Name, so instancing / subsetting is allowed.
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "CambridgeRacer" / "UI" / "Fonts"
BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl"

# Basic Latin + Latin-1 + general punctuation, arrows, a few symbols used in the UI
LATIN = list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)) + list(range(0x2010, 0x2027)) + [
    0x2030, 0x2032, 0x2033, 0x2039, 0x203A, 0x20AC, 0x2122, 0x2190, 0x2191, 0x2192, 0x2193, 0x2212, 0x25B2, 0x25B6, 0x25BC, 0x25C0,
]


def fetch(path: str) -> bytes:
    url = f"{BASE}/{path.replace('[', '%5B').replace(']', '%5D')}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def static_instance(vf: bytes, axes: dict[str, float], family: str, style: str, out: Path) -> None:
    font = TTFont(io.BytesIO(vf))
    inst = instancer.instantiateVariableFont(font, axes, updateFontNames=False)
    opts = subset.Options()
    opts.layout_features = ["kern", "liga", "tnum", "lnum"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=LATIN)
    sub.subset(inst)
    # static names so tools (and FreeType's style name) agree with the file
    name = inst["name"]
    for rec_id, value in ((1, family), (2, style), (4, f"{family} {style}"), (6, f"{family.replace(' ', '')}-{style}"), (16, family), (17, style)):
        name.setName(value, rec_id, 3, 1, 0x409)
    inst.save(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for src, dst in [
        ("silkscreen/Silkscreen-Regular.ttf", "Silkscreen-Regular.ttf"),
        ("silkscreen/Silkscreen-Bold.ttf", "Silkscreen-Bold.ttf"),
        ("pressstart2p/PressStart2P-Regular.ttf", "PressStart2P-Regular.ttf"),
    ]:
        (OUT / dst).write_bytes(fetch(src))
    doto = fetch("doto/Doto[ROND,wght].ttf")
    static_instance(doto, {"wght": 900, "ROND": 100}, "Doto", "Black", OUT / "Doto-Black.ttf")
    static_instance(doto, {"wght": 700, "ROND": 100}, "Doto", "Bold", OUT / "Doto-Bold.ttf")
    sans = fetch("opensans/OpenSans[wdth,wght].ttf")
    static_instance(sans, {"wght": 400, "wdth": 100}, "Open Sans", "Regular", OUT / "OpenSans-Regular.ttf")
    static_instance(sans, {"wght": 700, "wdth": 100}, "Open Sans", "Bold", OUT / "OpenSans-Bold.ttf")
    static_instance(sans, {"wght": 700, "wdth": 75}, "Open Sans Condensed", "Bold", OUT / "OpenSansCondensed-Bold.ttf")
    for fam in ("silkscreen", "pressstart2p", "doto", "opensans"):
        (OUT / f"OFL-{fam}.txt").write_bytes(fetch(f"{fam}/OFL.txt"))
    total = 0
    for p in sorted(OUT.iterdir()):
        total += p.stat().st_size
        print(f"{p.name:32s} {p.stat().st_size / 1024:7.1f} KB")
    print(f"{'total':32s} {total / 1024:7.1f} KB")


if __name__ == "__main__":
    main()

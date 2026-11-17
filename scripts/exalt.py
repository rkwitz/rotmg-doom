"""Art from your own Realm of the Mad God (Exalt) install, for the client's title screen.

Exalt is a Unity game: its pictures are packed in Unity asset files, read with UnityPy
(`pip install --user UnityPy`). This exports a few named textures to
<workspace>/reference/rotmg/exalt/ (never committed):

  Logo             the "Realm of the Mad God Exalt" logo
  TitleBackground  the title screen's background art

The install is found at Documents/RealmOfTheMadGod/Production (where the launcher puts the game),
or ROTMG_EXALT_DIR. `setup.py client` copies the results into the built client's assets.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

WANTED = ("Logo", "TitleBackground")
FILES = ("globalgamemanagers.assets", "resources.assets")


def exalt_data() -> Path | None:
    env = os.environ.get("ROTMG_EXALT_DIR")
    for base in ([Path(env)] if env else []) + [Path.home() / "Documents" / "RealmOfTheMadGod" / "Production"]:
        data = base / "RotMG Exalt_Data"
        if data.is_dir():
            return data
    return None


def export(out: Path) -> dict[str, Path]:
    """Name -> exported PNG, for each WANTED texture found (empty without UnityPy or the game)."""
    data = exalt_data()
    if data is None:
        return {}
    try:
        import UnityPy
    except ImportError:
        return {}
    out.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    for name in FILES:
        path = data / name
        if not path.exists():
            continue
        env = UnityPy.load(str(path))
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            tex = obj.read()
            if tex.m_Name in WANTED and tex.m_Name not in found:
                png = out / f"{tex.m_Name}.png"
                tex.image.save(png)
                found[tex.m_Name] = png
    return found


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent.parent / "reference" / "rotmg" / "exalt"
    result = export(target)
    print(result or "nothing exported (is UnityPy installed and the game in Documents/RealmOfTheMadGod?)")
    sys.exit(0 if result else 1)

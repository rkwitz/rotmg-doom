"""RotMG's ground tiles and objects (walls, trees, enemies, players, portals, items, projectiles)
as Doom sprites.

Reads the client's own sprite sheets and object XML from the TK-Client checkout (server/TK-Client,
the same commit as the server) and writes, all under build/ (never committed):

  build/sprites/RxxxA0.png       one 4-character sprite name per distinct (sheet, index) picture,
                                 with a grAb offset at its centre
  build/zscript/romtg_sprites.zs an actor whose states name every sprite, so Doom registers them
                                 (Doom only knows sprite names that some state uses)
  build/romtg-assets.json        type id -> sprite for grounds and objects, read by the swapper

Pictures stay at RotMG's own pixel size; Doom scales them per actor, so they stay sharp.
"""
from __future__ import annotations

import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLIENT_SRC = REPO / "server" / "TK-Client" / "src"
ASSETS = CLIENT_SRC / "kabam" / "rotmg" / "assets"
BUILD = REPO / "build"
WALL_CLASSES = {"Wall", "ConnectedWall", "CaveWall", "DoubleWall"}
DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def sprite_name(n: int) -> str:
    """'R' and three base-36 digits: R000 .. RZZZ."""
    return "R" + DIGITS[n // 1296 % 36] + DIGITS[n // 36 % 36] + DIGITS[n % 36]


def image_sets() -> dict[str, tuple[Path, int, int, int, int]]:
    """Sheet name -> (png, picture width, height, block width, height). From AssetLoader:
    addImageSet sheets are a grid of pictures (block = picture); AnimatedChars.add sheets are a
    grid of characters, each a block of animation frames whose first frame is the standing one."""
    loader = (CLIENT_SRC / "com/company/assembleegameclient/util/AssetLoader.as").read_text(encoding="utf-8")
    embedded = (ASSETS / "EmbeddedAssets.as").read_text(encoding="utf-8")
    classes = dict(re.findall(r"static var (\w+):Class\s*=\s*(\w+);", embedded))
    sets = {}
    for name, var, w, h in re.findall(
            r'addImageSet\("(\w+)",\s*new EmbeddedAssets\.(\w+)\(\)\.bitmapData,\s*(\d+),\s*(\d+)\)', loader):
        png = ASSETS / f"{classes.get(var, var)}.png"
        if png.exists():
            sets[name] = (png, int(w), int(h), int(w), int(h))
    for name, var, w, h, bw, bh in re.findall(
            r'AnimatedChars\.add\("(\w+)",\s*new EmbeddedAssets\.(\w+)\(\)\.bitmapData,\s*'
            r'(?:null|new EmbeddedAssets\.\w+\(\)\.bitmapData),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)', loader):
        png = ASSETS / f"{classes.get(var, var)}.png"
        if png.exists() and name not in sets:
            sets[name] = (png, int(w), int(h), int(bw), int(bh))
    # ROMTG-Doom pets: RotMG's other pet sheets, copied from the NR client by scripts/pets.py.
    for name, w, bw in (("romtgPets1", 8, 56), ("chars8x8rPets2", 8, 56), ("petsDivine", 16, 112)):
        png = ASSETS / f"EmbeddedAssets_romtg_{name}.png"
        if png.exists() and name not in sets:
            sets[name] = (png, w, w, bw, w)
    return sets


def model_sizes() -> dict[str, tuple[float, float]]:
    """RotMG's 3D models (EmbeddedAssets' OBJ files: the nexus fountains' "Tower", pillars,
    monuments, tables...) -> (width, height) in tiles, from their vertices. Doom draws an object
    with a model as a box that size, as RotMG draws it in 3D rather than as its flat picture
    (the fountain was a pale flat square in Doom, 2026-11-12)."""
    embedded = (ASSETS / "EmbeddedAssets.as").read_text(encoding="utf-8")
    classes = dict(re.findall(r"static var (\w+):Class\s*=\s*(\w+);", embedded))
    sizes = {}
    for name, var in re.findall(r'"([^"]+)":new (\w+)\(\)', embedded):
        dat = ASSETS / f"{classes.get(var, var)}.dat"
        if not dat.exists():
            continue
        vs = [tuple(float(n) for n in line.split()[1:4]) for line in dat.read_text(encoding="utf-8", errors="replace").splitlines()
              if line.startswith("v ") and len(line.split()) >= 4]
        if not vs:
            continue
        width = max(max(v[0] for v in vs) - min(v[0] for v in vs), max(v[1] for v in vs) - min(v[1] for v in vs))
        height = max(v[2] for v in vs) - min(0.0, min(v[2] for v in vs))
        if width > 0 and height > 0:
            sizes[name] = (round(width, 3), round(height, 3))
    return sizes


def number(text: str) -> int:
    """RotMG XML numbers: 0x-prefixed hex, or decimal (sometimes with leading zeros)."""
    text = text.strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def lean(cell) -> float:
    """Which diagonal a picture lies along: the correlation of its solid pixels' x and y (y
    down), -1 to 1. RotMG's weapons mostly lie handle bottom-left, tip top-right (negative);
    some are drawn the other way round (positive), and Doom mirrors those so every weapon
    points the same way in your hand (Ryan, 2026-11-15)."""
    pts = [(i % cell.width, i // cell.width) for i, px in enumerate(cell.getdata()) if px[3] > 0]
    if len(pts) < 3:
        return 0.0
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    return round(sxy / (sxx * syy) ** 0.5, 3) if sxx > 0 and syy > 0 else 0.0


def animation_frames(sets, sheets, sheet_name, index, sprites_dir, sprite, Image) -> bool:
    """A RotMG character's walk and attack frames as sprite frames F, G (walking) and H, I
    (attacking) of SPRITE beside its A (standing), as RotMG's AnimatedChar reads its block: the
    facing-right row, frames 0 stand, 1 and 2 walk (2 empty: stand), 4 and 5 attack (empty:
    the walk ones), 6 the weapon's swing drawn to the right of 5 (a frame three wide, the
    character in its middle third). True if written (Ryan, 2026-11-15: characters didn't
    animate in Doom)."""
    if sheet_name not in sets:
        return False
    png, w, h, bw, bh = sets[sheet_name]
    if bw < w * 7:
        return False   # not an animation block
    if sheet_name not in sheets:
        sheets[sheet_name] = Image.open(png).convert("RGBA")
    sheet = sheets[sheet_name]
    cols = sheet.width // bw
    if cols == 0:
        return False
    x0, y0 = index % cols * bw, index // cols * bh
    if y0 + h > sheet.height:
        return False

    def frame(k):
        cell = sheet.crop((x0 + k * w, y0, x0 + k * w + w, y0 + h))
        return cell if cell.getbbox() is not None else None

    stand, walk1, walk2, attack1, attack2, swing = frame(0), frame(1), frame(2), frame(4), frame(5), frame(6)
    if stand is None:
        return False
    walk1 = walk1 or stand
    walk2 = walk2 or stand
    if attack1 is None and attack2 is None:
        attack1, attack2 = walk1, walk2
    attack1 = attack1 or attack2
    attack2 = attack2 or attack1
    wide = None
    if swing is not None:
        wide = Image.new("RGBA", (w * 3, h))
        wide.paste(attack2, (w, 0))
        wide.paste(swing, (w * 2, 0))
    for letter, img in (("F", walk1), ("G", walk2), ("H", attack1)):
        (sprites_dir / f"{sprite}{letter}0.png").write_bytes(png_with_grab(img, w // 2, h // 2))
    if wide is not None:
        (sprites_dir / f"{sprite}I0.png").write_bytes(png_with_grab(wide, w + w // 2, h // 2))
    else:
        (sprites_dir / f"{sprite}I0.png").write_bytes(png_with_grab(attack2, w // 2, h // 2))
    return True


def blade_in_hand(png: Path, mirror: bool):
    """A blade's picture turned for your hand, or None if it's right as it is: tip top right
    (mirrored first if MIRROR) and the hilt bottom left. The hilt end is the one whose half
    holds the widest part across the blade (the crossguard); hilt top-right means turned end
    over end (half a turn), which keeps the picture on its diagonal."""
    import math
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    if mirror:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    w, h = im.size
    px = im.load()
    pts = [(x, y) for y in range(h) for x in range(w) if px[x, y][3] > 0]
    if len(pts) < 4:
        return im if mirror else None
    along = [(x - y) / math.sqrt(2) for x, y in pts]   # bottom left -> top right
    across = [(x + y) / math.sqrt(2) for x, y in pts]
    lo, hi = min(along), max(along)
    bins = [[] for _ in range(6)]
    for t, p in zip(along, across):
        bins[min(5, int((t - lo) / (hi - lo + 1e-9) * 6))].append(p)
    width = [max(b) - min(b) if b else 0 for b in bins]
    if max(width[3:]) > max(width[:3]) + 0.7:
        return im.rotate(180)   # hilt top right: end over end
    return im if mirror else None


def bow_in_hand(png: Path, mirror: bool):
    """A bow picture turned for your hand, or None if it's right as it is: tip top right (so
    mirrored first if MIRROR), and its string, a long straight line, on the bottom-right side
    of the bow (towards you) with the curve top-left (away). The string side is the edge with
    more pixels in a straight line across the picture's diagonal; the curve's edge is its
    middle only. Turned by reflecting across that diagonal, which keeps the tip where it is."""
    import math
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    if mirror:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    w, h = im.size
    px = im.load()
    side = [(x + y) / math.sqrt(2) for y in range(h) for x in range(w) if px[x, y][3] > 0]
    if not side:
        return None
    lo, hi = min(side), max(side)
    top_left = sum(1 for p in side if p < lo + 1.0)
    bottom_right = sum(1 for p in side if p > hi - 1.0)
    if top_left <= bottom_right:
        return im if mirror else None   # string already towards you
    out = Image.new("RGBA", (w, h))
    o = out.load()
    for y in range(h):
        for x in range(w):
            o[w - 1 - y, h - 1 - x] = px[x, y]
    return out


def first_texture(node: ET.Element) -> tuple[str, int] | None:
    """(sheet, index) of an element's Texture, or the first of its RandomTexture/AnimatedTexture."""
    for tag in ("Texture", "RandomTexture/Texture", "AnimatedTexture"):
        tex = node.find(tag)
        if tex is not None and tex.findtext("File") and tex.findtext("Index"):
            return tex.findtext("File").strip(), number(tex.findtext("Index"))
    return None


def png_with_grab(img, x: int, y: int) -> bytes:
    """PNG bytes with a grAb chunk (Doom's sprite offset) inserted after IHDR."""
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    body = b"grAb" + struct.pack(">ii", x, y)
    chunk = struct.pack(">I", 8) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    ihdr_end = 8 + 8 + 13 + 4
    return data[:ihdr_end] + chunk + data[ihdr_end:]


def build() -> dict:
    from PIL import Image
    sets = image_sets()
    sheets: dict[str, Image.Image] = {}
    pictures: dict[tuple[str, int], dict] = {}   # (sheet, index) -> {"sprite", "px"}
    sprites_dir = BUILD / "sprites"
    sprites_dir.mkdir(parents=True, exist_ok=True)
    for old in list(sprites_dir.glob("R???A0.png")) + list(sprites_dir.glob("R???B0.png")) + list(sprites_dir.glob("R???[FGHI]0.png")) + list(sprites_dir.glob("ZWHTA0.png")) + list(sprites_dir.glob("ZHPB?0.png")):
        old.unlink()

    def picture(ref: tuple[str, int] | None) -> dict | None:
        if ref is None or ref[0] not in sets:
            return None
        if ref in pictures:
            return pictures[ref]
        png, w, h, bw, bh = sets[ref[0]]
        if ref[0] not in sheets:
            sheets[ref[0]] = Image.open(png).convert("RGBA")
        sheet = sheets[ref[0]]
        cols = sheet.width // bw
        if cols == 0:
            return None
        col, row = ref[1] % cols, ref[1] // cols
        if (row + 1) * bh > sheet.height:
            return None
        cell = sheet.crop((col * bw, row * bh, col * bw + w, row * bh + h))
        if cell.getbbox() is None:   # fully transparent
            return None
        name = sprite_name(len(pictures))
        (sprites_dir / f"{name}A0.png").write_bytes(png_with_grab(cell, w // 2, h // 2))
        # The picture's average colour, as RotMG's minimap shows a tile: for the far ground,
        # past RotMG's own sight, drawn plain.
        opaque = [px for px in cell.getdata() if px[3] > 0]
        rgb = tuple(sum(px[i] for px in opaque) // len(opaque) for i in range(3))
        pictures[ref] = {"sprite": name, "px": w, "py": h, "rgb": (rgb[0] << 16) | (rgb[1] << 8) | rgb[2],
                         "lean": lean(cell)}
        return pictures[ref]

    grounds, objects = {}, {}
    models = model_sizes()
    ground_xml = ET.parse(ASSETS / "EmbeddedData_GroundsCXML.xml").getroot()
    for g in ground_xml.iter("Ground"):
        pic = picture(first_texture(g))
        if pic:
            entry = dict(pic)
            # Moving ground (water, lava...): RotMG scrolls the texture ("Flow": DX, DY texture
            # widths a second) or rocks it ("Wave": sin(DX t), sin(DY t)); Doom does the same.
            anim = g.find("Animate")
            if anim is not None and (anim.text or "").strip() in ("Flow", "Wave"):
                entry["animate"] = anim.text.strip()
                entry["dx"] = float(anim.get("dx") or 0)
                entry["dy"] = float(anim.get("dy") or 0)
            # Ground you sink into (water): RotMG draws you sunk in; Doom lowers your eyes.
            if g.find("Sink") is not None:
                entry["sink"] = True
            grounds[number(g.get("type"))] = entry
    found = []
    for xml in ("EmbeddedData_ObjectsCXML.xml", "EmbeddedData_PlayersCXML.xml", "EmbeddedData_RomtgPetsCXML.xml"):
        if (ASSETS / xml).exists():   # the pets' (scripts/pets.py) only when it has run
            found += list(ET.parse(ASSETS / xml).getroot().iter("Object"))
    for o in found:
        klass = (o.findtext("Class") or "").strip()
        pic = picture(first_texture(o))
        if not pic:
            continue
        entry = {"sprite": pic["sprite"], "px": pic["px"], "py": pic["py"], "rgb": pic["rgb"],
                 "static": o.find("Static") is not None, "wall": klass in WALL_CLASSES,
                 "size": number(o.findtext("Size") or "100"), "class": klass}
        # Projectiles: which way the picture points (AngleCorrection, eighths of a turn from
        # pointing right; RotMG turns it to the flight direction) and how fast it spins
        # (Rotation, ms a radian). Doom points shots the way they fly (Ryan, 2026-11-15).
        if klass == "Projectile" or o.find("AngleCorrection") is not None:
            try:
                entry["ac"] = float(o.findtext("AngleCorrection") or 0)
            except ValueError:
                entry["ac"] = 0.0
            try:
                entry["spin"] = float(o.findtext("Rotation") or 0)
            except ValueError:
                entry["spin"] = 0.0
        if o.findtext("SlotType"):
            entry["slot"] = number(o.findtext("SlotType"))   # weapons: sword 1, dagger 2, bow 3, wand 8...
            # Drawn tip top-left instead of top-right: mirrored in your hand (see lean).
            entry["flip"] = pic.get("lean", 0) > 0.3
            if entry["slot"] in (1, 2, 24):
                # Swords, daggers, katanas: the hilt (its crossguard, the widest part across the
                # blade) at the bottom left, in your hand; some are drawn hilt top-right, tip
                # down (the warrior's, Ryan 2026-11-15). Those turned end over end, a frame B.
                hand = blade_in_hand(sprites_dir / f"{pic['sprite']}A0.png", entry["flip"])
                if hand is not None:
                    (sprites_dir / f"{pic['sprite']}B0.png").write_bytes(
                        png_with_grab(hand, hand.width // 2, hand.height // 2))
                    entry["hand"] = "B"
                    entry["flip"] = False
            if entry["slot"] == 3:
                # Bows: the string toward you (bottom right, as held), the bow's curve away;
                # RotMG draws them both ways (Ryan, 2026-11-15). Turned right, a frame B.
                hand = bow_in_hand(sprites_dir / f"{pic['sprite']}A0.png", entry["flip"])
                if hand is not None:
                    (sprites_dir / f"{pic['sprite']}B0.png").write_bytes(
                        png_with_grab(hand, hand.width // 2, hand.height // 2))
                    entry["hand"] = "B"
                    entry["flip"] = False
        top = o.find("Top")
        top_pic = picture(first_texture(top)) if top is not None else None
        if top_pic:
            entry["top"] = top_pic["sprite"]
        if o.find("DrawOnGround") is not None:
            entry["ground"] = True
        effect = o.find("Effect")
        if effect is not None and (effect.text or "").strip():
            # RotMG's particle effect on the object (the fountains' water, "Fountain"): Doom
            # makes the same particles (romtg_handler.zs, `fx`).
            entry["effect"] = effect.text.strip()
            if effect.get("color"):
                entry["effect_rgb"] = number(effect.get("color"))
        model = (o.findtext("Model") or "").strip()
        if model in models:
            entry["model"] = models[model]
        # Its other looks (AltTexture id=N: a boss changing as it fights, a chest opening...), as
        # RotMG switches to them (the AltTextureIndex stat; Ryan 2026-11-16): their sprites too.
        for alt in o.findall("AltTexture"):
            alt_pic = picture(first_texture(alt))
            if alt_pic is None or alt.get("id") is None:
                continue
            look = {"sprite": alt_pic["sprite"], "px": alt_pic["px"], "py": alt_pic["py"]}
            alt_anim = alt.find("AnimatedTexture")
            if alt_anim is not None and alt_anim.findtext("File") and alt_anim.findtext("Index"):
                if animation_frames(sets, sheets, alt_anim.findtext("File").strip(), number(alt_anim.findtext("Index")),
                                    sprites_dir, alt_pic["sprite"], Image):
                    look["anim"] = True
            entry.setdefault("alt", {})[str(number(alt.get("id")))] = look
        # RandomTexture: RotMG gives each one of these (a shot, a rock, a flower...) one of its
        # pictures at random, so a Staff of Yuletide Carols' two shots differ in colour; Doom
        # only had the first picture (Ryan, 2026-11-17). All of them, the bridge picks per object.
        variants = []
        for tex in o.findall("RandomTexture/Texture"):
            if tex.findtext("File") and tex.findtext("Index"):
                var_pic = picture((tex.findtext("File").strip(), number(tex.findtext("Index"))))
                if var_pic:
                    variants.append({"sprite": var_pic["sprite"], "px": var_pic["px"], "py": var_pic["py"]})
        if len(variants) > 1:
            entry["random"] = variants
        anim = o.find("AnimatedTexture")
        if anim is not None and anim.findtext("File") and anim.findtext("Index"):
            if animation_frames(sets, sheets, anim.findtext("File").strip(), number(anim.findtext("Index")),
                                sprites_dir, pic["sprite"], Image):
                entry["anim"] = True
        objects[number(o.get("type"))] = entry

    # ZWHT: one white pixel, tinted by Doom for the far ground (RomtgFar).
    from PIL import Image as _I
    (sprites_dir / "ZWHTA0.png").write_bytes(png_with_grab(_I.new("RGBA", (1, 1), (255, 255, 255, 255)), 0, 0))
    # ZHPB: an enemy's health bar at its feet, as RotMG draws it (42x7: a dark back, a 40x5 bar
    # from green to red), in 21 frames, A empty to U full, hanging from its bottom middle.
    for n in range(21):
        frac = n / 20
        if frac > 0.5:
            fill = (int(255 * (1 - frac) * 2), 0xDD, 0)
        else:
            fill = (0xDD, int(221 * frac * 2), 0)
        bar = _I.new("RGBA", (42, 7), (17, 17, 17, 200))
        if n:
            bar.paste(fill + (255,), (1, 1, 1 + round(40 * frac), 6))
        (sprites_dir / f"ZHPB{chr(65 + n)}0.png").write_bytes(png_with_grab(bar, 21, 7))
    names = sorted(p["sprite"] for p in pictures.values()) + ["ZHPB", "ZWHT"]
    zs = BUILD / "zscript" / "romtg_sprites.zs"
    zs.parent.mkdir(parents=True, exist_ok=True)
    zs.write_text("// Generated by scripts/assets.py: every RotMG picture's sprite name, so Doom registers them.\n"
                  "class RomtgSpriteList : Actor\n{\n\tStates\n\t{\n\tSpawn:\n"
                  + "".join(f"\t\t{n} A -1;\n" for n in names) + "\t\tStop;\n\t}\n}\n", encoding="utf-8")
    table = {"grounds": {str(k): v for k, v in grounds.items()}, "objects": {str(k): v for k, v in objects.items()}}
    (BUILD / "romtg-assets.json").write_text(json.dumps(table), encoding="utf-8")
    return {"pictures": len(pictures), "grounds": len(grounds), "objects": len(objects),
            "walls": sum(1 for o in objects.values() if o["wall"])}


if __name__ == "__main__":
    if not ASSETS.is_dir():
        sys.exit(f"{ASSETS} missing; run `setup.py server` first")
    print(build())

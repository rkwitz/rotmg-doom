"""RotMG's pet data, from the NR client, made to fit TKR (ROMTG-Doom's pet port).

The pet system is ported from NR-CORE (server) and the NR 27.7 client (reference/repos/NR-CORE and
reference/repos/NR-client, cloned by hand; see docs). Its data, RotMG's own object XML, is not ours
to commit, so this script builds it at setup time from the NR client's files:

  - every object in EmbeddedData_PetsCXML (pets, pet skins, pet abilities and behaviours, pet stones),
    the pet eggs from EmbeddedData_EquipCXML, and the pet yard's portal and upgraders;
  - moved into a type range TKR doesn't use (FIRST_TYPE..), because 17 of NR's pet types are TKR walls
    and trees;
  - with clashing ids renamed (TK has its own "Black Cat" etc. as cosmetic followers): the id gets
    RENAME_SUFFIX, the name you see (DisplayId) stays;
  - with every reference rewritten to match: skin names (DefaultSkin), first abilities (FirstAbility)
    and pet-stone skin types (Activate skinId).

Writes the same XML for the server (TK-Server/TKR.Shared/resources/xml/romtg_pets.xml) and the client
(TK-Client/src/kabam/rotmg/assets/EmbeddedData_RomtgPetsCXML.xml), and build/romtg-pets.json (the
old->new maps), and copies the pet sprite sheets TK's client lacks next to its embedded assets.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKSPACE = REPO.parent
NR_ASSETS = WORKSPACE / "reference" / "repos" / "NR-client" / "src" / "kabam" / "rotmg" / "assets"
TK_SERVER_XML = REPO / "server" / "TK-Server" / "TKR.Shared" / "resources" / "xml"
TK_CLIENT_ASSETS = REPO / "server" / "TK-Client" / "src" / "kabam" / "rotmg" / "assets"
FIRST_TYPE, LAST_TYPE = 0x1A00, 0x1DDF     # free in TKR (0x1DE0.. are the fixed ability types) (checked against its server and client XML)
RENAME_SUFFIX = " (RotMG Pet)"
EXTRA_OBJECTS = ("Pet Yard Portal", "Pet Upgrader", "Pet Upgrader Backup",
                 "Yard Upgrader 1", "Yard Upgrader 2", "Yard Upgrader 3", "Yard Upgrader 4", "Yard Upgrader 5")
# Fixed types for the abilities (the server's PAbility values) and the behaviours behind them.
ABILITY_TYPES = {"Attack Close": 0x1DF0, "Attack Mid": 0x1DF1, "Attack Far": 0x1DF2, "Electric": 0x1DF3,
                 "Heal": 0x1DF4, "Magic Heal": 0x1DF5, "Savage": 0x1DF6, "Decoy": 0x1DF7, "Rising Fury": 0x1DF8}
BEHAVIOR_TYPES = {"AttackClose": 0x1DE0, "AttackMid": 0x1DE1, "AttackFar": 0x1DE2, "ElectricZap": 0x1DE3,
                  "Heal": 0x1DE4, "MagicHeal": 0x1DE5, "PetSavage": 0x1DE6, "PetDecoy": 0x1DE7, "PetRisingFury": 0x1DE8}
# Sprite sheets the pets use that TK's client doesn't have: (sheet name, NR embed file).
# RotMG's pet sheets, copied in as the client's EmbeddedAssets_romtg_<name>.png. TK has a
# chars8x8rPets1 of its own (72 characters, for its followers) but RotMG's is 192 long, so the
# pets' XML points at RotMG's as "romtgPets1": with TK's, skins past 72 had no picture and pets
# kept their placeholder (a potion in TK's lofiObj2), 2026-11-12.
SHEETS = {"romtgPets1": "EmbeddedAssets_chars8x8rPets1Embed_.png",
          "chars8x8rPets2": "EmbeddedAssets_chars8x8rPets2Embed_.png",
          "petsDivine": "EmbeddedAssets_petsDivineEmbed_.png"}

OBJECT_RE = re.compile(r"<Object\s+([^>]*)>(.*?)</Object>", re.S)


def attr(attrs: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', attrs)
    return m.group(1) if m else None


def nr_objects(name: str) -> list[tuple[str, str]]:
    text = (NR_ASSETS / name).read_text(encoding="latin-1")
    return OBJECT_RE.findall(text)


def tk_ids() -> set[str]:
    ids = set()
    for f in TK_SERVER_XML.rglob("*.xml"):
        if f.name == "romtg_pets.xml":
            continue
        ids |= set(re.findall(r'<Object\s+[^>]*\bid="([^"]*)"', f.read_text(encoding="utf-8", errors="replace")))
    client = TK_CLIENT_ASSETS / "EmbeddedData_ObjectsCXML.xml"
    if client.exists():
        ids |= set(re.findall(r'<Object\s+[^>]*\bid="([^"]*)"', client.read_text(encoding="utf-8", errors="replace")))
    return ids


PET_YARD_WORLD = """  <World id="Pet Yard">
    <Width>64</Width>
    <Height>56</Height>
    <Capacity>1</Capacity>
    <MapJM>petyard.jm</MapJM>
    <CreateInstance/>
    <DisableShooting/>
    <DisableAbilities/>
  </World>"""


def pet_yard_map() -> dict:
    """The pet yard: a walled lawn where your pets roam (PetRegion), a wooden path up from the
    entrance (Spawn), the Pet Upgrader beside it and a fountain in the middle. RotMG's own yard
    maps came with NR-CORE's resource pack, which is gone; this is a stand-in."""
    import base64
    import struct
    import zlib
    # The yard (w x h) sits in the middle of a bigger, empty map (W x H), as TK's vault does:
    # RotMG's minimap zooms out no further than the map and broke on a map smaller than its
    # 192-pixel square (2026-11-12), and the walls' outer faces now face nothing, as the vault's.
    w, h = 32, 28
    W, H = 64, 56
    ox, oy = (W - w) // 2, (H - h) // 2
    kinds = [{"ground": "Dark Grass", "objs": [{"id": "Castle Nexus Wall 1"}]},     # 0 wall
             {"ground": "Dark Grass", "regions": [{"id": "PetRegion"}]},            # 1 lawn: pets roam here
             {"ground": "Castle Nexus Wood 1"},                                    # 2 path
             {"ground": "Castle Nexus Wood 1", "regions": [{"id": "Spawn"}]},      # 3 entrance
             # The upgrader: its sprite version ("Pet Upgrader" itself is a 3D model, size 0,
             # which TK's client and Doom don't draw).
             {"ground": "Castle Nexus Wood 1", "objs": [{"id": "Pet Upgrader Backup"}]},  # 4

             {"ground": "Dark Grass", "objs": [{"id": "White Fountain"}]},        # 5 fountain
             {"ground": "Dark Grass", "objs": [{"id": "Hanami Flower"}]},          # 6 flowers
             {"ground": "Castle Nexus Wood 1", "objs": [{"id": "Portal to Nexus"}]},  # 7 the way out (TK's "Nexus Portal" is the realm portal: no dungeon, crashed the server's portal handler)
             {}]                                                                   # 8 nothing
    cells = []
    for Y in range(H):
        for X in range(W):
            x, y = X - ox, Y - oy
            if not (0 <= x < w and 0 <= y < h):
                k = 8
            elif x in (0, w - 1) or y in (0, h - 1):
                k = 0
            elif x in (15, 16) and y >= 14:
                k = 3 if y == h - 2 else 2
            elif (x, y) == (13, h - 3):
                k = 4
            elif (x, y) == (18, h - 3):
                k = 7
            elif (x, y) == (15, 9):
                k = 5
            elif (x * 7 + y * 3) % 23 == 0:
                k = 6
            else:
                k = 1
            cells.append(k)
    data = zlib.compress(struct.pack(f">{len(cells)}H", *cells))
    return {"width": W, "height": H, "data": base64.b64encode(data).decode("ascii"), "dict": kinds}


def build() -> dict:
    if not NR_ASSETS.is_dir():
        raise SystemExit(f"{NR_ASSETS} missing: clone github.com/cp-nilly/NR-27.7.X13 to reference/repos/NR-client")
    picked = list(nr_objects("EmbeddedData_PetsCXML.dat"))
    picked += [o for o in nr_objects("EmbeddedData_EquipCXML.dat") if "<Activate>CreatePet</Activate>" in o[1]]
    extras = nr_objects("EmbeddedData_StaticObjectsCXML.dat") + nr_objects("EmbeddedData_ObjectsCXML.dat")
    picked += [o for o in extras if attr(o[0], "id") in EXTRA_OBJECTS]

    taken = tk_ids()
    types: dict[int, int] = {}
    names: dict[str, str] = {}
    # Pet abilities and behaviours get fixed types: the server's PAbility values are these types.
    for attrs, body in picked:
        klass = re.search(r"<Class>([^<]*)</Class>", body)
        klass = klass.group(1) if klass else ""
        old_id = attr(attrs, "id")
        if klass == "PetAbility" and old_id in ABILITY_TYPES:
            types[int(attr(attrs, "type"), 16)] = ABILITY_TYPES[old_id]
        elif klass == "PetBehavior" and old_id in BEHAVIOR_TYPES:
            types[int(attr(attrs, "type"), 16)] = BEHAVIOR_TYPES[old_id]
    for attrs, body in picked:
        old_id = attr(attrs, "id")
        klass = re.search(r"<Class>([^<]*)</Class>", body)
        klass = klass.group(1) if klass else ""
        # A behaviour shares its name with an ability ("Heal"): behaviours get a prefix.
        if klass == "PetBehavior":
            names.setdefault(old_id + "@behavior", "Pet Behavior " + old_id)
        elif old_id not in names:
            names[old_id] = old_id + RENAME_SUFFIX if old_id in taken else old_id
    next_type = FIRST_TYPE
    for attrs, _ in picked:
        old_type, old_id = int(attr(attrs, "type"), 16), attr(attrs, "id")
        if old_type in types:
            continue
        if next_type > LAST_TYPE:
            raise SystemExit("ran out of free types")
        types[old_type] = next_type
        next_type += 1

    out = []
    for attrs, body in picked:
        old_type, old_id = int(attr(attrs, "type"), 16), attr(attrs, "id")
        new_id = names[old_id + "@behavior"] if "<Class>PetBehavior</Class>" in body else names[old_id]
        if new_id != old_id and "<DisplayId>" not in body:
            body = f"\n      <DisplayId>{old_id}</DisplayId>" + body
        body = re.sub(r"<DisplayId>\{objects\.Pet_Yard_Portal\}</DisplayId>", "<DisplayId>Pet Yard Portal</DisplayId>", body)
        body = body.replace("<File>chars8x8rPets1</File>", "<File>romtgPets1</File>")
        # The upgraders' 3D models aren't in TK's client (nor in Doom): their sprites instead.
        body = re.sub(r"\s*<Model>[^<]*</Model>", "", body)
        for tag in ("DefaultSkin", "FirstAbility"):
            body = re.sub(rf"<{tag}>([^<]*)</{tag}>", lambda m: f"<{tag}>{names.get(m.group(1), m.group(1))}</{tag}>", body)
        body = re.sub(r'skinId="(\d+)"', lambda m: f'skinId="{types.get(int(m.group(1)), int(m.group(1)))}"', body)
        out.append(f'  <Object type="0x{types[old_type]:04x}" id="{new_id}">{body}</Object>')
    out.append(PET_YARD_WORLD)
    (TK_SERVER_XML.parent / "worlds" / "petyard.jm").write_text(json.dumps(pet_yard_map()), encoding="utf-8")
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<!-- Generated by rotmg-doom/scripts/pets.py from the NR client: '
           'RotMG pet data, moved to free types. Do not edit. -->\n<Objects>\n' + "\n".join(out) + "\n</Objects>\n")
    TK_SERVER_XML.mkdir(parents=True, exist_ok=True)
    (TK_SERVER_XML / "romtg_pets.xml").write_text(xml, encoding="utf-8")
    (TK_CLIENT_ASSETS / "EmbeddedData_RomtgPetsCXML.xml").write_text(xml, encoding="utf-8")
    for sheet, png in SHEETS.items():
        shutil.copy2(NR_ASSETS / png, TK_CLIENT_ASSETS / f"EmbeddedAssets_romtg_{sheet}.png")
    table = {"types": {f"0x{k:04x}": f"0x{v:04x}" for k, v in types.items()},
             "renamed": {k: v for k, v in names.items() if k != v}}
    (REPO / "build").mkdir(exist_ok=True)
    (REPO / "build" / "romtg-pets.json").write_text(json.dumps(table, indent=1), encoding="utf-8")
    return {"objects": len(out), "renamed": len(table["renamed"]),
            "types": f"0x{FIRST_TYPE:04x}..0x{next_type - 1:04x}"}


def ensure() -> str:
    """Builds the pet data if the NR client is there; otherwise leaves empty stand-ins so the
    client still compiles (no pets then). Returns what it did, for setup.py."""
    if NR_ASSETS.is_dir():
        r = build()
        return f"RotMG pets: {r['objects']} objects ({r['renamed']} renamed) in {r['types']}"
    empty = '<?xml version="1.0" encoding="utf-8"?>\n<Objects/>\n'
    target = TK_CLIENT_ASSETS / "EmbeddedData_RomtgPetsCXML.xml"
    if not target.exists():
        target.write_text(empty, encoding="utf-8")
    for sheet in SHEETS:
        png = TK_CLIENT_ASSETS / f"EmbeddedAssets_romtg_{sheet}.png"
        if not png.exists():
            from PIL import Image
            Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(png)
    return f"no pets: {NR_ASSETS} missing (clone github.com/cp-nilly/NR-27.7.X13 to reference/repos/NR-client)"


if __name__ == "__main__":
    print(build())

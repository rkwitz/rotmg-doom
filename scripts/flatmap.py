"""The map Doom starts on: one flat, empty, round room under a high ceiling.

RotMG's realm is drawn onto it as sprites (doom-mod/zscript/romtg_handler.zs). The room's
floor, far walls and ceiling are white (RTWHITE), coloured at run time with the colour of RotMG's
ground round you (the handler's SetBackground, from the bridge's `bg`); black until then. Written as a UDMF map in a tiny WAD, which
goes into the pk3 as maps/ROMTG.wad; UZDoom builds the nodes itself when it loads it.
"""
from __future__ import annotations

import math
import struct
import zlib

MAP_NAME = "ROMTG"
HALF = 16384             # the room's radius in map units
SIDES = 128              # walls round it
CEILING = 4096           # high, so the walls far away don't feel like a room
FLOOR_FLAT = "RTWHITE"   # coloured at run time (SetSpecialColor); RotMG's tiles are drawn on top
WALL_TEXTURE = "RTWHITE"
BLACK_SIZE = 64


def textmap() -> str:
    # A round room (SIDES walls, clockwise so their fronts face in), not a square: the far walls
    # are the horizon, and a square's corners showed (Ryan, 2026-11-12). No fake contrast, so
    # every wall is lit the same.
    parts = ['namespace = "zdoom";']
    for i in range(SIDES):
        t = 2 * math.pi * i / SIDES
        parts.append(f"vertex {{ x = {HALF * math.sin(t):.3f}; y = {HALF * math.cos(t):.3f}; }}")
    for i in range(SIDES):
        parts.append(f'sidedef {{ sector = 0; texturemiddle = "{WALL_TEXTURE}"; nofakecontrast = true; }}')
        parts.append(f"linedef {{ v1 = {i}; v2 = {(i + 1) % SIDES}; sidefront = {i}; blocking = true; }}")
    # Not a sky ceiling: a plain one, so it can be coloured like the floor (a sky can't).
    parts.append(f'sector {{ heightfloor = 0; heightceiling = {CEILING}; texturefloor = "{FLOOR_FLAT}"; '
                 f'textureceiling = "{FLOOR_FLAT}"; lightlevel = 255; color_floor = 0; color_ceiling = 0; '
                 f'color_walltop = 0; color_wallbottom = 0; }}')
    # Player 1 start in the middle, facing north.
    parts.append("thing { x = 0.0; y = 0.0; angle = 90; type = 1; skill1 = true; skill2 = true; "
                 "skill3 = true; skill4 = true; skill5 = true; single = true; coop = true; dm = true; }")
    return "\n".join(parts) + "\n"


def wad() -> bytes:
    """A PWAD with the map's marker, TEXTMAP and ENDMAP lumps."""
    lumps = [(MAP_NAME, b""), ("TEXTMAP", textmap().encode("ascii")), ("ENDMAP", b"")]
    data, directory, offset = b"", b"", 12
    for name, body in lumps:
        directory += struct.pack("<ii8s", offset, len(body), name.encode("ascii"))
        data += body
        offset += len(body)
    return struct.pack("<4sii", b"PWAD", len(lumps), offset) + data + directory


def black_png(white: bool = False) -> bytes:
    """RTBLACK (or RTWHITE): a plain square texture."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    px = b"\xff\xff\xff" if white else b"\x00\x00\x00"
    rows = b"".join(b"\x00" + px * BLACK_SIZE for _ in range(BLACK_SIZE))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", BLACK_SIZE, BLACK_SIZE, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def white_png() -> bytes:
    """RTWHITE: the floor, the far walls and the ceiling, coloured by Doom at run time."""
    return black_png(white=True)


if __name__ == "__main__":
    print(textmap())

"""The link between the RotMG client and Doom, run inside the swapper (duo.py).

  RotMG client (DoomLink.as)  --127.0.0.1:2051-->  Bridge  --127.0.0.1:2052-->  Doom (RomtgBridge)

The client reports what it knows in tiles: ground tiles, objects (walls, trees, enemies, other
players, portals, loot bags...), projectiles, where you are and the weapon you hold. The bridge
keeps that world, works out what is within Doom's sight of you (SIGHT: 48 tiles, the server's
patched send radius; RotMG itself draws 15),
and tells Doom what to show, move and hide, already in Doom units. Doom tells the bridge which way
you walk, where you look and whether you shoot; the swapper adds RotMG keys pressed in Doom
(potions, nexus, ability, interact, inventory). While Doom has the controls the client does all
of it itself, at its own speed and rate of fire, so Doom's speed is RotMG's speed by construction.

Scale: one tile is as many Doom units as Doom's marine runs (583 units/s) in the time your
character walks one tile at its base speed, so moving across the realm in Doom feels like running
in Doom. Doom coordinates stop at +-32768, smaller than the realm at that scale, so Doom's world
is drawn around an origin that follows you: every RECENTER tiles everything moves back by the same
amount in one tic (`shift`), which you don't see.
"""
from __future__ import annotations

import functools
import json
import os
import math
import select
import socket
import threading
import time
import traceback
from pathlib import Path

CLIENT_PORT = 2051
DOOM_PORT = 2052
SIGHT = 48                 # tiles: everything is drawn this far, fading out from 36 (the Doom
                           # handler's SHOW_FADE_*). RotMG draws 15; the server sends 48
                           # (server-patches/0010; Ryan, 2026-11-13). Enemies' AI runs at least
                           # 48 tiles round you, so all of it moves.
FAR_SIGHT = SIGHT          # (no far ground past the fog any more, Ryan 2026-11-13; it was 32, then 58:)
                           # past that, out to here, ground you've seen as RotMG's minimap shows it, a plain
                           # square of colour per tile, for the ground and anything that stands
                           # still (walls, trees...). Nothing that moves is drawn past SIGHT.
FAR_SHADE = 0.75           # far ground a little darker than its colour
BG_SIGHT = 32              # tiles: the background (fog) colour is the ground's average out to here.
                           # Averaged out to 58 it went dark and muddy (Ryan, 2026-11-13).
BASE_PX = 8                # RotMG draws objects at their picture's own pixel size: 8 px = a tile at 100%
# Upright pictures stand this many tiles above the floor. The ground is Doom's real floor (the
# handler draws the tiles into it): it can't cover anything standing on it. (As flat sprites,
# pulled towards you as Doom pulls every sprite, the tiles cut into the feet of items, enemies
# and health bars, 2026-11-12.)
LIFT_TILES = 0.02
OWN_SHOT_SCALE = 0.55      # your own projectiles, against RotMG's size for them (see describe)
OWN_SHOT_AHEAD = 0.8       # third person: your shots drawn this many tiles further along (see shot_at)
DOOM_EFFECTS = ("Fountain",)   # RotMG particle effects Doom draws (romtg_handler.zs `fx`)
GROUND_OBJECT_TILES = 0.02   # rugs and other pictures lying on the ground: just over the tiles
RECENTER = 24              # tiles from the origin before everything moves back
DOOM_RUN_SPEED = 583.33    # units per second: the marine running (16.67 units per tic)
MIN_SCALE, MAX_SCALE = 40.0, 160.0
FIGURE = 0.8               # a size-100 RotMG character or object looks about 0.8 of a tile
EYE = 0.85                 # your eyes, as a share of a size-100 figure's height (FIGURE tiles)
SMALL_CLASSES = {"Container": 0.5,   # loot bags and chests: smaller than a character
                 # the vault's closed chests and gift chests as the open one (they were twice
                 # its size; Ryan, 2026-11-15)
                 "ClosedVaultChest": 0.5, "SpecialClosedVaultChest": 0.5,
                 "ClosedGiftChest": 0.5, "OneWayContainer": 0.5}   # potion storage: full size (Ryan)
# The vault's chests, open and closed, gift chests and special chests: bigger than loot bags
# (which share the open chest's class), Ryan 2026-11-15.
VAULT_CHESTS = (0x504, 0x505, 0x743, 0x744, 0xa011, 0xa012)
VAULT_SCALE = 0.7
SHOT_HEIGHT = 0.3          # projectiles fly at this many tiles up: hand height, under your eyes (0.68),
                           # so your own shots don't cover the view as they leave (Ryan, 2026-11-12)


_LOG_FILE = None


def log(msg: str) -> None:
    """To the console and to logs/bridge.log (started afresh each run)."""
    global _LOG_FILE
    print(f"[bridge] {msg}", flush=True)
    try:
        if _LOG_FILE is None:
            home = os.environ.get("ROMTG_HOME")   # the friend demo's folder (scripts/friend_play.py)
            path = (Path(home) if home else Path(__file__).resolve().parent.parent) / "logs" / "bridge.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            _LOG_FILE = path.open("w", encoding="utf-8")
        _LOG_FILE.write(time.strftime('%H:%M:%S') + " " + msg + "\n")
        _LOG_FILE.flush()
    except OSError:
        pass


def _locked(method):
    """Bridge methods the swapper calls: run under the bridge's lock (its own thread polls)."""
    @functools.wraps(method)
    def run(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return run


class Conn:
    """One accepted socket: lines in, a buffer of lines out."""

    def __init__(self, sock: socket.socket, name: str):
        sock.setblocking(False)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock, self.name = sock, name
        self.inbuf, self.out = b"", bytearray()
        self.alive = True

    def lines(self) -> list[str]:
        while True:
            try:
                data = self.sock.recv(1 << 16)
            except BlockingIOError:
                break
            except OSError:
                self.alive = False
                break
            if not data:
                self.alive = False
                break
            self.inbuf += data
        *done, self.inbuf = self.inbuf.split(b"\n")
        return [line.decode("utf-8", "replace").strip() for line in done]

    def send(self, line: str) -> None:
        self.out += line.encode("utf-8") + b"\n"

    def flush(self) -> None:
        while self.out and self.alive:
            try:
                n = self.sock.send(self.out)
            except BlockingIOError:
                return
            except OSError:
                self.alive = False
                return
            del self.out[:n]

    def close(self) -> None:
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass


def listen(port: int) -> socket.socket | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as error:
        log(f"port {port} is taken ({error})")
        sock.close()
        return None
    sock.listen(2)
    sock.setblocking(False)
    return sock


class Bridge:
    def __init__(self, assets_json: Path):
        self.lock = threading.RLock()   # the poll thread (start) and the swapper's calls
        self.running = False
        table = json.loads(assets_json.read_text(encoding="utf-8")) if assets_json.exists() else {}
        if not table:
            log(f"{assets_json} missing: run `setup.py build-mod`; Doom will show nothing")
        self.grounds = {int(k): v for k, v in table.get("grounds", {}).items()}
        self.objects_xml = {int(k): v for k, v in table.get("objects", {}).items()}
        # Hallucinating's stand-ins: every 8x8 character picture there is (see describe).
        self.lookalikes = sorted({v["sprite"] for v in self.objects_xml.values()
                                  if v.get("class") == "Character" and v.get("px") == 8})
        for t in VAULT_CHESTS:   # the vault's chests a bit bigger than loot bags (see VAULT_SCALE)
            if t in self.objects_xml:
                self.objects_xml[t] = {**self.objects_xml[t], "vault": True}
        self.listeners = {"client": listen(CLIENT_PORT), "doom": listen(DOOM_PORT)}
        self.conns: dict[str, Conn | None] = {"client": None, "doom": None}
        self.swap_requested = False
        self.menu_rect: tuple[int, int, int, int] | None = None   # `menu`
        self.menu_changed = False
        self.dragging = False                                 # `drag`
        self.options = False          # `options`: RotMG's options screen is up
        self.options_changed = False
        self.home_requested = False   # `home`
        self.ingame = True            # `ingame`: in a game, not RotMG's menus
        self.ingame_changed = False
        self.modal = False            # `modal`: a RotMG dialog is open...
        self.modal_rect: tuple[int, int, int, int] | None = None   # ...and where
        self.modal_changed = False
        # RotMG's key bindings for what the swapper takes in Doom (`binds`), and a count that
        # goes up with every new set, for duo.apply_binds.
        self.binds: dict[str, int] = {}
        self.binds_seq = 0
        self.controlling = False
        self.weapon = -1
        self.me = -1        # your own object id: you are Doom's camera, a sprite only in third person
        # Doom's third-person camera (C, or the camera button in RotMG's side panel; Ryan
        # 2026-11-20): your own character is then drawn too, over Doom's player (`selfid`).
        self.camera = False
        self.viewing = False
        self.quest: list | None = None   # [x, y, hp, max, name] in tiles, or None
        self.cash = "cash 0 0"
        self.tip: tuple[int, int, int, int] | None = None   # a RotMG tooltip, stage units
        self.tip_changed = False
        self.statuses_logged = 0
        self.tips_logged = 0
        self.background: tuple[int, int, int] | None = None   # the last `bg` sent
        self.background_sprite: str | None = None             # the last `bgt` sent
        self.sinking = 0                                       # the last `sink` sent
        self.reset_world()

    # ------------------------------------------------------------------ world

    def reset_world(self) -> None:
        self.map_name = ""
        self.tiles: dict[tuple[int, int], int] = {}
        # id -> [type, x, y, size]; objs also carry whether they stand still (walls, trees...)
        self.objs: dict[int, list] = {}
        self.shots: dict[int, list] = {}
        self.player: tuple[float, float] | None = None
        self.speed = 0.0
        self.scale: float | None = None
        self.view: tuple[float, float, float] | None = None   # `view` (see there)
        self.walk_speed: float | None = None                  # `spd`, tiles/s
        self.names: dict[int, tuple[str, str]] = {}           # `nm`: object id -> (RGB, name)
        self.hallucinating = False                            # `cond`: you are Hallucinating
        self.alts: dict[int, int] = {}                        # `alt`: object id -> its picture
        self.push = (0.0, 0.0)                                # `push`: the conveyor under you
        self.anims: dict[int, tuple[str, float]] = {}         # `an`: object id -> (action, Doom yaw)
        self.motion_last = self.motion_last_at = None         # motion_stats
        self.motion_gaps: list[float] = []
        self.motion_client: list[int] = []
        self.motion_since = time.monotonic()
        self.view_logged = False
        self.origin = (0, 0)
        self.shown: dict[tuple, int] = {}      # ('t', x, y) / ('o', id) / ('j', id) -> Doom id
        self.free_ids: list[int] = []
        self.next_id = 0
        self.center: tuple[int, int] | None = None

    def doom_xy(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.origin[0]) * self.scale, -(y - self.origin[1]) * self.scale

    def in_sight(self, x: float, y: float, sight: int = FAR_SIGHT) -> bool:
        if self.center is None:
            return False
        cx, cy = self.center
        return (math.floor(x) - cx) ** 2 + (math.floor(y) - cy) ** 2 <= sight * sight

    # ------------------------------------------------------------------ Doom side

    def to_doom(self, line: str) -> None:
        if self.conns["doom"]:
            self.conns["doom"].send(line)

    @_locked
    def to_client(self, line: str) -> None:
        if self.conns["client"]:
            self.conns["client"].send(line)

    def new_id(self) -> int:
        if self.free_ids:
            return self.free_ids.pop()
        self.next_id += 1
        return self.next_id - 1

    def show(self, key: tuple) -> None:
        if key in self.shown or self.scale is None:
            return
        line = self.describe(key)
        if line is None:
            return
        did = self.new_id()
        self.shown[key] = did
        self.to_doom(line.format(id=did))
        if key == ("o", self.me):
            # Doom keeps this one on its player (third person), seen from behind if it has a back.
            # (and how wide your character is drawn, Doom units: your health bar under it is as wide)
            # (how wide the figure in your picture is, and how tall the picture: Doom units; your
            # health bar under you is as wide as the figure, below it as RotMG puts it)
            me_look = self.look(self.me) or {}
            me_sc = self.figure(me_look, self.objs[self.me][3])[0] if me_look and self.scale else 0
            me_width = me_sc * me_look.get("px", 8) if me_look else 0
            me_height = me_sc * me_look.get("py", me_look.get("px", 8)) if me_look else 0
            self.to_doom(f"selfid {did} {1 if me_look.get('back') else 0} {me_width:.1f} {me_height:.1f}")
        if key[0] == "o" and self.objs[key[1]][4] and not self.is_wall(key[1]):
            self.to_doom(f"hp {did} {self.objs[key[1]][4][0]} {self.objs[key[1]][4][1]}")
        if key[0] == "o" and key[1] in self.anims and not self.hallucinating and \
                (self.look(key[1]) or {}).get("anim"):
            self.to_doom(f"an {did} {self.anims[key[1]][0]} {self.anims[key[1]][1]:.0f} {self.anims[key[1]][2]}")
        if key[0] == "o" and key[1] in self.names:
            self.to_doom(f"nm {did} {self.names[key[1]][0]} {self.names[key[1]][1]}")
        if key[0] == "j":
            shot = self.shots.get(key[1])
            if shot and len(shot) > 5 and shot[5]:
                # Its particle trail: RGB, lifetime ms, intensity % (-1: always), Doom draws it.
                rgb, ms, intensity = shot[5]
                self.to_doom(f"tr {did} {rgb} {ms} {intensity} {1 if shot[4] else 0}")
            if shot and len(shot) > 6 and shot[6] is not None:
                # Pointed the way it flies: its direction (Doom degrees; RotMG's y runs down),
                # which way its picture points (AngleCorrection x 45 degrees), its spin.
                info = self.objects_xml.get(shot[0], {})
                self.to_doom(f"sa {did} {-math.degrees(shot[6]):.1f} {info.get('ac', 1.0) * 45:.1f} {info.get('spin', 0):.1f}")
        if key[0] == "o":
            info = self.objects_xml.get(self.objs[key[1]][0], {})
            if info.get("effect") in DOOM_EFFECTS:
                # RotMG's particles on it (a fountain's water): Doom makes them.
                self.to_doom(f"fx {did} {info['effect'].lower()} {info.get('effect_rgb', 0x4165D5):06x}")

    def hide(self, key: tuple) -> None:
        did = self.shown.pop(key, None)
        if did is not None:
            self.free_ids.append(did)
            self.to_doom(f"d {did}")

    def figure(self, info: dict, size: float) -> tuple[float, float]:
        """Scale and lift for an upright picture of SIZE percent: about FIGURE of a tile wide at
        100, standing on the floor (pictures hang from their centre)."""
        sc = self.scale / BASE_PX * size / 100 * FIGURE * (VAULT_SCALE if info.get("vault") else SMALL_CLASSES.get(info.get("class"), 1.0))
        return sc, info.get("py", info["px"]) * sc / 2 + max(1.0, LIFT_TILES * self.scale)

    def describe(self, key: tuple) -> str | None:
        """The Doom line that draws `key`, with {id} left to fill."""
        s = self.scale
        if key[0] == "t":
            pic = self.grounds.get(self.tiles.get((key[1], key[2]), -1))
            if not pic:
                return None
            x, y = self.doom_xy(key[1] + 0.5, key[2] + 0.5)
            line = f"f {{id}} {x:.2f} {y:.2f} {pic['sprite']} {s / pic['px']:.4f}"
            if pic.get("animate"):
                # moving ground: how it moves, after the tile itself
                line += "\n" + f"fa {{id}} {pic['animate'].lower()} {pic['dx']:.3f} {pic['dy']:.3f}"
            return line
        if key[0] == "ft":
            pic = self.grounds.get(self.tiles.get((key[1], key[2]), -1))
            if not pic or "rgb" not in pic:
                return None
            x, y = self.doom_xy(key[1] + 0.5, key[2] + 0.5)
            rgb = pic["rgb"]
            rgb = (int((rgb >> 16 & 255) * FAR_SHADE) << 16) | (int((rgb >> 8 & 255) * FAR_SHADE) << 8) | int((rgb & 255) * FAR_SHADE)
            return f"fc {{id}} {x:.2f} {y:.2f} {rgb:06x} {s:.2f}"
        if key[0] == "fo":
            obj = self.objs.get(key[1])
            info = self.objects_xml.get(obj[0]) if obj else None
            if not info or "rgb" not in info:
                return None
            x, y = self.doom_xy(math.floor(obj[1]) + 0.5, math.floor(obj[2]) + 0.5)
            return f"fc {{id}} {x:.2f} {y:.2f} {info['rgb']:06x} {s:.2f} 0.22"
        if key[0] == "j":
            shot = self.shots.get(key[1])
            info = self.objects_xml.get(shot[0]) if shot else None
            if not info:
                return None
            info = self.variant(info, key[1])
            x, y = self.doom_xy(*self.shot_at(shot))
            # RotMG's own size for it (projectiles are drawn like characters, by their Size), but
            # yours a good deal smaller: they start right at your eye, where RotMG's top-down view
            # never puts them, and covered the view (Ryan, 2026-11-13).
            sc = s / BASE_PX * max(shot[3], 20) / 100 * FIGURE * (OWN_SHOT_SCALE if len(shot) > 4 and shot[4] else 1.0)
            return f"b {{id}} {x:.2f} {y:.2f} {s * SHOT_HEIGHT:.2f} {info['sprite']} {sc:.4f}"
        obj = self.objs.get(key[1])
        info = self.look(key[1])
        if not info:
            return None
        x, y = self.doom_xy(obj[1], obj[2])
        if info["wall"]:
            # Walls sit on whole tiles: centred on the tile they stand in.
            x, y = self.doom_xy(math.floor(obj[1]) + 0.5, math.floor(obj[2]) + 0.5)
            return f"w {{id}} {x:.2f} {y:.2f} {s:.2f} {info['sprite']} {info.get('top', '-')} {s / info['px']:.4f}"
        if info.get("ground"):
            return f"f {{id}} {x:.2f} {y:.2f} {info['sprite']} {s / BASE_PX * obj[3] / 100:.4f} {max(1.0, GROUND_OBJECT_TILES * s):.2f}"
        if info.get("model"):
            # A 3D object in RotMG (fountains, pillars, monuments, tables...): a box its size,
            # its picture on every side and on top.
            width, height = (v * s * obj[3] / 100 for v in info["model"])
            return (f"w {{id}} {x:.2f} {y:.2f} {width:.2f} {info['sprite']} {info['sprite']} "
                    f"{width / info['px']:.4f} {height:.2f}")
        sc, z = self.figure(info, obj[3])
        sprite = info["sprite"]
        if self.hallucinating and self.lookalikes:
            # Hallucinating: RotMG draws every object as a random 8x8 character picture
            # (GameObject.getHallucinatingTexture), the same one for it until it goes.
            sprite = self.lookalikes[(key[1] * 2654435761) % len(self.lookalikes)]
            sc = self.figure({**info, "px": 8, "py": 8}, obj[3])[0]
            z = 8 * sc / 2 + max(1.0, LIFT_TILES * s)
        return f"b {{id}} {x:.2f} {y:.2f} {z:.2f} {sprite} {sc:.4f}"

    def send_push(self) -> None:
        if self.scale:
            self.to_doom(f"push {self.push[0] * self.scale:.2f} {-self.push[1] * self.scale:.2f}")

    def look(self, oid: int) -> dict | None:
        """Object OID's picture as it shows now: its own, or the AltTexture RotMG switched it
        to (`alt`), with the rest of its object (size, class...)."""
        obj = self.objs.get(oid)
        info = self.objects_xml.get(obj[0]) if obj else None
        if not info:
            return None
        alt = info.get("alt", {}).get(str(self.alts.get(oid, 0)))
        if alt:
            info = {**info, "sprite": alt["sprite"], "px": alt["px"], "py": alt["py"], "anim": alt.get("anim", False)}
        else:
            info = self.variant(info, oid)
        return info

    @staticmethod
    def variant(info: dict, oid: int) -> dict:
        """One of a RandomTexture object's pictures (assets.py `random`), the same one for the
        same object every time it's shown. RotMG picks at random per object; by id, a weapon's
        shots of one volley (ids one apart) get different pictures, as they do in RotMG."""
        variants = info.get("random")
        if not variants:
            return info
        pick = variants[oid % len(variants)]
        return {**info, "sprite": pick["sprite"], "px": pick["px"], "py": pick["py"]}

    def health(self, oid: int, hp: int, most: int) -> None:
        """An enemy's health, for its bar at its feet in Doom."""
        obj = self.objs.get(oid)
        if obj is None:
            return
        obj[4] = (hp, most)
        if ("o", oid) in self.shown and not self.is_wall(oid):
            self.to_doom(f"hp {self.shown[('o', oid)]} {hp} {most}")

    def is_wall(self, oid: int) -> bool:
        """A wall (breakable ones have health too): no health bar on it, only the damage
        numbers when you hit it."""
        obj = self.objs.get(oid)
        info = self.objects_xml.get(obj[0]) if obj else None
        return bool(info and info.get("wall"))

    def shot_at(self, shot: list) -> tuple[float, float]:
        """Where a shot is drawn (tiles). Yours, in third person, a little further along its way:
        they start where RotMG has you, a step behind where Doom draws you while you walk, so
        they flew out from inside your own picture (Ryan, 2026-11-20)."""
        if self.camera and len(shot) > 6 and shot[4] and shot[6] is not None:
            return (shot[1] + math.cos(shot[6]) * OWN_SHOT_AHEAD, shot[2] + math.sin(shot[6]) * OWN_SHOT_AHEAD)
        return shot[1], shot[2]

    def lift(self, key: tuple) -> float:
        """The height a shown upright thing stands at, for `mv`."""
        if key[0] == "j":
            return self.scale * SHOT_HEIGHT
        obj = self.objs.get(key[1])
        info = self.objects_xml.get(obj[0]) if obj else None
        return self.figure(info, obj[3])[1] if info else 0.0

    def everything_in_sight(self) -> set[tuple]:
        if self.center is None:
            return set()
        cx, cy = self.center
        keys = set()
        for dx in range(-FAR_SIGHT, FAR_SIGHT + 1):
            for dy in range(-FAR_SIGHT, FAR_SIGHT + 1):
                d = dx * dx + dy * dy
                if d <= FAR_SIGHT * FAR_SIGHT and (cx + dx, cy + dy) in self.tiles:
                    keys.add(("t" if d <= SIGHT * SIGHT else "ft", cx + dx, cy + dy))
        for oid, obj in self.objs.items():
            if oid == self.me:
                if self.camera:
                    keys.add(("o", oid))   # always: Doom keeps it on you (its place here is old)
                continue
            if self.in_sight(obj[1], obj[2], SIGHT):
                keys.add(("o", oid))
            elif self.in_sight(obj[1], obj[2]) and self.objects_xml.get(obj[0], {}).get("static"):
                keys.add(("fo", oid))
        for sid, shot in self.shots.items():
            if self.in_sight(shot[1], shot[2], SIGHT):
                keys.add(("j", sid))
        return keys

    def refresh(self) -> None:
        """You moved to another tile: show what came into sight, hide what left it."""
        want = self.everything_in_sight()
        for key in [k for k in self.shown if k not in want]:
            self.hide(key)
        for key in want:
            self.show(key)
        self.send_background()

    def send_background(self, force: bool = False) -> None:
        """`bg RGB`: the colour of RotMG's ground round you (out to FAR_SIGHT), on average and
        shaded as the far ground is, for Doom's floor and sky past it. Sent when it changes."""
        if self.center is None:
            return
        cx, cy = self.center
        r = g = b = n = 0
        counts: dict[str, int] = {}
        # Every tile, weighted down to nothing at BG_SIGHT: walking one tile only nudges the
        # colour (every other tile, all equal, jumped as tiles came and went at the edge,
        # Ryan 2026-11-13).
        for dx in range(-BG_SIGHT, BG_SIGHT + 1):
            for dy in range(-BG_SIGHT, BG_SIGHT + 1):
                d2 = dx * dx + dy * dy
                if d2 >= BG_SIGHT * BG_SIGHT:
                    continue
                pic = self.grounds.get(self.tiles.get((cx + dx, cy + dy), -1))
                if not pic or "rgb" not in pic:
                    continue
                rgb = pic["rgb"]
                counts[pic["sprite"]] = counts.get(pic["sprite"], 0) + 1
                wt = 1 - math.sqrt(d2) / BG_SIGHT
                r += (rgb >> 16 & 255) * wt
                g += (rgb >> 8 & 255) * wt
                b += (rgb & 255) * wt
                n += wt
        if n == 0:
            return
        # The most common ground round you: Doom shows a faint copy of it past the far ground.
        common = max(counts, key=counts.get)
        if force or common != self.background_sprite:
            self.background_sprite = common
            self.to_doom(f"bgt {common}")
        # The background (the fog, the floor past it and the sky): the average, which changes
        # smoothly as you walk. (The most common ground's own colour jumped when another ground
        # took over, Ryan 2026-11-13.)
        bg = tuple(int(c / n * FAR_SHADE) for c in (r, g, b))
        if not force and self.background is not None and max(abs(i - j) for i, j in zip(bg, self.background)) < 1:
            return
        self.background = bg
        self.to_doom("bg %02x%02x%02x" % bg)

    def place(self, key: tuple, x: float, y: float) -> None:
        """Something that moves moved: shown in Doom if in RotMG's sight, moved if already shown."""
        if not self.in_sight(x, y, SIGHT):
            self.hide(key)
        elif key in self.shown:
            dx, dy = self.doom_xy(x, y)
            self.to_doom(f"mv {self.shown[key]} {dx:.2f} {dy:.2f} {self.lift(key):.2f}")
        else:
            self.show(key)

    def resend_all(self) -> None:
        """Doom (re)connected: it gets the whole picture again."""
        self.shown.clear()
        self.free_ids.clear()
        self.next_id = 0
        self.to_doom("clear")
        self.to_doom(f"ctl {1 if self.controlling else 0}")
        self.to_doom(f"cam {1 if self.camera else 0}")
        self.refresh()
        if self.player and self.scale:
            self.to_doom("p %.2f %.2f" % self.doom_xy(*self.player))
            self.send_scale()
        self.send_weapon()
        self.send_quest()
        self.to_doom(self.cash)
        self.send_background(force=True)

    def send_scale(self) -> None:
        """Doom's eye height follows the tile size: your eyes near the top of a RotMG figure."""
        self.to_doom(f"scale {self.scale:.2f} {self.scale * FIGURE * EYE:.2f}")
        if self.walk_speed is not None:
            self.to_doom(f"spd {self.walk_speed * self.scale:.2f}")

    def send_quest(self) -> None:
        if self.quest is None or self.scale is None:
            self.to_doom("quest -")
            return
        x, y = self.doom_xy(self.quest[0], self.quest[1])
        self.to_doom(f"quest {x:.2f} {y:.2f} {self.quest[2]} {self.quest[3]} {self.quest[4]}")

    def send_weapon(self) -> None:
        info = self.objects_xml.get(self.weapon)
        self.to_doom(f"weapon {info['sprite']} {info['px']} {info.get('slot', 0)} {1 if info.get('flip') else 0} "
                     f"{info.get('hand', 'A')}" if info else "weapon - 8 0 0 A")

    # ------------------------------------------------------------------ client side

    def from_client(self, line: str) -> None:
        part = line.split()
        if not part:
            return
        kind = part[0]
        try:
            if kind == "p" and len(part) >= 4:
                self.moved(float(part[1]), float(part[2]), float(part[3]),
                           int(part[4]) if len(part) >= 5 else None)
            elif kind == "u" and len(part) >= 4:
                obj = self.objs.get(int(part[1]))
                if obj is not None:
                    obj[1], obj[2] = float(part[2]), float(part[3])
                    self.place(("o", int(part[1])), obj[1], obj[2])
                    if len(part) >= 6:
                        self.health(int(part[1]), int(part[4]), int(part[5]))
            elif kind == "uj" and len(part) >= 4:
                shot = self.shots.get(int(part[1]))
                if shot is not None:
                    shot[1], shot[2] = float(part[2]), float(part[3])
                    self.place(("j", int(part[1])), *self.shot_at(shot))
            elif kind == "t" and len(part) >= 4:
                x, y, t = int(part[1]), int(part[2]), int(part[3])
                old = self.tiles.get((x, y))
                self.tiles[(x, y)] = t
                if self.in_sight(x + 0.5, y + 0.5):
                    key = ("t" if self.in_sight(x + 0.5, y + 0.5, SIGHT) else "ft", x, y)
                    if old is not None:
                        self.hide(key)
                    self.show(key)
            elif kind == "quest":
                if len(part) >= 7 and part[1] != "-1":
                    self.quest = [float(part[2]), float(part[3]), int(part[4]), int(part[5]),
                                  " ".join(part[6:])]
                else:
                    self.quest = None
                self.send_quest()
            elif kind == "cash" and len(part) >= 3:
                self.cash = f"cash {int(part[1])} {int(part[2])}"
                self.to_doom(self.cash)
            elif kind == "st" and len(part) >= 3:
                if self.statuses_logged < 5:
                    self.statuses_logged += 1
                    log(f"status text over you: {' '.join(part[2:])}")
            elif kind == "atk" and len(part) >= 2:
                self.to_doom(line)   # your weapon went off: Doom animates it in your hand
            elif kind == "log":
                log("client: " + line[4:])
            elif kind == "myhp" and len(part) >= 3:
                # Your health (third person): the bar under your own character in Doom.
                self.health(self.me, int(part[1]), int(part[2]))
            elif kind == "dmg" and len(part) >= 4:
                # A status text over something else (the damage you do, mostly): over it in Doom.
                key = ("o", int(part[1]))
                if key in self.shown:
                    self.to_doom(f"ds {self.shown[key]} {part[2]} {' '.join(part[3:])}")
            elif kind == "view" and len(part) >= 4:
                # RotMG's circle of ground round you (its middle, radius; 800x600 units), for
                # the swapper's corner view.
                self.view = tuple(float(v) for v in part[1:4])
                if not self.view_logged:
                    self.view_logged = True
                    log(f"RotMG's view circle: middle {self.view[:2]}, radius {self.view[2]} (800x600 units)")
            elif kind == "tip":
                self.tip = tuple(int(v) for v in part[1:5]) if len(part) >= 5 else None
                if self.tips_logged < 5 and self.tip and self.viewing:
                    self.tips_logged += 1
                    log(f"a RotMG tooltip at {self.tip} (x, y, w, h in RotMG's 800x600)")
                self.tip_changed = True
            elif kind == "me" and len(part) >= 2:
                self.me = int(part[1])
                # On a new map your object can come before this line and be shown as anyone
                # else's (standing where you arrived, Ryan 2026-11-21): shown again, as you.
                self.hide(("o", self.me))
                if self.camera and self.me in self.objs:
                    self.show(("o", self.me))
                self.to_client(f"cam {1 if self.camera else 0}")
            elif kind == "o" and len(part) >= 5:
                oid = int(part[1])
                size = float(part[5]) if len(part) >= 6 else 100.0
                self.objs[oid] = [int(part[2]), float(part[3]), float(part[4]), size, None]
                if oid == self.me:
                    # You: kept (your picture, for third person), drawn only then.
                    self.hide(("o", oid))
                    if self.camera:
                        self.show(("o", oid))
                    return
                self.hide(("o", oid))
                self.hide(("fo", oid))
                if self.in_sight(float(part[3]), float(part[4]), SIGHT):
                    self.show(("o", oid))
                elif self.in_sight(float(part[3]), float(part[4])) and self.objects_xml.get(int(part[2]), {}).get("static"):
                    self.show(("fo", oid))
                if len(part) >= 9:
                    self.health(oid, int(part[7]), int(part[8]))
            elif kind == "j" and len(part) >= 6:
                sid = int(part[1])
                rest = part[7:]
                angle = None
                if rest and rest[0].startswith("a"):
                    angle = float(rest[0][1:])   # its flight direction, RotMG radians
                    rest = rest[1:]
                self.shots[sid] = [int(part[2]), float(part[3]), float(part[4]), float(part[5]),
                                   len(part) >= 7 and part[6] == "1",   # your own shot
                                   tuple(rest[0:3]) if len(rest) >= 3 else None,   # its particle trail
                                   angle]
                self.hide(("j", sid))
                if self.in_sight(float(part[3]), float(part[4]), SIGHT):
                    self.show(("j", sid))
            elif kind in ("r", "rj") and len(part) >= 2:
                oid = int(part[1])
                (self.objs if kind == "r" else self.shots).pop(oid, None)
                self.hide(("o" if kind == "r" else "j", oid))
                if kind == "r":
                    self.hide(("fo", oid))
            elif kind == "w" and len(part) >= 2:
                self.weapon = int(part[1])
                self.send_weapon()
            elif kind == "map":
                log(f"map {part[1] if len(part) > 1 else '?'}")
                self.reset_world()
                self.map_name = part[1] if len(part) > 1 else "?"
                self.quest = None
                self.to_doom("clear")
                self.send_quest()
            elif kind == "swap":
                self.swap_requested = True
            elif kind == "camtoggle":
                self.toggle_camera()   # the camera button in RotMG's side panel
            elif kind == "spd" and len(part) >= 2:
                # Your walking speed now, for Doom to walk you at: tiles/s to Doom units/s
                # (sent again with the scale, see send_scale).
                self.walk_speed = float(part[1])
                if self.scale:
                    self.to_doom(f"spd {self.walk_speed * self.scale:.2f}")
            elif kind == "push" and len(part) >= 3:
                # The conveyor under you: tiles/s to Doom units/s (RotMG's y runs down). Before
                # the map's scale is known, kept till it is (see `scale`).
                self.push = (float(part[1]), float(part[2]))
                self.send_push()
            elif kind == "grid" and len(part) >= 5 and self.scale:
                # The squares round you, for Doom's walking: the corner of square CX, CY in Doom.
                dx, dy = self.doom_xy(int(part[1]), int(part[2]))
                self.to_doom(f"grid {dx:.2f} {dy:.2f} {int(part[3])} {part[4]}")
            elif kind == "efx" and len(part) >= 9 and self.scale:
                # An effect the server shows: Doom draws it. The target's place (you, or an
                # object), both points in Doom units, and the radius-ish numbers scaled too.
                target = int(part[2])
                where = self.player if target == self.me else (
                    (self.objs[target][1], self.objs[target][2]) if target in self.objs else None)
                x1, y1, x2, y2 = (float(v) for v in part[3:7])
                if where is None:
                    where = (x1, y1)
                if self.in_sight(where[0], where[1], SIGHT) or self.in_sight(x1, y1, SIGHT):
                    tx, ty = self.doom_xy(*where)
                    ax, ay = self.doom_xy(x1, y1)
                    bx, by = self.doom_xy(x2, y2)
                    s = self.scale
                    self.to_doom(f"ef {part[1]} {tx:.1f} {ty:.1f} {ax:.1f} {ay:.1f} {bx:.1f} {by:.1f} "
                                 f"{x1 * s:.1f} {x2 * s:.1f} {part[7]} {part[8]} {1 if target == self.me else 0}")
            elif kind == "binds":
                binds = {}
                for pair in part[1:]:
                    name, _, code = pair.partition("=")
                    if code.isdigit():
                        binds[name] = int(code)
                if binds != self.binds:
                    self.binds = binds
                    self.binds_seq += 1
            elif kind == "throwaim" and len(part) >= 2:
                # Space held with a thrown ability: Doom draws its arc and landing spot
                # (`throwaim 1 MAX_TILES RADIUS_TILES`, `throwaim 0`), in Doom units.
                if part[1] == "1" and len(part) >= 4 and self.scale:
                    self.to_doom(f"throwaim 1 {float(part[2]) * self.scale:.1f} {float(part[3]) * self.scale:.1f}")
                else:
                    self.to_doom("throwaim 0")
            elif kind == "cond" and len(part) >= 3:
                # Your status effects: Doom draws blind, drunk, paused and swaps keys when
                # confused; hallucinating, every creature looks like some other one (here).
                self.to_doom(f"cond {part[1]} {part[2]}")
                hallucinating = bool(int(part[1]) & (1 << 8))
                if hallucinating != self.hallucinating:
                    self.hallucinating = hallucinating
                    for key in [k for k in self.shown if k[0] == "o"]:
                        self.hide(key)
                        self.show(key)
            elif kind == "alt" and len(part) >= 3:
                # It shows another of its pictures (a boss changing its look): Doom redraws it.
                oid = int(part[1])
                n = int(part[2])
                if self.alts.get(oid, 0) != n:
                    self.alts[oid] = n
                    if ("o", oid) in self.shown:
                        self.hide(("o", oid))
                        self.show(("o", oid))
            elif kind == "an" and len(part) >= 4:
                # A character's animation: Doom picks its frames and which way it faces.
                oid = int(part[1])
                obj = self.objs.get(oid)
                if obj is not None:
                    # (action, Doom yaw, ms for its two frames as RotMG plays them: 0 = Doom's default)
                    obj_anim = (part[2], -math.degrees(float(part[3])), int(part[4]) if len(part) >= 5 and part[4].isdigit() else 0)
                    self.anims[oid] = obj_anim
                    if ("o", oid) in self.shown and (self.look(oid) or {}).get("anim") and not self.hallucinating:
                        self.to_doom(f"an {self.shown[('o', oid)]} {obj_anim[0]} {obj_anim[1]:.0f} {obj_anim[2]}")
            elif kind == "heal" and len(part) >= 3:
                # A character under Healing (sparkles round it): you, or a shown object.
                oid = int(part[1])
                on = part[2] == "1"
                if oid == self.me:
                    self.to_doom(f"heal -1 {1 if on else 0}")
                elif ("o", oid) in self.shown:
                    self.to_doom(f"heal {self.shown[('o', oid)]} {1 if on else 0}")
            elif kind == "nm" and len(part) >= 4:
                # Another player's name tag (RGB, name): Doom draws it over them.
                oid = int(part[1])
                self.names[oid] = (part[2], part[3])
                if ("o", oid) in self.shown:
                    self.to_doom(f"nm {self.shown[('o', oid)]} {part[2]} {part[3]}")
            elif kind == "burst" and len(part) >= 9 and self.scale:
                # Particles bursting (a hit, a death): Doom draws them, in Doom units.
                x, y = float(part[1]), float(part[2])
                if self.in_sight(x, y, SIGHT):
                    dx, dy = self.doom_xy(x, y)
                    s = self.scale
                    self.to_doom(f"bu {dx:.2f} {dy:.2f} {s * SHOT_HEIGHT:.2f} {part[3]} {int(part[4]) * s / 100:.2f} "
                                 f"{float(part[5]) * s:.2f} {-float(part[6]) * s:.2f} {float(part[7]) * s:.2f} {part[8]}")
            elif kind == "drag" and len(part) >= 2:
                # An item dragged out of RotMG's side panel (or let go): the swapper shows RotMG's
                # ground over Doom meanwhile, to drop it on.
                if (part[1] == "1") != self.dragging:
                    self.dragging = part[1] == "1"
                    self.menu_changed = True
            elif kind == "menu" and len(part) >= 2:
                # A RotMG menu (teleport...) open at X Y W H in 800x600 units, or none.
                rect = tuple(int(v) for v in part[1:5]) if len(part) >= 5 else None
                if rect != self.menu_rect:
                    self.menu_rect = rect
                    self.menu_changed = True
            elif kind == "options" and len(part) >= 2:
                # RotMG's options screen up or down (the swapper shows RotMG for it).
                self.options = part[1] == "1"
                self.options_changed = True
            elif kind == "home":
                self.home_requested = True   # "back to home": out of Doom for RotMG's menus
            elif kind == "ingame" and len(part) >= 2:
                # In a game, or out in RotMG's menus (the swapper brings RotMG up then).
                ingame = part[1] == "1"
                if ingame != self.ingame:
                    self.ingame = ingame
                    self.ingame_changed = True
            elif kind == "modal" and len(part) >= 2:
                # A dialog or popup is open in RotMG's play area (the swapper shows it), and
                # where (800x600 units).
                was = self.modal
                self.modal = part[1] == "1"
                rect = tuple(int(v) for v in part[2:6]) if self.modal and len(part) >= 6 else None
                if self.modal != was or rect != self.modal_rect:
                    self.modal_changed = True
                if self.modal != was:
                    # Doom dims its view behind it, as RotMG grays the screen (Ryan, 2026-11-18).
                    self.to_doom(f"modal {1 if self.modal else 0}")
                self.modal_rect = rect
        except (ValueError, IndexError):
            pass

    def moved(self, x: float, y: float, speed: float, at: int | None = None) -> None:
        self.player = (x, y)
        if self.scale is None:
            # The map's size in Doom, from the speeds: see the module docstring.
            self.speed = speed
            self.scale = max(MIN_SCALE, min(MAX_SCALE, DOOM_RUN_SPEED / max(speed, 0.1)))
            self.origin = (math.floor(x), math.floor(y))
            log(f"{self.map_name}: walking {speed:.2f} tiles/s, so a tile is {self.scale:.1f} Doom units")
            self.send_scale()
            self.send_push()
        ox, oy = self.origin
        if abs(x - ox) > RECENTER or abs(y - oy) > RECENTER:
            new = (math.floor(x), math.floor(y))
            self.to_doom(f"shift {(ox - new[0]) * self.scale:.2f} {-(oy - new[1]) * self.scale:.2f}")
            log(f"re-centred Doom's origin at tile {new} (you at {x:.1f}, {y:.1f})")
            self.origin = new
            self.send_quest()
        center = (math.floor(x), math.floor(y))
        if center != self.center:
            self.center = center
            self.refresh()
            # Standing in water (a Sink ground): Doom lowers your eyes, as RotMG sinks you in.
            pic = self.grounds.get(self.tiles.get(center, -1)) or {}
            sink = 1 if pic.get("sink") else 0
            if sink != self.sinking:
                self.sinking = sink
                self.to_doom(f"sink {sink}")
        # With the client's time: Doom replays your path at an even pace (see the handler's
        # `p`); RotMG draws at 60 frames a second and Doom ticks at 35, so taking the latest
        # place each tic moved you one frame's step, then two: the stutter (2026-11-15).
        self.to_doom("p %.2f %.2f" % self.doom_xy(x, y) + (f" {at}" if at is not None else ""))
        self.motion_stats(at)

    # ------------------------------------------------------------------ both

    def motion_stats(self, at: int | None) -> None:
        """Every 5 s while you move: how evenly your positions came from the client (arrival
        gaps here, and gaps on the client's own clock), to measure stutter."""
        now = time.monotonic()
        if self.motion_last is not None and now - self.motion_last < 0.5:
            self.motion_gaps.append((now - self.motion_last) * 1000)
            if at is not None and self.motion_last_at is not None:
                self.motion_client.append(at - self.motion_last_at)
        self.motion_last, self.motion_last_at = now, at
        if now - self.motion_since >= 5 and self.motion_gaps:
            g = sorted(self.motion_gaps)
            c = sorted(self.motion_client) or [0]
            log(f"motion: {len(g)} positions in {now - self.motion_since:.1f}s; gaps here ms "
                f"median {g[len(g) // 2]:.0f} max {g[-1]:.0f} (>40: {sum(1 for v in g if v > 40)}); "
                f"on the client's clock median {c[len(c) // 2]} max {c[-1]}")
            self.motion_gaps, self.motion_client = [], []
            self.motion_since = now
        elif not self.motion_gaps and now - self.motion_since >= 5:
            self.motion_since = now

    @_locked
    def set_control(self, doom: bool) -> None:
        """Doom has the controls (walks, shoots, presses keys for your character) or RotMG does."""
        self.controlling = doom
        self.to_client(f"ctl {1 if doom else 0}")
        self.to_doom(f"ctl {1 if doom else 0}")   # Doom walks you itself only while it has them

    @_locked
    def set_view(self, doom: bool) -> None:
        """Doom is on screen: RotMG hides its own HUD over the play area and Doom draws it."""
        self.viewing = doom
        self.to_client(f"view {1 if doom else 0}")

    @_locked
    def toggle_camera(self) -> None:
        """Doom's camera: first person (your eyes) <-> third person (over your character, which
        is drawn then)."""
        self.camera = not self.camera
        self.to_doom(f"cam {1 if self.camera else 0}")
        self.to_client(f"cam {1 if self.camera else 0}")   # your status texts go over you then
        if self.camera and self.me in self.objs:
            self.show(("o", self.me))
        else:
            self.hide(("o", self.me))
        log(f"camera: {'third' if self.camera else 'first'} person")

    @_locked
    def set_panel(self, on: bool) -> None:
        """Tab out of Doom: Doom greys out and says how to come back."""
        self.to_doom(f"panel {1 if on else 0}")

    @_locked
    def act(self, name: str) -> None:
        """A RotMG key pressed in Doom (see duo.py ACTIONS)."""
        if name == "camera":
            self.toggle_camera()   # the camera key (duo.CAMERA_VKS): Doom's, not RotMG's
            return
        if self.controlling:
            self.to_client(f"act {name}")

    def from_doom(self, line: str) -> None:
        part = line.split()
        if not part:
            return
        try:
            if part[0] == "m" and len(part) >= 3 and self.controlling:
                # RotMG's y points down.
                self.to_client(f"m {float(part[1]):.4f} {-float(part[2]):.4f}")
            elif part[0] == "goto" and len(part) >= 3 and self.controlling and self.scale:
                # Where Doom has walked you, Doom units back to RotMG's tiles.
                x = float(part[1]) / self.scale + self.origin[0]
                y = -float(part[2]) / self.scale + self.origin[1]
                self.to_client(f"goto {x:.4f} {y:.4f}")
            elif part[0] == "fire" and len(part) >= 3 and self.controlling:
                # Doom's angle is degrees anticlockwise with y up; RotMG's radians with y down.
                self.to_client(f"fire {1 if part[1] == '1' else 0} {-math.radians(float(part[2])):.4f}")
            elif part[0] == "throw" and len(part) >= 2 and self.scale:
                # How far to throw the aimed ability, Doom units to tiles.
                self.to_client(f"throw {float(part[1]) / self.scale:.2f}")
            elif part[0] == "hello":
                self.resend_all()
        except ValueError:
            pass

    def start(self) -> None:
        """Poll on a thread of its own, waking as soon as either side sends something: your
        moves reach RotMG, and RotMG's reports reach Doom, at once, not on the swapper's next
        pass (every 10 ms or more; part of movement feeling slow, 2026-11-15)."""
        self.lock = getattr(self, "lock", None) or threading.RLock()
        self.running = True
        self.thread = threading.Thread(target=self._run, name="bridge", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        failures = 0
        while self.running:
            socks = [l for l in self.listeners.values() if l is not None]
            socks += [c.sock for c in self.conns.values() if c is not None and c.alive]
            try:
                if socks:
                    select.select(socks, [], [], 0.004)
                else:
                    time.sleep(0.004)
            except (OSError, ValueError):
                time.sleep(0.004)
            try:
                with self.lock:
                    self.poll()
            except Exception:
                failures += 1
                if failures <= 3 or failures % 500 == 0:
                    log("error (the bridge keeps going): " + traceback.format_exc())

    def poll(self) -> None:
        for name, listener in self.listeners.items():
            if listener is None:
                continue
            try:
                sock, _ = listener.accept()
            except (BlockingIOError, OSError):
                continue
            if self.conns[name]:
                self.conns[name].close()
            self.conns[name] = Conn(sock, name)
            log(f"{'RotMG client' if name == 'client' else 'Doom'} connected")
            if name == "client":
                self.reset_world()
                self.to_doom("clear")
                self.set_control(self.controlling)
                self.set_view(self.viewing)
        for name, conn in self.conns.items():
            if conn is None:
                continue
            for line in conn.lines():
                (self.from_client if name == "client" else self.from_doom)(line)
            if not conn.alive:
                log(f"{'RotMG client' if name == 'client' else 'Doom'} disconnected")
                conn.close()
                self.conns[name] = None
                if name == "client":
                    self.reset_world()
                    self.to_doom("clear")
        for conn in self.conns.values():
            if conn:
                conn.flush()

    def close(self) -> None:
        self.running = False
        thread = getattr(self, "thread", None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(0.5)   # stopped before the sockets go (and before Python exits)
        for conn in self.conns.values():
            if conn:
                conn.close()
        for listener in self.listeners.values():
            if listener:
                listener.close()

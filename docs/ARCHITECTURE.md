# Architecture (draft)

The RotMG server is the game. The Doom port is a first-person window onto it plus the player's
controls. Both run on one PC and talk over localhost TCP, the same pattern as rimworld-mw2.

```
Local RotMG server (C#)            bridge                      UZDoom (C++, ZScript)
  server/ + server-patches/  <──>  bridge/  ──TCP, NDJSON──>    port/ + port-patches/
  owns world, enemies, HP,         speaks RotMG to the         doom-mod/ draws tiles as
  bullets, loot                    server, NDJSON to Doom      sectors, objects as sprites
        ^
        └── the normal RotMG client can stay connected too (minimap / inventory view)
```

## Who owns what

RotMG server owns: the realm map and tiles, enemies and their AI, every projectile and hit,
HP/MP, stats, inventory, loot and portals.

Doom port owns: the camera, input, rendering, sound, and turning mouse aim into a RotMG shoot
angle. RotMG is top-down 2D, so Doom's map is the RotMG tile grid; height is cosmetic.

## Open design choices (each settled in its own thread)

1. **How the bridge reaches the game.** (a) A headless RotMG client that logs in as your
   character and speaks the game protocol, or (b) a server patch that exposes world state and
   accepts movement/shoot commands directly. (b) is simpler and fully local; (a) leaves the
   server untouched.
2. **How Doom receives it.** ZScript has no sockets, so a port patch adds a small TCP listener
   that hands messages to ZScript (as rimworld-mw2 does with its engine bridge plugin).
3. **World building.** Generate geometry at runtime from tile messages (like rimworld-mw2's
   terrain), or convert RotMG maps to UDMF ahead of time. Runtime is needed for procedural realms.
4. **Sprites.** RotMG sheets are 8x8 / 16x16 pixel art with 4 facings and attack frames. A
   converter in `scripts/` turns the user's sheets into Doom sprite lumps in `build/`, never committed.

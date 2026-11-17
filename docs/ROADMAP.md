# Roadmap

Get something working end to end, then iterate. Prefer the simplest thing that runs.

## M0: everything runs separately
- [ ] Local RotMG server builds and runs; the matching client connects and plays
- [x] Both games on one screen: `setup.py play` (RotMG in front, Doom hidden; F12 or RotMG's Doom button swaps to Doom with RotMG's side panel on the right)
- [x] UZDoom builds from the pinned commit and runs `doom-mod` on an IWAD (`setup.py port`, `setup.py run-doom`)
- [ ] `setup.py doctor` finds the server, client, IWAD and tools

## M1: hello socket
- [x] Bridge (`scripts/bridge.py`, run by the swapper) gets the realm and your position from the
      RotMG client (`server-patches/0002`, `romtg/DoomLink.as`) rather than from the server
- [x] Port patch `0001-romtg-bridge`: Doom connects to the bridge (`ROMTGDOOM_BRIDGE_ADDR`,
      default 127.0.0.1:2052); ZScript reads and writes lines through `RomtgBridge`

## M2: ghosts
- [x] Doom starts straight into a flat, empty map (`scripts/flatmap.py`, MAPINFO): no startup screen, title, menus or skill pick
- [x] RotMG ground tiles are drawn on Doom's floor and walls as boxes, within RotMG's 15-tile sight
- [x] Static decorations (trees, rocks...) as upright sprites
- [ ] Enemies, other players, loot and portals

## M3: you are your character
- [x] Doom movement walks your RotMG character (same speed; a tile is sized from the two speeds)
- [ ] Mouse aim and fire shoot in RotMG
- [ ] RotMG projectiles fly as sprites in Doom; your HP shows on the Doom HUD

## M4: it looks like the realm
- [x] Sprite converter for tiles, walls and decorations (`scripts/assets.py`)
- [ ] ... and enemies, projectiles, items
- [ ] Walls and objects get height; portals, loot bags and the nexus work

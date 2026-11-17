# Notes for coding agents

Read `docs/ARCHITECTURE.md` first, then `docs/ROADMAP.md` for the current milestone.

- The local RotMG server is the source of truth (map, enemies, HP, loot, projectiles). The Doom
  port renders it in first person and reports the player's input; it never decides outcomes.
- Never commit game files, sprites, decompiled client code, WADs, or anything under
  `reference/`, `port/` or `server/`. Read them freely: `../reference/rotmg/` holds the user's
  extracted RotMG client, sprite sheets and object XML.
- Doom port changes go in `port-patches/`, server changes in `server-patches/`, as numbered
  patches against the commits pinned in `versions.json`.
- Protocol changes: update `protocol/PROTOCOL.md`, `protocol/examples.ndjson` and both sides together.
- Shared tools across projects live in `../tools/`; don't duplicate them here.
- Build checks: `python scripts/setup.py doctor`.
- Offline only: never connect to official RotMG servers or any online service with modded clients.

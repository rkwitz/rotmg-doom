# Setup notes

Facts behind the setup choices, with where they were confirmed.

## Confirmed
- UZDoom 5.0 is the maintained GZDoom successor (released 2026-08). Pinned at 5.0.3.
- Server: TKR (github.com/Slendergo/TKR-Source, MIT), chosen 2026-11-09 over alloy-server (its
  client was "very unfinished") and NR-CORE (2019, AGPL). .NET 8; runs on newer runtimes with
  `DOTNET_ROLL_FORWARD=Major`, which `run-server` sets.
- Client: TKR ships its own AS3 client (RotMG 7.0 based) in the same repo and commit, so it always
  matches the server's protocol. Built with the Harman AIR SDK (`amxmlc`, needs Java); run with `adl`.
  The app descriptor's namespace must be at least the SDK version, or `adl` fails with "error while
  loading initial content"; `setup.py client` rewrites it.
- The server needs Redis: Memurai on Windows (port 6379, database 1). The friend server package
  runs TKR's bundled redis-server on port 6380 instead.
- No guest play: the game server answers "Bad Login" until you register an account.
- All server-patches apply in order to a fresh TKR clone at the pinned commit (checked 2026-11-16);
  the only other differences from a working tree are files generated at build time (pet data, pet
  yard map, Mad Lab map).

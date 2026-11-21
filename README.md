<img width="2560" height="1440" alt="rotmg-doom mp4_snapshot_01 16 000" src="https://github.com/user-attachments/assets/260202cf-3e15-4c41-9909-5e76eb2a4302" />

# RotMG x Doom

Walk around Realm of the Mad God in first person (or third person), in Doom.

A local Realm of the Mad God server runs the game: the realm, its enemies, their bullets, your HP,
your class and your loot. A patched Doom source port (UZDoom) draws the same world in 3D using
RotMG's own sprites. Both games run at the same time on your PC and talk over a local connection.
Where you walk in Doom, your character walks in RotMG, and when you shoot, they shoot. One key
swaps between the two views, and RotMG's side panel (map, stats, gear, inventory) stays on screen
while you're in Doom.

> **This repo contains no game code or assets.** Setup downloads the open-source pieces (the
> UZDoom source port and the TKR RotMG server), applies this repo's patches, and builds
> everything into folders that are never committed (`port/`, `server/`, `build/` and
> `../reference/`). Don't share those folders publicly. Play on your own server only, and never
> connect a modded client to the official RotMG servers.

- [What you need](#what-you-need)
- [Set it up (once)](#set-it-up-once)
- [Play](#play)
- [Controls](#controls)
- [Third person](#third-person)
- [Host a server for friends](#host-a-server-for-friends)
- [Updating](#updating)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Credits and license](#credits-and-license)

## What you need

**Windows 10 or 11** and a graphics card with OpenGL 4.x (anything from the last ten years).
Setup needs about **8 GB** of free disk space, almost all of it for the Doom port's build.

Install these, then **open a new PowerShell window** so they're on your PATH:

| Tool | Why | Get it |
|---|---|---|
| Git | Downloads this repo, the Doom port and the server | https://git-scm.com/download/win |
| Python 3.10+ | Runs setup, the sprite converter and the window swapper | https://www.python.org/downloads/ (tick **Add python.exe to PATH**) |
| Visual Studio 2022 Build Tools, workload **Desktop development with C++** | Compiles UZDoom | https://visualstudio.microsoft.com/downloads/ (under *Tools for Visual Studio*) |
| CMake 3.16+ | Builds UZDoom (the copy bundled with Visual Studio also works) | https://cmake.org/download/ |
| .NET SDK 8 or newer | Builds and runs the RotMG server | https://dotnet.microsoft.com/download |
| Java 11+ | Runs the AIR SDK's compiler | https://adoptium.net |
| Harman AIR SDK 51 | Compiles the RotMG client | https://airsdk.harman.com/download (see below) |
| Memurai (Developer edition, free) | The server's database (Redis for Windows) | https://www.memurai.com/get-memurai |

Then the Python packages (from the repo folder, once you've cloned it below):

```powershell
python -m pip install -r requirements.txt
```

**The AIR SDK.** Download the Windows SDK (or install the *AIR SDK Manager* and use it to download
one). Put the SDK folder at exactly `game_modding\tools\AIRSDK`, so
`game_modding\tools\AIRSDK\bin\amxmlc.bat` exists. Setup also accepts `ROMTGDOOM_AIR_SDK` in `.env`
(see [.env.example](.env.example)), but the friend-server packager only looks in `tools\AIRSDK`.

**Memurai** installs as a Windows service and starts by itself on port 6379. The server keeps its
data in database 1, so it won't touch anything else you keep in Memurai.

**A Doom IWAD.** Free and recommended: `freedoom2.wad` from https://freedoom.github.io (the
*Freedoom: Phase 2* download). `DOOM2.WAD` from Steam or GOG also works. Only Doom's engine basics
are used; every picture you see comes from RotMG. Put it in `game_modding\reference\doom\`.

**Optional: RotMG Exalt.** If you have Realm of the Mad God installed (Steam or the launcher), setup
takes the official logo and title background from your install for the title screen
(`pip install UnityPy` first). Without it, the title screen shows the name as text.

### Folder layout

Everything lives in one workspace folder. The repo sits next to two shared folders, which are never
committed:

```
Documents\game_modding\
├ reference\             never committed
│ ├ doom\                your IWAD (freedoom2.wad)
│ ├ repos\               reference repos setup clones (pets, dungeons)
│ └ rotmg\client\        the built RotMG client
├ tools\
│ └ AIRSDK\              the Harman AIR SDK
└ rotmg-doom\            this repo
```

## Set it up (once)

In PowerShell:

```powershell
mkdir $HOME\Documents\game_modding -Force
cd $HOME\Documents\game_modding
git clone https://github.com/rkwitz/rotmg-doom
cd rotmg-doom
python -m pip install -r requirements.txt
python scripts\setup.py doctor
```

`doctor` checks every tool and file above and says what's missing. When it's happy, run these five
steps in order. Each one can be re-run safely; it skips work that's already done.

```powershell
python scripts\setup.py references   # 1. reference repos: RotMG pet data, the full Mad Lab   (~1 min)
python scripts\setup.py server       # 2. download TKR, apply server-patches, build it         (~2 min)
python scripts\setup.py client       # 3. compile the RotMG client into reference\rotmg\client (~1 min)
python scripts\setup.py port         # 4. download UZDoom, apply port-patches, build it        (~10-15 min)
python scripts\setup.py build-mod    # 5. convert RotMG's sprites and pack the Doom mod        (~1 min)
```

What each step does:

1. **references** clones the pinned repos in [versions.json](versions.json) into
   `..\reference\repos`: NR-CORE and NR's 27.7 client (RotMG's pet data and pet sprite sheets) and
   alloy-server (the full-size Mad Lab map).
2. **server** clones [TKR](https://github.com/Slendergo/TKR-Source) at the pinned commit into
   `server\`, applies every patch in `server-patches\` in order, generates the pet and dungeon data,
   and builds the account server and game server (Release).
3. **client** compiles TKR's own RotMG client (RotMG 7.0 based, with this repo's client changes,
   which live in `server-patches\` too) with the AIR SDK into `..\reference\rotmg\client`.
4. **port** clones [UZDoom 5.0.3](https://github.com/UZDoom/UZDoom) into `port\`, applies
   `port-patches\` (the socket that lets Doom talk to RotMG) and builds it with Visual Studio 2022.
5. **build-mod** slices RotMG's sprite sheets from the client into Doom sprites and packs them with
   `doom-mod\` into `build\romtg-doom.pk3`. `play` re-runs this every time, so you only need it
   here to check it works.

Run `python scripts\setup.py doctor` again at the end. There should be no `[fail]` lines. A
`redis-cli not found` warning is fine, since Memurai's own tool is called `memurai-cli`.

## Play

```powershell
.\play.bat
```

`play.bat` (the same as `python scripts\setup.py play`) does everything:

1. Starts the account server (port 2000) and game server (port 2002) in their own windows, unless
   they're already running. If the server's code changed since its last build, it rebuilds first.
2. Starts UZDoom and the RotMG client.
3. Runs the swapper (`scripts\duo.py`), which arranges the two windows and handles the swap keys.

The first time, click **Register** in the RotMG client and make an account. The email can be
anything shaped like one, since nothing is sent. Names are letters only, at most 10. Pick a class
and play. Your accounts and characters stay in Memurai between runs.

RotMG starts in front, and Doom keeps running hidden behind it. Press **~** (or click the orange
swap icon next to the nexus button in RotMG's side panel) to go into Doom. In Doom, **C** switches
between first and third person. **F10** closes both games and the server.

## Controls

**Anywhere** (while one of the two games is in front):

| Key | Does |
|---|---|
| **~** or **Scroll Lock** (or the orange swap icon in RotMG's side panel) | Swap between RotMG and Doom |
| **F10** | Close both games and the server |

**In Doom:**

| Key | Does |
|---|---|
| Your Doom movement keys and mouse | Walk and look. You move at your character's real RotMG speed, with RotMG's collisions |
| Fire | Shoot your RotMG weapon where the crosshair is, at its own rate of fire |
| **C** (or the camera icon in RotMG's side panel) | First person / [third person](#third-person) |
| **Space** | Your class ability, aimed where you look. Thrown abilities: hold to aim, let go to throw (below) |
| **F** / **V** | Health potion / magic potion |
| **1-8** | Use inventory slot 1-8 |
| **Enter** | Interact: enter a portal, open a loot bag |
| **R** | Back to the nexus |
| **Q** / **E** | Turn RotMG's camera (the live view in the side panel) |
| **Tab** | Hand the mouse to RotMG's side panel (inventory, swapping and dropping items) with Doom still on screen; Tab again, or click Doom, to go back |
| **Esc** | RotMG's options screen |

**Changing keys:** every key above except Doom's movement, Tab and Esc follows your RotMG key
bindings, so you change them in RotMG's **Options → Controls**, and Doom picks the change up as soon
as you close Options. Three entries there are this mod's own: **Swap First Person / Top Down**
(default `~`), **First / Third Person Camera** (default C) and **Close Both Games** (default F10).
Scroll Lock always swaps too, and Enter always interacts in Doom.

**Thrown abilities** (the huntress's trap, the assassin's poison, the necromancer's skull, the
mystic's orb, the sorcerer's lightning, teleport cloaks): hold Space and Doom draws the throw's arc
and a ring where it lands, the size of what it does there. Look up to throw farther (up to 8
tiles; teleports up to the cloak's range), down to throw closer, and let go to throw. Other
abilities fire as soon as you press Space; the ninja's star is held and thrown on release, as in
RotMG.

When a RotMG dialog, shop, menu or the death screen opens, the swapper brings RotMG forward on its
own and goes back to Doom when it closes.

In Doom you see what RotMG sees: its ground on the floor, walls as blocks, and every enemy, player,
portal, bag and bullet as RotMG's own sprites, out to 48 tiles with fog. RotMG's own HUD (chat, gold
and fame, the boss bar, XP and damage texts) is drawn over Doom, and enemies get health bars at
their feet.

## Third person

Press **C** in Doom (or click the camera icon left of the swap icon in RotMG's side panel) to put
the camera behind and above your character, looking down at a fixed low angle; C again goes back
to your own eyes. The camera turns with your mouse, so you aim the same way: you shoot where you
face. Moving the mouse up and down doesn't tilt the camera; it only sets how far thrown abilities
go.

In third person you see your own character, seen from behind, walking and attacking with RotMG's
own animation frames and timing. Its health bar sits just under it, as in RotMG, and things in front
of you (your pet, players, statues, walls) hide it as they would in the world. Your damage, healing
and XP texts float over your character, and the HUD health bar at the bottom of the screen is off.
Everything else (movement, firing, the side panel, other players and enemies) works as in first
person.

### Swapper options

`play.bat` passes extra arguments to the swapper, for example `.\play.bat --key f12 --start doom`.

| Option | Default | |
|---|---|---|
| `--key` | `tilde,scrolllock` | Swap keys, comma separated: tilde, scrolllock, f12, pause, insert, numlock, rctrl, apps. Your RotMG Options binding replaces this once the client connects |
| `--quit-key` | `f10` | Closes everything; `none` turns it off. Also set in RotMG's Options |
| `--start` | `rotmg` | Which game fills the screen first: `rotmg` or `doom` |
| `--minimap` | `menu` | `corner` shows all of RotMG as a minimap in the top left instead of its side panel |

Settings that you'd otherwise pass every time can go in `.env` (copy [.env.example](.env.example)).
For example, `ROMTGDOOM_LOOT_POWER` changes drop rates. Drops are boosted for showcasing: each
chance p becomes p^0.7, so a 1% drop becomes about 4%. Set it to 1 for the stock game.

## Host a server for friends

`scripts\friend\build_demo.py` packages a **server** you run and a **client** your friends run.
Friends don't install anything; they just unzip the folder and run `Play.exe`.

**On your side (the host):**

1. Finish [Set it up](#set-it-up-once), so the server, client, port and mod are all built. The
   package ships `freedoom2.wad`, so it needs that IWAD in `reference\doom\`, not `DOOM2.WAD`
   (which you can't give away anyway).
2. Install PyInstaller, which makes the two launchers: `python -m pip install pyinstaller`.
3. Find your **public IP address** (search "what is my IP"), or use a dynamic DNS name if your IP
   changes.
4. Build both packages:

   ```powershell
   python scripts\friend\build_demo.py YOUR.PUBLIC.IP
   ```

   They land in `game_modding\friend-demos\rotmg-doom\`:
   - `server\`: `Start Server.exe`, the account and game servers, and their own database (a Redis
     on port 6380 inside that folder, kept apart from your Memurai, so friends' accounts never mix
     with yours).
   - `client\`: `Play.exe` (with its `play-lib\` folder beside it), Doom, the RotMG client with its own AIR runtime, and `rotmg\server.txt`
     holding your address.

5. **Forward TCP ports 2000 and 2002** on your router to your PC: 2000 is the account server and
   2002 is the game. Your router's admin page (often http://192.168.1.1) has this under *Port
   forwarding* or *Virtual servers*. Allow both through Windows Firewall when it asks.
6. Stop your own development server if it's running (it uses the same ports), then run
   `server\Start Server.exe`. It opens one terminal window with three tabs (database, accounts,
   game). Closing that window stops the server.
7. Zip the `client\` folder and send it to your friends privately. It contains game art, so don't
   post it publicly.

**On your friends' side:** unzip the folder anywhere, run `Play.exe`, register an account, play.
Same keys as above. Each player's Doom view and wall checks run on their own PC; only the game
itself (enemies, bullets, other players) goes over the internet.

**Testing at home:** many routers don't route your own public IP back to you. To try the client
package on the hosting PC, change `client\rotmg\server.txt` to `127.0.0.1`.

**Updating a running server:** rebuilding the packages overwrites them, and `server\redis\` holds
your friends' accounts. For an update, rebuild with `--out` set to a new folder, and copy only the
changed program files (for example `world\TKR.WorldServer.dll`) into the live server folder while
it's stopped. Never copy over `redis\`.

## Updating

```powershell
git pull
python scripts\setup.py server
python scripts\setup.py client
python scripts\setup.py port
```

New patches apply on top of what's there. If a patch fails to apply (your `server\` or `port\` was
edited by hand), add `--force` to start that checkout fresh from the pinned commit.

## Troubleshooting

| Problem | Fix |
|---|---|
| `doctor` can't find a tool you installed | Open a new PowerShell window so the new PATH loads |
| Client won't log in: "Bad Login" | There's no guest play. Click Register and make an account first |
| Account server window says *You must install or update .NET* | `run-server` already runs it on newer .NET. If it still fails, install the *ASP.NET Core Runtime 8.0 (x64)* from https://dotnet.microsoft.com/download/dotnet/8.0 |
| "Redis/Memurai not answering on 127.0.0.1:6379" | Start the *Memurai* service (Windows Services, or reinstall Memurai) |
| `adl` says *error while loading initial content* | Re-run `setup.py client`; it matches the client's descriptor to your AIR SDK version |
| Game server window shows a socket/Bind error | Another copy is already running on port 2002. Close the extra window |
| The server stops after a few hours | TKR restarts its world on a timer (`restartTime` hours in `server\TK-Server\TKR.WorldServer\wServer.json`); the friend server package sets it to 10 years |
| `setup.py client` finishes but nothing changed in game | Check the output for `Syntax error:` lines. The compiler then writes no new client. The good build ends with `... bytes written to ...TK-Client.swf` |
| Doom's HUD flickers | Doom uses OpenGL by default for this reason. On NVIDIA, set *Vulkan/OpenGL present method* to *Prefer layered on DXGI Swapchain* in the NVIDIA Control Panel |
| A window is left borderless or hidden after a crash | The swapper restores windows on a clean exit only. Close the games and run `play.bat` again |
| Windows Defender quarantines `Play.exe` (e.g. *Behavior:Win32/DefenseEvasion*) | A false positive: the launcher hooks the keyboard for the swap key, moves the game windows and can close them (F10), which looks like malware to behaviour checks. Restore it in Windows Security → Protection history → Allow, or exclude the folder. Rebuild the package if it's older than the one-folder launcher (`Play.exe` + `play-lib\`) |

Logs from the last run are in `logs\`: `duo.log` (window swapping), `bridge.log` (the link between
the games, client errors) and `uzdoom.log` (Doom's console). Server logs are in
`server\TK-Server\TKR.WorldServer\bin\Release\net8.0\logs\`.

## How it works

```
TKR server (C#, local)        RotMG client (AIR)                    UZDoom (patched)
 accounts :2000         <-->   TK-Client + romtg/DoomLink.as  <-->   romtg_bridge.cpp
 game     :2002                      |  127.0.0.1:2051                 |  127.0.0.1:2052
 owns the world, enemies,            +------ scripts/bridge.py --------+
 bullets, HP, loot                    (run inside scripts/duo.py, which also swaps the windows)
```

- The server is the game. The RotMG client plays it as usual and, through `romtg/DoomLink.as`,
  reports everything it knows (tiles, objects, bullets, your position) and accepts movement,
  aiming and key presses.
- `scripts/bridge.py` translates between the client and Doom. In Doom,
  `doom-mod/zscript/romtg_handler.zs` builds the world from those messages, walks you with RotMG's
  own movement rules, and sends your input back. Doom never decides an outcome.
- Scale: one tile is as many Doom units as Doom's marine runs in the time your character walks one
  tile, so the two speeds match.
- Sprites: `scripts/assets.py` slices the client's own sprite sheets into Doom sprites at build
  time, so no picture is ever in this repo.

| Folder | Holds |
|---|---|
| `server-patches/` | Numbered changes to TKR, server and client, against the commit in `versions.json` |
| `port-patches/` | Changes to UZDoom (the bridge socket) |
| `doom-mod/` | The Doom side: ZScript, MAPINFO, shaders |
| `scripts/` | `setup.py` (setup, build, play), `duo.py` (window swapper), `bridge.py`, `assets.py` (sprites), `pets.py` and `dungeons.py` (data generated at build time), `exalt.py` (title art), `friend/` (hosting packages) |
| `protocol/` | The bridge's message format |
| `docs/` | Architecture and roadmap |

Pinned versions are in [versions.json](versions.json). Change them on purpose, in their own commit.
Notes for AI coding agents are in [CLAUDE.md](CLAUDE.md).

### What's changed from TKR

- RotMG's **pet system**, ported from NR-CORE: the Pet Yard portal in the nexus, eggs from bosses,
  hatching, feeding, fusing, and pets that follow you and use their abilities.
- **No real-money currency.** Everything gold bought now costs fame.
- **Dungeons:** broken TK stubs removed, plus the full-size Mad Lab with its boss AI from
  alloy-server.
- Compressed loot odds (above), 48-tile sight, RotMG's own welcome texts and branding instead of TK's.

## Credits and license

- [UZDoom](https://github.com/UZDoom/UZDoom) (GPL-3.0), the Doom source port this patches.
- [TKR](https://github.com/Slendergo/TKR-Source) by Slendergo and contributors (MIT), the RotMG
  server and client this patches.
- [NR-CORE](https://github.com/cp-nilly/NR-CORE) by cp-nilly (AGPL-3.0), the pet system ported in
  `server-patches/0004` and `0005`. Pet data comes from NR's 27.7 client at build time.
- [alloy-server](https://github.com/Zolmex/alloy-server) by Zolmex (MIT), the Mad Lab map and boss AI.
- [Freedoom](https://freedoom.github.io), the free IWAD.

License: [AGPL-3.0](LICENSE). The port patches derive from UZDoom (GPL-3.0) and the pet patches
from NR-CORE (AGPL-3.0), so the repo as a whole is AGPL-3.0. TKR and alloy-server code used here is
MIT, which allows this.

Unofficial fan project, not affiliated with DECA Games or id Software. Realm of the Mad God is
(c) DECA Games; DOOM is (c) id Software. See [NOTICE](NOTICE).

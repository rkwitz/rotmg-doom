"""Play.exe of the friend demo (scripts/friend/build_demo.py packages it): Doom and the RotMG
client from the folder it sits in, then the swapper (duo.py) and bridge, as `setup.py play` but
with no server and nothing to build. The client finds the server in rotmg/server.txt.

    <folder>/Play.exe
    <folder>/doom/      uzdoom.exe, freedoom2.wad, romtg-doom.pk3
    <folder>/rotmg/     TK-Client.exe (its own AIR runtime), server.txt
    <folder>/data/      romtg-assets.json
    <folder>/logs/      uzdoom.log, duo.log, bridge.log
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Kept in step with setup.py's DOOM_START_ARGS and DOOM_DUO_ARGS.
DOOM_ARGS = ["-nostartup", "-skill", "3", "+map", "ROMTG", "+disableautosave", "2",
             "+screenblocks", "12", "+crosshair", "1",
             "+vid_fullscreen", "0", "+i_pauseinbackground", "0", "+i_soundinbackground", "0",
             "+vid_activeinbackground", "1", "+vid_lowerinbackground", "0", "+vid_preferbackend", "0",
             "+unbind", "t"]   # Doom's own chat trapped the keyboard (setup.py)


def home() -> Path:
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def main() -> int:
    base = home()
    os.environ["ROMTG_HOME"] = str(base)
    os.environ["ROMTG_ASSETS"] = str(base / "data" / "romtg-assets.json")
    sys.path.insert(0, str(base.parent))   # (unfrozen runs: duo.py and bridge.py next door)
    import duo  # noqa: E402  (after ROMTG_HOME: its log goes into this folder)

    (base / "logs").mkdir(exist_ok=True)
    doom_dir, rotmg_dir = base / "doom", base / "rotmg"
    doom_log = (base / "logs" / "uzdoom.log").open("w", encoding="utf-8")
    subprocess.Popen([str(doom_dir / "uzdoom.exe"), "-iwad", "freedoom2.wad", "-file", "romtg-doom.pk3",
                      "-stdout", *DOOM_ARGS], cwd=doom_dir, stdout=doom_log, stderr=subprocess.STDOUT)
    subprocess.Popen([str(rotmg_dir / "TK-Client.exe")], cwd=rotmg_dir)
    try:
        return duo.main(sys.argv[1:])
    finally:
        doom_log.close()


if __name__ == "__main__":
    sys.exit(main())

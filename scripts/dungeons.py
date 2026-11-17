"""Dungeon maps taken from other open-source RotMG servers, copied into TK's resources at build
time (like the pet data, never committed): Mad Lab's full-size layout from alloy-server
(github.com/Zolmex/alloy-server, MIT; pinned in versions.json). TK's own Mad Lab was a smaller
stand-in; TK already has the objects and the AI for everything in alloy's (the two it lacked,
Horrific Creation and Mad Gas Controller, are in server-patches/0007).
"""
from __future__ import annotations

import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ALLOY = REPO.parent / "reference" / "repos" / "Zolmex_alloy-server" / "Common" / "Resources" / "World" / "Data"
TK_WORLDS = REPO / "server" / "TK-Server" / "TKR.Shared" / "resources" / "worlds"
MAPS = {"MadLab.jm": "mad_lab.jm"}   # alloy's file -> TK's


def ensure() -> str:
    if not ALLOY.is_dir():
        return f"Mad Lab keeps TK's small layout: {ALLOY} missing (clone github.com/Zolmex/alloy-server there)"
    for src, dst in MAPS.items():
        shutil.copy2(ALLOY / src, TK_WORLDS / dst)
    return f"dungeon maps from alloy-server: {', '.join(MAPS.values())}"


if __name__ == "__main__":
    print(ensure())

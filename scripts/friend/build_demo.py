"""Build the friend demo (Ryan, 2026-11-15): a client folder friends run (Play.exe) that
connects to Ryan's server over the internet, and a server folder Ryan runs (Start Server.exe).

    python scripts/friend/build_demo.py HOST [--out DIR]

HOST is the public address friends connect to (written to the client's rotmg/server.txt and the
game server's listed address). The client needs the built pieces (setup.py port, build-mod,
client) and the server the built TKR (setup.py server); the .exe launchers need PyInstaller.
Friends forward nothing; the host forwards TCP 2000 (accounts) and 2002 (game).

The demo server keeps its own database (redis on port 6380, in its folder), apart from the
development one (Memurai, 6379): demo accounts and characters never mix with Ryan's.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
WORKSPACE = REPO.parent
SDK = WORKSPACE / "tools" / "AIRSDK" / "bin"
CLIENT_BUILD = WORKSPACE / "reference" / "rotmg" / "client"
DOOM_BUILD = REPO / "port" / "build" / "RelWithDebInfo"
IWAD = WORKSPACE / "reference" / "doom" / "freedoom2.wad"
TKR = REPO / "server" / "TK-Server"
DEMO_REDIS_PORT = 6380


def copy_tree(src: Path, dst: Path, skip=()) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in skip or item.suffix == ".pdb":
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def exe(script: Path, name: str, out: Path, work: Path, extra: list[str]) -> bool:
    """Launcher with PyInstaller, into OUT: NAME.exe and its Python beside it in NAME-lib/.

    Not one file: a one-file PyInstaller exe unpacks itself to a temp folder and runs from
    there, which together with what Play.exe does (a keyboard hook, moving other programs'
    windows, closing processes) Windows Defender took for malware and quarantined
    (Behavior:Win32/DefenseEvasion, Ryan 2026-11-21)."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(f"PyInstaller missing: {name}.exe not built (pip install pyinstaller)")
        return False
    dist = work / "dist"
    lib = f"{name.replace(' ', '-').lower()}-lib"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--console", "--noupx",
                    "--contents-directory", lib,
                    "--name", name, "--distpath", str(dist), "--workpath", str(work / "build"),
                    "--specpath", str(work), *extra, str(script)], check=True)
    old = out / f"{name}.exe"
    if old.exists():
        old.unlink()
    if (out / lib).exists():
        shutil.rmtree(out / lib)
    shutil.copy2(dist / name / f"{name}.exe", old)
    shutil.copytree(dist / name / lib, out / lib)
    return True


def build_client(host: str, out: Path, work: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    # RotMG with its own AIR runtime (a captive bundle): friends need no Adobe AIR.
    cert = work / "romtg-demo.p12"
    if not cert.exists():
        subprocess.run([str(SDK / "adt.bat"), "-certificate", "-cn", "RomtgDoomDemo", "2048-RSA",
                        str(cert), "romtgdemo"], check=True)
    rotmg = out / "rotmg"
    if rotmg.exists():
        shutil.rmtree(rotmg)
    subprocess.run([str(SDK / "adt.bat"), "-package", "-storetype", "pkcs12", "-keystore", str(cert),
                    "-storepass", "romtgdemo", "-target", "bundle", str(rotmg), "TK-Client-app.xml",
                    "TK-Client.swf", "assets"], cwd=CLIENT_BUILD, check=True)
    (rotmg / "server.txt").write_text(host + "\n", encoding="utf-8")
    # Doom: UZDoom, Freedoom (BSD-licensed) and the mod.
    doom = out / "doom"
    copy_tree(DOOM_BUILD, doom)
    shutil.copy2(IWAD, doom / "freedoom2.wad")
    shutil.copy2(REPO / "build" / "romtg-doom.pk3", doom / "romtg-doom.pk3")
    (out / "data").mkdir(exist_ok=True)
    shutil.copy2(REPO / "build" / "romtg-assets.json", out / "data" / "romtg-assets.json")
    (out / "logs").mkdir(exist_ok=True)
    exe(HERE / "friend_play.py", "Play", out, work / "play",
        ["--paths", str(REPO / "scripts"), "--hidden-import", "duo", "--hidden-import", "bridge"])
    (out / "README.txt").write_text(
        "Realm of the Mad God + Doom (demo)\n\n"
        "Run Play.exe. RotMG opens first: make an account and a character.\n"
        "Press ~ (tilde) or the Doom button in RotMG's side panel to play in Doom, and again to go back.\n"
        "In Doom: WASD to walk, mouse to look, click to shoot, Q/E to turn the minimap,\n"
        "Tab for RotMG's side panel (inventory), F10 closes both games.\n"
        "If something goes wrong, send the files in logs/.\n", encoding="utf-8")


def build_server(host: str, out: Path, work: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    copy_tree(TKR / "TKR.App" / "bin" / "Release" / "net8.0", out / "app", skip=("logs",))
    copy_tree(TKR / "TKR.WorldServer" / "bin" / "Release" / "net8.0", out / "world", skip=("logs",))
    copy_tree(TKR / "TKR.Shared" / "resources", out / "resources")
    for project, folder, name in (("TKR.App", "app", "server.json"), ("TKR.WorldServer", "world", "wServer.json")):
        cfg = json.loads((TKR / project / name).read_text(encoding="utf-8-sig"))
        cfg["dbInfo"]["port"] = DEMO_REDIS_PORT
        cfg["serverSettings"]["resourceFolder"] = "../resources"
        cfg["serverSettings"]["logFolder"] = "./logs"
        if project == "TKR.WorldServer":
            cfg["serverInfo"]["address"] = host
            # TKR restarts itself every restartTime hours (2: it shut down on its own after two
            # hours of play, Ryan 2026-11-15); 0 would restart at once. Ten years: never.
            cfg["serverSettings"]["restartTime"] = 87600
        (out / folder / name).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    redis = out / "redis"
    redis.mkdir(exist_ok=True)
    shutil.copy2(TKR / "TKR.Redis" / "redis-server.exe", redis / "redis-server.exe")
    conf = (TKR / "TKR.Redis" / "tk_database__config.conf").read_text(encoding="utf-8")
    conf = conf.replace("\nport 6379", f"\nport {DEMO_REDIS_PORT}").replace("maxmemory 8gb", "maxmemory 1gb")
    conf = conf.replace("dbfilename tk_database__file.rdb", "dbfilename demo.rdb")
    # A snapshot within 10 s of any change: closing the database window loses at most that
    # (with only TKR's rules, up to 15 minutes of play could go). Not AOF: switching an existing
    # RDB database to AOF can start it empty on older redis builds.
    conf = conf.replace("save 60 10000", "save 60 10000" + chr(10) + "save 10 1")
    (redis / "demo.conf").write_text(conf, encoding="utf-8")
    exe(HERE / "start_server.py", "Start Server", out, work / "server", [])
    (out / "README.txt").write_text(
        "Friend demo server (Ryan runs this).\n\n"
        "Run 'Start Server.exe': it opens one window with three tabs: database, game server, account server.\n"
        "Close that window to stop it. Forward TCP ports 2000 and 2002 to this PC.\n"
        "The dev server (play.bat) uses the same ports: run one or the other, not both.\n"
        "Its database (accounts, characters) is redis/demo.rdb, apart from the dev one.\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("host")
    parser.add_argument("--out", default=str(WORKSPACE / "friend-demos" / "rotmg-doom"))
    parser.add_argument("--work", default=str(REPO / "build" / "friend-demo"))
    parser.add_argument("--only", choices=("client", "server"))
    args = parser.parse_args()
    out, work = Path(args.out).resolve(), Path(args.work).resolve()   # adt runs elsewhere (cwd)
    work.mkdir(parents=True, exist_ok=True)
    if args.only != "server":
        build_client(args.host, out / "client", work)
    if args.only != "client":
        build_server(args.host, out / "server", work)
    print(f"built in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

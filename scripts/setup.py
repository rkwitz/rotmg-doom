#!/usr/bin/env python3
"""Workspace setup for RotMG x Doom (ROMTG-Doom).

Everything here works from files the user already has. Nothing produced here may be
committed or shared.

Layout: <workspace>/reference/{repos,rotmg,doom} is shared by every project in the
workspace; this project's port and server checkouts live in <repo>/port and <repo>/server.

Usage:
    python scripts/setup.py doctor        check tools and find game files
    python scripts/setup.py references    clone pinned reference repos
    python scripts/setup.py port          clone UZDoom into port/, apply port-patches, build (VS 2022)
    python scripts/setup.py build-mod     zip doom-mod/ into build/romtg-doom.pk3
    python scripts/setup.py run-doom      build-mod, then start UZDoom on the IWAD with the pk3
    python scripts/setup.py server        clone TKR into server/, apply server-patches, build
    python scripts/setup.py run-server    start the TKR account + game servers (needs Memurai)
    python scripts/setup.py client        compile TK-Client into reference/rotmg/client (AIR SDK)
    python scripts/setup.py run-client    start the client; it only talks to 127.0.0.1
    python scripts/setup.py play          server + both games; RotMG in front, Doom hidden; ~ or
                                          RotMG's Doom button swaps (scripts/duo.py)

Planned: assets.
Settings can also live in a .env file at the repo root (see .env.example).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERSIONS = json.loads((REPO / "versions.json").read_text(encoding="utf-8"))
ENV_PREFIXES = ("ROMTGDOOM_", "ROTMG_", "DOOM_")
IWAD_NAMES = ["DOOM2.WAD", "doom2.wad", "freedoom2.wad", "DOOM.WAD", "doom.wad", "freedoom1.wad"]


def load_env() -> dict[str, str]:
    """Read KEY=VALUE lines from .env, letting real environment variables win."""
    env: dict[str, str] = {}
    path = REPO / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"')
    env.update({k: v for k, v in os.environ.items() if k.startswith(ENV_PREFIXES)})
    return env


ENV = load_env()


def workspace() -> Path:
    return Path(ENV.get("ROMTGDOOM_WORKSPACE", REPO.parent)).expanduser().resolve()


def reference_dir() -> Path:
    return workspace() / "reference"


def server_dir() -> Path:
    return Path(ENV.get("ROTMG_SERVER_DIR") or REPO / "server")


def port_dir() -> Path:
    return REPO / "port"


def info(msg: str) -> None: print(f"  {msg}")
def ok(msg: str) -> None: print(f"  [ok]   {msg}")
def warn(msg: str) -> None: print(f"  [warn] {msg}")
def fail(msg: str) -> None: print(f"  [fail] {msg}")
def step(title: str) -> None: print(f"\n== {title}")


class SetupError(Exception):
    pass


def tool_fallbacks(name: str) -> list[Path]:
    """Install locations to try when a tool is missing from PATH (a terminal opened before install)."""
    if name != "cmake" or os.name != "nt":
        return []
    found = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "CMake" / "bin" / "cmake.exe"]
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.exists():
        for vs in (capture([str(vswhere), "-products", "*", "-property", "installationPath"]) or "").splitlines():
            found.append(Path(vs) / "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe")
    return found


def find_tool(name: str) -> str:
    if shutil.which(name):
        return name
    for path in tool_fallbacks(name):
        if path.exists():
            return str(path)
    return name


def run(cmd: list[str], cwd: Path | None = None) -> None:
    cmd = [find_tool(cmd[0]), *cmd[1:]]
    info("$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    try:
        code = subprocess.run(cmd, cwd=cwd).returncode
    except FileNotFoundError:
        raise SetupError(f"{cmd[0]} not found; install it or add it to PATH (see `setup.py doctor`)")
    if code != 0:
        raise SetupError(f"command failed: {cmd[0]}")


def capture(cmd: list[str]) -> str | None:
    if cmd[0] == "cmake":
        cmd = [find_tool("cmake"), *cmd[1:]]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def clone_pinned(url: str, commit: str, dest: Path, force: bool) -> None:
    if "TBD" in (url, commit):
        warn(f"{dest.name}: not pinned yet in versions.json")
        return
    if dest.exists() and force:
        shutil.rmtree(dest)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q", str(dest)])
        run(["git", "-C", str(dest), "remote", "add", "origin", url])
    if capture(["git", "-C", str(dest), "rev-parse", "HEAD"]) == commit:
        ok(f"{dest.name} already at {commit[:10]}")
        return
    run(["git", "-C", str(dest), "fetch", "-q", "--depth", "1", "origin", commit])
    run(["git", "-C", str(dest), "checkout", "-q", "--force", "FETCH_HEAD"])
    ok(f"{dest.name} at {commit[:10]}")


def find_iwad() -> Path | None:
    if ENV.get("DOOM_IWAD"):
        path = Path(ENV["DOOM_IWAD"])
        return path if path.exists() else None
    for folder in [reference_dir() / "doom", REPO]:
        for name in IWAD_NAMES:
            if (folder / name).exists():
                return folder / name
    return None


def cmd_doctor(args) -> bool:
    step("Tools")
    healthy = True
    for tool, flag, why, required in [
        ("git", "--version", "cloning repos", True),
        ("cmake", "--version", "building UZDoom", True),
        ("dotnet", "--version", "building the RotMG server", True),
        ("redis-cli", "--version", "the RotMG server database (Memurai on Windows)", False),
        ("java", "--version", "the AIR SDK compiler for the RotMG client", False),
    ]:
        version = capture([tool, flag])
        if version:
            ok(f"{tool}: {version.splitlines()[0]}")
        elif required:
            fail(f"{tool} not found (needed for {why})")
            healthy = False
        else:
            warn(f"{tool} not found (may be needed for {why})")
    ok(f"python {sys.version_info.major}.{sys.version_info.minor}")

    step("Game files")
    iwad = find_iwad()
    (ok if iwad else warn)(f"Doom IWAD: {iwad or 'not found; set DOOM_IWAD in .env or put one in reference/doom'}")
    client = reference_dir() / "rotmg" / "client"
    has_client = client.is_dir() and any(client.iterdir())
    (ok if has_client else warn)(f"RotMG client: {client}{'' if has_client else ' (empty; run `setup.py client`)'}")
    sdk = find_air_sdk()
    (ok if sdk else warn)(f"AIR SDK: {sdk or 'not found; extract Harman AIR SDK to tools/AIRSDK_<version>'}")
    (ok if redis_ok() else warn)("Redis/Memurai answering on 127.0.0.1:6379" if redis_ok() else
                                 "Redis/Memurai not answering on 127.0.0.1:6379")

    step("Workspace")
    info(f"workspace: {workspace()}")
    for name, path in [("references", reference_dir() / "repos"), ("server", server_dir()), ("port", port_dir())]:
        (ok if path.exists() else warn)(f"{name}: {path}{'' if path.exists() else ' (not set up yet)'}")
    return healthy


def cmd_references(args) -> bool:
    step("Reference repos")
    for ref in VERSIONS["references"]:
        clone_pinned(ref["repo"], ref["commit"], reference_dir() / "repos" / ref["name"], args.force)
    return True


PORT_BUILD_TYPE = "RelWithDebInfo"


def port_build_dir() -> Path:
    return port_dir() / "build"


def port_exe() -> Path:
    return port_build_dir() / PORT_BUILD_TYPE / "uzdoom.exe"


def applied_record(checkout: Path) -> Path:
    """The names of the patches applied to a checkout, one a line (inside its .git, so never
    committed and gone with the checkout)."""
    return checkout / ".git" / "romtg-applied-patches.txt"


def apply_patches(checkout: Path, patches: Path) -> None:
    """Apply numbered *.patch files in order; skip ones already applied.

    Applied patches are written down in the checkout. Testing a patch in reverse can't tell on
    its own: once a later patch changes the same lines (0059 edits DoomLink.as, which 0002
    created), the earlier one no longer reverses cleanly, and setup tried to apply 0002 again
    (Ryan, 2026-11-17)."""
    files = sorted(patches.glob("*.patch"))
    if not files:
        info(f"no patches in {patches.name}/")
        return
    record = applied_record(checkout)
    done = set(record.read_text(encoding="utf-8").split()) if record.exists() else set()

    def check(*extra: str) -> bool:
        return subprocess.run(["git", "-C", str(checkout), "apply", "--check", *extra, str(patch)],
                              capture_output=True).returncode == 0

    for patch in files:
        if patch.name in done:
            ok(f"{patch.name} already applied")
            continue
        if check("--whitespace=nowarn"):
            run(["git", "-C", str(checkout), "apply", "--whitespace=nowarn", str(patch)])
            ok(f"applied {patch.name}")
        elif check("--reverse"):
            ok(f"{patch.name} already applied")
        else:
            raise SetupError(f"{patch.name} doesn't apply to {checkout.name}/ (edited by hand, or a patch "
                             f"before it changed). Re-run with --force to start {checkout.name}/ fresh")
        done.add(patch.name)
        record.write_text("\n".join(sorted(done)) + "\n", encoding="utf-8")


def cmd_port(args) -> bool:
    pin = VERSIONS["port"]
    step(f"Clone {pin['name']} {pin.get('tag', '')}")
    clone_pinned(pin["repo"], pin["commit"], port_dir(), args.force)
    if not (port_dir() / "CMakeLists.txt").exists():
        return False

    step("Apply port-patches")
    apply_patches(port_dir(), REPO / "port-patches")

    step("Build (CMake + Visual Studio 2022, x64)")
    build = port_build_dir()
    run(["cmake", "-S", str(port_dir()), "-B", str(build), "-G", "Visual Studio 17 2022", "-A", "x64",
             "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"])
    run(["cmake", "--build", str(build), "--config", PORT_BUILD_TYPE, "--parallel"])
    if not port_exe().exists():
        raise SetupError(f"build finished but {port_exe()} is missing")
    ok(f"built {port_exe()}")
    return True


def mod_pk3() -> Path:
    return REPO / "build" / "romtg-doom.pk3"


def cmd_build_mod(args) -> bool:
    """Zip doom-mod/, the generated map and RotMG's pictures (scripts/assets.py) into build/romtg-doom.pk3."""
    import zipfile
    step("Build doom-mod")
    src, out = REPO / "doom-mod", mod_pk3()
    out.parent.mkdir(parents=True, exist_ok=True)
    sources = [(p, p.relative_to(src)) for p in src.rglob("*")
               if p.is_file() and p.suffix != ".pk3" and p.name != "README.md"]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import assets
    import flatmap
    # RotMG's tiles and objects as sprites (build/sprites, build/zscript, build/romtg-assets.json).
    counts = assets.build()
    ok(f"RotMG pictures: {counts['pictures']} ({counts['grounds']} grounds, {counts['objects']} objects)")
    for folder in ("sprites", "zscript"):
        made = REPO / "build" / folder
        if made.is_dir():
            sources += [(p, Path(folder) / p.relative_to(made)) for p in made.rglob("*") if p.is_file()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as pk3:
        for path, name in sorted(sources, key=lambda s: s[1].as_posix()):
            pk3.write(path, name.as_posix())
        pk3.writestr(f"maps/{flatmap.MAP_NAME}.wad", flatmap.wad())
        pk3.writestr("textures/RTBLACK.png", flatmap.black_png())
        pk3.writestr("textures/RTWHITE.png", flatmap.white_png())
    ok(f"{out} ({len(sources) + 3} files, map {flatmap.MAP_NAME})")
    return True


# Straight into the mod's flat map: no startup screen (-nostartup), no title, no new game or
# difficulty menus (+map starts the map at once, -skill picks the difficulty), no autosave.
# No status bar (screenblocks 12): the RotMG side panel has your HP, MP and gear. A crosshair
# to aim RotMG shots by.
DOOM_START_ARGS = ["-nostartup", "-skill", "3", "+map", "ROMTG", "+disableautosave", "2",
                   "+screenblocks", "12", "+crosshair", "1"]


def cmd_run_doom(args) -> bool:
    """Start UZDoom on the IWAD with the mod, logging the console to logs/uzdoom.log."""
    step("Run UZDoom")
    iwad = find_iwad()
    if not iwad:
        raise SetupError("no IWAD found; set DOOM_IWAD in .env or put one in reference/doom")
    if not port_exe().exists():
        raise SetupError("UZDoom not built yet; run `setup.py port`")
    if not cmd_build_mod(args):
        return False
    log = REPO / "logs" / "uzdoom.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    # -stdout makes UZDoom write its console to stdout, which we save to the log
    # (+logfile is unreliable when started from a script).
    cmd = [str(port_exe()), "-iwad", str(iwad), "-file", str(mod_pk3()), "-stdout", *DOOM_START_ARGS,
           *(args.extra or [])]
    info("$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    with log.open("w", encoding="utf-8") as out:
        code = subprocess.run(cmd, cwd=port_exe().parent, stdout=out, stderr=subprocess.STDOUT).returncode
    loaded = "[romtg] doom-mod loaded" in log.read_text(encoding="utf-8", errors="replace")
    (ok if loaded else warn)(f"doom-mod {'loaded' if loaded else 'load line not found'}; console log in {log}")
    return code == 0 and loaded


# ---------------------------------------------------------------- RotMG server (TKR) + client

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def tkr_server() -> Path:
    return server_dir() / "TK-Server"


def tkr_bin(project: str) -> Path:
    return tkr_server() / project / "bin" / "Release" / VERSIONS["server"].get("dotnet", "net8.0")


def redis_ok(host: str = "127.0.0.1", port: int = 6379) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=2) as sock:
            sock.sendall(b"PING\r\n")
            return sock.recv(16).startswith(b"+PONG")
    except OSError:
        return False


def check_local_only() -> None:
    """Refuse to run if a server config points anywhere but this PC."""
    for project, name in [("TKR.App", "server.json"), ("TKR.WorldServer", "wServer.json")]:
        cfg = json.loads((tkr_server() / project / name).read_text(encoding="utf-8-sig"))
        hosts = [cfg["dbInfo"]["host"], cfg["serverInfo"].get("address", "127.0.0.1")]
        if any(h not in LOOPBACK for h in hosts):
            raise SetupError(f"{project}/{name} points at {hosts}; only localhost is allowed")


def cmd_server(args) -> bool:
    """Clone TKR into server/, apply server-patches, build the App and WorldServer (Release)."""
    pin = VERSIONS["server"]
    step(f"Clone {pin['name']}")
    clone_pinned(pin["repo"], pin["commit"], server_dir(), args.force)
    if not (tkr_server() / "TKR.sln").exists():
        return False
    step("Apply server-patches")
    apply_patches(server_dir(), REPO / "server-patches")
    check_local_only()
    pet_data()
    step("Build (dotnet, Release)")
    run(["dotnet", "build", str(tkr_server() / "TKR.sln"), "-c", "Release", "-nologo", "-v", "minimal"])
    for project in ("TKR.App", "TKR.WorldServer"):
        exe = tkr_bin(project) / f"{project}.exe"
        if not exe.exists():
            raise SetupError(f"build finished but {exe} is missing")
        ok(f"built {exe}")
    (ok if redis_ok() else warn)("Redis/Memurai on 127.0.0.1:6379" + ("" if redis_ok() else
                                 " not answering; start the Memurai service before run-server"))
    return True


def rebuild_server_if_stale() -> None:
    """play: the server's C# changed since it was built (a fix landed while it was running, so
    it couldn't be rebuilt then): rebuilt first, so play never runs an old server."""
    dll = tkr_bin("TKR.WorldServer") / "TKR.WorldServer.dll"
    if not dll.exists():
        return
    built = dll.stat().st_mtime
    newer = [p for p in tkr_server().rglob("*.cs") if "obj" not in p.parts and "bin" not in p.parts
             and p.stat().st_mtime > built]
    if not newer:
        return
    step(f"Rebuild the server ({len(newer)} source files changed since its last build)")
    run(["dotnet", "build", str(tkr_server() / "TKR.sln"), "-c", "Release", "-nologo", "-v", "minimal"])


def cmd_run_server(args) -> bool:
    """Start the TKR App (accounts, :2000) and WorldServer (game, :2002) in their own consoles."""
    step("Run TKR server (localhost only)")
    if not redis_ok():
        raise SetupError("Redis/Memurai not answering on 127.0.0.1:6379; start the Memurai service")
    check_local_only()
    import socket
    for project, port in (("TKR.WorldServer", 2002), ("TKR.App", 2000)):
        exe = tkr_bin(project) / f"{project}.exe"
        if not exe.exists():
            raise SetupError(f"{exe} missing; run `setup.py server`")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            ok(f"{project} already running on port {port}; not starting another")
            continue
        except OSError:
            pass
        # cmd /k keeps the window open if the server crashes, so the error stays readable
        # TKR targets .NET 8; roll forward lets it run on a newer installed runtime (e.g. 10)
        # when the .NET 8 / ASP.NET Core 8 runtime isn't installed.
        env = {**os.environ, "DOTNET_ROLL_FORWARD": os.environ.get("DOTNET_ROLL_FORWARD", "Major")}
        subprocess.Popen(["cmd", "/k", str(exe)], cwd=exe.parent, env=env,
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        ok(f"started {project}")
    info("account server http://127.0.0.1:2000, game server 127.0.0.1:2002; close their windows to stop")
    return True


def client_dir() -> Path:
    return reference_dir() / "rotmg" / "client"


def find_air_sdk() -> Path | None:
    if ENV.get("ROMTGDOOM_AIR_SDK"):
        path = Path(ENV["ROMTGDOOM_AIR_SDK"])
        return path if (path / "bin").is_dir() else None
    for path in sorted((workspace() / "tools").glob("AIRSDK*"), reverse=True):
        if (path / "bin" / "amxmlc.bat").exists() or (path / "bin" / "amxmlc").exists():
            return path
    return None


def air_sdk_version(sdk: Path) -> str | None:
    """'51.5' from air-sdk-description.xml (major.minor is what descriptors use)."""
    desc = sdk / "air-sdk-description.xml"
    if not desc.exists():
        return None
    match = re.search(r"<version>(\d+\.\d+)", desc.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else None


def air_tool(sdk: Path, name: str) -> str:
    for candidate in (sdk / "bin" / f"{name}.bat", sdk / "bin" / f"{name}.exe", sdk / "bin" / name):
        if candidate.exists():
            return str(candidate)
    raise SetupError(f"{name} not found in {sdk / 'bin'}")


def pet_data() -> None:
    """RotMG's pets (server-patches/0004 and 0005): their data, built from the NR client's files
    by scripts/pets.py into the server's resources and the client's assets (never committed)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pets
    msg = pets.ensure()
    (ok if msg.startswith("RotMG pets") else warn)(msg)
    import dungeons
    msg = dungeons.ensure()
    (ok if msg.startswith("dungeon maps") else warn)(msg)


def cmd_client(args) -> bool:
    """Compile TKR's TK-Client (same commit as the server) into reference/rotmg/client."""
    step("Build TK-Client (AIR)")
    src = server_dir() / "TK-Client"
    if not (src / "src" / "WebMain.as").exists():
        raise SetupError("server/TK-Client missing; run `setup.py server` first")
    params = (src / "src/com/company/assembleegameclient/parameters/Parameters.as").read_text(encoding="utf-8")
    local = (src / "src/kabam/rotmg/application/impl/LocalhostSetup.as").read_text(encoding="utf-8")
    if "LOCAL_HOST:Boolean = true" not in params or '"http://127.0.0.1:2000"' not in local:
        raise SetupError("TK-Client is not set to localhost-only; refusing to build it")
    sdk = find_air_sdk()
    if not sdk:
        raise SetupError("Harman AIR SDK not found; extract it to <workspace>/tools/AIRSDK_<version> "
                         "or set ROMTGDOOM_AIR_SDK in .env")
    # server-patches also carry the client's changes (the Doom button); idempotent.
    apply_patches(server_dir(), REPO / "server-patches")
    pet_data()
    out = client_dir()
    (out / "assets").mkdir(parents=True, exist_ok=True)
    run([air_tool(sdk, "amxmlc"), "-source-path+=" + str(src / "src"), "-library-path+=" + str(src / "libs"),
         "-output", str(out / "TK-Client.swf"), str(src / "src" / "WebMain.as")])
    for icon in (src / "src" / "assets").glob("tk-*.png"):
        shutil.copy2(icon, out / "assets" / icon.name)
    descriptor = (src / "WebMain-app.xml").read_text(encoding="utf-8")
    descriptor = descriptor.replace("<content>Content.dll</content>", "<content>TK-Client.swf</content>")
    # Realm of the Mad God's name on the window and in the taskbar, not TK-Client's.
    descriptor = descriptor.replace("<name>TK-Client</name>", "<name>Realm of the Mad God</name>")
    if "<title>" not in descriptor:
        descriptor = descriptor.replace("<initialWindow>", "<initialWindow>\n        <title>Realm of the Mad God</title>")
    # The descriptor's namespace must be at least the SDK version, or adl rejects the newer SWF
    # with "error while loading initial content".
    sdk_version = air_sdk_version(sdk)
    if sdk_version:
        descriptor = re.sub(r"ns\.adobe\.com/air/application/[\d.]+",
                            f"ns.adobe.com/air/application/{sdk_version}", descriptor)
    (out / "TK-Client-app.xml").write_text(descriptor, encoding="utf-8")
    # The title screen's logo and background from your own Exalt install (scripts/exalt.py),
    # loaded by the client at run time (romtg/RealmArt.as); without them it shows the name as text.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import exalt
    art = exalt.export(reference_dir() / "rotmg" / "exalt")
    for name, dest in (("Logo", "realm-logo.png"), ("TitleBackground", "realm-title-bg.png")):
        if name in art:
            shutil.copy2(art[name], out / "assets" / dest)
    (ok if art else warn)(f"Exalt title art: {', '.join(art) if art else 'not found (UnityPy and the game install needed)'}")
    ok(f"client built in {out}")
    return True


def cmd_run_client(args) -> bool:
    """Run the built TK-Client with the AIR debug launcher (adl)."""
    step("Run TK-Client")
    sdk, descriptor = find_air_sdk(), client_dir() / "TK-Client-app.xml"
    if not sdk:
        raise SetupError("Harman AIR SDK not found; see `setup.py client`")
    if not descriptor.exists():
        raise SetupError("client not built yet; run `setup.py client`")
    run([air_tool(sdk, "adl"), str(descriptor), str(client_dir())], cwd=client_dir())
    return True


# Doom keeps running and drawing while RotMG has the focus (UZDoom pauses and stops drawing in
# the background by default) but stays quiet while hidden, and starts windowed so duo.py can
# place it.
# OpenGL, not Vulkan, by default (ROMTGDOOM_DOOM_BACKEND=1 for Vulkan): RotMG's HUD is a
# see-through window over Doom, and see-through windows over a windowed Vulkan game flicker on
# NVIDIA cards (the HUD's flicker, 2026-11-12; Ryan's is a GTX 1080).
DOOM_DUO_ARGS = ["+vid_fullscreen", "0", "+i_pauseinbackground", "0", "+i_soundinbackground", "0",
                 "+vid_activeinbackground", "1", "+vid_lowerinbackground", "0",
                 "+vid_preferbackend", os.environ.get("ROMTGDOOM_DOOM_BACKEND", "0"),
                 "+vid_fps", "1",   # frame rate top right (Ryan, 2026-11-13); vid_fps 0 in the console hides it
                 # Doom's own chat (T) took the keyboard and only Esc, which the swapper keeps
                 # from Doom, closes it: you were stuck (Ryan, 2026-11-15). No Doom chat.
                 "+unbind", "t"]


def wait_port(port: int, seconds: float) -> bool:
    import socket
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return True
        except OSError:
            time.sleep(1)
    return False


def cmd_play(args) -> bool:
    """Server, both games, then duo.py: RotMG in front with Doom running hidden; ~ (or the Doom
    button in RotMG's side panel) brings Doom up with RotMG's side menu on the right, and back.
    Extra arguments go to duo.py (--key, --minimap, --side, --start)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import duo
    rebuild_server_if_stale()
    if not cmd_run_server(args):
        return False
    step("Wait for the server")
    if not wait_port(2000, 90):
        raise SetupError("the account server never opened port 2000; check its console window")
    ok("account server is up")
    step("Start both games")
    iwad, sdk, descriptor = find_iwad(), find_air_sdk(), client_dir() / "TK-Client-app.xml"
    if not iwad:
        raise SetupError("no IWAD found; set DOOM_IWAD in .env or put one in reference/doom")
    if not port_exe().exists():
        raise SetupError("UZDoom not built yet; run `setup.py port`")
    if not sdk or not descriptor.exists():
        raise SetupError("RotMG client not built yet; run `setup.py client`")
    if not cmd_build_mod(args):
        return False
    log = REPO / "logs" / "uzdoom.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    doom_out = log.open("w", encoding="utf-8")
    doom = subprocess.Popen([str(port_exe()), "-iwad", str(iwad), "-file", str(mod_pk3()), "-stdout",
                             *DOOM_START_ARGS, *DOOM_DUO_ARGS], cwd=port_exe().parent, stdout=doom_out, stderr=subprocess.STDOUT)
    ok(f"started UZDoom (console in {log})")
    client = subprocess.Popen([air_tool(sdk, "adl"), str(descriptor), str(client_dir())], cwd=client_dir())
    ok("started the RotMG client")
    step("Doom + RotMG on one screen")
    try:
        code = duo.main(args.extra or [])
    finally:
        doom_out.close()
    info("swapper stopped; anything still open (after Ctrl+C or one game closing) you close yourself")
    del doom, client
    return code == 0


COMMANDS = {"play": cmd_play, "doctor": cmd_doctor, "references": cmd_references, "port": cmd_port,
            "build-mod": cmd_build_mod, "run-doom": cmd_run_doom,
            "server": cmd_server, "run-server": cmd_run_server,
            "client": cmd_client, "run-client": cmd_run_client}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--force", action="store_true", help="redo a step that already ran")
    parser.add_argument("extra", nargs=argparse.REMAINDER, help="run-doom: extra UZDoom arguments")
    args = parser.parse_args()
    try:
        return 0 if COMMANDS[args.command](args) else 1
    except SetupError as error:
        fail(str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())

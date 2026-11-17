"""Start Server.exe of the friend demo (scripts/friend/build_demo.py packages it): the demo's own
database (redis, port 6380, its data in redis/), then the TKR account server (port 2000) and
game server (port 2002), as three tabs of one Windows Terminal window (a window each without
it). Close that window to stop the server.

    <folder>/Start Server.exe
    <folder>/redis/       redis-server.exe, demo.conf, the database file
    <folder>/app/         TKR.App (accounts, :2000)
    <folder>/world/       TKR.WorldServer (the game, :2002)
    <folder>/resources/   the game's data
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REDIS_PORT = 6380


def home() -> Path:
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def answering(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return True
    except OSError:
        return False


WINDOW = "romtg-demo-server"   # Windows Terminal window the three run in, one tab each


def terminal() -> str | None:
    """Windows Terminal (wt.exe), if this PC has it (Windows 11 does)."""
    import shutil
    found = shutil.which("wt")
    if found:
        return found
    app = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "wt.exe"
    return str(app) if app.exists() else None


def console(args: list[str], cwd: Path, title: str, env: dict | None = None) -> None:
    """ARGS running in a tab of their own in one Windows Terminal window (Ryan, 2026-11-16:
    the three as tabs, not three windows), or a window of its own without Windows Terminal.
    cmd /k keeps it open if it stops, so an error stays readable."""
    print(f"starting {title}")
    wt = terminal()
    if wt:
        # The tab may open in a Windows Terminal already running, which doesn't get ENV: set
        # in the tab's own cmd instead. Programs by name, run in their folder (-d).
        line = [Path(args[0]).name, *args[1:]]
        if env and env.get("DOTNET_ROLL_FORWARD"):
            line = ["set", f"DOTNET_ROLL_FORWARD={env['DOTNET_ROLL_FORWARD']}&&", *line]
        subprocess.Popen([wt, "-w", WINDOW, "new-tab", "--title", title, "--suppressApplicationTitle",
                          "-d", str(cwd), "cmd", "/k", *line])
        time.sleep(1.5)   # one tab at a time, in order (the first opens the window)
        return
    subprocess.Popen(["cmd", "/k", *args], cwd=cwd, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)


def main() -> int:
    base = home()
    print("Realm of the Mad God + Doom: friend demo server")
    for port in (2000, 2002):
        if answering(port):
            print(f"Something is already using port {port} (a server already running?). Close it first.")
            input("Press Enter to close this window.")
            return 1
    if not answering(REDIS_PORT):
        console([str(base / "redis" / "redis-server.exe"), "demo.conf"], base / "redis", "Database")
        for _ in range(30):
            if answering(REDIS_PORT):
                break
            time.sleep(0.5)
    if not answering(REDIS_PORT):
        print("The database didn't start; see its window.")
        input("Press Enter to close this window.")
        return 1
    # TKR targets .NET 8; roll forward runs it on a newer installed .NET too.
    env = {**os.environ, "DOTNET_ROLL_FORWARD": "Major"}
    console([str(base / "world" / "TKR.WorldServer.exe")], base / "world", "Game server", env)
    console([str(base / "app" / "TKR.App.exe")], base / "app", "Account server", env)
    print("Started: database (6380, this PC only), account server (2000), game server (2002).")
    print("Friends need TCP ports 2000 and 2002 forwarded to this PC.")
    print("To stop the server, close its window (all three tabs).")
    time.sleep(8)
    return 0


if __name__ == "__main__":
    sys.exit(main())

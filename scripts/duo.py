#!/usr/bin/env python3
"""Doom and RotMG on one screen. RotMG starts in front and Doom runs hidden; the swap key (or
the Doom button in RotMG's side panel) brings Doom up, with RotMG's side menu down the right
edge, and back again.

Same idea as rimworld-mw2's minimap (RimView.cs): the other game's own window is placed over
the main one, borderless and kept on top without taking the focus, so it is that game itself
at its own speed rather than a copy. Here a small outside program does it to both windows.

The swap keys (tilde ~ and Scroll Lock by default) are caught with a low-level keyboard hook and
swallowed while either game is in front, so neither game sees them. F10 there closes both games
and the TKR server (for testing).

It also runs the bridge (bridge.py) that carries the realm from the RotMG client to Doom and
Doom's movement back; the Doom button in RotMG's side panel arrives over it as `swap`.

Usage (both games already running):
    python scripts/duo.py [--key tilde,scrolllock] [--minimap menu|corner] [--side 0.4] [--start rotmg|doom]
`setup.py play` starts the server and both games, then runs this.
"""
from __future__ import annotations

import argparse
import math
import traceback
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def _sig(fn, res, *args):
    fn.restype, fn.argtypes = res, list(args)


H, I, U, B = wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.BOOL
_sig(user32.SetWindowsHookExW, wintypes.HHOOK, I, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
_sig(user32.CallNextHookEx, LRESULT, wintypes.HHOOK, I, wintypes.WPARAM, wintypes.LPARAM)
_sig(user32.UnhookWindowsHookEx, B, wintypes.HHOOK)
_sig(user32.EnumWindows, B, ENUMPROC, wintypes.LPARAM)
_sig(user32.GetWindowThreadProcessId, wintypes.DWORD, H, ctypes.POINTER(wintypes.DWORD))
_sig(user32.IsWindowVisible, B, H)
_sig(user32.IsWindow, B, H)
_sig(user32.IsIconic, B, H)
_sig(user32.GetClassNameW, I, H, wintypes.LPWSTR, I)
_sig(user32.GetWindowRect, B, H, ctypes.POINTER(wintypes.RECT))
_sig(user32.GetForegroundWindow, H)
_sig(user32.SetForegroundWindow, B, H)
_sig(user32.BringWindowToTop, B, H)
_sig(user32.SetFocus, H, H)
_sig(user32.ShowWindow, B, H, I)
_sig(user32.GetWindowLongPtrW, ctypes.c_ssize_t, H, I)
_sig(user32.SetWindowLongPtrW, ctypes.c_ssize_t, H, I, ctypes.c_ssize_t)
_sig(user32.SetWindowPos, B, H, H, I, I, I, I, U)
_sig(user32.AttachThreadInput, B, wintypes.DWORD, wintypes.DWORD, B)
_sig(user32.MonitorFromWindow, wintypes.HMONITOR, H, wintypes.DWORD)
_sig(user32.GetMonitorInfoW, B, wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
_sig(user32.PeekMessageW, B, ctypes.POINTER(wintypes.MSG), H, U, U, U)
_sig(user32.TranslateMessage, B, ctypes.POINTER(wintypes.MSG))
_sig(user32.DispatchMessageW, LRESULT, ctypes.POINTER(wintypes.MSG))
_sig(user32.keybd_event, None, wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t)
_sig(user32.SetWindowRgn, I, H, wintypes.HANDLE, B)


class THUMB_PROPS(ctypes.Structure):
    _fields_ = [("dwFlags", wintypes.DWORD), ("rcDestination", wintypes.RECT), ("rcSource", wintypes.RECT),
                ("opacity", ctypes.c_ubyte), ("fVisible", B), ("fSourceClientAreaOnly", B)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", I), ("cbWndExtra", I),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


dwmapi = ctypes.WinDLL("dwmapi")
_sig(dwmapi.DwmRegisterThumbnail, ctypes.c_long, H, H, ctypes.POINTER(ctypes.c_void_p))
_sig(dwmapi.DwmUnregisterThumbnail, ctypes.c_long, ctypes.c_void_p)
_sig(dwmapi.DwmUpdateThumbnailProperties, ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(THUMB_PROPS))
_sig(user32.DefWindowProcW, LRESULT, H, U, wintypes.WPARAM, wintypes.LPARAM)
_sig(user32.RegisterClassW, wintypes.ATOM, ctypes.POINTER(WNDCLASSW))
_sig(user32.CreateWindowExW, H, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
     I, I, I, I, H, wintypes.HANDLE, wintypes.HINSTANCE, ctypes.c_void_p)
_sig(user32.DestroyWindow, B, H)
_sig(user32.GetWindow, H, H, U)
_sig(user32.GetWindowTextW, I, H, wintypes.LPWSTR, I)
_sig(ctypes.windll.gdi32.CombineRgn, I, wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, I)
_sig(ctypes.windll.gdi32.DeleteObject, B, wintypes.HANDLE)
_sig(ctypes.windll.gdi32.GetStockObject, wintypes.HANDLE, I)
_sig(ctypes.windll.gdi32.CreateRectRgn, wintypes.HANDLE, I, I, I, I)
_sig(ctypes.windll.gdi32.CreateCompatibleDC, wintypes.HDC, wintypes.HDC)
_sig(ctypes.windll.gdi32.DeleteDC, B, wintypes.HDC)
_sig(ctypes.windll.gdi32.SelectObject, wintypes.HANDLE, wintypes.HDC, wintypes.HANDLE)
_sig(ctypes.windll.gdi32.CreateDIBSection, wintypes.HANDLE, wintypes.HDC, ctypes.c_void_p, U,
     ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
_sig(user32.PrintWindow, B, H, wintypes.HDC, U)
_sig(user32.SetCursorPos, B, I, I)
_sig(kernel32.GetCurrentThreadId, wintypes.DWORD)
_sig(kernel32.OpenProcess, wintypes.HANDLE, wintypes.DWORD, B, wintypes.DWORD)
_sig(kernel32.CloseHandle, B, wintypes.HANDLE)
_sig(kernel32.QueryFullProcessImageNameW, B, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
     ctypes.POINTER(wintypes.DWORD))

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_POPUP, WS_VISIBLE, WS_CLIPSIBLINGS = 0x80000000, 0x10000000, 0x04000000
WS_FRAME = 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000  # caption, sizing, menus
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_APPWINDOW = 0x8, 0x80, 0x08000000, 0x40000
WS_EX_TRANSPARENT = 0x20
HWND_TOP, HWND_TOPMOST, HWND_NOTOPMOST = H(0), H(-1), H(-2)
SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW, SWP_NOMOVE, SWP_NOSIZE = 0x10, 0x20, 0x40, 0x2, 0x1
SWP_NOZORDER = 0x4
SW_RESTORE, SW_SHOWNOACTIVATE, SW_HIDE = 9, 4, 0
WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN = 13, 0x100, 0x104
PM_REMOVE, VK_MENU, KEYEVENTF_KEYUP = 1, 0x12, 2

# Keys: names the user can pass to --key. Neither game binds these by default.
KEYS = {"tilde": 0xC0, "f10": 0x79, "f12": 0x7B, "scrolllock": 0x91, "pause": 0x13, "insert": 0x2D, "f13": 0x7C, "f14": 0x7D, "f15": 0x7E,
        "numlock": 0x90, "rctrl": 0xA3, "apps": 0x5D}

GIVE_BACK_AFTER = 0.15  # the minimap may hold the focus this long before the main game gets it back
PLACE_EVERY = 0.5       # seconds between checks that both windows are where they should be
ELSEWHERE_AFTER = 1.0   # another program in front this long: the minimap stops floating over it
HUD_SHARE = 200 / 800   # RotMG's side panel is the right 200 of its 800-wide stage
# RotMG's minimap, in its 800x600 stage: the side panel's map at (604, 4), 192 square. In Doom the
# real game view is shown there instead (a live DWM thumbnail of RotMG's play area).
MINIMAP = (604 / 800, 4 / 600, 192 / 600)
PLAY_AREA = 600 / 800   # the play area is the left 600 of the stage, all 600 high: a square

# RotMG keys you can press in Doom: Windows key -> RotMG's binding name (Parameters.data_). The
# client presses whatever key you bound to that name, so your RotMG bindings still decide.
ACTIONS = {0x46: "useHealthPotion",   # F
           0x56: "useMagicPotion",    # V
           0x52: "escapeToNexus",     # R: recall to the nexus
           0x0D: "interact"}          # Enter: enter a portal, open a bag...
# Held keys: pressed in RotMG for as long as you hold them (camera turning, as in RotMG, so the
# side panel's live view turns with it). Q and E, RotMG's own keys for it.
HELD_ACTIONS = {0x20: "useSpecial",    # Space: your ability, aimed where you look; held, as the
                                    # ninja's star needs (thrown on release; Ryan 2026-11-17)
                0x51: "rotateLeft",    # Q
                0x45: "rotateRight"}   # E
for _slot in range(8):
    ACTIONS[0x31 + _slot] = f"useInvSlot{_slot + 1}"   # 1-8: inventory slots
AUTO_SWAP_SPAN = 6.0   # seconds: more than three swaps the game asks for in this long is a loop
# Which of those follow RotMG's own key bindings (its Options, sent as `binds`): the press
# kind and the held kind. Enter stays an interact key in Doom whatever RotMG's is (Doom has no
# chat to take it).
PRESS_BINDS = ("useHealthPotion", "useMagicPotion", "escapeToNexus", "interact") + tuple(f"useInvSlot{i}" for i in range(1, 9))
HELD_BINDS = ("useSpecial", "rotateLeft", "rotateRight")


def apply_binds(binds: dict, vks: set, quit_vks: set) -> None:
    """RotMG's key bindings (bridge.binds) for the keys taken in Doom, and its swap and close
    keys (romtgSwap, romtgQuit, in RotMG's Options; Ryan 2026-11-18). Changes ACTIONS,
    HELD_ACTIONS and the hook's key sets in place."""
    kept = {0x1B, VK_TAB}   # Esc (RotMG's options) and Tab (the side panel) stay as they are
    press = {vk: name for name in PRESS_BINDS if 0 < (vk := binds.get(name, 0)) < 256 and vk not in kept}
    held = {vk: name for name in HELD_BINDS if 0 < (vk := binds.get(name, 0)) < 256 and vk not in kept}
    if not press and not held:
        return
    press.setdefault(0x0D, "interact")
    for vk in held:
        press.pop(vk, None)
    ACTIONS.clear()
    ACTIONS.update(press)
    HELD_ACTIONS.clear()
    HELD_ACTIONS.update(held)
    swap = binds.get("romtgSwap", 0)
    if 0 < swap < 256:
        vks.clear()
        vks.update({swap, KEYS["scrolllock"]})   # Scroll Lock always swaps too
    camera = binds.get("romtgCamera", 0)
    if 0 < camera < 256:
        CAMERA_VKS.clear()
        CAMERA_VKS.add(camera)
        press.pop(camera, None)
        held.pop(camera, None)
        ACTIONS.pop(camera, None)
        HELD_ACTIONS.pop(camera, None)
    quit_key = binds.get("romtgQuit", 0)
    if quit_vks and 0 < quit_key < 256:   # (left off when started with --quit-key none)
        quit_vks.clear()
        quit_vks.add(quit_key)
    log(f"keys from RotMG's options: swap {sorted(hex(v) for v in vks)}, close {sorted(hex(v) for v in quit_vks)}, "
        + ", ".join(f"{n} {v:#x}" for v, n in sorted({**ACTIONS, **HELD_ACTIONS}.items())))


# In Doom: first / third person (RotMG's Options, romtgCamera; C by default, Ryan 2026-11-20).
CAMERA_VKS = {0x43}


VK_TAB = 0x09   # in Doom: let go of Doom so the mouse can use RotMG's side panel; Tab again to return


_LOG_FILE = None


def log(msg: str) -> None:
    """To the console and to logs/duo.log (started afresh each run), so a run can be looked at
    afterwards."""
    global _LOG_FILE
    print(f"[duo] {msg}", flush=True)
    try:
        if _LOG_FILE is None:
            # ROMTG_HOME: the friend demo's folder (scripts/friend_play.py), else this repo.
            home = os.environ.get("ROMTG_HOME")
            path = (Path(home) if home else Path(__file__).resolve().parent.parent) / "logs" / "duo.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            _LOG_FILE = path.open("w", encoding="utf-8")
        _LOG_FILE.write(time.strftime('%H:%M:%S') + " " + msg + "\n")
        _LOG_FILE.flush()
    except OSError:
        pass


def exe_of(hwnd) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)


HUD_TITLE = "RomtgHud"   # RotMG's HUD over Doom (romtg/HudWindow.as): a window of the client's own


def title_of(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def find_hud():
    """RotMG's HUD window, while it's up."""
    found = []

    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd) and title_of(hwnd) == HUD_TITLE and exe_of(hwnd) in ("adl.exe", "tk-client.exe"):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(ENUMPROC(visit), 0)
    return found[0] if found else None


def class_of(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def rect_of(hwnd) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def find_window(exes: tuple[str, ...], klass: str | None = None):
    """The biggest visible top-level window of a process named one of `exes`."""
    best, best_area = None, 0

    def visit(hwnd, _):
        nonlocal best, best_area
        if not user32.IsWindowVisible(hwnd) or exe_of(hwnd) not in exes or title_of(hwnd) == HUD_TITLE:
            return True
        if klass and class_of(hwnd) != klass:
            return True
        _, _, w, h = rect_of(hwnd)
        if w * h > best_area:
            best, best_area = hwnd, w * h
        return True

    user32.EnumWindows(ENUMPROC(visit), 0)
    return best


def monitor_rect(hwnd) -> tuple[int, int, int, int]:
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))  # MONITOR_DEFAULTTONEAREST
    m = info.rcMonitor
    return m.left, m.top, m.right - m.left, m.bottom - m.top


def take_focus(hwnd) -> bool:
    """Bring `hwnd` to the front with the keyboard. Windows only lets the foreground thread hand
    the focus on, so we join its input queue for a moment (and, if that is refused, tap Alt,
    which Windows counts as us having the last input)."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    front = user32.GetForegroundWindow()
    if front == hwnd:
        return True
    ours = kernel32.GetCurrentThreadId()
    theirs = user32.GetWindowThreadProcessId(front, None) if front else 0
    joined = bool(theirs) and theirs != ours and user32.AttachThreadInput(ours, theirs, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        if joined:
            user32.AttachThreadInput(ours, theirs, False)
    if user32.GetForegroundWindow() != hwnd:
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.SetForegroundWindow(hwnd)
    return user32.GetForegroundWindow() == hwnd


_noted: dict[str, float] = {}
_counts: dict[str, int] = {}


def note(key: str, msg: str, every: float = 5.0) -> None:
    """Something the swapper keeps having to redo (a window moved back, a restack): counted,
    and said at most every `every` seconds, so a fight with a game shows in the log."""
    _counts[key] = _counts.get(key, 0) + 1
    now = time.monotonic()
    if now - _noted.get(key, -1e9) >= every:
        _noted[key] = now
        log(f"{msg} ({_counts[key]} times so far)")


def near(a, b, slack: int = 3) -> bool:
    return all(abs(i - j) <= slack for i, j in zip(a, b))


def is_below(upper, lower, look: int = 400) -> bool:
    """Whether `lower` is under `upper` in the window stack (within `look` windows)."""
    hwnd = upper
    for _ in range(look):
        hwnd = user32.GetWindow(hwnd, 2)   # GW_HWNDNEXT: the next window down
        if not hwnd:
            return False
        if hwnd == lower:
            return True
    return False


CIRCLE_MISS = ""      # why find_circle last gave up (logged)
CIRCLE_VOTES = 9      # looks the corner view's circle is the median of
CIRCLE_EVERY = 2.0    # seconds between looks at where RotMG's circle of ground is


def longest_run(line):
    """First and last index of the longest run of True in a 1-D array, small gaps bridged."""
    import numpy as np
    # Gaps of a few pixels (a dark tile, a shadow) don't break a run.
    line = np.convolve(line.astype(np.float32), np.ones(15, np.float32) / 15, "same") > 0.3
    padded = np.concatenate(([False], line, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    if len(edges) < 2:
        return 0, -1
    starts, ends = edges[0::2], edges[1::2]
    i = int(np.argmax(ends - starts))
    return int(starts[i]), int(ends[i]) - 1


def find_circle(hwnd, rw: int, h: int):
    """Where RotMG's circle of ground is in its window (it draws only the squares within 15
    tiles of you; black round them): (middle x, middle y, radius) in window pixels, from a
    picture of the window; None if it can't tell (the circle fills the play area, or too dark
    to see). Looked at, not worked out: the client's own sums missed (it draws on the GPU)."""
    global CIRCLE_MISS
    try:
        import numpy as np
    except ImportError:
        CIRCLE_MISS = "no numpy"
        return None
    w = round(PLAY_AREA * rw)
    if w < 50 or h < 50:
        return None
    gdi = ctypes.windll.gdi32

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    dc = gdi.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    bmi = BMI(ctypes.sizeof(BMI), rw, -h, 1, 32, 0, 0, 0, 0, 0, 0)   # top-down
    bmp = gdi.CreateDIBSection(dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    try:
        if not bmp or not bits.value:
            CIRCLE_MISS = "no bitmap"
            return None
        old = gdi.SelectObject(dc, bmp)
        ok = user32.PrintWindow(hwnd, dc, 2)   # PW_RENDERFULLCONTENT: GPU-drawn windows too
        gdi.SelectObject(dc, old)
        if not ok:
            CIRCLE_MISS = "PrintWindow failed"
            return None
        img = np.ctypeslib.as_array((ctypes.c_uint8 * (rw * h * 4)).from_address(bits.value)).reshape(h, rw, 4)
        lit = img[:, :w, :3].max(axis=2) > 16
    finally:
        if bmp:
            gdi.DeleteObject(bmp)
        gdi.DeleteDC(dc)
    # A circle's chord through a column (row) is 2 sqrt(r^2 - d^2): longer than half the
    # longest chord exactly where d < r sqrt(3)/2. So the columns with more than half the
    # most lit pixels give the middle and the radius, and the odd lit thing outside the circle
    # (chat, names, a background that isn't pure black) can't reach half.
    k = math.sqrt(3) / 2
    colsum, rowsum = lit.sum(axis=0), lit.sum(axis=1)
    if colsum.max() < 0.1 * h:
        CIRCLE_MISS = "the picture is all black"
        return None
    cols = np.nonzero(colsum > colsum.max() / 2)[0]
    rows = np.nonzero(rowsum > rowsum.max() / 2)[0]
    left, right, top, bottom = cols[0], cols[-1], rows[0], rows[-1]
    if left <= 2 and right >= w - 3:
        CIRCLE_MISS = "no black at the sides"
        return None   # nothing to cut
    r = (right - left) / 2 / k
    cx = (left + right) / 2
    cy = (top + bottom) / 2 if top > 2 and bottom < h - 3 else (top + r * k if top > 2 else bottom - r * k)
    # Then refined along the lines through the middle: the longest unbroken lit run down the
    # middle column and across the middle row (anything else lit is in other runs).
    for _ in range(2):
        c = min(w - 1, max(0, int(round(cx))))
        t, b = longest_run(lit[:, c])
        row = min(h - 1, max(0, int(round(cy))))
        lft, rgt = longest_run(lit[row, :])
        if rgt - lft < 10 or b - t < 10:
            break
        r = (rgt - lft) / 2
        cx = (lft + rgt) / 2
        if t > 2 and b < h - 3:
            cy = (t + b) / 2
            r = max(r, (b - t) / 2)
        elif t > 2:
            cy = t + r
        elif b < h - 3:
            cy = b - r
    if not 0.15 * h < r < 0.75 * h:
        CIRCLE_MISS = f"odd size: columns {left}-{right}, rows {top}-{bottom} of {w}x{h}"
        return None
    return float(cx), float(cy), float(r)


def view_square(view, rw: int, h: int) -> tuple[int, int, int, int]:
    """The part of RotMG's window the corner view shows: the square inside RotMG's circle of
    ground round you (VIEW from the client: its middle and radius in 800x600 units), so none
    of the black round the circle shows (Ryan, 2026-11-13); the whole play area until the
    client has said where the circle is."""
    if not view:
        return (0, 0, round(PLAY_AREA * rw), h)
    cx, cy, r = view[0], view[1], view[2] / math.sqrt(2) * 0.97   # VIEW in window pixels
    return (round(cx - r), round(cy - r), round(cx + r), round(cy + r))


class Thumbnail:
    """Our own small window showing a live, scaled copy of part of another window (DWM draws it),
    used in Doom to show RotMG's real play area where its minimap is."""

    def __init__(self, source):
        self.source = source
        self._proc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
        cls = WNDCLASSW(lpfnWndProc=self._proc, lpszClassName="RomtgThumb",
                        hbrBackground=ctypes.windll.gdi32.GetStockObject(4))  # BLACK_BRUSH
        user32.RegisterClassW(ctypes.byref(cls))
        self.hwnd = user32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "RomtgThumb",
                                           "RotMG", WS_POPUP, 0, 0, 1, 1, None, None, None, None)
        self.thumb = ctypes.c_void_p()
        if not self.hwnd or dwmapi.DwmRegisterThumbnail(self.hwnd, source, ctypes.byref(self.thumb)) != 0:
            log("couldn't make the RotMG view for Doom's minimap; the plain minimap stays")
            self.thumb = None
        self.at = None

    def show(self, x: int, y: int, side: int, src: tuple[int, int, int, int]) -> None:
        if not self.thumb:
            return
        if self.at != (x, y, side, src):
            self.at = (x, y, side, src)
            props = THUMB_PROPS(dwFlags=0x1 | 0x2 | 0x4 | 0x8 | 0x10, opacity=255, fVisible=True,
                                fSourceClientAreaOnly=False)
            props.rcDestination = wintypes.RECT(0, 0, side, side)
            props.rcSource = wintypes.RECT(*src)
            dwmapi.DwmUpdateThumbnailProperties(self.thumb, ctypes.byref(props))
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, side, side, SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def hide(self) -> None:
        if self.hwnd and user32.IsWindowVisible(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_HIDE)

    def close(self) -> None:
        if self.thumb:
            dwmapi.DwmUnregisterThumbnail(self.thumb)
            self.thumb = None
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None


class Game:
    def __init__(self, name: str, hwnd, aspect: float | None):
        self.name, self.hwnd, self.aspect = name, hwnd, aspect
        self.style = self.long(GWL_STYLE)
        self.exstyle = self.long(GWL_EXSTYLE)
        self.rect = rect_of(hwnd)
        self.region = None

    def clip(self, region) -> None:
        """Show only the rectangle (x, y, w, h), or a list of them, of the window, in its own
        coordinates; None shows all of it. Clicks outside the shown part go to the window behind."""
        if isinstance(region, tuple):
            region = [region]
        if region == self.region:
            return
        self.region = region
        rgn = None
        for x, y, w, h in region or []:
            part = ctypes.windll.gdi32.CreateRectRgn(x, y, x + w, y + h)
            if rgn is None:
                rgn = part
            else:
                ctypes.windll.gdi32.CombineRgn(rgn, rgn, part, 2)   # RGN_OR
                ctypes.windll.gdi32.DeleteObject(part)
        user32.SetWindowRgn(self.hwnd, rgn, True)  # Windows owns the region from here

    def long(self, index: int) -> int:
        """A window style as the unsigned 32 bits it is (Windows sign-extends WS_POPUP)."""
        return user32.GetWindowLongPtrW(self.hwnd, index) & 0xFFFFFFFF

    def alive(self) -> bool:
        return bool(user32.IsWindow(self.hwnd))

    def place(self, x: int, y: int, w: int, h: int, overlay: bool, on_top: bool, force: bool = False,
              below=None) -> bool:
        """Borderless at (x, y, w, h); as the minimap also a tool window that won't take focus.
        Kept above the taskbar while `on_top`. True if the window was moved or restacked."""
        style = (self.style & ~WS_FRAME) | WS_POPUP | WS_VISIBLE | WS_CLIPSIBLINGS
        # Not WS_EX_WINDOWEDGE (0x100): Windows takes it off a borderless window again at once, so
        # asking for it had both games' styles re-set, with a frame recalculation, every half
        # second (logs/duo.log, 2026-11-12: hundreds of times a minute); Doom's occasional flicker.
        ex = self.exstyle & ~(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_APPWINDOW | 0x100)
        ex |= (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) if overlay else WS_EX_APPWINDOW
        changed = False
        if self.long(GWL_STYLE) != style:
            note(f"style-{self.name}", f"{self.name}'s window style was {self.long(GWL_STYLE):#x}, setting {style:#x}")
            user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, style)
            changed = True
        if self.long(GWL_EXSTYLE) & ~(WS_EX_TOPMOST | 0x100) != ex:
            note(f"exstyle-{self.name}", f"{self.name}'s window ex-style was {self.long(GWL_EXSTYLE):#x}, setting {ex:#x}")
            user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex)
            changed = True
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            changed = True
        topmost_now = bool(self.long(GWL_EXSTYLE) & WS_EX_TOPMOST)
        # Both games go above the taskbar while ours are in front: Doom, shortened by the side
        # menu, no longer covers the whole screen, so Windows stopped hiding the taskbar for it.
        want_top = on_top
        at = rect_of(self.hwnd)
        if not changed and not force and near(at, (x, y, w, h)) and topmost_now == want_top:
            return False
        if not changed and not force and not near(at, (x, y, w, h)):
            note(f"move-{self.name}", f"{self.name}'s window was at {at}, putting it back at {(x, y, w, h)}")
        after = HWND_TOPMOST if want_top else HWND_NOTOPMOST
        if below is not None and want_top:
            after = below   # straight under that window, in the topmost band with it
        flags = SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
        if topmost_now == want_top and not force:
            # Already in the right band: moved, sized or restyled only. Its place in the stack is
            # the restack's business: re-inserting it at the top (HWND_TOPMOST) put Doom over the
            # HUD whenever a game reset its own window style, until the next restack.
            flags |= SWP_NOZORDER
        user32.SetWindowPos(self.hwnd, after, x, y, w, h, flags)
        return True

    def hide(self) -> None:
        """Out of sight but still running (the game keeps its own loop going)."""
        if user32.IsWindowVisible(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_HIDE)

    def restore(self) -> None:
        if not self.alive():
            return
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.clip(None)
        user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, self.style)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, self.exstyle & ~WS_EX_TOPMOST)
        x, y, w, h = self.rect
        user32.SetWindowPos(self.hwnd, HWND_NOTOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_FRAMECHANGED)


class Duo:
    def __init__(self, doom: Game, rotmg: Game, side: float, start: str, minimap: str = "menu"):
        self.games = {"doom": doom, "rotmg": rotmg}
        self.minimap = minimap
        self.main = start
        self.side = side
        self.swap_wanted = False
        self.focus_wanted = True
        self.minimap_focused_at = -1.0
        self.elsewhere_since = -1.0
        self.on_top = True
        self.last_place = 0.0
        self.bridge = None   # bridge.Bridge: the RotMG client <-> Doom link, and the Doom button
        self.thumb = Thumbnail(rotmg.hwnd) if minimap == "menu" else None
        self.modal = False       # a RotMG dialog is open (set_modal)
        self.out_of_game_from_doom = False   # set_ingame took you out of Doom
        self.options_from_doom = False       # set_options took you out of Doom
        self.dialog_centre = None   # last `dlgcx` sent
        self.drag_button = False    # the left button was down (watch_drop)
        self.auto_swaps: list[float] = []   # when the game swapped by itself (auto_swap)
        self.auto_held = False
        self.modal_panel = False # ...and it switched on Tab
        self.hud_ok = False      # told the client its HUD window is in place ("hudok")
        self.circle = None       # RotMG's circle of ground (find_circle), for the corner view
        self.circle_at = -1e9
        self.circle_size = None
        self.circle_votes: list[float] = []
        self.actions: list[str] = []   # RotMG keys pressed in Doom, from the keyboard hook
        # Tab in Doom: Doom stays on screen but RotMG has the keyboard and mouse, for its side
        # panel (inventory, trading...). Tab in RotMG, or a click on Doom, goes back.
        self.panel = False
        self.panel_wanted: bool | None = None
        self.hud = None
        self.hud_looked = 0.0
        self.hud_placed = None    # (hwnd, rect) the HUD window was last put at
        self.hud_fixed_at = -1e9  # when it was last put back after moving off that

    @property
    def mini(self) -> str:
        return "rotmg" if self.main == "doom" else "doom"

    def layout(self, force: bool = False) -> None:
        main, mini = self.games[self.main], self.games[self.mini]
        # Every loop while the HUD window waits to be put over Doom, so gold and fame show at once.
        waiting = (self.main == "doom" and self.minimap == "menu" and not self.hud_ok
                   and self.on_top and self.hud_window() is not None)
        if not (force or waiting or time.monotonic() - self.last_place >= PLACE_EVERY):
            return
        self.last_place = time.monotonic()
        x, y, w, h = monitor_rect(main.hwnd)
        if self.mini == "doom":
            # In RotMG: RotMG whole, and Doom only shows once you swap into it; until then it
            # runs hidden.
            main.clip(None)
            main.place(x, y, w, h, overlay=False, on_top=self.on_top)
            mini.hide()
            if self.thumb:
                self.thumb.hide()
        elif self.minimap == "menu":
            # In Doom: RotMG's side panel (its stats, gear and inventory) down the right edge at
            # full height, and Doom in the rest. RotMG's window is a 4:3 the screen's height,
            # pushed right *behind* Doom, so only its panel shows past Doom's right edge, while
            # its play area keeps drawing behind Doom. That play area is shown, live and scaled,
            # where the panel's minimap is (Thumbnail), so the minimap square is RotMG itself.
            # Restacked every PLACE_EVERY so RotMG never ends up over Doom.
            rw = round(h * mini.aspect)
            panel = round(rw * HUD_SHARE)
            rx = x + w - rw
            k = rw / 800   # screen pixels per unit of RotMG's 800x600 stage
            restack = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            main.place(x, y, w - panel, h, overlay=False, on_top=self.on_top)
            # Where the middle of Doom's view is in RotMG's units, for its dialogs (dlgcx).
            centre = round((x + (w - panel) / 2 - rx) / k, 1)
            if self.bridge and centre != self.dialog_centre:
                self.dialog_centre = centre
                self.bridge.to_client(f"dlgcx {centre}")
            hud = self.hud_window()
            if not hud:
                self.hud_ok = False
            if hud and self.on_top:
                # RotMG's own HUD (gold and fame, boss bar, chat, status texts) over Doom:
                # see-through and click-through.
                ex = user32.GetWindowLongPtrW(hud, GWL_EXSTYLE) & 0xFFFFFFFF
                want = ex | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
                if ex != want:
                    note("style-hud", "RotMG's HUD window lost its click-through style; setting it again")
                    user32.SetWindowLongPtrW(hud, GWL_EXSTYLE, want)
                # Placed once (each new HUD window, or when the Doom area changes), not kept being
                # nudged: every move makes AIR resize and redraw the whole see-through window, a
                # flicker if the two ever disagree by a pixel (DPI rounding). Put back only if it
                # really went somewhere else, and at most every 5 s.
                target = (x, y, w - panel, h)
                now = time.monotonic()
                if self.hud_placed != (hud, target):
                    self.hud_placed = (hud, target)
                    user32.SetWindowPos(hud, HWND_TOPMOST, *target, SWP_NOACTIVATE)
                elif not near(rect_of(hud), target, slack=8) and now - self.hud_fixed_at >= 5:
                    self.hud_fixed_at = now
                    note("move-hud", f"RotMG's HUD window was at {rect_of(hud)}, putting it over Doom")
                    user32.SetWindowPos(hud, HWND_TOPMOST, *target, SWP_NOACTIVATE)
                # Its contents (gold, fame...) stay hidden until it's in place (romtg/HudWindow.as).
                if not self.hud_ok and self.bridge and near(rect_of(hud), target, slack=8):
                    self.hud_ok = True
                    self.bridge.to_client("hudok")
            if self.panel:
                # Tab: RotMG over Doom, but cut down to its side panel. Its tooltips show over
                # Doom in RotMG's HUD window (romtg/HudWindow.as draws a copy of them), so
                # RotMG's window never has to reach over Doom. The live minimap is off meanwhile.
                # The side panel; with a dialog open, the dialog too (just it, not the game
                # behind it, Ryan 2026-11-15), moved by the client to the middle of Doom's view.
                shown = [(rw - panel, 0, panel, h)]
                rect = self.bridge.modal_rect if self.modal and self.bridge else None
                if self.modal and rect is None:
                    shown = None   # where it is isn't known yet: all of RotMG
                elif rect:
                    # Its own rectangle, a pixel in: a margin showed RotMG's game round it, the
                    # dialogs' edges not being square (Ryan, 2026-11-18; the client also stops
                    # drawing the game behind it).
                    shown.append((round(rect[0] * k) + 1, round(rect[1] * k) + 1,
                                  max(1, round(rect[2] * k) - 2), max(1, round(rect[3] * k) - 2)))
                # A menu (teleport, player...) opened from the side panel pops up to its left,
                # over Doom: shown too, and clickable (Ryan, 2026-11-15).
                menu = self.bridge.menu_rect if self.bridge else None
                if menu and shown is not None:
                    shown.append((round(menu[0] * k) + 1, round(menu[1] * k) + 1,
                                  max(1, round(menu[2] * k) - 2), max(1, round(menu[3] * k) - 2)))
                mini.clip(shown)
                mini.place(rx, y, rw, h, overlay=False, on_top=self.on_top)
                if self.on_top:
                    self.restack([hud, mini.hwnd, main.hwnd])
                # RotMG's own map (where you've been) in the minimap square, the live view off:
                # Ryan wants the map on Tab (2026-11-13). (A copy of the clipped window was black.)
                if self.thumb:
                    self.thumb.hide()
            else:
                mini.place(rx, y, rw, h, overlay=True, on_top=self.on_top, below=main.hwnd)
                if self.on_top:
                    # RotMG may move in the stack: its HUD window has no owner (checked: GW_OWNER
                    # 0), so it doesn't drag the HUD along.
                    self.restack([hud, main.hwnd, mini.hwnd])
                mini.clip(None)   # only once it's under Doom again (coming back from Tab)
                if self.thumb and self.on_top:
                    side = round(MINIMAP[2] * h)
                    self.thumb.show(rx + round(MINIMAP[0] * rw), y + round(MINIMAP[1] * h), side,
                                    self.view_source(rw, h))
                elif self.thumb:
                    self.thumb.hide()
        else:
            # In Doom: all of RotMG as a minimap in the top left.
            mh = max(150, round(h * self.side))
            moved = main.place(x, y, w, h, overlay=False, on_top=self.on_top)
            mini.clip(None)
            mini.place(x, y, round(mh * mini.aspect), mh, overlay=True, on_top=self.on_top, force=moved)

    def view_source(self, rw: int, h: int) -> tuple[int, int, int, int]:
        """The corner view's part of RotMG's window: inside the circle (find_circle, looked at
        every CIRCLE_EVERY seconds and kept while the window keeps its size)."""
        # The circle never moves on screen (RotMG's camera follows you) and is as wide as the
        # play area (Ryan's log, 2026-11-13: radius 720 of a 1440 play area every time in the
        # realm). Each look only votes for how high its middle is, and the corner shows the
        # median of the last CIRCLE_VOTES good looks: single looks fooled by dark ground, names
        # or chat made the view jump and zoom (2026-11-13).
        now = time.monotonic()
        w = round(PLAY_AREA * rw)
        if self.circle_size != (rw, h):
            self.circle_size = (rw, h)
            self.circle_votes = []
            self.circle = (w / 2, h / 2, w / 2)
            self.circle_at = -1e9
        if now - self.circle_at >= CIRCLE_EVERY:
            self.circle_at = now
            found = find_circle(self.games["rotmg"].hwnd, rw, h)
            if found and abs(found[2] - w / 2) < 0.03 * w and abs(found[0] - w / 2) < 0.03 * w:
                self.circle_votes = (self.circle_votes + [found[1]])[-CIRCLE_VOTES:]
                cy = sorted(self.circle_votes)[len(self.circle_votes) // 2]
                if len(self.circle_votes) >= 3 and abs(cy - self.circle[1]) > 4:
                    self.circle = (w / 2, cy, w / 2)
                    log(f"RotMG's circle of ground: middle ({w / 2:.0f}, {cy:.0f}), radius {w / 2:.0f} px "
                        f"of a {rw}x{h} window ({len(self.circle_votes)} looks)")
            elif not found:
                note("circle-miss", f"couldn't see RotMG's circle of ground: {CIRCLE_MISS}", every=60)
        return view_square(self.circle, rw, h)

    def restack(self, order, keep=()) -> bool:
        """Puts the windows in `order` (top first; None skipped) at the top of the topmost band,
        if they aren't already in that order. Only ever by tucking each one straight under the
        one above it, never by lifting a lower one to the top: lifting Doom to the top, then the
        HUD back over it, showed Doom over the HUD for a frame (the HUD's flicker, 2026-11-12),
        as lifting RotMG did over Doom before it.

        Windows in `keep` (at the end of `order`) are only checked, never moved: they end up under
        the others by the others going to the top. RotMG must never be moved under Doom while
        the HUD is up: the HUD is RotMG's own window (AIR owns it by RotMG's), and Windows keeps
        an owned window right over its owner, so tucking RotMG under Doom dragged the HUD under
        Doom too; the next check lifted it back, twice a second for as long as you were in Doom
        (logs/duo.log, 2026-11-12: 215 restacks in 2 minutes). That was the HUD's flicker."""
        order = [w for w in order if w]
        wrong = [(a, b) for a, b in zip(order, order[1:]) if not is_below(a, b) or self.foreign_between(a, b)]
        over = self.covered(order[0])
        if not wrong and not over:
            return False
        names = {g.hwnd: n for n, g in self.games.items()}
        names[self.hud] = "HUD"
        why = "; ".join(f"{names.get(a, hex(a or 0))} not over {names.get(b, hex(b or 0))}" for a, b in wrong)
        if over:
            why += (" ; " if why else "") + f"{names.get(over, hex(over))} over the {names.get(order[0], 'top')}"
        note("restack", f"restacking the HUD, Doom and RotMG ({why}; above the top: {self.above(order[0])})")
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        user32.SetWindowPos(order[0], HWND_TOPMOST, 0, 0, 0, 0, flags)
        for above, below in zip(order, order[1:]):
            if below in keep:
                break
            user32.SetWindowPos(below, above, 0, 0, 0, 0, flags)
        return True

    def foreign_between(self, upper, lower) -> bool:
        """Whether the taskbar sits between `upper` and `lower`: then `lower` (RotMG's side
        panel) is under it, as it was in the pet yard (2026-11-12). Only the taskbar: other
        programs' always-on-top windows (overlays...) are left alone, not fought over."""
        w = user32.GetWindow(upper, 2)
        buf = ctypes.create_unicode_buffer(64)
        for _ in range(400):
            if not w or w == lower:
                return False
            if user32.IsWindowVisible(w):
                user32.GetClassNameW(w, buf, 64)
                if buf.value in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                    return True
            w = user32.GetWindow(w, 2)
        return False

    def above(self, hwnd, n: int = 3) -> str:
        """The visible windows just above `hwnd`, for the log: "exe 'title'" each."""
        out = []
        w = user32.GetWindow(hwnd, 3)
        for _ in range(200):
            if not w or len(out) >= n:
                break
            if user32.IsWindowVisible(w):
                out.append(f"{exe_of(w)} {title_of(w)!r}")
            w = user32.GetWindow(w, 3)
        return ", ".join(out) or "nothing"

    def covered(self, hwnd):
        """One of our games (or the taskbar) above `hwnd` (the top of our stack), or None."""
        ours = {g.hwnd for g in self.games.values()}
        buf = ctypes.create_unicode_buffer(64)
        w = user32.GetWindow(hwnd, 3)   # GW_HWNDPREV: the next window up
        for _ in range(64):
            if not w:
                return None
            if w in ours:
                return w
            if user32.IsWindowVisible(w):
                user32.GetClassNameW(w, buf, 64)
                if buf.value in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                    return w
            w = user32.GetWindow(w, 3)
        return None

    def focus_doom(self) -> None:
        """Doom gets the keyboard; Windows lifts it to the very top as it does, over the HUD, so
        the HUD goes straight back over it in the same breath."""
        main = self.games["doom"]
        # The mouse pointer off RotMG's side panel, to the middle of Doom: left where it was,
        # RotMG kept seeing it over an item and showed its tooltip ("Empty item slot") over
        # the panel while you played (Ryan, 2026-11-15).
        r = rect_of(main.hwnd)
        if r and r[2] > 0 and r[3] > 0:
            user32.SetCursorPos(r[0] + r[2] // 2, r[1] + r[3] // 2)
        take_focus(main.hwnd)
        if self.main == "doom" and self.minimap == "menu" and self.on_top:
            self.restack([self.hud_window(), main.hwnd])

    def hud_window(self):
        """RotMG's HUD window, found again whenever it's gone (the client makes it in Doom)."""
        # Kept while hidden (the client hides it outside Doom and shows the same window again):
        # back in Doom it's already where it goes, no search, no wait (Ryan, 2026-11-13: the
        # gold and fame took a while to show after a swap).
        if self.hud and user32.IsWindow(self.hud):
            return self.hud if user32.IsWindowVisible(self.hud) else None
        now = time.monotonic()
        if now - self.hud_looked < 0.1:
            return None
        self.hud_looked = now
        self.hud = find_hud()
        if self.hud:
            owner = user32.GetWindow(self.hud, 4)   # GW_OWNER
            who = {g.hwnd: name for name, g in self.games.items()}.get(owner, hex(owner or 0))
            log(f"found RotMG's HUD window; its owner is {who}")
        return self.hud

    def set_panel(self, on: bool) -> None:
        """Tab: RotMG's side panel gets the keyboard and mouse while Doom stays on screen."""
        if self.main != "doom" or on == self.panel:
            return
        if not on and self.modal:
            # A RotMG dialog (potion storage...) is open: it keeps the mouse until it closes;
            # Doom over it left it stuck half on screen (Ryan, 2026-11-15).
            note("modal-keep", "a RotMG dialog is open: staying on it until it closes")
            return
        self.panel = on
        log("RotMG's side panel has the mouse (Tab to go back to Doom)" if on else "back in Doom")
        if self.bridge is not None:
            self.bridge.set_control(not on)
            self.bridge.set_panel(on)
        self.layout(force=True)
        if on:
            take_focus(self.games["rotmg"].hwnd)
        else:
            self.focus_doom()
        self.layout(force=True)   # focusing RotMG lifts it: put it back under Doom at once

    def auto_swap(self, why: str) -> None:
        """A swap the game asked for (its options or a menu came up or went, you left or
        entered a game), not you. If those keep coming back and forth (four in AUTO_SWAP_SPAN
        seconds), they stop until you swap yourself: a friend's screen flickered between the two
        for good, only a restart fixed it (2026-11-18)."""
        now = time.monotonic()
        self.auto_swaps = [t for t in self.auto_swaps if now - t < AUTO_SWAP_SPAN]
        if self.auto_held:
            return
        if len(self.auto_swaps) >= 3:
            self.auto_held = True
            log(f"the game keeps swapping by itself ({why}): held until you swap (the swap key or Doom button)")
            return
        self.auto_swaps.append(now)
        self.swap()

    def set_options(self, up: bool) -> None:
        """RotMG's options screen (Esc, or the side panel's wrench) opened or closed. It covers
        RotMG's play area, behind Doom: RotMG comes up full screen for it, and Doom comes back
        when it closes (Ryan, 2026-11-15)."""
        if up and self.main == "doom":
            log("RotMG's options opened: showing RotMG")
            self.options_from_doom = True
            self.auto_swap("options")
            self.focus_wanted = True
        elif not up and self.options_from_doom:
            self.options_from_doom = False
            if self.main == "rotmg":
                log("RotMG's options closed: back to Doom")
                self.auto_swap("options")
                self.focus_wanted = True

    def go_home(self) -> None:
        """"Back to home" in RotMG's options: out of Doom for good, to RotMG's menus (not back
        to Doom when the options close, nor when you next enter a game)."""
        log("back to home: RotMG's menus, Doom stays down")
        self.options_from_doom = False
        self.out_of_game_from_doom = False
        if self.main == "doom":
            self.swap()
            self.focus_wanted = True

    def set_ingame(self, ingame: bool) -> None:
        """You left the game for RotMG's menus (character select, the death screen...) or came
        back. Out of a game in Doom, RotMG comes up full screen (nothing in Doom works then);
        back in a game, Doom again if that's where you were (Ryan, 2026-11-15)."""
        if not ingame and self.main == "doom":
            log("left the game for RotMG's menus: showing RotMG")
            self.out_of_game_from_doom = True
            self.auto_swap("in or out of a game")
            self.focus_wanted = True
        elif ingame and self.out_of_game_from_doom:
            self.out_of_game_from_doom = False
            if self.main == "rotmg":
                log("back in a game: back to Doom")
                self.auto_swap("in or out of a game")
                self.focus_wanted = True

    def set_modal(self, on: bool) -> None:
        """A RotMG dialog (the potion storage...) opened or closed. It opens in RotMG's play
        area, behind Doom: while it's open, all of RotMG is shown over Doom with the mouse, as
        Tab but not cut down to the side panel; when it closes, back to Doom if it took you
        out of it (Ryan, 2026-11-15)."""
        if on == self.modal:
            self.layout(force=True)   # it moved (the client centres it): show it where it is now
            return
        self.modal = on
        self.dialog_centre = None     # tell the client where Doom's middle is again
        log("a RotMG dialog opened: showing RotMG over Doom" if on else "the RotMG dialog closed")
        if on and self.main == "doom" and not self.panel:
            self.modal_panel = True
            self.set_panel(True)
        elif not on and self.modal_panel:
            self.modal_panel = False
            self.set_panel(False)
        self.layout(force=True)

    def swap(self) -> None:
        if self.panel and self.bridge is not None:
            self.bridge.set_panel(False)
        self.panel = False
        self.main = self.mini
        where = "its side menu on the right" if self.minimap == "menu" else "a minimap top left"
        log(f"doom fills the screen, rotmg is {where}" if self.main == "doom"
            else "rotmg fills the screen, doom is hidden")
        self.layout(force=True)
        self.focus_wanted = True
        if self.bridge is not None:
            self.bridge.set_control(self.main == "doom")
            self.bridge.set_view(self.main == "doom")

    def watch_drop(self) -> None:
        """An item dragged off RotMG's side panel (`drag 1`) and let go over Doom: the release
        goes to Doom's window, not RotMG's, so RotMG is told (`dragdrop`) and drops it on the
        ground, into a bag, as letting go over its own ground does. Doom stays on screen
        (Ryan, 2026-11-16: not RotMG over most of the screen while dragging)."""
        down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)   # VK_LBUTTON
        was = self.drag_button
        self.drag_button = down
        if not (was and not down) or not self.bridge.dragging or self.main != "doom":
            return
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        x, y, w, h = rect_of(self.games["doom"].hwnd)
        if x <= pt.x < x + w and y <= pt.y < y + h:
            log("an item let go over Doom: dropped on the ground")
            self.bridge.to_client("dragdrop")

    def tick(self) -> None:
        now = time.monotonic()
        if self.bridge is not None:
            while self.actions:
                self.bridge.act(self.actions.pop(0))
            # (the bridge polls on its own thread: Bridge.start)
            if self.bridge.modal_changed:
                self.bridge.modal_changed = False
                self.set_modal(self.bridge.modal)
            self.watch_drop()
            if self.bridge.home_requested:
                self.bridge.home_requested = False
                self.go_home()
            if self.bridge.options_changed:
                self.bridge.options_changed = False
                self.set_options(self.bridge.options)
            if self.bridge.menu_changed:
                self.bridge.menu_changed = False
                self.layout(force=True)   # show (or stop showing) the menu over Doom at once
            if self.bridge.ingame_changed:
                self.bridge.ingame_changed = False
                self.set_ingame(self.bridge.ingame)
            if self.bridge.swap_requested:   # the Doom button
                self.bridge.swap_requested = False
                log("RotMG's Doom button: swapping")
                self.swap_wanted = True
        if self.swap_wanted:
            self.swap_wanted = False
            if self.auto_held:
                log("you swapped: the game's own swaps are back on")
            self.auto_held = False
            self.auto_swaps = []
            if self.main == "rotmg" and self.bridge and (self.bridge.options or self.bridge.modal):
                # Not into Doom while RotMG's options or a dialog is up: close it first.
                note("cover-keep", "RotMG's options or a dialog is open: close it before going back to Doom")
            else:
                self.swap()
        if self.panel_wanted is not None:
            self.set_panel(self.panel_wanted)
            self.panel_wanted = None
        main, mini = self.games[self.main], self.games[self.mini]
        if self.focus_wanted:
            if self.main == "doom":
                r = rect_of(main.hwnd)   # the pointer off RotMG's panel (see focus_doom)
                if r[2] > 0 and r[3] > 0:
                    user32.SetCursorPos(r[0] + r[2] // 2, r[1] + r[3] // 2)
            self.focus_wanted = not take_focus(main.hwnd)
        front = user32.GetForegroundWindow()
        if self.panel and front == main.hwnd:
            self.set_panel(False)   # clicked back into Doom
        # The minimap took the focus (a click on it, or the game raising itself): give it back,
        # as RimView does, unless the swap key or Tab asked for it.
        if (self.main == "doom" and self.minimap == "menu" and not self.panel and self.on_top
                and front == main.hwnd and not is_below(main.hwnd, mini.hwnd)):
            # RotMG got over Doom without the focus (it raises its window now and then, at some
            # spots in the nexus: "the game flickers", 2026-11-12): back under at once, not at
            # the next half-second layout.
            note("rotmg-raised", "RotMG rose over Doom; putting it back under")
            self.restack([self.hud_window(), main.hwnd, mini.hwnd])
        if front == mini.hwnd and not self.panel and self.main == "doom":
            # RotMG raised itself over Doom (it does on a new map: walking into a realm portal,
            # 2026-11-12, "it tabs out for a second and tabs in"). Straight back under Doom and
            # the HUD, at once rather than at the next layout.
            note("rotmg-focus", "RotMG took the focus in Doom; putting Doom back over it")
            self.layout(force=True)
            self.focus_doom()
            self.minimap_focused_at = -1.0
        elif front == mini.hwnd and not self.panel:
            if self.minimap_focused_at < 0:
                self.minimap_focused_at = now
            elif now - self.minimap_focused_at >= GIVE_BACK_AFTER:
                self.minimap_focused_at = -1.0
                take_focus(main.hwnd)
        else:
            self.minimap_focused_at = -1.0
        # Another program in front for a while: stop floating the minimap over it.
        if front and front == self.hud:
            note("hud-focus", "RotMG's HUD window took the focus; giving it back")
            self.focus_doom() if self.main == "doom" else take_focus(main.hwnd)   # never the HUD
            front = user32.GetForegroundWindow()
        ours = front in (main.hwnd, mini.hwnd) or not front or (self.thumb is not None and front == self.thumb.hwnd)
        if ours:
            self.elsewhere_since = -1.0
            if not self.on_top:
                self.on_top = True
                self.layout(force=True)
        elif self.elsewhere_since < 0:
            self.elsewhere_since = now
        elif self.on_top and now - self.elsewhere_since >= ELSEWHERE_AFTER:
            self.on_top = False
            self.layout(force=True)
        if ours:
            self.layout()


def wait_for(name: str, exes: tuple[str, ...], klass: str | None, timeout: float):
    log(f"waiting for the {name} window ({', '.join(exes)})")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hwnd = find_window(exes, klass)
        if hwnd:
            return hwnd
        time.sleep(0.5)
    return None


def pid_of(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def close_everything(game_pids: list[int]) -> None:
    """The quit key: both games, then the TKR server and the consoles it runs in. For testing,
    so it doesn't ask: the processes are ended outright."""
    import subprocess
    quiet = {"capture_output": True, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    for pid in game_pids:
        if pid:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], **quiet)
    log("closed Doom and RotMG")
    if os.environ.get("ROMTG_HOME"):
        return   # the friend demo: the server isn't ours to close (it may be the host's own)
    # setup.py run-server starts each server as `cmd /k TKR.<name>.exe`, which keeps the console
    # open after the server ends; those consoles go too.
    script = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'cmd.exe' -and $_.CommandLine "
              r"-match 'TKR\.(App|WorldServer)\.exe' } | ForEach-Object { $_.ProcessId }")
    found = subprocess.run(["powershell", "-NoProfile", "-Command", script], text=True, **quiet).stdout.split()
    for pid in found:
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], **quiet)
    for exe in ("TKR.WorldServer.exe", "TKR.App.exe"):
        subprocess.run(["taskkill", "/F", "/IM", exe], **quiet)
    log(f"closed the server ({len(found)} console window{'s' if len(found) != 1 else ''})")


def run(key: str = "tilde,scrolllock", side: float = 0.4, start: str = "rotmg", timeout: float = 90.0,
        minimap: str = "menu", quit_key: str = "f10") -> int:
    if sys.platform != "win32":
        log("Windows only")
        return 1
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: real pixels
    except (AttributeError, OSError):
        pass
    names = [k.strip().lower() for k in key.split(",") if k.strip()]
    vks = {KEYS.get(k) or int(k, 0) for k in names}
    quit_vks = set() if quit_key.lower() == "none" else {KEYS.get(quit_key.lower()) or int(quit_key, 0)}
    quit_wanted = []
    doom_hwnd = wait_for("Doom", ("uzdoom.exe",), "MainWindow", timeout)
    doom_shown = None
    if doom_hwnd and start == "rotmg":
        # Out of sight at once, not after RotMG's window shows up.
        doom_shown = (user32.GetWindowLongPtrW(doom_hwnd, GWL_STYLE), rect_of(doom_hwnd))
        user32.ShowWindow(doom_hwnd, SW_HIDE)
    rotmg_hwnd = wait_for("RotMG", ("adl.exe", "tk-client.exe"), None, timeout)
    if not doom_hwnd or not rotmg_hwnd:
        if doom_hwnd:
            user32.ShowWindow(doom_hwnd, SW_SHOWNOACTIVATE)
        log("a game window never showed up; is it running?")
        return 1
    # The RotMG client stretches its 800x600 stage to the window, so its minimap stays 4:3;
    # Doom draws at any shape, so its minimap takes the screen's.
    doom = Game("doom", doom_hwnd, None)
    if doom_shown:
        doom.style = doom_shown[0] & 0xFFFFFFFF | WS_VISIBLE
        doom.rect = doom_shown[1]
    duo = Duo(doom, Game("rotmg", rotmg_hwnd, 4 / 3), side, start, minimap)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import bridge
    from pathlib import Path
    assets = os.environ.get("ROMTG_ASSETS")   # the friend demo's copy (scripts/friend_play.py)
    duo.bridge = bridge.Bridge(Path(assets) if assets else Path(__file__).resolve().parent.parent / "build" / "romtg-assets.json")
    duo.bridge.set_control(start == "doom")
    duo.bridge.set_view(start == "doom")
    duo.bridge.start()

    def hook(code, wparam, lparam):
        if code == 0:
            kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            # Only while one of the two games is in front: the key is left alone in other programs.
            front = user32.GetForegroundWindow()
            down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            if (kb.vkCode in vks or kb.vkCode in quit_vks) and front in (doom_hwnd, rotmg_hwnd):
                if down:
                    if kb.vkCode in quit_vks:
                        quit_wanted.append(True)
                    elif kb.vkCode not in held:
                        duo.swap_wanted = True
                        log(f"swap key ({kb.vkCode:#x})")
                    held.add(kb.vkCode)
                else:
                    held.discard(kb.vkCode)
                return 1  # swallowed: neither game sees the key
            # Esc in Doom: kept from Doom (its menu would pause it, but the realm doesn't pause,
            # Ryan 2026-11-12); it opens RotMG's options instead, which come up over Doom
            # (set_options; Ryan, 2026-11-15).
            if kb.vkCode == 0x1B and front == doom_hwnd and duo.main == "doom":
                if down and kb.vkCode not in held:
                    duo.actions.append("options")
                if down:
                    held.add(kb.vkCode)
                else:
                    held.discard(kb.vkCode)
                return 1
            # Tab while Doom is up: Doom <-> RotMG's side panel.
            if kb.vkCode == VK_TAB and duo.main == "doom" and front in (doom_hwnd, rotmg_hwnd):
                if down and kb.vkCode not in held:
                    duo.panel_wanted = front == doom_hwnd
                if down:
                    held.add(kb.vkCode)
                else:
                    held.discard(kb.vkCode)
                return 1
            # The camera key in Doom: first <-> third person (Doom's own camera, via the bridge).
            if kb.vkCode in CAMERA_VKS and front == doom_hwnd and duo.main == "doom":
                if down and kb.vkCode not in held:
                    duo.actions.append("camera")
                if down:
                    held.add(kb.vkCode)
                else:
                    held.discard(kb.vkCode)
                return 1
            # RotMG's held keys while you're in Doom: down on press, up on release.
            if kb.vkCode in HELD_ACTIONS and front == doom_hwnd and duo.main == "doom":
                if down and kb.vkCode not in held:
                    duo.actions.append(HELD_ACTIONS[kb.vkCode] + ":down")
                    held.add(kb.vkCode)
                elif not down and kb.vkCode in held:
                    duo.actions.append(HELD_ACTIONS[kb.vkCode] + ":up")
                    held.discard(kb.vkCode)
                return 1
            # RotMG's keys while you're in Doom: to RotMG, not Doom. Once per press, not on repeat.
            if kb.vkCode in ACTIONS and front == doom_hwnd and duo.main == "doom":
                if down and kb.vkCode not in held:
                    duo.actions.append(ACTIONS[kb.vkCode])
                if down:
                    held.add(kb.vkCode)
                else:
                    held.discard(kb.vkCode)
                return 1
            # Let go of a held key after leaving Doom (Space held as you swapped): forgotten, or
            # its next press in Doom never went through. The client already ended it on `ctl 0`.
            if not down:
                held.discard(kb.vkCode)
        return user32.CallNextHookEx(None, code, wparam, lparam)

    held: set[int] = set()
    proc = HOOKPROC(hook)
    handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
    if not handle:
        log(f"could not hook the keyboard (error {ctypes.get_last_error()})")
        return 1
    log(f"{start} fills the screen; press {' or '.join(names)} (or RotMG's Doom button) to swap"
        + (f", {quit_key} to close both games and the server" if quit_vks else "")
        + ". Ctrl+C here stops only the swapper.")
    duo.layout(force=True)
    msg = wintypes.MSG()
    binds_seen = 0
    try:
        failures = 0
        while all(g.alive() for g in duo.games.values()) and not quit_wanted:
            # The keyboard hook is called from inside PeekMessage. Our own window (the minimap
            # view) gets real messages too, which must be dispatched: a WM_PAINT taken but not
            # handled comes straight back, and the old `while PeekMessage: pass` spun on it for
            # ever (2026-11-12: ~, F10 and the bridge all stopped once Doom came up).
            for _ in range(200):
                if not user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            try:
                duo.tick()
                if duo.bridge is not None and duo.bridge.binds_seq != binds_seen:
                    binds_seen = duo.bridge.binds_seq
                    apply_binds(duo.bridge.binds, vks, quit_vks)
                failures = 0
            except Exception:   # keep the swapper (and so ~ and F10) alive; say what broke
                failures += 1
                if failures <= 3 or failures % 500 == 0:
                    log("error (the swapper keeps going):\n" + traceback.format_exc())
            time.sleep(0.01)
        if not quit_wanted:
            # One game closed (you quit RotMG from its menus, or closed Doom): the rest goes
            # too, as with the quit key (Ryan, 2026-11-15: backing out should close everything).
            log("a game closed: closing everything")
            quit_wanted.append(True)
    except KeyboardInterrupt:
        pass
    finally:
        user32.UnhookWindowsHookEx(handle)
        if duo.bridge is not None:
            duo.bridge.close()
        if duo.thumb is not None:
            duo.thumb.close()
        if quit_wanted:
            close_everything([pid_of(doom_hwnd), pid_of(rotmg_hwnd)])
        else:
            for game in duo.games.values():
                game.restore()
            log("windows put back")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key", default=os.environ.get("ROMTGDOOM_SWAP_KEY", "tilde,scrolllock"),
                        help=f"swap keys, comma-separated: {', '.join(KEYS)} or virtual-key codes like 0x91")
    parser.add_argument("--quit-key", default=os.environ.get("ROMTGDOOM_QUIT_KEY", "f10"),
                        help="closes both games and the server (for testing); 'none' turns it off")
    parser.add_argument("--minimap", choices=("menu", "corner"), default="menu",
                        help="RotMG while in Doom: its side menu down the right (menu) or all of it top left (corner)")
    parser.add_argument("--side", type=float, default=0.4, help="minimap height, as a share of the screen's")
    parser.add_argument("--start", choices=("doom", "rotmg"), default="rotmg", help="which game fills the screen first")
    parser.add_argument("--timeout", type=float, default=90.0, help="seconds to wait for the game windows")
    args = parser.parse_args(argv)
    return run(args.key, args.side, args.start, args.timeout, args.minimap, args.quit_key)


if __name__ == "__main__":
    sys.exit(main())

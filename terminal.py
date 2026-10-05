import os
import sys

BOLD = "\033[1m"
RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BG_GREEN = "\033[42m"


def enable_windows_ansi():
    # เปิดให้ CMD และ PowerShell แสดงรหัสสี ANSI ได้ โดยใช้ไลบรารีที่มากับ Python
    import ctypes
    from ctypes import wintypes

    try:
        console = ctypes.WinDLL("kernel32", use_last_error=True)
        console.GetStdHandle.argtypes = [wintypes.DWORD]
        console.GetStdHandle.restype = wintypes.HANDLE
        console.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        console.GetConsoleMode.restype = wintypes.BOOL
        console.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        console.SetConsoleMode.restype = wintypes.BOOL

        output_handle = console.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = wintypes.DWORD()
        if not console.GetConsoleMode(output_handle, ctypes.byref(mode)):
            return False
        # เก็บค่าของโหมดเดิม และเปิด processed output (1) กับ ANSI (4)
        return bool(console.SetConsoleMode(output_handle, mode.value | 1 | 4))
    except (AttributeError, OSError):
        return False


def supports_ansi():
    if not sys.stdout.isatty() or os.environ.get("TERM") == "dumb":
        return False
    if os.name != "nt":
        return True
    if enable_windows_ansi():
        return True
    # บาง terminal รองรับ ANSI เอง แม้ไม่ได้ใช้ Windows Console
    return "WT_SESSION" in os.environ or "TERM" in os.environ or "ANSICON" in os.environ


def color_text(text, color="", enabled=False, bold=False):
    text = str(text)
    if not enabled:
        return text
    if bold:
        color = BOLD + color
    return color + text + RESET

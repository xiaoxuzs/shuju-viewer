"""Native folder picker on the API host (local dev: same machine as the browser when using localhost)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class NativeFolderDialogError(RuntimeError):
    """Display or toolkit unavailable (e.g. headless server)."""


def pick_folder_native() -> tuple[str | None, bool]:
    """Open one native folder dialog; blocks until the user confirms or cancels.

    Returns:
        ``(absolute_path, cancelled)``. ``cancelled`` is True when the user dismissed
        the dialog without choosing a folder. ``absolute_path`` is set when a folder
        was chosen.
    """
    tk_res = _try_tk_folder()
    if tk_res is not None:
        return tk_res

    if sys.platform == "darwin":
        p = _ask_mac_osascript()
        if p:
            return str(Path(p).expanduser().resolve()), False
        return None, True

    if sys.platform.startswith("linux"):
        p = _ask_zenity()
        if p:
            return str(Path(p).expanduser().resolve()), False
        return None, True

    raise NativeFolderDialogError(
        "No folder dialog is available (tkinter missing and no OS fallback). Paste the folder path manually."
    )


def _try_tk_folder() -> tuple[str | None, bool] | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    try:
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            chosen = filedialog.askdirectory(mustexist=True, parent=root, title="Choose TopPIC dataset folder")
        except tk.TclError as exc:
            raise NativeFolderDialogError(
                "Tk folder dialog could not open (no display?). Paste the folder path manually."
            ) from exc
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass

    if not chosen:
        return None, True
    return str(Path(chosen).expanduser().resolve()), False


def _ask_mac_osascript() -> str | None:
    r = subprocess.run(
        [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Choose TopPIC dataset folder")',
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip()
    return out or None


def _ask_zenity() -> str | None:
    r = subprocess.run(
        ["zenity", "--file-selection", "--directory", "--title=Choose TopPIC dataset folder"],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip()
    return out or None

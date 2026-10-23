"""Ubuntu desktop integration; file paths never pass through a shell."""

import os
import shutil
import subprocess
from pathlib import Path


def folder_opener():
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None
    if executable := shutil.which("xdg-open"):
        return [executable]
    if executable := shutil.which("gio"):
        return [executable, "open"]
    return None


def open_folder(path: Path):
    command = folder_opener()
    if not command:
        raise OSError("No desktop file opener available")
    subprocess.run([*command, str(path)], check=True, timeout=5, capture_output=True)

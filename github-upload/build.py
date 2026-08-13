"""Build one platform-specific Team Lunch executable with PyInstaller."""

from __future__ import annotations

import subprocess
import shutil
import sys
from pathlib import Path


def main() -> int:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "team-lunch",
        "main.py",
    ]
    result = subprocess.call(command)
    if result == 0:
        destination = Path("dist") / "config.example.json"
        shutil.copy2("config.example.json", destination)
        print(f"Copied example configuration to {destination}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

"""Открывает интерфейс в отдельном окне без вкладок (режим «приложение» у Edge/Chrome),
а если подходящего браузера нет — в обычном браузере по умолчанию."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


def browser_candidates() -> list[Path]:
    found: list[Path] = []
    if sys.platform.startswith("win"):
        roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for root in filter(None, roots):
            found.append(Path(root) / "Microsoft/Edge/Application/msedge.exe")
            found.append(Path(root) / "Google/Chrome/Application/chrome.exe")
    elif sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
            found.append(Path(f"/Applications/{app}.app/Contents/MacOS/{app}"))
    else:
        for name in ("google-chrome", "microsoft-edge", "chromium", "chromium-browser"):
            path = shutil.which(name)
            if path:
                found.append(Path(path))
    return found


def open_ui(url: str, app_window: bool = True) -> str:
    """Возвращает, как открыли: 'app-window' или 'browser'."""
    if app_window:
        for exe in browser_candidates():
            if exe.exists():
                try:
                    subprocess.Popen([str(exe), f"--app={url}", "--window-size=1320,900"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return "app-window"
                except OSError:
                    continue
    webbrowser.open(url)
    return "browser"

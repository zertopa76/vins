"""Точка входа для готового приложения (PyInstaller): двойной щелчок по значку, без консоли.

Из исходников запускайте как раньше: python -m vinparts gui
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path


def _fix_streams() -> None:
    """В режиме «без консоли» у программы нет stdout/stderr; print() не должен её ронять."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _log_path() -> Path:
    from vinparts import config
    folder = config.data_dir(None)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "app.log"


def _show_error(message: str) -> None:
    """Сообщение об ошибке в окне: без консоли иначе его никто не увидит."""
    try:
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "VinPartsHelper", 0x10)
        elif sys.platform == "darwin":
            safe = message.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'display dialog "{safe}" with title "VinPartsHelper" '
                            'buttons {"OK"} with icon stop'], check=False)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    _fix_streams()
    try:
        from vinparts.cli import main as cli_main
        args = sys.argv[1:] or ["gui", "--auto-exit"]
        return cli_main(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:  # noqa: BLE001
        text = traceback.format_exc()
        try:
            log = _log_path()
            log.write_text(text, encoding="utf-8")
            where = f"\n\nПодробности записаны в файл:\n{log}"
        except Exception:  # noqa: BLE001
            where = ""
        _show_error("Программа не смогла запуститься." + where)
        return 1


if __name__ == "__main__":
    sys.exit(main())

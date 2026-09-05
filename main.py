from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from windbridge import __version__
from windbridge.network import get_local_ip
from windbridge.settings import Settings


ROOT = Path(__file__).resolve().parent


def smoke_test() -> int:
    checks = {
        "app": "WindBridge",
        "version": __version__,
        "python": sys.version.split()[0],
        "local_ip": get_local_ip(),
        "web_ui": (ROOT / "web" / "index.html").is_file(),
        "resume_scripts": all((ROOT / "web" / name).is_file() for name in ("transfer.js", "sha256.js")),
        "icon": (ROOT / "assets" / "app_icon.png").is_file(),
    }
    print(json.dumps(checks, ensure_ascii=False))
    return 0 if checks["web_ui"] and checks["resume_scripts"] and checks["icon"] else 1


def send_to_running_app(settings: Settings, paths: list[str]) -> bool:
    body = json.dumps({"paths": paths}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{settings.port}/internal/share",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-WindBridge-Control": settings.control_token},
    )
    for _attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=1.5) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    return False


def create_root():
    try:
        from tkinterdnd2 import TkinterDnD

        return TkinterDnD.Tk()
    except (ImportError, RuntimeError):
        import tkinter as tk

        return tk.Tk()


def main() -> int:
    parser = argparse.ArgumentParser(description="WindBridge 风桥 · 局域网文件与文本传输")
    parser.add_argument("--smoke-test", action="store_true", help="检查运行环境后退出")
    parser.add_argument("--share", nargs="+", metavar="FILE", help="把文件交给正在运行的风桥")
    args = parser.parse_args()
    if args.smoke_test:
        return smoke_test()

    from windbridge.gui import WindBridgeApp

    initial_paths: list[str] = []
    loaded_settings = Settings.load()
    loaded_settings.save()
    if args.share:
        initial_paths = [str(Path(path).expanduser().resolve()) for path in args.share if Path(path).expanduser().is_file()]
        if initial_paths and send_to_running_app(loaded_settings, initial_paths):
            return 0

    root = create_root()
    WindBridgeApp(root, settings=loaded_settings, initial_paths=initial_paths)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

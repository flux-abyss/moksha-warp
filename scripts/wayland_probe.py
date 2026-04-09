#!/usr/bin/env python3

import json
import os
import time
from datetime import datetime
from pathlib import Path

from pywayland.server.display import Display


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "wayland_probe.json"


def main():
    LOG_DIR.mkdir(exist_ok=True)

    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "display_created": False,
        "socket_created": False,
        "socket_name": None,
        "xdg_runtime_dir": os.environ.get("XDG_RUNTIME_DIR"),
        "expected_socket_path": None,
        "wayland_display_env": None,
        "error": None,
    }

    try:
        display = Display()
        report["display_created"] = True

        socket_name = "wayland-warp-0"
        actual_name = display.add_socket(socket_name)

        report["socket_created"] = True
        report["socket_name"] = actual_name
        report["wayland_display_env"] = actual_name
        os.environ["WAYLAND_DISPLAY"] = actual_name

        xdg_runtime_dir = report["xdg_runtime_dir"]
        if xdg_runtime_dir:
            report["expected_socket_path"] = str(Path(xdg_runtime_dir) / actual_name)

        print("\n=== Moksha-Warp Wayland Probe ===\n")
        print("Display created:", report["display_created"])
        print("Socket created:", report["socket_created"])
        print("Socket name:", report["socket_name"])
        print("XDG_RUNTIME_DIR:", report["xdg_runtime_dir"])
        print("Expected socket path:", report["expected_socket_path"])
        print("WAYLAND_DISPLAY:", report["wayland_display_env"])

        with open(LOG_FILE, "w") as f:
            json.dump(report, f, indent=2)

        print("\nReport saved to", LOG_FILE)
        print("\nServer will idle for 30 seconds for client testing...")
        time.sleep(30)

    except Exception as e:
        report["error"] = str(e)
        print("Error:", e)
        with open(LOG_FILE, "w") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()

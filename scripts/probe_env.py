
#!/usr/bin/env python3

import json
import os
import platform
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "env_report.json"

def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            text=True
        )
        return {
            "command": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()
        }
    except Exception as e:
        return {"command": cmd, "error": str(e)}

def test_import(module):
    try:
        __import__(module)
        return {"module": module, "status": "ok"}
    except Exception as e:
        return {"module": module, "status": "error", "error": str(e)}

def detect_session():
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"

def detect_dri():
    dri = Path("/dev/dri")
    if not dri.exists():
        return []
    return [str(p) for p in dri.glob("renderD*")]

def main():
    LOG_DIR.mkdir(exist_ok=True)

    report = {}
    report["timestamp"] = datetime.utcnow().isoformat()
    report["hostname"] = socket.gethostname()
    report["kernel"] = platform.release()
    report["python_version"] = sys.version
    report["session_type"] = detect_session()

    report["python_imports"] = [
        test_import("efl"),
        test_import("efl.evas"),
        test_import("efl.elementary"),
        test_import("pywayland"),
    ]

    report["pkg_config_versions"] = {
        "efl": run_cmd("pkg-config --modversion efl"),
        "evas": run_cmd("pkg-config --modversion evas"),
        "elementary": run_cmd("pkg-config --modversion elementary"),
        "ecore": run_cmd("pkg-config --modversion ecore"),
    }

    report["pkg_config_cflags"] = run_cmd(
        "pkg-config --cflags efl evas elementary ecore"
    )

    report["render_nodes"] = detect_dri()
    report["glxinfo"] = run_cmd("glxinfo -B")
    report["drm_syncobj"] = run_cmd(
        "zgrep CONFIG_DRM_SYNC_OBJ /boot/config-$(uname -r)"
    )

    with open(LOG_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print("\n=== Moksha-Warp Environment Report ===\n")
    print("Host:", report["hostname"])
    print("Kernel:", report["kernel"])
    print("Session:", report["session_type"])

    print("\nPython Imports:")
    for imp in report["python_imports"]:
        print(" ", imp["module"], ":", imp["status"])

    print("\nRender Nodes:")
    for node in report["render_nodes"]:
        print(" ", node)

    print("\nEFL Versions:")
    for k, v in report["pkg_config_versions"].items():
        print(" ", k, ":", v.get("stdout"))

    print("\nReport saved to", LOG_FILE)

if __name__ == "__main__":
    main()

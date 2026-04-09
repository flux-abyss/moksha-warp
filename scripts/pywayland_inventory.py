#!/usr/bin/env python3

import importlib
import inspect
import json
import pkgutil
from pathlib import Path

import pywayland


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "pywayland_inventory.json"


def main():
    LOG_DIR.mkdir(exist_ok=True)

    interesting = ("compositor", "surface", "shm", "xdg", "shell", "registry", "seat", "buffer")
    report = []

    for modinfo in pkgutil.walk_packages(pywayland.__path__, pywayland.__name__ + "."):
        name = modinfo.name
        low = name.lower()
        if not any(k in low for k in interesting):
            continue

        entry = {"module": name, "classes": [], "functions": [], "errors": []}
        try:
            mod = importlib.import_module(name)
            for attr_name in dir(mod):
                try:
                    obj = getattr(mod, attr_name)
                    if inspect.isclass(obj):
                        entry["classes"].append(attr_name)
                    elif inspect.isfunction(obj):
                        entry["functions"].append(attr_name)
                except Exception as e:
                    entry["errors"].append(f"{attr_name}: {e}")
        except Exception as e:
            entry["errors"].append(str(e))

        entry["classes"] = sorted(set(entry["classes"]))
        entry["functions"] = sorted(set(entry["functions"]))
        report.append(entry)

    report = sorted(report, key=lambda x: x["module"])

    print("\n=== Moksha-Warp PyWayland Inventory ===\n")
    for entry in report:
        print(f"[{entry['module']}]")
        if entry["classes"]:
            print("  classes:")
            for c in entry["classes"]:
                print("   -", c)
        if entry["functions"]:
            print("  functions:")
            for f in entry["functions"]:
                print("   -", f)
        if entry["errors"]:
            print("  errors:")
            for e in entry["errors"]:
                print("   -", e)
        print()

    with open(LOG_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print("Report saved to", LOG_FILE)


if __name__ == "__main__":
    main()

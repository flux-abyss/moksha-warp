#!/usr/bin/env python3

import json
from pathlib import Path

import efl.evas as evas_mod
from efl import elementary as elm


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "evas_native_hunt.json"


def hunt_names(obj, label, needles):
    results = []
    for name in dir(obj):
        low = name.lower()
        if any(n in low for n in needles):
            entry = {"name": name}
            try:
                value = getattr(obj, name)
                entry["type"] = str(type(value))
                entry["repr"] = repr(value)[:300]
                entry["callable"] = callable(value)
            except Exception as e:
                entry["error"] = str(e)
            results.append(entry)
    return {"label": label, "results": results}


def main():
    LOG_DIR.mkdir(exist_ok=True)

    needles = (
        "native",
        "surface",
        "engine",
        "gl",
        "wl",
        "x11",
        "buffer",
        "image",
    )

    elm.init()
    win = None

    try:
        win = elm.StandardWindow("hunt", "hunt")
        canvas = win.evas

        report = {
            "evas_module": hunt_names(evas_mod, "evas_module", needles),
            "canvas": hunt_names(canvas, "canvas", needles),
        }

        print("\n=== Moksha-Warp Evas Native Hunt ===\n")
        for section_name in ("evas_module", "canvas"):
            section = report[section_name]
            print(f"[{section['label']}]")
            if not section["results"]:
                print("  <none>")
                continue
            for item in section["results"]:
                line = f"  {item['name']} :: {item.get('type', 'unknown')}"
                if item.get("callable"):
                    line += " :: callable"
                if item.get("error"):
                    line += f" :: error={item['error']}"
                print(line)
            print()

        with open(LOG_FILE, "w") as f:
            json.dump(report, f, indent=2)

        print("Report saved to", LOG_FILE)

    finally:
        if win is not None:
            try:
                win.delete()
            except Exception:
                pass
        elm.shutdown()


if __name__ == "__main__":
    main()

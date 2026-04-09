#!/usr/bin/env python3

import inspect
import json
from pathlib import Path

from efl import elementary as elm
import efl.evas as evas_mod
from efl.evas import FilledImage


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "evas_deep_probe.json"


def safe_signature(obj):
    try:
        return str(inspect.signature(obj))
    except Exception:
        return None


def scan_names(obj, label, keywords):
    result = []
    try:
        for name in dir(obj):
            lower = name.lower()
            if any(k in lower for k in keywords):
                entry = {"name": name}
                try:
                    value = getattr(obj, name)
                    entry["callable"] = callable(value)
                    if callable(value):
                        entry["signature"] = safe_signature(value)
                    else:
                        entry["type"] = str(type(value))
                except Exception as e:
                    entry["error"] = str(e)
                result.append(entry)
    except Exception as e:
        result.append({"scan_error": f"{label}: {e}"})
    return result


def print_section(title, items):
    print(f"\n=== {title} ===\n")
    if not items:
        print("  <none>")
        return
    for item in items:
        if "scan_error" in item:
            print(" ", item["scan_error"])
            continue
        line = f"  {item['name']}"
        if item.get("callable"):
            if item.get("signature"):
                line += item["signature"]
            else:
                line += " (callable)"
        elif item.get("type"):
            line += f" [{item['type']}]"
        if item.get("error"):
            line += f" <error: {item['error']}>"
        print(line)


def main():
    LOG_DIR.mkdir(exist_ok=True)

    keywords = ("native", "surface", "gl", "engine", "image", "dmabuf", "buffer")
    report = {}

    elm.init()
    win = None

    try:
        win = elm.StandardWindow("deep-probe", "Moksha-Warp Deep Probe")
        win.resize(320, 240)
        win.show()

        canvas = win.evas
        img = FilledImage(canvas)

        report["module_matches"] = scan_names(evas_mod, "efl.evas module", keywords)
        report["canvas_matches"] = scan_names(canvas, "canvas", keywords)
        report["image_matches"] = scan_names(img, "image", keywords)

        print("\n=== Moksha-Warp Evas Deep Probe ===")
        print_section("efl.evas module", report["module_matches"])
        print_section("canvas", report["canvas_matches"])
        print_section("FilledImage", report["image_matches"])

        with open(LOG_FILE, "w") as f:
            json.dump(report, f, indent=2)

        print("\nReport saved to", LOG_FILE)

    finally:
        if win is not None:
            try:
                win.delete()
            except Exception:
                pass
        elm.shutdown()


if __name__ == "__main__":
    main()

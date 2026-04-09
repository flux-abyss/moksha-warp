#!/usr/bin/env python3

import inspect
import json
from pathlib import Path

from efl import elementary as elm
from efl.evas import FilledImage


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "evas_probe.json"


def safe_signature(obj):
    try:
        return str(inspect.signature(obj))
    except Exception:
        return None


def main():
    LOG_DIR.mkdir(exist_ok=True)

    report = {
        "window_created": False,
        "canvas_found": False,
        "image_created": False,
        "image_type": None,
        "matches": [],
        "signatures": {},
        "errors": [],
    }

    elm.init()
    win = None

    try:
        win = elm.StandardWindow("moksha-warp-probe", "Moksha-Warp Evas Probe")
        win.resize(480, 320)
        win.show()
        report["window_created"] = True

        canvas = win.evas
        report["canvas_found"] = canvas is not None

        img = FilledImage(canvas)
        img.size_hint_weight = 1.0, 1.0
        img.size_hint_align = -1.0, -1.0
        img.show()
        win.resize_object_add(img)

        report["image_created"] = True
        report["image_type"] = str(type(img))

        keywords = ("native", "surface", "image", "gl", "evas")
        attrs = dir(img)

        matches = []
        for name in attrs:
            lower = name.lower()
            if any(k in lower for k in keywords):
                matches.append(name)

        matches = sorted(set(matches))
        report["matches"] = matches

        for name in matches:
            try:
                value = getattr(img, name)
                if callable(value):
                    report["signatures"][name] = safe_signature(value)
            except Exception as e:
                report["errors"].append(f"getattr failed for {name}: {e}")

        print("\n=== Moksha-Warp Evas Probe ===\n")
        print("Window created:", report["window_created"])
        print("Canvas found:", report["canvas_found"])
        print("Image created:", report["image_created"])
        print("Image type:", report["image_type"])
        print("\nRelevant attributes/methods:\n")

        for name in matches:
            sig = report["signatures"].get(name)
            if sig:
                print(f"  {name}{sig}")
            else:
                print(f"  {name}")

        if report["errors"]:
            print("\nErrors:")
            for err in report["errors"]:
                print(" ", err)

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

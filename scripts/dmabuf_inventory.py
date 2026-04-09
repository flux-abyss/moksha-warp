#!/usr/bin/env python3
import importlib
import inspect
import json
import os

OUT = os.path.expanduser("~/repos/moksha-warp/logs/dmabuf_inventory.json")

CANDIDATES = [
    "pywayland.protocol.linux_dmabuf_unstable_v1",
    "pywayland.protocol.linux_dmabuf_v1",
    "pywayland.protocol.viewporter",
    "pywayland.protocol.presentation_time",
]

results = {}

for modname in CANDIDATES:
    entry = {
        "importable": False,
        "attrs": [],
        "error": None,
    }
    try:
        mod = importlib.import_module(modname)
        entry["importable"] = True
        entry["attrs"] = [name for name in dir(mod) if not name.startswith("_")]
    except Exception as e:
        entry["error"] = repr(e)
    results[modname] = entry

# Try to find likely dmabuf-related names anywhere under pywayland.protocol
protocol_scan = {}
try:
    import pywayland.protocol as protocol_pkg
    base_attrs = [name for name in dir(protocol_pkg) if not name.startswith("_")]
    protocol_scan["protocol_pkg_attrs"] = base_attrs
except Exception as e:
    protocol_scan["protocol_pkg_error"] = repr(e)

data = {
    "candidates": results,
    "protocol_scan": protocol_scan,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print(json.dumps(data, indent=2))
print(f"\nSaved to {OUT}")

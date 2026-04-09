# Moksha-Warp Environment Setup

## System
Host: MicroForge  
OS: Bodhi Linux (Jammy base)

## Installed Packages

The following packages were installed to prepare the development environment:

build-essential  
pkg-config  
python3-dev  
python3-pip  
python3-setuptools  
python3-wheel  
python3-venv  
libefl-dev  
python3-efl  
libwayland-dev  
wayland-protocols  
libdrm-dev  
mesa-utils  
mesa-common-dev  
libegl1-mesa-dev  
libgles2-mesa-dev  

## Python Modules

Verified imports:

- efl
- efl.evas
- efl.elementary
- pywayland

## EFL Versions

pkg-config reports:

- efl: 1.27.0
- evas: 1.27.0
- elementary: 1.27.0
- ecore: 1.27.0

## Notes

Bodhi provides a unified EFL runtime package () version 1.27.0.

Development headers are provided by:

libefl-dev (Bodhi repository)

The Ubuntu package  must **not** be used because it conflicts with the Bodhi runtime packages.

## Current Status

Environment verified.  
Next step: run diagnostic probes for Moksha-Warp.

Scripts to generate:

1. probe_env.py
2. evas_probe.py
3. wayland_probe.py

#!/usr/bin/env bash
set -euo pipefail
grep -nE '\[direct-scanout\]|\[scanout\]|\[gles\] flip done' /tmp/moksha-warp-run.log

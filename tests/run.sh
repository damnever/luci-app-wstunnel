#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -p 'test_*.py' -v
"${WSTUNNEL_LUA:-luajit}" tests/test_ui.lua

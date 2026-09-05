#!/usr/bin/env python3
"""
Shim entrypoint for produce.py inside whop-editor directory.
"""
import sys
from pathlib import Path

ROOT_PRODUCE = Path(__file__).resolve().parent.parent / "produce.py"
if not ROOT_PRODUCE.exists():
    raise FileNotFoundError(f"Root produce.py not found at {ROOT_PRODUCE}")

import runpy
runpy.run_path(str(ROOT_PRODUCE), run_name="__main__")

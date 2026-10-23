#!/usr/bin/env python3
"""兼容入口：实现在 skills/craft-process-workbench/scripts/craft_upload.py。"""

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "skills" / "craft-process-workbench" / "scripts"
sys.path.insert(0, str(TARGET))
runpy.run_path(str(TARGET / "craft_upload.py"), run_name="__main__")

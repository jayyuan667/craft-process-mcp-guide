#!/usr/bin/env python3
"""兼容入口：实现在 skills/craft-process-workbench/scripts/craft_flow.py。

保留这个文件是为了让 `python tools/craft_flow.py ...` 继续可用。技能安装后
自带同一份脚本，只下载 skills/ 目录的人不需要这个入口。
"""

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "skills" / "craft-process-workbench" / "scripts"
sys.path.insert(0, str(TARGET))
runpy.run_path(str(TARGET / "craft_flow.py"), run_name="__main__")

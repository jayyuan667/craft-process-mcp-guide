#!/usr/bin/env python3
"""Generate harnesses/portable-SKILL.md from the workbench skill.

The portable single-file manual is a convenience copy for harnesses without a
skill loader. Hand-editing it meant every rule change had to be made twice and
the copy drifted. This script is the only supported way to change it.

Usage:
    python tools/build_portable.py           # rewrite harnesses/portable-SKILL.md
    python tools/build_portable.py --check   # exit 3 if the file is stale

Exit codes: 0 ok, 3 stale (with --check), 1 input missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "craft-process-workbench" / "SKILL.md"
FRAGMENT = ROOT / "harnesses" / "fragments" / "unattended.md"
TARGET = ROOT / "harnesses" / "portable-SKILL.md"

HEADER = """# craft-process 工艺工作台（单文件版）

给没有技能系统、也装不了 MCP 的 harness 用：把这份文件整个放进系统提示或项目规则。有技能系统时用拆分的两个 skill，别用这份。

> 本文件由 `tools/build_portable.py` 从 `skills/craft-process-workbench/SKILL.md` 生成，**不要手改**；改流程改那边，然后重新生成。规则冲突时以 `docs/05` 为准。
"""

NO_RECOVERY = "> 出错、409、超时、状态不一致、找不到地址 → 读 `craft-process-recovery`，本 skill 只管正常路径。"
PORTABLE_RECOVERY = "> 出错、409、超时、状态不一致、找不到地址 → 停下并列出证据（请求、返回、revision、时间点）；症状速查见仓库 `docs/04`。"


def build() -> str:
    text = SKILL.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise SystemExit("SKILL.md 缺少 frontmatter")
    body = text.split("---", 2)[2].lstrip("\n")
    if body.startswith("# "):
        body = body.split("\n", 1)[1].lstrip("\n")
    body = body.replace(NO_RECOVERY, PORTABLE_RECOVERY)
    if FRAGMENT.exists():
        fragment = FRAGMENT.read_text(encoding="utf-8").strip()
        if "## 事实源" in body:
            before, after = body.split("## 事实源", 1)
            body = before.rstrip() + "\n\n" + fragment + "\n\n## 事实源" + after
        else:
            body = body.rstrip() + "\n\n" + fragment
    return HEADER + "\n" + body.rstrip() + "\n"


def main() -> int:
    try:
        generated = build()
    except FileNotFoundError as exc:
        print(f"找不到输入：{exc}", file=sys.stderr)
        return 1

    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != generated:
            print("portable-SKILL.md 与 skill 不同步，跑 python tools/build_portable.py")
            return 3
        print("portable 与 skill 同源。")
        return 0

    TARGET.write_text(generated, encoding="utf-8")
    print(f"已生成 {TARGET.relative_to(ROOT)}（{len(generated.splitlines())} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

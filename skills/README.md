# 技能（Agent Skills）

两份可直接安装的 `SKILL.md`：

| 目录 | 什么时候用 |
| --- | --- |
| `craft-process-workbench/` | 正常跑流程：接 MCP、上传、特征复核、选模板、槽位、出卡、改卡、导出 |
| `craft-process-recovery/` | 出故障时：工具不出现、409、超时、特征表被冲掉、状态矛盾、丢了 `job_id` |

两份一起装。主流程里写着「出错见 recovery」——skill 之间不会自动加载，只装一份会在出错那一步断链。

**需要自备一个 craft-process 实例。** 本仓库不含服务地址、模板库和图纸；装好技能只得到流程知识，跑不起别人的部署。

## 安装

**Claude 桌面端 / Claude Code**：把目录复制到技能目录，装完新开会话。

```bash
mkdir -p ~/.claude/skills
cp -r skills/craft-process-workbench skills/craft-process-recovery ~/.claude/skills/
```

**WorkBuddy**：路径是 `~/.workbuddy/skills/<name>/SKILL.md`，格式相同，直接复制。

```bash
mkdir -p ~/.workbuddy/skills
cp -r skills/craft-process-workbench skills/craft-process-recovery ~/.workbuddy/skills/
```

**Codex**：`~/.codex/skills/<name>/SKILL.md`，同样复制。

**opencode**：没有技能目录，用 `AGENTS.md` 引用本目录下的两份文件；或直接看 `harnesses/portable-SKILL.md`（两份合并的单文件版）。

## 验证装好了

1. **新开会话**——技能清单不热加载，旧会话看不到。
2. 技能列表里能看到 `craft-process-workbench` 与 `craft-process-recovery`。
3. 说一句「craft-process 怎么接」能触发主技能，且它第一步会问 `tools/list` 有没有 17 个 `craft_*`。

## 版本与同步

`skills/` 下的副本由 `docs/` 派生，规则冲突时以 `docs/` 为准。`.skill-source.json` 记录派生时对应的文档提交，`tools/skill_drift_check.py` 用它做漂移检查——见根 README「规则的权威位置」一节。

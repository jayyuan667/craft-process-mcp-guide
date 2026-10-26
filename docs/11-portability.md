# 11 · 换一个 harness 怎么跑

这套流程不绑定某个客户端。三种做法，按可靠性排序。

## 一、优先用 CLI：技能自带的 `scripts/craft_flow.py`

只要 harness 能执行 shell 命令，就能跑完整条链路——不需要 MCP 客户端，也不需要知道工具名。脚本就在技能目录里（`skills/craft-process-workbench/scripts/`），所以**只下载技能、不配 MCP 也能跑**；仓库检出时走 `tools/craft_flow.py`，那是同一实现的兼容入口。每条命令独立可重跑，`status` 永远说明卡在哪。

地址按 `--backend`（写在子命令前）→ `CRAFT_BACKEND_URL` → `~/.config/craft-process/endpoints.json` 的顺序取。先验通再干活：

```bash
export CRAFT_BACKEND_URL=http://<backend-host>:5199
python scripts/craft_flow.py doctor             # 首次使用：地址/后端/任务/下一步一次看完
python scripts/craft_flow.py health              # 200 且 service 对得上

python scripts/craft_flow.py upload drawing.png   # 记账 → 上传 → 记下 job_id
python scripts/craft_flow.py adopt <job_id>       # 接管 curl/别处建的 job，补本地状态
python scripts/craft_flow.py wait                 # 等到 extracted
python scripts/craft_flow.py dump                 # 工作台落盘 JSON
python scripts/craft_flow.py previews --download ./previews   # 复核单要用的图
python scripts/craft_flow.py review   --answers review.json
python scripts/craft_flow.py presence --list      # 结构项清单，逐条问人
python scripts/craft_flow.py presence --questions q.json  # 生成可点选问题清单
python scripts/craft_flow.py presence --answers presence.json
python scripts/craft_flow.py match                # 看候选与参考图号
python scripts/craft_flow.py select <template-id>
python scripts/craft_flow.py slots    --values slots.json
python scripts/craft_flow.py finalize             # 出卡 + 四字段校验
python scripts/craft_flow.py edit     --operations ops.json   # 生成后改行
python scripts/craft_flow.py export process-card.xlsx
```

`doctor` 是首次入口（地址、后端、任务、下一步一次看完）；`status` 是阶段探针：`blocking_action`、计数、下一步。

### answers 文件由人产出

工具不发明数值。三个 `--answers` / `--values` 文件就是人拍板的结果，工具只负责把它们套到服务端返回的完整对象上：

```json
// review.json
{"overrides": {"overall_length:1": {"value": "1786", "status": "confirmed"}}}

// presence.json
{"features": {"KEYWAY": "yes", "SQUARE": "no"},
 "branch_conditions": {"material": "<material>", "billet_type": "<billet-type>", "route_prefix": "<route-prefix>"}}

// slots.json
{"values": {"<template-id>-30-0": "φ77，0，-0.025", "<template-id>-60-0": "60"}}
```

`review` 会把整张特征表回传（就地修改后再发），所以不会踩到「最小载荷冲掉特征表」那个坑；`select` 遇到缺关键特征的模板会拒绝，除非加 `--force`（表示记成人工选择）。

退出码：`0` 正常，`2` 网络或超时，`3` 服务端拒绝，`4` 状态不一致，`5` 四字段没过。

### 实测

2026-10-23 在本部署上跑通一条完整链路：上传 → 识别 90s → 特征 3 项 → presence → 11 个候选 → 选 <template-id> → 5 个槽位 → 出卡 20 道工序 → 导出 4252 字节 XLSX，与同一张图此前人工逐项核对过的产卡**逐行一致（21 行 0 差异）**。

## 二、接入 MCP（先判断要不要接）

### 先自检

调 `tools/list`：有 17 个 `craft_*` 就说明已接好，直接进流程。**没有**的话有两条路——走 CLI（第一节，不需要配 MCP），或者配 MCP（下面）。

配置需要 `<mcp-host>`。仓库里没有地址，按 [08](08-endpoint-discovery.md) 找；找不到就停下来问部署方，别猜。

### 四家的配置片段

Claude 桌面端 / Claude Code（项目 `.mcp.json` 或客户端设置）：

```json
{"mcpServers": {"craft-process": {"type": "http", "url": "http://<mcp-host>:8764/mcp"}}}
```

Codex `~/.codex/config.toml`：

```toml
[mcp_servers.craft-process]
url = "http://<mcp-host>:8764/mcp"
```

WorkBuddy `~/.workbuddy/mcp.json`（或 `~/.workbuddy/.mcp.json`）：

```json
{"mcpServers": {"craft-process": {"type": "http", "url": "http://<mcp-host>:8764/mcp"}}}
```

opencode `opencode.json`：

```json
{"mcp": {"craft-process": {"type": "remote", "url": "http://<mcp-host>:8764/mcp"}}}
```

Codex 与 opencode 的键名各版本有差异，写之前对一眼它们的文档；Claude 与 WorkBuddy 用同一个 `mcpServers` 形状。

### 配完要验三件事

1. **新开会话。** 工具清单不热加载，当前会话看不到刚加的工具——这是最常见的一次性失败。
2. `initialize` 返回 `200` + `mcp-session-id` 头 + body 有 `serverInfo`。
3. `tools/list` 里有 17 个 `craft_*`。

三件都过了再往下走。只过第 2 件说明壳活着但工具没挂上。

## 技能装在哪

| harness | 技能位置 |
| --- | --- |
| Claude 桌面端 / Claude Code | 账号技能（`/` 菜单可查） |
| Codex | `~/.codex/skills/<name>/SKILL.md` |
| WorkBuddy | `~/.workbuddy/skills/<name>/SKILL.md`（也认 `~/.agents/skills/`） |
| opencode | `AGENTS.md` + 技能目录 |

技能负责「什么时候做什么、判据是什么」，CLI 负责「怎么做」。两者一起用最省事：技能里写 `python scripts/craft_flow.py doctor`，模型不需要记 REST 路径。

## 三、什么都没有：一份单文件

没有技能系统、也不能装 MCP 的 harness，把 [harnesses/portable-SKILL.md](../harnesses/portable-SKILL.md) 整个塞进系统提示或项目规则（`AGENTS.md` / `CLAUDE.md` 都行）。那份是两份技能合并、去掉跨文件引用的版本，代价是比拆分版长一倍。

## 平台差异

Windows 上三个实际踩过的点：

- **临时文件不要写 `/tmp`。** Git Bash / MSYS 的 `/tmp` 与 Python 看到的路径不一定是同一个；中间文件统一放 `~/.config/craft-process/tmp/`，两边都认。
- **Python 启动器常叫 `py`。** 技能里的 `python scripts/craft_flow.py` 换成 `py scripts\craft_flow.py`；路径含空格时加引号。
- **代码页。** 控制台默认不一定是 UTF-8；CLI 已经强制 stdout 用 UTF-8，自己写脚本读 `answers` 文件时要显式 `encoding="utf-8"`。

## 无人值守

批处理里没有人拍板时，不要走完整链路。跑 `upload` → `wait` → `dump`，然后停下，把待确认项落成问题清单等人处理；确认后再从 `review` 续。

理由：三处闸门是为「人负责」设计的，自动确认等于把责任转嫁给一个不会说话的脚本。

## 不要做的事

- 不要把后端地址写进公开仓库的文档
- 不要为某个 harness 改流程逻辑，改的都是包装层
- 不要让 CLI 在缺 answers 时猜一个默认值

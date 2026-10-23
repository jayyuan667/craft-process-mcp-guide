# 技能（Agent Skills）

两份可直接安装的 `SKILL.md`，外加一个能跑的客户端：

| 目录 | 什么时候用 |
| --- | --- |
| `craft-process-workbench/` | 正常跑流程：接 MCP、上传、特征复核、选模板、槽位、出卡、改卡、导出 |
| `craft-process-workbench/scripts/` | 技能自带的 CLI（`craft_flow.py`、`craft_upload.py`），不用 MCP 也能跑 |
| `craft-process-recovery/` | 出故障时：工具不出现、409、超时、特征表被冲掉、状态矛盾、丢了 `job_id` |

两份技能一起装。主流程里写着「出错见 recovery」——skill 之间不会自动加载，只装一份会在出错那一步断链。

## 只下载技能能用吗

能，但**光有技能不行，还差一个服务地址**。技能本身只是说明书，不会凭空连上谁。要让「下载即用」成立，需要三样：

1. **服务实例**——一套已部署的 craft-process（本仓库不含）；
2. **地址**——后端地址，或 MCP 端点；
3. **客户端**——技能里自带的 `scripts/craft_flow.py`。

有了 1 和 3，把地址填进 `CRAFT_BACKEND_URL` 就能跑完七步，全程不需要配 MCP。没有实例的话，装什么都不能工作——这不是安装问题。

## 安装

**Claude 桌面端 / Claude Code**：整个目录复制过去（`scripts/` 要一起），装完新开会话。

```bash
mkdir -p ~/.claude/skills
cp -r skills/craft-process-workbench skills/craft-process-recovery ~/.claude/skills/
```

**WorkBuddy**：`~/.workbuddy/skills/<name>/SKILL.md`，格式相同，同样整目录复制。

**Codex**：`~/.codex/skills/<name>/SKILL.md`，同样整目录复制。

**opencode**：没有技能目录，用 `AGENTS.md` 引用；或直接用 `harnesses/portable-SKILL.md` 单文件版。

> 只把 `SKILL.md` 单独上传到账号技能库时，`scripts/` 不会跟着走。那种装法下，CLI 需要另外 clone 本仓库，或者只用 MCP 那条路。

## 配地址

三种方式，优先级从高到低：

```bash
# 1. 每条命令带（注意写在子命令前面）
python scripts/craft_flow.py --backend http://<backend-host>:<port> health

# 2. 环境变量
export CRAFT_BACKEND_URL=http://<backend-host>:<port>

# 3. 写进配置文件（docs/08 约定的位置）
mkdir -p ~/.config/craft-process
echo '{"backend": "http://<backend-host>:<port>"}' > ~/.config/craft-process/endpoints.json
```

MCP 那条路则是把 `http://<mcp-host>:<port>/mcp` 写进 harness 的 `mcpServers`，片段见主技能的「先确认接没接上」一节。

## 验证装好了

1. **新开会话**——技能清单不热加载，旧会话看不到。
2. 技能列表里能看到 `craft-process-workbench` 与 `craft-process-recovery`。
3. `python scripts/craft_flow.py health` 返回 `ok`，且 `service` 是预期的服务名——只返回 200 不够，可能连到了别的服务。
4. 说一句「craft-process 怎么接」能触发主技能，且它第一步会问 `tools/list` 有没有 17 个 `craft_*`。

## 版本与同步

`skills/` 下的副本由 `docs/` 派生，规则冲突时以 `docs/` 为准。`.skill-source.json` 记录派生时各文档的最新提交，`tools/skill_drift_check.py` 用它做漂移检查——见根 README「规则的权威位置」一节。

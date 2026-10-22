# craft-process MCP 实践指南

[English](README.en.md) · 中文

一套把「二维图纸 → 结构化特征 → 模板工艺卡」封装成 MCP 工具的服务，在真实部署和真实图纸上踩过坑之后的实践笔记。本仓库只记录部署方式、接口契约、工作流闸门和修复方案，**不包含任何服务端源码、企业名称、图号或真实主机地址**。

## 这是什么

服务对外是一个 Streamable HTTP 的 MCP 端点，暴露一组 `craft_*` 工具，覆盖建任务、特征复核、模板匹配与选择、槽位补全、工艺卡生成与导出。对客户端来说它只是一个 MCP Server；对服务端来说它是两层：MCP 壳 + 业务后端。

典型调用链：

```
craft_create_job → craft_get_job / craft_wait_job → craft_get_workbench
→ craft_feature_review → craft_template_match → craft_select_template
→ craft_update_slots / craft_review_slots → craft_generate_process_card
→ craft_export_process_card
```

## 两段式架构

```
MCP client ──(Streamable HTTP)──> MCP shell (FastAPI/uvicorn)
                                        │  HTTP
                                        ▼
                                  backend (Flask/Werkzeug)
                                  /api/jobs, /workbench, /feature-review ...
```

关键点：**壳与后端是两个进程，可能不在同一台机器、同一个网络命名空间。** 大多数「连不上」不是 MCP 配置错，而是这一跳断了。详见 [docs/01-architecture.md](docs/01-architecture.md)。

## 快速开始

接一个 HTTP MCP 只需要一段配置：

```json
{
  "mcpServers": {
    "craft-process": {
      "type": "http",
      "url": "http://<mcp-host>:8764/mcp"
    }
  }
}
```

完整流程（含 multipart 直传和每步的判据）见 [docs/02-quickstart.md](docs/02-quickstart.md)。

**如果你是要直接调用它的 agent**，跳过上面那篇，直接看 [docs/05-agent-playbook.md](docs/05-agent-playbook.md)：只有动作、判据和禁令。地址不在仓库里，按该页第 0 节读取本机配置或环境变量。

## 问题清单

| 症状 | 先查什么 |
| --- | --- |
| MCP 能握手，工具调用报连接失败 | 壳到后端那一跳，不是 MCP 配置 |
| 工具报「文件不存在」 | 路径是相对壳所在主机解析的 |
| 写操作返回 409 | `revision` 过期，先重读 workbench |
| 生成工艺卡 409 | 候选模板不等于已选模板 |
| 生成返回成功但没有卡 | 实际出卡的是 `slot-review`，见现场笔记 5.4 |
| 卡里的公差和确认值不一致 | 派生规则在生成阶段重算，见 patch 8 |
| 选模板超时但状态变了 | 客户端超时、服务端已写成功 |
| 导出拿不到文件 | 文件写进了壳所在容器的目录 |

逐条排查见 [docs/04-troubleshooting.md](docs/04-troubleshooting.md)。

## 修复方案

十份说明，按「会不会毁数据」排序，实施顺序见 [docs/06-optimization-plan.md](docs/06-optimization-plan.md)：

1. [后端地址可配置](patches/01-api-base-url.md) — 不改数据，只改部署。
2. [特征复核改为合并语义](patches/02-feature-review-payload.md) — 防止整张特征表被覆盖。
3. [`create_job` 接收文件内容](patches/03-file-content-input.md) — 让客户端不必与后端共享文件系统。
4. [超时与导出](patches/04-timeout-and-export.md) — 长任务与产物落地。
5. [暴露预览工艺卡](patches/05-draft-process-card-tools.md) — 补上页面有、MCP 没有的复核环节。
6. [增加 `next_action` 工具](patches/06-next-action-tool.md) — 把下一步放进协议，而不是文档。
7. [任务状态一致性](patches/07-state-consistency.md) — 防止读错任务、写错任务。
8. [槽位取值权威](patches/08-slot-value-authority.md) — 人工确认值不被派生规则覆盖。
9. [生成语义与计数](patches/09-generate-semantics.md) — `generate` 空操作、`rejected` 计数、导出格式。
10. [后端地址自披露](patches/10-backend-address-discovery.md) — 让 `craft_health` 说出后端地址，不用再找端口。

一次真实链路的完整记录（含 revision 时间线和踩坑顺序）见 [docs/07-field-notes.md](docs/07-field-notes.md)。

## 工作流与闸门

这套服务把人工确认做成硬闸门，不是可选项。三处闸门、参数来源约束和几条业务红线见 [docs/03-workflow-and-gates.md](docs/03-workflow-and-gates.md)。

## 目录

```
README.md / README.en.md   本文件与英文版
LICENSE / NOTICE           Apache-2.0
docs/01-architecture.md    两段式架构与分层排障
docs/02-quickstart.md      从接入到出卡
docs/03-workflow-and-gates.md  闸门、约束与红线
docs/04-troubleshooting.md 按症状查的故障手册
docs/05-agent-playbook.md  给 agent 的十步操作协议
docs/06-optimization-plan.md 分三批的优化方案与验收标准
docs/07-field-notes.md     一次真实链路的现场笔记与 revision 时间线
docs/08-endpoint-discovery.md 后端地址的发现路径（不扫端口）
mcp.example.json           客户端配置模板（地址用占位符）
tools/craft_discover.py    CLI；验证候选地址并做服务名指纹比对
patches/                   十份修复与改进方案
```

## 许可

Apache-2.0，见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。本项目是非官方实践记录，与任何厂商、产品或服务无隶属关系。

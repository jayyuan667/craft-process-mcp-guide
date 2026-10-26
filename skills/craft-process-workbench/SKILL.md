---
name: "craft-process-workbench"
description: "把二维图纸跑成模板工艺卡：先确认 MCP 是否接上（含 Claude/Codex/WorkBuddy/opencode 配置），再走上传、特征复核、模板选择、槽位确认、出卡、改卡与导出。技能自带 CLI，下载后给一个后端地址即可跑，不必先配 MCP。明确禁止重做服务端已完成的提取与换算。提到 craft-process、工艺卡、阀杆工艺、模板匹配、二维图纸转工艺、怎么接 MCP 时使用。"
---

# craft-process 工艺工作台

把二维图纸跑成模板工艺卡。服务是两层：MCP 壳（Streamable HTTP，`/<port>/mcp`，17 个 `craft_*` 工具）+ 业务后端（Flask，根路径就是网页工作台）。壳只做协议与参数映射，业务状态全在后端；两者可能不在同一网络命名空间。

**需要自备一个 craft-process 实例**——这套流程不附带服务，地址与模板库因部署而异。

这套流程的价值不在自动化，在于三处人工闸门：特征复核、模板选择、槽位复核。闸门是产品行为，不是障碍。

## 红线（先读）

不写图上没有、也没人确认过的值。不把候选当选择。不把派生值当事实。不跳过人工确认。不把失败当成功继续往下走。不猜地址、不扫网段。

## 分工（别抢服务端的活）

服务端已经给出：特征值 / 置信度 / 部位 / 证据，槽位候选值 / 名义尺寸 / 上下偏差 / 绑定理由，模板候选 / `missing` / 参考图号，工序与工时。

所以**不要**重算派生值、不要重新 OCR 或量图、不要逐条切图核对、不要每步全量重读工作台、不要把 `display_value` 再格式化一遍。一次复核里，值得切图的只有被质疑的 1–2 处。

时间上：识别 70–90 秒、选模板 48–60 秒是服务端耗时，省不掉；**agent 侧复核与提交控制在 1 分钟内**。核对到第三处公差、切到第三张图，就是跑偏了。判据一句话：返回体里已经有对应字段，就停手。

> 出错、409、超时、状态不一致、找不到地址 → 读 `craft-process-recovery`，本 skill 只管正常路径。

## 0. 先确认接没接上

调 `tools/list`：有 17 个 `craft_*` 就说明已接好，跳到第 1 节。

**没有**的话，两条路选一条，不要停在"没有工具所以做不了"：

**A. 用 CLI，完全不配 MCP。** 技能目录自带客户端，只下载这份技能也够（路径按安装位置换）：

```bash
cd ~/.claude/skills/craft-process-workbench    # WorkBuddy: ~/.workbuddy/skills/...
python scripts/craft_flow.py --backend http://<backend-host>:<port> health
```

仓库检出时同一实现在 `tools/craft_flow.py`（兼容入口）。

**B. 配 MCP。** 写进当前 harness 的配置文件：

```json
// Claude 桌面端 / Claude Code（项目 .mcp.json 或客户端设置）
{"mcpServers": {"craft-process": {"type": "http", "url": "http://<mcp-host>:<port>/mcp"}}}

// WorkBuddy ~/.workbuddy/mcp.json（或 .mcp.json）
{"mcpServers": {"craft-process": {"type": "http", "url": "http://<mcp-host>:<port>/mcp"}}}

// opencode opencode.json
{"mcp": {"craft-process": {"type": "remote", "url": "http://<mcp-host>:<port>/mcp"}}}
```

```toml
# Codex ~/.codex/config.toml
[mcp_servers.craft-process]
url = "http://<mcp-host>:<port>/mcp"
```

Codex 与 opencode 的键名各版本有差异，写前对一眼它们的文档；Claude 与 WorkBuddy 用同一个 `mcpServers` 形状。

**配完必须验三件事**，缺一不可：

1. **新开会话。** 工具清单不热加载，当前会话看不到新加的工具——这是最常见的一次性失败，不要以为配置写错了。
2. `initialize` 返回 `200` + `mcp-session-id` 头 + body 有 `serverInfo`。
3. `tools/list` 里有 17 个 `craft_*`。只过第 2 件说明壳活着但工具没挂上。

`<mcp-host>` 是**壳**的地址，不是后端地址——两者不同端口，把后端端口填成 `/mcp` 只会得到 404。按顺序取：环境变量 `CRAFT_MCP_URL` → `~/.config/craft-process/endpoints.json` 的 `mcp` 字段 → 问部署方要「MCP 端点」（明确说是 `/mcp` 那个，不是后端）。有主机权限就 `ss -tlnp` 看 uvicorn 监听了什么，再发 `initialize` 验 `200` + `mcp-session-id`；端口开着不算数。**不要猜、不要扫网段。**

## 有 CLI 时优先用 CLI

技能自带 `scripts/craft_flow.py`——一条命令推进一步，任何能跑 shell 的 harness 都能用，不依赖 MCP 客户端。下面命令在技能目录下运行（Claude：`~/.claude/skills/craft-process-workbench`，WorkBuddy：`~/.workbuddy/skills/craft-process-workbench`）；仓库检出时用 `tools/craft_flow.py`，命令相同。

**先给地址**，按顺序取：`--backend`（写在子命令之前）→ 环境变量 `CRAFT_BACKEND_URL` → `~/.config/craft-process/endpoints.json` 的 `backend`。都没有时 `health` 会直接说没有地址，不会瞎连。

```bash
python scripts/craft_flow.py health      # 验地址：200 且 service 名对得上
python scripts/craft_flow.py status      # 阶段 / 阻断点 / 下一步
python scripts/craft_flow.py upload drawing.png
python scripts/craft_flow.py wait
python scripts/craft_flow.py previews --download ./previews
python scripts/craft_flow.py review --answers review.json
python scripts/craft_flow.py presence --answers presence.json
python scripts/craft_flow.py match
python scripts/craft_flow.py select <template-id>
python scripts/craft_flow.py slots --values slots.json
python scripts/craft_flow.py finalize
python scripts/craft_flow.py edit --operations ops.json
python scripts/craft_flow.py export process-card.xlsx
```

`answers` / `values` 文件就是人拍板的结果：`{"overrides": {"overall_length:1": {"value": "1786"}}}`、`{"features": {"KEYWAY": "yes"}, "branch_conditions": {...}}`、`{"values": {"<template-id>-30-0": "φ77，0，-0.025"}}`。

没有 CLI 时，下面各节是它背后的 REST 契约，照着手打。

## 1. 上传图纸

`craft_create_job` 收的是**路径**，并在**壳所在主机**解析——传本机路径不会传输任何字节。默认直传后端：

```bash
curl -sS -X POST "$CRAFT_BACKEND_URL/api/jobs" -F "files=@drawing.png"
```

只收 PDF / PNG / JPG。返回 `202` + 32 位十六进制 `job_id`。

**发字节之前先把 attempt 写进账本**（`~/.config/craft-process/jobs.jsonl`）：`GET /api/jobs` 返回 `405`，没有任务列表，`job_id` 一丢就只能靠账本对账。

## 2. 等识别

轮询 `GET /api/jobs/{id}` 到 `status=extracted` 且 `progress=100`。约 70~90 秒，进度会长时间停在 35%，不是卡住。`queued`/`running` 期间重复 create 会重复消耗算力。

## 3. 读工作台

`GET /api/jobs/{id}/workbench`（`detail=full` 在部分 build 上被忽略，恒返回全量）。

必看 `revision`、`current_stage`、`blocking_action`，并核对返回体的 `job_id` 等于请求的 id。**不等就停。**

`blocking_action` 是服务端拒绝跳过的下一步：`confirm_features` → `select_template` → `review_slots` → `export_card`。

## 4. 特征复核（最容易毁数据的一步）

`POST /feature-review` 是**整表替换**，不是补丁。只发 `{feature_id, decision}` 会把 role/value/confidence 全部删掉，计数塌成 unresolved，而且不报错。

正确做法：取 full 工作台的 `review.features` 完整数组 → 就地改需要改的对象 → `status` 置 `confirmed` → `value` **转成字符串** → 整个数组回传，带 `revision`。

```json
{"revision": 0,
 "features": [{"feature_id": "overall_length:1", "role": "overall_length",
               "value": "1786", "status": "confirmed", "...": "其余字段原样保留"}]}
```

判据：`counts.needs_review == 0`，`blocking_action` 前进。**每条都要有人确认过，不要自己批量确认。**

### 矛盾扫视（20–30 秒，不可省）

列给人之前做一次不看细节的扫视：把系统值和图面量级过一遍，只找图上根本不存在的数。不做全量核对——逐条切图放大是重复劳动，人看图比你快；但幽灵值必须标出来。只切被质疑的那 1–2 处，不要为了"确认一遍"把每个值都放大。

实测同一张图连跑三次，四项尺寸是四种错法：最大外径给 `108`（图上没有这个数）、总长给 `1776`（取了紧邻总长线的另一条尺寸）、端部外径三次给 `80`/`90`/`75`（图面是 Ø72±0.13，`75` 是图上别处的值、位置绑错）、螺纹给 `2A`（图面 `3A`）。四类是**幽灵值 / 取错尺寸线 / 绑错位置 / 字符读错**，前两类扫视能抓，后两类只能靠部位标注让人对照。

**每一项必须带部位**（"小端轴段""最大外圆"）。只有数字的清单无法被质疑，只能被盖章。

> 错值可能不出现在卡里：模板正文不含该数值时，错值照样产出看起来正常的卡。那是模板粗糙抵消了识别错误，不是闸门挡住了它。不要用"上次卡是对的"推断这次也对。

## 5. 结构特征与分支条件

`POST /feature-presence` 管「有/无」和三个分支条件。**`features` 必须是列表**，传对象会 422「特征选择格式不正确」：

```json
{"features": [{"feature_id": "KEYWAY", "presence": "yes"},
              {"feature_id": "SQUARE", "presence": "yes"}],
 "branch_conditions": {"material": "<material>", "billet_type": "<billet-type>", "route_prefix": "<route-prefix>"},
 "revision": 3}
```

分支条件不填，`blocking_action` 会卡在 `confirm_features` 不动。图纸上通常没有材料，只能问人；选项由服务端给（每次部署不同，读工作台的候选值），也可留 `unknown`。提交后会顺带触发模板匹配。

## 6. 模板匹配与选择

候选在 `decision.candidates`；`replacement` 在选择前是 null，不要等它填充。

**不要只看 `match_strength`。** 候选可以全部是 `complete`，区别在 `candidate.template_preview.reference_drawing`：等于当前图号的那个，槽位值和工艺文本本来属于这张图；别的图号是借另一档尺寸。

**选之前先看 `required_features` / `missing`**，缺哪个结构当场问人，别等 422 顶回来——「模板缺少关键特征：SQUARE」不是让你换模板，是要一个结构判断。

```json
{"template_id": "<template-id>", "revision": 5}
```

选模板可能跑 48~60 秒以上。**超时不等于失败**：先读工作台，`revision` 前进且已选就继续，不要重选。`selected_template_id` 有些构建选完仍是 null，别拿它当唯一判据。

参考图号与当前图号不一致时，两者并排列给人，说明这是借档，记成**人工选择**。

## 7. 槽位

`POST /slots` 写值，`POST /slot-review` 记录复核并出卡。

```json
{"values": {"<template-id>-30-0": {"value": "φ77，0，-0.025"},
            "<template-id>-30-1": {"value": "φ75，0，-0.2"},
            "<template-id>-60-0": {"value": "60"}},
 "revision": 6}
```

值格式跟 `display_value` 走（全角逗号、φ 前缀）。三个来源必须分清：**图纸事实 / 人工决定 / 后端派生**。车、磨、镗余量是派生的，不得当原始值写入；派生槽位（`source: derived_tolerance`）留空不填。

写完 `/slots` 只存值、不消项，`unresolved_slots` 仍列全部；**必须再调 `/slot-review`**（`{"values": {}, "revision": n}`），之后 `validation.status=ok`、`unresolved_slots=[]`、`process_card.mode=official`。

槽位确认属于本次 job：即使和上一张图逐字相同也要重新列给人确认，可注明「与上次相同」，但不能跳过。

**公差被拒不要猜格式。** 一次有依据的提交后仍被拒，就保留图纸事实并停下，把原文、提交值、错误响应一起转交。

## 8. 出卡与导出

`generate` **不一定真正出卡**：实测返回 200 而 `process_card` 仍是 null，official 卡实际在 `slot-review` 之后才出现。

**出卡前四项一起看，缺一不可**：`replacement.validation.status`（不是 partial/unresolved）、`unresolved_slots`（为空）、`blocking_action`（已允许出卡）、`process_card`（`mode == "official"` 且 `operations` 非空）。摘要说没问题而详细校验是 partial，就是状态不同源。

导出直连后端，不要走壳（壳会把文件写进容器目录）：

```bash
curl -sS -o process-card.xlsx "$CRAFT_BACKEND_URL/api/jobs/{id}/process-card/export"
```

按 `Content-Type` 和文件头判断格式，别信文档后缀——实测返回 XLSX 而文档写 CSV。

### 预览图

`craft_list_previews` / `GET /previews` 列图，`craft_download_preview` 取字节。复核单工具（仓库 `tools/review_sheet.py`）需要这张图才能生成可点选页面，没有图只能退回文字问答。CLI：`craft_flow.py previews --download ./previews`。

### 改卡

生成后用 `craft_edit_process_card`（`POST /process-card-edit`）**整体替换** `operations`。只是措辞或派生值要改时用它，不要重新生成——重跑复核时规则会再算一次，同样被覆盖。

1. 提交前把 `工时` 转成**字符串**。数字 `0` 会被当成空值，0 工时工序（来料、热处理、涂油）的工时格会变空白，其他行正常，很难发现。
2. 改之前存一份当前 `operations`，改完导出、与改前逐行比对，不要只看返回 200。
3. 回读条数要与提交一致，不一致说明服务端丢了行。

CLI：`craft_flow.py edit --operations ops.json`，归一化已内置。

## 事实源

权威文档：`https://github.com/jayyuan667/craft-process-mcp-guide`（`docs/05` 操作手册、`docs/08` 地址发现、`docs/11` 接入与跨 harness 运行、`docs/03` 闸门、`docs/07` 真实链路证据）。与本 skill 冲突时以仓库为准，并回报冲突。


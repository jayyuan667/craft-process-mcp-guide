# craft-process 工艺工作台（单文件版）

给没有技能系统、也装不了 MCP 的 harness 用：把这份文件整个放进系统提示或项目规则。有技能系统时用拆分的两个 skill，别用这份。

> 本文件由 `tools/build_portable.py` 从 `skills/craft-process-workbench/SKILL.md` 生成，**不要手改**；改流程改那边，然后重新生成。规则冲突时以 `docs/05` 为准。

把二维图纸跑成模板工艺卡。服务是两层：MCP 壳（Streamable HTTP，`:8764/mcp`，17 个 `craft_*` 工具）+ 业务后端（Flask，`:5199`，根路径就是网页工作台）。壳只做协议与参数映射，业务状态全在后端；两者可能不在同一网络命名空间。

**需要自备一个 craft-process 实例**——这套流程不附带服务，地址与模板库因部署而异。

这套流程的价值不在自动化，在于三处人工闸门：特征复核、模板选择、槽位复核。闸门是产品行为，不是障碍。

## 红线（先读）

不写图上没有、也没人确认过的值。不把候选当选择。不把派生值当事实。不跳过人工确认。不把失败当成功继续往下走。不猜地址、不扫网段。

## 60 秒上手

不知道自己接没接上、也不知道走到哪了？在技能目录下跑一条：

```bash
python scripts/craft_flow.py doctor
```

它按顺序回答四件事：地址从哪来、后端是否活着（服务名对不对）、当前任务在哪个阶段、下一步敲什么。任务建于多久之前也会打出来——超过两小时会提示你确认是不是残留任务。

三种开局：

- **第一次接入**：报「地址 没有」→ 按第 0 节配 MCP 或设 `CRAFT_BACKEND_URL`，再跑一次。
- **有图纸要跑**：报「任务 无」→ `upload <file>`，然后按第 1–8 节推进。
- **中途接手**：看它给出的 `revision` 和 `blocking_action`，从对应那节继续；状态看着不对，先读 `craft-process-recovery`——它会告诉你断在哪层、回哪一节。

## 分工（别抢服务端的活）

服务端已经给出：特征值 / 置信度 / 部位 / 证据，槽位候选值 / 名义尺寸 / 上下偏差 / 绑定理由，模板候选 / `missing` / 参考图号，工序与工时。

所以**不要**重算派生值、不要重新 OCR 或量图、不要逐条切图核对、不要每步全量重读工作台、不要把 `display_value` 再格式化一遍。一次复核里，值得切图的只有被质疑的 1–2 处。

时间上：识别 70–90 秒、选模板 48–60 秒是服务端耗时，省不掉；**agent 侧复核与提交控制在 1 分钟内**。核对到第三处公差、切到第三张图，就是跑偏了。判据一句话：返回体里已经有对应字段，就停手。

> 出错、409、超时、状态不一致、找不到地址 → 停下并列出证据（请求、返回、revision、时间点）；症状速查见仓库 `docs/04`。

## 0. 先确认接没接上

调 `tools/list`：有 17 个 `craft_*` 就说明已接好，跳到第 1 节。

**没有**的话，两条路选一条，不要停在"没有工具所以做不了"：

**A. 用 CLI，完全不配 MCP。** 技能目录自带客户端，只下载这份技能也够（路径按安装位置换）：

```bash
cd ~/.claude/skills/craft-process-workbench    # WorkBuddy: ~/.workbuddy/skills/...
python scripts/craft_flow.py --backend http://<backend-host>:5199 health
```

仓库检出时同一实现在 `tools/craft_flow.py`（兼容入口）。

**B. 配 MCP。** 写进当前 harness 的配置文件：

```json
// Claude 桌面端 / Claude Code（项目 .mcp.json 或客户端设置）
{"mcpServers": {"craft-process": {"type": "http", "url": "http://<mcp-host>:8764/mcp"}}}

// WorkBuddy ~/.workbuddy/mcp.json（或 .mcp.json）
{"mcpServers": {"craft-process": {"type": "http", "url": "http://<mcp-host>:8764/mcp"}}}

// opencode opencode.json
{"mcp": {"craft-process": {"type": "remote", "url": "http://<mcp-host>:8764/mcp"}}}
```

```toml
# Codex ~/.codex/config.toml
[mcp_servers.craft-process]
url = "http://<mcp-host>:8764/mcp"
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
python scripts/craft_flow.py doctor      # 首次使用：地址/后端/任务/下一步
python scripts/craft_flow.py health      # 只验地址：200 且 service 名对得上
python scripts/craft_flow.py status      # 阶段 / 阻断点 / 下一步
python scripts/craft_flow.py upload drawing.png
python scripts/craft_flow.py wait
python scripts/craft_flow.py previews --download ./previews
python scripts/craft_flow.py review --answers review.json
python scripts/craft_flow.py presence --list
python scripts/craft_flow.py presence --answers presence.json
python scripts/craft_flow.py match
python scripts/craft_flow.py select <template-id>
python scripts/craft_flow.py slots --values slots.json
python scripts/craft_flow.py finalize
python scripts/craft_flow.py edit --operations ops.json
python scripts/craft_flow.py export process-card.xlsx
```

`answers` / `values` 文件就是人拍板的结果：`{"overrides": {"overall_length:1": {"value": "1786"}}}`、`{"source": "human", "features": {"KEYWAY": "yes"}, "branch_conditions": {...}}`、`{"values": {"<template-id>-30-0": "φ77，0，-0.025"}}`。

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

**摘要不可信，计数是明细。** 摘要可能写着「可导出」而 `review.counts.needs_review > 0`——这时出卡会带着没确认过的结构。`status` 现在会直接打警告，`finalize` / `export` 也会拒绝（退出码 5），别绕过。

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

## 5. 结构特征与分支条件（必须逐条问人）

**结构判断和尺寸复核一样是人工闸门，不许代判。** `presence --list` 列出服务端认识的全部结构项——包括 `low_frequency` 里默认 `no` 的——把每项的当前值、名称、证据摆给人，逐条要 yes / no。**没回答的项不能按 no 提交。**

```bash
python scripts/craft_flow.py presence --list
```

提交的是人给的答案，且必须覆盖全部项、带来源：

```json
{"source": "human",
 "features": {"THREAD": "yes", "SQUARE": "no", "BALL_HEAD_KEYWAY": "yes"},
 "branch_conditions": {"material": "<material>", "billet_type": "<billet-type>", "route_prefix": "<route-prefix>"}}
```

命令行会拦三种：缺项（列出缺哪些）、没有 `source: human`、值不是 yes/no。不要绕过——缺项通常就是有人没被问过。

REST 形状不同：`POST /feature-presence` 的 `features` 是列表 `[{"feature_id", "presence"}]`，传对象会 422。

其余规则：

- 用业务键（`THREAD` / `SQUARE` / `END_OUTER_SQUARE` / `BALL_HEAD_KEYWAY`），不要用尺寸 id（`overall_length:1`）或 YOLO 框 id（`yolo:1:1:四方`），后者会 422「特征不属于当前任务」。
- **YOLO 框错 ≠ 特征不存在。** 框落在标注区只能说明框错了，不能当否定依据。
- 分支条件图上通常没有，必须问人；别指望 `unknown` 兜底。
- **先结构、后尺寸**：结构决定候选池，尺寸只影响槽位。能先提 presence 就先提；服务端要求先复核尺寸就按 `blocking_action` 走，但匹配后一旦发现池里没有当前图号，立刻回 presence。
- 提交会顺带触发匹配，反复改结构判断会让 `revision` 一路涨。

## 6. 模板匹配与选择

候选在 `decision.candidates`；`replacement` 在选择前是 null，不要等它填充。

**不要只看 `match_strength`。** 候选可以全部是 `complete`，区别在 `candidate.template_preview.reference_drawing`：等于当前图号的那个，槽位值和工艺文本本来属于这张图；别的图号是借另一档尺寸。

**候选里没有当前图号 = 结构判断大概率漏了。** 当 `complete` 为 0、或所有候选的 `reference_drawing` 都不等于当前图号时，`match` 会自动打印 `low_frequency` 里所有 `no` 的项。逐条回图确认这些 no——尤其 `BALL_HEAD_KEYWAY`、`END_OUTER_SQUARE`、`SQUARE` 这类低频结构——翻正后重跑 `presence` 再 `match`。不要因为"有 4 个候选"就直接挑最像的。

**图号拿不到时不下结论。** CLI 只在能取到可信图号（`drawing.drawing_no`，或形如 `D1000W-264400B001` 的文件名）时才判「借档」；`image1.png` 这种文件名会被判为「图号未知」，此时它不打印借档、也不触发缺项诊断，只提示你核对参考图号与标题栏。别拿文件名当图号去对。

**用户回答的不是候选，就别硬选。** 对方回「球头带键槽、四方、螺纹」这类结构词，是在纠正上游判断，不是在选模板；回 `presence` 重提，再看候选。

**选之前先看 `required_features` / `missing`**，缺哪个结构当场问人，别等 422 顶回来——「模板缺少关键特征：SQUARE」不是让你换模板，是要一个结构判断。

**候选为空 = 没有模板进池。** `candidates == []` 且 `manual_filter.before_count == 0`：不是分数不够，也不是被普通条件筛掉。可能是库空，也可能是没有这个件的模板——接口不暴露库存，别断言整个库为空（同一实例上别的图可能匹配得到）。不要编模板号，也不要靠反复改 presence 试探（实测 5 种结构组合全 0）。停，把 `job_id` / `before_count` / `revision` / 已确认特征交给部署方，问这个件有没有模板；恢复后重跑 `match`，复核结果保留。

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

**槽位语义**：CLI 提交前会核一遍工序——磨削槽位拿到「留余量」的候选、车削槽位拿到成品公差时打印警告。警告不是拦截，但看到就别直接过。

## 8. 出卡与导出

`generate` **不一定真正出卡**：实测返回 200 而 `process_card` 仍是 null，official 卡实际在 `slot-review` 之后才出现。

**出卡前四项一起看，缺一不可**：`replacement.validation.status`（不是 partial/unresolved）、`unresolved_slots`（为空）、`blocking_action`（已允许出卡）、`process_card`（`mode == "official"` 且 `operations` 非空）。摘要说没问题而详细校验是 partial，就是状态不同源。

导出直连后端，不要走壳（壳会把文件写进容器目录）：

```bash
curl -sS -o process-card.xlsx "$CRAFT_BACKEND_URL/api/jobs/{id}/process-card/export"
```

按 `Content-Type` 和文件头判断格式，别信文档后缀——实测返回 XLSX 而文档写 CSV。`export` 会回读行数（含表头），拿它和 `operations` 条数对一下，不要只看 200。

### 预览图

`craft_list_previews` / `GET /previews` 列图，`craft_download_preview` 取字节。复核单工具（仓库 `tools/review_sheet.py`）需要这张图才能生成可点选页面，没有图只能退回文字问答。CLI：`craft_flow.py previews --download ./previews`。

### 改卡

生成后用 `craft_edit_process_card`（`POST /process-card-edit`）**整体替换** `operations`。只是措辞或派生值要改时用它，不要重新生成——重跑复核时规则会再算一次，同样被覆盖。

1. 提交前把 `工时` 转成**字符串**。数字 `0` 会被当成空值，0 工时工序（来料、热处理、涂油）的工时格会变空白，其他行正常，很难发现。
2. 改之前存一份当前 `operations`，改完导出、与改前逐行比对，不要只看返回 200。
3. 回读条数要与提交一致，不一致说明服务端丢了行。

CLI：`craft_flow.py edit --operations ops.json`，归一化已内置。

## 无人值守

只跑 `upload` → `wait` → `dump`，然后把待确认项落成问题清单停下，等人确认后再从 `review` 续。自动确认等于把责任转给不会说话的脚本。

## 事实源

权威文档：`https://github.com/jayyuan667/craft-process-mcp-guide`（`docs/05` 操作手册、`docs/08` 地址发现、`docs/11` 接入与跨 harness 运行、`docs/03` 闸门、`docs/07` 真实链路证据）。与本 skill 冲突时以仓库为准，并回报冲突。

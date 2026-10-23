# 05 · 给 agent 的操作手册

这一页只给动作、判据和禁令。流程细节和验收标准在 [02](02-quickstart.md)，规则背后的原因在 [03](03-workflow-and-gates.md)，同一件事只在那里写一遍。

## 开工前

每次任务开始，先读仓库里的最新 guide 和 `tools/list` 返回的实际 schema，至少核对本页、[02](02-quickstart.md) 与 [04](04-troubleshooting.md)。**guide 会更新，旧记忆只能当索引**：以仓库当前版本和工具实际返回为准，不要凭上一次会话的印象调用参数。

## 0. 拿地址

`<mcp-host>` 与 `<backend-host>` 不在仓库里。按顺序试，别跳步、别扫网段：

1. 读 `LOCAL.endpoints.md`（本机私有，已被 `.gitignore` 排除）或 `~/.config/craft-process/endpoints.json`。
2. 读环境变量 `CRAFT_MCP_URL` / `CRAFT_BACKEND_URL`。
3. 调 `craft_health`，看返回里有没有 `backend_url`（打了 [patch 10](../patches/10-backend-address-discovery.md) 才有）。
4. 用脚本验证短名单，而不是扫端口：

```bash
python tools/craft_discover.py --mcp "$CRAFT_MCP_URL"
```

它只验证同主机的已知候选，并用 `craft_health` 报告的服务名做指纹比对；端口开着但服务不对会明确标成 `skip`。

5. 仍然没有，停下来问部署负责人。**不要猜地址、不要扫网段**——扫到的多半是别人的服务。完整说明见 [08](08-endpoint-discovery.md)。

拿到后照 [mcp.example.json](../mcp.example.json) 填。

## 1. 先证明壳活着

向 `$CRAFT_MCP_URL` 发 `initialize`（命令见 [02 §1](02-quickstart.md)）。判据：`200` + `mcp-session-id` 头 + body 有 `serverInfo`。**不要**用 `/health` 判活。

## 2. 拿工具清单

`tools/list`，期望 `craft_*` 一族。数量对不上说明版本不同，以实际返回为准，不要凭记忆调不存在的工具。

## 3. 上传图纸

`craft_create_job` 的路径在**壳所在主机**解析，不是你本机。图纸不在壳可读位置时，直传后端：

```bash
python tools/craft_upload.py --file drawing.png --backend "$CRAFT_BACKEND_URL" --timeout 300
```

拿到 `job_id` 后，**先把它写进上下文或文件，再解析响应其他字段**。`GET /api/jobs` 是 `405`，没有列表接口，`job_id` 一丢就没有查询入口。

退出码处理：

| 码 | 含义 | 动作 |
| --- | --- | --- |
| `0` | 上传成功 | 拿到 `job_id`，往下走 |
| `4` | 同一文件在复用窗口内传过 | 用返回的 `job_id`；确实要新任务才加 `--force` |
| `2` | 超时，**状态未知** | 见下 |
| `3` | 被拒（格式 / HTTP 错误 / 连不上） | 修原因后重试，不需要对账 |

状态未知的顺序：`--list` 看账本 → 按 sha256、文件名、时间对账 → 确认没有再 `--force` 重传 → 告诉用户「可能多一个孤儿任务，不影响已有结果」。

**不要把「请人去工作台看看」当成唯一出路。** 账本里有记录；把人工确认当默认路径，等于把自动化降级成转述。也不要因为怕重复建任务就把流程停死——`queued`/`running` 期间重复 create 才是浪费，对账后的重传不是。

## 4. 等识别

轮询 `GET $CRAFT_BACKEND_URL/api/jobs/<id>` 或 `craft_wait_job`，到 `status=extracted` 且 `progress=100`。`queued`/`running` 期间重复 create 会重复消耗算力。

## 5. 读工作台（每次写之前都读）

`craft_get_workbench`，默认 summary，要完整数据用 `detail="full"`。

必看 `revision`、`current_stage`、`blocking_action`，并核对返回体的 `job_id` 等于你请求的 id。**不等就停**，见 [04 第 9 条](04-troubleshooting.md)。

## 6. 特征复核（最容易毁数据的一步）

`POST /feature-review` 是**整表替换**。四步不能省：

1. 取 full 工作台的 `review.features` 完整数组。
2. 就地改需要改的对象，`status` 置 `confirmed` 或 `rejected`。
3. `value` 一律转**字符串**，壳的 schema 拒数字。
4. 把**整张表**回传。

只发 `{feature_id, decision}` 会丢掉 role / value / confidence，计数回到 unresolved。

判据：`counts.needs_review == 0`，`blocking_action` 前进。

**每一条都要有人确认过才能写。不要自己批量确认。** 把待确认项列给人，等人回。问法见 [09](09-asking-humans.md)；超过 5 项或混了类型时直接生成复核单：

```bash
python tools/review_sheet.py --workbench wb.json --image input-1.png --out sheet.html
```

写完之前把解析结果回显一遍再落库。

### 矛盾扫视（20–30 秒，不可省）

列给人之前，先做一次**不看细节**的扫视：把每个系统值和图面量级对一遍，只找「图上根本不存在」的数。

- **不要做全量核对。** 逐条切图放大是重复劳动，人看图比你快；把时间花在判断而不是定位上。
- **幽灵值必须标出来。** 实测同一张图连跑三次，四项尺寸是四种不同的错法：最大外径给 `108`，图上根本没有这个数（真实最大外圆 Ø126±0.1）；总长给 `1776`，那是紧邻总长线的另一条尺寸（总长 1786±0.3）；端部外径三次给出 `80`／`90`／`75`，图面该位置是 Ø72±0.13，而 `75` 是图上另一处（右端 Ø75 0/−0.2）的值，值存在但绑错了位置；螺纹给 `2A`，图面是 `3A`。四类错法分别是**幽灵值 / 取错尺寸线 / 绑错位置 / 字符读错**——前两类扫视能抓，后两类只能靠「每项带部位」让人自己对照。
- **每一项必须带部位。** "小端轴段""最大外圆"这种定位词不能省；只有数字的清单无法被质疑，只能被盖章。
- **已知风险：错值可能不出现在卡里。** 模板正文不含该数值时，三处错值仍产出逐字相同的工艺卡——**这是模板粗糙抵消了识别错误，不是闸门挡住了它**。换一张跨分支的图（最大外径 ≥200 或长度 ≥2 m）就会换模板，错误随之落地。不要用"上次卡是对的"推断这次也对。

**确认成本要算清楚。** 让人「全部确认」是最便宜也最危险的交互：确认成本趋零时，人在核对的是图面，而不是在核对系统。agent 的责任是把可疑项摆到明面上，而不是把责任转移给一句「按系统值」。

## 7. 模板匹配 → 选择

`craft_template_match` 只算候选，**候选不等于已选**。`craft_select_template` 才提交，可能超过 60 秒；超时后**先读工作台**，已选就继续，不要重选。

判据：`blocking_action` 前进、stage 进入 replace。**不要等 `replacement` 填充**——选择前它是 null，候选在 `decision.candidates`；`selected_template_id` 在有些版本选完仍是 null，别拿它当唯一判据。

**选候选不要只看 `match_strength`。** 候选可以全是 `complete`，看 `candidate.template_preview.reference_drawing`：等于当前图号的那个，槽位值和工艺文本本来属于这张图；别的图号是借另一档尺寸。

**参考图号不匹配时显式提示。** 把当前图号与 `reference_drawing` 并排列给用户。用户明确选择其他模板时可以遵从，但要记录为**人工选择**，并在生成前重点核对槽位和工序内容。

**选择可能被 422 拒绝**（`模板缺少关键特征：XXX`）。这不是让你换模板，是服务端说它还缺一个结构判断。回图纸确认该结构是否存在，用 `feature_presence` 置 yes/no，再重试。

**422 可以提前避免。** 候选列表里已经带 `required_features` 与 `missing`：选之前扫一眼，缺哪个结构当场问人，别等提交被拒。实测把 `SQUARE` 提前问清后，推荐模板第一次就是 `complete`，省掉一整趟往返。

## 8. 槽位

`craft_update_slots` 写值，`craft_review_slots` 记录复核。三个来源必须分清：图纸事实、人工决定、后端派生。**派生值不得当原始值写入。**

三件事逐项核对，不要信服务端建议：

- 候选事实可能绑错槽位。见过 Ø64 的槽位被建议 Ø164、Ø157。先比 nominal。
- 派生值可能在生成阶段覆盖人工确认值。确认了 `-0.05/-0.10`，正式卡回来 `-0.05/-0.13`。生成后逐行比对。
- 公差 OCR 会错。`+0.1` 被读成 `+0.01`，服务端「以图纸为准」指的也可能是错的那个。放大原图看标注。

**槽位确认属于本次 job。** 即使和你上一张图的槽位值逐字相同，也要重新列给人确认——模板可能不同、绑定位置可能不同，"上次一样"不是确认。可以在清单里注明「与上次相同」，但不能因此跳过。

**公差被拒后不要猜格式。** 先确认图纸原文和工具接受的格式，做一次有依据的提交；仍被拒就保留图纸事实并停下，把校验问题转交处理。不要反复换写法——合法的 Ø75（0/−0.2）曾被反复判成格式无效，多次尝试没有推进任何状态。**停下来报告是正确结果。**

## 9. 生成与导出

`craft_generate_process_card` **不一定真正出卡**。实测返回 200 而 `process_card` 仍是 null；official 卡在 `craft_review_slots` 之后才出现。

判据看状态：`process_card.mode == "official"` 且 `operations` 非空。还是 null 就调 `craft_review_slots` 再读。卡没出来就导出，会得到「待确认」占位行。

**出卡前四项一起看，缺一不可：** `replacement.validation.status`、`unresolved_slots`、`blocking_action`、`process_card`。详细校验还有未解决槽位就不生成、不导出；摘要与详细校验矛盾时重读一次，仍矛盾就停下报告。细节见 [03](03-workflow-and-gates.md#出卡门槛四个字段一起看)。

导出直连后端，避免文件落在壳的容器目录：

```bash
curl -sS -o process-card.xlsx "$CRAFT_BACKEND_URL/api/jobs/<id>/process-card/export"
```

按 `Content-Type` 判断格式，别信文档后缀（实测有返回 XLSX 而文档写 CSV）。

## 10. 写操作通用规则

- 每次写带当前 `revision`，409 就重读工作台再改，**不要盲目重试**。
- 写前写后都比对 `job_id`。
- 超时不等于失败，先查状态。
- `reference_drawing` 是模板来源图号，不是当前图号。
- 一个 job 同时只让一个客户端写。

## 绝对不要

编造尺寸、公差、材料；把候选当选择；把派生值当事实；跳过人工确认；把失败当成功继续往下走；只给数字不给部位；用另一个 job 的确认结果替代本次确认。

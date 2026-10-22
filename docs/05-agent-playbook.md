# 给 agent 的操作手册

这一页是给**要直接驱动这个 MCP 的 agent**看的：不给背景，只给动作、判据和禁令。人类读 [02-quickstart.md](02-quickstart.md)。

要人做判断时，按 [09-asking-humans.md](09-asking-humans.md) 的格式问——尤其在没有结构化提问控件的环境里，散文式提问会让人多花几倍时间。不同客户端的渲染方式见 [10-harness-interaction.md](10-harness-interaction.md)。

## 0. 拿地址

`<mcp-host>` 与 `<backend-host>` 不在公开仓库里。按顺序试，别跳步、别扫网段：

1. 读 `LOCAL.endpoints.md`（本机私有，已被 `.gitignore` 排除）或 `~/.config/craft-process/endpoints.json`。
2. 读环境变量 `CRAFT_MCP_URL` / `CRAFT_BACKEND_URL`。
3. 调一次 `craft_health`，看返回里有没有 `backend_url`（打了 [patch 10](../patches/10-backend-address-discovery.md) 就会有）。
4. 还没有，用验证脚本试一个短名单，而不是扫端口：

```bash
python tools/craft_discover.py --mcp "$CRAFT_MCP_URL"
```

它只验证同主机的已知候选，并用 `craft_health` 报告的服务名做指纹比对，端口开着但服务不对会被跳过。

5. 仍然没有，停下来问部署负责人。**不要猜地址、不要扫网段**——扫到的多半是别人的服务。完整说明见 [08-endpoint-discovery.md](08-endpoint-discovery.md)。

拿到后照 [mcp.example.json](../mcp.example.json) 填。

## 1. 先证明壳活着

```bash
curl -sS -X POST "$CRAFT_MCP_URL" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
```

判据：`200` + 响应头有 `mcp-session-id` + body 里有 `serverInfo`。
**不要**用 `/health` 判活，这个端口可能没有该路由。

## 2. 拿工具清单

`tools/list`，期望看到 `craft_*` 一族（建任务、查询、工作台、特征复核、模板匹配/选择、槽位、工艺卡生成/编辑/导出）。数量对不上说明版本不同，以实际返回为准，不要凭记忆调不存在的工具。

## 3. 上传图纸

`craft_create_job` 的路径参数在**壳所在主机**解析，不是你本机。

两条路：
- 图纸已在壳可读的位置 → 传那个路径。
- 否则 → 直传后端：`curl -F "files=@drawing.png" -F "library_key=default" "$CRAFT_BACKEND_URL/api/jobs"`，拿回 `job_id`，后续全走 MCP。

只收 PDF / PNG / JPG。

## 4. 等识别

轮询 `GET $CRAFT_BACKEND_URL/api/jobs/<id>` 或 `craft_wait_job`，到 `status=extracted` 且 `progress=100`。
`queued`/`running` 期间**重复 create 会重复消耗算力**。

## 5. 读工作台（每次写之前都读）

`craft_get_workbench`，默认 summary，要完整数据用 `detail="full"`。

三件事必看：`revision`、`current_stage`、`blocking_action`；再核对返回体里的 `job_id` 等于你请求的 id。**不等就停**，见 [故障手册第 9 条](04-troubleshooting.md)。

## 6. 特征复核（最容易毁数据的一步）

`POST /feature-review` 是**整表替换**，不是补丁。

正确做法：

1. 取 full 工作台的 `review.features` 完整数组。
2. 就地改需要改的对象（`status` 置 `confirmed` 或 `rejected`）。
3. `value` 一律转成**字符串**（壳的 schema 拒数字）。
4. 把**整张表**回传。

只发 `{feature_id, decision}` 会丢掉 role/value/confidence，计数回到 unresolved。

判据：`counts.needs_review == 0`，`blocking_action` 前进。

**每一条都要有人确认过才能写。** 不要自己批量确认；把待确认项列给人，等人回。

怎么问，比问什么更影响效率。下面这种问法不要用：

> 请按编号确认：1 总长 1786±0.3；2 最大外径 Φ126±0.1；3 小端 Φ72；4 螺纹 3"-80UN-3A；5 有外螺纹吗；6 有腰型键吗；7 有内键槽吗？可回复「1正确；2正确…」

七项挤成一段，还要用户自己编号对齐，中间一项拿不准整句就得重写。改成三条规则：

**默认值 + 只改例外。** 先说「系统读数如下，默认全部采用，只回需要改的」，然后给一张表：编号、项目、系统值、图纸原文。用户回「3 改成 +0.13，7 没有」就够了。

**按类型分批。** 数值确认、有/无判断、看不清，是三种不同的回答方式，不要混在一条里。数值一次问完，存在性另起一段。

**每项给证据。** 数值项附图上原文，检测项附 bbox 裁剪图。让人对着图判断，而不是对着你的转述判断。

想省掉手工对齐，可以直接生成可点选的复核单：

```bash
python tools/review_sheet.py --workbench wb.json --image input-1.png --out sheet.html
```

它把每项做成一张卡片（编号、系统值、图纸原文或裁剪图、四个选项），点完点「生成回填 JSON」，复制出来就是可以直接提交的数组。看不清的项会被标成 `needs_review` 留在数组里，不会被悄悄当成确认。

写完之前把解析结果回显一遍：「我理解为 3 改为 +0.13、7 无，其余采用，对吗？」比事后返工便宜。

## 7. 模板匹配 → 选择

`craft_template_match` 只是算候选，**候选不等于已选**。
`craft_select_template` 才提交选择，可能超过 60s，超时后**先读工作台**，看到已选就继续，不要重选。

判据：`blocking_action` 前进、stage 进入 replace。**不要等 `replacement` 填充**——选择前它是 null，候选在 `decision.candidates`；`selected_template_id` 在有些版本里选完仍是 null，别拿它当唯一判据。

**选候选不要只看 `match_strength`。** 25 个候选可以全是 `complete`。看 `candidate.template_preview.reference_drawing`：等于当前图号的那个，槽位值和工艺文本本来属于这张图；别的图号是借另一档尺寸。

**选模板可能被 422 拒绝**（`模板缺少关键特征：XXX`）。这不是让你换模板，是服务端在告诉你它还缺一个结构判断。回到图纸确认该结构是否真实存在，再用 `feature_presence` 置 yes/no，然后重试选择。

## 8. 槽位

`craft_update_slots` 写值，`craft_review_slots` 记录复核。
值的三个来源必须分清：图纸事实、人工决定、后端派生。**派生值（车/磨/镗余量）不得当原始值写入。**

三件事必须逐项核对，不要信服务端的建议：

- **候选事实可能绑错槽位。** 见过 Ø64 的槽位被建议 Ø164、Ø157。先比 nominal 再用。
- **派生值可能在生成阶段覆盖人工确认值。** 确认了 `-0.05/-0.10`，正式卡里回来的是 `-0.05/-0.13`。生成后逐行比对。
- **公差 OCR 会错。** `+0.1` 被读成 `+0.01`，而服务端提示「以图纸为准」指的也是错的那个。放大原图看原始标注。

## 9. 生成与导出

`craft_generate_process_card` **不一定是真正出卡的那一步**。实测它返回 200，但 `process_card` 仍是 null；official 卡是在 `craft_review_slots` 之后才出现的。

所以判据看状态，不看返回码：读工作台，要求 `process_card.mode == "official"` 且 `operations` 非空。还是 null 就调 `craft_review_slots` 再读。卡没出来就导出会得到带「待确认」占位的行。

导出优先直连后端，避免文件落在壳的容器目录里：

```bash
curl -sS -o process-card.xlsx "$CRAFT_BACKEND_URL/api/jobs/<id>/process-card/export"
```

按响应 `Content-Type` 判断格式，别信文档里的后缀（实测有返回 XLSX 而当文档写 CSV 的情况）。

## 10. 写操作通用规则

- 每次写带当前 `revision`，409 就重读工作台再改，**不要盲目重试**。
- 写前写后都比对 `job_id`。
- 超时不等于失败，先查状态。
- `reference_drawing` 是模板来源图号，不是当前图号。
- 一个 job 同时只让一个客户端写。

## 绝对不要

编造尺寸、公差、材料；把候选当选择；把派生值当事实；跳过人工确认；把失败当成功继续往下走。

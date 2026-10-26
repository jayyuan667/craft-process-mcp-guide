# 07 · 现场笔记：图纸 → 模板工艺卡的一次完整链路

> 环境：MCP 壳 `<mcp-host>:8764`，业务后端 `<backend-host>:5199`。图号、厂商与真实主机地址已脱敏。
> 日期：2026-10-22。对象：一张轴类阀杆图纸，模板库中存在同图号参考卡 T01。

这一页记录**证据**：看到了什么、数字是多少、revision 怎么走。操作步骤在 [02](02-quickstart.md)，agent 的动作用 [05](05-agent-playbook.md)，这里不重复。

## 0. 结论摘要

链路能跑通，最终产出 18 道工序的正式 XLSX。但这次能跑通的关键不是特征提取，而是**模板库里存在同图号参考卡**。当前实现的本质是「模板命中 + 槽位替换」，不是「从图纸重建工艺」。

按影响排序，主要问题：

1. `feature-review` 是整表替换，错误形状的提交会冲掉识别结果。
2. 派生槽位在生成阶段会覆盖人工确认值。
3. `select_template` 同步执行，客户端 60s 超时但服务端可能已成功。
4. VLM 会读错公差，且「以图纸为准」的提示本身也可能错。
5. `generate` 在槽位未复核时返回 200 空操作，必须走 `slot-review`。
6. 导出实际是 XLSX，且必须直连后端。

## 1. 接入

### 1.1 仓库不是服务

本仓库只有部署笔记和补丁，没有服务端源码，也没有真实地址。必须先拿到 `<mcp-host>`，否则配置了也是死配置。

壳与后端是两个进程（FastAPI/uvicorn 与 Flask/Werkzeug），任何一个不通都表现为「MCP 连不上」。本次用 `initialize` 探壳、用 `/health` 探后端，分别确认。

### 1.2 客户端工具不会热加载

用 `claude mcp add --transport http ... --scope user` 接入后，当前会话看不到新工具，必须新开会话。为了不打断流程，本次用 `curl` 直接发 JSON-RPC `tools/call`，等价于客户端调用。

### 1.3 传输安全

实际部署是公网 IP + 明文 HTTP，且未见鉴权。功能可用，但图纸与工艺数据没有保护。长期使用至少需要 TLS 和访问控制。

## 2. 上传与识别

### 2.1 路径在壳主机解析

`craft_create_job` 接收路径，按 MCP 壳所在主机解析；传本机路径，工具看不到。本次改为直传后端：

```bash
curl -sS -X POST "http://<backend-host>:5199/api/jobs" \
  -F "files=@drawing.png" \
  -F "library_key=default"
```

拿到 `job_id` 后，后续全走 MCP。

### 2.2 识别耗时

从 `queued` 到 `extracted` 约 70 秒，进度长时间停在 35%。必须轮询。

### 2.3 特征召回率

一张信息量较大的轴类图纸，只提取出 8 个特征：

- 4 个尺寸：总长、最大外径、端部外径、端部螺纹。
- 4 个 YOLO 结构：螺纹、四方、键槽、端面腰型键。这里的「四方」指 **YOLO 给出了检测框**，不等于图上存在该结构——下一小节的 3.3 说明这个框是误检，存在性按人工判断处理。

图上的 180、70、285.5、1047、278±0.05、195±0.05、Ø62±0.1、Ø95±0.05、SR94/SR92.9 等均未进入特征表。最终工艺卡里的尺寸主要来自模板槽位，而不是这些特征。

**结论：特征提取服务于模板匹配和少量尺寸替换，不要指望它完整还原图纸。**

## 3. 特征复核

### 3.1 `feature-review` 实际是整表替换

`patches/02` 建议改成合并语义，但**该改动尚未实现**。实测只提交 `{feature_id, decision}` 的 8 条决策后：

- `review.features` 被整体替换成这 8 条决策对象；
- 原有的 `role`、`value`、`confidence`、`evidence` 全部丢失；
- 计数从 `confirmed=1, needs_review=7` 变成 `confirmed=0, needs_review=0, unresolved=8`。

即：**一次错误形状的提交会冲掉识别结果。**

恢复方式：提交前保存完整 workbench；把原始特征对象整体回传，并同时带 `status`（confirmed/rejected）和 `decision`（accept/reject）。原始尺寸候选仍可从 `extraction.drawing_feature_fusion.structured_candidates` 取回。

### 3.2 拒绝项仍计入 `unresolved`

3 个 YOLO 误检标成 `status=rejected` 后，`counts.unresolved` 仍为 3，一直不归零。`feature-presence` 把流程推进到 match 后 `blocking_action` 才前进。计数语义不一致：拒绝 ≠ 已处理。

### 3.3 YOLO 框错 ≠ 特征不存在

三个待复核结构的实际情况：

| 结构 | YOLO 框位置 | 实际判断 |
| --- | --- | --- |
| 键槽 | 尺寸标注区（误检） | 技术要求明确「键槽及周围 5mm 不氮化」，A-A 剖面有键槽 → 存在 |
| 端面腰型键 | A-A 剖面（误检） | B 向视图有腰型槽（R14、28±0.026）→ 归入球头带键槽 |
| 四方 | 过渡圆角（误检） | 主视图未找到 → 按人工判断处理 |

这里最容易犯的错是「检测框错就删特征」。正确做法是分开判断：**检测框可以否掉，特征存在性按图纸文字和视图另行确认。**

### 3.4 结构特征走另一条工具

- 特征表 → `craft_feature_review`
- `auto_features` / `low_frequency` 的「有/没有」→ `craft_feature_presence`

两套 ID：`yolo:1:1:四方` 与 `SQUARE`，容易混。本次提交 presence 后，服务端顺带触发了模板匹配，一步完成「保存结构 + 重新匹配」。

### 3.5 分支条件为空

材料、毛坯类型、路线前缀三个 branch condition 均为空，图上也没有材料。模板匹配仍能完成，说明它们不是硬门槛；但若模板库按材料分支，匹配质量会受影响。

## 4. 模板匹配与选择

### 4.1 候选列表不直接给参考图号

workbench 候选只含 `template_id`、匹配特征、工序数；参考图号在 `candidate.template_preview.reference_drawing` 里。

本次有 11 个候选，T01 与 T02 都是 `match_strength=complete`、18 道工序、四条特征全命中，但 T01 的参考图号等于当前图号，T02 是另一张图（更大尺寸档）。**只看 match_strength 会选错。**

### 4.2 `select_template` 超时但服务端成功

客户端 60 秒超时，返回 `connection_error`。按文档先读 workbench：

- revision 从 4 → 5；
- `selected_template_id=T01`；
- stage 已到 replace。

期间后端短暂拒绝连接，随后自行恢复。**超时不等于失败；重试才会造成并发写。** 正确动作是读 workbench，看到已选就继续。

## 5. 槽位与正式卡

### 5.1 槽位候选事实绑定错误

工序 30/50 的小头 Ø64 槽位状态为 `unresolved`，但 `candidate_facts` 给的是 Ø164 和 Ø157，与 Ø64 完全不符；`conflicting_values` 则是「Ø64，-0.42，-0.445」和「Ø64」。最后只能人工直接写值，不走候选事实绑定。

### 5.2 VLM 读错公差

服务端把某外圆 Ø157 读成 `+0.01/0`，并提示「与模板参考值 +0.1/0 不一致，以图纸为准」。放大原图后确认，图上就是 **+0.1/0**，模板反而正确，是 VLM 多读了一个 0。

**公差必须放大原图人工核对，不能信服务端的「以图纸为准」。**

### 5.3 派生槽位覆盖人工确认值

后端 turning 规则：

- Ø164 0/-0.13 → 车至 -0.05/-0.13（模板为 -0.05/-0.10）
- Ø157 +0.1/0 → 车至 +0.05/0（与模板一致）

`slot-review` 时明确提交了 -0.05/-0.10，正式卡生成后工序 30 仍然是 -0.05/-0.13。说明**派生槽位在生成阶段被重新计算，人工确认值没有最高优先级**。

修正方式：用 `craft_edit_process_card` 整体替换 operations，把该处改回 -0.05/-0.10。

### 5.4 `generate` 是空操作

槽位全部 `confirmed`（revision 6）后调用 `craft_generate_process_card`，返回 200，但 `process_card` 仍为 null，`blocking_action` 还是 `export_card`。

真正生成 official 卡的是 `craft_review_slots`（revision 6 → 8）。在此之前导出，工序 30/50 会保留「待确认」占位。

### 5.5 导出实际是 XLSX

响应头：

```
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
```

文件头 `50 4B 03 04`（ZIP/XLSX）。按实际类型存成 `.xlsx` 才能打开。

另外 MCP 的 `craft_export_process_card` 会把文件落在壳主机目录，本机拿不到。必须直连后端：

```bash
curl -sS -o process-card.xlsx \
  "http://<backend-host>:5199/api/jobs/<job_id>/process-card/export"
```

## 6. revision 时间线

| 步骤 | revision | 结果 |
| --- | --- | --- |
| 初始识别完成 | 0 | review，confirm_features |
| 错误形状的 feature-review | 0 → 1 | 特征表被冲掉，unresolved=8 |
| 完整特征对象重新提交 | 1 → 2 | confirmed=5，unresolved=3 |
| feature-presence | 2 → 4 | match，11 个候选，推荐 T01 |
| select_template（客户端超时） | 4 → 5 | 服务端已选 T01，review_slots |
| update_slots | 5 → 6 | 7 个槽位 confirmed |
| generate（空操作） | 6 | process_card 仍为 null |
| slot-review | 6 → 8 | official 卡生成，18 道工序 |
| edit_process_card | 8 → 9 | 修正派生公差 |

## 7. 跑通的关键前提

1. **同图号参考卡最省事，但不是跑通的前提。** 槽位值和工艺文本本来就属于这张图，替换只是校正。同日另一次运行里模板库没有同图号卡（参考图号与当前图号不同），卡仍然生成了，且与逐项核对过的版本一致——**但这依赖模板正文恰好不含被判错的那几个尺寸**，不等于可信。没有同图号卡时，槽位绑定、工序内容和参考图号必须逐项核对，选择记为人工选择。
2. **写操作前保存完整 workbench。** 否则 `feature-review` 的整表替换无法恢复。
3. **超时后先读状态、不重试。** 避免重复选模板。
4. **可疑项回图核对，不做全量。** 公差只在量级不符或有矛盾时放大原图；派生值以服务端为准、不重算，理由是重算会引入第二个数。见 [05 §5.5](05-agent-playbook.md)。

## 8. 由本次证据支持的修复优先级

| 优先级 | 问题 | 建议 |
| --- | --- | --- |
| P0 | `feature-review` 整表替换 | 服务端强制合并语义；缺 role/value 时拒绝而不是覆盖 |
| P0 | 派生槽位覆盖人工值 | 人工确认值优先级最高，派生规则只填充未确认槽位 |
| P1 | `select_template` 同步长事务 | 改异步任务（202 + job_id），或客户端超时后自动查状态 |
| P1 | Ø64 事实绑定错误 | 按 nominal/location 匹配，别把 Ø164/Ø157 塞给 Ø64 槽位 |
| P2 | `generate` 空操作 | 未复核时返回明确 409，而不是 200 + null |
| P2 | 计数语义 | `rejected` 不应计入 `unresolved` |
| P2 | 公差 OCR | 保留原始文本，对 `+0.1` / `+0.01` 这类歧义强制人工确认 |
| P3 | 导出格式与落盘 | 文档与响应头对齐；提供客户端可下载的产物地址 |

每条对应的提案与当前状态见 [06](06-optimization-plan.md)。

## 9. 补充观察：门禁信号矛盾与合法公差被拒（另一次运行）

> 2026-10-22，另一张图纸。本节记录的是使用者侧复述的现象，没有与第 1–6 节的时间线合并，也没有补齐 revision 明细。

### 9.1 摘要与详细校验互相矛盾

工作台摘要看起来没有未解决项，`blocking_action` 也已经越过槽位复核，但 `replacement.validation.status` 是 `partial`，详细校验里仍有未解决槽位。

这类矛盾的危险在于两个方向都会错：只看摘要，会把「参数已写入」当成「正式卡已具备生成条件」；只看详细校验，又会因为状态机已经前进而卡住。二者不是同一次校验的投影，客户端只能自己发明优先级。

### 9.2 合法公差被反复判格式无效

图上写的是 Ø75（0/−0.2），提交后被判格式无效。换了几种写法继续提交，状态没有任何推进——既没有变成 confirmed，也没有给出可执行的修复动作。

这暴露的是取值模型的问题：槽位只有字符串，校验器只能从显示文本里解析工程标注，合法但不在解析器词表里的写法就会被当成错误。反复猜格式没有让状态收敛，正确动作是在一次有依据的提交后停下。

### 9.3 模板来源不匹配

本次还出现过参考图号与当前图号不一致、由使用者明确选择其他模板的情况。现有流程只要求看 `reference_drawing`，没有要求把「当前图号 / 参考图号」并列展示，也没有要求把这种选择记录成人工选择。补上记录后，生成前的槽位与工序核对才有明确对象。

### 9.4 由本节支持的提案

- [patch 11](../patches/11-state-source-consistency.md)：门禁信号同源，矛盾时返回明确错误。
- [patch 12](../patches/12-structured-dimension-fields.md)：名义尺寸与上下偏差结构化，字符串只作展示。
- [patch 13](../patches/13-confirmation-states.md)：保存、人工确认、过闸三态分开表达。

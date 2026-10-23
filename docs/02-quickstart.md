# 02 · 快速开始：从接入到出卡

这一页给**人**看，走完整条链路并给出每一步的验收判据。要驱动它的 agent 看 [05-agent-playbook.md](05-agent-playbook.md)；这一步为什么这样设计，看 [03-workflow-and-gates.md](03-workflow-and-gates.md)；真实运行的证据与时间线在 [07-field-notes.md](07-field-notes.md)。

占位符：`<mcp-host>` 是 MCP 壳，`<backend-host>` 是业务后端。地址不在仓库里，按 [08-endpoint-discovery.md](08-endpoint-discovery.md) 的顺寻找。

## 1. 接上

```json
{
  "mcpServers": {
    "craft-process": {
      "type": "http",
      "url": "http://<mcp-host>:<mcp-port>/mcp"
    }
  }
}
```

新建的会话才会加载工具清单；已经跑着的客户端通常不会热刷新。

不依赖客户端库验证壳：

```bash
curl -sS -X POST "http://<mcp-host>:<mcp-port>/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
```

判据：`200` + 响应头有 `mcp-session-id` + body 里有 `serverInfo`。不要用 `/health` 判活，这个端口可能没有该路由。

## 2. 把图纸送到服务端

这一步最容易误解：`craft_create_job` 收的是**路径**，并且在**壳所在主机**解析，不在你的笔记本上，也不在后端主机上。

两条可用路径：

**A. 文件对壳可见。** 把图纸放到壳能读的位置，传那个路径。

**B. 直接上传到后端。** 后端接受 multipart。不知道地址就按 [08](08-endpoint-discovery.md) 找，或用 `tools/craft_discover.py` 验证一个短名单，不要扫端口。

```bash
export CRAFT_BACKEND_URL=http://<backend-host>:<backend-port>
python tools/craft_upload.py --file ./drawing.png
# job_id   40d8e960017045b583a78b91d1a07b6f
# 耗时     1.8s    HTTP 202
```

这个脚本存在的理由是：上传是唯一一个「客户端超时就把整次运行毁掉」的步骤。`GET /api/jobs` 不是列表接口，返回 `405`（`Allow: OPTIONS, POST`），`job_id` 没拿到就无法通过 API 找回，只能请人去看工作台。所以它在发字节**之前**先把 attempt 写进 `~/.config/craft-process/jobs.jsonl`：

```json
{"event":"attempt","attempt_id":"…","sha256":"…","file":"…","backend":"…"}
{"event":"result","attempt_id":"…","job_id":"40d8e960017045b583a78b91d1a07b6f"}
{"event":"timeout","attempt_id":"…","seconds":180}
{"event":"failed","attempt_id":"…","http":413,"detail":"…"}
```

`job_id` 是后端原样返回的 32 位十六进制串，脚本不加工、不加前缀，`--list` 里的写法与 API 一致。台账四种事件：`attempt`（发字节前）、`result`、`timeout`（状态未知）、`failed`（被拒或连不上）。

超时会留下一条没有 result 的 attempt——既不是成功也不是失败，脚本如实标记为未知，不猜：

```bash
python tools/craft_upload.py --list                       # 成功 / 失败 / 未知，逐条列出
python tools/craft_upload.py --file ./drawing.png --force  # 对账确认没建出来，再重传
```

退出码：`0` 上传成功；`4` 同一文件在复用窗口内传过（返回已有 `job_id`，加 `--force` 才新建）；`2` 状态未知；`3` 被拒或连不上。默认等待 180 秒——10 秒不够，正是它制造了「到底成没成」的死胡同。拿到 `job_id` 后，后续步骤走 MCP。

只收 PDF / PNG / JPG，其他格式在上传阶段就被拒。

> 路径不是文件。把本机路径传给远程工具不会传输任何字节，工具只是看不见它。如果工具报「文件不存在」而你确认文件在，原因就是这个。彻底修法见 [patch 3](../patches/03-file-content-input.md)。

## 3. 等识别

识别是异步的。轮询到终态：

```bash
curl -sS "http://<backend-host>:<backend-port>/api/jobs/<job_id>"
```

判据：`status` 到 `extracted`，`progress` 为 `100`。`queued` / `running` 期间不要重复 create，那会重复消耗一次识别算力。

走 MCP 就用 `craft_get_job` 或 `craft_wait_job`。

## 4. 读工作台

```bash
curl -sS "http://<backend-host>:<backend-port>/api/jobs/<job_id>/workbench?detail=full"
```

工作台里有 `revision`、`current_stage`、`blocking_action`、各阶段状态、`review.features` 特征表，以及后续的 `replacement`（模板）和槽位数据。

两个字段先看：

`blocking_action` 是服务端拒绝跳过的下一步，常见值有 `confirm_features`、`select_template` 和槽位复核。

`detail=full` **不是所有构建都认**：实测一个部署上 `detail=full`、`view=full`、不带参数三种请求返回完全相同的载荷（19 个键、字节数一致），即参数被忽略、恒返回全量。带上它不会错，但别据此判断「拿到了全量」。**读之前先核对返回体里的 `job_id`**，如果像另一个任务的数据，停下，见 [04 第 9 条](04-troubleshooting.md)。

## 5. 特征复核

每个特征都是完整对象：id、role、中文名、value、unit、confidence、status、provenance、校验原因。服务端把 `POST /feature-review` 当作**整表替换**，不是补丁。只发 `{feature_id, decision}`，其余字段会被删除，状态塌陷，工作台倒退。

正确流程：读完整表 → 只改需要改的对象 → 设置 `status` → 把整个数组回传。`value` 在 MCP schema 里是字符串，数字会被壳的校验拒绝。细节见 [patch 2](../patches/02-feature-review-payload.md) 与 [03](03-workflow-and-gates.md)。

判据：`counts.needs_review` 归零，`blocking_action` 前进。

**每一处确认都应有人看过。** 批量代替人确认不属于流程的一部分；要人确认时按 [09](09-asking-humans.md) 的格式问。

## 6. 模板匹配与选择

`craft_template_match` 计算候选，是预览。**候选不等于已选**，没选就生成会返回 `409`。

候选在 `decision.candidates`，不在 `replacement`；`replacement` 在选择前是 null，不要等它填充再匹配。

`match_strength` 不足以做选择：真实运行里候选可以全部是 `complete`，区别只在 `template_preview.reference_drawing`。参考图号等于当前图号的，槽位值和工艺文本本来就属于这个零件；不同图号意味着你在借另一档尺寸。**先看参考图号再选。**

参考图号不一致时，把「当前图号 / 模板参考图号」并列给做决定的人看，并说明这意味着槽位和工序来自另一档尺寸。对方明确选择其他模板时可以遵从，但要把它记为**人工选择**，并在生成前重点核对槽位和工序内容——这不是系统推荐的结果。

`craft_select_template` 提交选择。真实图纸上这一步可能超过客户端默认超时。客户端超时**不代表服务端失败**：先重读工作台看 `revision` 和选择状态，再决定是否重试。

判据：`blocking_action` 越过模板选择。不要拿 `selected_template_id` 当唯一判据——有些构建里选择成功后它仍然是 null，阶段和阻断状态才可靠。

## 7. 填槽位

`craft_update_slots` 写值，`craft_review_slots` 记录复核。值只能来自图纸或人工决定；车、磨、镗余量这类派生值由后端计算，不得当原始事实写入。

两处真实运行里出现过的行为，看到绿勾之前值得核一遍：

候选事实可能绑错槽位。一个 Ø64 面的槽位被建议了 Ø164 和 Ø157，属于别的直径。接受前先比 nominal。

派生槽位可能在生成阶段被重算，忽略你确认过的值。卡和槽位不一致时，先逐行比对，再显式修正生成的卡，不要假定复核被静默丢弃。见 [patch 8](../patches/08-slot-value-authority.md)。

## 8. 生成工艺卡

`craft_generate_process_card` **不一定是真正出卡的那一步**。真实运行里它返回 `200`，`process_card` 仍是 null；official 卡要等 `craft_review_slots` 之后才出现。

所以判据看状态，不看返回码：读工作台，要求 `process_card.mode == "official"` 且 `operations` 非空。`generate` 之后仍是 null，就调 `craft_review_slots` 再读一次。卡没出来就导出，只会得到占位行。

生成前先过一道门槛，四个字段一起读：`replacement.validation.status`、`unresolved_slots`、`blocking_action`、`process_card`。只要详细校验还有未解决槽位，就不生成、不导出；摘要与详细校验互相矛盾时重读一次，仍矛盾就停下报告。判据与原因见 [03 的出卡门槛](03-workflow-and-gates.md#出卡门槛四个字段一起看)。

`craft_edit_process_card` 用于生成后的人工改行。只是措辞或派生值要改时用它，不要重新生成。

## 9. 导出

`craft_export_process_card` 走壳时可能把产物写进壳所在容器的目录，调用方拿不到。改为直接对后端导出：

```bash
curl -sS -o process-card.xlsx \
  "http://<backend-host>:<backend-port>/api/jobs/<job_id>/process-card/export"
```

按响应 `Content-Type` 和文件头判断格式，不要信文档里的后缀：有些构建返回 XLSX，而文档写的是 CSV。见 [patch 4](../patches/04-timeout-and-export.md)。

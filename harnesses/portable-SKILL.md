# craft-process 工艺工作台（单文件版）

给没有技能系统、也装不了 MCP 的 harness 用：把这份文件整个放进系统提示或项目规则。有技能系统时用拆分的两个 skill，别用这份。

把二维图纸跑成模板工艺卡。服务两层：MCP 壳（`:8764/mcp`）+ 业务后端（Flask，`:5199`）。本流程推荐直接用 CLI，不依赖 MCP 客户端。

## 铁律（先读这段）

不写图上没有、也没人确认过的值。不把候选当选择。不把派生值当事实。不跳过人工确认。不把失败当成功继续往下走。不猜地址、不扫网段。

出错、卡住、状态不对时：停下并列出证据，是正确结果。

## 0. 地址

按顺序：`CRAFT_BACKEND_URL` 环境变量 → `~/.config/craft-process/endpoints.json` → 问部署负责人。都没有就停。

## 1. 一次完整链路

```bash
export CRAFT_BACKEND_URL=http://<backend-host>:5199
python tools/craft_flow.py upload drawing.png
python tools/craft_flow.py wait
python tools/craft_flow.py dump
python tools/craft_flow.py previews --download ./previews
python tools/craft_flow.py review   --answers review.json
python tools/craft_flow.py presence --answers presence.json
python tools/craft_flow.py match
python tools/craft_flow.py select T10
python tools/craft_flow.py slots    --values slots.json
python tools/craft_flow.py finalize
python tools/craft_flow.py edit     --operations ops.json
python tools/craft_flow.py export process-card.xlsx
```

随时用 `python tools/craft_flow.py status` 看阶段、阻断点和下一步。没有 CLI 时按下面各节的 REST 契约手打。

## 2. 上传

`POST /api/jobs`，multipart 字段 `files`，只收 PDF / PNG / JPG，返回 `202` + 32 位十六进制 `job_id`。

**发字节之前先记 attempt**（`~/.config/craft-process/jobs.jsonl`）：`GET /api/jobs` 返回 `405`，没有任务列表，`job_id` 丢了只能靠账本对账。超时是状态未知——对账确认没建出来再重传。

`craft_create_job` 收的是路径且在**壳所在主机**解析，传本机路径不会传输任何字节。

## 3. 等识别

`GET /api/jobs/{id}` 到 `status=extracted`、`progress=100`。约 70~90 秒，长时间停在 35% 是正常的。

## 4. 读工作台

`GET /api/jobs/{id}/workbench`（`detail=full` 在部分 build 被忽略）。

必看 `revision`、`current_stage`、`blocking_action`，并核对 `job_id` 一致。`blocking_action` 的推进顺序：`confirm_features` → `select_template` → `review_slots` → `export_card`。

## 5. 特征复核

`POST /feature-review` 是**整表替换**。只发 `{feature_id, decision}` 会删掉 role/value/confidence，且不报错。

取 `review.features` 完整数组 → 就地改 → `status` 置 `confirmed` → `value` 转**字符串** → 整个数组回传，带 `revision`。

```json
{"revision": 0,
 "features": [{"feature_id": "overall_length:1", "role": "overall_length",
               "value": "1786", "status": "confirmed"}]}
```

判据：`counts.needs_review == 0`，`blocking_action` 前进。

### 矛盾扫视（20–30 秒）

列给人之前扫一遍，只找图上根本不存在的数。不做全量核对；但幽灵值必须标出。每项必须带部位（"小端轴段""最大外圆"）——只有数字的清单无法被质疑，只能被盖章。

实测同一张图三次：最大外径 `108`（图上没有）、总长 `1776`（取了紧邻尺寸线，真值 1786±0.3）、端部外径 `80`/`90`/`75`（图面 Ø72±0.13，75 是别处的值绑错了位置）、螺纹 `2A`（图面 3A）。

> 错值可能不进卡：模板正文不含该数值时，错值照样产出看起来正常的卡。那是模板粗糙，不是闸门有效。

## 6. 结构特征与分支条件

`POST /feature-presence`。**`features` 必须是列表**，传对象返回 422：

```json
{"features": [{"feature_id": "KEYWAY", "presence": "yes"}],
 "branch_conditions": {"material": "GH901", "billet_type": "大锻件", "route_prefix": "28F"},
 "revision": 3}
```

分支条件不填会卡在 `confirm_features`。图纸上通常没有材料，只能问人。提交后顺带触发匹配。

## 7. 模板

候选在 `decision.candidates`；`replacement` 选择前为 null。

**别只看 `match_strength`**：候选可以全是 `complete`，区别在 `template_preview.reference_drawing`——等于当前图号才是本档，否则是借档。

**选之前先看 `required_features` / `missing`**，缺结构当场问人。`POST /template-selection` 要 `template_id` + `revision`，可能跑 48~60 秒。

**超时不等于失败**：先读工作台，`revision` 前进且已选就继续。

## 8. 槽位

`POST /slots` 写值，`POST /slot-review` 记录复核并出卡。

```json
{"values": {"T10-30-0": {"value": "φ77，0，-0.025"}}, "revision": 6}
```

值格式跟 `display_value` 走（全角逗号、φ 前缀）。图纸事实 / 人工决定 / 后端派生三类不可混用；`source: derived_tolerance` 的派生槽位留空。

写入不会消项，`unresolved_slots` 仍列全部；**必须再调 `/slot-review`**（`{"values": {}, "revision": n}`）才会 `validation.status=ok`。

槽位确认属于本次 job，值相同也要重新列给人。

**公差被拒不要猜格式**：一次有依据的提交后仍被拒，保留图纸事实并停下。

## 9. 出卡与导出

`generate` 可能返回 200 但 `process_card` 仍是 null。**出卡前四字段一起看**：`replacement.validation.status`、`unresolved_slots`、`blocking_action`、`process_card`（`mode == official` 且 `operations` 非空）。摘要与详细校验矛盾时重读一次，仍矛盾就停。

导出直连后端（走壳会把文件写进容器）：

```bash
curl -sS -o process-card.xlsx "$CRAFT_BACKEND_URL/api/jobs/{id}/process-card/export"
```

按 `Content-Type` 与文件头判断格式，别信文档后缀。

## 9.5 预览与改卡

`GET /previews` 列图、`GET /previews/{rel}` 取图；复核单需要这张图才能做成可点选页面，没有就退回文字问答。

生成后用 `POST /process-card-edit` **整体替换** `operations`（不要重新生成——重跑复核时规则会再算一次）。三条硬要求：

1. `工时` 一律转字符串——数字 `0` 会被当成空值，0 工时工序的工时格变空白，其他行正常，很难发现。
2. 改前存一份当前 `operations`，改后导出与改前逐行比对，不要只看 200。
3. 回读条数要与提交一致。

## 10. 故障速查

| 症状 | 原因 | 动作 |
| --- | --- | --- |
| 握手正常但工具连不上 | 壳到后端那一跳 | 改地址后**重建**容器，`restart` 不重读 env |
| 工具报「文件不存在」 | 路径在壳主机解析 | 改用 multipart 直传 |
| 写操作 409 | revision 过期 | 重读后再写，不重发同一载荷 |
| 有候选但生成 409 | 候选 ≠ 已选 | 先 selection |
| 选模板超时 | 同步长事务 | 读工作台，已选就继续 |
| 导出成功但没文件 | 文件落在壳容器 | 直连后端 |
| 复核后特征表塌了 | 发了最小载荷 | 用保存的完整表回传，或重新识别 |
| 摘要干净、详细校验 partial | 状态不同源 | 四字段一起读，仍矛盾就停 |
| 工作台返回别的任务 | 多 worker 落错 | 写之前停下 |

## 11. 无人值守

只跑 `upload` → `wait` → `dump`，然后把待确认项落成问题清单停下，等人确认后再从 `review` 续。自动确认等于把责任转给不会说话的脚本。

## 事实源

`https://github.com/jayyuan667/craft-process-mcp-guide`。冲突时以仓库为准，并回报冲突。

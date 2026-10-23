# 06 · 优化方案与当前状态

这份方案回答一个问题：**要让另一个 agent 不读文档也能安全走完整条链路，最少要改什么。**

先看状态，再看方案。下表是 2026-10-22 在真实部署上观察到的结果；补丁本身是对上游服务的提案，本仓库无法验证上游代码，所以「未实现」只代表观察到的行为还没变。

## 补丁状态

| # | 补丁 | 状态 | 观察到的依据 |
| --- | --- | --- | --- |
| 1 | [后端地址可配置](../patches/01-api-base-url.md) | 部署侧已修，上游未合入 | 壳指向容器可达地址后业务工具恢复 |
| 2 | [复核合并语义](../patches/02-feature-review-payload.md) | 未实现，客户端绕过 | 最小载荷仍会冲掉整张特征表 |
| 3 | [文件内容入参](../patches/03-file-content-input.md) | 未实现，客户端绕过 | 仍只收路径，需 multipart 直传后端 |
| 4 | [超时与导出](../patches/04-timeout-and-export.md) | 部分：客户端绕过了导出 | 选模板仍可能超 60s；导出改由客户端直连后端，落壳容器的问题仍在服务端 |
| 5 | [预览工艺卡工具](../patches/05-draft-process-card-tools.md) | 未实现 | 页面有、MCP 无 |
| 6 | [`next_action` 工具](../patches/06-next-action-tool.md) | 未实现 | 阻断点仍需客户端自己推导 |
| 7 | [任务状态一致性](../patches/07-state-consistency.md) | 待确认 | 串号只观察到一次，未复现 |
| 8 | [槽位取值权威](../patches/08-slot-value-authority.md) | 未实现 | 生成阶段仍覆盖人工确认值 |
| 9 | [生成语义与计数](../patches/09-generate-semantics.md) | 未实现 | `generate` 仍会 200 空操作；`rejected` 仍计入 unresolved |
| 10 | [后端地址自披露](../patches/10-backend-address-discovery.md) | 未实现 | `craft_health` 仍不返回 `backend_url` |
| 11 | [统一状态来源](../patches/11-state-source-consistency.md) | 未实现 | 摘要与详细校验可互相矛盾（见 07 §9） |
| 12 | [结构化尺寸字段](../patches/12-structured-dimension-fields.md) | 未实现 | 合法公差仍会因字符串格式被拒（Ø75 0/−0.2） |
| 13 | [三态区分](../patches/13-confirmation-states.md) | 未实现 | 保存 / 人工确认 / 过闸仍共用一个成功口径 |

## 现状

页面（`WORKBENCH / V2`）是 7 阶段状态机：

```
图纸输入 → 视觉检测 → 语义提取 → 特征校正 → 模板匹配 → 参数替换 → 工艺卡片
```

MCP 有 17 个工具，覆盖了大部分 REST 端点，但没有覆盖状态机的全部动作。缺口集中在三处：预览工艺卡、下一步提示、写入安全。

| 页面动作 | 后端端点 | MCP 工具 | 状态 |
| --- | --- | --- | --- |
| 上传图纸 | `POST /api/jobs` | `craft_create_job` | 只收路径 |
| 特征有/无、分支条件 | `feature-presence` | `craft_feature_presence` | 有；结构特征（含四方）与分支条件走这条，它是 match 的前置 |
| 特征值修正 | `feature-review` | `craft_feature_review` | 有，整表替换，危险 |
| 模板候选 | `template-match` | `craft_template_match` | 有 |
| 采用模板 | `template-selection` | `craft_select_template` | 有，可能超时 |
| 槽位确认 | `slots` / `slot-review` | `craft_update_slots` / `craft_review_slots` | 有，强制逐项传值 |
| **预览工艺卡** | `GET/PUT /draft-process-card` | **无** | **缺** |
| **预览卡导出** | `GET /draft-process-card/export` | **无** | **缺** |
| 正式卡生成 | `process-card` | `craft_generate_process_card` | 有 |
| 正式卡编辑/导出 | `process-card-edit` / `export` | 有 | 导出落在壳主机 |
| 二分对照 | 前端 | 无（也不需要） | 说明即可 |

## 目标

三个可验收的结果：

agent 只读 `craft_next_action` 和 `craft_get_workbench` 就能走完 7 个阶段，不需要读任何文档。

任何一次写操作都不会因为「少传字段」而丢数据；出错时状态不变。

一次真实图纸全链路里，假超时和跨任务串号都为零。

## 第一批：止血

不做这几件，agent 不能上生产。

**文件入参。** `craft_create_job` 接受 `{name, content_base64}` 和 URL，保留路径形式。上限 32MB，按字节嗅探类型，URL 禁内网地址。见 [patch 3](../patches/03-file-content-input.md)。

**复核写入。** `feature-review` 改成合并语义，只有显式 `replace=true` 才整表替换；`value` 接受数字；未知 id 返回 4xx。见 [patch 2](../patches/02-feature-review-payload.md)。

**超时语义。** 选模板单独给 180–300 秒；错误里带「先读 workbench 再决定是否重试」。见 [patch 4](../patches/04-timeout-and-export.md)。

**槽位取值权威。** 人工确认 > 图纸事实 > 派生 > 模板默认；生成阶段不得覆盖已确认值；候选事实按 nominal 绑定，宁可为空也不给近似值。见 [patch 8](../patches/08-slot-value-authority.md)。

**生成语义。** 未复核时 `generate` 返回 409 或直接出卡，不能 `200 + null`；`rejected` 不计入 `unresolved`。见 [patch 9](../patches/09-generate-semantics.md)。

**后端地址自披露。** `craft_health` 返回 `backend_url` 与版本号；调用方不必再扫端口。见 [patch 10](../patches/10-backend-address-discovery.md)。

**统一状态来源。** `counts`、`blocking_action`、`validation` 从同一份校验结果生成；矛盾时返回明确的 `state_inconsistent`，而不是一个看起来可以继续的载荷。这是与「出卡门槛」配套的服务端改动，优先级等同第一条。见 [patch 11](../patches/11-state-source-consistency.md)。

验收：每条一个集成测试，外加一张真实图纸从头到尾。

## 第二批：对齐页面

**补预览卡。** 四个工具，对应 `GET/PUT /draft-process-card` 和它的导出。见 [patch 5](../patches/05-draft-process-card-tools.md)。

**加下一步提示。** `craft_next_action` 返回当前阻断点、revision 和下一个工具的完整参数骨架。见 [patch 6](../patches/06-next-action-tool.md)。

**按页面语义修工具。** 特征校正默认走 `feature_presence`（有/无 + 分支条件），只有改具体值才用 `feature_review`；`slot_review` 允许空 `values`，与页面行为一致。

**结构化尺寸字段。** 槽位拆成名义尺寸、上偏差、下偏差、单位、位置、视图和证据；显示字符串只作展示，不再作为解析源。见 [patch 12](../patches/12-structured-dimension-fields.md)。

**三态区分。** 保存、人工确认、过闸分开表达，校验失败的写入不得回显为「已确认」。见 [patch 13](../patches/13-confirmation-states.md)。

验收：一个只拿到工具清单、没有文档的 agent，能从上传走到导出正式卡。

## 第三批：生产化

导出回传字节或签名 URL，不写壳的目录。工作台按 `job_id` 取，不用进程内全局状态，写入前后校验 `job_id`。见 [patch 7](../patches/07-state-consistency.md)。

再加鉴权、HTTPS、`create_job` 幂等键、每任务阶段耗时与写入审计。

## 不建议做

自动确认特征、自动选模板、把多步合成一个万能工具、服务端自动填 `revision`。这四条都能让演示更顺，代价是拆掉三个人工闸门，出事时无法追溯。

## 度量

上线后看四个数：全链路成功率、假超时次数、写操作导致的状态回退次数、跨任务 `job_id` 不一致次数。前两个看可用性，后两个看安全性。

再加一个业务指标：**生成后与人工确认不一致的槽位数**。这个数不为零，说明取值权威没有落实；它比任何成功率都更能说明卡片能不能直接下发。

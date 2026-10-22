# 04 · 故障手册

按症状组织。每条先写你看到什么，再写查什么、做什么。**先定位断点，再重启**——在错误的层重启会毁掉证据。

更完整的机制说明见 [01](01-architecture.md)。地址找不到直接看 [08](08-endpoint-discovery.md)。

## 1. 工具连不上，但 MCP 握手正常

现象：`initialize` 返回 `200`，`tools/list` 返回预期工具，所有业务工具报连接错误，错误里带 loopback 地址。

检查：壳与后端是否同机、同网络命名空间。分别从你的机器和壳的环境请求后端 health。

原因：壳配置的后端地址是 `127.0.0.1` 或 `localhost`，在壳的命名空间里解析。容器里那就是容器自己。

处理：把后端地址改成从壳的命名空间可达的地址，然后**重建**容器——`restart` 不重新注入环境变量。见 [patch 1](../patches/01-api-base-url.md)。

## 2. MCP 端口上 `/health` 返回 404

现象：端口能连，根路径和 `/health` 都是 `404`，但 MCP 能用。

检查：向 `/mcp` 发 `initialize`。

原因：不是每个构建都在壳上暴露 health 路由，根路径也可能就是 404。

处理：把 `initialize` 成功当作存活判据；后端单独探它自己的 health。

## 3. 工具说文件不存在

现象：`craft_create_job` 报「文件不存在」，但文件明明在你机器上。

检查：路径在哪解析。工具读的是壳的文件系统，不是你的，也不是后端的。

原因：跨主机的路径参数不传输任何东西。

处理：把文件放到壳能读的位置，或直接用 multipart 上传到后端，拿返回的 `job_id` 继续。彻底修法是内容入参契约，见 [patch 3](../patches/03-file-content-input.md)。

## 4. 写操作返回 409

现象：`feature-review`、`slots` 或 `process-card` 返回 `409`，revision 不匹配。

检查：工作台当前的 `revision` 和阶段。

原因：你读过之后另一个写操作推进了 revision，或你在复用更早步骤的 revision。

处理：重读工作台，把意图应用到当前对象上，带新 revision 写。不要循环重发同一个载荷——revision 一直变说明有另一个客户端在写，停下来对账。

## 5. 已有候选，生成仍返回 409

现象：`template-match` 有候选，`generate` 返回 `409`。

检查：工作台里是否已有选中的模板。

原因：匹配是预览，选择是另一次提交。

处理：先 `select-template` 选中一个候选，再生成。

## 6. 选模板超时

现象：`select-template` 报超时或连接错误，任务仍在推进。

检查：工作台的 `revision`、`decision` 和模板字段。

原因：选择可能超过客户端或壳的请求超时。服务端可能在客户端放弃之后才提交。常见的 60 秒默认值太短，180–300 秒才现实。

处理：先读工作台再决定。已选就继续，不要重选；没选再带更长超时重试一次。见 [patch 4](../patches/04-timeout-and-export.md)。

## 7. 导出成功但没有文件

现象：`export` 返回成功，调用方目录里什么都没有。

检查：壳配置的下载目录。

原因：产物写进了壳的容器，客户端只拿到成功响应。

处理：直接对后端的导出端点请求并保存响应体。按 `Content-Type` 校验格式：有些构建文档写 CSV，实际返回 XLSX。

## 8. 复核之后特征表塌了

现象：提交复核后状态变成 unresolved，值消失，计数倒退。

检查：你发了什么。载荷里只有 feature id 和 decision 就是原因。

原因：端点整表替换，省略的字段被删除，不会保留。

处理：如果手上有副本，从工作台恢复，然后回传完整对象、设置 `status`、`value` 用字符串；否则重新识别。预防见 [patch 2](../patches/02-feature-review-payload.md)。

## 9. 工作台返回的是另一个任务

现象：请求任务 A 的工作台，返回体的 `job_id` 是任务 B，特征值属于另一张图。

检查：反复请求、每次比对 `job_id`；确认后端是不是多 worker 且状态在进程内存里。

原因：观察到于一个把工作台状态放在进程内存的部署，请求落到另一个 worker 就返回别的任务的快照。

处理：**写之前停下。** 对着错位的工作台发复核，可能改到别的任务。先确认部署让 worker 共享任务状态，或把请求钉在同一个 worker，再继续。每次写后都比对响应里的 `job_id`。见 [patch 7](../patches/07-state-consistency.md)。

## 10. 上传超时，没有 job_id

现象：multipart POST `/api/jobs` 在等待窗口内没有响应，没拿到 `job_id`。工作台查不了，agent 停下来问用户「是不是出现了任务」。

检查：请求是否真的发出去过；上传账本里有没有这个文件的 attempt——`python tools/craft_upload.py --list`。

原因：客户端先放弃了，这不能说明任务是否创建。API 没有恢复路径：`GET /api/jobs` 返回 `405`（`Allow: OPTIONS, POST`），任务无法枚举。等 10 秒且没有账本，就足以丢掉整次运行。

处理：不要盲目重传，但也不要卡死。按 sha256 对账；有 attempt 无 result 就是状态未知——用 `--force` 重传，并说明最多多一个孤儿任务，不影响已有结果。下次从 [02 §2](02-quickstart.md) 的 `craft_upload.py` 上传，它先记账再发字节、默认等 180 秒。agent 侧的决策表在 [05 §3](05-agent-playbook.md)。

## 11. 摘要显示没有未解决项，详细校验却是 partial

现象：`counts` / 摘要看起来干净，`replacement.validation.status` 是 `partial`，或者 `unresolved_slots` 非空而 `blocking_action` 已经允许生成。

检查：把四个字段一起读——`replacement.validation.status`、`unresolved_slots`、`blocking_action`、`process_card`，确认它们是不是来自同一次校验。

原因：摘要与详细校验走了不同的数据源，二者可以互相矛盾；这类矛盾在真实运行里出现过。

处理：重读一次工作台；仍然矛盾就**停下报告**，把四个字段原样列出，不生成、不导出。不要用「摘要看起来可以」当放行依据。见 [patch 11](../patches/11-state-source-consistency.md)。

## 12. 一个合法公差被反复判成格式无效

现象：图上写的是 Ø75（0/−0.2），提交后被判格式无效；换几种写法再提交，状态没有任何推进。

检查：图纸原文、工具文档里的取值格式，以及槽位字段是不是只有字符串。

原因：校验把显示字符串当成解析目标，没有名义尺寸与上下偏差的结构化字段，合法的工程写法会被格式规则误伤。

处理：确认原文和格式后做**一次**有依据的提交；仍被拒就保留人工确认的图纸事实并停下，把原文、提交值和错误响应一起转交。**不要继续猜格式。** 结构化字段的提案见 [patch 12](../patches/12-structured-dimension-fields.md)，状态区分见 [patch 13](../patches/13-confirmation-states.md)。

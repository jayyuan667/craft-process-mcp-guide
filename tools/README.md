# 工具参考

七个脚本都只依赖 Python 标准库，`review_sheet.py` 额外需要 Pillow。它们解决的是 MCP 工具本身覆盖不到、或者一超时就丢掉状态的那几步，以及「换一个 harness 怎么跑」这件事。

```bash
python3 --version        # 3.8+
pip install Pillow       # 只有 review_sheet.py 需要
```

共同约定：地址通过参数传，参数缺省时读环境变量 `CRAFT_MCP_URL` / `CRAFT_BACKEND_URL`；所有输出都是给人或给 agent 直接读的纯文本，`--json` 只输出后端原始响应。

## craft_flow.py

一条命令推进一步，状态存在 `~/.config/craft-process/state-<job>.json`。给任何能跑 shell 的 harness 用：不需要 MCP 客户端，也不需要记 REST 路径。步骤与 `answers` 文件格式见 [docs/11](../docs/11-portability.md)。

**实现已移到 `skills/craft-process-workbench/scripts/craft_flow.py`**，这样只下载技能目录的人也能拿到客户端；`tools/craft_flow.py` 保留为兼容入口，命令与退出码完全一致。装上技能后路径写成 `scripts/craft_flow.py`。

```bash
python tools/craft_flow.py health    # 验地址：200 且 service 名对得上
python tools/craft_flow.py upload drawing.png
python tools/craft_flow.py status
python tools/craft_flow.py previews --download ./previews
python tools/craft_flow.py review --answers review.json
python tools/craft_flow.py finalize
python tools/craft_flow.py edit --operations ops.json
python tools/craft_flow.py export process-card.xlsx
```

`edit` 会自动把 `工时` 归一化成字符串——传数字 `0` 会被服务端当空值（见 [docs/04 第 13 条](../docs/04-troubleshooting.md)）。

退出码：`0` 正常，`2` 网络或超时，`3` 服务端拒绝，`4` 状态不一致，`5` 四字段没过（不导出）。

## craft_upload.py

把图纸以 multipart 上传到后端，**在发字节之前**把这次尝试写进账本，并按 sha256 去重。`GET /api/jobs` 是 `405`，没有列表接口，`job_id` 丢了只能靠账本对账，所以这一步必须记账。

实现同样在 `skills/craft-process-workbench/scripts/craft_upload.py`，`tools/craft_upload.py` 是兼容入口。

```bash
python tools/craft_upload.py --file drawing.png --backend http://<backend-host>:5199
python tools/craft_upload.py --file drawing.png --timeout 300
python tools/craft_upload.py --list
python tools/craft_upload.py --file drawing.png --force
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--file` | — | 图纸，只收 PDF / PNG / JPG |
| `--backend` | `$CRAFT_BACKEND_URL` | 后端地址 |
| `--library-key` | `default` | 模板库键 |
| `--timeout` | `180` | 等待秒数；10 秒会制造「到底成没成」的死胡同 |
| `--ledger` | `~/.config/craft-process/jobs.jsonl` | 账本路径 |
| `--reuse-window` | `72` | 同哈希去重窗口（小时） |
| `--force` | 关 | 跳过去重，确实要新建任务 |
| `--list` | — | 列出账本，含没有 result 的未决上传 |
| `--json` | 关 | 只打印后端原始响应 |

退出码：`0` 上传成功或被复用；`4` 同文件在复用窗口内传过，返回已有 `job_id`；`2` 超时，**状态未知**；`3` 被拒或连不上。

`2` 的处理顺序是 `--list` 对账 → 按 sha256 / 文件名 / 时间确认没建出来 → `--force` 重传，并说明可能多一个孤儿任务。见 [docs/04 第 10 条](../docs/04-troubleshooting.md)。

## craft_discover.py

验证后端地址，不扫端口。先问壳（`craft_health`）要服务名，再对短名单请求 `/health`，只有 `service` 与壳报告的一致才认可。

```bash
python tools/craft_discover.py --mcp http://<mcp-host>:8764/mcp
python tools/craft_discover.py --mcp ... --ports 5199,5200 --save endpoints.json
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--mcp` | 必填 | MCP 端点 |
| `--ports` | `5199` | 逗号分隔的候选端口 |
| `--save` | — | 把结果写成 JSON |

退出码：`0` 找到并验证通过；`2` 没找到；`1` 用法错误或连不上壳。输出里 `skip` 表示端口开着但服务指纹不匹配。见 [docs/08](../docs/08-endpoint-discovery.md)。

## review_sheet.py

把工作台的 full dump 和预览图做成一个自包含 HTML：每项一张卡片（编号、系统值、图上原文或裁剪图、四个选项），点完生成可回填的 JSON。不需要网络，也不需要对方有结构化提问能力。

```bash
python tools/review_sheet.py --workbench wb.json --image input-1.png --out sheet.html
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--workbench` | 必填 | `workbench?detail=full` 保存下来的 JSON |
| `--image` | 必填 | `craft_download_preview` 下载的页图 |
| `--out` | `review-sheet.html` | 输出文件 |

没有像素 bbox 的项不会被裁剪，但仍会出现在表里。看不清的项标成 `needs_review`，不会被悄悄当成确认。

## ask.py

把同一份 `questions.json` 渲染成不同 harness 能用的形式，并把人的回复解析回统一结构。字段定义与四种入口的选择规则见 [docs/10](../docs/10-harness-interaction.md)。

```bash
python tools/ask.py render --in q.json --format md   > questions.md
python tools/ask.py render --in q.json --format html > questions.html
python tools/ask.py render --in q.json --format json > prompt.json
python tools/ask.py tui    --in q.json --out answers.json
python tools/ask.py parse  --in q.json --reply "3=Φ72±0.05; 7无; 其余采用"
```

| 子命令 | 参数 | 说明 |
| --- | --- | --- |
| `render` | `--in`，`--format {md,html,json}` | 渲染；默认 `md` |
| `tui` | `--in`，`--out` | 终端逐项问答；**需要 TTY**，管道或沙箱里读到 EOF 会直接退出且不写文件 |
| `parse` | `--in`，`--reply` | 把 `3=值` / `3正确` / `7有` / `7无` / `7看不清` / `其余采用` 解析成统一 answers |

统一状态只有七个：`confirmed`、`corrected`、`present`、`absent`、`selected`、`skipped`、`unsure`。解析不了的部分保持 `unsure`，不会默认成正确。写库前先回显一次解析结果。

## skill_drift_check.py

检查 `skills/` 里的两份技能是否落后于它们所依据的 docs。比对的是 `skills/.skill-source.json` 里记录的提交与各权威文档的最新提交。

```bash
python tools/skill_drift_check.py            # 用本地 git
python tools/skill_drift_check.py --remote   # 用 GitHub 上的 main，不需要仓库在本地
python tools/skill_drift_check.py --update   # 改了 docs 并重新派生后，记录新提交
```

退出码：`0` 同源，`3` 有漂移（逐条列出哪个文档变了、最新提交说明），`1` 检查不了（网络或 git 不可用）。

## build_portable.py

从 `skills/craft-process-workbench/SKILL.md` 生成单文件版 `harnesses/portable-SKILL.md`。那份文件以前是手抄的，规则一改就漂；现在只允许生成。

```bash
python tools/build_portable.py           # 重新生成
python tools/build_portable.py --check   # 不同步时退出码 3
```

无人值守那段不在主技能里，单独放在 `harnesses/fragments/unattended.md`，生成时插到「事实源」之前。

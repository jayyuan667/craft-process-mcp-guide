# 10 · 不同 harness 的交互

同样一批确认项，在 Claude 桌面端、Codex 的文本框、终端、无人值守批处理里，表现方式差很多。不要为每个环境重写话术——**把问题定义成中立数据，再按环境渲染**。

## 四个档位

| 环境 | 能做到什么 | 用什么形式 |
| --- | --- | --- |
| Claude 桌面端 | 结构化选项、文件预览、HTML 渲染 | 少量决策用 `AskUserQuestion`（≤4 题，每题 2–4 个互斥选项）；数值或超过 4 项改成可点页面 |
| Codex / 纯文本框 | 只有一个输入框 | 编号表格 + 默认值 + 只改例外；给固定回复语法 |
| 终端 / 无图形界面 | 可写文件、可开浏览器 | 渲染 HTML 让人点选；或给 JSON/YAML 让人填完回传 |
| 无人值守 | 没有人 | 生成 `questions.json` 停下，等人补完再继续；**不猜** |

判断规则：**决策类、选项互斥、不超过 4 项 → 用原生控件；数值类、需要看图、超过 5 项 → 用页面。**

## 中立数据：questions.json

```json
{
  "title": "特征与尺寸确认",
  "note": "默认全部采用，只回需要改的项。",
  "items": [
    { "id": "overall_length", "label": "总长", "value": "1786",
      "evidence": "图上外侧 1786±0.3，1776 为内侧", "type": "text" },
    { "id": "small_end_outer_diameter", "label": "小端外径", "value": "Φ72",
      "evidence": "上偏差 +0.13，下偏差不清", "type": "text", "uncertain": true },
    { "id": "inner_key", "label": "右端头部内键槽", "value": "有",
      "evidence": "技术要求提到槽内表面氮化", "type": "presence" },
    { "id": "template", "label": "采用模板", "value": "T01",
      "evidence": "参考图号与本图一致", "type": "choice",
      "options": ["T01", "T02", "T23"] }
  ]
}
```

字段说明：`type` 取 `text`（数值/文本更正）、`presence`（有/无/看不清）、`choice`（从 options 里选）。`evidence` 是给人看的依据，不是给模型看的备注——没有依据的确认等于让人替你签字。

## 渲染

```bash
ask.py render --in q.json --format md    > questions.md    # 纯文本框
ask.py render --in q.json --format html  > questions.html  # 可点页面
ask.py render --in q.json --format json  > prompt.json     # 有结构化控件的 harness
```

`--format json` 输出的是中立的题目结构（id、序号、选项），由 harness 自己映射到它的控件。Claude 桌面端可以把前 4 个决策题映射成 `AskUserQuestion`，其余的走页面。

## 解析回复

```bash
ask.py parse --in q.json --reply "3=Φ72 +0.13/-0.02; 7无; 其余采用"
```

输出统一结构：

```json
{"answers":[
  {"id":"small_end_outer_diameter","status":"corrected","value":"Φ72 +0.13/-0.02"},
  {"id":"inner_key","status":"absent","value":"无"},
  {"id":"overall_length","status":"confirmed","value":"1786"}
]}
```

支持的语法：`3=值`（更正）、`3正确`、`7有` / `7无`、`7看不清`、`其余采用`。解析不了的部分保持 `unsure`，并在回显里单独列出——**不默认成正确**。

## 回显

写库之前把解析结果回显一次：

> 我理解为：3 改为 Φ72 +0.13/-0.02，7 无，其余采用。对吗？

这一步能挡掉绝大多数「用户以为改了、实际没改」的返工。

## 不要把 harness 的短板变成流程缺陷

纯文本框环境最常见的退化是「把所有问题写成一段散文，再让用户用编号回复」。这不是能力限制，是表达选择。同样的环境，换成表格 + 默认值 + 固定语法，人力成本差好几倍。

反过来，有结构化控件的环境也别滥用：`AskUserQuestion` 上限四题，把七个数值塞进去会被截断或被迫合并，反而不如直接给页面。

# 10 · 不同 harness 的交互

同样一批确认项，在 Claude 桌面端、Codex 的文本框、终端、无人值守批处理里，表现方式差很多。不要为每个环境重写话术——**把问题定义成中立数据，再按环境渲染**。

## 四个档位

| 环境 | 能做到什么 | 用什么形式 |
| --- | --- | --- |
| Claude 桌面端 | 结构化选项、文件预览、HTML 渲染 | 少量决策用 `AskUserQuestion`（≤4 题，每题 2–4 个互斥选项）；数值或超过 4 项改成可点页面 |
| Codex / 纯文本框 | 只有一个输入框 | 编号表格 + 默认值 + 只改例外；给固定回复语法 |
| 终端 / 无图形界面 | 可写文件、可开浏览器、有 TTY | `ask.py tui` 逐项问答；或渲染 HTML 让人点选；无人时给 JSON 让人填完回传 |
| 无人值守 | 没有人 | 生成 `questions.json` 停下，等人补完再继续；**不猜** |

判断规则：**决策类、选项互斥、不超过 4 项 → 用原生控件；数值类、需要看图、超过 5 项 → 用页面。**

这两个数字不是同一个上限，不要混：**4 是单次调用能塞进原生控件的题数**（`AskUserQuestion` 的上限），**5 是让人用文字对齐编号还不至于出错的项目数**（[09](09-asking-humans.md) 的四条硬规则）。一批 5 项可以拆成两次控件调用，也可以直接给页面；但不该把 5 项硬塞进一次控件调用。

## 中立数据：questions.json

```json
{
  "title": "特征与尺寸确认",
  "note": "默认全部采用，只回需要改的项。",
  "items": [
    { "id": "overall_length", "label": "总长", "value": "1786",
      "evidence": "图上外侧 1786±0.3，1776 为内侧", "type": "text" },
    { "id": "small_end_outer_diameter", "label": "小端外径", "value": "Φ72",
      "evidence": "图上 Ø72±0.13", "type": "text" },
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

## 终端 TUI

有 TTY 但没有任何控件时，别让人对着编号表格自己对齐，直接逐项问：

```bash
ask.py tui --in q.json --out answers.json
```

```
[3/7] 小端外径    当前：Φ72
      依据：图上 Ø72±0.13
      > Φ72±0.05
```

回车采用当前值、直接输入即更正、`?` 看不清、`s` 跳过；`presence` 只问「有 / 无 / ?」，`choice` 给编号选项。全部走完后打印一遍结果，再问一次「写入？」，取消就不落文件。

**它需要 TTY。** 管道、重定向、agent 沙箱里 stdin 往往是关的，读到 EOF 时脚本直接退出、不写任何东西——这是故意的：静默地把全部项目当成「正确」正是没人给出的那个答案。这类环境退回 `--format md` 或 `html`。

三个入口产出的 `answers` 结构完全一致，后面的写库逻辑不必区分来源。

## 解析回复

```bash
ask.py parse --in q.json --reply "3=Φ72±0.05; 7无; 其余采用"
```

输出统一结构：

```json
{"answers":[
  {"id":"small_end_outer_diameter","status":"corrected","value":"Φ72±0.05"},
  {"id":"inner_key","status":"absent","value":"无"},
  {"id":"overall_length","status":"confirmed","value":"1786"}
]}
```

支持的语法：`3=值`（更正）、`3正确`、`7有` / `7无`、`7看不清`、`其余采用`。解析不了的部分保持 `unsure`，并在回显里单独列出——**不默认成正确**。

统一状态只有七个：`confirmed`（采用）、`corrected`（更正）、`present`、`absent`、`selected`（选项）、`skipped`、`unsure`。三种入口都输出这一套，写库代码不必判断来源。

## 回显

写库之前把解析结果回显一次：

> 我理解为：3 改为 Φ72±0.05，7 无，其余采用。对吗？

这一步能挡掉绝大多数「用户以为改了、实际没改」的返工。

## 不要把 harness 的短板变成流程缺陷

纯文本框环境最常见的退化是「把所有问题写成一段散文，再让用户用编号回复」。这不是能力限制，是表达选择。同样的环境，换成表格 + 默认值 + 固定语法，人力成本差好几倍。

反过来，有结构化控件的环境也别滥用：`AskUserQuestion` 上限四题，把七个数值塞进去会被截断或被迫合并，反而不如直接给页面。

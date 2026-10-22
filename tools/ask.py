#!/usr/bin/env python3
"""One question file, rendered for whatever the harness can show.

The problem this solves: the same review has to be asked in a desktop app with
structured controls, in a chat box with nothing but text, and in a batch run
with no human at all. Rewriting the questions per harness is how formats drift.

Define the questions once as JSON, then render:

    ask.py render --in q.json --format md     > questions.md     # text-only
    ask.py render --in q.json --format html   > questions.html   # clickable
    ask.py render --in q.json --format json   > prompt.json      # structured tools

And parse a human reply back into canonical answers:

    ask.py parse --in q.json --reply "3=+0.13; 6无; 其余采用"

Standard library only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

UNSURE = {"看不清", "不确定", "不知道", "?", "？"}
ABSENT = {"无", "没有", "否", "不存在", "n", "no"}
PRESENT = {"有", "存在", "y", "yes"}
CONFIRM = {"正确", "对", "是", "ok", "好", "确认"}
SKIP = {"跳过", "不管", "skip"}


def load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "items" not in data:
        raise SystemExit("questions.json 需要 items 数组")
    return data


def render_md(q: dict) -> str:
    lines = [f"# {q.get('title', '确认项')}", ""]
    if q.get("note"):
        lines += [q["note"], ""]
    lines += ["| # | 项目 | 系统值 | 证据 |", "|---|------|--------|------|"]
    for i, it in enumerate(q["items"], 1):
        value = it.get("value", "")
        ev = it.get("evidence", "")
        lines.append(f"| {i} | {it.get('label', '')} | {value} | {ev or '—'} |")
    lines += ["", "默认全部采用，只回需要改的项。语法："]
    lines.append("`3=+0.13`（更正）、`6无`、`7看不清`、`其余采用`。")
    uncertain = [i for i, it in enumerate(q["items"], 1) if it.get("uncertain")]
    if uncertain:
        lines.append(f"看不清会影响判断的：{', '.join(map(str, uncertain))}。")
    return "\n".join(lines)


def render_json(q: dict) -> str:
    """Neutral shape for a harness that has its own controls."""
    out = {
        "title": q.get("title", ""),
        "note": q.get("note", ""),
        "questions": [],
    }
    for i, it in enumerate(q["items"], 1):
        kind = it.get("type", "text")
        question = {
            "id": str(it.get("id", i)),
            "index": i,
            "label": it.get("label", ""),
            "value": it.get("value", ""),
            "evidence": it.get("evidence", ""),
            "kind": kind,
        }
        if kind == "presence":
            question["options"] = ["有", "无", "看不清"]
        elif kind == "choice":
            question["options"] = it.get("options", [])
        out["questions"].append(question)
    return json.dumps(out, ensure_ascii=False, indent=2)


def render_html(q: dict) -> str:
    cards = []
    for i, it in enumerate(q["items"], 1):
        kind = it.get("type", "text")
        value = html.escape(str(it.get("value", "")))
        ev = html.escape(str(it.get("evidence", "")))
        if kind == "presence":
            choices = [("有", "present"), ("无", "absent"), ("看不清", "unsure")]
            default = "present"
        elif kind == "choice":
            choices = [(o, o) for o in it.get("options", [])]
            default = choices[0][1] if choices else "ok"
        else:
            choices = [("正确", "ok"), ("更正", "fix"), ("看不清", "unsure")]
            default = "ok"
        radios = "".join(
            f'<label><input type="radio" name="c{i}" value="{html.escape(v)}"'
            f'{" checked" if v == default else ""}> {html.escape(l)}</label>'
            for l, v in choices
        )
        cards.append(f"""
    <section class="card" data-id="{html.escape(str(it.get('id', i)))}" data-index="{i}"
             data-value="{value}">
      <header><span class="no">{i}</span><h3>{html.escape(str(it.get('label', '')))}</h3></header>
      <div class="sys">系统值 <b>{value or '—'}</b></div>
      {f'<div class="ev">{ev}</div>' if ev else ''}
      <div class="choices">{radios}</div>
      <input class="fix" type="text" placeholder="正确值">
    </section>""")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(q.get('title', '确认项'))}</title>
<style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}
body{{margin:0;padding:24px 24px 170px;font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:#f6f7f9;color:#1b1f24;max-width:760px}}
h1{{font-size:18px;margin:0 0 6px}} .note{{color:#66707a;font-size:13px;margin:0 0 18px}}
.card{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin-bottom:10px}}
.card.unsure{{border-color:#e0a800;background:#fffdf3}}
header{{display:flex;gap:10px;align-items:center}} .no{{width:24px;height:24px;border-radius:50%;
background:#1b1f24;color:#fff;font-size:12px;display:inline-flex;align-items:center;justify-content:center}}
h3{{font-size:15px;margin:0}} .sys{{font-size:13px;color:#66707a;margin:8px 0 4px}}
.sys b{{font-size:17px;color:#1b1f24}} .ev{{font-size:12px;color:#8a939c}}
.choices{{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}}
.fix{{display:none;width:100%;margin-top:8px;padding:7px 9px;border:1px solid #d4d9de;border-radius:6px;font:inherit}}
.fix.on{{display:block}}
footer{{position:sticky;bottom:0;background:#f6f7f9;padding:14px 0;display:flex;gap:10px;align-items:center}}
button{{font:inherit;padding:9px 16px;border-radius:8px;border:1px solid #1b1f24;background:#1b1f24;color:#fff;cursor:pointer}}
button.ghost{{background:#fff;color:#1b1f24}}
#out{{display:none;width:100%;height:130px;font:12px ui-monospace,Menlo,monospace;border:1px solid #d4d9de;border-radius:8px;padding:8px}}
</style></head><body>
<h1>{html.escape(q.get('title', '确认项'))}</h1>
<p class="note">{html.escape(q.get('note', ''))}</p>{''.join(cards)}
<footer><button onclick="build()">生成回答 JSON</button><button class="ghost" onclick="copyOut()">复制</button>
<span class="note" id="hint" style="margin:0"></span></footer>
<textarea id="out" readonly></textarea>
<script>
const cards=[...document.querySelectorAll('.card')];
cards.forEach(c=>c.querySelectorAll('input[type=radio]').forEach(r=>r.addEventListener('change',()=>{{
  const v=c.querySelector('input[type=radio]:checked').value, f=c.querySelector('.fix');
  f.classList.toggle('on', v==='fix'); c.classList.toggle('unsure', v==='unsure'); if(v==='fix')f.focus();
}})));
function build(){{
  const answers=cards.map(c=>{{
    const v=c.querySelector('input[type=radio]:checked').value, id=c.dataset.id, base=c.dataset.value;
    if(v==='fix'){{const t=c.querySelector('.fix').value.trim();return t?{{id,status:'corrected',value:t}}:{{id,status:'unsure',value:base}};}}
    return {{id,status:{{ok:'confirmed',present:'present',absent:'absent',unsure:'unsure'}}[v]||v,value:base}};
  }});
  const out=document.getElementById('out');out.style.display='block';
  out.value=JSON.stringify({{answers}},null,2);
  const n=answers.filter(a=>a.status==='unsure').length;
  document.getElementById('hint').textContent=n?`还有 ${{n}} 项待定`:'全部已定';
}}
function copyOut(){{const o=document.getElementById('out');if(!o.value)build();
navigator.clipboard.writeText(o.value).then(()=>document.getElementById('hint').textContent='已复制');}}
</script></body></html>
"""


def parse_reply(q: dict, reply: str) -> dict:
    items = q["items"]
    answers = {str(it.get("id", i)): {"id": str(it.get("id", i)), "status": "unsure",
                                      "value": it.get("value", "")} for i, it in enumerate(items, 1)}
    rest_confirmed = False
    tokens = [t.strip() for t in re.split(r"[;；,，\n]", reply) if t.strip()]
    for token in tokens:
        if re.search(r"其余|其他|其它", token) and re.search(r"采用|正确|确认|对", token):
            rest_confirmed = True
            continue
        m = re.match(r"^#?(\d+)\s*[=:：]\s*(.+)$", token)
        if m:
            idx, val = int(m.group(1)), m.group(2).strip()
            if 1 <= idx <= len(items):
                key = str(items[idx - 1].get("id", idx))
                answers[key].update(status="corrected", value=val)
            continue
        m = re.match(r"^#?(\d+)\s*(.+)$", token)
        if not m:
            continue
        idx, word = int(m.group(1)), m.group(2).strip()
        if not (1 <= idx <= len(items)):
            continue
        key = str(items[idx - 1].get("id", idx))
        if word in UNSURE:
            answers[key]["status"] = "unsure"
        elif word in ABSENT:
            answers[key].update(status="absent", value="无")
        elif word in PRESENT:
            answers[key].update(status="present", value="有")
        elif word in CONFIRM:
            answers[key].update(status="confirmed")
        elif word in SKIP:
            answers[key]["status"] = "skipped"
        else:
            answers[key].update(status="corrected", value=word)
    if rest_confirmed:
        for it in answers.values():
            if it["status"] == "unsure":
                it["status"] = "confirmed"
    order = [str(it.get("id", i)) for i, it in enumerate(items, 1)]
    return {"answers": [answers[k] for k in order]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--in", dest="src", required=True)
    r.add_argument("--format", choices=["md", "html", "json"], default="md")
    p = sub.add_parser("parse")
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--reply", required=True)
    args = ap.parse_args()

    q = load(args.src)
    if args.cmd == "render":
        text = {"md": render_md, "html": render_html, "json": render_json}[args.format](q)
    else:
        text = json.dumps(parse_reply(q, args.reply), ensure_ascii=False, indent=2)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

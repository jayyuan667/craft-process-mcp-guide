#!/usr/bin/env python3
"""Turn a workbench full dump into a clickable review sheet.

Reads the job's workbench JSON and preview image, crops every feature that has
a pixel bbox, and writes a single self-contained HTML file. Review by clicking,
then copy the JSON it produces and hand it back to the agent.

No network, no dependencies beyond Pillow.

Usage:
    python review_sheet.py --workbench wb.json --image input-1.png --out sheet.html
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("需要 Pillow：pip install pillow", file=sys.stderr)
    raise SystemExit(1)

PAD = 18
SCALE = 2


def crop_data_url(img: Image.Image, bbox, pad: int = PAD) -> str | None:
    if not bbox or len(bbox) != 4:
        return None
    x0, y0, x1, y1 = [float(v) for v in bbox]
    if x1 <= x0 or y1 <= y0:
        return None
    box = (
        max(0, int(x0) - pad),
        max(0, int(y0) - pad),
        min(img.width, int(x1) + pad),
        min(img.height, int(y1) + pad),
    )
    piece = img.crop(box)
    if SCALE != 1:
        piece = piece.resize((piece.width * SCALE, piece.height * SCALE), Image.LANCZOS)
    buf = io.BytesIO()
    piece.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def collect(workbench: dict) -> list[dict]:
    rows = []
    for f in workbench.get("review", {}).get("features", []):
        ev = (f.get("evidence") or [{}])[0]
        advice = ev.get("review_reason") or ""
        rows.append({
            "id": f.get("feature_id"),
            "role": f.get("role_cn") or f.get("role") or f.get("type") or "",
            "value": f.get("value"),
            "unit": f.get("unit") or "",
            "status": f.get("status"),
            "policy": f.get("generation_policy") or "",
            "advice": advice,
            "raw": ev.get("raw_text") or "",
            "bbox": ev.get("bbox"),
        })
    return rows


def render(rows: list[dict], img: Image.Image, job_id: str) -> str:
    cards = []
    for i, r in enumerate(rows, 1):
        shot = crop_data_url(img, r["bbox"])
        if shot:
            picture = f'<img src="{shot}" alt="特征 {i} 的图纸位置">'
        else:
            raw = html.escape(str(r["raw"])) if r["raw"] else "—"
            picture = f'<div class="noimg">无定位框<br><small>图上原文：{raw}</small></div>'
        advice = f'<p class="advice">模型意见：{html.escape(str(r["advice"]))}</p>' if r["advice"] else ""
        cards.append(f"""
      <section class="card" data-id="{html.escape(str(r['id']))}" data-value="{html.escape(str(r['value'] or ''))}">
        <header><span class="no">{i}</span><h3>{html.escape(r['role'])}</h3>
          <span class="badge">{html.escape(str(r['status']))}</span></header>
        <div class="body">
          <div class="shot">{picture}</div>
          <div class="fields">
            <label class="sys"><span>系统读取</span><b>{html.escape(str(r['value'] or '—'))}</b>
              <i>{html.escape(r['unit'])}</i></label>
            <div class="choices">
              <label><input type="radio" name="c{i}" value="ok" checked> 正确</label>
              <label><input type="radio" name="c{i}" value="fix"> 更正</label>
              <label><input type="radio" name="c{i}" value="reject"> 不存在/拒绝</label>
              <label><input type="radio" name="c{i}" value="unsure"> 看不清</label>
            </div>
            <input class="fix" type="text" placeholder="正确值，例如 1786±0.3">
            {advice}
          </div>
        </div>
      </section>""")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>特征复核单 · {html.escape(job_id)}</title>
<style>
:root{{color-scheme:light}}
*{{box-sizing:border-box}}
body{{margin:0;padding:24px 24px 170px;font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  background:#f6f7f9;color:#1b1f24}}
h1{{font-size:18px;margin:0 0 4px}}
.sub{{color:#66707a;font-size:13px;margin-bottom:20px}}
.card{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin-bottom:12px}}
.card.unsure{{border-color:#e0a800;background:#fffdf3}}
.card.reject{{opacity:.72}}
header{{display:flex;align-items:center;gap:10px;margin-bottom:10px}}
.no{{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;
  border-radius:50%;background:#1b1f24;color:#fff;font-size:12px;flex:none}}
h3{{font-size:15px;margin:0;font-weight:600}}
.badge{{margin-left:auto;font-size:12px;color:#66707a;border:1px solid #e3e6ea;
  border-radius:999px;padding:1px 8px}}
.body{{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}}
.shot{{flex:0 0 260px;max-width:260px}}
.shot img{{width:100%;border:1px solid #e3e6ea;border-radius:6px;background:#fff}}
.noimg{{font-size:12px;color:#8a939c;border:1px dashed #d4d9de;border-radius:6px;
  padding:18px 10px;text-align:center}}
.fields{{flex:1 1 320px;min-width:280px}}
.sys{{display:flex;align-items:baseline;gap:8px;font-size:13px;color:#66707a}}
.sys b{{font-size:17px;color:#1b1f24}}
.sys i{{font-style:normal}}
.choices{{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0}}
.choices label{{font-size:14px;cursor:pointer;user-select:none}}
.fix{{width:100%;padding:7px 9px;border:1px solid #d4d9de;border-radius:6px;
  font:inherit;font-size:14px;display:none}}
.fix.on{{display:block}}
.advice{{font-size:12px;color:#8a6000;background:#fff8e6;border-radius:6px;
  padding:6px 8px;margin:8px 0 0}}
footer{{position:sticky;bottom:0;background:#f6f7f9;padding:16px 0 8px;
  display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
button{{font:inherit;font-size:14px;padding:9px 16px;border-radius:8px;border:1px solid #1b1f24;
  background:#1b1f24;color:#fff;cursor:pointer}}
button.ghost{{background:#fff;color:#1b1f24}}
#out{{width:100%;height:130px;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;
  border:1px solid #d4d9de;border-radius:8px;padding:8px;display:none;background:#fff}}
</style></head><body>
<h1>特征复核单</h1>
<p class="sub">{html.escape(job_id)} · 共 {len(rows)} 项 · 建议默认「正确」，只改例外。
看不清的项请标出来，不要猜。</p>
{''.join(cards)}
<footer>
  <button onclick="build()">生成回填 JSON</button>
  <button class="ghost" onclick="copyOut()">复制</button>
  <span id="hint" class="sub" style="margin:0"></span>
</footer>
<textarea id="out" readonly></textarea>
<script>
const cards = [...document.querySelectorAll('.card')];
cards.forEach(card => {{
  card.querySelectorAll('input[type=radio]').forEach(r => r.addEventListener('change', () => {{
    const v = card.querySelector('input[type=radio]:checked').value;
    const fix = card.querySelector('.fix');
    fix.classList.toggle('on', v === 'fix');
    card.classList.toggle('unsure', v === 'unsure');
    card.classList.toggle('reject', v === 'reject');
    if (v === 'fix') fix.focus();
  }}));
}});
function build() {{
  const items = cards.map(card => {{
    const id = card.dataset.id;
    const choice = card.querySelector('input[type=radio]:checked').value;
    const original = card.dataset.value;
    if (choice === 'ok') return {{feature_id: id, status: 'confirmed', value: original}};
    if (choice === 'fix') {{
      const v = card.querySelector('.fix').value.trim();
      return v ? {{feature_id: id, status: 'confirmed', value: v}}
               : {{feature_id: id, status: 'needs_review', value: original, note: '标记更正但未填值'}};
    }}
    if (choice === 'reject') return {{feature_id: id, status: 'rejected', value: original}};
    return {{feature_id: id, status: 'needs_review', value: original, note: '看不清'}};
  }});
  const out = document.getElementById('out');
  out.style.display = 'block';
  out.value = JSON.stringify(items, null, 2);
  const pending = items.filter(i => i.status === 'needs_review').length;
  document.getElementById('hint').textContent =
    pending ? `还有 ${{pending}} 项待定，确认后再回填` : '全部已定，可以直接回填';
}}
function copyOut() {{
  const out = document.getElementById('out');
  if (!out.value) build();
  navigator.clipboard.writeText(out.value).then(() => {{
    document.getElementById('hint').textContent = '已复制';
  }});
}}
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbench", required=True, help="workbench?detail=full 保存下来的 JSON")
    ap.add_argument("--image", required=True, help="craft_download_preview 下载的页图")
    ap.add_argument("--out", default="review-sheet.html")
    args = ap.parse_args()

    wb = json.loads(Path(args.workbench).read_text(encoding="utf-8"))
    rows = collect(wb)
    if not rows:
        print("workbench 里没有 review.features", file=sys.stderr)
        return 1
    img = Image.open(args.image).convert("RGB")
    Path(args.out).write_text(render(rows, img, wb.get("job_id", "")), encoding="utf-8")
    print(f"{len(rows)} 项 -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

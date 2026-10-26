#!/usr/bin/env python3
"""Drive a craft-process job one step at a time, from any harness.

The point is portability: an agent that can run shell commands can run the
whole pipeline without an MCP client, without knowing tool names, and without
re-reading a handbook. Every command is independently re-runnable; `status`
always says where the job is stuck.

    craft_flow.py status
    craft_flow.py upload drawing.png
    craft_flow.py wait
    craft_flow.py dump
    craft_flow.py previews --download ./previews
    craft_flow.py review   --answers review.json
    craft_flow.py presence --answers presence.json
    craft_flow.py match
    craft_flow.py select T10
    craft_flow.py slots    --values slots.json
    craft_flow.py finalize
    craft_flow.py edit     --operations ops.json
    craft_flow.py export process-card.xlsx

Human gates stay human: this tool never invents a value. `review` / `presence`
/ `slots` take an answers file that a person produced, and apply it to the
full objects the server returned.

Answers file shapes (all keys optional; anything omitted is left untouched):

    review.json    {"overrides": {"overall_length:1": {"value": "1786",
                                                       "status": "confirmed"}}}
    presence.json  {"source": "human",
                    "features": {"KEYWAY": "yes", "SQUARE": "no"},
                    "branch_conditions": {"material": "<从服务端选项里选>",
                                          "billet_type": "<idem>",
                                          "route_prefix": "<idem>"}}
    presence.json  {"features": {"KEYWAY": "yes", "SQUARE": "no"},
                    "branch_conditions": {"material": "GH901",
                                          "billet_type": "大锻件",
                                          "route_prefix": "28F"}}
    slots.json     {"values": {"T10-30-0": "φ77，0，-0.025", "T10-60-0": "60"}}

Exit codes: 0 ok, 1 usage, 2 network or timeout, 3 request rejected,
4 state mismatch (wrong job / stale revision after re-read), 5 gate not passed.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from craft_upload import DEFAULT_LEDGER, append, multipart, now_iso, pick_job_id, sha256_of

STATE_DIR = Path.home() / ".config" / "craft-process"
POINTER = STATE_DIR / "current"


# ---------------------------------------------------------------- transport

def backend_url() -> str:
    import os
    base = os.environ.get("CRAFT_BACKEND_URL", "").rstrip("/")
    if base:
        return base
    cfg = STATE_DIR / "endpoints.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if isinstance(data, dict):
            return str(data.get("backend") or data.get("backend_url") or "").rstrip("/")
    return ""


def http(method: str, url: str, body: bytes | None = None,
         content_type: str = "application/json", timeout: int = 60):
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw), resp.headers
            except (json.JSONDecodeError, UnicodeDecodeError):
                return resp.status, raw, resp.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw.decode("utf-8", "replace")[:400]}
        return exc.code, payload, exc.headers
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SystemExit(print_err(f"连不上 {url}：{reason}", 2))


def print_err(msg: str, code: int) -> int:
    print(msg, file=sys.stderr)
    return code


def die(payload, code: int = 3) -> int:
    if isinstance(payload, dict):
        msg = payload.get("error") or payload
        if payload.get("unresolved_slots"):
            msg = f"{msg}（未解决槽位：{', '.join(payload['unresolved_slots'])}）"
    else:
        msg = str(payload)[:400]
    return print_err(f"服务端拒绝：{msg}", code)


# ---------------------------------------------------------------- state

def path_for(job: str) -> Path:
    return STATE_DIR / f"state-{job}.json"


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path_for(state["job_id"]).write_text(
        json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    POINTER.write_text(state["job_id"], encoding="utf-8")


def load_state(job: str | None = None) -> dict:
    if not job:
        if not POINTER.exists():
            raise SystemExit(print_err("还没有任务。先 `craft_flow.py upload <file>`。", 1))
        job = POINTER.read_text(encoding="utf-8").strip()
    path = path_for(job)
    if not path.exists():
        raise SystemExit(print_err(f"没有任务 {job} 的本地状态。", 1))
    return json.loads(path.read_text(encoding="utf-8"))


def workbench(job: str, timeout: int = 60, retries: int = 3) -> dict:
    base = backend_url()
    status, payload = 0, {}
    for attempt in range(retries):
        status, payload, _ = http("GET", f"{base}/api/jobs/{job}/workbench",
                                  timeout=timeout)
        # A freshly created job can briefly 404 the workbench while the record
        # is still being written; that is not a state mismatch.
        if status == 200 or status not in (404, 502, 503, 504):
            break
        if attempt + 1 < retries:
            time.sleep(2 + attempt * 2)
    if status != 200:
        raise SystemExit(die(payload, 2 if status >= 500 else 3))
    if payload.get("job_id") and payload["job_id"] != job:
        raise SystemExit(print_err(
            f"工作台返回的是任务 {payload['job_id']}，不是你请求的 {job}。停下。", 4))
    return payload


def post(job: str, action: str, payload: dict, timeout: int = 60) -> dict:
    base = backend_url()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status, data, _ = http("POST", f"{base}/api/jobs/{job}/{action}", body, timeout=timeout)
    if status in (200, 202):
        return data
    raise SystemExit(die(data, 4 if status == 409 else 3))


def refresh(job: str | None) -> dict:
    """Read the workbench and fold the moving parts back into local state."""
    state = load_state(job)
    job = state["job_id"]
    wb = workbench(job)
    state.update({
        "revision": wb.get("revision"),
        "stage": wb.get("current_stage"),
        "blocking_action": wb.get("blocking_action"),
        "status": wb.get("stage_status"),
        "summary": wb.get("summary"),
        "updated_at": now_iso(),
    })
    save_state(state)
    return wb


def feature_counts(wb: dict) -> dict:
    """Counts live at top level in some builds, under review in others."""
    return wb.get("counts") or (wb.get("review") or {}).get("counts") or {}


def pending_features(wb: dict) -> int:
    """Feature-dimension pending count; slot counts reuse the same key after review."""
    review_counts = (wb.get("review") or {}).get("counts") or {}
    if "needs_review" in review_counts:
        return int(review_counts.get("needs_review") or 0)
    # Top-level counts are the slot dimension once the card exists; only trust
    # them as feature counts while the server is still blocking on features.
    if wb.get("blocking_action") == "confirm_features":
        return int((wb.get("counts") or {}).get("needs_review") or 0)
    return 0


def banner(wb: dict) -> None:
    counts = feature_counts(wb)
    print(f"任务     {wb.get('job_id')}")
    print(f"阶段     {wb.get('current_stage')} / {wb.get('stage_status')}"
          f"  revision {wb.get('revision')}")
    print(f"阻断     {wb.get('blocking_action') or '—'}")
    if counts:
        print(f"计数     confirmed {counts.get('confirmed')} · "
              f"needs_review {counts.get('needs_review')} · "
              f"unresolved {counts.get('unresolved')}")
    if wb.get("summary"):
        print(f"摘要     {wb['summary']}")
    pending = pending_features(wb)
    if pending:
        print(f"警告     还有 {pending} 项特征未人工确认；摘要里的「可导出」不可信，"
              "先 review / presence")


NEXT_HINT = {
    "confirm_features": "下一步  review / presence --answers（每条要有人确认）",
    "select_template": "下一步  match 看候选，再 select <template_id>",
    "review_slots": "下一步  slots --values，再 finalize",
    "export_card": "下一步  export <file.xlsx>",
}


# ---------------------------------------------------------------- commands

def cmd_status(args) -> int:
    wb = refresh(args.job)
    banner(wb)
    hint = NEXT_HINT.get(wb.get("blocking_action") or "")
    if hint:
        print(hint)
    return 0


def cmd_upload(args) -> int:
    path = Path(args.file).expanduser()
    if not path.exists():
        return print_err(f"文件不存在：{path}", 1)
    base = backend_url()
    if not base:
        return print_err("没有后端地址：设置 CRAFT_BACKEND_URL 或 --backend。", 1)

    digest = sha256_of(path)
    attempt_id = f"flow-{digest[:12]}-{int(time.time())}"
    append(Path(args.ledger).expanduser(), {
        "event": "attempt", "attempt_id": attempt_id,
        "time": now_iso(), "sha256": digest, "file": str(path), "backend": base})

    body, ctype = multipart({"library_key": args.library_key}, path)
    started = time.time()
    status, payload, _ = http("POST", f"{base}/api/jobs", body, ctype,
                              timeout=args.timeout)
    elapsed = round(time.time() - started, 1)
    if status not in (200, 202):
        return die(payload)

    job = pick_job_id(payload if isinstance(payload, dict) else {})
    if not job:
        return print_err(f"HTTP {status} 但没有 job_id：{str(payload)[:300]}", 3)

    append(Path(args.ledger).expanduser(), {
        "event": "result", "attempt_id": attempt_id, "time": now_iso(),
        "sha256": digest, "file": str(path), "backend": base,
        "job_id": job, "http": status, "seconds": elapsed})

    state = {"job_id": job, "backend": base, "drawing": path.name,
             "sha256": digest, "revision": None, "stage": "queued",
             "created_at": now_iso()}
    save_state(state)
    print(f"job_id   {job}")
    print(f"耗时     {elapsed}s  HTTP {status}")
    print("下一步  craft_flow.py wait")
    return 0


def cmd_adopt(args) -> int:
    """Take over a job created outside the CLI (curl, another machine)."""
    base = backend_url()
    if not base:
        return print_err("没有后端地址：设置 CRAFT_BACKEND_URL 或 --backend。", 1)
    job = args.job_id.strip()
    wb = workbench(job)
    files = (wb.get("drawing") or {}).get("files") or []
    save_state({
        "job_id": job,
        "backend": base,
        "drawing": files[0].get("name") if files else "",
        "revision": wb.get("revision"),
        "stage": wb.get("current_stage"),
        "status": wb.get("stage_status"),
        "created_at": now_iso(),
        "adopted": True,
    })
    print(f"已接管   {job}")
    banner(wb)
    print("说明     本地状态已写入，status / dump / presence 现在可用")
    return 0


def cmd_wait(args) -> int:
    state = load_state(args.job)
    job, base = state["job_id"], state["backend"]
    deadline = time.time() + args.timeout
    last = None
    while time.time() < deadline:
        status, payload, _ = http("GET", f"{base}/api/jobs/{job}", timeout=30)
        if status != 200:
            raise SystemExit(die(payload, 2 if status >= 500 else 3))
        label = f"{payload.get('status')} {payload.get('progress')}%"
        if label != last:
            print(f"  {label}")
            last = label
        if payload.get("status") in ("extracted", "failed", "error"):
            state.update({"stage": payload.get("status"),
                          "updated_at": now_iso()})
            save_state(state)
            if payload.get("status") != "extracted":
                return print_err(f"识别终止于 {payload.get('status')}", 3)
            print("下一步  craft_flow.py dump / status")
            return 0
        time.sleep(args.interval)
    return print_err(f"等了 {args.timeout}s 还没到 extracted；任务仍在跑，稍后再 wait。", 2)


def cmd_dump(args) -> int:
    state = load_state(args.job)
    job = state["job_id"]
    wb = workbench(job)
    out = Path(args.out).expanduser() if args.out else STATE_DIR / f"workbench-{job}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(wb, ensure_ascii=False, indent=1), encoding="utf-8")
    banner(wb)
    print(f"落盘     {out}")
    return 0


def cmd_review(args) -> int:
    state = load_state(args.job)
    job = state["job_id"]
    answers = json.loads(Path(args.answers).expanduser().read_text(encoding="utf-8"))
    overrides = answers.get("overrides") or answers

    wb = refresh(job)
    features = (wb.get("review") or {}).get("features") or []
    if not features:
        return print_err("工作台里没有特征表，先确认识别已完成。", 4)

    unknown = [k for k in overrides if k not in {f["feature_id"] for f in features}]
    if unknown:
        return print_err(f"这些 feature_id 不在当前特征表里：{', '.join(unknown)}", 4)

    # The endpoint replaces the whole table: send every object back, value as str.
    table = json.loads(json.dumps(features))
    for feature in table:
        override = overrides.get(feature["feature_id"], {})
        if "value" in override:
            feature["value"] = str(override["value"])
        feature.setdefault("value", "")
        feature["value"] = str(feature["value"])
        feature["status"] = override.get("status", feature.get("status") or "confirmed")
        if override.get("note"):
            feature["note"] = override["note"]

    result = post(job, "feature-review", {"revision": wb.get("revision"), "features": table})
    counts = result.get("counts") or {}
    print(f"已写入   confirmed {counts.get('confirmed')} · "
          f"needs_review {counts.get('needs_review')} · "
          f"unresolved {counts.get('unresolved')}")
    if counts.get("needs_review"):
        print("还有待确认项，`status` 看阻断点。")
    refresh(job)
    return 0


def cmd_presence(args) -> int:
    state = load_state(args.job)
    job = state["job_id"]
    wb = refresh(job)
    catalog = structural_catalog(wb)

    if args.questions:
        items = []
        for item in catalog:
            items.append({
                "id": item["feature_id"],
                "label": item["name"] or item["feature_id"],
                "value": "有" if item["presence"] == "yes" else "无",
                "evidence": item["evidence"] or f"服务端当前判断：{item['presence']}",
                "type": "presence",
            })
        for bc in (wb.get("review") or {}).get("branch_conditions") or []:
            options = [o.get("value") for o in bc.get("options") or [] if o.get("value")]
            items.append({
                "id": bc.get("field"),
                "label": bc.get("name") or bc.get("field"),
                "value": bc.get("value") or (options[0] if len(options) == 1 else ""),
                "evidence": f"可选：{' / '.join(options) or '（服务端未给选项）'}；"
                            "图纸上没有，只能从这些选项里选",
                "type": "choice",
                "options": options,
            })
        payload = {
            "title": "结构特征与分支条件确认",
            "note": "逐项选择，不要留空；选项来自服务端，不要另填。",
            "items": items,
        }
        out = Path(args.questions).expanduser()
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已生成   {out}（{len(items)} 项）")
        print("渲染     python tools/ask.py render --in %s --format html > questions.html" % out)
        return 0

    if args.list:
        if not catalog:
            print("服务端没有暴露结构特征清单；直接读工作台的 auto_features / low_frequency。")
        else:
            print(f"结构特征 {len(catalog)} 项（当前值是服务端的，逐条问人后再改）")
            for item in catalog:
                evidence = f" · {item['evidence']}" if item["evidence"] else ""
                print(f"  {item['feature_id']:<22}{item['name']:<8}"
                      f" 当前={item['presence']:<7} 来源={item['source']}{evidence}")

        branches = (wb.get("review") or {}).get("branch_conditions") or []
        if branches:
            print("\n分支条件（只能从选项里选，不能照抄示例、不要沿用别的 job）")
            for bc in branches:
                options = [o.get("value") for o in bc.get("options") or [] if o.get("value")]
                print(f"  {bc.get('field'):<12}{bc.get('name', ''):<8}"
                      f" 当前={bc.get('value') or '—'}  选项={ ' / '.join(options) or '未提供' }")
        print('\nanswers 形状：{"source": "human", "features": {"SQUARE": "yes", ...}, '
              '"branch_conditions": {"material": "<从选项里选>", ...}}')
        return 0

    if not args.answers:
        return print_err("缺少 --answers；先跑 presence --list 看清有哪些项。", 1)
    answers = json.loads(Path(args.answers).expanduser().read_text(encoding="utf-8"))
    features = answers.get("features") or {}
    branch = answers.get("branch_conditions") or {}
    if not features and not branch:
        return print_err("answers 里既没有 features 也没有 branch_conditions。", 1)

    required = {item["feature_id"] for item in catalog}
    missing = sorted(required - set(features))
    if missing:
        return print_err(
            f"结构判断不完整：还有 {len(missing)} 项没定——{', '.join(missing)}。\n"
            "先 presence --list，把每一项都问过人再提交；少一项也不发。", 4)
    if features and answers.get("source") != "human":
        return print_err('这批判断必须来自人工确认：在 answers 里加 "source": "human"。', 4)
    invalid = [key for key, value in features.items() if value not in ("yes", "no")]
    if invalid:
        return print_err(f"presence 只能是 yes / no：{', '.join(invalid)}", 4)

    unresolved_branch = [bc.get("field") for bc in (wb.get("review") or {}).get("branch_conditions") or []
                         if not (branch.get(bc.get("field")) or bc.get("value"))]
    if unresolved_branch:
        return print_err(
            "分支条件还没给全：" + ", ".join(unresolved_branch) + "。图纸上通常没有，必须问人。", 4)

    allowed = {bc.get("field"): [o.get("value") for o in bc.get("options") or [] if o.get("value")]
               for bc in (wb.get("review") or {}).get("branch_conditions") or []}
    invalid_branch = [f"{field}={value}（可选：{' / '.join(allowed[field])}）"
                      for field, value in branch.items()
                      if allowed.get(field) and value not in allowed[field]]
    if invalid_branch:
        return print_err(
            "分支条件的值不在服务端选项里——不能自编，也不要照抄示例：\n  "
            + "\n  ".join(invalid_branch), 4)

    payload = {
        "revision": wb.get("revision"),
        "features": [{"feature_id": k, "presence": v} for k, v in features.items()],
        "branch_conditions": branch,
    }
    result = post(job, "feature-presence", payload, timeout=180)
    print(f"已提交   features {len(payload['features'])} · "
          f"分支 {len(branch)} · revision → {result.get('revision')}")
    decision = result.get("decision") or {}
    selected = decision.get("selected_template_id")
    if selected:
        print(f"注意     服务端已自动选定 {selected}，先确认再继续。")
    refresh(job)
    print("下一步  craft_flow.py match")
    return 0


def drawing_number(wb: dict) -> str:
    """Current drawing number, only when the server or filename gives a credible one."""
    import re

    drawing = wb.get("drawing") or {}
    for key in ("drawing_no", "drawing_number", "part_no", "number"):
        value = drawing.get(key)
        if value:
            return str(value)

    files = drawing.get("files") or []
    if not files:
        return ""
    stem = Path(files[0].get("name") or "").stem
    # "image1" / "scan_02" are filenames, not drawing numbers; comparing them
    # against reference_drawing produces false "borrowed template" conclusions.
    if re.search(r"[A-Za-z]", stem) and "-" in stem:
        return stem
    return ""


def structural_catalog(wb: dict) -> list[dict]:
    """Every structural switch the server knows about, with its current value."""
    items: dict[str, dict] = {}

    def add(item: dict, source: str, **extra) -> None:
        fid = item.get("feature_id")
        if not fid:
            return
        evidence = (item.get("evidence") or "").replace("\n", " ").strip()
        if any(ch in evidence for ch in '{}"'):
            evidence = ""
        items[fid] = {
            "feature_id": fid,
            "name": item.get("name") or items.get(fid, {}).get("name", ""),
            "presence": item.get("presence") or "unknown",
            "source": source,
            "evidence": evidence[:60],
            **extra,
        }

    structural = ((wb.get("extraction") or {}).get("structural_features") or {})
    for item in structural.get("features") or []:
        add(item, "structural")
    review = wb.get("review") or {}
    for item in review.get("auto_features") or []:
        add(item, "auto")
    for item in review.get("low_frequency") or []:
        add(item, "low_frequency")
    return list(items.values())


def explain_empty_pool(wb: dict, current: str = "") -> None:
    review = wb.get("review") or {}
    selected = [f["feature_id"] for f in review.get("auto_features") or []
                if f.get("presence") == "yes"]
    flips = [f for f in review.get("low_frequency") or [] if f.get("presence") == "no"]

    where = f"（{current}）" if current else ""
    print(f"\n诊断：没有模板进池{where}")
    if selected:
        print("  已判 yes：" + ", ".join(selected))
    if flips:
        print(f"  默认 no 的可翻转项 {len(flips)} 个：")
        for item in flips:
            print(f"    - {item['feature_id']}（{item.get('name', '')}）")
        print("  逐条问人：这些 no 里有没有其实是 yes 的？改完再跑 presence、再 match。")
    print("  接口不会告诉你「若 X=yes 则某模板可入池」，别等它提示。")


def classify_match(candidates: list[dict], current: str) -> str:
    """empty / no_home / borrowed / partial_only / ok — used to pick the message."""
    if not candidates:
        return "empty"
    complete = [c for c in candidates if c.get("match_strength") == "complete"]
    home = [c for c in candidates if current
            and (c.get("template_preview") or {}).get("reference_drawing") == current]
    if current and not home:
        return "borrowed" if complete else "no_home"
    if not complete:
        return "partial_only"
    return "ok"


def cmd_match(args) -> int:
    state = load_state(args.job)
    job = state["job_id"]
    wb = refresh(job)
    result = post(job, "template-match", {"revision": wb.get("revision")}, timeout=180)
    decision = result.get("decision") or {}
    candidates = decision.get("candidates") or []
    current = drawing_number(wb)
    before = (result.get("manual_filter") or {}).get("before_count")

    if not candidates:
        explain_empty_pool(wb, current)
        hint = "模板池为空（过滤前就是 0）" if before == 0 else "候选被条件筛掉了"
        return print_err(f"没有候选模板（{hint}），先按上面的清单回图确认。", 3)

    if current:
        print(f"候选 {len(candidates)} 个（参考图号 ≠ {current} = 借档）")
    else:
        print(f"候选 {len(candidates)} 个（图号未知，无法判断借档：核对参考图号与标题栏）")

    for cand in candidates[: args.limit]:
        preview = cand.get("template_preview") or {}
        missing = cand.get("missing") or []
        print(f"  {cand.get('template_id'):>4}  {cand.get('match_strength'):<9}"
              f" {preview.get('reference_drawing')}  "
              f"ops={preview.get('operation_count')}"
              f"{'  missing=' + ','.join(missing) if missing else ''}"
              f"{'  [recommended]' if cand.get('is_recommended') else ''}")

    verdict = classify_match(candidates, current)
    if verdict == "borrowed":
        print(f"\n没有参考图号等于 {current} 的候选：可能是借档。"
              "逐个核对 reference_drawing 与图纸标题栏后再选，记成人工选择。")
    elif verdict in ("no_home", "partial_only"):
        explain_empty_pool(wb, current)

    print("下一步  craft_flow.py select <template_id>")
    return 0


def cmd_select(args) -> int:
    state = load_state(args.job)
    job = state["job_id"]
    wb = refresh(job)
    decision = wb.get("decision") or {}
    target = next((c for c in decision.get("candidates") or []
                   if c.get("template_id") == args.template_id), None)
    if target and target.get("missing") and not args.force:
        return print_err(
            f"{args.template_id} 缺少 {', '.join(target['missing'])}；"
            "回图纸确认后用 presence 补，或加 --force 记录为人工选择。", 3)

    try:
        result = post(job, "template-selection",
                      {"template_id": args.template_id, "revision": wb.get("revision")},
                      timeout=300)
    except SystemExit as exc:
        if exc.code != 2:
            raise
        print("超时不等于失败，重读工作台…")
        wb = refresh(job)
        if (wb.get("decision") or {}).get("selected_template_id"):
            print(f"服务端已选 {wb['decision']['selected_template_id']}，继续。")
            return 0
        return print_err("重读后仍未选中，带更长超时重试一次。", 2)

    print(f"已选     {args.template_id} → revision {result.get('revision')}")
    refresh(job)
    print("下一步  craft_flow.py slots --values")
    return 0


def warn_slot_semantics(wb: dict, values: dict) -> None:
    """Flag values whose evidence belongs to a different process step."""
    replacement = wb.get("replacement") or {}
    catalog = replacement.get("catalog") or {}
    meta: dict[str, dict] = {}
    for group in ("drawing_slots", "parameter_slots", "derived_slots"):
        for slot in catalog.get(group) or []:
            meta[slot.get("slot_id")] = slot
    candidates = replacement.get("values") or {}

    warnings = []
    for slot_id in values:
        operation = (meta.get(slot_id) or {}).get("operation_name") or ""
        info = candidates.get(slot_id) or {}
        evidence = f"{info.get('evidence') or ''} {info.get('binding_reason') or ''}"
        if "磨" in operation and "留" in evidence and "余量" in evidence:
            warnings.append(f"{slot_id} 是{operation}工序，候选证据是「留余量」的粗加工值——"
                            "确认填的是成品公差，不是车削值")
        if "车" in operation and "成品" in evidence:
            warnings.append(f"{slot_id} 是{operation}工序，候选证据偏向成品公差——"
                            "确认没有把磨削值填进来")
    if warnings:
        print("注意     槽位语义核对：")
        for line in warnings:
            print("         - " + line)


def cmd_slots(args) -> int:
    state = load_state(args.job)
    job = state["job_id"]
    answers = json.loads(Path(args.values).expanduser().read_text(encoding="utf-8"))
    raw = answers.get("values") or answers

    values = {}
    for slot_id, value in raw.items():
        values[slot_id] = value if isinstance(value, dict) else {"value": str(value)}

    wb = refresh(job)
    warn_slot_semantics(wb, values)
    result = post(job, "slots", {"revision": wb.get("revision"), "values": values}, timeout=120)
    print(f"已写入   {len(values)} 个槽位 → revision {result.get('revision')}")
    validation = (result.get("replacement") or {}).get("validation") or {}
    print(f"校验状态 {validation.get('status')}（写入不会消项，要 finalize）")
    print("下一步  craft_flow.py finalize")
    return 0


def cmd_finalize(args) -> int:
    state = load_state(args.job)
    job = state["job_id"]
    wb = refresh(job)

    pending = pending_features(wb)
    if pending:
        return print_err(
            f"还有 {pending} 项特征未人工确认，不能出卡。"
            "先 review / presence 把它们逐条确认，再 finalize。", 5)

    result = post(job, "slot-review", {"revision": wb.get("revision"), "values": {}},
                  timeout=300)
    card = result.get("process_card") or {}
    validation = (result.get("replacement") or {}).get("validation") or {}
    unresolved = validation.get("unresolved_slots") or []
    ok = (validation.get("status") == "ok" and not unresolved
          and card.get("mode") == "official" and card.get("operations"))
    print(f"validation  {validation.get('status')}  unresolved {len(unresolved)}")
    print(f"卡          {card.get('mode')} · {len(card.get('operations') or [])} 道工序")
    print(f"阻断        {result.get('blocking_action')}")
    refresh(job)
    if not ok:
        return print_err("四字段没有全部满足，不导出。按 status 排查。", 5)
    print("下一步  craft_flow.py export <file.xlsx>")
    return 0


def xlsx_row_count(data: bytes) -> int | None:
    import io
    import re
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist() if n.startswith("xl/worksheets/sheet")]
            if not names:
                return None
            names.sort()
            sheet = archive.read(names[0]).decode("utf-8", "replace")
        return len(re.findall(r"<row[ >]", sheet))
    except Exception:  # noqa: BLE001
        return None


def cmd_export(args) -> int:
    state = load_state(args.job)
    job, base = state["job_id"], state["backend"]

    pending = pending_features(refresh(job))
    if pending:
        return print_err(
            f"还有 {pending} 项特征未人工确认，导出会带着未确认的结构出卡。先 review / presence。", 5)

    status, raw, headers = http("GET",
                                f"{base}/api/jobs/{job}/process-card/export",
                                timeout=180)
    if status != 200:
        return die(raw)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    ctype = (headers.get("Content-Type") if headers else "") or "?"
    print(f"已导出   {out}  {len(raw)} bytes")
    print(f"类型     {ctype}")

    if raw[:2] == b"PK":
        rows = xlsx_row_count(raw)
        if rows:
            print(f"行数     {rows}（含表头，工序 {rows - 1}）——与工作台 operations 数对一下")
    elif out.suffix.lower() in (".csv", ".txt"):
        rows = len([line for line in raw.decode("utf-8", "replace").splitlines() if line.strip()])
        print(f"行数     {rows}（含表头）")
    return 0


def cmd_previews(args) -> int:
    state = load_state(args.job)
    job, base = state["job_id"], state["backend"]
    status, payload, _ = http("GET", f"{base}/api/jobs/{job}/previews", timeout=60)
    if status != 200:
        return die(payload)
    previews = payload.get("previews") or []
    if not previews:
        return print_err("没有预览图。", 3)
    print(f"预览 {len(previews)} 项")
    for item in previews:
        print(f"  {item.get('name')}  {item.get('url')}")
    if args.download:
        out_dir = Path(args.download).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        for item in previews:
            status, raw, _ = http("GET", base + item["url"], timeout=120)
            if status != 200:
                print(f"  跳过 {item.get('name')}：HTTP {status}")
                continue
            target = out_dir / Path(item["name"]).name
            target.write_bytes(raw)
            print(f"  落盘 {target}  {len(raw)} bytes")
    return 0


def cmd_result(args) -> int:
    state = load_state(args.job)
    job, base = state["job_id"], state["backend"]
    status, payload, _ = http("GET", f"{base}/api/jobs/{job}/result", timeout=60)
    if status != 200:
        return die(payload)
    out = Path(args.out).expanduser() if args.out else STATE_DIR / f"result-{job}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if isinstance(payload, dict):
        print(f"键       {', '.join(list(payload)[:12])}")
    print(f"落盘     {out}")
    return 0


def cmd_edit(args) -> int:
    state = load_state(args.job)
    job = state["job_id"]
    data = json.loads(Path(args.operations).expanduser().read_text(encoding="utf-8"))
    operations = data.get("operations") if isinstance(data, dict) else data
    if not isinstance(operations, list) or not operations:
        return print_err("operations 必须是非空数组。", 1)
    missing = [i for i, op in enumerate(operations) if not str(op.get("工序", "")).strip()]
    if missing:
        return print_err(f"第 {missing} 条缺「工序」字段；改卡是整表替换，字段不全不要提交。", 1)

    # 工时 传数字 0 会被服务端当成空值，回读后这一格变空白；一律转字符串。
    for op in operations:
        if "工时" in op:
            op["工时"] = "" if op["工时"] is None else str(op["工时"])
        for key in [k for k, v in op.items() if v is None]:
            op[key] = ""

    wb = refresh(job)
    card = wb.get("process_card") or {}
    before = len(card.get("operations") or [])
    result = post(job, "process-card-edit",
                  {"operations": operations, "revision": wb.get("revision")}, timeout=180)
    after = len((result.get("process_card") or {}).get("operations") or [])
    print(f"已替换   工序 {before} → {after} 条，revision {result.get('revision')}")
    if after != len(operations):
        return print_err(f"回读条数是 {after}，与提交的 {len(operations)} 不一致。", 4)
    print("下一步  craft_flow.py export <file.xlsx>")
    return 0


def cmd_health(args) -> int:
    base = backend_url()
    if not base:
        return print_err("没有后端地址：设置 CRAFT_BACKEND_URL 或 --backend。", 1)
    status, payload, _ = http("GET", f"{base}/health", timeout=10)
    if status != 200:
        return print_err(f"/health 返回 {status}：{payload}", 2)
    service = payload.get("service") if isinstance(payload, dict) else None
    print(f"backend : {base}")
    print(f"service : {service or 'unknown（服务名未自报，可能是别的服务）'}")
    print("ok")
    return 0


def cmd_doctor(args) -> int:
    """One-shot first-run check: address, backend, current job, next step."""
    import os

    print("craft-process 自检")
    base = backend_url()
    if not base:
        print("1) 地址   没有")
        print("   设 CRAFT_BACKEND_URL、传 --backend，或写 ~/.config/craft-process/endpoints.json")
        return 1
    source = "环境变量" if os.environ.get("CRAFT_BACKEND_URL") else "endpoints.json"
    print(f"1) 地址   {base}（{source}）")

    status, payload, _ = http("GET", f"{base}/health", timeout=10)
    service = payload.get("service") if isinstance(payload, dict) else None
    print(f"2) 后端   HTTP {status} · {service or '未自报服务名'}")
    if status != 200:
        print("   /health 不是 200：先确认地址和实例状态，别往下走")
        return 2
    expected = os.environ.get("CRAFT_SERVICE")
    if expected and service and service != expected:
        print(f"   服务名不符（期望 {expected}）：可能连到了同主机的别的服务")

    if not POINTER.exists():
        print("3) 任务   无。下一步：upload <file>")
        return 0
    try:
        state = load_state(None)
    except SystemExit:
        print("3) 任务   指针存在但状态文件缺失，重新 upload 或指定 --job")
        return 1

    job = state["job_id"]
    try:
        wb = refresh(job)
    except SystemExit as exc:
        print(f"3) 任务   {job} 读不到工作台（退出码 {exc.code}）")
        return 3

    print(f"3) 任务   {job} · revision {wb.get('revision')} · "
          f"{wb.get('current_stage')} · {wb.get('blocking_action')}")

    created = state.get("created_at")
    if created:
        from datetime import datetime
        try:
            created_at = datetime.fromisoformat(created)
            now = (datetime.now(created_at.tzinfo) if created_at.tzinfo
                   else datetime.now())
            age = now - created_at
            hours = age.total_seconds() / 3600
            label = f"{hours:.1f} 小时前" if hours >= 1 else f"{age.total_seconds()/60:.0f} 分钟前"
            print(f"   建于     {label}（{created}）· 图 {state.get('drawing', '?')}")
            if hours >= 2:
                print("   注意     这是较早的任务；若与当前图纸不符，先 upload 新建，"
                      "不要在残留任务上继续。")
        except ValueError:
            pass

    hint = NEXT_HINT.get(wb.get("blocking_action") or "")
    print("4) 下一步 " + (hint.replace("下一步  ", "") if hint else "status 查看"))
    return 0


# ---------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="任务 id；缺省用当前指针")
    ap.add_argument("--backend", help="后端地址；缺省读 CRAFT_BACKEND_URL")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="首次使用自检：地址、后端、当前任务、下一步").set_defaults(func=cmd_doctor)

    sub.add_parser("health", help="检查后端地址是否可用").set_defaults(func=cmd_health)

    sub.add_parser("status", help="当前阶段、阻断点、下一步").set_defaults(func=cmd_status)

    up = sub.add_parser("upload", help="上传图纸并建任务")
    up.add_argument("file")
    up.add_argument("--library-key", default="default")
    up.add_argument("--timeout", type=int, default=300)
    up.add_argument("--ledger", default=DEFAULT_LEDGER)
    up.set_defaults(func=cmd_upload)

    ad = sub.add_parser("adopt", help="接管已存在的 job（curl 直传后没有本地状态时）")
    ad.add_argument("job_id")
    ad.set_defaults(func=cmd_adopt)

    w = sub.add_parser("wait", help="等到 extracted")
    w.add_argument("--timeout", type=int, default=300)
    w.add_argument("--interval", type=float, default=6)
    w.set_defaults(func=cmd_wait)

    d = sub.add_parser("dump", help="工作台落盘 JSON")
    d.add_argument("--out")
    d.set_defaults(func=cmd_dump)

    r = sub.add_parser("review", help="特征复核（整表回传，值来自 answers）")
    r.add_argument("--answers", required=True)
    r.set_defaults(func=cmd_review)

    p = sub.add_parser("presence", help="结构特征与分支条件（必须覆盖全部项）")
    p.add_argument("--answers", help="人工确认后的答案文件；--list 时不需要")
    p.add_argument("--list", action="store_true", help="列出全部结构特征与当前值，逐条问人用")
    p.add_argument("--questions", metavar="OUT", help="导出可渲染的问题清单（ask.py 可生成可点选页面）")
    p.set_defaults(func=cmd_presence)

    m = sub.add_parser("match", help="算候选模板")
    m.add_argument("--limit", type=int, default=6)
    m.set_defaults(func=cmd_match)

    s = sub.add_parser("select", help="提交模板选择")
    s.add_argument("template_id")
    s.add_argument("--force", action="store_true", help="缺关键特征也提交（记为人工选择）")
    s.set_defaults(func=cmd_select)

    sl = sub.add_parser("slots", help="写槽位值")
    sl.add_argument("--values", required=True)
    sl.set_defaults(func=cmd_slots)

    sub.add_parser("finalize", help="slot-review 出卡并校验四字段").set_defaults(func=cmd_finalize)

    e = sub.add_parser("export", help="导出工艺卡")
    e.add_argument("out")
    e.set_defaults(func=cmd_export)

    pv = sub.add_parser("previews", help="列出预览图，可下载（复核单要用）")
    pv.add_argument("--download", help="下载到该目录")
    pv.set_defaults(func=cmd_previews)

    rs = sub.add_parser("result", help="识别原始结果落盘")
    rs.add_argument("--out")
    rs.set_defaults(func=cmd_result)

    ed = sub.add_parser("edit", help="整体替换工序（生成后人工改行）")
    ed.add_argument("--operations", required=True)
    ed.set_defaults(func=cmd_edit)

    args = ap.parse_args()
    if args.backend:
        import os
        os.environ["CRAFT_BACKEND_URL"] = args.backend
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

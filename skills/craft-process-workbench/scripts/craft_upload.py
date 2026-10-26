#!/usr/bin/env python3
"""Upload a drawing to the backend and never lose the job id.

The failure this fixes: a client waits ten seconds, the request does not come
back, and now nobody knows whether a job exists. The backend has no list
endpoint — `GET /api/jobs` is 405, only POST is allowed — so a lost job id is
unrecoverable except by asking a human to look at the workbench.

So every upload writes to a ledger before the bytes leave the machine:

    {"event":"attempt", "attempt_id":"...", "sha256":"...", "file":"...", ...}
    {"event":"result",  "attempt_id":"...", "job_id":"..."}

A timeout leaves an attempt without a result. That is not a failure and not a
success — it is an unresolved upload, and the ledger says so. Reconcile by
file hash: if the same drawing went up successfully within the reuse window,
reuse that job instead of creating a second one.

    craft_upload.py --file drawing.png --backend http://host:5199
    craft_upload.py --file drawing.png --backend http://host:5199 --timeout 300
    craft_upload.py --list                  # attempts, results, unresolved
    craft_upload.py --file drawing.png --backend http://host:5199 --force

Exit codes: 0 uploaded or reused, 2 state unknown (timeout), 3 request failed,
4 duplicate blocked.

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg"}
DEFAULT_LEDGER = "~/.config/craft-process/jobs.jsonl"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append(ledger: Path, record: dict) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_ledger(ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    out = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def multipart(fields: dict[str, str], path: Path) -> tuple[bytes, str]:
    boundary = f"----craft{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n".encode()
        + path.read_bytes()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def pick_job_id(payload: dict) -> str | None:
    for key in ("job_id", "jobId", "id", "uuid"):
        if isinstance(payload.get(key), str):
            return payload[key]
    for key in ("job", "data"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            found = pick_job_id(inner)
            if found:
                return found
    return None


def find_reusable(ledger: Path, digest: str, backend: str, window_hours: float) -> dict | None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    for rec in reversed(read_ledger(ledger)):
        if rec.get("event") != "result" or rec.get("sha256") != digest:
            continue
        if rec.get("backend") and rec["backend"] != backend:
            continue
        try:
            when = datetime.fromisoformat(rec["time"])
        except (KeyError, ValueError):
            continue
        if when >= cutoff:
            return rec
    return None


def cmd_list(ledger: Path) -> int:
    records = read_ledger(ledger)
    if not records:
        print(f"账本为空：{ledger}")
        return 0
    attempts = {r["attempt_id"]: r for r in records if r.get("event") == "attempt"}
    results = {r["attempt_id"]: r for r in records if r.get("event") == "result"}
    failures = {r["attempt_id"]: r for r in records if r.get("event") == "failed"}
    timeouts = {r["attempt_id"]: r for r in records if r.get("event") == "timeout"}
    print(f"账本：{ledger}\n")
    print(f"{'时间':<20} {'状态':<8} {'job_id':<24} 文件")
    for aid, att in attempts.items():
        if aid in results:
            state, jid = "成功", results[aid].get("job_id", "—")
        elif aid in failures:
            state, jid = "失败", "—"
        else:
            state, jid = ("未知", "—") if aid in timeouts else ("未决", "—")
        print(f"{att.get('time', '')[:19]:<20} {state:<8} {jid:<24} {att.get('file', '')}")
    unresolved = [a for a in attempts if a not in results and a not in failures]
    if unresolved:
        print(f"\n{len(unresolved)} 次上传状态未知（客户端超时或进程被杀），任务可能已经建出来了。")
        print("先在工作台按文件名和时间确认；确认没有再重传：--force。")
    return 0


def cmd_upload(args) -> int:
    path = Path(args.file).expanduser()
    if not path.is_file():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 3
    if path.suffix.lower() not in ALLOWED:
        print(f"只接受 PDF / PNG / JPG，收到 {path.suffix}", file=sys.stderr)
        return 3

    backend = args.backend.rstrip("/")
    ledger = Path(args.ledger).expanduser()
    digest = sha256_of(path)

    if not args.force:
        prior = find_reusable(ledger, digest, backend, args.reuse_window)
        if prior:
            print(f"同一份文件 {args.reuse_window:g} 小时内已上传过：job_id={prior['job_id']}")
            print(f"（sha256 {digest[:12]}…，{prior.get('time', '')[:19]}，{prior.get('file', '')}）")
            print("要继续用这个任务就按 id 往下走；确实要新建任务用 --force。")
            if args.json:
                print(json.dumps({"job_id": prior["job_id"], "reused": True}, ensure_ascii=False))
            return 4

    attempt_id = uuid.uuid4().hex
    body, ctype = multipart({"library_key": args.library_key}, path)
    req = urllib.request.Request(
        f"{backend}/api/jobs", data=body, method="POST",
        headers={"Content-Type": ctype, "Content-Length": str(len(body))},
    )

    append(ledger, {
        "event": "attempt", "attempt_id": attempt_id, "time": now_iso(),
        "sha256": digest, "size": path.stat().st_size, "file": str(path),
        "name": path.name, "backend": backend, "timeout": args.timeout,
    })

    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", "replace")
    except (socket.timeout, TimeoutError):
        append(ledger, {"event": "timeout", "attempt_id": attempt_id, "time": now_iso(),
                        "seconds": round(time.time() - started, 1), "sha256": digest,
                        "file": str(path), "backend": backend})
        print(f"等待 {args.timeout:g} 秒没有响应，状态未知——不是失败。", file=sys.stderr)
        print(f"已记入账本：attempt {attempt_id[:8]}（sha256 {digest[:12]}…）。", file=sys.stderr)
        print("先在工作台按文件名和时间确认；确认没有再重传：", file=sys.stderr)
        print(f"  {Path(sys.argv[0]).name} --file {path} --backend {backend} --force", file=sys.stderr)
        print("重传最多多一个孤儿任务，不影响已有结果。", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        append(ledger, {"event": "failed", "attempt_id": attempt_id, "time": now_iso(),
                        "http": exc.code, "detail": detail, "sha256": digest,
                        "file": str(path), "backend": backend})
        print(f"上传被拒绝：HTTP {exc.code}\n{detail}", file=sys.stderr)
        return 3
    except urllib.error.URLError as exc:
        append(ledger, {"event": "failed", "attempt_id": attempt_id, "time": now_iso(),
                        "error": str(exc.reason), "sha256": digest,
                        "file": str(path), "backend": backend})
        print(f"连不上 {backend}：{exc.reason}", file=sys.stderr)
        return 3

    elapsed = round(time.time() - started, 1)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}
    job_id = pick_job_id(payload)

    append(ledger, {"event": "result", "attempt_id": attempt_id, "time": now_iso(),
                    "sha256": digest, "file": str(path), "backend": backend,
                    "job_id": job_id, "http": status, "seconds": elapsed})
    if not job_id:
        print(f"HTTP {status}，但响应里没有 job_id。原始响应：", file=sys.stderr)
        print(raw[:800], file=sys.stderr)
        return 3

    if args.json:
        print(raw.strip())
        return 0
    print(f"job_id   {job_id}")
    print(f"耗时     {elapsed}s    HTTP {status}")
    print(f"文件     {path.name}  {path.stat().st_size} bytes  sha256 {digest[:12]}…")
    print(f"账本     {ledger}")
    hours = int(payload.get("estimated_seconds", 0) or 0)
    if hours:
        print(f"预计识别 {hours}s；用 MCP 的 craft_wait_job 或轮询 /api/jobs/{job_id} 等 extracted。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="图纸（PDF / PNG / JPG）")
    ap.add_argument("--backend", default=os.environ.get("CRAFT_BACKEND_URL", ""),
                    help="后端地址，默认取 CRAFT_BACKEND_URL")
    ap.add_argument("--library-key", default="default")
    ap.add_argument("--timeout", type=float, default=180.0, help="等待秒数，默认 180")
    ap.add_argument("--ledger", default=DEFAULT_LEDGER, help=f"账本路径，默认 {DEFAULT_LEDGER}")
    ap.add_argument("--reuse-window", type=float, default=72.0, help="同哈希去重窗口（小时）")
    ap.add_argument("--force", action="store_true", help="跳过去重，确实要新建任务")
    ap.add_argument("--list", action="store_true", help="列出账本，含未决上传")
    ap.add_argument("--json", action="store_true", help="只输出后端原始响应 JSON")
    args = ap.parse_args()

    ledger = Path(args.ledger).expanduser()
    if args.list:
        return cmd_list(ledger)
    if not args.file or not args.backend:
        ap.error("需要 --file 和 --backend（或设置 CRAFT_BACKEND_URL）")
    return cmd_upload(args)


if __name__ == "__main__":
    raise SystemExit(main())

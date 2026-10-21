# Patch 3: let `create_job` accept file content

Risk: medium. Adds an input contract; does not change existing behaviour if paths remain supported.

## Symptom

`craft_create_job` fails with "file not found" for a file the caller is looking at. The path is valid on the caller's machine.

## Root cause

The tool accepts a filesystem path and resolves it on the shell's host. A path is not a transfer. Clients and servers rarely share a filesystem, and asking every client to place files on the server is an operational dead end: it makes the tool unusable from laptops, agents in sandboxes, and anything that did not happen to deploy next to the service.

## Contract

Keep the existing input and add two forms:

```json
{
  "files": [
    "./local/path/drawing.png",
    { "name": "drawing.png", "content_base64": "iVBORw0KGgo..." },
    { "name": "drawing.pdf", "url": "https://example.invalid/drawing.pdf" }
  ]
}
```

The server normalises all three into bytes and performs the same multipart upload it already performs today. Everything downstream is unchanged: job id, polling, workbench.

The client stops needing to know about the backend host, the container, or the deployment topology. That is the point of the change: the topology becomes an implementation detail of the server, where it belongs.

## Implementation sketch

```python
def read_source(item) -> tuple[str, bytes]:
    if isinstance(item, str):
        with open(item, "rb") as fh:
            return Path(item).name, fh.read()
    if "content_base64" in item:
        return item.get("name") or "upload", base64.b64decode(item["content_base64"])
    if "url" in item:
        return item.get("name") or "upload", fetch(item["url"], limits)
    raise ValueError("unsupported file source")
```

Upload with the backend's existing expectations: multipart field name `files`, accepted types PDF, PNG and JPG.

## Limits that must exist before shipping

Size cap per file and per request, enforced before decoding.

Content-type check on decoded bytes, not on the declared name.

For URLs: schemes limited to `https` (and `http` only when explicitly configured), no redirects to private address ranges, a connect and total timeout, and a cap on bytes read. An unrestricted URL fetch in a server that accepts user input is an SSRF primitive.

Base64 inflates payloads by about a third. Prefer a direct binary multipart endpoint for large drawings.

## Error messages

Return the reason, not just the failure: unknown source form, file too large, unsupported type, URL not permitted, URL fetch timeout. The current "file not found" message sends callers looking at their own disk when the problem is architectural.

## Tests

Path input still works.

Base64 round-trips to identical bytes.

URL input respects the size cap and rejects a private address.

A mixed array uploads all files in order.

An unsupported form returns a 4xx naming the accepted forms.

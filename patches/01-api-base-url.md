# Patch 1: make the backend base URL configurable

Risk: deployment only. No data change, no schema change.

## Symptom

The MCP shell completes `initialize`, lists its tools, and then every business tool fails:

```
connection_error: cannot reach template process service (http://127.0.0.1:5199/health):
All connection attempts failed
```

The backend is healthy from your machine. Its public health path returns `200`.

## Root cause

The shell resolves the backend address relative to its own network namespace. When the shell runs in a container and the backend runs on the host, `127.0.0.1` is the container itself. The two processes can be healthy and still unreachable from each other.

Two secondary causes produce the same symptom:

The base URL is hard-coded in the image, so configuration cannot override it.

The base URL lives in an environment file that is only read at container creation. A restart reuses the old environment.

## Fix

Read the base URL from the environment with a sensible default, and document it:

```python
BASE_URL = os.environ.get("CRAFT_API_BASE_URL", "http://127.0.0.1:5199").rstrip("/")
```

In the deployment, set it to an address routable from inside the shell's namespace. For a shell on the default Docker bridge talking to a host process, the bridge gateway is the usual choice:

```dotenv
CRAFT_API_BASE_URL=http://<docker-bridge-gateway>:5199
```

Then recreate the container so the environment is re-injected:

```bash
docker-compose up -d --force-recreate
```

Note the hyphen. Hosts with only Compose v1 reject `docker compose` (v2) with `unknown shorthand flag: 'd'`.

## Verify

From inside the shell's namespace, request the backend health path. It should return the same payload you see from outside. Then call a read-only tool; a successful workbench read proves the hop.

## Why not just publish the backend on the host network

Running the shell with host networking also fixes reachability, at the cost of port collisions and a wider blast radius. Prefer an explicit, routable address; it keeps the container boundary intact and makes the dependency visible in configuration.

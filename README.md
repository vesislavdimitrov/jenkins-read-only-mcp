# jenkins-read-only-mcp

A read-only lightweight [Model Context Protocol](https://modelcontextprotocol.io/) server for Jenkins. It exposes Jenkins' REST API as a small set of MCP tools an LLM agent can call to investigate jobs, builds, console logs, queues, and pipeline definitions — without any ability to trigger or modify builds.

## Features

All tools are read-only. Nothing in this server can start, stop, abort, or reconfigure a build.

| Tool | Purpose |
| --- | --- |
| `list_jobs` | List jobs/folders at a Jenkins path. |
| `get_job_status` | Summary status for one job; optional `include_recent` embeds the last N builds. |
| `get_build_info` | Details for one build. Accepts aliases (`lastBuild`, `lastSuccessfulBuild`, `lastFailedBuild`, `lastCompletedBuild`). |
| `get_recent_builds` | Last N builds for a job in one call (newest-first). |
| `get_build_console` | Console log; tail by default, optional `pattern` grep with surrounding context. |
| `list_build_artifacts` | Archived artifacts for a build. |
| `get_build_artifact` | Read one artifact file (text decoded; binary base64'd; capped at 10 MiB). |
| `walk_jobs` | Recursively flatten jobs under a folder, with `status` / `kind` filters. |
| `search_jobs` | Substring or regex search over job names/paths across the tree. |
| `list_queue` | Items currently waiting in the build queue. |
| `list_running` | Builds executing on any node right now. |
| `get_pipeline_definition` | Inline Jenkinsfile script or SCM pointer for a pipeline job. |

## Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (the `setup.sh` installer fetches it if missing)
- Network access to a Jenkins instance

Dependencies: `mcp` (FastMCP) and `httpx`.

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and edit, or export the values in your shell.

| Variable | Default | Purpose |
| --- | --- | --- |
| `JENKINS_URL` | `http://localhost:8080` | Jenkins base URL (trailing slash stripped). Must be `http://` or `https://`. |
| `JENKINS_USER` | _(unset)_ | Jenkins username for basic auth. Optional — leave blank for anonymous access. |
| `JENKINS_TOKEN` | _(unset)_ | Jenkins API token. Required when `JENKINS_USER` is set. |
| `JENKINS_TIMEOUT` | `10` | Per-request HTTP timeout in seconds. |
| `HTTP_HOST` | `0.0.0.0` | Bind host when serving over HTTP (`--http`). |
| `PORT` | `8000` | Port when serving over HTTP. |
| `ENABLE_DNS_REBINDING_PROTECTION` | `false` | Enable the FastMCP DNS-rebinding allowlist for the HTTP transport. |

## Running locally

### stdio (default — for desktop MCP clients)

```bash
uv run python server.py
```

Wire it into a client like Claude Desktop / Claude Code by pointing at the `server.py` entry. Example MCP config snippet:

```json
{
  "mcpServers": {
    "jenkins": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/jenkins-read-only-mcp", "python", "server.py"],
      "env": {
        "JENKINS_URL": "https://jenkins.example.com",
        "JENKINS_USER": "your-user",
        "JENKINS_TOKEN": "your-token"
      }
    }
  }
}
```

### HTTP (streamable)

```bash
uv run python server.py --http
# or override host/port from the CLI:
uv run python server.py --http --host 127.0.0.1 --port 8080
```

The endpoint is `http://<host>:<port>/mcp`.

## Docker

Build and run the HTTP transport:

```bash
docker build -t jenkins-read-only-mcp .
docker run --rm -p 8000:8000 --env-file .env jenkins-read-only-mcp
```

Endpoint: `http://localhost:8000/mcp`. The image defaults to `server.py --http`; override the command for stdio or other flags.

## Deploying with `setup.sh`

`setup.sh` is an idempotent installer for hosting the HTTP transport on a Linux box. Copy the project into `INSTALL_DIR`, then run as root:

```bash
sudo ./setup.sh
```

It installs `uv` if needed, syncs the Python environment, kills any old instance, and restarts under `nohup`. Override behavior via env vars:

| Variable | Default |
| --- | --- |
| `INSTALL_DIR` | `/opt/jenkins-mcp` |
| `LOG_FILE` | `/var/log/jenkins-mcp.log` |
| `PYTHON` | `3.12` |
| `HTTP_PORT` | `8000` (used only in the printed endpoint URL) |
| `ENDPOINT_HOST` | `$(hostname -f)` |

Logs: `tail -f /var/log/jenkins-mcp.log`.

## Notes on safety

- **No write paths.** The server only issues `GET` requests against Jenkins' `/api/json`, `/consoleText`, `/artifact/`, `/config.xml`, `/queue/api/json`, and `/computer/api/json` endpoints.
- **Errors are returned, not raised.** Each tool wraps its body in a `_safe` decorator that turns HTTP and request errors into `{"error": "..."}` responses, so a failing call doesn't tear down the MCP session.
- **Response size caps.** Console logs default to a 200-line tail; artifacts default to 2 MiB and cap at 10 MiB; tree walks cap at 500 jobs by default and surface a `truncated: true` flag when exceeded.

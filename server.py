from __future__ import annotations

import argparse
import functools
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from config import Config, ConfigError
from jenkins_client import JenkinsClient

config = Config.from_env()
client = JenkinsClient(config)
mcp = FastMCP(
    "jenkins",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=config.enable_dns_rebinding_protection
    ),
)


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code} for {e.request.url}"}
        except httpx.RequestError as e:
            return {"error": f"request failed: {e!s}"}
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
    return wrapper


@mcp.tool()
@_safe
def list_jobs(path: str = "") -> dict[str, Any]:
    """List jobs/folders at a Jenkins path.

    `path` is slash-separated ("my-folder/sub-folder") or "" for the Jenkins
    root; a full Jenkins URL is also accepted.

    Returns the folder's name/url and a `jobs` list of {name, url, status,
    is_folder}.
    """
    return client.list_jobs(path)


@mcp.tool()
@_safe
def get_job_status(job_path: str, include_recent: int = 0) -> dict[str, Any]:
    """Get summary status for a single Jenkins job.

    Returns name/url/status plus pointers (number+url) for the last build,
    last successful build, and last failed build.

    `include_recent` (default 0) embeds the last N builds inline as
    `recent_builds` (1-100). Use this to skip a follow-up call to
    get_recent_builds when investigating a job. Tip: use the
    `lastFailedBuild` / `lastSuccessfulBuild` aliases with get_build_info
    or get_build_console to skip a hop when you only need one build.
    """
    return client.get_job_status(job_path, include_recent)


@mcp.tool()
@_safe
def get_build_info(job_path: str, build_number: int | str = "lastBuild") -> dict[str, Any]:
    """Get details for a specific build.

    `build_number` accepts an int or a Jenkins alias: "lastBuild",
    "lastSuccessfulBuild", "lastFailedBuild", "lastCompletedBuild".

    Returns number, result, building flag, duration, timestamp, URL,
    parameters, and causes.
    """
    return client.get_build_info(job_path, build_number)


@mcp.tool()
@_safe
def get_recent_builds(job_path: str, count: int = 10) -> dict[str, Any]:
    """Get the last N builds for a job in one call (newest-first).

    `count` is 1-100 (default 10). Each entry has number, url, result,
    building, timestamp, duration_ms, parameters, causes.
    """
    return client.get_recent_builds(job_path, count)


@mcp.tool()
@_safe
def get_build_console(
    job_path: str,
    build_number: int | str = "lastBuild",
    tail_lines: int = 200,
    pattern: str | None = None,
    regex: bool = False,
    context: int = 3,
) -> dict[str, Any]:
    """Get the console log for a build (tail by default to keep responses small).

    `build_number` accepts the same aliases as get_build_info.
    `tail_lines` is the number of trailing lines to return; pass a larger
    number (e.g. 5000) for more, or 0 for the full log.

    `pattern` (optional) finds matching lines anywhere in the full log and
    returns them with surrounding `context` lines (default 3, max 50). Set
    `regex=True` for regex matching, otherwise case-insensitive substring.
    Use this to locate the actual error in a long build instead of relying
    on the tail. The full tail is still returned alongside `matches`.

    Returns the requested console text plus the total line count.
    """
    return client.get_build_console(job_path, build_number, tail_lines, pattern, regex, context)


@mcp.tool()
@_safe
def list_build_artifacts(
    job_path: str,
    build_number: int | str = "lastBuild",
) -> dict[str, Any]:
    """List archived artifacts for a build.

    `build_number` accepts the same aliases as get_build_info.

    Returns count and a list of {file_name, relative_path, url}. Use
    `relative_path` with get_build_artifact to fetch a file's contents.
    """
    return client.list_build_artifacts(job_path, build_number)


@mcp.tool()
@_safe
def get_build_artifact(
    job_path: str,
    relative_path: str,
    build_number: int | str = "lastBuild",
    max_bytes: int = 2 * 1024 * 1024,
) -> dict[str, Any]:
    """Read one artifact file from a build.

    `relative_path` is the value from list_build_artifacts (e.g. "out/report.json").
    `max_bytes` caps the returned payload (default 2 MiB, max 10 MiB; 0 means no cap).

    Text artifacts are returned UTF-8 decoded with `is_text: true`. Binary
    artifacts are returned base64-encoded with `is_text: false`. `truncated`
    is set when the artifact exceeded `max_bytes`.
    """
    return client.get_build_artifact(job_path, relative_path, build_number, max_bytes)



@mcp.tool()
@_safe
def walk_jobs(
    path: str = "",
    depth: int = 3,
    max_jobs: int = 500,
    status: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Recursively list all jobs under a folder, flattened.

    `depth` is 1-8 (default 3). `max_jobs` caps the response and sets
    `truncated: true` when exceeded. Each entry has path, name, url, status,
    is_folder, depth.

    `status` (optional) filters by substring match on the `status` field
    (e.g. "failure", "success", "running"). `kind` (optional) filters by
    item type: "folder", "job", or "pipeline" (matches WorkflowJob).
    Both filters are applied before `max_jobs` truncation.
    """
    return client.walk_jobs(path, depth, max_jobs, status, kind)


@mcp.tool()
@_safe
def search_jobs(
    pattern: str,
    root: str = "",
    depth: int = 8,
    regex: bool = False,
    max_jobs: int = 500,
    status: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Search for jobs by name across the tree.

    Substring match by default (case-insensitive); pass `regex=True` for a
    regex. `root` is "" for the whole Jenkins. `depth` is 1-8.

    `status` and `kind` work the same as in walk_jobs — combine with
    `pattern` to e.g. find failing pipelines under a folder in one call.
    """
    return client.search_jobs(pattern, root, depth, regex, max_jobs, status, kind)


@mcp.tool()
@_safe
def list_queue() -> dict[str, Any]:
    """List items currently in Jenkins' build queue (waiting to start).

    Each item has: job, url, why (human-readable wait reason),
    in_queue_since (epoch ms), parameters.
    """
    return client.list_queue()


@mcp.tool()
@_safe
def list_running() -> dict[str, Any]:
    """List builds currently executing on any Jenkins node.

    Each entry has: node, job, build_number, url, timestamp.
    """
    return client.list_running()


@mcp.tool()
@_safe
def get_pipeline_definition(job_path: str) -> dict[str, Any]:
    """Get a pipeline job's Jenkinsfile / SCM definition.

    For inline pipelines: returns the script text.
    For SCM-backed pipelines: returns scm class/url/branch and script_path.
    Returns an error field for non-pipeline jobs or when config.xml is not
    accessible.
    """
    return client.get_pipeline_definition(job_path)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jenkins-mcp",
        description="Read-only Jenkins MCP server (stdio by default, HTTP with --http).",
    )
    parser.add_argument("--http", action="store_true", help="serve over HTTP instead of stdio")
    parser.add_argument("--host", default=None, help=f"HTTP bind host (default: {config.http_host})")
    parser.add_argument("--port", type=int, default=None, help=f"HTTP port (default: {config.http_port})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not args.http:
        mcp.run()
        return
    mcp.settings.host = args.host or config.http_host
    mcp.settings.port = args.port or config.http_port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    try:
        main()
    except ConfigError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        sys.exit(2)

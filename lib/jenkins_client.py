from __future__ import annotations

from typing import Any

from .config import Config
from .exceptions import JenkinsHTTPError, JenkinsValidationError
from .jenkins_http import JenkinsHTTP
from .jenkins_utils import (
    build_matcher,
    build_summary,
    build_walk_tree,
    color_to_status,
    computer_tree,
    decode_artifact,
    flatten_tree,
    grep_lines,
    iter_running,
    job_status_tree,
    make_walk_filter,
    normalize_root_path,
    parse_pipeline_config,
    recent_builds_tree,
    root_name,
    scan_warning,
    shape_artifact,
    shape_build,
    shape_job_summary,
    shape_queue_item,
    shape_recent_build,
    take,
    validate_range,
)


class JenkinsClient:
    MAX_WALK_DEPTH = 8
    DEFAULT_WALK_DEPTH = 3
    DEFAULT_WALK_MAX_JOBS = 500
    DEFAULT_RECENT_BUILDS = 10
    MAX_RECENT_BUILDS = 100
    DEFAULT_ARTIFACT_BYTES = 2 * 1024 * 1024
    MAX_ARTIFACT_BYTES = 10 * 1024 * 1024

    def __init__(self, config: Config, http: JenkinsHTTP | None = None) -> None:
        self._config = config
        self._http = http or JenkinsHTTP(config)

    def list_jobs(self, path: str = "") -> dict[str, Any]:
        data = self._http.get_json(path)
        return {
            "name": root_name(data),
            "url": data.get("url", self._config.jenkins_url),
            "jobs": [shape_job_summary(j) for j in data.get("jobs", []) or []],
        }

    def get_job_status(self, job_path: str, include_recent: int = 0) -> dict[str, Any]:
        validate_range("include_recent", include_recent, low=0, high=self.MAX_RECENT_BUILDS)
        params = {"tree": job_status_tree(include_recent)} if include_recent else None
        data = self._http.get_json(job_path, params=params)
        result = {
            "name": data.get("fullDisplayName") or data.get("name"),
            "url": data.get("url"),
            "status": color_to_status(data.get("color")),
            "buildable": data.get("buildable"),
            "in_queue": data.get("inQueue"),
            "last_build": build_summary(data.get("lastBuild")),
            "last_completed_build": build_summary(data.get("lastCompletedBuild")),
            "last_successful_build": build_summary(data.get("lastSuccessfulBuild")),
            "last_failed_build": build_summary(data.get("lastFailedBuild")),
            "last_unsuccessful_build": build_summary(data.get("lastUnsuccessfulBuild")),
        }
        if include_recent:
            result["recent_builds"] = [shape_recent_build(b) for b in data.get("builds", []) or []]
        return result

    def get_build_info(self, job_path: str, build_number: int | str = "lastBuild") -> dict[str, Any]:
        bn = self._http.safe_build_number(build_number)
        data = self._http.get(job_path, suffix=f"/{bn}/api/json").json()
        return shape_build(data)

    def get_recent_builds(self, job_path: str, count: int = DEFAULT_RECENT_BUILDS) -> dict[str, Any]:
        validate_range("count", count, low=1, high=self.MAX_RECENT_BUILDS)
        data = self._http.get_json(job_path, params={"tree": recent_builds_tree(count)})
        builds = [shape_recent_build(b) for b in data.get("builds", []) or []]
        return {
            "job": job_path,
            "url": data.get("url"),
            "count": len(builds),
            "builds": builds,
        }

    def get_build_console(
        self,
        job_path: str,
        build_number: int | str = "lastBuild",
        tail_lines: int = 200,
        pattern: str | None = None,
        regex: bool = False,
        context: int = 3,
    ) -> dict[str, Any]:
        bn = self._http.safe_build_number(build_number)
        validate_range("context", context, low=0, high=50)
        validate_range("tail_lines", tail_lines, low=0)
        response = self._http.get(job_path, suffix=f"/{bn}/consoleText")
        lines = response.text.splitlines()
        total = len(lines)
        truncated = bool(tail_lines and total > tail_lines)
        shown = lines[-tail_lines:] if truncated else lines
        result: dict[str, Any] = {
            "url": str(response.request.url),
            "total_lines": total,
            "returned_lines": len(shown),
            "truncated": truncated,
            "console": "\n".join(shown),
        }
        if not pattern:
            return result
        matches = grep_lines(lines, pattern, regex=regex, context=context)
        result["pattern"] = pattern
        result["regex"] = regex
        result["match_count"] = len(matches)
        result["matches"] = matches
        return result

    def list_build_artifacts(
        self,
        job_path: str,
        build_number: int | str = "lastBuild",
    ) -> dict[str, Any]:
        bn = self._http.safe_build_number(build_number)
        data = self._http.get(
            job_path,
            suffix=f"/{bn}/api/json",
            params={"tree": "url,artifacts[fileName,relativePath]"},
        ).json()
        build_url = data.get("url")
        artifacts = [shape_artifact(a, build_url) for a in data.get("artifacts", []) or []]
        return {
            "job": job_path,
            "build_number": bn,
            "url": build_url,
            "count": len(artifacts),
            "artifacts": artifacts,
        }

    def get_build_artifact(
        self,
        job_path: str,
        relative_path: str,
        build_number: int | str = "lastBuild",
        max_bytes: int = DEFAULT_ARTIFACT_BYTES,
    ) -> dict[str, Any]:
        bn = self._http.safe_build_number(build_number)
        rel = self._http.safe_relative_path(relative_path)
        validate_range("max_bytes", max_bytes, low=0, high=self.MAX_ARTIFACT_BYTES)
        response = self._http.get(job_path, suffix=f"/{bn}/artifact/{rel}")
        cap = max_bytes if max_bytes > 0 else len(response.content)
        decoded = decode_artifact(response.content, cap)
        return {
            "job": job_path,
            "build_number": bn,
            "relative_path": relative_path,
            "url": str(response.request.url),
            "content_type": response.headers.get("content-type"),
            **decoded,
        }

    def walk_jobs(
        self,
        path: str = "",
        depth: int = DEFAULT_WALK_DEPTH,
        max_jobs: int = DEFAULT_WALK_MAX_JOBS,
        status: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        validate_range("depth", depth, low=1, high=self.MAX_WALK_DEPTH)
        validate_range("max_jobs", max_jobs, low=1)

        keep = make_walk_filter(status=status, kind=kind)
        data = self._http.get_json(path, params={"tree": build_walk_tree(depth)})
        root = normalize_root_path(path)
        entries = (e for e in flatten_tree(data, root, 0, depth) if keep(e))
        flat, truncated = take(entries, max_jobs)
        return {
            "root": root or "(root)",
            "url": data.get("url", self._config.jenkins_url),
            "depth": depth,
            "status_filter": status,
            "kind_filter": kind,
            "count": len(flat),
            "truncated": truncated,
            "jobs": flat,
        }

    def search_jobs(
        self,
        pattern: str,
        root: str = "",
        depth: int = 8,
        regex: bool = False,
        max_jobs: int = DEFAULT_WALK_MAX_JOBS,
        status: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        if not pattern:
            raise JenkinsValidationError("pattern must not be empty")

        matcher = build_matcher(pattern, regex=regex)
        walk = self.walk_jobs(path=root, depth=depth, max_jobs=max_jobs, status=status, kind=kind)
        matches = [j for j in walk["jobs"] if matcher(j["name"]) or matcher(j["path"])]
        return {
            "pattern": pattern,
            "regex": regex,
            "root": walk["root"],
            "status_filter": status,
            "kind_filter": kind,
            "scanned": walk["count"],
            "scan_truncated": walk["truncated"],
            "warning": scan_warning(walk["truncated"], max_jobs),
            "match_count": len(matches),
            "matches": matches,
        }

    def list_queue(self) -> dict[str, Any]:
        data = self._http.get(
            "",
            suffix="/queue/api/json",
            params={"tree": "items[task[name,url],why,inQueueSince,actions[parameters[name,value]]]"},
        ).json()
        items = [shape_queue_item(it, self._config.jenkins_url) for it in data.get("items", []) or []]
        return {"count": len(items), "items": items}

    def list_running(self) -> dict[str, Any]:
        data = self._http.get("", suffix="/computer/api/json", params={"tree": computer_tree()}).json()
        running = list(iter_running(data, self._config.jenkins_url))
        return {"count": len(running), "running": running}

    def get_pipeline_definition(self, job_path: str) -> dict[str, Any]:
        meta = self._http.get_json(job_path)
        cls = meta.get("_class", "")
        if "WorkflowJob" not in cls:
            return {
                "job": job_path,
                "type": None,
                "_class": cls,
                "error": "not a pipeline job",
            }

        try:
            xml = self._http.get(job_path, suffix="/config.xml").text
        except JenkinsHTTPError as e:
            return {
                "job": job_path,
                "type": "pipeline",
                "_class": cls,
                "url": meta.get("url"),
                "error": f"config.xml not accessible (HTTP {e.status_code})",
            }

        return {
            "job": job_path,
            "type": "pipeline",
            "_class": cls,
            "url": meta.get("url"),
            **parse_pipeline_config(xml),
        }

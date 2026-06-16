from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Iterator
from urllib.parse import urlparse


_COLOR_STATUS = {
    "blue": "success",
    "red": "failure",
    "yellow": "unstable",
    "aborted": "aborted",
    "disabled": "disabled",
    "notbuilt": "not_built",
    "grey": "not_built",
}
_ANIME_SUFFIX = "_anime"
_KIND_ALIASES = {
    "folder": "folder",
    "folders": "folder",
    "job": "job",
    "jobs": "job",
    "pipeline": "pipeline",
    "pipelines": "pipeline",
}
_SCRIPT_RE = re.compile(r"<script>(?P<script>.*?)</script>", re.DOTALL)
_SCRIPT_PATH_RE = re.compile(r"<scriptPath>(?P<path>.*?)</scriptPath>", re.DOTALL)
_YAML_PATH_RE = re.compile(r"<yamlPath>(?P<path>.*?)</yamlPath>", re.DOTALL)
_SANDBOX_RE = re.compile(r"<sandbox>(?P<v>true|false)</sandbox>", re.DOTALL)
_SCM_CLASS_RE = re.compile(r'<scm class="(?P<cls>[^"]+)"')
_SCM_URL_RE = re.compile(r"<url>(?P<url>.*?)</url>", re.DOTALL)
_SCM_BRANCH_RE = re.compile(r"<name>(?P<branch>\*?/[^<]+)</name>", re.DOTALL)


def color_to_status(color: str | None) -> str:
    if not color:
        return "unknown"
    building = color.endswith(_ANIME_SUFFIX)
    base = color[: -len(_ANIME_SUFFIX)] if building else color
    status = _COLOR_STATUS.get(base, base)
    return f"running ({status})" if building else status


def build_summary(b: dict[str, Any] | None) -> dict[str, Any] | None:
    if not b:
        return None
    return {"number": b.get("number"), "url": b.get("url")}


def extract_parameters(actions: Iterable[dict[str, Any]] | None) -> dict[str, Any]:
    for a in actions or []:
        if "parameters" in a:
            return {p.get("name"): p.get("value") for p in a["parameters"] if p.get("name")}
    return {}


def extract_causes(actions: Iterable[dict[str, Any]] | None) -> list[str]:
    return [
        c["shortDescription"]
        for a in actions or []
        for c in a.get("causes", []) or []
        if c.get("shortDescription")
    ]


def is_folder_class(cls: str | None, has_color: bool) -> bool:
    return (cls or "").endswith("Folder") or not has_color


def shape_build(data: dict[str, Any]) -> dict[str, Any]:
    actions = data.get("actions", []) or []
    return {
        "number": data.get("number"),
        "url": data.get("url"),
        "result": data.get("result"),
        "building": data.get("building"),
        "duration_ms": data.get("duration"),
        "estimated_duration_ms": data.get("estimatedDuration"),
        "timestamp": data.get("timestamp"),
        "display_name": data.get("displayName"),
        "full_display_name": data.get("fullDisplayName"),
        "parameters": extract_parameters(actions),
        "causes": extract_causes(actions),
    }


def shape_recent_build(data: dict[str, Any]) -> dict[str, Any]:
    actions = data.get("actions", []) or []
    return {
        "number": data.get("number"),
        "url": data.get("url"),
        "result": data.get("result"),
        "building": data.get("building"),
        "timestamp": data.get("timestamp"),
        "duration_ms": data.get("duration"),
        "parameters": extract_parameters(actions),
        "causes": extract_causes(actions),
    }


def shape_job_summary(j: dict[str, Any]) -> dict[str, Any]:
    cls = j.get("_class", "")
    is_folder = is_folder_class(cls, has_color="color" in j)
    return {
        "name": j.get("name"),
        "url": j.get("url"),
        "status": "folder" if is_folder else color_to_status(j.get("color")),
        "is_folder": is_folder,
        "_class": cls,
    }


def shape_walk_entry(j: dict[str, Any], path: str, depth: int) -> dict[str, Any]:
    cls = j.get("_class", "")
    is_folder = is_folder_class(cls, has_color="color" in j)
    return {
        "path": path,
        "name": j.get("name") or "",
        "url": j.get("url"),
        "status": "folder" if is_folder else color_to_status(j.get("color")),
        "is_folder": is_folder,
        "depth": depth,
        "_class": cls,
    }


def shape_queue_item(it: dict[str, Any], base_url: str) -> dict[str, Any]:
    task = it.get("task") or {}
    return {
        "job": url_to_job_path(task.get("url", ""), base_url) or task.get("name"),
        "url": task.get("url"),
        "why": it.get("why"),
        "in_queue_since": it.get("inQueueSince"),
        "parameters": extract_parameters(it.get("actions", [])),
    }


def shape_running(node_name: str | None, cur: dict[str, Any], base_url: str) -> dict[str, Any]:
    url = cur.get("url", "")
    return {
        "node": node_name,
        "job": url_to_job_path(url, base_url),
        "build_number": cur.get("number"),
        "url": url,
        "timestamp": cur.get("timestamp"),
    }


def job_api_path(job_path: str) -> str:
    if not job_path:
        return ""
    s = job_path.strip()
    if s.startswith(("http://", "https://")):
        s = urlparse(s).path
    s = s.strip("/")
    if not s:
        return ""
    if s.startswith("job/"):
        return "/" + s
    return "".join(f"/job/{p}" for p in s.split("/") if p)


def url_to_job_path(url: str, base_url: str) -> str:
    if not url:
        return ""
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    out = []
    i = 0
    while i + 1 < len(parts):
        if parts[i] == "job":
            out.append(parts[i + 1])
            i += 2
            continue
        i += 1
    return "/".join(out)


def normalize_root_path(path: str) -> str:
    if not path:
        return ""
    s = path.strip()
    if s.startswith(("http://", "https://")):
        return urlparse(s).path.replace("/job/", "/").strip("/")
    return s.strip("/")


def build_walk_tree(depth: int) -> str:
    leaf = "name,url,color,_class"
    tree = leaf
    for _ in range(depth - 1):
        tree = f"{leaf},jobs[{tree}]"
    return f"jobs[{tree}]"


def flatten_tree(
    node: dict[str, Any],
    parent_path: str,
    current_depth: int,
    max_depth: int,
) -> Iterator[dict[str, Any]]:
    for j in node.get("jobs", []) or []:
        name = j.get("name") or ""
        entry_path = f"{parent_path}/{name}" if parent_path else name
        entry = shape_walk_entry(j, entry_path, current_depth + 1)
        yield entry
        if entry["is_folder"] and current_depth + 1 < max_depth and "jobs" in j:
            yield from flatten_tree(j, entry_path, current_depth + 1, max_depth)


def take(it: Iterable[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], bool]:
    out: list[dict[str, Any]] = []
    for x in it:
        if len(out) >= limit:
            return out, True
        out.append(x)
    return out, False


def build_matcher(pattern: str, *, regex: bool) -> Callable[[str | None], bool]:
    if regex:
        compiled = re.compile(pattern)
        return lambda s: bool(s and compiled.search(s))
    needle = pattern.lower()
    return lambda s: bool(s) and needle in s.lower()


def validate_range(name: str, value: int, *, low: int, high: int | None = None) -> None:
    if value < low:
        raise ValueError(f"{name} must be >= {low}, got {value}")
    if high is not None and value > high:
        raise ValueError(f"{name} must be <= {high}, got {value}")


def kind_of(entry: dict[str, Any]) -> str:
    if entry.get("is_folder"):
        return "folder"
    cls = entry.get("_class") or ""
    if "WorkflowJob" in cls:
        return "pipeline"
    return "job"


def make_walk_filter(
    status: str | None = None,
    kind: str | None = None,
) -> Callable[[dict[str, Any]], bool]:
    if not status and not kind:
        return lambda _e: True

    if kind:
        normalized = _KIND_ALIASES.get(kind.lower())
        if not normalized:
            raise ValueError(
                f"kind must be one of folder/job/pipeline, got {kind!r}"
            )
        kind = normalized

    needle = status.lower() if status else None

    def keep(entry: dict[str, Any]) -> bool:
        if kind and kind_of(entry) != kind:
            return False
        if needle and needle not in (entry.get("status") or "").lower():
            return False
        return True

    return keep


def grep_lines(
    lines: list[str],
    pattern: str,
    *,
    regex: bool = False,
    context: int = 3,
) -> list[dict[str, Any]]:
    matcher = build_matcher(pattern, regex=regex)
    matches: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        if not matcher(line):
            continue
        start = max(0, i - context)
        end = min(len(lines), i + context + 1)
        matches.append({
            "line_number": i + 1,
            "line": line,
            "context": lines[start:end],
            "context_start": start + 1,
        })
    return matches


def _unescape_xml(s: str) -> str:
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def _sandbox_value(xml: str) -> bool | None:
    m = _SANDBOX_RE.search(xml)
    return None if not m else m.group("v") == "true"


def _extract_scm(xml: str) -> dict[str, Any] | None:
    scm_class = _SCM_CLASS_RE.search(xml)
    url = _SCM_URL_RE.search(xml)
    branch = _SCM_BRANCH_RE.search(xml)
    if not (scm_class or url):
        return None
    return {
        "class": scm_class.group("cls") if scm_class else None,
        "url": url.group("url").strip() if url else None,
        "branch": branch.group("branch").strip() if branch else None,
    }


def parse_pipeline_config(xml: str) -> dict[str, Any]:
    sandbox = _sandbox_value(xml)
    inline = _SCRIPT_RE.search(xml)
    if inline:
        return {
            "definition": "inline",
            "script": _unescape_xml(inline.group("script")),
            "sandbox": sandbox,
            "scm": None,
        }
    scm_path = _SCRIPT_PATH_RE.search(xml)
    if scm_path:
        return {
            "definition": "scm",
            "script_path": scm_path.group("path").strip(),
            "sandbox": sandbox,
            "scm": _extract_scm(xml),
        }
    yaml_path = _YAML_PATH_RE.search(xml)
    if yaml_path:
        return {
            "definition": "yaml",
            "yaml_path": yaml_path.group("path").strip(),
            "sandbox": sandbox,
            "scm": _extract_scm(xml),
        }
    return {"definition": "unknown", "sandbox": sandbox, "scm": None}


def executors_of(node: dict[str, Any]) -> list[dict[str, Any]]:
    return (node.get("executors", []) or []) + (node.get("oneOffExecutors", []) or [])


def iter_running(data: dict[str, Any], base_url: str) -> Iterator[dict[str, Any]]:
    for node in data.get("computer", []) or []:
        node_name = node.get("displayName")
        for ex in executors_of(node):
            cur = ex.get("currentExecutable")
            if cur:
                yield shape_running(node_name, cur, base_url)


def recent_builds_tree(count: int) -> str:
    return (
        "builds[number,url,result,building,timestamp,duration,"
        "actions[causes[shortDescription],parameters[name,value]]]"
        f"{{0,{count}}}"
    )


def job_status_tree(include_recent: int) -> str:
    fields = [
        "fullDisplayName",
        "name",
        "url",
        "color",
        "buildable",
        "inQueue",
        "lastBuild[number,url]",
        "lastCompletedBuild[number,url]",
        "lastSuccessfulBuild[number,url]",
        "lastFailedBuild[number,url]",
        "lastUnsuccessfulBuild[number,url]",
    ]
    if include_recent:
        fields.append(recent_builds_tree(include_recent))
    return ",".join(fields)


def computer_tree() -> str:
    return (
        "computer[displayName,"
        "executors[currentExecutable[url,number,timestamp]],"
        "oneOffExecutors[currentExecutable[url,number,timestamp]]]"
    )


def root_name(data: dict[str, Any]) -> str:
    return (
        data.get("fullDisplayName")
        or data.get("displayName")
        or data.get("name")
        or "(root)"
    )


def scan_warning(truncated: bool, max_jobs: int) -> str | None:
    if not truncated:
        return None
    return (
        f"underlying walk truncated at {max_jobs} jobs; "
        "matches are only over the scanned subset"
    )


def shape_artifact(a: dict[str, Any], build_url: str | None) -> dict[str, Any]:
    rel = a.get("relativePath") or a.get("fileName") or ""
    return {
        "file_name": a.get("fileName"),
        "relative_path": rel,
        "url": f"{build_url.rstrip('/')}/artifact/{rel}" if build_url and rel else None,
    }


def decode_artifact(content: bytes, max_bytes: int) -> dict[str, Any]:
    total = len(content)
    truncated = max_bytes > 0 and total > max_bytes
    chunk = content[:max_bytes] if truncated else content
    try:
        text = chunk.decode("utf-8")
        return {
            "is_text": True,
            "encoding": "utf-8",
            "total_bytes": total,
            "returned_bytes": len(chunk),
            "truncated": truncated,
            "content": text,
        }
    except UnicodeDecodeError:
        import base64
        return {
            "is_text": False,
            "encoding": "base64",
            "total_bytes": total,
            "returned_bytes": len(chunk),
            "truncated": truncated,
            "content": base64.b64encode(chunk).decode("ascii"),
        }


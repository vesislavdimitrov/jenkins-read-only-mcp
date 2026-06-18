from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .config import Config
from .exceptions import JenkinsHTTPError, JenkinsRequestError, JenkinsValidationError


class JenkinsHTTP:
    def __init__(self, config: Config, http_client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = http_client or httpx.Client(
            auth=config.auth,
            timeout=config.jenkins_timeout,
            follow_redirects=True,
        )

    @property
    def base_url(self) -> str:
        return self._config.jenkins_url

    def get(
        self,
        path_or_url: str,
        *,
        suffix: str,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        url = f"{self._config.jenkins_url}{_safe_job_api_path(path_or_url)}{suffix}"
        try:
            r = self._client.get(url, params=params)
        except httpx.RequestError as e:
            raise JenkinsRequestError(f"request failed: {e!s}") from e
        if r.is_error:
            raise JenkinsHTTPError(r.status_code, str(r.request.url))
        return r

    def get_json(
        self,
        path_or_url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self.get(path_or_url, suffix="/api/json", params=params).json()

    @staticmethod
    def safe_build_number(value: int | str) -> str:
        return _safe_build_number(value)

    @staticmethod
    def safe_relative_path(value: str) -> str:
        return _safe_relative_path(value)


# --- Helpers for validating and constructing Jenkins API paths ---

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._\-+ %]+$")
_BUILD_ALIASES = frozenset(
    {
        "lastBuild",
        "lastCompletedBuild",
        "lastSuccessfulBuild",
        "lastFailedBuild",
        "lastUnsuccessfulBuild",
        "lastStableBuild",
        "lastUnstableBuild",
    }
)


def _segments_from(value: str) -> list[str]:
    s = value.strip()
    if s.startswith(("http://", "https://")):
        s = urlparse(s).path
    return [p for p in s.strip("/").split("/") if p]


def _strip_job_prefix(segments: list[str], original: str) -> list[str]:
    if not segments or segments[0] != "job":
        return segments
    if len(segments) % 2 != 0:
        raise JenkinsValidationError(f"malformed Jenkins URL path: {original!r}")
    if any(segments[i] != "job" for i in range(0, len(segments), 2)):
        raise JenkinsValidationError(f"malformed Jenkins URL path: {original!r}")
    return [segments[i] for i in range(1, len(segments), 2)]


def _validate_segment(name: str, kind: str) -> None:
    if name in ("", ".", ".."):
        raise JenkinsValidationError(f"invalid {kind} segment {name!r}")
    if not _SAFE_SEGMENT_RE.match(name):
        raise JenkinsValidationError(f"invalid characters in {kind} segment {name!r}")


def _safe_job_api_path(value: str) -> str:
    names = _strip_job_prefix(_segments_from(value), value)
    if not names:
        return ""
    for name in names:
        _validate_segment(name, "path")
    return "".join(f"/job/{quote(n, safe='')}" for n in names)


def _safe_build_number(value: int | str) -> str:
    if isinstance(value, bool):
        raise JenkinsValidationError(f"build_number must be int or alias, got {value!r}")
    if isinstance(value, int):
        if value <= 0:
            raise JenkinsValidationError(f"build_number must be positive, got {value}")
        return str(value)
    if not isinstance(value, str):
        raise JenkinsValidationError(f"build_number must be int or alias, got {value!r}")
    s = value.strip()
    if s in _BUILD_ALIASES:
        return s
    if s.isdigit() and int(s) > 0:
        return s
    raise JenkinsValidationError(f"build_number must be a positive int or known alias, got {value!r}")


def _safe_relative_path(value: str) -> str:
    if not value:
        raise JenkinsValidationError("relative_path must not be empty")
    if value.startswith(("/", "\\")):
        raise JenkinsValidationError(f"relative_path must be relative, got {value!r}")
    parts = re.split(r"[/\\]", value)
    for part in parts:
        _validate_segment(part, "relative_path")
    return "/".join(quote(p, safe="") for p in parts)

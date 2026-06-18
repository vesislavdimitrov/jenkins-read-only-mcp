from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    jenkins_url: str
    jenkins_user: str | None
    jenkins_token: str | None
    jenkins_timeout: float
    http_host: str
    http_port: int
    enable_dns_rebinding_protection: bool

    @property
    def auth(self) -> tuple[str, str] | None:
        if self.jenkins_user and self.jenkins_token:
            return (self.jenkins_user, self.jenkins_token)
        return None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = env if env is not None else dict(os.environ)
        return cls(
            jenkins_url=_parse_url(env.get("JENKINS_URL", _DEFAULT_URL)),
            jenkins_user=env.get("JENKINS_USER") or None,
            jenkins_token=env.get("JENKINS_TOKEN") or None,
            jenkins_timeout=_parse_float(env, "JENKINS_TIMEOUT", default=10.0, minimum=0.1),
            http_host=env.get("HTTP_HOST", "0.0.0.0"),
            http_port=_parse_int(env, "PORT", default=8000, minimum=1, maximum=65535),
            enable_dns_rebinding_protection=_parse_bool(env, "ENABLE_DNS_REBINDING_PROTECTION", default=False),
        )


_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off", ""})
_DEFAULT_URL = "http://localhost:8080"


def _parse_url(value: str) -> str:
    stripped = value.strip().rstrip("/")
    if not stripped:
        raise ConfigError("JENKINS_URL must not be empty")
    parsed = urlparse(stripped)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(f"JENKINS_URL must be an http(s) URL, got: {value!r}")
    return stripped


def _parse_float(env: dict[str, str], key: str, *, default: float, minimum: float) -> float:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise ConfigError(f"{key} must be a number, got: {raw!r}") from e
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got: {value}")
    return value


def _parse_int(env: dict[str, str], key: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ConfigError(f"{key} must be an integer, got: {raw!r}") from e
    if not (minimum <= value <= maximum):
        raise ConfigError(f"{key} must be between {minimum} and {maximum}, got: {value}")
    return value


def _parse_bool(env: dict[str, str], key: str, *, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return default if normalized == "" else False
    raise ConfigError(f"{key} must be true/false, got: {raw!r}")

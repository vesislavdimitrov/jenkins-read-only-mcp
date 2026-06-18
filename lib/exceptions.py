from __future__ import annotations


class JenkinsError(Exception):
    pass


class JenkinsHTTPError(JenkinsError):
    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} for {url}")
        self.status_code = status_code
        self.url = url


class JenkinsRequestError(JenkinsError):
    pass


class JenkinsValidationError(JenkinsError, ValueError):
    pass

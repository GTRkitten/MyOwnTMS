"""Security-bounded GitLab REST API v4 adapter."""

from __future__ import annotations

import ipaddress
import math
import os
import re
import ssl
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

import httpx


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MAX_TEXT_LENGTH = 1_000_000


class GitLabClientError(Exception):
    """Base class for safe errors exposed outside the HTTP boundary."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.request_id = request_id
        details = [message]
        if status_code is not None:
            details.append(f"HTTP {status_code}")
        if request_id is not None:
            details.append(f"request_id={request_id}")
        super().__init__("; ".join(details))


class GitLabConfigurationError(GitLabClientError):
    """Invalid local client configuration."""


class GitLabInputError(GitLabClientError):
    """Invalid value supplied by application code."""


class GitLabTokenRequiredError(GitLabClientError):
    """No PAT is available in the current process."""


class GitLabAuthenticationError(GitLabClientError):
    """GitLab rejected the current PAT."""


class GitLabPermissionError(GitLabClientError):
    """The authenticated user lacks permission."""


class GitLabNotFoundError(GitLabClientError):
    """The requested GitLab resource is unavailable."""


class GitLabPayloadTooLargeError(GitLabClientError):
    """GitLab rejected an oversized payload."""


class GitLabValidationError(GitLabClientError):
    """GitLab rejected request fields."""


class GitLabRateLimitError(GitLabClientError):
    """GitLab rate limit response with safe retry metadata."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        request_id: str | None,
        retry_after_seconds: int | None,
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            message, status_code=status_code, request_id=request_id
        )


class GitLabServerError(GitLabClientError):
    """GitLab returned a 5xx response."""


class GitLabUnexpectedResponseError(GitLabClientError):
    """GitLab returned an unexpected non-success response."""


class GitLabTimeoutError(GitLabClientError):
    """A bounded GitLab request timed out."""


class GitLabTLSError(GitLabClientError):
    """TLS negotiation or certificate validation failed."""


class GitLabConnectionError(GitLabClientError):
    """GitLab could not be reached."""


class GitLabMalformedResponseError(GitLabClientError):
    """A success response did not contain the expected JSON shape."""


def _normalize_origin(origin: str, allow_test_http: bool) -> str:
    if not isinstance(origin, str) or not origin.strip():
        raise GitLabConfigurationError("GitLab origin is required")
    candidate = origin.strip()
    if "\\" in candidate or any(
        character.isspace() or ord(character) < 32 for character in candidate
    ):
        raise GitLabConfigurationError("GitLab origin is invalid")
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        raise GitLabConfigurationError("GitLab origin is invalid") from None
    try:
        port = parsed.port
    except ValueError:
        raise GitLabConfigurationError("GitLab origin has an invalid port") from None

    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.netloc.endswith(":")
    ):
        raise GitLabConfigurationError(
            "GitLab origin must contain only scheme, host, and optional port"
        )

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    if scheme == "http":
        if not allow_test_http or "PYTEST_VERSION" not in os.environ:
            raise GitLabConfigurationError("GitLab origin must use HTTPS")
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = hostname == "localhost"
        if not is_loopback:
            raise GitLabConfigurationError(
                "Test HTTP origin must use a loopback host"
            )
    elif scheme != "https":
        raise GitLabConfigurationError("GitLab origin must use HTTPS")

    host_for_url = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{scheme}://{host_for_url}{port_suffix}"


@dataclass(frozen=True)
class GitLabClientConfig:
    """Validated connection settings for one GitLab Self-Managed origin."""

    origin: str
    ca_bundle: Path | str | None = field(default=None, repr=False)
    connect_timeout: float = 5.0
    request_timeout: float = 30.0
    allow_test_http: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.allow_test_http, bool):
            raise GitLabConfigurationError("Test HTTP flag must be boolean")
        object.__setattr__(
            self,
            "origin",
            _normalize_origin(self.origin, self.allow_test_http),
        )
        timeouts = (self.connect_timeout, self.request_timeout)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in timeouts
        ):
            raise GitLabConfigurationError("GitLab timeouts must be positive")
        if isinstance(self.ca_bundle, bool):
            raise GitLabConfigurationError("TLS verification cannot be disabled")
        if self.ca_bundle is not None:
            try:
                ca_path = Path(self.ca_bundle)
            except TypeError:
                raise GitLabConfigurationError("CA bundle path is invalid") from None
            if not ca_path.is_absolute() or not ca_path.is_file():
                raise GitLabConfigurationError(
                    "CA bundle must be an existing absolute file"
                )
            object.__setattr__(self, "ca_bundle", ca_path)


class SessionToken:
    """Thread-safe PAT holder that has no persistence integration."""

    __slots__ = ("_lock", "_prompt_lock", "_value")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prompt_lock = threading.Lock()
        self._value: str | None = None

    def set(self, token: str) -> None:
        if not isinstance(token, str):
            raise GitLabInputError("GitLab token must be text")
        value = token.strip()
        if not value or len(value) > 2048 or not value.isascii():
            raise GitLabInputError("GitLab token format is invalid")
        if any(character.isspace() or ord(character) < 33 for character in value):
            raise GitLabInputError("GitLab token format is invalid")
        with self._lock:
            self._value = value

    def get(self) -> str:
        with self._lock:
            if self._value is None:
                raise GitLabTokenRequiredError(
                    "GitLab token is required for this session"
                )
            return self._value

    def resolve(self, prompt: Callable[[], str | None] | None = None) -> str:
        """Return the current PAT or request it once from a UI-owned callback."""

        try:
            return self.get()
        except GitLabTokenRequiredError:
            if prompt is None:
                raise
        with self._prompt_lock:
            try:
                return self.get()
            except GitLabTokenRequiredError:
                supplied = prompt()
                if supplied is None:
                    raise GitLabTokenRequiredError(
                        "GitLab token is required for this session"
                    )
                self.set(supplied)
                return self.get()

    def clear(self) -> None:
        with self._lock:
            self._value = None

    @property
    def is_set(self) -> bool:
        with self._lock:
            return self._value is not None

    def __repr__(self) -> str:
        return f"SessionToken(is_set={self.is_set})"


def _build_ssl_context(config: GitLabClientConfig) -> ssl.SSLContext:
    try:
        if config.ca_bundle is None:
            return ssl.create_default_context()
        return ssl.create_default_context(cafile=str(config.ca_bundle))
    except (OSError, ssl.SSLError):
        raise GitLabConfigurationError("CA bundle could not be loaded") from None


def _safe_request_id(response: httpx.Response) -> str | None:
    value = response.headers.get("X-Request-ID")
    if value and _REQUEST_ID_RE.fullmatch(value):
        return value
    return None


def _retry_after_seconds(value: str | None) -> int | None:
    if not value:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        if len(stripped) > 10:
            return 86400
        return min(int(stripped), 86400)
    try:
        retry_at = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    delay = int((retry_at - datetime.now(timezone.utc)).total_seconds())
    return max(0, min(delay, 86400))


def _contains_ssl_error(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GitLabInputError(f"{field_name} must be a positive integer")
    return value


def _bounded_text(
    value: str,
    field_name: str,
    *,
    allow_empty: bool = False,
    maximum: int = _MAX_TEXT_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise GitLabInputError(f"{field_name} must be text")
    if (not allow_empty and not value) or len(value) > maximum:
        raise GitLabInputError(f"{field_name} length is invalid")
    return value


def _labels_value(labels: Sequence[str]) -> str:
    if isinstance(labels, (str, bytes)):
        raise GitLabInputError("labels must be a sequence of names")
    normalized = []
    for label in labels:
        value = _bounded_text(label, "label", maximum=255)
        if "," in value or any(ord(character) < 32 for character in value):
            raise GitLabInputError("label contains unsupported characters")
        normalized.append(value)
    return ",".join(normalized)


class GitLabApiClient:
    """Synchronous REST adapter intended to run outside the Qt GUI thread."""

    def __init__(
        self,
        config: GitLabClientConfig,
        session_token: SessionToken,
        *,
        token_prompt: Callable[[], str | None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if transport is not None and "PYTEST_VERSION" not in os.environ:
            raise GitLabConfigurationError(
                "Custom HTTP transport is available only to pytest runs"
            )
        self._config = config
        self._session_token = session_token
        self._token_prompt = token_prompt
        timeout = httpx.Timeout(
            config.request_timeout,
            connect=config.connect_timeout,
        )
        self._client = httpx.Client(
            base_url=f"{config.origin}/api/v4/",
            verify=_build_ssl_context(config),
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def __enter__(self) -> "GitLabApiClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"GitLabApiClient(origin={self._config.origin!r})"

    @property
    def origin(self) -> str:
        """Canonical configured origin, safe to use for response validation."""

        return self._config.origin

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        expected_status: int,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        expected_json_type: type = dict,
    ) -> Any:
        token = self._session_token.resolve(self._token_prompt)
        try:
            response = self._client.request(
                method,
                endpoint,
                params=params,
                json=json,
                files=files,
                headers={"PRIVATE-TOKEN": token},
            )
        except httpx.TimeoutException:
            raise GitLabTimeoutError("GitLab request timed out") from None
        except httpx.ConnectError as error:
            if _contains_ssl_error(error):
                raise GitLabTLSError("GitLab TLS verification failed") from None
            raise GitLabConnectionError("GitLab connection failed") from None
        except httpx.TransportError as error:
            if _contains_ssl_error(error):
                raise GitLabTLSError("GitLab TLS verification failed") from None
            raise GitLabConnectionError("GitLab transport failed") from None

        if response.status_code != expected_status:
            self._raise_http_error(response)
        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError):
            raise GitLabMalformedResponseError(
                "GitLab returned malformed JSON",
                status_code=response.status_code,
                request_id=_safe_request_id(response),
            ) from None
        if not isinstance(payload, expected_json_type):
            raise GitLabMalformedResponseError(
                "GitLab returned an unexpected JSON shape",
                status_code=response.status_code,
                request_id=_safe_request_id(response),
            )
        return payload

    @staticmethod
    def _raise_http_error(response: httpx.Response) -> None:
        status = response.status_code
        request_id = _safe_request_id(response)
        if status == 401:
            error = GitLabAuthenticationError(
                "GitLab authentication failed",
                status_code=status,
                request_id=request_id,
            )
        elif status == 403:
            error = GitLabPermissionError(
                "GitLab permission denied",
                status_code=status,
                request_id=request_id,
            )
        elif status == 404:
            error = GitLabNotFoundError(
                "GitLab resource was not found",
                status_code=status,
                request_id=request_id,
            )
        elif status == 413:
            error = GitLabPayloadTooLargeError(
                "GitLab payload is too large",
                status_code=status,
                request_id=request_id,
            )
        elif status == 422:
            error = GitLabValidationError(
                "GitLab rejected request fields",
                status_code=status,
                request_id=request_id,
            )
        elif status == 429:
            error = GitLabRateLimitError(
                "GitLab rate limit reached",
                status_code=status,
                request_id=request_id,
                retry_after_seconds=_retry_after_seconds(
                    response.headers.get("Retry-After")
                ),
            )
        elif 500 <= status <= 599:
            error = GitLabServerError(
                "GitLab server error",
                status_code=status,
                request_id=request_id,
            )
        else:
            error = GitLabUnexpectedResponseError(
                "GitLab returned an unexpected status",
                status_code=status,
                request_id=request_id,
            )
        raise error

    def check_connection(self) -> dict[str, Any]:
        return self._request("GET", "user", expected_status=200)

    def get_project(self, project_id: int) -> dict[str, Any]:
        project_id = _positive_id(project_id, "project_id")
        return self._request(
            "GET", f"projects/{project_id}", expected_status=200
        )

    def list_labels(
        self,
        project_id: int,
        *,
        search: str | None = None,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        project_id = _positive_id(project_id, "project_id")
        page = _positive_id(page, "page")
        params: dict[str, Any] = {"per_page": 100, "page": page}
        if search is not None:
            params["search"] = _bounded_text(search, "search", maximum=255)
        return self._request(
            "GET",
            f"projects/{project_id}/labels",
            expected_status=200,
            params=params,
            expected_json_type=list,
        )

    def create_label(
        self,
        project_id: int,
        *,
        name: str,
        color: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        project_id = _positive_id(project_id, "project_id")
        name = _bounded_text(name, "name", maximum=255)
        if "," in name or any(ord(character) < 32 for character in name):
            raise GitLabInputError("name contains unsupported characters")
        if not isinstance(color, str) or not _HEX_COLOR_RE.fullmatch(color):
            raise GitLabInputError("color must be a six-digit hex value")
        payload: dict[str, Any] = {"name": name, "color": color}
        if description is not None:
            payload["description"] = _bounded_text(
                description,
                "description",
                allow_empty=True,
                maximum=255,
            )
        return self._request(
            "POST",
            f"projects/{project_id}/labels",
            expected_status=201,
            json=payload,
        )

    def get_issue(self, project_id: int, issue_iid: int) -> dict[str, Any]:
        project_id = _positive_id(project_id, "project_id")
        issue_iid = _positive_id(issue_iid, "issue_iid")
        return self._request(
            "GET",
            f"projects/{project_id}/issues/{issue_iid}",
            expected_status=200,
        )

    def list_issues(
        self,
        project_id: int,
        *,
        search: str,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Search one project's Issue descriptions for publish recovery."""

        project_id = _positive_id(project_id, "project_id")
        page = _positive_id(page, "page")
        return self._request(
            "GET",
            f"projects/{project_id}/issues",
            expected_status=200,
            params={
                "search": _bounded_text(search, "search", maximum=255),
                "in": "description",
                "state": "all",
                "per_page": 100,
                "page": page,
            },
            expected_json_type=list,
        )

    def create_issue(
        self,
        project_id: int,
        *,
        title: str,
        description: str,
        labels: Sequence[str],
    ) -> dict[str, Any]:
        project_id = _positive_id(project_id, "project_id")
        payload = {
            "title": _bounded_text(title, "title", maximum=255),
            "description": _bounded_text(
                description, "description", allow_empty=True
            ),
            "labels": _labels_value(labels),
        }
        return self._request(
            "POST",
            f"projects/{project_id}/issues",
            expected_status=201,
            json=payload,
        )

    def update_issue(
        self,
        project_id: int,
        issue_iid: int,
        *,
        title: str | None = None,
        description: str | None = None,
        labels: Sequence[str] | None = None,
        state_event: str | None = None,
    ) -> dict[str, Any]:
        project_id = _positive_id(project_id, "project_id")
        issue_iid = _positive_id(issue_iid, "issue_iid")
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = _bounded_text(title, "title", maximum=255)
        if description is not None:
            payload["description"] = _bounded_text(
                description, "description", allow_empty=True
            )
        if labels is not None:
            payload["labels"] = _labels_value(labels)
        if state_event is not None:
            if state_event not in {"close", "reopen"}:
                raise GitLabInputError("state_event must be close or reopen")
            payload["state_event"] = state_event
        if not payload:
            raise GitLabInputError("Issue update must contain at least one field")
        return self._request(
            "PUT",
            f"projects/{project_id}/issues/{issue_iid}",
            expected_status=200,
            json=payload,
        )

    def upload_file(
        self,
        project_id: int,
        *,
        file_name: str,
        content: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        project_id = _positive_id(project_id, "project_id")
        file_name = _bounded_text(file_name, "file_name", maximum=255)
        if (
            Path(file_name).name != file_name
            or "/" in file_name
            or "\\" in file_name
            or ":" in file_name
            or any(ord(character) < 32 for character in file_name)
            or file_name in {".", ".."}
        ):
            raise GitLabInputError("file_name must not contain a local path")
        if not isinstance(content, bytes):
            raise GitLabInputError("upload content must be bytes")
        if content_type not in {"image/png", "image/jpeg"}:
            raise GitLabInputError("upload content type is not allowed")
        return self._request(
            "POST",
            f"projects/{project_id}/uploads",
            expected_status=201,
            files={"file": (file_name, content, content_type)},
        )

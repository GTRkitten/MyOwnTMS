import json
import ssl

import httpx
import pytest

from src.integrations.gitlab_client import (
    GitLabApiClient,
    GitLabAuthenticationError,
    GitLabClientConfig,
    GitLabConfigurationError,
    GitLabConnectionError,
    GitLabInputError,
    GitLabMalformedResponseError,
    GitLabNotFoundError,
    GitLabPayloadTooLargeError,
    GitLabPermissionError,
    GitLabRateLimitError,
    GitLabServerError,
    GitLabTimeoutError,
    GitLabTLSError,
    GitLabTokenRequiredError,
    GitLabUnexpectedResponseError,
    GitLabValidationError,
    SessionToken,
)


def _client(handler, *, token="test-pat-secret"):
    session_token = SessionToken()
    if token is not None:
        session_token.set(token)
    client = GitLabApiClient(
        GitLabClientConfig("https://gitlab.internal"),
        session_token,
        transport=httpx.MockTransport(handler),
    )
    return client, session_token


def _raise_timeout(request):
    raise httpx.ReadTimeout("secret timeout", request=request)


def _raise_tls_error(request):
    try:
        raise ssl.SSLError("certificate verify failed")
    except ssl.SSLError as error:
        raise httpx.ConnectError(
            "secret certificate path", request=request
        ) from error


def _raise_connection_error(request):
    raise httpx.ConnectError("secret host detail", request=request)


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "gitlab.internal",
        "ftp://gitlab.internal",
        "http://gitlab.internal",
        "https://user:secret@gitlab.internal",
        "https://gitlab.internal/group",
        "https://gitlab.internal?target=other",
        "https://gitlab.internal#fragment",
        "https://gitlab.internal\\@external.example",
        "https://[::1",
    ],
)
def test_rejects_non_origin_or_insecure_urls(origin):
    with pytest.raises(GitLabConfigurationError):
        GitLabClientConfig(origin)


def test_normalizes_https_origin_and_allows_only_test_loopback_http(monkeypatch):
    assert GitLabClientConfig("https://GITLAB.internal:443/").origin == (
        "https://gitlab.internal"
    )
    assert GitLabClientConfig(
        "http://127.0.0.1:8080", allow_test_http=True
    ).origin == "http://127.0.0.1:8080"

    monkeypatch.delenv("PYTEST_VERSION")
    with pytest.raises(GitLabConfigurationError, match="HTTPS"):
        GitLabClientConfig("http://localhost:8080", allow_test_http=True)


def test_custom_transport_is_test_only(monkeypatch):
    config = GitLabClientConfig("https://gitlab.internal")
    monkeypatch.delenv("PYTEST_VERSION")
    with pytest.raises(GitLabConfigurationError, match="only to pytest"):
        GitLabApiClient(
            config,
            SessionToken(),
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={})
            ),
        )


def test_ca_bundle_is_required_to_be_a_file_and_cannot_disable_tls(tmp_path):
    with pytest.raises(GitLabConfigurationError, match="cannot be disabled"):
        GitLabClientConfig("https://gitlab.internal", ca_bundle=False)
    with pytest.raises(GitLabConfigurationError, match="absolute file"):
        GitLabClientConfig("https://gitlab.internal", ca_bundle=tmp_path / "missing.pem")


def test_custom_ca_is_loaded_into_ssl_context(monkeypatch, tmp_path):
    ca_bundle = tmp_path / "internal-ca.pem"
    ca_bundle.write_text("test CA placeholder", encoding="utf-8")
    calls = []

    def create_context(*, cafile=None):
        calls.append(cafile)
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(
        "src.integrations.gitlab_client.ssl.create_default_context",
        create_context,
    )
    client, _ = _client(lambda request: httpx.Response(200, json={}))
    client.close()
    configured_client = GitLabApiClient(
        GitLabClientConfig("https://gitlab.internal", ca_bundle=ca_bundle),
        SessionToken(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    configured_client.close()

    assert calls == [None, str(ca_bundle)]


def test_session_token_is_memory_only_redacted_and_clearable():
    token = SessionToken()
    with pytest.raises(GitLabTokenRequiredError):
        token.get()

    token.set("secret-value")
    assert token.is_set is True
    assert token.get() == "secret-value"
    assert "secret-value" not in repr(token)
    token.clear()
    assert token.is_set is False
    with pytest.raises(GitLabTokenRequiredError):
        token.get()


def test_network_is_not_called_without_session_token():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    client, _ = _client(handler, token=None)
    try:
        with pytest.raises(GitLabTokenRequiredError):
            client.check_connection()
    finally:
        client.close()
    assert calls == 0


def test_first_network_action_prompts_once_and_keeps_pat_only_in_session():
    prompts = 0
    requests = []

    def prompt():
        nonlocal prompts
        prompts += 1
        return "prompted-session-secret"

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": 7})

    token = SessionToken()
    client = GitLabApiClient(
        GitLabClientConfig("https://gitlab.internal"),
        token,
        token_prompt=prompt,
        transport=httpx.MockTransport(handler),
    )
    try:
        client.check_connection()
        client.check_connection()
    finally:
        client.close()

    assert prompts == 1
    assert len(requests) == 2
    assert all(
        request.headers["PRIVATE-TOKEN"] == "prompted-session-secret"
        for request in requests
    )
    assert "prompted-session-secret" not in repr(client)
    token.clear()
    assert token.is_set is False


def test_client_applies_five_and_thirty_second_timeouts():
    observed_timeout = None

    def handler(request):
        nonlocal observed_timeout
        observed_timeout = request.extensions["timeout"]
        return httpx.Response(200, json={"id": 7})

    client, _ = _client(handler)
    try:
        client.check_connection()
    finally:
        client.close()

    assert observed_timeout == {
        "connect": 5.0,
        "read": 30.0,
        "write": 30.0,
        "pool": 30.0,
    }


def test_client_uses_private_token_expected_origin_and_no_redirect_following():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "https://external.example/steal"},
            json={"message": "redirect"},
        )

    client, _ = _client(handler)
    try:
        with pytest.raises(GitLabUnexpectedResponseError):
            client.check_connection()
    finally:
        client.close()

    assert len(requests) == 1
    assert str(requests[0].url) == "https://gitlab.internal/api/v4/user"
    assert requests[0].headers["PRIVATE-TOKEN"] == "test-pat-secret"
    assert "test-pat-secret" not in repr(client)


def test_adapter_endpoints_and_payloads():
    observed = []

    def handler(request):
        body = request.read()
        observed.append((request.method, request.url, body, request.headers))
        path = request.url.path
        if request.method == "GET" and path.endswith("/user"):
            return httpx.Response(200, json={"id": 7, "username": "operator"})
        if request.method == "GET" and path.endswith("/projects/11"):
            return httpx.Response(200, json={"id": 11, "visibility": "private"})
        if request.method == "GET" and path.endswith("/labels"):
            return httpx.Response(200, json=[{"name": "myowntms"}])
        if request.method == "POST" and path.endswith("/labels"):
            return httpx.Response(201, json={"name": "myowntms"})
        if request.method == "GET" and path.endswith("/issues/3"):
            return httpx.Response(200, json={"iid": 3})
        if request.method == "GET" and path.endswith("/issues"):
            return httpx.Response(200, json=[{"iid": 3}])
        if request.method == "POST" and path.endswith("/issues"):
            return httpx.Response(201, json={"iid": 3})
        if request.method == "PUT" and path.endswith("/issues/3"):
            return httpx.Response(200, json={"iid": 3, "state": "closed"})
        if request.method == "POST" and path.endswith("/uploads"):
            return httpx.Response(201, json={"id": 5, "markdown": "![a](url)"})
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    client, _ = _client(handler)
    try:
        assert client.check_connection()["id"] == 7
        assert client.get_project(11)["visibility"] == "private"
        assert client.list_labels(11, search="myowntms")[0]["name"] == "myowntms"
        assert client.create_label(
            11, name="myowntms", color="#123ABC", description="managed"
        )["name"] == "myowntms"
        assert client.get_issue(11, 3)["iid"] == 3
        assert client.list_issues(11, search="sync-marker")[0]["iid"] == 3
        assert client.create_issue(
            11,
            title="[BUG-1] Example",
            description="managed block",
            labels=["myowntms", "myowntms-status-new"],
        )["iid"] == 3
        assert client.update_issue(11, 3, state_event="close")["state"] == "closed"
        assert client.upload_file(
            11,
            file_name="screen.png",
            content=b"png bytes",
            content_type="image/png",
        )["id"] == 5
    finally:
        client.close()

    label_request = observed[2]
    assert label_request[1].params["search"] == "myowntms"
    assert label_request[1].params["per_page"] == "100"
    assert label_request[1].params["page"] == "1"
    issue_search_request = observed[5]
    assert issue_search_request[1].params["search"] == "sync-marker"
    assert issue_search_request[1].params["in"] == "description"
    assert issue_search_request[1].params["state"] == "all"
    create_issue_request = observed[6]
    assert json.loads(create_issue_request[2])["labels"] == (
        "myowntms,myowntms-status-new"
    )
    upload_request = observed[8]
    assert b'screen.png' in upload_request[2]
    assert b'/screen.png' not in upload_request[2]


@pytest.mark.parametrize(
    ("status", "expected_error"),
    [
        (401, GitLabAuthenticationError),
        (403, GitLabPermissionError),
        (404, GitLabNotFoundError),
        (413, GitLabPayloadTooLargeError),
        (422, GitLabValidationError),
        (500, GitLabServerError),
        (503, GitLabServerError),
    ],
)
def test_http_failures_are_typed_and_redacted(status, expected_error):
    secret_body = "private description and token test-pat-secret"

    def handler(request):
        return httpx.Response(
            status,
            headers={"X-Request-ID": "safe-request-123"},
            text=secret_body,
        )

    client, _ = _client(handler)
    try:
        with pytest.raises(expected_error) as raised:
            client.get_project(11)
    finally:
        client.close()

    error_text = str(raised.value)
    assert f"HTTP {status}" in error_text
    assert "safe-request-123" in error_text
    assert secret_body not in error_text
    assert "test-pat-secret" not in repr(raised.value)


def test_rate_limit_exposes_bounded_retry_after_without_retrying():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "120"}, json={})

    client, _ = _client(handler)
    try:
        with pytest.raises(GitLabRateLimitError) as raised:
            client.create_label(11, name="myowntms", color="#123456")
    finally:
        client.close()

    assert raised.value.retry_after_seconds == 120
    assert calls == 1


def test_untrusted_request_id_is_not_exposed():
    def handler(request):
        return httpx.Response(
            403,
            headers={"X-Request-ID": "private description test-pat-secret"},
            text="private body",
        )

    client, _ = _client(handler)
    try:
        with pytest.raises(GitLabPermissionError) as raised:
            client.get_project(11)
    finally:
        client.close()

    assert raised.value.request_id is None
    assert "private" not in str(raised.value)
    assert "test-pat-secret" not in str(raised.value)


def test_write_server_error_is_not_retried():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="sensitive response body")

    client, _ = _client(handler)
    try:
        with pytest.raises(GitLabServerError):
            client.create_issue(11, title="Bug", description="secret", labels=[])
    finally:
        client.close()

    assert calls == 1


def test_timeout_tls_connection_and_malformed_json_are_typed():
    cases = [
        (_raise_timeout, GitLabTimeoutError),
        (_raise_tls_error, GitLabTLSError),
        (_raise_connection_error, GitLabConnectionError),
        (
            lambda request: httpx.Response(200, text="private invalid JSON"),
            GitLabMalformedResponseError,
        ),
    ]

    for handler, expected_error in cases:
        client, _ = _client(handler)
        try:
            with pytest.raises(expected_error) as raised:
                client.check_connection()
        finally:
            client.close()
        assert "secret" not in str(raised.value)
        assert "private invalid JSON" not in str(raised.value)


@pytest.mark.parametrize(
    "operation",
    [
        lambda client: client.get_project(0),
        lambda client: client.get_issue(1, -1),
        lambda client: client.create_label(1, name="x", color="red"),
        lambda client: client.update_issue(1, 1),
        lambda client: client.upload_file(
            1,
            file_name="/tmp/private.png",
            content=b"data",
            content_type="image/png",
        ),
        lambda client: client.upload_file(
            1,
            file_name="C:\\private\\screen.png",
            content=b"data",
            content_type="image/png",
        ),
        lambda client: client.upload_file(
            1,
            file_name="private.txt",
            content=b"data",
            content_type="text/plain",
        ),
    ],
)
def test_invalid_application_inputs_are_rejected_before_network(operation):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    client, _ = _client(handler)
    try:
        with pytest.raises(GitLabInputError):
            operation(client)
    finally:
        client.close()
    assert calls == 0

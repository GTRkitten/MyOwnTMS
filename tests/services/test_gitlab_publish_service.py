import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Attachment,
    Base,
    BugReport,
    GitLabAttachmentBinding,
    GitLabBinding,
    GitLabProject,
)
from src.integrations.gitlab_client import (
    GitLabApiClient,
    GitLabClientConfig,
    GitLabServerError,
    SessionToken,
)
from src.services.gitlab_publish_service import (
    GitLabPublishResumableError,
    GitLabPublishService,
    PublishPreviewStaleError,
    PublishValidationError,
)
from src.services.gitlab_project_service import MANAGED_LABELS


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()


def _client(
    handler,
    *,
    origin="https://gitlab.internal",
    managed_label_names=None,
):
    token = SessionToken()
    token.set("session-only-test-token")
    label_names = (
        tuple(label.name for label in MANAGED_LABELS)
        if managed_label_names is None
        else tuple(managed_label_names)
    )

    def wrapped_handler(request):
        if request.method == "GET" and request.url.path.endswith("/labels"):
            return httpx.Response(
                200, json=[{"name": name} for name in label_names]
            )
        return handler(request)

    return GitLabApiClient(
        GitLabClientConfig(origin),
        token,
        transport=httpx.MockTransport(wrapped_handler),
    )


def _seed(session, tmp_path, *, attachments=0, status="Новый"):
    project = GitLabProject(
        display_name="Customer A",
        gitlab_project_id=11,
        path_with_namespace="customers/project-a",
        web_url="https://gitlab.internal/customers/project-a",
        visibility="private",
        is_active=True,
        labels_ready_at=datetime.now(),
    )
    bug = BugReport(
        id="BUG-251126-001",
        title="Checkout fails",
        description="Customer report",
        reproduction_steps="1. Open checkout",
        expected_result="Order is created",
        actual_result="Error is shown",
        environment="Windows 11",
        priority="Высокий",
        severity="Мажорный",
        status=status,
        source_channel="email",
        external_reference="REQ-42",
        gitlab_project=project,
    )
    session.add(bug)
    session.flush()
    for index in range(attachments):
        path = tmp_path / f"source-{index}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"same-image")
        bug.attachments.append(
            Attachment(
                artifact_id=bug.id,
                artifact_type="bug_report",
                file_path=str(path),
                file_name="same-name.png",
                file_type="image/png",
                bug_report_id=bug.id,
            )
        )
    session.commit()
    return bug, project


def _issue_payload(description, labels, *, updated="2026-11-25T12:00:00Z"):
    return {
        "id": 501,
        "iid": 7,
        "web_url": "https://gitlab.internal/customers/project-a/-/issues/7",
        "title": "[BUG-251126-001] Checkout fails",
        "description": description,
        "labels": list(labels),
        "state": "opened",
        "updated_at": updated,
    }


def _project_payload(**overrides):
    payload = {
        "id": 11,
        "path_with_namespace": "customers/project-a",
        "web_url": "https://gitlab.internal/customers/project-a",
        "visibility": "private",
        "archived": False,
    }
    payload.update(overrides)
    return payload


def test_preview_is_read_only_lists_all_files_and_validates_publish_fields(
    database, tmp_path
):
    session = database()
    bug, _ = _seed(session, tmp_path, attachments=1)
    text_path = tmp_path / "notes.txt"
    text_path.write_text("not transmitted", encoding="utf-8")
    bug.attachments.append(
        Attachment(
            artifact_id=bug.id,
            artifact_type="bug_report",
            file_path=str(text_path),
            file_name="notes.txt",
            file_type="text/plain",
            bug_report_id=bug.id,
        )
    )
    session.commit()
    requests = []

    with _client(lambda request: requests.append(request)) as client:
        preview = GitLabPublishService(client).preview(session, bug.id)

    assert requests == []
    assert preview.project_path_with_namespace == "customers/project-a"
    assert preview.issue_title == "[BUG-251126-001] Checkout fails"
    assert len(preview.fields) == 11
    assert [item.will_upload for item in preview.files] == [True, False]
    assert preview.files[1].skip_reason == "unsupported_type"
    assert preview.files[0].upload_name.startswith("attachment-")

    bug.status = "Черновик"
    session.commit()
    with _client(lambda request: httpx.Response(500)) as client:
        with pytest.raises(PublishValidationError, match="Draft"):
            GitLabPublishService(client).preview(session, bug.id)
    session.close()


def test_preview_rejects_project_from_different_origin_without_network(
    database, tmp_path
):
    session = database()
    bug, project = _seed(session, tmp_path)
    project.web_url = "https://gitlab-a.internal/customers/project-a"
    session.commit()
    requests = []

    with _client(
        lambda request: requests.append(request),
        origin="https://gitlab-b.internal",
    ) as client:
        with pytest.raises(PublishValidationError, match="different configured origin"):
            GitLabPublishService(client).preview(session, bug.id)

    assert requests == []
    assert session.query(GitLabBinding).count() == 0
    session.close()


@pytest.mark.parametrize(
    "remote_project",
    [
        _project_payload(id=12),
        _project_payload(
            path_with_namespace="customers/renamed",
            web_url="https://gitlab.internal/customers/renamed",
        ),
        _project_payload(visibility="internal"),
        _project_payload(archived=True),
    ],
)
def test_publish_revalidates_project_before_local_or_remote_mutation(
    database, tmp_path, remote_project
):
    session = database()
    bug, _ = _seed(session, tmp_path)
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        assert request.method == "GET"
        assert request.url.path.endswith("/projects/11")
        return httpx.Response(200, json=remote_project)

    with _client(handler) as client:
        service = GitLabPublishService(client)
        preview = service.preview(session, bug.id)
        with pytest.raises(PublishValidationError, match="safely revalidated"):
            service.publish(session, bug.id, preview)

    assert requests == [("GET", "/api/v4/projects/11")]
    assert session.query(GitLabBinding).count() == 0
    session.close()


def test_publish_revalidation_network_failure_leaves_no_binding(database, tmp_path):
    session = database()
    bug, _ = _seed(session, tmp_path)
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(500, json={})

    with _client(handler) as client:
        service = GitLabPublishService(client)
        preview = service.preview(session, bug.id)
        with pytest.raises(GitLabServerError):
            service.publish(session, bug.id, preview)

    assert requests == [("GET", "/api/v4/projects/11")]
    assert session.query(GitLabBinding).count() == 0
    session.close()


def test_publish_fails_closed_when_prepared_labels_were_removed(
    database, tmp_path
):
    session = database()
    bug, project = _seed(session, tmp_path)
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload())
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    remaining = tuple(label.name for label in MANAGED_LABELS[:-1])
    with _client(handler, managed_label_names=remaining) as client:
        service = GitLabPublishService(client)
        preview = service.preview(session, bug.id)
        with pytest.raises(PublishValidationError, match="prepared again"):
            service.publish(session, bug.id, preview)

    session.refresh(project)
    assert project.labels_ready_at is None
    assert session.query(GitLabBinding).count() == 0
    assert requests == [("GET", "/api/v4/projects/11")]
    session.close()


def test_uncertain_create_recovers_exact_marker_without_duplicate(database, tmp_path):
    session = database()
    bug, _ = _seed(session, tmp_path)
    issue = None
    create_calls = 0
    search_calls = 0

    def handler(request):
        nonlocal issue, create_calls, search_calls
        if request.method == "GET" and request.url.path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload())
        if request.method == "POST" and request.url.path.endswith("/issues"):
            create_calls += 1
            body = json.loads(request.read())
            issue = _issue_payload(body["description"], body["labels"].split(","))
            raise httpx.ReadTimeout("response lost", request=request)
        if request.method == "GET" and request.url.path.endswith("/issues"):
            search_calls += 1
            assert request.url.params["in"] == "description"
            return httpx.Response(200, json=[issue])
        if request.method == "GET" and request.url.path.endswith("/issues/7"):
            return httpx.Response(200, json=issue)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        service = GitLabPublishService(client)
        preview = service.preview(session, bug.id)
        result = service.publish(session, bug.id, preview)

    assert result.issue_iid == 7
    assert create_calls == 1
    assert search_calls == 1
    assert bug.gitlab_binding.sync_state == "synced"
    session.close()


def test_timeout_before_create_is_retried_only_after_marker_search(database, tmp_path):
    session = database()
    bug, _ = _seed(session, tmp_path)
    issue = None
    post_attempts = 0
    search_calls = 0

    def handler(request):
        nonlocal issue, post_attempts, search_calls
        path = request.url.path
        if request.method == "GET" and path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload())
        if request.method == "GET" and path.endswith("/issues"):
            search_calls += 1
            return httpx.Response(200, json=[] if issue is None else [issue])
        if request.method == "POST" and path.endswith("/issues"):
            post_attempts += 1
            if post_attempts == 1:
                raise httpx.WriteTimeout("request not delivered", request=request)
            body = json.loads(request.read())
            issue = _issue_payload(body["description"], body["labels"].split(","))
            return httpx.Response(201, json=issue)
        if request.method == "GET" and path.endswith("/issues/7"):
            return httpx.Response(200, json=issue)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        service = GitLabPublishService(client)
        preview = service.preview(session, bug.id)
        with pytest.raises(GitLabPublishResumableError) as raised:
            service.publish(session, bug.id, preview)
        assert raised.value.issue_created is False

        retry_preview = service.preview(session, bug.id)
        result = service.publish(session, bug.id, retry_preview)

    assert result.issue_iid == 7
    assert post_attempts == 2
    assert search_calls == 2
    assert session.query(GitLabBinding).one().sync_state == "synced"
    session.close()


def test_partial_upload_resumes_after_new_session_without_reuploading_completed_file(
    database, tmp_path
):
    first_session = database()
    bug, _ = _seed(first_session, tmp_path, attachments=2)
    issue = None
    create_calls = 0
    upload_calls = {}
    fail_second_once = True

    def handler(request):
        nonlocal issue, create_calls, fail_second_once
        path = request.url.path
        if request.method == "GET" and path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload())
        if request.method == "POST" and path.endswith("/issues"):
            create_calls += 1
            body = json.loads(request.read())
            issue = _issue_payload(body["description"], body["labels"].split(","))
            return httpx.Response(201, json=issue)
        if request.method == "GET" and path.endswith("/issues/7"):
            return httpx.Response(200, json=issue)
        if request.method == "POST" and path.endswith("/uploads"):
            body = request.read()
            upload_name = next(
                name
                for name in (b"attachment-1-same-name.png", b"attachment-2-same-name.png")
                if name in body
            ).decode()
            upload_calls[upload_name] = upload_calls.get(upload_name, 0) + 1
            if upload_name.startswith("attachment-2-") and fail_second_once:
                fail_second_once = False
                return httpx.Response(
                    429, headers={"Retry-After": "1"}, json={}
                )
            attachment_id = upload_name.split("-", 2)[1]
            return httpx.Response(
                201,
                json={
                    "id": int(attachment_id),
                    "full_path": f"/uploads/{attachment_id}/{upload_name}",
                    "markdown": f"![{upload_name}](/uploads/{attachment_id}/{upload_name})",
                },
            )
        if request.method == "PUT" and path.endswith("/issues/7"):
            body = json.loads(request.read())
            issue.update(body)
            if isinstance(issue.get("labels"), str):
                issue["labels"] = issue["labels"].split(",")
            issue["updated_at"] = "2026-11-25T12:01:00Z"
            return httpx.Response(200, json=issue)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        service = GitLabPublishService(client)
        preview = service.preview(first_session, bug.id)
        with pytest.raises(GitLabPublishResumableError) as raised:
            service.publish(first_session, bug.id, preview)

    assert raised.value.issue_created is True
    assert first_session.query(GitLabAttachmentBinding).count() == 1
    assert (
        first_session.query(GitLabAttachmentBinding)
        .filter(GitLabAttachmentBinding.uploaded_at.is_not(None))
        .count()
        == 1
    )
    bug_id = bug.id
    binding_id = bug.gitlab_binding.id
    first_session.close()

    restarted_session = database()
    with _client(handler) as client:
        restarted_service = GitLabPublishService(client)
        restarted_preview = restarted_service.preview(restarted_session, bug_id)
        result = restarted_service.publish(
            restarted_session, bug_id, restarted_preview
        )

    assert create_calls == 1
    assert upload_calls == {
        "attachment-1-same-name.png": 1,
        "attachment-2-same-name.png": 2,
    }
    assert result.uploaded_attachment_ids == (2,)
    assert result.reused_attachment_ids == (1,)
    assert restarted_session.get(GitLabBinding, binding_id).sync_state == "synced"
    restarted_session.close()


def test_lost_upload_response_blocks_retry_without_duplicate(database, tmp_path):
    session = database()
    bug, _ = _seed(session, tmp_path, attachments=1)
    issue = None
    upload_calls = 0

    def handler(request):
        nonlocal issue, upload_calls
        path = request.url.path
        if request.method == "GET" and path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload())
        if request.method == "POST" and path.endswith("/issues"):
            body = json.loads(request.read())
            issue = _issue_payload(body["description"], body["labels"].split(","))
            return httpx.Response(201, json=issue)
        if request.method == "GET" and path.endswith("/issues/7"):
            return httpx.Response(200, json=issue)
        if request.method == "POST" and path.endswith("/uploads"):
            upload_calls += 1
            request.read()  # The server accepted the complete multipart body.
            raise httpx.ReadTimeout("upload response lost", request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        service = GitLabPublishService(client)
        preview = service.preview(session, bug.id)
        with pytest.raises(GitLabPublishResumableError) as first_error:
            service.publish(session, bug.id, preview)

        bug_id = bug.id
        session.close()
        restarted_session = database()
        retry_preview = service.preview(restarted_session, bug_id)
        with pytest.raises(GitLabPublishResumableError) as retry_error:
            service.publish(restarted_session, bug_id, retry_preview)

    assert first_error.value.retry_safe is False
    assert retry_error.value.retry_safe is False
    assert upload_calls == 1
    pending = restarted_session.query(GitLabAttachmentBinding).one()
    assert pending.remote_upload_id is None
    assert pending.uploaded_at is None
    restarted_bug = restarted_session.get(BugReport, bug_id)
    assert (
        restarted_bug.gitlab_binding.last_error_type
        == "PublishUploadOutcomeUncertainError"
    )
    restarted_session.close()


def test_final_update_preserves_outside_text_and_unmanaged_labels(database, tmp_path):
    session = database()
    bug, _ = _seed(session, tmp_path)
    issue = None
    final_body = None

    def handler(request):
        nonlocal issue, final_body
        path = request.url.path
        if request.method == "GET" and path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload())
        if request.method == "POST" and path.endswith("/issues"):
            body = json.loads(request.read())
            issue = _issue_payload(body["description"], body["labels"].split(","))
            return httpx.Response(201, json=issue)
        if request.method == "GET" and path.endswith("/issues/7"):
            issue["description"] = f"Team prefix\n\n{issue['description']}\n\nTeam suffix"
            issue["description"] = issue["description"].replace(
                "Customer report", "Temporary remote edit"
            )
            issue["labels"] = [*issue["labels"], "customer-workflow"]
            return httpx.Response(200, json=issue)
        if request.method == "PUT" and path.endswith("/issues/7"):
            final_body = json.loads(request.read())
            issue.update(final_body)
            if isinstance(issue["labels"], str):
                issue["labels"] = issue["labels"].split(",")
            issue["updated_at"] = "2026-11-25T12:02:00Z"
            return httpx.Response(200, json=issue)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        service = GitLabPublishService(client)
        preview = service.preview(session, bug.id)
        service.publish(session, bug.id, preview)

    assert final_body["description"].startswith("Team prefix\n\n")
    assert final_body["description"].endswith("\n\nTeam suffix")
    assert "customer-workflow" in issue["labels"]
    session.close()


def test_changed_or_missing_image_invalidates_confirmed_preview(database, tmp_path):
    session = database()
    bug, _ = _seed(session, tmp_path, attachments=1)
    path = Path(bug.attachments[0].file_path)

    with _client(lambda request: httpx.Response(500)) as client:
        service = GitLabPublishService(client)
        preview = service.preview(session, bug.id)
        path.write_bytes(b"\x89PNG\r\n\x1a\nchanged")
        with pytest.raises(PublishPreviewStaleError):
            service.publish(session, bug.id, preview)

        preview = service.preview(session, bug.id)
        path.unlink()
        with pytest.raises(PublishValidationError, match="missing"):
            service.publish(session, bug.id, preview)
    session.close()

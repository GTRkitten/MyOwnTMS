import json
from datetime import datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, BugReport, GitLabBinding, GitLabProject
from src.integrations.gitlab_client import (
    GitLabApiClient,
    GitLabClientConfig,
    GitLabServerError,
    SessionToken,
)
from src.services.artifact_service import BugReportService, PublishedBugDeleteError
from src.services.gitlab_issue_codec import (
    ManagedIssueContent,
    managed_labels_for,
    serialize_managed_block,
)
from src.services.gitlab_sync_service import (
    GitLabSyncService,
    IssueSnapshot,
    SyncBaseSnapshotError,
    SyncConflictResolutionError,
    SyncPreviewStaleError,
    SyncRemoteStateError,
    SyncVerificationError,
    three_way_merge,
)


SYNC_UID = "00000000-0000-4000-8000-000000000004"


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()


def _snapshot(**changes):
    values = {
        "title": "Checkout fails",
        "description": "Customer report",
        "reproduction_steps": "1. Open checkout",
        "expected_result": "Order is created",
        "actual_result": "Error is shown",
        "environment": "Windows 11",
        "source_channel": "email",
        "external_reference": "REQ-42",
        "status": "Новый",
        "priority": "Высокий",
        "severity": "Мажорный",
    }
    values.update(changes)
    return IssueSnapshot(**values)


def _base_json(snapshot):
    return json.dumps(
        {**snapshot.as_dict(), "attachments": []},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _remote_payload(snapshot, *, outside=True, labels=(), state=None, updated="2026-11-25T12:00:00Z"):
    block = serialize_managed_block(
        ManagedIssueContent(
            sync_uid=SYNC_UID,
            description=snapshot.description,
            reproduction_steps=snapshot.reproduction_steps,
            expected_result=snapshot.expected_result,
            actual_result=snapshot.actual_result,
            environment=snapshot.environment,
            source_channel=snapshot.source_channel or None,
            external_reference=snapshot.external_reference or None,
            attachment_markdown=("![screen](/uploads/1/screen.png)",),
        )
    )
    return {
        "id": 501,
        "iid": 7,
        "web_url": "https://gitlab.internal/customers/project-a/-/issues/7",
        "title": f"[BUG-251126-001] {snapshot.title}",
        "description": f"Team prefix\n\n{block}\n\nTeam suffix" if outside else block,
        "labels": [*labels, *managed_labels_for(snapshot.status, snapshot.priority, snapshot.severity)],
        "state": state or ("closed" if snapshot.status == "Закрыт" else "opened"),
        "updated_at": updated,
    }


def _seed(session, *, base=None, local=None):
    base = base or _snapshot()
    local = local or base
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
        **local.as_dict(),
        gitlab_project=project,
    )
    binding = GitLabBinding(
        bug_report=bug,
        project=project,
        sync_uid=SYNC_UID,
        issue_id=501,
        issue_iid=7,
        issue_web_url="https://gitlab.internal/customers/project-a/-/issues/7",
        remote_updated_at=datetime(2026, 11, 25, 12, 0),
        base_snapshot=_base_json(base),
        sync_state="synced",
    )
    session.add(binding)
    session.commit()
    return bug, binding


def _client(handler):
    token = SessionToken()
    token.set("session-only-test-token")
    return GitLabApiClient(
        GitLabClientConfig("https://gitlab.internal"),
        token,
        transport=httpx.MockTransport(handler),
    )


def _stateful_handler(issue, *, mutate_control=None):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            if mutate_control is not None and calls.count("GET") == 3:
                mutate_control(issue)
            return httpx.Response(200, json=issue)
        if request.method == "PUT":
            body = json.loads(request.read())
            issue.update({key: value for key, value in body.items() if key != "state_event"})
            if isinstance(issue.get("labels"), str):
                issue["labels"] = issue["labels"].split(",")
            if body.get("state_event") == "close":
                issue["state"] = "closed"
            elif body.get("state_event") == "reopen":
                issue["state"] = "opened"
            issue["updated_at"] = "2026-11-25T12:01:00Z"
            return httpx.Response(200, json=issue)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return handler, calls


@pytest.mark.parametrize(
    ("local", "remote", "merged", "conflicts"),
    [
        (_snapshot(title="Local"), _snapshot(), _snapshot(title="Local"), ()),
        (_snapshot(), _snapshot(description="Remote"), _snapshot(description="Remote"), ()),
        (
            _snapshot(title="Local"),
            _snapshot(description="Remote"),
            _snapshot(title="Local", description="Remote"),
            (),
        ),
        (_snapshot(title="Local"), _snapshot(title="Remote"), _snapshot(), ("title",)),
    ],
)
def test_three_way_merge_matrix(local, remote, merged, conflicts):
    result = three_way_merge(_snapshot(), local, remote)

    assert result.merged == merged
    assert tuple(conflict.field for conflict in result.conflicts) == conflicts


def test_remote_only_change_is_pulled_and_normalized_base_is_saved(database):
    session = database()
    bug, binding = _seed(session)
    remote = _snapshot(description="Remote edit")
    issue = _remote_payload(remote)
    handler, calls = _stateful_handler(issue)

    with _client(handler) as client:
        service = GitLabSyncService(client)
        preview = service.preview(session, bug.id)
        result = service.confirm(session, preview)

    assert preview.action == "pull"
    assert result.pulled is True
    assert result.pushed is False
    assert bug.description == "Remote edit"
    assert json.loads(binding.base_snapshot)["description"] == "Remote edit"
    assert calls == ["GET", "GET"]
    session.close()


def test_unchanged_issue_remains_synced_without_put(database):
    session = database()
    bug, binding = _seed(session)
    issue = _remote_payload(_snapshot())
    handler, calls = _stateful_handler(issue)

    with _client(handler) as client:
        service = GitLabSyncService(client)
        preview = service.preview(session, bug.id)
        result = service.confirm(session, preview)

    assert preview.action == "none"
    assert result.pushed is False
    assert result.pulled is False
    assert calls == ["GET", "GET"]
    assert binding.sync_state == "synced"
    session.close()


def test_local_only_push_preserves_outside_text_and_unmanaged_labels(database):
    session = database()
    local = _snapshot(title="Local title")
    bug, binding = _seed(session, local=local)
    issue = _remote_payload(_snapshot(), labels=("customer-workflow",))
    handler, calls = _stateful_handler(issue)

    with _client(handler) as client:
        service = GitLabSyncService(client)
        preview = service.preview(session, bug.id)
        result = service.confirm(session, preview)

    assert preview.action == "push"
    assert result.pushed is True
    assert issue["title"] == "[BUG-251126-001] Local title"
    assert issue["description"].startswith("Team prefix\n\n")
    assert issue["description"].endswith("\n\nTeam suffix")
    assert "customer-workflow" in issue["labels"]
    assert calls == ["GET", "GET", "PUT", "GET"]
    assert binding.sync_state == "synced"
    session.close()


def test_non_overlapping_changes_are_combined_after_preview(database):
    session = database()
    bug, _ = _seed(session, local=_snapshot(title="Local title"))
    issue = _remote_payload(_snapshot(description="Remote description"))
    handler, _ = _stateful_handler(issue)

    with _client(handler) as client:
        service = GitLabSyncService(client)
        preview = service.preview(session, bug.id)
        result = service.confirm(session, preview)

    assert preview.action == "merge"
    assert preview.merged == _snapshot(title="Local title", description="Remote description")
    assert result.pushed and result.pulled
    assert bug.description == "Remote description"
    session.close()


def test_same_field_conflict_requires_explicit_choice(database):
    session = database()
    bug, binding = _seed(session, local=_snapshot(title="Local title"))
    issue = _remote_payload(_snapshot(title="Remote title"))
    handler, _ = _stateful_handler(issue)

    with _client(handler) as client:
        service = GitLabSyncService(client)
        preview = service.preview(session, bug.id)
        with pytest.raises(SyncConflictResolutionError):
            service.confirm(session, preview)
        result = service.confirm(session, preview, {"title": "remote"})

    assert preview.sync_state == "conflict"
    assert result.pushed is False
    assert bug.title == "Remote title"
    assert binding.sync_state == "synced"
    session.close()


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "unknown-version"])
def test_corrupt_or_unknown_managed_block_fails_closed(database, corruption):
    session = database()
    bug, binding = _seed(session, local=_snapshot(title="Local title"))
    issue = _remote_payload(_snapshot())
    if corruption == "missing":
        issue["description"] = "No managed block"
    elif corruption == "duplicate":
        issue["description"] += "\n" + issue["description"]
    else:
        issue["description"] = issue["description"].replace("version=1", "version=2")
    writes = []

    def handler(request):
        if request.method != "GET":
            writes.append(request.method)
        return httpx.Response(200, json=issue)

    with _client(handler) as client:
        with pytest.raises(SyncRemoteStateError):
            GitLabSyncService(client).preview(session, bug.id)

    assert writes == []
    assert binding.sync_state == "conflict"
    session.close()


def test_missing_or_corrupt_base_snapshot_fails_before_network(database):
    session = database()
    bug, binding = _seed(session)
    binding.base_snapshot = None
    session.commit()
    requests = []

    with _client(lambda request: requests.append(request)) as client:
        with pytest.raises(SyncBaseSnapshotError):
            GitLabSyncService(client).preview(session, bug.id)

    assert requests == []
    session.close()


def test_inconsistent_remote_state_and_status_label_is_conflict(database):
    session = database()
    bug, binding = _seed(session)
    issue = _remote_payload(_snapshot(), state="closed")

    with _client(lambda request: httpx.Response(200, json=issue)) as client:
        with pytest.raises(SyncRemoteStateError, match="inconsistent"):
            GitLabSyncService(client).preview(session, bug.id)

    assert binding.sync_state == "conflict"
    session.close()


def test_duplicate_managed_label_is_conflict(database):
    session = database()
    bug, binding = _seed(session)
    issue = _remote_payload(_snapshot())
    issue["labels"].append("MYOWNTMS-STATUS-NEW")

    with _client(lambda request: httpx.Response(200, json=issue)) as client:
        with pytest.raises(SyncRemoteStateError, match="managed status"):
            GitLabSyncService(client).preview(session, bug.id)

    assert binding.sync_state == "conflict"
    session.close()


def test_network_failure_sets_safe_error_state(database):
    session = database()
    bug, binding = _seed(session)

    with _client(lambda request: httpx.Response(500, json={})) as client:
        with pytest.raises(GitLabServerError):
            GitLabSyncService(client).preview(session, bug.id)

    assert binding.sync_state == "error"
    assert binding.last_error_type == "GitLabServerError"
    assert binding.last_error_http_status == 500
    session.close()


@pytest.mark.parametrize(
    ("base_status", "local_status", "remote_status", "expected_status"),
    [
        ("Новый", "Новый", "Закрыт", "Закрыт"),
        ("Закрыт", "Новый", "Закрыт", "Новый"),
        ("Новый", "Закрыт", "Новый", "Закрыт"),
    ],
)
def test_close_and_reopen_mapping_in_both_directions(
    database, base_status, local_status, remote_status, expected_status
):
    session = database()
    base = _snapshot(status=base_status)
    local = _snapshot(status=local_status)
    bug, _ = _seed(session, base=base, local=local)
    issue = _remote_payload(_snapshot(status=remote_status))
    handler, _ = _stateful_handler(issue)

    with _client(handler) as client:
        service = GitLabSyncService(client)
        preview = service.preview(session, bug.id)
        result = service.confirm(session, preview)

    assert result.snapshot.status == expected_status
    assert bug.status == expected_status
    assert issue["state"] == ("closed" if expected_status == "Закрыт" else "opened")
    session.close()


def test_missing_issue_sets_remote_missing_without_republish(database):
    session = database()
    bug, binding = _seed(session)
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(404, json={})

    with _client(handler) as client:
        with pytest.raises(SyncRemoteStateError, match="republish"):
            GitLabSyncService(client).preview(session, bug.id)

    assert methods == ["GET"]
    assert binding.sync_state == "remote_missing"
    session.close()


def test_remote_change_after_preview_blocks_put(database):
    session = database()
    bug, binding = _seed(session, local=_snapshot(title="Local title"))
    issue = _remote_payload(_snapshot())
    get_count = 0

    def handler(request):
        nonlocal get_count
        assert request.method == "GET"
        get_count += 1
        if get_count == 2:
            issue["updated_at"] = "2026-11-25T12:00:01Z"
        return httpx.Response(200, json=issue)

    with _client(handler) as client:
        service = GitLabSyncService(client)
        preview = service.preview(session, bug.id)
        with pytest.raises(SyncPreviewStaleError):
            service.confirm(session, preview)

    assert binding.sync_state == "conflict"
    session.close()


def test_control_read_detects_change_after_put(database):
    session = database()
    bug, binding = _seed(session, local=_snapshot(title="Local title"))
    issue = _remote_payload(_snapshot())

    def mutate_control(payload):
        payload["title"] = "[BUG-251126-001] Concurrent title"
        payload["updated_at"] = "2026-11-25T12:02:00Z"

    handler, calls = _stateful_handler(issue, mutate_control=mutate_control)
    with _client(handler) as client:
        service = GitLabSyncService(client)
        preview = service.preview(session, bug.id)
        with pytest.raises(SyncVerificationError):
            service.confirm(session, preview)

    assert calls == ["GET", "GET", "PUT", "GET"]
    assert binding.sync_state == "conflict"
    session.close()


def test_gitlab_bound_bug_cannot_be_hard_deleted(database):
    session = database()
    bug, _ = _seed(session)

    with pytest.raises(PublishedBugDeleteError):
        BugReportService.delete(session, bug.id)

    assert session.get(BugReport, bug.id) is not None
    session.close()


def test_local_service_edit_marks_published_bug_as_changed(database):
    session = database()
    bug, binding = _seed(session)

    BugReportService.update(session, bug.id, {"description": "Local edit"})

    assert binding.sync_state == "local_changed"
    assert bug.description == "Local edit"
    session.close()

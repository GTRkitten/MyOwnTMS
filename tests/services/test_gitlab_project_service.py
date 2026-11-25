import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, GitLabProject
from src.integrations.gitlab_client import (
    GitLabApiClient,
    GitLabClientConfig,
    GitLabNotFoundError,
    GitLabPermissionError,
    SessionToken,
)
from src.services.gitlab_project_service import (
    MANAGED_LABELS,
    GitLabLabelConflictError,
    GitLabLabelPreviewError,
    GitLabProjectAlreadyConfiguredError,
    GitLabProjectArchivedError,
    GitLabProjectResponseError,
    GitLabProjectService,
    GitLabProjectVisibilityError,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


def _project_payload(project_id, *, visibility="private", archived=False):
    return {
        "id": project_id,
        "path_with_namespace": f"customers/project-{project_id}",
        "web_url": f"https://gitlab.internal/customers/project-{project_id}",
        "visibility": visibility,
        "archived": archived,
    }


def _client(handler):
    token = SessionToken()
    token.set("session-only-test-token")
    return GitLabApiClient(
        GitLabClientConfig("https://gitlab.internal"),
        token,
        transport=httpx.MockTransport(handler),
    )


def test_adds_multiple_validated_private_project_profiles_without_token(session):
    def handler(request):
        project_id = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json=_project_payload(project_id))

    with _client(handler) as client:
        service = GitLabProjectService(client)
        first = service.add_project(
            session, display_name="Customer A", gitlab_project_id=11
        )
        second = service.add_project(
            session, display_name="Customer B", gitlab_project_id=12
        )

    assert first.id != second.id
    assert session.query(GitLabProject).count() == 2
    assert first.path_with_namespace == "customers/project-11"
    assert "token" not in GitLabProject.__table__.columns
    assert "session-only-test-token" not in repr(first.__dict__)


def test_duplicate_remote_project_is_rejected(session):
    with _client(
        lambda request: httpx.Response(200, json=_project_payload(11))
    ) as client:
        service = GitLabProjectService(client)
        service.add_project(session, display_name="First", gitlab_project_id=11)
        with pytest.raises(GitLabProjectAlreadyConfiguredError):
            service.add_project(session, display_name="Duplicate", gitlab_project_id=11)

    assert session.query(GitLabProject).count() == 1


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ({**_project_payload(11), "id": "11"}, GitLabProjectResponseError),
        (
            {**_project_payload(11), "web_url": "https://external.example/project"},
            GitLabProjectResponseError,
        ),
        (
            {**_project_payload(11), "web_url": "https://[::1"},
            GitLabProjectResponseError,
        ),
        (_project_payload(11, visibility="internal"), GitLabProjectVisibilityError),
        (_project_payload(11, archived=True), GitLabProjectArchivedError),
    ],
)
def test_rejects_invalid_non_private_or_archived_project_metadata(
    session, payload, expected_error
):
    with _client(lambda request: httpx.Response(200, json=payload)) as client:
        with pytest.raises(expected_error):
            GitLabProjectService(client).add_project(
                session, display_name="Rejected", gitlab_project_id=11
            )

    assert session.query(GitLabProject).count() == 0


def test_unavailable_project_is_a_controlled_client_error(session):
    with _client(lambda request: httpx.Response(404, text="private details")) as client:
        with pytest.raises(GitLabNotFoundError) as raised:
            GitLabProjectService(client).add_project(
                session, display_name="Unavailable", gitlab_project_id=11
            )

    assert "private details" not in str(raised.value)
    assert session.query(GitLabProject).count() == 0


def test_preview_has_no_mutation_and_confirmed_bootstrap_is_idempotent(session):
    remote_labels = {"myowntms"}
    posted_names = []

    def handler(request):
        if request.url.path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload(11))
        if request.method == "GET" and request.url.path.endswith("/labels"):
            return httpx.Response(
                200, json=[{"name": name} for name in sorted(remote_labels)]
            )
        if request.method == "POST" and request.url.path.endswith("/labels"):
            payload = json.loads(request.read())
            posted_names.append(payload["name"])
            remote_labels.add(payload["name"])
            return httpx.Response(201, json={"name": payload["name"]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        service = GitLabProjectService(client)
        project = service.add_project(
            session, display_name="Customer", gitlab_project_id=11
        )

        preview = service.preview_label_bootstrap(session, project.id)
        assert posted_names == []
        assert {label.name for label in preview.missing_labels} == {
            label.name for label in MANAGED_LABELS
        } - {"myowntms"}

        result = service.confirm_label_bootstrap(session, project.id, preview)
        second_preview = service.preview_label_bootstrap(session, project.id)
        second_result = service.confirm_label_bootstrap(
            session, project.id, second_preview
        )

    assert set(result.created_labels) == {
        label.name for label in MANAGED_LABELS
    } - {"myowntms"}
    assert result.remaining_missing_labels == ()
    assert result.labels_ready_at is not None
    assert second_preview.missing_labels == ()
    assert second_result.created_labels == ()
    assert len(posted_names) == len(MANAGED_LABELS) - 1


def test_confirm_creates_only_labels_shown_and_still_missing(session):
    remote_labels = {"myowntms"}
    posted_names = []

    def handler(request):
        if request.url.path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload(11))
        if request.method == "GET":
            return httpx.Response(200, json=[{"name": name} for name in remote_labels])
        payload = json.loads(request.read())
        posted_names.append(payload["name"])
        remote_labels.add(payload["name"])
        return httpx.Response(201, json={"name": payload["name"]})

    with _client(handler) as client:
        service = GitLabProjectService(client)
        project = service.add_project(
            session, display_name="Customer", gitlab_project_id=11
        )
        preview = service.preview_label_bootstrap(session, project.id)
        appeared_after_preview = preview.missing_labels[0].name
        remote_labels.add(appeared_after_preview)

        result = service.confirm_label_bootstrap(session, project.id, preview)

    assert appeared_after_preview not in posted_names
    assert result.remaining_missing_labels == ()


def test_preview_reads_all_matching_label_pages(session):
    labels = [f"myowntms-custom-{index}" for index in range(100)] + [
        MANAGED_LABELS[0].name
    ]

    def handler(request):
        if request.url.path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload(11))
        page = int(request.url.params["page"])
        start = (page - 1) * 100
        return httpx.Response(
            200, json=[{"name": name} for name in labels[start : start + 100]]
        )

    with _client(handler) as client:
        service = GitLabProjectService(client)
        project = service.add_project(
            session, display_name="Many labels", gitlab_project_id=11
        )
        preview = service.preview_label_bootstrap(session, project.id)

    assert MANAGED_LABELS[0] not in preview.missing_labels


def test_preview_refreshes_renamed_project_and_stale_preview_is_rejected(session):
    project_path = "customers/project-11"
    posted = []

    def handler(request):
        if request.url.path.endswith("/projects/11"):
            return httpx.Response(
                200,
                json={
                    **_project_payload(11),
                    "path_with_namespace": project_path,
                    "web_url": f"https://gitlab.internal/{project_path}",
                },
            )
        if request.method == "GET":
            return httpx.Response(200, json=[])
        posted.append(request)
        return httpx.Response(201, json={})

    with _client(handler) as client:
        service = GitLabProjectService(client)
        project = service.add_project(
            session, display_name="Renamed", gitlab_project_id=11
        )
        project_path = "customers/renamed-project"
        preview = service.preview_label_bootstrap(session, project.id)
        session.refresh(project)
        assert project.path_with_namespace == project_path
        assert preview.path_with_namespace == project_path

        project_path = "customers/moved-again"
        with pytest.raises(GitLabLabelPreviewError, match="changed"):
            service.confirm_label_bootstrap(session, project.id, preview)

    assert posted == []


def test_insufficient_role_does_not_mark_labels_ready(session):
    def handler(request):
        if request.url.path.endswith("/projects/11"):
            return httpx.Response(200, json=_project_payload(11))
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(403, text="sensitive role details")

    with _client(handler) as client:
        service = GitLabProjectService(client)
        project = service.add_project(
            session, display_name="Read only", gitlab_project_id=11
        )
        preview = service.preview_label_bootstrap(session, project.id)
        with pytest.raises(GitLabPermissionError) as raised:
            service.confirm_label_bootstrap(session, project.id, preview)

    session.refresh(project)
    assert "sensitive role details" not in str(raised.value)
    assert project.labels_ready_at is None


def test_rejects_case_collision_and_preview_for_another_project(session):
    labels_by_project = {11: [{"name": "MyOwnTMS"}], 12: []}

    def handler(request):
        parts = request.url.path.split("/")
        project_id = int(parts[parts.index("projects") + 1])
        if request.url.path.endswith(f"/projects/{project_id}"):
            return httpx.Response(200, json=_project_payload(project_id))
        return httpx.Response(200, json=labels_by_project[project_id])

    with _client(handler) as client:
        service = GitLabProjectService(client)
        first = service.add_project(
            session, display_name="First", gitlab_project_id=11
        )
        second = service.add_project(
            session, display_name="Second", gitlab_project_id=12
        )
        with pytest.raises(GitLabLabelConflictError):
            service.preview_label_bootstrap(session, first.id)
        second_preview = service.preview_label_bootstrap(session, second.id)
        with pytest.raises(GitLabLabelPreviewError):
            service.confirm_label_bootstrap(session, first.id, second_preview)

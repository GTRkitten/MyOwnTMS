"""Validated GitLab project profiles and explicit managed-label bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models import GitLabProject
from src.integrations.gitlab_client import GitLabApiClient


class GitLabProjectServiceError(Exception):
    """Base class for safe project-profile errors."""


class GitLabProjectResponseError(GitLabProjectServiceError):
    """GitLab returned project or label metadata that cannot be trusted."""


class GitLabProjectVisibilityError(GitLabProjectServiceError):
    """The selected project is not private."""


class GitLabProjectArchivedError(GitLabProjectServiceError):
    """The selected project is archived."""


class GitLabProjectNotConfiguredError(GitLabProjectServiceError):
    """The requested local profile does not exist."""


class GitLabProjectInactiveError(GitLabProjectServiceError):
    """The requested local profile is disabled."""


class GitLabProjectAlreadyConfiguredError(GitLabProjectServiceError):
    """The remote project already has a local profile."""


class GitLabLabelConflictError(GitLabProjectServiceError):
    """A differently-cased label prevents safe managed-label creation."""


class GitLabLabelPreviewError(GitLabProjectServiceError):
    """The confirmed preview does not belong to the selected profile."""


@dataclass(frozen=True)
class ManagedLabel:
    name: str
    color: str
    description: str


MANAGED_LABELS: tuple[ManagedLabel, ...] = (
    ManagedLabel("myowntms", "#1F75CB", "Managed by MyOwnTMS"),
    ManagedLabel("myowntms-status-new", "#428BCA", "MyOwnTMS status: new"),
    ManagedLabel(
        "myowntms-status-in-progress",
        "#FBCA04",
        "MyOwnTMS status: in progress",
    ),
    ManagedLabel(
        "myowntms-status-verified", "#0E8A16", "MyOwnTMS status: verified"
    ),
    ManagedLabel("myowntms-status-closed", "#6B7280", "MyOwnTMS status: closed"),
    ManagedLabel(
        "myowntms-priority-critical", "#B60205", "MyOwnTMS priority: critical"
    ),
    ManagedLabel("myowntms-priority-high", "#D93F0B", "MyOwnTMS priority: high"),
    ManagedLabel(
        "myowntms-priority-medium", "#FBCA04", "MyOwnTMS priority: medium"
    ),
    ManagedLabel("myowntms-priority-low", "#0E8A16", "MyOwnTMS priority: low"),
    ManagedLabel(
        "myowntms-severity-critical", "#B60205", "MyOwnTMS severity: critical"
    ),
    ManagedLabel("myowntms-severity-major", "#D93F0B", "MyOwnTMS severity: major"),
    ManagedLabel("myowntms-severity-minor", "#FBCA04", "MyOwnTMS severity: minor"),
    ManagedLabel(
        "myowntms-severity-trivial", "#C5DEF5", "MyOwnTMS severity: trivial"
    ),
)

_MANAGED_LABELS_BY_NAME = {label.name: label for label in MANAGED_LABELS}


@dataclass(frozen=True)
class LabelBootstrapPreview:
    """Read-only snapshot displayed before any label mutation."""

    local_project_id: int
    gitlab_project_id: int
    path_with_namespace: str
    web_url: str
    missing_labels: tuple[ManagedLabel, ...]


@dataclass(frozen=True)
class LabelBootstrapResult:
    """Result of an explicitly confirmed, resumable bootstrap attempt."""

    created_labels: tuple[str, ...]
    remaining_missing_labels: tuple[str, ...]
    labels_ready_at: datetime | None


@dataclass(frozen=True)
class _ValidatedRemoteProject:
    gitlab_project_id: int
    path_with_namespace: str
    web_url: str
    visibility: str


def _bounded_clean_text(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    if value != value.strip() or any(ord(character) < 32 for character in value):
        return None
    return value


def _url_origin_parts(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if not parsed.scheme or not parsed.hostname:
        return None
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    return parsed.scheme.lower(), parsed.hostname.lower(), port or default_port


class GitLabProjectService:
    """Coordinates remote validation with local project-profile persistence."""

    def __init__(self, client: GitLabApiClient) -> None:
        self._client = client

    def add_project(
        self,
        session: Session,
        *,
        display_name: str,
        gitlab_project_id: int,
    ) -> GitLabProject:
        display_name = _bounded_clean_text(display_name, 200)
        if display_name is None:
            raise GitLabProjectResponseError("Project display name is invalid")
        if (
            isinstance(gitlab_project_id, bool)
            or not isinstance(gitlab_project_id, int)
            or gitlab_project_id <= 0
        ):
            raise GitLabProjectResponseError("GitLab project ID is invalid")

        remote = self._get_validated_remote_project(gitlab_project_id)
        if (
            session.query(GitLabProject)
            .filter(GitLabProject.gitlab_project_id == gitlab_project_id)
            .first()
            is not None
        ):
            raise GitLabProjectAlreadyConfiguredError(
                "GitLab project is already configured"
            )

        project = GitLabProject(
            display_name=display_name,
            gitlab_project_id=remote.gitlab_project_id,
            path_with_namespace=remote.path_with_namespace,
            web_url=remote.web_url,
            visibility=remote.visibility,
            is_active=True,
        )
        session.add(project)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise GitLabProjectAlreadyConfiguredError(
                "GitLab project is already configured"
            ) from None
        session.refresh(project)
        return project

    def revalidate_project(self, project: GitLabProject) -> None:
        """Fail closed unless a stored profile still identifies the same project."""

        if not isinstance(project, GitLabProject):
            raise GitLabProjectResponseError("GitLab project profile is invalid")
        remote = self._get_validated_remote_project(project.gitlab_project_id)
        if (
            remote.path_with_namespace != project.path_with_namespace
            or remote.web_url != project.web_url
            or remote.visibility != project.visibility
        ):
            raise GitLabProjectResponseError(
                "GitLab project changed after local validation"
            )

    def preview_label_bootstrap(
        self, session: Session, local_project_id: int
    ) -> LabelBootstrapPreview:
        project = self._get_active_profile(session, local_project_id)
        remote = self._get_validated_remote_project(project.gitlab_project_id)
        self._refresh_profile_metadata(session, project, remote)
        existing = self._get_existing_label_names(remote.gitlab_project_id)
        missing = tuple(
            label for label in MANAGED_LABELS if label.name not in existing
        )
        return LabelBootstrapPreview(
            local_project_id=project.id,
            gitlab_project_id=remote.gitlab_project_id,
            path_with_namespace=remote.path_with_namespace,
            web_url=remote.web_url,
            missing_labels=missing,
        )

    def confirm_label_bootstrap(
        self,
        session: Session,
        local_project_id: int,
        preview: LabelBootstrapPreview,
    ) -> LabelBootstrapResult:
        """Create only labels shown in a prior preview, then verify readiness."""

        project = self._get_active_profile(session, local_project_id)
        self._validate_preview(project, preview)
        remote = self._get_validated_remote_project(project.gitlab_project_id)
        if (
            remote.path_with_namespace != preview.path_with_namespace
            or remote.web_url != preview.web_url
        ):
            raise GitLabLabelPreviewError(
                "GitLab project changed after the label preview"
            )
        existing = self._get_existing_label_names(remote.gitlab_project_id)
        created: list[str] = []

        for label in preview.missing_labels:
            if label.name in existing:
                continue
            self._client.create_label(
                remote.gitlab_project_id,
                name=label.name,
                color=label.color,
                description=label.description,
            )
            created.append(label.name)
            existing.add(label.name)

        final_names = self._get_existing_label_names(remote.gitlab_project_id)
        remaining = tuple(
            label.name for label in MANAGED_LABELS if label.name not in final_names
        )
        if remaining:
            project.labels_ready_at = None
        else:
            project.labels_ready_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()
        session.refresh(project)
        return LabelBootstrapResult(
            created_labels=tuple(created),
            remaining_missing_labels=remaining,
            labels_ready_at=project.labels_ready_at,
        )

    def _get_validated_remote_project(
        self, requested_project_id: int
    ) -> _ValidatedRemoteProject:
        payload = self._client.get_project(requested_project_id)
        return self._validate_remote_project(payload, requested_project_id)

    def _validate_remote_project(
        self, payload: Mapping[str, Any], requested_project_id: int
    ) -> _ValidatedRemoteProject:
        remote_id = payload.get("id")
        path = _bounded_clean_text(payload.get("path_with_namespace"), 500)
        web_url = _bounded_clean_text(payload.get("web_url"), 1000)
        visibility = payload.get("visibility")
        archived = payload.get("archived")

        if (
            isinstance(remote_id, bool)
            or not isinstance(remote_id, int)
            or remote_id <= 0
            or remote_id != requested_project_id
            or path is None
            or path.startswith("/")
            or path.endswith("/")
            or any(segment in {"", ".", ".."} for segment in path.split("/"))
            or any(
                not all(
                    character.isalnum() or character in "_.-"
                    for character in segment
                )
                for segment in path.split("/")
            )
            or web_url is None
            or not isinstance(visibility, str)
            or not isinstance(archived, bool)
        ):
            raise GitLabProjectResponseError("GitLab project metadata is invalid")
        if archived:
            raise GitLabProjectArchivedError("Archived GitLab project is not supported")
        if visibility != "private":
            raise GitLabProjectVisibilityError("GitLab project must be private")

        try:
            parsed_web_url = urlsplit(web_url)
            parsed_web_url.port
        except ValueError:
            raise GitLabProjectResponseError(
                "GitLab project web URL is invalid"
            ) from None
        if (
            parsed_web_url.username is not None
            or parsed_web_url.password is not None
            or parsed_web_url.query
            or parsed_web_url.fragment
            or _url_origin_parts(web_url) != _url_origin_parts(self._client.origin)
            or unquote(parsed_web_url.path).strip("/") != path
        ):
            raise GitLabProjectResponseError("GitLab project web URL is invalid")

        return _ValidatedRemoteProject(
            gitlab_project_id=remote_id,
            path_with_namespace=path,
            web_url=web_url,
            visibility=visibility,
        )

    def _get_existing_label_names(self, gitlab_project_id: int) -> set[str]:
        names: set[str] = set()
        casefolded: dict[str, str] = {}
        for page in range(1, 101):
            payload = self._client.list_labels(
                gitlab_project_id, search="myowntms", page=page
            )
            for item in payload:
                if not isinstance(item, Mapping):
                    raise GitLabProjectResponseError(
                        "GitLab label metadata is invalid"
                    )
                name = _bounded_clean_text(item.get("name"), 255)
                if name is None:
                    raise GitLabProjectResponseError(
                        "GitLab label metadata is invalid"
                    )
                folded = name.casefold()
                existing_spelling = casefolded.get(folded)
                if existing_spelling is not None and existing_spelling != name:
                    raise GitLabLabelConflictError(
                        "GitLab labels have a case conflict"
                    )
                casefolded[folded] = name
                names.add(name)
            if len(payload) < 100:
                break
        else:
            raise GitLabProjectResponseError("GitLab label result is too large")

        for managed_name in _MANAGED_LABELS_BY_NAME:
            existing_spelling = casefolded.get(managed_name.casefold())
            if existing_spelling is not None and existing_spelling != managed_name:
                raise GitLabLabelConflictError(
                    "A differently-cased managed label already exists"
                )
        return names

    @staticmethod
    def _refresh_profile_metadata(
        session: Session,
        project: GitLabProject,
        remote: _ValidatedRemoteProject,
    ) -> None:
        changed = (
            project.path_with_namespace != remote.path_with_namespace
            or project.web_url != remote.web_url
            or project.visibility != remote.visibility
        )
        if not changed:
            return
        project.path_with_namespace = remote.path_with_namespace
        project.web_url = remote.web_url
        project.visibility = remote.visibility
        session.commit()
        session.refresh(project)

    @staticmethod
    def _get_active_profile(session: Session, local_project_id: int) -> GitLabProject:
        if (
            isinstance(local_project_id, bool)
            or not isinstance(local_project_id, int)
            or local_project_id <= 0
        ):
            raise GitLabProjectNotConfiguredError("GitLab project is not configured")
        project = session.get(GitLabProject, local_project_id)
        if project is None:
            raise GitLabProjectNotConfiguredError("GitLab project is not configured")
        if not project.is_active:
            raise GitLabProjectInactiveError("GitLab project profile is inactive")
        return project

    @staticmethod
    def _validate_preview(
        project: GitLabProject, preview: LabelBootstrapPreview
    ) -> None:
        if not isinstance(preview, LabelBootstrapPreview):
            raise GitLabLabelPreviewError("Label bootstrap preview is invalid")
        if (
            preview.local_project_id != project.id
            or preview.gitlab_project_id != project.gitlab_project_id
            or preview.path_with_namespace != project.path_with_namespace
            or preview.web_url != project.web_url
        ):
            raise GitLabLabelPreviewError(
                "Label bootstrap preview does not match the project"
            )
        if not isinstance(preview.missing_labels, tuple) or not all(
            isinstance(label, ManagedLabel) for label in preview.missing_labels
        ):
            raise GitLabLabelPreviewError("Label bootstrap preview is invalid")
        names = [label.name for label in preview.missing_labels]
        if (
            len(names) != len(set(names))
            or any(
                _MANAGED_LABELS_BY_NAME.get(label.name) != label
                for label in preview.missing_labels
            )
        ):
            raise GitLabLabelPreviewError("Label bootstrap preview is invalid")

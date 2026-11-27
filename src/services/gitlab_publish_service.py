"""Explicit, resumable publication of local bug reports to GitLab Issues."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models import (
    Attachment,
    BugReport,
    GitLabAttachmentBinding,
    GitLabBinding,
    GitLabProject,
)
from src.integrations.gitlab_client import (
    GitLabApiClient,
    GitLabClientError,
    GitLabConnectionError,
    GitLabMalformedResponseError,
    GitLabServerError,
    GitLabTimeoutError,
    GitLabUnexpectedResponseError,
)
from src.services.gitlab_issue_codec import (
    ManagedBlockError,
    ManagedIssueContent,
    managed_labels_for,
    merge_managed_labels,
    parse_managed_document,
    replace_managed_block,
    serialize_managed_block,
)
from src.services.gitlab_project_service import (
    GitLabManagedLabelsMissingError,
    GitLabProjectService,
    GitLabProjectServiceError,
)


MAX_IMAGE_BYTES = 10 * 1024 * 1024
_IMAGE_EXTENSIONS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_SOURCE_CHANNELS = {"email", "messenger", "phone", "meeting", "other"}
_UNCERTAIN_CREATE_ERRORS = (
    GitLabTimeoutError,
    GitLabConnectionError,
    GitLabServerError,
    GitLabMalformedResponseError,
    GitLabUnexpectedResponseError,
)


class GitLabPublishError(Exception):
    """Base class for safe publication errors."""


class PublishValidationError(GitLabPublishError):
    """The local bug or selected project is not publishable."""


class PublishPreviewStaleError(GitLabPublishError):
    """Local fields or files changed after the displayed preview."""


class PublishBindingConflictError(GitLabPublishError):
    """The local bug is already bound inconsistently."""


class PublishDuplicateIssueError(GitLabPublishError):
    """More than one remote Issue contains the immutable marker."""


class PublishRemoteResponseError(GitLabPublishError):
    """GitLab returned unsafe or incomplete publish metadata."""


class PublishUploadOutcomeUncertainError(GitLabPublishError):
    """An upload may exist remotely but cannot be bound without its response."""

    def __init__(
        self, message: str, *, original_error: BaseException | None = None
    ) -> None:
        self.status_code = getattr(original_error, "status_code", None)
        self.request_id = getattr(original_error, "request_id", None)
        super().__init__(message)


_UNCERTAIN_UPLOAD_ERRORS = (
    *_UNCERTAIN_CREATE_ERRORS,
    PublishRemoteResponseError,
)


class GitLabPublishResumableError(GitLabPublishError):
    """A persisted publication stopped after a recoverable or uncertain failure."""

    def __init__(
        self, *, issue_created: bool, error_type: str, retry_safe: bool = True
    ) -> None:
        self.issue_created = issue_created
        self.error_type = error_type
        self.retry_safe = retry_safe
        if retry_safe:
            message = "GitLab publication is incomplete and can be resumed"
        else:
            message = (
                "GitLab upload outcome is uncertain; automatic retry is blocked "
                "to prevent a duplicate upload"
            )
        if issue_created:
            message += "; the remote Issue was retained"
        super().__init__(message)


@dataclass(frozen=True)
class PublishFieldPreview:
    name: str
    value: str


@dataclass(frozen=True)
class PublishFilePreview:
    attachment_id: int
    display_name: str
    upload_name: str | None
    content_type: str
    size_bytes: int | None
    content_sha256: str | None
    will_upload: bool
    skip_reason: str | None = None


@dataclass(frozen=True)
class PublishPreview:
    bug_report_id: str
    local_project_id: int
    gitlab_project_id: int
    project_display_name: str
    project_path_with_namespace: str
    project_web_url: str
    issue_title: str
    fields: tuple[PublishFieldPreview, ...]
    labels: tuple[str, ...]
    files: tuple[PublishFilePreview, ...]


@dataclass(frozen=True)
class PublishResult:
    issue_id: int
    issue_iid: int
    issue_web_url: str
    uploaded_attachment_ids: tuple[int, ...]
    reused_attachment_ids: tuple[int, ...]
    sync_state: str


@dataclass(frozen=True)
class _RemoteIssue:
    issue_id: int
    issue_iid: int
    web_url: str
    title: str
    description: str
    labels: tuple[str, ...]
    state: str
    updated_at: datetime


def _clean_required(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublishValidationError(f"{field_name} is required for publication")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > 1_000_000:
        raise PublishValidationError(f"{field_name} is too long")
    return normalized


def _clean_optional(value: Any, field_name: str, maximum: int = 1_000_000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PublishValidationError(f"{field_name} must be text")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > maximum:
        raise PublishValidationError(f"{field_name} is too long")
    return normalized


def _safe_upload_name(attachment: Attachment) -> str:
    raw_name = _clean_required(attachment.file_name, "Attachment file name")
    base_name = PurePosixPath(raw_name.replace("\\", "/")).name
    if (
        not base_name
        or base_name in {".", ".."}
        or ":" in base_name
        or any(ord(character) < 32 for character in base_name)
    ):
        raise PublishValidationError("Attachment file name is invalid")
    candidate = f"attachment-{attachment.id}-{base_name}"
    if len(candidate) > 255:
        suffix = Path(base_name).suffix
        candidate = f"attachment-{attachment.id}-{base_name[:220]}{suffix}"
    return candidate


def _read_validated_image(attachment: Attachment) -> tuple[bytes, str, str, str]:
    extension = Path(attachment.file_name).suffix.lower()
    expected_type = _IMAGE_EXTENSIONS.get(extension)
    if expected_type is None:
        raise PublishValidationError("Only PNG and JPEG attachments can be uploaded")
    path = attachment.get_absolute_path()
    if not path.is_file():
        raise PublishValidationError("Attachment file is missing")
    try:
        with path.open("rb") as stream:
            content = stream.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        raise PublishValidationError("Attachment file cannot be read") from None
    if not content:
        raise PublishValidationError("Attachment file is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise PublishValidationError("Attachment exceeds the 10 MiB limit")

    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        actual_type = "image/png"
    elif content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"):
        actual_type = "image/jpeg"
    else:
        raise PublishValidationError("Attachment content is not PNG or JPEG")
    if actual_type != expected_type:
        raise PublishValidationError("Attachment extension does not match its content")
    return content, actual_type, hashlib.sha256(content).hexdigest(), _safe_upload_name(attachment)


def _origin(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if not parsed.scheme or not parsed.hostname:
        return None
    return parsed.scheme.lower(), parsed.hostname.lower(), port or (443 if parsed.scheme.lower() == "https" else 80)


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 100:
        raise PublishRemoteResponseError("GitLab Issue timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PublishRemoteResponseError("GitLab Issue timestamp is invalid") from None
    if parsed.tzinfo is None:
        raise PublishRemoteResponseError("GitLab Issue timestamp is invalid")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


class GitLabPublishService:
    """Coordinates preview, create recovery, uploads, and final Issue update."""

    def __init__(self, client: GitLabApiClient) -> None:
        self._client = client

    def preview(self, session: Session, bug_report_id: str) -> PublishPreview:
        bug = session.get(BugReport, bug_report_id)
        if bug is None:
            raise PublishValidationError("Bug report was not found")
        project = self._validated_project(bug)
        values = self._validated_bug_values(bug)
        issue_title = f"[{bug.id}] {values['title']}"
        if len(issue_title) > 255:
            raise PublishValidationError("GitLab Issue title is too long")
        labels = managed_labels_for(bug.status, bug.priority, bug.severity)
        preview_block = serialize_managed_block(
            self._managed_content(
                bug, "00000000-0000-4000-8000-000000000004", ()
            )
        )
        if len(preview_block) > 1_000_000:
            raise PublishValidationError("GitLab Issue description is too long")

        files = []
        for attachment in sorted(bug.attachments, key=lambda item: item.id):
            extension = Path(attachment.file_name).suffix.lower()
            if extension not in _IMAGE_EXTENSIONS:
                files.append(
                    PublishFilePreview(
                        attachment_id=attachment.id,
                        display_name=attachment.file_name,
                        upload_name=None,
                        content_type=attachment.file_type,
                        size_bytes=None,
                        content_sha256=None,
                        will_upload=False,
                        skip_reason="unsupported_type",
                    )
                )
                continue
            content, content_type, digest, upload_name = _read_validated_image(attachment)
            files.append(
                PublishFilePreview(
                    attachment_id=attachment.id,
                    display_name=attachment.file_name,
                    upload_name=upload_name,
                    content_type=content_type,
                    size_bytes=len(content),
                    content_sha256=digest,
                    will_upload=True,
                )
            )

        fields = tuple(
            PublishFieldPreview(name, values[name])
            for name in (
                "title",
                "description",
                "reproduction_steps",
                "expected_result",
                "actual_result",
                "environment",
                "source_channel",
                "external_reference",
                "status",
                "priority",
                "severity",
            )
        )
        return PublishPreview(
            bug_report_id=bug.id,
            local_project_id=project.id,
            gitlab_project_id=project.gitlab_project_id,
            project_display_name=project.display_name,
            project_path_with_namespace=project.path_with_namespace,
            project_web_url=project.web_url,
            issue_title=issue_title,
            fields=fields,
            labels=labels,
            files=tuple(files),
        )

    def publish(
        self,
        session: Session,
        bug_report_id: str,
        preview: PublishPreview,
    ) -> PublishResult:
        """Execute an explicitly confirmed preview and persist resumable state."""

        current_preview = self.preview(session, bug_report_id)
        if current_preview != preview:
            raise PublishPreviewStaleError(
                "Bug fields, project, or attachments changed after preview"
            )
        bug = session.get(BugReport, bug_report_id)
        project = self._validated_project(bug)
        self._revalidate_project(session, project)
        binding, created_locally = self._get_or_create_binding(session, bug, project)

        uploaded_ids: list[int] = []
        reused_ids: list[int] = []
        try:
            remote = self._ensure_remote_issue(
                session,
                binding,
                project,
                bug,
                preview,
                created_locally=created_locally,
            )
            self._assert_matching_marker(remote, binding)
            markdown = []
            for file_preview in preview.files:
                if not file_preview.will_upload:
                    continue
                attachment = session.get(Attachment, file_preview.attachment_id)
                if attachment is None or attachment.bug_report_id != bug.id:
                    raise PublishPreviewStaleError("Attachment changed after preview")
                content, content_type, digest, upload_name = _read_validated_image(
                    attachment
                )
                if (
                    digest != file_preview.content_sha256
                    or len(content) != file_preview.size_bytes
                    or content_type != file_preview.content_type
                    or upload_name != file_preview.upload_name
                ):
                    raise PublishPreviewStaleError("Attachment changed after preview")
                attachment_binding = self._completed_attachment_binding(
                    session, binding.id, attachment.id, digest
                )
                if attachment_binding is not None:
                    markdown.append(attachment_binding.remote_markdown)
                    reused_ids.append(attachment.id)
                    continue
                attachment_binding, upload_intent_created = (
                    self._pending_attachment_binding(
                        session, binding, attachment, digest
                    )
                )
                if not upload_intent_created:
                    raise PublishUploadOutcomeUncertainError(
                        "A previous upload attempt has no recoverable response metadata"
                    )
                try:
                    upload = self._client.upload_file(
                        project.gitlab_project_id,
                        file_name=upload_name,
                        content=content,
                        content_type=content_type,
                    )
                    remote_upload_id, remote_url, remote_markdown = (
                        self._validated_upload(upload)
                    )
                except _UNCERTAIN_UPLOAD_ERRORS as error:
                    raise PublishUploadOutcomeUncertainError(
                        "GitLab may have stored the upload, but its response metadata "
                        "was not received",
                        original_error=error,
                    ) from error
                except GitLabClientError:
                    # A definitive rejection did not create an upload, so a later
                    # explicit publish may safely create a fresh intent and retry.
                    session.delete(attachment_binding)
                    session.commit()
                    raise
                attachment_binding.remote_upload_id = remote_upload_id
                attachment_binding.remote_url = remote_url
                attachment_binding.remote_markdown = remote_markdown
                attachment_binding.uploaded_at = datetime.now()
                session.commit()
                markdown.append(remote_markdown)
                uploaded_ids.append(attachment.id)

            remote = self._remote_issue(
                self._client.get_issue(project.gitlab_project_id, binding.issue_iid),
                project,
            )
            self._assert_matching_marker(remote, binding)
            desired_content = self._managed_content(
                bug, binding.sync_uid, tuple(markdown)
            )
            desired_description = replace_managed_block(
                remote.description, desired_content
            )
            desired_labels = merge_managed_labels(remote.labels, preview.labels)
            state_event = None
            desired_state = "closed" if bug.status == "Закрыт" else "opened"
            if remote.state != desired_state:
                state_event = "close" if desired_state == "closed" else "reopen"

            update_fields: dict[str, Any] = {}
            if remote.title != preview.issue_title:
                update_fields["title"] = preview.issue_title
            if remote.description != desired_description:
                update_fields["description"] = desired_description
            if set(remote.labels) != set(desired_labels):
                update_fields["labels"] = desired_labels
            if state_event is not None:
                update_fields["state_event"] = state_event
            if update_fields:
                remote = self._remote_issue(
                    self._client.update_issue(
                        project.gitlab_project_id,
                        binding.issue_iid,
                        **update_fields,
                    ),
                    project,
                )

            binding.issue_id = remote.issue_id
            binding.issue_iid = remote.issue_iid
            binding.issue_web_url = remote.web_url
            binding.remote_updated_at = remote.updated_at
            binding.base_snapshot = self._base_snapshot(bug, tuple(markdown))
            binding.sync_state = "synced"
            binding.last_error_type = None
            binding.last_error_http_status = None
            binding.last_error_request_id = None
            session.commit()
            return PublishResult(
                issue_id=remote.issue_id,
                issue_iid=remote.issue_iid,
                issue_web_url=remote.web_url,
                uploaded_attachment_ids=tuple(uploaded_ids),
                reused_attachment_ids=tuple(reused_ids),
                sync_state=binding.sync_state,
            )
        except (
            GitLabClientError,
            GitLabPublishError,
            ManagedBlockError,
        ) as error:
            session.rollback()
            binding = session.get(GitLabBinding, binding.id)
            self._record_error(session, binding, error)
            raise GitLabPublishResumableError(
                issue_created=binding.issue_iid is not None,
                error_type=type(error).__name__,
                retry_safe=not isinstance(
                    error, PublishUploadOutcomeUncertainError
                ),
            ) from error

    def _validated_project(self, bug: BugReport) -> GitLabProject:
        if bug is None or bug.gitlab_project is None:
            raise PublishValidationError("A GitLab project is required")
        project = bug.gitlab_project
        if not project.is_active or project.visibility != "private":
            raise PublishValidationError("The GitLab project is not active and private")
        if project.labels_ready_at is None:
            raise PublishValidationError("The GitLab project labels are not ready")
        if _origin(project.web_url) != _origin(self._client.origin):
            raise PublishValidationError(
                "The GitLab project belongs to a different configured origin"
            )
        return project

    def _revalidate_project(
        self, session: Session, project: GitLabProject
    ) -> None:
        """Recheck project identity and labels before any publish mutation."""

        try:
            GitLabProjectService(self._client).verify_managed_labels(project)
        except GitLabManagedLabelsMissingError as error:
            project.labels_ready_at = None
            session.commit()
            raise PublishValidationError(
                "The GitLab project labels must be previewed and prepared again"
            ) from error
        except GitLabProjectServiceError as error:
            raise PublishValidationError(
                "The GitLab project could not be safely revalidated"
            ) from error

    @staticmethod
    def _validated_bug_values(bug: BugReport) -> dict[str, str]:
        if bug.status == "Черновик":
            raise PublishValidationError("Draft bug reports cannot be published")
        values = {
            "title": _clean_required(bug.title, "Title"),
            "description": _clean_optional(bug.description, "Description"),
            "reproduction_steps": _clean_required(
                bug.reproduction_steps, "Reproduction steps"
            ),
            "expected_result": _clean_required(bug.expected_result, "Expected result"),
            "actual_result": _clean_required(bug.actual_result, "Actual result"),
            "environment": _clean_optional(bug.environment, "Environment"),
            "source_channel": _clean_optional(
                bug.source_channel, "Source channel", 20
            ),
            "external_reference": _clean_optional(
                bug.external_reference, "External reference", 500
            ),
            "status": _clean_required(bug.status, "Status"),
            "priority": _clean_required(bug.priority, "Priority"),
            "severity": _clean_required(bug.severity, "Severity"),
        }
        if (
            values["source_channel"]
            and values["source_channel"] not in _SOURCE_CHANNELS
        ):
            raise PublishValidationError("Source channel is invalid")
        if "\n" in values["external_reference"]:
            raise PublishValidationError("External reference must be single-line text")
        if "://" in values["external_reference"]:
            try:
                reference_url = urlsplit(values["external_reference"])
                reference_url.port
            except ValueError:
                raise PublishValidationError("External reference URL is invalid") from None
            if reference_url.username is not None or reference_url.password is not None:
                raise PublishValidationError(
                    "External reference URL must not contain credentials"
                )
        return values

    @staticmethod
    def _managed_content(
        bug: BugReport, sync_uid: str, markdown: tuple[str, ...]
    ) -> ManagedIssueContent:
        values = GitLabPublishService._validated_bug_values(bug)
        return ManagedIssueContent(
            sync_uid=sync_uid,
            description=values["description"],
            reproduction_steps=values["reproduction_steps"],
            expected_result=values["expected_result"],
            actual_result=values["actual_result"],
            environment=values["environment"],
            source_channel=values["source_channel"] or None,
            external_reference=values["external_reference"] or None,
            attachment_markdown=markdown,
        )

    @staticmethod
    def _get_or_create_binding(
        session: Session, bug: BugReport, project: GitLabProject
    ) -> tuple[GitLabBinding, bool]:
        binding = bug.gitlab_binding
        if binding is not None:
            if binding.project_id != project.id:
                raise PublishBindingConflictError(
                    "Published bug cannot be moved to another GitLab project"
                )
            binding.sync_state = "publishing"
            session.commit()
            return binding, False
        binding = GitLabBinding(
            bug_report=bug,
            project=project,
            sync_uid=str(uuid4()),
            sync_state="publishing",
        )
        session.add(binding)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            binding = session.query(GitLabBinding).filter_by(bug_report_id=bug.id).one()
            if binding.project_id != project.id:
                raise PublishBindingConflictError(
                    "Published bug cannot be moved to another GitLab project"
                ) from None
            binding.sync_state = "publishing"
            session.commit()
            return binding, False
        session.refresh(binding)
        return binding, True

    def _ensure_remote_issue(
        self,
        session: Session,
        binding: GitLabBinding,
        project: GitLabProject,
        bug: BugReport,
        preview: PublishPreview,
        *,
        created_locally: bool,
    ) -> _RemoteIssue:
        if binding.issue_iid is not None:
            return self._remote_issue(
                self._client.get_issue(project.gitlab_project_id, binding.issue_iid),
                project,
            )

        remote = None
        if not created_locally:
            remote = self._find_exact_marker(project, binding.sync_uid)
        if remote is None:
            initial_description = serialize_managed_block(
                self._managed_content(bug, binding.sync_uid, ())
            )
            try:
                payload = self._client.create_issue(
                    project.gitlab_project_id,
                    title=preview.issue_title,
                    description=initial_description,
                    labels=preview.labels,
                )
                remote = self._remote_issue(payload, project)
            except _UNCERTAIN_CREATE_ERRORS:
                recovered = self._find_exact_marker(project, binding.sync_uid)
                if recovered is None:
                    raise
                remote = recovered

        binding.issue_id = remote.issue_id
        binding.issue_iid = remote.issue_iid
        binding.issue_web_url = remote.web_url
        binding.remote_updated_at = remote.updated_at
        session.commit()
        return remote

    @staticmethod
    def _assert_matching_marker(
        remote: _RemoteIssue, binding: GitLabBinding
    ) -> None:
        parsed = parse_managed_document(remote.description)
        if parsed.content.sync_uid != binding.sync_uid:
            raise PublishRemoteResponseError("Remote Issue marker does not match")
        if binding.issue_id is not None and binding.issue_id != remote.issue_id:
            raise PublishRemoteResponseError("Remote Issue identity changed")
        if (
            binding.issue_web_url is not None
            and binding.issue_web_url != remote.web_url
        ):
            raise PublishRemoteResponseError("Remote Issue identity changed")

    def _find_exact_marker(
        self, project: GitLabProject, sync_uid: str
    ) -> _RemoteIssue | None:
        marker = f"<!-- MYOWNTMS:BEGIN version=1 sync_uid={sync_uid} -->"
        matches: list[_RemoteIssue] = []
        for page in range(1, 101):
            payloads = self._client.list_issues(
                project.gitlab_project_id, search=sync_uid, page=page
            )
            for payload in payloads:
                description = (
                    payload.get("description")
                    if isinstance(payload, Mapping)
                    else None
                )
                if not isinstance(description, str) or marker not in description:
                    continue
                remote = self._remote_issue(payload, project)
                try:
                    parsed = parse_managed_document(remote.description)
                except ManagedBlockError:
                    continue
                if parsed.content.sync_uid == sync_uid:
                    matches.append(remote)
            if len(payloads) < 100:
                break
        else:
            raise PublishRemoteResponseError("GitLab Issue recovery result is too large")
        if len(matches) > 1:
            raise PublishDuplicateIssueError("Duplicate GitLab Issues use the same marker")
        return matches[0] if matches else None

    def _remote_issue(
        self, payload: Mapping[str, Any], project: GitLabProject
    ) -> _RemoteIssue:
        if not isinstance(payload, Mapping):
            raise PublishRemoteResponseError("GitLab Issue metadata is invalid")
        issue_id = payload.get("id")
        iid = payload.get("iid")
        web_url = payload.get("web_url")
        title = payload.get("title")
        description = payload.get("description")
        labels = payload.get("labels")
        state = payload.get("state")
        if (
            isinstance(issue_id, bool)
            or not isinstance(issue_id, int)
            or issue_id <= 0
            or isinstance(iid, bool)
            or not isinstance(iid, int)
            or iid <= 0
            or not isinstance(web_url, str)
            or not isinstance(title, str)
            or not isinstance(description, str)
            or not isinstance(labels, list)
            or not all(isinstance(label, str) for label in labels)
            or state not in {"opened", "closed"}
        ):
            raise PublishRemoteResponseError("GitLab Issue metadata is invalid")
        expected_path = f"{urlsplit(project.web_url).path.rstrip('/')}/-/issues/{iid}"
        parsed_url = urlsplit(web_url)
        if (
            _origin(web_url) != _origin(self._client.origin)
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.path.rstrip("/") != expected_path
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise PublishRemoteResponseError("GitLab Issue URL is invalid")
        return _RemoteIssue(
            issue_id=issue_id,
            issue_iid=iid,
            web_url=web_url,
            title=title,
            description=description,
            labels=tuple(labels),
            state=state,
            updated_at=_parse_datetime(payload.get("updated_at")),
        )

    @staticmethod
    def _completed_attachment_binding(
        session: Session, binding_id: int, attachment_id: int, digest: str
    ) -> GitLabAttachmentBinding | None:
        candidate = (
            session.query(GitLabAttachmentBinding)
            .filter_by(
                gitlab_binding_id=binding_id,
                attachment_id=attachment_id,
                content_sha256=digest,
            )
            .one_or_none()
        )
        if (
            candidate is not None
            and candidate.remote_upload_id
            and candidate.remote_url
            and candidate.remote_markdown
            and candidate.uploaded_at is not None
        ):
            return candidate
        return None

    @staticmethod
    def _pending_attachment_binding(
        session: Session,
        binding: GitLabBinding,
        attachment: Attachment,
        digest: str,
    ) -> tuple[GitLabAttachmentBinding, bool]:
        candidate = (
            session.query(GitLabAttachmentBinding)
            .filter_by(attachment_id=attachment.id, content_sha256=digest)
            .one_or_none()
        )
        if candidate is None:
            candidate = GitLabAttachmentBinding(
                gitlab_binding=binding,
                attachment=attachment,
                content_sha256=digest,
            )
            session.add(candidate)
            session.commit()
            session.refresh(candidate)
            return candidate, True
        elif candidate.gitlab_binding_id != binding.id:
            raise PublishBindingConflictError("Attachment is bound to another Issue")
        return candidate, False

    def _validated_upload(self, payload: Mapping[str, Any]) -> tuple[str, str, str]:
        if not isinstance(payload, Mapping):
            raise PublishRemoteResponseError("GitLab upload metadata is invalid")
        upload_id = payload.get("id")
        remote_url = payload.get("full_path") or payload.get("url")
        markdown = payload.get("markdown")
        if (
            isinstance(upload_id, bool)
            or not isinstance(upload_id, (int, str))
            or not str(upload_id)
            or not isinstance(remote_url, str)
            or not remote_url.startswith("/")
            or "\n" in remote_url
            or not isinstance(markdown, str)
            or not markdown.strip()
            or "\n" in markdown
            or "MYOWNTMS:" in markdown
            or len(remote_url) > 1000
            or len(markdown) > 1_000_000
        ):
            raise PublishRemoteResponseError("GitLab upload metadata is invalid")
        return str(upload_id), remote_url, markdown.strip()

    @staticmethod
    def _base_snapshot(bug: BugReport, markdown: tuple[str, ...]) -> str:
        values = GitLabPublishService._validated_bug_values(bug)
        values["attachments"] = list(markdown)
        return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _record_error(
        session: Session, binding: GitLabBinding, error: BaseException
    ) -> None:
        binding.sync_state = "error"
        binding.last_error_type = type(error).__name__[:100]
        status = getattr(error, "status_code", None)
        binding.last_error_http_status = status if isinstance(status, int) else None
        request_id = getattr(error, "request_id", None)
        binding.last_error_request_id = (
            request_id[:255] if isinstance(request_id, str) else None
        )
        session.commit()

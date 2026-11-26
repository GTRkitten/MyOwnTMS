"""Explicit three-way synchronization for published GitLab Issues."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from src.database.models import BugReport, GitLabBinding, GitLabProject
from src.integrations.gitlab_client import (
    GitLabApiClient,
    GitLabClientError,
    GitLabNotFoundError,
)
from src.services.gitlab_issue_codec import (
    PRIORITY_LABELS,
    SEVERITY_LABELS,
    STATUS_LABELS,
    ManagedBlockError,
    ManagedIssueContent,
    managed_labels_for,
    merge_managed_labels,
    parse_managed_document,
    replace_managed_block,
)


SYNC_FIELD_NAMES = (
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
_BASE_KEYS = frozenset((*SYNC_FIELD_NAMES, "attachments"))
_LABEL_GROUPS = {
    "status": STATUS_LABELS,
    "priority": PRIORITY_LABELS,
    "severity": SEVERITY_LABELS,
}
_REVERSE_LABEL_GROUPS = {
    name: {label: value for value, label in mapping.items()}
    for name, mapping in _LABEL_GROUPS.items()
}
_SOURCE_CHANNELS = {"email", "messenger", "phone", "meeting", "other"}


class GitLabSyncError(Exception):
    """Base class for safe synchronization errors."""


class SyncValidationError(GitLabSyncError):
    """The local binding or snapshot cannot be synchronized safely."""


class SyncBaseSnapshotError(SyncValidationError):
    """The last successful base snapshot is absent or malformed."""


class SyncRemoteStateError(GitLabSyncError):
    """The remote Issue violates the managed synchronization contract."""


class SyncPreviewStaleError(GitLabSyncError):
    """Local or remote state changed after the displayed preview."""


class SyncConflictResolutionError(GitLabSyncError):
    """Conflict choices are absent or invalid."""


class SyncVerificationError(GitLabSyncError):
    """The control read after PUT does not match the intended state."""


@dataclass(frozen=True)
class IssueSnapshot:
    title: str
    description: str
    reproduction_steps: str
    expected_result: str
    actual_result: str
    environment: str
    source_channel: str
    external_reference: str
    status: str
    priority: str
    severity: str

    def as_dict(self) -> dict[str, str]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True)
class FieldConflict:
    field: str
    base: str
    local: str
    remote: str


@dataclass(frozen=True)
class MergeResult:
    merged: IssueSnapshot
    local_changes: tuple[str, ...]
    remote_changes: tuple[str, ...]
    conflicts: tuple[FieldConflict, ...]


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
    snapshot: IssueSnapshot
    attachment_markdown: tuple[str, ...]


@dataclass(frozen=True)
class SyncPreview:
    bug_report_id: str
    binding_id: int
    project_id: int
    issue_iid: int
    base: IssueSnapshot
    local: IssueSnapshot
    remote: IssueSnapshot
    merged: IssueSnapshot
    local_changes: tuple[str, ...]
    remote_changes: tuple[str, ...]
    conflicts: tuple[FieldConflict, ...]
    action: str
    sync_state: str
    remote_updated_at: datetime
    _remote_issue: _RemoteIssue


@dataclass(frozen=True)
class SyncResult:
    snapshot: IssueSnapshot
    pushed: bool
    pulled: bool
    sync_state: str
    remote_updated_at: datetime


def _normalize_text(value: Any, field_name: str, maximum: int = 1_000_000) -> str:
    if value is None and field_name in {"source_channel", "external_reference"}:
        return ""
    if not isinstance(value, str):
        raise SyncValidationError(f"{field_name} must be text")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > maximum:
        raise SyncValidationError(f"{field_name} is too long")
    return normalized


def normalize_snapshot(values: Mapping[str, Any]) -> IssueSnapshot:
    """Return a canonical snapshot suitable for deterministic comparison."""

    if not isinstance(values, Mapping):
        raise SyncValidationError("Issue snapshot must be an object")
    limits = {"title": 200, "source_channel": 20, "external_reference": 500}
    normalized = {
        name: _normalize_text(values.get(name), name, limits.get(name, 1_000_000))
        for name in SYNC_FIELD_NAMES
    }
    if any(
        not normalized[name]
        for name in ("title", "reproduction_steps", "expected_result", "actual_result")
    ):
        raise SyncValidationError("Required synchronized Issue fields cannot be empty")
    if normalized["source_channel"] and normalized["source_channel"] not in _SOURCE_CHANNELS:
        raise SyncValidationError("Issue source channel cannot be synchronized")
    if "\n" in normalized["external_reference"]:
        raise SyncValidationError("Issue external reference must be single-line text")
    if normalized["status"] not in STATUS_LABELS or normalized["status"] == "Черновик":
        raise SyncValidationError("Issue status cannot be synchronized")
    if normalized["priority"] not in PRIORITY_LABELS:
        raise SyncValidationError("Issue priority cannot be synchronized")
    if normalized["severity"] not in SEVERITY_LABELS:
        raise SyncValidationError("Issue severity cannot be synchronized")
    return IssueSnapshot(**normalized)


def three_way_merge(
    base: IssueSnapshot,
    local: IssueSnapshot,
    remote: IssueSnapshot,
) -> MergeResult:
    """Merge independent field changes and report same-field conflicts."""

    merged: dict[str, str] = {}
    local_changes: list[str] = []
    remote_changes: list[str] = []
    conflicts: list[FieldConflict] = []
    for name in SYNC_FIELD_NAMES:
        base_value = getattr(base, name)
        local_value = getattr(local, name)
        remote_value = getattr(remote, name)
        local_changed = local_value != base_value
        remote_changed = remote_value != base_value
        if local_changed:
            local_changes.append(name)
        if remote_changed:
            remote_changes.append(name)
        if local_value == remote_value:
            merged[name] = local_value
        elif not local_changed:
            merged[name] = remote_value
        elif not remote_changed:
            merged[name] = local_value
        else:
            merged[name] = base_value
            conflicts.append(
                FieldConflict(name, base_value, local_value, remote_value)
            )
    return MergeResult(
        merged=IssueSnapshot(**merged),
        local_changes=tuple(local_changes),
        remote_changes=tuple(remote_changes),
        conflicts=tuple(conflicts),
    )


def _snapshot_json(snapshot: IssueSnapshot, attachments: tuple[str, ...]) -> str:
    values: dict[str, Any] = snapshot.as_dict()
    values["attachments"] = list(attachments)
    return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _base_snapshot(value: str | None) -> IssueSnapshot:
    if not value:
        raise SyncBaseSnapshotError("The last successful sync snapshot is missing")
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        raise SyncBaseSnapshotError("The last successful sync snapshot is invalid") from None
    if not isinstance(decoded, dict) or set(decoded) != _BASE_KEYS:
        raise SyncBaseSnapshotError("The last successful sync snapshot is invalid")
    attachments = decoded.get("attachments")
    if not isinstance(attachments, list) or not all(
        isinstance(item, str) for item in attachments
    ):
        raise SyncBaseSnapshotError("The last successful sync snapshot is invalid")
    try:
        return normalize_snapshot(decoded)
    except SyncValidationError as error:
        raise SyncBaseSnapshotError("The last successful sync snapshot is invalid") from error


def _local_snapshot(bug: BugReport) -> IssueSnapshot:
    return normalize_snapshot({name: getattr(bug, name) for name in SYNC_FIELD_NAMES})


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 100:
        raise SyncRemoteStateError("GitLab Issue timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SyncRemoteStateError("GitLab Issue timestamp is invalid") from None
    if parsed.tzinfo is None:
        raise SyncRemoteStateError("GitLab Issue timestamp is invalid")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _origin(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if not parsed.scheme or not parsed.hostname:
        return None
    scheme = parsed.scheme.lower()
    return scheme, parsed.hostname.lower(), port or (443 if scheme == "https" else 80)


def _remote_values(labels: tuple[str, ...], state: str) -> dict[str, str]:
    folded = [label.casefold() for label in labels]
    if folded.count("myowntms") != 1:
        raise SyncRemoteStateError("Remote Issue has an invalid myowntms label set")
    values: dict[str, str] = {}
    for group_name, reverse in _REVERSE_LABEL_GROUPS.items():
        prefix = f"myowntms-{group_name}-"
        known = {label.casefold() for label in reverse}
        if any(label.startswith(prefix) and label not in known for label in folded):
            raise SyncRemoteStateError(
                f"Remote Issue has an unknown managed {group_name} label"
            )
        matches = [
            canonical
            for canonical in reverse
            if folded.count(canonical.casefold())
        ]
        if len(matches) != 1 or folded.count(matches[0].casefold()) != 1:
            raise SyncRemoteStateError(
                f"Remote Issue has an invalid managed {group_name} label set"
            )
        values[group_name] = reverse[matches[0]]
    expected_state = "closed" if values["status"] == "Закрыт" else "opened"
    if state != expected_state:
        raise SyncRemoteStateError("Remote Issue state and status label are inconsistent")
    return values


def _resolve_conflicts(
    merge: MergeResult, resolutions: Mapping[str, str] | None
) -> IssueSnapshot:
    choices = dict(resolutions or {})
    conflict_names = {conflict.field for conflict in merge.conflicts}
    if set(choices) != conflict_names or any(
        choice not in {"local", "remote"} for choice in choices.values()
    ):
        raise SyncConflictResolutionError(
            "Every conflict requires one local or remote choice"
        )
    values = merge.merged.as_dict()
    for conflict in merge.conflicts:
        values[conflict.field] = (
            conflict.local if choices[conflict.field] == "local" else conflict.remote
        )
    return IssueSnapshot(**values)


class GitLabSyncService:
    """Builds confirmed sync previews and applies them without silent overwrites."""

    def __init__(self, client: GitLabApiClient) -> None:
        self._client = client

    def preview(self, session: Session, bug_report_id: str) -> SyncPreview:
        bug, binding, project = self._binding(session, bug_report_id)
        base = _base_snapshot(binding.base_snapshot)
        local = _local_snapshot(bug)
        try:
            remote = self._fetch_remote(binding, project)
        except GitLabNotFoundError as error:
            self._record_missing(session, binding, error)
            raise SyncRemoteStateError(
                "The linked GitLab Issue is missing; automatic republish is disabled"
            ) from error
        except (GitLabClientError, GitLabSyncError, ManagedBlockError) as error:
            state = "conflict" if isinstance(error, (SyncRemoteStateError, ManagedBlockError)) else "error"
            self._record_error(session, binding, error, state=state)
            if isinstance(error, GitLabSyncError):
                raise
            if isinstance(error, ManagedBlockError):
                raise SyncRemoteStateError(
                    "Remote managed block is missing, malformed, or unsupported"
                ) from error
            raise

        merge = three_way_merge(base, local, remote.snapshot)
        if merge.conflicts:
            action = "conflict"
            sync_state = "conflict"
        elif merge.local_changes and merge.remote_changes:
            action = "merge"
            sync_state = "local_changed"
        elif merge.local_changes:
            action = "push"
            sync_state = "local_changed"
        elif merge.remote_changes:
            action = "pull"
            sync_state = "remote_changed"
        else:
            action = "none"
            sync_state = "synced"
        binding.sync_state = sync_state
        binding.last_error_type = None
        binding.last_error_http_status = None
        binding.last_error_request_id = None
        session.commit()
        return SyncPreview(
            bug_report_id=bug.id,
            binding_id=binding.id,
            project_id=project.gitlab_project_id,
            issue_iid=binding.issue_iid,
            base=base,
            local=local,
            remote=remote.snapshot,
            merged=merge.merged,
            local_changes=merge.local_changes,
            remote_changes=merge.remote_changes,
            conflicts=merge.conflicts,
            action=action,
            sync_state=sync_state,
            remote_updated_at=remote.updated_at,
            _remote_issue=remote,
        )

    def confirm(
        self,
        session: Session,
        preview: SyncPreview,
        resolutions: Mapping[str, str] | None = None,
    ) -> SyncResult:
        bug, binding, project = self._binding(session, preview.bug_report_id)
        if (
            binding.id != preview.binding_id
            or project.gitlab_project_id != preview.project_id
            or binding.issue_iid != preview.issue_iid
            or _base_snapshot(binding.base_snapshot) != preview.base
            or _local_snapshot(bug) != preview.local
        ):
            raise SyncPreviewStaleError("Local sync state changed after preview")
        try:
            current_remote = self._fetch_remote(binding, project)
        except GitLabNotFoundError as error:
            self._record_missing(session, binding, error)
            raise SyncRemoteStateError(
                "The linked GitLab Issue is missing; automatic republish is disabled"
            ) from error
        except (GitLabClientError, GitLabSyncError, ManagedBlockError) as error:
            state = "conflict" if isinstance(error, (SyncRemoteStateError, ManagedBlockError)) else "error"
            self._record_error(session, binding, error, state=state)
            if isinstance(error, GitLabSyncError):
                raise
            if isinstance(error, ManagedBlockError):
                raise SyncRemoteStateError(
                    "Remote managed block is missing, malformed, or unsupported"
                ) from error
            raise
        if not self._same_remote_revision(current_remote, preview._remote_issue):
            binding.sync_state = "conflict"
            session.commit()
            raise SyncPreviewStaleError("Remote Issue changed after preview")

        merge = three_way_merge(preview.base, preview.local, preview.remote)
        desired = _resolve_conflicts(merge, resolutions)
        pushed = desired != current_remote.snapshot
        verified = current_remote
        if pushed:
            try:
                update_fields = self._update_fields(bug, current_remote, desired)
                if update_fields:
                    put_remote = self._remote_issue(
                        self._client.update_issue(
                            project.gitlab_project_id,
                            binding.issue_iid,
                            **update_fields,
                        ),
                        binding,
                        project,
                    )
                    verified = self._fetch_remote(binding, project)
                    if not self._same_remote_revision(verified, put_remote):
                        raise SyncVerificationError(
                            "GitLab Issue changed during the post-update control read"
                        )
                if verified.snapshot != desired:
                    raise SyncVerificationError(
                        "GitLab Issue does not match the confirmed synchronization result"
                    )
            except GitLabNotFoundError as error:
                self._record_missing(session, binding, error)
                raise SyncRemoteStateError(
                    "The linked GitLab Issue is missing; automatic republish is disabled"
                ) from error
            except (GitLabClientError, GitLabSyncError, ManagedBlockError) as error:
                state = "conflict" if isinstance(
                    error, (SyncRemoteStateError, SyncVerificationError, ManagedBlockError)
                ) else "error"
                self._record_error(session, binding, error, state=state)
                if isinstance(error, GitLabSyncError):
                    raise
                if isinstance(error, ManagedBlockError):
                    raise SyncRemoteStateError(
                        "Remote managed block is missing, malformed, or unsupported"
                    ) from error
                raise

        pulled = desired != preview.local
        self._apply_local(bug, desired)
        binding.remote_updated_at = verified.updated_at
        binding.base_snapshot = _snapshot_json(
            desired, verified.attachment_markdown
        )
        binding.sync_state = "synced"
        binding.last_error_type = None
        binding.last_error_http_status = None
        binding.last_error_request_id = None
        session.commit()
        return SyncResult(
            snapshot=desired,
            pushed=pushed,
            pulled=pulled,
            sync_state="synced",
            remote_updated_at=verified.updated_at,
        )

    @staticmethod
    def _binding(
        session: Session, bug_report_id: str
    ) -> tuple[BugReport, GitLabBinding, GitLabProject]:
        bug = session.get(BugReport, bug_report_id)
        if bug is None:
            raise SyncValidationError("Bug report was not found")
        binding = bug.gitlab_binding
        if binding is None or binding.issue_iid is None or binding.issue_id is None:
            raise SyncValidationError("Bug report is not published")
        project = binding.project
        if project is None or not project.is_active or project.visibility != "private":
            raise SyncValidationError("The bound GitLab project is not active and private")
        return bug, binding, project

    def _fetch_remote(
        self, binding: GitLabBinding, project: GitLabProject
    ) -> _RemoteIssue:
        payload = self._client.get_issue(project.gitlab_project_id, binding.issue_iid)
        return self._remote_issue(payload, binding, project)

    def _remote_issue(
        self,
        payload: Mapping[str, Any],
        binding: GitLabBinding,
        project: GitLabProject,
    ) -> _RemoteIssue:
        if not isinstance(payload, Mapping):
            raise SyncRemoteStateError("GitLab Issue metadata is invalid")
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
            or len(title) > 255
            or not isinstance(description, str)
            or len(description) > 1_000_000
            or not isinstance(labels, list)
            or not all(isinstance(label, str) and len(label) <= 255 for label in labels)
            or state not in {"opened", "closed"}
        ):
            raise SyncRemoteStateError("GitLab Issue metadata is invalid")
        expected_path = f"{urlsplit(project.web_url).path.rstrip('/')}/-/issues/{iid}"
        parsed_url = urlsplit(web_url)
        if (
            issue_id != binding.issue_id
            or iid != binding.issue_iid
            or (binding.issue_web_url is not None and web_url != binding.issue_web_url)
            or _origin(web_url) != _origin(self._client.origin)
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.path.rstrip("/") != expected_path
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise SyncRemoteStateError("GitLab Issue identity is invalid")
        try:
            parsed = parse_managed_document(description)
        except ManagedBlockError:
            raise
        if parsed.content.sync_uid != binding.sync_uid:
            raise SyncRemoteStateError("Remote Issue marker does not match")
        label_values = _remote_values(tuple(labels), state)
        title_prefix = f"[{binding.bug_report_id}] "
        if not title.startswith(title_prefix):
            raise SyncRemoteStateError("Remote Issue title has an invalid bug ID prefix")
        local_title = title[len(title_prefix) :]
        content = parsed.content
        snapshot = normalize_snapshot(
            {
                "title": local_title,
                "description": content.description,
                "reproduction_steps": content.reproduction_steps,
                "expected_result": content.expected_result,
                "actual_result": content.actual_result,
                "environment": content.environment,
                "source_channel": content.source_channel,
                "external_reference": content.external_reference,
                **label_values,
            }
        )
        return _RemoteIssue(
            issue_id=issue_id,
            issue_iid=iid,
            web_url=web_url,
            title=title,
            description=description,
            labels=tuple(labels),
            state=state,
            updated_at=_parse_datetime(payload.get("updated_at")),
            snapshot=snapshot,
            attachment_markdown=content.attachment_markdown,
        )

    @staticmethod
    def _update_fields(
        bug: BugReport, remote: _RemoteIssue, desired: IssueSnapshot
    ) -> dict[str, Any]:
        desired_title = f"[{bug.id}] {desired.title}"
        desired_content = ManagedIssueContent(
            sync_uid=bug.gitlab_binding.sync_uid,
            description=desired.description,
            reproduction_steps=desired.reproduction_steps,
            expected_result=desired.expected_result,
            actual_result=desired.actual_result,
            environment=desired.environment,
            source_channel=desired.source_channel or None,
            external_reference=desired.external_reference or None,
            attachment_markdown=remote.attachment_markdown,
        )
        desired_description = replace_managed_block(remote.description, desired_content)
        desired_labels = merge_managed_labels(
            remote.labels,
            managed_labels_for(desired.status, desired.priority, desired.severity),
        )
        desired_state = "closed" if desired.status == "Закрыт" else "opened"
        update: dict[str, Any] = {}
        if remote.title != desired_title:
            update["title"] = desired_title
        if remote.description != desired_description:
            update["description"] = desired_description
        if {label.casefold() for label in remote.labels} != {
            label.casefold() for label in desired_labels
        }:
            update["labels"] = desired_labels
        if remote.state != desired_state:
            update["state_event"] = "close" if desired_state == "closed" else "reopen"
        return update

    @staticmethod
    def _apply_local(bug: BugReport, snapshot: IssueSnapshot) -> None:
        for name, value in snapshot.as_dict().items():
            if name in {"source_channel", "external_reference"}:
                value = value or None
            setattr(bug, name, value)

    @staticmethod
    def _same_remote_revision(left: _RemoteIssue, right: _RemoteIssue) -> bool:
        """Compare one Issue revision while ignoring GitLab label ordering."""

        return (
            left.issue_id == right.issue_id
            and left.issue_iid == right.issue_iid
            and left.web_url == right.web_url
            and left.title == right.title
            and left.description == right.description
            and {label.casefold() for label in left.labels}
            == {label.casefold() for label in right.labels}
            and left.state == right.state
            and left.updated_at == right.updated_at
            and left.snapshot == right.snapshot
            and left.attachment_markdown == right.attachment_markdown
        )

    @staticmethod
    def _record_missing(
        session: Session, binding: GitLabBinding, error: GitLabNotFoundError
    ) -> None:
        GitLabSyncService._record_error(session, binding, error, state="remote_missing")

    @staticmethod
    def _record_error(
        session: Session,
        binding: GitLabBinding,
        error: BaseException,
        *,
        state: str,
    ) -> None:
        binding.sync_state = state
        binding.last_error_type = type(error).__name__[:100]
        status = getattr(error, "status_code", None)
        binding.last_error_http_status = status if isinstance(status, int) else None
        request_id = getattr(error, "request_id", None)
        binding.last_error_request_id = request_id[:255] if isinstance(request_id, str) else None
        session.commit()

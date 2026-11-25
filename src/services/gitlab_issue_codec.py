"""Pure GitLab Issue managed-block and managed-label transformations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence
from uuid import UUID


MANAGED_BLOCK_VERSION = 1

_BEGIN_RE = re.compile(
    r"^<!-- MYOWNTMS:BEGIN version=(?P<version>[0-9]+) "
    r"sync_uid=(?P<sync_uid>[0-9a-fA-F-]{36}) -->$",
    re.MULTILINE,
)
_END_RE = re.compile(r"^<!-- MYOWNTMS:END -->$", re.MULTILINE)
_SECTION_NAMES = (
    "Описание",
    "Шаги воспроизведения",
    "Ожидаемый результат",
    "Фактический результат",
    "Окружение",
    "Источник",
    "Вложения",
)
_SECTION_HEADINGS = tuple(f"## {name}" for name in _SECTION_NAMES)
_RESERVED_LINES = frozenset((*_SECTION_HEADINGS, "<!-- MYOWNTMS:END -->"))

STATUS_LABELS = {
    "Новый": "myowntms-status-new",
    "В работе": "myowntms-status-in-progress",
    "Проверен": "myowntms-status-verified",
    "Закрыт": "myowntms-status-closed",
}
PRIORITY_LABELS = {
    "Критический": "myowntms-priority-critical",
    "Высокий": "myowntms-priority-high",
    "Средний": "myowntms-priority-medium",
    "Низкий": "myowntms-priority-low",
}
SEVERITY_LABELS = {
    "Критический": "myowntms-severity-critical",
    "Мажорный": "myowntms-severity-major",
    "Минорный": "myowntms-severity-minor",
    "Тривиальный": "myowntms-severity-trivial",
}
MANAGED_LABEL_NAMES = frozenset(
    {
        "myowntms",
        *STATUS_LABELS.values(),
        *PRIORITY_LABELS.values(),
        *SEVERITY_LABELS.values(),
    }
)
_MANAGED_LABEL_CASEFOLDS = frozenset(
    label.casefold() for label in MANAGED_LABEL_NAMES
)


class ManagedBlockError(ValueError):
    """The remote description cannot be transformed safely."""


class ManagedBlockMissingError(ManagedBlockError):
    """No managed block exists in the description."""


class ManagedBlockFormatError(ManagedBlockError):
    """The managed block is duplicated or malformed."""


class ManagedBlockVersionError(ManagedBlockError):
    """The managed block version is unsupported."""


class ManagedLabelValueError(ValueError):
    """A local enum value has no managed GitLab label mapping."""


@dataclass(frozen=True)
class ManagedIssueContent:
    sync_uid: str
    description: str
    reproduction_steps: str
    expected_result: str
    actual_result: str
    environment: str
    source_channel: str | None = None
    external_reference: str | None = None
    attachment_markdown: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedManagedDocument:
    content: ManagedIssueContent
    prefix: str
    suffix: str
    block: str


def _normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise ManagedBlockFormatError("Managed field must be text")
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _is_reserved_line(value: str) -> bool:
    return value in _RESERVED_LINES or _BEGIN_RE.fullmatch(value) is not None


def _has_reserved_payload(value: str) -> bool:
    return _is_reserved_line(value.lstrip("\\"))


def _escape_section_text(value: str) -> str:
    lines = _normalize_text(value).split("\n")
    return "\n".join(
        f"\\{line}"
        if _has_reserved_payload(line)
        else line
        for line in lines
    )


def _unescape_section_text(value: str) -> str:
    lines = value.split("\n")
    return "\n".join(
        line[1:]
        if line.startswith("\\")
        and _has_reserved_payload(line[1:])
        else line
        for line in lines
    ).strip()


def _validated_sync_uid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise ManagedBlockFormatError("Managed sync_uid is invalid") from None
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ManagedBlockFormatError("Managed sync_uid must be a canonical UUID4")
    return str(parsed)


def _source_text(content: ManagedIssueContent) -> str:
    channel = _normalize_text(content.source_channel or "")
    reference = _normalize_text(content.external_reference or "")
    if "\n" in channel or "\n" in reference:
        raise ManagedBlockFormatError("Source metadata must be single-line text")
    return f"Канал: {channel}\nВнешняя ссылка: {reference}"


def serialize_managed_block(content: ManagedIssueContent) -> str:
    """Serialize one canonical versioned block without any surrounding text."""

    sync_uid = _validated_sync_uid(content.sync_uid)
    markdown_lines = []
    for value in content.attachment_markdown:
        normalized = _normalize_text(value)
        if not normalized or "\n" in normalized or "MYOWNTMS:" in normalized:
            raise ManagedBlockFormatError("Attachment Markdown is invalid")
        markdown_lines.append(normalized)

    sections = (
        content.description,
        content.reproduction_steps,
        content.expected_result,
        content.actual_result,
        content.environment,
        _source_text(content),
        "\n".join(markdown_lines),
    )
    lines = [
        f"<!-- MYOWNTMS:BEGIN version={MANAGED_BLOCK_VERSION} "
        f"sync_uid={sync_uid} -->"
    ]
    for heading, value in zip(_SECTION_HEADINGS, sections):
        lines.extend((heading, _escape_section_text(value)))
    lines.append("<!-- MYOWNTMS:END -->")
    return "\n".join(lines)


def parse_managed_document(description: str) -> ParsedManagedDocument:
    """Parse exactly one known managed block and retain all outside text."""

    if not isinstance(description, str):
        raise ManagedBlockFormatError("Issue description must be text")
    if description.count("<!-- MYOWNTMS:BEGIN") != 1:
        raise ManagedBlockFormatError("Managed block must occur exactly once")
    if description.count("<!-- MYOWNTMS:END") != 1:
        raise ManagedBlockFormatError("Managed block must occur exactly once")
    begin_matches = list(_BEGIN_RE.finditer(description))
    end_matches = list(_END_RE.finditer(description))
    if not begin_matches and not end_matches:
        raise ManagedBlockMissingError("Managed block is missing")
    if len(begin_matches) != 1 or len(end_matches) != 1:
        raise ManagedBlockFormatError("Managed block must occur exactly once")
    begin = begin_matches[0]
    end = end_matches[0]
    if end.start() <= begin.end():
        raise ManagedBlockFormatError("Managed block boundaries are invalid")
    version = int(begin.group("version"))
    if version != MANAGED_BLOCK_VERSION:
        raise ManagedBlockVersionError("Managed block version is unsupported")
    sync_uid = _validated_sync_uid(begin.group("sync_uid"))

    body_start = begin.end()
    if description[body_start : body_start + 1] != "\n":
        raise ManagedBlockFormatError("Managed block layout is invalid")
    body = description[body_start + 1 : end.start()]
    if body.endswith("\n"):
        body = body[:-1]

    positions = []
    cursor = 0
    for heading in _SECTION_HEADINGS:
        token = f"{heading}\n"
        if not body.startswith(token, cursor):
            raise ManagedBlockFormatError("Managed block sections are invalid")
        value_start = cursor + len(token)
        positions.append(value_start)
        cursor = value_start
        if heading != _SECTION_HEADINGS[-1]:
            next_heading = _SECTION_HEADINGS[len(positions)]
            marker = f"\n{next_heading}\n"
            next_position = body.find(marker, cursor)
            if next_position < 0:
                raise ManagedBlockFormatError("Managed block sections are invalid")
            cursor = next_position + 1

    values = []
    for index, value_start in enumerate(positions):
        if index + 1 < len(positions):
            value_end = positions[index + 1] - len(_SECTION_HEADINGS[index + 1]) - 2
        else:
            value_end = len(body)
        values.append(_unescape_section_text(body[value_start:value_end]))

    source_lines = values[5].split("\n")
    if (
        len(source_lines) != 2
        or not source_lines[0].startswith("Канал: ")
        or not source_lines[1].startswith("Внешняя ссылка: ")
    ):
        raise ManagedBlockFormatError("Managed source metadata is invalid")
    channel = source_lines[0][len("Канал: ") :] or None
    reference = source_lines[1][len("Внешняя ссылка: ") :] or None
    attachments = tuple(line for line in values[6].split("\n") if line)
    block = description[begin.start() : end.end()]
    return ParsedManagedDocument(
        content=ManagedIssueContent(
            sync_uid=sync_uid,
            description=values[0],
            reproduction_steps=values[1],
            expected_result=values[2],
            actual_result=values[3],
            environment=values[4],
            source_channel=channel,
            external_reference=reference,
            attachment_markdown=attachments,
        ),
        prefix=description[: begin.start()],
        suffix=description[end.end() :],
        block=block,
    )


def replace_managed_block(description: str, content: ManagedIssueContent) -> str:
    """Replace only the managed block, preserving surrounding text byte-for-byte."""

    parsed = parse_managed_document(description)
    if parsed.content.sync_uid != _validated_sync_uid(content.sync_uid):
        raise ManagedBlockFormatError("Managed sync_uid cannot be changed")
    return f"{parsed.prefix}{serialize_managed_block(content)}{parsed.suffix}"


def managed_labels_for(status: str, priority: str, severity: str) -> tuple[str, ...]:
    try:
        return (
            "myowntms",
            STATUS_LABELS[status],
            PRIORITY_LABELS[priority],
            SEVERITY_LABELS[severity],
        )
    except KeyError as error:
        raise ManagedLabelValueError(
            f"Unsupported managed label value: {error.args[0]}"
        ) from None


def merge_managed_labels(
    existing: Iterable[str], desired_managed: Sequence[str]
) -> tuple[str, ...]:
    """Keep unmanaged labels in order and append one canonical managed set."""

    desired = tuple(desired_managed)
    if set(desired) - MANAGED_LABEL_NAMES or len(desired) != len(set(desired)):
        raise ManagedLabelValueError("Desired managed labels are invalid")
    unmanaged = []
    seen = set()
    for label in existing:
        if not isinstance(label, str):
            raise ManagedLabelValueError("Remote label name must be text")
        folded = label.casefold()
        if folded in _MANAGED_LABEL_CASEFOLDS or folded in seen:
            continue
        unmanaged.append(label)
        seen.add(folded)
    return tuple((*unmanaged, *desired))

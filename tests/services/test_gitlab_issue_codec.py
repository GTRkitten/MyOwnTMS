import pytest

from src.services.gitlab_issue_codec import (
    ManagedBlockFormatError,
    ManagedBlockVersionError,
    ManagedIssueContent,
    managed_labels_for,
    merge_managed_labels,
    parse_managed_document,
    replace_managed_block,
    serialize_managed_block,
)


SYNC_UID = "00000000-0000-4000-8000-000000000004"


def _content(**overrides):
    values = {
        "sync_uid": SYNC_UID,
        "description": "Описание\n## Шаги воспроизведения\n\\## Окружение",
        "reproduction_steps": "1. Открыть",
        "expected_result": "Работает",
        "actual_result": "Ошибка",
        "environment": "Windows 11",
        "source_channel": "email",
        "external_reference": "REQ-42",
        "attachment_markdown": ("![screen](/uploads/a/screen.png)",),
    }
    values.update(overrides)
    return ManagedIssueContent(**values)


def test_managed_block_round_trip_and_outside_text_are_preserved():
    block = serialize_managed_block(_content())
    document = f"Текст команды до блока\n\n{block}\n\nТекст после блока"

    parsed = parse_managed_document(document)
    changed = replace_managed_block(
        document, _content(actual_result="Новая ошибка")
    )

    assert parsed.content == _content()
    assert parsed.prefix == "Текст команды до блока\n\n"
    assert parsed.suffix == "\n\nТекст после блока"
    assert changed.startswith(parsed.prefix)
    assert changed.endswith(parsed.suffix)
    assert parse_managed_document(changed).content.actual_result == "Новая ошибка"


def test_parser_fails_closed_for_duplicates_unknown_version_and_uid_change():
    block = serialize_managed_block(_content())
    with pytest.raises(ManagedBlockFormatError):
        parse_managed_document(f"{block}\n{block}")
    with pytest.raises(ManagedBlockVersionError):
        parse_managed_document(block.replace("version=1", "version=2"))
    with pytest.raises(ManagedBlockFormatError, match="cannot be changed"):
        replace_managed_block(
            block,
            _content(sync_uid="00000000-0000-4000-8000-000000000005"),
        )


def test_managed_label_mapping_replaces_only_managed_labels():
    desired = managed_labels_for("Новый", "Высокий", "Мажорный")
    merged = merge_managed_labels(
        (
            "customer-label",
            "myowntms-status-closed",
            "MYOWNTMS-PRIORITY-LOW",
            "customer-label",
        ),
        desired,
    )

    assert merged == ("customer-label", *desired)

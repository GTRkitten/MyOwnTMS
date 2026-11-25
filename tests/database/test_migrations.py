import sqlite3

import pytest

from src.database.migrations import Migration, run_migrations


LEGACY_SCHEMA = """
CREATE TABLE test_cases (
    id VARCHAR(20) PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    preconditions TEXT,
    steps TEXT NOT NULL,
    expected_result TEXT NOT NULL,
    postconditions TEXT,
    environment TEXT,
    priority VARCHAR(20),
    status VARCHAR(30),
    created_at DATETIME NOT NULL,
    updated_at DATETIME
);
CREATE TABLE bug_reports (
    id VARCHAR(20) PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    reproduction_steps TEXT NOT NULL,
    expected_result TEXT NOT NULL,
    actual_result TEXT NOT NULL,
    environment TEXT,
    priority VARCHAR(20),
    severity VARCHAR(20),
    status VARCHAR(30),
    created_at DATETIME NOT NULL,
    updated_at DATETIME
);
CREATE TABLE attachments (
    id INTEGER PRIMARY KEY,
    artifact_id VARCHAR(20) NOT NULL,
    artifact_type VARCHAR(10) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_name VARCHAR(200) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    created_at DATETIME,
    test_case_id VARCHAR(20),
    bug_report_id VARCHAR(20)
);
CREATE TABLE artifact_links (
    id INTEGER PRIMARY KEY,
    source_id VARCHAR(20) NOT NULL,
    source_type VARCHAR(10) NOT NULL,
    target_id VARCHAR(20) NOT NULL,
    target_type VARCHAR(10) NOT NULL,
    link_type VARCHAR(50),
    created_at DATETIME
);
"""


def _create_legacy_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO test_cases VALUES "
            "('TC-010125-001', 'Legacy test', '', 'Step', 'Expected', '', '', "
            "'Средний', 'Готов', '2025-01-01', '2025-01-01')"
        )
        connection.execute(
            "INSERT INTO bug_reports VALUES "
            "('BUG-010125-001', 'Legacy bug', 'Description', 'Step', "
            "'Expected', 'Actual', '', 'Высокий', 'Мажорный', 'Новый', "
            "'2025-01-01', '2025-01-01')"
        )
        connection.execute(
            "INSERT INTO attachments VALUES "
            "(1, 'BUG-010125-001', 'bug_report', 'legacy.png', 'legacy.png', "
            "'image/png', '2025-01-01', NULL, 'BUG-010125-001')"
        )
        connection.execute(
            "INSERT INTO artifact_links VALUES "
            "(1, 'BUG-010125-001', 'bug_report', 'TC-010125-001', "
            "'test_case', 'related', '2025-01-01')"
        )


def _tables(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def test_migrates_legacy_database_with_backup_and_preserves_rows(tmp_path):
    database_path = tmp_path / "legacy.db"
    _create_legacy_database(database_path)

    result = run_migrations(database_path)

    assert result.applied == ("0001_gitlab_v1_1_schema",)
    assert result.backup_path is not None
    assert result.backup_path.exists()

    with sqlite3.connect(result.backup_path) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert backup.execute("SELECT title FROM bug_reports").fetchone() == (
            "Legacy bug",
        )
        assert "schema_migrations" not in _tables(backup)

    with sqlite3.connect(database_path) as migrated:
        assert migrated.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert migrated.execute("SELECT COUNT(*) FROM test_cases").fetchone() == (1,)
        assert migrated.execute("SELECT COUNT(*) FROM bug_reports").fetchone() == (1,)
        assert migrated.execute("SELECT COUNT(*) FROM attachments").fetchone() == (1,)
        assert migrated.execute("SELECT COUNT(*) FROM artifact_links").fetchone() == (1,)
        assert {
            "gitlab_projects",
            "gitlab_bindings",
            "gitlab_attachment_bindings",
            "schema_migrations",
        }.issubset(_tables(migrated))
        bug_columns = {
            row[1] for row in migrated.execute("PRAGMA table_info(bug_reports)")
        }
        assert {
            "source_channel",
            "external_reference",
            "gitlab_project_id",
        }.issubset(bug_columns)


def test_creates_new_empty_database_and_supports_draft_status(tmp_path):
    database_path = tmp_path / "new.db"

    run_migrations(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO bug_reports (
                id, title, description, reproduction_steps, expected_result,
                actual_result, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "BUG-010125-001",
                "Draft bug",
                "Raw customer message",
                "",
                "",
                "",
                "Черновик",
                "2025-01-01",
            ),
        )
        assert connection.execute(
            "SELECT status FROM bug_reports"
        ).fetchone() == ("Черновик",)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_second_run_is_idempotent_and_does_not_create_another_backup(tmp_path):
    database_path = tmp_path / "repeat.db"
    first = run_migrations(database_path)
    backups_after_first = set(tmp_path.glob("repeat.db.backup-*"))

    second = run_migrations(database_path)

    assert first.backup_path in backups_after_first
    assert second.applied == ()
    assert second.backup_path is None
    assert set(tmp_path.glob("repeat.db.backup-*")) == backups_after_first
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone() == (1,)


def test_failure_rolls_back_and_leaves_recoverable_backup(tmp_path):
    database_path = tmp_path / "failure.db"
    _create_legacy_database(database_path)

    def fail_after_write(connection):
        connection.execute("CREATE TABLE should_be_rolled_back (id INTEGER)")
        raise RuntimeError("forced migration failure")

    registry = (
        Migration("0001_failure", fail_after_write),
    )

    with pytest.raises(RuntimeError, match="forced migration failure"):
        run_migrations(database_path, registry=registry)

    backups = list(tmp_path.glob("failure.db.backup-*"))
    assert len(backups) == 1
    with sqlite3.connect(database_path) as original:
        assert "should_be_rolled_back" not in _tables(original)
        assert "schema_migrations" not in _tables(original)
        assert original.execute("SELECT title FROM bug_reports").fetchone() == (
            "Legacy bug",
        )
        assert original.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT title FROM bug_reports").fetchone() == (
            "Legacy bug",
        )
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)

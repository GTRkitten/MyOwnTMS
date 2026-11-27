"""Embedded, transactional SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence


MigrationCallable = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    """One ordered database migration."""

    migration_id: str
    apply: MigrationCallable


@dataclass(frozen=True)
class MigrationResult:
    """Summary returned to startup code and tests."""

    applied: tuple[str, ...]
    backup_path: Path | None


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table_name}")')
    }


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if column_name not in _table_columns(connection, table_name):
        connection.execute(
            f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'
        )


def _create_local_and_gitlab_schema(connection: sqlite3.Connection) -> None:
    """Create a new database or upgrade the unversioned v1.0 schema."""

    statements = (
        """
        CREATE TABLE IF NOT EXISTS test_cases (
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
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bug_reports (
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
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY,
            artifact_id VARCHAR(20) NOT NULL,
            artifact_type VARCHAR(10) NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            file_name VARCHAR(200) NOT NULL,
            file_type VARCHAR(50) NOT NULL,
            created_at DATETIME,
            test_case_id VARCHAR(20) REFERENCES test_cases(id) ON DELETE CASCADE,
            bug_report_id VARCHAR(20) REFERENCES bug_reports(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS artifact_links (
            id INTEGER PRIMARY KEY,
            source_id VARCHAR(20) NOT NULL,
            source_type VARCHAR(10) NOT NULL,
            target_id VARCHAR(20) NOT NULL,
            target_type VARCHAR(10) NOT NULL,
            link_type VARCHAR(50),
            created_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS gitlab_projects (
            id INTEGER PRIMARY KEY,
            display_name VARCHAR(200) NOT NULL,
            gitlab_project_id INTEGER NOT NULL UNIQUE,
            path_with_namespace VARCHAR(500) NOT NULL,
            web_url VARCHAR(1000) NOT NULL,
            visibility VARCHAR(20) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            labels_ready_at DATETIME,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS gitlab_bindings (
            id INTEGER PRIMARY KEY,
            bug_report_id VARCHAR(20) NOT NULL UNIQUE
                REFERENCES bug_reports(id) ON DELETE CASCADE,
            sync_uid VARCHAR(36) NOT NULL UNIQUE,
            project_id INTEGER NOT NULL REFERENCES gitlab_projects(id),
            issue_id INTEGER,
            issue_iid INTEGER,
            issue_web_url VARCHAR(1000),
            remote_updated_at DATETIME,
            base_snapshot TEXT,
            sync_state VARCHAR(30) NOT NULL DEFAULT 'local_only',
            last_error_type VARCHAR(100),
            last_error_http_status INTEGER,
            last_error_request_id VARCHAR(255),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS gitlab_attachment_bindings (
            id INTEGER PRIMARY KEY,
            gitlab_binding_id INTEGER NOT NULL
                REFERENCES gitlab_bindings(id) ON DELETE CASCADE,
            attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            content_sha256 VARCHAR(64) NOT NULL,
            remote_upload_id VARCHAR(255),
            remote_url VARCHAR(1000),
            remote_markdown TEXT,
            uploaded_at DATETIME,
            UNIQUE (attachment_id, content_sha256)
        )
        """,
    )
    for statement in statements:
        connection.execute(statement)

    _add_column_if_missing(
        connection, "bug_reports", "source_channel", "VARCHAR(20)"
    )
    _add_column_if_missing(
        connection, "bug_reports", "external_reference", "VARCHAR(500)"
    )
    _add_column_if_missing(
        connection,
        "bug_reports",
        "gitlab_project_id",
        "INTEGER REFERENCES gitlab_projects(id)",
    )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_gitlab_bindings_project_id "
        "ON gitlab_bindings(project_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_gitlab_attachment_bindings_binding_id "
        "ON gitlab_attachment_bindings(gitlab_binding_id)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration("0001_gitlab_v1_1_schema", _create_local_and_gitlab_schema),
)


def _validate_registry(registry: Sequence[Migration]) -> None:
    identifiers = [migration.migration_id for migration in registry]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Migration identifiers must be unique")
    if identifiers != sorted(identifiers):
        raise ValueError("Migrations must be ordered by identifier")


def _applied_migrations(connection: sqlite3.Connection) -> set[str]:
    table_exists = connection.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if not table_exists:
        return set()
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT migration_id FROM schema_migrations"
        ).fetchall()
    }


def _assert_integrity(connection: sqlite3.Connection) -> None:
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    messages = [str(row[0]) for row in rows]
    if messages != ["ok"]:
        raise RuntimeError("SQLite integrity_check failed")


def _backup_database(database_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = database_path.with_name(f"{database_path.name}.backup-{timestamp}")

    with sqlite3.connect(database_path) as source:
        with sqlite3.connect(backup_path) as destination:
            source.backup(destination)
            _assert_integrity(destination)
    return backup_path


def run_migrations(
    database_path: Path | str,
    registry: Iterable[Migration] = MIGRATIONS,
) -> MigrationResult:
    """Apply pending migrations atomically after making a SQLite backup."""

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered_registry = tuple(registry)
    _validate_registry(ordered_registry)

    with sqlite3.connect(path) as inspection_connection:
        applied = _applied_migrations(inspection_connection)
    pending = [
        migration
        for migration in ordered_registry
        if migration.migration_id not in applied
    ]
    if not pending:
        with sqlite3.connect(path) as connection:
            _assert_integrity(connection)
        return MigrationResult(applied=(), backup_path=None)

    backup_path = _backup_database(path)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_id VARCHAR(100) PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
            """
        )
        for migration in pending:
            migration.apply(connection)
            connection.execute(
                "INSERT INTO schema_migrations (migration_id, applied_at) "
                "VALUES (?, ?)",
                (
                    migration.migration_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        _assert_integrity(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return MigrationResult(
        applied=tuple(migration.migration_id for migration in pending),
        backup_path=backup_path,
    )

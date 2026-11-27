def test_migrated_schema_accepts_planned_sqlalchemy_models():
    from src.database.models import (
        BugReport,
        GitLabBinding,
        GitLabProject,
        SchemaMigration,
    )
    from src.database.session import get_session, init_database

    result = init_database()
    assert result.applied == ("0001_gitlab_v1_1_schema",)

    session = get_session()
    try:
        project = GitLabProject(
            display_name="Isolated test project",
            gitlab_project_id=101,
            path_with_namespace="tests/project",
            web_url="https://gitlab.test/tests/project",
            visibility="private",
        )
        bug = BugReport(
            id="BUG-010125-001",
            title="Draft bug",
            description="Raw message",
            reproduction_steps="",
            expected_result="",
            actual_result="",
            priority="Средний",
            severity="Мажорный",
            status="Черновик",
            source_channel="messenger",
            external_reference="internal-101",
            gitlab_project=project,
        )
        binding = GitLabBinding(
            bug_report=bug,
            project=project,
            sync_uid="00000000-0000-4000-8000-000000000001",
        )
        session.add(binding)
        session.commit()

        stored = session.get(BugReport, "BUG-010125-001")
        assert stored is not None
        assert stored.status == "Черновик"
        assert stored.gitlab_binding.sync_state == "local_only"
        assert session.query(SchemaMigration).count() == 1
    finally:
        session.rollback()
        session.close()

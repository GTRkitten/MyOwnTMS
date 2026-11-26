"""Focused pytest-qt coverage for TASK-GL-006 GUI boundaries."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import QDialog, QMessageBox
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, BugReport, GitLabBinding, GitLabProject
from src.gui.gitlab_controller import GitLabSessionController
from src.gui.main_window import MainWindow
from src.gui.widgets.bug_report_dialog import BugReportDialog
from src.gui.widgets.gitlab_settings_dialog import GitLabSettingsDialog
from src.gui.widgets.gitlab_sync_dialogs import ConflictResolutionDialog


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


@pytest.fixture(autouse=True)
def no_message_boxes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)


class _ImmediateController:
    """Synchronous test double; production scheduling is covered separately."""

    def __init__(self, session):
        self.session = session
        self.origin = "https://gitlab.internal"
        self.ca_bundle = ""
        self.token_is_set = True
        self.calls = 0

    def require_ready(self):
        return None

    def start(self, operation, *, succeeded=None, failed=None, finished=None):
        self.calls += 1
        try:
            result = operation(self.session, object())
        except BaseException as error:
            if finished:
                finished()
            if failed:
                failed(error)
        else:
            if finished:
                finished()
            if succeeded:
                succeeded(result)
        return SimpleNamespace()

    def shutdown(self):
        return None


def _project(session):
    project = GitLabProject(
        display_name="Customer",
        gitlab_project_id=17,
        path_with_namespace="customer/app",
        web_url="https://gitlab.internal/customer/app",
        visibility="private",
    )
    session.add(project)
    session.commit()
    return project


def _bug(session, project, *, status="Новый"):
    bug = BugReport(
        id="BUG-251126-001",
        title="Broken checkout",
        description="Details",
        reproduction_steps="1. Open checkout",
        expected_result="Checkout opens",
        actual_result="Error is shown",
        environment="Windows",
        priority="Высокий",
        severity="Мажорный",
        status=status,
        source_channel="email",
        external_reference="REQ-17",
        gitlab_project=project,
    )
    session.add(bug)
    session.commit()
    return bug


def test_incomplete_draft_is_saved_locally_without_network(qtbot, session):
    controller = _ImmediateController(session)
    dialog = BugReportDialog(session, gitlab_controller=controller)
    qtbot.addWidget(dialog)
    dialog.title_input.setText("Сообщение заказчика")
    dialog.status_combo.setCurrentText("Черновик")

    qtbot.mouseClick(dialog.save_btn, Qt.MouseButton.LeftButton)

    stored = session.query(BugReport).one()
    assert stored.status == "Черновик"
    assert stored.reproduction_steps == ""
    assert controller.calls == 0


def test_publish_requires_preview_and_disables_duplicate_start(
    qtbot, session, monkeypatch
):
    project = _project(session)
    bug = _bug(session, project)
    controller = _ImmediateController(session)
    calls = []

    class FakePublishService:
        def __init__(self, client):
            pass

        def preview(self, worker_session, bug_report_id):
            calls.append("preview")
            return SimpleNamespace(bug_report_id=bug_report_id)

        def publish(self, worker_session, bug_report_id, preview):
            calls.append("publish")
            return SimpleNamespace(issue_iid=42)

    class AcceptedPreview:
        def __init__(self, preview, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "src.gui.widgets.bug_report_dialog.GitLabPublishService", FakePublishService
    )
    monkeypatch.setattr(
        "src.gui.widgets.bug_report_dialog.PublishPreviewDialog", AcceptedPreview
    )
    dialog = BugReportDialog(
        session, bug.id, gitlab_controller=controller
    )
    qtbot.addWidget(dialog)

    dialog.preview_publish()

    assert calls == ["preview", "publish"]
    assert controller.calls == 2
    assert not dialog._network_busy


def test_sync_conflict_requires_per_field_resolution(qtbot, session, monkeypatch):
    project = _project(session)
    bug = _bug(session, project)
    binding = GitLabBinding(
        bug_report=bug,
        project=project,
        sync_uid="00000000-0000-4000-8000-000000000099",
        issue_id=100,
        issue_iid=7,
        issue_web_url="https://gitlab.internal/customer/app/-/issues/7",
        sync_state="conflict",
    )
    session.add(binding)
    session.commit()
    controller = _ImmediateController(session)
    captured = {}
    preview = SimpleNamespace(
        bug_report_id=bug.id,
        action="conflict",
        conflicts=(SimpleNamespace(field="title"),),
    )

    class FakeSyncService:
        def __init__(self, client):
            pass

        def preview(self, worker_session, bug_report_id):
            return preview

        def confirm(self, worker_session, received_preview, resolutions):
            captured.update(resolutions)
            return SimpleNamespace(sync_state="synced")

    class AcceptedConflict:
        resolutions = {"title": "remote"}

        def __init__(self, received_preview, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "src.gui.widgets.bug_report_dialog.GitLabSyncService", FakeSyncService
    )
    monkeypatch.setattr(
        "src.gui.widgets.bug_report_dialog.ConflictResolutionDialog", AcceptedConflict
    )
    dialog = BugReportDialog(session, bug.id, gitlab_controller=controller)
    qtbot.addWidget(dialog)

    dialog.preview_sync()

    assert captured == {"title": "remote"}
    assert controller.calls == 2


def test_conflict_dialog_requires_choice_for_every_field(qtbot):
    preview = SimpleNamespace(
        conflicts=(
            SimpleNamespace(
                field="title",
                base="Base title",
                local="Local title",
                remote="Remote title",
            ),
            SimpleNamespace(
                field="status",
                base="Новый",
                local="В работе",
                remote="Закрыт",
            ),
        )
    )
    dialog = ConflictResolutionDialog(preview)
    qtbot.addWidget(dialog)

    dialog._validate_and_accept()
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog._selectors["title"].setCurrentIndex(1)
    dialog._selectors["status"].setCurrentIndex(2)
    dialog._validate_and_accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.resolutions == {"title": "local", "status": "remote"}


def test_main_window_blocks_delete_for_published_bug(qtbot, session, monkeypatch):
    project = _project(session)
    bug = _bug(session, project)
    session.add(
        GitLabBinding(
            bug_report=bug,
            project=project,
            sync_uid="00000000-0000-4000-8000-000000000100",
            issue_id=100,
            issue_iid=8,
            issue_web_url="https://gitlab.internal/customer/app/-/issues/8",
            sync_state="synced",
        )
    )
    session.commit()
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[2]),
    )
    window = MainWindow(session=session, gitlab_controller=_ImmediateController(session))
    qtbot.addWidget(window)
    window.tabs.setCurrentIndex(1)
    window.bug_reports_table.selectRow(0)

    window.delete_artifact()

    assert session.get(BugReport, bug.id) is not None
    assert warnings and "нельзя удалить" in warnings[-1]


def test_settings_keep_origin_ca_and_token_in_runtime_only(qtbot, session):
    controller = GitLabSessionController(session_factory=lambda: session)
    dialog = GitLabSettingsDialog(session, controller)
    qtbot.addWidget(dialog)
    dialog.origin_input.setText("https://gitlab.internal")
    dialog.token_input.setText("session-test-token")

    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)

    assert controller.origin == "https://gitlab.internal"
    assert controller.token_is_set
    assert dialog.token_input.text() == ""
    assert "token" not in GitLabProject.__table__.columns
    controller.shutdown()


class _DummyClient:
    def close(self):
        pass


class _DummySession:
    def rollback(self):
        pass

    def close(self):
        pass


def test_controller_runs_operation_outside_gui_thread(qtbot):
    controller = GitLabSessionController(
        session_factory=_DummySession,
        client_factory=lambda config, token: _DummyClient(),
    )
    controller.configure("https://gitlab.internal")
    controller.set_token("session-test-token")
    gui_thread_id = threading.get_ident()
    release = threading.Event()

    def operation(session, client):
        release.wait(2)
        return threading.get_ident()

    worker = controller.start(operation)

    with qtbot.waitSignal(worker.signals.succeeded, timeout=3000) as blocker:
        release.set()
    assert blocker.args[0] != gui_thread_id
    controller.shutdown()


def test_controller_shutdown_waits_for_running_worker(qtbot):
    controller = GitLabSessionController(
        session_factory=_DummySession,
        client_factory=lambda config, token: _DummyClient(),
    )
    controller.configure("https://gitlab.internal")
    controller.set_token("session-test-token")
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def operation(session, client):
        started.set()
        release.wait(2)
        completed.set()

    controller.start(operation)
    assert started.wait(1)
    release_timer = threading.Timer(0.1, release.set)
    release_timer.start()
    try:
        controller.shutdown()
    finally:
        release_timer.cancel()

    assert completed.is_set()
    assert not controller.is_busy
    assert not controller.token_is_set


def test_worker_does_not_deliver_result_to_destroyed_widget(qtbot):
    controller = GitLabSessionController(
        session_factory=_DummySession,
        client_factory=lambda config, token: _DummyClient(),
    )
    controller.configure("https://gitlab.internal")
    controller.set_token("session-test-token")
    release = threading.Event()

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.results = []

        @Slot(object)
        def receive(self, value):
            self.results.append(value)

    receiver = Receiver()

    def operation(session, client):
        release.wait(2)
        return "late result"

    worker = controller.start(operation, succeeded=receiver.receive)
    receiver.deleteLater()
    qtbot.wait(20)
    with qtbot.waitSignal(worker.signals.finished, timeout=3000):
        release.set()
    qtbot.wait(20)

    assert receiver.results == []
    controller.shutdown()


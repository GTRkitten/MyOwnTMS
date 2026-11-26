"""Runtime-only GitLab connection settings and project preparation UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.database.models import GitLabProject
from src.gui.gitlab_controller import GitLabSessionController
from src.services.gitlab_project_service import GitLabProjectService


class GitLabSettingsDialog(QDialog):
    """Configure one runtime origin and validated private project profiles."""

    def __init__(self, session, controller: GitLabSessionController, parent=None):
        super().__init__(parent)
        self.session = session
        self.controller = controller
        self._busy = False
        self._pending_label_preview = None
        self.setWindowTitle("Настройки GitLab")
        self.setMinimumSize(900, 620)
        self._build_ui()
        self._load_runtime_settings()
        self.refresh_projects()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        connection_form = QFormLayout()

        self.origin_input = QLineEdit()
        self.origin_input.setPlaceholderText("https://gitlab.internal")
        connection_form.addRow("GitLab origin:", self.origin_input)

        ca_row = QHBoxLayout()
        self.ca_input = QLineEdit()
        self.ca_input.setPlaceholderText("Необязательно: абсолютный путь к CA bundle")
        ca_row.addWidget(self.ca_input)
        ca_button = QPushButton("Выбрать…")
        ca_button.clicked.connect(self._choose_ca_bundle)
        ca_row.addWidget(ca_button)
        connection_form.addRow("Internal CA:", ca_row)

        token_row = QHBoxLayout()
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setPlaceholderText("PAT только для текущего запуска")
        token_row.addWidget(self.token_input)
        self.clear_token_button = QPushButton("Очистить token")
        self.clear_token_button.clicked.connect(self._clear_token)
        token_row.addWidget(self.clear_token_button)
        connection_form.addRow("Personal access token:", token_row)
        layout.addLayout(connection_form)

        connection_actions = QHBoxLayout()
        self.apply_button = QPushButton("Применить в сеансе")
        self.apply_button.clicked.connect(self._apply_clicked)
        connection_actions.addWidget(self.apply_button)
        self.test_button = QPushButton("Проверить соединение")
        self.test_button.clicked.connect(self._test_connection)
        connection_actions.addWidget(self.test_button)
        self.token_state_label = QLabel()
        connection_actions.addWidget(self.token_state_label)
        connection_actions.addStretch()
        layout.addLayout(connection_actions)

        layout.addWidget(QLabel("Приватные проекты:"))
        self.projects_table = QTableWidget(0, 5)
        self.projects_table.setHorizontalHeaderLabels(
            ["Название", "GitLab ID", "Path", "Labels", "Активен"]
        )
        self.projects_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.projects_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.projects_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.projects_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.projects_table)

        add_form = QFormLayout()
        self.display_name_input = QLineEdit()
        self.display_name_input.setPlaceholderText("Заказчик / проект")
        add_form.addRow("Локальное название:", self.display_name_input)
        self.project_id_input = QSpinBox()
        self.project_id_input.setRange(1, 2_147_483_647)
        add_form.addRow("Numeric GitLab project ID:", self.project_id_input)
        layout.addLayout(add_form)

        project_actions = QHBoxLayout()
        self.add_project_button = QPushButton("Проверить и добавить проект")
        self.add_project_button.clicked.connect(self._add_project)
        project_actions.addWidget(self.add_project_button)
        self.bootstrap_button = QPushButton("Preview подготовки labels")
        self.bootstrap_button.clicked.connect(self._preview_labels)
        project_actions.addWidget(self.bootstrap_button)
        project_actions.addStretch()
        layout.addLayout(project_actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)

    def _load_runtime_settings(self) -> None:
        self.origin_input.setText(self.controller.origin)
        self.ca_input.setText(self.controller.ca_bundle)
        self._update_token_state()

    def _update_token_state(self) -> None:
        state = "token установлен" if self.controller.token_is_set else "token не установлен"
        self.token_state_label.setText(state)

    def _choose_ca_bundle(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите CA bundle", "", "Certificates (*.pem *.crt *.cer);;Все файлы (*)"
        )
        if path:
            self.ca_input.setText(path)

    def _apply_runtime_settings(self) -> bool:
        try:
            self.controller.configure(
                self.origin_input.text().strip(), self.ca_input.text().strip() or None
            )
            token = self.token_input.text()
            if token:
                self.controller.set_token(token)
                self.token_input.clear()
        except Exception as error:
            self._show_error(error)
            return False
        self._update_token_state()
        return True

    def _apply_clicked(self) -> None:
        if self._apply_runtime_settings():
            QMessageBox.information(
                self, "GitLab", "Настройки применены только для текущего запуска"
            )

    def _clear_token(self) -> None:
        self.token_input.clear()
        self.controller.clear_token()
        self._update_token_state()

    def refresh_projects(self) -> None:
        self.session.expire_all()
        projects = self.session.query(GitLabProject).order_by(GitLabProject.id).all()
        self.projects_table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            name_item = QTableWidgetItem(project.display_name)
            name_item.setData(Qt.ItemDataRole.UserRole, project.id)
            self.projects_table.setItem(row, 0, name_item)
            self.projects_table.setItem(row, 1, QTableWidgetItem(str(project.gitlab_project_id)))
            self.projects_table.setItem(row, 2, QTableWidgetItem(project.path_with_namespace))
            self.projects_table.setItem(
                row, 3, QTableWidgetItem("Готовы" if project.labels_ready_at else "Не подготовлены")
            )
            self.projects_table.setItem(
                row, 4, QTableWidgetItem("Да" if project.is_active else "Нет")
            )
        self.projects_table.resizeColumnsToContents()

    def _selected_project_id(self) -> int | None:
        rows = self.projects_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "GitLab", "Выберите проект")
            return None
        return self.projects_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        for button in (
            self.apply_button,
            self.test_button,
            self.add_project_button,
            self.bootstrap_button,
            self.clear_token_button,
        ):
            button.setEnabled(not busy)

    def _start(self, operation, succeeded) -> None:
        if self._busy or not self._apply_runtime_settings():
            return
        try:
            self._set_busy(True)
            self.controller.start(
                operation,
                succeeded=succeeded,
                failed=self._operation_failed,
                finished=self._operation_finished,
            )
        except Exception as error:
            self._set_busy(False)
            self._show_error(error)

    def _test_connection(self) -> None:
        self._start(lambda _session, client: client.check_connection(), self._connection_ok)

    @Slot(object)
    def _connection_ok(self, payload) -> None:
        username = payload.get("username") if isinstance(payload, dict) else None
        suffix = f": {username}" if isinstance(username, str) and username else ""
        QMessageBox.information(self, "GitLab", f"Соединение установлено{suffix}")

    def _add_project(self) -> None:
        display_name = self.display_name_input.text().strip()
        project_id = self.project_id_input.value()
        self._start(
            lambda session, client: GitLabProjectService(client).add_project(
                session, display_name=display_name, gitlab_project_id=project_id
            ),
            self._project_added,
        )

    @Slot(object)
    def _project_added(self, project) -> None:
        self.display_name_input.clear()
        self.refresh_projects()
        QMessageBox.information(
            self, "GitLab", f"Проект добавлен: {project.path_with_namespace}"
        )

    def _preview_labels(self) -> None:
        project_id = self._selected_project_id()
        if project_id is None:
            return
        self._start(
            lambda session, client: GitLabProjectService(client).preview_label_bootstrap(
                session, project_id
            ),
            self._labels_preview_ready,
        )

    @Slot(object)
    def _labels_preview_ready(self, preview) -> None:
        self._pending_label_preview = preview
        if preview.missing_labels:
            lines = "\n".join(f"• {label.name}" for label in preview.missing_labels)
            text = (
                f"Проект: {preview.path_with_namespace}\n\n"
                f"Будут созданы labels:\n{lines}\n\nПродолжить?"
            )
        else:
            QMessageBox.information(self, "GitLab labels", "Все managed labels уже существуют")
            return
        answer = QMessageBox.question(
            self,
            "Подтверждение labels",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start(
            lambda session, client: GitLabProjectService(client).confirm_label_bootstrap(
                session, preview.local_project_id, preview
            ),
            self._labels_bootstrapped,
        )

    @Slot(object)
    def _labels_bootstrapped(self, result) -> None:
        self.refresh_projects()
        QMessageBox.information(
            self,
            "GitLab labels",
            f"Создано: {len(result.created_labels)}; осталось: {len(result.remaining_missing_labels)}",
        )

    @Slot(object)
    def _operation_failed(self, error) -> None:
        self._show_error(error)

    @Slot()
    def _operation_finished(self) -> None:
        self._set_busy(False)

    def _show_error(self, error: BaseException) -> None:
        QMessageBox.critical(self, "GitLab", str(error))

    def reject(self) -> None:
        if self._busy:
            QMessageBox.information(self, "GitLab", "Дождитесь завершения операции")
            return
        super().reject()

    def accept(self) -> None:
        if self._busy:
            QMessageBox.information(self, "GitLab", "Дождитесь завершения операции")
            return
        super().accept()


"""
Диалог создания и редактирования баг-репорта
"""
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QComboBox, QPushButton,
    QLabel, QMessageBox, QListWidget, QFrame, QFileDialog,
    QScrollArea, QWidget, QProgressBar
)

from src.database.models import GitLabProject
from src.gui.gitlab_controller import GitLabSessionController
from src.gui.widgets.gitlab_sync_dialogs import (
    ConflictResolutionDialog,
    PublishPreviewDialog,
    SyncPreviewDialog,
)
from src.services.artifact_service import BugReportService, TestCaseService
from src.services.link_service import LinkService
from src.services.attachment_service import AttachmentService
from src.config import ALLOWED_FILE_TYPES
from src.services.gitlab_publish_service import GitLabPublishService
from src.services.gitlab_sync_service import GitLabSyncService


class BugReportDialog(QDialog):
    """Диалог создания и редактирования баг-репорта"""
    
    def __init__(
        self,
        session,
        artifact_id=None,
        parent=None,
        gitlab_controller: GitLabSessionController | None = None,
    ):
        super().__init__(parent)
        self.session = session
        self.artifact_id = artifact_id
        self.artifact_type = 'bug_report'
        self.linked_test_cases = []
        self.attachments = []  # Список прикрепленных файлов
        self.original_attachments = []  # Оригинальный список вложений из БД
        self.gitlab_controller = gitlab_controller
        self._network_busy = False
        self._pending_publish_preview = None
        self._pending_sync_preview = None
        
        self.init_ui()
        
        if artifact_id:
            self.load_artifact()
    
    def init_ui(self):
        """Инициализирует пользовательский интерфейс"""
        title = "Редактирование баг-репорта" if self.artifact_id else "Создание баг-репорта"
        self.setWindowTitle(title)
        self.setMinimumSize(1200, 800)
        
        # Создаем скролл-область
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Контейнер для всего содержимого
        container_widget = QWidget()
        container_layout = QVBoxLayout(container_widget)
        container_layout.setSpacing(10)
        container_layout.setContentsMargins(10, 10, 10, 10)
        
        # Форма
        form_layout = QFormLayout()
        
        self.id_label = QLabel()
        self.id_label.setProperty("dimmed", True)
        form_layout.addRow("ID:", self.id_label)
        
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Введите заголовок баг-репорта")
        self.title_input.setMinimumHeight(50)
        form_layout.addRow("Заголовок*:", self.title_input)
        
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Низкий", "Средний", "Высокий", "Критический"])
        self.priority_combo.setCurrentText("Средний")
        self.priority_combo.setMinimumHeight(50)
        form_layout.addRow("Приоритет:", self.priority_combo)
        
        self.severity_combo = QComboBox()
        self.severity_combo.addItems(["Тривиальный", "Минорный", "Мажорный", "Критический"])
        self.severity_combo.setCurrentText("Мажорный")
        self.severity_combo.setMinimumHeight(50)
        form_layout.addRow("Серьезность:", self.severity_combo)
        
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Черновик", "Новый", "В работе", "Проверен", "Закрыт"])
        self.status_combo.setCurrentText("Черновик")
        self.status_combo.setMinimumHeight(50)
        form_layout.addRow("Статус:", self.status_combo)

        self.project_combo = QComboBox()
        self.project_combo.addItem("Локально, без GitLab project", None)
        for project in (
            self.session.query(GitLabProject)
            .filter(GitLabProject.is_active.is_(True))
            .order_by(GitLabProject.display_name)
            .all()
        ):
            self.project_combo.addItem(
                f"{project.display_name} ({project.path_with_namespace})", project.id
            )
        form_layout.addRow("GitLab project:", self.project_combo)

        self.source_channel_combo = QComboBox()
        self.source_channel_combo.addItem("Не указан", None)
        self.source_channel_combo.addItem("Email", "email")
        self.source_channel_combo.addItem("Мессенджер", "messenger")
        self.source_channel_combo.addItem("Телефон", "phone")
        self.source_channel_combo.addItem("Встреча", "meeting")
        self.source_channel_combo.addItem("Другое", "other")
        form_layout.addRow("Канал источника:", self.source_channel_combo)

        self.external_reference_input = QLineEdit()
        self.external_reference_input.setMaxLength(500)
        self.external_reference_input.setPlaceholderText("Номер обращения или внешняя ссылка")
        form_layout.addRow("Внешний номер:", self.external_reference_input)

        self.sync_state_label = QLabel("local_only")
        form_layout.addRow("Состояние sync:", self.sync_state_label)
        
        container_layout.addLayout(form_layout)
        
        # Поля ввода
        container_layout.addWidget(QLabel("Описание:"))
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Опишите проблему")
        self.description_input.setMaximumHeight(80)
        container_layout.addWidget(self.description_input)
        
        container_layout.addWidget(QLabel("Шаги воспроизведения*:"))
        self.reproduction_steps_input = QTextEdit()
        self.reproduction_steps_input.setPlaceholderText("Опишите шаги для воспроизведения бага")
        self.reproduction_steps_input.setMaximumHeight(120)
        container_layout.addWidget(self.reproduction_steps_input)
        
        container_layout.addWidget(QLabel("Ожидаемый результат*:"))
        self.expected_result_input = QTextEdit()
        self.expected_result_input.setPlaceholderText("Опишите ожидаемый результат")
        self.expected_result_input.setMaximumHeight(120)
        container_layout.addWidget(self.expected_result_input)
        
        container_layout.addWidget(QLabel("Фактический результат*:"))
        self.actual_result_input = QTextEdit()
        self.actual_result_input.setPlaceholderText("Опишите фактический результат")
        self.actual_result_input.setMaximumHeight(120)
        container_layout.addWidget(self.actual_result_input)
        
        container_layout.addWidget(QLabel("Окружение:"))
        self.environment_input = QTextEdit()
        self.environment_input.setPlaceholderText("Опишите окружение (ОС, браузер, версия и т.д.)")
        self.environment_input.setMaximumHeight(80)
        container_layout.addWidget(self.environment_input)
        
        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        container_layout.addWidget(line)
        
        # Вложения
        container_layout.addWidget(QLabel("Вложения (png, jpg, jpeg):"))
        
        attachments_layout = QHBoxLayout()
        
        self.attachments_list = QListWidget()
        self.attachments_list.setMinimumHeight(150)
        attachments_layout.addWidget(self.attachments_list)
        
        attachments_buttons = QVBoxLayout()
        
        add_attachment_btn = QPushButton("Добавить")
        add_attachment_btn.clicked.connect(self.add_attachment)
        attachments_buttons.addWidget(add_attachment_btn)
        
        remove_attachment_btn = QPushButton("Удалить")
        remove_attachment_btn.clicked.connect(self.remove_attachment)
        attachments_buttons.addWidget(remove_attachment_btn)
        
        attachments_layout.addLayout(attachments_buttons)
        container_layout.addLayout(attachments_layout)
        
        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        container_layout.addWidget(line)
        
        # Связанные тест-кейсы
        container_layout.addWidget(QLabel("Связанные тест-кейсы:"))
        
        links_layout = QHBoxLayout()
        
        self.links_list = QListWidget()
        self.links_list.setMinimumHeight(150)
        links_layout.addWidget(self.links_list)
        
        links_buttons = QVBoxLayout()
        
        add_link_btn = QPushButton("Добавить")
        add_link_btn.clicked.connect(self.add_link)
        links_buttons.addWidget(add_link_btn)
        
        remove_link_btn = QPushButton("Удалить")
        remove_link_btn.clicked.connect(self.remove_link)
        links_buttons.addWidget(remove_link_btn)
        
        links_layout.addLayout(links_buttons)
        container_layout.addLayout(links_layout)
        
        # Добавляем растягивающийся spacer
        container_layout.addStretch()
        
        # Устанавливаем контейнер в скролл-область
        scroll_area.setWidget(container_widget)
        
        # Основной layout диалога
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll_area)
        
        # Кнопки (вне скролл-области)
        button_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("Сохранить локально")
        self.save_btn.setProperty("success", True)
        self.save_btn.clicked.connect(self.save_artifact)
        button_layout.addWidget(self.save_btn)

        self.publish_btn = QPushButton("Preview и опубликовать")
        self.publish_btn.clicked.connect(self.preview_publish)
        self.publish_btn.setEnabled(self.gitlab_controller is not None)
        button_layout.addWidget(self.publish_btn)

        self.sync_btn = QPushButton("Синхронизировать")
        self.sync_btn.clicked.connect(self.preview_sync)
        self.sync_btn.setEnabled(False)
        button_layout.addWidget(self.sync_btn)

        self.open_gitlab_btn = QPushButton("Открыть в GitLab")
        self.open_gitlab_btn.clicked.connect(self.open_in_gitlab)
        self.open_gitlab_btn.setEnabled(False)
        button_layout.addWidget(self.open_gitlab_btn)

        self.network_progress = QProgressBar()
        self.network_progress.setRange(0, 0)
        self.network_progress.setVisible(False)
        button_layout.addWidget(self.network_progress)
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        main_layout.addLayout(button_layout)
    
    def load_artifact(self):
        """Загружает данные баг-репорта"""
        artifact = BugReportService.get_by_id(self.session, self.artifact_id)
        if not artifact:
            return
        
        self.id_label.setText(artifact.id)
        self.title_input.setText(artifact.title)
        self.priority_combo.setCurrentText(artifact.priority)
        self.severity_combo.setCurrentText(artifact.severity)
        self.status_combo.setCurrentText(artifact.status)
        self.description_input.setText(artifact.description or "")
        self.reproduction_steps_input.setText(artifact.reproduction_steps)
        self.expected_result_input.setText(artifact.expected_result)
        self.actual_result_input.setText(artifact.actual_result)
        self.environment_input.setText(artifact.environment or "")
        project_index = self.project_combo.findData(artifact.gitlab_project_id)
        self.project_combo.setCurrentIndex(max(project_index, 0))
        source_index = self.source_channel_combo.findData(artifact.source_channel)
        self.source_channel_combo.setCurrentIndex(max(source_index, 0))
        self.external_reference_input.setText(artifact.external_reference or "")
        binding = artifact.gitlab_binding
        if binding is not None:
            self.sync_state_label.setText(binding.sync_state)
            self.project_combo.setEnabled(False)
            draft_index = self.status_combo.findText("Черновик")
            if draft_index >= 0:
                self.status_combo.model().item(draft_index).setEnabled(False)
            self.sync_btn.setEnabled(
                self.gitlab_controller is not None and binding.issue_iid is not None
            )
            self.open_gitlab_btn.setEnabled(bool(binding.issue_web_url))
        
        # Загружаем связанные тест-кейсы
        self.load_links()
        
        # Загружаем вложения
        self.load_attachments()
    
    def save_artifact(self):
        """Сохраняет баг-репорт"""
        if self._save_local():
            self.accept()

    def _save_local(self) -> bool:
        """Persist the current form without performing any network action."""
        # Валидация
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "Ошибка", "Введите заголовок баг-репорта")
            return False
        
        is_draft = self.status_combo.currentText() == "Черновик"
        if not is_draft and not self.reproduction_steps_input.toPlainText().strip():
            QMessageBox.warning(self, "Ошибка", "Введите шаги воспроизведения")
            return False
        
        if not is_draft and not self.expected_result_input.toPlainText().strip():
            QMessageBox.warning(self, "Ошибка", "Введите ожидаемый результат")
            return False
        
        if not is_draft and not self.actual_result_input.toPlainText().strip():
            QMessageBox.warning(self, "Ошибка", "Введите фактический результат")
            return False
        
        # Данные для сохранения
        data = {
            'title': self.title_input.text().strip(),
            'description': self.description_input.toPlainText().strip(),
            'reproduction_steps': self.reproduction_steps_input.toPlainText().strip(),
            'expected_result': self.expected_result_input.toPlainText().strip(),
            'actual_result': self.actual_result_input.toPlainText().strip(),
            'environment': self.environment_input.toPlainText().strip(),
            'priority': self.priority_combo.currentText(),
            'severity': self.severity_combo.currentText(),
            'status': self.status_combo.currentText(),
            'gitlab_project_id': self.project_combo.currentData(),
            'source_channel': self.source_channel_combo.currentData(),
            'external_reference': self.external_reference_input.text().strip() or None,
        }
        
        try:
            if self.artifact_id:
                # Обновление
                BugReportService.update(self.session, self.artifact_id, data)
            else:
                # Создание
                bug_report = BugReportService.create(self.session, data)
                self.artifact_id = bug_report.id
            
            # Сохраняем связи
            self.save_links()
            
            # Сохраняем вложения
            self.save_attachments()
            self.load_attachments()
            self.session.expire_all()
            self._refresh_sync_controls()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка сохранения: {str(e)}")
            return False

    def _refresh_sync_controls(self) -> None:
        if not self.artifact_id:
            return
        artifact = BugReportService.get_by_id(self.session, self.artifact_id)
        binding = artifact.gitlab_binding if artifact is not None else None
        state = binding.sync_state if binding is not None else "local_only"
        self.sync_state_label.setText(state)
        self.sync_btn.setEnabled(
            not self._network_busy
            and self.gitlab_controller is not None
            and binding is not None
            and binding.issue_iid is not None
        )
        self.open_gitlab_btn.setEnabled(
            not self._network_busy and binding is not None and bool(binding.issue_web_url)
        )
        if binding is not None:
            self.project_combo.setEnabled(False)
            draft_index = self.status_combo.findText("Черновик")
            if draft_index >= 0:
                self.status_combo.model().item(draft_index).setEnabled(False)

    def _set_network_busy(self, busy: bool) -> None:
        self._network_busy = busy
        self.network_progress.setVisible(busy)
        self.save_btn.setEnabled(not busy)
        self.publish_btn.setEnabled(not busy and self.gitlab_controller is not None)
        self.status_combo.setEnabled(not busy)
        self._refresh_sync_controls()

    def _start_network(self, operation, succeeded) -> None:
        if self._network_busy or self.gitlab_controller is None:
            return
        try:
            self.gitlab_controller.require_ready()
            self._set_network_busy(True)
            self.gitlab_controller.start(
                operation,
                succeeded=succeeded,
                failed=self._network_failed,
                finished=self._network_finished,
            )
        except Exception as error:
            self._set_network_busy(False)
            self._network_failed(error)

    def preview_publish(self) -> None:
        if not self._save_local():
            return
        bug_report_id = self.artifact_id
        self._start_network(
            lambda session, client: GitLabPublishService(client).preview(
                session, bug_report_id
            ),
            self._publish_preview_ready,
        )

    @Slot(object)
    def _publish_preview_ready(self, preview) -> None:
        self._pending_publish_preview = preview
        dialog = PublishPreviewDialog(preview, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_network(
            lambda session, client: GitLabPublishService(client).publish(
                session, preview.bug_report_id, preview
            ),
            self._publish_finished,
        )

    @Slot(object)
    def _publish_finished(self, result) -> None:
        self.session.expire_all()
        self._refresh_sync_controls()
        QMessageBox.information(
            self, "GitLab", f"Issue !{result.issue_iid} опубликован"
        )

    def preview_sync(self) -> None:
        if not self._save_local():
            return
        bug_report_id = self.artifact_id
        self._start_network(
            lambda session, client: GitLabSyncService(client).preview(
                session, bug_report_id
            ),
            self._sync_preview_ready,
        )

    @Slot(object)
    def _sync_preview_ready(self, preview) -> None:
        self._pending_sync_preview = preview
        if preview.action == "none":
            self.session.expire_all()
            self._refresh_sync_controls()
            QMessageBox.information(self, "GitLab", "Локальная и remote версии совпадают")
            return
        resolutions = None
        if preview.conflicts:
            dialog = ConflictResolutionDialog(preview, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            resolutions = dialog.resolutions
        else:
            dialog = SyncPreviewDialog(preview, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
        self._start_network(
            lambda session, client: GitLabSyncService(client).confirm(
                session, preview, resolutions
            ),
            self._sync_finished,
        )

    @Slot(object)
    def _sync_finished(self, result) -> None:
        self.session.expire_all()
        self.load_artifact()
        self._refresh_sync_controls()
        QMessageBox.information(self, "GitLab", "Синхронизация завершена")

    @Slot(object)
    def _network_failed(self, error) -> None:
        self.session.expire_all()
        self._refresh_sync_controls()
        QMessageBox.critical(self, "GitLab", str(error))

    @Slot()
    def _network_finished(self) -> None:
        self._set_network_busy(False)

    def open_in_gitlab(self) -> None:
        if not self.artifact_id:
            return
        artifact = BugReportService.get_by_id(self.session, self.artifact_id)
        url_value = (
            artifact.gitlab_binding.issue_web_url
            if artifact is not None and artifact.gitlab_binding is not None
            else None
        )
        url = QUrl(url_value or "")
        if not url.isValid() or url.scheme().lower() != "https" or not url.host():
            QMessageBox.warning(self, "GitLab", "Безопасный URL Issue недоступен")
            return
        QDesktopServices.openUrl(url)

    def reject(self) -> None:
        if self._network_busy:
            QMessageBox.information(self, "GitLab", "Дождитесь завершения операции")
            return
        super().reject()
    
    def load_links(self):
        """Загружает связанные тест-кейсы"""
        if not self.artifact_id:
            return
        
        self.links_list.clear()
        self.linked_test_cases = []
        
        # Получаем связанные артефакты
        linked = LinkService.get_linked_artifacts(
            self.session,
            self.artifact_id,
            self.artifact_type
        )
        
        for artifact in linked:
            if artifact['type'] == 'test_case':
                self.linked_test_cases.append(artifact)
                self.links_list.addItem(f"{artifact['id']}: {artifact['title']}")
    
    def add_link(self):
        """Добавляет связь с тест-кейсом"""
        from src.gui.widgets.link_selector import LinkSelectorDialog
        
        dialog = LinkSelectorDialog(self.session, 'test_case', parent=self)
        if dialog.exec():
            test_case = dialog.get_selected()
            if test_case:
                # Проверяем, что еще не связан
                for tc in self.linked_test_cases:
                    if tc['id'] == test_case['id']:
                        QMessageBox.information(self, "Информация", "Этот тест-кейс уже связан")
                        return
                
                self.linked_test_cases.append(test_case)
                self.links_list.addItem(f"{test_case['id']}: {test_case['title']}")
    
    def remove_link(self):
        """Удаляет связь"""
        current_row = self.links_list.currentRow()
        if current_row >= 0:
            self.linked_test_cases.pop(current_row)
            self.links_list.takeItem(current_row)
    
    def add_attachment(self):
        """Добавляет вложение"""
        if len(self.attachments) >= 7:
            QMessageBox.warning(self, "Предупреждение", "Максимум 7 вложений")
            return
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите изображение",
            "",
            "Изображения (*.png *.jpg *.jpeg);;Все файлы (*.*)"
        )
        
        if not file_path:
            return
        
        # Проверяем расширение
        file_ext = Path(file_path).suffix.lower()
        if file_ext not in ALLOWED_FILE_TYPES:
            QMessageBox.warning(self, "Ошибка", "Неподдерживаемый формат файла")
            return
        
        # Добавляем в список
        file_name = Path(file_path).name
        self.attachments.append({
            'file_path': file_path,
            'file_name': file_name,
            'file_type': ALLOWED_FILE_TYPES[file_ext]
        })
        
        # Обновляем отображение
        self.attachments_list.addItem(file_name)
    
    def remove_attachment(self):
        """Удаляет вложение"""
        current_row = self.attachments_list.currentRow()
        if current_row >= 0:
            self.attachments.pop(current_row)
            self.attachments_list.takeItem(current_row)
    
    def load_attachments(self):
        """Загружает вложения при редактировании"""
        if not self.artifact_id:
            return
        
        self.attachments.clear()
        self.attachments_list.clear()
        self.original_attachments.clear()
        
        attachments = AttachmentService.get_attachments(
            self.session,
            self.artifact_id,
            self.artifact_type
        )
        
        for att in attachments:
            attachment_data = {
                'id': att.id,
                'file_path': att.file_path,
                'file_name': att.file_name,
                'file_type': att.file_type,
                'existing': True  # Флаг, что файл уже существует в БД
            }
            self.attachments.append(attachment_data)
            self.original_attachments.append(attachment_data)
            self.attachments_list.addItem(att.file_name)
    
    def save_links(self):
        """Сохраняет связи с тест-кейсами"""
        if not self.artifact_id:
            return
        
        # Удаляем старые связи
        LinkService.delete_all_links(self.session, self.artifact_id, self.artifact_type)
        
        # Создаем новые связи
        for test_case in self.linked_test_cases:
            LinkService.create_link(
                self.session,
                self.artifact_id,
                self.artifact_type,
                test_case['id'],
                'test_case'
            )
    
    def save_attachments(self):
        """Сохраняет вложения"""
        if not self.artifact_id:
            return
        
        # Находим удаленные вложения (те, что были в original_attachments, но нет в attachments)
        original_ids = {att['id'] for att in self.original_attachments if att.get('id')}
        current_ids = {att['id'] for att in self.attachments if att.get('id')}
        deleted_ids = original_ids - current_ids
        
        # Удаляем удаленные вложения из БД
        for att_id in deleted_ids:
            try:
                AttachmentService.delete_attachment(self.session, att_id)
            except Exception as e:
                QMessageBox.warning(self, "Предупреждение", 
                                  f"Не удалось удалить вложение: {str(e)}")
        
        # Обрабатываем новые вложения
        for att in self.attachments:
            if not att.get('existing'):
                try:
                    AttachmentService.add_attachment(
                        self.session,
                        self.artifact_id,
                        self.artifact_type,
                        att['file_path'],
                        att['file_name']
                    )
                except Exception as e:
                    QMessageBox.warning(self, "Предупреждение", 
                                      f"Не удалось добавить вложение {att['file_name']}: {str(e)}")

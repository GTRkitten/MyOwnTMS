"""
Диалог просмотра деталей артефакта
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QTabWidget, QWidget,
    QMessageBox, QListWidget, QFrame, QFileDialog
)
from PySide6.QtCore import Qt
from pathlib import Path

from src.services.artifact_service import TestCaseService, BugReportService
from src.services.link_service import LinkService
from src.services.attachment_service import AttachmentService


class ArtifactDetailDialog(QDialog):
    """Диалог просмотра деталей артефакта"""
    
    def __init__(self, session, artifact_id, artifact_type, parent=None):
        super().__init__(parent)
        self.session = session
        self.artifact_id = artifact_id
        self.artifact_type = artifact_type
        
        self.init_ui()
        self.load_artifact()
    
    def init_ui(self):
        """Инициализирует пользовательский интерфейс"""
        self.setWindowTitle("Просмотр артефакта")
        self.setMinimumSize(700, 600)
        
        layout = QVBoxLayout(self)
        
        # Заголовок с ID
        header_layout = QHBoxLayout()
        self.id_label = QLabel()
        self.id_label.setProperty("heading", True)
        header_layout.addWidget(self.id_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Вкладки
        self.tabs = QTabWidget()
        
        # Вкладка с деталями
        details_tab = QWidget()
        details_layout = QVBoxLayout(details_tab)
        
        # Основные поля (только для чтения)
        self.title_label = QLabel()
        self.title_label.setProperty("subheading", True)
        details_layout.addWidget(self.title_label)
        
        self.metadata_label = QLabel()
        self.metadata_label.setProperty("dimmed", True)
        details_layout.addWidget(self.metadata_label)
        
        details_layout.addWidget(QLabel(""))
        
        # Содержимое в зависимости от типа
        if self.artifact_type == 'test_case':
            self.create_test_case_view(details_layout)
        else:
            self.create_bug_report_view(details_layout)
        
        self.tabs.addTab(details_tab, "Детали")
        
        # Вкладка со связями
        self.links_tab = QWidget()
        links_layout = QVBoxLayout(self.links_tab)
        
        self.links_list = QListWidget()
        self.links_list.itemDoubleClicked.connect(self.open_linked_artifact)
        links_layout.addWidget(self.links_list)
        
        self.tabs.addTab(self.links_tab, "Связи")
        
        # Вкладка с вложениями (только для баг-репортов)
        if self.artifact_type == 'bug_report':
            self.attachments_tab = QWidget()
            attachments_layout = QVBoxLayout(self.attachments_tab)
            
            self.attachments_list = QListWidget()
            self.attachments_list.itemDoubleClicked.connect(self.open_attachment)
            attachments_layout.addWidget(self.attachments_list)
            
            self.tabs.addTab(self.attachments_tab, "Вложения")
        
        layout.addWidget(self.tabs)
        
        # Кнопки
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def create_test_case_view(self, layout):
        """Создает представление тест-кейса"""
        self.preconditions_label = QLabel()
        self.preconditions_label.setWordWrap(True)
        layout.addWidget(QLabel("Предусловия:"))
        layout.addWidget(self.preconditions_label)
        
        self.steps_label = QTextEdit()
        self.steps_label.setReadOnly(True)
        layout.addWidget(QLabel("Шаги:"))
        layout.addWidget(self.steps_label)
        
        self.expected_result_label = QLabel()
        self.expected_result_label.setWordWrap(True)
        layout.addWidget(QLabel("Ожидаемый результат:"))
        layout.addWidget(self.expected_result_label)
        
        self.postconditions_label = QLabel()
        self.postconditions_label.setWordWrap(True)
        layout.addWidget(QLabel("Постусловия:"))
        layout.addWidget(self.postconditions_label)
        
        self.environment_label = QLabel()
        self.environment_label.setWordWrap(True)
        layout.addWidget(QLabel("Окружение:"))
        layout.addWidget(self.environment_label)
    
    def create_bug_report_view(self, layout):
        """Создает представление баг-репорта"""
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        layout.addWidget(QLabel("Описание:"))
        layout.addWidget(self.description_label)
        
        self.reproduction_steps_label = QTextEdit()
        self.reproduction_steps_label.setReadOnly(True)
        layout.addWidget(QLabel("Шаги воспроизведения:"))
        layout.addWidget(self.reproduction_steps_label)
        
        self.expected_result_label = QLabel()
        self.expected_result_label.setWordWrap(True)
        layout.addWidget(QLabel("Ожидаемый результат:"))
        layout.addWidget(self.expected_result_label)
        
        self.actual_result_label = QLabel()
        self.actual_result_label.setWordWrap(True)
        layout.addWidget(QLabel("Фактический результат:"))
        layout.addWidget(self.actual_result_label)
        
        self.environment_label = QLabel()
        self.environment_label.setWordWrap(True)
        layout.addWidget(QLabel("Окружение:"))
        layout.addWidget(self.environment_label)
    
    def load_artifact(self):
        """Загружает данные артефакта"""
        if self.artifact_type == 'test_case':
            artifact = TestCaseService.get_by_id(self.session, self.artifact_id)
            if artifact:
                self.id_label.setText(f"Тест-кейс: {artifact.id}")
                self.title_label.setText(artifact.title)
                
                metadata = (
                    f"Статус: {artifact.status} | "
                    f"Приоритет: {artifact.priority} | "
                    f"Создан: {artifact.created_at} | "
                    f"Обновлен: {artifact.updated_at}"
                )
                self.metadata_label.setText(metadata)
                
                self.preconditions_label.setText(artifact.preconditions or "Не указано")
                self.steps_label.setText(artifact.steps)
                self.expected_result_label.setText(artifact.expected_result)
                self.postconditions_label.setText(artifact.postconditions or "Не указано")
                self.environment_label.setText(artifact.environment or "Не указано")
                
                self.load_links()
        else:
            artifact = BugReportService.get_by_id(self.session, self.artifact_id)
            if artifact:
                self.id_label.setText(f"Баг-репорт: {artifact.id}")
                self.title_label.setText(artifact.title)
                
                metadata = (
                    f"Статус: {artifact.status} | "
                    f"Приоритет: {artifact.priority} | "
                    f"Серьезность: {artifact.severity} | "
                    f"Создан: {artifact.created_at} | "
                    f"Обновлен: {artifact.updated_at}"
                )
                self.metadata_label.setText(metadata)
                
                self.description_label.setText(artifact.description or "Не указано")
                self.reproduction_steps_label.setText(artifact.reproduction_steps)
                self.expected_result_label.setText(artifact.expected_result)
                self.actual_result_label.setText(artifact.actual_result)
                self.environment_label.setText(artifact.environment or "Не указано")
                
                self.load_links()
                self.load_attachments()
    
    def load_attachments(self):
        """Загружает вложения баг-репорта"""
        if self.artifact_type != 'bug_report' or not hasattr(self, 'attachments_list'):
            return
        
        self.attachments_list.clear()
        
        attachments = AttachmentService.get_attachments(
            self.session,
            self.artifact_id,
            'bug_report'
        )
        
        if not attachments:
            self.attachments_list.addItem("Нет вложений")
            self.attachments_list.item(0).setFlags(Qt.NoItemFlags)
            return
        
        for att in attachments:
            self.attachments_list.addItem(
                f"{att.file_name} ({att.file_type})"
            )
    
    def open_attachment(self, item):
        """Открывает вложение"""
        row = self.attachments_list.row(item)
        if row < 0:
            return
        
        attachments = AttachmentService.get_attachments(
            self.session,
            self.artifact_id,
            'bug_report'
        )
        
        if row < len(attachments):
            att = attachments[row]
            file_path = Path(att.file_path)
            
            if file_path.exists():
                import os
                os.startfile(str(file_path))
            else:
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    f"Файл не найден: {att.file_path}"
                )
    
    def load_links(self):
        """Загружает связи артефакта"""
        self.links_list.clear()
        
        linked = LinkService.get_linked_artifacts(
            self.session,
            self.artifact_id,
            self.artifact_type
        )
        
        if not linked:
            self.links_list.addItem("Нет связанных артефактов")
            self.links_list.item(0).setFlags(Qt.NoItemFlags)
            return
        
        for artifact in linked:
            artifact_type = "Тест-кейс" if artifact['type'] == 'test_case' else "Баг-репорт"
            self.links_list.addItem(
                f"{artifact_type}: {artifact['id']} - {artifact['title']}"
            )
    
    def open_linked_artifact(self, item):
        """Открывает связанный артефакт"""
        row = self.links_list.row(item)
        if row < 0:
            return
        
        linked = LinkService.get_linked_artifacts(
            self.session,
            self.artifact_id,
            self.artifact_type
        )
        
        if row < len(linked):
            artifact = linked[row]
            dialog = ArtifactDetailDialog(
                self.session,
                artifact['id'],
                artifact['type'],
                parent=self
            )
            dialog.exec()

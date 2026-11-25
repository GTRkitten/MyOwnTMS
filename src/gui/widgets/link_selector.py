"""
Диалог выбора артефакта для связывания
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QLabel,
    QLineEdit, QMessageBox
)

from src.services.link_service import LinkService


class LinkSelectorDialog(QDialog):
    """Диалог выбора артефакта для связывания"""
    
    def __init__(self, session, target_type, parent=None):
        """
        Инициализирует диалог
        
        Args:
            session: Сессия базы данных
            target_type: Тип артефакта для выбора ('test_case' или 'bug_report')
            parent: Родительский виджет
        """
        super().__init__(parent)
        self.session = session
        self.target_type = target_type
        self.selected_artifact = None
        
        self.init_ui()
        self.load_artifacts()
    
    def init_ui(self):
        """Инициализирует пользовательский интерфейс"""
        title = "Выбрать тест-кейс" if self.target_type == 'test_case' else "Выбрать баг-репорт"
        self.setWindowTitle(title)
        self.setMinimumSize(500, 600)
        
        layout = QVBoxLayout(self)
        
        # Поиск
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Поиск:"))
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите текст для поиска...")
        self.search_input.textChanged.connect(self.filter_artifacts)
        search_layout.addWidget(self.search_input)
        
        layout.addLayout(search_layout)
        
        # Список артефактов
        self.artifacts_list = QListWidget()
        layout.addWidget(self.artifacts_list)
        
        # Кнопки
        button_layout = QHBoxLayout()
        
        select_btn = QPushButton("Выбрать")
        select_btn.setProperty("primary", True)
        select_btn.clicked.connect(self.select_artifact)
        button_layout.addWidget(select_btn)
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def load_artifacts(self):
        """Загружает артефакты"""
        self.artifacts_list.clear()
        self.all_artifacts = []
        
        if self.target_type == 'test_case':
            artifacts = LinkService.get_all_test_cases(self.session)
        else:
            artifacts = LinkService.get_all_bug_reports(self.session)
        
        self.all_artifacts = artifacts
        
        for artifact in artifacts:
            self.artifacts_list.addItem(
                f"{artifact['id']}: {artifact['title']}"
            )
    
    def filter_artifacts(self, text):
        """Фильтрует артефакты по поиску"""
        self.artifacts_list.clear()
        
        if not text.strip():
            # Показываем все
            for artifact in self.all_artifacts:
                self.artifacts_list.addItem(
                    f"{artifact['id']}: {artifact['title']}"
                )
            return
        
        # Фильтруем
        text_lower = text.lower()
        for artifact in self.all_artifacts:
            if (text_lower in artifact['id'].lower() or 
                text_lower in artifact['title'].lower()):
                self.artifacts_list.addItem(
                    f"{artifact['id']}: {artifact['title']}"
                )
    
    def select_artifact(self):
        """Выбирает артефакт"""
        current_row = self.artifacts_list.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите артефакт")
            return
        
        # Находим выбранный артефакт
        filtered_artifacts = []
        text = self.search_input.text().lower() if self.search_input.text() else None
        
        for artifact in self.all_artifacts:
            if text:
                if (text in artifact['id'].lower() or 
                    text in artifact['title'].lower()):
                    filtered_artifacts.append(artifact)
            else:
                filtered_artifacts.append(artifact)
        
        if current_row < len(filtered_artifacts):
            self.selected_artifact = filtered_artifacts[current_row]
            self.accept()
    
    def get_selected(self):
        """Возвращает выбранный артефакт"""
        return self.selected_artifact

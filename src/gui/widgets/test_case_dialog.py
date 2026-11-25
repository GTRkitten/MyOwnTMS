"""
Диалог создания и редактирования тест-кейса
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QComboBox, QPushButton,
    QLabel, QFileDialog, QListWidget, QMessageBox,
    QSplitter, QFrame
)
from PySide6.QtCore import Qt

from src.services.artifact_service import TestCaseService, BugReportService
from src.services.attachment_service import AttachmentService
from src.services.link_service import LinkService


class TestCaseDialog(QDialog):
    """Диалог создания и редактирования тест-кейса"""
    
    def __init__(self, session, artifact_id=None, parent=None):
        super().__init__(parent)
        self.session = session
        self.artifact_id = artifact_id
        self.artifact_type = 'test_case'
        self.linked_bug_reports = []
        
        self.init_ui()
        
        if artifact_id:
            self.load_artifact()
    
    def init_ui(self):
        """Инициализирует пользовательский интерфейс"""
        title = "Редактирование тест-кейса" if self.artifact_id else "Создание тест-кейса"
        self.setWindowTitle(title)
        self.setMinimumSize(600, 800)
        
        layout = QVBoxLayout(self)
        
        # Форма
        form_layout = QFormLayout()
        
        self.id_label = QLabel()
        self.id_label.setProperty("dimmed", True)
        form_layout.addRow("ID:", self.id_label)
        
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Введите заголовок тест-кейса")
        self.title_input.setMinimumHeight(40)
        form_layout.addRow("Заголовок*:", self.title_input)
        
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Низкий", "Средний", "Высокий", "Критический"])
        self.priority_combo.setCurrentText("Средний")
        self.priority_combo.setMinimumHeight(40)
        form_layout.addRow("Приоритет:", self.priority_combo)
        
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Черновик", "Готов", "Пройден", "Провален", "Заблокирован"])
        self.status_combo.setCurrentText("Черновик")
        self.status_combo.setMinimumHeight(40)
        form_layout.addRow("Статус:", self.status_combo)
        
        layout.addLayout(form_layout)
        
        # Поля ввода
        layout.addWidget(QLabel("Предусловия:"))
        self.preconditions_input = QTextEdit()
        self.preconditions_input.setPlaceholderText("Опишите предусловия для выполнения тест-кейса")
        self.preconditions_input.setMaximumHeight(50)
        layout.addWidget(self.preconditions_input)
        
        layout.addWidget(QLabel("Шаги*:"))
        self.steps_input = QTextEdit()
        self.steps_input.setPlaceholderText("Опишите шаги выполнения тест-кейса")
        self.steps_input.setMaximumHeight(75)
        layout.addWidget(self.steps_input)
        
        layout.addWidget(QLabel("Ожидаемый результат*:"))
        self.expected_result_input = QTextEdit()
        self.expected_result_input.setPlaceholderText("Опишите ожидаемый результат")
        self.expected_result_input.setMaximumHeight(75)
        layout.addWidget(self.expected_result_input)
        
        layout.addWidget(QLabel("Постусловия:"))
        self.postconditions_input = QTextEdit()
        self.postconditions_input.setPlaceholderText("Опишите постусловия")
        self.postconditions_input.setMaximumHeight(50)
        layout.addWidget(self.postconditions_input)
        
        layout.addWidget(QLabel("Окружение:"))
        self.environment_input = QTextEdit()
        self.environment_input.setPlaceholderText("Опишите окружение (ОС, браузер, версия и т.д.)")
        self.environment_input.setMaximumHeight(50)
        layout.addWidget(self.environment_input)
        
        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        # Связанные баг-репорты
        layout.addWidget(QLabel("Связанные баг-репорты:"))
        
        links_layout = QHBoxLayout()
        
        self.links_list = QListWidget()
        links_layout.addWidget(self.links_list)
        
        links_buttons = QVBoxLayout()
        
        add_link_btn = QPushButton("Добавить")
        add_link_btn.clicked.connect(self.add_link)
        links_buttons.addWidget(add_link_btn)
        
        remove_link_btn = QPushButton("Удалить")
        remove_link_btn.clicked.connect(self.remove_link)
        links_buttons.addWidget(remove_link_btn)
        
        links_layout.addLayout(links_buttons)
        layout.addLayout(links_layout)
        
        # Кнопки
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton("Сохранить")
        save_btn.setProperty("success", True)
        save_btn.clicked.connect(self.save_artifact)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def load_artifact(self):
        """Загружает данные тест-кейса"""
        artifact = TestCaseService.get_by_id(self.session, self.artifact_id)
        if not artifact:
            return
        
        self.id_label.setText(artifact.id)
        self.title_input.setText(artifact.title)
        self.priority_combo.setCurrentText(artifact.priority)
        self.status_combo.setCurrentText(artifact.status)
        self.preconditions_input.setText(artifact.preconditions or "")
        self.steps_input.setText(artifact.steps)
        self.expected_result_input.setText(artifact.expected_result)
        self.postconditions_input.setText(artifact.postconditions or "")
        self.environment_input.setText(artifact.environment or "")
        
        # Загружаем связанные баг-репорты
        self.load_links()
    
    def save_artifact(self):
        """Сохраняет тест-кейс"""
        # Валидация
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "Ошибка", "Введите заголовок тест-кейса")
            return
        
        if not self.steps_input.toPlainText().strip():
            QMessageBox.warning(self, "Ошибка", "Введите шаги выполнения")
            return
        
        if not self.expected_result_input.toPlainText().strip():
            QMessageBox.warning(self, "Ошибка", "Введите ожидаемый результат")
            return
        
        # Данные для сохранения
        data = {
            'title': self.title_input.text().strip(),
            'preconditions': self.preconditions_input.toPlainText().strip(),
            'steps': self.steps_input.toPlainText().strip(),
            'expected_result': self.expected_result_input.toPlainText().strip(),
            'postconditions': self.postconditions_input.toPlainText().strip(),
            'environment': self.environment_input.toPlainText().strip(),
            'priority': self.priority_combo.currentText(),
            'status': self.status_combo.currentText()
        }
        
        try:
            if self.artifact_id:
                # Обновление
                TestCaseService.update(self.session, self.artifact_id, data)
            else:
                # Создание
                test_case = TestCaseService.create(self.session, data)
                self.artifact_id = test_case.id
            
            # Сохраняем связи
            self.save_links()
            
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка сохранения: {str(e)}")
    
    def load_links(self):
        """Загружает связанные баг-репорты"""
        if not self.artifact_id:
            return
        
        self.links_list.clear()
        self.linked_bug_reports = []
        
        # Получаем связанные артефакты
        linked = LinkService.get_linked_artifacts(
            self.session,
            self.artifact_id,
            self.artifact_type
        )
        
        for artifact in linked:
            if artifact['type'] == 'bug_report':
                self.linked_bug_reports.append(artifact)
                self.links_list.addItem(f"{artifact['id']}: {artifact['title']}")
    
    def add_link(self):
        """Добавляет связь с баг-репортом"""
        from src.gui.widgets.link_selector import LinkSelectorDialog
        
        dialog = LinkSelectorDialog(self.session, 'bug_report', parent=self)
        if dialog.exec():
            bug_report = dialog.get_selected()
            if bug_report:
                # Проверяем, что еще не связан
                for br in self.linked_bug_reports:
                    if br['id'] == bug_report['id']:
                        QMessageBox.information(self, "Информация", "Этот баг-репорт уже связан")
                        return
                
                self.linked_bug_reports.append(bug_report)
                self.links_list.addItem(f"{bug_report['id']}: {bug_report['title']}")
    
    def remove_link(self):
        """Удаляет связь"""
        current_row = self.links_list.currentRow()
        if current_row >= 0:
            self.linked_bug_reports.pop(current_row)
            self.links_list.takeItem(current_row)
    
    def save_links(self):
        """Сохраняет связи с баг-репортами"""
        if not self.artifact_id:
            return
        
        # Удаляем старые связи
        LinkService.delete_all_links(self.session, self.artifact_id, self.artifact_type)
        
        # Создаем новые связи
        for bug_report in self.linked_bug_reports:
            LinkService.create_link(
                self.session,
                self.artifact_id,
                self.artifact_type,
                bug_report['id'],
                'bug_report'
            )

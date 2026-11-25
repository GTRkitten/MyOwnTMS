"""
Диалог создания и редактирования баг-репорта
"""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QComboBox, QPushButton,
    QLabel, QMessageBox, QListWidget, QFrame, QFileDialog,
    QScrollArea, QWidget
)

from src.services.artifact_service import BugReportService, TestCaseService
from src.services.link_service import LinkService
from src.services.attachment_service import AttachmentService
from src.config import ALLOWED_FILE_TYPES


class BugReportDialog(QDialog):
    """Диалог создания и редактирования баг-репорта"""
    
    def __init__(self, session, artifact_id=None, parent=None):
        super().__init__(parent)
        self.session = session
        self.artifact_id = artifact_id
        self.artifact_type = 'bug_report'
        self.linked_test_cases = []
        self.attachments = []  # Список прикрепленных файлов
        self.original_attachments = []  # Оригинальный список вложений из БД
        
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
        self.status_combo.addItems(["Новый", "В работе", "Проверен", "Закрыт"])
        self.status_combo.setCurrentText("Новый")
        self.status_combo.setMinimumHeight(50)
        form_layout.addRow("Статус:", self.status_combo)
        
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
        
        save_btn = QPushButton("Сохранить")
        save_btn.setProperty("success", True)
        save_btn.clicked.connect(self.save_artifact)
        button_layout.addWidget(save_btn)
        
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
        
        # Загружаем связанные тест-кейсы
        self.load_links()
        
        # Загружаем вложения
        self.load_attachments()
    
    def save_artifact(self):
        """Сохраняет баг-репорт"""
        # Валидация
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "Ошибка", "Введите заголовок баг-репорта")
            return
        
        if not self.reproduction_steps_input.toPlainText().strip():
            QMessageBox.warning(self, "Ошибка", "Введите шаги воспроизведения")
            return
        
        if not self.expected_result_input.toPlainText().strip():
            QMessageBox.warning(self, "Ошибка", "Введите ожидаемый результат")
            return
        
        if not self.actual_result_input.toPlainText().strip():
            QMessageBox.warning(self, "Ошибка", "Введите фактический результат")
            return
        
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
            'status': self.status_combo.currentText()
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
            
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка сохранения: {str(e)}")
    
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

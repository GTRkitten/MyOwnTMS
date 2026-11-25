"""
Диалог экспорта артефактов
"""
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QFileDialog, QMessageBox, QCheckBox, QRadioButton,
    QButtonGroup, QGroupBox, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal

from src.export.pdf_exporter import PDFExporter
from src.export.docx_exporter import DOCXExporter
from src.export.md_exporter import MDExporter


class ExportThread(QThread):
    """Поток для экспорта"""
    progress = Signal(int)
    finished = Signal(bool, str)
    
    def __init__(self, artifacts, export_format, output_path, single_document):
        super().__init__()
        self.artifacts = artifacts
        self.export_format = export_format
        self.output_path = output_path
        self.single_document = single_document
    
    def run(self):
        """Выполняет экспорт"""
        try:
            if self.export_format == 'pdf':
                exporter = PDFExporter(self.output_path)
            elif self.export_format == 'docx':
                exporter = DOCXExporter(self.output_path)
            else:  # md
                exporter = MDExporter(self.output_path)
            
            self.progress.emit(50)
            
            if self.single_document:
                exporter._export_combined(self.artifacts)
                self.progress.emit(100)
                self.finished.emit(True, f"Экспорт завершен успешно!\nФайл сохранен:\n{self.output_path}")
            else:
                paths = exporter.export_multiple(self.artifacts, single_document=False)
                count = len(paths)
                self.progress.emit(100)
                if count > 0:
                    self.output_path = paths[0]  # Сохраняем первый путь для возможного использования
                    msg = f"Экспорт завершен успешно!\n\nСоздано файлов: {count}\nПапка сохранения:\n{str(Path(paths[0]).parent)}"
                else:
                    msg = "Экспорт завершен, но файлы не были созданы."
                self.finished.emit(True, msg)
        except Exception as e:
            self.finished.emit(False, f"Ошибка экспорта: {str(e)}")


class ExportDialog(QDialog):
    """Диалог экспорта артефактов"""
    
    def __init__(self, artifacts, artifact_type, parent=None):
        super().__init__(parent)
        self.artifacts = artifacts
        self.artifact_type = artifact_type
        self.export_thread = None
        
        self.init_ui()
    
    def init_ui(self):
        """Инициализирует пользовательский интерфейс"""
        self.setWindowTitle(f"Экспорт {len(self.artifacts)} артефактов")
        self.setMinimumSize(500, 400)
        
        layout = QVBoxLayout(self)
        
        # Информация
        info_label = QLabel(f"Выбрано {len(self.artifacts)} артефактов для экспорта")
        info_label.setProperty("dimmed", True)
        layout.addWidget(info_label)
        
        # Формат экспорта
        format_group = QGroupBox("Формат экспорта")
        format_layout = QVBoxLayout(format_group)
        
        self.format_radio_pdf = QRadioButton("PDF")
        self.format_radio_docx = QRadioButton("DOCX (Microsoft Word)")
        self.format_radio_md = QRadioButton("Markdown (.md)")
        self.format_radio_docx.setChecked(True)
        
        self.format_group = QButtonGroup(self)
        self.format_group.addButton(self.format_radio_pdf)
        self.format_group.addButton(self.format_radio_docx)
        self.format_group.addButton(self.format_radio_md)
        
        format_layout.addWidget(self.format_radio_pdf)
        format_layout.addWidget(self.format_radio_docx)
        format_layout.addWidget(self.format_radio_md)
        layout.addWidget(format_group)
        
        # Режим экспорта
        mode_group = QGroupBox("Режим экспорта")
        mode_layout = QVBoxLayout(mode_group)
        
        self.single_doc_radio = QRadioButton("Все артефакты в один документ")
        self.separate_docs_radio = QRadioButton("Каждый артефакт в отдельный файл")
        self.single_doc_radio.setChecked(True)
        
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.single_doc_radio)
        self.mode_group.addButton(self.separate_docs_radio)
        
        mode_layout.addWidget(self.single_doc_radio)
        mode_layout.addWidget(self.separate_docs_radio)
        layout.addWidget(mode_group)
        
        # Путь к файлу
        path_layout = QFormLayout()
        
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText("Выберите папку для сохранения")
        self.output_path_input.setText(str(Path.home() / "Desktop"))
        path_layout.addRow("Папка:", self.output_path_input)
        
        browse_btn = QPushButton("Обзор...")
        browse_btn.clicked.connect(self.browse_folder)
        path_layout.addRow("", browse_btn)
        
        layout.addLayout(path_layout)
        
        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Кнопки
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.export_btn = QPushButton("Экспортировать")
        self.export_btn.setProperty("success", True)
        self.export_btn.clicked.connect(self.start_export)
        button_layout.addWidget(self.export_btn)
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def browse_folder(self):
        """Выбирает папку для сохранения"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сохранения",
            self.output_path_input.text()
        )
        
        if folder:
            self.output_path_input.setText(folder)
    
    def get_export_format(self):
        """Возвращает выбранный формат экспорта"""
        if self.format_radio_pdf.isChecked():
            return 'pdf'
        elif self.format_radio_docx.isChecked():
            return 'docx'
        else:
            return 'md'
    
    def get_output_path(self):
        """Возвращает путь к выходному файлу"""
        folder = Path(self.output_path_input.text())
        format_name = self.get_export_format()
        
        if self.single_doc_radio.isChecked():
            artifact_name = 'test_cases' if self.artifact_type == 'test_cases' else 'bug_reports'
            return str(folder / f"{artifact_name}_export.{format_name}")
        else:
            # Для отдельного экспорта возвращаем папку
            return str(folder)
    
    def start_export(self):
        """Запускает экспорт"""
        if not self.output_path_input.text():
            QMessageBox.warning(self, "Ошибка", "Выберите папку для сохранения")
            return
        
        # Отключаем кнопки
        self.export_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Запускаем экспорт в отдельном потоке
        export_format = self.get_export_format()
        output_path = self.get_output_path()
        single_document = self.single_doc_radio.isChecked()
        
        self.export_thread = ExportThread(
            self.artifacts,
            export_format,
            output_path,
            single_document
        )
        self.export_thread.progress.connect(self.progress_bar.setValue)
        self.export_thread.finished.connect(self.on_export_finished)
        self.export_thread.start()
    
    def on_export_finished(self, success, message):
        """Обрабатывает завершение экспорта"""
        self.export_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Успех", message)
            self.accept()
        else:
            QMessageBox.critical(self, "Ошибка", message)
            self.progress_bar.setVisible(False)
            self.export_btn.setEnabled(True)
    
    def reject(self):
        """Обрабатывает отмену диалога"""
        if self.export_thread and self.export_thread.isRunning():
            self.export_thread.terminate()
        super().reject()

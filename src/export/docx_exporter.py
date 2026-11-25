"""
Экспорт артефактов в DOCX формат
"""
from typing import List, Dict, Any
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from pathlib import Path
import logging

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DOCXExporter:
    """Экспортер в DOCX формат"""
    
    def __init__(self, output_path: str):
        """
        Инициализирует экспортер
        
        Args:
            output_path: Путь к выходному файлу
        """
        self.output_path = output_path
        self.doc = Document()
        self._setup_styles()
    
    def _setup_styles(self):
        """Настраивает стили документа"""
        # Стиль заголовка
        style = self.doc.styles['Heading 1']
        style.font.name = 'Arial'
        style.font.size = Pt(18)
        style.font.color.rgb = RGBColor(44, 62, 80)  # #2C3E50
        
        # Стиль подзаголовка
        style = self.doc.styles['Heading 2']
        style.font.name = 'Arial'
        style.font.size = Pt(14)
        style.font.color.rgb = RGBColor(52, 152, 219)  # #3498DB
        
        # Обычный текст
        style = self.doc.styles['Normal']
        style.font.name = 'Arial'
        style.font.size = Pt(10)
        style.font.color.rgb = RGBColor(44, 62, 80)
    
    def export_test_case(self, test_case: Dict[str, Any]) -> str:
        """Экспортирует один тест-кейс"""
        # Заголовок
        title = self.doc.add_heading(f"Тест-кейс: {test_case['title']}", level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Метаданные
        self.doc.add_paragraph(f"ID: {test_case['id']}")
        self.doc.add_paragraph(f"Статус: {test_case['status']}")
        self.doc.add_paragraph(f"Приоритет: {test_case['priority']}")
        self.doc.add_paragraph(f"Создан: {test_case['created_at']}")
        self.doc.add_paragraph(f"Обновлен: {test_case['updated_at']}")
        
        self.doc.add_paragraph()
        
        # Предусловия
        if test_case.get('preconditions'):
            self.doc.add_heading("Предусловия:", level=2)
            self.doc.add_paragraph(test_case['preconditions'])
        
        # Шаги
        self.doc.add_heading("Шаги:", level=2)
        steps_para = self.doc.add_paragraph(test_case['steps'])
        steps_para.paragraph_format.left_indent = Inches(0.5)
        
        # Ожидаемый результат
        self.doc.add_heading("Ожидаемый результат:", level=2)
        self.doc.add_paragraph(test_case['expected_result'])
        
        # Постусловия
        if test_case.get('postconditions'):
            self.doc.add_heading("Постусловия:", level=2)
            self.doc.add_paragraph(test_case['postconditions'])
        
        # Окружение
        if test_case.get('environment'):
            self.doc.add_heading("Окружение:", level=2)
            self.doc.add_paragraph(test_case['environment'])
        
        self.doc.save(self.output_path)
        return self.output_path
    
    def export_bug_report(self, bug_report: Dict[str, Any]) -> str:
        """Экспортирует один баг-репорт"""
        # Заголовок
        title = self.doc.add_heading(f"{bug_report['id']}", level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Метаданные
        self.doc.add_paragraph(f"Заголовок: {bug_report['title']}")
        self.doc.add_paragraph(f"Статус: {bug_report['status']}")
        self.doc.add_paragraph(f"Приоритет: {bug_report['priority']}")
        self.doc.add_paragraph(f"Серьезность: {bug_report['severity']}")
        self.doc.add_paragraph(f"Создан: {bug_report['created_at']}")
        self.doc.add_paragraph(f"Обновлен: {bug_report['updated_at']}")
        
        self.doc.add_paragraph()
        
        # Описание
        if bug_report.get('description'):
            self.doc.add_heading("Описание:", level=2)
            self.doc.add_paragraph(bug_report['description'])
        
        # Шаги воспроизведения
        self.doc.add_heading("Шаги воспроизведения:", level=2)
        steps_para = self.doc.add_paragraph(bug_report['reproduction_steps'])
        steps_para.paragraph_format.left_indent = Inches(0.5)
        
        # Ожидаемый результат
        self.doc.add_heading("Ожидаемый результат:", level=2)
        self.doc.add_paragraph(bug_report['expected_result'])
        
        # Фактический результат
        self.doc.add_heading("Фактический результат:", level=2)
        self.doc.add_paragraph(bug_report['actual_result'])
        
        # Окружение
        if bug_report.get('environment'):
            self.doc.add_heading("Окружение:", level=2)
            self.doc.add_paragraph(bug_report['environment'])
        
        # Вложения
        if bug_report.get('attachments'):
            self.doc.add_heading("Вложения:", level=2)
            
            for i, attachment in enumerate(bug_report['attachments'], 1):
                if attachment['file_type'].startswith('image/'):
                    try:
                        # attachment['file_path'] уже содержит абсолютный путь
                        file_path = attachment['file_path']
                        logger.info(f"Попытка загрузки изображения {i}: {attachment['file_name']}")
                        logger.info(f"Путь к файлу: {file_path}")
                        logger.info(f"Файл существует: {Path(file_path).exists()}")
                        
                        # Добавляем изображение и центрируем его
                        last_paragraph = self.doc.add_picture(file_path, width=Inches(5.0))
                        last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        
                        # Добавляем подпись и центрируем её
                        caption = self.doc.add_paragraph(f"Рис. {i}")
                        caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        logger.info(f"Изображение {i} успешно загружено")
                    except Exception as e:
                        logger.error(f"Ошибка загрузки изображения {attachment['file_name']}: {str(e)}")
                        logger.error(f"Тип исключения: {type(e).__name__}")
                        logger.error(f"Путь к файлу: {attachment['file_path']}")
                        logger.error(f"Файл существует: {Path(attachment['file_path']).exists()}")
                        self.doc.add_paragraph(f"Ошибка загрузки изображения: {attachment['file_name']}")
        
        self.doc.save(self.output_path)
        return self.output_path
    
    def export_multiple(self, artifacts: List[Dict[str, Any]], single_document: bool = True) -> List[str]:
        """
        Экспортирует несколько артефактов
        
        Args:
            artifacts: Список артефактов
            single_document: True - все в одном файле, False - отдельные файлы
            
        Returns:
            Список путей к созданным файлам
        """
        if single_document:
            return [self._export_combined(artifacts)]
        else:
            paths = []
            base_path = Path(self.output_path)
            
            # Определяем папку для сохранения
            # Если base_path - это файл, берем его родительскую папку
            # Если base_path - это папка, используем её напрямую
            if base_path.is_dir():
                output_dir = base_path
            else:
                output_dir = base_path.parent
            
            for artifact in artifacts:
                if 'steps' in artifact:  # Тест-кейс
                    output = str(output_dir / f"{artifact['id']}_test_case.docx")
                else:  # Баг-репорт
                    output = str(output_dir / f"{artifact['id']}_bug_report.docx")
                
                exporter = DOCXExporter(output)
                if 'steps' in artifact:
                    exporter.export_test_case(artifact)
                else:
                    exporter.export_bug_report(artifact)
                
                paths.append(output)
            
            return paths
    
    def _export_combined(self, artifacts: List[Dict[str, Any]]) -> str:
        """Экспортирует все артефакты в один документ"""
        # Заголовок документа
        title = self.doc.add_heading("Отчет о дефектах", level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.doc.add_paragraph()
        
        for i, artifact in enumerate(artifacts):
            if i > 0:
                self.doc.add_page_break()
            
            if 'steps' in artifact:  # Тест-кейс
                self.doc.add_heading(f"Тест-кейс: {artifact['id']}", level=2)
                
                # Метаданные
                self.doc.add_paragraph(f"Заголовок: {artifact['title']}")
                self.doc.add_paragraph(f"Статус: {artifact['status']}")
                self.doc.add_paragraph(f"Приоритет: {artifact['priority']}")
                self.doc.add_paragraph(f"Создан: {artifact['created_at']}")
                self.doc.add_paragraph(f"Обновлен: {artifact['updated_at']}")
                self.doc.add_paragraph()
                
                # Предусловия
                if artifact.get('preconditions'):
                    self.doc.add_heading("Предусловия:", level=3)
                    self.doc.add_paragraph(artifact['preconditions'])
                
                # Шаги
                self.doc.add_heading("Шаги:", level=3)
                steps_para = self.doc.add_paragraph(artifact['steps'])
                steps_para.paragraph_format.left_indent = Inches(0.5)
                
                # Ожидаемый результат
                self.doc.add_heading("Ожидаемый результат:", level=3)
                self.doc.add_paragraph(artifact['expected_result'])
                
                # Постусловия
                if artifact.get('postconditions'):
                    self.doc.add_heading("Постусловия:", level=3)
                    self.doc.add_paragraph(artifact['postconditions'])
                
                # Окружение
                if artifact.get('environment'):
                    self.doc.add_heading("Окружение:", level=3)
                    self.doc.add_paragraph(artifact['environment'])
                
            else:  # Баг-репорт
                self.doc.add_heading(f"Дефект: {artifact['id']}", level=2)
                
                # Метаданные
                self.doc.add_paragraph(f"Заголовок: {artifact['title']}")
                self.doc.add_paragraph(f"Статус: {artifact['status']}")
                self.doc.add_paragraph(f"Приоритет: {artifact['priority']}")
                self.doc.add_paragraph(f"Серьезность: {artifact['severity']}")
                self.doc.add_paragraph(f"Создан: {artifact['created_at']}")
                self.doc.add_paragraph(f"Обновлен: {artifact['updated_at']}")
                self.doc.add_paragraph()
                
                # Описание
                if artifact.get('description'):
                    self.doc.add_heading("Описание:", level=3)
                    self.doc.add_paragraph(artifact['description'])
                
                # Шаги воспроизведения
                self.doc.add_heading("Шаги воспроизведения:", level=3)
                steps_para = self.doc.add_paragraph(artifact['reproduction_steps'])
                steps_para.paragraph_format.left_indent = Inches(0.5)
                
                # Ожидаемый результат
                self.doc.add_heading("Ожидаемый результат:", level=3)
                self.doc.add_paragraph(artifact['expected_result'])
                
                # Фактический результат
                self.doc.add_heading("Фактический результат:", level=3)
                self.doc.add_paragraph(artifact['actual_result'])
                
                # Окружение
                if artifact.get('environment'):
                    self.doc.add_heading("Окружение:", level=3)
                    self.doc.add_paragraph(artifact['environment'])
                
                # Вложения
                if artifact.get('attachments'):
                    self.doc.add_heading("Вложения:", level=3)
                    
                    for i, attachment in enumerate(artifact['attachments'], 1):
                        if attachment['file_type'].startswith('image/'):
                            try:
                                # attachment['file_path'] уже содержит абсолютный путь
                                file_path = attachment['file_path']
                                logger.info(f"Попытка загрузки изображения {i}: {attachment['file_name']}")
                                logger.info(f"Путь к файлу: {file_path}")
                                logger.info(f"Файл существует: {Path(file_path).exists()}")
                                
                                # Добавляем изображение и центрируем его
                                last_paragraph = self.doc.add_picture(file_path, width=Inches(5.0))
                                last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                
                                # Добавляем подпись и центрируем её
                                caption = self.doc.add_paragraph(f"Рис. {i}")
                                caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                logger.info(f"Изображение {i} успешно загружено")
                            except Exception as e:
                                logger.error(f"Ошибка загрузки изображения {attachment['file_name']}: {str(e)}")
                                logger.error(f"Тип исключения: {type(e).__name__}")
                                logger.error(f"Путь к файлу: {attachment['file_path']}")
                                logger.error(f"Файл существует: {Path(attachment['file_path']).exists()}")
                                self.doc.add_paragraph(f"Ошибка загрузки изображения: {attachment['file_name']}")
        
        self.doc.save(self.output_path)
        return self.output_path

"""
Экспорт артефактов в PDF формат
"""
from typing import List, Dict, Any
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pathlib import Path
import logging

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Регистрируем шрифт, поддерживающий кириллицу
# Используем встроенные шрифты Windows
def register_fonts():
    """Регистрирует шрифты для поддержки кириллицы"""
    font_paths = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\times.ttf",
    ]
    
    for font_path in font_paths:
        if Path(font_path).exists():
            try:
                pdfmetrics.registerFont(TTFont('Arial', font_path))
                return True
            except:
                continue
    
    # Если не удалось зарегистрировать шрифт, используем стандартный
    return False


# Регистрируем шрифты при импорте
try:
    register_fonts()
    FONT_NAME = 'Arial'
except:
    FONT_NAME = 'Helvetica'


class PDFExporter:
    """Экспортер в PDF формат"""
    
    def __init__(self, output_path: str):
        """
        Инициализирует экспортер
        
        Args:
            output_path: Путь к выходному файлу
        """
        self.output_path = output_path
        self.doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )
        
        # Стили
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            fontName=FONT_NAME,
            fontSize=18,
            textColor=colors.HexColor('#2C3E50'),
            alignment=TA_CENTER,
            spaceAfter=0.5*cm
        ))
        self.styles.add(ParagraphStyle(
            name='CustomHeading',
            fontName=FONT_NAME,
            fontSize=14,
            textColor=colors.HexColor('#3498DB'),
            spaceBefore=0.3*cm,
            spaceAfter=0.2*cm
        ))
        self.styles.add(ParagraphStyle(
            name='CustomNormal',
            fontName=FONT_NAME,
            fontSize=10,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=0.2*cm
        ))
        self.styles.add(ParagraphStyle(
            name='CustomCode',
            fontName=FONT_NAME,
            fontSize=10,
            textColor=colors.HexColor('#2C3E50'),
            leftIndent=1*cm,
            spaceAfter=0.2*cm
        ))
        self.styles.add(ParagraphStyle(
            name='CustomCentered',
            fontName=FONT_NAME,
            fontSize=10,
            textColor=colors.HexColor('#2C3E50'),
            alignment=TA_CENTER,
            spaceAfter=0.2*cm
        ))
    
    def export_test_case(self, test_case: Dict[str, Any]) -> str:
        """Экспортирует один тест-кейс"""
        elements = []
        
        # Заголовок
        elements.append(Paragraph(f"Тест-кейс: {test_case['title']}", self.styles['CustomTitle']))
        
        # Таблица с метаданными
        metadata = [
            ['ID', test_case['id']],
            ['Статус', test_case['status']],
            ['Приоритет', test_case['priority']],
            ['Создан', test_case['created_at']],
            ['Обновлен', test_case['updated_at']]
        ]
        
        table = Table(metadata, colWidths=[4*cm, 12*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F5F7FA')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2C3E50')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0.2*cm),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E6ED')),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.3*cm))
        
        # Предусловия
        if test_case.get('preconditions'):
            elements.append(Paragraph("Предусловия:", self.styles['CustomHeading']))
            elements.append(Paragraph(test_case['preconditions'], self.styles['CustomNormal']))
        
        # Шаги
        elements.append(Paragraph("Шаги:", self.styles['CustomHeading']))
        elements.append(Paragraph(test_case['steps'], self.styles['CustomCode']))
        
        # Ожидаемый результат
        elements.append(Paragraph("Ожидаемый результат:", self.styles['CustomHeading']))
        elements.append(Paragraph(test_case['expected_result'], self.styles['CustomNormal']))
        
        # Постусловия
        if test_case.get('postconditions'):
            elements.append(Paragraph("Постусловия:", self.styles['CustomHeading']))
            elements.append(Paragraph(test_case['postconditions'], self.styles['CustomNormal']))
        
        # Окружение
        if test_case.get('environment'):
            elements.append(Paragraph("Окружение:", self.styles['CustomHeading']))
            elements.append(Paragraph(test_case['environment'], self.styles['CustomNormal']))
        
        # Строим документ
        self.doc.build(elements)
        return self.output_path
    
    def export_bug_report(self, bug_report: Dict[str, Any]) -> str:
        """Экспортирует один баг-репорт"""
        elements = []
        
        # Заголовок
        elements.append(Paragraph(f"{bug_report['id']}", self.styles['CustomTitle']))
        
        # Таблица с метаданными
        metadata = [
            ['Заголовок', bug_report['title']],
            ['Статус', bug_report['status']],
            ['Приоритет', bug_report['priority']],
            ['Серьезность', bug_report['severity']],
            ['Создан', bug_report['created_at']],
            ['Обновлен', bug_report['updated_at']]
        ]
        
        table = Table(metadata, colWidths=[4*cm, 12*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F5F7FA')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2C3E50')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0.2*cm),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E6ED')),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.3*cm))
        
        # Описание
        if bug_report.get('description'):
            elements.append(Paragraph("Описание:", self.styles['CustomHeading']))
            elements.append(Paragraph(bug_report['description'], self.styles['CustomNormal']))
        
        # Шаги воспроизведения
        elements.append(Paragraph("Шаги воспроизведения:", self.styles['CustomHeading']))
        elements.append(Paragraph(bug_report['reproduction_steps'], self.styles['CustomCode']))
        
        # Ожидаемый результат
        elements.append(Paragraph("Ожидаемый результат:", self.styles['CustomHeading']))
        elements.append(Paragraph(bug_report['expected_result'], self.styles['CustomNormal']))
        
        # Фактический результат
        elements.append(Paragraph("Фактический результат:", self.styles['CustomHeading']))
        elements.append(Paragraph(bug_report['actual_result'], self.styles['CustomNormal']))
        
        # Окружение
        if bug_report.get('environment'):
            elements.append(Paragraph("Окружение:", self.styles['CustomHeading']))
            elements.append(Paragraph(bug_report['environment'], self.styles['CustomNormal']))
        
        # Вложения
        if bug_report.get('attachments'):
            elements.append(Spacer(1, 0.3*cm))
            elements.append(Paragraph("Вложения:", self.styles['CustomHeading']))
            
            for i, attachment in enumerate(bug_report['attachments'], 1):
                if attachment['file_type'].startswith('image/'):
                    from reportlab.platypus import Image
                    try:
                        # attachment['file_path'] уже содержит абсолютный путь
                        file_path = attachment['file_path']
                        logger.info(f"Попытка загрузки изображения {i}: {attachment['file_name']}")
                        logger.info(f"Путь к файлу: {file_path}")
                        logger.info(f"Файл существует: {Path(file_path).exists()}")
                        
                        img = Image(file_path, width=12*cm, height=9*cm, hAlign='CENTER')
                        elements.append(img)
                        elements.append(Paragraph(f"Рис. {i}", self.styles['CustomCentered']))
                        elements.append(Spacer(1, 0.2*cm))
                        logger.info(f"Изображение {i} успешно загружено")
                    except Exception as e:
                        logger.error(f"Ошибка загрузки изображения {attachment['file_name']}: {str(e)}")
                        logger.error(f"Тип исключения: {type(e).__name__}")
                        logger.error(f"Путь к файлу: {attachment['file_path']}")
                        logger.error(f"Файл существует: {Path(attachment['file_path']).exists()}")
                        elements.append(Paragraph(f"Ошибка загрузки изображения: {attachment['file_name']}", self.styles['CustomNormal']))
        
        # Строим документ
        self.doc.build(elements)
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
            # Все в одном документе
            return [self._export_combined(artifacts)]
        else:
            # Отдельные файлы
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
                if 'steps' in artifact:  # Это тест-кейс
                    output = str(output_dir / f"{artifact['id']}_test_case.pdf")
                    exporter = PDFExporter(output)
                    exporter.export_test_case(artifact)
                else:  # Это баг-репорт
                    output = str(output_dir / f"{artifact['id']}_bug_report.pdf")
                    exporter = PDFExporter(output)
                    exporter.export_bug_report(artifact)
                
                paths.append(output)
            
            return paths
    
    def _export_combined(self, artifacts: List[Dict[str, Any]]) -> str:
        """Экспортирует все артефакты в один документ"""
        elements = []
        
        # Заголовок документа
        elements.append(Paragraph("Отчет о дефектах", self.styles['CustomTitle']))
        elements.append(Spacer(1, 0.5*cm))
        
        for i, artifact in enumerate(artifacts):
            if i > 0:
                elements.append(PageBreak())
            
            if 'steps' in artifact:  # Тест-кейс
                elements.append(Paragraph(f"Тест-кейс: {artifact['id']}", self.styles['CustomHeading']))
                
                # Таблица с метаданными
                data = [
                    ['Заголовок:', artifact['title']],
                    ['Статус:', artifact['status']],
                    ['Приоритет:', artifact['priority']],
                    ['Создан:', artifact['created_at']],
                    ['Обновлен:', artifact['updated_at']],
                ]
                
                table = Table(data, colWidths=[4*cm, 12*cm])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F5F7FA')),
                    ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E6ED')),
                ]))
                elements.append(table)
                elements.append(Spacer(1, 0.2*cm))
                
                # Предусловия
                if artifact.get('preconditions'):
                    elements.append(Paragraph("Предусловия:", self.styles['CustomHeading']))
                    elements.append(Paragraph(artifact['preconditions'], self.styles['CustomNormal']))
                
                # Шаги
                elements.append(Paragraph("Шаги:", self.styles['CustomHeading']))
                steps_lines = artifact['steps'].split('\n')
                for line in steps_lines:
                    if line.strip():
                        elements.append(Paragraph(line, self.styles['CustomCode']))
                
                # Ожидаемый результат
                elements.append(Paragraph("Ожидаемый результат:", self.styles['CustomHeading']))
                elements.append(Paragraph(artifact['expected_result'], self.styles['CustomNormal']))
                
                # Постусловия
                if artifact.get('postconditions'):
                    elements.append(Paragraph("Постусловия:", self.styles['CustomHeading']))
                    elements.append(Paragraph(artifact['postconditions'], self.styles['CustomNormal']))
                
                # Окружение
                if artifact.get('environment'):
                    elements.append(Paragraph("Окружение:", self.styles['CustomHeading']))
                    elements.append(Paragraph(artifact['environment'], self.styles['CustomNormal']))
                
            else:  # Баг-репорт
                elements.append(Paragraph(f"Дефект: {artifact['id']}", self.styles['CustomHeading']))
                
                # Таблица с метаданными
                data = [
                    ['Заголовок:', artifact['title']],
                    ['Статус:', artifact['status']],
                    ['Приоритет:', artifact['priority']],
                    ['Серьезность:', artifact['severity']],
                    ['Создан:', artifact['created_at']],
                    ['Обновлен:', artifact['updated_at']],
                ]
                
                table = Table(data, colWidths=[4*cm, 12*cm])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F5F7FA')),
                    ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E6ED')),
                ]))
                elements.append(table)
                elements.append(Spacer(1, 0.2*cm))
                
                # Описание
                if artifact.get('description'):
                    elements.append(Paragraph("Описание:", self.styles['CustomHeading']))
                    elements.append(Paragraph(artifact['description'], self.styles['CustomNormal']))
                
                # Шаги воспроизведения
                elements.append(Paragraph("Шаги воспроизведения:", self.styles['CustomHeading']))
                steps_lines = artifact['reproduction_steps'].split('\n')
                for line in steps_lines:
                    if line.strip():
                        elements.append(Paragraph(line, self.styles['CustomCode']))
                
                # Ожидаемый результат
                elements.append(Paragraph("Ожидаемый результат:", self.styles['CustomHeading']))
                elements.append(Paragraph(artifact['expected_result'], self.styles['CustomNormal']))
                
                # Фактический результат
                elements.append(Paragraph("Фактический результат:", self.styles['CustomHeading']))
                elements.append(Paragraph(artifact['actual_result'], self.styles['CustomNormal']))
                
                # Окружение
                if artifact.get('environment'):
                    elements.append(Paragraph("Окружение:", self.styles['CustomHeading']))
                    elements.append(Paragraph(artifact['environment'], self.styles['CustomNormal']))
                
                # Вложения
                if artifact.get('attachments'):
                    elements.append(Spacer(1, 0.3*cm))
                    elements.append(Paragraph("Вложения:", self.styles['CustomHeading']))
                    
                    for i, attachment in enumerate(artifact['attachments'], 1):
                        if attachment['file_type'].startswith('image/'):
                            from reportlab.platypus import Image
                            try:
                                # attachment['file_path'] уже содержит абсолютный путь
                                file_path = attachment['file_path']
                                logger.info(f"Попытка загрузки изображения {i}: {attachment['file_name']}")
                                logger.info(f"Путь к файлу: {file_path}")
                                logger.info(f"Файл существует: {Path(file_path).exists()}")
                                
                                img = Image(file_path, width=12*cm, height=9*cm, hAlign='CENTER')
                                elements.append(img)
                                elements.append(Paragraph(f"Рис. {i}", self.styles['CustomCentered']))
                                elements.append(Spacer(1, 0.2*cm))
                                logger.info(f"Изображение {i} успешно загружено")
                            except Exception as e:
                                logger.error(f"Ошибка загрузки изображения {attachment['file_name']}: {str(e)}")
                                logger.error(f"Тип исключения: {type(e).__name__}")
                                logger.error(f"Путь к файлу: {attachment['file_path']}")
                                logger.error(f"Файл существует: {Path(attachment['file_path']).exists()}")
                                elements.append(Paragraph(f"Ошибка загрузки изображения: {attachment['file_name']}", self.styles['CustomNormal']))
            
            # Разделитель между артефактами
            elements.append(Spacer(1, 0.5*cm))
        
        self.doc.build(elements)
        return self.output_path

"""
Конфигурация MyOwnTMS
"""
import os
import sys
from pathlib import Path

# Информация о приложении
APP_NAME = "MyOwnTMS"
APP_VERSION = "1.0.0"


def get_data_dir() -> Path:
    """
    Возвращает директорию для данных.
    При запуске из EXE использует папку рядом с EXE,
    при запуске из Python использует папку data проекта.
    """
    test_data_dir = os.environ.get("MYOWNTMS_TEST_DATA_DIR")
    if test_data_dir:
        if (
            os.environ.get("MYOWNTMS_TESTING") != "1"
            or "PYTEST_VERSION" not in os.environ
            or getattr(sys, "frozen", False)
        ):
            raise RuntimeError(
                "MYOWNTMS_TEST_DATA_DIR is available only to pytest runs"
            )
        data_dir = Path(test_data_dir)
        if not data_dir.is_absolute():
            raise RuntimeError("MYOWNTMS_TEST_DATA_DIR must be an absolute path")
    elif getattr(sys, 'frozen', False):
        # Запущено как EXE (PyInstaller)
        exe_dir = Path(sys.executable).parent
        data_dir = exe_dir / "data"
    else:
        # Запущено из Python
        base_dir = Path(__file__).resolve().parent.parent
        data_dir = base_dir / "data"
    
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_style_path() -> Path:
    """
    Возвращает путь к файлу стилей.
    Корректно работает как при запуске из Python, так и из EXE.
    """
    if getattr(sys, 'frozen', False):
        # Запущено как EXE (PyInstaller)
        base_path = Path(sys._MEIPASS)
        style_path = base_path / "gui" / "styles" / "modern.qss"
    else:
        # Запущено из Python
        base_dir = Path(__file__).resolve().parent
        style_path = base_dir / "gui" / "styles" / "modern.qss"
    
    return style_path


# Базовая директория проекта (для разработки)
BASE_DIR = Path(__file__).resolve().parent.parent

# Директория для данных
DATA_DIR = get_data_dir()

# Директория для вложений (файлов)
ATTACHMENTS_DIR = DATA_DIR / "attachments"
ATTACHMENTS_DIR.mkdir(exist_ok=True)

# Директория для экспортированных документов
EXPORTS_DIR = DATA_DIR / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)

# Путь к базе данных SQLite
DATABASE_PATH = DATA_DIR / "tms.db"

# Путь к файлу стилей
STYLE_PATH = get_style_path()

# Формат ID артефактов: TC-DDMMYY-XXX или BUG-DDMMYY-XXX
ID_FORMAT = "{prefix}-{date:02d}{month:02d}{year:02d}-{sequence:03d}"

# Допустимые типы файлов для вложений
ALLOWED_FILE_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.pdf': 'application/pdf',
    '.txt': 'text/plain'
}

# Статусы тест-кейсов
TEST_CASE_STATUSES = ['Черновик', 'Готов', 'Пройден', 'Провален', 'Заблокирован']

# Статусы баг-репортов
BUG_REPORT_STATUSES = ['Черновик', 'Новый', 'В работе', 'Проверен', 'Закрыт']

# Приоритеты
PRIORITIES = ['Критический', 'Высокий', 'Средний', 'Низкий']

# Серьезность багов
SEVERITIES = ['Критический', 'Мажорный', 'Минорный', 'Тривиальный']

# Цветовая палитра для концентрации
COLORS = {
    'background': '#F5F7FA',
    'surface': '#FFFFFF',
    'primary': '#2C3E50',
    'secondary': '#3498DB',
    'accent': '#E74C3C',
    'success': '#27AE60',
    'warning': '#F39C12',
    'text_main': '#2C3E50',
    'text_dim': '#7F8C8D',
    'border': '#E0E6ED'
}

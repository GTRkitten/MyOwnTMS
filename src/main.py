"""
MyOwnTMS - Главная точка входа в приложение
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QVBoxLayout, QWidget, QLabel
from PySide6.QtCore import Qt

from src.config import APP_NAME, APP_VERSION
from src.database.session import init_db
from src.gui.main_window import MainWindow


def main():
    """Главная функция приложения"""
    # Инициализируем базу данных
    init_db()
    
    # Создаем приложение
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    
    # Создаем и показываем главное окно
    window = MainWindow()
    window.show()
    
    # Запускаем цикл обработки событий
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

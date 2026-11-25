"""
MyOwnTMS - Запуск приложения
Этот файл нужен для правильного запуска приложения из корневой директории
"""
import sys
from pathlib import Path

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, str(Path(__file__).parent))

from src.main import main

if __name__ == "__main__":
    main()

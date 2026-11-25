"""
Скрипт миграции базы данных для конвертации абсолютных путей в относительные.

Используйте этот скрипт, если у вас уже есть база данных с абсолютными путями
к вложениям, и вы хотите обновить её до нового формата с относительными путями.

Запустите скрипт из корневой директории проекта:
    python migrate_to_relative_paths.py
"""
import sys
from pathlib import Path

# Добавляем src в путь
sys.path.insert(0, str(Path(__file__).parent))

from src.database.session import get_session, engine
from src.database.models import Attachment, Base
from src.config import ATTACHMENTS_DIR
import shutil


def migrate_attachments():
    """
    Мигрирует абсолютные пути в относительные.
    
    1. Читает все вложения из БД
    2. Конвертирует абсолютные пути в относительные
    3. Копирует файлы в ATTACHMENTS_DIR если необходимо
    4. Обновляет записи в БД
    """
    session = get_session()
    
    try:
        # Проверяем, существуют ли вложения
        attachments = session.query(Attachment).all()
        
        if not attachments:
            print("Нет вложений для миграции.")
            return
        
        print(f"Найдено {len(attachments)} вложений для миграции.")
        print(f"Директория вложений: {ATTACHMENTS_DIR}")
        
        # Создаем директорию если не существует
        ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
        
        migrated = 0
        skipped = 0
        errors = 0
        
        for attachment in attachments:
            old_path_str = attachment.file_path
            old_path = Path(old_path_str)
            
            # Проверяем, путь уже относительный
            if not old_path.is_absolute():
                print(f"  [SKIP] {attachment.file_name} - уже относительный путь")
                skipped += 1
                continue
            
            # Проверяем, существует ли файл
            if not old_path.exists():
                print(f"  [WARN] {attachment.file_name} - файл не найден: {old_path}")
                errors += 1
                continue
            
            # Пробуем конвертировать в относительный путь
            try:
                # Проверяем, файл уже в ATTACHMENTS_DIR
                if old_path.resolve().parent == ATTACHMENTS_DIR.resolve():
                    # Уже в правильной директории, только меняем путь в БД
                    relative_path = old_path.name
                else:
                    # Копируем файл в ATTACHMENTS_DIR
                    relative_path = f"{old_path.parent.name}_{old_path.name}"
                    dest_path = ATTACHMENTS_DIR / relative_path
                    
                    # Если файл с таким именем уже существует, добавляем суффикс
                    counter = 1
                    while dest_path.exists():
                        stem = old_path.stem
                        suffix = old_path.suffix
                        relative_path = f"{old_path.parent.name}_{stem}_{counter}{suffix}"
                        dest_path = ATTACHMENTS_DIR / relative_path
                        counter += 1
                    
                    print(f"  [COPY] {attachment.file_name} -> {relative_path}")
                    shutil.copy2(old_path, dest_path)
                
                # Обновляем запись в БД
                print(f"  [UPDATE] {old_path_str} -> {relative_path}")
                attachment.file_path = relative_path
                migrated += 1
                
            except Exception as e:
                print(f"  [ERROR] {attachment.file_name}: {e}")
                errors += 1
        
        # Сохраняем изменения
        session.commit()
        
        print("\n" + "="*60)
        print(f"Миграция завершена:")
        print(f"  Мигрировано: {migrated}")
        print(f"  Пропущено: {skipped}")
        print(f"  Ошибок: {errors}")
        print("="*60)
        
        if errors > 0:
            print("\nВнимание! Возникли ошибки. Проверьте сообщения выше.")
        
    except Exception as e:
        session.rollback()
        print(f"\nКритическая ошибка миграции: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print("="*60)
    print("Миграция базы данных MyOwnTMS")
    print("Конвертация абсолютных путей в относительные")
    print("="*60)
    print()
    
    # Подтверждение
    response = input("Вы хотите создать бекап базы данных перед миграцией? (y/n): ")
    if response.lower() == 'y':
        db_path = Path("data/tms.db")
        if db_path.exists():
            backup_path = db_path.with_suffix('.db.backup')
            shutil.copy2(db_path, backup_path)
            print(f"Бекап создан: {backup_path}")
        else:
            print("База данных не найдена.")
    
    print("\nНачинаем миграцию...\n")
    migrate_attachments()
    
    print("\nМиграция завершена. Теперь вы можете запустить приложение.")

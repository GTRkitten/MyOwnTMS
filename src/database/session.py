"""
Управление сессиями базы данных
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from src.config import DATABASE_PATH
from src.database.models import Base

# Создаем движок SQLite
engine = create_engine(f'sqlite:///{DATABASE_PATH}', echo=False)

# Создаем фабрику сессий
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))


def init_database():
    """Инициализирует базу данных, создает таблицы"""
    Base.metadata.create_all(bind=engine)


# Алиас для совместимости
init_db = init_database


def get_session():
    """Получает сессию базы данных"""
    return SessionLocal()


def close_session():
    """Закрывает все сессии"""
    SessionLocal.remove()


if __name__ == '__main__':
    # Инициализация БД при прямом запуске
    init_database()
    print(f"База данных инициализирована: {DATABASE_PATH}")

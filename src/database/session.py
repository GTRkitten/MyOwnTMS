"""
Управление сессиями базы данных
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from src.config import DATABASE_PATH
from src.database.migrations import run_migrations

# Создаем движок SQLite
engine = create_engine(f'sqlite:///{DATABASE_PATH}', echo=False)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()

# Создаем фабрику сессий
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))


def init_database():
    """Создаёт backup и применяет pending migrations к локальной БД."""
    return run_migrations(DATABASE_PATH)


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

"""
Генератор уникальных ID для артефактов
Формат: TC-DDMMYY-XXX или BUG-DDMMYY-XXX
"""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from src.database.models import TestCase, BugReport


def generate_id(artifact_type: str, session: Session) -> str:
    """
    Генерирует уникальный ID для артефакта
    
    Args:
        artifact_type: 'test_case' или 'bug_report'
        session: Сессия базы данных
        
    Returns:
        Строка ID в формате TC-DDMMYY-XXX или BUG-DDMMYY-XXX
    """
    now = datetime.now()
    day = now.day
    month = now.month
    year = now.year % 100  # Последние 2 цифры года
    
    # Префикс по типу артефакта
    prefix = 'TC' if artifact_type == 'test_case' else 'BUG'
    
    # Получаем следующий порядковый номер за сегодня
    date_str = f"{day:02d}{month:02d}{year:02d}"
    pattern = f"{prefix}-{date_str}-%"
    
    if artifact_type == 'test_case':
        last = session.query(TestCase).filter(TestCase.id.like(pattern)).order_by(TestCase.id.desc()).first()
    else:
        last = session.query(BugReport).filter(BugReport.id.like(pattern)).order_by(BugReport.id.desc()).first()
    
    # Извлекаем порядковый номер
    if last:
        last_sequence = int(last.id.split('-')[-1])
        sequence = last_sequence + 1
    else:
        sequence = 1
    
    return f"{prefix}-{date_str}-{sequence:03d}"


def validate_id_unique(artifact_id: str, created_at: datetime, session: Session, 
                       artifact_type: str, exclude_id: Optional[str] = None) -> bool:
    """
    Проверяет уникальность комбинации ID + дата
    
    Args:
        artifact_id: ID артефакта
        created_at: Дата создания
        session: Сессия базы данных
        artifact_type: Тип артефакта
        exclude_id: ID для исключения (при обновлении)
        
    Returns:
        True если уникально, False если дубликат
    """
    if artifact_type == 'test_case':
        query = session.query(TestCase).filter(
            TestCase.id == artifact_id,
            TestCase.created_at == created_at
        )
    else:
        query = session.query(BugReport).filter(
            BugReport.id == artifact_id,
            BugReport.created_at == created_at
        )
    
    # Исключаем текущий артефакт при обновлении
    if exclude_id:
        query = query.filter(TestCase.id != exclude_id if artifact_type == 'test_case' 
                            else BugReport.id != exclude_id)
    
    return query.first() is None

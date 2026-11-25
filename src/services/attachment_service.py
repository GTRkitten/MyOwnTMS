"""
Сервис для работы с вложениями (файлами)
"""
import shutil
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from src.database.models import Attachment
from src.config import ATTACHMENTS_DIR, ALLOWED_FILE_TYPES


class AttachmentService:
    """Сервис для работы с вложениями"""
    
    @staticmethod
    def add_attachment(session: Session, 
                       artifact_id: str,
                       artifact_type: str,
                       file_path: str,
                       file_name: str) -> Optional[Attachment]:
        """
        Добавляет вложение к артефакту
        
        Args:
            session: Сессия БД
            artifact_id: ID артефакта
            artifact_type: Тип ('test_case' или 'bug_report')
            file_path: Путь к исходному файлу
            file_name: Имя файла
            
        Returns:
            Объект Attachment или None при ошибке
        """
        # Проверяем тип файла
        file_ext = Path(file_name).suffix.lower()
        if file_ext not in ALLOWED_FILE_TYPES:
            raise ValueError(f"Тип файла {file_ext} не поддерживается")
        
        # Создаем уникальное имя файла
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_name = f"{timestamp}_{file_name}"
        dest_path = ATTACHMENTS_DIR / unique_name
        
        # Копируем файл
        try:
            shutil.copy2(file_path, dest_path)
        except Exception as e:
            raise IOError(f"Ошибка копирования файла: {e}")
        
        # Создаем запись в БД с относительным путем
        attachment = Attachment(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            file_path=unique_name,  # Относительный путь
            file_name=file_name,
            file_type=ALLOWED_FILE_TYPES[file_ext],
            test_case_id=artifact_id if artifact_type == 'test_case' else None,
            bug_report_id=artifact_id if artifact_type == 'bug_report' else None
        )
        
        session.add(attachment)
        session.commit()
        session.refresh(attachment)
        
        return attachment
    
    @staticmethod
    def get_attachments(session: Session, artifact_id: str, artifact_type: str) -> List[Attachment]:
        """Получает список вложений для артефакта"""
        return session.query(Attachment).filter(
            Attachment.artifact_id == artifact_id,
            Attachment.artifact_type == artifact_type
        ).order_by(Attachment.created_at).all()
    
    @staticmethod
    def get_attachments_for_export(session: Session, artifact_id: str, artifact_type: str) -> List[dict]:
        """
        Получает список вложений для экспорта с абсолютными путями.
        
        Returns:
            Список словарей с информацией о вложениях, включая абсолютные пути к файлам
        """
        attachments = session.query(Attachment).filter(
            Attachment.artifact_id == artifact_id,
            Attachment.artifact_type == artifact_type
        ).order_by(Attachment.created_at).all()
        
        result = []
        for att in attachments:
            result.append({
                'id': att.id,
                'file_path': str(att.get_absolute_path()),  # Абсолютный путь
                'file_name': att.file_name,
                'file_type': att.file_type
            })
        
        return result
    
    @staticmethod
    def delete_attachment(session: Session, attachment_id: int) -> bool:
        """Удаляет вложение"""
        attachment = session.query(Attachment).filter(Attachment.id == attachment_id).first()
        if not attachment:
            return False
        
        # Удаляем файл (используем абсолютный путь)
        file_path = attachment.get_absolute_path()
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass  # Игнорируем ошибки удаления файла
        
        # Удаляем запись из БД
        session.delete(attachment)
        session.commit()
        
        return True
    
    @staticmethod
    def get_attachment_by_id(session: Session, attachment_id: int) -> Optional[Attachment]:
        """Получает вложение по ID"""
        return session.query(Attachment).filter(Attachment.id == attachment_id).first()

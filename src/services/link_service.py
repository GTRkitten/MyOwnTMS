"""
Сервис для работы со связями между артефактами
"""
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from src.database.models import ArtifactLink
from src.services.artifact_service import TestCaseService, BugReportService


class LinkService:
    """Сервис для связей между артефактами"""
    
    @staticmethod
    def create_link(session: Session, 
                   source_id: str, 
                   source_type: str,
                   target_id: str, 
                   target_type: str) -> ArtifactLink:
        """
        Создает связь между артефактами
        
        Args:
            session: Сессия базы данных
            source_id: ID исходного артефакта
            source_type: Тип исходного артефакта (test_case или bug_report)
            target_id: ID целевого артефакта
            target_type: Тип целевого артефакта (test_case или bug_report)
            
        Returns:
            Созданная связь
        """
        # Проверяем, что связь уже не существует
        existing = session.query(ArtifactLink).filter(
            ArtifactLink.source_id == source_id,
            ArtifactLink.source_type == source_type,
            ArtifactLink.target_id == target_id,
            ArtifactLink.target_type == target_type
        ).first()
        
        if existing:
            return existing
        
        link = ArtifactLink(
            source_id=source_id,
            source_type=source_type,
            target_id=target_id,
            target_type=target_type
        )
        session.add(link)
        session.commit()
        session.refresh(link)
        return link
    
    @staticmethod
    def delete_link(session: Session, source_id: str, source_type: str, target_id: str):
        """
        Удаляет связь между артефактами
        
        Args:
            session: Сессия базы данных
            source_id: ID исходного артефакта
            source_type: Тип исходного артефакта
            target_id: ID целевого артефакта
        """
        link = session.query(ArtifactLink).filter(
            ArtifactLink.source_id == source_id,
            ArtifactLink.source_type == source_type,
            ArtifactLink.target_id == target_id
        ).first()
        
        if link:
            session.delete(link)
            session.commit()
    
    @staticmethod
    def delete_all_links(session: Session, source_id: str, source_type: str):
        """
        Удаляет все связи артефакта
        
        Args:
            session: Сессия базы данных
            source_id: ID артефакта
            source_type: Тип артефакта
        """
        links = session.query(ArtifactLink).filter(
            ArtifactLink.source_id == source_id,
            ArtifactLink.source_type == source_type
        ).all()
        
        for link in links:
            session.delete(link)
        
        session.commit()
    
    @staticmethod
    def get_linked_artifacts(session: Session, artifact_id: str, artifact_type: str) -> List[Dict]:
        """
        Получает все связанные артефакты
        
        Args:
            session: Сессия базы данных
            artifact_id: ID артефакта
            artifact_type: Тип артефакта
            
        Returns:
            Список связанных артефактов
        """
        # Получаем исходящие связи
        outgoing = session.query(ArtifactLink).filter(
            ArtifactLink.source_id == artifact_id,
            ArtifactLink.source_type == artifact_type
        ).all()
        
        results = []
        for link in outgoing:
            if link.target_type == 'test_case':
                artifact = TestCaseService.get_by_id(session, link.target_id)
                if artifact:
                    artifact_dict = artifact.to_dict()
                    artifact_dict['type'] = 'test_case'
                    results.append(artifact_dict)
            else:
                artifact = BugReportService.get_by_id(session, link.target_id)
                if artifact:
                    artifact_dict = artifact.to_dict()
                    artifact_dict['type'] = 'bug_report'
                    results.append(artifact_dict)
        
        return results
    
    @staticmethod
    def get_all_test_cases(session: Session) -> List[Dict]:
        """
        Получает все тест-кейсы для выбора связей
        
        Args:
            session: Сессия базы данных
            
        Returns:
            Список тест-кейсов
        """
        test_cases = TestCaseService.get_all(session)
        return [tc.to_dict() for tc in test_cases]
    
    @staticmethod
    def get_all_bug_reports(session: Session) -> List[Dict]:
        """
        Получает все баг-репорты для выбора связей
        
        Args:
            session: Сессия базы данных
            
        Returns:
            Список баг-репортов
        """
        bug_reports = BugReportService.get_all(session)
        return [br.to_dict() for br in bug_reports]

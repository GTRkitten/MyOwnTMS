"""
Сервис для работы с артефактами (тест-кейсы и баг-репорты)
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from src.database.models import TestCase, BugReport, Attachment, ArtifactLink
from src.services.id_generator import generate_id


class PublishedBugDeleteError(ValueError):
    """A GitLab-bound bug must be closed instead of hard-deleted."""


class TestCaseService:
    """Сервис для тест-кейсов"""
    
    @staticmethod
    def create(session: Session, data: Dict[str, Any]) -> TestCase:
        """Создает новый тест-кейс"""
        test_case = TestCase(
            id=generate_id('test_case', session),
            title=data['title'],
            preconditions=data.get('preconditions', ''),
            steps=data['steps'],
            expected_result=data['expected_result'],
            postconditions=data.get('postconditions', ''),
            environment=data.get('environment', ''),
            priority=data.get('priority', 'Medium'),
            status=data.get('status', 'Draft')
        )
        session.add(test_case)
        session.commit()
        session.refresh(test_case)
        return test_case
    
    @staticmethod
    def get_by_id(session: Session, test_case_id: str) -> Optional[TestCase]:
        """Получает тест-кейс по ID"""
        return session.query(TestCase).filter(TestCase.id == test_case_id).first()
    
    @staticmethod
    def get_all(session: Session, 
                status: Optional[str] = None,
                priority: Optional[str] = None,
                search: Optional[str] = None,
                date_from: Optional[datetime] = None,
                date_to: Optional[datetime] = None,
                updated_from: Optional[datetime] = None,
                updated_to: Optional[datetime] = None) -> List[TestCase]:
        """Получает список тест-кейсов с фильтрацией"""
        query = session.query(TestCase)
        
        if status:
            query = query.filter(TestCase.status == status)
        
        if priority:
            query = query.filter(TestCase.priority == priority)
        
        if search:
            query = query.filter(
                or_(
                    TestCase.id.like(f'%{search}%'),
                    TestCase.title.like(f'%{search}%'),
                    TestCase.steps.like(f'%{search}%'),
                    TestCase.expected_result.like(f'%{search}%'),
                    TestCase.preconditions.like(f'%{search}%'),
                    TestCase.postconditions.like(f'%{search}%'),
                    TestCase.environment.like(f'%{search}%')
                )
            )
        
        if date_from:
            query = query.filter(TestCase.created_at >= date_from)
        
        if date_to:
            query = query.filter(TestCase.created_at <= date_to)
        
        if updated_from:
            query = query.filter(TestCase.updated_at >= updated_from)
        
        if updated_to:
            query = query.filter(TestCase.updated_at <= updated_to)
        
        return query.order_by(TestCase.created_at.desc()).all()
    
    @staticmethod
    def update(session: Session, test_case_id: str, data: Dict[str, Any]) -> Optional[TestCase]:
        """Обновляет тест-кейс"""
        test_case = TestCaseService.get_by_id(session, test_case_id)
        if not test_case:
            return None
        
        for key, value in data.items():
            if hasattr(test_case, key) and value is not None:
                setattr(test_case, key, value)
        
        test_case.updated_at = datetime.now()
        session.commit()
        session.refresh(test_case)
        return test_case
    
    @staticmethod
    def delete(session: Session, test_case_id: str) -> bool:
        """Удаляет тест-кейс"""
        test_case = TestCaseService.get_by_id(session, test_case_id)
        if not test_case:
            return False
        
        session.delete(test_case)
        session.commit()
        return True


class BugReportService:
    """Сервис для баг-репортов"""
    
    @staticmethod
    def create(session: Session, data: Dict[str, Any]) -> BugReport:
        """Создает новый баг-репорт"""
        bug_report = BugReport(
            id=generate_id('bug_report', session),
            title=data['title'],
            description=data.get('description', ''),
            reproduction_steps=data['reproduction_steps'],
            expected_result=data['expected_result'],
            actual_result=data['actual_result'],
            environment=data.get('environment', ''),
            priority=data.get('priority', 'Medium'),
            severity=data.get('severity', 'Major'),
            status=data.get('status', 'New'),
            source_channel=data.get('source_channel'),
            external_reference=data.get('external_reference'),
            gitlab_project_id=data.get('gitlab_project_id'),
        )
        session.add(bug_report)
        session.commit()
        session.refresh(bug_report)
        return bug_report
    
    @staticmethod
    def get_by_id(session: Session, bug_report_id: str) -> Optional[BugReport]:
        """Получает баг-репорт по ID"""
        return session.query(BugReport).filter(BugReport.id == bug_report_id).first()
    
    @staticmethod
    def get_all(session: Session,
                status: Optional[str] = None,
                priority: Optional[str] = None,
                severity: Optional[str] = None,
                search: Optional[str] = None,
                date_from: Optional[datetime] = None,
                date_to: Optional[datetime] = None,
                updated_from: Optional[datetime] = None,
                updated_to: Optional[datetime] = None) -> List[BugReport]:
        """Получает список баг-репортов с фильтрацией"""
        query = session.query(BugReport)
        
        if status:
            query = query.filter(BugReport.status == status)
        
        if priority:
            query = query.filter(BugReport.priority == priority)
        
        if severity:
            query = query.filter(BugReport.severity == severity)
        
        if search:
            query = query.filter(
                or_(
                    BugReport.id.like(f'%{search}%'),
                    BugReport.title.like(f'%{search}%'),
                    BugReport.description.like(f'%{search}%'),
                    BugReport.reproduction_steps.like(f'%{search}%'),
                    BugReport.expected_result.like(f'%{search}%'),
                    BugReport.actual_result.like(f'%{search}%'),
                    BugReport.environment.like(f'%{search}%')
                )
            )
        
        if date_from:
            query = query.filter(BugReport.created_at >= date_from)
        
        if date_to:
            query = query.filter(BugReport.created_at <= date_to)
        
        if updated_from:
            query = query.filter(BugReport.updated_at >= updated_from)
        
        if updated_to:
            query = query.filter(BugReport.updated_at <= updated_to)
        
        return query.order_by(BugReport.created_at.desc()).all()
    
    @staticmethod
    def update(session: Session, bug_report_id: str, data: Dict[str, Any]) -> Optional[BugReport]:
        """Обновляет баг-репорт"""
        bug_report = BugReportService.get_by_id(session, bug_report_id)
        if not bug_report:
            return None

        synchronized_fields = {
            'title', 'description', 'reproduction_steps', 'expected_result',
            'actual_result', 'environment', 'source_channel',
            'external_reference', 'status', 'priority', 'severity'
        }
        nullable_fields = {
            'source_channel', 'external_reference', 'gitlab_project_id'
        }
        synchronized_change = any(
            key in synchronized_fields
            and hasattr(bug_report, key)
            and getattr(bug_report, key) != value
            for key, value in data.items()
        )
        for key, value in data.items():
            if (
                hasattr(bug_report, key)
                and (value is not None or key in nullable_fields)
            ):
                setattr(bug_report, key, value)

        if (
            synchronized_change
            and bug_report.gitlab_binding is not None
            and bug_report.gitlab_binding.sync_state in {'synced', 'remote_changed'}
        ):
            bug_report.gitlab_binding.sync_state = 'local_changed'
        
        bug_report.updated_at = datetime.now()
        session.commit()
        session.refresh(bug_report)
        return bug_report
    
    @staticmethod
    def delete(session: Session, bug_report_id: str) -> bool:
        """Удаляет баг-репорт"""
        bug_report = BugReportService.get_by_id(session, bug_report_id)
        if not bug_report:
            return False

        if bug_report.gitlab_binding is not None:
            raise PublishedBugDeleteError(
                "Published bug reports cannot be hard-deleted; close the Issue instead"
            )
        
        session.delete(bug_report)
        session.commit()
        return True


class ArtifactService:
    """Общий сервис для работы с артефактами"""
    
    @staticmethod
    def get_all_artifacts(session: Session,
                          artifact_type: Optional[str] = None,
                          search: Optional[str] = None,
                          date_from: Optional[datetime] = None,
                          date_to: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Получает все артефакты"""
        results = []
        
        if artifact_type in ['test_case', None]:
            test_cases = TestCaseService.get_all(session, search=search, 
                                                   date_from=date_from, date_to=date_to)
            results.extend([tc.to_dict() for tc in test_cases])
        
        if artifact_type in ['bug_report', None]:
            bug_reports = BugReportService.get_all(session, search=search,
                                                     date_from=date_from, date_to=date_to)
            results.extend([br.to_dict() for br in bug_reports])
        
        # Сортировка по дате
        results.sort(key=lambda x: x['created_at'], reverse=True)
        return results
    
    @staticmethod
    def get_artifact_by_id(session: Session, artifact_id: str, artifact_type: str):
        """Получает артефакт по ID и типу"""
        if artifact_type == 'test_case':
            return TestCaseService.get_by_id(session, artifact_id)
        elif artifact_type == 'bug_report':
            return BugReportService.get_by_id(session, artifact_id)
        return None
    
    @staticmethod
    def get_linked_artifacts(session: Session, artifact_id: str, artifact_type: str) -> List[Dict]:
        """Получает связанные артефакты"""
        links = session.query(ArtifactLink).filter(
            ArtifactLink.source_id == artifact_id,
            ArtifactLink.source_type == artifact_type
        ).all()
        
        results = []
        for link in links:
            if link.target_type == 'test_case':
                artifact = TestCaseService.get_by_id(session, link.target_id)
            else:
                artifact = BugReportService.get_by_id(session, link.target_id)
            
            if artifact:
                results.append(artifact.to_dict())
        
        return results

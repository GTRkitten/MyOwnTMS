"""
SQLAlchemy модели базы данных MyOwnTMS
"""
from datetime import datetime
from pathlib import Path
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, declarative_base
from src.config import (
    TEST_CASE_STATUSES, BUG_REPORT_STATUSES, 
    PRIORITIES, SEVERITIES, ATTACHMENTS_DIR
)

Base = declarative_base()


class TestCase(Base):
    """Модель тест-кейса"""
    __tablename__ = 'test_cases'
    
    id = Column(String(20), primary_key=True)  # TC-DDMMYY-XXX
    title = Column(String(200), nullable=False)
    preconditions = Column(Text, default="")
    steps = Column(Text, nullable=False)
    expected_result = Column(Text, nullable=False)
    postconditions = Column(Text, default="")
    environment = Column(Text, default="")
    priority = Column(Enum(*PRIORITIES, name='priority_enum'), default='Medium')
    status = Column(Enum(*TEST_CASE_STATUSES, name='test_case_status_enum'), default='Draft')
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Связи
    attachments = relationship('Attachment', back_populates='test_case', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<TestCase(id='{self.id}', title='{self.title}')>"
    
    def to_dict(self):
        """Преобразовать в словарь"""
        return {
            'id': self.id,
            'title': self.title,
            'preconditions': self.preconditions,
            'steps': self.steps,
            'expected_result': self.expected_result,
            'postconditions': self.postconditions,
            'environment': self.environment,
            'priority': self.priority,
            'status': self.status,
            'created_at': self.created_at.strftime('%d.%m.%Y %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%d.%m.%Y %H:%M:%S')
        }


class BugReport(Base):
    """Модель баг-репорта"""
    __tablename__ = 'bug_reports'
    
    id = Column(String(20), primary_key=True)  # BUG-DDMMYY-XXX
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    reproduction_steps = Column(Text, nullable=False)
    expected_result = Column(Text, nullable=False)
    actual_result = Column(Text, nullable=False)
    environment = Column(Text, default="")
    priority = Column(Enum(*PRIORITIES, name='bug_priority_enum'), default='Medium')
    severity = Column(Enum(*SEVERITIES, name='severity_enum'), default='Major')
    status = Column(Enum(*BUG_REPORT_STATUSES, name='bug_status_enum'), default='New')
    source_channel = Column(String(20), nullable=True)
    external_reference = Column(String(500), nullable=True)
    gitlab_project_id = Column(Integer, ForeignKey('gitlab_projects.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Связи
    attachments = relationship('Attachment', back_populates='bug_report', cascade='all, delete-orphan')
    gitlab_project = relationship('GitLabProject', back_populates='bug_reports')
    gitlab_binding = relationship(
        'GitLabBinding', back_populates='bug_report', uselist=False,
        cascade='all, delete-orphan'
    )
    
    def __repr__(self):
        return f"<BugReport(id='{self.id}', title='{self.title}')>"
    
    def to_dict(self):
        """Преобразовать в словарь"""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'reproduction_steps': self.reproduction_steps,
            'expected_result': self.expected_result,
            'actual_result': self.actual_result,
            'environment': self.environment,
            'priority': self.priority,
            'severity': self.severity,
            'status': self.status,
            'source_channel': self.source_channel,
            'external_reference': self.external_reference,
            'gitlab_project_id': self.gitlab_project_id,
            'created_at': self.created_at.strftime('%d.%m.%Y %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%d.%m.%Y %H:%M:%S')
        }


class Attachment(Base):
    """Модель вложения (файла)"""
    __tablename__ = 'attachments'
    
    id = Column(Integer, primary_key=True)
    artifact_id = Column(String(20), nullable=False)  # ID артефакта
    artifact_type = Column(String(10), nullable=False)  # 'test_case' или 'bug_report'
    file_path = Column(String(500), nullable=False)
    file_name = Column(String(200), nullable=False)
    file_type = Column(String(50), nullable=False)  # MIME тип
    created_at = Column(DateTime, default=datetime.now)
    
    # Внешние ключи
    test_case_id = Column(String(20), ForeignKey('test_cases.id', ondelete='CASCADE'), nullable=True)
    bug_report_id = Column(String(20), ForeignKey('bug_reports.id', ondelete='CASCADE'), nullable=True)
    
    # Связи
    test_case = relationship('TestCase', back_populates='attachments')
    bug_report = relationship('BugReport', back_populates='attachments')
    gitlab_bindings = relationship(
        'GitLabAttachmentBinding', back_populates='attachment',
        cascade='all, delete-orphan'
    )
    
    def __repr__(self):
        return f"<Attachment(id={self.id}, file_name='{self.file_name}')>"
    
    def get_absolute_path(self) -> Path:
        """
        Возвращает абсолютный путь к файлу.
        
        Поддерживает несколько сценариев:
        - Абсолютный путь + файл существует: используется как есть
        - Абсолютный путь + файл не существует: пробуем найти в текущей data/attachments/
        - Относительный путь: присоединяется к текущей data/attachments/
        
        Это обеспечивает обратную совместимость и полную поддержку переносимости EXE.
        """
        from src.config import get_data_dir
        
        path = Path(self.file_path)
        data_dir = get_data_dir()
        attachments_dir = data_dir / "attachments"
        
        # Если путь абсолютный
        if path.is_absolute():
            # Проверяем, существует ли файл по абсолютному пути
            if path.exists():
                return path
            
            # Файл не существует по абсолютному пути (EXE перемещен)
            # Пробуем найти в текущей data/attachments/ по имени файла
            filename = path.name
            fallback_path = attachments_dir / filename
            
            # Если файл найден в текущей папке - возвращаем его
            if fallback_path.exists():
                return fallback_path
            
            # Если файл не найден ни там, ни тут - возвращаем абсолютный путь для ошибки
            return path
        
        # Если путь относительный - присоединяем к текущей data/attachments
        return attachments_dir / self.file_path
    
    def set_relative_path(self, absolute_path: Path) -> None:
        """
        Сохраняет относительный путь к файлу.
        Абсолютный путь конвертируется в относительный относительно ATTACHMENTS_DIR.
        
        Args:
            absolute_path: Абсолютный путь к файлу
        """
        absolute_path = Path(absolute_path).resolve()
        try:
            self.file_path = str(absolute_path.relative_to(ATTACHMENTS_DIR.resolve()))
        except ValueError:
            # Если путь не внутри ATTACHMENTS_DIR, копируем файл и сохраняем относительный путь
            import shutil
            relative_path = absolute_path.name
            dest_path = ATTACHMENTS_DIR / relative_path
            shutil.copy2(absolute_path, dest_path)
            self.file_path = relative_path


class ArtifactLink(Base):
    """Модель связи между артефактами"""
    __tablename__ = 'artifact_links'
    
    id = Column(Integer, primary_key=True)
    source_id = Column(String(20), nullable=False)
    source_type = Column(String(10), nullable=False)  # 'test_case' или 'bug_report'
    target_id = Column(String(20), nullable=False)
    target_type = Column(String(10), nullable=False)  # 'test_case' или 'bug_report'
    link_type = Column(String(50), default='related')  # Тип связи: 'related', 'causes', 'blocked_by'
    created_at = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<ArtifactLink(source='{self.source_id}', target='{self.target_id}')>"


class GitLabProject(Base):
    """Validated private GitLab project profile (never stores a token)."""

    __tablename__ = 'gitlab_projects'

    id = Column(Integer, primary_key=True)
    display_name = Column(String(200), nullable=False)
    gitlab_project_id = Column(Integer, nullable=False, unique=True)
    path_with_namespace = Column(String(500), nullable=False)
    web_url = Column(String(1000), nullable=False)
    visibility = Column(String(20), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    labels_ready_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    bug_reports = relationship('BugReport', back_populates='gitlab_project')
    bindings = relationship('GitLabBinding', back_populates='project')


class GitLabBinding(Base):
    """Local cache and resumable state for one published bug."""

    __tablename__ = 'gitlab_bindings'

    id = Column(Integer, primary_key=True)
    bug_report_id = Column(
        String(20), ForeignKey('bug_reports.id', ondelete='CASCADE'),
        nullable=False, unique=True
    )
    sync_uid = Column(String(36), nullable=False, unique=True)
    project_id = Column(Integer, ForeignKey('gitlab_projects.id'), nullable=False)
    issue_id = Column(Integer, nullable=True)
    issue_iid = Column(Integer, nullable=True)
    issue_web_url = Column(String(1000), nullable=True)
    remote_updated_at = Column(DateTime, nullable=True)
    base_snapshot = Column(Text, nullable=True)
    sync_state = Column(String(30), nullable=False, default='local_only')
    last_error_type = Column(String(100), nullable=True)
    last_error_http_status = Column(Integer, nullable=True)
    last_error_request_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    bug_report = relationship('BugReport', back_populates='gitlab_binding')
    project = relationship('GitLabProject', back_populates='bindings')
    attachment_bindings = relationship(
        'GitLabAttachmentBinding', back_populates='gitlab_binding',
        cascade='all, delete-orphan'
    )


class GitLabAttachmentBinding(Base):
    """Remote upload metadata for one immutable local attachment revision."""

    __tablename__ = 'gitlab_attachment_bindings'
    __table_args__ = (
        UniqueConstraint('attachment_id', 'content_sha256'),
    )

    id = Column(Integer, primary_key=True)
    gitlab_binding_id = Column(
        Integer, ForeignKey('gitlab_bindings.id', ondelete='CASCADE'), nullable=False
    )
    attachment_id = Column(
        Integer, ForeignKey('attachments.id', ondelete='CASCADE'), nullable=False
    )
    content_sha256 = Column(String(64), nullable=False)
    remote_upload_id = Column(String(255), nullable=True)
    remote_url = Column(String(1000), nullable=True)
    remote_markdown = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, nullable=True)

    gitlab_binding = relationship(
        'GitLabBinding', back_populates='attachment_bindings'
    )
    attachment = relationship('Attachment', back_populates='gitlab_bindings')


class SchemaMigration(Base):
    """Applied embedded migration identifier."""

    __tablename__ = 'schema_migrations'

    migration_id = Column(String(100), primary_key=True)
    applied_at = Column(DateTime, nullable=False)

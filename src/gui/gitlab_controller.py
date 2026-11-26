"""Threaded, session-scoped boundary between Qt widgets and GitLab services."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from src.database.session import get_session
from src.integrations.gitlab_client import (
    GitLabApiClient,
    GitLabClientConfig,
    GitLabConfigurationError,
    GitLabTokenRequiredError,
    SessionToken,
)


WorkerOperation = Callable[[Any, GitLabApiClient], Any]


class GitLabWorkerSignals(QObject):
    """Signals emitted by one worker; result delivery is queued to the GUI."""

    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()


class GitLabWorker(QRunnable):
    """Run one GitLab operation with its own client and SQLAlchemy session."""

    def __init__(
        self,
        *,
        config: GitLabClientConfig,
        session_token: SessionToken,
        operation: WorkerOperation,
        session_factory: Callable[[], Any],
        client_factory: Callable[[GitLabClientConfig, SessionToken], GitLabApiClient],
    ) -> None:
        super().__init__()
        self.signals = GitLabWorkerSignals()
        self._config = config
        self._session_token = session_token
        self._operation = operation
        self._session_factory = session_factory
        self._client_factory = client_factory

    @Slot()
    def run(self) -> None:
        session = None
        client = None
        result = None
        failure = None
        try:
            session = self._session_factory()
            client = self._client_factory(self._config, self._session_token)
            result = self._operation(session, client)
        except BaseException as error:
            failure = error
            if session is not None:
                session.rollback()
        finally:
            if client is not None:
                client.close()
            if session is not None:
                session.close()
            self.signals.finished.emit()
        if failure is None:
            self.signals.succeeded.emit(result)
        else:
            self.signals.failed.emit(failure)


class GitLabSessionController(QObject):
    """Own in-memory GitLab settings and schedule explicit network actions."""

    busy_changed = Signal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        session_factory: Callable[[], Any] = get_session,
        client_factory: Callable[[GitLabClientConfig, SessionToken], GitLabApiClient] | None = None,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._client_factory = client_factory or (
            lambda config, token: GitLabApiClient(config, token)
        )
        self._thread_pool = thread_pool or QThreadPool(self)
        self._session_token = SessionToken()
        self._config: GitLabClientConfig | None = None
        self._active_workers: set[GitLabWorker] = set()
        self._workers_by_signal: dict[QObject, GitLabWorker] = {}
        self._shutting_down = False

    @property
    def origin(self) -> str:
        return self._config.origin if self._config is not None else ""

    @property
    def ca_bundle(self) -> str:
        if self._config is None or self._config.ca_bundle is None:
            return ""
        return str(self._config.ca_bundle)

    @property
    def token_is_set(self) -> bool:
        return self._session_token.is_set

    @property
    def is_busy(self) -> bool:
        return bool(self._active_workers)

    def configure(self, origin: str, ca_bundle: str | Path | None = None) -> None:
        normalized_ca = None if not ca_bundle else Path(ca_bundle)
        new_config = GitLabClientConfig(origin=origin, ca_bundle=normalized_ca)
        old_identity = (
            self._config.origin,
            self._config.ca_bundle,
        ) if self._config is not None else None
        new_identity = (new_config.origin, new_config.ca_bundle)
        self._config = new_config
        if old_identity is not None and old_identity != new_identity:
            self._session_token.clear()

    def set_token(self, token: str) -> None:
        self._session_token.set(token)

    def clear_token(self) -> None:
        self._session_token.clear()

    def require_ready(self) -> None:
        if self._config is None:
            raise GitLabConfigurationError("GitLab connection is not configured")
        if not self._session_token.is_set:
            raise GitLabTokenRequiredError(
                "GitLab token is required for this session"
            )
        if self._shutting_down:
            raise GitLabConfigurationError("GitLab operations are shutting down")

    def start(
        self,
        operation: WorkerOperation,
        *,
        succeeded: Callable[[Any], None] | None = None,
        failed: Callable[[BaseException], None] | None = None,
        finished: Callable[[], None] | None = None,
    ) -> GitLabWorker:
        """Schedule one explicit action after connecting its result handlers."""

        self.require_ready()
        worker = GitLabWorker(
            config=self._config,
            session_token=self._session_token,
            operation=operation,
            session_factory=self._session_factory,
            client_factory=self._client_factory,
        )
        if succeeded is not None:
            worker.signals.succeeded.connect(succeeded)
        if failed is not None:
            worker.signals.failed.connect(failed)
        if finished is not None:
            worker.signals.finished.connect(finished)
        worker.signals.finished.connect(self._worker_finished)
        was_busy = self.is_busy
        self._active_workers.add(worker)
        self._workers_by_signal[worker.signals] = worker
        if not was_busy:
            self.busy_changed.emit(True)
        self._thread_pool.start(worker)
        return worker

    @Slot()
    def _worker_finished(self) -> None:
        worker = self._workers_by_signal.pop(self.sender(), None)
        if worker is None:
            return
        self._active_workers.discard(worker)
        if not self._active_workers:
            self.busy_changed.emit(False)

    def shutdown(self) -> None:
        """Stop accepting work and drain operations already running in the pool."""

        self._shutting_down = True
        # clear() only removes queued runnables; an active operation may still
        # own a DB session and need the session token for its remaining requests.
        self._thread_pool.clear()
        self._thread_pool.waitForDone()
        self._session_token.clear()

        was_busy = self.is_busy
        self._active_workers.clear()
        self._workers_by_signal.clear()
        if was_busy:
            self.busy_changed.emit(False)


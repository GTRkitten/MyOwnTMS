"""Read-only GitLab publish/sync previews and explicit conflict choices."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


FIELD_LABELS = {
    "title": "Заголовок",
    "description": "Описание",
    "reproduction_steps": "Шаги воспроизведения",
    "expected_result": "Ожидаемый результат",
    "actual_result": "Фактический результат",
    "environment": "Окружение",
    "source_channel": "Канал источника",
    "external_reference": "Внешний номер",
    "status": "Статус",
    "priority": "Приоритет",
    "severity": "Серьёзность",
}


def _item(value: object) -> QTableWidgetItem:
    text = "" if value is None else str(value)
    item = QTableWidgetItem(text)
    item.setToolTip(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class PublishPreviewDialog(QDialog):
    """Show every field, label, and file before the first publish write."""

    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview публикации в GitLab")
        self.setMinimumSize(900, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"Проект: {preview.project_display_name} "
                f"({preview.project_path_with_namespace})\n"
                f"Issue: {preview.issue_title}"
            )
        )

        fields = QTableWidget(len(preview.fields), 2)
        fields.setHorizontalHeaderLabels(["Поле", "Передаваемое значение"])
        for row, field in enumerate(preview.fields):
            fields.setItem(row, 0, _item(FIELD_LABELS.get(field.name, field.name)))
            fields.setItem(row, 1, _item(field.value))
        fields.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        fields.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(fields)

        labels = QPlainTextEdit(", ".join(preview.labels))
        labels.setReadOnly(True)
        labels.setMaximumHeight(70)
        layout.addWidget(QLabel("Managed labels:"))
        layout.addWidget(labels)

        files = QTableWidget(len(preview.files), 4)
        files.setHorizontalHeaderLabels(["Файл", "Размер", "Действие", "Причина пропуска"])
        for row, file_preview in enumerate(preview.files):
            files.setItem(row, 0, _item(file_preview.display_name))
            files.setItem(row, 1, _item(file_preview.size_bytes or ""))
            files.setItem(row, 2, _item("Загрузить" if file_preview.will_upload else "Не передавать"))
            files.setItem(row, 3, _item(file_preview.skip_reason or ""))
        files.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("Файлы:"))
        layout.addWidget(files)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Опубликовать")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SyncPreviewDialog(QDialog):
    """Show base/local/remote and the intended non-conflicting result."""

    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview синхронизации GitLab")
        self.setMinimumSize(1050, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"Действие: {preview.action}; Issue !{preview.issue_iid}. "
                "Запись выполняется только после подтверждения."
            )
        )
        table = QTableWidget(len(FIELD_LABELS), 5)
        table.setHorizontalHeaderLabels(["Поле", "Base", "Local", "Remote", "Итог"])
        for row, name in enumerate(FIELD_LABELS):
            table.setItem(row, 0, _item(FIELD_LABELS[name]))
            table.setItem(row, 1, _item(getattr(preview.base, name)))
            table.setItem(row, 2, _item(getattr(preview.local, name)))
            table.setItem(row, 3, _item(getattr(preview.remote, name)))
            table.setItem(row, 4, _item(getattr(preview.merged, name)))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, 5):
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Подтвердить")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ConflictResolutionDialog(QDialog):
    """Require one local/remote choice for every same-field conflict."""

    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Конфликт синхронизации GitLab")
        self.setMinimumSize(1050, 520)
        self._selectors: dict[str, QComboBox] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Для каждого конфликтующего поля выберите Local или Remote.")
        )
        table = QTableWidget(len(preview.conflicts), 5)
        table.setHorizontalHeaderLabels(["Поле", "Base", "Local", "Remote", "Выбор"])
        for row, conflict in enumerate(preview.conflicts):
            table.setItem(row, 0, _item(FIELD_LABELS.get(conflict.field, conflict.field)))
            table.setItem(row, 1, _item(conflict.base))
            table.setItem(row, 2, _item(conflict.local))
            table.setItem(row, 3, _item(conflict.remote))
            selector = QComboBox()
            selector.addItem("Выберите…", None)
            selector.addItem("Local", "local")
            selector.addItem("Remote", "remote")
            self._selectors[conflict.field] = selector
            table.setCellWidget(row, 4, selector)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, 4):
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Применить выбор")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def resolutions(self) -> dict[str, str]:
        return {
            field: selector.currentData()
            for field, selector in self._selectors.items()
            if selector.currentData() in {"local", "remote"}
        }

    def _validate_and_accept(self) -> None:
        if len(self.resolutions) != len(self._selectors):
            QMessageBox.warning(
                self, "Конфликт", "Выберите Local или Remote для каждого поля"
            )
            return
        self.accept()


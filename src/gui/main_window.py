"""
Главное окно приложения MyOwnTMS
"""
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTabWidget, QPushButton, QLabel, QStatusBar,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QComboBox, QMessageBox, QFileDialog,
    QToolBar, QMenu, QMenuBar, QSplitter, QGroupBox, QFormLayout,
    QDateEdit, QCheckBox, QDialog, QProgressBar
)
from PySide6.QtCore import QDate
from PySide6.QtCore import Qt, QSize, QUrl, Slot
from PySide6.QtGui import QIcon, QAction, QDesktopServices

from src.config import APP_NAME, APP_VERSION, STYLE_PATH
from src.database.session import get_session
from src.services.artifact_service import (
    ArtifactService,
    BugReportService,
    PublishedBugDeleteError,
    TestCaseService,
)
from src.services.link_service import LinkService
from src.services.attachment_service import AttachmentService
from src.gui.widgets.test_case_dialog import TestCaseDialog
from src.gui.widgets.bug_report_dialog import BugReportDialog
from src.gui.widgets.artifact_detail_dialog import ArtifactDetailDialog
from src.gui.widgets.export_dialog import ExportDialog
from src.gui.gitlab_controller import GitLabSessionController
from src.gui.widgets.gitlab_settings_dialog import GitLabSettingsDialog
from src.gui.widgets.gitlab_sync_dialogs import (
    ConflictResolutionDialog,
    SyncPreviewDialog,
)
from src.services.gitlab_sync_service import GitLabSyncService


class MainWindow(QMainWindow):
    """Главное окно приложения"""
    
    def __init__(self, session=None, gitlab_controller=None):
        super().__init__()
        self.current_tab = 'test_cases'
        self.session = session or get_session()
        self.gitlab_controller = gitlab_controller or GitLabSessionController(self)
        self.current_artifacts = []
        self.selected_artifacts = []
        self.sort_column = None
        self.sort_order = Qt.AscendingOrder
        self._gitlab_busy = False
        self._pending_sync_preview = None
        
        self.init_ui()
        self.load_artifacts()
    
    def init_ui(self):
        """Инициализирует пользовательский интерфейс"""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1200, 800)
        
        # Применяем стили
        self.apply_styles()
        
        # Создаем меню
        self.create_menu()
        
        # Создаем панель инструментов
        self.create_toolbar()
        
        # Создаем центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Основной layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Верхняя панель с поиском и фильтрами
        search_layout = self.create_search_panel()
        main_layout.addLayout(search_layout)
        
        # Вкладки
        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_test_cases_tab(), "Тест-кейсы")
        self.tabs.addTab(self.create_bug_reports_tab(), "Баг-репорты")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        main_layout.addWidget(self.tabs)
        
        # Статус бар
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Готово")
    
    def create_menu(self):
        """Создает меню приложения"""
        menubar = self.menuBar()
        
        # Файл
        file_menu = menubar.addMenu("Файл")
        
        new_tc_action = QAction("Новый тест-кейс", self)
        new_tc_action.setShortcut("Ctrl+N")
        new_tc_action.triggered.connect(lambda: self.create_artifact('test_case'))
        file_menu.addAction(new_tc_action)
        
        new_br_action = QAction("Новый баг-репорт", self)
        new_br_action.setShortcut("Ctrl+Shift+N")
        new_br_action.triggered.connect(lambda: self.create_artifact('bug_report'))
        file_menu.addAction(new_br_action)
        
        file_menu.addSeparator()
        
        export_action = QAction("Экспорт", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_artifacts)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Выход", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Правка
        edit_menu = menubar.addMenu("Правка")
        
        self.edit_action = QAction("Редактировать", self)
        self.edit_action.setShortcut("Ctrl+R")
        self.edit_action.setEnabled(False)
        self.edit_action.triggered.connect(self.edit_artifact)
        edit_menu.addAction(self.edit_action)
        
        deselect_action = QAction("Снять выделение", self)
        deselect_action.setShortcut("Escape")
        deselect_action.triggered.connect(self.deselect_all)
        edit_menu.addAction(deselect_action)
        
        delete_action = QAction("Удалить", self)
        delete_action.setShortcut("Del")
        delete_action.triggered.connect(self.delete_artifact)
        edit_menu.addAction(delete_action)

        # GitLab
        gitlab_menu = menubar.addMenu("GitLab")
        settings_action = QAction("Настройки и проекты", self)
        settings_action.triggered.connect(self.open_gitlab_settings)
        gitlab_menu.addAction(settings_action)
        
        # Справка
        help_menu = menubar.addMenu("Справка")
        
        about_action = QAction("О программе", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def create_toolbar(self):
        """Создает панель инструментов"""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # Новые артефакты
        new_tc_btn = QPushButton("Тест-кейс")
        new_tc_btn.setProperty("primary", True)
        new_tc_btn.clicked.connect(lambda: self.create_artifact('test_case'))
        toolbar.addWidget(new_tc_btn)
        
        new_br_btn = QPushButton("Баг-репорт")
        new_br_btn.setProperty("primary", True)
        new_br_btn.clicked.connect(lambda: self.create_artifact('bug_report'))
        toolbar.addWidget(new_br_btn)
        
        toolbar.addSeparator()
        
        # Редактирование
        self.edit_btn = QPushButton("Редактировать")
        self.edit_btn.setProperty("warning", True)
        self.edit_btn.setEnabled(False)
        self.edit_btn.clicked.connect(self.edit_artifact)
        toolbar.addWidget(self.edit_btn)
        
        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.setProperty("danger", True)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.delete_artifact)
        toolbar.addWidget(self.delete_btn)
        
        toolbar.addSeparator()
        
        # Экспорт
        export_btn = QPushButton("Экспорт")
        export_btn.setProperty("success", True)
        export_btn.clicked.connect(self.export_artifacts)
        toolbar.addWidget(export_btn)

        self.sync_btn = QPushButton("Синхронизировать")
        self.sync_btn.setProperty("sync", True)
        self.sync_btn.setEnabled(False)
        self.sync_btn.setVisible(False)
        self.sync_btn.clicked.connect(self.sync_selected_bug_report)
        toolbar.addWidget(self.sync_btn)

        self.open_gitlab_btn = QPushButton("Открыть в GitLab")
        self.open_gitlab_btn.setProperty("gitlabOpen", True)
        self.open_gitlab_btn.setEnabled(False)
        self.open_gitlab_btn.setVisible(False)
        self.open_gitlab_btn.clicked.connect(self.open_selected_bug_report_in_gitlab)
        toolbar.addWidget(self.open_gitlab_btn)

        self.gitlab_progress = QProgressBar()
        self.gitlab_progress.setRange(0, 0)
        self.gitlab_progress.setMaximumWidth(100)
        self.gitlab_progress.setVisible(False)
        toolbar.addWidget(self.gitlab_progress)
    
    def create_search_panel(self):
        """Создает панель поиска и фильтрации"""
        # Основной layout
        main_layout = QVBoxLayout()
        
        # Верхняя строка с поиском
        top_layout = QHBoxLayout()
        
        # Поиск
        search_label = QLabel("Поиск:")
        top_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите текст для поиска...")
        self.search_input.textChanged.connect(self.on_search_changed)
        top_layout.addWidget(self.search_input)
        
        # Фильтр по статусу
        status_label = QLabel("Статус:")
        top_layout.addWidget(status_label)
        
        self.status_filter = QComboBox()
        self.status_filter.addItem("Все статусы")
        self.status_filter.currentTextChanged.connect(self.on_filter_changed)
        top_layout.addWidget(self.status_filter)
        
        # Фильтр по приоритету
        priority_label = QLabel("Приоритет:")
        top_layout.addWidget(priority_label)
        
        self.priority_filter = QComboBox()
        self.priority_filter.addItem("Все приоритеты")
        self.priority_filter.addItems(["Низкий", "Средний", "Высокий", "Критический"])
        self.priority_filter.currentTextChanged.connect(self.on_filter_changed)
        top_layout.addWidget(self.priority_filter)
        
        # Фильтр по серьезности (только для баг-репортов)
        severity_label = QLabel("Серьезность:")
        top_layout.addWidget(severity_label)
        
        self.severity_filter = QComboBox()
        self.severity_filter.addItem("Все серьезности")
        self.severity_filter.addItems(["Тривиальный", "Минорный", "Мажорный", "Критический", "Блокирующий"])
        self.severity_filter.currentTextChanged.connect(self.on_filter_changed)
        top_layout.addWidget(self.severity_filter)
        
        main_layout.addLayout(top_layout)
        
        # Нижняя строка с датами
        date_layout = QHBoxLayout()
        
        # Дата создания (от)
        created_from_label = QLabel("Создан от:")
        date_layout.addWidget(created_from_label)
        
        self.created_from_filter = QDateEdit()
        self.created_from_filter.setCalendarPopup(True)
        self.created_from_filter.setDateRange(QDate(2020, 1, 1), QDate.currentDate())
        self.created_from_filter.setDate(QDate(2020, 1, 1))
        self.created_from_filter.setDisplayFormat("dd.MM.yyyy")
        self.created_from_filter.dateChanged.connect(self.on_filter_changed)
        date_layout.addWidget(self.created_from_filter)
        
        # Дата создания (до)
        created_to_label = QLabel("до:")
        date_layout.addWidget(created_to_label)
        
        self.created_to_filter = QDateEdit()
        self.created_to_filter.setCalendarPopup(True)
        self.created_to_filter.setDateRange(QDate(2020, 1, 1), QDate.currentDate())
        self.created_to_filter.setDate(QDate.currentDate())
        self.created_to_filter.setDisplayFormat("dd.MM.yyyy")
        self.created_to_filter.dateChanged.connect(self.on_filter_changed)
        date_layout.addWidget(self.created_to_filter)
        
        date_layout.addSpacing(20)
        
        # Дата обновления (от)
        updated_from_label = QLabel("Обновлен от:")
        date_layout.addWidget(updated_from_label)
        
        self.updated_from_filter = QDateEdit()
        self.updated_from_filter.setCalendarPopup(True)
        self.updated_from_filter.setDateRange(QDate(2020, 1, 1), QDate.currentDate())
        self.updated_from_filter.setDate(QDate(2020, 1, 1))
        self.updated_from_filter.setDisplayFormat("dd.MM.yyyy")
        self.updated_from_filter.dateChanged.connect(self.on_filter_changed)
        date_layout.addWidget(self.updated_from_filter)
        
        # Дата обновления (до)
        updated_to_label = QLabel("до:")
        date_layout.addWidget(updated_to_label)
        
        self.updated_to_filter = QDateEdit()
        self.updated_to_filter.setCalendarPopup(True)
        self.updated_to_filter.setDateRange(QDate(2020, 1, 1), QDate.currentDate())
        self.updated_to_filter.setDate(QDate.currentDate())
        self.updated_to_filter.setDisplayFormat("dd.MM.yyyy")
        self.updated_to_filter.dateChanged.connect(self.on_filter_changed)
        date_layout.addWidget(self.updated_to_filter)
        
        date_layout.addStretch()
        
        # Кнопка сброса фильтров
        reset_filters_btn = QPushButton("Сбросить фильтры")
        reset_filters_btn.clicked.connect(self.reset_filters)
        date_layout.addWidget(reset_filters_btn)
        
        # Кнопка обновления
        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self.load_artifacts)
        date_layout.addWidget(refresh_btn)
        
        main_layout.addLayout(date_layout)
        
        return main_layout
    
    def create_test_cases_tab(self):
        """Создает вкладку с тест-кейсами"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Таблица
        self.test_cases_table = QTableWidget()
        self.test_cases_table.setColumnCount(6)
        self.test_cases_table.setHorizontalHeaderLabels([
            "ID", "Заголовок", "Статус", "Приоритет", "Создан", "Обновлен"
        ])
        self.test_cases_table.horizontalHeader().setStretchLastSection(True)
        self.test_cases_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.test_cases_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        self.test_cases_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.test_cases_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.test_cases_table.doubleClicked.connect(self.view_artifact)
        self.test_cases_table.itemSelectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.test_cases_table)
        
        # Настраиваем фильтры для тест-кейсов
        self.status_filter.clear()
        self.status_filter.addItem("Все статусы")
        self.status_filter.addItems(["Черновик", "Готов", "Пройден", "Провален", "Заблокирован"])
        
        return widget
    
    def create_bug_reports_tab(self):
        """Создает вкладку с баг-репортами"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Таблица
        self.bug_reports_table = QTableWidget()
        self.bug_reports_table.setColumnCount(9)
        self.bug_reports_table.setHorizontalHeaderLabels([
            "ID", "Заголовок", "Статус", "Приоритет", "Серьезность",
            "GitLab project", "Sync", "Создан", "Обновлен"
        ])
        self.bug_reports_table.horizontalHeader().setStretchLastSection(True)
        self.bug_reports_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.bug_reports_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        self.bug_reports_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.bug_reports_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.bug_reports_table.doubleClicked.connect(self.view_artifact)
        self.bug_reports_table.itemSelectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.bug_reports_table)
        
        return widget
    
    def apply_styles(self):
        """Применяет стили к приложению"""
        try:
            style_path = STYLE_PATH
            print(f"Путь к стилям: {style_path}")
            print(f"Стили существуют: {style_path.exists()}")
            
            if style_path.exists():
                with open(style_path, 'r', encoding='utf-8') as f:
                    styles = f.read()
                    self.setStyleSheet(styles)
                    print(f"Стили загружены успешно ({len(styles)} символов)")
            else:
                print(f"Файл стилей не найден: {style_path}")
                # Применяем встроенные стили если файл не найден
                self.apply_fallback_styles()
        except Exception as e:
            print(f"Не удалось загрузить стили: {e}")
            # Применяем встроенные стили при ошибке
            self.apply_fallback_styles()
    
    def apply_fallback_styles(self):
        """Применяет встроенные стили если файл не найден"""
        styles = """
        QMainWindow {
            background-color: #F5F7FA;
        }
        
        QWidget {
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 10pt;
            color: #2C3E50;
        }
        
        QPushButton {
            background-color: #3498DB;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 8px 16px;
            font-weight: bold;
        }
        
        QPushButton:hover {
            background-color: #2980B9;
        }
        
        QPushButton[primary="true"] {
            background-color: #3498DB;
        }
        
        QPushButton[success="true"] {
            background-color: #27AE60;
        }
        
        QPushButton[success="true"]:hover {
            background-color: #229954;
        }

        QPushButton[warning="true"] {
            background-color: #F1C40F;
            color: #2C3E50;
        }

        QPushButton[warning="true"]:hover {
            background-color: #D4AC0D;
        }

        QPushButton[sync="true"] {
            background-color: #3498DB;
        }

        QPushButton[sync="true"]:hover {
            background-color: #2980B9;
        }

        QPushButton[gitlabOpen="true"] {
            background-color: #E67E22;
        }

        QPushButton[gitlabOpen="true"]:hover {
            background-color: #CA6F1E;
        }

        QPushButton[warning="true"]:disabled,
        QPushButton[sync="true"]:disabled,
        QPushButton[gitlabOpen="true"]:disabled {
            background-color: #BDC3C7;
            color: #7F8C8D;
        }
        
        QPushButton[danger="true"] {
            background-color: #E74C3C;
        }
        
        QPushButton[danger="true"]:hover {
            background-color: #C0392B;
        }
        
        QLineEdit, QTextEdit, QComboBox {
            border: 1px solid #E0E6ED;
            border-radius: 4px;
            padding: 6px;
            background-color: white;
        }
        
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
            border: 1px solid #3498DB;
        }
        
        QTableWidget {
            background-color: white;
            border: 1px solid #E0E6ED;
            border-radius: 4px;
            gridline-color: #E0E6ED;
        }
        
        QTableWidget::item {
            padding: 4px;
        }
        
        QTableWidget::item:selected {
            background-color: #3498DB;
            color: white;
        }
        
        QHeaderView::section {
            background-color: #F5F7FA;
            padding: 6px;
            border: none;
            border-right: 1px solid #E0E6ED;
            border-bottom: 1px solid #E0E6ED;
            font-weight: bold;
        }
        
        QTabWidget::pane {
            border: 1px solid #E0E6ED;
            border-radius: 4px;
            background-color: white;
        }
        
        QTabBar::tab {
            background-color: #E0E6ED;
            padding: 8px 16px;
            margin-right: 2px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }
        
        QTabBar::tab:selected {
            background-color: white;
            color: #3498DB;
        }
        
        QLabel[heading="true"] {
            font-size: 16pt;
            font-weight: bold;
            color: #2C3E50;
        }
        
        QLabel[subheading="true"] {
            font-size: 12pt;
            font-weight: bold;
            color: #3498DB;
        }
        
        QLabel[dimmed="true"] {
            color: #7F8C8D;
        }
        
        QStatusBar {
            background-color: #F5F7FA;
            border-top: 1px solid #E0E6ED;
        }
        
        QMenuBar {
            background-color: #F5F7FA;
            border-bottom: 1px solid #E0E6ED;
        }
        
        QMenuBar::item {
            padding: 6px 12px;
        }
        
        QMenuBar::item:selected {
            background-color: #3498DB;
            color: white;
        }
        
        QToolBar {
            background-color: white;
            border: 1px solid #E0E6ED;
            spacing: 6px;
        }
        """
        self.setStyleSheet(styles)
    
    def on_tab_changed(self, index):
        """Обрабатывает изменение вкладки"""
        if index == 0:
            self.current_tab = 'test_cases'
            self.status_filter.clear()
            self.status_filter.addItem("Все статусы")
            self.status_filter.addItems(["Черновик", "Готов", "Пройден", "Провален", "Заблокирован"])
        else:
            self.current_tab = 'bug_reports'
            self.status_filter.clear()
            self.status_filter.addItem("Все статусы")
            self.status_filter.addItems(["Новый", "В работе", "Проверен", "Закрыт"])
        
        self.load_artifacts()
    
    def on_search_changed(self, text):
        """Обрабатывает изменение текста поиска"""
        self.load_artifacts()
    
    def on_filter_changed(self, value):
        """Обрабатывает изменение фильтра"""
        self.load_artifacts()
    
    def on_header_clicked(self, column):
        """Обрабатывает клик по заголовку таблицы для сортировки"""
        # Если кликнули на ту же колонку - меняем порядок
        if self.sort_column == column:
            self.sort_order = Qt.DescendingOrder if self.sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self.sort_column = column
            self.sort_order = Qt.AscendingOrder
        
        # Перегружаем артефакты с сортировкой
        self.load_artifacts()
    
    def on_selection_changed(self):
        """Обрабатывает изменение выделения"""
        self._update_action_states()

    def _update_action_states(self):
        """Обновляет действия с учетом вкладки, выбора и GitLab binding."""
        selected_rows = self.get_current_table().selectionModel().selectedRows()
        selection_count = len(selected_rows)
        has_single_selection = selection_count == 1
        is_bug_tab = self.current_tab == 'bug_reports'

        can_edit = has_single_selection and not self._gitlab_busy
        self.edit_btn.setEnabled(can_edit)
        self.edit_action.setEnabled(can_edit)
        self.delete_btn.setEnabled(selection_count > 0 and not self._gitlab_busy)

        self.sync_btn.setVisible(is_bug_tab)
        self.open_gitlab_btn.setVisible(is_bug_tab)
        if not is_bug_tab or not has_single_selection or self._gitlab_busy:
            self.sync_btn.setEnabled(False)
            self.open_gitlab_btn.setEnabled(False)
            return

        row = selected_rows[0].row()
        item = self.bug_reports_table.item(row, 0)
        bug = BugReportService.get_by_id(self.session, item.text()) if item else None
        binding = bug.gitlab_binding if bug is not None else None
        self.sync_btn.setEnabled(
            self.gitlab_controller is not None
            and binding is not None
            and binding.issue_iid is not None
        )
        self.open_gitlab_btn.setEnabled(
            binding is not None and bool(binding.issue_web_url)
        )
    
    def get_current_table(self):
        """Возвращает текущую таблицу"""
        if self.current_tab == 'test_cases':
            return self.test_cases_table
        return self.bug_reports_table
    
    def load_artifacts(self):
        """Загружает артефакты в таблицу с учетом всех фильтров"""
        # Получаем значения фильтров
        search_text = self.search_input.text() if self.search_input.text() else None
        status_filter = self.status_filter.currentText()
        priority_filter = self.priority_filter.currentText()
        severity_filter = self.severity_filter.currentText()
        
        # Преобразуем значения "Все" в None
        if status_filter == "Все статусы":
            status_filter = None
        if priority_filter == "Все приоритеты":
            priority_filter = None
        if severity_filter == "Все серьезности":
            severity_filter = None
        
        # Получаем даты
        created_from = self.created_from_filter.date().toPython()
        created_to = self.created_to_filter.date().toPython()
        updated_from = self.updated_from_filter.date().toPython()
        updated_to = self.updated_to_filter.date().toPython()
        
        # Устанавливаем время в конце дня для корректного фильтрации
        created_to = datetime.combine(created_to, datetime.max.time())
        updated_to = datetime.combine(updated_to, datetime.max.time())
        
        if self.current_tab == 'test_cases':
            artifacts = TestCaseService.get_all(
                self.session,
                search=search_text,
                status=status_filter,
                priority=priority_filter,
                date_from=created_from,
                date_to=created_to,
                updated_from=updated_from,
                updated_to=updated_to
            )
            # Применяем сортировку
            artifacts = self.sort_artifacts(artifacts, 'test_case')
            self.fill_test_cases_table(artifacts)
        else:
            artifacts = BugReportService.get_all(
                self.session,
                search=search_text,
                status=status_filter,
                priority=priority_filter,
                severity=severity_filter,
                date_from=created_from,
                date_to=created_to,
                updated_from=updated_from,
                updated_to=updated_to
            )
            # Применяем сортировку
            artifacts = self.sort_artifacts(artifacts, 'bug_report')
            self.fill_bug_reports_table(artifacts)
        
        self.statusBar().showMessage(f"Загружено {len(artifacts)} артефактов")
        self._update_action_states()
    
    def reset_filters(self):
        """Сбрасывает все фильтры"""
        # Сбрасываем текст поиска
        self.search_input.clear()
        
        # Сбрасываем фильтры по статусам и приоритетам
        self.status_filter.setCurrentIndex(0)
        self.priority_filter.setCurrentIndex(0)
        self.severity_filter.setCurrentIndex(0)
        
        # Сбрасываем даты
        self.created_from_filter.setDate(QDate(2020, 1, 1))
        self.created_to_filter.setDate(QDate.currentDate())
        self.updated_from_filter.setDate(QDate(2020, 1, 1))
        self.updated_to_filter.setDate(QDate.currentDate())
        
        # Перезагружаем артефакты
        self.load_artifacts()
        self.statusBar().showMessage("Фильтры сброшены")
    
    def sort_artifacts(self, artifacts, artifact_type):
        """Сортирует артефакты по выбранной колонке"""
        if self.sort_column is None:
            return artifacts
        
        # Определяем поле для сортировки
        column_mapping = {
            0: 'id',
            1: 'title',
            2: 'status',
            3: 'priority',
        }
        
        if artifact_type == 'bug_report':
            column_mapping[4] = 'severity'
            column_mapping[7] = 'created_at'
            column_mapping[8] = 'updated_at'
        else:
            column_mapping[4] = 'created_at'
            column_mapping[5] = 'updated_at'
        
        sort_field = column_mapping.get(self.sort_column)
        if not sort_field:
            return artifacts
        
        # Сортируем
        reverse = self.sort_order == Qt.DescendingOrder
        try:
            # Для полей с датами используем timestamp для корректного сравнения
            if sort_field in ('created_at', 'updated_at'):
                artifacts.sort(key=lambda x: getattr(x, sort_field).timestamp(), reverse=reverse)
            else:
                artifacts.sort(key=lambda x: getattr(x, sort_field), reverse=reverse)
        except:
            pass
        
        return artifacts
    
    def fill_test_cases_table(self, test_cases):
        """Заполняет таблицу тест-кейсов"""
        self.test_cases_table.setRowCount(len(test_cases))
        
        for row, tc in enumerate(test_cases):
            self.test_cases_table.setItem(row, 0, QTableWidgetItem(tc.id))
            self.test_cases_table.setItem(row, 1, QTableWidgetItem(tc.title))
            self.test_cases_table.setItem(row, 2, QTableWidgetItem(tc.status))
            self.test_cases_table.setItem(row, 3, QTableWidgetItem(tc.priority))
            self.test_cases_table.setItem(row, 4, QTableWidgetItem(str(tc.created_at)))
            self.test_cases_table.setItem(row, 5, QTableWidgetItem(str(tc.updated_at)))
        
        self.test_cases_table.resizeColumnsToContents()
    
    def fill_bug_reports_table(self, bug_reports):
        """Заполняет таблицу баг-репортов"""
        self.bug_reports_table.setRowCount(len(bug_reports))
        
        for row, br in enumerate(bug_reports):
            self.bug_reports_table.setItem(row, 0, QTableWidgetItem(br.id))
            self.bug_reports_table.setItem(row, 1, QTableWidgetItem(br.title))
            self.bug_reports_table.setItem(row, 2, QTableWidgetItem(br.status))
            self.bug_reports_table.setItem(row, 3, QTableWidgetItem(br.priority))
            self.bug_reports_table.setItem(row, 4, QTableWidgetItem(br.severity))
            project_name = br.gitlab_project.display_name if br.gitlab_project else "—"
            sync_state = br.gitlab_binding.sync_state if br.gitlab_binding else "local_only"
            self.bug_reports_table.setItem(row, 5, QTableWidgetItem(project_name))
            self.bug_reports_table.setItem(row, 6, QTableWidgetItem(sync_state))
            self.bug_reports_table.setItem(row, 7, QTableWidgetItem(str(br.created_at)))
            self.bug_reports_table.setItem(row, 8, QTableWidgetItem(str(br.updated_at)))
        
        self.bug_reports_table.resizeColumnsToContents()
    
    def create_artifact(self, artifact_type):
        """Создает новый артефакт"""
        dialog = (
            TestCaseDialog(self.session, parent=self)
            if artifact_type == 'test_case'
            else BugReportDialog(
                self.session,
                parent=self,
                gitlab_controller=self.gitlab_controller,
            )
        )
        
        if dialog.exec() == 1:
            self.load_artifacts()
            self.statusBar().showMessage(f"Создан новый {artifact_type.replace('_', ' ')}")
    
    def edit_artifact(self):
        """Редактирует выбранный артефакт"""
        table = self.get_current_table()
        selected_rows = table.selectionModel().selectedRows()
        
        if len(selected_rows) != 1:
            message = (
                "Выберите ровно один артефакт для редактирования"
                if selected_rows
                else "Не выбран артефакт для редактирования"
            )
            QMessageBox.warning(self, "Предупреждение", message)
            return
        
        # Берем первую выделенную строку
        row = selected_rows[0].row()
        artifact_id = table.item(row, 0).text()
        artifact_type = 'test_case' if self.current_tab == 'test_cases' else 'bug_report'
        
        dialog = (
            TestCaseDialog(self.session, artifact_id, parent=self)
            if artifact_type == 'test_case'
            else BugReportDialog(
                self.session,
                artifact_id,
                parent=self,
                gitlab_controller=self.gitlab_controller,
            )
        )
        
        if dialog.exec() == 1:
            self.load_artifacts()
            self.statusBar().showMessage(f"Артефакт {artifact_id} обновлен")

    def _selected_bug_report(self):
        """Возвращает единственный выбранный баг или None."""
        if self.current_tab != 'bug_reports':
            return None
        selected_rows = self.bug_reports_table.selectionModel().selectedRows()
        if len(selected_rows) != 1:
            return None
        item = self.bug_reports_table.item(selected_rows[0].row(), 0)
        return BugReportService.get_by_id(self.session, item.text()) if item else None

    def _set_gitlab_busy(self, busy):
        self._gitlab_busy = busy
        self.gitlab_progress.setVisible(busy)
        self._update_action_states()

    def _start_gitlab_operation(self, operation, succeeded):
        if self._gitlab_busy or self.gitlab_controller is None:
            return
        try:
            self.gitlab_controller.require_ready()
            self._set_gitlab_busy(True)
            self.gitlab_controller.start(
                operation,
                succeeded=succeeded,
                failed=self._gitlab_failed,
                finished=self._gitlab_finished,
            )
        except Exception as error:
            self._set_gitlab_busy(False)
            self._gitlab_failed(error)

    def sync_selected_bug_report(self):
        """Показывает preview и синхронизирует один выбранный опубликованный баг."""
        bug = self._selected_bug_report()
        if bug is None:
            QMessageBox.warning(
                self,
                "GitLab",
                "Выберите ровно один опубликованный баг-репорт для синхронизации",
            )
            return
        if bug.gitlab_binding is None or bug.gitlab_binding.issue_iid is None:
            QMessageBox.warning(self, "GitLab", "Баг-репорт ещё не опубликован")
            return

        bug_report_id = bug.id
        self._start_gitlab_operation(
            lambda session, client: GitLabSyncService(client).preview(
                session, bug_report_id
            ),
            self._sync_preview_ready,
        )

    @Slot(object)
    def _sync_preview_ready(self, preview):
        self._pending_sync_preview = preview
        if preview.action == "none":
            self.session.expire_all()
            self.load_artifacts()
            QMessageBox.information(self, "GitLab", "Локальная и remote версии совпадают")
            return

        resolutions = None
        if preview.conflicts:
            dialog = ConflictResolutionDialog(preview, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            resolutions = dialog.resolutions
        else:
            dialog = SyncPreviewDialog(preview, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

        self._start_gitlab_operation(
            lambda session, client: GitLabSyncService(client).confirm(
                session, preview, resolutions
            ),
            self._sync_finished,
        )

    @Slot(object)
    def _sync_finished(self, result):
        self.session.expire_all()
        self.load_artifacts()
        self.statusBar().showMessage("Синхронизация GitLab завершена")
        QMessageBox.information(self, "GitLab", "Синхронизация завершена")

    @Slot(object)
    def _gitlab_failed(self, error):
        self.session.expire_all()
        self.load_artifacts()
        QMessageBox.critical(self, "GitLab", str(error))

    @Slot()
    def _gitlab_finished(self):
        self._set_gitlab_busy(False)

    def open_selected_bug_report_in_gitlab(self):
        """Открывает Issue только для одного выбранного опубликованного бага."""
        bug = self._selected_bug_report()
        if bug is None:
            QMessageBox.warning(
                self,
                "GitLab",
                "Выберите ровно один опубликованный баг-репорт",
            )
            return
        url_value = (
            bug.gitlab_binding.issue_web_url
            if bug.gitlab_binding is not None
            else None
        )
        url = QUrl(url_value or "")
        if not url.isValid() or url.scheme().lower() != "https" or not url.host():
            QMessageBox.warning(self, "GitLab", "Безопасный URL Issue недоступен")
            return
        QDesktopServices.openUrl(url)
    
    def view_artifact(self):
        """Просматривает выбранный артефакт"""
        table = self.get_current_table()
        selected_rows = table.selectionModel().selectedRows()
        
        if not selected_rows:
            return
        
        # Берем первую выделенную строку
        row = selected_rows[0].row()
        artifact_id = table.item(row, 0).text()
        artifact_type = 'test_case' if self.current_tab == 'test_cases' else 'bug_report'
        
        dialog = ArtifactDetailDialog(self.session, artifact_id, artifact_type, parent=self)
        dialog.exec()
    
    def delete_artifact(self):
        """Удаляет выбранные артефакты"""
        table = self.get_current_table()
        selected_rows = table.selectionModel().selectedRows()
        
        if not selected_rows:
            QMessageBox.warning(self, "Предупреждение", "Не выбраны артефакты для удаления")
            return
        
        artifact_type = 'test_case' if self.current_tab == 'test_cases' else 'bug_report'
        artifact_name = 'тест-кейсов' if artifact_type == 'test_case' else 'баг-репортов'
        count = len(selected_rows)

        if artifact_type == 'bug_report':
            for index in selected_rows:
                artifact_id = table.item(index.row(), 0).text()
                bug = BugReportService.get_by_id(self.session, artifact_id)
                if bug is not None and bug.gitlab_binding is not None:
                    QMessageBox.warning(
                        self,
                        "Удаление запрещено",
                        "Опубликованный баг нельзя удалить. Закройте его через синхронизацию.",
                    )
                    return
        
        # Проверяем связи
        has_links = False
        for index in selected_rows:
            row = index.row()
            artifact_id = table.item(row, 0).text()
            linked = LinkService.get_linked_artifacts(self.session, artifact_id, artifact_type)
            if linked:
                has_links = True
                break
        
        # Формируем сообщение
        if has_links:
            message = (f"Выбранные артефакты имеют связи с другими артефактами.\n"
                      f"Удаление приведет к разрыву связей.\n\n"
                      f"Вы уверены, что хотите удалить {count} {artifact_name}?")
        else:
            message = f"Вы уверены, что хотите удалить {count} {artifact_name}?"
        
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Сортируем в обратном порядке для корректного удаления
            for index in sorted(selected_rows, reverse=True):
                row = index.row()
                artifact_id = table.item(row, 0).text()
                if artifact_type == 'test_case':
                    TestCaseService.delete(self.session, artifact_id)
                else:
                    try:
                        BugReportService.delete(self.session, artifact_id)
                    except PublishedBugDeleteError as error:
                        QMessageBox.warning(self, "Удаление запрещено", str(error))
                        return
            
            self.load_artifacts()
            self.statusBar().showMessage(f"Удалено {count} артефактов")
    
    def export_artifacts(self):
        """Экспортирует выбранные артефакты"""
        table = self.get_current_table()
        selected_rows = sorted(set(item.row() for item in table.selectedItems()))
        
        if not selected_rows:
            QMessageBox.warning(self, "Предупреждение", "Не выбраны артефакты для экспорта")
            return
        
        artifacts = []
        for row in selected_rows:
            artifact_id = table.item(row, 0).text()
            if self.current_tab == 'test_cases':
                artifact = TestCaseService.get_by_id(self.session, artifact_id)
            else:
                artifact = BugReportService.get_by_id(self.session, artifact_id)
            
            if artifact:
                artifact_dict = artifact.to_dict()
                
                # Добавляем вложения для баг-репортов с абсолютными путями для экспорта
                if self.current_tab == 'bug_reports':
                    attachments = AttachmentService.get_attachments_for_export(
                        self.session,
                        artifact_id,
                        'bug_report'
                    )
                    artifact_dict['attachments'] = attachments
                
                artifacts.append(artifact_dict)
        
        dialog = ExportDialog(artifacts, self.current_tab, parent=self)
        dialog.exec()
    
    def show_about(self):
        """Показывает информацию о программе"""
        QMessageBox.about(
            self,
            f"О {APP_NAME}",
            f"""
            <h2>{APP_NAME} v{APP_VERSION}</h2>
            <p>Система управления тест-кейсами и баг-репортами</p>
            <p>Разработано по стандартам ISTQB</p>
            <hr>
            <p>© 2026 MyOwnTMS</p>
            """
        )

    def open_gitlab_settings(self):
        """Open runtime-only connection settings without making startup requests."""
        dialog = GitLabSettingsDialog(
            self.session, self.gitlab_controller, parent=self
        )
        dialog.exec()
        self.session.expire_all()
        self.load_artifacts()
    
    def deselect_all(self):
        """Снимает выделение со всех артефактов"""
        table = self.get_current_table()
        table.clearSelection()
        self.statusBar().showMessage("Выделение снято")
    
    def closeEvent(self, event):
        """Обрабатывает закрытие окна"""
        self.gitlab_controller.shutdown()
        self.session.close()
        event.accept()

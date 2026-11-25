# MyOwnTMS — контекст для новой сессии

> Быстрый старт для работы с проектом. Нормативная спецификация:
> [`docs/SRS.md`](SRS.md). План реализации GitLab:
> [`docs/SESSION_BRIEF_GITLAB_ISSUES.md`](SESSION_BRIEF_GITLAB_ISSUES.md).

## Что это за проект

MyOwnTMS — локальное некоммерческое desktop-приложение для независимого
тестировщика. Оно хранит тест-кейсы и баг-репорты, связи и вложения, позволяет
искать артефакты и экспортировать их в PDF, DOCX и Markdown.

Текущая версия приложения в коде — `1.0.0`. Планируемая v1.1 добавляет только
явную совместную работу над баг-репортами через GitLab Self-Managed в
изолированной LAN. Передача артефактов в интернет запрещена. Тест-кейсы остаются
локальными.

## Стек

| Слой | Технология |
|---|---|
| Runtime | Python 3.10+ |
| GUI | PySide6 |
| Persistence | SQLAlchemy 2 + SQLite |
| Export | ReportLab, python-docx, Markdown |
| Package | PyInstaller, Windows EXE |
| Planned GitLab client | httpx + REST API v4 |
| Planned tests | pytest, pytest-qt, httpx.MockTransport |

Версии в `requirements.txt` сейчас заданы нижними границами, lock/constraints
отсутствуют.

## Архитектура

```text
src/
├── config.py              # data paths, enums, app version
├── main.py                # startup и QApplication
├── database/              # SQLAlchemy models/session
├── services/              # artifacts, attachments, links, ID generation
├── export/                # PDF, DOCX, Markdown
└── gui/                   # main window, dialogs, styles
```

Текущие сервисы сами выполняют `commit()`. База создаётся через
`Base.metadata.create_all()`; полноценного migration framework пока нет.
Runtime-данные лежат рядом с EXE в `data/`, а при запуске из source — в корневом
`data/`.

## Текущий статус

### Реализовано в source

- CRUD тест-кейсов и баг-репортов.
- ID `TC-ДДММГГ-ННН` / `BUG-ДДММГГ-ННН`.
- Статусы, приоритеты, серьёзность, даты и окружение.
- Связи между артефактами.
- Локальные вложения и относительные пути.
- Поиск, фильтры, сортировка и табличный GUI.
- PDF/DOCX/Markdown export.
- Windows PyInstaller spec.

Это source inspection, не runtime acceptance. Автотестов в репозитории нет.

### TASK-DOC-001

- `docs/SRS.md` — создан.
- `docs/CONTEXT.md` — создан.
- `docs/SESSION_BRIEF_GITLAB_ISSUES.md` — создан.
- Реализация GitLab не начата.

### TASK-SEC-001

- Локальная Git hygiene реализована; GitLab-интеграция не начиналась.
- До очистки path-only inventory через `git ls-files` показал 14 файлов в
  `build/`, 18 в `dist/` (16 пользовательских вложений и одна runtime SQLite
  DB), 23 файла в `__pycache__/` и 4 raw `context/*.json`.
- `.gitignore` закрывает runtime `data/`, `dist/`, `build/`, Python bytecode,
  SQLite runtime/sidecars/backups и raw `context/*.json`.
- В исходной рабочей копии эти paths были удалены только из Git index, поэтому
  локальная `dist/data/tms.db` и все 16 файлов вложений там сохранились. В clean
  import runtime/user files не переносились.
- `scripts/check_git_hygiene.py` проверяет denylist через `git ls-files`; тот же
  check подключён в `.gitlab-ci.yml`.
- `scripts/scan_secrets.py` проверяет non-ignored worktree и все reachable Git
  blobs с path-only redacted output.
- Clean import подготовлен без старой `.git`: commits и remote отсутствуют,
  поэтому старая история не попадёт в первый push. Предыдущая публикация может
  оставаться во внешних clones/caches и рассматривается отдельно.

### План v1.1

| Task | Состояние |
|---|---|
| TASK-SEC-001 | Ready for clean initial commit — remote NOT CONFIGURED |
| TASK-GL-001 | Planned |
| TASK-GL-002 | Planned |
| TASK-GL-003 | Planned |
| TASK-GL-004 | Planned |
| TASK-GL-005 | Planned |
| TASK-GL-006 | Planned |
| TASK-GL-007 | Planned |

## Ключевые решения v1.1

- Один GitLab Self-Managed instance, несколько Private projects.
- GitLab расположен в LAN без интернет-egress; HTTPS и внутренний CA
  обязательны.
- Баг создаёт оператор в MyOwnTMS; заказчик не входит в GitLab.
- Синхронизируются только баг-репорты и PNG/JPEG.
- GitLab authoritative после публикации; SQLite остаётся offline cache.
- Нет background/startup sync: только явные Publish/Sync.
- Перед write/upload показывается preview.
- Личный PAT существует только в памяти текущего процесса.
- Черновик может быть неполным; публикация требует полных ISTQB-полей.
- Конфликт разрешается сравнением `base/local/remote` по каждому полю.
- Опубликованный баг нельзя hard-delete.
- Comments, assignees, milestones и test cases не входят в v1.1.

## Security boundary

GitLab Self-Managed сам по себе не гарантирует отсутствие egress. Обязательны
firewall deny, private projects, отключённые внешние integrations/telemetry,
HTTPS и внутренний CA. Приложение ограничивает API одним origin, не следует
redirects и не позволяет отключать TLS verification.

До `TASK-SEC-001` исходный Git index содержал `dist/data/tms.db`, пользовательские
изображения, build/dist outputs и raw `context/*.json`. Clean import создан из
очищенного snapshot без исходной `.git`, runtime/user files и старых commits;
denylist и `.gitignore` добавлены. Remote, commit и push ещё не выполнялись.
Предыдущая публикация может сохраняться во внешних clones/caches; её удаление не
входит в clean import.

Никогда не выводить значения PAT, credentials или содержимое артефактов в логи и
отчёты проверок.

## Ключевые файлы

| Что | Где |
|---|---|
| Спецификация | `docs/SRS.md` |
| Implementation brief | `docs/SESSION_BRIEF_GITLAB_ISSUES.md` |
| Обзор/установка | `README.md` |
| Инструкция пользователя | `USAGE.md` |
| Модели | `src/database/models.py` |
| DB session/init | `src/database/session.py` |
| Artifact CRUD | `src/services/artifact_service.py` |
| Attachments | `src/services/attachment_service.py` |
| Bug dialog | `src/gui/widgets/bug_report_dialog.py` |
| Main window | `src/gui/main_window.py` |
| Data paths/enums | `src/config.py` |
| EXE config | `MyOwnTMS.spec` |

## Команды

```bash
# Запуск из source
python run.py

# Сборка существующего Windows EXE
pyinstaller MyOwnTMS.spec

# Текущая статическая проверка Python без запуска GUI
python -m compileall -q src run.py

# Проверка Markdown whitespace после изменения документации
git diff --check
```

Автоматизированные тестовые команды появятся только в `TASK-GL-001`. До этого
не утверждать, что pytest или GitLab acceptance прошли.

## Как продолжать работу

1. Прочитать этот файл, `docs/SRS.md` и brief целиком.
2. Проверить `git status --short`; не затрагивать пользовательские изменения.
3. Выполнять ровно одну numbered task из brief.
4. Начать с `TASK-SEC-001`; не подключать remote и не отправлять репозиторий до
   закрытия P0 data hygiene.
5. Для GitLab проверок разделять mock/local, disposable GitLab, LAN/EXE и
   production-like evidence. Незапущенное отмечать `NOT RUN`.
6. После каждой закрытой задачи синхронизировать статусы в SRS, CONTEXT и brief.

## Шаблон задачи для новой сессии

```text
Задача: [TASK-ID] — [краткое описание]
Контекст: прочитай docs/CONTEXT.md, docs/SRS.md и
docs/SESSION_BRIEF_GITLAB_ISSUES.md
Цель: выполнить только указанную numbered task
DoD: критерии указанной задачи из brief
Ограничения: не выполнять соседние задачи; не commit/push/pull; не подключать
внешний GitLab; не использовать реальные runtime/user data в тестах
```

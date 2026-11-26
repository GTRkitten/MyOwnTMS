# MyOwnTMS — контекст для новой сессии

> Быстрый старт для работы с проектом. Нормативная спецификация:
> [`docs/SRS.md`](SRS.md). План реализации GitLab:
> [`docs/SESSION_BRIEF_GITLAB_ISSUES.md`](SESSION_BRIEF_GITLAB_ISSUES.md).

## Что это за проект

MyOwnTMS — локальное некоммерческое desktop-приложение для независимого
тестировщика. Оно хранит тест-кейсы и баг-репорты, связи и вложения, позволяет
искать артефакты и экспортировать их в PDF, DOCX и Markdown.

Текущая версия приложения в коде — `1.0.0`. Разрабатываемая v1.1 добавляет только
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
| GitLab client | httpx + REST API v4 |
| Tests | pytest, pytest-qt, httpx.MockTransport |

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

Текущие сервисы сами выполняют `commit()`. Схема создаётся и обновляется через
небольшой embedded SQLite migration registry; Alembic не используется.
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

Это source inspection, не runtime acceptance. Текущий test suite покрывает
миграции и GitLab HTTP boundary, но не весь legacy GUI/runtime baseline.

### TASK-DOC-001

- `docs/SRS.md` — создан.
- `docs/CONTEXT.md` — создан.
- `docs/SESSION_BRIEF_GITLAB_ISSUES.md` — создан.
- GitLab API adapter, project-profile/label-bootstrap, resumable publish,
  explicit sync и PySide6 GUI интеграции реализованы локально.

### TASK-SEC-001

- Локальная Git hygiene реализована до начала сетевой GitLab-интеграции.
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

### TASK-GL-001

- Добавлен изолированный pytest-контур с временным data directory; тестовый
  override недоступен обычному runtime/EXE.
- `init_database()` использует embedded migration registry вместо
  `Base.metadata.create_all()`.
- Перед первой pending migration SQLite backup API создаёт согласованный backup;
  migrations и их registry-записи применяются в одной транзакции, затем
  выполняется `PRAGMA integrity_check`.
- Добавлены planned GitLab tables, поля источника/project у bug report и статус
  `Черновик`; legacy rows, links и attachments сохраняются.
- Focused tests: `6 passed`; runtime `data/`, `dist/data/` и пользовательские
  вложения не использовались.

### TASK-GL-002

- Добавлен `httpx>=0.27,<0.29` и изолированный REST API v4 adapter для current
  user/project checks, labels, Issue get/create/update и project upload.
- Origin ограничен HTTPS scheme/host/port без redirects, proxy environment и
  произвольных response URLs; HTTP доступен только pytest на loopback.
- TLS verification всегда включена через `SSLContext`; optional internal CA
  bundle должен быть существующим абсолютным файлом.
- PAT запрашивается callback только при первом сетевом действии, хранится в
  `SessionToken` текущего процесса, не попадает в repr/errors и очищается явно.
- Безопасные typed errors покрывают HTTP failures, timeout, TLS, connection и
  malformed JSON; `Retry-After` сохраняется как bounded metadata, auto-retry нет.
- `httpx.MockTransport`: `38 passed`; весь изолированный suite: `44 passed`.
  Реальный GitLab/TLS/LAN — **NOT RUN**.

### TASK-GL-003

- Добавлен `GitLabProjectService`: remote project проверяется до локальной
  записи по numeric ID, `path_with_namespace`, same-origin web URL, private
  visibility и признаку archive.
- Локально поддерживаются несколько project profiles; PAT остаётся только в
  `SessionToken` и в SQLite-модель не попадает.
- Определены 13 Free/CE-compatible managed labels. Preview выполняет только
  чтение; подтверждение создаёт лишь показанные и всё ещё отсутствующие labels.
- После записи выполняется контрольное чтение; `labels_ready_at` фиксируется
  только при полном наборе labels. Pagination учитывается, rename обновляет
  профиль при preview, повторный bootstrap не создаёт дубли.
- Focused service/API tests: `14 passed`; весь изолированный suite: `58 passed`.
  GUI settings smoke и реальный GitLab/role/TLS/LAN — **NOT RUN**.

### TASK-GL-004

- Добавлены pure codec managed block/labels и `GitLabPublishService` с read-only
  preview, publish validation и сохранением `sync_uid`/`publishing` до POST.
- Неопределённый create восстанавливается project-scoped поиском точного marker;
  повторный запуск сначала ищет marker и не создаёт Issue вслепую.
- PNG/JPEG проверяются по расширению, сигнатуре и лимиту 10 MiB; upload bindings
  фиксируют attachment ID, SHA-256 и remote metadata после каждого файла.
- Partial upload сохраняет Issue и завершённые bindings; restart продолжает без
  повторной загрузки уже зафиксированных файлов.
- Если GitLab принял upload, но ответ потерян, незавершённый binding блокирует
  автоматический повтор POST, чтобы не создавать второй remote upload; такой
  исход требует операторской сверки.
- Финальное обновление сохраняет текст вне managed block и unmanaged labels.
- Focused codec/publish/API tests: `47 passed`; весь изолированный suite:
  `67 passed`. Реальный GitLab/TLS/LAN и GUI — **NOT RUN**.

### TASK-GL-005

- Добавлены pure normalized snapshots и field-level three-way merge для
  `base/local/remote`; preview различает pull, push, non-overlapping merge,
  conflict и no-op.
- `GitLabSyncService` повторно проверяет local/remote перед подтверждением,
  сохраняет внешний Markdown и unmanaged labels, а после каждого PUT выполняет
  контрольный GET.
- Corrupt/missing/unknown managed block и несогласованные managed labels/state
  fail-closed; удалённый/недоступный Issue получает `remote_missing` без
  auto-republish.
- Close/Reopen синхронизируются через status label + Issue state; каждый
  same-field conflict требует явного выбора local/remote.
- Обычное service-level редактирование опубликованного бага переводит binding
  из `synced`/`remote_changed` в `local_changed`.
- Hard-delete любого GitLab-bound bug заблокирован на service boundary.
- Focused sync/lifecycle tests: `24 passed`; весь изолированный suite:
  `91 passed`. Реальный GitLab/TLS/LAN и GUI conflict flow — **NOT RUN**.

### TASK-GL-006

- Добавлены runtime-only настройки origin/internal CA/PAT, проверка соединения,
  управление validated project profiles и preview/confirm bootstrap labels.
- Bug dialog поддерживает неполный `Черновик`, project/source/reference/sync
  state, локальное сохранение, preview/publish, sync и безопасное открытие Issue.
- Main table показывает project/sync state; conflict dialog отображает
  base/local/remote и требует выбор для каждого конфликтующего поля.
- GitLab-операции выполняются через `QThreadPool` с отдельными DB sessions;
  progress/buttons исключают повторный запуск, а Qt auto-disconnect не доставляет
  результат уничтоженному widget.
- Focused headless `pytest-qt`: `8 passed`; весь изолированный suite:
  `99 passed`. Manual responsiveness, real GitLab/TLS/LAN и Windows EXE —
  **NOT RUN**.

### TASK-GL-007

- `MyOwnTMS.spec` сохраняет явный allowlist public documentation/style assets;
  runtime data, SQLite DB, CA bundle, GitLab config и PAT в EXE не добавляются.
- PyInstaller `6.22.3` на Linux собрал one-file bundle; Analysis включил
  `httpx`, `httpcore`, `_ssl`, TLS libraries и `certifi/cacert.pem`.
- Неграфический изолированный suite: `91 passed`; hygiene и redacted secret scan
  — **PASS**.
- Frozen Linux startup и GUI suite остановились на отсутствующей системной
  `libEGL.so.1`; это не Windows acceptance.
- Отдельный отчёт и runbook: `docs/GITLAB_V1_1_ACCEPTANCE.md`.
- Clean Windows, real GitLab/internal CA/LAN, migration/rollback, outage/PAT
  restart и egress capture — **NOT RUN**; задача остаётся открытой.

### План v1.1

| Task | Состояние |
|---|---|
| TASK-SEC-001 | Ready for clean initial commit — remote NOT CONFIGURED |
| TASK-GL-001 | Implemented locally — focused tests PASS; CI/real legacy DB NOT RUN |
| TASK-GL-002 | Implemented locally — MockTransport tests PASS; real GitLab NOT RUN |
| TASK-GL-003 | Implemented locally — service/API tests PASS; GUI/real GitLab NOT RUN |
| TASK-GL-004 | Implemented locally — focused tests PASS; real GitLab/GUI NOT RUN |
| TASK-GL-005 | Implemented locally — focused tests PASS; real GitLab/GUI NOT RUN |
| TASK-GL-006 | Implemented locally — focused pytest-qt PASS; real GitLab/LAN NOT RUN |
| TASK-GL-007 | Local packaging preflight PASS; Windows/LAN acceptance NOT RUN |

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
| Windows/LAN acceptance report | `docs/GITLAB_V1_1_ACCEPTANCE.md` |
| Обзор/установка | `README.md` |
| Инструкция пользователя | `USAGE.md` |
| Модели | `src/database/models.py` |
| DB session/init | `src/database/session.py` |
| Artifact CRUD | `src/services/artifact_service.py` |
| Attachments | `src/services/attachment_service.py` |
| Bug dialog | `src/gui/widgets/bug_report_dialog.py` |
| Main window | `src/gui/main_window.py` |
| Data paths/enums | `src/config.py` |
| GitLab API adapter | `src/integrations/gitlab_client.py` |
| GitLab project profiles/labels | `src/services/gitlab_project_service.py` |
| GitLab managed block/labels | `src/services/gitlab_issue_codec.py` |
| GitLab resumable publish | `src/services/gitlab_publish_service.py` |
| GitLab explicit sync/merge | `src/services/gitlab_sync_service.py` |
| EXE config | `MyOwnTMS.spec` |

## Команды

```bash
# Запуск из source
python run.py

# Сборка существующего Windows EXE
pyinstaller MyOwnTMS.spec

# Текущая статическая проверка Python без запуска GUI
python3 -m compileall -q src tests run.py

# Изолированные тесты TASK-GL-001–007
python3 -m pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python3 -m pytest

# Проверка Markdown whitespace после изменения документации
git diff --check
```

В headless Linux для Qt может понадобиться системная `libEGL.so.1`. Не утверждать,
что manual responsiveness, реальный GitLab, LAN, Windows EXE или реальная
legacy-БД прошли acceptance.

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

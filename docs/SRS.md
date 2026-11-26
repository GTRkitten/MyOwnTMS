# SRS: MyOwnTMS v1.1 — локальная TMS с GitLab Issues

**Статус документа:** baseline v1.0 подтверждён чтением исходного кода;
test foundation, SQLite migrations, GitLab API boundary, project bootstrap,
resumable publish, explicit sync и PySide6 UX из `TASK-GL-001`–006 реализованы
локально; local packaging preflight из `TASK-GL-007` выполнен, Windows/LAN
acceptance остаётся `NOT RUN`.

**Дата актуализации:** 2026-11-26

## Goal

Сохранить MyOwnTMS локальным desktop-приложением, которое полноценно работает
без сети и хранит тестовые артефакты на компьютере пользователя, но добавить
контролируемую совместную работу над баг-репортами через GitLab Self-Managed.

Главный сценарий v1.1: оператор быстро фиксирует сообщение заказчика локально,
дополняет его до структурированного баг-репорта и явно публикует в приватный
GitLab Issue. Передача в интернет запрещена; GitLab доступен только в доверенной
локальной сети.

## Users and Stakeholders

- **Оператор / тестировщик:** создаёт и редактирует локальные артефакты,
  публикует баги и разрешает конфликты синхронизации.
- **Внутренняя команда:** работает с опубликованными Issue через GitLab.
- **Заказчик:** сообщает о проблеме оператору, но не получает доступ к GitLab в
  рамках v1.1.
- **Администратор GitLab:** обеспечивает приватные проекты, HTTPS, внутренний
  CA и сетевую изоляцию инстанса.

## Success Criteria

1. Без GitLab и без сети сохраняются все существующие локальные функции.
2. Неполное сообщение заказчика можно сохранить как локальный черновик.
3. Перед публикацией пользователь видит проект, передаваемые поля и файлы.
4. Один локальный баг создаёт не более одного GitLab Issue даже после сбоя или
   неопределённого результата запроса.
5. Основные поля, статусы, приоритет, серьёзность и изображения синхронизируются
   только по явной команде.
6. Параллельные изменения одного поля не перезаписываются молча.
7. Личный GitLab-токен не сохраняется на диск и не попадает в логи.
8. Приложение не обращается ни к каким внешним адресам, кроме заранее
   настроенного GitLab origin в локальной сети.
9. Существующие SQLite-данные и вложения сохраняются при обновлении.

## Scope / Out-of-Scope

### Existing baseline v1.0 — implemented in source

- Локальные тест-кейсы и баг-репорты.
- ID формата `TC-ДДММГГ-ННН` и `BUG-ДДММГГ-ННН`.
- Статусы, приоритеты, серьёзность, окружение и даты изменения.
- Связи между тест-кейсами и багами.
- Локальные вложения.
- Поиск, фильтры и сортировка.
- Экспорт PDF, DOCX и Markdown.
- PySide6 GUI, SQLAlchemy и SQLite.
- Упаковка Windows EXE через PyInstaller.

Этот перечень подтверждён чтением исходного кода. Добавленный test suite
проверяет migrations и GitLab HTTP boundary, но полный runtime/GUI/EXE baseline
ещё не покрыт и acceptance не считается выполненным.

### In-Scope v1.1

- Быстрый локальный черновик баг-репорта.
- Необязательные метаданные источника сообщения.
- Один GitLab Self-Managed instance и несколько приватных проектов.
- Личный PAT каждого оператора, существующий только в памяти процесса.
- Явная настройка и проверка проектов.
- Явная подготовка labels после preview и подтверждения.
- Создание и обновление GitLab Issue через REST API v4.
- Загрузка PNG/JPEG во вложения GitLab Issue.
- Локальный кеш опубликованных Issue.
- Трёхсторонняя синхронизация и разрешение конфликтов по полям.
- Закрытие и переоткрытие Issue.
- Безопасная миграция существующей SQLite-базы.
- Сборка и ручная проверка Windows EXE.
- Прекращение отслеживания runtime-БД, пользовательских вложений, build/dist и
  сырых context histories до подключения репозитория к GitLab.

### Out-of-Scope v1.1

- GitLab.com и любые внешние SaaS-хранилища.
- Развёртывание и администрирование GitLab Self-Managed.
- Фоновая или периодическая синхронизация.
- Webhooks и входящие соединения к MyOwnTMS.
- Импорт Issue, изначально созданных в GitLab.
- Синхронизация тест-кейсов и связей между артефактами.
- GitLab comments, assignees, milestones, boards и Service Desk внутри GUI.
- Доступ заказчика к GitLab.
- Хранение персональных данных заказчика, кроме переданного им содержания бага.
- Переписывание уже опубликованной Git-истории.
- Автоматическое удаление удалённых Issue или GitLab uploads.

## Functional Requirements

### FR-1: Локальные артефакты

1. Существующие test case и bug report операции сохраняют обратную
   совместимость.
2. Тест-кейсы всегда остаются локальными.
3. Баг до первой публикации является исключительно локальным артефактом.
4. Отсутствие GitLab, токена или сети не блокирует локальное создание,
   редактирование, поиск и экспорт.

### FR-2: Быстрая фиксация сообщения заказчика

1. Статус баг-репорта расширяется значением `Черновик`.
2. Для сохранения черновика достаточно заголовка или описания исходного
   сообщения.
3. Добавляются необязательные поля:
   - `source_channel`: `email`, `messenger`, `phone`, `meeting`, `other`;
   - `external_reference`: внешний номер или ссылка без учётных данных.
4. Проект можно выбрать при создании или перед публикацией.
5. Для публикации обязательны проект, заголовок, шаги воспроизведения,
   ожидаемый и фактический результаты.

### FR-3: GitLab instance и токен

1. v1.1 поддерживает один GitLab Self-Managed origin.
2. URL должен использовать HTTPS; HTTP допускается только для автоматизированных
   тестов на loopback.
3. Можно указать путь к внутреннему CA bundle.
4. Отключение проверки TLS через GUI или конфигурацию запрещено.
5. PAT вводится при первом сетевом действии в текущем сеансе.
6. PAT хранится только в памяти, очищается при завершении процесса и никогда не
   записывается в SQLite, QSettings, файлы, логи или crash reports.
7. Для обычного PAT требуется минимально необходимый доступ к выбранным
   проектам и REST API. Если установленная версия GitLab поддерживает
   fine-grained token, предпочтительны права только на Issues, Labels, Projects
   read и Markdown uploads.

### FR-4: Проекты и labels

1. Один MyOwnTMS обслуживает несколько GitLab-проектов одного instance.
2. Локальный профиль проекта хранит имя заказчика/проекта, numeric GitLab ID,
   `path_with_namespace`, web URL и активность.
3. Добавление профиля требует успешной проверки доступа текущим токеном.
4. Проект должен быть приватным; иной visibility блокирует настройку.
5. Подготовка проекта сначала показывает недостающие labels и только после
   подтверждения создаёт их.
6. Используются Free/CE-совместимые обычные labels:
   - `myowntms`;
   - `myowntms-status-{new|in-progress|verified|closed}`;
   - `myowntms-priority-{critical|high|medium|low}`;
   - `myowntms-severity-{critical|major|minor|trivial}`.
7. Приложение обеспечивает ровно один label каждой управляемой группы и
   сохраняет все неуправляемые labels.
8. Непосредственно перед publish приложение повторно читает проект и полный
   набор managed labels. Если хотя бы один label исчез, Issue write блокируется,
   локальный `labels_ready_at` сбрасывается, а оператор должен снова выполнить
   preview и подтверждённый bootstrap. Publish не создаёт labels неявно.

### FR-5: Preview и публикация

1. До первого POST пользователь видит destination project, заголовок, все
   передаваемые поля и список файлов.
2. Пользователь явно подтверждает публикацию.
3. Заголовок Issue имеет формат `[BUG-ID] Заголовок`.
4. Description содержит версионированный managed block:

```markdown
<!-- MYOWNTMS:BEGIN version=1 sync_uid=<uuid> -->
## Описание
## Шаги воспроизведения
## Ожидаемый результат
## Фактический результат
## Окружение
## Источник
## Вложения
<!-- MYOWNTMS:END -->
```

5. `sync_uid` генерируется и сохраняется до сетевого запроса.
6. После создания Issue локально сохраняются global Issue ID, project IID,
   web URL и remote `updated_at`.
7. При неопределённом результате create-запроса приложение ищет точный
   `sync_uid` в выбранном проекте. Повторный create без такой проверки запрещён.
8. Частично завершённая публикация помечается как resumable error; созданный
   Issue автоматически не удаляется.

### FR-6: Вложения

1. В v1.1 передаются только PNG и JPEG.
2. Перед upload проверяются расширение, фактический формат, размер и наличие
   файла; абсолютный локальный путь не передаётся.
3. Локальный лимит по умолчанию — 10 MiB на файл.
4. После upload сохраняются remote upload ID/URL, Markdown, SHA-256 локального
   содержимого и время загрузки.
5. Повторная синхронизация не загружает файл с тем же attachment ID и SHA-256.
   Если результат upload неопределён и response metadata не получены,
   автоматический повтор POST блокируется во избежание remote-дубликата.
6. GitLab Markdown размещается только в секции `Вложения` managed block.
7. Удаление локального вложения убирает ссылку из managed block, но не удаляет
   GitLab upload автоматически. До удаления upload binding точный Markdown
   фиксируется как pending removal; Sync показывает его в `base/local/remote`
   preview, требует explicit resolution при concurrent remote edit и очищает
   intent только после подтверждённого результата.
8. Файлы, добавленные вручную в GitLab, автоматически локально не скачиваются.

### FR-7: Явная синхронизация

1. Приложение не выполняет сетевых запросов при старте, открытии или обычном
   локальном сохранении.
2. `Синхронизировать` сначала получает текущий Issue, затем сравнивает
   нормализованные `base`, `local` и `remote` snapshots.
3. Remote-only изменения обновляют локальный кеш.
4. Local-only изменения показываются в preview и отправляются после
   подтверждения.
5. Изменения разных полей объединяются автоматически, но итоговая отправка
   требует preview.
6. Разные изменения одного поля требуют явного выбора local/remote.
7. Поля сравнения: title, description, reproduction steps, expected result,
   actual result, environment, source metadata, status, priority и severity.
8. Текст GitLab description вне managed block сохраняется без изменений.
9. Отсутствующий или повреждённый managed block запрещает автоматическую запись.

### FR-8: Статусы и жизненный цикл

| MyOwnTMS | GitLab state | Managed label |
|---|---|---|
| Черновик | Issue отсутствует | отсутствует |
| Новый | opened | `myowntms-status-new` |
| В работе | opened | `myowntms-status-in-progress` |
| Проверен | opened | `myowntms-status-verified` |
| Закрыт | closed | `myowntms-status-closed` |

1. Remote closed state переводит локальный баг в `Закрыт`.
2. Несогласованные remote state и status label считаются конфликтом.
3. Опубликованный баг нельзя hard-delete из главного окна.
4. Удалённый или недоступный Issue получает состояние `remote_missing`; новый
   Issue автоматически не создаётся.
5. После появления GitLab binding баг нельзя вернуть в `Черновик`; ограничение
   действует и в GUI, и на service boundary.

### FR-9: GUI и состояния

1. Настройки GitLab включают origin, CA bundle, token-for-session, список
   профилей, проверку соединения и подготовку labels.
2. Bug dialog включает проект, источник, внешний номер и sync status.
3. Доступны действия `Сохранить локально`, `Preview и опубликовать`,
   `Синхронизировать`, `Открыть в GitLab`.
4. Main window показывает проект и sync status опубликованного бага.
5. Сетевые операции выполняются вне GUI thread; окно остаётся отзывчивым.
6. Ошибка показывает безопасное описание, HTTP status и request ID при наличии,
   но не token, request body, description или имена локальных каталогов.

## Non-Functional Requirements

### NFR-1: Network isolation

- GitLab располагается в LAN/VLAN без маршрута в интернет.
- Firewall является основной границей egress deny; проверка origin в приложении
  — дополнительная защита.
- API client обращается только к заранее настроенному origin.
- Redirects отключены; URL из ответа GitLab не используется как новый API host.
- Внешние webhooks, SMTP, CI runners, cloud object storage, telemetry и GitLab
  Duo не входят в контур.

### NFR-2: Security and privacy

- Проекты GitLab только Private.
- Секреты не сохраняются и не логируются.
- Runtime-БД, вложения, build/dist и raw context histories не отслеживаются Git.
- Никакое содержимое артефакта не отправляется до preview и подтверждения.
- Внешние значения проходят length/type validation до записи в БД или GUI.
- Неуправляемое содержимое GitLab не интерпретируется как команда.

### NFR-3: Reliability

- Локальная БД остаётся доступна при любом сбое GitLab.
- Write-запросы не повторяются вслепую.
- `429` учитывает `Retry-After`; фонового retry нет.
- Ошибки `401`, `403`, `404`, `413`, `422`, `429`, `5xx`, timeout, TLS и malformed
  JSON имеют отдельные безопасные состояния.
- Remote и local store не считаются одной атомарной транзакцией; публикация
  реализуется как возобновляемая state machine.

### NFR-4: Performance and UX

- Connect timeout по умолчанию 5 секунд, request timeout 30 секунд.
- Сетевые операции не блокируют Qt event loop.
- Sync получает только конкретный связанный Issue; глобальный импорт не
  выполняется.
- Пользователь всегда видит, идёт ли чтение, запись или upload.

### NFR-5: Compatibility and maintainability

- Текущие v1.0 записи читаются без ручной конвертации.
- Схема managed block имеет явную версию.
- API GitLab изолирован за application adapter.
- Domain mapping и merge logic не зависят от PySide6 widgets.
- HTTP boundary покрывается `httpx.MockTransport`.

## Data and Interfaces

### Local entities for v1.1

Таблицы и ORM-модели созданы в `TASK-GL-001`; validated project-profile и
label-bootstrap service добавлен в `TASK-GL-003`; managed block codec и
resumable publish service добавлены в `TASK-GL-004`; pure three-way merge и
explicit sync service добавлены в `TASK-GL-005`.

- `GitLabProject`: display/customer name, GitLab project ID/path/web URL,
  visibility, active flag, labels readiness timestamps.
- `GitLabBinding`: bug ID, immutable `sync_uid`, project, Issue ID/IID/URL,
  remote timestamp, base snapshot, sync state, last safe error metadata.
- `GitLabAttachmentBinding`: local attachment, content hash, remote upload
  ID/URL/Markdown and upload timestamp.
- `SchemaMigration`: applied migration identifier and timestamp.

### Sync states

`local_only`, `publishing`, `synced`, `local_changed`, `remote_changed`,
`conflict`, `error`, `remote_missing`.

### External API baseline

- GitLab REST API authentication:
  <https://docs.gitlab.com/api/rest/authentication/>
- Issues API:
  <https://docs.gitlab.com/api/issues/>
- Project Markdown uploads:
  <https://docs.gitlab.com/api/project_markdown_uploads/>
- Labels:
  <https://docs.gitlab.com/api/labels/>
- Projects:
  <https://docs.gitlab.com/api/projects/>
- Offline Self-Managed guidance:
  <https://docs.gitlab.com/topics/offline/quick_start_guide/>
- HTTPX SSL, timeouts и mock transports:
  <https://www.python-httpx.org/advanced/ssl/>,
  <https://www.python-httpx.org/advanced/timeouts/>,
  <https://www.python-httpx.org/advanced/transports/>.

## Edge Cases and Failure Modes

- PAT истёк или не имеет прав к одному из проектов.
- Project перемещён, переименован, архивирован или стал не Private.
- Issue удалён вручную или стал недоступен текущему пользователю.
- Create Issue завершился на сервере, но клиент не получил ответ.
- Upload завершился частично.
- Файл изменился после preview, но до upload.
- Несколько локальных вложений имеют одинаковое имя.
- Remote managed block отсутствует, дублирован или имеет неизвестную версию.
- Remote содержит несколько managed labels одной группы.
- Issue закрыт, но status label остался открытым, или наоборот.
- Локальные часы отличаются от GitLab; сравнение опирается на remote timestamp и
  сохранённый snapshot, а не на локальное время.
- Пользователь закрывает приложение во время сетевой операции.
- В GitLab произошла правка между последним GET и PUT. REST API Issues не даёт
  атомарного compare-and-swap; это документированный остаточный риск.

## Implementation Tasks

Подробный порядок, DoD и команды проверки находятся в
[`SESSION_BRIEF_GITLAB_ISSUES.md`](SESSION_BRIEF_GITLAB_ISSUES.md).

| Task | Outcome | Status |
|---|---|---|
| TASK-DOC-001 | SRS, CONTEXT и implementation brief | Implemented locally |
| TASK-SEC-001 | Runtime/user data больше не отслеживаются Git | Local hygiene PASS; commit и remote уже существуют, push status не проверялся |
| TASK-GL-001 | Test foundation и безопасные SQLite migrations | Implemented locally; focused tests PASS |
| TASK-GL-002 | GitLab API client, TLS и session-only token | Implemented locally; MockTransport tests PASS |
| TASK-GL-003 | Project profiles и label bootstrap | Implemented locally; service/API tests PASS |
| TASK-GL-004 | Resumable publish и image uploads | Implemented locally; focused tests PASS |
| TASK-GL-005 | Pull/push и field-level conflicts | Implemented locally; focused tests PASS |
| TASK-GL-006 | PySide6 UX интеграции | Implemented locally; текущий GUI suite NOT RUN из-за `libEGL.so.1` |
| TASK-GL-007 | Windows package и LAN acceptance | Local packaging preflight PASS; Windows/LAN NOT RUN |

## Testing and Acceptance Criteria

### Automated

- Legacy SQLite migration, backup, idempotence and failure rollback.
- Serializer/parser round trip managed block.
- Label and status mappings.
- Three-way merge: local-only, remote-only, non-overlap and conflict.
- URL/origin/TLS validation and secret redaction.
- API responses and failures through `httpx.MockTransport`.
- Publish recovery after uncertain create and partial upload.
- PySide6 draft, preview, progress and conflict UI through `pytest-qt`.

### Manual / environment acceptance

1. Приложение полностью работает при отключённом GitLab.
2. Private project получает labels только после подтверждения.
3. Полный баг с изображением появляется в GitLab без локальных путей.
4. Повтор после timeout не создаёт дубликат.
5. Remote edit синхронизируется локально.
6. Параллельный edit одного поля вызывает conflict dialog.
7. Закрытие работает в обе стороны.
8. После перезапуска PAT запрашивается снова.
9. EXE на чистой Windows-машине доверяет внутреннему CA.
10. Network capture показывает соединения только с настроенным GitLab origin.

Текущий локальный evidence 2026-11-26 относится к commit
`8a88b6b1400f5d1c30558f7ffe060e2ef4144336` плюс незакоммиченным изменениям
защиты labels, lifecycle вложений и published-Draft guard. Ветка — `dev`,
`origin` настроен на GitHub; факт push текущего snapshot не проверялся.
Runtime/user paths в index отсутствуют; denylist, redacted worktree/history
secret scan, `compileall` и `git diff --check` — **PASS**.

Неграфический изолированный suite — **102 passed**: migrations/models/test-env —
**6**, project profiles/bootstrap — **14**, client/codec/publish — **55**,
sync/lifecycle — **27**. Добавлены regressions для label drift перед publish,
durable attachment removal с attachment conflict resolution и запрета возврата
опубликованного бага в `Черновик`. В GUI-файле определено 10 focused tests,
включая post-publish Draft guard, но текущий GUI suite — **NOT RUN**: импорт Qt
останавливается на отсутствующей системной `libEGL.so.1`.

Исторический Linux packaging preflight из `TASK-GL-007` остаётся PASS для
зафиксированного в acceptance report snapshot, но bundle после последних
незакоммиченных source-изменений не пересобирался. Реальная legacy/runtime DB,
GitLab CI, manual responsiveness, clean Windows, реальный GitLab/TLS/role, LAN,
migration/rollback drill и Windows EXE acceptance — **NOT RUN**. Подробности:
[`GITLAB_V1_1_ACCEPTANCE.md`](GITLAB_V1_1_ACCEPTANCE.md).

## Known Issues and Risks

### KR-1: Previous publication may remain outside the clean import

Clean import не содержит `dist/data/tms.db`, пользовательские изображения,
build/dist outputs, Python bytecode, raw `context/` или исходную Git history;
denylist не допускает их повторное отслеживание. Сейчас commit и GitHub remote
уже существуют, но содержимое внешнего remote и факт push текущего snapshot в
этой локальной проверке не исследовались. Старые blobs могут сохраняться во
внешних clones/caches после предыдущей публикации; их удаление и возможная
privacy/credential remediation требуют отдельного решения.

### KR-2: Automated coverage is limited to TASK-GL-001–006

Добавлены focused tests для backup/migration/idempotence/rollback, ORM schema и
GitLab HTTP boundary через `MockTransport`, validated project profiles,
idempotent label bootstrap, managed block/labels, uncertain create recovery,
resumable uploads, pre-publish label drift, durable attachment removal и
attachment conflict, pure three-way merge, explicit pull/push, conflicts,
Close/Reopen, published-Draft/delete guards, remote deletion и post-PUT control
read. PySide6 regressions присутствуют в source, но на текущем host не запущены.
Manual GUI responsiveness, реальный GitLab/TLS и Windows EXE ещё не покрыты. Local Linux
packaging preflight выполнен, но environment acceptance остаётся открытой частью
`TASK-GL-007`.

### KR-3: GitLab is not deployed yet

Версия, edition, CA, roles, limits и offline settings реального GitLab ещё не
проверены. Реальное acceptance остаётся `NOT RUN` до отдельного стенда.

## Decision Records

### DR-1: GitLab Issues, а не Git repository как collaboration backend

GitLab Issue предоставляет командный UI, labels, состояние и вложения. SQLite
остаётся локальным кешем; двоичные базы не синхронизируются Git.

### DR-2: GitLab authoritative after publication

До публикации authoritative local SQLite. После публикации GitLab является
центральным состоянием, а локальные изменения становятся pending до явной sync.

### DR-3: Explicit network only

Нет startup/background sync. Любая передача данных запускается кнопкой и запись
всегда предваряется preview.

### DR-4: Session-only personal PAT

Каждый оператор использует личный токен для персонального GitLab audit. Токен
не сохраняется, даже ценой повторного ввода после запуска.

### DR-5: Free-compatible managed labels

Scoped labels не являются baseline, поскольку требуют Premium/Ultimate.
MyOwnTMS управляет обычными labels с уникальными prefix-группами.

### DR-6: Versioned managed Markdown block

Структурированные поля размещаются в ограниченном блоке, а внешний текст
сохраняется. Повреждённый контракт fail-closed для записи.

### DR-7: Three-way field merge

Последний синхронизированный snapshot позволяет не перезаписывать молча
параллельные изменения. Конфликт разрешается пользователем по каждому полю.

### DR-8: Small embedded SQLite migration runner

Для packaged desktop v1.1 используется последовательный migration registry с
backup и integrity check. Alembic пока не добавляется.

### DR-9: httpx adapter outside GUI thread

HTTP boundary реализуется отдельным adapter, а вызовы выполняются через
`QThreadPool`; mapping и merge logic остаются pure Python.

## Interview Log

- Утечка означает запрет передачи артефактов в интернет; LAN разрешена.
- Выбран вариант GitLab Issues как центральная модель опубликованных багов.
- Баг первоначально создаёт оператор в MyOwnTMS.
- В v1.1 синхронизируются только баги и изображения.
- Один instance обслуживает несколько проектов заказчиков.
- Заказчик не работает в GitLab.
- Сеть используется только по явной команде.
- Каждый оператор вводит личный PAT; токен действует только текущий сеанс.
- Конфликты разрешаются по полям.
- Comments/assignees остаются в GitLab UI.
- Разрешён быстрый локальный черновик.
- Опубликованный баг не удаляется, а закрывается.
- Label bootstrap выполняется только после preview и подтверждения.
- SRS описывает весь MyOwnTMS и расширение v1.1.
- GitLab ещё не развёрнут.
- Для приёма бага добавляются канал и внешний номер без контакта заказчика.
- Очистка отслеживаемых runtime/user files включена как P0 до интеграции.

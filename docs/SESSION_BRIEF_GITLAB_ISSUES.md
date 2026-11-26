# Бриф для следующей сессии: MYOWN-GITLAB-001

> Скопируйте этот текст целиком в первое сообщение новой сессии вместе с ID
> одной задачи. Актуальные источники — `docs/CONTEXT.md`, `docs/SRS.md` и этот
> brief. Не выполнять соседние задачи без отдельного запроса.

---

## Задача: MYOWN-GITLAB-001 — локальная совместная работа через GitLab Issues

**Контекст:** MyOwnTMS — локальное PySide6-приложение с SQLAlchemy/SQLite,
вложениями и экспортом. v1.1 должна сохранить полный offline mode и добавить
явную синхронизацию только баг-репортов с GitLab Self-Managed в изолированной
LAN. GitLab ещё не развёрнут. Полные требования и решения находятся в
`docs/SRS.md`; оперативный статус — в `docs/CONTEXT.md`.

**Цель:** Оператор быстро фиксирует сообщение заказчика локально, публикует
готовый баг в выбранный приватный GitLab-проект и безопасно синхронизирует
изменения без фоновой передачи данных, потери локальной работы или сохранения
PAT на диск.

**Definition of Done (DoD):**
1. Runtime/user files не попадают в новые Git commits.
2. Legacy SQLite обновляется с backup, integrity check и сохранением данных.
3. Приложение работает полностью локально при недоступном GitLab.
4. Token существует только в памяти текущего запуска.
5. Поддержаны несколько Private projects одного Self-Managed instance.
6. Project labels создаются только после preview и подтверждения.
7. Публикация показывает все передаваемые поля и файлы.
8. Один локальный bug создаёт не более одного Issue после timeout/retry.
9. PNG/JPEG uploads возобновляются без дублей.
10. Sync выполняет field-level three-way merge и не затирает конфликт молча.
11. Опубликованный баг закрывается, но не hard-delete.
12. GUI не блокируется сетевыми операциями.
13. Windows EXE проходит LAN/TLS/offline acceptance.
14. `docs/SRS.md`, `docs/CONTEXT.md` и этот brief отражают фактический статус.

## TASK-SEC-001 — Git hygiene до интеграции

**Dependencies:** `TASK-DOC-001` завершён.

**Status:** Local hygiene PASS. Snapshot перенесён без старой `.git` и
runtime/user files; текущий index и будущий CI защищены denylist. Локальный
репозиторий уже содержит commit и GitHub `origin`; факт push текущего snapshot
не проверен. Остаточный риск внешних clones/caches от
предыдущей публикации рассматривается отдельно.

**Outcome:** Репозиторий можно подключать к приватному GitLab без автоматической
отправки runtime-БД, пользовательских вложений, build outputs и raw histories.

**DoD:**
1. Составлен список отслеживаемых runtime/user/generated paths без чтения и
   публикации содержимого артефактов.
2. Добавлен `.gitignore` минимум для `data/`, `dist/`, `build/`, `__pycache__/`,
   `*.py[cod]`, SQLite runtime/backup и raw `context/*.json`.
3. Уже отслеживаемые runtime/generated файлы удалены только из Git index;
   локальные пользовательские файлы сохранены.
4. Добавлена локальная/CI denylist-проверка `git ls-files`.
5. Выполнен секрет-скан текущего tree/history с redacted output: отчёт содержит
   только тип и путь, но не значение секрета.
6. Переписывание истории и удаление remote data не выполнялись; commit и remote
   существуют, а push status остаётся непроверенным.

**Validate with:**

```bash
git status --short
git ls-files
git diff --check
```

Проверка должна доказать отсутствие DB, attachments, build/dist и raw context
в index. Если remote уже содержал эти данные, остановиться и отдельно запросить
решение о history rewrite/rotation.

**Evidence 2026-11-25:**

- path-only inventory до очистки: `build/` — 14 файлов; `dist/` — 18 файлов,
  включая 16 вложений и одну SQLite DB; `__pycache__/` — 23 файла;
  `context/*.json` — 4 файла;
- перечисленные paths удалены только из index; локальная DB и 16 вложений
  подтверждены на месте;
- `python3 scripts/check_git_hygiene.py` — PASS;
- `python3 scripts/scan_secrets.py` — PASS, worktree findings: 0, reachable
  history findings: 0; scanner выводит только тип и путь;
- `.gitlab-ci.yml` job — NOT RUN (GitLab/runner ещё не развёрнут);
- history rewrite, remote deletion, push и pull — NOT RUN.

**Clean import evidence 2026-11-25:**

- clean snapshot создан из `ec7f7fa` без исходной `.git` и старых commits;
- `context/`, `data/`, `dist/`, `build/`, attachments, SQLite и bytecode в
  snapshot отсутствуют;
- исторически clean import был создан без старой `.git`; текущий репозиторий —
  ветка `dev`, commit `8a88b6b1400f5d1c30558f7ffe060e2ef4144336`, GitHub `origin`;
  содержимое remote и push status локально не проверены;
- initial commit и push оставлены владельцу репозитория.

## TASK-GL-001 — tests и безопасные SQLite migrations

**Dependencies:** `TASK-SEC-001`.

**Status:** Implemented locally. Focused temporary-DB tests PASS; GitLab CI,
real legacy/runtime DB и Windows EXE — NOT RUN.

**Outcome:** Есть изолированный тестовый контур и версионированное обновление
legacy-БД без пересоздания пользовательских данных.

**DoD:**
1. Добавлены dev requirements с `pytest` и `pytest-qt`.
2. Data/database path можно переопределить только для теста без обращения к
   реальному `data/` или `dist/data/`.
3. Добавлен embedded migration registry; Alembic не вводится.
4. Перед первой pending migration создаётся согласованный backup через SQLite
   backup API.
5. Migration добавляет planned GitLab tables/fields и `Черновик`, сохраняя все
   legacy rows, links и attachments.
6. После migration выполняется `PRAGMA integrity_check`.
7. Повторный запуск идемпотентен; ошибка оставляет исходную БД восстановимой.

**Validate with:** focused migration tests на временных копиях legacy fixture,
новой пустой БД, повторном запуске и принудительном исключении. Общий реальный
`dist/data/tms.db` не использовать.

**Evidence 2026-11-25:**

- `requirements-dev.txt` содержит `pytest` и `pytest-qt`; CI job добавлен, но
  GitLab runner ещё **NOT RUN**;
- pytest imports перенаправлены в одноразовый test data directory, runtime
  `data/` и `dist/data/` не использовались;
- embedded migration `0001_gitlab_v1_1_schema` создаёт backup через SQLite
  backup API, применяет schema transactionally и выполняет `integrity_check`;
- legacy fixture сохранила test case, bug report, attachment и artifact link;
- новая DB, повторный запуск и forced-exception rollback проверены;
- `/tmp/myowntms-task-gl001-venv/bin/python -m pytest -q -p no:pytest-qt` —
  **6 passed**;
- `python3 -m compileall -q src tests run.py` — **PASS**;
- обычная активация `pytest-qt` в текущем Linux-контейнере требует отсутствующую
  системную `libEGL.so.1`; GUI tests относятся к `TASK-GL-006`.

## TASK-GL-002 — GitLab API client и security boundary

**Dependencies:** `TASK-GL-001`.

**Status:** Implemented locally. MockTransport tests PASS; real GitLab, internal
CA handshake, LAN и Windows EXE — NOT RUN.

**Outcome:** Изолированный, тестируемый API adapter с обязательным TLS и
session-only PAT.

**DoD:**
1. Runtime dependency `httpx` добавлена с совместимым ограничением версии.
2. Поддержан один HTTPS origin и optional internal CA bundle.
3. Redirects и `verify=False` запрещены.
4. Token prompt не сохраняет PAT после завершения процесса.
5. API adapter реализует connection/project check, labels, issue get/create/
   update и project upload.
6. Connect/request timeouts имеют безопасные defaults 5/30 секунд.
7. `401`, `403`, `404`, `413`, `422`, `429`, `5xx`, timeout, TLS и malformed JSON
   преобразуются в typed errors без body/token в логах.
8. `429` учитывает `Retry-After`; write requests не повторяются вслепую.

**Validate with:** `httpx.MockTransport`, fake CA/TLS boundary, URL/origin tests
и redaction assertions. Реальный GitLab на этом этапе `NOT RUN`.

**Evidence 2026-11-25:**

- runtime dependency: `httpx>=0.27,<0.29`; tested with `httpx 0.28.1`;
- adapter implements current-user/project checks, labels, Issue get/create/
  update and project Markdown upload endpoints;
- HTTPS-only canonical origin, no redirects, `trust_env=False`, SSL context and
  optional absolute CA bundle boundary are covered; pytest-only loopback HTTP is
  isolated from runtime;
- first network action can obtain PAT through a UI-owned callback; PAT remains
  only in the thread-safe in-memory `SessionToken`, is absent from repr/errors
  and can be cleared;
- defaults connect/request are 5/30 seconds and confirmed in request extensions;
- `401`, `403`, `404`, `413`, `422`, `429`, `5xx`, timeout, TLS, connection and
  malformed JSON map to safe typed errors; response body, token and unsafe
  request ID are not exposed;
- `429` exposes bounded `Retry-After`; redirects and write failures receive no
  automatic retry;
- focused MockTransport command — **38 passed**; full isolated suite —
  **44 passed**; real GitLab/TLS/LAN — **NOT RUN**.

## TASK-GL-003 — project profiles и label bootstrap

**Dependencies:** `TASK-GL-002`.

**Status:** Implemented locally. Service/API tests PASS; GUI settings smoke,
real GitLab, internal CA, real roles, LAN и Windows EXE — NOT RUN.

**Outcome:** Оператор безопасно добавляет несколько Private projects одного
GitLab instance и явно готовит каждый к синхронизации.

**DoD:**
1. Реализована persistence-модель `GitLabProject` без token.
2. Project profile создаётся только после API validation numeric ID/path/URL и
   visibility `private`.
3. Перед mutation показывается preview недостающих managed labels.
4. После подтверждения создаются только отсутствующие labels.
5. Повторный bootstrap идемпотентен.
6. Архивный, недоступный или не-private project получает контролируемую ошибку.

**Validate with:** service/API tests для multiple projects, duplicate bootstrap,
insufficient role и non-private project; GUI smoke настроек.

**Evidence 2026-11-25:**

- `GitLabProjectService` получает project по numeric ID и до локального commit
  проверяет совпадение ID, bounded `path_with_namespace`, same-origin web URL,
  `visibility=private` и `archived=false`;
- несколько profiles сохраняются без PAT; duplicate remote project получает
  controlled application error;
- preview возвращает недостающие из 13 managed labels без POST; confirm создаёт
  только labels из preview, которые всё ещё отсутствуют;
- после bootstrap выполняется повторный list; `labels_ready_at` ставится только
  при полном наборе, pagination учитывается, повторный bootstrap не создаёт
  labels; rename обновляет профиль при новом preview, а stale preview блокируется;
- malformed/foreign URL, archived/non-private/unavailable project,
  case-collision и simulated `403` insufficient role покрыты controlled errors;
- focused command — **14 passed**; полный изолированный suite — **58 passed**;
  `python3 -m compileall -q src tests run.py` и `git diff --check` — **PASS**;
- GUI settings smoke относится к `TASK-GL-006`; реальный GitLab/TLS/roles/LAN
  — **NOT RUN**.

**Correction evidence 2026-11-26:** перед каждым publish профиль проекта и все
13 managed labels перечитываются. Label drift блокирует Issue write, сбрасывает
`labels_ready_at` и требует нового preview/confirm bootstrap. Focused tests —
**14 passed**; реальный GitLab — **NOT RUN**.

## TASK-GL-004 — resumable publish и image uploads

**Dependencies:** `TASK-GL-003`.

**Status:** Implemented locally. Focused codec/publish/API tests PASS; real
GitLab, internal CA, LAN, GUI и Windows EXE — NOT RUN.

**Outcome:** Полный локальный баг публикуется ровно в один Issue, а частичные
сбои безопасно возобновляются.

**DoD:**
1. Добавлены pure serializer/parser versioned managed block и managed labels.
2. Publish validation блокирует черновик и неполные обязательные поля.
3. Preview перечисляет project, поля и каждый файл до network write.
4. `sync_uid` и publishing state фиксируются до POST.
5. Uncertain create восстанавливается поиском точного marker; duplicate create
   запрещён.
6. PNG/JPEG проверяются по содержимому и лимиту 10 MiB.
7. Attachment bindings используют local attachment ID + SHA-256 и не создают
   duplicate uploads.
8. Partial upload/publish имеет resumable error и не удаляет remote Issue.
9. Текст вне managed block и unmanaged labels сохраняются.

**Validate with:** unit/API tests happy path, timeout before/after Issue create,
потерянный upload response, existing marker, changed/missing file, duplicate
filename/hash, partial upload и resume after process restart.

**Evidence 2026-11-25:**

- pure managed block serializer/parser делает canonical version 1 round trip,
  fail-closed обрабатывает duplicate/malformed/unknown marker и сохраняет текст
  вне блока; managed label merge сохраняет unmanaged labels;
- preview не выполняет network write, перечисляет destination, все поля и все
  файлы, помечая неподдерживаемые вложения как не передаваемые; draft,
  незаполненные поля и stale preview блокируются;
- новый UUID4 `sync_uid` и состояние `publishing` коммитятся до create Issue;
  повторный publish без local Issue metadata сначала выполняет project-scoped
  поиск exact marker по description;
- timeout до обработки create оставляет resumable state, а timeout после
  создания восстанавливает единственный Issue без второго POST;
- PNG/JPEG проверяются по extension/signature, наличию и лимиту 10 MiB; remote
  имя не содержит локальный path и включает attachment ID;
- bindings используют attachment ID + SHA-256; каждый успешный upload сохраняет
  remote ID/URL/Markdown отдельно, а restart переиспользует завершённые bindings;
- upload intent сохраняется до POST; после timeout, обрыва, 5xx или потерянного /
  malformed success-response автоматический повтор этого upload блокируется,
  потому что GitLab upload API не принимает idempotency key и без ответа не
  возвращает recoverable URL/Markdown; однозначный отказ удаляет intent и
  допускает явный повтор;
- partial upload возвращает безопасный resumable error и не удаляет Issue;
  финальный GET/PUT сохраняет внешний текст и unmanaged labels;
- focused codec/publish/API command — **47 passed**; полный изолированный suite
  — **67 passed**; `python3 -m compileall -q src tests run.py` и
  `git diff --check` — **PASS**;
- real GitLab/TLS/LAN, GUI и Windows EXE — **NOT RUN**.

**Correction evidence 2026-11-26:** lost-response regression сохраняет
незавершённый intent между DB sessions и подтверждает один upload POST после
явного повтора; дополнительная label-drift проверка выполняется до write.
Publish/client tests — **55 passed**, весь неграфический suite — **102 passed**.
Реальный GitLab — **NOT RUN**.

## TASK-GL-005 — sync, conflicts и lifecycle

**Dependencies:** `TASK-GL-004`.

**Status:** Implemented locally. Focused sync/lifecycle tests PASS; real GitLab,
internal CA, LAN, GUI conflict flow и Windows EXE — NOT RUN.

**Outcome:** Явный pull/push синхронизирует основные поля без молчаливой потери
изменений.

**DoD:**
1. Сохраняется normalized base snapshot последней успешной sync.
2. Реализован pure three-way merge `base/local/remote`.
3. Remote-only применяется локально; local-only отправляется после preview.
4. Non-overlapping changes объединяются с итоговым preview.
5. Same-field conflict требует выбора local/remote для каждого поля.
6. Corrupt/missing/version-unknown block fail-closed для write.
7. Status/label/state mapping соответствует SRS.
8. Published bug hard-delete заблокирован; Close/Reopen синхронизируются.
9. Missing Issue становится `remote_missing` без auto-republish.
10. Остаточная GET→PUT race документирована и после PUT выполняется контрольное
    чтение текущего remote state.

**Validate with:** pure merge matrix и API tests всех sync states, managed/unmanaged
content, inconsistent labels/state, remote deletion и concurrent changes.

**Evidence 2026-11-25:**

- normalized base snapshot совместим с publish snapshot и обновляется только
  после успешного pull либо подтверждённого PUT + control GET;
- pure merge покрывает no-op, local-only, remote-only, non-overlapping changes и
  same-field conflicts с обязательным выбором local/remote для каждого поля;
- preview повторно проверяется по local state и полной remote revision перед
  write; внешний Markdown и unmanaged labels сохраняются;
- missing/corrupt/version-unknown block, duplicate/unknown managed labels,
  identity mismatch и inconsistent status/state fail-closed;
- remote `404` сохраняет `remote_missing` и не выполняет create/re-publish;
  другие API failures сохраняют безопасный `error` metadata;
- Close/Reopen проверены в обе стороны; hard-delete GitLab-bound bug блокируется
  в `BugReportService`, а обычное редактирование меняет sync state на
  `local_changed`;
- после PUT выполняется контрольный GET; изменение между PUT и control read
  переводит binding в `conflict`. Неатомарная GET→PUT race остаётся
  документированным ограничением GitLab Issues API;
- исторический focused command — **24 passed**; полный изолированный suite на
  том snapshot — **91 passed**;
  `python3 -m compileall -q src tests run.py` и `git diff --check` — **PASS**;
- real GitLab/TLS/LAN, GUI conflict flow и Windows EXE — **NOT RUN**.

**Correction evidence 2026-11-26:** удаление опубликованного локального
вложения сохраняет exact Markdown как pending removal в base snapshot. Sync
показывает `base/local/remote`, удаляет ссылку только после подтверждения, а
concurrent remote edit требует explicit choice. GitLab-bound bug нельзя вернуть
в `Черновик` на service boundary. Focused sync/lifecycle tests — **27 passed**;
полный неграфический suite — **102 passed**.

## TASK-GL-006 — PySide6 UX

**Dependencies:** `TASK-GL-003`, `TASK-GL-004`, `TASK-GL-005`.

**Status:** Implemented locally. Текущий GUI suite NOT RUN из-за отсутствующей
`libEGL.so.1`; manual responsiveness, real GitLab/TLS/LAN и Windows EXE — NOT RUN.

**Outcome:** Вся интеграция доступна через понятный GUI без блокировки event loop.

**DoD:**
1. Настройки GitLab: origin, CA, token-for-session, projects, connection test,
   label bootstrap.
2. Bug dialog: `Черновик`, project, source channel, external reference и sync
   state.
3. Действия: Save locally, Preview/Publish, Sync, Open in GitLab.
4. Main table показывает project и sync state.
5. Conflict dialog отображает base/local/remote и требует выбор.
6. Network calls выполняются через `QThreadPool`; buttons/progress/error states
   исключают двойной запуск.
7. Закрытие приложения во время запроса не повреждает DB и не вызывает запись
   после уничтожения widgets.

**Validate with:** focused `pytest-qt` для draft/publish/sync/conflict/delete
guard и ручной responsiveness smoke. Реальный LAN остаётся `NOT RUN`.

**Evidence 2026-11-25:**

- runtime-only settings покрывают origin, internal CA, session PAT, connection
  test, validated projects и explicit label preview/confirm;
- bug dialog поддерживает draft/project/source/reference/sync state и действия
  Save locally, Preview/Publish, Sync и Open in GitLab; main table показывает
  project/sync state;
- publish/sync preview показывают передаваемые данные, conflict dialog требует
  local/remote выбор по каждому конфликтующему полю;
- network operations используют `QThreadPool`, отдельную SQLAlchemy session,
  busy/progress state и Qt auto-disconnect для уничтоженных widgets;
- исторический focused headless pytest-qt command — **8 passed**; полный
  изолированный suite на том snapshot — **99 passed**;
  `python3 -m compileall -q src tests run.py` и
  `git diff --check` — **PASS**;
- manual responsiveness, real GitLab/TLS/LAN, GitLab CI и Windows EXE —
  **NOT RUN**.

**Correction evidence 2026-11-26:** после первой публикации `Черновик` сразу
недоступен; conflict dialog отображает pending removal вложения. Определено 10
focused GUI tests, но текущий запуск — **NOT RUN**: импорт Qt требует
отсутствующую `libEGL.so.1`.

## TASK-GL-007 — package и LAN acceptance

**Dependencies:** `TASK-GL-001`–`TASK-GL-006`.

**Status:** Local packaging preflight PASS; clean Windows, real GitLab/internal
CA/LAN, migration/rollback drill and egress capture — NOT RUN. Task remains open.

**Outcome:** Собранный Windows EXE подтверждён на реальном изолированном GitLab.

**DoD:**
1. PyInstaller spec включает необходимые httpx/TLS assets без token/config data.
2. EXE запускается на чистой поддерживаемой Windows-машине.
3. Legacy DB backup/migration и rollback drill пройдены на копии.
4. Private GitLab project и internal CA проходят create/upload/sync/conflict/
   close scenarios.
5. GitLab outage оставляет local workflow рабочим.
6. После restart PAT отсутствует и запрашивается снова.
7. Network capture/firewall logs подтверждают только configured GitLab origin и
   отсутствие internet egress.
8. SRS, CONTEXT и brief обновлены точными evidence; незапущенное осталось
   `NOT RUN`.

**Validate with:** отдельный acceptance report с версиями EXE/GitLab, командами,
результатами и rollback. Production-like rollout без явного разрешения не
выполнять.

**Evidence 2026-11-26:**

- `MyOwnTMS.spec` использует explicit allowlist только для public documentation
  и style assets; runtime data/DB, CA bundle, GitLab config и PAT не включаются;
- PyInstaller `6.22.3` + hooks-contrib `2026.10` на Linux успешно собрал
  one-file bundle; Analysis содержит `httpx`, `httpcore`, `_ssl`, TLS libraries
  и `certifi/cacert.pem`;
- текущий неграфический изолированный suite — **102 passed**; Git hygiene и redacted
  worktree/history secret scan — **PASS**;
- frozen Linux startup и полный GUI suite — **NOT RUN/PRECONDITION FAILED**:
  host не содержит системную `libEGL.so.1`; Linux bundle не является Windows EXE;
- создан отдельный точный report/runbook:
  `docs/GITLAB_V1_1_ACCEPTANCE.md`;
- исторический Linux bundle не пересобирался после последних source-изменений;
- clean Windows build/start, representative legacy DB migration/rollback,
  real Private GitLab/internal CA create/upload/sync/conflict/close, outage,
  restart PAT и network/firewall capture — **NOT RUN**.

## Известные риски для проверки

- Текущие hygiene и redacted secret checks проходят; опубликованные ранее
  clones/caches остаются отдельным непроверенным риском.
- GitLab ещё не развёрнут: edition/version/roles/limits неизвестны.
- Test coverage ограничен локальными `TASK-GL-001`–006; manual responsiveness и
  реальный GitLab не проверены.
- REST Issue update не предоставляет атомарный compare-and-swap между GET/PUT.
- GitLab upload и SQLite не являются общей транзакцией.
- После неопределённого upload outcome публикация остаётся в error до
  операторской сверки: автоматический POST запрещён, поскольку API не позволяет
  безопасно восстановить потерянные URL/Markdown.
- Remote upload может остаться на GitLab после удаления локальной ссылки.
- Реальные вложения могут содержать PII; preview не заменяет ручную проверку
  оператором.

## Дополнительно (только отдельными задачами)

- Импорт Issue, созданных в GitLab.
- Comments/assignees/milestones в MyOwnTMS.
- Синхронизация test cases.
- Background sync/webhooks.
- Несколько GitLab instances.
- Клиентское end-to-end encryption.
- Git history rewrite и удаление уже опубликованных sensitive blobs.

## Как начать

```text
1. Прочитать docs/CONTEXT.md, docs/SRS.md и этот brief целиком.
2. Проверить git status --short и не затрагивать пользовательские изменения.
3. Выбрать одну ещё открытую задачу и соблюдать её dependencies/границы.
4. Выполнить только выбранную задачу и её focused validation.
5. Не использовать реальные data/dist DB или attachments в тестах.
6. Не выполнять commit, push, pull, history rewrite, deploy или внешний network
   access без отдельного разрешения.
7. Обновить task status и фактическое evidence одновременно в SRS, CONTEXT и
   brief; непроверенное отметить NOT RUN.
```

# MyOwnTMS v1.1 — Windows package и LAN acceptance

## Назначение

Этот отчёт фиксирует проверки `TASK-GL-007` без смешивания локального
packaging preflight и фактического acceptance на Windows/GitLab-стенде.
Заполнять `PASS` можно только после выполнения указанной проверки и сохранения
несекретного evidence. PAT, содержимое баг-репортов и вложений в отчёт не
добавляются.

## Текущий результат

Дата локальной проверки: 2026-11-26.

Исходный snapshot: `b87efcad7589f21a31a9f30295958892ac805010` плюс
незакоммиченные изменения `TASK-GL-005`–`TASK-GL-007`; SHA сам по себе не
идентифицирует весь проверенный snapshot.

Локальная среда:

- Linux `6.8.0-147-generic`, x86_64;
- Python `3.12.3`;
- PyInstaller `6.22.3`, hooks-contrib `2026.10`;
- PySide6 `6.12.0`;
- SQLAlchemy `2.1.9`;
- httpx `0.28.1`;
- certifi `2026.11.20`.

| Проверка | Результат | Evidence / ограничение |
|---|---|---|
| PyInstaller Analysis и one-file build на Linux | PASS | Bundle создан в `/tmp`; SHA-256 `844a65d0727764d90e94ca2cf5cb90a4110a0701d4287ee9eea599b38c79be39` |
| httpx/TLS содержимое bundle | PASS | Analysis содержит `httpx`, `httpcore`, `_ssl`, TLS library и `certifi/cacert.pem` |
| Отсутствие runtime/config data в spec | PASS | `datas` — явный allowlist styles и публичной документации; DB, attachments, CA, settings и PAT не включены |
| Linux frozen startup smoke | BLOCKED | Bundle собран, но хост не содержит системную `libEGL.so.1`; приложение не стартовало |
| Неграфический изолированный suite | PASS | `91 passed`; GUI tests не запускались из-за той же отсутствующей `libEGL.so.1` |
| Git hygiene | PASS | Запрещённые runtime/generated paths не отслеживаются |
| Redacted secret scan | PASS | Worktree/history findings: `0` / `0` |
| Windows EXE build | NOT RUN | Нужна Windows build-машина |
| Запуск EXE на чистой Windows | NOT RUN | Нужна отдельная поддерживаемая Windows-машина |
| Legacy DB migration и rollback drill | NOT RUN | Нужна одноразовая копия representative legacy DB; реальные runtime DB запрещены |
| Private GitLab + internal CA scenarios | NOT RUN | GitLab-стенд не предоставлен |
| GitLab outage / local workflow | NOT RUN | Нужны Windows EXE и стенд |
| PAT после restart | NOT RUN | Нужен Windows EXE runtime smoke |
| Network capture и firewall egress evidence | NOT RUN | Нужен изолированный LAN и оператор firewall/capture |

Локальная сборка не является Windows EXE и не закрывает environment acceptance.

## Воспроизведение локального packaging preflight

Временные пути не должны находиться внутри репозитория:

```bash
python3 -m venv /tmp/myowntms-task-gl007-venv
/tmp/myowntms-task-gl007-venv/bin/python -m pip install -r requirements-dev.txt
env PYINSTALLER_CONFIG_DIR=/tmp/myowntms-task-gl007-pyinstaller \
  /tmp/myowntms-task-gl007-venv/bin/python -m PyInstaller \
  --noconfirm --clean \
  --distpath /tmp/myowntms-task-gl007-dist \
  --workpath /tmp/myowntms-task-gl007-build \
  MyOwnTMS.spec
/tmp/myowntms-task-gl007-venv/bin/pyi-archive_viewer \
  -l -r -b /tmp/myowntms-task-gl007-dist/MyOwnTMS
/tmp/myowntms-task-gl007-venv/bin/python -m pytest -q \
  -p no:pytest-qt --ignore=tests/gui
python3 scripts/check_git_hygiene.py
python3 scripts/scan_secrets.py
git diff --check
```

На Linux host 2026-11-26 полный pytest и frozen startup не прошли импорт Qt:
`libEGL.so.1` отсутствует. Это ограничение среды, а не пройденная проверка.

## Windows build record

Выполнять на отдельной Windows build-машине из чистого source snapshot. Не
копировать в build tree runtime `data/`, пользовательские вложения, CA или PAT.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean MyOwnTMS.spec
Get-FileHash .\dist\MyOwnTMS.exe -Algorithm SHA256
```

Заполнить после выполнения:

- Windows edition/build: `NOT RUN`
- Python/PyInstaller/PySide6 versions: `NOT RUN`
- Source commit и подтверждение clean worktree: `NOT RUN`
- EXE SHA-256: `NOT RUN`
- Build warnings reviewed: `NOT RUN`
- Full automated suite: `NOT RUN`

## Чистая Windows и migration/rollback drill

1. Перенести только проверенный `MyOwnTMS.exe` и записать его hash.
2. Разместить рядом с EXE каталог `data/` с одноразовой копией representative
   legacy `tms.db`. Не использовать единственную или production-like копию.
3. До запуска записать SHA-256 DB, выполнить `PRAGMA integrity_check`, сохранить
   безопасные counts `test_cases`, `bug_reports`, `attachments`,
   `artifact_links`.
4. Запустить EXE. Убедиться, что рядом создан единственный
   `tms.db.backup-<timestamp>`, приложение открывается, а данные доступны.
5. Повторить integrity check и counts; проверить migration ID
   `0001_gitlab_v1_1_schema`.
6. Закрыть приложение. Для rollback переименовать migrated DB, восстановить
   backup под именем `tms.db`, снова проверить integrity/counts и запуск legacy
   snapshot совместимой версией приложения.
7. Удалить одноразовые данные с acceptance-машины по согласованной процедуре.

Заполнить после выполнения:

- Windows machine/OS: `NOT RUN`
- Legacy fixture provenance, без содержимого и PII: `NOT RUN`
- Pre/post integrity and safe counts: `NOT RUN`
- Backup filename и hash: `NOT RUN`
- Rollback result: `NOT RUN`

## LAN GitLab acceptance

Предусловия:

- изолированный GitLab Self-Managed без internet egress;
- Private test project и отдельный acceptance PAT с минимальными правами;
- внутренний CA bundle как внешний файл на acceptance-машине;
- разрешённый destination — только configured GitLab origin;
- synthetic bug data и PNG/JPEG без PII.

Записать GitLab edition/version, project numeric ID, CA fingerprint, роль
оператора и firewall/capture method. Не записывать PAT, Issue body или файлы.

| Сценарий | Ожидаемый результат | Результат |
|---|---|---|
| Connection и label bootstrap | Private project validated; mutation только после preview/confirm | NOT RUN |
| Create + PNG/JPEG upload | Один Issue; managed block/labels корректны; локальные пути отсутствуют | NOT RUN |
| Remote-only sync | Изменение GitLab применяется локально после preview | NOT RUN |
| Local-only sync | Изменение отправляется после preview и control GET | NOT RUN |
| Same-field conflict | Для каждого поля требуется explicit local/remote choice | NOT RUN |
| Close/Reopen | Status label и Issue state согласованы в обе стороны | NOT RUN |
| GitLab outage | Локальные CRUD/export продолжают работать; network error контролируемый | NOT RUN |
| Restart | PAT отсутствует и запрашивается заново | NOT RUN |
| Egress capture | Только configured GitLab origin; internet egress отсутствует | NOT RUN |

## Итоговый sign-off

`TASK-GL-007` остаётся открытой до выполнения всех обязательных Windows/LAN
проверок. Финальный результат: **NOT RUN**.

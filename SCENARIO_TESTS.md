# Scenario Tests (PST) — WordPress Hub

Метод: `Docs/session-notes/SCENARIO_TESTING_STANDARD.md`. Систематический
(не выборочный) grep всех 259 `@chat.function` имён против текста всех
файлов `tests/*.py`, чтобы найти функции, ни разу не вызванные напрямую
по имени ни в одном тесте.

---

## Прогон 2026-08-20 — Часть D (Deploy Verification / Idempotency / Security-SSRF / Regression grep)

**D1 (Deploy Verification):** не применялось — код приложения не менялся (только тесты).

**D2 (Idempotency):** добавлен 1 тест в `tests/test_post_lifecycle.py` — повторный `delete_post(force=true)` на уже permanently-удалённом посте. WordPress возвращает свой собственный 404, обработка чистая (не падает, не заявляет о втором успешном permanent-удалении — это особенно важно для force-delete, у которого нет undo, в отличие от обычного trash). Самопроверка: первая версия теста провалилась не из-за бага приложения, а из-за собственной ошибки в моке — `MockHTTP._find()` совпадает с ПЕРВОЙ зарегистрированной записью по паттерну URL (не очередь), так что второй `_mock_delete()` с тем же паттерном не переопределял первый; исправлено явной очисткой `ctx.http._mocks` перед регистрацией второго ответа.

**D3 (Security/SSRF):** добавлен 1 тест в `tests/test_pst_coverage.py`. `upload_media`'s собственное описание прямо фиксирует safe-by-design контракт: "WordPress fetches the image itself (via the Imperal Bridge plugin) — Imperal never downloads or re-uploads the image bytes." Подтверждено на уровне кода: `sideload_image` только POST'ит `source_url` как JSON body на bridge-эндпоинт самого сайта, никогда не GET'ит его напрямую. Добавлен regression-тест против этого контракта тихо регрессировавшего в будущем.

**D4 (Regression grep):** нет новых находок специфичных для этого приложения сверх `Docs/known-bug-patterns.md`.

**Итог:** 889/889 тестов зелёные (было 887). Реальных багов не найдено (в отличие от прогона 2026-08-19, где были найдены и исправлены 2 реальных бага).

---

## Прогон 2026-08-19

Предыдущий сквозной пост-аудит этого приложения (см. запись ниже в
`POST_AUDIT_LOG.md`) проверил окружение, классификацию `action_type` и
double-prompt антипаттерн, но не проверял покрытие по имени функции.

**Найдено 9 функций из 259, ни разу не вызванных напрямую ни в одном
тесте:** `add_ssh`, `remove_ssh`, `create_network_site`,
`refresh_all_sites`, `list_scheduled`, `list_users`, `list_custom_posts`,
`list_wp_abilities`, `update_order_status_risky`.

Написан `tests/test_pst_coverage.py` — 23 сценария, реально вызывающих
каждую из 9 функций через `MockContext` (happy path, ошибочные пути,
пагинация, отказ на не-multisite сайте, недостижимый сайт и т.д.).

### Найдены и исправлены 2 реальных бага кода приложения

1. **`create_network_site` был полностью нерабочим.**
   `handlers_multisite.py` вызывал `wp_post(..., json_body=payload)`
   напрямую — но `wp_post()` в `wp_client.py` принимает параметр `json=`,
   не `json_body=`. Каждый реальный вызов падал с `TypeError` ещё до
   отправки запроса. Все остальные файлы в приложении избегают этой
   ошибки, оборачивая `wp_post` в локальный `_bridge_post(..., json_body=None)`,
   который сам транслирует `json_body` → `json=` — `handlers_multisite.py`
   был единственным местом, где `wp_post` вызывался напрямую с неверным
   именем аргумента. Исправлено: `json_body=payload` → `json=payload`.

2. **`remove_ssh` не снимал SSH-производные поля с записи о сайте.**
   Код делал `record.pop(field, None)` для восьми полей
   (`ssh_host`, `wp_version`, `php_version`, `db_size_mb`, `cron_count`,
   `pending_updates`, `plugin_updates_list`, `theme_updates_list`,
   `server_last_checked`), затем сохранял урезанный словарь через
   `storage.save_site_record()` → `ctx.store.update()`. Но платформенная
   схема `store_update.json` документирует `store.update` как **patch
   semantics only** ("Field values to apply (patch semantics)") — у
   реального стора нет примитива удаления ключа, `update()` только
   мёржит переданные поля поверх существующих. Значит `.pop()` перед
   `save_site_record()` был тихим no-op: после «удаления» SSH сайт
   продолжал бы вечно показывать старые `wp_version`/`php_version`/
   `db_size_mb`/`cron_count`/список обновлений, как будто SSH всё ещё
   подключён — вводящие в заблуждение данные о сервере. Подтверждено
   не только моком (`MockStore.update` делает `dict.update()`), но и
   прямым текстом платформенной JSON-схемы `store_update.json`.
   Исправлено: вместо `.pop()` поля явно обнуляются (`""` / `[]`), что
   реально переживает patch-семантику стора.

### Итог

23/23 новых теста зелёные. Полный набор: 887/887 (было 864, +23).
Оба фикса — правки кода приложения (2 файла), не тестов под баг.

# WordPress Hub Connector — UI component plan

Источники: `Docs/session-notes/UI_COMPONENT_VOCABULARY.md`, `UI_INTERFACE_STANDARD.md`,
`concepts/panels.md`. Основано на `POST_CONNECT_EXPERIENCE.md` этого приложения.

## 1. Компоненты

| Экран | Примитивы | Почему именно эти |
|---|---|---|
| Sidebar (left) | `ui.Column`(align="start") + `ui.Text`(site URL) + `ui.Divider` + navigation `ui.ListItem`(Posts/Pages/Media/Comments/Plugins) + `ui.Button`("App settings") | Без карточек по стандарту. |
| Post List (center, `center_overlay=True`) | `ui.Stats`(Published/Draft/Scheduled) + `ui.Select`(status_filter) + `ui.DataTable`(title, author, status Badge publish/draft/pending, date; sortable) | `DataTable` — стандартный способ обзора записей блога/CMS. |
| Post Editor | Back-button + `ui.Input`(title) + `ui.RichEditor`(content, полноценное редактирование HTML) + `ui.MultiSelect`(categories/tags) + `ui.FileUpload`(featured image) + `ui.Button`("Publish"/"Update") | `RichEditor` — единственный примитив с полноценным WYSIWYG-редактированием, необходим для тела поста WordPress. |
| Page List | `ui.DataTable`(title, status Badge, parent page, date; sortable) | Симметрично Post List, но для статических страниц. |
| Media Library | `ui.DataTable`(image thumb via `ui.Image` в ячейке, filename, type, uploaded date; sortable) + `ui.FileUpload`("Загрузить медиа") | Табличный обзор медиатеки с превью изображений в ячейке. |
| Comments Moderation Queue | `ui.DataTable`(author, excerpt, post, status Badge pending/approved/spam; sortable, selectable=True, bulk_actions=[Approve, Spam, Trash]) | Модерация комментариев массово — bulk_actions напрямую закрывает частый сценарий. |
| Plugin/Theme List | `ui.DataTable`(name, version, active Toggle-колонка editable, update available Badge; sortable) | Активация плагина прямо из таблицы через editable toggle-колонку. |
| SEO Snapshot (
... [16 chars elided from this argument for history replay -- the tool received the FULL value] ...
или Yoast/RankMath) | `ui.KeyValue`(meta title/description/focus keyword) на Post Editor | Компактный блок SEO-полей прямо в редакторе поста. |
| App Settings | `ui.Accordion`([Connections+Disconnect, Default Author, Auto-publish Schedule]) | Централизованные настройки по стандарту. |

## 2. User flow (валидно по panel lifecycle)

1. **SESSION INIT** → `__panel__wp_sidebar` рендерит site URL + разделы,
   `auto_action` открывает Post List.
2. Post List: DataTable → клик на строку → `ui.Call(post_id=...)` → Post
   Editor на том же center handler; "+ New Post" → тот же handler с
   `post_id=None` (пустая форма).
3. Post Editor: `RichEditor` для тела, "Publish"/"Update" → `ui.Call` →
   `save_post` → `refresh_panels` (обратимо — WordPress хранит ревизии,
   без Dialog).
4. Comments Moderation Queue: bulk select → "Spam"/"Trash" через
   `bulk_actions` (обратимо — можно восстановить из корзины, без Dialog).
5. Plugin List: editable toggle "Active" → `on_cell_edit` → `toggle_plugin`
   → `refresh_panels` напрямую (обратимо).
6. "App settings" (нижняя кнопка сайдбара) → отдельный center handler
   `panels_settings.py`; "Disconnect" — единственное деструктивное действие,
   обёрнуто в `Dialog`.

## 3. Экраны/карточки (конкретно)

- **Screen: Post List** — Stats(3) + Select(status) + DataTable(title/author/status/date).
- **Screen: Post Editor** — Input(title) + RichEditor(content) + MultiSelect(taxonomy) + FileUpload(featured image) + KeyValue(SEO).
- **Screen: Page List** — DataTable(title/status/parent/date).
- **Screen: Media Library** — DataTable(thumb/filename/type/date) + FileUpload.
- **Screen: Comments Moderation** — DataTable(author/excerpt/post/status, selectable+bulk_actions).
- **Screen: Plugin/Theme List** — DataTable(name/version/active toggle/update available).
- **Screen: App Settings** — Accordion(Connections, Default Author, Auto-publish).

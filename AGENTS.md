# Особенности bafser для агентов

Краткая памятка по API. Полные контракты — [documentation.md](documentation.md). Сверяй реэкспорты и версию зависимости потребителя.

## Undefined

`Undefined` — сам класс-сентинел отсутствующего поля, не `None` и не `Undefined()`. Не проверяй отсутствие через truthiness.

```python
from bafser import U, UD  # U = Undefined, UD = Undefined.default

value: str | None | U.T = U
if U.defined(value):
    record.value = value  # Также сохраняет явные None, False, 0 и "".
value = UD(value, fallback)  # Подмена только Undefined.
```

- `JsonOpt[str]` разрешает отсутствие JSON-поля; `str | None` требует поле, но разрешает null. `JsonOpt[str | None]` разрешает оба случая. Для необязательного аргумента конструктора явно указывай `= Undefined`.
- `Undefined.cast` сужает тип, не проверяя/преобразуя значение. При частичном обновлении пропуск сохраняет старое значение; явный None может очищать его.
- `JsonObj.new` требует последующего `valid()`/`validate()`; `get_from_req()` проверяет вход. Неизвестные ключи по умолчанию запрещены; простые `get_json_values*` не дают того же строгого контракта. Используй явные публичные DTO.

## Транзакции и авторы

- Для составной операции одна Session, `commit=False` у вложенных CRUD/Log и одна внешняя фиксация. Default True удобен для одиночного вызова. `use_db_sess` сам не коммитит.
- Flush не commit: Log.added может flush-нуть всю Session для ID. Image.new при ошибке может откатить переданную Session даже с commit=False; сохраняй файловые/ambiguous-COMMIT гарантии.
- `for_update=True` получает и обновляет строку; `require_for_update()` только проверяет отметку текущей транзакции. После commit/rollback она недействительна. SQLite-эмуляция не доказывает реальную блокировку.
- Log без actor/с Undefined выбирает текущего пользователя, иначе систему; явный None всегда означает систему с NULL userId. Не подставляй фиктивный User с ID 1 как FK.
- Банк/SMTP выполняются вне блокировок и автоматически повторяемых транзакций. Вне HTTP используй явную Session и нужный app context; не передавай ORM-объекты между потоками.
- UserBase.has_any_role/has_permissions/has_any_permissions — общие проверки; plural permissions сохраняют custom check_permission. set_roles/add_role/remove_role используют одну Session и user-row lock/current membership read; flush возможен даже с commit=False/no-op, блокировка живёт до конца транзакции. Low-level UserRole/raw SQL writers соблюдают тот же протокол.

## Запуск, HTTP и авторизация

- `AUTO_SETUP` управляет подготовкой при старте; production runtime обычно False с отдельным `--setup`. `MULTIPROCESS_LOGGING` независимо включает безопасные общие файлы; THREADED больше не используется.
- `blueprints_package`/`data_tables_package` — имена пакетов, не пути; None явно отключает проектную часть. Модели `_roles`/`_operations`/`_tables` нельзя терять при discovery.
- При настройке встроенной БД/auth нужен конкретный UserBase приложения; None для discovery не создаёт за него таблицу User.
- Быстрые `get_user_id_by_jwt_identity`/`get_userId` не читают БД и не проверяют отзыв. Подпись проверяет JWT-слой. User.current/check_user=True/perms дают строгую проверку; refresh также проверяет актуального пользователя.
- Renewal читает scalar поля без autoflush и ORM-кеша; MySQL current read кратко держит row lock до завершения request transaction. Он не требует второго connection и не коммитит view.
- Обычная strict-проверка читает сохранённый stamp отдельно от ORM-кеша, но сохраняет isolation текущей Session. Для locking current read используй существующий for_update=True; он также refresh-ит ORM row и может затронуть pending edits. Повторный g.user — request cache.
- RequestPolicy задаёт лимит до чтения тела и политику HTTP-данных в логах. Production по умолчанию пишет метаданные HTTP, dev — полные доступные значения. Сообщения и исключения в серверных логах полные по умолчанию, в том числе до конфигурации app; LOG_ERROR_DETAILS=False включает сокращённый production-режим, dev всегда полный. `authenticate=False` только для намеренно публичной ручки, не замена её собственного протокола авторизации.
- `authenticate=True` разрешает необязательный user JWT; вход требует protected_route. При False стандартный current-user resolver не читает user cookie даже через неявного Log actor. Production `body_fields` разрешает только поля корневого объекта; массивы/скаляры целиком скрываются.
- body_fields сравнивает ключи точно (case/Unicode); aliases перечисляй явно. Нормализация sensitive names работает отдельно от сообщений/исключений. При LOG_ERROR_DETAILS=False собственные recovery-сообщения сокращены ещё до host formatter; произвольные сторонние сообщения он фильтрует сам.
- Переиспользуй PublicError для разрешённого клиентского текста; внутренние ошибки и ORM to_dict не становятся публично безопасными автоматически.

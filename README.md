# Portals NFT Auto-Order Manager

Система автоматического управления офферами (заявками) на маркетплейсе Portals.
Состоит из двух частей:

- **Backend** — Python-сервис (FastAPI + SQLAlchemy 2 + SQLite/WAL), который непрерывно
  работает на сервере и управляет офферами через Partners API Portals.
- **Frontend** — веб-панель управления (Next.js + TypeScript + Tailwind).

Закрытие браузера не останавливает автоматизацию: вся работа выполняется на сервере
фоновым воркером, а веб-панель лишь отображает состояние и управляет настройками.

## Возможности

- Управление API-ключами Portals (шифрование токена, проверка, выбор основного).
- Кэш каталога коллекций и моделей, обновление из API.
- Правила автоматизации: стратегии (пол, удержание первого места, фиксированная цена,
  только выбранные модели, безопасная пауза), лимиты цены, бюджета, количества офферов и NFT.
- Расчёт цены по формуле `max_price = floor_price * (1 - discount_percent / 100)` (Decimal).
- Автоматическое удержание первого места с минимальным шагом.
- Единый централизованный диспетчер запросов: 1 запрос/сек на ключ, обработка
  заголовков `X-RateLimit-*` и HTTP 429 `RATE_LIMITED`, блокировка при превышении.
- Очередь операций с ретраями, идемпотентностью (dedupe) и lease-блокировками.
- Явные статусы позиции: `FIRST_CONFIRMED`, `OUTBID`, `LIMIT_REACHED`,
  `INSUFFICIENT_FUNDS`, `DATA_INCOMPLETE`, `STALE_DATA`, `API_ERROR`, `RATE_LIMITED`,
  `ATTRIBUTE_OFFERS_UNAVAILABLE`, `UNKNOWN`. Статус «Первое место» никогда не показывается
  без подтверждения данными.
- Режимы `DRY_RUN` и `LIVE`, глобальная аварийная остановка.
- Аудит действий, история, уведомления (в панели и опционально в Telegram).
- Панель управления: Главная, Коллекции, Правила, Офферы, История, Уведомления, Настройки.

## Быстрый старт (Docker)

1. Скопируйте пример окружения и заполните секреты:

   ```sh
   cp .env.example .env
   ```

   Обязательно задайте:
   - `ADMIN_USERNAME` и `ADMIN_PASSWORD` — первый администратор (создаётся при старте).

   Остальное задавать не нужно: `SECRET_KEY` и `ENCRYPTION_KEY` генерируются
   автоматически при первом запуске и сохраняются в `data/secrets.json`
   (в Docker — в volume `appdata`). База данных — файл SQLite в том же каталоге.

   При запуске по HTTP оставьте `COOKIE_SECURE=false`, иначе браузер не сохранит cookie
   и вход в панель не сработает.

2. Соберите и запустите:

   ```sh
   docker compose up -d --build
   ```

3. Для локального/временного запуска откройте панель: `http://<адрес-сервера>:3000`.
   Для production-запуска с доменом используйте Caddy из `docker-compose.yml`:
   `https://autoorder.monkeysdynasty.website`. Caddy автоматически получит и продлит
   HTTPS-сертификат, если DNS A-запись домена указывает на сервер и порты 80/443 открыты.
   Войдите под созданным администратором.

### Production-деплой на VPS

На сервере Ubuntu установите Docker и Compose plugin, затем выполните:

```sh
git clone <URL-репозитория> autoorder
cd autoorder
cp .env.example .env
nano .env
docker compose up -d --build
docker compose logs -f caddy
```

В `.env` задайте новые значения `ADMIN_USERNAME`, `ADMIN_PASSWORD`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID`, а для HTTPS установите
`COOKIE_SECURE=true` и `TRUST_PROXY_HEADERS=true`. Секреты не добавляйте в git и
не передавайте в чат. Если проект переносится с другого сервера, сохраните volume
`appdata`, иначе база и зашифрованные API-ключи не будут перенесены.

Администратор управляет дополнительными аккаунтами в панели **Пользователи**:
создаёт логин и пароль, указывает Telegram chat ID пользователя, включает
уведомления и при необходимости отключает аккаунт. Telegram chat ID можно получить
через Telegram-бота или из уже используемого Telegram-клиента; сам пользователь
должен сначала открыть чат с ботом и нажать `/start`, иначе Telegram не разрешит
боту отправить личное сообщение.

Миграции применяются автоматически при старте контейнеров `backend` и `worker`
(`alembic upgrade head`).

### Состав сервисов

| Сервис   | Назначение                                              |
|----------|---------------------------------------------------------|
| `backend`| FastAPI: REST API                                       |
| `worker` | Фоновый воркер: правила, очередь операций, запросы в API |
| `frontend`| Next.js панель управления, проксирует `/api/*` на backend |

База данных — файл SQLite (`data/portals.db`) в общем volume `appdata`, доступном
`backend` и `worker`. Режим журнала — WAL, что позволяет читать и писать параллельно.

## Где ввести API-ключ Portals

Ключ **не хранится в `.env`**. Он вводится в веб-панели и сохраняется в базе данных
в зашифрованном виде:

1. Войдите в панель под администратором.
2. Откройте **Настройки** → раздел **API-ключ Portals**.
3. Вставьте токен партнёра Portals в поле «Токен» (Label — произвольное имя, например
   `Основной`, лимит запросов — `1`), нажмите **Добавить**.
4. Нажмите **Проверить** у добавленной записи — статус должен стать `active`,
   а `sender_id` заполнится. Затем **Сделать основным**, если ключей несколько.

Токен передаётся на backend по HTTP(S) только в момент ввода и ответах API больше
не возвращается (в панели показывается только подсказка вида `abcd…wxyz`).
Тот же ключ можно добавить через API: `POST /api/credentials` с телом
`{"token": "<токен>", "label": "Основной", "rate_limit_per_second": 1}`.

## Первый запуск

Автоматизация выключена по умолчанию, режим — `DRY_RUN`. Порядок действий:

1. Настройки → API-ключ Portals: добавьте ключ и нажмите «Проверить».
2. Коллекции → «Обновить каталог».
3. Правила → создайте правило и нажмите «Проверить» (пробный расчёт без реальных действий).
4. Для реальной работы: Настройки → включите автоматизацию и переключите режим в `LIVE`
   (требует явного подтверждения).

## Локальная разработка

### Backend

```sh
python -m venv .venv
.venv\Scripts\python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt   # Windows
```

```sh
cd backend
python -m pytest
alembic upgrade head
uvicorn app.main:app --reload
```

Для локального запуска каталог `data/` создаётся автоматически, миграции
применяются командой `alembic upgrade head`. При необходимости можно указать
другой путь: `DATABASE_URL=sqlite+aiosqlite:///./dev.db`, `AUTO_CREATE_SCHEMA=true`,
`COOKIE_SECURE=false`.

### Frontend

```sh
cd frontend
npm install
npm run dev
```

Next.js проксирует `/api/*` на `BACKEND_URL` (в dev — `http://localhost:8000`,
в Docker — `http://backend:8000`), поэтому cookie и CSRF работают без CORS.
В production-сборке значение `BACKEND_URL` передаётся как build-arg (см. `docker-compose.yml`).

## Безопасность

- Ключ API Portals вводится только в панели, хранится в БД зашифрованным (Fernet).
- Сессия — httpOnly cookie `portals_session` (`SameSite=Lax`); небезопасные методы
  требуют заголовок `X-CSRF-Token`.
- Пароли — scrypt с индивидуальной солью; блокировка входа после 8 неудачных попыток.
- Все данные изолированы по пользователю; чужие объекты возвращают 404.
- Секреты маскируются в ответах API и в журнале аудита.

## Резервное копирование

```sh
sh scripts/backup.sh                       # создаст backups/portals-<дата>.db
sh scripts/restore.sh backups/<файл>.db    # восстановление (сначала остановите backend и worker)
```

## Структура проекта

```
backend/
  app/
    api/          REST-роутеры
    portals/      клиент Partners API и лимитер запросов
    services/     бизнес-логика (движок решений, цены, офферы, очередь, аудит)
    worker/       фоновый планировщик
    models.py     модели SQLAlchemy
    schemas.py    схемы Pydantic
  alembic/        миграции
  tests/          тесты
frontend/
  app/            страницы (App Router)
  components/     UI и layout
  lib/            API-клиент и типы
scripts/          резервное копирование
docker-compose.yml
.env.example
```

## API Portals

Используются реальные эндпоинты Partners API
(`https://docs.portals.tg/ru/developers/api/`), базовый адрес —
`https://portal-market.com/partners`, авторизация `Authorization: partners <token>`.
Офферы по атрибутам возвращают 403, пока функция отключена на стороне маркетплейса:
правило переводится в паузу со статусом `ATTRIBUTE_OFFERS_UNAVAILABLE`.

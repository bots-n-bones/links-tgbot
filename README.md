# Link Collector

Telegram-бот собирает ссылки из групповых чатов и личных сообщений, обогащает
их через OpenAI (описание, теги, embedding), дедуплицирует и складывает в
общую базу. Веб-дашборд даёт просмотр, фильтры, поиск, RAG-вопросы к базе,
research-отчёты по теме и еженедельные тематические подборки. Полная
спецификация — [`TZ.md`](TZ.md).

## Стек

Python 3.12, aiogram 3, FastAPI + Jinja2 + HTMX, Celery + Redis, PostgreSQL 16
+ pgvector, OpenAI API (LLM/embeddings/web search).

## Локальная разработка

1. Скопируйте `.env.example` в `.env` и заполните `BOT_TOKEN`,
   `OPENAI_API_KEY`, `ALLOWED_USER_IDS` (свой `telegram_id`, узнать через
   `@userinfobot`).
2. `docker compose up -d --build` — поднимет Postgres+pgvector, Redis,
   бота (polling), воркер, Celery Beat и дашборд на `http://localhost:8000`.
3. Применить миграции: `make migrate` (или
   `alembic -c db/alembic.ini upgrade head`).
4. Опционально засеять дашборд синтетическими данными без реального бота:
   `make seed`.
5. Тесты: `make test` (нужен запущенный Postgres, `TEST_DATABASE_URL`
   по умолчанию — `linkcollector_test` на локальном сервере).

### Настройка бота в BotFather

- `/setprivacy` → выбрать бота → **Disable** — иначе бот не увидит обычные
  сообщения в группах (только реплаи/упоминания).
- Добавить бота в целевые групповые чаты вручную (до 10 по ТЗ).
- Если токен когда-либо публиковался открытым текстом (чат, скриншот,
  публичный репозиторий) — перевыпустить через `/revoke` в BotFather.

### OpenAI

Нужен один ключ `OPENAI_API_KEY` — используется и для LLM (описания/теги/
отчёты), и для embeddings, и для web search в research-отчётах (единственный
поисковый провайдер, отдельный Tavily/Serper не подключается). Если ключ
когда-либо публиковался открытым текстом — перевыпустить на
platform.openai.com/api-keys.

## Тесты

`pytest` — 100% офлайн, без обращения к реальным Telegram/OpenAI API
(fake-реализации `LLMClient`/`EmbeddingClient`/`SearchClient` за интерфейсом,
включаются автоматически при `ENV=test`). Живые вызовы задействуются только
при ручном запуске с реальными ключами в `.env`.

## Продакшен-деплой

Код готов (webhook-режим бота, nginx + Basic Auth, алерт админу при сбоях),
но требует реальной инфраструктуры, которой пока нет:

1. **VPS** (Ubuntu, ≥2 GB RAM) с публичным IP и SSH-доступом.
2. **Домен**, A-запись указывает на IP VPS.
3. На сервере: склонировать репозиторий, создать `.env` из
   `.env.example` (с реальными ключами, `DASHBOARD_URL=https://ваш-домен`).
4. Создать `nginx/.htpasswd` для Basic Auth дашборда:
   `htpasswd -c nginx/.htpasswd admin` (пакет `apache2-utils`).
5. Первый запуск **без** SSL, чтобы certbot смог провалидировать домен по HTTP:
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
6. Выпустить сертификат (certbot, отдельно — не автоматизировано в
   compose, т.к. требует реального прохождения HTTP-01 challenge):
   ```
   sudo apt install certbot
   sudo certbot certonly --webroot -w /var/www/certbot -d ваш-домен
   ```
7. Раскомментировать `server { listen 443 ssl; ... }` в `nginx/nginx.conf`
   (пути к сертификату `/etc/letsencrypt/live/ваш-домен/`), примонтировать
   `/etc/letsencrypt` в nginx-контейнер, перезапустить nginx.
8. Убедиться, что `RUN_MODE=webhook` подхватился у бота (задаётся автоматически
   через `docker-compose.prod.yml`) — Telegram примет webhook только на
   HTTPS с валидным сертификатом.
9. Проверить: `/health` отвечает `{"status": "ok"}`, `/telegram/webhook`
   отвечает Telegram (не должен требовать Basic Auth), дашборд на `/`
   спрашивает Basic Auth.
10. Пройти чек-лист приёмки — TZ.md §16.

### Что уже сделано в коде для деплоя

- `bot/main.py` — `RUN_MODE=webhook` регистрирует webhook у Telegram и
  поднимает aiohttp-сервер на `:8080` (только внутри Docker-сети, наружу не
  публикуется — только через nginx).
- `nginx/nginx.conf` — `/telegram/webhook` и `/health` без Basic Auth
  (webhook должен быть открыт для серверов Telegram), `/` и `/api` — с
  Basic Auth.
- `docker-compose.prod.yml` — overlay поверх `docker-compose.yml`,
  переключает бота на webhook, добавляет nginx. Не используется в dev
  (`docker-compose.override.yml` — отдельный dev-overlay с polling).
- NF-04: при 10+ ошибках подряд в обработке ссылок воркер шлёт алерт
  `ADMIN_USER_ID` в Telegram (см. `worker/tasks.py::_record_outcome`).
- NF-12: `shared/redact.py` маскирует токено-подобные query-параметры
  (`token`, `api_key`, `secret` и т.п.) в текстах ошибок fetch перед
  сохранением/логированием.

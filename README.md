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

### Личный кабинет (Telegram Login Widget)

Дашборд использует Telegram Login Widget для входа под своим аккаунтом —
каждый пользователь видит только данные workspace, к которому принадлежит
(см. `TZ.md` / план "Личный кабинет + workspace").

- `SESSION_SECRET_KEY` — сгенерировать один раз и не менять (иначе все
  сессии инвалидируются): `python -c "import secrets; print(secrets.token_hex(32))"`.
- `BOT_USERNAME` — username бота без `@` (нужен виджету, чтобы знать, куда
  вести пользователя логиниться).
- В BotFather: `/setdomain` → выбрать бота → указать домен дашборда
  (`ваш-домен`, без `https://`) — без этого шага виджет не отрендерится
  (страница `/login` покажет заглушку "BOT_USERNAME is not configured" или
  просто не даст войти). Обязательно на **проде** — на localhost виджет
  Telegram не работает в принципе (нужен настоящий домен).
- Basic Auth в nginx (`.htpasswd`) и сессионный логин — независимые слои:
  Basic Auth остаётся грубым внешним фильтром (защита от случайных
  сканеров), сессия отвечает за то, чьи данные показывать внутри
  приложения. Не конфликтуют, снимать Basic Auth не обязательно.
- Бутстрап: первый `ADMIN_USER_ID` автоматически становится owner'ом
  дефолтного workspace при накатке миграции `c1d2e3f4a5b6` — с него можно
  выдавать инвайты (`/invite` в боте или кнопка в `/account`) новым
  участникам без правки `.env`.

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

### Вариант A — выделенный VPS (свой nginx-контейнер)

Если сервер целиком под этот проект и порты 80/443 свободны:

1. **VPS** (Ubuntu, ≥2 GB RAM) с публичным IP и SSH-доступом, **домен**
   (A-запись → IP VPS).
2. На сервере: `git clone`, создать `.env` из `.env.example` (реальные
   ключи, `DASHBOARD_URL=https://ваш-домен`).
3. `htpasswd -c nginx/.htpasswd admin` (пакет `apache2-utils`).
4. Поднять с overlay'ем nginx-контейнера (публикует 80/443, монтирует
   `nginx/nginx.conf` + `.htpasswd`):
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.nginx.yml up -d --build`.
5. Выпустить сертификат: `certbot certonly --webroot -w /var/www/certbot -d ваш-домен`,
   раскомментировать `server { listen 443 ssl; ... }` в `nginx/nginx.conf`,
   перезапустить nginx-контейнер.

### Вариант B — общий сервер с уже занятым системным nginx (наш случай)

Когда на сервере уже есть другие проекты и порты 80/443/5432/6379 заняты —
свой nginx-контейнер не поднимаем, используем **системный** nginx с отдельным
конфигом на конкретный домен, а `api`/`bot` публикуются только на `127.0.0.1`
на свободных портах.

1. Убедиться, что домен резолвится на IP сервера (`dig +short домен`), и что
   выбранные порты (по умолчанию `8010` для api, `8080` для webhook бота)
   свободны на сервере — при конфликте поменять их в
   `docker-compose.prod.yml` и в `nginx/bnblinks.conf`.
2. Склонировать репозиторий, создать `.env` (см. `.env.example`,
   `DASHBOARD_URL=https://ваш-домен`).
3. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
   — поднимет `db`/`redis`/`worker`/`beat`/`api`/`bot`, **без** отдельного
   nginx-сервиса (закомментирован/отсутствует в этом overlay).
4. `htpasswd -c /etc/nginx/.htpasswd-bnblinks admin`.
5. Скопировать `nginx/bnblinks.conf` в `/etc/nginx/sites-available/`,
   поправить домен/порты под себя, включить:
   `ln -s /etc/nginx/sites-available/bnblinks.conf /etc/nginx/sites-enabled/`.
6. Выпустить сертификат (не трогая существующие сайты):
   `certbot certonly --nginx -d ваш-домен`.
7. `nginx -t && systemctl reload nginx`.
8. Применить миграции внутри контейнера:
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api alembic -c db/alembic.ini upgrade head`.
9. Проверить: `curl https://ваш-домен/health` → `{"status":"ok"}`,
   `/telegram/webhook` доступен без Basic Auth, `/` спрашивает пароль.
10. Личный кабинет: `/setdomain` в BotFather на этот домен (см. раздел
    "Личный кабинет" выше), зайти на `/login`, проверить, что виджет
    рендерится и логин работает — после волны 4 плана "Личный кабинет +
    workspace" весь дашборд требует логина.
11. Пройти чек-лист приёмки — TZ.md §16.

### Что уже сделано в коде для деплоя

- `bot/main.py` — `RUN_MODE=webhook` регистрирует webhook у Telegram и
  поднимает aiohttp-сервер на `:8080` внутри контейнера.
- `docker-compose.yml` — `api`/`bot` не публикуют порты наружу по умолчанию
  (чтобы не конфликтовать с другими проектами на общем сервере) — порты
  добавляются overlay'ем: `docker-compose.override.yml` (dev, `0.0.0.0:8000`)
  или `docker-compose.prod.yml` (прод, только `127.0.0.1`).
- `nginx/nginx.conf` — шаблон для варианта A (выделенный сервер, свой
  nginx-контейнер). `nginx/bnblinks.conf` — конкретный конфиг для варианта B
  (наш реальный сервер, системный nginx, `server_name bnblinks.duckdns.org`).
- NF-04: при 10+ ошибках подряд в обработке ссылок воркер шлёт алерт
  `ADMIN_USER_ID` в Telegram (см. `worker/tasks.py::_record_outcome`).
- NF-12: `shared/redact.py` маскирует токено-подобные query-параметры
  (`token`, `api_key`, `secret` и т.п.) в текстах ошибок fetch перед
  сохранением/логированием.

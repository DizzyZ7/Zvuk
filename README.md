# Zvuk — Telegram media bot

Асинхронный Telegram-бот на Python 3.11+, aiogram 3, yt-dlp, FFmpeg, PostgreSQL, Redis Streams. Поддерживает поиск музыки по названию и исполнителю, публичные ссылки YouTube, VK, Rutube, TikTok, Instagram, Pinterest, Яндекс.Музыки, а также ссылки на отдельные треки Spotify и Deezer через поиск по метаданным.

## Возможности

- Поиск песни текстом через yt-dlp/YouTube: показывает до пяти результатов с кнопками выбора MP3.
- Ускоренные и замедленные аудиоверсии (1.25× и 0.80×): FFmpeg atempo, отдельный файл и ключ кэша.\n- Кнопки MP3, MP4, 1.25×, 0.80× для видеоплощадок и три аудиоформата для музыкальных ссылок.
- Redis + PostgreSQL кэш Telegram `file_id` по нормализованной ссылке и типу файла.
- Отдельный воркер: скачивание не блокирует получение обновлений Telegram.
- Ограничение трех незавершенных загрузок на пользователя, защита от повторных нажатий на кнопки.
- Redis Streams с consumer groups, ACK и восстановлением зависших задач (порог 3 минуты при доступном heartbeat).
- Обязательная подписка на спонсорские каналы; бот должен быть их администратором.
- Рекламный текст в caption, который администратор меняет без перезапуска.
- Встроенная /admin: статистика с размером очередей, каналы, подпись, подтверждаемая рассылка с прогресс-баром и остановкой, кнопка проверки состояния сервисов.\n- Команда /health в личном чате доступна администраторам и проверяет Telegram Bot API, PostgreSQL, Redis и heartbeat воркера.
- Rate limiting 1 скачивание/3 секунды на пользователя (Redis).
- Временные директории удаляются после отправки, включая исключения; старые каталоги после аварий очищаются при запуске воркера (через 24 ч).
- Local Bot API в режиме `--local`: отправка файлов до **2000 МБ** (не 2 GiB).
- Proxy rotation между заданиями; cookies.txt опционально только для администраторов.

## Структура

```text
app/
  bot/
    admin.py             FSM-админка и рассылка
    handlers.py          /start, ссылки, форматы, file_id-кэш
    keyboards.py         inline-клавиатуры
    middlewares.py       throttle, обязательная подписка
  core/
    config.py            pydantic-settings
    database.py          async SQLAlchemy
    redis.py             Redis client
    telegram.py          Local Bot API session
  models/entities.py     User, MediaCache, DownloadHistory, AdPost, SponsorChannel, Broadcast
  services/
    urls.py              allowlist и канонизация URL
    spotify_resolver.py  Spotify Web API: track + artists\n    deezer_resolver.py   Deezer metadata API: track + artist\n    music_search.py      Поиск названия/исполнителя в YouTube\n    health.py            Проверка инфраструктуры
    media_downloader.py  yt-dlp, FFmpeg, proxy, cookies
    repository.py        DB/Redis operations
    ad_manager.py
    user_service.py
    queue.py             Redis Streams, heartbeats, ACK+XDEL
    housekeeping.py      cleanup of orphaned temporary directories
  main.py                long polling
  worker.py              загрузки и рассылка
alembic/
  env.py
  versions/0001_initial.py
tests/
Dockerfile
docker-compose.yml
pyproject.toml
.env.example
```

## Быстрый запуск

1. Скопируйте `.env.example` в `.env`. Настройте `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `ADMIN_IDS` и обязательно задайте одинаковый пароль в `POSTGRES_PASSWORD` и `DATABASE_URL`.
2. `TELEGRAM_API_ID`/`TELEGRAM_API_HASH` — ключи приложения с [my.telegram.org](https://my.telegram.org); это **не** токен бота. Если токен ранее работал с публичным Bot API, перед переносом на Local Bot API нужно выполнить официальный метод `logOut` публичного API и затем запускать локальный сервер.
3. Для Spotify: зарегистрируйте приложение в [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) и задайте `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`. Без них ссылки Spotify возвращают явную ошибку настройки, остальные сервисы доступны.
4. Запустите `docker compose up --build -d`. Миграции выполняются сервисом `migrate` до старта бота и воркера.
5. Просмотр логов: `docker compose logs -f bot worker`. Напишите боту `/start`, отправьте ссылку или просто название песни и выберите результат. В личном чате отправьте `/admin` или `/health` с ID из `ADMIN_IDS`.

Контейнер `media-init` выставляет права на общий том для непривилегированного воркера. Временные файлы доступны локальному Bot API на чтение до завершения отправки.

Локальный Bot API не опубликован на хосте и доступен только внутри Docker. Том `media_tmp` общедоступен воркеру и локальному Bot API по пути `/shared`, что необходимо для локальной отправки файлов.

## Настройки

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Токен Telegram от BotFather |
| `ADMIN_IDS` | Telegram ID администраторов через запятую |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Учетные данные Telegram API для Local Bot API |
| `DATABASE_URL` | Async SQLAlchemy `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis URL |
| `BOT_API_URL` | По умолчанию `http://telegram-bot-api:8081` |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | Spotify Web API Client Credentials |
| `PROXIES` | HTTP/SOCKS5 прокси через запятую, round-robin |
| `YTDLP_COOKIES` | Путь к приватному cookies.txt; используется только для администраторов |
| `MAX_FILE_MB` | Максимальный размер файла (по умолчанию 1990 МБ) |
| `MAX_DURATION_SEC` | Максимальная продолжительность (по умолчанию 1800 с) |
| `WORKER_CONCURRENCY` | Количество параллельных воркеров скачивания |
| `MAX_PENDING_PER_USER` | Максимум незавершенных загрузок одного пользователя (по умолчанию 3) |

Для cookies можно включить bind mount в `docker-compose.yml`. Не храните cookies, прокси с паролями или `.env` в git.

## Как работает скачивание

1. Handler принимает ссылку (строгий allowlist доменов), предлагает MP3/MP4 и выбор темпа (в музыкальных сервисах — только аудио).
2. Middleware проверяет обязательную подписку, затем handler смотрит Redis и таблицу `media_cache`.
3. При промахе создает `download_history` и отправляет ID задания в Redis Stream.
4. Worker берет задачу, ставит распределенную блокировку по cache key, скачивает через `asyncio.to_thread(yt-dlp)`, конвертирует FFmpeg при необходимости и отправляет файл.
5. Worker сохраняет Telegram `file_id` и освобождает блокировку; временные файлы исчезают по выходу из `TemporaryDirectory`. Другие запросы того же медиа получают `file_id` из кэша.

Рекламная подпись подставляется при **каждой** отправке, в том числе при попадании в кэш.

## ОП и админка

В `/admin` выберите «Спонсорские каналы»: можно добавить публичный канал по `@username`, либо приватный по строке `-100xxxxxxxxxx | https://t.me/+invite`. Бот обязан быть администратором канала для корректной проверки участников. В «Рекламная подпись» установите до 1024 символов или `-` для отключения. В «Рассылка» отправьте текст или медиа и подтвердите запуск отдельной кнопкой. После старта есть кнопка «Остановить рассылку». Бот копирует сообщение пользователям, сохраняет курсор после каждого получателя и обновляет визуальный прогресс каждые 25 получателей. Отмена не удаляет уже доставленные сообщения. `/cancel` отменяет ввод админского действия.

## Проверка

```sh
python -m pip install -e ".[dev]"
python -m compileall -q app tests alembic
ruff check app tests
pytest -q
```

## Эксплуатационные ограничения

- Поиск по тексту выполняется по открытым метаданным YouTube. Это не поиск по словам из текста песни и не музыкальное распознавание (Shazam).\n- Возможность скачивания зависит от сайта, авторизации, доступности контента и изменений его защиты. Прокси не гарантируют доступность.
- Spotify и Deezer используются **только для метаданных**. Затем `ytsearch1:` пытается найти похожую независимую запись на YouTube; результат может отличаться от исходного трека. Spotify DRM/потоки не извлекаются.
- Файлы сверх 2000 МБ не отправляются. Установлен запас 1990 МБ. Для крупных файлов требуется запас временного диска и времени на транскодирование.
- Redis Streams обеспечивают доставку *at-least-once*. При падении сразу после отправки, но до записи статуса, возможна повторная отправка. Для строгой семантики exactly-once нужна дополнительная бизнес-процедура.
- Redis Stream использует consumer group: heartbeat обновляет PEL каждые 45 секунд, потерянные задания повторно забираются через 3 минуты. Подтвержденные события ACK + XDEL удаляются из stream. Обработка имеет семантику at-least-once.
- Временные ошибки Redis, БД и Telegram повторяются до 3 раз; после исчерпания попыток задача завершится с ошибкой. Автоматическое восстановление после падения процесса может повторно доставить последний файл.
- Ограничение MAX_PENDING_PER_USER проверяется транзакционным запросом к PostgreSQL, но не является глобальным атомарным лимитом при одновременной обработке запросов на нескольких экземплярах бота. Для горизонтального масштабирования нужен дополнительный распределенный admission-control.
- Cookies администратора не применяются к обычным пользователям; их кэш изолирован ID пользователя. По умолчанию запросы работают без cookies.
- Проверять E2E нужно на реальном Bot API и тестовых URL: CI выполняет unit-тесты и Docker Compose config, но не проверяет доступность сторонних площадок. См. [операционный чек-лист](docs/OPERATIONS.md).
- Используйте бот только с материалами, на которые у вас есть права, соблюдая правила площадок и применимое законодательство.

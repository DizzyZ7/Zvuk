# Zvuk: локальный запуск на Windows 10/11 с VPN

Проверка локально **рекомендуется перед арендой хостинга**. Требуются Docker Desktop
с Linux containers (WSL 2), Git, свободное место на диске и память для нескольких сервисов.

## 1. VPN и Docker Desktop

1. Включите VPN на компьютере в режиме полного туннеля / системного VPN,
   а не только расширение браузера. При необходимости запустите Docker Desktop уже после VPN.
2. Сравните IP на Windows и в отдельном тестовом контейнере:

```powershell
Invoke-RestMethod https://api.ipify.org
docker run --rm curlimages/curl:8.15.0 -fsS --max-time 15 https://api.ipify.org
```

Если IP разные, нельзя считать, что Docker идет через этот VPN. Проверьте
split tunneling, сетевые правила VPN, DNS и маршрутизацию WSL 2.
В случае проблем приложение можно направить через настроенный сетевой прокси
или использовать другой VPN с полным туннелем. `PROXIES` в Zvuk
передается только yt-dlp и **не** перенаправляет автоматически весь трафик
Telegram Bot API, Spotify, AudD и PostgreSQL.

**Не публикуйте токен бота, API Hash и .env.** VPN не отменяет правил
медиаплощадок и не гарантирует доступность их источников.

## 2. Клонируйте проект и заполните .env

```powershell
git clone https://github.com/DizzyZ7/Zvuk.git
cd Zvuk
Copy-Item .env.example .env
notepad .env
```

Минимально заполнить `BOT_TOKEN`, `TELEGRAM_API_ID`,
`TELEGRAM_API_HASH`, `ADMIN_IDS`, `POSTGRES_PASSWORD`, `DATABASE_URL`
(пароль в URL такой же, как у PostgreSQL). `TELEGRAM_API_ID` и
`TELEGRAM_API_HASH` получают на my.telegram.org для Local Bot API,
токен — через BotFather.

На первом тесте рекомендуемые настройки:

```dotenv
PREMIUM_ENABLED=false
WORKER_CONCURRENCY=1
MAX_PENDING_PER_USER=2
MAX_FILE_MB=150
MAX_DURATION_SEC=600
AUDD_API_TOKEN=
```

Эти настройки ограничивают время и расход места на тестовые файлы;
распознавание не заработает, пока не задан действующий ключ AudD.

## 3. Перенос токена с публичного Telegram API

Если **этот токен уже использовался** с публичным `api.telegram.org`,
перед стартом собственного Local Bot API необходимо вызвать метод
`logOut` публичного Bot API. Введите токен через запрос, не добавляя его
буквально в сохраняемый скрипт:

```powershell
$token = Read-Host 'BOT_TOKEN (не публикуйте)'
Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/logOut"
Remove-Variable token
```

После успешного вызова можно сразу работать через Local Bot API,
но Telegram запрещает повторный вход на облачный API на 10 минут.
**Не выполняйте logOut многократно и не запускайте разные poller-ы
с одним токеном одновременно**.

## 4. Первый старт

```powershell
docker compose config -q
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 bot worker telegram-bot-api migrate
docker compose run --rm --no-deps bot python -m app.tools.preflight
```

Preflight проверяет локальные TCP-порты, доступность некоторых HTTPS
доменов, наличие FFmpeg/Node и определяет внешний IP контейнера. Он не
печатает секреты. Для вызова уже должна быть поднята сеть Docker Compose.
Проверяйте ошибки по логам, а не только по статусу `running`.

Если невозможно подключиться к Telegram, сначала сравните IP контейнера и
хоста при VPN, DNS и логи Local Bot API. Установка `PROXIES` для yt-dlp
сама по себе не исправляет соединение локального Bot API с Telegram.

## 5. Живой функциональный smoke test

1. Отправьте `/start`, `/menu` и `/health` с ID в `ADMIN_IDS`.
2. Найдите публичный тестовый ролик, на который у вас есть права, и запросите MP3,
   затем тот же URL повторно для проверки Telegram file_id-кэша.
3. Проверьте MP4, 1.25× и 0.80× с коротким аудио.
4. Создайте `/playlist new Тест`, добавьте ссылку через `/playlist add ID URL | Тест`
   и откройте `/playlists`.
5. Проверьте `/fragment фраза песни`: результаты приблизительные, не
   гарантируется точное совпадение текста.
6. Проверьте `/library` и кнопку добавления в избранное.
7. `/economics` с администраторского аккаунта показывает только введенные вручную
   доходы/расходы в рублях; Stars учитываются отдельно.
8. AudD и платежи Stars оставьте выключенными, пока не завершен базовый тест.
   Включайте их поэтапно с реальными ключами и контролем затрат.

**Ни автоматические CI-тесты, ни preflight не подтверждают успешную
отправку файла пользователю.** Для этого нужен именно живой тест с ботом.

## 6. Остановка

```powershell
docker compose down
```

Не запускайте `docker compose down -v` без резервной копии —
он удалит тома PostgreSQL, Redis и Bot API.


## Проверка мультизагрузки после обновления

1. Отправьте имя исполнителя `lil peep`. Теперь результаты сохраняются 30 минут:
   скачайте сначала первый, затем второй и третий трек без нового запроса.
2. Проверьте стрелки перелистывания (до 10 результатов) и `💾` под каждой песней.
3. Нажмите `📥 Скачать следующие 3`. Поскольку в вашей конфигурации
   `MAX_PENDING_PER_USER=3`, очередь возьмет не больше трех незавершенных задач.
   Дождитесь файлов и повторите кнопку, если нужны следующие песни.
4. Создайте `/playlist new Любимые`, нажмите `➕` у найденного трека,
   выберите плейлист. Убедитесь, что песня появилась в `/playlists`.
5. Повторите скачивание уже выбранного трека кнопкой `🔁`. Если он есть в кэше,
   бот может вернуть его без нового скачивания.
6. Сверьте, что при недоступности YouTube бот пишет конкретную причину,
   а не обещает, что публичное видео обязательно приватное.

После обновления на уже запущенном Windows:

```powershell
cd C:\Users\DizZy\Zvuk
git pull --ff-only
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 bot worker
```

`.env` и тома PostgreSQL не теряются при штатном `git pull` /
`docker compose up --build -d`. Не вызывайте `docker compose down -v`.

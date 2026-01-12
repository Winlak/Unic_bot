# Unic Video Bot

Telegram-бот на aiogram 3, который локально уникализирует вертикальные видео по заданному пайплайну и автоматически добавляет рекламный баннер.

## Требования
- Python 3.10+
- Установленный FFmpeg CLI (должен быть доступен как `ffmpeg`)
- (опционально) FFprobe — если его нет, используется fallback через `ffmpeg -i`

## Настройка
1. Создай виртуальное окружение и установи зависимости:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -U pip wheel
   pip install -r requirements.txt
   ```
2. Сконфигурируй переменные окружения. Можно скопировать `.env.example`:
   ```bash
   cp .env.example .env
   ```
   Минимум нужно заполнить:
   - `BOT_TOKEN`
   - `OWNER_TELEGRAM_ID`

### Баннер
По умолчанию бот автоматически ищет баннер рядом с кодом (в корне проекта):
- `banner.mp4`, `banner.mov`, `banner.png`, `banner.webp`
- `overlay.mp4`, `ad.mp4`, `promo.mp4`

Можно указать путь явно через переменную окружения:
```
UNIC_BANNER_PATH=/absolute/path/to/banner.mp4
```

Параметры баннера:
- `UNIC_BANNER_ENABLED=true|false`
- `UNIC_BANNER_POSITION=auto|top|bottom`
- `UNIC_BANNER_STRIP_MODE=auto|overlay|strip`
- `UNIC_BANNER_STRIP_RATIO=0.20`
- `UNIC_BANNER_WIDTH_RATIO=0.86`
- `UNIC_BANNER_MARGIN_RATIO=0.03`
- `UNIC_CHROMAKEY_ENABLED=true|false`
- `UNIC_CHROMAKEY_SIMILARITY=0.18`
- `UNIC_CHROMAKEY_BLEND=0.02`
- `UNIC_CHROMAKEY_COLOR=0x2ca0fc` (если пусто — определяется автоматически по углам)
- `UNIC_FAIL_ON_MISSING_BANNER=false` (если true — ошибка при отсутствии баннера)

#### Banner safe-fit (no clipping)
Баннер всегда вписывается в доступную зону по максимальным `max_w/max_h` и координаты overlay «clamped», чтобы исключить обрезание по краям кадра даже при больших размерах и нестандартных пропорциях. Влияют параметры `UNIC_BANNER_WIDTH_RATIO`, `UNIC_BANNER_MARGIN_RATIO`, `UNIC_BANNER_STRIP_RATIO`.

## Запуск
```bash
python bot.py
```
Бот работает в режиме polling и хранит временные файлы в `tmp/` (очищаются после обработки).

## CLI режим (локальная проверка)
```bash
python cli.py --input /path/in.mp4 --outdir ./out --variants 3 --seed 123
```
CLI использует тот же пайплайн, что и бот, включая баннер.

## Smoke test
```bash
python tests/smoke_test.py
```
Тест создаёт синтетические видео и проверяет, что баннер ставится сверху/снизу противоположно тексту.

## Docker
1. Создай `.env` (см. `.env.example`).
2. Собери образ:
   ```bash
   docker build -t unicbot .
   ```
3. Запусти контейнер:
   ```bash
   docker run --rm --name unicbot \
     --env-file .env \
     -v $(pwd)/tmp:/app/tmp \
     unicbot
   ```
4. Или используй docker compose:
   ```bash
   docker compose up --build
   ```

## Поведение
1. `/start` выводит короткую инструкцию.
2. Бот принимает либо видеофайл (телеграм-видео или документ `mime_type=video`), либо ссылку на YouTube Shorts/ролик. Любой другой контент отклоняется.
3. После загрузки или скачивания файла бот предлагает выбрать 1–5 вариантов и нажать «Старт».
4. Для каждого варианта генерируются независимые параметры:
   - Zoom + crop + возврат к исходному разрешению (без изменения пропорций)
   - Яркость и насыщенность в допустимых диапазонах
   - Слой шума/зерна
   - Pitch shift аудио ±1.5% с компенсацией темпа
   - Очистка метаданных
   - Добавление баннера сверху/снизу (auto с эвристикой по тексту)
5. Все результаты отправляются в чат вместе с отчётом по параметрам. После успешной отправки исходный и выходные файлы удаляются. Для ссылок видео предварительно скачивается через `yt-dlp`.

## Ошибки и ретраи
- Ошибки FFmpeg возвращаются в чат с указанием варианта.
- Отправка в Telegram повторяется до 3 раз (учитывается `RetryAfter`).
- Telegram ограничивает скачивание ботами примерно 20 МБ при работе через официальный облачный API (это ограничение сервиса).

## Дополнительные фичи
1. Audio Pitch Micro-Shift — микросмещение тональности ±1.5% с сохранением длительности.
2. (удалено) Dynamic Vignette — отключено для исключения мерцания.
3. (удалено) Frame Dup Shuffle — отключено, чтобы не менять порядок кадров.

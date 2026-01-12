from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramRetryAfter,
)
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    FSInputFile,
)

import config
from ffmpeg_runner import FFmpegProcessError, build_ffmpeg_command, run_ffmpeg
from media_utils import get_file_size_bytes, transcode_to_size_limit
from video_params import generate_variant_params
from youtube_downloader import (
    YouTubeDownloadError,
    download_youtube_video,
    extract_youtube_url,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _is_owner(user_id: Optional[int]) -> bool:
    return user_id == config.OWNER_TELEGRAM_ID


def _build_variants_keyboard(selected: int) -> InlineKeyboardMarkup:
    buttons = []
    for value in range(config.ALLOWED_VARIANT_RANGE[0], config.ALLOWED_VARIANT_RANGE[1] + 1):
        text = f"{value} {'✓' if value == selected else ''}".strip()
        buttons.append(InlineKeyboardButton(text=text, callback_data=f"variants:{value}"))
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(text="Старт", callback_data="process:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dataclass
class SessionState:
    input_path: Path
    original_name: str
    variants: int = 1
    processing: bool = False


sessions: Dict[int, SessionState] = {}
session_lock = asyncio.Lock()
TELEGRAM_UPLOAD_LIMIT_BYTES = config.TELEGRAM_MAX_UPLOAD_MB * 1024 * 1024


async def try_set_session_state(user_id: int, state: SessionState) -> tuple[bool, Optional[Path]]:
    async with session_lock:
        existing = sessions.get(user_id)
        if existing and existing.processing:
            return False, None
        cleanup_old = existing.input_path if existing else None
        sessions[user_id] = state
        return True, cleanup_old


async def ensure_owner_message(message: Message) -> bool:
    if _is_owner(message.from_user and message.from_user.id):
        return True
    await message.answer("Access denied")
    return False


async def ensure_owner_callback(callback: CallbackQuery) -> bool:
    if _is_owner(callback.from_user and callback.from_user.id):
        return True
    await callback.answer("Access denied", show_alert=True)
    return False


def _validate_video_message(message: Message) -> Optional[str]:
    file = message.video or message.document
    if file is None:
        return "Отправь только видеофайл"
    if message.document and (not message.document.mime_type or not message.document.mime_type.startswith(config.ALLOWED_VIDEO_MIME_PREFIX)):
        return "Отправь только видеофайл"
    return None


def _format_size_mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} МБ"


async def _compress_for_telegram(source: Path) -> Path:
    target = config.TMP_DIR / f"tg_{uuid.uuid4().hex}.mp4"
    limit = TELEGRAM_UPLOAD_LIMIT_BYTES
    await asyncio.to_thread(transcode_to_size_limit, source, target, limit)
    return target


async def download_video_file(message: Message) -> Path:
    file = message.video or message.document
    assert file is not None
    extension = Path(file.file_name or "input.mp4").suffix or ".mp4"
    input_path = config.TMP_DIR / f"input_{uuid.uuid4().hex}{extension}"
    file_info = await message.bot.get_file(file.file_id)
    await message.bot.download_file(
        file_info.file_path,
        destination=input_path,
        timeout=config.TELEGRAM_DOWNLOAD_TIMEOUT,
    )
    return input_path


async def cleanup_path(path: Path) -> None:
    if path.exists():
        try:
            path.unlink()
        except OSError:
            logger.warning("Failed to delete %s", path)


async def cmd_start(message: Message) -> None:
    if not await ensure_owner_message(message):
        return
    text = (
        "Привет! Скинь ссылку на YouTube Shorts или отправь вертикальное видео (9:16).\n"
        "После загрузки выбери количество вариантов (1–5) и нажми Старт."
    )
    await message.answer(text)


async def _finalize_session(message: Message, state: SessionState, accepted_text: str) -> None:
    success, cleanup_old = await try_set_session_state(message.from_user.id, state)
    if not success:
        await cleanup_path(state.input_path)
        await message.answer("Дождись окончания текущей обработки.")
        return
    if cleanup_old:
        await cleanup_path(cleanup_old)
    await message.answer(
        accepted_text,
        reply_markup=_build_variants_keyboard(state.variants),
    )


async def handle_video(message: Message) -> None:
    if not await ensure_owner_message(message):
        return
    error = _validate_video_message(message)
    if error:
        await message.answer(error)
        return
    try:
        input_path = await download_video_file(message)
    except TelegramBadRequest as exc:
        await message.answer("Не удалось скачать файл: Telegram ограничивает загрузку ботами до ~20 МБ.")
        logger.warning("Download failed for user %s: %s", message.from_user.id, exc)
        return
    state = SessionState(
        input_path=input_path,
        original_name=(message.video and message.video.file_name) or (message.document and message.document.file_name) or input_path.name,
    )
    await _finalize_session(
        message,
        state,
        "Файл получен. Выбери количество вариантов и запусти обработку.",
    )


async def update_variants(callback: CallbackQuery, value: int) -> None:
    if not await ensure_owner_callback(callback):
        return
    async with session_lock:
        state = sessions.get(callback.from_user.id)
        if not state or state.processing:
            await callback.answer("Нет загруженного видео", show_alert=True)
            return
        state.variants = value
        keyboard = _build_variants_keyboard(value)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer(f"Будет создано {value} вариант(ов)")


async def handle_youtube_link(message: Message) -> None:
    if not await ensure_owner_message(message):
        return
    url = extract_youtube_url(message.text or "")
    if not url:
        await message.answer("Не могу распознать ссылку на YouTube. Пришли полный URL.")
        return
    await message.answer("Скачиваю видео с YouTube…")
    try:
        result = await download_youtube_video(url, config.TMP_DIR)
    except YouTubeDownloadError as exc:
        await message.answer(f"Не удалось скачать видео: {exc}")
        return
    state = SessionState(input_path=result.file_path, original_name=result.title)
    await _finalize_session(
        message,
        state,
        "Видео скачано. Выбери количество вариантов и запусти обработку.",
    )


async def start_processing(callback: CallbackQuery) -> None:
    if not await ensure_owner_callback(callback):
        return
    async with session_lock:
        state = sessions.get(callback.from_user.id)
        if not state:
            await callback.answer("Сначала отправь видео", show_alert=True)
            return
        if state.processing:
            await callback.answer("Уже обрабатываю", show_alert=True)
            return
        state.processing = True
    await callback.answer("Запуск")
    await callback.message.answer("Начинаю обработку…")
    asyncio.create_task(process_video(callback.message.bot, callback.from_user.id, callback.message.chat.id))


async def process_video(bot: Bot, user_id: int, chat_id: int) -> None:
    async with session_lock:
        state = sessions.get(user_id)
        if not state:
            return
        input_path = state.input_path
        variants = state.variants
    try:
        for index in range(1, variants + 1):
            seed = random.randint(1, 10_000_000)
            params = generate_variant_params(seed)
            output_path = config.TMP_DIR / f"output_{uuid.uuid4().hex}_{index}.mp4"
            command = build_ffmpeg_command(input_path, output_path, params)
            try:
                await run_ffmpeg(command)
            except FFmpegProcessError as exc:
                await bot.send_message(chat_id, f"Ошибка FFmpeg (вариант {index}): {exc}")
                await cleanup_path(output_path)
                return
            caption = (
                f"Вариант {index}/{variants}\n" f"{params.as_report()}"
            )
            await send_video_with_retry(bot, chat_id, output_path, caption)
            await cleanup_path(output_path)
        await bot.send_message(chat_id, "Готово ✅")
    finally:
        await cleanup_path(input_path)
        async with session_lock:
            sessions.pop(user_id, None)


async def send_video_with_retry(bot: Bot, chat_id: int, file_path: Path, caption: str) -> None:
    compressed_path: Optional[Path] = None
    to_send = file_path
    try:
        if get_file_size_bytes(file_path) > TELEGRAM_UPLOAD_LIMIT_BYTES:
            try:
                compressed_path = await _compress_for_telegram(file_path)
            except RuntimeError as exc:
                await bot.send_message(chat_id, f"Не удалось сжать видео для Telegram: {exc}")
                return
            to_send = compressed_path
            await bot.send_message(
                chat_id,
                f"Сжал видео до {_format_size_mb(get_file_size_bytes(to_send))} для отправки.",
            )

        for attempt in range(1, config.TELEGRAM_RETRY_ATTEMPTS + 1):
            try:
                media = FSInputFile(to_send)
                await bot.send_video(chat_id, media, caption=caption)
                return
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
            except TelegramEntityTooLarge:
                if compressed_path is None:
                    try:
                        compressed_path = await _compress_for_telegram(to_send)
                    except RuntimeError as exc:
                        await bot.send_message(chat_id, f"Файл слишком большой, не удалось сжать: {exc}")
                        return
                    to_send = compressed_path
                    await bot.send_message(
                        chat_id,
                        f"Сжал видео до {_format_size_mb(get_file_size_bytes(to_send))} для отправки.",
                    )
                    continue
                await bot.send_message(
                    chat_id,
                    "Файл слишком большой даже после сжатия. Сократи длительность и попробуй снова.",
                )
                return
            except (TelegramBadRequest, TelegramAPIError):
                if attempt == config.TELEGRAM_RETRY_ATTEMPTS:
                    raise
                await asyncio.sleep(2 * attempt)
        raise RuntimeError("Не удалось отправить видео")
    finally:
        if compressed_path:
            await cleanup_path(compressed_path)


async def main() -> None:
    if not config.BOT_TOKEN or config.OWNER_TELEGRAM_ID == 0:
        raise RuntimeError("Заполни BOT_TOKEN и OWNER_TELEGRAM_ID в config.py")
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(handle_video, F.video | F.document)
    dp.message.register(
        handle_youtube_link,
        F.text.func(lambda text: bool(text and "youtu" in text.lower())),
    )
    dp.message.register(handle_non_video)

    dp.callback_query.register(start_processing, F.data == "process:start")
    for value in range(config.ALLOWED_VARIANT_RANGE[0], config.ALLOWED_VARIANT_RANGE[1] + 1):
        dp.callback_query.register(update_variants_handler(value), F.data == f"variants:{value}")

    await dp.start_polling(bot)


def update_variants_handler(value: int):
    async def handler(callback: CallbackQuery) -> None:
        await update_variants(callback, value)

    return handler


async def handle_non_video(message: Message) -> None:
    if not await ensure_owner_message(message):
        return
    await message.answer("Отправь видеофайл или ссылку на YouTube Shorts")


if __name__ == "__main__":
    asyncio.run(main())

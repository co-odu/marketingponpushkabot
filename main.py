# ─────────────────────────────────────────────
# bot.py — Основа Telegram-бота для сбора заявок
# ─────────────────────────────────────────────

import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ─────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────

# Вставь сюда свой токен от @BotFather
# Лучше хранить в переменных окружения:
# BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_TOKEN = "8878511511:AAEEqOkNBvwFrtTGpg17qBUFn2jlGthZAoE"

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# СТЕЙТЫ (этапы диалога) — пока не используем,
# но заготовим для будущего сбора заявок
# ─────────────────────────────────────────────

(
    NAME,
    PHONE,
    EMAIL,
    MESSAGE,
    CONFIRM,
) = range(5)


# ─────────────────────────────────────────────
# ОБРАБОТЧИКИ КОМАНД
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветствие при команде /start"""
    user = update.effective_user
    welcome_text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Я бот для сбора заявок отдела маркетинга сети пончиковых PON-PUSHKA. Скоро я смогу принимать "
        "и обрабатывать твои обращения.\n\n"
    )
    await update.message.reply_text(welcome_text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда помощи"""
    help_text = (
        "📋 <b>Справка по боту</b>\n\n"
        "Этот бот помогает собирать заявки от пользователей.\n\n"
        "<b>Команды:</b>\n"
        "/start — начать работу с ботом\n"
        "/help — показать эту справку\n"
        "/new_request — создать заявку (в разработке)\n\n"
        "По вопросам обращайтесь к администратору."
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


async def new_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Заглушка для будущей команды создания заявки"""
    await update.message.reply_text(
        "🚧 Функция создания заявки пока в разработке.\n"
        "Скоро всё заработает! Следи за обновлениями."
    )


# ─────────────────────────────────────────────
# ОБРАБОТЧИК СООБЩЕНИЙ
# ─────────────────────────────────────────────

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ответ на любое текстовое сообщение (пока эхо)"""
    await update.message.reply_text(
        "Я пока не понимаю произвольные сообщения 😅\n"
        "Используй команды из меню или напиши /help"
    )


# ─────────────────────────────────────────────
# ОБРАБОТЧИК ОШИБОК
# ─────────────────────────────────────────────

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирование ошибок"""
    logger.error(f"Ошибка: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Произошла ошибка. Попробуй позже или напиши /start"
        )


# ─────────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────

def main() -> None:
    """Запуск бота"""
    # Проверка токена
    if not BOT_TOKEN or BOT_TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН_ОТ_BOTFATHER":
        print("❌ ОШИБКА: Вставь токен бота в переменную BOT_TOKEN!")
        print("   Получи токен у @BotFather в Telegram")
        return

    # Создаём приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("new_request", new_request))

    # Обработчик обычных сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Обработчик ошибок
    application.add_error_handler(error_handler)

    # Запускаем бота
    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

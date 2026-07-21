# bot.py — Бот для сбора заявок на макеты (v2)

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ─────────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ─────────────────────────────────────────────

BOT_TOKEN = "ВСТАВЬ_ТОКЕН_ОТ_BOTFATHER"
ADMIN_ID = 123456789  # Telegram ID руководителя отдела маркетинга (узнать у @userinfobot)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# СТЕЙТЫ ДИАЛОГА
# ─────────────────────────────────────────────

(
    COMPANY_NAME,      # 1. Название юр.лица
    OBJECT_NAME,       # 2. Название объекта, город, адрес
    TECH_TASK,         # 3. Техническое задание (описание макета)
    PRINT_TYPE,        # 4. Печать / Диджитал
    SIZE,              # 5. Размер
    DEADLINE_CONFIRM,  # 6. Подтверждение дедлайна (+10 рабочих дней)
    URGENT_CHOICE,     # 7. Выбор: обычный / ускоренный
) = range(7)

# ─────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────

def get_working_days_later(start_date: datetime, days: int) -> datetime:
    """Считает дату через N рабочих дней (без учёта выходных)"""
    current = start_date
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0-4 = пн-пт
            added += 1
    return current

def format_date_ru(date: datetime) -> str:
    """Форматирует дату по-русски"""
    months = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    return f"{date.day} {months[date.month - 1]} {date.year}"

def generate_request_id() -> str:
    """Генерирует ID заявки"""
    return f"REQ-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

# ─────────────────────────────────────────────
# КОМАНДЫ
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало диалога — приветствие"""
    user = update.effective_user
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я бот для подачи заявок на изготовление макетов.\n"
        "Сейчас я задам тебе несколько вопросов.\n\n"
        "📝 <b>Шаг 1 из 6</b>\n"
        "Введи <b>название юридического лица</b> (организации):",
        parse_mode="HTML"
    )
    return COMPANY_NAME


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена диалога"""
    await update.message.reply_text(
        "❌ Заявка отменена. Чтобы начать заново — /start"
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# ШАГИ ДИАЛОГА
# ─────────────────────────────────────────────

async def get_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем название юр.лица"""
    context.user_data["company"] = update.message.text.strip()
    
    await update.message.reply_text(
        "✅ Принято!\n\n"
        "📝 <b>Шаг 2 из 6</b>\n"
        "Введи <b>название объекта, город и адрес</b>:\n"
        "<i>Например: ТЦ Мега, Москва, ул. Ленина 1</i>",
        parse_mode="HTML"
    )
    return OBJECT_NAME


async def get_object_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем объект, город, адрес"""
    context.user_data["object"] = update.message.text.strip()
    
    # Автоматически ставим дату постановки задачи
    context.user_data["task_date"] = datetime.now()
    
    await update.message.reply_text(
        f"✅ Принято!\n"
        f"📅 Дата постановки задачи: <b>{format_date_ru(datetime.now())}</b>\n\n"
        f"📝 <b>Шаг 3 из 6</b>\n"
        f"Опиши <b>техническое задание</b> — что должно быть на макете:\n"
        f"<i>Например: баннер 3x6м, логотип компании, слоган, фон синий...</i>",
        parse_mode="HTML"
    )
    return TECH_TASK


async def get_tech_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем ТЗ"""
    context.user_data["tech_task"] = update.message.text.strip()
    
    # Кнопки выбора типа
    keyboard = [
        [InlineKeyboardButton("🖨 Печать", callback_data="print")],
        [InlineKeyboardButton("💻 Диджитал", callback_data="digital")],
    ]
    
    await update.message.reply_text(
        "✅ Принято!\n\n"
        "📝 <b>Шаг 4 из 6</b>\n"
        "Выбери <b>тип макета</b>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PRINT_TYPE


async def get_print_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем тип (печать/диджитал)"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["print_type"] = "Печать" if query.data == "print" else "Диджитал"
    
    await query.edit_message_text(
        f"✅ Тип: <b>{context.user_data['print_type']}</b>\n\n"
        f"📝 <b>Шаг 5 из 6</b>\n"
        f"Укажи <b>размер макета</b>:\n"
        f"<i>Например: 3x6 метра, A4, 1920x1080 px...</i>",
        parse_mode="HTML"
    )
    return SIZE


async def get_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем размер"""
    context.user_data["size"] = update.message.text.strip()
    
    # Считаем дедлайн (+10 рабочих дней)
    task_date = context.user_data["task_date"]
    normal_deadline = get_working_days_later(task_date, 10)
    urgent_deadline = get_working_days_later(task_date, 2)
    
    context.user_data["normal_deadline"] = normal_deadline
    context.user_data["urgent_deadline"] = urgent_deadline
    
    # Кнопки подтверждения дедлайна
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_deadline")],
    ]
    
    await update.message.reply_text(
        f"✅ Размер: <b>{context.user_data['size']}</b>\n\n"
        f"📅 <b>Стандартный дедлайн</b> (+10 раб.дней):\n"
        f"<b>{format_date_ru(normal_deadline)}</b>\n\n"
        f"📝 <b>Шаг 6 из 6</b>\n"
        f"Нажми «Подтвердить» для выбора типа выполнения:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return DEADLINE_CONFIRM


async def confirm_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение дедлайна → выбор обычный/ускоренный"""
    query = update.callback_query
    await query.answer()
    
    normal = format_date_ru(context.user_data["normal_deadline"])
    urgent = format_date_ru(context.user_data["urgent_deadline"])
    
    keyboard = [
        [InlineKeyboardButton(f"🐢 Обычный (до {normal})", callback_data="normal")],
        [InlineKeyboardButton(f"🚀 Ускоренный +100₽ (до {urgent})", callback_data="urgent")],
    ]
    
    await query.edit_message_text(
        f"⏰ <b>Выбери тип выполнения:</b>\n\n"
        f"🐢 <b>Обычный</b> — готовность <b>{normal}</b>\n"
        f"🚀 <b>Ускоренный</b> — готовность <b>{urgent}</b> (+100 ₽)\n\n"
        f"Выбери вариант:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return URGENT_CHOICE


async def process_urgent_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора обычный/ускоренный → финализация заявки"""
    query = update.callback_query
    await query.answer()
    
    is_urgent = query.data == "urgent"
    context.user_data["is_urgent"] = is_urgent
    context.user_data["cost"] = 100 if is_urgent else 0
    
    deadline = context.user_data["urgent_deadline"] if is_urgent else context.user_data["normal_deadline"]
    deadline_str = format_date_ru(deadline)
    
    # Генерируем ID заявки
    request_id = generate_request_id()
    context.user_data["request_id"] = request_id
    
    # Формируем итоговое сообщение для заказчика
    summary = (
        f"📋 <b>ЗАЯВКА #{request_id}</b>\n"
        f"{'━' * 30}\n"
        f"🏢 <b>Юр.лицо:</b> {context.user_data['company']}\n"
        f"📍 <b>Объект:</b> {context.user_data['object']}\n"
        f"📅 <b>Дата постановки:</b> {format_date_ru(context.user_data['task_date'])}\n"
        f"📝 <b>ТЗ:</b> {context.user_data['tech_task']}\n"
        f"🖨 <b>Тип:</b> {context.user_data['print_type']}\n"
        f"📐 <b>Размер:</b> {context.user_data['size']}\n"
        f"⏰ <b>Дедлайн:</b> {deadline_str}\n"
        f"🚀 <b>Ускоренный:</b> {'Да (+100 ₽)' if is_urgent else 'Нет'}\n"
        f"{'━' * 30}\n"
        f"✅ Заявка отправлена на рассмотрение!\n"
        f"Ожидай уведомления о статусе."
    )
    
    await query.edit_message_text(summary, parse_mode="HTML")
    
    # ── ОТПРАВЛЯЕМ ЗАЯВКУ АДМИНУ ──
    await send_to_admin(update, context)
    
    return ConversationHandler.END


async def send_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет заявку админу с кнопками управления"""
    bot = context.bot
    data = context.user_data
    
    deadline = data["urgent_deadline"] if data["is_urgent"] else data["normal_deadline"]
    
    admin_text = (
        f"🆕 <b>НОВАЯ ЗАЯВКА #{data['request_id']}</b>\n"
        f"{'━' * 30}\n"
        f"👤 <b>От:</b> {update.effective_user.full_name} "
        f"(@{update.effective_user.username or 'нет username'})\n"
        f"🆔 <b>ID заказчика:</b> <code>{update.effective_user.id}</code>\n\n"
        f"🏢 <b>Юр.лицо:</b> {data['company']}\n"
        f"📍 <b>Объект:</b> {data['object']}\n"
        f"📅 <b>Дата постановки:</b> {format_date_ru(data['task_date'])}\n"
        f"📝 <b>ТЗ:</b> {data['tech_task']}\n"
        f"🖨 <b>Тип:</b> {data['print_type']}\n"
        f"📐 <b>Размер:</b> {data['size']}\n"
        f"⏰ <b>Дедлайн:</b> {format_date_ru(deadline)}\n"
        f"🚀 <b>Ускоренный:</b> {'Да (+100 ₽)' if data['is_urgent'] else 'Нет'}\n"
        f"{'━' * 30}"
    )
    
    # Кнопки для админа
    keyboard = [
        [
            InlineKeyboardButton("✅ Принято в работу", callback_data=f"accept_{data['request_id']}"),
        ],
        [
            InlineKeyboardButton("❌ Отклонено", callback_data=f"reject_{data['request_id']}"),
        ],
    ]
    
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─────────────────────────────────────────────
# ОБРАБОТЧИКИ КНОПОК АДМИНА
# ─────────────────────────────────────────────

async def admin_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ нажал 'Принято в работу'"""
    query = update.callback_query
    await query.answer()
    
    request_id = query.data.replace("accept_", "")
    
    # Меняем кнопки у админа
    keyboard = [
        [InlineKeyboardButton("✅ В работе", callback_data="noop")],
        [
            InlineKeyboardButton("🏁 Выполнено", callback_data=f"complete_{request_id}"),
            InlineKeyboardButton("❌ Отклонено", callback_data=f"reject_{request_id}"),
        ],
    ]
    
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    
    # Уведомляем заказчика (нужно хранить user_id — пока заглушка)
    # TODO: добавить хранение user_id по request_id
    await query.edit_message_text(
        query.message.text + "\n\n✅ <b>Принято в работу</b>",
        parse_mode="HTML"
    )


async def admin_complete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ нажал 'Выполнено' — запрашиваем макет"""
    query = update.callback_query
    await query.answer()
    
    request_id = query.data.replace("complete_", "")
    
    await query.edit_message_text(
        query.message.text + "\n\n🏁 <b>Ожидается загрузка макета...</b>\n"
        "Отправь файл макетом в ответ на это сообщение.",
        parse_mode="HTML"
    )
    
    # TODO: сохранить состояние "ожидаем макет от админа"


async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ нажал 'Отклонено' — запрашиваем причину"""
    query = update.callback_query
    await query.answer()
    
    request_id = query.data.replace("reject_", "")
    
    await query.edit_message_text(
        query.message.text + "\n\n❌ <b>Введи причину отклонения:</b>",
        parse_mode="HTML"
    )
    
    # TODO: сохранить состояние "ожидаем причину отклонения"


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пустая кнопка (уже в работе)"""
    query = update.callback_query
    await query.answer("Уже в работе!")


# ─────────────────────────────────────────────
# ОБРАБОТЧИК ОШИБОК
# ─────────────────────────────────────────────

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Ошибка: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Произошла ошибка. Попробуй /start"
        )


# ─────────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────

def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "ВСТАВЬ_ТОКЕН_ОТ_BOTFATHER":
        print("❌ Вставь токен в BOT_TOKEN!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Диалог сбора заявки
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            COMPANY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_company_name)],
            OBJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_object_name)],
            TECH_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_tech_task)],
            PRINT_TYPE: [CallbackQueryHandler(get_print_type, pattern="^(print|digital)$")],
            SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_size)],
            DEADLINE_CONFIRM: [CallbackQueryHandler(confirm_deadline, pattern="^confirm_deadline$")],
            URGENT_CHOICE: [CallbackQueryHandler(process_urgent_choice, pattern="^(normal|urgent)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # Кнопки админа
    application.add_handler(CallbackQueryHandler(admin_accept, pattern="^accept_"))
    application.add_handler(CallbackQueryHandler(admin_complete, pattern="^complete_"))
    application.add_handler(CallbackQueryHandler(admin_reject, pattern="^reject_"))
    application.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))

    application.add_error_handler(error_handler)

    print("🤖 Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

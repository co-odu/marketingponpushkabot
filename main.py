# bot.py — Бот для сбора заявок на макеты (v3)

import logging
import os
import re
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

import db

# ─────────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ─────────────────────────────────────────────

BOT_TOKEN = "8878511511:AAEEqOkNBvwFrtTGpg17qBUFn2jlGthZAoE"
ADMIN_ID = 6235378997  # Telegram ID руководителя отдела маркетинга (узнать у @userinfobot)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ХРАНЕНИЕ ЗАЯВОК — теперь в SQLite (см. db.py), переживает перезапуск бота
# ─────────────────────────────────────────────

STATUS_LABELS = {
    "pending": "🕐 На рассмотрении",
    "in_progress": "✅ Принято в работу",
    "rejected": "❌ Отклонено",
    "completed": "🏁 Выполнено",
}

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
# КЛАВИАТУРЫ
# ─────────────────────────────────────────────

MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📝 Подать заявку")],
        [KeyboardButton("📋 Мои заявки")],
    ],
    resize_keyboard=True,
)

BACK_TEXT = "◀️ Назад"
BACK_CALLBACK = "nav_back"

# Постоянная клавиатура с кнопкой "Назад" — показывается на всех шагах заявки,
# заменяя собой главное меню, пока идёт заполнение
BACK_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton(BACK_TEXT)]],
    resize_keyboard=True,
)

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
    """Начало диалога — приветствие + меню"""
    user = update.effective_user

    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я бот для подачи заявок на изготовление макетов.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

    return await start_new_request(update, context)


async def start_new_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запускает диалог сбора новой заявки (вызывается из /start и из кнопки меню)"""
    context.user_data.clear()  # чистим данные предыдущей заявки
    await prompt_company(update.effective_chat.id, context)
    return COMPANY_NAME


# ─────────────────────────────────────────────
# ФУНКЦИИ ОТПРАВКИ ШАГОВ (переиспользуются и вперёд, и назад)
# ─────────────────────────────────────────────

async def prompt_company(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📝 <b>Шаг 1 из 6</b>\n"
            "Введи <b>название юридического лица</b> (организации):"
        ),
        parse_mode="HTML",
        reply_markup=BACK_KEYBOARD,
    )


async def prompt_object(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📝 <b>Шаг 2 из 6</b>\n"
            "Введи <b>название объекта, город и адрес</b>:\n"
            "<i>Например: ТЦ Мега, Москва, ул. Ленина 1</i>"
        ),
        parse_mode="HTML",
        reply_markup=BACK_KEYBOARD,
    )


async def prompt_tech_task(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📝 <b>Шаг 3 из 6</b>\n"
            "Опиши <b>техническое задание</b> — что должно быть на макете:\n"
            "<i>Например: баннер 3x6м, логотип компании, слоган, фон синий...</i>"
        ),
        parse_mode="HTML",
        reply_markup=BACK_KEYBOARD,
    )


async def prompt_print_type(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("🖨 Печать", callback_data="print")],
        [InlineKeyboardButton("💻 Диджитал", callback_data="digital")],
        [InlineKeyboardButton(BACK_TEXT, callback_data=BACK_CALLBACK)],
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text="📝 <b>Шаг 4 из 6</b>\nВыбери <b>тип макета</b>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def prompt_size(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    print_type = context.user_data.get("print_type", "")
    prefix = f"Тип: <b>{print_type}</b>\n\n" if print_type else ""
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"{prefix}"
            "📝 <b>Шаг 5 из 6</b>\n"
            "Укажи <b>размер макета</b>:\n"
            "<i>Например: 3x6 метра, A4, 1920x1080 px...</i>"
        ),
        parse_mode="HTML",
        reply_markup=BACK_KEYBOARD,
    )


async def prompt_deadline_confirm(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    normal_deadline = context.user_data["normal_deadline"]
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_deadline")],
        [InlineKeyboardButton(BACK_TEXT, callback_data=BACK_CALLBACK)],
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📅 <b>Стандартный дедлайн</b> (+10 раб.дней):\n"
            f"<b>{format_date_ru(normal_deadline)}</b>\n\n"
            f"📝 <b>Шаг 6 из 6</b>\n"
            f"Нажми «Подтвердить» для выбора типа выполнения:"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def prompt_urgent_choice(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    normal = format_date_ru(context.user_data["normal_deadline"])
    urgent = format_date_ru(context.user_data["urgent_deadline"])

    keyboard = [
        [InlineKeyboardButton(f"🐢 Обычный (до {normal})", callback_data="normal")],
        [InlineKeyboardButton(f"🚀 Ускоренный +100₽ (до {urgent})", callback_data="urgent")],
        [InlineKeyboardButton(BACK_TEXT, callback_data=BACK_CALLBACK)],
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏰ <b>Выбери тип выполнения:</b>\n\n"
            f"🐢 <b>Обычный</b> — готовность <b>{normal}</b>\n"
            f"🚀 <b>Ускоренный</b> — готовность <b>{urgent}</b> (+100 ₽)"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список заявок текущего пользователя со статусами"""
    user_id = update.effective_user.id

    my_requests = db.get_requests_by_user(user_id)  # уже отсортированы: свежие сверху

    if not my_requests:
        await update.message.reply_text(
            "У тебя пока нет заявок.\nНажми «📝 Подать заявку», чтобы создать первую.",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return

    lines = ["📋 <b>Твои заявки:</b>\n"]
    for r in my_requests:
        status_label = STATUS_LABELS.get(r["status"], r["status"])
        line = f"<b>#{r['request_id']}</b> — {r['object']}\n{status_label}"
        if r["status"] == "rejected" and r["reason"]:
            line += f"\nПричина: {r['reason']}"
        lines.append(line)

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode="HTML",
        reply_markup=MAIN_MENU_KEYBOARD,
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена диалога"""
    await update.message.reply_text(
        "❌ Заявка отменена.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# ШАГИ ДИАЛОГА
# ─────────────────────────────────────────────

async def get_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем название юр.лица"""
    if update.message.text == BACK_TEXT:
        await update.message.reply_text(
            "Хорошо, отменил подачу заявки.",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return ConversationHandler.END

    context.user_data["company"] = update.message.text.strip()
    await prompt_object(update.effective_chat.id, context)
    return OBJECT_NAME


async def get_object_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем объект, город, адрес"""
    if update.message.text == BACK_TEXT:
        await prompt_company(update.effective_chat.id, context)
        return COMPANY_NAME

    context.user_data["object"] = update.message.text.strip()
    context.user_data["task_date"] = datetime.now()  # дата постановки задачи
    await prompt_tech_task(update.effective_chat.id, context)
    return TECH_TASK


async def get_tech_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем ТЗ"""
    if update.message.text == BACK_TEXT:
        await prompt_object(update.effective_chat.id, context)
        return OBJECT_NAME

    context.user_data["tech_task"] = update.message.text.strip()
    await prompt_print_type(update.effective_chat.id, context)
    return PRINT_TYPE


async def get_print_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем тип (печать/диджитал)"""
    query = update.callback_query
    await query.answer()

    if query.data == BACK_CALLBACK:
        await query.edit_message_reply_markup(reply_markup=None)
        await prompt_tech_task(update.effective_chat.id, context)
        return TECH_TASK

    context.user_data["print_type"] = "Печать" if query.data == "print" else "Диджитал"

    await query.edit_message_text(
        f"✅ Тип: <b>{context.user_data['print_type']}</b>",
        parse_mode="HTML",
    )
    await prompt_size(update.effective_chat.id, context)
    return SIZE


async def back_from_print_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Нажата reply-кнопка 'Назад' на шаге выбора типа макета"""
    await prompt_tech_task(update.effective_chat.id, context)
    return TECH_TASK


async def get_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем размер"""
    if update.message.text == BACK_TEXT:
        await prompt_print_type(update.effective_chat.id, context)
        return PRINT_TYPE

    context.user_data["size"] = update.message.text.strip()

    task_date = context.user_data["task_date"]
    context.user_data["normal_deadline"] = get_working_days_later(task_date, 10)
    context.user_data["urgent_deadline"] = get_working_days_later(task_date, 2)

    await prompt_deadline_confirm(update.effective_chat.id, context)
    return DEADLINE_CONFIRM


async def confirm_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение дедлайна → выбор обычный/ускоренный"""
    query = update.callback_query
    await query.answer()

    if query.data == BACK_CALLBACK:
        await query.edit_message_reply_markup(reply_markup=None)
        await prompt_size(update.effective_chat.id, context)
        return SIZE

    await query.edit_message_reply_markup(reply_markup=None)
    await prompt_urgent_choice(update.effective_chat.id, context)
    return URGENT_CHOICE


async def back_from_deadline_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Нажата reply-кнопка 'Назад' на шаге подтверждения дедлайна"""
    await prompt_size(update.effective_chat.id, context)
    return SIZE


async def process_urgent_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора обычный/ускоренный → финализация заявки"""
    query = update.callback_query
    await query.answer()

    if query.data == BACK_CALLBACK:
        await query.edit_message_reply_markup(reply_markup=None)
        await prompt_deadline_confirm(update.effective_chat.id, context)
        return DEADLINE_CONFIRM

    is_urgent = query.data == "urgent"
    context.user_data["is_urgent"] = is_urgent
    context.user_data["cost"] = 100 if is_urgent else 0

    deadline = context.user_data["urgent_deadline"] if is_urgent else context.user_data["normal_deadline"]
    deadline_str = format_date_ru(deadline)

    request_id = generate_request_id()
    context.user_data["request_id"] = request_id

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
        f"Ожидай уведомления о статусе.\n\n"
        f"Статус всегда можно посмотреть в «📋 Мои заявки»."
    )

    await query.edit_message_text(summary, parse_mode="HTML")

    # Сохраняем заявку в SQLite
    db.create_request(
        request_id=request_id,
        user_id=update.effective_user.id,
        company=context.user_data["company"],
        object_=context.user_data["object"],
        task_date=context.user_data["task_date"],
        tech_task=context.user_data["tech_task"],
        print_type=context.user_data["print_type"],
        size=context.user_data["size"],
        deadline_str=deadline_str,
        is_urgent=is_urgent,
    )

    # ── ОТПРАВЛЯЕМ ЗАЯВКУ АДМИНУ ──
    await send_to_admin(update, context, request_id)

    # Показываем меню заказчику снова
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="Что дальше?",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

    return ConversationHandler.END


async def back_from_urgent_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Нажата reply-кнопка 'Назад' на шаге выбора обычный/ускоренный"""
    await prompt_deadline_confirm(update.effective_chat.id, context)
    return DEADLINE_CONFIRM


async def send_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, request_id: str) -> None:
    """Отправляет заявку админу с кнопками управления"""
    bot = context.bot
    data = context.user_data

    deadline = data["urgent_deadline"] if data["is_urgent"] else data["normal_deadline"]

    admin_text = (
        f"🆕 <b>НОВАЯ ЗАЯВКА #{request_id}</b>\n"
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

    keyboard = [
        [
            InlineKeyboardButton("✅ Принято в работу", callback_data=f"accept_{request_id}"),
        ],
        [
            InlineKeyboardButton("❌ Отклонено", callback_data=f"reject_{request_id}"),
        ],
    ]

    msg = await bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    db.set_admin_message(request_id, msg.chat_id, msg.message_id)


# ─────────────────────────────────────────────
# ОБРАБОТЧИКИ КНОПОК АДМИНА
# ─────────────────────────────────────────────

async def admin_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ нажал 'Принято в работу'"""
    query = update.callback_query
    await query.answer()

    request_id = query.data.replace("accept_", "")
    req = db.get_request(request_id)
    if not req:
        await query.edit_message_text("⚠️ Заявка не найдена.")
        return

    db.set_status(request_id, "in_progress")

    keyboard = [
        [InlineKeyboardButton("✅ В работе", callback_data="noop")],
        [
            InlineKeyboardButton("🏁 Выполнено", callback_data=f"complete_{request_id}"),
            InlineKeyboardButton("❌ Отклонено", callback_data=f"reject_{request_id}"),
        ],
    ]

    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    await query.edit_message_text(
        query.message.text + "\n\n✅ <b>Принято в работу</b>",
        parse_mode="HTML"
    )

    # ── Уведомляем заказчика ──
    try:
        await context.bot.send_message(
            chat_id=req["user_id"],
            text=(
                f"✅ Твоя заявка <b>#{request_id}</b> принята в работу!\n"
                f"Объект: {req['object']}\n"
                f"Дедлайн: {req['deadline_str']}"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить заказчика {req['user_id']}: {e}")


async def admin_complete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ нажал 'Выполнено' — запрашиваем макет"""
    query = update.callback_query
    await query.answer()

    request_id = query.data.replace("complete_", "")
    req = db.get_request(request_id)
    if not req:
        await query.edit_message_text("⚠️ Заявка не найдена.")
        return

    # Помечаем, что от этого админа ждём файл макета для этой заявки
    context.bot_data.setdefault("awaiting_layout_file", {})[update.effective_user.id] = request_id

    await query.edit_message_text(
        query.message.text + "\n\n🏁 <b>Ожидается загрузка макета...</b>\n"
        "Отправь файл макетом в ответ на это сообщение (или просто следующим сообщением).",
        parse_mode="HTML",
    )


async def admin_receive_layout_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ловит файл/фото от админа, если он ожидается для конкретной заявки"""
    awaiting = context.bot_data.get("awaiting_layout_file", {})
    request_id = awaiting.get(update.effective_user.id)
    if not request_id:
        return  # админ просто прислал что-то не по делу — игнорируем

    req = db.get_request(request_id)
    if not req:
        return

    db.set_status(request_id, "completed")
    del awaiting[update.effective_user.id]

    await update.message.reply_text(f"✅ Макет по заявке #{request_id} отправлен заказчику.")

    caption = f"🏁 Твоя заявка <b>#{request_id}</b> выполнена! Макет во вложении."

    try:
        if update.message.document:
            await context.bot.send_document(
                chat_id=req["user_id"],
                document=update.message.document.file_id,
                caption=caption,
                parse_mode="HTML",
            )
        elif update.message.photo:
            await context.bot.send_photo(
                chat_id=req["user_id"],
                photo=update.message.photo[-1].file_id,
                caption=caption,
                parse_mode="HTML",
            )
        else:
            await context.bot.send_message(chat_id=req["user_id"], text=caption, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Не удалось отправить макет заказчику {req['user_id']}: {e}")


async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ нажал 'Отклонено' — запрашиваем причину"""
    query = update.callback_query
    await query.answer()

    request_id = query.data.replace("reject_", "")
    req = db.get_request(request_id)
    if not req:
        await query.edit_message_text("⚠️ Заявка не найдена.")
        return

    # Помечаем, что от этого админа ждём текст причины для этой заявки
    context.bot_data.setdefault("awaiting_reject_reason", {})[update.effective_user.id] = request_id

    await query.edit_message_text(
        query.message.text + "\n\n❌ <b>Напиши причину отклонения следующим сообщением:</b>",
        parse_mode="HTML",
    )


async def admin_receive_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ловит текстовое сообщение от админа, если оно является причиной отклонения"""
    awaiting = context.bot_data.get("awaiting_reject_reason", {})
    request_id = awaiting.get(update.effective_user.id)
    if not request_id:
        return  # это не причина отклонения — пропускаем (обработается другими хендлерами, если есть)

    req = db.get_request(request_id)
    if not req:
        del awaiting[update.effective_user.id]
        return

    reason = update.message.text.strip()
    db.set_status(request_id, "rejected", reason=reason)
    del awaiting[update.effective_user.id]

    await update.message.reply_text(f"❌ Заявка #{request_id} отклонена. Причина отправлена заказчику.")

    # ── Уведомляем заказчика ──
    try:
        await context.bot.send_message(
            chat_id=req["user_id"],
            text=(
                f"❌ Твоя заявка <b>#{request_id}</b> отклонена.\n\n"
                f"<b>Причина:</b> {reason}\n\n"
                f"Если что-то нужно исправить — подай заявку заново через «📝 Подать заявку»."
            ),
            parse_mode="HTML",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить заказчика {req['user_id']}: {e}")

    # Обновляем сообщение у админа тоже
    try:
        await context.bot.edit_message_text(
            chat_id=req["admin_chat_id"],
            message_id=req["admin_message_id"],
            text=(
                f"🆕 <b>ЗАЯВКА #{request_id}</b>\n\n"
                f"❌ <b>Отклонено</b>\n"
                f"Причина: {reason}"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Не удалось обновить сообщение админа: {e}")


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пустая кнопка (уже в работе)"""
    query = update.callback_query
    await query.answer("Уже в работе!")


# ─────────────────────────────────────────────
# ОБЩИЙ РОУТЕР ТЕКСТОВЫХ СООБЩЕНИЙ ОТ АДМИНА
# (вне ConversationHandler — реагирует на причину отклонения)
# ─────────────────────────────────────────────

async def admin_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единая точка входа для текстовых сообщений от админа вне диалога заявки"""
    if update.effective_user.id != ADMIN_ID:
        return
    await admin_receive_reject_reason(update, context)


async def admin_file_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единая точка входа для файлов/фото от админа"""
    if update.effective_user.id != ADMIN_ID:
        return
    await admin_receive_layout_file(update, context)


# ─────────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ (кнопки под полем ввода)
# ─────────────────────────────────────────────

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Обрабатывает нажатия на кнопки главного меню (для не-админа)"""
    text = update.message.text

    if text == "📝 Подать заявку":
        return await start_new_request(update, context)

    if text == "📋 Мои заявки":
        await show_my_requests(update, context)
        return None

    return None


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

    db.init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    # Диалог сбора заявки. Точки входа: /start и кнопка "Подать заявку"
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^📝 Подать заявку$") & ~filters.User(user_id=ADMIN_ID), start_new_request),
        ],
        states={
            COMPANY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_company_name)],
            OBJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_object_name)],
            TECH_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_tech_task)],
            PRINT_TYPE: [
                CallbackQueryHandler(get_print_type, pattern=f"^(print|digital|{BACK_CALLBACK})$"),
                MessageHandler(filters.Regex(f"^{re.escape(BACK_TEXT)}$"), back_from_print_type),
            ],
            SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_size)],
            DEADLINE_CONFIRM: [
                CallbackQueryHandler(confirm_deadline, pattern=f"^(confirm_deadline|{BACK_CALLBACK})$"),
                MessageHandler(filters.Regex(f"^{re.escape(BACK_TEXT)}$"), back_from_deadline_confirm),
            ],
            URGENT_CHOICE: [
                CallbackQueryHandler(process_urgent_choice, pattern=f"^(normal|urgent|{BACK_CALLBACK})$"),
                MessageHandler(filters.Regex(f"^{re.escape(BACK_TEXT)}$"), back_from_urgent_choice),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # Кнопка "Мои заявки" (не-админ)
    application.add_handler(
        MessageHandler(
            filters.Regex("^📋 Мои заявки$") & ~filters.User(user_id=ADMIN_ID),
            show_my_requests,
        )
    )

    # Кнопки админа
    application.add_handler(CallbackQueryHandler(admin_accept, pattern="^accept_"))
    application.add_handler(CallbackQueryHandler(admin_complete, pattern="^complete_"))
    application.add_handler(CallbackQueryHandler(admin_reject, pattern="^reject_"))
    application.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))

    # Текст/файлы от админа вне диалога заявки (причина отклонения / файл макета)
    application.add_handler(
        MessageHandler(filters.User(user_id=ADMIN_ID) & filters.TEXT & ~filters.COMMAND, admin_text_router)
    )
    application.add_handler(
        MessageHandler(
            filters.User(user_id=ADMIN_ID) & (filters.Document.ALL | filters.PHOTO),
            admin_file_router,
        )
    )

    application.add_error_handler(error_handler)

    print("🤖 Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

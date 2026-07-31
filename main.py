# bot.py — Бот для сбора заявок на макеты (v5)

import logging
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
ADMIN_IDS = [6235378997, 111111111]  # ID всех, кто принимает решения по заявкам (узнать у @userinfobot)

DEADLINE_DAYS = 10  # стандартный срок изготовления, рабочих дней

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ХРАНЕНИЕ ЗАЯВОК — в SQLite (см. db.py), переживает перезапуск бота
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
    WORK_FORMAT,       # 3. Формат работ (баннер, наклейка, логотип, сайт и т.д.)
    PRINT_TYPE,        # 4. Печать / Диджитал
    TECH_TASK,         # 5. Полное ТЗ — что должно быть на макете
    SIZE,              # 6. Размер
    DEADLINE_CONFIRM,  # 7. Согласие со сроком изготовления (10 раб.дней)
) = range(7)

TOTAL_STEPS = 7

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

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def build_admin_card_text(req) -> str:
    """Единый текст карточки заявки для админов — используется и при рассылке
    новой заявки, и при показе карточки из списка «В работе»"""
    task_date = datetime.fromisoformat(req["task_date"])
    lines = [
        f"🆕 <b>ЗАЯВКА #{req['request_id']}</b>",
        "━" * 30,
        f"🆔 <b>ID заказчика:</b> <code>{req['user_id']}</code>",
        f"🏢 <b>Юр.лицо:</b> {req['company']}",
        f"📍 <b>Объект:</b> {req['object']}",
        f"📅 <b>Дата постановки:</b> {format_date_ru(task_date)}",
        f"🎨 <b>Формат работ:</b> {req['work_format']}",
        f"🖨 <b>Тип:</b> {req['print_type']}",
        f"📝 <b>ТЗ:</b> {req['tech_task']}",
        f"📐 <b>Размер:</b> {req['size']}",
        f"⏰ <b>Дедлайн:</b> {req['deadline_str']}",
        "━" * 30,
        f"Статус: {STATUS_LABELS.get(req['status'], req['status'])}",
    ]
    if req["status"] == "rejected" and req["reason"]:
        lines.append(f"Причина: {req['reason']}")
    return "\n".join(lines)

def in_progress_action_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Кнопки действий для заявки, которая уже в работе (используется и в
    уведомлении, и в карточке из списка «В работе»)"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏁 Выполнено", callback_data=f"complete_{request_id}"),
            InlineKeyboardButton("❌ Отклонено", callback_data=f"reject_{request_id}"),
        ],
    ])

async def update_all_admin_messages(context: ContextTypes.DEFAULT_TYPE, request_id: str, text: str,
                                     reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    """Обновляет карточку заявки во всех чатах админов, куда она была разослана"""
    for row in db.get_admin_messages(request_id):
        try:
            await context.bot.edit_message_text(
                chat_id=row["chat_id"],
                message_id=row["message_id"],
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error(f"Не удалось обновить сообщение админа {row['chat_id']}: {e}")

# ─────────────────────────────────────────────
# КОМАНДЫ
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало диалога — приветствие + меню"""
    user = update.effective_user

    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Это бот компании PON-PUSHKA для заказа макетов — баннеров, вывесок, диджитал-рекламы и другой печатной/цифровой продукции для ваших объектов.Больше не нужно писать в чат и ждать ответа менеджера — заявка подаётся прямо в отдел маркетинга за пару минут, а статус всегда видно в самом боте.",
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
            f"📝 <b>Шаг 1 из {TOTAL_STEPS}</b>\n"
            "Введи <b>название юридического лица</b> (организации):"
        ),
        parse_mode="HTML",
        reply_markup=BACK_KEYBOARD,
    )


async def prompt_object(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📝 <b>Шаг 2 из {TOTAL_STEPS}</b>\n"
            "Введи <b>название объекта, город и адрес</b>:\n"
            "<i>Например: ТЦ Галилео, Минск, ул. Ленина 1</i>"
        ),
        parse_mode="HTML",
        reply_markup=BACK_KEYBOARD,
    )


async def prompt_work_format(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📝 <b>Шаг 3 из {TOTAL_STEPS}</b>\n"
            "Какой <b>формат работ</b> тебе нужен?\n"
            "<i>Например: баннер, наклейка, логотип, обновление тв, и т.д....</i>"
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
        text=f"📝 <b>Шаг 4 из {TOTAL_STEPS}</b>\nВыбери <b>тип макета</b>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def prompt_tech_task(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📝 <b>Шаг 5 из {TOTAL_STEPS}</b>\n"
            "Опиши <b>полное техническое задание</b> — что должно быть на макете:\n"
            "<i>Например: баннер 3x6м, логотип компании, слоган, фон синий...</i>\n\n"
            "Если пока не знаешь точно, как должно выглядеть — так и напиши, "
            "например: <i>«на усмотрение УК»</i> — мы сами предложим варианты."
        ),
        parse_mode="HTML",
        reply_markup=BACK_KEYBOARD,
    )


async def prompt_size(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📝 <b>Шаг 6 из {TOTAL_STEPS}</b>\n"
            "Укажи <b>размер макета</b>:\n"
            "<i>Например: 3x6 метра, A4, 1920x1080 px...</i>"
        ),
        parse_mode="HTML",
        reply_markup=BACK_KEYBOARD,
    )


async def prompt_deadline_confirm(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    normal_deadline = context.user_data["normal_deadline"]
    keyboard = [
        [InlineKeyboardButton("✅ Согласен со сроком", callback_data="confirm_deadline")],
        [InlineKeyboardButton(BACK_TEXT, callback_data=BACK_CALLBACK)],
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📝 <b>Шаг 7 из {TOTAL_STEPS}</b>\n"
            f"Стандартный срок изготовления — <b>до {DEADLINE_DAYS} рабочих дней</b>.\n"
            f"Ориентировочная дата готовности: <b>{format_date_ru(normal_deadline)}</b>\n\n"
            f"Подтверди, что согласен(на) с этим сроком:"
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
    await prompt_work_format(update.effective_chat.id, context)
    return WORK_FORMAT


async def get_work_format(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем формат работ (баннер, наклейка, логотип, сайт и т.д.)"""
    if update.message.text == BACK_TEXT:
        await prompt_object(update.effective_chat.id, context)
        return OBJECT_NAME

    context.user_data["work_format"] = update.message.text.strip()
    await prompt_print_type(update.effective_chat.id, context)
    return PRINT_TYPE


async def get_print_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем тип (печать/диджитал)"""
    query = update.callback_query
    await query.answer()

    if query.data == BACK_CALLBACK:
        await query.edit_message_reply_markup(reply_markup=None)
        await prompt_work_format(update.effective_chat.id, context)
        return WORK_FORMAT

    context.user_data["print_type"] = "Печать" if query.data == "print" else "Диджитал"

    await query.edit_message_text(
        f"✅ Тип: <b>{context.user_data['print_type']}</b>",
        parse_mode="HTML",
    )
    await prompt_tech_task(update.effective_chat.id, context)
    return TECH_TASK


async def back_from_print_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Нажата reply-кнопка 'Назад' на шаге выбора типа макета"""
    await prompt_work_format(update.effective_chat.id, context)
    return WORK_FORMAT


async def get_tech_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем полное ТЗ"""
    if update.message.text == BACK_TEXT:
        await prompt_print_type(update.effective_chat.id, context)
        return PRINT_TYPE

    context.user_data["tech_task"] = update.message.text.strip()
    await prompt_size(update.effective_chat.id, context)
    return SIZE


async def get_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем размер"""
    if update.message.text == BACK_TEXT:
        await prompt_tech_task(update.effective_chat.id, context)
        return TECH_TASK

    context.user_data["size"] = update.message.text.strip()

    task_date = context.user_data["task_date"]
    context.user_data["normal_deadline"] = get_working_days_later(task_date, DEADLINE_DAYS)

    await prompt_deadline_confirm(update.effective_chat.id, context)
    return DEADLINE_CONFIRM


async def confirm_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Финальный шаг — согласие со сроком → отправка заявки"""
    query = update.callback_query
    await query.answer()

    if query.data == BACK_CALLBACK:
        await query.edit_message_reply_markup(reply_markup=None)
        await prompt_size(update.effective_chat.id, context)
        return SIZE

    deadline_str = format_date_ru(context.user_data["normal_deadline"])

    request_id = generate_request_id()
    context.user_data["request_id"] = request_id

    summary = (
        f"📋 <b>ЗАЯВКА #{request_id}</b>\n"
        f"{'━' * 30}\n"
        f"🏢 <b>Юр.лицо:</b> {context.user_data['company']}\n"
        f"📍 <b>Объект:</b> {context.user_data['object']}\n"
        f"📅 <b>Дата постановки:</b> {format_date_ru(context.user_data['task_date'])}\n"
        f"🎨 <b>Формат работ:</b> {context.user_data['work_format']}\n"
        f"🖨 <b>Тип:</b> {context.user_data['print_type']}\n"
        f"📝 <b>ТЗ:</b> {context.user_data['tech_task']}\n"
        f"📐 <b>Размер:</b> {context.user_data['size']}\n"
        f"⏰ <b>Дедлайн:</b> {deadline_str}\n"
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
        work_format=context.user_data["work_format"],
        tech_task=context.user_data["tech_task"],
        print_type=context.user_data["print_type"],
        size=context.user_data["size"],
        deadline_str=deadline_str,
    )

    # ── ОТПРАВЛЯЕМ ЗАЯВКУ ВСЕМ АДМИНАМ ──
    await send_to_admins(context, request_id)

    # Показываем меню заказчику снова — теперь, когда заявка реально подана
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="Что дальше?",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

    return ConversationHandler.END


async def back_from_deadline_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Нажата reply-кнопка 'Назад' на финальном шаге"""
    await prompt_size(update.effective_chat.id, context)
    return SIZE


async def send_to_admins(context: ContextTypes.DEFAULT_TYPE, request_id: str) -> None:
    """Рассылает новую заявку ВСЕМ админам из ADMIN_IDS с кнопками управления"""
    req = db.get_request(request_id)
    text = build_admin_card_text(req)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Принято в работу", callback_data=f"accept_{request_id}")],
        [InlineKeyboardButton("❌ Отклонено", callback_data=f"reject_{request_id}")],
    ])

    for admin_id in ADMIN_IDS:
        try:
            msg = await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            db.add_admin_message(request_id, msg.chat_id, msg.message_id)
        except Exception as e:
            logger.error(f"Не удалось отправить заявку админу {admin_id}: {e}")


# ─────────────────────────────────────────────
# ОБРАБОТЧИКИ КНОПОК АДМИНА
# ─────────────────────────────────────────────

async def admin_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кто-то из админов нажал 'Принято в работу'"""
    query = update.callback_query
    await query.answer()

    request_id = query.data.replace("accept_", "")
    req = db.get_request(request_id)
    if not req:
        await query.edit_message_text("⚠️ Заявка не найдена.")
        return

    if req["status"] != "pending":
        await query.answer("Заявку уже обработал(а) другой сотрудник.", show_alert=True)
        return

    db.set_status(request_id, "in_progress")
    req = db.get_request(request_id)  # перечитываем со свежим статусом

    # Обновляем карточку у ВСЕХ админов сразу (чтобы не получилось, что двое
    # одновременно жмут разные кнопки на одной и той же заявке)
    await update_all_admin_messages(
        context, request_id, build_admin_card_text(req), in_progress_action_keyboard(request_id)
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

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"🏁 <b>Заявка #{request_id}</b>\n"
            f"Пришли файл макетом следующим сообщением — перед отправкой заказчику "
            f"я покажу его тебе на подтверждение."
        ),
        parse_mode="HTML",
    )


async def admin_receive_layout_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ловит файл/фото от админа, если он ожидается для конкретной заявки.
    Файл пока НЕ уходит заказчику — сначала просим подтверждение."""
    admin_id = update.effective_user.id
    awaiting = context.bot_data.get("awaiting_layout_file", {})
    request_id = awaiting.get(admin_id)
    if not request_id:
        return  # админ просто прислал что-то не по делу — игнорируем

    req = db.get_request(request_id)
    if not req:
        del awaiting[admin_id]
        return

    if update.message.document:
        file_id = update.message.document.file_id
        kind = "document"
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        kind = "photo"
    else:
        return  # не файл и не фото — не наш случай

    # Сохраняем файл во временное ожидание подтверждения (сам файл не скачиваем —
    # достаточно file_id, Telegram хранит его на своей стороне)
    context.bot_data.setdefault("pending_layout", {})[admin_id] = {
        "request_id": request_id,
        "file_id": file_id,
        "kind": kind,
    }
    del awaiting[admin_id]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Отправить заказчику", callback_data=f"send_layout_{request_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_layout_{request_id}"),
        ],
    ])

    caption = (
        f"Отправить этот макет по заявке <b>#{request_id}</b>?\n\n"
        f"🏢 {req['company']}\n"
        f"📍 {req['object']}\n"
        f"🆔 Заказчик: <code>{req['user_id']}</code>"
    )

    if kind == "document":
        await update.message.reply_document(document=file_id, caption=caption, parse_mode="HTML", reply_markup=keyboard)
    else:
        await update.message.reply_photo(photo=file_id, caption=caption, parse_mode="HTML", reply_markup=keyboard)


async def confirm_send_layout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ подтвердил отправку макета — теперь реально отправляем заказчику"""
    query = update.callback_query
    admin_id = update.effective_user.id

    request_id = query.data.replace("send_layout_", "")
    pending = context.bot_data.get("pending_layout", {}).get(admin_id)

    if not pending or pending["request_id"] != request_id:
        await query.answer("Этот файл уже обработан или устарел.", show_alert=True)
        return

    await query.answer()

    req = db.get_request(request_id)
    if not req:
        await query.edit_message_caption(caption="⚠️ Заявка не найдена.")
        del context.bot_data["pending_layout"][admin_id]
        return

    caption = f"🏁 Твоя заявка <b>#{request_id}</b> выполнена! Макет во вложении."

    try:
        if pending["kind"] == "document":
            await context.bot.send_document(
                chat_id=req["user_id"], document=pending["file_id"], caption=caption, parse_mode="HTML",
            )
        else:
            await context.bot.send_photo(
                chat_id=req["user_id"], photo=pending["file_id"], caption=caption, parse_mode="HTML",
            )
        db.set_status(request_id, "completed")
        req = db.get_request(request_id)
        await update_all_admin_messages(context, request_id, build_admin_card_text(req))
        await query.edit_message_caption(caption=f"✅ Макет по заявке #{request_id} отправлен заказчику.")
    except Exception as e:
        logger.error(f"Не удалось отправить макет заказчику {req['user_id']}: {e}")
        await query.edit_message_caption(caption=f"⚠️ Не удалось отправить макет: {e}")

    del context.bot_data["pending_layout"][admin_id]


async def cancel_send_layout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ передумал — файл никуда не уходит, можно прислать другой"""
    query = update.callback_query
    admin_id = update.effective_user.id

    request_id = query.data.replace("cancel_layout_", "")
    pending = context.bot_data.get("pending_layout", {}).get(admin_id)

    await query.answer()

    if pending and pending["request_id"] == request_id:
        del context.bot_data["pending_layout"][admin_id]

    # Разрешаем сразу прислать другой файл без повторного нажатия "Выполнено"
    context.bot_data.setdefault("awaiting_layout_file", {})[admin_id] = request_id

    await query.edit_message_caption(caption="❌ Отменено. Пришли другой файл, когда будет готов.")


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

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"❌ <b>Заявка #{request_id}</b>\nНапиши причину отклонения следующим сообщением:",
        parse_mode="HTML",
    )


async def admin_receive_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ловит текстовое сообщение от админа, если оно является причиной отклонения"""
    admin_id = update.effective_user.id
    awaiting = context.bot_data.get("awaiting_reject_reason", {})
    request_id = awaiting.get(admin_id)
    if not request_id:
        return  # это не причина отклонения — пропускаем

    req = db.get_request(request_id)
    if not req:
        del awaiting[admin_id]
        return

    reason = update.message.text.strip()
    db.set_status(request_id, "rejected", reason=reason)
    req = db.get_request(request_id)
    del awaiting[admin_id]

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

    # Обновляем карточки у всех админов
    await update_all_admin_messages(context, request_id, build_admin_card_text(req))


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пустая кнопка (уже в работе)"""
    query = update.callback_query
    await query.answer("Уже в работе!")


# ─────────────────────────────────────────────
# СПИСОК "В РАБОТЕ" (для админов)
# ─────────────────────────────────────────────

async def show_in_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список заявок в статусе in_progress инлайн-кнопками"""
    if not is_admin(update.effective_user.id):
        return

    requests = db.get_requests_by_status("in_progress")

    if not requests:
        await update.message.reply_text("Сейчас нет заявок в работе.")
        return

    keyboard = [
        [InlineKeyboardButton(f"#{r['request_id']} — {r['object']}", callback_data=f"view_{r['request_id']}")]
        for r in requests
    ]

    await update.message.reply_text(
        "📌 <b>Заявки в работе:</b>\nВыбери, чтобы открыть карточку и изменить статус.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def view_request_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открывает полную карточку заявки из списка «В работе»"""
    query = update.callback_query
    await query.answer()

    request_id = query.data.replace("view_", "")
    req = db.get_request(request_id)
    if not req:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Заявка не найдена.")
        return

    text = build_admin_card_text(req)

    if req["status"] == "in_progress":
        reply_markup = in_progress_action_keyboard(request_id)
    else:
        reply_markup = None  # заявка уже сменила статус, пока список не обновляли — просто показываем инфо

    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=reply_markup,
    )

    # Регистрируем это сообщение тоже, чтобы оно обновлялось при смене статуса
    db.add_admin_message(request_id, msg.chat_id, msg.message_id)


# ─────────────────────────────────────────────
# ОБЩИЙ РОУТЕР ТЕКСТОВЫХ СООБЩЕНИЙ / ФАЙЛОВ ОТ АДМИНОВ
# (вне ConversationHandler — реагирует на причину отклонения и файл макета)
# ─────────────────────────────────────────────

async def admin_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единая точка входа для текстовых сообщений от админа вне диалога заявки"""
    if not is_admin(update.effective_user.id):
        return
    await admin_receive_reject_reason(update, context)


async def admin_file_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единая точка входа для файлов/фото от админа"""
    if not is_admin(update.effective_user.id):
        return
    await admin_receive_layout_file(update, context)


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

    # Диалог сбора заявки. Точки входа: /start и кнопка "Подать заявку".
    # Админам эта ветка не нужна — исключаем их явно.
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start, filters=~filters.User(user_id=ADMIN_IDS)),
            MessageHandler(filters.Regex("^📝 Подать заявку$") & ~filters.User(user_id=ADMIN_IDS), start_new_request),
        ],
        states={
            COMPANY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_company_name)],
            OBJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_object_name)],
            WORK_FORMAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_work_format)],
            PRINT_TYPE: [
                CallbackQueryHandler(get_print_type, pattern=f"^(print|digital|{BACK_CALLBACK})$"),
                MessageHandler(filters.Regex(f"^{re.escape(BACK_TEXT)}$"), back_from_print_type),
            ],
            TECH_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_tech_task)],
            SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_size)],
            DEADLINE_CONFIRM: [
                CallbackQueryHandler(confirm_deadline, pattern=f"^(confirm_deadline|{BACK_CALLBACK})$"),
                MessageHandler(filters.Regex(f"^{re.escape(BACK_TEXT)}$"), back_from_deadline_confirm),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # Кнопка "Мои заявки" (не-админ)
    application.add_handler(
        MessageHandler(
            filters.Regex("^📋 Мои заявки$") & ~filters.User(user_id=ADMIN_IDS),
            show_my_requests,
        )
    )

    # /start и команда для админов — список "В работе"
    application.add_handler(CommandHandler("start", lambda u, c: show_in_progress(u, c), filters=filters.User(user_id=ADMIN_IDS)))
    application.add_handler(CommandHandler("inprogress", show_in_progress, filters=filters.User(user_id=ADMIN_IDS)))
    application.add_handler(CallbackQueryHandler(view_request_card, pattern="^view_"))

    # Кнопки админа
    application.add_handler(CallbackQueryHandler(admin_accept, pattern="^accept_"))
    application.add_handler(CallbackQueryHandler(admin_complete, pattern="^complete_"))
    application.add_handler(CallbackQueryHandler(admin_reject, pattern="^reject_"))
    application.add_handler(CallbackQueryHandler(confirm_send_layout, pattern="^send_layout_"))
    application.add_handler(CallbackQueryHandler(cancel_send_layout, pattern="^cancel_layout_"))
    application.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))

    # Текст/файлы от админа вне диалога заявки (причина отклонения / файл макета)
    application.add_handler(
        MessageHandler(filters.User(user_id=ADMIN_IDS) & filters.TEXT & ~filters.COMMAND, admin_text_router)
    )
    application.add_handler(
        MessageHandler(
            filters.User(user_id=ADMIN_IDS) & (filters.Document.ALL | filters.PHOTO),
            admin_file_router,
        )
    )

    application.add_error_handler(error_handler)

    print("🤖 Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

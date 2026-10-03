import asyncio
import os
import sqlite3
from decimal import Decimal, ROUND_HALF_UP

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
KASPI_NUMBER = os.getenv("KASPI_NUMBER", "Не указан")

SHOP_NAME = "Veylora Shop"

CHANNEL_URL = "https://t.me/veylorashopp"
SUPPORT_URL = "https://t.me/srkhnv"

DB_NAME = "shop.db"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =========================
# БАЗА ДАННЫХ
# =========================

db = sqlite3.connect(DB_NAME, check_same_thread=False)
db.row_factory = sqlite3.Row


def init_db():
    db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            product TEXT NOT NULL,
            quantity TEXT NOT NULL,
            price INTEGER NOT NULL,
            status TEXT NOT NULL,
            receipt TEXT,
            wallet TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Если база была создана старой версией бота,
    # добавляем колонку wallet.
    columns = db.execute(
        "PRAGMA table_info(orders)"
    ).fetchall()

    column_names = [column["name"] for column in columns]

    if "wallet" not in column_names:
        db.execute(
            "ALTER TABLE orders ADD COLUMN wallet TEXT"
        )

    db.commit()


init_db()


# =========================
# СОСТОЯНИЯ
# =========================

class CustomQuantity(StatesGroup):
    stars = State()
    gram = State()


class GramWallet(StatesGroup):
    waiting = State()


# =========================
# РАБОТА С ЗАКАЗАМИ
# =========================

def create_order(
    user_id,
    username,
    product,
    quantity,
    price,
    wallet=None
):
    cursor = db.execute(
        """
        INSERT INTO orders
        (
            user_id,
            username,
            product,
            quantity,
            price,
            status,
            wallet
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            product,
            str(quantity),
            price,
            "awaiting_payment",
            wallet,
        ),
    )

    db.commit()

    return cursor.lastrowid


def get_order(order_id):
    cursor = db.execute(
        "SELECT * FROM orders WHERE id = ?",
        (order_id,),
    )

    return cursor.fetchone()


def update_order_status(order_id, status):
    db.execute(
        "UPDATE orders SET status = ? WHERE id = ?",
        (status, order_id),
    )

    db.commit()


def save_receipt(order_id, receipt):
    db.execute(
        """
        UPDATE orders
        SET receipt = ?, status = ?
        WHERE id = ?
        """,
        (
            receipt,
            "checking",
            order_id,
        ),
    )

    db.commit()


def get_user_orders(user_id):
    cursor = db.execute(
        """
        SELECT *
        FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 10
        """,
        (user_id,),
    )

    return cursor.fetchall()


def get_active_user_order(user_id):
    cursor = db.execute(
        """
        SELECT *
        FROM orders
        WHERE user_id = ?
        AND status = 'waiting_receipt'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    )

    return cursor.fetchone()


# =========================
# КЛАВИАТУРЫ
# =========================

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛍 Магазин",
                    callback_data="shop"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Таблица лидеров",
                    callback_data="leaders"
                ),
                InlineKeyboardButton(
                    text="📖 Инструкция",
                    callback_data="instruction"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Канал",
                    url=CHANNEL_URL
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Мои покупки",
                    callback_data="orders"
                ),
                InlineKeyboardButton(
                    text="💬 Поддержка",
                    callback_data="support"
                )
            ],
        ]
    )


def shop_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Telegram Stars",
                    callback_data="category_stars"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Telegram Premium",
                    callback_data="category_premium"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💠 GRAM",
                    callback_data="category_gram"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back"
                )
            ],
        ]
    )


def stars_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="50 Stars — 420 ₸",
                    callback_data="stars_50"
                )
            ],
            [
                InlineKeyboardButton(
                    text="100 Stars — 840 ₸",
                    callback_data="stars_100"
                )
            ],
            [
                InlineKeyboardButton(
                    text="200 Stars — 1680 ₸",
                    callback_data="stars_200"
                )
            ],
            [
                InlineKeyboardButton(
                    text="300 Stars — 2520 ₸",
                    callback_data="stars_300"
                )
            ],
            [
                InlineKeyboardButton(
                    text="400 Stars — 3360 ₸",
                    callback_data="stars_400"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Своё количество",
                    callback_data="custom_stars"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="shop"
                )
            ],
        ]
    )


def premium_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="3 месяца — 6400 ₸",
                    callback_data="premium_3"
                )
            ],
            [
                InlineKeyboardButton(
                    text="6 месяцев — 8400 ₸",
                    callback_data="premium_6"
                )
            ],
            [
                InlineKeyboardButton(
                    text="12 месяцев — 15400 ₸",
                    callback_data="premium_12"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="shop"
                )
            ],
        ]
    )


def gram_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1 GRAM — 780 ₸",
                    callback_data="gram_1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="2 GRAM — 1560 ₸",
                    callback_data="gram_2"
                )
            ],
            [
                InlineKeyboardButton(
                    text="3 GRAM — 2340 ₸",
                    callback_data="gram_3"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Своё количество",
                    callback_data="custom_gram"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="shop"
                )
            ],
        ]
    )


def payment_keyboard(order_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Я оплатил",
                    callback_data=f"paid_{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ В магазин",
                    callback_data="shop"
                )
            ],
        ]
    )


def admin_order_keyboard(order_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"approve_{order_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject_{order_id}"
                ),
            ]
        ]
    )


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        f"Добро пожаловать в {SHOP_NAME}.\n\n"
        "Здесь можно приобрести Telegram Stars, Premium и GRAM.\n\n"
        "Выберите нужный раздел:",
        reply_markup=main_keyboard()
    )


# =========================
# МАГАЗИН
# =========================

@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛍 Магазин\n\n"
        "Выберите категорию:",
        reply_markup=shop_keyboard()
    )

    await callback.answer()


# =========================
# STARS
# =========================

@dp.callback_query(F.data == "category_stars")
async def stars(callback: CallbackQuery):
    await callback.message.edit_text(
        "⭐ Telegram Stars\n\n"
        "Выберите количество Stars:",
        reply_markup=stars_keyboard()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("stars_"))
async def stars_purchase(callback: CallbackQuery):
    quantity = int(
        callback.data.split("_")[1]
    )

    prices = {
        50: 420,
        100: 840,
        200: 1680,
        300: 2520,
        400: 3360,
    }

    price = prices[quantity]

    await show_payment(
        callback.message,
        callback.from_user,
        "Telegram Stars",
        quantity,
        price
    )

    await callback.answer()


# =========================
# PREMIUM
# =========================

@dp.callback_query(F.data == "category_premium")
async def premium(callback: CallbackQuery):
    await callback.message.edit_text(
        "💎 Telegram Premium\n\n"
        "Выберите срок:",
        reply_markup=premium_keyboard()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("premium_"))
async def premium_purchase(callback: CallbackQuery):
    months = int(
        callback.data.split("_")[1]
    )

    prices = {
        3: 6400,
        6: 8400,
        12: 15400,
    }

    price = prices[months]

    await show_payment(
        callback.message,
        callback.from_user,
        "Telegram Premium",
        f"{months} месяцев",
        price
    )

    await callback.answer()


# =========================
# GRAM
# =========================

@dp.callback_query(F.data == "category_gram")
async def gram(callback: CallbackQuery):
    await callback.message.edit_text(
        "💠 GRAM\n\n"
        "Выберите количество:",
        reply_markup=gram_keyboard()
    )

    await callback.answer()


# Покупка готового количества GRAM
@dp.callback_query(F.data.startswith("gram_"))
async def gram_purchase(callback: CallbackQuery):
    quantity = int(
        callback.data.split("_")[1]
    )

    price = quantity * 780

    # Сохраняем выбранное количество
    # и переводим пользователя на ввод кошелька
    await callback.message.answer(
        f"💠 Покупка GRAM\n\n"
        f"Количество: {quantity}\n"
        f"Стоимость: {price} ₸\n\n"
        "Введите ваш TON-кошелёк, "
        "на который нужно отправить GRAM:"
    )

    await callback.bot.send_chat_action(
        callback.from_user.id,
        "typing"
    )

    await dp.fsm.get_context(
        bot=bot,
        chat_id=callback.from_user.id,
        user_id=callback.from_user.id
    )

    # Передаём данные через FSM
    from aiogram.fsm.context import FSMContext

    state = FSMContext(
        storage=dp.storage,
        key=await dp.fsm.get_context(
            bot=bot,
            chat_id=callback.from_user.id,
            user_id=callback.from_user.id
        ).key
    )

    await state.update_data(
        quantity=quantity,
        price=price
    )

    await state.set_state(
        GramWallet.waiting
    )

    await callback.answer()


# =========================
# СВОЁ КОЛИЧЕСТВО GRAM
# =========================

@dp.callback_query(F.data == "custom_gram")
async def custom_gram(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.set_state(
        CustomQuantity.gram
    )

    await callback.message.answer(
        "💠 Введите количество GRAM числом.\n\n"
        "Например: 4, 5 или 10."
    )

    await callback.answer()


@dp.message(CustomQuantity.gram)
async def custom_gram_amount(
    message: Message,
    state: FSMContext
):
    try:
        quantity = int(
            message.text.strip()
        )

        if quantity <= 0:
            raise ValueError

        price = quantity * 780

        await state.clear()

        await state.update_data(
            quantity=quantity,
            price=price
        )

        await state.set_state(
            GramWallet.waiting
        )

        await message.answer(
            f"💠 Покупка GRAM\n\n"
            f"Количество: {quantity}\n"
            f"Стоимость: {price} ₸\n\n"
            "Введите ваш TON-кошелёк, "
            "на который нужно отправить GRAM:"
        )

    except ValueError:
        await message.answer(
            "Введите целое число больше 0.\n"
            "Например: 5"
        )


# =========================
# ПОЛУЧЕНИЕ TON-КОШЕЛЬКА
# =========================

@dp.message(GramWallet.waiting)
async def gram_wallet(
    message: Message,
    state: FSMContext
):
    wallet = message.text.strip()

    if not wallet:
        await message.answer(
            "Введите TON-кошелёк."
        )
        return

    # Простая проверка длины.
    # Не принимает совсем короткие строки.
    if len(wallet) < 20:
        await message.answer(
            "Похоже, кошелёк указан неправильно.\n\n"
            "Отправьте полный TON-адрес."
        )
        return

    data = await state.get_data()

    quantity = data.get("quantity")
    price = data.get("price")

    if not quantity or not price:
        await state.clear()

        await message.answer(
            "Произошла ошибка. "
            "Пожалуйста, оформите заказ заново."
        )
        return

    await state.clear()

    await show_payment(
        message,
        message.from_user,
        "GRAM",
        quantity,
        price,
        wallet=wallet
    )


# =========================
# СОЗДАНИЕ ЗАКАЗА
# =========================

async def show_payment(
    message,
    user,
    product,
    quantity,
    price,
    wallet=None
):
    username = (
        f"@{user.username}"
        if user.username
        else "без username"
    )

    order_id = create_order(
        user_id=user.id,
        username=username,
        product=product,
        quantity=quantity,
        price=price,
        wallet=wallet
    )

    wallet_text = ""

    if wallet:
        wallet_text = (
            f"\n\nTON-кошелёк:\n"
            f"`{wallet}`"
        )

    await message.answer(
        f"🧾 Заказ #{order_id}\n\n"
        f"Товар: {product}\n"
        f"Количество: {quantity}\n"
        f"Стоимость: {price} ₸"
        f"{wallet_text}\n\n"
        f"💳 Оплата через Kaspi:\n"
        f"{KASPI_NUMBER}\n\n"
        "После перевода нажмите «Я оплатил» "
        "и отправьте фото чека.",
        reply_markup=payment_keyboard(order_id),
        parse_mode="Markdown"
    )


# =========================
# СВОЁ КОЛИЧЕСТВО STARS
# =========================

@dp.callback_query(F.data == "custom_stars")
async def custom_stars(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.set_state(
        CustomQuantity.stars
    )

    await callback.message.answer(
        "⭐ Введите количество Stars числом.\n\n"
        "Например: 55, 75 или 101."
    )

    await callback.answer()


@dp.message(CustomQuantity.stars)
async def custom_stars_amount(
    message: Message,
    state: FSMContext
):
    try:
        quantity = int(
            message.text.strip()
        )

        if quantity <= 0:
            raise ValueError

        raw_price = (
            Decimal(quantity)
            * Decimal("8.4")
        )

        price = int(
            raw_price.quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP
            )
        )

        await state.clear()

        await show_payment(
            message,
            message.from_user,
            "Telegram Stars",
            quantity,
            price
        )

    except ValueError:
        await message.answer(
            "Введите целое число больше 0.\n"
            "Например: 55"
        )


# =========================
# Я ОПЛАТИЛ
# =========================

@dp.callback_query(F.data.startswith("paid_"))
async def paid(callback: CallbackQuery):
    order_id = int(
        callback.data.split("_")[1]
    )

    order = get_order(order_id)

    if not order:
        await callback.answer(
            "Заказ не найден.",
            show_alert=True
        )
        return

    if order["user_id"] != callback.from_user.id:
        await callback.answer(
            "Это не ваш заказ.",
            show_alert=True
        )
        return

    update_order_status(
        order_id,
        "waiting_receipt"
    )

    await callback.message.answer(
        f"Заказ #{order_id}\n\n"
        "Теперь отправьте сюда фото чека Kaspi.\n"
        "После проверки администратор подтвердит заказ."
    )

    await callback.answer()


# =========================
# ПОЛУЧЕНИЕ ЧЕКА
# =========================

@dp.message(F.photo)
async def receipt(message: Message):
    user_id = message.from_user.id

    order = get_active_user_order(
        user_id
    )

    if not order:
        await message.answer(
            "Сначала оформите заказ в магазине."
        )
        return

    receipt_file_id = message.photo[-1].file_id

    save_receipt(
        order["id"],
        receipt_file_id
    )

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "без username"
    )

    wallet_text = ""

    if order["wallet"]:
        wallet_text = (
            f"\n💎 TON-кошелёк:\n"
            f"`{order['wallet']}`\n"
        )

    admin_text = (
        f"🧾 НОВЫЙ ЗАКАЗ #{order['id']}\n\n"
        f"👤 Пользователь: {username}\n"
        f"🆔 ID: {user_id}\n\n"
        f"📦 Товар: {order['product']}\n"
        f"🔢 Количество: {order['quantity']}\n"
        f"💰 Сумма: {order['price']} ₸\n"
        f"{wallet_text}\n"
        "Проверьте оплату по чеку."
    )

    await bot.send_photo(
        ADMIN_ID,
        receipt_file_id,
        caption=admin_text,
        reply_markup=admin_order_keyboard(
            order["id"]
        ),
        parse_mode="Markdown"
    )

    await message.answer(
        f"Чек по заказу #{order['id']} "
        "отправлен администратору.\n\n"
        "Ожидайте подтверждения."
    )


# =========================
# ПОДТВЕРЖДЕНИЕ
# =========================

@dp.callback_query(F.data.startswith("approve_"))
async def approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    order_id = int(
        callback.data.split("_")[1]
    )

    order = get_order(order_id)

    if not order:
        await callback.answer(
            "Заказ не найден.",
            show_alert=True
        )
        return

    update_order_status(
        order_id,
        "approved"
    )

    user_id = order["user_id"]

    await bot.send_message(
        user_id,
        f"✅ Заказ #{order_id} подтверждён.\n\n"
        f"Товар: {order['product']}\n"
        f"Количество: {order['quantity']}\n\n"
        "Оплата подтверждена."
    )

    await bot.send_message(
        user_id,
        "📦 Ваш заказ выдан!"
    )

    await callback.message.edit_caption(
        caption=(
            f"✅ ЗАКАЗ #{order_id} ПОДТВЕРЖДЁН\n\n"
            f"Товар: {order['product']}\n"
            f"Количество: {order['quantity']}\n"
            f"Сумма: {order['price']} ₸"
        )
    )

    await callback.answer(
        "Заказ подтверждён."
    )


# =========================
# ОТКЛОНЕНИЕ
# =========================

@dp.callback_query(F.data.startswith("reject_"))
async def reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    order_id = int(
        callback.data.split("_")[1]
    )

    order = get_order(order_id)

    if not order:
        await callback.answer(
            "Заказ не найден.",
            show_alert=True
        )
        return

    update_order_status(
        order_id,
        "rejected"
    )

    user_id = order["user_id"]

    await bot.send_message(
        user_id,
        f"❌ Заказ #{order_id} не подтверждён.\n\n"
        "Проверьте оплату или обратитесь в поддержку."
    )

    await callback.message.edit_caption(
        caption=(
            f"❌ ЗАКАЗ #{order_id} ОТКЛОНЁН\n\n"
            f"Товар: {order['product']}\n"
            f"Сумма: {order['price']} ₸"
        )
    )

    await callback.answer(
        "Заказ отклонён."
    )


# =========================
# МОИ ПОКУПКИ
# =========================

@dp.callback_query(F.data == "orders")
async def my_orders(callback: CallbackQuery):
    orders = get_user_orders(
        callback.from_user.id
    )

    if not orders:
        await callback.message.edit_text(
            "📦 У вас пока нет заказов.",
            reply_markup=main_keyboard()
        )

        await callback.answer()
        return

    status_names = {
        "awaiting_payment": "Ожидает оплаты",
        "waiting_receipt": "Ожидает чек",
        "checking": "Проверяется",
        "approved": "Подтверждён",
        "rejected": "Отклонён",
    }

    text = "📦 Ваши заказы:\n\n"

    for order in orders:
        status = status_names.get(
            order["status"],
            order["status"]
        )

        text += (
            f"#{order['id']} — {order['product']}\n"
            f"Количество: {order['quantity']}\n"
            f"Сумма: {order['price']} ₸\n"
            f"Статус: {status}\n"
        )

        if order["wallet"]:
            text += (
                f"TON-кошелёк: {order['wallet']}\n"
            )

        text += "\n"

    await callback.message.edit_text(
        text,
        reply_markup=main_keyboard()
    )

    await callback.answer()


# =========================
# ТАБЛИЦА ЛИДЕРОВ
# =========================

@dp.callback_query(F.data == "leaders")
async def leaders(callback: CallbackQuery):
    cursor = db.execute("""
        SELECT
            username,
            COUNT(*) AS purchases,
            SUM(price) AS total
        FROM orders
        WHERE status = 'approved'
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT 10
    """)

    leaders_list = cursor.fetchall()

    if not leaders_list:
        text = (
            "🏆 Таблица лидеров\n\n"
            "Пока здесь никого нет."
        )

    else:
        text = "🏆 Таблица лидеров\n\n"

        for index, user in enumerate(
            leaders_list,
            start=1
        ):
            username = (
                user["username"]
                or "без username"
            )

            text += (
                f"{index}. {username}\n"
                f"Покупок: {user['purchases']}\n"
                f"Сумма: {user['total']} ₸\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=main_keyboard()
    )

    await callback.answer()


# =========================
# ИНСТРУКЦИЯ
# =========================

@dp.callback_query(F.data == "instruction")
async def instruction(callback: CallbackQuery):
    await callback.message.edit_text(
        "📖 Инструкция\n\n"
        "1. Откройте «Магазин».\n"
        "2. Выберите нужный товар.\n"
        "3. Для GRAM укажите TON-кошелёк.\n"
        "4. Оплатите заказ через Kaspi.\n"
        "5. Нажмите «Я оплатил».\n"
        "6. Отправьте фото чека.\n"
        "7. Дождитесь проверки оплаты.\n"
        "8. После подтверждения получите уведомление.\n\n"
        "Если возникли проблемы — обратитесь в поддержку.",
        reply_markup=main_keyboard()
    )

    await callback.answer()


# =========================
# ПОДДЕРЖКА
# =========================

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    support_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Написать в поддержку",
                    url=SUPPORT_URL
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back"
                )
            ],
        ]
    )

    await callback.message.edit_text(
        "💬 Поддержка\n\n"
        "Если возникла проблема с заказом, "
        "напишите в поддержку.",
        reply_markup=support_keyboard
    )

    await callback.answer()


# =========================
# НАЗАД
# =========================

@dp.callback_query(F.data == "back")
async def back(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_keyboard()
    )

    await callback.answer()


# =========================
# ЗАПУСК
# =========================

async def main():
    print("Veylora Shop запущен")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

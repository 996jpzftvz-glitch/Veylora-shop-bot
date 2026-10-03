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
KASPI_NUMBER = os.getenv("KASPI_NUMBER", "")

CHANNEL_URL = "https://t.me/veylorashopp"
REVIEWS_URL = "https://t.me/veylorashopp/111"
SUPPORT_URL = "https://t.me/srkhnv"

PROMO_CODE = "VEYLO5"
PROMO_DISCOUNT = 5
PROMO_LIMIT = 3

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# =========================
# БАЗА ДАННЫХ
# =========================

DB_NAME = "shop.db"


def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            product TEXT,
            amount REAL,
            price INTEGER,
            status TEXT DEFAULT 'awaiting_payment',
            wallet TEXT,
            promo_code TEXT,
            discount INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            product TEXT,
            UNIQUE(user_id, product)
        )
    """)

    # На случай старой базы
    columns = [row[1] for row in cur.execute("PRAGMA table_info(orders)")]

    if "promo_code" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN promo_code TEXT")

    if "discount" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN discount INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


init_db()


# =========================
# СОСТОЯНИЯ
# =========================

class OrderState(StatesGroup):
    waiting_amount = State()
    waiting_wallet = State()
    waiting_receipt = State()


class PromoState(StatesGroup):
    waiting_code = State()


# =========================
# ЦЕНЫ
# =========================

STARS = {
    50: 420,
    100: 840,
    200: 1680,
    300: 2520,
    400: 3360,
}

PREMIUM = {
    3: 6400,
    6: 8400,
    12: 15400,
}

GRAM = {
    1: 800,
    2: 1600,
    3: 2400,
}


# =========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================

def save_user(message: Message):
    conn = db()
    conn.execute("""
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    ))
    conn.commit()
    conn.close()


def create_order(
    user_id,
    username,
    product,
    amount,
    price,
    wallet=None
):
    conn = db()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders
        (user_id, username, product, amount, price, status, wallet)
        VALUES (?, ?, ?, ?, ?, 'awaiting_payment', ?)
    """, (
        user_id,
        username,
        product,
        amount,
        price,
        wallet
    ))

    order_id = cur.lastrowid

    conn.commit()
    conn.close()

    return order_id


def get_order(order_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            user_id,
            username,
            product,
            amount,
            price,
            status,
            wallet,
            promo_code,
            discount
        FROM orders
        WHERE id=?
    """, (order_id,))

    result = cur.fetchone()
    conn.close()

    return result


def update_order_status(order_id, status):
    conn = db()

    conn.execute("""
        UPDATE orders
        SET status=?
        WHERE id=?
    """, (status, order_id))

    conn.commit()
    conn.close()


def update_order_promo(order_id, code, discount, new_price):
    conn = db()

    conn.execute("""
        UPDATE orders
        SET promo_code=?, discount=?, price=?
        WHERE id=?
    """, (
        code,
        discount,
        new_price,
        order_id
    ))

    conn.commit()
    conn.close()


def get_promo_usage():
    conn = db()

    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE promo_code=?
    """, (PROMO_CODE,))

    result = cur.fetchone()[0]

    conn.close()

    return result


def user_used_promo(user_id):
    conn = db()

    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE user_id=? AND promo_code=?
    """, (user_id, PROMO_CODE))

    result = cur.fetchone()[0]

    conn.close()

    return result > 0


def is_favorite(user_id, product):
    conn = db()

    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM favorites
        WHERE user_id=? AND product=?
    """, (user_id, product))

    result = cur.fetchone() is not None

    conn.close()

    return result


def add_favorite(user_id, product):
    conn = db()

    conn.execute("""
        INSERT OR IGNORE INTO favorites
        (user_id, product)
        VALUES (?, ?)
    """, (user_id, product))

    conn.commit()
    conn.close()


def remove_favorite(user_id, product):
    conn = db()

    conn.execute("""
        DELETE FROM favorites
        WHERE user_id=? AND product=?
    """, (user_id, product))

    conn.commit()
    conn.close()


def get_favorites(user_id):
    conn = db()

    cur = conn.cursor()

    cur.execute("""
        SELECT product
        FROM favorites
        WHERE user_id=?
    """, (user_id,))

    result = [row[0] for row in cur.fetchall()]

    conn.close()

    return result


def calculate_stars_price(amount):
    price = Decimal(str(amount)) * Decimal("8.4")
    return int(price.quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP
    ))


def calculate_gram_price(amount):
    return amount * 800


# =========================
# КЛАВИАТУРЫ
# =========================

def main_keyboard(user_id=None):
    buttons = [
        [
            InlineKeyboardButton(
                text="🛍 Магазин",
                callback_data="shop"
            ),
            InlineKeyboardButton(
                text="🪽 Избранное",
                callback_data="favorites"
            )
        ],
        [
            InlineKeyboardButton(
                text="✨ Отзывы",
                url=REVIEWS_URL
            ),
            InlineKeyboardButton(
                text="🏆 Таблица лидеров",
                callback_data="leaders"
            )
        ],
        [
            InlineKeyboardButton(
                text="📖 Инструкция",
                callback_data="instruction"
            ),
            InlineKeyboardButton(
                text="📢 Канал",
                url=CHANNEL_URL
            )
        ],
        [
            InlineKeyboardButton(
                text="🏦 Мои покупки",
                callback_data="my_orders"
            ),
            InlineKeyboardButton(
                text="💬 Поддержка",
                url=SUPPORT_URL
            )
        ]
    ]

    if user_id == ADMIN_ID and ADMIN_ID != 0:
        buttons.append([
            InlineKeyboardButton(
                text="⚙️ Админ-панель",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main"
                )
            ]
        ]
    )


def shop_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Telegram Stars",
                    callback_data="stars"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Telegram Premium",
                    callback_data="premium"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💠 GRAM",
                    callback_data="gram"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main"
                )
            ]
        ]
    )


def receipt_keyboard(order_id):
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
                    text="🎟 Промокод",
                    callback_data=f"promo_{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="shop"
                )
            ]
        ]
    )


def admin_order_keyboard(order_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить",
                    callback_data=f"approve_{order_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject_{order_id}"
                )
            ]
        ]
    )


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):
    save_user(message)

    await message.answer(
        "Добро пожаловать в Veylora Shop.\n\n"
        "Выберите нужный раздел:",
        reply_markup=main_keyboard(message.from_user.id)
    )


# =========================
# НАЗАД
# =========================

@dp.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_keyboard(callback.from_user.id)
    )


# =========================
# МАГАЗИН
# =========================

@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "🛍 Магазин\n\n"
        "Выберите товар:",
        reply_markup=shop_keyboard()
    )


# =========================
# STARS
# =========================

@dp.callback_query(F.data == "stars")
async def stars(callback: CallbackQuery):
    await callback.answer()

    buttons = []

    for amount, price in STARS.items():
        fav = "🪽" if is_favorite(
            callback.from_user.id,
            f"stars_{amount}"
        ) else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{fav} {amount} Stars — {price} ₸",
                callback_data=f"buy_stars_{amount}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="🪽 Добавить/убрать избранное",
            callback_data="fav_stars_menu"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="✏️ Свое количество",
            callback_data="custom_stars"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="shop"
        )
    ])

    await callback.message.edit_text(
        "⭐ Telegram Stars\n\n"
        "Выберите количество:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data.startswith("buy_stars_"))
async def buy_stars(callback: CallbackQuery):
    await callback.answer()

    amount = int(callback.data.split("_")[-1])
    price = STARS[amount]

    product = f"stars_{amount}"

    favorite_text = (
        "🪽 Убрать из избранного"
        if is_favorite(callback.from_user.id, product)
        else "🪽 В избранное"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=favorite_text,
                    callback_data=f"togglefav_{product}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 Купить",
                    callback_data=f"confirm_stars_{amount}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="stars"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        f"⭐ Telegram Stars\n\n"
        f"Количество: {amount}\n"
        f"Цена: {price} ₸",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("confirm_stars_"))
async def confirm_stars(callback: CallbackQuery):
    await callback.answer()

    amount = int(callback.data.split("_")[-1])
    price = STARS[amount]

    order_id = create_order(
        callback.from_user.id,
        callback.from_user.username,
        f"Telegram Stars — {amount}",
        amount,
        price
    )

    await callback.message.edit_text(
        f"Заказ №{order_id}\n\n"
        f"⭐ Telegram Stars: {amount}\n"
        f"💰 К оплате: {price} ₸\n\n"
        f"Оплата через Kaspi:\n"
        f"{KASPI_NUMBER}\n\n"
        "После оплаты нажмите «Я оплатил».",
        reply_markup=receipt_keyboard(order_id)
    )


# =========================
# CUSTOM STARS
# =========================

@dp.callback_query(F.data == "custom_stars")
async def custom_stars(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    await state.set_state(OrderState.waiting_amount)
    await state.update_data(type="stars")

    await callback.message.edit_text(
        "Введите количество Stars числом.\n\n"
        "Цена: 8.4 ₸ за 1 Star."
    )


@dp.message(OrderState.waiting_amount)
async def custom_amount(message: Message, state: FSMContext):
    data = await state.get_data()

    try:
        amount = int(message.text)
    except ValueError:
        await message.answer("Введите количество числом.")
        return

    if amount <= 0:
        await message.answer("Количество должно быть больше 0.")
        return

    if data.get("type") == "stars":
        price = calculate_stars_price(amount)

        order_id = create_order(
            message.from_user.id,
            message.from_user.username,
            f"Telegram Stars — {amount}",
            amount,
            price
        )

        await state.clear()

        await message.answer(
            f"Заказ №{order_id}\n\n"
            f"⭐ Stars: {amount}\n"
            f"💰 К оплате: {price} ₸\n\n"
            f"Kaspi:\n{KASPI_NUMBER}\n\n"
            "После оплаты нажмите «Я оплатил».",
            reply_markup=receipt_keyboard(order_id)
        )


# =========================
# PREMIUM
# =========================

@dp.callback_query(F.data == "premium")
async def premium(callback: CallbackQuery):
    await callback.answer()

    buttons = []

    for months, price in PREMIUM.items():
        product = f"premium_{months}"

        fav = "🪽" if is_favorite(
            callback.from_user.id,
            product
        ) else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{fav} {months} мес. — {price} ₸",
                callback_data=f"buy_premium_{months}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="shop"
        )
    ])

    await callback.message.edit_text(
        "💎 Telegram Premium\n\n"
        "Выберите срок:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data.startswith("buy_premium_"))
async def buy_premium(callback: CallbackQuery):
    await callback.answer()

    months = int(callback.data.split("_")[-1])
    price = PREMIUM[months]

    product = f"premium_{months}"

    favorite_text = (
        "🪽 Убрать из избранного"
        if is_favorite(callback.from_user.id, product)
        else "🪽 В избранное"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=favorite_text,
                    callback_data=f"togglefav_{product}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 Купить",
                    callback_data=f"confirm_premium_{months}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="premium"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        f"💎 Telegram Premium\n\n"
        f"Срок: {months} мес.\n"
        f"Цена: {price} ₸",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("confirm_premium_"))
async def confirm_premium(callback: CallbackQuery):
    await callback.answer()

    months = int(callback.data.split("_")[-1])
    price = PREMIUM[months]

    order_id = create_order(
        callback.from_user.id,
        callback.from_user.username,
        f"Telegram Premium — {months} мес.",
        months,
        price
    )

    await callback.message.edit_text(
        f"Заказ №{order_id}\n\n"
        f"💎 Premium: {months} мес.\n"
        f"💰 К оплате: {price} ₸\n\n"
        f"Kaspi:\n{KASPI_NUMBER}\n\n"
        "После оплаты нажмите «Я оплатил».",
        reply_markup=receipt_keyboard(order_id)
    )


# =========================
# GRAM
# =========================

@dp.callback_query(F.data == "gram")
async def gram(callback: CallbackQuery):
    await callback.answer()

    buttons = []

    for amount, price in GRAM.items():
        product = f"gram_{amount}"

        fav = "🪽" if is_favorite(
            callback.from_user.id,
            product
        ) else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{fav} {amount} GRAM — {price} ₸",
                callback_data=f"buy_gram_{amount}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="✏️ Свое количество",
            callback_data="custom_gram"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="shop"
        )
    ])

    await callback.message.edit_text(
        "💠 GRAM\n\n"
        "Выберите количество:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data.startswith("buy_gram_"))
async def buy_gram(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    amount = int(callback.data.split("_")[-1])

    await state.set_state(OrderState.waiting_wallet)
    await state.update_data(
        type="gram",
        amount=amount
    )

    await callback.message.edit_text(
        f"💠 GRAM: {amount}\n\n"
        "Введите ваш TON-кошелёк для получения GRAM:"
    )


@dp.callback_query(F.data == "custom_gram")
async def custom_gram(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    await state.set_state(OrderState.waiting_amount)
    await state.update_data(type="gram")

    await callback.message.edit_text(
        "Введите количество GRAM числом.\n\n"
        "Цена: 800 ₸ за 1 GRAM."
    )


@dp.message(OrderState.waiting_wallet)
async def wallet_received(message: Message, state: FSMContext):
    wallet = message.text.strip()

    if len(wallet) < 20:
        await message.answer(
            "Похоже, кошелёк указан неправильно.\n"
            "Отправьте TON-кошелёк ещё раз."
        )
        return

    data = await state.get_data()

    amount = data["amount"]
    price = calculate_gram_price(amount)

    order_id = create_order(
        message.from_user.id,
        message.from_user.username,
        f"GRAM — {amount}",
        amount,
        price,
        wallet
    )

    await state.clear()

    await message.answer(
        f"Заказ №{order_id}\n\n"
        f"💠 GRAM: {amount}\n"
        f"💰 К оплате: {price} ₸\n"
        f"👛 Кошелёк: {wallet}\n\n"
        f"Kaspi:\n{KASPI_NUMBER}\n\n"
        "После оплаты нажмите «Я оплатил».",
        reply_markup=receipt_keyboard(order_id)
    )


# =========================
# ИЗБРАННОЕ
# =========================

@dp.callback_query(F.data == "favorites")
async def favorites(callback: CallbackQuery):
    await callback.answer()

    products = get_favorites(callback.from_user.id)

    if not products:
        await callback.message.edit_text(
            "🪽 Избранное пока пустое.\n\n"
            "Добавляйте товары, которые хотите быстро находить.",
            reply_markup=back_button()
        )
        return

    buttons = []

    for product in products:
        if product.startswith("stars_"):
            amount = product.split("_")[1]
            price = calculate_stars_price(int(amount))

            buttons.append([
                InlineKeyboardButton(
                    text=f"⭐ Stars {amount} — {price} ₸",
                    callback_data=f"favopen_{product}"
                )
            ])

        elif product.startswith("premium_"):
            months = product.split("_")[1]
            price = PREMIUM.get(int(months), 0)

            buttons.append([
                InlineKeyboardButton(
                    text=f"💎 Premium {months} мес. — {price} ₸",
                    callback_data=f"favopen_{product}"
                )
            ])

        elif product.startswith("gram_"):
            amount = product.split("_")[1]
            price = int(amount) * 800

            buttons.append([
                InlineKeyboardButton(
                    text=f"💠 GRAM {amount} — {price} ₸",
                    callback_data=f"favopen_{product}"
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_main"
        )
    ])

    await callback.message.edit_text(
        "🪽 Избранное\n\n"
        "Ваши сохранённые товары:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data.startswith("togglefav_"))
async def toggle_favorite(callback: CallbackQuery):
    await callback.answer()

    product = callback.data.replace("togglefav_", "")

    if is_favorite(callback.from_user.id, product):
        remove_favorite(callback.from_user.id, product)
        text = "Удалено из избранного."
    else:
        add_favorite(callback.from_user.id, product)
        text = "Добавлено в избранное."

    await callback.answer(text)

    if product.startswith("stars_"):
        amount = int(product.split("_")[1])

        await callback.message.edit_text(
            f"⭐ Telegram Stars\n\n"
            f"Количество: {amount}\n"
            f"Цена: {calculate_stars_price(amount)} ₸",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=(
                                "🪽 Убрать из избранного"
                                if is_favorite(
                                    callback.from_user.id,
                                    product
                                )
                                else "🪽 В избранное"
                            ),
                            callback_data=f"togglefav_{product}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="💳 Купить",
                            callback_data=f"confirm_stars_{amount}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data="stars"
                        )
                    ]
                ]
            )
        )

    elif product.startswith("premium_"):
        months = int(product.split("_")[1])

        await callback.message.edit_text(
            f"💎 Telegram Premium\n\n"
            f"Срок: {months} мес.\n"
            f"Цена: {PREMIUM[months]} ₸",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=(
                                "🪽 Убрать из избранного"
                                if is_favorite(
                                    callback.from_user.id,
                                    product
                                )
                                else "🪽 В избранное"
                            ),
                            callback_data=f"togglefav_{product}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="💳 Купить",
                            callback_data=f"confirm_premium_{months}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data="premium"
                        )
                    ]
                ]
            )
        )


@dp.callback_query(F.data.startswith("favopen_"))
async def favorite_open(callback: CallbackQuery):
    await callback.answer()

    product = callback.data.replace("favopen_", "")

    if product.startswith("stars_"):
        amount = int(product.split("_")[1])

        await callback.message.edit_text(
            f"⭐ Telegram Stars\n\n"
            f"Количество: {amount}\n"
            f"Цена: {calculate_stars_price(amount)} ₸",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💳 Купить",
                            callback_data=f"confirm_stars_{amount}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🗑 Убрать из избранного",
                            callback_data=f"togglefav_{product}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data="favorites"
                        )
                    ]
                ]
            )
        )

    elif product.startswith("premium_"):
        months = int(product.split("_")[1])

        await callback.message.edit_text(
            f"💎 Telegram Premium\n\n"
            f"Срок: {months} мес.\n"
            f"Цена: {PREMIUM[months]} ₸",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💳 Купить",
                            callback_data=f"confirm_premium_{months}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🗑 Убрать из избранного",
                            callback_data=f"togglefav_{product}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data="favorites"
                        )
                    ]
                ]
            )
        )

    elif product.startswith("gram_"):
        amount = int(product.split("_")[1])

        await callback.message.edit_text(
            f"💠 GRAM\n\n"
            f"Количество: {amount}\n"
            f"Цена: {amount * 800} ₸\n\n"
            "Для покупки потребуется TON-кошелёк.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🗑 Убрать из избранного",
                            callback_data=f"togglefav_{product}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data="favorites"
                        )
                    ]
                ]
            )
        )


# =========================
# ОТЗЫВЫ
# =========================

@dp.callback_query(F.data == "reviews")
async def reviews(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "✨ Отзывы Veylora Shop\n\n"
        "Оставить отзыв можно в комментариях "
        "под постом с отзывами:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="—> Оставить отзыв",
                        url=REVIEWS_URL
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


# =========================
# ПРОМОКОД
# =========================

@dp.callback_query(F.data.startswith("promo_"))
async def promo_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    order_id = int(callback.data.split("_")[-1])

    order = get_order(order_id)

    if not order or order[1] != callback.from_user.id:
        await callback.message.answer("Заказ не найден.")
        return

    await state.set_state(PromoState.waiting_code)
    await state.update_data(order_id=order_id)

    await callback.message.answer(
        "Введите промокод:"
    )


@dp.message(PromoState.waiting_code)
async def promo_received(message: Message, state: FSMContext):
    code = message.text.strip().upper()

    data = await state.get_data()
    order_id = data["order_id"]

    order = get_order(order_id)

    if not order:
        await state.clear()
        await message.answer("Заказ не найден.")
        return

    if code != PROMO_CODE:
        await message.answer(
            "Такого промокода нет."
        )
        return

    usage = get_promo_usage()

    if usage >= PROMO_LIMIT:
        await state.clear()

        await message.answer(
            "Этот промокод уже использовали первые "
            f"{PROMO_LIMIT} покупателей."
        )
        return

    if user_used_promo(message.from_user.id):
        await state.clear()

        await message.answer(
            "Вы уже использовали этот промокод."
        )
        return

    old_price = order[5]

    new_price = int(
        Decimal(old_price)
        * Decimal(100 - PROMO_DISCOUNT)
        / Decimal(100)
    )

    update_order_promo(
        order_id,
        PROMO_CODE,
        PROMO_DISCOUNT,
        new_price
    )

    await state.clear()

    await message.answer(
        f"Промокод применён.\n\n"
        f"Старая цена: {old_price} ₸\n"
        f"Скидка: {PROMO_DISCOUNT}%\n"
        f"Новая цена: {new_price} ₸\n\n"
        f"Kaspi:\n{KASPI_NUMBER}\n\n"
        "После оплаты нажмите «Я оплатил».",
        reply_markup=receipt_keyboard(order_id)
    )


# =========================
# ОПЛАТА
# =========================

@dp.callback_query(F.data.startswith("paid_"))
async def paid(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    order_id = int(callback.data.split("_")[-1])

    order = get_order(order_id)

    if not order or order[1] != callback.from_user.id:
        await callback.message.answer("Заказ не найден.")
        return

    await state.set_state(OrderState.waiting_receipt)
    await state.update_data(order_id=order_id)

    await callback.message.edit_text(
        f"Заказ №{order_id}\n\n"
        "Отправьте чек об оплате.\n\n"
        "Можно отправить:\n"
        "• фото\n"
        "• PDF-файл"
    )


# =========================
# ЧЕК — ФОТО
# =========================

@dp.message(
    OrderState.waiting_receipt,
    F.photo
)
async def receipt_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data["order_id"]

    order = get_order(order_id)

    if not order:
        await state.clear()
        await message.answer("Заказ не найден.")
        return

    update_order_status(order_id, "waiting_check")

    caption = (
        f"🧾 Новый чек\n\n"
        f"Заказ: #{order_id}\n"
        f"Пользователь: @{order[2] or 'нет username'}\n"
        f"ID: {order[1]}\n"
        f"Товар: {order[3]}\n"
        f"Сумма: {order[5]} ₸\n"
    )

    if order[7]:
        caption += f"Кошелёк: {order[7]}\n"

    if order[8]:
        caption += (
            f"Промокод: {order[8]}\n"
            f"Скидка: {order[9]}%\n"
        )

    try:
        await bot.send_photo(
            ADMIN_ID,
            message.photo[-1].file_id,
            caption=caption,
            reply_markup=admin_order_keyboard(order_id)
        )
    except Exception as e:
        print("Ошибка отправки чека админу:", e)

    await state.clear()

    await message.answer(
        "Чек отправлен на проверку.\n"
        "Ожидайте подтверждения заказа."
    )


# =========================
# ЧЕК — PDF
# =========================

@dp.message(
    OrderState.waiting_receipt,
    F.document
)
async def receipt_pdf(message: Message, state: FSMContext):
    document = message.document

    is_pdf = (
        document.mime_type == "application/pdf"
        or (
            document.file_name
            and document.file_name.lower().endswith(".pdf")
        )
    )

    if not is_pdf:
        await message.answer(
            "Пожалуйста, отправьте чек в формате PDF или фото."
        )
        return

    data = await state.get_data()
    order_id = data["order_id"]

    order = get_order(order_id)

    if not order:
        await state.clear()
        await message.answer("Заказ не найден.")
        return

    update_order_status(order_id, "waiting_check")

    caption = (
        f"🧾 Новый PDF-чек\n\n"
        f"Заказ: #{order_id}\n"
        f"Пользователь: @{order[2] or 'нет username'}\n"
        f"ID: {order[1]}\n"
        f"Товар: {order[3]}\n"
        f"Сумма: {order[5]} ₸\n"
    )

    if order[7]:
        caption += f"Кошелёк: {order[7]}\n"

    if order[8]:
        caption += (
            f"Промокод: {order[8]}\n"
            f"Скидка: {order[9]}%\n"
        )

    try:
        await bot.send_document(
            ADMIN_ID,
            document.file_id,
            caption=caption,
            reply_markup=admin_order_keyboard(order_id)
        )
    except Exception as e:
        print("Ошибка отправки PDF:", e)

    await state.clear()

    await message.answer(
        "PDF-чек отправлен на проверку.\n"
        "Ожидайте подтверждения заказа."
    )


# =========================
# АДМИН — ОДОБРЕНИЕ
# =========================

@dp.callback_query(F.data.startswith("approve_"))
async def approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.")
        return

    await callback.answer()

    order_id = int(callback.data.split("_")[-1])
    order = get_order(order_id)

    if not order:
        await callback.message.answer("Заказ не найден.")
        return

    update_order_status(order_id, "approved")

    try:
        await callback.message.edit_caption(
            caption=(
                f"✅ Заказ #{order_id} одобрен\n\n"
                f"Товар: {order[3]}\n"
                f"Сумма: {order[5]} ₸"
            )
        )
    except Exception:
        try:
            await callback.message.edit_text(
                f"✅ Заказ #{order_id} одобрен\n\n"
                f"Товар: {order[3]}\n"
                f"Сумма: {order[5]} ₸"
            )
        except Exception:
            pass

    try:
        await bot.send_message(
            order[1],
            "✅ Заказ успешно обработан!\n\n"
            "Спасибо за покупку в Veylora Shop.\n\n"
            "Будем очень благодарны за отзыв:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="—> Оставить отзыв",
                            url=REVIEWS_URL
                        )
                    ]
                ]
            )
        )
    except Exception as e:
        print("Ошибка уведомления пользователя:", e)


# =========================
# АДМИН — ОТКЛОНЕНИЕ
# =========================

@dp.callback_query(F.data.startswith("reject_"))
async def reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.")
        return

    await callback.answer()

    order_id = int(callback.data.split("_")[-1])
    order = get_order(order_id)

    if not order:
        await callback.message.answer("Заказ не найден.")
        return

    update_order_status(order_id, "rejected")

    try:
        await callback.message.edit_caption(
            caption=f"❌ Заказ #{order_id} отклонён."
        )
    except Exception:
        try:
            await callback.message.edit_text(
                f"❌ Заказ #{order_id} отклонён."
            )
        except Exception:
            pass

    try:
        await bot.send_message(
            order[1],
            f"❌ Заказ №{order_id} отклонён.\n\n"
            "Если произошла ошибка, обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💬 Поддержка",
                            url=SUPPORT_URL
                        )
                    ]
                ]
            )
        )
    except Exception as e:
        print("Ошибка уведомления:", e)


# =========================
# МОИ ПОКУПКИ
# =========================

@dp.callback_query(F.data == "my_orders")
async def my_orders(callback: CallbackQuery):
    await callback.answer()

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, product, price, status
        FROM orders
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (callback.from_user.id,))

    orders = cur.fetchall()

    conn.close()

    if not orders:
        await callback.message.edit_text(
            "🏦 У вас пока нет покупок.",
            reply_markup=back_button()
        )
        return

    text = "🏦 Мои покупки\n\n"

    for order_id, product, price, status in orders:
        if status == "approved":
            status_text = "обработан"
        elif status == "rejected":
            status_text = "отклонён"
        elif status == "waiting_check":
            status_text = "проверяется"
        else:
            status_text = "ожидает оплаты"

        text += (
            f"№{order_id} — {product}\n"
            f"{price} ₸ — {status_text}\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=back_button()
    )


# =========================
# ЛИДЕРЫ
# =========================

@dp.callback_query(F.data == "leaders")
async def leaders(callback: CallbackQuery):
    await callback.answer()

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT username, SUM(price) AS total
        FROM orders
        WHERE status='approved'
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT 10
    """)

    leaders_data = cur.fetchall()

    conn.close()

    if not leaders_data:
        await callback.message.edit_text(
            "🏆 Таблица лидеров пока пуста.",
            reply_markup=back_button()
        )
        return

    text = "🏆 Таблица лидеров\n\n"

    for i, (username, total) in enumerate(leaders_data, 1):
        name = f"@{username}" if username else "Покупатель"

        text += (
            f"{i}. {name} — {total} ₸\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=back_button()
    )


# =========================
# ИНСТРУКЦИЯ
# =========================

@dp.callback_query(F.data == "instruction")
async def instruction(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "📖 Инструкция\n\n"
        "1. Выберите товар в магазине.\n"
        "2. Создайте заказ.\n"
        "3. Оплатите указанную сумму.\n"
        "4. Нажмите «Я оплатил».\n"
        "5. Отправьте чек — фото или PDF.\n"
        "6. Дождитесь проверки.\n"
        "7. После подтверждения заказ будет обработан.\n\n"
        "По вопросам обращайтесь в поддержку.",
        reply_markup=back_button()
    )


# =========================
# АДМИН-ПАНЕЛЬ
# =========================

@dp.callback_query(F.data == "admin")
async def admin(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.")
        return

    await callback.answer()

    await callback.message.edit_text(
        "⚙️ Админ-панель",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📦 Новые заказы",
                        callback_data="admin_new"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔎 Проверка чеков",
                        callback_data="admin_checks"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📊 Статистика",
                        callback_data="admin_stats"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="👥 Пользователи",
                        callback_data="admin_users"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


@dp.callback_query(F.data == "admin_new")
async def admin_new(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.")
        return

    await callback.answer()

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, username, product, price
        FROM orders
        WHERE status='awaiting_payment'
        ORDER BY id DESC
        LIMIT 20
    """)

    orders = cur.fetchall()

    conn.close()

    if not orders:
        text = "📦 Новых заказов нет."
    else:
        text = "📦 Новые заказы\n\n"

        for order_id, username, product, price in orders:
            text += (
                f"#{order_id} — "
                f"@{username or 'нет username'}\n"
                f"{product} — {price} ₸\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="admin"
                    )
                ]
            ]
        )
    )


@dp.callback_query(F.data == "admin_checks")
async def admin_checks(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.")
        return

    await callback.answer()

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, username, product, price
        FROM orders
        WHERE status='waiting_check'
        ORDER BY id DESC
        LIMIT 20
    """)

    orders = cur.fetchall()

    conn.close()

    if not orders:
        text = "🔎 Сейчас чеков на проверке нет."
    else:
        text = "🔎 Чеки на проверке\n\n"

        for order_id, username, product, price in orders:
            text += (
                f"#{order_id} — "
                f"@{username or 'нет username'}\n"
                f"{product} — {price} ₸\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="admin"
                    )
                ]
            ]
        )
    )


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.")
        return

    await callback.answer()

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE status='approved'
    """)
    approved = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(price), 0)
        FROM orders
        WHERE status='approved'
    """)
    revenue = cur.fetchone()[0]

    conn.close()

    promo_usage = get_promo_usage()

    await callback.message.edit_text(
        "📊 Статистика\n\n"
        f"👥 Пользователей: {users}\n"
        f"✅ Обработано заказов: {approved}\n"
        f"💰 Выручка: {revenue} ₸\n\n"
        f"🎟 Промокод {PROMO_CODE}: "
        f"{promo_usage}/{PROMO_LIMIT}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="admin"
                    )
                ]
            ]
        )
    )


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.")
        return

    await callback.answer()

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]

    conn.close()

    await callback.message.edit_text(
        f"👥 Пользователи\n\n"
        f"Всего пользователей: {count}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="admin"
                    )
                ]
            ]
        )
    )


# =========================
# ЗАПУСК
# =========================

async def main():
    print("Veylora Shop Bot запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

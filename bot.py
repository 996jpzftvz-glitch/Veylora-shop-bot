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


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
KASPI_NUMBER = os.getenv("KASPI_NUMBER", "")

CHANNEL_URL = "https://t.me/veylorashopp"
REVIEWS_URL = "https://t.me/veylorashopp/111"
SUPPORT_URL = "https://t.me/srkhnv"

# ВАЖНО:
# База всегда находится рядом с bot.py.
# Это позволяет не создавать новую shop.db
# при запуске бота из другой рабочей директории.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "shop.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")


bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# =========================================================
# СОСТОЯНИЯ
# =========================================================

class OrderState(StatesGroup):
    waiting_amount = State()
    waiting_wallet = State()
    waiting_receipt = State()


class PriceState(StatesGroup):
    waiting_price = State()


class BroadcastState(StatesGroup):
    waiting_text = State()


# =========================================================
# БАЗА ДАННЫХ
# =========================================================

def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table, column, definition):
    """
    Безопасно добавляет колонку в старую базу,
    если её ещё нет.
    """
    cur = conn.cursor()

    cur.execute(f"PRAGMA table_info({table})")
    columns = [row["name"] for row in cur.fetchall()]

    if column not in columns:
        cur.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():
    conn = db()
    cur = conn.cursor()

    # -----------------------------------------------------
    # Пользователи
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT
        )
    """)

    # Добавляем фамилию в старую базу,
    # если её ещё нет.
    ensure_column(
        conn,
        "users",
        "last_name",
        "TEXT"
    )

    # -----------------------------------------------------
    # Заказы
    # -----------------------------------------------------

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # -----------------------------------------------------
    # Избранное
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            product TEXT,
            UNIQUE(user_id, product)
        )
    """)

    # -----------------------------------------------------
    # Настройки
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # -----------------------------------------------------
    # ПОСТОЯННАЯ СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ
    # -----------------------------------------------------
    #
    # Здесь хранится статистика каждого пользователя:
    #
    # purchases_count = количество одобренных покупок
    # total_spent     = сколько всего потратил
    # last_purchase_at = дата последней покупки
    #
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id INTEGER PRIMARY KEY,
            purchases_count INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0,
            last_purchase_at TEXT
        )
    """)

    defaults = {
        "stars_50": "420",
        "stars_100": "840",
        "stars_200": "1680",
        "stars_300": "2520",
        "stars_400": "3360",

        "premium_3": "6400",
        "premium_6": "8400",
        "premium_12": "15400",

        "gram_1": "800",
        "gram_2": "1600",
        "gram_3": "2400",
    }

    for key, value in defaults.items():
        cur.execute("""
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
        """, (key, value))

    conn.commit()

    # -----------------------------------------------------
    # ВОССТАНОВЛЕНИЕ СТАТИСТИКИ
    # -----------------------------------------------------
    #
    # При каждом запуске статистика сверяется с уже
    # существующими approved-заказами.
    #
    # Это позволяет сохранить старую статистику даже
    # после обновления bot.py.
    #
    # -----------------------------------------------------

    rebuild_user_stats(conn)

    conn.close()


def rebuild_user_stats(conn=None):
    """
    Восстанавливает user_stats на основании всех
    уже одобренных заказов.

    Это НЕ удаляет пользователей и НЕ удаляет заказы.
    """

    own_connection = False

    if conn is None:
        conn = db()
        own_connection = True

    cur = conn.cursor()

    # Создаём статистику для пользователей,
    # у которых ещё нет записи.
    cur.execute("""
        INSERT OR IGNORE INTO user_stats (
            user_id,
            purchases_count,
            total_spent,
            last_purchase_at
        )
        SELECT
            user_id,
            0,
            0,
            NULL
        FROM users
    """)

    # Полностью пересчитываем статистику по истории
    # подтверждённых заказов.
    cur.execute("""
        UPDATE user_stats
        SET
            purchases_count = 0,
            total_spent = 0,
            last_purchase_at = NULL
    """)

    cur.execute("""
        SELECT
            user_id,
            COUNT(*) AS purchases_count,
            COALESCE(SUM(price), 0) AS total_spent,
            MAX(created_at) AS last_purchase_at
        FROM orders
        WHERE status = 'approved'
        GROUP BY user_id
    """)

    rows = cur.fetchall()

    for row in rows:
        cur.execute("""
            INSERT INTO user_stats (
                user_id,
                purchases_count,
                total_spent,
                last_purchase_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                purchases_count = excluded.purchases_count,
                total_spent = excluded.total_spent,
                last_purchase_at = excluded.last_purchase_at
        """, (
            row["user_id"],
            row["purchases_count"],
            row["total_spent"],
            row["last_purchase_at"]
        ))

    conn.commit()

    if own_connection:
        conn.close()


init_db()


# =========================================================
# НАСТРОЙКИ / ЦЕНЫ
# =========================================================

def get_setting(key, default=None):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    )

    row = cur.fetchone()

    conn.close()

    if row is None:
        return default

    return row["value"]


def set_setting(key, value):
    conn = db()

    conn.execute("""
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
    """, (key, str(value)))

    conn.commit()
    conn.close()


def get_price(key):
    return int(get_setting(key, "0"))


# =========================================================
# ПРОВЕРКА USERNAME
# =========================================================

def has_username(user):
    return bool(
        user.username and
        user.username.strip()
    )


def username_required_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Установить username",
                    url="tg://settings/username"
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


async def check_username_message(message: Message):
    if has_username(message.from_user):
        return True

    await message.answer(
        "❌ Для оформления заказа необходимо "
        "установить username в Telegram.\n\n"
        "Ваш username нужен для идентификации заказа "
        "и связи с вами.\n\n"
        "Установите @username в настройках Telegram, "
        "а затем снова оформите заказ.",
        reply_markup=username_required_keyboard()
    )

    return False


async def check_username_callback(callback: CallbackQuery):
    if has_username(callback.from_user):
        return True

    await callback.answer(
        "Сначала установите username в Telegram.",
        show_alert=True
    )

    try:
        await callback.message.edit_text(
            "❌ Для оформления заказа необходимо "
            "установить username в Telegram.\n\n"
            "Ваш username нужен для идентификации заказа "
            "и связи с вами.\n\n"
            "Установите @username в настройках Telegram, "
            "а затем снова оформите заказ.",
            reply_markup=username_required_keyboard()
        )
    except Exception:
        pass

    return False


# =========================================================
# ПОЛЬЗОВАТЕЛИ
# =========================================================

def save_user(message: Message):
    user = message.from_user

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            last_name
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name
    """, (
        user.id,
        user.username,
        user.first_name,
        user.last_name
    ))

    # Создаём запись постоянной статистики,
    # если её ещё нет.
    cur.execute("""
        INSERT OR IGNORE INTO user_stats (
            user_id,
            purchases_count,
            total_spent,
            last_purchase_at
        )
        VALUES (?, 0, 0, NULL)
    """, (user.id,))

    conn.commit()
    conn.close()


def update_user_username(user):
    conn = db()

    conn.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            last_name
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name
    """, (
        user.id,
        user.username,
        user.first_name,
        user.last_name
    ))

    conn.execute("""
        INSERT OR IGNORE INTO user_stats (
            user_id,
            purchases_count,
            total_spent,
            last_purchase_at
        )
        VALUES (?, 0, 0, NULL)
    """, (user.id,))

    conn.commit()
    conn.close()


def get_display_name(user_id):
    """
    Возвращает имя пользователя БЕЗ @username.
    """

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT first_name, last_name
        FROM users
        WHERE user_id=?
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    if not row:
        return "Покупатель"

    first_name = (row["first_name"] or "").strip()
    last_name = (row["last_name"] or "").strip()

    name = " ".join(
        part for part in [first_name, last_name]
        if part
    ).strip()

    return name or "Покупатель"


# =========================================================
# ПОСТОЯННАЯ СТАТИСТИКА
# =========================================================

def get_global_stats():
    """
    Возвращает общую статистику магазина.
    """

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*)
        FROM users
    """)
    users = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE status='approved'
    """)
    approved_orders = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(price), 0)
        FROM orders
        WHERE status='approved'
    """)
    revenue = cur.fetchone()[0] or 0

    cur.execute("""
        SELECT COUNT(*)
        FROM orders
    """)
    all_orders = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE status='waiting_check'
    """)
    waiting_checks = cur.fetchone()[0]

    conn.close()

    return {
        "users": users,
        "all_orders": all_orders,
        "approved_orders": approved_orders,
        "revenue": revenue,
        "waiting_checks": waiting_checks
    }


def get_user_stats(user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            purchases_count,
            total_spent,
            last_purchase_at
        FROM user_stats
        WHERE user_id=?
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    if not row:
        return {
            "purchases_count": 0,
            "total_spent": 0,
            "last_purchase_at": None
        }

    return {
        "purchases_count": row["purchases_count"],
        "total_spent": row["total_spent"],
        "last_purchase_at": row["last_purchase_at"]
    }


def get_all_user_stats(limit=100):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            u.user_id,
            u.first_name,
            u.last_name,
            s.purchases_count,
            s.total_spent,
            s.last_purchase_at
        FROM user_stats s
        LEFT JOIN users u
            ON u.user_id = s.user_id
        ORDER BY
            s.total_spent DESC,
            s.purchases_count DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()

    conn.close()

    return rows


# =========================================================
# ЗАКАЗЫ
# =========================================================

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
        INSERT INTO orders (
            user_id,
            username,
            product,
            amount,
            price,
            status,
            wallet
        )
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
            created_at
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


def approve_order_and_update_stats(order_id):
    """
    Одновременно подтверждает заказ и обновляет
    постоянную статистику пользователя.

    Возвращает False, если заказ уже был обработан.
    """

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            user_id,
            price,
            status
        FROM orders
        WHERE id=?
    """, (order_id,))

    order = cur.fetchone()

    if not order:
        conn.close()
        return None

    if order["status"] == "approved":
        conn.close()
        return False

    # Меняем статус заказа.
    cur.execute("""
        UPDATE orders
        SET status='approved'
        WHERE id=?
    """, (order_id,))

    # Создаём статистику, если пользователь новый.
    cur.execute("""
        INSERT OR IGNORE INTO user_stats (
            user_id,
            purchases_count,
            total_spent,
            last_purchase_at
        )
        VALUES (?, 0, 0, NULL)
    """, (order["user_id"],))

    # Увеличиваем количество покупок.
    # Сумма добавляется в постоянную статистику.
    cur.execute("""
        UPDATE user_stats
        SET
            purchases_count = purchases_count + 1,
            total_spent = total_spent + ?,
            last_purchase_at = CURRENT_TIMESTAMP
        WHERE user_id=?
    """, (
        order["price"],
        order["user_id"]
    ))

    conn.commit()

    # Получаем обновлённую статистику.
    cur.execute("""
        SELECT
            purchases_count,
            total_spent,
            last_purchase_at
        FROM user_stats
        WHERE user_id=?
    """, (order["user_id"],))

    stats = cur.fetchone()

    conn.close()

    return {
        "user_id": order["user_id"],
        "price": order["price"],
        "purchases_count": stats["purchases_count"],
        "total_spent": stats["total_spent"],
        "last_purchase_at": stats["last_purchase_at"]
    }


# =========================================================
# ИЗБРАННОЕ
# =========================================================

def is_favorite(user_id, product):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM favorites
        WHERE user_id=? AND product=?
    """, (
        user_id,
        product
    ))

    result = cur.fetchone() is not None

    conn.close()

    return result


def add_favorite(user_id, product):
    conn = db()

    conn.execute("""
        INSERT OR IGNORE INTO favorites
        (user_id, product)
        VALUES (?, ?)
    """, (
        user_id,
        product
    ))

    conn.commit()
    conn.close()


def remove_favorite(user_id, product):
    conn = db()

    conn.execute("""
        DELETE FROM favorites
        WHERE user_id=? AND product=?
    """, (
        user_id,
        product
    ))

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

    result = [
        row["product"]
        for row in cur.fetchall()
    ]

    conn.close()

    return result


# =========================================================
# ЦЕНЫ
# =========================================================

def calculate_stars_custom_price(amount):
    price = Decimal(str(amount)) * Decimal("8.4")

    return int(
        price.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )


def stars_price(amount):
    return get_price(f"stars_{amount}")


def premium_price(months):
    return get_price(f"premium_{months}")


def gram_price(amount):
    return get_price(f"gram_{amount}")


# =========================================================
# ГЛАВНАЯ КЛАВИАТУРА
# =========================================================

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

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


def back_main_keyboard():
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


# =========================================================
# КЛАВИАТУРА МАГАЗИНА
# =========================================================

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


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):
    save_user(message)

    await message.answer(
        "Добро пожаловать в Veylora Shop.\n\n"
        "Выберите нужный раздел:",
        reply_markup=main_keyboard(
            message.from_user.id
        )
    )


# =========================================================
# НАЗАД
# =========================================================

@dp.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    await callback.answer()

    update_user_username(callback.from_user)

    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_keyboard(
            callback.from_user.id
        )
    )


# =========================================================
# МАГАЗИН
# =========================================================

@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    await callback.answer()

    update_user_username(callback.from_user)

    await callback.message.edit_text(
        "🛍 Магазин\n\n"
        "Выберите товар:",
        reply_markup=shop_keyboard()
    )


# =========================================================
# STARS
# =========================================================

@dp.callback_query(F.data == "stars")
async def stars(callback: CallbackQuery):
    await callback.answer()

    buttons = []

    for amount in [50, 100, 200, 300, 400]:
        price = stars_price(amount)

        fav = (
            "🪽"
            if is_favorite(
                callback.from_user.id,
                f"stars_{amount}"
            )
            else ""
        )

        buttons.append([
            InlineKeyboardButton(
                text=f"{fav} {amount} Stars — {price} ₸",
                callback_data=f"buy_stars_{amount}"
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
    if not await check_username_callback(callback):
        return

    update_user_username(callback.from_user)

    await callback.answer()

    amount = int(
        callback.data.split("_")[-1]
    )

    price = stars_price(amount)
    product = f"stars_{amount}"

    favorite_text = (
        "🪽 Убрать из избранного"
        if is_favorite(
            callback.from_user.id,
            product
        )
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
    if not await check_username_callback(callback):
        return

    update_user_username(callback.from_user)

    await callback.answer()

    amount = int(
        callback.data.split("_")[-1]
    )

    price = stars_price(amount)

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


@dp.callback_query(F.data == "custom_stars")
async def custom_stars(
    callback: CallbackQuery,
    state: FSMContext
):
    if not await check_username_callback(callback):
        return

    update_user_username(callback.from_user)

    await callback.answer()

    await state.set_state(
        OrderState.waiting_amount
    )

    await state.update_data(
        type="stars"
    )

    await callback.message.edit_text(
        "Введите количество Stars числом.\n\n"
        "Цена рассчитывается по тарифу "
        "8.4 ₸ за 1 Star."
    )


# =========================================================
# PREMIUM
# =========================================================

@dp.callback_query(F.data == "premium")
async def premium(callback: CallbackQuery):
    await callback.answer()

    buttons = []

    for months in [3, 6, 12]:

        price = premium_price(months)
        product = f"premium_{months}"

        fav = (
            "🪽"
            if is_favorite(
                callback.from_user.id,
                product
            )
            else ""
        )

        buttons.append([
            InlineKeyboardButton(
                text=(
                    f"{fav} {months} мес. — "
                    f"{price} ₸"
                ),
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
    if not await check_username_callback(callback):
        return

    update_user_username(callback.from_user)

    await callback.answer()

    months = int(
        callback.data.split("_")[-1]
    )

    price = premium_price(months)
    product = f"premium_{months}"

    favorite_text = (
        "🪽 Убрать из избранного"
        if is_favorite(
            callback.from_user.id,
            product
        )
        else "🪽 В избранное"
    )

    await callback.message.edit_text(
        f"💎 Telegram Premium\n\n"
        f"Срок: {months} мес.\n"
        f"Цена: {price} ₸",
        reply_markup=InlineKeyboardMarkup(
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
    )


@dp.callback_query(F.data.startswith("confirm_premium_"))
async def confirm_premium(callback: CallbackQuery):
    if not await check_username_callback(callback):
        return

    update_user_username(callback.from_user)

    await callback.answer()

    months = int(
        callback.data.split("_")[-1]
    )

    price = premium_price(months)

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


# =========================================================
# GRAM
# =========================================================

@dp.callback_query(F.data == "gram")
async def gram(callback: CallbackQuery):
    await callback.answer()

    buttons = []

    for amount in [1, 2, 3]:

        price = gram_price(amount)
        product = f"gram_{amount}"

        fav = (
            "🪽"
            if is_favorite(
                callback.from_user.id,
                product
            )
            else ""
        )

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
async def buy_gram(
    callback: CallbackQuery,
    state: FSMContext
):
    if not await check_username_callback(callback):
        return

    update_user_username(callback.from_user)

    await callback.answer()

    amount = int(
        callback.data.split("_")[-1]
    )

    await state.set_state(
        OrderState.waiting_wallet
    )

    await state.update_data(
        type="gram",
        amount=amount
    )

    await callback.message.edit_text(
        f"💠 GRAM: {amount}\n\n"
        "Введите ваш TON-кошелёк "
        "для получения GRAM:"
    )


@dp.callback_query(F.data == "custom_gram")
async def custom_gram(
    callback: CallbackQuery,
    state: FSMContext
):
    if not await check_username_callback(callback):
        return

    update_user_username(callback.from_user)

    await callback.answer()

    await state.set_state(
        OrderState.waiting_amount
    )

    await state.update_data(
        type="gram"
    )

    await callback.message.edit_text(
        "Введите количество GRAM числом.\n\n"
        "Цена: 800 ₸ за 1 GRAM."
    )


# =========================================================
# ВВОД КОЛИЧЕСТВА
# =========================================================

@dp.message(OrderState.waiting_amount)
async def custom_amount(
    message: Message,
    state: FSMContext
):
    if not await check_username_message(message):
        await state.clear()
        return

    save_user(message)

    data = await state.get_data()

    try:
        amount = int(message.text)
    except (ValueError, TypeError):
        await message.answer(
            "Введите количество числом."
        )
        return

    if amount <= 0:
        await message.answer(
            "Количество должно быть больше 0."
        )
        return

    if data.get("type") == "stars":

        price = calculate_stars_custom_price(
            amount
        )

        order_id = create_order(
            message.from_user.id,
            message.from_user.username,
            f"Telegram Stars — {amount}",
            amount,
            price
        )

    elif data.get("type") == "gram":

        price = amount * 800

        order_id = create_order(
            message.from_user.id,
            message.from_user.username,
            f"GRAM — {amount}",
            amount,
            price
        )

    else:
        await state.clear()
        return

    await state.clear()

    await message.answer(
        f"Заказ №{order_id}\n\n"
        f"Количество: {amount}\n"
        f"💰 К оплате: {price} ₸\n\n"
        f"Kaspi:\n{KASPI_NUMBER}\n\n"
        "После оплаты нажмите «Я оплатил».",
        reply_markup=receipt_keyboard(order_id)
    )


# =========================================================
# TON-КОШЕЛЁК
# =========================================================

@dp.message(OrderState.waiting_wallet)
async def wallet_received(
    message: Message,
    state: FSMContext
):
    if not await check_username_message(message):
        await state.clear()
        return

    save_user(message)

    wallet = message.text.strip()

    if len(wallet) < 20:
        await message.answer(
            "Похоже, кошелёк указан неправильно.\n"
            "Отправьте TON-кошелёк ещё раз."
        )
        return

    data = await state.get_data()

    amount = data["amount"]

    price = amount * 800

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


# =========================================================
# ИЗБРАННОЕ
# =========================================================

@dp.callback_query(F.data == "favorites")
async def favorites(callback: CallbackQuery):
    await callback.answer()

    products = get_favorites(
        callback.from_user.id
    )

    if not products:
        await callback.message.edit_text(
            "🪽 Избранное пока пустое.\n\n"
            "Добавляйте товары, чтобы быстро "
            "находить их снова.",
            reply_markup=back_main_keyboard()
        )
        return

    buttons = []

    for product in products:

        if product.startswith("stars_"):

            amount = int(
                product.split("_")[1]
            )

            price = stars_price(amount)

            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"⭐ Stars {amount} — "
                        f"{price} ₸"
                    ),
                    callback_data=f"favopen_{product}"
                )
            ])

        elif product.startswith("premium_"):

            months = int(
                product.split("_")[1]
            )

            price = premium_price(months)

            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"💎 Premium {months} мес. — "
                        f"{price} ₸"
                    ),
                    callback_data=f"favopen_{product}"
                )
            ])

        elif product.startswith("gram_"):

            amount = int(
                product.split("_")[1]
            )

            price = amount * 800

            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"💠 GRAM {amount} — "
                        f"{price} ₸"
                    ),
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
async def toggle_favorite(
    callback: CallbackQuery
):
    product = callback.data.replace(
        "togglefav_",
        ""
    )

    if is_favorite(
        callback.from_user.id,
        product
    ):
        remove_favorite(
            callback.from_user.id,
            product
        )

        await callback.answer(
            "Удалено из избранного."
        )

    else:
        add_favorite(
            callback.from_user.id,
            product
        )

        await callback.answer(
            "Добавлено в избранное."
        )

    await callback.message.edit_reply_markup(
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
                        text="⬅️ Назад",
                        callback_data="favorites"
                    )
                ]
            ]
        )
    )


@dp.callback_query(F.data.startswith("favopen_"))
async def favorite_open(callback: CallbackQuery):
    await callback.answer()

    product = callback.data.replace(
        "favopen_",
        ""
    )

    if product.startswith("stars_"):

        amount = int(
            product.split("_")[1]
        )

        price = stars_price(amount)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 Купить",
                        callback_data=(
                            f"confirm_stars_{amount}"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🗑 Убрать",
                        callback_data=(
                            f"togglefav_{product}"
                        )
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

        await callback.message.edit_text(
            f"⭐ Telegram Stars\n\n"
            f"Количество: {amount}\n"
            f"Цена: {price} ₸",
            reply_markup=keyboard
        )

    elif product.startswith("premium_"):

        months = int(
            product.split("_")[1]
        )

        price = premium_price(months)

        await callback.message.edit_text(
            f"💎 Telegram Premium\n\n"
            f"Срок: {months} мес.\n"
            f"Цена: {price} ₸",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💳 Купить",
                            callback_data=(
                                f"confirm_premium_{months}"
                            )
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🗑 Убрать",
                            callback_data=(
                                f"togglefav_{product}"
                            )
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

        amount = int(
            product.split("_")[1]
        )

        price = amount * 800

        await callback.message.edit_text(
            f"💠 GRAM\n\n"
            f"Количество: {amount}\n"
            f"Цена: {price} ₸",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💳 Купить",
                            callback_data=(
                                f"buy_gram_{amount}"
                            )
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🗑 Убрать",
                            callback_data=(
                                f"togglefav_{product}"
                            )
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


# =========================================================
# ОТЗЫВЫ
# =========================================================

@dp.callback_query(F.data == "reviews")
async def reviews(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "✨ Отзывы Veylora Shop\n\n"
        "Будем очень благодарны за отзыв.\n\n"
        "Оставить его можно в комментариях "
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


# =========================================================
# ОПЛАТА
# =========================================================

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
                    text="⬅️ Назад",
                    callback_data="shop"
                )
            ]
        ]
    )


@dp.callback_query(F.data.startswith("paid_"))
async def paid(
    callback: CallbackQuery,
    state: FSMContext
):
    await callback.answer()

    order_id = int(
        callback.data.split("_")[-1]
    )

    order = get_order(order_id)

    if not order:
        await callback.message.answer(
            "Заказ не найден."
        )
        return

    if order["user_id"] != callback.from_user.id:
        await callback.message.answer(
            "Этот заказ вам не принадлежит."
        )
        return

    await state.set_state(
        OrderState.waiting_receipt
    )

    await state.update_data(
        order_id=order_id
    )

    await callback.message.edit_text(
        f"Заказ №{order_id}\n\n"
        "Отправьте чек об оплате.\n\n"
        "Можно отправить:\n"
        "• фото\n"
        "• PDF-файл"
    )


# =========================================================
# ЧЕК — ФОТО
# =========================================================

@dp.message(
    OrderState.waiting_receipt,
    F.photo
)
async def receipt_photo(
    message: Message,
    state: FSMContext
):
    data = await state.get_data()

    order_id = data["order_id"]
    order = get_order(order_id)

    if not order:
        await state.clear()

        await message.answer(
            "Заказ не найден."
        )
        return

    update_order_status(
        order_id,
        "waiting_check"
    )

    caption = build_admin_order_text(
        order,
        "🧾 Новый чек"
    )

    await bot.send_photo(
        ADMIN_ID,
        message.photo[-1].file_id,
        caption=caption,
        reply_markup=admin_order_keyboard(
            order_id
        )
    )

    await state.clear()

    await message.answer(
        "Чек отправлен на проверку.\n"
        "Ожидайте подтверждения заказа."
    )


# =========================================================
# ЧЕК — PDF
# =========================================================

@dp.message(
    OrderState.waiting_receipt,
    F.document
)
async def receipt_pdf(
    message: Message,
    state: FSMContext
):
    document = message.document

    is_pdf = (
        document.mime_type == "application/pdf"
        or (
            document.file_name
            and document.file_name.lower().endswith(
                ".pdf"
            )
        )
    )

    if not is_pdf:
        await message.answer(
            "Отправьте чек в формате PDF или фото."
        )
        return

    data = await state.get_data()

    order_id = data["order_id"]
    order = get_order(order_id)

    if not order:
        await state.clear()

        await message.answer(
            "Заказ не найден."
        )
        return

    update_order_status(
        order_id,
        "waiting_check"
    )

    caption = build_admin_order_text(
        order,
        "🧾 Новый PDF-чек"
    )

    await bot.send_document(
        ADMIN_ID,
        document.file_id,
        caption=caption,
        reply_markup=admin_order_keyboard(
            order_id
        )
    )

    await state.clear()

    await message.answer(
        "PDF-чек отправлен на проверку.\n"
        "Ожидайте подтверждения."
    )


# =========================================================
# ТЕКСТ ЗАКАЗА ДЛЯ АДМИНА
# =========================================================

def build_admin_order_text(
    order,
    title
):
    text = (
        f"{title}\n\n"
        f"Заказ: #{order['id']}\n"
        f"Пользователь: @{order['username'] or 'нет username'}\n"
        f"ID: {order['user_id']}\n"
        f"Товар: {order['product']}\n"
        f"Сумма: {order['price']} ₸\n"
    )

    if order["wallet"]:
        text += f"Кошелёк: {order['wallet']}\n"

    return text


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


# =========================================================
# ОДОБРЕНИЕ
# =========================================================

@dp.callback_query(F.data.startswith("approve_"))
async def approve(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    order_id = int(
        callback.data.split("_")[-1]
    )

    order = get_order(order_id)

    if not order:
        await callback.answer(
            "Заказ не найден."
        )
        return

    # Если уже одобрен — повторно статистику
    # НЕ увеличиваем.
    if order["status"] == "approved":
        await callback.answer(
            "Заказ уже обработан."
        )
        return

    result = approve_order_and_update_stats(
        order_id
    )

    if result is False:
        await callback.answer(
            "Заказ уже обработан."
        )
        return

    if result is None:
        await callback.answer(
            "Заказ не найден."
        )
        return

    await callback.answer(
        "Заказ одобрен."
    )

    try:
        await callback.message.edit_caption(
            caption=(
                f"✅ Заказ #{order_id} одобрен\n\n"
                f"Товар: {order['product']}\n"
                f"Сумма: {order['price']} ₸"
            )
        )
    except Exception:
        try:
            await callback.message.edit_text(
                f"✅ Заказ #{order_id} одобрен\n\n"
                f"Товар: {order['product']}\n"
                f"Сумма: {order['price']} ₸"
            )
        except Exception:
            pass

    await bot.send_message(
        order["user_id"],
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


# =========================================================
# ОТКЛОНЕНИЕ
# =========================================================

@dp.callback_query(F.data.startswith("reject_"))
async def reject(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    order_id = int(
        callback.data.split("_")[-1]
    )

    order = get_order(order_id)

    if not order:
        return

    if order["status"] == "approved":
        await callback.answer(
            "Одобренный заказ нельзя отклонить.",
            show_alert=True
        )
        return

    update_order_status(
        order_id,
        "rejected"
    )

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

    await bot.send_message(
        order["user_id"],
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


# =========================================================
# МОИ ПОКУПКИ
# =========================================================

@dp.callback_query(F.data == "my_orders")
async def my_orders(callback: CallbackQuery):
    await callback.answer()

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            product,
            price,
            status
        FROM orders
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (
        callback.from_user.id,
    ))

    orders = cur.fetchall()

    conn.close()

    if not orders:
        await callback.message.edit_text(
            "🏦 У вас пока нет покупок.",
            reply_markup=back_main_keyboard()
        )
        return

    text = "🏦 Мои покупки\n\n"
    buttons = []

    for order in orders:

        status_text = {
            "approved": "обработан",
            "rejected": "отклонён",
            "waiting_check": "проверяется",
            "awaiting_payment": "ожидает оплаты"
        }.get(
            order["status"],
            order["status"]
        )

        text += (
            f"№{order['id']} — {order['product']}\n"
            f"{order['price']} ₸ — {status_text}\n\n"
        )

        if order["status"] == "approved":
            buttons.append([
                InlineKeyboardButton(
                    text=f"🔁 Купить снова №{order['id']}",
                    callback_data=f"repeat_{order['id']}"
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_main"
        )
    ])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# =========================================================
# ПОВТОРНАЯ ПОКУПКА
# =========================================================

@dp.callback_query(F.data.startswith("repeat_"))
async def repeat_order(
    callback: CallbackQuery
):
    if not await check_username_callback(callback):
        return

    update_user_username(callback.from_user)

    await callback.answer()

    order_id = int(
        callback.data.split("_")[-1]
    )

    order = get_order(order_id)

    if not order:
        await callback.message.answer(
            "Заказ не найден."
        )
        return

    if order["user_id"] != callback.from_user.id:
        await callback.message.answer(
            "Этот заказ вам не принадлежит."
        )
        return

    new_order_id = create_order(
        callback.from_user.id,
        callback.from_user.username,
        order["product"],
        order["amount"],
        order["price"],
        order["wallet"]
    )

    await callback.message.edit_text(
        f"🔁 Новый заказ №{new_order_id}\n\n"
        f"Товар: {order['product']}\n"
        f"Сумма: {order['price']} ₸\n\n"
        f"Kaspi:\n{KASPI_NUMBER}\n\n"
        "После оплаты нажмите «Я оплатил».",
        reply_markup=receipt_keyboard(
            new_order_id
        )
    )


# =========================================================
# ТАБЛИЦА ЛИДЕРОВ
# =========================================================

@dp.callback_query(F.data == "leaders")
async def leaders(callback: CallbackQuery):
    await callback.answer()

    rows = get_all_user_stats(limit=10)

    # Показываем только пользователей,
    # у которых есть хотя бы одна покупка.
    rows = [
        row for row in rows
        if row["purchases_count"] > 0
    ]

    if not rows:
        await callback.message.edit_text(
            "🏆 Таблица лидеров пока пуста.",
            reply_markup=back_main_keyboard()
        )
        return

    text = "🏆 Таблица лидеров\n\n"

    medals = {
        1: "🥇",
        2: "🥈",
        3: "🥉"
    }

    for index, row in enumerate(rows, 1):

        first_name = (
            row["first_name"] or ""
        ).strip()

        last_name = (
            row["last_name"] or ""
        ).strip()

        name = " ".join(
            part
            for part in [first_name, last_name]
            if part
        ).strip()

        if not name:
            name = "Покупатель"

        prefix = medals.get(
            index,
            f"{index}."
        )

        text += (
            f"{prefix} {name}\n"
            f"   Покупок: {row['purchases_count']}\n"
            f"   Потрачено: {row['total_spent']} ₸\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=back_main_keyboard()
    )


# =========================================================
# ИНСТРУКЦИЯ
# =========================================================

@dp.callback_query(F.data == "instruction")
async def instruction(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "📖 Инструкция\n\n"
        "1. Откройте магазин.\n"
        "2. Выберите товар.\n"
        "3. Убедитесь, что у вас установлен @username.\n"
        "4. Создайте заказ.\n"
        "5. Оплатите указанную сумму.\n"
        "6. Нажмите «Я оплатил».\n"
        "7. Отправьте чек — фото или PDF.\n"
        "8. Дождитесь проверки.\n"
        "9. После подтверждения заказ будет обработан.\n\n"
        "Также доступны:\n"
        "🪽 Избранное\n"
        "🔁 Повторная покупка\n"
        "✨ Отзывы",
        reply_markup=back_main_keyboard()
    )


# =========================================================
# АДМИН-ПАНЕЛЬ
# =========================================================

def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧾 Заказы",
                    callback_data="admin_orders"
                ),
                InlineKeyboardButton(
                    text="🔎 Чеки",
                    callback_data="admin_checks"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Товары",
                    callback_data="admin_products"
                ),
                InlineKeyboardButton(
                    text="💰 Цены",
                    callback_data="admin_prices"
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
                    text="📢 Рассылка",
                    callback_data="admin_broadcast"
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


@dp.callback_query(F.data == "admin")
async def admin(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    await callback.message.edit_text(
        "⚙️ Админ-панель",
        reply_markup=admin_keyboard()
    )


# =========================================================
# АДМИН — ЗАКАЗЫ
# =========================================================

@dp.callback_query(F.data == "admin_orders")
async def admin_orders(
    callback: CallbackQuery
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            username,
            product,
            price,
            status
        FROM orders
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cur.fetchall()

    conn.close()

    if not rows:
        text = "🧾 Заказов пока нет."
    else:
        text = "🧾 Последние заказы\n\n"

        for row in rows:

            status_text = {
                "approved": "✅",
                "rejected": "❌",
                "waiting_check": "🔎",
                "awaiting_payment": "⏳"
            }.get(
                row["status"],
                "•"
            )

            text += (
                f"{status_text} #{row['id']}\n"
                f"@{row['username'] or 'нет username'}\n"
                f"{row['product']}\n"
                f"{row['price']} ₸\n\n"
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


# =========================================================
# АДМИН — ПРОВЕРКА ЧЕКОВ
# =========================================================

@dp.callback_query(F.data == "admin_checks")
async def admin_checks(
    callback: CallbackQuery
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            username,
            product,
            price
        FROM orders
        WHERE status='waiting_check'
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cur.fetchall()

    conn.close()

    if not rows:
        text = "🔎 Сейчас чеков на проверке нет."
    else:
        text = "🔎 Чеки на проверке\n\n"

        for row in rows:
            text += (
                f"#{row['id']}\n"
                f"@{row['username'] or 'нет username'}\n"
                f"{row['product']} — {row['price']} ₸\n\n"
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


# =========================================================
# АДМИН — ТОВАРЫ
# =========================================================

@dp.callback_query(F.data == "admin_products")
async def admin_products(
    callback: CallbackQuery
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    text = (
        "📦 Товары\n\n"
        "⭐ Stars\n"
        "50 / 100 / 200 / 300 / 400\n\n"
        "💎 Premium\n"
        "3 / 6 / 12 месяцев\n\n"
        "💠 GRAM\n"
        "1 / 2 / 3"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💰 Изменить цены",
                        callback_data="admin_prices"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="admin"
                    )
                ]
            ]
        )
    )


# =========================================================
# АДМИН — ЦЕНЫ
# =========================================================

@dp.callback_query(F.data == "admin_prices")
async def admin_prices(
    callback: CallbackQuery
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    buttons = [
        [
            InlineKeyboardButton(
                text="⭐ Stars 50",
                callback_data="editprice_stars_50"
            ),
            InlineKeyboardButton(
                text="100",
                callback_data="editprice_stars_100"
            )
        ],
        [
            InlineKeyboardButton(
                text="⭐ Stars 200",
                callback_data="editprice_stars_200"
            ),
            InlineKeyboardButton(
                text="300",
                callback_data="editprice_stars_300"
            )
        ],
        [
            InlineKeyboardButton(
                text="⭐ Stars 400",
                callback_data="editprice_stars_400"
            )
        ],
        [
            InlineKeyboardButton(
                text="💎 Premium 3",
                callback_data="editprice_premium_3"
            ),
            InlineKeyboardButton(
                text="6",
                callback_data="editprice_premium_6"
            )
        ],
        [
            InlineKeyboardButton(
                text="💎 Premium 12",
                callback_data="editprice_premium_12"
            )
        ],
        [
            InlineKeyboardButton(
                text="💠 GRAM 1",
                callback_data="editprice_gram_1"
            ),
            InlineKeyboardButton(
                text="2",
                callback_data="editprice_gram_2"
            )
        ],
        [
            InlineKeyboardButton(
                text="💠 GRAM 3",
                callback_data="editprice_gram_3"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="admin"
            )
        ]
    ]

    await callback.message.edit_text(
        "💰 Изменение цен\n\n"
        "Выберите товар:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data.startswith("editprice_"))
async def edit_price_start(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    key = callback.data.replace(
        "editprice_",
        ""
    )

    await state.set_state(
        PriceState.waiting_price
    )

    await state.update_data(
        price_key=key
    )

    current = get_price(key)

    await callback.message.edit_text(
        f"Текущая цена: {current} ₸\n\n"
        "Введите новую цену числом:"
    )


@dp.message(PriceState.waiting_price)
async def edit_price_received(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        price = int(message.text)
    except (ValueError, TypeError):
        await message.answer(
            "Введите цену числом."
        )
        return

    if price <= 0:
        await message.answer(
            "Цена должна быть больше 0."
        )
        return

    data = await state.get_data()

    key = data["price_key"]

    set_setting(
        key,
        price
    )

    await state.clear()

    await message.answer(
        f"Цена изменена.\n\n"
        f"{key}: {price} ₸",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💰 К ценам",
                        callback_data="admin_prices"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚙️ Админ-панель",
                        callback_data="admin"
                    )
                ]
            ]
        )
    )


# =========================================================
# АДМИН — ПОСТОЯННАЯ СТАТИСТИКА
# =========================================================

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(
    callback: CallbackQuery
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    # Перед показом дополнительно синхронизируем
    # постоянную статистику со всей историей заказов.
    conn = db()
    rebuild_user_stats(conn)

    stats = get_global_stats()

    conn.close()

    await callback.message.edit_text(
        "📊 ПОСТОЯННАЯ СТАТИСТИКА\n\n"
        f"👥 Всего пользователей: "
        f"{stats['users']}\n\n"
        f"🛍 Всего заказов: "
        f"{stats['all_orders']}\n"
        f"✅ Оплаченных заказов: "
        f"{stats['approved_orders']}\n"
        f"🔎 Чеков на проверке: "
        f"{stats['waiting_checks']}\n\n"
        f"💰 Общая выручка: "
        f"{stats['revenue']} ₸\n\n"
        "🏆 Количество покупок каждого пользователя "
        "сохраняется отдельно.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏆 Покупатели",
                        callback_data="admin_buyer_stats"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="admin"
                    )
                ]
            ]
        )
    )


# =========================================================
# АДМИН — СТАТИСТИКА ПОКУПАТЕЛЕЙ
# =========================================================

@dp.callback_query(F.data == "admin_buyer_stats")
async def admin_buyer_stats(
    callback: CallbackQuery
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    rows = get_all_user_stats(limit=50)

    rows = [
        row
        for row in rows
        if row["purchases_count"] > 0
    ]

    if not rows:
        await callback.message.edit_text(
            "🏆 Пока нет пользователей "
            "с одобренными покупками.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data="admin_stats"
                        )
                    ]
                ]
            )
        )
        return

    text = "🏆 ПОКУПАТЕЛИ\n\n"

    for index, row in enumerate(rows, 1):

        first_name = (
            row["first_name"] or ""
        ).strip()

        last_name = (
            row["last_name"] or ""
        ).strip()

        name = " ".join(
            part
            for part in [first_name, last_name]
            if part
        ).strip()

        if not name:
            name = "Покупатель"

        text += (
            f"{index}. {name}\n"
            f"Покупок: {row['purchases_count']}\n"
            f"Потрачено: {row['total_spent']} ₸\n"
        )

        if row["last_purchase_at"]:
            text += (
                f"Последняя покупка: "
                f"{row['last_purchase_at']}\n"
            )

        text += "\n"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="admin_stats"
                    )
                ]
            ]
        )
    )


# =========================================================
# АДМИН — ПОЛЬЗОВАТЕЛИ
# =========================================================

@dp.callback_query(F.data == "admin_users")
async def admin_users(
    callback: CallbackQuery
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    stats = get_global_stats()

    await callback.message.edit_text(
        "👥 Пользователи\n\n"
        f"Всего пользователей: "
        f"{stats['users']}\n\n"
        "Статистика покупателей хранится "
        "отдельно и не сбрасывается.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏆 Статистика покупателей",
                        callback_data="admin_buyer_stats"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="admin"
                    )
                ]
            ]
        )
    )


# =========================================================
# АДМИН — РАССЫЛКА
# =========================================================

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа."
        )
        return

    await callback.answer()

    await state.set_state(
        BroadcastState.waiting_text
    )

    await callback.message.edit_text(
        "📢 Рассылка\n\n"
        "Отправьте текст сообщения, "
        "которое нужно отправить пользователям."
    )


@dp.message(BroadcastState.waiting_text)
async def broadcast_received(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text

    if not text:
        await message.answer(
            "Нужен текст сообщения."
        )
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users"
    )

    users = [
        row["user_id"]
        for row in cur.fetchall()
    ]

    conn.close()

    success = 0
    failed = 0

    await message.answer(
        f"Начинаю рассылку.\n"
        f"Пользователей: {len(users)}"
    )

    for user_id in users:

        try:
            await bot.send_message(
                user_id,
                text
            )

            success += 1

        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    await state.clear()

    await message.answer(
        "📢 Рассылка завершена.\n\n"
        f"Отправлено: {success}\n"
        f"Не доставлено: {failed}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⚙️ Админ-панель",
                        callback_data="admin"
                    )
                ]
            ]
        )
    )


# =========================================================
# ЗАПУСК
# =========================================================

async def main():
    print("Veylora Shop Bot запущен")
    print(f"База данных: {DB_NAME}")

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":
    asyncio.run(main())

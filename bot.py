import asyncio
import os
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

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
KASPI_NUMBER = os.getenv("KASPI_NUMBER", "Не указан")

SHOP_NAME = "Veylora Shop"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =========================
# СОСТОЯНИЯ
# =========================

class CustomQuantity(StatesGroup):
    stars = State()
    gram = State()


# =========================
# ЗАКАЗЫ
# =========================

orders = {}
user_orders = {}

order_counter = 1000


def create_order(user_id, product, quantity, price):
    global order_counter

    order_counter += 1
    order_id = order_counter

    orders[order_id] = {
        "user_id": user_id,
        "product": product,
        "quantity": quantity,
        "price": price,
        "status": "awaiting_payment",
        "receipt": None,
    }

    user_orders.setdefault(user_id, [])
    user_orders[user_id].append(order_id)

    return order_id


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
                    text="📦 Мои покупки",
                    callback_data="orders"
                )
            ],
            [
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
                InlineKeyboardButton(text="50 Stars — 420 ₸", callback_data="stars_50"),
            ],
            [
                InlineKeyboardButton(text="100 Stars — 840 ₸", callback_data="stars_100"),
            ],
            [
                InlineKeyboardButton(text="200 Stars — 1680 ₸", callback_data="stars_200"),
            ],
            [
                InlineKeyboardButton(text="300 Stars — 2520 ₸", callback_data="stars_300"),
            ],
            [
                InlineKeyboardButton(text="400 Stars — 3360 ₸", callback_data="stars_400"),
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
        "🛍 Магазин\n\nВыберите категорию:",
        reply_markup=shop_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "category_stars")
async def stars(callback: CallbackQuery):
    await callback.message.edit_text(
        "⭐ Telegram Stars\n\n"
        "Выберите количество:",
        reply_markup=stars_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "category_premium")
async def premium(callback: CallbackQuery):
    await callback.message.edit_text(
        "💎 Telegram Premium\n\n"
        "Выберите срок:",
        reply_markup=premium_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "category_gram")
async def gram(callback: CallbackQuery):
    await callback.message.edit_text(
        "💠 GRAM\n\n"
        "Выберите количество:",
        reply_markup=gram_keyboard()
    )
    await callback.answer()


# =========================
# ПОКУПКА
# =========================

async def show_payment(
    message,
    user_id,
    product,
    quantity,
    price
):
    order_id = create_order(
        user_id=user_id,
        product=product,
        quantity=quantity,
        price=price
    )

    await message.answer(
        f"🧾 Заказ #{order_id}\n\n"
        f"Товар: {product}\n"
        f"Количество: {quantity}\n"
        f"Стоимость: {price} ₸\n\n"
        f"💳 Оплата через Kaspi:\n"
        f"{KASPI_NUMBER}\n\n"
        "После перевода нажмите «Я оплатил» "
        "и отправьте фото чека.",
        reply_markup=payment_keyboard(order_id)
    )


# =========================
# STARS
# =========================

@dp.callback_query(F.data.startswith("stars_"))
async def stars_purchase(callback: CallbackQuery):
    quantity = int(callback.data.split("_")[1])

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
        callback.from_user.id,
        "Telegram Stars",
        quantity,
        price
    )

    await callback.answer()


# =========================
# PREMIUM
# =========================

@dp.callback_query(F.data.startswith("premium_"))
async def premium_purchase(callback: CallbackQuery):
    months = int(callback.data.split("_")[1])

    prices = {
        3: 6400,
        6: 8400,
        12: 15400,
    }

    price = prices[months]

    await show_payment(
        callback.message,
        callback.from_user.id,
        "Telegram Premium",
        f"{months} месяцев",
        price
    )

    await callback.answer()


# =========================
# GRAM
# =========================

@dp.callback_query(F.data.startswith("gram_"))
async def gram_purchase(callback: CallbackQuery):
    quantity = int(callback.data.split("_")[1])
    price = quantity * 780

    await show_payment(
        callback.message,
        callback.from_user.id,
        "GRAM",
        quantity,
        price
    )

    await callback.answer()


# =========================
# СВОЁ КОЛИЧЕСТВО STARS
# =========================

@dp.callback_query(F.data == "custom_stars")
async def custom_stars(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomQuantity.stars)

    await callback.message.answer(
        "Введите количество Stars числом.\n\n"
        "Например: 55, 75, 101"
    )

    await callback.answer()


@dp.message(CustomQuantity.stars)
async def custom_stars_amount(message: Message, state: FSMContext):
    try:
        quantity = int(message.text.strip())

        if quantity <= 0:
            raise ValueError

        # 8.4 ₸ за 1 Star
        raw_price = Decimal(quantity) * Decimal("8.4")
        price = int(
            raw_price.quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP
            )
        )

        await state.clear()

        await show_payment(
            message,
            message.from_user.id,
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
# СВОЁ КОЛИЧЕСТВО GRAM
# =========================

@dp.callback_query(F.data == "custom_gram")
async def custom_gram(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomQuantity.gram)

    await callback.message.answer(
        "Введите количество GRAM числом.\n\n"
        "Например: 4, 5, 10"
    )

    await callback.answer()


@dp.message(CustomQuantity.gram)
async def custom_gram_amount(message: Message, state: FSMContext):
    try:
        quantity = int(message.text.strip())

        if quantity <= 0:
            raise ValueError

        price = quantity * 780

        await state.clear()

        await show_payment(
            message,
            message.from_user.id,
            "GRAM",
            quantity,
            price
        )

    except ValueError:
        await message.answer(
            "Введите целое число больше 0.\n"
            "Например: 5"
        )


# =========================
# Я ОПЛАТИЛ
# =========================

@dp.callback_query(F.data.startswith("paid_"))
async def paid(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])

    if order_id not in orders:
        await callback.answer(
            "Заказ не найден.",
            show_alert=True
        )
        return

    order = orders[order_id]

    if order["user_id"] != callback.from_user.id:
        await callback.answer(
            "Это не ваш заказ.",
            show_alert=True
        )
        return

    order["status"] = "waiting_receipt"

    await callback.message.answer(
        f"Заказ #{order_id}\n\n"
        "Теперь отправьте сюда фото чека Kaspi.\n"
        "После проверки администратор подтвердит заказ."
    )

    await callback.answer()


# =========================
# ЧЕК
# =========================

@dp.message(F.photo)
async def receipt(message: Message):
    user_id = message.from_user.id

    user_order_ids = user_orders.get(user_id, [])

    active_order = None

    for order_id in reversed(user_order_ids):
        order = orders.get(order_id)

        if order and order["status"] == "waiting_receipt":
            active_order = order_id
            break

    if not active_order:
        await message.answer(
            "Сначала оформите заказ в магазине."
        )
        return

    order = orders[active_order]

    order["receipt"] = message.photo[-1].file_id
    order["status"] = "checking"

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "без username"
    )

    admin_text = (
        f"🧾 НОВЫЙ ЗАКАЗ #{active_order}\n\n"
        f"👤 Пользователь: {username}\n"
        f"🆔 ID: {user_id}\n\n"
        f"📦 Товар: {order['product']}\n"
        f"🔢 Количество: {order['quantity']}\n"
        f"💰 Сумма: {order['price']} ₸\n\n"
        "Проверьте оплату по чеку."
    )

    await bot.send_photo(
        ADMIN_ID,
        order["receipt"],
        caption=admin_text,
        reply_markup=admin_order_keyboard(active_order)
    )

    await message.answer(
        f"Чек по заказу #{active_order} отправлен администратору.\n\n"
        "Ожидайте подтверждения."
    )


# =========================
# ПОДТВЕРЖДЕНИЕ АДМИНОМ
# =========================

@dp.callback_query(F.data.startswith("approve_"))
async def approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    order_id = int(callback.data.split("_")[1])

    if order_id not in orders:
        await callback.answer(
            "Заказ не найден.",
            show_alert=True
        )
        return

    order = orders[order_id]
    order["status"] = "approved"

    user_id = order["user_id"]

    await bot.send_message(
        user_id,
        f"✅ Заказ #{order_id} подтверждён.\n\n"
        f"Товар: {order['product']}\n"
        f"Количество: {order['quantity']}\n\n"
        "Оплата подтверждена."
    )

    await callback.message.edit_caption(
        caption=(
            f"✅ ЗАКАЗ #{order_id} ПОДТВЕРЖДЁН\n\n"
            f"Товар: {order['product']}\n"
            f"Количество: {order['quantity']}\n"
            f"Сумма: {order['price']} ₸"
        )
    )

    await callback.answer("Заказ подтверждён.")


@dp.callback_query(F.data.startswith("reject_"))
async def reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    order_id = int(callback.data.split("_")[1])

    if order_id not in orders:
        await callback.answer(
            "Заказ не найден.",
            show_alert=True
        )
        return

    order = orders[order_id]
    order["status"] = "rejected"

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

    await callback.answer("Заказ отклонён.")


# =========================
# МОИ ПОКУПКИ
# =========================

@dp.callback_query(F.data == "orders")
async def my_orders(callback: CallbackQuery):
    user_id = callback.from_user.id
    order_ids = user_orders.get(user_id, [])

    if not order_ids:
        await callback.message.edit_text(
            "📦 У вас пока нет заказов.",
            reply_markup=main_keyboard()
        )
        await callback.answer()
        return

    text = "📦 Ваши заказы:\n\n"

    for order_id in order_ids[-10:]:
        order = orders[order_id]

        status_names = {
            "awaiting_payment": "Ожидает оплаты",
            "waiting_receipt": "Ожидает чек",
            "checking": "Проверяется",
            "approved": "Подтверждён",
            "rejected": "Отклонён",
        }

        status = status_names.get(
            order["status"],
            order["status"]
        )

        text += (
            f"#{order_id} — {order['product']}\n"
            f"Количество: {order['quantity']}\n"
            f"Сумма: {order['price']} ₸\n"
            f"Статус: {status}\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=main_keyboard()
    )

    await callback.answer()


# =========================
# ПОДДЕРЖКА
# =========================

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    await callback.message.edit_text(
        "💬 Поддержка\n\n"
        "Если возникла проблема с заказом, "
        "напишите администратору."
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

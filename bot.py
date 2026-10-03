import asyncio
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
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

# СЮДА ПОТОМ ВПИШЕШЬ СВОЙ TELEGRAM ID
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# СЮДА ПОТОМ ВПИШЕШЬ НОМЕР KASPI
KASPI_NUMBER = os.getenv("KASPI_NUMBER", "УКАЖИ НОМЕР KASPI")

SHOP_NAME = "Veylora Shop"

dp = Dispatcher()


# =========================
# ТОВАРЫ
# =========================

PRODUCTS = {
    "stars": {
        "name": "Telegram Stars",
        "items": {
            "stars_100": ("100 Stars", 1000),
            "stars_250": ("250 Stars", 2200),
            "stars_500": ("500 Stars", 4000),
        },
    },

    "premium": {
        "name": "Telegram Premium",
        "items": {
            "premium_1": ("Premium — 1 месяц", 2500),
            "premium_3": ("Premium — 3 месяца", 6500),
        },
    },

    "gifts": {
        "name": "Подарки",
        "items": {
            "gift_1": ("Подарок №1", 1000),
            "gift_2": ("Подарок №2", 2000),
        },
    },
}


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
                    text="🎁 Подарки",
                    callback_data="category_gifts"
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


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):

    await message.answer(
        f"Добро пожаловать в {SHOP_NAME}!\n\n"
        "Здесь ты можешь выбрать нужный товар.\n\n"
        "Выбери раздел:",
        reply_markup=main_keyboard(),
    )


# =========================
# МАГАЗИН
# =========================

@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):

    await callback.message.edit_text(
        "🛍 Veylora Shop\n\n"
        "Выбери категорию:",
        reply_markup=shop_keyboard(),
    )

    await callback.answer()


# =========================
# КАТЕГОРИИ
# =========================

@dp.callback_query(F.data.startswith("category_"))
async def category(callback: CallbackQuery):

    category_name = callback.data.replace("category_", "")

    category_data = PRODUCTS.get(category_name)

    if not category_data:
        await callback.answer("Категория не найдена")
        return

    buttons = []

    for product_id, product_data in category_data["items"].items():

        product_name, price = product_data

        buttons.append([
            InlineKeyboardButton(
                text=f"{product_name} — {price} ₸",
                callback_data=f"product_{product_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="shop"
        )
    ])

    await callback.message.edit_text(
        f"{category_data['name']}\n\n"
        "Выбери товар:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
    )

    await callback.answer()


# =========================
# ТОВАР
# =========================

@dp.callback_query(F.data.startswith("product_"))
async def product(callback: CallbackQuery):

    product_id = callback.data.replace("product_", "")

    found_product = None

    for category in PRODUCTS.values():

        if product_id in category["items"]:

            found_product = category["items"][product_id]

            break

    if not found_product:

        await callback.answer("Товар не найден")
        return

    product_name, price = found_product

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Оплатить через Kaspi",
                    callback_data=f"pay_{product_id}"
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

    await callback.message.edit_text(
        f"🛍 {product_name}\n\n"
        f"Цена: {price} ₸\n\n"
        "Нажми кнопку ниже, чтобы получить реквизиты для оплаты.",
        reply_markup=keyboard,
    )

    await callback.answer()


# =========================
# ОПЛАТА KASPI
# =========================

@dp.callback_query(F.data.startswith("pay_"))
async def payment(callback: CallbackQuery):

    product_id = callback.data.replace("pay_", "")

    found_product = None

    for category in PRODUCTS.values():

        if product_id in category["items"]:

            found_product = category["items"][product_id]

            break

    if not found_product:

        await callback.answer("Товар не найден")
        return

    product_name, price = found_product

    await callback.message.edit_text(
        f"💳 Оплата заказа\n\n"
        f"Товар: {product_name}\n"
        f"Сумма: {price} ₸\n\n"
        f"Переведи {price} ₸ на Kaspi:\n\n"
        f"📱 {KASPI_NUMBER}\n\n"
        "После оплаты нажми кнопку ниже и отправь чек.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Я оплатил",
                        callback_data=f"paid_{product_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data=f"product_{product_id}"
                    )
                ],
            ]
        ),
    )

    await callback.answer()


# =========================
# ПОЛЬЗОВАТЕЛЬ ОПЛАТИЛ
# =========================

@dp.callback_query(F.data.startswith("paid_"))
async def paid(callback: CallbackQuery):

    product_id = callback.data.replace("paid_", "")

    found_product = None

    for category in PRODUCTS.values():

        if product_id in category["items"]:

            found_product = category["items"][product_id]

            break

    if not found_product:

        await callback.answer("Товар не найден")
        return

    product_name, price = found_product

    await callback.message.answer(
        f"Заказ создан.\n\n"
        f"Товар: {product_name}\n"
        f"Сумма: {price} ₸\n\n"
        "Теперь отправь сюда скриншот или фото чека "
        "об оплате."
    )

    await callback.answer()


# =========================
# ПОЛУЧЕНИЕ ЧЕКА
# =========================

@dp.message(F.photo)
async def receipt_photo(message: Message):

    if ADMIN_ID == 0:
        return

    user = message.from_user

    username = (
        f"@{user.username}"
        if user.username
        else "без username"
    )

    await message.bot.send_message(
        ADMIN_ID,
        "🔔 Новый чек на проверку!\n\n"
        f"Пользователь: {username}\n"
        f"ID: {user.id}\n\n"
        "Проверь оплату вручную."
    )

    await message.bot.send_photo(
        ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption="Чек пользователя"
    )

    await message.answer(
        "Чек отправлен на проверку.\n\n"
        "После проверки с тобой свяжутся."
    )


# =========================
# МОИ ПОКУПКИ
# =========================

@dp.callback_query(F.data == "orders")
async def orders(callback: CallbackQuery):

    await callback.message.edit_text(
        "📦 Мои покупки\n\n"
        "История покупок пока пуста.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="back"
                    )
                ]
            ]
        ),
    )

    await callback.answer()


# =========================
# ПОДДЕРЖКА
# =========================

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):

    await callback.message.edit_text(
        "💬 Поддержка\n\n"
        "По вопросам заказа напиши администратору:\n"
        "@deecoller",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="back"
                    )
                ]
            ]
        ),
    )

    await callback.answer()


# =========================
# НАЗАД
# =========================

@dp.callback_query(F.data == "back")
async def back(callback: CallbackQuery):

    await callback.message.edit_text(
        f"Добро пожаловать в {SHOP_NAME}!\n\n"
        "Выбери нужный раздел:",
        reply_markup=main_keyboard(),
    )

    await callback.answer()


# =========================
# ЗАПУСК
# =========================

async def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не установлен"
        )

    bot = Bot(BOT_TOKEN)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

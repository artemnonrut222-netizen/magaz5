#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAWWEAR Telegram Shop Bot - ИСПРАВЛЕННАЯ ВЕРСИЯ
"""

import logging
import os
import sqlite3
import traceback
from contextlib import contextmanager
from typing import List, Optional, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto, ParseMode
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, MessageHandler, 
    Filters, CallbackContext, ConversationHandler
)
from telegram.error import TelegramError, BadRequest
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set in environment")

ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()]

BOT_AVATAR_FILE_ID = os.getenv("BOT_AVATAR_FILE_ID", "")
DATABASE = "shop.db"

# -------------------- LOGGING --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# -------------------- ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК --------------------
def error_handler(update: Update, context: CallbackContext):
    """Глобальный обработчик ошибок"""
    try:
        raise context.error
    except Exception as e:
        logger.error(f"Unhandled error: {e}\n{traceback.format_exc()}")
        
        # Пытаемся уведомить пользователя
        try:
            if update and update.effective_chat:
                context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Произошла внутренняя ошибка. Попробуйте позже или напишите @matpluuux"
                )
        except:
            pass
        
        # Уведомляем админов
        for admin_id in ADMIN_IDS:
            try:
                context.bot.send_message(
                    chat_id=admin_id,
                    text=f"❌ Критическая ошибка:\n{str(e)[:200]}"
                )
            except:
                pass

# -------------------- СОСТОЯНИЯ --------------------
(
    CATEGORY_SELECTION, SUBCATEGORY_SELECTION, ADD_PRODUCT_NAME, 
    ADD_PRODUCT_DESCRIPTION, ADD_PRODUCT_PRICE, ADD_PRODUCT_SIZES, 
    ADD_PRODUCT_PHOTO, CHECKOUT_CONTACT, CHECKOUT_ADDRESS, 
    CHECKOUT_COMMENT, CHECKOUT_CONFIRM, SEARCH_QUERY,
    MAILING_TEXT, MAILING_CONFIRM, ORDER_REJECT_REASON
) = range(15)

# -------------------- СТАТУСЫ ЗАКАЗОВ --------------------
ORDER_STATUSES = {
    'new': '🟡 На модерации',
    'approved': '✅ Одобрен',
    'rejected': '❌ Отклонён'
}

# -------------------- ИНИЦИАЛИЗАЦИЯ БД --------------------
@contextmanager
def db_connection():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def init_db():
    """Создание таблиц если их нет"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()

            # Пользователи
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Категории
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
            """)

            # Подкатегории
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subcategories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    UNIQUE(category_id, name),
                    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
                )
            """)

            # Товары
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    price INTEGER NOT NULL,
                    sizes TEXT,
                    subcategory_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (subcategory_id) REFERENCES subcategories(id) ON DELETE SET NULL
                )
            """)

            # Изображения товаров
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    file_id TEXT NOT NULL,
                    position INTEGER DEFAULT 0,
                    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
                )
            """)

            # Корзина
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cart (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    size TEXT,
                    quantity INTEGER DEFAULT 1,
                    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
                )
            """)

            # Заказы
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'new',
                    total_price INTEGER NOT NULL,
                    contact TEXT,
                    address TEXT,
                    comment TEXT,
                    reject_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Позиции заказа
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    size TEXT,
                    quantity INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
            """)

            # Сообщения пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Индексы
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cart_user ON cart(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_product_images_product ON product_images(product_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_subcategory ON products(subcategory_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_messages_user ON user_messages(user_id)")

            # Заполнение начальными данными
            for cat_name in ['Одежда', 'Обувь', 'Аксессуары']:
                cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat_name,))

            cursor.execute("SELECT id, name FROM categories")
            cat_map = {row['name']: row['id'] for row in cursor.fetchall()}

            clothes_subs = [
                ('Куртки', cat_map['Одежда']),
                ('Джинсы/Брюки', cat_map['Одежда']),
                ('Футболки/Майки', cat_map['Одежда']),
                ('Худи/Зипки', cat_map['Одежда']),
                ('Свитшоты/Лонгсливы', cat_map['Одежда']),
                ('Шорты', cat_map['Одежда']),
                ('Свитеры', cat_map['Одежда'])
            ]
            shoes_subs = [
                ('Кроссовки', cat_map['Обувь']),
                ('Кеды', cat_map['Обувь']),
                ('Прочее', cat_map['Обувь'])
            ]
            accessories_subs = [
                ('Шапки', cat_map['Аксессуары']),
                ('Очки', cat_map['Аксессуары']),
                ('Ремни', cat_map['Аксессуары']),
                ('Сумки', cat_map['Аксессуары']),
                ('Кепки', cat_map['Аксессуары']),
                ('Рюкзаки', cat_map['Аксессуары']),
                ('Украшения', cat_map['Аксессуары'])
            ]

            for sub_name, cat_id in clothes_subs + shoes_subs + accessories_subs:
                cursor.execute(
                    "INSERT OR IGNORE INTO subcategories (category_id, name) VALUES (?, ?)",
                    (cat_id, sub_name)
                )

            # Удаление дублей
            cursor.execute("""
                DELETE FROM subcategories
                WHERE id NOT IN (
                    SELECT MIN(id) FROM subcategories GROUP BY category_id, name
                )
            """)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

# -------------------- ФУНКЦИИ ДЛЯ РАБОТЫ С СООБЩЕНИЯМИ --------------------
def save_message(user_id: int, chat_id: int, message_id: int, message_type: str = "regular"):
    """Сохраняет ID сообщения для возможного удаления"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_messages (user_id, message_id, chat_id, message_type) VALUES (?, ?, ?, ?)",
                (user_id, message_id, chat_id, message_type)
            )
    except Exception as e:
        logger.error(f"Failed to save message: {e}")

def delete_user_messages(user_id: int, message_type: str = None):
    """Удаляет все сообщения пользователя определенного типа"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            if message_type:
                cursor.execute(
                    "SELECT chat_id, message_id FROM user_messages WHERE user_id = ? AND message_type = ?",
                    (user_id, message_type)
                )
            else:
                cursor.execute(
                    "SELECT chat_id, message_id FROM user_messages WHERE user_id = ?",
                    (user_id,)
                )
            messages = cursor.fetchall()
            
            if message_type:
                cursor.execute(
                    "DELETE FROM user_messages WHERE user_id = ? AND message_type = ?",
                    (user_id, message_type)
                )
            else:
                cursor.execute("DELETE FROM user_messages WHERE user_id = ?", (user_id,))
            
            return messages
    except Exception as e:
        logger.error(f"Failed to delete messages: {e}")
        return []

# -------------------- ОСНОВНЫЕ ФУНКЦИИ БД --------------------
def add_user(telegram_id: int, username: str = None):
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?, ?)",
                (telegram_id, username)
            )
    except Exception as e:
        logger.error(f"Failed to add user: {e}")

def get_all_products(offset: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, price FROM products ORDER BY name LIMIT ? OFFSET ?",
                (limit, offset)
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get all products: {e}")
        return []

def get_product(product_id: int) -> Optional[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, description, price, sizes, subcategory_id FROM products WHERE id = ?",
                (product_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get product {product_id}: {e}")
        return None

def add_product(name: str, description: str, price: int, sizes: str, subcategory_id: Optional[int] = None) -> Optional[int]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO products (name, description, price, sizes, subcategory_id) VALUES (?, ?, ?, ?, ?)",
                (name, description, price, sizes, subcategory_id)
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to add product: {e}")
        return None

def delete_product(product_id: int):
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    except Exception as e:
        logger.error(f"Failed to delete product {product_id}: {e}")

def add_product_image(product_id: int, file_id: str, position: int = 0):
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO product_images (product_id, file_id, position) VALUES (?, ?, ?)",
                (product_id, file_id, position)
            )
    except Exception as e:
        logger.error(f"Failed to add product image: {e}")

def get_product_images(product_id: int) -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, file_id, position FROM product_images WHERE product_id = ? ORDER BY position",
                (product_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get product images: {e}")
        return []

def delete_product_images(product_id: int):
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM product_images WHERE product_id = ?", (product_id,))
    except Exception as e:
        logger.error(f"Failed to delete product images: {e}")

def search_products(query: str, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, price FROM products WHERE name LIKE ? ORDER BY name LIMIT ? OFFSET ?",
                (f"%{query}%", limit, offset)
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to search products: {e}")
        return []

def count_search_products(query: str) -> int:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products WHERE name LIKE ?", (f"%{query}%",))
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Failed to count search products: {e}")
        return 0

def get_cart(user_id: int) -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cart.id, cart.product_id, cart.size, cart.quantity,
                       products.name, products.price
                FROM cart
                JOIN products ON cart.product_id = products.id
                WHERE cart.user_id = ?
            """, (user_id,))
            rows = cursor.fetchall()
            cart_items = []
            for row in rows:
                item = dict(row)
                item['total'] = item['price'] * item['quantity']
                cart_items.append(item)
            return cart_items
    except Exception as e:
        logger.error(f"Failed to get cart: {e}")
        return []

def add_to_cart(user_id: int, product_id: int, size: str = None) -> bool:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            product = get_product(product_id)
            if not product:
                return False
            cursor.execute(
                "SELECT id, quantity FROM cart WHERE user_id = ? AND product_id = ? AND size IS ?",
                (user_id, product_id, size)
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE cart SET quantity = quantity + 1 WHERE id = ?",
                    (existing['id'],)
                )
            else:
                cursor.execute(
                    "INSERT INTO cart (user_id, product_id, size) VALUES (?, ?, ?)",
                    (user_id, product_id, size)
                )
            return True
    except Exception as e:
        logger.error(f"Failed to add to cart: {e}")
        return False

def update_cart_quantity(cart_item_id: int, delta: int) -> bool:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT quantity FROM cart WHERE id = ?", (cart_item_id,))
            row = cursor.fetchone()
            if not row:
                return False
            new_qty = row['quantity'] + delta
            if new_qty <= 0:
                cursor.execute("DELETE FROM cart WHERE id = ?", (cart_item_id,))
            else:
                cursor.execute("UPDATE cart SET quantity = ? WHERE id = ?", (new_qty, cart_item_id))
            return True
    except Exception as e:
        logger.error(f"Failed to update cart quantity: {e}")
        return False

def remove_from_cart(cart_item_id: int):
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cart WHERE id = ?", (cart_item_id,))
    except Exception as e:
        logger.error(f"Failed to remove from cart: {e}")

def clear_cart(user_id: int):
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
    except Exception as e:
        logger.error(f"Failed to clear cart: {e}")

def create_order(user_id: int, contact: str, address: str, comment: str = "") -> Optional[int]:
    try:
        cart_items = get_cart(user_id)
        if not cart_items:
            return None
        total_price = sum(item['price'] * item['quantity'] for item in cart_items)
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO orders (user_id, total_price, contact, address, comment, status)
                VALUES (?, ?, ?, ?, ?, 'new')
            """, (user_id, total_price, contact, address, comment))
            order_id = cursor.lastrowid
            for item in cart_items:
                cursor.execute("""
                    INSERT INTO order_items (order_id, product_id, size, quantity, price)
                    VALUES (?, ?, ?, ?, ?)
                """, (order_id, item['product_id'], item['size'], item['quantity'], item['price']))
            cursor.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
        return order_id
    except Exception as e:
        logger.error(f"Failed to create order: {e}")
        return None

def get_orders(status: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute("""
                    SELECT o.*, u.username
                    FROM orders o
                    LEFT JOIN users u ON o.user_id = u.telegram_id
                    WHERE o.status = ?
                    ORDER BY o.created_at DESC
                """, (status,))
            else:
                cursor.execute("""
                    SELECT o.*, u.username
                    FROM orders o
                    LEFT JOIN users u ON o.user_id = u.telegram_id
                    ORDER BY o.created_at DESC
                """)
            orders = [dict(row) for row in cursor.fetchall()]
            for order in orders:
                cursor.execute("""
                    SELECT oi.*, p.name
                    FROM order_items oi
                    JOIN products p ON oi.product_id = p.id
                    WHERE oi.order_id = ?
                """, (order['id'],))
                order['items'] = [dict(row) for row in cursor.fetchall()]
            return orders
    except Exception as e:
        logger.error(f"Failed to get orders: {e}")
        return []

def get_user_orders(user_id: int) -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT o.*, u.username
                FROM orders o
                LEFT JOIN users u ON o.user_id = u.telegram_id
                WHERE o.user_id = ?
                ORDER BY o.created_at DESC
            """, (user_id,))
            orders = [dict(row) for row in cursor.fetchall()]
            for order in orders:
                cursor.execute("""
                    SELECT oi.*, p.name
                    FROM order_items oi
                    JOIN products p ON oi.product_id = p.id
                    WHERE oi.order_id = ?
                """, (order['id'],))
                order['items'] = [dict(row) for row in cursor.fetchall()]
            return orders
    except Exception as e:
        logger.error(f"Failed to get user orders: {e}")
        return []

def update_order_status(order_id: int, status: str, reject_reason: str = ""):
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            if status == 'rejected':
                cursor.execute(
                    "UPDATE orders SET status = ?, reject_reason = ? WHERE id = ?",
                    (status, reject_reason, order_id)
                )
            else:
                cursor.execute(
                    "UPDATE orders SET status = ? WHERE id = ?",
                    (status, order_id)
                )
    except Exception as e:
        logger.error(f"Failed to update order status: {e}")

def get_order(order_id: int) -> Optional[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            order = cursor.fetchone()
            if not order:
                return None
            order = dict(order)
            cursor.execute("""
                SELECT oi.*, p.name
                FROM order_items oi
                JOIN products p ON oi.product_id = p.id
                WHERE oi.order_id = ?
            """, (order_id,))
            order['items'] = [dict(row) for row in cursor.fetchall()]
            return order
    except Exception as e:
        logger.error(f"Failed to get order: {e}")
        return None

def get_statistics() -> Dict[str, Any]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM products")
            products = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM orders")
            orders = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(total_price) FROM orders WHERE status = 'approved'")
            revenue = cursor.fetchone()[0] or 0
            return {
                "users": users,
                "products": products,
                "orders": orders,
                "revenue": revenue
            }
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        return {"users": 0, "products": 0, "orders": 0, "revenue": 0}

def get_all_users() -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT telegram_id, username FROM users ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get all users: {e}")
        return []

# -------------------- ФУНКЦИИ ДЛЯ КАТЕГОРИЙ --------------------
def get_all_categories() -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM categories ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get categories: {e}")
        return []

def get_subcategories(category_id: int) -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name FROM subcategories WHERE category_id = ? ORDER BY name",
                (category_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get subcategories: {e}")
        return []

def get_all_subcategories_with_category() -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.name, c.name as category_name
                FROM subcategories s
                JOIN categories c ON s.category_id = c.id
                ORDER BY c.name, s.name
            """)
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get subcategories with category: {e}")
        return []

def get_products_by_subcategory(subcategory_id: int, offset: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, price FROM products WHERE subcategory_id = ? ORDER BY name LIMIT ? OFFSET ?",
                (subcategory_id, limit, offset)
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get products by subcategory: {e}")
        return []

def count_products_by_subcategory(subcategory_id: int) -> int:
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products WHERE subcategory_id = ?", (subcategory_id,))
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Failed to count products by subcategory: {e}")
        return 0

# -------------------- ФУНКЦИИ ДЛЯ КЛАВИАТУР --------------------
def get_main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton("🛍 Ассортимент")],
        [KeyboardButton("🛒 Корзина"), KeyboardButton("📦 Мои заказы")],
        [KeyboardButton("ℹ️ О нас"), KeyboardButton("📞 Поддержка")],
        [KeyboardButton("🌐 Соцсети")]
    ]
    if is_admin:
        buttons.append([KeyboardButton("🔧 Админ панель")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def admin_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="admin_add_product")],
        [InlineKeyboardButton("🗑 Удалить товар", callback_data="admin_delete_product")],
        [InlineKeyboardButton("📦 Заказы", callback_data="admin_orders")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📨 Рассылка", callback_data="admin_mailing")],
        [InlineKeyboardButton("🔙 Выход", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def assortment_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    categories = get_all_categories()
    for cat in categories:
        if cat['name'] == 'Одежда':
            keyboard.append([InlineKeyboardButton("👕 Одежда", callback_data=f"cat_{cat['id']}")])
        elif cat['name'] == 'Обувь':
            keyboard.append([InlineKeyboardButton("👟 Обувь", callback_data=f"cat_{cat['id']}")])
        elif cat['name'] == 'Аксессуары':
            keyboard.append([InlineKeyboardButton("🎒 Аксессуары", callback_data=f"cat_{cat['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

def subcategories_keyboard(subcategories: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    keyboard = []
    for sub in subcategories:
        keyboard.append([InlineKeyboardButton(sub['name'], callback_data=f"subcat_{sub['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 К категориям", callback_data="back_to_assortment")])
    return InlineKeyboardMarkup(keyboard)

def products_keyboard(products: List[Dict[str, Any]], page: int, total_pages: int, subcategory_id: int) -> InlineKeyboardMarkup:
    keyboard = []
    for prod in products:
        keyboard.append([InlineKeyboardButton(
            f"{prod['name']} - {prod['price']} BYN",
            callback_data=f"prod_{prod['id']}_{subcategory_id}"
        )])

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"subcat_prod_page_{subcategory_id}_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="ignore"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"subcat_prod_page_{subcategory_id}_{page+1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("🔙 К подкатегориям", callback_data=f"back_to_subcats_{subcategory_id}")])
    return InlineKeyboardMarkup(keyboard)

def product_detail_keyboard(
    product_id: int,
    sizes: List[str],
    current_image: int,
    total_images: int,
    subcategory_id: Optional[int] = None
) -> InlineKeyboardMarkup:
    keyboard = []

    if sizes:
        size_buttons = []
        for s in sizes:
            size_buttons.append(InlineKeyboardButton(s, callback_data=f"size_{product_id}_{s}"))
        for i in range(0, len(size_buttons), 3):
            keyboard.append(size_buttons[i:i+3])

    if total_images > 1:
        nav_photo = []
        if current_image > 1:
            nav_photo.append(InlineKeyboardButton("⬅️", callback_data=f"photo_{product_id}_{current_image-1}"))
        nav_photo.append(InlineKeyboardButton(f"{current_image}/{total_images}", callback_data="ignore"))
        if current_image < total_images:
            nav_photo.append(InlineKeyboardButton("➡️", callback_data=f"photo_{product_id}_{current_image+1}"))
        keyboard.append(nav_photo)

    keyboard.append([InlineKeyboardButton("➕ Добавить в корзину", callback_data=f"add_{product_id}_")])

    # Кнопка возврата к товарам
    if subcategory_id:
        keyboard.append([InlineKeyboardButton("🔙 К товарам", callback_data=f"back_to_products_{subcategory_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🔙 К товарам", callback_data="back_to_assortment")])
    
    return InlineKeyboardMarkup(keyboard)

def cart_keyboard(cart_items: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    keyboard = []
    for item in cart_items:
        row = [
            InlineKeyboardButton("➖", callback_data=f"cart_dec_{item['id']}"),
            InlineKeyboardButton(f"{item['name'][:12]}... {item.get('size','')} x{item['quantity']}", callback_data="ignore"),
            InlineKeyboardButton("➕", callback_data=f"cart_inc_{item['id']}"),
            InlineKeyboardButton("❌", callback_data=f"cart_del_{item['id']}")
        ]
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton("🗑 Очистить", callback_data="cart_clear"),
        InlineKeyboardButton("✅ Оформить", callback_data="checkout")
    ])
    keyboard.append([InlineKeyboardButton("🔙 В ассортимент", callback_data="back_to_assortment")])
    return InlineKeyboardMarkup(keyboard)

def checkout_confirm_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data="checkout_confirm"),
            InlineKeyboardButton("❌ Отменить", callback_data="checkout_cancel")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_orders_keyboard(orders: List[Dict[str, Any]], page: int = 1, total_pages: int = 1) -> InlineKeyboardMarkup:
    keyboard = []
    for order in orders:
        status_display = ORDER_STATUSES.get(order['status'], order['status'])
        keyboard.append([InlineKeyboardButton(
            f"Заказ #{order['id']} ({status_display}) - {order['total_price']} BYN",
            callback_data=f"admin_order_{order['id']}"
        )])
    
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"admin_orders_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="ignore"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"admin_orders_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 В админку", callback_data="admin_back")])
    return InlineKeyboardMarkup(keyboard)

def admin_order_detail_keyboard(order_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✅ Одобрить", callback_data=f"set_status_{order_id}_approved"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"set_status_{order_id}_rejected")
        ],
        [InlineKeyboardButton("🔙 К заказам", callback_data="admin_orders")]
    ]
    return InlineKeyboardMarkup(keyboard)

def search_keyboard(results: List[Dict[str, Any]], page: int, total_pages: int, query: str) -> InlineKeyboardMarkup:
    keyboard = []
    for prod in results:
        keyboard.append([InlineKeyboardButton(
            f"{prod['name']} - {prod['price']} BYN",
            callback_data=f"prod_{prod['id']}_0"
        )])
    
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"search_page_{query}_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="ignore"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"search_page_{query}_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

def user_orders_keyboard(orders: List[Dict[str, Any]], page: int, total_pages: int) -> InlineKeyboardMarkup:
    keyboard = []
    for order in orders:
        status_display = ORDER_STATUSES.get(order['status'], order['status'])
        keyboard.append([InlineKeyboardButton(
            f"Заказ #{order['id']} {status_display} - {order['total_price']} BYN",
            callback_data=f"user_order_{order['id']}"
        )])
    
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"user_orders_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="ignore"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"user_orders_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

def social_media_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📱 TikTok", url="https://www.tiktok.com/@rawwearrr?_r=1&_t=ZS-94eY0eiJVMQ")],
        [InlineKeyboardButton("📸 Instagram", url="https://www.instagram.com/rawwear_storee?igsh=MTdoczZsNTBycjFtZg%3D%3D&utm_source=qr")],
        [InlineKeyboardButton("▶️ YouTube", url="https://youtube.com/@rawwearrr?si=0xFL5L2vU9gcOeZ_")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def mailing_confirm_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✅ Отправить", callback_data="mailing_send"),
            InlineKeyboardButton("❌ Отменить", callback_data="mailing_cancel")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_photo_options_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить добавление фото", callback_data="admin_skip_photos")],
        [InlineKeyboardButton("❌ Отменить добавление", callback_data="admin_cancel_add")]
    ]
    return InlineKeyboardMarkup(keyboard)

# -------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ --------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def parse_sizes(sizes_str: str) -> List[str]:
    if not sizes_str:
        return []
    return [s.strip() for s in sizes_str.split(',') if s.strip()]

def notify_admins(bot, message: str):
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, message, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

def safe_delete_message(context: CallbackContext, chat_id: int, message_id: int):
    """Безопасное удаление сообщения"""
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except BadRequest as e:
        if "message to delete not found" not in str(e).lower():
            logger.error(f"Failed to delete message: {e}")
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

def safe_edit_message_text(query, text: str, reply_markup=None, parse_mode=None):
    """Безопасное редактирование сообщения"""
    try:
        if reply_markup:
            query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            query.edit_message_text(text, parse_mode=parse_mode)
        return True
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return True
        elif "There is no text in the message to edit" in str(e).lower():
            # Если сообщение не содержит текста (например, фото), отправляем новое
            try:
                chat_id = query.message.chat_id
                context = query.message.bot
                safe_delete_message(context, chat_id, query.message.message_id)
                context.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
                return True
            except:
                return False
        logger.error(f"Failed to edit message: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")
        return False

def end_conversation_and_clear(user_id: int, context: CallbackContext, chat_id: int, message: str):
    """Завершает разговор, очищает сообщения и отправляет финальное сообщение"""
    try:
        # Удаляем все сообщения пользователя
        messages = delete_user_messages(user_id)
        for msg_chat_id, msg_id in messages:
            safe_delete_message(context, msg_chat_id, msg_id)
        
        # Очищаем данные пользователя
        context.user_data.clear()
        
        # Отправляем сообщение об окончании
        sent_msg = context.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=get_main_menu_keyboard(is_admin(user_id))
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "menu")
    except Exception as e:
        logger.error(f"Error in end_conversation_and_clear: {e}")
    
    return ConversationHandler.END

# -------------------- ОБРАБОТЧИКИ КОМАНД --------------------
def start(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        add_user(user_id, username)

        welcome_text = (
            "👋 Привет! Я ваш бот‑помощник телеграма RAWWEAR\n"
            "Помогу вам в выборе и заказе самой актуальной и качественной одежды⬇️"
        )

        # Отправляем приветствие
        try:
            if BOT_AVATAR_FILE_ID and BOT_AVATAR_FILE_ID.strip():
                try:
                    sent_msg = context.bot.send_photo(
                        chat_id=update.message.chat_id,
                        photo=BOT_AVATAR_FILE_ID,
                        caption=welcome_text
                    )
                except:
                    sent_msg = update.message.reply_text(welcome_text)
            else:
                sent_msg = update.message.reply_text(welcome_text)
        except:
            sent_msg = update.message.reply_text(welcome_text)
        
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "welcome")

        # Отправляем меню
        admin_flag = is_admin(user_id)
        sent_msg = update.message.reply_text(
            "👇 Выберите действие:",
            reply_markup=get_main_menu_keyboard(admin_flag)
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "menu")
    except Exception as e:
        logger.error(f"Error in start: {e}")

def search_command(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        
        # Клавиатура с кнопкой отмены
        keyboard = [[InlineKeyboardButton("❌ Отменить поиск", callback_data="cancel_search")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = update.message.reply_text(
            "🔍 Введите название товара для поиска:",
            reply_markup=reply_markup
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "search")
        return SEARCH_QUERY
    except Exception as e:
        logger.error(f"Error in search_command: {e}")
        return ConversationHandler.END

def cancel_search(update: Update, context: CallbackContext):
    """Отмена поиска"""
    try:
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
        # Удаляем сообщение с кнопками
        safe_delete_message(context, chat_id, query.message.message_id)
        
        return end_conversation_and_clear(user_id, context, chat_id, "🔍 Поиск отменён.")
    except Exception as e:
        logger.error(f"Error in cancel_search: {e}")
        return ConversationHandler.END

# -------------------- ОБРАБОТЧИКИ ТЕКСТОВЫХ КНОПОК --------------------
def handle_assortment(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        delete_user_messages(user_id, "product_list")
        
        sent_msg = update.message.reply_text(
            "📂 Выберите категорию:",
            reply_markup=assortment_keyboard()
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "assortment")
    except Exception as e:
        logger.error(f"Error in handle_assortment: {e}")

def handle_cart(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        cart_items = get_cart(user_id)
        if not cart_items:
            sent_msg = update.message.reply_text("🛒 Ваша корзина пуста.")
            save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "cart")
            return
        text = "🛒 *Ваша корзина:*\n\n"
        total = 0
        for item in cart_items:
            text += f"• {item['name']} "
            if item['size']:
                text += f"(размер {item['size']}) "
            text += f"x{item['quantity']} = {item['price'] * item['quantity']} BYN\n"
            total += item['price'] * item['quantity']
        text += f"\n💰 *Итого: {total} BYN*"
        sent_msg = update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cart_keyboard(cart_items)
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "cart")
    except Exception as e:
        logger.error(f"Error in handle_cart: {e}")

def handle_my_orders(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        orders = get_user_orders(user_id)
        if not orders:
            sent_msg = update.message.reply_text("📭 У вас пока нет заказов.")
            save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "orders")
            return
        page = 1
        per_page = 5
        total_pages = (len(orders) + per_page - 1) // per_page
        start = (page - 1) * per_page
        end = start + per_page
        page_orders = orders[start:end]
        text = f"📦 *Ваши заказы* (стр. {page}/{total_pages}):\n\n"
        for order in page_orders:
            status_display = ORDER_STATUSES.get(order['status'], order['status'])
            text += f"• #{order['id']} от {order['created_at'][:10]} — {order['total_price']} BYN ({status_display})\n"
        sent_msg = update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=user_orders_keyboard(page_orders, page, total_pages)
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "orders")
    except Exception as e:
        logger.error(f"Error in handle_my_orders: {e}")

def handle_about(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        text = (
            "ℹ️ *О нас*\n\n"
            "Мы — RAWWEAR, бренд уличной одежды.\n"
            "Работаем с 2025 года. Все товары сертифицированы.\n\n"
            "Почему мы?\n"
            "🔘 Качество: Только проверенные фабрики и честные обзоры\n"
            "🔘 Доставка: Бережно и в срок, отправка в тот же день после заказа (1-3 дня по РБ🇧🇾 | 3-7 дней по РФ🇷🇺)\n"
            "🔘 Доверенность: публичные отзывы\n\n"
            "✨ Спасибо, что выбираете нас!"
        )
        
        keyboard = [[InlineKeyboardButton("📝 Отзывы", url="https://t.me/rawwearrr_otziv")]]
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
        
        sent_msg = update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "about")
    except Exception as e:
        logger.error(f"Error in handle_about: {e}")

def handle_support(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        text = (
            "📞 Поддержка\n\n"
            "Если у вас возникли вопросы, напишите нам:\n"
            "📱 Telegram: @matpluuux\n"
            "⏰ Время работы: круглосуточно"
        )
        sent_msg = update.message.reply_text(text)
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "support")
    except Exception as e:
        logger.error(f"Error in handle_support: {e}")

def handle_social(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        sent_msg = update.message.reply_text(
            "🌐 Наши социальные сети:",
            reply_markup=social_media_keyboard()
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "social")
    except Exception as e:
        logger.error(f"Error in handle_social: {e}")

def handle_admin_panel(update: Update, context: CallbackContext):
    try:
        if not is_admin(update.effective_user.id):
            update.message.reply_text("⛔ Доступ запрещён.")
            return
        user_id = update.effective_user.id
        sent_msg = update.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin")
    except Exception as e:
        logger.error(f"Error in handle_admin_panel: {e}")

# -------------------- ОБРАБОТЧИКИ КАТЕГОРИЙ/ПОДКАТЕГОРИЙ --------------------
def callback_show_subcategories(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        
        category_id = int(query.data.split('_')[1])
        subcategories = get_subcategories(category_id)
        if not subcategories:
            safe_edit_message_text(query, "😕 В этой категории пока нет подкатегорий.")
            return
        
        safe_edit_message_text(
            query,
            "📂 Выберите подкатегорию:",
            reply_markup=subcategories_keyboard(subcategories)
        )
    except Exception as e:
        logger.error(f"Error in callback_show_subcategories: {e}")

def callback_show_products_by_subcategory(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        subcategory_id = int(query.data.split('_')[1])
        show_products_by_subcategory(query, subcategory_id, 1, context)
    except Exception as e:
        logger.error(f"Error in callback_show_products_by_subcategory: {e}")

def show_products_by_subcategory(query, subcategory_id: int, page: int, context: CallbackContext):
    try:
        user_id = query.from_user.id
        
        delete_user_messages(user_id, "product_list")
        
        offset = (page - 1) * 10
        products = get_products_by_subcategory(subcategory_id, offset=offset)
        total = count_products_by_subcategory(subcategory_id)
        total_pages = (total + 9) // 10

        if not products:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К подкатегориям", callback_data=f"back_to_subcats_{subcategory_id}")
            ]])
            safe_edit_message_text(query, "📭 В этой подкатегории пока нет товаров.", reply_markup=keyboard)
            return

        safe_edit_message_text(
            query,
            f"📦 Товары (стр. {page}/{total_pages}):",
            reply_markup=products_keyboard(products, page, total_pages, subcategory_id)
        )
    except Exception as e:
        logger.error(f"Error in show_products_by_subcategory: {e}")

def callback_subcat_products_page(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        parts = query.data.split('_')
        subcategory_id = int(parts[3])
        page = int(parts[4])
        show_products_by_subcategory(query, subcategory_id, page, context)
    except Exception as e:
        logger.error(f"Error in callback_subcat_products_page: {e}")

def callback_back_to_subcategories(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        subcategory_id = int(query.data.split('_')[3])
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT category_id FROM subcategories WHERE id = ?", (subcategory_id,))
            row = cursor.fetchone()
            if not row:
                safe_edit_message_text(query, "❌ Ошибка: подкатегория не найдена.")
                return
            category_id = row['category_id']
        subcategories = get_subcategories(category_id)
        safe_edit_message_text(
            query,
            "📂 Выберите подкатегорию:",
            reply_markup=subcategories_keyboard(subcategories)
        )
    except Exception as e:
        logger.error(f"Error in callback_back_to_subcategories: {e}")

def callback_back_to_assortment(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        safe_edit_message_text(
            query,
            "📂 Выберите категорию:",
            reply_markup=assortment_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in callback_back_to_assortment: {e}")

# -------------------- ОБРАБОТЧИКИ ТОВАРОВ --------------------
def callback_product(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        
        parts = query.data.split('_')
        prod_id = int(parts[1])
        subcategory_id = int(parts[2]) if len(parts) > 2 and parts[2] != '0' else None
        product = get_product(prod_id)
        if not product:
            safe_edit_message_text(query, "❌ Товар не найден.")
            return

        sizes_list = parse_sizes(product['sizes'])
        images = get_product_images(prod_id)

        if not images:
            text = f"🧥 *{product['name']}*\n\n"
            text += f"💰 *Цена:* {product['price']} BYN\n"
            text += f"📝 *Описание:* {product['description']}\n"
            if sizes_list:
                text += f"📏 *Размеры:* {', '.join(sizes_list)}\n"
            else:
                text += "📏 Размеры: единый размер.\n"
            keyboard = product_detail_keyboard(prod_id, sizes_list, 0, 0, subcategory_id)
            
            if query.message:
                delete_user_messages(user_id, "product_detail")
                safe_edit_message_text(
                    query,
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
        else:
            current = 1
            total = len(images)
            img = images[0]
            text = f"🧥 *{product['name']}*\n\n"
            text += f"💰 *Цена:* {product['price']} BYN\n"
            text += f"📝 *Описание:* {product['description']}\n"
            if sizes_list:
                text += f"📏 *Размеры:* {', '.join(sizes_list)}\n"
            else:
                text += "📏 Размеры: единый размер.\n"
            keyboard = product_detail_keyboard(prod_id, sizes_list, current, total, subcategory_id)
            
            safe_delete_message(context, query.message.chat_id, query.message.message_id)
            sent_msg = context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=img['file_id'],
                caption=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            delete_user_messages(user_id, "product_detail")
            save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "product_detail")
    except Exception as e:
        logger.error(f"Error in callback_product: {e}")

def callback_product_photo_nav(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        parts = query.data.split('_')
        prod_id = int(parts[1])
        target = int(parts[2])
        product = get_product(prod_id)
        if not product:
            safe_edit_message_text(query, "❌ Товар не найден.")
            return

        images = get_product_images(prod_id)
        if not images or target < 1 or target > len(images):
            query.answer("❌ Изображение не найдено.")
            return

        sizes_list = parse_sizes(product['sizes'])
        img = images[target - 1]
        text = f"🧥 *{product['name']}*\n\n"
        text += f"💰 *Цена:* {product['price']} BYN\n"
        text += f"📝 *Описание:* {product['description']}\n"
        if sizes_list:
            text += f"📏 *Размеры:* {', '.join(sizes_list)}\n"
        else:
            text += "📏 Размеры: единый размер.\n"
        keyboard = product_detail_keyboard(prod_id, sizes_list, target, len(images), product.get('subcategory_id'))

        try:
            query.edit_message_media(
                media=InputMediaPhoto(media=img['file_id'], caption=text, parse_mode=ParseMode.MARKDOWN),
                reply_markup=keyboard
            )
        except:
            safe_delete_message(context, query.message.chat_id, query.message.message_id)
            context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=img['file_id'],
                caption=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"Error in callback_product_photo_nav: {e}")

def callback_size(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        parts = query.data.split('_')
        prod_id = int(parts[1])
        size = parts[2]
        context.user_data['selected_size'] = size
        context.user_data['selected_product'] = prod_id
        sent_msg = query.message.reply_text(f"📏 Выбран размер {size}. Теперь нажмите «➕ Добавить в корзину».")
        save_message(query.from_user.id, sent_msg.chat_id, sent_msg.message_id, "size_select")
    except Exception as e:
        logger.error(f"Error in callback_size: {e}")

def callback_add_to_cart(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        
        parts = query.data.split('_')
        prod_id = int(parts[1])
        size = context.user_data.get('selected_size')
        success = add_to_cart(user_id, prod_id, size)
        
        delete_user_messages(user_id, "size_select")
        
        if 'selected_size' in context.user_data:
            del context.user_data['selected_size']
        
        if success:
            sent_msg = query.message.reply_text("✅ Товар добавлен в корзину.")
        else:
            sent_msg = query.message.reply_text("❌ Не удалось добавить товар.")
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "cart_notify")
    except Exception as e:
        logger.error(f"Error in callback_add_to_cart: {e}")

def callback_back_to_products(update: Update, context: CallbackContext):
    """Возврат к списку товаров из карточки товара"""
    try:
        query = update.callback_query
        query.answer()
        
        # Извлекаем subcategory_id из callback_data
        # Формат: back_to_products_{subcategory_id}
        parts = query.data.split('_')
        if len(parts) >= 4:
            subcategory_id = int(parts[3])
        else:
            logger.error(f"Invalid callback data: {query.data}")
            return
        
        user_id = query.from_user.id
        
        # Удаляем сообщения с деталями товара
        delete_user_messages(user_id, "product_detail")
        
        # Показываем список товаров
        show_products_by_subcategory(query, subcategory_id, 1, context)
        
    except Exception as e:
        logger.error(f"Error in callback_back_to_products: {e}")

def callback_back_to_products_all(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        callback_back_to_assortment(update, context)
    except Exception as e:
        logger.error(f"Error in callback_back_to_products_all: {e}")

# -------------------- ОБРАБОТЧИКИ КОРЗИНЫ --------------------
def cart_increase(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        item_id = int(query.data.split('_')[2])
        update_cart_quantity(item_id, delta=1)
        update_cart_message(query)
    except Exception as e:
        logger.error(f"Error in cart_increase: {e}")

def cart_decrease(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        item_id = int(query.data.split('_')[2])
        update_cart_quantity(item_id, delta=-1)
        update_cart_message(query)
    except Exception as e:
        logger.error(f"Error in cart_decrease: {e}")

def cart_delete(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        item_id = int(query.data.split('_')[2])
        remove_from_cart(item_id)
        update_cart_message(query)
    except Exception as e:
        logger.error(f"Error in cart_delete: {e}")

def cart_clear(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        clear_cart(query.from_user.id)
        safe_edit_message_text(query, "🛒 Корзина очищена.")
    except Exception as e:
        logger.error(f"Error in cart_clear: {e}")

def update_cart_message(query):
    try:
        user_id = query.from_user.id
        cart_items = get_cart(user_id)
        if not cart_items:
            safe_edit_message_text(query, "🛒 Корзина пуста.")
            return
        text = "🛒 *Ваша корзина:*\n\n"
        total = 0
        for item in cart_items:
            text += f"• {item['name']} "
            if item['size']:
                text += f"(размер {item['size']}) "
            text += f"x{item['quantity']} = {item['price'] * item['quantity']} BYN\n"
            total += item['price'] * item['quantity']
        text += f"\n💰 *Итого: {total} BYN*"
        safe_edit_message_text(
            query,
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cart_keyboard(cart_items)
        )
    except Exception as e:
        logger.error(f"Error in update_cart_message: {e}")

# -------------------- ОБРАБОТЧИКИ ОФОРМЛЕНИЯ ЗАКАЗА --------------------
def checkout_start(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        cart_items = get_cart(user_id)
        if not cart_items:
            query.message.reply_text("🛒 Корзина пуста.")
            return ConversationHandler.END
        
        delete_user_messages(user_id, "checkout")
        
        # Клавиатура с отменой
        keyboard = [[InlineKeyboardButton("❌ Отменить оформление", callback_data="checkout_cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = query.message.reply_text(
            "📞 Напишите свой юзернейм или номер телефона, чтобы мы могли связаться с вами.",
            reply_markup=reply_markup
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "checkout")
        return CHECKOUT_CONTACT
    except Exception as e:
        logger.error(f"Error in checkout_start: {e}")
        return ConversationHandler.END

def checkout_contact(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        contact = update.message.text.strip()
        context.user_data['contact'] = contact
        
        save_message(user_id, update.message.chat_id, update.message.message_id, "checkout")
        
        # Клавиатура с отменой
        keyboard = [[InlineKeyboardButton("❌ Отменить оформление", callback_data="checkout_cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = update.message.reply_text(
            "🏙 Введите ваш город и адрес доставки.",
            reply_markup=reply_markup
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "checkout")
        return CHECKOUT_ADDRESS
    except Exception as e:
        logger.error(f"Error in checkout_contact: {e}")
        return ConversationHandler.END

def checkout_address(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        address = update.message.text.strip()
        context.user_data['address'] = address
        
        save_message(user_id, update.message.chat_id, update.message.message_id, "checkout")
        
        # Клавиатура с отменой
        keyboard = [[InlineKeyboardButton("❌ Отменить оформление", callback_data="checkout_cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = update.message.reply_text(
            "📝 Введите комментарий к заказу (необязательно). Можно отправить прочерк '-'.",
            reply_markup=reply_markup
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "checkout")
        return CHECKOUT_COMMENT
    except Exception as e:
        logger.error(f"Error in checkout_address: {e}")
        return ConversationHandler.END

def checkout_comment(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        comment = update.message.text.strip()
        if comment == '-':
            comment = ""
        context.user_data['comment'] = comment
        
        save_message(user_id, update.message.chat_id, update.message.message_id, "checkout")
        
        cart_items = get_cart(user_id)
        if not cart_items:
            update.message.reply_text("🛒 Корзина пуста. Заказ отменён.")
            return ConversationHandler.END
        
        text = "📦 *Проверьте данные заказа:*\n\n"
        text += f"📞 *Контакт:* {context.user_data['contact']}\n"
        text += f"🏙 *Адрес:* {context.user_data['address']}\n"
        if context.user_data['comment']:
            text += f"📝 *Комментарий:* {context.user_data['comment']}\n"
        text += "\n🛍 *Состав корзины:*\n"
        total = 0
        for item in cart_items:
            text += f"• {item['name']} "
            if item['size']:
                text += f"(размер {item['size']}) "
            text += f"x{item['quantity']} = {item['price'] * item['quantity']} BYN\n"
            total += item['price'] * item['quantity']
        text += f"\n💰 *Итого: {total} BYN*"
        
        sent_msg = update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=checkout_confirm_keyboard()
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "checkout")
        return CHECKOUT_CONFIRM
    except Exception as e:
        logger.error(f"Error in checkout_comment: {e}")
        return ConversationHandler.END

def checkout_confirm(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        
        order_id = create_order(
            user_id, 
            context.user_data['contact'], 
            context.user_data['address'], 
            context.user_data.get('comment', '')
        )
        
        for key in ['contact', 'address', 'comment']:
            if key in context.user_data:
                del context.user_data[key]
        
        if order_id:
            delete_user_messages(user_id, "checkout")
            
            safe_edit_message_text(
                query,
                "✅ Заказ оформлен и отправлен на модерацию!\n\n"
                "Вам придет уведомление о статусе заказа. "
                "Следите за заказом в разделе «📦 Мои заказы»."
            )
            
            order = get_order(order_id)
            items_text = ""
            for item in order['items']:
                items_text += f"• {item['name']} x{item['quantity']} = {item['price']*item['quantity']} BYN\n"
            admin_msg = (
                f"🆕 *Новый заказ #{order_id}*\n\n"
                f"👤 *Пользователь:* {query.from_user.full_name} (@{query.from_user.username})\n"
                f"📞 *Контакт:* {order['contact']}\n"
                f"🏙 *Адрес:* {order['address']}\n"
                f"📝 *Комментарий:* {order['comment'] or '—'}\n\n"
                f"🛍 *Состав:*\n{items_text}"
                f"💰 *Итого:* {order['total_price']} BYN"
            )
            notify_admins(context.bot, admin_msg)
        else:
            safe_edit_message_text(query, "❌ Ошибка при оформлении заказа. Попробуйте позже.")
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in checkout_confirm: {e}")
        return ConversationHandler.END

def checkout_cancel(update: Update, context: CallbackContext):
    """Отмена оформления заказа"""
    try:
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
        # Удаляем сообщение с кнопками
        safe_delete_message(context, chat_id, query.message.message_id)
        
        return end_conversation_and_clear(user_id, context, chat_id, "❌ Оформление заказа отменено.")
    except Exception as e:
        logger.error(f"Error in checkout_cancel: {e}")
        return ConversationHandler.END

# -------------------- ОБРАБОТЧИКИ ЗАКАЗОВ ПОЛЬЗОВАТЕЛЯ --------------------
def callback_user_order_detail(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        order_id = int(query.data.split('_')[2])
        order = get_order(order_id)
        if not order:
            safe_edit_message_text(query, "❌ Заказ не найден.")
            return
        
        status_display = ORDER_STATUSES.get(order['status'], order['status'])
        text = f"📦 *Заказ #{order['id']}*\n"
        text += f"📅 *Дата:* {order['created_at']}\n"
        text += f"📌 *Статус:* {status_display}\n"
        text += f"📞 *Контакт:* {order['contact']}\n"
        text += f"🏙 *Адрес:* {order['address']}\n"
        if order['comment']:
            text += f"📝 *Комментарий:* {order['comment']}\n"
        
        if order['status'] == 'rejected' and order.get('reject_reason'):
            text += f"❌ *Причина отказа:* {order['reject_reason']}\n"
        elif order['status'] == 'approved':
            text += f"📱 *Для отправки:* @matpluuux\n"
        
        text += "🛍 *Состав:*\n"
        for item in order['items']:
            text += f"  • {item['name']} x{item['quantity']} = {item['price']*item['quantity']} BYN"
            if item['size']:
                text += f" (размер {item['size']})"
            text += "\n"
        text += f"💰 *Итого: {order['total_price']} BYN*"
        
        safe_edit_message_text(query, text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in callback_user_order_detail: {e}")

def callback_user_orders_page(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        page = int(query.data.split('_')[3])
        user_id = query.from_user.id
        orders = get_user_orders(user_id)
        per_page = 5
        total_pages = (len(orders) + per_page - 1) // per_page
        start = (page - 1) * per_page
        end = start + per_page
        page_orders = orders[start:end]
        text = f"📦 *Ваши заказы* (стр. {page}/{total_pages}):\n\n"
        for order in page_orders:
            status_display = ORDER_STATUSES.get(order['status'], order['status'])
            text += f"• #{order['id']} от {order['created_at'][:10]} — {order['total_price']} BYN ({status_display})\n"
        safe_edit_message_text(
            query,
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=user_orders_keyboard(page_orders, page, total_pages)
        )
    except Exception as e:
        logger.error(f"Error in callback_user_orders_page: {e}")

# -------------------- АДМИН ОБРАБОТЧИКИ (ДОБАВЛЕНИЕ ТОВАРА) --------------------
def admin_add_product_start(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        if not is_admin(query.from_user.id):
            query.answer("⛔ Доступ запрещён.", show_alert=True)
            return ConversationHandler.END
        
        # Очищаем данные пользователя
        context.user_data.clear()
        
        all_subs = get_all_subcategories_with_category()
        if not all_subs:
            safe_edit_message_text(query, "❌ Нет доступных подкатегорий.")
            return ConversationHandler.END

        keyboard = []
        emoji_map = {
            'Одежда': '👕',
            'Обувь': '👟',
            'Аксессуары': '🎒'
        }
        for sub in all_subs:
            emoji = emoji_map.get(sub['category_name'], '•')
            keyboard.append([InlineKeyboardButton(
                f"{emoji} {sub['category_name']} – {sub['name']}",
                callback_data=f"admin_sub_{sub['id']}"
            )])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="admin_cancel_add")])
        
        safe_edit_message_text(
            query,
            "📂 Выберите подкатегорию для нового товара:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SUBCATEGORY_SELECTION
    except Exception as e:
        logger.error(f"Error in admin_add_product_start: {e}")
        return ConversationHandler.END

def admin_choose_subcategory(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        if not is_admin(query.from_user.id):
            query.answer("⛔ Доступ запрещён.", show_alert=True)
            return ConversationHandler.END
        
        subcategory_id = int(query.data.split('_')[2])
        context.user_data['subcategory_id'] = subcategory_id
        
        # Клавиатура с отменой
        keyboard = [[InlineKeyboardButton("❌ Отменить добавление", callback_data="admin_cancel_add")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        safe_edit_message_text(
            query,
            "📝 Введите название товара:",
            reply_markup=reply_markup
        )
        return ADD_PRODUCT_NAME
    except Exception as e:
        logger.error(f"Error in admin_choose_subcategory: {e}")
        return ConversationHandler.END

def admin_add_product_name(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        save_message(user_id, update.message.chat_id, update.message.message_id, "admin_add")
        
        context.user_data['name'] = update.message.text
        
        # Клавиатура с отменой
        keyboard = [[InlineKeyboardButton("❌ Отменить добавление", callback_data="admin_cancel_add")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = update.message.reply_text(
            "📄 Введите описание товара:",
            reply_markup=reply_markup
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin_add")
        return ADD_PRODUCT_DESCRIPTION
    except Exception as e:
        logger.error(f"Error in admin_add_product_name: {e}")
        return ConversationHandler.END

def admin_add_product_description(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        save_message(user_id, update.message.chat_id, update.message.message_id, "admin_add")
        
        context.user_data['description'] = update.message.text
        
        # Клавиатура с отменой
        keyboard = [[InlineKeyboardButton("❌ Отменить добавление", callback_data="admin_cancel_add")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = update.message.reply_text(
            "💰 Введите цену товара (только число, в BYN):",
            reply_markup=reply_markup
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin_add")
        return ADD_PRODUCT_PRICE
    except Exception as e:
        logger.error(f"Error in admin_add_product_description: {e}")
        return ConversationHandler.END

def admin_add_product_price(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        save_message(user_id, update.message.chat_id, update.message.message_id, "admin_add")
        
        try:
            price = int(update.message.text)
            if price <= 0:
                raise ValueError
        except ValueError:
            # Клавиатура с отменой
            keyboard = [[InlineKeyboardButton("❌ Отменить добавление", callback_data="admin_cancel_add")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            sent_msg = update.message.reply_text(
                "❌ Цена должна быть положительным целым числом. Попробуйте снова:",
                reply_markup=reply_markup
            )
            save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin_add")
            return ADD_PRODUCT_PRICE
        
        context.user_data['price'] = price
        
        # Клавиатура с отменой
        keyboard = [[InlineKeyboardButton("❌ Отменить добавление", callback_data="admin_cancel_add")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = update.message.reply_text(
            "📏 Введите размеры через запятую (например: S,M,L,XL,36,37,38) или отправьте прочерк (-), если размеров нет:",
            reply_markup=reply_markup
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin_add")
        return ADD_PRODUCT_SIZES
    except Exception as e:
        logger.error(f"Error in admin_add_product_price: {e}")
        return ConversationHandler.END

def admin_add_product_sizes(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        save_message(user_id, update.message.chat_id, update.message.message_id, "admin_add")
        
        sizes = update.message.text.strip()
        if sizes == '-':
            sizes = ''
        context.user_data['sizes'] = sizes
        
        sent_msg = update.message.reply_text(
            "🖼 Отправьте фото товара (можно несколько).",
            reply_markup=admin_photo_options_keyboard()
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin_add")
        return ADD_PRODUCT_PHOTO
    except Exception as e:
        logger.error(f"Error in admin_add_product_sizes: {e}")
        return ConversationHandler.END

def admin_add_product_photo(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        save_message(user_id, update.message.chat_id, update.message.message_id, "admin_add")
        
        # Обработка фото
        if update.message.photo:
            photos = context.user_data.get('photos', [])
            file_id = update.message.photo[-1].file_id
            photos.append(file_id)
            context.user_data['photos'] = photos
            
            sent_msg = update.message.reply_text(
                f"🖼 Фото {len(photos)} добавлено. Выберите действие:",
                reply_markup=admin_photo_options_keyboard()
            )
            save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin_add")
            return ADD_PRODUCT_PHOTO
        else:
            sent_msg = update.message.reply_text(
                "❌ Пожалуйста, отправьте фото или выберите действие на клавиатуре:",
                reply_markup=admin_photo_options_keyboard()
            )
            save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin_add")
            return ADD_PRODUCT_PHOTO
    except Exception as e:
        logger.error(f"Error in admin_add_product_photo: {e}")
        return ConversationHandler.END

def admin_skip_photos(update: Update, context: CallbackContext):
    """Пропуск добавления фото"""
    try:
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        
        # Проверяем, что все необходимые данные есть
        required_fields = ['name', 'description', 'price', 'sizes']
        for field in required_fields:
            if field not in context.user_data:
                logger.error(f"Missing required field: {field}")
                return ConversationHandler.END
        
        # Создаем товар без фото
        product_id = add_product(
            name=context.user_data['name'],
            description=context.user_data['description'],
            price=context.user_data['price'],
            sizes=context.user_data['sizes'],
            subcategory_id=context.user_data.get('subcategory_id')
        )
        
        if not product_id:
            query.message.reply_text("❌ Ошибка при создании товара.")
            return ConversationHandler.END
        
        # Удаляем все сообщения процесса добавления
        delete_user_messages(user_id, "admin_add")
        
        # Отправляем сообщение об успехе
        safe_delete_message(context, query.message.chat_id, query.message.message_id)
        sent_msg = context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"✅ Товар успешно добавлен без фото! ID: {product_id}"
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin")
        
        context.bot.send_message(
            chat_id=query.message.chat_id,
            text="🔧 Админ-панель:",
            reply_markup=admin_menu_keyboard()
        )
        
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in admin_skip_photos: {e}")
        return ConversationHandler.END

def admin_finish_photos(update: Update, context: CallbackContext):
    """Завершение добавления с фото"""
    try:
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        
        # Проверяем, что все необходимые данные есть
        required_fields = ['name', 'description', 'price', 'sizes']
        for field in required_fields:
            if field not in context.user_data:
                logger.error(f"Missing required field: {field}")
                return ConversationHandler.END
        
        # Создаем товар
        product_id = add_product(
            name=context.user_data['name'],
            description=context.user_data['description'],
            price=context.user_data['price'],
            sizes=context.user_data['sizes'],
            subcategory_id=context.user_data.get('subcategory_id')
        )
        
        if not product_id:
            query.message.reply_text("❌ Ошибка при создании товара.")
            return ConversationHandler.END
        
        # Добавляем фото
        photos = context.user_data.get('photos', [])
        for idx, file_id in enumerate(photos):
            add_product_image(product_id, file_id, position=idx)
        
        photo_text = f" с {len(photos)} фото"
        
        # Удаляем все сообщения процесса добавления
        delete_user_messages(user_id, "admin_add")
        
        # Отправляем сообщение об успехе
        safe_delete_message(context, query.message.chat_id, query.message.message_id)
        sent_msg = context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"✅ Товар успешно добавлен{photo_text}! ID: {product_id}"
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "admin")
        
        context.bot.send_message(
            chat_id=query.message.chat_id,
            text="🔧 Админ-панель:",
            reply_markup=admin_menu_keyboard()
        )
        
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in admin_finish_photos: {e}")
        return ConversationHandler.END

def admin_cancel_add(update: Update, context: CallbackContext):
    """Отмена добавления товара"""
    try:
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
        # Удаляем сообщение с кнопками
        safe_delete_message(context, chat_id, query.message.message_id)
        
        return end_conversation_and_clear(user_id, context, chat_id, "❌ Добавление товара отменено.")
    except Exception as e:
        logger.error(f"Error in admin_cancel_add: {e}")
        return ConversationHandler.END

# -------------------- АДМИН ОБРАБОТЧИКИ (УДАЛЕНИЕ ТОВАРОВ) --------------------
def admin_delete_product_start(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        if not is_admin(query.from_user.id):
            query.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        
        products = get_all_products(limit=100)
        if not products:
            safe_edit_message_text(query, "📭 Нет товаров.")
            return
        
        keyboard = []
        for prod in products:
            keyboard.append([InlineKeyboardButton(f"❌ {prod['name']}", callback_data=f"adm_del_prod_{prod['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_back")])
        
        safe_edit_message_text(
            query,
            "🗑 Выберите товар для удаления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in admin_delete_product_start: {e}")

def admin_delete_product_confirm(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        prod_id = int(query.data.split('_')[3])
        product = get_product(prod_id)
        if not product:
            safe_edit_message_text(query, "❌ Товар не найден.")
            return
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"adm_del_prod_yes_{prod_id}"),
                InlineKeyboardButton("❌ Нет", callback_data="admin_back")
            ]
        ]
        safe_edit_message_text(
            query,
            f"Вы уверены, что хотите удалить товар «{product['name']}»?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in admin_delete_product_confirm: {e}")

def admin_delete_product_yes(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        prod_id = int(query.data.split('_')[4])
        delete_product_images(prod_id)
        delete_product(prod_id)
        safe_edit_message_text(query, "✅ Товар удалён.")
        query.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())
    except Exception as e:
        logger.error(f"Error in admin_delete_product_yes: {e}")

# -------------------- АДМИН ОБРАБОТЧИКИ (ЗАКАЗЫ) --------------------
def admin_orders(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        if not is_admin(query.from_user.id):
            query.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        
        orders = get_orders()
        if not orders:
            safe_edit_message_text(query, "📭 Заказов пока нет.")
            return
        
        page = 1
        per_page = 5
        total_pages = (len(orders) + per_page - 1) // per_page
        start = (page - 1) * per_page
        end = start + per_page
        page_orders = orders[start:end]
        
        safe_edit_message_text(
            query,
            "📦 Список заказов:",
            reply_markup=admin_orders_keyboard(page_orders, page, total_pages)
        )
    except Exception as e:
        logger.error(f"Error in admin_orders: {e}")

def admin_orders_page(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        page = int(query.data.split('_')[3])
        orders = get_orders()
        per_page = 5
        total_pages = (len(orders) + per_page - 1) // per_page
        start = (page - 1) * per_page
        end = start + per_page
        page_orders = orders[start:end]
        
        safe_edit_message_text(
            query,
            "📦 Список заказов:",
            reply_markup=admin_orders_keyboard(page_orders, page, total_pages)
        )
    except Exception as e:
        logger.error(f"Error in admin_orders_page: {e}")

def admin_order_detail(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        order_id = int(query.data.split('_')[2])
        order = get_order(order_id)
        if not order:
            safe_edit_message_text(query, "❌ Заказ не найден.")
            return
        
        status_display = ORDER_STATUSES.get(order['status'], order['status'])
        text = f"📦 *Заказ #{order['id']}*\n"
        text += f"📅 *Дата:* {order['created_at']}\n"
        text += f"👤 *Пользователь:* {order.get('username', order['user_id'])}\n"
        text += f"📞 *Контакт:* {order['contact']}\n"
        text += f"🏙 *Адрес:* {order['address']}\n"
        if order['comment']:
            text += f"📝 *Комментарий:* {order['comment']}\n"
        
        if order['status'] == 'rejected' and order.get('reject_reason'):
            text += f"❌ *Причина отказа:* {order['reject_reason']}\n"
        
        text += f"📌 *Статус:* {status_display}\n"
        text += "🛍 *Состав:*\n"
        for item in order['items']:
            text += f"  • {item['name']} x{item['quantity']} = {item['price']*item['quantity']} BYN"
            if item['size']:
                text += f" (размер {item['size']})"
            text += "\n"
        text += f"💰 *Итого: {order['total_price']} BYN*"
        
        safe_edit_message_text(
            query,
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_order_detail_keyboard(order_id)
        )
    except Exception as e:
        logger.error(f"Error in admin_order_detail: {e}")

def admin_set_order_status(update: Update, context: CallbackContext):
    """Обработчик установки статуса заказа"""
    try:
        query = update.callback_query
        query.answer()
        
        parts = query.data.split('_')
        order_id = int(parts[2])
        status = parts[3]
        
        if status == 'approved':
            # Просто одобряем заказ
            update_order_status(order_id, 'approved')
            
            # Отправляем уведомление пользователю
            order = get_order(order_id)
            if order:
                user_id = order['user_id']
                message = (
                    f"✅ *Ваш заказ #{order_id} одобрен!*\n\n"
                    f"Напишите админу для отправки: @matpluuux"
                )
                try:
                    context.bot.send_message(user_id, message, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id}: {e}")
            
            # Возвращаемся к деталям заказа
            admin_order_detail(update, context)
        
        elif status == 'rejected':
            # Запрашиваем причину отказа с возможностью отмены
            keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="admin_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            safe_edit_message_text(
                query,
                "❌ Введите причину отказа (одним сообщением):",
                reply_markup=reply_markup
            )
            context.user_data['reject_order_id'] = order_id
            return ORDER_REJECT_REASON
    except Exception as e:
        logger.error(f"Error in admin_set_order_status: {e}")
        return ConversationHandler.END

def admin_custom_reject_reason(update: Update, context: CallbackContext):
    """Получение своей причины отказа"""
    try:
        reason = update.message.text.strip()
        
        order_id = context.user_data.get('reject_order_id')
        if not order_id:
            update.message.reply_text("❌ Ошибка: заказ не найден.")
            return ConversationHandler.END
        
        # Обновляем статус с причиной
        update_order_status(order_id, 'rejected', reason)
        
        # Отправляем уведомление пользователю
        order = get_order(order_id)
        if order:
            user_id = order['user_id']
            message = (
                f"❌ *Ваш заказ #{order_id} отклонён*\n\n"
                f"📌 *Причина:* {reason}\n\n"
                f"Если у вас есть вопросы, свяжитесь с поддержкой @matpluuux"
            )
            try:
                context.bot.send_message(user_id, message, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
        
        update.message.reply_text(f"✅ Заказ #{order_id} отклонён с причиной: {reason}")
        
        # Очищаем данные
        if 'reject_order_id' in context.user_data:
            del context.user_data['reject_order_id']
        
        # Возвращаемся к списку заказов
        # Создаем фиктивный update для admin_orders
        class FakeQuery:
            def __init__(self, user_id, message):
                self.from_user = type('User', (), {'id': user_id})()
                self.message = message
            def answer(self): pass
        
        fake_update = type('Update', (), {
            'callback_query': FakeQuery(update.effective_user.id, update.message)
        })()
        admin_orders(fake_update, context)
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in admin_custom_reject_reason: {e}")
        return ConversationHandler.END

# -------------------- АДМИН ОБРАБОТЧИКИ (СТАТИСТИКА) --------------------
def admin_stats(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        if not is_admin(query.from_user.id):
            query.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        
        stats = get_statistics()
        text = (
            f"📊 *Статистика*\n\n"
            f"👤 Пользователей: {stats['users']}\n"
            f"📦 Товаров: {stats['products']}\n"
            f"🛍 Заказов: {stats['orders']}\n"
            f"💰 Выручка (одобренные): {stats['revenue']} BYN"
        )
        safe_edit_message_text(query, text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in admin_stats: {e}")

# -------------------- АДМИН ОБРАБОТЧИКИ (РАССЫЛКА) --------------------
def admin_mailing(update: Update, context: CallbackContext):
    """Начало рассылки"""
    try:
        query = update.callback_query
        query.answer()
        
        if not is_admin(query.from_user.id):
            query.answer("⛔ Доступ запрещён.", show_alert=True)
            return ConversationHandler.END
        
        # Очищаем старые данные рассылки
        if 'mailing_text' in context.user_data:
            del context.user_data['mailing_text']
        if 'mailing_users' in context.user_data:
            del context.user_data['mailing_users']
        
        # Клавиатура с отменой
        keyboard = [[InlineKeyboardButton("❌ Отменить рассылку", callback_data="mailing_cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        safe_edit_message_text(
            query,
            "📨 Введите текст для рассылки (можно использовать Markdown):",
            reply_markup=reply_markup
        )
        return MAILING_TEXT
    except Exception as e:
        logger.error(f"Error in admin_mailing: {e}")
        return ConversationHandler.END

def admin_mailing_text(update: Update, context: CallbackContext):
    """Получение текста рассылки"""
    try:
        text = update.message.text.strip()
        
        # Проверка на пустой текст
        if not text:
            update.message.reply_text("❌ Текст не может быть пустым. Попробуйте снова:")
            return MAILING_TEXT
        
        context.user_data['mailing_text'] = text
        
        users = get_all_users()
        context.user_data['mailing_users'] = users
        
        preview = f"📨 *Превью рассылки:*\n\n{text}\n\n"
        preview += f"📊 *Всего получателей:* {len(users)}"
        
        # Удаляем предыдущее сообщение с запросом текста
        try:
            context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=update.message.message_id - 1
            )
        except:
            pass
        
        update.message.reply_text(
            preview,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=mailing_confirm_keyboard()
        )
        return MAILING_CONFIRM
    except Exception as e:
        logger.error(f"Error in admin_mailing_text: {e}")
        return ConversationHandler.END

def admin_mailing_send(update: Update, context: CallbackContext):
    """Отправка рассылки"""
    try:
        query = update.callback_query
        query.answer()
        
        # Проверяем, есть ли данные рассылки
        if 'mailing_text' not in context.user_data or 'mailing_users' not in context.user_data:
            safe_edit_message_text(query, "❌ Ошибка: данные рассылки не найдены. Начните заново.")
            query.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())
            return ConversationHandler.END
        
        text = context.user_data['mailing_text']
        users = context.user_data['mailing_users']
        
        safe_edit_message_text(query, "📨 Рассылка началась... Это может занять некоторое время.")
        
        success = 0
        failed = 0
        
        for user in users:
            try:
                context.bot.send_message(
                    user['telegram_id'],
                    text,
                    parse_mode=ParseMode.MARKDOWN
                )
                success += 1
            except Exception as e:
                logger.error(f"Failed to send to {user['telegram_id']}: {e}")
                failed += 1
        
        # Отправляем отчет
        query.message.reply_text(
            f"✅ Рассылка завершена!\n"
            f"📨 Успешно отправлено: {success}\n"
            f"❌ Не удалось отправить: {failed}"
        )
        
        # Возвращаемся в админ-панель
        query.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())
        
        # Очищаем данные рассылки
        if 'mailing_text' in context.user_data:
            del context.user_data['mailing_text']
        if 'mailing_users' in context.user_data:
            del context.user_data['mailing_users']
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in admin_mailing_send: {e}")
        return ConversationHandler.END

def admin_mailing_cancel(update: Update, context: CallbackContext):
    """Отмена рассылки"""
    try:
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
        # Удаляем сообщение с кнопками
        safe_delete_message(context, chat_id, query.message.message_id)
        
        return end_conversation_and_clear(user_id, context, chat_id, "❌ Рассылка отменена.")
    except Exception as e:
        logger.error(f"Error in admin_mailing_cancel: {e}")
        return ConversationHandler.END

# -------------------- ОБРАБОТЧИКИ ПОИСКА --------------------
def search_query(update: Update, context: CallbackContext):
    try:
        query_text = update.message.text.strip()
        if len(query_text) < 2:
            update.message.reply_text("❌ Слишком короткий запрос. Введите минимум 2 символа.")
            return SEARCH_QUERY
        
        context.user_data['search_query'] = query_text
        show_search_results(update.message, query_text, 1, context)
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in search_query: {e}")
        return ConversationHandler.END

def show_search_results(message, query: str, page: int, context: CallbackContext):
    try:
        offset = (page - 1) * 10
        results = search_products(query, limit=10, offset=offset)
        total = count_search_products(query)
        total_pages = (total + 9) // 10
        
        if not results:
            message.reply_text("😕 Ничего не найдено.")
            return
        
        text = f"🔍 Результаты поиска по запросу «{query}» (стр. {page}/{total_pages}):"
        message.reply_text(text, reply_markup=search_keyboard(results, page, total_pages, query))
    except Exception as e:
        logger.error(f"Error in show_search_results: {e}")

def callback_search_page(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        parts = query.data.split('_')
        query_text = parts[2]
        page = int(parts[3])
        show_search_results(query.message, query_text, page, context)
    except Exception as e:
        logger.error(f"Error in callback_search_page: {e}")

# -------------------- ОБЩИЕ ОБРАБОТЧИКИ --------------------
def callback_back_to_main(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        
        delete_user_messages(user_id)
        
        safe_delete_message(context, query.message.chat_id, query.message.message_id)
        
        admin_flag = is_admin(user_id)
        sent_msg = context.bot.send_message(
            chat_id=query.message.chat_id,
            text="🏠 Главное меню:",
            reply_markup=get_main_menu_keyboard(admin_flag)
        )
        save_message(user_id, sent_msg.chat_id, sent_msg.message_id, "menu")
    except Exception as e:
        logger.error(f"Error in callback_back_to_main: {e}")

def callback_admin_back(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        if not is_admin(query.from_user.id):
            query.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        safe_edit_message_text(
            query,
            "🔧 Админ-панель:",
            reply_markup=admin_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in callback_admin_back: {e}")

def callback_ignore(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
    except Exception as e:
        logger.error(f"Error in callback_ignore: {e}")

def callback_unknown(update: Update, context: CallbackContext):
    """Обработчик неизвестных callback запросов"""
    try:
        query = update.callback_query
        query.answer("❌ Неизвестная команда")
        logger.warning(f"Unknown callback data: {query.data}")
    except Exception as e:
        logger.error(f"Error in callback_unknown: {e}")

# -------------------- ОСНОВНАЯ ФУНКЦИЯ --------------------
def main():
    try:
        # Инициализация БД
        init_db()
        logger.info("Database initialized")

        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher

        # Глобальный обработчик ошибок
        dp.add_error_handler(error_handler)

        # Команды
        dp.add_handler(CommandHandler('start', start))

        # Поиск
        search_conv = ConversationHandler(
            entry_points=[CommandHandler('search', search_command)],
            states={
                SEARCH_QUERY: [MessageHandler(Filters.text & ~Filters.command, search_query)]
            },
            fallbacks=[CallbackQueryHandler(cancel_search, pattern='^cancel_search$')],
            per_message=False,
            allow_reentry=True
        )
        dp.add_handler(search_conv)

        # Оформление заказа
        checkout_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(checkout_start, pattern='^checkout$')],
            states={
                CHECKOUT_CONTACT: [MessageHandler(Filters.text & ~Filters.command, checkout_contact)],
                CHECKOUT_ADDRESS: [MessageHandler(Filters.text & ~Filters.command, checkout_address)],
                CHECKOUT_COMMENT: [MessageHandler(Filters.text & ~Filters.command, checkout_comment)],
                CHECKOUT_CONFIRM: [CallbackQueryHandler(checkout_confirm, pattern='^checkout_confirm$')]
            },
            fallbacks=[CallbackQueryHandler(checkout_cancel, pattern='^checkout_cancel$')],
            per_message=False,
            allow_reentry=True
        )
        dp.add_handler(checkout_conv)

        # Добавление товара
        add_product_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_add_product_start, pattern='^admin_add_product$')],
            states={
                SUBCATEGORY_SELECTION: [
                    CallbackQueryHandler(admin_choose_subcategory, pattern='^admin_sub_'),
                    CallbackQueryHandler(admin_cancel_add, pattern='^admin_cancel_add$')
                ],
                ADD_PRODUCT_NAME: [
                    MessageHandler(Filters.text & ~Filters.command, admin_add_product_name)
                ],
                ADD_PRODUCT_DESCRIPTION: [
                    MessageHandler(Filters.text & ~Filters.command, admin_add_product_description)
                ],
                ADD_PRODUCT_PRICE: [
                    MessageHandler(Filters.text & ~Filters.command, admin_add_product_price)
                ],
                ADD_PRODUCT_SIZES: [
                    MessageHandler(Filters.text & ~Filters.command, admin_add_product_sizes)
                ],
                ADD_PRODUCT_PHOTO: [
                    MessageHandler(Filters.photo, admin_add_product_photo),
                    CallbackQueryHandler(admin_skip_photos, pattern='^admin_skip_photos$'),
                    CallbackQueryHandler(admin_finish_photos, pattern='^admin_finish_photos$')
                ]
            },
            fallbacks=[CallbackQueryHandler(admin_cancel_add, pattern='^admin_cancel_add$')],
            per_message=False,
            allow_reentry=True
        )
        dp.add_handler(add_product_conv)

        # Рассылка
        mailing_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_mailing, pattern='^admin_mailing$')],
            states={
                MAILING_TEXT: [MessageHandler(Filters.text & ~Filters.command, admin_mailing_text)],
                MAILING_CONFIRM: [CallbackQueryHandler(admin_mailing_send, pattern='^mailing_send$')]
            },
            fallbacks=[CallbackQueryHandler(admin_mailing_cancel, pattern='^mailing_cancel$')],
            per_message=False,
            allow_reentry=True
        )
        dp.add_handler(mailing_conv)

        # Причина отказа
        reject_reason_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_set_order_status, pattern='^set_status_.*_rejected$')],
            states={
                ORDER_REJECT_REASON: [MessageHandler(Filters.text & ~Filters.command, admin_custom_reject_reason)]
            },
            fallbacks=[CallbackQueryHandler(callback_admin_back, pattern='^admin_back$')],
            per_message=False,
            allow_reentry=True
        )
        dp.add_handler(reject_reason_conv)

        # Одобрение заказа
        dp.add_handler(CallbackQueryHandler(admin_set_order_status, pattern='^set_status_.*_approved$'))

        # Текстовые кнопки
        dp.add_handler(MessageHandler(Filters.regex('^🛍 Ассортимент$'), handle_assortment))
        dp.add_handler(MessageHandler(Filters.regex('^🛒 Корзина$'), handle_cart))
        dp.add_handler(MessageHandler(Filters.regex('^📦 Мои заказы$'), handle_my_orders))
        dp.add_handler(MessageHandler(Filters.regex('^ℹ️ О нас$'), handle_about))
        dp.add_handler(MessageHandler(Filters.regex('^📞 Поддержка$'), handle_support))
        dp.add_handler(MessageHandler(Filters.regex('^🌐 Соцсети$'), handle_social))
        dp.add_handler(MessageHandler(Filters.regex('^🔧 Админ панель$'), handle_admin_panel))

        # Callback-запросы
        dp.add_handler(CallbackQueryHandler(callback_show_subcategories, pattern='^cat_'))
        dp.add_handler(CallbackQueryHandler(callback_show_products_by_subcategory, pattern='^subcat_'))
        dp.add_handler(CallbackQueryHandler(callback_subcat_products_page, pattern='^subcat_prod_page_'))
        dp.add_handler(CallbackQueryHandler(callback_back_to_subcategories, pattern='^back_to_subcats_'))
        dp.add_handler(CallbackQueryHandler(callback_back_to_assortment, pattern='^back_to_assortment$'))
        
        dp.add_handler(CallbackQueryHandler(callback_product, pattern='^prod_'))
        dp.add_handler(CallbackQueryHandler(callback_product_photo_nav, pattern='^photo_'))
        dp.add_handler(CallbackQueryHandler(callback_size, pattern='^size_'))
        dp.add_handler(CallbackQueryHandler(callback_add_to_cart, pattern='^add_'))
        dp.add_handler(CallbackQueryHandler(callback_back_to_products, pattern='^back_to_products_\d+$'))
        dp.add_handler(CallbackQueryHandler(callback_back_to_products_all, pattern='^back_to_products_all$'))
        
        dp.add_handler(CallbackQueryHandler(cart_increase, pattern='^cart_inc_'))
        dp.add_handler(CallbackQueryHandler(cart_decrease, pattern='^cart_dec_'))
        dp.add_handler(CallbackQueryHandler(cart_delete, pattern='^cart_del_'))
        dp.add_handler(CallbackQueryHandler(cart_clear, pattern='^cart_clear$'))
        
        dp.add_handler(CallbackQueryHandler(callback_user_order_detail, pattern='^user_order_'))
        dp.add_handler(CallbackQueryHandler(callback_user_orders_page, pattern='^user_orders_page_'))
        
        dp.add_handler(CallbackQueryHandler(admin_delete_product_start, pattern='^admin_delete_product$'))
        dp.add_handler(CallbackQueryHandler(admin_delete_product_confirm, pattern=r'^adm_del_prod_\d+$'))
        dp.add_handler(CallbackQueryHandler(admin_delete_product_yes, pattern='^adm_del_prod_yes_'))
        
        dp.add_handler(CallbackQueryHandler(admin_orders, pattern='^admin_orders$'))
        dp.add_handler(CallbackQueryHandler(admin_orders_page, pattern='^admin_orders_page_'))
        dp.add_handler(CallbackQueryHandler(admin_order_detail, pattern='^admin_order_'))
        
        dp.add_handler(CallbackQueryHandler(admin_stats, pattern='^admin_stats$'))
        dp.add_handler(CallbackQueryHandler(callback_admin_back, pattern='^admin_back$'))
        
        dp.add_handler(CallbackQueryHandler(callback_search_page, pattern='^search_page_'))
        dp.add_handler(CallbackQueryHandler(callback_back_to_main, pattern='^back_to_main$'))
        dp.add_handler(CallbackQueryHandler(callback_ignore, pattern='^ignore$'))
        
        # Обработчик неизвестных callback_data (всегда последний)
        dp.add_handler(CallbackQueryHandler(callback_unknown, pattern='.*'))

        logger.info("Starting bot polling")
        updater.start_polling()
        updater.idle()
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        raise

if __name__ == "__main__":
    main()

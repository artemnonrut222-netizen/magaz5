#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAWWEAR Telegram Shop Bot
Версия для Termux на python-telegram-bot v13.x (исправленная)
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import List, Optional, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto, ParseMode
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, MessageHandler, 
    Filters, CallbackContext, ConversationHandler
)
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

# -------------------- СОСТОЯНИЯ ДЛЯ CONVERSATION HANDLER --------------------
(
    CATEGORY_SELECTION, SUBCATEGORY_SELECTION, ADD_PRODUCT_NAME, 
    ADD_PRODUCT_DESCRIPTION, ADD_PRODUCT_PRICE, ADD_PRODUCT_SIZES, 
    ADD_PRODUCT_PHOTO, CHECKOUT_CONTACT, CHECKOUT_ADDRESS, 
    CHECKOUT_COMMENT, CHECKOUT_CONFIRM, SEARCH_QUERY
) = range(12)

# -------------------- СТАТУСЫ ЗАКАЗОВ НА РУССКОМ --------------------
ORDER_STATUSES = {
    'new': '🟡 Новый',
    'processing': '🟠 В обработке',
    'shipped': '🔵 Отправлен',
    'completed': '✅ Завершён',
    'cancelled': '❌ Отменён'
}

# -------------------- DATABASE --------------------
@contextmanager
def db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        conn.close()

def init_db():
    """Создание таблиц с категориями и подкатегориями"""
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

        # Индексы
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cart_user ON cart(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_product_images_product ON product_images(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_subcategory ON products(subcategory_id)")

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

# -------------------- DATABASE FUNCTIONS --------------------
def add_user(telegram_id: int, username: str = None):
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?, ?)",
            (telegram_id, username)
        )

def get_all_products(offset: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, price FROM products ORDER BY name LIMIT ? OFFSET ?",
            (limit, offset)
        )
        return [dict(row) for row in cursor.fetchall()]

def count_all_products() -> int:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM products")
        return cursor.fetchone()[0]

def get_product(product_id: int) -> Optional[Dict[str, Any]]:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, description, price, sizes, subcategory_id FROM products WHERE id = ?",
            (product_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

def add_product(name: str, description: str, price: int, sizes: str, subcategory_id: Optional[int] = None) -> int:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO products (name, description, price, sizes, subcategory_id) VALUES (?, ?, ?, ?, ?)",
            (name, description, price, sizes, subcategory_id)
        )
        return cursor.lastrowid

def delete_product(product_id: int):
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))

def add_product_image(product_id: int, file_id: str, position: int = 0):
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO product_images (product_id, file_id, position) VALUES (?, ?, ?)",
            (product_id, file_id, position)
        )

def get_product_images(product_id: int) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, file_id, position FROM product_images WHERE product_id = ? ORDER BY position",
            (product_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

def delete_product_images(product_id: int):
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM product_images WHERE product_id = ?", (product_id,))

def search_products(query: str, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, price FROM products WHERE name LIKE ? ORDER BY name LIMIT ? OFFSET ?",
            (f"%{query}%", limit, offset)
        )
        return [dict(row) for row in cursor.fetchall()]

def count_search_products(query: str) -> int:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM products WHERE name LIKE ?", (f"%{query}%",))
        return cursor.fetchone()[0]

def get_cart(user_id: int) -> List[Dict[str, Any]]:
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

def add_to_cart(user_id: int, product_id: int, size: str = None) -> bool:
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

def update_cart_quantity(cart_item_id: int, delta: int) -> bool:
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

def remove_from_cart(cart_item_id: int):
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart WHERE id = ?", (cart_item_id,))

def clear_cart(user_id: int):
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))

def create_order(user_id: int, contact: str, address: str, comment: str = "") -> Optional[int]:
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

def get_orders(status: Optional[str] = None) -> List[Dict[str, Any]]:
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

def get_user_orders(user_id: int) -> List[Dict[str, Any]]:
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

def update_order_status(order_id: int, status: str) -> bool:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        return cursor.rowcount > 0

def get_order(order_id: int) -> Optional[Dict[str, Any]]:
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

def get_statistics() -> Dict[str, Any]:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM products")
        products = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM orders")
        orders = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(total_price) FROM orders WHERE status = 'completed'")
        revenue = cursor.fetchone()[0] or 0
        return {
            "users": users,
            "products": products,
            "orders": orders,
            "revenue": revenue
        }

# -------------------- ФУНКЦИИ ДЛЯ КАТЕГОРИЙ/ПОДКАТЕГОРИЙ --------------------
def get_all_categories() -> List[Dict[str, Any]]:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM categories ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]

def get_subcategories(category_id: int) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name FROM subcategories WHERE category_id = ? ORDER BY name",
            (category_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

def get_all_subcategories_with_category() -> List[Dict[str, Any]]:
    """Возвращает все подкатегории с названием категории для отображения в админке"""
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id, s.name, c.name as category_name
            FROM subcategories s
            JOIN categories c ON s.category_id = c.id
            ORDER BY c.name, s.name
        """)
        return [dict(row) for row in cursor.fetchall()]

def get_products_by_subcategory(subcategory_id: int, offset: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, price FROM products WHERE subcategory_id = ? ORDER BY name LIMIT ? OFFSET ?",
            (subcategory_id, limit, offset)
        )
        return [dict(row) for row in cursor.fetchall()]

def count_products_by_subcategory(subcategory_id: int) -> int:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM products WHERE subcategory_id = ?", (subcategory_id,))
        return cursor.fetchone()[0]

# -------------------- ФУНКЦИИ ДЛЯ КЛАВИАТУР --------------------
def get_main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню с опциональной кнопкой админ-панели для администратора"""
    buttons = [
        [KeyboardButton("🛍 Ассортимент")],
        [KeyboardButton("🛒 Корзина"), KeyboardButton("📦 Мои заказы")],
        [KeyboardButton("ℹ️ О нас"), KeyboardButton("📞 Поддержка")]
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
        [InlineKeyboardButton("🔙 Выход", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def assortment_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с 3 кнопками: Одежда, Обувь, Аксессуары"""
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
            f"{prod['name']} - {prod['price']} ₽", 
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
        # Разбиваем на ряды по 3 кнопки
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

    if subcategory_id:
        keyboard.append([InlineKeyboardButton("🔙 К товарам", callback_data=f"back_to_subcat_products_{subcategory_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🔙 К товарам", callback_data="back_to_products_all")])
    
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
            f"Заказ #{order['id']} ({status_display}) - {order['total_price']} ₽",
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
    keyboard = []
    statuses = [
        ('new', '🟡 Новый'),
        ('processing', '🟠 В обработке'),
        ('shipped', '🔵 Отправлен'),
        ('completed', '✅ Завершён'),
        ('cancelled', '❌ Отменён')
    ]
    status_row = []
    for status_key, status_name in statuses:
        status_row.append(InlineKeyboardButton(status_name, callback_data=f"set_status_{order_id}_{status_key}"))
        if len(status_row) == 2:
            keyboard.append(status_row)
            status_row = []
    if status_row:
        keyboard.append(status_row)
    
    keyboard.append([InlineKeyboardButton("🔙 К заказам", callback_data="admin_orders")])
    return InlineKeyboardMarkup(keyboard)

def search_keyboard(results: List[Dict[str, Any]], page: int, total_pages: int, query: str) -> InlineKeyboardMarkup:
    keyboard = []
    for prod in results:
        keyboard.append([InlineKeyboardButton(
            f"{prod['name']} - {prod['price']} ₽",
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
            f"Заказ #{order['id']} {status_display} - {order['total_price']} ₽",
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

# -------------------- ОБРАБОТЧИКИ КОМАНД --------------------
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    username = update.effective_user.username
    add_user(user_id, username)

    welcome_text = (
        "👋 Привет! Я ваш бот‑помощник телеграма RAWWEAR\n"
        "Помогу вам в выборе и заказе самой актуальной и качественной одежды⬇️"
    )

    if BOT_AVATAR_FILE_ID:
        try:
            context.bot.send_photo(
                chat_id=update.message.chat_id,
                photo=BOT_AVATAR_FILE_ID,
                caption=welcome_text
            )
        except Exception as e:
            logger.error(f"Failed to send avatar: {e}")
            update.message.reply_text(welcome_text)
    else:
        update.message.reply_text(welcome_text)

    admin_flag = is_admin(user_id)
    update.message.reply_text(
        "👇 Выберите действие:",
        reply_markup=get_main_menu_keyboard(admin_flag)
    )

def search_command(update: Update, context: CallbackContext):
    update.message.reply_text("🔍 Введите название товара для поиска:")
    return SEARCH_QUERY

# -------------------- ОБРАБОТЧИКИ ТЕКСТОВЫХ КНОПОК --------------------
def handle_assortment(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📂 Выберите категорию:",
        reply_markup=assortment_keyboard()
    )

def handle_cart(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    cart_items = get_cart(user_id)
    if not cart_items:
        update.message.reply_text("🛒 Ваша корзина пуста.")
        return
    text = "🛒 *Ваша корзина:*\n\n"
    total = 0
    for item in cart_items:
        text += f"• {item['name']} "
        if item['size']:
            text += f"(размер {item['size']}) "
        text += f"x{item['quantity']} = {item['price'] * item['quantity']} ₽\n"
        total += item['price'] * item['quantity']
    text += f"\n💰 *Итого: {total} ₽*"
    update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cart_keyboard(cart_items)
    )

def handle_my_orders(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    orders = get_user_orders(user_id)
    if not orders:
        update.message.reply_text("📭 У вас пока нет заказов.")
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
        text += f"• #{order['id']} от {order['created_at'][:10]} — {order['total_price']} ₽ ({status_display})\n"
    update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=user_orders_keyboard(page_orders, page, total_pages)
    )

def handle_about(update: Update, context: CallbackContext):
    update.message.reply_text(
        "ℹ️ *О нас*\n\n"
        "Мы — RAWWEAR, бренд уличной одежды.\n"
        "Работаем с 2025 года. Все товары сертифицированы.\n\n"
        "✨ Спасибо, что выбираете нас!",
        parse_mode=ParseMode.MARKDOWN
    )

def handle_support(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📞 Поддержка\n\n"
        "Если у вас возникли вопросы, напишите нам:\n"
        "📱 Telegram: @matpluuux\n"
        "⏰ Время работы: круглосуточно"
    )

def handle_admin_panel(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("⛔ Доступ запрещён.")
        return
    update.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())

# -------------------- ОБРАБОТЧИКИ КАТЕГОРИЙ/ПОДКАТЕГОРИЙ --------------------
def callback_show_subcategories(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    category_id = int(query.data.split('_')[1])
    subcategories = get_subcategories(category_id)
    if not subcategories:
        query.edit_message_text("😕 В этой категории пока нет подкатегорий.")
        return
    query.edit_message_text(
        "📂 Выберите подкатегорию:",
        reply_markup=subcategories_keyboard(subcategories)
    )

def callback_show_products_by_subcategory(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    subcategory_id = int(query.data.split('_')[1])
    show_products_by_subcategory(query.message, subcategory_id, 1, context)

def show_products_by_subcategory(message, subcategory_id: int, page: int, context: CallbackContext):
    offset = (page - 1) * 10
    products = get_products_by_subcategory(subcategory_id, offset=offset)
    total = count_products_by_subcategory(subcategory_id)
    total_pages = (total + 9) // 10

    if not products:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 К подкатегориям", callback_data=f"back_to_subcats_{subcategory_id}")
        ]])
        message.edit_text("📭 В этой подкатегории пока нет товаров.", reply_markup=keyboard)
        return

    message.edit_text(
        f"📦 Товары (стр. {page}/{total_pages}):",
        reply_markup=products_keyboard(products, page, total_pages, subcategory_id)
    )

def callback_subcat_products_page(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    parts = query.data.split('_')
    subcategory_id = int(parts[3])
    page = int(parts[4])
    show_products_by_subcategory(query.message, subcategory_id, page, context)

def callback_back_to_subcategories(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    subcategory_id = int(query.data.split('_')[3])
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT category_id FROM subcategories WHERE id = ?", (subcategory_id,))
        row = cursor.fetchone()
        if not row:
            query.edit_message_text("❌ Ошибка: подкатегория не найдена.")
            return
        category_id = row['category_id']
    subcategories = get_subcategories(category_id)
    query.edit_message_text(
        "📂 Выберите подкатегорию:",
        reply_markup=subcategories_keyboard(subcategories)
    )

def callback_back_to_assortment(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        "📂 Выберите категорию:",
        reply_markup=assortment_keyboard()
    )

# -------------------- ОБРАБОТЧИКИ ТОВАРОВ --------------------
def callback_product(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    parts = query.data.split('_')
    prod_id = int(parts[1])
    subcategory_id = int(parts[2]) if len(parts) > 2 and parts[2] != '0' else None
    product = get_product(prod_id)
    if not product:
        query.edit_message_text("❌ Товар не найден.")
        return

    sizes_list = parse_sizes(product['sizes'])
    images = get_product_images(prod_id)

    if not images:
        text = f"🧥 *{product['name']}*\n\n"
        text += f"💰 *Цена:* {product['price']} ₽\n"
        text += f"📝 *Описание:* {product['description']}\n"
        if sizes_list:
            text += f"📏 *Размеры:* {', '.join(sizes_list)}\n"
        else:
            text += "📏 Размеры: единый размер.\n"
        keyboard = product_detail_keyboard(prod_id, sizes_list, 0, 0, subcategory_id)
        query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    else:
        current = 1
        total = len(images)
        img = images[0]
        text = f"🧥 *{product['name']}*\n\n"
        text += f"💰 *Цена:* {product['price']} ₽\n"
        text += f"📝 *Описание:* {product['description']}\n"
        if sizes_list:
            text += f"📏 *Размеры:* {', '.join(sizes_list)}\n"
        else:
            text += "📏 Размеры: единый размер.\n"
        keyboard = product_detail_keyboard(prod_id, sizes_list, current, total, subcategory_id)
        
        # Удаляем старое сообщение и отправляем фото
        query.message.delete()
        context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=img['file_id'],
            caption=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

def callback_product_photo_nav(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    parts = query.data.split('_')
    prod_id = int(parts[1])
    target = int(parts[2])
    product = get_product(prod_id)
    if not product:
        query.edit_message_text("❌ Товар не найден.")
        return

    images = get_product_images(prod_id)
    if not images or target < 1 or target > len(images):
        query.answer("❌ Изображение не найдено.")
        return

    sizes_list = parse_sizes(product['sizes'])
    img = images[target - 1]
    text = f"🧥 *{product['name']}*\n\n"
    text += f"💰 *Цена:* {product['price']} ₽\n"
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
        # Если не получается отредактировать, удаляем и отправляем новое
        query.message.delete()
        context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=img['file_id'],
            caption=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

def callback_size(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    parts = query.data.split('_')
    prod_id = int(parts[1])
    size = parts[2]
    context.user_data['selected_size'] = size
    context.user_data['selected_product'] = prod_id
    query.message.reply_text(f"📏 Выбран размер {size}. Теперь нажмите «➕ Добавить в корзину».")

def callback_add_to_cart(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    parts = query.data.split('_')
    prod_id = int(parts[1])
    size = context.user_data.get('selected_size')
    success = add_to_cart(query.from_user.id, prod_id, size)
    if 'selected_size' in context.user_data:
        del context.user_data['selected_size']
    if success:
        query.message.reply_text("✅ Товар добавлен в корзину.")
    else:
        query.message.reply_text("❌ Не удалось добавить товар.")

def callback_back_to_subcat_products(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    subcategory_id = int(query.data.split('_')[4])
    show_products_by_subcategory(query.message, subcategory_id, 1, context)

def callback_back_to_products_all(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    callback_back_to_assortment(update, context)

# -------------------- ОБРАБОТЧИКИ КОРЗИНЫ --------------------
def cart_increase(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    item_id = int(query.data.split('_')[2])
    update_cart_quantity(item_id, delta=1)
    update_cart_message(query)

def cart_decrease(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    item_id = int(query.data.split('_')[2])
    update_cart_quantity(item_id, delta=-1)
    update_cart_message(query)

def cart_delete(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    item_id = int(query.data.split('_')[2])
    remove_from_cart(item_id)
    update_cart_message(query)

def cart_clear(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    clear_cart(query.from_user.id)
    query.edit_message_text("🛒 Корзина очищена.")

def update_cart_message(query):
    user_id = query.from_user.id
    cart_items = get_cart(user_id)
    if not cart_items:
        query.edit_message_text("🛒 Корзина пуста.")
        return
    text = "🛒 *Ваша корзина:*\n\n"
    total = 0
    for item in cart_items:
        text += f"• {item['name']} "
        if item['size']:
            text += f"(размер {item['size']}) "
        text += f"x{item['quantity']} = {item['price'] * item['quantity']} ₽\n"
        total += item['price'] * item['quantity']
    text += f"\n💰 *Итого: {total} ₽*"
    query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cart_keyboard(cart_items)
    )

# -------------------- ОБРАБОТЧИКИ ОФОРМЛЕНИЯ ЗАКАЗА --------------------
def checkout_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    cart_items = get_cart(user_id)
    if not cart_items:
        query.message.reply_text("🛒 Корзина пуста.")
        return ConversationHandler.END
    
    query.message.reply_text(
        "📞 Напишите свой юзернейм или номер телефона, чтобы мы могли связаться с вами."
    )
    return CHECKOUT_CONTACT

def checkout_contact(update: Update, context: CallbackContext):
    contact = update.message.text.strip()
    context.user_data['contact'] = contact
    update.message.reply_text("🏙 Введите ваш город и адрес доставки.")
    return CHECKOUT_ADDRESS

def checkout_address(update: Update, context: CallbackContext):
    address = update.message.text.strip()
    context.user_data['address'] = address
    update.message.reply_text("📝 Введите комментарий к заказу (необязательно). Можно отправить прочерк '-'.")
    return CHECKOUT_COMMENT

def checkout_comment(update: Update, context: CallbackContext):
    comment = update.message.text.strip()
    if comment == '-':
        comment = ""
    context.user_data['comment'] = comment
    
    user_id = update.effective_user.id
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
        text += f"x{item['quantity']} = {item['price'] * item['quantity']} ₽\n"
        total += item['price'] * item['quantity']
    text += f"\n💰 *Итого: {total} ₽*"
    
    update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=checkout_confirm_keyboard()
    )
    return CHECKOUT_CONFIRM

def checkout_confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    order_id = create_order(
        user_id, 
        context.user_data['contact'], 
        context.user_data['address'], 
        context.user_data.get('comment', '')
    )
    
    # Очищаем данные пользователя
    for key in ['contact', 'address', 'comment']:
        if key in context.user_data:
            del context.user_data[key]
    
    if order_id:
        query.edit_message_text("✅ Заказ успешно оформлен! Мы свяжемся с вами для подтверждения.")
        order = get_order(order_id)
        items_text = ""
        for item in order['items']:
            items_text += f"• {item['name']} x{item['quantity']} = {item['price']*item['quantity']} ₽\n"
        admin_msg = (
            f"🆕 *Новый заказ #{order_id}*\n\n"
            f"👤 *Пользователь:* {query.from_user.full_name} (@{query.from_user.username})\n"
            f"📞 *Контакт:* {order['contact']}\n"
            f"🏙 *Адрес:* {order['address']}\n"
            f"📝 *Комментарий:* {order['comment'] or '—'}\n\n"
            f"🛍 *Состав:*\n{items_text}"
            f"💰 *Итого:* {order['total_price']} ₽"
        )
        notify_admins(context.bot, admin_msg)
    else:
        query.edit_message_text("❌ Ошибка при оформлении заказа. Попробуйте позже.")
    
    return ConversationHandler.END

def checkout_cancel(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text("❌ Оформление заказа отменено.")
    return ConversationHandler.END

# -------------------- ОБРАБОТЧИКИ ЗАКАЗОВ ПОЛЬЗОВАТЕЛЯ --------------------
def callback_user_order_detail(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    order_id = int(query.data.split('_')[2])
    order = get_order(order_id)
    if not order:
        query.edit_message_text("❌ Заказ не найден.")
        return
    status_display = ORDER_STATUSES.get(order['status'], order['status'])
    text = f"📦 *Заказ #{order['id']}*\n"
    text += f"📅 *Дата:* {order['created_at']}\n"
    text += f"📌 *Статус:* {status_display}\n"
    text += f"📞 *Контакт:* {order['contact']}\n"
    text += f"🏙 *Адрес:* {order['address']}\n"
    if order['comment']:
        text += f"📝 *Комментарий:* {order['comment']}\n"
    text += "🛍 *Состав:*\n"
    for item in order['items']:
        text += f"  • {item['name']} x{item['quantity']} = {item['price']*item['quantity']} ₽"
        if item['size']:
            text += f" (размер {item['size']})"
        text += "\n"
    text += f"💰 *Итого: {order['total_price']} ₽*"
    query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

def callback_user_orders_page(update: Update, context: CallbackContext):
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
        text += f"• #{order['id']} от {order['created_at'][:10]} — {order['total_price']} ₽ ({status_display})\n"
    query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=user_orders_keyboard(page_orders, page, total_pages)
    )

# -------------------- АДМИН ОБРАБОТЧИКИ (ДОБАВЛЕНИЕ ТОВАРА) --------------------
def admin_add_product_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if not is_admin(query.from_user.id):
        query.answer("⛔ Доступ запрещён.", show_alert=True)
        return ConversationHandler.END
    
    all_subs = get_all_subcategories_with_category()
    if not all_subs:
        query.edit_message_text("❌ Нет доступных подкатегорий.")
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
    
    query.edit_message_text(
        "📂 Выберите подкатегорию для нового товара:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SUBCATEGORY_SELECTION

def admin_choose_subcategory(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if not is_admin(query.from_user.id):
        query.answer("⛔ Доступ запрещён.", show_alert=True)
        return ConversationHandler.END
    
    subcategory_id = int(query.data.split('_')[2])
    context.user_data['subcategory_id'] = subcategory_id
    
    query.edit_message_text(
        "📝 Введите название товара (или /cancel для отмены):"
    )
    return ADD_PRODUCT_NAME

def admin_cancel_add(update: Update, context: CallbackContext):
    if update.callback_query:
        query = update.callback_query
        query.answer()
        query.edit_message_text("❌ Добавление товара отменено.")
        query.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())
    else:
        update.message.reply_text("❌ Добавление отменено.")
        update.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())
    
    # Очищаем данные
    context.user_data.clear()
    return ConversationHandler.END

def admin_add_product_name(update: Update, context: CallbackContext):
    if update.message.text == '/cancel':
        return admin_cancel_add(update, context)
    
    context.user_data['name'] = update.message.text
    update.message.reply_text("📄 Введите описание товара (или /cancel для отмены):")
    return ADD_PRODUCT_DESCRIPTION

def admin_add_product_description(update: Update, context: CallbackContext):
    if update.message.text == '/cancel':
        return admin_cancel_add(update, context)
    
    context.user_data['description'] = update.message.text
    update.message.reply_text("💰 Введите цену товара (только число, в рублях):")
    return ADD_PRODUCT_PRICE

def admin_add_product_price(update: Update, context: CallbackContext):
    if update.message.text == '/cancel':
        return admin_cancel_add(update, context)
    
    try:
        price = int(update.message.text)
        if price <= 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("❌ Цена должна быть положительным целым числом. Попробуйте снова:")
        return ADD_PRODUCT_PRICE
    
    context.user_data['price'] = price
    update.message.reply_text(
        "📏 Введите размеры через запятую (например: S,M,L,XL,36,37,38) или отправьте прочерк (-), если размеров нет:\n"
        "(или /cancel для отмены)"
    )
    return ADD_PRODUCT_SIZES

def admin_add_product_sizes(update: Update, context: CallbackContext):
    if update.message.text == '/cancel':
        return admin_cancel_add(update, context)
    
    sizes = update.message.text.strip()
    if sizes == '-':
        sizes = ''
    context.user_data['sizes'] = sizes
    
    update.message.reply_text(
        "🖼 Отправьте фото товара (можно несколько). После каждого фото бот спросит, добавить ли ещё.\n"
        "Отправьте фото сейчас или /skip чтобы пропустить, /cancel для отмены."
    )
    return ADD_PRODUCT_PHOTO

def admin_add_product_photo(update: Update, context: CallbackContext):
    if update.message.text and update.message.text == '/cancel':
        return admin_cancel_add(update, context)
    
    if update.message.photo:
        photos = context.user_data.get('photos', [])
        file_id = update.message.photo[-1].file_id
        photos.append(file_id)
        context.user_data['photos'] = photos
        
        keyboard = [
            [
                InlineKeyboardButton("➕ Добавить ещё фото", callback_data="admin_add_more_photo"),
                InlineKeyboardButton("✅ Закончить", callback_data="admin_finish_photos"),
                InlineKeyboardButton("❌ Отмена", callback_data="admin_cancel_add")
            ]
        ]
        update.message.reply_text(
            "🖼 Фото добавлено. Хотите добавить ещё?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ADD_PRODUCT_PHOTO
    else:
        update.message.reply_text("❌ Пожалуйста, отправьте фото или используйте кнопки.")
        return ADD_PRODUCT_PHOTO

def admin_add_more_photo(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text("🖼 Отправьте следующее фото:")
    return ADD_PRODUCT_PHOTO

def admin_finish_photos(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    product_id = add_product(
        name=context.user_data['name'],
        description=context.user_data['description'],
        price=context.user_data['price'],
        sizes=context.user_data['sizes'],
        subcategory_id=context.user_data.get('subcategory_id')
    )
    
    photos = context.user_data.get('photos', [])
    for idx, file_id in enumerate(photos):
        add_product_image(product_id, file_id, position=idx)
    
    query.edit_message_text(f"✅ Товар успешно добавлен! ID: {product_id}")
    query.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())
    
    context.user_data.clear()
    return ConversationHandler.END

def admin_add_product_skip_photo(update: Update, context: CallbackContext):
    product_id = add_product(
        name=context.user_data['name'],
        description=context.user_data['description'],
        price=context.user_data['price'],
        sizes=context.user_data['sizes'],
        subcategory_id=context.user_data.get('subcategory_id')
    )
    
    update.message.reply_text(f"✅ Товар успешно добавлен без фото! ID: {product_id}")
    update.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())
    
    context.user_data.clear()
    return ConversationHandler.END

# -------------------- АДМИН ОБРАБОТЧИКИ (УДАЛЕНИЕ ТОВАРОВ) --------------------
def admin_delete_product_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if not is_admin(query.from_user.id):
        query.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    
    products = get_all_products(limit=100)
    if not products:
        query.edit_message_text("📭 Нет товаров.")
        return
    
    keyboard = []
    for prod in products:
        keyboard.append([InlineKeyboardButton(f"❌ {prod['name']}", callback_data=f"adm_del_prod_{prod['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_back")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="admin_cancel_delete")])
    
    query.edit_message_text(
        "🗑 Выберите товар для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def admin_cancel_delete(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())

def admin_delete_product_confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    prod_id = int(query.data.split('_')[3])
    product = get_product(prod_id)
    if not product:
        query.edit_message_text("❌ Товар не найден.")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"adm_del_prod_yes_{prod_id}"),
            InlineKeyboardButton("❌ Нет", callback_data="admin_back")
        ]
    ]
    query.edit_message_text(
        f"Вы уверены, что хотите удалить товар «{product['name']}»?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def admin_delete_product_yes(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    prod_id = int(query.data.split('_')[4])
    delete_product_images(prod_id)
    delete_product(prod_id)
    query.edit_message_text("✅ Товар удалён.")
    query.message.reply_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())

# -------------------- АДМИН ОБРАБОТЧИКИ (ЗАКАЗЫ) --------------------
def admin_orders(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if not is_admin(query.from_user.id):
        query.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    
    orders = get_orders()
    if not orders:
        query.edit_message_text("📭 Заказов пока нет.")
        return
    
    page = 1
    per_page = 5
    total_pages = (len(orders) + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    page_orders = orders[start:end]
    
    query.edit_message_text(
        "📦 Список заказов:",
        reply_markup=admin_orders_keyboard(page_orders, page, total_pages)
    )

def admin_orders_page(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    page = int(query.data.split('_')[3])
    orders = get_orders()
    per_page = 5
    total_pages = (len(orders) + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    page_orders = orders[start:end]
    
    query.edit_message_text(
        "📦 Список заказов:",
        reply_markup=admin_orders_keyboard(page_orders, page, total_pages)
    )

def admin_order_detail(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    order_id = int(query.data.split('_')[2])
    order = get_order(order_id)
    if not order:
        query.edit_message_text("❌ Заказ не найден.")
        return
    
    status_display = ORDER_STATUSES.get(order['status'], order['status'])
    text = f"📦 *Заказ #{order['id']}*\n"
    text += f"📅 *Дата:* {order['created_at']}\n"
    text += f"👤 *Пользователь:* {order.get('username', order['user_id'])}\n"
    text += f"📞 *Контакт:* {order['contact']}\n"
    text += f"🏙 *Адрес:* {order['address']}\n"
    if order['comment']:
        text += f"📝 *Комментарий:* {order['comment']}\n"
    text += f"📌 *Статус:* {status_display}\n"
    text += "🛍 *Состав:*\n"
    for item in order['items']:
        text += f"  • {item['name']} x{item['quantity']} = {item['price']*item['quantity']} ₽"
        if item['size']:
            text += f" (размер {item['size']})"
        text += "\n"
    text += f"💰 *Итого: {order['total_price']} ₽*"
    
    query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_order_detail_keyboard(order_id)
    )

def admin_set_order_status(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    parts = query.data.split('_')
    order_id = int(parts[2])
    status = parts[3]
    update_order_status(order_id, status)
    
    # Показываем обновлённый заказ
    order = get_order(order_id)
    if order:
        status_display = ORDER_STATUSES.get(order['status'], order['status'])
        text = f"📦 *Заказ #{order['id']}*\n"
        text += f"📅 *Дата:* {order['created_at']}\n"
        text += f"👤 *Пользователь:* {order.get('username', order['user_id'])}\n"
        text += f"📞 *Контакт:* {order['contact']}\n"
        text += f"🏙 *Адрес:* {order['address']}\n"
        if order['comment']:
            text += f"📝 *Комментарий:* {order['comment']}\n"
        text += f"📌 *Статус:* {status_display}\n"
        text += "🛍 *Состав:*\n"
        for item in order['items']:
            text += f"  • {item['name']} x{item['quantity']} = {item['price']*item['quantity']} ₽"
            if item['size']:
                text += f" (размер {item['size']})"
            text += "\n"
        text += f"💰 *Итого: {order['total_price']} ₽*"
        
        query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_order_detail_keyboard(order_id)
        )

# -------------------- АДМИН ОБРАБОТЧИКИ (СТАТИСТИКА) --------------------
def admin_stats(update: Update, context: CallbackContext):
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
        f"💰 Выручка (завершённые): {stats['revenue']} ₽"
    )
    query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

# -------------------- ОБРАБОТЧИКИ ПОИСКА --------------------
def search_query(update: Update, context: CallbackContext):
    query_text = update.message.text.strip()
    if len(query_text) < 2:
        update.message.reply_text("❌ Слишком короткий запрос. Введите минимум 2 символа.")
        return SEARCH_QUERY
    
    context.user_data['search_query'] = query_text
    show_search_results(update.message, query_text, 1, context)
    return ConversationHandler.END

def show_search_results(message, query: str, page: int, context: CallbackContext):
    offset = (page - 1) * 10
    results = search_products(query, limit=10, offset=offset)
    total = count_search_products(query)
    total_pages = (total + 9) // 10
    
    if not results:
        message.reply_text("😕 Ничего не найдено.")
        return
    
    text = f"🔍 Результаты поиска по запросу «{query}» (стр. {page}/{total_pages}):"
    message.reply_text(text, reply_markup=search_keyboard(results, page, total_pages, query))

def callback_search_page(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    parts = query.data.split('_')
    query_text = parts[2]
    page = int(parts[3])
    show_search_results(query.message, query_text, page, context)

# -------------------- ОБЩИЕ ОБРАБОТЧИКИ --------------------
def callback_back_to_main(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.message.delete()
    admin_flag = is_admin(query.from_user.id)
    query.message.reply_text(
        "🏠 Главное меню:",
        reply_markup=get_main_menu_keyboard(admin_flag)
    )

def callback_admin_back(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if not is_admin(query.from_user.id):
        query.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    query.edit_message_text("🔧 Админ-панель:", reply_markup=admin_menu_keyboard())

def callback_ignore(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

# -------------------- ОСНОВНАЯ ФУНКЦИЯ --------------------
def main():
    # Инициализация базы данных
    init_db()
    logger.info("Database initialized")

    # Создаем Updater и передаем ему токен бота
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Регистрируем обработчики команд
    dp.add_handler(CommandHandler('start', start))

    # Регистрируем ConversationHandler для поиска
    search_conv = ConversationHandler(
        entry_points=[CommandHandler('search', search_command)],
        states={
            SEARCH_QUERY: [MessageHandler(Filters.text & ~Filters.command, search_query)]
        },
        fallbacks=[]
    )
    dp.add_handler(search_conv)

    # Регистрируем ConversationHandler для оформления заказа
    checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout_start, pattern='^checkout$')],
        states={
            CHECKOUT_CONTACT: [MessageHandler(Filters.text & ~Filters.command, checkout_contact)],
            CHECKOUT_ADDRESS: [MessageHandler(Filters.text & ~Filters.command, checkout_address)],
            CHECKOUT_COMMENT: [MessageHandler(Filters.text & ~Filters.command, checkout_comment)],
            CHECKOUT_CONFIRM: [CallbackQueryHandler(checkout_confirm, pattern='^checkout_confirm$'),
                               CallbackQueryHandler(checkout_cancel, pattern='^checkout_cancel$')]
        },
        fallbacks=[],
        per_message=False
    )
    dp.add_handler(checkout_conv)

    # Регистрируем ConversationHandler для добавления товара
    add_product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_product_start, pattern='^admin_add_product$')],
        states={
            SUBCATEGORY_SELECTION: [CallbackQueryHandler(admin_choose_subcategory, pattern='^admin_sub_'),
                                    CallbackQueryHandler(admin_cancel_add, pattern='^admin_cancel_add$')],
            ADD_PRODUCT_NAME: [MessageHandler(Filters.text & ~Filters.command, admin_add_product_name)],
            ADD_PRODUCT_DESCRIPTION: [MessageHandler(Filters.text & ~Filters.command, admin_add_product_description)],
            ADD_PRODUCT_PRICE: [MessageHandler(Filters.text & ~Filters.command, admin_add_product_price)],
            ADD_PRODUCT_SIZES: [MessageHandler(Filters.text & ~Filters.command, admin_add_product_sizes)],
            ADD_PRODUCT_PHOTO: [MessageHandler(Filters.photo, admin_add_product_photo),
                                 MessageHandler(Filters.regex('^/skip$'), admin_add_product_skip_photo),
                                 CallbackQueryHandler(admin_add_more_photo, pattern='^admin_add_more_photo$'),
                                 CallbackQueryHandler(admin_finish_photos, pattern='^admin_finish_photos$'),
                                 CallbackQueryHandler(admin_cancel_add, pattern='^admin_cancel_add$')]
        },
        fallbacks=[],
        per_message=False
    )
    dp.add_handler(add_product_conv)

    # Регистрируем обработчики текстовых кнопок главного меню
    dp.add_handler(MessageHandler(Filters.regex('^🛍 Ассортимент$'), handle_assortment))
    dp.add_handler(MessageHandler(Filters.regex('^🛒 Корзина$'), handle_cart))
    dp.add_handler(MessageHandler(Filters.regex('^📦 Мои заказы$'), handle_my_orders))
    dp.add_handler(MessageHandler(Filters.regex('^ℹ️ О нас$'), handle_about))
    dp.add_handler(MessageHandler(Filters.regex('^📞 Поддержка$'), handle_support))
    dp.add_handler(MessageHandler(Filters.regex('^🔧 Админ панель$'), handle_admin_panel))

    # Регистрируем обработчики callback-запросов
    dp.add_handler(CallbackQueryHandler(callback_show_subcategories, pattern='^cat_'))
    dp.add_handler(CallbackQueryHandler(callback_show_products_by_subcategory, pattern='^subcat_'))
    dp.add_handler(CallbackQueryHandler(callback_subcat_products_page, pattern='^subcat_prod_page_'))
    dp.add_handler(CallbackQueryHandler(callback_back_to_subcategories, pattern='^back_to_subcats_'))
    dp.add_handler(CallbackQueryHandler(callback_back_to_assortment, pattern='^back_to_assortment$'))
    
    dp.add_handler(CallbackQueryHandler(callback_product, pattern='^prod_'))
    dp.add_handler(CallbackQueryHandler(callback_product_photo_nav, pattern='^photo_'))
    dp.add_handler(CallbackQueryHandler(callback_size, pattern='^size_'))
    dp.add_handler(CallbackQueryHandler(callback_add_to_cart, pattern='^add_'))
    dp.add_handler(CallbackQueryHandler(callback_back_to_subcat_products, pattern='^back_to_subcat_products_'))
    dp.add_handler(CallbackQueryHandler(callback_back_to_products_all, pattern='^back_to_products_all$'))
    
    dp.add_handler(CallbackQueryHandler(cart_increase, pattern='^cart_inc_'))
    dp.add_handler(CallbackQueryHandler(cart_decrease, pattern='^cart_dec_'))
    dp.add_handler(CallbackQueryHandler(cart_delete, pattern='^cart_del_'))
    dp.add_handler(CallbackQueryHandler(cart_clear, pattern='^cart_clear$'))
    
    dp.add_handler(CallbackQueryHandler(callback_user_order_detail, pattern='^user_order_'))
    dp.add_handler(CallbackQueryHandler(callback_user_orders_page, pattern='^user_orders_page_'))
    
    dp.add_handler(CallbackQueryHandler(admin_delete_product_start, pattern='^admin_delete_product$'))
    dp.add_handler(CallbackQueryHandler(admin_cancel_delete, pattern='^admin_cancel_delete$'))
    # Используем raw string для корректной обработки \d
    dp.add_handler(CallbackQueryHandler(admin_delete_product_confirm, pattern=r'^adm_del_prod_\d+$'))
    dp.add_handler(CallbackQueryHandler(admin_delete_product_yes, pattern='^adm_del_prod_yes_'))
    
    dp.add_handler(CallbackQueryHandler(admin_orders, pattern='^admin_orders$'))
    dp.add_handler(CallbackQueryHandler(admin_orders_page, pattern='^admin_orders_page_'))
    dp.add_handler(CallbackQueryHandler(admin_order_detail, pattern='^admin_order_'))
    dp.add_handler(CallbackQueryHandler(admin_set_order_status, pattern='^set_status_'))
    
    dp.add_handler(CallbackQueryHandler(admin_stats, pattern='^admin_stats$'))
    dp.add_handler(CallbackQueryHandler(callback_admin_back, pattern='^admin_back$'))
    
    dp.add_handler(CallbackQueryHandler(callback_search_page, pattern='^search_page_'))
    dp.add_handler(CallbackQueryHandler(callback_back_to_main, pattern='^back_to_main$'))
    dp.add_handler(CallbackQueryHandler(callback_ignore, pattern='^ignore$'))

    # Запускаем бота
    logger.info("Starting bot polling")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

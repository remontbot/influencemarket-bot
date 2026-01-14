"""
Централизованное хранилище всех callback_data констант.
Это предотвращает опечатки и облегчает рефакторинг.
"""

# ===== ОСНОВНЫЕ МЕНЮ =====
GO_MAIN_MENU = "go_main_menu"
SHOW_CLIENT_MENU = "show_client_menu"
SHOW_WORKER_MENU = "show_worker_menu"

# ===== РОЛИ =====
SELECT_ROLE_CLIENT = "select_role_client"
SELECT_ROLE_WORKER = "select_role_worker"
ROLE_WORKER = "role_worker"
ROLE_CLIENT = "role_client"

# ===== КЛИЕНТ =====
CLIENT_MY_ORDERS = "client_my_orders"
CLIENT_WAITING_ORDERS = "client_waiting_orders"
CLIENT_IN_PROGRESS_ORDERS = "client_in_progress_orders"
CLIENT_COMPLETED_ORDERS = "client_completed_orders"
CLIENT_CREATE_ORDER = "client_create_order"
CLIENT_VIEW_BIDS = "client_view_bids"
CLIENT_SELECT_BID = "client_select_bid_{bid_id}"  # Template
CLIENT_CONFIRM_SELECT_BID = "client_confirm_select_bid_{bid_id}"  # Template

# ===== МАСТЕР =====
WORKER_MY_ORDERS = "worker_my_orders"
WORKER_IN_PROGRESS_ORDERS = "worker_in_progress_orders"
WORKER_COMPLETED_ORDERS = "worker_completed_orders"
WORKER_VIEW_ORDERS = "worker_view_orders"
WORKER_PROFILE = "worker_profile"
WORKER_EDIT_PROFILE = "worker_edit_profile"
MANAGE_COMPLETED_PHOTOS = "manage_completed_photos"

# ===== ЗАКАЗЫ =====
ORDER_DETAILS = "order_details_{order_id}"  # Template
COMPLETE_ORDER = "complete_order_{order_id}"  # Template
WORKER_COMPLETE_ORDER = "worker_complete_order_{order_id}"  # Template
CANCEL_ORDER = "cancel_order_{order_id}"  # Template

# ===== ОТЗЫВЫ =====
LEAVE_REVIEW = "leave_review_{order_id}"  # Template
REVIEW_RATING = "review_rating_{rating}"  # Template
REVIEW_SKIP_COMMENT = "review_skip_comment"
CANCEL_REVIEW = "cancel_review"

# ===== ЧАТ =====
OPEN_CHAT = "open_chat_{chat_id}"  # Template

# ===== ФОТО =====
PHOTO_PAGE = "photo_page_{direction}_{index}"  # Template
VIEW_WORK_PHOTO = "view_work_photo_{photo_id}"  # Template
DELETE_WORK_PHOTO = "delete_work_photo_{photo_id}"  # Template
CONFIRM_DELETE_PHOTO = "confirm_delete_work_photo_{photo_id}"  # Template

# ===== АДМИН =====
ADMIN_PANEL = "admin_panel"
ADMIN_BACK = "admin_back"
ADMIN_CLOSE = "admin_close"

# Админ: Пользователи
ADMIN_USERS = "admin_users"
ADMIN_USERS_LIST = "admin_users_list_{filter}"  # Template
ADMIN_USERS_PAGE = "admin_users_page_{filter}_{page}"  # Template
ADMIN_USER_VIEW = "admin_user_view_{telegram_id}"  # Template
ADMIN_USER_BAN_START = "admin_user_ban_start_{telegram_id}"  # Template
ADMIN_USER_UNBAN = "admin_user_unban_{telegram_id}"  # Template
ADMIN_USER_SEARCH_START = "admin_user_search_start"

# Админ: Предложения
ADMIN_SUGGESTIONS = "admin_suggestions"
ADMIN_SUGGESTIONS_NEW = "admin_suggestions_new"
ADMIN_SUGGESTIONS_VIEWED = "admin_suggestions_viewed"
ADMIN_SUGGESTIONS_RESOLVED = "admin_suggestions_resolved"

# Админ: Аналитика
ADMIN_ANALYTICS = "admin_analytics"
ADMIN_CATEGORY_REPORTS = "admin_category_reports"
ADMIN_CITY_ACTIVITY = "admin_city_activity"
ADMIN_AVG_PRICES = "admin_avg_prices"
ADMIN_CATEGORY_STATUSES = "admin_category_statuses"

# Админ: Экспорт
ADMIN_EXPORT_MENU = "admin_export_menu"
ADMIN_EXPORT_DATA = "admin_export_{data_type}"  # Template

# Админ: Рассылка
ADMIN_BROADCAST = "admin_broadcast"
BROADCAST_ALL = "broadcast_all"
BROADCAST_WORKERS = "broadcast_workers"
BROADCAST_CLIENTS = "broadcast_clients"

# ===== ЗАГЛУШКИ =====
NOOP = "noop"

# ===== УТИЛИТЫ =====

def order_details(order_id: int) -> str:
    """Создаёт callback_data для деталей заказа"""
    return f"order_details_{order_id}"

def complete_order(order_id: int) -> str:
    """Создаёт callback_data для завершения заказа"""
    return f"complete_order_{order_id}"

def leave_review(order_id: int) -> str:
    """Создаёт callback_data для оставления отзыва"""
    return f"leave_review_{order_id}"

def open_chat(chat_id: int) -> str:
    """Создаёт callback_data для открытия чата"""
    return f"open_chat_{chat_id}"

def admin_user_view(telegram_id: int) -> str:
    """Создаёт callback_data для просмотра пользователя"""
    return f"admin_user_view_{telegram_id}"

def admin_users_page(filter_type: str, page: int) -> str:
    """Создаёт callback_data для пагинации пользователей"""
    return f"admin_users_page_{filter_type}_{page}"

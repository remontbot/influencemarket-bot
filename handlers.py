import logging
import re
import asyncio
import html
from datetime import datetime, timedelta
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    InputMediaPhoto,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import db

logger = logging.getLogger(__name__)


# ===== BELARUS REGIONS AND CITIES =====
#
# ЛОГИКА "ДРУГОЙ ГОРОД":
# - В каждом регионе доступна опция "📍 Другой город в области"
# - Позволяет указать город, не входящий в основной список
# - Используется для:
#   1. Регистрация блогера: блогер работает в указанном городе
#   2. Регистрация клиента: город проживания клиента (для статистики)
#   3. Создание кампании: кампания создаётся в указанном городе
# - Блогеры получают уведомления о кампаниях из своих городов
# - Если город блогера совпадает с городом кампании - блогер видит кампанию
# - Полезно для небольших городов, посёлков и агрогородков
#

BELARUS_REGIONS = {
    "Минск": {
        "type": "city",  # Минск - отдельный город, не часть Минской области
        "display": "🏛 Минск"
    },
    "Брестская область": {
        "type": "region",
        "display": "🌾 Брестская область",
        "cities": ["Брест", "Барановичи", "Пинск", "Кобрин", "Берёза", "Ивацевичи", "Лунинец", "Пружаны", "Столин", "Малорита", "Жабинка"]
    },
    "Витебская область": {
        "type": "region",
        "display": "🌲 Витебская область",
        "cities": ["Витебск", "Орша", "Новополоцк", "Полоцк", "Глубокое", "Лепель", "Поставы", "Сенно", "Толочин", "Чашники"]
    },
    "Гомельская область": {
        "type": "region",
        "display": "🏭 Гомельская область",
        "cities": ["Гомель", "Мозырь", "Жлобин", "Светлогорск", "Речица", "Калинковичи", "Рогачёв", "Добруш", "Житковичи", "Петриков", "Хойники"]
    },
    "Гродненская область": {
        "type": "region",
        "display": "🏰 Гродненская область",
        "cities": ["Гродно", "Лида", "Слоним", "Волковыск", "Новогрудок", "Сморгонь", "Щучин", "Островец", "Берёзовка", "Ивье"]
    },
    "Минская область": {
        "type": "region",
        "display": "🌳 Минская область",
        "cities": ["Борисов", "Солигорск", "Молодечно", "Жодино", "Слуцк", "Дзержинск", "Марьина Горка", "Вилейка", "Столбцы", "Несвиж", "Копыль", "Узда", "Логойск", "Смолевичи"]
    },
    "Могилёвская область": {
        "type": "region",
        "display": "🌾 Могилёвская область",
        "cities": ["Могилёв", "Бобруйск", "Горки", "Осиповичи", "Кричев", "Шклов", "Быхов", "Климовичи", "Чаусы", "Чериков"]
    },
    "Вся Беларусь": {
        "type": "country",
        "display": "🇧🇾 Вся Беларусь"
    }
}


# ===== WORK CATEGORIES HIERARCHY =====

# ===== BLOGGER CATEGORIES =====
# Простые категории контента для блогеров (без подкатегорий)

BLOGGER_CATEGORIES = [
    "✨ Lifestyle / Личный блог",
    "👗 Мода и стиль",
    "💄 Красота и уход",
    "💪 Спорт и фитнес",
    "🍕 Еда и рестораны",
    "✈️ Путешествия",
    "📱 Технологии и гаджеты",
    "📚 Образование",
    "💼 Бизнес и финансы",
    "🎬 Развлечения и медиа",
    "👨‍👩‍👧 Семья и дети",
    "🚗 Авто и мото",
]

# ===== BLOGGER TOPICS (для создания кампаний) =====
# Временно оставлено для создания кампаний рекламодателями
# TODO: упростить создание кампаний позже
BLOGGER_TOPICS = {
    "fashion": {"name": "👗 Мода и стиль", "emoji": "👗", "subcategories": ["Женская мода", "Мужская мода", "Аксессуары"]},
    "beauty": {"name": "💄 Красота и уход", "emoji": "💄", "subcategories": ["Макияж", "Уход за кожей", "Уход за волосами"]},
    "fitness": {"name": "💪 Спорт и фитнес", "emoji": "💪", "subcategories": ["Тренировки", "Питание", "Йога"]},
    "food": {"name": "🍕 Еда и рестораны", "emoji": "🍕", "subcategories": ["Рецепты", "Рестораны", "ПП и ЗОЖ"]},
    "travel": {"name": "✈️ Путешествия", "emoji": "✈️", "subcategories": ["Отдых за границей", "Туризм по Беларуси", "Отели"]},
    "tech": {"name": "📱 Технологии", "emoji": "📱", "subcategories": ["Гаджеты", "Приложения", "Компьютеры"]},
    "education": {"name": "📚 Образование", "emoji": "📚", "subcategories": ["Языки", "Саморазвитие", "Онлайн-курсы"]},
    "business": {"name": "💼 Бизнес", "emoji": "💼", "subcategories": ["Предпринимательство", "Инвестиции", "Маркетинг"]},
    "entertainment": {"name": "🎬 Развлечения", "emoji": "🎬", "subcategories": ["Кино", "Музыка", "Книги"]},
    "family": {"name": "👨‍👩‍👧 Семья и дети", "emoji": "👨‍👩‍👧", "subcategories": ["Материнство", "Воспитание", "Детские товары"]},
    "auto": {"name": "🚗 Авто и мото", "emoji": "🚗", "subcategories": ["Обзоры авто", "Тюнинг", "Мотоциклы"]},
}


# ===== HELPER FUNCTIONS =====

async def safe_edit_message(query, text, context=None, **kwargs):
    """
    КРИТИЧЕСКИ ВАЖНО: Безопасное редактирование сообщения.

    Обрабатывает:
    - Timeout callback_query (>30 сек)
    - Попытка редактировать одинаковый текст
    - Сообщения с фото (вместо текста)
    - Другие BadRequest ошибки

    Если редактирование невозможно, удаляет старое и отправляет новое сообщение.
    """
    import telegram

    try:
        # Проверяем, есть ли в сообщении фото
        if query.message.photo:
            # Сообщение с фото - удаляем и отправляем текстовое
            await query.message.delete()
            await query.message.reply_text(text, **kwargs)
        else:
            # Обычное текстовое сообщение - редактируем
            await query.edit_message_text(text, **kwargs)
    except telegram.error.BadRequest as e:
        error_msg = str(e).lower()

        if "message is not modified" in error_msg:
            # Текст не изменился, ничего не делаем
            logger.debug("Message not modified, skipping")
            return

        if "message to edit not found" in error_msg or "message can't be deleted" in error_msg:
            # Сообщение уже удалено или не существует, отправляем новое
            logger.warning("Message not found, sending new message")
            try:
                if context:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=text,
                        **kwargs
                    )
                else:
                    await query.message.reply_text(text, **kwargs)
            except Exception as send_error:
                logger.error(f"Failed to send new message: {send_error}")
            return

        if "query is too old" in error_msg or "message can't be edited" in error_msg:
            # Callback устарел (>30 сек), отправляем новое сообщение
            logger.warning("Callback query too old, sending new message")
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception as send_error:
                logger.error(f"Failed to send new message: {send_error}")
        else:
            # Другая BadRequest ошибка, логируем и пробрасываем
            logger.error(f"BadRequest in edit_message: {e}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error in safe_edit_message: {e}", exc_info=True)
        raise


def safe_get_user_data(context, keys, default=None):
    """
    КРИТИЧЕСКИ ВАЖНО: Безопасное получение данных из context.user_data.

    Args:
        context: Telegram context
        keys: str или list - ключ или список ключей для проверки
        default: значение по умолчанию если ключа нет

    Returns:
        dict: {key: value} или {key: default} для каждого ключа

    Пример:
        data = safe_get_user_data(context, ["name", "phone", "city"])
        if None in data.values():
            # Не хватает данных
            return error_message
    """
    if isinstance(keys, str):
        keys = [keys]

    result = {}
    for key in keys:
        result[key] = context.user_data.get(key, default)

    return result


def validate_required_fields(context, required_fields):
    """
    КРИТИЧЕСКИ ВАЖНО: Проверяет наличие обязательных полей в context.user_data.

    Args:
        context: Telegram context
        required_fields: list - список обязательных ключей

    Returns:
        tuple: (bool, list) - (все ли есть, список отсутствующих)

    Пример:
        ok, missing = validate_required_fields(context, ["name", "phone"])
        if not ok:
            logger.error(f"Missing fields: {missing}")
            return error
    """
    missing = [f for f in required_fields if f not in context.user_data]
    return (len(missing) == 0, missing)


def validate_file_id(file_id):
    """
    КРИТИЧЕСКИ ВАЖНО: Валидация file_id от Telegram.

    Telegram file_id - это строка длиной 50-200 символов, содержащая:
    - Буквы (A-Z, a-z)
    - Цифры (0-9)
    - Спецсимволы: _ - =

    Args:
        file_id: строка с file_id для проверки

    Returns:
        bool: True если file_id валиден, False иначе

    Примеры:
        ✅ "AgACAgIAAxkBAAIBY2..."  # валидный
        ❌ ""                       # пустой
        ❌ None                     # не строка
        ❌ "abc"                    # слишком короткий
        ❌ "abc<script>"            # недопустимые символы
    """
    if not file_id or not isinstance(file_id, str):
        logger.warning(f"❌ file_id невалиден: пустой или не строка ({type(file_id)})")
        return False

    # Проверка длины (Telegram file_id обычно 50-200 символов)
    if len(file_id) < 20 or len(file_id) > 250:
        logger.warning(f"❌ file_id невалиден: неправильная длина ({len(file_id)} символов)")
        return False

    # Проверка разрешенных символов (только безопасные для Telegram)
    if not re.match(r'^[A-Za-z0-9_\-=]+$', file_id):
        logger.warning(f"❌ file_id невалиден: недопустимые символы")
        return False

    return True


def _get_bids_word(count):
    """Возвращает правильное склонение слова 'предложение'"""
    if count % 10 == 1 and count % 100 != 11:
        return "предложение"
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "предложения"
    else:
        return "предложений"

(
    SELECTING_ROLE,
    REGISTER_BLOGGER_NAME,
    REGISTER_BLOGGER_REGION_SELECT,
    REGISTER_BLOGGER_CITY,
    REGISTER_BLOGGER_CITY_SELECT,
    REGISTER_BLOGGER_CITY_OTHER,
    REGISTER_BLOGGER_CITIES_CONFIRM,
    REGISTER_BLOGGER_CATEGORIES_SELECT,
    REGISTER_BLOGGER_DESCRIPTION,
    REGISTER_BLOGGER_PHOTOS,
    REGISTER_ADVERTISER_NAME,
    REGISTER_ADVERTISER_PHONE,
    REGISTER_ADVERTISER_REGION_SELECT,
    REGISTER_ADVERTISER_CITY,
    REGISTER_ADVERTISER_CITY_SELECT,
    REGISTER_ADVERTISER_CITY_OTHER,
    REGISTER_ADVERTISER_DESCRIPTION,
    # Новые состояния для редактирования профиля
    EDIT_PROFILE_MENU,
    EDIT_NAME,
    EDIT_REGION_SELECT,
    EDIT_CITY,
    EDIT_CATEGORIES_SELECT,
    EDIT_SOCIAL_MEDIA,
    EDIT_SOCIAL_MEDIA_INPUT,
    EDIT_FOLLOWERS,
    EDIT_FOLLOWERS_INPUT,
    EDIT_DESCRIPTION,
    ADD_PHOTOS_MENU,
    ADD_PHOTOS_UPLOAD,
    # Состояния для создания кампания
    CREATE_CAMPAIGN_REGION_SELECT,
    CREATE_CAMPAIGN_CITY,
    CREATE_CAMPAIGN_MAIN_CATEGORY,
    CREATE_CAMPAIGN_SUBCATEGORY_SELECT,
    CREATE_CAMPAIGN_BUDGET,
    CREATE_CAMPAIGN_DESCRIPTION,
    CREATE_CAMPAIGN_PHOTOS,
    # Состояния для создания предложения
    OFFER_SELECT_PAYMENT_TYPE,
    OFFER_ENTER_PRICE,
    OFFER_SELECT_CURRENCY,
    OFFER_SELECT_READY_DAYS,
    OFFER_ENTER_COMMENT,
    # Состояния для оставления отзыва
    REVIEW_SELECT_RATING,
    REVIEW_ENTER_COMMENT,
    # Состояния для админ-панели
    ADMIN_MENU,
    BROADCAST_SELECT_AUDIENCE,
    BROADCAST_ENTER_MESSAGE,
    ADMIN_BAN_REASON,
    ADMIN_SEARCH,
    # Состояния для изменения названия страницы рекламодателя
    EDIT_ADVERTISER_NAME,
    # Состояния для выбора опыта при регистрации и редактировании
    REGISTER_BLOGGER_EXPERIENCE,
    EDIT_EXPERIENCE,
) = range(51)


def is_valid_name(name: str) -> bool:
    if not name:
        return False
    name = name.strip()
    if len(name) < 2 or len(name) > 40:
        return False
    bad_patterns = [r"http", r"www", r"@", r"\.ru", r"\.by", r"\.com", r"t\.me"]
    return not any(re.search(p, name.lower()) for p in bad_patterns)


def is_valid_phone(phone: str) -> bool:
    phone = phone.strip()
    return bool(re.fullmatch(r"\+?\d[\d\s\-()]{6,20}", phone))


def is_profile_complete(user_id: int, role: str) -> bool:
    """
    Проверяет, заполнен ли профиль пользователя.

    Для блогера обязательны:
    - Город (city или regions)
    - Тематика (categories)
    - Описание (description)
    - Хотя бы одна социальная сеть (Instagram, YouTube, TikTok, Telegram, Threads)

    Для рекламодателя обязательны:
    - Город (city)
    - Описание (description)
    """
    if role == "blogger":
        profile = db.get_worker_profile(user_id)
        if not profile:
            return False

        profile_dict = dict(profile)
        city = (profile_dict.get("city") or "").strip()
        regions = (profile_dict.get("regions") or "").strip()
        categories = (profile_dict.get("categories") or "").strip()
        description = (profile_dict.get("description") or "").strip()

        # Проверяем социальные сети (обрабатываем None)
        instagram = (profile_dict.get("instagram_link") or "").strip()
        youtube = (profile_dict.get("youtube_link") or "").strip()
        tiktok = (profile_dict.get("tiktok_link") or "").strip()
        telegram = (profile_dict.get("telegram_link") or "").strip()
        threads = (profile_dict.get("threads_link") or "").strip()

        # Проверяем обязательные поля
        has_location = bool(city or regions)
        has_categories = bool(categories)
        has_description = bool(description)
        has_social_media = bool(instagram or youtube or tiktok or telegram or threads)

        return has_location and has_categories and has_description and has_social_media

    elif role == "advertiser":
        profile = db.get_client_profile(user_id)
        if not profile:
            return False

        profile_dict = dict(profile)
        city = (profile_dict.get("city") or "").strip()
        description = (profile_dict.get("description") or "").strip()

        return bool(city and description)

    return False


# /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_telegram_id = update.effective_user.id
    logger.info(f"[CMD] /start вызван от пользователя {user_telegram_id}")

    # Проверяем не забанен ли пользователь
    if db.is_user_banned(user_telegram_id):
        await update.message.reply_text(
            "🚫 <b>Доступ заблокирован</b>\n\n"
            "Ваш аккаунт заблокирован администратором.\n\n"
            "Если вы считаете, что это ошибка, обратитесь в поддержку.",
            parse_mode="HTML"
        )
        return

    user = db.get_user(user_telegram_id)

    if user:
        user_dict = dict(user)
        role = user_dict["role"]
        user_id = user_dict["id"]
        
        # Проверяем есть ли профиль блогера
        worker_profile = db.get_worker_profile(user_id)
        # Проверяем есть ли профиль клиента
        client_profile = db.get_client_profile(user_id)
        
        has_worker = worker_profile is not None
        has_client = client_profile is not None
        
        keyboard = []
        
        if has_worker:
            keyboard.append([InlineKeyboardButton("🎬 Меню блогера", callback_data="show_worker_menu")])
        
        if has_client:
            keyboard.append([InlineKeyboardButton("💼 Меню рекламодатела", callback_data="show_client_menu")])
        
        # Кнопка для создания второго профиля
        if not has_worker:
            keyboard.append([InlineKeyboardButton("➕ Стать блогером", callback_data="role_blogger")])

        if not has_client:
            keyboard.append([InlineKeyboardButton("➕ Стать рекламодателем", callback_data="role_advertiser")])
        
        message = "👋 Добро пожаловать!\n\n"

        if has_worker and has_client:
            message += "У вас есть оба профиля.\nВыберите какой использовать:"
        elif has_worker:
            message += "Вы зарегистрированы как блогер.\n\nХотите также стать рекламодателем?"
        elif has_client:
            message += "Вы зарегистрированы как рекламодател.\n\nХотите также стать блогером?"

        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        # Новый пользователь - выбор первой роли
        keyboard = [
            [InlineKeyboardButton("📱 Я блогер", callback_data="select_role_blogger")],
            [InlineKeyboardButton("💼 Я рекламодатель", callback_data="select_role_advertiser")],
        ]
        await update.message.reply_text(
            "<b>gde.reklama</b> — маркетплейс для блогеров и рекламодателей в Беларуси.\n\n"
            "<b>Для блогеров</b>\n"
            "Получайте предложения от брендов, выбирайте подходящие кампании и зарабатывайте на своём контенте.\n"
            "Растите в рейтинге, получайте больше заказов и повышайте цены.\n"
            "Поиск рекламодателей мы берём на себя — вы делаете контент.\n\n"
            "<b>Для рекламодателей</b>\n"
            "Находите блогеров по тематике, охвату и городу.\n"
            "Запускайте кампании — блогеры откликаются с предложениями.\n"
            "Выбирайте по цене, статистике и рейтингу.\n\n"
            "Выберите, в роли кого хотите зарегистрироваться.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
    return SELECTING_ROLE


async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = query.data.split("_")[-1]
    context.user_data["selected_role"] = role

    if role == "blogger":
        await query.edit_message_text(
            "Отлично! Вы регистрируетесь как <b>блогер</b>.\n\n"
            "✏️ Введите ваше имя:",
            parse_mode="HTML",
        )
        return REGISTER_BLOGGER_NAME
    else:
        await query.edit_message_text(
            "Отлично! Вы регистрируетесь как <b>рекламодатель</b>.\n\n"
            "✏️ Введите ваше имя:",
            parse_mode="HTML",
        )
        return REGISTER_ADVERTISER_NAME


# ------- РЕГИСТРАЦИЯ БЛОГЕРА -------

async def register_blogger_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not is_valid_name(name):
        await update.message.reply_text(
            "Пожалуйста, укажите только ваше имя или имя и фамилию, без ссылок и рекламы.\n"
            "Пример: «Александра», «Иван Петров», «Мария (lifestyle блогер)»."
        )
        return REGISTER_BLOGGER_NAME
    context.user_data["name"] = name

    # НОВЫЙ УПРОЩЕННЫЙ ФЛОУ: Сразу завершаем регистрацию после ввода имени
    return await finalize_simple_blogger_registration(update, context)


async def register_blogger_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not is_valid_phone(phone):
        await update.message.reply_text(
            "Не могу распознать номер.\n"
            "Пожалуйста, укажите номер в формате: +375 29 123 45 67"
        )
        return REGISTER_BLOGGER_PHONE

    context.user_data["phone"] = phone

    # Показываем регионы Беларуси
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"bloggerregion_{region_name}"
        )])

    await update.message.reply_text(
        "🏙 <b>В каком городе Беларуси вы работаете?</b>\n\n"
        "Выберите регион или город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REGISTER_BLOGGER_REGION_SELECT


async def register_blogger_region_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора региона блогером"""
    query = update.callback_query
    await query.answer()

    region = query.data.replace("bloggerregion_", "")
    region_data = BELARUS_REGIONS.get(region)

    if not region_data:
        await query.edit_message_text("❌ Ошибка выбора региона. Попробуйте снова.")
        return REGISTER_BLOGGER_REGION_SELECT

    context.user_data["region"] = region

    # Если выбран Минск или "Вся Беларусь" - сохраняем и переходим к подтверждению городов
    if region_data["type"] in ["city", "country"]:
        # Инициализируем список городов если его нет
        if "cities" not in context.user_data:
            context.user_data["cities"] = []

        # Добавляем регион в список городов (если его там еще нет)
        if region not in context.user_data["cities"]:
            context.user_data["cities"].append(region)

        # Сохраняем первый город как основной (для обратной совместимости)
        if not context.user_data.get("city"):
            context.user_data["city"] = region
            context.user_data["regions"] = region

        # Инициализируем список категорий если его нет
        if "categories" not in context.user_data:
            context.user_data["categories"] = []

        # Переходим к подтверждению городов
        return await show_cities_confirmation(query, context)

    # Если выбрана область - показываем города
    else:
        cities = region_data.get("cities", [])
        keyboard = []
        row = []
        for city in cities:
            row.append(InlineKeyboardButton(city, callback_data=f"bloggercity_{city}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:  # Добавляем оставшиеся города
            keyboard.append(row)

        # Добавляем кнопку "Другой город в области"
        # ЛОГИКА "ДРУГОЙ ГОРОД":
        # - Блогер может указать любой город, не входящий в основной список
        # - Кампании из этого города также будут видны блогеру
        # - Это полезно для небольших городов и посёлков
        keyboard.append([InlineKeyboardButton(
            f"📍 Другой город в области",
            callback_data="bloggercity_other"
        )])

        # Добавляем кнопку "Назад" для возврата к выбору региона
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="bloggercity_back")])

        await query.edit_message_text(
            f"🏙 Выберите город в регионе <b>{region}</b>:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REGISTER_BLOGGER_CITY_SELECT


async def register_blogger_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города блогером после выбора региона"""
    query = update.callback_query
    await query.answer()

    city = query.data.replace("bloggercity_", "")

    # Обработка кнопки "Назад" - возврат к выбору региона
    if city == "back":
        # Показываем регионы Беларуси
        keyboard = []
        for region_name, region_data in BELARUS_REGIONS.items():
            keyboard.append([InlineKeyboardButton(
                region_data["display"],
                callback_data=f"bloggerregion_{region_name}"
            )])

        await query.edit_message_text(
            "🏙 <b>В каком городе Беларуси вы работаете?</b>\n\n"
            "Выберите регион или город:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REGISTER_BLOGGER_REGION_SELECT

    if city == "other":
        region = context.user_data.get("region", "")
        await query.edit_message_text(
            f"🏙 Напишите название города в регионе <b>{region}</b>:",
            parse_mode="HTML"
        )
        return REGISTER_BLOGGER_CITY_OTHER
    else:
        # Инициализируем список городов если его нет
        if "cities" not in context.user_data:
            context.user_data["cities"] = []

        # Добавляем город в список (если его там еще нет)
        if city not in context.user_data["cities"]:
            context.user_data["cities"].append(city)

        # Сохраняем первый город как основной (для обратной совместимости)
        if not context.user_data.get("city"):
            context.user_data["city"] = city
            region = context.user_data.get("region", city)
            context.user_data["regions"] = region

        # Инициализируем список категорий если его нет
        if "categories" not in context.user_data:
            context.user_data["categories"] = []

        # Переходим к подтверждению городов
        return await show_cities_confirmation(query, context)


async def register_blogger_city_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод другого города блогером вручную"""
    city = update.message.text.strip()

    # Инициализируем список городов если его нет
    if "cities" not in context.user_data:
        context.user_data["cities"] = []

    # Добавляем город в список (если его там еще нет)
    if city not in context.user_data["cities"]:
        context.user_data["cities"].append(city)

    # Сохраняем первый город как основной (для обратной совместимости)
    if not context.user_data.get("city"):
        context.user_data["city"] = city
        region = context.user_data.get("region", city)
        context.user_data["regions"] = region

    # Инициализируем список категорий если его нет
    if "categories" not in context.user_data:
        context.user_data["categories"] = []

    # Отправляем сообщение с подтверждением через фейковый query
    class FakeQuery:
        def __init__(self, message):
            self.message = message
            self.from_user = message.from_user

        async def edit_message_text(self, text, **kwargs):
            await self.message.reply_text(text, **kwargs)

    fake_query = FakeQuery(update.message)
    return await show_cities_confirmation(fake_query, context)


async def show_cities_confirmation(query, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбранные города и предлагает добавить еще или завершить"""
    cities = context.user_data.get("cities", [])

    cities_text = "\n".join([f"  📍 {city}" for city in cities])

    text = (
        f"🏙 <b>Выбранные города ({len(cities)}):</b>\n"
        f"{cities_text}\n\n"
        "Вы можете добавить еще города или завершить выбор:"
    )

    keyboard = [
        [InlineKeyboardButton("➕ Добавить еще город", callback_data="add_more_cities")],
        [InlineKeyboardButton("✅ Завершить выбор городов", callback_data="finish_cities")],
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return REGISTER_BLOGGER_CITIES_CONFIRM


async def register_blogger_cities_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора: добавить еще город или завершить"""
    query = update.callback_query
    await query.answer()

    if query.data == "add_more_cities":
        # Показываем регионы снова
        keyboard = []
        for region_name, region_data in BELARUS_REGIONS.items():
            keyboard.append([InlineKeyboardButton(
                region_data["display"],
                callback_data=f"bloggerregion_{region_name}"
            )])

        cities = context.user_data.get("cities", [])
        cities_text = ", ".join(cities)

        await query.edit_message_text(
            f"🏙 <b>Уже выбрано:</b> {cities_text}\n\n"
            "Выберите регион для добавления города:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REGISTER_BLOGGER_REGION_SELECT

    elif query.data == "finish_cities":
        # Завершаем выбор городов, переходим к категориям
        cities = context.user_data.get("cities", [])
        cities_text = ", ".join(cities)

        # Инициализируем пустой список категорий
        if "categories" not in context.user_data:
            context.user_data["categories"] = []

        # Показываем все категории с галочками (2 в ряд)
        keyboard = []
        row = []
        for idx, category in enumerate(BLOGGER_CATEGORIES):
            is_selected = category in context.user_data.get("categories", [])
            button_text = f"☑️ {category}" if is_selected else category

            row.append(InlineKeyboardButton(button_text, callback_data=f"cat_{idx}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("✅ Завершить выбор", callback_data="cat_done")])

        await query.edit_message_text(
            f"🏙 Города: {cities_text}\n\n"
            "📱 <b>Шаг 4/7:</b> Выберите категории контента:\n\n"
            "Нажимайте подходящие кнопки (можно несколько).\n"
            "Когда закончите — нажмите «✅ Завершить выбор».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REGISTER_BLOGGER_CATEGORIES_SELECT


async def register_blogger_categories_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора категорий с переключением галочек"""
    query = update.callback_query
    data = query.data
    selected = data.replace("cat_", "")

    if selected == "done":
        # Проверяем что выбрана хотя бы одна категория
        if not context.user_data.get("categories"):
            await query.answer("Выберите хотя бы одну категорию!", show_alert=True)
            return REGISTER_BLOGGER_CATEGORIES_SELECT

        await query.answer()

        # Переходим к выбору уровня опыта
        keyboard = [
            [InlineKeyboardButton("🌱 Начинающий блогер", callback_data="exp_Начинающий блогер")],
            [InlineKeyboardButton("⚡ Опытный блогер", callback_data="exp_Опытный блогер")],
            [InlineKeyboardButton("⭐ Профессионал", callback_data="exp_Профессионал")],
        ]

        categories_text = ", ".join(context.user_data["categories"])

        await query.edit_message_text(
            f"✅ <b>Выбранные категории:</b>\n{categories_text}\n\n"
            "<b>Шаг 5/7:</b> Выберите ваш уровень опыта:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REGISTER_BLOGGER_EXPERIENCE

    else:
        # Переключаем выбор категории
        idx = int(selected)
        category = BLOGGER_CATEGORIES[idx]

        if "categories" not in context.user_data:
            context.user_data["categories"] = []

        if category not in context.user_data["categories"]:
            context.user_data["categories"].append(category)
            await query.answer(f"✅ Добавлено")
        else:
            context.user_data["categories"].remove(category)
            await query.answer(f"❌ Убрано")

        # Обновляем кнопки с галочками
        cities = context.user_data.get("cities", [])
        cities_text = ", ".join(cities)

        keyboard = []
        row = []
        for idx2, cat in enumerate(BLOGGER_CATEGORIES):
            is_selected = cat in context.user_data["categories"]
            button_text = f"☑️ {cat}" if is_selected else cat

            row.append(InlineKeyboardButton(button_text, callback_data=f"cat_{idx2}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("✅ Завершить выбор", callback_data="cat_done")])

        await query.edit_message_text(
            f"🏙 Города: {cities_text}\n\n"
            "📱 <b>Шаг 4/7:</b> Выберите категории контента:\n\n"
            "Нажимайте подходящие кнопки (можно несколько).\n"
            "Когда закончите — нажмите «✅ Завершить выбор».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return REGISTER_BLOGGER_CATEGORIES_SELECT


async def register_blogger_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    experience = query.data.replace("exp_", "")
    context.user_data["experience"] = experience
    
    await query.edit_message_text(
        f"Уровень: {experience}\n\n"
        "📝 <b>Расскажите о своём опыте и выполненных проектах</b>\n\n"
        "💡 Это описание увидят потенциальные рекламодатели. Укажите:\n\n"
        "✓ <b>Опыт создания контента:</b> Сколько лет в профессии, какие проекты выполняли\n"
        "✓ <b>Примеры проектов:</b> Что делали, какой сложности контент\n"
        "✓ <b>Специализация:</b> В чём вы особенно сильны\n"
        "✓ <b>Как работаете:</b> Опыт, стиль контента, аудитория, охваты\n\n"
        "<b>Пример:</b>\n"
        "«Веду блог про семейные путешествия 3 года. Аудитория 25-40 лет, 70% женщин. "
        "Средний охват Stories 15 000, постов 8 000. Специализируюсь на отзывах об отелях "
        "и семейных развлечениях. Работаю профессионально, соблюдаю сроки. Готова предоставить "
        "статистику охватов и примеры прошлых рекламных интеграций.»",
        parse_mode="HTML"
    )
    return REGISTER_BLOGGER_DESCRIPTION


async def register_blogger_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text.strip()
    
    # НОВОЕ: Предлагаем добавить фото контент
    keyboard = [
        [InlineKeyboardButton("📸 Да, добавить фото контент", callback_data="add_photos_yes")],
        [InlineKeyboardButton("⏭ Пропустить (добавлю позже)", callback_data="add_photos_no")],
    ]
    
    await update.message.reply_text(
        "📸 <b>Ваше портфолио (до 10 фотографий)</b>\n\n"
        "Добавьте фотографии, чтобы рекламодатели увидели качество вашего контента.\n\n"
        "⚠️ <b>ОЧЕНЬ ВАЖНО про первое фото:</b>\n"
        "🤵 Первая фотография <b>станет вашим фото профиля и должна быть с вашим лицом!</b>\n"
        "Это повышает доверие рекламодателей и показывает, что вы реальный блогер.\n\n"
        "📋 Дальше добавьте <b>до 9 фотографий вашего контента:</b>\n"
        "• Скриншоты успешных публикаций\n"
        "• Примеры интеграций\n"
        "• Фото с мероприятий/съёмок\n\n"
        "💡 <i>Блогеры с фото получают в 5 раз больше откликов!</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return REGISTER_BLOGGER_PHOTOS


async def register_blogger_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора: добавлять фото или нет"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_photos_yes":
        context.user_data["portfolio_photos"] = []
        await query.edit_message_text(
            "📸 <b>Загрузка портфолио (до 10 фото)</b>\n\n"
            "🤵 <b>Фото #1 - ФОТО ПРОФИЛЯ (с вашим лицом!)</b>\n\n"
            "Это фото станет вашим фото профиля и должно быть с вашим лицом.\n"
            "Хорошие варианты:\n"
            "• Фото с мероприятия или съёмки\n"
            "• Профессиональное фото для соцсетей\n"
            "• Фото в процессе создания контента\n\n"
            "💡 Фото с лицом повышает доверие рекламодателей и увеличивает отклики в 5 раз!",
            parse_mode="HTML",
        )
        return REGISTER_BLOGGER_PHOTOS
    else:
        # Пропускаем фото, завершаем регистрацию
        return await finalize_blogger_registration(update, context)


async def handle_blogger_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загруженных фотографий"""
    logger.info(f"📱 DEBUG: handle_master_photos вызван. Текст: {update.message.text if update.message.text else 'фото'}")

    # КРИТИЧНО: Проверяем, не зарегистрирован ли уже пользователь
    telegram_id = update.effective_user.id
    existing_user = db.get_user(telegram_id)

    if existing_user:
        logger.warning(f"📱 DEBUG: Пользователь {telegram_id} УЖЕ ЗАРЕГИСТРИРОВАН! Завершаем ConversationHandler")
        context.user_data.clear()

        await update.message.reply_text(
            "✅ Вы уже зарегистрированы!\n\n"
            "Чтобы добавить фото в портфолио, используйте меню:\n"
            "Профиль → Добавить фото контент\n\n"
            "Или нажмите /start для возврата в главное меню.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💼 Главное меню", callback_data="show_worker_menu")
            ]])
        )

        return ConversationHandler.END

    # КРИТИЧНО: Проверка на видео/документы (не фото)
    if update.message.video:
        logger.warning("Пользователь отправил видео вместо фото")
        await update.message.reply_text(
            "⚠️ <b>Можно отправлять только фотографии!</b>\n\n"
            "Видео не поддерживаются.\n"
            "Пожалуйста, отправьте фото или:\n"
            "• Напишите /done_photos для завершения\n"
            "• Напишите: готово",
            parse_mode="HTML"
        )
        return REGISTER_BLOGGER_PHOTOS

    # КРИТИЧНО: Проверка на документы (файлы)
    if update.message.document:
        # Если это изображение-документ (файл), разрешаем
        if update.message.document.mime_type and update.message.document.mime_type.startswith('image/'):
            logger.info("Получено изображение как документ - обрабатываем как фото")
            # Обрабатываем как фото дальше по коду
        else:
            logger.warning(f"Пользователь отправил документ (не изображение): {update.message.document.mime_type}")
            await update.message.reply_text(
                "⚠️ <b>Можно отправлять только изображения!</b>\n\n"
                "Документы, видео и другие файлы не поддерживаются.\n"
                "Пожалуйста, отправьте фото или:\n"
                "• Напишите /done_photos для завершения\n"
                "• Напишите: готово",
                parse_mode="HTML"
            )
            return REGISTER_BLOGGER_PHOTOS

    # Проверяем текст сообщения
    if update.message.text:
        text = update.message.text.strip().lower()
        logger.info(f"Получен текст: '{text}'")

        # Проверяем различные варианты команды
        if text in ['/done_photos', 'done_photos', '/donephotos', 'donephotos', 'готово']:
            logger.info("Команда завершения фото распознана, вызываем finalize")
            return await finalize_blogger_registration(update, context)

    # Обработка фото
    if update.message.photo or (update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('image/')):
        logger.info("Получено фото")
        if "portfolio_photos" not in context.user_data:
            context.user_data["portfolio_photos"] = []

        # Получаем file_id (может быть photo или document)
        if update.message.photo:
            photo = update.message.photo[-1]  # Берём самое большое разрешение
            file_id = photo.file_id
        else:
            # Это document с image/ mime_type
            file_id = update.message.document.file_id

        # КРИТИЧНО: Валидация file_id
        if not validate_file_id(file_id):
            logger.error(f"❌ Невалидный file_id при загрузке фото портфолио: {file_id}")
            await update.message.reply_text(
                "❌ Ошибка при обработке фото.\n\n"
                "Попробуйте отправить фото еще раз или используйте другое изображение.\n\n"
                "Отправьте /done_photos для завершения регистрации без этого фото."
            )
            return REGISTER_BLOGGER_PHOTOS

        if len(context.user_data["portfolio_photos"]) < 10:
            context.user_data["portfolio_photos"].append(file_id)
            count = len(context.user_data["portfolio_photos"])
            logger.info(f"Фото добавлено. Всего: {count}")

            # Разные сообщения в зависимости от номера фото
            if count == 1:
                await update.message.reply_text(
                    "✅ <b>Фото #1 добавлено!</b>\n\n"
                    "💡 <b>РЕКОМЕНДАЦИЯ:</b> Первое фото желательно с вашим лицом!\n"
                    "Это повышает доверие клиентов и увеличивает количество откликов.\n\n"
                    "📸 <b>Теперь добавьте фото ваших контент</b> (до 9 штук):\n\n"
                    "Отправьте фотографии завершённых проектов, которыми вы гордитесь.\n\n"
                    "Когда загрузите все фото, напишите:\n"
                    "/done_photos или просто: готово",
                    parse_mode="HTML"
                )
            elif count < 10:
                await update.message.reply_text(
                    f"✅ Фото #{count} добавлено!\n\n"
                    f"📊 Загружено: {count}/10\n"
                    f"Можно ещё: {10 - count}\n\n"
                    f"Отправьте ещё фото или напишите:\n"
                    f"/done_photos (или: готово)",
                    parse_mode="HTML"
                )
            else:  # count == 10
                await update.message.reply_text(
                    "✅ Отлично! Все 10 фотографий загружены!\n\n"
                    "📝 Напишите /done_photos или просто: готово\n"
                    "чтобы завершить регистрацию."
                )
        else:
            await update.message.reply_text(
                "⚠️ Максимум 10 фотографий.\n\n"
                "Отправьте /done_photos для завершения."
            )

        return REGISTER_BLOGGER_PHOTOS
    
    # Если пришло что-то другое
    logger.warning(f"Неожиданный ввод: {update.message.text}")
    await update.message.reply_text(
        "⚠️ Пожалуйста, отправьте:\n"
        "• Фотографии ваших контент, или\n"
        "• Команду /done_photos для завершения\n"
        "• Или напишите: готово"
    )
    return REGISTER_BLOGGER_PHOTOS


async def finalize_blogger_registration(update, context):
    """
    Финальное создание профиля блогера.
    ИСПРАВЛЕНО: Валидация обязательных полей перед созданием.
    """
    telegram_id = update.effective_user.id if update.message else update.callback_query.from_user.id

    # КРИТИЧНО: Проверяем наличие всех обязательных полей
    # ОБНОВЛЕНО: Убраны phone и experience для блогерского маркетплейса
    required_fields = ["name", "city", "regions", "categories", "description"]
    ok, missing = validate_required_fields(context, required_fields)

    if not ok:
        logger.error(f"Missing required fields in master registration: {missing}")
        keyboard = [[InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")]]
        error_msg = (
            "❌ Ошибка: недостаточно данных для создания профиля.\n\n"
            "Пожалуйста, начните регистрацию заново: /start"
        )

        if update.message:
            await update.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))

        context.user_data.clear()
        return ConversationHandler.END

    # КРИТИЧНО: Обработка ошибок БД при создании пользователя и профиля
    user_created = False  # Флаг для отслеживания создания нового пользователя
    user_id = None

    try:
        # Проверяем существование пользователя перед созданием
        existing_user = db.get_user(telegram_id)
        if existing_user:
            user_id = existing_user['id']
            logger.info(f"Пользователь {telegram_id} уже существует, используем существующий ID: {user_id}")
        else:
            user_id = db.create_user(telegram_id, "blogger")
            user_created = True  # КРИТИЧНО: Отмечаем что создали нового пользователя
            logger.info(f"Создан новый пользователь {telegram_id} с ID: {user_id}")

        # Сохраняем фото контент (если есть)
        portfolio_photos = context.user_data.get("portfolio_photos", [])

        # КРИТИЧНО: Дополнительная валидация всех file_id перед сохранением в БД
        valid_photos = [fid for fid in portfolio_photos if validate_file_id(fid)]
        if len(valid_photos) < len(portfolio_photos):
            removed_count = len(portfolio_photos) - len(valid_photos)
            logger.warning(f"⚠️ Удалено {removed_count} невалидных file_id перед сохранением профиля")

        photos_json = ",".join(valid_photos) if valid_photos else ""

        # Автоматически устанавливаем первое фото как фото профиля (если есть)
        profile_photo = valid_photos[0] if valid_photos else ""

        db.create_worker_profile(
            user_id=user_id,
            name=context.user_data["name"],
            phone=context.user_data.get("phone", ""),  # ОБНОВЛЕНО: опционально для блогеров
            city=context.user_data["city"],
            regions=context.user_data["regions"],  # Теперь это просто город
            categories=", ".join(context.user_data["categories"]),
            experience=context.user_data.get("experience", ""),  # ОБНОВЛЕНО: опционально для блогеров
            description=context.user_data["description"],
            portfolio_photos=photos_json,
            profile_photo=profile_photo,  # Устанавливаем первое фото как фото профиля
            cities=context.user_data.get("cities"),  # Список всех городов блогера
        )

    except ValueError as e:
        # Ошибки валидации (например, дубликат профиля из race condition protection)
        logger.error(f"❌ Ошибка валидации при создании профиля блогера: {e}")

        # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
        if user_created and user_id:
            try:
                db.delete_user_profile(telegram_id)
                logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

        keyboard = [[InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")]]
        error_msg = (
            "❌ Не удалось создать профиль.\n\n"
            f"Причина: {str(e)}\n\n"
            "Попробуйте еще раз или обратитесь в поддержку."
        )
        if update.message:
            await update.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data.clear()
        return ConversationHandler.END

    except Exception as e:
        # Любые другие ошибки БД (connection, SQL syntax, etc)
        logger.error(f"❌ Ошибка БД при создании профиля блогера: {e}", exc_info=True)

        # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
        if user_created and user_id:
            try:
                db.delete_user_profile(telegram_id)
                logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

        keyboard = [[InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")]]
        error_msg = (
            "❌ Произошла ошибка при сохранении профиля в базу данных.\n\n"
            "Пожалуйста, попробуйте еще раз через минуту.\n\n"
            "Если проблема повторяется, обратитесь в поддержку."
        )
        if update.message:
            await update.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data.clear()
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("Моё меню блогера", callback_data="show_worker_menu")]]

    # Используем валидные фото для точной статистики
    photos_count = len(valid_photos)
    photos_text = f"\n📸 Добавлено фотографий: {photos_count}" if photos_count > 0 else ""

    message_text = (
        f"🥳 <b>Профиль блогера создан!</b>{photos_text}\n\n"
        "Теперь вы можете:\n"
        "• Посмотреть свой профиль\n"
        "• Получать кампании от клиентов\n"
        "• Добавить больше фото контент в любое время"
    )

    if update.message:
        await update.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
    else:
        await update.callback_query.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    context.user_data.clear()
    return ConversationHandler.END


async def finalize_simple_blogger_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Упрощенная регистрация блогера: только имя.
    Остальные поля (город, категории, описание) заполняются в настройках профиля.
    """
    telegram_id = update.effective_user.id
    name = context.user_data.get("name", "").strip()

    if not name:
        await update.message.reply_text(
            "❌ Ошибка: имя не указано.\n\n"
            "Пожалуйста, начните регистрацию заново: /start"
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        # Создаём или получаем пользователя
        existing_user = db.get_user(telegram_id)
        if existing_user:
            user_id = existing_user['id']
            current_role = existing_user.get('role', 'blogger')
            logger.info(f"Пользователь {telegram_id} уже существует с ролью {current_role}")

            # Если пользователь был рекламодателем - обновляем роль на 'both'
            if current_role == 'advertiser':
                db.update_user_role(user_id, 'both')
                logger.info(f"Роль пользователя {telegram_id} обновлена на 'both'")
            elif current_role == 'blogger':
                # Уже блогер - ничего не делаем
                pass
            # Если 'both' - тоже ничего не делаем
        else:
            user_id = db.create_user(telegram_id, "blogger")
            logger.info(f"Создан новый пользователь {telegram_id} с ID: {user_id}")

        # Создаём минимальный профиль блогера (только с именем)
        db.create_worker_profile(
            user_id=user_id,
            name=name,
            phone="",  # Пустые значения - заполнятся в настройках
            city="",
            regions="",
            categories="",
            experience="",
            description="",
            portfolio_photos="",
            profile_photo="",
            cities=None
        )

        logger.info(f"Создан упрощенный профиль блогера для user_id={user_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка при создании упрощенного профиля: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при создании профиля.\n\n"
            "Пожалуйста, попробуйте еще раз: /start"
        )
        context.user_data.clear()
        return ConversationHandler.END

    # Успешная регистрация - отправляем в меню
    keyboard = [[InlineKeyboardButton("🎬 Моё меню блогера", callback_data="show_worker_menu")]]

    await update.message.reply_text(
        f"✅ Добро пожаловать, {name}!\n\n"
        "Ваш профиль создан.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

    context.user_data.clear()
    return ConversationHandler.END


async def finalize_simple_advertiser_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Упрощенная регистрация рекламодателя: только имя.
    Остальные поля заполняются в настройках профиля.
    """
    telegram_id = update.effective_user.id
    name = context.user_data.get("name", "").strip()

    if not name:
        await update.message.reply_text(
            "❌ Ошибка: имя не указано.\n\n"
            "Пожалуйста, начните регистрацию заново: /start"
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        # Создаём или получаем пользователя
        existing_user = db.get_user(telegram_id)
        if existing_user:
            user_id = existing_user['id']
            current_role = existing_user.get('role', 'advertiser')
            logger.info(f"Пользователь {telegram_id} уже существует с ролью {current_role}")

            # Если пользователь был блогером - обновляем роль на 'both'
            if current_role == 'blogger':
                db.update_user_role(user_id, 'both')
                logger.info(f"Роль пользователя {telegram_id} обновлена на 'both'")
            elif current_role == 'advertiser':
                # Уже рекламодатель - ничего не делаем
                pass
            # Если 'both' - тоже ничего не делаем
        else:
            user_id = db.create_user(telegram_id, "advertiser")
            logger.info(f"Создан новый пользователь {telegram_id} с ID: {user_id}")

        # Создаём минимальный профиль рекламодателя (только с именем)
        db.create_client_profile(
            user_id=user_id,
            name=name,
            phone="",  # Пустые значения - заполнятся в настройках
            city="",
            description=""
        )

        logger.info(f"Создан упрощенный профиль рекламодателя для user_id={user_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка при создании упрощенного профиля: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при создании профиля.\n\n"
            "Пожалуйста, попробуйте еще раз: /start"
        )
        context.user_data.clear()
        return ConversationHandler.END

    # Успешная регистрация - отправляем в меню
    keyboard = [[InlineKeyboardButton("💼 Моё меню рекламодателя", callback_data="show_client_menu")]]

    await update.message.reply_text(
        f"✅ Добро пожаловать, {name}!\n\n"
        "Ваш профиль создан.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

    context.user_data.clear()
    return ConversationHandler.END


# ------- РЕГИСТРАЦИЯ РЕКЛАМОДАТЕЛЯ -------

async def register_advertiser_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not is_valid_name(name):
        await update.message.reply_text(
            "Пожалуйста, укажите только ваше имя или имя и фамилию, без ссылок и рекламы.\n"
            "Пример: «Александр», «Иван Петров», «Компания XYZ»."
        )
        return REGISTER_ADVERTISER_NAME
    context.user_data["name"] = name

    # НОВЫЙ УПРОЩЕННЫЙ ФЛОУ: Сразу завершаем регистрацию после ввода имени
    return await finalize_simple_advertiser_registration(update, context)


async def register_advertiser_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not is_valid_phone(phone):
        await update.message.reply_text(
            "Не могу распознать номер.\n"
            "Пожалуйста, укажите номер в формате: +375 29 123 45 67"
        )
        return REGISTER_ADVERTISER_PHONE

    context.user_data["phone"] = phone

    # Показываем регионы Беларуси
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"clientregion_{region_name}"
        )])

    await update.message.reply_text(
        "🏙 <b>Где вы находитесь?</b>\n\n"
        "Выберите регион или город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REGISTER_ADVERTISER_REGION_SELECT


async def register_advertiser_region_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора региона клиентом"""
    query = update.callback_query
    await query.answer()

    region = query.data.replace("clientregion_", "")
    region_data = BELARUS_REGIONS.get(region)

    if not region_data:
        await query.edit_message_text("❌ Ошибка выбора региона. Попробуйте снова.")
        return REGISTER_ADVERTISER_REGION_SELECT

    context.user_data["region"] = region

    # Если выбран Минск или "Вся Беларусь" - создаём профиль сразу
    if region_data["type"] in ["city", "country"]:
        context.user_data["city"] = region
        context.user_data["regions"] = region

        # Создаём профиль клиента
        telegram_id = query.from_user.id

        logger.info(f"=== Создание профиля клиента ===")
        logger.info(f"Telegram ID: {telegram_id}")
        logger.info(f"Имя: {context.user_data.get('name')}")
        logger.info(f"Телефон: {context.user_data.get('phone')}")
        logger.info(f"Регион: {region}")

        # КРИТИЧНО: Обработка ошибок БД при создании пользователя и профиля
        user_created = False  # Флаг для отслеживания создания нового пользователя
        user_id = None

        try:
            # Проверяем есть ли уже user (если добавляет вторую роль)
            existing_user = db.get_user(telegram_id)
            if existing_user:
                user_id = existing_user["id"]
                logger.info(f"Существующий user_id: {user_id}")
            else:
                user_id = db.create_user(telegram_id, "advertiser")
                user_created = True  # КРИТИЧНО: Отмечаем что создали нового пользователя
                logger.info(f"Создан новый user_id: {user_id}")

            db.create_client_profile(
                user_id=user_id,
                name=context.user_data["name"],
                phone=context.user_data["phone"],
                city=context.user_data["city"],
                description="",
                regions=context.user_data["regions"],
            )
            logger.info("✅ Профиль клиента успешно создан в БД!")

        except ValueError as e:
            # Ошибки валидации (например, дубликат профиля)
            logger.error(f"❌ Ошибка валидации при создании профиля клиента: {e}")

            # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
            if user_created and user_id:
                try:
                    db.delete_user_profile(telegram_id)
                    logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
                except Exception as rollback_error:
                    logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

            await query.edit_message_text(
                f"❌ Не удалось создать профиль.\n\n"
                f"Причина: {str(e)}\n\n"
                f"Попробуйте еще раз или обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")
                ]])
            )
            context.user_data.clear()
            return ConversationHandler.END

        except Exception as e:
            # Любые другие ошибки БД
            logger.error(f"❌ Ошибка БД при создании профиля клиента: {e}", exc_info=True)

            # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
            if user_created and user_id:
                try:
                    db.delete_user_profile(telegram_id)
                    logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
                except Exception as rollback_error:
                    logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

            await query.edit_message_text(
                "❌ Произошла ошибка при сохранении профиля в базу данных.\n\n"
                "Пожалуйста, попробуйте еще раз через минуту.\n\n"
                "Если проблема повторяется, обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")
                ]])
            )
            context.user_data.clear()
            return ConversationHandler.END

        keyboard = [[InlineKeyboardButton("💼 Моё меню рекламодатела", callback_data="show_client_menu")]]
        await query.edit_message_text(
            "🥳 <b>Профиль рекламодатела создан!</b>\n\n"
            "Теперь вы можете:\n"
            "• 📝 Создавать кампании\n"
            "• 🔍 Искать блогеров\n"
            "• 💬 Общаться с блогерами\n\n"
            "Детали о задаче вы опишете при создании кампания!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        context.user_data.clear()
        logger.info("✅ Context очищен")
        return ConversationHandler.END

    # Если выбрана область - показываем города
    else:
        cities = region_data.get("cities", [])
        keyboard = []
        row = []
        for city in cities:
            row.append(InlineKeyboardButton(city, callback_data=f"clientcity_{city}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:  # Добавляем оставшиеся города
            keyboard.append(row)

        # Добавляем кнопку "Другой город в области"
        # ЛОГИКА "ДРУГОЙ ГОРОД":
        # - Клиент может указать город регистрации, не входящий в основной список
        # - Город клиента используется для статистики
        keyboard.append([InlineKeyboardButton(
            f"📍 Другой город в области",
            callback_data="clientcity_other"
        )])

        # Добавляем кнопку "Назад" для возврата к выбору региона
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="clientcity_back")])

        await query.edit_message_text(
            f"🏙 Выберите город в регионе <b>{region}</b>:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REGISTER_ADVERTISER_CITY_SELECT


async def register_advertiser_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города клиентом после выбора региона"""
    query = update.callback_query
    await query.answer()

    city = query.data.replace("clientcity_", "")

    # Обработка кнопки "Назад" - возврат к выбору региона
    if city == "back":
        # Показываем регионы Беларуси
        keyboard = []
        for region_name, region_data in BELARUS_REGIONS.items():
            keyboard.append([InlineKeyboardButton(
                region_data["display"],
                callback_data=f"clientregion_{region_name}"
            )])

        await query.edit_message_text(
            "🏙 <b>Где вы находитесь?</b>\n\n"
            "Выберите регион или город:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REGISTER_ADVERTISER_REGION_SELECT

    if city == "other":
        region = context.user_data.get("region", "")
        await query.edit_message_text(
            f"🏙 Напишите название города в регионе <b>{region}</b>:",
            parse_mode="HTML"
        )
        return REGISTER_ADVERTISER_CITY_OTHER
    else:
        context.user_data["city"] = city
        region = context.user_data.get("region", city)
        context.user_data["regions"] = region

        # Создаём профиль
        telegram_id = query.from_user.id

        logger.info(f"=== Создание профиля клиента ===")
        logger.info(f"Telegram ID: {telegram_id}")
        logger.info(f"Имя: {context.user_data.get('name')}")
        logger.info(f"Телефон: {context.user_data.get('phone')}")
        logger.info(f"Город: {city}")
        logger.info(f"Регион: {region}")

        # КРИТИЧНО: Обработка ошибок БД при создании пользователя и профиля
        user_created = False  # Флаг для отслеживания создания нового пользователя
        user_id = None

        try:
            # Проверяем есть ли уже user (если добавляет вторую роль)
            existing_user = db.get_user(telegram_id)
            if existing_user:
                user_id = existing_user["id"]
                logger.info(f"Существующий user_id: {user_id}")
            else:
                user_id = db.create_user(telegram_id, "advertiser")
                user_created = True  # КРИТИЧНО: Отмечаем что создали нового пользователя
                logger.info(f"Создан новый user_id: {user_id}")

            db.create_client_profile(
                user_id=user_id,
                name=context.user_data["name"],
                phone=context.user_data["phone"],
                city=context.user_data["city"],
                description="",
                regions=context.user_data["regions"],
            )
            logger.info("✅ Профиль клиента успешно создан в БД!")

        except ValueError as e:
            # Ошибки валидации (например, дубликат профиля)
            logger.error(f"❌ Ошибка валидации при создании профиля клиента: {e}")

            # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
            if user_created and user_id:
                try:
                    db.delete_user_profile(telegram_id)
                    logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
                except Exception as rollback_error:
                    logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

            await query.edit_message_text(
                f"❌ Не удалось создать профиль.\n\n"
                f"Причина: {str(e)}\n\n"
                f"Попробуйте еще раз или обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")
                ]])
            )
            context.user_data.clear()
            return ConversationHandler.END

        except Exception as e:
            # Любые другие ошибки БД
            logger.error(f"❌ Ошибка БД при создании профиля клиента: {e}", exc_info=True)

            # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
            if user_created and user_id:
                try:
                    db.delete_user_profile(telegram_id)
                    logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
                except Exception as rollback_error:
                    logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

            await query.edit_message_text(
                "❌ Произошла ошибка при сохранении профиля в базу данных.\n\n"
                "Пожалуйста, попробуйте еще раз через минуту.\n\n"
                "Если проблема повторяется, обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")
                ]])
            )
            context.user_data.clear()
            return ConversationHandler.END

        keyboard = [[InlineKeyboardButton("💼 Моё меню рекламодатела", callback_data="show_client_menu")]]
        await query.edit_message_text(
            "🥳 <b>Профиль рекламодатела создан!</b>\n\n"
            "Теперь вы можете:\n"
            "• 📝 Создавать кампании\n"
            "• 🔍 Искать блогеров\n"
            "• 💬 Общаться с блогерами\n\n"
            "Детали о задаче вы опишете при создании кампания!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        context.user_data.clear()
        logger.info("✅ Context очищен")
        return ConversationHandler.END


async def register_advertiser_city_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод другого города клиентом вручную"""
    city = update.message.text.strip()
    context.user_data["city"] = city
    region = context.user_data.get("region", city)
    context.user_data["regions"] = region

    # Создаём профиль
    telegram_id = update.effective_user.id

    # КРИТИЧНО: Обработка ошибок БД при создании пользователя и профиля
    user_created = False  # Флаг для отслеживания создания нового пользователя
    user_id = None

    try:
        # Проверяем есть ли уже user (если добавляет вторую роль)
        existing_user = db.get_user(telegram_id)
        if existing_user:
            user_id = existing_user["id"]
        else:
            user_id = db.create_user(telegram_id, "advertiser")
            user_created = True  # КРИТИЧНО: Отмечаем что создали нового пользователя

        db.create_client_profile(
            user_id=user_id,
            name=context.user_data["name"],
            phone=context.user_data["phone"],
            city=context.user_data["city"],
            description="",
            regions=context.user_data["regions"],
        )

    except ValueError as e:
        # Ошибки валидации (например, дубликат профиля)
        logger.error(f"❌ Ошибка валидации при создании профиля клиента: {e}")

        # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
        if user_created and user_id:
            try:
                db.delete_user_profile(telegram_id)
                logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

        keyboard = [[InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")]]
        await update.message.reply_text(
            f"❌ Не удалось создать профиль.\n\n"
            f"Причина: {str(e)}\n\n"
            f"Попробуйте еще раз или обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data.clear()
        return ConversationHandler.END

    except Exception as e:
        # Любые другие ошибки БД
        logger.error(f"❌ Ошибка БД при создании профиля клиента: {e}", exc_info=True)

        # КРИТИЧНО: Откатываем создание пользователя если создали его, но профиль не создался
        if user_created and user_id:
            try:
                db.delete_user_profile(telegram_id)
                logger.info(f"🔄 Откат: удален пользователь {telegram_id} после ошибки создания профиля")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате создания пользователя: {rollback_error}")

        keyboard = [[InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")]]
        await update.message.reply_text(
            "❌ Произошла ошибка при сохранении профиля в базу данных.\n\n"
            "Пожалуйста, попробуйте еще раз через минуту.\n\n"
            "Если проблема повторяется, обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data.clear()
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("💼 Моё меню рекламодатела", callback_data="show_client_menu")]]
    await update.message.reply_text(
        "🥳 <b>Профиль рекламодатела создан!</b>\n\n"
        "Теперь вы можете:\n"
        "• 📝 Создавать кампании\n"
        "• 🔍 Искать блогеров\n"
        "• 💬 Общаться с блогерами\n\n"
        "Детали о задаче вы опишете при создании кампания!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    context.user_data.clear()
    return ConversationHandler.END


# ------- МЕНЮ -------

async def show_blogger_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # ИСПРАВЛЕНИЕ БАГА: Очищаем активный чат при возврате в меню
    # Это предотвращает открытие неправильного чата при нажатии "Обновить чат"
    db.clear_active_chat(update.effective_user.id)

    # Получаем текущий статус уведомлений
    user = db.get_user_by_telegram_id(update.effective_user.id)
    notifications_enabled = db.are_notifications_enabled(user['id']) if user else True
    notification_status = "🔔 Вкл" if notifications_enabled else "🔕 Выкл"

    # НОВОЕ: Получаем количество непрочитанных кампаний
    unread_orders_count = 0
    if user:
        notification = db.get_worker_notification(user['id'])
        if notification:
            unread_orders_count = dict(notification).get('available_orders_count', 0)

    # Формируем текст кнопки с бейджем
    orders_button_text = "📋 Рекламные предложения"
    if unread_orders_count > 0:
        orders_button_text = f"📋 Рекламные предложения 🔴 {unread_orders_count}"

    # Проверяем наличие новых акций
    news_button_text = "🎯 Новости и акции"
    if db.has_unviewed_ads(user['id'], 'menu_banner', user_role='blogger'):
        news_button_text = "🎯 Новости и акции 🔴 НОВОЕ"

    # Проверяем заполненность профиля для индикатора
    profile_complete = is_profile_complete(user['id'], "blogger")
    profile_button_text = "👤 Мой профиль"
    if not profile_complete:
        profile_button_text = "👤 Мой профиль ⚠️"

    keyboard = [
        [InlineKeyboardButton(orders_button_text, callback_data="worker_view_orders")],
        [InlineKeyboardButton("💼 Мои отклики", callback_data="worker_my_bids")],
        [InlineKeyboardButton("📦 Мои кампании", callback_data="worker_my_orders")],
        [InlineKeyboardButton(profile_button_text, callback_data="worker_profile")],
        [InlineKeyboardButton(f"{notification_status} Уведомления", callback_data="toggle_notifications")],
        [InlineKeyboardButton("💡 Предложения", callback_data="send_suggestion")],
        [InlineKeyboardButton(news_button_text, callback_data="show_news_and_ads")],  # НОВОЕ: Постоянная кнопка для рекламы с индикатором
        [InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")],
    ]

    # Добавляем кнопку админки только для админов
    if db.is_admin(update.effective_user.id):
        keyboard.insert(0, [InlineKeyboardButton("📱 Админ-панель", callback_data="admin_panel")])

    # Удаляем старое сообщение и отправляем новое
    # (работает с любым типом сообщения: текст, фото, медиа)
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="🎬 <b>Меню блогера</b>\n\n"
             "Добро пожаловать! Здесь вы найдёте рекламные кампании от брендов.\n"
             "Откликайтесь на интересные предложения и зарабатывайте на своём контенте.\n\n"
             "Выберите действие:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def blogger_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр доступных кампаний для блогера"""
    query = update.callback_query
    await query.answer()

    # Сбрасываем страницу при входе в список
    context.user_data['campaigns_page'] = 0

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    user_dict = dict(user)
    profile_complete = is_profile_complete(user_dict['id'], 'blogger')

    if not profile_complete:
        await query.edit_message_text(
            "⚠️ <b>Профиль не заполнен</b>\n\n"
            "Для просмотра доступных кампаний необходимо заполнить профиль:\n"
            "• Город\n"
            "• Тематика контента\n"
            "• Описание\n"
            "• Хотя бы одна социальная сеть\n\n"
            "Перейдите в профиль и заполните обязательные поля.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚙️ Настройки профиля", callback_data="edit_profile_menu")
            ], [
                InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")
            ]])
        )
        return

    try:
        # Обнуляем счётчик непрочитанных кампаний
        db.save_worker_notification(user_dict['id'], None, None, 0)

        # Получаем профиль блогера
        worker_profile = db.get_worker_profile(user_dict["id"])
        if not worker_profile:
            await query.edit_message_text("❌ Ошибка: профиль блогера не найден.")
            return

        worker_dict = dict(worker_profile)
        worker_id = worker_dict['id']
        categories = (worker_dict.get("categories") or "").split(", ")

        # Получаем кампании по категориям блогера
        all_orders = db.get_orders_by_categories(categories, per_page=10000, blogger_id=worker_id)
        all_orders = [dict(campaign) for campaign in all_orders]

        # Фильтруем кампании - не показываем те, на которые блогер уже откликнулся или отказался
        all_orders = [campaign for campaign in all_orders
                     if not db.check_worker_bid_exists(campaign['id'], worker_id)
                     and not db.check_order_declined(user_dict["id"], campaign['id'])]

        if not all_orders:
            keyboard = [
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")],
            ]

            await query.edit_message_text(
                "📋 <b>Рекламные предложения</b>\n\n"
                "Пока нет открытых кампаний по вашим категориям.\n\n"
                "Как только появятся новые рекламные предложения, вы их увидите здесь!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Показываем список кампаний
        orders_text = "📋 <b>Рекламные предложения</b>\n\n"
        orders_text += f"Найдено предложений: <b>{len(all_orders)}</b>\n\n"

        # Пагинация - показываем по 5 кампаний
        page = context.user_data.get('campaigns_page', 0)
        per_page = 5
        total_pages = (len(all_orders) + per_page - 1) // per_page

        # Сохраняем данные для навигации
        context.user_data['all_campaigns'] = all_orders
        context.user_data['campaigns_page'] = page

        start_idx = page * per_page
        end_idx = min(start_idx + per_page, len(all_orders))
        current_campaigns = all_orders[start_idx:end_idx]

        keyboard = []
        for i, campaign in enumerate(current_campaigns, start_idx + 1):
            advertiser_name = campaign.get('advertiser_name', 'Неизвестно')
            orders_text += f"🟢 <b>{advertiser_name}</b>\n"
            orders_text += f"📍 Город: {campaign.get('city', 'Не указан')}\n"

            # Отображение оплаты
            payment_type = campaign.get('payment_type', 'paid')
            budget_type = campaign.get('budget_type', 'none')
            budget_value = campaign.get('budget_value', 0)

            payment_parts = []

            # Если оплата денежная (paid или both)
            if payment_type in ['paid', 'both']:
                if budget_value and budget_value > 0:
                    if budget_type == 'fixed':
                        payment_parts.append(f"💰 {int(budget_value)} BYN (фиксированная)")
                    elif budget_type == 'flexible':
                        payment_parts.append(f"💰 {int(budget_value)} BYN (гибкая)")
                    else:
                        payment_parts.append(f"💰 {int(budget_value)} BYN")
                elif budget_type == 'flexible':
                    payment_parts.append("💬 Блогеры предложат цену")

            # Если есть бартер
            if payment_type in ['barter', 'both']:
                payment_parts.append("🤝 Бартер")

            # Показываем оплату
            if payment_parts:
                orders_text += f"💵 {' + '.join(payment_parts)}\n"
            else:
                orders_text += f"💵 По договорённости\n"

            # Описание (сокращённое)
            description = campaign.get('description', '')
            if len(description) > 80:
                description = description[:80] + "..."
            orders_text += f"📝 {description}\n"
            orders_text += "\n"

            # Добавляем кнопку для просмотра деталей
            keyboard.append([InlineKeyboardButton(
                f"👁 {advertiser_name} - Подробнее",
                callback_data=f"view_order_{campaign['id']}"
            )])

        # Кнопки навигации по страницам
        if total_pages > 1:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data="campaigns_prev_page"))
            nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data="campaigns_next_page"))
            keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")])

        await safe_edit_message(
            query,
            orders_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре кампаний: {e}", exc_info=True)
        await safe_edit_message(
            query,
            "❌ Произошла ошибка при загрузке кампаний.\n\n"
            "Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
            ])
        )


async def navigate_campaigns_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по страницам списка кампаний для блогера"""
    query = update.callback_query
    await query.answer()

    # Получаем текущую страницу
    page = context.user_data.get('campaigns_page', 0)
    all_campaigns = context.user_data.get('all_campaigns', [])

    if not all_campaigns:
        await query.answer("❌ Данные не найдены, обновите список", show_alert=True)
        return

    per_page = 5
    total_pages = (len(all_campaigns) + per_page - 1) // per_page

    # Определяем направление
    if query.data == "campaigns_next_page":
        page = min(page + 1, total_pages - 1)
    elif query.data == "campaigns_prev_page":
        page = max(page - 1, 0)

    context.user_data['campaigns_page'] = page

    # Перестраиваем сообщение
    user = db.get_user_by_telegram_id(update.effective_user.id)
    worker_profile = db.get_worker_profile(user['id'])
    worker_dict = dict(worker_profile)

    orders_text = "📋 <b>Рекламные предложения</b>\n\n"
    orders_text += f"Найдено предложений: <b>{len(all_campaigns)}</b>\n\n"

    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(all_campaigns))
    current_campaigns = all_campaigns[start_idx:end_idx]

    keyboard = []
    for i, campaign in enumerate(current_campaigns, start_idx + 1):
        advertiser_name = campaign.get('advertiser_name', 'Неизвестно')
        orders_text += f"🟢 <b>{advertiser_name}</b>\n"
        orders_text += f"📍 Город: {campaign.get('city', 'Не указан')}\n"

        payment_type = campaign.get('payment_type', 'paid')
        budget_type = campaign.get('budget_type', 'none')
        budget_value = campaign.get('budget_value', 0)
        payment_parts = []

        if payment_type in ['paid', 'both']:
            if budget_value and budget_value > 0:
                if budget_type == 'fixed':
                    payment_parts.append(f"💰 {int(budget_value)} BYN (фиксированная)")
                elif budget_type == 'flexible':
                    payment_parts.append(f"💰 {int(budget_value)} BYN (гибкая)")
                else:
                    payment_parts.append(f"💰 {int(budget_value)} BYN")
            elif budget_type == 'flexible':
                payment_parts.append("💬 Блогеры предложат цену")

        if payment_type in ['barter', 'both']:
            payment_parts.append("🤝 Бартер")

        if payment_parts:
            orders_text += f"💵 {' + '.join(payment_parts)}\n"
        else:
            orders_text += f"💵 По договорённости\n"

        description = campaign.get('description', '')
        if len(description) > 80:
            description = description[:80] + "..."
        orders_text += f"📝 {description}\n\n"

        keyboard.append([InlineKeyboardButton(
            f"👁 {advertiser_name} - Подробнее",
            callback_data=f"view_order_{campaign['id']}"
        )])

    # Кнопки навигации
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data="campaigns_prev_page"))
        nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data="campaigns_next_page"))
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")])

    await safe_edit_message(
        query,
        orders_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def toggle_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает уведомления для блогера"""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    # Получаем текущий статус
    current_status = db.are_notifications_enabled(user['id'])

    # Переключаем статус
    new_status = not current_status
    db.set_notifications_enabled(user['id'], new_status)

    status_text = "включены ✅" if new_status else "отключены ❌"

    # ИСПРАВЛЕНО: Вынесли текст в переменные (нельзя использовать \n внутри f-string expression)
    notification_on_text = 'Вы будете получать уведомления о новых заказах в вашем городе и категориях.'
    notification_off_text = 'Вы НЕ будете получать уведомления о новых заказах. Вы можете просматривать кампании вручную в разделе "Доступные кампании".'

    await query.edit_message_text(
        f"🔔 <b>Уведомления {status_text}</b>\n\n"
        f"{notification_on_text if new_status else notification_off_text}\n\n"
        "Возвращаемся в меню...",
        parse_mode="HTML"
    )

    # Возвращаемся в меню блогера через 2 секунды
    await asyncio.sleep(2)
    await show_blogger_menu(update, context)


async def toggle_advertiser_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает уведомления для клиента"""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    # Получаем текущий статус
    current_status = db.are_client_notifications_enabled(user['id'])

    # Переключаем статус
    new_status = not current_status
    db.set_client_notifications_enabled(user['id'], new_status)

    status_text = "включены ✅" if new_status else "отключены ❌"

    notification_on_text = 'Вы будете получать уведомления о новых откликах на ваши кампании.'
    notification_off_text = 'Вы НЕ будете получать уведомления об откликах. Вы можете проверять отклики вручную в разделе "Мои кампании".'

    await query.edit_message_text(
        f"🔔 <b>Уведомления {status_text}</b>\n\n"
        f"{notification_on_text if new_status else notification_off_text}\n\n"
        "Возвращаемся в меню...",
        parse_mode="HTML"
    )

    # Возвращаемся в меню рекламодателя через 2 секунды
    await asyncio.sleep(2)
    await show_advertiser_menu(update, context)


async def blogger_my_offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает только АКТИВНЫЕ отклики блогера (где блогера ещё не выбрали)"""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    # Получаем профиль блогера
    blogger = db.get_worker_by_user_id(user['id'])
    if not blogger:
        await query.edit_message_text(
            "❌ Профиль блогера не найден.\n\n"
            "Возможно, вы зарегистрированы как рекламодател."
        )
        return

    worker_dict = dict(blogger)

    # Получаем все отклики блогера
    all_bids = db.get_bids_for_worker(worker_dict['id'])

    if not all_bids:
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")]]
        await query.edit_message_text(
            "💼 <b>Мои отклики</b>\n\n"
            "У вас пока нет откликов на кампаниюи.\n\n"
            "Перейдите в раздел \"Доступные кампании\" и откликнитесь на интересные вам кампании!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ИСПРАВЛЕНО: Фильтруем только АКТИВНЫЕ отклики (active - ждём ответа клиента)
    # Статус 'active' присваивается при создании предложения в db.create_bid()
    active_bids = [dict(offer) for offer in all_bids if dict(offer)['status'] == 'active']

    if not active_bids:
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")]]
        await query.edit_message_text(
            "💼 <b>Активные отклики</b>\n\n"
            "У вас нет активных откликов, ожидающих ответа клиента.\n\n"
            "Все ваши отклики либо были приняты (см. \"Мои кампании\"), либо отклонены.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Формируем текст с активными откликами
    text = f"💼 <b>Активные отклики</b> ({len(active_bids)})\n\n"
    text += "⏳ Ожидают ответа клиента:\n\n"

    keyboard = []

    for i, offer in enumerate(active_bids[:10], 1):  # Показываем до 10 активных
        campaign_id = offer['campaign_id']
        campaign = db.get_order_by_id(campaign_id)

        if campaign:
            campaign_dict = dict(campaign)
            category = campaign_dict.get('category', 'Без категории')
            description = campaign_dict.get('description', '')
            advertiser_name = campaign_dict.get('advertiser_name', 'Неизвестно')
            if len(description) > 40:
                description = description[:40] + "..."

            text += f"{i}. <b>{advertiser_name}</b>\n"
            text += f"📱 {category}\n"
            text += f"📝 {description}\n"
            text += f"💰 Ваша цена: {offer['proposed_price']} {offer['currency']}\n"

            # Добавляем кнопку для просмотра кампания
            keyboard.append([InlineKeyboardButton(
                f"📋 {advertiser_name}",
                callback_data=f"view_order_{campaign_id}"
            )])

            text += "\n"

    if len(active_bids) > 10:
        text += f"... и ещё {len(active_bids) - 10}\n\n"

    text += f"📊 <b>Всего активных откликов:</b> {len(active_bids)}"

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def blogger_my_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор категории заказов блогера (в работе/завершённые)"""
    query = update.callback_query
    await query.answer()

    try:
        # Получаем пользователя и профиль блогера
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)

        # Удаляем уведомление о новых сообщениях (пользователь открыл кампании)
        db.delete_chat_message_notification(user_dict['id'])

        worker_profile = db.get_worker_profile(user_dict["id"])
        if not worker_profile:
            await safe_edit_message(
                query,
                "❌ Профиль блогера не найден.\n\n"
                "Возможно произошла ошибка при регистрации.\n"
                "Нажмите /start и зарегистрируйтесь заново.",
                parse_mode="HTML"
            )
            return

        worker_dict = dict(worker_profile)

        # Получаем все отклики блогера
        bids = db.get_bids_for_worker(worker_dict['id'])

        # Подсчитываем кампании по статусам
        active_count = 0
        completed_count = 0

        for offer in bids:
            bid_dict = dict(offer)
            if bid_dict['status'] == 'selected':
                campaign = db.get_order_by_id(bid_dict['campaign_id'])
                if campaign:
                    campaign_dict = dict(campaign)
                    if campaign_dict['status'] in ('master_selected', 'contact_shared', 'master_confirmed', 'waiting_master_confirmation'):
                        active_count += 1
                    elif campaign_dict['status'] in ('done', 'completed', 'canceled', 'cancelled'):
                        completed_count += 1

        if active_count == 0 and completed_count == 0:
            keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")]]
            await safe_edit_message(
                query,
                "📦 <b>Мои кампании</b>\n\n"
                "У вас пока нет заказов.\n\n"
                "Когда клиент выберет ваше предложение, кампания появится здесь.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Показываем меню выбора категории
        text = "📦 <b>Мои кампании</b>\n\n"
        text += f"Всего заказов: {active_count + completed_count}\n"
        text += f"📱 В работе: {active_count}\n"
        text += f"✅ Завершённые: {completed_count}\n\n"
        text += "Выберите категорию:"

        keyboard = [
            [InlineKeyboardButton(f"📱 Кампании в работе ({active_count})", callback_data="blogger_active_campaigns")],
            [InlineKeyboardButton(f"✅ Завершённые кампании ({completed_count})", callback_data="blogger_completed_campaigns")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")]
        ]

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в worker_my_orders: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка при загрузке заказов:\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")
            ]])
        )


async def blogger_active_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает активные кампании блогера (в работе)"""
    query = update.callback_query
    await query.answer()

    try:
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict["id"])
        if not worker_profile:
            await safe_edit_message(query, "❌ Профиль блогера не найден.")
            return

        worker_dict = dict(worker_profile)

        # Получаем все отклики и фильтруем активные кампании
        bids = db.get_bids_for_worker(worker_dict['id'])
        active_orders = []

        for offer in bids:
            bid_dict = dict(offer)
            if bid_dict['status'] == 'selected':
                campaign = db.get_order_by_id(bid_dict['campaign_id'])
                if campaign:
                    campaign_dict = dict(campaign)
                    if campaign_dict['status'] in ('master_selected', 'contact_shared', 'master_confirmed', 'waiting_master_confirmation'):
                        bid_dict['order_status'] = campaign_dict['status']
                        bid_dict['order_city'] = campaign_dict.get('city', 'Не указан')
                        bid_dict['order_category'] = campaign_dict.get('category', 'Без категории')
                        bid_dict['order_description'] = campaign_dict.get('description', '')
                        active_orders.append(bid_dict)

        if not active_orders:
            keyboard = [[InlineKeyboardButton("⬅️ Назад к заказам", callback_data="worker_my_orders")]]
            await safe_edit_message(
                query,
                "📱 <b>Кампании в работе</b>\n\nУ вас нет активных заказов.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Формируем текст и кнопки
        text = f"📱 <b>Кампании в работе</b> ({len(active_orders)})\n\n"
        keyboard = []

        for i, campaign in enumerate(active_orders[:10], 1):
            text += f"{i}. <b>Кампания #{campaign['campaign_id']}</b>\n"
            text += f"📱 {campaign.get('order_category', 'Без категории')}\n"

            description = campaign.get('order_description', '')
            if len(description) > 50:
                description = description[:50] + "..."
            text += f"📝 {description}\n"
            text += f"💰 {campaign['proposed_price']} {campaign['currency']}\n"

            # Кнопка чата
            chat = db.get_chat_by_order(campaign['campaign_id'])
            if chat:
                chat_dict = dict(chat)
                keyboard.append([InlineKeyboardButton(
                    f"💬 Чат (кампания #{campaign['campaign_id']})",
                    callback_data=f"open_chat_{chat_dict['id']}"
                )])

            # Кнопка завершения
            keyboard.append([InlineKeyboardButton(
                f"✅ Завершить кампаниюя #{campaign['campaign_id']}",
                callback_data=f"complete_campaign_{campaign['campaign_id']}"
            )])

            text += "\n"

        keyboard.append([InlineKeyboardButton("⬅️ Назад к заказам", callback_data="worker_my_orders")])

        await safe_edit_message(query, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Ошибка в blogger_active_campaigns: {e}", exc_info=True)
        await safe_edit_message(query, f"❌ Ошибка: {str(e)}")


async def blogger_completed_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает завершённые кампании блогера"""
    query = update.callback_query
    await query.answer()

    try:
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict["id"])
        if not worker_profile:
            await safe_edit_message(query, "❌ Профиль блогера не найден.")
            return

        worker_dict = dict(worker_profile)

        # Получаем все отклики и фильтруем завершённые кампании
        bids = db.get_bids_for_worker(worker_dict['id'])
        completed_orders = []

        for offer in bids:
            bid_dict = dict(offer)
            if bid_dict['status'] == 'selected':
                campaign = db.get_order_by_id(bid_dict['campaign_id'])
                if campaign:
                    campaign_dict = dict(campaign)
                    if campaign_dict['status'] in ('done', 'completed', 'canceled', 'cancelled'):
                        bid_dict['order_status'] = campaign_dict['status']
                        bid_dict['order_city'] = campaign_dict.get('city', 'Не указан')
                        bid_dict['order_category'] = campaign_dict.get('category', 'Без категории')
                        bid_dict['order_description'] = campaign_dict.get('description', '')
                        completed_orders.append(bid_dict)

        if not completed_orders:
            keyboard = [[InlineKeyboardButton("⬅️ Назад к заказам", callback_data="worker_my_orders")]]
            await safe_edit_message(
                query,
                "✅ <b>Завершённые кампании</b>\n\nУ вас нет завершённых заказов.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Формируем текст и кнопки
        text = f"✅ <b>Завершённые кампании</b> ({len(completed_orders)})\n\n"
        keyboard = []

        for i, campaign in enumerate(completed_orders[:10], 1):
            status_emoji = {"done": "✅", "completed": "✅", "canceled": "❌"}
            emoji = status_emoji.get(campaign.get('order_status', 'done'), "✅")

            text += f"{i}. {emoji} <b>Кампания #{campaign['campaign_id']}</b>\n"
            text += f"📱 {campaign.get('order_category', 'Без категории')}\n"

            description = campaign.get('order_description', '')
            if len(description) > 50:
                description = description[:50] + "..."
            text += f"📝 {description}\n"
            text += f"💰 {campaign['proposed_price']} {campaign['currency']}\n"

            # Кнопка чата для просмотра истории
            chat = db.get_chat_by_order(campaign['campaign_id'])
            if chat:
                chat_dict = dict(chat)
                keyboard.append([InlineKeyboardButton(
                    f"💬 Посмотреть чат (кампания #{campaign['campaign_id']})",
                    callback_data=f"open_chat_{chat_dict['id']}"
                )])

            text += "\n"

        keyboard.append([InlineKeyboardButton("⬅️ Назад к заказам", callback_data="worker_my_orders")])

        await safe_edit_message(query, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Ошибка в blogger_completed_campaigns: {e}", exc_info=True)
        await safe_edit_message(query, f"❌ Ошибка: {str(e)}")


def _get_order_status_text(status):
    """Возвращает читаемый текст статуса кампания"""
    status_map = {
        'open': '🟢 Открыт',
        'waiting_master_confirmation': '⏳ Ожидает подтверждения',
        'master_confirmed': '✅ Блогер подтвердил',
        'master_selected': '👤 Блогер выбран',
        'completed': '✅ Завершен',
        'cancelled': '❌ Отменён'
    }
    return status_map.get(status, status)


async def show_advertiser_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # ИСПРАВЛЕНИЕ БАГА: Очищаем активный чат при возврате в меню
    # Это предотвращает открытие неправильного чата при нажатии "Обновить чат"
    db.clear_active_chat(update.effective_user.id)

    # Получаем текущий статус уведомлений для клиента
    user = db.get_user_by_telegram_id(update.effective_user.id)
    notifications_enabled = db.are_client_notifications_enabled(user['id']) if user else True
    notification_status = "🔔 Вкл" if notifications_enabled else "🔕 Выкл"

    # НОВОЕ: Получаем количество непрочитанных откликов
    unread_bids_count = 0
    if user:
        notification = db.get_client_notification(user['id'])
        if notification:
            unread_bids_count = notification.get('unread_bids_count', 0)

    # Формируем текст кнопки с бейджем
    orders_button_text = "📂 Мои кампании"
    if unread_bids_count > 0:
        orders_button_text = f"📂 Мои кампании 🔴 {unread_bids_count}"

    # Проверяем наличие новых акций
    news_button_text = "🎯 Новости и акции"
    if db.has_unviewed_ads(user['id'], 'menu_banner', user_role='advertiser'):
        news_button_text = "🎯 Новости и акции 🔴 НОВОЕ"

    keyboard = [
        [InlineKeyboardButton("📝 Создать рекламную кампанию", callback_data="client_create_order")],
        [InlineKeyboardButton(orders_button_text, callback_data="client_my_orders")],
        # [InlineKeyboardButton("💳 Мои платежи", callback_data="client_my_payments")],  # Скрыто до внедрения платной версии
        [InlineKeyboardButton("✏️ Изменить название страницы", callback_data="edit_advertiser_name")],
        [InlineKeyboardButton(f"{notification_status} Уведомления", callback_data="toggle_client_notifications")],
        [InlineKeyboardButton("💡 Предложения", callback_data="send_suggestion")],
        [InlineKeyboardButton(news_button_text, callback_data="show_news_and_ads")],  # НОВОЕ: Постоянная кнопка для рекламы с индикатором
        [InlineKeyboardButton("🎬 Главное меню", callback_data="go_main_menu")],
    ]

    # Добавляем кнопку админки только для админов
    if db.is_admin(update.effective_user.id):
        keyboard.insert(0, [InlineKeyboardButton("📱 Админ-панель", callback_data="admin_panel")])

    # Удаляем старое сообщение и отправляем новое
    # (работает с любым типом сообщения: текст, фото, медиа)
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="💼 <b>Меню рекламодателя</b>\n\n"
             "Создайте рекламную кампанию - блогеры увидят её и откликнутся!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def start_edit_advertiser_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс изменения названия страницы рекламодателя"""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return ConversationHandler.END

    # Проверяем возможность изменения названия
    can_change, days_remaining = db.can_change_advertiser_name(user['id'])

    if not can_change:
        keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")]]

        if days_remaining is not None:
            await query.edit_message_text(
                f"⏳ <b>Изменение названия страницы</b>\n\n"
                f"Вы уже меняли название страницы недавно.\n\n"
                f"Вы сможете изменить название через <b>{days_remaining} дн.</b>\n\n"
                f"Ограничение: 1 раз в месяц.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                "❌ Профиль не найден.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return ConversationHandler.END

    # Получаем текущее название
    client_profile = db.get_client_profile(user['id'])
    current_name = client_profile.get('name', 'Не указано') if client_profile else 'Не указано'

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel")]]

    await query.edit_message_text(
        f"✏️ <b>Изменение названия страницы</b>\n\n"
        f"Текущее название: <b>{current_name}</b>\n\n"
        f"Введите новое название для вашей страницы.\n\n"
        f"⚠️ Внимание: После изменения вы сможете изменить название снова только через 30 дней.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return EDIT_ADVERTISER_NAME


async def handle_new_advertiser_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает новое название страницы рекламодателя"""
    new_name = update.message.text.strip()

    # Валидация имени
    if not is_valid_name(new_name):
        await update.message.reply_text(
            "❌ Пожалуйста, укажите корректное название без ссылок и рекламы.\n"
            "Пример: «Александр», «Иван Петров», «Компания XYZ».\n\n"
            "Попробуйте снова или введите /cancel для отмены."
        )
        return EDIT_ADVERTISER_NAME

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ Пользователь не найден.")
        return ConversationHandler.END

    # Обновляем название
    success, message = db.update_advertiser_name(user['id'], new_name)

    keyboard = [[InlineKeyboardButton("💼 Вернуться в меню", callback_data="show_client_menu")]]

    if success:
        await update.message.reply_text(
            f"✅ <b>{message}</b>\n\n"
            f"Новое название: <b>{new_name}</b>\n\n"
            f"Следующее изменение будет доступно через 30 дней.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            f"❌ <b>Ошибка</b>\n\n{message}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    return ConversationHandler.END


async def advertiser_my_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю платежей клиента"""
    query = update.callback_query
    await query.answer()

    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    # Получаем историю транзакций
    transactions = db.get_user_transactions(user['id'])

    if not transactions:
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="show_client_menu")]]
        await query.edit_message_text(
            "💳 <b>Мои платежи</b>\n\n"
            "У вас пока нет платежей.\n\n"
            "Когда вы выберете блогера для кампания и оплатите доступ к его контактам, "
            "платежи будут отображаться здесь.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Формируем текст с платежами
    text = "💳 <b>Мои платежи</b>\n\n"

    total_spent = 0.0

    for transaction in transactions[:10]:  # Показываем последние 10 платежей
        trans_dict = dict(transaction)
        amount = float(trans_dict['amount'])
        currency = trans_dict['currency']
        total_spent += amount

        # Форматируем дату
        from datetime import datetime
        created_at_raw = trans_dict['created_at']
        # PostgreSQL возвращает datetime объект, SQLite возвращает строку
        if isinstance(created_at_raw, str):
            created_at = datetime.fromisoformat(created_at_raw)
            date_str = created_at.strftime("%d.%m.%Y %H:%M")
        else:
            # datetime объект - форматируем напрямую
            date_str = created_at_raw.strftime("%d.%m.%Y %H:%M")

        # Получаем описание или тип транзакции
        description = trans_dict.get('description', '')
        if not description:
            trans_type = trans_dict.get('transaction_type', 'payment')
            description = f"Платёж ({trans_type})"

        # Статус транзакции
        status = trans_dict.get('status', 'unknown')
        status_emoji = "✅" if status == 'completed' else "⏳" if status == 'pending' else "❌"

        text += f"{status_emoji} <b>{amount:.2f} {currency}</b>\n"
        text += f"  {description[:50]}{'...' if len(description) > 50 else ''}\n"
        text += f"  📅 {date_str}\n\n"

    if len(transactions) > 10:
        text += f"... и ещё {len(transactions) - 10} платежей\n\n"

    text += f"💰 <b>Всего потрачено:</b> {total_spent:.2f} BYN\n"
    text += f"📊 <b>Количество платежей:</b> {len(transactions)}"

    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="show_client_menu")]]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ------- ПРОФИЛЬ МАСТЕРА -------

async def show_blogger_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ профиля блогера с правильным доступом к базе данных"""
    query = update.callback_query
    await query.answer()

    # Очищаем context для сброса всех активных флагов (например, uploading_profile_photo)
    context.user_data.clear()

    telegram_id = query.from_user.id
    logger.info(f"Запрос профиля блогера для telegram_id: {telegram_id}")
    
    try:
        user = db.get_user(telegram_id)
        
        if not user:
            logger.error(f"Пользователь не найден: telegram_id={telegram_id}")
            await query.edit_message_text(
                "❌ Профиль не найден в базе данных.\n\n"
                "Попробуйте использовать /reset_profile и зарегистрируйтесь заново."
            )
            return

        # ИСПРАВЛЕНО: Используем dict() для безопасного доступа к sqlite3.Row
        user_dict = dict(user)
        user_id = user_dict.get("id")
        role = user_dict.get("role")
        
        logger.info(f"Найден пользователь: id={user_id}, role={role}")

        if role not in ["blogger", "both"]:
            logger.error(f"Пользователь не является мастером: role={role}")
            await query.edit_message_text(
                "❌ Вы не зарегистрированы как блогер.\n\n"
                "Используйте /reset_profile для перерегистрации."
            )
            return

        worker_profile = db.get_worker_profile(user_id)

        if not worker_profile:
            logger.error(f"Профиль блогера не найден для user_id={user_id}")
            await query.edit_message_text(
                "❌ Профиль блогера не заполнен.\n\n"
                "Используйте /reset_profile и пройдите регистрацию заново."
            )
            return

        logger.info(f"Профиль блогера найден для user_id={user_id}")

        # ИСПРАВЛЕНО: Конвертируем в dict для безопасного доступа к sqlite3.Row
        profile_dict = dict(worker_profile)
        
        name = profile_dict.get("name") or "—"
        phone = profile_dict.get("phone") or "—"
        city = profile_dict.get("city") or "—"
        regions = profile_dict.get("regions") or "—"
        categories = profile_dict.get("categories") or "—"
        experience = profile_dict.get("experience") or "—"
        description = profile_dict.get("description") or "—"
        rating = profile_dict.get("rating") or 0
        rating_count = profile_dict.get("rating_count") or 0
        verified_reviews = profile_dict.get("verified_reviews") or 0
        portfolio_photos = profile_dict.get("portfolio_photos") or ""
        profile_photo = profile_dict.get("profile_photo") or ""

        # Социальные сети
        instagram = profile_dict.get("instagram_link") or ""
        youtube = profile_dict.get("youtube_link") or ""
        tiktok = profile_dict.get("tiktok_link") or ""
        telegram = profile_dict.get("telegram_link") or ""
        threads = profile_dict.get("threads_link") or ""

        # Подписчики
        instagram_followers = profile_dict.get("instagram_followers") or 0
        tiktok_followers = profile_dict.get("tiktok_followers") or 0
        youtube_followers = profile_dict.get("youtube_followers") or 0
        telegram_followers = profile_dict.get("telegram_followers") or 0

        # Подсчёт фотографий
        photos_count = len(portfolio_photos.split(",")) if portfolio_photos else 0

        if rating and rating > 0:
            rating_text = f"⭐ {rating:.1f}/5.0"
            reviews_text = f"📊 Отзывов: {rating_count} (проверенных: {verified_reviews})"
        else:
            rating_text = "⭐ Нет отзывов"
            reviews_text = "📊 Отзывов пока нет"

        photos_text = f"📸 Фото контент: {photos_count}" if photos_count > 0 else "📸 Фото контент: не добавлено"

        # Определяем статус профиля
        is_banned = db.is_user_banned(telegram_id)
        profile_complete = is_profile_complete(user_id, "blogger")

        if is_banned:
            status_banner = "🚫 <b>Ваш профиль заблокирован</b>\n\n"
        elif not profile_complete:
            status_banner = "⚠️ <b>Профиль недоступен для продвижения</b>\n" \
                           "Заполните обязательные поля: Город, Тематика, Описание, Социальные сети.\n\n"
        else:
            status_banner = "✅ <b>Ваш профиль активен</b>\n\n"

        # Формируем список социальных сетей с подписчиками
        social_media_list = []
        if instagram:
            followers_str = f" ({format_followers_count(instagram_followers)})" if instagram_followers else ""
            social_media_list.append(f"📸 Instagram{followers_str}: {instagram}")
        if youtube:
            followers_str = f" ({format_followers_count(youtube_followers)})" if youtube_followers else ""
            social_media_list.append(f"📺 YouTube{followers_str}: {youtube}")
        if tiktok:
            followers_str = f" ({format_followers_count(tiktok_followers)})" if tiktok_followers else ""
            social_media_list.append(f"🎵 TikTok{followers_str}: {tiktok}")
        if telegram:
            followers_str = f" ({format_followers_count(telegram_followers)})" if telegram_followers else ""
            social_media_list.append(f"✈️ Telegram{followers_str}: {telegram}")
        if threads:
            social_media_list.append(f"🧵 Threads: {threads}")

        social_media_text = "\n".join(social_media_list) if social_media_list else "❌ Не указаны"

        text = (
            f"{status_banner}"
            "👤 <b>Информация о профиле</b>\n\n"
            f"<b>Имя:</b> {name}\n"
            f"<b>Город:</b> {city if city else '❌ Не указан'}\n"
            f"<b>Районы:</b> {regions if regions else '—'}\n"
            f"<b>Виды контент:</b> {categories if categories else '❌ Не указаны'}\n\n"
            f"<b>Социальные сети:</b>\n{social_media_text}\n\n"
            f"<b>Описание:</b>\n{description if description else '❌ Не заполнено'}\n\n"
            f"{rating_text}\n"
            f"{reviews_text}\n"
            f"{photos_text}"
        )

        keyboard = [
            [InlineKeyboardButton("✏️ Редактировать профиль", callback_data="edit_profile_menu")],
        ]

        # Добавляем кнопку просмотра контент если они есть
        if photos_count > 0:
            keyboard.append([InlineKeyboardButton("📸 Посмотреть портфолио", callback_data="view_portfolio")])

        # Добавляем кнопку отзывов если они есть
        if rating_count > 0:
            keyboard.append([InlineKeyboardButton(f"📊 Отзывы ({rating_count})", callback_data=f"show_reviews_worker_{user_id}")])

        keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")])

        # Показываем фото профиля (лицо), если есть. Иначе - первое из портфолио
        photo_to_show = profile_photo if profile_photo else (portfolio_photos.split(",")[0] if portfolio_photos else None)

        if photo_to_show:
            try:
                await query.message.reply_photo(
                    photo=photo_to_show,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                await query.message.delete()
            except Exception as photo_error:
                # Если не удалось отправить фото (например, file_id документа), показываем без фото
                logger.warning(f"Не удалось отправить фото профиля: {photo_error}")
                await query.edit_message_text(
                    text=text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
        else:
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        logger.info(f"Профиль успешно отображён для telegram_id={telegram_id}")

    except Exception as e:
        logger.error(f"Ошибка при отображении профиля: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка при загрузке профиля.\n\n"
            f"Детали: {str(e)}\n\n"
            f"Используйте /reset_profile для сброса профиля."
        )


# ------- ДОБАВЛЕНИЕ ФОТО ПОСЛЕ РЕГИСТРАЦИИ (БЕЗ ConversationHandler) -------

async def blogger_add_photos_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления фото контент"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_photos = profile_dict.get("portfolio_photos") or ""
    
    # Подсчитываем текущие фото
    current_photos_list = [p for p in current_photos.split(",") if p] if current_photos else []
    current_count = len(current_photos_list)

    # Динамический лимит на основе выполненных заказов
    max_photos = db.calculate_photo_limit(user_id)
    completed_orders = db.get_blogger_completed_campaigns_count(user_id)
    available_slots = max_photos - current_count

    # Сохраняем в context - РЕЖИМ ДОБАВЛЕНИЯ ФОТО АКТИВЕН
    context.user_data["adding_photos"] = True
    context.user_data["existing_photos"] = current_photos_list
    context.user_data["new_photos"] = []

    logger.info(f"📱 DEBUG: Флаг adding_photos установлен для user_id={user_id}, telegram_id={telegram_id}")
    logger.info(f"📊 Лимит фото для блогера: {max_photos} (завершено заказов: {completed_orders})")
    logger.info(f"Запущен режим добавления фото для user_id={user_id}")

    if available_slots <= 0:
        await query.edit_message_text(
            "📸 <b>Портфолио заполнено</b>\n\n"
            f"У вас уже загружено максимум {max_photos} фото в портфолио.\n\n"
            "🗑 <b>Чтобы добавить новые фото:</b>\n"
            "Используйте кнопку «🗑 Управление фото» чтобы удалить старые.\n\n"
            "✨ <b>Хотите больше фото?</b>\n"
            "Загружайте фото завершенных контент после каждого кампания!\n"
            "• До 3 фото за кампанию\n"
            "• С подтверждением рекламодателя ✅\n"
            "• До 90 подтвержденных фото в профиле",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Управление фото", callback_data="manage_portfolio_photos")],
                [InlineKeyboardButton("⬅️ Назад к профилю", callback_data="worker_profile")]
            ])
        )
        context.user_data.clear()
        return

    # Если это первое фото
    if current_count == 0:
        hint_text = "🤵 <b>Первое фото должно быть с вашим лицом!</b>\n" \
                   "Это повышает доверие клиентов.\n\n" \
                   f"После можете добавить до {max_photos - 1} фотографий ваших контент и 1 видео."
    else:
        # Показываем прогресс
        hint_text = f"📊 Загружено: {current_count}/{max_photos}\n" \
                   f"Можно добавить ещё: {available_slots} фото/видео\n\n" \
                   f"💡 Это портфолио (макс. 10 фото). После заказов загружайте подтвержденные фото контент!"

    await query.edit_message_text(
        f"📸 <b>Добавление фото в портфолио</b>\n\n"
        f"{hint_text}\n\n"
        f"Отправьте фотографии (можно по одной или группой).\n\n"
        f"Когда загрузите все фото, нажмите кнопку ниже:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]
        ])
    )


async def blogger_add_photos_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загружаемых фото (photo или document)"""

    telegram_id = update.effective_user.id
    logger.info(f"📱 DEBUG: worker_add_photos_upload вызван для telegram_id={telegram_id}")
    logger.info(f"📱 DEBUG: context.user_data = {context.user_data}")
    logger.info(f"📱 DEBUG: uploading_profile_photo = {context.user_data.get('uploading_profile_photo')}")
    logger.info(f"📱 DEBUG: adding_photos = {context.user_data.get('adding_photos')}")

    # КРИТИЧНО: Проверяем, зарегистрирован ли пользователь
    # Если НЕТ - пропускаем (пусть ConversationHandler регистрации обработает)
    existing_user = db.get_user(telegram_id)
    if not existing_user:
        logger.info(f"📱 DEBUG: Пользователь {telegram_id} НЕ зарегистрирован - пропускаем обработку")
        return  # Пропускаем, чтобы ConversationHandler мог обработать

    logger.info(f"📱 DEBUG: Пользователь {telegram_id} ЗАРЕГИСТРИРОВАН - обрабатываем фото")

    # Если активен режим загрузки фото профиля - передаем управление туда
    if context.user_data.get("uploading_profile_photo"):
        logger.info(f"📱 DEBUG: Передаем управление в upload_profile_photo")
        return await upload_profile_photo(update, context)

    # Проверяем активен ли режим добавления фото
    if not context.user_data.get("adding_photos"):
        # Игнорируем фото если режим не активен
        logger.info("📱 DEBUG: Получено фото но режим добавления не активен - игнорируем")
        return

    file_id = None
    is_video = False

    # Обработка фото (сжатое изображение)
    if update.message and update.message.photo:
        logger.info("Получено фото (photo) для добавления в портфолио")
        photo = update.message.photo[-1]  # Берём самое большое разрешение
        file_id = photo.file_id

    # Обработка видео
    elif update.message and update.message.video:
        # Проверяем, не загружено ли уже видео
        existing_videos = [p for p in context.user_data.get("existing_photos", []) if p.startswith("VIDEO:")]
        new_videos = [p for p in context.user_data.get("new_photos", []) if p.startswith("VIDEO:")]
        if len(existing_videos) + len(new_videos) >= 1:
            keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]
            await update.message.reply_text(
                "⚠️ Можно загрузить максимум 1 видео.\n\n"
                "У вас уже есть видео в портфолио.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        logger.info("Получено видео для добавления в портфолио")
        video = update.message.video
        file_id = "VIDEO:" + video.file_id
        is_video = True

    # Обработка документа (файл без сжатия)
    elif update.message and update.message.document:
        document = update.message.document
        # Проверяем, что это изображение
        if document.mime_type and document.mime_type.startswith('image/'):
            logger.info("Получено фото (document) для добавления в портфолио")
            file_id = document.file_id
        else:
            keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]
            await update.message.reply_text(
                "❌ Можно отправлять только изображения (JPG, PNG и т.д.) или видео.\n\n"
                "Попробуйте отправить фото/видео еще раз.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    if not file_id:
        logger.warning("Не удалось получить file_id из сообщения")
        return

    # КРИТИЧНО: Валидация file_id
    if not validate_file_id(file_id):
        logger.error(f"❌ Невалидный file_id при добавлении фото в портфолио: {file_id}")
        keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]
        await update.message.reply_text(
            "❌ Ошибка при обработке фото.\n\n"
            "Попробуйте отправить фото еще раз или используйте другое изображение.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Получаем user_id для расчета лимита
    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_id = user['id'] if user else None

    existing_count = len(context.user_data.get("existing_photos", []))
    new_count = len(context.user_data.get("new_photos", []))
    total_count = existing_count + new_count

    # Динамический лимит на основе выполненных заказов
    max_photos = db.calculate_photo_limit(user_id) if user_id else 10

    if total_count >= max_photos:
        keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]
        limit_info = "\n\n💡 Загружайте фото после заказов (до 3 фото, подтвержденные рекламодателем)!"

        await update.message.reply_text(
            f"⚠️ Достигнут лимит в {max_photos} фотографий.\n\n"
            f"Нажмите кнопку ниже для завершения:{limit_info}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return

    context.user_data["new_photos"].append(file_id)
    new_count = len(context.user_data["new_photos"])
    total_count = existing_count + new_count
    remaining = max_photos - total_count

    media_type = "Видео" if is_video else "Фото"
    logger.info(f"{media_type} добавлено. Новых: {new_count}, Всего: {total_count}")

    # ДОБАВЛЯЕМ КНОПКУ для завершения
    keyboard = [[InlineKeyboardButton("✅ Завершить добавление", callback_data="finish_adding_photos")]]

    await update.message.reply_text(
        f"✅ {media_type} #{total_count} добавлено!\n\n"
        f"📊 Статус:\n"
        f"• Было: {existing_count}\n"
        f"• Добавлено новых: {new_count}\n"
        f"• Всего будет: {total_count}/{max_photos}\n"
        f"• Можно ещё: {remaining}\n\n"
        f"Отправьте ещё фото/видео или нажмите кнопку:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def blogger_add_photos_finish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки завершения"""
    query = update.callback_query
    await query.answer()

    logger.info(f"Нажата кнопка завершения добавления фото. Context: {context.user_data}")

    # Проверяем есть ли новые фото (более надежная проверка чем флаг adding_photos)
    new_photos = context.user_data.get("new_photos", [])
    has_new_photos = len(new_photos) > 0

    if not context.user_data.get("adding_photos") and not has_new_photos:
        logger.warning("Режим добавления фото не активен и нет новых фото!")
        try:
            await query.edit_message_text(
                "⚠️ Режим добавления фото не активен.\n\n"
                "Возможно произошла ошибка. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
                ])
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {e}")
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="⚠️ Режим добавления фото не активен.\n\nВозвращаемся в меню.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
                ])
            )
        return

    # Вызываем функцию завершения
    await worker_add_photos_finish(query, context)


async def blogger_add_photos_finish(query, context: ContextTypes.DEFAULT_TYPE):
    """Завершение добавления фото - сохранение в БД"""

    logger.info("=== worker_add_photos_finish вызвана ===")
    logger.info(f"Context user_data: {context.user_data}")

    new_photos = context.user_data.get("new_photos", [])
    existing_photos = context.user_data.get("existing_photos", [])

    logger.info(f"new_photos count: {len(new_photos)}")
    logger.info(f"existing_photos count: {len(existing_photos)}")

    if not new_photos:
        logger.warning("Нет новых фото для сохранения")
        keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]]

        # Удаляем старое сообщение и отправляем новое
        try:
            await query.message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        try:
            await query.message.reply_text(
                "⚠️ Вы не добавили ни одного фото.\n\nОперация отменена.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Не удалось отправить reply_text: {e}")
            # Пробуем через edit_message_text
            await query.edit_message_text(
                "⚠️ Вы не добавили ни одного фото.\n\nОперация отменена.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        context.user_data.clear()
        logger.info("Context очищен")
        return
    
    try:
        # Объединяем старые и новые фото
        all_photos = existing_photos + new_photos

        # КРИТИЧНО: Валидация всех file_id перед сохранением в БД
        valid_photos = [fid for fid in all_photos if validate_file_id(fid)]
        if len(valid_photos) < len(all_photos):
            removed_count = len(all_photos) - len(valid_photos)
            logger.warning(f"⚠️ Удалено {removed_count} невалидных file_id перед обновлением портфолио")

        photos_string = ",".join(valid_photos)

        logger.info(f"Объединённые фото (всего {len(valid_photos)} валидных из {len(all_photos)})")
        
        # Получаем telegram_id
        telegram_id = query.from_user.id
        logger.info(f"telegram_id: {telegram_id}")
        
        # Получаем user из БД
        user = db.get_user(telegram_id)
        if not user:
            logger.error(f"Пользователь не найден в БД: telegram_id={telegram_id}")
            raise ValueError(f"User not found: {telegram_id}")
        
        user_dict = dict(user)
        user_id = user_dict.get("id")
        logger.info(f"user_id из БД: {user_id}")
        
        # Обновляем в БД
        result = db.update_worker_field(user_id, "portfolio_photos", photos_string)
        logger.info(f"Результат обновления БД: {result}")
        
        keyboard = [[InlineKeyboardButton("👤 Мой профиль", callback_data="worker_profile")],
                    [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]]

        # Подсчитываем валидные фото (для точной статистики)
        valid_new_photos = [fid for fid in new_photos if validate_file_id(fid)]
        added_count = len(valid_new_photos)
        total_count = len(valid_photos)
        
        message_text = (
            f"✅ <b>Фото успешно добавлены!</b>\n\n"
            f"📊 Итого:\n"
            f"• Добавлено новых: {added_count}\n"
            f"• Всего в портфолио: {total_count}/10\n\n"
            f"Теперь клиенты увидят ваш контент!"
        )
        
        logger.info("Отправка успешного сообщения пользователю")

        # ВАЖНО: Удаляем старое сообщение и отправляем НОВОЕ
        # Потому что последнее сообщение может быть фото (которое нельзя редактировать на текст)
        try:
            await query.message.delete()
            logger.info("Старое сообщение удалено")
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        # Отправляем НОВОЕ сообщение с результатом
        try:
            await query.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            logger.info("Новое сообщение отправлено успешно")
        except Exception as e:
            logger.error(f"Не удалось отправить новое сообщение через reply_text: {e}")
            # Пробуем через bot.send_message напрямую
            try:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML"
                )
                logger.info("Сообщение отправлено через bot.send_message")
            except Exception as e2:
                logger.error(f"Не удалось отправить через bot.send_message: {e2}")

        logger.info("Фото успешно сохранены, ОЧИЩАЮ context.user_data")
        # ВАЖНО: Очищаем context чтобы выйти из режима добавления фото
        context.user_data.clear()
        logger.info("Context очищен - режим добавления фото завершён")
        
    except Exception as e:
        logger.error(f"Ошибка в worker_add_photos_finish: {e}", exc_info=True)
        
        error_text = (
            f"❌ Произошла ошибка при сохранении фото.\n\n"
            f"Детали: {str(e)}\n\n"
            f"Попробуйте ещё раз или обратитесь в поддержку."
        )
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]]
        
        # Удаляем старое и отправляем новое
        try:
            await query.message.delete()
        except:
            pass
        
        await query.message.reply_text(
            error_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        context.user_data.clear()
        logger.info("Context очищен после ошибки")

        context.user_data.clear()
        return ConversationHandler.END


# ------- ГАЛЕРЕЯ РАБОТ МАСТЕРА -------

async def view_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр галереи контент блогера с навигацией"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)

    if not user:
        await query.edit_message_text("❌ Пользователь не найден")
        return

    user_dict = dict(user)
    user_id = user_dict["id"]
    worker_profile = db.get_worker_profile(user_id)

    if not worker_profile:
        await query.edit_message_text("❌ Профиль блогера не найден")
        return

    profile_dict = dict(worker_profile)
    portfolio_photos = profile_dict.get("portfolio_photos") or ""

    if not portfolio_photos:
        await query.edit_message_text(
            "📸 У вас пока нет фото контент.\n\nДобавьте их через редактирование профиля.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ К профилю", callback_data="worker_profile")
            ]])
        )
        return

    photo_ids = [p.strip() for p in portfolio_photos.split(",") if p.strip()]

    # НОВОЕ: Проверяем какие фото подтверждены клиентами (из completed_work_photos)
    worker_id = profile_dict.get("id")
    verified_photos_info = {}  # photo_id -> True если подтверждено

    if worker_id:
        # Получаем все подтвержденные фото блогера из completed_work_photos
        verified_photos = db.get_worker_verified_photos(worker_id, limit=100)
        for photo_row in verified_photos:
            photo_dict = dict(photo_row)
            photo_file_id = photo_dict.get('photo_id')
            if photo_file_id:
                verified_photos_info[photo_file_id] = True

    # Сохраняем в context для навигации
    context.user_data['portfolio_photos'] = photo_ids
    context.user_data['verified_photos'] = verified_photos_info
    context.user_data['current_portfolio_index'] = 0

    # Показываем первое фото
    keyboard = []

    # Навигация если фото больше одного
    if len(photo_ids) > 1:
        nav_buttons = [
            InlineKeyboardButton("◀️", callback_data="portfolio_prev"),
            InlineKeyboardButton(f"1/{len(photo_ids)}", callback_data="noop"),
            InlineKeyboardButton("▶️", callback_data="portfolio_next")
        ]
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ К профилю", callback_data="worker_profile")])

    # НОВОЕ: Добавляем галочку если фото подтверждено клиентом
    first_photo_id = photo_ids[0]
    is_verified = verified_photos_info.get(first_photo_id, False)
    verified_mark = " ✅ <i>Подтверждено клиентом</i>" if is_verified else ""

    try:
        await query.message.delete()
        await query.message.reply_photo(
            photo=photo_ids[0],
            caption=f"📸 <b>Фото контент</b>\n\n1 из {len(photo_ids)}{verified_mark}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Ошибка при показе галереи: {e}")
        await query.edit_message_text("❌ Ошибка при загрузке фото")


async def portfolio_navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по галерее контент"""
    query = update.callback_query
    await query.answer()

    photo_ids = context.user_data.get('portfolio_photos', [])
    current_index = context.user_data.get('current_portfolio_index', 0)
    verified_photos = context.user_data.get('verified_photos', {})  # НОВОЕ

    if not photo_ids:
        return

    # Определяем направление
    if "prev" in query.data:
        current_index = (current_index - 1) % len(photo_ids)
    elif "next" in query.data:
        current_index = (current_index + 1) % len(photo_ids)

    context.user_data['current_portfolio_index'] = current_index

    # НОВОЕ: Проверяем подтверждено ли текущее фото
    current_photo_id = photo_ids[current_index]
    is_verified = verified_photos.get(current_photo_id, False)
    verified_mark = "\n✅ <i>Подтверждено клиентом</i>" if is_verified else ""

    # Формируем keyboard
    keyboard = []
    if len(photo_ids) > 1:
        nav_buttons = [
            InlineKeyboardButton("◀️", callback_data="portfolio_prev"),
            InlineKeyboardButton(f"{current_index + 1}/{len(photo_ids)}", callback_data="noop"),
            InlineKeyboardButton("▶️", callback_data="portfolio_next")
        ]
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ К профилю", callback_data="worker_profile")])

    try:
        await query.message.edit_media(
            media=query.message.photo[-1].file_id,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except:
        # Если edit_media не работает, удаляем и отправляем заново
        try:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.from_user.id,
                photo=photo_ids[current_index],
                caption=f"📸 <b>Фото контент</b>\n\n{current_index + 1} из {len(photo_ids)}{verified_mark}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Ошибка навигации по галерее: {e}")


# ------- ЗАГРУЗКА ФОТО ПРОФИЛЯ -------

async def edit_profile_photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало загрузки/изменения фото профиля"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_photo = profile_dict.get("profile_photo")

    # Устанавливаем флаг загрузки фото профиля
    context.user_data['uploading_profile_photo'] = True
    context.user_data['user_id'] = user_id
    logger.info(f"📱 DEBUG: Флаг uploading_profile_photo установлен для user_id={user_id}, telegram_id={telegram_id}")

    if current_photo:
        # Показываем текущее фото
        await query.message.delete()
        await query.message.reply_photo(
            photo=current_photo,
            caption=(
                "👤 <b>Текущее фото профиля</b>\n\n"
                "📸 <b>Как изменить фото:</b>\n"
                "Просто отправьте новое фото сюда в чат, и оно автоматически заменит текущее.\n\n"
                "💡 <i>Рекомендуем использовать фото вашего лица - это повышает доверие клиентов!</i>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к профилю", callback_data="worker_profile")
            ]])
        )
    else:
        await query.edit_message_text(
            "👤 <b>Добавить фото профиля</b>\n\n"
            "У вас пока нет фото профиля.\n\n"
            "📸 <b>Как добавить фото:</b>\n"
            "Просто отправьте фото сюда в чат, и оно автоматически установится как фото вашего профиля.\n\n"
            "💡 <i>Рекомендуем использовать фото вашего лица - это повышает доверие клиентов и увеличивает количество откликов!</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к профилю", callback_data="worker_profile")
            ]])
        )


async def upload_profile_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загружаемого фото профиля"""

    telegram_id = update.effective_user.id
    logger.info(f"📱 DEBUG: upload_profile_photo вызван для telegram_id={telegram_id}")

    # Этот handler вызывается только если флаг установлен (проверка в worker_add_photos_upload)
    # Двойная проверка не нужна

    file_id = None

    # Обработка фото (сжатое изображение)
    if update.message and update.message.photo:
        logger.info("📱 DEBUG: Получено фото профиля (photo)")
        photo = update.message.photo[-1]  # Берём самое большое разрешение
        file_id = photo.file_id

    # Обработка документа (файл без сжатия)
    elif update.message and update.message.document:
        document = update.message.document
        # Проверяем, что это изображение
        if document.mime_type and document.mime_type.startswith('image/'):
            logger.info("Получено фото профиля (document)")
            file_id = document.file_id
        else:
            await update.message.reply_text(
                "❌ Можно отправлять только изображения (JPG, PNG и т.д.).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data="cancel_profile_photo")
                ]])
            )
            return

    if not file_id:
        logger.warning("Не удалось получить file_id из сообщения")
        return

    # КРИТИЧНО: Валидация file_id
    if not validate_file_id(file_id):
        logger.error(f"❌ Невалидный file_id при загрузке фото профиля: {file_id}")
        await update.message.reply_text(
            "❌ Ошибка при обработке фото.\n\n"
            "Попробуйте отправить фото еще раз или используйте другое изображение.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_profile_photo")
            ]])
        )
        return

    # Сохраняем фото профиля в БД
    user_id = context.user_data.get('user_id')

    if user_id:
        try:
            db.update_worker_field(user_id, "profile_photo", file_id)
            logger.info(f"Фото профиля сохранено для user_id={user_id}")

            await update.message.reply_text(
                "✅ <b>Фото профиля успешно обновлено!</b>\n\n"
                "Теперь это фото будет показываться в вашем профиле.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👤 Посмотреть профиль", callback_data="worker_profile")],
                    [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
                ])
            )

            # Очищаем флаг
            context.user_data.clear()

        except Exception as e:
            logger.error(f"Ошибка при сохранении фото профиля: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при сохранении фото: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")
                ]])
            )
            context.user_data.clear()


async def cancel_profile_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена загрузки фото профиля"""
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "❌ Загрузка фото профиля отменена.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ К профилю", callback_data="worker_profile")
        ]])
    )


# ------- УПРАВЛЕНИЕ ФОТО ПОРТФОЛИО -------

async def manage_portfolio_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает фото портфолио с возможностью удаления"""
    query = update.callback_query
    await query.answer()

    # Получаем профиль блогера
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    user_dict = dict(user)
    user_id = user_dict.get("id")

    worker_profile = db.get_worker_profile(user_id)
    if not worker_profile:
        await query.edit_message_text("❌ Профиль блогера не найден.")
        return

    profile_dict = dict(worker_profile)
    portfolio_photos = profile_dict.get("portfolio_photos", "")

    if not portfolio_photos:
        await query.edit_message_text(
            "📸 <b>Управление фото контент</b>\n\n"
            "У вас пока нет фото контент в портфолио.\n\n"
            "Добавьте фото через меню редактирования профиля.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к редактированию", callback_data="edit_profile_menu")
            ]])
        )
        return

    # Парсим фото и видео
    photos_list = [p.strip() for p in portfolio_photos.split(',') if p.strip()]

    if not photos_list:
        await query.edit_message_text(
            "📸 <b>Управление фото контент</b>\n\n"
            "У вас пока нет фото контент в портфолио.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к редактированию", callback_data="edit_profile_menu")
            ]])
        )
        return

    # Сохраняем список фото в контекст и начинаем с первого
    context.user_data['portfolio_photos'] = photos_list
    context.user_data['current_photo_index'] = 0

    # Показываем первое фото
    await show_portfolio_photo(query, context, 0)


async def show_portfolio_photo(query, context, index):
    """Показывает конкретное фото из портфолио с кнопками навигации и удаления"""
    photos_list = context.user_data.get('portfolio_photos', [])

    if index >= len(photos_list):
        index = 0

    photo_id = photos_list[index]
    is_video = photo_id.startswith("VIDEO:")

    # Формируем кнопки
    keyboard = []

    # Кнопки навигации
    nav_buttons = []
    if index > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Предыдущее", callback_data=f"portfolio_prev_{index}"))
    if index < len(photos_list) - 1:
        nav_buttons.append(InlineKeyboardButton("Следующее ➡️", callback_data=f"portfolio_next_{index}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # Кнопка удаления
    keyboard.append([InlineKeyboardButton("🗑 Удалить это фото", callback_data=f"delete_portfolio_photo_{index}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад к профилю", callback_data="worker_profile")])

    caption = (
        f"📸 <b>Фото {index + 1} из {len(photos_list)}</b>\n\n"
        f"{'🎥 Видео' if is_video else '📷 Фото'}\n\n"
        f"Нажмите кнопку ниже чтобы удалить это фото."
    )

    # Удаляем предыдущее сообщение
    try:
        await query.message.delete()
    except Exception:
        pass

    # Отправляем фото/видео
    try:
        if is_video:
            clean_video_id = photo_id.replace("VIDEO:", "")
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=clean_video_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=photo_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке фото портфолио: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Ошибка при отображении фото #{index + 1}\n\n"
                 f"Возможно файл был удален из Telegram.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def portfolio_photo_navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по фото портфолио"""
    query = update.callback_query
    await query.answer()

    # Парсим направление и текущий индекс из callback_data
    data = query.data
    if data.startswith("portfolio_prev_"):
        current_index = int(data.split("_")[-1])
        new_index = current_index - 1
    elif data.startswith("portfolio_next_"):
        current_index = int(data.split("_")[-1])
        new_index = current_index + 1
    else:
        return

    context.user_data['current_photo_index'] = new_index
    await show_portfolio_photo(query, context, new_index)


async def delete_portfolio_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет фото из портфолио"""
    query = update.callback_query
    await query.answer()

    # Парсим индекс из callback_data
    index = int(query.data.split("_")[-1])

    # Получаем профиль блогера
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    user_dict = dict(user)
    user_id = user_dict.get("id")

    # Удаляем фото
    photos_list = context.user_data.get('portfolio_photos', [])
    if index >= len(photos_list):
        await query.answer("❌ Фото не найдено", show_alert=True)
        return

    deleted_photo = photos_list.pop(index)

    # Обновляем в БД
    new_portfolio = ",".join(photos_list)
    db.update_worker_field(user_id, "portfolio_photos", new_portfolio)

    logger.info(f"Удалено фото из портфолио блогера {user_id}: индекс {index}")

    # Если остались фото - показываем следующее или предыдущее
    if photos_list:
        context.user_data['portfolio_photos'] = photos_list

        # Если удалили последнее - показываем предпоследнее
        new_index = min(index, len(photos_list) - 1)
        context.user_data['current_photo_index'] = new_index

        await query.answer("✅ Фото удалено", show_alert=True)
        await show_portfolio_photo(query, context, new_index)
    else:
        # Фото больше нет - возвращаемся в меню
        context.user_data.clear()

        try:
            await query.message.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="✅ <b>Фото удалено</b>\n\n"
                 "Все фото из портфолио удалены.\n"
                 "Вы можете добавить новые фото через меню редактирования профиля.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ К профилю", callback_data="worker_profile")
            ]])
        )


async def view_blogger_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр галереи контент другого блогера (для клиента)"""
    query = update.callback_query
    await query.answer()

    # Извлекаем worker_id из callback_data
    try:
        worker_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await safe_edit_message(query, "❌ Ошибка: неверный формат данных")
        return

    # Получаем профиль блогера
    worker_profile = db.get_worker_profile_by_id(worker_id)

    if not worker_profile:
        await safe_edit_message(query, "❌ Профиль блогера не найден")
        return

    profile_dict = dict(worker_profile)
    portfolio_photos = profile_dict.get("portfolio_photos") or ""

    if not portfolio_photos:
        await safe_edit_message(
            query,
            "📸 У этого блогера пока нет фото контент.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="back_to_offer_card")
            ]])
        )
        return

    photo_ids = [p.strip() for p in portfolio_photos.split(",") if p.strip()]

    # Сохраняем в context для навигации
    context.user_data['viewing_worker_portfolio'] = photo_ids
    context.user_data['viewing_worker_portfolio_index'] = 0
    context.user_data['viewing_worker_id'] = worker_id

    # Показываем первое фото
    keyboard = []

    # Навигация если фото больше одного
    if len(photo_ids) > 1:
        nav_buttons = [
            InlineKeyboardButton("◀️", callback_data="blogger_portfolio_view_prev"),
            InlineKeyboardButton(f"1/{len(photo_ids)}", callback_data="noop"),
            InlineKeyboardButton("▶️", callback_data="blogger_portfolio_view_next")
        ]
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_offer_card")])

    try:
        await query.message.delete()
        await query.message.reply_photo(
            photo=photo_ids[0],
            caption=f"📸 <b>Контенты блогера</b>\n\n1 из {len(photo_ids)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Ошибка при показе галереи блогера: {e}")
        await safe_edit_message(query, "❌ Ошибка при загрузке фото")


async def blogger_portfolio_view_navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по галерее контент другого блогера"""
    query = update.callback_query
    await query.answer()

    photos = context.user_data.get('viewing_worker_portfolio', [])
    current_index = context.user_data.get('viewing_worker_portfolio_index', 0)

    if not photos:
        await query.message.delete()
        await query.message.reply_text("❌ Ошибка: фотографии не найдены")
        return

    # Определяем направление
    if query.data == "blogger_portfolio_view_next":
        current_index = (current_index + 1) % len(photos)
    elif query.data == "blogger_portfolio_view_prev":
        current_index = (current_index - 1) % len(photos)

    context.user_data['viewing_worker_portfolio_index'] = current_index

    # Обновляем фото
    keyboard = []

    if len(photos) > 1:
        nav_buttons = [
            InlineKeyboardButton("◀️", callback_data="blogger_portfolio_view_prev"),
            InlineKeyboardButton(f"{current_index + 1}/{len(photos)}", callback_data="noop"),
            InlineKeyboardButton("▶️", callback_data="blogger_portfolio_view_next")
        ]
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_offer_card")])

    try:
        await query.message.delete()
        await query.message.reply_photo(
            photo=photos[current_index],
            caption=f"📸 <b>Контенты блогера</b>\n\n{current_index + 1} из {len(photos)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Ошибка при навигации по галерее: {e}")


# ------- РЕДАКТИРОВАНИЕ ПРОФИЛЯ -------

async def show_edit_profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню редактирования профиля"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("👤 Изменить фото профиля", callback_data="edit_profile_photo")],
        [InlineKeyboardButton("✏️ Изменить имя", callback_data="edit_name")],
        [InlineKeyboardButton("🏙 Изменить город", callback_data="edit_city")],
        [InlineKeyboardButton("📱 Изменить виды контент", callback_data="edit_categories")],
        [InlineKeyboardButton("🌐 Социальные сети", callback_data="edit_social_media")],
        [InlineKeyboardButton("📊 Подписчики", callback_data="edit_followers")],
        [InlineKeyboardButton("📝 Изменить описание", callback_data="edit_description")],
        [InlineKeyboardButton("📊 Уровень опыта", callback_data="edit_experience")],
        [InlineKeyboardButton("⬅️ Назад к профилю", callback_data="worker_profile")],
    ]

    # ИСПРАВЛЕНИЕ: Если предыдущее сообщение с фото, нельзя использовать edit_message_text
    # Удаляем старое и отправляем новое
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="✏️ <b>Редактирование профиля</b>\n\n"
             "Выберите что хотите изменить:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return EDIT_PROFILE_MENU


async def edit_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования имени"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_name = profile_dict.get("name") or "—"
    
    await query.edit_message_text(
        f"✏️ <b>Изменение имени</b>\n\n"
        f"Текущее имя: <b>{current_name}</b>\n\n"
        f"Введите новое имя:\n"
        f"Например: «Александр», «Иван Петров»\n\n"
        f"Или отправьте /cancel для отмены",
        parse_mode="HTML",
    )
    return EDIT_NAME


async def edit_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение нового имени"""
    new_name = update.message.text.strip()
    
    if not is_valid_name(new_name):
        await update.message.reply_text(
            "❌ Неверный формат имени.\n"
            "Укажите только имя или имя и фамилию, без ссылок.\n\n"
            "Попробуйте ещё раз или /cancel для отмены"
        )
        return EDIT_NAME
    
    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    db.update_worker_field(user_id, "name", new_name)
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await update.message.reply_text(
        f"✅ Имя успешно изменено на: <b>{new_name}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def edit_phone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования телефона"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_phone = profile_dict.get("phone") or "—"
    
    await query.edit_message_text(
        f"📱 <b>Изменение телефона</b>\n\n"
        f"Текущий телефон: <b>{current_phone}</b>\n\n"
        f"Введите новый номер телефона:\n"
        f"Пример: +375 29 123 45 67\n\n"
        f"Или отправьте /cancel для отмены",
        parse_mode="HTML",
    )
    return EDIT_PHONE


async def edit_phone_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение нового телефона"""
    new_phone = update.message.text.strip()
    
    if not is_valid_phone(new_phone):
        await update.message.reply_text(
            "❌ Неверный формат телефона.\n"
            "Пример: +375 29 123 45 67\n\n"
            "Попробуйте ещё раз или /cancel для отмены"
        )
        return EDIT_PHONE
    
    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    db.update_worker_field(user_id, "phone", new_phone)
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await update.message.reply_text(
        f"✅ Телефон успешно изменён на: <b>{new_phone}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def edit_city_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ИСПРАВЛЕНО: Редактирование городов - теперь поддерживает НЕСКОЛЬКО городов"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    worker_id = profile_dict['id']

    # Получаем ВСЕ города блогера из worker_cities
    worker_cities = db.get_worker_cities(worker_id)

    # Если городов нет в worker_cities, берём из старого поля city
    if not worker_cities:
        current_city = profile_dict.get("city")
        if current_city:
            worker_cities = [current_city]
            # Мигрируем в worker_cities
            db.add_worker_city(worker_id, current_city)

    # Сохраняем worker_id в context для последующих шагов
    context.user_data["edit_worker_id"] = worker_id
    context.user_data["current_cities"] = worker_cities

    # Формируем текст с текущими городами
    if worker_cities:
        cities_text = "\n".join([f"  • {city}" for city in worker_cities])
    else:
        cities_text = "  (не указаны)"

    # Показываем регионы Беларуси для ДОБАВЛЕНИЯ нового города
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"editregion_{region_name}"
        )])

    # Кнопки управления городами
    if worker_cities:
        keyboard.append([InlineKeyboardButton("🗑 Удалить город", callback_data="remove_city_menu")])

    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="worker_profile")])

    await query.edit_message_text(
        f"🏙 <b>Редактирование городов</b>\n\n"
        f"📍 <b>Ваши города:</b>\n{cities_text}\n\n"
        f"➕ Выберите регион чтобы ДОБАВИТЬ новый город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return EDIT_REGION_SELECT




async def edit_region_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ИСПРАВЛЕНО: ДОБАВЛЕНИЕ города (не замена)"""
    query = update.callback_query
    await query.answer()

    region = query.data.replace("editregion_", "")
    region_data = BELARUS_REGIONS.get(region)

    if not region_data:
        await query.edit_message_text("❌ Ошибка выбора региона. Попробуйте снова.")
        return EDIT_REGION_SELECT

    context.user_data["edit_region"] = region

    # Если выбран Минск или "Вся Беларусь" - сразу добавляем
    if region_data["type"] in ["city", "country"]:
        telegram_id = query.from_user.id
        user = db.get_user(telegram_id)
        user_dict = dict(user)
        user_id = user_dict.get("id")

        # ИСПРАВЛЕНО: ДОБАВЛЯЕМ город в worker_cities
        worker_id = context.user_data.get("edit_worker_id")
        if worker_id:
            db.add_worker_city(worker_id, region)

        # Также обновляем старое поле city для обратной совместимости
        db.update_worker_field(user_id, "city", region)
        db.update_worker_field(user_id, "regions", region)

        # Показываем обновлённый список городов
        worker_cities = db.get_worker_cities(worker_id) if worker_id else [region]
        cities_text = "\n".join([f"  • {c}" for c in worker_cities])

        keyboard = [
            [InlineKeyboardButton("➕ Добавить ещё город", callback_data="edit_city")],
            [InlineKeyboardButton("✅ Готово", callback_data="worker_profile")]
        ]

        await query.edit_message_text(
            f"✅ Город <b>{region_data['display']}</b> добавлен!\n\n"
            f"📍 <b>Ваши города:</b>\n{cities_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        return EDIT_PROFILE_MENU

    # Если выбрана область - показываем города
    else:
        cities = region_data.get("cities", [])
        keyboard = []
        row = []
        for city in cities:
            row.append(InlineKeyboardButton(city, callback_data=f"editcity_{city}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # Добавляем кнопку "Другой город в области"
        # ЛОГИКА "ДРУГОЙ ГОРОД":
        # - При редактировании блогер может добавить любой город
        # - Это полезно для небольших городов и посёлков
        keyboard.append([InlineKeyboardButton(
            f"📍 Другой город в области",
            callback_data="editcity_other"
        )])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")])

        await query.edit_message_text(
            f"📍 Область: {region_data['display']}\n\n"
            "🏙 Выберите город:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return EDIT_CITY


async def edit_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ИСПРАВЛЕНО: ДОБАВЛЕНИЕ города (не замена)"""
    query = update.callback_query
    await query.answer()

    city = query.data.replace("editcity_", "")

    if city == "other":
        await query.edit_message_text(
            "🏙 Напишите название города:"
        )
        return EDIT_CITY
    else:
        # ИСПРАВЛЕНО: ДОБАВЛЯЕМ город в worker_cities
        worker_id = context.user_data.get("edit_worker_id")
        if not worker_id:
            await query.edit_message_text("❌ Ошибка: не найден worker_id")
            return ConversationHandler.END

        # Добавляем город
        db.add_worker_city(worker_id, city)

        # Также обновляем старое поле city для обратной совместимости
        telegram_id = query.from_user.id
        user = db.get_user(telegram_id)
        user_dict = dict(user)
        user_id = user_dict.get("id")
        region = context.user_data.get("edit_region", city)
        db.update_worker_field(user_id, "city", city)
        db.update_worker_field(user_id, "regions", region)

        # Показываем обновлённый список городов
        worker_cities = db.get_worker_cities(worker_id)
        cities_text = "\n".join([f"  • {c}" for c in worker_cities])

        keyboard = [
            [InlineKeyboardButton("➕ Добавить ещё город", callback_data="edit_city")],
            [InlineKeyboardButton("✅ Готово", callback_data="worker_profile")]
        ]

        await query.edit_message_text(
            f"✅ Город <b>{city}</b> добавлен!\n\n"
            f"📍 <b>Ваши города:</b>\n{cities_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        return EDIT_PROFILE_MENU



async def edit_city_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ИСПРАВЛЕНО: ДОБАВЛЕНИЕ нового города (не замена)"""
    new_city = update.message.text.strip()

    if len(new_city) < 2:
        await update.message.reply_text(
            "❌ Слишком короткое название города.\n\n"
            "Попробуйте ещё раз или /cancel для отмены"
        )
        return EDIT_CITY

    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    # ИСПРАВЛЕНО: ДОБАВЛЯЕМ город в worker_cities
    worker_id = context.user_data.get("edit_worker_id")
    if worker_id:
        db.add_worker_city(worker_id, new_city)

    # Также обновляем старое поле city для обратной совместимости
    db.update_worker_field(user_id, "city", new_city)
    db.update_worker_field(user_id, "regions", new_city)

    # Показываем обновлённый список городов
    worker_cities = db.get_worker_cities(worker_id) if worker_id else [new_city]
    cities_text = "\n".join([f"  • {c}" for c in worker_cities])

    keyboard = [
        [InlineKeyboardButton("➕ Добавить ещё город", callback_data="edit_city")],
        [InlineKeyboardButton("✅ Готово", callback_data="worker_profile")]
    ]

    await update.message.reply_text(
        f"✅ Город <b>{new_city}</b> добавлен!\n\n"
        f"📍 <b>Ваши города:</b>\n{cities_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return EDIT_PROFILE_MENU


async def remove_city_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню удаления города"""
    query = update.callback_query
    await query.answer()

    worker_id = context.user_data.get("edit_worker_id")
    if not worker_id:
        await query.edit_message_text("❌ Ошибка: не найден worker_id")
        return ConversationHandler.END

    # Получаем все города блогера
    worker_cities = db.get_worker_cities(worker_id)

    if not worker_cities:
        await query.edit_message_text(
            "❌ У вас нет городов для удаления.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="edit_city")
            ]])
        )
        return ConversationHandler.END

    # Создаём кнопки для каждого города
    keyboard = []
    for city in worker_cities:
        keyboard.append([InlineKeyboardButton(
            f"🗑 Удалить {city}",
            callback_data=f"remove_city_{city}"
        )])

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="edit_city")])

    await query.edit_message_text(
        "🗑 <b>Удаление города</b>\n\n"
        "Выберите город для удаления:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END


async def remove_city_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет выбранный город"""
    query = update.callback_query
    await query.answer()

    city_to_remove = query.data.replace("remove_city_", "")
    worker_id = context.user_data.get("edit_worker_id")

    if not worker_id:
        await query.edit_message_text("❌ Ошибка: не найден worker_id")
        return ConversationHandler.END

    # Удаляем город
    db.remove_worker_city(worker_id, city_to_remove)

    # Показываем обновлённый список
    worker_cities = db.get_worker_cities(worker_id)
    if worker_cities:
        cities_text = "\n".join([f"  • {c}" for c in worker_cities])
    else:
        cities_text = "  (не указаны)"

    keyboard = [
        [InlineKeyboardButton("➕ Добавить город", callback_data="edit_city")],
        [InlineKeyboardButton("✅ Готово", callback_data="worker_profile")]
    ]

    await query.edit_message_text(
        f"✅ Город <b>{city_to_remove}</b> удалён!\n\n"
        f"📍 <b>Ваши города:</b>\n{cities_text}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END


async def edit_categories_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования категорий"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_categories_str = profile_dict.get("categories") or ""

    # Парсим текущие категории
    if current_categories_str:
        current_categories = [cat.strip() for cat in current_categories_str.split(",")]
    else:
        current_categories = []

    context.user_data["edit_categories"] = current_categories.copy()

    # Показываем все категории с галочками (2 в ряд)
    keyboard = []
    row = []
    for idx, category in enumerate(BLOGGER_CATEGORIES):
        is_selected = category in context.user_data["edit_categories"]
        button_text = f"☑️ {category}" if is_selected else category

        row.append(InlineKeyboardButton(button_text, callback_data=f"editcat_{idx}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("✅ Сохранить изменения", callback_data="editcat_done")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")])

    current_text = ", ".join(current_categories) if current_categories else "не выбраны"

    await query.edit_message_text(
        f"📱 <b>Изменение категорий контента</b>\n\n"
        f"Текущие категории: <b>{current_text}</b>\n\n"
        "Выберите категории (можно несколько):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return EDIT_CATEGORIES_SELECT


async def edit_categories_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора категорий при редактировании"""
    query = update.callback_query
    data = query.data
    selected = data.replace("editcat_", "")

    if selected == "done":
        # Проверяем что выбрана хотя бы одна категория
        if not context.user_data.get("edit_categories"):
            await query.answer("Выберите хотя бы одну категорию!", show_alert=True)
            return EDIT_CATEGORIES_SELECT

        await query.answer()

        # Сохраняем изменения
        telegram_id = query.from_user.id
        user = db.get_user(telegram_id)
        user_dict = dict(user)
        user_id = user_dict.get("id")

        new_categories = ", ".join(context.user_data["edit_categories"])
        db.update_worker_field(user_id, "categories", new_categories)

        await query.edit_message_text(
            f"✅ Категории успешно обновлены!\n\n"
            f"Новые категории: <b>{new_categories}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к профилю", callback_data="worker_profile")
            ]])
        )
        return ConversationHandler.END

    else:
        # Переключаем выбор категории
        idx = int(selected)
        category = BLOGGER_CATEGORIES[idx]

        if "edit_categories" not in context.user_data:
            context.user_data["edit_categories"] = []

        if category not in context.user_data["edit_categories"]:
            context.user_data["edit_categories"].append(category)
            await query.answer(f"✅ Добавлено")
        else:
            context.user_data["edit_categories"].remove(category)
            await query.answer(f"❌ Убрано")

        # Обновляем кнопки с галочками
        keyboard = []
        row = []
        for idx2, cat in enumerate(BLOGGER_CATEGORIES):
            is_selected = cat in context.user_data["edit_categories"]
            button_text = f"☑️ {cat}" if is_selected else cat

            row.append(InlineKeyboardButton(button_text, callback_data=f"editcat_{idx2}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("✅ Сохранить изменения", callback_data="editcat_done")])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")])

        current_text = ", ".join(context.user_data["edit_categories"]) if context.user_data["edit_categories"] else "не выбраны"

        await query.edit_message_text(
            f"📱 <b>Изменение категорий контента</b>\n\n"
            f"Выбрано: <b>{current_text}</b>\n\n"
            "Выберите категории (можно несколько):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

        return EDIT_CATEGORIES_SELECT


async def edit_experience_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования опыта"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_exp = profile_dict.get("experience") or "—"
    
    keyboard = [
        [InlineKeyboardButton("🌱 Начинающий блогер", callback_data="editexp_Начинающий блогер")],
        [InlineKeyboardButton("⚡ Опытный блогер", callback_data="editexp_Опытный блогер")],
        [InlineKeyboardButton("⭐ Профессионал", callback_data="editexp_Профессионал")],
        [InlineKeyboardButton("❌ Отмена", callback_data="worker_profile")],
    ]

    await query.edit_message_text(
        f"📊 <b>Изменение уровня опыта</b>\n\n"
        f"Текущий уровень: <b>{current_exp}</b>\n\n"
        f"Выберите новый уровень:\n\n"
        "🌱 <b>Начинающий блогер</b> — осваиваете профессию\n"
        "⚡ <b>Опытный блогер</b> — есть портфолио проектов\n"
        "⭐ <b>Профессионал</b> — высокий уровень, сложные проекты",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return EDIT_EXPERIENCE


async def edit_experience_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение нового опыта"""
    query = update.callback_query
    await query.answer()
    
    new_exp = query.data.replace("editexp_", "")
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    db.update_worker_field(user_id, "experience", new_exp)
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await query.edit_message_text(
        f"✅ Опыт создания контента успешно изменён на: <b>{new_exp}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def edit_description_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования описания"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)
    current_desc = profile_dict.get("description") or "—"
    
    await query.edit_message_text(
        f"📝 <b>Изменение описания</b>\n\n"
        f"Текущее описание:\n<i>{current_desc}</i>\n\n"
        f"Введите новое описание профиля:\n"
        f"Расскажите о своём опыте, специализации, как работаете.\n\n"
        f"Или отправьте /cancel для отмены",
        parse_mode="HTML",
    )
    return EDIT_DESCRIPTION


async def edit_description_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение нового описания"""
    new_desc = update.message.text.strip()
    
    if len(new_desc) < 10:
        await update.message.reply_text(
            "❌ Описание слишком короткое (минимум 10 символов).\n\n"
            "Попробуйте ещё раз или /cancel для отмены"
        )
        return EDIT_DESCRIPTION
    
    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")
    
    db.update_worker_field(user_id, "description", new_desc)
    
    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]
    
    await update.message.reply_text(
        f"✅ Описание успешно изменено!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def edit_social_media_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню редактирования социальных сетей"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)

    instagram = profile_dict.get("instagram_link") or "Не указан"
    youtube = profile_dict.get("youtube_link") or "Не указан"
    tiktok = profile_dict.get("tiktok_link") or "Не указан"
    telegram_link = profile_dict.get("telegram_link") or "Не указан"
    threads = profile_dict.get("threads_link") or "Не указан"

    keyboard = [
        [InlineKeyboardButton(f"📸 Instagram: {instagram[:20]}...", callback_data="edit_sm_instagram")],
        [InlineKeyboardButton(f"📺 YouTube: {youtube[:20]}...", callback_data="edit_sm_youtube")],
        [InlineKeyboardButton(f"🎵 TikTok: {tiktok[:20]}...", callback_data="edit_sm_tiktok")],
        [InlineKeyboardButton(f"✈️ Telegram: {telegram_link[:20]}...", callback_data="edit_sm_telegram")],
        [InlineKeyboardButton(f"🧵 Threads: {threads[:20]}...", callback_data="edit_sm_threads")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="edit_profile_menu")],
    ]

    await query.edit_message_text(
        "🌐 <b>Социальные сети</b>\n\n"
        "Выберите платформу для редактирования:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return EDIT_SOCIAL_MEDIA


async def edit_social_media_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора платформы для редактирования"""
    query = update.callback_query
    await query.answer()

    platform_map = {
        "edit_sm_instagram": ("instagram_link", "Instagram", "📸"),
        "edit_sm_youtube": ("youtube_link", "YouTube", "📺"),
        "edit_sm_tiktok": ("tiktok_link", "TikTok", "🎵"),
        "edit_sm_telegram": ("telegram_link", "Telegram", "✈️"),
        "edit_sm_threads": ("threads_link", "Threads", "🧵"),
    }

    if query.data not in platform_map:
        return EDIT_SOCIAL_MEDIA

    field_name, platform_name, emoji = platform_map[query.data]
    context.user_data["editing_social_platform"] = field_name

    await query.edit_message_text(
        f"{emoji} <b>Редактирование {platform_name}</b>\n\n"
        f"Введите ссылку на ваш профиль в {platform_name}:\n"
        f"Например: https://instagram.com/username\n\n"
        f"Или отправьте /cancel для отмены",
        parse_mode="HTML",
    )
    return EDIT_SOCIAL_MEDIA_INPUT


async def edit_social_media_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение ссылки на социальную сеть"""
    new_link = update.message.text.strip()

    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    field_name = context.user_data.get("editing_social_platform")
    if not field_name:
        await update.message.reply_text("❌ Ошибка: не выбрана платформа")
        return ConversationHandler.END

    # Сохраняем ссылку
    db.update_worker_field(user_id, field_name, new_link)

    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]

    await update.message.reply_text(
        f"✅ Ссылка успешно сохранена!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


def format_followers_count(count: int) -> str:
    """Форматирует количество подписчиков для отображения"""
    if count == 0:
        return "Не указано"
    elif count >= 1000000:
        return f"{count / 1000000:.1f}M"
    elif count >= 1000:
        return f"{count / 1000:.1f}K"
    else:
        return str(count)


async def edit_followers_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню редактирования количества подписчиков"""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    worker_profile = db.get_worker_profile(user_id)
    profile_dict = dict(worker_profile)

    instagram_followers = profile_dict.get("instagram_followers") or 0
    tiktok_followers = profile_dict.get("tiktok_followers") or 0
    youtube_followers = profile_dict.get("youtube_followers") or 0
    telegram_followers = profile_dict.get("telegram_followers") or 0

    keyboard = [
        [InlineKeyboardButton(f"📸 Instagram: {format_followers_count(instagram_followers)}", callback_data="edit_fl_instagram")],
        [InlineKeyboardButton(f"🎵 TikTok: {format_followers_count(tiktok_followers)}", callback_data="edit_fl_tiktok")],
        [InlineKeyboardButton(f"📺 YouTube: {format_followers_count(youtube_followers)}", callback_data="edit_fl_youtube")],
        [InlineKeyboardButton(f"✈️ Telegram: {format_followers_count(telegram_followers)}", callback_data="edit_fl_telegram")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="edit_profile_menu")],
    ]

    await query.edit_message_text(
        "📊 <b>Подписчики</b>\n\n"
        "Укажите количество подписчиков по каждой социальной сети.\n"
        "Это поможет рекламодателям оценить ваш охват.\n\n"
        "Выберите платформу для редактирования:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return EDIT_FOLLOWERS


async def edit_followers_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора платформы для редактирования подписчиков"""
    query = update.callback_query
    await query.answer()

    platform_map = {
        "edit_fl_instagram": ("instagram_followers", "Instagram", "📸"),
        "edit_fl_tiktok": ("tiktok_followers", "TikTok", "🎵"),
        "edit_fl_youtube": ("youtube_followers", "YouTube", "📺"),
        "edit_fl_telegram": ("telegram_followers", "Telegram", "✈️"),
    }

    if query.data not in platform_map:
        return EDIT_FOLLOWERS

    field_name, platform_name, emoji = platform_map[query.data]
    context.user_data["editing_followers_platform"] = field_name
    context.user_data["editing_followers_platform_name"] = platform_name

    await query.edit_message_text(
        f"{emoji} <b>Подписчики в {platform_name}</b>\n\n"
        f"Введите количество подписчиков (только число):\n"
        f"Например: 15000, 1500000\n\n"
        f"Или отправьте /cancel для отмены",
        parse_mode="HTML",
    )
    return EDIT_FOLLOWERS_INPUT


async def edit_followers_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение количества подписчиков"""
    text = update.message.text.strip()

    # Убираем возможные пробелы и разделители тысяч
    text = text.replace(" ", "").replace(",", "").replace(".", "")

    try:
        followers_count = int(text)
        if followers_count < 0:
            raise ValueError("Negative number")
    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число (без букв и символов).\n"
            "Например: 15000\n\n"
            "Попробуйте ещё раз или /cancel для отмены"
        )
        return EDIT_FOLLOWERS_INPUT

    telegram_id = update.effective_user.id
    user = db.get_user(telegram_id)
    user_dict = dict(user)
    user_id = user_dict.get("id")

    field_name = context.user_data.get("editing_followers_platform")
    platform_name = context.user_data.get("editing_followers_platform_name", "")

    if not field_name:
        await update.message.reply_text("❌ Ошибка: не выбрана платформа")
        return ConversationHandler.END

    # Сохраняем количество подписчиков
    db.update_worker_field(user_id, field_name, followers_count)

    keyboard = [[InlineKeyboardButton("📊 К списку подписчиков", callback_data="edit_followers")],
                [InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]

    await update.message.reply_text(
        f"✅ Количество подписчиков в {platform_name} обновлено: <b>{format_followers_count(followers_count)}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ConversationHandler.END


# ------- ЗАГЛУШКИ ДЛЯ ЗАКАЗЧИКА -------

async def advertiser_my_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор категории заказов (активные/завершённые)"""
    query = update.callback_query
    await query.answer()

    try:
        # Получаем профиль клиента
        user = db.get_user(query.from_user.id)
        if not user:
            logger.error(f"User не найден для telegram_id: {query.from_user.id}")
            await safe_edit_message(
                query,
                "❌ Ошибка: пользователь не найден.\n\nНажмите /start для регистрации.",
                parse_mode="HTML"
            )
            return

        # Удаляем уведомление о новых сообщениях (пользователь открыл кампании)
        db.delete_chat_message_notification(user['id'])

        # НОВОЕ: Обнуляем счётчик непрочитанных откликов (пользователь их просматривает)
        db.save_client_notification(user['id'], None, None, 0)

        client_profile = db.get_client_profile(user["id"])
        if not client_profile:
            logger.error(f"Advertiser profile не найден для user_id: {user['id']}")
            await safe_edit_message(
                query,
                "❌ Ошибка: профиль клиента не найден.\n\n"
                "Возможно произошла ошибка при регистрации.\n"
                "Нажмите /start и зарегистрируйтесь заново.",
                parse_mode="HTML"
            )
            return

        # Получаем все кампании для подсчета
        all_orders, total_count, _ = db.get_client_orders(client_profile["id"], page=1, per_page=1000)

        if not all_orders:
            keyboard = [
                [InlineKeyboardButton("📝 Создать первую кампанию", callback_data="client_create_order")],
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")],
            ]

            await safe_edit_message(
                query,
                "📂 <b>Мои кампании</b>\n\n"
                "У вас пока нет созданных рекламных кампаний.\n\n"
                "Создайте первую рекламную кампанию, чтобы начать получать отклики от блогеров!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # Подсчитываем кампании по трем категориям
        # 1. В ожидании блогеров (кампания открыта)
        waiting_statuses = ['open']
        # 2. В работе - кампании с выбранными блогерами
        campaigns_in_progress = db.get_campaigns_with_selected_bloggers(client_profile["id"])
        in_progress_count = len(campaigns_in_progress) if campaigns_in_progress else 0
        # 3. Завершенные
        completed_statuses = ['done', 'completed', 'canceled', 'cancelled']

        waiting_count = sum(1 for o in all_orders if dict(o).get('status', 'open') in waiting_statuses)
        completed_count = sum(1 for o in all_orders if dict(o).get('status', 'open') in completed_statuses)

        # Показываем меню выбора категории
        text = "📂 <b>Мои кампании</b>\n\n"
        text += f"Всего заказов: {total_count}\n"
        text += f"🔍 В ожидании блогеров: {waiting_count}\n"
        text += f"📱 В работе: {in_progress_count}\n"
        text += f"✅ Завершённые: {completed_count}\n\n"
        text += "Выберите категорию:"

        keyboard = [
            [InlineKeyboardButton(f"🔍 В ожидании блогеров ({waiting_count})", callback_data="advertiser_waiting_campaigns")],
            [InlineKeyboardButton(f"📱 В работе ({in_progress_count})", callback_data="advertiser_in_progress_campaigns")],
            [InlineKeyboardButton(f"✅ Завершённые ({completed_count})", callback_data="advertiser_completed_campaigns")],
            [InlineKeyboardButton("📝 Создать новую кампанию", callback_data="client_create_order")],
            [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")]
        ]

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Ошибка в client_my_orders: {e}", exc_info=True)

        keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")]]

        await query.edit_message_text(
            f"❌ Ошибка при загрузке заказов:\n{str(e)}\n\nПопробуйте позже.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def advertiser_waiting_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает кампании в ожидании блогеров (без выбранного блогера)"""
    query = update.callback_query
    await query.answer()

    try:
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        client_profile = db.get_client_profile(user["id"])
        if not client_profile:
            await safe_edit_message(query, "❌ Профиль клиента не найден.")
            return

        # Получаем кампании в ожидании (блогер еще не выбран)
        all_orders, _, _ = db.get_client_orders(client_profile["id"], page=1, per_page=1000)
        waiting_statuses = ['open']
        orders = [o for o in all_orders if dict(o).get('status', 'open') in waiting_statuses]

        if not orders:
            keyboard = [
                [InlineKeyboardButton("📝 Создать новую кампанию", callback_data="client_create_order")],
                [InlineKeyboardButton("⬅️ Назад к заказам", callback_data="client_my_orders")]
            ]
            await safe_edit_message(
                query,
                "🔍 <b>В ожидании блогеров</b>\n\nУ вас нет заказов в ожидании.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Формируем список заказов
        text = f"🔍 <b>В ожидании блогеров</b> ({len(orders)})\n\n"
        keyboard = []

        for campaign in orders[:10]:
            campaign_dict = dict(campaign)
            campaign_id = campaign_dict['id']

            text += f"🟢 <b>Кампания #{campaign_id}</b> - Открыт\n"
            text += f"📱 {campaign_dict.get('category', 'Не указана')}\n"

            # ИСПРАВЛЕНО: Тип оплаты с поддержкой комбинированного варианта
            payment_type = campaign_dict.get('payment_type', 'paid')
            budget_type = campaign_dict.get('budget_type', 'none')
            budget_value = campaign_dict.get('budget_value', 0)

            payment_parts = []
            if payment_type in ['paid', 'both']:
                if budget_value > 0:
                    if budget_type == 'fixed':
                        payment_parts.append(f"💰 {int(budget_value)} BYN")
                    elif budget_type == 'flexible':
                        payment_parts.append(f"💬 до {int(budget_value)} BYN")
                    else:
                        payment_parts.append(f"💰 {int(budget_value)} BYN")
                elif budget_type == 'flexible':
                    payment_parts.append("💬 Блогеры предложат цену")
            if payment_type in ['barter', 'both']:
                payment_parts.append("🤝 Бартер")

            if payment_parts:
                text += f"{' + '.join(payment_parts)}\n"
            else:
                text += f"По договорённости\n"

            description = campaign_dict.get('description', '')
            if len(description) > 50:
                description = description[:50] + "..."
            text += f"📝 {description}\n"

            # Количество откликов
            bids_count = db.get_bids_count_for_order(campaign_id)
            if bids_count > 0:
                text += f"💼 {bids_count} {_get_bids_word(bids_count)}\n"
                keyboard.append([InlineKeyboardButton(
                    f"💼 Отклики на кампанию #{campaign_id}: {bids_count}",
                    callback_data=f"view_offers_{campaign_id}"
                )])

            keyboard.append([InlineKeyboardButton(
                f"❌ Отменить кампанию #{campaign_id}",
                callback_data=f"cancel_campaign_{campaign_id}"
            )])

            text += "\n"

        keyboard.append([InlineKeyboardButton("📝 Создать новую кампанию", callback_data="client_create_order")])
        keyboard.append([InlineKeyboardButton("⬅️ Назад к заказам", callback_data="client_my_orders")])

        await safe_edit_message(query, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Ошибка в client_waiting_orders: {e}", exc_info=True)
        await safe_edit_message(query, f"❌ Ошибка: {str(e)}")


async def advertiser_in_progress_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает кампании в работе (есть выбранные блогеры)"""
    query = update.callback_query
    await query.answer()

    try:
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        client_profile = db.get_client_profile(user["id"])
        if not client_profile:
            await safe_edit_message(query, "❌ Профиль клиента не найден.")
            return

        # Получаем кампании где есть выбранные блогеры
        orders = db.get_campaigns_with_selected_bloggers(client_profile["id"])

        if not orders:
            keyboard = [
                [InlineKeyboardButton("📝 Создать новую кампанию", callback_data="client_create_order")],
                [InlineKeyboardButton("⬅️ Назад к заказам", callback_data="client_my_orders")]
            ]
            await safe_edit_message(
                query,
                "📱 <b>В работе</b>\n\nУ вас нет кампаний с выбранными блогерами.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Формируем список заказов
        text = f"📱 <b>В работе</b> ({len(orders)})\n\n"
        keyboard = []

        for campaign in orders[:10]:
            campaign_dict = dict(campaign)
            campaign_id = campaign_dict['id']

            text += f"📱 <b>Кампания #{campaign_id}</b>\n"
            text += f"📂 {campaign_dict.get('category', 'Не указана')}\n"

            # Тип оплаты
            payment_type = campaign_dict.get('payment_type', 'paid')
            budget_type = campaign_dict.get('budget_type', 'none')
            budget_value = campaign_dict.get('budget_value', 0)

            payment_parts = []
            if payment_type in ['paid', 'both']:
                if budget_value > 0:
                    if budget_type == 'fixed':
                        payment_parts.append(f"💰 {int(budget_value)} BYN")
                    elif budget_type == 'flexible':
                        payment_parts.append(f"💬 до {int(budget_value)} BYN")
                    else:
                        payment_parts.append(f"💰 {int(budget_value)} BYN")
                elif budget_type == 'flexible':
                    payment_parts.append("💬 Блогеры предложат цену")
            if payment_type in ['barter', 'both']:
                payment_parts.append("🤝 Бартер")

            if payment_parts:
                text += f"{' + '.join(payment_parts)}\n"

            # Получаем выбранных блогеров для этой кампании
            selected_bloggers = db.get_selected_bloggers_for_campaign(campaign_id)
            if selected_bloggers:
                text += f"👥 <b>Выбрано блогеров:</b> {len(selected_bloggers)}\n"
                for blogger in selected_bloggers:
                    blogger_dict = dict(blogger)
                    blogger_name = blogger_dict.get('blogger_name', 'Блогер')
                    chat_id = blogger_dict.get('chat_id')
                    text += f"  • {blogger_name}\n"

                    # Кнопка чата для каждого блогера
                    if chat_id:
                        keyboard.append([InlineKeyboardButton(
                            f"💬 Чат с {blogger_name}",
                            callback_data=f"open_chat_{chat_id}"
                        )])

            keyboard.append([InlineKeyboardButton(
                f"✅ Завершить кампанию #{campaign_id}",
                callback_data=f"complete_campaign_{campaign_id}"
            )])

            text += "\n"

        keyboard.append([InlineKeyboardButton("⬅️ Назад к заказам", callback_data="client_my_orders")])

        await safe_edit_message(query, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Ошибка в advertiser_in_progress_campaigns: {e}", exc_info=True)
        await safe_edit_message(query, f"❌ Ошибка: {str(e)}")


async def advertiser_completed_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает завершённые кампании клиента"""
    query = update.callback_query
    await query.answer()

    try:
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        client_profile = db.get_client_profile(user["id"])
        if not client_profile:
            await safe_edit_message(query, "❌ Профиль клиента не найден.")
            return

        # Получаем все кампании и фильтруем завершённые
        all_orders, _, _ = db.get_client_orders(client_profile["id"], page=1, per_page=1000)
        completed_statuses = ['done', 'completed', 'canceled', 'cancelled']
        orders = [o for o in all_orders if dict(o).get('status', 'open') in completed_statuses]

        if not orders:
            keyboard = [[InlineKeyboardButton("⬅️ Назад к заказам", callback_data="client_my_orders")]]
            await safe_edit_message(
                query,
                "✅ <b>Завершённые кампании</b>\n\nУ вас нет завершённых заказов.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Формируем список заказов
        text = f"✅ <b>Завершённые кампании</b> ({len(orders)})\n\n"
        keyboard = []

        for campaign in orders[:10]:  # Показываем первые 10
            campaign_dict = dict(campaign)
            campaign_id = campaign_dict['id']

            status_emoji = {
                "done": "✅",
                "completed": "✅",
                "canceled": "❌"
            }
            status_text = {
                "done": "Выполнен",
                "completed": "Завершён",
                "canceled": "Отменён"
            }

            emoji = status_emoji.get(campaign_dict.get("status", "done"), "✅")
            status = status_text.get(campaign_dict.get("status", "done"), "Завершён")

            text += f"{emoji} <b>Кампания #{campaign_id}</b> - {status}\n"
            text += f"📱 {campaign_dict.get('category', 'Не указана')}\n"

            # ИСПРАВЛЕНО: Тип оплаты с поддержкой комбинированного варианта
            payment_type = campaign_dict.get('payment_type', 'paid')
            budget_type = campaign_dict.get('budget_type', 'none')
            budget_value = campaign_dict.get('budget_value', 0)

            payment_parts = []
            if payment_type in ['paid', 'both']:
                if budget_value > 0:
                    if budget_type == 'fixed':
                        payment_parts.append(f"💰 {int(budget_value)} BYN")
                    elif budget_type == 'flexible':
                        payment_parts.append(f"💬 до {int(budget_value)} BYN")
                    else:
                        payment_parts.append(f"💰 {int(budget_value)} BYN")
                elif budget_type == 'flexible':
                    payment_parts.append("💬 Блогеры предложат цену")
            if payment_type in ['barter', 'both']:
                payment_parts.append("🤝 Бартер")

            if payment_parts:
                text += f"{' + '.join(payment_parts)}\n"
            else:
                text += f"По договорённости\n"

            description = campaign_dict.get('description', '')
            if len(description) > 50:
                description = description[:50] + "..."
            text += f"📝 {description}\n"

            # Показываем чат если есть
            selected_worker_id = campaign_dict.get('selected_worker_id')
            if selected_worker_id:
                chat = db.get_chat_by_order(campaign_id)
                if chat:
                    chat_dict = dict(chat)
                    keyboard.append([InlineKeyboardButton(
                        f"💬 Посмотреть чат (кампания #{campaign_id})",
                        callback_data=f"open_chat_{chat_dict['id']}"
                    )])

            text += "\n"

        keyboard.append([InlineKeyboardButton("⬅️ Назад к заказам", callback_data="client_my_orders")])

        await safe_edit_message(query, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Ошибка в client_completed_orders: {e}", exc_info=True)
        await safe_edit_message(query, f"❌ Ошибка: {str(e)}")


async def cancel_campaign_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Обработчик отмены кампания клиентом.
    """
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id из callback_data
        campaign_id = int(query.data.replace("cancel_campaign_", ""))

        # Получаем пользователя
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Пользователь не найден.")
            return

        # Отменяем кампанию
        result = db.cancel_order(campaign_id, user['id'], reason="Отменена клиентом через бот")

        if not result['success']:
            await query.edit_message_text(
                f"❌ <b>Ошибка отмены кампания</b>\n\n{result['message']}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад к заказам", callback_data="client_my_orders")
                ]])
            )
            return

        # Успешная отмена - уведомляем мастеров
        notified_count = 0
        for blogger_user_id in result['notified_workers']:
            try:
                worker_user = db.get_user_by_id(blogger_user_id)
                if worker_user:
                    await context.bot.send_message(
                        chat_id=worker_user['telegram_id'],
                        text=(
                            f"❌ <b>Кампания #{campaign_id} отменен</b>\n\n"
                            f"Клиент отменил кампанию на который вы откликались.\n"
                            f"Ваше предложение больше не актуально."
                        ),
                        parse_mode="HTML"
                    )
                    notified_count += 1
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление блогеру {blogger_user_id}: {e}")

        # Сообщаем клиенту об успехе
        await query.edit_message_text(
            f"✅ <b>Кампания #{campaign_id} успешно отменена</b>\n\n"
            f"📨 Уведомлено блогеров: {notified_count}\n\n"
            f"Кампания больше не будет показываться в поиске.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📂 Мои кампании", callback_data="client_my_orders"),
                InlineKeyboardButton("💼 Главное меню", callback_data="show_client_menu")
            ]])
        )

        logger.info(f"Кампания {campaign_id} отменена пользователем {user['id']}. Уведомлено блогеров: {notified_count}")

    except Exception as e:
        logger.error(f"Ошибка при отмене кампания: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка при отмене кампания:\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="client_my_orders")
            ]])
        )


async def complete_campaign_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ОБНОВЛЕНО: Обработчик завершения кампания с оценкой - работает для ОБЕИХ сторон.
    Клиент оценивает блогера, блогер оценивает клиента.
    """
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id из callback_data
        campaign_id = int(query.data.replace("complete_campaign_", ""))

        # Получаем пользователя
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Пользователь не найден.")
            return

        user_dict = dict(user)

        # Получаем кампани
        campaign = db.get_order_by_id(campaign_id)
        if not campaign:
            await query.edit_message_text("❌ Кампани не найден.")
            return

        campaign_dict = dict(campaign)

        # Проверяем статус кампании - нельзя оценить отменённую кампанию
        # ВАЖНО: 'completed' разрешён, чтобы обе стороны могли оставить отзыв
        if campaign_dict['status'] in ('cancelled',):
            await safe_edit_message(
                query,
                f"❌ Этот кампания была отменён.\n\n"
                f"Статус: {campaign_dict['status']}",
                parse_mode="HTML"
            )
            return

        # Получаем выбранного блогера
        selected_worker_id = campaign_dict.get('selected_worker_id')
        if not selected_worker_id:
            await safe_edit_message(
                query,
                "❌ Для завершения кампания необходимо сначала выбрать блогера.",
                parse_mode="HTML"
            )
            return

        # КРИТИЧНО: Определяем, кто вызывает - клиент или блогер
        client_profile = db.get_client_profile(user_dict["id"])
        worker_profile_caller = db.get_worker_profile(user_dict["id"])

        is_client = client_profile and campaign_dict['advertiser_id'] == dict(client_profile)['id']
        is_worker = worker_profile_caller and dict(worker_profile_caller)['id'] == selected_worker_id

        if not is_client and not is_worker:
            await safe_edit_message(query, "❌ Вы не являетесь участником этого кампания.")
            return

        # Проверяем, не оставлен ли уже отзыв этим пользователем
        existing_review = db.check_review_exists(campaign_id, user_dict['id'])
        if existing_review:
            await safe_edit_message(
                query,
                "✅ Вы уже завершили эту кампанию и оставили отзыв.",
                parse_mode="HTML"
            )
            return

        # Получаем информацию о противоположной стороне
        if is_client:
            # Клиент оценивает блогера
            target_profile = db.get_worker_by_id(selected_worker_id)
            if not target_profile:
                await safe_edit_message(query, "❌ Информация о блогере не найдена.")
                return
            target_dict = dict(target_profile)
            target_name = target_dict.get('name', 'Без имени')
            target_role = "Блогер"
            cancel_callback = "client_my_orders"
        else:
            # Блогер оценивает клиента
            client_data = db.get_client_by_id(campaign_dict['advertiser_id'])
            if not client_data:
                await safe_edit_message(query, "❌ Информация о клиенте не найдена.")
                return
            client_dict = dict(client_data)
            client_user = db.get_user_by_id(client_dict['user_id'])
            if not client_user:
                await safe_edit_message(query, "❌ Информация о клиенте не найдена.")
                return
            client_user_dict = dict(client_user)
            target_name = client_user_dict.get('first_name', 'Рекламодател')
            target_role = "Рекламодател"
            cancel_callback = "worker_my_orders"

        # Показываем форму оценки
        text = (
            f"✅ <b>Завершение кампания #{campaign_id}</b>\n\n"
            f"👤 <b>{target_role}:</b> {target_name}\n\n"
            f"📊 <b>Оцените {'работу блогера' if is_client else 'рекламодателя'}:</b>\n"
            f"Ваша оценка поможет {'другим клиентам' if is_client else 'другим мастерам'} сделать правильный выбор."
        )

        # Кнопки с оценками от 1 до 5 звезд
        # Формат callback: rate_campaign_{campaign_id}_{rating}_{role}
        # role: 'advertiser' если оценивает клиент, 'blogger' если оценивает блогер
        role_suffix = 'advertiser' if is_client else 'blogger'
        keyboard = [
            [
                InlineKeyboardButton("⭐", callback_data=f"rate_campaign_{campaign_id}_1_{role_suffix}"),
                InlineKeyboardButton("⭐⭐", callback_data=f"rate_campaign_{campaign_id}_2_{role_suffix}"),
                InlineKeyboardButton("⭐⭐⭐", callback_data=f"rate_campaign_{campaign_id}_3_{role_suffix}"),
            ],
            [
                InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"rate_campaign_{campaign_id}_4_{role_suffix}"),
                InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rate_campaign_{campaign_id}_5_{role_suffix}"),
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data=cancel_callback)]
        ]

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        logger.info(f"{'Клиент' if is_client else 'Блогер'} {user_dict['id']} открыл форму завершения кампания {campaign_id}")

    except Exception as e:
        logger.error(f"Ошибка при открытии формы завершения кампания: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка:\n{str(e)}",
            parse_mode="HTML"
        )


async def submit_campaign_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ОБНОВЛЕНО: Обработчик сохранения оценки кампания - работает для ОБЕИХ сторон.
    Callback data format: rate_campaign_{campaign_id}_{rating}_{role}
    role: 'advertiser' (клиент оценивает блогера) или 'blogger' (блогер оценивает клиента)
    """
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id, rating и role из callback_data
        # Формат: rate_campaign_{campaign_id}_{rating}_{role}
        data_parts = query.data.replace("rate_campaign_", "").split("_")
        campaign_id = int(data_parts[0])
        rating = int(data_parts[1])
        role = data_parts[2] if len(data_parts) > 2 else 'advertiser'  # По умолчанию клиент (обратная совместимость)

        is_client = (role == 'advertiser')

        # Получаем пользователя
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)

        # Получаем кампанию
        campaign = db.get_order_by_id(campaign_id)
        if not campaign:
            await safe_edit_message(query, "❌ Кампания не найдена.")
            return

        campaign_dict = dict(campaign)

        # Получаем выбранного блогера
        selected_worker_id = campaign_dict.get('selected_worker_id')
        if not selected_worker_id:
            await safe_edit_message(query, "❌ Блогер не выбран.")
            return

        # Получаем информацию о блогере
        worker_profile = db.get_worker_by_id(selected_worker_id)
        if not worker_profile:
            await safe_edit_message(query, "❌ Информация о блогере не найдена.")
            return

        worker_dict = dict(worker_profile)
        blogger_user_id = worker_dict['user_id']

        # Получаем информацию о клиенте
        client_data = db.get_client_by_id(campaign_dict['advertiser_id'])
        if not client_data:
            await safe_edit_message(query, "❌ Информация о клиенте не найдена.")
            return
        client_dict = dict(client_data)
        advertiser_user_id = client_dict['user_id']

        # Сохраняем отзыв в зависимости от того, кто оценивает
        if is_client:
            # Клиент оценивает блогера
            review_saved = db.add_review(
                from_user_id=user_dict['id'],
                to_user_id=blogger_user_id,
                campaign_id=campaign_id,
                role_from='advertiser',
                role_to='blogger',
                rating=rating,
                comment=None
            )
            target_name = worker_dict.get('name', 'Без имени')
            target_role = "блогера"
            return_callback = "client_my_orders"
            return_menu_callback = "show_client_menu"
            notify_user_id = blogger_user_id
            notify_text_prefix = "Клиент завершил кампанию и оставил вам оценку"
        else:
            # Блогер оценивает клиента
            review_saved = db.add_review(
                from_user_id=user_dict['id'],
                to_user_id=advertiser_user_id,
                campaign_id=campaign_id,
                role_from='blogger',
                role_to='advertiser',
                rating=rating,
                comment=None
            )
            client_user = db.get_user_by_id(advertiser_user_id)
            client_user_dict = dict(client_user) if client_user else {}
            target_name = client_user_dict.get('first_name', 'Клиент')
            target_role = "клиента"
            return_callback = "worker_my_orders"
            return_menu_callback = "show_worker_menu"
            notify_user_id = advertiser_user_id
            notify_text_prefix = "Блогер завершил кампанию и оставил вам оценку"

        if not review_saved:
            await safe_edit_message(
                query,
                "❌ Не удалось сохранить отзыв. Возможно, вы уже оценили эту кампанию.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад к заказам", callback_data=return_callback)
                ]])
            )
            return

        # Проверяем, оставила ли противоположная сторона уже отзыв
        opposite_review_exists = db.check_review_exists(campaign_id, notify_user_id)

        # ИСПРАВЛЕНО: Обновляем статус кампания на "completed" СРАЗУ при первой оценке
        # Это делает кампанию видимой в "Завершенные кампании" у обеих сторон
        if campaign_dict['status'] not in ['completed', 'done']:
            db.update_order_status(campaign_id, 'completed')
            logger.info(f"✅ Кампания {campaign_id} помечена как 'completed' - первая оценка получена")

        # Если обе стороны оценили, дополнительно помечаем как 'done'
        if opposite_review_exists and campaign_dict['status'] != 'done':
            db.update_order_status(campaign_id, 'done')
            logger.info(f"✅ Кампания {campaign_id} помечена как 'done' - обе стороны оценили")

        # Уведомляем противоположную сторону
        try:
            notify_user = db.get_user_by_id(notify_user_id)
            if not notify_user:
                logger.error(f"❌ Пользователь {notify_user_id} не найден для отправки уведомления")
                return

            notify_user_dict = dict(notify_user)
            logger.info(f"📨 Отправка уведомления о завершении кампания #{campaign_id} пользователю {notify_user_id} (telegram_id={notify_user_dict['telegram_id']})")

            # ИСПРАВЛЕНО: НЕ показываем рейтинг в уведомлении
            # Пользователь НЕ должен видеть кто и какую оценку ему поставил

            # Предлагаем противоположной стороне оценить
            keyboard = []
            if not opposite_review_exists:
                if is_client:
                    # Клиент оценил блогера - предлагаем блогеру оценить клиента
                    keyboard.append([InlineKeyboardButton("⭐ Оценить рекламодателя", callback_data=f"leave_review_{campaign_id}")])
                    extra_text = "\n\n💡 Оцените рекламодателя - это поможет другим блогерам!"
                    logger.info(f"⭐ Клиент оценил блогера - предлагаем блогеру оценить клиента")
                else:
                    # Блогер оценил клиента - предлагаем клиенту оценить блогера
                    keyboard.append([InlineKeyboardButton("⭐ Оценить блогера", callback_data=f"leave_review_{campaign_id}")])
                    extra_text = "\n\n💡 Оцените работу блогера - это поможет другим рекламодателям!"
                    logger.info(f"⭐ Блогер оценил клиента - предлагаем клиенту оценить блогера")
            else:
                extra_text = ""

            await context.bot.send_message(
                chat_id=notify_user_dict['telegram_id'],
                text=(
                    f"✅ <b>Кампания #{campaign_id} завершена!</b>\n\n"
                    f"Противоположная сторона завершила кампанию.\n\n"
                    f"🎉 Поздравляем с успешным {'выполнением контента' if is_client else 'заказом'}!"
                    f"{extra_text}"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
            logger.info(f"✅ Уведомление о завершении кампания #{campaign_id} успешно отправлено пользователю {notify_user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке уведомления пользователю {notify_user_id}: {e}", exc_info=True)

        # Показываем сообщение об успехе
        stars = "⭐" * rating
        text = (
            f"✅ <b>Кампания завершена!</b>\n\n"
            f"Спасибо за вашу оценку: {stars} ({rating}/5)\n\n"
            f"👤 <b>{target_role.capitalize()}:</b> {target_name}\n\n"
            f"💬 Хотите оставить комментарий к отзыву?"
        )

        keyboard = [
            [InlineKeyboardButton("💬 Оставить комментарий", callback_data=f"add_comment_{campaign_id}")],
            [InlineKeyboardButton("📂 Мои кампании", callback_data=return_callback)],
            [InlineKeyboardButton("💼 Главное меню", callback_data=return_menu_callback)]
        ]

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        logger.info(f"{'Клиент' if is_client else 'Блогер'} {user_dict['id']} завершил кампанию {campaign_id} с оценкой {rating}")

    except Exception as e:
        logger.error(f"Ошибка при сохранении оценки кампания: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка при сохранении оценки:\n{str(e)}",
            parse_mode="HTML"
        )


async def add_comment_to_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Оставить комментарий' после завершения кампания"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id из callback_data
        campaign_id = int(query.data.replace("add_comment_", ""))

        # Получаем пользователя
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)

        # Проверяем что отзыв существует
        if not db.check_review_exists(campaign_id, user_dict['id']):
            await safe_edit_message(
                query,
                "❌ Отзыв не найден. Сначала завершите кампанию с оценкой.",
                parse_mode="HTML"
            )
            return

        # Сохраняем campaign_id в context для последующего использования
        context.user_data['add_comment_order_id'] = campaign_id

        # Просим пользователя ввести комментарий
        await safe_edit_message(
            query,
            f"💬 <b>Добавление комментария к отзыву</b>\n\n"
            f"Кампания #{campaign_id}\n\n"
            f"Напишите ваш комментарий к отзыву (до 500 символов):",
            parse_mode="HTML"
        )

        logger.info(f"Пользователь {user_dict['id']} начал добавление комментария к отзыву по кампании {campaign_id}")

    except Exception as e:
        logger.error(f"Ошибка при начале добавления комментария: {e}", exc_info=True)
        await safe_edit_message(query, f"❌ Ошибка: {str(e)}")


async def receive_review_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает текст комментария от пользователя"""
    # Проверяем что пользователь в процессе добавления комментария
    if 'add_comment_order_id' not in context.user_data:
        return  # Игнорируем сообщение если не ожидаем комментарий

    campaign_id = context.user_data['add_comment_order_id']
    comment = update.message.text.strip()

    if len(comment) > 500:
        await update.message.reply_text(
            "❌ Комментарий слишком длинный. Максимум 500 символов.\n\n"
            "Пожалуйста, отправьте более короткий комментарий:"
        )
        return

    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ Пользователь не найден.")
        del context.user_data['add_comment_order_id']
        return

    user_dict = dict(user)

    # Определяем роль пользователя
    worker_profile = db.get_worker_by_user_id(user_dict['id'])
    is_worker = worker_profile is not None

    # Обновляем комментарий в отзыве
    success = db.update_review_comment(campaign_id, user_dict['id'], comment)

    # Кнопки возврата в зависимости от роли
    if is_worker:
        keyboard = [
            [InlineKeyboardButton("📂 Мои кампании", callback_data="worker_my_orders")],
            [InlineKeyboardButton("📱 Меню блогера", callback_data="show_worker_menu")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("📂 Мои кампании", callback_data="client_my_orders")],
            [InlineKeyboardButton("💼 Меню рекламодатела", callback_data="show_client_menu")]
        ]

    if success:
        await update.message.reply_text(
            f"✅ <b>Комментарий добавлен!</b>\n\n"
            f"Ваш отзыв обновлён.\n\n"
            f"💬 <i>\"{comment}\"</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        logger.info(f"Пользователь {user_dict['id']} добавил комментарий к отзыву по кампании {campaign_id}")
    else:
        await update.message.reply_text(
            "❌ Не удалось обновить комментарий.\n\n"
            "Возможно отзыв не найден.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # Очищаем состояние
    del context.user_data['add_comment_order_id']


async def blogger_upload_work_photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Начало загрузки фото завершённого контента блогером.
    """
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id из callback_data
        campaign_id = int(query.data.replace("upload_work_photo_", ""))

        # Сохраняем campaign_id в context для последующей загрузки фото
        context.user_data['uploading_work_photo_order_id'] = campaign_id

        text = (
            f"📸 <b>Загрузка фото контента для кампании #{campaign_id}</b>\n\n"
            f"Отправьте фотографии выполненного контента (до 3 фото).\n\n"
            f"✅ <b>Подтвержденные рекламодателем фото:</b>\n"
            f"• Получат специальный значок ✅\n"
            f"• Повышают доверие клиентов\n"
            f"• Максимум 90 фото в профиле\n\n"
            f"💡 <b>Советы для качественных фото:</b>\n"
            f"• Убедитесь, что контента хорошо видна\n"
            f"• Используйте хорошее освещение\n"
            f"• Покажите результат с разных ракурсов\n\n"
            f"После загрузки всех фото нажмите «Завершить»."
        )

        keyboard = [
            [InlineKeyboardButton("✅ Завершить загрузку", callback_data=f"finish_work_photos_{campaign_id}")],
            [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_work_photos_{campaign_id}")]
        ]

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Инициализируем список загруженных фото
        context.user_data['uploaded_work_photos'] = []

        logger.info(f"Блогер начал загрузку фото для кампания {campaign_id}")

    except Exception as e:
        logger.error(f"Ошибка при начале загрузки фото контента: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка:\n{str(e)}",
            parse_mode="HTML"
        )


async def blogger_skip_work_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Пропуск загрузки фото контента.
    """
    query = update.callback_query
    await query.answer()

    try:
        campaign_id = int(query.data.replace("skip_work_photo_", ""))

        keyboard = [
            [InlineKeyboardButton("📂 Мои кампании", callback_data="worker_my_orders")],
            [InlineKeyboardButton("📱 Меню блогера", callback_data="show_worker_menu")]
        ]

        await safe_edit_message(
            query,
            "✅ Фото контента можно добавить позже через профиль.\n\n"
            "Спасибо за контент!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        logger.info(f"Блогер пропустил загрузку фото для кампания {campaign_id}")

    except Exception as e:
        logger.error(f"Ошибка при пропуске загрузки фото: {e}", exc_info=True)


async def blogger_upload_work_photo_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Получение фото завершённого контента от блогера.
    """
    try:
        # КРИТИЧНО: Пропускаем если идет загрузка фото профиля или портфолио
        if context.user_data.get('uploading_profile_photo') or context.user_data.get('adding_photos'):
            return  # Пропускаем - пусть обработают другие handlers

        # Проверяем, что идёт процесс загрузки фото контента
        campaign_id = context.user_data.get('uploading_work_photo_order_id')
        if not campaign_id:
            return  # Игнорируем фото, если не в процессе загрузки

        # Получаем file_id фото
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id  # Берём фото максимального размера

            # Добавляем в список загруженных
            if 'uploaded_work_photos' not in context.user_data:
                context.user_data['uploaded_work_photos'] = []

            # Проверяем лимит 3 фото
            if len(context.user_data['uploaded_work_photos']) >= 3:
                await update.message.reply_text(
                    "⚠️ <b>Достигнут лимит</b>\n\n"
                    "Максимум 3 фото на одну кампанию.\n\n"
                    "Нажмите «Завершить загрузку» чтобы сохранить фото.",
                    parse_mode="HTML"
                )
                return

            context.user_data['uploaded_work_photos'].append(photo_id)
            count = len(context.user_data['uploaded_work_photos'])

            # Подтверждаем получение
            remaining = 3 - count
            if remaining > 0:
                await update.message.reply_text(
                    f"✅ Фото {count}/3 получено.\n\n"
                    f"Можете отправить ещё {remaining} фото или нажмите «Завершить загрузку».",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"✅ Все 3 фото получены!\n\n"
                    f"Нажмите «Завершить загрузку» чтобы сохранить.",
                    parse_mode="HTML"
                )

            logger.info(f"Получено фото {count}/3 для кампания {campaign_id}")

    except Exception as e:
        logger.error(f"Ошибка при получении фото контента: {e}", exc_info=True)


async def blogger_finish_work_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Завершение загрузки фото контента и сохранение в БД.
    """
    query = update.callback_query
    await query.answer()

    try:
        campaign_id = int(query.data.replace("finish_work_photos_", ""))
        photos = context.user_data.get('uploaded_work_photos', [])

        if not photos:
            # ИСПРАВЛЕНО: Добавлены кнопки для повторной попытки или пропуска
            keyboard = [
                [InlineKeyboardButton("📸 Попробовать снова", callback_data=f"upload_work_photo_{campaign_id}")],
                [InlineKeyboardButton("➡️ Пропустить (добавить позже)", callback_data=f"skip_work_photo_{campaign_id}")],
                [InlineKeyboardButton("⬅️ К моим заказам", callback_data="worker_my_orders")]
            ]
            await safe_edit_message(
                query,
                "❌ <b>Вы не загрузили ни одного фото</b>\n\n"
                "Чтобы загрузить фото:\n"
                "1️⃣ Нажмите «Попробовать снова»\n"
                "2️⃣ Отправьте фотографии (до 3 шт)\n"
                "3️⃣ Нажмите «Завершить загрузку»\n\n"
                "💡 Вы также можете пропустить и добавить фото позже через раздел «Мои кампании».",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Получаем информацию о блогере
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict["id"])
        if not worker_profile:
            await safe_edit_message(query, "❌ Профиль блогера не найден.")
            return

        worker_dict = dict(worker_profile)

        # Проверяем общий лимит подтвержденных фото (90 максимум)
        current_total = db.count_worker_completed_work_photos(worker_dict['id'])
        remaining_slots = max(0, 90 - current_total)

        if remaining_slots == 0:
            await safe_edit_message(
                query,
                "⚠️ <b>Достигнут максимальный лимит</b>\n\n"
                "У вас уже 90 подтвержденных фото контент (максимум).\n\n"
                "🗑 <b>Удалите старые фото:</b>\n"
                "Чтобы добавить новые, сначала удалите некоторые старые фото через управление портфолио.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🗑 Управление фото", callback_data="manage_completed_photos"),
                    InlineKeyboardButton("⬅️ Назад", callback_data="worker_my_orders")
                ]])
            )
            context.user_data.pop('uploading_work_photo_order_id', None)
            context.user_data.pop('uploaded_work_photos', None)
            return

        # Если фото больше чем доступно слотов - обрезаем
        photos_to_save = photos[:remaining_slots]
        if len(photos_to_save) < len(photos):
            warning_text = f"\n\n⚠️ Сохранено только {len(photos_to_save)} из {len(photos)} фото (достигнут лимит 90)"
        else:
            warning_text = ""

        # Сохраняем каждое фото в БД
        saved_count = 0
        for photo_id in photos_to_save:
            result = db.add_completed_work_photo(campaign_id, worker_dict['id'], photo_id)
            if result:
                saved_count += 1

        # Получаем кампании для уведомления клиента
        campaign = db.get_order_by_id(campaign_id)
        if campaign:
            campaign_dict = dict(campaign)
            advertiser = db.get_client_by_id(campaign_dict['advertiser_id'])
            if advertiser:
                client_dict = dict(advertiser)
                client_user = db.get_user_by_id(client_dict['user_id'])
                if client_user:
                    client_user_dict = dict(client_user)

                    # Уведомляем клиента о загруженных фото
                    keyboard = [
                        [InlineKeyboardButton("📸 Проверить фото", callback_data=f"check_work_photos_{campaign_id}")],
                        [InlineKeyboardButton("➡️ Позже", callback_data="noop")]
                    ]

                    try:
                        await context.bot.send_message(
                            chat_id=client_user_dict['telegram_id'],
                            text=(
                                f"📸 <b>Блогер загрузил фото контента!</b>\n\n"
                                f"По кампании #{campaign_id} блогер <b>{worker_dict.get('name', 'Блогер')}</b> "
                                f"загрузил {saved_count} {_get_photos_word(saved_count)} выполненного контента.\n\n"
                                f"✅ <b>Подтвердите фотографии:</b>\n"
                                f"Если это действительно фото вашего кампания, подтвердите их. "
                                f"Подтверждённые фото получат специальный значок ✅ и будут показаны в профиле блогера."
                            ),
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось уведомить клиента о фото: {e}")

        # Подтверждаем блогеру (ИСПРАВЛЕНО: добавлены кнопки навигации)
        keyboard = [
            [InlineKeyboardButton("👤 Мой профиль", callback_data="worker_profile")],
            [InlineKeyboardButton("📦 Мои кампании", callback_data="worker_my_orders")],
            [InlineKeyboardButton("💼 Главное меню", callback_data="show_worker_menu")]
        ]

        await safe_edit_message(
            query,
            f"✅ <b>Фотографии загружены!</b>\n\n"
            f"Загружено {saved_count} {_get_photos_word(saved_count)}.\n\n"
            f"📨 Клиент получил уведомление и сможет подтвердить подлинность фото.\n"
            f"Подтверждённые фото будут отмечены значком ✅ в вашем профиле."
            f"{warning_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Очищаем context
        context.user_data.pop('uploading_work_photo_order_id', None)
        context.user_data.pop('uploaded_work_photos', None)

        logger.info(f"Блогер {worker_dict['id']} загрузил {saved_count} фото для кампания {campaign_id}")

    except Exception as e:
        logger.error(f"Ошибка при завершении загрузки фото: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка при сохранении фото:\n{str(e)}",
            parse_mode="HTML"
        )


async def blogger_cancel_work_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Отмена загрузки фото контента.
    """
    query = update.callback_query
    await query.answer()

    try:
        # Очищаем context
        context.user_data.pop('uploading_work_photo_order_id', None)
        context.user_data.pop('uploaded_work_photos', None)

        await safe_edit_message(
            query,
            "❌ Загрузка фото отменена.\n\n"
            "Вы сможете добавить фото позже через профиль.",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при отмене загрузки фото: {e}", exc_info=True)


async def manage_completed_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Управление фотографиями завершенных контент блогера.
    Позволяет просматривать и удалять старые фото.
    """
    query = update.callback_query
    await query.answer()

    try:
        user_id = query.from_user.id
        user = db.get_user_by_telegram_id(user_id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict['id'])
        if not worker_profile:
            await safe_edit_message(query, "❌ Профиль блогера не найден.")
            return

        worker_dict = dict(worker_profile)

        # Получаем все фотографии блогера
        all_photos = db.get_all_worker_completed_photos(worker_dict['id'])
        if not all_photos:
            await safe_edit_message(
                query,
                "📸 <b>У вас пока нет фотографий завершенных контент</b>\n\n"
                "Фотографии появятся после завершения заказов.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")
                ]])
            )
            return

        total_photos = len(all_photos)

        # Сохраняем текущую страницу в context
        if 'photo_management_page' not in context.user_data:
            context.user_data['photo_management_page'] = 0

        page = context.user_data.get('photo_management_page', 0)
        photos_per_page = 5
        start_idx = page * photos_per_page
        end_idx = start_idx + photos_per_page
        photos_on_page = all_photos[start_idx:end_idx]

        # Формируем сообщение
        text = (
            f"🗑 <b>Управление фотографиями контент</b>\n\n"
            f"📊 <b>Всего фото:</b> {total_photos}/90\n\n"
            f"💡 <b>Совет:</b> Оставляйте только лучшие работы для красивого портфолио!\n\n"
            f"📸 <b>Страница {page + 1}/{(total_photos - 1) // photos_per_page + 1}:</b>"
        )

        # Формируем клавиатуру с фото
        keyboard = []
        for idx, photo in enumerate(photos_on_page, start=start_idx + 1):
            photo_dict = dict(photo)
            verified_mark = "✅" if photo_dict.get('verified') else ""
            order_title = photo_dict.get('order_title', 'Без названия')[:30]

            keyboard.append([InlineKeyboardButton(
                f"{verified_mark} Фото #{idx}: {order_title}",
                callback_data=f"view_work_photo_{photo_dict['id']}"
            )])

        # Кнопки навигации
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data="photo_page_prev"))
        if end_idx < total_photos:
            nav_buttons.append(InlineKeyboardButton("➡️ Вперед", callback_data="photo_page_next"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Кнопка возврата
        keyboard.append([InlineKeyboardButton("💼 В главное меню", callback_data="show_worker_menu")])

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка при управлении фото: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка:\n{str(e)}",
            parse_mode="HTML"
        )


async def photo_page_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Навигация между страницами фотографий.
    """
    query = update.callback_query
    await query.answer()

    try:
        direction = query.data.replace("photo_page_", "")
        current_page = context.user_data.get('photo_management_page', 0)

        if direction == "next":
            context.user_data['photo_management_page'] = current_page + 1
        elif direction == "prev":
            context.user_data['photo_management_page'] = max(0, current_page - 1)

        # Перенаправляем на manage_completed_photos для обновления отображения
        await manage_completed_photos(update, context)

    except Exception as e:
        logger.error(f"Ошибка при навигации по страницам: {e}", exc_info=True)


async def view_work_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Просмотр отдельного фото контента с возможностью удаления.
    """
    query = update.callback_query
    await query.answer()

    try:
        photo_db_id = int(query.data.replace("view_work_photo_", ""))

        user_id = query.from_user.id
        user = db.get_user_by_telegram_id(user_id)
        if not user:
            await safe_edit_message(query, "❌ Пользователь не найден.")
            return

        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict['id'])
        if not worker_profile:
            await safe_edit_message(query, "❌ Профиль блогера не найден.")
            return

        worker_dict = dict(worker_profile)

        # Получаем все фото и находим нужное
        all_photos = db.get_all_worker_completed_photos(worker_dict['id'])
        target_photo = None
        for photo in all_photos:
            photo_dict = dict(photo)
            if photo_dict['id'] == photo_db_id:
                target_photo = photo_dict
                break

        if not target_photo:
            await safe_edit_message(query, "❌ Фото не найдено.")
            return

        # Отправляем фото с кнопками
        verified_text = "✅ Подтверждено рекламодателем" if target_photo.get('verified') else "⏳ Не подтверждено"
        order_title = target_photo.get('order_title', 'Без названия')

        text = (
            f"📸 <b>Фото контента</b>\n\n"
            f"📋 <b>Кампания:</b> {order_title}\n"
            f"🔖 <b>Статус:</b> {verified_text}\n\n"
            f"🗑 Хотите удалить это фото?"
        )

        keyboard = [
            [InlineKeyboardButton("🗑 Удалить фото", callback_data=f"confirm_delete_photo_{photo_db_id}")],
            [InlineKeyboardButton("⬅️ Назад к списку", callback_data="manage_completed_photos")]
        ]

        # Удаляем старое сообщение и отправляем фото
        await query.message.delete()
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=target_photo['photo_id'],
            caption=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре фото: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Произошла ошибка:\n{str(e)}",
            parse_mode="HTML"
        )


async def confirm_delete_work_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Подтверждение удаления фото контента.
    """
    query = update.callback_query
    await query.answer()

    try:
        photo_db_id = int(query.data.replace("confirm_delete_photo_", ""))

        # Удаляем фото из БД
        success = db.delete_completed_work_photo(photo_db_id)

        if success:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="✅ <b>Фото удалено</b>\n\nВозвращаемся к списку фотографий...",
                parse_mode="HTML"
            )

            # Сбрасываем страницу и возвращаемся к списку
            context.user_data['photo_management_page'] = 0

            # Создаем новый query для manage_completed_photos
            # Используем send_message вместо редактирования
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="🔄 Обновляем список...",
                parse_mode="HTML"
            )
        else:
            await query.message.edit_caption(
                caption="❌ Не удалось удалить фото. Попробуйте позже.",
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка при удалении фото: {e}", exc_info=True)
        await query.message.edit_caption(
            caption=f"❌ Произошла ошибка:\n{str(e)}",
            parse_mode="HTML"
        )


async def advertiser_check_work_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВОЕ: Просмотр фото контента клиентом для подтверждения.
    """
    query = update.callback_query
    await query.answer()

    try:
        campaign_id = int(query.data.replace("check_work_photos_", ""))

        # Получаем фото контента
        photos = db.get_completed_work_photos(campaign_id)
        if not photos:
            await safe_edit_message(
                query,
                "❌ Фотографии не найдены.",
                parse_mode="HTML"
            )
            return

        # Отправляем фото с кнопками подтверждения
        text = (
            f"📸 <b>Фотографии контента по кампании #{campaign_id}</b>\n\n"
            f"Всего фото: {len(photos)}\n\n"
            f"Подтвердите, что это фото вашего кампания:"
        )

        for idx, photo in enumerate(photos):
            photo_dict = dict(photo)
            status = "✅ Подтверждено" if photo_dict['verified'] else "⏳ Ожидает подтверждения"

            keyboard = []
            if not photo_dict['verified']:
                keyboard.append([InlineKeyboardButton(
                    f"✅ Подтвердить фото #{idx+1}",
                    callback_data=f"verify_photo_{photo_dict['id']}"
                )])

            try:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=photo_dict['photo_id'],
                    caption=f"Фото #{idx+1} - {status}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке фото: {e}")

        await query.message.delete()

    except Exception as e:
        logger.error(f"Ошибка при просмотре фото контента: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Произошла ошибка:\n{str(e)}",
            parse_mode="HTML"
        )


async def advertiser_verify_work_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ИСПРАВЛЕНО: Подтверждение фото контента клиентом.
    После подтверждения фото добавляется в портфолио блогера.
    """
    query = update.callback_query
    await query.answer("✅ Фото подтверждено!")

    try:
        photo_id = int(query.data.replace("verify_photo_", ""))

        # Получаем информацию о фото перед подтверждением (для уведомления блогера)
        photo_info = db.get_completed_work_photo_by_id(photo_id)

        # Подтверждаем фото в БД (также добавляет в портфолио блогера)
        success = db.verify_completed_work_photo(photo_id)

        if success:
            # НОВОЕ: Уведомляем блогера о подтверждении фото
            if photo_info:
                photo_dict = dict(photo_info)
                worker_id = photo_dict.get('worker_id')
                campaign_id = photo_dict.get('campaign_id')

                if worker_id:
                    worker_profile = db.get_worker_profile_by_id(worker_id)
                    if worker_profile:
                        worker_dict = dict(worker_profile)
                        worker_user = db.get_user_by_id(worker_dict['user_id'])

                        if worker_user:
                            worker_user_dict = dict(worker_user)
                            try:
                                # Отправляем уведомление блогеру
                                await context.bot.send_message(
                                    chat_id=worker_user_dict['telegram_id'],
                                    text=(
                                        f"✅ <b>Клиент подтвердил ваше фото!</b>\n\n"
                                        f"Ваше фото контента по кампании #{campaign_id} подтверждено клиентом.\n\n"
                                        f"🎉 Фото добавлено в ваш профиль с отметкой ✅ «Подтверждено клиентом».\n\n"
                                        f"💡 Подтверждённые фото повышают доверие новых клиентов!"
                                    ),
                                    parse_mode="HTML",
                                    reply_markup=InlineKeyboardMarkup([[
                                        InlineKeyboardButton("👤 Мой профиль", callback_data="worker_profile"),
                                        InlineKeyboardButton("💼 Главное меню", callback_data="show_worker_menu")
                                    ]])
                                )
                                logger.info(f"✅ Отправлено уведомление блогеру {worker_id} о подтверждении фото {photo_id}")
                            except Exception as e:
                                logger.warning(f"Не удалось уведомить блогера о подтверждении фото: {e}")

            # Определяем роль для кнопки возврата
            user = db.get_user(query.from_user.id)
            is_worker = db.get_worker_profile(user['id']) if user else None
            menu_callback = "show_worker_menu" if is_worker else "show_client_menu"

            keyboard = [[InlineKeyboardButton("💼 Главное меню", callback_data=menu_callback)]]

            await query.edit_message_caption(
                caption="✅ <b>Фото подтверждено клиентом</b>\n\n"
                        "Это фото добавлено в портфолио блогера с отметкой о подтверждении.\n\n"
                        "Теперь другие заказчики смогут видеть этот проверенный контент в профиле блогера.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"✅ Клиент подтвердил фото {photo_id}, добавлено в портфолио")
        else:
            await query.answer("❌ Ошибка при подтверждении фото", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка при подтверждении фото: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка", show_alert=True)


def _get_photos_word(count):
    """Вспомогательная функция для склонения слова 'фото'"""
    if count % 10 == 1 and count % 100 != 11:
        return "фото"
    elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
        return "фото"
    else:
        return "фото"


async def view_campaign_offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр откликов на кампанию клиента с навигацией"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id из callback_data или из user_data (если вызвано из sort_offers_handler)
        if '_view_offers_campaign_id' in context.user_data:
            campaign_id = context.user_data.pop('_view_offers_campaign_id')
        else:
            campaign_id = int(query.data.replace("view_offers_", ""))

        # Проверяем что кампания принадлежит текущему пользователю
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text(
                "❌ Ошибка: пользователь не найден.",
                parse_mode="HTML"
            )
            return

        client_profile = db.get_client_profile(user["id"])
        if not client_profile:
            await query.edit_message_text(
                "❌ Ошибка: профиль клиента не найден.",
                parse_mode="HTML"
            )
            return

        # Получаем кампанию
        campaign = db.get_order_by_id(campaign_id)
        if not campaign or campaign['advertiser_id'] != client_profile['id']:
            await query.edit_message_text(
                "❌ Кампания не найдена или у вас нет доступа к ней.",
                parse_mode="HTML"
            )
            return

        # Получаем все отклики
        bids = db.get_bids_for_order(campaign_id)

        if not bids:
            keyboard = [[InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")]]
            await query.edit_message_text(
                f"💼 <b>Отклики на кампанию #{campaign_id}</b>\n\n"
                "Пока нет откликов от блогеров.\n\n"
                "Ожидайте, блогеры скоро откликнутся!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Применяем сортировку, если выбрана
        sort_order = context.user_data.get('bids_sort_order', 'default')
        bids_list = [dict(offer) for offer in bids]

        if sort_order == 'price_low':
            bids_list.sort(key=lambda x: x.get('proposed_price', 0))
        elif sort_order == 'price_high':
            bids_list.sort(key=lambda x: x.get('proposed_price', 0), reverse=True)
        elif sort_order == 'rating':
            bids_list.sort(key=lambda x: x.get('blogger_rating', 0), reverse=True)
        elif sort_order == 'timeline':
            bids_list.sort(key=lambda x: x.get('ready_in_days', 999))

        # Сохраняем отклики в контексте для навигации
        context.user_data['viewing_bids'] = {
            'campaign_id': campaign_id,
            'bids': bids_list,
            'current_index': 0
        }

        # Показываем первое предложение
        await show_offer_card(update, context, query=query)

    except Exception as e:
        logger.error(f"Ошибка в view_order_bids: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")]]
        await query.edit_message_text(
            f"❌ Ошибка при загрузке откликов:\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def sort_offers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сортировки откликов"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id и тип сортировки из callback_data
        # Формат: sort_bids_{campaign_id}_{sort_type}
        parts = query.data.replace("sort_bids_", "").split("_")
        campaign_id = int(parts[0])
        sort_type = "_".join(parts[1:])  # price_low, price_high, rating, timeline

        # Сохраняем выбранную сортировку и campaign_id для view_campaign_offers
        context.user_data['bids_sort_order'] = sort_type
        context.user_data['_view_offers_campaign_id'] = campaign_id

        # Перезагружаем отклики с новой сортировкой
        await view_campaign_offers(update, context)

    except Exception as e:
        logger.error(f"Ошибка в sort_bids_handler: {e}", exc_info=True)
        await query.answer("❌ Ошибка при сортировке откликов", show_alert=True)


async def show_offer_card(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """Показывает карточку предложения с информацией о блогере"""
    if not query:
        query = update.callback_query
        await query.answer()

    try:
        bid_data = context.user_data.get('viewing_bids')
        if not bid_data:
            await query.edit_message_text(
                "❌ Ошибка: данные откликов не найдены.",
                parse_mode="HTML"
            )
            return

        bids = bid_data['bids']
        current_index = bid_data['current_index']
        offer = bids[current_index]

        # Формируем текст карточки блогера
        text = f"💼 <b>Предложение {current_index + 1} из {len(bids)}</b>\n\n"

        text += f"👤 <b>{offer['blogger_name']}</b>\n"

        # Город
        city = offer.get('blogger_city', '')
        if city:
            text += f"📍 {city}\n"

        text += "\n"

        # Подписчики (без длинных ссылок - ссылки будут в кнопках)
        instagram_followers = offer.get('blogger_instagram_followers', 0) or 0
        tiktok_followers = offer.get('blogger_tiktok_followers', 0) or 0
        youtube_followers = offer.get('blogger_youtube_followers', 0) or 0
        telegram_followers = offer.get('blogger_telegram_followers', 0) or 0

        # Сохраняем ссылки для кнопок
        instagram_link = offer.get('blogger_instagram_link', '') or ''
        tiktok_link = offer.get('blogger_tiktok_link', '') or ''
        youtube_link = offer.get('blogger_youtube_link', '') or ''
        telegram_link = offer.get('blogger_telegram_link', '') or ''

        # Показываем только подписчиков в тексте (ссылки в кнопках)
        social_list = []
        if instagram_followers > 0:
            social_list.append(f"📸 Instagram: {format_followers_count(instagram_followers)}")
        if tiktok_followers > 0:
            social_list.append(f"🎵 TikTok: {format_followers_count(tiktok_followers)}")
        if youtube_followers > 0:
            social_list.append(f"📺 YouTube: {format_followers_count(youtube_followers)}")
        if telegram_followers > 0:
            social_list.append(f"✈️ Telegram: {format_followers_count(telegram_followers)}")

        if social_list:
            text += "<b>Подписчики:</b>\n"
            text += "\n".join(social_list)
            text += "\n\n"

        # Предложенная цена (с учетом типа оплаты кампании)
        price = offer.get('proposed_price', 0) or 0
        currency = offer.get('currency', 'BYN')
        campaign_payment_type = offer.get('campaign_payment_type', 'paid')
        campaign_budget_type = offer.get('campaign_budget_type', '')
        campaign_budget_value = offer.get('campaign_budget_value', 0) or 0

        # Определяем что показывать
        if campaign_payment_type == 'barter' or (price == 0 and campaign_payment_type in ['barter', 'both']):
            # Бартер
            text += f"🤝 <b>Согласился работать по бартеру</b>\n"
        elif campaign_budget_type == 'fixed' and campaign_budget_value > 0 and price == 0:
            # Фиксированная цена - блогер согласился
            text += f"💰 <b>Согласился работать за {int(campaign_budget_value)} {currency}</b>\n"
        elif price > 0:
            # Блогер предложил свою цену
            text += f"💰 <b>Предложил {int(price)} {currency}</b>\n"
        else:
            # По бартеру (если цена 0)
            text += f"🤝 <b>Согласился работать по бартеру</b>\n"

        # Комментарий к предложению
        comment = offer.get('comment', '')
        if comment:
            text += f"\n💬 <b>Комментарий:</b>\n{comment}\n"

        text += "\n💡 <i>Выберите этого блогера, чтобы получить доступ к его контактам</i>"

        # Кнопки навигации и действий
        keyboard = []

        # Сортировка (если откликов больше 1)
        if len(bids) > 1:
            current_sort = context.user_data.get('bids_sort_order', 'default')
            sort_buttons = [
                InlineKeyboardButton(
                    "✅ Цена ⬆️" if current_sort == "price_low" else "Цена ⬆️",
                    callback_data=f"sort_bids_{bid_data['campaign_id']}_price_low"
                ),
                InlineKeyboardButton(
                    "✅ Цена ⬇️" if current_sort == "price_high" else "Цена ⬇️",
                    callback_data=f"sort_bids_{bid_data['campaign_id']}_price_high"
                ),
                InlineKeyboardButton(
                    "✅ Рейтинг" if current_sort == "rating" else "⭐ Рейтинг",
                    callback_data=f"sort_bids_{bid_data['campaign_id']}_rating"
                ),
            ]
            keyboard.append(sort_buttons)

        # Навигация (если откликов больше 1)
        if len(bids) > 1:
            nav_buttons = []
            if current_index > 0:
                nav_buttons.append(InlineKeyboardButton("◀️ Предыдущий", callback_data="bid_prev"))
            nav_buttons.append(InlineKeyboardButton(
                f"{current_index + 1}/{len(bids)}",
                callback_data="noop"
            ))
            if current_index < len(bids) - 1:
                nav_buttons.append(InlineKeyboardButton("Следующий ▶️", callback_data="bid_next"))
            keyboard.append(nav_buttons)

        # Кнопки соцсетей (URL-кнопки)
        social_buttons = []
        if instagram_link:
            social_buttons.append(InlineKeyboardButton("📸 Instagram", url=instagram_link))
        if tiktok_link:
            social_buttons.append(InlineKeyboardButton("🎵 TikTok", url=tiktok_link))
        if youtube_link:
            social_buttons.append(InlineKeyboardButton("📺 YouTube", url=youtube_link))
        if telegram_link:
            social_buttons.append(InlineKeyboardButton("✈️ Telegram", url=telegram_link))

        # Добавляем кнопки соцсетей по 2 в ряд
        for i in range(0, len(social_buttons), 2):
            keyboard.append(social_buttons[i:i+2])

        # Кнопка выбора блогера
        keyboard.append([InlineKeyboardButton(
            "✅ Выбрать",
            callback_data=f"select_blogger_{offer['id']}"
        )])

        # Кнопка отказа от блогера
        keyboard.append([InlineKeyboardButton(
            "❌ Отказаться",
            callback_data=f"reject_blogger_{offer['id']}"
        )])

        # Кнопка просмотра профиля блогера
        keyboard.append([InlineKeyboardButton(
            "👤 Профиль",
            callback_data=f"view_blogger_profile_{offer['blogger_id']}"
        )])

        # Кнопка просмотра портфолио (если есть фото)
        portfolio_photos = offer.get('blogger_portfolio_photos', '')
        if portfolio_photos:
            keyboard.append([InlineKeyboardButton(
                "📸 Портфолио",
                callback_data=f"view_blogger_portfolio_{offer['blogger_id']}"
            )])

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="client_my_orders")])

        # Отправляем с фото профиля блогера, если есть
        profile_photo = offer.get('blogger_profile_photo', '')
        portfolio_photos_list = [p.strip() for p in portfolio_photos.split(',') if p.strip()] if portfolio_photos else []

        photo_to_show = profile_photo if profile_photo else (portfolio_photos_list[0] if portfolio_photos_list else None)

        # Всегда удаляем старое сообщение и отправляем новое
        # (чтобы избежать ошибки при переключении между сообщениями с фото и без)
        try:
            await query.message.delete()
        except:
            pass

        if photo_to_show:
            try:
                await context.bot.send_photo(
                    chat_id=query.from_user.id,
                    photo=photo_to_show,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as photo_error:
                # Если не удалось отправить фото, отправляем без фото
                logger.warning(f"Не удалось отправить фото предложения: {photo_error}")
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            # Нет фото - отправляем текстовое сообщение
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logger.error(f"Ошибка в show_offer_card: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")]]
        # Сообщение могло быть удалено, поэтому используем send_message вместо edit
        try:
            await query.message.delete()
        except:
            pass
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=f"❌ Ошибка при отображении предложения:\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def offer_navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация между откликами"""
    query = update.callback_query
    await query.answer()

    try:
        bid_data = context.user_data.get('viewing_bids')
        if not bid_data:
            await query.edit_message_text("❌ Ошибка: данные откликов не найдены.")
            return

        bids = bid_data['bids']
        current_index = bid_data['current_index']

        if "prev" in query.data:
            current_index = max(0, current_index - 1)
        elif "next" in query.data:
            current_index = min(len(bids) - 1, current_index + 1)

        context.user_data['viewing_bids']['current_index'] = current_index

        await show_offer_card(update, context, query=query)

    except Exception as e:
        logger.error(f"Ошибка в bid_navigate: {e}", exc_info=True)


async def reject_blogger_from_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отказ от блогера - отклоняет предложение и показывает следующего"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем offer_id из callback_data
        offer_id = int(query.data.replace("reject_blogger_", ""))

        # Получаем данные о текущих откликах
        bid_data = context.user_data.get('viewing_bids')
        if not bid_data:
            await query.answer("❌ Ошибка: данные не найдены", show_alert=True)
            return

        # Отклоняем предложение в БД
        db.update_bid_status(offer_id, 'rejected')
        logger.info(f"Предложение {offer_id} отклонено рекламодателем")

        # Удаляем отклонённый отклик из списка
        bids = bid_data['bids']
        current_index = bid_data['current_index']

        # Находим и удаляем отклонённый отклик
        bids = [b for b in bids if b['id'] != offer_id]
        bid_data['bids'] = bids

        # Если откликов больше нет
        if not bids:
            keyboard = [[InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")]]
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="✅ Блогер отклонён.\n\nБольше откликов на эту кампанию нет.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Корректируем индекс если нужно
        if current_index >= len(bids):
            current_index = len(bids) - 1
        bid_data['current_index'] = current_index

        # Показываем следующую карточку
        await show_offer_card(update, context, query=query)

    except Exception as e:
        logger.error(f"Ошибка в reject_blogger_from_offer: {e}", exc_info=True)
        await query.answer("❌ Ошибка при отклонении", show_alert=True)


async def view_blogger_profile_from_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр профиля блогера из карточки отклика"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем blogger_id из callback_data
        blogger_id = int(query.data.replace("view_blogger_profile_", ""))

        # Получаем профиль блогера
        blogger = db.get_worker_by_id(blogger_id)
        if not blogger:
            await query.answer("❌ Профиль блогера не найден", show_alert=True)
            return

        blogger_dict = dict(blogger)

        # Формируем текст профиля
        name = blogger_dict.get("name", "—")
        city = blogger_dict.get("city", "—")
        categories = blogger_dict.get("categories", "—")
        experience = blogger_dict.get("experience", "—")
        description = blogger_dict.get("description", "—")
        rating = blogger_dict.get("rating", 0)
        rating_count = blogger_dict.get("rating_count", 0)

        text = f"👤 <b>Профиль блогера</b>\n\n"
        text += f"<b>{name}</b>\n\n"

        # Рейтинг
        if rating > 0:
            stars = "⭐" * int(rating)
            text += f"{stars} {rating:.1f} ({rating_count} отзывов)\n\n"
        else:
            text += "⭐ Новый блогер (пока нет отзывов)\n\n"

        if city and city != "—":
            text += f"📍 <b>Город:</b> {city}\n"
        if categories and categories != "—":
            text += f"📱 <b>Тематика:</b> {categories}\n"
        if experience and experience != "—":
            text += f"📅 <b>Опыт:</b> {experience}\n"

        text += "\n"

        if description and description != "—":
            text += f"📝 <b>О себе:</b>\n{description}\n\n"

        # Социальные сети
        social_links = []
        if blogger_dict.get("instagram_link"):
            social_links.append(f"📸 Instagram: {blogger_dict['instagram_link']}")
        if blogger_dict.get("youtube_link"):
            social_links.append(f"🎬 YouTube: {blogger_dict['youtube_link']}")
        if blogger_dict.get("tiktok_link"):
            social_links.append(f"🎵 TikTok: {blogger_dict['tiktok_link']}")
        if blogger_dict.get("telegram_link"):
            social_links.append(f"✈️ Telegram: {blogger_dict['telegram_link']}")

        if social_links:
            text += "<b>Социальные сети:</b>\n"
            text += "\n".join(social_links) + "\n"

        # Кнопки
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад к отклику", callback_data="back_to_offer_card")]
        ]

        # Показываем с фото профиля, если есть
        profile_photo = blogger_dict.get("profile_photo", "")

        if profile_photo:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_photo(
                chat_id=query.from_user.id,
                photo=profile_photo,
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logger.error(f"Ошибка в view_blogger_profile_from_offer: {e}", exc_info=True)
        await query.answer("❌ Ошибка при загрузке профиля", show_alert=True)


async def back_to_offer_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к карточке предложения из просмотра портфолио"""
    query = update.callback_query
    await query.answer()

    try:
        # Проверяем, что у нас есть данные об откликах
        bid_data = context.user_data.get('viewing_bids')
        if not bid_data:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="❌ Ошибка: данные откликов не найдены. Вернитесь к списку заказов.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")
                ]])
            )
            return

        # Показываем текущую карточку предложения
        await show_offer_card(update, context, query=query)

    except Exception as e:
        logger.error(f"Ошибка в back_to_bid_card: {e}", exc_info=True)
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="❌ Произошла ошибка. Вернитесь к списку заказов.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ К моим заказам", callback_data="client_my_orders")
            ]])
        )


async def select_blogger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора блогера клиентом - сразу открывает чат"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем offer_id из callback_data
        offer_id = int(query.data.replace("select_blogger_", ""))

        # Сразу создаем чат и показываем рекомендации
        await process_offer_selection(update, context, offer_id)

    except Exception as e:
        logger.error(f"Ошибка в select_blogger: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Ошибка при выборе блогера:\n{str(e)}",
            parse_mode="HTML"
        )


async def pay_with_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплата через Telegram Stars"""
    query = update.callback_query
    await query.answer()

    try:
        offer_id = int(query.data.replace("pay_stars_", ""))

        # TODO: Интеграция с Telegram Stars Payment API
        # Здесь должна быть реальная интеграция с платежной системой Telegram Stars
        # На данный момент - заглушка для демонстрации

        text = (
            "⭐ <b>Оплата Telegram Stars</b>\n\n"
            "🚧 Функция оплаты через Telegram Stars находится в разработке.\n\n"
            "Для тестирования используйте кнопку ниже для имитации оплаты:"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Имитировать успешную оплату (тест)", callback_data=f"test_payment_success_{offer_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"select_blogger_{offer_id}")],
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в pay_with_stars: {e}", exc_info=True)


async def pay_with_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплата картой через внешний платежный сервис (MOCK для демонстрации)"""
    query = update.callback_query
    await query.answer()

    try:
        offer_id = int(query.data.replace("pay_card_", ""))

        # MOCK: В реальной системе здесь будет интеграция с BePaid/Stripe
        # Для демонстрации показываем реквизиты и кнопку подтверждения

        text = (
            "💳 <b>Оплата банковской картой</b>\n\n"
            "💰 <b>Сумма к оплате: 1.00 BYN</b>\n\n"
            "📋 <b>Реквизиты для оплаты:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💳 Карта: <code>4242 4242 4242 4242</code>\n"
            "👤 Получатель: <b>gde.reklama Belarus</b>\n"
            "📝 Назначение: <i>Доступ к контакту блогера</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ <b>ДЕМО-РЕЖИМ:</b> Это тестовая заглушка.\n"
            "В продакшн будет интеграция с:\n"
            "• <b>BePaid</b> (для клиентов из Беларуси)\n"
            "• <b>Stripe</b> (международные платежи)\n\n"
            "💡 Нажмите кнопку ниже для имитации оплаты:"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Я оплатил", callback_data=f"confirm_payment_{offer_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"select_blogger_{offer_id}")],
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в pay_with_card: {e}", exc_info=True)


async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Подтверждение оплаты клиентом (MOCK для демонстрации).
    В реальной системе здесь будет проверка статуса платежа через API платежного провайдера.
    """
    query = update.callback_query
    await query.answer("Проверяем оплату...")

    try:
        offer_id = int(query.data.replace("confirm_payment_", ""))

        # MOCK: Показываем процесс проверки
        await query.edit_message_text(
            "⏳ <b>Проверяем оплату...</b>\n\n"
            "Подождите, идет проверка платежа...",
            parse_mode="HTML"
        )

        # MOCK: В реальной системе здесь был бы запрос к платежному API
        # Например: payment_status = await check_payment_status(transaction_id)
        # Для демонстрации просто имитируем успешную оплату

        # Небольшая задержка для реалистичности (опционально)
        import asyncio
        await asyncio.sleep(1)

        # Показываем успешную оплату
        await query.edit_message_text(
            "✅ <b>Оплата подтверждена!</b>\n\n"
            "💳 Списано: <b>1.00 BYN</b>\n"
            "📄 ID транзакции: <code>MOCK-" + str(offer_id).zfill(6) + "</code>\n\n"
            "⏳ Открываем доступ к блогеру...",
            parse_mode="HTML"
        )

        # Еще небольшая задержка
        await asyncio.sleep(1)

        # Вызываем основную функцию успешной оплаты
        context.user_data['_payment_offer_id'] = offer_id
        await test_payment_success(update, context)

    except Exception as e:
        logger.error(f"Ошибка в confirm_payment: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ <b>Ошибка при проверке оплаты</b>\n\n"
            f"Произошла ошибка: {str(e)}\n\n"
            "Попробуйте еще раз или обратитесь в поддержку.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Попробовать еще раз", callback_data=f"pay_card_{offer_id}"),
                InlineKeyboardButton("💼 Главное меню", callback_data="show_client_menu")
            ]])
        )


async def process_offer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, offer_id: int):
    """
    Общая функция для обработки выбора блогера.
    Создает чат и отправляет рекомендации по общению.
    """
    query = update.callback_query

    try:
        # Получаем информацию об предложение
        # Сначала пытаемся получить из context.user_data, если нет - из базы данных
        bids = context.user_data.get('viewing_bids', {}).get('bids', [])
        selected_bid = None
        for offer in bids:
            if offer['id'] == offer_id:
                selected_bid = offer
                break

        # Если не нашли в context.user_data, получаем из базы данных
        if not selected_bid:
            bid_from_db = db.get_bid_by_id(offer_id)
            if bid_from_db:
                selected_bid = dict(bid_from_db)
            else:
                await safe_edit_message(query, "❌ Ошибка: предложение не найдено.", parse_mode="HTML")
                return

        campaign_id = selected_bid['campaign_id']
        blogger_id = selected_bid.get('blogger_id') or selected_bid.get('worker_id')
        blogger_name = selected_bid['blogger_name']
        blogger_telegram_id = selected_bid.get('blogger_telegram_id')

        # Получаем информацию о клиенте
        user = db.get_user(query.from_user.id)
        if not user:
            await safe_edit_message(query, "❌ Ошибка: пользователь не найден.", parse_mode="HTML")
            return

        client_profile = db.get_client_profile(user["id"])
        if not client_profile:
            await safe_edit_message(query, "❌ Ошибка: профиль клиента не найден.", parse_mode="HTML")
            return

        # 1. Получаем blogger_user_id (из таблицы bloggers поле user_id)
        blogger_profile = db.get_worker_by_id(blogger_id)
        if not blogger_profile:
            await safe_edit_message(query, "❌ Ошибка: профиль блогера не найден.", parse_mode="HTML")
            return

        blogger_user_id = blogger_profile['user_id']

        # 2. Проверяем существует ли уже чат
        existing_chat = db.get_chat_by_order_and_bid(campaign_id, offer_id)

        if existing_chat:
            chat_id = existing_chat['id']
            logger.info(f"Чат #{chat_id} уже существует, используем его")
        else:
            # Создаём новый чат
            chat_id = db.create_chat(
                campaign_id=campaign_id,
                advertiser_user_id=user["id"],
                blogger_user_id=blogger_user_id,
                offer_id=offer_id
            )
            logger.info(f"✅ Чат #{chat_id} создан между рекламодателем {user['id']} и блогером {blogger_user_id}")

        # 3. Отмечаем предложение как выбранное
        # Кампания остается открытой - рекламодатель может выбрать нескольких блогеров
        db.select_bid(offer_id)

        # 4. Уведомляем блогера что его выбрали и открыт чат
        if blogger_telegram_id:
            try:
                # Получаем данные рекламодателя для показа контактов
                advertiser_name = client_profile.get('name', 'Рекламодатель') if client_profile else 'Рекламодатель'
                advertiser_phone = client_profile.get('phone', '') if client_profile else ''
                advertiser_telegram_id = query.from_user.id

                # Формируем текст с контактами
                advertiser_contacts = ""
                if advertiser_telegram_id:
                    advertiser_contacts += f"• Telegram: <a href='tg://user?id={advertiser_telegram_id}'>Открыть профиль</a>\n"
                if advertiser_phone:
                    advertiser_contacts += f"• Телефон: {advertiser_phone}\n"

                if not advertiser_contacts:
                    advertiser_contacts = "• Контакты не указаны\n"

                keyboard_for_blogger = []
                # Кнопка для связи в Telegram
                if advertiser_telegram_id:
                    keyboard_for_blogger.append([InlineKeyboardButton(
                        "📱 Написать в Telegram",
                        url=f"tg://user?id={advertiser_telegram_id}"
                    )])
                keyboard_for_blogger.append([InlineKeyboardButton("💬 Писать в боте", callback_data=f"open_chat_{chat_id}")])

                await context.bot.send_message(
                    chat_id=blogger_telegram_id,
                    text=(
                        f"🎉 <b>Ваш отклик выбран!</b>\n\n"
                        f"Рекламодатель <b>{advertiser_name}</b> выбрал вас для кампании #{campaign_id}\n\n"
                        f"📱 <b>Контакты рекламодателя:</b>\n"
                        f"{advertiser_contacts}\n"
                        f"💬 <b>Выберите способ связи:</b>\n"
                        f"• <b>Написать в Telegram</b> — откроется личный чат с рекламодателем\n"
                        f"• <b>Писать в боте</b> — общение через нашу платформу\n\n"
                        f"⚠️ <b>ВАЖНО:</b> Ответьте в течение 24 часов!"
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard_for_blogger)
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления блогеру: {e}")

        # 5. Показываем рекламодателю экран выбора способа связи
        # Получаем контактные данные блогера
        blogger_phone = selected_bid.get('blogger_phone', '')
        blogger_telegram_link = selected_bid.get('blogger_telegram_link', '')

        # Формируем блок с контактами
        contacts_text = ""
        if blogger_telegram_id:
            contacts_text += f"• Telegram: <a href='tg://user?id={blogger_telegram_id}'>Открыть профиль</a>\n"
        if blogger_telegram_link:
            contacts_text += f"• Telegram канал: {blogger_telegram_link}\n"
        if blogger_phone:
            contacts_text += f"• Телефон: {blogger_phone}\n"

        # Добавляем ссылки на соцсети
        instagram_link = selected_bid.get('blogger_instagram_link', '')
        tiktok_link = selected_bid.get('blogger_tiktok_link', '')
        youtube_link = selected_bid.get('blogger_youtube_link', '')

        if instagram_link:
            contacts_text += f"• Instagram: {instagram_link}\n"
        if tiktok_link:
            contacts_text += f"• TikTok: {tiktok_link}\n"
        if youtube_link:
            contacts_text += f"• YouTube: {youtube_link}\n"

        if not contacts_text:
            contacts_text = "• Контакты не указаны\n"

        text = (
            f"✅ <b>Блогер выбран!</b>\n\n"
            f"👤 <b>{blogger_name}</b>\n\n"
            f"📱 <b>Контакты для связи:</b>\n"
            f"{contacts_text}\n"
            f"💬 <b>Выберите способ связи:</b>\n"
            f"• <b>Написать в Telegram</b> — откроется личный чат с блогером\n"
            f"• <b>Писать в боте</b> — общение через нашу платформу\n\n"
            f"⚠️ <i>Сделка уже открыта! Любой способ связи засчитывается как начало работы.</i>"
        )

        keyboard = []

        # Кнопка "Написать в Telegram" - URL кнопка
        if blogger_telegram_id:
            keyboard.append([InlineKeyboardButton(
                "📱 Написать в Telegram",
                url=f"tg://user?id={blogger_telegram_id}"
            )])

        # Кнопка "Писать в боте" - внутренний чат
        keyboard.append([InlineKeyboardButton("💬 Писать в боте", callback_data=f"open_chat_{chat_id}")])
        keyboard.append([InlineKeyboardButton("📂 Мои кампании", callback_data="client_my_orders")])
        keyboard.append([InlineKeyboardButton("💼 Главное меню", callback_data="show_client_menu")])

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в process_offer_selection: {e}", exc_info=True)
        await safe_edit_message(
            query,
            "❌ Произошла ошибка. Попробуйте ещё раз.",
            parse_mode="HTML"
        )


async def thank_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    💝 Обработчик кнопки "Сказать спасибо платформе"

    На данный момент работает бесплатно - просто создаёт чат между клиентом и мастером.
    В будущем (при 10-20k пользователей) здесь будет реальная оплата через Telegram Stars.
    Цель: приучить пользователей к действию "поблагодарить/оплатить" перед получением контакта.
    """
    query = update.callback_query
    await query.answer("💝 Спасибо за поддержку!")

    try:
        offer_id = int(query.data.replace("thank_platform_", ""))
        # ИСПРАВЛЕНО: Вызываем общую функцию напрямую с offer_id
        await process_offer_selection(update, context, offer_id)

    except Exception as e:
        logger.error(f"Ошибка в thank_platform: {e}", exc_info=True)
        await safe_edit_message(
            query,
            "❌ Произошла ошибка. Попробуйте ещё раз.",
            parse_mode="HTML"
        )


async def test_payment_success(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    🆓 БЕСПЛАТНЫЙ РЕЖИМ: Обрабатывает выбор блогера БЕЗ оплаты (до достижения 10-20k пользователей)

    Раньше была тестовой функцией для имитации оплаты, теперь используется как основной обработчик
    в бесплатном режиме. Создаёт чат между клиентом и мастером напрямую без платежей.
    """
    query = update.callback_query
    # Не вызываем answer() здесь, т.к. уже вызван в thank_platform
    if not query.message:
        await query.answer()

    try:
        if '_payment_offer_id' in context.user_data:
            offer_id = context.user_data.pop('_payment_offer_id')
        else:
            offer_id = int(query.data.replace("test_payment_success_", ""))
        # ИСПРАВЛЕНО: Вызываем общую функцию process_offer_selection
        await process_offer_selection(update, context, offer_id)

        # Очищаем контекст просмотра откликов
        if 'viewing_bids' in context.user_data:
            del context.user_data['viewing_bids']

    except Exception as e:
        logger.error(f"Ошибка в test_payment_success: {e}", exc_info=True)
        await safe_edit_message(
            query,
            f"❌ Ошибка при обработке оплаты:\n{str(e)}",
            parse_mode="HTML"
        )


# ============================================
# СИСТЕМА ЧАТОВ
# ============================================

async def open_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает чат между клиентом и мастером"""
    query = update.callback_query
    await query.answer()

    try:
        chat_id = int(query.data.replace("open_chat_", ""))

        # Получаем информацию о чате
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            await query.edit_message_text("❌ Чат не найден.")
            return

        chat_dict = dict(chat)

        # Проверяем что пользователь участник этого чата
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Пользователь не найден.")
            return

        user_dict = dict(user)
        is_client = user_dict['id'] == chat_dict['advertiser_user_id']
        is_worker = user_dict['id'] == chat_dict['blogger_user_id']

        if not is_client and not is_worker:
            await query.edit_message_text("❌ У вас нет доступа к этому чату.")
            return

        # Определяем роль пользователя
        my_role = "advertiser" if is_client else "blogger"
        other_role = "blogger" if is_client else "advertiser"

        # Получаем информацию о собеседнике
        if is_client:
            blogger = db.get_user_by_id(chat_dict['blogger_user_id'])
            if blogger:
                blogger = dict(blogger)
                worker_profile = db.get_worker_profile(blogger['id'])
                if worker_profile:
                    worker_profile = dict(worker_profile)
                    other_name = worker_profile['name']
                else:
                    other_name = "Блогер"
            else:
                other_name = "Блогер"
        else:
            advertiser = db.get_user_by_id(chat_dict['advertiser_user_id'])
            if advertiser:
                advertiser = dict(advertiser)
                client_profile = db.get_client_profile(advertiser['id'])
                if client_profile:
                    client_profile = dict(client_profile)
                    other_name = client_profile['name']
                else:
                    other_name = "Клиент"
            else:
                other_name = "Клиент"

        # Получаем последние сообщения (увеличен лимит для показа всей истории)
        messages = db.get_chat_messages(chat_id, limit=100)
        messages_list = list(reversed(messages))  # Старые сверху, новые снизу

        # Отмечаем сообщения как прочитанные
        db.mark_messages_as_read(chat_id, user_dict['id'])

        # Формируем текст чата
        text = f"💬 <b>Чат с {other_name}</b>\n"
        text += f"📋 Кампания #{chat_dict['campaign_id']}\n\n"

        if messages_list:
            text += "<b>История сообщений:</b>\n\n"
            for msg in messages_list:
                msg_dict = dict(msg)
                sender_role = msg_dict['sender_role']
                message_text = msg_dict['message_text']

                # PostgreSQL возвращает datetime объект, SQLite возвращает строку
                created_at_raw = msg_dict['created_at']
                if isinstance(created_at_raw, str):
                    created_at = created_at_raw[:16]  # Обрезаем до минут
                else:
                    # datetime объект - форматируем
                    created_at = created_at_raw.strftime('%Y-%m-%d %H:%M')

                if sender_role == my_role:
                    text += f"<b>Вы:</b> {message_text}\n"
                else:
                    text += f"<b>{other_name}:</b> {message_text}\n"
                text += f"<i>{created_at}</i>\n\n"
        else:
            text += "<i>Пока нет сообщений</i>\n\n"

        text += "💡 Напишите сообщение для отправки в чат:"

        # ИСПРАВЛЕНО: Сохраняем активный чат в БД вместо user_data
        # Это решает проблему потери состояния при перезапуске бота
        db.set_active_chat(query.from_user.id, chat_id, my_role)

        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"open_chat_{chat_id}")],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="show_client_menu" if is_client else "show_worker_menu"),
                InlineKeyboardButton("💼 Главное меню", callback_data="show_client_menu" if is_client else "show_worker_menu")
            ],
        ]

        await safe_edit_message(
            query,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в open_chat: {e}", exc_info=True)
        await safe_edit_message(query, f"❌ Ошибка при открытии чата:\n{str(e)}")


async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сообщения, отправленные в активный чат"""
    logger.info(f"[DEBUG] handle_chat_message вызван для пользователя {update.effective_user.id}, текст: {update.message.text[:50] if update.message and update.message.text else 'N/A'}")
    logger.info(f"[DEBUG] context.user_data: suggestion_active={context.user_data.get('suggestion_active')}, broadcast_active={context.user_data.get('broadcast_active')}, ad_step={context.user_data.get('ad_step')}")

    # FIX B: Прямая маршрутизация для гарантированной работы ConversationHandler
    # (это резервная проверка, основная обработка в direct_routing group=-1)
    if context.user_data.get("suggestion_active"):
        logger.info(f"[FIX B] Прямая маршрутизация в receive_suggestion_text")
        return await receive_suggestion_text(update, context)

    if context.user_data.get("broadcast_active"):
        logger.info(f"[FIX B] Прямая маршрутизация в admin_broadcast_send")
        return await admin_broadcast_send(update, context)

    # Если пользователь в процессе создания рекламы - пропускаем, дать ConversationHandler обработать
    if context.user_data.get('ad_step'):
        logger.info(f"[FIX B] Пользователь в процессе создания рекламы, пропускаем")
        return  # Пропускаем, уже обработано в direct_routing
    if context.user_data.get('ad_step'):
        logger.info(f"[FIX B] Пользователь в процессе создания рекламы, пропускаем")
        return  # Пропускаем, уже обработано в direct_routing
    if context.user_data.get('ad_step'):
        logger.info(f"[FIX B] Пользователь в процессе создания рекламы, пропускаем")
        return  # Пропускаем, уже обработано в direct_routing

    # КРИТИЧНО: Проверяем, не находится ли пользователь в ConversationHandler
    # Если находится - пропускаем, чтобы ConversationHandler обработал сообщение
    conversation_keys = ['review_order_id', 'review_bid_id', 'review_rating',
                        'adding_photos', 'bid_order_id',
                        'uploading_work_photo_order_id', 'order_client_id']
    if any(key in context.user_data for key in conversation_keys):
        # Пользователь в ConversationHandler, пропускаем
        logger.info(f"[DEBUG] handle_chat_message: пользователь в ConversationHandler, пропускаем")
        return

    # ИСПРАВЛЕНО: Получаем активный чат из БД вместо user_data
    # Это решает проблему потери состояния при перезапуске бота
    active_chat = db.get_active_chat(update.effective_user.id)

    if not active_chat:
        # Нет активного чата, пропускаем
        logger.info(f"[DEBUG] handle_chat_message: нет активного чата для пользователя {update.effective_user.id}, пропускаем")
        return

    chat_id = active_chat['chat_id']
    my_role = active_chat['role']

    message_text = update.message.text

    if not message_text:
        return

    try:
        # Получаем информацию о пользователе
        user = db.get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text("❌ Пользователь не найден.")
            return

        user_dict = dict(user)

        # Отправляем сообщение в чат
        message_id = db.send_message(chat_id, user_dict['id'], my_role, message_text)

        logger.info(f"✅ Сообщение #{message_id} отправлено в чат #{chat_id} от {my_role}")

        # Если это первое сообщение блогера - подтверждаем готовность
        if my_role == "blogger" and not db.is_worker_confirmed(chat_id):
            db.confirm_worker_in_chat(chat_id)
            logger.info(f"✅ Блогер подтвердил готовность в чате #{chat_id}")

            # НОВАЯ ЛОГИКА: Кампания остаётся открытой для множественного выбора блогеров
            # Статус не меняется, заказчик может продолжать выбирать других блогеров
            # chat = db.get_chat_by_id(chat_id)
            # if chat:
            #     db.update_order_status(chat['campaign_id'], "master_confirmed")
            #     logger.info(f"✅ Кампания #{chat['campaign_id']} переведён в статус 'master_confirmed'")

        # Получаем информацию о чате для уведомления
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            await update.message.reply_text("❌ Чат не найден.")
            return

        chat_dict = dict(chat)

        # Уведомляем собеседника о новом сообщении
        other_user_id = chat_dict['blogger_user_id'] if my_role == "advertiser" else chat_dict['advertiser_user_id']
        other_user = db.get_user_by_id(other_user_id)

        if other_user:
            other_user_dict = dict(other_user)

            # ИСПРАВЛЕНО: Проверяем статус кампания - не уведомляем о сообщениях в завершенных заказах
            campaign = db.get_order_by_id(chat_dict['campaign_id'])
            should_notify = False

            if campaign:
                campaign_dict = dict(campaign)
                order_status = campaign_dict.get('status', 'open')
                # Уведомляем только для активных заказов (НЕ завершенных)
                if order_status in ['open', 'waiting_master_confirmation', 'master_confirmed', 'in_progress']:
                    should_notify = True
                else:
                    logger.info(f"Кампания #{chat_dict['campaign_id']} имеет статус '{order_status}' - пропускаем уведомление о сообщении")

            if should_notify:
                try:
                    # Определяем кнопку для возврата в кампании (в зависимости от роли получателя)
                    other_user_id = other_user_dict['id']
                    is_client = db.get_client_profile(other_user_id) is not None
                    orders_callback = "client_my_orders" if is_client else "worker_my_orders"

                    # ОБНОВЛЯЕМОЕ уведомление - одно сообщение на пользователя
                    notification_text = (
                        f"💬 <b>У вас есть новые сообщения!</b>\n\n"
                        f"Откройте \"Мои кампании\" чтобы прочитать сообщения"
                    )

                    keyboard = [[InlineKeyboardButton("📂 Мои кампании", callback_data=orders_callback)]]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    # Получаем существующее уведомление
                    existing_notification = db.get_chat_message_notification(other_user_id)

                    try:
                        if existing_notification and existing_notification['notification_message_id']:
                            # Пытаемся РЕДАКТИРОВАТЬ существующее сообщение
                            await context.bot.edit_message_text(
                                chat_id=existing_notification['notification_chat_id'],
                                message_id=existing_notification['notification_message_id'],
                                text=notification_text,
                                reply_markup=reply_markup,
                                parse_mode="HTML"
                            )
                            # Обновляем timestamp
                            db.save_chat_message_notification(
                                other_user_id,
                                existing_notification['notification_message_id'],
                                existing_notification['notification_chat_id']
                            )
                            logger.info(f"✅ Обновлено уведомление о сообщении для пользователя {other_user_id}")
                        else:
                            # Сообщения нет - отправляем НОВОЕ
                            raise Exception("No existing notification")

                    except Exception as edit_error:
                        # Не удалось отредактировать (сообщение удалено или не существует) - отправляем новое
                        logger.info(f"Отправка нового уведомления о сообщении для пользователя {other_user_id}: {edit_error}")
                        msg = await context.bot.send_message(
                            chat_id=other_user_dict['telegram_id'],
                            text=notification_text,
                            reply_markup=reply_markup,
                            parse_mode="HTML"
                        )
                        # Сохраняем message_id для будущих обновлений
                        db.save_chat_message_notification(other_user_id, msg.message_id, other_user_dict['telegram_id'])
                        logger.info(f"✅ Отправлено новое уведомление о сообщении пользователю {other_user_id}")

                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления: {e}")

        # Определяем меню для возврата
        menu_callback = "show_client_menu" if my_role == "advertiser" else "show_worker_menu"

        # Подтверждаем отправку
        await update.message.reply_text(
            "✅ Сообщение отправлено!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить чат", callback_data=f"open_chat_{chat_id}")],
                [
                    InlineKeyboardButton("⬅️ Назад", callback_data=menu_callback),
                    InlineKeyboardButton("💼 Главное меню", callback_data=menu_callback)
                ]
            ])
        )

    except Exception as e:
        logger.error(f"Ошибка в handle_chat_message: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка при отправке сообщения:\n{str(e)}")


# ------- СЛУЖЕБНЫЕ -------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ИСПРАВЛЕНО: Полная отмена любого активного диалога с возвратом в главное меню.
    """
    context.user_data.clear()

    keyboard = [[InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")]]

    await update.message.reply_text(
        "❌ Действие отменено.\n\n"
        "Возвращаемся в главное меню...",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END


async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик для заглушек (noop) - кнопки которые ничего не делают.
    Необходим чтобы не было эффекта "зависания" когда пользователь нажимает такую кнопку.
    """
    query = update.callback_query
    await query.answer()


async def cancel_edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отмена редактирования профиля с возвратом к профилю блогера.
    """
    context.user_data.clear()

    keyboard = [[InlineKeyboardButton("👤 Вернуться к профилю", callback_data="worker_profile")]]

    await update.message.reply_text(
        "❌ Действие отменено.\n\n"
        "Возвращаемся к профилю...",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END


async def cancel_from_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРИТИЧЕСКИ ВАЖНО: Обработка /start во время ConversationHandler.

    Позволяет пользователю выйти из застрявшего диалога.
    """
    context.user_data.clear()
    logger.info(f"User {update.effective_user.id} cancelled conversation via /start")

    # Вызываем обычный start_command для показа меню
    return await start_command(update, context)


async def cancel_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРИТИЧЕСКИ ВАЖНО: Обработка кнопок меню во время ConversationHandler.

    Позволяет пользователю выйти из застрявшего диалога через кнопки меню.
    Исправляет баг, когда бот зависал после ошибки при загрузке фото.
    """
    query = update.callback_query
    await query.answer()

    context.user_data.clear()
    logger.info(f"User {query.from_user.id} cancelled conversation via callback: {query.data}")

    # Перенаправляем на соответствующий обработчик меню
    if query.data == "go_main_menu":
        return await go_main_menu(update, context)
    elif query.data == "show_worker_menu":
        return await show_blogger_menu(update, context)
    elif query.data == "show_client_menu":
        return await show_advertiser_menu(update, context)

    # По умолчанию возвращаемся в главное меню
    return await go_main_menu(update, context)


async def cancel_from_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена через команду /cancel"""
    context.user_data.clear()
    logger.info(f"User {update.effective_user.id} cancelled conversation via /cancel command")

    await update.message.reply_text(
        "❌ Действие отменено.\n\n"
        "Отправьте /start для возврата в главное меню."
    )

    return ConversationHandler.END


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Команда не распознана. Используйте /start.")


async def handle_invalid_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "Не вижу тут ожидаемого ответа. Попробуйте ещё раз или введите /start."
        )
    elif update.callback_query:
        await update.callback_query.answer("Неверное действие. Используйте /start для начала.")


async def reset_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для полной очистки профиля пользователя из базы данных"""
    telegram_id = update.effective_user.id
    
    success = db.delete_user_profile(telegram_id)
    
    if success:
        await update.message.reply_text(
            "✅ Ваш профиль успешно удалён из базы данных.\n\n"
            "Теперь вы можете зарегистрироваться заново, используя команду /start"
        )
    else:
        await update.message.reply_text(
            "⚠️ Профиль не найден или уже удалён.\n\n"
            "Используйте /start для регистрации."
        )


async def add_test_campaigns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления тестовых заказов (только для администраторов)"""
    telegram_id = update.effective_user.id
    logger.info(f"[CMD] /add_test_campaigns вызван от пользователя {telegram_id}")

    # Проверка прав администратора
    if not db.is_admin(telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    # Вызываем функцию из db.py
    success, message, count = db.add_test_orders(telegram_id)

    await update.message.reply_text(message)


async def add_test_bloggers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления тестовых блогеров (только для администраторов)"""
    telegram_id = update.effective_user.id
    logger.info(f"[CMD] /add_test_bloggers вызван от пользователя {telegram_id}")

    # Проверка прав администратора
    if not db.is_admin(telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    # Вызываем функцию из db.py
    success, message, count = db.add_test_workers(telegram_id)

    await update.message.reply_text(message)


async def add_test_advertisers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления тестовых рекламодателей (только для администраторов)"""
    telegram_id = update.effective_user.id
    logger.info(f"[CMD] /add_test_advertisers вызван от пользователя {telegram_id}")

    # Проверка прав администратора
    if not db.is_admin(telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    # Вызываем функцию из db.py
    success, message, count = db.add_test_advertisers(telegram_id)

    await update.message.reply_text(message)


async def add_test_offers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда для добавления тестовых откликов на кампанию
    Использование: /add_test_offers campaign_id
    """
    telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "📋 <b>Использование команды /add_test_offers</b>\n\n"
            "<code>/add_test_offers campaign_id</code>\n\n"
            "Пример:\n"
            "<code>/add_test_offers 123</code>\n\n"
            "Эта команда добавит несколько тестовых откликов от блогеров на указанную кампанию.",
            parse_mode="HTML"
        )
        return

    try:
        campaign_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID кампании должен быть числом")
        return

    # Проверяем существование кампании
    campaign = db.get_order(campaign_id)
    if not campaign:
        await update.message.reply_text(f"❌ Кампания с ID {campaign_id} не найдена")
        return

    # Получаем всех мастеров
    all_workers = db.get_all_workers()
    if not all_workers or len(all_workers) == 0:
        await update.message.reply_text(
            "❌ В системе нет блогеров.\n\n"
            "Сначала создайте профили блогеров или используйте команду /add_test_bloggers"
        )
        return

    # Создаем отклики от первых 5 мастеров (или меньше, если мастеров мало)
    workers_to_use = list(all_workers)[:5]
    created_count = 0

    base_price = 100
    comments = [
        "Готов выполнить качественно и в срок!",
        "Большой опыт создания контента, есть примеры",
        "Сделаю быстро и недорого",
        "Работаю с гарантией качества",
        "Могу приступить уже сегодня"
    ]

    for i, blogger in enumerate(workers_to_use):
        worker_dict = dict(blogger)
        worker_id = worker_dict['id']

        # Генерируем разные цены
        price = base_price + (i * 50)  # 100, 150, 200, 250, 300
        comment = comments[i % len(comments)]
        ready_days = 3 + i  # 3, 4, 5, 6, 7 дней

        try:
            # Проверяем, не откликался ли уже этот блогер
            # ИСПРАВЛЕНО: используем worker_id (ID профиля блогера), а не worker_dict['user_id']
            if db.check_worker_bid_exists(campaign_id, worker_id):
                continue

            # Создаем предложение (обходим rate limiting через прямую вставку в БД)
            with db.get_db_connection() as conn:
                cursor = db.get_cursor(conn)
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                cursor.execute("""
                    INSERT INTO bids (
                        campaign_id, worker_id, proposed_price, currency,
                        comment, ready_in_days, created_at, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                """, (campaign_id, worker_id, price, 'BYN', comment, ready_days, now))

                conn.commit()
                created_count += 1
                logger.info(f"✅ Создано тестовое предложение от блогера {worker_id} на кампанию {campaign_id}")

        except Exception as e:
            logger.error(f"Ошибка создания тестового предложения: {e}")
            continue

    if created_count > 0:
        await update.message.reply_text(
            f"✅ Создано тестовых откликов: {created_count}\n\n"
            f"📋 Кампания ID: {campaign_id}\n"
            f"Откликов добавлено: {created_count}\n\n"
            "Теперь вы можете проверить сортировку откликов!",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            f"⚠️ Не удалось создать отклики.\n\n"
            f"Возможные причины:\n"
            f"• Все блогера уже откликнулись на эту кампанию\n"
            f"• Произошла ошибка при создании",
            parse_mode="HTML"
        )


# ------- ПРОСМОТР ЗАКАЗОВ ДЛЯ МАСТЕРОВ -------

async def blogger_view_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр доступных заказов для блогера"""
    query = update.callback_query
    await query.answer()

    try:
        # Получаем профиль блогера
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Ошибка: пользователь не найден.")
            return

        # НОВОЕ: Обнуляем счётчик непрочитанных кампаний (пользователь их просматривает)
        db.save_worker_notification(user['id'], None, None, 0)

        worker_profile = db.get_worker_profile(user["id"])
        if not worker_profile:
            await query.edit_message_text("❌ Ошибка: профиль блогера не найден.")
            return
        
        worker_dict = dict(worker_profile)
        worker_id = worker_dict['id']
        categories = (worker_dict.get("categories") or "").split(", ")

        # ИСПРАВЛЕНО: Один запрос для всех категорий вместо N запросов
        # ИСПРАВЛЕНО: Фильтрация по городам блогера (worker_id)
        # Раньше: 5 категорий = 5 SQL запросов, блогер видел кампании из ВСЕХ городов
        # Теперь: 5 категорий = 1 SQL запрос, блогер видит кампании ТОЛЬКО из своих городов
        all_orders = db.get_orders_by_categories(categories, per_page=10000, blogger_id=worker_id)
        all_orders = [dict(campaign) for campaign in all_orders]

        # Фильтруем кампании - не показываем те, на которые блогер уже откликнулся
        # НОВОЕ: Также не показываем кампании, от которых блогер отказался
        # ИСПРАВЛЕНО: Используем worker_id (ID профиля блогера), а не user["id"] (ID пользователя)
        all_orders = [campaign for campaign in all_orders
                     if not db.check_worker_bid_exists(campaign['id'], worker_id)
                     and not db.check_order_declined(user["id"], campaign['id'])]
        
        if not all_orders:
            keyboard = [
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")],
            ]
            
            await query.edit_message_text(
                "📋 <b>Доступные кампании</b>\n\n"
                "Пока нет открытых заказов по вашим категориям.\n\n"
                "Как только появятся новые кампании, вы их увидите здесь!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # Показываем список заказов
        orders_text = "📋 <b>Доступные кампании</b>\n\n"
        orders_text += f"Найдено заказов: <b>{len(all_orders)}</b>\n\n"
        
        # Показываем первые 5 заказов
        keyboard = []
        for i, campaign in enumerate(all_orders[:5], 1):
            orders_text += f"🟢 <b>Кампания #{campaign['id']}</b>\n"
            orders_text += f"📍 Город: {campaign.get('city', 'Не указан')}\n"

            # ИСПРАВЛЕНО: Показываем payment_type и budget для корректного отображения оплаты
            payment_type = campaign.get('payment_type', 'paid')
            budget_type = campaign.get('budget_type', 'none')
            budget_value = campaign.get('budget_value', 0)

            # Формируем строку оплаты
            payment_parts = []

            # Если есть денежная оплата (paid или both)
            if payment_type in ['paid', 'both']:
                if budget_value and budget_value > 0:
                    if budget_type == 'fixed':
                        payment_parts.append(f"💰 {int(budget_value)} BYN")
                    elif budget_type == 'flexible':
                        payment_parts.append(f"💰 до {int(budget_value)} BYN (гибкая)")
                    else:
                        payment_parts.append(f"💰 {int(budget_value)} BYN")
                elif budget_type == 'flexible':
                    payment_parts.append("💬 Блогеры предложат цену")

            # Если есть бартер
            if payment_type in ['barter', 'both']:
                payment_parts.append("🤝 Бартер")

            # Показываем оплату
            if payment_parts:
                orders_text += f"<b>Оплата:</b> {' + '.join(payment_parts)}\n"
            else:
                orders_text += f"<b>Оплата:</b> По договорённости\n"

            # НОВОЕ: Показываем описание (это главное!)
            description = campaign.get('description', '')
            if description:
                # Обрезаем описание до 150 символов для краткости
                short_desc = description[:150] + "..." if len(description) > 150 else description
                orders_text += f"📝 <b>Описание:</b> {short_desc}\n"

            orders_text += "\n"
            
            # Добавляем кнопку для просмотра деталей
            keyboard.append([InlineKeyboardButton(
                f"👁 Кампания #{campaign['id']} - Подробнее", 
                callback_data=f"view_order_{campaign['id']}"
            )])
        
        if len(all_orders) > 5:
            orders_text += f"<i>... и ещё {len(all_orders) - 5} заказов</i>\n\n"

        keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")])

        await safe_edit_message(
            query,
            orders_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка при просмотре заказов: {e}", exc_info=True)
        await safe_edit_message(
            query,
            "❌ Произошла ошибка при загрузке заказов.\n\n"
            "Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_worker_menu")]
            ])
        )


async def blogger_view_campaign_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный просмотр кампания мастером"""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass  # query уже отвечен если вызвано из другого handler-а

    try:
        # Извлекаем campaign_id из callback_data или из user_data (если вызвано из decline_no)
        if '_view_campaign_id' in context.user_data:
            campaign_id = context.user_data.pop('_view_campaign_id')
        else:
            campaign_id = int(query.data.replace("view_order_", ""))

        # Получаем кампанию
        campaign = db.get_order_by_id(campaign_id)
        if not campaign:
            await query.edit_message_text("❌ Кампания не найдена.")
            return
        
        campaign_dict = dict(campaign)
        
        # Проверяем есть ли уже предложение от этого блогера
        user = db.get_user(query.from_user.id)
        worker_profile = db.get_worker_profile(user["id"])

        already_bid = db.check_worker_bid_exists(campaign_id, worker_profile["id"])

        # ПРОВЕРКА: Блогер не может откликаться на свою кампанию
        advertiser = db.get_client_by_id(campaign_dict['advertiser_id'])
        is_own_order = False
        if advertiser:
            client_dict = dict(advertiser)
            is_own_order = (client_dict['user_id'] == user["id"])

        # Формируем текст
        advertiser_name = campaign_dict.get('advertiser_name', 'Неизвестно')
        text = f"📋 <b>{advertiser_name}</b>\n\n"
        text += f"📍 <b>Город:</b> {campaign_dict.get('city', 'Не указан')}\n"
        text += f"📱 <b>Категория:</b> {campaign_dict.get('category', 'Не указана')}\n"

        # ИСПРАВЛЕНО: Правильное отображение типа оплаты
        payment_type = campaign_dict.get('payment_type', 'paid')
        budget_type = campaign_dict.get('budget_type', 'none')
        budget_value = campaign_dict.get('budget_value', 0)

        payment_parts = []

        # Если оплата денежная (paid или both)
        if payment_type in ['paid', 'both']:
            if budget_value and budget_value > 0:
                if budget_type == 'fixed':
                    payment_parts.append(f"💰 {int(budget_value)} BYN (фиксированная)")
                elif budget_type == 'flexible':
                    payment_parts.append(f"💰 {int(budget_value)} BYN (гибкая)")
                else:
                    payment_parts.append(f"💰 {int(budget_value)} BYN")
            elif budget_type == 'flexible':
                payment_parts.append("💬 Блогеры предложат цену")

        # Если есть бартер
        if payment_type in ['barter', 'both']:
            payment_parts.append("🤝 Бартер")

        # Показываем оплату
        if payment_parts:
            text += f"<b>Оплата:</b> {' + '.join(payment_parts)}\n"
        else:
            text += f"<b>Оплата:</b> По договорённости\n"

        text += f"📅 <b>Создан:</b> {campaign_dict.get('created_at', '')}\n\n"
        text += f"📝 <b>Описание:</b>\n{campaign_dict.get('description', 'Нет описания')}\n\n"

        # Информация о клиенте
        text += f"👤 <b>Рекламодател:</b> {campaign_dict.get('advertiser_name', 'Неизвестно')}\n"
        advertiser_rating = campaign_dict.get('advertiser_rating', 0)
        advertiser_rating_count = campaign_dict.get('advertiser_rating_count', 0)
        if advertiser_rating_count > 0:
            text += f"⭐ {advertiser_rating:.1f} ({advertiser_rating_count} отзывов)\n"
        
        # Получаем фото
        photos = campaign_dict.get('photos', '')
        photo_ids = [p.strip() for p in photos.split(',') if p.strip()]
        
        if photo_ids:
            # Отправляем первое фото с текстом
            context.user_data['current_order_id'] = campaign_id
            context.user_data['order_photos'] = photo_ids
            context.user_data['current_photo_index'] = 0
            
            keyboard = []
            
            # Навигация по фото если их больше 1
            if len(photo_ids) > 1:
                nav_buttons = []
                if len(photo_ids) > 1:
                    nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"order_photo_prev_{campaign_id}"))
                nav_buttons.append(InlineKeyboardButton(f"1/{len(photo_ids)}", callback_data="noop"))
                if len(photo_ids) > 1:
                    nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"order_photo_next_{campaign_id}"))
                keyboard.append(nav_buttons)
            
            # Кнопка завершения кампания если блогер работает над ним
            order_status = campaign_dict.get('status', 'open')
            selected_worker_id = campaign_dict.get('selected_worker_id')

            if order_status == 'in_progress' and selected_worker_id == worker_profile["id"]:
                keyboard.append([InlineKeyboardButton("✅ Контента завершена", callback_data=f"blogger_complete_campaign_{campaign_id}")])
            # Кнопка предложения (только для открытых заказов)
            elif order_status == 'open':
                if is_own_order:
                    keyboard.append([InlineKeyboardButton("🚫 Это ваша кампания", callback_data="noop")])
                elif already_bid:
                    keyboard.append([InlineKeyboardButton("✅ Вы уже откликнулись", callback_data="noop")])
                else:
                    keyboard.append([InlineKeyboardButton("💰 Откликнуться", callback_data=f"offer_on_campaign_{campaign_id}")])
                    # НОВОЕ: Кнопка "Отказаться от кампания" (не показывать эту кампанию больше)
                    keyboard.append([InlineKeyboardButton("🚫 Отказаться от кампания", callback_data=f"decline_campaign_{campaign_id}")])

            # ИСПРАВЛЕНО: Если блогер откликнулся на кампанию - возвращаем в "Мои отклики", иначе в "Доступные кампании"
            back_callback = "worker_my_bids" if already_bid else "worker_view_orders"
            keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)])
            
            await query.message.delete()
            await query.message.reply_photo(
                photo=photo_ids[0],
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Нет фото - просто текст
            keyboard = []

            # Кнопка завершения кампания если блогер работает над ним
            order_status = campaign_dict.get('status', 'open')
            selected_worker_id = campaign_dict.get('selected_worker_id')

            if order_status == 'in_progress' and selected_worker_id == worker_profile["id"]:
                keyboard.append([InlineKeyboardButton("✅ Контента завершена", callback_data=f"blogger_complete_campaign_{campaign_id}")])
            # Кнопка предложения (только для открытых заказов)
            elif order_status == 'open':
                if is_own_order:
                    keyboard.append([InlineKeyboardButton("🚫 Это ваша кампания", callback_data="noop")])
                elif already_bid:
                    keyboard.append([InlineKeyboardButton("✅ Вы уже откликнулись", callback_data="noop")])
                else:
                    keyboard.append([InlineKeyboardButton("💰 Откликнуться", callback_data=f"offer_on_campaign_{campaign_id}")])
                    # НОВОЕ: Кнопка "Отказаться от кампания" (не показывать эту кампанию больше)
                    keyboard.append([InlineKeyboardButton("🚫 Отказаться от кампания", callback_data=f"decline_campaign_{campaign_id}")])

            # ИСПРАВЛЕНО: Если блогер откликнулся на кампанию - возвращаем в "Мои отклики", иначе в "Доступные кампании"
            back_callback = "worker_my_bids" if already_bid else "worker_view_orders"
            keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)])
            
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.error(f"Ошибка при просмотре деталей кампания: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Произошла ошибка.\n\nПопробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="worker_view_orders")
            ]])
        )


async def blogger_decline_campaign_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """НОВОЕ: Подтверждение отказа от кампания (шаг 1)"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id из callback_data: "decline_campaign_123"
        campaign_id = int(query.data.replace("decline_campaign_", ""))

        # Получаем кампанию
        campaign = db.get_order_by_id(campaign_id)
        if not campaign:
            await query.edit_message_text("❌ Кампания не найдена.")
            return

        campaign_dict = dict(campaign)
        advertiser_name = campaign_dict.get('advertiser_name', 'Неизвестно')

        # Спрашиваем подтверждение
        text = (
            f"🚫 <b>Отказаться от кампания?</b>\n\n"
            f"Кампания от «{advertiser_name}» больше не будет отображаться в списке доступных заказов.\n\n"
            f"📍 <b>Город:</b> {campaign_dict.get('city', 'Не указан')}\n"
            f"📱 <b>Категория:</b> {campaign_dict.get('category', 'Не указана')}\n\n"
            f"Вы уверены, что хотите отказаться от этого кампания?"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Да, отказаться", callback_data=f"decline_campaign_yes_{campaign_id}"),
                InlineKeyboardButton("❌ Нет, вернуться", callback_data=f"decline_campaign_no_{campaign_id}")
            ]
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка при подтверждении отказа: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Произошла ошибка.\n\nПопробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="worker_view_orders")
            ]])
        )


async def blogger_decline_campaign_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """НОВОЕ: Подтверждение отказа - ДА (шаг 2)"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id из callback_data: "decline_campaign_yes_123"
        campaign_id = int(query.data.replace("decline_campaign_yes_", ""))

        # Получаем user_id
        user = db.get_user(query.from_user.id)
        if not user:
            await query.edit_message_text("❌ Ошибка: пользователь не найден.")
            return

        blogger_user_id = user["id"]

        # Получаем информацию о кампании для отображения
        campaign = db.get_order_by_id(campaign_id)
        advertiser_name = dict(campaign).get('advertiser_name', 'Неизвестно') if campaign else 'Неизвестно'

        # Сохраняем отказ в БД
        success = db.decline_order(blogger_user_id, campaign_id)

        if success:
            text = (
                f"✅ <b>Кампания скрыта</b>\n\n"
                f"Кампания от «{advertiser_name}» больше не будет отображаться в списке доступных заказов.\n\n"
                f"Вы можете продолжить просмотр других заказов."
            )
        else:
            text = "❌ Не удалось скрыть кампанию. Попробуйте позже."

        keyboard = [
            [InlineKeyboardButton("📋 К списку заказов", callback_data="worker_view_orders")],
            [InlineKeyboardButton("💼 Главное меню", callback_data="show_worker_menu")]
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка при отказе от кампания: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Произошла ошибка.\n\nПопробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="worker_view_orders")
            ]])
        )


async def blogger_decline_campaign_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """НОВОЕ: Отмена отказа - НЕТ, вернуться к кампаниу"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем campaign_id из callback_data: "decline_campaign_no_123"
        campaign_id = int(query.data.replace("decline_campaign_no_", ""))

        # Передаём campaign_id через user_data — query.data нельзя изменить в PTB 21
        context.user_data['_view_campaign_id'] = campaign_id
        await blogger_view_campaign_details(update, context)

    except Exception as e:
        logger.error(f"Ошибка при отмене отказа: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Произошла ошибка.\n\nПопробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="worker_view_orders")
            ]])
        )


async def blogger_campaign_photo_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по фото кампания"""
    query = update.callback_query
    await query.answer()
    
    try:
        photo_ids = context.user_data.get('order_photos', [])
        current_index = context.user_data.get('current_photo_index', 0)
        campaign_id = context.user_data.get('current_order_id')
        
        if not photo_ids or campaign_id is None:
            return
        
        # Определяем направление
        if "prev" in query.data:
            current_index = (current_index - 1) % len(photo_ids)
        elif "next" in query.data:
            current_index = (current_index + 1) % len(photo_ids)
        
        context.user_data['current_photo_index'] = current_index
        
        # Получаем кампании для caption
        campaign = db.get_order_by_id(campaign_id)
        campaign_dict = dict(campaign)
        
        # Проверяем предложение
        user = db.get_user(query.from_user.id)
        worker_profile = db.get_worker_profile(user["id"])
        already_bid = db.check_worker_bid_exists(campaign_id, worker_profile["id"])

        # ПРОВЕРКА: Блогер не может откликаться на свою кампанию
        advertiser = db.get_client_by_id(campaign_dict['advertiser_id'])
        is_own_order = False
        if advertiser:
            client_dict = dict(advertiser)
            is_own_order = (client_dict['user_id'] == user["id"])

        # Формируем текст
        advertiser_name = campaign_dict.get('advertiser_name', 'Неизвестно')
        text = f"📋 <b>{advertiser_name}</b>\n\n"
        text += f"📍 <b>Город:</b> {campaign_dict.get('city', 'Не указан')}\n"
        text += f"📱 <b>Категория:</b> {campaign_dict.get('category', 'Не указана')}\n"

        # ИСПРАВЛЕНО: Правильное отображение типа оплаты
        payment_type = campaign_dict.get('payment_type', 'paid')
        budget_type = campaign_dict.get('budget_type', 'none')
        budget_value = campaign_dict.get('budget_value', 0)

        payment_parts = []

        # Если оплата денежная (paid или both)
        if payment_type in ['paid', 'both']:
            if budget_value and budget_value > 0:
                if budget_type == 'fixed':
                    payment_parts.append(f"💰 {int(budget_value)} BYN (фиксированная)")
                elif budget_type == 'flexible':
                    payment_parts.append(f"💰 {int(budget_value)} BYN (гибкая)")
                else:
                    payment_parts.append(f"💰 {int(budget_value)} BYN")
            elif budget_type == 'flexible':
                payment_parts.append("💬 Блогеры предложат цену")

        # Если есть бартер
        if payment_type in ['barter', 'both']:
            payment_parts.append("🤝 Бартер")

        # Показываем оплату
        if payment_parts:
            text += f"<b>Оплата:</b> {' + '.join(payment_parts)}\n"
        else:
            text += f"<b>Оплата:</b> По договорённости\n"

        text += f"📅 <b>Создан:</b> {campaign_dict.get('created_at', '')}\n\n"
        text += f"📝 <b>Описание:</b>\n{campaign_dict.get('description', 'Нет описания')}\n\n"
        text += f"👤 <b>Рекламодател:</b> {campaign_dict.get('advertiser_name', 'Неизвестно')}\n"
        
        # Обновляем кнопки
        keyboard = []
        nav_buttons = []
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"order_photo_prev_{campaign_id}"))
        nav_buttons.append(InlineKeyboardButton(f"{current_index+1}/{len(photo_ids)}", callback_data="noop"))
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"order_photo_next_{campaign_id}"))
        keyboard.append(nav_buttons)

        if is_own_order:
            keyboard.append([InlineKeyboardButton("🚫 Это ваша кампания", callback_data="noop")])
        elif already_bid:
            keyboard.append([InlineKeyboardButton("✅ Вы уже откликнулись", callback_data="noop")])
        else:
            keyboard.append([InlineKeyboardButton("💰 Откликнуться", callback_data=f"offer_on_campaign_{campaign_id}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ К списку заказов", callback_data="worker_view_orders")])

        # Обновляем фото
        await query.message.edit_media(
            media=InputMediaPhoto(media=photo_ids[current_index], caption=text, parse_mode="HTML"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Ошибка навигации по фото: {e}", exc_info=True)


# ------- ЛИСТАНИЕ МАСТЕРОВ ДЛЯ КЛИЕНТОВ -------

async def advertiser_browse_bloggers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало просмотра мастеров - выбор фильтров"""
    query = update.callback_query
    await query.answer()
    
    # Сбрасываем фильтры
    context.user_data.pop("browse_city", None)
    context.user_data.pop("browse_category", None)
    
    keyboard = [
        [InlineKeyboardButton("▶️ Начать просмотр", callback_data="browse_start_now")],
        [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")],
    ]
    
    await query.edit_message_text(
        "🔍 <b>Поиск блогера</b>\n\n"
        "Сейчас показываем всех мастеров.\n\n"
        "(Фильтры по городу и категориям добавим в следующей версии)\n\n"
        "Нажмите \"Начать просмотр\" чтобы увидеть карточки мастеров:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def browse_start_viewing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало просмотра карточек мастеров"""
    query = update.callback_query
    await query.answer()
    
    # Получаем фильтры из context (если есть)
    city_filter = context.user_data.get("browse_city")
    category_filter = context.user_data.get("browse_category")
    
    # Получаем список мастеров
    workers = db.get_all_workers(city=city_filter, category=category_filter)
    
    if not workers:
        await query.edit_message_text(
            "😔 <b>Блогера не найдены</b>\n\n"
            "Пока ни один блогер не зарегистрировался.\n"
            "Попробуйте зайти позже!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")],
            ])
        )
        return
    
    # Сохраняем список и индекс текущего блогера
    context.user_data["workers_list"] = [dict(w) for w in workers]
    context.user_data["current_worker_index"] = 0
    context.user_data["current_photo_index"] = 0
    
    logger.info(f"Найдено мастеров: {len(workers)}")
    
    # Показываем первого блогера
    await show_worker_card(query, context, edit=True)


async def show_blogger_card(query_or_message, context: ContextTypes.DEFAULT_TYPE, edit=False):
    """Показывает карточку блогера"""
    
    workers_list = context.user_data.get("workers_list", [])
    worker_index = context.user_data.get("current_worker_index", 0)
    photo_index = context.user_data.get("current_photo_index", 0)
    
    if worker_index >= len(workers_list):
        # Все блогера просмотрены
        keyboard = [
            [InlineKeyboardButton("🔄 Начать сначала", callback_data="browse_restart")],
            [InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")],
        ]
        
        text = (
            "✅ <b>Вы просмотрели всех мастеров!</b>\n\n"
            "Можете начать сначала или вернуться в меню."
        )
        
        if hasattr(query_or_message, 'edit_message_text'):
            await query_or_message.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query_or_message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return
    
    blogger = workers_list[worker_index]
    
    # Формируем текст карточки
    name = blogger.get("name", "Без имени")
    city = blogger.get("city", "Не указан")
    categories = blogger.get("categories", "Не указаны")
    experience = blogger.get("experience", "Не указан")
    description = blogger.get("description", "Нет описания")
    rating = blogger.get("rating", 0.0)
    rating_count = blogger.get("rating_count", 0)
    portfolio_photos = blogger.get("portfolio_photos", "")
    
    # Обрабатываем фото
    photos_list = [p for p in portfolio_photos.split(",") if p] if portfolio_photos else []
    
    card_text = f"👤 <b>{name}</b>\n\n"
    card_text += f"📍 Город: {city}\n"
    card_text += f"📱 Категории: {categories}\n"
    card_text += f"💼 Опыт: {experience}\n"
    card_text += f"⭐ Рейтинг: {rating:.1f} ({rating_count} отзывов)\n\n"
    card_text += f"📝 {description}\n\n"
    
    if photos_list:
        card_text += f"📸 Фото контент: {photo_index + 1}/{len(photos_list)}"
    else:
        card_text += "📸 Нет фото контент"
    
    # Кнопки навигации
    keyboard = []
    
    # Навигация по фото
    if photos_list and len(photos_list) > 1:
        photo_nav = []
        if photo_index > 0:
            photo_nav.append(InlineKeyboardButton("⬅️ Фото", callback_data="browse_photo_prev"))
        if photo_index < len(photos_list) - 1:
            photo_nav.append(InlineKeyboardButton("Фото ➡️", callback_data="browse_photo_next"))
        
        if photo_nav:
            keyboard.append(photo_nav)
    
    # Действия с мастером
    keyboard.append([
        InlineKeyboardButton("💬 Написать", url=f"tg://user?id={blogger.get('telegram_id')}")
    ])
    
    # Навигация по мастерам
    nav_buttons = []
    if worker_index < len(workers_list) - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ Следующий блогер", callback_data="browse_next_blogger"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="show_client_menu")])
    
    # Отправляем карточку
    if photos_list:
        # Отправляем фото
        current_photo = photos_list[photo_index]
        
        if edit and hasattr(query_or_message, 'message'):
            # Удаляем старое сообщение и отправляем новое с фото
            try:
                await query_or_message.message.delete()
            except:
                pass
            
            await query_or_message.message.reply_photo(
                photo=current_photo,
                caption=card_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Просто отправляем фото
            await query_or_message.reply_photo(
                photo=current_photo,
                caption=card_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        # Нет фото - отправляем только текст
        if edit and hasattr(query_or_message, 'edit_message_text'):
            await query_or_message.edit_message_text(
                card_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query_or_message.reply_text(
                card_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )


async def browse_next_blogger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение на следующего блогера"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["current_worker_index"] = context.user_data.get("current_worker_index", 0) + 1
    context.user_data["current_photo_index"] = 0  # Сбрасываем индекс фото
    
    await show_worker_card(query, context, edit=True)


async def browse_photo_prev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Предыдущее фото блогера"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["current_photo_index"] = max(0, context.user_data.get("current_photo_index", 0) - 1)
    
    await show_worker_card(query, context, edit=True)


async def browse_photo_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Следующее фото блогера"""
    query = update.callback_query
    await query.answer()
    
    workers_list = context.user_data.get("workers_list", [])
    worker_index = context.user_data.get("current_worker_index", 0)
    
    if worker_index < len(workers_list):
        blogger = workers_list[worker_index]
        photos_list = [p for p in (blogger.get("portfolio_photos") or "").split(",") if p]
        
        current_photo_index = context.user_data.get("current_photo_index", 0)
        context.user_data["current_photo_index"] = min(len(photos_list) - 1, current_photo_index + 1)
    
    await show_worker_card(query, context, edit=True)


async def browse_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать просмотр мастеров сначала"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["current_worker_index"] = 0
    context.user_data["current_photo_index"] = 0
    
    await show_worker_card(query, context, edit=True)


# ------- ОТКЛИКИ МАСТЕРОВ НА ЗАКАЗЫ -------

async def blogger_offer_on_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания предложения - зависит от payment_type"""
    query = update.callback_query
    await query.answer()

    # Извлекаем campaign_id
    campaign_id = int(query.data.replace("offer_on_campaign_", ""))
    context.user_data['bid_order_id'] = campaign_id

    # Проверяем не откликался ли уже
    user = db.get_user(query.from_user.id)
    user_dict = dict(user) if user else {}
    worker_profile = db.get_worker_profile(user_dict.get("id"))

    if not worker_profile:
        await query.answer("Ошибка: профиль блогера не найден", show_alert=True)
        return ConversationHandler.END

    profile_dict = dict(worker_profile)
    worker_id = profile_dict.get("id")

    # ПРОВЕРКА: Блогер не может откликаться на свою кампанию
    campaign = db.get_order_by_id(campaign_id)
    if not campaign:
        await query.answer("❌ Кампания не найдена!", show_alert=True)
        return ConversationHandler.END

    campaign_dict = dict(campaign)
    advertiser = db.get_client_by_id(campaign_dict['advertiser_id'])
    if advertiser:
        client_dict = dict(advertiser)
        if client_dict['user_id'] == user_dict.get("id"):
            await query.answer("❌ Вы не можете откликнуться на свою кампанию!", show_alert=True)
            return ConversationHandler.END

    if db.check_worker_bid_exists(campaign_id, worker_id):
        await query.answer("Вы уже откликнулись на эту кампанию!", show_alert=True)
        return ConversationHandler.END

    # НОВАЯ ЛОГИКА: проверяем payment_type
    payment_type = campaign_dict.get('payment_type', 'paid')
    budget_type = campaign_dict.get('budget_type', 'none')
    budget_value = campaign_dict.get('budget_value', 0)
    advertiser_name = campaign_dict.get('advertiser_name', 'Неизвестно')

    # НОВОЕ: Если выбраны оба варианта (оплата + бартер), блогер выбирает
    if payment_type == "both":
        text = (
            "💰🤝 <b>Выберите вариант оплаты</b>\n\n"
            f"📋 <b>{advertiser_name}</b>\n\n"
            "Рекламодатель готов рассмотреть два варианта:\n\n"
            f"💰 <b>Денежная оплата:</b> {int(budget_value)} BYN\n"
            "🤝 <b>Бартер:</b> взаимовыгодное сотрудничество\n\n"
            "Выберите удобный для вас вариант:"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💰 Работать за {int(budget_value)} BYN", callback_data=f"offer_paid_{campaign_id}")],
            [InlineKeyboardButton("🤝 Работать за бартер", callback_data=f"offer_barter_{campaign_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_offer")]
        ])

        try:
            await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
        except:
            await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)

        return OFFER_SELECT_PAYMENT_TYPE

    # 1. БАРТЕР: сразу создаем отклик без ввода цены
    elif payment_type == "barter":
        context.user_data['bid_price'] = 0
        context.user_data['bid_currency'] = 'BYN'
        context.user_data['bid_ready_days'] = 7

        text = (
            "🤝 <b>Отклик на бартер</b>\n\n"
            f"📋 <b>{advertiser_name}</b>\n"
            f"💼 Бартерное сотрудничество\n\n"
            "📝 Хотите добавить комментарий к вашему отклику?\n\n"
            "💡 Расскажите о себе:\n"
            "✓ Ваш опыт в создании подобного контента\n"
            "✓ Примеры ваших работ\n"
            "✓ Почему вас интересует это сотрудничество\n\n"
            "Напишите комментарий или нажмите «Пропустить»:"
        )

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ Пропустить", callback_data="offer_skip_comment"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_offer")
        ]])

        try:
            await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
        except:
            await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)

        return OFFER_ENTER_COMMENT

    # 2. ФИКСИРОВАННЫЙ БЮДЖЕТ: сразу создаем отклик без ввода цены
    elif payment_type == "fixed_budget" and budget_value > 0:
        context.user_data['bid_price'] = budget_value
        context.user_data['bid_currency'] = 'BYN'
        context.user_data['bid_ready_days'] = 7

        text = (
            "💰 <b>Отклик на кампанию</b>\n\n"
            f"📋 <b>{advertiser_name}</b>\n"
            f"💵 Бюджет: <b>{budget_value} BYN</b>\n\n"
            "✅ Вы соглашаетесь работать за указанную сумму.\n\n"
            "📝 Хотите добавить комментарий к вашему отклику?\n\n"
            "💡 Расскажите о себе:\n"
            "✓ Ваш опыт в создании подобного контента\n"
            "✓ Примеры ваших работ\n"
            "✓ Почему именно вы подходите для этой кампании\n\n"
            "Напишите комментарий или нажмите «Пропустить»:"
        )

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ Пропустить", callback_data="offer_skip_comment"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_offer")
        ]])

        try:
            await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
        except:
            await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)

        return OFFER_ENTER_COMMENT

    # 3. БЛОГЕР ПРЕДЛАГАЕТ ЦЕНУ: запрашиваем ввод цены
    else:  # payment_type == "blogger_offer"
        text = (
            "💰 <b>Ваше предложение по цене</b>\n\n"
            f"📋 <b>{advertiser_name}</b>\n\n"
            "Заказчик хочет, чтобы вы предложили свою цену за выполнение кампании.\n\n"
            "⚠️ <b>ВНИМАНИЕ:</b> Цену изменить будет НЕЛЬЗЯ!\n\n"
            "💵 Сначала выберите валюту, в которой будете указывать цену:"
        )

        # Выбор валюты
        keyboard = [
            [
                InlineKeyboardButton("BYN (₽)", callback_data="offer_currency_BYN"),
                InlineKeyboardButton("USD ($)", callback_data="offer_currency_USD"),
            ],
            [
                InlineKeyboardButton("EUR (€)", callback_data="offer_currency_EUR"),
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_offer")],
        ]

        # Пробуем отредактировать как caption (если есть фото), иначе как text
        try:
            await query.edit_message_caption(
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            # Если не получилось (нет фото), редактируем текст
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return OFFER_SELECT_CURRENCY


async def blogger_offer_select_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Блогер выбрал работать за деньги (в случае payment_type = "both")"""
    query = update.callback_query
    await query.answer()

    # Извлекаем campaign_id из callback_data
    campaign_id = int(query.data.replace("offer_paid_", ""))

    # Получаем кампанию
    campaign = db.get_order_by_id(campaign_id)
    if not campaign:
        await query.answer("❌ Кампания не найдена!", show_alert=True)
        return ConversationHandler.END

    campaign_dict = dict(campaign)
    budget_value = campaign_dict.get('budget_value', 0)
    advertiser_name = campaign_dict.get('advertiser_name', 'Неизвестно')

    # Сохраняем параметры для создания отклика
    context.user_data['bid_price'] = budget_value
    context.user_data['bid_currency'] = 'BYN'
    context.user_data['bid_ready_days'] = 7
    context.user_data['current_campaign_id'] = campaign_id

    text = (
        "💰 <b>Отклик на кампанию</b>\n\n"
        f"📋 <b>{advertiser_name}</b>\n"
        f"💵 Оплата: <b>{int(budget_value)} BYN</b>\n\n"
        "✅ Вы выбрали работать за денежную оплату.\n\n"
        "📝 Хотите добавить комментарий к вашему отклику?\n\n"
        "💡 Расскажите о себе:\n"
        "✓ Ваш опыт в создании подобного контента\n"
        "✓ Примеры ваших работ\n"
        "✓ Почему именно вы подходите для этой кампании\n\n"
        "Напишите комментарий или нажмите «Пропустить»:"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭ Пропустить", callback_data="offer_skip_comment"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_offer")
    ]])

    try:
        await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
    except:
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)

    return OFFER_ENTER_COMMENT


async def blogger_offer_select_barter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Блогер выбрал работать за бартер (в случае payment_type = "both")"""
    query = update.callback_query
    await query.answer()

    # Извлекаем campaign_id из callback_data
    campaign_id = int(query.data.replace("offer_barter_", ""))

    # Получаем информацию о кампании для отображения названия рекламодателя
    campaign = db.get_order_by_id(campaign_id)
    advertiser_name = dict(campaign).get('advertiser_name', 'Неизвестно') if campaign else 'Неизвестно'

    # Сохраняем параметры для создания отклика (бартер = цена 0)
    context.user_data['bid_price'] = 0
    context.user_data['bid_currency'] = 'BYN'
    context.user_data['bid_ready_days'] = 7
    context.user_data['current_campaign_id'] = campaign_id

    text = (
        "🤝 <b>Отклик на бартер</b>\n\n"
        f"📋 <b>{advertiser_name}</b>\n"
        "💼 Бартерное сотрудничество\n\n"
        "✅ Вы выбрали работать за бартер.\n\n"
        "📝 Хотите добавить комментарий к вашему отклику?\n\n"
        "💡 Расскажите о себе:\n"
        "✓ Ваш опыт в создании подобного контента\n"
        "✓ Примеры ваших работ\n"
        "✓ Почему вас интересует это сотрудничество\n\n"
        "Напишите комментарий или нажмите «Пропустить»:"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭ Пропустить", callback_data="offer_skip_comment"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_offer")
    ]])

    try:
        await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
    except:
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)

    return OFFER_ENTER_COMMENT


async def blogger_offer_enter_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода цены - переход к комментарию"""
    price_text = update.message.text.strip()

    # Проверяем что это число
    try:
        price = float(price_text.replace(',', '.'))
        if price <= 0:
            raise ValueError
    except:
        currency = context.user_data.get('bid_currency', 'BYN')
        await update.message.reply_text(
            f"❌ Пожалуйста, введите корректную цену в {currency} (только число).\n\n"
            "Например: <code>150</code> или <code>99.50</code>",
            parse_mode="HTML"
        )
        return OFFER_ENTER_PRICE

    context.user_data['bid_price'] = price
    currency = context.user_data.get('bid_currency', 'BYN')

    # Устанавливаем срок по умолчанию (7 дней)
    context.user_data['bid_ready_days'] = 7

    # Сразу спрашиваем комментарий
    await update.message.reply_text(
        f"💰 Ваша цена: <b>{price} {currency}</b>\n\n"
        "📝 Хотите добавить комментарий к вашему отклику?\n\n"
        "💡 <b>Это ваш шанс выделиться!</b> Расскажите о себе:\n"
        "✓ Ваш опыт в создании подобного контента\n"
        "✓ Примеры ваших работ или достижения\n"
        "✓ Почему именно вы подходите для этой кампании\n\n"
        "Напишите комментарий или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ Пропустить", callback_data="offer_skip_comment"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_offer")
        ]])
    )

    return OFFER_ENTER_COMMENT


async def blogger_offer_select_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора валюты - переход к вводу цены"""
    query = update.callback_query
    await query.answer()

    currency = query.data.replace("offer_currency_", "")
    context.user_data['bid_currency'] = currency

    # Получаем символ валюты для отображения
    currency_symbols = {
        'BYN': '₽',
        'USD': '$',
        'EUR': '€'
    }
    currency_symbol = currency_symbols.get(currency, currency)

    # Спрашиваем цену в выбранной валюте
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_offer")
    ]])

    text = (
        f"💰 <b>Валюта выбрана: {currency} ({currency_symbol})</b>\n\n"
        f"Теперь введите вашу цену в {currency} (только число):\n\n"
        "Например: <code>150</code> или <code>99.50</code>"
    )

    # Пробуем отредактировать как caption (если есть фото), иначе как text
    try:
        await query.edit_message_caption(
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except:
        # Если не получилось (нет фото), редактируем текст
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    return OFFER_ENTER_PRICE


async def blogger_offer_select_ready_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора срока готовности - переход к комментарию"""
    query = update.callback_query
    await query.answer()

    # Извлекаем количество дней из callback_data
    ready_days = int(query.data.replace("ready_days_", ""))
    context.user_data['bid_ready_days'] = ready_days

    # Формируем текст для отображения срока
    if ready_days == 0:
        ready_text = "Сегодня"
    elif ready_days == 1:
        ready_text = "Завтра"
    elif ready_days == 3:
        ready_text = "Через 3 дня"
    elif ready_days == 7:
        ready_text = "Через неделю"
    elif ready_days == 14:
        ready_text = "Через 2 недели"
    elif ready_days == 30:
        ready_text = "Через месяц"
    else:
        ready_text = f"Через {ready_days} дн."

    price = context.user_data['bid_price']
    currency = context.user_data['bid_currency']

    # Спрашиваем комментарий
    await query.edit_message_text(
        f"💰 Ваша цена: <b>{price} {currency}</b>\n"
        f"⏱ Срок: <b>{ready_text}</b>\n\n"
        "📝 Хотите добавить комментарий к предложениу?\n\n"
        "💡 <b>Это ваш шанс выделиться!</b> Расскажите:\n"
        "✓ Почему именно такая цена (материалы, сложность контент)\n"
        "✓ Что входит в стоимость, а что оплачивается отдельно\n"
        "✓ Ваш опыт в подобных проектах\n\n"
        "<b>Примеры:</b>\n"
        "• «Цена с моими материалами. Делал 20+ таких объектов»\n"
        "• «В стоимость входит контент и расходники. Выезд бесплатный. Опыт 8 лет»\n"
        "• «Цена за контент, материалы оплачиваете отдельно. Гарантия 2 года»\n\n"
        "Напишите комментарий или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ Пропустить", callback_data="offer_skip_comment"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_offer")
        ]])
    )

    return OFFER_ENTER_COMMENT


async def blogger_offer_enter_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода комментария"""
    comment = update.message.text.strip()
    context.user_data['bid_comment'] = comment

    return await blogger_offer_publish(update, context)


async def blogger_offer_skip_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск комментария"""
    query = update.callback_query
    await query.answer()

    context.user_data['bid_comment'] = ""

    return await blogger_offer_publish(update, context)


async def blogger_offer_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Публикация предложения"""
    try:
        # Получаем данные
        campaign_id = context.user_data['bid_order_id']
        price = context.user_data['bid_price']
        currency = context.user_data['bid_currency']
        comment = context.user_data.get('bid_comment', '')
        ready_in_days = context.user_data.get('bid_ready_days', 7)

        # Получаем worker_id
        if update.callback_query:
            telegram_id = update.callback_query.from_user.id
            message = update.callback_query.message
        else:
            telegram_id = update.effective_user.id
            message = update.message

        user = db.get_user(telegram_id)
        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict["id"])
        worker_profile_dict = dict(worker_profile)

        # Создаём предложение (может вызвать ValueError при rate limiting)
        try:
            offer_id = db.create_bid(
                campaign_id=campaign_id,
                blogger_id=worker_profile_dict["id"],
                proposed_price=price,
                currency=currency,
                comment=comment,
                ready_in_days=ready_in_days
            )
        except ValueError as e:
            # Rate limiting error
            if update.callback_query:
                message = update.callback_query.message
            else:
                message = update.message

            await message.reply_text(
                str(e),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад", callback_data="worker_view_orders")
                ]])
            )
            context.user_data.clear()
            return ConversationHandler.END

        logger.info(f"✅ Предложение #{offer_id} создано блогером {worker_profile_dict['id']} на кампанию {campaign_id}")

        # Отправляем уведомление клиенту
        campaign = db.get_order_by_id(campaign_id)
        if campaign:
            # Получаем telegram_id клиента
            advertiser = db.get_client_by_id(campaign['advertiser_id'])
            client_user = db.get_user_by_id(advertiser['user_id'])

            blogger_name = worker_profile_dict.get('name', 'Блогер')

            # Используем новую функцию уведомления
            await notify_advertiser_new_offer(
                context,
                client_user['telegram_id'],
                client_user['id'],  # advertiser_user_id для системы уведомлений
                campaign_id,
                blogger_name,
                price,
                currency
            )
        
        # ИСПРАВЛЕНО: Добавлена кнопка "Мои отклики" для быстрого доступа к своим откликам
        keyboard = [
            [InlineKeyboardButton("💼 Мои отклики", callback_data="worker_my_bids")],
            [InlineKeyboardButton("📋 К доступным заказам", callback_data="worker_view_orders")],
        ]

        await message.reply_text(
            "✅ <b>Предложение отправлено!</b>\n\n"
            f"💰 Ваша цена: {price} {currency}\n"
            f"📝 Комментарий: {comment if comment else 'Нет'}\n\n"
            "Клиент увидит ваше предложение и сможет с вами связаться!\n\n"
            "💡 Вы можете посмотреть свои отклики в разделе \"💼 Мои отклики\"",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка создания предложения: {e}", exc_info=True)

        if update.callback_query:
            message = update.callback_query.message
        else:
            message = update.message
            
        await message.reply_text(
            "❌ Произошла ошибка при создании предложения.\n\nПопробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="worker_view_orders")
            ]])
        )
        context.user_data.clear()
        return ConversationHandler.END


async def blogger_offer_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена создания предложения"""
    query = update.callback_query
    await query.answer()

    await safe_edit_message(
        query,
        "❌ Создание предложения отменено.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 К доступным заказам", callback_data="worker_view_orders")
        ]])
    )

    context.user_data.clear()
    return ConversationHandler.END


# ------- ПЕРЕКЛЮЧЕНИЕ МЕЖДУ РОЛЯМИ -------

async def go_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню с выбором роли"""
    query = update.callback_query
    await query.answer()
    
    user_telegram_id = query.from_user.id
    user = db.get_user(user_telegram_id)
    
    if not user:
        await query.edit_message_text("Ошибка: пользователь не найден")
        return
    
    user_dict = dict(user)
    user_id = user_dict["id"]
    
    # Проверяем есть ли профиль блогера
    worker_profile = db.get_worker_profile(user_id)
    # Проверяем есть ли профиль клиента
    client_profile = db.get_client_profile(user_id)
    
    has_worker = worker_profile is not None
    has_client = client_profile is not None
    
    keyboard = []
    
    if has_worker:
        keyboard.append([InlineKeyboardButton("🎬 Меню блогера", callback_data="show_worker_menu")])
    
    if has_client:
        keyboard.append([InlineKeyboardButton("💼 Меню рекламодатела", callback_data="show_client_menu")])
    
    # Кнопка для создания второго профиля
    if not has_worker:
        keyboard.append([InlineKeyboardButton("➕ Стать блогером", callback_data="role_blogger")])

    if not has_client:
        keyboard.append([InlineKeyboardButton("➕ Стать рекламодателем", callback_data="role_advertiser")])
    
    message = "💼 <b>Главное меню</b>\n\n"
    
    if has_worker and has_client:
        message += "У вас есть оба профиля.\nВыберите какой использовать:"
    elif has_worker:
        message += "Вы зарегистрированы как блогер.\n\nХотите также стать рекламодателем?"
    elif has_client:
        message += "Вы зарегистрированы как рекламодател.\n\nХотите также стать блогером?"

    # Удаляем старое сообщение и отправляем новое
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=message,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def add_second_role_blogger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление роли блогера к существующему аккаунту"""
    query = update.callback_query
    await query.answer()
    
    # Запускаем регистрацию блогера
    await query.edit_message_text(
        "🎬 <b>Регистрация блогера</b>\n\n"
        "Как вас зовут? Введите ваше имя:",
        parse_mode="HTML"
    )
    
    # Переходим в состояние ввода имени блогера
    return REGISTER_BLOGGER_NAME


async def add_second_role_advertiser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление роли рекламодатела к существующему аккаунту"""
    query = update.callback_query
    await query.answer()
    
    # Запускаем регистрацию рекламодатела
    await query.edit_message_text(
        "💼 <b>Регистрация рекламодатела</b>\n\n"
        "Как вас зовут? Введите ваше имя:",
        parse_mode="HTML"
    )
    
    # Переходим в состояние ввода имени клиента
    return REGISTER_ADVERTISER_NAME


# ------- СОЗДАНИЕ ЗАКАЗА -------

async def advertiser_create_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания кампания - выбор региона"""
    query = update.callback_query
    await query.answer()

    # Получаем профиль клиента
    user = db.get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("Ошибка: пользователь не найден")
        return ConversationHandler.END

    client_profile = db.get_client_profile(user["id"])
    if not client_profile:
        await query.edit_message_text("Ошибка: профиль клиента не найден")
        return ConversationHandler.END

    # Сохраняем client_id
    context.user_data["order_client_id"] = client_profile["id"]

    # Показываем регионы Беларуси
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"campaignregion_{region_name}"
        )])

    await query.edit_message_text(
        "📝 <b>Создание кампании</b>\n\n"
        "🏙 <b>Шаг 1:</b> Где нужен контент? Выберите регион или город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CREATE_CAMPAIGN_REGION_SELECT


async def create_campaign_region_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора региона для кампания"""
    query = update.callback_query
    await query.answer()

    region = query.data.replace("campaignregion_", "")
    region_data = BELARUS_REGIONS.get(region)

    if not region_data:
        await query.edit_message_text("❌ Ошибка выбора региона. Попробуйте снова.")
        return CREATE_CAMPAIGN_REGION_SELECT

    context.user_data["order_region"] = region

    # Если выбран Минск или "Вся Беларусь" - сохраняем и переходим к выбору категорий
    if region_data["type"] in ["city", "country"]:
        context.user_data["order_city"] = region

        # Инициализируем список выбранных категорий
        if "order_categories" not in context.user_data:
            context.user_data["order_categories"] = []

        # Переходим к выбору категорий (множественный выбор)
        selected = context.user_data["order_categories"]
        keyboard = []
        row = []
        for idx, category in enumerate(BLOGGER_CATEGORIES):
            # Добавляем чекбокс: ✅ если выбрано, ⬜ если нет
            checkbox = "✅" if category in selected else "⬜"
            row.append(InlineKeyboardButton(f"{checkbox} {category}", callback_data=f"order_cat_{idx}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # Кнопка "Готово" (активна только если выбрана хотя бы одна категория)
        if selected:
            keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="order_categories_done")])

        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_campaign_back_to_region")])

        selected_text = f"\n\n<b>Выбрано:</b> {', '.join(selected)}" if selected else "\n\n<i>Выберите хотя бы одну категорию</i>"

        await query.edit_message_text(
            f"🏙 Город: {region_data['display']}\n\n"
            f"📱 <b>Шаг 2:</b> Выберите тематики контента (можно несколько):{selected_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_CAMPAIGN_MAIN_CATEGORY

    # Если выбрана область - показываем города
    else:
        cities = region_data.get("cities", [])
        keyboard = []
        row = []
        for city in cities:
            row.append(InlineKeyboardButton(city, callback_data=f"campaigncity_{city}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # Добавляем кнопку "Другой город в области"
        # ЛОГИКА "ДРУГОЙ ГОРОД":
        # - Рекламодатель может указать любой город, не входящий в основной список
        # - Блогеры, работающие в этом городе, увидят кампанию
        # - Это полезно для небольших городов и посёлков
        keyboard.append([InlineKeyboardButton(
            f"📍 Другой город в области",
            callback_data="campaigncity_other"
        )])

        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_campaign_back_to_region")])

        await query.edit_message_text(
            f"📍 Область: {region_data['display']}\n\n"
            "🏙 Выберите город:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_CAMPAIGN_CITY


async def create_campaign_city_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора города для кампания"""
    query = update.callback_query
    await query.answer()

    city = query.data.replace("campaigncity_", "")

    if city == "other":
        await query.edit_message_text(
            "🏙 Напишите название города:"
        )
        return CREATE_CAMPAIGN_CITY
    else:
        context.user_data["order_city"] = city

        # Инициализируем список выбранных категорий
        if "order_categories" not in context.user_data:
            context.user_data["order_categories"] = []

        # Переходим к выбору категорий (множественный выбор)
        selected = context.user_data["order_categories"]
        keyboard = []
        row = []
        for idx, category in enumerate(BLOGGER_CATEGORIES):
            # Добавляем чекбокс: ✅ если выбрано, ⬜ если нет
            checkbox = "✅" if category in selected else "⬜"
            row.append(InlineKeyboardButton(f"{checkbox} {category}", callback_data=f"order_cat_{idx}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # Кнопка "Готово" (активна только если выбрана хотя бы одна категория)
        if selected:
            keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="order_categories_done")])

        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_campaign_back_to_city")])

        selected_text = f"\n\n<b>Выбрано:</b> {', '.join(selected)}" if selected else "\n\n<i>Выберите хотя бы одну категорию</i>"

        await query.edit_message_text(
            f"🏙 Город: <b>{city}</b>\n\n"
            f"📱 <b>Шаг 2:</b> Выберите тематики контента (можно несколько):{selected_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_CAMPAIGN_MAIN_CATEGORY


async def create_campaign_main_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора/отмены категории (множественный выбор)"""
    query = update.callback_query
    await query.answer()

    # Проверяем, это нажатие на "Готово" или выбор категории
    if query.data == "order_categories_done":
        # Переходим к выбору типа оплаты
        categories = context.user_data.get("order_categories", [])
        city = context.user_data.get("order_city", "")

        # Инициализируем список выбранных типов оплаты
        if "payment_types" not in context.user_data:
            context.user_data["payment_types"] = []

        # Переходим к выбору типа оплаты (3 варианта) - множественный выбор
        selected_payments = context.user_data["payment_types"]

        keyboard = []
        # Чекбокс для фиксированного бюджета
        checkbox_fixed = "✅" if "fixed_budget" in selected_payments else "⬜"
        keyboard.append([InlineKeyboardButton(f"{checkbox_fixed} 💰 Указать бюджет", callback_data="payment_type_fixed_budget")])

        # Чекбокс для открытого ценообразования
        checkbox_blogger = "✅" if "blogger_offer" in selected_payments else "⬜"
        keyboard.append([InlineKeyboardButton(f"{checkbox_blogger} 💬 Блогеры предложат цену", callback_data="payment_type_blogger_offer")])

        # Чекбокс для бартера
        checkbox_barter = "✅" if "barter" in selected_payments else "⬜"
        keyboard.append([InlineKeyboardButton(f"{checkbox_barter} 🤝 Бартер", callback_data="payment_type_barter")])

        # Кнопка "Готово" (активна только если выбран хотя бы один вариант)
        if selected_payments:
            keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="payment_types_done")])

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_campaign_back_to_maincat")])

        categories_text = ", ".join(categories)
        selected_text = ""
        if selected_payments:
            payment_names = []
            if "fixed_budget" in selected_payments:
                payment_names.append("Указать бюджет")
            if "blogger_offer" in selected_payments:
                payment_names.append("Блогеры предложат цену")
            if "barter" in selected_payments:
                payment_names.append("Бартер")
            selected_text = f"\n\n<b>Выбрано:</b> {', '.join(payment_names)}"
        else:
            selected_text = "\n\n<i>Выберите хотя бы один вариант оплаты</i>"

        await query.edit_message_text(
            f"🏙 Город: {city}\n"
            f"📱 Категории: {categories_text}\n\n"
            f"💳 <b>Шаг 3:</b> Как вы готовы оплатить публикацию? (можно выбрать несколько){selected_text}\n\n"
            "💰 <b>Указать бюджет</b> - вы указываете фиксированную сумму, блогеры либо соглашаются, либо нет\n"
            "💬 <b>Блогеры предложат цену</b> - блогеры сами предложат свою стоимость в откликах\n"
            "🤝 <b>Бартер</b> - предложение взаимовыгодного сотрудничества без денежной оплаты",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_CAMPAIGN_SUBCATEGORY_SELECT  # Переиспользуем состояние для payment_type
    else:
        # Это toggle категории
        cat_idx = int(query.data.replace("order_cat_", ""))
        category = BLOGGER_CATEGORIES[cat_idx]

        # Toggle: добавить или убрать из списка
        if "order_categories" not in context.user_data:
            context.user_data["order_categories"] = []

        if category in context.user_data["order_categories"]:
            context.user_data["order_categories"].remove(category)
        else:
            context.user_data["order_categories"].append(category)

        # Перерисовываем клавиатуру с обновленными чекбоксами
        selected = context.user_data["order_categories"]
        city = context.user_data.get("order_city", "")

        keyboard = []
        row = []
        for idx, cat in enumerate(BLOGGER_CATEGORIES):
            # Добавляем чекбокс: ✅ если выбрано, ⬜ если нет
            checkbox = "✅" if cat in selected else "⬜"
            row.append(InlineKeyboardButton(f"{checkbox} {cat}", callback_data=f"order_cat_{idx}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # Кнопка "Готово" (активна только если выбрана хотя бы одна категория)
        if selected:
            keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="order_categories_done")])

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_campaign_back_to_maincat")])

        selected_text = f"\n\n<b>Выбрано:</b> {', '.join(selected)}" if selected else "\n\n<i>Выберите хотя бы одну категорию</i>"

        await query.edit_message_text(
            f"🏙 Город: <b>{city}</b>\n\n"
            f"📱 <b>Шаг 2:</b> Выберите категории блогеров (можно несколько):{selected_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_CAMPAIGN_MAIN_CATEGORY


async def create_campaign_subcategory_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типов оплаты (бартер и/или цена) - множественный выбор"""
    query = update.callback_query
    await query.answer()

    # Проверяем, это нажатие на "Готово" или toggle типа оплаты
    if query.data == "payment_types_done":
        # Переходим к описанию
        city = context.user_data.get('order_city', '')
        categories = context.user_data.get('order_categories', [])
        categories_text = ", ".join(categories)

        selected_payments = context.user_data.get('payment_types', [])
        payment_names = []
        if "fixed_budget" in selected_payments:
            payment_names.append("Указать бюджет")
        if "blogger_offer" in selected_payments:
            payment_names.append("Блогеры предложат цену")
        if "barter" in selected_payments:
            payment_names.append("Бартер")
        payment_text = ", ".join(payment_names)

        # ИСПРАВЛЕНО: Правильно сохраняем payment_type для комбинированных вариантов
        # payment_type может быть: "paid", "barter", "both"
        has_paid = ("fixed_budget" in selected_payments or "blogger_offer" in selected_payments)
        has_barter = "barter" in selected_payments

        if has_paid and has_barter:
            context.user_data["payment_type"] = "both"
        elif has_barter:
            context.user_data["payment_type"] = "barter"
        else:
            context.user_data["payment_type"] = "paid"

        # Сохраняем тип бюджета отдельно
        if "fixed_budget" in selected_payments:
            context.user_data["budget_type"] = "fixed"
        elif "blogger_offer" in selected_payments:
            context.user_data["budget_type"] = "flexible"
        else:
            context.user_data["budget_type"] = "none"

        # Если выбран "Указать бюджет" - запрашиваем сумму
        if "fixed_budget" in selected_payments:
            await query.edit_message_text(
                f"🏙 Город: <b>{city}</b>\n"
                f"📱 Категории: <b>{categories_text}</b>\n"
                f"💳 Оплата: <b>{payment_text}</b>\n\n"
                "💰 <b>Шаг 4:</b> Укажите ваш бюджет\n\n"
                "Введите сумму в белорусских рублях (BYN), которую вы готовы заплатить за публикацию.\n"
                "Например: 100 или 50.5\n\n"
                "💡 Блогеры увидят эту сумму и будут откликаться, если их устраивает цена.",
                parse_mode="HTML"
            )
            return CREATE_CAMPAIGN_BUDGET
        else:
            # Если бюджет не указывается - сразу к описанию
            await query.edit_message_text(
                f"🏙 Город: <b>{city}</b>\n"
                f"📱 Категории: <b>{categories_text}</b>\n"
                f"💳 Оплата: <b>{payment_text}</b>\n\n"
                "📝 <b>Шаг 4:</b> Опишите что нужно сделать\n\n"
                "💡 <b>Важно!</b> Блогеры будут предлагать свою цену за услуги, поэтому укажите:\n"
                "✓ Объём контента (сколько постов, Stories, Reels)\n"
                "✓ Размеры и особенности (формат видео, длительность)\n"
                "✓ Материалы (есть свои фото/видео или нужна съёмка)\n"
                "✓ Требования (упоминание бренда, ссылки, хештеги)\n\n"
                "Пример:\n"
                "• Разместить 3 Stories + 1 пост в ленте о нашем кафе (фото предоставим)\n"
                "• Снять Reels 30-60 сек с обзором нашего товара (товар вышлем)\n"
                "• Опубликовать отзыв о семейном отеле с фото (приглашаем на выходные)\n\n"
                "Чем точнее описание - тем точнее цена и меньше недопониманий!",
                parse_mode="HTML"
            )
            return CREATE_CAMPAIGN_DESCRIPTION
    else:
        # Это toggle типа оплаты
        if "payment_types" not in context.user_data:
            context.user_data["payment_types"] = []

        # Toggle: добавить или убрать из списка
        if query.data == "payment_type_fixed_budget":
            payment_type = "fixed_budget"
        elif query.data == "payment_type_blogger_offer":
            payment_type = "blogger_offer"
        elif query.data == "payment_type_barter":
            payment_type = "barter"
        else:
            payment_type = "fixed_budget"

        if payment_type in context.user_data["payment_types"]:
            context.user_data["payment_types"].remove(payment_type)
        else:
            context.user_data["payment_types"].append(payment_type)

        # Перерисовываем клавиатуру с обновленными чекбоксами
        categories = context.user_data.get("order_categories", [])
        city = context.user_data.get("order_city", "")
        selected_payments = context.user_data["payment_types"]

        keyboard = []
        # Чекбокс для фиксированного бюджета
        checkbox_fixed = "✅" if "fixed_budget" in selected_payments else "⬜"
        keyboard.append([InlineKeyboardButton(f"{checkbox_fixed} 💰 Указать бюджет", callback_data="payment_type_fixed_budget")])

        # Чекбокс для открытого ценообразования
        checkbox_blogger = "✅" if "blogger_offer" in selected_payments else "⬜"
        keyboard.append([InlineKeyboardButton(f"{checkbox_blogger} 💬 Блогеры предложат цену", callback_data="payment_type_blogger_offer")])

        # Чекбокс для бартера
        checkbox_barter = "✅" if "barter" in selected_payments else "⬜"
        keyboard.append([InlineKeyboardButton(f"{checkbox_barter} 🤝 Бартер", callback_data="payment_type_barter")])

        # Кнопка "Готово" (активна только если выбран хотя бы один вариант)
        if selected_payments:
            keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="payment_types_done")])

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_campaign_back_to_maincat")])

        categories_text = ", ".join(categories)
        selected_text = ""
        if selected_payments:
            payment_names = []
            if "fixed_budget" in selected_payments:
                payment_names.append("Указать бюджет")
            if "blogger_offer" in selected_payments:
                payment_names.append("Блогеры предложат цену")
            if "barter" in selected_payments:
                payment_names.append("Бартер")
            selected_text = f"\n\n<b>Выбрано:</b> {', '.join(payment_names)}"
        else:
            selected_text = "\n\n<i>Выберите хотя бы один вариант оплаты</i>"

        await query.edit_message_text(
            f"🏙 Город: {city}\n"
            f"📱 Категории: {categories_text}\n\n"
            f"💳 <b>Шаг 3:</b> Как вы готовы оплатить публикацию? (можно выбрать несколько){selected_text}\n\n"
            "💰 <b>Указать бюджет</b> - вы указываете фиксированную сумму, блогеры либо соглашаются, либо нет\n"
            "💬 <b>Блогеры предложат цену</b> - блогеры сами предложат свою стоимость в откликах\n"
            "🤝 <b>Бартер</b> - предложение взаимовыгодного сотрудничества без денежной оплаты",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_CAMPAIGN_SUBCATEGORY_SELECT


async def create_campaign_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода бюджета кампании"""
    budget_text = update.message.text.strip()

    # Проверяем, что введено число
    try:
        budget = float(budget_text.replace(',', '.'))
        if budget <= 0:
            await update.message.reply_text(
                "⚠️ Бюджет должен быть больше нуля. Попробуйте ещё раз:"
            )
            return CREATE_CAMPAIGN_BUDGET
    except ValueError:
        await update.message.reply_text(
            "⚠️ Введите корректную сумму (например: 100 или 50.5)"
        )
        return CREATE_CAMPAIGN_BUDGET

    # Сохраняем бюджет
    context.user_data["budget_value"] = budget

    # Переходим к описанию
    city = context.user_data.get('order_city', '')
    categories = context.user_data.get('order_categories', [])
    categories_text = ", ".join(categories)

    selected_payments = context.user_data.get('payment_types', [])
    payment_names = []
    if "fixed_budget" in selected_payments:
        payment_names.append(f"Бюджет: {budget} BYN")
    if "blogger_offer" in selected_payments:
        payment_names.append("Блогеры предложат цену")
    if "barter" in selected_payments:
        payment_names.append("Бартер")
    payment_text = ", ".join(payment_names)

    await update.message.reply_text(
        f"🏙 Город: <b>{city}</b>\n"
        f"📱 Категории: <b>{categories_text}</b>\n"
        f"💳 Оплата: <b>{payment_text}</b>\n\n"
        "📝 <b>Шаг 5:</b> Опишите что нужно сделать\n\n"
        "💡 <b>Важно!</b> Укажите детали для блогеров:\n"
        "✓ Объём контента (сколько постов, Stories, Reels)\n"
        "✓ Размеры и особенности (формат видео, длительность)\n"
        "✓ Материалы (есть свои фото/видео или нужна съёмка)\n"
        "✓ Требования (упоминание бренда, ссылки, хештеги)\n\n"
        "Пример:\n"
        "• Разместить 3 Stories + 1 пост в ленте о нашем кафе (фото предоставим)\n"
        "• Снять Reels 30-60 сек с обзором нашего товара (товар вышлем)\n"
        "• Опубликовать отзыв о семейном отеле с фото (приглашаем на выходные)\n\n"
        "Чем точнее описание - тем точнее результат!",
        parse_mode="HTML"
    )
    return CREATE_CAMPAIGN_DESCRIPTION


async def create_campaign_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка описания кампания"""
    description = update.message.text.strip()
    
    if len(description) < 10:
        await update.message.reply_text(
            "⚠️ Опишите подробнее (минимум 10 символов)"
        )
        return CREATE_CAMPAIGN_DESCRIPTION
    
    context.user_data["order_description"] = description

    # Предлагаем загрузить фото и видео
    keyboard = [[InlineKeyboardButton("⏭ Пропустить", callback_data="campaign_skip_photos")]]

    await update.message.reply_text(
        "📸 <b>Шаг 4:</b> Загрузите фото или видео объекта\n\n"
        "📷 Фото: до 10 штук\n"
        "🎥 Видео: до 3 штук (макс. 50 МБ каждое)\n\n"
        "Фото и видео помогут блогеру точнее оценить контент и сделать правильное предложение.\n\n"
        "Когда закончите загрузку, отправьте команду /done или нажмите кнопку ниже.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    context.user_data["order_photos"] = []
    context.user_data["order_videos"] = []
    return CREATE_CAMPAIGN_PHOTOS


async def create_campaign_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загрузки фото и видео для кампания"""

    if "order_photos" not in context.user_data:
        context.user_data["order_photos"] = []
    if "order_videos" not in context.user_data:
        context.user_data["order_videos"] = []

    photos = context.user_data["order_photos"]
    videos = context.user_data["order_videos"]

    # Обработка фото
    if update.message.photo:
        if len(photos) >= 10:
            await update.message.reply_text(
                "⚠️ Максимум 10 фото.\n\nМожете добавить видео или завершить командой /done"
            )
            return CREATE_CAMPAIGN_PHOTOS

        # Получаем file_id
        file_id = update.message.photo[-1].file_id

        # КРИТИЧНО: Валидация file_id
        if not validate_file_id(file_id):
            logger.error(f"❌ Невалидный file_id при загрузке фото кампания: {file_id}")
            keyboard = [[InlineKeyboardButton("✅ Далее →", callback_data="campaign_confirm")]]
            await update.message.reply_text(
                "❌ Ошибка при обработке фото.\n\n"
                "Попробуйте отправить фото еще раз или используйте другое изображение.\n\n"
                "Или завершите создание кампания без этого фото.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CREATE_CAMPAIGN_PHOTOS

        # Сохраняем file_id
        photos.append(file_id)

        keyboard = [[InlineKeyboardButton("✅ Далее →", callback_data="campaign_confirm")]]

        await update.message.reply_text(
            f"✅ Фото {len(photos)}/10 добавлено!\n\n"
            f"📷 Фото: {len(photos)}/10\n"
            f"🎥 Видео: {len(videos)}/3\n\n"
            f"Можете добавить ещё или завершить командой /done",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return CREATE_CAMPAIGN_PHOTOS

    # Обработка видео
    elif update.message.video:
        if len(videos) >= 3:
            await update.message.reply_text(
                "⚠️ Максимум 3 видео.\n\nМожете добавить фото или завершить командой /done"
            )
            return CREATE_CAMPAIGN_PHOTOS

        # Проверка размера видео (50 МБ = 50 * 1024 * 1024 байт)
        video_size = update.message.video.file_size
        max_size = 50 * 1024 * 1024

        if video_size > max_size:
            await update.message.reply_text(
                f"⚠️ Видео слишком большое ({video_size / 1024 / 1024:.1f} МБ).\n"
                f"Максимальный размер: 50 МБ.\n\n"
                f"Попробуйте сжать видео или отправьте другое."
            )
            return CREATE_CAMPAIGN_PHOTOS

        # Получаем file_id
        file_id = update.message.video.file_id

        # КРИТИЧНО: Валидация file_id
        if not validate_file_id(file_id):
            logger.error(f"❌ Невалидный file_id при загрузке видео кампания: {file_id}")
            keyboard = [[InlineKeyboardButton("✅ Далее →", callback_data="campaign_confirm")]]
            await update.message.reply_text(
                "❌ Ошибка при обработке видео.\n\n"
                "Попробуйте отправить видео еще раз или используйте другой файл.\n\n"
                "Или завершите создание кампания без этого видео.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CREATE_CAMPAIGN_PHOTOS

        # Сохраняем file_id
        videos.append(file_id)

        keyboard = [[InlineKeyboardButton("✅ Далее →", callback_data="campaign_confirm")]]

        await update.message.reply_text(
            f"✅ Видео {len(videos)}/3 добавлено!\n\n"
            f"📷 Фото: {len(photos)}/10\n"
            f"🎥 Видео: {len(videos)}/3\n\n"
            f"Можете добавить ещё или завершить командой /done",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return CREATE_CAMPAIGN_PHOTOS

    return CREATE_CAMPAIGN_PHOTOS


async def create_campaign_done_uploading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение загрузки фото и видео по команде /done"""
    return await create_campaign_confirm(update, context)


async def create_campaign_skip_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск загрузки фото и видео"""
    query = update.callback_query
    await query.answer()

    context.user_data["order_photos"] = []
    context.user_data["order_videos"] = []

    return await create_campaign_confirm(update, context)


async def create_campaign_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экран подтверждения перед публикацией кампании"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        message = query.message
        is_callback = True
    else:
        message = update.message
        is_callback = False

    # Формируем сводку по кампании
    city = context.user_data.get("order_city", "Не указан")
    categories = context.user_data.get("order_categories", [])
    categories_text = ", ".join(categories) if categories else "Не указаны"
    description = context.user_data.get("order_description", "Нет описания")
    photos_count = len(context.user_data.get("order_photos", []))
    videos_count = len(context.user_data.get("order_videos", []))

    payment_types = context.user_data.get("payment_types", [])
    budget_value = context.user_data.get("budget_value", 0)

    payment_text = ""
    if "fixed_budget" in payment_types:
        payment_text = f"💰 <b>Бюджет:</b> {budget_value} BYN\n"
    elif "blogger_offer" in payment_types:
        payment_text = "💬 <b>Оплата:</b> Блогеры предложат цену\n"
    if "barter" in payment_types:
        payment_text += "🤝 <b>Бартер:</b> Возможен\n"

    media_text = ""
    if photos_count > 0:
        media_text += f"📸 Фото: {photos_count}\n"
    if videos_count > 0:
        media_text += f"🎥 Видео: {videos_count}\n"

    text = (
        "✨ <b>Подтверждение публикации</b>\n\n"
        f"📍 <b>Город:</b> {city}\n"
        f"📱 <b>Категории:</b> {categories_text}\n"
        f"{payment_text}"
        f"{media_text}"
        f"📝 <b>Описание:</b> {description[:100]}{'...' if len(description) > 100 else ''}\n\n"
        "🎯 Нажмите кнопку ниже чтобы опубликовать кампанию.\n"
        "Блогеры получат уведомление и смогут откликнуться!"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Опубликовать", callback_data="campaign_publish_confirmed")],
        [InlineKeyboardButton("❌ Отменить", callback_data="show_client_menu")]
    ]

    if is_callback:
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    return CREATE_CAMPAIGN_PHOTOS




# ------- ОБРАБОТЧИКИ КНОПОК "НАЗАД" ДЛЯ СОЗДАНИЯ ЗАКАЗА -------

async def create_campaign_back_to_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору региона"""
    query = update.callback_query
    await query.answer()

    # Показываем регионы Беларуси
    keyboard = []
    for region_name, region_data in BELARUS_REGIONS.items():
        keyboard.append([InlineKeyboardButton(
            region_data["display"],
            callback_data=f"campaignregion_{region_name}"
        )])

    await query.edit_message_text(
        "📝 <b>Создание кампании</b>\n\n"
        "🏙 <b>Шаг 1:</b> Где нужен контент? Выберите регион или город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CREATE_CAMPAIGN_REGION_SELECT


async def create_campaign_back_to_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору города"""
    query = update.callback_query
    await query.answer()

    region = context.user_data.get("order_region")
    if not region:
        # Если региона нет, возвращаемся к выбору региона
        return await create_campaign_back_to_region(update, context)

    region_data = BELARUS_REGIONS.get(region)
    if not region_data:
        return await create_campaign_back_to_region(update, context)

    # Если это был Минск или Вся Беларусь - возвращаемся к выбору региона
    if region_data["type"] in ["city", "country"]:
        return await create_campaign_back_to_region(update, context)

    # Показываем города области
    cities = region_data.get("cities", [])
    keyboard = []
    row = []
    for city in cities:
        row.append(InlineKeyboardButton(city, callback_data=f"campaigncity_{city}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(
        f"📍 Другой город в области",
        callback_data="campaigncity_other"
    )])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_campaign_back_to_region")])

    await query.edit_message_text(
        f"📍 Область: {region_data['display']}\n\n"
        "🏙 Выберите город:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CREATE_CAMPAIGN_CITY


async def create_campaign_back_to_maincat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору основной категории"""
    query = update.callback_query
    await query.answer()

    city = context.user_data.get("order_city", "")

    # Переходим к выбору категорий (упрощенные, без подкатегорий)
    keyboard = []
    row = []
    for idx, category in enumerate(BLOGGER_CATEGORIES):
        row.append(InlineKeyboardButton(category, callback_data=f"order_cat_{idx}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_campaign_back_to_city")])

    await query.edit_message_text(
        f"🏙 Город: <b>{city}</b>\n\n"
        "📱 <b>Шаг 2:</b> Выберите основную тематику контента:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CREATE_CAMPAIGN_MAIN_CATEGORY


async def create_campaign_city_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода города вручную при создании кампания"""
    if update.callback_query:
        # Это callback от кнопки "Другой город"
        await update.callback_query.answer()

        # Отправляем инструкцию пользователю
        await update.callback_query.edit_message_text(
            "📍 <b>Введите название вашего города</b>\n\n"
            "Например: <code>Жодино</code>\n\n"
            "Или нажмите /cancel для отмены.",
            parse_mode="HTML"
        )
        return CREATE_CAMPAIGN_CITY  # Ожидаем текстовое сообщение
    else:
        # Это текстовое сообщение с названием города
        city = update.message.text.strip()
        context.user_data["order_city"] = city

        # Переходим к выбору категорий (упрощенные, без подкатегорий)
        keyboard = []
        row = []
        for idx, category in enumerate(BLOGGER_CATEGORIES):
            row.append(InlineKeyboardButton(category, callback_data=f"order_cat_{idx}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="create_campaign_back_to_city")])

        await update.message.reply_text(
            f"🏙 Город: <b>{city}</b>\n\n"
            "📱 <b>Шаг 2:</b> Выберите основную тематику контента:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CREATE_CAMPAIGN_MAIN_CATEGORY



async def create_campaign_publish_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик подтверждения публикации - вызывает create_campaign_publish"""
    return await create_campaign_publish(update, context)


async def create_campaign_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Публикация кампания.
    ИСПРАВЛЕНО: Валидация обязательных полей перед созданием.
    """

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        message = query.message
    else:
        message = update.message

    # КРИТИЧНО: Проверяем наличие всех обязательных полей
    required_fields = ["order_client_id", "order_city", "order_categories", "order_description"]
    ok, missing = validate_required_fields(context, required_fields)

    if not ok:
        logger.error(f"Missing required fields in create_order: {missing}")
        keyboard = [[InlineKeyboardButton("💼 Главное меню", callback_data="go_main_menu")]]
        await message.reply_text(
            "❌ Ошибка: недостаточно данных для создания кампания.\n\n"
            "Пожалуйста, начните создание кампания заново.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        logger.info("=== Публикация кампания ===")
        logger.info(f"client_id: {context.user_data.get('order_client_id')}")
        logger.info(f"city: {context.user_data.get('order_city')}")
        logger.info(f"categories: {context.user_data.get('order_categories')}")
        logger.info(f"description: {context.user_data.get('order_description')}")
        logger.info(f"photos: {len(context.user_data.get('order_photos', []))}")
        logger.info(f"videos: {len(context.user_data.get('order_videos', []))}")

        # КРИТИЧНО: Валидация file_id перед сохранением кампания
        order_photos = context.user_data.get("order_photos", [])
        valid_order_photos = [fid for fid in order_photos if validate_file_id(fid)]
        if len(valid_order_photos) < len(order_photos):
            removed_count = len(order_photos) - len(valid_order_photos)
            logger.warning(f"⚠️ Удалено {removed_count} невалидных file_id из фото кампания")

        # Валидация file_id для видео
        order_videos = context.user_data.get("order_videos", [])
        valid_order_videos = [fid for fid in order_videos if validate_file_id(fid)]
        if len(valid_order_videos) < len(order_videos):
            removed_count = len(order_videos) - len(valid_order_videos)
            logger.warning(f"⚠️ Удалено {removed_count} невалидных file_id из видео кампания")

        # Создаём кампанию в БД (может вызвать ValueError при rate limiting)
        try:
            campaign_id = db.create_order(
                advertiser_id=context.user_data["order_client_id"],
                city=context.user_data["order_city"],
                categories=context.user_data["order_categories"],  # Теперь это список
                description=context.user_data["order_description"],
                photos=valid_order_photos,
                videos=valid_order_videos,
                budget_type=context.user_data.get("budget_type", "none"),
                budget_value=context.user_data.get("budget_value", 0),
                payment_type=context.user_data.get("payment_type", "paid")
            )
        except ValueError as e:
            # Rate limiting error
            keyboard = [[InlineKeyboardButton("⬅️ В меню", callback_data="show_client_menu")]]
            await message.reply_text(
                str(e),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data.clear()
            return ConversationHandler.END

        logger.info(f"✅ Кампания #{campaign_id} успешно сохранён в БД!")

        # КРИТИЧНО: Логирование для диагностики уведомлений
        logger.info(f"🔔 НАЧИНАЮ ОТПРАВКУ УВЕДОМЛЕНИЙ для кампания #{campaign_id}")

        # Получаем созданную кампанию для отправки уведомлений
        campaign = db.get_order_by_id(campaign_id)
        logger.info(f"🔔 Кампания получена из БД: {campaign is not None}")
        if campaign:
            campaign_dict = dict(campaign)

            # Находим всех блогеров в нужных категориях И городе и отправляем уведомления
            order_city = context.user_data['order_city']
            categories = context.user_data["order_categories"]

            # ВАЖНО: фильтруем блогеров по городу И любой из выбранных категорий
            # Используем set для избежания дубликатов
            all_workers = set()
            for category in categories:
                workers_in_cat = db.get_all_workers(city=order_city, category=category)
                for worker in workers_in_cat:
                    all_workers.add(worker['id'])  # Добавляем по ID чтобы избежать дубликатов

            # Получаем полные данные блогеров
            workers = [db.get_worker_by_id(worker_id) for worker_id in all_workers]
            workers = [w for w in workers if w is not None]  # Фильтруем None

            logger.info(f"📢 Найдено {len(workers)} блогеров для уведомления (город: {order_city}, категории: {', '.join(categories)})")

            notified_count = 0
            for blogger in workers:
                worker_dict = dict(blogger)

                worker_user = db.get_user_by_id(worker_dict['user_id'])
                if worker_user:
                    # Проверяем включены ли уведомления у блогера
                    notifications_enabled = db.are_notifications_enabled(worker_dict['user_id'])
                    logger.info(f"🔔 Блогер {worker_dict['user_id']}: уведомления {'включены' if notifications_enabled else 'отключены'}")

                    if notifications_enabled:
                        await notify_blogger_new_campaign(
                            context,
                            worker_user['telegram_id'],
                            worker_dict['user_id'],
                            campaign_dict
                        )
                        notified_count += 1

            logger.info(f"✅ Отправлено уведомлений: {notified_count} из {len(workers)} мастеров")

        categories = context.user_data["order_categories"]
        categories_text = ", ".join(categories)
        photos_count = len(context.user_data.get("order_photos", []))
        videos_count = len(context.user_data.get("order_videos", []))

        keyboard = [
            [InlineKeyboardButton("📂 Мои кампании", callback_data="client_my_orders")],
            [InlineKeyboardButton("⬅️ В меню", callback_data="show_client_menu")],
        ]

        media_info = ""
        if photos_count > 0:
            media_info += f"📸 Фото: {photos_count}\n"
        if videos_count > 0:
            media_info += f"🎥 Видео: {videos_count}\n"

        await message.reply_text(
            "🎉 <b>Рекламная кампания опубликована!</b>\n\n"
            f"📍 Город: {context.user_data['order_city']}\n"
            f"📱 Категории: {categories_text}\n"
            f"{media_info}"
            f"📝 Описание: {context.user_data['order_description'][:50]}...\n\n"
            "⏰ <b>Срок действия: 7 дней</b>\n"
            "После этого кампания автоматически закроется и её нужно будет создать заново.\n\n"
            "Блогеры получили уведомление о вашей кампании и скоро начнут откликаться!\n"
            "Вы сможете выбрать лучших и начать общение для обсуждения деталей.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logger.info("✅ Сообщение отправлено клиенту")
        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка создания кампания: {e}", exc_info=True)
        
        keyboard = [[InlineKeyboardButton("⬅️ В меню", callback_data="show_client_menu")]]
        
        await message.reply_text(
            f"❌ Ошибка при создании кампания:\n{str(e)}\n\nПопробуйте ещё раз или обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data.clear()
        return ConversationHandler.END


# ============================================
# ЗАВЕРШЕНИЕ ЗАКАЗА И СИСТЕМА ОТЗЫВОВ
# ============================================

async def advertiser_complete_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ИСПРАВЛЕНО: Клиент завершает кампанию.
    Кампания сразу получает статус 'completed', обе стороны могут оставить отзыв.
    """
    query = update.callback_query
    await query.answer()

    campaign_id = int(query.data.replace("complete_campaign_", ""))

    # ИСПРАВЛЕНО: Кампания завершается сразу (не требуется подтверждение от обеих сторон)
    db.mark_order_completed_by_client(campaign_id)

    # Получаем информацию о кампание и блогере
    campaign = db.get_order_by_id(campaign_id)
    worker_info = db.get_worker_info_for_order(campaign_id)

    if campaign and worker_info:
        campaign_dict = dict(campaign)
        worker_dict = dict(worker_info)

        # Уведомляем клиента
        await query.edit_message_text(
            "✅ <b>Кампания завершена!</b>\n\n"
            "Кампания перемещена во вкладку \"Завершенные кампании\".\n\n"
            "💡 Оставьте отзыв о контенте блогера - это поможет другим заказчикам выбрать проверенного специалиста!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Оценить блогера", callback_data=f"leave_review_{campaign_id}")],
                [InlineKeyboardButton("📂 Мои кампании", callback_data="client_my_orders")]
            ])
        )

        # Уведомляем блогера о завершении кампания
        user_id = worker_dict['user_id']
        user = db.get_user_by_id(user_id)
        if user:
            user_dict = dict(user)
            telegram_id = user_dict['telegram_id']
            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=f"✅ <b>Кампания #{campaign_id} завершена!</b>\n\n"
                         f"Клиент завершил кампанию.\n"
                         f"Кампания перемещена во вкладку \"Завершенные кампании\".\n\n"
                         f"💡 Оставьте отзыв о контенте с клиентом!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⭐ Оценить рекламодатела", callback_data=f"leave_review_{campaign_id}")],
                        [InlineKeyboardButton("📦 Мои кампании", callback_data="worker_my_orders")]
                    ])
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление блогеру: {e}")


async def blogger_complete_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ИСПРАВЛЕНО: Блогер завершает кампанию.
    Кампания сразу получает статус 'completed', обе стороны могут оставить отзыв.
    """
    query = update.callback_query
    await query.answer()

    campaign_id = int(query.data.replace("blogger_complete_campaign_", ""))

    # ИСПРАВЛЕНО: Кампания завершается сразу (не требуется подтверждение от обеих сторон)
    db.mark_order_completed_by_worker(campaign_id)

    # Получаем информацию о кампание
    campaign = db.get_order_by_id(campaign_id)

    if campaign:
        campaign_dict = dict(campaign)

        # Уведомляем блогера
        await query.edit_message_text(
            "✅ <b>Кампания завершена!</b>\n\n"
            "Кампания перемещена во вкладку \"Завершенные кампании\".\n\n"
            "💡 Оставьте отзыв о контенте с рекламодателем!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Оценить рекламодатела", callback_data=f"leave_review_{campaign_id}")],
                [InlineKeyboardButton("📦 Мои кампании", callback_data="worker_my_orders")]
            ])
        )

        # Уведомляем клиента о завершении кампания
        advertiser_user_id = campaign_dict['advertiser_user_id']
        user = db.get_user_by_id(advertiser_user_id)
        if user:
            user_dict = dict(user)
            telegram_id = user_dict['telegram_id']
            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=f"✅ <b>Кампания #{campaign_id} завершена!</b>\n\n"
                         f"Блогер завершил кампанию.\n"
                         f"Кампания перемещена во вкладку \"Завершенные кампании\".\n\n"
                         f"💡 Оставьте отзыв о контенте блогера!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⭐ Оценить блогера", callback_data=f"leave_review_{campaign_id}")],
                        [InlineKeyboardButton("📂 Мои кампании", callback_data="client_my_orders")]
                    ])
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление клиенту: {e}")


async def start_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса оставления отзыва"""
    query = update.callback_query
    await query.answer()

    campaign_id = int(query.data.replace("leave_review_", ""))
    user_telegram_id = update.effective_user.id
    user = db.get_user(user_telegram_id)

    if not user:
        await query.edit_message_text("❌ Ошибка: пользователь не найден")
        return ConversationHandler.END

    user_dict = dict(user)
    user_id = user_dict['id']

    # Получаем информацию о кампание
    campaign = db.get_order_by_id(campaign_id)
    if not campaign:
        await query.edit_message_text("❌ Кампания не найдена")
        return ConversationHandler.END

    campaign_dict = dict(campaign)

    # 🛡️ ЗАЩИТА 1: Проверяем статус кампания - только completed
    if campaign_dict['status'] != 'completed':
        await query.edit_message_text(
            "⚠️ <b>Отзыв можно оставить только после завершения кампания</b>\n\n"
            f"Текущий статус: {campaign_dict['status']}\n\n"
            "Сначала завершите кампанию!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="go_main_menu")
            ]])
        )
        return ConversationHandler.END

    # 🛡️ ЗАЩИТА 2: Проверяем что пользователь - участник кампания
    advertiser_user_id = campaign_dict['advertiser_user_id']
    worker_info = db.get_worker_info_for_order(campaign_id)

    is_client = (user_id == advertiser_user_id)
    is_worker = False
    if worker_info:
        worker_dict = dict(worker_info)
        is_worker = (user_id == worker_dict['user_id'])

    if not is_client and not is_worker:
        await query.edit_message_text(
            "⚠️ <b>Ошибка доступа</b>\n\n"
            "Вы не являетесь участником этого кампания.\n"
            "Оставить отзыв могут только клиент и блогер.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="go_main_menu")
            ]])
        )
        return ConversationHandler.END

    # 🛡️ ЗАЩИТА 3: Минимальное время между принятием ставки и завершением (1 час)
    from datetime import datetime, timedelta
    if campaign_dict.get('accepted_at'):
        accepted_at = datetime.fromisoformat(campaign_dict['accepted_at'])
        completed_at = datetime.fromisoformat(campaign_dict['completed_at'])
        time_diff = (completed_at - accepted_at).total_seconds() / 3600  # в часах

        MIN_HOURS = 1
        if time_diff < MIN_HOURS:
            await query.edit_message_text(
                "⚠️ <b>Подозрительно быстрое завершение</b>\n\n"
                f"Кампания была завершена слишком быстро (менее {MIN_HOURS} часа после принятия ставки).\n\n"
                "Отзывы для такихзаказов недоступны для предотвращения накрутки рейтинга.\n\n"
                "💡 Если это ошибка, обратитесь в поддержку.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад", callback_data="go_main_menu")
                ]])
            )
            logger.warning(f"🛡️ [ANTI-FRAUD] Кампания #{campaign_id} завершен за {time_diff:.2f}ч - отзыв ЗАБЛОКИРОВАН")
            return ConversationHandler.END

    # 🛡️ ЗАЩИТА 4: Лимит заказов между одними и теми же пользователями (макс 5 за неделю)
    # Определяем второго участника для проверки
    partner_user_id = None
    if is_client and worker_info:
        partner_user_id = worker_dict['user_id']
    elif is_worker:
        partner_user_id = advertiser_user_id

    if partner_user_id:
        orders_count = db.count_orders_between_users(user_id, partner_user_id, days=7)
        MAX_ORDERS_PER_WEEK = 5

        if orders_count > MAX_ORDERS_PER_WEEK:
            await query.edit_message_text(
                "⚠️ <b>Превышен лимит заказов</b>\n\n"
                f"Вы выполнили слишком много заказов ({orders_count}) с этим партнером за последнюю неделю.\n\n"
                f"Лимит отзывов: {MAX_ORDERS_PER_WEEK} заказов/неделю между одними и теми же пользователями.\n\n"
                "Эта мера защищает от накрутки рейтинга.\n\n"
                "💡 Если это ошибка, обратитесь в поддержку.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад", callback_data="go_main_menu")
                ]])
            )
            logger.warning(
                f"🛡️ [ANTI-FRAUD] Между user_id={user_id} и user_id={partner_user_id} "
                f"уже {orders_count} заказов за неделю - отзыв ЗАБЛОКИРОВАН"
            )
            return ConversationHandler.END

    # Проверяем не оставлен ли уже отзыв
    if db.check_review_exists(campaign_id, user_id):
        await query.edit_message_text(
            "ℹ️ Вы уже оставили отзыв по этому кампаниу.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="go_main_menu")
            ]])
        )
        return ConversationHandler.END

    # Сохраняем информацию в контексте
    context.user_data['review_order_id'] = campaign_id
    context.user_data['review_from_user_id'] = user_id

    # Определяем кого оцениваем (клиент или блогер)
    if user_id == advertiser_user_id:
        # Клиент оценивает блогера
        if worker_info:
            worker_dict = dict(worker_info)
            context.user_data['review_to_user_id'] = worker_dict['user_id']
            context.user_data['review_role_from'] = 'advertiser'
            context.user_data['review_role_to'] = 'blogger'
            reviewer_name = worker_dict['name']
        else:
            await query.edit_message_text("❌ Информация о блогере не найдена")
            return ConversationHandler.END
    else:
        # Блогер оценивает клиента
        context.user_data['review_to_user_id'] = advertiser_user_id
        context.user_data['review_role_from'] = 'blogger'
        context.user_data['review_role_to'] = 'advertiser'
        reviewer_name = campaign_dict['advertiser_name']

    # Показываем выбор звезд
    keyboard = [
        [
            InlineKeyboardButton("⭐", callback_data="review_rating_1"),
            InlineKeyboardButton("⭐⭐", callback_data="review_rating_2"),
            InlineKeyboardButton("⭐⭐⭐", callback_data="review_rating_3"),
        ],
        [
            InlineKeyboardButton("⭐⭐⭐⭐", callback_data="review_rating_4"),
            InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="review_rating_5"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_review")]
    ]

    await query.edit_message_text(
        f"⭐ <b>Оставьте отзыв</b>\n\n"
        f"Оцените работу: <b>{reviewer_name}</b>\n\n"
        f"Выберите оценку от 1 до 5 звезд:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return REVIEW_SELECT_RATING


async def review_select_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора оценки"""
    query = update.callback_query
    await query.answer()

    rating = int(query.data.replace("review_rating_", ""))
    context.user_data['review_rating'] = rating

    # Просим написать комментарий
    keyboard = [[InlineKeyboardButton("⏭ Пропустить комментарий", callback_data="review_skip_comment")]]

    stars = "⭐" * rating
    await query.edit_message_text(
        f"✅ Оценка: {stars} ({rating}/5)\n\n"
        f"📝 Теперь напишите отзыв:\n"
        f"• Что понравилось или не понравилось?\n"
        f"• Качество контента\n"
        f"• Соблюдение сроков\n"
        f"• Коммуникация\n\n"
        f"Или пропустите, если хотите оставить только оценку.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return REVIEW_ENTER_COMMENT


async def review_enter_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текста отзыва"""
    comment = update.message.text.strip()

    if len(comment) > 1000:
        await update.message.reply_text(
            "❌ Отзыв слишком длинный. Максимум 1000 символов.\n"
            "Пожалуйста, сократите текст и отправьте снова."
        )
        return REVIEW_ENTER_COMMENT

    context.user_data['review_comment'] = comment

    # Сохраняем отзыв
    return await save_review(update, context)


async def review_skip_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск комментария - только оценка"""
    query = update.callback_query
    await query.answer()

    context.user_data['review_comment'] = ""

    # Сохраняем отзыв
    return await save_review(update, context, query=query)


async def save_review(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """Сохранение отзыва в базу данных"""
    try:
        from_user_id = context.user_data['review_from_user_id']
        to_user_id = context.user_data['review_to_user_id']
        campaign_id = context.user_data['review_order_id']
        role_from = context.user_data['review_role_from']
        role_to = context.user_data['review_role_to']
        rating = context.user_data['review_rating']
        comment = context.user_data.get('review_comment', '')

        # Сохраняем отзыв
        success = db.add_review(from_user_id, to_user_id, campaign_id, role_from, role_to, rating, comment)

        # Определяем меню для возврата на основе роли
        menu_callback = "show_worker_menu" if role_from == "blogger" else "show_client_menu"

        if success:
            stars = "⭐" * rating
            message_text = (
                f"✅ <b>Отзыв успешно опубликован!</b>\n\n"
                f"Оценка: {stars} ({rating}/5)\n"
            )
            if comment:
                message_text += f"\n📝 Комментарий:\n{comment[:100]}{'...' if len(comment) > 100 else ''}"

            keyboard = [[InlineKeyboardButton("💼 В главное меню", callback_data=menu_callback)]]

            if query:
                await query.edit_message_text(
                    message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            error_message = "❌ Не удалось сохранить отзыв. Возможно вы уже оставляли отзыв по этому кампаниу."
            keyboard = [[InlineKeyboardButton("💼 В главное меню", callback_data=menu_callback)]]
            if query:
                await query.edit_message_text(error_message, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text(error_message, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Ошибка при сохранении отзыва: {e}", exc_info=True)
        error_message = f"❌ Произошла ошибка при сохранении отзыва: {str(e)}"
        # Определяем меню для возврата
        role_from = context.user_data.get('review_role_from', 'blogger')
        menu_callback = "show_worker_menu" if role_from == "blogger" else "show_client_menu"
        keyboard = [[InlineKeyboardButton("💼 В главное меню", callback_data=menu_callback)]]
        if query:
            await query.edit_message_text(error_message, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(error_message, reply_markup=InlineKeyboardMarkup(keyboard))

    # Очищаем данные
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена оставления отзыва"""
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "❌ Отмена. Вы можете оставить отзыв позже.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ В главное меню", callback_data="go_main_menu")
        ]])
    )

    return ConversationHandler.END


async def show_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все отзывы о пользователе"""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем user_id из callback_data (формат: show_reviews_worker_123 или show_reviews_client_123)
        parts = query.data.split("_")
        role = parts[2]  # blogger или advertiser
        profile_user_id = int(parts[3])

        logger.info(f"Показываю отзывы для user_id={profile_user_id}, role={role}")

        # Получаем текущего пользователя для проверки, смотрит ли он свой профиль
        current_user = db.get_user(query.from_user.id)
        is_own_profile = False
        if current_user:
            current_user_dict = dict(current_user)
            is_own_profile = (current_user_dict['id'] == profile_user_id)

        # Получаем отзывы
        reviews = db.get_reviews_for_user(profile_user_id, role)
        logger.info(f"Найдено {len(reviews) if reviews else 0} отзывов")

        if not reviews:
            # Определяем callback для кнопки "Назад"
            if is_own_profile:
                # Если смотрим свой профиль - возврат в меню
                back_callback = "show_worker_menu" if role in ["blogger", "both"] else "show_client_menu"
            else:
                # Если смотрим чужой профиль - возврат в профиль
                back_callback = "worker_profile" if role in ["blogger", "both"] else "show_client_menu"

            await safe_edit_message(
                query,
                "📊 <b>Отзывы</b>\n\n"
                "Пока нет отзывов.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)
                ]])
            )
            return

        # Формируем текст с отзывами
        message_text = "📊 <b>Отзывы</b>\n\n"

        for review in reviews[:10]:  # Показываем первые 10 отзывов
            review_dict = dict(review)
            rating = review_dict['rating']
            stars = "⭐" * rating
            reviewer_name = review_dict.get('reviewer_name', 'Аноним')
            comment = review_dict.get('comment', '')

            message_text += f"👤 <b>{reviewer_name}</b>\n"
            message_text += f"{stars} ({rating}/5)\n"
            if comment:
                # Обрезаем длинные комментарии
                if len(comment) > 150:
                    comment = comment[:150] + "..."
                message_text += f"💬 {comment}\n"
            message_text += "\n"

        if len(reviews) > 10:
            message_text += f"<i>Показано 10 из {len(reviews)} отзывов</i>\n"

        # Определяем callback для кнопки "Назад"
        if is_own_profile:
            # Если смотрим свой профиль - возврат в меню
            back_callback = "show_worker_menu" if role in ["blogger", "both"] else "show_client_menu"
        else:
            # Если смотрим чужой профиль - возврат в профиль
            back_callback = "worker_profile" if role in ["blogger", "both"] else "show_client_menu"

        await safe_edit_message(
            query,
            message_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)
            ]])
        )

    except Exception as e:
        logger.error(f"Ошибка при показе отзывов: {e}", exc_info=True)
        await safe_edit_message(
            query,
            "❌ <b>Ошибка при загрузке отзывов</b>\n\n"
            f"К сожалению, произошла ошибка: {str(e)}\n\n"
            "Попробуйте позже или обратитесь к администратору.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="show_worker_menu")
            ]])
        )


# ============================================
# КОНЕЦ СИСТЕМЫ ОТЗЫВОВ
# ============================================


# ============================================
# СИСТЕМА УВЕДОМЛЕНИЙ (ANNOUNCE)
# ============================================

# ===== NOTIFICATION HELPERS =====

def declension_orders(count):
    """Склонение слова 'кампания' в зависимости от числа"""
    if count % 10 == 1 and count % 100 != 11:
        return "доступная кампания"
    elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
        return "доступные кампании"
    else:
        return "доступных кампаний"


def declension_bids(count):
    """Склонение слова 'предложение' в зависимости от числа"""
    if count % 10 == 1 and count % 100 != 11:
        return "новое предложение"
    elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
        return "новых предложения"
    else:
        return "новых предложений"


async def notify_blogger_new_campaign(context, blogger_telegram_id, blogger_user_id, campaign_dict):
    """
    Уведомление блогеру о новом кампание - ОБНОВЛЯЕТ существующее сообщение.
    Вместо спама отдельными сообщениями показывает одно обновляемое сообщение с количеством.
    """
    try:
        # Проверяем включены ли уведомления у блогера
        if not db.are_notifications_enabled(blogger_user_id):
            logger.info(f"Уведомления отключены для блогера {blogger_user_id}, пропускаем отправку")
            return False

        # Подсчитываем все доступные кампании для этого блогера
        available_orders_count = db.count_available_orders_for_worker(blogger_user_id)

        advertiser_name = campaign_dict.get('advertiser_name', 'Не указан')
        budget_value = campaign_dict.get('budget_value')
        budget_str = f"{budget_value} BYN" if budget_value else "По договорённости"
        description = campaign_dict.get('description', '') or ''
        description_preview = (description[:80] + '…') if len(description) > 80 else description

        text = (
            f"🔔 <b>У вас {available_orders_count} {declension_orders(available_orders_count)}!</b>\n\n"
            f"👤 Рекламодатель: <b>{advertiser_name}</b>\n"
            f"💰 Бюджет: <b>{budget_str}</b>\n"
            + (f"📝 {description_preview}\n" if description_preview else "")
            + f"\n👇 Нажмите кнопку чтобы посмотреть все доступные кампании"
        )

        keyboard = [[InlineKeyboardButton("📋 Посмотреть кампании", callback_data="worker_view_orders")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Пытаемся получить существующее уведомление
        notification = db.get_worker_notification(blogger_user_id)

        try:
            # НОВАЯ ЛОГИКА: Удаляем старое уведомление, отправляем новое (всегда со звуком!)
            if notification and notification['notification_message_id']:
                try:
                    # Удаляем старое уведомление
                    await context.bot.delete_message(
                        chat_id=notification['notification_chat_id'],
                        message_id=notification['notification_message_id']
                    )
                    logger.info(f"🗑 Удалено старое уведомление для блогера {blogger_user_id}")
                except Exception as delete_error:
                    logger.warning(f"Не удалось удалить старое уведомление: {delete_error}")

            # Отправляем НОВОЕ уведомление (всегда со звуком!)
            msg = await context.bot.send_message(
                chat_id=blogger_telegram_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            # Сохраняем message_id для следующего удаления
            db.save_worker_notification(blogger_user_id, msg.message_id, blogger_telegram_id, available_orders_count)
            logger.info(f"✅ Отправлено новое уведомление блогеру {blogger_user_id}: {available_orders_count} заказов")

        except Exception as send_error:
            logger.error(f"Ошибка при отправке нового уведомления: {send_error}")
            return False

        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления блогеру {blogger_telegram_id}: {e}")
        return False


async def notify_advertiser_new_offer(context, advertiser_telegram_id, advertiser_user_id, campaign_id, blogger_name, price, currency):
    """
    Уведомление клиенту о новом предложение - ОБНОВЛЯЕТ существующее сообщение.
    Вместо спама отдельными сообщениями показывает одно обновляемое сообщение.
    """
    try:
        # Проверяем включены ли уведомления у клиента
        if not db.are_client_notifications_enabled(advertiser_user_id):
            logger.info(f"Уведомления отключены для клиента {advertiser_user_id}, пропускаем отправку")
            return False

        # Подсчитываем общее количество непрочитанных откликов
        orders_with_bids = db.get_orders_with_unread_bids(advertiser_user_id)
        total_bids = sum(campaign.get('offer_count', 0) for campaign in orders_with_bids)

        text = (
            f"🔔 <b>У вас {total_bids} {declension_bids(total_bids)}!</b>\n\n"
            f"📍 Последний: Кампания #{campaign_id} от {blogger_name} ({price} {currency})\n\n"
            f"👇 Нажмите кнопку чтобы посмотреть все отклики"
        )

        keyboard = [[InlineKeyboardButton("📂 Мои кампании", callback_data="client_my_orders")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Пытаемся получить существующее уведомление
        notification = db.get_client_notification(advertiser_user_id)

        try:
            # НОВАЯ ЛОГИКА: Удаляем старое уведомление, отправляем новое (всегда со звуком!)
            if notification and notification.get('notification_message_id'):
                try:
                    # Удаляем старое уведомление
                    await context.bot.delete_message(
                        chat_id=notification['notification_chat_id'],
                        message_id=notification['notification_message_id']
                    )
                    logger.info(f"🗑 Удалено старое уведомление для клиента {advertiser_user_id}")
                except Exception as delete_error:
                    logger.warning(f"Не удалось удалить старое уведомление: {delete_error}")

            # Отправляем НОВОЕ уведомление (всегда со звуком!)
            msg = await context.bot.send_message(
                chat_id=advertiser_telegram_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            # Сохраняем message_id для следующего удаления
            db.save_client_notification(advertiser_user_id, msg.message_id, advertiser_telegram_id, total_bids)
            logger.info(f"✅ Отправлено новое уведомление клиенту {advertiser_user_id}: {total_bids} откликов")

        except Exception as send_error:
            logger.error(f"Ошибка при отправке нового уведомления: {send_error}")
            return False

        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления клиенту {advertiser_telegram_id}: {e}")
        return False


async def notify_blogger_selected(context, blogger_telegram_id, campaign_id, advertiser_name, advertiser_phone):
    """Уведомление блогеру что его выбрали для кампания"""
    try:
        text = (
            f"🎉 <b>Вас выбрали!</b>\n\n"
            f"Клиент выбрал вас для выполнения кампания #{campaign_id}\n\n"
            f"📞 <b>Контакт клиента:</b>\n"
            f"Имя: {advertiser_name}\n"
            f"Телефон: <code>{advertiser_phone}</code>\n\n"
            f"✅ Свяжитесь с клиентом и обсудите детали кампания!\n\n"
            f"💡 После завершения работы не забудьте отметить кампанию как выполненную."
        )

        await context.bot.send_message(
            chat_id=blogger_telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления блогеру {blogger_telegram_id}: {e}")
        return False


async def notify_advertiser_master_selected(context, advertiser_telegram_id, campaign_id, blogger_name, blogger_phone):
    """Уведомление клиенту что он успешно выбрал блогера"""
    try:
        text = (
            f"✅ <b>Блогер выбран!</b>\n\n"
            f"Вы выбрали блогера для кампания #{campaign_id}\n\n"
            f"👤 <b>Контакт блогера:</b>\n"
            f"Имя: {blogger_name}\n"
            f"Телефон: <code>{blogger_phone}</code>\n\n"
            f"✅ Свяжитесь с мастером и обсудите детали кампания!\n\n"
            f"💡 После завершения контенты не забудьте отметить кампанию как выполненный и оставить отзыв."
        )

        await context.bot.send_message(
            chat_id=advertiser_telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления клиенту {advertiser_telegram_id}: {e}")
        return False


async def notify_completion_request(context, recipient_telegram_id, campaign_id, requester_role):
    """Уведомление о том что другая сторона отметила кампанию как завершённую"""
    role_text = "Клиент" if requester_role == "advertiser" else "Блогер"

    try:
        text = (
            f"✅ <b>Запрос на завершение кампания #{campaign_id}</b>\n\n"
            f"{role_text} отметил кампанию как выполненный.\n\n"
            f"Если контента действительно завершена, подтвердите завершение в разделе «Мои кампании».\n\n"
            f"💡 После подтверждения обеих сторон вы сможете оставить отзыв."
        )

        await context.bot.send_message(
            chat_id=recipient_telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления {recipient_telegram_id}: {e}")
        return False


async def notify_campaign_completed(context, telegram_id, campaign_id, role):
    """Уведомление об успешном завершении кампания"""
    try:
        text = (
            f"🎉 <b>Кампания #{campaign_id} завершён!</b>\n\n"
            f"Обе стороны подтвердили завершение кампания.\n\n"
            f"💬 Не забудьте оставить отзыв о {'блогере' if role == 'advertiser' else 'клиенте'}!\n\n"
            f"Это поможет другим пользователям сделать правильный выбор. 🤝"
        )

        await context.bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления {telegram_id}: {e}")
        return False


async def notify_new_review(context, telegram_id, reviewer_name, rating, campaign_id):
    """Уведомление о получении нового отзыва"""
    stars = "⭐" * int(rating)

    try:
        text = (
            f"📝 <b>Новый отзыв!</b>\n\n"
            f"👤 От: {reviewer_name}\n"
            f"{stars} {rating}/5\n"
            f"📋 Кампания: #{campaign_id}\n\n"
            f"Посмотрите отзыв в своём профиле!"
        )

        await context.bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления {telegram_id}: {e}")
        return False


async def enable_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /enable_premium для включения premium функций
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(user_telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    # Включаем premium функции
    db.set_premium_enabled(True)

    await update.message.reply_text(
        "✅ <b>Premium функции включены!</b>\n\n"
        "Теперь доступны:\n"
        "• Поднятие заказов в топ\n"
        "• Premium профили мастеров\n"
        "• Выделение в списках\n\n"
        "💡 Используйте /disable_premium для отключения",
        parse_mode="HTML"
    )


async def disable_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /disable_premium для отключения premium функций
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(user_telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    # Выключаем premium функции
    db.set_premium_enabled(False)

    await update.message.reply_text(
        "✅ <b>Premium функции отключены!</b>\n\n"
        "Все premium возможности скрыты от пользователей.\n\n"
        "💡 Используйте /enable_premium для включения",
        parse_mode="HTML"
    )


async def premium_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /premium_status для проверки статуса premium функций
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(user_telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    is_enabled = db.is_premium_enabled()

    status_emoji = "✅" if is_enabled else "❌"
    status_text = "Включены" if is_enabled else "Отключены"

    await update.message.reply_text(
        f"📊 <b>Статус Premium функций</b>\n\n"
        f"{status_emoji} Статус: <b>{status_text}</b>\n\n"
        f"<b>Доступные команды:</b>\n"
        f"/enable_premium - Включить premium\n"
        f"/disable_premium - Отключить premium\n"
        f"/premium_status - Проверить статус",
        parse_mode="HTML"
    )


async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /ban для блокировки пользователя
    Использование: /ban telegram_id причина
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(user_telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "📋 <b>Использование команды /ban</b>\n\n"
            "<code>/ban telegram_id причина</code>\n\n"
            "Пример:\n"
            "<code>/ban 123456789 Спам</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_telegram_id = int(context.args[0])
        reason = " ".join(context.args[1:])

        # Проверяем существование пользователя
        user = db.get_user(target_telegram_id)
        if not user:
            await update.message.reply_text(
                f"❌ Пользователь с ID {target_telegram_id} не найден в базе."
            )
            return

        # Нельзя забанить самого себя или другого админа
        if db.is_admin(target_telegram_id):
            await update.message.reply_text("❌ Нельзя забанить администратора.")
            return

        # Баним пользователя
        success = db.ban_user(target_telegram_id, reason, str(user_telegram_id))

        if success:
            await update.message.reply_text(
                f"✅ <b>Пользователь забанен</b>\n\n"
                f"ID: <code>{target_telegram_id}</code>\n"
                f"Причина: {reason}\n\n"
                f"Пользователь больше не сможет использовать бота.",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("❌ Ошибка при блокировке пользователя.")

    except ValueError:
        await update.message.reply_text("❌ Неверный формат Telegram ID. Используйте числовой ID.")
    except Exception as e:
        logger.error(f"Ошибка в ban_user_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /unban для разблокировки пользователя
    Использование: /unban telegram_id
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(user_telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "📋 <b>Использование команды /unban</b>\n\n"
            "<code>/unban telegram_id</code>\n\n"
            "Пример:\n"
            "<code>/unban 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_telegram_id = int(context.args[0])

        # Разбаниваем пользователя
        success = db.unban_user(target_telegram_id)

        if success:
            await update.message.reply_text(
                f"✅ <b>Пользователь разблокирован</b>\n\n"
                f"ID: <code>{target_telegram_id}</code>\n\n"
                f"Пользователь снова может использовать бота.",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"❌ Пользователь с ID {target_telegram_id} не найден или не был забанен."
            )

    except ValueError:
        await update.message.reply_text("❌ Неверный формат Telegram ID. Используйте числовой ID.")
    except Exception as e:
        logger.error(f"Ошибка в unban_user_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def banned_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /banned для просмотра списка забаненных пользователей
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(user_telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    banned_users = db.get_banned_users()

    if not banned_users:
        await update.message.reply_text("📋 Список забаненных пользователей пуст.")
        return

    text = "🚫 <b>Забаненные пользователи</b>\n\n"

    for user in banned_users[:10]:  # Показываем первых 10
        telegram_id = user[0]
        reason = user[1] or "Не указана"
        banned_at = user[2] or "Неизвестно"
        banned_by = user[3] or "Неизвестно"

        text += (
            f"👤 ID: <code>{telegram_id}</code>\n"
            f"📝 Причина: {reason}\n"
            f"📅 Дата: {banned_at}\n"
            f"👮 Забанил: {banned_by}\n\n"
        )

    text += f"\n<i>Всего забанено: {len(banned_users)}</i>"

    await update.message.reply_text(text, parse_mode="HTML")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /stats для просмотра статистики бота
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(user_telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    stats = db.get_analytics_stats()

    premium_status = "✅ Включены" if stats['premium_enabled'] else "❌ Отключены"

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 <b>Пользователи:</b>\n"
        f"• Всего: {stats['total_users']}\n"
        f"• Мастеров: {stats['total_workers']}\n"
        f"• Клиентов: {stats['total_clients']}\n"
        f"• Забанено: {stats['banned_users']}\n\n"
        f"📋 <b>Кампании:</b>\n"
        f"• Всего: {stats['total_orders']}\n"
        f"• Активных: {stats['active_orders']}\n"
        f"• Завершённых: {stats['completed_orders']}\n\n"
        f"💼 <b>Отклики:</b>\n"
        f"• Всего: {stats['total_bids']}\n"
        f"• Активных: {stats['active_bids']}\n\n"
        f"⭐ <b>Отзывы:</b> {stats['total_reviews']}\n\n"
        f"💎 <b>Premium:</b> {premium_status}"
    )

    await update.message.reply_text(text, parse_mode="HTML")


async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /announce для отправки уведомлений всем пользователям.
    Использование: /announce Текст сообщения
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(user_telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    # Извлекаем текст сообщения
    if not context.args:
        await update.message.reply_text(
            "📢 <b>Команда /announce</b>\n\n"
            "Использование:\n"
            "<code>/announce Текст уведомления</code>\n\n"
            "Пример:\n"
            "<code>/announce ⚠️ Завтра с 10:00 до 12:00 технические работы. Бот будет недоступен.</code>",
            parse_mode="HTML"
        )
        return

    message_text = " ".join(context.args)

    # Получаем всех пользователей
    telegram_ids = db.get_all_user_telegram_ids()

    if not telegram_ids:
        await update.message.reply_text("ℹ️ В базе нет пользователей для рассылки.")
        return

    # Отправляем уведомление
    await update.message.reply_text(
        f"📤 Начинаю рассылку {len(telegram_ids)} пользователям...\n"
        f"Текст:\n<i>{message_text}</i>",
        parse_mode="HTML"
    )

    sent_count = 0
    failed_count = 0

    for telegram_id in telegram_ids:
        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=f"📢 <b>Уведомление от администрации</b>\n\n{message_text}",
                parse_mode="HTML"
            )
            sent_count += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {telegram_id}: {e}")
            failed_count += 1

    # Отчет о рассылке
    await update.message.reply_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"✅ Отправлено: {sent_count}\n"
        f"❌ Не удалось: {failed_count}\n"
        f"📊 Всего: {len(telegram_ids)}",
        parse_mode="HTML"
    )


async def check_expired_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /check_expired_chats для проверки и обработки чатов где блогер не ответил в течение 24 часов.
    Эта команда также может быть запущена автоматически по расписанию (cron/scheduler).
    """
    user_telegram_id = update.effective_user.id

    # Проверка прав администратора
    if not db.is_admin(user_telegram_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    # Получаем все просроченные чаты (где блогер не ответил в течение 24 часов)
    expired_chats = db.get_expired_chats(hours=24)

    if not expired_chats:
        await update.message.reply_text("✅ Нет просроченных чатов (все блогера отвечают вовремя).")
        return

    await update.message.reply_text(
        f"🔍 Найдено просроченных чатов: {len(expired_chats)}\n"
        f"Начинаю обработку...",
        parse_mode="HTML"
    )

    processed_count = 0
    error_count = 0

    for chat in expired_chats:
        try:
            chat_id = chat['id']
            campaign_id = chat['campaign_id']
            advertiser_user_id = chat['advertiser_user_id']
            blogger_user_id = chat['blogger_user_id']
            offer_id = chat['offer_id']

            # Получаем информацию о кампание
            campaign = db.get_order_by_id(campaign_id)
            if not campaign:
                logger.warning(f"Кампания {campaign_id} не найдена для чата {chat_id}")
                error_count += 1
                continue

            # Получаем информацию о клиенте и блогере
            advertiser = db.get_user_by_id(advertiser_user_id)
            worker_user = db.get_user_by_id(blogger_user_id)

            if not advertiser or not worker_user:
                logger.warning(f"Пользователи не найдены для чата {chat_id}")
                error_count += 1
                continue

            # 1. Снижаем рейтинг блогера (добавляем негативную оценку 1.0 из 5.0)
            db.update_user_rating(blogger_user_id, 1.0, "blogger")

            # 2. Возвращаем кампанию в статус "open" (клиент может выбрать другого блогера)
            db.update_order_status(campaign_id, "open")

            # 3. Отмечаем предложение как отклоненное (чтобы не показывалось как выбранное)
            # Но НЕ удаляем его - клиент может увидеть, что этот блогер не ответил
            db.update_bid_status(offer_id, "rejected")

            # 4. Уведомляем клиента что блогер не ответил и он может выбрать другого БЕЗ доп. оплаты
            try:
                await context.bot.send_message(
                    chat_id=advertiser['telegram_id'],
                    text=(
                        f"⚠️ <b>Блогер не ответил в течение 24 часов</b>\n\n"
                        f"📋 Кампания: {campaign['title']}\n\n"
                        f"Ваша кампания снова открыта для выбора другого блогера.\n"
                        f"💰 Дополнительная оплата НЕ требуется - ваша предыдущая оплата остается активной.\n\n"
                        f"Просто выберите другого блогера из списка откликов."
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📋 Мои кампании", callback_data="client_my_orders")
                    ]])
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление клиенту {advertiser['telegram_id']}: {e}")

            # 5. Уведомляем блогера о снижении рейтинга
            try:
                await context.bot.send_message(
                    chat_id=worker_user['telegram_id'],
                    text=(
                        f"⚠️ <b>Ваш рейтинг снижен!</b>\n\n"
                        f"📋 Кампания: {campaign['title']}\n\n"
                        f"Вы не ответили клиенту в течение 24 часов после того, как ваше предложение было выбрано.\n"
                        f"📉 Ваш рейтинг был снижен.\n\n"
                        f"⚡ <b>Совет:</b> Отвечайте клиентам быстрее, чтобы поддерживать высокий рейтинг!"
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление блогеру {worker_user['telegram_id']}: {e}")

            processed_count += 1
            logger.info(f"Обработан просроченный чат {chat_id} (кампания {campaign_id})")

        except Exception as e:
            logger.error(f"Ошибка при обработке чата {chat.get('id', 'unknown')}: {e}")
            error_count += 1

    # Отчет о проверке
    await update.message.reply_text(
        f"✅ <b>Проверка завершена!</b>\n\n"
        f"✅ Обработано: {processed_count}\n"
        f"❌ Ошибок: {error_count}\n"
        f"📊 Всего найдено: {len(expired_chats)}",
        parse_mode="HTML"
    )




# ============================================
# КОНСТАНТЫ ДЛЯ CONVERSATION HANDLERS
# ============================================

# Состояния для админ-панели
ADMIN_MENU = 100
ADMIN_BAN_REASON = 101
ADMIN_SEARCH = 102
BROADCAST_SELECT_AUDIENCE = 103
BROADCAST_ENTER_MESSAGE = 104

# Состояния для создания рекламы
AD_TITLE = 105
AD_TEXT = 106
AD_URL = 107
AD_BUTTON_TEXT = 108
AD_AUDIENCE = 109  # Выбор целевой аудитории
AD_DURATION = 110  # Выбор продолжительности
AD_START_DATE = 111  # Выбор даты начала (отложенная публикация)
AD_CONFIRM = 112
AD_EDIT = 113  # Редактирование рекламы

# ============================================
# СИСТЕМА ПРЕДЛОЖЕНИЙ
# ============================================

# Состояния для ConversationHandler
SUGGESTION_TEXT = 50  # ИСПРАВЛЕНО: Уникальное значение, не конфликтует с range(50)


async def show_news_and_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает ВСЕ активные рекламы/новости пользователю"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADS] show_news_and_ads вызван пользователем {update.effective_user.id}")

    # Получаем информацию о пользователе
    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ Ошибка: пользователь не найден.")
        return

    user_dict = dict(user)

    # Определяем роль пользователя для правильной кнопки "Назад"
    role = user_dict.get('role', 'advertiser')
    back_callback = "show_worker_menu" if role in ['blogger', 'both'] else "show_client_menu"
    back_text = "🔙 Назад в меню блогера" if role in ['blogger', 'both'] else "🔙 Назад в меню"

    # Получаем ВСЕ активные рекламы для баннера в меню с фильтрацией по роли
    ads = db.get_active_ads('menu_banner', user_id=user_dict['id'], user_role=role)

    if not ads:
        # Если нет рекламы - показываем стандартное сообщение
        await query.edit_message_text(
            "📰 <b>Новости и акции</b>\n\n"
            "В данный момент нет активных новостей или акций.\n\n"
            "Следите за обновлениями! 🎯",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(back_text, callback_data=back_callback)
            ]])
        )
        logger.info(f"[ADS] Нет активной рекламы для пользователя {update.effective_user.id}")
        return

    # Редактируем первое сообщение (вместо кнопки "Новости и акции")
    first_ad = ads[0]
    message_text = f"🎯 <b>{first_ad['title']}</b>\n\n"
    message_text += f"{first_ad['description']}\n\n"

    # Формируем клавиатуру для первой рекламы
    keyboard = []
    if first_ad.get('button_text') and first_ad.get('button_url'):
        keyboard.append([InlineKeyboardButton(
            first_ad['button_text'],
            url=first_ad['button_url']
        )])

    # Для первой рекламы НЕ добавляем кнопку "Назад" (она будет в последней)

    await query.edit_message_text(
        message_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

    logger.info(f"[ADS] Показана реклама ID={first_ad['id']} пользователю {update.effective_user.id}")

    # Записываем просмотр первой рекламы
    try:
        db.record_ad_view(first_ad['id'], user_dict['id'])
        logger.info(f"[ADS] Записан просмотр рекламы ID={first_ad['id']}")
    except Exception as e:
        logger.error(f"[ADS] Ошибка записи просмотра рекламы: {e}")

    # Отправляем остальные рекламы как новые сообщения
    for i, ad_dict in enumerate(ads[1:], start=2):
        message_text = f"🎯 <b>{ad_dict['title']}</b>\n\n"
        message_text += f"{ad_dict['description']}\n\n"

        # Формируем клавиатуру
        keyboard = []
        if ad_dict.get('button_text') and ad_dict.get('button_url'):
            keyboard.append([InlineKeyboardButton(
                ad_dict['button_text'],
                url=ad_dict['button_url']
            )])

        # Добавляем кнопку "Назад" только к последней рекламе
        is_last = (i == len(ads))
        if is_last:
            keyboard.append([InlineKeyboardButton(back_text, callback_data=back_callback)])

        await update.effective_chat.send_message(
            message_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )

        logger.info(f"[ADS] Показана реклама ID={ad_dict['id']} пользователю {update.effective_user.id}")

        # Записываем просмотр рекламы
        try:
            db.record_ad_view(ad_dict['id'], user_dict['id'])
            logger.info(f"[ADS] Записан просмотр рекламы ID={ad_dict['id']}")
        except Exception as e:
            logger.error(f"[ADS] Ошибка записи просмотра рекламы: {e}")

    # Если была только одна реклама, отправляем отдельное сообщение с кнопкой "Назад"
    if len(ads) == 1:
        await update.effective_chat.send_message(
            "📰 Это все актуальные новости и акции на сегодня! 🎯",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(back_text, callback_data=back_callback)
            ]])
        )


async def send_suggestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса отправки предложения"""
    query = update.callback_query
    await query.answer()

    logger.info(f"🔍 send_suggestion_start вызван пользователем {update.effective_user.id}")

    # Устанавливаем флаг, чтобы handle_chat_message не перехватывал сообщения
    context.user_data['suggestion_active'] = True

    await query.edit_message_text(
        "💡 <b>Отправить предложение</b>\n\n"
        "Здесь вы можете отправить свои предложения по улучшению платформы:\n"
        "• Какие функции добавить\n"
        "• Что исправить\n"
        "• Как сделать удобнее\n\n"
        "📝 Просто напишите ваше предложение текстом (до 1000 символов):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_suggestion")
        ]])
    )

    logger.info(f"✅ Переход в состояние SUGGESTION_TEXT")
    return SUGGESTION_TEXT


async def receive_suggestion_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение текста предложения"""
    logger.info(f"[DEBUG] receive_suggestion_text ВЫЗВАН! Пользователь: {update.effective_user.id}")

    # КРИТИЧНО: Очищаем флаг сразу, чтобы предотвратить двойную обработку
    # Если произойдет ошибка ниже, флаг уже будет очищен и handle_chat_message
    # в group=1 не обработает это сообщение повторно
    context.user_data.pop('suggestion_active', None)
    logger.info(f"[FIX] Флаг suggestion_active очищен для пользователя {update.effective_user.id}")

    message = update.message
    text = message.text

    logger.info(f"🔍 receive_suggestion_text вызван пользователем {update.effective_user.id}. Текст: '{text[:50]}...'")

    # ИСПРАВЛЕНО: Показываем индикатор "печатает..." для визуальной обратной связи
    try:
        await message.chat.send_action(action="typing")
    except Exception as e:
        logger.warning(f"Не удалось отправить typing action: {e}")

    # Проверка длины
    if len(text) > 1000:
        await message.reply_text(
            "❌ Слишком длинное сообщение. Максимум 1000 символов.\n\n"
            "Попробуйте сократить ваше предложение:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_suggestion")
            ]])
        )
        return SUGGESTION_TEXT

    # Получаем информацию о пользователе
    user = db.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await message.reply_text("❌ Ошибка: пользователь не найден.")
        return ConversationHandler.END

    user_dict = dict(user)

    # Определяем роль пользователя
    worker_profile = db.get_worker_profile(user_dict['id'])
    client_profile = db.get_client_profile(user_dict['id'])

    if worker_profile and client_profile:
        user_role = 'both'
    elif worker_profile:
        user_role = 'blogger'
    elif client_profile:
        user_role = 'advertiser'
    else:
        user_role = 'unknown'

    # Сохраняем предложение
    try:
        suggestion_id = db.create_suggestion(user_dict['id'], user_role, text)
        logger.info(f"✅ Предложение #{suggestion_id} создано пользователем {user_dict['id']}")

        # Флаг уже очищен в начале функции

        # Определяем правильное меню для возврата
        menu_callback = "show_worker_menu" if user_role in ['blogger', 'both'] else "show_client_menu"

        logger.info(f"📤 Отправка подтверждения пользователю {update.effective_user.id} о получении предложения #{suggestion_id}")

        sent_message = await message.reply_text(
            "✅ <b>Спасибо за ваше предложение!</b>\n\n"
            f"📝 <b>Ваше предложение #{suggestion_id} получено!</b>\n\n"
            "Мы обязательно рассмотрим его и постараемся сделать платформу лучше!\n\n"
            "💡 Вы можете отправить еще предложения в любое время через меню.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💼 В главное меню", callback_data=menu_callback)
            ]])
        )

        logger.info(f"✅ Подтверждение успешно отправлено. Message ID: {sent_message.message_id}")

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при создании предложения: {e}", exc_info=True)

        # Флаг уже очищен в начале функции

        # Определяем правильное меню для возврата
        menu_callback = "show_worker_menu" if user_role in ['blogger', 'both'] else "show_client_menu"

        await message.reply_text(
            "❌ Произошла ошибка при отправке предложения.\n\n"
            "Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💼 В главное меню", callback_data=menu_callback)
            ]])
        )
        return ConversationHandler.END


async def cancel_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена отправки предложения"""
    query = update.callback_query
    await query.answer()

    # Очищаем флаг
    context.user_data.pop('suggestion_active', None)

    # Определяем меню для возврата
    user = db.get_user_by_telegram_id(update.effective_user.id)
    menu_callback = "show_worker_menu"
    if user:
        user_dict = dict(user)
        client_profile = db.get_client_profile(user_dict['id'])
        if client_profile and not db.get_worker_profile(user_dict['id']):
            menu_callback = "show_client_menu"

    await query.edit_message_text(
        "❌ Отправка предложения отменена.\n\n"
        "Вы можете вернуться к ней в любое время через меню.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("💼 В главное меню", callback_data=menu_callback)
        ]])
    )

    return ConversationHandler.END


# ============================================
# АДМИН-ПАНЕЛЬ И РЕКЛАМА
# ============================================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ-панель - доступна только админам (работает с командой /admin и callback)"""
    telegram_id = update.effective_user.id

    logger.info(f"[ADMIN] admin_panel вызвана пользователем {telegram_id}")

    if not db.is_admin(telegram_id):
        # Проверяем откуда пришел запрос - команда или callback
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("❌ У вас нет прав администратора.")
        else:
            await update.message.reply_text("❌ У вас нет прав администратора.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📈 Отчеты по категориям", callback_data="admin_category_reports")],
        [InlineKeyboardButton("📢 Рассылка сообщений", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📺 Создать рекламу", callback_data="admin_create_ad")],
        [InlineKeyboardButton("🎯 Управление рекламой", callback_data="admin_manage_ads")],
        [InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_users")],
        [InlineKeyboardButton("💡 Предложения", callback_data="admin_suggestions")],
        [InlineKeyboardButton("❌ Закрыть", callback_data="admin_close")],
    ]

    text = (
        "📱 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выберите действие:"
    )

    # Отправляем ответ в зависимости от типа запроса
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    logger.info(f"[ADMIN] Пользователь {telegram_id} вошёл в админ-панель, состояние ADMIN_MENU")
    return ADMIN_MENU


async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню админ-панели (для callback query)"""
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id

    if not db.is_admin(telegram_id):
        await query.edit_message_text("❌ У вас нет прав администратора.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📈 Отчеты по категориям", callback_data="admin_category_reports")],
        [InlineKeyboardButton("📢 Рассылка сообщений", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📺 Создать рекламу", callback_data="admin_create_ad")],
        [InlineKeyboardButton("🎯 Управление рекламой", callback_data="admin_manage_ads")],
        [InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_users")],
        [InlineKeyboardButton("💡 Предложения", callback_data="admin_suggestions")],
        [InlineKeyboardButton("❌ Закрыть", callback_data="admin_close")],
    ]

    await query.edit_message_text(
        "📱 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания broadcast"""
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    logger.info(f"[ADMIN] admin_broadcast_start вызвана пользователем {telegram_id}")

    # Проверка прав администратора
    if not db.is_admin(telegram_id):
        await query.edit_message_text("❌ У вас нет прав администратора.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("👥 Всем", callback_data="broadcast_all")],
        [InlineKeyboardButton("👷 Только мастерам", callback_data="broadcast_workers")],
        [InlineKeyboardButton("📋 Только клиентам", callback_data="broadcast_clients")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        "📢 <b>РАССЫЛКА СООБЩЕНИЙ</b>\n\n"
        "Кому отправить сообщение?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return BROADCAST_SELECT_AUDIENCE


async def admin_broadcast_select_audience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор аудитории для broadcast"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADMIN] admin_broadcast_select_audience вызвана пользователем {update.effective_user.id}, callback_data: {query.data}")

    # Проверка прав администратора
    if not db.is_admin(update.effective_user.id):
        await query.edit_message_text("❌ У вас нет прав администратора.")
        return ConversationHandler.END

    audience = query.data.replace("broadcast_", "")
    context.user_data['broadcast_audience'] = audience
    context.user_data['broadcast_active'] = True  # FIX B: Устанавливаем флаг для прямой маршрутизации

    logger.info(f"[FIX B] Установлен broadcast_active=True для пользователя {update.effective_user.id}, audience={audience}")

    audience_text = {
        'all': '👥 Всем пользователям',
        'workers': '👷 Только мастерам',
        'clients': '📋 Только клиентам'
    }.get(audience, 'Неизвестно')

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_broadcast_start")]]

    await query.edit_message_text(
        f"📢 <b>РАССЫЛКА СООБЩЕНИЙ</b>\n\n"
        f"Кому: {audience_text}\n\n"
        f"✏️ Теперь напишите текст сообщения.\n\n"
        f"Вы можете:\n"
        f"• Написать обычный текст\n"
        f"• Добавить ссылки (просто вставьте URL)\n"
        f"• Сделать <b>жирный текст</b> - напишите &lt;b&gt;ваш текст&lt;/b&gt;\n"
        f"• Сделать <i>курсивный текст</i> - напишите &lt;i&gt;ваш текст&lt;/i&gt;\n\n"
        f"Пример:\n"
        f"<code>⚠️ Завтра с 10:00 до 12:00 технические работы.\n"
        f"Бот может быть временно недоступен.\n"
        f"Подробнее: https://example.com</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return BROADCAST_ENTER_MESSAGE


async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка broadcast сообщения"""
    logger.info(f"[ADMIN] admin_broadcast_send вызвана пользователем {update.effective_user.id}, текст: {update.message.text[:50] if update.message and update.message.text else 'N/A'}")

    # Проверка прав администратора
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return ConversationHandler.END

    # КРИТИЧНО: Очищаем флаг сразу, чтобы предотвратить двойную обработку
    # Если произойдет ошибка ниже, флаг уже будет очищен и handle_chat_message
    # в group=1 не обработает это сообщение повторно
    context.user_data.pop('broadcast_active', None)
    logger.info(f"[FIX] Флаг broadcast_active очищен для пользователя {update.effective_user.id}")

    message_text = update.message.text
    audience = context.user_data.get('broadcast_audience', 'all')
    telegram_id = update.effective_user.id

    # Создаем broadcast в БД
    broadcast_id = db.create_broadcast(message_text, audience, None, telegram_id)

    # Получаем список пользователей
    users = db.get_all_users()  # Нужно создать эту функцию в db.py

    sent_count = 0
    failed_count = 0

    # Фильтруем по аудитории и отправляем
    for user in users:
        user_dict = dict(user)

        # Пропускаем забаненных пользователей
        if user_dict.get('is_banned'):
            continue

        # Проверяем аудиторию
        if audience == 'workers':
            blogger = db.get_worker_profile(user_dict['id'])
            if not blogger:
                continue
        elif audience == 'clients':
            advertiser = db.get_client_profile(user_dict['id'])
            if not advertiser:
                continue

        # Отправляем сообщение
        try:
            await context.bot.send_message(
                chat_id=user_dict['telegram_id'],
                text=message_text,
                parse_mode="HTML"
            )
            sent_count += 1
        except Exception as e:
            logger.error(f"Ошибка отправки broadcast пользователю {user_dict['telegram_id']}: {e}")
            failed_count += 1

    # Обновляем статистику в БД
    with db.get_db_connection() as conn:
        cursor = db.get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            UPDATE broadcasts
            SET sent_at = ?, sent_count = ?, failed_count = ?
            WHERE id = ?
        """, (now, sent_count, failed_count, broadcast_id))
        conn.commit()

    keyboard = [[InlineKeyboardButton("🔙 В админ панель", callback_data="admin_panel")]]

    await update.message.reply_text(
        f"✅ <b>Broadcast отправлен!</b>\n\n"
        f"📊 Отправлено: {sent_count}\n"
        f"❌ Ошибок: {failed_count}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    # Флаг уже очищен в начале функции
    return ConversationHandler.END


async def admin_create_ad_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало пошагового создания рекламы"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADMIN] admin_create_ad_start вызвана пользователем {update.effective_user.id}")

    # Очищаем данные рекламы и устанавливаем флаг для direct_routing
    context.user_data['ad_data'] = {}
    context.user_data['ad_step'] = 'title'

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]

    await query.edit_message_text(
        "📺 <b>СОЗДАНИЕ РЕКЛАМЫ - Шаг 1/7</b>\n\n"
        "📝 <b>Введите заголовок рекламы</b>\n\n"
        "Заголовок должен быть коротким и привлекательным.\n"
        "Максимум 100 символов.\n\n"
        "Пример: <code>Скидка 20% на все услуги!</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return AD_TITLE


async def admin_ad_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение заголовка рекламы"""
    logger.info(f"[ADMIN] admin_ad_title вызвана пользователем {update.effective_user.id}")

    title = update.message.text

    if len(title) > 100:
        await update.message.reply_text(
            "❌ Заголовок слишком длинный. Максимум 100 символов.\n\n"
            "Попробуйте еще раз:"
        )
        return AD_TITLE

    context.user_data['ad_data']['title'] = title
    context.user_data['ad_step'] = 'text'

    await update.message.reply_text(
        "📺 <b>СОЗДАНИЕ РЕКЛАМЫ - Шаг 2/7</b>\n\n"
        "📝 <b>Введите текст рекламы</b>\n\n"
        "Опишите ваше предложение подробнее.\n"
        "Максимум 500 символов.\n\n"
        "Пример: <code>Только до конца месяца! Воспользуйтесь промокодом REMONT20</code>",
        parse_mode="HTML"
    )

    return AD_TEXT


async def admin_ad_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение текста рекламы"""
    logger.info(f"[ADMIN] admin_ad_text вызвана пользователем {update.effective_user.id}")

    text = update.message.text

    if len(text) > 500:
        await update.message.reply_text(
            "❌ Текст слишком длинный. Максимум 500 символов.\n\n"
            "Попробуйте еще раз:"
        )
        return AD_TEXT

    context.user_data['ad_step'] = 'url'
    context.user_data['ad_data']['text'] = text

    await update.message.reply_text(
        "📺 <b>СОЗДАНИЕ РЕКЛАМЫ - Шаг 3/7</b>\n\n"
        "🔗 <b>Введите URL ссылки</b>\n\n"
        "Куда будет вести кнопка рекламы?\n\n"
        "Пример: <code>https://example.com/promo</code>\n\n"
        "Или отправьте <code>-</code> если ссылка не нужна",
        parse_mode="HTML"
    )

    return AD_URL


async def admin_ad_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение URL рекламы"""
    logger.info(f"[ADMIN] admin_ad_url вызвана пользователем {update.effective_user.id}")

    url = update.message.text

    if url != "-" and not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            "❌ Неверный формат URL. Должен начинаться с http:// или https://\n\n"
            "Попробуйте еще раз или отправьте <code>-</code> если ссылка не нужна:",
            parse_mode="HTML"
        )
        return AD_URL

    context.user_data['ad_data']['url'] = None if url == "-" else url
    context.user_data['ad_step'] = 'button_text'

    await update.message.reply_text(
        "📺 <b>СОЗДАНИЕ РЕКЛАМЫ - Шаг 4/7</b>\n\n"
        "🔘 <b>Введите текст кнопки</b>\n\n"
        "Что будет написано на кнопке?\n"
        "Максимум 30 символов.\n\n"
        "Пример: <code>Узнать подробнее</code>\n\n"
        "Или отправьте <code>-</code> если кнопка не нужна",
        parse_mode="HTML"
    )

    return AD_BUTTON_TEXT


async def admin_ad_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение текста кнопки"""
    logger.info(f"[ADMIN] admin_ad_button_text вызвана пользователем {update.effective_user.id}")

    button_text = update.message.text

    if button_text != "-" and len(button_text) > 30:
        await update.message.reply_text(
            "❌ Текст кнопки слишком длинный. Максимум 30 символов.\n\n"
            "Попробуйте еще раз:"
        )
        return AD_BUTTON_TEXT

    context.user_data['ad_data']['button_text'] = None if button_text == "-" else button_text
    context.user_data.pop('ad_step', None)  # Очищаем флаг, дальше будут CallbackQuery

    # Автоматически устанавливаем размещение = баннер в меню
    context.user_data['ad_data']['placement'] = 'menu_banner'

    logger.info(f"[AD] Переход к выбору целевой аудитории")

    # Переходим к выбору целевой аудитории
    keyboard = [
        [
            InlineKeyboardButton("👥 Всем", callback_data="ad_audience_all"),
        ],
        [
            InlineKeyboardButton("📱 Только мастерам", callback_data="ad_audience_workers"),
            InlineKeyboardButton("👤 Только клиентам", callback_data="ad_audience_clients"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="ad_confirm_no")]
    ]

    await update.message.reply_text(
        "📺 <b>СОЗДАНИЕ РЕКЛАМЫ - Шаг 5/7</b>\n\n"
        "👥 <b>Выберите целевую аудиторию</b>\n\n"
        "Кому будет показана реклама?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return AD_AUDIENCE


async def admin_ad_audience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора целевой аудитории"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADMIN] admin_ad_audience вызвана пользователем {update.effective_user.id}, callback_data: {query.data}")

    # Проверка наличия данных рекламы
    if 'ad_data' not in context.user_data:
        logger.warning(f"[AD] Нет ad_data для пользователя {update.effective_user.id}, пропускаем")
        await query.edit_message_text("❌ Ошибка: данные рекламы не найдены. Начните создание заново.")
        return ADMIN_MENU

    # Определяем аудиторию
    if query.data == "ad_audience_all":
        target_audience = "all"
        audience_text = "👥 Всем"
    elif query.data == "ad_audience_workers":
        target_audience = "workers"
        audience_text = "📱 Только мастерам"
    elif query.data == "ad_audience_clients":
        target_audience = "clients"
        audience_text = "👤 Только клиентам"
    else:
        await query.edit_message_text("❌ Неверный выбор аудитории")
        return ADMIN_MENU

    context.user_data['ad_data']['target_audience'] = target_audience
    logger.info(f"[AD] Выбрана аудитория: {target_audience}")

    # Переходим к выбору продолжительности
    keyboard = [
        [InlineKeyboardButton("📅 7 дней", callback_data="ad_duration_7")],
        [InlineKeyboardButton("📅 14 дней", callback_data="ad_duration_14")],
        [InlineKeyboardButton("📅 30 дней", callback_data="ad_duration_30")],
        [InlineKeyboardButton("📅 Без ограничения", callback_data="ad_duration_unlimited")],
        [InlineKeyboardButton("❌ Отмена", callback_data="ad_confirm_no")]
    ]

    await query.edit_message_text(
        f"📺 <b>СОЗДАНИЕ РЕКЛАМЫ - Шаг 6/7</b>\n\n"
        f"✅ Аудитория: {audience_text}\n\n"
        f"📅 <b>Выберите продолжительность показа</b>\n\n"
        f"Как долго реклама будет активна?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return AD_DURATION


async def admin_ad_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора продолжительности рекламы"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADMIN] admin_ad_duration вызвана пользователем {update.effective_user.id}, callback_data: {query.data}")

    # Проверка наличия данных рекламы
    if 'ad_data' not in context.user_data:
        logger.warning(f"[AD] Нет ad_data для пользователя {update.effective_user.id}, пропускаем")
        await query.edit_message_text("❌ Ошибка: данные рекламы не найдены. Начните создание заново.")
        return ADMIN_MENU

    # Определяем длительность
    if query.data == "ad_duration_7":
        duration_days = 7
        duration_text = "7 дней"
    elif query.data == "ad_duration_14":
        duration_days = 14
        duration_text = "14 дней"
    elif query.data == "ad_duration_30":
        duration_days = 30
        duration_text = "30 дней"
    elif query.data == "ad_duration_unlimited":
        duration_days = None
        duration_text = "Без ограничения"
    else:
        await query.edit_message_text("❌ Неверный выбор продолжительности")
        return ADMIN_MENU

    context.user_data['ad_data']['duration_days'] = duration_days
    logger.info(f"[AD] Выбрана продолжительность: {duration_days} дней")

    # Получаем данные для отображения
    target_audience = context.user_data['ad_data'].get('target_audience', 'all')
    if target_audience == 'all':
        audience_text = "👥 Всем"
    elif target_audience == 'workers':
        audience_text = "📱 Только мастерам"
    else:
        audience_text = "👤 Только клиентам"

    # Переходим к выбору даты начала
    keyboard = [
        [InlineKeyboardButton("▶️ Начать сейчас", callback_data="ad_start_now")],
        [InlineKeyboardButton("⏰ Отложить на 1 час", callback_data="ad_start_1h")],
        [InlineKeyboardButton("⏰ Отложить на 1 день", callback_data="ad_start_1d")],
        [InlineKeyboardButton("⏰ Отложить на 3 дня", callback_data="ad_start_3d")],
        [InlineKeyboardButton("⏰ Отложить на 7 дней", callback_data="ad_start_7d")],
        [InlineKeyboardButton("❌ Отмена", callback_data="ad_confirm_no")]
    ]

    await query.edit_message_text(
        f"📺 <b>СОЗДАНИЕ РЕКЛАМЫ - Шаг 7/7</b>\n\n"
        f"✅ Аудитория: {audience_text}\n"
        f"✅ Продолжительность: {duration_text}\n\n"
        f"⏰ <b>Когда начать показ рекламы?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return AD_START_DATE


async def admin_ad_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора даты начала и показ превью"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADMIN] admin_ad_start_date вызвана пользователем {update.effective_user.id}, callback_data: {query.data}")

    # Проверка наличия данных рекламы
    if 'ad_data' not in context.user_data:
        logger.warning(f"[AD] Нет ad_data для пользователя {update.effective_user.id}, пропускаем")
        await query.edit_message_text("❌ Ошибка: данные рекламы не найдены. Начните создание заново.")
        return ADMIN_MENU

    from datetime import datetime, timedelta

    # Определяем дату начала
    now = datetime.now()
    if query.data == "ad_start_now":
        start_date = now
        start_text = "▶️ Сейчас"
    elif query.data == "ad_start_1h":
        start_date = now + timedelta(hours=1)
        start_text = f"⏰ {start_date.strftime('%d.%m.%Y %H:%M')}"
    elif query.data == "ad_start_1d":
        start_date = now + timedelta(days=1)
        start_text = f"⏰ {start_date.strftime('%d.%m.%Y %H:%M')}"
    elif query.data == "ad_start_3d":
        start_date = now + timedelta(days=3)
        start_text = f"⏰ {start_date.strftime('%d.%m.%Y %H:%M')}"
    elif query.data == "ad_start_7d":
        start_date = now + timedelta(days=7)
        start_text = f"⏰ {start_date.strftime('%d.%m.%Y %H:%M')}"
    else:
        await query.edit_message_text("❌ Неверный выбор даты начала")
        return ADMIN_MENU

    context.user_data['ad_data']['start_datetime'] = start_date
    logger.info(f"[AD] Выбрана дата начала: {start_date}")

    # Вычисляем дату окончания
    duration_days = context.user_data['ad_data'].get('duration_days')
    if duration_days:
        end_date = start_date + timedelta(days=duration_days)
        end_text = end_date.strftime('%d.%m.%Y %H:%M')
    else:
        end_date = None
        end_text = "Без ограничения"

    context.user_data['ad_data']['end_datetime'] = end_date

    # Получаем данные для отображения
    ad_data = context.user_data['ad_data']
    target_audience = ad_data.get('target_audience', 'all')
    if target_audience == 'all':
        audience_text = "👥 Всем"
    elif target_audience == 'workers':
        audience_text = "📱 Только мастерам"
    else:
        audience_text = "👤 Только клиентам"

    duration_days = ad_data.get('duration_days')
    if duration_days:
        duration_text = f"{duration_days} дней"
    else:
        duration_text = "Без ограничения"

    # Формируем превью рекламы
    preview = (
        "📺 <b>ПРЕДПРОСМОТР РЕКЛАМЫ</b>\n\n"
        f"<b>{ad_data['title']}</b>\n\n"
        f"{ad_data['text']}\n\n"
    )

    if ad_data.get('url') and ad_data.get('button_text'):
        preview += f"🔘 Кнопка: {ad_data['button_text']}\n"
        preview += f"🔗 URL: {ad_data['url']}\n\n"

    preview += f"📍 Размещение: 💼 Баннер в меню\n"
    preview += f"👥 Аудитория: {audience_text}\n"
    preview += f"📅 Продолжительность: {duration_text}\n"
    preview += f"⏰ Начало: {start_text}\n"
    if end_date:
        preview += f"🏁 Окончание: {end_text}\n"
    preview += "\nСоздать эту рекламу?"

    keyboard = [
        [InlineKeyboardButton("✅ Создать", callback_data="ad_confirm_yes")],
        [InlineKeyboardButton("❌ Отмена", callback_data="ad_confirm_no")]
    ]

    await query.edit_message_text(
        preview,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    logger.info(f"[AD] Отправлено подтверждение с полными настройками")
    return AD_CONFIRM


async def admin_ad_placement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор размещения рекламы"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADMIN] admin_ad_placement вызвана пользователем {update.effective_user.id}, callback_data: {query.data}")

    # Проверка наличия данных рекламы
    if 'ad_data' not in context.user_data:
        logger.warning(f"[AD] Нет ad_data для пользователя {update.effective_user.id}, пропускаем")
        await query.edit_message_text("❌ Ошибка: данные рекламы не найдены. Начните создание заново.")
        return ADMIN_MENU

    placement = query.data.replace("ad_placement_", "")
    context.user_data['ad_data']['placement'] = placement

    logger.info(f"[AD] Выбрано размещение: {placement}")

    ad_data = context.user_data['ad_data']
    placement_text = "💼 Баннер в меню" if placement == "menu_banner" else "☀️ Утренняя рассылка"

    # Формируем превью
    preview = (
        "📺 <b>ПРЕДПРОСМОТР РЕКЛАМЫ</b>\n\n"
        f"<b>{ad_data['title']}</b>\n\n"
        f"{ad_data['text']}\n\n"
    )

    if ad_data.get('url') and ad_data.get('button_text'):
        preview += f"🔘 Кнопка: {ad_data['button_text']}\n"
        preview += f"🔗 URL: {ad_data['url']}\n\n"

    preview += f"📍 Размещение: {placement_text}\n\n"
    preview += "Создать эту рекламу?"

    keyboard = [
        [InlineKeyboardButton("✅ Создать", callback_data="ad_confirm_yes")],
        [InlineKeyboardButton("❌ Отмена", callback_data="ad_confirm_no")]
    ]

    await query.edit_message_text(
        preview,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    logger.info(f"[AD] Переходим в состояние AD_CONFIRM для обработки подтверждения")
    return AD_CONFIRM


async def admin_ad_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение создания рекламы"""
    logger.info(f"[AD_CONFIRM] ✅ ФУНКЦИЯ ВЫЗВАНА! Пользователь: {update.effective_user.id}")

    query = update.callback_query
    await query.answer()

    logger.info(f"[AD_CONFIRM] Callback data: {query.data}")
    logger.info(f"[AD_CONFIRM] Context user_data: {context.user_data}")

    if query.data == "ad_confirm_no":
        logger.info(f"[AD] Создание рекламы отменено пользователем {update.effective_user.id}")
        await query.edit_message_text(
            "❌ Создание рекламы отменено.",
            parse_mode="HTML"
        )
        # Очищаем только данные рекламы, не весь user_data
        context.user_data.pop('ad_data', None)
        context.user_data.pop('ad_step', None)
        return ADMIN_MENU

    # Проверка наличия данных рекламы
    if 'ad_data' not in context.user_data:
        logger.warning(f"[AD] Нет ad_data для пользователя {update.effective_user.id}, пропускаем")
        await query.edit_message_text("❌ Ошибка: данные рекламы не найдены. Начните создание заново.")
        return ADMIN_MENU

    # Создаем рекламу
    ad_data = context.user_data['ad_data']

    logger.info(f"[AD] Создание рекламы: {ad_data}")

    try:
        # Используем выбранные даты или defaults
        start_datetime = ad_data.get('start_datetime', datetime.now())
        end_datetime = ad_data.get('end_datetime')

        # Форматируем даты для БД
        start_date = start_datetime.strftime("%Y-%m-%d %H:%M:%S")
        end_date = end_datetime.strftime("%Y-%m-%d %H:%M:%S") if end_datetime else None

        # Используем выбранную аудиторию
        target_audience = ad_data.get('target_audience', 'all')

        ad_id = db.create_ad(
            title=ad_data['title'],
            description=ad_data['text'],  # ИСПРАВЛЕНО: text -> description
            photo_file_id=None,  # У нас нет фото в текущей реализации
            button_text=ad_data.get('button_text'),
            button_url=ad_data.get('url'),  # ИСПРАВЛЕНО: url -> button_url
            target_audience=target_audience,
            placement=ad_data['placement'],
            start_date=start_date,
            end_date=end_date,
            max_views_per_user_per_day=3,  # Максимум 3 показа в день
            created_by=update.effective_user.id,
            categories=None  # Без таргетинга по категориям
        )

        placement_text = "💼 Баннер в меню" if ad_data['placement'] == "menu_banner" else "☀️ Утренняя рассылка"

        if target_audience == 'all':
            audience_text = "👥 Всем"
        elif target_audience == 'workers':
            audience_text = "📱 Только мастерам"
        else:
            audience_text = "👤 Только клиентам"

        duration_info = ""
        if end_date:
            duration_info = f"📅 Действует до {end_datetime.strftime('%d.%m.%Y %H:%M')}\n"
        else:
            duration_info = "📅 Действует без ограничения срока\n"

        logger.info(f"✅ Реклама создана: ID={ad_id}")

        await query.edit_message_text(
            f"✅ <b>Реклама создана!</b>\n\n"
            f"📺 ID рекламы: #{ad_id}\n"
            f"📍 Размещение: {placement_text}\n"
            f"👥 Аудитория: {audience_text}\n"
            f"⏰ Начало: {start_datetime.strftime('%d.%m.%Y %H:%M')}\n"
            f"{duration_info}"
            f"👀 Максимум 3 показа в день на пользователя\n\n"
            "Реклама будет показана пользователям согласно настройкам.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 В админ панель", callback_data="admin_panel")
            ]])
        )

        logger.info(f"✅ Реклама #{ad_id} создана пользователем {update.effective_user.id}")

    except Exception as e:
        logger.error(f"Ошибка создания рекламы: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при создании рекламы:\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Админ-панель", callback_data="admin_panel")
            ]])
        )

    # Очищаем только данные рекламы, не весь user_data
    context.user_data.pop('ad_data', None)
    context.user_data.pop('ad_step', None)
    return ADMIN_MENU


# ============================================================
# УПРАВЛЕНИЕ РЕКЛАМАМИ
# ============================================================

async def admin_manage_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню управления рекламами с разделением на категории"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADMIN] admin_manage_ads вызвана пользователем {update.effective_user.id}")

    # Получаем статистику по рекламам
    all_ads = db.get_all_ads()
    active_count = sum(1 for ad in all_ads if dict(ad)['active'])
    inactive_count = len(all_ads) - active_count

    keyboard = [
        [InlineKeyboardButton(f"✅ Активные рекламы ({active_count})", callback_data="admin_ads_active")],
        [InlineKeyboardButton(f"❌ Неактивные рекламы ({inactive_count})", callback_data="admin_ads_inactive")],
        [InlineKeyboardButton("📋 Все рекламы", callback_data="admin_ads_all")],
        [InlineKeyboardButton("🔙 В админ панель", callback_data="admin_panel")]
    ]

    await query.edit_message_text(
        "📺 <b>УПРАВЛЕНИЕ РЕКЛАМОЙ</b>\n\n"
        f"Всего реклам: {len(all_ads)}\n"
        f"├ Активных: {active_count}\n"
        f"└ Неактивных: {inactive_count}\n\n"
        "Выберите категорию:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_list_ads_by_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список реклам по выбранному статусу"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADMIN] admin_list_ads_by_status вызвана, callback: {query.data}")

    # Определяем фильтр
    if query.data == "admin_ads_active":
        filter_active = True
        status_text = "АКТИВНЫЕ"
    elif query.data == "admin_ads_inactive":
        filter_active = False
        status_text = "НЕАКТИВНЫЕ"
    else:  # admin_ads_all
        filter_active = None
        status_text = "ВСЕ"

    # Получаем рекламы
    all_ads = db.get_all_ads()

    # Фильтруем по статусу
    if filter_active is not None:
        ads = [ad for ad in all_ads if dict(ad)['active'] == filter_active]
    else:
        ads = all_ads

    if not ads:
        await query.edit_message_text(
            f"📺 <b>{status_text} РЕКЛАМЫ</b>\n\n"
            f"📭 Реклам в этой категории пока нет.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_manage_ads")
            ]])
        )
        return ADMIN_MENU

    # Формируем список реклам
    message_text = f"📺 <b>{status_text} РЕКЛАМЫ</b>\n\n"
    message_text += f"Найдено: {len(ads)}\n\n"

    keyboard = []

    for ad in ads[:20]:  # Показываем максимум 20
        ad_dict = dict(ad)
        status_icon = "✅" if ad_dict['active'] else "❌"
        placement_icon = "💼" if ad_dict['placement'] == 'menu_banner' else "☀️"

        # Получаем статистику
        stats = db.get_ad_stats(ad_dict['id'])

        button_text = (
            f"{status_icon} {placement_icon} #{ad_dict['id']}: {ad_dict['title'][:25]} "
            f"(👁 {stats.get('total_views', 0)})"
        )

        keyboard.append([InlineKeyboardButton(
            button_text,
            callback_data=f"admin_view_ad_{ad_dict['id']}"
        )])

    # Добавляем кнопки навигации
    keyboard.append([InlineKeyboardButton("🔙 Назад к категориям", callback_data="admin_manage_ads")])
    keyboard.append([InlineKeyboardButton("💼 В админ панель", callback_data="admin_panel")])

    await query.edit_message_text(
        message_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_view_ad_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную информацию о рекламе"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID рекламы из callback_data
    ad_id = int(query.data.split('_')[-1])

    logger.info(f"[ADMIN] admin_view_ad_detail: ad_id={ad_id}")

    # Получаем рекламу
    ad = db.get_ad_by_id(ad_id)

    if not ad:
        await query.edit_message_text(
            "❌ Реклама не найдена.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К списку реклам", callback_data="admin_manage_ads")
            ]])
        )
        return ADMIN_MENU

    # Получаем статистику
    stats = db.get_ad_stats(ad_id)

    # Формируем сообщение
    status_text = "✅ Активна" if ad['active'] else "❌ Неактивна"
    placement_text = "💼 Баннер в меню" if ad['placement'] == 'menu_banner' else "☀️ Утренняя рассылка"

    message_text = f"📺 <b>РЕКЛАМА #{ad_id}</b>\n\n"
    message_text += f"<b>{ad['title']}</b>\n\n"
    message_text += f"{ad['description']}\n\n"

    if ad['button_text'] and ad['button_url']:
        message_text += f"🔘 Кнопка: {ad['button_text']}\n"
        message_text += f"🔗 URL: {ad['button_url']}\n\n"

    message_text += f"📍 Размещение: {placement_text}\n"
    message_text += f"📊 Статус: {status_text}\n\n"

    message_text += f"📈 <b>Статистика:</b>\n"
    message_text += f"👁 Просмотров: {stats['total_views']}\n"
    message_text += f"👤 Уникальных: {stats['unique_users']}\n"
    message_text += f"🖱 Кликов: {stats['total_clicks']}\n\n"

    if ad['start_date']:
        message_text += f"📅 С: {ad['start_date']}\n"
    if ad['end_date']:
        message_text += f"📅 До: {ad['end_date']}\n"

    # Кнопки управления
    keyboard = []

    # Кнопка активации/деактивации
    toggle_text = "❌ Деактивировать" if ad['active'] else "✅ Активировать"
    keyboard.append([InlineKeyboardButton(toggle_text, callback_data=f"admin_toggle_ad_{ad_id}")])

    # Кнопка редактирования
    keyboard.append([InlineKeyboardButton("✏️ Редактировать", callback_data=f"admin_edit_ad_{ad_id}")])

    # Кнопка удаления
    keyboard.append([InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_delete_ad_confirm_{ad_id}")])

    # Кнопка назад
    keyboard.append([InlineKeyboardButton("🔙 К списку реклам", callback_data="admin_manage_ads")])

    await query.edit_message_text(
        message_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_toggle_ad_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает активность рекламы"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID рекламы
    ad_id = int(query.data.split('_')[-1])

    logger.info(f"[ADMIN] admin_toggle_ad_status: ad_id={ad_id}")

    # Переключаем статус
    new_status = db.toggle_ad_active(ad_id)

    if new_status is None:
        await query.answer("❌ Реклама не найдена", show_alert=True)
        return ADMIN_MENU

    status_text = "активирована" if new_status else "деактивирована"
    await query.answer(f"✅ Реклама {status_text}", show_alert=True)

    # Перезагружаем детали рекламы
    context.user_data['callback_data'] = f"admin_view_ad_{ad_id}"
    return await admin_view_ad_detail(update, context)


async def admin_edit_ad_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню редактирования рекламы"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID рекламы
    ad_id = int(query.data.split('_')[-1])

    logger.info(f"[ADMIN] admin_edit_ad_menu: ad_id={ad_id}")

    # Получаем рекламу
    ad = db.get_ad_by_id(ad_id)

    if not ad:
        await query.edit_message_text(
            "❌ Реклама не найдена.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К списку реклам", callback_data="admin_manage_ads")
            ]])
        )
        return ADMIN_MENU

    # Сохраняем ID в контексте
    context.user_data['editing_ad_id'] = ad_id

    message_text = f"✏️ <b>РЕДАКТИРОВАНИЕ РЕКЛАМЫ #{ad_id}</b>\n\n"
    message_text += "Выберите, что хотите изменить:"

    keyboard = [
        [InlineKeyboardButton("📝 Заголовок", callback_data=f"admin_edit_field_title_{ad_id}")],
        [InlineKeyboardButton("📄 Описание", callback_data=f"admin_edit_field_description_{ad_id}")],
        [InlineKeyboardButton("🔘 Текст кнопки", callback_data=f"admin_edit_field_button_text_{ad_id}")],
        [InlineKeyboardButton("🔗 URL кнопки", callback_data=f"admin_edit_field_button_url_{ad_id}")],
        [InlineKeyboardButton("📅 Срок действия", callback_data=f"admin_edit_field_dates_{ad_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"admin_view_ad_{ad_id}")],
    ]

    await query.edit_message_text(
        message_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_edit_ad_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает редактирование конкретного поля рекламы"""
    query = update.callback_query
    await query.answer()

    # Парсим callback_data: admin_edit_field_{field}_{ad_id}
    parts = query.data.split('_')
    field = parts[3]  # title, description, button_text, button_url, dates
    ad_id = int(parts[-1])

    logger.info(f"[ADMIN] admin_edit_ad_field: ad_id={ad_id}, field={field}")

    # Сохраняем в контексте
    context.user_data['editing_ad_id'] = ad_id
    context.user_data['editing_field'] = field
    context.user_data['ad_edit_step'] = field  # Для direct_routing

    # Формируем сообщение в зависимости от поля
    field_names = {
        'title': ('заголовок', 'Введите новый заголовок рекламы:'),
        'description': ('описание', 'Введите новое описание рекламы:'),
        'button_text': ('текст кнопки', 'Введите новый текст кнопки (или "-" чтобы убрать):'),
        'button_url': ('URL кнопки', 'Введите новый URL кнопки:'),
        'dates': ('срок действия', 'Введите количество дней (например, 30):'),
    }

    field_name, prompt = field_names.get(field, ('поле', 'Введите новое значение:'))

    await query.edit_message_text(
        f"✏️ <b>РЕДАКТИРОВАНИЕ: {field_name.upper()}</b>\n\n"
        f"{prompt}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data=f"admin_view_ad_{ad_id}")
        ]])
    )

    return AD_EDIT


async def admin_delete_ad_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления рекламы"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID рекламы
    ad_id = int(query.data.split('_')[-1])

    logger.info(f"[ADMIN] admin_delete_ad_confirm: ad_id={ad_id}")

    # Получаем рекламу
    ad = db.get_ad_by_id(ad_id)

    if not ad:
        await query.edit_message_text(
            "❌ Реклама не найдена.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К списку реклам", callback_data="admin_manage_ads")
            ]])
        )
        return ADMIN_MENU

    message_text = f"⚠️ <b>УДАЛЕНИЕ РЕКЛАМЫ</b>\n\n"
    message_text += f"Вы действительно хотите удалить рекламу?\n\n"
    message_text += f"<b>#{ad_id}: {ad['title']}</b>\n\n"
    message_text += "Это действие нельзя отменить!"

    keyboard = [
        [InlineKeyboardButton("🗑 Да, удалить", callback_data=f"admin_delete_ad_yes_{ad_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"admin_view_ad_{ad_id}")],
    ]

    await query.edit_message_text(
        message_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_delete_ad_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет рекламу"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID рекламы
    ad_id = int(query.data.split('_')[-1])

    logger.info(f"[ADMIN] admin_delete_ad_yes: ad_id={ad_id}")

    # Удаляем рекламу
    success = db.delete_ad(ad_id)

    if success:
        await query.answer("✅ Реклама удалена", show_alert=True)
        await query.edit_message_text(
            f"✅ Реклама #{ad_id} успешно удалена.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К списку реклам", callback_data="admin_manage_ads")
            ]])
        )
    else:
        await query.answer("❌ Ошибка удаления", show_alert=True)

    return ADMIN_MENU


async def admin_process_ad_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовый ввод для редактирования рекламы"""
    if 'editing_ad_id' not in context.user_data or 'editing_field' not in context.user_data:
        # Если нет данных редактирования - игнорируем
        return ADMIN_MENU

    ad_id = context.user_data['editing_ad_id']
    field = context.user_data['editing_field']
    new_value = update.message.text.strip()

    logger.info(f"[ADMIN] admin_process_ad_edit: ad_id={ad_id}, field={field}, value={new_value[:50]}")

    try:
        # Валидация и обновление в зависимости от поля
        if field == 'title':
            if len(new_value) > 100:
                await update.message.reply_text(
                    "❌ Заголовок слишком длинный (макс. 100 символов). Попробуйте еще раз:"
                )
                return ADMIN_MENU

            db.update_ad(ad_id, title=new_value)
            await update.message.reply_text(
                f"✅ Заголовок обновлен!\n\n<b>Новый заголовок:</b>\n{new_value}",
                parse_mode="HTML"
            )

        elif field == 'description':
            if len(new_value) > 500:
                await update.message.reply_text(
                    "❌ Описание слишком длинное (макс. 500 символов). Попробуйте еще раз:"
                )
                return ADMIN_MENU

            db.update_ad(ad_id, description=new_value)
            await update.message.reply_text(
                f"✅ Описание обновлено!\n\n<b>Новое описание:</b>\n{new_value}",
                parse_mode="HTML"
            )

        elif field == 'button_text':
            if new_value == '-':
                new_value = None

            db.update_ad(ad_id, button_text=new_value)
            text = "✅ Кнопка удалена!" if new_value is None else f"✅ Текст кнопки обновлен: {new_value}"
            await update.message.reply_text(text)

        elif field == 'button_url':
            # Простая валидация URL
            if not new_value.startswith('http'):
                await update.message.reply_text(
                    "❌ URL должен начинаться с http:// или https://\nПопробуйте еще раз:"
                )
                return ADMIN_MENU

            db.update_ad(ad_id, button_url=new_value)
            await update.message.reply_text(f"✅ URL обновлен: {new_value}")

        elif field == 'dates':
            # Обновляем срок действия
            try:
                days = int(new_value)
                if days < 1 or days > 365:
                    await update.message.reply_text(
                        "❌ Количество дней должно быть от 1 до 365.\nПопробуйте еще раз:"
                    )
                    return ADMIN_MENU

                from datetime import datetime, timedelta
                new_end_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                db.update_ad(ad_id, end_date=new_end_date)

                await update.message.reply_text(
                    f"✅ Срок действия обновлен!\n\n"
                    f"📅 Действует {days} дней до {new_end_date.split()[0]}"
                )

            except ValueError:
                await update.message.reply_text(
                    "❌ Введите число (количество дней).\nПопробуйте еще раз:"
                )
                return ADMIN_MENU

        # Очищаем данные редактирования
        context.user_data.pop('editing_ad_id', None)
        context.user_data.pop('editing_field', None)
        context.user_data.pop('ad_edit_step', None)

        # Показываем детали обновленной рекламы
        ad = db.get_ad_by_id(ad_id)
        stats = db.get_ad_stats(ad_id)

        status_text = "✅ Активна" if ad['active'] else "❌ Неактивна"
        placement_text = "💼 Баннер в меню" if ad['placement'] == 'menu_banner' else "☀️ Утренняя рассылка"

        message_text = f"\n📺 <b>РЕКЛАМА #{ad_id}</b>\n\n"
        message_text += f"<b>{ad['title']}</b>\n\n"
        message_text += f"{ad['description']}\n\n"

        if ad['button_text'] and ad['button_url']:
            message_text += f"🔘 Кнопка: {ad['button_text']}\n"
            message_text += f"🔗 URL: {ad['button_url']}\n\n"

        message_text += f"📍 Размещение: {placement_text}\n"
        message_text += f"📊 Статус: {status_text}\n\n"

        message_text += f"📈 <b>Статистика:</b>\n"
        message_text += f"👁 Просмотров: {stats['total_views']}\n"
        message_text += f"👤 Уникальных: {stats['unique_users']}\n"
        message_text += f"🖱 Кликов: {stats['total_clicks']}"

        keyboard = [
            [InlineKeyboardButton(
                "❌ Деактивировать" if ad['active'] else "✅ Активировать",
                callback_data=f"admin_toggle_ad_{ad_id}"
            )],
            [InlineKeyboardButton("✏️ Редактировать", callback_data=f"admin_edit_ad_{ad_id}")],
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_delete_ad_confirm_{ad_id}")],
            [InlineKeyboardButton("🔙 К списку реклам", callback_data="admin_manage_ads")],
        ]

        await update.message.reply_text(
            message_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"[ADMIN] Ошибка при редактировании рекламы: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при обновлении: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К списку реклам", callback_data="admin_manage_ads")
            ]])
        )

        # Очищаем данные
        context.user_data.pop('editing_ad_id', None)
        context.user_data.pop('editing_field', None)
        context.user_data.pop('ad_edit_step', None)

    return ADMIN_MENU


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подробная статистика системы"""
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    logger.info(f"[ADMIN] admin_stats вызвана пользователем {telegram_id}")

    # Получаем статистику из БД
    stats = db.get_analytics_stats()

    # Добавляем timestamp для обновления
    from datetime import datetime
    current_time = datetime.now().strftime("%H:%M:%S")

    text = f"📊 <b>СТАТИСТИКА ПЛАТФОРМЫ</b>\n"
    text += f"🕐 Обновлено: {current_time}\n\n"

    # Пользователи
    text += "👥 <b>ПОЛЬЗОВАТЕЛИ:</b>\n"
    text += f"• Всего: {stats['total_users']}\n"
    text += f"• Блогеров: {stats['total_workers']}\n"
    text += f"• Рекламодателей: {stats['total_clients']}\n"
    text += f"• С двумя профилями: {stats['dual_profile_users']}\n"
    text += f"• Забанено: {stats['banned_users']}\n\n"

    # Кампании
    text += "📦 <b>ЗАКАЗЫ:</b>\n"
    text += f"• Всего создано: {stats['total_orders']}\n"
    text += f"• Открытые: {stats['open_orders']}\n"
    text += f"• В работе: {stats['active_orders']}\n"
    text += f"• Завершённые: {stats['completed_orders']}\n"
    text += f"• Отменённые: {stats['canceled_orders']}\n\n"

    # Отклики
    text += "💼 <b>ОТКЛИКИ:</b>\n"
    text += f"• Всего откликов: {stats['total_bids']}\n"
    text += f"• Ожидают ответа: {stats['pending_bids']}\n"
    text += f"• Приняты: {stats['selected_bids']}\n"
    text += f"• Отклонены: {stats['rejected_bids']}\n\n"

    # Отзывы
    text += "⭐ <b>ОТЗЫВЫ:</b>\n"
    text += f"• Оставлено отзывов: {stats['total_reviews']}\n"
    text += f"• Средний рейтинг: {stats['average_rating']:.1f} ⭐\n\n"

    # Активность
    text += "📈 <b>АКТИВНОСТЬ:</b>\n"
    text += f"• Заказов за последние 24ч: {stats['orders_last_24h']}\n"
    text += f"• Новых пользователей за 7 дней: {stats['users_last_7days']}\n\n"

    # Статистика по подписчикам
    followers_stats = db.get_followers_stats()
    text += "📊 <b>АУДИТОРИЯ БЛОГЕРОВ:</b>\n"
    text += f"• До 1K: {followers_stats['under_1k']}\n"
    text += f"• 1K - 5K: {followers_stats['1k_5k']}\n"
    text += f"• 5K - 20K: {followers_stats['5k_20k']}\n"
    text += f"• 20K - 50K: {followers_stats['20k_50k']}\n"
    text += f"• 50K - 100K: {followers_stats['50k_100k']}\n"
    text += f"• 100K+: {followers_stats['over_100k']}"

    keyboard = [
        [InlineKeyboardButton("📥 Экспорт данных", callback_data="admin_export_menu")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")]
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню экспорта данных"""
    query = update.callback_query
    await query.answer()

    text = "📥 <b>ЭКСПОРТ ДАННЫХ</b>\n\n"
    text += "Выберите, какие данные экспортировать в CSV:"

    keyboard = [
        [InlineKeyboardButton("👥 Экспорт пользователей", callback_data="admin_export_users")],
        [InlineKeyboardButton("📦 Экспорт заказов", callback_data="admin_export_orders")],
        [InlineKeyboardButton("💼 Экспорт откликов", callback_data="admin_export_bids")],
        [InlineKeyboardButton("⭐ Экспорт отзывов", callback_data="admin_export_reviews")],
        [InlineKeyboardButton("📊 Сводная статистика", callback_data="admin_export_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_stats")]
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспортирует выбранные данные в CSV"""
    query = update.callback_query
    await query.answer("Подготовка данных...")

    export_type = query.data.replace("admin_export_", "")

    try:
        import csv
        import io
        from datetime import datetime

        # Создаем CSV в памяти
        output = io.StringIO()
        writer = csv.writer(output)

        if export_type == "users":
            users = db.get_all_users()
            # Заголовки
            writer.writerow(["ID", "Telegram ID", "Имя", "Username", "Дата регистрации", "Забанен", "Причина бана"])
            # Данные
            for user in users:
                user_dict = dict(user)
                created_at = user_dict.get('created_at', '')
                if isinstance(created_at, datetime):
                    created_at = created_at.strftime('%Y-%m-%d %H:%M:%S')
                writer.writerow([
                    user_dict.get('id', ''),
                    user_dict.get('telegram_id', ''),
                    user_dict.get('full_name', ''),
                    user_dict.get('username', ''),
                    created_at,
                    'Да' if user_dict.get('is_banned') else 'Нет',
                    user_dict.get('ban_reason', '')
                ])
            filename = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            caption = f"📊 Экспорт пользователей ({len(users)} записей)"

        elif export_type == "orders":
            orders = db.get_all_orders_for_export()
            writer.writerow(["ID кампания", "Клиент ID", "Название", "Категория", "Город", "Статус", "Дата создания", "Описание"])
            for campaign in orders:
                campaign_dict = dict(campaign)
                created_at = campaign_dict.get('created_at', '')
                if isinstance(created_at, datetime):
                    created_at = created_at.strftime('%Y-%m-%d %H:%M:%S')
                writer.writerow([
                    campaign_dict.get('id', ''),
                    campaign_dict.get('client_id', ''),
                    campaign_dict.get('title', ''),
                    campaign_dict.get('category', ''),
                    campaign_dict.get('city', ''),
                    campaign_dict.get('status', ''),
                    created_at,
                    campaign_dict.get('description', '')[:100]
                ])
            filename = f"orders_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            caption = f"📦 Экспорт заказов ({len(orders)} записей)"

        elif export_type == "bids":
            bids = db.get_all_bids_for_export()
            writer.writerow(["ID предложения", "Кампания ID", "Блогер ID", "Цена", "Валюта", "Дней до готовности", "Статус", "Дата создания"])
            for offer in bids:
                bid_dict = dict(offer)
                created_at = bid_dict.get('created_at', '')
                if isinstance(created_at, datetime):
                    created_at = created_at.strftime('%Y-%m-%d %H:%M:%S')
                writer.writerow([
                    bid_dict.get('id', ''),
                    bid_dict.get('campaign_id', ''),
                    bid_dict.get('worker_id', ''),
                    bid_dict.get('price', ''),
                    bid_dict.get('currency', ''),
                    bid_dict.get('ready_days', ''),
                    bid_dict.get('status', ''),
                    created_at
                ])
            filename = f"bids_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            caption = f"💼 Экспорт откликов ({len(bids)} записей)"

        elif export_type == "reviews":
            reviews = db.get_all_reviews_for_export()
            writer.writerow(["ID отзыва", "Кампания ID", "От пользователя", "К пользователю", "Рейтинг", "Комментарий", "Дата"])
            for review in reviews:
                review_dict = dict(review)
                created_at = review_dict.get('created_at', '')
                if isinstance(created_at, datetime):
                    created_at = created_at.strftime('%Y-%m-%d %H:%M:%S')
                writer.writerow([
                    review_dict.get('id', ''),
                    review_dict.get('campaign_id', ''),
                    review_dict.get('from_user_id', ''),
                    review_dict.get('to_user_id', ''),
                    review_dict.get('rating', ''),
                    review_dict.get('comment', '')[:100],
                    created_at
                ])
            filename = f"reviews_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            caption = f"⭐ Экспорт отзывов ({len(reviews)} записей)"

        elif export_type == "stats":
            stats = db.get_analytics_stats()
            writer.writerow(["Метрика", "Значение"])
            writer.writerow(["Всего пользователей", stats['total_users']])
            writer.writerow(["Мастеров", stats['total_workers']])
            writer.writerow(["Клиентов", stats['total_clients']])
            writer.writerow(["С двумя профилями", stats['dual_profile_users']])
            writer.writerow(["Забанено", stats['banned_users']])
            writer.writerow(["Всего заказов", stats['total_orders']])
            writer.writerow(["Открытые кампании", stats['open_orders']])
            writer.writerow(["Активные кампании", stats['active_orders']])
            writer.writerow(["Завершённые кампании", stats['completed_orders']])
            writer.writerow(["Отменённые кампании", stats['canceled_orders']])
            writer.writerow(["Всего откликов", stats['total_bids']])
            writer.writerow(["Ожидают ответа", stats['pending_bids']])
            writer.writerow(["Приняты", stats['selected_bids']])
            writer.writerow(["Отклонены", stats['rejected_bids']])
            writer.writerow(["Активных чатов", stats['total_chats']])
            writer.writerow(["Всего сообщений", stats['total_messages']])
            writer.writerow(["Всего отзывов", stats['total_reviews']])
            writer.writerow(["Средний рейтинг", f"{stats['average_rating']:.2f}"])
            writer.writerow(["Заказов за 24ч", stats['orders_last_24h']])
            writer.writerow(["Новых пользователей за 7 дней", stats['users_last_7days']])
            filename = f"stats_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            caption = "📊 Сводная статистика платформы"

        # Конвертируем в байты
        csv_data = output.getvalue().encode('utf-8-sig')  # utf-8-sig для правильного отображения в Excel
        csv_file = io.BytesIO(csv_data)
        csv_file.name = filename

        # Отправляем файл
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=csv_file,
            filename=filename,
            caption=caption
        )

        # Возвращаемся в меню экспорта
        text = "✅ Данные успешно экспортированы!\n\n"
        text += "Файл отправлен выше. Выберите другой тип данных для экспорта или вернитесь назад."

        keyboard = [
            [InlineKeyboardButton("📥 Экспортировать еще", callback_data="admin_export_menu")],
            [InlineKeyboardButton("⬅️ К статистике", callback_data="admin_stats")]
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка экспорта данных: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Ошибка при экспорте данных: {str(e)}\n\n"
            "Попробуйте еще раз или обратитесь к разработчику.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_export_menu")
            ]])
        )

    return ADMIN_MENU


async def admin_category_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подробные отчеты по категориям, городам и специализациям"""
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    logger.info(f"[ADMIN] admin_category_reports вызвана пользователем {telegram_id}")

    try:
        reports = db.get_category_reports()

        text = "📈 <b>ОТЧЕТЫ ПО КАТЕГОРИЯМ</b>\n\n"

        # ТОП КАТЕГОРИЙ ЗАКАЗОВ
        text += "🏆 <b>ТОП-10 КАТЕГОРИЙ ЗАКАЗОВ:</b>\n"
        if reports['top_categories']:
            for i, row in enumerate(reports['top_categories'][:10], 1):
                row_dict = dict(row)
                category = row_dict.get('category', 'Неизвестно')
                count = row_dict.get('count', 0)
                text += f"{i}. {category}: <b>{count}</b>\n"
        else:
            text += "Нет данных\n"

        text += "\n"

        # ТОП ГОРОДОВ
        text += "🏙 <b>ТОП-10 ГОРОДОВ ПО ЗАКАЗАМ:</b>\n"
        if reports['top_cities_orders']:
            for i, row in enumerate(reports['top_cities_orders'][:10], 1):
                row_dict = dict(row)
                city = row_dict.get('city', 'Неизвестно')
                count = row_dict.get('count', 0)
                text += f"{i}. {city}: <b>{count}</b>\n"
        else:
            text += "Нет данных\n"

        text += "\n"

        # ТОП СПЕЦИАЛИЗАЦИЙ МАСТЕРОВ
        text += "👷 <b>ТОП-10 СПЕЦИАЛИЗАЦИЙ:</b>\n"
        if reports['top_specializations']:
            for i, row in enumerate(reports['top_specializations'][:10], 1):
                row_dict = dict(row)
                spec = row_dict.get('categories', 'Неизвестно')
                count = row_dict.get('count', 0)
                text += f"{i}. {spec}: <b>{count}</b>\n"
        else:
            text += "Нет данных\n"

        keyboard = [
            [InlineKeyboardButton("🌍 Активность по городам", callback_data="admin_city_activity")],
            [InlineKeyboardButton("💰 Средние цены", callback_data="admin_avg_prices")],
            [InlineKeyboardButton("📊 Статусы по категориям", callback_data="admin_category_statuses")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")]
        ]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в admin_category_reports: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Ошибка при получении отчетов: {str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
            ]])
        )

    return ADMIN_MENU


async def admin_city_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная активность по городам"""
    query = update.callback_query
    await query.answer()

    try:
        reports = db.get_category_reports()

        text = "🌍 <b>АКТИВНОСТЬ ПО ГОРОДАМ</b>\n\n"

        if reports['city_activity']:
            for i, city_data in enumerate(reports['city_activity'][:10], 1):
                city = city_data['city']
                orders = city_data['orders']
                workers = city_data['workers']
                total = city_data['total']
                text += f"{i}. <b>{city}</b>\n"
                text += f"   📦 Заказов: {orders}\n"
                text += f"   👷 Мастеров: {workers}\n"
                text += f"   📊 Всего активности: {total}\n\n"
        else:
            text += "Нет данных\n"

        keyboard = [[InlineKeyboardButton("⬅️ Назад к отчетам", callback_data="admin_category_reports")]]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в admin_city_activity: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка при получении данных",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_category_reports")
            ]])
        )

    return ADMIN_MENU


async def admin_avg_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Средние цены по категориям"""
    query = update.callback_query
    await query.answer()

    try:
        reports = db.get_category_reports()

        text = "💰 <b>СРЕДНИЕ ЦЕНЫ ПО КАТЕГОРИЯМ</b>\n\n"
        text += "<i>(Только для категорий с минимум 3 откликами в BYN)</i>\n\n"

        if reports['avg_prices_by_category']:
            for i, row in enumerate(reports['avg_prices_by_category'][:10], 1):
                row_dict = dict(row)
                category = row_dict.get('category', 'Неизвестно')
                avg_price = row_dict.get('avg_price', 0)
                bid_count = row_dict.get('bid_count', 0)
                text += f"{i}. <b>{category}</b>\n"
                text += f"   Средняя цена: {avg_price:.2f} BYN\n"
                text += f"   Откликов: {bid_count}\n\n"
        else:
            text += "Недостаточно данных для анализа\n"

        keyboard = [[InlineKeyboardButton("⬅️ Назад к отчетам", callback_data="admin_category_reports")]]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в admin_avg_prices: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка при получении данных",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_category_reports")
            ]])
        )

    return ADMIN_MENU


async def admin_category_statuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статусы заказов по категориям"""
    query = update.callback_query
    await query.answer()

    try:
        reports = db.get_category_reports()

        text = "📊 <b>СТАТУСЫ ЗАКАЗОВ ПО КАТЕГОРИЯМ</b>\n\n"

        if reports['category_statuses']:
            for row in reports['category_statuses'][:10]:
                row_dict = dict(row)
                category = row_dict.get('category', 'Неизвестно')
                open_count = row_dict.get('open_count', 0)
                active_count = row_dict.get('active_count', 0)
                completed_count = row_dict.get('completed_count', 0)
                total_count = row_dict.get('total_count', 0)

                text += f"<b>{category}</b> (всего: {total_count})\n"
                text += f"  🟢 Открытые: {open_count}\n"
                text += f"  🔵 В работе: {active_count}\n"
                text += f"  ✅ Завершённые: {completed_count}\n\n"
        else:
            text += "Нет данных\n"

        keyboard = [[InlineKeyboardButton("⬅️ Назад к отчетам", callback_data="admin_category_reports")]]

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Ошибка в admin_category_statuses: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка при получении данных",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_category_reports")
            ]])
        )

    return ADMIN_MENU


async def admin_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления пользователями"""
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    logger.info(f"[ADMIN] admin_users_menu вызвана пользователем {telegram_id}")

    stats = db.get_analytics_stats()

    text = "👥 <b>УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ</b>\n\n"
    text += f"Всего пользователей: {stats['total_users']}\n"
    text += f"Мастеров: {stats['total_workers']}\n"
    text += f"Клиентов: {stats['total_clients']}\n"
    text += f"Забанено: {stats['banned_users']}\n\n"
    text += "Выберите фильтр или воспользуйтесь поиском:"

    keyboard = [
        [InlineKeyboardButton("👤 Все пользователи", callback_data="admin_users_list_all")],
        [InlineKeyboardButton("👷 Только блогера", callback_data="admin_users_list_workers")],
        [InlineKeyboardButton("📋 Только клиенты", callback_data="admin_users_list_clients")],
        [InlineKeyboardButton("🔄 Оба профиля", callback_data="admin_users_list_dual")],
        [InlineKeyboardButton("🚫 Забаненные", callback_data="admin_users_list_banned")],
        [InlineKeyboardButton("🔍 Поиск пользователя", callback_data="admin_user_search_start")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")]
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список пользователей с выбранным фильтром"""
    query = update.callback_query
    await query.answer()

    # Парсим фильтр из callback_data или из user_data (если вызвано из admin_users_page)
    if 'admin_users_filter' in context.user_data and not query.data.startswith("admin_users_list_"):
        filter_type = context.user_data['admin_users_filter']
    else:
        filter_type = query.data.replace("admin_users_list_", "")
    page = context.user_data.get('admin_users_page', 1)

    users = db.get_users_filtered(filter_type, page=page, per_page=10)

    if not users:
        text = "👥 <b>Пользователи не найдены</b>\n\n"
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_users")]]
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ADMIN_MENU

    filter_names = {
        'all': 'Все пользователи',
        'workers': 'Блогера',
        'clients': 'Клиенты',
        'dual': 'С двумя профилями',
        'banned': 'Забаненные'
    }

    text = f"👥 <b>{filter_names.get(filter_type, 'Пользователи')}</b>\n"
    text += f"Страница {page}\n\n"

    keyboard = []
    for user in users:
        user_dict = dict(user)
        name = user_dict.get('full_name', 'Без имени')
        telegram_id = user_dict['telegram_id']

        # Эмодзи статуса
        status_emoji = "🚫" if user_dict.get('is_banned') else ""

        # Тип профиля
        profile_type = ""
        if user_dict.get('worker_id') and user_dict.get('client_id'):
            profile_type = "👷📋"
        elif user_dict.get('worker_id'):
            profile_type = "👷"
        elif user_dict.get('client_id'):
            profile_type = "📋"

        button_text = f"{status_emoji}{profile_type} {name[:25]}"
        keyboard.append([InlineKeyboardButton(
            button_text,
            callback_data=f"admin_user_view_{telegram_id}"
        )])

    # Навигация
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Предыдущая", callback_data=f"admin_users_page_{filter_type}_{page-1}"))
    if len(users) == 10:  # Полная страница = возможно есть следующая
        nav_row.append(InlineKeyboardButton("➡️ Следующая", callback_data=f"admin_users_page_{filter_type}_{page+1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="admin_users")])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_users_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик пагинации списка пользователей"""
    query = update.callback_query
    await query.answer()

    # Парсим callback_data: admin_users_page_{filter}_{page}
    parts = query.data.split("_")
    # parts[0] = 'admin', parts[1] = 'users', parts[2] = 'page', parts[3] = filter, parts[4] = page
    filter_type = parts[3]
    page = int(parts[4])

    # Сохраняем страницу и фильтр в контекст для admin_users_list
    context.user_data['admin_users_page'] = page
    context.user_data['admin_users_filter'] = filter_type

    # Вызываем основной обработчик списка пользователей
    return await admin_users_list(update, context)


async def admin_user_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную информацию о пользователе"""
    query = update.callback_query
    await query.answer()

    telegram_id = int(query.data.replace("admin_user_view_", ""))
    details = db.get_user_details_for_admin(telegram_id)

    if not details:
        await query.edit_message_text("❌ Пользователь не найден.")
        return ADMIN_MENU

    user = details['user']
    blogger = details['worker_profile']
    advertiser = details['client_profile']
    stats = details['stats']

    # Форматируем информацию
    text = "👤 <b>ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ</b>\n\n"

    # Основная информация
    text += f"<b>Имя:</b> {user.get('full_name', 'Не указано')}\n"
    text += f"<b>Username:</b> @{user.get('username', 'нет')}\n"
    text += f"<b>Telegram ID:</b> <code>{user['telegram_id']}</code>\n"
    text += f"<b>Статус:</b> {'🚫 Забанен' if user.get('is_banned') else '✅ Активен'}\n"

    if user.get('is_banned'):
        text += f"<b>Причина бана:</b> {user.get('ban_reason', 'Не указана')}\n"

    from datetime import datetime
    created_at = user.get('created_at')
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if created_at:
        text += f"<b>Регистрация:</b> {created_at.strftime('%d.%m.%Y %H:%M')}\n"

    # Профили
    text += f"\n<b>ПРОФИЛИ:</b>\n"
    if blogger:
        text += f"👷 <b>Блогер</b>\n"
        text += f"  • Специализация: {blogger.get('specialization', 'Не указана')}\n"
        if stats.get('total_bids'):
            text += f"  • Откликов: {stats['total_bids']} (принято: {stats.get('accepted_bids', 0)})\n"
        if stats.get('worker_rating'):
            text += f"  • Рейтинг: {stats['worker_rating']:.1f} ⭐\n"

    if advertiser:
        text += f"📋 <b>Клиент</b>\n"
        if stats.get('total_orders'):
            text += f"  • Заказов создано: {stats['total_orders']}\n"
            text += f"  • Завершено: {stats.get('completed_orders', 0)}\n"

    if not blogger and not advertiser:
        text += "❌ Нет активных профилей\n"

    # Кнопки действий
    keyboard = []
    if user.get('is_banned'):
        keyboard.append([InlineKeyboardButton("✅ Разбанить", callback_data=f"admin_user_unban_{telegram_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🚫 Забанить", callback_data=f"admin_user_ban_start_{telegram_id}")])

    keyboard.append([InlineKeyboardButton("⬅️ Назад к списку", callback_data="admin_users")])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_user_ban_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса бана пользователя"""
    query = update.callback_query
    await query.answer()

    telegram_id = int(query.data.replace("admin_user_ban_start_", ""))
    context.user_data['admin_ban_user_id'] = telegram_id

    text = "🚫 <b>БАН ПОЛЬЗОВАТЕЛЯ</b>\n\n"
    text += f"Telegram ID: <code>{telegram_id}</code>\n\n"
    text += "Отправьте причину бана или нажмите \"Отмена\":"

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data=f"admin_user_view_{telegram_id}")]]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_BAN_REASON


async def admin_user_ban_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполняет бан пользователя с указанной причиной"""
    telegram_id = context.user_data.get('admin_ban_user_id')
    if not telegram_id:
        await update.message.reply_text("❌ Ошибка: пользователь не выбран.")
        return ConversationHandler.END

    reason = update.message.text.strip()
    admin_telegram_id = update.effective_user.id

    success = db.ban_user(telegram_id, reason, admin_telegram_id)

    if success:
        text = f"✅ Пользователь <code>{telegram_id}</code> забанен.\n"
        text += f"Причина: {reason}"
    else:
        text = "❌ Ошибка при бане пользователя."

    keyboard = [[InlineKeyboardButton("⬅️ К управлению пользователями", callback_data="admin_users")]]

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    context.user_data.pop('admin_ban_user_id', None)
    return ADMIN_MENU


async def admin_user_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разбанивает пользователя"""
    query = update.callback_query
    await query.answer()

    telegram_id = int(query.data.replace("admin_user_unban_", ""))

    success = db.unban_user(telegram_id)

    if success:
        text = f"✅ Пользователь <code>{telegram_id}</code> разбанен."
    else:
        text = "❌ Ошибка при разбане пользователя."

    keyboard = [
        [InlineKeyboardButton("👤 Посмотреть профиль", callback_data=f"admin_user_view_{telegram_id}")],
        [InlineKeyboardButton("⬅️ К управлению пользователями", callback_data="admin_users")]
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_user_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало поиска пользователя"""
    query = update.callback_query
    await query.answer()

    text = "🔍 <b>ПОИСК ПОЛЬЗОВАТЕЛЯ</b>\n\n"
    text += "Введите для поиска:\n"
    text += "• Telegram ID\n"
    text += "• Имя пользователя\n"
    text += "• Username (без @)\n\n"
    text += "Или нажмите \"Отмена\":"

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_users")]]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_SEARCH


async def admin_user_search_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполняет поиск пользователя"""
    query_text = update.message.text.strip()

    users = db.search_users(query_text, limit=10)

    if not users:
        text = f"🔍 По запросу '<code>{query_text}</code>' ничего не найдено."
        keyboard = [[InlineKeyboardButton("🔍 Новый поиск", callback_data="admin_user_search_start")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="admin_users")]]

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ADMIN_MENU

    text = f"🔍 <b>Результаты поиска:</b> '<code>{query_text}</code>'\n\n"
    text += f"Найдено пользователей: {len(users)}\n\n"

    keyboard = []
    for user in users:
        user_dict = dict(user)
        name = user_dict.get('full_name', 'Без имени')
        telegram_id = user_dict['telegram_id']

        # Эмодзи статуса
        status_emoji = "🚫" if user_dict.get('is_banned') else ""

        # Тип профиля
        profile_type = ""
        if user_dict.get('worker_id') and user_dict.get('client_id'):
            profile_type = "👷📋"
        elif user_dict.get('worker_id'):
            profile_type = "👷"
        elif user_dict.get('client_id'):
            profile_type = "📋"

        button_text = f"{status_emoji}{profile_type} {name[:25]} (ID: {telegram_id})"
        keyboard.append([InlineKeyboardButton(
            button_text,
            callback_data=f"admin_user_view_{telegram_id}"
        )])

    keyboard.append([InlineKeyboardButton("🔍 Новый поиск", callback_data="admin_user_search_start")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_users")])

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр предложений пользователей"""
    query = update.callback_query
    await query.answer()

    # Получаем предложения
    suggestions = db.get_all_suggestions()
    new_count = db.get_suggestions_count('new')
    viewed_count = db.get_suggestions_count('viewed')
    resolved_count = db.get_suggestions_count('resolved')

    if not suggestions:
        await query.edit_message_text(
            "💡 <b>Предложения пользователей</b>\n\n"
            "Пока нет предложений.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")
            ]])
        )
        return ADMIN_MENU

    # Формируем текст
    text = (
        f"💡 <b>Предложения пользователей</b>\n\n"
        f"📊 Статистика:\n"
        f"🆕 Новых: {new_count}\n"
        f"👁 Просмотренных: {viewed_count}\n"
        f"✅ Решенных: {resolved_count}\n\n"
        f"Всего предложений: {len(suggestions)}\n\n"
        f"📝 Последние 10 предложений:\n\n"
    )

    read_buttons = []
    for i, suggestion in enumerate(suggestions[:10], 1):
        suggestion_dict = dict(suggestion)
        status_emoji = {"new": "🆕", "viewed": "👁", "resolved": "✅"}.get(suggestion_dict['status'], "")
        role_emoji = {"blogger": "📱", "advertiser": "👤", "both": "📱👤"}.get(suggestion_dict['user_role'], "")

        # Экранируем пользовательский текст для безопасности
        message_text = html.escape(suggestion_dict["message"])
        message_preview = (
            message_text[:50] + "..."
            if len(message_text) > 50
            else message_text
        )

        text += (
            f"{status_emoji} <b>#{suggestion_dict['id']}</b> {role_emoji}\n"
            f"<code>{message_preview}</code>\n"
            f"📅 {suggestion_dict['created_at']}\n\n"
        )

        back_status = suggestion_dict.get('status', 'new')
        read_buttons.append([
            InlineKeyboardButton(
                f"📖 Читать #{suggestion_dict['id']}",
                callback_data=f"admin_suggestion_view_{suggestion_dict['id']}_{back_status}"
            )
        ])

    keyboard = read_buttons + [
        [InlineKeyboardButton("🆕 Новые", callback_data="admin_suggestions_new")],
        [InlineKeyboardButton("👁 Просмотренные", callback_data="admin_suggestions_viewed")],
        [InlineKeyboardButton("✅ Решенные", callback_data="admin_suggestions_resolved")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_suggestions_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр предложений с фильтром по статусу"""
    query = update.callback_query
    await query.answer()

    logger.info(f"[ADMIN] admin_suggestions_filter вызвана пользователем {update.effective_user.id}, callback_data: {query.data}")

    # Извлекаем статус из callback_data: admin_suggestions_new/viewed/resolved
    status = query.data.split("_")[-1]  # new / viewed / resolved

    # Получаем предложения по статусу
    suggestions = db.get_suggestions_by_status(status)
    total_count = len(suggestions) if suggestions else 0

    logger.info(f"[SUGGESTIONS] Найдено {total_count} предложений со статусом '{status}'")

    # КРИТИЧНО: Если просматриваем НОВЫЕ предложения - отмечаем их как ПРОСМОТРЕННЫЕ
    if status == 'new' and suggestions:
        marked_count = 0
        for suggestion in suggestions[:20]:  # Отмечаем только те, что показываем
            suggestion_dict = dict(suggestion)
            try:
                db.update_suggestion_status(suggestion_dict['id'], 'viewed')
                marked_count += 1
            except Exception as e:
                logger.error(f"Ошибка при обновлении статуса предложения #{suggestion_dict['id']}: {e}")

        logger.info(f"✅ Отмечено {marked_count} предложений как 'viewed'")

    if not suggestions:
        await query.edit_message_text(
            f"💡 <b>Предложения: {status}</b>\n\n"
            f"Нет предложений с этим статусом.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="admin_suggestions")
            ]])
        )
        return ADMIN_MENU

    # Формируем текст
    status_name = {"new": "Новые", "viewed": "Просмотренные", "resolved": "Решенные"}.get(status, status)
    text = (
        f"💡 <b>Предложения: {status_name}</b>\n\n"
        f"Найдено: {total_count}\n\n"
        f"📝 Список предложений:\n\n"
    )

    suggestion_buttons = []
    for i, suggestion in enumerate(suggestions[:20], 1):
        suggestion_dict = dict(suggestion)
        role_emoji = {"blogger": "📱", "advertiser": "👤", "both": "📱👤"}.get(suggestion_dict['user_role'], "")

        # Экранируем пользовательский текст для безопасности
        message_text = html.escape(suggestion_dict["message"])
        message_preview = (
            message_text[:50] + "..."
            if len(message_text) > 50
            else message_text
        )

        text += (
            f"{i}. <b>#{suggestion_dict['id']}</b> {role_emoji}\n"
            f"<code>{message_preview}</code>\n"
            f"📅 {suggestion_dict['created_at']}\n\n"
        )

        suggestion_buttons.append([
            InlineKeyboardButton(
                f"📖 Читать #{suggestion_dict['id']}",
                callback_data=f"admin_suggestion_view_{suggestion_dict['id']}_{status}"
            )
        ])

    keyboard = suggestion_buttons + [
        [InlineKeyboardButton("⬅️ Назад к предложениям", callback_data="admin_suggestions")],
        [InlineKeyboardButton("⬅️ Админ меню", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_suggestion_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр полного текста предложения"""
    query = update.callback_query
    await query.answer()

    # callback_data: admin_suggestion_view_{id}_{status}
    parts = query.data.split("_")
    # parts: ['admin', 'suggestion', 'view', '{id}', '{status}']
    suggestion_id = int(parts[3])
    back_status = parts[4] if len(parts) > 4 else "new"

    suggestions = db.get_all_suggestions()
    suggestion_dict = None
    for s in suggestions:
        sd = dict(s)
        if sd['id'] == suggestion_id:
            suggestion_dict = sd
            break

    if not suggestion_dict:
        await query.edit_message_text(
            "Предложение не найдено.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_suggestions_{back_status}")
            ]])
        )
        return ADMIN_MENU

    status_emoji = {"new": "🆕", "viewed": "👁", "resolved": "✅"}.get(suggestion_dict['status'], "")
    role_emoji = {"blogger": "📱", "advertiser": "👤", "both": "📱👤"}.get(suggestion_dict['user_role'], "")
    status_name = {"new": "Новое", "viewed": "Просмотрено", "resolved": "Решено"}.get(suggestion_dict['status'], suggestion_dict['status'])

    message_text = html.escape(suggestion_dict["message"])

    text = (
        f"💡 <b>Предложение #{suggestion_dict['id']}</b>\n\n"
        f"{status_emoji} Статус: {status_name}\n"
        f"{role_emoji} Роль: {suggestion_dict['user_role']}\n"
        f"📅 Дата: {suggestion_dict['created_at']}\n\n"
        f"📝 <b>Текст:</b>\n"
        f"{message_text}"
    )

    keyboard = [
        [InlineKeyboardButton("⬅️ Назад к списку", callback_data=f"admin_suggestions_{back_status}")],
        [InlineKeyboardButton("⬅️ Предложения", callback_data="admin_suggestions")],
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ADMIN_MENU


async def admin_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закрыть админ-панель"""
    query = update.callback_query
    await query.answer()

    # Определяем роль пользователя
    user = db.get_user(update.effective_user.id)
    if user:
        user_dict = dict(user)
        worker_profile = db.get_worker_profile(user_dict['id'])
        client_profile = db.get_client_profile(user_dict['id'])

        context.user_data.clear()

        # Возвращаем в соответствующее меню
        if worker_profile:
            await query.edit_message_text("✅ Админ-панель закрыта.")
            # Вызываем меню блогера
            await show_blogger_menu(update, context)
        elif client_profile:
            await query.edit_message_text("✅ Админ-панель закрыта.")
            # Вызываем меню клиента
            await show_advertiser_menu(update, context)
        else:
            await query.edit_message_text("✅ Админ-панель закрыта.")
    else:
        await query.edit_message_text("✅ Админ-панель закрыта.")
        context.user_data.clear()

    return ConversationHandler.END

import logging
import os

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram import Update

import db
import handlers

# Версия бота
BOT_VERSION = "2.0.1 - GDE.REKLAMA MVP"  # Исправлены команды и PostgreSQL Row доступ
BOT_NAME = "gde.reklama"
BOT_USERNAME = "@gdereklama_bot"

# --- НАЧАЛО ИСПРАВЛЕННОГО БЛОКА ДЛЯ ИМПОРТА CONFIG.PY И ЗАГРУЗКИ ENV ---
# Попытка импортировать config, если он есть рядом (локально)
config = None
try:
    import config as local_config
    config = local_config
except ModuleNotFoundError:
    # В Railway или другой среде config.py может не быть — это ок, пойдём через ENV
    pass

# Если локально используешь .env, подхватим (не мешает Railway)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Если python-dotenv не установлен, это не критично для Railway, где ENV уже есть
    pass
# --- КОНЕЦ ИСПРАВЛЕННОГО БЛОКА ---

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_bot_token() -> str:
    """
    1) Если есть config.py и в нём BOT_TOKEN — используем его.
    2) Если нет config.py или нет BOT_TOKEN в нём — берём из переменной окружения BOT_TOKEN.
    """
    # Вариант 1: из config.py
    if config is not None and getattr(config, "BOT_TOKEN", None):
        logger.info("BOT_TOKEN взят из config.py")
        return config.BOT_TOKEN

    # Вариант 2: из ENV (Railway Variables / .env)
    token = os.getenv("BOT_TOKEN")
    if token:
        logger.info("BOT_TOKEN взят из переменных окружения")
        return token

    # Если не нашли вообще — кидаем в лог и падаем с ошибкой
    logger.error("BOT_TOKEN не найден ни в config.py, ни в переменных окружения.")
    raise RuntimeError("BOT_TOKEN не установлен")


def main():
    # Логируем версию бота при старте
    logger.info(f"🚀 ЗАПУСК БОТА - Версия: {BOT_VERSION}")

    # Инициализация connection pool (для PostgreSQL)
    db.init_connection_pool()

    db.init_db()
    db.migrate_add_portfolio_photos()  # Добавляем колонку если её нет
    # db.migrate_add_campaign_photos() удалено - функция не существует
    db.migrate_add_currency_to_bids()  # Добавляем колонку currency в bids (offers)
    db.migrate_add_cascading_deletes()  # Добавляем cascading deletes для PostgreSQL
    db.migrate_add_order_completion_tracking()  # Добавляем отслеживание завершения заказов (campaigns)
    db.migrate_add_profile_photo()  # Добавляем поле для фото профиля блогера
    db.migrate_add_premium_features()  # Добавляем поля для premium функций (выключены по умолчанию)
    db.migrate_add_moderation()  # Добавляем поля для модерации и банов
    db.migrate_add_regions_to_clients()  # Добавляем поле regions в таблицу clients (advertisers)
    db.migrate_add_videos_to_orders()  # Добавляем поле videos в таблицу orders (campaigns)
    db.migrate_add_name_change_tracking()  # Добавляем отслеживание изменения имени рекламодателя (1 раз в месяц)
    db.migrate_add_chat_system()  # Создаём таблицы для чата между рекламодателем и блогером
    db.migrate_add_transactions()  # Создаём таблицу для истории транзакций
    db.migrate_add_notification_settings()  # Добавляем настройки уведомлений для блогеров
    db.migrate_normalize_categories()  # ИСПРАВЛЕНИЕ: Нормализация категорий блогеров (точный поиск вместо LIKE)
    db.migrate_normalize_order_categories()  # ИСПРАВЛЕНИЕ: Нормализация категорий кампаний (точный поиск вместо LIKE)
    db.migrate_add_ready_in_days_and_notifications()  # Добавляем ready_in_days в offers и blogger_notifications
    db.migrate_add_admin_and_ads()  # Добавляем систему админ-панели, broadcast и рекламы
    db.migrate_add_worker_cities()  # Добавляем таблицу для множественного выбора городов мастером (blogger)
    db.migrate_add_chat_message_notifications()  # Добавляем таблицу для агрегированных уведомлений о сообщениях в чате
    db.migrate_fix_portfolio_photos_size()  # ИСПРАВЛЕНИЕ: Увеличиваем размер portfolio_photos с VARCHAR(1000) на TEXT

    # === НОВЫЕ МИГРАЦИИ ДЛЯ INFLUENCEMARKET ===
    db.migrate_add_blogger_platform_fields()  # Добавляем поля платформ, цен, верификации
    db.migrate_add_blogger_stats()  # Создаём таблицу статистики блогеров
    db.migrate_add_campaign_reports()  # Создаём таблицу отчётов о кампаниях
    db.migrate_add_campaign_fields()  # Добавляем поля для кампаний (бюджет, требования)
    db.migrate_add_blogger_followers()  # Добавляем поля подписчиков блогеров по соцсетям
    db.migrate_fix_old_campaigns_for_multiple_bloggers()  # Исправляем старые кампании для выбора нескольких блогеров

    db.create_indexes()  # Создаем индексы для оптимизации производительности

    # Добавляем супер-админов
    SUPER_ADMIN_TELEGRAM_ID = 641830790  # Ваш telegram_id
    db.add_admin_user(SUPER_ADMIN_TELEGRAM_ID, role='super_admin')

    SECOND_ADMIN_TELEGRAM_ID = 661071015  # Второй админ
    db.add_admin_user(SECOND_ADMIN_TELEGRAM_ID, role='super_admin')

    token = get_bot_token()

    logger.info("=" * 80)
    logger.info(f"🚀 ЗАПУСК БОТА - ВЕРСИЯ: {BOT_VERSION}")
    logger.info("✅ ВКЛЮЧЕНЫ ИСПРАВЛЕНИЯ:")
    logger.info("   - Обработчики admin_ad_placement и admin_ad_confirm в ADMIN_MENU")
    logger.info("   - Прямая маршрутизация для broadcast, suggestions, ads")
    logger.info("   - Автоматическая отметка предложений как 'viewed'")
    logger.info("   - Исправлены тестовые команды и PostgreSQL Row доступ")
    logger.info("=" * 80)

    application = ApplicationBuilder().token(token).build()

    # --- Команда /start (ОТДЕЛЬНО от ConversationHandler) ---
    logger.info("🔧 [STARTUP] Регистрация команды /start в group=-1")
    application.add_handler(CommandHandler("start", handlers.start_command), group=-1)

    # --- Тестовые команды (ВЫСОКИЙ ПРИОРИТЕТ - group=-1, до ВСЕХ handlers) ---
    logger.info("🔧 [STARTUP] Регистрация тестовых команд в group=-1")
    application.add_handler(CommandHandler("add_test_campaigns", handlers.add_test_campaigns_command), group=-1)
    application.add_handler(CommandHandler("add_test_bloggers", handlers.add_test_bloggers_command), group=-1)
    application.add_handler(CommandHandler("add_test_advertisers", handlers.add_test_advertisers_command), group=-1)
    application.add_handler(CommandHandler("add_test_offers", handlers.add_test_offers_command), group=-1)
    logger.info("✅ [STARTUP] Команды /start и тестовые команды зарегистрированы в group=-1")

    # --- Глобальный handler для noop (заглушки) ---
    application.add_handler(CallbackQueryHandler(handlers.noop_callback, pattern="^noop$"))

    # --- ConversationHandler для регистрации ---

    reg_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.select_role, pattern="^select_role_"),
            CallbackQueryHandler(handlers.add_second_role_blogger, pattern="^role_blogger$"),
            CallbackQueryHandler(handlers.add_second_role_advertiser, pattern="^role_advertiser$"),
        ],
        states={
            # Выбор роли
            handlers.SELECTING_ROLE: [
                CallbackQueryHandler(handlers.select_role, pattern="^select_role_"),
            ],

            # Регистрация блогера
            handlers.REGISTER_BLOGGER_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_blogger_name,
                )
            ],
            handlers.REGISTER_BLOGGER_REGION_SELECT: [
                CallbackQueryHandler(
                    handlers.register_blogger_region_select,
                    pattern="^bloggerregion_",
                )
            ],
            handlers.REGISTER_BLOGGER_CITY: [
                CallbackQueryHandler(
                    handlers.register_blogger_city_select,
                    pattern="^bloggercity_",
                )
            ],
            handlers.REGISTER_BLOGGER_CITY_SELECT: [
                CallbackQueryHandler(
                    handlers.register_blogger_city_select,
                    pattern="^bloggercity_",
                )
            ],
            handlers.REGISTER_BLOGGER_CITY_OTHER: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_blogger_city_other,
                )
            ],
            handlers.REGISTER_BLOGGER_CITIES_CONFIRM: [
                CallbackQueryHandler(
                    handlers.register_blogger_cities_confirm,
                    pattern="^(add_more_cities|finish_cities)$",
                )
            ],
            # Упрощенный выбор категорий (12 категорий, без подкатегорий)
            handlers.REGISTER_BLOGGER_CATEGORIES_SELECT: [
                CallbackQueryHandler(
                    handlers.register_blogger_categories_select,
                    pattern="^cat_",
                )
            ],
            handlers.REGISTER_BLOGGER_DESCRIPTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_blogger_description,
                )
            ],
            # НОВОЕ: Обработка фото контента
            handlers.REGISTER_BLOGGER_PHOTOS: [
                CallbackQueryHandler(
                    handlers.register_blogger_photos,
                    pattern="^add_photos_",
                ),
                MessageHandler(
                    filters.PHOTO | filters.TEXT | filters.VIDEO | filters.Document.ALL,
                    handlers.handle_blogger_photos,
                ),
            ],

            # Регистрация рекламодателя
            handlers.REGISTER_ADVERTISER_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_advertiser_name,
                )
            ],
            handlers.REGISTER_ADVERTISER_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_advertiser_phone,
                )
            ],
            handlers.REGISTER_ADVERTISER_REGION_SELECT: [
                CallbackQueryHandler(
                    handlers.register_advertiser_region_select,
                    pattern="^advertiserregion_",
                )
            ],
            handlers.REGISTER_ADVERTISER_CITY: [
                CallbackQueryHandler(
                    handlers.register_advertiser_city_select,
                    pattern="^advertisercity_",
                )
            ],
            handlers.REGISTER_ADVERTISER_CITY_SELECT: [
                CallbackQueryHandler(
                    handlers.register_advertiser_city_select,
                    pattern="^advertisercity_",
                )
            ],
            handlers.REGISTER_ADVERTISER_CITY_OTHER: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handlers.register_advertiser_city_other,
                )
            ],
            # REGISTER_ADVERTISER_DESCRIPTION удалено - регистрация завершается сразу после города
        },
        fallbacks=[
            CommandHandler("cancel", handlers.cancel),
            CommandHandler("start", handlers.cancel_from_start),  # КРИТИЧНО: выход из застрявшего диалога
            MessageHandler(filters.Regex("^(Отмена|отмена|cancel)$"), handlers.cancel),
            CallbackQueryHandler(handlers.cancel_from_callback, pattern="^go_main_menu$"),  # КРИТИЧНО: выход через кнопку меню
            CallbackQueryHandler(handlers.cancel_from_callback, pattern="^show_blogger_menu$"),  # КРИТИЧНО: выход через кнопку меню блогера
            CallbackQueryHandler(handlers.cancel_from_callback, pattern="^show_advertiser_menu$"),  # КРИТИЧНО: выход через кнопку меню рекламодателя
        ],
        allow_reentry=True,
    )

    application.add_handler(reg_conv_handler)

    # --- ConversationHandler для создания кампании ---

    create_campaign_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.advertiser_create_campaign, pattern="^advertiser_create_campaign$"),
            CallbackQueryHandler(handlers.advertiser_create_campaign, pattern="^client_create_order$"),  # Алиас
        ],
        states={
            handlers.CREATE_CAMPAIGN_REGION_SELECT: [
                CallbackQueryHandler(handlers.create_campaign_region_select, pattern="^campaignregion_"),
            ],
            handlers.CREATE_CAMPAIGN_CITY: [
                CallbackQueryHandler(handlers.create_campaign_city_select, pattern="^campaigncity_"),
                CallbackQueryHandler(handlers.create_campaign_city_other, pattern="^campaigncity_other$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.create_campaign_city_other),
                CallbackQueryHandler(handlers.create_campaign_back_to_region, pattern="^create_campaign_back_to_region$"),
            ],
            handlers.CREATE_CAMPAIGN_MAIN_CATEGORY: [
                CallbackQueryHandler(handlers.create_campaign_main_category, pattern="^order_cat_"),
                CallbackQueryHandler(handlers.create_campaign_main_category, pattern="^order_categories_done$"),
                CallbackQueryHandler(handlers.create_campaign_back_to_region, pattern="^create_campaign_back_to_region$"),
                CallbackQueryHandler(handlers.create_campaign_back_to_city, pattern="^create_campaign_back_to_city$"),
            ],
            handlers.CREATE_CAMPAIGN_SUBCATEGORY_SELECT: [
                CallbackQueryHandler(handlers.create_campaign_subcategory_select, pattern="^payment_type_"),
                CallbackQueryHandler(handlers.create_campaign_subcategory_select, pattern="^payment_types_done$"),
                CallbackQueryHandler(handlers.create_campaign_back_to_maincat, pattern="^create_campaign_back_to_maincat$"),
            ],
            handlers.CREATE_CAMPAIGN_BUDGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.create_campaign_budget),
            ],
            handlers.CREATE_CAMPAIGN_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.create_campaign_description),
            ],
            handlers.CREATE_CAMPAIGN_PHOTOS: [
                MessageHandler(filters.PHOTO, handlers.create_campaign_photo_upload),
                MessageHandler(filters.VIDEO, handlers.create_campaign_photo_upload),
                CommandHandler("done", handlers.create_campaign_done_uploading),
                CallbackQueryHandler(handlers.create_campaign_skip_photos, pattern="^campaign_skip_photos$"),
                CallbackQueryHandler(handlers.create_campaign_confirm, pattern="^campaign_confirm$"),
                CallbackQueryHandler(handlers.create_campaign_publish_confirmed, pattern="^campaign_publish_confirmed$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handlers.cancel),
            CommandHandler("start", handlers.cancel_from_start),  # КРИТИЧНО: выход из застрявшего диалога
            MessageHandler(filters.Regex("^(Отмена|отмена|cancel)$"), handlers.cancel),
        ],
        allow_reentry=True,
    )

    application.add_handler(create_campaign_handler)

    # --- ConversationHandler для редактирования профиля ---
    
    edit_profile_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.show_edit_profile_menu, pattern="^edit_profile_menu$")
        ],
        states={
            handlers.EDIT_PROFILE_MENU: [
                CallbackQueryHandler(handlers.edit_name_start, pattern="^edit_name$"),
                CallbackQueryHandler(handlers.edit_city_start, pattern="^edit_city$"),
                CallbackQueryHandler(handlers.edit_categories_start, pattern="^edit_categories$"),
                CallbackQueryHandler(handlers.edit_social_media_start, pattern="^edit_social_media$"),
                CallbackQueryHandler(handlers.edit_followers_start, pattern="^edit_followers$"),
                CallbackQueryHandler(handlers.edit_description_start, pattern="^edit_description$"),
            ],
            handlers.EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_name_save),
            ],
            handlers.EDIT_REGION_SELECT: [
                CallbackQueryHandler(handlers.edit_region_select, pattern="^editregion_"),
            ],
            handlers.EDIT_CITY: [
                CallbackQueryHandler(handlers.edit_city_select, pattern="^editcity_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_city_save),
            ],
            handlers.EDIT_CATEGORIES_SELECT: [
                CallbackQueryHandler(handlers.edit_categories_select, pattern="^editcat_"),
            ],
            handlers.EDIT_SOCIAL_MEDIA: [
                CallbackQueryHandler(handlers.edit_social_media_select, pattern="^edit_sm_"),
            ],
            handlers.EDIT_SOCIAL_MEDIA_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_social_media_save),
            ],
            handlers.EDIT_FOLLOWERS: [
                CallbackQueryHandler(handlers.edit_followers_select, pattern="^edit_fl_"),
                CallbackQueryHandler(handlers.show_edit_profile_menu, pattern="^edit_profile_menu$"),
            ],
            handlers.EDIT_FOLLOWERS_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_followers_save),
            ],
            handlers.EDIT_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.edit_description_save),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handlers.cancel_edit_profile),
            CommandHandler("start", handlers.cancel_from_start),  # КРИТИЧНО: выход из застрявшего диалога
            MessageHandler(filters.Regex("^(Отмена|отмена|cancel)$"), handlers.cancel_edit_profile),
            CallbackQueryHandler(handlers.show_blogger_profile, pattern="^blogger_profile$"),
        ],
        allow_reentry=True,
    )

    application.add_handler(edit_profile_handler)

    # === Глобальные обработчики для управления городами (вне ConversationHandler) ===
    application.add_handler(CallbackQueryHandler(handlers.remove_city_menu, pattern="^remove_city_menu$"))
    application.add_handler(CallbackQueryHandler(handlers.remove_city_confirm, pattern="^remove_city_"))

    # --- ConversationHandler для предложений блогеров ---

    offer_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.blogger_offer_on_campaign, pattern="^offer_on_campaign_")
        ],
        states={
            handlers.OFFER_SELECT_PAYMENT_TYPE: [
                CallbackQueryHandler(handlers.blogger_offer_select_paid, pattern="^offer_paid_"),
                CallbackQueryHandler(handlers.blogger_offer_select_barter, pattern="^offer_barter_"),
            ],
            handlers.OFFER_SELECT_CURRENCY: [
                CallbackQueryHandler(handlers.blogger_offer_select_currency, pattern="^offer_currency_"),
            ],
            handlers.OFFER_ENTER_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.blogger_offer_enter_price),
            ],
            handlers.OFFER_SELECT_READY_DAYS: [
                CallbackQueryHandler(handlers.blogger_offer_select_ready_days, pattern="^ready_days_"),
            ],
            handlers.OFFER_ENTER_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.blogger_offer_enter_comment),
                CallbackQueryHandler(handlers.blogger_offer_skip_comment, pattern="^offer_skip_comment$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(handlers.blogger_offer_cancel, pattern="^cancel_offer$"),
        ],
        allow_reentry=True,
    )

    application.add_handler(offer_conv_handler)

    # --- ConversationHandler для изменения названия рекламодателя ---

    edit_advertiser_name_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.start_edit_advertiser_name, pattern="^edit_advertiser_name$")
        ],
        states={
            handlers.EDIT_ADVERTISER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_new_advertiser_name),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(handlers.cancel_from_callback, pattern="^cancel$"),
            CommandHandler("cancel", handlers.cancel_from_command),
        ],
        allow_reentry=True,
    )

    application.add_handler(edit_advertiser_name_handler)

    # --- Обработчик "Мои кампании" (НЕ в ConversationHandler) ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_my_campaigns,
            pattern="^advertiser_my_campaigns$",
        )
    )

    # Алиас для обратной совместимости
    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_my_campaigns,
            pattern="^client_my_orders$",
        )
    )

    # --- Обработчики категорий кампаний РЕКЛАМОДАТЕЛЯ ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_waiting_campaigns,
            pattern="^advertiser_waiting_campaigns$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_in_progress_campaigns,
            pattern="^advertiser_in_progress_campaigns$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_completed_campaigns,
            pattern="^advertiser_completed_campaigns$",
        )
    )

    # --- Обработчики категорий кампаний БЛОГЕРА ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_active_campaigns,
            pattern="^blogger_active_campaigns$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_completed_campaigns,
            pattern="^blogger_completed_campaigns$",
        )
    )

    # --- Обработчик отмены кампании ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.cancel_campaign_handler,
            pattern="^cancel_campaign_"
        )
    )

    # НОВОЕ: Обработчики завершения кампании и оценки блогера
    application.add_handler(
        CallbackQueryHandler(
            handlers.complete_campaign_handler,
            pattern="^complete_campaign_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.submit_campaign_rating,
            pattern="^rate_campaign_"
        )
    )

    # --- Обработчик добавления комментария к отзыву ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.add_comment_to_review,
            pattern="^add_comment_"
        )
    )

    # НОВОЕ: Обработчики фотографий выполненного контента
    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_upload_work_photo_start,
            pattern="^upload_work_photo_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_skip_work_photo,
            pattern="^skip_work_photo_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_finish_work_photos,
            pattern="^finish_work_photos_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_cancel_work_photos,
            pattern="^cancel_work_photos_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_check_work_photos,
            pattern="^check_work_photos_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_verify_work_photo,
            pattern="^verify_photo_"
        )
    )

    # Управление фотографиями завершённых работ
    application.add_handler(
        CallbackQueryHandler(
            handlers.manage_completed_photos,
            pattern="^manage_completed_photos$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.photo_page_navigation,
            pattern="^photo_page_(prev|next)$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.view_work_photo,
            pattern="^view_work_photo_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.confirm_delete_work_photo,
            pattern="^confirm_delete_photo_"
        )
    )

    # MessageHandler для приёма фото завершённых работ от блогера
    application.add_handler(
        MessageHandler(
            filters.PHOTO & ~filters.COMMAND,
            handlers.blogger_upload_work_photo_receive
        )
    )

    # MessageHandler для приёма комментариев к отзывам
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handlers.receive_review_comment
        )
    )

    # --- Обработчики для добавления фото (БЕЗ ConversationHandler) ---

    # Начало добавления фото
    application.add_handler(
        CallbackQueryHandler(handlers.blogger_add_photos_start, pattern="^blogger_add_photos$")
    )

    # Завершение добавления фото
    application.add_handler(
        CallbackQueryHandler(handlers.blogger_add_photos_finish_callback, pattern="^finish_adding_photos$")
    )

    # --- Обработчики фото профиля ---
    application.add_handler(
        CallbackQueryHandler(handlers.edit_profile_photo_start, pattern="^edit_profile_photo$")
    )

    application.add_handler(
        CallbackQueryHandler(handlers.cancel_profile_photo, pattern="^cancel_profile_photo$")
    )

    # --- Управление фото портфолио ---
    application.add_handler(
        CallbackQueryHandler(handlers.manage_portfolio_photos, pattern="^manage_portfolio_photos$")
    )

    application.add_handler(
        CallbackQueryHandler(handlers.portfolio_photo_navigate, pattern="^portfolio_(prev|next)_")
    )

    application.add_handler(
        CallbackQueryHandler(handlers.delete_portfolio_photo, pattern="^delete_portfolio_photo_")
    )

    # --- Просмотр портфолио другого блогера ---
    application.add_handler(
        CallbackQueryHandler(handlers.view_blogger_portfolio, pattern="^view_blogger_portfolio_")
    )

    application.add_handler(
        CallbackQueryHandler(handlers.blogger_portfolio_view_navigate, pattern="^blogger_portfolio_view_(prev|next)$")
    )

    application.add_handler(
        CallbackQueryHandler(handlers.back_to_offer_card, pattern="^back_to_offer_card$")
    )

    # Загрузка фото (обрабатывает и portfolio_photos и profile_photo)
    # КРИТИЧНО: Группа -1 чтобы выполнялось РАНЬШЕ ConversationHandler
    application.add_handler(
        MessageHandler(filters.PHOTO, handlers.blogger_add_photos_upload),
        group=-1
    )

    # Загрузка видео (для портфолио)
    application.add_handler(
        MessageHandler(filters.VIDEO, handlers.blogger_add_photos_upload),
        group=-1
    )

    # Загрузка документов (когда пользователь перетягивает файл)
    application.add_handler(
        MessageHandler(filters.Document.ALL, handlers.blogger_add_photos_upload),
        group=-1
    )

    # --- Меню блогера и рекламодателя ---

    application.add_handler(
        CallbackQueryHandler(
            handlers.show_blogger_menu,
            pattern="^show_blogger_menu$",
        )
    )

    # Алиас для обратной совместимости
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_blogger_menu,
            pattern="^show_worker_menu$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.toggle_notifications,
            pattern="^toggle_notifications$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.toggle_advertiser_notifications,
            pattern="^toggle_advertiser_notifications$",
        )
    )

    # Алиас для обратной совместимости
    application.add_handler(
        CallbackQueryHandler(
            handlers.toggle_advertiser_notifications,
            pattern="^toggle_client_notifications$",
        )
    )

    # НОВОЕ: Обработчик для показа рекламы/новостей
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_news_and_ads,
            pattern="^show_news_and_ads$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_my_offers,
            pattern="^blogger_my_offers$",
        )
    )

    # НОВОЕ: Мои кампании блогера (активные кампании)
    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_my_campaigns,
            pattern="^blogger_my_campaigns$",
        )
    )

    # Доступные кампании для блогера
    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_view_orders,
            pattern="^blogger_view_orders$",
        )
    )

    # Навигация по страницам кампаний для блогера
    application.add_handler(
        CallbackQueryHandler(
            handlers.navigate_campaigns_page,
            pattern="^campaigns_(prev|next)_page$",
        )
    )

    # Алиасы для обратной совместимости (worker_* → blogger_*)
    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_view_orders,
            pattern="^worker_view_orders$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_my_offers,
            pattern="^worker_my_bids$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_my_campaigns,
            pattern="^worker_my_orders$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.show_advertiser_menu,
            pattern="^show_advertiser_menu$",
        )
    )

    # Алиас для обратной совместимости
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_advertiser_menu,
            pattern="^show_client_menu$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_my_payments,
            pattern="^advertiser_my_payments$",
        )
    )

    # "Мой профиль" блогера
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_blogger_profile,
            pattern="^blogger_profile$",
        )
    )

    # Алиас для обратной совместимости
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_blogger_profile,
            pattern="^worker_profile$",
        )
    )

    # "Доступные кампании" для блогера
    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_view_campaigns,
            pattern="^blogger_view_campaigns$",
        )
    )

    # Детальный просмотр кампании блогером
    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_view_campaign_details,
            pattern="^view_order_"
        )
    )

    # Навигация по фото кампании
    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_campaign_photo_nav,
            pattern="^order_photo_(prev|next)_"
        )
    )

    # НОВОЕ: Отказ от кампании блогером
    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_decline_campaign_confirm,
            pattern=r"^decline_campaign_\d+$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_decline_campaign_yes,
            pattern="^decline_campaign_yes_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_decline_campaign_no,
            pattern="^decline_campaign_no_"
        )
    )

    # --- Обработчики для листания блогеров ---

    application.add_handler(
        CallbackQueryHandler(
            handlers.go_main_menu,
            pattern="^go_main_menu$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_browse_bloggers,
            pattern="^advertiser_browse_bloggers$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_start_viewing,
            pattern="^browse_start_now$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_next_blogger,
            pattern="^browse_next_blogger$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_photo_prev,
            pattern="^browse_photo_prev$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_photo_next,
            pattern="^browse_photo_next$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.browse_restart,
            pattern="^browse_restart$",
        )
    )

    # --- Обработчики завершения кампании ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.advertiser_complete_campaign,
            pattern="^complete_campaign_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.blogger_complete_campaign,
            pattern="^blogger_complete_campaign_"
        )
    )

    # --- Обработчики просмотра отзывов ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.show_reviews,
            pattern="^show_reviews_"
        )
    )

    # --- Обработчики галереи работ ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.view_portfolio,
            pattern="^view_portfolio$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.portfolio_navigate,
            pattern="^portfolio_(prev|next)$"
        )
    )

    # --- Обработчики просмотра предложений ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.view_campaign_offers,
            pattern="^view_offers_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.sort_offers_handler,
            pattern="^sort_offers_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.offer_navigate,
            pattern="^bid_(prev|next)$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.view_blogger_profile_from_offer,
            pattern="^view_blogger_profile_"
        )
    )

    # --- Обработчики выбора блогера и оплаты ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.select_blogger,
            pattern="^select_blogger_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.reject_blogger_from_offer,
            pattern="^reject_blogger_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.pay_with_stars,
            pattern="^pay_stars_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.pay_with_card,
            pattern="^pay_card_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.confirm_payment,
            pattern="^confirm_payment_"
        )
    )

    # --- Обработчик кнопки "Сказать спасибо платформе" ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.thank_platform,
            pattern="^thank_platform_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            handlers.test_payment_success,
            pattern="^test_payment_success_"
        )
    )

    # --- Обработчики чатов ---
    application.add_handler(
        CallbackQueryHandler(
            handlers.open_chat,
            pattern="^open_chat_"
        )
    )

    # --- ConversationHandler для отзывов ---
    review_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.start_review, pattern="^leave_review_"),
        ],
        states={
            handlers.REVIEW_SELECT_RATING: [
                CallbackQueryHandler(handlers.review_select_rating, pattern="^review_rating_"),
            ],
            handlers.REVIEW_ENTER_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.review_enter_comment),
                CallbackQueryHandler(handlers.review_skip_comment, pattern="^review_skip_comment$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(handlers.cancel_review, pattern="^cancel_review$"),
        ],
        allow_reentry=True,
    )

    application.add_handler(review_conv_handler)

    # Команда для очистки профиля
    application.add_handler(
        CommandHandler("reset_profile", handlers.reset_profile_command)
    )

    # === ADMIN КОМАНДЫ ===

    # Команды управления premium функциями (только для администратора)
    application.add_handler(
        CommandHandler("enable_premium", handlers.enable_premium_command)
    )

    application.add_handler(
        CommandHandler("disable_premium", handlers.disable_premium_command)
    )

    application.add_handler(
        CommandHandler("premium_status", handlers.premium_status_command)
    )

    # Команды модерации (только для администратора)
    application.add_handler(
        CommandHandler("ban", handlers.ban_user_command)
    )

    application.add_handler(
        CommandHandler("unban", handlers.unban_user_command)
    )

    application.add_handler(
        CommandHandler("banned", handlers.banned_users_command)
    )

    # Команда статистики (только для администратора)
    application.add_handler(
        CommandHandler("stats", handlers.stats_command)
    )

    # Команда для массовой рассылки уведомлений (только для администратора)
    application.add_handler(
        CommandHandler("announce", handlers.announce_command)
    )

    # Команда для проверки просроченных чатов (только для администратора)
    application.add_handler(
        CommandHandler("check_expired_chats", handlers.check_expired_chats_command)
    )

    # --- ConversationHandler для админ-панели ---
    admin_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("admin", handlers.admin_panel),
            CallbackQueryHandler(handlers.admin_panel, pattern="^admin_panel$"),
        ],
        states={
            handlers.ADMIN_MENU: [
                CallbackQueryHandler(handlers.admin_broadcast_start, pattern="^admin_broadcast$"),
                CallbackQueryHandler(handlers.admin_create_ad_start, pattern="^admin_create_ad$"),
                CallbackQueryHandler(handlers.admin_stats, pattern="^admin_stats$"),
                CallbackQueryHandler(handlers.admin_category_reports, pattern="^admin_category_reports$"),
                CallbackQueryHandler(handlers.admin_city_activity, pattern="^admin_city_activity$"),
                CallbackQueryHandler(handlers.admin_avg_prices, pattern="^admin_avg_prices$"),
                CallbackQueryHandler(handlers.admin_category_statuses, pattern="^admin_category_statuses$"),
                CallbackQueryHandler(handlers.admin_export_menu, pattern="^admin_export_menu$"),
                CallbackQueryHandler(handlers.admin_export_data, pattern="^admin_export_"),
                CallbackQueryHandler(handlers.admin_users_menu, pattern="^admin_users$"),
                CallbackQueryHandler(handlers.admin_users_list, pattern="^admin_users_list_"),
                CallbackQueryHandler(handlers.admin_users_page, pattern="^admin_users_page_"),
                CallbackQueryHandler(handlers.admin_user_view, pattern="^admin_user_view_"),
                CallbackQueryHandler(handlers.admin_user_ban_start, pattern="^admin_user_ban_start_"),
                CallbackQueryHandler(handlers.admin_user_unban, pattern="^admin_user_unban_"),
                CallbackQueryHandler(handlers.admin_user_search_start, pattern="^admin_user_search_start$"),
                CallbackQueryHandler(handlers.admin_suggestions, pattern="^admin_suggestions$"),
                CallbackQueryHandler(handlers.admin_suggestions_filter, pattern="^admin_suggestions_(new|viewed|resolved)$"),
                CallbackQueryHandler(handlers.admin_suggestion_view, pattern="^admin_suggestion_view_"),
                # КРИТИЧНО: Обработчики для рекламы (работают из ADMIN_MENU когда ad_data есть)
                CallbackQueryHandler(handlers.admin_ad_placement, pattern="^ad_placement_"),
                CallbackQueryHandler(handlers.admin_ad_confirm, pattern="^ad_confirm_"),
                # Управление рекламами
                CallbackQueryHandler(handlers.admin_manage_ads, pattern="^admin_manage_ads$"),
                CallbackQueryHandler(handlers.admin_list_ads_by_status, pattern="^admin_ads_(active|inactive|all)$"),
                CallbackQueryHandler(handlers.admin_view_ad_detail, pattern="^admin_view_ad_\\d+$"),
                CallbackQueryHandler(handlers.admin_toggle_ad_status, pattern="^admin_toggle_ad_\\d+$"),
                CallbackQueryHandler(handlers.admin_edit_ad_menu, pattern="^admin_edit_ad_\\d+$"),
                CallbackQueryHandler(handlers.admin_edit_ad_field, pattern="^admin_edit_field_"),
                CallbackQueryHandler(handlers.admin_delete_ad_confirm, pattern="^admin_delete_ad_confirm_\\d+$"),
                CallbackQueryHandler(handlers.admin_delete_ad_yes, pattern="^admin_delete_ad_yes_\\d+$"),
                CallbackQueryHandler(handlers.admin_close, pattern="^admin_close$"),
                CallbackQueryHandler(handlers.admin_back, pattern="^admin_back$"),  # Возврат в меню
            ],
            handlers.BROADCAST_SELECT_AUDIENCE: [
                CallbackQueryHandler(handlers.admin_broadcast_select_audience, pattern="^broadcast_"),
                CallbackQueryHandler(handlers.admin_back, pattern="^admin_back$"),
            ],
            handlers.BROADCAST_ENTER_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.admin_broadcast_send),
                CallbackQueryHandler(handlers.admin_broadcast_start, pattern="^admin_broadcast_start$"),
            ],
            handlers.ADMIN_BAN_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.admin_user_ban_execute),
                CallbackQueryHandler(handlers.admin_user_view, pattern="^admin_user_view_"),
            ],
            handlers.ADMIN_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.admin_user_search_execute),
                CallbackQueryHandler(handlers.admin_users_menu, pattern="^admin_users$"),
                CallbackQueryHandler(handlers.admin_user_search_start, pattern="^admin_user_search_start$"),
            ],
            handlers.AD_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.admin_ad_title),
                CallbackQueryHandler(handlers.admin_back, pattern="^admin_back$"),
            ],
            handlers.AD_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.admin_ad_text),
                # ИСПРАВЛЕНИЕ: Добавлены обработчики для следующих шагов
                CallbackQueryHandler(handlers.admin_ad_audience, pattern="^ad_audience_"),
                CallbackQueryHandler(handlers.admin_ad_duration, pattern="^ad_duration_"),
                CallbackQueryHandler(handlers.admin_ad_start_date, pattern="^ad_start_"),
                CallbackQueryHandler(handlers.admin_ad_confirm, pattern="^ad_confirm_"),
                CallbackQueryHandler(handlers.admin_back, pattern="^admin_back$"),
            ],
            handlers.AD_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.admin_ad_url),
                # ИСПРАВЛЕНИЕ: Добавлены обработчики для следующих шагов
                CallbackQueryHandler(handlers.admin_ad_audience, pattern="^ad_audience_"),
                CallbackQueryHandler(handlers.admin_ad_duration, pattern="^ad_duration_"),
                CallbackQueryHandler(handlers.admin_ad_start_date, pattern="^ad_start_"),
                CallbackQueryHandler(handlers.admin_ad_confirm, pattern="^ad_confirm_"),
                CallbackQueryHandler(handlers.admin_back, pattern="^admin_back$"),
            ],
            handlers.AD_BUTTON_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.admin_ad_button_text),
                # ИСПРАВЛЕНИЕ: Добавлены обработчики для следующих шагов, т.к. direct_routing не меняет состояние ConversationHandler
                CallbackQueryHandler(handlers.admin_ad_audience, pattern="^ad_audience_"),
                CallbackQueryHandler(handlers.admin_ad_duration, pattern="^ad_duration_"),
                CallbackQueryHandler(handlers.admin_ad_start_date, pattern="^ad_start_"),
                CallbackQueryHandler(handlers.admin_ad_confirm, pattern="^ad_confirm_"),
                CallbackQueryHandler(handlers.admin_back, pattern="^admin_back$"),
            ],
            handlers.AD_AUDIENCE: [
                CallbackQueryHandler(handlers.admin_ad_audience, pattern="^ad_audience_"),
                # ИСПРАВЛЕНИЕ: Добавлены обработчики для следующих шагов
                CallbackQueryHandler(handlers.admin_ad_duration, pattern="^ad_duration_"),
                CallbackQueryHandler(handlers.admin_ad_start_date, pattern="^ad_start_"),
                CallbackQueryHandler(handlers.admin_ad_confirm, pattern="^ad_confirm_"),
            ],
            handlers.AD_DURATION: [
                CallbackQueryHandler(handlers.admin_ad_duration, pattern="^ad_duration_"),
                # ИСПРАВЛЕНИЕ: Добавлены обработчики для следующих шагов
                CallbackQueryHandler(handlers.admin_ad_start_date, pattern="^ad_start_"),
                CallbackQueryHandler(handlers.admin_ad_confirm, pattern="^ad_confirm_"),
            ],
            handlers.AD_START_DATE: [
                CallbackQueryHandler(handlers.admin_ad_start_date, pattern="^ad_start_"),
                # ИСПРАВЛЕНИЕ: Добавлен обработчик для подтверждения
                CallbackQueryHandler(handlers.admin_ad_confirm, pattern="^ad_confirm_"),
            ],
            handlers.AD_CONFIRM: [
                CallbackQueryHandler(handlers.admin_ad_confirm, pattern="^ad_confirm_"),
            ],
            handlers.AD_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.admin_process_ad_edit),
                CallbackQueryHandler(handlers.admin_view_ad_detail, pattern="^admin_view_ad_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handlers.cancel_from_command),
        ],
        allow_reentry=True,
        name="admin_conversation",  # Для отладки
    )

    # Регистрируем в group=0 (по умолчанию) - будет первым обрабатывать сообщения
    application.add_handler(admin_conv_handler, group=0)

    # --- ConversationHandler для предложений ---
    suggestion_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.send_suggestion_start, pattern="^send_suggestion$")
        ],
        states={
            handlers.SUGGESTION_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_suggestion_text),
                CallbackQueryHandler(handlers.cancel_suggestion, pattern="^cancel_suggestion$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(handlers.cancel_suggestion, pattern="^cancel_suggestion$"),
            CommandHandler("cancel", handlers.cancel_from_command),
        ],
        allow_reentry=True,
    )

    # Важно: ConversationHandler должен быть в group=0 для приоритета
    application.add_handler(suggestion_conv_handler, group=0)

    # КРИТИЧНО: Прямая маршрутизация ДО ConversationHandlers для FIX B
    # Это обязательно должно быть в group=-1, чтобы обработать текст ДО того,
    # как ConversationHandler его "съест" из-за per_message=False
    async def direct_routing(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Прямая маршрутизация для ConversationHandler states (FIX B)"""
        logger.info(f"[DIRECT-ROUTING] Проверка для пользователя {update.effective_user.id}")
        logger.info(f"[DIRECT-ROUTING] Флаги: suggestion_active={context.user_data.get('suggestion_active')}, broadcast_active={context.user_data.get('broadcast_active')}, ad_step={context.user_data.get('ad_step')}")

        # Прямая маршрутизация для предложений
        if context.user_data.get("suggestion_active"):
            logger.info(f"[FIX B] Прямая маршрутизация в receive_suggestion_text")
            return await handlers.receive_suggestion_text(update, context)

        # Прямая маршрутизация для рассылки
        if context.user_data.get("broadcast_active"):
            logger.info(f"[FIX B] Прямая маршрутизация в admin_broadcast_send")
            return await handlers.admin_broadcast_send(update, context)

        # Прямая маршрутизация для создания рекламы
        ad_step = context.user_data.get("ad_step")
        if ad_step:
            logger.info(f"[AD-ROUTING] Обработка ad_step={ad_step}")
            if ad_step == "title":
                return await handlers.admin_ad_title(update, context)
            elif ad_step == "text":
                return await handlers.admin_ad_text(update, context)
            elif ad_step == "url":
                return await handlers.admin_ad_url(update, context)
            elif ad_step == "button_text":
                return await handlers.admin_ad_button_text(update, context)

        # Нет активных флагов - пропускаем обработку
        logger.info(f"[DIRECT-ROUTING] Нет активных флагов, пропускаем обработку")

    logger.info("🔧 [STARTUP] Регистрация direct_routing в group=-1 (ДО ConversationHandlers)")
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            direct_routing,
            block=False  # ВАЖНО: Не блокируем ConversationHandler!
        ),
        group=-1
    )

    # Глобальный обработчик подтверждения создания рекламы
    # Регистрируется в group=-1 чтобы перехватить callback ДО ConversationHandler
    logger.info("🔧 [STARTUP] Регистрация ad_confirm callback handler в group=-1")

    async def handle_ad_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Глобальный обработчик подтверждения рекламы (обходит ConversationHandler state issue)"""
        query = update.callback_query
        logger.info(f"[AD-CONFIRM-GLOBAL] Перехвачен callback: {query.data} от пользователя {update.effective_user.id}")

        # Проверяем, что это callback для подтверждения рекламы и есть данные
        if 'ad_data' in context.user_data:
            logger.info(f"[AD-CONFIRM-GLOBAL] Найдены ad_data, вызываем admin_ad_confirm")
            # Вызываем обработчик подтверждения напрямую
            return await handlers.admin_ad_confirm(update, context)
        else:
            logger.warning(f"[AD-CONFIRM-GLOBAL] ad_data не найдены, пропускаем")
            # Пропускаем - пусть ConversationHandler обработает
            return None

    application.add_handler(
        CallbackQueryHandler(
            handle_ad_confirm_callback,
            pattern="^ad_confirm_"
        ),
        group=-1
    )

    # КРИТИЧНО: Глобальные обработчики для ВСЕХ шагов создания рекламы
    # Регистрируются в group=-1 чтобы перехватить callbacks ДО ConversationHandler
    logger.info("🔧 [STARTUP] Регистрация глобальных обработчиков для создания рекламы в group=-1")

    async def handle_ad_audience_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Глобальный обработчик выбора аудитории рекламы"""
        query = update.callback_query
        logger.info(f"[AD-AUDIENCE-GLOBAL] Перехвачен callback: {query.data} от пользователя {update.effective_user.id}")

        if 'ad_data' in context.user_data:
            logger.info(f"[AD-AUDIENCE-GLOBAL] Найдены ad_data, вызываем admin_ad_audience")
            return await handlers.admin_ad_audience(update, context)
        else:
            logger.warning(f"[AD-AUDIENCE-GLOBAL] ad_data не найдены, пропускаем")
            return None

    async def handle_ad_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Глобальный обработчик выбора продолжительности рекламы"""
        query = update.callback_query
        logger.info(f"[AD-DURATION-GLOBAL] Перехвачен callback: {query.data} от пользователя {update.effective_user.id}")

        if 'ad_data' in context.user_data:
            logger.info(f"[AD-DURATION-GLOBAL] Найдены ad_data, вызываем admin_ad_duration")
            return await handlers.admin_ad_duration(update, context)
        else:
            logger.warning(f"[AD-DURATION-GLOBAL] ad_data не найдены, пропускаем")
            return None

    async def handle_ad_start_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Глобальный обработчик выбора даты старта рекламы"""
        query = update.callback_query
        logger.info(f"[AD-START-DATE-GLOBAL] Перехвачен callback: {query.data} от пользователя {update.effective_user.id}")

        if 'ad_data' in context.user_data:
            logger.info(f"[AD-START-DATE-GLOBAL] Найдены ad_data, вызываем admin_ad_start_date")
            return await handlers.admin_ad_start_date(update, context)
        else:
            logger.warning(f"[AD-START-DATE-GLOBAL] ad_data не найдены, пропускаем")
            return None

    # Регистрируем глобальные обработчики
    application.add_handler(
        CallbackQueryHandler(handle_ad_audience_callback, pattern="^ad_audience_"),
        group=-1
    )
    application.add_handler(
        CallbackQueryHandler(handle_ad_duration_callback, pattern="^ad_duration_"),
        group=-1
    )
    application.add_handler(
        CallbackQueryHandler(handle_ad_start_date_callback, pattern="^ad_start_"),
        group=-1
    )

    # Глобальный обработчик сообщений для чатов
    # Регистрируется ПОСЛЕ ConversationHandlers для обработки активных чатов
    logger.info("🔧 [STARTUP] Регистрация handle_chat_message в group=1 (ПОСЛЕ ConversationHandlers)")
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handlers.handle_chat_message
        ),
        group=1
    )

    # Обработчик неизвестных команд
    application.add_handler(
        MessageHandler(filters.COMMAND, handlers.unknown_command)
    )

    # ДИАГНОСТИКА: Ловушка для ВСЕХ сообщений, которые не были обработаны
    async def catch_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ловит ВСЕ необработанные сообщения для диагностики"""
        if update.message:
            logger.warning(f"[CATCH-ALL] Необработанное сообщение от {update.effective_user.id}: "
                          f"text={update.message.text}, "
                          f"caption={update.message.caption}, "
                          f"photo={bool(update.message.photo)}, "
                          f"document={bool(update.message.document)}, "
                          f"sticker={bool(update.message.sticker)}")
        else:
            logger.warning(f"[CATCH-ALL] Необработанный update: {update}")

    application.add_handler(
        MessageHandler(~filters.COMMAND, catch_all_messages),
        group=10  # Самая низкая приоритетность - ловит только неизвестные сообщения (не команды)
    )

    # --- ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ---
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        КРИТИЧЕСКИ ВАЖНО: Глобальный обработчик всех необработанных ошибок.
        Предотвращает крашинг бота и помогает пользователям восстановиться.
        """
        logger.error(
            f"❌ EXCEPTION while handling update {update}",
            exc_info=context.error
        )

        # Логируем контекст для debugging
        if context.user_data:
            logger.error(f"User data: {context.user_data}")

        try:
            # Пытаемся уведомить пользователя
            if update and update.effective_message:
                error_message = (
                    "❌ <b>Произошла ошибка</b>\n\n"
                    "К сожалению, что-то пошло не так.\n\n"
                    "Попробуйте:\n"
                    "• Отправить /start для возврата в главное меню\n"
                    "• Повторить действие через минуту\n\n"
                    "Если проблема повторяется, обратитесь в поддержку."
                )

                await update.effective_message.reply_text(
                    error_message,
                    parse_mode="HTML"
                )
            elif update and update.callback_query:
                # Если это callback query, отвечаем через answer
                await update.callback_query.answer(
                    "❌ Произошла ошибка. Попробуйте отправить /start",
                    show_alert=True
                )
        except Exception as e:
            logger.error(f"❌ Error in error_handler itself: {e}", exc_info=True)

    # Регистрируем обработчик ошибок
    application.add_error_handler(error_handler)

    # --- ФОНОВАЯ ЗАДАЧА: Проверка просроченных кампаний ---
    async def check_deadlines_job(context):
        """
        Периодическая проверка просроченных кампаний.
        Запускается каждый час.
        """
        logger.info("🔍 Запуск проверки просроченных кампаний...")

        expired_campaigns = db.check_expired_campaigns()

        if not expired_campaigns:
            logger.debug("Просроченных кампаний не найдено")
            return

        logger.info(f"📋 Найдено просроченных кампаний: {len(expired_campaigns)}")

        # Отправляем уведомления
        for campaign_data in expired_campaigns:
            campaign_id = campaign_data['campaign_id']
            advertiser_user_id = campaign_data['advertiser_user_id']
            blogger_user_ids = campaign_data['blogger_user_ids']
            title = campaign_data['title']

            # Уведомляем рекламодателя
            try:
                advertiser_user = db.get_user_by_id(advertiser_user_id)
                if advertiser_user:
                    await context.bot.send_message(
                        chat_id=advertiser_user['telegram_id'],
                        text=f"⏰ Кампания #{campaign_id} истекла по дедлайну\n\n"
                             f"📝 {title}\n\n"
                             f"Кампания автоматически закрыта, так как прошёл указанный срок выполнения."
                    )
                    logger.info(f"✅ Уведомление рекламодателя {advertiser_user_id} отправлено")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки уведомления рекламодателю {advertiser_user_id}: {e}")

            # Уведомляем блогеров
            for blogger_user_id in blogger_user_ids:
                try:
                    blogger_user = db.get_user_by_id(blogger_user_id)
                    if blogger_user:
                        await context.bot.send_message(
                            chat_id=blogger_user['telegram_id'],
                            text=f"⏰ Кампания #{campaign_id} истекла по дедлайну\n\n"
                                 f"📝 {title}\n\n"
                                 f"Кампания автоматически закрыта."
                        )
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки уведомления блогеру {blogger_user_id}: {e}")

        logger.info(f"✅ Проверка просроченных кампаний завершена. Обработано: {len(expired_campaigns)}")

    # Добавляем задачу в очередь (запуск каждый час)
    job_queue = application.job_queue
    if job_queue is not None:
        job_queue.run_repeating(
            check_deadlines_job,
            interval=3600,  # 3600 секунд = 1 час
            first=10  # Первый запуск через 10 секунд после старта бота
        )
        logger.info("⏰ Фоновая задача проверки дедлайнов активирована (каждый час)")
    else:
        logger.warning("⚠️ JobQueue не доступен. Проверка дедлайнов отключена.")

    logger.info(f"🚀 Бот запущен (версия {BOT_VERSION}). Опрос обновлений...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

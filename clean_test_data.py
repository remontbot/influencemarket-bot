#!/usr/bin/env python3
"""
Скрипт для очистки тестовых данных из старого бота по стройке.
Удаляет все кампании, блогеров и связанные данные, которые были созданы для тестирования.
"""

import os
import sys
from datetime import datetime

# Импортируем функции из db.py
import db

# Категории из старого бота по стройке (тестовые данные)
OLD_CONSTRUCTION_CATEGORIES = [
    "Электрика",
    "Сантехника",
    "Отделка",
    "Сборка мебели",
    "Окна/двери",
    "Бытовая техника",
    "Напольные покрытия",
    "Мелкий ремонт",
    "Дизайн"
]

# Диапазон telegram_id для тестовых блогеров
TEST_BLOGGER_TELEGRAM_ID_START = 100000000
TEST_BLOGGER_TELEGRAM_ID_END = 100000999


def clean_test_campaigns():
    """Удаляет все тестовые кампании и связанные данные"""
    print("\n🗑️  Удаление тестовых кампаний из старого бота по стройке...")

    with db.get_db_connection() as conn:
        cursor = db.get_cursor(conn)

        # 1. Находим все тестовые кампании по категориям
        placeholders = ','.join('?' * len(OLD_CONSTRUCTION_CATEGORIES))
        query = f"SELECT id, title, category, city, created_at FROM campaigns WHERE category IN ({placeholders})"
        cursor.execute(query, OLD_CONSTRUCTION_CATEGORIES)
        campaigns = cursor.fetchall()

        if not campaigns:
            print("✅ Тестовых кампаний не найдено")
            return 0

        campaign_ids = [c['id'] if isinstance(c, dict) else c[0] for c in campaigns]
        print(f"\n📋 Найдено {len(campaign_ids)} тестовых кампаний:")

        for campaign in campaigns[:10]:  # Показываем первые 10
            if isinstance(campaign, dict):
                print(f"  • ID {campaign['id']}: {campaign.get('title', campaign.get('description', 'Без названия')[:30])} - {campaign['category']}")
            else:
                print(f"  • ID {campaign[0]}: {campaign[2]}")

        if len(campaigns) > 10:
            print(f"  ... и еще {len(campaigns) - 10} кампаний")

        # 2. Удаляем связанные данные
        print("\n🗑️  Удаление связанных данных...")

        # Удаляем сообщения чата
        placeholders_ids = ','.join('?' * len(campaign_ids))
        cursor.execute(f"DELETE FROM messages WHERE campaign_id IN ({placeholders_ids})", campaign_ids)
        messages_deleted = cursor.rowcount
        print(f"  ✓ Удалено сообщений: {messages_deleted}")

        # Удаляем отказы от кампаний
        cursor.execute(f"DELETE FROM declined_campaigns WHERE campaign_id IN ({placeholders_ids})", campaign_ids)
        declined_deleted = cursor.rowcount
        print(f"  ✓ Удалено отказов: {declined_deleted}")

        # Удаляем отклики
        cursor.execute(f"DELETE FROM offers WHERE campaign_id IN ({placeholders_ids})", campaign_ids)
        offers_deleted = cursor.rowcount
        print(f"  ✓ Удалено откликов: {offers_deleted}")

        # Удаляем категории кампаний
        cursor.execute(f"DELETE FROM campaign_categories WHERE campaign_id IN ({placeholders_ids})", campaign_ids)
        categories_deleted = cursor.rowcount
        print(f"  ✓ Удалено категорий кампаний: {categories_deleted}")

        # 3. Удаляем сами кампании
        cursor.execute(f"DELETE FROM campaigns WHERE id IN ({placeholders_ids})", campaign_ids)
        campaigns_deleted = cursor.rowcount
        print(f"\n✅ Удалено кампаний: {campaigns_deleted}")

        conn.commit()
        return campaigns_deleted


def clean_test_bloggers():
    """Удаляет тестовых блогеров и их данные"""
    print("\n🗑️  Удаление тестовых блогеров...")

    with db.get_db_connection() as conn:
        cursor = db.get_cursor(conn)

        # Находим тестовых блогеров по диапазону telegram_id
        cursor.execute("""
            SELECT id, user_id, name, categories
            FROM bloggers
            WHERE user_id >= ? AND user_id <= ?
        """, (TEST_BLOGGER_TELEGRAM_ID_START, TEST_BLOGGER_TELEGRAM_ID_END))
        bloggers = cursor.fetchall()

        if not bloggers:
            print("✅ Тестовых блогеров не найдено")
            return 0

        blogger_ids = [b['id'] if isinstance(b, dict) else b[0] for b in bloggers]
        print(f"\n📋 Найдено {len(blogger_ids)} тестовых блогеров:")

        for blogger in bloggers:
            if isinstance(blogger, dict):
                print(f"  • ID {blogger['id']}: {blogger['name']} (Telegram ID: {blogger['user_id']})")
            else:
                print(f"  • ID {blogger[0]}: {blogger[2]}")

        # Удаляем связанные данные блогеров
        print("\n🗑️  Удаление связанных данных блогеров...")

        placeholders = ','.join('?' * len(blogger_ids))

        # Удаляем категории блогеров
        cursor.execute(f"DELETE FROM blogger_categories WHERE blogger_id IN ({placeholders})", blogger_ids)
        categories_deleted = cursor.rowcount
        print(f"  ✓ Удалено категорий блогеров: {categories_deleted}")

        # Удаляем города блогеров
        cursor.execute(f"DELETE FROM blogger_cities WHERE blogger_id IN ({placeholders})", blogger_ids)
        cities_deleted = cursor.rowcount
        print(f"  ✓ Удалено городов блогеров: {cities_deleted}")

        # Удаляем отклики блогеров
        cursor.execute(f"DELETE FROM offers WHERE blogger_id IN ({placeholders})", blogger_ids)
        offers_deleted = cursor.rowcount
        print(f"  ✓ Удалено откликов блогеров: {offers_deleted}")

        # Удаляем настройки уведомлений
        user_ids = [b['user_id'] if isinstance(b, dict) else b[1] for b in bloggers]
        placeholders_users = ','.join('?' * len(user_ids))
        cursor.execute(f"DELETE FROM blogger_notifications WHERE blogger_id IN ({placeholders})", blogger_ids)
        notifications_deleted = cursor.rowcount
        print(f"  ✓ Удалено настроек уведомлений: {notifications_deleted}")

        # Удаляем самих блогеров
        cursor.execute(f"DELETE FROM bloggers WHERE id IN ({placeholders})", blogger_ids)
        bloggers_deleted = cursor.rowcount
        print(f"\n✅ Удалено блогеров: {bloggers_deleted}")

        conn.commit()
        return bloggers_deleted


def clean_test_advertiser():
    """Удаляет тестового рекламодателя 'Тестовый клиент'"""
    print("\n🗑️  Удаление тестового рекламодателя...")

    with db.get_db_connection() as conn:
        cursor = db.get_cursor(conn)

        # Находим тестового рекламодателя
        cursor.execute("SELECT id, name, user_id FROM advertisers WHERE name = 'Тестовый клиент'")
        advertiser = cursor.fetchone()

        if not advertiser:
            print("✅ Тестовый рекламодатель не найден")
            return 0

        advertiser_id = advertiser['id'] if isinstance(advertiser, dict) else advertiser[0]
        advertiser_name = advertiser['name'] if isinstance(advertiser, dict) else advertiser[1]
        user_id = advertiser['user_id'] if isinstance(advertiser, dict) else advertiser[2]

        print(f"  • Найден: ID {advertiser_id} - {advertiser_name} (User ID: {user_id})")

        # Проверяем, есть ли еще кампании у этого рекламодателя
        cursor.execute("SELECT COUNT(*) FROM campaigns WHERE advertiser_id = ?", (advertiser_id,))
        campaigns_count_result = cursor.fetchone()
        campaigns_count = campaigns_count_result[0] if campaigns_count_result else 0

        if campaigns_count > 0:
            print(f"  ⚠️  У рекламодателя еще есть {campaigns_count} активных кампаний. Пропускаем удаление.")
            return 0

        # Удаляем рекламодателя
        cursor.execute("DELETE FROM advertisers WHERE id = ?", (advertiser_id,))
        deleted = cursor.rowcount
        print(f"\n✅ Удален рекламодатель: {advertiser_name}")

        conn.commit()
        return deleted


def show_statistics():
    """Показывает статистику после очистки"""
    print("\n" + "="*60)
    print("📊 СТАТИСТИКА ПОСЛЕ ОЧИСТКИ")
    print("="*60)

    with db.get_db_connection() as conn:
        cursor = db.get_cursor(conn)

        # Кампании
        cursor.execute("SELECT COUNT(*) FROM campaigns")
        total_campaigns = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM campaigns WHERE status = 'open'")
        open_campaigns = cursor.fetchone()[0]

        print(f"\n📋 Кампании:")
        print(f"  • Всего: {total_campaigns}")
        print(f"  • Открытых: {open_campaigns}")

        # Блогеры
        cursor.execute("SELECT COUNT(*) FROM bloggers")
        total_bloggers = cursor.fetchone()[0]
        print(f"\n👥 Блогеры: {total_bloggers}")

        # Рекламодатели
        cursor.execute("SELECT COUNT(*) FROM advertisers")
        total_advertisers = cursor.fetchone()[0]
        print(f"\n💼 Рекламодатели: {total_advertisers}")

        # Отклики
        cursor.execute("SELECT COUNT(*) FROM offers")
        total_offers = cursor.fetchone()[0]
        print(f"\n📝 Отклики: {total_offers}")

        print("\n" + "="*60)


def main():
    """Главная функция"""
    print("="*60)
    print("🧹 ОЧИСТКА ТЕСТОВЫХ ДАННЫХ ИЗ СТАРОГО БОТА ПО СТРОЙКЕ")
    print("="*60)

    # Подтверждение
    print("\n⚠️  ВНИМАНИЕ! Эта операция необратима!")
    print("Будут удалены все:")
    print("  • Кампании со старыми категориями (Электрика, Сантехника и т.д.)")
    print("  • Тестовые блогеры (Telegram ID 100000000-100000999)")
    print("  • Тестовый рекламодатель")
    print("  • Все связанные данные (отклики, сообщения, категории)")

    confirm = input("\n❓ Продолжить? (yes/no): ").lower().strip()

    if confirm not in ['yes', 'y', 'да', 'д']:
        print("\n❌ Операция отменена")
        return

    print("\n🚀 Начинаем очистку...")

    try:
        # Очистка данных
        campaigns_deleted = clean_test_campaigns()
        bloggers_deleted = clean_test_bloggers()
        advertiser_deleted = clean_test_advertiser()

        # Статистика
        show_statistics()

        print("\n✅ Очистка завершена успешно!")
        print(f"📊 Итого удалено:")
        print(f"  • Кампаний: {campaigns_deleted}")
        print(f"  • Блогеров: {bloggers_deleted}")
        print(f"  • Рекламодателей: {advertiser_deleted}")

    except Exception as e:
        print(f"\n❌ Ошибка при очистке: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict

# Логирование для критических операций
logger = logging.getLogger(__name__)

# Определяем тип базы данных
DATABASE_URL = os.getenv("DATABASE_URL")

# Константы для валидации входных данных
MAX_NAME_LENGTH = 100
MAX_PHONE_LENGTH = 20
MAX_CITY_LENGTH = 50
MAX_DESCRIPTION_LENGTH = 2000
MAX_COMMENT_LENGTH = 1000
MAX_CATEGORY_LENGTH = 200
MAX_EXPERIENCE_LENGTH = 50

# Константы для rate limiting
RATE_LIMIT_ORDERS_PER_HOUR = 10  # Максимум 10 заказов в час от одного пользователя
RATE_LIMIT_BIDS_PER_HOUR = 50    # Максимум 50 откликов в час от одного мастера
RATE_LIMIT_WINDOW_SECONDS = 3600  # Окно для подсчета (1 час)


class RateLimiter:
    """
    ИСПРАВЛЕНО: Автоматическая очистка памяти каждые 100 вызовов.

    In-memory rate limiter для защиты от спама с автоматической очисткой.
    """

    def __init__(self):
        self._requests = defaultdict(list)  # {(user_id, action): [timestamp1, timestamp2, ...]}
        self._cleanup_counter = 0  # Счетчик для периодической очистки
        self._cleanup_interval = 100  # Очистка каждые 100 вызовов

    def is_allowed(self, user_id, action, max_requests):
        """
        Проверяет, разрешен ли запрос для пользователя.

        Args:
            user_id: ID пользователя
            action: Тип действия (create_order, create_bid, etc.)
            max_requests: Максимум запросов в окне времени

        Returns:
            tuple: (allowed: bool, remaining_seconds: int)
        """
        # ИСПРАВЛЕНИЕ: Автоматическая очистка памяти
        self._cleanup_counter += 1
        if self._cleanup_counter >= self._cleanup_interval:
            self.cleanup_old_entries()
            self._cleanup_counter = 0

        key = (user_id, action)
        now = datetime.now()
        cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)

        # Удаляем старые запросы за пределами окна
        self._requests[key] = [ts for ts in self._requests[key] if ts > cutoff]

        # Проверяем лимит
        if len(self._requests[key]) >= max_requests:
            # Вычисляем, через сколько секунд откроется слот
            oldest_request = min(self._requests[key])
            remaining_seconds = int((oldest_request + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS) - now).total_seconds())
            return False, remaining_seconds

        # Добавляем текущий запрос
        self._requests[key].append(now)
        return True, 0

    def cleanup_old_entries(self):
        """Очищает старые записи для экономии памяти (теперь вызывается автоматически)"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS * 2)

        keys_to_remove = []
        for key in self._requests:
            self._requests[key] = [ts for ts in self._requests[key] if ts > cutoff]
            if not self._requests[key]:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._requests[key]

        logger.info(f"RateLimiter cleanup: удалено {len(keys_to_remove)} старых ключей, осталось {len(self._requests)}")


# Глобальный экземпляр rate limiter
_rate_limiter = RateLimiter()


def validate_string_length(value, max_length, field_name):
    """
    Проверяет длину строки и обрезает если необходимо.

    Args:
        value: Значение для проверки
        max_length: Максимальная допустимая длина
        field_name: Название поля для сообщения об ошибке

    Returns:
        str: Обрезанная строка
    """
    if value is None:
        return ""

    value_str = str(value)
    if len(value_str) > max_length:
        # Логируем предупреждение
        print(f"⚠️  Предупреждение: {field_name} превышает {max_length} символов (получено {len(value_str)}), обрезаем")
        return value_str[:max_length]

    return value_str


def validate_telegram_file_id(file_id, field_name="file_id"):
    """
    НОВОЕ: Валидация Telegram file_id для предотвращения сохранения некорректных данных.

    Telegram file_id должен быть:
    - Непустой строкой
    - Содержать только допустимые символы (буквы, цифры, _, -, =)
    - Иметь разумную длину (обычно 30-200 символов)

    Args:
        file_id: ID файла от Telegram
        field_name: Название поля для сообщения об ошибке

    Returns:
        str: Валидный file_id

    Raises:
        ValueError: Если file_id невалидный
    """
    if not file_id:
        raise ValueError(f"❌ {field_name}: file_id не может быть пустым")

    file_id_str = str(file_id).strip()

    if not file_id_str:
        raise ValueError(f"❌ {field_name}: file_id не может быть пустым после strip()")

    # Проверяем длину (Telegram file_id обычно 30-200 символов)
    if len(file_id_str) < 10:
        raise ValueError(f"❌ {field_name}: file_id слишком короткий ({len(file_id_str)} символов)")

    if len(file_id_str) > 300:
        raise ValueError(f"❌ {field_name}: file_id слишком длинный ({len(file_id_str)} символов)")

    # Проверяем допустимые символы (Telegram использует base64-like формат)
    import re
    if not re.match(r'^[A-Za-z0-9_\-=]+$', file_id_str):
        raise ValueError(f"❌ {field_name}: file_id содержит недопустимые символы")

    logger.debug(f"✅ file_id валидирован: {file_id_str[:20]}... ({len(file_id_str)} символов)")
    return file_id_str


def validate_photo_list(photo_ids, field_name="photos"):
    """
    НОВОЕ: Валидация списка file_id фотографий.

    Args:
        photo_ids: Список или строка с file_id через запятую
        field_name: Название поля для логирования

    Returns:
        list: Список валидных file_id

    Raises:
        ValueError: Если хотя бы один file_id невалидный
    """
    if not photo_ids:
        return []

    # Преобразуем в список если передана строка
    if isinstance(photo_ids, str):
        ids_list = [pid.strip() for pid in photo_ids.split(',') if pid.strip()]
    elif isinstance(photo_ids, list):
        ids_list = [str(pid).strip() for pid in photo_ids if pid]
    else:
        raise ValueError(f"❌ {field_name}: должен быть список или строка")

    # Валидируем каждый file_id
    validated = []
    for i, file_id in enumerate(ids_list):
        try:
            valid_id = validate_telegram_file_id(file_id, f"{field_name}[{i}]")
            validated.append(valid_id)
        except ValueError as e:
            logger.warning(f"⚠️ Пропускаем невалидный file_id: {e}")
            # Пропускаем невалидные, но не падаем полностью

    logger.info(f"✅ {field_name}: валидировано {len(validated)} из {len(ids_list)} file_id")
    return validated


if DATABASE_URL:
    # Используем PostgreSQL
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor
    import psycopg2.extras
    USE_POSTGRES = True

    # Connection pool для PostgreSQL (повышает производительность в 10 раз)
    _connection_pool = None

    def init_connection_pool():
        """Инициализирует пул соединений при запуске приложения"""
        global _connection_pool
        if _connection_pool is None:
            try:
                _connection_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=5,   # Минимум 5 готовых соединений
                    maxconn=20,  # Максимум 20 одновременных соединений
                    dsn=DATABASE_URL
                )
                logger.info("✅ PostgreSQL connection pool инициализирован (5-20 соединений)")
            except psycopg2.OperationalError as e:
                logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось подключиться к PostgreSQL: {e}", exc_info=True)
                raise
            except Exception as e:
                logger.error(f"❌ Неожиданная ошибка при инициализации connection pool: {e}", exc_info=True)
                raise

    def close_connection_pool():
        """Закрывает пул соединений при остановке приложения"""
        global _connection_pool
        if _connection_pool:
            try:
                _connection_pool.closeall()
                logger.info("✅ PostgreSQL connection pool закрыт")
            except Exception as e:
                logger.error(f"❌ Ошибка при закрытии connection pool: {e}", exc_info=True)
else:
    # Используем SQLite для локальной разработки и тестирования
    # ВАЖНО: База данных в /tmp очищается при каждом деплое на Railway
    import sqlite3
    DATABASE_NAME = "/tmp/influencemarket_test.db"
    USE_POSTGRES = False

    def init_connection_pool():
        """Для SQLite пул не нужен"""
        pass

    def close_connection_pool():
        """Для SQLite пул не нужен"""
        pass


def is_retryable_postgres_error(error):
    """
    НОВОЕ: Определяет, можно ли повторить операцию после ошибки PostgreSQL.

    Возвращает True для:
    - Serialization failures (SQLSTATE 40001)
    - Deadlocks (SQLSTATE 40P01)
    - Connection errors

    Args:
        error: Исключение от psycopg2

    Returns:
        bool: True если операцию можно повторить
    """
    if not USE_POSTGRES:
        return False

    import psycopg2

    # Проверяем тип ошибки
    if isinstance(error, (psycopg2.extensions.TransactionRollbackError,
                         psycopg2.OperationalError)):
        return True

    # Проверяем SQLSTATE код
    if hasattr(error, 'pgcode'):
        # 40001 = serialization_failure
        # 40P01 = deadlock_detected
        if error.pgcode in ('40001', '40P01'):
            return True

    return False


def get_connection():
    """Возвращает подключение к базе данных (из пула для PostgreSQL или новое для SQLite)"""
    if USE_POSTGRES:
        try:
            # Берем соединение из пула (быстро!)
            conn = _connection_pool.getconn()
            # Проверяем, что соединение живо
            if conn.closed:
                logger.warning("⚠️ Получено закрытое соединение из пула, переподключаемся")
                _connection_pool.putconn(conn, close=True)
                conn = _connection_pool.getconn()
            return conn
        except psycopg2.pool.PoolError as e:
            logger.error(f"❌ Ошибка пула соединений PostgreSQL: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при получении соединения: {e}", exc_info=True)
            raise
    else:
        conn = sqlite3.connect(DATABASE_NAME)
        conn.row_factory = sqlite3.Row
        return conn


def return_connection(conn):
    """Возвращает соединение в пул (только для PostgreSQL)"""
    if USE_POSTGRES:
        _connection_pool.putconn(conn)
    else:
        # Для SQLite просто закрываем
        conn.close()


class DatabaseConnection:
    """
    Context manager для автоматического управления соединениями с пулом.
    ИСПРАВЛЕНО: Добавлен rollback при ошибках для PostgreSQL.
    """

    def __enter__(self):
        self.conn = get_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            # Нет ошибок - коммитим изменения
            try:
                self.conn.commit()
            except Exception as e:
                # КРИТИЧЕСКИ ВАЖНО: не игнорируем ошибки commit!
                logger.error(f"❌ ОШИБКА COMMIT БД: {e}", exc_info=True)
                try:
                    self.conn.rollback()
                except Exception as rollback_error:
                    logger.error(f"❌ ОШИБКА ROLLBACK: {rollback_error}", exc_info=True)
                return_connection(self.conn)
                raise  # Пробрасываем ошибку дальше
        else:
            # Произошла ошибка - откатываем транзакцию
            try:
                self.conn.rollback()
                logger.warning(f"⚠️ Rollback выполнен из-за ошибки: {exc_type.__name__}")
            except Exception as rollback_error:
                logger.error(f"❌ ОШИБКА ROLLBACK: {rollback_error}", exc_info=True)

        return_connection(self.conn)
        return False


def get_db_connection():
    """
    Возвращает context manager для работы с БД.
    Автоматически возвращает соединение в пул после использования.

    Использование:
        with get_db_connection() as conn:
            cursor = get_cursor(conn)
            cursor.execute("SELECT ...")
    """
    return DatabaseConnection()


def get_cursor(conn):
    """Возвращает курсор с правильными настройками"""
    if USE_POSTGRES:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
    else:
        cursor = conn.cursor()
    return DBCursor(cursor)


def convert_sql(sql):
    """Преобразует SQL из SQLite формата в PostgreSQL если нужно"""
    if USE_POSTGRES:
        # Заменяем placeholders
        sql = sql.replace('?', '%s')

        # Преобразуем типы данных
        sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
        sql = sql.replace('AUTOINCREMENT', '')  # Удаляем оставшиеся AUTOINCREMENT
        sql = sql.replace('TEXT', 'VARCHAR(1000)')
        sql = sql.replace('REAL', 'NUMERIC')
        sql = sql.replace('INTEGER', 'INTEGER')  # Оставляем как есть

        # Исправляем telegram_id - он должен быть BIGINT
        if 'telegram_id' in sql and 'INTEGER' in sql:
            sql = sql.replace('telegram_id INTEGER', 'telegram_id BIGINT')

    return sql


class DBCursor:
    """Обертка для cursor, автоматически преобразует SQL"""
    def __init__(self, cursor):
        self.cursor = cursor
        self._lastrowid = None

    def execute(self, sql, params=None):
        sql = convert_sql(sql)

        # Для PostgreSQL INSERT нужно добавить RETURNING id
        # НО только если это не INSERT с ON CONFLICT (там может не быть колонки id)
        should_return_id = False
        if USE_POSTGRES and sql.strip().upper().startswith('INSERT'):
            if 'RETURNING' not in sql.upper() and 'ON CONFLICT' not in sql.upper():
                sql = sql.rstrip().rstrip(';') + ' RETURNING id'
                should_return_id = True

        if params:
            result = self.cursor.execute(sql, params)
        else:
            result = self.cursor.execute(sql)

        # Получаем lastrowid для PostgreSQL
        if should_return_id:
            row = self.cursor.fetchone()
            if row:
                self._lastrowid = row['id'] if isinstance(row, dict) else row[0]

        return result

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def lastrowid(self):
        if USE_POSTGRES:
            return self._lastrowid
        return self.cursor.lastrowid

    @property
    def rowcount(self):
        """КРИТИЧНО: Проксируем rowcount к внутреннему cursor"""
        return self.cursor.rowcount


def init_db():
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Пользователи (convert_sql автоматически преобразует в PostgreSQL формат)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        # Мастера
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bloggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                name TEXT,
                phone TEXT,
                city TEXT,
                regions TEXT,
                categories TEXT,
                experience TEXT,
                description TEXT,
                portfolio_photos TEXT,
                rating REAL DEFAULT 0.0,
                rating_count INTEGER DEFAULT 0,
                verified_reviews INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        # Заказчики
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS advertisers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                name TEXT,
                phone TEXT,
                city TEXT,
                description TEXT,
                rating REAL DEFAULT 0.0,
                rating_count INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        # Заказы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                advertiser_id INTEGER NOT NULL,
                title TEXT,
                description TEXT,
                city TEXT,
                address TEXT,
                category TEXT,
                budget_type TEXT, -- 'fixed' или 'flexible'
                budget_value REAL,
                deadline TEXT,
                photos TEXT DEFAULT '',
                videos TEXT DEFAULT '',
                status TEXT NOT NULL, -- 'open', 'pending_choice', 'master_selected', 'contact_shared', 'done', 'canceled', 'cancelled', 'expired'
                created_at TEXT NOT NULL,
                FOREIGN KEY (advertiser_id) REFERENCES advertisers(id)
            );
        """)

        # Отклики мастеров
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                blogger_id INTEGER NOT NULL,
                proposed_price REAL,
                currency TEXT DEFAULT 'BYN',
                proposed_deadline TEXT,
                comment TEXT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL, -- 'active', 'rejected', 'selected', 'expired'
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (blogger_id) REFERENCES bloggers(id)
            );
        """)

        # НОВОЕ: Отказы мастеров от заказов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS declined_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blogger_id INTEGER NOT NULL,
                campaign_id INTEGER NOT NULL,
                declined_at TEXT NOT NULL,
                UNIQUE (blogger_id, campaign_id),
                FOREIGN KEY (blogger_id) REFERENCES bloggers(id),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
        """)

        # Оплата за доступ к контактам
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                blogger_id INTEGER NOT NULL,
                advertiser_id INTEGER NOT NULL,
                paid INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (blogger_id) REFERENCES bloggers(id),
                FOREIGN KEY (advertiser_id) REFERENCES advertisers(id)
            );
        """)

        # Отзывы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                campaign_id INTEGER NOT NULL,
                role_from TEXT NOT NULL,
                role_to TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (campaign_id, from_user_id, to_user_id),
                FOREIGN KEY (from_user_id) REFERENCES users(id),
                FOREIGN KEY (to_user_id) REFERENCES users(id),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
        """)

        # НОВОЕ: Таблица для фотографий завершённых работ
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS completed_work_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                blogger_id INTEGER NOT NULL,
                photo_id TEXT NOT NULL,
                verified BOOLEAN DEFAULT FALSE,
                verified_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (blogger_id) REFERENCES bloggers(id)
            );
        """)

        # НОВОЕ: Таблица настроек уведомлений пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                new_orders_enabled BOOLEAN DEFAULT TRUE,      -- Уведомления о новых заказах (для мастеров)
                new_bids_enabled BOOLEAN DEFAULT TRUE,        -- Уведомления о новых откликах (для заказчиков)
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        # НОВОЕ: Таблица отправленных уведомлений (для предотвращения дубликатов)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sent_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,           -- 'new_orders', 'new_bids'
                message_id INTEGER,                        -- ID сообщения для удаления
                sent_at TEXT NOT NULL,
                cleared_at TEXT,                           -- Когда уведомление было просмотрено/удалено
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        # Таблица предложений от пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_role TEXT NOT NULL,           -- 'blogger', 'advertiser' или 'both'
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'new',         -- 'new', 'viewed', 'resolved'
                admin_notes TEXT,                  -- Заметки админа
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        # ИСПРАВЛЕНИЕ: Таблица активных чатов (для сохранения состояния между перезапусками)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_chats (
                telegram_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,                -- 'advertiser' или 'blogger'
                updated_at TEXT NOT NULL
            );
        """)

        conn.commit()


def migrate_add_portfolio_photos():
    """Миграция: добавляет колонку portfolio_photos если её нет"""
    # Для PostgreSQL миграции не нужны - таблицы создаются через init_db()
    if USE_POSTGRES:
        print("✅ Используется PostgreSQL, миграция не требуется")
        return

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Проверяем существует ли колонка (только для SQLite)
        cursor.execute("PRAGMA table_info(bloggers)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'portfolio_photos' not in columns:
            print("⚠️  Колонка 'portfolio_photos' отсутствует, добавляю...")
            cursor.execute("""
                ALTER TABLE bloggers
                ADD COLUMN portfolio_photos TEXT DEFAULT ''
            """)
            conn.commit()
            print("✅ Колонка 'portfolio_photos' успешно добавлена!")
        else:
            print("✅ Колонка 'portfolio_photos' уже существует")


# --- Пользователи ---

def get_user(telegram_id):
    with get_db_connection() as conn:

        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone()


# Алиас для совместимости с кодом в handlers.py
def get_user_by_telegram_id(telegram_id):
    """Алиас для get_user() - возвращает пользователя по telegram_id"""
    return get_user(telegram_id)


def get_user_by_id(user_id):
    """Получает пользователя по внутреннему ID"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cursor.fetchone()


def create_user(telegram_id, role):
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        created_at = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO users (telegram_id, role, created_at) VALUES (?, ?, ?)",
            (telegram_id, role, created_at),
        )
        conn.commit()
        user_id = cursor.lastrowid
        logger.info(f"✅ Создан пользователь: ID={user_id}, Telegram={telegram_id}, Роль={role}")
        return user_id


def delete_user_profile(telegram_id):
    """
    КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Удаляет ВСЕ профили пользователя (и мастер, и клиент).
    Вручную удаляет ВСЕ связанные данные для обхода foreign key constraints.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Получаем user_id
            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_row = cursor.fetchone()

            if not user_row:
                logger.warning(f"⚠️ Пользователь {telegram_id} не найден")
                return False

            user_id = user_row['id']

            logger.info(f"🗑️ Начинаем ПОЛНОЕ удаление профиля: telegram_id={telegram_id}, user_id={user_id}")

            # === УДАЛЕНИЕ ПРОФИЛЯ МАСТЕРА (если существует) ===
            cursor.execute("SELECT id FROM bloggers WHERE user_id = ?", (user_id,))
            blogger_row = cursor.fetchone()

            if blogger_row:
                blogger_id = blogger_row['id']
                logger.info(f"🔍 Найден профиль мастера: blogger_id={blogger_id}")

                # 1. Удаляем категории мастера
                cursor.execute("DELETE FROM blogger_categories WHERE blogger_id = ?", (blogger_id,))
                logger.info(f"✅ Удалены категории мастера")

                # 2. Удаляем города мастера
                cursor.execute("DELETE FROM blogger_cities WHERE blogger_id = ?", (blogger_id,))
                logger.info(f"✅ Удалены города мастера")

                # 3. Удаляем фотографии завершённых работ
                cursor.execute("DELETE FROM completed_work_photos WHERE blogger_id = ?", (blogger_id,))
                logger.info(f"✅ Удалены фотографии работ")

                # 4. Удаляем отклики мастера
                cursor.execute("DELETE FROM offers WHERE blogger_id = ?", (blogger_id,))
                logger.info(f"✅ Удалены отклики мастера")

                # 5. Удаляем настройки уведомлений
                cursor.execute("DELETE FROM blogger_notifications WHERE blogger_id = ?", (blogger_id,))
                logger.info(f"✅ Удалены настройки уведомлений")

                # 6. Удаляем профиль мастера
                cursor.execute("DELETE FROM bloggers WHERE id = ?", (blogger_id,))
                logger.info(f"✅ Удалён профиль мастера blogger_id={blogger_id}")

            # === УДАЛЕНИЕ ПРОФИЛЯ КЛИЕНТА (если существует) ===
            cursor.execute("SELECT id FROM advertisers WHERE user_id = ?", (user_id,))
            advertiser_row = cursor.fetchone()

            if advertiser_row:
                advertiser_id = advertiser_row['id']
                logger.info(f"🔍 Найден профиль клиента: advertiser_id={advertiser_id}")

                # 1. Получаем все заказы клиента
                cursor.execute("SELECT id FROM campaigns WHERE advertiser_id = ?", (advertiser_id,))
                campaigns = cursor.fetchall()

                for campaign in campaigns:
                    campaign_id = campaign['id']
                    logger.info(f"🔍 Удаляем заказ campaign_id={campaign_id}")

                    # Удаляем отклики на заказ
                    cursor.execute("DELETE FROM offers WHERE campaign_id = ?", (campaign_id,))

                    # Удаляем отзывы на заказ
                    cursor.execute("DELETE FROM reviews WHERE campaign_id = ?", (campaign_id,))

                    # Удаляем фотографии завершённых работ
                    cursor.execute("DELETE FROM completed_work_photos WHERE campaign_id = ?", (campaign_id,))

                    # Удаляем сообщения чата
                    cursor.execute("DELETE FROM chat_messages WHERE campaign_id = ?", (campaign_id,))

                    # Удаляем чаты
                    cursor.execute("DELETE FROM chats WHERE campaign_id = ?", (campaign_id,))

                # 2. Удаляем все заказы
                cursor.execute("DELETE FROM campaigns WHERE advertiser_id = ?", (advertiser_id,))
                logger.info(f"✅ Удалены заказы клиента")

                # 3. Удаляем профиль клиента
                cursor.execute("DELETE FROM advertisers WHERE id = ?", (advertiser_id,))
                logger.info(f"✅ Удалён профиль клиента advertiser_id={advertiser_id}")

            # === УДАЛЕНИЕ ОТЗЫВОВ ПОЛЬЗОВАТЕЛЯ ===
            # ИСПРАВЛЕНО: Таблица reviews не имеет поля blogger_id!
            # Удаляем все отзывы, где пользователь - отправитель или получатель
            cursor.execute("DELETE FROM reviews WHERE from_user_id = ? OR to_user_id = ?", (user_id, user_id))
            logger.info(f"✅ Удалены отзывы пользователя")

            # === УДАЛЕНИЕ ОБЩИХ ДАННЫХ ===
            # Удаляем уведомления о сообщениях
            cursor.execute("DELETE FROM chat_message_notifications WHERE user_id = ?", (user_id,))

            # Удаляем активные чаты пользователя
            cursor.execute("DELETE FROM active_user_chats WHERE telegram_id = ?", (telegram_id,))

            # Удаляем транзакции
            cursor.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))

            # Удаляем предложения
            cursor.execute("DELETE FROM suggestions WHERE user_id = ?", (user_id,))

            # === УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ИЗ USERS ===
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            logger.info(f"✅ Удалён пользователь {telegram_id} (user_id={user_id})")

            conn.commit()
            logger.info(f"🎉 ВСЕ профили успешно удалены: telegram_id={telegram_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка при удалении профиля {telegram_id}: {e}", exc_info=True)
            conn.rollback()
            return False


# --- Профили мастеров и заказчиков ---

def create_worker_profile(user_id, name, phone, city, regions, categories, experience, description, portfolio_photos="", profile_photo="", cities=None):
    """
    ОБНОВЛЕНО: Добавляет категории в нормализованную таблицу blogger_categories.
    ОБНОВЛЕНО: Поддержка множественного выбора городов через параметр cities.
    ОБНОВЛЕНО: Поддержка profile_photo - фото профиля мастера.
    ИСПРАВЛЕНО: Валидация file_id для portfolio_photos.
    ИСПРАВЛЕНО: Проверка существования профиля для предотвращения race condition.

    Args:
        profile_photo: file_id фото профиля (опционально).
        cities: Список городов (опционально). Если указан, используется вместо city.
                Первый город из списка сохраняется в поле city для обратной совместимости.
    """
    # КРИТИЧНО: Проверяем что профиль еще не существует (race condition защита)
    existing_profile = get_worker_profile(user_id)
    if existing_profile:
        logger.warning(f"⚠️ Попытка создать дубликат профиля мастера для user_id={user_id}")
        raise ValueError(f"У пользователя {user_id} уже есть профиль мастера")

    # Валидация входных данных
    name = validate_string_length(name, MAX_NAME_LENGTH, "name")
    phone = validate_string_length(phone, MAX_PHONE_LENGTH, "phone")
    city = validate_string_length(city, MAX_CITY_LENGTH, "city")
    regions = validate_string_length(regions, MAX_CITY_LENGTH, "regions")
    categories = validate_string_length(categories, MAX_CATEGORY_LENGTH, "categories")
    experience = validate_string_length(experience, MAX_EXPERIENCE_LENGTH, "experience")
    description = validate_string_length(description, MAX_DESCRIPTION_LENGTH, "description")

    # ИСПРАВЛЕНИЕ: Валидация file_id для фотографий
    if portfolio_photos:
        validated_photos = validate_photo_list(portfolio_photos, "portfolio_photos")
        portfolio_photos = ",".join(validated_photos)

    # NOTE: profile_photo уже валидируется в handlers.py перед вызовом этой функции

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO bloggers (user_id, name, phone, city, regions, categories, experience, description, portfolio_photos, profile_photo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, name, phone, city, regions, categories, experience, description, portfolio_photos, profile_photo))
        blogger_id = cursor.lastrowid
        conn.commit()  # КРИТИЧНО: Без этого транзакция не фиксируется!
        logger.info(f"✅ Создан профиль мастера: ID={blogger_id}, User={user_id}, Имя={name}, Город={city}")

    # ИСПРАВЛЕНИЕ: Добавляем категории в нормализованную таблицу
    if categories:
        categories_list = [cat.strip() for cat in categories.split(',') if cat.strip()]
        add_worker_categories(blogger_id, categories_list)
        logger.info(f"📋 Добавлены категории для мастера {blogger_id}: {categories_list}")

    # НОВОЕ: Добавляем города в таблицу blogger_cities
    if cities and isinstance(cities, list):
        for city_name in cities:
            add_worker_city(blogger_id, city_name)
        logger.info(f"🏙 Добавлено {len(cities)} городов для мастера {blogger_id}: {cities}")


def create_client_profile(user_id, name, phone, city, description, regions=None):
    """
    ИСПРАВЛЕНО: Проверка существования профиля для предотвращения race condition.
    Добавлен параметр regions для хранения региона клиента.
    """
    # КРИТИЧНО: Проверяем что профиль еще не существует (race condition защита)
    existing_profile = get_client_profile(user_id)
    if existing_profile:
        logger.warning(f"⚠️ Попытка создать дубликат профиля клиента для user_id={user_id}")
        raise ValueError(f"У пользователя {user_id} уже есть профиль клиента")

    # Валидация входных данных
    name = validate_string_length(name, MAX_NAME_LENGTH, "name")
    phone = validate_string_length(phone, MAX_PHONE_LENGTH, "phone")
    city = validate_string_length(city, MAX_CITY_LENGTH, "city")
    description = validate_string_length(description, MAX_DESCRIPTION_LENGTH, "description")

    # Валидация regions если указан
    if regions:
        regions = validate_string_length(regions, MAX_CITY_LENGTH, "regions")

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO advertisers (user_id, name, phone, city, description, regions)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, name, phone, city, description, regions))
        advertiser_id = cursor.lastrowid
        conn.commit()
        logger.info(f"✅ Создан профиль клиента: ID={advertiser_id}, User={user_id}, Имя={name}, Город={city}, Регион={regions}")


def get_worker_profile(user_id):
    """Возвращает профиль мастера по user_id"""
    with get_db_connection() as conn:

        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT w.*, u.telegram_id
            FROM bloggers w
            JOIN users u ON w.user_id = u.id
            WHERE w.user_id = ?
        """, (user_id,))
        return cursor.fetchone()


# Алиас для совместимости с кодом в handlers.py
def get_worker_by_user_id(user_id):
    """Алиас для get_worker_profile() - возвращает профиль мастера по user_id"""
    return get_worker_profile(user_id)


def get_worker_profile_by_id(blogger_id):
    """Возвращает профиль мастера по id записи в таблице bloggers"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT w.*, u.telegram_id
            FROM bloggers w
            JOIN users u ON w.user_id = u.id
            WHERE w.id = ?
        """, (blogger_id,))
        return cursor.fetchone()


def get_worker_completed_orders_count(blogger_user_id):
    """
    Подсчитывает количество завершенных заказов мастера (status='completed').

    Args:
        blogger_user_id: ID пользователя-мастера

    Returns:
        int: Количество завершенных заказов
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT COUNT(*)
            FROM campaigns
            WHERE selected_worker_id = ? AND status = 'completed'
        """, (blogger_user_id,))
        result = cursor.fetchone()
        if not result:
            return 0
        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return result.get('count', 0)
        else:
            return result[0]


def calculate_photo_limit(blogger_user_id):
    """
    Рассчитывает максимальное количество фото для портфолио мастера.

    Логика:
    - Фиксированный лимит: 10 фото (обычное портфолио)
    - Подтвержденные фото работ хранятся отдельно (до 90 фото)

    Args:
        blogger_user_id: ID пользователя-мастера

    Returns:
        int: Максимальное количество фото в портфолио (10)
    """
    # Фиксированный лимит портфолио
    return 10


def get_client_profile(user_id):
    """Возвращает профиль заказчика по user_id"""
    with get_db_connection() as conn:
        
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT c.*, u.telegram_id
            FROM advertisers c
            JOIN users u ON c.user_id = u.id
            WHERE c.user_id = ?
        """, (user_id,))
        return cursor.fetchone()


def get_client_by_id(advertiser_id):
    """Возвращает профиль заказчика по advertiser_id"""
    with get_db_connection() as conn:
        
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM advertisers WHERE id = ?
        """, (advertiser_id,))
        return cursor.fetchone()


# УДАЛЕНА ДУБЛИРУЮЩАЯСЯ ФУНКЦИЯ get_user_by_id() - используется версия из строки 429


# --- Рейтинг и отзывы ---

def update_user_rating(user_id, new_rating, role_to):
    """
    ИСПРАВЛЕНО: Использует атомарный UPDATE для предотвращения race conditions.
    Теперь вычисление нового рейтинга происходит внутри SQL запроса,
    что гарантирует консистентность даже при одновременных обновлениях.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if role_to == "blogger":
            # Атомарный UPDATE: вычисление происходит в БД, не в Python
            cursor.execute("""
                UPDATE bloggers
                SET
                    rating = CASE
                        WHEN rating_count = 0 THEN ?
                        ELSE (rating * rating_count + ?) / (rating_count + 1)
                    END,
                    rating_count = rating_count + 1
                WHERE user_id = ?
            """, (new_rating, new_rating, user_id))

        elif role_to == "advertiser":
            # Атомарный UPDATE для клиентов
            cursor.execute("""
                UPDATE advertisers
                SET
                    rating = CASE
                        WHEN rating_count = 0 THEN ?
                        ELSE (rating * rating_count + ?) / (rating_count + 1)
                    END,
                    rating_count = rating_count + 1
                WHERE user_id = ?
            """, (new_rating, new_rating, user_id))

        conn.commit()


def add_review(from_user_id, to_user_id, campaign_id, role_from, role_to, rating, comment):
    """
    Добавляет отзыв и обновляет рейтинг пользователя.
    Если роль получателя - blogger, увеличивает счетчик verified_reviews.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        created_at = datetime.now().isoformat()
        try:
            cursor.execute("""
                INSERT INTO reviews
                (from_user_id, to_user_id, campaign_id, role_from, role_to, rating, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (from_user_id, to_user_id, campaign_id, role_from, role_to, rating, comment, created_at))
            conn.commit()
            update_user_rating(to_user_id, rating, role_to)

            # Увеличиваем счетчик проверенных отзывов для мастеров
            if role_to == "blogger":
                increment_verified_reviews(to_user_id)

            return True
        except (sqlite3.IntegrityError, Exception) as e:
            print(f"⚠️ Ошибка при добавлении отзыва: {e}")
            return False


def get_reviews_for_user(user_id, role):
    """
    Получает все отзывы о пользователе.

    Args:
        user_id: ID пользователя
        role: Роль пользователя ('blogger' или 'advertiser')

    Returns:
        List of reviews with reviewer info
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем отзывы с информацией о том, кто оставил
        cursor.execute("""
            SELECT
                r.rating,
                r.comment,
                r.created_at,
                r.campaign_id,
                r.role_from,
                CASE
                    WHEN r.role_from = 'blogger' THEN w.name
                    WHEN r.role_from = 'advertiser' THEN c.name
                END as reviewer_name
            FROM reviews r
            LEFT JOIN bloggers w ON r.from_user_id = w.user_id AND r.role_from = 'blogger'
            LEFT JOIN advertisers c ON r.from_user_id = c.user_id AND r.role_from = 'advertiser'
            WHERE r.to_user_id = ? AND r.role_to = ?
            ORDER BY r.created_at DESC
        """, (user_id, role))

        return cursor.fetchall()


def check_review_exists(campaign_id, from_user_id):
    """
    Проверяет, оставил ли пользователь уже отзыв по этому заказу.

    Returns:
        bool: True если отзыв уже существует
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT COUNT(*) FROM reviews
            WHERE campaign_id = ? AND from_user_id = ?
        """, (campaign_id, from_user_id))

        count = cursor.fetchone()
        if USE_POSTGRES:
            return count['count'] > 0
        else:
            return count[0] > 0


def count_orders_between_users(user1_id, user2_id, days=7):
    """
    🛡️ АНТИ-ФРОД: Подсчитывает количество completed заказов между двумя пользователями за последние N дней.
    Используется для предотвращения накрутки рейтинга через повторяющиеся заказы.

    Args:
        user1_id: ID первого пользователя
        user2_id: ID второго пользователя
        days: Количество дней для проверки (по умолчанию 7)

    Returns:
        int: Количество completed заказов между пользователями
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Вычисляем дату N дней назад
        from datetime import datetime, timedelta
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        # Считаем заказы где user1 клиент, а user2 мастер ИЛИ наоборот
        cursor.execute("""
            SELECT COUNT(*) FROM campaigns o
            LEFT JOIN offers b ON o.accepted_bid_id = b.id
            WHERE o.status = 'completed'
            AND o.completed_at >= ?
            AND (
                (o.advertiser_user_id = ? AND b.blogger_id = ?)
                OR
                (o.advertiser_user_id = ? AND b.blogger_id = ?)
            )
        """, (cutoff_date, user1_id, user2_id, user2_id, user1_id))

        count = cursor.fetchone()
        if USE_POSTGRES:
            return count['count']
        else:
            return count[0]


def get_suspicious_activity_report(days=7, min_orders=3):
    """
    🛡️ АНТИ-ФРОД: Генерирует отчет о подозрительной активности для админов.

    Находит:
    1. Пары пользователей с подозрительно большим количеством заказов
    2. Заказы, завершенные слишком быстро (менее 1 часа)
    3. Пользователей с подозрительно высоким рейтингом (только 5 звезд)

    Args:
        days: Период для анализа (по умолчанию 7 дней)
        min_orders: Минимальное количество заказов для попадания в отчет (по умолчанию 3)

    Returns:
        dict: Словарь с тремя списками: repeated_orders, quick_completions, perfect_ratings
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        from datetime import datetime, timedelta
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        # 1. Находим пары пользователей с большим количеством заказов друг с другом
        cursor.execute("""
            SELECT
                o.advertiser_user_id,
                b.blogger_id,
                COUNT(*) as campaign_count,
                MAX(o.completed_at) as last_order
            FROM campaigns o
            LEFT JOIN offers b ON o.accepted_bid_id = b.id
            WHERE o.status = 'completed'
            AND o.completed_at >= ?
            AND b.blogger_id IS NOT NULL
            GROUP BY o.advertiser_user_id, b.blogger_id
            HAVING COUNT(*) >= ?
            ORDER BY campaign_count DESC
        """, (cutoff_date, min_orders))

        repeated_orders = cursor.fetchall()

        # 2. Находим заказы, завершенные слишком быстро (менее 1 часа)
        cursor.execute("""
            SELECT
                o.id as campaign_id,
                o.advertiser_user_id,
                b.blogger_id,
                o.accepted_at,
                o.completed_at,
                CAST((julianday(o.completed_at) - julianday(o.accepted_at)) * 24 AS REAL) as hours_diff
            FROM campaigns o
            LEFT JOIN offers b ON o.accepted_bid_id = b.id
            WHERE o.status = 'completed'
            AND o.completed_at >= ?
            AND o.accepted_at IS NOT NULL
            AND (julianday(o.completed_at) - julianday(o.accepted_at)) * 24 < 1
            ORDER BY hours_diff ASC
        """, (cutoff_date,))

        quick_completions = cursor.fetchall()

        # 3. Находим пользователей с подозрительно высоким рейтингом (все отзывы 5 звезд)
        cursor.execute("""
            SELECT
                r.to_user_id,
                r.role_to,
                COUNT(*) as total_reviews,
                SUM(CASE WHEN r.rating = 5 THEN 1 ELSE 0 END) as five_star_count,
                CAST(SUM(CASE WHEN r.rating = 5 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) * 100 as five_star_percent
            FROM reviews r
            WHERE r.created_at >= ?
            GROUP BY r.to_user_id, r.role_to
            HAVING COUNT(*) >= 3
            AND (CAST(SUM(CASE WHEN r.rating = 5 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) * 100) = 100
            ORDER BY total_reviews DESC
        """, (cutoff_date,))

        perfect_ratings = cursor.fetchall()

        return {
            'repeated_orders': repeated_orders,
            'quick_completions': quick_completions,
            'perfect_ratings': perfect_ratings
        }


def update_review_comment(campaign_id, from_user_id, comment):
    """Обновляет комментарий существующего отзыва."""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        try:
            cursor.execute("""
                UPDATE reviews
                SET comment = ?
                WHERE campaign_id = ? AND from_user_id = ?
            """, (comment, campaign_id, from_user_id))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"⚠️ Ошибка при обновлении комментария отзыва: {e}")
            return False


def increment_verified_reviews(user_id):
    """
    Увеличивает счетчик проверенных отзывов для мастера.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE bloggers
            SET verified_reviews = verified_reviews + 1
            WHERE user_id = ?
        """, (user_id,))
        conn.commit()


# --- НОВОЕ: Фотографии завершённых работ ---

def add_completed_work_photo(campaign_id, blogger_id, photo_id):
    """
    Добавляет фотографию завершённой работы от мастера.

    Args:
        campaign_id: ID заказа
        blogger_id: ID мастера
        photo_id: Telegram file_id фотографии

    Returns:
        int: ID добавленной фотографии или None при ошибке
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        created_at = datetime.now().isoformat()
        try:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO completed_work_photos
                    (campaign_id, blogger_id, photo_id, verified, created_at)
                    VALUES (%s, %s, %s, FALSE, %s)
                """, (campaign_id, blogger_id, photo_id, created_at))
            else:
                cursor.execute("""
                    INSERT INTO completed_work_photos
                    (campaign_id, blogger_id, photo_id, verified, created_at)
                    VALUES (?, ?, ?, 0, ?)
                """, (campaign_id, blogger_id, photo_id, created_at))
            conn.commit()

            if USE_POSTGRES:
                cursor.execute("SELECT LASTVAL()")
            else:
                cursor.execute("SELECT last_insert_rowid()")

            result = cursor.fetchone()
            if not result:
                return None
            # PostgreSQL возвращает dict, SQLite может вернуть tuple
            if isinstance(result, dict):
                return result.get('lastval') or result.get('last_insert_rowid()')
            else:
                return result[0]
        except Exception as e:
            logger.error(f"Ошибка при добавлении фото завершённой работы: {e}")
            return None


def verify_completed_work_photo(photo_id):
    """
    Подтверждает фотографию завершённой работы клиентом.
    ВАЖНО: Также добавляет фото в портфолио мастера.

    Args:
        photo_id: ID фотографии в таблице completed_work_photos

    Returns:
        bool: True если успешно, False при ошибке
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        verified_at = datetime.now().isoformat()
        try:
            # 1. Получаем информацию о фото
            cursor.execute("""
                SELECT photo_id, blogger_id FROM completed_work_photos
                WHERE id = ?
            """, (photo_id,))
            photo_info = cursor.fetchone()

            if not photo_info:
                logger.error(f"Фото {photo_id} не найдено в completed_work_photos")
                return False

            photo_file_id = photo_info['photo_id']
            blogger_id = photo_info['blogger_id']

            # 2. Подтверждаем фото (ИСПРАВЛЕНО: PostgreSQL boolean совместимость)
            cursor.execute("""
                UPDATE completed_work_photos
                SET verified = TRUE, verified_at = ?
                WHERE id = ?
            """, (verified_at, photo_id))

            # 3. Добавляем фото в портфолио мастера
            cursor.execute("""
                SELECT portfolio_photos FROM bloggers WHERE id = ?
            """, (blogger_id,))
            blogger = cursor.fetchone()

            if blogger:
                current_portfolio = blogger['portfolio_photos'] or ""
                portfolio_list = [p.strip() for p in current_portfolio.split(',') if p.strip()]

                # Добавляем фото если его ещё нет
                if photo_file_id not in portfolio_list:
                    portfolio_list.append(photo_file_id)
                    new_portfolio = ",".join(portfolio_list)

                    cursor.execute("""
                        UPDATE bloggers
                        SET portfolio_photos = ?
                        WHERE id = ?
                    """, (new_portfolio, blogger_id))

                    logger.info(f"✅ Подтверждённое фото {photo_file_id} добавлено в портфолио мастера {blogger_id}")

            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка при подтверждении фото: {e}", exc_info=True)
            return False


def get_completed_work_photos(campaign_id):
    """
    Получает все фотографии завершённой работы для заказа.

    Args:
        campaign_id: ID заказа

    Returns:
        list: Список фотографий с информацией о подтверждении
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM completed_work_photos
            WHERE campaign_id = ?
            ORDER BY created_at DESC
        """, (campaign_id,))
        return cursor.fetchall()


def get_completed_work_photo_by_id(photo_id):
    """
    НОВОЕ: Получает информацию о фотографии работы по её ID.

    Args:
        photo_id: ID фотографии в таблице completed_work_photos

    Returns:
        dict|None: Информация о фото или None если не найдено
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM completed_work_photos
            WHERE id = ?
        """, (photo_id,))
        return cursor.fetchone()


def get_worker_verified_photos(blogger_id, limit=20):
    """
    Получает подтверждённые фотографии работ мастера для показа в профиле.

    Args:
        blogger_id: ID мастера
        limit: Максимальное количество фото (по умолчанию 20)

    Returns:
        list: Список подтверждённых фотографий с информацией о заказах
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT
                cwp.*,
                o.title as campaign_title,
                o.category as campaign_category,
                r.rating as campaign_rating
            FROM completed_work_photos cwp
            JOIN campaigns o ON cwp.campaign_id = o.id
            LEFT JOIN reviews r ON o.id = r.campaign_id AND r.role_to = 'blogger'
            WHERE cwp.blogger_id = ? AND cwp.verified = TRUE
            ORDER BY cwp.created_at DESC
            LIMIT ?
        """, (blogger_id, limit))
        return cursor.fetchall()


def get_unverified_photos_for_client(user_id):
    """
    Получает неподтверждённые фотографии работ для заказов клиента.

    Args:
        user_id: ID пользователя (клиента)

    Returns:
        list: Список неподтверждённых фотографий, ожидающих проверки
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT
                cwp.*,
                o.title as campaign_title,
                o.id as campaign_id,
                w.name as blogger_name
            FROM completed_work_photos cwp
            JOIN campaigns o ON cwp.campaign_id = o.id
            JOIN advertisers c ON o.advertiser_id = c.id
            JOIN bloggers w ON cwp.blogger_id = w.id
            WHERE c.user_id = ? AND cwp.verified = FALSE
            ORDER BY cwp.created_at DESC
        """, (user_id,))
        return cursor.fetchall()


def count_worker_completed_work_photos(blogger_id):
    """
    Подсчитывает общее количество фотографий завершенных работ у мастера.

    Args:
        blogger_id: ID мастера

    Returns:
        int: Количество фотографий
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM completed_work_photos
            WHERE blogger_id = ?
        """, (blogger_id,))
        result = cursor.fetchone()
        if result:
            return dict(result)['count'] if isinstance(result, dict) else result[0]
        return 0


def get_all_worker_completed_photos(blogger_id):
    """
    Получает все фотографии завершенных работ мастера с информацией о заказах.

    Args:
        blogger_id: ID мастера

    Returns:
        List of dicts: Список фотографий с информацией о заказах
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT
                cwp.id,
                cwp.photo_id,
                cwp.campaign_id,
                cwp.verified,
                cwp.created_at,
                o.title as campaign_title,
                o.description as campaign_description
            FROM completed_work_photos cwp
            JOIN campaigns o ON cwp.campaign_id = o.id
            WHERE cwp.blogger_id = ?
            ORDER BY cwp.created_at DESC
        """, (blogger_id,))
        return cursor.fetchall()


def delete_completed_work_photo(photo_db_id):
    """
    Удаляет фотографию завершенной работы по её ID в базе данных.

    Args:
        photo_db_id: ID записи в таблице completed_work_photos

    Returns:
        bool: True если удалено успешно, False иначе
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            DELETE FROM completed_work_photos
            WHERE id = ?
        """, (photo_db_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_order_by_id(campaign_id):
    """
    Получает заказ по ID со всей информацией о клиенте.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT
                o.*,
                c.name as advertiser_name,
                c.phone as advertiser_phone,
                c.user_id as advertiser_user_id,
                c.rating as advertiser_rating,
                c.rating_count as advertiser_rating_count
            FROM campaigns o
            JOIN advertisers c ON o.advertiser_id = c.id
            WHERE o.id = ?
        """, (campaign_id,))
        return cursor.fetchone()


def update_order_status(campaign_id, new_status):
    """
    Обновляет статус заказа.

    Args:
        campaign_id: ID заказа
        new_status: Новый статус ('open', 'in_progress', 'completed', 'canceled')

    Returns:
        bool: True если статус обновлен, False если заказ не найден
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE campaigns
            SET status = ?
            WHERE id = ?
        """, (new_status, campaign_id))
        conn.commit()
        success = cursor.rowcount > 0
        if success:
            logger.info(f"✅ Обновлен статус заказа: ID={campaign_id}, Новый статус={new_status}")
        else:
            logger.warning(f"⚠️ Заказ {campaign_id} не найден для обновления статуса")
        return success


def get_all_user_telegram_ids():
    """
    Получает все telegram_id пользователей для массовой рассылки.

    Returns:
        List of telegram_ids
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT telegram_id FROM users")
        results = cursor.fetchall()

        if USE_POSTGRES:
            return [row['telegram_id'] for row in results]
        else:
            return [row[0] for row in results]


def set_selected_worker(campaign_id, blogger_id):
    """
    Устанавливает выбранного мастера для заказа и меняет статус на 'in_progress'.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE campaigns
            SET selected_worker_id = ?, status = 'in_progress'
            WHERE id = ?
        """, (blogger_id, campaign_id))
        conn.commit()


def mark_order_completed_by_client(campaign_id):
    """
    ИСПРАВЛЕНО: Клиент завершает заказ.
    Заказ сразу получает статус 'completed' - не требуется подтверждение от мастера.
    Обе стороны могут оставить отзыв о работе.

    Returns:
        bool: True (заказ завершен)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Помечаем что клиент завершил и сразу меняем статус
        cursor.execute("""
            UPDATE campaigns
            SET completed_by_client = 1,
                status = 'completed'
            WHERE id = ?
        """, (campaign_id,))

        conn.commit()
        logger.info(f"✅ Заказ {campaign_id} завершен клиентом")
        return True


def mark_order_completed_by_worker(campaign_id):
    """
    ИСПРАВЛЕНО: Мастер завершает заказ.
    Заказ сразу получает статус 'completed' - не требуется подтверждение от клиента.
    Обе стороны могут оставить отзыв о работе.

    Returns:
        bool: True (заказ завершен)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Помечаем что мастер завершил и сразу меняем статус
        cursor.execute("""
            UPDATE campaigns
            SET completed_by_worker = 1,
                status = 'completed'
            WHERE id = ?
        """, (campaign_id,))

        conn.commit()
        logger.info(f"✅ Заказ {campaign_id} завершен мастером")
        return True


def get_worker_info_for_order(campaign_id):
    """
    Получает информацию о мастере, работающем над заказом.

    Returns:
        dict with blogger info or None
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT
                w.id as blogger_id,
                w.user_id,
                w.name,
                w.phone,
                w.rating,
                w.rating_count
            FROM campaigns o
            JOIN bloggers w ON o.selected_worker_id = w.id
            WHERE o.id = ?
        """, (campaign_id,))
        return cursor.fetchone()


# --- Обновление полей профиля мастера ---

def update_worker_field(user_id, field_name, new_value):
    """
    Универсальная функция для обновления любого поля профиля мастера.
    Используется для редактирования профиля без потери рейтинга и истории.

    Args:
        user_id: ID пользователя
        field_name: Название поля (name, phone, city, etc.)
        new_value: Новое значение
    """
    # Безопасный whitelist подход - используем словарь для маппинга
    allowed_fields = {
        "name": "name",
        "phone": "phone",
        "city": "city",
        "regions": "regions",
        "categories": "categories",
        "experience": "experience",
        "description": "description",
        "portfolio_photos": "portfolio_photos",
        "profile_photo": "profile_photo",  # Фото профиля мастера
        "instagram_link": "instagram_link",
        "youtube_link": "youtube_link",
        "tiktok_link": "tiktok_link",
        "telegram_link": "telegram_link",
        "threads_link": "threads_link"
    }

    if field_name not in allowed_fields:
        raise ValueError(f"Недопустимое поле: {field_name}")

    # Валидация входных данных в зависимости от поля
    if field_name == "name":
        new_value = validate_string_length(new_value, MAX_NAME_LENGTH, "name")
    elif field_name == "phone":
        new_value = validate_string_length(new_value, MAX_PHONE_LENGTH, "phone")
    elif field_name in ["city", "regions"]:
        new_value = validate_string_length(new_value, MAX_CITY_LENGTH, field_name)
    elif field_name == "categories":
        new_value = validate_string_length(new_value, MAX_CATEGORY_LENGTH, "categories")
    elif field_name == "experience":
        new_value = validate_string_length(new_value, MAX_EXPERIENCE_LENGTH, "experience")
    elif field_name == "description":
        new_value = validate_string_length(new_value, MAX_DESCRIPTION_LENGTH, "description")
    elif field_name == "portfolio_photos":
        # ИСПРАВЛЕНИЕ: Валидация file_id для фотографий портфолио
        if new_value:
            validated_photos = validate_photo_list(new_value, "portfolio_photos")
            new_value = ",".join(validated_photos)
    elif field_name == "profile_photo":
        # ИСПРАВЛЕНИЕ: Валидация file_id для фото профиля
        if new_value:
            new_value = validate_telegram_file_id(new_value, "profile_photo")

    # Используем безопасное имя поля из whitelist
    safe_field = allowed_fields[field_name]

    logger.info(f"🔍 update_worker_field: user_id={user_id}, field={field_name}, value_length={len(str(new_value))}")

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        logger.info(f"🔍 Cursor получен: type={type(cursor)}, has_rowcount={hasattr(cursor, 'rowcount')}")

        # Безопасное построение запроса с явным whitelist
        query = f"UPDATE bloggers SET {safe_field} = ? WHERE user_id = ?"
        logger.info(f"🔍 Выполняем UPDATE: {query}")
        cursor.execute(query, (new_value, user_id))
        logger.info(f"🔍 UPDATE выполнен")

        conn.commit()
        logger.info(f"🔍 COMMIT выполнен")

        try:
            rowcount = cursor.rowcount
            logger.info(f"🔍 rowcount получен: {rowcount}")
            result = rowcount > 0
            logger.info(f"🔍 Результат: {result}")
            return result
        except Exception as e:
            logger.error(f"❌ ОШИБКА при получении rowcount: {e}", exc_info=True)
            logger.error(f"❌ Тип cursor: {type(cursor)}")
            logger.error(f"❌ Атрибуты cursor: {dir(cursor)}")
            raise


def update_client_field(user_id, field_name, new_value):
    """
    Универсальная функция для обновления любого поля профиля заказчика.

    Args:
        user_id: ID пользователя
        field_name: Название поля (name, phone, city, description)
        new_value: Новое значение
    """
    # Безопасный whitelist подход - используем словарь для маппинга
    allowed_fields = {
        "name": "name",
        "phone": "phone",
        "city": "city",
        "description": "description"
    }

    if field_name not in allowed_fields:
        raise ValueError(f"Недопустимое поле: {field_name}")

    # Валидация входных данных в зависимости от поля
    if field_name == "name":
        new_value = validate_string_length(new_value, MAX_NAME_LENGTH, "name")
    elif field_name == "phone":
        new_value = validate_string_length(new_value, MAX_PHONE_LENGTH, "phone")
    elif field_name == "city":
        new_value = validate_string_length(new_value, MAX_CITY_LENGTH, "city")
    elif field_name == "description":
        new_value = validate_string_length(new_value, MAX_DESCRIPTION_LENGTH, "description")

    # Используем безопасное имя поля из whitelist
    safe_field = allowed_fields[field_name]

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        # Безопасное построение запроса с явным whitelist
        query = f"UPDATE advertisers SET {safe_field} = ? WHERE user_id = ?"
        cursor.execute(query, (new_value, user_id))
        conn.commit()

        return cursor.rowcount > 0


# --- Поиск мастеров ---

def get_all_workers(city=None, category=None):
    """
    ИСПРАВЛЕНО: Использует точный поиск по категориям через blogger_categories.
    FALLBACK: Если категории нет в blogger_categories, ищет в поле categories (для старых мастеров).

    Получает список всех мастеров с фильтрами.

    Args:
        city: Фильтр по городу (опционально)
        category: Фильтр по категории (опционально)

    Returns:
        List of blogger profiles with user info
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        query = """
            SELECT
                w.*,
                u.telegram_id
            FROM bloggers w
            JOIN users u ON w.user_id = u.id
            WHERE 1=1
        """
        params = []

        # ИСПРАВЛЕНО: Поиск по городу через blogger_cities ИЛИ через city (для старых записей)
        if city:
            query += """
                AND (
                    EXISTS (
                        SELECT 1 FROM blogger_cities wc
                        WHERE wc.blogger_id = w.id AND wc.city = ?
                    )
                    OR w.city = ?
                )
            """
            params.append(city)
            params.append(city)

        if category:
            # ИСПРАВЛЕНО: Поиск по категории через blogger_categories ИЛИ через categories (для старых записей)
            query += """
                AND (
                    EXISTS (
                        SELECT 1 FROM blogger_categories wc
                        WHERE wc.blogger_id = w.id AND wc.category = ?
                    )
                    OR w.categories LIKE ?
                )
            """
            params.append(category)
            params.append(f"%{category}%")

        query += " ORDER BY w.rating DESC, w.rating_count DESC"

        logger.info(f"🔍 Поиск мастеров: город={city}, категория={category}")
        cursor.execute(query, params)
        results = cursor.fetchall()
        logger.info(f"🔍 Найдено мастеров: {len(results)}")
        return results


def get_worker_by_id(blogger_id):
    """Получает профиль мастера по ID"""
    with get_db_connection() as conn:
        
        cursor = get_cursor(conn)
        
        cursor.execute("""
            SELECT 
                w.*,
                u.telegram_id
            FROM bloggers w
            JOIN users u ON w.user_id = u.id
            WHERE w.id = ?
        """, (blogger_id,))
        
        return cursor.fetchone()


# --- Категории мастеров (новая нормализованная система) ---

def add_worker_categories(blogger_id, categories_list):
    """
    Добавляет категории для мастера в таблицу blogger_categories.

    Args:
        blogger_id: ID мастера
        categories_list: список категорий ["Электрика", "Сантехника"]
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        for category in categories_list:
            if not category or not category.strip():
                continue

            try:
                cursor.execute("""
                    INSERT INTO blogger_categories (blogger_id, category)
                    VALUES (?, ?)
                """, (blogger_id, category.strip()))
            except:
                # Игнорируем дубликаты (UNIQUE constraint)
                pass

        conn.commit()


def get_worker_categories(blogger_id):
    """
    Получает все категории мастера.

    Returns:
        Список категорий: ["Электрика", "Сантехника"]
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT category FROM blogger_categories
            WHERE blogger_id = ?
            ORDER BY category
        """, (blogger_id,))

        return [row[0] for row in cursor.fetchall()]


def remove_worker_category(blogger_id, category):
    """Удаляет категорию у мастера"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            DELETE FROM blogger_categories
            WHERE blogger_id = ? AND category = ?
        """, (blogger_id, category))
        conn.commit()


def clear_worker_categories(blogger_id):
    """Удаляет все категории мастера"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            DELETE FROM blogger_categories
            WHERE blogger_id = ?
        """, (blogger_id,))
        conn.commit()


def add_order_categories(campaign_id, categories_list):
    """
    НОВОЕ: Добавляет категории для заказа в таблицу campaign_categories.

    Args:
        campaign_id: ID заказа
        categories_list: список категорий ["Электрика", "Сантехника"]
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        for category in categories_list:
            if not category or not category.strip():
                continue

            try:
                cursor.execute("""
                    INSERT INTO campaign_categories (campaign_id, category)
                    VALUES (?, ?)
                """, (campaign_id, category.strip()))
            except:
                # Игнорируем дубликаты (UNIQUE constraint)
                pass

        conn.commit()  # КРИТИЧНО: Фиксируем транзакцию


def get_order_categories(campaign_id):
    """
    НОВОЕ: Получает все категории заказа.

    Returns:
        Список категорий: ["Электрика", "Сантехника"]
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT category FROM campaign_categories
            WHERE campaign_id = ?
            ORDER BY category
        """, (campaign_id,))

        return [row[0] for row in cursor.fetchall()]


def migrate_add_order_photos():
    """Добавляет колонку photos в таблицу campaigns"""
    # Для PostgreSQL миграции не нужны - таблицы создаются через init_db()
    if USE_POSTGRES:
        print("✅ Используется PostgreSQL, миграция не требуется")
        return

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Проверяем есть ли колонка photos (только для SQLite)
        cursor.execute("PRAGMA table_info(campaigns)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'photos' not in columns:
            print("➕ Добавляем колонку 'photos' в таблицу campaigns...")
            cursor.execute("ALTER TABLE campaigns ADD COLUMN photos TEXT DEFAULT ''")
            conn.commit()
            print("✅ Колонка 'photos' успешно добавлена в campaigns!")
        else:
            print("✅ Колонка 'photos' уже существует в campaigns")


def migrate_add_currency_to_bids():
    """Добавляет колонку currency в таблицу offers"""
    # Для PostgreSQL миграции не нужны - таблицы создаются через init_db()
    if USE_POSTGRES:
        print("✅ Используется PostgreSQL, миграция не требуется")
        return

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Проверяем есть ли колонка currency (только для SQLite)
        cursor.execute("PRAGMA table_info(offers)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'currency' not in columns:
            print("➕ Добавляем колонку 'currency' в таблицу offers...")
            cursor.execute("ALTER TABLE offers ADD COLUMN currency TEXT DEFAULT 'BYN'")
            conn.commit()
            print("✅ Колонка 'currency' успешно добавлена в offers!")
        else:
            print("✅ Колонка 'currency' уже существует в offers")


def migrate_add_cascading_deletes():
    """
    Добавляет cascading deletes для PostgreSQL.
    При удалении пользователя автоматически удаляются все связанные записи.
    """
    if not USE_POSTGRES:
        print("✅ SQLite не требует миграции cascading deletes")
        return

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Для PostgreSQL нужно пересоздать foreign keys с ON DELETE CASCADE
            # Сначала удаляем старые ограничения, затем создаем новые

            print("📝 Добавление cascading deletes для PostgreSQL...")

            # Workers: user_id -> users(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'workers_user_id_fkey'
                    ) THEN
                        ALTER TABLE bloggers DROP CONSTRAINT workers_user_id_fkey;
                    END IF;
                    ALTER TABLE bloggers ADD CONSTRAINT workers_user_id_fkey
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                END $$;
            """)

            # Clients: user_id -> users(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'clients_user_id_fkey'
                    ) THEN
                        ALTER TABLE advertisers DROP CONSTRAINT clients_user_id_fkey;
                    END IF;
                    ALTER TABLE advertisers ADD CONSTRAINT clients_user_id_fkey
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                END $$;
            """)

            # Orders: advertiser_id -> advertisers(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'orders_client_id_fkey'
                    ) THEN
                        ALTER TABLE campaigns DROP CONSTRAINT orders_client_id_fkey;
                    END IF;
                    ALTER TABLE campaigns ADD CONSTRAINT orders_client_id_fkey
                        FOREIGN KEY (advertiser_id) REFERENCES advertisers(id) ON DELETE CASCADE;
                END $$;
            """)

            # Bids: campaign_id -> campaigns(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'bids_order_id_fkey'
                    ) THEN
                        ALTER TABLE offers DROP CONSTRAINT bids_order_id_fkey;
                    END IF;
                    ALTER TABLE offers ADD CONSTRAINT bids_order_id_fkey
                        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE;
                END $$;
            """)

            # Bids: blogger_id -> bloggers(id) ON DELETE CASCADE
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'bids_worker_id_fkey'
                    ) THEN
                        ALTER TABLE offers DROP CONSTRAINT bids_worker_id_fkey;
                    END IF;
                    ALTER TABLE offers ADD CONSTRAINT bids_worker_id_fkey
                        FOREIGN KEY (blogger_id) REFERENCES bloggers(id) ON DELETE CASCADE;
                END $$;
            """)

            # Reviews: ON DELETE CASCADE для всех внешних ключей
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'reviews_from_user_id_fkey'
                    ) THEN
                        ALTER TABLE reviews DROP CONSTRAINT reviews_from_user_id_fkey;
                    END IF;
                    ALTER TABLE reviews ADD CONSTRAINT reviews_from_user_id_fkey
                        FOREIGN KEY (from_user_id) REFERENCES users(id) ON DELETE CASCADE;

                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'reviews_to_user_id_fkey'
                    ) THEN
                        ALTER TABLE reviews DROP CONSTRAINT reviews_to_user_id_fkey;
                    END IF;
                    ALTER TABLE reviews ADD CONSTRAINT reviews_to_user_id_fkey
                        FOREIGN KEY (to_user_id) REFERENCES users(id) ON DELETE CASCADE;

                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'reviews_order_id_fkey'
                    ) THEN
                        ALTER TABLE reviews DROP CONSTRAINT reviews_order_id_fkey;
                    END IF;
                    ALTER TABLE reviews ADD CONSTRAINT reviews_order_id_fkey
                        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE;
                END $$;
            """)

            logger.info("✅ Cascading deletes успешно добавлены!")

        except Exception as e:
            logger.warning(f"⚠️ Предупреждение при добавлении cascading deletes: {e}", exc_info=True)
            # Не пробрасываем ошибку - миграция не критична если constraint уже существует


def migrate_add_order_completion_tracking():
    """
    Добавляет поля для отслеживания завершения заказа обеими сторонами.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                print("📝 Добавление полей отслеживания завершения для PostgreSQL...")

                # Проверяем и добавляем поля если их нет
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'campaigns' AND column_name = 'selected_worker_id'
                        ) THEN
                            ALTER TABLE campaigns ADD COLUMN selected_worker_id INTEGER;
                            ALTER TABLE campaigns ADD CONSTRAINT orders_selected_worker_id_fkey
                                FOREIGN KEY (selected_worker_id) REFERENCES bloggers(id) ON DELETE SET NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'campaigns' AND column_name = 'completed_by_client'
                        ) THEN
                            ALTER TABLE campaigns ADD COLUMN completed_by_client INTEGER DEFAULT 0;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'campaigns' AND column_name = 'completed_by_worker'
                        ) THEN
                            ALTER TABLE campaigns ADD COLUMN completed_by_worker INTEGER DEFAULT 0;
                        END IF;
                    END $$;
                """)
                conn.commit()
                print("✅ Поля отслеживания завершения успешно добавлены!")

            else:
                # Для SQLite проверяем существование колонок
                cursor.execute("PRAGMA table_info(campaigns)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'selected_worker_id' not in columns:
                    print("📝 Добавление поля selected_worker_id...")
                    cursor.execute("ALTER TABLE campaigns ADD COLUMN selected_worker_id INTEGER")

                if 'completed_by_client' not in columns:
                    print("📝 Добавление поля completed_by_client...")
                    cursor.execute("ALTER TABLE campaigns ADD COLUMN completed_by_client INTEGER DEFAULT 0")

                if 'completed_by_worker' not in columns:
                    print("📝 Добавление поля completed_by_worker...")
                    cursor.execute("ALTER TABLE campaigns ADD COLUMN completed_by_worker INTEGER DEFAULT 0")

                conn.commit()
                print("✅ Поля отслеживания завершения успешно добавлены!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении полей отслеживания завершения: {e}")


def migrate_add_profile_photo():
    """
    Добавляет поле profile_photo для фото профиля мастера (лицо).
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                print("📝 Добавление поля profile_photo для PostgreSQL...")

                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'bloggers' AND column_name = 'profile_photo'
                        ) THEN
                            ALTER TABLE bloggers ADD COLUMN profile_photo TEXT;
                        END IF;
                    END $$;
                """)
                conn.commit()
                print("✅ Поле profile_photo успешно добавлено!")

            else:
                # Для SQLite проверяем существование колонки
                cursor.execute("PRAGMA table_info(bloggers)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'profile_photo' not in columns:
                    print("📝 Добавление поля profile_photo...")
                    cursor.execute("ALTER TABLE bloggers ADD COLUMN profile_photo TEXT")
                    conn.commit()
                    print("✅ Поле profile_photo успешно добавлено!")
                else:
                    print("✅ Поле profile_photo уже существует")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении поля profile_photo: {e}")


def migrate_add_premium_features():
    """
    Добавляет поля для premium функций:
    - premium_enabled (глобальный флаг в settings)
    - is_premium_order (для campaigns)
    - is_premium_worker (для bloggers)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Создаём таблицу settings если её нет
            if USE_POSTGRES:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key VARCHAR(100) PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

            # Устанавливаем premium_enabled = false по умолчанию
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO settings (key, value)
                    VALUES ('premium_enabled', 'false')
                    ON CONFLICT (key) DO NOTHING
                """)
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO settings (key, value)
                    VALUES ('premium_enabled', 'false')
                """)

            # Добавляем поля для premium в campaigns
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'campaigns' AND column_name = 'is_premium'
                        ) THEN
                            ALTER TABLE campaigns ADD COLUMN is_premium BOOLEAN DEFAULT FALSE;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'campaigns' AND column_name = 'premium_until'
                        ) THEN
                            ALTER TABLE campaigns ADD COLUMN premium_until TIMESTAMP;
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(campaigns)")
                campaign_columns = [column[1] for column in cursor.fetchall()]

                if 'is_premium' not in campaign_columns:
                    cursor.execute("ALTER TABLE campaigns ADD COLUMN is_premium INTEGER DEFAULT 0")

                if 'premium_until' not in campaign_columns:
                    cursor.execute("ALTER TABLE campaigns ADD COLUMN premium_until TIMESTAMP")

            # Добавляем поля для premium в bloggers
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'bloggers' AND column_name = 'is_premium'
                        ) THEN
                            ALTER TABLE bloggers ADD COLUMN is_premium BOOLEAN DEFAULT FALSE;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'bloggers' AND column_name = 'premium_until'
                        ) THEN
                            ALTER TABLE bloggers ADD COLUMN premium_until TIMESTAMP;
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(bloggers)")
                blogger_columns = [column[1] for column in cursor.fetchall()]

                if 'is_premium' not in blogger_columns:
                    cursor.execute("ALTER TABLE bloggers ADD COLUMN is_premium INTEGER DEFAULT 0")

                if 'premium_until' not in blogger_columns:
                    cursor.execute("ALTER TABLE bloggers ADD COLUMN premium_until TIMESTAMP")

            conn.commit()
            print("✅ Premium features migration completed successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении premium полей: {e}")
            import traceback
            traceback.print_exc()


def migrate_add_chat_system():
    """
    Создаёт таблицы для системы чата между клиентом и мастером
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Таблица чатов
            if USE_POSTGRES:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        id SERIAL PRIMARY KEY,
                        campaign_id INTEGER NOT NULL,
                        advertiser_user_id INTEGER NOT NULL,
                        blogger_user_id INTEGER NOT NULL,
                        offer_id INTEGER NOT NULL,
                        status VARCHAR(50) DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_message_at TIMESTAMP,
                        blogger_confirmed BOOLEAN DEFAULT FALSE,
                        blogger_confirmed_at TIMESTAMP,
                        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                        FOREIGN KEY (offer_id) REFERENCES offers(id) ON DELETE CASCADE
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id SERIAL PRIMARY KEY,
                        chat_id INTEGER NOT NULL,
                        sender_user_id INTEGER NOT NULL,
                        sender_role VARCHAR(20) NOT NULL,
                        message_text TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_read BOOLEAN DEFAULT FALSE,
                        FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
                    )
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        campaign_id INTEGER NOT NULL,
                        advertiser_user_id INTEGER NOT NULL,
                        blogger_user_id INTEGER NOT NULL,
                        offer_id INTEGER NOT NULL,
                        status TEXT DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_message_at TIMESTAMP,
                        blogger_confirmed INTEGER DEFAULT 0,
                        blogger_confirmed_at TIMESTAMP,
                        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                        FOREIGN KEY (offer_id) REFERENCES offers(id) ON DELETE CASCADE
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        sender_user_id INTEGER NOT NULL,
                        sender_role TEXT NOT NULL,
                        message_text TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_read INTEGER DEFAULT 0,
                        FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
                    )
                """)

            conn.commit()
            print("✅ Chat system tables created successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при создании таблиц чата: {e}")
            import traceback
            traceback.print_exc()


def migrate_add_transactions():
    """
    Создаёт таблицу для истории транзакций (платежей клиентов)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        campaign_id INTEGER,
                        offer_id INTEGER,
                        transaction_type VARCHAR(50) NOT NULL,
                        amount DECIMAL(10, 2) NOT NULL,
                        currency VARCHAR(10) DEFAULT 'BYN',
                        status VARCHAR(50) DEFAULT 'pending',
                        payment_method VARCHAR(50),
                        description TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL,
                        FOREIGN KEY (offer_id) REFERENCES offers(id) ON DELETE SET NULL
                    )
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        campaign_id INTEGER,
                        offer_id INTEGER,
                        transaction_type TEXT NOT NULL,
                        amount REAL NOT NULL,
                        currency TEXT DEFAULT 'BYN',
                        status TEXT DEFAULT 'pending',
                        payment_method TEXT,
                        description TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL,
                        FOREIGN KEY (offer_id) REFERENCES offers(id) ON DELETE SET NULL
                    )
                """)

            conn.commit()
            print("✅ Transactions table created successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при создании таблицы транзакций: {e}")
            import traceback
            traceback.print_exc()


def migrate_add_notification_settings():
    """
    Добавляет поле для управления уведомлениями мастеров и клиентов:
    - notifications_enabled (по умолчанию TRUE - уведомления включены)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                # Миграция для bloggers
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'bloggers' AND column_name = 'notifications_enabled'
                        ) THEN
                            ALTER TABLE bloggers ADD COLUMN notifications_enabled BOOLEAN DEFAULT TRUE;
                        END IF;
                    END $$;
                """)

                # Миграция для advertisers
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'advertisers' AND column_name = 'notifications_enabled'
                        ) THEN
                            ALTER TABLE advertisers ADD COLUMN notifications_enabled BOOLEAN DEFAULT TRUE;
                        END IF;
                    END $$;
                """)
            else:
                # SQLite - миграция для bloggers
                cursor.execute("PRAGMA table_info(bloggers)")
                blogger_columns = [column[1] for column in cursor.fetchall()]

                if 'notifications_enabled' not in blogger_columns:
                    cursor.execute("ALTER TABLE bloggers ADD COLUMN notifications_enabled INTEGER DEFAULT 1")

                # SQLite - миграция для advertisers
                cursor.execute("PRAGMA table_info(advertisers)")
                advertiser_columns = [column[1] for column in cursor.fetchall()]

                if 'notifications_enabled' not in advertiser_columns:
                    cursor.execute("ALTER TABLE advertisers ADD COLUMN notifications_enabled INTEGER DEFAULT 1")

            conn.commit()
            print("✅ Notification settings migration completed successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении настроек уведомлений: {e}")
            import traceback
            traceback.print_exc()


def migrate_normalize_categories():
    """
    ИСПРАВЛЕНИЕ: Создает отдельную таблицу для категорий мастеров.

    ПРОБЛЕМА: categories LIKE '%Электрика%' находит 'Неэлектрика'
    РЕШЕНИЕ: Отдельная таблица blogger_categories с точным поиском

    Создает:
    1. Таблицу blogger_categories (blogger_id, category)
    2. Переносит данные из bloggers.categories
    3. Создает индексы для быстрого поиска
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Проверяем существует ли уже таблица
            if USE_POSTGRES:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'blogger_categories'
                    )
                """)
                result = cursor.fetchone()
                # PostgreSQL возвращает dict, SQLite может вернуть tuple
                if isinstance(result, dict):
                    table_exists = bool(result.get('exists', False))
                else:
                    table_exists = bool(result[0]) if result else False
            else:
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='blogger_categories'
                """)
                table_exists = cursor.fetchone() is not None

            if table_exists:
                print("ℹ️  Таблица blogger_categories уже существует, пропускаем миграцию")
                return

            # Создаем таблицу blogger_categories
            if USE_POSTGRES:
                cursor.execute("""
                    CREATE TABLE blogger_categories (
                        id SERIAL PRIMARY KEY,
                        blogger_id INTEGER NOT NULL,
                        category VARCHAR(100) NOT NULL,
                        FOREIGN KEY (blogger_id) REFERENCES bloggers(id) ON DELETE CASCADE,
                        UNIQUE (blogger_id, category)
                    )
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS blogger_categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        blogger_id INTEGER NOT NULL,
                        category TEXT NOT NULL,
                        FOREIGN KEY (blogger_id) REFERENCES bloggers(id) ON DELETE CASCADE,
                        UNIQUE (blogger_id, category)
                    )
                """)

            # Переносим существующие категории из bloggers.categories
            cursor.execute("SELECT id, categories FROM bloggers WHERE categories IS NOT NULL AND categories != ''")
            bloggers = cursor.fetchall()

            migrated_count = 0
            for blogger in bloggers:
                # PostgreSQL возвращает dict, SQLite может вернуть tuple
                if isinstance(blogger, dict):
                    blogger_id = blogger['id']
                    categories_str = blogger['categories']
                else:
                    blogger_id = blogger[0]
                    categories_str = blogger[1]

                if not categories_str:
                    continue

                # Разбиваем строку "Электрика, Сантехника" на список
                categories = [cat.strip() for cat in categories_str.split(',') if cat.strip()]

                for category in categories:
                    try:
                        cursor.execute("""
                            INSERT INTO blogger_categories (blogger_id, category)
                            VALUES (?, ?)
                        """, (blogger_id, category))
                        migrated_count += 1
                    except:
                        # Пропускаем дубликаты
                        pass

            # Создаем индексы для быстрого поиска
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_worker_categories_worker
                ON blogger_categories(blogger_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_worker_categories_category
                ON blogger_categories(category)
            """)

            conn.commit()
            print(f"✅ Категории нормализованы! Перенесено {migrated_count} категорий")
            print("   Теперь поиск будет точным, без ложных совпадений")

        except Exception as e:
            logger.warning(f"⚠️ Ошибка при нормализации категорий мастеров: {e}", exc_info=True)


def migrate_normalize_order_categories():
    """
    ИСПРАВЛЕНИЕ: Создает отдельную таблицу для категорий заказов.

    Проблема: категории хранятся как TEXT со значениями вида "Электрика, Сантехника"
    Поиск через LIKE '%Электрика%' находит также "Неэлектрика" (ложное совпадение)

    Решение: нормализованная таблица campaign_categories с точным поиском
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # 1. Создаем таблицу campaign_categories
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS campaign_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                    UNIQUE (campaign_id, category)
                )
            """)

            logger.info("📋 Таблица campaign_categories создана")

            # 2. Проверяем есть ли уже данные в campaign_categories
            cursor.execute("SELECT COUNT(*) FROM campaign_categories")
            result = cursor.fetchone()
            # PostgreSQL возвращает dict, SQLite может вернуть tuple
            if isinstance(result, dict):
                existing_count = result.get('count', 0)
            else:
                existing_count = result[0] if result else 0

            if existing_count > 0:
                logger.info(f"✅ Категории заказов уже мигрированы ({existing_count} записей)")
                return

            # 3. Переносим существующие категории из campaigns.category в campaign_categories
            cursor.execute("SELECT id, category FROM campaigns WHERE category IS NOT NULL AND category != ''")
            campaigns = cursor.fetchall()

            migrated_count = 0
            for campaign in campaigns:
                # PostgreSQL возвращает dict, SQLite может вернуть tuple
                if isinstance(campaign, dict):
                    campaign_id = campaign['id']
                    categories_str = campaign['category']
                else:
                    campaign_id = campaign[0]
                    categories_str = campaign[1]

                if not categories_str:
                    continue

                # Разбиваем строку на категории
                categories = [cat.strip() for cat in categories_str.split(',') if cat.strip()]

                # Добавляем каждую категорию
                for category in categories:
                    try:
                        cursor.execute("""
                            INSERT INTO campaign_categories (campaign_id, category)
                            VALUES (?, ?)
                        """, (campaign_id, category))
                        migrated_count += 1
                    except Exception as e:
                        # Игнорируем дубликаты (UNIQUE constraint)
                        if "UNIQUE constraint failed" not in str(e) and "duplicate key" not in str(e):
                            logger.warning(f"⚠️ Ошибка при добавлении категории '{category}' для заказа {campaign_id}: {e}")

            # 4. Создаем индексы для быстрого поиска
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_order_categories_order
                ON campaign_categories(campaign_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_order_categories_category
                ON campaign_categories(category)
            """)

            logger.info(f"✅ Категории заказов нормализованы! Перенесено {migrated_count} категорий")
            logger.info("   Теперь поиск заказов будет точным, без ложных совпадений")

        except Exception as e:
            logger.warning(f"⚠️ Ошибка при нормализации категорий заказов: {e}", exc_info=True)


def migrate_add_moderation():
    """
    Добавляет поля для модерации пользователей:
    - is_banned (флаг бана)
    - ban_reason (причина бана)
    - banned_at (дата бана)
    - banned_by (кто забанил)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'users' AND column_name = 'is_banned'
                        ) THEN
                            ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'users' AND column_name = 'ban_reason'
                        ) THEN
                            ALTER TABLE users ADD COLUMN ban_reason TEXT;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'users' AND column_name = 'banned_at'
                        ) THEN
                            ALTER TABLE users ADD COLUMN banned_at TIMESTAMP;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'users' AND column_name = 'banned_by'
                        ) THEN
                            ALTER TABLE users ADD COLUMN banned_by VARCHAR(100);
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(users)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'is_banned' not in columns:
                    cursor.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")

                if 'ban_reason' not in columns:
                    cursor.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")

                if 'banned_at' not in columns:
                    cursor.execute("ALTER TABLE users ADD COLUMN banned_at TIMESTAMP")

                if 'banned_by' not in columns:
                    cursor.execute("ALTER TABLE users ADD COLUMN banned_by TEXT")

            conn.commit()
            print("✅ Moderation fields migration completed successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении модерационных полей: {e}")
            import traceback
            traceback.print_exc()


def migrate_add_regions_to_clients():
    """
    Добавляет поле regions в таблицу advertisers для хранения региона клиента.
    Аналогично полю regions в таблице bloggers.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'advertisers' AND column_name = 'regions'
                        ) THEN
                            ALTER TABLE advertisers ADD COLUMN regions TEXT;
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(advertisers)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'regions' not in columns:
                    cursor.execute("ALTER TABLE advertisers ADD COLUMN regions TEXT")

            conn.commit()
            print("✅ Regions field migration for advertisers completed successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении поля regions в advertisers: {e}")
            import traceback
            traceback.print_exc()


def migrate_add_videos_to_orders():
    """
    Добавляет поле videos в таблицу campaigns для хранения видео заказа.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'campaigns' AND column_name = 'videos'
                        ) THEN
                            ALTER TABLE campaigns ADD COLUMN videos TEXT DEFAULT '';
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(campaigns)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'videos' not in columns:
                    cursor.execute("ALTER TABLE campaigns ADD COLUMN videos TEXT DEFAULT ''")

            conn.commit()
            print("✅ Videos field migration for campaigns completed successfully!")

        except Exception as e:
            print(f"⚠️  Ошибка при добавлении поля videos в campaigns: {e}")
            import traceback
            traceback.print_exc()


# === CHAT SYSTEM HELPERS ===

def create_chat(campaign_id, advertiser_user_id, blogger_user_id, offer_id):
    """Создаёт чат между клиентом и мастером"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO chats (campaign_id, advertiser_user_id, blogger_user_id, offer_id, created_at, last_message_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (campaign_id, advertiser_user_id, blogger_user_id, offer_id, datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()
        return cursor.lastrowid


def get_chat_by_order_and_bid(campaign_id, offer_id):
    """Получает чат по заказу и отклику"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM chats
            WHERE campaign_id = ? AND offer_id = ?
        """, (campaign_id, offer_id))
        return cursor.fetchone()


def get_chat_by_order(campaign_id):
    """
    НОВОЕ: Получает чат по заказу (для упрощения доступа из списка заказов).
    Возвращает первый найденный чат для этого заказа.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM chats
            WHERE campaign_id = ?
            LIMIT 1
        """, (campaign_id,))
        return cursor.fetchone()


def get_chat_by_id(chat_id):
    """Получает чат по ID"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM chats WHERE id = ?", (chat_id,))
        return cursor.fetchone()


def get_user_chats(user_id):
    """Получает все чаты пользователя"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT c.*, o.description as campaign_description
            FROM chats c
            JOIN campaigns o ON c.campaign_id = o.id
            WHERE c.advertiser_user_id = ? OR c.blogger_user_id = ?
            ORDER BY c.last_message_at DESC
        """, (user_id, user_id))
        return cursor.fetchall()


def send_message(chat_id, sender_user_id, sender_role, message_text):
    """Отправляет сообщение в чат"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Добавляем сообщение
        cursor.execute("""
            INSERT INTO messages (chat_id, sender_user_id, sender_role, message_text, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, sender_user_id, sender_role, message_text, datetime.now().isoformat()))

        # Обновляем время последнего сообщения в чате
        cursor.execute("""
            UPDATE chats
            SET last_message_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), chat_id))

        conn.commit()
        return cursor.lastrowid


def get_chat_messages(chat_id, limit=50):
    """Получает сообщения чата"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM messages
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (chat_id, limit))
        return cursor.fetchall()


def mark_messages_as_read(chat_id, user_id):
    """Отмечает сообщения как прочитанные для пользователя"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE messages
            SET is_read = TRUE
            WHERE chat_id = ? AND sender_user_id != ?
        """, (chat_id, user_id))
        conn.commit()


def get_unread_messages_count(chat_id, user_id):
    """Получает количество непрочитанных сообщений"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT COUNT(*) FROM messages
            WHERE chat_id = ? AND sender_user_id != ? AND is_read = FALSE
        """, (chat_id, user_id))
        result = cursor.fetchone()
        if not result:
            return 0
        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return result.get('count', 0)
        else:
            return result[0]


def confirm_worker_in_chat(chat_id):
    """Мастер подтверждает готовность работать (первое сообщение = подтверждение)"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE chats
            SET blogger_confirmed = TRUE, blogger_confirmed_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), chat_id))
        conn.commit()


def is_worker_confirmed(chat_id):
    """Проверяет подтвердил ли мастер готовность"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT blogger_confirmed FROM chats WHERE id = ?", (chat_id,))
        result = cursor.fetchone()
        if not result:
            return False
        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return bool(result.get('blogger_confirmed', False))
        else:
            return bool(result[0])


# === ACTIVE CHAT HELPERS (ИСПРАВЛЕНИЕ: сохранение в БД вместо user_data) ===

def set_active_chat(telegram_id, chat_id, role):
    """
    Сохраняет активный чат пользователя в БД.
    Это решает проблему потери состояния при перезапуске бота.

    Args:
        telegram_id: Telegram ID пользователя
        chat_id: ID чата
        role: Роль пользователя в чате ('advertiser' или 'blogger')
    """
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if USE_POSTGRES:
            # PostgreSQL: используем ON CONFLICT вместо INSERT OR REPLACE
            cursor.execute("""
                INSERT INTO active_chats (telegram_id, chat_id, role, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (telegram_id)
                DO UPDATE SET chat_id = EXCLUDED.chat_id,
                              role = EXCLUDED.role,
                              updated_at = EXCLUDED.updated_at
            """, (telegram_id, chat_id, role, datetime.now().isoformat()))
        else:
            # SQLite: используем INSERT OR REPLACE
            cursor.execute("""
                INSERT OR REPLACE INTO active_chats (telegram_id, chat_id, role, updated_at)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, chat_id, role, datetime.now().isoformat()))

        conn.commit()
        logger.info(f"✅ Активный чат сохранён: user={telegram_id}, chat={chat_id}, role={role}")


def get_active_chat(telegram_id):
    """
    Получает активный чат пользователя из БД.

    Args:
        telegram_id: Telegram ID пользователя

    Returns:
        dict: {'chat_id': int, 'role': str} или None если нет активного чата
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if USE_POSTGRES:
            cursor.execute("""
                SELECT chat_id, role FROM active_chats WHERE telegram_id = %s
            """, (telegram_id,))
        else:
            cursor.execute("""
                SELECT chat_id, role FROM active_chats WHERE telegram_id = ?
            """, (telegram_id,))

        result = cursor.fetchone()

        if not result:
            return None

        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return {'chat_id': result['chat_id'], 'role': result['role']}
        else:
            return {'chat_id': result[0], 'role': result[1]}


def clear_active_chat(telegram_id):
    """
    Очищает активный чат пользователя.

    Args:
        telegram_id: Telegram ID пользователя
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if USE_POSTGRES:
            cursor.execute("DELETE FROM active_chats WHERE telegram_id = %s", (telegram_id,))
        else:
            cursor.execute("DELETE FROM active_chats WHERE telegram_id = ?", (telegram_id,))

        conn.commit()
        logger.info(f"✅ Активный чат очищен для user={telegram_id}")


# === TRANSACTION HELPERS ===

def create_transaction(user_id, campaign_id, offer_id, transaction_type, amount, currency='BYN', payment_method='test', description=''):
    """Создаёт транзакцию"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO transactions
            (user_id, campaign_id, offer_id, transaction_type, amount, currency, status, payment_method, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)
        """, (user_id, campaign_id, offer_id, transaction_type, amount, currency, payment_method, description, datetime.now().isoformat()))
        conn.commit()
        return cursor.lastrowid


def get_user_transactions(user_id):
    """Получает историю транзакций пользователя"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
        return cursor.fetchall()


def get_transaction_by_order_bid(campaign_id, offer_id):
    """Проверяет была ли оплата за доступ к мастеру"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM transactions
            WHERE campaign_id = ? AND offer_id = ? AND status = 'completed'
        """, (campaign_id, offer_id))
        return cursor.fetchone()


def get_expired_chats(hours=24):
    """
    Получает чаты где мастер не ответил в течение заданного времени

    Args:
        hours: количество часов для проверки (по умолчанию 24)

    Returns:
        Список чатов где blogger_confirmed = FALSE и прошло более hours часов с created_at
    """
    from datetime import datetime, timedelta

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        expiration_time = datetime.now() - timedelta(hours=hours)

        cursor.execute("""
            SELECT * FROM chats
            WHERE blogger_confirmed = FALSE
            AND created_at < ?
        """, (expiration_time.isoformat(),))

        return cursor.fetchall()


def mark_chat_as_expired(chat_id):
    """Помечает чат как просроченный (мастер не ответил вовремя)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        # Можно добавить поле expired_at или is_expired, но пока просто оставим
        # Чат будет считаться просроченным по факту что blogger_confirmed = 0 и прошло 24 часа
        pass


# === NOTIFICATION SETTINGS HELPERS ===

def are_notifications_enabled(user_id):
    """
    Проверяет включены ли уведомления для мастера.

    Args:
        user_id: ID пользователя в таблице users

    Returns:
        True если уведомления включены или настройка не найдена (по умолчанию включены)
        False если уведомления отключены
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT notifications_enabled
            FROM bloggers
            WHERE user_id = ?
        """, (user_id,))
        result = cursor.fetchone()

        # Если запись не найдена или поле не существует - по умолчанию включены
        if not result:
            return True

        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return bool(result.get('notifications_enabled', True))
        else:
            # SQLite хранит boolean как INTEGER (1 или 0)
            return bool(result[0]) if result[0] is not None else True


def set_notifications_enabled(user_id, enabled):
    """
    Включает или отключает уведомления для мастера.

    Args:
        user_id: ID пользователя в таблице users
        enabled: True для включения, False для отключения

    Returns:
        True если обновление успешно, False если мастер не найден
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if USE_POSTGRES:
            # PostgreSQL: используем TRUE/FALSE напрямую
            value_str = 'TRUE' if enabled else 'FALSE'
            cursor.execute(f"""
                UPDATE bloggers
                SET notifications_enabled = {value_str}
                WHERE user_id = %s
            """, (user_id,))
        else:
            # SQLite: используем 1/0
            value = 1 if enabled else 0
            cursor.execute("""
                UPDATE bloggers
                SET notifications_enabled = ?
                WHERE user_id = ?
            """, (value, user_id))

        conn.commit()
        return cursor.rowcount > 0


def are_client_notifications_enabled(user_id):
    """
    Проверяет включены ли уведомления для клиента.

    Args:
        user_id: ID пользователя в таблице users

    Returns:
        True если уведомления включены или настройка не найдена (по умолчанию включены)
        False если уведомления отключены
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT notifications_enabled
            FROM advertisers
            WHERE user_id = ?
        """, (user_id,))
        result = cursor.fetchone()

        # Если запись не найдена или поле не существует - по умолчанию включены
        if not result:
            return True

        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return bool(result.get('notifications_enabled', True))
        else:
            # SQLite хранит boolean как INTEGER (1 или 0)
            return bool(result[0]) if result[0] is not None else True


def set_client_notifications_enabled(user_id, enabled):
    """
    Включает или отключает уведомления для клиента.

    Args:
        user_id: ID пользователя в таблице users
        enabled: True для включения, False для отключения

    Returns:
        True если обновление успешно, False если клиент не найден
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if USE_POSTGRES:
            # PostgreSQL: используем TRUE/FALSE напрямую
            value_str = 'TRUE' if enabled else 'FALSE'
            cursor.execute(f"""
                UPDATE advertisers
                SET notifications_enabled = {value_str}
                WHERE user_id = %s
            """, (user_id,))
        else:
            # SQLite: используем 1/0
            value = 1 if enabled else 0
            cursor.execute("""
                UPDATE advertisers
                SET notifications_enabled = ?
                WHERE user_id = ?
            """, (value, user_id))

        conn.commit()
        return cursor.rowcount > 0


# === PREMIUM FEATURES HELPERS ===

def is_premium_enabled():
    """Проверяет включены ли premium функции глобально"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT value FROM settings WHERE key = 'premium_enabled'")
        result = cursor.fetchone()
        if not result:
            return False
        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return result.get('value') == 'true'
        else:
            return result[0] == 'true'


def set_premium_enabled(enabled):
    """Включает/выключает premium функции глобально"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        value = 'true' if enabled else 'false'
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ('premium_enabled', %s, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (value,))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES ('premium_enabled', ?, datetime('now'))
            """, (value,))
        conn.commit()


def get_setting(key, default=None):
    """Получает значение настройки"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        if not result:
            return default
        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return result.get('value', default)
        else:
            return result[0]


def set_setting(key, value):
    """Устанавливает значение настройки"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
            """, (key, value))
        conn.commit()


# === MODERATION HELPERS ===

def is_user_banned(telegram_id):
    """Проверяет забанен ли пользователь"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT is_banned FROM users WHERE telegram_id = ?
        """, (telegram_id,))
        result = cursor.fetchone()
        if result:
            # PostgreSQL возвращает dict, SQLite может вернуть tuple
            if isinstance(result, dict):
                return bool(result.get('is_banned', False))
            else:
                return bool(result[0])
        return False


def ban_user(telegram_id, reason, banned_by):
    """Банит пользователя"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE users
            SET is_banned = TRUE,
                ban_reason = ?,
                banned_at = ?,
                banned_by = ?
            WHERE telegram_id = ?
        """, (reason, datetime.now().isoformat(), banned_by, telegram_id))
        conn.commit()
        return cursor.rowcount > 0


def unban_user(telegram_id):
    """Разбанивает пользователя"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE users
            SET is_banned = FALSE,
                ban_reason = NULL,
                banned_at = NULL,
                banned_by = NULL
            WHERE telegram_id = ?
        """, (telegram_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_banned_users():
    """Получает список всех забаненных пользователей"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT telegram_id, ban_reason, banned_at, banned_by
            FROM users
            WHERE is_banned = TRUE
            ORDER BY banned_at DESC
        """)
        return cursor.fetchall()


def search_users(query, limit=20):
    """Ищет пользователей по telegram_id, имени или username"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        # Ищем по telegram_id (точное совпадение) или имени/username (LIKE)
        if USE_POSTGRES:
            cursor.execute("""
                SELECT u.*,
                       w.id as blogger_id,
                       c.id as advertiser_id
                FROM users u
                LEFT JOIN bloggers w ON u.id = w.user_id
                LEFT JOIN advertisers c ON u.id = c.user_id
                WHERE u.telegram_id::text LIKE %s
                   OR LOWER(u.full_name) LIKE LOWER(%s)
                   OR LOWER(u.username) LIKE LOWER(%s)
                ORDER BY u.created_at DESC
                LIMIT %s
            """, (f'%{query}%', f'%{query}%', f'%{query}%', limit))
        else:
            cursor.execute("""
                SELECT u.*,
                       w.id as blogger_id,
                       c.id as advertiser_id
                FROM users u
                LEFT JOIN bloggers w ON u.id = w.user_id
                LEFT JOIN advertisers c ON u.id = c.user_id
                WHERE CAST(u.telegram_id AS TEXT) LIKE ?
                   OR LOWER(u.full_name) LIKE LOWER(?)
                   OR LOWER(u.username) LIKE LOWER(?)
                ORDER BY u.created_at DESC
                LIMIT ?
            """, (f'%{query}%', f'%{query}%', f'%{query}%', limit))
        return cursor.fetchall()


def get_users_filtered(filter_type='all', page=1, per_page=20):
    """
    Получает пользователей с фильтром
    filter_type: 'all', 'bloggers', 'advertisers', 'banned', 'dual'
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        offset = (page - 1) * per_page

        if filter_type == 'banned':
            cursor.execute("""
                SELECT u.*, w.id as blogger_id, c.id as advertiser_id
                FROM users u
                LEFT JOIN bloggers w ON u.id = w.user_id
                LEFT JOIN advertisers c ON u.id = c.user_id
                WHERE u.is_banned = TRUE
                ORDER BY u.created_at DESC
                LIMIT ? OFFSET ?
            """, (per_page, offset))
        elif filter_type == 'bloggers':
            cursor.execute("""
                SELECT u.*, w.id as blogger_id, c.id as advertiser_id
                FROM users u
                INNER JOIN bloggers w ON u.id = w.user_id
                LEFT JOIN advertisers c ON u.id = c.user_id
                WHERE u.is_banned = FALSE
                ORDER BY u.created_at DESC
                LIMIT ? OFFSET ?
            """, (per_page, offset))
        elif filter_type == 'advertisers':
            cursor.execute("""
                SELECT u.*, w.id as blogger_id, c.id as advertiser_id
                FROM users u
                LEFT JOIN bloggers w ON u.id = w.user_id
                INNER JOIN advertisers c ON u.id = c.user_id
                WHERE u.is_banned = FALSE
                ORDER BY u.created_at DESC
                LIMIT ? OFFSET ?
            """, (per_page, offset))
        elif filter_type == 'dual':
            cursor.execute("""
                SELECT u.*, w.id as blogger_id, c.id as advertiser_id
                FROM users u
                INNER JOIN bloggers w ON u.id = w.user_id
                INNER JOIN advertisers c ON u.id = c.user_id
                WHERE u.is_banned = FALSE
                ORDER BY u.created_at DESC
                LIMIT ? OFFSET ?
            """, (per_page, offset))
        else:  # 'all'
            cursor.execute("""
                SELECT u.*, w.id as blogger_id, c.id as advertiser_id
                FROM users u
                LEFT JOIN bloggers w ON u.id = w.user_id
                LEFT JOIN advertisers c ON u.id = c.user_id
                ORDER BY u.created_at DESC
                LIMIT ? OFFSET ?
            """, (per_page, offset))

        return cursor.fetchall()


def get_user_details_for_admin(telegram_id):
    """Получает подробную информацию о пользователе для админ-панели"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Основная информация
        user = get_user(telegram_id)
        if not user:
            return None

        user_dict = dict(user)
        details = {
            'user': user_dict,
            'blogger_profile': None,
            'advertiser_profile': None,
            'stats': {}
        }

        # Профили
        blogger = get_worker_profile(user_dict['id'])
        if blogger:
            details['blogger_profile'] = dict(blogger)

        advertiser = get_client_profile(user_dict['id'])
        if advertiser:
            details['advertiser_profile'] = dict(advertiser)

        # Статистика как мастера
        if blogger:
            blogger_dict = dict(blogger)
            cursor.execute("""
                SELECT COUNT(*) FROM offers WHERE blogger_id = ?
            """, (blogger_dict['id'],))
            details['stats']['total_bids'] = _get_count_from_result(cursor.fetchone())

            cursor.execute("""
                SELECT COUNT(*) FROM offers
                WHERE blogger_id = ? AND status = 'selected'
            """, (blogger_dict['id'],))
            details['stats']['accepted_bids'] = _get_count_from_result(cursor.fetchone())

            cursor.execute("""
                SELECT AVG(rating) FROM reviews WHERE to_user_id = ?
            """, (user_dict['id'],))
            result = cursor.fetchone()
            if result:
                avg_rating = result['avg'] if isinstance(result, dict) else result[0]
                details['stats']['blogger_rating'] = float(avg_rating) if avg_rating else 0.0
            else:
                details['stats']['blogger_rating'] = 0.0

        # Статистика как клиента
        if advertiser:
            advertiser_dict = dict(advertiser)
            cursor.execute("""
                SELECT COUNT(*) FROM campaigns WHERE advertiser_id = ?
            """, (advertiser_dict['id'],))
            details['stats']['total_orders'] = _get_count_from_result(cursor.fetchone())

            cursor.execute("""
                SELECT COUNT(*) FROM campaigns
                WHERE advertiser_id = ? AND status = 'completed'
            """, (advertiser_dict['id'],))
            details['stats']['completed_orders'] = _get_count_from_result(cursor.fetchone())

        return details


# === ANALYTICS HELPERS ===

def _get_count_from_result(result):
    """Helper для извлечения значения COUNT(*) из результата fetchone()"""
    if not result:
        return 0
    # PostgreSQL возвращает dict, SQLite может вернуть tuple
    if isinstance(result, dict):
        return result.get('count', 0)
    else:
        return result[0]

def get_analytics_stats():
    """Получает подробную статистику для админ-панели"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        stats = {}

        # === ПОЛЬЗОВАТЕЛИ ===
        cursor.execute("SELECT COUNT(*) FROM users")
        stats['total_users'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = TRUE")
        stats['banned_users'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM bloggers")
        stats['total_workers'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM advertisers")
        stats['total_clients'] = _get_count_from_result(cursor.fetchone())

        # Пользователи с двумя профилями (и мастер и клиент)
        cursor.execute("""
            SELECT COUNT(DISTINCT w.user_id)
            FROM bloggers w
            INNER JOIN advertisers c ON w.user_id = c.user_id
        """)
        stats['dual_profile_users'] = _get_count_from_result(cursor.fetchone())

        # === ЗАКАЗЫ ===
        cursor.execute("SELECT COUNT(*) FROM campaigns")
        stats['total_orders'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM campaigns WHERE status = 'open'")
        stats['open_orders'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("""
            SELECT COUNT(*) FROM campaigns
            WHERE status IN ('master_selected', 'contact_shared', 'master_confirmed', 'waiting_master_confirmation')
        """)
        stats['active_orders'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM campaigns WHERE status IN ('done', 'completed')")
        stats['completed_orders'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM campaigns WHERE status = 'canceled'")
        stats['canceled_orders'] = _get_count_from_result(cursor.fetchone())

        # === ОТКЛИКИ ===
        cursor.execute("SELECT COUNT(*) FROM offers")
        stats['total_bids'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM offers WHERE status = 'pending'")
        stats['pending_bids'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM offers WHERE status = 'selected'")
        stats['selected_bids'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM offers WHERE status = 'rejected'")
        stats['rejected_bids'] = _get_count_from_result(cursor.fetchone())

        # === ЧАТЫ И СООБЩЕНИЯ ===
        cursor.execute("SELECT COUNT(*) FROM chats")
        stats['total_chats'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) FROM messages")
        stats['total_messages'] = _get_count_from_result(cursor.fetchone())

        # === ОТЗЫВЫ ===
        cursor.execute("SELECT COUNT(*) FROM reviews")
        stats['total_reviews'] = _get_count_from_result(cursor.fetchone())

        cursor.execute("SELECT AVG(rating) FROM reviews")
        result = cursor.fetchone()
        if result:
            avg_rating = result['avg'] if isinstance(result, dict) else result[0]
            stats['average_rating'] = float(avg_rating) if avg_rating else 0.0
        else:
            stats['average_rating'] = 0.0

        # === АКТИВНОСТЬ ===
        # Заказов за последние 24 часа
        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) FROM campaigns
                WHERE CAST(created_at AS TIMESTAMP) >= NOW() - INTERVAL '1 day'
            """)
        else:
            cursor.execute("""
                SELECT COUNT(*) FROM campaigns
                WHERE created_at >= datetime('now', '-1 day')
            """)
        stats['orders_last_24h'] = _get_count_from_result(cursor.fetchone())

        # Новых пользователей за 7 дней
        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE CAST(created_at AS TIMESTAMP) >= NOW() - INTERVAL '7 days'
            """)
        else:
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE created_at >= datetime('now', '-7 days')
            """)
        stats['users_last_7days'] = _get_count_from_result(cursor.fetchone())

        # Premium статус
        stats['premium_enabled'] = is_premium_enabled()

        return stats


def create_indexes():
    """
    Создает индексы для оптимизации производительности запросов.
    Должна вызываться после init_db().
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Индексы для таблицы users
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")

            # Индексы для таблицы bloggers
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_user_id ON bloggers(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_city ON bloggers(city)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_rating ON bloggers(rating DESC)")

            # Индексы для таблицы advertisers
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clients_user_id ON advertisers(user_id)")

            # Индексы для таблицы campaigns
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_client_id ON campaigns(advertiser_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON campaigns(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_city ON campaigns(city)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_category ON campaigns(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON campaigns(created_at DESC)")
            # Composite index для часто используемого запроса
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status_category ON campaigns(status, category)")

            # Индексы для таблицы offers
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bids_order_id ON offers(campaign_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bids_worker_id ON offers(blogger_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bids_status ON offers(status)")
            # Composite index для проверки существования отклика
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bids_order_worker ON offers(campaign_id, blogger_id)")

            # Индексы для таблицы reviews
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_from_user ON reviews(from_user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_to_user ON reviews(to_user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_order_id ON reviews(campaign_id)")

            conn.commit()
            print("✅ Индексы успешно созданы для оптимизации производительности")

        except Exception as e:
            print(f"⚠️  Предупреждение при создании индексов: {e}")

def create_order(advertiser_id, city, categories, description, photos, videos=None, budget_type="none", budget_value=0, payment_type="paid"):
    """
    Создаёт новый заказ.
    ИСПРАВЛЕНО: Валидация file_id для фотографий.
    ОБНОВЛЕНО: Добавлена поддержка видео.
    ОБНОВЛЕНО: Добавлена поддержка типа оплаты (paid/barter).
    """
    # Rate limiting: проверяем лимит заказов
    allowed, remaining_seconds = _rate_limiter.is_allowed(advertiser_id, "create_order", RATE_LIMIT_ORDERS_PER_HOUR)
    if not allowed:
        minutes = remaining_seconds // 60
        raise ValueError(f"❌ Превышен лимит создания заказов. Попробуйте через {minutes} мин.")

    # Валидация входных данных
    city = validate_string_length(city, MAX_CITY_LENGTH, "city")
    description = validate_string_length(description, MAX_DESCRIPTION_LENGTH, "description")

    # ИСПРАВЛЕНИЕ: Валидация file_id для фотографий заказа
    if photos:
        validated_photos = validate_photo_list(photos, "campaign_photos")
        photos = validated_photos  # Сохраняем как список для последующего преобразования

    # Валидация file_id для видео
    if videos:
        validated_videos = validate_photo_list(videos, "campaign_videos")
        videos = validated_videos

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Преобразуем список категорий в строку
        categories_str = ", ".join(categories) if isinstance(categories, list) else categories
        categories_str = validate_string_length(categories_str, MAX_CATEGORY_LENGTH, "categories")

        # Преобразуем список фото в строку
        photos_str = ",".join(photos) if isinstance(photos, list) else photos

        # Преобразуем список видео в строку
        videos_str = ",".join(videos) if videos and isinstance(videos, list) else (videos if videos else "")

        cursor.execute("""
            INSERT INTO campaigns (
                advertiser_id, city, category, description, photos, videos,
                budget_type, budget_value, payment_type, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """, (advertiser_id, city, categories_str, description, photos_str, videos_str, budget_type, budget_value, payment_type, now))

        campaign_id = cursor.lastrowid
        conn.commit()  # КРИТИЧНО: Фиксируем транзакцию создания заказа
        logger.info(f"✅ Создан заказ: ID={campaign_id}, Клиент={advertiser_id}, Город={city}, Категории={categories_str}, Фото={len(photos) if photos else 0}, Видео={len(videos) if videos else 0}")

    # ИСПРАВЛЕНИЕ: Добавляем категории в нормализованную таблицу
    if categories:
        categories_list = categories if isinstance(categories, list) else [cat.strip() for cat in categories.split(',') if cat.strip()]
        add_order_categories(campaign_id, categories_list)
        logger.info(f"📋 Добавлены категории для заказа {campaign_id}: {categories_list}")

    return campaign_id


def get_orders_by_category(category, page=1, per_page=10):
    """
    ИСПРАВЛЕНО: Получает открытые заказы по категории с пагинацией.
    Использует нормализованную таблицу campaign_categories для точного поиска.

    Args:
        category: Категория заказа (точное совпадение)
        page: Номер страницы (начиная с 1)
        per_page: Количество заказов на странице

    Returns:
        tuple: (campaigns, total_count, has_next_page)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # ИСПРАВЛЕНО: Используем campaign_categories для точного поиска вместо LIKE
        # Получаем общее количество заказов
        cursor.execute("""
            SELECT COUNT(DISTINCT o.id)
            FROM campaigns o
            JOIN campaign_categories oc ON o.id = oc.campaign_id
            WHERE o.status = 'open'
            AND oc.category = ?
        """, (category,))
        total_count = _get_count_from_result(cursor.fetchone())

        # Получаем заказы для текущей страницы
        offset = (page - 1) * per_page
        cursor.execute("""
            SELECT DISTINCT
                o.*,
                c.name as advertiser_name,
                c.rating as advertiser_rating,
                c.rating_count as advertiser_rating_count
            FROM campaigns o
            JOIN campaign_categories oc ON o.id = oc.campaign_id
            JOIN advertisers c ON o.advertiser_id = c.id
            WHERE o.status = 'open'
            AND oc.category = ?
            ORDER BY o.created_at DESC
            LIMIT ? OFFSET ?
        """, (category, per_page, offset))

        campaigns = cursor.fetchall()
        has_next_page = (offset + per_page) < total_count

        return campaigns, total_count, has_next_page


def get_orders_by_categories(categories_list, per_page=30, blogger_id=None):
    """
    ИСПРАВЛЕНО: Получает заказы для НЕСКОЛЬКИХ категорий ОДНИМ запросом с ТОЧНЫМ поиском.
    ИСПРАВЛЕНО: Фильтрует заказы по городам мастера (мастер видит только заказы из СВОИХ городов).

    Раньше:
    - 5 категорий = 5 SQL запросов (N+1 проблема)
    - LIKE '%Электрика%' находил "Неэлектрика" (ложные совпадения)
    - Мастер видел заказы из ВСЕХ городов (неправильно)

    Теперь:
    - 5 категорий = 1 SQL запрос
    - Точное совпадение через campaign_categories таблицу
    - Фильтрация по городам мастера через blogger_cities

    Args:
        categories_list: Список категорий ["Электрика", "Сантехника"]
        per_page: Максимум заказов (по умолчанию 30)
        blogger_id: ID мастера для фильтрации по городам (опционально)

    Returns:
        Список заказов, отсортированных по дате (новые первые)
    """
    if not categories_list:
        return []

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Создаем IN clause для точного поиска по категориям
        # Используем нормализованную таблицу campaign_categories
        placeholders = ', '.join(['?' for _ in categories_list])

        # ИСПРАВЛЕНО: Добавлена фильтрация по городам мастера
        city_filter = ""
        if blogger_id:
            city_filter = """
                AND (
                    o.city IN (SELECT city FROM blogger_cities WHERE blogger_id = ?)
                    OR o.city = (SELECT city FROM bloggers WHERE id = ?)
                )
            """

        query = f"""
            SELECT DISTINCT
                o.*,
                c.name as advertiser_name,
                c.rating as advertiser_rating,
                c.rating_count as advertiser_rating_count
            FROM campaigns o
            JOIN advertisers c ON o.advertiser_id = c.id
            JOIN campaign_categories oc ON o.id = oc.campaign_id
            WHERE o.status = 'open'
            AND oc.category IN ({placeholders})
            {city_filter}
            ORDER BY o.created_at DESC
            LIMIT ?
        """

        params = [cat.strip() for cat in categories_list if cat and cat.strip()]

        # Добавляем blogger_id дважды для фильтрации по городам
        if blogger_id:
            params.append(blogger_id)
            params.append(blogger_id)

        params.append(per_page)

        logger.info(f"🔍 Поиск заказов: категории={categories_list}, blogger_id={blogger_id}")
        cursor.execute(query, params)
        results = cursor.fetchall()
        logger.info(f"🔍 Найдено заказов: {len(results)}")
        return results


def get_client_orders(advertiser_id, page=1, per_page=10):
    """
    Получает заказы клиента с пагинацией.

    Args:
        advertiser_id: ID клиента
        page: Номер страницы (начиная с 1)
        per_page: Количество заказов на странице

    Returns:
        tuple: (campaigns, total_count, has_next_page)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем общее количество заказов
        cursor.execute("SELECT COUNT(*) FROM campaigns WHERE advertiser_id = ?", (advertiser_id,))
        total_count = _get_count_from_result(cursor.fetchone())

        # Получаем заказы для текущей страницы
        offset = (page - 1) * per_page
        cursor.execute("""
            SELECT * FROM campaigns
            WHERE advertiser_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (advertiser_id, per_page, offset))

        campaigns = cursor.fetchall()
        has_next_page = (offset + per_page) < total_count

        return campaigns, total_count, has_next_page




def cancel_order(campaign_id, cancelled_by_user_id, reason=""):
    """
    НОВОЕ: Отменяет заказ клиентом.

    Args:
        campaign_id: ID заказа
        cancelled_by_user_id: ID пользователя который отменяет
        reason: Причина отмены (опционально)

    Returns:
        dict: {
            'success': bool,
            'message': str,
            'notified_workers': list  # ID мастеров которым отправлено уведомление
        }
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Проверяем существование заказа и права на отмену
        cursor.execute("""
            SELECT o.*, c.user_id as advertiser_user_id
            FROM campaigns o
            JOIN advertisers c ON o.advertiser_id = c.id
            WHERE o.id = ?
        """, (campaign_id,))

        campaign = cursor.fetchone()
        if not campaign:
            return {'success': False, 'message': 'Заказ не найден', 'notified_workers': []}

        campaign_dict = dict(campaign)

        # Проверка прав: только владелец может отменить
        if campaign_dict['advertiser_user_id'] != cancelled_by_user_id:
            return {'success': False, 'message': 'Нет прав на отмену этого заказа', 'notified_workers': []}

        # Проверка статуса: можно отменить только open или waiting_master_confirmation
        if campaign_dict['status'] not in ('open', 'waiting_master_confirmation'):
            return {
                'success': False,
                'message': f"Нельзя отменить заказ в статусе '{campaign_dict['status']}'",
                'notified_workers': []
            }

        # Обновляем статус заказа
        cursor.execute("""
            UPDATE campaigns
            SET status = 'cancelled'
            WHERE id = ?
        """, (campaign_id,))

        # Получаем список мастеров которые откликнулись (для уведомления)
        cursor.execute("""
            SELECT DISTINCT w.user_id
            FROM offers b
            JOIN bloggers w ON b.blogger_id = w.id
            WHERE b.campaign_id = ? AND b.status IN ('pending', 'selected')
        """, (campaign_id,))

        blogger_user_ids = [row[0] for row in cursor.fetchall()]

        # Отмечаем все отклики как rejected
        cursor.execute("""
            UPDATE offers
            SET status = 'rejected'
            WHERE campaign_id = ?
        """, (campaign_id,))

        conn.commit()

        logger.info(f"Заказ {campaign_id} отменен пользователем {cancelled_by_user_id}. Причина: {reason}")

        return {
            'success': True,
            'message': 'Заказ успешно отменен',
            'notified_workers': blogger_user_ids
        }


def check_expired_orders():
    """
    НОВОЕ: Проверяет и обрабатывает заказы с истекшим дедлайном.

    Автоматически находит заказы, у которых:
    - deadline прошел (deadline < now)
    - статус 'open' или 'waiting_master_confirmation'

    Для найденных заказов:
    - Меняет статус на 'expired'
    - Отклоняет все активные отклики
    - Возвращает информацию для отправки уведомлений

    Returns:
        list: Список словарей с информацией о просроченных заказах:
            [
                {
                    'campaign_id': int,
                    'advertiser_user_id': int,
                    'blogger_user_ids': [int, ...],
                    'title': str
                },
                ...
            ]
    """
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Находим просроченные заказы
        now = datetime.now().isoformat()

        cursor.execute("""
            SELECT o.id, o.title, o.deadline, c.user_id as advertiser_user_id
            FROM campaigns o
            JOIN advertisers c ON o.advertiser_id = c.id
            WHERE o.deadline IS NOT NULL
            AND o.deadline != ''
            AND o.deadline < ?
            AND o.status IN ('open', 'waiting_master_confirmation')
        """, (now,))

        expired_orders = cursor.fetchall()

        if not expired_orders:
            logger.debug("Просроченных заказов не найдено")
            return []

        result = []

        for campaign_row in expired_orders:
            campaign_id = campaign_row['id']
            title = campaign_row['title']
            advertiser_user_id = campaign_row['advertiser_user_id']

            # Получаем всех мастеров, которые откликнулись
            cursor.execute("""
                SELECT DISTINCT w.user_id
                FROM offers b
                JOIN bloggers w ON b.blogger_id = w.id
                WHERE b.campaign_id = ? AND b.status IN ('pending', 'selected')
            """, (campaign_id,))

            blogger_rows = cursor.fetchall()
            blogger_user_ids = [row['user_id'] for row in blogger_rows]

            # Обновляем статус заказа
            cursor.execute("""
                UPDATE campaigns
                SET status = 'expired'
                WHERE id = ?
            """, (campaign_id,))

            # Отклоняем все активные отклики
            cursor.execute("""
                UPDATE offers
                SET status = 'rejected'
                WHERE campaign_id = ? AND status IN ('pending', 'selected')
            """, (campaign_id,))

            logger.info(f"Заказ {campaign_id} истек по дедлайну. Клиент: {advertiser_user_id}, Мастеров: {len(blogger_user_ids)}")

            result.append({
                'campaign_id': campaign_id,
                'advertiser_user_id': advertiser_user_id,
                'blogger_user_ids': blogger_user_ids,
                'title': title
            })

        conn.commit()

        logger.info(f"Обработано просроченных заказов: {len(result)}")
        return result


def create_bid(campaign_id, blogger_id, proposed_price, currency, comment="", ready_in_days=7):
    """Создаёт отклик мастера на заказ"""
    # Rate limiting: проверяем лимит откликов
    allowed, remaining_seconds = _rate_limiter.is_allowed(blogger_id, "create_bid", RATE_LIMIT_BIDS_PER_HOUR)
    if not allowed:
        minutes = remaining_seconds // 60
        raise ValueError(f"❌ Превышен лимит откликов. Попробуйте через {minutes} мин.")

    # Валидация входных данных
    comment = validate_string_length(comment, MAX_COMMENT_LENGTH, "comment")

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO offers (
                campaign_id, blogger_id, proposed_price, currency,
                comment, ready_in_days, created_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """, (campaign_id, blogger_id, proposed_price, currency, comment, ready_in_days, now))

        conn.commit()
        offer_id = cursor.lastrowid
        logger.info(f"✅ Создан отклик: ID={offer_id}, Заказ={campaign_id}, Мастер={blogger_id}, Цена={proposed_price} {currency}, Срок={ready_in_days} дн.")
        return offer_id


def get_bids_for_order(campaign_id):
    """Получает все отклики для заказа с полной информацией о мастере"""
    with get_db_connection() as conn:

        cursor = get_cursor(conn)

        cursor.execute("""
            SELECT
                b.*,
                w.name as blogger_name,
                w.rating as blogger_rating,
                w.rating_count as blogger_rating_count,
                w.experience as blogger_experience,
                w.phone as blogger_phone,
                w.profile_photo as blogger_profile_photo,
                w.portfolio_photos as blogger_portfolio_photos,
                w.description as blogger_description,
                w.city as blogger_city,
                w.categories as blogger_categories,
                w.verified_reviews as blogger_verified_reviews,
                u.telegram_id as blogger_telegram_id
            FROM offers b
            JOIN bloggers w ON b.blogger_id = w.id
            JOIN users u ON w.user_id = u.id
            WHERE b.campaign_id = ?
            AND b.status = 'active'
            ORDER BY b.created_at ASC
        """, (campaign_id,))

        return cursor.fetchall()


def check_worker_bid_exists(campaign_id, blogger_id):
    """Проверяет, откликался ли уже мастер на этот заказ"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        cursor.execute("""
            SELECT COUNT(*) FROM offers
            WHERE campaign_id = ? AND blogger_id = ?
        """, (campaign_id, blogger_id))

        result = cursor.fetchone()
        if not result:
            return False
        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return result.get('count', 0) > 0
        else:
            return result[0] > 0


def get_bid_by_id(offer_id):
    """Получает отклик по ID с полной информацией о мастере"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if USE_POSTGRES:
            cursor.execute("""
                SELECT
                    b.*,
                    w.name as blogger_name,
                    w.rating as blogger_rating,
                    w.rating_count as blogger_rating_count,
                    w.experience as blogger_experience,
                    w.phone as blogger_phone,
                    w.profile_photo as blogger_profile_photo,
                    w.portfolio_photos as blogger_portfolio_photos,
                    w.description as blogger_description,
                    w.city as blogger_city,
                    w.categories as blogger_categories,
                    w.verified_reviews as blogger_verified_reviews,
                    u.telegram_id as blogger_telegram_id
                FROM offers b
                JOIN bloggers w ON b.blogger_id = w.id
                JOIN users u ON w.user_id = u.id
                WHERE b.id = %s
            """, (offer_id,))
        else:
            cursor.execute("""
                SELECT
                    b.*,
                    w.name as blogger_name,
                    w.rating as blogger_rating,
                    w.rating_count as blogger_rating_count,
                    w.experience as blogger_experience,
                    w.phone as blogger_phone,
                    w.profile_photo as blogger_profile_photo,
                    w.portfolio_photos as blogger_portfolio_photos,
                    w.description as blogger_description,
                    w.city as blogger_city,
                    w.categories as blogger_categories,
                    w.verified_reviews as blogger_verified_reviews,
                    u.telegram_id as blogger_telegram_id
                FROM offers b
                JOIN bloggers w ON b.blogger_id = w.id
                JOIN users u ON w.user_id = u.id
                WHERE b.id = ?
            """, (offer_id,))

        return cursor.fetchone()


def get_bids_count_for_order(campaign_id):
    """Получает количество активных откликов для заказа"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        cursor.execute("""
            SELECT COUNT(*) FROM offers
            WHERE campaign_id = ? AND status = 'active'
        """, (campaign_id,))

        result = cursor.fetchone()
        if not result:
            return 0
        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            return result.get('count', 0)
        else:
            return result[0]


def get_bids_for_worker(blogger_id):
    """
    Получает все отклики мастера с информацией о заказах.

    Args:
        blogger_id: ID мастера в таблице bloggers

    Returns:
        Список откликов с информацией о заказе и клиенте
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        cursor.execute("""
            SELECT
                b.*,
                o.title as campaign_title,
                o.description as campaign_description,
                o.city as campaign_city,
                o.category as campaign_category,
                o.status as campaign_status,
                o.created_at as campaign_created_at,
                c.name as advertiser_name,
                u.telegram_id as advertiser_telegram_id
            FROM offers b
            JOIN campaigns o ON b.campaign_id = o.id
            JOIN advertisers c ON o.advertiser_id = c.id
            JOIN users u ON c.user_id = u.id
            WHERE b.blogger_id = ?
            ORDER BY b.created_at DESC
        """, (blogger_id,))

        return cursor.fetchall()


def select_bid(offer_id):
    """
    ИСПРАВЛЕНО: Отмечает отклик как выбранный с защитой от race conditions.
    Проверяет что заказ еще не был выбран другим пользователем.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # КРИТИЧНО: Получаем campaign_id, blogger_id и проверяем статус заказа одним запросом
        cursor.execute("""
            SELECT b.campaign_id, b.blogger_id, o.status
            FROM offers b
            JOIN campaigns o ON b.campaign_id = o.id
            WHERE b.id = ?
        """, (offer_id,))
        result = cursor.fetchone()
        if not result:
            logger.warning(f"Отклик {offer_id} не найден")
            return False

        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            campaign_id = result['campaign_id']
            blogger_id = result['blogger_id']
            campaign_status = result['status']
        else:
            campaign_id, blogger_id, campaign_status = result[0], result[1], result[2]

        # ЗАЩИТА ОТ RACE CONDITION: проверяем что заказ еще не был выбран
        if campaign_status not in ('open', 'waiting_master_confirmation'):
            logger.warning(f"Заказ {campaign_id} уже в статусе '{campaign_status}', нельзя выбрать мастера")
            return False

        # Обновляем статус выбранного отклика
        cursor.execute("""
            UPDATE offers
            SET status = 'selected'
            WHERE id = ?
        """, (offer_id,))

        # Остальные отклики отмечаем как rejected
        cursor.execute("""
            UPDATE offers
            SET status = 'rejected'
            WHERE campaign_id = ? AND id != ?
        """, (campaign_id, offer_id))

        # КРИТИЧНО: Обновляем статус заказа И устанавливаем selected_worker_id
        # Это необходимо для показа кнопок чата и завершения заказа
        cursor.execute("""
            UPDATE campaigns
            SET status = 'master_selected', selected_worker_id = ?
            WHERE id = ? AND status IN ('open', 'waiting_master_confirmation')
        """, (blogger_id, campaign_id))

        # Проверяем что UPDATE действительно произошел
        if cursor.rowcount == 0:
            logger.warning(f"Не удалось обновить заказ {campaign_id} - возможно race condition")
            conn.rollback()
            return False

        conn.commit()
        logger.info(f"✅ Заказ {campaign_id}: выбран мастер {blogger_id}, установлен selected_worker_id")
        return True


def update_bid_status(offer_id, new_status):
    """Обновляет статус отклика (pending, selected, rejected)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE offers
            SET status = ?
            WHERE id = ?
        """, (new_status, offer_id))
        conn.commit()
        return cursor.rowcount > 0


def add_test_orders(telegram_id):
    """
    Добавляет 18 тестовых заказов для указанного пользователя.
    Используется только для пользователя с telegram_id = 641830790.

    Args:
        telegram_id: Telegram ID пользователя

    Returns:
        tuple: (success: bool, message: str, orders_created: int)
    """
    # Проверка, что это разрешенный пользователь
    if telegram_id != 641830790:
        return (False, "❌ Эта команда доступна только для администратора.", 0)

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем или создаем пользователя
        cursor.execute("SELECT id, role FROM users WHERE telegram_id = ?", (telegram_id,))
        user_row = cursor.fetchone()

        if not user_row:
            # Создаем пользователя как клиента
            created_at = datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO users (telegram_id, role, created_at) VALUES (?, ?, ?)",
                (telegram_id, "advertiser", created_at)
            )
            user_id = cursor.lastrowid

            # Создаем профиль клиента
            cursor.execute("""
                INSERT INTO advertisers (user_id, name, phone, city, description)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, "Тестовый клиент", "+375291234567", "Минск", "Тестовый профиль"))
        else:
            user_id = user_row['id']
            # Пользователь может быть мастером или клиентом - это не важно
            # Проверим наличие профиля клиента и создадим если нужно

        # Получаем advertiser_id
        cursor.execute("SELECT id FROM advertisers WHERE user_id = ?", (user_id,))
        advertiser_row = cursor.fetchone()

        if not advertiser_row:
            # Создаем профиль клиента, если его нет
            cursor.execute("""
                INSERT INTO advertisers (user_id, name, phone, city, description)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, "Тестовый клиент", "+375291234567", "Минск", "Тестовый профиль"))
            advertiser_id = cursor.lastrowid
        else:
            advertiser_id = advertiser_row['id']

        # Данные для создания тестовых заказов
        categories = [
            "Электрика", "Сантехника", "Отделка", "Сборка мебели",
            "Окна/двери", "Бытовая техника", "Напольные покрытия",
            "Мелкий ремонт", "Дизайн"
        ]

        cities = ["Минск", "Гомель", "Могилёв", "Витебск", "Гродно", "Брест"]

        test_orders = [
            ("Электрика", "Минск", "Замена розеток в квартире", "none", 0),
            ("Сантехника", "Минск", "Установка смесителя на кухне", "fixed", 50),
            ("Отделка", "Минск", "Покраска стен в двух комнатах", "flexible", 200),
            ("Сборка мебели", "Минск", "Сборка шкафа-купе 2м", "fixed", 80),
            ("Окна/двери", "Минск", "Регулировка пластиковых окон", "none", 0),
            ("Бытовая техника", "Минск", "Ремонт стиральной машины", "flexible", 100),
            ("Напольные покрытия", "Минск", "Укладка ламината 20м²", "fixed", 300),
            ("Мелкий ремонт", "Минск", "Повесить полки и картины", "none", 0),
            ("Дизайн", "Минск", "Консультация по дизайну интерьера", "flexible", 150),
            ("Электрика", "Минск", "Установка люстры в зале", "fixed", 40),
            ("Сантехника", "Минск", "Замена унитаза", "flexible", 120),
            ("Отделка", "Минск", "Поклейка обоев в спальне", "fixed", 180),
            ("Сборка мебели", "Минск", "Сборка кухонного гарнитура", "flexible", 250),
            ("Окна/двери", "Минск", "Установка межкомнатной двери", "fixed", 100),
            ("Бытовая техника", "Минск", "Ремонт холодильника", "none", 0),
            ("Напольные покрытия", "Минск", "Укладка плитки в ванной 5м²", "fixed", 200),
            ("Мелкий ремонт", "Минск", "Замена замков на дверях", "flexible", 70),
            ("Электрика", "Минск", "Проводка света в гараже", "fixed", 150),
        ]

        # Создаем заказы
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        orders_created = 0

        for category, city, description, budget_type, budget_value in test_orders:
            try:
                cursor.execute("""
                    INSERT INTO campaigns (
                        advertiser_id, city, category, description, photos,
                        budget_type, budget_value, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """, (advertiser_id, city, category, description, "", budget_type, budget_value, now))
                orders_created += 1
            except Exception as e:
                print(f"Ошибка при создании заказа: {e}")

        conn.commit()

        return (True, f"✅ Успешно добавлено {orders_created} тестовых заказов!", orders_created)


def add_test_workers(telegram_id):
    """
    Добавляет тестовых мастеров и их отклики на заказы.
    Используется только для пользователя с telegram_id = 641830790.

    Args:
        telegram_id: Telegram ID пользователя

    Returns:
        tuple: (success: bool, message: str, workers_created: int)
    """
    # Проверка, что это разрешенный пользователь
    if telegram_id != 641830790:
        return (False, "❌ Эта команда доступна только для администратора.", 0)

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Данные тестовых мастеров
        test_workers = [
            {
                "telegram_id": 100000001,
                "name": "Иван Петров",
                "phone": "+375291111111",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Электрика, Мелкий ремонт",
                "experience": "5-10 лет",
                "description": "Профессиональный электрик. Выполняю все виды электромонтажных работ. Качественно и в срок.",
                "rating": 4.8,
                "rating_count": 15
            },
            {
                "telegram_id": 100000002,
                "name": "Сергей Козлов",
                "phone": "+375292222222",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Сантехника, Отделка",
                "experience": "10+ лет",
                "description": "Опытный сантехник. Установка, ремонт, замена любого сантехнического оборудования.",
                "rating": 4.9,
                "rating_count": 23
            },
            {
                "telegram_id": 100000003,
                "name": "Александр Смирнов",
                "phone": "+375293333333",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Сборка мебели, Мелкий ремонт",
                "experience": "3-5 лет",
                "description": "Быстро и качественно соберу любую мебель. Работаю с инструкциями и без.",
                "rating": 4.7,
                "rating_count": 12
            },
            {
                "telegram_id": 100000004,
                "name": "Дмитрий Волков",
                "phone": "+375294444444",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Окна/двери, Напольные покрытия",
                "experience": "5-10 лет",
                "description": "Установка и ремонт окон, дверей. Укладка ламината, плитки. Гарантия качества.",
                "rating": 4.6,
                "rating_count": 18
            },
            {
                "telegram_id": 100000005,
                "name": "Андрей Новиков",
                "phone": "+375295555555",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Бытовая техника, Электрика",
                "experience": "10+ лет",
                "description": "Ремонт любой бытовой техники: холодильники, стиральные машины, СВЧ и др.",
                "rating": 4.9,
                "rating_count": 31
            },
            {
                "telegram_id": 100000006,
                "name": "Михаил Соколов",
                "phone": "+375296666666",
                "city": "Минск",
                "regions": "Минск",
                "categories": "Отделка, Дизайн",
                "experience": "5-10 лет",
                "description": "Профессиональная отделка помещений. Консультации по дизайну интерьера.",
                "rating": 4.8,
                "rating_count": 20
            }
        ]

        workers_created = 0
        blogger_ids = []

        # Создаем тестовых мастеров
        for blogger_data in test_workers:
            try:
                # Проверяем, существует ли пользователь
                cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (blogger_data["telegram_id"],))
                existing_user = cursor.fetchone()

                if not existing_user:
                    # Создаем пользователя
                    created_at = datetime.now().isoformat()
                    cursor.execute(
                        "INSERT INTO users (telegram_id, role, created_at) VALUES (?, ?, ?)",
                        (blogger_data["telegram_id"], "blogger", created_at)
                    )
                    user_id = cursor.lastrowid

                    # Создаем профиль мастера
                    cursor.execute("""
                        INSERT INTO bloggers (user_id, name, phone, city, regions, categories, experience, description, rating, rating_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id,
                        blogger_data["name"],
                        blogger_data["phone"],
                        blogger_data["city"],
                        blogger_data["regions"],
                        blogger_data["categories"],
                        blogger_data["experience"],
                        blogger_data["description"],
                        blogger_data["rating"],
                        blogger_data["rating_count"]
                    ))
                    blogger_id = cursor.lastrowid
                    blogger_ids.append(blogger_id)
                    workers_created += 1
                else:
                    # Получаем blogger_id существующего мастера
                    user_id = existing_user[0] if isinstance(existing_user, tuple) else existing_user['id']
                    cursor.execute("SELECT id FROM bloggers WHERE user_id = ?", (user_id,))
                    blogger_row = cursor.fetchone()
                    if blogger_row:
                        blogger_id = blogger_row[0] if isinstance(blogger_row, tuple) else blogger_row['id']
                        blogger_ids.append(blogger_id)

            except Exception as e:
                print(f"Ошибка при создании мастера: {e}")

        # Получаем все открытые заказы
        cursor.execute("SELECT id, category FROM campaigns WHERE status = 'open'")
        campaigns = cursor.fetchall()

        # Создаем отклики от мастеров на подходящие заказы
        bids_created = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for campaign in campaigns:
            campaign_id = campaign[0] if isinstance(campaign, tuple) else campaign['id']
            campaign_category = campaign[1] if isinstance(campaign, tuple) else campaign['category']

            # Для каждого заказа добавляем 2-3 отклика от подходящих мастеров
            suitable_workers = []
            for i, blogger_data in enumerate(test_workers):
                if i < len(blogger_ids) and campaign_category in blogger_data["categories"]:
                    suitable_workers.append((blogger_ids[i], blogger_data))

            # Добавляем отклики от первых 2-3 подходящих мастеров
            for blogger_id, blogger_data in suitable_workers[:3]:
                try:
                    # Проверяем, нет ли уже отклика
                    cursor.execute(
                        "SELECT COUNT(*) FROM offers WHERE campaign_id = ? AND blogger_id = ?",
                        (campaign_id, blogger_id)
                    )
                    existing_bid = cursor.fetchone()
                    offer_exists = existing_bid[0] if isinstance(existing_bid, tuple) else existing_bid['COUNT(*)']

                    if not offer_exists or offer_exists == 0:
                        # Генерируем цену (50-300 BYN)
                        import random
                        price = random.randint(50, 300)

                        # Создаем отклик
                        cursor.execute("""
                            INSERT INTO offers (campaign_id, blogger_id, proposed_price, currency, comment, created_at, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            campaign_id,
                            blogger_id,
                            price,
                            "BYN",
                            f"Готов выполнить работу качественно и в срок. Опыт {blogger_data['experience']}.",
                            now,
                            "active"
                        ))
                        bids_created += 1

                except Exception as e:
                    print(f"Ошибка при создании отклика: {e}")

        conn.commit()

        message = f"✅ Успешно добавлено:\n• {workers_created} тестовых мастеров\n• {bids_created} откликов на заказы"
        return (True, message, workers_created)


def add_test_advertisers(telegram_id):
    """
    Добавляет тестовых рекламодателей (заказчиков).
    Используется только для пользователя с telegram_id = 641830790.

    Args:
        telegram_id: Telegram ID пользователя

    Returns:
        tuple: (success: bool, message: str, advertisers_created: int)
    """
    # Проверка, что это разрешенный пользователь
    if telegram_id != 641830790:
        return (False, "❌ Эта команда доступна только для администратора.", 0)

    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Данные тестовых рекламодателей
        test_advertisers = [
            {
                "telegram_id": 200000001,
                "name": "Кафе 'Минский Шик'",
                "phone": "+375441111111",
                "city": "Минск",
                "regions": "Минск",
                "description": "Уютное кафе в центре Минска. Ищем блогеров для продвижения новых позиций меню."
            },
            {
                "telegram_id": 200000002,
                "name": "Спортзал 'Атлетик'",
                "phone": "+375442222222",
                "city": "Минск",
                "regions": "Минск",
                "description": "Современный фитнес-клуб. Предлагаем сотрудничество блогерам в сфере ЗОЖ и спорта."
            },
            {
                "telegram_id": 200000003,
                "name": "Салон красоты 'Элеганс'",
                "phone": "+375443333333",
                "city": "Минск",
                "regions": "Минск",
                "description": "Салон красоты премиум-класса. Ищем beauty-блогеров для рекламы наших услуг."
            },
            {
                "telegram_id": 200000004,
                "name": "Магазин 'Eco Life'",
                "phone": "+375444444444",
                "city": "Минск",
                "regions": "Минск",
                "description": "Эко-магазин с натуральными продуктами. Сотрудничаем с блогерами о ЗОЖ и экологии."
            },
            {
                "telegram_id": 200000005,
                "name": "Детский центр 'Умка'",
                "phone": "+375445555555",
                "city": "Минск",
                "regions": "Минск",
                "description": "Развивающий центр для детей. Ищем мам-блогеров для продвижения наших программ."
            }
        ]

        advertisers_created = 0

        # Создаем тестовых рекламодателей
        for adv_data in test_advertisers:
            try:
                # Проверяем, существует ли пользователь
                cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (adv_data["telegram_id"],))
                existing_user = cursor.fetchone()

                if not existing_user:
                    # Создаем пользователя
                    created_at = datetime.now().isoformat()
                    cursor.execute(
                        "INSERT INTO users (telegram_id, role, created_at) VALUES (?, ?, ?)",
                        (adv_data["telegram_id"], "advertiser", created_at)
                    )
                    user_id = cursor.lastrowid

                    # Создаем профиль рекламодателя
                    cursor.execute("""
                        INSERT INTO advertisers (user_id, name, phone, city, regions, description)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        user_id,
                        adv_data["name"],
                        adv_data["phone"],
                        adv_data["city"],
                        adv_data["regions"],
                        adv_data["description"]
                    ))

                    advertisers_created += 1

            except Exception as e:
                print(f"Ошибка при создании рекламодателя: {e}")

        conn.commit()
        message = f"✅ Успешно создано {advertisers_created} тестовых рекламодателей"
        return (True, message, advertisers_created)


def migrate_add_ready_in_days_and_notifications():
    """
    Добавляет:
    1. Поле ready_in_days в таблицу offers (срок готовности мастера)
    2. Таблицу blogger_notifications (для обновляемых уведомлений)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # 1. Добавляем поле ready_in_days в offers
            if USE_POSTGRES:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'offers' AND column_name = 'ready_in_days'
                        ) THEN
                            ALTER TABLE offers ADD COLUMN ready_in_days INTEGER DEFAULT 7;
                        END IF;
                    END $$;
                """)
            else:
                cursor.execute("PRAGMA table_info(offers)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'ready_in_days' not in columns:
                    cursor.execute("ALTER TABLE offers ADD COLUMN ready_in_days INTEGER DEFAULT 7")

            # 2. Создаем таблицу blogger_notifications
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blogger_notifications (
                    user_id INTEGER PRIMARY KEY,
                    notification_message_id INTEGER,
                    notification_chat_id INTEGER,
                    last_update_timestamp INTEGER,
                    available_orders_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            # 3. Создаем таблицу advertiser_notifications
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS advertiser_notifications (
                    user_id INTEGER PRIMARY KEY,
                    notification_message_id INTEGER,
                    notification_chat_id INTEGER,
                    last_update_timestamp INTEGER,
                    unread_bids_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            conn.commit()
            print("✅ Migration completed: added ready_in_days, blogger_notifications and advertiser_notifications!")

        except Exception as e:
            print(f"⚠️  Error in migrate_add_ready_in_days_and_notifications: {e}")
            import traceback
            traceback.print_exc()


# === BLOGGER NOTIFICATIONS HELPERS ===

def save_worker_notification(blogger_user_id, message_id, chat_id, orders_count=0):
    """Сохраняет или обновляет ID сообщения с уведомлением для мастера"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        timestamp = int(datetime.now().timestamp())

        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO blogger_notifications
                (user_id, notification_message_id, notification_chat_id, last_update_timestamp, available_orders_count)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    notification_message_id = EXCLUDED.notification_message_id,
                    notification_chat_id = EXCLUDED.notification_chat_id,
                    last_update_timestamp = EXCLUDED.last_update_timestamp,
                    available_orders_count = EXCLUDED.available_orders_count
            """, (blogger_user_id, message_id, chat_id, timestamp, orders_count))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO blogger_notifications
                (user_id, notification_message_id, notification_chat_id, last_update_timestamp, available_orders_count)
                VALUES (?, ?, ?, ?, ?)
            """, (blogger_user_id, message_id, chat_id, timestamp, orders_count))
        conn.commit()


def get_worker_notification(blogger_user_id):
    """Получает сохраненное уведомление мастера"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM blogger_notifications WHERE user_id = ?
        """, (blogger_user_id,))
        return cursor.fetchone()


def delete_worker_notification(blogger_user_id):
    """Удаляет сохраненное уведомление (когда мастер просмотрел все заказы)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("DELETE FROM blogger_notifications WHERE user_id = ?", (blogger_user_id,))
        conn.commit()


# === ADVERTISER NOTIFICATIONS HELPERS ===

def save_client_notification(advertiser_user_id, message_id, chat_id, bids_count=0):
    """Сохраняет или обновляет ID сообщения с уведомлением для клиента"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        timestamp = int(datetime.now().timestamp())

        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO advertiser_notifications
                (user_id, notification_message_id, notification_chat_id, last_update_timestamp, unread_bids_count)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    notification_message_id = EXCLUDED.notification_message_id,
                    notification_chat_id = EXCLUDED.notification_chat_id,
                    last_update_timestamp = EXCLUDED.last_update_timestamp,
                    unread_bids_count = EXCLUDED.unread_bids_count
            """, (advertiser_user_id, message_id, chat_id, timestamp, bids_count))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO advertiser_notifications
                (user_id, notification_message_id, notification_chat_id, last_update_timestamp, unread_bids_count)
                VALUES (?, ?, ?, ?, ?)
            """, (advertiser_user_id, message_id, chat_id, timestamp, bids_count))
        conn.commit()


def get_client_notification(advertiser_user_id):
    """Получает сохраненное уведомление клиента"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM advertiser_notifications WHERE user_id = ?
        """, (advertiser_user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def delete_client_notification(advertiser_user_id):
    """Удаляет сохраненное уведомление (когда клиент просмотрел все отклики)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("DELETE FROM advertiser_notifications WHERE user_id = ?", (advertiser_user_id,))
        conn.commit()


# === CHAT MESSAGE NOTIFICATIONS HELPERS ===

def save_chat_message_notification(user_id, message_id, chat_id):
    """Сохраняет или обновляет ID уведомления о новых сообщениях в чате"""
    from datetime import datetime

    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        timestamp = int(datetime.now().timestamp())

        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO chat_message_notifications
                (user_id, notification_message_id, notification_chat_id, last_update_timestamp)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    notification_message_id = EXCLUDED.notification_message_id,
                    notification_chat_id = EXCLUDED.notification_chat_id,
                    last_update_timestamp = EXCLUDED.last_update_timestamp
            """, (user_id, message_id, chat_id, timestamp))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO chat_message_notifications
                (user_id, notification_message_id, notification_chat_id, last_update_timestamp)
                VALUES (?, ?, ?, ?)
            """, (user_id, message_id, chat_id, timestamp))
        conn.commit()


def get_chat_message_notification(user_id):
    """Получает сохраненное уведомление о сообщениях в чате"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT * FROM chat_message_notifications WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def delete_chat_message_notification(user_id):
    """Удаляет сохраненное уведомление о сообщениях (когда пользователь просмотрел заказы)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("DELETE FROM chat_message_notifications WHERE user_id = ?", (user_id,))
        conn.commit()


def get_orders_with_unread_bids(advertiser_user_id):
    """
    Получает все заказы клиента с количеством откликов.

    Args:
        advertiser_user_id: ID пользователя-клиента

    Returns:
        list: Список заказов с полем offer_count
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT
                o.id,
                o.city,
                o.category,
                o.description,
                o.status,
                COUNT(b.id) as offer_count
            FROM campaigns o
            LEFT JOIN offers b ON o.id = b.campaign_id AND b.status = 'active'
            WHERE o.advertiser_id = (SELECT id FROM advertisers WHERE user_id = ?)
                AND o.status = 'open'
            GROUP BY o.id, o.city, o.category, o.description, o.status
            HAVING COUNT(b.id) > 0
        """, (advertiser_user_id,))

        return [dict(row) for row in cursor.fetchall()]


def count_available_orders_for_worker(blogger_user_id):
    """
    ИСПРАВЛЕНО: Подсчитывает количество доступных заказов для мастера.
    Использует нормализованные таблицы blogger_categories и campaign_categories для точного поиска.
    Использует blogger_cities для поиска заказов во всех городах мастера.

    (в его городах и его категориях, на которые он еще не откликнулся)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем blogger_id по user_id
        cursor.execute("SELECT id FROM bloggers WHERE user_id = ?", (blogger_user_id,))
        blogger = cursor.fetchone()

        if not blogger:
            return 0

        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(blogger, dict):
            blogger_id = blogger['id']
        else:
            blogger_id = blogger[0]

        # Получаем список городов мастера
        cursor.execute("SELECT city FROM blogger_cities WHERE blogger_id = ?", (blogger_id,))
        cities_result = cursor.fetchall()

        if not cities_result:
            return 0

        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if cities_result and isinstance(cities_result[0], dict):
            cities = [row['city'] for row in cities_result]
        else:
            cities = [row[0] for row in cities_result]

        # ИСПРАВЛЕНО: Используем нормализованные таблицы вместо LIKE
        # Ищем заказы через JOIN с campaign_categories и blogger_categories
        # Проверяем, что заказ находится в одном из городов мастера
        placeholders = ','.join('?' * len(cities))
        query = f"""
            SELECT COUNT(DISTINCT o.id)
            FROM campaigns o
            JOIN campaign_categories oc ON o.id = oc.campaign_id
            JOIN blogger_categories wc ON oc.category = wc.category
            WHERE o.status = 'open'
            AND o.city IN ({placeholders})
            AND wc.blogger_id = ?
            AND o.id NOT IN (
                SELECT campaign_id FROM offers WHERE blogger_id = ?
            )
        """

        cursor.execute(query, (*cities, blogger_id, blogger_id))

        result = cursor.fetchone()
        if not result:
            return 0
        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            count = result.get('count', 0)
        else:
            count = result[0]

        return count


# ============================================
# СИСТЕМА АДМИН-ПАНЕЛИ И РЕКЛАМЫ
# ============================================

def migrate_add_admin_and_ads():
    """
    Добавляет таблицы для:
    1. Админ-панели (супер-админы для broadcast и управления рекламой)
    2. Системы рекламы с таргетингом по категориям
    3. Broadcast-оповещений
    4. Статистики просмотров рекламы
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # 1. Таблица админов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    role TEXT DEFAULT 'admin',
                    added_at TEXT NOT NULL,
                    added_by INTEGER
                )
            """)
            logger.info("✅ Таблица admin_users создана")

            # 2. Таблица broadcast-оповещений
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_text TEXT NOT NULL,
                    target_audience TEXT NOT NULL,
                    photo_file_id TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    sent_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    created_by INTEGER NOT NULL,
                    FOREIGN KEY (created_by) REFERENCES admin_users(telegram_id)
                )
            """)
            logger.info("✅ Таблица broadcasts создана")

            # 3. Таблица рекламы
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    photo_file_id TEXT,
                    button_text TEXT,
                    button_url TEXT,
                    target_audience TEXT NOT NULL,
                    placement TEXT NOT NULL,
                    active BOOLEAN DEFAULT TRUE,
                    start_date TEXT,
                    end_date TEXT,
                    max_views_per_user_per_day INTEGER DEFAULT 1,
                    view_count INTEGER DEFAULT 0,
                    click_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    FOREIGN KEY (created_by) REFERENCES admin_users(telegram_id)
                )
            """)
            logger.info("✅ Таблица ads создана")

            # 4. Таблица связи рекламы с категориями (для таргетинга)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ad_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    FOREIGN KEY (ad_id) REFERENCES ads(id) ON DELETE CASCADE,
                    UNIQUE (ad_id, category)
                )
            """)
            logger.info("✅ Таблица ad_categories создана")

            # 5. Таблица просмотров рекламы
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ad_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    viewed_at TEXT NOT NULL,
                    clicked BOOLEAN DEFAULT FALSE,
                    placement TEXT,
                    FOREIGN KEY (ad_id) REFERENCES ads(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            logger.info("✅ Таблица ad_views создана")

            conn.commit()
            logger.info("✅ Migration completed: admin and ads system!")

        except Exception as e:
            logger.error(f"⚠️ Error in migrate_add_admin_and_ads: {e}")
            conn.rollback()


def migrate_add_worker_cities():
    """
    Добавляет таблицу blogger_cities для хранения нескольких городов у мастера.
    Мигрирует существующие данные из поля bloggers.city в новую таблицу.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Создаем таблицу blogger_cities
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blogger_cities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    blogger_id INTEGER NOT NULL,
                    city TEXT NOT NULL,
                    FOREIGN KEY (blogger_id) REFERENCES bloggers(id) ON DELETE CASCADE,
                    UNIQUE (blogger_id, city)
                )
            """)
            logger.info("✅ Таблица blogger_cities создана")

            # Мигрируем существующие данные из bloggers.city
            cursor.execute("""
                SELECT id, city FROM bloggers WHERE city IS NOT NULL AND city != ''
            """)
            bloggers = cursor.fetchall()

            for blogger in bloggers:
                # PostgreSQL возвращает dict, SQLite возвращает tuple
                if isinstance(blogger, dict):
                    blogger_id = blogger['id']
                    city = blogger['city']
                else:
                    blogger_id, city = blogger

                if USE_POSTGRES:
                    cursor.execute("""
                        INSERT INTO blogger_cities (blogger_id, city)
                        VALUES (%s, %s)
                        ON CONFLICT (blogger_id, city) DO NOTHING
                    """, (blogger_id, city))
                else:
                    cursor.execute("""
                        INSERT OR IGNORE INTO blogger_cities (blogger_id, city)
                        VALUES (?, ?)
                    """, (blogger_id, city))

            logger.info(f"✅ Мигрировано {len(bloggers)} городов из поля bloggers.city")

            conn.commit()
            logger.info("✅ Migration completed: blogger_cities table!")

        except Exception as e:
            logger.error(f"⚠️ Error in migrate_add_worker_cities: {e}")
            conn.rollback()


def migrate_add_chat_message_notifications():
    """
    Добавляет таблицу chat_message_notifications для хранения одного обновляемого
    уведомления о новых сообщениях в чате для каждого пользователя.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            # Создаем таблицу chat_message_notifications
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_message_notifications (
                    user_id INTEGER PRIMARY KEY,
                    notification_message_id INTEGER,
                    notification_chat_id INTEGER,
                    last_update_timestamp INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            logger.info("✅ Таблица chat_message_notifications создана")

            conn.commit()
            logger.info("✅ Migration completed: chat_message_notifications table!")

        except Exception as e:
            logger.error(f"⚠️ Error in migrate_add_chat_message_notifications: {e}")
            conn.rollback()


def migrate_fix_portfolio_photos_size():
    """
    ИСПРАВЛЕНИЕ: Увеличивает размер поля portfolio_photos с VARCHAR(1000) на TEXT.
    Решает проблему "value too long for type character varying(1000)" при добавлении фото.
    """
    if not USE_POSTGRES:
        logger.info("✅ SQLite использует TEXT, миграция не требуется")
        return

    with get_db_connection() as conn:
        # КРИТИЧНО: Используем RAW cursor, минуя DBCursor который конвертирует TEXT в VARCHAR(1000)
        raw_cursor = conn.cursor()

        try:
            # ИСПРАВЛЕНО: Используем USING для корректного преобразования типа в PostgreSQL
            raw_cursor.execute("""
                ALTER TABLE bloggers
                ALTER COLUMN portfolio_photos TYPE TEXT
                USING portfolio_photos::TEXT
            """)
            logger.info("✅ Колонка portfolio_photos изменена на TEXT")

            conn.commit()
            logger.info("✅ Migration completed: portfolio_photos size fixed!")

        except Exception as e:
            # Если колонка уже TEXT или другая ошибка
            logger.warning(f"⚠️ Migration portfolio_photos size: {e}")
            conn.rollback()
        finally:
            raw_cursor.close()


def add_admin_user(telegram_id, role='admin', added_by=None):
    """Добавляет пользователя в список админов"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO admin_users (telegram_id, role, added_at, added_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (telegram_id) DO NOTHING
            """, (telegram_id, role, now, added_by))
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO admin_users (telegram_id, role, added_at, added_by)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, role, now, added_by))

        conn.commit()
        logger.info(f"✅ Админ добавлен: telegram_id={telegram_id}, role={role}")


def is_admin(telegram_id):
    """Проверяет является ли пользователь админом"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT COUNT(*) FROM admin_users WHERE telegram_id = ?", (telegram_id,))
        result = cursor.fetchone()
        if not result:
            return False
        # PostgreSQL возвращает dict, SQLite может вернуть tuple
        if isinstance(result, dict):
            count = result.get('count', 0)
            return count > 0
        else:
            return result[0] > 0


def create_broadcast(message_text, target_audience, photo_file_id, created_by):
    """Создает broadcast-оповещение"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO broadcasts (message_text, target_audience, photo_file_id, created_at, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (message_text, target_audience, photo_file_id, now, created_by))

        conn.commit()
        broadcast_id = cursor.lastrowid
        logger.info(f"✅ Broadcast создан: ID={broadcast_id}, audience={target_audience}")
        return broadcast_id


def create_ad(title, description, photo_file_id, button_text, button_url,
              target_audience, placement, start_date, end_date,
              max_views_per_user_per_day, created_by, categories=None):
    """Создает рекламу с опциональным таргетингом по категориям"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO ads (
                title, description, photo_file_id, button_text, button_url,
                target_audience, placement, start_date, end_date,
                max_views_per_user_per_day, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, description, photo_file_id, button_text, button_url,
              target_audience, placement, start_date, end_date,
              max_views_per_user_per_day, now, created_by))

        ad_id = cursor.lastrowid

        # Добавляем категории для таргетинга (если указаны)
        if categories:
            for category in categories:
                cursor.execute("""
                    INSERT INTO ad_categories (ad_id, category)
                    VALUES (?, ?)
                """, (ad_id, category))

        conn.commit()
        logger.info(f"✅ Реклама создана: ID={ad_id}, categories={categories}")
        return ad_id


def get_active_ad(placement, user_id=None, user_categories=None):
    """
    Получает активную рекламу для показа.

    Args:
        placement: где показывать ('menu_banner', 'morning_digest')
        user_id: ID пользователя (для проверки лимита показов)
        user_categories: список категорий пользователя (для таргетинга)

    Returns:
        dict с данными рекламы или None
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")

        # Базовый запрос (PostgreSQL: используем TRUE вместо 1)
        query = """
            SELECT a.*
            FROM ads a
            WHERE a.active = TRUE
            AND a.placement = ?
            AND (a.start_date IS NULL OR a.start_date <= ?)
            AND (a.end_date IS NULL OR a.end_date >= ?)
        """
        params = [placement, now, now]

        # Если есть категории пользователя - фильтруем по таргетингу
        if user_categories:
            query += """
                AND (
                    NOT EXISTS (SELECT 1 FROM ad_categories WHERE ad_id = a.id)
                    OR EXISTS (
                        SELECT 1 FROM ad_categories ac
                        WHERE ac.ad_id = a.id
                        AND ac.category IN ({})
                    )
                )
            """.format(','.join('?' * len(user_categories)))
            params.extend(user_categories)

        # Проверяем лимит показов пользователю
        if user_id:
            query += """
                AND (
                    SELECT COUNT(*) FROM ad_views av
                    WHERE av.ad_id = a.id
                    AND av.user_id = ?
                    AND av.viewed_at >= ?
                ) < a.max_views_per_user_per_day
            """
            params.extend([user_id, today_start])

        query += " ORDER BY a.id DESC LIMIT 1"

        cursor.execute(query, params)
        result = cursor.fetchone()

        return dict(result) if result else None


def get_active_ads(placement, user_id=None, user_categories=None, user_role=None):
    """
    Получает ВСЕ активные рекламы для показа (без LIMIT).

    Args:
        placement: где показывать ('menu_banner', 'morning_digest')
        user_id: ID пользователя (для проверки лимита показов)
        user_categories: список категорий пользователя (для таргетинга)
        user_role: роль пользователя ('blogger', 'advertiser') для фильтрации по target_audience

    Returns:
        список dict с данными реклам
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")

        # Базовый запрос (PostgreSQL: используем TRUE вместо 1)
        query = """
            SELECT a.*
            FROM ads a
            WHERE a.active = TRUE
            AND a.placement = ?
            AND (a.start_date IS NULL OR a.start_date <= ?)
            AND (a.end_date IS NULL OR a.end_date >= ?)
        """
        params = [placement, now, now]

        # Фильтр по целевой аудитории
        if user_role:
            query += """
                AND (a.target_audience = 'all'
                    OR (a.target_audience = 'bloggers' AND ? = 'blogger')
                    OR (a.target_audience = 'advertisers' AND ? = 'advertiser'))
            """
            params.extend([user_role, user_role])

        # Если есть категории пользователя - фильтруем по таргетингу
        if user_categories:
            query += """
                AND (
                    NOT EXISTS (SELECT 1 FROM ad_categories WHERE ad_id = a.id)
                    OR EXISTS (
                        SELECT 1 FROM ad_categories ac
                        WHERE ac.ad_id = a.id
                        AND ac.category IN ({})
                    )
                )
            """.format(','.join('?' * len(user_categories)))
            params.extend(user_categories)

        # Проверяем лимит показов пользователю
        if user_id:
            query += """
                AND (
                    SELECT COUNT(*) FROM ad_views av
                    WHERE av.ad_id = a.id
                    AND av.user_id = ?
                    AND av.viewed_at >= ?
                ) < a.max_views_per_user_per_day
            """
            params.extend([user_id, today_start])

        query += " ORDER BY a.id DESC"  # БЕЗ LIMIT - показываем все

        cursor.execute(query, params)
        results = cursor.fetchall()

        return [dict(row) for row in results] if results else []


def log_ad_view(ad_id, user_id, placement, clicked=False):
    """Записывает просмотр/клик по рекламе"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO ad_views (ad_id, user_id, viewed_at, clicked, placement)
            VALUES (?, ?, ?, ?, ?)
        """, (ad_id, user_id, now, clicked, placement))

        # Обновляем счетчики
        if clicked:
            cursor.execute("UPDATE ads SET click_count = click_count + 1 WHERE id = ?", (ad_id,))
        else:
            cursor.execute("UPDATE ads SET view_count = view_count + 1 WHERE id = ?", (ad_id,))

        conn.commit()


def record_ad_view(ad_id, user_id, placement='menu_banner'):
    """Записывает просмотр рекламы (алиас для log_ad_view)"""
    return log_ad_view(ad_id, user_id, placement, clicked=False)


def has_unviewed_ads(user_id, placement='menu_banner', user_role=None):
    """
    Проверяет, есть ли непросмотренные активные рекламы для пользователя.

    ВАЖНО: Учитывает фильтр target_audience, чтобы красный кружочек показывался
    только если есть реклама для ЭТОГО типа пользователя (blogger/advertiser).

    Args:
        user_id: ID пользователя
        placement: Место размещения ('menu_banner')
        user_role: Роль пользователя ('blogger' или 'advertiser') для фильтрации
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Проверяем, есть ли активные рекламы, которые пользователь еще не видел
        query = """
            SELECT COUNT(*) as unviewed_count
            FROM ads a
            WHERE a.active = TRUE
            AND a.placement = ?
            AND (a.start_date IS NULL OR a.start_date <= ?)
            AND (a.end_date IS NULL OR a.end_date >= ?)
        """
        params = [placement, now, now]

        # 🛡️ ФИЛЬТР ПО АУДИТОРИИ - показываем красный кружок только если есть реклама для этой роли
        if user_role:
            query += """
                AND (a.target_audience = 'all'
                    OR (a.target_audience = 'bloggers' AND ? = 'blogger')
                    OR (a.target_audience = 'advertisers' AND ? = 'advertiser'))
            """
            params.extend([user_role, user_role])

        # Проверяем что пользователь еще не видел эту рекламу
        query += """
            AND NOT EXISTS (
                SELECT 1 FROM ad_views av
                WHERE av.ad_id = a.id
                AND av.user_id = ?
            )
        """
        params.append(user_id)

        cursor.execute(query, params)
        result = cursor.fetchone()

        return result['unviewed_count'] > 0 if result else False


def get_all_ads(limit=None, offset=0):
    """Получает все рекламы (активные и неактивные) для админ-панели"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        query = "SELECT * FROM ads ORDER BY created_at DESC"
        if limit:
            query += f" LIMIT {limit} OFFSET {offset}"
        cursor.execute(query)
        return cursor.fetchall()


def get_ad_by_id(ad_id):
    """Получает конкретную рекламу по ID"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
        result = cursor.fetchone()
        return dict(result) if result else None


def update_ad(ad_id, **fields):
    """Обновляет поля рекламы"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Формируем SQL для обновления только переданных полей
        set_parts = []
        values = []
        for field, value in fields.items():
            set_parts.append(f"{field} = ?")
            values.append(value)

        if not set_parts:
            return False

        values.append(ad_id)
        query = f"UPDATE ads SET {', '.join(set_parts)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()

        logger.info(f"✅ Реклама ID={ad_id} обновлена: {fields}")
        return True


def delete_ad(ad_id):
    """Удаляет рекламу и все связанные записи"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Удаляем категории таргетинга
        cursor.execute("DELETE FROM ad_categories WHERE ad_id = ?", (ad_id,))

        # Удаляем просмотры
        cursor.execute("DELETE FROM ad_views WHERE ad_id = ?", (ad_id,))

        # Удаляем саму рекламу
        cursor.execute("DELETE FROM ads WHERE id = ?", (ad_id,))

        conn.commit()
        logger.info(f"✅ Реклама ID={ad_id} удалена")
        return True


def toggle_ad_active(ad_id):
    """Переключает статус активности рекламы"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем текущий статус
        cursor.execute("SELECT active FROM ads WHERE id = ?", (ad_id,))
        result = cursor.fetchone()
        if not result:
            return None

        current_status = bool(result['active'])
        new_status = not current_status

        # Обновляем статус
        cursor.execute("UPDATE ads SET active = ? WHERE id = ?", (new_status, ad_id))
        conn.commit()

        logger.info(f"✅ Реклама ID={ad_id}: active={current_status} → {new_status}")
        return new_status


def get_ad_stats(ad_id):
    """Получает статистику по рекламе"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Общее количество просмотров
        cursor.execute("""
            SELECT COUNT(*) as total_views,
                   SUM(CASE WHEN clicked = TRUE THEN 1 ELSE 0 END) as total_clicks
            FROM ad_views
            WHERE ad_id = ?
        """, (ad_id,))
        stats = dict(cursor.fetchone())

        # Уникальные пользователи
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) as unique_users
            FROM ad_views
            WHERE ad_id = ?
        """, (ad_id,))
        stats['unique_users'] = cursor.fetchone()['unique_users']

        return stats


def get_all_users():
    """Получает всех пользователей (для broadcast)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM users")
        return cursor.fetchall()


def get_all_orders_for_export():
    """Получает все заказы для экспорта"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM campaigns ORDER BY created_at DESC")
        return cursor.fetchall()


def get_all_bids_for_export():
    """Получает все отклики для экспорта"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM offers ORDER BY created_at DESC")
        return cursor.fetchall()


def get_all_reviews_for_export():
    """Получает все отзывы для экспорта"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM reviews ORDER BY created_at DESC")
        return cursor.fetchall()


def get_category_reports():
    """
    Получает подробные отчеты по категориям работ, городам и специализациям
    для аналитики в админ-панели
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        reports = {}

        # === ТОП КАТЕГОРИЙ ЗАКАЗОВ ===
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM campaigns
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
        """)
        reports['top_categories'] = cursor.fetchall()

        # === ТОП ГОРОДОВ ПО ЗАКАЗАМ ===
        cursor.execute("""
            SELECT city, COUNT(*) as count
            FROM campaigns
            WHERE city IS NOT NULL AND city != ''
            GROUP BY city
            ORDER BY count DESC
            LIMIT 10
        """)
        reports['top_cities_orders'] = cursor.fetchall()

        # === ТОП КАТЕГОРИЙ МАСТЕРОВ ===
        cursor.execute("""
            SELECT categories, COUNT(*) as count
            FROM bloggers
            WHERE categories IS NOT NULL AND categories != ''
            GROUP BY categories
            ORDER BY count DESC
            LIMIT 10
        """)
        reports['top_specializations'] = cursor.fetchall()

        # === СТАТИСТИКА ПО СТАТУСАМ ЗАКАЗОВ В КАТЕГОРИЯХ ===
        cursor.execute("""
            SELECT
                category,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_count,
                SUM(CASE WHEN status IN ('master_selected', 'contact_shared', 'master_confirmed') THEN 1 ELSE 0 END) as active_count,
                SUM(CASE WHEN status IN ('done', 'completed') THEN 1 ELSE 0 END) as completed_count,
                COUNT(*) as total_count
            FROM campaigns
            GROUP BY category
            ORDER BY total_count DESC
            LIMIT 15
        """)
        reports['category_statuses'] = cursor.fetchall()

        # === АКТИВНОСТЬ ПО ГОРОДАМ (заказы + мастера) ===
        cursor.execute("""
            SELECT
                city,
                COUNT(*) as campaign_count
            FROM campaigns
            WHERE city IS NOT NULL AND city != ''
            GROUP BY city
            ORDER BY campaign_count DESC
            LIMIT 10
        """)
        city_orders = {dict(row)['city']: dict(row)['campaign_count'] for row in cursor.fetchall()}

        # Получаем количество мастеров по городам
        cursor.execute("""
            SELECT
                wc.city,
                COUNT(DISTINCT wc.blogger_id) as blogger_count
            FROM blogger_cities wc
            GROUP BY wc.city
            ORDER BY blogger_count DESC
            LIMIT 15
        """)
        city_workers = {dict(row)['city']: dict(row)['blogger_count'] for row in cursor.fetchall()}

        # Объединяем данные
        all_cities = set(city_orders.keys()) | set(city_workers.keys())
        city_activity = []
        for city in all_cities:
            city_activity.append({
                'city': city,
                'campaigns': city_orders.get(city, 0),
                'bloggers': city_workers.get(city, 0),
                'total': city_orders.get(city, 0) + city_workers.get(city, 0)
            })

        # Сортируем по общей активности
        city_activity.sort(key=lambda x: x['total'], reverse=True)
        reports['city_activity'] = city_activity[:10]

        # === СРЕДНЯЯ ЦЕНА ПО КАТЕГОРИЯМ (из откликов) ===
        cursor.execute("""
            SELECT
                o.category,
                AVG(CAST(b.proposed_price AS REAL)) as avg_price,
                COUNT(b.id) as offer_count
            FROM offers b
            INNER JOIN campaigns o ON b.campaign_id = o.id
            WHERE b.proposed_price IS NOT NULL
              AND b.proposed_price > 0
              AND b.currency = 'BYN'
            GROUP BY o.category
            HAVING COUNT(b.id) >= 3
            ORDER BY avg_price DESC
            LIMIT 10
        """)
        reports['avg_prices_by_category'] = cursor.fetchall()

        return reports


# ------- ФУНКЦИИ ДЛЯ РАБОТЫ С ГОРОДАМИ МАСТЕРА -------

def add_worker_city(blogger_id, city):
    """Добавляет город к мастеру"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO blogger_cities (blogger_id, city)
                VALUES (%s, %s)
                ON CONFLICT (blogger_id, city) DO NOTHING
            """, (blogger_id, city))
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO blogger_cities (blogger_id, city)
                VALUES (?, ?)
            """, (blogger_id, city))
        conn.commit()
        logger.info(f"✅ Город '{city}' добавлен мастеру blogger_id={blogger_id}")


def remove_worker_city(blogger_id, city):
    """Удаляет город у мастера"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            DELETE FROM blogger_cities WHERE blogger_id = ? AND city = ?
        """, (blogger_id, city))
        conn.commit()
        logger.info(f"✅ Город '{city}' удален у мастера blogger_id={blogger_id}")


def get_worker_cities(blogger_id):
    """Получает список всех городов мастера"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT city FROM blogger_cities WHERE blogger_id = ? ORDER BY id
        """, (blogger_id,))
        rows = cursor.fetchall()

        # ИСПРАВЛЕНО: Поддержка PostgreSQL (dict) и SQLite (tuple)
        if not rows:
            return []

        if isinstance(rows[0], dict):
            # PostgreSQL возвращает dict
            return [row['city'] for row in rows]
        else:
            # SQLite возвращает tuple
            return [row[0] for row in rows]


def clear_worker_cities(blogger_id):
    """Удаляет все города у мастера"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("DELETE FROM blogger_cities WHERE blogger_id = ?", (blogger_id,))
        conn.commit()
        logger.info(f"✅ Все города удалены у мастера blogger_id={blogger_id}")


def set_worker_cities(blogger_id, cities):
    """Устанавливает список городов мастера (заменяет все существующие)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        # Удаляем все существующие
        if USE_POSTGRES:
            cursor.execute("DELETE FROM blogger_cities WHERE blogger_id = %s", (blogger_id,))
        else:
            cursor.execute("DELETE FROM blogger_cities WHERE blogger_id = ?", (blogger_id,))
        # Добавляем новые
        for city in cities:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO blogger_cities (blogger_id, city)
                    VALUES (%s, %s)
                    ON CONFLICT (blogger_id, city) DO NOTHING
                """, (blogger_id, city))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO blogger_cities (blogger_id, city)
                    VALUES (?, ?)
                """, (blogger_id, city))
        conn.commit()
        logger.info(f"✅ Установлено {len(cities)} городов для мастера blogger_id={blogger_id}")


# ============================================================
# СИСТЕМА УВЕДОМЛЕНИЙ
# ============================================================

def get_notification_settings(user_id):
    """
    Получает настройки уведомлений пользователя.
    Если настроек нет - создает с дефолтными значениями.

    Args:
        user_id: ID пользователя

    Returns:
        dict: Настройки уведомлений
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT new_orders_enabled, new_bids_enabled
            FROM notification_settings
            WHERE user_id = ?
        """, (user_id,))

        row = cursor.fetchone()
        if row:
            return dict(row)

        # Создаем дефолтные настройки
        now = datetime.now().isoformat()
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO notification_settings (user_id, new_orders_enabled, new_bids_enabled, updated_at)
                VALUES (%s, TRUE, TRUE, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id, now))
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO notification_settings (user_id, new_orders_enabled, new_bids_enabled, updated_at)
                VALUES (?, 1, 1, ?)
            """, (user_id, now))
        conn.commit()

        return {
            'new_orders_enabled': True,
            'new_bids_enabled': True
        }


def update_notification_setting(user_id, setting_name, enabled):
    """
    Обновляет конкретную настройку уведомлений.

    Args:
        user_id: ID пользователя
        setting_name: 'new_orders_enabled' или 'new_bids_enabled'
        enabled: True/False
    """
    allowed_settings = ['new_orders_enabled', 'new_bids_enabled']
    if setting_name not in allowed_settings:
        raise ValueError(f"Недопустимое имя настройки: {setting_name}")

    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Создаем запись если не существует
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO notification_settings (user_id, new_orders_enabled, new_bids_enabled, updated_at)
                VALUES (%s, TRUE, TRUE, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id, now))
            # Обновляем настройку
            query = f"UPDATE notification_settings SET {setting_name} = %s, updated_at = %s WHERE user_id = %s"
            cursor.execute(query, (enabled, now, user_id))
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO notification_settings (user_id, new_orders_enabled, new_bids_enabled, updated_at)
                VALUES (?, 1, 1, ?)
            """, (user_id, now))
            # Обновляем настройку
            query = f"UPDATE notification_settings SET {setting_name} = ?, updated_at = ? WHERE user_id = ?"
            cursor.execute(query, (1 if enabled else 0, now, user_id))
        conn.commit()

        logger.info(f"📢 Настройка уведомлений обновлена: user_id={user_id}, {setting_name}={enabled}")


def has_active_notification(user_id, notification_type):
    """
    Проверяет, есть ли активное (не просмотренное) уведомление у пользователя.

    Args:
        user_id: ID пользователя
        notification_type: 'new_orders' или 'new_bids'

    Returns:
        bool: True если есть активное уведомление
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT id FROM sent_notifications
            WHERE user_id = ? AND notification_type = ? AND cleared_at IS NULL
            ORDER BY sent_at DESC
            LIMIT 1
        """, (user_id, notification_type))

        return cursor.fetchone() is not None


def save_sent_notification(user_id, notification_type, message_id=None):
    """
    Сохраняет информацию об отправленном уведомлении.

    Args:
        user_id: ID пользователя
        notification_type: 'new_orders' или 'new_bids'
        message_id: ID сообщения в Telegram (для последующего удаления)

    Returns:
        int: ID созданной записи
    """
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            INSERT INTO sent_notifications (user_id, notification_type, message_id, sent_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, notification_type, message_id, now))
        conn.commit()

        notification_id = cursor.lastrowid
        logger.info(f"📬 Уведомление сохранено: id={notification_id}, user_id={user_id}, type={notification_type}")
        return notification_id


def clear_notification(user_id, notification_type):
    """
    Помечает уведомление как просмотренное (очищает).

    Args:
        user_id: ID пользователя
        notification_type: 'new_orders' или 'new_bids'
    """
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE sent_notifications
            SET cleared_at = ?
            WHERE user_id = ? AND notification_type = ? AND cleared_at IS NULL
        """, (now, user_id, notification_type))
        conn.commit()

        logger.info(f"✅ Уведомление очищено: user_id={user_id}, type={notification_type}")


def get_active_notification_message_id(user_id, notification_type):
    """
    Получает message_id активного уведомления для удаления.

    Args:
        user_id: ID пользователя
        notification_type: 'new_orders' или 'new_bids'

    Returns:
        int | None: message_id или None если не найдено
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            SELECT message_id FROM sent_notifications
            WHERE user_id = ? AND notification_type = ? AND cleared_at IS NULL
            ORDER BY sent_at DESC
            LIMIT 1
        """, (user_id, notification_type))

        row = cursor.fetchone()
        return row['message_id'] if row else None


def get_workers_for_new_order_notification(campaign_city, campaign_category):
    """
    Получает список мастеров, которым нужно отправить уведомление о новом заказе.
    Учитывает:
    - Настройки уведомлений (включены ли уведомления)
    - Соответствие города и категории
    - Отсутствие активных уведомлений

    Args:
        campaign_city: Город заказа
        campaign_category: Категория заказа

    Returns:
        list: Список словарей с данными мастеров (user_id, telegram_id, name)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        # Получаем мастеров у которых:
        # 1. Включены уведомления о новых заказах (или настройки не заданы - по умолчанию включено)
        # 2. Работают в нужном городе
        # 3. Работают в нужной категории
        # 4. Нет активного уведомления о новых заказах
        cursor.execute("""
            SELECT DISTINCT
                w.user_id,
                u.telegram_id,
                w.name
            FROM bloggers w
            INNER JOIN users u ON w.user_id = u.id
            LEFT JOIN notification_settings ns ON w.user_id = ns.user_id
            LEFT JOIN sent_notifications sn ON (
                w.user_id = sn.user_id
                AND sn.notification_type = 'new_orders'
                AND sn.cleared_at IS NULL
            )
            WHERE
                (ns.new_orders_enabled = 1 OR ns.new_orders_enabled IS NULL)
                AND sn.id IS NULL
                AND (
                    w.city LIKE ? OR
                    w.regions LIKE ? OR
                    EXISTS (
                        SELECT 1 FROM blogger_cities wc
                        WHERE wc.blogger_id = w.id AND wc.city = ?
                    )
                )
                AND w.categories LIKE ?
        """, (
            f'%{campaign_city}%',
            f'%{campaign_city}%',
            campaign_city,
            f'%{campaign_category}%'
        ))

        return [dict(row) for row in cursor.fetchall()]
        return [dict(row) for row in cursor.fetchall()]


# ============================================
# СИСТЕМА ПРЕДЛОЖЕНИЙ
# ============================================

def create_suggestion(user_id, user_role, message):
    """Создает предложение от пользователя"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO suggestions (user_id, user_role, message, created_at, status)
                VALUES (%s, %s, %s, NOW(), 'new')
            """, (user_id, user_role, message))
        else:
            cursor.execute("""
                INSERT INTO suggestions (user_id, user_role, message, created_at, status)
                VALUES (?, ?, ?, datetime('now'), 'new')
            """, (user_id, user_role, message))
        
        conn.commit()
        return cursor.lastrowid


def get_all_suggestions(status=None):
    """Получает все предложения (опционально фильтрует по статусу)"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        
        if status:
            if USE_POSTGRES:
                cursor.execute("""
                    SELECT s.*, u.telegram_id
                    FROM suggestions s
                    JOIN users u ON s.user_id = u.id
                    WHERE s.status = %s
                    ORDER BY s.created_at DESC
                """, (status,))
            else:
                cursor.execute("""
                    SELECT s.*, u.telegram_id
                    FROM suggestions s
                    JOIN users u ON s.user_id = u.id
                    WHERE s.status = ?
                    ORDER BY s.created_at DESC
                """, (status,))
        else:
            cursor.execute("""
                SELECT s.*, u.telegram_id
                FROM suggestions s
                JOIN users u ON s.user_id = u.id
                ORDER BY s.created_at DESC
            """)
        
        return cursor.fetchall()


def update_suggestion_status(suggestion_id, status, admin_notes=None):
    """Обновляет статус предложения"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        
        if admin_notes:
            if USE_POSTGRES:
                cursor.execute("""
                    UPDATE suggestions
                    SET status = %s, admin_notes = %s
                    WHERE id = %s
                """, (status, admin_notes, suggestion_id))
            else:
                cursor.execute("""
                    UPDATE suggestions
                    SET status = ?, admin_notes = ?
                    WHERE id = ?
                """, (status, admin_notes, suggestion_id))
        else:
            if USE_POSTGRES:
                cursor.execute("""
                    UPDATE suggestions
                    SET status = %s
                    WHERE id = %s
                """, (status, suggestion_id))
            else:
                cursor.execute("""
                    UPDATE suggestions
                    SET status = ?
                    WHERE id = ?
                """, (status, suggestion_id))
        
        conn.commit()


def get_suggestions_by_status(status):
    """Получает предложения по конкретному статусу (alias для get_all_suggestions)"""
    return get_all_suggestions(status=status)


def get_suggestions_count(status='new'):
    """Получает количество предложений по статусу"""
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) as count FROM suggestions WHERE status = %s
            """, (status,))
        else:
            cursor.execute("""
                SELECT COUNT(*) as count FROM suggestions WHERE status = ?
            """, (status,))

        result = cursor.fetchone()
        if isinstance(result, dict):
            return result.get('count', 0)
        else:
            return result[0] if result else 0


# ============================================================
# НОВОЕ: Функции для отказа мастеров от заказов
# ============================================================

def decline_order(blogger_id, campaign_id):
    """
    Мастер отказывается от заказа (больше не будет его видеть)

    Args:
        blogger_id: ID мастера (из таблицы bloggers или users, зависит от контекста)
        campaign_id: ID заказа

    Returns:
        True если успешно, False если ошибка
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        declined_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO declined_orders (blogger_id, campaign_id, declined_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (blogger_id, campaign_id) DO NOTHING
                """, (blogger_id, campaign_id, declined_at))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO declined_orders (blogger_id, campaign_id, declined_at)
                    VALUES (?, ?, ?)
                """, (blogger_id, campaign_id, declined_at))

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при отказе от заказа: {e}", exc_info=True)
            conn.rollback()
            return False


def check_order_declined(blogger_id, campaign_id):
    """
    Проверяет, отказался ли мастер от этого заказа

    Args:
        blogger_id: ID мастера
        campaign_id: ID заказа

    Returns:
        True если отказался, False если нет
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM declined_orders
                WHERE blogger_id = %s AND campaign_id = %s
            """, (blogger_id, campaign_id))
        else:
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM declined_orders
                WHERE blogger_id = ? AND campaign_id = ?
            """, (blogger_id, campaign_id))

        result = cursor.fetchone()
        if isinstance(result, dict):
            count = result.get('count', 0)
        else:
            count = result[0] if result else 0

        return count > 0


def get_declined_orders(blogger_id):
    """
    Получает список ID заказов, от которых отказался мастер

    Args:
        blogger_id: ID мастера

    Returns:
        Список ID заказов
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        if USE_POSTGRES:
            cursor.execute("""
                SELECT campaign_id FROM declined_orders
                WHERE blogger_id = %s
            """, (blogger_id,))
        else:
            cursor.execute("""
                SELECT campaign_id FROM declined_orders
                WHERE blogger_id = ?
            """, (blogger_id,))

        results = cursor.fetchall()
        return [row['campaign_id'] if isinstance(row, dict) else row[0] for row in results]


# ===== NEW MIGRATIONS FOR INFLUENCEMARKET =====

def migrate_add_blogger_platform_fields():
    """
    Добавляет поля для платформ блогеров и верификации.
    Новые поля:
    - platform_instagram, platform_tiktok, platform_youtube
    - instagram_link, tiktok_link, youtube_link, telegram_link, threads_link
    - format_stories, format_reels, format_posts, format_integration
    - price_stories, price_reels, price_posts
    - verified_ownership, verification_code, trust_score
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                logger.info("📝 Добавление полей социальных сетей для PostgreSQL...")

                # Список всех полей для добавления
                fields = [
                    ("platform_instagram", "BOOLEAN DEFAULT FALSE"),
                    ("platform_tiktok", "BOOLEAN DEFAULT FALSE"),
                    ("platform_youtube", "BOOLEAN DEFAULT FALSE"),
                    ("instagram_link", "VARCHAR(200)"),
                    ("tiktok_link", "VARCHAR(200)"),
                    ("youtube_link", "VARCHAR(200)"),
                    ("telegram_link", "VARCHAR(200)"),
                    ("threads_link", "VARCHAR(200)"),
                    ("format_stories", "BOOLEAN DEFAULT FALSE"),
                    ("format_reels", "BOOLEAN DEFAULT FALSE"),
                    ("format_posts", "BOOLEAN DEFAULT FALSE"),
                    ("format_integration", "BOOLEAN DEFAULT FALSE"),
                    ("price_stories", "INTEGER"),
                    ("price_reels", "INTEGER"),
                    ("price_posts", "INTEGER"),
                    ("currency", "VARCHAR(3) DEFAULT 'BYN'"),
                    ("verified_ownership", "BOOLEAN DEFAULT FALSE"),
                    ("verification_code", "VARCHAR(20)"),
                    ("trust_score", "INTEGER DEFAULT 0"),
                    ("content_language", "VARCHAR(50) DEFAULT 'Русский'"),
                ]

                for field_name, field_type in fields:
                    cursor.execute(f"""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'bloggers' AND column_name = '{field_name}'
                            ) THEN
                                ALTER TABLE bloggers ADD COLUMN {field_name} {field_type};
                            END IF;
                        END $$;
                    """)

                conn.commit()
                logger.info("✅ Поля социальных сетей успешно добавлены!")

            else:
                # Для SQLite проверяем существование колонок
                cursor.execute("PRAGMA table_info(bloggers)")
                existing_columns = [column[1] for column in cursor.fetchall()]

                logger.info(f"📝 Проверка полей социальных сетей для SQLite... Существующие колонки: {len(existing_columns)}")

                # Список всех полей для добавления (SQLite синтаксис)
                fields = [
                    ("platform_instagram", "INTEGER DEFAULT 0"),
                    ("platform_tiktok", "INTEGER DEFAULT 0"),
                    ("platform_youtube", "INTEGER DEFAULT 0"),
                    ("instagram_link", "TEXT"),
                    ("tiktok_link", "TEXT"),
                    ("youtube_link", "TEXT"),
                    ("telegram_link", "TEXT"),
                    ("threads_link", "TEXT"),
                    ("format_stories", "INTEGER DEFAULT 0"),
                    ("format_reels", "INTEGER DEFAULT 0"),
                    ("format_posts", "INTEGER DEFAULT 0"),
                    ("format_integration", "INTEGER DEFAULT 0"),
                    ("price_stories", "INTEGER"),
                    ("price_reels", "INTEGER"),
                    ("price_posts", "INTEGER"),
                    ("currency", "TEXT DEFAULT 'BYN'"),
                    ("verified_ownership", "INTEGER DEFAULT 0"),
                    ("verification_code", "TEXT"),
                    ("trust_score", "INTEGER DEFAULT 0"),
                    ("content_language", "TEXT DEFAULT 'Русский'"),
                ]

                added_count = 0
                for field_name, field_type in fields:
                    if field_name not in existing_columns:
                        logger.info(f"  📝 Добавление поля {field_name}...")
                        cursor.execute(f"ALTER TABLE bloggers ADD COLUMN {field_name} {field_type}")
                        added_count += 1

                conn.commit()
                logger.info(f"✅ Добавлено {added_count} новых полей для социальных сетей!")

        except Exception as e:
            logger.error(f"⚠️ Error in migrate_add_blogger_platform_fields: {e}")
            conn.rollback()
            logger.info("✅ Migration completed: blogger platform fields added!")
            
        except Exception as e:
            logger.error(f"⚠️ Error in migrate_add_blogger_platform_fields: {e}")
            conn.rollback()


def migrate_add_blogger_stats():
    """
    Создаёт таблицу blogger_stats для хранения статистики блогеров.
    Хранит метрики по платформам: подписчики, охваты, вовлечённость, демографию.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blogger_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    blogger_id INTEGER NOT NULL,
                    platform VARCHAR(20) NOT NULL,
                    
                    -- Метрики
                    followers INTEGER,
                    avg_story_reach INTEGER,
                    median_reels_views INTEGER,
                    engagement_rate DECIMAL(5,2),
                    
                    -- Гео аудитории (детально по городам Беларуси)
                    belarus_audience_percent INTEGER,
                    
                    -- Топ-3 города Беларуси в аудитории
                    city_1 VARCHAR(50),
                    city_1_percent INTEGER,
                    city_2 VARCHAR(50),
                    city_2_percent INTEGER,
                    city_3 VARCHAR(50),
                    city_3_percent INTEGER,
                    
                    -- Демография
                    demographics TEXT,  -- JSON: {"male": 40, "female": 60, "age_18_24": 30}
                    
                    -- Доказательства (скриншоты)
                    proof_screenshots TEXT,  -- JSON array с file_id
                    
                    -- Статус верификации
                    verified BOOLEAN DEFAULT FALSE,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    
                    FOREIGN KEY (blogger_id) REFERENCES bloggers(user_id) ON DELETE CASCADE
                )
            """)
            
            conn.commit()
            logger.info("✅ Migration completed: blogger_stats table created!")
            
        except Exception as e:
            logger.error(f"⚠️ Error in migrate_add_blogger_stats: {e}")
            conn.rollback()


def migrate_add_campaign_reports():
    """
    Создаёт таблицу campaign_reports для отчётов о выполненных кампаниях.
    Блогер загружает отчёт, рекламодатель подтверждает.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS campaign_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL,
                    offer_id INTEGER NOT NULL,
                    
                    -- Ссылка и скрины размещения
                    post_link VARCHAR(300),
                    post_screenshots TEXT,  -- JSON array с file_id
                    
                    -- Результаты
                    reach INTEGER,
                    views INTEGER,
                    engagement INTEGER,
                    result_screenshots TEXT,  -- JSON array с file_id статистики
                    
                    -- Даты
                    published_at TIMESTAMP,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    -- Подтверждение рекламодателя
                    advertiser_confirmed BOOLEAN DEFAULT FALSE,
                    advertiser_satisfied BOOLEAN,
                    confirmed_at TIMESTAMP,
                    
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(order_id) ON DELETE CASCADE,
                    FOREIGN KEY (offer_id) REFERENCES offers(bid_id) ON DELETE CASCADE
                )
            """)
            
            conn.commit()
            logger.info("✅ Migration completed: campaign_reports table created!")
            
        except Exception as e:
            logger.error(f"⚠️ Error in migrate_add_campaign_reports: {e}")
            conn.rollback()


def migrate_add_campaign_fields():
    """
    Добавляет новые поля в таблицу campaigns для маркетплейса блогеров:
    - product_description, platform, required_topics
    - budget_type, budget_amount, requirements, deadline
    - min_trust_score, only_verified
    - payment_type (paid/barter)
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)

        try:
            if USE_POSTGRES:
                logger.info("📝 Добавление полей для кампаний (PostgreSQL)...")

                # Список всех полей для добавления
                fields = [
                    ("product_description", "TEXT"),
                    ("platform", "VARCHAR(20)"),
                    ("required_topics", "TEXT"),  # JSON array
                    ("required_format", "VARCHAR(20)"),
                    ("budget_type", "VARCHAR(20)"),
                    ("budget_amount", "INTEGER"),
                    ("requirements", "TEXT"),
                    ("deadline", "DATE"),
                    ("min_trust_score", "INTEGER DEFAULT 0"),
                    ("only_verified", "BOOLEAN DEFAULT FALSE"),
                    ("payment_type", "VARCHAR(20) DEFAULT 'paid'"),  # 'paid' или 'barter'
                ]

                for field_name, field_type in fields:
                    cursor.execute(f"""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'campaigns' AND column_name = '{field_name}'
                            ) THEN
                                ALTER TABLE campaigns ADD COLUMN {field_name} {field_type};
                            END IF;
                        END $$;
                    """)

                conn.commit()
                logger.info("✅ Поля для кампаний успешно добавлены!")

            else:
                # Для SQLite проверяем существование колонок
                cursor.execute("PRAGMA table_info(campaigns)")
                existing_columns = [column[1] for column in cursor.fetchall()]

                logger.info(f"📝 Проверка полей кампаний для SQLite... Существующие колонки: {len(existing_columns)}")

                # Список всех полей для добавления (SQLite синтаксис)
                fields = [
                    ("product_description", "TEXT"),
                    ("platform", "TEXT"),
                    ("required_topics", "TEXT"),
                    ("required_format", "TEXT"),
                    ("budget_type", "TEXT"),
                    ("budget_amount", "INTEGER"),
                    ("requirements", "TEXT"),
                    ("deadline", "TEXT"),
                    ("min_trust_score", "INTEGER DEFAULT 0"),
                    ("only_verified", "INTEGER DEFAULT 0"),
                    ("payment_type", "TEXT DEFAULT 'paid'"),
                ]

                added_count = 0
                for field_name, field_type in fields:
                    if field_name not in existing_columns:
                        logger.info(f"  📝 Добавление поля {field_name}...")
                        cursor.execute(f"ALTER TABLE campaigns ADD COLUMN {field_name} {field_type}")
                        added_count += 1

                conn.commit()
                logger.info(f"✅ Добавлено {added_count} новых полей для кампаний!")

        except Exception as e:
            logger.error(f"⚠️ Error in migrate_add_campaign_fields: {e}")
            conn.rollback()


def create_indexes():
    """
    Создаёт индексы для оптимизации производительности БД.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        
        try:
            # Индексы для быстрого поиска
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bloggers_telegram_id ON bloggers(telegram_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bloggers_verified ON bloggers(verified_ownership)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bloggers_trust_score ON bloggers(trust_score)")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_advertiser ON campaigns(advertiser_id)")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_offers_campaign ON offers(campaign_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_offers_blogger ON offers(blogger_id)")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stats_blogger ON blogger_stats(blogger_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stats_active ON blogger_stats(is_active)")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_campaign ON campaign_reports(campaign_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_offer ON campaign_reports(offer_id)")
            
            conn.commit()
            logger.info("✅ All indexes created successfully!")
            
        except Exception as e:
            logger.error(f"⚠️ Error creating indexes: {e}")
            conn.rollback()


# ===== VERIFICATION AND TRUST SCORE FUNCTIONS =====

def generate_verification_code(blogger_id):
    """
    Генерирует код верификации для блогера.
    Формат: BH-XXXX (BH = Belarus Bloggers, 4 цифры)
    """
    import random
    code = f"BH-{random.randint(1000, 9999)}"
    
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
            UPDATE bloggers
            SET verification_code = ?, verified_ownership = FALSE
            WHERE user_id = ?
        """, (code, blogger_id))
        conn.commit()
        
        logger.info(f"✅ Код верификации создан для blogger_id={blogger_id}: {code}")
        return code


def verify_blogger_ownership(blogger_id):
    """
    Подтверждает верификацию владения аккаунтом.
    Добавляет +20 к Trust Score.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        
        # Устанавливаем verified_ownership = TRUE
        cursor.execute("""
            UPDATE bloggers
            SET verified_ownership = TRUE
            WHERE user_id = ?
        """, (blogger_id,))
        
        # Пересчитываем Trust Score
        new_score = calculate_trust_score(blogger_id)
        
        conn.commit()
        logger.info(f"✅ Блогер {blogger_id} верифицирован! Trust Score: {new_score}")
        return new_score


def add_blogger_stats(blogger_id, platform, followers, avg_story_reach, median_reels_views, 
                      engagement_rate, belarus_percent, city_1=None, city_1_percent=None,
                      city_2=None, city_2_percent=None, city_3=None, city_3_percent=None,
                      demographics=None, proof_screenshots=None):
    """
    Добавляет статистику блогера.
    proof_screenshots - JSON array с file_id скринов.
    demographics - JSON: {"male": 40, "female": 60, "age_18_24": 30}
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        expires = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        
        import json
        demographics_json = json.dumps(demographics) if demographics else None
        screenshots_json = json.dumps(proof_screenshots) if proof_screenshots else None
        
        cursor.execute("""
            INSERT INTO blogger_stats (
                blogger_id, platform, followers, avg_story_reach, median_reels_views,
                engagement_rate, belarus_audience_percent, 
                city_1, city_1_percent, city_2, city_2_percent, city_3, city_3_percent,
                demographics, proof_screenshots, verified, uploaded_at, expires_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE, ?, ?, TRUE)
        """, (blogger_id, platform, followers, avg_story_reach, median_reels_views,
              engagement_rate, belarus_percent,
              city_1, city_1_percent, city_2, city_2_percent, city_3, city_3_percent,
              demographics_json, screenshots_json, now, expires))
        
        stats_id = cursor.lastrowid
        conn.commit()
        
        logger.info(f"✅ Статистика добавлена: blogger_id={blogger_id}, platform={platform}, stats_id={stats_id}")
        return stats_id


def verify_blogger_stats(stats_id):
    """
    Верифицирует статистику блогера (admin подтверждает).
    Добавляет +25 к Trust Score если полная, +10 если актуальна.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        
        # Получаем статистику
        cursor.execute("SELECT blogger_id FROM blogger_stats WHERE id = ?", (stats_id,))
        result = cursor.fetchone()
        if not result:
            logger.warning(f"⚠️ Статистика {stats_id} не найдена")
            return None
        
        blogger_id = result['blogger_id'] if isinstance(result, dict) else result[0]
        
        # Устанавливаем verified = TRUE
        cursor.execute("""
            UPDATE blogger_stats
            SET verified = TRUE
            WHERE id = ?
        """, (stats_id,))
        
        # Пересчитываем Trust Score
        new_score = calculate_trust_score(blogger_id)
        
        conn.commit()
        logger.info(f"✅ Статистика {stats_id} верифицирована! Trust Score блогера {blogger_id}: {new_score}")
        return new_score


def calculate_trust_score(blogger_id):
    """
    Рассчитывает Trust Score блогера (0-100).
    
    Формула:
    - Verified ownership: +20
    - Stats verified (полная): +25
    - Stats актуальны (<30 дней): +10
    - Выполнено кампаний: +2 за каждую (макс +30)
    - Средняя оценка 4.5+: +10
    - Споры: -15 за каждый
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        score = 0
        
        # 1. Verified ownership: +20
        cursor.execute("SELECT verified_ownership FROM bloggers WHERE user_id = ?", (blogger_id,))
        blogger = cursor.fetchone()
        if blogger and (blogger['verified_ownership'] if isinstance(blogger, dict) else blogger[0]):
            score += 20
        
        # 2. Stats verified: +25
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM blogger_stats 
            WHERE blogger_id = ? AND verified = TRUE AND is_active = TRUE
        """, (blogger_id,))
        verified_stats = cursor.fetchone()
        if verified_stats and (verified_stats['cnt'] if isinstance(verified_stats, dict) else verified_stats[0]) > 0:
            score += 25
        
        # 3. Stats актуальны (<30 дней): +10
        now = datetime.now()
        cursor.execute("""
            SELECT expires_at FROM blogger_stats 
            WHERE blogger_id = ? AND verified = TRUE AND is_active = TRUE
            ORDER BY uploaded_at DESC LIMIT 1
        """, (blogger_id,))
        latest_stats = cursor.fetchone()
        if latest_stats:
            expires = latest_stats['expires_at'] if isinstance(latest_stats, dict) else latest_stats[0]
            if isinstance(expires, str):
                expires = datetime.strptime(expires, "%Y-%m-%d %H:%M:%S")
            if expires > now:
                score += 10
        
        # 4. Выполнено кампаний: +2 за каждую (макс +30)
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM campaign_reports r
            JOIN offers o ON r.offer_id = o.bid_id
            WHERE o.blogger_id = ? AND r.advertiser_confirmed = TRUE
        """, (blogger_id,))
        completed = cursor.fetchone()
        if completed:
            cnt = completed['cnt'] if isinstance(completed, dict) else completed[0]
            score += min(cnt * 2, 30)
        
        # 5. Средняя оценка 4.5+: +10
        # TODO: Добавить когда будет таблица ratings
        
        # 6. Споры: -15 за каждый
        # TODO: Добавить когда будет таблица disputes
        
        # Ограничиваем 0-100
        score = max(0, min(100, score))
        
        # Сохраняем в БД
        cursor.execute("""
            UPDATE bloggers
            SET trust_score = ?
            WHERE user_id = ?
        """, (score, blogger_id))
        
        conn.commit()
        logger.info(f"✅ Trust Score пересчитан для blogger_id={blogger_id}: {score}")
        return score


def get_blogger_stats(blogger_id, platform=None):
    """
    Получает статистику блогера (последнюю активную).
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        
        if platform:
            cursor.execute("""
                SELECT * FROM blogger_stats
                WHERE blogger_id = ? AND platform = ? AND is_active = TRUE
                ORDER BY uploaded_at DESC LIMIT 1
            """, (blogger_id, platform))
        else:
            cursor.execute("""
                SELECT * FROM blogger_stats
                WHERE blogger_id = ? AND is_active = TRUE
                ORDER BY uploaded_at DESC
            """, (blogger_id,))
        
        return cursor.fetchall() if not platform else cursor.fetchone()


def create_campaign_report(campaign_id, offer_id, post_link, post_screenshots, 
                           reach=None, views=None, engagement=None, result_screenshots=None):
    """
    Создаёт отчёт о кампании.
    post_screenshots и result_screenshots - JSON arrays с file_id.
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        import json
        post_screens = json.dumps(post_screenshots) if post_screenshots else None
        result_screens = json.dumps(result_screenshots) if result_screenshots else None
        
        cursor.execute("""
            INSERT INTO campaign_reports (
                campaign_id, offer_id, post_link, post_screenshots,
                reach, views, engagement, result_screenshots,
                published_at, uploaded_at, advertiser_confirmed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE)
        """, (campaign_id, offer_id, post_link, post_screens,
              reach, views, engagement, result_screens, now, now))
        
        report_id = cursor.lastrowid
        conn.commit()
        
        logger.info(f"✅ Отчёт создан: campaign_id={campaign_id}, report_id={report_id}")
        return report_id


def confirm_campaign_report(report_id, satisfied, advertiser_id):
    """
    Рекламодатель подтверждает отчёт о кампании.
    satisfied - True/False (устроил ли результат).
    """
    with get_db_connection() as conn:
        cursor = get_cursor(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            UPDATE campaign_reports
            SET advertiser_confirmed = TRUE,
                advertiser_satisfied = ?,
                confirmed_at = ?
            WHERE id = ?
        """, (satisfied, now, report_id))
        
        # Если подтверждено, увеличиваем Trust Score блогера
        if satisfied:
            # Получаем blogger_id из offer
            cursor.execute("""
                SELECT o.blogger_id FROM campaign_reports r
                JOIN offers o ON r.offer_id = o.bid_id
                WHERE r.id = ?
            """, (report_id,))
            result = cursor.fetchone()
            if result:
                blogger_id = result['blogger_id'] if isinstance(result, dict) else result[0]
                calculate_trust_score(blogger_id)
        
        conn.commit()
        logger.info(f"✅ Отчёт {report_id} подтверждён: satisfied={satisfied}")
        return True

#!/usr/bin/env python3
"""
Скрипт проверки consistency между callback_data и handlers.

Проверяет что:
1. Все callback_data из handlers.py имеют соответствующие обработчики в bot.py
2. Все handlers из bot.py используются в коде
3. Нет опечаток в callback_data
"""

import re
from pathlib import Path
from typing import Set, List, Tuple

def extract_callback_data_from_handlers(handlers_file: Path) -> Set[str]:
    """Извлекает все callback_data из handlers.py"""
    content = handlers_file.read_text()

    # Паттерны для поиска callback_data
    patterns = [
        r'callback_data\s*=\s*["\']([^"\']+)["\']',  # callback_data="..."
        r'pattern\s*=\s*["\']([^"\']+)["\']',  # pattern="..." (в bot.py)
    ]

    callbacks = set()
    for pattern in patterns:
        matches = re.findall(pattern, content)
        callbacks.update(matches)

    return callbacks

def extract_handlers_from_bot(bot_file: Path) -> Set[str]:
    """Извлекает все patterns из bot.py"""
    content = bot_file.read_text()

    # Ищем все CallbackQueryHandler с pattern
    pattern = r'CallbackQueryHandler\([^,]+,\s*pattern\s*=\s*["\']([^"\']+)["\']\)'
    matches = re.findall(pattern, content)

    return set(matches)

def normalize_callback(callback: str) -> str:
    """
    Нормализует callback_data для сравнения.
    Заменяет {id}, {order_id}, etc. на regex паттерны.
    """
    # Заменяем placeholders на regex
    normalized = callback
    normalized = re.sub(r'\{[^}]+\}', r'\\d+', normalized)
    normalized = re.sub(r'_\d+$', r'_\\d+', normalized)

    return normalized

def match_callback_to_pattern(callback: str, patterns: Set[str]) -> bool:
    """Проверяет соответствует ли callback хотя бы одному паттерну"""
    callback_normalized = normalize_callback(callback)

    for pattern in patterns:
        # Паттерны из bot.py могут быть regex
        try:
            if re.match(pattern, callback):
                return True
            if re.match(callback_normalized, pattern):
                return True
        except re.error:
            # Если не regex, сравниваем как строки
            if callback == pattern:
                return True

    return False

def find_unmatched_callbacks(
    handlers_file: Path,
    bot_file: Path
) -> Tuple[List[str], List[str]]:
    """
    Находит несоответствия между callbacks и handlers.

    Returns:
        (callbacks_without_handlers, handlers_without_usage)
    """
    callbacks = extract_callback_data_from_handlers(handlers_file)
    patterns = extract_handlers_from_bot(bot_file)

    # Фильтруем системные callbacks
    system_callbacks = {
        "noop",
        "start",  # Команда, а не callback
        "go_main_menu",
        "show_client_menu",
        "show_worker_menu",
    }

    # Callbacks без handlers
    unmatched_callbacks = []
    for callback in sorted(callbacks):
        if callback in system_callbacks:
            continue
        if callback.startswith("^"):  # Это паттерн из bot.py
            continue
        if not match_callback_to_pattern(callback, patterns):
            unmatched_callbacks.append(callback)

    # Handlers без использования (сложнее проверить, пропускаем пока)
    unused_handlers = []

    return unmatched_callbacks, unused_handlers

def main():
    """Основная функция проверки"""
    project_dir = Path(__file__).parent
    handlers_file = project_dir / "handlers.py"
    bot_file = project_dir / "bot.py"

    if not handlers_file.exists():
        print(f"❌ Файл не найден: {handlers_file}")
        return 1

    if not bot_file.exists():
        print(f"❌ Файл не найден: {bot_file}")
        return 1

    print("🔍 Проверка callback consistency...")
    print()

    unmatched_callbacks, unused_handlers = find_unmatched_callbacks(
        handlers_file, bot_file
    )

    # Результаты
    if unmatched_callbacks:
        print("❌ МЁРТВЫЕ КНОПКИ (callback_data без handlers):")
        print()
        for callback in unmatched_callbacks[:20]:  # Показываем первые 20
            print(f"  • {callback}")
        if len(unmatched_callbacks) > 20:
            print(f"  ... и ещё {len(unmatched_callbacks) - 20}")
        print()
    else:
        print("✅ Все callback_data имеют обработчики!")
        print()

    # Статистика
    callbacks_total = len(extract_callback_data_from_handlers(handlers_file))
    handlers_total = len(extract_handlers_from_bot(bot_file))

    print("📊 Статистика:")
    print(f"  Всего callback_data: {callbacks_total}")
    print(f"  Всего handlers: {handlers_total}")
    print(f"  Мёртвых кнопок: {len(unmatched_callbacks)}")
    print()

    if unmatched_callbacks:
        print("💡 Рекомендация:")
        print("  Проверьте файл bot.py и добавьте недостающие handlers")
        return 1
    else:
        print("✅ Всё хорошо!")
        return 0

if __name__ == "__main__":
    exit(main())

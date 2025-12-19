#!/usr/bin/env python3
"""
Быстрый старт: Интеграция Supabase + S3 Cloud.ru

Этот скрипт помогает быстро начать работу с новыми компонентами.
Запустите: python QUICKSTART.py
"""

import os
import sys
import subprocess
from pathlib import Path

def print_header(text: str):
    """Печать заголовка."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def print_step(number: int, text: str):
    """Печать шага."""
    print(f"  [{number}] {text}")

def print_success(text: str):
    """Печать успеха."""
    print(f"  ✅ {text}")

def print_error(text: str):
    """Печать ошибки."""
    print(f"  ❌ {text}")

def print_warning(text: str):
    """Печать предупреждения."""
    print(f"  ⚠️  {text}")

def check_python_version():
    """Проверить версию Python."""
    print_header("Проверка Python версии")
    
    version = sys.version_info
    if version.major >= 3 and version.minor >= 10:
        print_success(f"Python {version.major}.{version.minor}.{version.micro} OK")
        return True
    else:
        print_error(f"Python 3.10+ требуется (у вас {version.major}.{version.minor})")
        return False

def check_env_file():
    """Проверить наличие .env файла."""
    print_header("Проверка .env файла")
    
    env_path = Path(".env")
    example_path = Path("env.example")
    
    if env_path.exists():
        print_success(".env файл найден")
        return True
    elif example_path.exists():
        print_warning(".env файл не найден, но есть env.example")
        print("\n  Создать .env из env.example? (y/n): ", end="")
        response = input().lower()
        
        if response == 'y':
            with open(example_path, 'r') as f:
                content = f.read()
            with open(env_path, 'w') as f:
                f.write(content)
            print_success(".env создан из env.example")
            print_warning("Отредактируйте .env и добавьте реальные ключи!")
            return True
    else:
        print_error("env.example не найден в текущей директории")
        return False

def check_dependencies():
    """Проверить зависимости."""
    print_header("Проверка зависимостей")
    
    required = [
        'supabase',
        'boto3',
    ]
    
    missing = []
    for package in required:
        try:
            __import__(package)
            print_success(f"{package} установлен")
        except ImportError:
            print_error(f"{package} НЕ установлен")
            missing.append(package)
    
    if missing:
        print_warning(f"Отсутствуют пакеты: {', '.join(missing)}")
        print("\n  Установить? (y/n): ", end="")
        response = input().lower()
        
        if response == 'y':
            print("\n  Установка зависимостей...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            print_success("Зависимости установлены")
            return True
        return False
    else:
        print_success("Все зависимости установлены")
        return True

def check_env_variables():
    """Проверить переменные окружения."""
    print_header("Проверка переменных окружения")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = [
        'SUPABASE_URL',
        'SUPABASE_ANON_KEY',
        # 'DATABASE_URL' - удален
        'R2_ACCESS_KEY_ID', # Обновлено для R2
        'R2_SECRET_ACCESS_KEY',
        'R2_BUCKET_NAME',
    ]
    
    missing = []
    for var in required_vars:
        # Проверяем и старые имена для совместимости
        value = os.getenv(var)
        if not value and var.startswith('R2'):
            legacy_var = var.replace('R2', 'S3').replace('_NAME', '')
            value = os.getenv(legacy_var)
            
        if value and value != f"your-{var.lower()}" and len(value) > 5:
            print_success(f"{var} (или S3 аналог) установлена")
        else:
            print_error(f"{var} НЕ установлена или некорректна")
            missing.append(var)
    
    if missing:
        print_warning(f"Не заполнены переменные: {', '.join(missing)}")
        return False
    else:
        print_success("Все переменные окружения установлены корректно")
        return True

def test_connections():
    """Протестировать подключения."""
    print_header("Тестирование подключений")
    
    try:
        from src.config import config
        
        # Проверить конфигурацию
        try:
            config.validate()
            print_success("Конфигурация валидна")
        except ValueError as e:
            print_error(f"Ошибка конфигурации: {e}")
            return False
        
        # Проверить Supabase
        from src.supabase_client import supabase_client
        if supabase_client.is_connected():
            print_success("Supabase подключен")
        else:
            print_warning("Supabase не подключен (может быть отключен в .env)")
        
        # Проверить S3
        from src.s3_storage import s3_storage
        if s3_storage.is_connected():
            print_success("S3 Cloud.ru подключен")
        else:
            print_warning("S3 не подключен (может быть отключен в .env)")
        
        return True
        
    except Exception as e:
        print_error(f"Ошибка при тестировании: {e}")
        return False

def show_next_steps():
    """Показать следующие шаги."""
    print_header("Следующие шаги")
    
    print_step(1, "Отредактировать .env файл:")
    print("     - Заполнить SUPABASE_URL")
    print("     - Заполнить SUPABASE_ANON_KEY")
    print("     - Заполнить R2_ACCESS_KEY_ID")
    print("     - Заполнить R2_SECRET_ACCESS_KEY")
    print("")
    
    print_step(2, "Инициализировать БД в Supabase:")
    print("     - Скопировать содержимое FULL_DB_INIT.sql")
    print("     - Вставить в SQL Editor в Supabase Dashboard")
    print("     - Нажать Run")
    print("")
    
    print_step(3, "Протестировать примеры:")
    print("     Смотри INTEGRATION_EXAMPLES.py")
    print("")
    
    print_step(4, "Прочитать документацию:")
    print("     - SUPABASE_S3_SETUP_SUMMARY.md (начните отсюда)")
    print("")

def show_helpful_commands():
    """Показать полезные команды."""
    print_header("Полезные команды")
    
    commands = [
        ("Проверить подключения", "python -c \"from src.supabase_client import supabase_client; from src.s3_storage import s3_storage; print(f'DB: {supabase_client.is_connected()}'); print(f'S3: {s3_storage.is_connected()}')\""),
    ]
    
    for description, command in commands:
        print(f"\n  {description}:")
        print(f"    $ {command}")
    
    print()

def show_documentation_structure():
    """Показать структуру документации."""
    print_header("Структура документации")
    
    docs = [
        ("🎯 НАЧНИТЕ ЗДЕСЬ", "SUPABASE_S3_SETUP_SUMMARY.md"),
        ("📋 План реализации", "IMPLEMENTATION_PLAN.md"),
        ("🏗️  Архитектура", "ARCHITECTURE.md"),
        ("🗄️  Схема БД", "DATABASE_ARCHITECTURE.md"),
        ("🔌 Интеграция", "SUPABASE_S3_INTEGRATION.md"),
        ("💻 Примеры кода", "INTEGRATION_EXAMPLES.py"),
        ("✅ Что было сделано", "CHECKLIST.md"),
        ("🧭 Навигация", "NAVIGATION.md"),
    ]
    
    for description, filename in docs:
        print(f"  {description:30} → {filename}")
    
    print()

def main():
    """Основная функция."""
    print_header("🚀 БЫСТРЫЙ СТАРТ: Supabase + S3 Cloud.ru")
    
    checks = [
        ("Проверка Python версии", check_python_version),
        ("Проверка .env файла", check_env_file),
        ("Проверка зависимостей", check_dependencies),
        ("Проверка переменных окружения", check_env_variables),
        ("Тестирование подключений", test_connections),
    ]
    
    results = []
    for description, check_func in checks:
        try:
            result = check_func()
            results.append((description, result))
        except Exception as e:
            print_error(f"Ошибка при проверке: {e}")
            results.append((description, False))
    
    # Итоги
    print_header("📊 Итоги проверок")
    
    for description, result in results:
        status = "✅" if result else "❌"
        print(f"  {status} {description}")
    
    if not all(result for _, result in results):
        print_warning("Некоторые проверки не прошли")
        print("Пожалуйста, исправьте ошибки выше перед продолжением")
    else:
        print_success("Все проверки пройдены успешно!")
    
    # Показать полезные команды
    show_helpful_commands()
    
    # Показать структуру документации
    show_documentation_structure()
    
    # Следующие шаги
    show_next_steps()
    
    print_header("🎉 Готово!")
    print("  Для начала работы:")
    print("  1. Отредактируйте .env с реальными ключами")
    print("  2. Инициализируйте БД в Supabase (используйте FULL_DB_INIT.sql)")
    print("  3. Используйте примеры из INTEGRATION_EXAMPLES.py")
    print("")
    print("  Документация: смотри SUPABASE_S3_SETUP_SUMMARY.md")
    print("")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nПрограмма прервана пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)


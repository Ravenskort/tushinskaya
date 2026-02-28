import telebot
import schedule
import time
import random
from threading import Thread
from datetime import datetime
from telebot import types
import pytz
import os
import sys

# ====== НАСТРОЙКИ ======
TOKEN = "8568812025:AAHL-u8tquSPxlBW8ZEXz2wv4oi0z8R6r3U"  # Ваш токен
GROUP_CHAT_ID = -1002990790597  # ID вашей группы

# Время публикации (МСК)
VOTING_TIME = "12:00"  # Время создания голосования
REMINDER_TIME = "18:00"  # Время создания второго сообщения (напоминание)

# Часовой пояс Москвы
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Список случайных имен для гостей
GUEST_NAMES = [
    "Шефан Карри", "ЛеБрик", "Вестбрик", "Шакал О'Нил",
    "Черная Мамба", "Джокер", "Грик Фрик", "Флоппер",
    "Просто Бен Симмонс", "Мистер Трипл Дабл"
]

# Структура данных голосования
voting_data = {
    'voting_message_id': None,      # ID первого сообщения (с кнопками и результатами)
    'reminder_message_id': None,     # ID второго сообщения (напоминание в 18:00)
    'yes_voters': {},               # Проголосовавшие ДА
    'no_voters': {},                # Проголосовавшие НЕТ
    'plus_one_voters': {},          # Гости (user_id: список гостей)
    'user_cache': {}                # Кэш данных пользователей
}

# ====== ИНИЦИАЛИЗАЦИЯ БОТА ======
bot = telebot.TeleBot(TOKEN)

# ====== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ======

def safe_delete(message_id, chat_id=GROUP_CHAT_ID):
    """Безопасное удаление сообщения"""
    try:
        if message_id:
            bot.delete_message(chat_id, message_id)
            return True
    except Exception as e:
        print(f"Ошибка удаления: {e}")
        return False

def safe_edit(message_id, text, parse_mode=None, reply_markup=None, chat_id=GROUP_CHAT_ID):
    """Безопасное редактирование сообщения"""
    try:
        if reply_markup is not None:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        else:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode
            )
        return True
    except Exception as e:
        print(f"Ошибка редактирования: {e}")
        return False

def is_admin(user_id, chat_id=GROUP_CHAT_ID):
    """Проверка прав администратора"""
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except:
        return False

def get_display_name(user):
    """Получение отображаемого имени пользователя"""
    name_parts = []
    if user.first_name:
        name_parts.append(user.first_name)
    if user.last_name:
        name_parts.append(user.last_name)
    
    display_name = " ".join(name_parts) if name_parts else f"User{user.id}"
    
    if user.username:
        display_name += f" (@{user.username})"
    
    return display_name

def save_user_to_cache(user):
    """Сохранение пользователя в кэш"""
    user_id = user.id
    display_name = get_display_name(user)
    
    user_data = {
        'user_id': user_id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'display_name': display_name,
        'is_bot': user.is_bot
    }
    
    voting_data['user_cache'][user_id] = user_data
    return user_data

def get_user_display_from_cache(user_id):
    """Получение имени пользователя из кэша"""
    if user_id in voting_data['user_cache']:
        return voting_data['user_cache'][user_id]['display_name']
    elif user_id in voting_data['yes_voters']:
        return voting_data['yes_voters'][user_id]['display_name']
    elif user_id in voting_data['no_voters']:
        return voting_data['no_voters'][user_id]['display_name']
    else:
        return f"Участник {user_id}"

def log_action(action, user_name, details=""):
    """Логирование действий"""
    moscow_time = datetime.now(MOSCOW_TZ).strftime("%H:%M:%S")
    print(f"[{moscow_time}] {action}: {user_name} {details}")

# ====== ФУНКЦИИ ФОРМИРОВАНИЯ ТЕКСТА ======

def get_first_message_text():
    """Формирование текста первого сообщения (с кнопками и полными результатами)"""
    text = "🏀 *ТРЕНИРОВКА НА ТУШИНСКОЙ*\n\n"
    
    # Статистика сверху
    yes_count = len(voting_data['yes_voters'])
    no_count = len(voting_data['no_voters'])
    guests_count = sum(len(g) for g in voting_data['plus_one_voters'].values())
    
    text += f"✅ ДА: {yes_count}\n"
    text += f"❌ НЕТ: {no_count}\n"
    text += f"👥 Гостей: {guests_count}\n"
    text += f"📈 Всего идет: {yes_count + guests_count}\n\n"
    
    text += "📋 *Полный список участников:*\n\n"
    
    all_participants = []
    
    # Добавляем проголосовавших ДА и их гостей
    for user_id, user_data in voting_data['yes_voters'].items():
        display_name = user_data.get('display_name', f'Участник {user_id}')
        all_participants.append(f"✅ {display_name}")
        
        # Добавляем гостей этого пользователя
        if user_id in voting_data['plus_one_voters']:
            for guest in voting_data['plus_one_voters'][user_id]:
                guest_name = guest.get('guest_name', 'Гость')
                all_participants.append(f"   👥 {guest_name} (гость {display_name})")
    
    # Добавляем гостей от тех, кто не голосовал ДА
    for user_id, guests in voting_data['plus_one_voters'].items():
        if user_id not in voting_data['yes_voters']:
            display_name = get_user_display_from_cache(user_id)
            for guest in guests:
                guest_name = guest.get('guest_name', 'Гость')
                all_participants.append(f"   👥 {guest_name} (гость {display_name})")
    
    # Добавляем проголосовавших НЕТ
    for user_id, user_data in voting_data['no_voters'].items():
        display_name = user_data.get('display_name', f'Участник {user_id}')
        all_participants.append(f"❌ {display_name}")
    
    # Формируем список (БЕЗ ОГРАНИЧЕНИЯ ПО КОЛИЧЕСТВУ)
    if all_participants:
        for i, participant in enumerate(all_participants, 1):
            text += f"{i}. {participant}\n"
    else:
        text += "_Пока никто не проголосовал_ 😔\n"
    
    text += "\n👇 *Сделайте свой выбор:*"
    
    return text

def get_reminder_text():
    """Формирование текста второго сообщения (напоминание)"""
    text = "🏀 *НАПОМИНАНИЕ О ТРЕНИРОВКЕ*\n\n"
    text += "Жду на Тушинской с 19:00\n\n"
    
    yes_count = len(voting_data['yes_voters'])
    guests_count = sum(len(g) for g in voting_data['plus_one_voters'].values())
    
    text += f"✅ Идет: {yes_count} чел.\n"
    text += f"👥 С гостями: {yes_count + guests_count} чел.\n\n"
    
    going = []
    
    # Собираем всех, кто идет (сокращенный список для напоминания)
    for user_id, user_data in voting_data['yes_voters'].items():
        display_name = user_data.get('display_name', f'Участник {user_id}')
        # Сокращаем имя для компактности
        if len(display_name) > 30:
            display_name = display_name[:27] + "..."
        going.append(f"✅ {display_name}")
        
        if user_id in voting_data['plus_one_voters']:
            for guest in voting_data['plus_one_voters'][user_id]:
                guest_name = guest.get('guest_name', 'Гость')
                going.append(f"   👥 {guest_name}")
    
    for user_id, guests in voting_data['plus_one_voters'].items():
        if user_id not in voting_data['yes_voters']:
            display_name = get_user_display_from_cache(user_id)
            if len(display_name) > 30:
                display_name = display_name[:27] + "..."
            for guest in guests:
                guest_name = guest.get('guest_name', 'Гость')
                going.append(f"   👥 {guest_name} (гость {display_name})")
    
    if going:
        text += "👥 *Список идущих:*\n"
        # Показываем только первые 15, чтобы не было слишком длинно
        for i, person in enumerate(going[:15], 1):
            text += f"{i}. {person}\n"
        
        if len(going) > 15:
            text += f"...и еще {len(going) - 15} чел.\n"
    else:
        text += "😔 Пока никто не идет"
    
    return text

def get_voting_keyboard():
    """Создание клавиатуры для голосования"""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    btn_yes = types.InlineKeyboardButton("✅ ДА", callback_data="vote_yes")
    btn_no = types.InlineKeyboardButton("❌ НЕТ", callback_data="vote_no")
    btn_plus = types.InlineKeyboardButton("➕ +1 ГОСТЬ", callback_data="plus_one")
    btn_minus = types.InlineKeyboardButton("➖ -1 ГОСТЬ", callback_data="minus_one")
    
    keyboard.add(btn_yes, btn_no)
    keyboard.add(btn_plus, btn_minus)
    
    return keyboard

# ====== ФУНКЦИИ ОБНОВЛЕНИЯ СООБЩЕНИЙ ======

def update_first_message():
    """Обновление первого сообщения (с кнопками и результатами)"""
    if voting_data['voting_message_id']:
        keyboard = get_voting_keyboard()
        safe_edit(
            voting_data['voting_message_id'],
            get_first_message_text(),
            parse_mode='Markdown',
            reply_markup=keyboard
        )

def update_reminder_message():
    """Обновление второго сообщения (напоминание)"""
    if voting_data['reminder_message_id']:
        safe_edit(
            voting_data['reminder_message_id'],
            get_reminder_text(),
            parse_mode='Markdown'
        )

def update_all_messages():
    """Обновление всех сообщений"""
    update_first_message()
    update_reminder_message()

# ====== СОЗДАНИЕ ГОЛОСОВАНИЯ ======

def create_voting():
    """Создание нового голосования"""
    try:
        # Проверяем, существует ли уже активное голосование
        moscow_now = datetime.now(MOSCOW_TZ)
        
        # Удаляем старые сообщения, если они есть
        if voting_data['voting_message_id']:
            safe_delete(voting_data['voting_message_id'])
        if voting_data['reminder_message_id']:
            safe_delete(voting_data['reminder_message_id'])
        
        # Сбрасываем данные, но сохраняем структуру
        voting_data['yes_voters'] = {}
        voting_data['no_voters'] = {}
        voting_data['plus_one_voters'] = {}
        voting_data['user_cache'] = {}
        voting_data['voting_message_id'] = None
        voting_data['reminder_message_id'] = None
        
        # 1. ПЕРВОЕ СООБЩЕНИЕ (с кнопками и полными результатами)
        first_msg = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=get_first_message_text(),
            parse_mode='Markdown',
            reply_markup=get_voting_keyboard()
        )
        voting_data['voting_message_id'] = first_msg.message_id
        
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ✅ ПЕРВОЕ СООБЩЕНИЕ СОЗДАНО")
        
    except Exception as e:
        print(f"❌ Ошибка создания голосования: {e}")

def create_reminder_message():
    """Создание второго сообщения (напоминание в 18:00)"""
    try:
        moscow_now = datetime.now(MOSCOW_TZ)
        
        # Если второе сообщение уже существует, удаляем его
        if voting_data['reminder_message_id']:
            safe_delete(voting_data['reminder_message_id'])
            voting_data['reminder_message_id'] = None
        
        # Создаем новое второе сообщение
        reminder_msg = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=get_reminder_text(),
            parse_mode='Markdown'
        )
        voting_data['reminder_message_id'] = reminder_msg.message_id
        
        print(f"[{moscow_now.strftime('%H:%M:%S')}] 📢 ВТОРОЕ СООБЩЕНИЕ (НАПОМИНАНИЕ) СОЗДАНО")
        
    except Exception as e:
        print(f"❌ Ошибка создания второго сообщения: {e}")

# ====== ОБРАБОТЧИК НАЖАТИЙ КНОПОК ======

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработка нажатий на кнопки"""
    user_id = call.from_user.id
    user = call.from_user
    display_name = get_display_name(user)
    
    # Проверяем, есть ли сообщение с кнопками
    if not voting_data['voting_message_id']:
        bot.answer_callback_query(call.id, "❌ Голосование не активно. Дождитесь /start", show_alert=True)
        return
    
    # Сохраняем пользователя в кэш
    save_user_to_cache(user)
    
    try:
        if call.data == "vote_yes":
            # Удаляем из НЕТ, если был там
            if user_id in voting_data['no_voters']:
                del voting_data['no_voters'][user_id]
            
            # Добавляем в ДА
            voting_data['yes_voters'][user_id] = voting_data['user_cache'][user_id]
            
            bot.answer_callback_query(call.id, "✅ Вы выбрали ДА!", show_alert=False)
            log_action("✅ ДА", display_name)
            
        elif call.data == "vote_no":
            # Удаляем из ДА, если был там
            if user_id in voting_data['yes_voters']:
                del voting_data['yes_voters'][user_id]
            
            # Добавляем в НЕТ
            voting_data['no_voters'][user_id] = voting_data['user_cache'][user_id]
            
            bot.answer_callback_query(call.id, "❌ Вы выбрали НЕТ!", show_alert=False)
            log_action("❌ НЕТ", display_name)
            
        elif call.data == "plus_one":
            # Добавление гостя
            if user_id not in voting_data['plus_one_voters']:
                voting_data['plus_one_voters'][user_id] = []
            
            guest_name = random.choice(GUEST_NAMES)
            guest_data = {
                'guest_name': guest_name,
                'host_name': display_name,
                'host_id': user_id,
                'timestamp': datetime.now(MOSCOW_TZ)
            }
            
            voting_data['plus_one_voters'][user_id].append(guest_data)
            guest_count = len(voting_data['plus_one_voters'][user_id])
            
            bot.answer_callback_query(
                call.id,
                f"✅ Добавлен гость: {guest_name}\nВсего гостей: {guest_count}",
                show_alert=False
            )
            log_action("➕ ГОСТЬ", display_name, f"({guest_name})")
            
        elif call.data == "minus_one":
            # Удаление последнего гостя
            if user_id not in voting_data['plus_one_voters'] or not voting_data['plus_one_voters'][user_id]:
                bot.answer_callback_query(call.id, "❌ У вас нет гостей!", show_alert=True)
                return
            
            removed = voting_data['plus_one_voters'][user_id].pop()
            guest_name = removed.get('guest_name', 'Гость')
            
            if not voting_data['plus_one_voters'][user_id]:
                del voting_data['plus_one_voters'][user_id]
            
            bot.answer_callback_query(call.id, f"✅ Убран гость: {guest_name}", show_alert=False)
            log_action("➖ ГОСТЬ", display_name, f"(удален {guest_name})")
        
        # Обновляем все сообщения после каждого действия
        update_all_messages()
        
    except Exception as e:
        print(f"Ошибка обработки нажатия: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка", show_alert=True)

# ====== КОМАНДЫ АДМИНИСТРАТОРОВ ======

@bot.message_handler(commands=['start'])
def cmd_start(message):
    """Быстрая команда: запуск голосования"""
    user_id = message.from_user.id
    
    # Проверка прав администратора
    if not is_admin(user_id, message.chat.id):
        bot.reply_to(message, "❌ Только для администраторов!")
        return
    
    # Удаляем команду
    safe_delete(message.message_id, message.chat.id)
    
    # Создаем голосование
    create_voting()
    
    # Отправляем подтверждение (удаляется через 3 сек)
    confirm = bot.send_message(message.chat.id, "✅ Голосование запущено!")
    time.sleep(3)
    safe_delete(confirm.message_id, message.chat.id)

@bot.message_handler(commands=['remind'])
def cmd_remind(message):
    """Быстрая команда: создать второе сообщение (напоминание) сейчас"""
    user_id = message.from_user.id
    
    if not is_admin(user_id, message.chat.id):
        bot.reply_to(message, "❌ Только для администраторов!")
        return
    
    # Удаляем команду
    safe_delete(message.message_id, message.chat.id)
    
    # Проверяем, есть ли активное голосование
    if not voting_data['voting_message_id']:
        confirm = bot.send_message(message.chat.id, "❌ Нет активного голосования. Используйте /start")
        time.sleep(3)
        safe_delete(confirm.message_id, message.chat.id)
        return
    
    # Создаем второе сообщение
    create_reminder_message()
    
    # Отправляем подтверждение
    confirm = bot.send_message(message.chat.id, "✅ Второе сообщение (напоминание) создано!")
    time.sleep(3)
    safe_delete(confirm.message_id, message.chat.id)

@bot.message_handler(commands=['clear'])
def cmd_clear(message):
    """Быстрая команда: очистка всех данных голосования"""
    user_id = message.from_user.id
    
    if not is_admin(user_id, message.chat.id):
        bot.reply_to(message, "❌ Только для администраторов!")
        return
    
    # Удаляем команду
    safe_delete(message.message_id, message.chat.id)
    
    # Очищаем все данные
    voting_data['yes_voters'] = {}
    voting_data['no_voters'] = {}
    voting_data['plus_one_voters'] = {}
    voting_data['user_cache'] = {}
    
    # Обновляем сообщения
    update_all_messages()
    
    # Отправляем подтверждение
    confirm = bot.send_message(message.chat.id, "✅ Все данные голосования очищены!")
    time.sleep(3)
    safe_delete(confirm.message_id, message.chat.id)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    """Команда помощи"""
    user_id = message.from_user.id
    
    if not is_admin(user_id, message.chat.id):
        bot.reply_to(message, "❌ Только для администраторов!")
        return
    
    safe_delete(message.message_id, message.chat.id)
    
    help_text = """
🤖 *Команды администратора:*

🔹 /start - Запустить голосование (создает 1-е сообщение)
🔹 /remind - Создать 2-е сообщение (напоминание) сейчас
🔹 /clear - Очистить все данные голосования
🔹 /help - Показать эту справку

*Расписание:*
📅 1-е сообщение (голосование): ежедневно в 12:00 МСК
📅 2-е сообщение (напоминание): ежедневно в 18:00 МСК

*Как голосовать:*
✅ ДА - вы идете
❌ НЕТ - вы не идете
➕ +1 ГОСТЬ - добавить гостя
➖ -1 ГОСТЬ - убрать последнего гостя

*Примечание:*
- В первом сообщении сразу виден полный список участников
- Второе сообщение появляется в 18:00 как напоминание
- Гостей можно добавлять даже без выбора ДА
- Все сообщения обновляются автоматически
    """
    
    msg = bot.send_message(message.chat.id, help_text, parse_mode='Markdown')
    time.sleep(10)
    safe_delete(msg.message_id, message.chat.id)

# ====== ПЛАНИРОВЩИК ЗАДАЧ ======

def run_scheduler():
    """Запуск планировщика в отдельном потоке"""
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            print(f"Ошибка планировщика: {e}")
            time.sleep(5)

def setup_scheduler():
    """Настройка расписания"""
    schedule.clear()
    
    # Конвертация времени из МСК в UTC
    def msk_to_utc(time_str):
        hour, minute = map(int, time_str.split(':'))
        hour_utc = hour - 3
        if hour_utc < 0:
            hour_utc += 24
        return f"{hour_utc:02d}:{minute:02d}"
    
    # Планируем голосование на 12:00 МСК
    voting_utc = msk_to_utc(VOTING_TIME)
    schedule.every().day.at(voting_utc).do(create_voting)
    
    # Планируем второе сообщение на 18:00 МСК
    reminder_utc = msk_to_utc(REMINDER_TIME)
    schedule.every().day.at(reminder_utc).do(create_reminder_message)
    
    print(f"📅 Расписание:")
    print(f"   - 1-е сообщение (голосование): {VOTING_TIME} МСК ({voting_utc} UTC)")
    print(f"   - 2-е сообщение (напоминание): {REMINDER_TIME} МСК ({reminder_utc} UTC)")

# ====== ЗАПУСК БОТА ======

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 БОТ ДЛЯ ГОЛОСОВАНИЯ ЗАПУСКАЕТСЯ...")
    print("=" * 50)
    
    # Проверка подключения к группе
    try:
        chat = bot.get_chat(GROUP_CHAT_ID)
        print(f"✅ Подключено к группе: {chat.title}")
        print(f"✅ ID группы: {GROUP_CHAT_ID}")
    except Exception as e:
        print(f"⚠️ Ошибка подключения к группе: {e}")
        print("   Проверьте GROUP_CHAT_ID и права бота")
    
    # Настройка расписания
    setup_scheduler()
    
    # Запуск планировщика в отдельном потоке
    scheduler_thread = Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    print("✅ Планировщик задач запущен")
    
    print("=" * 50)
    print("🔄 БОТ РАБОТАЕТ. ОЖИДАНИЕ КОМАНД...")
    print("=" * 50)
    
    # Запуск бота с обработкой ошибок для BotHost
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            print(f"❌ Ошибка polling: {e}")
            print("🔄 Перезапуск через 10 секунд...")
            time.sleep(10)

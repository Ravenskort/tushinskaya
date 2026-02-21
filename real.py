import telebot
import schedule
import time
import random
from threading import Thread, Lock
from datetime import datetime, timedelta
from telebot import types
import pytz
import os
import sys
import traceback

# ====== НАСТРОЙКИ ======
TOKEN = "8568812025:AAHL-u8tquSPxlBW8ZEXz2wv4oi0z8R6r3U"  # Ваш токен
GROUP_CHAT_ID = -1003559215540  # ID вашей группы

# Время публикации (МСК)
VOTING_TIME = "12:00"  # Время создания голосования
NOTIFICATION_TIME = "18:00"  # Время создания третьего сообщения

# Часовой пояс Москвы
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Список случайных имен для гостей
GUEST_NAMES = [
    "Шефан Карри", "ЛеБрик", "Вестбрик", "Шакал О'Нил",
    "Черная Мамба", "Джокер", "Грик Фрик", "Флоппер",
    "Просто Бен Симмонс", "Доктор Дрим", "Король Трэш", "Мистер Тройной Дабл"
]

# Лимиты Telegram
MAX_MESSAGE_LENGTH = 4096
SAFE_MESSAGE_LENGTH = 4000  # Оставляем запас
MAX_CACHE_SIZE = 1000  # Максимальный размер кэша пользователей

# Структура данных голосования
voting_data = {
    'voting_message_id': None,      # ID сообщения с кнопками
    'results_message_id': None,     # ID сообщения с результатами
    'third_message_id': None,       # ID третьего сообщения (в 18:00)
    'yes_voters': {},               # Проголосовавшие ДА
    'no_voters': {},                # Проголосовавшие НЕТ
    'plus_one_voters': {},          # Гости (user_id: список гостей)
    'user_cache': {}                # Кэш данных пользователей
}

# Блокировка для потокобезопасной работы с данными
voting_data_lock = Lock()

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
        # Игнорируем ошибку "message to delete not found"
        error_str = str(e).lower()
        if "message to delete not found" not in error_str and "message can't be deleted" not in error_str:
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
        error_str = str(e).lower()
        # Игнорируем ошибки, связанные с тем, что сообщение не изменилось
        if "message is not modified" not in error_str:
            print(f"Ошибка редактирования: {e}")
        return False

def is_admin(user_id, chat_id=GROUP_CHAT_ID):
    """Проверка прав администратора"""
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except Exception as e:
        print(f"Ошибка проверки прав: {e}")
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
    """Сохранение пользователя в кэш с ограничением размера"""
    user_id = user.id
    display_name = get_display_name(user)
    
    user_data = {
        'user_id': user_id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'display_name': display_name,
        'is_bot': user.is_bot,
        'cached_at': datetime.now(MOSCOW_TZ).isoformat()
    }
    
    with voting_data_lock:
        # Ограничиваем размер кэша
        if len(voting_data['user_cache']) >= MAX_CACHE_SIZE:
            # Удаляем самую старую запись
            oldest_key = min(voting_data['user_cache'].keys(), 
                           key=lambda k: voting_data['user_cache'][k].get('cached_at', ''))
            del voting_data['user_cache'][oldest_key]
        
        voting_data['user_cache'][user_id] = user_data
    
    return user_data

def get_user_display_from_cache(user_id):
    """Получение имени пользователя из кэша"""
    with voting_data_lock:
        if user_id in voting_data['user_cache']:
            return voting_data['user_cache'][user_id]['display_name']
        elif user_id in voting_data['yes_voters']:
            return voting_data['yes_voters'][user_id]['display_name']
        elif user_id in voting_data['no_voters']:
            return voting_data['no_voters'][user_id]['display_name']
    
    return f"Участник {user_id}"

def log_action(action, user_name, details=""):
    """Логирование действий"""
    moscow_time = datetime.now(MOSCOW_TZ).strftime("%H:%M:%S")
    print(f"[{moscow_time}] {action}: {user_name} {details}")

def safe_send_long_message(chat_id, text, parse_mode=None, reply_markup=None):
    """Безопасная отправка длинного сообщения с разбивкой"""
    if len(text) <= SAFE_MESSAGE_LENGTH:
        return bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
    
    # Разбиваем на части
    parts = []
    current_part = ""
    
    for line in text.split('\n'):
        if len(current_part) + len(line) + 1 > SAFE_MESSAGE_LENGTH:
            parts.append(current_part)
            current_part = line + '\n'
        else:
            current_part += line + '\n'
    
    if current_part:
        parts.append(current_part)
    
    # Отправляем первую часть с клавиатурой, остальные без
    messages = []
    for i, part in enumerate(parts):
        if i == 0 and reply_markup:
            msg = bot.send_message(chat_id, part, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            msg = bot.send_message(chat_id, part, parse_mode=parse_mode)
        messages.append(msg)
    
    return messages[0]  # Возвращаем первое сообщение для совместимости

# ====== ФУНКЦИИ ФОРМИРОВАНИЯ ТЕКСТА ======

def get_results_text():
    """Формирование текста сообщения с результатами (с защитой от переполнения)"""
    with voting_data_lock:
        text = "🏀 *РЕЗУЛЬТАТЫ ГОЛОСОВАНИЯ*\n\n"
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
        
        # Формируем список с проверкой длины
        if all_participants:
            participants_text = ""
            for i, participant in enumerate(all_participants, 1):
                line = f"{i}. {participant}\n"
                # Проверяем, не превысит ли лимит
                if len(text) + len(participants_text) + len(line) > SAFE_MESSAGE_LENGTH - 200:  # Оставляем место для статистики
                    remaining = len(all_participants) - i + 1
                    participants_text += f"\n... и еще {remaining} участников"
                    break
                participants_text += line
            text += participants_text
        else:
            text += "_Пока никто не проголосовал_ 😔\n"
        
        # Добавляем статистику
        yes_count = len(voting_data['yes_voters'])
        no_count = len(voting_data['no_voters'])
        guests_count = sum(len(g) for g in voting_data['plus_one_voters'].values())
        
        text += f"\n📊 *Статистика:*\n"
        text += f"✅ ДА: {yes_count} чел.\n"
        text += f"❌ НЕТ: {no_count} чел.\n"
        text += f"👥 Гостей: {guests_count} чел.\n"
        text += f"📈 Всего идет: {yes_count + guests_count} чел."
        
        return text

def get_voting_text():
    """Формирование текста сообщения с кнопками"""
    with voting_data_lock:
        yes_count = len(voting_data['yes_voters'])
        no_count = len(voting_data['no_voters'])
        
        text = "🏀 *ТРЕНИРОВКА НА ТУШИНСКОЙ*\n\n"
        text += f"✅ ДА: {yes_count}\n"
        text += f"❌ НЕТ: {no_count}\n\n"
        text += "👇 *Сделайте свой выбор:*"
        
        return text

def get_third_message_text():
    """Формирование текста третьего сообщения"""
    with voting_data_lock:
        text = "🏀 *Напоминание о тренировке*\n\n"
        text += "Жду на Тушинской с 19:00\n\n"
        
        going = []
        
        # Собираем всех, кто идет
        for user_id, user_data in voting_data['yes_voters'].items():
            display_name = user_data.get('display_name', f'Участник {user_id}')
            going.append(display_name)
            
            if user_id in voting_data['plus_one_voters']:
                for guest in voting_data['plus_one_voters'][user_id]:
                    guest_name = guest.get('guest_name', 'Гость')
                    going.append(f"{guest_name} (гость {display_name})")
        
        for user_id, guests in voting_data['plus_one_voters'].items():
            if user_id not in voting_data['yes_voters']:
                display_name = get_user_display_from_cache(user_id)
                for guest in guests:
                    guest_name = guest.get('guest_name', 'Гость')
                    going.append(f"{guest_name} (гость {display_name})")
        
        if going:
            text += "👥 *Идут:*\n"
            for i, person in enumerate(going, 1):
                # Проверяем длину
                line = f"{i}. {person}\n"
                if len(text) + len(line) > SAFE_MESSAGE_LENGTH:
                    text += f"\n... и еще {len(going) - i + 1} человек"
                    break
                text += line
        else:
            text += "😔 Пока никто не идет"
        
        return text

# ====== ФУНКЦИИ ОБНОВЛЕНИЯ СООБЩЕНИЙ ======

def update_all_messages():
    """Обновление всех сообщений (потокобезопасно)"""
    with voting_data_lock:
        # Обновляем сообщение с кнопками
        if voting_data['voting_message_id']:
            keyboard = get_voting_keyboard()
            safe_edit(
                voting_data['voting_message_id'],
                get_voting_text(),
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        
        # Обновляем сообщение с результатами
        if voting_data['results_message_id']:
            safe_edit(
                voting_data['results_message_id'],
                get_results_text(),
                parse_mode='Markdown'
            )
        
        # Обновляем третье сообщение, если оно существует
        if voting_data['third_message_id']:
            safe_edit(
                voting_data['third_message_id'],
                get_third_message_text(),
                parse_mode='Markdown'
            )

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

# ====== СОЗДАНИЕ ГОЛОСОВАНИЯ ======

def create_voting():
    """Создание нового голосования"""
    try:
        moscow_now = datetime.now(MOSCOW_TZ)
        
        with voting_data_lock:
            # Удаляем старые сообщения
            if voting_data['voting_message_id']:
                safe_delete(voting_data['voting_message_id'])
            if voting_data['results_message_id']:
                safe_delete(voting_data['results_message_id'])
            if voting_data['third_message_id']:
                safe_delete(voting_data['third_message_id'])
            
            # Сбрасываем данные
            voting_data['yes_voters'] = {}
            voting_data['no_voters'] = {}
            voting_data['plus_one_voters'] = {}
            voting_data['user_cache'] = {}
            voting_data['voting_message_id'] = None
            voting_data['results_message_id'] = None
            voting_data['third_message_id'] = None
        
        # 1. СООБЩЕНИЕ С КНОПКАМИ (вне блокировки, чтобы не блокировать другие операции)
        voting_msg = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=get_voting_text(),
            parse_mode='Markdown',
            reply_markup=get_voting_keyboard()
        )
        
        # 2. СООБЩЕНИЕ С РЕЗУЛЬТАТАМИ
        results_msg = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=get_results_text(),
            parse_mode='Markdown'
        )
        
        with voting_data_lock:
            voting_data['voting_message_id'] = voting_msg.message_id
            voting_data['results_message_id'] = results_msg.message_id
        
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ✅ ГОЛОСОВАНИЕ СОЗДАНО")
        
    except Exception as e:
        print(f"❌ Ошибка создания голосования: {e}")
        traceback.print_exc()

def create_third_message():
    """Создание третьего сообщения (в 18:00)"""
    try:
        moscow_now = datetime.now(MOSCOW_TZ)
        
        with voting_data_lock:
            # Если третье сообщение уже существует, удаляем его
            if voting_data['third_message_id']:
                safe_delete(voting_data['third_message_id'])
                voting_data['third_message_id'] = None
        
        # Создаем новое третье сообщение
        third_msg = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=get_third_message_text(),
            parse_mode='Markdown'
        )
        
        with voting_data_lock:
            voting_data['third_message_id'] = third_msg.message_id
        
        print(f"[{moscow_now.strftime('%H:%M:%S')}] 📢 ТРЕТЬЕ СООБЩЕНИЕ СОЗДАНО")
        
    except Exception as e:
        print(f"❌ Ошибка создания третьего сообщения: {e}")
        traceback.print_exc()

# ====== ОБРАБОТЧИК НАЖАТИЙ КНОПОК ======

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработка нажатий на кнопки"""
    user_id = call.from_user.id
    user = call.from_user
    display_name = get_display_name(user)
    
    # Сначала отвечаем на callback, чтобы Telegram знал, что запрос обработан
    try:
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка ответа на callback: {e}")
    
    try:
        # Проверяем, есть ли сообщение с кнопками
        with voting_data_lock:
            if not voting_data['voting_message_id']:
                try:
                    bot.answer_callback_query(call.id, "❌ Голосование не активно", show_alert=True)
                except:
                    pass
                return
        
        # Сохраняем пользователя в кэш
        save_user_to_cache(user)
        
        # Обработка действия с блокировкой
        with voting_data_lock:
            if call.data == "vote_yes":
                # Удаляем из НЕТ, если был там
                if user_id in voting_data['no_voters']:
                    del voting_data['no_voters'][user_id]
                
                # Добавляем в ДА
                voting_data['yes_voters'][user_id] = voting_data['user_cache'][user_id]
                
                log_action("✅ ДА", display_name)
                
            elif call.data == "vote_no":
                # Удаляем из ДА, если был там
                if user_id in voting_data['yes_voters']:
                    del voting_data['yes_voters'][user_id]
                
                # Добавляем в НЕТ
                voting_data['no_voters'][user_id] = voting_data['user_cache'][user_id]
                
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
                    'timestamp': datetime.now(MOSCOW_TZ).isoformat()
                }
                
                voting_data['plus_one_voters'][user_id].append(guest_data)
                guest_count = len(voting_data['plus_one_voters'][user_id])
                
                try:
                    bot.answer_callback_query(
                        call.id,
                        f"✅ Добавлен гость: {guest_name}\nВсего гостей: {guest_count}",
                        show_alert=False
                    )
                except:
                    pass
                
                log_action("➕ ГОСТЬ", display_name, f"({guest_name})")
                
            elif call.data == "minus_one":
                # Удаление последнего гостя
                if user_id not in voting_data['plus_one_voters'] or not voting_data['plus_one_voters'][user_id]:
                    try:
                        bot.answer_callback_query(call.id, "❌ У вас нет гостей!", show_alert=True)
                    except:
                        pass
                    return
                
                removed = voting_data['plus_one_voters'][user_id].pop()
                guest_name = removed.get('guest_name', 'Гость')
                
                if not voting_data['plus_one_voters'][user_id]:
                    del voting_data['plus_one_voters'][user_id]
                
                try:
                    bot.answer_callback_query(call.id, f"✅ Убран гость: {guest_name}", show_alert=False)
                except:
                    pass
                
                log_action("➖ ГОСТЬ", display_name, f"(удален {guest_name})")
        
        # Обновляем все сообщения после каждого действия (вне блокировки)
        update_all_messages()
        
    except Exception as e:
        print(f"Ошибка обработки нажатия: {e}")
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, "❌ Произошла ошибка", show_alert=True)
        except:
            pass

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
    try:
        confirm = bot.send_message(message.chat.id, "✅ Голосование запущено!")
        time.sleep(3)
        safe_delete(confirm.message_id, message.chat.id)
    except Exception as e:
        print(f"Ошибка отправки подтверждения: {e}")

@bot.message_handler(commands=['restart'])
def cmd_restart(message):
    """Быстрая команда: перезапуск сообщения с результатами"""
    user_id = message.from_user.id
    
    if not is_admin(user_id, message.chat.id):
        bot.reply_to(message, "❌ Только для администраторов!")
        return
    
    # Удаляем команду
    safe_delete(message.message_id, message.chat.id)
    
    # Проверяем, есть ли активное голосование
    with voting_data_lock:
        if not voting_data['voting_message_id']:
            try:
                confirm = bot.send_message(message.chat.id, "❌ Нет активного голосования. Используйте /start")
                time.sleep(3)
                safe_delete(confirm.message_id, message.chat.id)
            except:
                pass
            return
        
        # Запоминаем старый ID для удаления
        old_results_id = voting_data['results_message_id']
        voting_data['results_message_id'] = None
    
    # Удаляем старое сообщение с результатами, если оно есть
    if old_results_id:
        safe_delete(old_results_id)
    
    # Создаем новое сообщение с результатами
    try:
        results_msg = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=get_results_text(),
            parse_mode='Markdown'
        )
        
        with voting_data_lock:
            voting_data['results_message_id'] = results_msg.message_id
        
        # Отправляем подтверждение
        confirm = bot.send_message(message.chat.id, "✅ Сообщение с результатами перезапущено!")
        time.sleep(3)
        safe_delete(confirm.message_id, message.chat.id)
    except Exception as e:
        print(f"Ошибка перезапуска: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['third'])
def cmd_third(message):
    """Быстрая команда: создать третье сообщение сейчас"""
    user_id = message.from_user.id
    
    if not is_admin(user_id, message.chat.id):
        bot.reply_to(message, "❌ Только для администраторов!")
        return
    
    # Удаляем команду
    safe_delete(message.message_id, message.chat.id)
    
    # Проверяем, есть ли активное голосование
    with voting_data_lock:
        if not voting_data['voting_message_id']:
            try:
                confirm = bot.send_message(message.chat.id, "❌ Нет активного голосования. Используйте /start")
                time.sleep(3)
                safe_delete(confirm.message_id, message.chat.id)
            except:
                pass
            return
    
    # Создаем третье сообщение
    create_third_message()
    
    # Отправляем подтверждение
    try:
        confirm = bot.send_message(message.chat.id, "✅ Третье сообщение создано!")
        time.sleep(3)
        safe_delete(confirm.message_id, message.chat.id)
    except Exception as e:
        print(f"Ошибка: {e}")

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
    with voting_data_lock:
        voting_data['yes_voters'] = {}
        voting_data['no_voters'] = {}
        voting_data['plus_one_voters'] = {}
        voting_data['user_cache'] = {}
    
    # Обновляем сообщения
    update_all_messages()
    
    # Отправляем подтверждение
    try:
        confirm = bot.send_message(message.chat.id, "✅ Все данные голосования очищены!")
        time.sleep(3)
        safe_delete(confirm.message_id, message.chat.id)
    except Exception as e:
        print(f"Ошибка: {e}")

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

🔹 /start - Запустить голосование (создает 2 сообщения)
🔹 /restart - Перезапустить сообщение с результатами (удаляет старое)
🔹 /third - Создать третье сообщение сейчас
🔹 /clear - Очистить все данные голосования
🔹 /help - Показать эту справку

*Расписание:*
📅 Голосование: ежедневно в 12:00 МСК
📅 Третье сообщение: ежедневно в 18:00 МСК

*Как голосовать:*
✅ ДА - вы идете
❌ НЕТ - вы не идете
➕ +1 ГОСТЬ - добавить гостя
➖ -1 ГОСТЬ - убрать последнего гостя

*Примечание:*
- Гостей можно добавлять даже без выбора ДА
- Все сообщения обновляются автоматически
- Голосование активно до следующего /start или 12:00 следующего дня
    """
    
    try:
        msg = bot.send_message(message.chat.id, help_text, parse_mode='Markdown')
        time.sleep(10)
        safe_delete(msg.message_id, message.chat.id)
    except Exception as e:
        print(f"Ошибка отправки help: {e}")

# ====== ПЛАНИРОВЩИК ЗАДАЧ ======

def get_next_run_time(time_str):
    """Получение следующего времени запуска в UTC для schedule"""
    now_moscow = datetime.now(MOSCOW_TZ)
    hour, minute = map(int, time_str.split(':'))
    
    # Создаем время выполнения сегодня
    run_time_moscow = now_moscow.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # Если время уже прошло, переносим на завтра
    if run_time_moscow <= now_moscow:
        run_time_moscow += timedelta(days=1)
    
    # Конвертируем в UTC
    run_time_utc = run_time_moscow.astimezone(pytz.UTC)
    return run_time_utc.strftime("%H:%M")

def run_scheduler():
    """Запуск планировщика в отдельном потоке с защитой от сбоев"""
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
            consecutive_errors = 0  # Сбрасываем счетчик при успехе
        except Exception as e:
            consecutive_errors += 1
            print(f"Ошибка планировщика ({consecutive_errors}): {e}")
            traceback.print_exc()
            
            if consecutive_errors > max_consecutive_errors:
                print("⚠️ СЛИШКОМ МНОГО ОШИБОК. Перезапуск планировщика...")
                setup_scheduler()  # Перезагружаем расписание
                consecutive_errors = 0
            
            # Экспоненциальная задержка
            time.sleep(5 * min(consecutive_errors, 6))

def setup_scheduler():
    """Настройка расписания с учетом часового пояса"""
    schedule.clear()
    
    # Получаем следующее время запуска в UTC
    voting_utc = get_next_run_time(VOTING_TIME)
    third_utc = get_next_run_time(NOTIFICATION_TIME)
    
    # Планируем задачи
    schedule.every().day.at(voting_utc).do(create_voting)
    schedule.every().day.at(third_utc).do(create_third_message)
    
    print(f"📅 Расписание:")
    print(f"   - Голосование: {VOTING_TIME} МСК (след. запуск в {voting_utc} UTC)")
    print(f"   - 3-е сообщение: {NOTIFICATION_TIME} МСК (след. запуск в {third_utc} UTC)")

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
    scheduler_thread = Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    print("✅ Планировщик задач запущен")
    
    print("=" * 50)
    print("🔄 БОТ РАБОТАЕТ. ОЖИДАНИЕ КОМАНД...")
    print("=" * 50)
    
    # Запуск бота с улучшенной обработкой ошибок
    retry_count = 0
    max_retries = 10
    
    while True:
        try:
            # Используем параметры, оптимальные для BotHost
            bot.polling(none_stop=True, interval=1, timeout=30, long_polling_timeout=30)
        except Exception as e:
            retry_count += 1
            print(f"❌ Ошибка polling (попытка {retry_count}): {e}")
            traceback.print_exc()
            
            if retry_count > max_retries:
                print("⚠️ СЛИШКОМ МНОГО ПОПЫТОК. Ожидание 5 минут...")
                time.sleep(300)
                retry_count = 0
            else:
                # Экспоненциальная задержка
                wait_time = min(30 * retry_count, 300)
                print(f"🔄 Перезапуск через {wait_time} секунд...")
                time.sleep(wait_time)

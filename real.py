import telebot
import schedule
import time
import random
from threading import Thread
from datetime import datetime
from telebot import types
import pytz  

# ====== НАСТРОЙКИ ======
TOKEN = "8568812025:AAHL-u8tquSPxlBW8ZEXz2wv4oi0z8R6r3U"  # Вставьте ваш токен
GROUP_CHAT_ID = -1003685818116 # ID вашей группы (должен начинаться с -)
ADMIN_USERNAME = "Ravenskort"  # Username администратора

# Время публикации (24-часовой формат, указываем МСК)
VOTING_TIME = "20:32"  # Время отправки сообщения с кнопками (по Москве)
NOTIFICATION_TIME = "20:33"  # Время отправки финального сообщения "Жду на Тушинской" (по Москве)

# Устанавливаем часовой пояс (Москва)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Список случайных имен для гостей
GUEST_NAMES = [
    "Шефан Карри", "ЛеБрик", "Вестбрик", "Шакал О'Нил", 
    "Черная Мамба", "Джокер", "Грик Фрик", "Флоппер", 
    "Просто Бен Симмонс"
]

# Словарь для хранения данных о голосовании
current_voting = {
    'voting_message_id': None,  # ID сообщения с кнопками
    'results_message_id': None, # ID сообщения с результатами
    'notification_message_id': None,  # ID финального сообщения
    'date': None,
    'yes_voters': {},  # user_id: user_data (основные голоса)
    'no_voters': {},   # user_id: user_data
    'plus_one_voters': {},  # user_id: список гостей (теперь храним списки)
    'user_cache': {},  # Кэш данных о пользователях для тех, кто только добавляет гостей
}

# ====== ИНИЦИАЛИЗАЦИЯ БОТА ======
bot = telebot.TeleBot(TOKEN)

# ====== ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ ИМЕНИ ПОЛЬЗОВАТЕЛЯ ======
def get_user_display_name(user):
    """Возвращает отображаемое имя пользователя в формате nickname(username)"""
    display_name = ""
    
    if user.first_name:
        display_name = user.first_name
        if user.last_name:
            display_name += f" {user.last_name}"
    
    if user.username:
        if display_name:
            display_name += f"(@{user.username})"
        else:
            display_name = f"@{user.username}"
    elif not display_name:
        display_name = f"Участник {user.id}"
    
    return display_name

# ====== ФУНКЦИЯ ДЛЯ СОХРАНЕНИЯ ДАННЫХ ПОЛЬЗОВАТЕЛЯ ======
def save_user_data(user):
    """Сохраняет данные пользователя в кэш"""
    user_id = user.id
    display_name = get_user_display_name(user)
    
    user_data = {
        'user_id': user_id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'display_name': display_name,
        'is_bot': user.is_bot,
    }
    
    # Сохраняем в кэш для пользователей, которые только добавляют гостей
    current_voting['user_cache'][user_id] = user_data
    return user_data

# ====== ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ ИМЕНИ ПОЛЬЗОВАТЕЛЯ ИЗ КЭША ======
def get_user_display_name_from_cache(user_id):
    """Получает отображаемое имя пользователя из кэша"""
    if user_id in current_voting['user_cache']:
        return current_voting['user_cache'][user_id]['display_name']
    elif user_id in current_voting['yes_voters']:
        return current_voting['yes_voters'][user_id]['display_name']
    elif user_id in current_voting['no_voters']:
        return current_voting['no_voters'][user_id]['display_name']
    else:
        return f"Участник {user_id}"

# ====== ФУНКЦИЯ ДЛЯ ПРОВЕРКИ АДМИНИСТРАТОРА ======
def is_admin(user):
    """Проверяет, является ли пользователь администратором"""
    return user.username == ADMIN_USERNAME

# ====== ФУНКЦИЯ ДЛЯ УДАЛЕНИЯ СООБЩЕНИЯ ======
def delete_message_safe(chat_id, message_id):
    """Безопасно удаляет сообщение"""
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

# ====== ФУНКЦИЯ ДЛЯ ОБРАБОТКИ КОМАНД АДМИНА ======
def handle_admin_command(message, command_func, *args):
    """Обрабатывает команду администратора: удаляет сообщение и выполняет команду"""
    # Удаляем команду
    delete_message_safe(message.chat.id, message.message_id)
    
    # Проверяем права администратора
    if not is_admin(message.from_user):
        # Отправляем сообщение об ошибке и удаляем его через 3 секунды
        msg = bot.reply_to(message, "❌ Эта команда только для администратора!")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        return
    
    # Выполняем команду
    try:
        command_func(message, *args)
    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== ФУНКЦИЯ ЛОГИРОВАНИЯ ГОЛОСОВАНИЯ ======
def log_vote(user_id, user_name, vote_type, guest_count=0):
    """Логирует информацию о голосовании"""
    moscow_time = datetime.now(MOSCOW_TZ).strftime("%H:%M:%S")
    log_message = f"[{moscow_time}] "
    
    if vote_type == "yes":
        log_message += f"✅ {user_name} (ID: {user_id}) проголосовал за 'Да'"
    elif vote_type == "no":
        log_message += f"❌ {user_name} (ID: {user_id}) проголосовал за 'Нет'"
    elif vote_type == "plus_one":
        log_message += f"➕ {user_name} (ID: {user_id}) добавил +1 (всего: {guest_count})"
    elif vote_type == "minus_one":
        log_message += f"➖ {user_name} (ID: {user_id}) убрал +1 (осталось: {guest_count})"
    elif vote_type == "change_yes_to_no":
        log_message += f"🔄 {user_name} (ID: {user_id}) изменил голос с 'Да' на 'Нет'"
    elif vote_type == "change_no_to_yes":
        log_message += f"🔄 {user_name} (ID: {user_id}) изменил голос с 'Нет' на 'Да'"
    
    print(log_message)

# ====== ФУНКЦИЯ СОЗДАНИЯ СООБЩЕНИЙ С КНОПКАМИ И РЕЗУЛЬТАТАМИ ======
def create_daily_voting():
    """Создает сообщение с кнопками и сообщение с результатами в группе в заданное время"""
    try:
        # Текущее время по Москве
        moscow_now = datetime.now(MOSCOW_TZ)
        
        # Сбрасываем данные о предыдущем голосовании
        global current_voting
        current_voting = {
            'voting_message_id': None,
            'results_message_id': None,
            'notification_message_id': None,
            'date': moscow_now,
            'yes_voters': {},
            'no_voters': {},
            'plus_one_voters': {},  # Храним списки гостей для каждого пользователя
            'user_cache': {},  # Кэш данных о пользователях для тех, кто только добавляет гостей
        }
        
        # 1. СОЗДАЕМ СООБЩЕНИЕ С КНОПКАМИ
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        
        # Первый ряд: основные кнопки Да/Нет
        btn_yes = types.InlineKeyboardButton(text="✅ Да", callback_data="vote_yes")
        btn_no = types.InlineKeyboardButton(text="❌ Нет", callback_data="vote_no")
        
        # Второй ряд: кнопки +1 и -1
        btn_plus_one = types.InlineKeyboardButton(text="➕ +1", callback_data="plus_one")
        btn_minus_one = types.InlineKeyboardButton(text="➖ -1", callback_data="minus_one")
        
        keyboard.add(btn_yes, btn_no)
        keyboard.add(btn_plus_one, btn_minus_one)
        
        voting_text = "🏀 *Тренировка на Тушинской сегодня*\n\nВыберите вариант:"
        voting_message = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=voting_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
        # Сохраняем ID сообщения с кнопками
        current_voting['voting_message_id'] = voting_message.message_id
        
        # 2. СОЗДАЕМ СООБЩЕНИЕ С РЕЗУЛЬТАТАМИ (изначально пустое)
        results_text = "🏀 *На тренировку идут:*\n\n"
        results_text += "_Пока никто не проголосовал за 'Да'_ 😔"
        
        results_message = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=results_text,
            parse_mode='Markdown'
        )
        
        # Сохраняем ID сообщения с результатами
        current_voting['results_message_id'] = results_message.message_id
        
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ✅ Голосование создано")
        
    except Exception as e:
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ❌ Ошибка при создании голосования: {e}")

# ====== ОБНОВЛЕНИЕ СООБЩЕНИЯ С РЕЗУЛЬТАТАМИ ======
def update_results_message():
    """Обновляет сообщение с результатами"""
    if not current_voting['results_message_id']:
        return
    
    try:
        # Формируем текст сообщения
        results_text = "🏀 *На тренировку идут:*\n\n"
        
        # Собираем все записи тех, кто голосует за "Да" (включая их гостей)
        all_entries = []
        
        # Добавляем тех, кто голосует за "Да"
        for user_id, user_data in current_voting['yes_voters'].items():
            display_name = user_data.get('display_name', f'Участник {user_id}')
            all_entries.append(f"{display_name}")
            
            # Добавляем гостей этого пользователя
            if user_id in current_voting['plus_one_voters']:
                guest_list = current_voting['plus_one_voters'][user_id]
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_entries.append(f"{guest_name} от {display_name}")
        
        # Теперь добавляем гостей пользователей, которые не голосовали за "Да"
        for user_id, guest_list in current_voting['plus_one_voters'].items():
            # Если пользователь не в списке "Да"
            if user_id not in current_voting['yes_voters']:
                # Получаем имя пользователя из кэша или создаем базовое
                display_name = get_user_display_name_from_cache(user_id)
                
                # Добавляем гостей этого пользователя
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_entries.append(f"{guest_name} от {display_name}")
        
        if all_entries:
            for i, entry in enumerate(all_entries, 1):
                results_text += f"{i}. {entry}\n"
        else:
            results_text += "_Пока никто не проголосовал за 'Да'_ 😔"
        
        # Обновляем сообщение с результатами
        bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=current_voting['results_message_id'],
            text=results_text,
            parse_mode='Markdown'
        )
        
        # Также обновляем уведомительное сообщение, если оно уже было создано
        update_notification_message()
        
        total_yes = len(current_voting['yes_voters'])
        total_guests = sum(len(guests) for guests in current_voting['plus_one_voters'].values())
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] 📊 Статистика: Да: {total_yes}, гостей: {total_guests}")
        
    except Exception as e:
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ❌ Ошибка при обновлении сообщения с результатами: {e}")

# ====== ОБНОВЛЕНИЕ СООБЩЕНИЯ С КНОПКАМИ ======
def update_voting_message():
    """Обновляет сообщение с кнопками, показывая текущие результаты"""
    if not current_voting['voting_message_id']:
        return
    
    try:
        # Подсчитываем результаты
        yes_count = len(current_voting['yes_voters'])
        no_count = len(current_voting['no_voters'])
        total_guests = sum(len(guests) for guests in current_voting['plus_one_voters'].values())
        total_people = yes_count + total_guests
        
        # Формируем обновленный текст (как было раньше)
        message_text = f"🏀 *Тренировка на Тушинской сегодня*\n\n"
        message_text += f"✅ Да: {yes_count} человек\n"
        message_text += f"❌ Нет: {no_count} человек\n"
        message_text += f"👥 Всего: {yes_count + no_count}\n\n"
        message_text += "Выберите вариант:"
        
        # Создаем клавиатуру с кнопками
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        
        # Первый ряд: основные кнопки Да/Нет
        btn_yes = types.InlineKeyboardButton(text="✅ Да", callback_data="vote_yes")
        btn_no = types.InlineKeyboardButton(text="❌ Нет", callback_data="vote_no")
        
        # Второй ряд: кнопки +1 и -1
        btn_plus_one = types.InlineKeyboardButton(text="➕ +1", callback_data="plus_one")
        btn_minus_one = types.InlineKeyboardButton(text="➖ -1", callback_data="minus_one")
        
        keyboard.add(btn_yes, btn_no)
        keyboard.add(btn_plus_one, btn_minus_one)
        
        # Обновляем сообщение
        bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=current_voting['voting_message_id'],
            text=message_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
    except Exception as e:
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ❌ Ошибка при обновлении сообщения с кнопками: {e}")

# ====== ФУНКЦИЯ ДЛЯ ОБНОВЛЕНИЯ УВЕДОМИТЕЛЬНОГО СООБЩЕНИЯ ======
def update_notification_message():
    """Обновляет уведомительное сообщение (третье сообщение)"""
    if not current_voting['notification_message_id']:
        return
    
    try:
        # Получаем список всех, кто идет (Да + гости)
        all_going = []
        
        # Те, кто голосует за "Да"
        for user_id, user_data in current_voting['yes_voters'].items():
            display_name = user_data.get('display_name', f'Участник {user_id}')
            all_going.append(display_name)
            
            # Добавляем гостей этого пользователя
            if user_id in current_voting['plus_one_voters']:
                guest_list = current_voting['plus_one_voters'][user_id]
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_going.append(f"{guest_name} от {display_name}")
        
        # Теперь добавляем гостей пользователей, которые не голосовали за "Да"
        for user_id, guest_list in current_voting['plus_one_voters'].items():
            # Если пользователь не в списке "Да"
            if user_id not in current_voting['yes_voters']:
                # Получаем имя пользователя из кэша
                display_name = get_user_display_name_from_cache(user_id)
                
                # Добавляем гостей этого пользователя
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_going.append(f"{guest_name} от {display_name}")
        
        # Формируем текст уведомительного сообщения
        notification_text = "Жду на Тушинской с 19:00"
        
        if all_going:
            for entry in all_going:
                notification_text += f", {entry}"
        else:
            notification_text += " (пока никто)"
        
        # Обновляем сообщение
        bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=current_voting['notification_message_id'],
            text=notification_text,
            parse_mode=None  # Без разметки
        )
        
    except Exception as e:
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ❌ Ошибка при обновлении уведомительного сообщения: {e}")

# ====== ФУНКЦИЯ ДЛЯ СОЗДАНИЯ УВЕДОМИТЕЛЬНОГО СООБЩЕНИЯ ======
def create_notification_message():
    """Создает уведомительное сообщение в заданное время"""
    try:
        # Получаем список всех, кто идет (Да + гости)
        all_going = []
        
        # Те, кто голосует за "Да"
        for user_id, user_data in current_voting['yes_voters'].items():
            display_name = user_data.get('display_name', f'Участник {user_id}')
            all_going.append(display_name)
            
            # Добавляем гостей этого пользователя
            if user_id in current_voting['plus_one_voters']:
                guest_list = current_voting['plus_one_voters'][user_id]
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_going.append(f"{guest_name} от {display_name}")
        
        # Теперь добавляем гостей пользователей, которые не голосовали за "Да"
        for user_id, guest_list in current_voting['plus_one_voters'].items():
            # Если пользователь не в списке "Да"
            if user_id not in current_voting['yes_voters']:
                # Получаем имя пользователя из кэша
                display_name = get_user_display_name_from_cache(user_id)
                
                # Добавляем гостей этого пользователя
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_going.append(f"{guest_name} от {display_name}")
        
        # Формируем текст уведомительного сообщения
        notification_text = "Жду на Тушинской с 19:00"
        
        if all_going:
            for entry in all_going:
                notification_text += f", {entry}"
        else:
            notification_text += " (пока никто)"
        
        # Отправляем сообщение
        notification_message = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=notification_text,
            parse_mode=None  # Без разметки
        )
        
        # Сохраняем ID уведомительного сообщения
        current_voting['notification_message_id'] = notification_message.message_id
        
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] 📢 Уведомительное сообщение создано")
        
    except Exception as e:
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ❌ Ошибка при создании уведомительного сообщения: {e}")

# ====== ОБРАБОТЧИК НАЖАТИЯ КНОПОК ======
@bot.callback_query_handler(func=lambda call: True)
def handle_button_click(call):
    """Обрабатывает нажатия на кнопки"""
    user_id = call.from_user.id
    user = call.from_user  # Объект пользователя
    
    # Получаем отображаемое имя
    display_name = get_user_display_name(user)
    
    if call.data == "vote_yes":
        # Убираем из "Нет" если пользователь там был
        was_no = user_id in current_voting['no_voters']
        if was_no:
            del current_voting['no_voters'][user_id]
        
        # Сохраняем данные пользователя
        save_user_data(user)
        
        # Добавляем в "Да" с полной информацией
        user_data = {
            'user_id': user_id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'display_name': display_name,
            'is_bot': user.is_bot,
        }
        current_voting['yes_voters'][user_id] = user_data
        
        # Отправляем подтверждение
        bot.answer_callback_query(
            callback_query_id=call.id,
            text="✅ Вы выбрали 'Да'!",
            show_alert=False
        )
        
        # Логируем голос
        if was_no:
            log_vote(user_id, display_name, "change_no_to_yes")
        else:
            log_vote(user_id, display_name, "yes")
        
    elif call.data == "vote_no":
        # Убираем из "Да" если пользователь там был
        was_yes = user_id in current_voting['yes_voters']
        if was_yes:
            del current_voting['yes_voters'][user_id]
            # НЕ удаляем его гостей, даже если он уходит из "Да"
            # Теперь гости могут быть и без "Да"
        
        # Сохраняем данные пользователя
        save_user_data(user)
        
        # Добавляем в "Нет" с полной информацией
        user_data = {
            'user_id': user_id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'display_name': display_name,
            'is_bot': user.is_bot
        }
        current_voting['no_voters'][user_id] = user_data
        
        # Отправляем подтверждение
        bot.answer_callback_query(
            callback_query_id=call.id,
            text="❌ Вы выбрали 'Нет'!",
            show_alert=False
        )
        
        # Логируем голос
        if was_yes:
            log_vote(user_id, display_name, "change_yes_to_no")
        else:
            log_vote(user_id, display_name, "no")
    
    elif call.data == "plus_one":
        # МОЖНО добавлять гостей БЕЗ выбора "Да"
        
        # Сохраняем данные пользователя в кэш
        save_user_data(user)
        
        # Получаем или создаем список гостей для этого пользователя
        if user_id not in current_voting['plus_one_voters']:
            current_voting['plus_one_voters'][user_id] = []
        
        # Выбираем случайное имя из списка
        guest_name = random.choice(GUEST_NAMES)
        
        # Добавляем нового гостя в список
        guest_data = {
            'guest_name': guest_name,
            'host_name': display_name,
            'host_id': user_id,
            'timestamp': datetime.now(MOSCOW_TZ)
        }
        current_voting['plus_one_voters'][user_id].append(guest_data)
        
        # Номер гостя (сколько уже добавил)
        guest_count = len(current_voting['plus_one_voters'][user_id])
        
        # Отправляем подтверждение
        bot.answer_callback_query(
            callback_query_id=call.id,
            text=f"✅ Добавлен гость: {guest_name}! Всего гостей: {guest_count}",
            show_alert=False
        )
        
        # Логируем голос
        log_vote(user_id, display_name, "plus_one", guest_count)
    
    elif call.data == "minus_one":
        # Проверяем только наличие добавленных гостей
        if user_id not in current_voting['plus_one_voters'] or not current_voting['plus_one_voters'][user_id]:
            bot.answer_callback_query(
                callback_query_id=call.id,
                text="❌ У вас нет добавленных гостей!",
                show_alert=True
            )
            return
        
        # Удаляем последнего добавленного гостя
        guest_list = current_voting['plus_one_voters'][user_id]
        removed_guest = guest_list.pop()
        guest_name = removed_guest.get('guest_name', 'не указан')
        
        # Если список гостей стал пустым, удаляем запись пользователя
        if not guest_list:
            del current_voting['plus_one_voters'][user_id]
        
        # Оставшееся количество гостей
        remaining_guests = len(current_voting['plus_one_voters'].get(user_id, []))
        
        # Отправляем подтверждение
        confirmation_text = f"✅ Убран гость: {guest_name}"
        if remaining_guests > 0:
            confirmation_text += f"\nОсталось гостей: {remaining_guests}"
        
        bot.answer_callback_query(
            callback_query_id=call.id,
            text=confirmation_text,
            show_alert=False
        )
        
        # Логируем голос
        log_vote(user_id, display_name, "minus_one", remaining_guests)
    
    # ОБНОВЛЯЕМ ВСЕ СООБЩЕНИЯ ПОСЛЕ КАЖДОГО ДЕЙСТВИЯ
    update_voting_message()
    update_results_message()

# ====== КОМАНДА ДЛЯ РУЧНОГО ДОБАВЛЕНИЯ ПОЛЬЗОВАТЕЛЕЙ ======
@bot.message_handler(commands=['add_yes'])
def add_yes_manually(message):
    """Ручное добавление пользователя в список 'Да'"""
    handle_admin_command(message, _add_yes_manually_impl)

def _add_yes_manually_impl(message):
    """Реализация команды добавления пользователя в список 'Да'"""
    try:
        # Получаем аргументы из команды
        parts = message.text.split(maxsplit=3)
        if len(parts) < 2:
            msg = bot.reply_to(message, "❌ Используйте: /add_yes nickname [username] [гости]\nПример: /add_yes Иван ivan123 2\nИли: /add_yes @username")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return
        
        nickname = parts[1].replace('@', '')  # Убираем @ если есть
        
        # Пытаемся получить username из второго аргумента (если есть)
        username = None
        guest_count = 0
        
        if len(parts) > 2:
            # Проверяем, является ли второй аргумент числом (количеством гостей)
            if parts[2].isdigit():
                guest_count = int(parts[2])
            else:
                username = parts[2].replace('@', '')
                # Проверяем третий аргумент на количество гостей
                if len(parts) > 3 and parts[3].isdigit():
                    guest_count = int(parts[3])
        
        # Формируем отображаемое имя в формате nickname(username)
        if username:
            display_name = f"{nickname}(@{username})"
        else:
            # Проверяем, похоже ли на username (без русских букв)
            if any(c.isalpha() and ord(c) > 127 for c in nickname):
                # Есть русские буквы - считаем nickname
                display_name = nickname
            else:
                # Нет русских букв - считаем username
                display_name = f"@{nickname}"
        
        # Генерируем фиктивный ID (отрицательный для ручных добавлений)
        fake_user_id = -len(current_voting['yes_voters']) - 1000
        
        # Сохраняем в кэш
        current_voting['user_cache'][fake_user_id] = {
            'user_id': fake_user_id,
            'username': username,
            'first_name': nickname if username else None,
            'last_name': None,
            'display_name': display_name,
            'is_bot': False,
            'added_manually': True,
        }
        
        # Добавляем в список "Да"
        current_voting['yes_voters'][fake_user_id] = current_voting['user_cache'][fake_user_id]
        
        # Добавляем гостей, если указано
        if guest_count > 0:
            if fake_user_id not in current_voting['plus_one_voters']:
                current_voting['plus_one_voters'][fake_user_id] = []
            
            for i in range(guest_count):
                guest_name = random.choice(GUEST_NAMES)
                current_voting['plus_one_voters'][fake_user_id].append({
                    'guest_name': guest_name,
                    'host_name': display_name,
                    'host_id': fake_user_id,
                    'added_manually': True
                })
        
        # Логируем ручное добавление
        moscow_now = datetime.now(MOSCOW_TZ)
        if guest_count > 0:
            print(f"[{moscow_now.strftime('%H:%M:%S')}] 👑 АДМИН добавил вручную: {display_name} -> 'Да' с {guest_count} гостями")
        else:
            print(f"[{moscow_now.strftime('%H:%M:%S')}] 👑 АДМИН добавил вручную: {display_name} -> 'Да'")
        
        # Обновляем сообщения
        update_voting_message()
        update_results_message()
        
        # Отправляем подтверждение и удаляем через 3 секунды
        if guest_count > 0:
            msg = bot.reply_to(message, f"✅ Пользователь '{display_name}' добавлен в список 'Да' с {guest_count} гостями")
        else:
            msg = bot.reply_to(message, f"✅ Пользователь '{display_name}' добавлен в список 'Да'")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        
    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== КОМАНДА ДЛЯ УДАЛЕНИЯ ПОЛЬЗОВАТЕЛЯ ======
@bot.message_handler(commands=['remove'])
def remove_voter(message):
    """Удалить пользователя из списка"""
    handle_admin_command(message, _remove_voter_impl)

def _remove_voter_impl(message):
    """Реализация команды удаления пользователя"""
    try:
        parts = message.text.split()
        if len(parts) < 2:
            msg = bot.reply_to(message, "❌ Используйте: /remove имя\nМожно использовать часть имени или username")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return
        
        search_term = parts[1].replace('@', '').lower()
        
        # Ищем и удаляем пользователя из всех списков
        removed = False
        removed_name = ""
        list_type = ""
        
        # Ищем в "Да"
        for user_id, user_data in list(current_voting['yes_voters'].items()):
            display_name = user_data.get('display_name', '').lower()
            username = user_data.get('username', '').lower() if user_data.get('username') else ''
            first_name = user_data.get('first_name', '').lower() if user_data.get('first_name') else ''
            
            if (search_term in display_name or 
                search_term in username or 
                search_term in first_name):
                
                del current_voting['yes_voters'][user_id]
                # Также удаляем его гостей, если они есть
                if user_id in current_voting['plus_one_voters']:
                    guest_count = len(current_voting['plus_one_voters'][user_id])
                    del current_voting['plus_one_voters'][user_id]
                    removed = True
                    removed_name = user_data.get('display_name', 'Unknown')
                    list_type = "'Да'"
                    if guest_count > 0:
                        removed_name += f" (+{guest_count})"
                else:
                    removed = True
                    removed_name = user_data.get('display_name', 'Unknown')
                    list_type = "'Да'"
                break
        
        # Ищем в "Нет"
        if not removed:
            for user_id, user_data in list(current_voting['no_voters'].items()):
                display_name = user_data.get('display_name', '').lower()
                username = user_data.get('username', '').lower() if user_data.get('username') else ''
                first_name = user_data.get('first_name', '').lower() if user_data.get('first_name') else ''
                
                if (search_term in display_name or 
                    search_term in username or 
                    search_term in first_name):
                    
                    del current_voting['no_voters'][user_id]
                    removed = True
                    removed_name = user_data.get('display_name', 'Unknown')
                    list_type = "'Нет'"
                    break
        
        # Ищем в кэше (пользователи, которые только добавляли гостей)
        if not removed:
            for user_id, user_data in list(current_voting['user_cache'].items()):
                display_name = user_data.get('display_name', '').lower()
                username = user_data.get('username', '').lower() if user_data.get('username') else ''
                first_name = user_data.get('first_name', '').lower() if user_data.get('first_name') else ''
                
                if (search_term in display_name or 
                    search_term in username or 
                    search_term in first_name):
                    
                    # Удаляем из кэша
                    del current_voting['user_cache'][user_id]
                    # Удаляем его гостей, если они есть
                    if user_id in current_voting['plus_one_voters']:
                        guest_count = len(current_voting['plus_one_voters'][user_id])
                        del current_voting['plus_one_voters'][user_id]
                        removed = True
                        removed_name = user_data.get('display_name', 'Unknown')
                        list_type = "'Только гости'"
                        if guest_count > 0:
                            removed_name += f" (+{guest_count})"
                    break
        
        if removed:
            # Логируем удаление
            moscow_now = datetime.now(MOSCOW_TZ)
            print(f"[{moscow_now.strftime('%H:%M:%S')}] 👑 АДМИН удалил: {removed_name} из списка {list_type}")
            
            update_voting_message()
            update_results_message()
            
            # Отправляем подтверждение и удаляем через 3 секунды
            msg = bot.reply_to(message, f"✅ Пользователь '{removed_name}' удален из списка {list_type}")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
        else:
            msg = bot.reply_to(message, f"❌ Пользователь не найден")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
        
    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== КОМАНДА ДЛЯ ПРОСМОТРА ТЕКУЩЕЙ СТАТИСТИКИ ======
@bot.message_handler(commands=['stats'])
def show_stats(message):
    """Показать текущую статистику голосования"""
    handle_admin_command(message, _show_stats_impl)

def _show_stats_impl(message):
    """Реализация команды показа статистики"""
    yes_count = len(current_voting['yes_voters'])
    no_count = len(current_voting['no_voters'])
    total_guests = sum(len(guests) for guests in current_voting['plus_one_voters'].values())
    total_people = yes_count + total_guests
    
    # ДОБАВЛЯЕМ: Информация о пользователях с только гостями
    users_with_only_guests = sum(1 for user_id in current_voting['plus_one_voters'] 
                                if user_id not in current_voting['yes_voters'])
    
    stats_text = f"📊 *Текущая статистика голосования:*\n\n"
    stats_text += f"✅ Да: {yes_count} человек\n"
    stats_text += f"❌ Нет: {no_count} человек\n"
    stats_text += f"➕ Гостей: {total_guests} человек\n"
    stats_text += f"👥 Всего идут: {total_people} человек\n"
    
    if users_with_only_guests > 0:
        stats_text += f"👥 Только гости (без 'Да'): {users_with_only_guests} чел.\n"
    
    stats_text += "\n"
    
    if yes_count > 0:
        stats_text += "*Проголосовали 'Да':*\n"
        for i, user_data in enumerate(current_voting['yes_voters'].values(), 1):
            display_name = user_data.get('display_name', 'Unknown')
            user_id = user_data.get('user_id')
            guest_count = len(current_voting['plus_one_voters'].get(user_id, []))
            if guest_count > 0:
                stats_text += f"{i}. {display_name} (+{guest_count})\n"
            else:
                stats_text += f"{i}. {display_name}\n"
    
    # Отправляем статистику
    msg = bot.reply_to(message, stats_text, parse_mode='Markdown')
    # Не удаляем статистику автоматически
    
# ====== КОМАНДА ДЛА ПОКАЗА СПИСКА ВСЕХ ГОЛОСОВАВШИХ ======
@bot.message_handler(commands=['list'])
def show_all_voters(message):
    """Показать всех проголосовавших"""
    handle_admin_command(message, _show_all_voters_impl)

def _show_all_voters_impl(message):
    """Реализация команды показа всех голосовавших"""
    yes_count = len(current_voting['yes_voters'])
    no_count = len(current_voting['no_voters'])
    total_guests = sum(len(guests) for guests in current_voting['plus_one_voters'].values())
    
    response = "👥 *Все проголосовавшие:*\n\n"
    
    if yes_count > 0:
        response += "✅ *За 'Да':*\n"
        for i, user_data in enumerate(current_voting['yes_voters'].values(), 1):
            display_name = user_data.get('display_name', 'Unknown')
            user_id = user_data.get('user_id', '?')
            guest_list = current_voting['plus_one_voters'].get(user_id, [])
            
            response += f"{i}. {display_name} (ID: {user_id})\n"
            
            # Добавляем гостей этого пользователя
            for j, guest_data in enumerate(guest_list, 1):
                guest_name = guest_data.get('guest_name', 'Гость')
                response += f"   └ {guest_name} от {display_name}\n"
        response += "\n"
    
    if no_count > 0:
        response += "❌ *За 'Нет':*\n"
        for i, user_data in enumerate(current_voting['no_voters'].values(), 1):
            display_name = user_data.get('display_name', 'Unknown')
            user_id = user_data.get('user_id', '?')
            response += f"{i}. {display_name} (ID: {user_id})\n"
    
    # ДОБАВЛЯЕМ: Пользователи только с гостями (без "Да")
    users_with_only_guests = [(user_id, guest_list) for user_id, guest_list in current_voting['plus_one_voters'].items() 
                             if user_id not in current_voting['yes_voters']]
    
    if users_with_only_guests:
        response += "👥 *Только гости (без 'Да'):*\n"
        for i, (user_id, guest_list) in enumerate(users_with_only_guests, 1):
            # Получаем имя пользователя из кэша
            if user_id in current_voting['user_cache']:
                user_display_name = current_voting['user_cache'][user_id].get('display_name', f'Участник {user_id}')
            elif user_id in current_voting['no_voters']:
                user_display_name = current_voting['no_voters'][user_id].get('display_name', f'Участник {user_id}')
            else:
                user_display_name = f"Участник {user_id}"
            
            response += f"{i}. {user_display_name} (ID: {user_id})\n"
            
            # Добавляем его гостей
            for j, guest_data in enumerate(guest_list, 1):
                guest_name = guest_data.get('guest_name', 'Гость')
                response += f"   └ {guest_name} от {user_display_name}\n"
    
    if yes_count == 0 and no_count == 0 and not users_with_only_guests:
        response += "Пока никто не проголосовал"
    
    msg = bot.reply_to(message, response, parse_mode='Markdown')
    # Не удаляем список автоматически

# ====== КОМАНДА ДЛЯ ЗАКРЫТИЯ ГОЛОСОВАНИЯ ======
@bot.message_handler(commands=['close'])
def close_voting(message):
    """Закрыть голосование (убрать кнопки)"""
    handle_admin_command(message, _close_voting_impl)

def _close_voting_impl(message):
    """Реализация команды закрытия голосования"""
    try:
        if not current_voting['voting_message_id']:
            msg = bot.reply_to(message, "❌ Нет активного голосования")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return
        
        # Подсчитываем финальные результаты
        yes_count = len(current_voting['yes_voters'])
        no_count = len(current_voting['no_voters'])
        total_guests = sum(len(guests) for guests in current_voting['plus_one_voters'].values())
        total_people = yes_count + total_guests
        
        # Формируем финальный текст для сообщения с кнопками (как было раньше)
        final_text = f"🏀 *Тренировка на Тушинской сегодня*\n\n"
        final_text += f"✅ Да: {yes_count} человек\n"
        final_text += f"❌ Нет: {no_count} человек\n"
        final_text += f"👥 Всего: {yes_count + no_count}\n\n"
        final_text += "*Голосование завершено* ✅"
        
        # Убираем кнопки (пустая клавиатура)
        keyboard = types.InlineKeyboardMarkup()
        
        # Обновляем сообщение с кнопками
        bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=current_voting['voting_message_id'],
            text=final_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
        # Формируем финальный список
        all_entries = []
        
        # Те, кто голосует за "Да" (включая их гостей)
        for user_id, user_data in current_voting['yes_voters'].items():
            display_name = user_data.get('display_name', 'Unknown')
            all_entries.append(f"{display_name}")
            
            # Добавляем гостей этого пользователя
            if user_id in current_voting['plus_one_voters']:
                guest_list = current_voting['plus_one_voters'][user_id]
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_entries.append(f"{guest_name} от {display_name}")
        
        # Теперь добавляем гостей пользователей, которые не голосовали за "Да"
        for user_id, guest_list in current_voting['plus_one_voters'].items():
            # Если пользователь не в списке "Да"
            if user_id not in current_voting['yes_voters']:
                # Получаем имя пользователя из кэша
                display_name = get_user_display_name_from_cache(user_id)
                
                # Добавляем гостей этого пользователя
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_entries.append(f"{guest_name} от {display_name}")
        
        # Обновляем сообщение с результатами (делаем его неизменяемым)
        final_results_text = "🏀 *На тренировку идут:*\n\n"
        
        if all_entries:
            for i, entry in enumerate(all_entries, 1):
                final_results_text += f"{i}. {entry}\n"
            final_results_text += f"\n_Итого: {total_people} человек_"
        else:
            final_results_text += "_Никто не идет на тренировку_ 😔"
        
        bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=current_voting['results_message_id'],
            text=final_results_text,
            parse_mode='Markdown'
        )
        
        # Логируем закрытие голосования
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] 🏁 Голосование закрыто админом")
        
        # Отправляем подтверждение и удаляем через 3 секунды
        msg = bot.reply_to(message, "✅ Голосование закрыто. Кнопки убраны.")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        
    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== КОМАНДА ДЛЯ СОЗДАНИЯ УВЕДОМИТЕЛЬНОГО СООБЩЕНИЯ СЕЙЧАС ======
@bot.message_handler(commands=['notify'])
def create_notification_now(message):
    """Создать уведомительное сообщение немедленно"""
    handle_admin_command(message, _create_notification_now_impl)

def _create_notification_now_impl(message):
    """Реализация команды создания уведомительного сообщения"""
    try:
        # Создаем уведомительное сообщение без предварительного сообщения
        create_notification_message()
        
        # Отправляем подтверждение и удаляем через 3 секунды
        msg = bot.reply_to(message, "📢 Уведомительное сообщение создано!")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== КОМАНДА ДЛЯ ИЗМЕНЕНИЯ ВРЕМЕНИ УВЕДОМЛЕНИЯ ======
@bot.message_handler(commands=['set_notify_time'])
def set_notification_time(message):
    """Установить новое время для уведомительного сообщения"""
    handle_admin_command(message, _set_notification_time_impl)

def _set_notification_time_impl(message):
    """Реализация команды установки времени уведомления"""
    try:
        global NOTIFICATION_TIME
        parts = message.text.split()
        if len(parts) < 2:
            msg = bot.reply_to(message, "❌ Используйте: /set_notify_time HH:MM")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return
        
        new_time = parts[1]
        
        # Валидация времени
        datetime.strptime(new_time, "%H:%M")
        
        # Обновляем время
        NOTIFICATION_TIME = new_time
        schedule.clear('notification')  # Очищаем старое расписание
        
        # Создаем новое расписание с учетом часового пояса
        def scheduled_create_notification():
            create_notification_message()
        
        schedule.every().day.at(NOTIFICATION_TIME).do(scheduled_create_notification).tag('notification')
        
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ⏰ Время уведомления изменено на {NOTIFICATION_TIME} МСК")
        
        # Отправляем подтверждение и удаляем через 3 секунды
        msg = bot.reply_to(message, f"✅ Время уведомительного сообщения обновлено! Новое время: {NOTIFICATION_TIME} МСК")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        
    except (IndexError, ValueError):
        msg = bot.reply_to(message, "❌ Неверный формат времени. Используйте: /set_notify_time HH:MM")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== ФУНКЦИЯ ПЛАНИРОВЩИКА ======
def run_scheduler():
    """Запускает планировщик задач в отдельном потоке"""
    while True:
        schedule.run_pending()
        time.sleep(1)  # Проверяем каждую секунду для точности

# ====== КОМАНДА ДЛЯ ПОЛУЧЕНИЯ ID ГРУППЫ ======
@bot.message_handler(commands=['getid'])
def get_group_id_command(message):
    """Получить ID группы/чата по команде"""
    if message.chat.type in ['group', 'supergroup']:
        # Удаляем команду
        delete_message_safe(message.chat.id, message.message_id)
        
        # Отправляем ID и удаляем через 5 секунд
        msg = bot.reply_to(message, 
                     f"📋 ID этой группы: `{message.chat.id}`\n\n"
                     f"Скопируйте этот ID и вставьте в переменную GROUP_CHAT_ID", 
                     parse_mode='Markdown')
        time.sleep(5)
        delete_message_safe(msg.chat.id, msg.message_id)
    else:
        # Удаляем команду
        delete_message_safe(message.chat.id, message.message_id)
        
        # Отправляем сообщение об ошибке и удаляем через 3 секунды
        msg = bot.reply_to(message, "❌ Эта команда работает только в группах!")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)

# ====== КОМАНДЫ БОТА ======
@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Приветственное сообщение"""
    moscow_now = datetime.now(MOSCOW_TZ)
    welcome_text = f"""
    🤖 *Бот для голосования о тренировках*
    
    *Новая логика:*
    ✅ 'Да' - Я иду на тренировку
    ❌ 'Нет' - Я не иду на тренировку
    ➕ '+1' - Добавить гостя (можно БЕЗ выбора "Да")  <-- ИЗМЕНЕНО!
    ➖ '-1' - Убрать гостя
    
    *Команды администратора (@{ADMIN_USERNAME}):*
    /create - Создать голосование сейчас
    /notify - Создать уведомительное сообщение сейчас
    /add_yes имя [username] [гости] - Добавить пользователя в список 'Да'
    /remove имя - Удалить пользователя из списка
    /stats - Текущая статистика
    /list - Список всех голосовавших
    /close - Закрыть голосование (убрать кнопки)
    /set_time HH:MM - Установить время для автоматического голосования
    /set_notify_time HH:MM - Установить время для уведомительного сообщения
    /getid - Получить ID группы
    
    *Как работает:*
    - ✅ Да - личное участие
    - ❌ Нет - отказ
    - ➕ +1 - добавить гостя (теперь МОЖНО без выбора "Да")  <-- ИЗМЕНЕНО!
    - ➖ -1 - убрать последнего добавленного гостя
    - Гости отображаются как: "СлучайноеИмя от nickname(username)"
    
    *Случайные имена гостей:*
    {', '.join(GUEST_NAMES)}
    
    *Текущее время (Москва):* {moscow_now.strftime('%H:%M')}
    
    *Автоматически:* 
    - Бот создает голосование каждый день в {VOTING_TIME} МСК
    - Бот создает уведомительное сообщение каждый день в {NOTIFICATION_TIME} МСК
    """
    
    msg = bot.reply_to(message, welcome_text, parse_mode='Markdown')
    # Не удаляем приветственное сообщение

@bot.message_handler(commands=['create'])
def create_voting_now(message):
    """Создать голосование немедленно"""
    handle_admin_command(message, _create_voting_now_impl)

def _create_voting_now_impl(message):
    """Реализация команды создания голосования"""
    try:
        create_daily_voting()
        
        # Отправляем подтверждение и удаляем через 3 секунды
        msg = bot.reply_to(message, "✅ Голосование создано!")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

@bot.message_handler(commands=['set_time'])
def set_voting_time(message):
    """Установить новое время для голосования"""
    handle_admin_command(message, _set_voting_time_impl)

def _set_voting_time_impl(message):
    """Реализация команды установки времени голосования"""
    try:
        global VOTING_TIME
        parts = message.text.split()
        if len(parts) < 2:
            msg = bot.reply_to(message, "❌ Используйте: /set_time HH:MM")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return
        
        new_time = parts[1]
        
        # Валидация времени
        datetime.strptime(new_time, "%H:%M")
        
        # Обновляем время
        VOTING_TIME = new_time
        schedule.clear('daily_voting')  # Очищаем старое расписание
        
        # Создаем новое расписание с учетом часового пояса
        def scheduled_create_daily_voting():
            create_daily_voting()
        
        schedule.every().day.at(VOTING_TIME).do(scheduled_create_daily_voting).tag('daily_voting')
        
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ⏰ Время голосования изменено на {VOTING_TIME} МСК")
        
        # Отправляем подтверждение и удаляем через 3 секунды
        msg = bot.reply_to(message, f"✅ Время голосования обновлено! Новое время: {VOTING_TIME} МСК")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        
    except (IndexError, ValueError):
        msg = bot.reply_to(message, "❌ Неверный формат времени. Используйте: /set_time HH:MM")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== КОМАНДА ДЛЯ ОЧИСТКИ РЕЗУЛЬТАТОВ ======
@bot.message_handler(commands=['clear'])
def clear_voting(message):
    """Очистить текущие результаты"""
    handle_admin_command(message, _clear_voting_impl)

def _clear_voting_impl(message):
    """Реализация команды очистки результатов"""
    current_voting['yes_voters'] = {}
    current_voting['no_voters'] = {}
    current_voting['plus_one_voters'] = {}
    current_voting['user_cache'] = {}
    
    # Логируем очистку
    moscow_now = datetime.now(MOSCOW_TZ)
    print(f"[{moscow_now.strftime('%H:%M:%S')}] 🧹 АДМИН очистил все результаты голосования")
    
    update_voting_message()
    update_results_message()
    update_notification_message()
    
    # Отправляем подтверждение и удаляем через 3 секунды
    msg = bot.reply_to(message, "✅ Результаты голосования очищены!")
    time.sleep(3)
    delete_message_safe(msg.chat.id, msg.message_id)

# ====== ЗАПУСК БОТА ======
if __name__ == "__main__":
    print("🤖 Бот запускается...")
    
    # Устанавливаем часовой пояс для schedule
    schedule.default_timezone = MOSCOW_TZ
    
    print(f"⏰ Бот запланировал голосование на {VOTING_TIME} МСК")
    print(f"⏰ Бот запланировал уведомление на {NOTIFICATION_TIME} МСК")
    print(f"👑 Администратор: @{ADMIN_USERNAME}")
    print("")
    print("📋 КОМАНДЫ ДЛЯ АДМИНИСТРАТОРА:")
    print("  /create - Создать голосование сейчас")
    print("  /notify - Создать уведомительное сообщение сейчас")
    print("  /add_yes имя [username] [гости] - Добавить пользователя в список 'Да'")
    print("  /remove имя - Удалить пользователя из списка")
    print("  /stats - Текущая статистика")
    print("  /list - Список всех голосовавших")
    print("  /close - Закрыть голосование (убрать кнопки)")
    print("  /set_time HH:MM - Изменить время голосования")
    print("  /set_notify_time HH:MM - Изменить время уведомления")
    print("  /clear - Очистить результаты")
    print("  /getid - Получить ID группы")
    print("")
    print("🎯 КНОПКИ ДЛЯ УЧАСТНИКОВ:")
    print("  ✅ Да - Я иду на тренировку")
    print("  ❌ Нет - Я не иду на тренировку")
    print("  ➕ +1 - Добавить гостя (теперь МОЖНО без выбора 'Да')")
    print("  ➖ -1 - Убрать последнего добавленного гостя")
    print("")
    print("🎲 СЛУЧАЙНЫЕ ИМЕНА ГОСТЕЙ:")
    for i, name in enumerate(GUEST_NAMES, 1):
        print(f"  {i}. {name}")
    print("")
    print("🔑 ОСОБЕННОСТИ:")
    print("  - Команды доступны только @Ravenskort")
    print("  - Команды автоматически удаляются после выполнения")
    print("  - Ответы на команды удаляются через 3 секунды")
    print("  - +1 можно добавлять БЕЗ выбора 'Да'")
    print("  - Гости отображаются как: 'СлучайноеИмя от nickname(username)'")
    print("  - В первом сообщении отображается только 'Да', 'Нет' и 'Всего'")
    print("  - Во втором сообщении показывается список с гостями")
    print("")
    print("🔄 Сообщение с результатами обновляется после КАЖДОГО голоса!")
    print("-" * 50)

    # Автоматическая проверка при старте
    try:
        chat = bot.get_chat(GROUP_CHAT_ID)
        print(f"✅ Подключено к группе: {chat.title}")
    except:
        print("⚠️  ID группы устарел. Используйте /getid в группе для получения ID")

    # Очищаем все старые задачи
    schedule.clear()
    
    # Настраиваем ежедневное голосование (уже с правильным часовым поясом)
    schedule.every().day.at(VOTING_TIME).do(create_daily_voting).tag('daily_voting')
    print(f"📅 Голосование запланировано на {VOTING_TIME} МСК")
    
    # Настраиваем ежедневное уведомительное сообщение
    schedule.every().day.at(NOTIFICATION_TIME).do(create_notification_message).tag('notification')
    print(f"📅 Уведомление запланировано на {NOTIFICATION_TIME} МСК")
    
    # Для теста: создаем голосование сразу при запуске
    print("🔄 Создание тестового голосования сейчас...")
    create_daily_voting()
    
    # Запускаем планировщик в отдельном потоке
    scheduler_thread = Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    print("🔄 Бот запущен. Нажмите Ctrl+C для остановки.")
    print("-" * 50)
    
    # Запускаем бота
    try:
        bot.polling(none_stop=True, interval=1, timeout=30)
    except Exception as e:
        print(f"❌ Ошибка: {e}")

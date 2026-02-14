import telebot
import schedule
import time
import random
from threading import Thread
from datetime import datetime
from telebot import types
import pytz

# ====== НАСТРОЙКИ ======
TOKEN = "8568812025:AAHL-u8tquSPxlBW8ZEXz2wv4oi0z8R6r3U"
GROUP_CHAT_ID = -1002990790597

# Время публикации (24-часовой формат, указываем МСК)
VOTING_TIME = "12:00"  # ТОЛЬКО ПО СУББОТАМ
NOTIFICATION_TIME = "18:00"  # ТОЛЬКО ПО СУББОТАМ

# Устанавливаем часовой пояс (Москва)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Список случайных имен для гостей
GUEST_NAMES = [
    "Шефан Карри", "ЛеБрик", "Вестбрик", "Шакал О'Нил", 
    "Черная Мамба", "Джокер", "Грик Фрик", "Флоппер", 
    "Просто Бен Симмонс"
]

# Словарь для хранения данных о голосовании
# Теперь храним несколько голосований одновременно
active_votings = {}  # key: voting_id (timestamp), value: voting_data

# Текущее активное голосование (для обратной совместимости)
current_voting_id = None

# ====== ИНИЦИАЛИЗАЦИЯ БОТА ======
bot = telebot.TeleBot(TOKEN)

# ====== ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ ТЕКУЩЕГО ГОЛОСОВАНИЯ ======
def get_current_voting():
    """Возвращает данные текущего голосования"""
    global current_voting_id
    if current_voting_id and current_voting_id in active_votings:
        return active_votings[current_voting_id]
    return None

# ====== ФУНКЦИЯ ДЛЯ СОЗДАНИЯ НОВОГО ГОЛОСОВАНИЯ ======
def create_new_voting():
    """Создает новое голосование, сохраняя старое активным"""
    try:
        moscow_now = datetime.now(MOSCOW_TZ)
        
        # Проверяем, что сегодня суббота для автоматического создания
        if moscow_now.weekday() != 5:  # 0 - понедельник, 5 - суббота
            print(f"[{moscow_now.strftime('%H:%M:%S')}] 📅 Сегодня не суббота, голосование не создается")
            return

        # Генерируем уникальный ID для голосования
        voting_id = int(moscow_now.timestamp())
        
        # Создаем данные нового голосования
        new_voting = {
            'voting_id': voting_id,
            'voting_message_id': None,
            'results_message_id': None,
            'notification_message_id': None,
            'date': moscow_now,
            'yes_voters': {},
            'no_voters': {},
            'plus_one_voters': {},
            'user_cache': {},
        }

        # 1. СОЗДАЕМ СООБЩЕНИЕ С КНОПКАМИ
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        btn_yes = types.InlineKeyboardButton(text="✅ Да", callback_data=f"vote_yes_{voting_id}")
        btn_no = types.InlineKeyboardButton(text="❌ Нет", callback_data=f"vote_no_{voting_id}")
        btn_plus_one = types.InlineKeyboardButton(text="➕ +1", callback_data=f"plus_one_{voting_id}")
        btn_minus_one = types.InlineKeyboardButton(text="➖ -1", callback_data=f"minus_one_{voting_id}")
        
        keyboard.add(btn_yes, btn_no)
        keyboard.add(btn_plus_one, btn_minus_one)

        voting_text = f"🏀 *Тренировка на Тушинской сегодня (СУББОТА)*\n\nГолосование #{voting_id}\nВыберите вариант:"
        voting_message = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=voting_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )

        new_voting['voting_message_id'] = voting_message.message_id

        # 2. СОЗДАЕМ СООБЩЕНИЕ С РЕЗУЛЬТАТАМИ
        results_text = f"🏀 *На тренировку идут (голосование #{voting_id}):*\n\n"
        results_text += "_Пока никто не проголосовал за 'Да'_ 😔"

        results_message = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=results_text,
            parse_mode='Markdown'
        )

        new_voting['results_message_id'] = results_message.message_id

        # Сохраняем новое голосование
        active_votings[voting_id] = new_voting
        
        # Устанавливаем его как текущее
        global current_voting_id
        current_voting_id = voting_id

        print(f"[{moscow_now.strftime('%H:%M:%S')}] ✅ Создано новое голосование #{voting_id}")
        print(f"   Всего активных голосований: {len(active_votings)}")

    except Exception as e:
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ❌ Ошибка при создании голосования: {e}")

# ====== ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ ДАННЫХ ПОЛЬЗОВАТЕЛЯ ======
def get_user_display_name_from_voting(voting, user_id):
    """Получает отображаемое имя пользователя из голосования"""
    # Проверяем в кэше
    if user_id in voting['user_cache']:
        return voting['user_cache'][user_id]['display_name']
    
    # В списке "Да"
    if user_id in voting['yes_voters']:
        return voting['yes_voters'][user_id].get('display_name', f'Участник {user_id}')
    
    # В списке "Нет"
    if user_id in voting['no_voters']:
        return voting['no_voters'][user_id].get('display_name', f'Участник {user_id}')
    
    return f"Участник {user_id}"

# ====== ОБНОВЛЕНИЕ СООБЩЕНИЯ С РЕЗУЛЬТАТАМИ ======
def update_results_message(voting):
    """Обновляет сообщение с результатами для конкретного голосования"""
    if not voting['results_message_id']:
        return

    try:
        # Формируем текст сообщения
        results_text = f"🏀 *На тренировку идут (голосование #{voting['voting_id']}):*\n\n"

        # Собираем все записи
        all_entries = []

        # Добавляем тех, кто голосует за "Да"
        for user_id, user_data in voting['yes_voters'].items():
            display_name = user_data.get('display_name', f'Участник {user_id}')
            all_entries.append(f"{display_name}")

            # Добавляем гостей этого пользователя
            if user_id in voting['plus_one_voters']:
                guest_list = voting['plus_one_voters'][user_id]
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_entries.append(f"{guest_name} от {display_name}")

        # Добавляем гостей пользователей, которые не голосовали за "Да"
        for user_id, guest_list in voting['plus_one_voters'].items():
            if user_id not in voting['yes_voters']:
                display_name = get_user_display_name_from_voting(voting, user_id)
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_entries.append(f"{guest_name} от {display_name}")

        # ВСЕ ЗАПИСИ - без ограничения
        if all_entries:
            for i, entry in enumerate(all_entries, 1):
                results_text += f"{i}. {entry}\n"
            
            # Добавляем статистику
            total_yes = len(voting['yes_voters'])
            total_guests = sum(len(guests) for guests in voting['plus_one_voters'].values())
            results_text += f"\n📊 *Всего:* {total_yes + total_guests} человек ({total_yes} основных + {total_guests} гостей)"
        else:
            results_text += "_Пока никто не проголосовал за 'Да'_ 😔"

        # Обновляем сообщение
        bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=voting['results_message_id'],
            text=results_text,
            parse_mode='Markdown'
        )

        # Обновляем уведомительное сообщение, если оно есть
        if voting['notification_message_id']:
            update_notification_message(voting)

        print(f"[{datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}] 📊 Обновлены результаты голосования #{voting['voting_id']}")

    except Exception as e:
        print(f"[{datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}] ❌ Ошибка при обновлении сообщения с результатами: {e}")

# ====== ОБНОВЛЕНИЕ СООБЩЕНИЯ С КНОПКАМИ ======
def update_voting_message(voting):
    """Обновляет сообщение с кнопками для конкретного голосования"""
    if not voting['voting_message_id']:
        return

    try:
        # Подсчитываем результаты
        yes_count = len(voting['yes_voters'])
        no_count = len(voting['no_voters'])
        total_guests = sum(len(guests) for guests in voting['plus_one_voters'].values())

        # Формируем текст
        message_text = f"🏀 *Тренировка на Тушинской сегодня (СУББОТА)*\n\n"
        message_text += f"Голосование #{voting['voting_id']}\n"
        message_text += f"✅ Да: {yes_count} человек\n"
        message_text += f"❌ Нет: {no_count} человек\n"
        message_text += f"👥 Всего: {yes_count + no_count}\n\n"
        message_text += "Выберите вариант:"

        # Создаем клавиатуру
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        
        voting_id = voting['voting_id']
        btn_yes = types.InlineKeyboardButton(text="✅ Да", callback_data=f"vote_yes_{voting_id}")
        btn_no = types.InlineKeyboardButton(text="❌ Нет", callback_data=f"vote_no_{voting_id}")
        btn_plus_one = types.InlineKeyboardButton(text="➕ +1", callback_data=f"plus_one_{voting_id}")
        btn_minus_one = types.InlineKeyboardButton(text="➖ -1", callback_data=f"minus_one_{voting_id}")
        
        keyboard.add(btn_yes, btn_no)
        keyboard.add(btn_plus_one, btn_minus_one)

        # Обновляем сообщение
        bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=voting['voting_message_id'],
            text=message_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )

    except Exception as e:
        print(f"[{datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}] ❌ Ошибка при обновлении сообщения с кнопками: {e}")

# ====== ОБНОВЛЕНИЕ УВЕДОМИТЕЛЬНОГО СООБЩЕНИЯ ======
def update_notification_message(voting):
    """Обновляет уведомительное сообщение для конкретного голосования"""
    if not voting['notification_message_id']:
        return

    try:
        # Получаем список всех, кто идет
        all_going = []

        # Те, кто голосует за "Да"
        for user_id, user_data in voting['yes_voters'].items():
            display_name = user_data.get('display_name', f'Участник {user_id}')
            all_going.append(display_name)

            # Добавляем гостей
            if user_id in voting['plus_one_voters']:
                guest_list = voting['plus_one_voters'][user_id]
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_going.append(f"{guest_name} от {display_name}")

        # Гости пользователей без "Да"
        for user_id, guest_list in voting['plus_one_voters'].items():
            if user_id not in voting['yes_voters']:
                display_name = get_user_display_name_from_voting(voting, user_id)
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_going.append(f"{guest_name} от {display_name}")

        # Формируем текст
        notification_text = f"Жду на Тушинской с 19:00 (голосование #{voting['voting_id']})"

        if all_going:
            for entry in all_going:
                notification_text += f", {entry}"
        else:
            notification_text += " (пока никто)"

        # Обновляем сообщение
        bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=voting['notification_message_id'],
            text=notification_text
        )

    except Exception as e:
        print(f"[{datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}] ❌ Ошибка при обновлении уведомительного сообщения: {e}")

# ====== ФУНКЦИЯ ДЛЯ СОЗДАНИЯ УВЕДОМИТЕЛЬНОГО СООБЩЕНИЯ ======
def create_notification_message():
    """Создает уведомительное сообщение для текущего голосования"""
    voting = get_current_voting()
    if not voting:
        return
    
    moscow_now = datetime.now(MOSCOW_TZ)
    if moscow_now.weekday() != 5:
        print(f"[{moscow_now.strftime('%H:%M:%S')}] 📅 Сегодня не суббота, уведомление не отправляется")
        return
    
    try:
        # Получаем список всех, кто идет
        all_going = []

        # Те, кто голосует за "Да"
        for user_id, user_data in voting['yes_voters'].items():
            display_name = user_data.get('display_name', f'Участник {user_id}')
            all_going.append(display_name)

            # Добавляем гостей
            if user_id in voting['plus_one_voters']:
                guest_list = voting['plus_one_voters'][user_id]
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_going.append(f"{guest_name} от {display_name}")

        # Гости пользователей без "Да"
        for user_id, guest_list in voting['plus_one_voters'].items():
            if user_id not in voting['yes_voters']:
                display_name = get_user_display_name_from_voting(voting, user_id)
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_going.append(f"{guest_name} от {display_name}")

        # Формируем текст
        notification_text = f"Жду на Тушинской с 19:00 (голосование #{voting['voting_id']})"

        if all_going:
            for entry in all_going:
                notification_text += f", {entry}"
        else:
            notification_text += " (пока никто)"

        # Отправляем сообщение
        notification_message = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=notification_text
        )

        voting['notification_message_id'] = notification_message.message_id

        print(f"[{moscow_now.strftime('%H:%M:%S')}] 📢 Уведомительное сообщение создано для голосования #{voting['voting_id']}")

    except Exception as e:
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ❌ Ошибка при создании уведомительного сообщения: {e}")

# ====== ФУНКЦИЯ ДЛЯ ПЕРЕСОЗДАНИЯ ВТОРОГО СООБЩЕНИЯ ======
def recreate_results_message(voting):
    """Пересоздает второе сообщение с результатами для конкретного голосования"""
    try:
        # Удаляем старое второе сообщение, если оно есть
        if voting['results_message_id']:
            try:
                bot.delete_message(GROUP_CHAT_ID, voting['results_message_id'])
            except:
                pass

        # Формируем текст нового сообщения
        results_text = f"🏀 *На тренировку идут (голосование #{voting['voting_id']}):*\n\n"

        # Собираем все записи
        all_entries = []

        # Добавляем тех, кто голосует за "Да"
        for user_id, user_data in voting['yes_voters'].items():
            display_name = user_data.get('display_name', f'Участник {user_id}')
            all_entries.append(f"{display_name}")

            # Добавляем гостей этого пользователя
            if user_id in voting['plus_one_voters']:
                guest_list = voting['plus_one_voters'][user_id]
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_entries.append(f"{guest_name} от {display_name}")

        # Добавляем гостей пользователей, которые не голосовали за "Да"
        for user_id, guest_list in voting['plus_one_voters'].items():
            if user_id not in voting['yes_voters']:
                display_name = get_user_display_name_from_voting(voting, user_id)
                for guest_data in guest_list:
                    guest_name = guest_data.get('guest_name', 'Гость')
                    all_entries.append(f"{guest_name} от {display_name}")

        # Формируем полный список
        if all_entries:
            for i, entry in enumerate(all_entries, 1):
                results_text += f"{i}. {entry}\n"
            
            # Добавляем статистику
            total_yes = len(voting['yes_voters'])
            total_guests = sum(len(guests) for guests in voting['plus_one_voters'].values())
            results_text += f"\n📊 *Всего:* {total_yes + total_guests} человек ({total_yes} основных + {total_guests} гостей)"
        else:
            results_text += "_Пока никто не проголосовал за 'Да'_ 😔"

        # Создаем новое второе сообщение
        new_results_message = bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=results_text,
            parse_mode='Markdown'
        )

        # Сохраняем новый ID
        voting['results_message_id'] = new_results_message.message_id

        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] 📋 Второе сообщение пересоздано для голосования #{voting['voting_id']}")

    except Exception as e:
        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] ❌ Ошибка при пересоздании второго сообщения: {e}")

# ====== ОБРАБОТЧИК НАЖАТИЯ КНОПОК ======
@bot.callback_query_handler(func=lambda call: True)
def handle_button_click(call):
    """Обрабатывает нажатия на кнопки"""
    try:
        # Разбираем callback_data
        data_parts = call.data.split('_')
        
        # Определяем действие и ID голосования
        if len(data_parts) >= 3:
            action = '_'.join(data_parts[:-1])  # vote_yes, vote_no, plus_one, minus_one
            voting_id = int(data_parts[-1])
        else:
            # Старый формат без ID
            action = call.data
            voting_id = current_voting_id

        # Получаем голосование
        voting = active_votings.get(voting_id)
        if not voting:
            bot.answer_callback_query(
                callback_query_id=call.id,
                text="❌ Это голосование уже не активно!",
                show_alert=True
            )
            return

        user_id = call.from_user.id
        user = call.from_user
        display_name = get_user_display_name(user)

        # Сохраняем данные пользователя
        save_user_data_to_voting(voting, user)

        if action == "vote_yes":
            # Убираем из "Нет" если был
            was_no = user_id in voting['no_voters']
            if was_no:
                del voting['no_voters'][user_id]

            # Добавляем в "Да"
            user_data = {
                'user_id': user_id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'display_name': display_name,
                'is_bot': user.is_bot,
            }
            voting['yes_voters'][user_id] = user_data

            bot.answer_callback_query(
                callback_query_id=call.id,
                text="✅ Вы выбрали 'Да'!",
                show_alert=False
            )

        elif action == "vote_no":
            # Убираем из "Да" если был
            was_yes = user_id in voting['yes_voters']
            if was_yes:
                del voting['yes_voters'][user_id]

            # Добавляем в "Нет"
            user_data = {
                'user_id': user_id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'display_name': display_name,
                'is_bot': user.is_bot
            }
            voting['no_voters'][user_id] = user_data

            bot.answer_callback_query(
                callback_query_id=call.id,
                text="❌ Вы выбрали 'Нет'!",
                show_alert=False
            )

        elif action == "plus_one":
            # Добавляем гостя
            if user_id not in voting['plus_one_voters']:
                voting['plus_one_voters'][user_id] = []

            guest_name = random.choice(GUEST_NAMES)
            
            guest_data = {
                'guest_name': guest_name,
                'host_name': display_name,
                'host_id': user_id,
                'timestamp': datetime.now(MOSCOW_TZ)
            }
            voting['plus_one_voters'][user_id].append(guest_data)

            guest_count = len(voting['plus_one_voters'][user_id])

            bot.answer_callback_query(
                callback_query_id=call.id,
                text=f"✅ Добавлен гость: {guest_name}! Всего гостей: {guest_count}",
                show_alert=False
            )

        elif action == "minus_one":
            # Убираем гостя
            if user_id not in voting['plus_one_voters'] or not voting['plus_one_voters'][user_id]:
                bot.answer_callback_query(
                    callback_query_id=call.id,
                    text="❌ У вас нет добавленных гостей!",
                    show_alert=True
                )
                return

            guest_list = voting['plus_one_voters'][user_id]
            removed_guest = guest_list.pop()
            
            if not guest_list:
                del voting['plus_one_voters'][user_id]

            remaining_guests = len(voting['plus_one_voters'].get(user_id, []))

            bot.answer_callback_query(
                callback_query_id=call.id,
                text=f"✅ Убран гость: {removed_guest.get('guest_name', '')}",
                show_alert=False
            )

        # Обновляем сообщения
        update_voting_message(voting)
        update_results_message(voting)

    except Exception as e:
        print(f"❌ Ошибка в обработчике кнопок: {e}")
        bot.answer_callback_query(
            callback_query_id=call.id,
            text="❌ Произошла ошибка",
            show_alert=True
        )

def save_user_data_to_voting(voting, user):
    """Сохраняет данные пользователя в голосование"""
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

    voting['user_cache'][user_id] = user_data

# ====== КОМАНДА ДЛЯ ПЕРЕСОЗДАНИЯ ВТОРОГО СООБЩЕНИЯ ======
@bot.message_handler(commands=['extra_list'])
def extra_list_command(message):
    """Пересоздать второе сообщение с результатами"""
    handle_admin_command(message, _extra_list_impl)

def _extra_list_impl(message):
    """Реализация команды пересоздания второго сообщения"""
    voting = get_current_voting()
    if not voting:
        msg = bot.reply_to(message, "❌ Нет активного голосования")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        return

    recreate_results_message(voting)

    msg = bot.reply_to(message, "✅ Второе сообщение пересоздано!")
    time.sleep(3)
    delete_message_safe(msg.chat.id, msg.message_id)

# ====== КОМАНДА ДЛЯ РУЧНОГО ДОБАВЛЕНИЯ ПОЛЬЗОВАТЕЛЕЙ ======
@bot.message_handler(commands=['add_yes'])
def add_yes_manually(message):
    """Ручное добавление пользователя в список 'Да'"""
    handle_admin_command(message, _add_yes_manually_impl)

def _add_yes_manually_impl(message):
    """Реализация команды добавления пользователя"""
    voting = get_current_voting()
    if not voting:
        msg = bot.reply_to(message, "❌ Нет активного голосования")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        return

    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 2:
            msg = bot.reply_to(message, "❌ Используйте: /add_yes nickname [username] [гости]")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return

        nickname = parts[1].replace('@', '')
        username = None
        guest_count = 0

        if len(parts) > 2:
            if parts[2].isdigit():
                guest_count = int(parts[2])
            else:
                username = parts[2].replace('@', '')
                if len(parts) > 3 and parts[3].isdigit():
                    guest_count = int(parts[3])

        if username:
            display_name = f"{nickname}(@{username})"
        else:
            if any(c.isalpha() and ord(c) > 127 for c in nickname):
                display_name = nickname
            else:
                display_name = f"@{nickname}"

        fake_user_id = -len(voting['yes_voters']) - 1000

        voting['user_cache'][fake_user_id] = {
            'user_id': fake_user_id,
            'username': username,
            'first_name': nickname if username else None,
            'last_name': None,
            'display_name': display_name,
            'is_bot': False,
            'added_manually': True,
        }

        voting['yes_voters'][fake_user_id] = voting['user_cache'][fake_user_id]

        if guest_count > 0:
            if fake_user_id not in voting['plus_one_voters']:
                voting['plus_one_voters'][fake_user_id] = []

            for i in range(guest_count):
                guest_name = random.choice(GUEST_NAMES)
                voting['plus_one_voters'][fake_user_id].append({
                    'guest_name': guest_name,
                    'host_name': display_name,
                    'host_id': fake_user_id,
                    'added_manually': True
                })

        moscow_now = datetime.now(MOSCOW_TZ)
        print(f"[{moscow_now.strftime('%H:%M:%S')}] 👑 АДМИН добавил вручную: {display_name} -> 'Да' с {guest_count} гостями")

        update_voting_message(voting)
        update_results_message(voting)

        msg = bot.reply_to(message, f"✅ Пользователь '{display_name}' добавлен в список 'Да' с {guest_count} гостями")
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
    voting = get_current_voting()
    if not voting:
        msg = bot.reply_to(message, "❌ Нет активного голосования")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        return

    try:
        parts = message.text.split()
        if len(parts) < 2:
            msg = bot.reply_to(message, "❌ Используйте: /remove имя")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return

        search_term = parts[1].replace('@', '').lower()

        # Ищем в "Да"
        for user_id, user_data in list(voting['yes_voters'].items()):
            display_name = user_data.get('display_name', '').lower()
            username = user_data.get('username', '').lower() if user_data.get('username') else ''
            first_name = user_data.get('first_name', '').lower() if user_data.get('first_name') else ''

            if (search_term in display_name or search_term in username or search_term in first_name):
                del voting['yes_voters'][user_id]
                if user_id in voting['plus_one_voters']:
                    guest_count = len(voting['plus_one_voters'][user_id])
                    del voting['plus_one_voters'][user_id]
                    msg_text = f"✅ Пользователь удален из списка 'Да' (+{guest_count} гостей)"
                else:
                    msg_text = "✅ Пользователь удален из списка 'Да'"
                
                update_voting_message(voting)
                update_results_message(voting)
                
                msg = bot.reply_to(message, msg_text)
                time.sleep(3)
                delete_message_safe(msg.chat.id, msg.message_id)
                return

        # Ищем в "Нет"
        for user_id, user_data in list(voting['no_voters'].items()):
            display_name = user_data.get('display_name', '').lower()
            username = user_data.get('username', '').lower() if user_data.get('username') else ''
            first_name = user_data.get('first_name', '').lower() if user_data.get('first_name') else ''

            if (search_term in display_name or search_term in username or search_term in first_name):
                del voting['no_voters'][user_id]
                
                update_voting_message(voting)
                update_results_message(voting)
                
                msg = bot.reply_to(message, "✅ Пользователь удален из списка 'Нет'")
                time.sleep(3)
                delete_message_safe(msg.chat.id, msg.message_id)
                return

        msg = bot.reply_to(message, "❌ Пользователь не найден")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)

    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== КОМАНДА ДЛЯ ПРОСМОТРА СТАТИСТИКИ ======
@bot.message_handler(commands=['stats'])
def show_stats(message):
    """Показать текущую статистику голосования"""
    handle_admin_command(message, _show_stats_impl)

def _show_stats_impl(message):
    """Реализация команды показа статистики"""
    voting = get_current_voting()
    if not voting:
        msg = bot.reply_to(message, "❌ Нет активного голосования")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        return

    yes_count = len(voting['yes_voters'])
    no_count = len(voting['no_voters'])
    total_guests = sum(len(guests) for guests in voting['plus_one_voters'].values())
    
    users_with_only_guests = sum(1 for user_id in voting['plus_one_voters']
                                 if user_id not in voting['yes_voters'])

    stats_text = f"📊 *Статистика голосования #{voting['voting_id']}:*\n\n"
    stats_text += f"✅ Да: {yes_count} человек\n"
    stats_text += f"❌ Нет: {no_count} человек\n"
    stats_text += f"➕ Гостей: {total_guests} человек\n"
    stats_text += f"👥 Всего идут: {yes_count + total_guests} человек\n"

    if users_with_only_guests > 0:
        stats_text += f"👥 Только гости (без 'Да'): {users_with_only_guests} чел.\n"

    msg = bot.reply_to(message, stats_text, parse_mode='Markdown')

# ====== КОМАНДА ДЛЯ СПИСКА ВСЕХ ГОЛОСОВАНИЙ ======
@bot.message_handler(commands=['list_votings'])
def list_votings(message):
    """Показать список всех активных голосований"""
    handle_admin_command(message, _list_votings_impl)

def _list_votings_impl(message):
    """Реализация команды показа списка голосований"""
    if not active_votings:
        msg = bot.reply_to(message, "📋 Нет активных голосований")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        return

    text = "📋 *Активные голосования:*\n\n"
    for voting_id, voting in active_votings.items():
        yes_count = len(voting['yes_voters'])
        no_count = len(voting['no_voters'])
        guests = sum(len(g) for g in voting['plus_one_voters'].values())
        
        marker = "👉 " if voting_id == current_voting_id else ""
        text += f"{marker}#{voting_id}: {voting['date'].strftime('%d.%m %H:%M')}\n"
        text += f"   Да: {yes_count}, Нет: {no_count}, Гости: {guests}\n\n"

    msg = bot.reply_to(message, text, parse_mode='Markdown')

# ====== КОМАНДА ДЛЯ СМЕНЫ ТЕКУЩЕГО ГОЛОСОВАНИЯ ======
@bot.message_handler(commands=['switch_voting'])
def switch_voting(message):
    """Переключиться на другое голосование"""
    handle_admin_command(message, _switch_voting_impl)

def _switch_voting_impl(message):
    """Реализация команды переключения голосования"""
    global current_voting_id
    
    parts = message.text.split()
    if len(parts) < 2:
        msg = bot.reply_to(message, "❌ Используйте: /switch_voting ID_голосования")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        return

    try:
        voting_id = int(parts[1])
        if voting_id not in active_votings:
            msg = bot.reply_to(message, f"❌ Голосование #{voting_id} не найдено")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return

        current_voting_id = voting_id
        msg = bot.reply_to(message, f"✅ Текущее голосование: #{voting_id}")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)

    except ValueError:
        msg = bot.reply_to(message, "❌ Неверный формат ID")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)

# ====== КОМАНДА ДЛЯ ЗАКРЫТИЯ ГОЛОСОВАНИЯ ======
@bot.message_handler(commands=['close'])
def close_voting(message):
    """Закрыть голосование (убрать кнопки)"""
    handle_admin_command(message, _close_voting_impl)

def _close_voting_impl(message):
    """Реализация команды закрытия голосования"""
    voting = get_current_voting()
    if not voting:
        msg = bot.reply_to(message, "❌ Нет активного голосования")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        return

    try:
        if voting['voting_message_id']:
            # Убираем кнопки
            final_text = f"🏀 *Тренировка на Тушинской сегодня (СУББОТА)*\n\n"
            final_text += f"Голосование #{voting['voting_id']} завершено ✅"
            
            bot.edit_message_text(
                chat_id=GROUP_CHAT_ID,
                message_id=voting['voting_message_id'],
                text=final_text,
                parse_mode='Markdown',
                reply_markup=types.InlineKeyboardMarkup()
            )

        msg = bot.reply_to(message, f"✅ Голосование #{voting['voting_id']} закрыто")
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
    voting = get_current_voting()
    if not voting:
        msg = bot.reply_to(message, "❌ Нет активного голосования")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)
        return

    voting['yes_voters'] = {}
    voting['no_voters'] = {}
    voting['plus_one_voters'] = {}
    voting['user_cache'] = {}

    update_voting_message(voting)
    update_results_message(voting)
    if voting['notification_message_id']:
        update_notification_message(voting)

    msg = bot.reply_to(message, "✅ Результаты голосования очищены!")
    time.sleep(3)
    delete_message_safe(msg.chat.id, msg.message_id)

# ====== КОМАНДА ДЛЯ СОЗДАНИЯ ГОЛОСОВАНИЯ СЕЙЧАС ======
@bot.message_handler(commands=['create'])
def create_voting_now(message):
    """Создать голосование немедленно"""
    handle_admin_command(message, _create_voting_now_impl)

def _create_voting_now_impl(message):
    """Реализация команды создания голосования"""
    create_new_voting()
    msg = bot.reply_to(message, "✅ Новое голосование создано!")
    time.sleep(3)
    delete_message_safe(msg.chat.id, msg.message_id)

# ====== КОМАНДА ДЛЯ СОЗДАНИЯ УВЕДОМЛЕНИЯ СЕЙЧАС ======
@bot.message_handler(commands=['notify'])
def create_notification_now(message):
    """Создать уведомительное сообщение немедленно"""
    handle_admin_command(message, _create_notification_now_impl)

def _create_notification_now_impl(message):
    """Реализация команды создания уведомления"""
    create_notification_message()
    msg = bot.reply_to(message, "📢 Уведомительное сообщение создано!")
    time.sleep(3)
    delete_message_safe(msg.chat.id, msg.message_id)

# ====== КОМАНДА /START ======
@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Приветственное сообщение"""
    moscow_now = datetime.now(MOSCOW_TZ)
    welcome_text = f"""
    🤖 *Бот для голосования о тренировках*
    
    *Команды администратора:*
    /create - Создать новое голосование
    /extra_list - Пересоздать второе сообщение
    /add_yes имя [username] [гости] - Добавить в 'Да'
    /remove имя - Удалить пользователя
    /stats - Текущая статистика
    /list_votings - Список всех голосований
    /switch_voting ID - Сменить текущее голосование
    /close - Закрыть голосование
    /clear - Очистить результаты
    /notify - Создать уведомление
    /set_time HH:MM - Установить время голосования
    /set_notify_time HH:MM - Установить время уведомления
    /getid - Получить ID группы
    
    *Текущее время:* {moscow_now.strftime('%H:%M')}
    *Активных голосований:* {len(active_votings)}
    """

    msg = bot.reply_to(message, welcome_text, parse_mode='Markdown')

# ====== КОМАНДА /GETID ======
@bot.message_handler(commands=['getid'])
def get_group_id_command(message):
    """Получить ID группы"""
    if message.chat.type in ['group', 'supergroup']:
        delete_message_safe(message.chat.id, message.message_id)
        msg = bot.reply_to(message,
                           f"📋 ID этой группы: `{message.chat.id}`",
                           parse_mode='Markdown')
        time.sleep(5)
        delete_message_safe(msg.chat.id, msg.message_id)
    else:
        delete_message_safe(message.chat.id, message.message_id)
        msg = bot.reply_to(message, "❌ Эта команда работает только в группах!")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)

# ====== КОМАНДА ДЛЯ УСТАНОВКИ ВРЕМЕНИ ГОЛОСОВАНИЯ ======
@bot.message_handler(commands=['set_time'])
def set_voting_time(message):
    """Установить новое время для голосования"""
    handle_admin_command(message, _set_voting_time_impl)

def _set_voting_time_impl(message):
    """Реализация команды установки времени голосования"""
    global VOTING_TIME
    try:
        parts = message.text.split()
        if len(parts) < 2:
            msg = bot.reply_to(message, "❌ Используйте: /set_time HH:MM")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return

        new_time = parts[1]
        datetime.strptime(new_time, "%H:%M")

        VOTING_TIME = new_time
        schedule.clear('daily_voting')

        def msk_to_utc(time_msk):
            hour, minute = map(int, time_msk.split(':'))
            hour_utc = hour - 3
            if hour_utc < 0:
                hour_utc += 24
            return f"{hour_utc:02d}:{minute:02d}"

        voting_time_utc = msk_to_utc(VOTING_TIME)
        schedule.every().saturday.at(voting_time_utc).do(create_new_voting).tag('daily_voting')

        msg = bot.reply_to(message, f"✅ Время голосования: {VOTING_TIME} МСК (только суббота)")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)

    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== КОМАНДА ДЛЯ УСТАНОВКИ ВРЕМЕНИ УВЕДОМЛЕНИЯ ======
@bot.message_handler(commands=['set_notify_time'])
def set_notification_time(message):
    """Установить новое время для уведомления"""
    handle_admin_command(message, _set_notification_time_impl)

def _set_notification_time_impl(message):
    """Реализация команды установки времени уведомления"""
    global NOTIFICATION_TIME
    try:
        parts = message.text.split()
        if len(parts) < 2:
            msg = bot.reply_to(message, "❌ Используйте: /set_notify_time HH:MM")
            time.sleep(3)
            delete_message_safe(msg.chat.id, msg.message_id)
            return

        new_time = parts[1]
        datetime.strptime(new_time, "%H:%M")

        NOTIFICATION_TIME = new_time
        schedule.clear('notification')

        def msk_to_utc(time_msk):
            hour, minute = map(int, time_msk.split(':'))
            hour_utc = hour - 3
            if hour_utc < 0:
                hour_utc += 24
            return f"{hour_utc:02d}:{minute:02d}"

        notification_time_utc = msk_to_utc(NOTIFICATION_TIME)
        schedule.every().saturday.at(notification_time_utc).do(create_notification_message).tag('notification')

        msg = bot.reply_to(message, f"✅ Время уведомления: {NOTIFICATION_TIME} МСК (только суббота)")
        time.sleep(3)
        delete_message_safe(msg.chat.id, msg.message_id)

    except Exception as e:
        error_msg = bot.reply_to(message, f"❌ Ошибка: {e}")
        time.sleep(3)
        delete_message_safe(error_msg.chat.id, error_msg.message_id)

# ====== ФУНКЦИЯ ПЛАНИРОВЩИКА ======
def run_scheduler():
    """Запускает планировщик задач"""
    while True:
        schedule.run_pending()
        time.sleep(1)

# ====== ЗАПУСК БОТА ======
if __name__ == "__main__":
    print("🤖 Бот запускается...")

    def msk_to_utc(time_msk):
        hour, minute = map(int, time_msk.split(':'))
        hour_utc = hour - 3
        if hour_utc < 0:
            hour_utc += 24
        return f"{hour_utc:02d}:{minute:02d}"

    voting_time_utc = msk_to_utc(VOTING_TIME)
    notification_time_utc = msk_to_utc(NOTIFICATION_TIME)

    print(f"⏰ Голосование: {VOTING_TIME} МСК ({voting_time_utc} UTC) - ТОЛЬКО ПО СУББОТАМ")
    print(f"⏰ Уведомление: {NOTIFICATION_TIME} МСК ({notification_time_utc} UTC) - ТОЛЬКО ПО СУББОТАМ")

    # Проверка подключения к группе
    try:
        chat = bot.get_chat(GROUP_CHAT_ID)
        print(f"✅ Подключено к группе: {chat.title}")
    except:
        print("⚠️  Не удалось подключиться к группе")

    # Очищаем старые задачи
    schedule.clear()

    # Настраиваем расписание
    schedule.every().saturday.at(voting_time_utc).do(create_new_voting).tag('daily_voting')
    schedule.every().saturday.at(notification_time_utc).do(create_notification_message).tag('notification')

    print(f"📅 Голосование запланировано на субботу {voting_time_utc} UTC")
    print(f"📅 Уведомление запланировано на субботу {notification_time_utc} UTC")

    # Запускаем планировщик
    scheduler_thread = Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    print("🔄 Бот запущен. Ожидание задач...")
    print("-" * 50)

    # Запускаем бота
    try:
        bot.polling(none_stop=True, interval=1, timeout=30)
    except Exception as e:
        print(f"❌ Ошибка: {e}")

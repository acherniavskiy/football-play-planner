import logging
import random
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher.webhook import get_new_configured_app

# БЕЗОПАСНОСТЬ: Бот будет брать токен из настроек Render, а не из открытого кода
API_TOKEN = os.environ.get("8921087927:AAGpp5_adThIX9znrQul1bmM_SP6Fram8WQ")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Временное хранилище для демонстрации
events = {}

def get_event_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        InlineKeyboardButton("Я иду ✅", callback_data="going"),
        InlineKeyboardButton("Пас ❌", callback_data="skip"),
        InlineKeyboardButton("Думаю 🤔", callback_data="thinking")
    )
    keyboard.add(
        InlineKeyboardButton("+1 гость 👤", callback_data="plus_one"),
        InlineKeyboardButton("-1 гость 👤", callback_data="minus_one")
    )
    keyboard.add(InlineKeyboardButton("Поделить на команды 🔄", callback_data="split_teams"))
    keyboard.add(InlineKeyboardButton("Перемешать заново 🎲", callback_data="reshuffle_teams"))
    return keyboard

def render_event_text(title, going, skipped, thinking, guests, team1=None, team2=None):
    text = f"📅 **Мероприятие:** {title}\n\n"
    total_going = len(going) + sum(guests.values())
    text += f"🟢 **Идут / Гости ({total_going}):**\n"
    
    if going:
        for user_id, user_name in going:
            text += f"• [{user_name}](tg://user?id={user_id})\n"
    
    has_guests = False
    for host_info, count in guests.items():
        host_id, host_name = host_info
        for i in range(1, count + 1):
            text += f"• Гость {i} (от [{host_name}](tg://user?id={host_id}))\n"
            has_guests = True
            
    if not going and not has_guests:
        text += "• Пока никого...\n"
        
    text += f"\n🟡 **Думают ({len(thinking)}):**\n"
    if thinking:
        for user_id, user_name in thinking:
            text += f"• [{user_name}](tg://user?id={user_id})\n"
    else:
        text += "• Таких нет\n"
        
    text += f"\n🔴 **Не идут ({len(skipped)}):**\n"
    if skipped:
        for user_id, user_name in skipped:
            text += f"• [{user_name}](tg://user?id={user_id})\n"
    else:
        text += "• Таких нет\n"
        
    if team1 is not None and team2 is not None:
        text += "\n⚔️ **РАСПРЕДЕЛЕНИЕ НА КОМАНДЫ:**\n\n"
        text += f"🔵 **Команда 1 ({len(team1)}):**\n"
        if team1:
            for player in team1:
                text += f"• {player}\n"
        else:
            text += "• Пусто\n"
            
        text += f"\n🟡 **Команда 2 ({len(team2)}):**\n"
        if team2:
            for player in team2:
                text += f"• {player}\n"
        else:
            text += "• Пусто\n"
            
    return text

@dp.message_handler(commands=['event'])
async def create_event(message: types.Message):
    title = message.get_args().strip()
    if not title:
        await message.reply("❌ Использование: `/event Название мероприятия`", parse_mode="Markdown")
        return

    sent_msg = await message.answer(
        render_event_text(title, [], [], [], {}), 
        reply_markup=get_event_keyboard(),
        parse_mode="Markdown"
    )
    
    events[sent_msg.message_id] = {
        "title": title,
        "going": [],      
        "skipped": [],    
        "thinking": [],   
        "guests": {},      
        "team1": None,    
        "team2": None     
    }
    
    try:
        await message.delete()
    except Exception:
        pass

@dp.callback_query_handler(lambda c: c.data in ['going', 'skip', 'thinking', 'plus_one', 'minus_one', 'split_teams', 'reshuffle_teams'])
async def handle_attendance(callback_query: types.CallbackQuery):
    msg_id = callback_query.message.message_id
    if msg_id not in events:
        await callback_query.answer("Событие устарело или бот был перезагружен.", show_alert=True)
        return

    event = events[msg_id]
    user_id = callback_query.from_user.id
    user_name = callback_query.from_user.full_name
    user_info = (user_id, user_name)
    action = callback_query.data

    def remove_user_from_all(uid):
        event['going'] = [u for u in event['going'] if u[0] != uid]
        event['skipped'] = [u for u in event['skipped'] if u[0] != uid]
        event['thinking'] = [u for u in event['thinking'] if u[0] != uid]

    def get_guest_key(uid):
        for k in event['guests'].keys():
            if k[0] == uid:
                return k
        return None

    if action == 'going':
        remove_user_from_all(user_id)
        event['going'].append(user_info)
    elif action == 'skip':
        remove_user_from_all(user_id)
        event['skipped'].append(user_info)
    elif action == 'thinking':
        remove_user_from_all(user_id)
        event['thinking'].append(user_info)
    elif action == 'plus_one':
        guest_key = get_guest_key(user_id) or user_info
        event['guests'][guest_key] = event['guests'].get(guest_key, 0) + 1
    elif action == 'minus_one':
        guest_key = get_guest_key(user_id)
        if guest_key and event['guests'].get(guest_key, 0) > 0:
            event['guests'][guest_key] -= 1
            if event['guests'][guest_key] == 0:
                del event['guests'][guest_key]
        else:
            await callback_query.answer("⚠️ У вас пока нет добавленных гостей!", show_alert=True)
            return
    elif action in ['split_teams', 'reshuffle_teams']:
        all_players = []
        for _, u_name in event['going']:
            all_players.append(u_name)
        for (_, host_name), count in event['guests'].items():
            for i in range(1, count + 1):
                all_players.append(f"Гость {i} (от {host_name})")
        
        if len(all_players) < 2:
            await callback_query.answer("⚠️ Недостаточно участников для деления (минимум 2)!", show_alert=True)
            return
            
        random.shuffle(all_players)
        middle = len(all_players) // 2
        event['team1'] = all_players[:middle]
        event['team2'] = all_players[middle:]
        
        alert_text = "Команды сформированы!" if action == 'split_teams' else "Составы команд перераспределены! 🎲"
        await callback_query.answer(alert_text)

    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=msg_id,
        text=render_event_text(
            event['title'], event['going'], event['skipped'], event['thinking'],
            event['guests'], event['team1'], event['team2']
        ),
        reply_markup=get_event_keyboard(),
        parse_mode="Markdown"
    )
    
    if action not in ['split_teams', 'reshuffle_teams', 'minus_one']:
        await callback_query.answer()

# --- ПОЛНОЦЕННЫЙ БЛОК ЗАПУСКА WEBHOOK ДЛЯ RENDER.COM ---

PORT = int(os.environ.get("PORT", 3001))
WEBHOOK_HOST = os.environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_PATH = f"/webhook/{API_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Вебхук успешно установлен на URL: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.close()

if __name__ == '__main__':
    app = get_new_configured_app(dispatcher=dp, path=WEBHOOK_PATH)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host='0.0.0.0', port=PORT)

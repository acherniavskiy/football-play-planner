import logging
import random
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebhookInfo
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# БЕЗОПАСНОСТЬ: Бот берет токен из настроек Render
API_TOKEN = '8921087927:AAGpp5_adThIX9znrQul1bmM_SP6Fram8WQ'

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Временное хранилище событий
events = {}

def get_event_keyboard():
    # В aiogram 3 структура кнопок собирается через списки
    buttons = [
        [
            InlineKeyboardButton(text="Я иду ✅", callback_data="going"),
            InlineKeyboardButton(text="Пас ❌", callback_data="skip"),
            InlineKeyboardButton(text="Думаю 🤔", callback_data="thinking")
        ],
        [
            InlineKeyboardButton(text="+1 гость 👤", callback_data="plus_one"),
            InlineKeyboardButton(text="-1 гость 👤", callback_data="minus_one")
        ],
        [
            InlineKeyboardButton(text="Поделить на команды 🔄", callback_data="split_teams"),
            InlineKeyboardButton(text="Перемешать заново 🎲", callback_data="reshuffle_teams")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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

@dp.message(Command("event"))
async def create_event(message: types.Message, command: CommandObject):
    title = command.args.strip() if command.args else ""
    if not title:
        await message.reply("❌ Использование: `/event Название мероприятия`", parse_mode=ParseMode.MARKDOWN)
        return

    sent_msg = await message.answer(
        render_event_text(title, [], [], [], {}), 
        reply_markup=get_event_keyboard(),
        parse_mode=ParseMode.MARKDOWN
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

@dp.callback_query(F.data.in_(['going', 'skip', 'thinking', 'plus_one', 'minus_one', 'split_teams', 'reshuffle_teams']))
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
        parse_mode=ParseMode.MARKDOWN
    )
    
    if action not in ['split_teams', 'reshuffle_teams', 'minus_one']:
        await callback_query.answer()

# --- СОВРЕМЕННЫЙ ЗАПУСК WEBHOOK (AIOGRAM 3) ДЛЯ RENDER ---

PORT = int(os.environ.get("PORT", 3001))
WEBHOOK_HOST = os.environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_PATH = f"/webhook/{API_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

async def on_startup(bot: Bot) -> None:
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Вебхук успешно установлен на: {WEBHOOK_URL}")
    
async def handle_index(request):
    return web.Response(text="Football Bot is Alive!", content_type="text/plain")
    
def main():
    # 1. Сначала создаем приложение
    app = web.Application()
    
    # 2. СРАЗУ ЖЕ добавляем обработку главной страницы (ДЛЯ ПИНГА)
    app.router.add_get('/', handle_index)
    
    # 3. Только потом настраиваем обработчик запросов от Telegram
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    
    # 4. Регистрируем функции старта
    dp.startup.register(on_startup)
    setup_application(app, dp, bot=bot)
    
    # 5. Запускаем сервер
    web.run_app(app, host='0.0.0.0', port=PORT)


if __name__ == '__main__':
    main()

from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from database import init_db, get_db_session, User, Conversation

import os
import logging
import asyncio
import aiohttp
import json

# 1. Загрузка переменных окружения
load_dotenv(override=True)

# 2. Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 3. Инициализация БД
init_db()

# 4. Инициализация бота
bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher()

# 5. Конфигурационные константы
MAX_HISTORY = int(os.getenv("MAX_HISTORY", 10))
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "Ты полезный ассистент. Отвечай на русском языке.")

# 6. Функции для работы с БД (по пунктам):
# 6.1. Управление пользователями
async def get_or_create_user(user: types.User):
    """Создает или возвращает существующего пользователя"""
    session = get_db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
    
        if not db_user:
            db_user = User(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            session.add(db_user)
            session.commit()
            session.refresh(db_user) # Обновляем объект для получения ID
            logger.info(f"Создан новый пользователь: {user.id}")
    
        return db_user
    finally:
        session.close()

# 6.2. Сохранение и получение истории диалога
async def save_message(user_id: int, role: str, content: str):
    """Сохраняет сообщение в БД"""
    session = get_db_session()
    try:
        message = Conversation(
            user_id=user_id,
            role=role,
            content=content
        )
        session.add(message)
        session.commit()
    finally:
        session.close()

async def get_chat_history(user_id: int) -> list:
    """Возвращает историю диалога из БД"""
    session = get_db_session()
    try:
        messages = session.query(Conversation).filter_by(user_id=user_id).order_by(Conversation.timestamp.asc()).all()
    
        # Форматируем историю для API
        history = [{"role": msg.role, "content": msg.content} for msg in messages]
    
        # Ограничиваем размер истории
        if len(history) > MAX_HISTORY * 2 + 1:
            return [history[0]] + history[-(MAX_HISTORY * 2):]
        return history
    finally:
        session.close()

# 6.3. Потоковая передача ответа от DeepSeek API
async def stream_deepseek_response(user_id: int, history: list, message: types.Message):
    """Потоковая передача ответа от DeepSeek API"""
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": history,
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True
    }
    
    full_response = ""
    last_update = datetime.now()
    message_sent = False
    
    # Отправляем запрос к DeepSeek API
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status != 200:
                error = await response.text()
                logger.error(f"DeepSeek API error: {response.status} - {error}")
                await message.answer("⚠️ Ошибка API. Попробуйте позже.")
                return
            
            # Парсим ответ от DeepSeek API
            async for chunk in response.content.iter_any():
                if chunk:
                    try:
                        chunk_str = chunk.decode('utf-8')
                        if chunk_str.startswith("data: "):
                            json_str = chunk_str[6:].strip()
                            if json_str == "[DONE]":
                                break
                            
                            # Парсим JSON
                            data = json.loads(json_str)
                            
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    token = delta["content"]
                                    full_response += token
                                    
                                    # Отправляем частичные обновления каждые 0.5 сек
                                    if not message_sent:
                                        msg = await message.answer(full_response)
                                        message_sent = True
                                    elif (datetime.now() - last_update).total_seconds() > 0.5:
                                        # Обновляем существующее сообщение
                                        await bot.edit_message_text(
                                            chat_id=message.chat.id,
                                            message_id=msg.message_id,
                                            text=full_response
                                        )
                                        last_update = datetime.now()
                    except json.JSONDecodeError:
                        logger.error(f"Ошибка декодирования JSON: {json_str}")
                    except Exception as e:
                        logger.error(f"Ошибка обработки потока: {e}")
    
    # Финализируем сообщение
    if not message_sent:
        await message.answer(full_response)
    else:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg.message_id,
            text=full_response
        )
    
    # Сохраняем полный ответ в БД
    await save_message(user_id, "assistant", full_response)

# 7. Обработка telegram-команд (по пунктам):
# 7.1. Стартовая команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработка команды /start"""
    user = await get_or_create_user(message.from_user)
    welcome_text = (
        "🤖 Привет! Я бот с искусственным интеллектом на базе DeepSeek.\n"
        "Просто напиши мне сообщение, и я постараюсь помочь!\n\n"
        "ℹ️ Используйте /clear чтобы очистить историю диалога\n"
        "🔍 Используйте /history чтобы посмотреть историю"
    )
    await message.answer(welcome_text)

# 7.2. Очистка истории диалога /clear
@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    """Очистка истории диалога"""
    user = await get_or_create_user(message.from_user)
    session = get_db_session()
    try:
        session.query(Conversation).filter_by(user_id=user.id).delete()
        session.commit()
        await message.answer("🔄 История диалога очищена")
    finally:
        session.close()

# 7.3. История диалога /history
@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    """Показ последних сообщений"""
    user = await get_or_create_user(message.from_user)
    history = await get_chat_history(user.id)
    
    if not history or len(history) < 2:
        await message.answer("История диалога пуста")
        return
    
    # Форматируем последние 5 сообщений
    formatted = []
    for i, msg in enumerate(history[-10:]):
        prefix = "👤 Вы" if msg["role"] == "user" else "🤖 Бот"
        formatted.append(f"{prefix}: {msg['content']}")
    
    await message.answer(
        "📝 Последние сообщения:\n\n" + "\n\n".join(formatted[-5:])
    )

# 8. Обработка текстовых сообщений (основной функционал)
@dp.message(F.text)
async def handle_message(message: types.Message):
    """Обработка текстовых сообщений"""
    # Получение/создание пользователя
    user = await get_or_create_user(message.from_user)
    
    # Сохраняем сообщение пользователя
    await save_message(user.id, "user", message.text)
    
    # Получаем историю диалога из БД
    history = await get_chat_history(user.id)
    
    # Добавляем системный промпт, если его нет
    if not history or history[0]["role"] != "system":
        history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
        await save_message(user.id, "system", SYSTEM_PROMPT)
    
    # Отправляем запрос с потоковой передачей
    try:
        await stream_deepseek_response(user.id, history, message)
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer("🚫 Произошла ошибка при обработке запроса")

# 9. Запуск бота
if __name__ == "__main__":
    logger.info("Бот запущен")
    dp.run_polling(bot)
# DeepSeek Telegram Chat Bot

Telegram-бот для общения с LLM DeepSeek с сохранением истории диалога.

## Требования
- Python 3.11+
- Аккаунт на [DeepSeek Platform](https://platform.deepseek.com/)
- Telegram-бот (получить у [@BotFather](https://t.me/BotFather))

## Установка

1. Клонировать репозиторий:
```bash
git clone https://github.com/Diss-313/Test_bot_v1.git
cd Test_bot_v1
```

2. Установка зависимостей:
```bash
pip install -r requirements.txt
```

3. Создать файл .env и заполнить данные:
```bash
TELEGRAM_BOT_TOKEN = токен_бота
DEEPSEEK_API_KEY = api_ключ
```
# Опционально:
```bash
MODEL_NAME = deepseek-chat
SYSTEM_PROMPT = ...
MAX_HISTORY = 10
DB_NAME = my_chat.db
```
import asyncio
import json
import os
import time
import requests
from typing import Optional
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv

load_dotenv()


# ---- Настройки ----
TOKEN_TG = os.getenv("TOKEN_TG")          
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") 

bot = Bot(token=TOKEN_TG)
dp = Dispatcher()

# ---- Память и режимы ----
user_memory = {}
user_mode = {}        # {user_id: "training" | "ctf"} по умолчанию None => нейтральный ответ

# ---- Клавиатура + очистка + help ----
kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🟢 Обучение"), KeyboardButton(text="🔴 Режим CTF")],
        [KeyboardButton(text="/help"), KeyboardButton(text="🧹 Очистить память")],
    ],
    resize_keyboard=True
)

# ---- Вспомогательные функции ----
def openrouter_request(messages):
    """Синхронный POST к OpenRouter. Возвращает текст ответа или бросает Exception."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.com",
        "X-Title": "CTF Assistant"
    }
    payload = {
        "model": "openai/gpt-4o",
        "messages": messages
    }
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    j = r.json()
    try:
        return j["choices"][0]["message"]["content"].strip()
    except Exception:
        raise RuntimeError("Непредвиденный формат ответа от OpenRouter: " + str(j))

def append_history(user_id: int, role: str, content: str, limit=10):
    hist = user_memory.get(user_id, [])
    hist.append({"role": role, "content": content})
    user_memory[user_id] = hist[-limit:]

def build_system_role(mode: Optional[str]) -> str:
    if mode == "training":
        return (
            "Ты — профессиональный преподаватель по кибербезопасности и CTF. "
            "Объясняй простым понятным языком, досконально и пошагово. "
            "Показывай примеры команд, инструменты и что именно проверять в приложении/сайте. "
            "Упрощай, но не опускай важные детали. Без пафоса, только по делу. "
            "Общайся свободно как студент лет 20-ти, минимально эмодзи."
        )
    elif mode == "ctf":
        return (
            "Ты — опытный участник CTF. Ты не обучаешь — ты даёшь рабочие решения. "
            "Если задача неясна — задай 1–3 конкретных уточняющих вопроса. "
            "Пиши только практические шаги, команды, полезные payload'ы и варианты решения. "
            "Кратко и по существу, без объяснений для новичков. "
            "Общайся свободно как студент лет 20-ти, минимально эмодзи."
        )
    else:
        return (
            "Ты — эксперт по кибербезопасности и CTF. "
            "Отвечай по делу: что проверить, какие инструменты использовать и как применять уязвимость. "
            "Если нужно — показывай примеры команд. "
            "Общайся просто и по сути."
        )



@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "CTF Assistant запущен. Выбери режим работы.",
        reply_markup=kb
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "Как работать с ботом:\n"
        "🟢 Обучение — объяснения подробно и просто: что проверять, как эксплуатировать уязвимость, примеры команд.\n"
        "🔴 Режим CTF — даю сразу решение задачи (как участник), без обучения. Если нужно — задаю конкретные уточнения.\n\n"
        "Отправляй текст задания. Команда /start — запуск, кнопка 'Очистить память' — удаляет историю текущего пользователя."
    )
    await message.answer(text, reply_markup=kb)

@dp.message(lambda msg: msg.text and msg.text.lower() == "🧹 очистить память")
async def clear_memory(message: types.Message):
    user_memory.pop(message.from_user.id, None)
    await message.answer("Память очищена.", reply_markup=kb)

@dp.message(lambda msg: msg.text and msg.text == "🟢 Обучение")
async def set_training(message: types.Message):
    user_mode[message.from_user.id] = "training"
    await message.answer("Режим: ОБУЧЕНИЕ (объясняю подробно).", reply_markup=kb)

@dp.message(lambda msg: msg.text and msg.text == "🔴 Режим CTF")
async def set_ctf(message: types.Message):
    user_mode[message.from_user.id] = "ctf"
    await message.answer("Режим: CTF (даю решение, спрашиваю уточнения при необходимости).", reply_markup=kb)


@dp.message()
async def generic_handler(message: types.Message):
    uid = message.from_user.id
    mode = user_mode.get(uid)

    if not message.text or not message.text.strip():
        await message.answer("Напиши текст задания или вопрос.", reply_markup=kb)
        return

    user_input = message.text.strip()

    # Построение промпта + история
    system_role = build_system_role(mode)
    history = user_memory.get(uid, [])
    messages = [{"role": "system", "content": system_role}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})

    # Оповещение пользователя
    try:
        await message.answer("Думаю над ответом...", reply_markup=kb)
    except TelegramBadRequest:
        pass

    # Запрос к OpenRouter
    try:
        answer = openrouter_request(messages)
    except Exception as e:
        await message.answer(f"Ошибка при обращении к ИИ: {e}", reply_markup=kb)
        return

    if not answer:
        answer = "ИИ вернул пустой ответ — попробуй переформулировать вопрос."

    # Сохраняем в память
    append_history(uid, "user", user_input)
    append_history(uid, "assistant", answer)

    # Отправляем ответ, разделяя если слишком длинный
    try:
        await message.answer(answer, reply_markup=kb)
    except TelegramBadRequest:
        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000])
        else:
            await message.answer("Не удалось отправить сообщение (ошибка Telegram).")

# ---- Запуск Бота ----
async def main():
    print("Bobik запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

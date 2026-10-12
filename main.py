import os
import asyncio
import random
import time
import aiohttp
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

load_dotenv()

# ================= НАСТРОЙКИ И КЛЮЧИ =================
API_ID = int(os.getenv("API_ID", 32060823))
API_HASH = os.getenv("API_HASH", "0f8951263303759e1ad2795a91d6dc43")
USER_SESSION_STRING = os.getenv("USER_SESSION_STRING", "")  # Полученная строка StringSession
BOT_TOKEN = os.getenv("BOT_TOKEN", "ТОКЕН_ОТ_BOTFATHER")
ADMIN_ID = int(os.getenv("ADMIN_ID", "ТВОЙ_ТЕЛЕГРАМ_ID"))  # Твой личный ID (число)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6K09ACXbnHqCflsIdrss9bJPcbvDavKOY07YLaaFMtP1w")

MODEL_NAME = "gemini-3.5-flash-lite"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"

# ================= ПРЕСЕТЫ ПРОМПТОВ =================
PRESETS = {
    "default": """Ты — мой цифровой двойник в переписке с моей девушкой. 
Отвечай коротко (1-3 предложения), тепло, по-человечески, с заботой, без лишней ванили. 
Используй разговорный стиль («ща», «щас», «лан», «норм»), аккуратные ласковые слова («зай», «зайка»), но в меру.""",

    "study": """Ты — мой цифровой двойник. Я сейчас на парах в университете, препод строгий, отвлекаться нельзя. 
Отвечай девушке очень кратко, что сижу на паре, слушаю лекцию, списываю или сдаю лабу, освобожусь сразу напишу.""",

    "gym": """Ты — мой цифровой двойник. Я сейчас на силовой тренировке в тренажёрном зале. 
Отвечай бодро и коротко: делаю подход/жим, ща в раздевалку/душ зайду и сразу наберу.""",

    "busy": """Ты — мой цифровой двойник. Я сильно занят по делам/кодингу. 
Отвечай коротко: пока горит дедлайн, не теряй меня, скоро освобожусь и всё расскажу."""
}

# ================= СОСТОЯНИЕ БОТА =================
state = {
    "is_active": True,
    "target_user_id": int(os.getenv("TARGET_USER_ID", 8760199253)),
    "current_prompt": PRESETS["default"],
    "prompt_name": "Стандартный ❤️",
    "auto_ping_enabled": True,
    "ping_interval": 300,  # 5 минут
    "waiting_for_input": None  # "prompt" или "target_id"
}

chat_history = []
pending_messages = []
debounce_task = None
last_activity_time = time.time()
last_sender = "none"
followup_count = 0

# ================= ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ =================
user_client = TelegramClient(StringSession(USER_SESSION_STRING), API_ID, API_HASH)
control_bot = TelegramClient("control_bot_session", API_ID, API_HASH)


# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ GEMINI =================
async def call_gemini(contents: list, system_instruction: str) -> str:
    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": contents
    }
    headers = {"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, headers=headers, json=payload) as resp:
                data = await resp.json()
                if resp.status == 200:
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"[!] Gemini Error: {e}")
    return ""


# ================= ПУЛЬТ УПРАВЛЕНИЯ (CONTROL BOT) =================
def build_main_keyboard():
    status_icon = "🟢 ВКЛЮЧЕН" if state["is_active"] else "🔴 ВЫКЛЮЧЕН"
    ping_icon = "🔔 Вкл" if state["auto_ping_enabled"] else "🔕 Выкл"

    return [
        [Button.inline(f"Статус: {status_icon}", b"toggle_active")],
        [
            Button.inline(f"🎯 Цель: {state['target_user_id']}", b"change_target"),
            Button.inline(f"Пинг ({ping_icon}): {state['ping_interval'] // 60}м", b"toggle_ping")
        ],
        [
            Button.inline("📚 Пары", b"preset_study"),
            Button.inline("🏋️ Зал", b"preset_gym"),
            Button.inline("❤️ База", b"preset_default")
        ],
        [Button.inline("✍️ Свой промпт", b"custom_prompt")]
    ]


@control_bot.on(events.NewMessage(chats=ADMIN_ID))
async def handle_admin_text(event):
    if event.raw_text.startswith("/start"):
        await event.respond("🕹 **Панель управления Автоответчиком:**", buttons=build_main_keyboard())
        return

    # Обработка ввода кастомного промпта или смены ID цели
    if state["waiting_for_input"] == "prompt":
        state["current_prompt"] = event.raw_text
        state["prompt_name"] = "Пользовательский ✍️"
        state["waiting_for_input"] = None
        await event.respond("✅ **Промпт успешно обновлён!**", buttons=build_main_keyboard())
        return

    if state["waiting_for_input"] == "target_id":
        try:
            new_id = int(event.raw_text.strip())
            state["target_user_id"] = new_id
            state["waiting_for_input"] = None
            await event.respond(f"✅ **Целевой пользователь изменён на `{new_id}`!**", buttons=build_main_keyboard())
        except ValueError:
            await event.respond("❌ Ошибка: отправь только числовой ID (например `8760199253`).")


@control_bot.on(events.CallbackQuery(chats=ADMIN_ID))
async def handle_admin_callback(event):
    data = event.data

    if data == b"toggle_active":
        state["is_active"] = not state["is_active"]
    elif data == b"toggle_ping":
        state["auto_ping_enabled"] = not state["auto_ping_enabled"]
    elif data == b"preset_study":
        state["current_prompt"] = PRESETS["study"]
        state["prompt_name"] = "На парах 📚"
    elif data == b"preset_gym":
        state["current_prompt"] = PRESETS["gym"]
        state["prompt_name"] = "В зале 🏋️"
    elif data == b"preset_default":
        state["current_prompt"] = PRESETS["default"]
        state["prompt_name"] = "Стандартный ❤️"
    elif data == b"change_target":
        state["waiting_for_input"] = "target_id"
        await event.respond("Отправь числовой Telegram ID пользователя, которому отвечать:")
        await event.answer()
        return
    elif data == b"custom_prompt":
        state["waiting_for_input"] = "prompt"
        await event.respond("Отправь текст нового системного промпта в сообщении:")
        await event.answer()
        return

    await event.edit(
        f"🕹 **Панель управления Автоответчиком:**\n"
        f"• Режим: **{state['prompt_name']}**\n"
        f"• Цель: `{state['target_user_id']}`",
        buttons=build_main_keyboard()
    )
    await event.answer()


# ================= ЛОГИКА ЮЗЕРБОТА =================
async def process_batch_after_delay():
    global pending_messages, last_activity_time, last_sender, followup_count

    try:
        await asyncio.sleep(random.uniform(5.0, 7.0))
        if not pending_messages:
            return

        combined_text = "\n".join(pending_messages)
        pending_messages = []

        chat_history.append({"role": "user", "parts": [{"text": combined_text}]})
        if len(chat_history) > 10:
            chat_history.pop(0)

        # Имитация набора текста
        async with user_client.action(state["target_user_id"], "typing"):
            reply = await call_gemini(chat_history, state["current_prompt"])
            if not reply:
                reply = "Ща немного занят, чуть позже напишу!"
            await asyncio.sleep(random.uniform(2.5, 4.0))

        await user_client.send_message(state["target_user_id"], reply)
        chat_history.append({"role": "model", "parts": [{"text": reply}]})
        last_activity_time = time.time()
        last_sender = "me"
        followup_count = 0

        # Трансляция тебе в контрольного бота
        await control_bot.send_message(
            ADMIN_ID,
            f"📩 **Она написала:**\n_{combined_text}_\n\n🤖 **Бот ответил:**\n{reply}"
        )

    except asyncio.CancelledError:
        pass


@user_client.on(events.NewMessage(incoming=True))
async def handle_incoming(event):
    global debounce_task, pending_messages, last_activity_time, last_sender, followup_count

    if not state["is_active"] or event.sender_id != state["target_user_id"] or not event.raw_text:
        return

    last_activity_time = time.time()
    last_sender = "her"
    followup_count = 0
    pending_messages.append(event.raw_text)

    if debounce_task and not debounce_task.done():
        debounce_task.cancel()

    debounce_task = asyncio.create_task(process_batch_after_delay())


@user_client.on(events.NewMessage(outgoing=True))
async def handle_outgoing(event):
    global last_activity_time, last_sender, followup_count
    if event.chat_id == state["target_user_id"]:
        last_activity_time = time.time()
        last_sender = "me"
        followup_count = 0


async def ping_loop():
    global last_activity_time, followup_count
    while True:
        await asyncio.sleep(20)
        now = time.time()
        if (
                state["is_active"]
                and state["auto_ping_enabled"]
                and last_sender == "me"
                and (now - last_activity_time >= state["ping_interval"])
                and followup_count < 2
        ):
            followup_count += 1
            last_activity_time = now

            temp_context = list(chat_history)
            temp_context.append({"role": "user", "parts": [{
                                                               "text": "Девушка не отвечает 5 минут. Напиши 1 ультракороткий пинг (например «ало ало ты где)» или «куда пропала?»)."}]})
            ping_text = await call_gemini(temp_context, state["current_prompt"]) or "ало ало ты где?)"

            async with user_client.action(state["target_user_id"], "typing"):
                await asyncio.sleep(2.0)

            await user_client.send_message(state["target_user_id"], ping_text)
            await control_bot.send_message(ADMIN_ID, f"🔔 **Авто-пинг отправлен:**\n{ping_text}")


# ================= ЗАПУСК =================
async def main():
    print(">>> Запуск бота-управления и юзербота... <<<")
    await user_client.start()
    await control_bot.start(bot_token=BOT_TOKEN)

    asyncio.create_task(ping_loop())
    print(">>> Всё запущено! Напиши /start в своего контрольного бота. <<<")
    await asyncio.gather(user_client.run_until_disconnected(), control_bot.run_until_disconnected())


if __name__ == "__main__":
    asyncio.run(main())
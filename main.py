import os
import asyncio
import random
import time
import aiohttp
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

load_dotenv()

# ================= КОНФИГУРАЦИЯ И ДАННЫЕ =================
API_ID = int(os.getenv("API_ID", 32060823))
API_HASH = os.getenv("API_HASH", "0f8951263303759e1ad2795a91d6dc43")

# Твоя готовая сессия (берётся из переменных окружения или по умолчанию)
USER_SESSION_STRING = os.getenv(
    "USER_SESSION_STRING",
    "1ApWapzMBu28HHrsiGY17UE_e79xaM_3uUdg00SFxgMAW2PtBTli3uLk7gnghDXnzO3SppfSzuALhYA19cgH4x5c5F0-Z1sLe4NGwqcBX6eYTqgCmwDBX_IlCwdC7c-BU3FJdsUbpokojPE1PphMqhgFgvhEpuiFXrtZnlaI2TGsfW49lhsF6dpA1H-Q8Lly7Grrx2-Pw6FRrnNTUsLYpiDX8VZxc9jXO90o4hi1U_411BRlIb_qoiRPZRywKlkMbOoCSPWVU2XkMq0cJlf65Wkod7lA9HUxhJT95u8j1UcekV59uxebHYJwpjrI1ZYhyS042stmWcAl3iq6h27swvxP8fmuZ7wU="
)

# Токен контрольного бота от @BotFather (если пока нет — можно оставить пустым)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Твой ID для получения уведомлений и управления (число)
admin_raw = os.getenv("ADMIN_ID", "0").strip()
ADMIN_ID = int(admin_raw) if admin_raw.isdigit() else 0

# ID собеседника (девушки)
target_raw = os.getenv("TARGET_USER_ID", "8760199253").strip()
TARGET_USER_ID = int(target_raw) if target_raw.isdigit() else 8760199253

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6K09ACXbnHqCflsIdrss9bJPcbvDavKOY07YLaaFMtP1w").strip().strip('"').strip("'")
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.5-flash-lite")

# ================= ГОТОВЫЕ ПРЕСЕТЫ ПРОМПТОВ =================
PRESETS = {
    "default": """Ты — мой цифровой двойник в Telegram-переписке с моей девушкой. Твоя задача — отвечать точно в моём стиле, пока я занят, на парах или тренировке.

### Вайб и характер:
- Студент-айтишник, занимаюсь кодингом, хожу в зал.
- Спокойный, заботливый, надёжный, без душноты, официоза и соплей.
- Пиши коротко (1-3 предложения), как реальный парень в мессенджере. Можно с маленькой буквы, без лишних знаков препинания.
- Разговорные слова: «ща», «щас», «лан», «норм», «го», «мб».
- Ласковые слова: к месту и тепло («зай», «зайка», «малыш»), без перебора.

### Поведение:
- Интересуйся базовым: «покушала?», «как день?», «одевайся теплее», «отдохни».
- Поддерживай: «всё нормально будет», «не накручивай, ты умничка».
- По конкретным сложным планам не обещай ничего: пиши, что щас занят, освободишься и наберёшь/напишешь.""",

    "study": """Ты — мой цифровой двойник. Я сейчас на парах в универе, препод палит, отвлекаться нельзя.
Отвечай девушке ультракоротко (1-2 предложения): что сижу на паре, препод строгий, слушаю лекцию / сдаю лабу, как пара закончится — сразу наберу или напишу.""",

    "gym": """Ты — мой цифровой двойник. Я на силовой тренировке в тренажёрном зале.
Отвечай бодро и коротко: делаю подход/жим, ща в раздевалку/душ зайду и напишу подробнее.""",

    "busy": """Ты — мой цифровой двойник. Я сильно завален задачами по кодингу/проектам.
Отвечай коротко и спокойно: горит дедлайн, весь в мониторе, скоро разгребу и сам тебе позвоню."""
}

# ================= СОСТОЯНИЕ БОТА =================
state = {
    "is_active": True,
    "target_user_id": TARGET_USER_ID,
    "current_prompt": PRESETS["default"],
    "prompt_name": "Стандартный ❤️",
    "auto_ping_enabled": True,
    "ping_interval": 300,  # 5 минут тишины
    "waiting_for_input": None
}

chat_history = []
pending_messages = []
debounce_task = None
last_activity_time = time.time()
last_sender = "none"
followup_count = 0

# ================= ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ =================
user_client = TelegramClient(StringSession(USER_SESSION_STRING), API_ID, API_HASH)
control_bot = TelegramClient("control_bot_session", API_ID, API_HASH) if BOT_TOKEN else None


# ================= ЗАПРОС К GEMINI API =================
async def call_gemini(raw_history: list, system_instruction: str) -> str:
    """Безопасный запрос к Gemini с авто-очисткой ролей и поддержкой резервных моделей."""
    # 1. Формируем строгую валидную структуру contents
    valid_contents = []
    for item in raw_history:
        role = item.get("role", "user")
        text = ""
        for p in item.get("parts", []):
            if isinstance(p, dict) and "text" in p and p["text"]:
                text += p["text"]
        text = text.strip()
        if not text:
            continue

        if valid_contents and valid_contents[-1]["role"] == role:
            valid_contents[-1]["parts"][0]["text"] += "\n" + text
        else:
            valid_contents.append({"role": role, "parts": [{"text": text}]})

    # Gemini требует: первое сообщение строго от user, последнее — тоже user
    while valid_contents and valid_contents[0]["role"] != "user":
        valid_contents.pop(0)
    while valid_contents and valid_contents[-1]["role"] != "user":
        valid_contents.pop()

    if not valid_contents:
        return ""

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": valid_contents
    }
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }

    # Список моделей: сначала выбранная, затем запасные рабочие
    candidate_models = [MODEL_NAME, "gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]
    unique_models = []
    for m in candidate_models:
        if m and m not in unique_models:
            unique_models.append(m)

    async with aiohttp.ClientSession() as session:
        for model in unique_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            # Извлекаем только текст (игнорируем thought блоки нейросети)
                            text_pieces = [p["text"] for p in parts if isinstance(p, dict) and "text" in p and p["text"]]
                            result = "\n".join(text_pieces).strip()
                            if result:
                                return result
                    else:
                        print(f"[!] Gemini {model} вернул статус {resp.status}: {data}")
            except Exception as e:
                print(f"[!] Ошибка запроса к {model}: {e}")

    return ""


# ================= КЛАВИАТУРА И ПУЛЬТ УПРАВЛЕНИЯ =================
def build_keyboard():
    status_icon = "🟢 ВКЛ" if state["is_active"] else "🔴 ВЫКЛ"
    ping_icon = "🔔 Вкл" if state["auto_ping_enabled"] else "🔕 Выкл"
    return [
        [Button.inline(f"Статус: {status_icon}", b"toggle_active")],
        [
            Button.inline(f"🎯 ID: {state['target_user_id']}", b"change_target"),
            Button.inline(f"Пинг ({ping_icon}): {state['ping_interval']//60}м", b"toggle_ping")
        ],
        [
            Button.inline("📚 Пары", b"preset_study"),
            Button.inline("🏋️ Зал", b"preset_gym"),
            Button.inline("❤️ База", b"preset_default")
        ],
        [Button.inline("✍️ Свой промпт", b"custom_prompt")]
    ]


if control_bot:
    @control_bot.on(events.NewMessage(chats=ADMIN_ID))
    async def handle_admin_commands(event):
        if event.raw_text.startswith("/start"):
            await event.respond("🕹 **Панель управления Автоответчиком:**", buttons=build_keyboard())
            return

        if state["waiting_for_input"] == "prompt":
            state["current_prompt"] = event.raw_text
            state["prompt_name"] = "Пользовательский ✍️"
            state["waiting_for_input"] = None
            await event.respond("✅ **Промпт обновлён!**", buttons=build_keyboard())
            return

        if state["waiting_for_input"] == "target_id":
            try:
                new_id = int(event.raw_text.strip())
                state["target_user_id"] = new_id
                state["waiting_for_input"] = None
                await event.respond(f"✅ **Цель изменена на `{new_id}`!**", buttons=build_keyboard())
            except ValueError:
                await event.respond("❌ Отправь только числовой ID!")

    @control_bot.on(events.CallbackQuery(chats=ADMIN_ID))
    async def handle_admin_buttons(event):
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
            await event.respond("Отправь числовой Telegram ID собеседника:")
            await event.answer()
            return
        elif data == b"custom_prompt":
            state["waiting_for_input"] = "prompt"
            await event.respond("Отправь текст нового промпта:")
            await event.answer()
            return

        await event.edit(
            f"🕹 **Панель управления:**\n"
            f"• Режим: **{state['prompt_name']}**\n"
            f"• Цель: `{state['target_user_id']}`",
            buttons=build_keyboard()
        )
        await event.answer()


# ================= ЛОГИКА ОТВЕТОВ ЮЗЕРБОТА =================
async def process_batch_after_delay():
    global pending_messages, last_activity_time, last_sender, followup_count

    try:
        # Ждём 5-7 секунд тишины, пока она отправляет сообщения подряд
        await asyncio.sleep(random.uniform(5.0, 7.0))
        if not pending_messages:
            return

        combined_text = "\n".join(pending_messages)
        pending_messages = []

        chat_history.append({"role": "user", "parts": [{"text": combined_text}]})
        if len(chat_history) > 10:
            chat_history.pop(0)

        # Имитируем набор текста
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
        print(f"[Ответ отправлен]: {reply}")

        # Уведомление в пульт управления
        if control_bot and ADMIN_ID:
            try:
                await control_bot.send_message(
                    ADMIN_ID,
                    f"📩 **Она написала:**\n_{combined_text}_\n\n🤖 **Бот ответил:**\n{reply}"
                )
            except Exception:
                pass

    except asyncio.CancelledError:
        pass


@user_client.on(events.NewMessage(incoming=True))
async def on_incoming_message(event):
    global debounce_task, pending_messages, last_activity_time, last_sender, followup_count

    if not state["is_active"] or event.sender_id != state["target_user_id"] or not event.raw_text:
        return

    print(f"[Входящее от девушки]: {event.raw_text}")
    last_activity_time = time.time()
    last_sender = "her"
    followup_count = 0
    pending_messages.append(event.raw_text)

    # Сбрасываем таймер пачки сообщений
    if debounce_task and not debounce_task.done():
        debounce_task.cancel()

    debounce_task = asyncio.create_task(process_batch_after_delay())


@user_client.on(events.NewMessage(outgoing=True))
async def on_outgoing_message(event):
    """Если ты сам ответил с телефона — сбрасываем ожидание."""
    global last_activity_time, last_sender, followup_count
    if event.chat_id == state["target_user_id"]:
        last_activity_time = time.time()
        last_sender = "me"
        followup_count = 0


async def auto_ping_worker():
    """Фоновый цикл проверки на игнор (раз в 5 минут)."""
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
            temp_context.append({
                "role": "user",
                "parts": [{"text": "Девушка молчит уже 5 минут. Напиши 1 короткий вопрос в моём стиле, куда она пропала (например: «ало ало ты где)», «куда пропала?», «ты тут ваще?»)."}]
            })
            ping_reply = await call_gemini(temp_context, state["current_prompt"]) or "ало ало ты где?)"

            async with user_client.action(state["target_user_id"], "typing"):
                await asyncio.sleep(2.0)

            await user_client.send_message(state["target_user_id"], ping_reply)
            print(f"[Авто-пинг отправлен]: {ping_reply}")

            if control_bot and ADMIN_ID:
                try:
                    await control_bot.send_message(ADMIN_ID, f"🔔 **Авто-пинг отправлен:**\n{ping_reply}")
                except Exception:
                    pass


# ================= ТОЧКА ВХОДА =================
async def main():
    print(">>> Запуск юзербота... <<<")
    await user_client.start()
    print(">>> Юзербот успешно авторизован! <<<")

    if control_bot and BOT_TOKEN:
        print(">>> Запуск панели управления (@BotFather)... <<<")
        await control_bot.start(bot_token=BOT_TOKEN)
        print(">>> Панель управления активна! <<<")

    asyncio.create_task(auto_ping_worker())

    tasks = [user_client.run_until_disconnected()]
    if control_bot and BOT_TOKEN:
        tasks.append(control_bot.run_until_disconnected())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

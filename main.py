import os
import asyncio
import random
import time
import aiohttp
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import MessageNotModifiedError

load_dotenv()

# ================= КОНФИГУРАЦИЯ =================
API_ID = int(os.getenv("API_ID", 32060823))
API_HASH = os.getenv("API_HASH", "0f8951263303759e1ad2795a91d6dc43")

USER_SESSION_STRING = os.getenv(
    "USER_SESSION_STRING",
    "1ApWapzMBu28HHrsiGY17UE_e79xaM_3uUdg00SFxgMAW2PtBTli3uLk7gnghDXnzO3SppfSzuALhYA19cgH4x5c5F0-Z1sLe4NGwqcBX6eYTqgCmwDBX_IlCwdC7c-BU3FJdsUbpokojPE1PphMqhgFgvhEpuiFXrtZnlaI2TGsfW49lhsF6dpA1H-Q8Lly7Grrx2-Pw6FRrnNTUsLYpiDX8VZxc9jXO90o4hi1U_411BRlIb_qoiRPZRywKlkMbOoCSPWVU2XkMq0cJlf65Wkod7lA9HUxhJT95u8j1UcekV59uxebHYJwpjrI1ZYhyS042stmWcAl3iq6h27swvxP8fmuZ7wU="
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

admin_raw = os.getenv("ADMIN_ID", "0").strip()
ADMIN_ID = int(admin_raw) if admin_raw.isdigit() else 0

target_raw = os.getenv("TARGET_USER_ID", "8760199253").strip()
TARGET_USER_ID = int(target_raw) if target_raw.isdigit() else 8760199253

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6K09ACXbnHqCflsIdrss9bJPcbvDavKOY07YLaaFMtP1w").strip().strip('"').strip("'")
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-1.5-flash")

# Опционально: если есть прокси для обхода блокировки РФ (например: http://login:pass@ip:port)
PROXY_URL = os.getenv("PROXY_URL", "").strip() or None
BASE_API_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")

# ================= ПРЕСЕТЫ =================
PRESETS = {
    "default": """Ты — мой цифровой двойник в Telegram-переписке с моей девушкой. Твоя задача — отвечать точно в моём стиле, пока я занят, на парах или тренировке.

### Вайб и характер:
- Студент-айтишник, занимаюсь кодингом, хожу в зал.
- Спокойный, заботливый, надёжный, без душноты и официоза.
- Пиши коротко (1-3 предложения), с маленькой буквы, как реальное сообщение в телеге.
- Разговорные слова: «ща», «щас», «лан», «норм», «го», «мб».
- Ласковые слова: к месту («зай», «зайка», «малыш»), без перебора.

### Поведение:
- Забота: «покушала?», «как день?», «одевайся теплее», «отдохни».
- Поддержка: «всё нормально будет», «не накручивай, ты умничка».
- По конкретным сложным планам не обещай ничего: пиши, что щас занят, освободишься и наберёшь/напишешь.""",

    "study": """Ты — мой цифровой двойник. Я сейчас на парах в универе, препод палит.
Отвечай девушке очень кратко (1-2 предложения): что сижу на паре, препод строгий, слушаю лекцию / сдаю лабу, как пара закончится — сразу наберу.""",

    "gym": """Ты — мой цифровой двойник. Я на силовой тренировке в зале.
Отвечай бодро и коротко: делаю подход/жим, ща в раздевалку/душ зайду и напишу.""",

    "busy": """Ты — мой цифровой двойник. Я сильно завален задачами по кодингу.
Отвечай коротко: горит дедлайн, весь в мониторе, скоро разгребу и сам наберу."""
}

state = {
    "is_active": True,
    "target_user_id": TARGET_USER_ID,
    "current_prompt": PRESETS["default"],
    "prompt_name": "Стандартный ❤️",
    "auto_ping_enabled": True,
    "ping_interval": 300,
    "waiting_for_input": None
}

chat_history = []
pending_messages = []
debounce_task = None
last_activity_time = time.time()
last_sender = "none"
followup_count = 0

user_client = TelegramClient(StringSession(USER_SESSION_STRING), API_ID, API_HASH)
control_bot = TelegramClient("control_bot_session", API_ID, API_HASH) if BOT_TOKEN else None


# ================= ЗАПРОС К GEMINI =================
async def call_gemini(raw_history: list, system_instruction: str) -> tuple[str, str]:
    """Возвращает кортеж (текст_ответа, ошибка_если_есть)."""
    valid_contents = []
    for item in raw_history:
        role = item.get("role", "user")
        text = "".join(p.get("text", "") for p in item.get("parts", []) if isinstance(p, dict)).strip()
        if not text:
            continue

        if valid_contents and valid_contents[-1]["role"] == role:
            valid_contents[-1]["parts"][0]["text"] += "\n" + text
        else:
            valid_contents.append({"role": role, "parts": [{"text": text}]})

    while valid_contents and valid_contents[0]["role"] != "user":
        valid_contents.pop(0)
    while valid_contents and valid_contents[-1]["role"] != "user":
        valid_contents.pop()

    if not valid_contents:
        return "", "История диалога пуста"

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": valid_contents
    }
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }

    last_error = ""
    candidate_models = [MODEL_NAME, "gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash"]
    unique_models = list(dict.fromkeys([m for m in candidate_models if m]))

    async with aiohttp.ClientSession() as session:
        for model in unique_models:
            url = f"{BASE_API_URL}/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    proxy=PROXY_URL,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            text_pieces = [p["text"] for p in parts if isinstance(p, dict) and p.get("text")]
                            result = "\n".join(text_pieces).strip()
                            if result:
                                return result, ""
                    else:
                        error_msg = data.get("error", {}).get("message", str(data))
                        last_error = f"HTTP {resp.status} ({model}): {error_msg}"
                        print(f"[!] {last_error}")
            except Exception as e:
                last_error = f"Сетевая ошибка к {model}: {e}"
                print(f"[!] {last_error}")

    return "", last_error


# ================= ПУЛЬТ УПРАВЛЕНИЯ =================
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

        # Защита от падения MessageNotModifiedError
        try:
            await event.edit(
                f"🕹 **Панель управления:**\n"
                f"• Режим: **{state['prompt_name']}**\n"
                f"• Цель: `{state['target_user_id']}`",
                buttons=build_keyboard()
            )
        except MessageNotModifiedError:
            pass
        except Exception as e:
            print(f"[!] Edit error: {e}")

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

        async with user_client.action(state["target_user_id"], "typing"):
            reply, error = await call_gemini(chat_history, state["current_prompt"])
            if not reply:
                reply = "Ща немного занят, чуть позже напишу!"
                # Присылаем точную причину тебе в личный бот
                if control_bot and ADMIN_ID:
                    try:
                        await control_bot.send_message(
                            ADMIN_ID,
                            f"⚠️ **Ошибка вызова Gemini:**\n`{error}`"
                        )
                    except Exception:
                        pass

            await asyncio.sleep(random.uniform(2.5, 4.0))

        await user_client.send_message(state["target_user_id"], reply)
        chat_history.append({"role": "model", "parts": [{"text": reply}]})
        last_activity_time = time.time()
        last_sender = "me"
        followup_count = 0

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

    last_activity_time = time.time()
    last_sender = "her"
    followup_count = 0
    pending_messages.append(event.raw_text)

    if debounce_task and not debounce_task.done():
        debounce_task.cancel()

    debounce_task = asyncio.create_task(process_batch_after_delay())


@user_client.on(events.NewMessage(outgoing=True))
async def on_outgoing_message(event):
    global last_activity_time, last_sender, followup_count
    if event.chat_id == state["target_user_id"]:
        last_activity_time = time.time()
        last_sender = "me"
        followup_count = 0


async def auto_ping_worker():
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
                "parts": [{"text": "Девушка молчит 5 минут. Напиши 1 короткий вопрос, куда она пропала."}]
            })
            ping_reply, _ = await call_gemini(temp_context, state["current_prompt"])
            if not ping_reply:
                ping_reply = "ало ало ты где?)"

            async with user_client.action(state["target_user_id"], "typing"):
                await asyncio.sleep(2.0)

            await user_client.send_message(state["target_user_id"], ping_reply)

            if control_bot and ADMIN_ID:
                try:
                    await control_bot.send_message(ADMIN_ID, f"🔔 **Авто-пинг отправлен:**\n{ping_reply}")
                except Exception:
                    pass


# ================= ЗАПУСК =================
async def main():
    print(">>> Запуск юзербота... <<<")
    await user_client.start()
    print(">>> Юзербот активен! <<<")

    if control_bot and BOT_TOKEN:
        print(">>> Запуск панели управления... <<<")
        await control_bot.start(bot_token=BOT_TOKEN)
        print(">>> Панель управления запущена! <<<")

    asyncio.create_task(auto_ping_worker())

    tasks = [user_client.run_until_disconnected()]
    if control_bot and BOT_TOKEN:
        tasks.append(control_bot.run_until_disconnected())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

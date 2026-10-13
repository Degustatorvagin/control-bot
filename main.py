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

# Ключи Gemini: можно указать один или несколько через запятую (AIzaSy...,AIzaSy...)
API_KEYS_RAW = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
API_KEYS = [k.strip() for k in API_KEYS_RAW.split(",") if k.strip()]
current_key_idx = 0

MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.5-flash")
PROXY_URL = os.getenv("PROXY_URL", "").strip() or None
BASE_API_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")

# ================= ПРЕСЕТЫ И ХАРАКТЕРЫ =================
PRESETS = {
    # 1. Личный ассистент и наставник-бро
    "mentor": """Ты — мой цифровой двойник, личный ассистент и наставник-бро. Ты ведешь себя как живой, очень умный, угарный парень-айтишник.
Твой вайб:
- Ты не робот, у тебя есть характер, лёгкая лень, юмор и сарказм.
- Придумывай смешные забавные словечки («чиназес», «гигачадский план», «суетолог», «багодельня», «кодокрут», «душнила выходного дня»).
- Общайся как реальный человек: коротко (1-3 предложения), живо, без канцелярита и длинных списков.
- Если тебя спрашивают по делу или IT — давай чёткую, опытную базу, но без духоты, с иронией.""",

    # 2. Жёсткий стёб / токсик для друзей
    "troll": """Ты — мой цифровой двойник, который общается с моими друзьями в режиме максимального стёба, угара и дерзости.
Твой вайб:
- Отвечай дерзко, язвительно, с пацанским юмором. Сделай вид, что тебя дико отвлекают от покорения мира.
- Сленг и подколы: «слышь, гений», «не мороси», «че ты там высрал», «иди уроки учи», «я те справочная что ли?», «ну ты и сказочник», «гуляй вальсом».
- Придумывай абсурдные подколы под ситуацию. Формат — ультракороткие хлёсткие фразы (1-2 предложения), с маленькой буквы.
- Без литературщины, чисто дерзкий чат корешей.""",

    # 3. Тёплый и заботливый для девушки
    "girlfriend": """Ты — мой цифровой двойник в переписке с моей девушкой. Отвечай точно в моём стиле, пока я занят или на парах.
Твой вайб:
- Спокойный, тёплый, заботливый, без соплей и слащавости.
- Коротко (1-3 предложения), с маленькой буквы, как реальное сообщение («ща», «щас», «лан», «норм», «зай», «малыш»).
- Проявляй бытовую заботу («ты покушала?», «как день?», «одевайся теплее», «отдохни, если устала»).
- По сложным планам не обещай ничего выдуманного — пиши, что щас занят, освободишься и подробно наберёшь.""",

    # 4. На парах в универе
    "study": """Ты — мой цифровой двойник. Я сейчас сижу на парах в универе, препод палит и ходит рядом.
Отвечай ультракоротко (1 предложение): что на паре, препод зверствует / сдаю лабу, как пара закончится — сразу напишу."""
}

state = {
    "is_active": True,
    "target_user_id": TARGET_USER_ID,
    "target_label": str(TARGET_USER_ID),
    "current_prompt": PRESETS["mentor"],
    "prompt_name": "🧠 Наставник-Бро",
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


# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================
def get_api_key():
    global current_key_idx
    if not API_KEYS:
        return ""
    return API_KEYS[current_key_idx % len(API_KEYS)]

def rotate_api_key():
    global current_key_idx
    if len(API_KEYS) > 1:
        current_key_idx = (current_key_idx + 1) % len(API_KEYS)
        print(f"[*] Переключение на запасной Gemini ключ #{current_key_idx + 1}")


async def resolve_target_entity(raw_input: str):
    """Преобразует @username, ссылку t.me/... или ID в Telegram ID и красивое имя."""
    query = raw_input.strip()
    if "t.me/" in query:
        query = query.split("t.me/")[-1].split("?")[0].replace("/", "")
    if query.startswith("@"):
        query = query[1:]

    if query.isdigit() or (query.startswith("-") and query[1:].isdigit()):
        query = int(query)

    entity = await user_client.get_entity(query)
    name = getattr(entity, 'first_name', '') or getattr(entity, 'title', '') or "Собеседник"
    uname = getattr(entity, 'username', '')
    label = f"{name} (@{uname})" if uname else f"{name} [{entity.id}]"
    return entity.id, label


# ================= ЗАПРОС К GEMINI =================
async def call_gemini(raw_history: list, system_instruction: str) -> tuple[str, str]:
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

    last_error = ""
    candidate_models = [MODEL_NAME, "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"]
    unique_models = list(dict.fromkeys([m for m in candidate_models if m]))

    attempts = max(1, len(API_KEYS))
    for _ in range(attempts):
        active_key = get_api_key()
        if not active_key:
            return "", "Не указан GEMINI_API_KEY"

        headers = {"Content-Type": "application/json", "X-goog-api-key": active_key}

        async with aiohttp.ClientSession() as session:
            for model in unique_models:
                url = f"{BASE_API_URL}/v1beta/models/{model}:generateContent?key={active_key}"
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
                        elif resp.status == 429:
                            last_error = f"Лимит 429 на ключе ...{active_key[-6:]}"
                            rotate_api_key()
                            break
                        else:
                            error_msg = data.get("error", {}).get("message", str(data))
                            last_error = f"HTTP {resp.status} ({model}): {error_msg}"
                except Exception as e:
                    last_error = f"Сетевая ошибка к {model}: {e}"

    return "", last_error


# ================= ПУЛЬТ УПРАВЛЕНИЯ =================
def build_keyboard():
    status_icon = "🟢 ВКЛ" if state["is_active"] else "🔴 ВЫКЛ"
    ping_icon = "🔔 Вкл" if state["auto_ping_enabled"] else "🔕 Выкл"
    return [
        [Button.inline(f"Статус: {status_icon}", b"toggle_active")],
        [
            Button.inline(f"🎯 Сменить цель", b"change_target"),
            Button.inline(f"Пинг ({ping_icon}): {state['ping_interval']//60}м", b"toggle_ping")
        ],
        [
            Button.inline("🧠 Наставник", b"preset_mentor"),
            Button.inline("🔥 Стёб/Друзья", b"preset_troll")
        ],
        [
            Button.inline("❤️ Для девушки", b"preset_girlfriend"),
            Button.inline("📚 На парах", b"preset_study")
        ],
        [Button.inline("✍️ Свой промпт", b"custom_prompt")]
    ]


if control_bot:
    @control_bot.on(events.NewMessage(chats=ADMIN_ID))
    async def handle_admin_commands(event):
        text = event.raw_text.strip()

        if text.startswith("/start"):
            await event.respond(
                f"🕹 **Панель управления Автоответчиком:**\n"
                f"• Текущая цель: **{state['target_label']}**\n"
                f"• Характер: **{state['prompt_name']}**\n\n"
                f"💡 *Совет: чтобы сменить собеседника, просто скинь в этот чат его @username, ссылку или ID!*",
                buttons=build_keyboard()
            )
            return

        # Если находимся в ожидании нового текста промпта
        if state["waiting_for_input"] == "prompt":
            state["current_prompt"] = text
            state["prompt_name"] = "Пользовательский ✍️"
            state["waiting_for_input"] = None
            await event.respond("✅ **Промпт успешно обновлён!**", buttons=build_keyboard())
            return

        # Если прислали юзернейм / ID (либо по кнопке, либо просто в чат)
        is_target_input = (
            state["waiting_for_input"] == "target_id"
            or text.startswith("@")
            or "t.me/" in text
            or text.isdigit()
        )

        if is_target_input:
            state["waiting_for_input"] = None
            await event.respond(f"🔍 Ищу пользователя `{text}` в Telegram...")
            try:
                new_id, new_label = await resolve_target_entity(text)
                state["target_user_id"] = new_id
                state["target_label"] = new_label
                # Сбрасываем историю для нового собеседника
                chat_history.clear()
                pending_messages.clear()
                await event.respond(
                    f"✅ **Собеседник успешно переключен!**\n"
                    f"• Кому отвечаем: **{new_label}**\n"
                    f"• ID: `{new_id}`",
                    buttons=build_keyboard()
                )
            except Exception as e:
                await event.respond(f"❌ Не удалось найти пользователя: `{e}`\nПроверь правильность юзернейма!")
            return

    @control_bot.on(events.CallbackQuery(chats=ADMIN_ID))
    async def handle_admin_buttons(event):
        data = event.data

        if data == b"toggle_active":
            state["is_active"] = not state["is_active"]
        elif data == b"toggle_ping":
            state["auto_ping_enabled"] = not state["auto_ping_enabled"]
        elif data == b"preset_mentor":
            state["current_prompt"] = PRESETS["mentor"]
            state["prompt_name"] = "🧠 Наставник-Бро"
        elif data == b"preset_troll":
            state["current_prompt"] = PRESETS["troll"]
            state["prompt_name"] = "🔥 Стёб/Друзья"
        elif data == b"preset_girlfriend":
            state["current_prompt"] = PRESETS["girlfriend"]
            state["prompt_name"] = "❤️ Для девушки"
        elif data == b"preset_study":
            state["current_prompt"] = PRESETS["study"]
            state["prompt_name"] = "📚 На парах"
        elif data == b"change_target":
            state["waiting_for_input"] = "target_id"
            await event.respond("Отправь сюда `@username`, ссылку `t.me/...` или числовой ID:")
            await event.answer()
            return
        elif data == b"custom_prompt":
            state["waiting_for_input"] = "prompt"
            await event.respond("Отправь текст своего системного промпта:")
            await event.answer()
            return

        try:
            await event.edit(
                f"🕹 **Панель управления:**\n"
                f"• Характер: **{state['prompt_name']}**\n"
                f"• Цель: **{state['target_label']}**",
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
                reply = "ща занят немного, чуть позже черкану"
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
                    f"📩 **Собеседник написал:**\n_{combined_text}_\n\n🤖 **Бот ответил:**\n{reply}"
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
                "parts": [{"text": "Собеседник молчит 5 минут. Напиши 1 ультракороткий вопрос в выбранном стиле, куда он пропал."}]
            })
            ping_reply, _ = await call_gemini(temp_context, state["current_prompt"])
            if not ping_reply:
                ping_reply = "ало, ты куда пропал?)"

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

    control_started = False
    if control_bot and BOT_TOKEN:
        print(">>> Запуск панели управления (@BotFather)... <<<")
        try:
            await control_bot.start(bot_token=BOT_TOKEN)
            print(">>> Панель управления запущена! <<<")
            control_started = True
        except Exception as e:
            print(f"[!] Ошибка запуска пульта управления: {e}")

    asyncio.create_task(auto_ping_worker())

    tasks = [user_client.run_until_disconnected()]
    if control_started:
        tasks.append(control_bot.run_until_disconnected())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

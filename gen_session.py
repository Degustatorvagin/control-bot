from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = 32060823
API_HASH = "0f8951263303759e1ad2795a91d6dc43"

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\nСкопируй эту строку (USER_SESSION_STRING):\n")
    print(client.session.save())
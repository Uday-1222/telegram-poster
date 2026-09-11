import os
from telethon.sync import TelegramClient
from dotenv import load_dotenv

load_dotenv("/opt/telegram-poster/.env")

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
phone = os.getenv("PHONE")
session_name = os.getenv("SESSION_NAME", "business_session")

with TelegramClient(session_name, api_id, api_hash) as client:
    client.start(phone=phone)
    me = client.get_me()
    print("Login successful!")
    print(f"Logged in as: {me.first_name} (@{me.username})" if me.username else f"Logged in as: {me.first_name}")

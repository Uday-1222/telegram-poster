from email import message
from http import client
import signal
import os
import sys
import json
import asyncio
import random
import atexit
from datetime import datetime
from tokenize import group
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from dotenv import load_dotenv

BASE_DIR = "/opt/telegram-poster"
BATCH_DIR = os.path.join(BASE_DIR, "batches")
MESSAGE_DIR = os.path.join(BASE_DIR, "messages")
LOG_DIR = os.path.join(BASE_DIR, "logs")
ENV_FILE = os.path.join(BASE_DIR, ".env")
MESSAGE_STATE_FILE = os.path.join(MESSAGE_DIR, "current_message.txt")
LOCK_FILE = os.path.join(BASE_DIR, "send_to_groups.lock")
LOG_FILE = os.path.join(LOG_DIR, "posting.log")

os.makedirs(BATCH_DIR, exist_ok=True)
os.makedirs(MESSAGE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

load_dotenv(ENV_FILE)

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_name = os.getenv("SESSION_NAME", "business_session")

MIN_DELAY = int(os.getenv("MIN_DELAY", "45"))
MAX_DELAY = int(os.getenv("MAX_DELAY", "90"))


def get_groups_file():
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1]

    print("ERROR: groups file argument is required. Example: python send_to_groups.py /opt/telegram-poster/batches/batch_a.txt")
    sys.exit(1)


def get_batch_name(groups_file):
    return os.path.splitext(os.path.basename(groups_file))[0]


def log_status(batch_name, status, group, message, message_filename=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_text = message

    if message_filename:
        message_text = f"{message} | Message: {message_filename}"

    line = f"{timestamp} | {batch_name} | {status} | {group} | {message_text}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)


def read_lock_info():
    if not os.path.exists(LOCK_FILE):
        return None

    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            return None

        # New JSON lock format
        if content.startswith("{"):
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            return {"pid": str(data), "batch_name": "unknown", "started_at": "unknown"}

        # Old plain PID lock format
        return {
            "pid": content,
            "batch_name": "unknown",
            "started_at": "unknown"
        }

    except Exception:
        return {
            "pid": "unknown",
            "batch_name": "unknown",
            "started_at": "unknown"
        }


def is_pid_running(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False

    return True


def acquire_lock(batch_name):
    if os.path.exists(LOCK_FILE):
        lock_info = read_lock_info() or {}

        active_batch = lock_info.get("batch_name", "unknown")
        active_pid = lock_info.get("pid", "unknown")
        started_at = lock_info.get("started_at", "unknown")

        if not is_pid_running(active_pid):
            print(
                f"Stale lock detected (Batch: {active_batch}, PID: {active_pid}). Removing it..."
            )
            try:
                os.remove(LOCK_FILE)
            except FileNotFoundError:
                pass
        else:
            print(
                f"Another send_to_groups job is already running. "
                f"Active batch: {active_batch} | PID: {active_pid} | Started at: {started_at}"
            )
            sys.exit(0)

    lock_info = {
        "pid": os.getpid(),
        "batch_name": batch_name,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        json.dump(lock_info, f)

    atexit.register(release_lock)


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

def load_groups(groups_file):
    if not os.path.exists(groups_file):
        print(f"ERROR: {groups_file} not found")
        sys.exit(1)

    groups = []
    with open(groups_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            groups.append(line)

    if not groups:
        print(f"ERROR: No groups found in {groups_file}")
        sys.exit(1)

    return groups


VALID_MESSAGE_TEMPLATES = [
    "message1.txt",
    "message2.txt",
    "message3.txt",
    "message4.txt",
    "message5.txt",
    "message6.txt",
]


def get_message_templates():
    if not os.path.isdir(MESSAGE_DIR):
        os.makedirs(MESSAGE_DIR, exist_ok=True)

    message_files = []

    for filename in sorted(os.listdir(MESSAGE_DIR)):
        if filename == "current_message.txt" or filename == "message.txt":
            continue
        if filename not in VALID_MESSAGE_TEMPLATES:
            continue
        if not filename.lower().endswith(".txt"):
            continue

        full_path = os.path.join(MESSAGE_DIR, filename)
        if not os.path.isfile(full_path):
            continue

        rel_path = os.path.relpath(full_path, MESSAGE_DIR).replace(os.sep, "/")
        message_files.append((rel_path, full_path))

    return sorted(message_files, key=lambda item: item[0])


def load_message():
    message_templates = get_message_templates()

    if not message_templates:
        print(f"ERROR: No message templates found inside {MESSAGE_DIR}")
        sys.exit(1)

    usable_templates = []
    for rel_path, full_path in message_templates:
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read().strip()

            if content:
                usable_templates.append((rel_path, full_path, content))
            else:
                print(f"WARNING: Skipping empty message template: {rel_path}")
        except Exception as exc:
            print(f"WARNING: Skipping unreadable message template: {rel_path} ({exc})")

    if not usable_templates:
        print(f"ERROR: No usable message templates found inside {MESSAGE_DIR}")
        sys.exit(1)

    if not os.path.exists(MESSAGE_STATE_FILE):
        with open(MESSAGE_STATE_FILE, "w", encoding="utf-8") as f:
            f.write("0")

    try:
        with open(MESSAGE_STATE_FILE, "r", encoding="utf-8") as f:
            state_value = f.read().strip()

        current_index = int(state_value) if state_value.isdigit() else 0
    except Exception:
        print("Reset rotation state to 0")
        current_index = 0

    if current_index < 0:
        current_index = 0

    if len(usable_templates) == 1:
        selected_index = 0
        next_index = 0
    else:
        selected_index = current_index % len(usable_templates)
        next_index = (selected_index + 1) % len(usable_templates)

    rel_path, full_path, content = usable_templates[selected_index]

    try:
        with open(MESSAGE_STATE_FILE, "w", encoding="utf-8") as f:
            f.write(str(next_index))
    except Exception:
        pass

    return content, rel_path


async def main():
    groups_file = get_groups_file()
    batch_name = get_batch_name(groups_file)

    # Validate first, lock second
    groups = load_groups(groups_file)
    message, message_filename = load_message()

    acquire_lock(batch_name)

    print("Using groups file:")
    print(groups_file)
    print()
    print("Loaded groups:")
    print(len(groups))
    print()
    print("Using message:")
    print(message_filename)
    print()
    print("Delay:")
    print(f"{MIN_DELAY}-{MAX_DELAY} seconds")
    print("Starting Telegram posting job...")

    log_status(batch_name, "START", "-", f"Starting batch run with {len(groups)} groups", message_filename)

    client = None

    try:
        client = TelegramClient(
            os.path.join(BASE_DIR, session_name),
            api_id,
            api_hash
        )

        await client.start()

        me = await client.get_me()
        my_id = me.id

        for idx, group in enumerate(groups, start=1):
            try:
                print(f"[{idx}/{len(groups)}] Checking latest message in {group} ...")
                latest = await client.get_messages(group, limit=1)
                if latest:
                    last = latest[0]
                    if (
                        last.sender_id == my_id and
                        (last.message or "").strip() == message.strip()
                    ):
                        print(f"SKIPPED {group}: Previous message is still the latest.")
                        log_status(
                            batch_name,
                            "SKIPPED",
                            group,
                            "Previous message is still the latest",
                            message_filename
                        )
                        continue

                print(f"[{idx}/{len(groups)}] Sending to {group} ...")
                await client.send_message(group, message)
                print(f"SUCCESS: sent to {group}")
                log_status(batch_name, "SUCCESS", group, "Message sent", message_filename)

            except FloodWaitError as e:
                msg = f"Telegram requested wait of {e.seconds} seconds. Skipping this group for this cycle."
                print(f"SKIPPED {group}: {msg}")
                log_status(batch_name, "SKIPPED", group, msg, message_filename)
                continue

            except Exception as e:
                error_text = str(e)

                if "A wait of" in error_text and "is required before sending another message in this chat" in error_text:
                    msg = f"Telegram chat cooldown triggered: {error_text}"
                    print(f"SKIPPED {group}: {msg}")
                    log_status(batch_name, "SKIPPED", group, msg, message_filename)
                    continue

                print(f"FAILED for {group}: {e}")
                log_status(batch_name, "FAILED", group, error_text, message_filename)
                continue

            if idx < len(groups):
                delay = random.randint(MIN_DELAY, MAX_DELAY)
                print(f"Waiting {delay} seconds before next group...")
                await asyncio.sleep(delay)

    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass

    release_lock()

    log_status(batch_name, "END", "-", "Batch run finished", message_filename)
    print("Posting job finished.")


if __name__ == "__main__":
    asyncio.run(main())

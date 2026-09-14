from flask import Flask, jsonify, request
from datetime import datetime
from zoneinfo import ZoneInfo
import subprocess
import os
from dotenv import load_dotenv

BASE_DIR = "/opt/telegram-poster"
BATCH_DIR = os.path.join(BASE_DIR, "batches")
ENV_FILE = os.path.join(BASE_DIR, ".env")
SCRIPT = os.path.join(BASE_DIR, "send_to_groups.py")
PYTHON = os.path.join(BASE_DIR, "venv/bin/python")
VALID_BATCHES = {
    "batch_a",
    "batch_b",
    "batch_c",
    "batch_d",
    "batch_e",
    "batch_f",
    "batch_g",
    "batch_h",
    "batch_i",
}

load_dotenv(ENV_FILE)

API_TRIGGER_KEY = os.getenv("API_TRIGGER_KEY")

app = Flask(__name__)


INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")

def posting_allowed(current_time=None):
    current_time = current_time or datetime.now(INDIA_TIMEZONE)
    hour = current_time.hour

    # Window 1: 07:00 AM – 10:59 AM IST
    if 7 <= hour < 11:
        return True

    # Window 2: 05:00 PM – 05:59 AM IST (crosses midnight)
    if hour >= 17 or hour < 6:
        return True

    # Blocked: 06:00–06:59 AM and 11:00 AM–04:59 PM
    return False

def resolve_batch_file(batch_name):
    if not batch_name:
        return None

    batch_name = str(batch_name).strip()

    if not batch_name:
        return None

    if not batch_name.replace("_", "").replace("-", "").isalnum():
        return None

    if batch_name not in VALID_BATCHES:
        return None

    batch_file = os.path.join(BATCH_DIR, f"{batch_name}.txt")

    if not os.path.exists(batch_file):
        return None

    return batch_file


@app.route("/send-telegram", methods=["POST"])
def send_telegram():
    token = request.headers.get("X-API-KEY")

    if not API_TRIGGER_KEY:
        return jsonify({
            "status": "error",
            "message": "API_TRIGGER_KEY not set in .env"
        }), 500

    if token != API_TRIGGER_KEY:
        return jsonify({
            "status": "error",
            "message": "Unauthorized"
        }), 401

    if not posting_allowed():
        return jsonify({
            "status": "skipped",
            "message": "Posting window closed. Allowed: 07:00-10:59 IST and 17:00-05:59 IST"
        }), 200    

    data = request.get_json(silent=True) or {}
    batch_name = data.get("batch")

    if not batch_name:
        return jsonify({
            "status": "error",
            "message": "Missing required field: batch"
        }), 400

    batch_file = resolve_batch_file(batch_name)

    if not batch_file:
        return jsonify({
            "status": "error",
            "message": f"Invalid or missing batch file for batch '{batch_name}'"
        }), 400

    command = [PYTHON, SCRIPT, batch_file]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=1800
        )

        stdout_text = (result.stdout or "").strip()
        stderr_text = (result.stderr or "").strip()

        # Detect busy/lock case more reliably
        if "Another send_to_groups job is already running" in stdout_text:
            return jsonify({
                "status": "busy",
                "returncode": result.returncode,
                "batch": batch_name,
                "groups_file": batch_file,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "message": "Another batch is already running"
            }), 409

        return jsonify({
            "status": "success" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "batch": batch_name,
            "groups_file": batch_file,
            "stdout": result.stdout,
            "stderr": result.stderr
        }), 200

    except subprocess.TimeoutExpired:
        return jsonify({
            "status": "error",
            "message": "Script timed out"
        }), 500

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)

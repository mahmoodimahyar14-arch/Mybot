"""
ربات تلگرام: تبدیل پیام خام به پست حرفه‌ای برای کانال
(نسخه آماده برای هاست رایگان روی Render - اجرای ۲۴ ساعته)
--------------------------------------------------------
این نسخه توکن‌ها رو از "متغیرهای محیطی" می‌خونه (نه مستقیم داخل کد)
چون وقتی روی Render آپلود می‌کنی، امن‌تره.

پیش‌نیاز:
    pip install requests flask
"""

import os
import time
import threading
import requests
from flask import Flask

# ------------------ تنظیمات (از متغیرهای محیطی خونده می‌شه) ------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_MODEL = "gemini-3.6-flash"

PROMPT_TEMPLATE = """متن زیر یک پیام خام برای انتشار در یک کانال تلگرام است.
آن را به یک پست حرفه‌ای، خوانا و آماده انتشار تبدیل کن:

- یک عنوان کوتاه و جذاب در ابتدا (در صورت نیاز)
- پاراگراف‌بندی مرتب و خوانا
- استفاده متعادل و مناسب از ایموجی (نه زیاد، نه هیچ)
- در پایان ۲ تا ۴ هشتگ مرتبط با موضوع
- لحن حرفه‌ای اما دوستانه
- فقط خروجی نهایی را بده، بدون توضیح اضافه

متن خام:
\"\"\"
{raw_text}
\"\"\"
"""


def ask_gemini(raw_text: str) -> str:
    prompt = PROMPT_TEMPLATE.format(raw_text=raw_text)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
        "Api-Revision": "2026-05-20",
    }
    payload = {"model": GEMINI_MODEL, "input": prompt}
    try:
        resp = requests.post(GEMINI_API, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        for step in data.get("steps", []):
            if step.get("type") == "model_output":
                for block in step.get("content", []):
                    if block.get("type") == "text":
                        return block["text"].strip()
        return "⚠️ پاسخی از مدل دریافت نشد."
    except requests.exceptions.HTTPError as e:
        print(f"خطا در تماس با Gemini: {e}")
        print(f"جزئیات پاسخ سرور: {e.response.text}")
        return "⚠️ مشکلی در پردازش پیام پیش اومد. دوباره امتحان کن."
    except Exception as e:
        print(f"خطا در تماس با Gemini: {e}")
        return "⚠️ مشکلی در پردازش پیام پیش اومد. دوباره امتحان کن."


def send_message(chat_id: int, text: str):
    url = f"{TELEGRAM_API}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})


def get_updates(offset=None):
    url = f"{TELEGRAM_API}/getUpdates"
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    resp = requests.get(url, params=params, timeout=40)
    return resp.json().get("result", [])


def run_bot():
    print("ربات روشن شد و منتظر پیامه...")
    offset = None
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message or "text" not in message:
                    continue
                chat_id = message["chat"]["id"]
                raw_text = message["text"]
                final_post = ask_gemini(raw_text)
                send_message(chat_id, final_post)
        except Exception as e:
            print(f"خطای موقت: {e}")
            time.sleep(3)


# ------------------ سرور کوچک فقط برای اینکه Render بدونه برنامه زنده‌ست ------------------
app = Flask(__name__)


@app.route("/")
def home():
    return "ربات فعاله و در حال کار کردنه ✅"


if __name__ == "__main__":
    # اجرای ربات در یک ترد جدا، همزمان با سرور Flask
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

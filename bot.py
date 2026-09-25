"""
ربات تلگرام - نسخه کامل (Flask/Webhook برای PythonAnywhere)
--------------------------------------------------------------------------
قابلیت‌ها:
  - ساخت پست با ۸ سبک مختلف
  - خلاصه‌سازی متن طولانی
  - تصحیح املایی و ویرایش حرفه‌ای
  - ترجمه پست (کردی سورانی / انگلیسی)
  - تولید تصویر برای پست
  - تبدیل ویس به متن و سپس ساخت پست
  - کپشن‌نویسی از روی عکس
  - آمار ساده‌ی تعداد پست‌های ساخته‌شده در ماه (برای هر کاربر)

این فایل باید جایگزین محتوای flask_app.py توی PythonAnywhere بشه.
"""

import base64
import json
import os
import re
import time
import urllib.parse
import requests
from flask import Flask, request

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
CARD_NUMBER = os.environ.get("CARD_NUMBER", "")
CARD_HOLDER = os.environ.get("CARD_HOLDER", "")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
GEMINI_TEXT_MODEL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"
POLLINATIONS_IMAGE_API = "https://image.pollinations.ai/prompt/"

STATS_FILE = "usage_stats.json"
SUBS_FILE = "subscriptions.json"
HISTORY_FILE = "history.json"
SIGNATURES_FILE = "signatures.json"
CHANNELS_FILE = "channels.json"
BONUS_FILE = "bonus.json"
REFERRALS_FILE = "referrals.json"

FREE_MONTHLY_QUOTA = 10
HISTORY_LIMIT = 5
REFERRAL_BONUS_FOR_REFERRER = 15
REFERRAL_BONUS_FOR_NEWCOMER = 5

PLANS = {
    "starter": {"label": "🟢 پایه ۱ ماهه (۱۰۰ پست) - ۸۹,۰۰۰ تومان", "days": 30, "quota": 100, "price": 89000},
    "standard": {"label": "🔵 استاندارد ۱ ماهه (۳۰۰ پست) - ۱۴۹,۰۰۰ تومان", "days": 30, "quota": 300, "price": 149000},
    "unlimited": {"label": "🟣 نامحدود ۱ ماهه - ۲۴۹,۰۰۰ تومان", "days": 30, "quota": None, "price": 249000},
    "starter_3m": {"label": "🟢 پایه ۳ ماهه (۲۰۰ پست) - ۱۹۹,۰۰۰ تومان", "days": 90, "quota": 200, "price": 199000},
    "standard_3m": {"label": "🔵 استاندارد ۳ ماهه (۵۰۰ پست) - ۳۹۹,۰۰۰ تومان", "days": 90, "quota": 500, "price": 399000},
    "unlimited_3m": {"label": "🟣 نامحدود ۳ ماهه - ۶۴۹,۰۰۰ تومان", "days": 90, "quota": None, "price": 649000},
}

app = Flask(__name__)

# درخواست خرید در انتظار پرداخت: user_id -> plan_id (تا رسید بعدی همین کاربر رو بشناسیم)
pending_purchases = {}

# متن خام (یا متنِ تبدیل‌شده از ویس) هر کاربر رو موقتاً همینجا نگه می‌داریم
# تا وقتی که از منو انتخاب کنه می‌خواد چیکار بشه
pending_texts = {}

# آخرین پست ساخته‌شده برای هر چت، برای دکمه‌ی "ارسال به کانال"
last_generated_post = {}

# ------------------ سبک‌های مختلف پست ------------------
STYLES = {
    "news": {"label": "📰 خبری رسمی", "instruction": "لحن کاملاً خبری، رسمی و بی‌طرف. مثل یک خبرگزاری معتبر. بدون شوخی یا احساسات اضافه."},
    "funny": {"label": "😂 طنز", "instruction": "لحن طنز و شوخ‌طبعانه، با جملات بامزه و ایموجی‌های خنده‌دار، ولی بدون توهین یا بی‌احترامی."},
    "emotional": {"label": "❤️ احساسی", "instruction": "لحن گرم، احساسی و صمیمی که با قلب مخاطب صحبت می‌کند."},
    "catchy": {"label": "🔥 تیتر جذاب", "instruction": "یک تیتر بسیار جذاب و کنجکاوی‌برانگیز در ابتدا، مثل تیترهای پربازدید خبری، که مخاطب را ترغیب به خواندن ادامه کند."},
    "urgent": {"label": "🚨 هشدار/فوری", "instruction": "لحن فوری، جدی و هشداردهنده، مناسب اطلاعیه‌های اضطراری. خیلی مختصر و رک، در همان ابتدا مهم‌ترین نکته را بگو."},
    "promo": {"label": "📢 تبلیغاتی", "instruction": "لحن تبلیغاتی و متقاعدکننده، مناسب معرفی یک کسب‌وکار، محصول یا رویداد، با یک دعوت به اقدام واضح در پایان."},
    "casual": {"label": "🗣️ محاوره‌ای دوستانه", "instruction": "لحن محاوره‌ای، صمیمی و ساده، انگار داری با یک دوست حرف می‌زنی."},
    "bullet": {"label": "📋 خلاصه بولت‌وار", "instruction": "محتوا را به‌صورت چند نکته‌ی کوتاه و بولت‌وار (هرکدام یک خط) خلاصه کن."},
    "factcheck": {"label": "🔍 راستی‌آزمایی/شایعه", "instruction": "لحن تحقیقی و بی‌طرفانه‌ی راستی‌آزمایی؛ موضوع را با احتیاط و بدون قطعیت کاذب مطرح کن، شواهد له و علیه را کوتاه اشاره کن و از مخاطب بخواه تا تایید رسمی صبر کند. هرگز ادعای قطعی «واقعی» یا «فیک» بودن نکن مگر منبع مطمئنی داده شده باشد."},
    "academic": {"label": "🎓 اطلاعیه آموزشی", "instruction": "لحن رسمی و شفاف مناسب اطلاعیه‌ی دانشگاهی/آموزشی (مثل اعلام کلاس، تمرین، یا تاریخ امتحان)؛ نکات مهم (تاریخ، مهلت، مکان) را برجسته و در همان ابتدا بیاور."},
}

LANGUAGES = {
    "ku": {"label": "🟢 کردی سورانی", "name": "کردی سورانی (Kurdish Sorani)"},
    "en": {"label": "🔵 انگلیسی", "name": "English"},
}

STYLE_PROMPT = """متن زیر یک پیام خام برای انتشار در یک کانال تلگرام است.
آن را به یک پست حرفه‌ای و آماده انتشار تبدیل کن، با این ویژگی خاص:

{style_instruction}

قوانین کلی:
- کوتاه و مختصر باش، حداکثر ۴ تا ۶ خط (مخاطب کانال تلگرامی حوصله‌ی متن طولانی نداره)
- پاراگراف‌بندی مرتب و خوانا
- استفاده متعادل و مناسب از ایموجی
- در پایان ۲ تا ۴ هشتگ مرتبط با موضوع
- فقط خروجی نهایی را بده، بدون توضیح اضافه

متن خام:
\"\"\"
{raw_text}
\"\"\"
"""

SUMMARY_PROMPT = """متن زیر را خلاصه کن، طوری که فقط نکات مهم و ضروری باقی بماند
و برای انتشار سریع در یک کانال تلگرام آماده باشد (چند جمله‌ی کوتاه).
فقط خروجی نهایی را بده، بدون توضیح اضافه.

متن:
\"\"\"
{raw_text}
\"\"\"
"""

FIX_PROMPT = """متن زیر را از نظر املایی، نگارشی و دستوری اصلاح کن.
لحن، سبک و پیام اصلی متن را دقیقاً حفظ کن و چیزی از خودت اضافه نکن.
فقط متن اصلاح‌شده را برگردان، بدون هیچ توضیح اضافه.

متن:
\"\"\"
{raw_text}
\"\"\"
"""

IDEA_PROMPT = """تو دستیار محتوای یک کانال تلگرامی محلی (مثل کانال خبری/اجتماعی یک شهر) هستی.
۵ تا ایده‌ی متنوع و جذاب برای پست پیشنهاد بده که ادمین کانال بتونه امروز استفاده کنه.
ایده‌ها می‌تونن شامل این‌ها باشن: نکته‌ی کاربردی روزمره، سوال تعاملی برای مخاطبا، یادآوری یا هشدار فصلی،
معرفی یه جنبه از فرهنگ/تاریخ محلی، یا یه سوژه‌ی بحث‌برانگیز اما مناسب.
هر ایده رو در یک خط کوتاه (حداکثر ۱۵ کلمه) بنویس، شماره‌گذاری شده.
فقط لیست ایده‌ها را بده، بدون توضیح اضافه.
"""

TRANSLATE_PROMPT = """متن زیر را به {language} ترجمه کن.
لحن و پیام اصلی را حفظ کن، طوری‌که برای انتشار در کانال آماده باشد.
فقط متن ترجمه‌شده را برگردان، بدون هیچ توضیح اضافه.

متن:
\"\"\"
{raw_text}
\"\"\"
"""

IMAGE_DESCRIBE_PROMPT = """بر اساس محتوای فارسی زیر، یک توصیف تصویری دقیق، زنده و کاملاً مشخص به زبان انگلیسی بساز
که برای تولید عکس توسط هوش مصنوعی مناسب باشد.

توصیف باید شامل این جزئیات باشد:
- سوژه‌ی اصلی و عمل/حالت آن به‌طور واضح
- نوع نورپردازی (مثلاً golden hour, soft daylight, dramatic lighting)
- زاویه‌ی دوربین و نوع نما (مثلاً wide shot, close-up, aerial view)
- سبک: photorealistic, professional photography, high detail, sharp focus
- در پایان همیشه اضافه کن: "no text, no watermark, no logo"

فقط همان توصیف انگلیسی را در یک پاراگراف بده، بدون هیچ توضیح یا علامت اضافه.

Content:
\"\"\"
{raw_text}
\"\"\"
"""

PHOTO_CAPTION_PROMPT = """این عکس رو ببین و یک کپشن حرفه‌ای و جذاب برای انتشار در کانال تلگرام بنویس.

قوانین:
- ابتدا توضیح بده که در عکس چه چیزی دیده می‌شود (خیلی کوتاه، ۱ جمله)
- بعد یک کپشن جذاب و مناسب کانال تلگرام برای این عکس بنویس
- استفاده متعادل از ایموجی مناسب با محتوای عکس
- در پایان ۲ تا ۴ هشتگ مرتبط
- فقط خروجی نهایی را بده، بدون توضیح اضافه
"""

HASHTAG_PROMPT = """بر اساس متن زیر، ۵ تا ۸ هشتگ فارسی، مرتبط و پرکاربرد برای انتشار در تلگرام/اینستاگرام پیشنهاد بده.
فقط لیست هشتگ‌ها را پشت سر هم با فاصله بده، بدون هیچ توضیح اضافه.

متن:
\"\"\"
{raw_text}
\"\"\"
"""

SHORTEN_PROMPT = """متن زیر را کوتاه‌تر و خلاصه‌تر کن، اما پیام اصلی و لحن آن را دقیقاً حفظ کن.
فقط خروجی نهایی را بده، بدون توضیح اضافه.

متن:
\"\"\"
{raw_text}
\"\"\"
"""

LENGTHEN_PROMPT = """متن زیر را کمی بلندتر و کامل‌تر کن (توضیح یا جزئیات مرتبط اضافه کن)، اما از موضوع اصلی خارج نشو و لحن را حفظ کن.
فقط خروجی نهایی را بده، بدون توضیح اضافه.

متن:
\"\"\"
{raw_text}
\"\"\"
"""

MODERATE_PROMPT = """متن زیر را از نظر وجود محتوای حساس، توهین‌آمیز، نادرست، یا نامناسب برای انتشار عمومی در یک کانال بررسی کن.
اگر مشکلی نداشت، فقط دقیقاً همین را بنویس: "✅ این متن مشکلی برای انتشار نداره."
اگر نکته‌ی حساسی وجود داشت، خیلی خلاصه (حداکثر ۳ خط) بگو چه بخشی مشکل داره و چرا باید احتیاط کرد.
فقط همین ارزیابی را بده، بدون بازنویسی متن.

متن:
\"\"\"
{raw_text}
\"\"\"
"""

INSTAGRAM_PROMPT = """متن زیر را به یک کپشن حرفه‌ای مخصوص اینستاگرام تبدیل کن:
- جمله‌ی اول باید کوتاه و قلاب‌مانند (Hook) باشد تا مخاطب رو نگه داره
- چند خط توضیح با فاصله‌گذاری مناسب برای خوانایی راحت در اینستاگرام
- در پایان متن، یک دعوت به تعامل (مثلاً نظر بدید، لایک کنید، ذخیره کنید)
- در انتها ۱۰ تا ۱۵ هشتگ مرتبط (ترکیبی از پرطرفدار و اختصاصی)
فقط خروجی نهایی را بده، بدون توضیح اضافه.

متن:
\"\"\"
{raw_text}
\"\"\"
"""

POLL_PROMPT = """بر اساس متن زیر، یک سوال نظرسنجی (Poll) جذاب برای کانال تلگرام بساز، با ۲ تا ۴ گزینه‌ی کوتاه پاسخ.
خروجی را دقیقاً و فقط به‌صورت JSON با این ساختار بده، بدون هیچ متن اضافه یا ```:
{{"question": "متن سوال", "options": ["گزینه ۱", "گزینه ۲", "گزینه ۳"]}}

متن:
\"\"\"
{raw_text}
\"\"\"
"""


# ================== توابع کمکی تماس با Gemini ==================

def call_gemini_text(prompt: str) -> str:
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    last_error = None
    for attempt in range(2):
        try:
            resp = requests.post(GEMINI_TEXT_MODEL, headers=headers, json=payload, timeout=25)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            last_error = e
            print(f"تلاش {attempt + 1} ناموفق: {e}")
            if attempt < 1:
                time.sleep(1.5)
    raise last_error


def call_gemini_with_media(prompt: str, media_bytes: bytes, mime_type: str) -> str:
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    b64_data = base64.b64encode(media_bytes).decode("utf-8")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": b64_data}},
                ]
            }
        ]
    }
    last_error = None
    for attempt in range(2):
        try:
            resp = requests.post(GEMINI_TEXT_MODEL, headers=headers, json=payload, timeout=25)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            last_error = e
            print(f"تلاش {attempt + 1} ناموفق: {e}")
            if attempt < 1:
                time.sleep(1.5)
    raise last_error


def generate_image(raw_text: str) -> bytes:
    """اول یه توصیف انگلیسی دقیق از متن می‌سازه (با Gemini)، بعد عکس رو از Pollinations (کاملاً رایگان، بدون نیاز به هیچ اکانتی) می‌گیره"""
    description = call_gemini_text(IMAGE_DESCRIBE_PROMPT.format(raw_text=raw_text))
    encoded_prompt = urllib.parse.quote(description)
    url = f"{POLLINATIONS_IMAGE_API}{encoded_prompt}"
    params = {
        "width": 1024,
        "height": 1024,
        "model": "flux",
        "nologo": "true",
        "enhance": "true",
        "safe": "true",
        "negative_prompt": "blurry, low quality, distorted, deformed, watermark, text, low resolution, ugly, bad anatomy",
        "seed": -1,
    }
    last_error = None
    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, timeout=45)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            last_error = e
            print(f"تلاش ساخت تصویر {attempt + 1} ناموفق: {e}")
            if attempt < 1:
                time.sleep(1.5)
    raise last_error


def safe_gemini_call(func, *args, **kwargs):
    """در صورت خطا None برمی‌گردونه (تا قبل از کسر اعتبار کاربر چک بشه که تولید موفق بوده یا نه)"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"خطا در تماس با Gemini: {e}")
        return None


# ================== توابع تلگرام ==================

def get_telegram_file_bytes(file_id: str) -> bytes:
    resp = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id}, timeout=30)
    resp.raise_for_status()
    file_path = resp.json()["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    file_resp = requests.get(file_url, timeout=30)
    file_resp.raise_for_status()
    return file_resp.content


def send_message(chat_id: int, text: str, reply_markup=None):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return requests.post(url, json=payload)


def pin_message(chat_id: int, message_id: int):
    url = f"{TELEGRAM_API}/pinChatMessage"
    requests.post(url, json={"chat_id": chat_id, "message_id": message_id, "disable_notification": True})


def send_photo_bytes(chat_id: int, image_bytes: bytes, caption: str = ""):
    url = f"{TELEGRAM_API}/sendPhoto"
    files = {"photo": ("image.png", image_bytes, "image/png")}
    data = {"chat_id": chat_id, "caption": caption}
    requests.post(url, files=files, data=data)


def send_poll(chat_id: int, question: str, options: list):
    url = f"{TELEGRAM_API}/sendPoll"
    payload = {
        "chat_id": chat_id,
        "question": question[:300],
        "options": [opt[:100] for opt in options][:10],
        "is_anonymous": True,
    }
    requests.post(url, json=payload)


def answer_callback(callback_query_id: str, text: str = ""):
    url = f"{TELEGRAM_API}/answerCallbackQuery"
    requests.post(url, json={"callback_query_id": callback_query_id, "text": text})


# ================== منوها (دکمه‌های شیشه‌ای) ==================

def build_main_menu():
    return {
        "inline_keyboard": [
            [{"text": "📝 ساخت پست (انتخاب سبک)", "callback_data": "act:style"}],
            [
                {"text": "✂️ خلاصه‌سازی", "callback_data": "act:summary"},
                {"text": "✅ تصحیح املا", "callback_data": "act:fix"},
            ],
            [
                {"text": "🌐 ترجمه", "callback_data": "act:translate"},
                {"text": "🖼 ساخت تصویر", "callback_data": "act:image"},
            ],
            [
                {"text": "#️⃣ پیشنهاد هشتگ", "callback_data": "act:hashtags"},
                {"text": "↔️ کوتاه/بلندتر", "callback_data": "act:length"},
            ],
            [
                {"text": "📊 ساخت نظرسنجی", "callback_data": "act:poll"},
                {"text": "🛡 بررسی حساسیت", "callback_data": "act:moderate"},
            ],
            [
                {"text": "📸 کپشن اینستاگرام", "callback_data": "act:instagram"},
            ],
            [
                {"text": "🌍 همه پلتفرم‌ها (یکجا)", "callback_data": "act:allplatforms"},
            ],
        ]
    }


def build_length_menu():
    return {
        "inline_keyboard": [
            [
                {"text": "🔽 کوتاه‌تر", "callback_data": "len:short"},
                {"text": "🔼 بلندتر", "callback_data": "len:long"},
            ]
        ]
    }


def build_style_menu():
    return {
        "inline_keyboard": [
            [{"text": STYLES["news"]["label"], "callback_data": "style:news"}, {"text": STYLES["funny"]["label"], "callback_data": "style:funny"}],
            [{"text": STYLES["emotional"]["label"], "callback_data": "style:emotional"}, {"text": STYLES["catchy"]["label"], "callback_data": "style:catchy"}],
            [{"text": STYLES["urgent"]["label"], "callback_data": "style:urgent"}, {"text": STYLES["promo"]["label"], "callback_data": "style:promo"}],
            [{"text": STYLES["casual"]["label"], "callback_data": "style:casual"}, {"text": STYLES["bullet"]["label"], "callback_data": "style:bullet"}],
            [{"text": STYLES["factcheck"]["label"], "callback_data": "style:factcheck"}, {"text": STYLES["academic"]["label"], "callback_data": "style:academic"}],
        ]
    }


def build_lang_menu():
    return {
        "inline_keyboard": [
            [
                {"text": LANGUAGES["ku"]["label"], "callback_data": "lang:ku"},
                {"text": LANGUAGES["en"]["label"], "callback_data": "lang:en"},
            ]
        ]
    }


def build_plans_menu():
    buttons = [[{"text": p["label"], "callback_data": f"plan:{pid}"}] for pid, p in PLANS.items()]
    return {"inline_keyboard": buttons}


# ================== آمار استفاده ماهانه ==================

def _load_stats() -> dict:
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_stats(stats: dict):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)


def _current_month() -> str:
    return time.strftime("%Y-%m")


def increment_usage(user_id: int):
    stats = _load_stats()
    key = str(user_id)
    month = _current_month()
    entry = stats.get(key)
    if not entry or entry.get("month") != month:
        entry = {"month": month, "count": 0}
    entry["count"] += 1
    stats[key] = entry
    _save_stats(stats)


def get_usage(user_id: int) -> int:
    stats = _load_stats()
    entry = stats.get(str(user_id))
    if not entry or entry.get("month") != _current_month():
        return 0
    return entry.get("count", 0)


# ================== اشتراک‌ها ==================

def _load_subs() -> dict:
    if not os.path.exists(SUBS_FILE):
        return {}
    try:
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_subs(subs: dict):
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False)


def get_subscription(user_id: int):
    subs = _load_subs()
    entry = subs.get(str(user_id))
    if not entry:
        return None
    if entry.get("expires", "") < time.strftime("%Y-%m-%d"):
        return None
    return entry


def activate_subscription(user_id: int, plan_id: str):
    plan = PLANS[plan_id]
    expires = time.strftime("%Y-%m-%d", time.localtime(time.time() + plan["days"] * 86400))
    subs = _load_subs()
    subs[str(user_id)] = {"plan": plan_id, "expires": expires, "quota_left": plan["quota"]}
    _save_subs(subs)
    return expires


def consume_credit(user_id: int):
    """قبل از هر عملیات تولید محتوا صدا زده می‌شه.
    برمی‌گردونه: (مجاز است یا نه, پیام خطا در صورت رد شدن, پیام اطلاع‌رسانی اعتبار)"""
    if user_id == ADMIN_ID:
        return True, None, None

    used_free = get_usage(user_id)
    if used_free < FREE_MONTHLY_QUOTA:
        increment_usage(user_id)
        remaining = FREE_MONTHLY_QUOTA - (used_free + 1)
        if remaining > 0:
            info = f"📌 {remaining} از {FREE_MONTHLY_QUOTA} پست رایگان این ماهت باقی مونده."
        else:
            info = "📌 این آخرین پست رایگانت بود این ماه. برای ادامه /buy رو بزن."
        return True, None, info

    bonus = get_bonus(user_id)
    if bonus > 0:
        use_bonus(user_id)
        return True, None, f"🎁 از اعتبار هدیه‌ات استفاده شد ({bonus - 1} مورد باقی مونده)."

    sub = get_subscription(user_id)
    if sub:
        if sub["quota_left"] is None:
            return True, None, None
        if sub["quota_left"] > 0:
            subs = _load_subs()
            subs[str(user_id)]["quota_left"] -= 1
            _save_subs(subs)
            return True, None, f"📌 {sub['quota_left'] - 1} پست از اشتراکت باقی مونده."
        return False, "⚠️ سهمیه‌ی اشتراکت تموم شده. برای شارژ دوباره /buy رو بزن.", None

    return False, "⚠️ سهمیه‌ی رایگان این ماهت (۱۰ پست) تموم شده.\nبرای ادامه، یکی از پلن‌ها رو بخر: /buy", None


# ================== تاریخچه‌ی پست‌ها ==================

def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def add_history(user_id: int, text: str):
    history = _load_json(HISTORY_FILE)
    key = str(user_id)
    entries = history.get(key, [])
    entries.insert(0, text)
    history[key] = entries[:HISTORY_LIMIT]
    _save_json(HISTORY_FILE, history)


def get_history(user_id: int) -> list:
    history = _load_json(HISTORY_FILE)
    return history.get(str(user_id), [])


# ================== امضای کانال ==================

def get_signature(user_id: int):
    sigs = _load_json(SIGNATURES_FILE)
    return sigs.get(str(user_id))


def set_signature(user_id: int, text: str):
    sigs = _load_json(SIGNATURES_FILE)
    sigs[str(user_id)] = text
    _save_json(SIGNATURES_FILE, sigs)


def append_signature(user_id: int, text: str) -> str:
    sig = get_signature(user_id)
    return f"{text}\n\n{sig}" if sig else text


# ================== کانال متصل ==================

def get_channel(user_id: int):
    channels = _load_json(CHANNELS_FILE)
    return channels.get(str(user_id))


def set_channel(user_id: int, channel: str):
    channels = _load_json(CHANNELS_FILE)
    channels[str(user_id)] = channel
    _save_json(CHANNELS_FILE, channels)


def build_send_to_channel_button():
    return {"inline_keyboard": [[{"text": "📤 ارسال به کانال", "callback_data": "send_to_channel"}]]}


# ================== اعتبار هدیه (بونوس) ==================

def get_bonus(user_id: int) -> int:
    bonuses = _load_json(BONUS_FILE)
    return bonuses.get(str(user_id), 0)


def add_bonus(user_id: int, amount: int):
    bonuses = _load_json(BONUS_FILE)
    key = str(user_id)
    bonuses[key] = bonuses.get(key, 0) + amount
    _save_json(BONUS_FILE, bonuses)


def use_bonus(user_id: int):
    bonuses = _load_json(BONUS_FILE)
    key = str(user_id)
    bonuses[key] = max(0, bonuses.get(key, 0) - 1)
    _save_json(BONUS_FILE, bonuses)


# ================== سیستم دعوت (ریفرال) ==================

def register_referral(new_user_id: int, referrer_id: int):
    """اگه کاربر جدید قبلاً ثبت نشده بود، به هردو نفر اعتبار هدیه می‌ده"""
    if new_user_id == referrer_id:
        return
    referrals = _load_json(REFERRALS_FILE)
    if str(new_user_id) in referrals:
        return
    referrals[str(new_user_id)] = referrer_id
    _save_json(REFERRALS_FILE, referrals)
    add_bonus(referrer_id, REFERRAL_BONUS_FOR_REFERRER)
    add_bonus(new_user_id, REFERRAL_BONUS_FOR_NEWCOMER)
    send_message(referrer_id, f"🎉 یه نفر با لینک دعوتت اومد! {REFERRAL_BONUS_FOR_REFERRER} پست هدیه گرفتی.")


def get_referral_counts() -> dict:
    """تعداد دعوت موفق هر کاربر رو برمی‌گردونه: {آیدی_دعوت‌کننده: تعداد}"""
    referrals = _load_json(REFERRALS_FILE)
    counts = {}
    for referrer_id in referrals.values():
        key = str(referrer_id)
        counts[key] = counts.get(key, 0) + 1
    return counts


# ================== تحویل نهایی پست به کاربر ==================

def deliver_post(chat_id: int, user_id: int, text: str, info_msg: str = None):
    """برای پست‌های نهایی: امضا اضافه می‌کنه، توی تاریخچه ذخیره می‌کنه، دکمه‌ی ارسال به کانال می‌ذاره"""
    final_text = append_signature(user_id, text)
    add_history(user_id, final_text)
    last_generated_post[chat_id] = final_text
    markup = build_send_to_channel_button() if get_channel(user_id) else None
    send_message(chat_id, final_text, reply_markup=markup)
    if info_msg:
        send_message(chat_id, info_msg)


def deliver_info(chat_id: int, text: str, info_msg: str = None):
    """برای خروجی‌هایی که پست نهایی نیستن (هشتگ، بررسی حساسیت و...)"""
    send_message(chat_id, text)
    if info_msg:
        send_message(chat_id, info_msg)


# ================== ثبت کاربران (فقط برای آمار خود ادمین) ==================

USERS_FILE = "all_users.json"
PENDING_APPROVALS_FILE = "pending_approvals.json"


def register_pending_approval(message_id: int, user_id: int, plan_id: str):
    approvals = _load_json(PENDING_APPROVALS_FILE)
    approvals[str(message_id)] = {"user_id": user_id, "plan_id": plan_id}
    _save_json(PENDING_APPROVALS_FILE, approvals)


def pop_pending_approval(message_id: int):
    approvals = _load_json(PENDING_APPROVALS_FILE)
    entry = approvals.pop(str(message_id), None)
    if entry is not None:
        _save_json(PENDING_APPROVALS_FILE, approvals)
    return entry


def register_user(user_id: int, first_name: str = "", username: str = ""):
    users = _load_json(USERS_FILE)
    key = str(user_id)
    if key not in users:
        users[key] = {
            "first_name": first_name,
            "username": username,
            "first_seen": time.strftime("%Y-%m-%d"),
        }
        _save_json(USERS_FILE, users)


def get_total_users() -> int:
    return len(_load_json(USERS_FILE))


def get_active_users_this_month() -> int:
    stats = _load_stats()
    month = _current_month()
    return sum(1 for entry in stats.values() if entry.get("month") == month)


# ================== مسیر اصلی وبهوک ==================

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    message = update.get("message")

    # ثبت کاربر (برای آمار کلی خودت، هیچ تاثیری روی کاربر نداره)
    from_user = None
    if message:
        from_user = message.get("from")
    elif update.get("callback_query"):
        from_user = update["callback_query"].get("from")
    if from_user:
        register_user(from_user["id"], from_user.get("first_name", ""), from_user.get("username", ""))

    # ---------- پیام عکس ----------
    if message and "photo" in message:
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        best_photo = message["photo"][-1]

        # اگه کاربر منتظر تایید پرداخته، این عکس رو رسید در نظر بگیر
        if user_id in pending_purchases:
            plan_id = pending_purchases[user_id]
            user_info = message["from"]
            username = user_info.get("username", "بدون یوزرنیم")
            caption_receipt = (
                f"📥 رسید پرداخت جدید\n"
                f"کاربر: {user_info.get('first_name', '')} (@{username})\n"
                f"آیدی عددی: {user_id}\n"
                f"پلن درخواستی: {PLANS[plan_id]['label']}\n\n"
                f"برای تایید: /approve {user_id} {plan_id}"
            )
            forward_url = f"{TELEGRAM_API}/sendPhoto"
            forward_resp = requests.post(forward_url, json={"chat_id": ADMIN_ID, "photo": best_photo["file_id"], "caption": caption_receipt})
            try:
                forwarded_message_id = forward_resp.json()["result"]["message_id"]
                register_pending_approval(forwarded_message_id, user_id, plan_id)
            except Exception as e:
                print(f"خطا در ذخیره‌ی تاییدیه در انتظار: {e}")
            send_message(chat_id, "✅ رسیدت برای بررسی ارسال شد. به‌زودی اشتراکت فعال می‌شه.")
            del pending_purchases[user_id]
            return "OK", 200

        extra_caption = message.get("caption", "")

        prompt = PHOTO_CAPTION_PROMPT
        if extra_caption:
            prompt += f"\n\nتوضیح یا کپشنی که کاربر همراه عکس فرستاده: \"{extra_caption}\""

        image_bytes = get_telegram_file_bytes(best_photo["file_id"])
        caption = safe_gemini_call(call_gemini_with_media, prompt, image_bytes, "image/jpeg")
        if caption is None:
            send_message(chat_id, "⚠️ مشکلی در پردازش عکس پیش اومد. دوباره امتحان کن.")
            return "OK", 200

        allowed, err_msg, info_msg = consume_credit(user_id)
        if not allowed:
            send_message(chat_id, err_msg)
            return "OK", 200

        deliver_post(chat_id, user_id, caption, info_msg)
        return "OK", 200

    # ---------- پیام صوتی یا فایل صوتی/آهنگ: تبدیل به متن و بعد نمایش منو ----------
    voice_or_audio = message.get("voice") or message.get("audio") if message else None
    if message and voice_or_audio:
        chat_id = message["chat"]["id"]
        audio_bytes = get_telegram_file_bytes(voice_or_audio["file_id"])
        mime_type = voice_or_audio.get("mime_type", "audio/ogg")
        transcribe_prompt = "این فایل صوتی رو کلمه‌به‌کلمه به متن فارسی تبدیل کن. اگه آهنگ یا موسیقیه و صدای گفتاری نداره، فقط بنویس: NO_SPEECH. فقط متن پیاده‌شده یا NO_SPEECH رو برگردون، بدون هیچ توضیح اضافه."
        transcribed = safe_gemini_call(call_gemini_with_media, transcribe_prompt, audio_bytes, mime_type)
        if not transcribed:
            send_message(chat_id, "⚠️ نتونستم صدا رو تبدیل به متن کنم. دوباره امتحان کن.")
            return "OK", 200

        if transcribed.strip() == "NO_SPEECH":
            send_message(chat_id, "🎵 این یه آهنگ/موسیقیه و صدای گفتاری نداره، نمی‌تونم ازش پست بسازم.")
            return "OK", 200

        pending_texts[chat_id] = transcribed
        send_message(
            chat_id,
            f"📝 متن پیاده‌شده:\n{transcribed}\n\nحالا چیکار کنم؟ 👇",
            reply_markup=build_main_menu(),
        )
        return "OK", 200

    # ---------- پیام متنی ----------
    if message and "text" in message:
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        text = message["text"]

        # اگه ادمین روی یه پیام رسید ریپلای زده باشه، خودکار تایید/رد کن
        if user_id == ADMIN_ID and message.get("reply_to_message"):
            replied_id = message["reply_to_message"]["message_id"]
            approval = pop_pending_approval(replied_id)
            if approval:
                target_user_id = approval["user_id"]
                plan_id = approval["plan_id"]
                if "رد" in text or text.strip().lower() in ("no", "n"):
                    send_message(chat_id, f"❌ پرداخت {target_user_id} رد شد.")
                    send_message(target_user_id, "متاسفانه پرداختت تایید نشد. لطفاً دوباره چک کن یا با /support تماس بگیر.")
                else:
                    expires = activate_subscription(target_user_id, plan_id)
                    pending_purchases.pop(target_user_id, None)
                    send_message(chat_id, f"✅ اشتراک {PLANS[plan_id]['label']} برای {target_user_id} تا {expires} فعال شد.")
                    send_message(target_user_id, f"🎉 اشتراکت فعال شد!\nپلن: {PLANS[plan_id]['label']}\nتا تاریخ: {expires}")
                return "OK", 200

        if text.strip() == "/stats":
            count = get_usage(user_id)
            bonus = get_bonus(user_id)
            sub = get_subscription(user_id)
            msg = f"📊 این ماه {count} از {FREE_MONTHLY_QUOTA} پست رایگانت استفاده شده."
            if bonus > 0:
                msg += f"\n🎁 اعتبار هدیه باقی‌مانده: {bonus}"
            if sub:
                quota_txt = "نامحدود" if sub["quota_left"] is None else f"{sub['quota_left']} پست باقی‌مانده"
                msg += f"\n\n💳 اشتراک فعال: {PLANS[sub['plan']]['label']}\nتا تاریخ: {sub['expires']}\n{quota_txt}"
            send_message(chat_id, msg)
            return "OK", 200

        if text.strip() == "/myplan":
            sub = get_subscription(user_id)
            if not sub:
                send_message(chat_id, "اشتراک فعالی نداری. برای خرید /buy رو بزن.")
            else:
                quota_txt = "نامحدود" if sub["quota_left"] is None else f"{sub['quota_left']} پست باقی‌مانده"
                send_message(chat_id, f"💳 پلن: {PLANS[sub['plan']]['label']}\nتا تاریخ: {sub['expires']}\n{quota_txt}")
            return "OK", 200

        if text.strip() == "/buy":
            send_message(chat_id, "کدوم پلن رو می‌خوای؟ 👇", reply_markup=build_plans_menu())
            return "OK", 200

        if text.strip() == "/history":
            entries = get_history(user_id)
            if not entries:
                send_message(chat_id, "هنوز پستی نساختی.")
            else:
                msg = "🗂 آخرین پست‌هات:\n\n" + "\n\n---\n\n".join(
                    f"{i+1}. {e[:200]}{'...' if len(e) > 200 else ''}" for i, e in enumerate(entries)
                )
                send_message(chat_id, msg)
            return "OK", 200

        if text.strip().startswith("/setsignature"):
            sig_text = text.strip()[len("/setsignature"):].strip()
            if not sig_text:
                send_message(chat_id, "بعد از دستور، امضات رو بنویس. مثال:\n/setsignature 📢 کانال شهر سنندج | @mychannel")
            else:
                set_signature(user_id, sig_text)
                send_message(chat_id, f"✅ امضات ثبت شد و از این به بعد به آخر هر پست اضافه می‌شه:\n\n{sig_text}")
            return "OK", 200

        if text.strip().startswith("/setchannel"):
            channel_id = text.strip()[len("/setchannel"):].strip()
            if not channel_id:
                send_message(chat_id, "بعد از دستور، آیدی کانالت رو بنویس. مثال:\n/setchannel @mychannel\n\n⚠️ یادت نره ربات رو اول ادمین کانالت کنی.")
            else:
                set_channel(user_id, channel_id)
                send_message(chat_id, f"✅ کانالت ({channel_id}) ثبت شد. از این به بعد دکمه‌ی «ارسال به کانال» زیر پست‌هات میاد.")
            return "OK", 200

        if text.strip() == "/idea":
            result = safe_gemini_call(call_gemini_text, IDEA_PROMPT)
            if result is None:
                send_message(chat_id, "⚠️ الان نتونستم ایده بسازم. دوباره امتحان کن.")
            else:
                send_message(chat_id, f"💡 چند تا ایده برای پست امروز:\n\n{result}")
            return "OK", 200

        if text.strip() == "/leaderboard":
            counts = get_referral_counts()
            if not counts:
                send_message(chat_id, "هنوز کسی کس دیگه‌ای رو دعوت نکرده. اولین نفر باش! /invite")
            else:
                top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
                users = _load_json(USERS_FILE)
                lines = []
                for i, (uid, count) in enumerate(top, start=1):
                    name = users.get(uid, {}).get("first_name") or f"کاربر {uid}"
                    lines.append(f"{i}. {name} — {count} دعوت موفق")
                send_message(chat_id, "🏆 برترین دعوت‌کننده‌ها:\n\n" + "\n".join(lines))
            return "OK", 200

        if text.strip() == "/invite":
            link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
            send_message(
                chat_id,
                f"👥 این لینک اختصاصی خودته:\n{link}\n\n"
                f"هر کسی با این لینک بیاد و شروع کنه، تو {REFERRAL_BONUS_FOR_REFERRER} پست هدیه می‌گیری "
                f"و اون هم {REFERRAL_BONUS_FOR_NEWCOMER} پست هدیه‌ی خوش‌آمدگویی می‌گیره.",
            )
            return "OK", 200

        # دستور مخصوص ادمین: هدیه دادن پست به هرکسی
        # دستور مخصوص ادمین: ارسال پیام همگانی به همه کاربرا
        if text.strip().startswith("/broadcast") and user_id == ADMIN_ID:
            broadcast_text = text.strip()[len("/broadcast"):].strip()
            if not broadcast_text:
                send_message(chat_id, "بعد از دستور، متن پیام همگانی رو بنویس.\nمثال: /broadcast سلام، ربات آپدیت جدید گرفت!")
                return "OK", 200
            users = _load_json(USERS_FILE)
            sent, failed = 0, 0
            for uid in users:
                try:
                    resp = send_message(int(uid), broadcast_text)
                    if resp is not None and resp.status_code == 200:
                        sent += 1
                    else:
                        failed += 1
                except Exception as e:
                    print(f"خطا در ارسال همگانی به {uid}: {e}")
                    failed += 1
                time.sleep(0.1)
            send_message(chat_id, f"📢 پیام همگانی ارسال شد.\n✅ موفق: {sent}\n❌ ناموفق: {failed}")
            return "OK", 200

        if text.strip().startswith("/gift") and user_id == ADMIN_ID:
            parts = text.strip().split()
            if len(parts) != 3 or not parts[2].isdigit():
                send_message(chat_id, "فرمت درست: /gift USER_ID تعداد\nمثال: /gift 123456789 10")
                return "OK", 200
            target_user_id = int(parts[1])
            amount = int(parts[2])
            add_bonus(target_user_id, amount)
            send_message(chat_id, f"🎁 {amount} پست هدیه به {target_user_id} داده شد.")
            send_message(target_user_id, f"🎁 ادمین بهت {amount} پست هدیه داد! از /stats می‌تونی ببینیش.")
            return "OK", 200

        # دستور مخصوص ادمین: آمار کلی کاربران
        if text.strip() == "/users" and user_id == ADMIN_ID:
            total = get_total_users()
            active = get_active_users_this_month()
            send_message(chat_id, f"👥 تعداد کل کاربران: {total}\n📈 فعال در این ماه: {active}")
            return "OK", 200

        if text.strip().startswith("/support"):
            support_text = text.strip()[len("/support"):].strip()
            if not support_text:
                send_message(chat_id, "بعد از دستور، مشکلت رو بنویس. مثال:\n/support ربات برام تصویر نمی‌سازه")
            else:
                user_info = message["from"]
                username = user_info.get("username", "بدون یوزرنیم")
                admin_msg = (
                    f"🆘 پیام پشتیبانی جدید\n"
                    f"کاربر: {user_info.get('first_name', '')} (@{username})\n"
                    f"آیدی عددی: {user_id}\n\n"
                    f"متن پیام:\n{support_text}\n\n"
                    f"برای پاسخ: /reply {user_id} متن‌جوابت"
                )
                send_message(ADMIN_ID, admin_msg)
                send_message(chat_id, "✅ پیامت برای پشتیبانی ارسال شد. به‌زودی جواب می‌گیری.")
            return "OK", 200

        # دستور مخصوص ادمین برای پاسخ به پشتیبانی: /reply <user_id> <متن>
        if text.strip().startswith("/reply") and user_id == ADMIN_ID:
            parts = text.strip().split(maxsplit=2)
            if len(parts) != 3:
                send_message(chat_id, "فرمت درست: /reply USER_ID متن‌جواب")
                return "OK", 200
            target_user_id = int(parts[1])
            reply_text = parts[2]
            send_message(target_user_id, f"💬 پاسخ پشتیبانی:\n{reply_text}")
            send_message(chat_id, f"✅ جواب برای {target_user_id} ارسال شد.")
            return "OK", 200

        # دستور مخصوص ادمین برای تایید پرداخت: /approve <user_id> <plan_id>
        if text.strip().startswith("/approve") and user_id == ADMIN_ID:
            parts = text.strip().split()
            if len(parts) != 3 or parts[2] not in PLANS:
                send_message(chat_id, "فرمت درست: /approve USER_ID PLAN_ID\nپلن‌ها: " + ", ".join(PLANS.keys()))
                return "OK", 200
            target_user_id = int(parts[1])
            plan_id = parts[2]
            expires = activate_subscription(target_user_id, plan_id)
            pending_purchases.pop(target_user_id, None)
            send_message(chat_id, f"✅ اشتراک {PLANS[plan_id]['label']} برای {target_user_id} تا {expires} فعال شد.")
            send_message(target_user_id, f"🎉 اشتراکت فعال شد!\nپلن: {PLANS[plan_id]['label']}\nتا تاریخ: {expires}")
            return "OK", 200

        if text.strip().startswith("/start"):
            parts = text.strip().split(maxsplit=1)
            if len(parts) == 2 and parts[1].startswith("ref_"):
                try:
                    referrer_id = int(parts[1][len("ref_"):])
                    register_referral(user_id, referrer_id)
                except ValueError:
                    pass
            welcome_resp = send_message(
                chat_id,
                "سلام! 👋 به کانال‌یار خوش اومدی — دستیار هوش مصنوعی ادمین‌های کانال، ساخته‌ی مهیار 🚀\n\n"
                "یه متن خام، عکس یا ویس بفرست، بعد از منو انتخاب کن چیکار کنم.\n\n"
                "برای دیدن توضیح کامل همه‌ی قابلیت‌ها: /help\n\n"
                f"هر ماه {FREE_MONTHLY_QUOTA} پست کاملاً رایگان داری. شروع کن! 🎉",
            )
            try:
                message_id = welcome_resp.json()["result"]["message_id"]
                pin_message(chat_id, message_id)
            except Exception as e:
                print(f"خطا در سنجاق کردن پیام: {e}")
            return "OK", 200

        if text.strip() == "/help":
            send_message(
                chat_id,
                "📖 راهنمای کامل کانال‌یار\n\n"
                "🔹 چطور شروع کنم؟\n"
                "یه متن خام (خبر، اطلاعیه، هر چی) بفرست، عکس بفرست، یا ویس بفرست. بعدش یه منو میاد که چیکار می‌خوای بکنم.\n\n"
                "🔹 قابلیت‌های منو (بعد از فرستادن متن):\n"
                "📝 ساخت پست — با ۸ سبک: خبری، طنز، احساسی، تیتر جذاب، هشدار، تبلیغاتی، محاوره‌ای، بولت‌وار\n"
                "✂️ خلاصه‌سازی — متن طولانی رو کوتاه و آماده انتشار می‌کنه\n"
                "✅ تصحیح املا — غلط‌های نگارشی رو درست می‌کنه، لحنت رو عوض نمی‌کنه\n"
                "🌐 ترجمه — به کردی سورانی یا انگلیسی\n"
                "🖼 ساخت تصویر — یه عکس واقعی و مرتبط با متن برات می‌سازه\n"
                "#️⃣ پیشنهاد هشتگ — چندتا هشتگ مرتبط پیشنهاد می‌ده\n"
                "↔️ کوتاه/بلندتر — طول متن رو تغییر می‌ده\n"
                "📊 ساخت نظرسنجی — یه Poll واقعی تلگرامی می‌سازه\n"
                "🛡 بررسی حساسیت — می‌گه متنت مشکل احتمالی داره یا نه\n"
                "📸 کپشن اینستاگرام — کپشن با فرمت و هشتگ مخصوص اینستاگرام\n"
                "🌍 همه پلتفرم‌ها — تلگرام + اینستاگرام + کردی، همه با هم یکجا\n\n"
                "🔹 عکس بفرستی → خودش کپشن حرفه‌ای می‌سازه (بدون نیاز به منو)\n"
                "🔹 ویس بفرستی → پیاده میشه متن، بعد منو میاد که چیکارش کنم\n\n"
                "🔹 دستورات مفید:\n"
                "/idea — چند تا ایده‌ی پست، همیشه رایگان و نامحدود\n"
                "/history — ۵ پست آخرت\n"
                "/setsignature متن — امضای ثابت که خودکار به آخر هر پست اضافه می‌شه\n"
                "/setchannel @کانالت — بعدش زیر هر پست دکمه‌ی «ارسال به کانال» میاد (ربات باید ادمین کانالت باشه)\n"
                "/invite — لینک دعوت؛ هرکی بیاد، پست هدیه می‌گیری\n"
                "/leaderboard — برترین دعوت‌کننده‌ها\n"
                "/stats — سهمیه و اشتراک فعلیت\n"
                "/buy — خرید اشتراک\n"
                "/support متن‌مشکلت — ارتباط با پشتیبانی\n\n"
                f"هر ماه {FREE_MONTHLY_QUOTA} پست کاملاً رایگانه، بدون نیاز به کارت یا ثبت‌نام.",
            )
            return "OK", 200

        pending_texts[chat_id] = text
        send_message(chat_id, "چیکار کنم با این متن؟ 👇", reply_markup=build_main_menu())
        return "OK", 200

    # ---------- کلیک روی دکمه‌ها ----------
    callback_query = update.get("callback_query")
    if callback_query:
        chat_id = callback_query["message"]["chat"]["id"]
        user_id = callback_query["from"]["id"]
        data = callback_query["data"]
        callback_id = callback_query["id"]
        answer_callback(callback_id)

        # ارسال آخرین پست ساخته‌شده به کانال متصل
        if data == "send_to_channel":
            channel_id = get_channel(user_id)
            post_text = last_generated_post.get(chat_id)
            if not channel_id:
                send_message(chat_id, "هنوز کانالی وصل نکردی. اول /setchannel رو بزن.")
            elif not post_text:
                send_message(chat_id, "⚠️ پستی برای ارسال پیدا نشد.")
            else:
                try:
                    send_message(channel_id, post_text)
                    send_message(chat_id, "✅ پست به کانالت ارسال شد.")
                except Exception as e:
                    print(f"خطا در ارسال به کانال: {e}")
                    send_message(chat_id, "⚠️ نتونستم به کانال بفرستم. مطمئن شو ربات ادمین کانالته.")
            return "OK", 200

        # انتخاب پلن خرید
        if data.startswith("plan:"):
            plan_id = data.split(":", 1)[1]
            plan = PLANS[plan_id]
            pending_purchases[user_id] = plan_id
            send_message(
                chat_id,
                f"پلن انتخابی: {plan['label']}\n\n"
                f"💳 لطفاً مبلغ {plan['price']:,} تومان رو به این شماره کارت واریز کن:\n"
                f"{CARD_NUMBER}\nبه نام: {CARD_HOLDER}\n\n"
                f"بعد از واریز، فقط عکس رسید رو همینجا بفرست تا برای بررسی برام ارسال بشه.",
            )
            return "OK", 200

        raw_text = pending_texts.get(chat_id)
        if not raw_text:
            send_message(chat_id, "⚠️ متنی پیدا نشد، لطفاً دوباره پیامت رو بفرست.")
            return "OK", 200

        # منوی اصلی: چه کاری انجام بشه
        if data.startswith("act:"):
            action = data.split(":", 1)[1]

            if action == "style":
                send_message(chat_id, "چه سبکی؟ 👇", reply_markup=build_style_menu())
                return "OK", 200

            if action == "translate":
                send_message(chat_id, "به چه زبانی؟ 👇", reply_markup=build_lang_menu())
                return "OK", 200

            if action == "length":
                send_message(chat_id, "کوتاه‌تر کنم یا بلندتر؟ 👇", reply_markup=build_length_menu())
                return "OK", 200

            if action == "summary":
                result = safe_gemini_call(call_gemini_text, SUMMARY_PROMPT.format(raw_text=raw_text))
                if result is None:
                    send_message(chat_id, "⚠️ مشکلی پیش اومد. دوباره امتحان کن.")
                    return "OK", 200
                allowed, err_msg, info_msg = consume_credit(user_id)
                if not allowed:
                    send_message(chat_id, err_msg)
                    return "OK", 200
                deliver_post(chat_id, user_id, result, info_msg)

            elif action == "fix":
                result = safe_gemini_call(call_gemini_text, FIX_PROMPT.format(raw_text=raw_text))
                if result is None:
                    send_message(chat_id, "⚠️ مشکلی پیش اومد. دوباره امتحان کن.")
                    return "OK", 200
                allowed, err_msg, info_msg = consume_credit(user_id)
                if not allowed:
                    send_message(chat_id, err_msg)
                    return "OK", 200
                deliver_post(chat_id, user_id, result, info_msg)

            elif action == "image":
                send_message(chat_id, "⏳ در حال ساخت تصویر... (ممکنه ۳۰-۶۰ ثانیه طول بکشه)")
                try:
                    image_bytes = generate_image(raw_text)
                except Exception as e:
                    print(f"خطا در ساخت تصویر: {e}")
                    send_message(chat_id, "⚠️ نتونستم تصویر بسازم. دوباره امتحان کن.")
                    return "OK", 200
                allowed, err_msg, info_msg = consume_credit(user_id)
                if not allowed:
                    send_message(chat_id, err_msg)
                    return "OK", 200
                send_photo_bytes(chat_id, image_bytes)
                if info_msg:
                    send_message(chat_id, info_msg)

            elif action == "hashtags":
                result = safe_gemini_call(call_gemini_text, HASHTAG_PROMPT.format(raw_text=raw_text))
                if result is None:
                    send_message(chat_id, "⚠️ مشکلی پیش اومد. دوباره امتحان کن.")
                    return "OK", 200
                allowed, err_msg, info_msg = consume_credit(user_id)
                if not allowed:
                    send_message(chat_id, err_msg)
                    return "OK", 200
                deliver_info(chat_id, result, info_msg)

            elif action == "poll":
                raw_json = safe_gemini_call(call_gemini_text, POLL_PROMPT.format(raw_text=raw_text))
                poll_data = None
                if raw_json is not None:
                    try:
                        cleaned = re.sub(r"^```json|```$", "", raw_json.strip(), flags=re.MULTILINE).strip()
                        poll_data = json.loads(cleaned)
                        if len(poll_data.get("options", [])) < 2:
                            poll_data = None
                    except Exception as e:
                        print(f"خطا در پردازش نظرسنجی: {e}")
                        poll_data = None
                if poll_data is None:
                    send_message(chat_id, "⚠️ نتونستم نظرسنجی بسازم. دوباره امتحان کن.")
                    return "OK", 200
                allowed, err_msg, info_msg = consume_credit(user_id)
                if not allowed:
                    send_message(chat_id, err_msg)
                    return "OK", 200
                send_poll(chat_id, poll_data["question"], poll_data["options"])
                if info_msg:
                    send_message(chat_id, info_msg)

            elif action == "moderate":
                result = safe_gemini_call(call_gemini_text, MODERATE_PROMPT.format(raw_text=raw_text))
                if result is None:
                    send_message(chat_id, "⚠️ مشکلی پیش اومد. دوباره امتحان کن.")
                    return "OK", 200
                allowed, err_msg, info_msg = consume_credit(user_id)
                if not allowed:
                    send_message(chat_id, err_msg)
                    return "OK", 200
                deliver_info(chat_id, result, info_msg)

            elif action == "instagram":
                result = safe_gemini_call(call_gemini_text, INSTAGRAM_PROMPT.format(raw_text=raw_text))
                if result is None:
                    send_message(chat_id, "⚠️ مشکلی پیش اومد. دوباره امتحان کن.")
                    return "OK", 200
                allowed, err_msg, info_msg = consume_credit(user_id)
                if not allowed:
                    send_message(chat_id, err_msg)
                    return "OK", 200
                deliver_post(chat_id, user_id, result, info_msg)

            elif action == "allplatforms":
                tg = safe_gemini_call(call_gemini_text, STYLE_PROMPT.format(style_instruction=STYLES["news"]["instruction"], raw_text=raw_text))
                ig = safe_gemini_call(call_gemini_text, INSTAGRAM_PROMPT.format(raw_text=raw_text))
                ku = safe_gemini_call(call_gemini_text, TRANSLATE_PROMPT.format(language=LANGUAGES["ku"]["name"], raw_text=raw_text))
                if tg is None or ig is None or ku is None:
                    send_message(chat_id, "⚠️ مشکلی پیش اومد. دوباره امتحان کن.")
                    return "OK", 200
                allowed, err_msg, info_msg = consume_credit(user_id)
                if not allowed:
                    send_message(chat_id, err_msg)
                    return "OK", 200
                combined = (
                    f"📱 نسخه تلگرام:\n{tg}\n\n"
                    f"📸 نسخه اینستاگرام:\n{ig}\n\n"
                    f"🌐 نسخه کردی سورانی:\n{ku}"
                )
                deliver_post(chat_id, user_id, combined, info_msg)

            return "OK", 200

        # کوتاه‌تر یا بلندتر کردن متن
        if data.startswith("len:"):
            send_message(chat_id, "⏳ در حال ساخت...")
            length_key = data.split(":", 1)[1]
            prompt = SHORTEN_PROMPT.format(raw_text=raw_text) if length_key == "short" else LENGTHEN_PROMPT.format(raw_text=raw_text)
            result = safe_gemini_call(call_gemini_text, prompt)
            if result is None:
                send_message(chat_id, "⚠️ مشکلی پیش اومد. دوباره امتحان کن.")
                return "OK", 200
            allowed, err_msg, info_msg = consume_credit(user_id)
            if not allowed:
                send_message(chat_id, err_msg)
                return "OK", 200
            deliver_post(chat_id, user_id, result, info_msg)
            return "OK", 200

        # انتخاب سبک پست
        if data.startswith("style:"):
            send_message(chat_id, "⏳ در حال ساخت...")
            style_key = data.split(":", 1)[1]
            prompt = STYLE_PROMPT.format(style_instruction=STYLES[style_key]["instruction"], raw_text=raw_text)
            result = safe_gemini_call(call_gemini_text, prompt)
            if result is None:
                send_message(chat_id, "⚠️ مشکلی پیش اومد. دوباره امتحان کن.")
                return "OK", 200
            allowed, err_msg, info_msg = consume_credit(user_id)
            if not allowed:
                send_message(chat_id, err_msg)
                return "OK", 200
            deliver_post(chat_id, user_id, result, info_msg)
            return "OK", 200

        # انتخاب زبان ترجمه
        if data.startswith("lang:"):
            send_message(chat_id, "⏳ در حال ساخت...")
            lang_key = data.split(":", 1)[1]
            prompt = TRANSLATE_PROMPT.format(language=LANGUAGES[lang_key]["name"], raw_text=raw_text)
            result = safe_gemini_call(call_gemini_text, prompt)
            if result is None:
                send_message(chat_id, "⚠️ مشکلی پیش اومد. دوباره امتحان کن.")
                return "OK", 200
            allowed, err_msg, info_msg = consume_credit(user_id)
            if not allowed:
                send_message(chat_id, err_msg)
                return "OK", 200
            deliver_post(chat_id, user_id, result, info_msg)
            return "OK", 200

    return "OK", 200


@app.route("/")
def home():
    return "ربات فعاله و در حال کار کردنه ✅"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

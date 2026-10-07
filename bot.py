import json
import os
import re
import unicodedata
from datetime import datetime

import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================================================
# API KEYS
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
REBRICKABLE_API_KEY = os.getenv("REBRICKABLE_API_KEY")
BRICKSET_API_KEY = os.getenv("BRICKSET_API_KEY")


# =========================================================
# FILES
# =========================================================

COLLECTION_FILE = "collection.json"
WISHLIST_FILE = "wishlist.json"


# =========================================================
# API URLS
# =========================================================

REBRICKABLE_BASE = "https://rebrickable.com/api/v3/lego"
BRICKSET_BASE = "https://brickset.com/api/v3.asmx"
FRANKFURTER_BASE = "https://api.frankfurter.dev/v2"


# =========================================================
# BASIC HELPERS
# =========================================================

def normalize_set_number(value):
    value = str(value).strip()

    if "-" in value:
        value = value.split("-")[0]

    if not value.isdigit():
        return None

    if not 4 <= len(value) <= 6:
        return None

    return value


def normalize_text(text):
    text = text.lower()

    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )

    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()

    return text


# =========================================================
# COLLECTION
# =========================================================

def load_collection():
    if not os.path.exists(COLLECTION_FILE):
        return {}

    try:
        with open(COLLECTION_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def save_collection(collection):
    with open(COLLECTION_FILE, "w", encoding="utf-8") as file:
        json.dump(collection, file, ensure_ascii=False, indent=2)


def get_user_collection(user_id):
    collection = load_collection()
    return collection.get(str(user_id), [])


def add_to_collection(user_id, set_number):
    collection = load_collection()

    user_key = str(user_id)

    if user_key not in collection:
        collection[user_key] = []

    if set_number not in collection[user_key]:
        collection[user_key].append(set_number)
        save_collection(collection)
        return True

    return False


def remove_from_collection(user_id, set_number):
    collection = load_collection()

    user_key = str(user_id)

    if user_key not in collection:
        return False

    if set_number not in collection[user_key]:
        return False

    collection[user_key].remove(set_number)
    save_collection(collection)

    return True


# =========================================================
# WISHLIST
# =========================================================

def load_wishlist():
    if not os.path.exists(WISHLIST_FILE):
        return {}

    try:
        with open(WISHLIST_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def save_wishlist(wishlist):
    with open(WISHLIST_FILE, "w", encoding="utf-8") as file:
        json.dump(wishlist, file, ensure_ascii=False, indent=2)


def get_user_wishlist(user_id):
    wishlist = load_wishlist()
    return wishlist.get(str(user_id), [])


def add_to_wishlist(user_id, set_number):
    wishlist = load_wishlist()

    user_key = str(user_id)

    if user_key not in wishlist:
        wishlist[user_key] = []

    if set_number not in wishlist[user_key]:
        wishlist[user_key].append(set_number)
        save_wishlist(wishlist)
        return True

    return False


def remove_from_wishlist(user_id, set_number):
    wishlist = load_wishlist()

    user_key = str(user_id)

    if user_key not in wishlist:
        return False

    if set_number not in wishlist[user_key]:
        return False

    wishlist[user_key].remove(set_number)
    save_wishlist(wishlist)

    return True


# =========================================================
# REBRICKABLE
# =========================================================

def get_rebrickable_set(set_number):
    url = f"{REBRICKABLE_BASE}/sets/{set_number}-1/"

    headers = {
        "Authorization": f"key {REBRICKABLE_API_KEY}"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:
            return None

        return response.json()

    except Exception:
        return None


def search_rebrickable_sets(search_text):
    url = f"{REBRICKABLE_BASE}/sets/"

    headers = {
        "Authorization": f"key {REBRICKABLE_API_KEY}"
    }

    params = {
        "search": search_text,
        "page_size": 10,
        "page": 1,
        "ordering": "-year"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code != 200:
            return []

        data = response.json()

        return data.get("results", [])

    except Exception:
        return []


# =========================================================
# BRICKSET
# =========================================================

def get_brickset_set(set_number):
    url = f"{BRICKSET_BASE}/getSets"

    params = {
        "apiKey": BRICKSET_API_KEY,
        "userHash": "",
        "params": json.dumps({
            "setNumber": f"{set_number}-1",
            "pageSize": 1,
            "pageNumber": 1
        })
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=15
        )

        if response.status_code != 200:
            return None

        data = response.json()

        sets = data.get("sets", [])

        if not sets:
            return None

        return sets[0]

    except Exception:
        return None


# =========================================================
# RRP
# =========================================================

def get_rrp(brickset_data):
    if not brickset_data:
        return None

    lego_com = brickset_data.get("LEGOCom", {})

    if isinstance(lego_com, dict):

        de_data = lego_com.get("DE")

        if isinstance(de_data, dict):
            price = de_data.get("retailPrice")

            if isinstance(price, (int, float)):
                return float(price)

        uk_data = lego_com.get("UK")

        if isinstance(uk_data, dict):
            price = uk_data.get("retailPrice")

            if isinstance(price, (int, float)):
                return float(price)

        us_data = lego_com.get("US")

        if isinstance(us_data, dict):
            price = us_data.get("retailPrice")

            if isinstance(price, (int, float)):
                return float(price)

    for field in ["retailPrice", "RRP", "rrp", "price"]:

        value = brickset_data.get(field)

        if isinstance(value, (int, float)):
            return float(value)

    return None


# =========================================================
# STATUS
# =========================================================

def get_set_status(brickset_data, year):

    if not brickset_data:
        return "❓ Άγνωστη"

    released = brickset_data.get("released")
    launch_date = brickset_data.get("launchDate")
    exit_date = brickset_data.get("exitDate")

    today = datetime.now().date()

    if released is False:
        return "🔵 Δεν έχει κυκλοφορήσει ακόμα"

    if exit_date:

        try:
            exit_date_obj = datetime.strptime(
                exit_date[:10],
                "%Y-%m-%d"
            ).date()

            if today > exit_date_obj:
                return "🔴 Retired"

        except Exception:
            pass

    if launch_date:

        try:
            launch_date_obj = datetime.strptime(
                launch_date[:10],
                "%Y-%m-%d"
            ).date()

            if today >= launch_date_obj:
                return "🟢 Σε κυκλοφορία"

        except Exception:
            pass

    if released is True:
        return "🟢 Σε κυκλοφορία"

    return "❓ Άγνωστη"


def calculate_age(year):

    try:
        current_year = datetime.now().year
        return current_year - int(year)

    except Exception:
        return None


# =========================================================
# CURRENCY
# =========================================================

CURRENCY_ALIASES = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "ευρω": "EUR",
    "ευρώ": "EUR",

    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",

    "£": "GBP",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",

    "¥": "JPY",
    "jpy": "JPY",
    "yen": "JPY",

    "cny": "CNY",
    "yuan": "CNY",

    "cad": "CAD",
    "aud": "AUD",
    "chf": "CHF",
    "sek": "SEK",
    "nok": "NOK",
    "dkk": "DKK",
    "pln": "PLN",
    "czk": "CZK",
    "huf": "HUF",
}


def find_currency(text):

    normalized = normalize_text(text)

    for alias, code in CURRENCY_ALIASES.items():

        if alias in text.lower() or alias in normalized:
            return code

    match = re.search(r"\b([A-Za-z]{3})\b", text)

    if match:
        return match.group(1).upper()

    return None


def extract_price(text):

    currency = find_currency(text)

    cleaned = text

    if currency:

        for alias, code in CURRENCY_ALIASES.items():

            if code == currency:

                cleaned = cleaned.replace(alias, "")
                cleaned = cleaned.replace(alias.upper(), "")
                cleaned = cleaned.replace(alias.capitalize(), "")

    cleaned = re.sub(r"[€$£¥]", "", cleaned)

    numbers = re.findall(
        r"\d+(?:[.,]\d+)?",
        cleaned
    )

    if not numbers:
        return None, currency

    try:

        amount = float(
            numbers[-1].replace(",", ".")
        )

        if currency is None:
            currency = "EUR"

        return amount, currency

    except Exception:
        return None, currency


def convert_to_eur(amount, currency):

    if currency == "EUR":
        return amount

    url = f"{FRANKFURTER_BASE}/rate/{currency}/EUR"

    try:

        response = requests.get(
            url,
            timeout=15
        )

        if response.status_code != 200:
            return None

        data = response.json()

        rate = data.get("rate")

        if rate is None:
            return None

        return amount * float(rate)

    except Exception:
        return None


def price_rating(discount_percent):

    if discount_percent >= 30:
        return "🟢 Εξαιρετική τιμή!"

    if discount_percent >= 15:
        return "🟢 Πολύ καλή τιμή!"

    if discount_percent >= 5:
        return "🟡 Καλή τιμή"

    if discount_percent >= 0:
        return "🟠 Μικρή έκπτωση"

    if discount_percent > -10:
        return "🔴 Πάνω από το RRP"

    return "🔴 Αρκετά πάνω από το RRP"


# =========================================================
# FULL SET INFORMATION
# =========================================================

def get_set_information(set_number):

    rebrickable = get_rebrickable_set(set_number)

    if not rebrickable:
        return None

    brickset = get_brickset_set(set_number)

    name = rebrickable.get(
        "name",
        "Άγνωστο"
    )

    year = rebrickable.get("year")
    pieces = rebrickable.get("num_parts")
    image = rebrickable.get("set_img_url")

    rrp = get_rrp(brickset)

    status = get_set_status(
        brickset,
        year
    )

    age = calculate_age(year)

    launch_date = None
    exit_date = None

    if brickset:

        launch_date = brickset.get(
            "launchDate"
        )

        exit_date = brickset.get(
            "exitDate"
        )

    price_per_piece = None

    if rrp and pieces:

        try:
            price_per_piece = rrp / pieces

        except Exception:
            pass

    return {
        "set_number": set_number,
        "name": name,
        "year": year,
        "pieces": pieces,
        "image": image,
        "rrp": rrp,
        "status": status,
        "age": age,
        "launch_date": launch_date,
        "exit_date": exit_date,
        "price_per_piece": price_per_piece,
    }


# =========================================================
# BUTTONS
# =========================================================

def get_set_buttons(set_number):

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "➕ Collection",
                callback_data=f"addcollection:{set_number}"
            ),
            InlineKeyboardButton(
                "⭐ Wishlist",
                callback_data=f"addwishlist:{set_number}"
            )
        ],

        [
            InlineKeyboardButton(
                "🛒 LEGO",
                url=(
                    "https://www.lego.com/en-gb/search"
                    f"?q={set_number}"
                )
            ),

            InlineKeyboardButton(
                "🛍️ eBay",
                url=(
                    "https://www.ebay.com/sch/i.html"
                    f"?_nkw=LEGO+{set_number}"
                )
            )
        ],

        [
            InlineKeyboardButton(
                "🧱 BrickLink",
                url=(
                    "https://www.bricklink.com/v2/catalog/"
                    f"catalogitem.page?S={set_number}-1"
                )
            ),

            InlineKeyboardButton(
                "📊 Price Guide",
                url=(
                    "https://www.bricklink.com/catalogPG.asp"
                    f"?S={set_number}-1&ColorID=0"
                )
            )
        ]

    ])


# =========================================================
# SEND SET INFORMATION
# =========================================================

async def send_set_information(message, set_info):

    set_number = set_info["set_number"]

    text = (
        f"🧱 <b>{set_info['name']}</b>\n\n"
        f"🔢 Set: <b>{set_number}</b>\n"
        f"📅 Year: <b>{set_info['year']}</b>\n"
        f"🧩 Pieces: <b>{set_info['pieces']}</b>\n"
        f"📌 Status: <b>{set_info['status']}</b>\n"
    )

    if set_info["age"] is not None:

        text += (
            f"⏳ Age: "
            f"<b>{set_info['age']} χρόνια</b>\n"
        )

    if set_info["launch_date"]:

        text += (
            f"🚀 Launch: "
            f"<b>{set_info['launch_date'][:10]}</b>\n"
        )

    if set_info["exit_date"]:

        text += (
            f"🏁 Exit: "
            f"<b>{set_info['exit_date'][:10]}</b>\n"
        )

    if set_info["rrp"] is not None:

        text += (
            f"💰 RRP: "
            f"<b>€{set_info['rrp']:.2f}</b>\n"
        )

    if set_info["price_per_piece"] is not None:

        text += (
            f"📐 Price per piece: "
            f"<b>€{set_info['price_per_piece']:.2f}</b>\n"
        )

    await message.reply_photo(
        photo=set_info["image"],
        caption=text,
        parse_mode="HTML",
        reply_markup=get_set_buttons(set_number)
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "👋 <b>Καλώς ήρθες στο LEGO Bot!</b>\n\n"

        "🔎 Γράψε έναν αριθμό LEGO set, π.χ.:\n"
        "<code>10316</code>\n\n"

        "💰 Μπορείς επίσης να γράψεις τιμή με το νόμισμά της:\n"
        "<code>10316 420 EUR</code>\n"
        "<code>10316 500 USD</code>\n"
        "<code>10316 500 yen</code>\n"
        "<code>10316 €420</code>\n\n"

        "📦 Collection:\n"
        "<code>/add 10316</code>\n"
        "<code>/collection</code>\n"
        "<code>/remove 10316</code>\n\n"

        "⭐ Wishlist:\n"
        "<code>/want 10316</code>\n"
        "<code>/wishlist</code>\n"
        "<code>/unwant 10316</code>\n\n"

        "📊 Στατιστικά:\n"
        "<code>/stats</code>\n\n"

        "🔍 Αναζήτηση:\n"
        "<code>/search castle</code>\n"
        "<code>/search batman</code>\n"
        "<code>/search train</code>\n"
        "<code>/search star wars</code>"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# NUMERIC SET SEARCH
# =========================================================

async def handle_set_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    parts = text.split()

    if not parts:
        return

    set_number = normalize_set_number(
        parts[0]
    )

    if not set_number:
        return

    set_info = get_set_information(
        set_number
    )

    if not set_info:

        await update.message.reply_text(
            "❌ Δεν βρήκα αυτό το LEGO set."
        )

        return

    # -----------------------------------------------------
    # PRICE COMPARISON
    # -----------------------------------------------------

    if len(parts) > 1:

        price_text = " ".join(parts[1:])

        amount, currency = extract_price(
            price_text
        )

        if amount is not None:

            converted_eur = convert_to_eur(
                amount,
                currency
            )

            if (
                converted_eur is not None
                and set_info["rrp"]
            ):

                discount_percent = (
                    (
                        set_info["rrp"]
                        - converted_eur
                    )
                    / set_info["rrp"]
                ) * 100

                rating = price_rating(
                    discount_percent
                )

                await send_set_information(
                    update.message,
                    set_info
                )

                comparison_text = (
                    f"💵 Τιμή που έδωσες: "
                    f"<b>{amount:.2f} {currency}</b>\n"

                    f"💶 Σε EUR: "
                    f"<b>€{converted_eur:.2f}</b>\n"

                    f"📊 Διαφορά από RRP: "
                    f"<b>{discount_percent:+.1f}%</b>\n"

                    f"{rating}"
                )

                await update.message.reply_text(
                    comparison_text,
                    parse_mode="HTML"
                )

                return

    await send_set_information(
        update.message,
        set_info
    )


# =========================================================
# /ADD
# =========================================================

async def add_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Χρήση: /add 10316"
        )

        return

    set_number = normalize_set_number(
        context.args[0]
    )

    if not set_number:

        await update.message.reply_text(
            "❌ Δώσε έναν σωστό αριθμό LEGO set."
        )

        return

    set_info = get_set_information(
        set_number
    )

    if not set_info:

        await update.message.reply_text(
            "❌ Δεν βρήκα αυτό το LEGO set."
        )

        return

    added = add_to_collection(
        update.effective_user.id,
        set_number
    )

    if added:

        await update.message.reply_text(
            f"✅ Το {set_number} προστέθηκε στη Collection!"
        )

    else:

        await update.message.reply_text(
            f"ℹ️ Το {set_number} υπάρχει ήδη στη Collection."
        )


# =========================================================
# /COLLECTION
# =========================================================

async def collection_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    set_numbers = get_user_collection(
        update.effective_user.id
    )

    if not set_numbers:

        await update.message.reply_text(
            "📦 Η Collection σου είναι άδεια."
        )

        return

    total_pieces = 0
    total_rrp = 0
    valid_sets = 0

    for set_number in set_numbers:

        set_info = get_set_information(
            set_number
        )

        if not set_info:
            continue

        await send_set_information(
            update.message,
            set_info
        )

        valid_sets += 1

        if set_info["pieces"]:
            total_pieces += int(
                set_info["pieces"]
            )

        if set_info["rrp"]:
            total_rrp += float(
                set_info["rrp"]
            )

    summary = (
        f"📦 <b>Collection Summary</b>\n\n"
        f"🧱 Sets: <b>{valid_sets}</b>\n"
        f"🧩 Pieces: <b>{total_pieces}</b>\n"
        f"💰 Total RRP: <b>€{total_rrp:.2f}</b>"
    )

    await update.message.reply_text(
        summary,
        parse_mode="HTML"
    )


# =========================================================
# /REMOVE
# =========================================================

async def remove_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Χρήση: /remove 10316"
        )

        return

    set_number = normalize_set_number(
        context.args[0]
    )

    if not set_number:

        await update.message.reply_text(
            "❌ Δώσε έναν σωστό αριθμό LEGO set."
        )

        return

    removed = remove_from_collection(
        update.effective_user.id,
        set_number
    )

    if removed:

        await update.message.reply_text(
            f"🗑️ Το {set_number} αφαιρέθηκε από τη Collection."
        )

    else:

        await update.message.reply_text(
            f"ℹ️ Το {set_number} δεν υπάρχει στη Collection."
        )


# =========================================================
# /WANT
# =========================================================

async def want_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Χρήση: /want 10316"
        )

        return

    set_number = normalize_set_number(
        context.args[0]
    )

    if not set_number:

        await update.message.reply_text(
            "❌ Δώσε έναν σωστό αριθμό LEGO set."
        )

        return

    set_info = get_set_information(
        set_number
    )

    if not set_info:

        await update.message.reply_text(
            "❌ Δεν βρήκα αυτό το LEGO set."
        )

        return

    added = add_to_wishlist(
        update.effective_user.id,
        set_number
    )

    if added:

        await update.message.reply_text(
            f"⭐ Το {set_number} προστέθηκε στο Wishlist!"
        )

    else:

        await update.message.reply_text(
            f"ℹ️ Το {set_number} υπάρχει ήδη στο Wishlist."
        )


# =========================================================
# /WISHLIST
# =========================================================

async def wishlist_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    set_numbers = get_user_wishlist(
        update.effective_user.id
    )

    if not set_numbers:

        await update.message.reply_text(
            "⭐ Το Wishlist σου είναι άδειο."
        )

        return

    for set_number in set_numbers:

        set_info = get_set_information(
            set_number
        )

        if not set_info:
            continue

        await send_set_information(
            update.message,
            set_info
        )

    await update.message.reply_text(
        f"⭐ Έχεις <b>{len(set_numbers)}</b> sets στο Wishlist.",
        parse_mode="HTML"
    )


# =========================================================
# /UNWANT
# =========================================================

async def unwant_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Χρήση: /unwant 10316"
        )

        return

    set_number = normalize_set_number(
        context.args[0]
    )

    if not set_number:

        await update.message.reply_text(
            "❌ Δώσε έναν σωστό αριθμό LEGO set."
        )

        return

    removed = remove_from_wishlist(
        update.effective_user.id,
        set_number
    )

    if removed:

        await update.message.reply_text(
            f"🗑️ Το {set_number} αφαιρέθηκε από το Wishlist."
        )

    else:

        await update.message.reply_text(
            f"ℹ️ Το {set_number} δεν υπάρχει στο Wishlist."
        )


# =========================================================
# /STATS
# =========================================================

async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    set_numbers = get_user_collection(
        update.effective_user.id
    )

    if not set_numbers:

        await update.message.reply_text(
            "📊 Δεν έχεις sets στη Collection για στατιστικά."
        )

        return

    infos = []

    for set_number in set_numbers:

        set_info = get_set_information(
            set_number
        )

        if set_info:
            infos.append(set_info)

    if not infos:

        await update.message.reply_text(
            "❌ Δεν μπόρεσα να φορτώσω τα sets."
        )

        return

    total_sets = len(infos)

    total_pieces = sum(
        int(info["pieces"] or 0)
        for info in infos
    )

    total_rrp = sum(
        float(info["rrp"] or 0)
        for info in infos
    )

    average_rrp = (
        total_rrp / total_sets
        if total_sets
        else 0
    )

    oldest = min(
        infos,
        key=lambda x: int(x["year"])
    )

    newest = max(
        infos,
        key=lambda x: int(x["year"])
    )

    largest = max(
        infos,
        key=lambda x: int(
            x["pieces"] or 0
        )
    )

    most_expensive = max(
        infos,
        key=lambda x: float(
            x["rrp"] or 0
        )
    )

    active = sum(
        1
        for info in infos
        if info["status"] == "🟢 Σε κυκλοφορία"
    )

    retired = sum(
        1
        for info in infos
        if info["status"] == "🔴 Retired"
    )

    unknown = sum(
        1
        for info in infos
        if info["status"] == "❓ Άγνωστη"
    )

    text = (
        "📊 <b>Collection Statistics</b>\n\n"

        f"🧱 Sets: <b>{total_sets}</b>\n"
        f"🧩 Total pieces: <b>{total_pieces}</b>\n"
        f"💰 Total RRP: <b>€{total_rrp:.2f}</b>\n"
        f"📈 Average RRP: <b>€{average_rrp:.2f}</b>\n\n"

        f"👴 Oldest: <b>{oldest['set_number']}</b> "
        f"({oldest['year']})\n"

        f"🆕 Newest: <b>{newest['set_number']}</b> "
        f"({newest['year']})\n"

        f"🧩 Largest: <b>{largest['set_number']}</b> "
        f"({largest['pieces']} pieces)\n"

        f"💎 Most expensive: "
        f"<b>{most_expensive['set_number']}</b> "
        f"(€{float(most_expensive['rrp'] or 0):.2f})\n\n"

        f"🟢 Active: <b>{active}</b>\n"
        f"🔴 Retired: <b>{retired}</b>\n"
        f"❓ Unknown: <b>{unknown}</b>"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# SEARCH RESULT
# =========================================================

async def send_search_result(
    message,
    result
):

    set_number = result.get(
        "set_num",
        ""
    )

    image_url = result.get(
        "set_img_url"
    )

    if not image_url:

        image_url = (
            "https://cdn.rebrickable.com/media/sets/"
            f"{set_number}-1.jpg"
        )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                set_number,
                callback_data=f"setinfo:{set_number}"
            )
        ]
    ])

    try:

        await message.reply_photo(
            photo=image_url,
            reply_markup=keyboard
        )

    except Exception:

        await message.reply_text(
            f"{set_number}",
            reply_markup=keyboard
        )


# =========================================================
# /SEARCH
# =========================================================

async def search_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Χρήση: /search castle"
        )

        return

    search_text = " ".join(
        context.args
    )

    results = search_rebrickable_sets(
        search_text
    )

    if not results:

        await update.message.reply_text(
            "❌ Δεν βρήκα αποτελέσματα."
        )

        return

    await update.message.reply_text(
        f"🔎 Αποτελέσματα για: "
        f"<b>{search_text}</b>",
        parse_mode="HTML"
    )

    for result in results:

        await send_search_result(
            update.message,
            result
        )


# =========================================================
# CALLBACK BUTTONS
# =========================================================

async def button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    data = query.data

    # -----------------------------------------------------
    # SHOW SET INFORMATION
    # -----------------------------------------------------

    if data.startswith("setinfo:"):

        await query.answer()

        set_number = data.split(
            ":",
            1
        )[1]

        set_info = get_set_information(
            set_number
        )

        if not set_info:

            await query.message.reply_text(
                "❌ Δεν μπόρεσα να βρω το set."
            )

            return

        await send_set_information(
            query.message,
            set_info
        )

        return

    # -----------------------------------------------------
    # ADD TO COLLECTION
    # -----------------------------------------------------

    if data.startswith("addcollection:"):

        set_number = data.split(
            ":",
            1
        )[1]

        added = add_to_collection(
            update.effective_user.id,
            set_number
        )

        if added:

            await query.answer(
                f"✅ {set_number} προστέθηκε στη Collection!",
                show_alert=True
            )

        else:

            await query.answer(
                f"ℹ️ {set_number} υπάρχει ήδη στη Collection.",
                show_alert=True
            )

        return

    # -----------------------------------------------------
    # ADD TO WISHLIST
    # -----------------------------------------------------

    if data.startswith("addwishlist:"):

        set_number = data.split(
            ":",
            1
        )[1]

        added = add_to_wishlist(
            update.effective_user.id,
            set_number
        )

        if added:

            await query.answer(
                f"⭐ {set_number} προστέθηκε στο Wishlist!",
                show_alert=True
            )

        else:

            await query.answer(
                f"ℹ️ {set_number} υπάρχει ήδη στο Wishlist.",
                show_alert=True
            )

        return


# =========================================================
# MAIN
# =========================================================

def main():

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "Missing TELEGRAM_TOKEN environment variable."
        )

    if not REBRICKABLE_API_KEY:
        raise RuntimeError(
            "Missing REBRICKABLE_API_KEY environment variable."
        )

    if not BRICKSET_API_KEY:
        raise RuntimeError(
            "Missing BRICKSET_API_KEY environment variable."
        )

    application = (
        Application
        .builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "add",
            add_command
        )
    )

    application.add_handler(
        CommandHandler(
            "collection",
            collection_command
        )
    )

    application.add_handler(
        CommandHandler(
            "remove",
            remove_command
        )
    )

    application.add_handler(
        CommandHandler(
            "want",
            want_command
        )
    )

    application.add_handler(
        CommandHandler(
            "wishlist",
            wishlist_command
        )
    )

    application.add_handler(
        CommandHandler(
            "unwant",
            unwant_command
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_command
        )
    )

    application.add_handler(
        CommandHandler(
            "search",
            search_command
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_callback
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_set_message
        )
    )

    print("🤖 LEGO Bot is running...")

    application.run_polling()


if __name__ == "__main__":
    main()
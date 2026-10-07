import json
import os
import re
import unicodedata
from datetime import datetime
from urllib.parse import quote_plus

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
REBRICKABLE_API_KEY = os.getenv("REBRICKABLE_API_KEY")
BRICKSET_API_KEY = os.getenv("BRICKSET_API_KEY")

# Το Telegram ID του διαχειριστή έρχεται από το Render
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# Κωδικός πρόσκλησης
INVITE_CODE = os.getenv("INVITE_CODE", "LEGO2026")


# =========================================================
# FILES
# =========================================================

COLLECTION_FILE = "collection.json"
WISHLIST_FILE = "wishlist.json"
ACCESS_FILE = "access.json"


# =========================================================
# BASIC HELPERS
# =========================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_text(text):
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(
        c for c in text
        if unicodedata.category(c) != "Mn"
    )
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# =========================================================
# ACCESS SYSTEM
# =========================================================

def get_access_data():
    return load_json(
        ACCESS_FILE,
        {
            "approved": [],
            "pending": []
        }
    )


def save_access_data(data):
    save_json(ACCESS_FILE, data)


def is_admin(user_id):
    return user_id == ADMIN_USER_ID


def has_access(user_id):
    if is_admin(user_id):
        return True

    data = get_access_data()

    return str(user_id) in [
        str(x) for x in data.get("approved", [])
    ]


def is_pending(user_id):
    data = get_access_data()

    return str(user_id) in [
        str(x) for x in data.get("pending", [])
    ]


async def access_denied(update):
    if update.effective_message:
        await update.effective_message.reply_text(
            "🔒 Δεν έχεις πρόσβαση στο bot.\n\n"
            "Χρειάζεσαι invitation link από τον διαχειριστή."
        )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    # ADMIN
    if is_admin(user.id):
        await update.message.reply_text(
            "👑 Καλώς ήρθες Admin!\n\n"
            "Το bot είναι έτοιμο."
        )
        return

    # Already approved
    if has_access(user.id):
        await update.message.reply_text(
            "🧱 Καλώς ήρθες ξανά!\n\n"
            "Μπορείς να γράψεις έναν αριθμό LEGO set, π.χ.:\n"
            "10316\n\n"
            "Ή χρησιμοποίησε:\n"
            "/collection\n"
            "/wishlist\n"
            "/stats\n"
            "/search castle"
        )
        return

    # Invitation code
    code = ""

    if context.args:
        code = context.args[0]

    if code != INVITE_CODE:
        await update.message.reply_text(
            "🔒 Αυτό το bot λειτουργεί με πρόσκληση.\n\n"
            "Χρειάζεσαι το προσωπικό invitation link."
        )
        return

    # Already pending
    if is_pending(user.id):
        await update.message.reply_text(
            "⏳ Το αίτημά σου έχει ήδη σταλεί.\n\n"
            "Περίμενε την έγκριση του διαχειριστή."
        )
        return

    # Add pending request
    data = get_access_data()

    data.setdefault("pending", [])

    if str(user.id) not in [
        str(x) for x in data["pending"]
    ]:
        data["pending"].append(str(user.id))

    save_access_data(data)

    username = (
        f"@{user.username}"
        if user.username
        else "χωρίς username"
    )

    # Send request to admin
    if ADMIN_USER_ID != 0:

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"approve:{user.id}"
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"reject:{user.id}"
                )
            ]
        ])

        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=(
                "👤 Νέο αίτημα πρόσβασης!\n\n"
                f"Όνομα: {user.full_name}\n"
                f"Username: {username}\n"
                f"Telegram ID: {user.id}"
            ),
            reply_markup=keyboard
        )

    await update.message.reply_text(
        "📨 Το αίτημά σου στάλθηκε στον διαχειριστή.\n\n"
        "⏳ Περίμενε μέχρι να εγκριθεί η πρόσβασή σου."
    )


# =========================================================
# APPROVE / REJECT
# =========================================================

async def access_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    admin = query.from_user

    if not is_admin(admin.id):
        await query.answer(
            "Δεν έχεις δικαίωμα.",
            show_alert=True
        )
        return

    await query.answer()

    data = get_access_data()

    action, user_id = query.data.split(":", 1)

    user_id = str(user_id)

    data.setdefault("approved", [])
    data.setdefault("pending", [])

    if action == "approve":

        if user_id not in [
            str(x) for x in data["approved"]
        ]:
            data["approved"].append(user_id)

        data["pending"] = [
            str(x)
            for x in data["pending"]
            if str(x) != user_id
        ]

        save_access_data(data)

        await query.edit_message_text(
            f"✅ Ο χρήστης {user_id} εγκρίθηκε."
        )

        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=(
                    "🎉 Η πρόσβασή σου εγκρίθηκε!\n\n"
                    "Καλώς ήρθες στο LEGO bot! 🧱"
                )
            )
        except Exception:
            pass

    elif action == "reject":

        data["pending"] = [
            str(x)
            for x in data["pending"]
            if str(x) != user_id
        ]

        save_access_data(data)

        await query.edit_message_text(
            f"❌ Ο χρήστης {user_id} απορρίφθηκε."
        )

        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=(
                    "❌ Το αίτημά σου για πρόσβαση "
                    "δεν εγκρίθηκε."
                )
            )
        except Exception:
            pass


# =========================================================
# MY ID
# =========================================================

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        f"🆔 Το Telegram ID σου είναι:\n\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# REBRICKABLE
# =========================================================

def get_rebrickable_set(set_number):

    url = (
        f"https://rebrickable.com/api/v3/lego/sets/"
        f"{set_number}-1/"
    )

    headers = {
        "Authorization": f"key {REBRICKABLE_API_KEY}"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    if response.status_code != 200:
        return None

    return response.json()


# =========================================================
# BRICKSET
# =========================================================

def get_brickset_set(set_number):

    url = "https://brickset.com/api/v3.asmx/getSets"

    params = {
        "setNumber": f"{set_number}-1",
        "pageSize": 1,
        "pageNumber": 1
    }

    payload = {
        "apiKey": BRICKSET_API_KEY,
        "userHash": "",
        "params": json.dumps(params)
    }

    response = requests.post(
        url,
        data=payload,
        timeout=20
    )

    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except Exception:
        return None

    sets = data.get("sets", [])

    if not sets:
        return None

    return sets[0]


# =========================================================
# RRP
# =========================================================

def get_rrp(brickset):

    lego_com = brickset.get("LEGOCom", {})

    if isinstance(lego_com, dict):

        for country in ["DE", "UK", "US"]:

            data = lego_com.get(country)

            if isinstance(data, dict):

                price = data.get("retailPrice")

                if price:
                    return price

    for field in [
        "retailPrice",
        "RRP",
        "rrp",
        "price"
    ]:

        price = brickset.get(field)

        if price:
            return price

    return None


# =========================================================
# STATUS
# =========================================================

def get_status(brickset):

    released = brickset.get("released")
    exit_date = brickset.get("exitDate")

    if released is False:
        return "🔵 Δεν έχει κυκλοφορήσει ακόμα"

    if exit_date:
        try:
            exit_dt = datetime.strptime(
                exit_date[:10],
                "%Y-%m-%d"
            )

            if exit_dt < datetime.now():
                return "🔴 Retired"

        except Exception:
            pass

    if released is True:
        return "🟢 Σε κυκλοφορία"

    return "❓ Άγνωστη"


# =========================================================
# CURRENCY
# =========================================================

CURRENCY_SYMBOLS = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "¥": "JPY",
    "₩": "KRW",
    "CHF": "CHF",
    "C$": "CAD",
    "A$": "AUD"
}


CURRENCY_NAMES = {
    "euro": "EUR",
    "euros": "EUR",
    "ευρω": "EUR",

    "dollar": "USD",
    "dollars": "USD",
    "usd": "USD",

    "pound": "GBP",
    "pounds": "GBP",
    "gbp": "GBP",

    "yen": "JPY",
    "jpy": "JPY",

    "won": "KRW",
    "krw": "KRW",

    "franc": "CHF",
    "chf": "CHF"
}


def find_currency(text):

    normalized = normalize_text(text)

    for symbol, code in CURRENCY_SYMBOLS.items():

        if symbol in text:
            return code

    for name, code in CURRENCY_NAMES.items():

        if re.search(
            rf"\b{re.escape(name)}\b",
            normalized
        ):
            return code

    match = re.search(
        r"\b([A-Za-z]{3})\b",
        text
    )

    if match:
        return match.group(1).upper()

    return "EUR"


def extract_price(text):

    currency = find_currency(text)

    cleaned = text

    for symbol in CURRENCY_SYMBOLS:
        cleaned = cleaned.replace(symbol, " ")

    for name in CURRENCY_NAMES:
        cleaned = re.sub(
            rf"\b{re.escape(name)}\b",
            " ",
            cleaned,
            flags=re.IGNORECASE
        )

    cleaned = re.sub(
        r"\b[A-Za-z]{3}\b",
        " ",
        cleaned
    )

    match = re.search(
        r"(\d+(?:[.,]\d+)?)",
        cleaned
    )

    if not match:
        return None, currency

    try:
        amount = float(
            match.group(1).replace(",", ".")
        )

        return amount, currency

    except Exception:
        return None, currency


def convert_to_eur(amount, currency):

    if currency == "EUR":
        return amount

    try:

        url = (
            f"https://api.frankfurter.dev/v2/"
            f"rate/{currency}/EUR"
        )

        response = requests.get(
            url,
            timeout=15
        )

        if response.status_code != 200:
            return None

        data = response.json()

        rate = data.get("rate")

        if not rate:
            return None

        return amount * float(rate)

    except Exception:
        return None


# =========================================================
# PRICE RATING
# =========================================================

def price_rating(price, rrp):

    if not rrp or rrp <= 0:
        return ""

    difference = ((rrp - price) / rrp) * 100

    if difference >= 30:
        return "🟢 Εξαιρετική τιμή!"

    if difference >= 15:
        return "🟢 Πολύ καλή τιμή!"

    if difference >= 5:
        return "🟡 Καλή τιμή"

    if difference >= 0:
        return "🟠 Μικρή έκπτωση"

    if difference > -10:
        return "🔴 Πάνω από το RRP"

    return "🔴 Αρκετά πάνω από το RRP"


# =========================================================
# COLLECTION
# =========================================================

def get_collection():
    return load_json(COLLECTION_FILE, {})


def save_collection(data):
    save_json(COLLECTION_FILE, data)


def add_to_collection(user_id, set_number):

    data = get_collection()

    user_key = str(user_id)

    data.setdefault(user_key, [])

    if set_number not in data[user_key]:
        data[user_key].append(set_number)

    save_collection(data)


def remove_from_collection(user_id, set_number):

    data = get_collection()

    user_key = str(user_id)

    if user_key in data:
        data[user_key] = [
            x for x in data[user_key]
            if x != set_number
        ]

    save_collection(data)


# =========================================================
# WISHLIST
# =========================================================

def get_wishlist():
    return load_json(WISHLIST_FILE, {})


def save_wishlist(data):
    save_json(WISHLIST_FILE, data)


def add_to_wishlist(user_id, set_number):

    data = get_wishlist()

    user_key = str(user_id)

    data.setdefault(user_key, [])

    if set_number not in data[user_key]:
        data[user_key].append(set_number)

    save_wishlist(data)


def remove_from_wishlist(user_id, set_number):

    data = get_wishlist()

    user_key = str(user_id)

    if user_key in data:
        data[user_key] = [
            x for x in data[user_key]
            if x != set_number
        ]

    save_wishlist(data)


# =========================================================
# SET INFORMATION
# =========================================================

async def send_set_information(
    message,
    set_number,
    entered_price=None,
    entered_currency="EUR"
):

    rb = get_rebrickable_set(set_number)

    if not rb:
        await message.reply_text(
            "❌ Δεν βρέθηκε το LEGO set."
        )
        return

    brickset = get_brickset_set(set_number)

    name = rb.get("name", "Άγνωστο")
    year = rb.get("year", "?")
    pieces = rb.get("num_parts", "?")
    image_url = rb.get("set_img_url")

    text = (
        f"🧱 <b>{name}</b>\n\n"
        f"🔢 Set: <b>{set_number}</b>\n"
        f"📅 Έτος: {year}\n"
        f"🧩 Κομμάτια: {pieces}\n"
    )

    rrp = None

    if brickset:

        status = get_status(brickset)

        text += f"📌 Κατάσταση: {status}\n"

        if year and str(year).isdigit():

            age = datetime.now().year - int(year)

            text += f"🎂 Ηλικία: {age} χρόνια\n"

        launch_date = brickset.get("launchDate")
        exit_date = brickset.get("exitDate")

        if launch_date:
            text += f"🚀 Κυκλοφορία: {launch_date[:10]}\n"

        if exit_date:
            text += f"🏁 Απόσυρση: {exit_date[:10]}\n"

        rrp = get_rrp(brickset)

        if rrp:

            try:

                rrp = float(rrp)

                text += f"💶 RRP: €{rrp:.2f}\n"

                if pieces:

                    try:

                        price_per_piece = (
                            rrp / float(pieces)
                        )

                        text += (
                            f"📐 RRP/κομμάτι: "
                            f"€{price_per_piece:.2f}\n"
                        )

                    except Exception:
                        pass

            except Exception:
                rrp = None

    # Price entered by user
    if entered_price is not None:

        eur_price = convert_to_eur(
            entered_price,
            entered_currency
        )

        if eur_price is not None:

            text += (
                f"\n💰 Τιμή που έδωσες: "
                f"{entered_price:.2f} {entered_currency}\n"
                f"💶 Σε EUR: €{eur_price:.2f}\n"
            )

            if rrp:

                difference = (
                    (rrp - eur_price)
                    / rrp
                ) * 100

                sign = "+" if difference < 0 else ""

                text += (
                    f"📊 Διαφορά από RRP: "
                    f"{sign}{difference:.1f}%\n"
                    f"{price_rating(eur_price, rrp)}\n"
                )

        else:

            text += (
                f"\n💰 Τιμή: "
                f"{entered_price:.2f} "
                f"{entered_currency}\n"
                "⚠️ Δεν μπόρεσα να κάνω "
                "τη μετατροπή σε EUR."
            )

    # Buttons
    keyboard = InlineKeyboardMarkup([
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
                    "https://www.lego.com/en-gb/search?q="
                    + quote_plus(set_number)
                )
            ),
            InlineKeyboardButton(
                "🛍️ eBay",
                url=(
                    "https://www.ebay.com/sch/i.html?_nkw="
                    + quote_plus("LEGO " + set_number)
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
                    "https://www.bricklink.com/catalogPG.asp?"
                    f"S={set_number}-1&ColorID=0"
                )
            )
        ]
    ])

    if image_url:

        await message.reply_photo(
            photo=image_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    else:

        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )


# =========================================================
# SEARCH
# =========================================================

async def search_sets(message, keyword):

    url = (
        "https://rebrickable.com/api/v3/lego/sets/"
    )

    headers = {
        "Authorization": f"key {REBRICKABLE_API_KEY}"
    }

    params = {
        "search": keyword,
        "page_size": 10,
        "page": 1,
        "ordering": "-year"
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=20
    )

    if response.status_code != 200:

        await message.reply_text(
            "❌ Πρόβλημα στην αναζήτηση."
        )
        return

    data = response.json()

    results = data.get("results", [])

    if not results:

        await message.reply_text(
            "❌ Δεν βρέθηκαν sets."
        )
        return

    for result in results:

        set_number = result.get(
            "set_num",
            ""
        ).replace("-1", "")

        image_url = result.get("set_img_url")

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    set_number,
                    callback_data=f"setinfo:{set_number}"
                )
            ]
        ])

        if image_url:

            await message.reply_photo(
                photo=image_url,
                reply_markup=keyboard
            )

        else:

            await message.reply_text(
                "🧱",
                reply_markup=keyboard
            )


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not has_access(user.id):
        await access_denied(update)
        return

    text = update.message.text.strip()

    match = re.match(
        r"^(\d{4,6})(?:\s+(.+))?$",
        text
    )

    if not match:
        return

    set_number = match.group(1)
    price_text = match.group(2)

    entered_price = None
    entered_currency = "EUR"

    if price_text:
        entered_price, entered_currency = (
            extract_price(price_text)
        )

    await send_set_information(
        update.message,
        set_number,
        entered_price,
        entered_currency
    )


# =========================================================
# COLLECTION COMMAND
# =========================================================

async def collection_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not has_access(user.id):
        await access_denied(update)
        return

    data = get_collection()

    sets = data.get(
        str(user.id),
        []
    )

    if not sets:

        await update.message.reply_text(
            "📦 Η Collection σου είναι άδεια."
        )
        return

    await update.message.reply_text(
        f"📦 Η Collection σου έχει "
        f"{len(sets)} sets."
    )

    for set_number in sets:

        await send_set_information(
            update.message,
            set_number
        )


# =========================================================
# WISHLIST COMMAND
# =========================================================

async def wishlist_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not has_access(user.id):
        await access_denied(update)
        return

    data = get_wishlist()

    sets = data.get(
        str(user.id),
        []
    )

    if not sets:

        await update.message.reply_text(
            "⭐ Η Wishlist σου είναι άδεια."
        )
        return

    await update.message.reply_text(
        f"⭐ Η Wishlist σου έχει "
        f"{len(sets)} sets."
    )

    for set_number in sets:

        await send_set_information(
            update.message,
            set_number
        )


# =========================================================
# ADD / REMOVE COLLECTION
# =========================================================

async def add_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    if not context.args:

        await update.message.reply_text(
            "Χρήση:\n/add 10316"
        )
        return

    set_number = context.args[0]

    add_to_collection(
        update.effective_user.id,
        set_number
    )

    await update.message.reply_text(
        f"✅ Το {set_number} προστέθηκε "
        "στην Collection."
    )


async def remove_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    if not context.args:

        await update.message.reply_text(
            "Χρήση:\n/remove 10316"
        )
        return

    set_number = context.args[0]

    remove_from_collection(
        update.effective_user.id,
        set_number
    )

    await update.message.reply_text(
        f"🗑️ Το {set_number} αφαιρέθηκε "
        "από την Collection."
    )


# =========================================================
# ADD / REMOVE WISHLIST
# =========================================================

async def want_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    if not context.args:

        await update.message.reply_text(
            "Χρήση:\n/want 10316"
        )
        return

    set_number = context.args[0]

    add_to_wishlist(
        update.effective_user.id,
        set_number
    )

    await update.message.reply_text(
        f"⭐ Το {set_number} προστέθηκε "
        "στη Wishlist."
    )


async def unwant_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    if not context.args:

        await update.message.reply_text(
            "Χρήση:\n/unwant 10316"
        )
        return

    set_number = context.args[0]

    remove_from_wishlist(
        update.effective_user.id,
        set_number
    )

    await update.message.reply_text(
        f"🗑️ Το {set_number} αφαιρέθηκε "
        "από τη Wishlist."
    )


# =========================================================
# STATS
# =========================================================

async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not has_access(user.id):
        await access_denied(update)
        return

    collection = get_collection()

    sets = collection.get(
        str(user.id),
        []
    )

    if not sets:

        await update.message.reply_text(
            "📊 Δεν έχεις ακόμα sets "
            "στη Collection."
        )
        return

    total_pieces = 0
    prices = []

    oldest = None
    newest = None
    largest = None
    expensive = None

    active = 0
    retired = 0
    unknown = 0

    for set_number in sets:

        rb = get_rebrickable_set(set_number)

        if not rb:
            continue

        year = rb.get("year")
        pieces = rb.get("num_parts", 0)

        try:
            total_pieces += int(pieces)
        except Exception:
            pass

        if year:

            if oldest is None or year < oldest["year"]:
                oldest = {
                    "number": set_number,
                    "year": year
                }

            if newest is None or year > newest["year"]:
                newest = {
                    "number": set_number,
                    "year": year
                }

        try:

            pieces_number = int(pieces)

            if (
                largest is None
                or pieces_number > largest["pieces"]
            ):
                largest = {
                    "number": set_number,
                    "pieces": pieces_number
                }

        except Exception:
            pass

        brickset = get_brickset_set(set_number)

        if brickset:

            status = get_status(brickset)

            if "Σε κυκλοφορία" in status:
                active += 1

            elif "Retired" in status:
                retired += 1

            else:
                unknown += 1

            rrp = get_rrp(brickset)

            if rrp:

                try:

                    rrp = float(rrp)

                    prices.append(rrp)

                    if (
                        expensive is None
                        or rrp > expensive["price"]
                    ):
                        expensive = {
                            "number": set_number,
                            "price": rrp
                        }

                except Exception:
                    pass

    text = (
        "📊 <b>Collection Stats</b>\n\n"
        f"🧱 Sets: <b>{len(sets)}</b>\n"
        f"🧩 Κομμάτια: <b>{total_pieces:,}</b>\n"
    )

    if prices:

        total_rrp = sum(prices)
        average_rrp = total_rrp / len(prices)

        text += (
            f"💶 Συνολικό RRP: <b>€{total_rrp:.2f}</b>\n"
            f"📈 Μέσο RRP: <b>€{average_rrp:.2f}</b>\n"
        )

    if oldest:

        text += (
            f"\n👴 Παλαιότερο: "
            f"<b>{oldest['number']}</b> "
            f"({oldest['year']})\n"
        )

    if newest:

        text += (
            f"🆕 Νεότερο: "
            f"<b>{newest['number']}</b> "
            f"({newest['year']})\n"
        )

    if largest:

        text += (
            f"🧩 Μεγαλύτερο: "
            f"<b>{largest['number']}</b> "
            f"({largest['pieces']:,} pieces)\n"
        )

    if expensive:

        text += (
            f"💰 Ακριβότερο: "
            f"<b>{expensive['number']}</b> "
            f"(€{expensive['price']:.2f})\n"
        )

    text += (
        f"\n🟢 Active: {active}\n"
        f"🔴 Retired: {retired}\n"
        f"❓ Unknown: {unknown}"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# CALLBACKS
# =========================================================

async def button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    user = query.from_user

    # Approve / Reject
    if (
        query.data.startswith("approve:")
        or query.data.startswith("reject:")
    ):

        await access_callback(
            update,
            context
        )

        return

    # Other buttons require access
    if not has_access(user.id):

        await query.answer(
            "🔒 Δεν έχεις πρόσβαση.",
            show_alert=True
        )

        return

    if query.data.startswith("setinfo:"):

        await query.answer()

        set_number = query.data.split(":", 1)[1]

        await send_set_information(
            query.message,
            set_number
        )

        return

    if query.data.startswith("addcollection:"):

        set_number = query.data.split(":", 1)[1]

        add_to_collection(
            user.id,
            set_number
        )

        await query.answer(
            "✅ Προστέθηκε στην Collection!",
            show_alert=True
        )

        return

    if query.data.startswith("addwishlist:"):

        set_number = query.data.split(":", 1)[1]

        add_to_wishlist(
            user.id,
            set_number
        )

        await query.answer(
            "⭐ Προστέθηκε στη Wishlist!",
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

    if not ADMIN_USER_ID:
        raise RuntimeError(
            "Missing ADMIN_USER_ID environment variable."
        )

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("id", my_id)
    )

    app.add_handler(
        CommandHandler("collection", collection_command)
    )

    app.add_handler(
        CommandHandler("wishlist", wishlist_command)
    )

    app.add_handler(
        CommandHandler("stats", stats_command)
    )

    app.add_handler(
        CommandHandler("add", add_command)
    )

    app.add_handler(
        CommandHandler("remove", remove_command)
    )

    app.add_handler(
        CommandHandler("want", want_command)
    )

    app.add_handler(
        CommandHandler("unwant", unwant_command)
    )

    app.add_handler(
        CommandHandler("search", search_sets)
    )

    app.add_handler(
        CallbackQueryHandler(button_callback)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("LEGO bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()

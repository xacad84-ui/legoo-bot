import os
import json
import re
import unicodedata
from datetime import datetime

import requests
import psycopg
from psycopg.rows import dict_row

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)


# =========================================================
# SETTINGS
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
REBRICKABLE_API_KEY = os.getenv("REBRICKABLE_API_KEY")
BRICKSET_API_KEY = os.getenv("BRICKSET_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
INVITE_CODE = os.getenv("INVITE_CODE", "LEGO2026")


# =========================================================
# DATABASE
# =========================================================

def db_connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing.")

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )


def init_db():
    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS access_users (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    approved BOOLEAN NOT NULL DEFAULT FALSE,
                    pending BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS collections (
                    user_id BIGINT NOT NULL,
                    set_number TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, set_number)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS wishlist (
                    user_id BIGINT NOT NULL,
                    set_number TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, set_number)
                )
            """)

        conn.commit()


# =========================================================
# ACCESS / ADMIN
# =========================================================

def is_admin(user_id):
    return user_id == ADMIN_USER_ID


def get_access_user(user_id):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM access_users WHERE user_id = %s",
                (user_id,),
            )

            return cur.fetchone()


def has_access(user_id):
    if is_admin(user_id):
        return True

    user = get_access_user(user_id)

    return bool(user and user["approved"])


def is_pending(user_id):
    user = get_access_user(user_id)

    return bool(user and user["pending"])


def create_access_request(user):
    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO access_users
                    (user_id, first_name, username, approved, pending)
                VALUES
                    (%s, %s, %s, FALSE, TRUE)

                ON CONFLICT (user_id)
                DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    username = EXCLUDED.username,
                    pending = TRUE
                """,
                (
                    user.id,
                    user.first_name or "",
                    user.username or "",
                ),
            )

        conn.commit()


def approve_user(user_id):
    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO access_users
                    (user_id, approved, pending)
                VALUES
                    (%s, TRUE, FALSE)

                ON CONFLICT (user_id)
                DO UPDATE SET
                    approved = TRUE,
                    pending = FALSE
                """,
                (user_id,),
            )

        conn.commit()


def reject_user(user_id):
    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                UPDATE access_users
                SET pending = FALSE,
                    approved = FALSE
                WHERE user_id = %s
                """,
                (user_id,),
            )

        conn.commit()


# =========================================================
# WELCOME / HELP MENU
# =========================================================

def welcome_message():
    return (
        "🎉 <b>Η πρόσβασή σου εγκρίθηκε!</b>\n\n"
        "🧱 Καλώς ήρθες στο LEGO Bot!\n\n"

        "📋 <b>Τι μπορείς να κάνεις:</b>\n\n"

        "🔢 <b>Αναζήτηση set</b>\n"
        "Γράψε απλά τον αριθμό του LEGO set.\n"
        "Παράδειγμα:\n"
        "<code>10316</code>\n\n"

        "💰 <b>Έλεγχος τιμής</b>\n"
        "Μπορείς να γράψεις το set μαζί με την τιμή που βρήκες.\n\n"
        "Παραδείγματα:\n"
        "<code>10316 420</code>\n"
        "<code>10316 500 yen</code>\n"
        "<code>10316 €420</code>\n"
        "<code>10316 $450</code>\n\n"

        "Το bot θα μετατρέψει την τιμή σε EUR, "
        "θα τη συγκρίνει με το RRP και θα σου πει αν είναι "
        "καλή ή κακή προσφορά.\n\n"

        "🧱 <b>Collection</b>\n"
        "<code>/add 10316</code> — προσθήκη set\n"
        "<code>/remove 10316</code> — αφαίρεση set\n"
        "<code>/collection</code> — εμφάνιση Collection\n"
        "<code>/stats</code> — στατιστικά Collection\n\n"

        "⭐ <b>Wishlist</b>\n"
        "<code>/want 10316</code> — προσθήκη στο Wishlist\n"
        "<code>/unwant 10316</code> — αφαίρεση από Wishlist\n"
        "<code>/wishlist</code> — εμφάνιση Wishlist\n\n"

        "🔎 <b>Αναζήτηση με λέξη</b>\n"
        "<code>/search castle</code>\n"
        "<code>/search batman</code>\n"
        "<code>/search star wars</code>\n\n"

        "🆔 <b>Το Telegram ID σου</b>\n"
        "<code>/id</code>\n\n"

        "🛒 Μέσα σε κάθε set θα βρίσκεις επίσης "
        "συνδέσμους για LEGO, eBay και BrickLink.\n\n"

        "🧱 Καλή συλλογή!"
    )


def admin_welcome_message():
    return (
        "👑 <b>Admin — LEGO Bot</b>\n\n"
        "Το bot είναι έτοιμο και έχεις πλήρη πρόσβαση.\n\n"
        + welcome_message()
    )


async def access_denied(update):
    if update.message:
        await update.message.reply_text(
            "🔒 Δεν έχεις πρόσβαση στο bot.\n\n"
            "Χρειάζεσαι invitation link και έγκριση από τον διαχειριστή."
        )


# =========================================================
# START
# =========================================================

async def start(update, context):
    user = update.effective_user
    user_id = user.id

    # ADMIN
    if is_admin(user_id):
        await update.message.reply_text(
            admin_welcome_message(),
            parse_mode="HTML",
        )
        return

    # ALREADY APPROVED
    if has_access(user_id):
        await update.message.reply_text(
            welcome_message(),
            parse_mode="HTML",
        )
        return

    # NO INVITE LINK
    args = context.args

    if not args:
        await update.message.reply_text(
            "🔒 Για να αποκτήσεις πρόσβαση χρειάζεσαι invitation link."
        )
        return

    # CHECK INVITE CODE
    provided_code = args[0]

    if provided_code != INVITE_CODE:
        await update.message.reply_text(
            "❌ Μη έγκυρος κωδικός πρόσκλησης."
        )
        return

    # ALREADY WAITING
    if is_pending(user_id):
        await update.message.reply_text(
            "⏳ Το αίτημά σου έχει ήδη σταλεί στον διαχειριστή.\n\n"
            "Περίμενε την έγκρισή του."
        )
        return

    # CREATE REQUEST
    create_access_request(user)

    username_text = (
        f"@{user.username}"
        if user.username
        else "χωρίς username"
    )

    admin_message = (
        "👤 <b>Νέο αίτημα πρόσβασης!</b>\n\n"
        f"Όνομα: {user.first_name or 'Άγνωστο'}\n"
        f"Username: {username_text}\n"
        f"ID: {user.id}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"approve:{user.id}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"reject:{user.id}"
            ),
        ]
    ])

    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=admin_message,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception:
        pass

    await update.message.reply_text(
        "📨 Το αίτημά σου στάλθηκε στον διαχειριστή.\n\n"
        "Περίμενε να εγκριθεί η πρόσβασή σου."
    )


# =========================================================
# APPROVE / REJECT
# =========================================================

async def access_callback(update, context):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer(
            "Δεν έχεις δικαίωμα να κάνεις αυτή την ενέργεια.",
            show_alert=True,
        )
        return

    await query.answer()

    data = query.data

    # APPROVE
    if data.startswith("approve:"):

        user_id = int(data.split(":")[1])

        approve_user(user_id)

        await query.edit_message_text(
            query.message.text
            + "\n\n"
            + "✅ <b>ΕΓΚΡΙΘΗΚΕ</b>\n\n"
            + "📋 <b>Commands που μπορείς να χρησιμοποιήσεις:</b>\n\n"
            + "🔢 Γράψε <code>10316</code> για πληροφορίες set\n"
            + "💰 Γράψε <code>10316 420</code> για έλεγχο τιμής\n"
            + "💰 <code>10316 500 yen</code>\n"
            + "💰 <code>10316 €420</code>\n"
            + "💰 <code>10316 $450</code>\n\n"
            + "🧱 <code>/add 10316</code> — Collection\n"
            + "🗑️ <code>/remove 10316</code> — αφαίρεση\n"
            + "📦 <code>/collection</code> — Collection\n"
            + "📊 <code>/stats</code> — στατιστικά\n\n"
            + "⭐ <code>/want 10316</code> — Wishlist\n"
            + "🗑️ <code>/unwant 10316</code> — αφαίρεση\n"
            + "⭐ <code>/wishlist</code> — Wishlist\n\n"
            + "🔎 <code>/search castle</code>\n"
            + "🔎 <code>/search batman</code>\n"
            + "🔎 <code>/search star wars</code>\n\n"
            + "🆔 <code>/id</code> — Telegram ID",
            parse_mode="HTML",
        )

        # SEND WELCOME TO APPROVED USER
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=welcome_message(),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # REJECT
    elif data.startswith("reject:"):

        user_id = int(data.split(":")[1])

        reject_user(user_id)

        await query.edit_message_text(
            query.message.text
            + "\n\n"
            + "❌ <b>ΑΠΟΡΡΙΦΘΗΚΕ</b>",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ <b>Το αίτημά σου για πρόσβαση απορρίφθηκε.</b>\n\n"
                    "Δεν μπορείς να χρησιμοποιήσεις το LEGO Bot "
                    "χωρίς έγκριση από τον διαχειριστή."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


# =========================================================
# SET NUMBER
# =========================================================

def normalize_set_number(text):
    return text.strip().upper().replace("-1", "")


def normalize_text(text):
    text = text.lower()

    text = "".join(
        c
        for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )

    text = text.replace("-", " ")

    return " ".join(text.split())


# =========================================================
# REBRICKABLE
# =========================================================

def get_set_info(set_number):

    url = f"https://rebrickable.com/api/v3/lego/sets/{set_number}-1/"

    headers = {
        "Authorization": f"key {REBRICKABLE_API_KEY}"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=15,
        )

        if response.status_code != 200:
            return None

        return response.json()

    except Exception:
        return None


# =========================================================
# BRICKSET
# =========================================================

def get_brickset_info(set_number):

    url = "https://brickset.com/api/v3.asmx/getSets"

    params = {
        "setNumber": f"{set_number}-1",
        "pageSize": 1,
        "pageNumber": 1,
    }

    payload = {
        "apiKey": BRICKSET_API_KEY,
        "userHash": "",
        "params": json.dumps(params),
    }

    try:
        response = requests.post(
            url,
            data=payload,
            timeout=15,
        )

        if response.status_code != 200:
            return None

        data = response.json()

        if data.get("status") != "success":
            return None

        sets = data.get("sets", [])

        if not sets:
            return None

        return sets[0]

    except Exception:
        return None


# =========================================================
# RRP
# =========================================================

def get_rrp(brickset):

    if not brickset:
        return None

    lego_com = brickset.get("LEGOCom", {})

    if isinstance(lego_com, dict):

        for country in ["DE", "UK", "US"]:

            country_data = lego_com.get(country)

            if isinstance(country_data, dict):

                price = country_data.get("retailPrice")

                if price is not None:
                    try:
                        return float(price)
                    except Exception:
                        pass

    for field in [
        "retailPrice",
        "RRP",
        "rrp",
        "price",
    ]:

        value = brickset.get(field)

        if value is not None:
            try:
                return float(value)
            except Exception:
                pass

    return None


# =========================================================
# STATUS
# =========================================================

def get_status(brickset):

    if not brickset:
        return "❓ Άγνωστο"

    released = brickset.get("released")
    launch_date = brickset.get("launchDate")
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

    return "❓ Άγνωστο"


def format_date(date_value):

    if not date_value:
        return None

    try:
        dt = datetime.strptime(
            date_value[:10],
            "%Y-%m-%d"
        )

        return dt.strftime("%d/%m/%Y")

    except Exception:
        return date_value


# =========================================================
# CURRENCIES
# =========================================================

CURRENCY_ALIASES = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",

    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",

    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "£": "GBP",

    "yen": "JPY",
    "jpy": "JPY",
    "¥": "JPY",

    "chf": "CHF",
    "franc": "CHF",
    "francs": "CHF",

    "cad": "CAD",
    "canadian dollar": "CAD",

    "aud": "AUD",
    "australian dollar": "AUD",

    "sek": "SEK",
    "nok": "NOK",
    "dkk": "DKK",
    "pln": "PLN",
}


def find_currency(text):

    normalized = normalize_text(text)

    for alias, code in CURRENCY_ALIASES.items():

        if alias in normalized:
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

    for alias in sorted(
        CURRENCY_ALIASES.keys(),
        key=len,
        reverse=True
    ):

        cleaned = re.sub(
            re.escape(alias),
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )

    numbers = re.findall(
        r"\d+(?:[.,]\d+)?",
        cleaned
    )

    if not numbers:
        return None, currency

    try:

        value = float(
            numbers[-1].replace(",", ".")
        )

        return value, currency

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
            timeout=15,
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


def price_rating(percentage):

    if percentage >= 30:
        return "🟢 Εξαιρετική τιμή!"

    if percentage >= 15:
        return "🟢 Πολύ καλή τιμή!"

    if percentage >= 5:
        return "🟡 Καλή τιμή"

    if percentage >= 0:
        return "🟠 Μικρή έκπτωση"

    if percentage > -10:
        return "🔴 Πάνω από το RRP"

    return "🔴 Αρκετά πάνω από το RRP"


# =========================================================
# SET BUTTONS
# =========================================================

def set_buttons(set_number):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛒 LEGO",
                url=(
                    "https://www.lego.com/en-gb/search"
                    f"?q={set_number}"
                ),
            ),
            InlineKeyboardButton(
                "🛍️ eBay",
                url=(
                    "https://www.ebay.com/sch/i.html"
                    f"?_nkw=LEGO+{set_number}"
                ),
            ),
        ],
        [
            InlineKeyboardButton(
                "🧱 BrickLink",
                url=(
                    "https://www.bricklink.com/v2/catalog/"
                    f"catalogitem.page?S={set_number}-1"
                ),
            ),
            InlineKeyboardButton(
                "📊 Price Guide",
                url=(
                    "https://www.bricklink.com/catalogPG.asp"
                    f"?S={set_number}-1&ColorID=0"
                ),
            ),
        ],
        [
            InlineKeyboardButton(
                "➕ Collection",
                callback_data=f"addcollection:{set_number}",
            ),
            InlineKeyboardButton(
                "⭐ Wishlist",
                callback_data=f"addwishlist:{set_number}",
            ),
        ],
    ])


# =========================================================
# SET INFORMATION
# =========================================================

async def send_set_information(message, set_number):

    set_number = normalize_set_number(set_number)

    data = get_set_info(set_number)

    if not data:
        await message.reply_text(
            "❌ Δεν βρήκα αυτό το LEGO set."
        )
        return

    brickset = get_brickset_info(set_number)

    name = data.get("name", "Άγνωστο")
    year = data.get("year")
    pieces = data.get("num_parts")
    image_url = data.get("set_img_url")

    status = get_status(brickset)

    lines = [
        f"🧱 <b>{name}</b>",
        "",
        f"🔢 Set: <b>{set_number}</b>",
        f"📅 Έτος: {year or 'Άγνωστο'}",
        f"🧩 Κομμάτια: {pieces or 'Άγνωστο'}",
        f"📊 Κατάσταση: {status}",
    ]

    if year:

        try:

            age = datetime.now().year - int(year)

            lines.append(
                f"⏳ Ηλικία: {age} χρόνια"
            )

        except Exception:
            pass

    launch_date = (
        brickset.get("launchDate")
        if brickset
        else None
    )

    exit_date = (
        brickset.get("exitDate")
        if brickset
        else None
    )

    if launch_date:
        lines.append(
            f"🚀 Κυκλοφορία: {format_date(launch_date)}"
        )

    if exit_date:
        lines.append(
            f"🏁 Απόσυρση: {format_date(exit_date)}"
        )

    rrp = get_rrp(brickset)

    if rrp is not None:

        lines.append(
            f"💶 RRP: €{rrp:.2f}"
        )

        if pieces:

            try:

                per_piece = rrp / int(pieces)

                lines.append(
                    f"🧮 RRP / κομμάτι: €{per_piece:.2f}"
                )

            except Exception:
                pass

    text = "\n".join(lines)

    if image_url:

        await message.reply_photo(
            photo=image_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=set_buttons(set_number),
        )

    else:

        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=set_buttons(set_number),
        )


# =========================================================
# COLLECTION
# =========================================================

def add_collection(user_id, set_number):

    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO collections
                    (user_id, set_number)

                VALUES
                    (%s, %s)

                ON CONFLICT DO NOTHING
                """,
                (
                    user_id,
                    set_number,
                ),
            )

        conn.commit()


def remove_collection(user_id, set_number):

    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                DELETE FROM collections
                WHERE user_id = %s
                  AND set_number = %s
                """,
                (
                    user_id,
                    set_number,
                ),
            )

        conn.commit()


def get_collection(user_id):

    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT set_number
                FROM collections
                WHERE user_id = %s
                ORDER BY created_at
                """,
                (user_id,),
            )

            rows = cur.fetchall()

    return [
        row["set_number"]
        for row in rows
    ]


# =========================================================
# WISHLIST
# =========================================================

def add_wishlist(user_id, set_number):

    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO wishlist
                    (user_id, set_number)

                VALUES
                    (%s, %s)

                ON CONFLICT DO NOTHING
                """,
                (
                    user_id,
                    set_number,
                ),
            )

        conn.commit()


def remove_wishlist(user_id, set_number):

    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                DELETE FROM wishlist
                WHERE user_id = %s
                  AND set_number = %s
                """,
                (
                    user_id,
                    set_number,
                ),
            )

        conn.commit()


def get_wishlist(user_id):

    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT set_number
                FROM wishlist
                WHERE user_id = %s
                ORDER BY created_at
                """,
                (user_id,),
            )

            rows = cur.fetchall()

    return [
        row["set_number"]
        for row in rows
    ]


# =========================================================
# COMMAND: /ADD
# =========================================================

async def add_command(update, context):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    if not context.args:
        await update.message.reply_text(
            "Χρήση: /add 10316"
        )
        return

    set_number = normalize_set_number(
        context.args[0]
    )

    if not get_set_info(set_number):

        await update.message.reply_text(
            "❌ Δεν βρήκα αυτό το LEGO set."
        )
        return

    add_collection(
        update.effective_user.id,
        set_number,
    )

    await update.message.reply_text(
        f"🧱 Το {set_number} προστέθηκε στη Collection σου!"
    )


# =========================================================
# COMMAND: /REMOVE
# =========================================================

async def remove_command(update, context):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    if not context.args:
        await update.message.reply_text(
            "Χρήση: /remove 10316"
        )
        return

    set_number = normalize_set_number(
        context.args[0]
    )

    remove_collection(
        update.effective_user.id,
        set_number,
    )

    await update.message.reply_text(
        f"🗑️ Το {set_number} αφαιρέθηκε από τη Collection."
    )


# =========================================================
# COMMAND: /WANT
# =========================================================

async def want_command(update, context):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    if not context.args:
        await update.message.reply_text(
            "Χρήση: /want 10316"
        )
        return

    set_number = normalize_set_number(
        context.args[0]
    )

    if not get_set_info(set_number):

        await update.message.reply_text(
            "❌ Δεν βρήκα αυτό το LEGO set."
        )
        return

    add_wishlist(
        update.effective_user.id,
        set_number,
    )

    await update.message.reply_text(
        f"⭐ Το {set_number} προστέθηκε στο Wishlist!"
    )


# =========================================================
# COMMAND: /UNWANT
# =========================================================

async def unwant_command(update, context):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    if not context.args:
        await update.message.reply_text(
            "Χρήση: /unwant 10316"
        )
        return

    set_number = normalize_set_number(
        context.args[0]
    )

    remove_wishlist(
        update.effective_user.id,
        set_number,
    )

    await update.message.reply_text(
        f"🗑️ Το {set_number} αφαιρέθηκε από το Wishlist."
    )


# =========================================================
# COMMAND: /COLLECTION
# =========================================================

async def collection_command(update, context):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    sets = get_collection(
        update.effective_user.id
    )

    if not sets:

        await update.message.reply_text(
            "🧱 Η Collection σου είναι άδεια."
        )
        return

    await update.message.reply_text(
        f"🧱 Collection — {len(sets)} sets"
    )

    for set_number in sets:

        await send_set_information(
            update.message,
            set_number,
        )


# =========================================================
# COMMAND: /WISHLIST
# =========================================================

async def wishlist_command(update, context):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    sets = get_wishlist(
        update.effective_user.id
    )

    if not sets:

        await update.message.reply_text(
            "⭐ Το Wishlist σου είναι άδειο."
        )
        return

    await update.message.reply_text(
        f"⭐ Wishlist — {len(sets)} sets"
    )

    for set_number in sets:

        await send_set_information(
            update.message,
            set_number,
        )


# =========================================================
# COMMAND: /STATS
# =========================================================

async def stats_command(update, context):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    sets = get_collection(
        update.effective_user.id
    )

    if not sets:

        await update.message.reply_text(
            "📊 Η Collection σου είναι άδεια."
        )
        return

    total_pieces = 0
    total_rrp = 0
    rrp_count = 0

    oldest = None
    newest = None
    largest = None
    expensive = None

    active = 0
    retired = 0
    unknown = 0

    for set_number in sets:

        data = get_set_info(set_number)
        brickset = get_brickset_info(set_number)

        if not data:
            continue

        year = data.get("year")
        pieces = data.get("num_parts")
        rrp = get_rrp(brickset)
        status = get_status(brickset)

        if pieces:

            try:

                total_pieces += int(pieces)

                if (
                    largest is None
                    or int(pieces) > largest[1]
                ):
                    largest = (
                        set_number,
                        int(pieces),
                    )

            except Exception:
                pass

        if rrp is not None:

            total_rrp += rrp
            rrp_count += 1

            if (
                expensive is None
                or rrp > expensive[1]
            ):
                expensive = (
                    set_number,
                    rrp,
                )

        if year:

            try:

                year_int = int(year)

                if (
                    oldest is None
                    or year_int < oldest[1]
                ):
                    oldest = (
                        set_number,
                        year_int,
                    )

                if (
                    newest is None
                    or year_int > newest[1]
                ):
                    newest = (
                        set_number,
                        year_int,
                    )

            except Exception:
                pass

        if status == "🟢 Σε κυκλοφορία":
            active += 1

        elif status == "🔴 Retired":
            retired += 1

        else:
            unknown += 1

    lines = [
        "📊 <b>Collection Stats</b>",
        "",
        f"🧱 Sets: {len(sets)}",
        f"🧩 Συνολικά κομμάτια: {total_pieces:,}",
        f"💶 Συνολικό RRP: €{total_rrp:,.2f}",
    ]

    if rrp_count:

        lines.append(
            f"📈 Μέσο RRP / set: "
            f"€{total_rrp / rrp_count:,.2f}"
        )

    if oldest:

        lines.append(
            f"👴 Παλαιότερο: "
            f"{oldest[0]} ({oldest[1]})"
        )

    if newest:

        lines.append(
            f"🆕 Νεότερο: "
            f"{newest[0]} ({newest[1]})"
        )

    if largest:

        lines.append(
            f"🧩 Μεγαλύτερο: "
            f"{largest[0]} ({largest[1]:,} κομμάτια)"
        )

    if expensive:

        lines.append(
            f"💰 Ακριβότερο: "
            f"{expensive[0]} (€{expensive[1]:,.2f})"
        )

    lines.extend([
        "",
        f"🟢 Σε κυκλοφορία: {active}",
        f"🔴 Retired: {retired}",
        f"❓ Άγνωστα: {unknown}",
    ])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
    )


# =========================================================
# COMMAND: /ID
# =========================================================

async def id_command(update, context):

    await update.message.reply_text(
        f"🆔 Telegram ID: {update.effective_user.id}"
    )


# =========================================================
# SEARCH
# =========================================================

async def search_sets(message, keyword):

    keyword = keyword.strip()

    if not keyword:

        await message.reply_text(
            "Χρήση: /search castle"
        )
        return

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
        "ordering": "-year",
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=15,
        )

        if response.status_code != 200:

            await message.reply_text(
                "❌ Πρόβλημα με την αναζήτηση."
            )
            return

        data = response.json()

    except Exception:

        await message.reply_text(
            "❌ Δεν μπόρεσα να κάνω την αναζήτηση."
        )
        return

    results = data.get("results", [])

    if not results:

        await message.reply_text(
            f"❌ Δεν βρήκα sets για: {keyword}"
        )
        return

    await message.reply_text(
        f"🔎 Αποτελέσματα για: "
        f"<b>{keyword}</b>",
        parse_mode="HTML",
    )

    for result in results:

        set_number = result.get(
            "set_num",
            ""
        )

        image_url = result.get(
            "set_img_url"
        )

        if not set_number:
            continue

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
                reply_markup=keyboard,
            )

        else:

            await message.reply_text(
                "🧱",
                reply_markup=keyboard,
            )


async def search_command(update, context):

    if not has_access(update.effective_user.id):
        await access_denied(update)
        return

    keyword = " ".join(context.args)

    await search_sets(
        update.message,
        keyword,
    )


# =========================================================
# BUTTON CALLBACKS
# =========================================================

async def button_callback(update, context):

    query = update.callback_query
    data = query.data

    # APPROVE / REJECT
    if (
        data.startswith("approve:")
        or data.startswith("reject:")
    ):

        await access_callback(
            update,
            context,
        )

        return

    await query.answer()

    user_id = query.from_user.id

    if not has_access(user_id):

        await query.answer(
            "🔒 Δεν έχεις πρόσβαση.",
            show_alert=True,
        )
        return

    # SEARCH RESULT -> SET INFO
    if data.startswith("setinfo:"):

        set_number = data.split(
            ":",
            1
        )[1]

        await send_set_information(
            query.message,
            set_number,
        )

    # ADD COLLECTION
    elif data.startswith("addcollection:"):

        set_number = data.split(
            ":",
            1
        )[1]

        add_collection(
            user_id,
            set_number,
        )

        await query.answer(
            "🧱 Προστέθηκε στη Collection!"
        )

    # ADD WISHLIST
    elif data.startswith("addwishlist:"):

        set_number = data.split(
            ":",
            1
        )[1]

        add_wishlist(
            user_id,
            set_number,
        )

        await query.answer(
            "⭐ Προστέθηκε στο Wishlist!"
        )


# =========================================================
# NORMAL TEXT / SET + PRICE
# =========================================================

async def handle_message(update, context):

    if not update.message:
        return

    if not has_access(
        update.effective_user.id
    ):
        await access_denied(update)
        return

    text = update.message.text.strip()

    match = re.match(
        r"^(\d{4,6})(?:\s+(.+))?$",
        text,
    )

    if not match:
        return

    set_number = match.group(1)
    price_text = match.group(2)

    data = get_set_info(set_number)

    if not data:

        await update.message.reply_text(
            "❌ Δεν βρήκα αυτό το LEGO set."
        )
        return

    # SHOW SET INFORMATION
    await send_set_information(
        update.message,
        set_number,
    )

    # NO PRICE
    if not price_text:
        return

    # EXTRACT PRICE
    price, currency = extract_price(
        price_text
    )

    if price is None:
        return

    brickset = get_brickset_info(
        set_number
    )

    rrp = get_rrp(brickset)

    if rrp is None:

        await update.message.reply_text(
            "💰 Δεν βρήκα διαθέσιμο RRP για σύγκριση."
        )
        return

    # CONVERT TO EUR
    eur_price = convert_to_eur(
        price,
        currency,
    )

    if eur_price is None:

        await update.message.reply_text(
            "❌ Δεν μπόρεσα να μετατρέψω "
            "το νόμισμα σε EUR."
        )
        return

    # CALCULATE DIFFERENCE
    difference = (
        (rrp - eur_price)
        / rrp
    ) * 100

    rating = price_rating(
        difference
    )

    await update.message.reply_text(
        "💰 <b>Σύγκριση τιμής</b>\n\n"
        f"Τιμή που έδωσες: "
        f"{price:.2f} {currency}\n"
        f"Σε EUR: €{eur_price:.2f}\n"
        f"RRP: €{rrp:.2f}\n"
        f"Διαφορά: {difference:+.1f}%\n\n"
        f"{rating}",
        parse_mode="HTML",
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):

    print(
        "ERROR:",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    required = [
        TELEGRAM_TOKEN,
        REBRICKABLE_API_KEY,
        BRICKSET_API_KEY,
        DATABASE_URL,
    ]

    if not all(required):
        raise RuntimeError(
            "Missing required environment variables."
        )

    if not ADMIN_USER_ID:
        raise RuntimeError(
            "ADMIN_USER_ID is missing."
        )

    # CREATE DATABASE TABLES
    init_db()

    # CREATE BOT
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    # COMMANDS
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "id",
            id_command
        )
    )

    app.add_handler(
        CommandHandler(
            "add",
            add_command
        )
    )

    app.add_handler(
        CommandHandler(
            "remove",
            remove_command
        )
    )

    app.add_handler(
        CommandHandler(
            "collection",
            collection_command
        )
    )

    app.add_handler(
        CommandHandler(
            "want",
            want_command
        )
    )

    app.add_handler(
        CommandHandler(
            "unwant",
            unwant_command
        )
    )

    app.add_handler(
        CommandHandler(
            "wishlist",
            wishlist_command
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats_command
        )
    )

    app.add_handler(
        CommandHandler(
            "search",
            search_command
        )
    )

    # BUTTONS
    app.add_handler(
        CallbackQueryHandler(
            button_callback
        )
    )

    # NORMAL TEXT
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    # ERRORS
    app.add_error_handler(
        error_handler
    )

    print(
        "LEGO Bot started."
    )

    app.run_polling()


if __name__ == "__main__":
    main()

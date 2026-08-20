import os
import json
import time
import logging
import threading
from threading import Lock
from flask import Flask
import telebot
from telebot import types

# ============================================================
# ENVIRONMENT & CONFIGURATION
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

DATA_FILE = "bot_data.json"

# IMPORTANT:
# Render Environment Variable:
# PROTECTED_USER_ID=8637166626
#
# This user will automatically be recreated in the local DB
# if the DB is fresh/reset.
PROTECTED_USER_ID = os.getenv("PROTECTED_USER_ID", "").strip()

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set!")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
db_lock = Lock()

# ============================================================
# WEB SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "⚡ Gateway Service Active ✅", 200


def run_flask():
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ============================================================
# DATABASE CORE
# ============================================================

def empty_db():
    return {
        "users": {},          # user_id -> {"admin_msgs": [], "user_msgs": []}
        "reply_map": {},      # admin_msg_id -> user_id
        "msg_map_a2u": {},    # admin_msg_id -> user_msg_id
        "msg_map_u2a": {},    # f"{user_id}_{user_msg_id}" -> admin_msg_id
        "blocked": [],
        "alerts": [],
        "selected_user": None
    }


def ensure_user(data, user_id):
    user_id = str(user_id)

    if user_id not in data["users"]:
        data["users"][user_id] = {
            "admin_msgs": [],
            "user_msgs": []
        }


def ensure_protected_user(data):
    """
    Re-create the protected user's basic DB record if missing.
    This protects only the user's identity/record, not old history.
    """

    if PROTECTED_USER_ID:
        ensure_user(data, PROTECTED_USER_ID)


def load_data():
    with db_lock:

        if not os.path.exists(DATA_FILE):
            data = empty_db()
            ensure_protected_user(data)
            return data

        try:

            with open(
                DATA_FILE,
                "r",
                encoding="utf-8"
            ) as f:
                data = json.load(f)

            for k in [
                "users",
                "reply_map",
                "msg_map_a2u",
                "msg_map_u2a",
                "blocked",
                "alerts"
            ]:
                data.setdefault(
                    k,
                    {} if "map" in k or k == "users" else []
                )

            data.setdefault("selected_user", None)

            ensure_protected_user(data)

            return data

        except Exception as e:

            logging.error(
                f"DB Load Error: {e}"
            )

            data = empty_db()
            ensure_protected_user(data)

            return data


def save_data(data):

    with db_lock:

        temp = DATA_FILE + ".tmp"

        try:

            with open(
                temp,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            os.replace(
                temp,
                DATA_FILE
            )

        except Exception as e:

            logging.error(
                f"DB Save Error: {e}"
            )


SUPPORTED_TYPES = [
    "text",
    "photo",
    "video",
    "document",
    "audio",
    "voice",
    "sticker",
    "animation"
]

# ============================================================
# ADMIN DASHBOARD
# ============================================================

@bot.message_handler(commands=["start"])
def handle_start(message):

    chat_id = message.chat.id
    data = load_data()

    # ========================================================
    # ADMIN
    # ========================================================

    if chat_id == ADMIN_ID:

        selected = (
            f"<code>{data['selected_user']}</code>"
            if data["selected_user"]
            else "⭕ <i>None (Manual/Reply Mode)</i>"
        )

        protected = (
            f"<code>{PROTECTED_USER_ID}</code>"
            if PROTECTED_USER_ID
            else "⭕ <i>Not configured</i>"
        )

        panel = f"""
🎛️ <b>CONTROL CONSOLE | ADMIN</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 <b>Focused Target:</b> {selected}
🛡️ <b>Protected User:</b> {protected}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📡 <b>ROUTING & MESSAGING:</b>
• <b>Reply directly</b> to any forwarded message to quote-reply.
• <code>/select &lt;user_id&gt;</code> ── Lock focus to a specific user
• <code>/unselect</code> ──────────── Release locked focus
• <code>/dm &lt;id&gt; &lt;text&gt;</code> ──────── Send instant standalone message

👤 <b>USER PROFILE:</b>
• <code>/userprofile &lt;id&gt;</code> ───── View Telegram profile information

🧹 <b>PURGE & DELETION:</b>
• <code>/clearall &lt;id&gt;</code> ──────── Delete ALL admin messages
• <code>/purge &lt;id&gt;</code> ─────────── Wipe entire user chat
• <code>/resetdb</code> ────────────── Reset database

👥 <b>MANAGEMENT:</b>
• <code>/users</code> ──────────────── List all users
• <code>/ban &lt;id&gt;</code> ────────────── Restrict user
• <code>/unban &lt;id&gt;</code> ──────────── Restore user
• <code>/alert &lt;id&gt;</code> ──────────── Toggle alert flag
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        bot.send_message(
            ADMIN_ID,
            panel
        )

        return

    # ========================================================
    # USER
    # ========================================================

    user_id = str(chat_id)

    if user_id in data["blocked"]:
        return

    ensure_user(
        data,
        user_id
    )

    save_data(data)

    welcome_text = """
🔒 <b>ENCRYPTED SECURE CHANNEL</b>

<blockquote>Aapka direct communication session establish ho chuka hai.

Aap yahan apna koi bhi message, photo, ya document bhej sakte hain. Hamaari team aapse isi chat me connect karegi.</blockquote>

💬 <i>Apna sandesh niche type karke send karein.</i>
"""

    bot.send_message(
        chat_id,
        welcome_text
    )


# ============================================================
# SELECT USER
# ============================================================

@bot.message_handler(commands=["select"])
def select_user(message):

    if message.chat.id != ADMIN_ID:
        return

    try:
        user_id = message.text.split()[1]

    except IndexError:

        bot.send_message(
            ADMIN_ID,
            "⚠️ <b>Format:</b> "
            "<code>/select &lt;user_id&gt;</code>"
        )

        return

    data = load_data()

    data["selected_user"] = str(user_id)

    save_data(data)

    bot.send_message(
        ADMIN_ID,
        f"🎯 <b>Focus Locked:</b> "
        f"<code>{user_id}</code>."
        "\nMessages without reply will be delivered here."
    )


# ============================================================
# UNSELECT
# ============================================================

@bot.message_handler(commands=["unselect"])
def unselect_user(message):

    if message.chat.id != ADMIN_ID:
        return

    data = load_data()

    data["selected_user"] = None

    save_data(data)

    bot.send_message(
        ADMIN_ID,
        "🎯 <b>Focus Released.</b> "
        "Manual/Reply mode active."
    )


# ============================================================
# DIRECT MESSAGE
# ============================================================

@bot.message_handler(commands=["dm"])
def direct_message(message):

    if message.chat.id != ADMIN_ID:
        return

    try:

        parts = message.text.split(
            " ",
            2
        )

        user_id = parts[1]
        text = parts[2]

    except IndexError:

        bot.send_message(
            ADMIN_ID,
            "⚠️ <b>Format:</b> "
            "<code>/dm &lt;user_id&gt; &lt;text&gt;</code>"
        )

        return

    data = load_data()

    try:

        sent = bot.send_message(
            int(user_id),
            text
        )

        ensure_user(
            data,
            user_id
        )

        data["users"][str(user_id)][
            "admin_msgs"
        ].append(
            sent.message_id
        )

        # Store mapping so future replies can remain connected.
        data["msg_map_a2u"][
            str(message.message_id)
        ] = sent.message_id

        data["reply_map"][
            str(message.message_id)
        ] = str(user_id)

        save_data(data)

        bot.send_message(
            ADMIN_ID,
            f"✅ <b>Sent to</b> "
            f"<code>{user_id}</code>"
        )

    except Exception as e:

        bot.send_message(
            ADMIN_ID,
            f"❌ <b>Delivery Error:</b> {e}"
        )


# ============================================================
# CLEAR ALL ADMIN MESSAGES
# ============================================================

@bot.message_handler(commands=["clearall"])
def clear_admin_messages(message):

    if message.chat.id != ADMIN_ID:
        return

    try:

        user_id = message.text.split()[1]

    except IndexError:

        data = load_data()

        user_id = data.get(
            "selected_user"
        )

        if not user_id:

            bot.send_message(
                ADMIN_ID,
                "⚠️ <b>Format:</b> "
                "<code>/clearall &lt;user_id&gt;</code>"
            )

            return

    data = load_data()

    user_str = str(user_id)

    if user_str not in data["users"]:

        bot.send_message(
            ADMIN_ID,
            "⚠️ No message history found for this user."
        )

        return

    admin_msgs = data["users"][user_str].get(
        "admin_msgs",
        []
    )

    count = 0

    for msg_id in admin_msgs:

        try:

            bot.delete_message(
                chat_id=int(user_str),
                message_id=msg_id
            )

            count += 1

        except Exception:
            pass

    data["users"][user_str]["admin_msgs"] = []

    save_data(data)

    bot.send_message(
        ADMIN_ID,
        f"🧹 <b>Cleared:</b> {count} Admin messages "
        f"deleted from <code>{user_str}</code>'s chat."
    )


# ============================================================
# PURGE
# ============================================================

@bot.message_handler(commands=["purge"])
def purge_chat(message):

    if message.chat.id != ADMIN_ID:
        return

    try:

        user_id = message.text.split()[1]

    except IndexError:

        bot.send_message(
            ADMIN_ID,
            "⚠️ <b>Format:</b> "
            "<code>/purge &lt;user_id&gt;</code>"
        )

        return

    data = load_data()

    user_str = str(user_id)

    if user_str not in data["users"]:

        bot.send_message(
            ADMIN_ID,
            "⚠️ User history not found."
        )

        return

    total = 0

    # USER MESSAGES
    for msg_id in data["users"][user_str].get(
        "user_msgs",
        []
    ):

        try:

            bot.delete_message(
                chat_id=int(user_str),
                message_id=msg_id
            )

            total += 1

        except Exception:
            pass

    # ADMIN MESSAGES
    for msg_id in data["users"][user_str].get(
        "admin_msgs",
        []
    ):

        try:

            bot.delete_message(
                chat_id=int(user_str),
                message_id=msg_id
            )

            total += 1

        except Exception:
            pass

    data["users"][user_str] = {
        "admin_msgs": [],
        "user_msgs": []
    }

    save_data(data)

    bot.send_message(
        ADMIN_ID,
        f"💥 <b>Purged:</b> {total} total messages "
        f"cleared from <code>{user_str}</code>'s chat."
    )


# ============================================================
# RESET DATABASE
# ============================================================

@bot.message_handler(commands=["resetdb"])
def reset_database(message):

    if message.chat.id != ADMIN_ID:
        return

    data = empty_db()

    # IMPORTANT:
    # Protected user's basic record survives reset.
    ensure_protected_user(data)

    save_data(data)

    if PROTECTED_USER_ID:

        bot.send_message(
            ADMIN_ID,
            "♻️ <b>Database Reset:</b> "
            "All state logs and mappings cleared.\n\n"
            f"🛡️ Protected user "
            f"<code>{PROTECTED_USER_ID}</code> "
            "was preserved."
        )

    else:

        bot.send_message(
            ADMIN_ID,
            "♻️ <b>Database Reset:</b> "
            "All state logs and mappings cleared."
        )


# ============================================================
# USERS LIST
# ============================================================

@bot.message_handler(commands=["users"])
def list_users(message):

    if message.chat.id != ADMIN_ID:
        return

    data = load_data()

    users_dict = data.get(
        "users",
        {}
    )

    if not users_dict:

        bot.send_message(
            ADMIN_ID,
            "👥 <b>No registered users found.</b>"
        )

        return

    text = (
        "📊 <b>USER DIRECTORY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, u_id in enumerate(
        users_dict.keys(),
        1
    ):

        status = (
            "⛔ [Banned]"
            if u_id in data["blocked"]
            else
            "🚨 [Flagged]"
            if u_id in data["alerts"]
            else
            "🟢 [Active]"
        )

        text += (
            f"{i}. <code>{u_id}</code> "
            f"── {status}\n"
        )

    bot.send_message(
        ADMIN_ID,
        text
    )


# ============================================================
# USER PROFILE
# ============================================================

@bot.message_handler(commands=["userprofile"])
def user_profile(message):

    if message.chat.id != ADMIN_ID:
        return

    parts = message.text.split(
        maxsplit=1
    )

    if len(parts) < 2:

        bot.send_message(
            ADMIN_ID,
            "⚠️ <b>Format:</b>\n"
            "<code>/userprofile USER_ID</code>"
        )

        return

    user_id = parts[1].strip()

    if not user_id.lstrip("-").isdigit():

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid Chat ID."
        )

        return

    user_id_int = int(user_id)

    data = load_data()

    # If the protected user is missing for any reason,
    # recreate its basic record.
    if user_id not in data.get("users", {}):

        if (
            PROTECTED_USER_ID
            and user_id == PROTECTED_USER_ID
        ):

            ensure_protected_user(data)

            save_data(data)

        else:

            bot.send_message(
                ADMIN_ID,
                f"⚠️ User "
                f"<code>{user_id}</code> "
                "local database mein registered nahi hai."
            )

            return

    try:

        # Ask Telegram for current information.
        chat = bot.get_chat(
            user_id_int
        )

        first_name = (
            getattr(
                chat,
                "first_name",
                None
            )
            or ""
        )

        last_name = (
            getattr(
                chat,
                "last_name",
                None
            )
            or ""
        )

        username = (
            getattr(
                chat,
                "username",
                None
            )
            or ""
        )

        full_name = (
            f"{first_name} {last_name}"
        ).strip()

        if not full_name:
            full_name = "Not Available"

        if username:

            username_text = (
                f"@{username}"
            )

            profile_url = (
                f"https://t.me/{username}"
            )

        else:

            username_text = (
                "Not Available"
            )

            # Telegram deep-link for the user.
            profile_url = (
                f"tg://user?id={user_id}"
            )

        status = (
            "⛔ Banned"
            if user_id in data["blocked"]
            else
            "🚨 Alert"
            if user_id in data["alerts"]
            else
            "🟢 Active"
        )

        user_data = data["users"].get(
            user_id,
            {}
        )

        user_messages = len(
            user_data.get(
                "user_msgs",
                []
            )
        )

        admin_messages = len(
            user_data.get(
                "admin_msgs",
                []
            )
        )

        # Telegram profile button.
        keyboard = types.InlineKeyboardMarkup()

        keyboard.add(
            types.InlineKeyboardButton(
                "👤 OPEN TELEGRAM PROFILE",
                url=profile_url
            )
        )

        text = (
            "👤 <b>USER PROFILE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👨 <b>Name:</b> "
            f"{full_name}\n"
            f"🔗 <b>Username:</b> "
            f"{username_text}\n"
            f"🆔 <b>Chat ID:</b> "
            f"<code>{user_id}</code>\n"
            f"📊 <b>Status:</b> "
            f"{status}\n"
            f"💬 <b>User Messages:</b> "
            f"{user_messages}\n"
            f"📨 <b>Admin Messages:</b> "
            f"{admin_messages}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        bot.send_message(
            ADMIN_ID,
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except Exception as e:

        logging.error(
            f"User Profile Error: {e}"
        )

        bot.send_message(
            ADMIN_ID,
            "❌ <b>Profile Fetch Failed</b>\n\n"
            f"<code>{e}</code>\n\n"
            "Telegram Bot API ne is Chat ID "
            "ki profile information provide nahi ki."
        )


# ============================================================
# BAN USER
# ============================================================

@bot.message_handler(commands=["ban"])
def ban_user(message):

    if message.chat.id != ADMIN_ID:
        return

    try:

        user_id = message.text.split()[1]

    except IndexError:

        bot.send_message(
            ADMIN_ID,
            "⚠️ <b>Format:</b> "
            "<code>/ban &lt;user_id&gt;</code>"
        )

        return

    data = load_data()

    if user_id not in data["blocked"]:

        data["blocked"].append(
            user_id
        )

        save_data(data)

        bot.send_message(
            ADMIN_ID,
            f"⛔ User "
            f"<code>{user_id}</code> "
            "is now blocked."
        )

    else:

        bot.send_message(
            ADMIN_ID,
            "⚠️ User is already blocked."
        )


# ============================================================
# UNBAN USER
# ============================================================

@bot.message_handler(commands=["unban"])
def unban_user(message):

    if message.chat.id != ADMIN_ID:
        return

    try:

        user_id = message.text.split()[1]

    except IndexError:

        bot.send_message(
            ADMIN_ID,
            "⚠️ <b>Format:</b> "
            "<code>/unban &lt;user_id&gt;</code>"
        )

        return

    data = load_data()

    if user_id in data["blocked"]:

        data["blocked"].remove(
            user_id
        )

        save_data(data)

        bot.send_message(
            ADMIN_ID,
            f"✅ User "
            f"<code>{user_id}</code> "
            "unblocked."
        )

    else:

        bot.send_message(
            ADMIN_ID,
            "⚠️ User is not blocked."
        )


# ============================================================
# ALERT
# ============================================================

@bot.message_handler(commands=["alert"])
def toggle_alert(message):

    if message.chat.id != ADMIN_ID:
        return

    try:

        user_id = message.text.split()[1]

    except IndexError:

        bot.send_message(
            ADMIN_ID,
            "⚠️ <b>Format:</b> "
            "<code>/alert &lt;user_id&gt;</code>"
        )

        return

    data = load_data()

    if user_id not in data["alerts"]:

        data["alerts"].append(
            user_id
        )

        save_data(data)

        bot.send_message(
            ADMIN_ID,
            f"🚨 Alert flag "
            f"<b>ADDED</b> to "
            f"<code>{user_id}</code>."
        )

    else:

        data["alerts"].remove(
            user_id
        )

        save_data(data)

        bot.send_message(
            ADMIN_ID,
            f"🏳️ Alert flag "
            f"<b>REMOVED</b> from "
            f"<code>{user_id}</code>."
        )


# ============================================================
# CORE ROUTING ENGINE
# NATIVE QUOTE-REPLY MAPPING
# ============================================================

@bot.message_handler(
    func=lambda message: True,
    content_types=SUPPORTED_TYPES
)
def handle_all_messages(message):

    chat_id = message.chat.id
    message_id = message.message_id

    data = load_data()

    # ========================================================
    # 1. ADMIN -> USER
    # ========================================================

    if chat_id == ADMIN_ID:

        target_user = None
        target_quote_id = None

        # ----------------------------------------------------
        # ADMIN REPLY MODE
        # ----------------------------------------------------

        if message.reply_to_message:

            replied_admin_id = str(
                message.reply_to_message.message_id
            )

            target_user = data[
                "reply_map"
            ].get(
                replied_admin_id
            )

            target_quote_id = data[
                "msg_map_a2u"
            ].get(
                replied_admin_id
            )

        # ----------------------------------------------------
        # SELECTED USER MODE
        # ----------------------------------------------------

        elif data.get("selected_user"):

            target_user = data[
                "selected_user"
            ]

        if not target_user:

            bot.send_message(
                ADMIN_ID,
                "⚠️ <b>Action Required:</b> "
                "Reply directly to a user's message, "
                "or select one via "
                "<code>/select &lt;id&gt;</code>"
            )

            return

        target_user = str(
            target_user
        )

        if target_user in data["blocked"]:

            bot.send_message(
                ADMIN_ID,
                "⛔ Delivery failed: "
                "User is blocked."
            )

            return

        try:

            # IMPORTANT:
            # copy_message keeps ADMIN profile hidden.
            #
            # Native quote-reply mapping is preserved.

            sent = bot.copy_message(
                chat_id=int(target_user),
                from_chat_id=ADMIN_ID,
                message_id=message_id,
                reply_to_message_id=target_quote_id
            )

            ensure_user(
                data,
                target_user
            )

            data["users"][
                str(target_user)
            ]["admin_msgs"].append(
                sent.message_id
            )

            # ------------------------------------------------
            # CROSS MAPPING
            # ------------------------------------------------

            admin_msg_str = str(
                message_id
            )

            data["msg_map_u2a"][
                f"{target_user}_{sent.message_id}"
            ] = message_id

            data["msg_map_a2u"][
                admin_msg_str
            ] = sent.message_id

            data["reply_map"][
                admin_msg_str
            ] = str(target_user)

            save_data(data)

        except Exception as e:

            logging.error(
                f"Admin -> User Error: {e}"
            )

            bot.send_message(
                ADMIN_ID,
                f"❌ <b>Send Failed:</b> "
                f"{e}"
            )

        return

    # ========================================================
    # 2. USER -> ADMIN
    # ========================================================

    user_id = str(
        chat_id
    )

    if user_id in data["blocked"]:
        return

    ensure_user(
        data,
        user_id
    )

    data["users"][
        user_id
    ]["user_msgs"].append(
        message_id
    )

    # --------------------------------------------------------
    # USER REPLY -> FIND ORIGINAL ADMIN MESSAGE
    # --------------------------------------------------------

    reply_to_admin_msg_id = None

    if message.reply_to_message:

        user_replied_to = (
            message.reply_to_message.message_id
        )

        lookup_key = (
            f"{user_id}_{user_replied_to}"
        )

        reply_to_admin_msg_id = (
            data["msg_map_u2a"].get(
                lookup_key
            )
        )

    try:

        # IMPORTANT:
        # User -> Admin uses FORWARD again.
        #
        # Therefore Admin can see:
        # "Forwarded from User"
        #
        # This is intentionally kept exactly as requested.

        forwarded = bot.forward_message(
            chat_id=ADMIN_ID,
            from_chat_id=chat_id,
            message_id=message_id
        )

        admin_forward_id = str(
            forwarded.message_id
        )

        # ----------------------------------------------------
        # DUAL MAPPINGS
        # ----------------------------------------------------

        data["reply_map"][
            admin_forward_id
        ] = user_id

        data["msg_map_a2u"][
            admin_forward_id
        ] = message_id

        data["msg_map_u2a"][
            f"{user_id}_{message_id}"
        ] = forwarded.message_id

        # ----------------------------------------------------
        # ALERT
        # ----------------------------------------------------

        if user_id in data["alerts"]:

            bot.send_message(
                ADMIN_ID,
                f"🚨 <b>ALERT: "
                f"Flagged User Active</b> "
                f"[<code>{user_id}</code>]",
                reply_to_message_id=(
                    forwarded.message_id
                )
            )

        save_data(data)

    except Exception as e:

        logging.error(
            f"Inbound routing error: {e}"
        )


# ============================================================
# MESSAGE EDIT SYNCHRONIZATION
# ============================================================

@bot.edited_message_handler(
    func=lambda message: True,
    content_types=SUPPORTED_TYPES
)
def handle_edits(message):

    chat_id = message.chat.id
    message_id = message.message_id

    data = load_data()

    # ========================================================
    # ADMIN EDIT
    # ========================================================

    if chat_id == ADMIN_ID:

        user_target_msg_id = data[
            "msg_map_a2u"
        ].get(
            str(message_id)
        )

        target_user = data[
            "reply_map"
        ].get(
            str(message_id)
        )

        if (
            user_target_msg_id
            and target_user
        ):

            try:

                bot.edit_message_text(
                    message.text,
                    int(target_user),
                    int(user_target_msg_id)
                )

            except Exception:
                pass

    # ========================================================
    # USER EDIT
    # ========================================================

    else:

        user_id = str(
            chat_id
        )

        admin_ref_id = data[
            "msg_map_u2a"
        ].get(
            f"{user_id}_{message_id}"
        )

        if admin_ref_id:

            try:

                bot.send_message(
                    ADMIN_ID,
                    "✏️ <b>[User Edited Message]:</b>\n"
                    f"{message.text}",
                    reply_to_message_id=int(
                        admin_ref_id
                    )
                )

            except Exception:
                pass


# ============================================================
# STARTUP
# ============================================================

def start_services():

    # Make sure protected user exists
    # even after a fresh database/redeploy.

    data = load_data()

    ensure_protected_user(
        data
    )

    save_data(data)

    logging.info(
        "Core Gateway Server Running..."
    )

    if PROTECTED_USER_ID:

        logging.info(
            f"Protected User ID: "
            f"{PROTECTED_USER_ID}"
        )

    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        start_services()

    except Exception as e:

        logging.exception(
            f"Fatal Service Error: {e}"
        )

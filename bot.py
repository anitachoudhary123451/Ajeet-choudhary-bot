import os
import json
import time
import logging
import threading
from threading import Lock
from flask import Flask
import telebot

# --- ENVIRONMENT & CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # Set Admin ID
DATA_FILE = "bot_data.json"
PROTECTED_USER_ID = os.getenv("PROTECTED_USER_ID", "").strip()

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set!")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
db_lock = Lock()

# --- WEB SERVER (KEEP-ALIVE) ---
app = Flask(__name__)

@app.route("/")
def home():
    return "⚡ Gateway Service Active ✅", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- DATABASE CORE ---
def empty_db():
    return {
        "users": {},          # {user_id: {"admin_msgs": [], "user_msgs": []}}
        "reply_map": {},      # admin_msg_id -> user_id
        "msg_map_a2u": {},    # admin_msg_id -> user_msg_id
        "msg_map_u2a": {},    # f"{user_id}_{user_msg_id}" -> admin_msg_id
        "blocked": [],
        "alerts": [],
        "selected_user": None
    }

def load_data():
    with db_lock:
        if not os.path.exists(DATA_FILE):
            return empty_db()
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in ["users", "reply_map", "msg_map_a2u", "msg_map_u2a", "blocked", "alerts"]:
                data.setdefault(k, {} if "map" in k or k == "users" else [])
            data.setdefault("selected_user", None)
            ensure_protected_user(data)
            return data
        except Exception as e:
            logging.error(f"DB Load Error: {e}")
            return empty_db()

def save_data(data):
    with db_lock:
        temp = DATA_FILE + ".tmp"
        try:
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp, DATA_FILE)
        except Exception as e:
            logging.error(f"DB Save Error: {e}")

def ensure_user(data, user_id):
    u_str = str(user_id)
    if u_str not in data["users"]:
        data["users"][u_str] = {"admin_msgs": [], "user_msgs": []}

def ensure_protected_user(data):
    if PROTECTED_USER_ID:
        ensure_user(data, PROTECTED_USER_ID)

SUPPORTED_TYPES = ["text", "photo", "video", "document", "audio", "voice", "sticker", "animation"]

# --- ADMIN DASHBOARD & COMMANDS ---

@bot.message_handler(commands=["start"])
def handle_start(message):
    chat_id = message.chat.id
    data = load_data()

    # 👑 ADMIN INTERFACE
    if chat_id == ADMIN_ID:
        selected = f"<code>{data['selected_user']}</code>" if data['selected_user'] else "⭕ <i>None (Manual/Reply Mode)</i>"
        
        panel = f"""🎛️ <b>CONTROL CONSOLE | ADMIN</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 <b>Focused Target:</b> {selected}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📡 <b>ROUTING & MESSAGING:</b>
• <b>Reply directly</b> to any forwarded message to quote-reply.
• <code>/select &lt;user_id&gt;</code> ── Lock focus to a specific user
• <code>/unselect</code> ──────────── Release locked focus
• <code>/dm &lt;id&gt; &lt;text&gt;</code> ──────── Send instant standalone message

🧹 <b>PURGE & DELETION:</b>
• <code>/clearall &lt;id&gt;</code> ──────── Delete ALL admin messages from user's chat
• <code>/purge &lt;id&gt;</code> ─────────── Wipe entire chat (both user and admin sides)
• <code>/resetdb</code> ────────────── Reset database and session logs

👥 <b>MANAGEMENT:</b>
• <code>/users</code> ──────────────── List all active users & status
• <code>/userprofile &lt;id&gt;</code> ───── Open user profile
• <code>/ban &lt;id&gt;</code> ────────────── Restrict user from contacting
• <code>/unban &lt;id&gt;</code> ──────────── Restore user access
• <code>/alert &lt;id&gt;</code> ──────────── Toggle priority/alert flag
━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
        bot.send_message(ADMIN_ID, panel)
        return

    # 👤 END USER WELCOME INTERFACE
    user_id = str(chat_id)
    if user_id in data["blocked"]:
        return

    ensure_user(data, user_id)
    save_data(data)

    welcome_text = """🔒 <b>ENCRYPTED SECURE CHANNEL</b>

<blockquote>Aapka direct communication session establish ho chuka hai. 

Aap yahan apna koi bhi message, photo, ya document bhej sakte hain. Hamaari team aapse isi chat me connect karegi.</blockquote>

💬 <i>Apna sandesh niche type karke send karein.</i>"""
    bot.send_message(chat_id, welcome_text)

@bot.message_handler(commands=["select"])
def select_user(message):
    if message.chat.id != ADMIN_ID: return
    try:
        user_id = message.text.split()[1]
    except IndexError:
        bot.send_message(ADMIN_ID, "⚠️ <b>Format:</b> <code>/select &lt;user_id&gt;</code>")
        return
    data = load_data()
    data["selected_user"] = str(user_id)
    save_data(data)
    bot.send_message(ADMIN_ID, f"🎯 <b>Focus Locked:</b> <code>{user_id}</code>. Messages without reply will be delivered here.")

@bot.message_handler(commands=["unselect"])
def unselect_user(message):
    if message.chat.id != ADMIN_ID: return
    data = load_data()
    data["selected_user"] = None
    save_data(data)
    bot.send_message(ADMIN_ID, "🎯 <b>Focus Released.</b> Manual/Reply mode active.")

@bot.message_handler(commands=["dm"])
def direct_message(message):
    if message.chat.id != ADMIN_ID: return
    try:
        parts = message.text.split(" ", 2)
        user_id, text = parts[1], parts[2]
    except IndexError:
        bot.send_message(ADMIN_ID, "⚠️ <b>Format:</b> <code>/dm &lt;user_id&gt; &lt;text&gt;</code>")
        return
    data = load_data()
    try:
        sent = bot.send_message(int(user_id), text)
        ensure_user(data, user_id)
        data["users"][str(user_id)]["admin_msgs"].append(sent.message_id)
        save_data(data)
        bot.send_message(ADMIN_ID, f"✅ <b>Sent to</b> <code>{user_id}</code>")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ <b>Delivery Error:</b> {e}")

@bot.message_handler(commands=["clearall"])
def clear_admin_messages(message):
    """Deletes all messages sent by Admin from the target user's chat."""
    if message.chat.id != ADMIN_ID: return
    try:
        user_id = message.text.split()[1]
    except IndexError:
        # Fallback to selected user if argument missing
        data = load_data()
        user_id = data.get("selected_user")
        if not user_id:
            bot.send_message(ADMIN_ID, "⚠️ <b>Format:</b> <code>/clearall &lt;user_id&gt;</code>")
            return

    data = load_data()
    user_str = str(user_id)
    if user_str not in data["users"]:
        bot.send_message(ADMIN_ID, "⚠️ No message history found for this user.")
        return

    admin_msgs = data["users"][user_str].get("admin_msgs", [])
    count = 0
    for msg_id in admin_msgs:
        try:
            bot.delete_message(chat_id=int(user_str), message_id=msg_id)
            count += 1
        except Exception:
            pass

    data["users"][user_str]["admin_msgs"] = []
    save_data(data)
    bot.send_message(ADMIN_ID, f"🧹 <b>Cleared:</b> {count} Admin messages deleted from <code>{user_str}</code>'s chat.")

@bot.message_handler(commands=["purge"])
def purge_chat(message):
    """Deletes both Admin and User messages from user chat and local logs."""
    if message.chat.id != ADMIN_ID: return
    try:
        user_id = message.text.split()[1]
    except IndexError:
        bot.send_message(ADMIN_ID, "⚠️ <b>Format:</b> <code>/purge &lt;user_id&gt;</code>")
        return

    data = load_data()
    user_str = str(user_id)
    if user_str not in data["users"]:
        bot.send_message(ADMIN_ID, "⚠️ User history not found.")
        return

    total = 0
    # Clean user msgs
    for msg_id in data["users"][user_str].get("user_msgs", []):
        try:
            bot.delete_message(chat_id=int(user_str), message_id=msg_id)
            total += 1
        except Exception: pass
    
    # Clean admin msgs
    for msg_id in data["users"][user_str].get("admin_msgs", []):
        try:
            bot.delete_message(chat_id=int(user_str), message_id=msg_id)
            total += 1
        except Exception: pass

    data["users"][user_str] = {"admin_msgs": [], "user_msgs": []}
    save_data(data)
    bot.send_message(ADMIN_ID, f"💥 <b>Purged:</b> {total} total messages cleared from <code>{user_str}</code>'s chat.")

@bot.message_handler(commands=["resetdb"])
def reset_database(message):
    if message.chat.id != ADMIN_ID: return
    data = empty_db()
    ensure_protected_user(data)
    save_data(data)
    bot.send_message(ADMIN_ID, "♻️ <b>Database Reset:</b> All state logs and mappings cleared.")

@bot.message_handler(commands=["users"])
def list_users(message):
    if message.chat.id != ADMIN_ID: return
    data = load_data()
    users_dict = data.get("users", {})
    if not users_dict:
        bot.send_message(ADMIN_ID, "👥 <b>No registered users found.</b>")
        return

    text = "📊 <b>USER DIRECTORY</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, u_id in enumerate(users_dict.keys(), 1):
        status = "⛔ [Banned]" if u_id in data["blocked"] else "🚨 [Flagged]" if u_id in data["alerts"] else "🟢 [Active]"
        text += f"{i}. <code>{u_id}</code> ── {status}\n"
    bot.send_message(ADMIN_ID, text)

@bot.message_handler(commands=["ban"])
def ban_user(message):
    if message.chat.id != ADMIN_ID: return
    try: user_id = message.text.split()[1]
    except IndexError:
        bot.send_message(ADMIN_ID, "⚠️ <b>Format:</b> <code>/ban &lt;user_id&gt;</code>"); return
    data = load_data()
    if user_id not in data["blocked"]:
        data["blocked"].append(user_id)
        save_data(data)
        bot.send_message(ADMIN_ID, f"⛔ User <code>{user_id}</code> is now blocked.")
    else:
        bot.send_message(ADMIN_ID, "⚠️ User is already blocked.")

@bot.message_handler(commands=["unban"])
def unban_user(message):
    if message.chat.id != ADMIN_ID: return
    try: user_id = message.text.split()[1]
    except IndexError:
        bot.send_message(ADMIN_ID, "⚠️ <b>Format:</b> <code>/unban &lt;user_id&gt;</code>"); return
    data = load_data()
    if user_id in data["blocked"]:
        data["blocked"].remove(user_id)
        save_data(data)
        bot.send_message(ADMIN_ID, f"✅ User <code>{user_id}</code> unblocked.")
    else:
        bot.send_message(ADMIN_ID, "⚠️ User is not blocked.")

@bot.message_handler(commands=["alert"])
def toggle_alert(message):
    if message.chat.id != ADMIN_ID: return
    try: user_id = message.text.split()[1]
    except IndexError:
        bot.send_message(ADMIN_ID, "⚠️ <b>Format:</b> <code>/alert &lt;user_id&gt;</code>"); return
    data = load_data()
    if user_id not in data["alerts"]:
        data["alerts"].append(user_id)
        save_data(data)
        bot.send_message(ADMIN_ID, f"🚨 Alert flag ADDED to <code>{user_id}</code>.")
    else:
        data["alerts"].remove(user_id)
        save_data(data)
        bot.send_message(ADMIN_ID, f"🏳️ Alert flag REMOVED from <code>{user_id}</code>.")


# --- USER PROFILE COMMAND ---

@bot.message_handler(commands=["userprofile"])
def user_profile(message):
    if message.chat.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(
            ADMIN_ID,
            "⚠️ <b>Format:</b> <code>/userprofile &lt;user_id&gt;</code>"
        )
        return

    user_id = parts[1].strip()

    if not user_id.lstrip("-").isdigit():
        bot.send_message(ADMIN_ID, "⚠️ Invalid Chat ID.")
        return

    data = load_data()

    if user_id not in data.get("users", {}):
        if user_id == PROTECTED_USER_ID:
            ensure_protected_user(data)
            save_data(data)
        else:
            bot.send_message(
                ADMIN_ID,
                f"⚠️ User <code>{user_id}</code> is not registered."
            )
            return

    u = data["users"].get(user_id, {})
    status = (
        "⛔ Banned" if user_id in data["blocked"]
        else "🚨 Alert" if user_id in data["alerts"]
        else "🟢 Active"
    )

    # tg://user?id=... opens the Telegram profile when supported by the client.
    link = f"tg://user?id={user_id}"

    text = (
        "👤 <b>USER PROFILE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Chat ID:</b> <code>{user_id}</code>\n"
        f"📊 <b>Status:</b> {status}\n"
        f"💬 <b>User Messages:</b> {len(u.get('user_msgs', []))}\n"
        f"📨 <b>Admin Messages:</b> {len(u.get('admin_msgs', []))}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f'🔗 <a href="{link}">OPEN TELEGRAM PROFILE</a>'
    )

    bot.send_message(
        ADMIN_ID,
        text,
        disable_web_page_preview=True
    )

# --- CORE ROUTING ENGINE & BIDIRECTIONAL NATIVE QUOTE REPLIES ---

@bot.message_handler(func=lambda message: True, content_types=SUPPORTED_TYPES)
def handle_all_messages(message):
    chat_id = message.chat.id
    message_id = message.message_id
    data = load_data()

    # ==============================================================
    # ADMIN -> USER
    # ==============================================================
    if chat_id == ADMIN_ID:
        target_user = None
        target_quote_id = None

        if message.reply_to_message:
            replied_admin_id = str(message.reply_to_message.message_id)

            # The replied admin-chat message belongs to this user.
            target_user = data["reply_map"].get(replied_admin_id)

            # Find the corresponding message in the user's chat.
            if target_user:
                target_quote_id = data["msg_map_a2u"].get(replied_admin_id)

        elif data.get("selected_user"):
            target_user = str(data["selected_user"])

        if not target_user:
            bot.send_message(
                ADMIN_ID,
                "⚠️ <b>Action Required:</b> Reply directly to a user's "
                "message, or use <code>/select &lt;user_id&gt;</code>."
            )
            return

        target_user = str(target_user)

        if target_user in data["blocked"]:
            bot.send_message(ADMIN_ID, "⛔ Delivery failed: User is blocked.")
            return

        try:
            args = {
                "chat_id": int(target_user),
                "from_chat_id": ADMIN_ID,
                "message_id": message_id
            }

            if target_quote_id:
                args["reply_to_message_id"] = int(target_quote_id)

            sent = bot.copy_message(**args)

            ensure_user(data, target_user)
            data["users"][target_user]["admin_msgs"].append(sent.message_id)

            admin_id = str(message_id)
            user_id = str(sent.message_id)

            data["reply_map"][admin_id] = target_user
            data["msg_map_a2u"][admin_id] = sent.message_id
            data["msg_map_u2a"][f"{target_user}_{user_id}"] = message_id

            save_data(data)

        except Exception as e:
            logging.error(f"Admin -> User routing error: {e}")
            bot.send_message(ADMIN_ID, f"❌ <b>Send Failed:</b> {e}")

        return

    # ==============================================================
    # USER -> ADMIN
    # ==============================================================
    user_id = str(chat_id)

    if user_id in data["blocked"]:
        return

    ensure_user(data, user_id)
    data["users"][user_id]["user_msgs"].append(message_id)

    reply_to_admin_msg_id = None

    if message.reply_to_message:
        replied_user_msg_id = message.reply_to_message.message_id
        lookup_key = f"{user_id}_{replied_user_msg_id}"
        reply_to_admin_msg_id = data["msg_map_u2a"].get(lookup_key)

    try:
        # copy_message instead of forward_message:
        # this removes the visible "Forwarded from" header/profile trace.
        args = {
            "chat_id": ADMIN_ID,
            "from_chat_id": chat_id,
            "message_id": message_id
        }

        # Native quote in Admin chat when User replied to an Admin message.
        if reply_to_admin_msg_id:
            args["reply_to_message_id"] = int(reply_to_admin_msg_id)

        copied = bot.copy_message(**args)
        admin_message_id = copied.message_id

        # Save both directions.
        data["reply_map"][str(admin_message_id)] = user_id
        data["msg_map_a2u"][str(admin_message_id)] = message_id
        data["msg_map_u2a"][f"{user_id}_{message_id}"] = admin_message_id

        if user_id in data["alerts"]:
            bot.send_message(
                ADMIN_ID,
                f"🚨 <b>ALERT: Flagged User Active</b> "
                f"[<code>{user_id}</code>]",
                reply_to_message_id=admin_message_id
            )

        save_data(data)

    except Exception as e:
        logging.error(f"Inbound routing error: {e}")


# --- BIDIRECTIONAL REACTION SYNCHRONIZATION ---
#
# Telegram sends reactions as Update.message_reaction / message_reaction_count
# updates, not as normal messages. We map each side's message ID to the
# corresponding message in the other chat and mirror the reaction there.
#
# NOTE:
# - The bot must have the required Telegram Bot API permissions/update support.
# - Reactions are synchronized by replacing the bot's own reaction on the
#   counterpart message.
# - This works for messages that were routed/copied after this feature was
#   deployed and for which the cross-chat mappings exist.

def _reaction_to_payload(reaction):
    """
    Convert a Telegram ReactionType object into the format accepted by
    set_message_reaction().
    """
    try:
        if reaction.type == "emoji":
            return {"type": "emoji", "emoji": reaction.emoji}
        if reaction.type == "custom_emoji":
            return {
                "type": "custom_emoji",
                "custom_emoji_id": reaction.custom_emoji_id
            }
    except Exception:
        pass
    return None


def _mirror_reaction_to_other_side(
    source_chat_id,
    source_message_id,
    reaction_items,
    is_user_side
):
    """
    Find the mapped counterpart message and mirror the reaction.

    We intentionally mirror only the reacting person's current reaction.
    Telegram's reaction update contains the 'old_reaction' and 'new_reaction',
    so removing an old reaction and applying a new one is supported.
    """
    data = load_data()

    source_message_id = int(source_message_id)

    if is_user_side:
        user_id = str(source_chat_id)
        counterpart = data["msg_map_u2a"].get(
            f"{user_id}_{source_message_id}"
        )
        target_chat_id = ADMIN_ID
    else:
        counterpart = data["msg_map_a2u"].get(str(source_message_id))

        # The admin-side message tells us which user owns it.
        target_user = data["reply_map"].get(str(source_message_id))
        if not target_user:
            return
        target_chat_id = int(target_user)

    if not counterpart:
        return

    # Clear the bot's previous mirrored reaction first.
    try:
        bot.set_message_reaction(
            chat_id=target_chat_id,
            message_id=int(counterpart),
            reaction=[]
        )
    except Exception as e:
        logging.warning(f"Could not clear mirrored reaction: {e}")

    # Apply the latest reaction.
    if not reaction_items:
        return

    # Telegram can return multiple reactions. Bot API lets the bot set its
    # own reaction(s), so mirror the first supported reaction.
    for item in reaction_items:
        payload = _reaction_to_payload(item)
        if not payload:
            continue

        try:
            bot.set_message_reaction(
                chat_id=target_chat_id,
                message_id=int(counterpart),
                reaction=[payload]
            )
            break
        except Exception as e:
            logging.warning(f"Could not mirror reaction: {e}")


# Newer pyTelegramBotAPI versions expose this update handler.
# We use a fallback registration style so the bot fails gracefully if the
# installed library is older and does not expose reaction decorators.
if hasattr(bot, "message_reaction_handler"):

    @bot.message_reaction_handler(func=lambda reaction: True)
    def handle_message_reaction(reaction):
        try:
            is_user = reaction.chat.id != ADMIN_ID

            # message_reaction contains the user's new reaction state.
            new_reaction = getattr(reaction, "new_reaction", None) or []

            _mirror_reaction_to_other_side(
                source_chat_id=reaction.chat.id,
                source_message_id=reaction.message_id,
                reaction_items=new_reaction,
                is_user_side=is_user
            )
        except Exception as e:
            logging.error(f"Reaction sync error: {e}")


# Count-only reaction updates are not needed for mirroring the reacting
# person's emoji, so no separate count handler is required.

# --- MESSAGE EDIT SYNCHRONIZATION ---

@bot.edited_message_handler(func=lambda message: True, content_types=SUPPORTED_TYPES)
def handle_edits(message):
    chat_id = message.chat.id
    message_id = message.message_id
    data = load_data()

    if chat_id == ADMIN_ID:
        user_target_msg_id = data["msg_map_a2u"].get(str(message_id))
        target_user = data["reply_map"].get(str(message_id))
        if user_target_msg_id and target_user:
            try:
                bot.edit_message_text(message.text, int(target_user), int(user_target_msg_id))
            except Exception: pass
    else:
        user_id = str(chat_id)
        admin_ref_id = data["msg_map_u2a"].get(f"{user_id}_{message_id}")
        if admin_ref_id:
            try:
                bot.send_message(ADMIN_ID, f"✏️ <b>[User Edited Message]:</b>\n{message.text}", reply_to_message_id=int(admin_ref_id))
            except Exception: pass

# --- APP STARTUP ---

def start_services():
    data = load_data()
    ensure_protected_user(data)
    save_data(data)

    threading.Thread(target=run_flask, daemon=True).start()
    logging.info("Core Gateway Server Running...")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)

if __name__ == "__main__":
    try:
        start_services()
    except Exception as e:
        logging.exception(f"Fatal Service Error: {e}")

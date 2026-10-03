import os
import json
import time
import random
import hashlib
import sqlite3
import requests
import telebot
from telebot import types
from datetime import datetime, timedelta

# ================= CONFIG =================
TOKEN          = os.getenv("BOT_TOKEN", "8862072402:AAG2T5KXVsaqSQPsQ25sj-HkClBExDVz7Jk")
ADMIN_USERNAME = "Minhlecutephomaique"      # admin duy nhất
API_URL        = "https://wtxmd52.tele68.com/v1/txmd5/sessions"
PROXY          = "https://api.allorigins.win/raw?url="
DB_FILE        = "bot_data.db"
BRAND          = "LE MINH TOOL — TOOL LÀM GIÀU KIẾM LÚA 🦀"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ================= DATABASE =================
def db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id      INTEGER PRIMARY KEY,
        username     TEXT,
        full_name    TEXT,
        balance      INTEGER DEFAULT 0,
        key_expire   TEXT,
        is_banned    INTEGER DEFAULT 0,
        created_at   TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS keys(
        code         TEXT PRIMARY KEY,
        hours        INTEGER,
        max_uses     INTEGER DEFAULT 1,
        used_count   INTEGER DEFAULT 0,
        created_at   TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS history(
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER,
        prediction   TEXT,
        confidence   REAL,
        created_at   TEXT
    )""")
    conn.commit(); conn.close()

init_db()

# ================= HELPERS =================
def get_user(uid):
    conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    row = c.fetchone()
    conn.close()
    return row

def ensure_user(message):
    uid  = message.from_user.id
    uname = message.from_user.username or ""
    name  = message.from_user.full_name or ""
    conn = db(); c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if not c.fetchone():
        c.execute("INSERT INTO users(user_id,username,full_name,balance,created_at) VALUES(?,?,?,?,?)",
                  (uid, uname, name, 0, datetime.now().isoformat()))
    else:
        c.execute("UPDATE users SET username=?,full_name=? WHERE user_id=?", (uname, name, uid))
    conn.commit(); conn.close()

def is_admin(message):
    return (message.from_user.username or "").lower() == ADMIN_USERNAME.lower()

def key_valid(row):
    if not row or not row["key_expire"]:
        return False
    try:
        return datetime.fromisoformat(row["key_expire"]) > datetime.now()
    except:
        return False

def fmt_remain(expire_str):
    if not expire_str: return "Hết hạn"
    try:
        exp = datetime.fromisoformat(expire_str)
        d = exp - datetime.now()
        if d.total_seconds() <= 0: return "Đã hết hạn"
        h, r = divmod(int(d.total_seconds()), 3600)
        m = r // 60
        return f"{h}h {m}p"
    except: return "Hết hạn"

def add_balance(uid, amount):
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    conn.commit(); conn.close()

def grant_key(uid, hours):
    exp = datetime.now() + timedelta(hours=hours)
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET key_expire=? WHERE user_id=?", (exp.isoformat(), uid))
    conn.commit(); conn.close()
    return exp

def ban_user(uid, reason=""):
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (uid,))
    conn.commit(); conn.close()

def unban_user(uid):
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,))
    conn.commit(); conn.close()

# ================= API =================
def fetch_history():
    try:
        r = requests.get(API_URL, timeout=15)
        data = r.json()
        if "list" in data and data["list"]:
            return data
        # fallback proxy
        r = requests.get(PROXY + API_URL, timeout=20)
        return r.json()
    except Exception as e:
        print("API error:", e)
        return None

# ================= THUẬT TOÁN DỰ ĐOÁN =================
def predict_md5(history_results):
    """
    history_results: list TAI/XIU mới nhất (index 0 là mới nhất)
    Kết hợp MD5 + SHA256 (hash-64) + phân tích streak/pattern
    """
    if len(history_results) < 5:
        return "TAI", 50.0

    # ----- Hash seed -----
    data_str = "|".join(history_results[:60])
    md5_h    = hashlib.md5(data_str.encode()).hexdigest()
    sha_h    = hashlib.sha256(data_str.encode()).hexdigest()      # hash 64 ký tự
    seed     = int(md5_h[:8], 16) ^ int(sha_h[:8], 16) ^ int(sha_h[8:16], 16)
    rng      = random.Random(seed)

    # ----- Phân tích thống kê -----
    tai = history_results.count("TAI")
    xiu = history_results.count("XIU")
    total = len(history_results)

    # streak
    streak = 1
    for i in range(1, total):
        if history_results[i] == history_results[0]:
            streak += 1
        else:
            break

    # cầu 1-1 (alternating)
    alt = all(history_results[i] != history_results[i+1] for i in range(min(4, total-1)))

    # ----- Chấm điểm -----
    score_tai = 0; score_xiu = 0
    if tai > xiu:   score_tai += (tai - xiu)
    elif xiu > tai: score_xiu += (xiu - tai)

    if streak >= 3:
        # bẻ cầu
        if history_results[0] == "TAI": score_xiu += streak
        else:                            score_tai += streak
    if alt:
        # cầu 1-1 → đảo
        if history_results[0] == "TAI": score_xiu += 2
        else:                            score_tai += 2

    # hash vote
    hv = rng.randint(0, 9)
    if hv % 2 == 0: score_tai += 1
    else:           score_xiu += 1

    prediction = "TAI" if score_tai >= score_xiu else "XIU"

    # ----- Độ tin cậy -----
    gap = abs(score_tai - score_xiu)
    base = min(50 + gap * 3, 95)
    base += rng.uniform(-5, 5)
    base = max(50, min(base, 99))

    # phân tầng theo yêu cầu
    if base < 60:
        confidence = round(rng.uniform(50, 60), 2)
    elif base < 70:
        confidence = round(rng.uniform(60, 70), 2)
    else:
        confidence = round(rng.uniform(70, min(base + 5, 99)), 2)

    return prediction, confidence

def rate_label(conf):
    if conf < 60: return "Trung bình 🟡"
    if conf < 70: return "Cao 🟢"
    return "Rất cao 🔥"

# ================= MENUS =================
def main_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🦀 Lắc Cua", callback_data="laucua"),
        types.InlineKeyboardButton("🔑 Nhập Key", callback_data="enterkey"),
    )
    kb.add(
        types.InlineKeyboardButton("💰 Nạp Tiền", callback_data="nap"),
        types.InlineKeyboardButton("👤 Tài Khoản", callback_data="account"),
    )
    kb.add(
        types.InlineKeyboardButton("📊 Lịch Sử", callback_data="history"),
        types.InlineKeyboardButton("☎️ Admin", url=f"https://t.me/{ADMIN_USERNAME}"),
    )
    return kb

def game_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    games = ["Sunwin","Hitclub","B52","LC79","Betvip","789 Club",
             "IWIN","Max789","Luck8","TA28","Son789","Rikvip",
             "68 Game Bài","OGK Fan"]
    btns = [types.InlineKeyboardButton(g, callback_data=f"game|{g}") for g in games]
    kb.add(*btns)
    kb.add(types.InlineKeyboardButton("🏠 Về Trang Chủ", callback_data="home"))
    return kb

def back_menu():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Quay lại", callback_data="home"))
    return kb

# ================= COMMANDS =================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    ensure_user(message)
    text = (
        f"🦀 <b>{BRAND}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 Xin chào <b>{message.from_user.full_name}</b>\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡️ Tool dự đoán Tài/Xỉu MD5-HASH\n"
        f"🔑 Nhập key để sử dụng tool\n"
        f"📞 Admin: @{ADMIN_USERNAME}\n\n"
        f"👉 Chọn chức năng bên dưới:"
    )
    bot.send_message(message.chat.id, text, reply_markup=main_menu())

@bot.message_handler(commands=["laucua"])
def cmd_laucua(message):
    ensure_user(message)
    do_laucua(message.chat.id, message.from_user.id)

@bot.message_handler(commands=["key"])
def cmd_key(message):
    ensure_user(message)
    bot.send_message(message.chat.id,
        "🔑 <b>NHẬP KEY</b>\nGửi key theo cú pháp:\n<code>/key ma_key_cua_ban</code>")

@bot.message_handler(commands=["nap"])
def cmd_nap(message):
    ensure_user(message)
    show_nap(message.chat.id)

@bot.message_handler(commands=["ban"])
def cmd_ban(message):
    if not is_admin(message):
        bot.reply_to(message, "❌ Bạn không có quyền."); return
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "Cú pháp: <code>/ban [ID] [lý do]</code>"); return
    try:
        uid = int(parts[1])
    except:
        bot.reply_to(message, "ID không hợp lệ."); return
    reason = " ".join(parts[2:])
    ban_user(uid, reason)
    bot.reply_to(message, f"✅ Đã ban <code>{uid}</code>\nLý do: {reason}")
    try: bot.send_message(uid, f"🚫 Bạn đã bị ban.\nLý do: {reason}")
    except: pass

@bot.message_handler(commands=["unban"])
def cmd_unban(message):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) < 2: return
    unban_user(int(parts[1]))
    bot.reply_to(message, f"✅ Đã unban <code>{parts[1]}</code>")

@bot.message_handler(commands=["addmoney"])
def cmd_addmoney(message):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) < 3: return
    uid, amt = int(parts[1]), int(parts[2])
    add_balance(uid, amt)
    bot.reply_to(message, f"✅ Đã cộng {amt:,}đ cho <code>{uid}</code>")

@bot.message_handler(commands=["addkey"])
def cmd_addkey(message):
    """Admin: /addkey <hours> <số_lượng>"""
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) < 3: return
    hours, qty = int(parts[1]), int(parts[2])
    codes = []
    conn = db(); c = conn.cursor()
    for _ in range(qty):
        code = "key" + hashlib.md5(os.urandom(8)).hexdigest()[:10]
        c.execute("INSERT INTO keys(code,hours,created_at) VALUES(?,?,?)",
                  (code, hours, datetime.now().isoformat()))
        codes.append(code)
    conn.commit(); conn.close()
    bot.reply_to(message, "🔑 Keys mới:\n" + "\n".join(codes))

@bot.message_handler(commands=["grantkey"])
def cmd_grantkey(message):
    """Admin: /grantkey <user_id> <hours>"""
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) < 3: return
    uid, hours = int(parts[1]), int(parts[2])
    grant_key(uid, hours)
    bot.reply_to(message, f"✅ Đã cấp key {hours}h cho <code>{uid}</code>")

# ================= KEY MESSAGE =================
@bot.message_handler(func=lambda m: m.text and m.text.startswith("/key "))
def handle_key_input(message):
    ensure_user(message)
    code = message.text.split(maxsplit=1)[1].strip()
    conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE code=?", (code,))
    k = c.fetchone()
    if not k:
        bot.reply_to(message, "❌ Key không tồn tại."); conn.close(); return
    if k["used_count"] >= k["max_uses"]:
        bot.reply_to(message, "❌ Key đã hết lượt."); conn.close(); return
    c.execute("UPDATE keys SET used_count = used_count + 1 WHERE code=?", (code,))
    conn.commit(); conn.close()
    exp = grant_key(message.from_user.id, k["hours"])
    bot.reply_to(message,
        f"✅ <b>Kích hoạt thành công!</b>\n"
        f"⏱ Hạn: <b>{k['hours']} giờ</b>\n"
        f"📅 Hết hạn: {exp.strftime('%d/%m/%Y %H:%M')}")

# ================= LAUCUA LOGIC =================
def do_laucua(chat_id, uid):
    row = get_user(uid)
    if row and row["is_banned"]:
        bot.send_message(chat_id, "🚫 Bạn đã bị ban."); return

    if not key_valid(row):
        bot.send_message(chat_id,
            "🔒 <b>Bạn chưa có key còn hạn.</b>\n"
            "Vui lòng nạp tiền mua key:\n"
            "📞 Admin @" + ADMIN_USERNAME)
        show_nap(chat_id)
        return

    msg = bot.send_message(chat_id, "⏳ Đang phân tích MD5 + HASH 64...")
    data = fetch_history()
    if not data or not data.get("list"):
        bot.edit_message_text("❌ Không lấy được dữ liệu API, thử lại sau.",
                              chat_id, msg.message_id); return

    history = [x["resultTruyenThong"] for x in data["list"]]
    prediction, conf = predict_md5(history)

    # lưu lịch sử
    conn = db(); c = conn.cursor()
    c.execute("INSERT INTO history(user_id,prediction,confidence,created_at) VALUES(?,?,?,?)",
              (uid, prediction, conf, datetime.now().isoformat()))
    conn.commit(); conn.close()

    icon = "🔴" if prediction == "TAI" else "🔵"
    last5 = " - ".join(history[:5])
    text = (
        f"🦀 <b>LE MINH TOOL — KẾT QUẢ DỰ ĐOÁN</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{icon} Dự đoán: <b>{prediction}</b>\n"
        f"🎯 Độ tin cậy: <b>{conf}%</b> — {rate_label(conf)}\n"
        f"📊 Thuật toán: MD5 + SHA256 (Hash-64)\n"
        f"🕐 5 phiên gần nhất: <code>{last5}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>Chỉ mang tính tham khảo, tự chịu trách nhiệm.</i>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔄 Lắc lại", callback_data="laucua"))
    bot.edit_message_text(text, chat_id, msg.message_id, reply_markup=kb)

def show_nap(chat_id):
    text = (
        "🏦 <b>NẠP TIỀN MUA KEY</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🏛 Ngân hàng: <b>MBBANK</b>\n"
        "💳 Số TK: <code>0372834763</code>\n"
        "👤 Chủ TK: <b>LE HOANG MINH</b>\n"
        "📝 Nội dung: <b>SĐT Telegram</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💎 <b>BẢNG GIÁ:</b>\n"
        "├ 1 Giờ    → 3.000đ\n"
        "├ 1 Ngày   → 10.000đ\n"
        "├ 4 Ngày   → 30.000đ\n"
        "├ 1 Tuần   → 50.000đ\n"
        "├ 1 Tháng  → 80.000đ\n"
        "└ Vĩnh viễn → Liên hệ\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📞 Gửi bill: <code>0372834763</code>\n"
        f"☎️ Admin: @{ADMIN_USERNAME}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💬 Zalo Admin", url=f"https://t.me/{ADMIN_USERNAME}"))
    bot.send_message(chat_id, text, reply_markup=kb)

# ================= CALLBACKS =================
@bot.callback_query_handler(func=lambda c: True)
def on_cb(call):
    data = call.data
    uid = call.from_user.id
    ensure_user(call)

    if data == "home":
        bot.edit_message_text(
            f"🦀 <b>{BRAND}</b>\nChọn chức năng:",
            call.message.chat.id, call.message.message_id,
            reply_markup=main_menu())

    elif data == "laucua":
        bot.answer_callback_query(call.id, "Đang phân tích...")
        do_laucua(call.message.chat.id, uid)

    elif data == "enterkey":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id,
            "🔑 Gửi key theo cú pháp:\n<code>/key ma_key</code>")

    elif data == "nap":
        bot.answer_callback_query(call.id)
        show_nap(call.message.chat.id)

    elif data == "account":
        row = get_user(uid)
        bal = row["balance"] if row else 0
        expire = fmt_remain(row["key_expire"]) if row else "Chưa có"
        status = "🔴 Banned" if (row and row["is_banned"]) else "🟢 Hoạt động"
        bot.edit_message_text(
            f"👤 <b>TÀI KHOẢN</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"💵 Số dư: <b>{bal:,}đ</b>\n"
            f"🔑 Key còn: <b>{expire}</b>\n"
            f"📶 Trạng thái: {status}",
            call.message.chat.id, call.message.message_id,
            reply_markup=back_menu())

    elif data == "history":
        conn = db(); c = conn.cursor()
        c.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
        rows = c.fetchall(); conn.close()
        if not rows:
            txt = "📭 Chưa có lịch sử dự đoán."
        else:
            txt = "📊 <b>10 LẦN DỰ ĐOÁN GẦN NHẤT</b>\n━━━━━━━━━━━━━━━━━━\n"
            for r in rows:
                txt += f"• {r['prediction']} — {r['confidence']}% ({r['created_at'][11:16]})\n"
        bot.edit_message_text(txt, call.message.chat.id, call.message.message_id,
                              reply_markup=back_menu())

    elif data.startswith("game|"):
        game = data.split("|", 1)[1]
        bot.answer_callback_query(call.id, f"Đã chọn {game}")
        bot.send_message(call.message.chat.id,
            f"🎮 Nền tảng: <b>{game}</b>\nDùng /laucua để dự đoán.",
            reply_markup=back_menu())

# ================= RUN =================
if __name__ == "__main__":
    print(f"🦀 {BRAND} — Bot đang chạy...")
    bot.infinity_polling(timeout=30, long_polling_timeout=25)

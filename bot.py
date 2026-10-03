import os
import json
import time
import random
import hashlib
import sqlite3
import threading
import requests
import telebot
from telebot import types
from datetime import datetime, timedelta

# ================= CONFIG =================
TOKEN          = os.getenv("BOT_TOKEN", "8862072402:AAG2T5KXVsaqSQPsQ25sj-HkClBExDVz7Jk")
ADMIN_USERNAME = "Minhlecutephomaique"
API_URL        = "https://wtxmd52.tele68.com/v1/txmd5/sessions"
PROXY          = "https://api.allorigins.win/raw?url="
DB_FILE        = "bot_data.db"
BRAND          = "LE MINH TOOL — TOOL LÀM GIÀU KIẾM LÚA 🦀"
CHECK_INTERVAL = 60   # giây — chu kỳ quét key hết hạn

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ================= DATABASE =================
def db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id      INTEGER PRIMARY KEY,
        username     TEXT,
        full_name    TEXT,
        balance      INTEGER DEFAULT 0,
        key_expire   TEXT,               -- ISO timestamp | NULL
        notified     INTEGER DEFAULT 0,  -- đã thông báo hết hạn chưa
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
    row = c.fetchone(); conn.close()
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

# --- Kiểm tra key theo thời gian thực ---
def key_status(row):
    """Trả về (còn_hạn: bool, chuỗi_hiển_thị, giây_còn_lại)"""
    if not row or not row["key_expire"]:
        return False, "Chưa có key", 0
    try:
        exp = datetime.fromisoformat(row["key_expire"])
    except:
        return False, "Key lỗi", 0
    remain = (exp - datetime.now()).total_seconds()
    if remain <= 0:
        return False, "Đã hết hạn", 0
    d = int(remain)
    h, r = divmod(d, 3600)
    m, s = divmod(r, 60)
    if h > 24:
        day, h = divmod(h, 24)
        txt = f"{day} ngày {h}h"
    elif h > 0:
        txt = f"{h}h {m}p"
    else:
        txt = f"{m}p {s}s"
    return True, txt, d

def add_balance(uid, amount):
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    conn.commit(); conn.close()

def grant_key(uid, hours):
    """Cộng dồn nếu còn hạn, reset nếu hết hạn."""
    row = get_user(uid)
    now = datetime.now()
    base = now
    if row and row["key_expire"]:
        try:
            old = datetime.fromisoformat(row["key_expire"])
            if old > now:
                base = old
        except: pass
    exp = base + timedelta(hours=hours)
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET key_expire=?, notified=0 WHERE user_id=?",
              (exp.isoformat(), uid))
    conn.commit(); conn.close()
    return exp

def ban_user(uid): 
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (uid,))
    conn.commit(); conn.close()

def unban_user(uid):
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,))
    conn.commit(); conn.close()

# ================= BACKGROUND WATCHER =================
def key_watcher():
    """
    Chạy nền 24/7:
    - Mỗi 60s quét user có key_expire <= now và notified=0
    - Gửi tin nhắn báo hết hạn
    - Đánh dấu notified=1 để không spam
    """
    while True:
        try:
            conn = db(); c = conn.cursor()
            now_iso = datetime.now().isoformat()
            c.execute("""SELECT user_id, username FROM users
                         WHERE key_expire IS NOT NULL
                           AND key_expire <= ?
                           AND notified = 0
                           AND is_banned = 0""", (now_iso,))
            expired = c.fetchall()

            for row in expired:
                uid = row["user_id"]
                try:
                    bot.send_message(
                        uid,
                        "🔒 <b>KEY KHÔNG CÒN HOẠT ĐỘNG</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        "⏰ Key của bạn đã <b>hết hạn</b>.\n"
                        "Vui lòng nạp tiền gia hạn để tiếp tục dùng tool.\n\n"
                        "💰 Gõ /nap để xem bảng giá\n"
                        f"☎️ Admin: @{ADMIN_USERNAME}"
                    )
                except Exception as e:
                    print(f"[watcher] Gửi tin thất bại cho {uid}: {e}")
                # đánh dấu đã thông báo
                c.execute("UPDATE users SET notified=1 WHERE user_id=?", (uid,))
                print(f"[watcher] Báo hết hạn -> {uid}")

            conn.commit(); conn.close()
        except Exception as e:
            print(f"[watcher] Lỗi: {e}")
        time.sleep(CHECK_INTERVAL)

# ================= API =================
def fetch_history():
    try:
        r = requests.get(API_URL, timeout=15)
        d = r.json()
        if d.get("list"): return d
        r = requests.get(PROXY + API_URL, timeout=20)
        return r.json()
    except Exception as e:
        print("API error:", e)
        return None

# ================= THUẬT TOÁN =================
def predict_md5(history_results):
    if len(history_results) < 5:
        return "TAI", 50.0

    data_str = "|".join(history_results[:60])
    md5_h    = hashlib.md5(data_str.encode()).hexdigest()
    sha_h    = hashlib.sha256(data_str.encode()).hexdigest()
    seed     = int(md5_h[:8], 16) ^ int(sha_h[:8], 16) ^ int(sha_h[8:16], 16)
    rng      = random.Random(seed)

    tai = history_results.count("TAI")
    xiu = history_results.count("XIU")
    total = len(history_results)

    streak = 1
    for i in range(1, total):
        if history_results[i] == history_results[0]:
            streak += 1
        else:
            break

    alt = all(history_results[i] != history_results[i+1] for i in range(min(4, total-1)))

    s_tai = 0; s_xiu = 0
    if tai > xiu:   s_tai += (tai - xiu)
    elif xiu > tai: s_xiu += (xiu - tai)

    if streak >= 3:
        if history_results[0] == "TAI": s_xiu += streak
        else:                            s_tai += streak
    if alt:
        if history_results[0] == "TAI": s_xiu += 2
        else:                            s_tai += 2

    if rng.randint(0, 9) % 2 == 0: s_tai += 1
    else:                           s_xiu += 1

    prediction = "TAI" if s_tai >= s_xiu else "XIU"
    gap = abs(s_tai - s_xiu)
    base = min(50 + gap * 3, 95) + rng.uniform(-5, 5)
    base = max(50, min(base, 99))

    if base < 60:   conf = round(rng.uniform(50, 60), 2)
    elif base < 70: conf = round(rng.uniform(60, 70), 2)
    else:           conf = round(rng.uniform(70, min(base+5, 99)), 2)

    return prediction, conf

def rate_label(c):
    if c < 60: return "Trung bình 🟡"
    if c < 70: return "Cao 🟢"
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

def back_menu():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Quay lại", callback_data="home"))
    return kb

# ================= START =================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    ensure_user(message)
    row = get_user(message.from_user.id)
    ok, remain, _ = key_status(row)
    key_line = f"✅ Còn hạn: <b>{remain}</b>" if ok else f"🔒 Key: <b>{remain}</b>"

    bot.send_message(message.chat.id,
        f"🦀 <b>{BRAND}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{message.from_user.full_name}</b>\n"
        f"🆔 <code>{message.from_user.id}</code>\n"
        f"🔑 {key_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Tool dự đoán Tài/Xỉu MD5-HASH\n"
        f"📞 Admin: @{ADMIN_USERNAME}",
        reply_markup=main_menu())

# ================= LAUCUA =================
@bot.message_handler(commands=["laucua"])
def cmd_laucua(message):
    ensure_user(message)
    do_laucua(message.chat.id, message.from_user.id)

def do_laucua(chat_id, uid):
    row = get_user(uid)
    if row and row["is_banned"]:
        bot.send_message(chat_id, "🚫 Bạn đã bị ban."); return

    ok, remain, _ = key_status(row)
    if not ok:
        bot.send_message(chat_id,
            f"🔒 <b>KEY KHÔNG CÒN HOẠT ĐỘNG</b>\n"
            f"Trạng thái: <b>{remain}</b>\n\n"
            f"💰 Gõ /nap để gia hạn key.")
        return

    msg = bot.send_message(chat_id, "⏳ Đang phân tích MD5 + HASH 64...")
    data = fetch_history()
    if not data or not data.get("list"):
        bot.edit_message_text("❌ Không lấy được dữ liệu API.", chat_id, msg.message_id)
        return

    history = [x["resultTruyenThong"] for x in data["list"]]
    prediction, conf = predict_md5(history)

    conn = db(); c = conn.cursor()
    c.execute("INSERT INTO history(user_id,prediction,confidence,created_at) VALUES(?,?,?,?)",
              (uid, prediction, conf, datetime.now().isoformat()))
    conn.commit(); conn.close()

    icon = "🔴" if prediction == "TAI" else "🔵"
    last5 = " - ".join(history[:5])
    text = (
        f"🦀 <b>LE MINH TOOL — KẾT QUẢ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{icon} Dự đoán: <b>{prediction}</b>\n"
        f"🎯 Độ tin cậy: <b>{conf}%</b> — {rate_label(conf)}\n"
        f"📊 Thuật toán: MD5 + SHA256 (Hash-64)\n"
        f"🕐 5 phiên gần: <code>{last5}</code>\n"
        f"⏳ Key còn: <b>{remain}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>Chỉ mang tính tham khảo.</i>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔄 Lắc lại", callback_data="laucua"))
    bot.edit_message_text(text, chat_id, msg.message_id, reply_markup=kb)

# ================= NAP =================
@bot.message_handler(commands=["nap"])
def cmd_nap(message):
    ensure_user(message); show_nap(message.chat.id)

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
        f"☎️ Admin: @{ADMIN_USERNAME}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💬 Liên hệ Admin", url=f"https://t.me/{ADMIN_USERNAME}"))
    bot.send_message(chat_id, text, reply_markup=kb)

# ================= KEY INPUT =================
@bot.message_handler(commands=["key"])
def cmd_key(message):
    ensure_user(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "🔑 Cú pháp: <code>/key ma_key_cua_ban</code>"); return

    code = parts[1].strip()
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
        f"✅ <b>KÍCH HOẠT THÀNH CÔNG</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏱ Thời lượng: <b>{k['hours']} giờ</b>\n"
        f"📅 Hết hạn lúc: <b>{exp.strftime('%d/%m/%Y %H:%M:%S')}</b>\n"
        f"💡 Key đếm theo thời gian thực — hết hạn là dừng.")

# ================= ADMIN =================
@bot.message_handler(commands=["ban"])
def cmd_ban(message):
    if not is_admin(message):
        bot.reply_to(message, "❌ Không có quyền."); return
    p = message.text.split()
    if len(p) < 3:
        bot.reply_to(message, "Cú pháp: <code>/ban [ID] [lý do]</code>"); return
    try: uid = int(p[1])
    except: bot.reply_to(message, "ID sai."); return
    ban_user(uid)
    reason = " ".join(p[2:])
    bot.reply_to(message, f"✅ Đã ban <code>{uid}</code>\nLý do: {reason}")
    try: bot.send_message(uid, f"🚫 Bạn đã bị ban.\nLý do: {reason}")
    except: pass

@bot.message_handler(commands=["unban"])
def cmd_unban(message):
    if not is_admin(message): return
    p = message.text.split()
    if len(p) < 2: return
    unban_user(int(p[1]))
    bot.reply_to(message, f"✅ Unban <code>{p[1]}</code>")

@bot.message_handler(commands=["addmoney"])
def cmd_addmoney(message):
    if not is_admin(message): return
    p = message.text.split()
    if len(p) < 3: return
    uid, amt = int(p[1]), int(p[2])
    add_balance(uid, amt)
    bot.reply_to(message, f"✅ +{amt:,}đ cho <code>{uid}</code>")

@bot.message_handler(commands=["addkey"])
def cmd_addkey(message):
    """Admin: /addkey <giờ> <số_lượng>"""
    if not is_admin(message): return
    p = message.text.split()
    if len(p) < 3: return
    hours, qty = int(p[1]), int(p[2])
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
    """Admin: /grantkey <user_id> <giờ>"""
    if not is_admin(message): return
    p = message.text.split()
    if len(p) < 3: return
    uid, hours = int(p[1]), int(p[2])
    exp = grant_key(uid, hours)
    bot.reply_to(message, f"✅ Cấp {hours}h cho <code>{uid}</code>\nHết hạn: {exp.strftime('%d/%m/%Y %H:%M')}")

@bot.message_handler(commands=["checkkey"])
def cmd_checkkey(message):
    """Admin: /checkkey <user_id> — xem key user còn bao lâu"""
    if not is_admin(message): return
    p = message.text.split()
    if len(p) < 2:
        bot.reply_to(message, "Cú pháp: <code>/checkkey [user_id]</code>"); return
    uid = int(p[1])
    row = get_user(uid)
    if not row:
        bot.reply_to(message, "❌ User chưa tồn tại."); return
    ok, remain, _ = key_status(row)
    bot.reply_to(message,
        f"👤 User: <code>{uid}</code>\n"
        f"🔑 Key: {'✅ Còn hạn' if ok else '🔒 ' + remain}\n"
        f"⏱ Còn lại: <b>{remain}</b>\n"
        f"📅 Hết hạn: {row['key_expire'] or '---'}")

# ================= CALLBACKS =================
@bot.callback_query_handler(func=lambda c: True)
def on_cb(call):
    data = call.data
    uid = call.from_user.id
    ensure_user(call)
    row = get_user(uid)

    if data == "home":
        ok, remain, _ = key_status(row)
        key_line = f"✅ Còn hạn: <b>{remain}</b>" if ok else f"🔒 Key: <b>{remain}</b>"
        bot.edit_message_text(
            f"🦀 <b>{BRAND}</b>\n"
            f"🔑 {key_line}\n\nChọn chức năng:",
            call.message.chat.id, call.message.message_id, reply_markup=main_menu())

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
        ok, remain, _ = key_status(row)
        bal = row["balance"] if row else 0
        status = "🔴 Banned" if (row and row["is_banned"]) else "🟢 Hoạt động"
        bot.edit_message_text(
            f"👤 <b>TÀI KHOẢN</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <code>{uid}</code>\n"
            f"💵 Số dư: <b>{bal:,}đ</b>\n"
            f"🔑 Key: {'✅ Còn hạn <b>'+remain+'</b>' if ok else '🔒 '+remain}\n"
            f"📅 Hết hạn: {row['key_expire'] if row and row['key_expire'] else '---'}\n"
            f"📶 {status}",
            call.message.chat.id, call.message.message_id, reply_markup=back_menu())

    elif data == "history":
        conn = db(); c = conn.cursor()
        c.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
        rows = c.fetchall(); conn.close()
        if not rows:
            txt = "📭 Chưa có lịch sử."
        else:
            txt = "📊 <b>10 LẦN GẦN NHẤT</b>\n━━━━━━━━━━━━━━━━━━\n"
            for r in rows:
                txt += f"• {r['prediction']} — {r['confidence']}% ({r['created_at'][11:16]})\n"
        bot.edit_message_text(txt, call.message.chat.id, call.message.message_id,
                              reply_markup=back_menu())

# ================= RUN =================
if __name__ == "__main__":
    # Bật thread nền trước
    t = threading.Thread(target=key_watcher, daemon=True)
    t.start()
    print(f"🦀 {BRAND} — Bot đang chạy... (watcher: {CHECK_INTERVAL}s/lần)")
    bot.infinity_polling(timeout=30, long_polling_timeout=25)

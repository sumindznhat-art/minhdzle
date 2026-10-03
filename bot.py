import os
import re
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
TOKEN          = os.getenv("BOT_TOKEN")
ADMIN_USERNAME = "Minhlecutephomaique"
API_URL        = "https://wtxmd52.tele68.com/v1/txmd5/sessions"
PROXY          = "https://api.allorigins.win/raw?url="
DB_FILE        = "bot_data.db"
BRAND          = "LE MINH TOOL — TOOL LÀM GIÀU KIẾM LÚA 🦀"
CHECK_INTERVAL = 30
IMAGE_URL      = "https://raw.githubusercontent.com/sumindznhat-ari/minhdzle/main/vietqr.jpg"

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
        key_expire   TEXT,
        notified     INTEGER DEFAULT 0,
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
        session_id   INTEGER,
        prediction   TEXT,
        confidence   REAL,
        actual       TEXT,
        is_correct   INTEGER DEFAULT -1,
        notified     INTEGER DEFAULT 0,
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

def find_user_by_username(username):
    conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE LOWER(username)=?", (username.lower().lstrip("@"),))
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

def is_admin_id(uid):
    row = get_user(uid)
    if not row: return False
    return (row["username"] or "").lower() == ADMIN_USERNAME.lower()

def key_status(row):
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

def gen_key_code():
    return "key" + hashlib.md5(os.urandom(8)).hexdigest()[:10]

# ================= BACKGROUND WATCHER (KEY + PHIÊN) =================
def key_watcher():
    """Báo key hết hạn"""
    while True:
        try:
            conn = db(); c = conn.cursor()
            now_iso = datetime.now().isoformat()
            c.execute("""SELECT user_id FROM users
                         WHERE key_expire IS NOT NULL
                           AND key_expire <= ?
                           AND notified = 0
                           AND is_banned = 0""", (now_iso,))
            expired = c.fetchall()
            for row in expired:
                uid = row["user_id"]
                try:
                    bot.send_message(uid,
                        "🔒 <b>KEY KHÔNG CÒN HOẠT ĐỘNG</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        "⏰ Key của bạn đã <b>hết hạn</b>.\n"
                        f"💰 Gõ /nap để gia hạn\n"
                        f"☎️ Admin: @{ADMIN_USERNAME}")
                except Exception as e:
                    print(f"[watcher] Lỗi gửi tin {uid}: {e}")
                c.execute("UPDATE users SET notified=1 WHERE user_id=?", (uid,))
                print(f"[watcher] Báo hết hạn -> {uid}")
            conn.commit(); conn.close()
        except Exception as e:
            print(f"[watcher] Lỗi: {e}")
        time.sleep(60)

def session_watcher():
    """
    Chạy nền: mỗi 30s kiểm tra API.
    Khi có phiên mới kết thúc → so sánh với dự đoán đã lưu → báo đúng/sai.
    """
    last_session_id = None
    while True:
        try:
            data = fetch_history()
            if data and data.get("list"):
                newest = data["list"][0]
                sid = newest["id"]
                actual = newest["resultTruyenThong"]  # TAI hoặc XIU

                if last_session_id is None:
                    last_session_id = sid
                elif sid > last_session_id:
                    # Có phiên mới → xử lý tất cả các phiên đã bỏ lỡ
                    new_sessions = [x for x in data["list"] if last_session_id < x["id"] <= sid]
                    for s in new_sessions:
                        process_session_result(s["id"], s["resultTruyenThong"])
                    last_session_id = sid
        except Exception as e:
            print(f"[session_watcher] Lỗi: {e}")
        time.sleep(CHECK_INTERVAL)

def process_session_result(session_id, actual):
    """So sánh dự đoán đã lưu với kết quả thực tế, gửi thông báo cho user."""
    conn = db(); c = conn.cursor()
    c.execute("""SELECT id, user_id, prediction, confidence FROM history
                 WHERE session_id=? AND actual IS NULL AND notified=0""", (session_id,))
    rows = c.fetchall()

    for r in rows:
        uid = r["user_id"]
        pred = r["prediction"]
        conf = r["confidence"]
        is_correct = 1 if pred == actual else 0
        try:
            bot.send_message(uid,
                f"🦀 <b>KẾT QUẢ PHIÊN #{session_id}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎲 Thực tế: <b>{actual}</b>\n"
                f"🎯 Dự đoán: <b>{pred}</b> ({conf}%)\n"
                f"📢 Kết quả: {'✅ ĐÚNG' if is_correct else '❌ SAI'}")
        except Exception as e:
            print(f"[session_watcher] Lỗi gửi {uid}: {e}")
        c.execute("UPDATE history SET actual=?, is_correct=?, notified=1 WHERE id=?",
                  (actual, is_correct, r["id"]))
        print(f"[session_watcher] Phiên #{session_id} → {actual} (pred={pred}, {'ĐÚNG' if is_correct else 'SAI'})")

    conn.commit(); conn.close()

# ================= API & THUẬT TOÁN =================
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

def predict_md5(history_results):
    if len(history_results) < 5: return "TAI", 50.0
    data_str = "|".join(history_results[:60])
    md5_h    = hashlib.md5(data_str.encode()).hexdigest()
    sha_h    = hashlib.sha256(data_str.encode()).hexdigest()
    seed     = int(md5_h[:8], 16) ^ int(sha_h[:8], 16) ^ int(sha_h[8:16], 16)
    rng      = random.Random(seed)
    tai, xiu, total = history_results.count("TAI"), history_results.count("XIU"), len(history_results)
    streak = 1
    for i in range(1, total):
        if history_results[i] == history_results[0]: streak += 1
        else: break
    alt = all(history_results[i] != history_results[i+1] for i in range(min(4, total-1)))
    s_tai = 0; s_xiu = 0
    if tai > xiu: s_tai += (tai - xiu)
    elif xiu > tai: s_xiu += (xiu - tai)
    if streak >= 3:
        if history_results[0] == "TAI": s_xiu += streak
        else: s_tai += streak
    if alt:
        if history_results[0] == "TAI": s_xiu += 2
        else: s_tai += 2
    if rng.randint(0, 9) % 2 == 0: s_tai += 1
    else: s_xiu += 1
    prediction = "TAI" if s_tai >= s_xiu else "XIU"
    base = min(50 + abs(s_tai - s_xiu) * 3, 95) + rng.uniform(-5, 5)
    base = max(50, min(base, 99))
    if base < 60: conf = round(rng.uniform(50, 60), 2)
    elif base < 70: conf = round(rng.uniform(60, 70), 2)
    else: conf = round(rng.uniform(70, min(base+5, 99)), 2)
    return prediction, conf

def predict_from_hash(hash_str):
    seed = int(hashlib.md5(hash_str.encode()).hexdigest()[:8], 16) ^ \
           int(hashlib.sha256(hash_str.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    prediction = "TAI" if rng.randint(0, 1) == 1 else "XIU"
    conf_base = 50 + rng.randint(0, 45)
    conf = round(conf_base + rng.uniform(-2, 2), 2)
    conf = max(50, min(conf, 99))
    return prediction, conf

def rate_label(c):
    if c < 60: return ""
    if c < 70: return ""
    return ""

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

def admin_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💰 Cấp Tiền", callback_data="adm_money"),
        types.InlineKeyboardButton("🔑 Cấp Key", callback_data="adm_key"),
    )
    kb.add(
        types.InlineKeyboardButton("👤 Kiểm User", callback_data="adm_check"),
        types.InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"),
    )
    kb.add(
        types.InlineKeyboardButton("✅ Unban User", callback_data="adm_unban"),
        types.InlineKeyboardButton("📋 Danh Sách User", callback_data="adm_list"),
    )
    kb.add(
        types.InlineKeyboardButton("🆕 Tạo Key Hàng Loạt", callback_data="adm_genkey"),
        types.InlineKeyboardButton("📊 Thống Kê", callback_data="adm_stats"),
    )
    return kb

ADMIN_STATE = {}

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

# ================= LAUCUA (CHỈ HIỆN PHIÊN + DỰ ĐOÁN + ĐỘ TIN CẬY) =================
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
    msg = bot.send_message(chat_id, "⏳ Đang phân tích...")
    data = fetch_history()
    if not data or not data.get("list"):
        bot.edit_message_text("❌ Không lấy được dữ liệu API.", chat_id, msg.message_id); return

    history = [x["resultTruyenThong"] for x in data["list"]]
    session_id = data["list"][0]["id"]
    prediction, conf = predict_md5(history)

    # Lưu vào DB để session_watcher so sánh sau khi hết phiên
    conn = db(); c = conn.cursor()
    c.execute("""INSERT INTO history(user_id, session_id, prediction, confidence, created_at)
                 VALUES(?,?,?,?,?)""",
              (uid, session_id, prediction, conf, datetime.now().isoformat()))
    conn.commit(); conn.close()

    icon = "🔴" if prediction == "TAI" else "🔵"
    text = (
        f"🦀 <b>LE MINH TOOL — KẾT QUẢ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 Phiên: <b>#{session_id}</b>\n"
        f"{icon} Dự đoán: <b>{prediction}</b>\n"
        f"🎯 Độ tin cậy: <b>{conf}%</b> — {rate_label(conf)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏳ Bot sẽ tự thông báo kết quả khi phiên kết thúc."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("DỰ ĐOÁN", callback_data="laucua"))
    bot.edit_message_text(text, chat_id, msg.message_id, reply_markup=kb)

# ================= NHẬP HASH =================
@bot.message_handler(func=lambda m: m.text and re.match(r'^[a-fA-F0-9]{32}$|^[a-fA-F0-9]{64}$', m.text.strip()))
def handle_hash_input(message):
    ensure_user(message)
    uid = message.from_user.id
    row = get_user(uid)
    if row and row["is_banned"]:
        bot.reply_to(message, "🚫 Bạn đã bị ban."); return
    ok, remain, _ = key_status(row)
    if not ok:
        bot.reply_to(message, f"🔒 <b>KEY KHÔNG CÒN HOẠT ĐỘNG</b>\nTrạng thái: <b>{remain}</b>\n\n💰 Gõ /nap để gia hạn key.")
        return
    hash_str = message.text.strip()
    prediction, conf = predict_from_hash(hash_str)
    icon = "🔴" if prediction == "TAI" else "🔵"
    text = (
        f"🦀 <b>LE MINH TOOL — DỰ ĐOÁN HASH</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📥 Hash: <code>{hash_str[:10]}...{hash_str[-10:]}</code>\n"
        f"{icon} Dự đoán: <b>{prediction}</b>\n"
        f"🎯 Độ tin cậy: <b>{conf}%</b> — {rate_label(conf)}"
    )
    bot.reply_to(message, text)

# ================= NAP =================
@bot.message_handler(commands=["nap"])
def cmd_nap(message):
    ensure_user(message); show_nap(message.chat.id)

def show_nap(chat_id):
    text = (
        "🏦 <b>NẠP TIỀN MUA KEY</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🏛 Ngân hàng: <b>MB BANK</b>\n"
        "💳 Số TK: <code>0372834763</code>\n"
        "👤 Chủ TK: <b>A LE HUY NHAT</b>\n"
        "📝 Nội dung CK: <b>[SĐT Telegram]</b>\n"
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
    try:
        bot.send_photo(chat_id, IMAGE_URL, caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        print(f"Lỗi gửi ảnh: {e}")
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

# ================= KEY =================
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
        f"📅 Hết hạn lúc: <b>{exp.strftime('%d/%m/%Y %H:%M:%S')}</b>")

# ================= ADMIN PANEL =================
@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if not is_admin(message):
        bot.reply_to(message, "❌ Bạn không có quyền dùng lệnh này."); return
    bot.send_message(message.chat.id,
        "🛠 <b>BẢNG ĐIỀU KHIỂN ADMIN</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👑 Admin: <b>@{ADMIN_USERNAME}</b>\n"
        "Chọn chức năng bên dưới:",
        reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_"))
def on_admin_cb(call):
    uid = call.from_user.id
    if not is_admin_id(uid):
        bot.answer_callback_query(call.id, "❌ Không có quyền", show_alert=True); return
    act = call.data
    bot.answer_callback_query(call.id)

    if act == "adm_money":
        ADMIN_STATE[uid] = {"action": "money"}
        bot.send_message(call.message.chat.id, "💰 <b>CẤP TIỀN</b>\nCú pháp: <code>[user_id] [số_tiền]</code>")
    elif act == "adm_key":
        ADMIN_STATE[uid] = {"action": "key"}
        bot.send_message(call.message.chat.id, "🔑 <b>CẤP KEY</b>\nCú pháp: <code>[user_id] [số_giờ]</code>")
    elif act == "adm_check":
        ADMIN_STATE[uid] = {"action": "check"}
        bot.send_message(call.message.chat.id, "👤 <b>KIỂM USER</b>\nGửi <code>[user_id]</code> hoặc <code>@username</code>")
    elif act == "adm_ban":
        ADMIN_STATE[uid] = {"action": "ban"}
        bot.send_message(call.message.chat.id, "🚫 <b>BAN USER</b>\nGửi <code>[user_id]</code> hoặc <code>@username</code>")
    elif act == "adm_unban":
        ADMIN_STATE[uid] = {"action": "unban"}
        bot.send_message(call.message.chat.id, "✅ <b>UNBAN USER</b>\nGửi <code>[user_id]</code> hoặc <code>@username</code>")
    elif act == "adm_list":
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id, username, balance, key_expire, is_banned FROM users ORDER BY created_at DESC LIMIT 30")
        rows = c.fetchall(); conn.close()
        if not rows:
            bot.send_message(call.message.chat.id, "📭 Chưa có user nào."); return
        txt = "📋 <b>DANH SÁCH USER (30 mới nhất)</b>\n━━━━━━━━━━━━━━━━━━\n"
        for r in rows:
            ok, remain, _ = key_status(r)
            status = "🔴" if r["is_banned"] else ("✅" if ok else "🔒")
            uname = f"@{r['username']}" if r['username'] else "—"
            txt += f"{status} <code>{r['user_id']}</code> {uname}\n   💵 {r['balance']:,}đ | 🔑 {remain}\n"
        bot.send_message(call.message.chat.id, txt)
    elif act == "adm_genkey":
        ADMIN_STATE[uid] = {"action": "genkey"}
        bot.send_message(call.message.chat.id, "🆕 <b>TẠO KEY</b>\nCú pháp: <code>[số_giờ] [số_lượng]</code>")
    elif act == "adm_stats":
        conn = db(); c = conn.cursor()
        c.execute("SELECT COUNT(*) as t FROM users"); total = c.fetchone()["t"]
        c.execute("SELECT COUNT(*) as b FROM users WHERE is_banned=1"); banned = c.fetchone()["b"]
        c.execute("SELECT COUNT(*) as k FROM keys"); keys = c.fetchone()["k"]
        c.execute("SELECT COUNT(*) as u FROM keys WHERE used_count>0"); used = c.fetchone()["u"]
        c.execute("SELECT COUNT(*) as h FROM history"); hist = c.fetchone()["h"]
        c.execute("SELECT COUNT(*) as a FROM users WHERE key_expire > ?", (datetime.now().isoformat(),))
        active = c.fetchone()["a"]
        c.execute("SELECT COUNT(*) as c FROM history WHERE is_correct=1"); correct = c.fetchone()["c"]
        c.execute("SELECT COUNT(*) as w FROM history WHERE is_correct=0"); wrong = c.fetchone()["w"]
        conn.close()
        total_done = correct + wrong
        rate = round(correct / total_done * 100, 1) if total_done > 0 else 0
        bot.send_message(call.message.chat.id,
            f"📊 <b>THỐNG KÊ HỆ THỐNG</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 Tổng user: <b>{total}</b>\n"
            f"🚫 Banned: <b>{banned}</b>\n"
            f"✅ Đang active: <b>{active}</b>\n"
            f"🔑 Tổng key: <b>{keys}</b>\n"
            f"📤 Key đã dùng: <b>{used}</b>\n"
            f"📊 Lượt lắc: <b>{hist}</b>\n"
            f"✅ Đúng: <b>{correct}</b> | ❌ Sai: <b>{wrong}</b>\n"
            f"🎯 Tỉ lệ đúng: <b>{rate}%</b>")

@bot.message_handler(func=lambda m: m.from_user.id in ADMIN_STATE, content_types=["text"])
def admin_input(message):
    uid = message.from_user.id
    if not is_admin_id(uid):
        ADMIN_STATE.pop(uid, None); return
    state = ADMIN_STATE.get(uid)
    if not state: return
    act = state["action"]
    text = message.text.strip()

    def resolve_target(s):
        s = s.strip()
        if s.startswith("@"):
            row = find_user_by_username(s)
            return row["user_id"] if row else None
        try: return int(s)
        except: return None

    try:
        if act == "money":
            parts = text.split()
            target = resolve_target(parts[0]); amount = int(parts[1].replace(",", "").replace(".", ""))
            if not target: bot.reply_to(message, "❌ Không tìm thấy user."); return
            add_balance(target, amount)
            bot.reply_to(message, f"✅ Đã cộng <b>{amount:,}đ</b> cho <code>{target}</code>")
            try: bot.send_message(target, f"💰 Admin đã cộng <b>{amount:,}đ</b> vào tài khoản của bạn!")
            except: pass
            ADMIN_STATE.pop(uid, None)
        elif act == "key":
            parts = text.split()
            target = resolve_target(parts[0]); hours = int(parts[1])
            if not target: bot.reply_to(message, "❌ Không tìm thấy user."); return
            exp = grant_key(target, hours)
            bot.reply_to(message, f"✅ Đã cấp key <b>{hours}h</b> cho <code>{target}</code>\nHết hạn: {exp.strftime('%d/%m/%Y %H:%M')}")
            try: bot.send_message(target, f"🎁 Admin đã cấp cho bạn key <b>{hours} giờ</b>!\n📅 Hết hạn: {exp.strftime('%d/%m/%Y %H:%M')}")
            except: pass
            ADMIN_STATE.pop(uid, None)
        elif act == "check":
            target = resolve_target(text)
            if not target: bot.reply_to(message, "❌ Không tìm thấy user."); return
            row = get_user(target)
            if not row: bot.reply_to(message, "❌ User chưa tồn tại."); return
            ok, remain, _ = key_status(row)
            conn = db(); c = conn.cursor()
            c.execute("SELECT COUNT(*) as t FROM history WHERE user_id=?", (target,)); total = c.fetchone()["t"]
            c.execute("SELECT COUNT(*) as cc FROM history WHERE user_id=? AND is_correct=1", (target,)); correct = c.fetchone()["cc"]
            c.execute("SELECT COUNT(*) as ww FROM history WHERE user_id=? AND is_correct=0", (target,)); wrong = c.fetchone()["ww"]
            conn.close()
            done = correct + wrong
            rate = round(correct / done * 100, 1) if done > 0 else 0
            bot.reply_to(message,
                f"👤 <b>THÔNG TIN USER</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"🆔 <code>{row['user_id']}</code>\n📛 Tên: {row['full_name']}\n"
                f"📧 Username: @{row['username'] or '—'}\n💵 Số dư: <b>{row['balance']:,}đ</b>\n"
                f"🔑 Key: {'✅ Còn <b>'+remain+'</b>' if ok else '🔒 '+remain}\n"
                f"📶 Trạng thái: {'🔴 Banned' if row['is_banned'] else '🟢 OK'}\n"
                f"📊 Lượt lắc: <b>{total}</b> | ✅ {correct} | ❌ {wrong} ({rate}%)")
            ADMIN_STATE.pop(uid, None)
        elif act == "ban":
            target = resolve_target(text)
            if not target: bot.reply_to(message, "❌ Không tìm thấy user."); return
            ban_user(target)
            bot.reply_to(message, f"✅ Đã ban <code>{target}</code>")
            try: bot.send_message(target, "🚫 Bạn đã bị admin ban.")
            except: pass
            ADMIN_STATE.pop(uid, None)
        elif act == "unban":
            target = resolve_target(text)
            if not target: bot.reply_to(message, "❌ Không tìm thấy user."); return
            unban_user(target)
            bot.reply_to(message, f"✅ Đã unban <code>{target}</code>")
            try: bot.send_message(target, "✅ Bạn đã được admin gỡ ban.")
            except: pass
            ADMIN_STATE.pop(uid, None)
        elif act == "genkey":
            parts = text.split()
            hours, qty = int(parts[0]), int(parts[1])
            if qty > 100: bot.reply_to(message, "❌ Tối đa 100 key/lần."); return
            codes = []
            conn = db(); c = conn.cursor()
            for _ in range(qty):
                code = gen_key_code()
                c.execute("INSERT INTO keys(code,hours,created_at) VALUES(?,?,?)", (code, hours, datetime.now().isoformat()))
                codes.append(code)
            conn.commit(); conn.close()
            bot.reply_to(message, f"✅ Đã tạo <b>{qty}</b> key loại <b>{hours}h</b>:\n\n" + "\n".join([f"<code>{x}</code>" for x in codes]))
            ADMIN_STATE.pop(uid, None)
    except Exception as e:
        bot.reply_to(message, f"❌ Lỗi: <code>{e}</code>")
        ADMIN_STATE.pop(uid, None)

# ================= USER CALLBACKS =================
@bot.callback_query_handler(func=lambda c: True)
def on_cb(call):
    data = call.data
    if data.startswith("adm_"):
        on_admin_cb(call); return
    uid = call.from_user.id
    ensure_user(call); row = get_user(uid)

    if data == "home":
        ok, remain, _ = key_status(row)
        key_line = f"✅ Còn hạn: <b>{remain}</b>" if ok else f"🔒 Key: <b>{remain}</b>"
        bot.edit_message_text(
            f"🦀 <b>{BRAND}</b>\n🔑 {key_line}\n\nChọn chức năng:",
            call.message.chat.id, call.message.message_id, reply_markup=main_menu())
    elif data == "laucua":
        bot.answer_callback_query(call.id, "Đang phân tích...")
        do_laucua(call.message.chat.id, uid)
    elif data == "enterkey":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🔑 Gửi key theo cú pháp:\n<code>/key ma_key</code>")
    elif data == "nap":
        bot.answer_callback_query(call.id); show_nap(call.message.chat.id)
    elif data == "account":
        ok, remain, _ = key_status(row)
        bal = row["balance"] if row else 0
        status = "🔴 Banned" if (row and row["is_banned"]) else "🟢 Hoạt động"
        conn = db(); c = conn.cursor()
        c.execute("SELECT COUNT(*) as t FROM history WHERE user_id=?", (uid,)); total = c.fetchone()["t"]
        c.execute("SELECT COUNT(*) as cc FROM history WHERE user_id=? AND is_correct=1", (uid,)); correct = c.fetchone()["cc"]
        c.execute("SELECT COUNT(*) as ww FROM history WHERE user_id=? AND is_correct=0", (uid,)); wrong = c.fetchone()["ww"]
        conn.close()
        done = correct + wrong
        rate = round(correct / done * 100, 1) if done > 0 else 0
        bot.edit_message_text(
            f"👤 <b>TÀI KHOẢN</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <code>{uid}</code>\n💵 Số dư: <b>{bal:,}đ</b>\n"
            f"🔑 Key: {'✅ Còn hạn <b>'+remain+'</b>' if ok else '🔒 '+remain}\n"
            f"📶 {status}\n"
            f"📊 Lượt lắc: <b>{total}</b> | ✅ {correct} | ❌ {wrong} ({rate}%)",
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
                if r["actual"]:
                    kq = "✅" if r["is_correct"] == 1 else "❌"
                else:
                    kq = "⏳"
                txt += f"{kq} #{r['session_id']} — {r['prediction']} ({r['confidence']}%)\n"
        bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=back_menu())

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=key_watcher, daemon=True).start()
    threading.Thread(target=session_watcher, daemon=True).start()
    print(f"🦀 {BRAND} — Bot đang chạy...")
    bot.infinity_polling(timeout=30, long_polling_timeout=25)

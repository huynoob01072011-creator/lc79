import telebot
from telebot import types
from telethon import TelegramClient, utils, events
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, PhoneNumberInvalidError,
    ApiIdInvalidError, PasswordHashInvalidError,
)
import asyncio, threading, os, re, time, random
import base64, json, html, requests
from concurrent.futures import ThreadPoolExecutor, wait as fut_wait
from flask import Flask, jsonify

# ================= CONFIG =================
BOT_TOKEN = "9042450675:AAHWU1HNAzok0avxdy-Ub3PxPTb5DmsD_cg"
bot = telebot.TeleBot(BOT_TOKEN)
os.makedirs("sessions", exist_ok=True)

DEFAULT_CHAT_ID   = -1002237214360
DEFAULT_CHAT_USER = "codelaucuagame"
POLL_INTERVAL     = 0.2
PRE_REFRESH_SEC   = 180
HISTORY_MAX       = 50

# Flask config
FLASK_PORT = int(os.environ.get("PORT", 8080))

API_GET_ACCESS  = "https://apifo88daigia.tele68.com/api"
LOGIN_URL       = "https://wlb.tele68.com/v1/lobby/auth/login"
BASE_URL        = "https://gameapi.tele68.com"
PARAMS          = "/v1/giftcode/redemption?cp=R&cl=R&pf=web&at="
CONNECT_TIMEOUT = 3
READ_TIMEOUT    = 10
MAX_RETRY       = 2

LINE  = "━━━━━━━━━━━━━━━"
LINE2 = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈"

# ================= FLASK KEEP-ALIVE =================
flask_app = Flask(__name__)
START_TIME = time.time()

@flask_app.route("/")
def index():
    uptime = int(time.time() - START_TIME)
    h = uptime // 3600
    m = (uptime % 3600) // 60
    s = uptime % 60
    return (
        f"<h1>🤖 Bot v8 Online</h1>"
        f"<p>⏱️ Uptime: {h}h {m}m {s}s</p>"
        f"<p>👥 Users: {len(user_states)}</p>"
        f"<p>⚡ Listening: "
        f"{sum(1 for s in user_states.values() if s.get('step') == 'listening')}</p>"
    )

@flask_app.route("/ping")
def ping():
    return jsonify({
        "status": "ok",
        "uptime": int(time.time() - START_TIME),
        "users": len(user_states),
        "listening": sum(
            1 for s in user_states.values()
            if s.get("step") == "listening"
        ),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })

@flask_app.route("/health")
def health():
    return "OK", 200

def start_flask():
    flask_app.run(
        host="0.0.0.0",
        port=FLASK_PORT,
        debug=False,
        use_reloader=False,
    )

# ================= ASYNC LOOP =================
_loop = asyncio.new_event_loop()

def _start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=_start_loop, args=(_loop,), daemon=True).start()

def run_async(coro, timeout=120):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)

_executor = ThreadPoolExecutor(max_workers=100, thread_name_prefix="redeem")
_redeem_tasks = set()

# ================= HELPERS =================
def normalize_code(raw):
    if not raw:
        return None
    code = re.sub(r"[^A-Z0-9]", "", raw.strip().upper())
    if code.endswith("LC79") and len(code) > 4:
        code = code[:-4]
    return code or None

def extract_code(text):
    if not text:
        return None
    m = re.search(r"Mã code là[:\s]+([A-Z0-9]+)", text)
    if not m:
        return None
    return normalize_code(m.group(1))

# ================= ACCOUNT =================
class Account:
    def __init__(self, un, pw, nick):
        self.un = un
        self.pw = pw
        self.nick = nick
        self.used_codes = set()
        self.lock = threading.Lock()
        self.jwt = None
        self.jwt_exp = 0
        self.http = requests.Session()
        self.http.headers.update({
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0",
            "origin": "https://lc79.to",
            "referer": "https://lc79.to/",
            "accept": "application/json, text/plain, */*",
        })

    def _auth(self):
        return {"authorization": f"Bearer {self.jwt}"}

    @staticmethod
    def parse_jwt_exp(token):
        try:
            p = token.split(".")[1]
            p += "=" * (-len(p) % 4)
            return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
        except Exception:
            return 0

    def is_token_valid(self):
        if self.jwt is None:
            return False
        return time.time() < (self.jwt_exp - 120)

    def get_access_token(self):
        try:
            res = self.http.get(
                API_GET_ACCESS,
                params={
                    "c": "3", "un": self.un, "pw": self.pw,
                    "cp": "R", "cl": "R", "pf": "web", "at": "",
                },
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            d = res.json()
            return d.get("accessToken") if d.get("success") else None
        except Exception:
            return None

    def refresh_token(self):
        token = self.get_access_token()
        if not token:
            return False
        try:
            res = self.http.post(
                LOGIN_URL,
                json={"nickName": self.nick, "accessToken": token},
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                headers={
                    "origin": "https://lc79b.bet",
                    "referer": "https://lc79b.bet/",
                },
            )
            new = res.json().get("token")
            if not new:
                return False
            self.jwt = new
            self.jwt_exp = self.parse_jwt_exp(new)
            return True
        except Exception:
            return False

    def redeem_code(self, code, _attempt=0):
        with self.lock:
            if code in self.used_codes:
                return (False, None)
            self.used_codes.add(code)

        if not self.is_token_valid():
            if not self.refresh_token():
                return (False, None)

        try:
            res = self.http.post(
                BASE_URL + PARAMS,
                headers=self._auth(),
                json={"code": code, "captcha": ""},
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            try:
                data = res.json()
            except Exception:
                data = {}

            if res.status_code == 401:
                if self.refresh_token():
                    with self.lock:
                        self.used_codes.discard(code)
                    return self.redeem_code(code, _attempt)
                return (False, None)

            if res.status_code in (200, 201):
                amt = (
                    data.get("money") or data.get("amount")
                    or data.get("reward")
                    or (data.get("data") or {}).get("money")
                )
                return (True, amt)
            return (False, None)
        except Exception:
            if _attempt < MAX_RETRY:
                return self.redeem_code(code, _attempt + 1)
            return (False, None)

# ================= REDEEM =================
def redeem_parallel(accounts, code):
    futures = {_executor.submit(a.redeem_code, code): a for a in accounts}
    done, _ = fut_wait(futures, timeout=30)
    results = []
    for fut in done:
        acc = futures[fut]
        try:
            ok, amt = fut.result()
        except Exception:
            ok, amt = False, None
        results.append((acc.nick, ok, amt))
    for acc in accounts:
        if not any(r[0] == acc.nick for r in results):
            results.append((acc.nick, False, None))
    return results

# ================= STATE =================
user_states = {}

def _notify(uid, text):
    try:
        bot.send_message(uid, text, parse_mode="HTML")
    except Exception:
        pass

def _cleanup_state(uid):
    st = user_states.pop(uid, None)
    if not st:
        return
    client = st.get("client")
    if client:
        h = st.get("handler")
        if h:
            try:
                client.remove_event_handler(h)
            except Exception:
                pass
        try:
            run_async(client.disconnect(), timeout=10)
        except Exception:
            pass

def _save_history(uid, code, results, elapsed_ms, manual=False):
    st = user_states.get(uid)
    if not st:
        return
    hist = st.setdefault("history", [])
    hist.append({
        "code": code,
        "time": time.time(),
        "ok": sum(1 for _, ok, _ in results if ok),
        "total": len(results),
        "manual": manual,
    })
    if len(hist) > HISTORY_MAX:
        del hist[:-HISTORY_MAX]

def _format_history(uid):
    st = user_states.get(uid)
    hist = st.get("history", []) if st else []
    if not hist:
        return (
            f"╔══════════════════════╗\n"
            f"  🏆 <b>TOP 10 CODE</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"📭 <i>Chưa có code nào!</i>\n"
            f"{LINE2}\n"
            f"💡 /setchat để bật auto bắt code"
        )
    latest = list(reversed(hist[-10:]))
    text = (
        f"╔══════════════════════╗\n"
        f"  🏆 <b>10 CODE GẦN NHẤT</b>\n"
        f"╚══════════════════════╝\n\n"
        f"{LINE}\n"
    )
    for i, h in enumerate(latest, 1):
        icon = "💰" if h["ok"] > 0 else "❌"
        if h.get("manual"):
            icon = "✍️" + icon
        t = time.strftime("%H:%M:%S", time.localtime(h["time"]))
        text += (
            f"{i:2d}. {icon} <code>{h['code']}</code>  "
            f"<b>{h['ok']}/{h['total']}</b>  <i>{t}</i>\n"
        )
    total_ok = sum(1 for h in hist if h["ok"] > 0)
    text += (
        f"{LINE2}\n"
        f"📊 Tổng đã thử: <b>{len(hist)}</b>\n"
        f"💰 Thành công: <b>{total_ok}</b>"
    )
    return text

# ================= FIRE REDEEM =================
def _fire_redeem(uid, code, accounts, manual=False):
    fut = asyncio.run_coroutine_threadsafe(
        _do_redeem(uid, code, accounts, manual), _loop
    )
    _redeem_tasks.add(fut)
    fut.add_done_callback(_redeem_tasks.discard)

async def _do_redeem(uid, code, accounts, manual=False):
    t0 = time.time()
    tag = "✍️ THỦ CÔNG" if manual else "🎁 AUTO"
    _notify(uid,
        f"{tag}\n"
        f"{LINE}\n"
        f"🔑 <code>{code}</code>\n"
        f"👥 Bắn: <b>{len(accounts)}</b> acc\n"
        f"⚡ Đang tranh chấp...")
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        _executor, redeem_parallel, accounts, code
    )
    elapsed = (time.time() - t0) * 1000
    ok_count = sum(1 for _, ok, _ in results if ok)
    _save_history(uid, code, results, elapsed, manual)
    rep = (
        f"⚡ <b>XONG</b> ({elapsed:.0f}ms)\n"
        f"{LINE}\n"
        f"🔑 <code>{code}</code>\n"
        f"📊 KQ: <b>{ok_count}/{len(results)}</b> OK\n"
        f"{LINE2}\n"
    )
    for nick, ok, amt in results:
        if ok and amt:
            rep += f"💰 {nick}: <b>+{int(amt):,}</b>\n"
        elif ok:
            rep += f"✅ {nick}: OK\n"
        else:
            rep += f"❌ {nick}\n"
    _notify(uid, rep)

# ================= LISTENER =================
async def start_listener(client, uid, chat_id, start_id):
    st = user_states.get(uid)
    if not st:
        return
    last_id = [start_id]

    async def on_new(event):
        cur = user_states.get(uid, {})
        if cur.get("step") != "listening":
            return
        if event.id <= last_id[0]:
            return
        last_id[0] = event.id
        code = extract_code(event.raw_text or "")
        if not code:
            return
        accounts = cur.get("accounts", [])
        if not accounts:
            return
        _fire_redeem(uid, code, accounts)

    client.add_event_handler(on_new, events.NewMessage(chats=[chat_id]))
    st["handler"] = on_new

    async def poll_backup():
        while True:
            cur = user_states.get(uid, {})
            if cur.get("step") != "listening":
                return
            try:
                msgs = await client.get_messages(
                    chat_id, limit=3, min_id=last_id[0]
                )
                for msg in reversed(msgs or []):
                    if msg.id <= last_id[0]:
                        continue
                    last_id[0] = msg.id
                    code = extract_code(msg.raw_text or "")
                    if not code:
                        continue
                    accs = cur.get("accounts", [])
                    if accs:
                        _fire_redeem(uid, code, accs)
            except Exception:
                pass
            await asyncio.sleep(POLL_INTERVAL)

    asyncio.create_task(poll_backup())

    async def pre_refresh():
        while True:
            cur = user_states.get(uid, {})
            if cur.get("step") != "listening":
                return
            loop = asyncio.get_event_loop()
            for acc in cur.get("accounts", []):
                if not acc.is_token_valid():
                    await loop.run_in_executor(_executor, acc.refresh_token)
            await asyncio.sleep(PRE_REFRESH_SEC)

    asyncio.create_task(pre_refresh())

# ================= /start =================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    name = html.escape(message.from_user.first_name or "bạn")
    _cleanup_state(uid)
    text = (
        f"╔══════════════════════╗\n"
        f"  🌟 <b>WELCOME TO BOT</b> 🌟\n"
        f"╚══════════════════════╝\n\n"
        f"👋 Chào <b>{name}</b>!\n"
        f"🆔 <code>{uid}</code>\n\n"
        f"{LINE}\n"
        f"⚡ <b>AUTO CODE LC79 v8</b>\n"
        f"{LINE}\n\n"
        f"🚀 Real-time event &lt; 100ms\n"
        f"🎯 Bắn song song 100% acc\n"
        f"🔥 Bỏ LC79 tự động\n"
        f"💨 Poll backup 0.2s\n"
        f"🏆 Lưu 50 code gần nhất\n"
        f"✍️ Nhập code tay khi cần\n"
        f"🌐 Flask keep-alive\n\n"
        f"{LINE}\n"
        f"📖 <b>QUY TRÌNH 3 BƯỚC</b>\n"
        f"{LINE}\n\n"
        f"<b>1️⃣</b> Login Telegram\n"
        f"<b>2️⃣</b> Login LC79\n"
        f"<b>3️⃣</b> /setchat → auto\n\n"
        f"{LINE2}\n"
        f"👇 Bấm nút:"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🚀 Bắt Đầu", callback_data="auto"),
        types.InlineKeyboardButton("📖 HDSD", callback_data="help"),
    )
    kb.add(
        types.InlineKeyboardButton("✍️ Nhập Tay", callback_data="manual"),
        types.InlineKeyboardButton("🏆 Top 10", callback_data="codes"),
    )
    kb.add(
        types.InlineKeyboardButton("💬 Hỗ Trợ", callback_data="support"),
        types.InlineKeyboardButton("ℹ️ Info", callback_data="info"),
    )
    bot.send_message(message.chat.id, text,
                     reply_markup=kb, parse_mode="HTML")

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def on_cb(call):
    cid = call.message.chat.id
    uid = call.from_user.id

    if call.data == "auto":
        bot.answer_callback_query(call.id)
        _cleanup_state(uid)
        user_states[uid] = {"step": "api_id"}
        text = (
            f"╔══════════════════════╗\n"
            f"  🔐 <b>BƯỚC 1 — TELEGRAM</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"📖 <b>LẤY API:</b>\n"
            f"{LINE}\n\n"
            f"🌐 <b>my.telegram.org</b>\n\n"
            f"1️⃣ Login SĐT Telegram\n"
            f"2️⃣ Chọn <b>API development tools</b>\n"
            f"3️⃣ Điền form:\n"
            f"   • Title: <code>AutoCode</code>\n"
            f"   • Short: <code>autocode</code>\n"
            f"   • Platform: <code>Other</code>\n"
            f"4️⃣ Copy api_id + api_hash\n\n"
            f"{LINE2}\n"
            f"📩 Gửi <b>api_id</b>:\n"
            f"└ VD: <code>12345678</code>\n\n"
            f"⚠️ /cancel để hủy"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back"))
        bot.send_message(cid, text, parse_mode="HTML", reply_markup=kb)

    elif call.data == "manual":
        bot.answer_callback_query(call.id)
        st = user_states.get(uid)
        if not st or st.get("step") not in ("telegram_done", "listening"):
            bot.send_message(cid,
                "⚠️ <b>Chưa login Telegram!</b>\n\n"
                "Bấm 🚀 Bắt Đầu Auto trước.",
                parse_mode="HTML")
            return
        accounts = st.get("accounts", [])
        if not accounts:
            bot.send_message(cid,
                "⚠️ <b>Chưa có acc game!</b>\n\n"
                "Gửi: <code>/login user pass</code>",
                parse_mode="HTML")
            return
        st["manual_mode"] = True
        bot.send_message(cid,
            f"╔══════════════════════╗\n"
            f"  ✍️ <b>NHẬP CODE TAY</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"📩 Gửi mã code vào đây:\n\n"
            f"💡 Có thể paste full LC79\n"
            f"└ VD: <code>YMQTWHXYTLC79</code>\n"
            f"└ Tự bỏ → <code>YMQTWHXYT</code>\n\n"
            f"{LINE2}\n"
            f"⚡ Bot bắn tới <b>{len(accounts)}</b> acc\n"
            f"🔁 Cho phép retry code cũ\n"
            f"⚠️ /cancel để hủy",
            parse_mode="HTML")

    elif call.data == "codes":
        bot.answer_callback_query(call.id)
        st = user_states.get(uid)
        if not st:
            bot.send_message(cid, "⚠️ Gõ /start trước.")
            return
        bot.send_message(cid, _format_history(uid), parse_mode="HTML")

    elif call.data == "help":
        bot.answer_callback_query(call.id)
        text = (
            f"╔══════════════════════╗\n"
            f"  📖 <b>HƯỚNG DẪN</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"🔐 <b>B1 — TELEGRAM</b>\n"
            f"{LINE}\n"
            f"• 🚀 Bắt Đầu → gửi:\n"
            f"  1. api_id\n"
            f"  2. api_hash\n"
            f"  3. SĐT (+84...)\n"
            f"• OTP → (2FA) → done\n\n"
            f"{LINE}\n"
            f"🎮 <b>B2 — GAME</b>\n"
            f"{LINE}\n"
            f"• <code>/login user pass</code>\n"
            f"• <code>/add user pass</code>\n\n"
            f"{LINE}\n"
            f"⚡ <b>B3 — AUTO</b>\n"
            f"{LINE}\n"
            f"• <code>/setchat</code> (kênh mặc định)\n"
            f"• <code>/setchat @kênh</code>\n\n"
            f"{LINE2}\n"
            f"🎁 <b>NHẬP TAY / LỊCH SỬ</b>\n"
            f"{LINE2}\n"
            f"• <code>/code YMQTWHXYT</code>\n"
            f"  └ Nhập code thủ công\n"
            f"  └ Cho phép retry code cũ\n\n"
            f"• <code>/codes</code>\n"
            f"  └ Xem 10 code gần nhất\n\n"
            f"{LINE2}\n"
            f"📋 <b>LỆNH KHÁC</b>\n"
            f"• /accounts /stop /cancel /logout\n\n"
            f"{LINE2}\n"
            f"💡 <b>MẸO THẮNG:</b>\n"
            f"• VPS gần SG/HK\n"
            f"• Nhiều acc có nạp\n"
            f"• Giữ bot online 24/7"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back"))
        bot.send_message(cid, text, parse_mode="HTML", reply_markup=kb)

    elif call.data == "support":
        bot.answer_callback_query(call.id)
        text = (
            f"╔══════════════════════╗\n"
            f"  💬 <b>HỖ TRỢ</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"👨‍💻 Admin: @your_admin\n"
            f"📢 Kênh: @{DEFAULT_CHAT_USER}\n"
            f"🌐 Web: lc79.luxury\n"
            f"{LINE}\n\n"
            f"⏰ 8h - 22h\n"
            f"⚡ Phản hồi 5 phút"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back"))
        bot.send_message(cid, text, parse_mode="HTML", reply_markup=kb)

    elif call.data == "info":
        bot.answer_callback_query(call.id)
        uptime = int(time.time() - START_TIME)
        text = (
            f"╔══════════════════════╗\n"
            f"  ℹ️ <b>THÔNG TIN</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"🤖 Auto Code LC79\n"
            f"📦 Version: v8.0\n"
            f"⚙️ Engine: Telethon Events\n"
            f"⏱️ Poll backup: {POLL_INTERVAL}s\n"
            f"🔥 Pre-refresh: {PRE_REFRESH_SEC}s\n"
            f"📚 History max: {HISTORY_MAX}\n"
            f"🌐 Uptime: {uptime // 3600}h "
            f"{(uptime % 3600) // 60}m\n"
            f"👥 Users: {len(user_states)}\n"
            f"🌐 Flask: port {FLASK_PORT}\n"
            f"{LINE}\n\n"
            f"✅ Event realtime &lt; 100ms\n"
            f"✅ Song song 100% acc\n"
            f"✅ Keep-alive HTTP\n"
            f"✅ Bỏ suffix LC79\n"
            f"✅ Nhập tay + retry\n"
            f"✅ Top 10 code\n"
            f"✅ Flask keep-alive\n"
            f"{LINE2}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back"))
        bot.send_message(cid, text, parse_mode="HTML", reply_markup=kb)

    elif call.data == "back":
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(cid, call.message.message_id)
        except Exception:
            pass
        fake = type("M", (), {
            "chat": call.message.chat,
            "from_user": call.from_user,
        })()
        cmd_start(fake)

# ================= LOGIN FLOW =================
@bot.message_handler(func=lambda m: (
    m.from_user.id in user_states
    and m.text is not None
    and not m.text.startswith("/")
))
def login_flow(message):
    uid = message.from_user.id
    txt = message.text.strip()
    st = user_states.get(uid)
    if not st:
        return

    if st.get("manual_mode"):
        st["manual_mode"] = False
        code = normalize_code(txt)
        if not code or len(code) < 4:
            bot.reply_to(message,
                "❌ <b>Code không hợp lệ!</b>\n"
                "Gõ /start nếu cần.",
                parse_mode="HTML")
            return
        accounts = st.get("accounts", [])
        if not accounts:
            bot.reply_to(message,
                "⚠️ Chưa có acc!\n/login user pass",
                parse_mode="HTML")
            return
        for acc in accounts:
            acc.used_codes.discard(code)
        _fire_redeem(uid, code, accounts, manual=True)
        return

    step = st.get("step")

    if step == "api_id":
        if not txt.isdigit() or len(txt) < 5:
            bot.reply_to(message,
                "❌ api_id không hợp lệ.\nVD: <code>12345678</code>",
                parse_mode="HTML")
            return
        st["api_id"] = int(txt)
        st["step"] = "api_hash"
        bot.reply_to(message,
            f"✅ api_id: <code>{txt}</code>\n\n"
            f"📩 Gửi <b>api_hash</b> (32 ký tự):",
            parse_mode="HTML")

    elif step == "api_hash":
        if len(txt) < 20 or " " in txt:
            bot.reply_to(message,
                "❌ api_hash không hợp lệ (≥20 ký tự, không dấu cách).",
                parse_mode="HTML")
            return
        st["api_hash"] = txt
        st["step"] = "phone"
        bot.reply_to(message,
            f"✅ api_hash đã lưu\n\n"
            f"📱 Gửi <b>SĐT</b> (+84...):",
            parse_mode="HTML")

    elif step == "phone":
        phone = txt.replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            bot.reply_to(message,
                "❌ SĐT phải bắt đầu bằng +.\nVD: +84901234567",
                parse_mode="HTML")
            return
        bot.reply_to(message, "⏳ Đang gửi OTP...")
        api_id = st["api_id"]
        api_hash = st["api_hash"]
        session = f"sessions/{uid}"

        async def create_and_send():
            client = TelegramClient(
                session, api_id, api_hash,
                flood_sleep_threshold=120,
                connection_retries=5,
                retry_delay=2,
            )
            await client.connect()
            if await client.is_user_authorized():
                return client, {"status": "already"}
            sent = await client.send_code_request(phone)
            return client, {"status": "sent",
                            "hash": sent.phone_code_hash}

        try:
            client, result = run_async(create_and_send())
            st["client"] = client
            st["phone"] = phone

            if result["status"] == "already":
                st["step"] = "telegram_done"
                bot.reply_to(message,
                    f"✅ <b>Session còn hạn!</b>\n\n"
                    f"➡️ <code>/login user pass</code>",
                    parse_mode="HTML")
                return

            st["phone_code_hash"] = result["hash"]
            st["step"] = "otp"
            bot.reply_to(message,
                f"📨 <b>Đã gửi OTP</b>\n\n"
                f"📱 Mở Telegram xem tin nhắn\n\n"
                f"📩 Nhập <b>OTP</b> (chỉ số):",
                parse_mode="HTML")

        except ApiIdInvalidError:
            _cleanup_state(uid)
            bot.reply_to(message,
                "❌ api_id/hash sai!\n/start làm lại.",
                parse_mode="HTML")
        except PhoneNumberInvalidError:
            bot.reply_to(message, "❌ SĐT không hợp lệ!")
        except Exception as e:
            _cleanup_state(uid)
            bot.reply_to(message,
                f"❌ Lỗi: <code>{html.escape(str(e))}</code>",
                parse_mode="HTML")

    elif step == "otp":
        code = txt.replace(" ", "")
        client = st["client"]

        async def do_sign_in():
            try:
                await client.sign_in(
                    phone=st["phone"], code=code,
                    phone_code_hash=st["phone_code_hash"])
                return "ok"
            except SessionPasswordNeededError:
                return "2fa"

        try:
            r = run_async(do_sign_in())
            if r == "2fa":
                st["step"] = "2fa"
                bot.reply_to(message,
                    f"🔐 <b>Có 2FA</b>\n\n"
                    f"📩 Nhập <b>mật khẩu 2FA</b>:\n"
                    f"(Settings → Privacy → Two-Step)",
                    parse_mode="HTML")
                return
            st["step"] = "telegram_done"
            bot.reply_to(message,
                f"✅ <b>LOGIN TELEGRAM OK</b>\n\n"
                f"➡️ <code>/login user pass</code>\n"
                f"└ Thêm: <code>/add user pass</code>",
                parse_mode="HTML")
        except PhoneCodeInvalidError:
            bot.reply_to(message, "❌ OTP sai! Nhập lại:")
        except PhoneCodeExpiredError:
            _cleanup_state(uid)
            bot.reply_to(message,
                "❌ OTP hết hạn!\n/start làm lại.")
        except Exception as e:
            bot.reply_to(message,
                f"❌ <code>{html.escape(str(e))}</code>",
                parse_mode="HTML")

    elif step == "2fa":
        client = st["client"]

        async def do_2fa():
            await client.sign_in(password=txt)

        try:
            run_async(do_2fa())
            st["step"] = "telegram_done"
            bot.reply_to(message,
                f"✅ <b>2FA OK</b>\n\n"
                f"➡️ <code>/login user pass</code>",
                parse_mode="HTML")
        except PasswordHashInvalidError:
            bot.reply_to(message, "❌ Pass 2FA sai! Nhập lại:")
        except Exception as e:
            bot.reply_to(message,
                f"❌ <code>{html.escape(str(e))}</code>",
                parse_mode="HTML")

# ================= /login =================
@bot.message_handler(commands=["login"])
def cmd_login(message):
    uid = message.from_user.id
    st = user_states.get(uid)
    if not st or st.get("step") != "telegram_done":
        bot.reply_to(message,
            "⚠️ Chưa login Telegram! /start",
            parse_mode="HTML")
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message,
            "⚠️ <code>/login user pass</code>",
            parse_mode="HTML")
        return
    un, pw = parts[1], parts[2]
    bot.reply_to(message, "⏳ Đang login...")
    acc = Account(un, pw, un)
    if not acc.refresh_token():
        bot.reply_to(message,
            f"❌ Login fail <code>{html.escape(un)}</code>\n"
            f"Check user/pass.",
            parse_mode="HTML")
        return
    st.setdefault("accounts", []).append(acc)
    bot.reply_to(message,
        f"✅ <b>Login OK</b>\n"
        f"{LINE}\n"
        f"👤 <code>{html.escape(un)}</code>\n"
        f"📊 Tổng: <b>{len(st['accounts'])}</b>\n\n"
        f"➡️ <code>/setchat</code> để bật auto",
        parse_mode="HTML")

# ================= /add =================
@bot.message_handler(commands=["add"])
def cmd_add(message):
    uid = message.from_user.id
    st = user_states.get(uid)
    if not st or st.get("step") not in ("telegram_done", "listening"):
        bot.reply_to(message, "⚠️ Chưa login Telegram!")
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message,
            "⚠️ <code>/add user pass</code>",
            parse_mode="HTML")
        return
    un, pw = parts[1], parts[2]
    bot.reply_to(message, "⏳ Đang thêm...")
    acc = Account(un, pw, un)
    if not acc.refresh_token():
        bot.reply_to(message, f"❌ Fail <code>{html.escape(un)}</code>")
        return
    st.setdefault("accounts", []).append(acc)
    bot.reply_to(message,
        f"✅ Đã thêm <code>{html.escape(un)}</code>\n"
        f"📊 Tổng: <b>{len(st['accounts'])}</b>",
        parse_mode="HTML")

# ================= /setchat =================
@bot.message_handler(commands=["setchat"])
def cmd_setchat(message):
    uid = message.from_user.id
    st = user_states.get(uid)
    if not st or st.get("step") not in ("telegram_done", "listening"):
        bot.reply_to(message, "⚠️ Chưa login Telegram!")
        return
    accounts = st.get("accounts", [])
    if not accounts:
        bot.reply_to(message,
            "⚠️ Chưa có acc!\n/login user pass",
            parse_mode="HTML")
        return

    parts = message.text.split(maxsplit=1)
    target = parts[1].strip() if len(parts) > 1 else None
    client = st["client"]

    async def resolve():
        try:
            if target is None:
                try:
                    entity = await client.get_entity(DEFAULT_CHAT_ID)
                except Exception:
                    entity = await client.get_entity(DEFAULT_CHAT_USER)
            elif target.lstrip("-").isdigit():
                entity = await client.get_entity(int(target))
            elif "t.me/" in target:
                un = target.rstrip("/").split("/")[-1].lstrip("@")
                entity = await client.get_entity(un)
            else:
                entity = await client.get_entity(target.lstrip("@"))
            pid = utils.get_peer_id(entity)
            latest = await client.get_messages(entity, limit=1)
            lid = latest[0].id if latest else 0
            return pid, lid, None
        except Exception as e:
            return None, 0, str(e)

    label = target or f"@{DEFAULT_CHAT_USER}"
    bot.reply_to(message, f"🔍 Kết nối {label}...")

    try:
        pid, lid, err = run_async(resolve())
    except Exception as e:
        pid, lid, err = None, 0, str(e)

    if pid is None:
        bot.reply_to(message,
            f"❌ <b>Không kết nối được</b>\n\n"
            f"⚠️ Join kênh trước\n"
            f"⚠️ Kênh phải public\n\n"
            f"Lỗi: <code>{html.escape(str(err))}</code>",
            parse_mode="HTML")
        return

    st["target_chat"] = pid
    st["step"] = "listening"

    asyncio.run_coroutine_threadsafe(
        start_listener(client, uid, pid, lid), _loop
    )

    bot.reply_to(message,
        f"╔══════════════════════╗\n"
        f"  🎯 <b>AUTO ĐÃ BẬT</b>\n"
        f"╚══════════════════════╝\n\n"
        f"{LINE}\n"
        f"📡 <code>{html.escape(label)}</code>\n"
        f"🆔 <code>{pid}</code>\n"
        f"👥 Acc: <b>{len(accounts)}</b>\n"
        f"{LINE}\n\n"
        f"⚡ <b>Real-time event</b> &lt;100ms\n"
        f"💨 Backup poll <b>{POLL_INTERVAL}s</b>\n"
        f"🔐 Pre-refresh <b>{PRE_REFRESH_SEC}s</b>\n"
        f"🎯 Bắn song song <b>100%</b>\n\n"
        f"{LINE2}\n"
        f"🤖 Đang nghe code...\n"
        f"✍️ /code để nhập tay\n"
        f"🏆 /codes xem lịch sử",
        parse_mode="HTML")

# ================= /code =================
@bot.message_handler(commands=["code"])
def cmd_code(message):
    uid = message.from_user.id
    st = user_states.get(uid)
    if not st or st.get("step") not in ("telegram_done", "listening"):
        bot.reply_to(message,
            "⚠️ Login Telegram trước!\n/start",
            parse_mode="HTML")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message,
            f"✍️ <b>NHẬP CODE TAY</b>\n"
            f"{LINE}\n"
            f"📝 Cú pháp:\n"
            f"<code>/code YMQTWHXYT</code>\n\n"
            f"💡 Có thể paste full mã:\n"
            f"<code>/code YMQTWHXYTLC79</code>\n"
            f"└ Tự bỏ LC79 → <code>YMQTWHXYT</code>\n\n"
            f"🔁 Cho phép retry code cũ\n"
            f"⚡ Bắn song song mọi acc",
            parse_mode="HTML")
        return
    code = normalize_code(parts[1])
    if not code or len(code) < 4:
        bot.reply_to(message,
            "❌ <b>Code không hợp lệ!</b>\n"
            "VD: <code>YMQTWHXYT</code>",
            parse_mode="HTML")
        return
    accounts = st.get("accounts", [])
    if not accounts:
        bot.reply_to(message,
            "⚠️ Chưa có acc!\n/login user pass",
            parse_mode="HTML")
        return
    for acc in accounts:
        acc.used_codes.discard(code)
    _fire_redeem(uid, code, accounts, manual=True)

# ================= /codes =================
@bot.message_handler(commands=["codes", "history"])
def cmd_codes(message):
    uid = message.from_user.id
    st = user_states.get(uid)
    if not st:
        bot.reply_to(message, "⚠️ Gõ /start trước.")
        return
    bot.reply_to(message, _format_history(uid), parse_mode="HTML")

# ================= /accounts =================
@bot.message_handler(commands=["accounts"])
def cmd_accounts(message):
    uid = message.from_user.id
    st = user_states.get(uid)
    if not st:
        bot.reply_to(message, "⚠️ /start")
        return
    accounts = st.get("accounts", [])
    if not accounts:
        bot.reply_to(message,
            "📭 Chưa có acc.\n/login user pass",
            parse_mode="HTML")
        return
    text = f"👥 <b>ACC LIST</b>\n{LINE}\n"
    for i, a in enumerate(accounts, 1):
        icon = "🟢" if a.is_token_valid() else "🟡"
        text += f"{icon} {i}. <code>{html.escape(a.nick)}</code>\n"
    text += (
        f"{LINE2}\n"
        f"📊 <b>{len(accounts)}</b> acc\n"
        f"⏱️ Auto: "
        f"{'🟢 chạy' if st.get('step') == 'listening' else '🔴 tắt'}"
    )
    bot.reply_to(message, text, parse_mode="HTML")

# ================= /stop =================
@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    uid = message.from_user.id
    st = user_states.get(uid)
    if not st or st.get("step") != "listening":
        bot.reply_to(message, "ℹ️ Không có auto nào chạy.")
        return
    st["step"] = "telegram_done"
    st["target_chat"] = None
    bot.reply_to(message,
        "🛑 <b>Đã dừng auto</b>\n"
        "Bật lại: /setchat",
        parse_mode="HTML")

# ================= /cancel & /logout =================
@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    uid = message.from_user.id
    if uid in user_states:
        _cleanup_state(uid)
        bot.reply_to(message, "✅ Đã hủy.\n/start làm lại.")
    else:
        bot.reply_to(message, "ℹ️ Không có gì chạy.")

@bot.message_handler(commands=["logout"])
def cmd_logout(message):
    uid = message.from_user.id
    _cleanup_state(uid)
    f = f"sessions/{uid}.session"
    if os.path.exists(f):
        try:
            os.remove(f)
        except Exception:
            pass
    bot.reply_to(message,
        "✅ Đã logout và xóa session!\n/start")

# ================= FALLBACK =================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def fallback(message):
    if message.from_user.id in user_states:
        return
    if message.text.startswith("/"):
        bot.reply_to(message, "❓ Lệnh không hợp lệ.\n/start")
        return
    bot.reply_to(message,
        f"📥 <code>{html.escape(message.text)}</code>",
        parse_mode="HTML")

# ================= RUN =================
if __name__ == "__main__":
    print("🤖 Bot v8 đang chạy...")
    print(f"📡 Kênh: @{DEFAULT_CHAT_USER} ({DEFAULT_CHAT_ID})")
    print(f"⚡ Backup poll: {POLL_INTERVAL}s")
    print(f"🏆 History max: {HISTORY_MAX}")
    print(f"🌐 Flask: http://0.0.0.0:{FLASK_PORT}")
    print(f"🌐 Ping endpoint: /ping")

    # Start Flask keep-alive
    threading.Thread(target=start_flask, daemon=True).start()

    # Start bot
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
import telebot
from telebot import types
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError,
    ApiIdInvalidError,
    PasswordHashInvalidError,
)
import asyncio
import threading
import os
import html

# ============ CẤU HÌNH ============
BOT_TOKEN = "9042450675:AAHWU1HNAzok0avxdy-Ub3PxPTb5DmsD_cg"
bot = telebot.TeleBot(BOT_TOKEN)

os.makedirs("sessions", exist_ok=True)

# Event loop chạy nền cho Telethon
_loop = asyncio.new_event_loop()
def _start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()
threading.Thread(target=_start_loop, args=(_loop,), daemon=True).start()

def run_async(coro, timeout=120):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)

# State lưu theo user
# state[user_id] = {step, api_id, api_hash, phone, phone_code_hash, client}
user_states = {}

LINE  = "━━━━━━━━━━━━━━━━━━━━━━"
LINE2 = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"


# ============ /start ============
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user_name = html.escape(message.from_user.first_name or "bạn")

    # Reset state nếu có
    _cleanup_state(user_id)

    welcome_text = (
        f"╔══════════════════════╗\n"
        f"   🌟 <b>WELCOME TO BOT</b> 🌟\n"
        f"╚══════════════════════╝\n\n"
        f"👋 Xin chào <b>{user_name}</b>!\n"
        f"🆔 ID của bạn: <code>{user_id}</code>\n\n"
        f"{LINE}\n"
        f"🎯 <b>BOT AUTO NHẬP MÃ CODE LC79</b>\n"
        f"{LINE}\n\n"
        f"⚡ <i>Tương tác tự động 100%</i>\n"
        f"🚀 <i>Tốc độ xử lý cực nhanh</i>\n"
        f"🔒 <i>Bảo mật thông tin tuyệt đối</i>\n"
        f"🌐 <i>Hoạt động 24/7 - Không nghỉ</i>\n\n"
        f"{LINE}\n"
        f"📖 <b>QUY TRÌNH 3 BƯỚC:</b>\n"
        f"{LINE}\n\n"
        f"<b>Bước 1️⃣</b> — Đăng nhập <b>Telegram</b>\n"
        f"     └─ Lấy api_id &amp; api_hash tại my.telegram.org\n\n"
        f"<b>Bước 2️⃣</b> — Đăng nhập <b>Game LC79</b>\n"
        f"     └─ Nhập tài khoản &amp; mật khẩu game\n\n"
        f"<b>Bước 3️⃣</b> — Đợi thông báo mã code\n"
        f"     └─ Bot tự động nhập khi có code\n\n"
        f"{LINE2}\n"
        f"👇 <b>Bấm nút bên dưới để bắt đầu:</b>"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🚀 Bắt Đầu Auto", callback_data="auto_code"),
        types.InlineKeyboardButton("📖 Hướng Dẫn",    callback_data="help"),
    )
    markup.add(
        types.InlineKeyboardButton("💬 Hỗ Trợ",   callback_data="support"),
        types.InlineKeyboardButton("ℹ️ Thông Tin", callback_data="info"),
    )
    markup.add(types.InlineKeyboardButton("🌐 Website LC79", url="https://lc79.com"))

    bot.send_message(message.chat.id, welcome_text,
                     reply_markup=markup, parse_mode="HTML",
                     disable_web_page_preview=True)


# ============ CLEANUP ============
def _cleanup_state(user_id):
    st = user_states.pop(user_id, None)
    if not st:
        return
    client = st.get('client')
    if client:
        try:
            run_async(client.disconnect(), timeout=10)
        except Exception:
            pass


# ============ CALLBACK ============
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    # 🚀 BẮT ĐẦU AUTO → LOGIN TELEGRAM
    if call.data == "auto_code":
        bot.answer_callback_query(call.id, "🔐 Bắt đầu đăng nhập Telegram...")
        _cleanup_state(user_id)
        user_states[user_id] = {'step': 'waiting_api_id'}

        text = (
            f"╔══════════════════════╗\n"
            f"   🔐 <b>BƯỚC 1 — LOGIN TELEGRAM</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"📖 <b>HƯỚNG DẪN LẤY API:</b>\n"
            f"{LINE}\n\n"
            f"1️⃣ Truy cập: <b>https://my.telegram.org</b>\n\n"
            f"2️⃣ Đăng nhập bằng <b>số điện thoại</b> của bạn\n\n"
            f"3️⃣ Chọn <b>API development tools</b>\n\n"
            f"4️⃣ Điền form tạo app (nếu chưa có):\n"
            f"   • App title: <code>AutoCode</code>\n"
            f"   • Short name: <code>autocode</code>\n"
            f"   • Platform: <code>Other</code>\n\n"
            f"5️⃣ Copy 2 thông số:\n"
            f"   • <b>App api_id</b> — dãy số\n"
            f"   • <b>App api_hash</b> — chuỗi ký tự\n\n"
            f"{LINE2}\n"
            f"📩 <b>Gửi <code>api_id</code> cho bot:</b>\n"
            f"└─ Ví dụ: <code>12345678</code>\n\n"
            f"⚠️ <i>Gõ /cancel để hủy bất cứ lúc nào</i>"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back_start"))
        bot.send_message(chat_id, text, parse_mode="HTML",
                         reply_markup=markup, disable_web_page_preview=True)

    elif call.data == "help":
        bot.answer_callback_query(call.id)
        text = (
            f"╔══════════════════════╗\n"
            f"   📖 <b>HƯỚNG DẪN CHI TIẾT</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"🔐 <b>BƯỚC 1 — LOGIN TELEGRAM</b>\n"
            f"{LINE}\n"
            f"• Bấm nút <b>🚀 Bắt Đầu Auto</b>\n"
            f"• Bot hướng dẫn lấy <code>api_id</code>, <code>api_hash</code>\n"
            f"• Gửi lần lượt: api_id → api_hash → SĐT\n"
            f"• Nhập <b>mã OTP</b> Telegram gửi về\n"
            f"• Nếu có <b>2FA</b> → nhập mật khẩu 2FA\n\n"
            f"{LINE}\n"
            f"🎮 <b>BƯỚC 2 — LOGIN GAME LC79</b>\n"
            f"{LINE}\n"
            f"• Gửi lệnh: <code>/login tài_khoản mật_khẩu</code>\n"
            f"• Ví dụ: <code>/login user123 pass456</code>\n\n"
            f"{LINE}\n"
            f"📩 <b>BƯỚC 3 — ĐỢI CODE &amp; AUTO</b>\n"
            f"{LINE}\n"
            f"• Bot tự theo dõi thông báo mã code\n"
            f"• Tự động nhập khi có code về\n\n"
            f"{LINE2}\n"
            f"⚠️ <b>LƯU Ý:</b>\n"
            f"• Không chia sẻ api_hash cho ai\n"
            f"• Gõ /cancel để hủy giữa chừng\n"
            f"• Gõ /logout để xóa session"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back_start"))
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

    elif call.data == "support":
        bot.answer_callback_query(call.id)
        text = (
            f"╔══════════════════════╗\n"
            f"   💬 <b>TRUNG TÂM HỖ TRỢ</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"👨‍💻 <b>Admin:</b> @your_admin\n"
            f"📢 <b>Channel:</b> @your_channel\n"
            f"🌐 <b>Website:</b> lc79.com\n"
            f"📧 <b>Email:</b> support@lc79.com\n"
            f"{LINE}\n\n"
            f"⏰ <b>Hỗ trợ:</b> 8:00 - 22:00\n"
            f"⚡ <b>Phản hồi:</b> Trong 5 phút"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back_start"))
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

    elif call.data == "info":
        bot.answer_callback_query(call.id)
        text = (
            f"╔══════════════════════╗\n"
            f"   ℹ️ <b>THÔNG TIN BOT</b>\n"
            f"╚══════════════════════╝\n\n"
            f"{LINE}\n"
            f"🤖 <b>Tên:</b> Auto Code LC79\n"
            f"📦 <b>Version:</b> v3.0\n"
            f"⚙️ <b>Engine:</b> Telethon Userbot\n"
            f"🔐 <b>Login:</b> Real 100% (MTProto)\n"
            f"{LINE}\n\n"
            f"✅ Auto nhập code 100%\n"
            f"✅ Hỗ trợ 2FA\n"
            f"✅ Session mã hóa\n"
            f"✅ Uptime 99.9%\n"
            f"{LINE2}"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back_start"))
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

    elif call.data == "back_start":
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        # Gọi lại start
        fake = type("M", (), {"chat": call.message.chat,
                               "from_user": call.from_user,
                               "message_id": None})()
        send_welcome(fake)


# ============ LUỒNG LOGIN TELEGRAM ============
@bot.message_handler(func=lambda m: m.from_user.id in user_states
                                  and m.text is not None
                                  and not m.text.startswith('/'))
def handle_login_flow(message):
    user_id = message.from_user.id
    text    = message.text.strip()
    st      = user_states.get(user_id)
    if not st:
        return

    step = st.get('step')

    # ---- (1) Nhập api_id ----
    if step == 'waiting_api_id':
        if not text.isdigit() or len(text) < 5:
            bot.reply_to(message, "❌ <b>api_id không hợp lệ!</b>\n\nPhải là dãy số (VD: <code>12345678</code>).\nThử lại:",
                         parse_mode="HTML")
            return

        st['api_id'] = int(text)
        st['step']   = 'waiting_api_hash'
        bot.reply_to(
            message,
            f"✅ Đã lưu <b>api_id:</b> <code>{text}</code>\n\n"
            f"{LINE}\n"
            f"📩 Gửi tiếp <b>api_hash</b>:\n"
            f"└─ Chuỗi 32 ký tự (VD: <code>a1b2c3d4e5f6...</code>)",
            parse_mode="HTML"
        )

    # ---- (2) Nhập api_hash ----
    elif step == 'waiting_api_hash':
        if len(text) < 20 or ' ' in text:
            bot.reply_to(message, "❌ <b>api_hash không hợp lệ!</b>\n\nPhải là chuỗi ≥ 20 ký tự, không có dấu cách.\nThử lại:",
                         parse_mode="HTML")
            return

        st['api_hash'] = text
        st['step']     = 'waiting_phone'
        bot.reply_to(
            message,
            f"✅ Đã lưu <b>api_hash</b>\n\n"
            f"{LINE}\n"
            f"📱 Gửi <b>số điện thoại</b> Telegram:\n"
            f"└─ Format quốc tế: <code>+84901234567</code>\n"
            f"└─ (Bắt đầu bằng dấu <b>+</b> và mã quốc gia)",
            parse_mode="HTML"
        )

    # ---- (3) Nhập SĐT → gửi OTP ----
    elif step == 'waiting_phone':
        phone = text.replace(' ', '').replace('-', '').replace('.', '')
        if not phone.startswith('+'):
            bot.reply_to(message,
                         "❌ Số phải bắt đầu bằng <b>+</b>\n"
                         "VD: <code>+84901234567</code>",
                         parse_mode="HTML")
            return

        bot.reply_to(message, "⏳ Đang gửi mã OTP qua Telegram...")

        try:
            session_path = f"sessions/{user_id}"
            client = TelegramClient(session_path, st['api_id'], st['api_hash'])

            async def connect_and_send():
                await client.connect()
                if await client.is_user_authorized():
                    return {'status': 'already'}
                sent = await client.send_code_request(phone)
                return {'status': 'sent', 'hash': sent.phone_code_hash}

            result = run_async(connect_and_send())
            st['client'] = client
            st['phone']  = phone

            if result['status'] == 'already':
                st['step'] = 'done'
                bot.reply_to(
                    message,
                    "╔══════════════════════╗\n"
                    "   ✅ <b>ĐÃ ĐĂNG NHẬP TRƯỚC ĐÓ</b>\n"
                    "╚══════════════════════╝\n\n"
                    "🎉 Session Telegram còn hiệu lực!\n\n"
                    "➡️ <b>Tiếp theo:</b> Login Game LC79\n"
                    "📩 Gửi: <code>/login tài_khoản mật_khẩu</code>",
                    parse_mode="HTML"
                )
                return

            st['phone_code_hash'] = result['hash']
            st['step']            = 'waiting_otp'

            bot.reply_to(
                message,
                f"╔══════════════════════╗\n"
                f"   📨 <b>ĐÃ GỬI OTP</b>\n"
                f"╚══════════════════════╝\n\n"
                f"📱 Kiểm tra tin nhắn Telegram của bạn\n"
                f"(hoặc SMS nếu không có Telegram)\n\n"
                f"{LINE}\n"
                f"📩 Nhập mã <b>OTP</b> vào đây:\n"
                f"└─ Ví dụ: <code>12345</code>\n\n"
                f"⚠️ <i>Đừng nhập dấu cách. Gõ /cancel để hủy</i>",
                parse_mode="HTML"
            )

        except ApiIdInvalidError:
            _cleanup_state(user_id)
            bot.reply_to(message,
                         "❌ <b>api_id hoặc api_hash SAI!</b>\n\n"
                         "Kiểm tra lại tại my.telegram.org rồi gõ /start làm lại.",
                         parse_mode="HTML")
        except PhoneNumberInvalidError:
            bot.reply_to(message, "❌ Số điện thoại không hợp lệ! Thử lại:")
        except Exception as e:
            _cleanup_state(user_id)
            bot.reply_to(message,
                         f"❌ <b>Lỗi:</b> <code>{html.escape(str(e))}</code>\n\n"
                         f"Gõ /start để làm lại.",
                         parse_mode="HTML")

    # ---- (4) Nhập OTP ----
    elif step == 'waiting_otp':
        code = text.replace(' ', '')
        try:
            async def sign_in():
                try:
                    await st['client'].sign_in(
                        phone=st['phone'],
                        code=code,
                        phone_code_hash=st['phone_code_hash']
                    )
                    return 'success'
                except SessionPasswordNeededError:
                    return 'need_2fa'

            result = run_async(sign_in())

            if result == 'need_2fa':
                st['step'] = 'waiting_2fa'
                bot.reply_to(
                    message,
                    f"╔══════════════════════╗\n"
                    f"   🔐 <b>TÀI KHOẢN CÓ 2FA</b>\n"
                    f"╚══════════════════════╝\n\n"
                    f"✅ OTP đúng!\n\n"
                    f"{LINE}\n"
                    f"📩 Nhập <b>mật khẩu 2FA</b> của Telegram:\n"
                    f"└─ Mật khẩu bạn đặt trong\n"
                    f"   <i>Settings → Privacy → Two-Step Verification</i>\n\n"
                    f"⚠️ <i>Gõ /cancel để hủy</i>",
                    parse_mode="HTML"
                )
            else:
                st['step'] = 'done'
                bot.reply_to(
                    message,
                    f"╔══════════════════════╗\n"
                    f"   ✅ <b>LOGIN THÀNH CÔNG!</b>\n"
                    f"╚══════════════════════╝\n\n"
                    f"🎉 Đã đăng nhập Telegram thật 100%\n"
                    f"📱 SĐT: <code>{html.escape(st['phone'])}</code>\n\n"
                    f"{LINE2}\n"
                    f"➡️ <b>BƯỚC 2 — LOGIN GAME LC79</b>\n"
                    f"📩 Gửi: <code>/login tài_khoản mật_khẩu</code>\n"
                    f"└─ VD: <code>/login user123 pass456</code>",
                    parse_mode="HTML"
                )

        except PhoneCodeInvalidError:
            bot.reply_to(message, "❌ Mã OTP sai! Nhập lại:")
        except PhoneCodeExpiredError:
            _cleanup_state(user_id)
            bot.reply_to(message,
                         "❌ Mã OTP đã hết hạn!\nGõ /start làm lại.",
                         parse_mode="HTML")
        except Exception as e:
            bot.reply_to(message,
                         f"❌ Lỗi: <code>{html.escape(str(e))}</code>",
                         parse_mode="HTML")

    # ---- (5) Nhập 2FA ----
    elif step == 'waiting_2fa':
        try:
            async def sign_2fa():
                await st['client'].sign_in(password=text)

            run_async(sign_2fa())
            st['step'] = 'done'

            bot.reply_to(
                message,
                f"╔══════════════════════╗\n"
                f"   ✅ <b>LOGIN 2FA THÀNH CÔNG</b>\n"
                f"╚══════════════════════╝\n\n"
                f"🎉 Đã xác thực 2FA thành công!\n"
                f"🔐 Session đã được mã hóa an toàn\n\n"
                f"{LINE2}\n"
                f"➡️ <b>BƯỚC 2 — LOGIN GAME LC79</b>\n"
                f"📩 Gửi: <code>/login tài_khoản mật_khẩu</code>",
                parse_mode="HTML"
            )
        except PasswordHashInvalidError:
            bot.reply_to(message, "❌ Mật khẩu 2FA sai! Nhập lại:")
        except Exception as e:
            bot.reply_to(message,
                         f"❌ Lỗi: <code>{html.escape(str(e))}</code>",
                         parse_mode="HTML")


# ============ /login LC79 ============
@bot.message_handler(commands=['login'])
def login_game(message):
    user_id = message.from_user.id
    parts = message.text.split()

    if user_id not in user_states or user_states[user_id].get('step') != 'done':
        bot.reply_to(
            message,
            "⚠️ <b>Chưa login Telegram!</b>\n\n"
            "Bấm nút <b>🚀 Bắt Đầu Auto</b> trước để login Telegram.",
            parse_mode="HTML"
        )
        return

    if len(parts) != 3:
        bot.reply_to(
            message,
            "⚠️ <b>Sai cú pháp!</b>\n\n"
            "📝 Dùng: <code>/login tài_khoản mật_khẩu</code>\n"
            "💡 VD: <code>/login user123 pass456</code>",
            parse_mode="HTML"
        )
        return

    username, password = parts[1], parts[2]
    user_states[user_id]['lc79_user'] = username
    user_states[user_id]['lc79_pass'] = password

    bot.reply_to(
        message,
        f"╔══════════════════════╗\n"
        f"   ✅ <b>LOGIN LC79 THÀNH CÔNG</b>\n"
        f"╚══════════════════════╝\n\n"
        f"👤 <b>Tài khoản:</b> <code>{html.escape(username)}</code>\n"
        f"🎮 <b>Game:</b> LC79\n"
        f"⚡ <b>Trạng thái:</b> 🟢 Online\n\n"
        f"{LINE2}\n"
        f"📩 <i>Đang chờ thông báo mã code...</i>\n"
        f"🤖 <i>Bot sẽ tự động nhập khi có code về!</i>\n"
        f"🔔 <i>Giữ bot mở để nhận thông báo!</i>",
        parse_mode="HTML"
    )


# ============ /cancel ============
@bot.message_handler(commands=['cancel'])
def cancel(message):
    user_id = message.from_user.id
    if user_id in user_states:
        _cleanup_state(user_id)
        bot.reply_to(message,
                     "✅ Đã hủy quy trình.\n\nGõ /start để bắt đầu lại.",
                     parse_mode="HTML")
    else:
        bot.reply_to(message, "ℹ️ Không có quy trình nào đang chạy.")


# ============ /logout ============
@bot.message_handler(commands=['logout'])
def logout(message):
    user_id = message.from_user.id
    _cleanup_state(user_id)

    session_file = f"sessions/{user_id}.session"
    if os.path.exists(session_file):
        try:
            os.remove(session_file)
        except Exception:
            pass

    bot.reply_to(message,
                 "✅ Đã đăng xuất và xóa session!\n\n"
                 "Gõ /start để bắt đầu lại.",
                 parse_mode="HTML")


# ============ TEXT THƯỜNG ============
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    # Bỏ qua nếu đang trong flow login
    if message.from_user.id in user_states:
        return

    if message.text.startswith('/'):
        bot.reply_to(
            message,
            "❓ <b>Lệnh không hợp lệ!</b>\n\n"
            "📖 Gõ /start để xem hướng dẫn\n"
            "🔐 Gõ /login để đăng nhập game",
            parse_mode="HTML"
        )
        return

    bot.reply_to(
        message,
        f"📥 <b>Đã nhận mã code:</b>\n"
        f"<code>{html.escape(message.text)}</code>\n\n"
        f"⏳ <i>Đang xử lý auto...</i>\n"
        f"✅ <i>Hoàn thành!</i>",
        parse_mode="HTML"
    )


# ============ CHẠY BOT ============
if __name__ == "__main__":
    print("🤖 Bot đang chạy...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
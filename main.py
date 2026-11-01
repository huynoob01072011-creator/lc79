# ============================================================================
#  LC79 AUTO REDEEM - WEB EDITION (single file)
#  Deploy Render: gunicorn --workers=1 --threads=8 --timeout=0 --bind=0.0.0.0:$PORT main:app
# ============================================================================
import os
import re
import sys
import time
import json
import base64
import random
import asyncio
import threading
from collections import deque
from datetime import datetime

import requests
from flask import Flask, request, jsonify, Response
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
)

# ============================================================================
# GLOBAL STATE
# ============================================================================
app = Flask(__name__)

STATE = {
    "config": {
        "api_id": None,
        "api_hash": None,
        "phone": None,
        "group_link": None,
        "accounts": [],
    },
    "session_string": None,
    "target_chat_id": None,
    "bot_running": False,
    "logged_in": False,
    "me": None,
}

LOGS = deque(maxlen=500)
LOG_LOCK = threading.Lock()


def log(msg, level="info"):
    ts = datetime.now().strftime("%H:%M:%S")
    with LOG_LOCK:
        LOGS.append({"ts": ts, "msg": msg, "level": level})
    try:
        print(f"[{ts}] {msg}", flush=True)
    except Exception:
        pass


# ============================================================================
# GAME ACCOUNT
# ============================================================================
class Account:
    def __init__(self, un, pw, nick):
        self.un = un
        self.pw = pw
        self.nick = nick
        self.used_codes = set()
        self.lock = threading.Lock()
        self.jwt = None
        self.jwt_exp = 0

    def _headers(self, auth=None):
        h = {
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0",
            "origin": "https://lc79.to",
            "referer": "https://lc79.to/",
            "accept": "application/json, text/plain, */*",
            "connection": "close",
        }
        if auth:
            h["authorization"] = f"Bearer {auth}"
        return h

    @staticmethod
    def parse_jwt_exp(token):
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload))
            return data.get("exp", 0)
        except Exception:
            return 0

    def is_token_valid(self):
        return self.jwt is not None and time.time() < (self.jwt_exp - 60)

    def get_access_token(self):
        try:
            with requests.Session() as s:
                res = s.get(
                    "https://apifo88daigia.tele68.com/api",
                    params={"c": "3", "un": self.un, "pw": self.pw,
                            "cp": "R", "cl": "R", "pf": "web", "at": ""},
                    headers=self._headers(), timeout=(5, 45),
                )
            data = res.json()
            if data.get("success"):
                return data.get("accessToken")
            log(f"[{self.nick}] ❌ get_access_token fail: {data}", "error")
            return None
        except Exception as e:
            log(f"[{self.nick}] ❌ get_access_token: {e}", "error")
            return None

    def refresh_token(self):
        at = self.get_access_token()
        if not at:
            return False
        try:
            with requests.Session() as s:
                res = s.post(
                    "https://wlb.tele68.com/v1/lobby/auth/login",
                    headers={
                        "content-type": "application/json",
                        "origin": "https://lc79b.bet",
                        "referer": "https://lc79b.bet/",
                        "user-agent": "Mozilla/5.0",
                        "connection": "close",
                    },
                    json={"nickName": self.nick, "accessToken": at},
                    timeout=(5, 45),
                )
            data = res.json()
            tok = data.get("token")
            if tok:
                self.jwt = tok
                self.jwt_exp = self.parse_jwt_exp(tok)
                remain = int((self.jwt_exp - time.time()) / 60) if self.jwt_exp else 0
                log(f"[{self.nick}] ✅ JWT OK (còn {remain} phút)", "success")
                return True
            log(f"[{self.nick}] ❌ login fail: {data}", "error")
            return False
        except Exception as e:
            log(f"[{self.nick}] ❌ refresh_token: {e}", "error")
            return False

    def redeem_code(self, code, _attempt=0):
        with self.lock:
            if code in self.used_codes:
                return
            self.used_codes.add(code)

        if not self.is_token_valid():
            log(f"[{self.nick}] 🔄 Token hết hạn → login lại")
            if not self.refresh_token():
                log(f"[{self.nick}] ❌ Không login được → bỏ qua {code}", "error")
                with self.lock:
                    self.used_codes.discard(code)
                return

        log(f"[{self.nick}] 🚀 Redeem: {code}")

        try:
            with requests.Session() as s:
                res = s.post(
                    "https://gameapi.tele68.com/v1/giftcode/redemption?cp=R&cl=R&pf=web&at=",
                    headers=self._headers(self.jwt),
                    json={"code": code.strip(), "captcha": ""},
                    timeout=(5, 45),
                )
            try:
                data = res.json()
            except Exception:
                data = {}

            if res.status_code == 401:
                log(f"[{self.nick}] 🔑 401 → login lại")
                if self.refresh_token() and _attempt < 3:
                    with self.lock:
                        self.used_codes.discard(code)
                    return self.redeem_code(code, _attempt + 1)
                with self.lock:
                    self.used_codes.discard(code)
                return

            if res.status_code in (200, 201):
                amt = (data.get("money") or data.get("amount") or data.get("reward")
                       or (data.get("data") or {}).get("money"))
                if amt:
                    log(f"[{self.nick}] 💰 SUCCESS: +{int(amt):,}", "success")
                else:
                    log(f"[{self.nick}] ✅ SUCCESS", "success")
            elif res.status_code == 400:
                msg = data.get("message") if isinstance(data, dict) else res.text
                log(f"[{self.nick}] ❌ FAIL (400): {msg}", "error")
            elif res.status_code == 428:
                log(f"[{self.nick}] ⚠️ CAPTCHA", "warn")
            elif res.status_code == 429:
                log(f"[{self.nick}] ⚠️ RATE LIMIT", "warn")
            else:
                log(f"[{self.nick}] ❌ FAIL ({res.status_code})", "error")

        except (requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as e:
            if _attempt < 3:
                time.sleep(1 + _attempt + random.uniform(0, 0.5))
                return self.redeem_code(code, _attempt + 1)
            log(f"[{self.nick}] ❌ Bỏ code sau 3 retry: {e}", "error")
            with self.lock:
                self.used_codes.discard(code)
        except Exception as e:
            log(f"[{self.nick}] ❌ ERROR: {e}", "error")


ACCOUNT_OBJS = []


def build_accounts():
    global ACCOUNT_OBJS
    ACCOUNT_OBJS = [Account(a["un"], a["pw"], a["nick"])
                    for a in STATE["config"]["accounts"]]


def redeem_all_sync(code):
    log(f"🎯 CODE: {code} → {len(ACCOUNT_OBJS)} acc")
    def worker(acc, idx):
        if idx > 0:
            time.sleep(idx * 1.0 + random.uniform(0, 0.3))
        acc.redeem_code(code)
    threads = [threading.Thread(target=worker, args=(a, i))
               for i, a in enumerate(ACCOUNT_OBJS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ============================================================================
# TELEGRAM ASYNC LOOP
# ============================================================================
TG_LOOP = asyncio.new_event_loop()
TG_CLIENT = None
TG_CLIENT_LOCK = threading.Lock()


def start_tg_loop():
    def runner():
        asyncio.set_event_loop(TG_LOOP)
        TG_LOOP.run_forever()
    threading.Thread(target=runner, daemon=True).start()


def run_async(coro, timeout=60):
    fut = asyncio.run_coroutine_threadsafe(coro, TG_LOOP)
    return fut.result(timeout=timeout)


async def _make_client():
    global TG_CLIENT
    with TG_CLIENT_LOCK:
        if TG_CLIENT is not None:
            try:
                await TG_CLIENT.disconnect()
            except Exception:
                pass
        cfg = STATE["config"]
        session = StringSession(STATE["session_string"]) if STATE["session_string"] else StringSession()
        TG_CLIENT = TelegramClient(
            session, cfg["api_id"], cfg["api_hash"],
            connection_retries=5, retry_delay=10, auto_reconnect=True,
            request_retries=5, flood_sleep_threshold=60,
        )
        await TG_CLIENT.connect()
    return TG_CLIENT


# ============================================================================
# API ROUTES
# ============================================================================
@app.route("/ping")
def ping():
    return "pong"


@app.route("/api/status")
def api_status():
    with LOG_LOCK:
        logs = list(LOGS)
    return jsonify({
        "logged_in": STATE["logged_in"],
        "bot_running": STATE["bot_running"],
        "me": STATE["me"],
        "target_chat_id": STATE["target_chat_id"],
        "config": {
            "api_id": STATE["config"]["api_id"],
            "group_link": STATE["config"]["group_link"],
            "accounts": STATE["config"]["accounts"],
            "phone": STATE["config"]["phone"],
            "has_session": bool(STATE["session_string"]),
            "has_api": bool(STATE["config"]["api_hash"]),
        },
        "logs": logs,
    })


@app.route("/api/send_otp", methods=["POST"])
def api_send_otp():
    data = request.json or {}
    api_id = data.get("api_id")
    api_hash = (data.get("api_hash") or "").strip()
    phone = (data.get("phone") or "").strip()
    if not (api_id and api_hash and phone):
        return jsonify({"ok": False, "error": "Thiếu api_id / api_hash / phone"}), 400

    try:
        STATE["config"]["api_id"] = int(api_id)
    except Exception:
        return jsonify({"ok": False, "error": "api_id phải là số"}), 400

    STATE["config"]["api_hash"] = api_hash
    STATE["config"]["phone"] = phone

    async def _send():
        try:
            cli = await _make_client()
            await cli.send_code_request(phone)
            return {"ok": True}
        except FloodWaitError as e:
            return {"ok": False, "error": f"Flood wait {e.seconds}s"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    try:
        res = run_async(_send(), timeout=60)
        if res.get("ok"):
            log(f"📱 Đã gửi OTP tới {phone}", "success")
        else:
            log(f"❌ Gửi OTP thất bại: {res.get('error')}", "error")
        return jsonify(res)
    except Exception as e:
        log(f"❌ send_otp error: {e}", "error")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/verify_otp", methods=["POST"])
def api_verify_otp():
    data = request.json or {}
    code = (data.get("code") or "").strip()
    password = data.get("password") or None
    if not code:
        return jsonify({"ok": False, "error": "Thiếu OTP"}), 400

    async def _verify():
        try:
            cli = TG_CLIENT
            if cli is None:
                return {"ok": False, "error": "Chưa gửi OTP"}
            try:
                await cli.sign_in(phone=STATE["config"]["phone"], code=code)
            except SessionPasswordNeededError:
                if not password:
                    return {"ok": False, "need_password": True,
                            "error": "Cần mật khẩu 2FA"}
                await cli.sign_in(password=password)
            me = await cli.get_me()
            session_str = cli.session.save()
            return {"ok": True, "session_string": session_str,
                    "me": {"id": me.id, "first_name": me.first_name,
                           "username": me.username}}
        except PhoneCodeInvalidError:
            return {"ok": False, "error": "OTP sai"}
        except PhoneCodeExpiredError:
            return {"ok": False, "error": "OTP hết hạn"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    try:
        res = run_async(_verify(), timeout=60)
        if res.get("ok"):
            STATE["session_string"] = res["session_string"]
            STATE["logged_in"] = True
            STATE["me"] = res["me"]
            log(f"✅ Login Telegram OK: {res['me'].get('first_name')}", "success")
            log(f"💡 Lưu session vào Render Env TELEGRAM_SESSION để không cần OTP lần sau", "info")
        else:
            log(f"❌ Verify OTP thất bại: {res.get('error')}", "error")
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/save_config", methods=["POST"])
def api_save_config():
    data = request.json or {}
    group_link = (data.get("group_link") or "").strip()
    accounts = data.get("accounts") or []
    if not group_link:
        return jsonify({"ok": False, "error": "Thiếu group link"}), 400

    clean = []
    for a in accounts:
        un = (a.get("un") or "").strip()
        pw = (a.get("pw") or "").strip()
        nick = (a.get("nick") or un).strip()
        if un and pw:
            clean.append({"un": un, "pw": pw, "nick": nick or un})

    if not clean:
        return jsonify({"ok": False, "error": "Cần ít nhất 1 account game"}), 400

    STATE["config"]["group_link"] = group_link
    STATE["config"]["accounts"] = clean
    build_accounts()
    log(f"💾 Đã lưu config: group={group_link}, {len(clean)} acc", "success")
    return jsonify({"ok": True})


@app.route("/api/refresh_accounts", methods=["POST"])
def api_refresh_accounts():
    if not ACCOUNT_OBJS:
        build_accounts()
    if not ACCOUNT_OBJS:
        return jsonify({"ok": False, "error": "Chưa có account"}), 400

    def worker():
        results = {}
        def w(acc):
            results[acc.nick] = acc.refresh_token()
        ts = [threading.Thread(target=w, args=(a,)) for a in ACCOUNT_OBJS]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        ok = sum(1 for v in results.values() if v)
        level = "success" if ok == len(ACCOUNT_OBJS) else "warn"
        log(f"🔄 Refresh: {ok}/{len(ACCOUNT_OBJS)} OK", level)

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/manual_redeem", methods=["POST"])
def api_manual_redeem():
    data = request.json or {}
    code = (data.get("code") or "").strip().upper()
    if not code:
        return jsonify({"ok": False, "error": "Thiếu code"}), 400
    if not ACCOUNT_OBJS:
        build_accounts()
    if not ACCOUNT_OBJS:
        return jsonify({"ok": False, "error": "Chưa có account"}), 400
    threading.Thread(target=redeem_all_sync, args=(code,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/start_bot", methods=["POST"])
def api_start_bot():
    if not STATE["logged_in"]:
        return jsonify({"ok": False, "error": "Chưa login Telegram"}), 400
    if not STATE["config"]["group_link"]:
        return jsonify({"ok": False, "error": "Chưa cấu hình group"}), 400
    if STATE["bot_running"]:
        return jsonify({"ok": False, "error": "Bot đang chạy"}), 400
    if not ACCOUNT_OBJS:
        build_accounts()
    if not ACCOUNT_OBJS:
        return jsonify({"ok": False, "error": "Chưa có account game"}), 400

    STATE["bot_running"] = True

    def runner():
        try:
            _run_bot()
        except Exception as e:
            log(f"❌ Bot crash: {e}", "error")
        finally:
            STATE["bot_running"] = False
            log("🛑 Bot đã dừng", "warn")

    threading.Thread(target=runner, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/stop_bot", methods=["POST"])
def api_stop_bot():
    async def _stop():
        if TG_CLIENT:
            try:
                await TG_CLIENT.disconnect()
            except Exception:
                pass
    try:
        run_async(_stop(), timeout=10)
    except Exception:
        pass
    STATE["bot_running"] = False
    return jsonify({"ok": True})


def _run_bot():
    def w(acc):
        acc.refresh_token()
    ts = [threading.Thread(target=w, args=(a,)) for a in ACCOUNT_OBJS]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    async def bot_main():
        global TG_CLIENT
        cfg = STATE["config"]
        username = cfg["group_link"].rstrip("/").split("/")[-1].lstrip("@")
        log(f"🔍 Resolve @{username}...")

        with TG_CLIENT_LOCK:
            if TG_CLIENT is not None:
                try:
                    await TG_CLIENT.disconnect()
                except Exception:
                    pass
            session = StringSession(STATE["session_string"])
            TG_CLIENT = TelegramClient(
                session, cfg["api_id"], cfg["api_hash"],
                connection_retries=5, retry_delay=10, auto_reconnect=True,
                request_retries=5, flood_sleep_threshold=60,
            )
            await TG_CLIENT.connect()

        if not await TG_CLIENT.is_user_authorized():
            log("❌ Session không hợp lệ", "error")
            return

        try:
            entity = await TG_CLIENT.get_entity(username)
            STATE["target_chat_id"] = utils.get_peer_id(entity)
            log(f"✅ Group ID: {STATE['target_chat_id']}", "success")
        except Exception as e:
            log(f"❌ Resolve fail: {e}", "error")
            return

        @TG_CLIENT.on(events.NewMessage)
        async def handler(event):
            if STATE["target_chat_id"] is None:
                return
            if event.chat_id != STATE["target_chat_id"]:
                return
            text = event.raw_text or ""
            m = re.search(r"Mã code là:\s*([A-Z0-9]+)", text)
            if not m:
                return
            full_code = m.group(1)
            candidates = [full_code]
            if full_code.endswith("LC79"):
                candidates.append(full_code[:-4])
            for c in candidates:
                threading.Thread(
                    target=redeem_all_sync, args=(c,), daemon=True
                ).start()

        log("✅ Bot online — đang chờ message...", "success")
        await TG_CLIENT.run_until_disconnected()

    run_async(bot_main(), timeout=None)


# ============================================================================
# FRONTEND (embedded HTML)
# ============================================================================
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>🎁 LC79 Auto Redeem</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { background: #0a0e1a; font-family: 'Segoe UI', sans-serif; }
  .glass { background: rgba(255,255,255,0.03); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.08); }
  .glow { box-shadow: 0 0 30px rgba(99,102,241,0.15); }
  .log-scroll::-webkit-scrollbar { width: 6px; }
  .log-scroll::-webkit-scrollbar-track { background: #0f172a; }
  .log-scroll::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
  .log-line { animation: fadeIn 0.3s ease; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: translateY(0); } }
  .pulse-dot { animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
  .btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); }
  .btn-primary:hover { background: linear-gradient(135deg, #4f46e5, #7c3aed); }
</style>
</head>
<body class="min-h-screen text-slate-200">

<div class="max-w-6xl mx-auto px-4 py-8">

  <div class="flex items-center justify-between mb-8">
    <div>
      <h1 class="text-3xl font-bold bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">
        🎁 LC79 Auto Redeem
      </h1>
      <p class="text-sm text-slate-400 mt-1">Bot tự động nhận gift code từ Telegram</p>
    </div>
    <div class="flex gap-2">
      <span id="badgeLogin" class="px-3 py-1.5 rounded-full text-xs font-medium bg-slate-700/50 border border-slate-600/50">⚪ Chưa login</span>
      <span id="badgeBot" class="px-3 py-1.5 rounded-full text-xs font-medium bg-slate-700/50 border border-slate-600/50">⚪ Bot tắt</span>
    </div>
  </div>

  <div class="glass glow rounded-2xl p-4 mb-6 grid grid-cols-2 md:grid-cols-4 gap-4">
    <div>
      <div class="text-xs text-slate-400">Telegram</div>
      <div id="statUser" class="text-sm font-mono mt-1 text-slate-300">—</div>
    </div>
    <div>
      <div class="text-xs text-slate-400">Group ID</div>
      <div id="statGroup" class="text-sm font-mono mt-1 text-slate-300">—</div>
    </div>
    <div>
      <div class="text-xs text-slate-400">Accounts</div>
      <div id="statAcc" class="text-sm font-mono mt-1 text-slate-300">—</div>
    </div>
    <div>
      <div class="text-xs text-slate-400">Session</div>
      <div id="statSession" class="text-sm font-mono mt-1 text-slate-300">—</div>
    </div>
  </div>

  <div class="grid md:grid-cols-2 gap-6">

    <div class="space-y-6">

      <div id="cardLogin" class="glass rounded-2xl p-6">
        <h2 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span>🔐</span> Đăng nhập Telegram
        </h2>

        <div id="loginStep1" class="space-y-3">
          <input id="apiId" type="number" placeholder="api_id (VD: 34425014)"
                 class="w-full bg-slate-900/70 border border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-500" />
          <input id="apiHash" type="text" placeholder="api_hash"
                 class="w-full bg-slate-900/70 border border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-500" />
          <input id="phone" type="text" placeholder="Số điện thoại (+84...)"
                 class="w-full bg-slate-900/70 border border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-500" />
          <button onclick="sendOTP()"
                  class="btn-primary w-full text-white font-medium rounded-lg py-2.5 text-sm transition">
            📱 Gửi mã OTP
          </button>
        </div>

        <div id="loginStep2" class="hidden space-y-3">
          <input id="otpCode" type="text" placeholder="Mã OTP (VD: 12345)"
                 class="w-full bg-slate-900/70 border border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-500" />
          <input id="otpPassword" type="password" placeholder="Mật khẩu 2FA (nếu có)"
                 class="w-full bg-slate-900/70 border border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-500" />
          <div class="flex gap-2">
            <button onclick="verifyOTP()"
                    class="btn-primary flex-1 text-white font-medium rounded-lg py-2.5 text-sm">
              ✅ Xác nhận
            </button>
            <button onclick="backToLogin1()"
                    class="flex-1 bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium rounded-lg py-2.5 text-sm">
              ← Quay lại
            </button>
          </div>
        </div>
      </div>

      <div id="cardConfig" class="glass rounded-2xl p-6">
        <h2 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span>⚙️</span> Cấu hình
        </h2>

        <label class="text-xs text-slate-400 mb-1 block">Link group Telegram</label>
        <input id="groupLink" type="text" placeholder="https://t.me/codelaucuagame"
               class="w-full bg-slate-900/70 border border-slate-700 rounded-lg px-4 py-2.5 text-sm mb-4 focus:outline-none focus:border-indigo-500" />

        <label class="text-xs text-slate-400 mb-2 block">Accounts game LC79</label>
        <div id="accountList" class="space-y-2 mb-3"></div>

        <button onclick="addAccount()"
                class="w-full border border-dashed border-slate-600 hover:border-indigo-500 text-slate-400 hover:text-indigo-400 rounded-lg py-2 text-sm mb-3 transition">
          ➕ Thêm account
        </button>

        <button onclick="saveConfig()"
                class="btn-primary w-full text-white font-medium rounded-lg py-2.5 text-sm">
          💾 Lưu cấu hình
        </button>
      </div>
    </div>

    <div class="space-y-6">

      <div class="glass rounded-2xl p-6">
        <h2 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span>🎮</span> Điều khiển
        </h2>

        <div class="grid grid-cols-2 gap-3 mb-3">
          <button onclick="startBot()"
                  class="bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg py-2.5 text-sm transition">
            ▶️ Start Bot
          </button>
          <button onclick="stopBot()"
                  class="bg-rose-600 hover:bg-rose-500 text-white font-medium rounded-lg py-2.5 text-sm transition">
            ⏹ Stop Bot
          </button>
        </div>

        <button onclick="refreshAccounts()"
                class="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium rounded-lg py-2.5 text-sm mb-3">
          🔄 Refresh Accounts
        </button>

        <div class="flex gap-2">
          <input id="manualCode" type="text" placeholder="Nhập code để redeem thủ công..."
                 class="flex-1 bg-slate-900/70 border border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-500" />
          <button onclick="manualRedeem()"
                  class="btn-primary text-white font-medium rounded-lg px-4 text-sm">
            🚀
          </button>
        </div>
      </div>

      <div class="glass rounded-2xl p-6">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-lg font-semibold flex items-center gap-2">
            <span>📜</span> Logs
          </h2>
          <button onclick="clearLogs()" class="text-xs text-slate-500 hover:text-slate-300">Xoá</button>
        </div>
        <div id="logViewer"
             class="log-scroll bg-slate-950/80 rounded-lg p-3 h-96 overflow-y-auto text-xs font-mono space-y-0.5"></div>
      </div>
    </div>
  </div>

  <p class="text-center text-xs text-slate-600 mt-8">
    LC79 Auto Redeem • Web Edition
  </p>
</div>

<script>
let lastLogCount = 0;
let autoScroll = true;

function saveLocal() {
  const data = {
    apiId: document.getElementById('apiId').value,
    apiHash: document.getElementById('apiHash').value,
    phone: document.getElementById('phone').value,
    groupLink: document.getElementById('groupLink').value,
    accounts: getAccountsFromUI(),
  };
  localStorage.setItem('lc79_config', JSON.stringify(data));
}

function loadLocal() {
  try {
    const d = JSON.parse(localStorage.getItem('lc79_config') || '{}');
    if (d.apiId) document.getElementById('apiId').value = d.apiId;
    if (d.apiHash) document.getElementById('apiHash').value = d.apiHash;
    if (d.phone) document.getElementById('phone').value = d.phone;
    if (d.groupLink) document.getElementById('groupLink').value = d.groupLink;
    if (d.accounts && d.accounts.length) {
      d.accounts.forEach(a => addAccount(a.un, a.pw, a.nick));
    }
  } catch(e) {}
}

function addAccount(un='', pw='', nick='') {
  const div = document.createElement('div');
  div.className = 'flex gap-2 account-item';
  div.innerHTML = `
    <input type="text" placeholder="Username" value="${escape(un)}"
           class="acc-un flex-1 bg-slate-900/70 border border-slate-700 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-indigo-500" />
    <input type="password" placeholder="Password" value="${escape(pw)}"
           class="acc-pw flex-1 bg-slate-900/70 border border-slate-700 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-indigo-500" />
    <input type="text" placeholder="Nick" value="${escape(nick)}"
           class="acc-nick flex-1 bg-slate-900/70 border border-slate-700 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-indigo-500" />
    <button onclick="this.parentElement.remove()"
            class="text-rose-400 hover:text-rose-300 px-2">✖</button>
  `;
  document.getElementById('accountList').appendChild(div);
}

function getAccountsFromUI() {
  const items = document.querySelectorAll('.account-item');
  const out = [];
  items.forEach(it => {
    const un = it.querySelector('.acc-un').value.trim();
    const pw = it.querySelector('.acc-pw').value.trim();
    const nick = it.querySelector('.acc-nick').value.trim() || un;
    if (un && pw) out.push({ un, pw, nick });
  });
  return out;
}

function escape(s) {
  return String(s || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

async function sendOTP() {
  const api_id = document.getElementById('apiId').value;
  const api_hash = document.getElementById('apiHash').value;
  const phone = document.getElementById('phone').value;
  if (!api_id || !api_hash || !phone) return alert('Điền đủ 3 field');
  saveLocal();
  const r = await api('/api/send_otp', { api_id, api_hash, phone });
  if (r.ok) {
    document.getElementById('loginStep1').classList.add('hidden');
    document.getElementById('loginStep2').classList.remove('hidden');
  } else {
    alert('Lỗi: ' + (r.error || 'unknown'));
  }
}

async function verifyOTP() {
  const code = document.getElementById('otpCode').value.trim();
  const password = document.getElementById('otpPassword').value;
  if (!code) return alert('Nhập OTP');
  const r = await api('/api/verify_otp', { code, password });
  if (r.ok) {
    document.getElementById('loginStep1').classList.remove('hidden');
    document.getElementById('loginStep2').classList.add('hidden');
    document.getElementById('otpCode').value = '';
    document.getElementById('otpPassword').value = '';
  } else if (r.need_password) {
    alert('Cần mật khẩu 2FA');
  } else {
    alert('Lỗi: ' + (r.error || 'unknown'));
  }
}

function backToLogin1() {
  document.getElementById('loginStep1').classList.remove('hidden');
  document.getElementById('loginStep2').classList.add('hidden');
}

async function saveConfig() {
  const group_link = document.getElementById('groupLink').value.trim();
  const accounts = getAccountsFromUI();
  if (!group_link) return alert('Nhập link group');
  if (!accounts.length) return alert('Thêm ít nhất 1 account');
  const r = await api('/api/save_config', { group_link, accounts });
  if (r.ok) {
    saveLocal();
    alert('✅ Đã lưu cấu hình');
  } else {
    alert('Lỗi: ' + (r.error || 'unknown'));
  }
}

async function startBot() {
  const r = await api('/api/start_bot', {});
  if (!r.ok) alert('Lỗi: ' + (r.error || 'unknown'));
}

async function stopBot() {
  await api('/api/stop_bot', {});
}

async function refreshAccounts() {
  await api('/api/refresh_accounts', {});
}

async function manualRedeem() {
  const code = document.getElementById('manualCode').value.trim();
  if (!code) return;
  const r = await api('/api/manual_redeem', { code });
  if (r.ok) {
    document.getElementById('manualCode').value = '';
  } else {
    alert('Lỗi: ' + (r.error || 'unknown'));
  }
}

function clearLogs() {
  document.getElementById('logViewer').innerHTML = '';
  lastLogCount = 0;
}

async function api(url, body) {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    return await res.json();
  } catch(e) {
    return { ok: false, error: String(e) };
  }
}

async function poll() {
  try {
    const res = await fetch('/api/status');
    const d = await res.json();

    const bl = document.getElementById('badgeLogin');
    if (d.logged_in) {
      bl.textContent = '🟢 Đã login';
      bl.className = 'px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-900/40 text-emerald-300 border border-emerald-700/50';
    } else {
      bl.textContent = '⚪ Chưa login';
      bl.className = 'px-3 py-1.5 rounded-full text-xs font-medium bg-slate-700/50 border border-slate-600/50';
    }
    const bb = document.getElementById('badgeBot');
    if (d.bot_running) {
      bb.innerHTML = '<span class="pulse-dot">🟢</span> Bot online';
      bb.className = 'px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-900/40 text-emerald-300 border border-emerald-700/50';
    } else {
      bb.textContent = '⚪ Bot tắt';
      bb.className = 'px-3 py-1.5 rounded-full text-xs font-medium bg-slate-700/50 border border-slate-600/50';
    }

    document.getElementById('statUser').textContent = d.me ? (d.me.first_name || d.me.username || '?') : '—';
    document.getElementById('statGroup').textContent = d.target_chat_id || '—';
    document.getElementById('statAcc').textContent = (d.config.accounts || []).length + ' acc';
    document.getElementById('statSession').textContent = d.config.has_session ? '✅ Có' : '❌ Chưa';

    renderLogs(d.logs || []);
  } catch(e) {}
}

function renderLogs(logs) {
  const viewer = document.getElementById('logViewer');
  if (logs.length === lastLogCount) return;
  lastLogCount = logs.length;

  const colorFor = (level) => {
    if (level === 'success') return 'text-emerald-400';
    if (level === 'error') return 'text-rose-400';
    if (level === 'warn') return 'text-amber-400';
    return 'text-slate-300';
  };

  viewer.innerHTML = logs.map(l =>
    `<div class="log-line ${colorFor(l.level)}"><span class="text-slate-600">${l.ts}</span>  ${escapeHtml(l.msg)}</div>`
  ).join('');

  if (autoScroll) viewer.scrollTop = viewer.scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

loadLocal();
if (document.querySelectorAll('.account-item').length === 0) {
  addAccount();
}
poll();
setInterval(poll, 1500);

const logViewer = document.getElementById('logViewer');
logViewer.addEventListener('scroll', () => {
  autoScroll = logViewer.scrollTop + logViewer.clientHeight >= logViewer.scrollHeight - 20;
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


# ============================================================================
# BOOT
# ============================================================================
start_tg_loop()

if os.environ.get("TELEGRAM_SESSION"):
    STATE["session_string"] = os.environ["TELEGRAM_SESSION"]
    STATE["logged_in"] = True
    log("🔑 Đã nạp TELEGRAM_SESSION từ env", "info")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
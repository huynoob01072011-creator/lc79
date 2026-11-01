# ============================================================================
#  LC79 AUTO REDEEM - WEB EDITION
#  Deploy: gunicorn --workers=1 --threads=8 --timeout=0 --bind=0.0.0.0:$PORT main:app
# ============================================================================
import os
import re
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

app = Flask(__name__)

# ----------------------------------------------------------------------------
# Global state
# ----------------------------------------------------------------------------
STATE = {
    "config": {"api_id": None, "api_hash": None, "phone": None,
               "group_link": None, "accounts": []},
    "session_string": None,
    "target_chat_id": None,
    "bot_running": False,
    "logged_in": False,
    "me": None,
}

LOGS = deque(maxlen=500)
LOGS_VERSION = 0
LOG_LOCK = threading.Lock()


def log(msg, level="info"):
    global LOGS_VERSION
    ts = datetime.now().strftime("%H:%M:%S")
    with LOG_LOCK:
        LOGS.append({"ts": ts, "msg": msg, "level": level})
        LOGS_VERSION += 1
    try:
        print(f"[{ts}] {msg}", flush=True)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Game account
# ----------------------------------------------------------------------------
class Account:
    def __init__(self, un, pw, nick):
        self.un, self.pw, self.nick = un, pw, nick
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
            return json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0)
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
                log(f"[{self.nick}] ❌ Không login được → bỏ {code}", "error")
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
                log(f"[{self.nick}] 💰 SUCCESS: +{int(amt):,}" if amt
                    else f"[{self.nick}] ✅ SUCCESS", "success")
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


# ----------------------------------------------------------------------------
# Telegram async loop
# ----------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------
# API routes
# ----------------------------------------------------------------------------
@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/ping")
def ping():
    return "pong"


@app.route("/api/status")
def api_status():
    with LOG_LOCK:
        logs = list(LOGS)
        ver = LOGS_VERSION
    return jsonify({
        "logged_in": STATE["logged_in"],
        "bot_running": STATE["bot_running"],
        "me": STATE["me"],
        "target_chat_id": STATE["target_chat_id"],
        "logs_version": ver,
        "config": {
            "api_id": STATE["config"]["api_id"],
            "group_link": STATE["config"]["group_link"],
            "accounts": STATE["config"]["accounts"],
            "phone": STATE["config"]["phone"],
            "has_session": bool(STATE["session_string"]),
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
            return {"ok": True, "session_string": cli.session.save(),
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
            log(f"✅ Login OK: {res['me'].get('first_name')}", "success")
            log("💡 Copy session ở stats bar → dán vào Render env TELEGRAM_SESSION", "info")
        else:
            log(f"❌ Verify OTP fail: {res.get('error')}", "error")
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/logout", methods=["POST"])
def api_logout():
    async def _lo():
        if TG_CLIENT:
            try:
                await TG_CLIENT.log_out()
            except Exception:
                pass
    try:
        run_async(_lo(), timeout=10)
    except Exception:
        pass
    STATE["session_string"] = None
    STATE["logged_in"] = False
    STATE["me"] = None
    STATE["target_chat_id"] = None
    STATE["bot_running"] = False
    log("🚪 Đã logout Telegram", "warn")
    return jsonify({"ok": True})


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
    log(f"💾 Đã lưu: {len(clean)} acc, group={group_link}", "success")
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
        log(f"🔄 Refresh: {ok}/{len(ACCOUNT_OBJS)} OK",
            "success" if ok == len(ACCOUNT_OBJS) else "warn")

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
            TG_CLIENT = TelegramClient(
                StringSession(STATE["session_string"]),
                cfg["api_id"], cfg["api_hash"],
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
            full = m.group(1)
            cands = [full] + ([full[:-4]] if full.endswith("LC79") else [])
            for c in cands:
                threading.Thread(target=redeem_all_sync, args=(c,),
                                 daemon=True).start()

        log("✅ Bot online — đang chờ message...", "success")
        await TG_CLIENT.run_until_disconnected()

    run_async(bot_main(), timeout=None)


# ----------------------------------------------------------------------------
# Frontend (embedded)
# ----------------------------------------------------------------------------
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0, user-scalable=no, viewport-fit=cover" />
<meta name="theme-color" content="#0a0e1a" />
<meta name="format-detection" content="telephone=no" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<title>LC79 Auto Redeem</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{
  --bg:#0a0e1a;--bg2:#131a2e;--card:rgba(255,255,255,.03);--border:rgba(255,255,255,.08);
  --text:#e2e8f0;--dim:#94a3b8;--muted:#64748b;
  --primary:#6366f1;--primary-h:#4f46e5;
  --success:#10b981;--danger:#ef4444;--warn:#f59e0b;
}
html,body{height:100%;overflow-x:hidden;-webkit-text-size-adjust:100%}
body{
  background:
    radial-gradient(ellipse 80% 50% at 50% 0%,rgba(99,102,241,.15),transparent),
    radial-gradient(ellipse 60% 40% at 80% 80%,rgba(139,92,246,.08),transparent),
    var(--bg);
  color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  min-height:100vh;padding-bottom:env(safe-area-inset-bottom)
}
button{font:inherit;cursor:pointer;border:none;outline:none;background:none;color:inherit}
input,textarea{font:inherit;-webkit-appearance:none;appearance:none}
.app{max-width:1200px;margin:0 auto;padding:20px}
@media(max-width:640px){.app{padding:12px}}

/* Header */
.header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:20px}
.brand{display:flex;align-items:center;gap:12px}
.brand-icon{font-size:36px;filter:drop-shadow(0 4px 12px rgba(99,102,241,.5))}
.brand h1{font-size:22px;font-weight:700;letter-spacing:-.02em;
  background:linear-gradient(135deg,#818cf8,#c084fc);-webkit-background-clip:text;
  -webkit-text-fill-color:transparent;background-clip:text}
.brand p{font-size:12px;color:var(--dim);margin-top:2px}
.badges{display:flex;gap:8px;flex-wrap:wrap}
.badge{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;
  border-radius:999px;font-size:12px;font-weight:500;
  background:rgba(255,255,255,.05);border:1px solid var(--border);color:var(--dim);
  transition:all .3s}
.badge.on{background:rgba(16,185,129,.12);border-color:rgba(16,185,129,.4);color:#6ee7b7}
.badge .dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
.badge.on .dot{background:var(--success);box-shadow:0 0 8px var(--success);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}

/* Stats */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}
@media(max-width:640px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{background:linear-gradient(135deg,rgba(255,255,255,.04),rgba(255,255,255,.01));
  border:1px solid var(--border);border-radius:14px;padding:14px;
  backdrop-filter:blur(8px)}
.stat-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.stat-value{font:600 14px/1.4 "SF Mono",Consolas,monospace;color:var(--text);margin-top:6px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.stat-value.ok{color:#6ee7b7}
.stat-value.no{color:#fca5a5}

/* Grid */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.col{display:flex;flex-direction:column;gap:20px}

/* Card */
.card{background:linear-gradient(135deg,rgba(255,255,255,.04),rgba(255,255,255,.01));
  border:1px solid var(--border);border-radius:16px;padding:20px;
  backdrop-filter:blur(12px);box-shadow:0 4px 24px rgba(0,0,0,.2)}
.card-title{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:600;margin-bottom:16px}
.card-title span{font-size:18px}
.card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.card-header .card-title{margin:0}

/* Form */
.field{margin-bottom:14px}
.label{display:block;font-size:12px;font-weight:500;color:var(--dim);margin-bottom:6px}
.input{width:100%;padding:12px 14px;font-size:16px;color:var(--text);
  background:rgba(0,0,0,.35);border:1px solid var(--border);border-radius:10px;
  transition:all .2s;min-height:44px}
.input::placeholder{color:var(--muted)}
.input:focus{outline:none;border-color:var(--primary);
  box-shadow:0 0 0 3px rgba(99,102,241,.15);background:rgba(0,0,0,.5)}
.input:disabled{opacity:.5;cursor:not-allowed}

/* Buttons */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;
  padding:12px 18px;font-size:14px;font-weight:600;border-radius:10px;
  min-height:44px;cursor:pointer;user-select:none;white-space:nowrap;
  transition:all .15s ease;border:none;touch-action:manipulation}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-primary{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;
  box-shadow:0 4px 14px rgba(99,102,241,.35)}
.btn-primary:hover:not(:disabled){background:linear-gradient(135deg,#4f46e5,#7c3aed);
  box-shadow:0 6px 20px rgba(99,102,241,.55);transform:translateY(-1px)}
.btn-primary:active:not(:disabled){transform:translateY(0)}
.btn-success{background:linear-gradient(135deg,#10b981,#059669);color:#fff;
  box-shadow:0 4px 14px rgba(16,185,129,.3)}
.btn-success:hover:not(:disabled){background:linear-gradient(135deg,#059669,#047857);transform:translateY(-1px)}
.btn-danger{background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff;
  box-shadow:0 4px 14px rgba(239,68,68,.3)}
.btn-danger:hover:not(:disabled){background:linear-gradient(135deg,#dc2626,#b91c1c);transform:translateY(-1px)}
.btn-secondary{background:rgba(255,255,255,.06);color:var(--text);
  border:1px solid var(--border)}
.btn-secondary:hover:not(:disabled){background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.2)}
.btn-block{width:100%}
.btn-sm{padding:8px 14px;font-size:13px;min-height:38px}
.btn-group{display:flex;gap:10px}
.btn-group>.btn{flex:1}
.btn-text{color:var(--dim);font-size:12px;font-weight:500;padding:4px 8px;border-radius:6px;
  transition:all .15s}
.btn-text:hover{color:var(--text);background:rgba(255,255,255,.05)}
.input-group{display:flex;gap:8px}
.input-group .input{flex:1}
.input-group .btn{padding:12px 16px;flex-shrink:0}

/* Spinner */
.spinner{display:inline-block;width:14px;height:14px;
  border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;
  animation:spin .6s linear infinite;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}

/* Hidden */
.hidden{display:none!important}

/* Account list */
.acc-list{display:flex;flex-direction:column;gap:8px;margin-bottom:10px}
.acc-row{display:grid;grid-template-columns:1fr 1fr 1fr 36px;gap:6px;align-items:center}
.acc-row .input{padding:10px 10px;font-size:14px;min-height:40px}
.acc-remove{width:36px;height:40px;display:flex;align-items:center;justify-content:center;
  color:#fca5a5;background:rgba(239,68,68,.1);border-radius:8px;
  transition:all .15s;font-size:16px;cursor:pointer;border:none}
.acc-remove:hover{background:rgba(239,68,68,.25);color:#fff}
@media(max-width:520px){.acc-row{grid-template-columns:1fr 1fr 36px}
  .acc-row .acc-nick{grid-column:1/3}}

/* Logs */
.logs{background:rgba(0,0,0,.6);border:1px solid rgba(255,255,255,.05);border-radius:10px;
  padding:12px;height:340px;overflow-y:auto;font:11px/1.5 "SF Mono",Consolas,monospace;
  scroll-behavior:smooth}
.logs::-webkit-scrollbar{width:6px}
.logs::-webkit-scrollbar-track{background:transparent}
.logs::-webkit-scrollbar-thumb{background:rgba(255,255,255,.1);border-radius:3px}
.log-line{padding:2px 0;animation:logIn .25s ease}
@keyframes logIn{from{opacity:0;transform:translateY(2px)}to{opacity:1;transform:translateY(0)}}
.log-time{color:#475569;margin-right:8px}
.log-info{color:#cbd5e1}
.log-success{color:#6ee7b7}
.log-error{color:#fca5a5}
.log-warn{color:#fcd34d}

/* Toast */
.toasts{position:fixed;top:16px;right:16px;z-index:9999;display:flex;
  flex-direction:column;gap:8px;pointer-events:none}
@media(max-width:640px){.toasts{left:16px;right:16px}}
.toast{pointer-events:auto;padding:12px 16px;border-radius:10px;font-size:13px;
  font-weight:500;color:#fff;background:#1e293b;border:1px solid rgba(255,255,255,.1);
  box-shadow:0 8px 24px rgba(0,0,0,.4);animation:toastIn .3s ease;max-width:360px}
.toast.success{background:linear-gradient(135deg,#065f46,#064e3b);border-color:rgba(16,185,129,.5)}
.toast.error{background:linear-gradient(135deg,#991b1b,#7f1d1d);border-color:rgba(239,68,68,.5)}
.toast.warn{background:linear-gradient(135deg,#92400e,#78350f);border-color:rgba(245,158,11,.5)}
@keyframes toastIn{from{transform:translateX(400px);opacity:0}to{transform:translateX(0);opacity:1}}

/* Footer */
.footer{text-align:center;font-size:12px;color:var(--muted);margin-top:32px;padding:16px 0}
</style>
</head>
<body>

<div id="toasts" class="toasts"></div>

<div class="app">

  <header class="header">
    <div class="brand">
      <div class="brand-icon">🎁</div>
      <div>
        <h1>LC79 Auto Redeem</h1>
        <p>Bot tự động nhận gift code từ Telegram</p>
      </div>
    </div>
    <div class="badges">
      <div class="badge" id="badge-login"><span class="dot"></span><span class="txt">Chưa login</span></div>
      <div class="badge" id="badge-bot"><span class="dot"></span><span class="txt">Bot tắt</span></div>
    </div>
  </header>

  <div class="stats">
    <div class="stat">
      <div class="stat-label">Telegram</div>
      <div class="stat-value" id="stat-user">—</div>
    </div>
    <div class="stat">
      <div class="stat-label">Group ID</div>
      <div class="stat-value" id="stat-group">—</div>
    </div>
    <div class="stat">
      <div class="stat-label">Accounts</div>
      <div class="stat-value" id="stat-acc">0</div>
    </div>
    <div class="stat">
      <div class="stat-label">Session</div>
      <div class="stat-value" id="stat-session">❌</div>
    </div>
  </div>

  <div class="grid">
    <div class="col">

      <!-- Login card -->
      <div class="card">
        <h2 class="card-title"><span>🔐</span> Đăng nhập Telegram</h2>

        <div id="step1">
          <div class="field">
            <label class="label">API ID</label>
            <input id="apiId" type="number" class="input" placeholder="VD: 34425014" inputmode="numeric" />
          </div>
          <div class="field">
            <label class="label">API Hash</label>
            <input id="apiHash" type="text" class="input" placeholder="Nhập api_hash" autocomplete="off" spellcheck="false" />
          </div>
          <div class="field">
            <label class="label">Số điện thoại</label>
            <input id="phone" type="tel" class="input" placeholder="+84..." inputmode="tel" autocomplete="tel" />
          </div>
          <button type="button" class="btn btn-primary btn-block" onclick="sendOTP(this)">
            📱 Gửi mã OTP
          </button>
        </div>

        <div id="step2" class="hidden">
          <div class="field">
            <label class="label">Mã OTP</label>
            <input id="otpCode" type="text" class="input" placeholder="Nhập mã OTP" inputmode="numeric" autocomplete="one-time-code" />
          </div>
          <div class="field">
            <label class="label">Mật khẩu 2FA (nếu có)</label>
            <input id="otpPassword" type="password" class="input" placeholder="Để trống nếu không có" />
          </div>
          <div class="btn-group">
            <button type="button" class="btn btn-secondary" onclick="showStep1()">← Quay lại</button>
            <button type="button" class="btn btn-primary" onclick="verifyOTP(this)">✅ Xác nhận</button>
          </div>
        </div>

        <div id="loggedIn" class="hidden">
          <p style="color:var(--dim);font-size:13px;margin-bottom:12px">
            ✅ Đã đăng nhập. Session được lưu server — không cần nhập lại nếu restart (thêm env).
          </p>
          <button type="button" class="btn btn-secondary btn-block" onclick="logout(this)">
            🚪 Đăng xuất
          </button>
        </div>
      </div>

      <!-- Config card -->
      <div class="card">
        <h2 class="card-title"><span>⚙️</span> Cấu hình</h2>
        <div class="field">
          <label class="label">Link group Telegram</label>
          <input id="groupLink" type="text" class="input" placeholder="https://t.me/codelaucuagame" autocomplete="off" />
        </div>
        <div class="field">
          <label class="label">Accounts game LC79</label>
          <div id="accountList" class="acc-list"></div>
          <button type="button" class="btn btn-secondary btn-block btn-sm" onclick="addAccount()">
            ➕ Thêm account
          </button>
        </div>
        <button type="button" class="btn btn-primary btn-block" onclick="saveConfig(this)">
          💾 Lưu cấu hình
        </button>
      </div>
    </div>

    <div class="col">

      <!-- Control card -->
      <div class="card">
        <h2 class="card-title"><span>🎮</span> Điều khiển</h2>
        <div class="btn-group" style="margin-bottom:12px">
          <button type="button" class="btn btn-success" onclick="startBot(this)">▶️ Start Bot</button>
          <button type="button" class="btn btn-danger" onclick="stopBot(this)">⏹ Stop Bot</button>
        </div>
        <button type="button" class="btn btn-secondary btn-block" style="margin-bottom:12px" onclick="refreshAccounts(this)">
          🔄 Refresh Accounts
        </button>
        <div class="input-group">
          <input id="manualCode" type="text" class="input" placeholder="Nhập code redeem thủ công..." autocomplete="off" />
          <button type="button" class="btn btn-primary" onclick="manualRedeem(this)">🚀</button>
        </div>
      </div>

      <!-- Logs card -->
      <div class="card">
        <div class="card-header">
          <h2 class="card-title"><span>📜</span> Logs</h2>
          <button type="button" class="btn-text" onclick="clearLogs()">Xoá</button>
        </div>
        <div id="logs" class="logs"></div>
      </div>
    </div>
  </div>

  <footer class="footer">LC79 Auto Redeem • Web Edition</footer>
</div>

<script>
"use strict";

// ============ STATE ============
let lastLogVer = -1;
let autoScroll = true;

// ============ TOAST ============
function toast(msg, level) {
  const box = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = "toast " + (level || "info");
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .3s, transform .3s";
    el.style.opacity = "0";
    el.style.transform = "translateX(400px)";
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

// ============ LOADING ============
function setLoading(btn, loading, text) {
  if (!btn) return;
  if (loading) {
    btn.dataset.orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> ' + (text || "Đang xử lý...");
  } else {
    btn.disabled = false;
    if (btn.dataset.orig) btn.innerHTML = btn.dataset.orig;
  }
}

// ============ API ============
async function api(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// ============ LOCAL STORAGE ============
function saveLocal() {
  try {
    localStorage.setItem("lc79_cfg", JSON.stringify({
      apiId: val("apiId"),
      apiHash: val("apiHash"),
      phone: val("phone"),
      groupLink: val("groupLink"),
      accounts: getAccounts(),
    }));
  } catch (e) {}
}

function loadLocal() {
  try {
    const d = JSON.parse(localStorage.getItem("lc79_cfg") || "{}");
    if (d.apiId) document.getElementById("apiId").value = d.apiId;
    if (d.apiHash) document.getElementById("apiHash").value = d.apiHash;
    if (d.phone) document.getElementById("phone").value = d.phone;
    if (d.groupLink) document.getElementById("groupLink").value = d.groupLink;
    (d.accounts || []).forEach(a => addAccount(a.un, a.pw, a.nick));
  } catch (e) {}
}

function val(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : "";
}

// ============ ACCOUNTS ============
function addAccount(un, pw, nick) {
  un = un || ""; pw = pw || ""; nick = nick || "";
  const row = document.createElement("div");
  row.className = "acc-row";
  row.innerHTML =
    '<input type="text" class="input acc-un" placeholder="Username" autocomplete="off" spellcheck="false">' +
    '<input type="password" class="input acc-pw" placeholder="Password" autocomplete="new-password">' +
    '<input type="text" class="input acc-nick" placeholder="Nick (tùy chọn)" autocomplete="off" spellcheck="false">' +
    '<button type="button" class="acc-remove" title="Xoá">✖</button>';
  row.querySelector(".acc-un").value = un;
  row.querySelector(".acc-pw").value = pw;
  row.querySelector(".acc-nick").value = nick;
  row.querySelector(".acc-remove").onclick = () => row.remove();
  document.getElementById("accountList").appendChild(row);
}

function getAccounts() {
  const out = [];
  document.querySelectorAll(".acc-row").forEach(r => {
    const un = r.querySelector(".acc-un").value.trim();
    const pw = r.querySelector(".acc-pw").value.trim();
    const nick = r.querySelector(".acc-nick").value.trim() || un;
    if (un && pw) out.push({ un, pw, nick });
  });
  return out;
}

// ============ LOGIN FLOW ============
function showStep1() {
  document.getElementById("step1").classList.remove("hidden");
  document.getElementById("step2").classList.add("hidden");
}

function showStep2() {
  document.getElementById("step1").classList.add("hidden");
  document.getElementById("step2").classList.remove("hidden");
}

function showLoggedIn() {
  document.getElementById("step1").classList.add("hidden");
  document.getElementById("step2").classList.add("hidden");
  document.getElementById("loggedIn").classList.remove("hidden");
}

async function sendOTP(btn) {
  const api_id = val("apiId");
  const api_hash = val("apiHash");
  const phone = val("phone");
  if (!api_id || !api_hash || !phone) {
    toast("Vui lòng điền đủ 3 field", "error");
    return;
  }
  setLoading(btn, true, "Đang gửi OTP...");
  saveLocal();
  try {
    const r = await api("/api/send_otp", { api_id, api_hash, phone });
    if (r.ok) {
      toast("Đã gửi OTP tới " + phone, "success");
      showStep2();
    } else {
      toast(r.error || "Lỗi không xác định", "error");
    }
  } finally {
    setLoading(btn, false);
  }
}

async function verifyOTP(btn) {
  const code = val("otpCode");
  const password = document.getElementById("otpPassword").value;
  if (!code) {
    toast("Nhập OTP trước", "error");
    return;
  }
  setLoading(btn, true, "Đang xác nhận...");
  try {
    const r = await api("/api/verify_otp", { code, password });
    if (r.ok) {
      toast("✅ Đăng nhập thành công!", "success");
      showLoggedIn();
      document.getElementById("otpCode").value = "";
      document.getElementById("otpPassword").value = "";
    } else if (r.need_password) {
      toast("Cần mật khẩu 2FA", "warn");
    } else {
      toast(r.error || "OTP sai", "error");
    }
  } finally {
    setLoading(btn, false);
  }
}

async function logout(btn) {
  if (!confirm("Đăng xuất Telegram?")) return;
  setLoading(btn, true, "Đang logout...");
  try {
    const r = await api("/api/logout", {});
    if (r.ok) {
      toast("Đã logout", "warn");
      showStep1();
    }
  } finally {
    setLoading(btn, false);
  }
}

// ============ CONFIG ============
async function saveConfig(btn) {
  const group_link = val("groupLink");
  const accounts = getAccounts();
  if (!group_link) { toast("Nhập link group", "error"); return; }
  if (!accounts.length) { toast("Cần ít nhất 1 account", "error"); return; }
  setLoading(btn, true, "Đang lưu...");
  try {
    const r = await api("/api/save_config", { group_link, accounts });
    if (r.ok) {
      toast("✅ Đã lưu cấu hình", "success");
      saveLocal();
    } else {
      toast(r.error || "Lỗi lưu", "error");
    }
  } finally {
    setLoading(btn, false);
  }
}

// ============ CONTROL ============
async function startBot(btn) {
  setLoading(btn, true, "Đang start...");
  try {
    const r = await api("/api/start_bot", {});
    if (r.ok) toast("Đang khởi động bot...", "success");
    else toast(r.error || "Lỗi", "error");
  } finally {
    setLoading(btn, false);
  }
}

async function stopBot(btn) {
  if (!confirm("Dừng bot?")) return;
  setLoading(btn, true, "Đang dừng...");
  try {
    await api("/api/stop_bot", {});
    toast("Đã gửi lệnh dừng", "warn");
  } finally {
    setLoading(btn, false);
  }
}

async function refreshAccounts(btn) {
  setLoading(btn, true, "Đang refresh...");
  try {
    const r = await api("/api/refresh_accounts", {});
    if (!r.ok) toast(r.error || "Lỗi", "error");
    else toast("Đang refresh accounts...", "success");
  } finally {
    setTimeout(() => setLoading(btn, false), 800);
  }
}

async function manualRedeem(btn) {
  const code = val("manualCode").toUpperCase();
  if (!code) { toast("Nhập code", "error"); return; }
  setLoading(btn, true, "");
  try {
    const r = await api("/api/manual_redeem", { code });
    if (r.ok) {
      toast("Đang redeem: " + code, "success");
      document.getElementById("manualCode").value = "";
    } else {
      toast(r.error || "Lỗi", "error");
    }
  } finally {
    setLoading(btn, false);
  }
}

function clearLogs() {
  document.getElementById("logs").innerHTML = "";
  lastLogVer = -1;
}

// ============ POLL ============
async function poll() {
  try {
    const res = await fetch("/api/status", { cache: "no-store" });
    const d = await res.json();

    // Badges
    setBadge("badge-login", d.logged_in, d.logged_in ? "Đã login" : "Chưa login");
    setBadge("badge-bot", d.bot_running, d.bot_running ? "Bot online" : "Bot tắt");

    // Login/logout card state
    if (d.logged_in) showLoggedIn();
    else {
      const s1 = document.getElementById("step1");
      const s2 = document.getElementById("step2");
      const li = document.getElementById("loggedIn");
      if (s1.classList.contains("hidden") && li.classList.contains("hidden")) {
        // đang ở step2 → giữ nguyên
      } else if (li && !li.classList.contains("hidden")) {
        s1.classList.remove("hidden");
        li.classList.add("hidden");
      }
    }

    // Stats
    setStat("stat-user", d.me ? (d.me.first_name || d.me.username || "?") : "—");
    setStat("stat-group", d.target_chat_id || "—");
    setStat("stat-acc", (d.config.accounts || []).length + " acc");
    const ss = document.getElementById("stat-session");
    ss.textContent = d.config.has_session ? "✅ Có" : "❌ Chưa";
    ss.className = "stat-value " + (d.config.has_session ? "ok" : "no");

    // Logs
    if (d.logs_version !== lastLogVer) {
      lastLogVer = d.logs_version;
      renderLogs(d.logs || []);
    }
  } catch (e) {}
}

function setBadge(id, on, text) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle("on", !!on);
  const t = el.querySelector(".txt");
  if (t) t.textContent = text;
}

function setStat(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function renderLogs(logs) {
  const viewer = document.getElementById("logs");
  const cls = { success: "log-success", error: "log-error", warn: "log-warn" };
  viewer.innerHTML = logs.map(l =>
    '<div class="log-line ' + (cls[l.level] || "log-info") + '">' +
    '<span class="log-time">' + escapeHtml(l.ts) + '</span>' +
    escapeHtml(l.msg) + '</div>'
  ).join("");
  if (autoScroll) viewer.scrollTop = viewer.scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// ============ INIT ============
loadLocal();
if (document.querySelectorAll(".acc-row").length === 0) addAccount();
poll();
setInterval(poll, 1500);

const viewer = document.getElementById("logs");
viewer.addEventListener("scroll", () => {
  autoScroll = viewer.scrollTop + viewer.clientHeight >= viewer.scrollHeight - 20;
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


# ----------------------------------------------------------------------------
# Boot
# ----------------------------------------------------------------------------
start_tg_loop()

if os.environ.get("TELEGRAM_SESSION"):
    STATE["session_string"] = os.environ["TELEGRAM_SESSION"]
    STATE["logged_in"] = True
    log("🔑 Đã nạp TELEGRAM_SESSION từ env", "info")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
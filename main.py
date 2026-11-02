from flask import Flask, request, jsonify, session
import os, requests, hashlib, base64, json, time, threading, uuid

import socketio
import algo

app = Flask(__name__)
app.secret_key = "LC79_SECRET_KEY_CHANGE_ME_IN_PROD_2025_v4"

# ==========================================================
# ⚙️ CONFIG
# ==========================================================
COLLECTOR_USER  = "HuyDaiXuLC79"
COLLECTOR_PASS  = "GiaHuy2011@"
WS_URL          = "https://wtxmd52.tele68.com"
WS_PATH         = "txmd5/"
WS_NAMESPACE    = "/txmd5"
RECONNECT_DELAY = 8
LOGIN_DELAY     = 15
MAX_BET_HIST    = 200
TEMPLATE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.html")

# ==========================================================
# 🌐 GLOBAL STATE
# ==========================================================
USER_LOCK    = threading.RLock()
USER_STATES  = {}
USER_SOCKETS = {}

BG_STATE  = {"logged_in": False, "ws_connected": False, "ws_error": None, "nickname": None}


def log(msg):
    print(f"[SRV] {msg}", flush=True)


def ulog(uid, msg):
    with USER_LOCK:
        st = USER_STATES.get(uid)
        if st:
            st["events"].append({"t": time.time(), "msg": msg})
            if len(st["events"]) > 60:
                st["events"] = st["events"][-60:]


def new_user_state(nickname, balance, username):
    return {
        "username": username, "nickname": nickname,
        "balance": balance, "prev_balance": balance,
        "ws_connected": False, "ws_error": None,
        "current_session": None, "current_state": None,
        "current_prediction": None, "current_confidence": 0.0,
        "current_result": None,
        "last_bet_sid": None, "waiting_for_result": False,
        "current_bet": 0,
        "auto_bet": False, "base_bet": 10000,
        "max_losses": 3, "consecutive_losses": 0, "auto_paused": False,
        "min_confidence": 0.52,
        # 🎯 Chốt lãi
        "profit_target": 0,
        "auto_start_balance": 0,
        "auto_target_reached": False,
        # stats
        "paper_bets": 0, "paper_wins": 0,
        "bet_history": [], "profit_curve": [], "events": [],
        "total_wagered": 0, "total_profit": 0,
        "total_wins": 0, "total_losses": 0,
        "best_streak": 0, "worst_streak": 0, "cur_streak": 0,
    }


def check_profit_target(uid):
    """Kiểm tra & tự dừng nếu số dư đạt mục tiêu chốt lãi."""
    with USER_LOCK:
        st = USER_STATES.get(uid)
        if not st or not st["auto_bet"]: return
        if st["profit_target"] <= 0 or st["auto_start_balance"] <= 0: return
        gain = st["balance"] - st["auto_start_balance"]
        if gain >= st["profit_target"]:
            st["auto_bet"] = False
            st["auto_target_reached"] = True
            ulog(uid, f"🎯 CHỐT LÃI +{st['profit_target']:,}đ → TỰ DỪNG AUTO")


# ==========================================================
# 🌐 LOGIN
# ==========================================================
def md5_hash(text): return hashlib.md5(text.encode("utf-8")).hexdigest()


def login_and_get_token(username, password):
    pw = md5_hash(password) if len(password) != 32 else password
    url = f"https://apifo88daigia.tele68.com/api?c=3&un={username}&pw={pw}&cp=R&cl=R&pf=web&at="
    try:
        r = requests.get(url, timeout=12); r.raise_for_status()
        game = r.json()
        if not game.get("success"):
            return {"_error": f"Game: {game.get('message','Sai thông tin')}"}
        sk = game.get("sessionKey", "") + "=" * ((4 - len(game.get("sessionKey","")) % 4) % 4)
        sd = json.loads(base64.b64decode(sk).decode("utf-8"))
        nick = sd.get("nickname") or sd.get("nickName")
        r2 = requests.post(
            "https://wlb.tele68.com/v1/lobby/auth/login?cp=R&cl=R&pf=web&at=",
            headers={
                "authority":"wlb.tele68.com","content-type":"application/json",
                "origin":"https://tele68.com","referer":"https://tele68.com/",
                "user-agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            json={"nickName": nick, "accessToken": game.get("accessToken")}, timeout=12,
        )
        r2.raise_for_status(); lobby = r2.json()
        token = lobby.get("token")
        if not token: return {"_error": "Lobby không trả JWT."}
        return {"token": token, "nickname": nick,
                "money": lobby.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e:
        return {"_error": f"Kết nối: {e}"}


# ==========================================================
# 🔌 WS per-user
# ==========================================================
def start_user_ws(uid, jwt_token):
    sio = socketio.Client(reconnection=True, reconnection_attempts=999,
                          logger=False, engineio_logger=False)
    with USER_LOCK:
        USER_SOCKETS[uid] = sio

    @sio.event(namespace=WS_NAMESPACE)
    def connect():
        with USER_LOCK:
            st = USER_STATES.get(uid)
            if st:
                st["ws_connected"] = True; st["ws_error"] = None
        ulog(uid, "🟢 Đã kết nối WebSocket")
        log(f"🟢 [{uid[:8]}] WS LIVE")

    @sio.event(namespace=WS_NAMESPACE)
    def disconnect():
        with USER_LOCK:
            st = USER_STATES.get(uid)
            if st: st["ws_connected"] = False
        ulog(uid, "🔴 Mất kết nối WS — tự reconnect")
        log(f"🔴 [{uid[:8]}] WS off")

    @sio.on("new-session", namespace=WS_NAMESPACE)
    def on_new_session(data):
        sid = data.get("id", "N/A")
        pred, conf = algo.get_cached_prediction(sid)
        with USER_LOCK:
            st = USER_STATES.get(uid)
            if not st: return
            st["current_session"] = sid
            st["current_state"] = "BETTING"
            st["current_result"] = None
            st["waiting_for_result"] = False
            st["current_prediction"] = pred
            st["current_confidence"] = conf
        if pred:
            ulog(uid, f"🔔 Phiên #{sid} · AI: {pred} ({conf*100:.0f}%)")
        else:
            with algo.GLOBAL_LOCK:
                hn = len(algo.GLOBAL_HISTORY)
            ulog(uid, f"🔔 Phiên #{sid} · chờ data ({hn}/{algo.MIN_TRAIN})")

    @sio.on("tick-update", namespace=WS_NAMESPACE)
    def on_tick(data):
        gs = data.get("state")
        with USER_LOCK:
            st = USER_STATES.get(uid)
            if not st: return
            st["current_state"] = gs
            should_bet = (
                gs == "BETTING"
                and st["auto_bet"]
                and not st["auto_paused"]
                and not st["auto_target_reached"]
                and st["current_prediction"]
                and st["current_confidence"] >= st["min_confidence"]
                and st["last_bet_sid"] != st["current_session"]
            )
            if not should_bet: return
            amount = int(st["base_bet"])
            if amount > st["balance"] * 0.9:
                ulog(uid, "⚠️ Số dư không đủ")
                return
            try:
                sio.emit("bet", {"type": st["current_prediction"], "amount": amount},
                         namespace=WS_NAMESPACE)
                st["last_bet_sid"] = st["current_session"]
                st["waiting_for_result"] = True
                st["current_bet"] = amount
                ulog(uid, f"🚀 BET {amount:,}đ → {st['current_prediction']}")
            except Exception as e:
                ulog(uid, f"⚠️ Bet fail: {e}")

    @sio.on("bet-result", namespace=WS_NAMESPACE)
    def on_bet_result(data):
        with USER_LOCK:
            st = USER_STATES.get(uid)
            if st and "postBalance" in data:
                st["prev_balance"] = st["balance"]
                st["balance"] = data["postBalance"]
        check_profit_target(uid)

    @sio.on("session-result", namespace=WS_NAMESPACE)
    def on_session_result(data):
        result = data.get("resultTruyenThong", "N/A")
        dices = data.get("dices", [0, 0, 0])
        if result not in ("TAI", "XIU"): return

        sid_out = None; pred_out = None
        with USER_LOCK:
            st = USER_STATES.get(uid)
            if not st: return
            sid = st["current_session"]
            pred = st["current_prediction"]
            was_betting = st["waiting_for_result"]
            was_paused = st["auto_paused"]
            ok = (pred == result) if pred else None
            st["current_result"] = {"result": result, "dices": dices, "ok": ok}

            if was_paused:
                st["paper_bets"] += 1
                if ok:
                    st["paper_wins"] += 1
                    st["auto_paused"] = False
                    st["consecutive_losses"] = 0
                    ulog(uid, "🟢 AI đúng khi nghỉ → BẬT LẠI auto")
                else:
                    ulog(uid, "⏸ vẫn nghỉ (AI sai tiếp)")
            elif was_betting:
                amount = st["current_bet"]
                profit = amount * 0.98 if ok else -amount
                st["total_wagered"] += amount
                st["total_profit"] += profit
                if ok:
                    st["total_wins"] += 1
                    st["cur_streak"] = max(1, st["cur_streak"] + 1)
                    st["best_streak"] = max(st["best_streak"], st["cur_streak"])
                    st["consecutive_losses"] = 0
                else:
                    st["total_losses"] += 1
                    st["cur_streak"] = min(-1, st["cur_streak"] - 1) if st["cur_streak"] < 0 else -1
                    st["worst_streak"] = max(st["worst_streak"], abs(st["cur_streak"]))
                    st["consecutive_losses"] += 1
                    if st["consecutive_losses"] >= st["max_losses"]:
                        st["auto_paused"] = True
                        ulog(uid, f"⏸ Đã thua {st['consecutive_losses']} tay → TẠM NGHỈ")

                st["bet_history"].append({
                    "sid": sid, "pred": pred, "result": result,
                    "amount": amount, "won": ok, "profit": profit,
                    "balance_after": st["balance"], "ts": time.time(),
                })
                if len(st["bet_history"]) > MAX_BET_HIST:
                    st["bet_history"] = st["bet_history"][-MAX_BET_HIST:]
                st["profit_curve"].append(st["total_profit"])
                if len(st["profit_curve"]) > MAX_BET_HIST:
                    st["profit_curve"] = st["profit_curve"][-MAX_BET_HIST:]
                st["waiting_for_result"] = False
                mark = "✅ Thắng" if ok else "❌ Thua"
                ulog(uid, f"{mark} {result} · lãi {profit:+,.0f}đ")

            sid_out = sid; pred_out = pred

        if sid_out:
            algo.record_result(sid_out, result, pred_out)
        check_profit_target(uid)

    def _runner():
        try:
            sio.connect(WS_URL, socketio_path=WS_PATH, namespaces=[WS_NAMESPACE],
                        transports=["websocket"], auth={"token": jwt_token},
                        headers={"User-Agent": "Mozilla/5.0"})
            sio.wait()
        except Exception as e:
            with USER_LOCK:
                st = USER_STATES.get(uid)
                if st:
                    st["ws_connected"] = False
                    st["ws_error"] = str(e)
            ulog(uid, f"⚠️ WS: {e}")
            log(f"[{uid[:8]}] WS error: {e}")

    threading.Thread(target=_runner, daemon=True).start()


# ==========================================================
# 🔌 BG collector (feed AI)
# ==========================================================
def run_bg_ws(token):
    sio = socketio.Client(reconnection=True, reconnection_attempts=999,
                          logger=False, engineio_logger=False)
    cur = {"sid": None}

    @sio.event(namespace=WS_NAMESPACE)
    def connect():
        BG_STATE["ws_connected"] = True; BG_STATE["ws_error"] = None
        log("🟢 [BG] WS LIVE")

    @sio.event(namespace=WS_NAMESPACE)
    def disconnect():
        BG_STATE["ws_connected"] = False
        log("🔴 [BG] WS off")

    @sio.on("new-session", namespace=WS_NAMESPACE)
    def on_new(data):
        cur["sid"] = data.get("id", "N/A")

    @sio.on("session-result", namespace=WS_NAMESPACE)
    def on_res(data):
        result = data.get("resultTruyenThong", "N/A")
        if result not in ("TAI", "XIU"): return
        sid = cur["sid"]
        if not sid: return
        pred, _ = algo.get_cached_prediction(sid)
        if algo.record_result(sid, result, pred):
            with algo.GLOBAL_LOCK:
                hn = len(algo.GLOBAL_HISTORY)
            log(f"[BG] 📥 {result} #{sid} · tổng {hn} phiên")

    try:
        sio.connect(WS_URL, socketio_path=WS_PATH, namespaces=[WS_NAMESPACE],
                    transports=["websocket"], auth={"token": token},
                    headers={"User-Agent": "Mozilla/5.0"})
        sio.wait()
    except Exception as e:
        BG_STATE["ws_connected"] = False
        BG_STATE["ws_error"] = str(e)
        log(f"⚠️ [BG] WS: {e}")


def bg_worker():
    log(f"🚀 BG collector · acc={COLLECTOR_USER}")
    while True:
        try:
            res = login_and_get_token(COLLECTOR_USER, COLLECTOR_PASS)
            if "_error" in res:
                BG_STATE["ws_error"] = res["_error"]
                log(f"❌ [BG] login: {res['_error']}")
                time.sleep(LOGIN_DELAY); continue
            BG_STATE["logged_in"] = True
            BG_STATE["nickname"] = res["nickname"]
            log(f"🔑 [BG] OK · {res['nickname']} · dư {res['money']:,}")
            run_bg_ws(res["token"])
        except Exception as e:
            log(f"⚠️ [BG] worker: {e}")
        log(f"⏳ [BG] login lại sau {RECONNECT_DELAY}s...")
        time.sleep(RECONNECT_DELAY)

_bg_started = False
_bg_lock = threading.Lock()
def ensure_bg():
    global _bg_started
    with _bg_lock:
        if _bg_started: return
        _bg_started = True
    threading.Thread(target=bg_worker, daemon=True).start()


# ==========================================================
# ROUTES
# ==========================================================
@app.route("/")
def index():
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        return f.read()


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"success": False, "message": "Thiếu thông tin"}), 400

    old_uid = session.get("uid")
    if old_uid:
        with USER_LOCK:
            old_sio = USER_SOCKETS.pop(old_uid, None)
            USER_STATES.pop(old_uid, None)
        if old_sio:
            try: old_sio.disconnect()
            except: pass

    result = login_and_get_token(username, password)
    if "_error" in result:
        return jsonify({"success": False, "message": result["_error"]})

    uid = str(uuid.uuid4())
    session["uid"] = uid
    with USER_LOCK:
        USER_STATES[uid] = new_user_state(result["nickname"], result["money"], username)

    start_user_ws(uid, result["token"])
    log(f"🔑 Login: {result['nickname']} ({uid[:8]})")
    return jsonify({"success": True, "nickname": result["nickname"], "balance": result["money"]})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    uid = session.get("uid")
    if uid:
        with USER_LOCK:
            sio = USER_SOCKETS.pop(uid, None)
            USER_STATES.pop(uid, None)
        if sio:
            try: sio.disconnect()
            except: pass
        session.pop("uid", None)
        log(f"👋 Logout ({uid[:8]})")
    return jsonify({"success": True})


@app.route("/api/state")
def api_state():
    uid = session.get("uid")
    if not uid:
        return jsonify({"logged_in": False})
    with USER_LOCK:
        st = USER_STATES.get(uid)
        if not st:
            return jsonify({"logged_in": False})
        st_copy = {k: v for k, v in st.items()}

    stats = algo.get_stats()

    win_rate = round(
        st_copy["total_wins"] / (st_copy["total_wins"] + st_copy["total_losses"]) * 100, 1
    ) if (st_copy["total_wins"] + st_copy["total_losses"]) else 0
    ai_accuracy = round(
        stats["ai_stats"]["correct"] / stats["ai_stats"]["total"] * 100, 1
    ) if stats["ai_stats"]["total"] else 0

    session_profit = (st_copy["balance"] - st_copy["auto_start_balance"]) \
        if st_copy["auto_start_balance"] > 0 else 0
    progress_pct = 0
    if st_copy["profit_target"] > 0 and st_copy["auto_start_balance"] > 0:
        progress_pct = min(max(session_profit / st_copy["profit_target"] * 100, 0), 100)

    return jsonify({
        "logged_in": True,
        "nickname": st_copy["nickname"], "username": st_copy["username"],
        "balance": st_copy["balance"], "prev_balance": st_copy["prev_balance"],
        "ws_connected": st_copy["ws_connected"], "ws_error": st_copy["ws_error"],
        "current_session": st_copy["current_session"], "current_state": st_copy["current_state"],
        "current_prediction": st_copy["current_prediction"],
        "current_confidence": st_copy["current_confidence"],
        "current_result": st_copy["current_result"],
        "history": stats["history"],
        "ai_correct": stats["ai_stats"]["correct"], "ai_total": stats["ai_stats"]["total"],
        "ai_accuracy": ai_accuracy, "ai_weights_top": stats["ai_weights_top"],
        "auto_bet": st_copy["auto_bet"], "base_bet": st_copy["base_bet"],
        "max_losses": st_copy["max_losses"],
        "consecutive_losses": st_copy["consecutive_losses"],
        "auto_paused": st_copy["auto_paused"],
        "profit_target": st_copy["profit_target"],
        "auto_start_balance": st_copy["auto_start_balance"],
        "auto_target_reached": st_copy["auto_target_reached"],
        "session_profit": session_profit,
        "progress_pct": round(progress_pct, 1),
        "paper_bets": st_copy["paper_bets"], "paper_wins": st_copy["paper_wins"],
        "bet_history": st_copy["bet_history"][-30:],
        "total_wagered": st_copy["total_wagered"],
        "total_profit": st_copy["total_profit"],
        "total_wins": st_copy["total_wins"], "total_losses": st_copy["total_losses"],
        "win_rate": win_rate, "profit_curve": st_copy["profit_curve"][-50:],
        "best_streak": st_copy["best_streak"], "worst_streak": st_copy["worst_streak"],
        "events": st_copy["events"][-30:],
    })


@app.route("/api/settings", methods=["POST"])
def api_settings():
    uid = session.get("uid")
    if not uid:
        return jsonify({"success": False}), 401
    data = request.json or {}
    with USER_LOCK:
        st = USER_STATES.get(uid)
        if not st:
            return jsonify({"success": False}), 401
        if "base_bet" in data:
            st["base_bet"] = max(1000, int(data["base_bet"]))
        if "max_losses" in data:
            st["max_losses"] = max(1, min(20, int(data["max_losses"])))
        if "profit_target" in data:
            st["profit_target"] = max(0, int(data["profit_target"]))
        if "auto_bet" in data:
            v = bool(data["auto_bet"])
            if v and not st["auto_bet"]:
                # Bật auto → reset mốc chốt lãi
                st["auto_start_balance"] = st["balance"]
                st["auto_target_reached"] = False
                st["consecutive_losses"] = 0
                ulog(uid, f"⚡ Bật AUTO từ mốc {st['balance']:,}đ · chốt lãi {st['profit_target']:,}đ")
            st["auto_bet"] = v
            if not v:
                st["auto_paused"] = False
                st["consecutive_losses"] = 0
        ulog(uid, f"⚙️ Cược {st['base_bet']:,}đ · nghỉ {st['max_losses']} tay · chốt {st['profit_target']:,}đ · Auto {'ON' if st['auto_bet'] else 'OFF'}")
    return jsonify({"success": True})


# ==========================================================
# STARTUP
# ==========================================================
ensure_bg()

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 LC79 · Multi-User Auto Bet · Chốt lãi theo số dư")
    print(f"   BG Collector: {COLLECTOR_USER}")
    print(f"   WS: {WS_URL}/{WS_PATH}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
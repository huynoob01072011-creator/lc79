from flask import Flask, render_template_string, request, jsonify, session
import requests, hashlib, base64, json, time, threading, random, uuid

import socketio

app = Flask(__name__)
app.secret_key = "LC79_SECRET_KEY_CHANGE_ME_IN_PROD_2025_v3"

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
MAX_HISTORY     = 200
MAX_BET_HIST    = 200
MIN_TRAIN       = 10

# ==========================================================
# 🌐 GLOBAL STATE
# ==========================================================
GLOBAL_LOCK    = threading.RLock()
GLOBAL_HISTORY = []
SEEN_SESSIONS  = set()
GLOBAL_AI_STATS = {"correct": 0, "total": 0}
AI_WEIGHTS     = {f"core_{i:02d}": 1.0 for i in range(1, 36)}
METHOD_WEIGHTS = {
    "markov": 2.0, "streak": 1.8, "ngram2": 1.5, "ngram3": 2.2, "ngram4": 1.8,
    "freq5": 1.0, "freq8": 1.5, "freq12": 1.8, "freq20": 2.0,
    "momentum": 1.6, "alternating": 2.5, "rsi": 1.4, "bollinger": 1.6,
}
PRED_LOCK = threading.Lock()
PREDICTION_CACHE = {}

# ==========================================================
# 🌐 PER-USER STATE
# ==========================================================
USER_LOCK    = threading.RLock()
USER_STATES  = {}
USER_SOCKETS = {}

BG_STATE  = {"logged_in": False, "ws_connected": False, "ws_error": None, "nickname": None}
BG_SOCKET = {"sio": None}


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
        "has_bet_this_session": False, "waiting_for_result": False,
        "current_bet": 0,
        "auto_bet": False, "base_bet": 10000,
        "max_losses": 3, "consecutive_losses": 0, "auto_paused": False,
        "min_confidence": 0.55,
        "paper_bets": 0, "paper_wins": 0,
        "bet_history": [], "profit_curve": [], "events": [],
        "total_wagered": 0, "total_profit": 0,
        "total_wins": 0, "total_losses": 0,
        "best_streak": 0, "worst_streak": 0, "cur_streak": 0,
    }


# ==========================================================
# 🧠 AI
# ==========================================================
def _markov(hist):
    if len(hist) < 6: return None
    last = hist[-1]
    trans = {"TAI": {"TAI": 0, "XIU": 0}, "XIU": {"TAI": 0, "XIU": 0}}
    for i in range(len(hist) - 1):
        trans[hist[i]][hist[i+1]] += 1
    t = trans[last]; total = t["TAI"] + t["XIU"]
    if total < 3: return None
    if t["TAI"] > t["XIU"]: return ("TAI", t["TAI"] / total)
    if t["XIU"] > t["TAI"]: return ("XIU", t["XIU"] / total)
    return None

def _streak(hist):
    if len(hist) < 3: return None
    last = hist[-1]; cnt = 0
    for v in reversed(hist):
        if v == last: cnt += 1
        else: break
    if cnt >= 3: return ("XIU" if last == "TAI" else "TAI", min(cnt / 5.0, 0.9))
    if cnt == 2: return (last, 0.55)
    if cnt == 1: return (last, 0.45)
    return None

def _ngram(hist, n):
    if len(hist) < n + 3: return None
    pattern = tuple(hist[-n:])
    matches = []
    for i in range(len(hist) - n):
        if tuple(hist[i:i+n]) == pattern and i + n < len(hist):
            matches.append(hist[i+n])
    if len(matches) < 2: return None
    tai = matches.count("TAI"); xiu = matches.count("XIU")
    if tai > xiu: return ("TAI", tai / len(matches))
    if xiu > tai: return ("XIU", xiu / len(matches))
    return None

def _freq(hist, w):
    if len(hist) < w: return None
    seg = hist[-w:]
    tai = seg.count("TAI"); xiu = w - tai
    if tai == xiu: return None
    if tai > xiu * 1.4: return ("XIU", tai / w)
    if xiu > tai * 1.4: return ("TAI", xiu / w)
    return None

def _momentum(hist):
    if len(hist) < 5: return None
    scores = [1 if v == "TAI" else -1 for v in hist[-5:]]
    weights = [1, 1.3, 1.6, 2, 2.5]
    m = sum(s * w for s, w in zip(scores, weights))
    if m > 1.5: return ("TAI", min(m / 6.0, 0.85))
    if m < -1.5: return ("XIU", min(-m / 6.0, 0.85))
    return None

def _alternating(hist):
    if len(hist) < 5: return None
    if all(hist[-i-2] != hist[-i-1] for i in range(4)):
        return ("XIU" if hist[-1] == "TAI" else "TAI", 0.8)
    return None

def _rsi(hist):
    if len(hist) < 8: return None
    seg = hist[-8:]; tai = seg.count("TAI"); rsi = tai / 8 * 100
    if rsi > 65: return ("XIU", (rsi - 65) / 35)
    if rsi < 35: return ("TAI", (35 - rsi) / 35)
    return None

def _bollinger(hist):
    if len(hist) < 12: return None
    seg = hist[-12:]
    val = [1 if v == "TAI" else 0 for v in seg]
    mean = sum(val) / 12
    std = (sum((v - mean)**2 for v in val) / 12) ** 0.5
    if std == 0: return None
    last = val[-1]; upper = mean + 1.5 * std; lower = mean - 1.5 * std
    if last > upper: return ("XIU", min((last - upper) / 0.5, 0.9))
    if last < lower: return ("TAI", min((lower - last) / 0.5, 0.9))
    return None

def _vote_core(idx, hist):
    n = len(hist)
    if n < 6: return None
    if idx <= 7:
        w = 3 + (idx - 1); seg = hist[-w:]
        return "TAI" if seg.count("TAI") > seg.count("XIU") else "XIU"
    if idx <= 14:
        last = hist[-1]; cnt = 0
        for v in reversed(hist):
            if v == last: cnt += 1
            else: break
        if cnt >= 3: return "XIU" if last == "TAI" else "TAI"
        return last
    if idx <= 21:
        l3 = hist[-3:]
        if l3[0] == l3[2] and l3[1] != l3[0]: return l3[1]
        return "TAI" if hist[-1] == "XIU" else "XIU"
    if idx <= 28:
        w = 8 + (idx - 22); seg = hist[-w:]
        return "TAI" if seg.count("TAI") > seg.count("XIU") else "XIU"
    w = 5 + (idx - 29); seg = hist[-w:]
    tai, xiu = seg.count("TAI"), seg.count("XIU")
    if tai == xiu: return hist[-1]
    return "TAI" if tai > xiu else "XIU"

def analyze_all(hist):
    methods = {}
    for name, fn in [
        ("markov", _markov), ("streak", _streak),
        ("momentum", _momentum), ("alternating", _alternating),
        ("rsi", _rsi), ("bollinger", _bollinger),
    ]:
        v = fn(hist)
        if v: methods[name] = v
    for n in (2, 3, 4):
        v = _ngram(hist, n)
        if v: methods[f"ngram{n}"] = v
    for w in (5, 8, 12, 20):
        v = _freq(hist, w)
        if v: methods[f"freq{w}"] = v
    return methods

def make_prediction_vip():
    with GLOBAL_LOCK:
        hist = list(GLOBAL_HISTORY)
    if len(hist) < MIN_TRAIN: return None, 0.0
    tai_s = xiu_s = 0.0
    for i in range(1, 36):
        v = _vote_core(i, hist)
        if not v: continue
        w = AI_WEIGHTS.get(f"core_{i:02d}", 1.0)
        if v == "TAI": tai_s += w * 0.3
        else: xiu_s += w * 0.3
    for name, (vote, conf) in analyze_all(hist).items():
        weight = METHOD_WEIGHTS.get(name, 1.0)
        score = conf * weight
        if vote == "TAI": tai_s += score
        else: xiu_s += score
    if tai_s == 0 and xiu_s == 0:
        return random.choice(["TAI", "XIU"]), 0.5
    total = tai_s + xiu_s
    if tai_s > xiu_s: return "TAI", round(tai_s / total, 3)
    elif xiu_s > tai_s: return "XIU", round(xiu_s / total, 3)
    return random.choice(["TAI", "XIU"]), 0.5

def update_ai_weights(result):
    with GLOBAL_LOCK:
        hist = list(GLOBAL_HISTORY)
    if len(hist) < 6: return
    for i in range(1, 36):
        key = f"core_{i:02d}"
        v = _vote_core(i, hist[:-1])
        if not v: continue
        if v == result:
            AI_WEIGHTS[key] = min(AI_WEIGHTS[key] + 0.05, 5.0)
        else:
            AI_WEIGHTS[key] = max(AI_WEIGHTS[key] - 0.03, 0.1)

def get_cached_prediction(sid):
    with PRED_LOCK:
        if sid in PREDICTION_CACHE:
            return PREDICTION_CACHE[sid]
    pred, conf = make_prediction_vip()
    with PRED_LOCK:
        PREDICTION_CACHE[sid] = (pred, conf)
        if len(PREDICTION_CACHE) > 500:
            keys = list(PREDICTION_CACHE.keys())[:100]
            for k in keys: PREDICTION_CACHE.pop(k, None)
    return pred, conf

def record_result(sid, result, pred):
    with GLOBAL_LOCK:
        if sid in SEEN_SESSIONS: return False
        SEEN_SESSIONS.add(sid)
        GLOBAL_HISTORY.append(result)
        if len(GLOBAL_HISTORY) > MAX_HISTORY:
            del GLOBAL_HISTORY[:-MAX_HISTORY]
        if pred:
            GLOBAL_AI_STATS["total"] += 1
            if pred == result:
                GLOBAL_AI_STATS["correct"] += 1
    update_ai_weights(result)
    return True


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
            headers={"authority":"wlb.tele68.com","content-type":"application/json",
                     "origin":"https://tele68.com","referer":"https://tele68.com/",
                     "user-agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
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
                st["ws_connected"] = True
                st["ws_error"] = None
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
        pred, conf = get_cached_prediction(sid)
        with USER_LOCK:
            st = USER_STATES.get(uid)
            if not st: return
            st["current_session"] = sid
            st["current_state"] = "BETTING"
            st["current_result"] = None
            st["has_bet_this_session"] = False
            st["waiting_for_result"] = False
            st["current_prediction"] = pred
            st["current_confidence"] = conf
        if pred:
            ulog(uid, f"🔔 Phiên #{sid} · AI: {pred} ({conf*100:.0f}%)")
        else:
            with GLOBAL_LOCK:
                hn = len(GLOBAL_HISTORY)
            ulog(uid, f"🔔 Phiên #{sid} · chờ data ({hn}/{MIN_TRAIN})")

    @sio.on("tick-update", namespace=WS_NAMESPACE)
    def on_tick(data):
        gs = data.get("state")
        with USER_LOCK:
            st = USER_STATES.get(uid)
            if not st: return
            st["current_state"] = gs
            should_bet = (gs == "BETTING" and st["auto_bet"]
                and not st["auto_paused"] and st["current_prediction"]
                and st["current_confidence"] >= st["min_confidence"]
                and not st["has_bet_this_session"])
            if not should_bet: return
            amount = int(st["base_bet"])
            if amount > st["balance"] * 0.9:
                ulog(uid, "⚠️ Số dư không đủ")
                return
            try:
                sio.emit("bet", {"type": st["current_prediction"], "amount": amount},
                         namespace=WS_NAMESPACE)
                st["has_bet_this_session"] = True
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

    @sio.on("session-result", namespace=WS_NAMESPACE)
    def on_session_result(data):
        result = data.get("resultTruyenThong", "N/A")
        dices = data.get("dices", [0, 0, 0])
        if result not in ("TAI", "XIU"): return

        sid_out = None
        pred_out = None
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
                    ulog(uid, "⏸ vẫn nghỉ")
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

            sid_out = sid
            pred_out = pred

        if sid_out:
            record_result(sid_out, result, pred_out)

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
# 🔌 BG collector
# ==========================================================
def run_bg_ws(token):
    sio = socketio.Client(reconnection=True, reconnection_attempts=999,
                          logger=False, engineio_logger=False)
    BG_SOCKET["sio"] = sio
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
        pred, _ = get_cached_prediction(sid)
        if record_result(sid, result, pred):
            with GLOBAL_LOCK:
                hn = len(GLOBAL_HISTORY)
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
def index(): return render_template_string(HTML_TEMPLATE)


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
    with GLOBAL_LOCK:
        history_copy = GLOBAL_HISTORY[-50:]
        ai_stats = dict(GLOBAL_AI_STATS)
        ai_weights_top = sorted(AI_WEIGHTS.items(), key=lambda x: x[1], reverse=True)[:10]

    win_rate = round(
        st_copy["total_wins"] / (st_copy["total_wins"] + st_copy["total_losses"]) * 100, 1
    ) if (st_copy["total_wins"] + st_copy["total_losses"]) else 0
    ai_accuracy = round(
        ai_stats["correct"] / ai_stats["total"] * 100, 1
    ) if ai_stats["total"] else 0

    return jsonify({
        "logged_in": True,
        "nickname": st_copy["nickname"], "username": st_copy["username"],
        "balance": st_copy["balance"], "prev_balance": st_copy["prev_balance"],
        "ws_connected": st_copy["ws_connected"], "ws_error": st_copy["ws_error"],
        "current_session": st_copy["current_session"], "current_state": st_copy["current_state"],
        "current_prediction": st_copy["current_prediction"],
        "current_confidence": st_copy["current_confidence"],
        "current_result": st_copy["current_result"],
        "history": history_copy,
        "ai_correct": ai_stats["correct"], "ai_total": ai_stats["total"],
        "ai_accuracy": ai_accuracy, "ai_weights_top": ai_weights_top,
        "auto_bet": st_copy["auto_bet"], "base_bet": st_copy["base_bet"],
        "max_losses": st_copy["max_losses"],
        "consecutive_losses": st_copy["consecutive_losses"],
        "auto_paused": st_copy["auto_paused"],
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
        if "auto_bet" in data:
            v = bool(data["auto_bet"])
            st["auto_bet"] = v
            if not v:
                st["auto_paused"] = False
                st["consecutive_losses"] = 0
        ulog(uid, f"⚙️ Cài đặt: cược {st['base_bet']:,}đ · nghỉ {st['max_losses']} tay · Auto {'ON' if st['auto_bet'] else 'OFF'}")
    return jsonify({"success": True})


# ==========================================================
# HTML TEMPLATE
# ==========================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<title>LC79 · Auto Bet Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.2.0/crypto-js.min.js"></script>
<style>
  *{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  :root{
    --primary:#e63946;--primary-2:#ff4d6d;--primary-dark:#b5172a;
    --gold:#f4b400;--accent:#ffb703;--ink:#0d1117;--muted:#6b7280;
    --line:#e5e7eb;--bg:#f6f7fb;--success:#10b981;--danger:#ef4444;
    --blue:#3b82f6;--purple:#8b5cf6;
    --shadow-sm:0 2px 8px rgba(15,23,42,.04);
    --shadow-md:0 8px 24px rgba(15,23,42,.06);
    --shadow-lg:0 20px 50px rgba(15,23,42,.1);
  }
  body{font-family:'Plus Jakarta Sans',sans-serif;background:var(--bg);color:#1f2937;min-height:100vh;line-height:1.5;display:flex;flex-direction:column;-webkit-font-smoothing:antialiased;background-image:radial-gradient(circle at 10% 0%,rgba(230,57,70,.06) 0%,transparent 40%),radial-gradient(circle at 90% 10%,rgba(59,130,246,.06) 0%,transparent 40%);background-attachment:fixed}
  code{user-select:text;-webkit-user-select:text}
  input{user-select:text;-webkit-user-select:text}

  .header{background:rgba(255,255,255,.85);backdrop-filter:saturate(180%) blur(16px);-webkit-backdrop-filter:saturate(180%) blur(16px);border-bottom:1px solid rgba(15,23,42,.06);position:sticky;top:0;z-index:100}
  .header-inner{max-width:1180px;margin:0 auto;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
  .brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}
  .brand-mark{width:40px;height:40px;border-radius:11px;background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));display:grid;place-items:center;color:#fff;font-family:'Space Grotesk';font-weight:700;font-size:12px;box-shadow:0 6px 16px rgba(230,57,70,.35)}
  .brand-name{display:flex;flex-direction:column;line-height:1.15}
  .brand-name strong{font-family:'Space Grotesk';font-size:14px;font-weight:700;color:var(--ink)}
  .brand-name small{font-size:10px;letter-spacing:1.8px;color:var(--muted);text-transform:uppercase;font-weight:600}
  .header-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  .status-pill{display:inline-flex;align-items:center;gap:7px;padding:6px 13px;border-radius:999px;background:#fff;border:1px solid var(--line);font-size:12px;font-weight:600;color:var(--ink);box-shadow:var(--shadow-sm)}
  .status-dot{width:9px;height:9px;border-radius:50%;background:#9ca3af;box-shadow:0 0 0 3px rgba(0,0,0,.08)}
  .status-dot.live{background:#10b981;box-shadow:0 0 0 3px rgba(16,185,129,.28);animation:pulse 1.5s infinite}
  .status-dot.off{background:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.28)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}

  .user-chip{display:flex;align-items:center;gap:8px;padding:4px 12px 4px 4px;background:#fff;border:1px solid var(--line);border-radius:999px;font-size:13px;font-weight:600;color:var(--ink);max-width:200px}
  .user-chip .avatar{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));color:#fff;display:grid;place-items:center;font-size:11px;font-weight:700;text-transform:uppercase;flex-shrink:0}
  .user-chip span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .btn-logout{padding:8px 14px;background:#fef2f2;color:var(--primary);border:1px solid #fecaca;border-radius:9px;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px;transition:.2s}
  .btn-logout:hover{background:#fee2e2}

  #loginView{display:none;min-height:100vh;flex-direction:column}
  .login-main{flex:1;display:grid;grid-template-columns:1fr 1fr;max-width:1180px;width:100%;margin:0 auto;padding:24px 20px;gap:32px;align-items:center}
  .brand-panel{position:relative;min-height:520px;border-radius:22px;padding:40px 36px;color:#fff;background:radial-gradient(circle at 20% 10%,rgba(255,183,3,.18) 0%,transparent 40%),radial-gradient(circle at 90% 90%,rgba(255,77,109,.25) 0%,transparent 45%),linear-gradient(150deg,#1a1f2e 0%,#0d1117 60%,#1a0a10 100%);overflow:hidden;display:flex;flex-direction:column;justify-content:space-between;box-shadow:var(--shadow-lg);isolation:isolate}
  .brand-panel::before{content:'';position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:40px 40px;mask-image:radial-gradient(ellipse at 50% 0%,#000 30%,transparent 75%);-webkit-mask-image:radial-gradient(ellipse at 50% 0%,#000 30%,transparent 75%)}
  .brand-panel>*{position:relative;z-index:1}
  .badge-new{display:inline-flex;align-items:center;gap:7px;padding:5px 11px 5px 7px;border-radius:999px;font-size:11px;font-weight:600;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);width:fit-content}
  .badge-new .dot{width:6px;height:6px;border-radius:50%;background:var(--success);box-shadow:0 0 0 3px rgba(16,185,129,.25)}
  .brand-panel h1{font-family:'Space Grotesk';font-size:clamp(24px,3vw,36px);line-height:1.18;font-weight:700;letter-spacing:-.7px;margin:18px 0 12px;max-width:440px}
  .brand-panel h1 .grad{background:linear-gradient(120deg,#ff4d6d 0%,#ffb703 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
  .brand-panel p.lead{font-size:14.5px;line-height:1.7;color:rgba(255,255,255,.65);max-width:400px}
  .feature-list{display:grid;gap:10px;margin-top:24px}
  .feature-item{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:11px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.06)}
  .feature-icon{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,rgba(255,77,109,.25),rgba(255,183,3,.2));display:grid;place-items:center;flex-shrink:0;color:#ffb703}
  .feature-item strong{display:block;font-size:13px;font-weight:600;color:#fff;margin-bottom:1px}
  .feature-item small{font-size:11.5px;color:rgba(255,255,255,.5)}
  .login-panel{display:flex;justify-content:center;align-items:center}
  .login-card{width:100%;max-width:420px;background:#fff;border-radius:18px;padding:36px 30px 32px;border:1px solid var(--line);box-shadow:var(--shadow-md)}
  .login-card h2{font-family:'Space Grotesk';font-size:22px;font-weight:700;color:var(--ink);margin-bottom:5px}
  .login-card .subtitle{font-size:13.5px;color:var(--muted);margin-bottom:24px}
  .alert{display:none;align-items:flex-start;gap:9px;padding:11px 13px;border-radius:10px;font-size:13px;margin-bottom:16px}
  .alert.show{display:flex}
  .alert.error{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c}
  .field{margin-bottom:16px}
  .field label{display:block;font-size:12.5px;font-weight:600;color:#374151;margin-bottom:6px}
  .input-box{position:relative}
  .input-box input{width:100%;padding:12px 42px 12px 40px;font-size:14px;font-family:inherit;color:var(--ink);background:#fff;border:1.5px solid #e5e7eb;border-radius:10px;outline:none;font-weight:500;transition:.2s}
  .input-box input:focus{border-color:var(--primary);box-shadow:0 0 0 4px rgba(230,57,70,.1)}
  .input-box .lead{position:absolute;left:13px;top:50%;transform:translateY(-50%);width:17px;height:17px;color:#9ca3af;pointer-events:none}
  .btn-eye{position:absolute;right:6px;top:50%;transform:translateY(-50%);width:30px;height:30px;border-radius:7px;border:none;background:transparent;color:#9ca3af;cursor:pointer;display:grid;place-items:center;font-size:15px}
  .btn-submit{width:100%;padding:13px;font-size:14.5px;font-weight:600;font-family:inherit;color:#fff;background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));border:none;border-radius:10px;cursor:pointer;box-shadow:0 5px 16px rgba(230,57,70,.32);display:flex;align-items:center;justify-content:center;gap:8px;transition:.2s}
  .btn-submit:hover:not(:disabled){transform:translateY(-1px)}
  .btn-submit:disabled{opacity:.7;cursor:not-allowed}
  .spinner{width:15px;height:15px;border:2px solid rgba(255,255,255,.35);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;display:none}
  .btn-submit.loading .spinner{display:block}
  @keyframes spin{to{transform:rotate(360deg)}}
  .footer{background:#fff;border-top:1px solid var(--line);padding:16px 20px;text-align:center;font-size:12px;color:var(--muted);margin-top:auto}
  .footer b{background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;font-weight:700}

  @media(max-width:900px){.login-main{grid-template-columns:1fr;padding:18px 16px;gap:20px}.brand-panel{min-height:auto;padding:28px 24px}.brand-panel h1{font-size:22px;margin:14px 0 10px}.feature-list{display:none}}

  #dashboardView{display:none;flex-direction:column;min-height:100vh}
  .dash{flex:1;max-width:1180px;width:100%;margin:0 auto;padding:20px;display:flex;flex-direction:column;gap:14px}

  .welcome-card{background:linear-gradient(135deg,#ff4d6d 0%,#b5172a 50%,#8b0f1f 100%);color:#fff;padding:22px 24px;border-radius:20px;display:flex;align-items:center;gap:16px;box-shadow:0 14px 32px rgba(230,57,70,.32);position:relative;overflow:hidden;isolation:isolate}
  .welcome-card::before{content:'';position:absolute;width:300px;height:300px;border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,.2),transparent 70%);top:-120px;right:-100px;z-index:0}
  .welcome-card::after{content:'';position:absolute;width:200px;height:200px;border-radius:50%;background:radial-gradient(circle,rgba(255,183,3,.25),transparent 70%);bottom:-80px;left:-60px;z-index:0}
  .welcome-avatar{width:58px;height:58px;border-radius:15px;background:rgba(255,255,255,.24);backdrop-filter:blur(8px);display:grid;place-items:center;font-size:23px;font-weight:800;font-family:'Space Grotesk';border:2px solid rgba(255,255,255,.35);text-transform:uppercase;flex-shrink:0;position:relative;z-index:1}
  .welcome-info{position:relative;z-index:1;flex:1;min-width:0}
  .welcome-info .greet{font-size:12px;opacity:.9;margin-bottom:2px;font-weight:500}
  .welcome-info h2{font-family:'Space Grotesk';font-size:20px;font-weight:700;margin-bottom:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:-.3px}
  .level-badge{display:inline-flex;align-items:center;gap:5px;padding:4px 12px;background:linear-gradient(135deg,#ffb703,#ff8c00);border-radius:999px;font-size:11px;font-weight:800;color:#1a1f2e;text-transform:uppercase;letter-spacing:.4px;box-shadow:0 3px 10px rgba(0,0,0,.15)}

  .card{background:#fff;border-radius:18px;padding:20px 22px;border:1px solid rgba(15,23,42,.06);box-shadow:var(--shadow-md);transition:box-shadow .2s}
  .card:hover{box-shadow:var(--shadow-lg)}
  .card h3{font-family:'Space Grotesk';font-size:14.5px;font-weight:700;color:var(--ink);margin-bottom:14px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;letter-spacing:-.2px}
  .card h3 .badge{margin-left:auto;font-size:10.5px;font-weight:700;color:var(--muted);background:#f3f4f6;padding:3px 9px;border-radius:6px;letter-spacing:.3px}

  .settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px}
  @media(max-width:600px){.settings-grid{grid-template-columns:1fr}}
  .setting-item label{display:block;font-size:12px;font-weight:600;color:#374151;margin-bottom:6px}
  .setting-item input{width:100%;padding:11px 14px;font-size:14.5px;font-family:inherit;font-weight:600;color:var(--ink);background:#f9fafb;border:1.5px solid #e5e7eb;border-radius:10px;outline:none;transition:.2s}
  .setting-item input:focus{border-color:var(--primary);background:#fff;box-shadow:0 0 0 3px rgba(230,57,70,.1)}
  .setting-hint{font-size:11px;color:var(--muted);margin-top:4px}
  .settings-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  .btn-save{flex:1;min-width:140px;padding:12px 20px;background:linear-gradient(135deg,#3b82f6,#1d4ed8);color:#fff;border:none;border-radius:11px;font-family:inherit;font-size:13.5px;font-weight:700;cursor:pointer;box-shadow:0 6px 16px rgba(59,130,246,.3);transition:.2s}
  .btn-save:hover{transform:translateY(-1px)}
  .btn-save.saved{background:linear-gradient(135deg,#10b981,#059669)}
  .btn-auto{padding:12px 24px;border:none;border-radius:11px;font-family:inherit;font-size:13.5px;font-weight:700;cursor:pointer;transition:.25s;min-width:170px}
  .btn-auto.off{background:#f3f4f6;color:#6b7280;border:1.5px solid #e5e7eb}
  .btn-auto.on{background:linear-gradient(135deg,#10b981,#059669);color:#fff;box-shadow:0 8px 20px rgba(16,185,129,.4)}
  .btn-auto.paused{background:linear-gradient(135deg,#f59e0b,#d97706);color:#fff;box-shadow:0 8px 20px rgba(245,158,11,.4)}
  .auto-status{margin-top:12px;padding:11px 15px;border-radius:11px;background:#f8f9fb;border:1px solid #eef0f4;font-size:12.5px;color:#374151;display:flex;align-items:center;gap:8px;flex-wrap:wrap;transition:.3s}
  .auto-status.active{background:linear-gradient(135deg,#ecfdf5,#d1fae5);border-color:#a7f3d0;color:#065f46}
  .auto-status.paused{background:linear-gradient(135deg,#fef3c7,#fde68a);border-color:#fbbf24;color:#92400e}

  .session-card{background:linear-gradient(135deg,#1a1f2e,#0d1117);color:#fff;border-radius:20px;padding:22px 24px;box-shadow:0 14px 34px rgba(0,0,0,.22);border:1px solid rgba(255,255,255,.06);position:relative;overflow:hidden;isolation:isolate}
  .session-card::before{content:'';position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:32px 32px;mask-image:radial-gradient(ellipse at 50% 0%,#000 30%,transparent 75%);-webkit-mask-image:radial-gradient(ellipse at 50% 0%,#000 30%,transparent 75%)}
  .session-card>*{position:relative;z-index:1}
  .session-head{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
  .session-id{font-family:'Space Grotesk';font-size:22px;font-weight:800;letter-spacing:-.5px}
  .session-tag{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;padding:4px 10px;border-radius:6px;background:rgba(255,255,255,.1);color:#a8b3d0}
  .session-tag.betting{background:rgba(16,185,129,.18);color:#34d399;animation:pulse 2s infinite}
  .pred-row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media(max-width:640px){.pred-row{grid-template-columns:1fr}}
  .pred-main,.result-main{text-align:center;padding:16px 12px;border-radius:13px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.09)}
  .pred-label{font-size:11px;letter-spacing:1.5px;color:#8b949e;text-transform:uppercase;font-weight:700;margin-bottom:8px}
  .pred-big{font-family:'Space Grotesk';font-size:42px;font-weight:800;letter-spacing:-1px;line-height:1}
  .pred-big.tai{color:#60a5fa;text-shadow:0 0 24px rgba(96,165,250,.4)}
  .pred-big.xiu{color:#f87171;text-shadow:0 0 24px rgba(248,113,113,.4)}
  .pred-big.empty{color:#4b5563;font-size:17px;font-weight:500;letter-spacing:0}
  .pred-sub{font-size:11.5px;color:#8b949e;margin-top:7px}
  .result-big{font-family:'Space Grotesk';font-size:36px;font-weight:800;letter-spacing:-1px;line-height:1}
  .result-big.tai{color:#60a5fa}.result-big.xiu{color:#f87171}
  .result-big.empty{color:#4b5563;font-size:16px;font-weight:500}
  .dices{font-family:'Consolas',monospace;font-size:13px;color:#c9d1d9;margin-top:8px;letter-spacing:2px}
  .result-mark{font-size:12px;font-weight:700;margin-top:7px}
  .result-mark.ok{color:#34d399}.result-mark.fail{color:#f87171}.result-mark.none{color:#8b949e}

  .stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
  @media(max-width:900px){.stats-grid{grid-template-columns:repeat(2,1fr)}}
  @media(max-width:480px){.stats-grid{grid-template-columns:1fr}}
  .stat-card{background:#fff;border-radius:16px;padding:18px;border:1px solid rgba(15,23,42,.06);box-shadow:var(--shadow-md);position:relative;overflow:hidden;transition:transform .2s,box-shadow .2s}
  .stat-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-lg)}
  .stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:4px}
  .stat-card.balance::before{background:linear-gradient(90deg,#ffb703,#f4b400)}
  .stat-card.pl::before{background:linear-gradient(90deg,#10b981,#059669)}
  .stat-card.pl.neg::before{background:linear-gradient(90deg,#ef4444,#b91c1c)}
  .stat-card.wr::before{background:linear-gradient(90deg,#8b5cf6,#6366f1)}
  .stat-card.wagered::before{background:linear-gradient(90deg,#3b82f6,#1d4ed8)}
  .stat-icon{position:absolute;top:16px;right:16px;width:32px;height:32px;border-radius:9px;display:grid;place-items:center;font-size:15px;opacity:.7}
  .stat-card.balance .stat-icon{background:#fef3c7;color:#d97706}
  .stat-card.pl .stat-icon{background:#d1fae5;color:#059669}
  .stat-card.pl.neg .stat-icon{background:#fee2e2;color:#dc2626}
  .stat-card.wr .stat-icon{background:#ede9fe;color:#7c3aed}
  .stat-card.wagered .stat-icon{background:#dbeafe;color:#2563eb}
  .stat-label{font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
  .stat-value{font-family:'Space Grotesk';font-size:22px;font-weight:700;color:var(--ink);letter-spacing:-.5px;word-break:break-all;transition:color .3s}
  .stat-value.pos{color:var(--success)}
  .stat-value.neg{color:var(--danger)}
  .stat-value.flash{animation:flash .8s ease}
  @keyframes flash{0%,100%{transform:scale(1)}50%{transform:scale(1.08);color:#ffb703}}
  .stat-hint{font-size:10.5px;color:var(--muted);margin-top:4px;font-weight:500}

  .charts-grid{display:grid;grid-template-columns:2fr 1fr;gap:14px}
  @media(max-width:900px){.charts-grid{grid-template-columns:1fr}}
  .chart-container{position:relative;height:220px;width:100%}
  .chart-empty{position:absolute;inset:0;display:grid;place-items:center;color:var(--muted);font-size:13px;font-style:italic;pointer-events:none}

  .table-wrap{overflow-x:auto;margin:0 -22px;padding:0 22px}
  table.bet-table{width:100%;border-collapse:collapse;font-size:12.5px;min-width:600px}
  table.bet-table thead th{text-align:left;padding:9px 10px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);border-bottom:1.5px solid var(--line);background:#f9fafb}
  table.bet-table tbody td{padding:11px 10px;border-bottom:1px solid #f3f4f6;font-weight:500}
  table.bet-table tbody tr:hover{background:#f9fafb}
  table.bet-table tbody tr:last-child td{border-bottom:none}
  .badge-mini{display:inline-block;padding:2px 8px;border-radius:6px;font-size:10.5px;font-weight:700;letter-spacing:.3px}
  .badge-mini.tai{background:#dbeafe;color:#1d4ed8}
  .badge-mini.xiu{background:#fee2e2;color:#b91c1c}
  .badge-mini.win{background:#d1fae5;color:#047857}
  .badge-mini.loss{background:#fee2e2;color:#b91c1c}
  .pl-cell{font-family:'Space Grotesk';font-weight:700;text-align:right}
  .pl-cell.pos{color:var(--success)}
  .pl-cell.neg{color:var(--danger)}
  .num-cell{font-family:'Space Grotesk';font-weight:600;text-align:right;color:var(--ink)}
  .table-empty{padding:32px;text-align:center;color:var(--muted);font-size:13px;font-style:italic}

  .recent-10{display:grid;grid-template-columns:repeat(10,1fr);gap:8px}
  @media(max-width:720px){.recent-10{grid-template-columns:repeat(5,1fr)}}
  .hist-big{aspect-ratio:1;display:grid;place-items:center;border-radius:11px;font-family:'Space Grotesk';font-weight:800;font-size:18px;color:#fff;letter-spacing:-.5px;box-shadow:0 3px 8px rgba(0,0,0,.08);transition:transform .15s}
  .hist-big:hover{transform:scale(1.05)}
  .hist-big.tai{background:linear-gradient(135deg,#3b82f6,#1d4ed8)}
  .hist-big.xiu{background:linear-gradient(135deg,#ef4444,#b91c1c)}
  .hist-big.empty{background:#f3f4f6;color:#d1d5db;font-size:13px}
  .history-grid{display:flex;flex-wrap:wrap;gap:5px}
  .hist-chip{min-width:34px;text-align:center;padding:5px 8px;border-radius:7px;font-size:11px;font-weight:700;color:#fff;font-family:'Space Grotesk'}
  .hist-chip.tai{background:linear-gradient(135deg,#3b82f6,#1d4ed8)}
  .hist-chip.xiu{background:linear-gradient(135deg,#ef4444,#b91c1c)}
  .hist-chip.core{min-width:auto;padding:5px 10px;background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe}
  .hist-empty{font-size:12px;color:var(--muted);font-style:italic}

  .event-list{font-family:'Consolas',monospace;font-size:11.5px;background:#0d1117;color:#c9d1d9;padding:12px 14px;border-radius:11px;max-height:220px;overflow-y:auto;line-height:1.65;word-break:break-word}
  .event-list .t{color:#6e7681}

  .loading-overlay{position:fixed;inset:0;background:rgba(246,247,251,.95);display:grid;place-items:center;z-index:999;transition:opacity .3s;backdrop-filter:blur(6px)}
  .loading-overlay.hidden{opacity:0;pointer-events:none}
  .loading-box{background:#fff;padding:36px 44px;border-radius:20px;box-shadow:var(--shadow-lg);text-align:center;max-width:360px}
  .loading-spin{width:48px;height:48px;border:4px solid #f3f4f6;border-top-color:var(--primary);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 18px}
  .loading-box h3{font-family:'Space Grotesk';font-size:17px;font-weight:700;color:var(--ink);margin-bottom:6px}
  .loading-box p{font-size:13px;color:var(--muted);line-height:1.6}

  @media(max-width:720px){
    .welcome-avatar{width:50px;height:50px;font-size:20px}
    .welcome-info h2{font-size:17px}
    .session-id{font-size:18px}
    .pred-big{font-size:34px}.result-big{font-size:28px}
    .dash{padding:14px;gap:12px}
    .stat-value{font-size:19px}
    .card{padding:16px 18px;border-radius:16px}
    .table-wrap{margin:0 -18px;padding:0 18px}
    .user-chip span{display:none}
    .user-chip{padding:4px}
  }
</style>
</head>
<body>

<div class="loading-overlay" id="loadingOverlay">
  <div class="loading-box">
    <div class="loading-spin"></div>
    <h3>Đang kiểm tra phiên đăng nhập...</h3>
    <p>Vui lòng chờ giây lát.</p>
  </div>
</div>

<div id="loginView">
  <header class="header">
    <div class="header-inner">
      <a href="#" class="brand">
        <div class="brand-mark">LC79</div>
        <div class="brand-name"><strong>LC79 · AUTO BET</strong><small>AI Analytics System</small></div>
      </a>
    </div>
  </header>

  <main class="login-main">
    <section class="brand-panel">
      <div>
        <div class="badge-new"><span class="dot"></span>AI sẵn sàng · thu thập 24/7</div>
        <h1>Đăng nhập acc của bạn<br><span class="grad">để bắt đầu auto cược</span></h1>
        <p class="lead">Mỗi người dùng có phiên riêng — AI dùng chung dữ liệu (35 cores + 13 phương pháp) để dự đoán. Auto bet chạy trên chính tài khoản của bạn.</p>
        <div class="feature-list">
          <div class="feature-item">
            <div class="feature-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </div>
            <div><strong>Bảo mật MD5</strong><small>Mật khẩu mã hóa 1 chiều</small></div>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            </div>
            <div><strong>WebSocket riêng</strong><small>Mỗi user 1 kết nối độc lập</small></div>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
            <div><strong>Auto cược riêng</strong><small>Cài đặt theo acc của bạn</small></div>
          </div>
        </div>
      </div>
    </section>

    <section class="login-panel">
      <div class="login-card">
        <h2>Đăng nhập 👋</h2>
        <p class="subtitle">Nhập tài khoản game của bạn</p>
        <div class="alert error" id="alertBox"><span id="alertText"></span></div>
        <form id="loginForm" novalidate>
          <div class="field">
            <label for="username">Tên đăng nhập</label>
            <div class="input-box">
              <input type="text" id="username" placeholder="Tên đăng nhập game" autocomplete="username" required />
              <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
          </div>
          <div class="field">
            <label for="password">Mật khẩu</label>
            <div class="input-box">
              <input type="password" id="password" placeholder="Mật khẩu" autocomplete="current-password" required />
              <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <button type="button" class="btn-eye" id="togglePass">👁</button>
            </div>
          </div>
          <button type="submit" class="btn-submit" id="btnLogin">
            <span class="spinner"></span><span class="btn-text">Đăng nhập & Kết nối WS</span>
          </button>
        </form>
      </div>
    </section>
  </main>

  <footer class="footer">© 2025 LC79 — <b>HuyDaiXuVN</b></footer>
</div>

<div id="dashboardView">
  <header class="header">
    <div class="header-inner">
      <a href="#" class="brand">
        <div class="brand-mark">LC79</div>
        <div class="brand-name"><strong>LC79 · AUTO BET</strong><small>Live · AI · Analytics</small></div>
      </a>
      <div class="header-right">
        <div class="status-pill">
          <span class="status-dot" id="wsDot"></span>
          <span id="wsLabel">Đang kết nối...</span>
        </div>
        <div class="user-chip">
          <div class="avatar" id="userAvatar">U</div>
          <span id="userChipName">User</span>
        </div>
        <button class="btn-logout" id="btnLogout">Đăng xuất</button>
      </div>
    </div>
  </header>

  <main class="dash">
    <div class="welcome-card">
      <div class="welcome-avatar" id="welcomeAvatar">U</div>
      <div class="welcome-info">
        <div class="greet" id="welcomeGreet">AI đa tầng · 35 cores + 13 phương pháp</div>
        <h2 id="welcomeName">Đang chờ...</h2>
        <span class="level-badge" id="statBadge">ĐANG KHỞI ĐỘNG</span>
      </div>
    </div>

    <div class="card">
      <h3>⚙️ Cài đặt Auto Cược</h3>
      <div class="settings-grid">
        <div class="setting-item">
          <label>💰 Tiền cược mỗi ván (VNĐ)</label>
          <input type="number" id="baseBetInput" value="10000" min="1000" step="1000">
          <div class="setting-hint">Tối thiểu 1.000đ · khuyến nghị ≤ 10% số dư</div>
        </div>
        <div class="setting-item">
          <label>🛑 Nghỉ sau N tay thua liên tiếp</label>
          <input type="number" id="maxLossesInput" value="3" min="1" max="20">
          <div class="setting-hint">Tự bật lại khi AI đoán đúng (paper trade)</div>
        </div>
      </div>
      <div class="settings-actions">
        <button class="btn-save" id="btnSaveSettings">💾 Lưu cài đặt</button>
        <button class="btn-auto off" id="btnToggleAuto">⚡ Bật Auto Cược</button>
      </div>
      <div class="auto-status" id="autoStatus">Auto: TẮT</div>
    </div>

    <div class="session-card">
      <div class="session-head">
        <span class="session-id" id="sessId">#—</span>
        <span class="session-tag" id="sessTag">WAITING</span>
      </div>
      <div class="pred-row">
        <div class="pred-main">
          <div class="pred-label">🤖 AI DỰ ĐOÁN</div>
          <div class="pred-big empty" id="predVal">Chờ đủ 10 phiên</div>
          <div class="pred-sub" id="predSub">Đang tích lũy...</div>
        </div>
        <div class="result-main">
          <div class="pred-label">🎲 KẾT QUẢ PHIÊN TRƯỚC</div>
          <div class="result-big empty" id="resultVal">—</div>
          <div class="dices" id="resultDices">— · — · —</div>
          <div class="result-mark none" id="resultMark">—</div>
        </div>
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat-card balance">
        <div class="stat-icon">💰</div>
        <div class="stat-label">Số dư</div>
        <div class="stat-value" id="balanceVal">—</div>
        <div class="stat-hint">VND</div>
      </div>
      <div class="stat-card pl" id="plCard">
        <div class="stat-icon" id="plIcon">📈</div>
        <div class="stat-label">Tổng lãi/lỗ</div>
        <div class="stat-value" id="plVal">0</div>
        <div class="stat-hint" id="plHint">0 ván</div>
      </div>
      <div class="stat-card wr">
        <div class="stat-icon">🎯</div>
        <div class="stat-label">Win rate</div>
        <div class="stat-value" id="wrVal">0%</div>
        <div class="stat-hint" id="wrHint">0/0</div>
      </div>
      <div class="stat-card wagered">
        <div class="stat-icon">💸</div>
        <div class="stat-label">Tổng đã cược</div>
        <div class="stat-value" id="wageredVal">0</div>
        <div class="stat-hint" id="streakHint">Best: 0</div>
      </div>
    </div>

    <div class="charts-grid">
      <div class="card">
        <h3>📈 Biểu đồ lãi/lỗ tích lũy</h3>
        <div class="chart-container">
          <canvas id="profitChart"></canvas>
          <div class="chart-empty" id="profitEmpty">Chưa có dữ liệu cược</div>
        </div>
      </div>
      <div class="card">
        <h3>🎯 Tỷ lệ thắng/thua</h3>
        <div class="chart-container">
          <canvas id="winChart"></canvas>
          <div class="chart-empty" id="winEmpty">Chưa có dữ liệu</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>📋 Lịch sử cược <span class="badge" id="betCountBadge">0 ván</span></h3>
      <div class="table-wrap">
        <table class="bet-table">
          <thead>
            <tr>
              <th>Phiên</th>
              <th>Dự đoán</th>
              <th>Kết quả</th>
              <th style="text-align:right">Tiền cược</th>
              <th style="text-align:right">Lãi/Lỗ</th>
              <th style="text-align:right">Số dư sau</th>
              <th style="text-align:right">Thời gian</th>
            </tr>
          </thead>
          <tbody id="betTableBody">
            <tr><td colspan="7" class="table-empty">Chưa có ván cược nào</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h3>🔥 10 phiên gần nhất <span class="badge" id="recent10Badge">0/10</span></h3>
      <div class="recent-10" id="recent10"></div>
    </div>

    <div class="card">
      <h3>📜 Lịch sử 50 phiên (toàn hệ thống) <span class="badge" id="histBadge">0</span></h3>
      <div class="history-grid" id="historyGrid"><span class="hist-empty">Chưa có dữ liệu</span></div>
    </div>

    <div class="card">
      <h3>🧠 Top Core AI dẫn đầu</h3>
      <div class="history-grid" id="coresGrid"><span class="hist-empty">Đang tính...</span></div>
    </div>

    <div class="card">
      <h3>📡 Sự kiện của bạn</h3>
      <div class="event-list" id="eventList">Đang chờ sự kiện...</div>
    </div>
  </main>

  <footer class="footer">© 2025 LC79 — <b>HuyDaiXuVN</b> · Auto Bet + Risk Management</footer>
</div>

<script>
const $ = id => document.getElementById(id);
const API = { login:'/api/login', logout:'/api/logout', state:'/api/state', settings:'/api/settings' };
let loadingHidden = false;
let settingsLoaded = false;
let lastBalance = null;
let profitChart = null, winChart = null;
let isDashboardActive = false;

function fmt(n){ return new Intl.NumberFormat('vi-VN').format(Number(n)||0); }
function esc(s){ return String(s).replace(/[&<>"']/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }
function hideLoading(){ if(loadingHidden)return; loadingHidden=true; const el=$('loadingOverlay'); el.classList.add('hidden'); setTimeout(()=>el.remove(),400); }
function timeStr(ts){ const d = new Date(ts*1000); return d.toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}); }

$('togglePass').addEventListener('click', () => {
  const p = $('password');
  p.type = p.type === 'password' ? 'text' : 'password';
});

function showLogin(){
  $('loginView').style.display = 'flex';
  $('dashboardView').style.display = 'none';
}
function showDashboard(){
  $('loginView').style.display = 'none';
  $('dashboardView').style.display = 'flex';
}

function initCharts(){
  if (profitChart) return;
  const pCtx = $('profitChart').getContext('2d');
  const grad = pCtx.createLinearGradient(0,0,0,220);
  grad.addColorStop(0,'rgba(16,185,129,0.28)');
  grad.addColorStop(1,'rgba(16,185,129,0.02)');
  profitChart = new Chart(pCtx, {
    type: 'line',
    data: { labels: [], datasets: [{
      label: 'Lãi/Lỗ tích lũy', data: [], borderColor: '#10b981',
      backgroundColor: grad, borderWidth: 2.5, fill: true, tension: 0.35,
      pointRadius: 0, pointHoverRadius: 5,
      pointHoverBackgroundColor: '#10b981', pointHoverBorderColor: '#fff', pointHoverBorderWidth: 2,
    }]},
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(13,17,23,0.95)', padding: 10,
          titleFont: { family: 'Space Grotesk', size: 12, weight: '700' },
          bodyFont: { family: 'Plus Jakarta Sans', size: 12 },
          callbacks: {
            title: (items) => `Ván #${items[0].label}`,
            label: (ctx) => { const v = ctx.parsed.y; return `${v>=0?'+':''}${fmt(v)} đ`; }
          }
        }
      },
      scales: {
        x: { display: false },
        y: {
          ticks: { color: '#9ca3af', font: { size: 10, family: 'Plus Jakarta Sans' },
            callback: v => Math.abs(v)>=1e6?(v/1e6).toFixed(1)+'M':(Math.abs(v)>=1e3?(v/1e3).toFixed(0)+'k':v) },
          grid: { color: 'rgba(15,23,42,0.05)', drawTicks: false },
          border: { display: false }
        }
      }
    }
  });
  const wCtx = $('winChart').getContext('2d');
  winChart = new Chart(wCtx, {
    type: 'doughnut',
    data: { labels: ['Thắng','Thua'], datasets: [{ data: [0,0],
      backgroundColor: ['#10b981', '#ef4444'], borderColor: '#fff', borderWidth: 3, hoverOffset: 8 }]},
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '70%',
      plugins: {
        legend: { position: 'bottom', labels: { color: '#374151',
          font: { size: 12, family: 'Plus Jakarta Sans', weight: '600' },
          padding: 14, usePointStyle: true, pointStyle: 'circle', boxWidth: 9 }},
        tooltip: { backgroundColor: 'rgba(13,17,23,0.95)', padding: 10,
          titleFont: { family: 'Space Grotesk', size: 12, weight: '700' },
          bodyFont: { family: 'Plus Jakarta Sans', size: 12 },
          callbacks: { label: (ctx) => {
            const total = ctx.dataset.data.reduce((a,b)=>a+b,0);
            const pct = total ? ((ctx.parsed / total)*100).toFixed(1) : 0;
            return ` ${ctx.label}: ${ctx.parsed} ván (${pct}%)`;
          }}
        }
      }
    }
  });
}

function updateProfitChart(curve){
  if (!profitChart) return;
  const empty = $('profitEmpty');
  if (!curve || curve.length === 0){ empty.style.display = 'grid'; return; }
  empty.style.display = 'none';
  profitChart.data.labels = curve.map((_,i) => i+1);
  profitChart.data.datasets[0].data = curve;
  const last = curve[curve.length - 1];
  if (last >= 0){
    profitChart.data.datasets[0].borderColor = '#10b981';
    const g = profitChart.ctx.createLinearGradient(0,0,0,220);
    g.addColorStop(0,'rgba(16,185,129,0.28)'); g.addColorStop(1,'rgba(16,185,129,0.02)');
    profitChart.data.datasets[0].backgroundColor = g;
  } else {
    profitChart.data.datasets[0].borderColor = '#ef4444';
    const g = profitChart.ctx.createLinearGradient(0,0,0,220);
    g.addColorStop(0,'rgba(239,68,68,0.28)'); g.addColorStop(1,'rgba(239,68,68,0.02)');
    profitChart.data.datasets[0].backgroundColor = g;
  }
  profitChart.update('none');
}
function updateWinChart(wins, losses){
  if (!winChart) return;
  const empty = $('winEmpty');
  if (!wins && !losses){ empty.style.display = 'grid'; return; }
  empty.style.display = 'none';
  winChart.data.datasets[0].data = [wins, losses];
  winChart.update('none');
}

async function refresh(){
  try {
    const r = await fetch(API.state, { credentials: 'same-origin' });
    const s = await r.json();
    hideLoading();
    if (!s.logged_in){ showLogin(); return; }
    showDashboard();
    if (!isDashboardActive){ initCharts(); isDashboardActive = true; }
    render(s);
    if (!settingsLoaded && s.base_bet){
      $('baseBetInput').value = s.base_bet;
      $('maxLossesInput').value = s.max_losses;
      settingsLoaded = true;
    }
  } catch(e){
    hideLoading();
    if ($('wsLabel')) $('wsLabel').textContent = 'Mất kết nối';
  }
}

function render(s){
  const dot = $('wsDot'), lbl = $('wsLabel');
  if (s.ws_connected){ dot.className='status-dot live'; lbl.textContent='Live'; }
  else if (s.logged_in){ dot.className='status-dot off'; lbl.textContent='Reconnect...'; }
  else { dot.className='status-dot'; lbl.textContent = s.ws_error?'Lỗi':'Khởi động...'; }

  if (s.nickname){
    $('welcomeName').textContent = s.nickname;
    $('welcomeAvatar').textContent = s.nickname[0].toUpperCase();
    $('userChipName').textContent = s.nickname;
    $('userAvatar').textContent = s.nickname[0].toUpperCase();
  }
  const hist = s.history || [];
  $('statBadge').textContent = hist.length >= 10 ? '★ AI READY' : `THU THẬP ${hist.length}/10`;

  $('sessId').textContent = s.current_session ? '#'+s.current_session : '#—';
  const tag = $('sessTag');
  const cs = (s.current_state || '').toUpperCase();
  tag.textContent = cs || 'WAITING';
  tag.className = 'session-tag ' + (cs==='BETTING'?'betting':'');

  const pv = $('predVal'), ps = $('predSub');
  const p = s.current_prediction;
  const conf = s.current_confidence || 0;
  if (p === 'TAI'){ pv.textContent='🔵 TÀI'; pv.className='pred-big tai'; ps.textContent=`Confidence: ${(conf*100).toFixed(1)}%`; }
  else if (p === 'XIU'){ pv.textContent='🔴 XỈU'; pv.className='pred-big xiu'; ps.textContent=`Confidence: ${(conf*100).toFixed(1)}%`; }
  else { pv.textContent = hist.length < 10 ? `Chờ (${hist.length}/10)` : 'Chưa có dự đoán'; pv.className='pred-big empty'; ps.textContent='Đang tích lũy...'; }

  const rv = $('resultVal'), rd = $('resultDices'), rm = $('resultMark');
  const r = s.current_result;
  if (r && r.result){
    rv.textContent = r.result === 'TAI' ? '🔵 TÀI' : '🔴 XỈU';
    rv.className = 'result-big ' + (r.result==='TAI'?'tai':'xiu');
    rd.textContent = (r.dices||[]).join(' · ') || '—';
    if (r.ok === true){ rm.textContent='✓ AI đoán đúng'; rm.className='result-mark ok'; }
    else if (r.ok === false){ rm.textContent='✗ AI đoán sai'; rm.className='result-mark fail'; }
    else { rm.textContent='—'; rm.className='result-mark none'; }
  } else {
    rv.textContent='—'; rv.className='result-big empty';
    rd.textContent='— · — · —'; rm.textContent='—'; rm.className='result-mark none';
  }

  const balEl = $('balanceVal');
  const newBal = s.balance;
  balEl.textContent = fmt(newBal);
  if (lastBalance !== null && lastBalance !== newBal){
    balEl.classList.remove('flash'); void balEl.offsetWidth; balEl.classList.add('flash');
  }
  lastBalance = newBal;

  const pl = s.total_profit || 0;
  const plEl = $('plVal'), plCard = $('plCard');
  plEl.textContent = (pl>=0?'+':'') + fmt(pl) + 'đ';
  plEl.className = 'stat-value ' + (pl>0?'pos':(pl<0?'neg':''));
  plCard.className = 'stat-card pl' + (pl<0?' neg':'');
  $('plIcon').textContent = pl > 0 ? '📈' : (pl < 0 ? '📉' : '📊');
  $('plHint').textContent = (s.total_wins||0) + ' thắng / ' + (s.total_losses||0) + ' thua';

  $('wrVal').textContent = (s.win_rate || 0) + '%';
  $('wrVal').className = 'stat-value ' + (s.win_rate >= 50 ? 'pos' : (s.total_wins+s.total_losses > 0 ? 'neg' : ''));
  $('wrHint').textContent = `AI acc: ${s.ai_accuracy||0}%`;

  $('wageredVal').textContent = fmt(s.total_wagered || 0);
  $('streakHint').textContent = `Best: ${s.best_streak||0} · Worst: ${s.worst_streak||0}`;

  updateProfitChart(s.profit_curve || []);
  updateWinChart(s.total_wins || 0, s.total_losses || 0);

  const bh = s.bet_history || [];
  $('betCountBadge').textContent = bh.length + ' ván';
  const tbody = $('betTableBody');
  if (bh.length === 0){
    tbody.innerHTML = '<tr><td colspan="7" class="table-empty">Chưa có ván cược nào</td></tr>';
  } else {
    tbody.innerHTML = bh.slice().reverse().map(b => {
      const predBadge = `<span class="badge-mini ${b.pred==='TAI'?'tai':'xiu'}">${b.pred}</span>`;
      const resBadge = `<span class="badge-mini ${b.result==='TAI'?'tai':'xiu'}">${b.result}</span>`;
      const winBadge = b.won ? '<span class="badge-mini win">✓</span>' : '<span class="badge-mini loss">✗</span>';
      const plClass = b.profit >= 0 ? 'pos' : 'neg';
      return `<tr>
        <td>#${esc(b.sid||'—')}</td>
        <td>${predBadge} ${winBadge}</td>
        <td>${resBadge}</td>
        <td class="num-cell">${fmt(b.amount)}</td>
        <td class="pl-cell ${plClass}">${(b.profit>=0?'+':'')+fmt(b.profit)}</td>
        <td class="num-cell">${fmt(b.balance_after)}</td>
        <td style="text-align:right;color:#6b7280;font-size:11px">${timeStr(b.ts)}</td>
      </tr>`;
    }).join('');
  }

  const st = $('autoStatus'), btn = $('btnToggleAuto');
  if (!s.auto_bet){
    btn.textContent = '⚡ Bật Auto Cược'; btn.className = 'btn-auto off';
    st.className = 'auto-status';
    st.textContent = 'Auto: TẮT · nhập tiền cược rồi bật để bắt đầu';
  } else if (s.auto_paused){
    btn.textContent = '⏸ Đang nghỉ (chờ thắng)'; btn.className = 'btn-auto paused';
    st.className = 'auto-status paused';
    st.textContent = `⏸ TẠM NGHỈ · thua ${s.consecutive_losses} tay · paper ${s.paper_wins}/${s.paper_bets} · tự bật lại khi AI đúng`;
  } else {
    btn.textContent = '🛑 Tắt Auto Cược'; btn.className = 'btn-auto on';
    st.className = 'auto-status active';
    st.textContent = `✅ ĐANG AUTO · ${fmt(s.base_bet)}đ/ván · thua ${s.consecutive_losses}/${s.max_losses} tay → nghỉ`;
  }

  const last10 = hist.slice(-10).reverse();
  let r10 = '';
  for (let i=0;i<10;i++){
    const v = last10[i];
    if (v==='TAI') r10 += `<div class="hist-big tai">T</div>`;
    else if (v==='XIU') r10 += `<div class="hist-big xiu">X</div>`;
    else r10 += `<div class="hist-big empty">?</div>`;
  }
  $('recent10').innerHTML = r10;
  $('recent10Badge').textContent = `${hist.length}/10`;

  const hg = $('historyGrid');
  if (hist.length) hg.innerHTML = hist.slice(-50).map(v => `<span class="hist-chip ${v==='TAI'?'tai':'xiu'}">${v==='TAI'?'T':'X'}</span>`).join('');
  else hg.innerHTML = '<span class="hist-empty">Chưa có dữ liệu</span>';
  $('histBadge').textContent = hist.length;

  const cg = $('coresGrid');
  if (s.ai_weights_top && s.ai_weights_top.length){
    cg.innerHTML = s.ai_weights_top.map(([k,v]) => `<span class="hist-chip core">${esc(k)} · ${v.toFixed(2)}</span>`).join('');
  }

  const el = $('eventList');
  const ev = s.events || [];
  if (ev.length){
    el.innerHTML = ev.map(l => `<div><span class="t">[${timeStr(l.t)}]</span> ${esc(l.msg)}</div>`).join('');
    el.scrollTop = el.scrollHeight;
  } else {
    el.textContent = 'Chưa có sự kiện';
  }
}

$('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('alertBox').classList.remove('show');
  const username = $('username').value.trim();
  const password = $('password').value;
  if (!username || !password){
    $('alertText').textContent = 'Nhập đủ tài khoản & mật khẩu';
    $('alertBox').classList.add('show'); return;
  }
  const btn = $('btnLogin');
  btn.classList.add('loading'); btn.disabled = true;
  try {
    const md5 = CryptoJS.MD5(password).toString();
    const r = await fetch(API.login, {
      method:'POST', credentials:'same-origin',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ username, password: md5 })
    });
    const d = await r.json();
    if (d.success){
      $('password').value = '';
      settingsLoaded = false;
      await refresh();
    } else {
      $('alertText').textContent = d.message || 'Đăng nhập thất bại';
      $('alertBox').classList.add('show');
    }
  } catch(err){
    $('alertText').textContent = 'Lỗi kết nối server';
    $('alertBox').classList.add('show');
  } finally {
    btn.classList.remove('loading'); btn.disabled = false;
  }
});

$('btnLogout').addEventListener('click', async () => {
  if (!confirm('Đăng xuất và ngắt kết nối WebSocket?')) return;
  try {
    await fetch(API.logout, { method:'POST', credentials:'same-origin' });
  } catch(e){}
  settingsLoaded = false;
  lastBalance = null;
  isDashboardActive = false;
  if (profitChart){ profitChart.destroy(); profitChart = null; }
  if (winChart){ winChart.destroy(); winChart = null; }
  showLogin();
});

$('btnSaveSettings').addEventListener('click', async () => {
  const base_bet = parseInt($('baseBetInput').value) || 10000;
  const max_losses = parseInt($('maxLossesInput').value) || 3;
  if (base_bet < 1000){ alert('Tiền cược tối thiểu 1.000đ'); return; }
  const btn = $('btnSaveSettings');
  try {
    const r = await fetch(API.settings, {
      method:'POST', credentials:'same-origin',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ base_bet, max_losses })
    });
    const d = await r.json();
    if (d.success){
      btn.textContent = '✅ Đã lưu';
      btn.classList.add('saved');
      setTimeout(() => {
        btn.textContent = '💾 Lưu cài đặt';
        btn.classList.remove('saved');
      }, 1800);
      refresh();
    } else {
      alert('Lỗi lưu: ' + (d.message || 'unknown'));
    }
  } catch(e){ alert('Lỗi kết nối server'); }
});

$('btnToggleAuto').addEventListener('click', async () => {
  const base_bet = parseInt($('baseBetInput').value) || 10000;
  const max_losses = parseInt($('maxLossesInput').value) || 3;
  if (base_bet < 1000){ alert('Tiền cược tối thiểu 1.000đ'); return; }
  try {
    const st = await (await fetch(API.state, { credentials:'same-origin' })).json();
    const newAuto = !st.auto_bet;
    await fetch(API.settings, {
      method:'POST', credentials:'same-origin',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ base_bet, max_losses, auto_bet: newAuto })
    });
    refresh();
  } catch(e){ alert('Lỗi toggle auto'); }
});

async function boot(){
  await refresh();
  setInterval(refresh, 1500);
}
boot();
</script>
</body>
</html>
"""


# ==========================================================
# KHỞI ĐỘNG
# ==========================================================
ensure_bg()

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 LC79 · Multi-User Auto Bet Dashboard")
    print(f"   BG Collector: {COLLECTOR_USER} (feed AI 24/7)")
    print(f"   WebSocket: {WS_URL}/{WS_PATH}")
    print(f"   User cần đăng nhập acc của mình để vào dashboard")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
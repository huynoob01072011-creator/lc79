"""
🤖 AI TÀI XỈU ULTRA V4 — 35 CORES + REGIME DETECTION + CONFIDENCE SCORING
Chạy: python app.py  →  http://localhost:5000  (admin / admin123)
"""

import os, json, hashlib, base64, logging, threading, time, random, math, itertools
from functools import wraps

import requests
import socketio as sio_client
from flask import Flask, request, jsonify, session, redirect, render_template_string
from flask_socketio import SocketIO, emit, join_room

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'CHANGE-ME-PROD-SECRET-KEY-123')
web_socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ==========================================
# CONFIG
# ==========================================
DATA_COLLECTOR_USER = "HuyDaiXuLc79"
DATA_COLLECTOR_PASS = "GiaHuy2011@"
USERS_FILE = "users.json"

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f: return json.load(f)
        except Exception: pass
    default = {"admin": {"password": hash_pw("admin123"), "is_admin": True, "is_vip": True}}
    with open(USERS_FILE, 'w') as f: json.dump(default, f, indent=2)
    return default

def save_users(u):
    with open(USERS_FILE, 'w') as f: json.dump(u, f, indent=2)

USERS = load_users()
active_sockets = {}
user_states = {}

# ==========================================
# GLOBAL DATA & 35 AI CORES
# ==========================================
GLOBAL_HISTORY = []
MAX_GLOBAL_HISTORY = 2000
GLOBAL_STATS = {"total": 0, "correct": 0}

GLOBAL_AI_WEIGHTS = {
    "trend": 1.0, "pattern": 1.0, "frequency": 1.0, "momentum": 1.0, "symmetry": 1.0,
    "alternating": 1.0, "fibonacci": 1.0, "chaos": 1.0, "shadow": 1.0,
    "markov1": 1.0, "markov2": 1.0, "markov3": 1.0,
    "rsi_indicator": 1.0, "macd_cross": 1.0, "pivot_reversal": 1.0, "cluster_3": 1.0,
    "parity": 1.0, "golden_ratio": 1.0, "quantum": 1.0,
    "anti_bait": 2.0, "smart_breaker": 2.0,
    "ngram_4": 1.5, "ngram_5": 1.5, "elliott_wave": 1.5, "contrarian": 2.0,
    "bollinger_bands": 1.5, "mean_reversion": 1.0, "mirror_reflection": 1.0,
    "martingale_trap": 1.5, "poisson_prob": 1.0, "harmonic_cycle": 1.0,
    "breakout_hunter": 1.5, "volume_fakeout": 1.5, "time_decay": 1.0,
    "neural_bias": 1.0, "twin_peaks": 1.0
}
GLOBAL_MODEL_STREAK = {k: 0 for k in GLOBAL_AI_WEIGHTS.keys()}

def init_user_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {
            "profit_loss": 0, "auto_bet_enabled": False, "x2_mode": False,
            "win_streak": 0, "base_bet_amount": 10000, "current_bet": 10000,
            "target_profit": None, "current_prediction": None, "current_confidence": 0,
            "current_top_models": [], "waiting_for_result": False,
            "has_bet_this_session": False, "session_id": None, "balance": 0,
            "last_predictions": {}, "min_confidence": 50,
            "pred_total": 0, "pred_correct": 0,
            "history_tail": []  # last 50 results for chart
        }

def send_msg(user_id, text):
    web_socketio.emit('bot_message', {'text': text, 'ts': time.time()}, room=f"user_{user_id}")

def send_state(user_id):
    """Push live state to client"""
    if user_id not in user_states: return
    s = user_states[user_id]
    web_socketio.emit('state_update', {
        "prediction": s["current_prediction"], "confidence": s["current_confidence"],
        "top_models": s["current_top_models"], "balance": s["balance"],
        "profit_loss": s["profit_loss"], "win_streak": s["win_streak"],
        "session_id": s["session_id"], "auto_bet": s["auto_bet_enabled"],
        "x2_mode": s["x2_mode"], "pred_total": s["pred_total"], "pred_correct": s["pred_correct"],
        "history_tail": s["history_tail"][-50:],
    }, room=f"user_{user_id}")

# ==========================================
# REGIME DETECTION
# ==========================================
def detect_regime(recent_str):
    """Phân loại chế độ thị trường hiện tại."""
    if len(recent_str) < 20: return "unknown"
    recent = recent_str[-20:]
    # Longest streak
    max_streak = max(len(list(g)) for _, g in itertools.groupby(recent))
    # Alternation ratio
    alt_count = sum(1 for i in range(len(recent) - 1) if recent[i] != recent[i+1])
    alt_ratio = alt_count / (len(recent) - 1)
    if max_streak >= 6: return "streak"
    if alt_ratio >= 0.75: return "alternating"
    if max_streak >= 4: return "short_streak"
    return "chaos"

REGIME_BOOST = {
    "streak":       {"anti_bait": 1.6, "smart_breaker": 1.6, "breakout_hunter": 1.4,
                     "martingale_trap": 1.4, "contrarian": 1.3, "bollinger_bands": 1.3},
    "alternating":  {"alternating": 2.2, "symmetry": 1.6, "parity": 1.6, "pattern": 1.4,
                     "mirror_reflection": 1.3},
    "short_streak": {"elliott_wave": 1.5, "twin_peaks": 1.4, "cluster_3": 1.3,
                     "harmonic_cycle": 1.3, "pivot_reversal": 1.2},
    "chaos":        {"ngram_4": 1.7, "ngram_5": 1.7, "quantum": 1.4, "chaos": 1.4,
                     "time_decay": 1.3, "frequency": 1.2},
}

# ==========================================
# ENHANCED AI PREDICTION — Returns (pred, confidence, top_models)
# ==========================================
def make_prediction_vip(user_id):
    state = user_states[user_id]
    history = GLOBAL_HISTORY
    weights = GLOBAL_AI_WEIGHTS
    n = len(history)
    if n < 10:
        return None, 0, []

    last_item = history[-1]
    opp_item = "XIU" if last_item == "TAI" else "TAI"
    recent_str = "".join(["T" if x == "TAI" else "X" for x in history])
    streak = len(recent_str) - len(recent_str.rstrip(recent_str[-1]))
    regime = detect_regime(recent_str)
    boost = REGIME_BOOST.get(regime, {})
    preds = {}

    # ---- CORE 1-9: Basic pattern analysis ----
    preds["trend"] = last_item if history[-5:].count(last_item) >= 3 else opp_item
    preds["pattern"] = opp_item if recent_str.endswith(("TXTX", "TTXX")) else last_item
    t1 = {"TAI": {"TAI": 0, "XIU": 0}, "XIU": {"TAI": 0, "XIU": 0}}
    for i in range(n - 1): t1[history[i]][history[i+1]] += 1
    preds["markov1"] = "TAI" if t1[last_item]["TAI"] > t1[last_item]["XIU"] else "XIU"
    preds["markov2"] = "TAI" if history[-2:] == ["TAI", "TAI"] else "XIU"
    preds["markov3"] = opp_item if history[-3:] == [last_item]*3 else preds["markov2"]
    preds["frequency"] = "XIU" if history[-20:].count("TAI") > 10 else "TAI"
    preds["momentum"] = "TAI" if sum((i+1) * (1 if r == "TAI" else -1) for i, r in enumerate(history[-5:])) > 0 else "XIU"
    preds["symmetry"] = opp_item if len(recent_str) >= 6 and recent_str[-6:-3] == recent_str[-3:][::-1] else last_item
    preds["alternating"] = opp_item

    # ---- CORE 10-20: Advanced patterns ----
    preds["fibonacci"] = opp_item if streak in [3, 5, 8, 13] else last_item
    preds["chaos"] = opp_item if sum(1 for i in range(9) if recent_str[-10:][i] != recent_str[-10:][i+1]) >= 7 else last_item
    preds["shadow"] = "TAI" if history[-50:].count("TAI") < 25 else "XIU"
    rsi = recent_str[-10:].count("T")
    preds["rsi_indicator"] = "XIU" if rsi >= 7 else ("TAI" if rsi <= 3 else last_item)
    preds["macd_cross"] = "TAI" if recent_str[-3:].count("T") > (recent_str[-9:].count("T") / 3) else "XIU"
    preds["pivot_reversal"] = history[-1] if history[-3] == history[-2] and history[-2] != history[-1] else last_item
    preds["cluster_3"] = "TAI" if recent_str[-3:] in ("TTT", "TXX", "XTX", "XXT") else "XIU"
    preds["parity"] = opp_item if streak % 2 == 0 else last_item
    preds["golden_ratio"] = "TAI" if (history[-30:].count("TAI") / 30) < 0.618 else "XIU"
    preds["quantum"] = random.choice(["TAI", "XIU"])
    preds["anti_bait"] = opp_item if streak >= 5 or recent_str.endswith("TXTXT") else last_item

    max_s = 1; cur = 1
    for i in range(1, n):
        if history[i] == history[i-1]: cur += 1
        else: max_s = max(max_s, cur); cur = 1
    preds["smart_breaker"] = opp_item if streak >= max_s - 1 and streak >= 3 else last_item

    # ---- CORE 21-35: Advanced super cores ----
    l4 = recent_str[-4:]
    t4, x4 = recent_str[:-1].count(l4 + "T"), recent_str[:-1].count(l4 + "X")
    preds["ngram_4"] = "TAI" if t4 > x4 else ("XIU" if x4 > t4 else opp_item)
    l5 = recent_str[-5:]
    t5, x5 = recent_str[:-1].count(l5 + "T"), recent_str[:-1].count(l5 + "X")
    preds["ngram_5"] = "TAI" if t5 > x5 else ("XIU" if x5 > t5 else opp_item)

    if recent_str.endswith("TXTXT"): preds["elliott_wave"] = last_item
    elif recent_str.endswith("TTXXTT"): preds["elliott_wave"] = "XIU"
    else: preds["elliott_wave"] = opp_item

    if streak in (4, 6): preds["contrarian"] = opp_item
    elif recent_str[-6:] == "TXTXTX": preds["contrarian"] = "XIU"
    else: preds["contrarian"] = last_item

    ma10 = recent_str[-10:].count("T") / 10.0
    preds["bollinger_bands"] = "XIU" if ma10 >= 0.8 else ("TAI" if ma10 <= 0.2 else last_item)
    t_total = history[-100:].count("TAI")
    preds["mean_reversion"] = "TAI" if t_total < (len(history[-100:]) * 0.45) else "XIU"
    preds["mirror_reflection"] = ("TAI" if recent_str[-8] == "T" else "XIU") if len(recent_str) >= 8 else opp_item
    preds["martingale_trap"] = opp_item if streak in (3, 7) else last_item
    preds["poisson_prob"] = "TAI" if (history[-5:].count("TAI") % 2 == 1) else "XIU"
    preds["harmonic_cycle"] = history[-4] if n >= 4 else opp_item
    preds["breakout_hunter"] = last_item if streak == 1 and history[-2] == history[-3] else opp_item
    preds["volume_fakeout"] = last_item if recent_str[-5:] in ("TTTXT", "XXXTX") else opp_item
    preds["time_decay"] = opp_item
    preds["neural_bias"] = "TAI" if history[-7:].count("TAI") > 3 else "XIU"
    preds["twin_peaks"] = opp_item if recent_str.endswith(("TTXTT", "XXTXX")) else last_item

    # ---- SCORING with regime boost ----
    scores = {"TAI": 0.0, "XIU": 0.0}
    weighted_models = {}
    for m, p in preds.items():
        w = weights[m] * boost.get(m, 1.0)
        scores[p] += w
        weighted_models[m] = w

    total = scores["TAI"] + scores["XIU"]
    if total == 0:
        return random.choice(["TAI", "XIU"]), 0, []

    tai_pct = scores["TAI"] / total * 100
    xiu_pct = scores["XIU"] / total * 100
    prediction = "TAI" if tai_pct > xiu_pct else "XIU"
    margin = abs(tai_pct - xiu_pct)

    # Agreement: % weight of models that agree with prediction
    agree_w = sum(w for m, p in preds.items() if p == prediction for w in [weighted_models[m]])
    agree_pct = (agree_w / total) * 100

    # Confidence: 60% margin + 40% agreement-above-random
    confidence = margin * 0.6 + (agree_pct - 50) * 0.8
    confidence = round(max(0, min(100, confidence)), 1)

    # Top contributing cores
    top = sorted(
        [(m, round(weighted_models[m], 2)) for m in preds if preds[m] == prediction],
        key=lambda x: x[1], reverse=True
    )[:4]

    state["last_predictions"] = preds
    return prediction, confidence, top


def update_global_ai_weights(actual_result, user_id=None):
    """Adaptive weights: faster learn on streak, slow decay on miss."""
    if not (user_id and user_id in user_states and "last_predictions" in user_states[user_id]):
        return
    preds = user_states[user_id]["last_predictions"]
    for model, pred in preds.items():
        if pred == actual_result:
            GLOBAL_MODEL_STREAK[model] += 1
            bonus = 0.3 + 0.15 * min(GLOBAL_MODEL_STREAK[model], 10)
            GLOBAL_AI_WEIGHTS[model] = min(25.0, GLOBAL_AI_WEIGHTS[model] + bonus)
        else:
            GLOBAL_MODEL_STREAK[model] = 0
            GLOBAL_AI_WEIGHTS[model] = max(0.1, GLOBAL_AI_WEIGHTS[model] * 0.9 - 0.5)

# ==========================================
# GAME API & SOCKET
# ==========================================
def md5_hash(t): return hashlib.md5(t.encode('utf-8')).hexdigest()

def login_and_get_token(username, password):
    pw_md5 = md5_hash(password)
    url = f"https://apifo88daigia.tele68.com/api?c=3&un={username}&pw={pw_md5}&cp=R&cl=R&pf=web&at="
    try:
        r = requests.get(url, timeout=12); r.raise_for_status(); data = r.json()
        if not data.get("success"): return {"_error": f"Lỗi Game: {str(data.get('message', 'Sai thông tin'))}"}
        sk = data["sessionKey"]; sk += "=" * ((4 - len(sk) % 4) % 4)
        sd = json.loads(base64.b64decode(sk).decode('utf-8'))
        nickname = sd.get("nickname") or sd.get("nickName")
        r2 = requests.post("https://wlb.tele68.com/v1/lobby/auth/login?cp=R&cl=R&pf=web&at=",
                           headers={"authority": "wlb.tele68.com", "content-type": "application/json"},
                           json={"nickName": nickname, "accessToken": data["accessToken"]}, timeout=12)
        lobby = r2.json(); token = lobby.get("token")
        if not token: return {"_error": "Lobby không trả về JWT token."}
        return {"token": token, "nickname": nickname,
                "money": lobby.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e:
        return {"_error": f"Lỗi kết nối: {e}"}

def start_websocket(user_id, token, is_background=False):
    if user_id in active_sockets and not is_background:
        try: active_sockets[user_id].disconnect()
        except: pass

    sio = sio_client.Client(reconnection=True, reconnection_attempts=10,
                            logger=False, engineio_logger=False)
    if not is_background:
        active_sockets[user_id] = sio
        init_user_state(user_id)

    @sio.event(namespace='/txmd5')
    def connect():
        if not is_background:
            send_msg(user_id, "🟢 <b>HỆ THỐNG V4 ONLINE</b>\n<i>35 lõi AI + Regime Detection đã kích hoạt</i>")

    @sio.on('new-session', namespace='/txmd5')
    def on_new_session(data):
        if is_background: return
        state = user_states[user_id]
        state["session_id"] = data.get('id', 'N/A')
        state["has_bet_this_session"] = False

        # Target hit check
        if state["auto_bet_enabled"] and state["target_profit"] is not None:
            if state["profit_loss"] >= state["target_profit"]:
                state["auto_bet_enabled"] = False
                send_msg(user_id, f"🏆 <b>ĐẠT TARGET — ĐÃ CHỐT LÃI</b>\n💰 Lãi: <code>{state['profit_loss']:,}</code>\n🔴 Auto tắt an toàn.")

        history_len = len(GLOBAL_HISTORY)
        pred, conf, top = make_prediction_vip(user_id) if history_len >= 10 else (None, 0, [])
        state["current_prediction"] = pred
        state["current_confidence"] = conf
        state["current_top_models"] = top

        if state["x2_mode"] and state["win_streak"] >= 1:
            state["current_bet"] = state["base_bet_amount"] * 2
        else:
            state["current_bet"] = state["base_bet_amount"]

        msg = f"🔔 <b>PHIÊN MỚI</b> · <code>#{state['session_id']}</code>\n"
        if pred:
            pe = "🔵 TÀI" if pred == "TAI" else "🔴 XỈU"
            stars = "⭐" * min(5, int(conf // 20) + 1)
            msg += f"🔥 <b>AI CHỐT: {pe}</b> · Độ tin: <b>{conf}%</b> {stars}\n"
            if top:
                msg += f"🧠 Top cores: <code>{', '.join(m for m,_ in top[:3])}</code>\n"
            if state["auto_bet_enabled"]:
                if conf >= state["min_confidence"]:
                    extra = " ⚡X2" if state["x2_mode"] and state["win_streak"] >= 1 else ""
                    msg += f"⏳ <i>Vào cược{extra}: <code>{state['current_bet']:,}</code></i>"
                else:
                    msg += f"⏸ <i>Bỏ qua (conf {conf}% &lt; {state['min_confidence']}%)</i>"
            else:
                msg += "⏸ <i>Auto đang tắt</i>"
        else:
            msg += f"⏳ <i>Đang thu thập: {history_len}/10...</i>"
        send_msg(user_id, msg)
        send_state(user_id)

    @sio.on('tick-update', namespace='/txmd5')
    def on_tick_update(data):
        if is_background: return
        state = user_states[user_id]
        if data.get('state') == 'BETTING' and state["auto_bet_enabled"] and state["current_prediction"]:
            if state["current_confidence"] < state["min_confidence"]:
                return
            if not state["has_bet_this_session"]:
                sio.emit('bet', {"type": state["current_prediction"], "amount": state["current_bet"]},
                         namespace='/txmd5')
                state["has_bet_this_session"] = True
                state["waiting_for_result"] = True
                send_msg(user_id, f"🚀 <b>VÀO TIỀN:</b> <code>{state['current_bet']:,}</code> · Conf {state['current_confidence']}%")

    @sio.on('bet-result', namespace='/txmd5')
    def on_bet_result(data):
        if is_background: return
        if "postBalance" in data: user_states[user_id]["balance"] = data["postBalance"]
        sio.emit('get-current-my-info', None, namespace='/txmd5')
        send_state(user_id)

    @sio.on('session-result', namespace='/txmd5')
    def on_session_result(data):
        result = data.get('resultTruyenThong', 'N/A')
        if result in ("TAI", "XIU"):
            GLOBAL_HISTORY.append(result)
            if len(GLOBAL_HISTORY) > MAX_GLOBAL_HISTORY: GLOBAL_HISTORY.pop(0)
            update_global_ai_weights(result, None if is_background else user_id)
            if is_background: return

            state = user_states[user_id]
            state["history_tail"].append(result)
            if len(state["history_tail"]) > 200: state["history_tail"].pop(0)

            dices = data.get('dices', [0, 0, 0])
            re = "🔵 TÀI" if result == "TAI" else "🔴 XỈU"

            # Track prediction accuracy
            if state["current_prediction"] == result:
                state["pred_total"] += 1
                state["pred_correct"] += 1
            elif state["current_prediction"]:
                state["pred_total"] += 1

            msg = f"🎲 <b>KẾT QUẢ: {re}</b> ({dices[0]}-{dices[1]}-{dices[2]})\n"

            if state["current_prediction"] and state["waiting_for_result"]:
                if state["current_prediction"] == result:
                    win = int(state["current_bet"] * 0.98)
                    state["profit_loss"] += win
                    state["win_streak"] += 1
                    msg += f"✅ <b>HÚP!</b> Lãi: <code>+{win:,}</code>\n"
                else:
                    state["profit_loss"] -= state["current_bet"]
                    state["win_streak"] = 0
                    msg += f"❌ <b>GÃY CẦU</b>\n"
                state["waiting_for_result"] = False

            acc = (state["pred_correct"] / state["pred_total"] * 100) if state["pred_total"] > 0 else 0
            msg += (f"📊 Lãi/Lỗ: <b>{state['profit_loss']:,}</b> · "
                    f"💳 Dư: <b>{state['balance']:,}</b>\n"
                    f"🎯 Accuracy: <b>{acc:.1f}%</b> ({state['pred_correct']}/{state['pred_total']})")
            send_msg(user_id, msg)
            send_state(user_id)
        elif not is_background:
            send_state(user_id)

    try:
        sio.connect('https://wtxmd52.tele68.com', socketio_path='txmd5/',
                    namespaces=['/txmd5'], transports=['websocket'],
                    auth={"token": token}, headers={"User-Agent": "Mozilla/5.0"})
        sio.wait()
    except Exception as e:
        if not is_background: send_msg(user_id, f"⚠️ Lỗi kết nối: <code>{e}</code>")

def background_data_collector():
    if DATA_COLLECTOR_USER != "acc_clone_soi_cau":
        logger.info("Khởi động AI soi cầu ngầm...")
        while True:
            try:
                res = login_and_get_token(DATA_COLLECTOR_USER, DATA_COLLECTOR_PASS)
                if "token" in res:
                    logger.info("Đã kết nối. Train 35 lõi AI...")
                    start_websocket("BG", res["token"], is_background=True)
            except Exception: pass
            time.sleep(30)

# ==========================================
# AUTH
# ==========================================
def require_login(f):
    @wraps(f)
    def w(*a, **kw):
        if 'user' not in session: return jsonify({"error": "Chưa đăng nhập"}), 401
        return f(*a, **kw)
    return w

def require_vip(f):
    @wraps(f)
    def w(*a, **kw):
        u = session.get('user')
        if not u: return jsonify({"error": "Chưa đăng nhập"}), 401
        if not USERS.get(u, {}).get('is_vip'): return jsonify({"error": "Không có VIP"}), 403
        return f(*a, **kw)
    return w

# ==========================================
# EMBEDDED HTML
# ==========================================
LOGIN_HTML = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Tài Xỉu V4 — Đăng nhập</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:radial-gradient(circle at 20% 20%,#1e3a8a,#0f172a 60%);
  min-height:100vh;display:flex;align-items:center;justify-content:center;color:#e2e8f0;overflow:hidden}
body:before{content:'';position:fixed;width:500px;height:500px;background:radial-gradient(circle,#0ea5e9 0%,transparent 70%);
  filter:blur(80px);opacity:.3;top:-100px;right:-100px;animation:float 20s infinite}
body:after{content:'';position:fixed;width:400px;height:400px;background:radial-gradient(circle,#6366f1 0%,transparent 70%);
  filter:blur(80px);opacity:.25;bottom:-100px;left:-100px;animation:float 25s infinite reverse}
@keyframes float{50%{transform:translate(80px,40px)}}
.card{position:relative;z-index:1;width:380px;max-width:92vw;padding:40px 32px;
  background:rgba(30,41,59,.75);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  border-radius:20px;border:1px solid rgba(148,163,184,.15);
  box-shadow:0 20px 60px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.05)}
.logo{text-align:center;font-size:44px;margin-bottom:8px;filter:drop-shadow(0 0 20px #0ea5e9)}
h1{text-align:center;font-size:19px;color:#38bdf8;margin-bottom:6px;font-weight:700}
.sub{text-align:center;font-size:11px;color:#64748b;margin-bottom:28px;letter-spacing:1px;text-transform:uppercase}
.field{margin-bottom:14px}
label{display:block;font-size:11px;color:#94a3b8;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
input{width:100%;padding:13px 16px;border-radius:10px;border:1px solid rgba(148,163,184,.2);
  background:rgba(15,23,42,.7);color:#e2e8f0;font-size:14px;outline:none;transition:.2s}
input:focus{border-color:#0ea5e9;box-shadow:0 0 0 3px rgba(14,165,233,.15)}
button{width:100%;padding:14px;border:none;border-radius:10px;font-weight:700;font-size:15px;
  background:linear-gradient(135deg,#0ea5e9,#6366f1);color:#fff;cursor:pointer;
  transition:.2s;letter-spacing:.5px;box-shadow:0 8px 24px rgba(14,165,233,.35)}
button:hover{transform:translateY(-2px);box-shadow:0 12px 32px rgba(14,165,233,.45)}
button:active{transform:translateY(0)}
.err{color:#f87171;text-align:center;margin-top:12px;font-size:13px;min-height:20px}
.hint{text-align:center;font-size:11px;color:#64748b;margin-top:20px}
</style></head>
<body>
<div class="card">
  <div class="logo">🤖</div>
  <h1>AI TÀI XỈU ULTRA V4</h1>
  <div class="sub">35 Cores · Regime Detection</div>
  <div class="field"><label>Tên đăng nhập</label>
    <input id="username" autocomplete="username" placeholder="admin"></div>
  <div class="field"><label>Mật khẩu</label>
    <input id="password" type="password" autocomplete="current-password" placeholder="••••••"></div>
  <button onclick="doLogin()">ĐĂNG NHẬP</button>
  <div class="err" id="err"></div>
  <div class="hint">Mặc định: admin / admin123</div>
</div>
<script>
async function doLogin() {
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  const err = document.getElementById('err'); err.textContent = '';
  try {
    const r = await fetch('/api/login', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({username,password})});
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Lỗi');
    window.location.href = '/';
  } catch (e) { err.textContent = '❌ ' + e.message; }
}
document.getElementById('password').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
</script>
</body></html>"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Tài Xỉu V4</title>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0a0f1e;--panel:#111827;--panel2:#1a2332;--border:#1f2937;
  --text:#e2e8f0;--muted:#64748b;--accent:#0ea5e9;--accent2:#6366f1;
  --green:#22c55e;--red:#ef4444;--gold:#f59e0b;--tai:#0ea5e9;--xiu:#ef4444;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden}
body::before{content:'';position:fixed;top:-30%;left:-10%;width:600px;height:600px;
  background:radial-gradient(circle,rgba(14,165,233,.15),transparent 70%);
  filter:blur(80px);pointer-events:none;z-index:0}
body::after{content:'';position:fixed;bottom:-30%;right:-10%;width:500px;height:500px;
  background:radial-gradient(circle,rgba(99,102,241,.12),transparent 70%);
  filter:blur(80px);pointer-events:none;z-index:0}

.topbar{position:sticky;top:0;z-index:10;display:flex;justify-content:space-between;
  align-items:center;padding:14px 24px;background:rgba(17,24,39,.85);backdrop-filter:blur(20px);
  border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:15px;color:#fff}
.brand-logo{font-size:22px;filter:drop-shadow(0 0 8px var(--accent))}
.brand-sub{font-size:10px;color:var(--muted);font-weight:400;letter-spacing:1px;text-transform:uppercase}
.top-right{display:flex;align-items:center;gap:12px;font-size:13px}
.badge{padding:4px 10px;border-radius:6px;font-size:10px;font-weight:800;letter-spacing:.5px}
.badge.vip{background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#fff}
.badge.admin{background:linear-gradient(135deg,#f59e0b,#d97706);color:#fff}
.btn-logout{background:rgba(239,68,68,.15);color:#fca5a5;border:1px solid rgba(239,68,68,.3);
  padding:7px 14px;border-radius:8px;cursor:pointer;font-size:12px;font-weight:600;transition:.2s}
.btn-logout:hover{background:rgba(239,68,68,.25)}

.layout{position:relative;z-index:1;display:grid;grid-template-columns:420px 1fr 380px;
  gap:16px;padding:16px;min-height:calc(100vh - 60px);max-width:1800px;margin:0 auto}
@media(max-width:1400px){.layout{grid-template-columns:400px 1fr}}
@media(max-width:1024px){.layout{grid-template-columns:1fr;padding:12px}}
@media(max-width:768px){.topbar{flex-direction:column;gap:10px;padding:12px}}

.panel{background:rgba(17,24,39,.7);backdrop-filter:blur(20px);
  border:1px solid var(--border);border-radius:16px;padding:18px;overflow:hidden;
  display:flex;flex-direction:column}
.panel-title{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);
  margin-bottom:14px;font-weight:700;display:flex;align-items:center;gap:8px}

/* ============ HERO PREDICTION ============ */
.hero{position:relative;background:linear-gradient(135deg,rgba(14,165,233,.1),rgba(99,102,241,.1));
  border:1px solid rgba(14,165,233,.25);border-radius:16px;padding:24px;text-align:center;
  margin-bottom:16px;overflow:hidden;transition:.4s}
.hero.tai{border-color:rgba(14,165,233,.4);box-shadow:0 0 40px rgba(14,165,233,.15)}
.hero.xiu{border-color:rgba(239,68,68,.4);box-shadow:0 0 40px rgba(239,68,68,.15)}
.hero.none{border-color:rgba(100,116,139,.25)}
.hero::before{content:'';position:absolute;inset:0;
  background:linear-gradient(45deg,transparent 30%,rgba(255,255,255,.03) 50%,transparent 70%);
  animation:shimmer 3s infinite}
@keyframes shimmer{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
.hero-label{font-size:10px;text-transform:uppercase;letter-spacing:2px;color:var(--muted);margin-bottom:12px}
.hero-pred{font-size:48px;font-weight:900;letter-spacing:2px;margin-bottom:8px;
  filter:drop-shadow(0 0 20px currentColor)}
.hero-pred.tai{color:var(--tai)}.hero-pred.xiu{color:var(--xiu)}
.hero-pred.none{color:var(--muted);font-size:32px}
.hero-conf{font-size:13px;color:var(--muted)}
.hero-conf b{color:#fff;font-size:16px}
.hero-cores{margin-top:14px;font-size:11px;color:var(--muted)}
.hero-cores code{background:rgba(14,165,233,.15);color:#7dd3fc;padding:2px 8px;
  border-radius:4px;margin:0 3px;font-family:monospace}

/* ============ GAUGE ============ */
.gauge-wrap{position:relative;width:140px;height:140px;margin:0 auto 16px}
.gauge-svg{transform:rotate(-90deg);width:100%;height:100%}
.gauge-track{fill:none;stroke:rgba(100,116,139,.2);stroke-width:10}
.gauge-fill{fill:none;stroke:url(#ggrad);stroke-width:10;stroke-linecap:round;
  transition:stroke-dasharray .8s cubic-bezier(.4,0,.2,1)}
.gauge-value{position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;font-weight:900}
.gauge-value .n{font-size:32px;background:linear-gradient(135deg,#0ea5e9,#6366f1);
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.gauge-value .u{font-size:10px;color:var(--muted);letter-spacing:1px;text-transform:uppercase}

/* ============ STATS GRID ============ */
.stats{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px}
.stat{background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:12px;text-align:center}
.stat .k{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
.stat .v{font-size:16px;font-weight:800;color:#7dd3fc;word-break:break-all}
.stat.pos .v{color:var(--green)}.stat.neg .v{color:var(--red)}

/* ============ CHART ============ */
.chart-wrap{background:var(--panel2);border:1px solid var(--border);border-radius:12px;
  padding:12px;height:180px;position:relative}
.chart-wrap canvas{max-height:100%}

/* ============ CHAT ============ */
.chat{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:8px;
  padding-right:4px;scrollbar-width:thin;scrollbar-color:var(--border) transparent;
  max-height:calc(100vh - 200px)}
.chat::-webkit-scrollbar{width:6px}
.chat::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.msg{background:rgba(15,23,42,.6);border-left:3px solid var(--accent);
  padding:10px 14px;border-radius:8px;font-size:12.5px;line-height:1.6;
  animation:slideIn .3s ease;word-wrap:break-word}
@keyframes slideIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
.msg code{background:rgba(14,165,233,.15);color:#7dd3fc;padding:1px 6px;
  border-radius:3px;font-family:'SF Mono',Monaco,monospace;font-size:11.5px}
.msg b{color:#fff;font-weight:700}
.msg .win{border-left-color:var(--green);background:rgba(34,197,94,.08)}
.msg .loss{border-left-color:var(--red);background:rgba(239,68,68,.08)}

/* ============ TABS ============ */
.tabs{display:flex;gap:4px;margin-bottom:16px;background:var(--panel2);
  padding:4px;border-radius:10px}
.tab{flex:1;padding:9px;background:transparent;border:none;border-radius:7px;
  cursor:pointer;font-size:11px;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.5px;transition:.2s}
.tab:hover{color:var(--text)}
.tab.active{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;
  box-shadow:0 4px 12px rgba(14,165,233,.3)}
.tab-content{display:none;flex:1;overflow-y:auto;padding-right:4px;
  scrollbar-width:thin;scrollbar-color:var(--border) transparent}
.tab-content::-webkit-scrollbar{width:6px}
.tab-content::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.tab-content.active{display:block}

/* ============ FORMS ============ */
.field{margin-bottom:12px}
.field label{display:block;font-size:10px;color:var(--muted);margin-bottom:6px;
  text-transform:uppercase;letter-spacing:.5px;font-weight:600}
.field input,.field select{width:100%;padding:10px 12px;background:var(--panel2);
  border:1px solid var(--border);border-radius:8px;color:var(--text);
  font-size:13px;outline:none;transition:.2s}
.field input:focus,.field select:focus{border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(14,165,233,.12)}
.btn{width:100%;padding:11px;border:none;border-radius:9px;font-weight:700;
  cursor:pointer;font-size:12.5px;color:#fff;background:linear-gradient(135deg,var(--accent),var(--accent2));
  transition:.2s;letter-spacing:.5px;margin-bottom:8px}
.btn:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(14,165,233,.35)}
.btn:active{transform:translateY(0)}
.btn.green{background:linear-gradient(135deg,#22c55e,#16a34a)}
.btn.green:hover{box-shadow:0 6px 16px rgba(34,197,94,.35)}
.btn.red{background:linear-gradient(135deg,#ef4444,#dc2626)}
.btn.red:hover{box-shadow:0 6px 16px rgba(239,68,68,.35)}
.btn.gray{background:#374151}
.btn.gray:hover{box-shadow:0 6px 16px rgba(55,65,81,.35)}
.btn.small{padding:7px;font-size:11px}
.row{display:flex;gap:8px}.row .btn{margin-bottom:0}

/* ============ WEIGHTS ============ */
.weight-row{display:flex;justify-content:space-between;align-items:center;
  padding:8px 10px;background:var(--panel2);border-radius:6px;margin-bottom:4px;font-size:12px}
.weight-row .name{color:#cbd5e1;font-family:monospace}
.weight-row .bar{flex:1;height:4px;background:rgba(100,116,139,.2);border-radius:2px;
  margin:0 12px;overflow:hidden}
.weight-row .bar>div{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));
  border-radius:2px;transition:width .5s}
.weight-row .val{color:#7dd3fc;font-family:monospace;font-weight:700;min-width:44px;text-align:right}

/* ============ ADMIN ============ */
.user-row{display:flex;justify-content:space-between;align-items:center;
  padding:8px 12px;background:var(--panel2);border-radius:8px;margin-bottom:6px;font-size:12px}
.user-row .info{display:flex;align-items:center;gap:8px}
.user-row .actions{display:flex;gap:4px}
.user-row button{padding:5px 10px;font-size:10px;border:none;border-radius:5px;
  cursor:pointer;color:#fff;font-weight:700}

/* ============ TOAST ============ */
.toast-box{position:fixed;top:80px;right:20px;z-index:1000;display:flex;
  flex-direction:column;gap:8px;pointer-events:none}
.toast{background:rgba(30,41,59,.95);backdrop-filter:blur(20px);border:1px solid var(--border);
  padding:12px 18px;border-radius:10px;font-size:13px;color:#fff;
  box-shadow:0 10px 30px rgba(0,0,0,.4);animation:toastIn .3s ease;max-width:320px;pointer-events:auto}
.toast.success{border-left:3px solid var(--green)}
.toast.error{border-left:3px solid var(--red)}
.toast.info{border-left:3px solid var(--accent)}
@keyframes toastIn{from{opacity:0;transform:translateX(60px)}to{opacity:1;transform:none}}
@keyframes toastOut{to{opacity:0;transform:translateX(60px)}}

.history-strip{display:flex;gap:3px;flex-wrap:wrap;padding:8px 0}
.history-chip{width:26px;height:26px;border-radius:6px;display:flex;
  align-items:center;justify-content:center;font-size:10px;font-weight:900;color:#fff}
.history-chip.tai{background:linear-gradient(135deg,#0ea5e9,#0284c7)}
.history-chip.xiu{background:linear-gradient(135deg,#ef4444,#b91c1c)}
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    <span class="brand-logo">🤖</span>
    <div>
      <div>AI TÀI XỈU ULTRA V4</div>
      <div class="brand-sub">35 Cores · Regime-Aware · Confidence Scoring</div>
    </div>
  </div>
  <div class="top-right">
    <span>👤 <b>{{ username }}</b></span>
    {% if is_vip %}<span class="badge vip">VIP</span>{% endif %}
    {% if is_admin %}<span class="badge admin">ADMIN</span>{% endif %}
    <button class="btn-logout" onclick="logout()">Thoát</button>
  </div>
</div>

<div class="layout">

  <!-- ================= LEFT: LIVE PREDICTION ================= -->
  <div class="panel" style="max-height:calc(100vh - 92px)">
    <div class="panel-title">🎯 Dự đoán Live</div>

    <div class="gauge-wrap">
      <svg class="gauge-svg" viewBox="0 0 100 100">
        <defs>
          <linearGradient id="ggrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#0ea5e9"/>
            <stop offset="100%" stop-color="#6366f1"/>
          </linearGradient>
        </defs>
        <circle class="gauge-track" cx="50" cy="50" r="42"/>
        <circle class="gauge-fill" id="gauge-fill" cx="50" cy="50" r="42"
                stroke-dasharray="0 264"/>
      </svg>
      <div class="gauge-value">
        <div class="n" id="conf-num">0%</div>
        <div class="u">Confidence</div>
      </div>
    </div>

    <div class="hero none" id="hero">
      <div class="hero-label">Dự đoán AI</div>
      <div class="hero-pred none" id="hero-pred">ĐANG TẢI...</div>
      <div class="hero-conf"><b id="conf-detail">0%</b> độ tin cậy</div>
      <div class="hero-cores" id="hero-cores"></div>
    </div>

    <div class="stats">
      <div class="stat" id="st-balance-wrap"><div class="k">Số dư</div><div class="v" id="st-balance">-</div></div>
      <div class="stat" id="st-pl-wrap"><div class="k">Lãi/Lỗ</div><div class="v" id="st-pl">-</div></div>
      <div class="stat"><div class="k">Streak</div><div class="v" id="st-streak">0</div></div>
      <div class="stat"><div class="k">Accuracy</div><div class="v" id="st-acc">0%</div></div>
    </div>

    <div class="panel-title" style="margin-top:8px">📈 Lịch sử gần đây</div>
    <div class="history-strip" id="history-strip"></div>
  </div>

  <!-- ================= CENTER: CHART + CHAT ================= -->
  <div class="panel" style="max-height:calc(100vh - 92px)">
    <div class="panel-title">📊 Xu hướng 50 phiên gần nhất</div>
    <div class="chart-wrap">
      <canvas id="mainChart"></canvas>
    </div>

    <div class="panel-title" style="margin-top:18px">📡 Nhật ký Bot</div>
    <div class="chat" id="chat"></div>
  </div>

  <!-- ================= RIGHT: CONTROLS ================= -->
  <div class="panel" style="max-height:calc(100vh - 92px)">
    <div class="tabs">
      <button class="tab active" onclick="switchTab('main',this)">Điều khiển</button>
      <button class="tab" onclick="switchTab('weights',this)">AI</button>
      {% if is_admin %}<button class="tab" onclick="switchTab('admin',this)">Admin</button>{% endif %}
    </div>

    <div class="tab-content active" id="tab-main">
      <div class="panel-title">🔐 Đăng nhập Game</div>
      <div class="field"><label>Tài khoản</label><input id="game-user" placeholder="username"></div>
      <div class="field"><label>Mật khẩu</label><input id="game-pass" type="password" placeholder="••••••"></div>
      <button class="btn" onclick="gameLogin()">🚀 Kết nối</button>

      <div class="panel-title" style="margin-top:20px">⚙️ Cấu hình Bot</div>
      <div class="row">
        <button class="btn green small" onclick="autobet(true)">▶ Bật Auto</button>
        <button class="btn red small" onclick="autobet(false)">⏸ Tắt</button>
      </div>
      <div class="field" style="margin-top:12px"><label>Tiền cược gốc</label>
        <input id="bet-amount" type="number" value="10000"></div>
      <div class="field"><label>Min Confidence % (chỉ bet khi conf ≥)</label>
        <input id="min-conf" type="number" value="50" min="0" max="100"></div>
      <button class="btn gray small" onclick="setMinConf()">Lưu Min Conf</button>
      <div class="field" style="margin-top:12px"><label>Target chốt lãi</label>
        <input id="target" type="number" placeholder="VD: 500000"></div>
      <button class="btn small" onclick="setTarget()">🎯 Đặt Target</button>
      <div class="row" style="margin-top:8px">
        <button class="btn small" onclick="setX2(true)">🔥 X2 ON</button>
        <button class="btn gray small" onclick="setX2(false)">X2 OFF</button>
      </div>
      <button class="btn red small" style="margin-top:12px" onclick="stopBot()">🔌 Ngắt kết nối</button>
    </div>

    <div class="tab-content" id="tab-weights">
      <div class="panel-title">🧠 TOP Cores đang dẫn đầu</div>
      <div id="weights-list" style="font-size:12px">Đang tải...</div>
      <div style="margin-top:16px;font-size:11px;color:var(--muted);line-height:1.6">
        <b style="color:#e2e8f0">Cơ chế cập nhật:</b><br>
        • Đúng → weight tăng (max 25.0)<br>
        • Sai → weight giảm 10% - 0.5 (min 0.1)<br>
        • Kèm <b>regime boost</b> theo xu hướng thị trường
      </div>
    </div>

    {% if is_admin %}
    <div class="tab-content" id="tab-admin">
      <div class="panel-title">➕ Tạo User</div>
      <div class="field"><label>Username</label><input id="new-username"></div>
      <div class="field"><label>Password</label><input id="new-password" type="password"></div>
      <button class="btn" onclick="createUser()">Tạo user</button>
      <div class="panel-title" style="margin-top:16px">👥 Danh sách</div>
      <div id="user-list">Đang tải...</div>
    </div>
    {% endif %}
  </div>

</div>

<div class="toast-box" id="toast-box"></div>

<script>
const socket = io();
let lastPrediction = null;
let chart = null;

// ============ TOAST ============
function toast(text, type='info') {
  const box = document.getElementById('toast-box');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = text;
  box.appendChild(el);
  setTimeout(() => { el.style.animation = 'toastOut .3s forwards';
    setTimeout(() => el.remove(), 300); }, 3500);
}

// ============ CHAT ============
function addMessage(html) {
  const c = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = 'msg';
  // Determine styling
  if (html.includes('HÚP') || html.includes('ĐẠT TARGET')) div.classList.add('win');
  else if (html.includes('GÃY CẦU')) div.classList.add('loss');
  div.innerHTML = html.replace(/\\n/g, '<br>');
  c.appendChild(div);
  c.scrollTop = c.scrollHeight;
  while (c.children.length > 400) c.removeChild(c.firstChild);
}

// ============ SOCKET ============
socket.on('connect', () => addMessage('🟢 <b>WebSocket đã kết nối</b>'));
socket.on('bot_message', m => addMessage(m.text));
socket.on('state_update', updateState);

function updateState(s) {
  // Hero
  const hero = document.getElementById('hero');
  const hp = document.getElementById('hero-pred');
  const hc = document.getElementById('hero-cores');
  hero.className = 'hero';
  hp.className = 'hero-pred';
  if (s.prediction === 'TAI') {
    hero.classList.add('tai'); hp.classList.add('tai'); hp.textContent = '🔵 TÀI';
  } else if (s.prediction === 'XIU') {
    hero.classList.add('xiu'); hp.classList.add('xiu'); hp.textContent = '🔴 XỈU';
  } else {
    hero.classList.add('none'); hp.classList.add('none'); hp.textContent = 'ĐANG TÍNH...';
  }
  document.getElementById('conf-detail').textContent = (s.confidence||0) + '%';
  if (s.top_models && s.top_models.length) {
    hc.innerHTML = 'Top cores: ' + s.top_models.slice(0,3)
      .map(([m,w]) => `<code>${m}</code>`).join('');
  } else { hc.innerHTML = ''; }

  // Gauge
  const pct = Math.max(0, Math.min(100, s.confidence || 0));
  document.getElementById('gauge-fill').setAttribute('stroke-dasharray',
    `${(pct/100)*264} 264`);
  document.getElementById('conf-num').textContent = Math.round(pct) + '%';

  // Stats
  const bal = document.getElementById('st-balance');
  const pl = document.getElementById('st-pl');
  bal.textContent = (s.balance||0).toLocaleString();
  pl.textContent = (s.profit_loss||0).toLocaleString();
  document.getElementById('st-pl-wrap').className = 'stat ' +
    ((s.profit_loss||0) >= 0 ? 'pos' : 'neg');
  document.getElementById('st-streak').textContent = s.win_streak || 0;
  const acc = s.pred_total > 0 ? (s.pred_correct / s.pred_total * 100).toFixed(1) : '0.0';
  document.getElementById('st-acc').textContent = acc + '%';

  // History strip
  const strip = document.getElementById('history-strip');
  if (s.history_tail && s.history_tail.length) {
    strip.innerHTML = s.history_tail.slice(-30).map(r => 
      `<div class="history-chip ${r==='TAI'?'tai':'xiu'}">${r==='TAI'?'T':'X'}</div>`
    ).join('');
  }

  // Chart
  updateChart(s.history_tail || []);

  // Auto trigger bet when prediction changes
  if (s.prediction !== lastPrediction) {
    lastPrediction = s.prediction;
    if (s.prediction) {
      toast(`AI chốt: ${s.prediction === 'TAI' ? '🔵 TÀI' : '🔴 XỈU'} (${s.confidence}%)`,
        s.confidence >= 60 ? 'success' : 'info');
    }
  }
}

// ============ CHART ============
function updateChart(history) {
  const ctx = document.getElementById('mainChart').getContext('2d');
  const tail = history.slice(-50);
  const labels = tail.map((_, i) => i + 1);
  const data = tail.map(r => r === 'TAI' ? 1 : -1);
  const colors = tail.map(r => r === 'TAI' ? '#0ea5e9' : '#ef4444');

  if (!chart) {
    chart = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets: [{
        data, backgroundColor: colors, borderRadius: 3, borderSkipped: false
      }]},
      options: {
        responsive: true, maintainAspectRatio: false, animation: {duration: 300},
        plugins: { legend: {display: false}, tooltip: {
          callbacks: { label: c => c.raw === 1 ? '🔵 TÀI' : '🔴 XỈU' }
        }},
        scales: {
          y: { display: false, min: -1.2, max: 1.2 },
          x: { display: false }
        }
      }
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = data;
    chart.data.datasets[0].backgroundColor = colors;
    chart.update('none');
  }
}

// ============ API ============
async function api(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body||{})});
  return await r.json();
}

async function gameLogin() {
  const u = document.getElementById('game-user').value.trim();
  const p = document.getElementById('game-pass').value;
  if (!u || !p) return toast('Nhập đủ tài khoản + mật khẩu', 'error');
  toast('Đang kết nối...', 'info');
  const d = await api('/api/game-login', {username:u, password:p});
  if (d.error) toast(d.error, 'error');
  else toast(`✅ Đã kết nối: ${d.nickname}`, 'success');
}

async function autobet(enabled) {
  const amount = parseInt(document.getElementById('bet-amount').value) || 10000;
  const d = await api('/api/autobet', {enabled, amount});
  if (d.error) toast(d.error, 'error');
  else toast(enabled ? `✅ Auto BẬT · Cược ${amount.toLocaleString()}` : '🔴 Auto TẮT', 'info');
}

async function setMinConf() {
  const v = parseInt(document.getElementById('min-conf').value) || 50;
  const d = await api('/api/min-conf', {value: v});
  if (d.error) toast(d.error, 'error');
  else toast(`✅ Min confidence: ${v}%`, 'success');
}

async function setTarget() {
  const t = parseInt(document.getElementById('target').value);
  if (!t) return toast('Nhập số target', 'error');
  const d = await api('/api/chotlai', {target:t});
  if (d.error) toast(d.error, 'error');
  else toast(`🎯 Target: ${t.toLocaleString()}`, 'success');
}

async function setX2(enabled) {
  const d = await api('/api/x2', {enabled});
  if (d.error) toast(d.error, 'error');
  else toast(`X2: ${enabled ? 'BẬT' : 'TẮT'}`, 'info');
}

async function stopBot() {
  if (!confirm('Ngắt kết nối?')) return;
  const d = await api('/api/stop', {});
  toast('🔌 Đã ngắt', 'info');
}

// ============ WEIGHTS ============
async function loadWeights() {
  const r = await fetch('/api/weights');
  const d = await r.json();
  if (d.error) return;
  const max = Math.max(...d.weights.map(w => w[1]));
  document.getElementById('weights-list').innerHTML =
    `<div style="color:#64748b;margin-bottom:10px;font-size:11px">Data: ${d.history_len} vòng</div>` +
    d.weights.map(([k, v]) => 
      `<div class="weight-row">
         <span class="name">${k}</span>
         <div class="bar"><div style="width:${(v/max*100).toFixed(0)}%"></div></div>
         <span class="val">${v.toFixed(2)}</span>
       </div>`
    ).join('');
}

// ============ ADMIN ============
async function createUser() {
  const un = document.getElementById('new-username').value.trim();
  const pw = document.getElementById('new-password').value;
  if (!un || !pw) return toast('Nhập đủ', 'error');
  const d = await api('/api/admin/create', {username:un, password:pw, is_vip:true});
  if (d.error) toast(d.error, 'error');
  else { toast('✅ Đã tạo user', 'success'); loadUsers(); }
}

async function loadUsers() {
  const r = await fetch('/api/admin/users');
  const d = await r.json();
  if (d.error) return;
  document.getElementById('user-list').innerHTML = Object.entries(d).map(([u, info]) =>
    `<div class="user-row">
       <div class="info">
         <b>${u}</b>
         ${info.is_admin ? '<span class="badge admin">ADMIN</span>' : ''}
         ${info.is_vip ? '<span class="badge vip">VIP</span>' : ''}
       </div>
       <div class="actions">
         <button style="background:#22c55e" onclick="setVip('${u}',${!info.is_vip})">${info.is_vip?'Bỏ VIP':'Cấp VIP'}</button>
         <button style="background:#ef4444" onclick="delUser('${u}')">Xóa</button>
       </div>
     </div>`
  ).join('');
}

async function setVip(username, is_vip) {
  const d = await api('/api/admin/set-vip', {username, is_vip});
  if (d.error) toast(d.error, 'error'); else { toast('Đã cập nhật', 'success'); loadUsers(); }
}
async function delUser(username) {
  if (!confirm('Xóa user ' + username + '?')) return;
  const d = await api('/api/admin/delete', {username});
  if (d.error) toast(d.error, 'error'); else { toast('Đã xóa', 'success'); loadUsers(); }
}

function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'weights') loadWeights();
  if (name === 'admin') loadUsers();
}

async function logout() {
  await fetch('/api/logout', {method:'POST'});
  window.location.href = '/login';
}

// Auto-refresh weights tab every 10s if active
setInterval(() => {
  if (document.getElementById('tab-weights').classList.contains('active')) loadWeights();
}, 10000);
</script>
</body></html>"""

# ==========================================
# ROUTES
# ==========================================
@app.route('/')
def index():
    if 'user' not in session: return redirect('/login')
    u = USERS.get(session['user'], {})
    return render_template_string(INDEX_HTML, username=session['user'],
                                  is_admin=u.get('is_admin', False),
                                  is_vip=u.get('is_vip', False))

@app.route('/login')
def login_page(): return render_template_string(LOGIN_HTML)

@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.json
    username = (d.get('username') or '').strip()
    if username not in USERS or USERS[username]['password'] != hash_pw(d.get('password') or ''):
        return jsonify({"error": "Sai tài khoản/mật khẩu"}), 401
    session['user'] = username
    init_user_state(username)
    return jsonify({"ok": True, "is_admin": USERS[username]['is_admin'], "is_vip": USERS[username]['is_vip']})

@app.route('/api/logout', methods=['POST'])
def api_logout(): session.clear(); return jsonify({"ok": True})

@app.route('/api/game-login', methods=['POST'])
@require_vip
def api_game_login():
    user = session['user']; d = request.json
    res = login_and_get_token(d.get('username',''), d.get('password',''))
    if '_error' in res: return jsonify({"error": res['_error']}), 400
    init_user_state(user)
    user_states[user]['balance'] = res['money']
    send_msg(user, f"🎉 <b>ĐĂNG NHẬP THÀNH CÔNG</b>\n👤 <code>{res['nickname']}</code>\n💰 Dư: <code>{res['money']:,}</code>\n🌍 Data: {len(GLOBAL_HISTORY)} vòng")
    threading.Thread(target=start_websocket, args=(user, res['token']), daemon=True).start()
    return jsonify({"ok": True, "nickname": res['nickname'], "money": res['money']})

@app.route('/api/autobet', methods=['POST'])
@require_vip
def api_autobet():
    user = session['user']
    if user not in user_states: return jsonify({"error": "Chưa login game"}), 400
    d = request.json
    if d.get('enabled'):
        amt = int(d.get('amount', 10000))
        user_states[user]['auto_bet_enabled'] = True
        user_states[user]['base_bet_amount'] = amt
        send_msg(user, f"✅ <b>AUTO BET: BẬT</b>\n💸 Vốn gốc: <code>{amt:,}</code>")
    else:
        user_states[user]['auto_bet_enabled'] = False
        send_msg(user, "🔴 <b>AUTO BET: TẮT</b>")
    return jsonify({"ok": True})

@app.route('/api/min-conf', methods=['POST'])
@require_vip
def api_min_conf():
    user = session['user']
    if user not in user_states: return jsonify({"error": "Chưa login game"}), 400
    v = int(request.json.get('value', 50))
    user_states[user]['min_confidence'] = max(0, min(100, v))
    send_msg(user, f"🎯 Min confidence = <b>{v}%</b> (chỉ bet khi AI tự tin ≥ mức này)")
    return jsonify({"ok": True})

@app.route('/api/x2', methods=['POST'])
@require_vip
def api_x2():
    user = session['user']
    if user not in user_states: return jsonify({"error": "Chưa login game"}), 400
    e = bool(request.json.get('enabled'))
    user_states[user]['x2_mode'] = e
    send_msg(user, f"🔥 <b>X2: {'BẬT' if e else 'TẮT'}</b>")
    return jsonify({"ok": True})

@app.route('/api/chotlai', methods=['POST'])
@require_vip
def api_chotlai():
    user = session['user']
    if user not in user_states: return jsonify({"error": "Chưa login game"}), 400
    try:
        t = int(request.json.get('target', 0))
        user_states[user]['target_profit'] = t
        send_msg(user, f"🎯 <b>TARGET:</b> <code>{t:,}</code>")
        return jsonify({"ok": True})
    except: return jsonify({"error": "Số không hợp lệ"}), 400

@app.route('/api/stats')
@require_vip
def api_stats():
    user = session['user']
    if user not in user_states: return jsonify({"error": "Chưa login game"}), 400
    s = dict(user_states[user]); s.pop('last_predictions', None)
    return jsonify(s)

@app.route('/api/weights')
@require_vip
def api_weights():
    top = sorted(GLOBAL_AI_WEIGHTS.items(), key=lambda x: x[1], reverse=True)[:15]
    return jsonify({"weights": top, "history_len": len(GLOBAL_HISTORY)})

@app.route('/api/stop', methods=['POST'])
@require_vip
def api_stop():
    user = session['user']
    if user in active_sockets:
        try: active_sockets[user].disconnect()
        except: pass
        del active_sockets[user]
    send_msg(user, "🔌 Đã ngắt kết nối.")
    return jsonify({"ok": True})

@app.route('/api/admin/users')
@require_login
def api_admin_users():
    if not USERS[session['user']]['is_admin']: return jsonify({"error": "Forbidden"}), 403
    return jsonify({u: {"is_admin": d['is_admin'], "is_vip": d['is_vip']} for u, d in USERS.items()})

@app.route('/api/admin/create', methods=['POST'])
@require_login
def api_admin_create():
    if not USERS[session['user']]['is_admin']: return jsonify({"error": "Forbidden"}), 403
    d = request.json
    un = (d.get('username') or '').strip()
    if not un or not d.get('password'): return jsonify({"error": "Thiếu thông tin"}), 400
    if un in USERS: return jsonify({"error": "User đã tồn tại"}), 400
    USERS[un] = {"password": hash_pw(d['password']), "is_admin": False,
                 "is_vip": bool(d.get('is_vip', True))}
    save_users(USERS)
    return jsonify({"ok": True})

@app.route('/api/admin/set-vip', methods=['POST'])
@require_login
def api_admin_set_vip():
    if not USERS[session['user']]['is_admin']: return jsonify({"error": "Forbidden"}), 403
    d = request.json; u = d.get('username')
    if u not in USERS: return jsonify({"error": "User không tồn tại"}), 404
    USERS[u]['is_vip'] = bool(d.get('is_vip'))
    save_users(USERS)
    return jsonify({"ok": True})

@app.route('/api/admin/delete', methods=['POST'])
@require_login
def api_admin_delete():
    if not USERS[session['user']]['is_admin']: return jsonify({"error": "Forbidden"}), 403
    u = request.json.get('username')
    if u == session['user']: return jsonify({"error": "Không tự xóa mình"}), 400
    if u in USERS: del USERS[u]; save_users(USERS)
    return jsonify({"ok": True})

# ==========================================
# WEB SOCKET
# ==========================================
@web_socketio.on('connect')
def on_web_connect():
    user = session.get('user')
    if user:
        join_room(f"user_{user}")
        send_state(user)

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    print("=" * 60)
    print("🤖 AI TÀI XỈU ULTRA V4 — REGIME-AWARE + CONFIDENCE")
    print("🌐 http://localhost:5000  (admin / admin123)")
    print("=" * 60)
    threading.Thread(target=background_data_collector, daemon=True).start()
    web_socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
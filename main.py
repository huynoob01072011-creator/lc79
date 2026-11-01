import requests
import hashlib
import base64
import json
import logging
import threading
import time
import socketio
import random
import math
import secrets
from flask import Flask, render_template_string, request, jsonify

# ==========================================
# CẤU HÌNH
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

app = Flask(__name__)

MAX_GLOBAL_HISTORY = 2000

# Global AI State
GLOBAL_HISTORY = []
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
GLOBAL_LAST_PREDICTIONS = {}
GLOBAL_CURRENT_PREDICTION = None
GLOBAL_LAST_SESSION_ID = None
GLOBAL_PROCESSED_SESSIONS = set()
GLOBAL_LOCK = threading.Lock()

USER_SESSIONS = {}
USERNAME_TO_TOKEN = {}
SESSION_LOCK = threading.Lock()


def md5_hash(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


# ==========================================
# 🧠 35 LÕI AI - DỰ ĐOÁN
# ==========================================
def make_prediction_vip():
    with GLOBAL_LOCK:
        history = list(GLOBAL_HISTORY)
        weights = dict(GLOBAL_AI_WEIGHTS)

    if len(history) < 10:
        return random.choice(["TAI", "XIU"]), {}

    model_preds = {}
    last_item = history[-1]
    opp_item = "XIU" if last_item == "TAI" else "TAI"
    recent_str = "".join(["T" if x == "TAI" else "X" for x in history])
    streak = len(recent_str) - len(recent_str.rstrip(recent_str[-1]))

    model_preds["trend"] = last_item if history[-5:].count(last_item) >= 3 else opp_item
    model_preds["pattern"] = opp_item if recent_str.endswith("TXTX") or recent_str.endswith("TTXX") else last_item

    t1 = {"TAI": {"TAI": 0, "XIU": 0}, "XIU": {"TAI": 0, "XIU": 0}}
    for i in range(len(history) - 1):
        t1[history[i]][history[i+1]] += 1
    model_preds["markov1"] = "TAI" if t1[last_item]["TAI"] > t1[last_item]["XIU"] else "XIU"
    model_preds["markov2"] = "TAI" if history[-2:] == ["TAI", "TAI"] else "XIU"
    model_preds["markov3"] = opp_item if history[-3:] == [last_item]*3 else model_preds["markov2"]

    model_preds["frequency"] = "XIU" if history[-20:].count("TAI") > 10 else "TAI"
    model_preds["momentum"] = "TAI" if sum([i+1 if r == "TAI" else -(i+1) for i, r in enumerate(history[-5:])]) > 0 else "XIU"
    model_preds["symmetry"] = opp_item if len(recent_str) >= 6 and recent_str[-6:-3] == recent_str[-3:][::-1] else last_item
    model_preds["alternating"] = opp_item
    model_preds["fibonacci"] = opp_item if streak in [3, 5, 8, 13] else last_item
    model_preds["chaos"] = opp_item if sum(1 for i in range(len(recent_str[-10:]) - 1) if recent_str[-10:][i] != recent_str[-10:][i+1]) >= 7 else last_item
    model_preds["shadow"] = "TAI" if history[-50:].count("TAI") < 25 else "XIU"

    rsi_score = recent_str[-10:].count("T")
    model_preds["rsi_indicator"] = "XIU" if rsi_score >= 7 else ("TAI" if rsi_score <= 3 else last_item)
    model_preds["macd_cross"] = "TAI" if recent_str[-3:].count("T") > (recent_str[-9:].count("T") / 3) else "XIU"
    model_preds["pivot_reversal"] = history[-1] if history[-3] == history[-2] and history[-2] != history[-1] else last_item
    model_preds["cluster_3"] = "TAI" if recent_str[-3:] in ["TTT", "TXX", "XTX", "XXT"] else "XIU"
    model_preds["parity"] = opp_item if streak % 2 == 0 else last_item
    model_preds["golden_ratio"] = "TAI" if (history[-30:].count("TAI") / 30) < 0.618 else "XIU"
    model_preds["quantum"] = random.choice(["TAI", "XIU"])

    model_preds["anti_bait"] = opp_item if streak >= 5 or recent_str.endswith("TXTXT") else last_item

    max_streak = 1; cur = 1
    for i in range(1, len(history)):
        if history[i] == history[i-1]: cur += 1
        else: max_streak = max(max_streak, cur); cur = 1
    model_preds["smart_breaker"] = opp_item if streak >= max_streak - 1 and streak >= 3 else last_item

    l4 = recent_str[-4:]
    t_c4 = recent_str[:-1].count(l4 + "T")
    x_c4 = recent_str[:-1].count(l4 + "X")
    model_preds["ngram_4"] = "TAI" if t_c4 > x_c4 else ("XIU" if x_c4 > t_c4 else opp_item)

    l5 = recent_str[-5:]
    t_c5 = recent_str[:-1].count(l5 + "T")
    x_c5 = recent_str[:-1].count(l5 + "X")
    model_preds["ngram_5"] = "TAI" if t_c5 > x_c5 else ("XIU" if x_c5 > t_c5 else opp_item)

    if recent_str.endswith("TXTXT"): model_preds["elliott_wave"] = last_item
    elif recent_str.endswith("TTXXTT"): model_preds["elliott_wave"] = "XIU"
    else: model_preds["elliott_wave"] = opp_item

    if streak == 4 or streak == 6: model_preds["contrarian"] = opp_item
    elif recent_str[-6:] == "TXTXTX": model_preds["contrarian"] = "XIU"
    else: model_preds["contrarian"] = last_item

    ma10 = recent_str[-10:].count("T") / 10.0
    if ma10 >= 0.8: model_preds["bollinger_bands"] = "XIU"
    elif ma10 <= 0.2: model_preds["bollinger_bands"] = "TAI"
    else: model_preds["bollinger_bands"] = last_item

    t_total = history[-100:].count("TAI") if len(history) >= 100 else history.count("TAI")
    model_preds["mean_reversion"] = "TAI" if t_total < (len(history[-100:]) * 0.45) else "XIU"

    if len(recent_str) >= 8:
        model_preds["mirror_reflection"] = "TAI" if recent_str[-8] == "T" else "XIU"
    else: model_preds["mirror_reflection"] = opp_item

    model_preds["martingale_trap"] = opp_item if streak == 3 or streak == 7 else last_item
    model_preds["poisson_prob"] = "TAI" if (history[-5:].count("TAI") % 2 == 1) else "XIU"
    model_preds["harmonic_cycle"] = history[-4] if len(history) >= 4 else opp_item
    model_preds["breakout_hunter"] = last_item if streak == 1 and history[-2] == history[-3] else opp_item

    if len(recent_str) >= 5 and recent_str[-5:] in ["TTTXT", "XXXTX"]:
        model_preds["volume_fakeout"] = last_item
    else: model_preds["volume_fakeout"] = opp_item

    model_preds["time_decay"] = opp_item
    model_preds["neural_bias"] = "TAI" if history[-7:].count("TAI") > 3 else "XIU"
    model_preds["twin_peaks"] = opp_item if recent_str.endswith("TTXTT") or recent_str.endswith("XXTXX") else last_item

    predictions = {"TAI": 0.0, "XIU": 0.0}
    for model, pred in model_preds.items():
        if model in weights:
            predictions[pred] += math.pow(weights[model], 1.5)

    return ("TAI" if predictions["TAI"] > predictions["XIU"] else "XIU"), model_preds


# ==========================================
# 🔐 LOGIN API
# ==========================================
def do_login(username, password_md5):
    try:
        url = f"https://apifo88daigia.tele68.com/api?c=3&un={username}&pw={password_md5}&cp=R&cl=R&pf=web&at="
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        data = r.json()

        if not data.get("success"):
            return {"success": False, "message": data.get("message", "Sai thông tin đăng nhập")}

        session_key = data["sessionKey"]
        session_key_padded = session_key + "=" * ((4 - len(session_key) % 4) % 4)
        session_data = json.loads(base64.b64decode(session_key_padded).decode('utf-8'))
        nickname = session_data.get("nickname") or session_data.get("nickName")

        access_token = data["accessToken"]
        r2 = requests.post(
            "https://wlb.tele68.com/v1/lobby/auth/login?cp=R&cl=R&pf=web&at=",
            headers={"authority": "wlb.tele68.com", "content-type": "application/json"},
            json={"nickName": nickname, "accessToken": access_token}, timeout=12
        )
        lobby = r2.json()
        game_token = lobby.get("token")

        if not game_token:
            return {"success": False, "message": "Lobby không trả về JWT token"}

        return {
            "success": True,
            "game_token": game_token,
            "nickname": nickname,
            "money": lobby.get("remoteLoginResp", {}).get("money", 0),
            "session_data": session_data,
            "raw": data
        }
    except Exception as e:
        return {"success": False, "message": f"Lỗi kết nối: {e}"}


# ==========================================
# 🌐 GAME SOCKET (theo từng user)
# ==========================================
def add_log(token_id, msg):
    with SESSION_LOCK:
        if token_id in USER_SESSIONS:
            USER_SESSIONS[token_id]["log"].append({
                "time": time.strftime("%H:%M:%S"),
                "msg": msg
            })
            if len(USER_SESSIONS[token_id]["log"]) > 100:
                USER_SESSIONS[token_id]["log"] = USER_SESSIONS[token_id]["log"][-100:]


def start_game_socket(token_id, game_token):
    with SESSION_LOCK:
        if token_id not in USER_SESSIONS:
            return

    sio = socketio.Client(reconnection=True, reconnection_attempts=20, logger=False, engineio_logger=False)

    @sio.event(namespace='/txmd5')
    def connect():
        with SESSION_LOCK:
            if token_id in USER_SESSIONS:
                USER_SESSIONS[token_id]["game_connected"] = True
        add_log(token_id, "✅ Đã kết nối game server")

    @sio.event(namespace='/txmd5')
    def disconnect():
        with SESSION_LOCK:
            if token_id in USER_SESSIONS:
                USER_SESSIONS[token_id]["game_connected"] = False
        add_log(token_id, "❌ Mất kết nối game server")

    @sio.on('new-session', namespace='/txmd5')
    def on_new_session(data):
        with SESSION_LOCK:
            if token_id not in USER_SESSIONS:
                return
            session = USER_SESSIONS[token_id]
            session["session_id"] = data.get('id', 'N/A')
            session["has_bet_this_session"] = False
            session["dices"] = None
            my_session_id = session["session_id"]

        # Dự đoán (chỉ chạy 1 lần/session)
        with GLOBAL_LOCK:
            if GLOBAL_LAST_SESSION_ID != my_session_id or GLOBAL_CURRENT_PREDICTION is None:
                pred, model_preds = make_prediction_vip()
                GLOBAL_LAST_PREDICTIONS.clear()
                GLOBAL_LAST_PREDICTIONS.update(model_preds)
                GLOBAL_LAST_SESSION_ID = my_session_id
                GLOBAL_CURRENT_PREDICTION = pred
                logger.info(f"AI Dự đoán phiên {my_session_id}: {pred}")
            current_pred = GLOBAL_CURRENT_PREDICTION

        with SESSION_LOCK:
            if token_id not in USER_SESSIONS:
                return
            session = USER_SESSIONS[token_id]
            session["current_prediction"] = current_pred

            # X2 logic: thắng ≥1 → bet × 2, thua reset về base
            if session["x2_mode"] and session["win_streak"] >= 1:
                session["current_bet"] = session["base_bet"] * 2
            else:
                session["current_bet"] = session["base_bet"]

            # Kiểm tra target
            if session["auto_bet"] and session["target_profit"] is not None and session["target_profit"] > 0:
                if session["profit_loss"] >= session["target_profit"]:
                    session["auto_bet"] = False
                    add_log(token_id, f"🏆 ĐẠT TARGET +{session['target_profit']:,} — TẮT AUTO")

        add_log(token_id, f"🔔 Phiên {my_session_id} | Dự đoán: {current_pred} | Cược: {session['current_bet']:,}")

    @sio.on('tick-update', namespace='/txmd5')
    def on_tick_update(data):
        game_state = data.get('state')
        with SESSION_LOCK:
            if token_id not in USER_SESSIONS:
                return
            session = USER_SESSIONS[token_id]
            if (game_state == 'BETTING' and session["auto_bet"]
                    and session["current_prediction"] and not session["has_bet_this_session"]):
                try:
                    sio.emit('bet', {
                        "type": session["current_prediction"],
                        "amount": session["current_bet"]
                    }, namespace='/txmd5')
                    session["has_bet_this_session"] = True
                    session["waiting_for_result"] = True
                    add_log(token_id, f"🚀 Đặt cược {session['current_bet']:,} → {session['current_prediction']}")
                except Exception as e:
                    add_log(token_id, f"⚠️ Lỗi đặt cược: {e}")

    @sio.on('bet-result', namespace='/txmd5')
    def on_bet_result(data):
        with SESSION_LOCK:
            if token_id in USER_SESSIONS and "postBalance" in data:
                USER_SESSIONS[token_id]["balance"] = data["postBalance"]
        try:
            sio.emit('get-current-my-info', None, namespace='/txmd5')
        except:
            pass

    @sio.on('session-result', namespace='/txmd5')
    def on_session_result(data):
        result = data.get('resultTruyenThong', 'N/A')
        dices = data.get('dices', [0, 0, 0])

        with SESSION_LOCK:
            if token_id not in USER_SESSIONS:
                return
            my_session_id = USER_SESSIONS[token_id].get("session_id")

        # Cập nhật history & weights (chỉ 1 lần/session)
        if result in ["TAI", "XIU"]:
            with GLOBAL_LOCK:
                if my_session_id not in GLOBAL_PROCESSED_SESSIONS:
                    GLOBAL_PROCESSED_SESSIONS.add(my_session_id)
                    GLOBAL_HISTORY.append(result)
                    if len(GLOBAL_HISTORY) > MAX_GLOBAL_HISTORY:
                        GLOBAL_HISTORY.pop(0)

                    for model, pred in GLOBAL_LAST_PREDICTIONS.items():
                        if pred == result:
                            GLOBAL_MODEL_STREAK[model] += 1
                            bonus = 0.5 + (0.2 * GLOBAL_MODEL_STREAK[model])
                            GLOBAL_AI_WEIGHTS[model] = min(20.0, GLOBAL_AI_WEIGHTS[model] + bonus)
                        else:
                            GLOBAL_MODEL_STREAK[model] = 0
                            GLOBAL_AI_WEIGHTS[model] = max(0.1, GLOBAL_AI_WEIGHTS[model] - 2.5)

                    if len(GLOBAL_PROCESSED_SESSIONS) > 1000:
                        GLOBAL_PROCESSED_SESSIONS = set(list(GLOBAL_PROCESSED_SESSIONS)[-500:])

        with SESSION_LOCK:
            if token_id not in USER_SESSIONS:
                return
            session = USER_SESSIONS[token_id]
            session["current_result"] = result
            session["dices"] = dices

            if session["current_prediction"] and session["waiting_for_result"]:
                if session["current_prediction"] == result:
                    win_amt = int(session["current_bet"] * 0.98)
                    session["profit_loss"] += win_amt
                    session["win_streak"] += 1
                    add_log(token_id, f"✅ THẮNG +{win_amt:,} | Chuỗi: {session['win_streak']}")
                else:
                    session["profit_loss"] -= session["current_bet"]
                    session["win_streak"] = 0
                    add_log(token_id, f"❌ THUA -{session['current_bet']:,} | Reset chuỗi")
                session["waiting_for_result"] = False

        add_log(token_id, f"🎲 KQ: {result} ({dices[0]}-{dices[1]}-{dices[2]})")

    try:
        sio.connect('https://wtxmd52.tele68.com',
                    socketio_path='txmd5/', namespaces=['/txmd5'],
                    transports=['websocket'], auth={"token": game_token},
                    headers={"User-Agent": "Mozilla/5.0"})
        with SESSION_LOCK:
            if token_id in USER_SESSIONS:
                USER_SESSIONS[token_id]["sio"] = sio
        sio.wait()
    except Exception as e:
        add_log(token_id, f"⚠️ Lỗi socket: {e}")
        with SESSION_LOCK:
            if token_id in USER_SESSIONS:
                USER_SESSIONS[token_id]["game_connected"] = False


# ==========================================
# 🚀 FLASK API ENDPOINTS
# ==========================================
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password_md5 = data.get('password', '')

    if not username or not password_md5:
        return jsonify({"success": False, "message": "Thiếu thông tin đăng nhập"})

    result = do_login(username, password_md5)
    if not result.get("success"):
        return jsonify({"success": False, "message": result.get("message", "Đăng nhập thất bại")})

    # Xoá session cũ (nếu có)
    with SESSION_LOCK:
        old_token = USERNAME_TO_TOKEN.get(username)
        if old_token and old_token in USER_SESSIONS:
            try:
                if USER_SESSIONS[old_token].get("sio"):
                    USER_SESSIONS[old_token]["sio"].disconnect()
            except:
                pass
            del USER_SESSIONS[old_token]

    # Tạo session mới
    token_id = secrets.token_urlsafe(32)
    with SESSION_LOCK:
        USER_SESSIONS[token_id] = {
            "username": username,
            "nickname": result["nickname"],
            "balance": result["money"],
            "game_token": result["game_token"],
            "session_data": result["session_data"],
            "sio": None,
            "game_connected": False,
            "session_id": None,
            "auto_bet": False,
            "base_bet": 10000,
            "current_bet": 10000,
            "x2_mode": False,
            "win_streak": 0,
            "profit_loss": 0,
            "target_profit": None,
            "current_prediction": None,
            "waiting_for_result": False,
            "has_bet_this_session": False,
            "current_result": None,
            "dices": None,
            "log": []
        }
        USERNAME_TO_TOKEN[username] = token_id

    threading.Thread(target=start_game_socket, args=(token_id, result["game_token"]), daemon=True).start()

    return jsonify({
        "success": True,
        "errorCode": "0",
        "server_token": token_id,
        "sessionKey": result["raw"].get("sessionKey"),
        "curLevel": result["session_data"].get("curLevel", 1),
        "nickname": result["nickname"],
        "money": result["money"],
        "session_data": result["session_data"]
    })


@app.route('/api/state')
def api_state():
    token_id = request.headers.get('X-Session-Token')
    with SESSION_LOCK:
        if not token_id or token_id not in USER_SESSIONS:
            return jsonify({"error": "unauthorized"}), 401
        session = USER_SESSIONS[token_id]
        weights_sorted = sorted(
            [(k, round(v, 2)) for k, v in GLOBAL_AI_WEIGHTS.items()],
            key=lambda x: -x[1]
        )[:10]

        return jsonify({
            "nickname": session["nickname"],
            "balance": session["balance"],
            "game_connected": session["game_connected"],
            "session_id": session["session_id"],
            "auto_bet": session["auto_bet"],
            "base_bet": session["base_bet"],
            "current_bet": session["current_bet"],
            "x2_mode": session["x2_mode"],
            "win_streak": session["win_streak"],
            "profit_loss": session["profit_loss"],
            "target_profit": session["target_profit"],
            "current_prediction": session["current_prediction"],
            "waiting_for_result": session["waiting_for_result"],
            "current_result": session["current_result"],
            "dices": session["dices"],
            "history": GLOBAL_HISTORY[-30:],
            "history_len": len(GLOBAL_HISTORY),
            "log": session["log"][-25:],
            "ai_weights": weights_sorted,
            "session_data": session["session_data"]
        })


@app.route('/api/settings', methods=['POST'])
def api_settings():
    token_id = request.headers.get('X-Session-Token')
    if not token_id or token_id not in USER_SESSIONS:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json or {}
    with SESSION_LOCK:
        if token_id not in USER_SESSIONS:
            return jsonify({"error": "session expired"}), 401
        session = USER_SESSIONS[token_id]

        if 'auto_bet' in data:
            session["auto_bet"] = bool(data["auto_bet"])
            add_log(token_id, "🟢 BẬT Auto Cược" if data["auto_bet"] else "🔴 TẮT Auto Cược")
        if 'base_bet' in data:
            try:
                val = max(1000, int(data["base_bet"]))
                session["base_bet"] = val
                add_log(token_id, f"⚙️ Vốn gốc: {val:,}")
            except:
                pass
        if 'x2_mode' in data:
            session["x2_mode"] = bool(data["x2_mode"])
            add_log(token_id, "🔥 BẬT X2" if data["x2_mode"] else "🔴 TẮT X2")
        if 'target_profit' in data:
            try:
                val = int(data["target_profit"])
                session["target_profit"] = val if val > 0 else None
            except:
                session["target_profit"] = None

    return jsonify({"ok": True})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    token_id = request.headers.get('X-Session-Token')
    with SESSION_LOCK:
        if token_id and token_id in USER_SESSIONS:
            session = USER_SESSIONS[token_id]
            username = session["username"]
            try:
                if session.get("sio"):
                    session["sio"].disconnect()
            except:
                pass
            del USER_SESSIONS[token_id]
            if USERNAME_TO_TOKEN.get(username) == token_id:
                del USERNAME_TO_TOKEN[username]
    return jsonify({"ok": True})


# ==========================================
# HTML TEMPLATE
# ==========================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover" />
<title>AUTO CƯỢC LC79 — HuyDaiXuVN</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.2.0/crypto-js.min.js"></script>
<style>
  *{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  html,body{touch-action:manipulation;-webkit-text-size-adjust:100%;height:100%}
  :root{
    --primary:#e63946;--primary-2:#ff4d6d;--primary-dark:#b5172a;--accent:#ffb703;--gold:#f4b400;
    --ink:#0d1117;--muted:#6b7280;--line:#e5e7eb;--bg:#f6f7fb;--success:#10b981;--danger:#ef4444;
    --shadow-md:0 8px 24px rgba(15,23,42,0.06);--shadow-lg:0 20px 60px rgba(15,23,42,0.08);
  }
  body{font-family:'Plus Jakarta Sans',sans-serif;background:var(--bg);color:#1f2937;display:flex;flex-direction:column;min-height:100vh;-webkit-font-smoothing:antialiased;user-select:none}
  input,textarea{user-select:text}
  .header{background:rgba(255,255,255,0.9);backdrop-filter:saturate(180%) blur(14px);border-bottom:1px solid rgba(15,23,42,0.06);position:sticky;top:0;z-index:100}
  .header-inner{max-width:1280px;margin:0 auto;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px}
  .brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}
  .brand-mark{width:40px;height:40px;border-radius:11px;background:radial-gradient(circle at 30% 30%,#ff9a9e 0%,transparent 55%),linear-gradient(135deg,var(--primary-2),var(--primary-dark));display:grid;place-items:center;color:#fff;font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:12px;box-shadow:0 6px 16px rgba(230,57,70,0.35)}
  .brand-name strong{font-family:'Space Grotesk',sans-serif;font-size:14px;color:var(--ink)}
  .brand-name small{font-size:10px;letter-spacing:1.8px;color:var(--muted);text-transform:uppercase;font-weight:600}
  .header-right{display:flex;align-items:center;gap:10px}
  .user-chip{display:flex;align-items:center;gap:8px;padding:5px 12px 5px 5px;background:#fff;border:1px solid var(--line);border-radius:999px;font-size:13px;font-weight:600;color:var(--ink);max-width:200px}
  .user-chip .avatar{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));color:#fff;display:grid;place-items:center;font-size:11px;font-weight:700;text-transform:uppercase;flex-shrink:0}
  .btn-logout{padding:8px 14px;background:#fef2f2;color:var(--primary);border:1px solid #fecaca;border-radius:9px;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:all 0.2s}
  .btn-logout:hover{background:#fee2e2}
  .main{flex:1;display:grid;grid-template-columns:1fr 1fr;max-width:1180px;width:100%;margin:0 auto;padding:24px 20px;gap:32px;align-items:center}
  .brand-panel{position:relative;min-height:520px;border-radius:22px;padding:40px 36px;color:#fff;background:radial-gradient(circle at 20% 10%,rgba(255,183,3,0.18) 0%,transparent 40%),radial-gradient(circle at 90% 90%,rgba(255,77,109,0.25) 0%,transparent 45%),linear-gradient(150deg,#1a1f2e 0%,#0d1117 60%,#1a0a10 100%);overflow:hidden;display:flex;flex-direction:column;justify-content:space-between;box-shadow:var(--shadow-lg);isolation:isolate}
  .brand-panel::before{content:'';position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,0.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.035) 1px,transparent 1px);background-size:40px 40px;mask-image:radial-gradient(ellipse at 50% 0%,#000 30%,transparent 75%)}
  .brand-panel > *{position:relative;z-index:1}
  .badge-new{display:inline-flex;align-items:center;gap:7px;padding:5px 11px 5px 7px;border-radius:999px;font-size:11px;font-weight:600;background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.12);width:fit-content}
  .badge-new .dot{width:6px;height:6px;border-radius:50%;background:var(--success);box-shadow:0 0 0 3px rgba(16,185,129,0.25)}
  .brand-panel h1{font-family:'Space Grotesk',sans-serif;font-size:clamp(24px,3vw,36px);line-height:1.18;font-weight:700;letter-spacing:-0.7px;margin:18px 0 12px;max-width:440px}
  .brand-panel h1 .grad{background:linear-gradient(120deg,#ff4d6d 0%,#ffb703 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
  .brand-panel p.lead{font-size:14.5px;line-height:1.7;color:rgba(255,255,255,0.65);max-width:400px}
  .feature-list{display:grid;gap:10px;margin-top:24px}
  .feature-item{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:11px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06)}
  .feature-icon{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,rgba(255,77,109,0.25),rgba(255,183,3,0.2));display:grid;place-items:center;flex-shrink:0;color:#ffb703}
  .feature-item strong{display:block;font-size:13px;font-weight:600;color:#fff;margin-bottom:1px}
  .feature-item small{font-size:11.5px;color:rgba(255,255,255,0.5)}
  .login-panel{display:flex;justify-content:center;align-items:center}
  .login-card{width:100%;max-width:420px;background:#fff;border-radius:18px;padding:36px 30px 32px;border:1px solid var(--line);box-shadow:var(--shadow-md)}
  .login-card h2{font-family:'Space Grotesk',sans-serif;font-size:22px;font-weight:700;color:var(--ink);margin-bottom:5px}
  .login-card .subtitle{font-size:13.5px;color:var(--muted);margin-bottom:24px}
  .alert{display:none;align-items:flex-start;gap:9px;padding:11px 13px;border-radius:10px;font-size:13px;margin-bottom:16px}
  .alert.show{display:flex}
  .alert.error{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c}
  .field{margin-bottom:16px}
  .field label{display:block;font-size:12.5px;font-weight:600;color:#374151;margin-bottom:6px}
  .input-box{position:relative}
  .input-box .lead{position:absolute;left:13px;top:50%;transform:translateY(-50%);width:17px;height:17px;color:#9ca3af;pointer-events:none}
  .input-box input{width:100%;padding:12px 42px 12px 40px;font-size:14px;font-family:inherit;color:var(--ink);background:#fff;border:1.5px solid #e5e7eb;border-radius:10px;outline:none;transition:all 0.2s;font-weight:500}
  .input-box input:focus{border-color:var(--primary);box-shadow:0 0 0 4px rgba(230,57,70,0.1)}
  .btn-eye{position:absolute;right:6px;top:50%;transform:translateY(-50%);width:30px;height:30px;border-radius:7px;border:none;background:transparent;color:#9ca3af;cursor:pointer;display:grid;place-items:center}
  .btn-eye:hover{color:var(--primary);background:#fef2f2}
  .remember{display:inline-flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:#4b5563;margin-bottom:20px;user-select:none}
  .remember input{position:absolute;opacity:0;pointer-events:none}
  .remember .box{width:17px;height:17px;border-radius:4px;border:1.5px solid #d1d5db;display:grid;place-items:center;transition:all 0.2s;background:#fff}
  .remember .box svg{width:10px;height:10px;color:#fff;opacity:0;transform:scale(0.6);transition:all 0.2s}
  .remember input:checked + .box{background:var(--primary);border-color:var(--primary)}
  .remember input:checked + .box svg{opacity:1;transform:scale(1)}
  .btn-submit{width:100%;padding:13px;font-size:14.5px;font-weight:600;font-family:inherit;color:#fff;background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));border:none;border-radius:10px;cursor:pointer;transition:all 0.25s;box-shadow:0 5px 16px rgba(230,57,70,0.32);display:flex;align-items:center;justify-content:center;gap:8px}
  .btn-submit:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 8px 22px rgba(230,57,70,0.42)}
  .btn-submit:disabled{cursor:not-allowed;opacity:0.9}
  .spinner{width:15px;height:15px;border:2px solid rgba(255,255,255,0.35);border-top-color:#fff;border-radius:50%;animation:spin 0.7s linear infinite;display:none}
  .btn-submit.loading .spinner{display:block}
  @keyframes spin{to{transform:rotate(360deg)}}

  /* DASHBOARD */
  .dash{flex:1;max-width:1000px;width:100%;margin:0 auto;padding:20px;display:flex;flex-direction:column;gap:16px}
  .welcome-card{background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));color:#fff;padding:24px 26px;border-radius:18px;display:flex;align-items:center;gap:16px;box-shadow:0 10px 26px rgba(230,57,70,0.28);position:relative;overflow:hidden}
  .welcome-card::after{content:'';position:absolute;width:220px;height:220px;border-radius:50%;background:rgba(255,255,255,0.15);top:-90px;right:-70px}
  .welcome-avatar{width:62px;height:62px;border-radius:16px;background:rgba(255,255,255,0.22);display:grid;place-items:center;font-size:24px;font-weight:800;font-family:'Space Grotesk',sans-serif;border:2px solid rgba(255,255,255,0.3);flex-shrink:0;position:relative;z-index:1;text-transform:uppercase}
  .welcome-info{position:relative;z-index:1;min-width:0;flex:1}
  .welcome-info .greet{font-size:12px;opacity:0.85;margin-bottom:1px;font-weight:500}
  .welcome-info h2{font-family:'Space Grotesk',sans-serif;font-size:20px;font-weight:700;margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .level-badge{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;background:linear-gradient(135deg,#ffb703,#ff8c00);border-radius:999px;font-size:11px;font-weight:700;color:#1a1f2e;text-transform:uppercase;letter-spacing:0.5px;margin-right:6px}
  .connection-status{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:999px;font-size:11px;font-weight:600}
  .connection-status.connected{background:rgba(16,185,129,0.2);color:#a7f3d0}
  .connection-status.disconnected{background:rgba(239,68,68,0.2);color:#fecaca}
  .connection-status .dot{width:6px;height:6px;border-radius:50%;background:currentColor;animation:pulse 1.5s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}

  .stats-grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
  .stat-card{background:#fff;border-radius:16px;padding:18px 18px 16px;border:1px solid var(--line);box-shadow:var(--shadow-md);border-left:4px solid var(--primary);position:relative}
  .stat-card.win{border-left-color:var(--success)}
  .stat-card.loss{border-left-color:var(--danger)}
  .stat-card.gold{border-left-color:var(--gold)}
  .stat-label{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px}
  .stat-value{font-family:'Space Grotesk',sans-serif;font-size:clamp(20px,2.5vw,26px);font-weight:700;color:var(--ink);letter-spacing:-0.5px;display:flex;align-items:center;gap:6px;word-break:break-all}
  .stat-value.win{color:var(--success)}
  .stat-value.loss{color:var(--danger)}
  .stat-unit{font-size:11px;font-weight:600;color:var(--muted);margin-left:2px}

  .prediction-panel{background:linear-gradient(135deg,#1a1f2e 0%,#2d1b2e 100%);color:#fff;border-radius:18px;padding:24px;position:relative;overflow:hidden}
  .prediction-panel::after{content:'';position:absolute;width:280px;height:280px;border-radius:50%;background:radial-gradient(circle,rgba(255,183,3,0.15),transparent 70%);top:-100px;right:-100px}
  .pred-session{font-size:12px;opacity:0.7;margin-bottom:8px;font-family:'Space Grotesk',sans-serif;letter-spacing:0.5px;position:relative;z-index:1}
  .pred-value{font-size:48px;font-weight:800;font-family:'Space Grotesk',sans-serif;letter-spacing:-1.5px;position:relative;z-index:1}
  .pred-value.tai{color:#4dabf7;text-shadow:0 0 24px rgba(77,171,247,0.55)}
  .pred-value.xiu{color:#ff6b6b;text-shadow:0 0 24px rgba(255,107,107,0.55)}
  .pred-value.unknown{color:#9ca3af;font-size:22px;letter-spacing:0}
  .pred-result-line{margin-top:10px;font-size:13px;opacity:0.75;position:relative;z-index:1}
  .pred-result-line b{font-weight:700}
  .history-strip{display:flex;flex-wrap:wrap;gap:6px;margin-top:16px;position:relative;z-index:1;max-height:100px;overflow-y:auto}
  .history-chip{width:30px;height:30px;border-radius:8px;display:grid;place-items:center;font-size:13px;font-weight:800;font-family:'Space Grotesk',sans-serif;flex-shrink:0}
  .history-chip.tai{background:rgba(77,171,247,0.2);color:#4dabf7;border:1px solid rgba(77,171,247,0.4)}
  .history-chip.xiu{background:rgba(255,107,107,0.2);color:#ff6b6b;border:1px solid rgba(255,107,107,0.4)}

  .card{background:#fff;border-radius:16px;padding:22px;border:1px solid var(--line);box-shadow:var(--shadow-md)}
  .card h3{font-family:'Space Grotesk',sans-serif;font-size:15px;font-weight:700;color:var(--ink);margin-bottom:16px;display:flex;align-items:center;gap:8px}

  .setting-row{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 0;border-bottom:1px solid #f0f2f5}
  .setting-row:last-child{border-bottom:none}
  .setting-row .info{flex:1;min-width:0}
  .setting-row label{font-size:14px;font-weight:600;color:var(--ink);display:block;cursor:pointer}
  .setting-row small{display:block;font-size:11.5px;color:var(--muted);font-weight:400;margin-top:3px;line-height:1.4}
  .setting-input{width:140px;padding:9px 12px;border:1.5px solid var(--line);border-radius:8px;font-size:14px;font-weight:600;text-align:right;font-family:'Space Grotesk',sans-serif;transition:border 0.15s}
  .setting-input:focus{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px rgba(230,57,70,0.08)}
  .toggle-switch{position:relative;width:48px;height:26px;background:#e5e7eb;border-radius:999px;cursor:pointer;transition:background 0.2s;border:none;padding:0;flex-shrink:0}
  .toggle-switch::after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;background:#fff;border-radius:50%;box-shadow:0 1px 3px rgba(0,0,0,0.2);transition:transform 0.2s}
  .toggle-switch.on{background:linear-gradient(135deg,var(--primary-2),var(--primary-dark))}
  .toggle-switch.on::after{transform:translateX(22px)}

  .weights-list{display:grid;gap:6px}
  .weight-row{display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:8px;background:#f8f9fb;font-size:13px}
  .weight-name{flex:0 0 130px;color:var(--ink);font-weight:600;font-family:'Space Grotesk',sans-serif;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .weight-bar{flex:1;height:6px;background:#e5e7eb;border-radius:999px;overflow:hidden;min-width:40px}
  .weight-bar-fill{height:100%;background:linear-gradient(90deg,var(--primary-2),var(--accent));border-radius:999px;transition:width 0.4s}
  .weight-value{font-size:12px;color:var(--primary);font-weight:700;min-width:42px;text-align:right;font-family:'Space Grotesk',sans-serif}

  .log-list{display:grid;gap:4px;max-height:340px;overflow-y:auto;font-family:'Consolas','Monaco',monospace;font-size:12px}
  .log-item{padding:7px 10px;border-radius:6px;background:#f8f9fb;display:flex;gap:10px;border-left:2px solid #e5e7eb}
  .log-item.win{background:#ecfdf5;border-left-color:var(--success)}
  .log-item.loss{background:#fef2f2;border-left-color:var(--danger)}
  .log-time{color:var(--muted);flex-shrink:0;font-weight:600}
  .log-msg{color:#1f2937;word-break:break-word}

  .x2-badge{display:inline-block;padding:2px 7px;border-radius:5px;background:linear-gradient(135deg,#ffb703,#ff8c00);color:#1a1f2e;font-size:10px;font-weight:800;margin-left:6px;letter-spacing:0.5px}

  .footer{background:#fff;border-top:1px solid var(--line);padding:18px 20px;margin-top:auto}
  .footer-inner{max-width:1280px;margin:0 auto;text-align:center}
  .copyright{font-size:12.5px;color:var(--muted)}
  .copyright b{background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;font-weight:700}

  @media (max-width:900px){
    .main{grid-template-columns:1fr;padding:18px 16px;gap:20px}
    .brand-panel{min-height:auto;padding:28px 24px;border-radius:16px}
    .feature-list{display:none}
    .brand-panel h1{font-size:22px;margin:14px 0 10px}
    .brand-panel p.lead{font-size:13.5px}
    .stats-grid-4{grid-template-columns:repeat(2,1fr)}
    .pred-value{font-size:36px}
  }
  @media (max-width:720px){
    .welcome-card{padding:20px;gap:14px}
    .welcome-avatar{width:52px;height:52px;font-size:20px}
    .welcome-info h2{font-size:17px}
    .login-card{padding:30px 22px 26px}
    .login-card h2{font-size:20px}
  }
  @media (max-width:480px){
    .header-inner{padding:10px 14px}
    .user-chip span{display:none}
    .brand-name small{font-size:9px}
    .dash{padding:14px;gap:12px}
    .stat-card{padding:14px 16px}
    .stat-value{font-size:20px}
    .stats-grid-4{grid-template-columns:1fr}
    .pred-value{font-size:32px}
    .setting-row{flex-wrap:wrap}
    .setting-input{width:100%}
    .weight-name{flex:0 0 90px}
  }
</style>
</head>
<body>

<!-- LOGIN VIEW -->
<div id="loginView">
  <header class="header">
    <div class="header-inner">
      <a href="#" class="brand">
        <div class="brand-mark">LC79</div>
        <div class="brand-name"><strong>AUTO CƯỢC LC79</strong><small>Automation System</small></div>
      </a>
    </div>
  </header>
  <main class="main">
    <section class="brand-panel">
      <div>
        <div class="badge-new"><span class="dot"></span>Hệ thống AI 35 lõi đang hoạt động</div>
        <h1>Đăng nhập để bước vào<br><span class="grad">kỷ nguyên tự động hóa</span></h1>
        <p class="lead">Dự đoán Tài Xỉu bằng 35 lõi AI thích ứng — tự động vào tiền, nhân đôi khi thắng, chốt lãi thông minh, quản lý vốn chuyên nghiệp.</p>
        <div class="feature-list">
          <div class="feature-item">
            <div class="feature-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg></div>
            <div><strong>Bảo mật MD5</strong><small>Mật khẩu mã hóa 1 chiều</small></div>
          </div>
          <div class="feature-item">
            <div class="feature-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></div>
            <div><strong>35 lõi AI thích ứng</strong><small>Exponential Weighting</small></div>
          </div>
          <div class="feature-item">
            <div class="feature-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></div>
            <div><strong>Auto Cược + X2</strong><small>Tự động hóa toàn bộ</small></div>
          </div>
        </div>
      </div>
    </section>
    <section class="login-panel">
      <div class="login-card">
        <h2>Chào mừng trở lại 👋</h2>
        <p class="subtitle">Đăng nhập tài khoản để tiếp tục</p>
        <div class="alert error" id="alertBox">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <span id="alertText"></span>
        </div>
        <form id="loginForm" autocomplete="off" novalidate>
          <div class="field">
            <label for="username">Tên đăng nhập</label>
            <div class="input-box">
              <input type="text" id="username" placeholder="Nhập tên đăng nhập" required />
              <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
          </div>
          <div class="field">
            <label for="password">Mật khẩu</label>
            <div class="input-box">
              <input type="password" id="password" placeholder="Nhập mật khẩu" required />
              <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <button type="button" class="btn-eye" id="togglePass">
                <svg id="eyeIcon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              </button>
            </div>
          </div>
          <label class="remember">
            <input type="checkbox" id="remember" />
            <span class="box"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span>
            Ghi nhớ đăng nhập
          </label>
          <button type="submit" class="btn-submit" id="btnLogin"><span class="spinner"></span><span class="btn-text">Đăng nhập</span></button>
        </form>
      </div>
    </section>
  </main>
  <footer class="footer"><div class="footer-inner"><div class="copyright">© 2025 AUTO CƯỢC LC79 — Bản quyền thuộc về <b>HuyDaiXuVN</b></div></div></footer>
</div>

<!-- DASHBOARD VIEW -->
<div id="dashboardView" style="display:none">
  <header class="header">
    <div class="header-inner">
      <a href="#" class="brand">
        <div class="brand-mark">LC79</div>
        <div class="brand-name"><strong>AUTO CƯỢC LC79</strong><small>Dashboard</small></div>
      </a>
      <div class="header-right">
        <div class="user-chip"><div class="avatar" id="userAvatar">U</div><span id="userChipName">User</span></div>
        <button class="btn-logout" id="btnLogout">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          Đăng xuất
        </button>
      </div>
    </div>
  </header>
  <main class="dash">
    <div class="welcome-card">
      <div class="welcome-avatar" id="welcomeAvatar">U</div>
      <div class="welcome-info">
        <div class="greet">Xin chào, chào mừng trở lại!</div>
        <h2 id="welcomeName">nickname</h2>
        <div>
          <span class="level-badge" id="levelBadge">★ LV.1</span>
          <span class="connection-status disconnected" id="connStatus"><span class="dot"></span><span id="connText">Đang kết nối...</span></span>
        </div>
      </div>
    </div>

    <div class="stats-grid-4">
      <div class="stat-card">
        <div class="stat-label">💰 Số dư VIN</div>
        <div class="stat-value" id="balanceValue">0</div>
      </div>
      <div class="stat-card" id="plCard">
        <div class="stat-label">📈 Lãi/Lỗ</div>
        <div class="stat-value" id="plValue">0</div>
      </div>
      <div class="stat-card gold">
        <div class="stat-label">🔥 Chuỗi thắng</div>
        <div class="stat-value" id="streakValue">0</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">💵 Cược hiện tại</div>
        <div class="stat-value"><span id="betValue">0</span><span class="x2-badge" id="x2Badge" style="display:none">X2</span></div>
      </div>
    </div>

    <div class="prediction-panel">
      <div class="pred-session">PHIÊN #<span id="sessionId">—</span></div>
      <div class="pred-value unknown" id="predValue">Đang chờ dữ liệu...</div>
      <div class="pred-result-line">Kết quả gần nhất: <b id="lastResult">—</b></div>
      <div class="history-strip" id="historyStrip"></div>
    </div>

    <div class="card">
      <h3>⚙️ Cài đặt Auto Cược</h3>
      <div class="setting-row">
        <div class="info">
          <label for="baseBet">Số tiền auto cược mỗi phiên</label>
          <small>Vốn cơ bản cho mỗi phiên (VIN)</small>
        </div>
        <input type="number" class="setting-input" id="baseBet" value="10000" min="1000" step="1000" />
      </div>
      <div class="setting-row">
        <div class="info">
          <label>Bật/Tắt Auto Cược</label>
          <small>Bot tự động đặt cược theo tín hiệu AI</small>
        </div>
        <button class="toggle-switch" id="autoBetToggle" aria-label="Auto Bet"></button>
      </div>
      <div class="setting-row">
        <div class="info">
          <label>X2 (Nhân đôi số tiền khi thắng)</label>
          <small>Thắng 1k → cược 2k. Thắng tiếp vẫn 2k (không x4). Thua → quay về 1k.</small>
        </div>
        <button class="toggle-switch" id="x2Toggle" aria-label="X2 Mode"></button>
      </div>
      <div class="setting-row">
        <div class="info">
          <label for="targetProfit">Target chốt lãi</label>
          <small>Bot tự tắt khi đạt lợi nhuận. Đặt 0 = tắt.</small>
        </div>
        <input type="number" class="setting-input" id="targetProfit" value="0" min="0" step="10000" />
      </div>
    </div>

    <div class="card">
      <h3>🧠 TOP 10 Lõi AI dẫn đầu</h3>
      <div class="weights-list" id="weightsList"><div style="color:var(--muted);font-size:13px;text-align:center;padding:20px">Đang tải...</div></div>
    </div>

    <div class="card">
      <h3>📋 Nhật ký hoạt động</h3>
      <div class="log-list" id="logList"><div style="color:var(--muted);font-size:13px;text-align:center;padding:20px">Chưa có hoạt động</div></div>
    </div>
  </main>
  <footer class="footer"><div class="footer-inner"><div class="copyright">© 2025 AUTO CƯỢC LC79 — Bản quyền thuộc về <b>HuyDaiXuVN</b></div></div></footer>
</div>

<script>
const $ = id => document.getElementById(id);
let SERVER_TOKEN = null;
let POLL_TIMER = null;
let LAST_LOG_LEN = 0;

function fmt(v){
  if(v===null||v===undefined||v==='') return '0';
  const n = Number(v);
  if(isNaN(n)) return String(v);
  return new Intl.NumberFormat('vi-VN').format(n);
}
function showError(msg){ $('alertText').textContent = msg; $('alertBox').classList.add('show'); }
function hideError(){ $('alertBox').classList.remove('show'); }

// Chống zoom
let lastTouch=0;
document.addEventListener('touchend',e=>{const now=Date.now();if(now-lastTouch<=300)e.preventDefault();lastTouch=now;},{passive:false});
document.addEventListener('touchmove',e=>{if(e.touches.length>1)e.preventDefault();},{passive:false});

// Ẩn/hiện mật khẩu
const eyeOpen=`<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>`;
const eyeClosed=`<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>`;
$('togglePass').addEventListener('click',()=>{
  const pw=$('password'); const show=pw.type==='password';
  pw.type=show?'text':'password';
  $('eyeIcon').innerHTML=show?eyeClosed:eyeOpen;
});

const savedUser = localStorage.getItem('lc79_user');
if(savedUser){ $('username').value = savedUser; $('remember').checked = true; }

// LOGIN
$('loginForm').addEventListener('submit', async (e)=>{
  e.preventDefault(); hideError();
  const username = $('username').value.trim();
  const password = $('password').value;
  if(!username||!password){ showError('Vui lòng nhập đầy đủ thông tin'); return; }

  const btn = $('btnLogin');
  btn.classList.add('loading'); btn.disabled = true;

  try {
    const res = await fetch('/api/login',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ username, password: CryptoJS.MD5(password).toString() })
    });
    const data = await res.json();

    if(data.success){
      SERVER_TOKEN = data.server_token;
      if($('remember').checked) localStorage.setItem('lc79_user', username);
      else localStorage.removeItem('lc79_user');

      localStorage.setItem('lc79_server_token', SERVER_TOKEN);
      showDashboard(data);
      startPolling();
    } else {
      showError(data.message || 'Đăng nhập thất bại');
    }
  } catch(err){
    console.error(err);
    showError('Không thể kết nối server');
  } finally {
    btn.classList.remove('loading'); btn.disabled = false;
  }
});

function showDashboard(loginData){
  $('loginView').style.display = 'none';
  $('dashboardView').style.display = 'block';

  const sd = loginData.session_data || {};
  const nick = loginData.nickname || sd.nickname || 'User';
  const initial = nick.charAt(0).toUpperCase();

  $('userAvatar').textContent = initial;
  $('userChipName').textContent = nick;
  $('welcomeAvatar').textContent = initial;
  $('welcomeName').textContent = nick;
  $('levelBadge').textContent = `★ LV.${loginData.curLevel || 1}`;
  $('balanceValue').textContent = fmt(loginData.money);
}

// LOGOUT
$('btnLogout').addEventListener('click', async ()=>{
  try {
    await fetch('/api/logout',{method:'POST',headers:{'X-Session-Token':SERVER_TOKEN}});
  } catch(e){}
  stopPolling();
  localStorage.removeItem('lc79_server_token');
  SERVER_TOKEN = null;
  $('dashboardView').style.display = 'none';
  $('loginView').style.display = 'block';
  $('password').value = '';
  hideError();
});

// RESTORE SESSION
(function restore(){
  const saved = localStorage.getItem('lc79_server_token');
  if(!saved) return;
  SERVER_TOKEN = saved;
  fetch('/api/state',{headers:{'X-Session-Token':saved}})
    .then(r=>r.ok?r.json():null)
    .then(state=>{
      if(state){
        const sd = state.session_data || {};
        showDashboard({nickname:state.nickname, money:state.balance, curLevel:sd.curLevel||1, session_data:sd});
        startPolling();
      } else {
        localStorage.removeItem('lc79_server_token');
        SERVER_TOKEN = null;
      }
    })
    .catch(()=>{ localStorage.removeItem('lc79_server_token'); SERVER_TOKEN=null; });
})();

// ===================== POLLING =====================
function startPolling(){
  if(POLL_TIMER) return;
  pollState();
  POLL_TIMER = setInterval(pollState, 1200);
}
function stopPolling(){
  if(POLL_TIMER){ clearInterval(POLL_TIMER); POLL_TIMER = null; }
}

async function pollState(){
  if(!SERVER_TOKEN) return;
  try {
    const res = await fetch('/api/state',{headers:{'X-Session-Token':SERVER_TOKEN}});
    if(!res.ok){
      if(res.status === 401){
        // Session hết hạn
        stopPolling();
        localStorage.removeItem('lc79_server_token');
        SERVER_TOKEN = null;
        $('dashboardView').style.display='none';
        $('loginView').style.display='block';
      }
      return;
    }
    const state = await res.json();
    updateDashboard(state);
  } catch(e){ /* ignore */ }
}

function updateDashboard(s){
  // Balance
  $('balanceValue').textContent = fmt(s.balance);

  // P/L
  const plEl = $('plValue');
  plEl.textContent = (s.profit_loss >= 0 ? '+' : '') + fmt(s.profit_loss);
  plEl.className = 'stat-value ' + (s.profit_loss >= 0 ? 'win' : 'loss');
  $('plCard').className = 'stat-card ' + (s.profit_loss >= 0 ? 'win' : 'loss');

  // Streak
  $('streakValue').textContent = s.win_streak;

  // Current bet
  $('betValue').textContent = fmt(s.current_bet);
  $('x2Badge').style.display = (s.x2_mode && s.win_streak >= 1) ? 'inline-block' : 'none';

  // Connection status
  const cs = $('connStatus');
  if(s.game_connected){
    cs.className = 'connection-status connected';
    $('connText').textContent = 'Đã kết nối';
  } else {
    cs.className = 'connection-status disconnected';
    $('connText').textContent = 'Đang kết nối...';
  }

  // Session ID
  $('sessionId').textContent = s.session_id || '—';

  // Prediction
  const pv = $('predValue');
  if(s.current_prediction){
    pv.textContent = s.current_prediction === 'TAI' ? '🔵 TÀI' : '🔴 XỈU';
    pv.className = 'pred-value ' + (s.current_prediction === 'TAI' ? 'tai' : 'xiu');
  } else if(s.history_len < 10){
    pv.textContent = `Thu thập dữ liệu (${s.history_len}/10)...`;
    pv.className = 'pred-value unknown';
  } else {
    pv.textContent = 'Đang chờ phiên mới...';
    pv.className = 'pred-value unknown';
  }

  // Latest result
  if(s.current_result && s.dices){
    $('lastResult').textContent = `${s.current_result} (${s.dices.join('-')})`;
  } else {
    $('lastResult').textContent = '—';
  }

  // History strip
  const strip = $('historyStrip');
  strip.innerHTML = (s.history || []).slice().reverse().map(r=>{
    const cls = r === 'TAI' ? 'tai' : 'xiu';
    const label = r === 'TAI' ? 'T' : 'X';
    return `<div class="history-chip ${cls}">${label}</div>`;
  }).join('');

  // Settings (chỉ update nếu chưa focus)
  if(document.activeElement !== $('baseBet')){
    if(!$('baseBet').value || $('baseBet').value === '10000' || document.activeElement !== $('baseBet'))
      $('baseBet').value = s.base_bet;
  }
  if(document.activeElement !== $('targetProfit')){
    $('targetProfit').value = s.target_profit || 0;
  }
  $('autoBetToggle').classList.toggle('on', s.auto_bet);
  $('x2Toggle').classList.toggle('on', s.x2_mode);

  // AI weights
  const wl = $('weightsList');
  if(s.ai_weights && s.ai_weights.length){
    const maxW = s.ai_weights[0][1] || 1;
    wl.innerHTML = s.ai_weights.map(([k,v])=>{
      const pct = Math.min(100, (v/maxW)*100);
      return `<div class="weight-row">
        <div class="weight-name">${k}</div>
        <div class="weight-bar"><div class="weight-bar-fill" style="width:${pct}%"></div></div>
        <div class="weight-value">${v.toFixed(1)}</div>
      </div>`;
    }).join('');
  }

  // Log
  const logList = $('logList');
  if(s.log && s.log.length){
    logList.innerHTML = s.log.slice().reverse().map(l=>{
      let cls = 'log-item';
      if(l.msg.includes('THẮNG') || l.msg.includes('ĐẠT TARGET')) cls += ' win';
      else if(l.msg.includes('THUA')) cls += ' loss';
      return `<div class="${cls}"><span class="log-time">${l.time}</span><span class="log-msg">${escapeHtml(l.msg)}</span></div>`;
    }).join('');
  } else {
    logList.innerHTML = '<div style="color:var(--muted);font-size:13px;text-align:center;padding:20px">Chưa có hoạt động</div>';
  }
}

function escapeHtml(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ===================== SETTINGS =====================
async function updateSetting(patch){
  if(!SERVER_TOKEN) return;
  try {
    await fetch('/api/settings',{
      method:'POST',
      headers:{'Content-Type':'application/json','X-Session-Token':SERVER_TOKEN},
      body:JSON.stringify(patch)
    });
    pollState();
  } catch(e){ console.error(e); }
}

$('autoBetToggle').addEventListener('click',()=>{
  const isOn = $('autoBetToggle').classList.contains('on');
  updateSetting({ auto_bet: !isOn });
});

$('x2Toggle').addEventListener('click',()=>{
  const isOn = $('x2Toggle').classList.contains('on');
  updateSetting({ x2_mode: !isOn });
});

let baseBetTimer = null;
$('baseBet').addEventListener('input',()=>{
  clearTimeout(baseBetTimer);
  baseBetTimer = setTimeout(()=>{
    const v = Math.max(1000, parseInt($('baseBet').value)||10000);
    updateSetting({ base_bet: v });
  }, 600);
});

let targetTimer = null;
$('targetProfit').addEventListener('input',()=>{
  clearTimeout(targetTimer);
  targetTimer = setTimeout(()=>{
    const v = Math.max(0, parseInt($('targetProfit').value)||0);
    updateSetting({ target_profit: v });
  }, 600);
});
</script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 LC79 AUTO WEB — 35 AI CORES + AUTO BET + X2")
    print("🌐 Truy cập: http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
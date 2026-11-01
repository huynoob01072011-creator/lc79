"""
⚡ ULTRA VIP V4 — Single File Edition
35 AI Cores · Live Accuracy · Confidence Gating · Kelly Sizing · Stop-Loss · Cooldown
Web UI · LC79 Manual Code · Auto Bet
"""
import os, hashlib, base64, json, logging, threading, time, random, math
import requests
import socketio as sio_client
from flask import Flask, request, jsonify, Response
from flask_socketio import SocketIO, join_room
from collections import deque
from datetime import datetime

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

# ============================================================
# FLASK + SOCKETIO
# ============================================================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'ultra-vip-v4-single-file')
webio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)

# ============================================================
# GLOBAL STATE
# ============================================================
GLOBAL_HISTORY = deque(maxlen=2000)

GLOBAL_AI_WEIGHTS = {
    "trend": 1.0, "pattern": 1.0, "frequency": 1.0, "momentum": 1.0, "symmetry": 1.0,
    "alternating": 1.0, "fibonacci": 1.0, "chaos": 1.0, "shadow": 1.0,
    "markov1": 1.0, "markov2": 1.0, "markov3": 1.0,
    "rsi_indicator": 1.0, "macd_cross": 1.0, "pivot_reversal": 1.0, "cluster_3": 1.0,
    "parity": 1.0, "golden_ratio": 1.0, "quantum": 1.0,
    "anti_bait": 2.0, "smart_breaker": 2.0,
    "ngram_4": 1.5, "ngram_5": 1.5, "elliott_wave": 1.5,
    "contrarian": 2.0, "bollinger_bands": 1.5, "mean_reversion": 1.0,
    "mirror_reflection": 1.0, "martingale_trap": 1.5, "poisson_prob": 1.0,
    "harmonic_cycle": 1.0, "breakout_hunter": 1.5, "volume_fakeout": 1.5,
    "time_decay": 1.0, "neural_bias": 1.0, "twin_peaks": 1.0,
}

MODEL_ACCURACY = {
    m: {'correct': 0, 'total': 0, 'rec_correct': 0.0, 'rec_total': 0.0}
    for m in GLOBAL_AI_WEIGHTS
}

USERS = {}
GAME_CLIENTS = {}

# ============================================================
# USER STATE
# ============================================================
def new_user_state(uid):
    return {
        'uid': uid, 'nickname': None, 'token': None, 'balance': 0, 'logged_in': False,
        'auto_bet_enabled': False, 'notify_win': True, 'notify_lose': True,
        'base_bet': 10000, 'current_bet': 10000, 'x2_mode': False, 'win_streak': 0,
        'profit_loss': 0, 'target_profit': None, 'current_prediction': None,
        'has_bet_this_session': False, 'waiting_for_result': False,
        'session_id': None, 'last_predictions': {}, 'logs': deque(maxlen=300),
        'lc79_jwt': None, 'lc79_api': 'https://api.lc79.luxury/v1/code/redeem',
        'lc79_strip4': True, 'last_dices': [0, 0, 0], 'last_result': None,
        # ---- V4 ----
        'current_confidence': 0.0,
        'confidence_details': {},
        'confidence_threshold': 0.62,
        'consecutive_losses': 0,
        'cooldown_remaining': 0,
        'stop_loss': 500000,
        'skip_reason': None,
        'kelly_size': 0,
    }

def get_user():
    uid = request.headers.get('X-Client-Id') or request.args.get('client_id') or 'default'
    if uid not in USERS:
        USERS[uid] = new_user_state(uid)
    return USERS[uid], uid

def add_log(uid, message, level='info'):
    if uid not in USERS: return
    ts = datetime.now().strftime('%H:%M:%S')
    entry = {'ts': ts, 'msg': message, 'level': level}
    USERS[uid]['logs'].append(entry)
    webio.emit('log', entry, room=uid)

# ============================================================
# 35 AI CORES (base models)
# ============================================================
def compute_all_models(history):
    mp = {}
    last = history[-1]
    opp = "XIU" if last == "TAI" else "TAI"
    rs = "".join(["T" if x == "TAI" else "X" for x in history])
    streak = len(rs) - len(rs.rstrip(rs[-1]))

    mp["trend"] = last if history[-5:].count(last) >= 3 else opp
    mp["pattern"] = opp if rs.endswith("TXTX") or rs.endswith("TTXX") else last

    t1 = {"TAI": {"TAI": 0, "XIU": 0}, "XIU": {"TAI": 0, "XIU": 0}}
    for i in range(len(history) - 1):
        t1[history[i]][history[i+1]] += 1
    mp["markov1"] = "TAI" if t1[last]["TAI"] > t1[last]["XIU"] else "XIU"
    mp["markov2"] = "TAI" if history[-2:] == ["TAI", "TAI"] else "XIU"
    mp["markov3"] = opp if history[-3:] == [last]*3 else mp["markov2"]

    mp["frequency"] = "XIU" if history[-20:].count("TAI") > 10 else "TAI"
    mp["momentum"] = "TAI" if sum([i+1 if r == "TAI" else -(i+1) for i, r in enumerate(history[-5:])]) > 0 else "XIU"
    mp["symmetry"] = opp if len(rs) >= 6 and rs[-6:-3] == rs[-3:][::-1] else last
    mp["alternating"] = opp
    mp["fibonacci"] = opp if streak in [3, 5, 8, 13] else last
    mp["chaos"] = opp if sum(1 for i in range(len(rs[-10:]) - 1) if rs[-10:][i] != rs[-10:][i+1]) >= 7 else last
    mp["shadow"] = "TAI" if history[-50:].count("TAI") < 25 else "XIU"

    rsi = rs[-10:].count("T")
    mp["rsi_indicator"] = "XIU" if rsi >= 7 else ("TAI" if rsi <= 3 else last)
    mp["macd_cross"] = "TAI" if rs[-3:].count("T") > (rs[-9:].count("T") / 3) else "XIU"
    mp["pivot_reversal"] = last if len(history) >= 3 and history[-3] == history[-2] != history[-1] else last
    mp["cluster_3"] = "TAI" if rs[-3:] in ["TTT", "TXX", "XTX", "XXT"] else "XIU"
    mp["parity"] = opp if streak % 2 == 0 else last
    mp["golden_ratio"] = "TAI" if (history[-30:].count("TAI") / 30) < 0.618 else "XIU"
    mp["quantum"] = random.choice(["TAI", "XIU"])

    mp["anti_bait"] = opp if streak >= 5 or rs.endswith("TXTXT") else last
    mx = cur = 1
    for i in range(1, len(history)):
        if history[i] == history[i-1]: cur += 1
        else: mx = max(mx, cur); cur = 1
    mp["smart_breaker"] = opp if streak >= mx - 1 and streak >= 3 else last

    l4 = rs[-4:]; t_c4 = rs[:-1].count(l4 + "T"); x_c4 = rs[:-1].count(l4 + "X")
    mp["ngram_4"] = "TAI" if t_c4 > x_c4 else ("XIU" if x_c4 > t_c4 else opp)
    l5 = rs[-5:]; t_c5 = rs[:-1].count(l5 + "T"); x_c5 = rs[:-1].count(l5 + "X")
    mp["ngram_5"] = "TAI" if t_c5 > x_c5 else ("XIU" if x_c5 > t_c5 else opp)

    if rs.endswith("TXTXT"): mp["elliott_wave"] = last
    elif rs.endswith("TTXXTT"): mp["elliott_wave"] = "XIU"
    else: mp["elliott_wave"] = opp

    if streak in (4, 6): mp["contrarian"] = opp
    elif rs[-6:] == "TXTXTX": mp["contrarian"] = "XIU"
    else: mp["contrarian"] = last

    ma10 = rs[-10:].count("T") / 10.0
    mp["bollinger_bands"] = "XIU" if ma10 >= 0.8 else ("TAI" if ma10 <= 0.2 else last)

    t100 = history[-100:].count("TAI") if len(history) >= 100 else history.count("TAI")
    mp["mean_reversion"] = "TAI" if t100 < (len(history[-100:]) * 0.45) else "XIU"

    mp["mirror_reflection"] = ("TAI" if rs[-8] == "T" else "XIU") if len(rs) >= 8 else opp
    mp["martingale_trap"] = opp if streak in (3, 7) else last
    mp["poisson_prob"] = "TAI" if (history[-5:].count("TAI") % 2 == 1) else "XIU"
    mp["harmonic_cycle"] = history[-4] if len(history) >= 4 else opp
    mp["breakout_hunter"] = last if streak == 1 and len(history) >= 3 and history[-2] == history[-3] else opp
    mp["volume_fakeout"] = last if len(rs) >= 5 and rs[-5:] in ["TTTXT", "XXXTX"] else opp
    mp["time_decay"] = opp
    mp["neural_bias"] = "TAI" if history[-7:].count("TAI") > 3 else "XIU"
    mp["twin_peaks"] = opp if rs.endswith("TTXTT") or rs.endswith("XXTXX") else last

    return mp


# ============================================================
# V4 PREDICTION + CONFIDENCE
# ============================================================
def make_prediction(uid):
    """Returns (pred, confidence, details)"""
    state = USERS[uid]
    history = list(GLOBAL_HISTORY)

    if len(history) < 15:
        return None, 0.0, {"reason": f"Chưa đủ data ({len(history)}/15)"}

    model_preds = compute_all_models(history)
    state['last_predictions'] = model_preds

    score = {"TAI": 0.0, "XIU": 0.0}
    vote_count = {"TAI": 0, "XIU": 0}
    total_w = 0.0

    for m, p in model_preds.items():
        acc = MODEL_ACCURACY.get(m, {'rec_correct': 0, 'rec_total': 0})
        base_w = GLOBAL_AI_WEIGHTS.get(m, 1.0)
        if acc['rec_total'] >= 5:
            rec_acc = acc['rec_correct'] / acc['rec_total']
            acc_factor = max(0.2, rec_acc * 2)
        else:
            acc_factor = 0.7
        reliability = base_w * acc_factor
        score[p] += reliability
        vote_count[p] += 1
        total_w += reliability

    if total_w == 0:
        return None, 0.0, {"reason": "Không model nào vote"}

    pred = "TAI" if score["TAI"] > score["XIU"] else "XIU"
    other = "XIU" if pred == "TAI" else "TAI"

    margin = (score[pred] - score[other]) / total_w
    agree_pct = vote_count[pred] / len(model_preds)
    confidence = 0.5 * margin + 0.5 * agree_pct
    confidence = min(0.85, confidence * 1.3)

    if agree_pct < 0.55:
        confidence *= 0.7

    return pred, confidence, {
        "score": score, "votes": vote_count,
        "margin": round(margin, 3), "agree_pct": round(agree_pct, 3),
        "n_models": len(model_preds),
    }


def update_ai_weights(actual_result, uid=None):
    """V4: cập nhật trọng số dựa trên live accuracy (cửa sổ trượt 30)"""
    global GLOBAL_AI_WEIGHTS
    preds = None
    if uid and uid in USERS:
        preds = USERS[uid].get('last_predictions')
    else:
        for s in USERS.values():
            if s.get('last_predictions'):
                preds = s['last_predictions']; break
    if not preds: return

    for model, p in preds.items():
        acc = MODEL_ACCURACY[model]
        correct = (p == actual_result)
        acc['total'] += 1
        acc['rec_total'] += 1
        if correct:
            acc['correct'] += 1
            acc['rec_correct'] += 1

        if acc['rec_total'] > 30:
            acc['rec_correct'] *= 0.9
            acc['rec_total'] = 30.0

        if acc['rec_total'] >= 8:
            rec_acc = acc['rec_correct'] / acc['rec_total']
            edge = rec_acc - 0.5
            GLOBAL_AI_WEIGHTS[model] = max(0.1, min(5.0, 1.0 + edge * 8))


# ============================================================
# V4 RISK + KELLY
# ============================================================
def check_risk_limits(uid):
    s = USERS[uid]

    if s['stop_loss'] and s['profit_loss'] <= -s['stop_loss']:
        return False, f"STOP-LOSS chạm -{s['stop_loss']:,} Win"

    if s['target_profit'] is not None and s['profit_loss'] >= s['target_profit']:
        return False, f"TARGET chạm +{s['target_profit']:,} Win"

    if s['cooldown_remaining'] > 0:
        s['cooldown_remaining'] -= 1
        return False, f"Cooldown còn {s['cooldown_remaining']+1} phiên"

    if s['balance'] < 1000:
        return False, "Balance < 1000"

    return True, None


def calculate_bet_size(uid):
    s = USERS[uid]
    conf = s.get('current_confidence', 0)

    if conf < 0.5:
        return 0

    kelly = (conf * 1.98 - 1) / 0.98
    kelly = max(0.0, min(0.05, kelly * 0.25))

    bet = int(s['balance'] * kelly)
    bet = max(s['base_bet'], bet) if s['base_bet'] else bet
    bet = min(bet, int(s['balance'] * 0.05))
    bet = max(1000, bet)
    return bet


# ============================================================
# TELE68 LOGIN & WEBSOCKET
# ============================================================
def md5(s): return hashlib.md5(s.encode()).hexdigest()

def login_tele68(username, password):
    try:
        url = f"https://apifo88daigia.tele68.com/api?c=3&un={username}&pw={md5(password)}&cp=R&cl=R&pf=web&at="
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return {"_error": data.get('message', 'Sai thông tin đăng nhập')}
        sk = data["sessionKey"]
        sk += "=" * ((4 - len(sk) % 4) % 4)
        sd = json.loads(base64.b64decode(sk).decode('utf-8'))
        nickname = sd.get("nickname") or sd.get("nickName")
        r2 = requests.post(
            "https://wlb.tele68.com/v1/lobby/auth/login?cp=R&cl=R&pf=web&at=",
            headers={"authority": "wlb.tele68.com", "content-type": "application/json"},
            json={"nickName": nickname, "accessToken": data["accessToken"]}, timeout=12
        )
        lobby = r2.json()
        token = lobby.get("token")
        if not token:
            return {"_error": "Lobby không trả JWT"}
        return {"token": token, "nickname": nickname, "money": lobby.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e:
        return {"_error": f"Lỗi kết nối: {e}"}


def start_game_ws(uid):
    if uid in GAME_CLIENTS:
        try: GAME_CLIENTS[uid].disconnect()
        except: pass

    state = USERS[uid]
    client = sio_client.Client(reconnection=True, reconnection_attempts=20, logger=False, engineio_logger=False)
    GAME_CLIENTS[uid] = client

    @client.event(namespace='/txmd5')
    def connect():
        add_log(uid, "✅ Đã kết nối WebSocket game", 'success')
        webio.emit('status', {'connected': True}, room=uid)

    @client.event(namespace='/txmd5')
    def disconnect():
        add_log(uid, "⚠️ Mất kết nối WebSocket", 'warn')
        webio.emit('status', {'connected': False}, room=uid)

    @client.on('new-session', namespace='/txmd5')
    def on_new_session(data):
        state['session_id'] = data.get('id', '?')
        state['has_bet_this_session'] = False
        state['waiting_for_result'] = False

        # V4 prediction
        pred, conf, details = make_prediction(uid)
        state['current_prediction'] = pred
        state['current_confidence'] = conf
        state['confidence_details'] = details

        # Gating
        allowed, reason = check_risk_limits(uid)
        if pred is None:
            state['skip_reason'] = details.get('reason', 'Không có dự đoán')
            state['current_prediction'] = None
        elif not allowed:
            state['current_prediction'] = None
            state['skip_reason'] = reason
            add_log(uid, f"🛑 SKIP phiên: {reason}", 'warn')
        elif conf < state['confidence_threshold']:
            state['current_prediction'] = None
            state['skip_reason'] = f"Confidence {conf:.0%} < {state['confidence_threshold']:.0%}"
            add_log(uid, f"🛑 SKIP phiên: conf {conf:.0%} thấp", 'warn')
        else:
            state['skip_reason'] = None
            add_log(uid, f"🎯 AI chốt {pred} (conf {conf:.0%}, agree {details.get('agree_pct',0):.0%})", 'info')

        # Bet sizing
        if state['x2_mode'] and state['win_streak'] >= 1:
            kelly = calculate_bet_size(uid)
            state['current_bet'] = max(kelly, state['base_bet'] * 2)
        else:
            state['current_bet'] = calculate_bet_size(uid) or state['base_bet']
        state['kelly_size'] = state['current_bet']

        webio.emit('new_session', {
            'session_id': state['session_id'],
            'prediction': state['current_prediction'],
            'confidence': round(state['current_confidence'], 3),
            'confidence_details': details,
            'current_bet': state['current_bet'],
            'skip_reason': state['skip_reason'],
            'history_len': len(GLOBAL_HISTORY),
        }, room=uid)

    @client.on('tick-update', namespace='/txmd5')
    def on_tick(data):
        if data.get('state') == 'BETTING' and state['auto_bet_enabled'] and state['current_prediction']:
            if not state['has_bet_this_session']:
                try:
                    client.emit('bet', {
                        "type": state['current_prediction'],
                        "amount": state['current_bet']
                    }, namespace='/txmd5')
                    state['has_bet_this_session'] = True
                    state['waiting_for_result'] = True
                    add_log(uid, f"🚀 Đặt {state['current_bet']:,} Win → {state['current_prediction']}", 'bet')
                    webio.emit('bet_placed', {
                        'amount': state['current_bet'],
                        'type': state['current_prediction'],
                    }, room=uid)
                except Exception as e:
                    add_log(uid, f"❌ Lỗi đặt cược: {e}", 'error')

    @client.on('bet-result', namespace='/txmd5')
    def on_bet_result(data):
        if "postBalance" in data:
            state['balance'] = data["postBalance"]
            webio.emit('balance', {'balance': state['balance']}, room=uid)
        client.emit('get-current-my-info', None, namespace='/txmd5')

    @client.on('session-result', namespace='/txmd5')
    def on_result(data):
        result = data.get('resultTruyenThong', 'N/A')
        dices = data.get('dices', [0, 0, 0])
        state['last_dices'] = dices
        state['last_result'] = result

        if result in ("TAI", "XIU"):
            GLOBAL_HISTORY.append(result)
            update_ai_weights(result, uid)

        prediction = state['current_prediction']
        won = (prediction == result) if prediction else None

        if state['waiting_for_result'] and prediction:
            if won:
                win_amt = int(state['current_bet'] * 0.98)
                state['profit_loss'] += win_amt
                state['win_streak'] += 1
                state['consecutive_losses'] = 0
                add_log(uid, f"✅ THẮNG {result} — +{win_amt:,} Win (streak {state['win_streak']})", 'win')
                if state['notify_win']:
                    webio.emit('notify', {
                        'type': 'win', 'amount': win_amt, 'result': result,
                        'dices': dices, 'streak': state['win_streak'],
                    }, room=uid)
            else:
                state['profit_loss'] -= state['current_bet']
                state['win_streak'] = 0
                state['consecutive_losses'] += 1
                if state['consecutive_losses'] >= 3:
                    state['cooldown_remaining'] = 5
                    state['consecutive_losses'] = 0
                    add_log(uid, "🛑 THUA 3 liên tiếp → nghỉ 5 phiên", 'warn')
                add_log(uid, f"❌ THUA {result} — -{state['current_bet']:,} Win", 'lose')
                if state['notify_lose']:
                    webio.emit('notify', {
                        'type': 'lose', 'amount': -state['current_bet'],
                        'result': result, 'dices': dices,
                    }, room=uid)
            state['waiting_for_result'] = False

        webio.emit('result', {
            'result': result, 'dices': dices,
            'prediction': prediction, 'won': won,
            'profit_loss': state['profit_loss'],
            'win_streak': state['win_streak'],
            'balance': state['balance'],
            'consecutive_losses': state['consecutive_losses'],
            'cooldown_remaining': state['cooldown_remaining'],
            'history': list(GLOBAL_HISTORY)[-40:],
        }, room=uid)

    try:
        client.connect(
            'https://wtxmd52.tele68.com',
            socketio_path='txmd5/',
            namespaces=['/txmd5'],
            transports=['websocket'],
            auth={"token": state['token']},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        client.wait()
    except Exception as e:
        add_log(uid, f"❌ Lỗi WS: {e}", 'error')
        webio.emit('status', {'connected': False}, room=uid)

# ============================================================
# LC79 CODE
# ============================================================
def submit_lc79_code(jwt, code, api_url):
    if not jwt: return {"ok": False, "message": "Chưa có JWT"}
    if not code: return {"ok": False, "message": "Chưa có code"}
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://lc79.luxury",
        "Referer": "https://lc79.luxury/",
    }
    try:
        r = requests.post(api_url, json={"code": code}, headers=headers, timeout=15)
        txt = r.text[:400]
        try:
            j = r.json()
            ok = r.status_code == 200 and (j.get("success") or j.get("code") == 0 or j.get("status") == "ok" or j.get("data"))
            msg = j.get("message") or j.get("msg") or ("Thành công" if ok else "Thất bại")
            return {"ok": bool(ok), "message": msg, "raw": j}
        except Exception:
            return {"ok": r.status_code == 200, "message": f"[{r.status_code}] {txt}", "raw": txt}
    except Exception as e:
        return {"ok": False, "message": f"Lỗi request: {e}"}

# ============================================================
# ROUTES
# ============================================================
@app.route('/')
def index():
    return Response(HTML_PAGE, mimetype='text/html')

@app.route('/api/state', methods=['GET'])
def api_state():
    u, uid = get_user()
    return jsonify({
        'uid': uid, 'logged_in': u['logged_in'], 'nickname': u['nickname'],
        'balance': u['balance'], 'auto_bet_enabled': u['auto_bet_enabled'],
        'notify_win': u['notify_win'], 'notify_lose': u['notify_lose'],
        'base_bet': u['base_bet'], 'current_bet': u['current_bet'],
        'x2_mode': u['x2_mode'], 'win_streak': u['win_streak'],
        'profit_loss': u['profit_loss'], 'target_profit': u['target_profit'],
        'current_prediction': u['current_prediction'], 'session_id': u['session_id'],
        'history': list(GLOBAL_HISTORY)[-40:],
        'last_dices': u['last_dices'], 'last_result': u['last_result'],
        'lc79_jwt_set': bool(u['lc79_jwt']), 'lc79_api': u['lc79_api'],
        'lc79_strip4': u['lc79_strip4'],
        'logs': list(u['logs'])[-50:],
        'ai_top': sorted(GLOBAL_AI_WEIGHTS.items(), key=lambda x: x[1], reverse=True)[:10],
        # V4 fields
        'current_confidence': u.get('current_confidence', 0),
        'confidence_threshold': u.get('confidence_threshold', 0.62),
        'skip_reason': u.get('skip_reason'),
        'consecutive_losses': u.get('consecutive_losses', 0),
        'cooldown_remaining': u.get('cooldown_remaining', 0),
        'stop_loss': u.get('stop_loss', 500000),
        'confidence_details': u.get('confidence_details', {}),
    })

@app.route('/api/login', methods=['POST'])
def api_login():
    u, uid = get_user()
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return jsonify({'ok': False, 'error': 'Thiếu tài khoản hoặc mật khẩu'}), 400

    add_log(uid, f"🔄 Đang đăng nhập {username}...", 'info')
    result = login_tele68(username, password)
    if '_error' in result:
        add_log(uid, f"❌ Login fail: {result['_error']}", 'error')
        return jsonify({'ok': False, 'error': result['_error']}), 400

    u['token'] = result['token']
    u['nickname'] = result['nickname']
    u['balance'] = result['money']
    u['logged_in'] = True
    u['profit_loss'] = 0
    u['win_streak'] = 0
    u['consecutive_losses'] = 0
    u['cooldown_remaining'] = 0
    add_log(uid, f"✅ Login OK: {result['nickname']} — {result['money']:,} Win", 'success')

    threading.Thread(target=start_game_ws, args=(uid,), daemon=True).start()
    return jsonify({'ok': True, 'nickname': result['nickname'], 'balance': result['money']})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    u, uid = get_user()
    if uid in GAME_CLIENTS:
        try: GAME_CLIENTS[uid].disconnect()
        except: pass
        GAME_CLIENTS.pop(uid, None)
    u['logged_in'] = False
    u['auto_bet_enabled'] = False
    u['token'] = None
    add_log(uid, "🔌 Đã đăng xuất", 'warn')
    return jsonify({'ok': True})

@app.route('/api/config', methods=['POST'])
def api_config():
    u, uid = get_user()
    d = request.get_json() or {}
    if 'auto_bet_enabled' in d:
        u['auto_bet_enabled'] = bool(d['auto_bet_enabled'])
        add_log(uid, f"{'🟢 BẬT' if u['auto_bet_enabled'] else '🔴 TẮT'} auto cược", 'info')
    if 'notify_win' in d: u['notify_win'] = bool(d['notify_win'])
    if 'notify_lose' in d: u['notify_lose'] = bool(d['notify_lose'])
    if 'base_bet' in d:
        try:
            v = int(d['base_bet'])
            if v >= 1000:
                u['base_bet'] = v
                add_log(uid, f"💸 Đổi vốn gốc: {v:,} Win", 'info')
        except: pass
    if 'x2_mode' in d:
        u['x2_mode'] = bool(d['x2_mode'])
        add_log(uid, f"{'🔥 BẬT' if u['x2_mode'] else '⚪ TẮT'} chế độ X2", 'info')
    if 'target_profit' in d:
        try: u['target_profit'] = int(d['target_profit']) if d['target_profit'] else None
        except: u['target_profit'] = None
    if 'lc79_jwt' in d:
        u['lc79_jwt'] = d['lc79_jwt'] or None
        add_log(uid, "🔑 Đã lưu JWT LC79", 'info')
    if 'lc79_api' in d and d['lc79_api']: u['lc79_api'] = d['lc79_api']
    if 'lc79_strip4' in d: u['lc79_strip4'] = bool(d['lc79_strip4'])
    # V4
    if 'confidence_threshold' in d:
        try: u['confidence_threshold'] = max(0.5, min(0.85, float(d['confidence_threshold'])))
        except: pass
    if 'stop_loss' in d:
        try: u['stop_loss'] = int(d['stop_loss'])
        except: u['stop_loss'] = 0
    return jsonify({'ok': True, 'state': {
        'base_bet': u['base_bet'], 'auto_bet_enabled': u['auto_bet_enabled'], 'x2_mode': u['x2_mode'],
    }})

@app.route('/api/code', methods=['POST'])
def api_code():
    u, uid = get_user()
    d = request.get_json() or {}
    raw = (d.get('code') or '').strip().upper()
    if not raw: return jsonify({'ok': False, 'error': 'Chưa nhập code'}), 400
    code = raw[:-4] if (u['lc79_strip4'] and len(raw) > 4) else raw
    add_log(uid, f"📤 Submit LC79: {raw} → {code}", 'info')
    res = submit_lc79_code(u['lc79_jwt'], code, u['lc79_api'])
    if res['ok']: add_log(uid, f"✅ LC79 OK: {res['message']}", 'success')
    else: add_log(uid, f"❌ LC79 fail: {res['message']}", 'error')
    return jsonify(res)

@app.route('/api/ai', methods=['GET'])
def api_ai():
    top = sorted(GLOBAL_AI_WEIGHTS.items(), key=lambda x: x[1], reverse=True)[:20]
    return jsonify({'top': top, 'history_len': len(GLOBAL_HISTORY)})

# ============================================================
# SOCKETIO
# ============================================================
@webio.on('connect')
def on_ws_connect(auth=None):
    uid = (auth or {}).get('client_id') or request.args.get('client_id') or 'default'
    join_room(uid)
    if uid not in USERS:
        USERS[uid] = new_user_state(uid)

# ============================================================
# HTML PAGE (embedded raw string)
# ============================================================
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚡ ULTRA VIP V4 — TX AI</title>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  * { font-family: 'Inter', -apple-system, sans-serif; }
  .mono { font-family: 'JetBrains Mono', monospace; }
  body { background: #05050a; color: #e5e7eb; overflow-x: hidden; min-height: 100vh; }
  .bg-blob { position: fixed; border-radius: 50%; filter: blur(120px); opacity: 0.35; z-index: 0; animation: float 20s ease-in-out infinite; pointer-events: none; }
  .blob-1 { width: 500px; height: 500px; background: #7c3aed; top: -150px; left: -150px; }
  .blob-2 { width: 400px; height: 400px; background: #06b6d4; bottom: -100px; right: -100px; animation-delay: -7s; }
  .blob-3 { width: 350px; height: 350px; background: #ec4899; top: 40%; left: 40%; animation-delay: -14s; }
  @keyframes float {
    0%, 100% { transform: translate(0, 0) scale(1); }
    33% { transform: translate(60px, -80px) scale(1.1); }
    66% { transform: translate(-40px, 60px) scale(0.9); }
  }
  .glass { background: rgba(15, 15, 25, 0.55); backdrop-filter: blur(20px) saturate(180%); -webkit-backdrop-filter: blur(20px) saturate(180%); border: 1px solid rgba(255,255,255,0.08); border-radius: 20px; box-shadow: 0 8px 40px rgba(0,0,0,0.4); }
  .neon-purple { box-shadow: 0 0 30px rgba(139,92,246,0.4); }
  .btn-primary { background: linear-gradient(135deg, #8b5cf6, #6366f1); transition: all 0.25s; border: 1px solid rgba(139,92,246,0.4); }
  .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 10px 30px rgba(139,92,246,0.4); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
  .toggle { position: relative; width: 52px; height: 28px; background: #27272a; border-radius: 999px; transition: all 0.3s; cursor: pointer; border: 1px solid rgba(255,255,255,0.1); flex-shrink: 0; }
  .toggle::after { content: ''; position: absolute; top: 2px; left: 2px; width: 22px; height: 22px; background: #fff; border-radius: 50%; transition: all 0.3s; }
  .toggle.on { background: linear-gradient(135deg, #8b5cf6, #06b6d4); box-shadow: 0 0 20px rgba(139,92,246,0.5); }
  .toggle.on::after { transform: translateX(24px); }
  .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: #10b981; box-shadow: 0 0 0 rgba(16,185,129,0.7); animation: pulse 2s infinite; }
  @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(16,185,129,0.7); } 70% { box-shadow: 0 0 0 12px rgba(16,185,129,0); } 100% { box-shadow: 0 0 0 0 rgba(16,185,129,0); } }
  .history-bar { height: 34px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 800; letter-spacing: 0.5px; transition: transform 0.15s; cursor: default; }
  .history-bar:hover { transform: scale(1.08); }
  .bar-tai { background: linear-gradient(135deg, #3b82f6, #06b6d4); color: white; box-shadow: 0 2px 8px rgba(59,130,246,0.4); }
  .bar-xiu { background: linear-gradient(135deg, #ef4444, #f43f5e); color: white; box-shadow: 0 2px 8px rgba(239,68,68,0.4); }
  .dice { width: 60px; height: 60px; background: linear-gradient(135deg, #f8fafc, #cbd5e1); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 32px; font-weight: 900; color: #1e293b; box-shadow: inset 0 -4px 12px rgba(0,0,0,0.15), 0 4px 20px rgba(0,0,0,0.3); transition: all 0.3s; animation: diceRoll 0.6s ease-out; }
  @keyframes diceRoll { 0% { transform: rotate(0) scale(0.8); } 50% { transform: rotate(180deg) scale(1.15); } 100% { transform: rotate(360deg) scale(1); } }
  .log-line { font-family: 'JetBrains Mono', monospace; font-size: 11.5px; padding: 5px 10px; border-radius: 6px; margin-bottom: 3px; background: rgba(0,0,0,0.25); border-left: 3px solid; line-height: 1.4; }
  .log-info { border-color: #6366f1; color: #c7d2fe; }
  .log-success, .log-win { border-color: #10b981; color: #86efac; }
  .log-error, .log-lose { border-color: #ef4444; color: #fca5a5; }
  .log-warn { border-color: #f59e0b; color: #fde68a; }
  .log-bet { border-color: #8b5cf6; color: #ddd6fe; }
  .scroll::-webkit-scrollbar { width: 6px; }
  .scroll::-webkit-scrollbar-track { background: transparent; }
  .scroll::-webkit-scrollbar-thumb { background: rgba(139,92,246,0.4); border-radius: 3px; }
  .prediction-card { background: linear-gradient(135deg, rgba(139,92,246,0.15), rgba(6,182,212,0.15)); border: 1px solid rgba(139,92,246,0.3); animation: glow 3s ease-in-out infinite alternate; }
  @keyframes glow { from { box-shadow: 0 0 20px rgba(139,92,246,0.15); } to { box-shadow: 0 0 40px rgba(139,92,246,0.35); } }
  .input-field { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 12px 16px; color: #f3f4f6; width: 100%; transition: all 0.2s; outline: none; font-size: 14px; }
  .input-field:focus { border-color: #8b5cf6; background: rgba(139,92,246,0.08); box-shadow: 0 0 0 3px rgba(139,92,246,0.15); }
  .toast { position: fixed; top: 20px; right: 20px; padding: 16px 24px; border-radius: 14px; font-weight: 600; z-index: 9999; animation: slideIn 0.4s ease-out; backdrop-filter: blur(20px); border: 1px solid; min-width: 280px; }
  @keyframes slideIn { from { transform: translateX(120%); } to { transform: translateX(0); } }
  .toast-win { background: rgba(16,185,129,0.2); border-color: #10b981; color: #86efac; }
  .toast-lose { background: rgba(239,68,68,0.2); border-color: #ef4444; color: #fca5a5; }
  .fade-in { animation: fadeIn 0.4s ease-out; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
  .badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }
</style>
</head>
<body class="relative">

<div class="bg-blob blob-1"></div>
<div class="bg-blob blob-2"></div>
<div class="bg-blob blob-3"></div>
<div id="toasts"></div>

<header class="relative z-10 px-4 md:px-8 py-5 border-b border-white/5 backdrop-blur-xl">
  <div class="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-4">
    <div class="flex items-center gap-3">
      <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-violet-500 via-purple-500 to-cyan-500 flex items-center justify-center text-2xl shadow-lg shadow-purple-500/40">⚡</div>
      <div>
        <h1 class="text-lg md:text-xl font-black bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent tracking-tight">ULTRA VIP V4</h1>
        <p class="text-[10px] text-zinc-500 font-semibold tracking-widest uppercase">35 AI Cores · Confidence Gating · Kelly</p>
      </div>
    </div>
    <div class="flex items-center gap-2 md:gap-3">
      <div class="glass px-3 py-2 flex items-center gap-2 text-xs">
        <div class="w-2 h-2 rounded-full bg-zinc-500" id="statusDot"></div>
        <span id="statusText" class="text-zinc-400 font-semibold">Chưa kết nối</span>
      </div>
      <div class="glass px-4 py-2 text-right">
        <div class="text-[9px] text-zinc-500 font-bold tracking-widest uppercase">Số dư</div>
        <div class="text-sm md:text-base font-black text-emerald-400 mono" id="hdrBalance">0</div>
      </div>
    </div>
  </div>
</header>

<main class="relative z-10 max-w-7xl mx-auto p-4 md:p-8">

<section id="loginScreen">
  <div class="max-w-md mx-auto mt-8 md:mt-16 fade-in">
    <div class="glass p-8 md:p-10 neon-purple">
      <div class="text-center mb-8">
        <div class="w-20 h-20 mx-auto rounded-3xl bg-gradient-to-br from-violet-500 to-cyan-500 flex items-center justify-center text-4xl shadow-2xl shadow-purple-500/50 mb-4">🎰</div>
        <h2 class="text-2xl font-black mb-2">Đăng nhập tài khoản</h2>
        <p class="text-zinc-500 text-sm">Nhập tài khoản game tele68 của bạn</p>
      </div>
      <div class="space-y-4">
        <div>
          <label class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Tài khoản</label>
          <input type="text" id="inpUser" class="input-field mono" placeholder="username">
        </div>
        <div>
          <label class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Mật khẩu</label>
          <input type="password" id="inpPass" class="input-field mono" placeholder="••••••••" onkeydown="if(event.key==='Enter') doLogin()">
        </div>
        <button onclick="doLogin()" id="btnLogin" class="btn-primary w-full py-3.5 rounded-xl font-bold text-white">🚀 Đăng nhập</button>
        <p id="loginError" class="text-red-400 text-sm text-center hidden"></p>
      </div>
    </div>
  </div>
</section>

<section id="dashboard" class="hidden">
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6">

    <div class="lg:col-span-2 space-y-4 md:space-y-6">
      <div class="glass p-5 md:p-6 fade-in">
        <div class="flex items-center justify-between flex-wrap gap-4">
          <div class="flex items-center gap-4">
            <div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-500 to-cyan-500 flex items-center justify-center text-2xl font-black shadow-lg shadow-purple-500/30"><span id="avatarLetter">A</span></div>
            <div>
              <div class="text-xs text-zinc-500 font-bold uppercase tracking-widest">Tài khoản</div>
              <div class="text-xl font-black" id="nickname">-</div>
            </div>
          </div>
          <button onclick="doLogout()" class="text-xs text-zinc-400 hover:text-red-400 font-semibold px-3 py-2 rounded-lg hover:bg-red-500/10 transition">Đăng xuất →</button>
        </div>
        <div class="grid grid-cols-3 gap-3 mt-6">
          <div class="bg-black/30 rounded-xl p-3 text-center">
            <div class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider mb-1">Số dư</div>
            <div class="text-base font-black text-cyan-400 mono" id="cardBalance">0</div>
          </div>
          <div class="bg-black/30 rounded-xl p-3 text-center">
            <div class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider mb-1">Lãi / Lỗ</div>
            <div class="text-base font-black mono" id="cardPL">0</div>
          </div>
          <div class="bg-black/30 rounded-xl p-3 text-center">
            <div class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider mb-1">Chuỗi thắng</div>
            <div class="text-base font-black text-amber-400 mono" id="cardStreak">0</div>
          </div>
        </div>
      </div>

      <div class="prediction-card rounded-2xl p-6 md:p-8 fade-in">
        <div class="flex items-center justify-between flex-wrap gap-4 mb-6">
          <div>
            <div class="text-[10px] text-violet-300 font-bold uppercase tracking-widest mb-1">Phiên hiện tại</div>
            <div class="text-2xl md:text-3xl font-black mono" id="sessionId">#---</div>
          </div>
          <div class="flex gap-2 flex-wrap">
            <div class="badge bg-violet-500/20 text-violet-300"><span class="pulse-dot"></span> LIVE</div>
            <div class="badge bg-cyan-500/20 text-cyan-300" id="betBadge">AUTO: OFF</div>
            <div class="badge bg-amber-500/20 text-amber-300" id="cooldownBadge" style="display:none">COOLDOWN</div>
          </div>
        </div>
        <div class="flex items-center justify-center gap-8 md:gap-12 my-6 flex-wrap">
          <div class="text-center">
            <div class="text-[10px] text-zinc-400 font-bold uppercase tracking-widest mb-3">AI Dự đoán</div>
            <div id="predictionBox" class="px-8 md:px-12 py-5 md:py-6 rounded-2xl bg-black/40 border border-white/10">
              <div class="text-4xl md:text-5xl font-black tracking-tight text-zinc-500">...</div>
              <div class="text-xs text-zinc-500 mt-1 font-semibold">chờ session</div>
            </div>
          </div>
          <div class="text-center">
            <div class="text-[10px] text-zinc-400 font-bold uppercase tracking-widest mb-3">Mức cược</div>
            <div class="px-6 md:px-8 py-5 md:py-6 rounded-2xl bg-black/40 border border-white/10">
              <div class="text-2xl md:text-3xl font-black text-emerald-400 mono" id="currentBet">0</div>
              <div class="text-xs text-zinc-500 mt-1 font-semibold">Win</div>
            </div>
          </div>
        </div>

        <div class="mt-4 px-2">
          <div class="flex justify-between text-[10px] mb-1">
            <span class="text-zinc-400 font-bold uppercase tracking-wider">Confidence AI</span>
            <span class="mono font-black text-violet-400" id="confVal">0%</span>
          </div>
          <div class="h-2 bg-white/5 rounded-full overflow-hidden">
            <div id="confBar" class="h-full bg-gradient-to-r from-red-500 via-amber-500 to-emerald-500 transition-all duration-500" style="width:0%"></div>
          </div>
          <div id="skipReason" class="text-[10px] text-amber-400 mt-2 font-semibold hidden"></div>
        </div>

        <div class="flex items-center justify-center gap-3 mt-6" id="diceRow">
          <div class="dice">?</div><div class="dice">?</div><div class="dice">?</div>
        </div>
        <div id="resultBadge" class="text-center mt-4 text-sm font-bold text-zinc-500">Chờ kết quả...</div>
      </div>

      <div class="glass p-5 md:p-6 fade-in">
        <div class="flex items-center justify-between mb-4">
          <div>
            <div class="text-[10px] text-zinc-500 font-bold uppercase tracking-widest">Lịch sử 40 vòng gần nhất</div>
            <div class="text-sm text-zinc-400 mt-1"><span id="historyCount">0</span> vòng tổng</div>
          </div>
          <div class="flex gap-2 text-[10px] font-bold">
            <span class="px-2 py-1 rounded bg-blue-500/20 text-blue-300">TÀI</span>
            <span class="px-2 py-1 rounded bg-red-500/20 text-red-300">XỈU</span>
          </div>
        </div>
        <div id="historyBars" class="grid grid-cols-10 gap-1.5"></div>
      </div>
    </div>

    <div class="space-y-4 md:space-y-6">
      <div class="glass p-5 md:p-6 fade-in">
        <h3 class="text-sm font-black uppercase tracking-widest text-zinc-400 mb-5">⚙️ Cấu hình bot</h3>
        <div class="flex items-center justify-between py-3 border-b border-white/5 gap-3">
          <div><div class="font-bold text-sm">Auto cược</div><div class="text-[10px] text-zinc-500">Tự động đặt cược mỗi phiên</div></div>
          <div class="toggle" id="tglAuto" onclick="toggleConfig('auto_bet_enabled', this)"></div>
        </div>
        <div class="flex items-center justify-between py-3 border-b border-white/5 gap-3">
          <div><div class="font-bold text-sm">Chế độ X2 🔥</div><div class="text-[10px] text-zinc-500">Thắng → x2, thua → về vốn gốc</div></div>
          <div class="toggle" id="tglX2" onclick="toggleConfig('x2_mode', this)"></div>
        </div>
        <div class="flex items-center justify-between py-3 border-b border-white/5 gap-3">
          <div><div class="font-bold text-sm">Thông báo thắng</div><div class="text-[10px] text-zinc-500">Toast xanh khi thắng</div></div>
          <div class="toggle" id="tglNotifyWin" onclick="toggleConfig('notify_win', this)"></div>
        </div>
        <div class="flex items-center justify-between py-3 border-b border-white/5 gap-3">
          <div><div class="font-bold text-sm">Thông báo thua</div><div class="text-[10px] text-zinc-500">Toast đỏ khi thua</div></div>
          <div class="toggle" id="tglNotifyLose" onclick="toggleConfig('notify_lose', this)"></div>
        </div>
        <div class="pt-4">
          <label class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Vốn cược mỗi phiên (Win)</label>
          <div class="flex gap-2">
            <input type="number" id="inpBaseBet" class="input-field mono" value="10000" step="1000" min="1000">
            <button onclick="saveBaseBet()" class="btn-primary px-4 rounded-xl text-white font-bold text-sm whitespace-nowrap">Lưu</button>
          </div>
          <div class="flex gap-1 mt-2">
            <button onclick="setBet(10000)" class="flex-1 text-xs py-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition">10K</button>
            <button onclick="setBet(50000)" class="flex-1 text-xs py-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition">50K</button>
            <button onclick="setBet(100000)" class="flex-1 text-xs py-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition">100K</button>
            <button onclick="setBet(500000)" class="flex-1 text-xs py-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition">500K</button>
          </div>
        </div>
        <div class="pt-4">
          <label class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Chốt lãi tự động (Win)</label>
          <input type="number" id="inpTarget" class="input-field mono" placeholder="VD: 500000 (trống = tắt)" step="10000" onblur="saveTarget()">
        </div>
        <div class="pt-4">
          <label class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Ngưỡng confidence tối thiểu</label>
          <input type="range" min="50" max="85" value="62" id="inpConfThresh" oninput="document.getElementById('confThreshVal').textContent=this.value+'%'; saveConfThresh()" class="w-full accent-violet-500">
          <div class="text-right text-xs mono text-violet-400 mt-1" id="confThreshVal">62%</div>
        </div>
        <div class="pt-4">
          <label class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">Cắt lỗ (Win)</label>
          <input type="number" id="inpStopLoss" class="input-field mono" value="500000" step="100000" onblur="saveStopLoss()">
        </div>
      </div>

      <div class="glass p-5 md:p-6 fade-in">
        <h3 class="text-sm font-black uppercase tracking-widest text-zinc-400 mb-4">🎁 Nhập code LC79</h3>
        <div class="space-y-3">
          <div>
            <label class="text-[10px] font-bold text-zinc-500 uppercase tracking-wider mb-1 block">JWT Token</label>
            <input type="password" id="inpJwt" class="input-field mono text-xs" placeholder="eyJhbGci...">
          </div>
          <div>
            <label class="text-[10px] font-bold text-zinc-500 uppercase tracking-wider mb-1 block">API Endpoint</label>
            <input type="text" id="inpLcApi" class="input-field mono text-xs" value="https://api.lc79.luxury/v1/code/redeem">
          </div>
          <div class="flex items-center gap-2 py-1">
            <input type="checkbox" id="chkStrip4" checked class="w-4 h-4 accent-violet-500">
            <label for="chkStrip4" class="text-xs text-zinc-400">Bỏ 4 ký tự cuối (vd: <span class="mono text-violet-300">WEYJZQLYBLC79</span> → <span class="mono text-emerald-300">WEYJZQLYB</span>)</label>
          </div>
          <div>
            <label class="text-[10px] font-bold text-zinc-500 uppercase tracking-wider mb-1 block">Mã code</label>
            <input type="text" id="inpCode" class="input-field mono uppercase" placeholder="WEYJZQLYBLC79" onkeydown="if(event.key==='Enter') submitCode()">
          </div>
          <button onclick="submitCode()" id="btnSubmitCode" class="btn-primary w-full py-3 rounded-xl font-bold text-white text-sm">📤 Submit code</button>
        </div>
      </div>

      <div class="glass p-5 md:p-6 fade-in">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-black uppercase tracking-widest text-zinc-400">📜 Logs</h3>
          <button onclick="document.getElementById('logsBox').innerHTML=''" class="text-[10px] text-zinc-500 hover:text-red-400 font-bold">CLEAR</button>
        </div>
        <div id="logsBox" class="scroll max-h-80 overflow-y-auto pr-1 space-y-1"></div>
      </div>

      <div class="glass p-5 md:p-6 fade-in">
        <h3 class="text-sm font-black uppercase tracking-widest text-zinc-400 mb-3">🧠 Top AI Cores</h3>
        <div id="aiWeights" class="space-y-1.5"></div>
      </div>
    </div>
  </div>
</section>
</main>

<footer class="relative z-10 text-center py-6 text-[10px] text-zinc-600 font-semibold tracking-wider">
  ULTRA VIP V4 · Live Accuracy · Confidence Gating · Kelly Sizing
</footer>

<script>
const CLIENT_ID = (() => {
  let v = localStorage.getItem('uid');
  if (!v) { v = 'u_' + Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem('uid', v); }
  return v;
})();

let state = {
  logged_in: false, nickname: null, balance: 0, auto_bet_enabled: false,
  notify_win: true, notify_lose: true, base_bet: 10000, current_bet: 10000,
  x2_mode: false, win_streak: 0, profit_loss: 0, target_profit: null,
  current_prediction: null, session_id: null, history: [], logs: [],
  lc79_api: 'https://api.lc79.luxury/v1/code/redeem',
  current_confidence: 0, confidence_threshold: 0.62,
  stop_loss: 500000, cooldown_remaining: 0,
};

const socket = io({ query: { client_id: CLIENT_ID }, transports: ['websocket','polling'] });
socket.on('connect', () => { setStatus(true, 'Đã kết nối'); refreshState(); });
socket.on('disconnect', () => setStatus(false, 'Mất kết nối'));
socket.on('log', (e) => appendLog(e));
socket.on('status', (d) => setStatus(d.connected, d.connected ? 'Game online' : 'Game offline'));

socket.on('new_session', (d) => {
  state.session_id = d.session_id;
  state.current_prediction = d.prediction;
  state.current_bet = d.current_bet;
  state.current_confidence = d.confidence || 0;
  document.getElementById('sessionId').textContent = '#' + d.session_id;
  document.getElementById('currentBet').textContent = fmt(d.current_bet);
  document.getElementById('confVal').textContent = Math.round((d.confidence || 0) * 100) + '%';
  document.getElementById('confBar').style.width = Math.round((d.confidence || 0) * 100) + '%';
  const sr = document.getElementById('skipReason');
  if (d.skip_reason) { sr.textContent = '🛑 ' + d.skip_reason; sr.classList.remove('hidden'); }
  else sr.classList.add('hidden');
  renderPrediction();
});

socket.on('notify', (d) => {
  if (d.type === 'win') showToast('win', `🎉 Thắng ${d.result}! +${fmt(d.amount)} Win`);
  else showToast('lose', `💔 Thua ${d.result} — về vốn gốc`);
});

socket.on('balance', (d) => {
  state.balance = d.balance;
  document.getElementById('hdrBalance').textContent = fmt(d.balance);
  document.getElementById('cardBalance').textContent = fmt(d.balance);
});

socket.on('result', (d) => {
  state.current_prediction = d.prediction;
  state.profit_loss = d.profit_loss;
  state.win_streak = d.win_streak;
  state.balance = d.balance;
  state.history = d.history || [];
  state.cooldown_remaining = d.cooldown_remaining || 0;
  const cb = document.getElementById('cooldownBadge');
  if (state.cooldown_remaining > 0) { cb.style.display = 'inline-flex'; cb.textContent = `COOLDOWN ${state.cooldown_remaining}`; }
  else cb.style.display = 'none';
  renderResult(d); renderStats();
});

socket.on('target_hit', (d) => showToast('win', `🏆 ĐẠT TARGET ${fmt(d.profit)} Win!`));

async function api(path, method='GET', body=null) {
  const opts = { method, headers: { 'Content-Type': 'application/json', 'X-Client-Id': CLIENT_ID } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  return r.json();
}

async function refreshState() {
  const s = await api('/api/state');
  Object.assign(state, s);
  if (s.logged_in) showDashboard(); else showLogin();
  syncUI();
}

async function doLogin() {
  const u = document.getElementById('inpUser').value.trim();
  const p = document.getElementById('inpPass').value.trim();
  if (!u || !p) return;
  const btn = document.getElementById('btnLogin');
  const err = document.getElementById('loginError');
  btn.disabled = true; btn.textContent = '⏳ Đang đăng nhập...';
  err.classList.add('hidden');
  try {
    const r = await api('/api/login', 'POST', { username: u, password: p });
    if (r.ok) await refreshState();
    else { err.textContent = '❌ ' + (r.error || 'Đăng nhập thất bại'); err.classList.remove('hidden'); }
  } catch(e) { err.textContent = '❌ ' + e.message; err.classList.remove('hidden'); }
  btn.disabled = false; btn.textContent = '🚀 Đăng nhập';
}

async function doLogout() { await api('/api/logout', 'POST'); await refreshState(); }

function toggleConfig(key, el) {
  const newVal = !state[key];
  el.classList.toggle('on', newVal);
  state[key] = newVal;
  api('/api/config', 'POST', { [key]: newVal }).then(() => {
    document.getElementById('betBadge').textContent = 'AUTO: ' + (state.auto_bet_enabled ? 'ON' : 'OFF');
  });
}

function saveBaseBet() {
  const v = parseInt(document.getElementById('inpBaseBet').value) || 10000;
  api('/api/config', 'POST', { base_bet: v }).then(() => { state.base_bet = v; showToast('win', `💸 Vốn gốc: ${fmt(v)} Win`); });
}
function setBet(v) { document.getElementById('inpBaseBet').value = v; saveBaseBet(); }
function saveTarget() {
  const v = document.getElementById('inpTarget').value;
  api('/api/config', 'POST', { target_profit: v ? parseInt(v) : null });
}
function saveConfThresh() {
  api('/api/config', 'POST', { confidence_threshold: parseInt(document.getElementById('inpConfThresh').value) / 100 });
}
function saveStopLoss() {
  api('/api/config', 'POST', { stop_loss: parseInt(document.getElementById('inpStopLoss').value) });
}

async function submitCode() {
  const jwt = document.getElementById('inpJwt').value.trim();
  const code = document.getElementById('inpCode').value.trim().toUpperCase();
  const endpoint = document.getElementById('inpLcApi').value.trim();
  const strip4 = document.getElementById('chkStrip4').checked;
  if (!jwt) return alert('Nhập JWT trước');
  if (!code) return alert('Nhập code');
  await api('/api/config', 'POST', { lc79_jwt: jwt, lc79_api: endpoint, lc79_strip4: strip4 });
  const btn = document.getElementById('btnSubmitCode');
  btn.disabled = true; btn.textContent = '⏳ Đang gửi...';
  const r = await api('/api/code', 'POST', { code });
  btn.disabled = false; btn.textContent = '📤 Submit code';
  if (r.ok) showToast('win', '✅ ' + (r.message || 'Code OK'));
  else showToast('lose', '❌ ' + (r.message || 'Code fail'));
}

function showLogin() {
  document.getElementById('loginScreen').classList.remove('hidden');
  document.getElementById('dashboard').classList.add('hidden');
}
function showDashboard() {
  document.getElementById('loginScreen').classList.add('hidden');
  document.getElementById('dashboard').classList.remove('hidden');
  syncUI();
}

function syncUI() {
  document.getElementById('nickname').textContent = state.nickname || '-';
  document.getElementById('avatarLetter').textContent = (state.nickname || 'A')[0].toUpperCase();
  document.getElementById('hdrBalance').textContent = fmt(state.balance);
  document.getElementById('cardBalance').textContent = fmt(state.balance);
  document.getElementById('inpBaseBet').value = state.base_bet;
  document.getElementById('inpLcApi').value = state.lc79_api || 'https://api.lc79.luxury/v1/code/redeem';
  document.getElementById('tglAuto').classList.toggle('on', state.auto_bet_enabled);
  document.getElementById('tglX2').classList.toggle('on', state.x2_mode);
  document.getElementById('tglNotifyWin').classList.toggle('on', state.notify_win);
  document.getElementById('tglNotifyLose').classList.toggle('on', state.notify_lose);
  document.getElementById('betBadge').textContent = 'AUTO: ' + (state.auto_bet_enabled ? 'ON' : 'OFF');
  if (state.target_profit) document.getElementById('inpTarget').value = state.target_profit;
  if (state.confidence_threshold) {
    const pct = Math.round(state.confidence_threshold * 100);
    document.getElementById('inpConfThresh').value = pct;
    document.getElementById('confThreshVal').textContent = pct + '%';
  }
  if (state.stop_loss !== undefined) document.getElementById('inpStopLoss').value = state.stop_loss;
  renderPrediction(); renderStats(); renderHistory(state.history);
  document.getElementById('sessionId').textContent = '#' + (state.session_id || '---');
  document.getElementById('currentBet').textContent = fmt(state.current_bet);
  document.getElementById('confVal').textContent = Math.round((state.current_confidence || 0) * 100) + '%';
  document.getElementById('confBar').style.width = Math.round((state.current_confidence || 0) * 100) + '%';
  if (state.skip_reason) {
    const sr = document.getElementById('skipReason');
    sr.textContent = '🛑 ' + state.skip_reason; sr.classList.remove('hidden');
  }
  if (state.logs && state.logs.length) {
    document.getElementById('logsBox').innerHTML = '';
    state.logs.forEach(appendLog);
  }
  refreshAI();
}

function renderPrediction() {
  const box = document.getElementById('predictionBox');
  if (!state.current_prediction) {
    box.innerHTML = '<div class="text-4xl md:text-5xl font-black tracking-tight text-zinc-500">...</div><div class="text-xs text-zinc-500 mt-1 font-semibold">chờ session</div>';
    return;
  }
  const isTai = state.current_prediction === 'TAI';
  box.innerHTML = `
    <div class="text-4xl md:text-5xl font-black tracking-tight ${isTai ? 'text-blue-400' : 'text-red-400'}">
      ${isTai ? '🔵' : '🔴'} ${state.current_prediction}
    </div>
    <div class="text-xs ${isTai ? 'text-blue-300' : 'text-red-300'} mt-1 font-bold">AI CHỐT</div>
  `;
}

function renderStats() {
  const pl = state.profit_loss;
  const plEl = document.getElementById('cardPL');
  plEl.textContent = (pl >= 0 ? '+' : '') + fmt(pl);
  plEl.className = 'text-base font-black mono ' + (pl >= 0 ? 'text-emerald-400' : 'text-red-400');
  document.getElementById('cardStreak').textContent = state.win_streak;
}

function renderResult(d) {
  const diceRow = document.getElementById('diceRow');
  const vals = d.dices || [0,0,0];
  diceRow.innerHTML = vals.map((v,i) => `<div class="dice" style="animation-delay:${i*0.1}s">${v||'?'}</div>`).join('');
  const badge = document.getElementById('resultBadge');
  const isTai = d.result === 'TAI';
  if (d.result === 'TAI' || d.result === 'XIU') {
    if (d.won === true) badge.innerHTML = `<span class="text-emerald-400">✅ THẮNG — ${isTai ? '🔵 TÀI' : '🔴 XỈU'}</span>`;
    else if (d.won === false) badge.innerHTML = `<span class="text-red-400">❌ THUA — ${isTai ? '🔵 TÀI' : '🔴 XỈU'}</span>`;
    else badge.innerHTML = `<span class="text-zinc-400">🎲 ${isTai ? '🔵 TÀI' : '🔴 XỈU'}</span>`;
  }
  renderHistory(d.history);
}

function renderHistory(hist) {
  const c = document.getElementById('historyBars');
  const h = hist || [];
  document.getElementById('historyCount').textContent = h.length;
  c.innerHTML = h.slice(-40).map(r => {
    const isTai = r === 'TAI';
    return `<div class="history-bar ${isTai ? 'bar-tai' : 'bar-xiu'}" title="${r}">${isTai ? 'T' : 'X'}</div>`;
  }).join('');
}

async function refreshAI() {
  try {
    const d = await api('/api/ai');
    const box = document.getElementById('aiWeights');
    const max = d.top[0]?.[1] || 1;
    box.innerHTML = d.top.slice(0, 10).map(([name, w]) => {
      const pct = Math.round((w / max) * 100);
      return `<div><div class="flex justify-between text-[11px] mb-1"><span class="font-bold text-zinc-300">${name}</span><span class="mono text-violet-400 font-bold">${w.toFixed(2)}</span></div><div class="h-1.5 bg-white/5 rounded-full overflow-hidden"><div class="h-full bg-gradient-to-r from-violet-500 to-cyan-500 transition-all duration-500" style="width:${pct}%"></div></div></div>`;
    }).join('');
  } catch {}
}

function appendLog(e) {
  const box = document.getElementById('logsBox');
  const div = document.createElement('div');
  div.className = 'log-line log-' + (e.level || 'info');
  div.textContent = `[${e.ts}] ${e.msg}`;
  box.appendChild(div);
  while (box.children.length > 100) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

function setStatus(ok, text) {
  const dot = document.getElementById('statusDot');
  const t = document.getElementById('statusText');
  dot.className = 'w-2 h-2 rounded-full ' + (ok ? 'bg-emerald-400 shadow-lg shadow-emerald-400/60' : 'bg-zinc-500');
  t.textContent = text;
  t.className = 'text-xs font-semibold ' + (ok ? 'text-emerald-400' : 'text-zinc-400');
}

function showToast(type, msg) {
  const c = document.getElementById('toasts');
  const div = document.createElement('div');
  div.className = 'toast toast-' + type;
  div.textContent = msg;
  c.appendChild(div);
  setTimeout(() => { div.style.transition = 'all 0.4s'; div.style.opacity = '0'; div.style.transform = 'translateX(120%)'; setTimeout(()=>div.remove(), 400); }, 4000);
}

function fmt(n) { return (n || 0).toLocaleString('en-US'); }

document.addEventListener('DOMContentLoaded', () => {
  refreshState();
  setInterval(refreshAI, 15000);
});
</script>
</body>
</html>"""

# ============================================================
# RUN
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 60)
    print("⚡ ULTRA VIP V4 — SINGLE FILE ONLINE")
    print(f"   http://0.0.0.0:{port}")
    print("   Features: 35 Cores · Live Accuracy · Confidence Gating · Kelly · Stop-Loss · Cooldown")
    print("=" * 60)
    webio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
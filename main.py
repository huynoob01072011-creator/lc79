"""
⚡ ULTRA VIP V4 — Full Fixed Edition
35 AI Cores · Live Accuracy · Confidence Gating · Kelly Sizing · Stop-Loss · Cooldown
Web UI · LC79 Manual Code · Auto Bet · Background Data Collector
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
# BACKGROUND COLLECTOR CONFIG
# ============================================================
DATA_COLLECTOR_USER = os.environ.get('COLLECTOR_USER', 'acc_clone_soi_cau')
DATA_COLLECTOR_PASS = os.environ.get('COLLECTOR_PASS', 'matkhau123')
ENABLE_BG_COLLECTOR = os.environ.get('ENABLE_BG_COLLECTOR', '0') == '1'

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
_BG_THREAD_STARTED = False

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
        'current_confidence': 0.0,
        'confidence_details': {},
        'confidence_threshold': 0.68,
        'consecutive_losses': 0,
        'cooldown_remaining': 0,
        'stop_loss': 500000,
        'skip_reason': None,
        'kelly_size': 0,
        '_password': None,
        '_is_bg': False,
    }

def get_user():
    uid = request.headers.get('X-Client-Id') or request.args.get('client_id') or 'default'
    if uid not in USERS:
        USERS[uid] = new_user_state(uid)
    return USERS[uid], uid

def add_log(uid, message, level='info'):
    """Thread-safe log — không bao giờ raise."""
    try:
        if uid not in USERS: return
        ts = datetime.now().strftime('%H:%M:%S')
        entry = {'ts': ts, 'msg': message, 'level': level}
        USERS[uid]['logs'].append(entry)
        try:
            webio.emit('log', entry, room=uid)
        except Exception as e:
            logger.debug(f"webio.emit log skipped: {e}")
    except Exception as e:
        logger.debug(f"add_log skipped: {e}")

def safe_emit(event, data, uid):
    """Thread-safe emit — không bao giờ raise."""
    try:
        webio.emit(event, data, room=uid)
    except Exception as e:
        logger.debug(f"safe_emit {event} skipped: {e}")

# ============================================================
# 35 AI CORES
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
    state = USERS[uid]
    history = list(GLOBAL_HISTORY)

    if len(history) < 15:
        return None, 0.0, {"reason": f"Chưa đủ data ({len(history)}/15)"}

    model_preds = compute_all_models(history)
    state['last_predictions'] = model_preds

    score = {"TAI": 0.0, "XIU": 0.0}
    vote_count = {"TAI": 0, "XIU": 0}
    total_w = 0.0
    reliabilities = {}

    for m, p in model_preds.items():
        acc = MODEL_ACCURACY.get(m, {'rec_correct': 0, 'rec_total': 0})
        base_w = GLOBAL_AI_WEIGHTS.get(m, 1.0)
        if acc['rec_total'] >= 8:
            rec_acc = acc['rec_correct'] / acc['rec_total']
            acc_factor = max(0.15, (rec_acc ** 2) * 2.5)
        else:
            acc_factor = 0.6
        reliability = base_w * acc_factor
        reliabilities[m] = reliability
        score[p] += reliability
        vote_count[p] += 1
        total_w += reliability

    if total_w == 0:
        return None, 0.0, {"reason": "Không model nào vote"}

    pred = "TAI" if score["TAI"] > score["XIU"] else "XIU"
    other = "XIU" if pred == "TAI" else "TAI"

    margin = (score[pred] - score[other]) / total_w
    agree_pct = vote_count[pred] / len(model_preds)

    top_models = sorted(reliabilities.items(), key=lambda x: x[1], reverse=True)[:7]
    top_agree = sum(1 for m, _ in top_models if model_preds[m] == pred)
    top_consensus = top_agree / max(1, len(top_models))

    confidence = 0.45 * margin + 0.35 * agree_pct + 0.20 * top_consensus

    if top_consensus < 0.70:
        confidence *= 0.75
    if agree_pct < 0.60:
        confidence *= 0.80
    if margin < 0.05:
        confidence *= 0.70

    confidence = max(0.0, min(0.82, confidence))

    return pred, confidence, {
        "score": score, "votes": vote_count,
        "margin": round(margin, 3),
        "agree_pct": round(agree_pct, 3),
        "top_consensus": round(top_consensus, 3),
        "n_models": len(model_preds),
    }


def update_ai_weights(actual_result, uid=None):
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
# RISK + KELLY
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
# TELE68 LOGIN
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


# ============================================================
# GAME WEBSOCKET — FULL FIX với retry + diagnostics
# ============================================================
def start_game_ws(uid, attempt=1, max_attempts=3):
    state = USERS.get(uid)
    if not state:
        logger.warning(f"start_game_ws: uid {uid} không tồn tại")
        return
    if not state.get('token'):
        add_log(uid, "❌ Không có token — hãy đăng nhập lại", 'error')
        return

    tok = state['token']
    is_bg = state.get('_is_bg', False)
    add_log(uid, f"🔑 Token len={len(tok)} · {tok[:24]}... · attempt {attempt}/{max_attempts}", 'info')

    # Dọn kết nối cũ
    if uid in GAME_CLIENTS:
        try: GAME_CLIENTS[uid].disconnect()
        except: pass
        GAME_CLIENTS.pop(uid, None)

    client = sio_client.Client(
        reconnection=True,
        reconnection_attempts=3,
        logger=False,
        engineio_logger=False,
    )
    GAME_CLIENTS[uid] = client

    # ---------- CONNECT HANDLERS ----------
    @client.event(namespace='/txmd5')
    def connect():
        add_log(uid, "✅ WS /txmd5 đã kết nối!", 'success')
        safe_emit('status', {'connected': True}, uid)

    @client.event(namespace='/txmd5')
    def connect_error(data):
        add_log(uid, f"❌ WS connect_error: {data}", 'error')
        safe_emit('status', {'connected': False, 'error': str(data)}, uid)

    @client.event(namespace='/txmd5')
    def disconnect():
        add_log(uid, "⚠️ WS đã ngắt kết nối", 'warn')
        safe_emit('status', {'connected': False}, uid)

    # ---------- GAME EVENTS ----------
    @client.on('new-session', namespace='/txmd5')
    def on_new_session(data):
        state['session_id'] = data.get('id', '?')
        state['has_bet_this_session'] = False
        state['waiting_for_result'] = False

        pred, conf, details = make_prediction(uid)
        state['current_prediction'] = pred
        state['current_confidence'] = conf
        state['confidence_details'] = details

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
            add_log(
                uid,
                f"🎯 AI chốt {pred} (conf {conf:.0%} · margin {details.get('margin',0):.0%} · "
                f"top {details.get('top_consensus',0):.0%})",
                'info'
            )

        if state['x2_mode'] and state['win_streak'] >= 1:
            kelly = calculate_bet_size(uid)
            state['current_bet'] = max(kelly, state['base_bet'] * 2)
        else:
            state['current_bet'] = calculate_bet_size(uid) or state['base_bet']
        state['kelly_size'] = state['current_bet']

        safe_emit('new_session', {
            'session_id': state['session_id'],
            'prediction': state['current_prediction'],
            'confidence': round(state['current_confidence'], 3),
            'confidence_details': details,
            'current_bet': state['current_bet'],
            'skip_reason': state['skip_reason'],
            'history_len': len(GLOBAL_HISTORY),
        }, uid)

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
                    safe_emit('bet_placed', {
                        'amount': state['current_bet'],
                        'type': state['current_prediction'],
                    }, uid)
                except Exception as e:
                    add_log(uid, f"❌ Lỗi đặt cược: {e}", 'error')

    @client.on('bet-result', namespace='/txmd5')
    def on_bet_result(data):
        if "postBalance" in data:
            state['balance'] = data["postBalance"]
            safe_emit('balance', {'balance': state['balance']}, uid)
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
                    safe_emit('notify', {
                        'type': 'win', 'amount': win_amt, 'result': result,
                        'dices': dices, 'streak': state['win_streak'],
                    }, uid)
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
                    safe_emit('notify', {
                        'type': 'lose', 'amount': -state['current_bet'],
                        'result': result, 'dices': dices,
                    }, uid)
            state['waiting_for_result'] = False

        safe_emit('result', {
            'result': result, 'dices': dices,
            'prediction': prediction, 'won': won,
            'profit_loss': state['profit_loss'],
            'win_streak': state['win_streak'],
            'balance': state['balance'],
            'consecutive_losses': state['consecutive_losses'],
            'cooldown_remaining': state['cooldown_remaining'],
            'history': list(GLOBAL_HISTORY)[-40:],
        }, uid)

    # ---------- CONNECT với fallback transports ----------
    transports_list = [['websocket']]
    if attempt >= 2:
        transports_list = [['polling', 'websocket'], ['websocket']]
        add_log(uid, "🔄 Thử fallback transports polling+websocket", 'warn')

    ok = False
    for transports in transports_list:
        try:
            add_log(uid, f"🔌 Connecting transports={transports}...", 'info')
            client.connect(
                'https://wtxmd52.tele68.com',
                socketio_path='txmd5/',
                namespaces=['/txmd5'],
                transports=transports,
                auth={"token": tok},
                headers={"User-Agent": "Mozilla/5.0"},
                wait_timeout=15,
            )
            ok = True
            add_log(uid, "✅ Namespace /txmd5 OK", 'success')
            break
        except Exception as e:
            add_log(uid, f"❌ Fail ({transports}): {e}", 'error')
            try: client.disconnect()
            except: pass
            time.sleep(1.5)

    if ok:
        try:
            client.wait()
        except Exception as e:
            add_log(uid, f"⚠️ wait error: {e}", 'warn')

    # ---------- Retry nếu fail ----------
    if not ok:
        GAME_CLIENTS.pop(uid, None)
        if attempt < max_attempts and not is_bg:
            delay = 3 * attempt
            add_log(uid, f"🔄 Retry {attempt+1}/{max_attempts} sau {delay}s...", 'warn')
            time.sleep(delay)
            start_game_ws(uid, attempt + 1, max_attempts)
        elif not is_bg:
            add_log(uid, "❌ WS thất bại sau nhiều lần — hãy logout → login lại", 'error')
            safe_emit('status', {'connected': False, 'error': 'WS failed after retries'}, uid)


# ============================================================
# BACKGROUND DATA COLLECTOR
# ============================================================
def background_data_collector():
    """Login acc riêng, giữ WS sống để tích lũy GLOBAL_HISTORY 24/7."""
    global _BG_THREAD_STARTED
    if _BG_THREAD_STARTED:
        return
    _BG_THREAD_STARTED = True

    if not ENABLE_BG_COLLECTOR:
        logger.info("ℹ️ Background collector TẮT (set ENABLE_BG_COLLECTOR=1 để bật)")
        return

    logger.info("🌐 Background collector đang khởi động...")
    bg_uid = "_bg_collector"

    while True:
        try:
            if bg_uid not in USERS:
                USERS[bg_uid] = new_user_state(bg_uid)
            bg = USERS[bg_uid]
            bg['_is_bg'] = True

            res = login_tele68(DATA_COLLECTOR_USER, DATA_COLLECTOR_PASS)
            if 'token' in res:
                bg['token'] = res['token']
                bg['nickname'] = res.get('nickname')
                bg['logged_in'] = True
                logger.info(f"✅ BG collector login OK: {res.get('nickname')}")
                try:
                    start_game_ws(bg_uid)
                except Exception as e:
                    logger.warning(f"BG WS error: {e}")
            else:
                logger.warning(f"BG login fail: {res.get('_error')}")
        except Exception as e:
            logger.warning(f"BG collector error: {e}")
        time.sleep(30)


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
        'current_confidence': u.get('current_confidence', 0),
        'confidence_threshold': u.get('confidence_threshold', 0.68),
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

    # Ngắt WS cũ nếu có
    if uid in GAME_CLIENTS:
        try: GAME_CLIENTS[uid].disconnect()
        except: pass
        GAME_CLIENTS.pop(uid, None)

    add_log(uid, f"🔄 Đang đăng nhập {username}...", 'info')
    result = login_tele68(username, password)
    if '_error' in result:
        add_log(uid, f"❌ Login fail: {result['_error']}", 'error')
        return jsonify({'ok': False, 'error': result['_error']}), 400

    # Set toàn bộ state TRƯỚC khi start thread
    u['token'] = result['token']
    u['nickname'] = result['nickname']
    u['balance'] = result['money']
    u['logged_in'] = True
    u['profit_loss'] = 0
    u['win_streak'] = 0
    u['consecutive_losses'] = 0
    u['cooldown_remaining'] = 0
    u['_password'] = password
    u['_is_bg'] = False

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


@app.route('/api/reconnect', methods=['POST'])
def api_reconnect():
    """Manual reconnect WS."""
    u, uid = get_user()
    if not u['token']:
        return jsonify({'ok': False, 'error': 'Chưa login'}), 400
    add_log(uid, "🔄 Manual reconnect...", 'info')
    threading.Thread(target=start_game_ws, args=(uid,), daemon=True).start()
    return jsonify({'ok': True})


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
# HTML PAGE (CLEAN + NO-ZOOM)
# ============================================================
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="format-detection" content="telephone=no">
<title>⚡ ULTRA VIP V4 — TX AI</title>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; }
  html, body {
    -webkit-text-size-adjust: 100%;
    text-size-adjust: 100%;
    touch-action: pan-x pan-y;
    -ms-touch-action: pan-x pan-y;
  }
  * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
  .mono { font-family: 'JetBrains Mono', monospace; }
  body {
    background: #0b0b12;
    color: #e5e7eb;
    min-height: 100vh;
    margin: 0;
    overflow-x: hidden;
    -webkit-tap-highlight-color: transparent;
  }
  .card {
    background: #13131d;
    border: 1px solid #232330;
    border-radius: 12px;
    padding: 20px;
  }
  .card-tight { padding: 14px 18px; }
  .label-xs {
    font-size: 10px;
    font-weight: 700;
    color: #71717a;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .btn {
    background: #6366f1;
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 11px 18px;
    font-weight: 600;
    font-size: 14px;
    cursor: pointer;
    transition: background 0.15s;
  }
  .btn:hover:not(:disabled) { background: #4f46e5; }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-ghost {
    background: #1a1a26;
    border: 1px solid #2a2a3a;
    color: #d4d4d8;
  }
  .btn-ghost:hover:not(:disabled) { background: #232330; }
  .input {
    background: #0a0a12;
    border: 1px solid #2a2a3a;
    border-radius: 8px;
    padding: 10px 12px;
    color: #f3f4f6;
    width: 100%;
    font-size: 14px;
    outline: none;
    transition: border-color 0.15s;
  }
  .input:focus { border-color: #6366f1; }
  .toggle {
    position: relative;
    width: 44px;
    height: 24px;
    background: #2a2a3a;
    border-radius: 999px;
    cursor: pointer;
    transition: background 0.2s;
    flex-shrink: 0;
    border: none;
    padding: 0;
  }
  .toggle::after {
    content: '';
    position: absolute;
    top: 2px;
    left: 2px;
    width: 20px;
    height: 20px;
    background: #fff;
    border-radius: 50%;
    transition: transform 0.2s;
  }
  .toggle.on { background: #6366f1; }
  .toggle.on::after { transform: translateX(20px); }
  .history-bar {
    height: 30px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 800;
    color: #fff;
  }
  .bar-tai { background: #3b82f6; }
  .bar-xiu { background: #ef4444; }
  .dice {
    width: 54px;
    height: 54px;
    background: #e5e7eb;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 26px;
    font-weight: 800;
    color: #111827;
  }
  .log-line {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    padding: 5px 9px;
    border-radius: 4px;
    margin-bottom: 3px;
    background: #0a0a12;
    border-left: 2px solid #6366f1;
    line-height: 1.45;
    word-break: break-word;
  }
  .log-info { border-color: #6366f1; color: #c7d2fe; }
  .log-success, .log-win { border-color: #10b981; color: #86efac; }
  .log-error, .log-lose { border-color: #ef4444; color: #fca5a5; }
  .log-warn { border-color: #f59e0b; color: #fde68a; }
  .log-bet { border-color: #8b5cf6; color: #ddd6fe; }
  .toast {
    position: fixed;
    top: 16px;
    right: 16px;
    padding: 12px 18px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 13px;
    z-index: 9999;
    border: 1px solid;
    background: #13131d;
    min-width: 240px;
    animation: fadeIn 0.2s ease-out;
  }
  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
  .toast-win { border-color: #10b981; color: #86efac; }
  .toast-lose { border-color: #ef4444; color: #fca5a5; }
  .scroll::-webkit-scrollbar { width: 5px; }
  .scroll::-webkit-scrollbar-track { background: transparent; }
  .scroll::-webkit-scrollbar-thumb { background: #2a2a3a; border-radius: 3px; }
  .badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.03em;
  }
  .status-dot { width: 7px; height: 7px; border-radius: 50%; background: #71717a; }
  .status-dot.online { background: #10b981; }
  .progress { height: 6px; background: #1a1a26; border-radius: 999px; overflow: hidden; }
  .progress-fill { height: 100%; background: #6366f1; transition: width 0.4s; }
</style>
</head>
<body>

<div id="toasts"></div>

<header style="border-bottom: 1px solid #1a1a26; padding: 14px 20px;">
  <div style="max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
    <div style="display: flex; align-items: center; gap: 10px;">
      <div style="width: 38px; height: 38px; border-radius: 10px; background: #6366f1; display: flex; align-items: center; justify-content: center; font-size: 18px;">⚡</div>
      <div>
        <h1 style="font-size: 16px; font-weight: 800; margin: 0; line-height: 1.1;">ULTRA VIP V4</h1>
        <p style="font-size: 10px; color: #71717a; margin: 2px 0 0;">35 AI · Confidence · Kelly</p>
      </div>
    </div>
    <div style="display: flex; gap: 8px; flex-wrap: wrap;">
      <div style="background: #13131d; border: 1px solid #232330; border-radius: 8px; padding: 8px 12px; display: flex; align-items: center; gap: 8px;">
        <div class="status-dot" id="statusDot"></div>
        <span id="statusText" style="font-size: 12px; color: #71717a; font-weight: 500;">Chưa kết nối</span>
      </div>
      <div style="background: #13131d; border: 1px solid #232330; border-radius: 8px; padding: 6px 14px; text-align: right; min-width: 100px;">
        <div class="label-xs">Số dư</div>
        <div style="font-size: 15px; font-weight: 800; color: #10b981; line-height: 1.2;" class="mono" id="hdrBalance">0</div>
      </div>
    </div>
  </div>
</header>

<main style="max-width: 1200px; margin: 0 auto; padding: 20px;">

<!-- LOGIN SCREEN -->
<section id="loginScreen">
  <div style="max-width: 420px; margin: 40px auto 0;">
    <div class="card">
      <div style="text-align: center; margin-bottom: 24px;">
        <div style="width: 64px; height: 64px; margin: 0 auto 16px; border-radius: 16px; background: #6366f1; display: flex; align-items: center; justify-content: center; font-size: 28px;">🎰</div>
        <h2 style="font-size: 20px; font-weight: 800; margin: 0 0 4px;">Đăng nhập</h2>
        <p style="font-size: 13px; color: #71717a; margin: 0;">Nhập tài khoản tele68</p>
      </div>
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div>
          <label class="label-xs" style="display:block; margin-bottom: 6px;">Tài khoản</label>
          <input type="text" id="inpUser" class="input mono" placeholder="username" autocomplete="username">
        </div>
        <div>
          <label class="label-xs" style="display:block; margin-bottom: 6px;">Mật khẩu</label>
          <input type="password" id="inpPass" class="input mono" placeholder="••••••••" autocomplete="current-password" onkeydown="if(event.key==='Enter') doLogin()">
        </div>
        <button onclick="doLogin()" id="btnLogin" class="btn" style="width:100%; margin-top: 4px;">Đăng nhập</button>
        <p id="loginError" style="color: #fca5a5; font-size: 13px; text-align: center; margin: 0; display: none;"></p>
      </div>
    </div>
  </div>
</section>

<!-- DASHBOARD -->
<section id="dashboard" style="display: none;">
  <div style="display: grid; grid-template-columns: 1fr; gap: 16px;" id="dashGrid">

    <div style="display: flex; flex-direction: column; gap: 16px;">
      <div class="card">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <div style="width: 46px; height: 46px; border-radius: 12px; background: #6366f1; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 800;"><span id="avatarLetter">A</span></div>
            <div>
              <div class="label-xs">Tài khoản</div>
              <div style="font-size: 17px; font-weight: 800; line-height: 1.2;" id="nickname">-</div>
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button onclick="doReconnect()" class="btn btn-ghost" style="font-size: 12px; padding: 8px 14px;">Reconnect</button>
            <button onclick="doLogout()" class="btn btn-ghost" style="font-size: 12px; padding: 8px 14px;">Đăng xuất</button>
          </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 16px;">
          <div style="background: #0a0a12; border: 1px solid #232330; border-radius: 8px; padding: 10px; text-align: center;">
            <div class="label-xs" style="margin-bottom: 3px;">Số dư</div>
            <div style="font-size: 15px; font-weight: 800; color: #06b6d4;" class="mono" id="cardBalance">0</div>
          </div>
          <div style="background: #0a0a12; border: 1px solid #232330; border-radius: 8px; padding: 10px; text-align: center;">
            <div class="label-xs" style="margin-bottom: 3px;">Lãi / Lỗ</div>
            <div style="font-size: 15px; font-weight: 800;" class="mono" id="cardPL">0</div>
          </div>
          <div style="background: #0a0a12; border: 1px solid #232330; border-radius: 8px; padding: 10px; text-align: center;">
            <div class="label-xs" style="margin-bottom: 3px;">Chuỗi thắng</div>
            <div style="font-size: 15px; font-weight: 800; color: #f59e0b;" class="mono" id="cardStreak">0</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 16px;">
          <div>
            <div class="label-xs">Phiên hiện tại</div>
            <div style="font-size: 20px; font-weight: 800;" class="mono" id="sessionId">#---</div>
          </div>
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            <div class="badge" style="background: #1e1b4b; color: #a5b4fc;">LIVE</div>
            <div class="badge" style="background: #0c4a6e; color: #7dd3fc;" id="betBadge">AUTO: OFF</div>
            <div class="badge" style="background: #451a03; color: #fcd34d; display:none;" id="cooldownBadge">COOLDOWN</div>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div style="text-align: center; background: #0a0a12; border: 1px solid #232330; border-radius: 10px; padding: 16px 10px;">
            <div class="label-xs" style="margin-bottom: 8px;">AI Dự đoán</div>
            <div id="predictionBox">
              <div style="font-size: 28px; font-weight: 800; color: #71717a;">...</div>
              <div style="font-size: 11px; color: #52525b; margin-top: 2px;">chờ session</div>
            </div>
          </div>
          <div style="text-align: center; background: #0a0a12; border: 1px solid #232330; border-radius: 10px; padding: 16px 10px;">
            <div class="label-xs" style="margin-bottom: 8px;">Mức cược</div>
            <div style="font-size: 22px; font-weight: 800; color: #10b981;" class="mono" id="currentBet">0</div>
            <div style="font-size: 11px; color: #52525b; margin-top: 2px;">Win</div>
          </div>
        </div>

        <div style="margin-top: 14px;">
          <div style="display: flex; justify-content: space-between; font-size: 10px; margin-bottom: 6px;">
            <span class="label-xs">Độ tin cậy AI</span>
            <span class="mono" style="font-weight: 800; color: #a5b4fc;" id="confVal">0%</span>
          </div>
          <div class="progress">
            <div id="confBar" class="progress-fill" style="width: 0%;"></div>
          </div>
          <div id="skipReason" style="font-size: 11px; color: #fbbf24; margin-top: 6px; font-weight: 600; display: none;"></div>
        </div>

        <div style="display: flex; align-items: center; justify-content: center; gap: 10px; margin: 18px 0 10px;" id="diceRow">
          <div class="dice">?</div><div class="dice">?</div><div class="dice">?</div>
        </div>
        <div id="resultBadge" style="text-align: center; margin-top: 8px; font-size: 13px; font-weight: 700; color: #71717a;">Chờ kết quả...</div>
      </div>

      <div class="card">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
          <div>
            <div class="label-xs">Lịch sử 40 vòng</div>
            <div style="font-size: 13px; color: #71717a; margin-top: 2px;"><span id="historyCount">0</span> vòng</div>
          </div>
          <div style="display: flex; gap: 6px; font-size: 10px; font-weight: 700;">
            <span style="padding: 3px 8px; border-radius: 4px; background: #1e3a8a; color: #93c5fd;">TÀI</span>
            <span style="padding: 3px 8px; border-radius: 4px; background: #7f1d1d; color: #fca5a5;">XỈU</span>
          </div>
        </div>
        <div id="historyBars" style="display: grid; grid-template-columns: repeat(10, 1fr); gap: 4px;"></div>
      </div>
    </div>

    <div style="display: flex; flex-direction: column; gap: 16px;">

      <div class="card">
        <h3 class="label-xs" style="margin: 0 0 14px;">Cấu hình bot</h3>

        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #1a1a26; gap: 10px;">
          <div><div style="font-weight: 700; font-size: 13px;">Auto cược</div><div style="font-size: 10px; color: #71717a;">Tự động đặt cược</div></div>
          <button class="toggle" id="tglAuto" onclick="toggleConfig('auto_bet_enabled', this)"></button>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #1a1a26; gap: 10px;">
          <div><div style="font-weight: 700; font-size: 13px;">Chế độ X2</div><div style="font-size: 10px; color: #71717a;">Thắng → x2, thua → vốn gốc</div></div>
          <button class="toggle" id="tglX2" onclick="toggleConfig('x2_mode', this)"></button>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #1a1a26; gap: 10px;">
          <div><div style="font-weight: 700; font-size: 13px;">Thông báo thắng</div></div>
          <button class="toggle" id="tglNotifyWin" onclick="toggleConfig('notify_win', this)"></button>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; gap: 10px;">
          <div><div style="font-weight: 700; font-size: 13px;">Thông báo thua</div></div>
          <button class="toggle" id="tglNotifyLose" onclick="toggleConfig('notify_lose', this)"></button>
        </div>

        <div style="margin-top: 12px;">
          <label class="label-xs" style="display:block; margin-bottom: 6px;">Vốn cược mỗi phiên (Win)</label>
          <div style="display: flex; gap: 8px;">
            <input type="number" id="inpBaseBet" class="input mono" value="10000" step="1000" min="1000">
            <button onclick="saveBaseBet()" class="btn" style="padding: 10px 16px; white-space: nowrap;">Lưu</button>
          </div>
          <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 8px;">
            <button onclick="setBet(10000)" class="btn btn-ghost" style="padding: 6px; font-size: 11px;">10K</button>
            <button onclick="setBet(50000)" class="btn btn-ghost" style="padding: 6px; font-size: 11px;">50K</button>
            <button onclick="setBet(100000)" class="btn btn-ghost" style="padding: 6px; font-size: 11px;">100K</button>
            <button onclick="setBet(500000)" class="btn btn-ghost" style="padding: 6px; font-size: 11px;">500K</button>
          </div>
        </div>

        <div style="margin-top: 14px;">
          <label class="label-xs" style="display:block; margin-bottom: 6px;">Chốt lãi tự động (Win)</label>
          <input type="number" id="inpTarget" class="input mono" placeholder="VD: 500000 (trống = tắt)" step="10000" onblur="saveTarget()">
        </div>

        <div style="margin-top: 14px;">
          <label class="label-xs" style="display:block; margin-bottom: 6px;">Ngưỡng confidence tối thiểu</label>
          <input type="range" min="60" max="85" value="68" id="inpConfThresh" oninput="document.getElementById('confThreshVal').textContent=this.value+'%'; saveConfThresh()" style="width: 100%; accent-color: #6366f1;">
          <div style="text-align: right; font-size: 12px; color: #a5b4fc; font-weight: 700; margin-top: 4px;" id="confThreshVal">68%</div>
        </div>

        <div style="margin-top: 14px;">
          <label class="label-xs" style="display:block; margin-bottom: 6px;">Cắt lỗ (Win)</label>
          <input type="number" id="inpStopLoss" class="input mono" value="500000" step="100000" onblur="saveStopLoss()">
        </div>
      </div>

      <div class="card">
        <h3 class="label-xs" style="margin: 0 0 12px;">Nhập code LC79</h3>
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div>
            <label class="label-xs" style="display:block; margin-bottom: 4px;">JWT Token</label>
            <input type="password" id="inpJwt" class="input mono" style="font-size: 11px;" placeholder="eyJhbGci...">
          </div>
          <div>
            <label class="label-xs" style="display:block; margin-bottom: 4px;">API Endpoint</label>
            <input type="text" id="inpLcApi" class="input mono" style="font-size: 11px;" value="https://api.lc79.luxury/v1/code/redeem">
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <input type="checkbox" id="chkStrip4" checked style="width: 16px; height: 16px; accent-color: #6366f1;">
            <label for="chkStrip4" style="font-size: 11px; color: #a1a1aa;">Bỏ 4 ký tự cuối</label>
          </div>
          <div>
            <label class="label-xs" style="display:block; margin-bottom: 4px;">Mã code</label>
            <input type="text" id="inpCode" class="input mono" style="text-transform: uppercase;" placeholder="WEYJZQLYBLC79" onkeydown="if(event.key==='Enter') submitCode()">
          </div>
          <button onclick="submitCode()" id="btnSubmitCode" class="btn" style="width: 100%;">Submit code</button>
        </div>
      </div>

      <div class="card">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
          <h3 class="label-xs" style="margin: 0;">Logs</h3>
          <button onclick="document.getElementById('logsBox').innerHTML=''" style="font-size: 10px; color: #71717a; background: none; border: none; cursor: pointer; font-weight: 700;">CLEAR</button>
        </div>
        <div id="logsBox" class="scroll" style="max-height: 300px; overflow-y: auto; padding-right: 2px;"></div>
      </div>

      <div class="card">
        <h3 class="label-xs" style="margin: 0 0 10px;">Top AI Cores</h3>
        <div id="aiWeights" style="display: flex; flex-direction: column; gap: 6px;"></div>
      </div>
    </div>
  </div>
</section>
</main>

<footer style="text-align: center; padding: 24px 12px; font-size: 10px; color: #52525b; font-weight: 600; letter-spacing: 0.05em;">
  ULTRA VIP V4 · Confidence Gating · Top-K Consensus · Kelly Sizing
</footer>

<script>
// ===== DISABLE PINCH-ZOOM & DOUBLE-TAP ZOOM =====
document.addEventListener('gesturestart', e => e.preventDefault(), { passive: false });
document.addEventListener('gesturechange', e => e.preventDefault(), { passive: false });
document.addEventListener('gestureend', e => e.preventDefault(), { passive: false });
let _lastTouchEnd = 0;
document.addEventListener('touchend', function(e) {
  const now = Date.now();
  if (now - _lastTouchEnd <= 320) e.preventDefault();
  _lastTouchEnd = now;
}, { passive: false });
document.addEventListener('wheel', function(e) { if (e.ctrlKey) e.preventDefault(); }, { passive: false });

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
  current_confidence: 0, confidence_threshold: 0.68,
  stop_loss: 500000, cooldown_remaining: 0,
};

const socket = io({ query: { client_id: CLIENT_ID }, transports: ['websocket','polling'] });
socket.on('connect', () => { setStatus(true, 'Đã kết nối'); refreshState(); });
socket.on('disconnect', () => setStatus(false, 'Mất kết nối'));
socket.on('log', (e) => appendLog(e));
socket.on('status', (d) => {
  if (d.connected) setStatus(true, 'Game online');
  else setStatus(false, d.error ? ('Lỗi: ' + d.error).slice(0, 40) : 'Game offline');
});

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
  if (d.skip_reason) { sr.textContent = '🛑 ' + d.skip_reason; sr.style.display = 'block'; }
  else sr.style.display = 'none';
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
  btn.disabled = true; btn.textContent = 'Đang đăng nhập...';
  err.style.display = 'none';
  try {
    const r = await api('/api/login', 'POST', { username: u, password: p });
    if (r.ok) await refreshState();
    else { err.textContent = '❌ ' + (r.error || 'Đăng nhập thất bại'); err.style.display = 'block'; }
  } catch(e) { err.textContent = '❌ ' + e.message; err.style.display = 'block'; }
  btn.disabled = false; btn.textContent = 'Đăng nhập';
}

async function doLogout() { await api('/api/logout', 'POST'); await refreshState(); }

async function doReconnect() {
  const r = await api('/api/reconnect', 'POST');
  if (r.ok) showToast('win', '🔄 Đang reconnect WS...');
  else showToast('lose', '❌ ' + (r.error || 'Reconnect fail'));
}

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
  api('/api/config', 'POST', { base_bet: v }).then(() => { state.base_bet = v; showToast('win', `Vốn gốc: ${fmt(v)} Win`); });
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
  btn.disabled = true; btn.textContent = 'Đang gửi...';
  const r = await api('/api/code', 'POST', { code });
  btn.disabled = false; btn.textContent = 'Submit code';
  if (r.ok) showToast('win', '✅ ' + (r.message || 'Code OK'));
  else showToast('lose', '❌ ' + (r.message || 'Code fail'));
}

function showLogin() {
  document.getElementById('loginScreen').style.display = 'block';
  document.getElementById('dashboard').style.display = 'none';
}
function showDashboard() {
  document.getElementById('loginScreen').style.display = 'none';
  document.getElementById('dashboard').style.display = 'block';
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
  const sr = document.getElementById('skipReason');
  if (state.skip_reason) { sr.textContent = '🛑 ' + state.skip_reason; sr.style.display = 'block'; }
  else sr.style.display = 'none';
  if (state.logs && state.logs.length) {
    document.getElementById('logsBox').innerHTML = '';
    state.logs.forEach(appendLog);
  }
  refreshAI();
}

function renderPrediction() {
  const box = document.getElementById('predictionBox');
  if (!state.current_prediction) {
    box.innerHTML = '<div style="font-size: 28px; font-weight: 800; color: #71717a;">...</div><div style="font-size: 11px; color: #52525b; margin-top: 2px;">chờ session</div>';
    return;
  }
  const isTai = state.current_prediction === 'TAI';
  box.innerHTML = `
    <div style="font-size: 30px; font-weight: 800; color: ${isTai ? '#3b82f6' : '#ef4444'};">${state.current_prediction}</div>
    <div style="font-size: 11px; color: ${isTai ? '#93c5fd' : '#fca5a5'}; margin-top: 2px; font-weight: 700;">AI CHỐT</div>
  `;
}

function renderStats() {
  const pl = state.profit_loss;
  const plEl = document.getElementById('cardPL');
  plEl.textContent = (pl >= 0 ? '+' : '') + fmt(pl);
  plEl.style.color = pl >= 0 ? '#10b981' : '#ef4444';
  document.getElementById('cardStreak').textContent = state.win_streak;
}

function renderResult(d) {
  const diceRow = document.getElementById('diceRow');
  const vals = d.dices || [0,0,0];
  diceRow.innerHTML = vals.map(v => `<div class="dice">${v||'?'}</div>`).join('');
  const badge = document.getElementById('resultBadge');
  const isTai = d.result === 'TAI';
  if (d.result === 'TAI' || d.result === 'XIU') {
    if (d.won === true) badge.innerHTML = `<span style="color:#10b981;">✅ THẮNG — ${isTai ? 'TÀI' : 'XỈU'}</span>`;
    else if (d.won === false) badge.innerHTML = `<span style="color:#ef4444;">❌ THUA — ${isTai ? 'TÀI' : 'XỈU'}</span>`;
    else badge.innerHTML = `<span style="color:#a1a1aa;">${isTai ? 'TÀI' : 'XỈU'}</span>`;
  }
  renderHistory(d.history);
}

function renderHistory(hist) {
  const c = document.getElementById('historyBars');
  const h = hist || [];
  document.getElementById('historyCount').textContent = h.length;
  c.innerHTML = h.slice(-40).map(r => {
    const isTai = r === 'TAI';
    return `<div class="history-bar ${isTai ? 'bar-tai' : 'bar-xiu'}">${isTai ? 'T' : 'X'}</div>`;
  }).join('');
}

async function refreshAI() {
  try {
    const d = await api('/api/ai');
    const box = document.getElementById('aiWeights');
    const max = d.top[0]?.[1] || 1;
    box.innerHTML = d.top.slice(0, 10).map(([name, w]) => {
      const pct = Math.round((w / max) * 100);
      return `<div>
        <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:3px;">
          <span style="font-weight:700; color:#d4d4d8;">${name}</span>
          <span class="mono" style="color:#a5b4fc; font-weight:700;">${w.toFixed(2)}</span>
        </div>
        <div class="progress"><div class="progress-fill" style="width:${pct}%;"></div></div>
      </div>`;
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
  dot.className = 'status-dot' + (ok ? ' online' : '');
  t.textContent = text;
  t.style.color = ok ? '#10b981' : '#71717a';
}

function showToast(type, msg) {
  const c = document.getElementById('toasts');
  const div = document.createElement('div');
  div.className = 'toast toast-' + type;
  div.textContent = msg;
  c.appendChild(div);
  setTimeout(() => { div.style.transition = 'opacity 0.3s'; div.style.opacity = '0'; setTimeout(()=>div.remove(), 300); }, 3500);
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
    print("⚡ ULTRA VIP V4 — FULL FIXED EDITION")
    print(f"   http://0.0.0.0:{port}")
    print(f"   Background Collector: {'BẬT' if ENABLE_BG_COLLECTOR else 'TẮT'}")
    print("   Clean UI · No Zoom · Top-K Consensus · Confidence Gating")
    print("=" * 60)

    # Khởi động background collector (nếu bật)
    threading.Thread(target=background_data_collector, daemon=True).start()

    webio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
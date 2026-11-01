from flask import Flask, render_template_string, request, jsonify
import requests, hashlib, base64, json, time, threading, random

import socketio

app = Flask(__name__)

# ==========================================================
# ⚙️ CẤU HÌNH
# ==========================================================
COLLECTOR_USER  = "HuyDaiXuLC79"
COLLECTOR_PASS  = "GiaHuy2011@"
WS_URL          = "https://wtxmd52.tele68.com"
WS_PATH         = "txmd5/"
WS_NAMESPACE    = "/txmd5"
RECONNECT_DELAY = 8
LOGIN_DELAY     = 15
MAX_HISTORY     = 200
MAX_LOGS        = 100
MIN_TRAIN       = 10

# ==========================================================
# 🌐 STATE
# ==========================================================
LOCK = threading.RLock()
STATE = {
    "logged_in": False, "nickname": None, "balance": 0,
    "ws_connected": False, "ws_error": None,
    "current_session": None, "current_state": None,
    "current_prediction": None, "current_confidence": 0.0,
    "current_result": None,
    "history": [], "sessions": [], "logs": [],
    "ai_correct": 0, "ai_total": 0, "ai_paper_correct": 0, "ai_paper_total": 0,
    # AUTO BET
    "auto_bet": False, "base_bet": 10000,
    "max_losses": 3, "consecutive_losses": 0,
    "auto_paused": False,
    "has_bet_this_session": False, "waiting_for_result": False,
    "current_bet": 0, "min_confidence": 0.55,
    "paper_bets": 0, "paper_wins": 0,
}

AI_WEIGHTS = {f"core_{i:02d}": 1.0 for i in range(1, 36)}
METHOD_WEIGHTS = {
    "markov": 2.0, "streak": 1.8, "ngram2": 1.5, "ngram3": 2.2, "ngram4": 1.8,
    "freq5": 1.0, "freq8": 1.5, "freq12": 1.8, "freq20": 2.0,
    "momentum": 1.6, "alternating": 2.5, "rsi": 1.4, "bollinger": 1.6,
}
WS_CLIENT = {"sio": None}


def log(msg):
    with LOCK:
        STATE["logs"].append({"t": time.time(), "msg": msg})
        if len(STATE["logs"]) > MAX_LOGS:
            STATE["logs"] = STATE["logs"][-MAX_LOGS:]
    print(f"[BG] {msg}", flush=True)


# ==========================================================
# 🧠 AI — ĐA TẦNG PHÂN TÍCH
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
    if cnt >= 3:  # cầu dài → bẻ
        return ("XIU" if last == "TAI" else "TAI", min(cnt / 5.0, 0.9))
    if cnt == 2:  # cầu trung bình → bám nhẹ
        return (last, 0.55)
    if cnt == 1:
        return (last, 0.45)
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
    # bias về phía ít xuất hiện hơn (mean reversion)
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
    alt = all(hist[-i-2] != hist[-i-1] for i in range(4))
    if alt: return ("XIU" if hist[-1] == "TAI" else "TAI", 0.8)
    return None

def _rsi(hist):
    """RSI-like: TAI strength vs XIU strength."""
    if len(hist) < 8: return None
    seg = hist[-8:]
    tai = seg.count("TAI")
    rsi = tai / 8 * 100
    if rsi > 65: return ("XIU", (rsi - 65) / 35)
    if rsi < 35: return ("TAI", (35 - rsi) / 35)
    return None

def _bollinger(hist):
    """Mean reversion khi lệch band."""
    if len(hist) < 12: return None
    seg = hist[-12:]
    val = [1 if v == "TAI" else 0 for v in seg]
    mean = sum(val) / 12
    std = (sum((v - mean)**2 for v in val) / 12) ** 0.5
    if std == 0: return None
    last = val[-1]
    upper = mean + 1.5 * std
    lower = mean - 1.5 * std
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
    m = _markov(hist);       m and methods.__setitem__("markov", m)
    s = _streak(hist);       s and methods.__setitem__("streak", s)
    for n in (2, 3, 4):
        v = _ngram(hist, n)
        if v: methods[f"ngram{n}"] = v
    for w in (5, 8, 12, 20):
        v = _freq(hist, w)
        if v: methods[f"freq{w}"] = v
    mo = _momentum(hist);    mo and methods.__setitem__("momentum", mo)
    a = _alternating(hist);  a and methods.__setitem__("alternating", a)
    r = _rsi(hist);          r and methods.__setitem__("rsi", r)
    b = _bollinger(hist);    b and methods.__setitem__("bollinger", b)
    return methods


def make_prediction_vip():
    """Trả về (prediction, confidence) hoặc (None, 0)."""
    with LOCK:
        hist = list(STATE["history"])
    if len(hist) < MIN_TRAIN:
        return None, 0.0

    tai_s = xiu_s = 0.0

    # 1) 35 cores voting
    for i in range(1, 36):
        v = _vote_core(i, hist)
        if not v: continue
        w = AI_WEIGHTS.get(f"core_{i:02d}", 1.0)
        if v == "TAI": tai_s += w * 0.3
        else: xiu_s += w * 0.3

    # 2) Multi-method analysis
    methods = analyze_all(hist)
    for name, (vote, conf) in methods.items():
        weight = METHOD_WEIGHTS.get(name, 1.0)
        score = conf * weight
        if vote == "TAI": tai_s += score
        else: xiu_s += score

    if tai_s == 0 and xiu_s == 0:
        return random.choice(["TAI", "XIU"]), 0.5

    total = tai_s + xiu_s
    if tai_s > xiu_s:
        return "TAI", round(tai_s / total, 3)
    elif xiu_s > tai_s:
        return "XIU", round(xiu_s / total, 3)
    return random.choice(["TAI", "XIU"]), 0.5


def update_ai_weights(result):
    with LOCK:
        hist = list(STATE["history"])
    if len(hist) < 6: return
    for i in range(1, 36):
        key = f"core_{i:02d}"
        v = _vote_core(i, hist[:-1])
        if not v: continue
        if v == result:
            AI_WEIGHTS[key] = min(AI_WEIGHTS[key] + 0.05, 5.0)
        else:
            AI_WEIGHTS[key] = max(AI_WEIGHTS[key] - 0.03, 0.1)


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
# 🔌 WEBSOCKET + AUTO BET
# ==========================================================
def run_ws_blocking(token):
    sio = socketio.Client(reconnection=True, reconnection_attempts=999,
                          logger=False, engineio_logger=False)
    WS_CLIENT["sio"] = sio

    @sio.event(namespace=WS_NAMESPACE)
    def connect():
        with LOCK:
            STATE["ws_connected"] = True; STATE["ws_error"] = None
        log("🟢 WebSocket LIVE — thu thập phiên")

    @sio.event(namespace=WS_NAMESPACE)
    def disconnect():
        with LOCK: STATE["ws_connected"] = False
        log("🔴 WS ngắt — tự reconnect")

    @sio.on("new-session", namespace=WS_NAMESPACE)
    def on_new_session(data):
        sid = data.get("id", "N/A")
        with LOCK:
            STATE["current_session"] = sid
            STATE["current_state"] = "BETTING"
            STATE["current_result"] = None
            STATE["has_bet_this_session"] = False
            STATE["waiting_for_result"] = False
            pred, conf = make_prediction_vip()
            STATE["current_prediction"] = pred
            STATE["current_confidence"] = conf
            hist_n = len(STATE["history"])
            STATE["sessions"].append({"id": sid, "result": None, "dices": None,
                                     "pred": pred, "conf": conf, "ok": None, "ts": time.time()})
            if len(STATE["sessions"]) > 100:
                STATE["sessions"] = STATE["sessions"][-100:]
        tag = f" · AI {pred} ({conf*100:.0f}%)" if pred else f" · chờ ({hist_n}/{MIN_TRAIN})"
        log(f"🔔 Phiên #{sid}{tag}")

    @sio.on("tick-update", namespace=WS_NAMESPACE)
    def on_tick(data):
        gs = data.get("state")
        with LOCK:
            STATE["current_state"] = gs
            should_bet = (
                gs == "BETTING"
                and STATE["auto_bet"]
                and not STATE["auto_paused"]
                and STATE["current_prediction"]
                and STATE["current_confidence"] >= STATE["min_confidence"]
                and not STATE["has_bet_this_session"]
            )
            if not should_bet: return
            amount = int(STATE["base_bet"])
            if amount > STATE["balance"] * 0.9:
                log("⚠️ Số dư không đủ để bet")
                return
            try:
                sio.emit("bet", {"type": STATE["current_prediction"], "amount": amount},
                         namespace=WS_NAMESPACE)
                STATE["has_bet_this_session"] = True
                STATE["waiting_for_result"] = True
                STATE["current_bet"] = amount
                log(f"🚀 BET {amount:,} → {STATE['current_prediction']} ({STATE['current_confidence']*100:.0f}%)")
            except Exception as e:
                log(f"⚠️ Bet fail: {e}")

    @sio.on("bet-result", namespace=WS_NAMESPACE)
    def on_bet_result(data):
        with LOCK:
            if "postBalance" in data:
                STATE["balance"] = data["postBalance"]

    @sio.on("session-result", namespace=WS_NAMESPACE)
    def on_session_result(data):
        result = data.get("resultTruyenThong", "N/A")
        dices = data.get("dices", [0, 0, 0])
        if result not in ("TAI", "XIU"): return

        with LOCK:
            pred = STATE["current_prediction"]
            was_betting = STATE["waiting_for_result"]
            was_paused = STATE["auto_paused"]

            ok = (pred == result) if pred else None
            STATE["current_result"] = {"result": result, "dices": dices, "ok": ok}
            if STATE["sessions"]:
                STATE["sessions"][-1].update(result=result, dices=dices, ok=ok)

            # AI accuracy (chỉ tính khi có prediction)
            if pred:
                STATE["ai_total"] += 1
                if ok: STATE["ai_correct"] += 1

            # Lưu history
            STATE["history"].append(result)
            if len(STATE["history"]) > MAX_HISTORY:
                STATE["history"] = STATE["history"][-MAX_HISTORY:]

            # ─── LOGIC AUTO BET ───
            log_parts = []
            if was_paused:
                # Đang nghỉ → paper trade để check "would-win"
                STATE["paper_bets"] += 1
                if ok:
                    STATE["paper_wins"] += 1
                    STATE["auto_paused"] = False
                    STATE["consecutive_losses"] = 0
                    log_parts.append("🟢 AI đúng trong lúc nghỉ → BẬT LẠI auto bet")
                else:
                    log_parts.append("⏸ vẫn nghỉ (AI sai)")
            elif was_betting:
                if ok:
                    STATE["consecutive_losses"] = 0
                    log_parts.append(f"✅ Thắng · chuỗi thua reset")
                else:
                    STATE["consecutive_losses"] += 1
                    if STATE["consecutive_losses"] >= STATE["max_losses"]:
                        STATE["auto_paused"] = True
                        log_parts.append(
                            f"🛑 THUA {STATE['consecutive_losses']} TAY → TẠM NGHỈ"
                        )
                    else:
                        log_parts.append(f"❌ Thua ({STATE['consecutive_losses']}/{STATE['max_losses']})")
                STATE["waiting_for_result"] = False

        update_ai_weights(result)

        mark = "✅" if ok else ("❌" if ok is False else "⚪")
        msg = f"{mark} {result} ({dices[0]}-{dices[1]}-{dices[2]})"
        if pred: msg += f" · AI {pred}"
        if log_parts: msg += " · " + " | ".join(log_parts)
        log(msg)

    try:
        sio.connect(WS_URL, socketio_path=WS_PATH, namespaces=[WS_NAMESPACE],
                    transports=["websocket"], auth={"token": token},
                    headers={"User-Agent": "Mozilla/5.0"})
        sio.wait()
    except Exception as e:
        with LOCK:
            STATE["ws_connected"] = False
            STATE["ws_error"] = str(e)
        log(f"⚠️ WS: {e}")


# ==========================================================
# ♻️ BACKGROUND
# ==========================================================
def background_worker():
    log(f"🚀 Collector khởi động · acc={COLLECTOR_USER}")
    while True:
        try:
            res = login_and_get_token(COLLECTOR_USER, COLLECTOR_PASS)
            if "_error" in res:
                with LOCK: STATE["ws_error"] = res["_error"]
                log(f"❌ Login fail: {res['_error']}")
                time.sleep(LOGIN_DELAY); continue
            with LOCK:
                STATE["logged_in"] = True
                STATE["nickname"] = res["nickname"]
                STATE["balance"] = res["money"]
            log(f"🔑 Login OK · {res['nickname']} · dư {res['money']:,}")
            run_ws_blocking(res["token"])
        except Exception as e:
            log(f"⚠️ Worker: {e}")
        log(f"⏳ Login lại sau {RECONNECT_DELAY}s...")
        time.sleep(RECONNECT_DELAY)

_bg_started = False
_bg_lock = threading.Lock()
def ensure_background():
    global _bg_started
    with _bg_lock:
        if _bg_started: return
        _bg_started = True
    threading.Thread(target=background_worker, daemon=True).start()


# ==========================================================
# ROUTES
# ==========================================================
@app.route("/")
def index(): return render_template_string(HTML_TEMPLATE)

@app.route("/api/state")
def api_state():
    with LOCK:
        return jsonify({
            "logged_in": STATE["logged_in"],
            "nickname": STATE["nickname"],
            "balance": STATE["balance"],
            "ws_connected": STATE["ws_connected"],
            "ws_error": STATE["ws_error"],
            "current_session": STATE["current_session"],
            "current_state": STATE["current_state"],
            "current_prediction": STATE["current_prediction"],
            "current_confidence": STATE["current_confidence"],
            "current_result": STATE["current_result"],
            "history": STATE["history"][-50:],
            "ai_correct": STATE["ai_correct"],
            "ai_total": STATE["ai_total"],
            "ai_accuracy": round(
                (STATE["ai_correct"] / STATE["ai_total"] * 100) if STATE["ai_total"] else 0, 1),
            "ai_weights_top": sorted(AI_WEIGHTS.items(), key=lambda x: x[1], reverse=True)[:10],
            "auto_bet": STATE["auto_bet"],
            "base_bet": STATE["base_bet"],
            "max_losses": STATE["max_losses"],
            "consecutive_losses": STATE["consecutive_losses"],
            "auto_paused": STATE["auto_paused"],
            "paper_bets": STATE["paper_bets"],
            "paper_wins": STATE["paper_wins"],
            "logs": STATE["logs"][-30:],
        })

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.json or {}
        with LOCK:
            if "base_bet" in data:
                STATE["base_bet"] = max(1000, int(data["base_bet"]))
            if "max_losses" in data:
                STATE["max_losses"] = max(1, min(20, int(data["max_losses"])))
            if "auto_bet" in data:
                new_val = bool(data["auto_bet"])
                STATE["auto_bet"] = new_val
                if not new_val:
                    STATE["auto_paused"] = False
                    STATE["consecutive_losses"] = 0
            msg = (f"⚙️ Lưu cài đặt · cược {STATE['base_bet']:,}đ · "
                   f"nghỉ sau {STATE['max_losses']} thua · "
                   f"Auto {'BẬT' if STATE['auto_bet'] else 'TẮT'}")
        log(msg)
        return jsonify({"success": True})
    with LOCK:
        return jsonify({
            "base_bet": STATE["base_bet"],
            "max_losses": STATE["max_losses"],
            "auto_bet": STATE["auto_bet"],
            "auto_paused": STATE["auto_paused"],
            "consecutive_losses": STATE["consecutive_losses"],
        })


# ==========================================================
# HTML
# ==========================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<title>LC79 — Live + Auto Bet</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700;800&display=swap" rel="stylesheet">
<style>
  *{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  :root{--primary:#e63946;--primary-2:#ff4d6d;--primary-dark:#b5172a;--gold:#f4b400;--accent:#ffb703;--ink:#0d1117;--muted:#6b7280;--line:#e5e7eb;--bg:#f6f7fb;--success:#10b981;--danger:#ef4444;--shadow-md:0 8px 24px rgba(15,23,42,.06)}
  body{font-family:'Plus Jakarta Sans',sans-serif;background:var(--bg);color:#1f2937;min-height:100vh;line-height:1.5;display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}
  code{user-select:text;-webkit-user-select:text}
  .header{background:rgba(255,255,255,.92);backdrop-filter:blur(14px);border-bottom:1px solid rgba(15,23,42,.06);position:sticky;top:0;z-index:100}
  .header-inner{max-width:1100px;margin:0 auto;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
  .brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}
  .brand-mark{width:40px;height:40px;border-radius:11px;background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));display:grid;place-items:center;color:#fff;font-family:'Space Grotesk';font-weight:700;font-size:12px;box-shadow:0 6px 16px rgba(230,57,70,.35)}
  .brand-name{display:flex;flex-direction:column;line-height:1.15}
  .brand-name strong{font-family:'Space Grotesk';font-size:14px;font-weight:700;color:var(--ink)}
  .brand-name small{font-size:10px;letter-spacing:1.8px;color:var(--muted);text-transform:uppercase;font-weight:600}
  .status-pill{display:inline-flex;align-items:center;gap:7px;padding:6px 13px;border-radius:999px;background:#fff;border:1px solid var(--line);font-size:12px;font-weight:600;color:var(--ink)}
  .status-dot{width:9px;height:9px;border-radius:50%;background:#9ca3af;box-shadow:0 0 0 3px rgba(0,0,0,.08)}
  .status-dot.live{background:#10b981;box-shadow:0 0 0 3px rgba(16,185,129,.28);animation:pulse 1.5s infinite}
  .status-dot.off{background:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.28)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}

  .dash{flex:1;max-width:1100px;width:100%;margin:0 auto;padding:20px;display:flex;flex-direction:column;gap:14px}
  .welcome-card{background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));color:#fff;padding:22px 24px;border-radius:18px;display:flex;align-items:center;gap:16px;box-shadow:0 10px 26px rgba(230,57,70,.28);position:relative;overflow:hidden}
  .welcome-card::after{content:'';position:absolute;width:220px;height:220px;border-radius:50%;background:rgba(255,255,255,.15);top:-90px;right:-70px}
  .welcome-avatar{width:56px;height:56px;border-radius:14px;background:rgba(255,255,255,.22);display:grid;place-items:center;font-size:22px;font-weight:800;font-family:'Space Grotesk';border:2px solid rgba(255,255,255,.3);text-transform:uppercase;flex-shrink:0;position:relative;z-index:1}
  .welcome-info{position:relative;z-index:1;flex:1;min-width:0}
  .welcome-info .greet{font-size:12px;opacity:.85;margin-bottom:1px}
  .welcome-info h2{font-family:'Space Grotesk';font-size:19px;font-weight:700;margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .level-badge{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;background:linear-gradient(135deg,#ffb703,#ff8c00);border-radius:999px;font-size:11px;font-weight:700;color:#1a1f2e;text-transform:uppercase}

  .card{background:#fff;border-radius:16px;padding:18px 20px;border:1px solid var(--line);box-shadow:var(--shadow-md)}
  .card h3{font-family:'Space Grotesk';font-size:14px;font-weight:700;color:var(--ink);margin-bottom:14px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .card h3 .badge{margin-left:auto;font-size:10.5px;font-weight:700;color:var(--muted);background:#f3f4f6;padding:2px 8px;border-radius:6px}

  /* SETTINGS */
  .settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px}
  @media(max-width:600px){.settings-grid{grid-template-columns:1fr}}
  .setting-item label{display:block;font-size:12px;font-weight:600;color:#374151;margin-bottom:6px}
  .setting-item input{width:100%;padding:11px 13px;font-size:14px;font-family:inherit;font-weight:600;color:var(--ink);background:#f9fafb;border:1.5px solid #e5e7eb;border-radius:9px;outline:none;transition:.2s}
  .setting-item input:focus{border-color:var(--primary);background:#fff;box-shadow:0 0 0 3px rgba(230,57,70,.1)}
  .setting-hint{font-size:11px;color:var(--muted);margin-top:4px}

  .settings-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  .btn-save{flex:1;min-width:140px;padding:12px 18px;background:linear-gradient(135deg,#3b82f6,#1d4ed8);color:#fff;border:none;border-radius:10px;font-family:inherit;font-size:13.5px;font-weight:700;cursor:pointer;box-shadow:0 4px 12px rgba(59,130,246,.3);transition:.2s}
  .btn-save:hover{transform:translateY(-1px)}
  .btn-save.saved{background:linear-gradient(135deg,#10b981,#059669)}

  .btn-auto{padding:12px 22px;border:none;border-radius:10px;font-family:inherit;font-size:13.5px;font-weight:700;cursor:pointer;transition:.25s;min-width:160px}
  .btn-auto.off{background:#f3f4f6;color:#6b7280;border:1.5px solid #e5e7eb}
  .btn-auto.on{background:linear-gradient(135deg,#10b981,#059669);color:#fff;box-shadow:0 6px 16px rgba(16,185,129,.35)}
  .btn-auto.paused{background:linear-gradient(135deg,#f59e0b,#d97706);color:#fff;box-shadow:0 6px 16px rgba(245,158,11,.35)}

  .auto-status{margin-top:12px;padding:10px 14px;border-radius:10px;background:#f8f9fb;border:1px solid #eef0f4;font-size:12.5px;color:#374151;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .auto-status.warn{background:#fffbeb;border-color:#fde68a;color:#92400e}
  .auto-status.active{background:#ecfdf5;border-color:#a7f3d0;color:#065f46}
  .auto-status.paused{background:#fef3c7;border-color:#fbbf24;color:#92400e}

  .stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
  @media(max-width:720px){.stats-grid{grid-template-columns:1fr}}
  .stat-card{background:#fff;border-radius:14px;padding:16px;border:1px solid var(--line);box-shadow:var(--shadow-md);border-left:4px solid var(--primary)}
  .stat-card.gold{border-left-color:var(--gold)}
  .stat-card.green{border-left-color:var(--success)}
  .stat-label{font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
  .stat-value{font-family:'Space Grotesk';font-size:24px;font-weight:700;color:var(--ink);letter-spacing:-.5px;word-break:break-all}
  .stat-value.pos{color:var(--success)}
  .stat-value.neg{color:var(--danger)}

  .session-card{background:linear-gradient(135deg,#1a1f2e,#0d1117);color:#fff;border-radius:18px;padding:22px 24px;box-shadow:0 12px 30px rgba(0,0,0,.18);border:1px solid rgba(255,255,255,.06)}
  .session-head{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
  .session-id{font-family:'Space Grotesk';font-size:22px;font-weight:800;letter-spacing:-.5px}
  .session-tag{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;padding:4px 10px;border-radius:6px;background:rgba(255,255,255,.1);color:#a8b3d0}
  .session-tag.betting{background:rgba(16,185,129,.15);color:#34d399}
  .pred-row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media(max-width:640px){.pred-row{grid-template-columns:1fr}}
  .pred-main,.result-main{text-align:center;padding:16px 12px;border-radius:12px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08)}
  .pred-label{font-size:11px;letter-spacing:1.5px;color:#8b949e;text-transform:uppercase;font-weight:700;margin-bottom:6px}
  .pred-big{font-family:'Space Grotesk';font-size:42px;font-weight:800;letter-spacing:-1px;line-height:1}
  .pred-big.tai{color:#60a5fa}.pred-big.xiu{color:#f87171}
  .pred-big.empty{color:#4b5563;font-size:17px;font-weight:500;letter-spacing:0}
  .pred-sub{font-size:11.5px;color:#8b949e;margin-top:6px}
  .result-big{font-family:'Space Grotesk';font-size:36px;font-weight:800;letter-spacing:-1px;line-height:1}
  .result-big.tai{color:#60a5fa}.result-big.xiu{color:#f87171}
  .result-big.empty{color:#4b5563;font-size:16px;font-weight:500}
  .dices{font-family:'Consolas',monospace;font-size:13px;color:#c9d1d9;margin-top:6px}
  .result-mark{font-size:11.5px;font-weight:700;margin-top:6px}
  .result-mark.ok{color:#34d399}.result-mark.fail{color:#f87171}.result-mark.none{color:#8b949e}

  .recent-10{display:grid;grid-template-columns:repeat(10,1fr);gap:8px}
  @media(max-width:720px){.recent-10{grid-template-columns:repeat(5,1fr)}}
  .hist-big{aspect-ratio:1;display:grid;place-items:center;border-radius:10px;font-family:'Space Grotesk';font-weight:800;font-size:18px;color:#fff;letter-spacing:-.5px}
  .hist-big.tai{background:linear-gradient(135deg,#3b82f6,#1d4ed8)}
  .hist-big.xiu{background:linear-gradient(135deg,#ef4444,#b91c1c)}
  .hist-big.empty{background:#f3f4f6;color:#d1d5db;font-size:13px}
  .history-grid{display:flex;flex-wrap:wrap;gap:5px}
  .hist-chip{min-width:34px;text-align:center;padding:5px 7px;border-radius:7px;font-size:11px;font-weight:700;color:#fff;font-family:'Space Grotesk'}
  .hist-chip.tai{background:linear-gradient(135deg,#3b82f6,#1d4ed8)}
  .hist-chip.xiu{background:linear-gradient(135deg,#ef4444,#b91c1c)}
  .hist-empty{font-size:12px;color:var(--muted);font-style:italic}

  .log-list{font-family:'Consolas',monospace;font-size:11.5px;background:#0d1117;color:#c9d1d9;padding:12px 14px;border-radius:10px;max-height:240px;overflow-y:auto;line-height:1.65;word-break:break-word}
  .log-list .t{color:#6e7681}

  .footer{background:#fff;border-top:1px solid var(--line);padding:16px 20px;text-align:center;font-size:12px;color:var(--muted);margin-top:auto}
  .footer b{background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;font-weight:700}

  .loading-overlay{position:fixed;inset:0;background:rgba(246,247,251,.95);display:grid;place-items:center;z-index:999;transition:opacity .3s;backdrop-filter:blur(4px)}
  .loading-overlay.hidden{opacity:0;pointer-events:none}
  .loading-box{background:#fff;padding:32px 40px;border-radius:18px;box-shadow:var(--shadow-md);text-align:center;max-width:360px}
  .loading-spin{width:44px;height:44px;border:4px solid #f3f4f6;border-top-color:var(--primary);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 16px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .loading-box h3{font-family:'Space Grotesk';font-size:16px;font-weight:700;color:var(--ink);margin-bottom:6px}
  .loading-box p{font-size:13px;color:var(--muted);line-height:1.6}

  @media(max-width:720px){
    .welcome-avatar{width:48px;height:48px;font-size:19px}
    .welcome-info h2{font-size:16px}
    .session-id{font-size:18px}
    .pred-big{font-size:34px}.result-big{font-size:28px}
    .dash{padding:14px;gap:12px}
    .stat-value{font-size:22px}
  }
</style>
</head>
<body>

<div class="loading-overlay" id="loadingOverlay">
  <div class="loading-box">
    <div class="loading-spin"></div>
    <h3 id="loadTitle">Đang khởi động...</h3>
    <p id="loadDesc">Backend đang login và kết nối WebSocket. Chờ ~15-30 giây.</p>
  </div>
</div>

<header class="header">
  <div class="header-inner">
    <a href="#" class="brand">
      <div class="brand-mark">LC79</div>
      <div class="brand-name"><strong>LC79 · AUTO CƯỢC</strong><small>Live · AI · Auto Bet</small></div>
    </a>
    <div class="status-pill">
      <span class="status-dot" id="wsDot"></span>
      <span id="wsLabel">Đang kết nối...</span>
    </div>
  </div>
</header>

<main class="dash">
  <div class="welcome-card">
    <div class="welcome-avatar" id="welcomeAvatar">L</div>
    <div class="welcome-info">
      <div class="greet">AI đa tầng · 35 cores + 13 phương pháp phân tích</div>
      <h2 id="welcomeName">Đang chờ dữ liệu...</h2>
      <span class="level-badge" id="statBadge">ĐANG KHỞI ĐỘNG</span>
    </div>
  </div>

  <!-- SETTINGS -->
  <div class="card">
    <h3>⚙️ Cài đặt Auto Cược</h3>
    <div class="settings-grid">
      <div class="setting-item">
        <label>💰 Tiền cược mỗi ván (VNĐ)</label>
        <input type="number" id="baseBetInput" value="10000" min="1000" step="1000">
        <div class="setting-hint">Tối thiểu 1.000đ · khuyến nghị ≤ 10% số dư</div>
      </div>
      <div class="setting-item">
        <label>🛑 Nghỉ sau N tay thua</label>
        <input type="number" id="maxLossesInput" value="3" min="1" max="20">
        <div class="setting-hint">Tự bật lại khi AI đoán đúng (paper trade)</div>
      </div>
    </div>
    <div class="settings-actions">
      <button class="btn-save" id="btnSaveSettings">💾 Lưu cài đặt</button>
      <button class="btn-auto off" id="btnToggleAuto">⚡ Bật Auto Cược</button>
    </div>
    <div class="auto-status" id="autoStatus">Auto: TẮT · sẵn sàng nhận lệnh</div>
  </div>

  <!-- Session -->
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

  <!-- Stats -->
  <div class="stats-grid">
    <div class="stat-card gold">
      <div class="stat-label">Số dư</div>
      <div class="stat-value" id="balanceVal">—</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Chuỗi thua hiện tại</div>
      <div class="stat-value" id="lossStreakVal">0</div>
    </div>
    <div class="stat-card green">
      <div class="stat-label">Độ chính xác AI</div>
      <div class="stat-value" id="accVal">0%</div>
    </div>
  </div>

  <div class="card">
    <h3>🔥 10 phiên gần nhất <span class="badge" id="recent10Badge">0/10</span></h3>
    <div class="recent-10" id="recent10"></div>
  </div>

  <div class="card">
    <h3>📜 Lịch sử 50 phiên <span class="badge" id="histBadge">0</span></h3>
    <div class="history-grid" id="historyGrid"><span class="hist-empty">Chưa có dữ liệu</span></div>
  </div>

  <div class="card">
    <h3>🧠 Top Core AI</h3>
    <div class="history-grid" id="coresGrid"><span class="hist-empty">Đang tính...</span></div>
  </div>

  <div class="card">
    <h3>📡 Log WebSocket</h3>
    <div class="log-list" id="logList">Đang chờ sự kiện...</div>
  </div>
</main>

<footer class="footer">© 2025 LC79 — <b>HuyDaiXuVN</b> · Auto Bet dùng risk management</footer>

<script>
const $ = id => document.getElementById(id);
const API = { state:'/api/state', settings:'/api/settings' };
let loadingHidden = false;
let settingsLoaded = false;

function fmt(n){ return new Intl.NumberFormat('vi-VN').format(Number(n)||0); }
function esc(s){ return String(s).replace(/[&<>"']/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }
function hideLoading(){ if(loadingHidden)return; loadingHidden=true; const el=$('loadingOverlay'); el.classList.add('hidden'); setTimeout(()=>el.remove(),400); }

async function refresh(){
  try {
    const r = await fetch(API.state);
    const s = await r.json();
    render(s);
    if (s.ws_connected || (s.history && s.history.length >= 3)) hideLoading();
    else if (s.logged_in){ $('loadTitle').textContent='Đang kết nối WS...'; $('loadDesc').textContent='Login OK, chờ phiên đầu tiên.'; }
    if (s.history && s.history.length >= 10) hideLoading();

    // Load settings lần đầu
    if (!settingsLoaded){
      $('baseBetInput').value = s.base_bet;
      $('maxLossesInput').value = s.max_losses;
      settingsLoaded = true;
    }
  } catch(e){ $('wsLabel').textContent='Mất kết nối server'; }
}

function render(s){
  // Status
  const dot = $('wsDot'), lbl = $('wsLabel');
  if (s.ws_connected){ dot.className='status-dot live'; lbl.textContent='WebSocket LIVE'; }
  else if (s.logged_in){ dot.className='status-dot off'; lbl.textContent='Reconnect...'; }
  else { dot.className='status-dot'; lbl.textContent = s.ws_error?'Lỗi login':'Khởi động...'; }

  // Welcome
  if (s.nickname){
    $('welcomeName').textContent = s.nickname;
    $('welcomeAvatar').textContent = s.nickname[0].toUpperCase();
  }
  const hist = s.history || [];
  $('statBadge').textContent = hist.length >= 10 ? '★ AI READY' : `THU THẬP ${hist.length}/10`;

  // Session
  $('sessId').textContent = s.current_session ? '#'+s.current_session : '#—';
  const tag = $('sessTag');
  const cs = (s.current_state || '').toUpperCase();
  tag.textContent = cs || 'WAITING';
  tag.className = 'session-tag ' + (cs==='BETTING'?'betting':'');

  // Prediction
  const pv = $('predVal'), ps = $('predSub');
  const p = s.current_prediction;
  const conf = s.current_confidence || 0;
  if (p === 'TAI'){ pv.textContent='🔵 TÀI'; pv.className='pred-big tai'; ps.textContent=`Confidence: ${(conf*100).toFixed(1)}%`; }
  else if (p === 'XIU'){ pv.textContent='🔴 XỈU'; pv.className='pred-big xiu'; ps.textContent=`Confidence: ${(conf*100).toFixed(1)}%`; }
  else { pv.textContent = hist.length < 10 ? `Chờ (${hist.length}/10)` : 'Chưa có dự đoán'; pv.className='pred-big empty'; ps.textContent='Đang tích lũy...'; }

  // Result
  const rv = $('resultVal'), rd = $('resultDices'), rm = $('resultMark');
  const r = s.current_result;
  if (r && r.result){
    rv.textContent = r.result === 'TAI' ? '🔵 TÀI' : '🔴 XỈU';
    rv.className = 'result-big ' + (r.result==='TAI'?'tai':'xiu');
    rd.textContent = (r.dices||[]).join(' · ') || '—';
    if (r.ok === true){ rm.textContent='✓ AI đúng'; rm.className='result-mark ok'; }
    else if (r.ok === false){ rm.textContent='✗ AI sai'; rm.className='result-mark fail'; }
    else { rm.textContent='—'; rm.className='result-mark none'; }
  } else {
    rv.textContent='—'; rv.className='result-big empty';
    rd.textContent='— · — · —'; rm.textContent='—'; rm.className='result-mark none';
  }

  // Stats
  $('balanceVal').textContent = fmt(s.balance);
  $('lossStreakVal').textContent = s.consecutive_losses || 0;
  $('lossStreakVal').className = 'stat-value ' + (s.consecutive_losses >= s.max_losses ? 'neg' : '');
  $('accVal').textContent = (s.ai_accuracy || 0) + '%';
  $('accVal').className = 'stat-value ' + (s.ai_accuracy >= 50 ? 'pos' : (s.ai_total > 0 ? 'neg' : ''));

  // Auto status
  const st = $('autoStatus'), btn = $('btnToggleAuto');
  if (!s.auto_bet){
    btn.textContent = '⚡ Bật Auto Cược'; btn.className = 'btn-auto off';
    st.className = 'auto-status';
    st.textContent = 'Auto: TẮT · nhập tiền cược rồi bật để bắt đầu';
  } else if (s.auto_paused){
    btn.textContent = '⏸ Đang nghỉ (chờ thắng)'; btn.className = 'btn-auto paused';
    st.className = 'auto-status paused';
    st.textContent = `⏸ TẠM NGHỈ do thua ${s.consecutive_losses} tay liên tiếp · paper trade ${s.paper_wins}/${s.paper_bets} · tự bật lại khi AI đoán đúng`;
  } else {
    btn.textContent = '🛑 Tắt Auto Cược'; btn.className = 'btn-auto on';
    st.className = 'auto-status active';
    st.textContent = `✅ ĐANG AUTO · ${fmt(s.base_bet)}đ/ván · thua ${s.consecutive_losses}/${s.max_losses} tay → nghỉ`;
  }

  // 10 phiên
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

  // History
  const hg = $('historyGrid');
  if (hist.length) hg.innerHTML = hist.slice(-50).map(v => `<span class="hist-chip ${v==='TAI'?'tai':'xiu'}">${v==='TAI'?'T':'X'}</span>`).join('');
  else hg.innerHTML = '<span class="hist-empty">Chưa có dữ liệu</span>';
  $('histBadge').textContent = hist.length;

  // Cores
  const cg = $('coresGrid');
  if (s.ai_weights_top && s.ai_weights_top.length){
    cg.innerHTML = s.ai_weights_top.map(([k,v]) =>
      `<span class="hist-chip tai" style="min-width:auto;padding:5px 10px;background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe">${esc(k)} · ${v.toFixed(2)}</span>`).join('');
  }

  // Logs
  const ll = $('logList');
  if (s.logs && s.logs.length){
    ll.innerHTML = s.logs.map(l => {
      const t = new Date(l.t*1000).toLocaleTimeString('vi-VN');
      return `<div><span class="t">[${t}]</span> ${esc(l.msg)}</div>`;
    }).join('');
    ll.scrollTop = ll.scrollHeight;
  }
}

// Save settings
$('btnSaveSettings').addEventListener('click', async () => {
  const base_bet = parseInt($('baseBetInput').value) || 10000;
  const max_losses = parseInt($('maxLossesInput').value) || 3;
  const btn = $('btnSaveSettings');
  try {
    const r = await fetch(API.settings, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ base_bet, max_losses })
    });
    if ((await r.json()).success){
      btn.textContent = '✅ Đã lưu'; btn.classList.add('saved');
      setTimeout(()=>{ btn.textContent = '💾 Lưu cài đặt'; btn.classList.remove('saved'); }, 1800);
      refresh();
    }
  } catch(e){ alert('Lỗi lưu cài đặt'); }
});

// Toggle Auto
$('btnToggleAuto').addEventListener('click', async () => {
  // Save settings trước để đảm bảo base_bet mới nhất được áp dụng
  const base_bet = parseInt($('baseBetInput').value) || 10000;
  const max_losses = parseInt($('maxLossesInput').value) || 3;
  const st = await (await fetch(API.state)).json();
  const newAuto = !st.auto_bet;
  await fetch(API.settings, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ base_bet, max_losses, auto_bet: newAuto })
  });
  refresh();
});

// Auto refresh
refresh();
setInterval(refresh, 1500);
</script>
</body>
</html>
"""


ensure_background()

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 LC79 AUTO BET · Live Monitor")
    print(f"   Collector: {COLLECTOR_USER}")
    print(f"   WebSocket: {WS_URL}/{WS_PATH}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
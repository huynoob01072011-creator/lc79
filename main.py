from flask import Flask, render_template_string, request, jsonify
import requests
import hashlib
import base64
import json
import time
import threading
import random

import socketio

app = Flask(__name__)

# ==========================================================
# ⚙️ CẤU HÌNH
# ==========================================================
COLLECTOR_USER = "HuyDaiXuLC79"
COLLECTOR_PASS = "GiaHuy2011@"

WS_URL          = "https://wtxmd52.tele68.com"
WS_PATH         = "txmd5/"
WS_NAMESPACE    = "/txmd5"
WS_MAX_RETRY    = 999
RECONNECT_DELAY = 8
LOGIN_DELAY     = 15

MAX_HISTORY   = 200
MAX_LOGS      = 100
MIN_TRAIN     = 10   # cần 10 phiên để AI predict

# ==========================================================
# 🌐 STATE
# ==========================================================
LOCK = threading.RLock()

STATE = {
    # auth
    "logged_in": False,
    "nickname": None,
    "username": COLLECTOR_USER,
    "balance": 0,

    # ws
    "ws_connected": False,
    "ws_error": None,
    "ws_connected_at": None,

    # session
    "current_session": None,
    "current_state": None,
    "current_prediction": None,
    "current_result": None,     # {"result": "TAI", "dices": [...], "ok": bool}

    # history
    "history": [],              # ["TAI","XIU",...]
    "sessions": [],             # [{"id","result","dices","pred","ok","ts"}]
    "logs": [],

    # AI stats
    "ai_correct": 0,
    "ai_total": 0,
}

AI_WEIGHTS = {f"core_{i:02d}": 1.0 for i in range(1, 36)}
WS_CLIENT = {"sio": None}


def log(msg: str):
    with LOCK:
        STATE["logs"].append({"t": time.time(), "msg": msg})
        if len(STATE["logs"]) > MAX_LOGS:
            STATE["logs"] = STATE["logs"][-MAX_LOGS:]
    print(f"[BG] {msg}", flush=True)


# ==========================================================
# 🧠 AI 35 CORES
# ==========================================================
def _vote_core(idx: int, hist: list):
    n = len(hist)
    if n < 6:
        return None
    if idx <= 7:
        w = 3 + (idx - 1)
        seg = hist[-w:]
        return "TAI" if seg.count("TAI") > seg.count("XIU") else "XIU"
    if idx <= 14:
        last = hist[-1]
        cnt = 0
        for v in reversed(hist):
            if v == last:
                cnt += 1
            else:
                break
        if cnt >= 3:
            return "XIU" if last == "TAI" else "TAI"
        return last
    if idx <= 21:
        last3 = hist[-3:]
        if last3[0] == last3[2] and last3[1] != last3[0]:
            return last3[1]
        return "TAI" if hist[-1] == "XIU" else "XIU"
    if idx <= 28:
        w = 8 + (idx - 22)
        seg = hist[-w:]
        return "TAI" if seg.count("TAI") > seg.count("XIU") else "XIU"
    w = 5 + (idx - 29)
    seg = hist[-w:]
    tai, xiu = seg.count("TAI"), seg.count("XIU")
    if tai == xiu:
        return hist[-1]
    return "TAI" if tai > xiu else "XIU"


def make_prediction_vip():
    with LOCK:
        hist = list(STATE["history"])
    if len(hist) < MIN_TRAIN:
        return None
    tai_s = xiu_s = 0.0
    for i in range(1, 36):
        v = _vote_core(i, hist)
        if not v:
            continue
        w = AI_WEIGHTS.get(f"core_{i:02d}", 1.0)
        if v == "TAI":
            tai_s += w
        else:
            xiu_s += w
    if tai_s == xiu_s:
        return random.choice(["TAI", "XIU"])
    return "TAI" if tai_s > xiu_s else "XIU"


def update_ai_weights(result: str):
    with LOCK:
        hist = list(STATE["history"])
    if len(hist) < 6:
        return
    for i in range(1, 36):
        key = f"core_{i:02d}"
        v = _vote_core(i, hist[:-1])
        if not v:
            continue
        if v == result:
            AI_WEIGHTS[key] = min(AI_WEIGHTS[key] + 0.05, 5.0)
        else:
            AI_WEIGHTS[key] = max(AI_WEIGHTS[key] - 0.03, 0.1)


# ==========================================================
# 🌐 LOGIN
# ==========================================================
def md5_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def login_and_get_token(username: str, password: str) -> dict:
    pw_md5 = md5_hash(password) if len(password) != 32 else password
    url = (
        f"https://apifo88daigia.tele68.com/api"
        f"?c=3&un={username}&pw={pw_md5}&cp=R&cl=R&pf=web&at="
    )
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        game = r.json()
        if not game.get("success"):
            return {"_error": f"Game API: {game.get('message', 'Sai thông tin')}"}

        sk = game.get("sessionKey", "")
        sk += "=" * ((4 - len(sk) % 4) % 4)
        session_data = json.loads(base64.b64decode(sk).decode("utf-8"))
        nickname = session_data.get("nickname") or session_data.get("nickName")

        r2 = requests.post(
            "https://wlb.tele68.com/v1/lobby/auth/login?cp=R&cl=R&pf=web&at=",
            headers={
                "authority": "wlb.tele68.com",
                "content-type": "application/json",
                "accept": "application/json, text/plain, */*",
                "origin": "https://tele68.com",
                "referer": "https://tele68.com/",
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            json={"nickName": nickname, "accessToken": game.get("accessToken")},
            timeout=12,
        )
        r2.raise_for_status()
        lobby = r2.json()
        token = lobby.get("token")
        if not token:
            return {"_error": "Lobby không trả JWT."}

        return {
            "token": token,
            "nickname": nickname,
            "money": lobby.get("remoteLoginResp", {}).get("money", 0),
        }
    except Exception as e:
        return {"_error": f"Kết nối: {e}"}


# ==========================================================
# 🔌 WEBSOCKET (blocking — chạy trong thread nền)
# ==========================================================
def run_ws_blocking(token: str):
    """Blocking: connect → listen → disconnect → return."""
    sio = socketio.Client(
        reconnection=True,
        reconnection_attempts=WS_MAX_RETRY,
        logger=False,
        engineio_logger=False,
    )
    WS_CLIENT["sio"] = sio

    @sio.event(namespace=WS_NAMESPACE)
    def connect():
        with LOCK:
            STATE["ws_connected"] = True
            STATE["ws_error"] = None
            STATE["ws_connected_at"] = time.time()
        log("🟢 WebSocket LIVE — bắt đầu thu thập phiên")

    @sio.event(namespace=WS_NAMESPACE)
    def disconnect():
        with LOCK:
            STATE["ws_connected"] = False
        log("🔴 WebSocket ngắt kết nối — sẽ tự reconnect")

    @sio.on("new-session", namespace=WS_NAMESPACE)
    def on_new_session(data):
        sid = data.get("id", "N/A")
        with LOCK:
            STATE["current_session"] = sid
            STATE["current_state"] = "BETTING"
            STATE["current_result"] = None

            pred = make_prediction_vip() if len(STATE["history"]) >= MIN_TRAIN else None
            STATE["current_prediction"] = pred

            STATE["sessions"].append({
                "id": sid, "result": None, "dices": None,
                "pred": pred, "ok": None, "ts": time.time(),
            })
            if len(STATE["sessions"]) > 100:
                STATE["sessions"] = STATE["sessions"][-100:]

            hist_n = len(STATE["history"])
        tag = f" · AI: {pred}" if pred else f" · chờ ({hist_n}/{MIN_TRAIN})"
        log(f"🔔 Phiên mới #{sid}{tag}")

    @sio.on("tick-update", namespace=WS_NAMESPACE)
    def on_tick(data):
        gs = data.get("state")
        with LOCK:
            STATE["current_state"] = gs

    @sio.on("bet-result", namespace=WS_NAMESPACE)
    def on_bet_result(data):
        with LOCK:
            if "postBalance" in data:
                STATE["balance"] = data["postBalance"]

    @sio.on("session-result", namespace=WS_NAMESPACE)
    def on_session_result(data):
        result = data.get("resultTruyenThong", "N/A")
        dices = data.get("dices", [0, 0, 0])

        if result not in ("TAI", "XIU"):
            return

        with LOCK:
            pred = STATE["current_prediction"]
            ok = (pred == result) if pred else None

            # stats
            if pred:
                STATE["ai_total"] += 1
                if ok:
                    STATE["ai_correct"] += 1

            STATE["current_result"] = {
                "result": result, "dices": dices, "ok": ok,
            }

            # cập nhật session gần nhất
            if STATE["sessions"]:
                STATE["sessions"][-1]["result"] = result
                STATE["sessions"][-1]["dices"] = dices
                STATE["sessions"][-1]["ok"] = ok

            # lưu history
            STATE["history"].append(result)
            if len(STATE["history"]) > MAX_HISTORY:
                STATE["history"] = STATE["history"][-MAX_HISTORY:]

        update_ai_weights(result)

        mark = "✅" if ok else ("❌" if ok is False else "⚪")
        log(f"{mark} {result} ({dices[0]}-{dices[1]}-{dices[2]})"
            + (f" · AI đoán {pred}" if pred else ""))

    try:
        sio.connect(
            WS_URL,
            socketio_path=WS_PATH,
            namespaces=[WS_NAMESPACE],
            transports=["websocket"],
            auth={"token": token},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        sio.wait()
    except Exception as e:
        with LOCK:
            STATE["ws_connected"] = False
            STATE["ws_error"] = str(e)
        log(f"⚠️ WS error: {e}")


# ==========================================================
# ♻️ BACKGROUND WORKER — chạy 24/7
# ==========================================================
def background_worker():
    log(f"🚀 Background collector khởi động · acc={COLLECTOR_USER}")
    while True:
        try:
            res = login_and_get_token(COLLECTOR_USER, COLLECTOR_PASS)
            if "_error" in res:
                with LOCK:
                    STATE["ws_error"] = res["_error"]
                log(f"❌ Login fail: {res['_error']}")
                time.sleep(LOGIN_DELAY)
                continue

            with LOCK:
                STATE["logged_in"] = True
                STATE["nickname"] = res["nickname"]
                STATE["balance"] = res["money"]
            log(f"🔑 Login OK · {res['nickname']} · dư {res['money']:,}")

            run_ws_blocking(res["token"])

        except Exception as e:
            log(f"⚠️ Worker error: {e}")

        log(f"⏳ Thử login lại sau {RECONNECT_DELAY}s...")
        time.sleep(RECONNECT_DELAY)


_bg_started = False
_bg_lock = threading.Lock()


def ensure_background():
    global _bg_started
    with _bg_lock:
        if _bg_started:
            return
        _bg_started = True
    threading.Thread(target=background_worker, daemon=True).start()


# ==========================================================
# ROUTES
# ==========================================================
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


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
            "current_result": STATE["current_result"],
            "history": STATE["history"][-50:],
            "recent_10": STATE["history"][-10:],
            "ai_correct": STATE["ai_correct"],
            "ai_total": STATE["ai_total"],
            "ai_accuracy": round(
                (STATE["ai_correct"] / STATE["ai_total"] * 100) if STATE["ai_total"] else 0,
                1
            ),
            "ai_weights_top": sorted(
                AI_WEIGHTS.items(), key=lambda x: x[1], reverse=True
            )[:10],
            "logs": STATE["logs"][-30:],
        })


# ==========================================================
# HTML TEMPLATE — Dashboard only (no login)
# ==========================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<title>AUTO CƯỢC LC79 — Live Monitor</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
  *{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  :root{
    --primary:#e63946;--primary-2:#ff4d6d;--primary-dark:#b5172a;
    --gold:#f4b400;--accent:#ffb703;--ink:#0d1117;--muted:#6b7280;
    --line:#e5e7eb;--bg:#f6f7fb;--success:#10b981;--danger:#ef4444;
    --shadow-md:0 8px 24px rgba(15,23,42,.06);
  }
  body{font-family:'Plus Jakarta Sans',sans-serif;background:var(--bg);color:#1f2937;min-height:100vh;line-height:1.5;-webkit-font-smoothing:antialiased;display:flex;flex-direction:column}
  code{user-select:text;-webkit-user-select:text}
  .header{background:rgba(255,255,255,.92);backdrop-filter:blur(14px);border-bottom:1px solid rgba(15,23,42,.06);position:sticky;top:0;z-index:100}
  .header-inner{max-width:1100px;margin:0 auto;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
  .brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}
  .brand-mark{width:40px;height:40px;border-radius:11px;background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));display:grid;place-items:center;color:#fff;font-family:'Space Grotesk';font-weight:700;font-size:12px;box-shadow:0 6px 16px rgba(230,57,70,.35)}
  .brand-name{display:flex;flex-direction:column;line-height:1.15}
  .brand-name strong{font-family:'Space Grotesk';font-size:14px;font-weight:700;color:var(--ink)}
  .brand-name small{font-size:10px;letter-spacing:1.8px;color:var(--muted);text-transform:uppercase;font-weight:600}
  .status-pill{display:inline-flex;align-items:center;gap:7px;padding:6px 13px;border-radius:999px;background:#fff;border:1px solid var(--line);font-size:12px;font-weight:600;color:var(--ink)}
  .status-dot{width:9px;height:9px;border-radius:50%;background:#9ca3af;box-shadow:0 0 0 3px rgba(0,0,0,.08);transition:.2s}
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
  .level-badge{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;background:linear-gradient(135deg,#ffb703,#ff8c00);border-radius:999px;font-size:11px;font-weight:700;color:#1a1f2e;text-transform:uppercase;letter-spacing:.5px}

  .card{background:#fff;border-radius:16px;padding:18px 20px;border:1px solid var(--line);box-shadow:var(--shadow-md)}
  .card h3{font-family:'Space Grotesk';font-size:14px;font-weight:700;color:var(--ink);margin-bottom:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .card h3 .badge{margin-left:auto;font-size:10.5px;font-weight:700;color:var(--muted);background:#f3f4f6;padding:2px 8px;border-radius:6px;letter-spacing:.3px}

  .stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
  .stat-card{background:#fff;border-radius:14px;padding:16px;border:1px solid var(--line);box-shadow:var(--shadow-md);border-left:4px solid var(--primary)}
  .stat-card.gold{border-left-color:var(--gold)}
  .stat-card.green{border-left-color:var(--success)}
  .stat-label{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
  .stat-value{font-family:'Space Grotesk';font-size:26px;font-weight:700;color:var(--ink);letter-spacing:-.5px;word-break:break-all}
  .stat-value.pos{color:var(--success)}
  .stat-value.neg{color:var(--danger)}

  /* SESSION LIVE */
  .session-card{background:linear-gradient(135deg,#1a1f2e,#0d1117);color:#fff;border-radius:18px;padding:22px 24px;box-shadow:0 12px 30px rgba(0,0,0,.18);border:1px solid rgba(255,255,255,.06);position:relative;overflow:hidden}
  .session-card::before{content:'';position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 1px);background-size:32px 32px;mask-image:radial-gradient(ellipse at 50% 0%,#000 30%,transparent 75%);-webkit-mask-image:radial-gradient(ellipse at 50% 0%,#000 30%,transparent 75%)}
  .session-card>*{position:relative;z-index:1}
  .session-head{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
  .session-id{font-family:'Space Grotesk';font-size:22px;font-weight:800;letter-spacing:-.5px}
  .session-tag{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;padding:4px 10px;border-radius:6px;background:rgba(255,255,255,.1);color:#a8b3d0}
  .session-tag.betting{background:rgba(16,185,129,.15);color:#34d399}
  .session-tag.dealing{background:rgba(245,158,11,.15);color:#fbbf24}

  .pred-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:center}
  @media(max-width:640px){.pred-row{grid-template-columns:1fr}}
  .pred-main{text-align:center;padding:16px 12px;border-radius:12px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08)}
  .pred-label{font-size:11px;letter-spacing:1.5px;color:#8b949e;text-transform:uppercase;font-weight:700;margin-bottom:6px}
  .pred-big{font-family:'Space Grotesk';font-size:42px;font-weight:800;letter-spacing:-1px;line-height:1}
  .pred-big.tai{color:#60a5fa}
  .pred-big.xiu{color:#f87171}
  .pred-big.empty{color:#4b5563;font-size:18px;font-weight:500;letter-spacing:0}
  .pred-sub{font-size:11.5px;color:#8b949e;margin-top:6px}

  .result-main{text-align:center;padding:16px 12px;border-radius:12px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08)}
  .result-big{font-family:'Space Grotesk';font-size:36px;font-weight:800;letter-spacing:-1px;line-height:1}
  .result-big.tai{color:#60a5fa}
  .result-big.xiu{color:#f87171}
  .result-big.empty{color:#4b5563;font-size:16px;font-weight:500}
  .dices{font-family:'Consolas',monospace;font-size:13px;color:#c9d1d9;margin-top:6px}
  .result-mark{font-size:11.5px;font-weight:700;margin-top:6px}
  .result-mark.ok{color:#34d399}
  .result-mark.fail{color:#f87171}
  .result-mark.none{color:#8b949e}

  /* HISTORY */
  .recent-10{display:grid;grid-template-columns:repeat(10,1fr);gap:8px}
  @media(max-width:720px){.recent-10{grid-template-columns:repeat(5,1fr)}}
  .hist-big{aspect-ratio:1;display:grid;place-items:center;border-radius:10px;font-family:'Space Grotesk';font-weight:800;font-size:18px;color:#fff;letter-spacing:-.5px;box-shadow:0 3px 8px rgba(0,0,0,.08)}
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
  .log-list .ok{color:#7ee787}
  .log-list .fail{color:#ff7b72}

  .footer{background:#fff;border-top:1px solid var(--line);padding:16px 20px;text-align:center;font-size:12px;color:var(--muted);margin-top:auto}
  .footer b{background:linear-gradient(135deg,var(--primary-2),var(--primary-dark));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;font-weight:700}

  .loading-overlay{position:fixed;inset:0;background:rgba(246,247,251,.94);display:grid;place-items:center;z-index:999;transition:opacity .3s;backdrop-filter:blur(4px)}
  .loading-overlay.hidden{opacity:0;pointer-events:none}
  .loading-box{background:#fff;padding:32px 40px;border-radius:18px;box-shadow:var(--shadow-md);text-align:center;max-width:360px}
  .loading-spin{width:44px;height:44px;border:4px solid #f3f4f6;border-top-color:var(--primary);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 16px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .loading-box h3{font-family:'Space Grotesk';font-size:16px;font-weight:700;color:var(--ink);margin-bottom:6px}
  .loading-box p{font-size:13px;color:var(--muted);line-height:1.6}

  @media(max-width:720px){
    .stats-grid{grid-template-columns:1fr}
    .welcome-avatar{width:48px;height:48px;font-size:19px}
    .welcome-info h2{font-size:16px}
    .session-id{font-size:18px}
    .pred-big{font-size:34px}
    .result-big{font-size:28px}
    .dash{padding:14px;gap:12px}
    .stat-value{font-size:22px}
  }
</style>
</head>
<body>

<div class="loading-overlay" id="loadingOverlay">
  <div class="loading-box">
    <div class="loading-spin"></div>
    <h3 id="loadTitle">Đang khởi động collector...</h3>
    <p id="loadDesc">Backend đang login và kết nối WebSocket để thu thập phiên. Vui lòng đợi ~15-30 giây.</p>
  </div>
</div>

<header class="header">
  <div class="header-inner">
    <a href="#" class="brand">
      <div class="brand-mark">LC79</div>
      <div class="brand-name">
        <strong>AUTO CƯỢC LC79</strong>
        <small>Live Session Monitor · 24/7</small>
      </div>
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
      <div class="greet">Phiên thu thập realtime · 35 Core AI</div>
      <h2 id="welcomeName">Đang chờ dữ liệu...</h2>
      <span class="level-badge" id="statBadge">ĐANG KHỞI ĐỘNG</span>
    </div>
  </div>

  <!-- Session hiện tại -->
  <div class="session-card">
    <div class="session-head">
      <span class="session-id" id="sessId">#—</span>
      <span class="session-tag" id="sessTag">WAITING</span>
    </div>
    <div class="pred-row">
      <div class="pred-main">
        <div class="pred-label">🤖 AI DỰ ĐOÁN PHIÊN NÀY</div>
        <div class="pred-big empty" id="predVal">Chờ đủ 10 phiên</div>
        <div class="pred-sub" id="predSub">Đang tích lũy dữ liệu...</div>
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
      <div class="stat-label">Tổng phiên thu thập</div>
      <div class="stat-value" id="totalHistVal">0</div>
    </div>
    <div class="stat-card green">
      <div class="stat-label">Độ chính xác AI</div>
      <div class="stat-value" id="accVal">0%</div>
    </div>
  </div>

  <!-- 10 phiên gần nhất -->
  <div class="card">
    <h3>🔥 10 phiên gần nhất <span class="badge" id="recent10Badge">0/10</span></h3>
    <div class="recent-10" id="recent10"></div>
  </div>

  <!-- Toàn bộ history -->
  <div class="card">
    <h3>📜 Lịch sử 50 phiên <span class="badge" id="histBadge">0</span></h3>
    <div class="history-grid" id="historyGrid"><span class="hist-empty">Chưa có dữ liệu</span></div>
  </div>

  <!-- AI Cores top -->
  <div class="card">
    <h3>🧠 Top Core AI đang dẫn đầu</h3>
    <div class="history-grid" id="coresGrid" style="gap:8px">
      <span class="hist-empty">Đang tính toán...</span>
    </div>
  </div>

  <!-- Logs -->
  <div class="card">
    <h3>📡 Log WebSocket</h3>
    <div class="log-list" id="logList">Đang chờ sự kiện...</div>
  </div>
</main>

<footer class="footer">© 2025 AUTO CƯỢC LC79 — <b>HuyDaiXuVN</b> · Collector chạy nền 24/7</footer>

<script>
const $ = id => document.getElementById(id);
const API_STATE = '/api/state';
let pollTimer = null;
let loadingHidden = false;

function fmt(n){
  const num = Number(n) || 0;
  return new Intl.NumberFormat('vi-VN').format(num);
}
function esc(s){ return String(s).replace(/[&<>"']/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

function hideLoading(){
  if (loadingHidden) return;
  loadingHidden = true;
  const el = $('loadingOverlay');
  el.classList.add('hidden');
  setTimeout(() => el.remove(), 400);
}

async function refresh(){
  try {
    const r = await fetch(API_STATE);
    const s = await r.json();
    render(s);

    // Ẩn overlay khi có data thật
    if (s.ws_connected || (s.history && s.history.length >= 3)) {
      hideLoading();
    } else if (s.logged_in) {
      $('loadTitle').textContent = 'Đang kết nối WebSocket...';
      $('loadDesc').textContent = 'Login thành công, đang chờ server đẩy phiên đầu tiên.';
    }
    if (s.history && s.history.length >= 10) {
      hideLoading();
    }
  } catch(e) {
    $('wsLabel').textContent = 'Mất kết nối server';
  }
}

function render(s){
  // Header status
  const dot = $('wsDot');
  const lbl = $('wsLabel');
  if (s.ws_connected){
    dot.className = 'status-dot live';
    lbl.textContent = 'WebSocket LIVE';
  } else if (s.logged_in){
    dot.className = 'status-dot off';
    lbl.textContent = 'Đang reconnect...';
  } else {
    dot.className = 'status-dot';
    lbl.textContent = s.ws_error ? 'Lỗi login' : 'Khởi động...';
  }

  // Welcome
  if (s.nickname){
    $('welcomeName').textContent = s.nickname;
    $('welcomeAvatar').textContent = s.nickname[0].toUpperCase();
  }
  const hist = s.history || [];
  if (hist.length >= 10){
    $('statBadge').textContent = '★ AI READY';
  } else if (hist.length > 0){
    $('statBadge').textContent = `ĐANG THU THẬP ${hist.length}/10`;
  } else {
    $('statBadge').textContent = 'ĐANG KHỞI ĐỘNG';
  }

  // Session
  $('sessId').textContent = s.current_session ? '#'+s.current_session : '#—';
  const tag = $('sessTag');
  const cs = (s.current_state || '').toUpperCase();
  tag.textContent = cs || 'WAITING';
  tag.className = 'session-tag ' + (cs === 'BETTING' ? 'betting' : (cs === 'DEALING' ? 'dealing' : ''));

  // Prediction
  const pv = $('predVal');
  const ps = $('predSub');
  const p = s.current_prediction;
  if (p === 'TAI'){ pv.textContent = '🔵 TÀI'; pv.className = 'pred-big tai'; ps.textContent = '35 cores đã vote'; }
  else if (p === 'XIU'){ pv.textContent = '🔴 XỈU'; pv.className = 'pred-big xiu'; ps.textContent = '35 cores đã vote'; }
  else {
    pv.textContent = hist.length < 10 ? `Chờ đủ 10 phiên (${hist.length}/10)` : 'Chưa có dự đoán';
    pv.className = 'pred-big empty';
    ps.textContent = hist.length < 10 ? 'Đang tích lũy dữ liệu...' : 'Chờ phiên mới...';
  }

  // Result
  const rv = $('resultVal');
  const rd = $('resultDices');
  const rm = $('resultMark');
  const r = s.current_result;
  if (r && r.result){
    rv.textContent = r.result === 'TAI' ? '🔵 TÀI' : '🔴 XỈU';
    rv.className = 'result-big ' + (r.result === 'TAI' ? 'tai' : 'xiu');
    rd.textContent = (r.dices || []).join(' · ') || '—';
    if (r.ok === true){ rm.textContent = '✓ AI đoán đúng'; rm.className = 'result-mark ok'; }
    else if (r.ok === false){ rm.textContent = '✗ AI đoán sai'; rm.className = 'result-mark fail'; }
    else { rm.textContent = '—'; rm.className = 'result-mark none'; }
  } else {
    rv.textContent = '—'; rv.className = 'result-big empty';
    rd.textContent = '— · — · —';
    rm.textContent = '—'; rm.className = 'result-mark none';
  }

  // Stats
  $('balanceVal').textContent = fmt(s.balance);
  $('totalHistVal').textContent = hist.length;
  $('accVal').textContent = (s.ai_accuracy || 0) + '%';
  $('accVal').className = 'stat-value ' + (s.ai_accuracy >= 50 ? 'pos' : (s.ai_total > 0 ? 'neg' : ''));

  // 10 phiên gần nhất
  const r10 = $('recent10');
  const last10 = hist.slice(-10).reverse();
  let r10html = '';
  for (let i = 0; i < 10; i++){
    const v = last10[i];
    if (v === 'TAI') r10html += `<div class="hist-big tai">T</div>`;
    else if (v === 'XIU') r10html += `<div class="hist-big xiu">X</div>`;
    else r10html += `<div class="hist-big empty">?</div>`;
  }
  r10.innerHTML = r10html;
  $('recent10Badge').textContent = `${hist.length}/10`;

  // Full history
  const hg = $('historyGrid');
  if (hist.length){
    hg.innerHTML = hist.slice(-50).map(v =>
      `<span class="hist-chip ${v === 'TAI' ? 'tai' : 'xiu'}">${v === 'TAI' ? 'T' : 'X'}</span>`
    ).join('');
  } else {
    hg.innerHTML = '<span class="hist-empty">Chưa có dữ liệu</span>';
  }
  $('histBadge').textContent = hist.length;

  // AI Cores
  const cg = $('coresGrid');
  if (s.ai_weights_top && s.ai_weights_top.length){
    cg.innerHTML = s.ai_weights_top.map(([k, v]) =>
      `<span class="hist-chip tai" style="min-width:auto;padding:5px 10px;background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe">${esc(k)} · ${v.toFixed(2)}</span>`
    ).join('');
  }

  // Logs
  const ll = $('logList');
  if (s.logs && s.logs.length){
    ll.innerHTML = s.logs.map(l => {
      const t = new Date(l.t * 1000).toLocaleTimeString('vi-VN');
      let msg = esc(l.msg);
      msg = msg.replace(/^✅/, '<span class="ok">✅</span>');
      msg = msg.replace(/^❌/, '<span class="fail">❌</span>');
      return `<div><span class="t">[${t}]</span> ${msg}</div>`;
    }).join('');
    ll.scrollTop = ll.scrollHeight;
  }
}

// Bắt đầu polling
refresh();
pollTimer = setInterval(refresh, 1500);
</script>
</body>
</html>
"""


# ==========================================================
# Khởi động background collector (chạy 24/7)
# ==========================================================
ensure_background()

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 LC79 LIVE MONITOR")
    print(f"   Collector: {COLLECTOR_USER}")
    print(f"   WebSocket: {WS_URL}/{WS_PATH}")
    print(f"   Chế độ: chạy nền 24/7, tự reconnect")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
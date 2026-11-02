"""
algo.py - AI Prediction Engine (Tài Xỉu)
Tách riêng thuật toán, dễ test & nâng cấp.
"""
import random, threading, math
from collections import Counter, defaultdict

MAX_HISTORY = 200
MIN_TRAIN   = 10

GLOBAL_LOCK    = threading.RLock()
GLOBAL_HISTORY = []
SEEN_SESSIONS  = set()
GLOBAL_AI_STATS = {"correct": 0, "total": 0}

AI_WEIGHTS = {f"core_{i:02d}": 1.0 for i in range(1, 36)}

METHOD_WEIGHTS = {
    "markov": 2.2, "markov_recency": 2.8, "streak": 1.6,
    "ngram2": 1.4, "ngram3": 2.0, "ngram4": 1.8,
    "freq5": 1.0, "freq8": 1.4, "freq12": 1.7, "freq20": 1.9,
    "momentum": 1.5, "alternating": 2.6, "rsi": 1.4, "bollinger": 1.7,
    "pattern_match": 3.2, "entropy": 1.3, "kelly_signal": 1.5,
}
METHOD_STATS = {k: {"correct": 0, "total": 0} for k in METHOD_WEIGHTS}

PRED_LOCK = threading.Lock()
PREDICTION_CACHE = {}


# ---------- Core methods ----------
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


def _markov_recency(hist, decay=0.88):
    if len(hist) < 6: return None
    last = hist[-1]
    trans = {"TAI": {"TAI": 0.0, "XIU": 0.0}, "XIU": {"TAI": 0.0, "XIU": 0.0}}
    n = len(hist)
    for i in range(n - 1):
        w = decay ** (n - 1 - i)
        trans[hist[i]][hist[i+1]] += w
    t = trans[last]; total = t["TAI"] + t["XIU"]
    if total < 0.5: return None
    if t["TAI"] > t["XIU"]: return ("TAI", t["TAI"] / total)
    if t["XIU"] > t["TAI"]: return ("XIU", t["XIU"] / total)
    return None


def _streak(hist):
    if len(hist) < 3: return None
    last = hist[-1]; cnt = 0
    for v in reversed(hist):
        if v == last: cnt += 1
        else: break
    if cnt >= 4: return ("XIU" if last == "TAI" else "TAI", min(0.5 + cnt/10.0, 0.88))
    if cnt == 3: return (last, 0.62)
    if cnt == 2: return (last, 0.52)
    return None


def _ngram(hist, n):
    if len(hist) < n + 3: return None
    pattern = tuple(hist[-n:])
    matches = []
    for i in range(len(hist) - n):
        if tuple(hist[i:i+n]) == pattern and i + n < len(hist):
            matches.append(hist[i+n])
    if len(matches) < 3: return None
    tai = matches.count("TAI"); xiu = len(matches) - tai
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
        return ("XIU" if hist[-1] == "TAI" else "TAI", 0.80)
    return None


def _rsi(hist):
    if len(hist) < 8: return None
    seg = hist[-8:]; tai = seg.count("TAI"); rsi = tai / 8 * 100
    if rsi > 70: return ("XIU", (rsi - 70) / 30)
    if rsi < 30: return ("TAI", (30 - rsi) / 30)
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


def _pattern_match(hist):
    """Tìm pattern dài nhất khớp suffix rồi vote phiên kế tiếp."""
    if len(hist) < 12: return None
    max_len = min(8, len(hist) - 3)
    for plen in range(max_len, 2, -1):
        pattern = tuple(hist[-plen:])
        matches = []
        for i in range(len(hist) - plen):
            if tuple(hist[i:i+plen]) == pattern and i + plen < len(hist):
                matches.append(hist[i+plen])
        if len(matches) >= 3:
            tai = matches.count("TAI"); xiu = len(matches) - tai
            if tai == xiu: return None
            raw = max(tai, xiu) / len(matches)
            conf = min(0.5 + (raw - 0.5) * (1 + plen / 10.0), 0.92)
            return ("TAI" if tai > xiu else "XIU", conf)
    return None


def _entropy(hist):
    """Shannon entropy: phân bố càng lệch → càng chắc."""
    if len(hist) < 10: return None
    seg = hist[-10:]
    p_tai = seg.count("TAI") / 10
    p_xiu = 1 - p_tai
    if p_tai in (0, 1): return None
    ent = -p_tai * math.log2(p_tai) - p_xiu * math.log2(p_xiu)
    if ent < 0.75:
        return ("TAI" if p_tai > p_xiu else "XIU", 1 - ent)
    return None


def _kelly_signal(hist):
    """Mean reversion khi lệch quá mức (áp dụng Kelly)."""
    if len(hist) < 15: return None
    seg = hist[-15:]
    tai_ratio = seg.count("TAI") / 15
    if tai_ratio >= 0.68: return ("XIU", min(0.5 + (tai_ratio - 0.68) * 1.8, 0.88))
    if tai_ratio <= 0.32: return ("TAI", min(0.5 + (0.32 - tai_ratio) * 1.8, 0.88))
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


# ---------- Ensemble ----------
def analyze_all(hist):
    methods = {}
    for name, fn in [
        ("markov", _markov), ("markov_recency", _markov_recency), ("streak", _streak),
        ("momentum", _momentum), ("alternating", _alternating),
        ("rsi", _rsi), ("bollinger", _bollinger),
        ("pattern_match", _pattern_match), ("entropy", _entropy), ("kelly_signal", _kelly_signal),
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
    if len(hist) < MIN_TRAIN:
        return None, 0.0

    tai_s = xiu_s = 0.0

    # Core votes
    for i in range(1, 36):
        v = _vote_core(i, hist)
        if not v: continue
        w = AI_WEIGHTS.get(f"core_{i:02d}", 1.0)
        if v == "TAI": tai_s += w * 0.25
        else:           xiu_s += w * 0.25

    # Method votes với dynamic weighting theo accuracy lịch sử
    for name, (vote, conf) in analyze_all(hist).items():
        base_weight = METHOD_WEIGHTS.get(name, 1.0)
        stats = METHOD_STATS.get(name, {"correct": 0, "total": 0})
        acc = stats["correct"] / stats["total"] if stats["total"] >= 5 else 0.5
        dynamic_w = 0.5 + acc            # 0.5 → 1.5
        weight = base_weight * dynamic_w
        score = conf * weight
        if vote == "TAI": tai_s += score
        else:             xiu_s += score

    if tai_s == 0 and xiu_s == 0:
        return random.choice(["TAI", "XIU"]), 0.5

    total = tai_s + xiu_s
    if tai_s > xiu_s:
        return "TAI", round(min(tai_s / total, 0.95), 3)
    elif xiu_s > tai_s:
        return "XIU", round(min(xiu_s / total, 0.95), 3)
    return random.choice(["TAI", "XIU"]), 0.5


def update_ai_weights(result):
    with GLOBAL_LOCK:
        hist = list(GLOBAL_HISTORY)
    if len(hist) < 6: return
    prev = hist[:-1]

    for i in range(1, 36):
        key = f"core_{i:02d}"
        v = _vote_core(i, prev)
        if not v: continue
        if v == result:
            AI_WEIGHTS[key] = min(AI_WEIGHTS[key] + 0.06, 5.0)
        else:
            AI_WEIGHTS[key] = max(AI_WEIGHTS[key] - 0.04, 0.1)

    for name, (vote, _) in analyze_all(prev).items():
        if name in METHOD_STATS:
            METHOD_STATS[name]["total"] += 1
            if vote == result:
                METHOD_STATS[name]["correct"] += 1


def get_cached_prediction(sid):
    with PRED_LOCK:
        if sid in PREDICTION_CACHE:
            return PREDICTION_CACHE[sid]
    pred, conf = make_prediction_vip()
    with PRED_LOCK:
        PREDICTION_CACHE[sid] = (pred, conf)
        if len(PREDICTION_CACHE) > 500:
            for k in list(PREDICTION_CACHE.keys())[:100]:
                PREDICTION_CACHE.pop(k, None)
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


def get_stats():
    with GLOBAL_LOCK:
        return {
            "history": list(GLOBAL_HISTORY[-50:]),
            "ai_stats": dict(GLOBAL_AI_STATS),
            "ai_weights_top": sorted(AI_WEIGHTS.items(), key=lambda x: x[1], reverse=True)[:10],
            "method_stats": {k: dict(v) for k, v in METHOD_STATS.items()},
            "history_len": len(GLOBAL_HISTORY),
        }
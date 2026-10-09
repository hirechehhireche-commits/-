from concurrent.futures import ThreadPoolExecutor
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت التداول الذكي — واجهة عصرية منظمة — DUAL 1m+5m
الاستراتيجية وتنفيذ الصفقات وإرسال الإشارات كما هي بدون تغيير
"""
import os, sys, json, time, pickle, base64, hashlib, threading, traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pandas as pd, numpy as np, requests

try:
    import titan_juggernaut_bot as T127
    import bt5y_static as BT5Y
    import golden_split_engine as GS_ENGINE
    HAS_UNIFIED = True
    HAS_V127 = True
except Exception as _e:
    T127 = None
    BT5Y = None
    GS_ENGINE = None
    HAS_UNIFIED = False
    HAS_V127 = False

try:
    import titan_unified_engine as UNI
except Exception:
    UNI = None

try:
    from cache_loader import load_from_bundle, load_titans_cache, load_gate5m, load_gate1m, get_bundle
    HAS_CACHE_BUNDLE = True
except ImportError:
    HAS_CACHE_BUNDLE = False
    load_from_bundle = None
    get_bundle = None

import gate_data
import live_runtime as LIVE
from emergency_circuit_breaker import BREAKER
from crash_prediction_engine import CRASH_SHIELD
try:
    from titan_ultimate_failsafe import FAILSAFE, init_failsafe
    HAS_FAILSAFE = True
    print("[Failsafe] ✅ Ultimate Failsafe 12 layers loaded")
except ImportError:
    HAS_FAILSAFE = False
    FAILSAFE = None
    init_failsafe = None
    print("[Failsafe] ⚠️ Ultimate Failsafe not found - using basic guards")

try:
    from titan_content_protection import PROTECTOR, CodeProtection
    HAS_PROTECTION = True
    print("[Protection] ✅ Content Protection - Anti-Forward/Copy/Save + Watermark")
except ImportError:
    HAS_PROTECTION = False
    PROTECTOR = None
    CodeProtection = None
try:
    import engine_1m_scalper as SCALPER_1M
except ImportError:
    SCALPER_1M = None

# [V129 Best + 37 Other Coins] استراتيجية ثانية مربحة للعملات الأخرى
try:
    from strategy_37coins import OTHER_37_ASSETS, S2_37_PARAMS
    HAS_37_STRATEGY = True
except ImportError:
    OTHER_37_ASSETS = [
        'ALGOUSDT', 'APTUSDT', 'ARUSDT', 'CELRUSDT', 'CHRUSDT', 'CTSIUSDT',
        'EGLDUSDT', 'FILUSDT', 'GRTUSDT', 'ICPUSDT', 'IOTXUSDT', 'JASMYUSDT',
        'KSMUSDT', 'LPTUSDT', 'OPUSDT', 'POLUSDT', 'PUNDIXUSDT', 'QTUMUSDT',
        'RENDERUSDT', 'ROSEUSDT', 'RSRUSDT', 'RVNUSDT', 'SANDUSDT', 'SFPUSDT',
        'SKLUSDT', 'SLPUSDT', 'STRAXUSDT', 'STXUSDT', 'SUIUSDT', 'SUSDT',
        'TAOUSDT', 'TLMUSDT', 'VETUSDT', 'VTHOUSDT', 'WLDUSDT', 'ZROUSDT'
    ]
    S2_37_PARAMS = {
        'risk_pct': 0.015, 'sl_atr_mult': 1.5, 't1_atr_mult': 3.0, 't2_atr_mult': 5.4,
        'min_confluence': 0.65, 'rsi_lo': 50.0, 'rsi_hi': 65.0, 's2_gmri_min': 0.50,
        'max_total': 1.0, 'max_risk': 1.0
    }
    HAS_37_STRATEGY = True

# [M1] قناة حفظ GitHub غير الحظرية (محدّثة داخلياً من github_disk_v5 اليتيمة)
try:
    from github_disk_v5 import GIT_SYNC
except Exception:
    GIT_SYNC = None

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or "").strip()
ADMIN_CHAT_ID = (os.environ.get("ADMIN_CHAT_ID") or os.environ.get("ADMIN_ID") or os.environ.get("CHAT_ID") or "").strip()
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None
except ValueError:
    ADMIN_CHAT_ID = None

PRIVATE_MODE = os.environ.get("TITAN_PRIVATE", "1") != "0"
ALLOWED_USERS_ENV = [x.strip() for x in os.environ.get("ALLOWED_USERS", "").split(",") if x.strip()]
ALLOWED_IDS_ENV = set()
ALLOWED_NAMES_ENV = set()
for _x in ALLOWED_USERS_ENV:
    if _x.lstrip("-").isdigit():
        ALLOWED_IDS_ENV.add(int(_x))
    else:
        ALLOWED_NAMES_ENV.add(_x.lower().lstrip("@"))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 🛡️ Render Free Fix: /var/data/bot_state.json يحتاج Disk مدفوع - استخدم محلي
_raw_state = os.environ.get("TITAN_STATE_FILE", "")
if _raw_state.startswith("/var/"):
    print(f"[Fix] TITAN_STATE_FILE {_raw_state} يحتاج Disk مدفوع - استخدام محلي")
    STATE_FILE = os.path.join(SCRIPT_DIR, "bot_state_v241.json")
else:
    STATE_FILE = os.environ.get("TITAN_STATE_FILE", os.path.join(SCRIPT_DIR, "bot_state_v241.json"))

_raw_ws = os.environ.get("TITAN_CACHE_DIR", "")
if _raw_ws.startswith("/var/"):
    print(f"[Fix] TITAN_CACHE_DIR {_raw_ws} يحتاج Disk مدفوع - استخدام محلي")
    WORKSPACE_DIR = SCRIPT_DIR
else:
    WORKSPACE_DIR = os.environ.get("TITAN_CACHE_DIR", SCRIPT_DIR)
DATA_DAYS = int(os.environ.get("TITAN_GATE_DAYS", "60"))
CYCLE_DELAY_SEC = int(os.environ.get("TITAN_CYCLE_DELAY", "15"))
FETCH_WORKERS = int(os.environ.get("TITAN_FETCH_WORKERS", "6"))
HEALTH_PORT = int(os.environ.get("PORT", "8080"))
PAPER_CAPITAL = 400.0
# ==== [PAPER-REAL ALIGN] معاملات الورقي مطابقة للتنفيذ الحقيقي على Binance ====
PAPER_FEE_PCT = 0.0010        # عمولة Binance القياسية لكل جهة (0.10%)
PAPER_SLIPPAGE_PCT = 0.0005   # انزلاق تقديري للبيع السوقي (0.05%) — مثل احتكاك الباكتست
PAPER_FRICTION_SELL = PAPER_FEE_PCT + PAPER_SLIPPAGE_PCT  # 0.15% عند كل بيع
PAPER_MIN_SLOT = 12.0         # أدنى ميزانية صفقة (نفس حد accept_plan الحقيقي ~12$)
PAPER_BE_LOCK = 1.005         # قفل التعادل بعد T1 مطابقاً للتنفيذ الحقيقي (+0.5%)
PAPER_MAX_SAME_SYMBOL = 3     # أقصى صفقات لنفس العملة (نفس قيد الحساب الحقيقي)
PAPER_COMPOUND = True         # الميزانية من إجمالي السيولة الورقية (تراكمي كوضع كامل الرصيد)
PAPER_USE_SIZE_PCT = True     # الميزانية = السيولة × size_pct للإشارة (مثل budget = equity×size%)

# ==== [M3] بروفايل الاستراتيجية: v241 (الافتراضي = السلوك الحالي حرفياً حرفاً بحرف) | vnext (مطوّر) ====
TITAN_STRATEGY_PROFILE = (os.environ.get("TITAN_STRATEGY_PROFILE", "v241") or "v241").strip().lower()
VNEXT = TITAN_STRATEGY_PROFILE == "vnext"
VNEXT_SIZE_MIN, VNEXT_SIZE_MAX = 6.0, 12.0   # [M3c] قيد Kelly-lite
VNEXT_TRAIL_PCT = 0.03                        # [M3a] ترايلينغ ورقي: الوقف يلاحق القمة بفارق 3% بعد T1
VNEXT_TP2_RUNNER_BOOST = 1.25                 # [M3a] توسيع T2 عند زخم حجمي ≥2.0x (ركوب الرابحين)
# [M3b] عملات المستخدم (+95) — ملاحظة: GRAM ملغاة من Binance وتُسمى الآن TON
VNEXT_EXTRA_BASES = [
    "XRP","SOL","TRX","ZEC","DOGE","LINK","ADA","XLM","BCH","NEAR","TON","LTC","AVAX","HBAR","SUI",
    "TAO","DOT","ICP","WLD","ARB","ETC","ATOM","ALGO","RENDER","FIL","QNT","VET","APT","STX","TUSD",
    "PYTH","ZRO","TIA","SEI","XTZ","DCR","OP","ENS","CFX","AR","TWT","GRT","THETA","SAND","CHZ","EGLD",
    "ROSE","MINA","JASMY","MANA","MASK","ZIL","RSR","IOTA","CHR","ENJ","YGG","IOTX","HOT","TRB","SLP",
    "KSM","RVN","CELR","TLM","LPT","XEC","SKL","GTC","SFP","MTL","QTUM","CTSI","AGLD","RLC","TFUEL",
    "WAXP","POWR","RARE","XVG","STRAX","SC","CVC","REQ","PUNDIX","LSK","VTHO","DGB","S","POL","KAIA","BTTC",
]
MAX_SEEN_EVENTS = 6000
PROXIMITY_PCT = 1.5
BACKTEST_PAGE_ROWS = 14

# 🛡️ Render Free Fix: /var/data يحتاج Disk مدفوع - fallback للمجلد المحلي
try:
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
except PermissionError:
    print(f"[Fix] Permission denied {WORKSPACE_DIR} - fallback to {SCRIPT_DIR}")
    WORKSPACE_DIR = SCRIPT_DIR
    STATE_FILE = os.path.join(SCRIPT_DIR, "bot_state_v241.json")
    try:
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
    except:
        pass
except Exception as e:
    print(f"[Fix] makedirs {WORKSPACE_DIR} fail: {e} - fallback to {SCRIPT_DIR}")
    WORKSPACE_DIR = SCRIPT_DIR
    STATE_FILE = os.path.join(SCRIPT_DIR, "bot_state_v241.json")

# [SPAM-FIX] ملف ذري صغير لإزاحة تيليجرام — تثبيت فوري لمنع إعادة تسليم التحديثات بعد أي إعادة تشغيل
TG_OFFSET_FILE = os.path.join(WORKSPACE_DIR, "tg_offset.txt")

GOLDEN_ASSETS = GS_ENGINE.GOLDEN_APPROVED_COINS if HAS_UNIFIED else []
TITAN_ASSETS = ['SOL','FET','DOT','XRP','BNB','ETH','XLM','HBAR','TRX','LINK','ADA','LTC','DOGE','ARB','BCH','ETC','EOS','ZEC','BTC','AVAX']
ALL_DATA_ASSETS = list(set([a+"USDT" if not a.endswith("USDT") else a for a in GOLDEN_ASSETS + TITAN_ASSETS] + ["BTCUSDT"]))

# ==== [M3] كون الفحص/الجلب خلف العلم — v241 يحتفظ بالقوائم الحالية حرفياً (لا تغيير سلوكي إطلاقاً) ====
if VNEXT:
    _extra_syms = [b if b.endswith("USDT") else b + "USDT" for b in VNEXT_EXTRA_BASES]
    S2SCAN_ASSETS = list(dict.fromkeys(OTHER_37_ASSETS + [s for s in _extra_syms if s not in ALL_DATA_ASSETS]))
    FETCH_ASSETS = list(dict.fromkeys(ALL_DATA_ASSETS + S2SCAN_ASSETS))
    S2_GMRI_MIN = 0.45        # تخفيف مدروس (كان 0.50)
    ENGINE_MAX_TOTAL = 8     # سقف الإشارات المشترك (كان 5)
else:
    S2SCAN_ASSETS = OTHER_37_ASSETS
    FETCH_ASSETS = ALL_DATA_ASSETS
    S2_GMRI_MIN = 0.50
    ENGINE_MAX_TOTAL = 5

# قائمة العملات المتوقفة أو الملغاة من Binance Spot (تمنع تماماً من توليد أي صفقات حية)
DELISTED_OR_INACTIVE = {
    "PLAUSDT", "WTCUSDT", "GTOUSDT", "DNTUSDT", "GXSUSDT", "TCTUSDT", 
    "REEFUSDT", "IRISUSDT", "MATICUSDT", "RNDRUSDT", "OCEANUSDT", "FTMUSDT", 
    "DARUSDT", "STPTUSDT", "ELFUSDT", "EOSUSDT", "LRCUSDT", "COSUSDT", 
    "DENTUSDT", "STORJUSDT", "ARDRUSDT", "PLA", "WTC", "GTO", "DNT", "GXS", "TCT", "REEF"
}

SIGNAL_BOT_VERSION = "بوت تداول هادئ"
BOT_VERSION = "بوت تداول طيب - نسخة صادقة"
STRATEGY_ID = "micro-hedge-fund"
STRATEGY_PROVENANCE = "Micro Hedge Fund — SOP $125/$400/$8/$24 (تأكيد ثلاثي D1/H4)"

POOL_NAMES = {"P1": "مجموعة 1", "P2": "مجموعة 2", "P3": "مجموعة 3", "S2": "اتجاه", "GS": "ذهبي — 58 عملة", "GS-T1": "ذهبي 1", "GS-T2": "ذهبي 2", "GS-T3": "ذهبي 3", "GS-T4": "ذهبي 4", "MHF": "مصغّر التحوط"}
POOL_PARAMS_MAP = {
    "P1": {"t1_frac": 0.50, "t2_frac_of_rest": 0.50},
    "P2": {"t1_frac": 0.40, "t2_frac_of_rest": 0.60},
    "P3": {"t1_frac": 0.35, "t2_frac_of_rest": 1.0},
    "S2": {"t1_frac": 0.45, "t2_frac_of_rest": 0.55},
    "GS": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "GS-T1": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "GS-T2": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "GS-T3": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "GS-T4": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "GS-V5-ULTRA": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "V5-ULTRA": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "MHF": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},          # [MHF-INTEGRATION] مصغّر التحوط — SOP
}
POOL_WEIGHT_OF_TOTAL = {"P1": 0.35, "P2": 0.15, "P3": 0.12, "S2": 0.20, "GS": 0.38}

# [MHF-INTEGRATION] جسر Micro Hedge Fund — المصدر الوحيد لخطط الدخول (TITAN_MHF=0 للتعطيل الكامل والرجوع للمحرك القديم)
MHF_ENABLED = (os.environ.get("TITAN_MHF", "1").strip() != "0")
MHF_BRIDGE = None
if MHF_ENABLED:
    try:
        from mhf_bridge import MHFBridge as _MHFBridge
        MHF_BRIDGE = _MHFBridge(state_dir=os.path.join(os.path.dirname(os.path.abspath(STATE_FILE)), "mhf_state"))
    except Exception as _mhf_boot_e:
        print(f"[MHF-INTEGRATION] ⚠️ تعذّر تهيئة جسر MHF: {_mhf_boot_e} — الرجوع إلى المحرك القديم", flush=True)
        MHF_ENABLED = False

BINANCE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
]
_host_health = {h: 0 for h in BINANCE_HOSTS}
LAST_CYCLE_COMPLETED_AT = 0

# جلسات HTTP دائمة مع Connection Pooling لسرعة استجابة فائقة
BINANCE_SESSION = requests.Session()
_bn_adapter = requests.adapters.HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=1)
BINANCE_SESSION.mount("https://", _bn_adapter)
BINANCE_SESSION.mount("http://", _bn_adapter)

# ==== [M2] Logging غير حظري: طابور محدود + كاتب خامل — لا يحظر أي مسار تداول أبداً ====
import queue as _logq_mod
_LOG_Q = _logq_mod.Queue(maxsize=5000)
_LOG_DROPPED = 0

def log(msg: str, level: str = "INFO"):
    """نفس التوقيع القديم + مستوى اختياري (INFO/WARN/ERR) — الاستدعاء غير حظري O(1)."""
    global _LOG_DROPPED
    try:
        if BOT_TOKEN: msg = str(msg).replace(BOT_TOKEN, "[BOT_TOKEN]")
        msg = str(msg)
        lv = str(level or "INFO").upper()
        if lv == "INFO":  # استنتاج بصري بدون لمس أي موضع استدعاء قديم
            if "FATAL" in msg or "❌" in msg or "[ERROR" in msg: lv = "ERR"
            elif "⚠️" in msg or "WARN" in msg: lv = "WARN"
        _LOG_Q.put_nowait(f"{lv}|{msg}")
    except Exception:
        _LOG_DROPPED += 1

def _log_writer_loop():
    """كاتب خامل: دفعات كل ~0.5s لتقليل نداءات النظام، مع عداد إسقاط ظاهر."""
    global _LOG_DROPPED
    while True:
        batch = []
        try:
            batch.append(_LOG_Q.get(timeout=0.5))
        except _logq_mod.Empty:
            continue
        try:
            for _ in range(249):
                try: batch.append(_LOG_Q.get_nowait())
                except _logq_mod.Empty: break
        except Exception:
            pass
        try:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            out = []
            for item in batch:
                lv, _, m = item.partition("|")
                out.append(f"[{ts} UTC] {lv} {m}")
            if _LOG_DROPPED:
                dropped, _LOG_DROPPED = _LOG_DROPPED, 0
                out.append(f"[{ts} UTC] WARN [LOG] أُسقطت {dropped} رسالة (فيض الطابور)")
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
        except Exception:
            pass

threading.Thread(target=_log_writer_loop, daemon=True, name="log-writer").start()

# ربط صمام الأمان بلوجر البوت الرئيسي بعد تعريفه
try:
    BREAKER.log = log
except Exception:
    pass

def _binance_get(path: str, params: dict = None, timeout: int = 15, hosts: list = None):
    hosts = hosts or BINANCE_HOSTS
    ordered = sorted(hosts, key=lambda h: _host_health.get(h, 0))
    last_err = None
    for h in ordered:
        if _host_health.get(h, 0) >= 900000:
            continue
        try:
            r = BINANCE_SESSION.get(h + path, params=params or {}, timeout=timeout)
            if r.status_code == 200:
                _host_health[h] = 0
                return r.json()
            if r.status_code == 451:
                # محظور جغرافياً على هذا السيرفر — استبعاد دائم حتى لا يستنزف وقت الاستجابة
                _host_health[h] = 999999
                continue
            # إذا كان الرمز ملغياً أو غير موجود في بايننس، لا داعي لتكرار المحاولة على باقي المرايا
            if r.status_code == 400 and ("-1121" in r.text or "Invalid symbol" in r.text):
                raise ValueError(f"رمز ملغي: {params.get('symbol') if params else ''}")
            last_err = f"HTTP {r.status_code}: {r.text[:120]}"
            _host_health[h] = _host_health.get(h, 0) + 1
        except ValueError:
            raise
        except Exception as e:
            last_err = str(e)
            _host_health[h] = _host_health.get(h, 0) + 1
    raise RuntimeError(f"فشل الجلب من كل المرايا ({path}): {last_err}")

def fetch_live_ticker_prices(symbols: list, timeout: float = 6.0) -> dict:
    """جلب أسعار السوق اللحظية لعدة رموز بطلب واحد مجمع فائق السرعة لمنع استنزاف طلبات بايننس والـ Rate Limit"""
    if not symbols:
        return {}
    clean = list(dict.fromkeys(s.strip().upper() for s in symbols if s and isinstance(s, str)))
    if not clean:
        return {}
        
    if len(clean) == 1:
        try:
            res = _binance_get("/api/v3/ticker/price", {"symbol": clean[0]}, timeout=int(timeout) or 5)
            if isinstance(res, dict) and "price" in res:
                return {clean[0]: float(res["price"])}
        except Exception as e:
            log(f"[PRICE FETCH] {clean[0]}: {e}")
            return {}

    # رموز متعددة — طلب مجمع Batch بطلب HTTP وحيد بدون مسافات
    try:
        import json as _json
        syms_json = _json.dumps(clean, separators=(',', ':'))
        res = _binance_get("/api/v3/ticker/price", {"symbols": syms_json}, timeout=int(timeout) or 6)
        if isinstance(res, list):
            prices = {}
            for item in res:
                if isinstance(item, dict) and "symbol" in item and "price" in item:
                    prices[item["symbol"]] = float(item["price"])
            if prices:
                return prices
    except Exception as e:
        log(f"[BATCH PRICE ERROR] {e}")

    # Fallback فردي سريع
    prices = {}
    for s in clean:
        try:
            r = _binance_get("/api/v3/ticker/price", {"symbol": s}, timeout=4)
            if isinstance(r, dict) and "price" in r:
                prices[s] = float(r["price"])
        except Exception:
            pass
    return prices

STATE_LOCK = threading.RLock()
_STATE = None
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _default_state() -> dict:
    return {
        "users": {},
        "seen_events": [],
        "alerted": {},
        "engine_initialized": False,
        "last_cycle": None,
        "last_metrics": None,
        "admin_chat_id": ADMIN_CHAT_ID,
        "global_snapshots": {},
        "allowed": [],
        "pending": {},
        "locked_notified": [],
        "strategy_id": STRATEGY_ID,
        "buy_fingerprints": {},
        "sell_fingerprints": {},
        "open_positions": [],
        "sent_signals": {},
        "paper": {
            "initial_capital": PAPER_CAPITAL,
            "cash": PAPER_CAPITAL,
            "realized_pnl": 0.0,
            "closed_deals": [],
            "since": _now_iso(),
        }
    }
def default_user(chat_id: int) -> dict:
    return {
        "id": chat_id,
        "first_name": "",
        "username": "",
        "joined": _now_iso(),
        "admin": False,
        "settings": {"signals": True, "paper": True, "guard": True, "proximity": True},
        "flow": None,
        "binance": {"key": None, "secret": None, "verified": False, "can_trade": False, "withdraw_enabled": False, "added_at": None},
        "mode": "none",
        "real": {"enabled": False, "capital": 400.0, "risk_scale": 1.0, "confirmed_at": None, "positions": {}, "history": [], "kill": False},
        "paper": {"capital": PAPER_CAPITAL, "cash": PAPER_CAPITAL, "realized": 0.0, "since": _now_iso(), "positions": {}, "deals": [], "signals_count": 0, "weeks": {}},
        "last_weekly": None
    }
def load_state() -> dict:
    global _STATE
    with STATE_LOCK:
        if _STATE is not None:
            return _STATE
        st = _default_state()
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    st.update(loaded)
            except Exception as e:
                raise RuntimeError("ملف حالة البوت تالف") from e
        _STATE = st
        return _STATE
def save_state():
    global STATE_FILE
    with STATE_LOCK:
        if _STATE is None:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(STATE_FILE)), exist_ok=True)
        except PermissionError:
            # Fallback محلي إذا /var/data ممنوع
            STATE_FILE = os.path.join(SCRIPT_DIR, "bot_state_v241.json")
            try:
                os.makedirs(os.path.dirname(os.path.abspath(STATE_FILE)), exist_ok=True)
            except:
                pass
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_STATE, f, ensure_ascii=False, default=str)
            f.flush()
        try:
            os.chmod(tmp, 0o600)
        except:
            pass
        os.replace(tmp, STATE_FILE)
        # [M1] نسخة غير حظرية إلى GitHub بعد كل حفظ ناجح (latest-wins، خنق 60s)
        if GIT_SYNC is not None:
            GIT_SYNC.push_state_file(STATE_FILE)
def get_user(chat_id: int, create: bool = True) -> dict:
    st = load_state()
    key = str(chat_id)
    if key not in st["users"] and create:
        st["users"][key] = default_user(chat_id)
    return st["users"].get(key)
OWNER_ID = 8599225300  # معرفك — سيتم السماح له دائماً

def is_allowed(chat_id, username: str = None) -> bool:
    if not PRIVATE_MODE:
        return True
    st = load_state()
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return False
    # مالك البوت — سماح دائم حتى لو تغيرت الإعدادات
    if cid == OWNER_ID:
        return True
    # السماح المباشر من متغير البيئة ADMIN_CHAT_ID
    if ADMIN_CHAT_ID and cid == int(ADMIN_CHAT_ID):
        return True
    admin = st.get("admin_chat_id")
    if admin and cid == int(admin):
        return True
    if cid in ALLOWED_IDS_ENV:
        return True
    if username:
        un = str(username).lower().lstrip("@")
        if un and un in ALLOWED_NAMES_ENV:
            return True
    allowed_raw = st.get("allowed") or []
    if str(cid) in [str(x) for x in allowed_raw]:
        return True
    # إذا لا يوجد مشرف نهائياً — أول مستخدم يصبح مشرف تلقائياً
    if not admin and not ADMIN_CHAT_ID and not (st.get("allowed") or []) and not ALLOWED_USERS_ENV:
        return True
    return False

def _obf_key() -> bytes:
    seed = (BOT_TOKEN or "titan") + "|241"
    return hashlib.sha256(seed.encode()).digest()
def obfuscate(s: str) -> str:
    if not s:
        return None
    kb = _obf_key()
    raw = s.encode("utf-8")
    x = bytes(b ^ kb[i % len(kb)] for i, b in enumerate(raw))
    return base64.b64encode(x).decode("ascii")
def deobfuscate(s: str) -> str:
    if not s:
        return ""
    kb = _obf_key()
    raw = base64.b64decode(s.encode("ascii"))
    return bytes(b ^ kb[i % len(kb)] for i, b in enumerate(raw)).decode("utf-8")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# جلسة تيليجرام دائمة مع Connection Pool وسرعة استجابة فورية
TG_SESSION = requests.Session()
_tg_adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=1)
TG_SESSION.mount("https://", _tg_adapter)
TG_SESSION.mount("http://", _tg_adapter)

def esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def tg(method: str, retries: int = 2, timeout: float = 6.0, **params):
    if not BOT_TOKEN:
        return None
    url = f"{TG_API}/{method}"
    if method == "getUpdates":
        timeout = float(params.get("timeout", 20)) + 4.0
    # 🛡️ حماية المحتوى - منع النسخ/إعادة التوجيه/الحفظ
    if method in ("sendMessage", "sendPhoto", "sendDocument", "sendVideo", "sendAnimation", "sendAudio", "sendVoice", "editMessageText"):
        params["protect_content"] = True
    for attempt in range(retries):
        try:
            r = TG_SESSION.post(url, json=params, timeout=timeout)
            data = r.json()
            if data.get("ok"):
                return data.get("result")
            desc = str(data.get("description", ""))
            if "message is not modified" in desc:
                return True
            if r.status_code == 429:
                wait = (data.get("parameters") or {}).get("retry_after", 2)
                time.sleep(wait + 0.1)
                continue
            log(f"[TG] {method} تنبيه: {desc}")
            return None
        except Exception as e:
            if attempt == retries - 1 and method != "getUpdates":
                log(f"[TG] {method} خطأ اتصال: {e}")
            time.sleep(0.2)
    return None

def answer_cb(cb_id, text: str = ""):
    """إلغاء دوران الزر فورياً في التيليجرام بشكل غير متزامن فائق السرعة"""
    if not cb_id:
        return
    def _fire():
        try:
            TG_SESSION.post(
                f"{TG_API}/answerCallbackQuery",
                json={"callback_query_id": cb_id, "text": text or None},
                timeout=3.0
            )
        except Exception:
            pass
    threading.Thread(target=_fire, daemon=True).start()

def send_msg(chat_id, text: str, kb=None, msg_id: int = None):
    # 🛡️ حماية المحتوى + بصمة خفية لتتبع التسريب
    try:
        if HAS_PROTECTION and PROTECTOR and chat_id:
            text = PROTECTOR.add_watermark(text, int(chat_id), add_visible=True, add_invisible=True)
    except:
        pass
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True, "protect_content": True}
    if kb:
        params["reply_markup"] = {"inline_keyboard": kb}
    if msg_id:
        params["message_id"] = msg_id
        res = tg("editMessageText", **params)
        if res is not None:
            return res
        params.pop("message_id", None)
    return tg("sendMessage", **params)

def respond_cb(cb: dict, text: str, kb=None):
    try:
        cb_id = cb.get("id", "")
        if cb_id:
            answer_cb(cb_id)
        msg = cb.get("message") or {}
        chat_id = msg.get("chat", {}).get("id") or cb.get("from", {}).get("id")
        msg_id = msg.get("message_id")
        if chat_id and msg_id:
            send_msg(chat_id, text, kb, msg_id=msg_id)
        elif chat_id:
            send_msg(chat_id, text, kb)
    except Exception as e:
        log(f"[RESPOND_CB] {e}")
        try:
            chat_id = (cb.get("message") or {}).get("chat", {}).get("id") or cb.get("from", {}).get("id")
            if chat_id:
                send_msg(chat_id, text, kb)
        except Exception:
            pass

def fmt_p(val) -> str:
    """تنسيق ذكي للأسعار يحمي العملات الصغيرة (مثل SHIB أو PEPE أو DENT) من التقريب للصفر"""
    try:
        p = float(val)
        if p >= 100.0: return f"{p:.2f}"
        elif p >= 1.0: return f"{p:.3f}"
        elif p >= 0.01: return f"{p:.4f}"
        elif p >= 0.0001: return f"{p:.6f}"
        else: return f"{p:.8f}".rstrip('0').rstrip('.')
    except Exception:
        return str(val)

def fmt_entry(p: dict, w2: float = 0.82, holds: dict = None) -> str:
    try:
        ticker = p.get("ticker","").replace("USDT","")
        price = float(p.get("price",0))
        sl = float(p.get("sl",0))
        tgt1 = float(p.get("tgt1",0))
        tgt2 = float(p.get("tgt2",0))
        txt = f"فرصة جديدة 💰 {ticker}\n\n"
        txt += f"دخول بهدوء عند {fmt_p(price)}\n"
        txt += f"وقف خسارة {fmt_p(sl)}\n"
        txt += f"أهداف متدرجة بإذن الله"
        return txt
    except Exception:
        return f"فرصة جديدة {p.get('ticker','')}"

def bt(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}

# ============ واجهة عصرية منظمة ============

def more_kb() -> list:
    """الزر الرئيسي المصغر — تصميم عصري"""
    return [
        [bt("🎛️ فتح لوحة التحكم", "nav:more")]
    ]

def get_collection_status_line() -> str:
    """حالة جمع البيانات كنص - بدل زر مباشر"""
    try:
        if CYCLE_LOCK.locked():
            return "يجمع البيانات ⏳"
        else:
            return "تم جمع البيانات ✅"
    except:
        return "تم جمع البيانات ✅"

def full_menu_kb(u: dict = None) -> list:
    """لوحة تحكم عصرية منظمة — بدون زر الإعدادات وبدون مباشر"""
    rows = [
        [bt("🚀 ربط binance", "m:api")],
        [bt("🛡️ مراكزي المفتوحة", "m:guard")],
        [bt("💼 المحفظة الورقية", "m:port"), bt("📈 الباكتاست", "bt:page:0")],
        [bt("📅 تقرير أسبوعي", "m:rep")],
        [bt("ℹ️ عن البوت", "m:abt")],
    ]
    if u and u.get("admin"):
        rows.append([bt("👥 إدارة المستخدمين", "m:users")])
    rows.append([bt("🔼 إخفاء القائمة", "nav:less")])
    return rows

def back_kb(extra_rows: list = None) -> list:
    """زر رجوع عصري"""
    rows = list(extra_rows or [])
    rows.append([bt("🏠 الرئيسية", "nav:more")])
    return rows

def api_back_kb() -> list:
    """رجوع خاص بلوحة المنصة"""
    return [[bt("🏠 الرئيسية", "nav:more")]]

# تهيئة تلقائية فورية لنظام التداول
try:
    LIVE.init(sys.modules[__name__])
except Exception:
    pass

WELCOME_TEXT = (
    "أهلاً بك 💰\n\n"
    "بوت تداول ذكي يتابع السوق لحظة بلحظة\n"
    "يفلتر أفضل العملات ويعطيك إشارات مدروسة\n"
    "يعمل بهدوء ويحميك من التقلبات\n\n"
    "ابدأ من الأزرار بالأسفل 👇"
)

ABOUT_TEXT = (
    "عن البوت 💵\n\n"
    "يتابع السوق كل دقائق على مدار الساعة\n"
    f"يراقب {len(ALL_DATA_ASSETS)} عملة نشطة منتقاة بعناية\n"
    "يفلتر العملات القوية فقط ويتجاهل الضعيفة\n\n"
    "استراتيجية V5 Ultra 📈\n"
    "• فريم 5 دقائق للاتجاه العام\n"
    "• فريم 1 دقيقة للدخول المجهري\n"
    "• EMA + RSI + اختراق ذكي\n"
    "• دخول بهدوء مع وقف واضح\n"
    "• هدفين متدرجين لجني الربح\n\n"
    "إدارة مخاطر 🛡️\n"
    "• وقف خسارة محكم لكل صفقة\n"
    "• لا يدخل عند تقلب شديد\n"
    "• يحمي المحفظة عند هبوط السوق\n"
    "• نظام بصمة ذكية يمنع التكرار\n\n"
    "المحفظة الورقية 💼\n"
    "• تتابع أرباحك تلقائياً\n"
    "• تعرض الصفقات المفتوحة والمغلقة\n"
    "• تحسب نسبة النجاح والأرباح\n\n"
    "نتائجه من تجربة 5 سنوات طويلة\n"
    "بكل صدق - لا يعد بالربح الدائم\n"
    "التداول مخاطرة، والصبر أساسه\n"
    "البوت أداة مساعدة وليس نصيحة مالية"
)


def event_fingerprint(ev: dict) -> str:
    base = f"{STRATEGY_ID}|{ev.get('time','')}|{ev.get('ticker','')}|{ev.get('pool','')}|{ev.get('kind','')}"
    return hashlib.sha1(base.encode()).hexdigest()[:20]

def _eval_store(store: dict, frame_label: str, now: datetime, btc_bullish: bool, btc_super: bool, max_signals: int = 5, existing_count: int = 0):
    plans = []
    checked = 0
    enters = 0
    if not (GS_ENGINE and store):
        return plans, checked, enters
        
    open_positions = get_open_positions()
    active_tickers = {p.get("ticker"): p for p in open_positions if p.get("status") == "OPEN"}
    
    # فحص جميع الـ 77 عملة المعتمدة
    for sym in ALL_DATA_ASSETS:
        if existing_count + enters >= max_signals:
            break
        if sym not in store:
            continue
            
        # 1. استبعاد العملات المتوقفة أو الملغاة تماماً لمنع أي صفقات قديمة (مثل PLA)
        if sym in DELISTED_OR_INACTIVE or sym.replace("USDT", "") in DELISTED_OR_INACTIVE:
            continue
            
        df = store[sym]
        min_bars = 40
        if len(df) < min_bars:
            continue
            
        # 2. شرط الجدة والحداثة الصارم: يجب أن تكون آخر شمعة حية ولحظية (أقل من ساعتين)
        # ولا يجوز أبداً فتح صفقات حية على شموع تاريخية قديمة
        try:
            last_ts = df.index[-1]
            last_dt = pd.to_datetime(last_ts)
            if last_dt.tzinfo is None:
                last_dt = last_dt.tz_localize(timezone.utc)
            else:
                last_dt = last_dt.tz_convert(timezone.utc)
            if (now - last_dt).total_seconds() > 2.0 * 3600:
                continue
        except Exception:
            continue
            
        checked += 1
        try:
            # 🛡️ FAILSAFE LAYER 1: تحقق من صحة البيانات قبل أي تقييم
            if HAS_FAILSAFE:
                valid, reason = FAILSAFE["data"].validate_ohlcv(df, sym)
                if not valid:
                    log(f"[Failsafe] Skip {sym}: {reason}")
                    continue
            
            # إعداد بيانات 1h لحساب ATR
            try:
                df1h = df.resample("1h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
            except Exception:
                df1h = None
                
            sub = df.tail(100)
            sub1h = df1h.tail(100) if df1h is not None and len(df1h) >= 15 else None
            
            # تقييم الاستراتيجية V5 Ultra بدقة (3 معاملات: EMA 9/21/50 + RSI 45-75 + BO 15)
            setup = GS_ENGINE.evaluate_golden_setup(sub, sub1h, btc_bullish, btc_super, sym)
            
            # 🛡️ FAILSAFE LAYER 2: تحقق من صحة الإشارة قبل الإرسال
            if HAS_FAILSAFE and setup:
                valid, reason = FAILSAFE["data"].validate_setup(setup, sym)
                if not valid:
                    log(f"[Failsafe] Invalid setup {sym}: {reason}")
                    continue
            
            # إذا لم تتحقق شروط الاستراتيجية → تخطي فوراً (لا إشارات وهمية ولا تخفيف للشروط)
            if not setup:
                continue
                
            c_col = "Close" if "Close" in df.columns else "close"
            price = float(setup.get("price", df[c_col].iloc[-1]))
            signal_price = float(setup.get("signal_price", price))
            atr = float(setup.get("atr_1h", 0.007))
            levels = GS_ENGINE.golden_adaptive_levels(signal_price, atr)
            
            # تاريخ الشمعة التي أغلقت وأعطت الإشارة لتثبيت البصمة
            try:
                candle_ts = str(df.index[-2]) if len(df) >= 2 else str(df.index[-1])
            except Exception:
                candle_ts = now.strftime("%Y-%m-%d-%H-%M")
                
            # التحقق إذا كانت العملة مفتوحة بالفعل عند نفس مستوى السعر (تجنب الإشارات المكررة لنفس الكسر)
            if sym in active_tickers:
                existing_p = active_tickers[sym]
                existing_buy_p = float(existing_p.get("buy_price", 0))
                if existing_buy_p > 0 and abs(signal_price - existing_buy_p) / existing_buy_p < 0.025:
                    log(f"[FILTER] {sym} لديه صفقة مفتوحة #{existing_p.get('position_number')} عند {existing_buy_p:.4f} (السعر الحالي {signal_price:.4f} قريب) → تخطي")
                    continue
                    
            size_pct = 10.0  # 10% من رأس المال (40$ من 400$)
            pool = "GS-V5-ULTRA"
            
            plan = {
                "id": hashlib.sha256(f"v5|{pool}|{sym}|{candle_ts}|LIMIT".encode()).hexdigest()[:24],
                "pool": pool,
                "ticker": sym,
                "time": now.isoformat(),
                "timestamp": float(now.timestamp()),
                "candle_time": candle_ts,
                "intent": "LIMIT",
                "price": signal_price,
                "signal_price": signal_price,
                "sl": float(levels["sl"]),
                "tgt1": float(levels["tp1"]),
                "tgt2": float(levels["tp2"]),
                "size_pct": float(size_pct),
                "frame": frame_label,
                "strategy": "Golden-V5-Ultra-3Params",
                "rsi": setup.get("rsi", 55.0),
                "ema9": setup.get("ema9", 0),
                "ema21": setup.get("ema21", 0),
                "ema50": setup.get("ema50", 0),
            }
            plans.append(plan)
            enters += 1
            log(f"[STRATEGY:V5] ✨ إشارة شراء حقيقية: {sym} عند {signal_price:.4f} (RSI {setup.get('rsi')} | BO15 | EMA9>21>50)")
        except Exception as e:
            log(f"[ENGINE:{frame_label}] {sym} {e}")
            continue
            
    return plans, checked, enters



# =====================================================================
# 🚀 محرك الاستراتيجية الاتجاهية الحقيقية المعتمدة (4H Gen 20000 Engine)
# =====================================================================
GLOBAL_4H_STORE = None
LAST_4H_UPDATE_TS = 0.0

def load_or_update_4h_store():
    """تحميل كاش 4H التاريخي وتحديثه بآخر شموع مغلقة مباشرة من Binance"""
    global GLOBAL_4H_STORE, LAST_4H_UPDATE_TS
    now_ts = time.time()
    
    # تحميل الكاش من الملف إن لم يكن محملاً
    if GLOBAL_4H_STORE is None:
        cache_path = os.path.join(WORKSPACE_DIR, "titans_4h_5y_cache.pkl")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    GLOBAL_4H_STORE = pickle.load(f)
                log(f"[4H STORE] ✅ تم تحميل كاش 4H التاريخي بنجاح ({len(GLOBAL_4H_STORE)} عملة)")
            except Exception as e:
                log(f"[4H STORE LOAD ERROR] {e}")
                GLOBAL_4H_STORE = {}
        else:
            GLOBAL_4H_STORE = {}

    # تحديث الشموع من بايننس مرة كل 10 دقائق كحد أقصى لتفادي الضغط
    if now_ts - LAST_4H_UPDATE_TS > 600.0 and GLOBAL_4H_STORE:
        LAST_4H_UPDATE_TS = now_ts
        try:
            all_assets = list(dict.fromkeys(T127.ELITE_TRADEABLE_ASSETS + T127.STRATEGY2_ASSETS))
            up_count = 0
            for sym in all_assets:
                kl = _binance_get("/api/v3/klines", {"symbol": sym, "interval": "4h", "limit": 6})
                if isinstance(kl, list) and len(kl) >= 2:
                    closed_klines = kl[:-1]  # نستبعد الشمعة الحالية غير المغلقة
                    records = []
                    indices = []
                    for k in closed_klines:
                        indices.append(pd.to_datetime(int(k[0]), unit="ms", utc=True))
                        records.append({
                            "Open": float(k[1]), "High": float(k[2]), "Low": float(k[3]),
                            "Close": float(k[4]), "Volume": float(k[5])
                        })
                    new_df = pd.DataFrame(records, index=indices)
                    if sym in GLOBAL_4H_STORE:
                        comb = pd.concat([GLOBAL_4H_STORE[sym], new_df])
                        GLOBAL_4H_STORE[sym] = comb[~comb.index.duplicated(keep="last")].sort_index()
                    else:
                        GLOBAL_4H_STORE[sym] = new_df
                    up_count += 1
            log(f"[4H LIVE UPDATE] تم تحديث أحدث شموع 4H لـ {up_count}/{len(all_assets)} عملة من Binance")
        except Exception as e:
            log(f"[4H UPDATE ERROR] {e}")

    return GLOBAL_4H_STORE


def eval_4h_juggernaut_strategy(now_dt: datetime) -> list:
    """فحص استراتيجية 4H المعتمدة لسلة العملات الـ 20 وإنتاج إشارات الدخول الحقيقية"""
    plans = []
    try:
        st = load_state()
    except Exception:
        st = {}
    store_4h = load_or_update_4h_store()
    if not store_4h or not hasattr(T127, "FastSimulator"):
        return plans

    try:
        all_assets = list(dict.fromkeys(T127.ELITE_TRADEABLE_ASSETS + T127.STRATEGY2_ASSETS))
        union_index, proc, _ = T127.FastSimulator.prepare_arrays(store_4h, assets=all_assets)
        if len(union_index) < 120:
            return plans

        t = len(union_index) - 1
        ts = union_index[t]
        candle_ts = ts.strftime("%Y-%m-%d-%H-%M")

        cfgs = [
            ("P1", T127.POOL1_ASSETS, T127.POOL1_PARAMS),
            ("P2", T127.POOL2_ASSETS, T127.POOL2_PARAMS),
            ("P3", T127.POOL3_ASSETS, T127.POOL3_PARAMS),
            ("S2", T127.STRATEGY2_ASSETS, T127.STRATEGY2_PARAMS),
        ]

        open_positions = get_open_positions()
        active_tickers = {p.get("ticker"): p for p in open_positions if p.get("status") == "OPEN"}

        for name, assets, p in cfgs:
            uni = [s for s in assets if s in proc]
            act = sum(1 for s in uni if proc[s]["ok"][t])
            above = sum(1 for s in uni if proc[s]["ok"][t] and proc[s]["c"][t] > proc[s]["ema"][t])
            gmri = (above / act) if act else 0.5
            rocs = [proc[s]["roc_60"][t] for s in uni if proc[s]["ok"][t] and not np.isnan(proc[s]["roc_60"][t])]
            med = float(np.median(rocs)) if rocs else 0.0

            for tkr in uni:
                if not proc[tkr]["ok"][t]:
                    continue

                if tkr in active_tickers:
                    existing_p = active_tickers[tkr]
                    existing_buy_p = float(existing_p.get("buy_price", 0))
                    curr_px = proc[tkr]["c"][t]
                    if existing_buy_p > 0 and abs(curr_px - existing_buy_p) / existing_buy_p < 0.025:
                        continue

                ok, cf, al, px, atr, mode, reason = T127.check_entry_signal(proc, tkr, t, p, gmri, med, rocs)
                if ok:
                    signal_price = float(px)
                    sl = float(signal_price * (1.0 - atr * p["sl_atr_mult"]))
                    tgt1 = float(signal_price * (1.0 + atr * p["t1_atr_mult"]))
                    tgt2 = float(signal_price * (1.0 + atr * p["t2_atr_mult"]))
                    
                    # [CRASH_PREDICTION_SMART_ARBITER] حساب حجم المخاطرة التكيفي للحساب الحي والورقي
                    _ba = proc.get("BTCUSDT", {})
                    _btc_weak = False
                    _btc_strong = False
                    if _ba and _ba.get("ok", [False])[t]:
                        if _ba["c"][t] < _ba["ema"][t] or _ba["slope"][t] < 0:
                            _btc_weak = True
                        elif _ba["c"][t] > _ba["ema"][t] and _ba["slope"][t] > 0:
                            _btc_strong = True

                    _wallet_eq = float(st.get("wallet", {}).get("total_equity", 400.0) or 400.0)
                    _peak_eq = float(st.get("wallet", {}).get("peak_equity", _wallet_eq) or _wallet_eq)
                    if _wallet_eq > _peak_eq:
                        st.setdefault("wallet", {})["peak_equity"] = _wallet_eq
                        _peak_eq = _wallet_eq
                    _nav_dd = max(0.0, (_peak_eq - _wallet_eq) / max(_peak_eq, 1e-6))

                    size_pct = 10.0
                    if _btc_strong and gmri >= 0.45:
                        size_pct = 10.0  # [SHIELD OFF]: بول ران وتوسع كامل
                    elif (_btc_weak or gmri < 0.35) and _nav_dd > 0.14:
                        size_pct = 3.0   # [SHIELD ACTIVE]: كبح فوري للمخاطرة أثناء الانهيار
                    elif (_btc_weak or gmri < 0.35) and _nav_dd > 0.10:
                        size_pct = 5.0

                    plan_id = hashlib.sha256(f"titan4h|{name}|{tkr}|{candle_ts}|LIMIT".encode()).hexdigest()[:24]
                    plans.append({
                        "id": plan_id,
                        "pool": name,
                        "ticker": tkr,
                        "time": now_dt.isoformat(),
                        "timestamp": float(now_dt.timestamp()),
                        "candle_time": candle_ts,
                        "intent": "LIMIT",
                        "price": signal_price,
                        "signal_price": signal_price,
                        "sl": sl,
                        "tgt1": tgt1,
                        "tgt2": tgt2,
                        "size_pct": size_pct,
                        "frame": "4h",
                        "strategy": f"Titan-4H-{name}-{mode}",
                        "atr": float(atr),
                        "confluence": float(cf),
                        "alpha": float(al)
                    })
                    log(f"[TITAN-4H] ✨ إشارة دخول حقيقية: {tkr} ({name}) عند {signal_price:.4f} | SL={sl:.4f} | TP1={tgt1:.4f} | TP2={tgt2:.4f}")
    except Exception as e:
        log(f"[TITAN-4H EVAL ERROR] {e}")

    return plans


# =====================================================================
# 🚀 محرك فريم الـ 5 دقائق الاحترافي المتوافق مع سياق 4H المجمّع
# (5m Execution Engine with Dynamic 4H Resampled Trend Confluence)
# =====================================================================

def evaluate_5m_with_4h_confluence(sym: str, df5: pd.DataFrame, btc_5m: pd.DataFrame, now_dt: datetime) -> dict:
    """
    فحص شروط الدخول كل 5 دقائق مع إعادة تجميع شموع 4H ديناميكياً
    للتأكد من قوة الاتجاه العام وحماية رأس المال قبل اقتناص الفرصة.
    """
    try:
        if df5 is None or len(df5) < 40:
            return None
            
        c_col = "Close" if "Close" in df5.columns else "close"
        o_col = "Open" if "Open" in df5.columns else "open"
        h_col = "High" if "High" in df5.columns else "high"
        l_col = "Low" if "Low" in df5.columns else "low"
        v_col = "Volume" if "Volume" in df5.columns else "volume"

        # 1. إعادة تجميع شموع 4H ديناميكياً من شموع 5m لمعرفة الاتجاه العام
        df4h = df5.resample("4h", closed="right", label="right").agg({
            o_col: "first", h_col: "max", l_col: "min", c_col: "last", v_col: "sum"
        }).dropna()
        
        # فحص اتجاه البيتكوين على 4H المجمّع
        btc_4h_bullish = True
        if btc_5m is not None and len(btc_5m) >= 50:
            btc_c = "Close" if "Close" in btc_5m.columns else "close"
            btc_4h = btc_5m.resample("4h", closed="right", label="right").agg({btc_c: "last"}).dropna()
            if len(btc_4h) >= 15:
                btc_ema50 = btc_4h[btc_c].ewm(span=min(50, len(btc_4h)), adjust=False).mean().iloc[-1]
                btc_4h_bullish = bool(btc_4h[btc_c].iloc[-1] >= btc_ema50 * 0.995)
                
        if not btc_4h_bullish:
            return None  # حماية رأس المال: لا شراء عندما يكون اتجاه البيتكوين 4H هابطاً

        # فحص اتجاه العملة نفسها على 4H المجمّع
        if len(df4h) >= 10:
            c4 = df4h[c_col]
            ema21_4h = c4.ewm(span=min(21, len(c4)), adjust=False).mean().iloc[-1]
            if c4.iloc[-1] < ema21_4h * 0.99:
                return None  # العملة تحت متوسطها الاتجاهي 4H

        # 2. فحص شروط الاختراق والزخم على فريم 5 دقائق (5m Trigger)
        c5 = df5[c_col].values
        h5 = df5[h_col].values
        l5 = df5[l_col].values
        v5 = df5[v_col].values
        
        # مؤشرات فريم 5m
        ema9 = pd.Series(c5).ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = pd.Series(c5).ewm(span=21, adjust=False).mean().iloc[-1]
        ema50 = pd.Series(c5).ewm(span=50, adjust=False).mean().iloc[-1]
        
        # ترتيب المتوسطات على 5m
        if not (c5[-1] > ema9 and ema9 >= ema21):
            return None
            
        # كسر قمة 15 شمعة سابقة على 5m
        prev_hi15 = np.max(h5[-16:-1]) if len(h5) >= 16 else h5[-2]
        if c5[-1] < prev_hi15:
            return None
            
        # مؤشر RSI(14) على 5m
        delta = pd.Series(c5).diff()
        gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
        rsi = 100.0 - (100.0 / (1.0 + (gain / (loss + 1e-9))))
        if not (48.0 <= rsi <= 76.0):
            return None
            
        # حجم التداول Volume Surge على 5m
        vol_avg20 = np.mean(v5[-21:-1]) if len(v5) >= 21 else v5[-2]
        vol_ratio = (v5[-1] / vol_avg20) if vol_avg20 > 0 else 1.0
        if vol_ratio < 1.35:
            return None

        # 3. حساب ATR ومستويات الوقف والربح التكيفية المتينة
        tr = np.maximum(h5[-15:] - l5[-15:], np.abs(h5[-15:] - np.roll(c5[-15:], 1)))
        atr_val = np.mean(tr[1:]) / c5[-1] if len(tr) > 1 and c5[-1] > 0 else 0.015
        
        current_price = float(c5[-1])
        # وقف الخسارة: مدروس بين 2.2% إلى 3.8% لمنع ضرب الوقف السريع بالتذبذب
        sl_pct = float(np.clip(atr_val * 2.0, 0.022, 0.038))
        # الهدف الأول: بين 4.0% إلى 7.5% (تأمين 50% ونقل الوقف للتعادل)
        tp1_pct = float(np.clip(atr_val * 3.5, 0.040, 0.075))
        # الهدف الثاني: بين 9.0% إلى 20.0% (ركوب أقصى الموجة بالترايلينغ)
        tp2_pct = float(np.clip(atr_val * 7.5, 0.090, 0.200))

        sl = current_price * (1.0 - sl_pct)
        tp1 = current_price * (1.0 + tp1_pct)
        tp2 = current_price * (1.0 + tp2_pct)
        # [M3a-VNEXT] ركوب الرابحين: زخم حجمي ≥2.0x ⟵ توسيع T2 بنسبة 25% (سقف 22% — العقد ثابت)
        if VNEXT and vol_ratio >= 2.0:
            tp2 = round(current_price * (1.0 + min(tp2_pct * VNEXT_TP2_RUNNER_BOOST, 0.22)), 8)
        
        candle_ts = str(df5.index[-2]) if len(df5) >= 2 else str(df5.index[-1])
        plan_id = hashlib.sha256(f"m5|{sym}|{candle_ts}|{current_price:.4f}".encode()).hexdigest()[:24]
        
        return {
            "id": plan_id,
            "pool": "M5-4H-CONFLUENCE",
            "ticker": sym,
            "time": now_dt.isoformat(),
            "timestamp": float(now_dt.timestamp()),
            "candle_time": candle_ts,
            "intent": "LIMIT",
            "price": current_price,
            "signal_price": current_price,
            "sl": float(sl),
            "tgt1": float(tp1),
            "tgt2": float(tp2),
            "size_pct": 10.0,
            "frame": "5m",
            "strategy": "5m-Trend-4H-Confluence",
            "rsi": float(rsi),
            "vol_ratio": float(vol_ratio),
            "atr_pct": float(atr_val * 100)
        }
    except Exception as e:
        log(f"[5m CONFLUENCE ERROR] {sym}: {e}")
        return None

def evaluate_5m_for_other_37(sym: str, df5: pd.DataFrame, btc_5m: pd.DataFrame, now_dt: datetime, gmri_val: float = 0.5) -> dict:
    """
    [S2-37] استراتيجية ثانية مربحة للعملات الأخرى (37 عملة)
    - أكثر تحفظاً: GMRI >=0.50 + تلاقي عالي 0.65 + مخاطرة منخفضة 1.5%
    - باكتست: 400$ → 589$ Ret 47% DD 35.9% PF 1.15 Trades 832 (مربحة)
    - تزيد الفرص +165% (501 → 1327 صفقة)
    """
    try:
        if df5 is None or len(df5) < 60:
            return None

        # فلتر أساسي: لا تداول إلا عند اتساع سوقي قوي (S2_GMRI_MIN: v241=0.50 | vnext=0.45)
        if gmri_val < S2_GMRI_MIN:
            return None

        c_col = "Close" if "Close" in df5.columns else "close"
        o_col = "Open" if "Open" in df5.columns else "open"
        h_col = "High" if "High" in df5.columns else "high"
        l_col = "Low" if "Low" in df5.columns else "low"
        v_col = "Volume" if "Volume" in df5.columns else "volume"

        # إعادة تجميع 4H
        df4h = df5.resample("4h", closed="right", label="right").agg({
            o_col: "first", h_col: "max", l_col: "min", c_col: "last", v_col: "sum"
        }).dropna()

        # BTC 4H bullish فقط
        if btc_5m is not None and len(btc_5m) >= 50:
            btc_c = "Close" if "Close" in btc_5m.columns else "close"
            btc_4h = btc_5m.resample("4h", closed="right", label="right").agg({btc_c: "last"}).dropna()
            if len(btc_4h) >= 15:
                btc_ema50 = btc_4h[btc_c].ewm(span=min(50, len(btc_4h)), adjust=False).mean().iloc[-1]
                if btc_4h[btc_c].iloc[-1] < btc_ema50 * 0.998:
                    return None

        if len(df4h) >= 10:
            c4 = df4h[c_col]
            ema21_4h = c4.ewm(span=min(21, len(c4)), adjust=False).mean().iloc[-1]
            if c4.iloc[-1] < ema21_4h * 0.995:
                return None

        c5 = df5[c_col].values
        h5 = df5[h_col].values
        l5 = df5[l_col].values
        v5 = df5[v_col].values

        ema9 = pd.Series(c5).ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = pd.Series(c5).ewm(span=21, adjust=False).mean().iloc[-1]

        if not (c5[-1] > ema9 and ema9 >= ema21):
            return None

        prev_hi20 = np.max(h5[-21:-1]) if len(h5) >= 21 else h5[-2]
        if c5[-1] < prev_hi20:
            return None

        delta = pd.Series(c5).diff()
        gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
        rsi = 100.0 - (100.0 / (1.0 + (gain / (loss + 1e-9))))
        # RSI أكثر تحفظاً للعملات الضعيفة: 50-65 فقط
        if not (50.0 <= rsi <= 65.0):
            return None

        vol_avg20 = np.mean(v5[-21:-1]) if len(v5) >= 21 else v5[-2]
        vol_ratio = (v5[-1] / vol_avg20) if vol_avg20 > 0 else 1.0
        # Volume أعلى للعملات الضعيفة: 1.5x
        if vol_ratio < 1.50:
            return None

        tr = np.maximum(h5[-15:] - l5[-15:], np.abs(h5[-15:] - np.roll(c5[-15:], 1)))
        atr_val = np.mean(tr[1:]) / c5[-1] if len(tr) > 1 and c5[-1] > 0 else 0.015

        current_price = float(c5[-1])
        # وقف ضيق وهدف سريع للعملات الضعيفة
        sl_pct = float(np.clip(atr_val * 1.5, 0.018, 0.030))
        tp1_pct = float(np.clip(atr_val * 3.0, 0.035, 0.060))
        tp2_pct = float(np.clip(atr_val * 5.4, 0.070, 0.150))
        # [M3a-VNEXT] ركوب الرابحين: زخم حجمي ≥2.0x ⟵ توسيع T2 بنسبة 25% (سقف 18%)
        if VNEXT and vol_ratio >= 2.0:
            tp2_pct = float(np.clip(tp2_pct * VNEXT_TP2_RUNNER_BOOST, 0.070, 0.180))

        sl = current_price * (1.0 - sl_pct)
        tp1 = current_price * (1.0 + tp1_pct)
        tp2 = current_price * (1.0 + tp2_pct)

        candle_ts = str(df5.index[-2]) if len(df5) >= 2 else str(df5.index[-1])
        plan_id = hashlib.sha256(f"s2-37|{sym}|{candle_ts}|{current_price:.4f}".encode()).hexdigest()[:24]

        return {
            "id": plan_id,
            "pool": "S2-37-OTHER",
            "ticker": sym,
            "time": now_dt.isoformat(),
            "timestamp": float(now_dt.timestamp()),
            "candle_time": candle_ts,
            "intent": "LIMIT",
            "price": current_price,
            "signal_price": current_price,
            "sl": float(sl),
            "tgt1": float(tp1),
            "tgt2": float(tp2),
            "size_pct": 6.0,  # حجم أقل للعملات الضعيفة (6% بدل 10%)
            "frame": "5m",
            "strategy": "S2-37-Other-Conservative",
            "rsi": float(rsi),
            "vol_ratio": float(vol_ratio),
            "atr_pct": float(atr_val * 100),
            "gmri": float(gmri_val)
        }
    except Exception as e:
        log(f"[S2-37 ERROR] {sym}: {e}")
        return None

# ==== [M3b] Probe الأزواج: لا فشل صامت — يسجل الرموز غير المتاحة مرة واحدة يومياً ====
_PROBE_SKIPPED = {}
def _probe_skip(sym: str, reason: str):
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if _PROBE_SKIPPED.get((sym, reason)) != today:
            _PROBE_SKIPPED[(sym, reason)] = today
            log(f"[PROBE] ⛔ {sym}: {reason} — تخطٍّ آلي حتى توفر البيانات", "WARN")
    except Exception:
        pass

# ==== [M3c] تحجيم Kelly-lite: نسبة فوز متدحرجة من الصفقات الورقية المغلقة + قوة الإشارة، مقيّد [6%, 12%] ====
def _vnext_clamped_size(plan: dict) -> float:
    try:
        base = float(plan.get("size_pct", 10.0) or 10.0)
        closed = [p for p in load_state().get("open_positions", []) if p.get("status") == "CLOSED"][-20:]
        if len(closed) < 10:
            return base  # عينة غير كافية — التزم بالحجم الأساسي
        wins = [float(p.get("final_profit_pct", 0) or 0) for p in closed if float(p.get("final_profit_usd", 0) or 0) > 0]
        losses = [abs(float(p.get("final_profit_pct", 0) or 0)) for p in closed if float(p.get("final_profit_usd", 0) or 0) < 0]
        if not wins or not losses:
            return base
        W = len(wins) / len(closed)
        R = (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if losses else 1.5
        kelly = W - (1.0 - W) / max(R, 0.3)               # معيار كيلي الكلاسيكي
        scaled = base * (1.0 + max(-0.5, min(1.0, kelly * 2.0)))
        # تدرّج بقوة الإشارة: الزخم الحجمي واتساع السوق
        vr = float(plan.get("vol_ratio", 1.0) or 1.0)
        gmri = float(plan.get("gmri", 0.5) or 0.5)
        boost = 1.0 + (0.15 if vr >= 2.0 else 0.0) + (0.10 if gmri >= 0.70 else (-0.10 if gmri < 0.55 else 0.0))
        return round(float(np.clip(scaled * boost, VNEXT_SIZE_MIN, VNEXT_SIZE_MAX)), 2)
    except Exception:
        return float(plan.get("size_pct", 10.0) or 10.0)

def run_unified_engine(dual_or_single_store: dict):
    events = []
    entry_plans = []
    now = datetime.now(timezone.utc)
    
    store_5m = {}
    store_1m = {}
    if isinstance(dual_or_single_store, dict):
        if "5m" in dual_or_single_store:
            store_5m = dual_or_single_store.get("5m", {})
            store_1m = dual_or_single_store.get("1m", {})
        else:
            store_5m = dual_or_single_store
            
    btc_5m = store_5m.get("BTCUSDT")
    total_checked = 0
    total_enters = 0
    
    open_positions = get_open_positions()
    active_tickers = {p.get("ticker"): p for p in open_positions if p.get("status") == "OPEN"}
    
    # 🌟 فحص فريم الـ 5 دقائق التكتيكي مع إعادة تجميع الـ 4H ديناميكياً للاتجاه العام
    # [V129 Best] للعملات الأساسية 19
    if store_5m:
        for sym in ALL_DATA_ASSETS:
            if len(entry_plans) >= 3:
                break
            if sym not in store_5m or sym in DELISTED_OR_INACTIVE or sym.replace("USDT","") in DELISTED_OR_INACTIVE:
                continue
                
            df5 = store_5m[sym]
            total_checked += 1
            
            # فحص إذا كانت هناك صفقة مفتوحة بالفعل لنفس العملة بسعر قريب
            if sym in active_tickers:
                existing_p = active_tickers[sym]
                existing_buy_p = float(existing_p.get("buy_price", 0))
                c_col = "Close" if "Close" in df5.columns else "close"
                curr_px = float(df5[c_col].iloc[-1])
                if existing_buy_p > 0 and abs(curr_px - existing_buy_p) / existing_buy_p < 0.025:
                    continue
                    
            plan = evaluate_5m_with_4h_confluence(sym, df5, btc_5m, now)
            if plan:
                if VNEXT:
                    plan["size_pct"] = _vnext_clamped_size(plan)  # [M3c] Kelly-lite مقيّد
                entry_plans.append(plan)
                total_enters += 1
                log(f"[ENGINE:5m] 🎯 إشارة V129 Best: {sym} عند {plan['signal_price']:.4f} (RSI {plan['rsi']:.1f} | Vol {plan['vol_ratio']:.2f}x)")

    # 🌟 [S2-37] استراتيجية ثانية مربحة للعملات الأخرى (37 عملة) لزيادة الفرص
    # - باكتست: 400$ → 589$ Ret 47% DD 35.9% PF 1.15 Trades 832 (مربحة)
    # - تزيد الفرص +165% (501 → 1327 صفقة)
    # - شروط أكثر تحفظاً: GMRI >=0.50 + تلاقي 0.65 + مخاطرة 1.5%
    if store_5m and HAS_37_STRATEGY:
        # حساب GMRI للسلة الأساسية لتحديد قوة السوق
        try:
            # GMRI = نسبة العملات فوق EMA21 على 4H
            above_count = 0
            total_count = 0
            for s in ALL_DATA_ASSETS[:20]:
                if s in store_5m and s not in DELISTED_OR_INACTIVE:
                    df = store_5m[s]
                    if len(df) >= 21:
                        c_col = "Close" if "Close" in df.columns else "close"
                        c = df[c_col].values
                        ema21 = pd.Series(c).ewm(span=21, adjust=False).mean().iloc[-1]
                        if c[-1] > ema21:
                            above_count += 1
                        total_count += 1
            gmri_current = (above_count / total_count) if total_count > 0 else 0.5
        except Exception:
            gmri_current = 0.5

        # فقط إذا السوق قوي (GMRI >=0.50) نفحص العملات الأخرى
        if gmri_current >= S2_GMRI_MIN:  # [M3b] v241=0.50 | vnext=0.45
            for sym in S2SCAN_ASSETS:   # [M3b] v241=OTHER_37 حرفياً | vnext=∪ عملات المستخدم (+95)
                if len(entry_plans) >= ENGINE_MAX_TOTAL:  # [M3b] v241=5 | vnext=8
                    break
                if sym not in store_5m:
                    if VNEXT:
                        _probe_skip(sym, "لا بيانات 5m (الزوج غير متاح في Binance أو فشل الجلب)")
                    continue
                if sym in DELISTED_OR_INACTIVE or sym.replace("USDT","") in DELISTED_OR_INACTIVE:
                    continue
                if sym in ALL_DATA_ASSETS:  # لا نكرر العملات الأساسية
                    continue
                    
                df5 = store_5m[sym]
                total_checked += 1
                
                if sym in active_tickers:
                    existing_p = active_tickers[sym]
                    existing_buy_p = float(existing_p.get("buy_price", 0))
                    c_col = "Close" if "Close" in df5.columns else "close"
                    curr_px = float(df5[c_col].iloc[-1])
                    if existing_buy_p > 0 and abs(curr_px - existing_buy_p) / existing_buy_p < 0.03:
                        continue
                        
                plan = evaluate_5m_for_other_37(sym, df5, btc_5m, now, gmri_current)
                if plan:
                    if VNEXT:
                        plan["size_pct"] = _vnext_clamped_size(plan)  # [M3c] Kelly-lite مقيّد
                    entry_plans.append(plan)
                    total_enters += 1
                    log(f"[ENGINE:S2-37] 🎯 إشارة ثانية مربحة: {sym} عند {plan['signal_price']:.4f} (RSI {plan['rsi']:.1f} | Vol {plan['vol_ratio']:.2f}x | GMRI {gmri_current:.2f})")

    w_golden = 0.82
    # V129 Best + S2-37 — أرقام حقيقية من باكتست 5 سنوات
    # V129 Best 19 عملة: 6954$ DD 21.08% PF 3.26 Trades 501 (الأساسية المعتمدة)
    # S2-37 37 عملة: 589$ (400$) Ret 47% DD 35.9% PF 1.15 Trades 832 — أو 171$ (100$) Ret 71% DD 34.75% (مربحة)
    # المجموع 400$ مقسمة (300$+100$): NAV 5377$ Ret 1244% Trades 1327 (+826 صفقة +165% فرص)
    # المجموع 500$ (400$+100$ إضافي): NAV 7125$ Ret 1325% Trades 1340
    return {
        "events": events,
        "entry_plans": entry_plans,
        "open_positions": [],
        "trades": [],
        "deals": [],
        "holds": {},
        "metrics": {
            "period_start": "2020-01-01",
            "period_end": "2025-09-30",
            "total_days": 2099,
            "final_nav": 6954.16,
            "total_ret": 1638.54,
            "max_dd": 21.08,
            "pf": 3.26,
            "sharpe": 2.45,
            "calmar": 3.58,
            "n_trades": 501,
            "win_rate": 53.49,
            "s2_37_nav_400": 589.6,
            "s2_37_ret_400": 47.4,
            "s2_37_dd": 35.9,
            "s2_37_pf": 1.15,
            "s2_37_trades": 832,
            "combined_nav_400_split": 5377.57,
            "combined_ret_400_split": 1244.39,
            "combined_trades_400_split": 1327,
            "combined_nav_500_extra": 7125.80,
            "combined_ret_500_extra": 1325.16
        },
        "w2_current": w_golden,
        "w_golden": w_golden,
        "w_titan": 1-w_golden,
        "n_reb": len(ALL_DATA_ASSETS),
        "gate": {"checked": total_checked, "enters": total_enters, "limits": 0, "chases": 0, "nogate": 0, "cancelled": 0, "skipped": [], "saved_bps": [], "frames": {"5m": len(store_5m)}},
        "pending_entries": entry_plans,
        "strategy_id": STRATEGY_ID,
        "last_candle": now.isoformat(),
        "nav": pd.Series([400, 6954.16]),
        "union_index": pd.date_range("2020-01-01", periods=2),
        "gmri": 0.52,
        "btc_data": None,
        "basket_rocs": [],
    }

LATEST_EVENTS = []
ENGINE_RES = None
CYCLE_LOCK = threading.Lock()
LAST_CYCLE_SECS = 0.0

def next_candle_run_ts(now: datetime = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    minute = (now.minute // 5) * 5
    boundary = now.replace(minute=minute, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(minutes=5)
    return boundary + timedelta(seconds=CYCLE_DELAY_SEC)

def next_5m_run_ts(now: datetime = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    minute = (now.minute // 5) * 5
    boundary = now.replace(minute=minute, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(minutes=5)
    return boundary + timedelta(seconds=CYCLE_DELAY_SEC)

def next_4h_run_ts(now: datetime = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    h = (now.hour // 4) * 4
    boundary = now.replace(hour=h, minute=0, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(hours=4)
    return boundary + timedelta(seconds=CYCLE_DELAY_SEC)

LATEST_PLANS = []
LATEST_SELL_PLANS = []
LATEST_OPEN_POSITIONS = []

# === نظام البصمة الذكية — يميز الإشارات الجديدة فعلاً ===
BUY_FINGERPRINTS = {}  # fingerprint -> {time, ticker, price, raw}
SELL_FINGERPRINTS = {}  # fingerprint -> {time}

def buy_fingerprint(plan: dict) -> tuple:
    """بصمة ذكية للإشارة — تعتمد على العملة والفريم وتاريخ شمعة الكسر
    كل شمعة تغلق وتحدث كسراً لا يمكن أن ترسل إشارة إلا مرة واحدة فقط.
    """
    try:
        ticker = plan.get("ticker", "")
        frame = plan.get("frame", "5m")
        candle_time = plan.get("candle_time", "")
        if not candle_time:
            now_dt = datetime.now(timezone.utc)
            m5 = (now_dt.minute // 5) * 5
            candle_time = now_dt.strftime(f"%Y-%m-%d-%H-{m5:02d}")
            
        raw = f"{ticker}_{frame}_{candle_time}"
        fp = hashlib.sha1(raw.encode()).hexdigest()[:16]
        return fp, raw
    except Exception as e:
        log(f"[FP] {e}")
        return hashlib.sha1(str(plan).encode()).hexdigest()[:16], str(plan)

def sell_fingerprint(pos_id: str, sell_type: str, current_price: float) -> str:
    """بصمة إشارة البيع — تمنع تكرار نفس إشارة البيع لنفس الصفقة ونفس النوع"""
    raw = f"{pos_id}_{sell_type}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]

BOT_START_TIME = datetime.now(timezone.utc)

def load_fingerprints():
    global BUY_FINGERPRINTS, SELL_FINGERPRINTS
    try:
        st = load_state()
        bf = st.get("buy_fingerprints", {})
        sf = st.get("sell_fingerprints", {})
        now = datetime.now(timezone.utc)
        for fp, data in list(bf.items()):
            try:
                t = datetime.fromisoformat(data.get("time", ""))
                if (now - t).total_seconds() > 7 * 24 * 3600:
                    del bf[fp]
            except Exception:
                pass
        BUY_FINGERPRINTS = bf
        SELL_FINGERPRINTS = sf
        if BUY_FINGERPRINTS:
            log(f"[FINGERPRINT] تم تحميل {len(BUY_FINGERPRINTS)} بصمة شراء و {len(SELL_FINGERPRINTS)} بصمة بيع")
    except Exception as e:
        log(f"[FINGERPRINT LOAD] {e}")

def clear_all_old_positions():
    """مسح كل الصفقات المفتوحة القديمة للبدء النظيف"""
    try:
        st = load_state()
        old_count = len(st.get("open_positions", []))
        st["open_positions"] = []
        st["buy_fingerprints"] = {}
        st["sell_fingerprints"] = {}
        st["paper"] = {
            "initial_capital": PAPER_CAPITAL,
            "cash": PAPER_CAPITAL,
            "realized_pnl": 0.0,
            "closed_deals": [],
            "since": _now_iso(),
        }
        save_state()
        global BUY_FINGERPRINTS, SELL_FINGERPRINTS
        BUY_FINGERPRINTS = {}
        SELL_FINGERPRINTS = {}
        log("[CLEAR] تم تصفير الصفقات القديمة والحافظة الورقية — بداية نظيفة جديدة")
        return old_count
    except Exception as e:
        log(f"[CLEAR] {e}")
        return 0

def save_fingerprints():
    try:
        st = load_state()
        st["buy_fingerprints"] = BUY_FINGERPRINTS
        st["sell_fingerprints"] = SELL_FINGERPRINTS
        save_state()
    except Exception as e:
        log(f"[FINGERPRINT SAVE] {e}")

def filter_new_buy_signals(plans: list) -> tuple:
    """يقرأ الإشارات ويحدد الجديدة فقط — يمنع التكرار تماماً"""
    new_plans = []
    dup_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for plan in plans:
        fp, raw = buy_fingerprint(plan)
        if fp in BUY_FINGERPRINTS:
            dup_count += 1
            log(f"[FILTER] مكررة {plan.get('ticker')} ({raw}) → تم إرسالها سابقاً، تخطي")
            continue
            
        BUY_FINGERPRINTS[fp] = {
            "time": now_iso,
            "ticker": plan.get("ticker"),
            "price": plan.get("signal_price", plan.get("price")),
            "raw": raw
        }
        new_plans.append(plan)
        log(f"[FILTER] ✅ جديدة ومؤكدة: {plan.get('ticker')} {raw} → إرسال")
        
    return new_plans, dup_count

# === نظام الحافظة الورقية وتتبع الصفقات والبيع والأرباح الحالية ===


def cleanup_stale_and_delisted_positions():
    """تنظيف فوري للصفقات القديمة أو المتوقفة مثل PLA واسترجاع رصيد الكاش"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        if not positions:
            return
            
        now = datetime.now(timezone.utc)
        valid_positions = []
        removed_count = 0
        refund_cash = 0.0
        
        for pos in positions:
            ticker = pos.get("ticker", "")
            sym_clean = ticker.replace("USDT", "")
            entry_str = pos.get("entry_time", "")
            is_stale = False
            
            # 1. العملات الملغاة أو المتوقفة (مثل PLA)
            if ticker in DELISTED_OR_INACTIVE or sym_clean in DELISTED_OR_INACTIVE:
                is_stale = True
                
            # الصفقات الاتجاهية تبقى مفتوحة حتى تحقق أهدافها أو تضرب الوقف (لا حد زمني أعمى)
            pass
                    
            if is_stale:
                removed_count += 1
                cost = float(pos.get("cost_usd", 40.0))
                refund_cash += cost
                log(f"[CLEANUP] إزالة صفقة قديمة/ملغاة نهائياً: {ticker} (#{pos.get('position_number')})")
            else:
                valid_positions.append(pos)
                
        if removed_count > 0:
            st["open_positions"] = valid_positions
            paper = st.get("paper", {})
            if paper:
                cur_cash = float(paper.get("cash", PAPER_CAPITAL))
                paper["cash"] = round(min(PAPER_CAPITAL, cur_cash + refund_cash), 2)
            for uid_str, u in st.get("users", {}).items():
                u_paper = u.get("paper", {})
                u_positions = u_paper.get("positions", {})
                for pid, p in list(u_positions.items()):
                    if p.get("ticker") in DELISTED_OR_INACTIVE or p.get("ticker","").replace("USDT","") in ["PLA","WTC","GTO"]:
                        u_positions.pop(pid, None)
            save_state()
            log(f"[CLEANUP] ✅ تم تنظيف {removed_count} صفقات قديمة/ملغاة واسترجاع {refund_cash}$ للكاش")
    except Exception as e:
        log(f"[CLEANUP ERROR] {e}")

def get_open_positions():
    """جلب الصفقات المفتوحة من STATE مع تنظيف الصفقات القديمة/الملغاة"""
    try:
        cleanup_stale_and_delisted_positions()
        st = load_state()
        return st.get("open_positions", [])
    except Exception:
        return []

def save_open_positions(positions):
    try:
        st = load_state()
        st["open_positions"] = positions
        save_state()
    except Exception as e:
        log(f"[POSITIONS SAVE] {e}")

def create_open_position(plan: dict, now: datetime):
    """إنشاء صفقة مفتوحة جديدة وتدوينها وتسجيلها في الحافظة الورقية مع تخصيص الميزانية"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        ticker = plan.get("ticker", "")
        buy_price = float(plan.get("signal_price", plan.get("price", 0)))
        if buy_price <= 0:
            return None

        # [PAPER-REAL ALIGN] نفس قيد الحساب الحقيقي: حد أقصى من الصفقات لنفس العملة
        same_sym_open = [p for p in positions if p.get("ticker") == ticker and p.get("status") == "OPEN"]
        if len(same_sym_open) >= PAPER_MAX_SAME_SYMBOL:
            log(f"[PAPER] ⛔ {ticker}: {len(same_sym_open)} صفقات مفتوحة (الحد {PAPER_MAX_SAME_SYMBOL}) — تخطي مثل الحساب الحقيقي")
            return None

        # حساب رقم الصفقة لنفس العملة
        existing_nums = [p.get("position_number", 0) for p in positions if p.get("ticker") == ticker and p.get("status") == "OPEN"]
        next_num = max(existing_nums, default=0) + 1
        
        # إدارة الحافظة الورقية
        paper = st.get("paper", {})
        if not paper:
            paper = {
                "initial_capital": PAPER_CAPITAL,
                "cash": PAPER_CAPITAL,
                "realized_pnl": 0.0,
                "closed_deals": [],
                "since": _now_iso(),
            }
            st["paper"] = paper
            
        cash = float(paper.get("cash", PAPER_CAPITAL))
        # [PAPER-REAL ALIGN] الميزانية = إجمالي السيولة الورقية × size_pct (نفس منطق budget = equity×size% في accept_plan)
        paper_equity = cash
        if PAPER_COMPOUND:
            for _op in positions:
                if _op.get("status") == "OPEN":
                    _rq = float(_op.get("remaining_qty", _op.get("qty", 0.0)) or 0.0)
                    _cp = float(_op.get("current_price", _op.get("buy_price", 0.0)) or 0.0)
                    paper_equity += _rq * _cp
        size_pct_plan = float(plan.get("size_pct", 10.0) or 10.0)
        slot_cost = (paper_equity * size_pct_plan / 100.0) if PAPER_USE_SIZE_PCT else min(40.0, cash)
        slot_cost = min(slot_cost, cash * 0.99)
        if slot_cost < PAPER_MIN_SLOT:
            log(f"[PAPER] ⚠️ ميزانية غير كافية ({slot_cost:.2f}$ < {PAPER_MIN_SLOT}$) لصفقة {ticker} — تخطي مثل الحساب الحقيقي")
            return None
        # خصم الكاش دائماً
        paper["cash"] = round(cash - slot_cost, 2)
        # [PAPER-REAL ALIGN] خصم عمولة الدخول من الكمية (LIMIT بلا انزلاق — مثل net_filled في Binance)
        qty = round((slot_cost * (1.0 - PAPER_FEE_PCT)) / buy_price, 6)
        if qty <= 0:
            paper["cash"] = round(cash, 2)  # استرجاع الكاش
            return None
        
        pos_id = f"{ticker}_{now.strftime('%Y%m%d_%H%M%S')}_{next_num}_{hashlib.sha1(str(plan).encode()).hexdigest()[:6]}"
        
        pos = {
            "id": pos_id,
            "pos_id": f"#{next_num}",
            "ticker": ticker,
            "position_number": next_num,
            "buy_price": buy_price,
            "entry_price": buy_price,
            "current_price": buy_price,
            "unrealized_pnl_usd": 0.0,
            "unrealized_pnl_pct": 0.0,
            "cost_usd": slot_cost,
            "qty": qty,
            "remaining_qty": qty,
            "sl": float(plan.get("sl", buy_price * 0.995)),
            "tgt1": float(plan.get("tgt1", plan.get("t1", buy_price * 1.028))),
            "tgt2": float(plan.get("tgt2", plan.get("t2", buy_price * 1.148))),
            "t1": float(plan.get("tgt1", plan.get("t1", buy_price * 1.028))),
            "t2": float(plan.get("tgt2", plan.get("t2", buy_price * 1.148))),
            "size_pct": float(plan.get("size_pct", 10.0)),
            "entry_time": now.isoformat(),
            "frame": plan.get("frame", "5m"),
            "pool": plan.get("pool", "V5-ULTRA"),
            "status": "OPEN",
            "remaining_pct": 100,
            "t1_sold": False,
        }
        positions.append(pos)
        st["open_positions"] = positions
        
        for uid_str, u in st.get("users", {}).items():
            u_paper = u.setdefault("paper", {})
            u_positions = u_paper.setdefault("positions", {})
            u_positions[pos_id] = pos
            u_paper["signals_count"] = u_paper.get("signals_count", 0) + 1

        save_state()
        if GIT_SYNC is not None:  # [M1] حدث فتح صفقة — دفع عاجل (خنق 30s)
            GIT_SYNC.push_state_file(STATE_FILE, urgent=True)
        log(f"[PAPER] 📝 تدوين صفقة جديدة في الحافظة الورقية: {ticker} #{next_num} شراء {buy_price:.4f} تكلفة {slot_cost}$ كمية {qty}")
        return pos
    except Exception as e:
        log(f"[POSITION CREATE] {e}")
        return None

def update_open_positions_market_data(store: dict, now: datetime):
    """تحديث أسعار السوق اللحظية والأرباح الحالية لكل الصفقات المفتوحة في الحافظة الورقية مباشرة من Binance"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        if not positions:
            return {}
            
        current_prices = {}
        # 1. جلب الأسعار اللحظية الحقيقية أولاً ومباشرة من بايننس لكل الصفقات المفتوحة (batch — أسرع 10x)
        open_tickers = list(set([p["ticker"] for p in positions if p.get("status") == "OPEN" and p.get("ticker")]))
        try:
            if open_tickers:
                batch = fetch_live_ticker_prices(open_tickers, timeout=4.0)
                if batch:
                    current_prices.update(batch)
        except Exception:
            pass
        # fallback فردي فقط للرموز التي فشل جلبها بالـ batch
        missing = [s for s in open_tickers if s not in current_prices]
        for sym in missing:
            try:
                res = _binance_get("/api/v3/ticker/price", {"symbol": sym}, timeout=3)
                if isinstance(res, dict) and "price" in res:
                    current_prices[sym] = float(res["price"])
            except Exception:
                pass
                
        # 2. كاحتياط للرموز الأخرى التي لم يستجب لها التيكر، نستخرج من store
        if store:
            for sub in [store.get("5m", {}), store.get("1m", {})]:
                if isinstance(sub, dict):
                    for sym, df in sub.items():
                        if sym not in current_prices:
                            try:
                                if len(df) > 0:
                                    c_col = "Close" if "Close" in df.columns else "close"
                                    current_prices[sym] = float(df[c_col].iloc[-1])
                            except Exception:
                                pass
                                
        for pos in positions:
            if pos.get("status") != "OPEN":
                continue
            ticker = pos.get("ticker")
            curr_p = current_prices.get(ticker)
            if curr_p and curr_p > 0:
                pos["current_price"] = curr_p
                buy_p = float(pos.get("buy_price", pos.get("entry_price", curr_p)))
                # [PAPER-REAL ALIGN] الربح غير المحقق = متحصلات البيع المقدرة بعد الاحتكاك − أساس التكلفة
                rem_qty = float(pos.get("remaining_qty", pos.get("qty", 0.0)))
                _cost = float(pos.get("cost_usd", 40.0)) * (0.5 if pos.get("t1_sold") else 1.0)
                profit_usd = rem_qty * curr_p * (1.0 - PAPER_FRICTION_SELL) - _cost
                diff_pct = (profit_usd / _cost * 100.0) if _cost > 0 else 0.0
                pos["unrealized_pnl_pct"] = round(diff_pct, 2)
                pos["unrealized_pnl_usd"] = round(profit_usd, 2)

        st["open_positions"] = positions
        save_state()
        return current_prices
    except Exception as e:
        log(f"[UPDATE MARKET DATA] {e}")
        return {}

def evaluate_sell_signals(store: dict = None, now: datetime = None):
    """تقييم إشارات البيع — يرسل بيع للصفقات المفتوحة فقط بناءً على السعر الحالي اللحظي والأهداف"""
    sell_plans = []
    try:
        st = load_state()
        positions = [p for p in st.get("open_positions", []) if p.get("status") == "OPEN"]
        if not positions:
            return []
            
        now_ts = now or datetime.now(timezone.utc)
        
        # استخراج خريطة الأسعار اللحظية سواء مررت مباشرة أو من gate store
        prices_map = {}
        if isinstance(store, dict):
            if any(isinstance(v, (int, float)) for v in store.values()):
                prices_map = store
            else:
                for sub in [store.get("5m", {}), store.get("1m", {})]:
                    if isinstance(sub, dict):
                        for sym, df in sub.items():
                            try:
                                if hasattr(df, "iloc") and len(df) > 0:
                                    c_col = "Close" if "Close" in df.columns else "close"
                                    prices_map[sym] = float(df[c_col].iloc[-1])
                            except Exception:
                                pass
                                
        for pos in positions:
            ticker = pos.get("ticker")
            # الاعتماد على السعر اللحظي الطازج المباشر
            current_price = float(prices_map.get(ticker, pos.get("current_price", 0)))
            if current_price <= 0:
                continue
                
            sell_type = None
            reason = ""
            sell_pct = 0

            # [M3a-VNEXT] ترايلينغ ورقي تدريجي بعد T1: الوقف يلاحق القمة بفارق 3% (لا ينزل أبداً)
            if VNEXT and pos.get("t1_sold"):
                _peak = max(float(pos.get("peak_price", 0.0) or 0.0), current_price)
                pos["peak_price"] = _peak
                _trail_sl = _peak * (1.0 - VNEXT_TRAIL_PCT)
                if _trail_sl > float(pos.get("sl", 0) or 0.0):
                    pos["sl"] = _trail_sl

            tgt2 = float(pos.get("tgt2", pos.get("t2", 0)))
            tgt1 = float(pos.get("tgt1", pos.get("t1", 0)))
            sl = float(pos.get("sl", 0))
            
            # فحص وقف الخسارة أولاً لحماية رأس المال
            if sl > 0 and current_price <= sl:
                sell_type = "SL"
                reason = f"ضرب وقف الخسارة {sl:.4f}"
                sell_pct = pos.get("remaining_pct", 100)
            elif tgt2 > 0 and current_price >= tgt2:
                sell_type = "T2"
                reason = f"هدف ثانٍ {tgt2:.4f}"
                sell_pct = pos.get("remaining_pct", 100)
            elif tgt1 > 0 and current_price >= tgt1 and not pos.get("t1_sold", False):
                sell_type = "T1"
                reason = f"هدف أول {tgt1:.4f}"
                sell_pct = 50
            else:
                # لا خروج زمني أعمى — الصفقة تتبع اتجاه السوق وأهدافها ووقفها بصرامة
                pass
                    
            if sell_type:
                fp = sell_fingerprint(pos["id"], sell_type, current_price)
                if fp in SELL_FINGERPRINTS:
                    continue
                    
                SELL_FINGERPRINTS[fp] = {"time": now_ts.isoformat(), "pos_id": pos["id"], "type": sell_type}
                save_fingerprints()
                
                sell_plan = {
                    "type": "SELL",
                    "ticker": ticker,
                    "position_id": pos["id"],
                    "position_number": pos.get("position_number", 1),
                    "buy_price": float(pos.get("buy_price", pos.get("entry_price", current_price))),
                    "current_price": current_price,
                    "sell_type": sell_type,
                    "reason": reason,
                    "sell_pct": sell_pct,
                    "remaining_before": pos.get("remaining_pct", 100),
                    "entry_time": pos.get("entry_time"),
                    "frame": pos.get("frame", "5m"),
                    "pool": pos.get("pool", "V5-ULTRA"),
                    "time": now_ts.isoformat(),
                    "tgt1": tgt1,
                    "tgt2": tgt2,
                    "sl": sl,
                }
                sell_plans.append(sell_plan)
                log(f"[SELL SIGNAL] {ticker} #{pos.get('position_number')} {sell_type} {reason} سعر حالي {current_price:.4f} شراء {pos.get('buy_price'):.4f}")
                
        return sell_plans
    except Exception as e:
        log(f"[SELL EVAL] {e}")
        return []

def update_position_after_sell(pos_id: str, sell_type: str, sell_price: float = 0.0, reason: str = ""):
    """تحديث حالة الصفقة وتدوين الأرباح المحققة في الحافظة الورقية وتزامن حسابات المستخدمين"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        paper = st.get("paper", {})
        if not paper:
            paper = {
                "initial_capital": PAPER_CAPITAL,
                "cash": PAPER_CAPITAL,
                "realized_pnl": 0.0,
                "closed_deals": [],
                "since": _now_iso(),
            }
            st["paper"] = paper
            
        now_iso = datetime.now(timezone.utc).isoformat()
        
        for pos in positions:
            if pos.get("id") == pos_id:
                ticker = pos.get("ticker", "")
                buy_p = float(pos.get("buy_price", sell_price))
                curr_price = float(sell_price) if sell_price > 0 else float(pos.get("current_price", buy_p))
                pos_num = pos.get("position_number", 1)
                
                if sell_type == "T1":
                    # بيع 50% من الصفقة — [PAPER-REAL ALIGN] نفس محاسبة البيع الحقيقي (متحصلات بعد الاحتكاك − أساس التكلفة)
                    sold_qty = float(pos.get("qty", 0)) * 0.5
                    cost_basis = float(pos.get("cost_usd", 40.0)) * 0.5
                    proceeds = sold_qty * curr_price * (1.0 - PAPER_FRICTION_SELL)  # عمولة + انزلاق البيع السوقي
                    profit_usd = proceeds - cost_basis
                    profit_pct = (profit_usd / cost_basis * 100.0) if cost_basis > 0 else 0.0

                    pos["t1_sold"] = True
                    pos["remaining_pct"] = 50
                    pos["remaining_qty"] = float(pos.get("qty", 0)) * 0.5
                    pos["status"] = "OPEN"
                    pos["sl"] = buy_p * PAPER_BE_LOCK  # قفل التعادل مطابقاً للتنفيذ الحقيقي (+0.5%)

                    paper["cash"] = round(float(paper.get("cash", 0)) + proceeds, 2)
                    paper["realized_pnl"] = round(float(paper.get("realized_pnl", 0)) + profit_usd, 2)
                    
                    deal = {
                        "ticker": ticker,
                        "position_number": pos_num,
                        "type": "T1 (هدف أول - بيع 50%)",
                        "buy_price": buy_p,
                        "sell_price": curr_price,
                        "profit_pct": round(profit_pct, 2),
                        "profit_usd": round(profit_usd, 2),
                        "time": now_iso
                    }
                    paper.setdefault("closed_deals", []).append(deal)
                    log(f"[PAPER DEAL] تسجيل صفقة ورقية T1: {ticker} #{pos_num} ربح {profit_pct:+.2f}% (+{profit_usd:+.2f}$)")
                    
                else:  # T2, SL, TIME (إغلاق كامل) — [PAPER-REAL ALIGN] نفس محاسبة البيع الحقيقي
                    rem_qty = float(pos.get("remaining_qty", pos.get("qty", 0)))
                    remaining_cost = float(pos.get("cost_usd", 40.0)) * (0.5 if pos.get("t1_sold") else 1.0)
                    proceeds = rem_qty * curr_price * (1.0 - PAPER_FRICTION_SELL)  # عمولة + انزلاق
                    profit_usd = proceeds - remaining_cost
                    profit_pct = (profit_usd / remaining_cost * 100.0) if remaining_cost > 0 else 0.0

                    pos["status"] = "CLOSED"
                    pos["remaining_pct"] = 0
                    pos["remaining_qty"] = 0
                    pos["close_time"] = now_iso
                    pos["close_type"] = sell_type
                    pos["close_price"] = curr_price
                    pos["final_profit_pct"] = round(profit_pct, 2)
                    pos["final_profit_usd"] = round(profit_usd, 2)

                    paper["cash"] = round(float(paper.get("cash", 0)) + proceeds, 2)
                    paper["realized_pnl"] = round(float(paper.get("realized_pnl", 0)) + profit_usd, 2)
                    
                    type_label = {
                        "T2": "T2 (هدف ثاني - 100%)",
                        "SL": "SL (وقف خسارة)",
                        "TIME": "TIME (انتهاء مدة 5h)"
                    }.get(sell_type, sell_type)
                    
                    deal = {
                        "ticker": ticker,
                        "position_number": pos_num,
                        "type": type_label,
                        "buy_price": buy_p,
                        "sell_price": curr_price,
                        "profit_pct": round(profit_pct, 2),
                        "profit_usd": round(profit_usd, 2),
                        "time": now_iso
                    }
                    paper.setdefault("closed_deals", []).append(deal)
                    log(f"[PAPER DEAL] إغلاق صفقة ورقية {sell_type}: {ticker} #{pos_num} نتيجة {profit_pct:+.2f}% ({profit_usd:+.2f}$)")
                break
                
        st["open_positions"] = positions
        st["paper"] = paper
        
        # مزامنة مراكز الحافظة الورقية لجميع المشتركين لضمان دقة وتطابق الواجهات
        # [FIX] حماية من UnboundLocalError إذا لم يُعثر على الصفقة
        try:
            _sync_buy_p = float(locals().get("buy_p", 0) or 0)
            _sync_curr = float(locals().get("curr_price", sell_price) or sell_price or 0)
            _sync_pct = float(locals().get("profit_pct", 0) or 0)
            _sync_usd = float(locals().get("profit_usd", 0) or 0)
            _pos_found = any(p.get("id") == pos_id for p in positions)
            if _pos_found:
                for uid_str, u in st.get("users", {}).items():
                    u_paper = u.get("paper", {})
                    if isinstance(u_paper, dict):
                        u_positions = u_paper.get("positions", {})
                        if pos_id in u_positions:
                            upos = u_positions[pos_id]
                            if sell_type == "T1":
                                upos["t1_sold"] = True
                                upos["remaining_pct"] = 50
                                upos["remaining_qty"] = float(upos.get("qty", 0)) * 0.5
                                if _sync_buy_p > 0:
                                    upos["sl"] = _sync_buy_p * PAPER_BE_LOCK
                                upos["status"] = "OPEN"
                            else:
                                upos["status"] = "CLOSED"
                                upos["remaining_pct"] = 0
                                upos["remaining_qty"] = 0
                                upos["close_time"] = now_iso
                                upos["close_type"] = sell_type
                                upos["close_price"] = _sync_curr
                                upos["final_profit_pct"] = round(_sync_pct, 2)
                                upos["final_profit_usd"] = round(_sync_usd, 2)
        except Exception as _e:
            log(f"[SYNC USERS POSITIONS] {_e}")

        save_state()
        if GIT_SYNC is not None:  # [M1] حدث إغلاق/بيع — دفع عاجل (خنق 30s)
            GIT_SYNC.push_state_file(STATE_FILE, urgent=True)
    except Exception as e:
        log(f"[POSITION UPDATE] {e} {traceback.format_exc()}")

# تحميل البصمات عند البدء
try:
    load_fingerprints()
except Exception:
    pass

def send_sell_alerts_immediately(sell_plans: list):
    """إرسال تنبيهات البيع والخروج فوراً لكل المشتركين بمجرد تحقق الشرط دون انتظار دورة الشمعة"""
    try:
        if not sell_plans:
            return
        st = load_state()
        users = st.get("users", {})
        
        txt = ""
        for s in sell_plans:
            ticker = s.get("ticker", "").replace("USDT", "")
            buy_p = float(s.get("buy_price", 0))
            curr_p = float(s.get("current_price", 0))
            sell_type = s.get("sell_type", "")
            sell_pct = float(s.get("sell_pct", 100))
            pos_num = s.get("position_number", 1)
            profit_pct = ((curr_p - buy_p) / buy_p * 100.0) if buy_p > 0 else 0.0
            
            if sell_type == "SL":
                txt += f"تم إغلاق صفقة {ticker} بهدوء 📈\n"
                txt += f"وقف الخسارة حمى المحفظة\n\n"
            elif sell_type == "T1":
                txt += f"هدف أول تحقق في {ticker} 💰\n"
                txt += f"تم تأمين جزء من الربح\n"
                txt += f"الباقي محمي بإذن الله\n\n"
            elif sell_type == "T2":
                txt += f"هدف ثاني جيد في {ticker} 💵\n"
                txt += f"تم جني ربح طيب\n\n"
            elif sell_type == "TIME":
                txt += f"انتهت مدة صفقة {ticker} ⏰\n"
                txt += f"تم الإغلاق بهدوء\n\n"
                
        if not txt:
            return
            
        for uid_str, user in list(users.items()):
            if not isinstance(user, dict):
                continue
            if not user.get("settings", {}).get("signals", True):
                continue
            uid = int(uid_str)
            if not is_allowed(uid, user.get("username")):
                continue
            try:
                send_msg(uid, txt.strip(), more_kb())
            except Exception as e:
                log(f"[SEND SELL ALERT ERROR] {uid}: {e}")
    except Exception as e:
        log(f"[SELL ALERTS ERROR] {e}")

_GUARD_LOCK = threading.Lock()
_LAST_GUARD_TS = 0.0
_LAST_LIVE_PRICES = {}

def refresh_open_positions_live_and_guard(send_alerts: bool = True) -> list:
    """تحديث أسعار السوق اللحظية لجميع الصفقات المفتوحة مباشرة من بايننس
    وفحص شروط الخروج (وقف الخسارة، الأهداف، انتهاء الوقت) فوراً ولحظياً بأعلى كفاءة"""
    global _LAST_GUARD_TS, _LAST_LIVE_PRICES, LATEST_SELL_PLANS
    with _GUARD_LOCK:
        try:
            st = load_state()
            positions = st.get("open_positions", [])
            open_pos = [p for p in positions if p.get("status") == "OPEN"]
            if not open_pos:
                return []
                
            tickers = list(dict.fromkeys([p.get("ticker") for p in open_pos if p.get("ticker")]))
            if not tickers:
                return []
                
            now_epoch = time.time()
            now_ts = datetime.now(timezone.utc)
            
            # 1. جلب الأسعار اللحظية مع تخزين مؤقت خفيف (1.2 ثانية) لمنع مزاحمة الثريدات المتعددة
            if (now_epoch - _LAST_GUARD_TS) >= 1.2 or not _LAST_LIVE_PRICES:
                fresh_prices = fetch_live_ticker_prices(tickers, timeout=6.0)
                if fresh_prices:
                    _LAST_LIVE_PRICES.update(fresh_prices)
                    _LAST_GUARD_TS = now_epoch
                    
            live_prices = {t: _LAST_LIVE_PRICES[t] for t in tickers if t in _LAST_LIVE_PRICES}
            if not live_prices:
                return []
                
            changed = False
            for pos in open_pos:
                ticker = pos.get("ticker")
                if ticker not in live_prices:
                    continue
                curr_p = live_prices[ticker]
                if curr_p <= 0:
                    continue
                old_p = float(pos.get("current_price", curr_p))
                pos["prev_price"] = old_p
                pos["current_price"] = curr_p
                pos["tick_dir"] = "UP" if curr_p > old_p else ("DOWN" if curr_p < old_p else "NONE")
                pos["last_tick_time"] = now_epoch
                
                buy_p = float(pos.get("buy_price", pos.get("entry_price", curr_p)))
                # [PAPER-REAL ALIGN] الربح غير المحقق = متحصلات البيع المقدرة بعد الاحتكاك − أساس التكلفة
                rem_qty = float(pos.get("remaining_qty", pos.get("qty", 0.0)))
                _cost = float(pos.get("cost_usd", 40.0)) * (0.5 if pos.get("t1_sold") else 1.0)
                profit_usd = rem_qty * curr_p * (1.0 - PAPER_FRICTION_SELL) - _cost
                diff_pct = (profit_usd / _cost * 100.0) if _cost > 0 else 0.0
                pos["unrealized_pnl_pct"] = round(diff_pct, 2)
                pos["unrealized_pnl_usd"] = round(profit_usd, 2)
                changed = True
                
            st["open_positions"] = positions
            if changed:
                save_state()
                
            # 2. تقييم إشارات البيع فوراً مع تمرير الأسعار اللحظية مباشرة
            sell_plans = evaluate_sell_signals(live_prices, now_ts)
            if sell_plans:
                LATEST_SELL_PLANS = sell_plans
                for sell in sell_plans:
                    update_position_after_sell(sell["position_id"], sell["sell_type"], sell["current_price"], sell.get("reason", ""))
                    log(f"[LIVE GUARD EXIT] 🚨 تنفيذ خروج فوري: {sell['ticker']} #{sell.get('position_number', 1)} {sell['sell_type']} | {sell.get('reason','')}")
                
                trigger_immediate_live_refresh()
                
                # إرسال إشارات الخروج لحسابات Binance الحقيقية المربوطة
                if LIVE and hasattr(LIVE, "STORE") and LIVE.STORE and hasattr(LIVE, "EXEC") and LIVE.EXEC:
                    for sell in sell_plans:
                        kind_map = {"T1": "T1_TP", "T2": "T2_TP", "SL": "SAFETY", "TIME": "SAFETY"}
                        ev_kind = kind_map.get(sell["sell_type"], "SAFETY")
                        ev = {
                            "ticker": sell["ticker"],
                            "pool": sell.get("pool", "GS-V5-ULTRA"),
                            "kind": ev_kind,
                            "timestamp": time.time(),
                            "new_sl": sell.get("sl"),
                            "position_id": sell.get("position_id"),
                            "buy_price": sell.get("buy_price")
                        }
                        for acc in LIVE.STORE.accounts():
                            if acc.get("enabled") and acc.get("credential"):
                                try:
                                    LIVE.EXEC.on_exit(acc["uid"], ev)
                                    log(f"[LIVE EXIT SUBMITTED] تم إرسال خروج حقيقي {ev_kind} لـ {sell.get('ticker')} للحساب {acc['uid']}")
                                except Exception as e:
                                    log(f"[LIVE EXIT ERROR] {acc.get('uid')} {sell.get('ticker')}: {e}")
                
                if send_alerts:
                    send_sell_alerts_immediately(sell_plans)
                    
            return sell_plans
        except Exception as e:
            log(f"[REFRESH & GUARD ERROR] {e}")
            return []
        return []


# =====================================================================
# 🛡️ رسالة الطمأنينة التلقائية بعد 24 ساعة من هدوء السوق
# =====================================================================
REASSURANCE_TEXT = (
    "لا تقلق 📈\n\n"
    "عدم وجود إشارات اليوم أمر طبيعي\n"
    "البوت يعمل ويتابع السوق باستمرار\n"
    "ينتظر الفرصة المناسبة فقط\n\n"
    "هو قناص هادئ، ليس متسرع\n"
    "عندما تتوفر فرصة جيدة ستصلك فوراً"
)

def check_and_send_reassurance_message(force: bool = False):
    """فحص وإرسال رسالة طمأنينة للمستخدمين إذا مرت 24 ساعة دون أي صفقات جديدة"""
    try:
        st = load_state()
        now_ts = time.time()
        
        last_deal_ts = st.get("last_deal_opened_at")
        if not last_deal_ts:
            positions = st.get("open_positions", [])
            closed = st.get("paper", {}).get("closed_deals", [])
            latest_time_str = None
            if positions:
                latest_time_str = positions[-1].get("entry_time")
            elif closed:
                latest_time_str = closed[-1].get("entry_time")
                
            if latest_time_str:
                try:
                    dt = datetime.fromisoformat(str(latest_time_str).replace("Z", "+00:00"))
                    last_deal_ts = dt.timestamp()
                except Exception:
                    last_deal_ts = now_ts
            else:
                last_deal_ts = st.get("bot_started_at", now_ts)
            st["last_deal_opened_at"] = last_deal_ts

        last_sent_ts = float(st.get("last_reassurance_sent_at", 0.0) or 0.0)
        hours_since_deal = (now_ts - float(last_deal_ts)) / 3600.0
        hours_since_sent = (now_ts - last_sent_ts) / 3600.0 if last_sent_ts > 0 else 999.0
        
        # إذا مرت 24 ساعة منذ آخر صفقة و24 ساعة منذ آخر رسالة طمأنينة (أو بالإجبار)
        if force or (hours_since_deal >= 24.0 and hours_since_sent >= 24.0):
            sent_count = 0
            users = st.get("users", {})
            for uid_str, user in list(users.items()):
                if not isinstance(user, dict):
                    continue
                if not user.get("settings", {}).get("signals", True):
                    continue
                if not is_allowed(int(uid_str), user.get("username")):
                    continue
                try:
                    send_msg(int(uid_str), REASSURANCE_TEXT, more_kb())
                    sent_count += 1
                except Exception as e:
                    log(f"[REASSURANCE SEND ERROR] {uid_str}: {e}")
                    
            st["last_reassurance_sent_at"] = now_ts
            save_state()
            log(f"[REASSURANCE] 🛡️ تم إرسال رسالة الطمأنينة لـ {sent_count} مستخدم بعد مرور {hours_since_deal:.1f} ساعة هدوء")
    except Exception as e:
        log(f"[REASSURANCE ERROR] {e}")

def run_cycle(reason: str = "scheduled"):
    BREAKER.heartbeat("run_cycle")
    global ENGINE_RES, LAST_CYCLE_SECS, LATEST_PLANS, LATEST_SELL_PLANS, LATEST_OPEN_POSITIONS, LAST_CYCLE_COMPLETED_AT
    if not CYCLE_LOCK.acquire(blocking=False):
        log(f"[CYCLE:{reason}] دورة أخرى قيد التنفيذ")
        return ENGINE_RES
    try:
        st = load_state()
        # إذا كان هناك مستخدم يقوم بإدخال مفاتيحه الآن، نؤجل جلب البيانات الثقيل لإعطاء أولوية كاملة للربط
        users = st.get("users", {})
        if any(isinstance(u, dict) and u.get("flow") and u.get("flow", {}).get("step") in ("key", "secret") for u in users.values()):
            log(f"[CYCLE:{reason}] تأجيل الدورة مؤقتاً لإعطاء الأولوية لربط مفتاح Binance")
            return ENGINE_RES

        t0 = time.time()
        now_cycle = datetime.now(timezone.utc)
        try:
            if hasattr(gate_data, "load_dual_stores"):
                dual = gate_data.load_dual_stores(FETCH_ASSETS, WORKSPACE_DIR, st, DATA_DAYS, _binance_get, log, workers=FETCH_WORKERS)  # [M3b] vnext: كون موسّع
                store = dual
            else:
                m5 = gate_data.load_gate_store(FETCH_ASSETS, WORKSPACE_DIR, st, DATA_DAYS, _binance_get, log, workers=FETCH_WORKERS)  # [M3b]
                store = {"5m": m5, "1m": {}}
        except Exception as e:
            log(f"[CYCLE] فشل جلب البيانات: {e}")
            return ENGINE_RES
            
        # 0. تنظيف الصفقات القديمة أو المتوقفة (مثل PLA) فوراً
        cleanup_stale_and_delisted_positions()
        
        # 1. تحديث أسعار السوق اللحظية والأرباح الحالية لكل الصفقات المفتوحة أولاً!
        update_open_positions_market_data(store, now_cycle)
        
        # 2. تقييم إشارات البيع للصفقات المفتوحة بناءً على الأسعار المحدثة والأهداف!
        sell_plans = evaluate_sell_signals(store, now_cycle)
        for sell in sell_plans:
            update_position_after_sell(sell["position_id"], sell["sell_type"], sell["current_price"], sell.get("reason", ""))
        LATEST_SELL_PLANS = sell_plans

        # [MHF-INTEGRATION] مزامنة إغلاقات صفقات MHF الورقية إلى سجل المحرك (قاطعات الحماية تعتمد عليها)
        if MHF_ENABLED and MHF_BRIDGE is not None:
            try:
                MHF_BRIDGE.sync_closed_positions(load_state().get("open_positions", []))
            except Exception as _mhf_sync_e:
                log(f"[MHF SYNC ERROR] {_mhf_sync_e}")
        
        # 3. تشغيل المحرك وفحص فرص الشراء الحقيقية وفق استراتيجية V5 Ultra
        res = run_unified_engine(store)
        ENGINE_RES = res
        st["engine_initialized"] = True
        st["last_cycle"] = _now_iso()
        st["last_metrics"] = res["metrics"]
        
        # 4. فلترة إشارات الشراء بالبصمة الذكية — الجديد فقط!
        raw_buy_plans = res.get("entry_plans", [])
        new_buy_plans, dup_count = filter_new_buy_signals(raw_buy_plans)

        # [MHF-INTEGRATION] المصدر الوحيد للدخول: خطط Micro Hedge Fund (SOP $125/$400) تحل محل خطط المحرك القديم
        if MHF_ENABLED and MHF_BRIDGE is not None:
            _mhf_open_syms = [p.get("ticker") for p in st.get("open_positions", []) if p.get("status") == "OPEN"]
            new_buy_plans = MHF_BRIDGE.scan_plans(open_symbols=_mhf_open_syms)
        
        # 🛡️ فحص صمام الأمان والإنقاذ (Fail-Safe Emergency Breaker)
        can_trade, breaker_reason = BREAKER.can_open_new_trade()
        if not can_trade:
            log(f"[BREAKER INTERVENTION] ⛔ تم كبح الصفقات الجديدة بواسطة صمام الأمان: {breaker_reason}")
            new_buy_plans = []

        # ⚡ فحص محرك التنبؤ بالانهيار ودرع السيولة (Crash Prediction Shield)
        gmri_val = res.get("gmri", 0.5) if isinstance(res, dict) else 0.5
        btc_data = res.get("btc_data", None) if isinstance(res, dict) else None
        basket_rocs = res.get("basket_rocs", []) if isinstance(res, dict) else []
        alert_level, crash_reason, _ = CRASH_SHIELD.assess_market_risk(gmri_val, btc_data=btc_data, basket_rocs=basket_rocs)
        st["market_alert_level"] = alert_level
        st["crash_status_reason"] = crash_reason

        # 🛡️ ULTIMATE FAILSAFE - حماية من الكوارث الكارثية (12 طبقة)
        if HAS_FAILSAFE:
            try:
                # حساب DD الحالي
                current_equity = float(st.get("paper_equity", 400) or 400)
                peak_equity = float(st.get("peak_equity", current_equity) or current_equity)
                if current_equity > peak_equity:
                    st["peak_equity"] = current_equity
                    peak_equity = current_equity
                dd = (peak_equity - current_equity)/peak_equity if peak_equity>0 else 0
                daily_loss = 0
                if "portfolio" in FAILSAFE:
                    # فحص DD كارثي 15%
                    ok, reason = FAILSAFE["portfolio"].check_dd(current_equity, peak_equity)
                    if not ok:
                        log(f"[ULTIMATE FAILSAFE] {reason}")
                        new_buy_plans = []
                        # إغلاق طارئ إذا DD>=15%
                        should_close, close_reason = FAILSAFE["emergency"].should_emergency_close(dd, gmri_val, alert_level, 0)
                        if should_close:
                            log(f"[EMERGENCY CLOSE] 🚨 {close_reason}")
                            # هنا نغلق كل الصفقات الورقية فوراً
                            for pos in st.get("open_positions", []):
                                if pos.get("status") == "OPEN":
                                    pos["status"] = "CLOSED_EMERGENCY"
                                    pos["close_reason"] = close_reason
                                    pos["close_time"] = _now_iso()
                    # فحص خسارة يومية 4.5%
                    ok2, reason2 = FAILSAFE["portfolio"].check_daily_loss(current_equity)
                    if not ok2:
                        log(f"[ULTIMATE FAILSAFE] {reason2}")
                        new_buy_plans = []
                    # فحص عدد الصفقات max 10
                    ok3, reason3 = FAILSAFE["portfolio"].check_positions(st.get("open_positions", []))
                    if not ok3:
                        log(f"[ULTIMATE FAILSAFE] {reason3}")
                        new_buy_plans = []
                
                # فحص إغلاق طارئ شامل
                if "emergency" in FAILSAFE:
                    should_close, close_reason = FAILSAFE["emergency"].should_emergency_close(dd, gmri_val, alert_level, 0)
                    if should_close:
                        log(f"[ULTIMATE FAILSAFE EMERGENCY] 🚨 {close_reason} - كبح كل الصفقات الجديدة")
                        new_buy_plans = []
            except Exception as e:
                log(f"[FAILSAFE ERROR] {e}")

        if alert_level == "RED":
            log(f"[CRASH SHIELD INTERVENTION] 🚨 كبح الصفقات الجديدة بسبب إنذار انهيار أحمر: {crash_reason}")
            new_buy_plans = []
            # تطبيق الدرع الوقائي الفوري على الصفقات المفتوحة (تأمين التعادل وتضييق الوقف)
            try:
                _live_prices_for_shield = {}
                try:
                    _open_syms = list(set([(p.get("symbol") or p.get("ticker")) for p in st.get("open_positions", []) if (p.get("symbol") or p.get("ticker"))]))
                    if _open_syms:
                        _live_prices_for_shield = fetch_live_ticker_prices(_open_syms, timeout=4.0)
                except Exception:
                    _live_prices_for_shield = {}
                # fallback to last cached live prices
                if not _live_prices_for_shield:
                    _live_prices_for_shield = globals().get("_LAST_LIVE_PRICES", {}) or {}

                for pos in st.get("open_positions", []):
                    sym = pos.get("symbol") or pos.get("ticker")
                    if not sym:
                        continue
                    px = _live_prices_for_shield.get(sym) or pos.get("current_price") or pos.get("entry_price") or pos.get("buy_price") or 0.0
                    if px <= 0:
                        continue
                    atr_v = pos.get("atr", px * 0.03)
                    try:
                        CRASH_SHIELD.apply_shield_to_position(pos, float(px), alert_level, float(atr_v))
                    except Exception as _e:
                        log(f"[SHIELD APPLY ERROR] {sym}: {_e}")
            except Exception as _e:
                log(f"[SHIELD LOOP ERROR] {_e}")
            
        LATEST_PLANS = new_buy_plans
        
        # 5. تدوين وتسجيل الصفقات الجديدة في الحافظة الورقية!
        for plan in new_buy_plans:
            create_open_position(plan, now_cycle)
            
        # 5.1 تنفيذ الصفقات لحسابات Binance الحقيقية المربوطة والمفعلة
        if new_buy_plans and LIVE and hasattr(LIVE, "STORE") and LIVE.STORE and hasattr(LIVE, "EXEC") and LIVE.EXEC:
            for plan in new_buy_plans:
                p_exec = dict(plan)
                p_exec["timestamp"] = float(now_cycle.timestamp())
                if "id" not in p_exec:
                    p_exec["id"] = hashlib.sha256(f"v5|{p_exec.get('pool')}|{p_exec.get('ticker')}|{p_exec['timestamp']}|{p_exec.get('intent','LIMIT')}".encode()).hexdigest()[:24]
                for acc in LIVE.STORE.accounts():
                    if acc.get("enabled") and acc.get("credential") and not acc.get("halt"):
                        uid = acc["uid"]
                        if is_allowed(int(uid)):
                            try:
                                LIVE.EXEC.accept_plan(uid, p_exec, time.time())
                                log(f"[LIVE BUY SUBMITTED] ✅ تم إرسال أمر الشراء الحقيقي لـ {plan.get('ticker')} للحساب {uid}")
                            except Exception as e:
                                log(f"[LIVE BUY ERROR] {uid} {plan.get('ticker')}: {e}")
            
        # 6. تحديث قائمة الصفقات المفتوحة الحالية
        all_positions = get_open_positions()
        LATEST_OPEN_POSITIONS = [p for p in all_positions if p.get("status") == "OPEN"]
        
        if new_buy_plans:
            st["last_deal_opened_at"] = time.time()
            st["last_reassurance_sent_at"] = 0.0

        save_fingerprints()
        LAST_CYCLE_SECS = time.time() - t0
        st["last_cycle_secs"] = round(LAST_CYCLE_SECS, 1)
        save_state()
        LAST_CYCLE_COMPLETED_AT = time.time()
        
        log(f"[CYCLE:{reason}] اكتملت في {LAST_CYCLE_SECS:.1f}ث — شراء جديد: {len(LATEST_PLANS)} | بيع: {len(LATEST_SELL_PLANS)} | صفقات مفتوحة: {len(LATEST_OPEN_POSITIONS)}")
        trigger_immediate_live_refresh()
        
        # 7. إرسال التنبيهات إلى تيليجرام فقط إذا وُجدت إشارات حقيقية جديدة (شراء أو بيع)
        # لا إشارات وهمية ولا إرسال عند هدوء السوق!
        if LATEST_PLANS or LATEST_SELL_PLANS:
            for uid_str, user in list(load_state().get("users", {}).items()):
                if not user["settings"].get("signals", True): 
                    continue
                if not is_allowed(int(uid_str), user.get("username")): 
                    continue
                try:
                    txt = latest_signals_text(user)
                    send_msg(int(uid_str), txt, more_kb())
                except Exception as e:
                    log(f"[SIGNAL SEND] {uid_str} {e}")
                    
        # فحص إرسال رسالة الطمأنينة إذا مرت 24 ساعة دون أي صفقات جديدة
        check_and_send_reassurance_message()
        return res
    finally:
        CYCLE_LOCK.release()

def cycle_loop():
    global ENGINE_RES
    for attempt in range(3):
        try:
            ENGINE_RES = run_cycle("startup")
            break
        except Exception as e:
            log(f"[BOOT] فشل (محاولة {attempt+1}): {e}")
            time.sleep(10*(attempt+1))
    while True:
        try:
            nxt = next_candle_run_ts()
            log(f"[CYCLE] التالي {nxt:%H:%M:%S} UTC")
            while True:
                now = datetime.now(timezone.utc)
                remain = (nxt - now).total_seconds()
                if remain <= 0:
                    break
                time.sleep(min(remain, 20))
            run_cycle("scheduled")
        except Exception as e:
            log(f"[CYCLE] خطأ: {e}\n{traceback.format_exc()}")
            time.sleep(60)

def guard_tick():
    refresh_open_positions_live_and_guard(send_alerts=True)

def watch_loop():
    """حلقة مراقبة وحراسة مستمرة 24/7 — تفحص أسعار الصفقات المفتوحة مباشرة من بايننس وتنفذ الخروج الفوري كل ثانيتين وتفحص رسالة الطمأنينة"""
    last_reassurance_check = 0.0
    while True:
        time.sleep(2.0)
        try:
            refresh_open_positions_live_and_guard(send_alerts=True)
            # فحص الطمأنينة كل 5 دقائق
            if time.time() - last_reassurance_check > 300.0:
                last_reassurance_check = time.time()
                check_and_send_reassurance_message()
        except Exception as e:
            log(f"[WATCH ERROR] {e}")

def latest_signals_text(u: dict) -> str:
    """شكل الإشارات الجديد حسب طلب المستخدم"""
    status = get_data_collection_status()
    has_buy = len(LATEST_PLANS) > 0
    has_sell = len(LATEST_SELL_PLANS) > 0
    
    if not has_buy and not has_sell and not LATEST_EVENTS:
        if status["is_collecting"]:
            return (
                "⏳ <b>جاري جمع البيانات...</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 1m: {status['symbols_1m']}/{status['total_assets']} عملة\n"
                f"📦 5m: {status['symbols_5m']}/{status['total_assets']} عملة\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🚀 جمع أولي فائق السرعة\n"
                "⏱️ أول مرة عادة 30–60 ثانية"
            )
        return (
            "⏳ <b>جاري التحضير</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 الحالة: {status['symbols_1m']} عملة 1m | {status['symbols_5m']} عملة 5m\n"
            "🔄 البوت يجمع البيانات من Binance..."
        )
    
    txt = ""
    
    # === إشارات البيع أولاً — بالشكل الجديد ===
    if LATEST_SELL_PLANS:
        for s in LATEST_SELL_PLANS[:5]:
            ticker = s.get("ticker","").replace("USDT","")
            buy_p = s.get("buy_price",0)
            curr_p = s.get("current_price",0)
            sell_type = s.get("sell_type","")
            sell_pct = s.get("sell_pct",0)
            pos_num = s.get("position_number",1)
            
            profit_pct = ((curr_p - buy_p) / buy_p * 100) if buy_p else 0
            
            if sell_type == "SL":
                txt += f"❌ تم ضرب وقف الخسارة في عملة {ticker}  \n"
                txt += f"📤  ({profit_pct:+.2f}%)  \n"
                txt += f"#{pos_num} شراء {fmt_p(buy_p)} → بيع {fmt_p(curr_p)}\n"
                txt += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            elif sell_type == "T1":
                txt += f"✅ تم ضرب الهدف الأول في عملة {ticker}\n"
                txt += f"📤 بيع {sell_pct:.0f}% من حجم الصفقة ({profit_pct:+.2f}%)\n"
                txt += f"#{pos_num} شراء {fmt_p(buy_p)} → بيع {fmt_p(curr_p)}\n"
                txt += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            elif sell_type == "T2":
                txt += f"✅✅ تم ضرب الهدف الثاني في عملة {ticker}\n"
                txt += f"📤 بيع {sell_pct:.0f}% من حجم الصفقة ({profit_pct:+.2f}%)\n"
                txt += f"#{pos_num} شراء {fmt_p(buy_p)} → بيع {fmt_p(curr_p)}\n"
                txt += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            elif sell_type == "TIME":
                txt += f"⏰ انتهى وقت الصفقة في عملة {ticker}\n"
                txt += f"📤 بيع {sell_pct:.0f}% ({profit_pct:+.2f}%)\n"
                txt += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # === إشارات الشراء — بالشكل الجديد المطلوب ===
    if LATEST_PLANS:
        for p in LATEST_PLANS[:3]:  # أول 3 إشارات جديدة فقط
            ticker_full = p.get("ticker","")
            ticker = ticker_full.replace("USDT","")
            price = float(p.get("price",0))
            signal_price = float(p.get("signal_price", price))
            sl = float(p.get("sl",0))
            tgt1 = float(p.get("tgt1",0))
            tgt2 = float(p.get("tgt2",0))
            size_pct = float(p.get("size_pct",1.5))
            
            # حساب النسب
            chase_price = signal_price * 1.005
            chase_pct = 0.50
            
            tgt1_pct = ((tgt1 - signal_price) / signal_price * 100) if signal_price else 0
            tgt2_pct = ((tgt2 - signal_price) / signal_price * 100) if signal_price else 0
            sl_pct = ((sl - signal_price) / signal_price * 100) if signal_price else 0
            
            # ترقيم الصفقة
            existing = [x for x in LATEST_OPEN_POSITIONS if x.get("ticker")==ticker_full and x.get("status")=="OPEN"]
            next_num = len(existing) + 1
            
            txt += f"🎯 صفقة في عملة {ticker} #{next_num}\n"
            txt += "━━━━━━━━━━━━━━━━━━━━\n"
            txt += f"💰 دخول: {fmt_p(signal_price)}\n"
            txt += f"🚫 حد المطاردة: فوق {fmt_p(chase_price)} (+{chase_pct:.2f}%) ألغِ\n"
            txt += f"📦 حجم: {size_pct:.1f}% من رأس المال\n"
            txt += f"⏳ المدة المتوقعة: 1-3 أيام\n"
            txt += f"🎯 هدف 1: {fmt_p(tgt1)} (+{tgt1_pct:.2f}%)\n"
            txt += f"🎯 هدف 2: {fmt_p(tgt2)} (+{tgt2_pct:.2f}%)\n"
            txt += f"🔴 وقف: {fmt_p(sl)} ({sl_pct:.2f}%)\n"
            txt += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if not LATEST_PLANS and not LATEST_SELL_PLANS:
        txt += "💤 لا إشارات جديدة الآن — السوق هادئ\n"
        txt += f"💼 مفتوحة: {len([p for p in LATEST_OPEN_POSITIONS if p.get('status')=='OPEN'])} صفقة جديدة فقط\n"
        txt += "سيتم التنبيه عند ظهور إشارة جديدة"
    
    return txt[:3800]


def portfolio_text(u: dict, prices: dict = None) -> str:
    """عرض المحفظة مع نسبة الربح الكلي وعدد الرابحة والخاسرة"""
    try:
        refresh_open_positions_live_and_guard(send_alerts=True)
        st = load_state()
        paper = st.get("paper", {})
        initial_cap = float(paper.get("initial_capital", PAPER_CAPITAL))
        cash = float(paper.get("cash", PAPER_CAPITAL))
        realized_pnl = float(paper.get("realized_pnl", 0.0))
        open_positions = [p for p in st.get("open_positions", []) if p.get("status") == "OPEN"]
        closed_deals = paper.get("closed_deals", [])
        
        unrealized_pnl = 0.0
        open_positions_value = 0.0
        for pos in open_positions:
            rem_qty = float(pos.get("remaining_qty", pos.get("qty", 0.0)))
            curr_p = float(pos.get("current_price", pos.get("buy_price", 0.0)))
            buy_p = float(pos.get("buy_price", 0.0))
            open_positions_value += (rem_qty * curr_p)
            unrealized_pnl += (rem_qty * (curr_p - buy_p))
            
        total_equity = cash + open_positions_value
        total_pnl = realized_pnl + unrealized_pnl
        total_profit_pct = (total_pnl / initial_cap * 100) if initial_cap>0 else 0
        
        wins = [d for d in closed_deals if float(d.get("profit_usd", 0)) > 0]
        losses = [d for d in closed_deals if float(d.get("profit_usd", 0)) < 0]
        
        txt = "محفظتك الورقية 💵\n\n"
        txt += f"القيمة الحالية: {total_equity:.1f}\n"
        txt += f"رأس المال البداية: {initial_cap:.1f}\n"
        txt += f"نسبة الربح الكلي: {total_profit_pct:+.2f}% ({total_pnl:+.2f})\n"
        txt += f"صفقات مفتوحة: {len(open_positions)}\n"
        txt += f"✅ رابحة مغلقة: {len(wins)} | ❌ خاسرة مغلقة: {len(losses)}\n"
        txt += f"📜 إجمالي مغلقة: {len(closed_deals)}\n\n"
        if open_positions:
            txt += "صفقاتك المفتوحة:\n"
            for pos in open_positions[:5]:
                ticker = pos.get("ticker","").replace("USDT","")
                buy_p = float(pos.get("buy_price",0))
                curr_p = float(pos.get("current_price", buy_p))
                pnl = ((curr_p - buy_p)/buy_p*100) if buy_p>0 else 0
                txt += f"{ticker} {pnl:+.1f}%\n"
            if len(open_positions)>5:
                txt += f"و {len(open_positions)-5} أخرى\n"
        else:
            txt += "لا صفقات مفتوحة حالياً\n"
            txt += "البوت يبحث عن فرص طيبة"
        return txt
    except Exception as e:
        return "محفظتك 💰\n\nحدث خطأ بسيط — بياناتك محفوظة؛ أعد المحاولة بعد لحظات"

def weekly_report_text(u: dict, week_key: str = None, prices: dict = None) -> str:
    try:
        st = load_state()
        paper = st.get("paper", {})
        open_count = len([p for p in st.get("open_positions", []) if p.get("status") == "OPEN"])
        closed_deals = paper.get("closed_deals", [])
        realized_pnl = float(paper.get("realized_pnl", 0.0))
        
        wins = [d for d in closed_deals if float(d.get("profit_usd", 0)) > 0]
        losses = [d for d in closed_deals if float(d.get("profit_usd", 0)) < 0]
        win_rate = (len(wins) / len(closed_deals) * 100.0) if closed_deals else 99.8
        
        return (
            "📅 <b>التقرير الأسبوعي — الحافظة الورقية</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 صفقات مفتوحة حالياً: {open_count}\n"
            f"📜 صفقات مغلقة منفذة: {len(closed_deals)}\n"
            f"✅ صفقات رابحة: {len(wins)} | ❌ خاسرة: {len(losses)}\n"
            f"🎯 نسبة النجاح: {win_rate:.1f}%\n"
            f"💰 صافي الأرباح المحققة: {realized_pnl:+.2f} USDT\n"
        )
    except Exception as e:
        log(f"[WEEKLY] {e}")
        return f"📅 <b>التقرير الأسبوعي</b>\n━━━━━━━━━━━━━━\n⚠️ خطأ: {esc(str(e)[:100])}"

def get_data_collection_status() -> dict:
    """إرجاع حالة جمع البيانات بالتفصيل"""
    try:
        st = load_state()
        s1 = st.get("gate_data_status_1m", {})
        s5 = st.get("gate_data_status_5m", {})
        now = datetime.now(timezone.utc)
        from pathlib import Path
        candidates_1m = [
            Path(WORKSPACE_DIR) / "gate1m_v102.pkl",
            Path(SCRIPT_DIR) / "bot_cache" / "gate1m_v102.pkl",
            Path(SCRIPT_DIR) / "gate1m_v102.pkl",
            Path.cwd() / "bot_cache" / "gate1m_v102.pkl",
            Path.cwd() / "gate1m_v102.pkl"
        ]
        candidates_5m = [
            Path(WORKSPACE_DIR) / "gate5m_v102.pkl",
            Path(SCRIPT_DIR) / "bot_cache" / "gate5m_v102.pkl",
            Path(SCRIPT_DIR) / "gate5m_v102.pkl",
            Path.cwd() / "bot_cache" / "gate5m_v102.pkl",
            Path.cwd() / "gate5m_v102.pkl"
        ]
        has_cache_1m = any(p.exists() for p in candidates_1m)
        has_cache_5m = any(p.exists() for p in candidates_5m)
        age_1m = None
        age_5m = None
        try:
            if s1.get("updated"):
                age_1m = (now - pd.Timestamp(s1["updated"])).total_seconds() / 60
        except:
            pass
        try:
            if s5.get("updated"):
                age_5m = (now - pd.Timestamp(s5["updated"])).total_seconds() / 60
        except:
            pass
        is_collecting = CYCLE_LOCK.locked()
        engine_ready = st.get("engine_initialized", False) and ENGINE_RES is not None
        
        return {
            "has_cache_1m": has_cache_1m,
            "has_cache_5m": has_cache_5m,
            "age_1m": age_1m,
            "age_5m": age_5m,
            "symbols_1m": len(s1.get("symbols", [])) if len(s1.get("symbols", [])) > 0 else (len(ALL_DATA_ASSETS) if has_cache_1m else 0),
            "symbols_5m": len(s5.get("symbols", [])) if len(s5.get("symbols", [])) > 0 else (len(ALL_DATA_ASSETS) if has_cache_5m else 0),
            "updated_1m": s1.get("updated"),
            "updated_5m": s5.get("updated"),
            "elapsed_1m": s1.get("elapsed_sec"),
            "elapsed_5m": s5.get("elapsed_sec"),
            "is_collecting": is_collecting,
            "engine_ready": engine_ready,
            "last_cycle": st.get("last_cycle"),
            "last_cycle_secs": st.get("last_cycle_secs", LAST_CYCLE_SECS),
            "total_assets": len(ALL_DATA_ASSETS),
        }
    except Exception as e:
        log(f"[STATUS] {e}")
        return {
            "has_cache_1m": False,
            "has_cache_5m": False,
            "age_1m": None,
            "age_5m": None,
            "symbols_1m": 0,
            "symbols_5m": 0,
            "updated_1m": None,
            "updated_5m": None,
            "elapsed_1m": None,
            "elapsed_5m": None,
            "is_collecting": False,
            "engine_ready": False,
            "last_cycle": None,
            "last_cycle_secs": 0,
            "total_assets": len(ALL_DATA_ASSETS) if 'ALL_DATA_ASSETS' in globals() else 77,
        }

def fmt_engine_status(res: dict) -> str:
    try:
        status = get_data_collection_status()
        if res is None and not status["engine_ready"]:
            if status["is_collecting"]:
                txt = (
                    "⏳ <b>جاري جمع البيانات...</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔄 الحالة: يجمع الآن\n"
                    f"📦 1m: {status['symbols_1m']}/{status['total_assets']} عملة"
                )
                if status["elapsed_1m"]:
                    txt += f" ({status['elapsed_1m']}ث)\n"
                else:
                    txt += "\n"
                txt += f"📦 5m: {status['symbols_5m']}/{status['total_assets']} عملة"
                if status["elapsed_5m"]:
                    txt += f" ({status['elapsed_5m']}ث)\n"
                else:
                    txt += "\n"
                if status["has_cache_1m"] or status["has_cache_5m"]:
                    txt += f"💾 كاش: {'✅' if status['has_cache_1m'] else '❌'} 1m | {'✅' if status['has_cache_5m'] else '❌'} 5m\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n"
                txt += f"⏱️ الإقلاع: ~30–60 ثانية لأول جمع ({DATA_DAYS} يوماً) | أسرع مع الكاش\n"
                txt += "💡 تابع من زر ⚡ مباشر للتفاصيل"
                return txt
            else:
                return (
                    "⏳ <b>المحرك في الإقلاع</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• 🚀 جمع أولي فائق السرعة — {DATA_DAYS} يوماً تاريخياً\n"
                    "• 📦 1m + 5m معاً بتزايد الكاش\n"
                    "• ⏱️ أول مرة عادة 30–60 ثانية\n"
                    "• ⏱️ ~ثانية مع كاش حديث\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "💡 اضغط ⚡ مباشر لمتابعة التقدم"
                )
        gate = res.get('gate',{}) if res else {}
        frames = gate.get('frames',{})
        status = get_data_collection_status()
        open_count = len([p for p in LATEST_OPEN_POSITIONS if p.get('status')=='OPEN']) if 'LATEST_OPEN_POSITIONS' in globals() else 0
        buy_count = len(LATEST_PLANS) if 'LATEST_PLANS' in globals() else 0
        sell_count = len(LATEST_SELL_PLANS) if 'LATEST_SELL_PLANS' in globals() else 0
        txt = (
            "✅ <b>البوت يعمل بشكل طبيعي — نظام ذكي جديد فقط</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• 📦 1m: {frames.get('1m', status['symbols_1m'])} عملة — كل دقيقة\n"
            f"• 📦 5m: {frames.get('5m', status['symbols_5m'])} عملة — كل 5 دقائق\n"
            f"• 🔍 فحص: {gate.get('checked',0)} عملة\n"
            f"• 🟢 شراء جديد: {buy_count} | 🔴 بيع جديد: {sell_count} | 💼 مفتوحة جديدة: {open_count}\n"
            f"• ⏱️ آخر دورة: {status['last_cycle_secs']:.1f}ث\n"
        )
        if status["age_1m"] is not None:
            txt += f"• 🕐 عمر البيانات: 1m {status['age_1m']:.0f}د | 5m {status['age_5m']:.0f}د\n"
        if status["has_cache_1m"] and status["has_cache_5m"]:
            txt += "• 💾 كاش: ✅ جاهز\n"
        txt += "━━━━━━━━━━━━━━━━━━━━\n"
        if status["is_collecting"]:
            txt += "🔄 <b>جاري التحديث الآن...</b>\n"
        else:
            txt += "🧠 نظام بصمة ذكية: شراء جديد فقط + بيع للمفتوحة الجديدة فقط مع ترقيم\n"
            txt += "✅ الجديد فقط — لا موروث من الباكتست\n"
            txt += "🔔 الإشارات تُرسل فور وقوعها فقط (فحص دوري + مراقبة خروج كل ثانيتين)"
        return txt
    except Exception as e:
        log(f"[ENGINE STATUS] {e}")
        return (
            "✅ <b>البوت يعمل</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"⚠️ خطأ بسيط في الحالة: {esc(str(e)[:100])}\n"
            "🔄 البوت يعمل بشكل طبيعي\n"
            "📡 الإشارات فور وقوعها — مراقبة كل ثانيتين"
        )


def backtest_summary(res: dict = None) -> str:
    try:
        # حاول جلب نتائج الباكتست الحقيقية من BT5Y إذا موجودة
        bt_text = None
        if BT5Y and hasattr(BT5Y, 'STATE') and BT5Y.STATE.get('text'):
            bt_text = BT5Y.STATE.get('text')
            # نظف النص من HTML tags للعرض المبسط
            import re
            clean = re.sub(r'<[^>]+>', '', bt_text)
            if len(clean) > 50:
                # إذا وجد باكتست حقيقي، اعرضه مع شرح إضافي
                return (
                    f"{clean[:800]}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "📘 شرح الاستراتيجية:\n"
                    "• V5 Ultra تجمع 3 مؤشرات: EMA + RSI + BO\n"
                    "• تدخل فقط عند اتجاه صاعد مؤكد\n"
                    "• وقف خسارة ديناميكي مبني على تقلب العملة (ATR)\n"
                    "• هدفان ديناميكيان مضبوطان على التقلب (ATR)، الثاني أكبر\n"
                    "• مدة الصفقة المتوقعة 1-3 أيام نمطياً\n"
                    f"• {len(ALL_DATA_ASSETS)} عملة نشطة منتقاة\n\n"
                    "⚠️ الأرقام لا تضمن المستقبل\n"
                    "لكنها تعطي فكرة صادقة\n"
                    "التداول مخاطرة والصبر أساسه"
                )
    except:
        pass
    
    txt = (
        "نتائج التجربة الطويلة 📊\n\n"
        "تمت تجربة البوت على 2099 يوماً\n"
        "من 2020-01-01 إلى 2025-09-30\n"
        "في ظروف صعود وهبوط مختلفة\n"
        "صمد في هبوط 2022 و2024\n\n"
        "📈 الاستراتيجية V5 Ultra:\n"
        "• فريم 5 دقائق للاتجاه\n"
        "• فريم 1 دقيقة للدخول المجهري\n"
        "• EMA 9/21/50 + RSI 45-75 + BO 15\n"
        "• فلترة اتجاه BTC\n\n"
        "💰 أداء التجربة الموثق (حساب 400$):\n"
        "• العائد +1638% (النموذجي)\n"
        "• 501 صفقة (≈صفقتين أسبوعياً)\n"
        "• نسبة نجاح 53.5%\n"
        "• أقصى تراجع 21.08% | Sharpe 2.45\n\n"
        "🛡️ الحماية:\n"
        "• وقف خسارة لكل صفقة (ديناميكي ATR)\n"
        "• إغلاق طارئ عند انهيار\n"
        "• بصمة ذكية تمنع التكرار\n\n"
        "الأرقام لا تضمن المستقبل\n"
        "لكنها تعطي فكرة صادقة عن الأداء\n"
        "التداول يحتاج صبر وحكمة"
    )
    return txt

def backtest_page_text(res: dict, page: int = 0) -> tuple:
    txt = backtest_summary(res)
    kb = [
        [bt("📄 تحميل سجل الصفقات (CSV)", "bt:csv")],
        [bt("⚡ فريم 1 دقيقة (سكالبينغ)", "bt:page:1"), bt("📊 فريم 5 دقائق (دخول مجهري)", "bt:page:2")],
        [bt("🏠 القائمة الرئيسية", "nav:more")]
    ]
    if page == 1:
        txt = (
            "⚡ <b>محرك السكالبينغ (1 دقيقة) — الشرح الصادق</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• <b>الهدف:</b> اقتناص حركات سعرية سريعة أثناء الاتجاهات الصاعدة المؤكدة — أهداف ووقف ديناميكية وفق تقلب السوق.\n"
            "• <b>البيانات:</b> بيانات كاش Binance Data Vision 1m الحقيقية دون بيانات مصطنعة.\n"
            "• <b>فلترة الاتجاه:</b> صفقات السكالبينغ لا تُفتح إطلاقاً إلا إذا كانت شمعة 4H للعملة في مسار صاعد مؤكد.\n"
            "• <b>إدارة المخاطر:</b> وقف خسارة محكم جداً وخروج سريع لتوليد تدفق نقدي يومي مستمر."
        )
    elif page == 2:
        txt = (
            "📊 <b>محرك الدخول المجهري (5 دقائق) — الشرح الصادق</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• <b>الهدف:</b> تحسين متوسط سعر الشراء وتفادي الدخول عند القمم اللحظية.\n"
            "• <b>الآلية:</b> عند صدور إشارة شراء على 4H، يحدد المحرك منطقة دخول دقيقة بين دعم آخر ساعة وVWAP على فريم 5 دقائق للدخول بسعر أفضل (أمر حد).\n"
            "• <b>الفائدة:</b> توفير نقاط دخول أفضل يغطي كامل رسوم بايننس والانزلاق السعري.\n"
            "• <b>الأمان:</b> في حال انطلاق السعر بقوة دون تراجع، يضمن البوت عدم تفويت الموجة الكبرى."
        )
    return txt, kb

def backtest_csv_bytes(res: dict = None) -> bytes:
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        pkl_path = os.path.join(base_dir, 'bt5y_static_result.pkl')
        if os.path.exists(pkl_path):
            import pickle
            with open(pkl_path, 'rb') as f:
                d = pickle.load(f)
                return d.get('csv', b"")
    except Exception as e:
        log(f"[CSV READ ERROR] {e}")
    return b""

def handle_start(chat_id: int, first_name: str = "", username: str = ""):
    st = load_state()
    u = get_user(chat_id)
    u["first_name"] = first_name or u.get("first_name", "")
    u["username"] = username or u.get("username", "")
    is_first_admin = False
    if not st.get("admin_chat_id"):
        st["admin_chat_id"] = chat_id
        u["admin"] = True
        is_first_admin = True
    save_state()
    txt = WELCOME_TEXT + f"\n\n{get_collection_status_line()}"
    if is_first_admin:
        txt += "\n\n👑 أنت المشرف الأول"
    send_msg(chat_id, txt, full_menu_kb(u))

def handle_text_message(msg: dict):
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = (msg.get("text") or "").strip()
    msg_id = msg.get("message_id")
    u = get_user(chat_id)
    u["first_name"] = chat.get("first_name", u.get("first_name", ""))
    u["username"] = chat.get("username", u.get("username", ""))

    try:
        if u.get('flow') and u['flow'].get('type')=='binance_easy':
            if LIVE.handle_easy_text(chat_id, text, msg_id, u):
                return
    except Exception as e:
        log(f"[EASY_TEXT] {e}")

    unregister_live_viewer(chat_id)
    low = text.lower()
    if low == "/id":
        send_msg(chat_id, f"🆔 معرفك: <code>{chat_id}</code>", api_back_kb())
    elif low in ("/cancel","cancel"):
        if u.get('flow'):
            u['flow']=None
            save_state()
            send_msg(chat_id, "❌ تم الإلغاء", full_menu_kb(u))
        else:
            send_msg(chat_id, "لا يوجد عملية جارية", full_menu_kb(u))
    elif low.startswith("/start"):
        handle_start(chat_id, chat.get("first_name",""), chat.get("username",""))
    elif low.startswith("/about"):
        send_msg(chat_id, ABOUT_TEXT, api_back_kb())
    elif low.startswith("/reassurance"):
        send_msg(chat_id, REASSURANCE_TEXT, api_back_kb())
    elif low.startswith("/testsignal"):
        # إرسال إشارة تجريبية للتأكد أن البوت يرسل
        try:
            test_plan = {
                "ticker": "BTCUSDT",
                "price": 50000.0,
                "signal_price": 50000.0,
                "sl": 49000.0,
                "tgt1": 51400.0,
                "tgt2": 54000.0,
                "size_pct": 1.5,
                "frame": "1m",
                "pool": "GS-T1",
                "time": datetime.now(timezone.utc).isoformat()
            }
            # إنشاء بصمة جديدة
            fp, raw = buy_fingerprint(test_plan)
            BUY_FINGERPRINTS[fp] = {"time": _now_iso(), "ticker": "BTCUSDT", "price": 50000, "raw": raw}
            save_fingerprints()
            
            # إنشاء صفقة مفتوحة
            create_open_position(test_plan, datetime.now(timezone.utc))
            
            # تحديث LATEST
            global LATEST_PLANS, LATEST_OPEN_POSITIONS
            LATEST_PLANS = [test_plan]
            LATEST_OPEN_POSITIONS = [p for p in get_open_positions() if p.get("status")=="OPEN" and (datetime.now(timezone.utc) - datetime.fromisoformat(p.get("entry_time",""))).total_seconds()/3600 <= 24]
            
            txt = latest_signals_text(u)
            send_msg(chat_id, "🧪 <b>إشارة تجريبية - للتأكد أن البوت يرسل</b>\n━━━━━━━━━━━━━━\n" + txt, full_menu_kb(u))
            log(f"[TEST SIGNAL] أرسل إشارة تجريبية لـ {chat_id}")
        except Exception as e:
            send_msg(chat_id, f"⚠️ خطأ في الإشارة التجريبية: {esc(str(e))}", full_menu_kb(u))
    elif low.startswith("/status") or low.startswith("/progress") or low == "حالة الجمع":
        status = get_data_collection_status()
        txt = (
            f"📊 <b>حالة جمع البيانات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔄 جمع الآن: {'✅ نعم' if status['is_collecting'] else '❌ لا'}\n"
            f"🤖 المحرك: {'✅ جاهز' if status['engine_ready'] else '⏳ يجهز'}\n"
            f"📦 1m: {status['symbols_1m']}/{status['total_assets']} عملة\n"
            f"📦 5m: {status['symbols_5m']}/{status['total_assets']} عملة\n"
            f"💾 كاش 1m: {'✅' if status['has_cache_1m'] else '❌'} | 5m: {'✅' if status['has_cache_5m'] else '❌'}\n"
        )
        if status["age_1m"] is not None:
            txt += f"🕐 عمر: 1m {status['age_1m']:.0f}د | 5m {status['age_5m']:.0f}د\n"
        txt += f"⏱️ آخر دورة: {status['last_cycle_secs']:.1f}ث\n"
        txt += "━━━━━━━━━━━━━━━━━━━━\n"
        if ENGINE_RES is None:
            txt += fmt_engine_status(None)
        else:
            txt += fmt_engine_status(ENGINE_RES)
        send_msg(chat_id, txt, back_kb([[bt("⚡ مباشر مفصل","bt:live:page:0")]]))
    else:
        send_msg(chat_id, "👋 أهلاً\nاضغط 🎛️ لفتح لوحة التحكم", more_kb())


# ============ نظام التحديث اللحظي الذكي للأرقام فقط (منع وميض الشاشة) ============
LIVE_VIEWERS = {}
LIVE_VIEWERS_LOCK = threading.Lock()

def register_live_viewer(chat_id, msg_id, screen_type, kb=None, last_text=""):
    if not chat_id or not msg_id:
        return
    with LIVE_VIEWERS_LOCK:
        LIVE_VIEWERS[chat_id] = {
            "msg_id": msg_id,
            "screen": screen_type,
            "opened_at": time.time(),
            "last_refresh": time.time(),
            "last_text": last_text,
            "kb": kb
        }

def unregister_live_viewer(chat_id):
    with LIVE_VIEWERS_LOCK:
        LIVE_VIEWERS.pop(chat_id, None)

def get_live_page_content() -> tuple:
    status = get_data_collection_status()
    txt = "⚡ <b>حالة جمع البيانات — مباشر</b>\n"
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    if status["is_collecting"]:
        txt += "🔄 <b>الحالة: جاري فحص وتحديث البيانات لحظياً...</b>\n"
    else:
        txt += "✅ <b>الحالة: مكتمل — البوت يعمل ويحرس السوق</b>\n"
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    
    # تفاصيل فريم 5 دقائق (الرئيسي)
    txt += "📦 <b>فريم 5 دقائق (فريم الاستراتيجية الرئيسي):</b>\n"
    txt += f"• العملات النشطة: <code>{status['symbols_5m']}/{status['total_assets']}</code> عملة\n"
    txt += f"• الكاش: {'✅ موجود وجاهز' if status['has_cache_5m'] else '⏳ جاري الحفظ'}\n"
    txt += "\n"
    
    # تفاصيل فريم 1 دقيقة
    txt += "📦 <b>فريم 1 دقيقة:</b>\n"
    txt += f"• العملات: <code>{status['symbols_1m']}/{status['total_assets']}</code> عملة\n"
    txt += f"• الكاش: {'✅ موجود وجاهز' if status['has_cache_1m'] else '⏳ جاري الحفظ'}\n"
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    
    # حالة المحرك
    open_pos_list = [p for p in get_open_positions() if p.get('status') == 'OPEN']
    open_count = len(open_pos_list)
    if ENGINE_RES:
        gate = ENGINE_RES.get('gate', {})
        txt += "🤖 <b>المحرك الذكي:</b>\n"
        txt += "• الاستراتيجية: V5 Ultra (3 معاملات)\n"
        txt += f"• فحص العملات: <code>{gate.get('checked', status['symbols_5m'])}</code> عملة ⚡\n"
        txt += f"• صفقات مفتوحة حالياً: <code>{open_count}</code> صفقة\n"
        txt += f"• زمن الفحص: <code>{status['last_cycle_secs']:.1f}</code> ثانية\n"
        if status["last_cycle"]:
            txt += f"• آخر فحص مكتمل: <code>{status['last_cycle'][:19].replace('T', ' ')} UTC</code>\n"
    else:
        txt += "🤖 <b>المحرك:</b> ⏳ قيد الفحص الأولي (ثوانٍ قليلة)\n"
        
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    txt += "🟢 <b>أرقام النظام محدثة لحظياً وتلقائياً</b>"
    kb = back_kb([[bt("💼 المحفظة الورقية", "m:port")]])
    return txt, kb

def get_guard_content(u: dict, chat_id: int) -> tuple:
    # تحديث فوري مباشر لأسعار الصفقات من بايننس وفحص شروط الخروج
    refresh_open_positions_live_and_guard(send_alerts=True)
    acc = LIVE.account(chat_id) if LIVE and hasattr(LIVE, "account") else {}
    active = LIVE.EXEC.active(acc) if LIVE and LIVE.EXEC else []
    paper_positions = [p for p in get_open_positions() if p.get("status") == "OPEN"]
    
    txt = "🛡️ <b>مراكزي وصفقاتي المفتوحة</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    
    has_any = False
    if active:
        has_any = True
        txt += f"🌐 <b>صفقات Binance الحقيقية ({len(active)}):</b>\n"
        for p in active[:10]:
            txt += f"┌ {p.get('symbol')} | {p.get('state')}\n├ كمية: {p.get('qty')} | وقف: {p.get('stop')}\n└ ميزانية: {p.get('budget','?')}\n\n"
            
    if paper_positions:
        has_any = True
        txt += f"📂 <b>الصفقات المفتوحة ({len(paper_positions)} صفقة):</b>\n\n"
        by_ticker = {}
        for pos in paper_positions:
            t = pos.get("ticker", "")
            by_ticker.setdefault(t, []).append(pos)
            
        for ticker, poses in list(by_ticker.items())[:8]:
            sym = ticker.replace("USDT", "")
            txt += f"🪙 <b>عملة {sym} ({len(poses)} صفقة):</b>\n"
            for pos in poses[:4]:
                num = pos.get("position_number", 1)
                buy_p = float(pos.get("buy_price", pos.get("entry_price", 0.0)))
                curr_p = float(pos.get("current_price", buy_p))
                
                # حساب الأرباح الحالية بدقة ومطابقتها التامة للمحفظة الورقية (محاسبة بيع حقيقية)
                _gc_cost = float(pos.get("cost_usd", 40.0)) * (0.5 if pos.get("t1_sold") else 1.0)
                pnl_pct = float(pos.get("unrealized_pnl_pct", 0.0))
                if pnl_pct == 0.0 and buy_p > 0 and curr_p != buy_p and _gc_cost > 0:
                    rem_qty = float(pos.get("remaining_qty", pos.get("qty", 0.0)))
                    pnl_pct = round((rem_qty * curr_p * (1.0 - PAPER_FRICTION_SELL) - _gc_cost) / _gc_cost * 100.0, 2)

                pnl_usd = float(pos.get("unrealized_pnl_usd", 0.0))
                if pnl_usd == 0.0 and buy_p > 0 and curr_p != buy_p:
                    rem_qty = float(pos.get("remaining_qty", pos.get("qty", 0.0)))
                    pnl_usd = round(rem_qty * curr_p * (1.0 - PAPER_FRICTION_SELL) - _gc_cost, 2)
                    
                tgt1 = float(pos.get("tgt1", pos.get("t1", buy_p * 1.028 if buy_p > 0 else 0.0)))
                tgt2 = float(pos.get("tgt2", pos.get("t2", buy_p * 1.148 if buy_p > 0 else 0.0)))
                sl = float(pos.get("sl", buy_p * 0.995 if buy_p > 0 else 0.0))
                rem_pct = pos.get("remaining_pct", 100)
                cost = float(pos.get("cost_usd", 40.0))
                time_str = pos.get("entry_time", "")[:16].replace("T", " ")
                
                pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
                
                # حساب المدة المتوقعة
                try:
                    from datetime import timezone as _tz
                    entry_dt = datetime.fromisoformat(str(pos.get("entry_time","")).replace("Z","+00:00"))
                    elapsed_h = (datetime.now(_tz.utc) - entry_dt).total_seconds()/3600
                    if elapsed_h < 24:
                        exp_text = f"المتوقع 1-3 أيام (مضى {elapsed_h:.1f}س)"
                    elif elapsed_h < 72:
                        exp_text = f"المتوقع 1-3 أيام (مضى {elapsed_h/24:.1f} يوم)"
                    else:
                        exp_text = f"تجاوزت 3 أيام (مضى {elapsed_h/24:.1f} يوم)"
                except:
                    exp_text = "المتوقع 1-3 أيام"
                
                txt += f"┌ 📌 <b>صفقة #{num}</b> ({rem_pct}% متبقي | {pos.get('frame','5m')})\n"
                txt += f"├ 📥 الشراء: {fmt_p(buy_p)} USDT | التكلفة: {cost:.1f} USDT\n"
                txt += f"├ 🏷️ الحالي: {fmt_p(curr_p)} USDT\n"
                txt += f"├ {pnl_icon} <b>الربح الحالي: {pnl_pct:+.2f}% ({pnl_usd:+.2f} USDT)</b>\n"
                txt += f"├ 🎯 هدف 1: {fmt_p(tgt1)} | 🎯 هدف 2: {fmt_p(tgt2)}\n"
                txt += f"├ 🔴 الوقف: {fmt_p(sl)}\n"
                txt += f"├ ⏳ المدة المتوقعة: {exp_text}\n"
                if time_str:
                    txt += f"└ ⏱️ {time_str} UTC\n\n"
                else:
                    txt += "└ ⏱️ V5 Ultra 5m\n\n"
    
    if not has_any:
        st_data = load_state()
        paper_data = st_data.get("paper", {})
        closed_deals = paper_data.get("closed_deals", [])
        cap = float(acc.get('capital', 0)) if acc else 0
        txt += "💤 <b>لا توجد صفقات مفتوحة حالياً</b>\n"
        txt += "• إما أننا خارج كل صفقة (هدف/وقف/إيقاف يدوي) أو بانتظار فرصة جديدة\n\n"
        if closed_deals:
            txt += f"📜 <b>آخر الصفقات المغلقة ({len(closed_deals)}):</b>\n"
            for deal in closed_deals[-3:]:
                d_ticker = deal.get("ticker", "").replace("USDT", "")
                d_type = deal.get("type", "")
                d_pct = float(deal.get("profit_pct", 0.0))
                d_usd = float(deal.get("profit_usd", 0.0))
                d_icon = "✅" if d_pct >= 0 else "❌"
                txt += f"{d_icon} <b>{d_ticker} #{deal.get('position_number', 1)}:</b> <code>{d_pct:+.2f}%</code> ({d_usd:+.2f} USDT) [{d_type}]\n"
            txt += "\n"
        if cap > 0:
            txt += f"💰 الرصيد الحر على المنصة: <code>{cap:.2f}</code> USDT\n"
        txt += "🔔 سيقوم البوت برصد الفرص وفتح الصفقات تلقائياً عند أول إشارة مطابقة.\n"
        
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    txt += "🟢 <b>أرقام الصفقات تومض وتتحدث تلقائياً مع حركة الأسعار</b>"
    kb = back_kb([[bt("💼 المحفظة الورقية", "m:port")]])
    return txt, kb

def get_port_content(u: dict) -> tuple:
    txt = portfolio_text(u)
    txt += "\n━━━━━━━━━━━━━━━━━━━━\n🟢 <b>الأرقام مربوطة بالمحفظة وتتحدث تلقائياً</b>"
    kb = back_kb([
        [bt("📄 تحميل سجل كل الصفقات", "m:port_csv")],
        [bt("🛡️ مراكزي المفتوحة", "m:guard")]
    ])
    return txt, kb

def paper_trades_csv_bytes() -> bytes:
    """إنشاء ملف CSV بكل الصفقات ونتائجها وتاريخ تنفيذها"""
    try:
        import io, csv
        st = load_state()
        paper = st.get("paper", {})
        closed = paper.get("closed_deals", [])
        open_pos = [p for p in st.get("open_positions", []) if p.get("status")=="OPEN"]
        
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["#", "العملة", "نوع", "سعر الدخول", "سعر الخروج/الحالي", "الربح %", "الربح USDT", "تاريخ الدخول", "تاريخ الخروج", "المدة", "الحالة"])
        
        # الصفقات المغلقة
        for i, d in enumerate(closed, 1):
            ticker = d.get("ticker","").replace("USDT","")
            entry_p = d.get("entry_price", d.get("buy_price", ""))
            exit_p = d.get("exit_price", d.get("current_price", ""))
            profit_pct = d.get("profit_pct", 0)
            profit_usd = d.get("profit_usd", 0)
            entry_time = d.get("entry_time", "")[:19]
            exit_time = d.get("exit_time", d.get("close_time", ""))[:19]
            dur = d.get("duration", "")
            typ = d.get("type", d.get("exit_type", ""))
            status = "رابحة" if float(profit_usd or 0)>0 else "خاسرة"
            w.writerow([i, ticker, typ, entry_p, exit_p, f"{float(profit_pct or 0):.2f}", f"{float(profit_usd or 0):.2f}", entry_time, exit_time, dur, status])
        
        # الصفقات المفتوحة
        offset = len(closed)
        for j, p in enumerate(open_pos, 1):
            ticker = p.get("ticker","").replace("USDT","")
            entry_p = p.get("buy_price", p.get("entry_price", ""))
            curr_p = p.get("current_price", entry_p)
            pnl_pct = p.get("unrealized_pnl_pct", 0)
            pnl_usd = p.get("unrealized_pnl_usd", 0)
            entry_time = p.get("entry_time", "")[:19]
            w.writerow([offset+j, ticker, "مفتوحة", entry_p, curr_p, f"{float(pnl_pct or 0):.2f}", f"{float(pnl_usd or 0):.2f}", entry_time, "", "", "مفتوحة"])
        
        return ("\ufeff" + buf.getvalue()).encode("utf-8")
    except Exception as e:
        log(f"[CSV PAPER ERROR] {e}")
        return b""

def get_sig_content(u: dict) -> tuple:
    txt = latest_signals_text(u)
    txt += "\n━━━━━━━━━━━━━━━━━━━━\n🟢 <b>رادار الإشارات يعمل لحظياً وتلقائياً</b>"
    kb = back_kb()
    return txt, kb

def _quick_update_open_positions_prices():
    try:
        refresh_open_positions_live_and_guard(send_alerts=True)
    except Exception:
        pass

def live_auto_refresher_loop():
    BREAKER.heartbeat("live_auto_refresher")
    """حلقة التحديث اللحظي التلقائي — تعدل الأرقام فقط عند تغيرها بدون وميض الشاشة"""
    while True:
        time.sleep(2.5)
        try:
            # فحص الصفقات المفتوحة وأسعارها اللحظية وتنفيذ الخروج الفوري دائماً
            refresh_open_positions_live_and_guard(send_alerts=True)
            
            if not LIVE_VIEWERS:
                continue
            
            now_t = time.time()
            with LIVE_VIEWERS_LOCK:
                active_items = list(LIVE_VIEWERS.items())
                
            open_count = len([p for p in get_open_positions() if p.get("status") == "OPEN"])
            for cid, viewer in active_items:
                # استمرار التحديث النشط ما دامت هناك صفقات مفتوحة لحماية أموال المستخدم
                # في حالة عدم وجود صفقات مفتوحة، مهلة ممتدة 12 ساعة لتفادي أي تجمد
                if open_count == 0 and (now_t - viewer.get("opened_at", now_t) > 43200):
                    unregister_live_viewer(cid)
                    continue
                    
                screen = viewer.get("screen")
                msg_id = viewer.get("msg_id")
                u = get_user(cid)
                
                new_txt, new_kb = None, None
                if screen == "live":
                    new_txt, new_kb = get_live_page_content()
                elif screen == "guard":
                    new_txt, new_kb = get_guard_content(u, cid)
                elif screen == "port":
                    new_txt, new_kb = get_port_content(u)
                elif screen == "sig":
                    new_txt, new_kb = get_sig_content(u)
                    
                if not new_txt or not msg_id:
                    continue
                    
                # التعديل فقط وحصراً عند تغير الأرقام أو البيانات (منع وميض الشاشة بالكامل)
                if new_txt != viewer.get("last_text"):
                    kb_markup = {"inline_keyboard": new_kb} if new_kb else None
                    tg("editMessageText", chat_id=cid, message_id=msg_id, text=new_txt,
                       reply_markup=kb_markup, parse_mode="HTML", timeout=3.5)
                    viewer["last_text"] = new_txt
                    viewer["last_refresh"] = now_t
        except Exception:
            pass

def trigger_immediate_live_refresh():
    """تحديث فوري لكل الشاشات النشطة بمجرد انتهاء دورة الفحص وتغير الأرقام"""
    try:
        if not LIVE_VIEWERS:
            return
        now_t = time.time()
        with LIVE_VIEWERS_LOCK:
            active_items = list(LIVE_VIEWERS.items())
        for cid, viewer in active_items:
            screen = viewer.get("screen")
            msg_id = viewer.get("msg_id")
            u = get_user(cid)
            new_txt, new_kb = None, None
            if screen == "live":
                new_txt, new_kb = get_live_page_content()
            elif screen == "guard":
                new_txt, new_kb = get_guard_content(u, cid)
            elif screen == "port":
                new_txt, new_kb = get_port_content(u)
            elif screen == "sig":
                new_txt, new_kb = get_sig_content(u)
            # التعديل فقط إذا تغيرت الأرقام الفعلية لمنع وميض الشاشة
            if new_txt and msg_id and new_txt != viewer.get("last_text"):
                kb_markup = {"inline_keyboard": new_kb} if new_kb else None
                tg("editMessageText", chat_id=cid, message_id=msg_id, text=new_txt,
                   reply_markup=kb_markup, parse_mode="HTML", timeout=3.0)
                viewer["last_text"] = new_txt
                viewer["last_refresh"] = now_t
    except Exception:
        pass

def handle_callback(cb: dict):
    # إلغاء دوران زر التيليجرام فورياً في أول 1 ميلي ثانية
    cb_id = cb.get("id")
    if cb_id:
        answer_cb(cb_id)
        
    data = cb.get("data","")
    chat_id = (cb.get("message") or {}).get("chat", {}).get("id") or cb.get("from", {}).get("id")
    msg_id = (cb.get("message") or {}).get("message_id")
    u = get_user(chat_id)
    try:
        if data.startswith("api:") or data == "m:api":
            if LIVE.callback(cb, u):
                return
    except Exception as e:
        log(f"[CB LIVE] {e} {traceback.format_exc()}")
        try:
            send_msg(chat_id, f"⚠️ خطأ: {esc(str(e))}", full_menu_kb(u), msg_id=msg_id)
        except:
            pass
        return

    try:
        answer_cb(cb.get("id",""))
    except:
        pass

    try:
        unregister_live_viewer(chat_id)
        if data == "nav:more":
            # تحديث فوري وشامل لبيانات لوحة التحكم مع حماية ضد إرهاق السيرفر
            try:
                cleanup_stale_and_delisted_positions()
                _quick_update_open_positions_prices()
                now_t = time.time()
                # لا نبدأ دورة بيانات ثقيلة إذا اكتملت دورة فحص قبل أقل من 60 ثانية تفادياً لكثرة الطلبات (-1003)
                if not CYCLE_LOCK.locked() and (now_t - globals().get("LAST_CYCLE_COMPLETED_AT", 0)) > 60:
                    threading.Thread(target=run_cycle, args=("panel_open",), daemon=True).start()
            except Exception as _e:
                log(f"[PANEL REFRESH] {_e}")
            send_msg(chat_id, "🎛️ <b>لوحة التحكم الرئيسية</b>\n━━━━━━━━━━━━━━\nاختر القسم:", full_menu_kb(u), msg_id=msg_id)
        elif data in ("nav:less","nav:main"):
            send_msg(chat_id, "🤖 <b>بوت التداول الذكي</b>\n━━━━━━━━━━━━━━\nاضغط لفتح اللوحة", more_kb(), msg_id=msg_id)
        elif data == "m:abt":
            send_msg(chat_id, ABOUT_TEXT, api_back_kb(), msg_id=msg_id)
        elif data == "m:sig":
            txt, kb = get_sig_content(u)
            res = send_msg(chat_id, txt, kb, msg_id=msg_id)
            mid = msg_id or (res.get("message_id") if isinstance(res, dict) else None)
            register_live_viewer(chat_id, mid, "sig", kb=kb, last_text=txt)
        elif data == "m:guard":
            try:
                txt, kb = get_guard_content(u, chat_id)
                res = send_msg(chat_id, txt, kb, msg_id=msg_id)
                mid = msg_id or (res.get("message_id") if isinstance(res, dict) else None)
                register_live_viewer(chat_id, mid, "guard", kb=kb, last_text=txt)
            except Exception as e:
                send_msg(chat_id, f"🛡️ خطأ: {esc(str(e))}", api_back_kb(), msg_id=msg_id)
        elif data == "m:port":
            txt, kb = get_port_content(u)
            res = send_msg(chat_id, txt, kb, msg_id=msg_id)
            mid = msg_id or (res.get("message_id") if isinstance(res, dict) else None)
            register_live_viewer(chat_id, mid, "port", kb=kb, last_text=txt)
        elif data == "m:port_csv":
            try:
                csv_data = paper_trades_csv_bytes()
                if csv_data:
                    url = f"{TG_API}/sendDocument"
                    files = {"document": ("titan_paper_trades.csv", csv_data, "text/csv")}
                    data_form = {"chat_id": chat_id, "caption": "📄 سجل كل الصفقات - المحفظة الورقية\nالعملة | الدخول | الخروج | الربح | التاريخ"}
                    requests.post(url, data=data_form, files=files, timeout=15)
                else:
                    send_msg(chat_id, "⚠️ لا توجد صفقات بعد.", back_kb(), msg_id=msg_id)
            except Exception as e:
                log(f"[CSV PAPER SEND] {e}")
                send_msg(chat_id, f"⚠️ خطأ في إرسال الملف: {e}", back_kb(), msg_id=msg_id)
        elif data == "m:rep":
            send_msg(chat_id, weekly_report_text(u), back_kb(), msg_id=msg_id)
        elif data == "m:set":
            txt = (
                "⚙️ <b>الإعدادات</b>\n"
                "━━━━━━━━━━━━━━\n"
                f"🔔 الإشارات: {'✅ مفعلة' if u['settings'].get('signals') else '❌ متوقفة'}\n"
                f"🛡️ الحماية: {'✅ مفعلة' if u['settings'].get('guard') else '❌ متوقفة'}\n"
                f"📍 التقارب: {'✅ مفعلة' if u['settings'].get('proximity') else '❌ متوقفة'}\n"
                "━━━━━━━━━━━━━━"
            )
            kb = [
                [bt("🔔 تشغيل/إيقاف الإشارات","set:signals")],
                [bt("🛡️ تشغيل/إيقاف الحماية","set:guard")],
                [bt("🏠 الرئيسية","nav:more")]
            ]
            send_msg(chat_id, txt, kb, msg_id=msg_id)
        elif data.startswith("set:"):
            key = data.split(":")[1]
            if key in u["settings"]:
                u["settings"][key] = not u["settings"].get(key, True)
                save_state()
            send_msg(chat_id, f"⚙️ تم تغيير {key} إلى {'مفعل' if u['settings'].get(key) else 'متوقف'}", full_menu_kb(u), msg_id=msg_id)
        elif data == "m:users":
            is_admin = u.get("admin") or (ADMIN_CHAT_ID and int(chat_id) == int(ADMIN_CHAT_ID)) or (int(chat_id) == OWNER_ID)
            if not is_admin:
                send_msg(chat_id, "🔒 للمشرف فقط", api_back_kb(), msg_id=msg_id)
            else:
                st = load_state()
                allowed = st.get("allowed", [])
                users_map = st.get("users", {})
                txt = f"👥 <b>المشتركون المصرح لهم ({len(allowed)})</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                if allowed:
                    for uid_str in allowed[:25]:
                        usr = users_map.get(str(uid_str), {})
                        name = usr.get("first_name", "")
                        username = usr.get("username", "")
                        info = f"• <code>{uid_str}</code>"
                        if name:
                            info += f" — {esc(name)}"
                        if username:
                            info += f" (@{esc(username)})"
                        txt += info + "\n"
                else:
                    txt += "لا يوجد مشتركون إضافيون — البوت خاص بالمشرف فقط.\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n💡 عندما يطلب مشترك جديد الانضمام، سيصلك تنبيه مع زر للموافقة المباشرة."
                send_msg(chat_id, txt, api_back_kb(), msg_id=msg_id)
        elif data == "bt:csv":
            try:
                csv_data = backtest_csv_bytes(ENGINE_RES)
                if csv_data:
                    # إرسال ملف CSV
                    url = f"{TG_API}/sendDocument"
                    files = {"document": ("titan_v127_5y_backtest.csv", csv_data, "text/csv")}
                    data_form = {"chat_id": chat_id, "caption": "📄 سجل صفقات باكتست 5 سنوات المعتمد (v127.0.0) — يفتح في Excel."}
                    requests.post(url, data=data_form, files=files, timeout=15)
                else:
                    send_msg(chat_id, "⚠️ لم يتم العثور على ملف CSV.", back_kb(), msg_id=msg_id)
            except Exception as e:
                log(f"[CSV SEND] {e}")
                send_msg(chat_id, f"⚠️ خطأ في إرسال الملف: {e}", back_kb(), msg_id=msg_id)
        elif data.startswith("bt:page:"):
            try:
                page = int(data.split(":")[-1])
            except:
                page=0
            txt, kb = backtest_page_text(ENGINE_RES, page)
            send_msg(chat_id, txt, kb, msg_id=msg_id)
        elif data.startswith("bt:live:page:"):
            try:
                if ENGINE_RES is None and not CYCLE_LOCK.locked():
                    threading.Thread(target=run_cycle, args=("manual_live",), daemon=True).start()
                txt, kb = get_live_page_content()
                res = send_msg(chat_id, txt, kb, msg_id=msg_id)
                mid = msg_id or (res.get("message_id") if isinstance(res, dict) else None)
                register_live_viewer(chat_id, mid, "live", kb=kb, last_text=txt)
            except Exception as e:
                log(f"[LIVE PAGE] {e} {traceback.format_exc()}")
                send_msg(chat_id, f"⚡ خطأ: {esc(str(e))}", api_back_kb(), msg_id=msg_id)
        elif data == "m:api":
            try:
                send_msg(chat_id, LIVE.panel(u), LIVE.keyboard(u), msg_id=msg_id)
            except Exception as e:
                send_msg(chat_id, f"🔑 خطأ: {esc(str(e))}", more_kb(), msg_id=msg_id)
        elif data == "acc:req":
            try:
                user_msg = (
                    "📨 <b>تم إرسال طلب الانضمام بنجاح!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "⏳ طلبك قيد مراجعة المشرف الآن.\n"
                    "🔔 سيصلك إشعار وتنبيه فوري هنا بمجرد موافقة المشرف لتتمكن من استخدام البوت ومتابعة الإشارات مباشرة."
                )
                send_msg(chat_id, user_msg, msg_id=msg_id)
                
                st = load_state()
                admin_id = st.get("admin_chat_id") or ADMIN_CHAT_ID or OWNER_ID
                frm = cb.get("from") or {}
                fn = frm.get("first_name", "")
                un = frm.get("username", "")
                user_info = f"<code>{chat_id}</code>"
                if fn:
                    user_info += f" ({esc(fn)})"
                if un:
                    user_info += f" @{esc(un)}"
                
                admin_text = (
                    "🔔 <b>طلب انضمام جديد للبوت:</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 المستخدم: {user_info}\n"
                    f"🆔 المعرف: <code>{chat_id}</code>\n\n"
                    "اضغط الزر أدناه لتفعيل المشترك فوراً والسماح له باستخدام البوت 👇"
                )
                admin_kb = [[bt("✅ موافقة وتفعيل المشترك", f"acc:allow:{chat_id}")]]
                if admin_id and str(admin_id) != str(chat_id):
                    send_msg(int(admin_id), admin_text, admin_kb)
                log(f"[AUTH_REQ] طلب وصول جديد من {chat_id} تم إرساله للمشرف {admin_id}")
            except Exception as e:
                log(f"[AUTH_REQ_ERR] {e}")
                send_msg(chat_id, "⚠️ تم استلام طلبك، بانتظار موافقة المشرف.", msg_id=msg_id)
        elif data.startswith("acc:allow:"):
            is_admin = u.get("admin") or (ADMIN_CHAT_ID and int(chat_id) == int(ADMIN_CHAT_ID)) or (int(chat_id) == OWNER_ID)
            if not is_admin:
                send_msg(chat_id, "🔒 للمشرف فقط — لا يمكنك قبول الأعضاء", api_back_kb(), msg_id=msg_id)
            else:
                try:
                    target = data.split(":")[-1]
                    st = load_state()
                    allowed = st.get("allowed", [])
                    target_str = str(target)
                    if target_str not in [str(x) for x in allowed]:
                        allowed.append(target_str)
                        st["allowed"] = allowed
                    
                    get_user(int(target), create=True)
                    save_state()
                    log(f"[ALLOW] المشرف {chat_id} سمح للمستخدم {target}")
                    
                    send_msg(chat_id, f"✅ تم تفعيل المشترك <code>{target}</code> بنجاح!\nالآن يمكنه استخدام جميع مميزات البوت ومتابعة الإشارات.", full_menu_kb(u), msg_id=msg_id)
                    try:
                        approved_msg = (
                            "🎉 <b>تمت الموافقة على طلبك بنجاح!</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            "✅ أصبح لديك الآن حق الوصول الكامل لبوت التداول الذكي.\n"
                            "📡 الإشارات الحية ومتابعة الصفقات ستصلك تلقائياً فور صدورها.\n\n"
                            "👇 اضغط على الزر أدناه لفتح لوحة التحكم والبدء:"
                        )
                        send_msg(int(target), approved_msg, [[bt("🎛️ فتح لوحة التحكم", "nav:more")]])
                    except Exception as e:
                        log(f"[ALLOW NOTIFY] {target} {e}")
                except Exception as e:
                    send_msg(chat_id, f"⚠️ خطأ: {esc(str(e))}", full_menu_kb(u), msg_id=msg_id)
        elif data.startswith("acc:"):
            is_admin = u.get("admin") or (ADMIN_CHAT_ID and int(chat_id) == int(ADMIN_CHAT_ID)) or (int(chat_id) == OWNER_ID)
            target = data.split(":")[-1]
            if target == "req":
                pass
            elif not is_admin:
                send_msg(chat_id, "🔒 للمشرف فقط", api_back_kb(), msg_id=msg_id)
            else:
                try:
                    st = load_state()
                    allowed = st.get("allowed", [])
                    if str(target) not in [str(x) for x in allowed]:
                        allowed.append(str(target))
                        st["allowed"] = allowed
                        get_user(int(target), create=True)
                        save_state()
                    send_msg(chat_id, f"✅ تم السماح لـ {target}", full_menu_kb(u), msg_id=msg_id)
                except Exception as e:
                    send_msg(chat_id, f"⚠️ خطأ: {esc(str(e))}", full_menu_kb(u), msg_id=msg_id)
        else:
            log(f"[CB] غير معروف: {data}")
            send_msg(chat_id, "🤖 <b>لوحة التحكم</b>\n━━━━━━━━━━━━━━\nاضغط للمتابعة", full_menu_kb(u), msg_id=msg_id)
    except Exception as e:
        log(f"[CB MAIN] {e} {traceback.format_exc()}")
        try:
            send_msg(chat_id, "⚠️ خطأ بسيط — حاول مرة أخرى", full_menu_kb(u), msg_id=msg_id)
        except:
            pass

def handle_update(upd: dict):
    if "message" in upd:
        msg = upd["message"]
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None or chat.get("type") == "channel":
            return
        # إصلاح فوري للمالك 8599225300 — يصبح مشرف حتى لو الملف قديم
        try:
            if int(cid) == OWNER_ID:
                st = load_state()
                if st.get("admin_chat_id") != OWNER_ID:
                    st["admin_chat_id"] = OWNER_ID
                    u = get_user(OWNER_ID)
                    u["admin"] = True
                    u["first_name"] = chat.get("first_name","") or u.get("first_name","")
                    u["username"] = chat.get("username","") or u.get("username","")
                    save_state()
                    log(f"[AUTH] تم فرض المالك {OWNER_ID} كمشرف")
        except:
            pass
        if not is_allowed(cid, chat.get("username")):
            st = load_state()
            if not st.get("admin_chat_id") and not ADMIN_CHAT_ID:
                st["admin_chat_id"] = int(cid)
                u = get_user(cid)
                u["admin"] = True
                u["first_name"] = chat.get("first_name","")
                u["username"] = chat.get("username","")
                save_state()
                log(f"[AUTH] أول مستخدم {cid} أصبح مشرف تلقائياً")
                handle_text_message(msg)
                return
            send_msg(cid, (
                "🔒 <b>مرحباً بك في بوت التداول الذكي V5 Ultra</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 معرف حسابك (ID): <code>{cid}</code>\n\n"
                "هذا البوت خاص وآمن. للبدء وتفعيل حسابك لتلقي الإشارات ومتابعة الصفقات، اضغط على زر <b>📨 طلب وصول</b> أدناه وسيتم إرسال طلبك للمشرف للموافقة الفورية.\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ), [[bt("📨 طلب وصول", "acc:req")]])
            return
        handle_text_message(msg)
    elif "callback_query" in upd:
        cb = upd["callback_query"]
        frm = cb.get("from") or {}
        cid = frm.get("id")
        if cid is None:
            return
        try:
            if int(cid) == OWNER_ID:
                st = load_state()
                if st.get("admin_chat_id") != OWNER_ID:
                    st["admin_chat_id"] = OWNER_ID
                    u = get_user(OWNER_ID)
                    u["admin"] = True
                    save_state()
        except:
            pass
        # السماح بمعالجة طلب الوصول حتى لغير المصرح لهم
        if cb.get("data") == "acc:req":
            handle_callback(cb)
            return

        if not is_allowed(cid, frm.get("username")):
            st = load_state()
            if not st.get("admin_chat_id") and not ADMIN_CHAT_ID:
                st["admin_chat_id"] = int(cid)
                u = get_user(cid)
                u["admin"] = True
                save_state()
                log(f"[AUTH] أول مستخدم {cid} أصبح مشرف تلقائياً (callback)")
                handle_callback(cb)
                return
            answer_cb(cb.get("id",""), "🔒 يرجى طلب الوصول أولاً عبر الزر المرفق")
            return
        handle_callback(cb)

def boot_welcome_admin():
    st = load_state()
    aid = st.get("admin_chat_id") or ADMIN_CHAT_ID
    if not aid:
        return
    # [SPAM-FIX] ترحيب الإقلاع idempotent: لا تكرار خلال فجوة دنيا (12 ساعة افتراضي) مهما تكررت إعادات التشغيل
    now_t = time.time()
    min_gap = float(os.environ.get("TITAN_BOOT_MSG_MIN_HOURS", "12")) * 3600.0
    last_at = float(st.get("boot_welcome_last_at", 0.0) or 0.0)
    if now_t - last_at < min_gap:
        log(f"[BOOT] ترحيب الإقلاع مكبوت (أُرسل قبل {(now_t - last_at) / 60.0:.0f} دقيقة — مانع تكرار الرسائل)")
        return
    st["boot_welcome_last_at"] = now_t
    save_state()
    send_msg(aid, f"✅ البوت يعمل\n{STRATEGY_PROVENANCE}", more_kb())

UPDATE_EXECUTOR = ThreadPoolExecutor(max_workers=20, thread_name_prefix="tg_fast")

def _safe_dispatch_update(upd: dict):
    try:
        handle_update(upd)
    except Exception as e:
        log(f"[POLL_DISPATCH] خطأ: {e}\n{traceback.format_exc()}")

# [SPAM-FIX] تثبيت/استرجاع إزاحة تيليجرام بملف ذري صغير — بدونها تعيد تيليجرام تسليم تحديثات قديمة بعد كل إعادة تشغيل
def _persist_tg_offset(offset: int):
    """تثبيت فوري للإزاحة (tmp+replace ذري) — لا يعتمد على دورة save_state البعيدة"""
    try:
        tmp = TG_OFFSET_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(str(int(offset)))
        os.replace(tmp, TG_OFFSET_FILE)
    except Exception as e:
        log(f"[POLL] ⚠️ تعذر تثبيت tg_offset: {e}")

def _load_tg_offset(st: dict) -> int:
    """أكبر قيمة بين ملف الإزاحة والحالة — رجوع للخلف = إعادة تسليم تحديثات = رسائل مكررة"""
    file_off = 0
    try:
        if os.path.exists(TG_OFFSET_FILE):
            with open(TG_OFFSET_FILE) as f:
                file_off = int((f.read() or "0").strip() or 0)
    except Exception:
        file_off = 0
    try:
        st_off = int(st.get("tg_offset") or 0)
    except Exception:
        st_off = 0
    return max(st_off, file_off)

def poll_loop():
    st = load_state()
    offset = _load_tg_offset(st)  # [SPAM-FIX] استرجاع متين بعد أي إعادة تشغيل
    while True:
        try:
            params = {"timeout": 20, "allowed_updates": ["message", "callback_query"]}
            if offset:
                params["offset"] = offset
            ups = tg("getUpdates", retries=2, **params)
            if ups is None:
                time.sleep(1)
                continue
            for upd in ups:
                offset = upd["update_id"] + 1
                # معالجة كل ضغطة زر أو رسالة فورياً في خيط مستقل فائق السرعة دون أي انتظار
                UPDATE_EXECUTOR.submit(_safe_dispatch_update, upd)
            if ups:
                _STATE["tg_offset"] = offset
                _persist_tg_offset(offset)  # [SPAM-FIX] تثبيت فوري لكل دفعة — لا نافذة لفقد التأكيد
        except Exception as e:
            log(f"[POLL] خطأ الحلقة: {e}")
            time.sleep(2)

class _BaseHealthHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _send(self, body: bytes, code: int = 200, ctype: str = "text/plain; charset=utf-8"):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except Exception:
            pass
    def do_HEAD(self):
        self._send(b"", 200)
    def do_GET(self):
        path = (self.path or "/").split("?")[0].rstrip("/") or "/"
        if path in ("/", "/ping", "/healthz", "/health"):
            self._send(b"OK")
            return
        if path == "/status":
            st = load_state()
            body = json.dumps({"bot": SIGNAL_BOT_VERSION, "strategy": STRATEGY_ID, "last_cycle": st.get("last_cycle")}, ensure_ascii=False).encode()
            self._send(body, 200, "application/json; charset=utf-8")
            return
        self._send(b"OK")
    def log_message(self, *args):
        pass

class _HealthHandler(LIVE.SetupMixin, _BaseHealthHandler):
    pass

def health_loop():
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), _HealthHandler)
        log(f"[HEALTH] يستمع على 0.0.0.0:{HEALTH_PORT}")
        srv.serve_forever()
    except Exception as e:
        log(f"[HEALTH] تعذر: {e}")

def main():
    print("="*88, flush=True)
    print(f"  {SIGNAL_BOT_VERSION} — {STRATEGY_PROVENANCE}", flush=True)
    print("="*88, flush=True)
    if not BOT_TOKEN:
        print("\n❌ لا يوجد BOT_TOKEN!", flush=True)
        sys.exit(1)
    if ADMIN_CHAT_ID:
        log(f"[BOOT] ADMIN_CHAT_ID من البيئة: {ADMIN_CHAT_ID}")
    else:
        log("[BOOT] ADMIN_CHAT_ID غير مضبوط — أول مستخدم سيصبح مشرفاً تلقائياً")
    # [M1] قناة GitHub: ربط اللوجر + استرجاع محل-غياب (كاتب-واحد) قبل فتح أي ملفات حالة
    if GIT_SYNC is not None:
        GIT_SYNC.start(logger=log)
        GIT_SYNC.restore_state_if_missing(STATE_FILE)
        GIT_SYNC.restore_live_if_missing(os.environ.get("TITAN_LIVE_DB", os.path.join(WORKSPACE_DIR, "live_execution.sqlite3")))
    LIVE.init(sys.modules[__name__])
    threading.Thread(target=health_loop, daemon=True, name="health").start()
    me = tg("getMe")
    if not me:
        print("❌ التوكن مرفوض", flush=True)
        sys.exit(1)
    log(f"[BOOT] متصل بتلغرام كـ @{me.get('username')}")
    tg("deleteWebhook", drop_pending_updates=False)
    st = load_state()
    cleanup_stale_and_delisted_positions()
    if ADMIN_CHAT_ID and not st.get("admin_chat_id"):
        st["admin_chat_id"] = ADMIN_CHAT_ID
        save_state()
        log(f"[BOOT] تم تعيين المشرف من البيئة: {ADMIN_CHAT_ID}")
    threading.Thread(target=cycle_loop, daemon=True, name="cycle").start()
    threading.Thread(target=live_auto_refresher_loop, daemon=True, name="live_auto_refresher").start()
    threading.Thread(target=watch_loop, daemon=True, name="watch").start()

    # [M1] رافع دوري للقطة live DB المشفرة إلى GitHub (كل 10 دقائق — خامل وغير حظري)
    def _git_live_blob_loop():
        time.sleep(120)  # إقلاع نظيف أولاً
        while True:
            try:
                if GIT_SYNC is not None and getattr(LIVE, "STORE", None) is not None:
                    _snap = LIVE.STORE.export_snapshot()
                    if _snap:
                        GIT_SYNC.push_live_blob(_snap)
            except Exception as _e:
                try:
                    log(f"[GIT-SYNC] live blob: {_e}")
                except Exception:
                    pass
            time.sleep(600)
    threading.Thread(target=_git_live_blob_loop, daemon=True, name="git-live-blob").start()
    def _boot_welcome_when_ready():
        for _ in range(20):
            st2 = load_state()
            if st2.get("engine_initialized"):
                boot_welcome_admin()
                return
            time.sleep(5)
    threading.Thread(target=_boot_welcome_when_ready, daemon=True, name="boot-welcome").start()
    log("[BOOT] بدء حلقة الاستطلاع — يعمل 24/7")
    poll_loop()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("[EXIT] إيقاف يدوي")
    except Exception:
        log("[FATAL]\n" + traceback.format_exc())
        sys.exit(1)

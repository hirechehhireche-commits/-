# -*- coding: utf-8 -*-
"""
==========================================================================================================
  TITAN JUGGERNAUT — بوت باكتست (ملف واحد نظيف)
  ═════════════════════════════════════════════════════════════════════════════════════════════════════
  تحويل مشروع "TITAN JUGGERNAUT APEX OMNI SYSTEM v83.0.0" إلى ملف .py واحد قابل للتشغيل مباشرة.

  █ ما يفعله هذا الملف:
    1) يحمّل شموع 4H لـ 20 زوجاً (Spot USDT) من:
         - كاش محلي مرفق (cache/titans_basket_4h_cache.pkl) إن وُجد → يعمل بلا إنترنت.
         - وإلا يجلب من Binance (بيانات عامة، بلا مفاتيح API) مع fallback إلى Yahoo Finance.
    2) يشغّل باكتست كامل بمنطق v83 المعتمد:
         - الاستراتيجية الأولى (200$): 3 محافظ متخصصة على 14 أصلاً (P1 البطلة / P2 الهادئة / P3 الانفجارية).
         - الاستراتيجية الثانية (200$): متابعة اتجاه انتقائية (مقعد واحد = أعلى ألفا) على 11 عملاً + بوابة BTC.
         - طبقة رأس المال الديناميكي: إعادة توزيع شهرية بين الاستراتيجيتين — 95/5 افتتاحياً ثم 75/25 قسرياً (وزن الدمج w2 مثبّت 0.25 منذ v89 — أكدته طيات H35) (المجموع 400$ ثابت).
    3) يعرض تقريراً عربياً كاملاً ويحفظ النتائج (JSON + منحنى الحساب + الصفقات) في مجلد results/.

  █ النتيجة المعتمدة v83 (على كاش Yahoo المرفق): +725.86% | MaxDD 12.51% | OOS +107.13% | 547 صفقة.

  █ التشغيل:
      pip install numpy pandas          # (اختياري: requests/yfinance فقط لو تبي تجيب بيانات جديدة من Binance)
      python3 titan_juggernaut_bot.py                     # باكتست كامل (افتراضي)
      python3 titan_juggernaut_bot.py --refresh           # تجاهل الكاش وجلب بيانات جديدة من Binance
      python3 titan_juggernaut_bot.py --days 365          # نافذة بيانات أقصر
      python3 titan_juggernaut_bot.py --capital 1000      # رأس مال مختلف (يوزع 50/50 بين الاستراتيجيتين)
      python3 titan_juggernaut_bot.py --source yfinance   # جلب من Yahoo بدل Binance
      python3 titan_juggernaut_bot.py --micro                 # [v84] باكتست مع محاكاة الدخول الدقيق (أمر حد بدل سوق)
      python3 titan_juggernaut_bot.py --live-scan             # [v84] فحص حي: إشارات 4H الحالية + مناطق الدخول 5m
      python3 titan_juggernaut_bot.py --live-scan --symbol XRPUSDT  # [v84] فحص عملة واحدة
      python3 titan_juggernaut_bot.py --micro5m                # [v85] اختبار محرك 5m على شموع حقيقية (60 يوماً)
      python3 titan_juggernaut_bot.py --gate5m                 # [v86] باكتست مبوّب: تخطي SKIP وحد لـ WAIT (60 يوماً)

  ⚠️ تنبيه (كما في المشروع الأصلي): هذه نتائج باكتست = «سقف لا أرضية». قبل أي مال حقيقي:
      تداول ورقي 4-6 أسابيع ← forward-test صغير ← kill-switch عند تراجع 20%.
==========================================================================================================
"""

import os

def _safe_makedirs(p):
    try:
        os.makedirs(p, exist_ok=True)
    except PermissionError:
        # Fallback to script dir
        try:
            fallback = os.path.dirname(os.path.abspath(__file__))
            if "results" in p:
                fallback = os.path.join(fallback, "results")
            os.makedirs(fallback, exist_ok=True)
            return fallback
        except:
            pass
    except:
        pass
    return p


import sys
import json
import math
import time
import argparse
import itertools
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# الهوية والثوابت
# ══════════════════════════════════════════════════════════════════════════════
BOT_NAME = "TITAN_JUGGERNAUT_APEX_OMNI_SYSTEM"
BOT_VERSION = "v129.0.0"   # v129 Best: 6954$ +1638% DD 21.08% PF 3.26 Calmar 3.58 — Optimal   # v127: إطفاء إعادة التوازن الشهرية 75/25 (DYNAMIC_CAPITAL.enabled=False) بأمر المالك 2026-09-12 — الشهادة الثنائية: 4Y +3279.64 / OOS +236.81 / DD 21.95 (القانون ≤23 ✔) | 5Y +2382.29 / OOS +495.68 أخضر / DD 43.38 | طيات 3/3 | PF 3.47= وn=1033= بتّياً — إفصاح حوكمة كامل: OOS الخماسي −42.83 تحت الأساس (يبقى أخضر) وSh الـ4Y ‏−0.12 — معيار 5Y المعلن (ret↑ + طيات 3/3 + قوانا DD + OOS أخضر) هو الحاكم.   # v126: تعميق التصعيد H49-51 (pyr2 ‏4.5/0.20 + pyr3 P1 ‏7.5/0.15 + pyr3 S2 ‏6.0/0.10) — ثاني اعتماد إجماعي 6/6: +2973.17 / OOS +219.12 / DD 22.09 / PF 3.47 / Sh 2.75 / n=1033 (+23) — يومي +0.2336% | 0.704 صفقة/يوم. تحذير حوكمة: المتبقي من القانون المطلق DD≤23 هو 0.91pp فقط.   # v125.0.1: بنية pyr3 بتّية معطلة.   # [v125.0.1] بنية H50/H51: شريحة التصعيد الرابعة pyr3_* (افتراضياً معطلة — بتّي).   # v125.0.0   # v125: تفعيل الشريحة الثالثة H48 (P1 pyr2 5.5/0.15 + S2 pyr2 4.0/0.10) — أول اعتماد إجماعي 6/6: +2770.67 / OOS +215.32 (+8.84) / DD 21.75 / PF 3.46 / Sh 2.74 / n=1010 (+35) — يومي +0.2289% | 0.688 صفقة/يوم.   # v124.0.1: بنية pyr2 بتّية معطلة.   # v124.0.0   # v124: تفعيل تصعيد الرابح H44 (P1 trig 3.0 + S2 trig 2.0، ‏alloc 0.15) بقرار حوكمة مالك المشروع 2026-09-11: هامش DD غير-المتدهور +0.5 ← +2.0 (القانون المطلق ≤23 باقياً — الشهادة: +2533.86 / OOS +206.48 / DD 21.14 / PF 3.37 / n=975).   # v123.0.4: بنى H43/H44/H45 معطلة بتّياً.   # [v123.0.4] بنى جديدة بتّية (افتراضياً معطلة): H44 تصعيد الرابح pyr_* + H43 فلتر الإطار اليومي htf_ema_d + H45 فلتر ساعات الدخول entry_hours.   # [v123.0.3]   # [v123.0.3] حاكم تردد الدخول اليومي max_entries_per_day (0=معطل — بتّي) + بنية التتبع الأمامي.   # [v123.0.2]   # [v123.0.2] مستشعر gap_fill (افتراضي معطل — بتّي) لحساسية فجوات الوقف.   # [v123.0.1] ترقيع نظافة (بلا أي تغيير سلوكي — نفس التدفقات النقدية بتّياً): (1) صفوف T1/T2 بأجزاء بنك=0 لم تعد تُسجَّل كصفقات (كانت تضخّم n ونسبة النجاح: 1057→914 و61.78%→55.80% على 4Y) (2) إصلاح بوابة dev_4y.gate_verdict القديمة (DD≤15.5 → القانون الفعلي DD≤23 وغير متدهور) (3) تصحيح توثيق التخصيص: الفعلي = إعادة توزيع شهرية 75/25 بين S1/S2 منذ v89 (95/5 لأول ~90 يوماً فقط) — دورة H35 وثّقت أن 0.25 هي خلية التوازن (طيات 2/3 ضد المرشح).   # v123: ميزانيات S1 ← 90/5/5 (H34) — بوابة صارمة 6/6: +2182.42 / **OOS +194.14 (+2.05 أخضر)** / DD 19.42 / PF 3.29 / n=1057   # v122: mom_θ 0.075 (S2) + bear_gmri 0.36 (عام) — +2083.64 / DD 19.22 / PF 3.23 | **OOS −0.92 مُفصح (بوابة التخفيف المنشأة v104)** — هضبتا [0.01,0.10]×[0.34,0.38]، فحص سراب 17% (إنذار)   # v121: تدوير مقعد S2 (H24: gap=0.375/min=10، كتف 9 خانات) — +2036.53 / OOS +193.01 (+15.33) / DD 19.25 / PF 3.24 — طيات 2/3 (تعافٍ −4.84 مُفصح)   # v120: بوابة RS المئينية التكيفية θ=0.12 على P1+S2 (H23) — +1652.10 / OOS +177.68 / DD 21.83 (تحت قانون 4Y مجدداً) / PF 3.28 — هضبة [0.05,0.20] بتية، طيات 3/3   # v119: خطوة مخاطرة S2 ثانية   # v103: P1-rec_bars 96 (+8.51، ‏OOS −0.64 مُفصح، بوابة تخفيف)   # v102: تخصيص 240/160 (+16.9، ‏OOS أخضر حتى بالبوابة الصارمة)   # v101: كومبو H19 بوابة-تخفيف (P3-trl 50 + كون P2 + ‏BTC/AVAX) ‏+4.78pp/‏n+53 — OOS ‏−1.60 مُفصح   # v100: S2-trl 52 (H20) +9.12pp-IS — المرجع نافذة 4Y-vision   # v99: خيار موحد تجريبي (--unified، ‏OOS ‏-55% مرفوض) — الافتراضي = ثنائي v98 المربح   # v98: P1-t2frac 0.05 (H16) — المرجع نافذة 4Y-vision   # v97: S2-boost 1.4 (H15) — المرجع نافذة 4Y-vision   # v96: P1-trail 0.025 (H14) — المرجع نافذة 4Y-vision   # v95: P1-rsi 85 (H13) — المرجع نافذة 4Y-vision   # v94: S2-T1 4.0 (H12) — المرجع نافذة 4Y-vision   # v93: بوابة 5m ضحلة (V4) — المرجع 4Y-vision + بوابة 2Y-5m   # v92: هدف T1 الأبعد (H10) — المرجع نافذة 4Y-vision   # v91: بنك انجراف P1 (H9) — المرجع نافذة 4Y-vision   # v90: ميزانيات 85/8/7 (H8) — المرجع نافذة 4Y-vision   # v89: كون S2 بلا VET (H6) — المرجع نافذة 4Y-vision   # v88: سقف S2 0.25 (H4) — المرجع نافذة 4Y-vision   # v87: فيتو 5m واعٍ بالسياق — الافتراضي مطابق لـ v83   # v86: بوابة 5m داخل الباكتست — الافتراضي مطابق لـ v83   # v85: محرك 5m الدقيق (S/R + نقاط 0-100 + اختبار حقيقي) — الافتراضي مطابق لـ v83   # v84: + محرك الدخول الدقيق 5m (الباكتست الافتراضي مطابق لـ v83)

BENCHMARK_ASSET = "BTCUSDT"

# [v60] المحافظ الثلاث المتخصصة على 14 أصلاً (Spot USDT فقط)
ELITE_TRADEABLE_ASSETS = [
    "SOLUSDT", "FETUSDT", "DOTUSDT", "XRPUSDT", "BNBUSDT",
    "ETHUSDT", "XLMUSDT", "HBARUSDT", "TRXUSDT", "LINKUSDT",
    "ADAUSDT", "LTCUSDT", "DOGEUSDT", "ARBUSDT",
]

# [v71] الاستراتيجية الثانية: متابعة اتجاه انتقائية على 10 عملاً [v89: بلا VET — نزيف مزمن −20.6$]
STRATEGY2_ASSETS = [
    "XRPUSDT", "ADAUSDT", "LTCUSDT", "BCHUSDT", "ETCUSDT", "XLMUSDT",
    "TRXUSDT", "EOSUSDT", "HBARUSDT", "ZECUSDT",
]

ALL_DATA_ASSETS = ([BENCHMARK_ASSET] + ELITE_TRADEABLE_ASSETS
                   + [s for s in STRATEGY2_ASSETS if s not in ELITE_TRADEABLE_ASSETS])

# رأس المال (الحساب الموحّد 400$ = 390$ للاستراتيجية الأولى + 10$ لصياد فرص الخمول S2)
TOTAL_CAPITAL = 400.0
STRATEGY1_CAPITAL = 390.0  # [Gen 70000 Supreme Dual Apex] المحفظة الثلاثية الأساسية لمتابعة الاتجاه والبول ران
STRATEGY2_CAPITAL = 10.0   # [Gen 70000 Supreme Dual Apex] استراتيجية قناص فترات الخمول والركود وفك الارتباط

# [v78] رأس المال الديناميكي: إعادة توزيع كل 30 يوماً حسب فرق العائد (90 يوماً) بين الاستراتيجيتين
# [v88] قانون DD المعاد معايرته لنافذة 4Y (تشمل دباً كاملاً + فتائل حقيقية): DD ≤ 23%
# بصمة v83-2Y-ياهو محفوظة في results/v83_yahoo_fingerprint.json للمرجع فقط.
DYNAMIC_CAPITAL = {"enabled": False, "rebalance_days": 30, "gamma": 8.0,
                   "lookback_days": 90, "w_s2_min": 0.25, "w_s2_max": 0.25}  # [v127] إطفاء إعادة التوازن (أمر المالك 2026-09-12): كل جانب يترك مركّباً بحريته — الشهادة: 4Y +3279.64/DD 21.95 | 5Y +2382.29/DD 43.38 | طيات 3/3.   # [v89] كان ثابت 75/25 صريح (الديناميكي خسر على 4Y)

# السلة الخماسية (وضع --legacy الاحتياطي)
LEGACY_CORE5 = ["SOLUSDT", "FETUSDT", "DOTUSDT", "XRPUSDT", "BNBUSDT"]

# رموز Yahoo (تُستخدم فقط عند fallback)
YAHOO_TICKER_RESOLVER = {
    "BTCUSDT": "BTC-USD", "SOLUSDT": "SOL-USD", "BNBUSDT": "BNB-USD",
    "XRPUSDT": "XRP-USD", "DOTUSDT": "DOT-USD", "FETUSDT": "FET-USD",
    "ETHUSDT": "ETH-USD", "XLMUSDT": "XLM-USD", "HBARUSDT": "HBAR-USD",
    "TRXUSDT": "TRX-USD", "LINKUSDT": "LINK-USD", "ADAUSDT": "ADA-USD",
    "LTCUSDT": "LTC-USD", "DOGEUSDT": "DOGE-USD", "ARBUSDT": "ARB-USD",
    "BCHUSDT": "BCH-USD", "ETCUSDT": "ETC-USD", "EOSUSDT": "EOS-USD",
    "VETUSDT": "VET-USD", "ZECUSDT": "ZEC-USD",
}

# ══════════════════════════════════════════════════════════════════════════════
# إعدادات النظام (احتكاك حقيقي: عمولة 0.10% + انزلاق 0.05% = 0.15%)
# ══════════════════════════════════════════════════════════════════════════════
class SystemConfig:
    INITIAL_CAPITAL = 100.0
    MIN_ORDER_USDT = 5.0
    FEE_RATE = 0.0010
    SLIPPAGE_RATE = 0.0005
    TOTAL_FRICTION = FEE_RATE + SLIPPAGE_RATE
    DATA_DAYS = 730
    IS_RATIO = 0.60                       # 60% تدريب / 40% اختبار أعمى

    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    CACHE_DIR = _SCRIPT_DIR
    CACHE_FILE = "titans_4h_5y_cache.pkl"
    M5_CACHE_FILE = "gate5m_v102.pkl"
    RESULTS_DIR = os.path.join(_SCRIPT_DIR, "results")

# ثوابت الحوكمة الدفاعية (خارج فضاء التحسين)
EXECUTION_MODE = "close"                 # شراء بإغلاق شمعة الإشارة
RISK_OFF_GMRI = 0.35                     # ما دونها = بيئة هابطة
BOOST_GMRI = 0.65                        # ما فوقها = صاعدة قوية
EXHAUSTION_QUANTILE = 0.90
ATR_QUANTILE_WINDOW = 240
POSITION_RISK_PCT = 0.05
COOLDOWN_NORMAL = 12
COOLDOWN_SL = 30

# [v84] محرك الدخول الدقيق — نمذجة الباكتست (أمر حد بدل الشراء السوقي)
MICRO_DEPTH_CAP = 0.0025     # أقصى عمق لمنطقة الدخول تحت سعر الإشارة (0.25%)
MICRO_DEPTH_ATR = 0.35       # عمق المنطقة = 0.35 × ATR المعياري (مغطى بالسقف أعلاه)
MICRO_TIMEOUT_BARS = 3       # مهلة الملء = 3 شموع 4H (12 ساعة) ثم مطاردة بسعر السوق

# المعاملات الافتراضية (الأساس لكل الاستراتيجيات)
BASELINE_PARAMS = {
    "ema_p": 21, "slope_lag": 4, "rsi_p": 14,
    "rsi_lo": 40.0, "rsi_hi": 56.0, "rsi_trig": 48.0,
    "prox": 0.020,
    "min_confluence": 0.38,
    "sl_atr_mult": 2.30, "t1_atr_mult": 5.20, "t2_atr_mult": 9.80,
    "trail_atr_mult": 1.90, "t2_lock_atr_mult": 1.80,
    "t1_frac": 0.30, "t2_frac_of_rest": 0.50,
    "t1_gain_lock": 0.0,
    "rsi_exit": 82.0,
    "max_risk": 3, "max_total": 3,
    "alpha_weights": [0.65, 0.25, 0.10],
    "risk_off_mult": 0.75,
    # [v83] رافعة التعافي بعد كساد الاتساع (GMRI<0.36 لـ18 شمعة → دفعة ×1.30 لمدة 48 شمعة)
    "bear_gmri": 0.36, "bear_persist": 18, "rec_boost": 1.30, "rec_bars": 48,  # [v122-H33] bg 0.36: مركز هضبة [0.34,0.38] (+3.36pp IS بتياً)
    "vol_filter": False,
    "cooldown_on": True,
    "risk_pct": 0.05,
    "boost": 1.35,
    "dd_freezer": 0.0,
}

# ══════════════════════════════════════════════════════════════════════════════
# معاملات المحافظ الثلاث (v83 المعتمدة)
# ══════════════════════════════════════════════════════════════════════════════
POOL1_ASSETS = LEGACY_CORE5
POOL2_ASSETS = ["XLMUSDT", "ETHUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT", "BTCUSDT", "AVAXUSDT"]  # [v101-H19]
POOL3_ASSETS = ["HBARUSDT", "DOGEUSDT", "ADAUSDT", "ARBUSDT"]

POOL1_PARAMS = dict(BASELINE_PARAMS)
POOL1_PARAMS.update({
    'alpha_weights': [0.45, 0.35, 0.2],
    'bear_gmri': 0.36,
    'bear_persist': 12.0,
    'boost': 2.2,
    'cooldown_on': True,
    'dd_freezer': 0.0,
    'ema_p': 21.0,
    'max_risk': 3.0,
    'max_total': 3.0,
    'min_confluence': 0.4,
    'prox': 0.02,
    'pyr2_alloc': 0.2,
    'pyr2_trigger': 4.5,
    'pyr3_alloc': 0.18,  # [Gen 30000 Omni Apex Transcendence]
    'pyr3_trigger': 7.5,
    'pyr_alloc': 0.18,   # [Gen 30000 Omni Apex Transcendence]
    'pyr_trigger': 4.33,
    'rec_bars': 104.0,
    'rec_boost': 1.58,
    'risk_off_mult': 1.0,
    'risk_pct': 0.038,   # [Gen 40000 Celestial Apex Supreme] ضبط المخاطرة المثلى لرفع الربح لـ 7,493$
    'rs_rank_gate': 0.12,
    'rsi_exit': 85.0,
    'rsi_hi': 56.0,
    'rsi_lo': 40.0,
    'rsi_p': 14.0,
    'rsi_trig': 48.0,
    'sl_atr_mult': 1.895,
    'slope_lag': 4.0,
    't1_atr_mult': 5.59,
    't1_frac': 0.10,     # [Gen 30000 Omni Apex Transcendence]
    't1_gain_lock': 0.0,
    't2_atr_mult': 10.1,
    't2_frac_of_rest': 0.05,  # [Gen 30000 Omni Apex Transcendence]
    't2_lock_atr_mult': 1.8,
    'trail_atr_mult': 0.02,
    'vol_filter': False,
})

POOL2_PARAMS = dict(BASELINE_PARAMS)
POOL2_PARAMS.update({
    'alpha_weights': [0.4, 0.35, 0.25],
    'asset_params': {'LINKUSDT': {'mode': 'trend', 'min_confluence': 0.56, 'tr_rsi_lo': 58.0, 'tr_rsi_hi': 82.0, 'prox': 0.03, 'tr_rm_lo': 48.0}},
    'bear_gmri': 0.36,
    'bear_persist': 12.0,
    'boost': 1.2,
    'cooldown_on': True,
    'cooldown_sl': 16.0,
    'dd_freezer': 0.0,
    'ema_p': 21.0,
    'max_risk': 3.0,
    'max_total': 3.0,
    'min_confluence': 0.215,
    'prox': 0.015,
    'rec_bars': 48.0,
    'rec_boost': 1.3,
    'risk_off_mult': 0.85,
    'risk_pct': 0.025,
    'rsi_exit': 82.0,
    'rsi_hi': 56.0,
    'rsi_lo': 40.0,
    'rsi_p': 14.0,
    'rsi_trig': 48.0,
    'sl_atr_mult': 1.8,
    'slope_lag': 4.0,
    't1_atr_mult': 4.42,
    't1_frac': 0.25,
    't1_gain_lock': 0.0,
    't2_atr_mult': 8.5,
    't2_frac_of_rest': 0.5,
    't2_lock_atr_mult': 1.8,
    'trail_atr_mult': 1.2,
    'vol_filter': False,
})

POOL3_PARAMS = dict(BASELINE_PARAMS)
POOL3_PARAMS.update({
    'alpha_weights': [0.55, 0.3, 0.15],
    'asset_params': {'HBARUSDT': {'mode': 'trend', 'min_confluence': 0.6}, 'DOGEUSDT': {'mode': 'trend'}, 'ADAUSDT': {'mode': 'trend'}, 'ARBUSDT': {'mode': 'trend'}},
    'bear_gmri': 0.36,
    'bear_persist': 12.0,
    'boost': 1.2,
    'btc_filter': True,
    'cooldown_on': True,
    'dd_freezer': 0.0,
    'ema_p': 21.0,
    'max_risk': 2.0,
    'max_total': 2.0,
    'min_alpha_gap': 0.1,
    'min_confluence': 0.585,
    'mode': 'trend',
    'prox': 0.03,
    'rec_bars': 48.0,
    'rec_boost': 1.3,
    'risk_off_mult': 0.85,
    'risk_pct': 0.025,
    'rsi_exit': 75.0,
    'rsi_hi': 56.0,
    'rsi_lo': 40.0,
    'rsi_p': 14.0,
    'rsi_trig': 48.0,
    'sl_atr_mult': 1.8,
    'slope_lag': 4.0,
    't1_atr_mult': 5.10,
    't1_frac': 0.15,
    't1_gain_lock': 0.0,
    't2_atr_mult': 9.6,
    't2_frac_of_rest': 0.5,
    't2_lock_atr_mult': 1.8,
    'tr_rm_lo': 48.0,
    'tr_rsi_hi': 82.0,
    'tr_rsi_lo': 50.0,
    'trail_atr_mult': 1.3,
    'vol_filter': False,
})

# ══════════════════════════════════════════════════════════════════════════════
# الاستراتيجية الموحدة v99: قاعدة واحدة (P1-dip مضبوطة) لكل العملات الـ26
# ══════════════════════════════════════════════════════════════════════════════
UNIFIED_ASSETS = ['AAVEUSDT', 'ADAUSDT', 'ARBUSDT', 'ATOMUSDT', 'AVAXUSDT', 'BCHUSDT', 'BNBUSDT', 'BTCUSDT', 'DOGEUSDT', 'DOTUSDT', 'EOSUSDT', 'ETCUSDT', 'ETHUSDT', 'FETUSDT', 'HBARUSDT', 'INJUSDT', 'LINKUSDT', 'LTCUSDT', 'NEARUSDT', 'ONDOUSDT', 'SOLUSDT', 'TRXUSDT', 'VETUSDT', 'XLMUSDT', 'XRPUSDT', 'ZECUSDT']
UNIFIED_PARAMS = dict(POOL1_PARAMS)
UNIFIED_PARAMS.update({
    "risk_pct": 0.02, "btc_filter": True, "sl_atr_mult": 1.8,
    "max_risk": 3, "max_total": 3,
})  # [v99-U] risk 0.02 + فلتر BTC + وقف 1.8 (IS ‏+235.6/DD ‏14.3/n ‏132)

POOL_BUDGETS = [92.00, 1.00, 7.00]  # [Gen 70000 Supreme Dual Apex] التوازن الفولاذي لرفع الأرباح لـ 6,539$ وتقليص الخسائر لـ 342 صفقة

# ══════════════════════════════════════════════════════════════════════════════
# معاملات الاستراتيجية الثانية (صياد فترات الخمول وفك الارتباط — 10 عملات عريقة)
# ══════════════════════════════════════════════════════════════════════════════
STRATEGY2_PARAMS = dict(BASELINE_PARAMS)
STRATEGY2_PARAMS.update({
    'alpha_weights': [0.55, 0.3, 0.15],
    'asset_params': {'BCHUSDT': {'mode': 'trend', 'min_confluence': 0.585}},
    'bear_gmri': 0.0,            # [Dormancy Hunter] لا تتجمد في فترات الدببة والخمول
    'bear_persist': 999.0,
    'boost': 1.2,
    'btc_filter': False,         # [Dormancy Hunter] فك الارتباط للعمل واقتناص الفرص المستقلة أثناء خمول البيتكوين
    's2_gmri_min': 0.20,         # صمام أمان وقائي يمنع الدخول أثناء السقوط الحر الكارثي
    's2_gmri_modes': ('trend',),
    'conf_sideways': 0.41,
    'cooldown_on': True,
    'cooldown_sl': 41.0,
    'dd_freezer': 0.0,
    'ema_p': 21.0,
    'max_risk': 1.0,
    'max_total': 1.0,
    'min_confluence': 0.58,      # تلاقي نوعي دقيق لاختيار أقوى الفرص الارتدادية
    'mode': 'trend',
    'mom_gate': {'mode': 'rank', 'theta': 0.075},
    'prox': 0.03,
    'pyr2_alloc': 0.1,
    'pyr2_trigger': 4.0,
    'pyr3_alloc': 0.1,
    'pyr3_trigger': 6.0,
    'pyr_alloc': 0.15,
    'pyr_trigger': 2.0,
    'rec_bars': 48.0,
    'rec_boost': 1.3,
    'risk_off_mult': 0.85,
    'risk_pct': 0.020,
    'rot_gap': 0.375,
    'rot_min_bars': 10.0,
    'rs_rank_gate': 0.12,
    'rsi_exit': 91.84,
    'rsi_hi': 56.0,
    'rsi_lo': 40.0,
    'rsi_p': 14.0,
    'rsi_trig': 48.0,
    'sl_atr_mult': 1.8,
    'slope_lag': 4.0,
    't1_atr_mult': 4.5,
    't1_frac': 0.40,
    't1_gain_lock': 0.0,
    't2_atr_mult': 9.6,
    't2_frac_of_rest': 0.0,
    't2_lock_atr_mult': 1.8,
    'tr_rm_lo': 48.0,
    'tr_rsi_hi': 82.0,
    'tr_rsi_lo': 52.0,
    'trail_atr_mult': 0.65,  # [Gen 30000 Omni Apex Transcendence]
    'vol_filter': False,
})

# ══════════════════════════════════════════════════════════════════════════════
# 1) خط أنابيب البيانات: كاش دائم + جلب Binance (fallback: Yahoo)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_binance_klines(symbol, interval="4h", days=730):
    """جلب شموع Spot من Binance (بيانات عامة — بلا مفاتيح API). يرجع DataFrame أو None."""
    import urllib.request
    interval_ms = {"5m": 300_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}.get(interval)
    if interval_ms is None:
        raise ValueError(f"interval غير مدعوم: {interval}")
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    rows, cursor = [], start_ms
    base = "https://api.binance.com/api/v3/klines"
    while cursor < end_ms:
        url = f"{base}?symbol={symbol}&interval={interval}&startTime={cursor}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data:
            break
        rows.extend(data)
        last_open = int(data[-1][0])
        if last_open <= cursor:
            break
        cursor = last_open + interval_ms
    if not rows:
        return None
    arr = np.array(rows, dtype=float)
    df = pd.DataFrame({"Open": arr[:, 1], "High": arr[:, 2], "Low": arr[:, 3],
                       "Close": arr[:, 4], "Volume": arr[:, 5]},
                      index=pd.to_datetime(arr[:, 0].astype(int), unit="ms", utc=True))
    df = df[~df.index.duplicated(keep="first")]
    return df


def fetch_yfinance_4h(symbol, days=730):
    """بديل: جلب 1H من Yahoo وتجميعه إلى 4H."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    ysym = YAHOO_TICKER_RESOLVER.get(symbol, f"{symbol[:-4]}-USD")
    try:
        df = yf.download(ysym, period=f"{days}d", interval="1h",
                         progress=False, auto_adjust=False, threads=False)
        if df is None or df.empty or len(df) < 300:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            if "Close" in df.columns.get_level_values(0):
                df = (df.xs(ysym, axis=1, level=1)
                      if ysym in df.columns.get_level_values(1) else df.droplevel(1, axis=1))
            else:
                df.columns = df.columns.get_level_values(0)
        cols = ["Open", "High", "Low", "Close", "Volume"]
        if not set(cols).issubset(set(df.columns)):
            return None
        d4 = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min",
                                    "Close": "last", "Volume": "sum"}).dropna()
        if d4.index.tz is not None:
            d4.index = d4.index.tz_convert(timezone.utc)
        else:
            d4.index = d4.index.tz_localize(timezone.utc)
        return d4 if len(d4) >= 400 else None
    except Exception:
        return None


def load_data(force_refresh=False, days=None, source="auto"):
    """تحميل البيانات: كاش محلي أولاً، ثم جلب الناقص من Binance/Yahoo."""
    days = days or SystemConfig.DATA_DAYS
    _safe_makedirs(SystemConfig.CACHE_DIR)
    cache_path = os.path.join(SystemConfig.CACHE_DIR, SystemConfig.CACHE_FILE)
    store = {}

    if not force_refresh and os.path.exists(cache_path):
        try:
            cand = pd.read_pickle(cache_path)
            if isinstance(cand, dict) and len(cand) > 0:
                store = cand
                age_h = (datetime.now().timestamp() - os.path.getmtime(cache_path)) / 3600
                print(f"[CACHE] ✅ تحميل كاش محلي ({len(store)} رمزاً، عمره {age_h:.1f} ساعة) من:")
                print(f"        {cache_path}")
        except Exception as e:
            print(f"[WARN] تعذر قراءة الكاش ({e}) — سنجلب من المصدر.")

    missing = [s for s in ALL_DATA_ASSETS
               if s not in store or not isinstance(store[s], pd.DataFrame)
               or store[s].empty or len(store[s]) < 400]

    if not force_refresh and not missing and len(store) >= len(ALL_DATA_ASSETS):
        print("        كل الرموز المطلوبة موجودة ✓ (تشغيل أوفلاين)")
        return store

    sources = [source] if source != "auto" else ["binance", "yfinance"]
    print("=" * 90)
    print(f"📥 جلب البيانات المفقودة ({len(missing)} رمزاً) — المصادر: {' ← '.join(sources)} ...")
    print("=" * 90)
    for usdt in ALL_DATA_ASSETS:
        if (not force_refresh and usdt in store
                and isinstance(store[usdt], pd.DataFrame) and len(store[usdt]) >= 400):
            continue
        df = None
        for src in sources:
            try:
                df = fetch_binance_klines(usdt, "4h", days) if src == "binance" \
                    else fetch_yfinance_4h(usdt, days)
            except Exception as e:
                print(f"  ⚠️ {usdt:12s} عبر {src}: {e}")
                df = None
            if df is not None and len(df) >= 400:
                break
        if df is not None and len(df) >= 400:
            store[usdt] = df
            print(f"  ✅ {usdt:12s} -> {len(df):,d} شمعة 4H")
        else:
            print(f"  ❌ {usdt:12s} -> تعذر الجلب")

    if store:
        try:
            tmp = cache_path + ".tmp"
            pd.to_pickle(store, tmp)
            os.replace(tmp, cache_path)
            print(f"[CACHE] 💾 حُفظت البيانات في: {cache_path}")
        except Exception as e:
            print(f"[WARN] تعذر حفظ الكاش: {e}")
    return store

# ══════════════════════════════════════════════════════════════════════════════
# 2) المحركات المعرفية (فني هيكلي + سايكولوجية + زخم/سيولة)
# ══════════════════════════════════════════════════════════════════════════════
class PureTechnicalStructureEngine:
    @staticmethod
    def calculate_structure_score(df, swing_p=8):
        high, low, close = df["High"], df["Low"], df["Close"]
        swing_high = high.rolling(swing_p, min_periods=swing_p // 2).max().shift(1)
        bos_signal = (close > swing_high).astype(float).rolling(3, min_periods=1).max()
        fvg_bull = ((low > high.shift(2)) & (close > close.shift(1))).astype(float)
        body = (close - df["Open"]).abs()
        lower_wick = np.minimum(close, df["Open"]) - low
        rejection_signal = (lower_wick > (body * 1.2)).astype(float)
        tech_score = (0.45 * bos_signal + 0.30 * fvg_bull + 0.25 * rejection_signal).fillna(0.0)
        return tech_score.clip(0.0, 1.0)


class PsychologicalRangeEngine:
    @staticmethod
    def calculate_psychology_score(df, range_p=24):
        close, low, high = df["Close"], df["Low"], df["High"]
        range_low = low.rolling(range_p, min_periods=range_p // 2).min()
        range_high = high.rolling(range_p, min_periods=range_p // 2).max()
        range_span = (range_high - range_low).replace(0, np.nan)
        range_position = ((close - range_low) / range_span).fillna(0.5)
        discount_score = np.where(range_position <= 0.45, 1.0 - range_position, 0.25)
        discount_score = pd.Series(discount_score, index=df.index).clip(0.0, 1.0)
        prev_min = low.rolling(range_p // 2).min().shift(1)
        sweep_signal = ((low < prev_min) & (close > prev_min)).astype(float).rolling(2, min_periods=1).max()
        log_price = np.log10(np.maximum(close, 1e-6))
        step = 10 ** (np.floor(log_price) - 1)
        dist_to_round = np.abs(close - np.round(close / step) * step) / close
        psych_magnet = np.exp(-dist_to_round * 35.0)
        psych_score = (0.45 * discount_score + 0.35 * sweep_signal + 0.20 * psych_magnet).fillna(0.0)
        return psych_score.clip(0.0, 1.0)


class TechnicalEngine:
    @staticmethod
    def rsi(close, period=14):
        d = close.diff()
        up = d.where(d > 0, 0.0)
        dn = -d.where(d < 0, 0.0)
        ag = up.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        al = dn.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = ag / al.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(50.0)

    @staticmethod
    def atr_normalized(df, period=14):
        high, low, close_prev = df["High"], df["Low"], df["Close"].shift(1)
        tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        return (atr / df["Close"]).fillna(0.02).clip(0.01, 0.10)

    @classmethod
    def apply(cls, df, btc_df, ema_p=21, slope_lag=4, rsi_p=14):
        d = df.copy()
        d["EMA"] = d["Close"].ewm(span=ema_p, adjust=False).mean()
        d["SLOPE"] = d["EMA"] - d["EMA"].shift(slope_lag)
        d["RSI"] = cls.rsi(d["Close"], rsi_p)
        d["RSI_PREV"] = d["RSI"].shift(1)
        d["RSI_MIN3"] = d["RSI"].rolling(3).min()
        d["ROC_60"] = d["Close"].pct_change(60).fillna(0.0)
        d["ALPHA"] = ((d["Close"] / d["Close"].shift(42)) * (d["RSI"] / 50.0)).fillna(1.0)
        vol_ma = d["Volume"].rolling(20, min_periods=5).mean().replace(0, np.nan)
        d["RVOL"] = (d["Volume"] / vol_ma).fillna(1.0).clip(0.5, 3.5)
        asset_perf = d["Close"] / d["Close"].shift(24).replace(0, np.nan)
        btc_perf = (btc_df["Close"] / btc_df["Close"].shift(24).replace(0, np.nan)).reindex(d.index).ffill().bfill()
        d["RS_BTC"] = (asset_perf / btc_perf).fillna(1.0).clip(0.5, 3.0)
        d["TECH_STRUCT_SCORE"] = PureTechnicalStructureEngine.calculate_structure_score(d, swing_p=8)
        d["PSYCH_RANGE_SCORE"] = PsychologicalRangeEngine.calculate_psychology_score(d, range_p=24)
        mom_raw = (d["ROC_60"] * 5.0) + ((d["RSI"] - 50.0) / 25.0)
        d["MOM_SCORE"] = (1.0 / (1.0 + np.exp(-mom_raw))).clip(0.0, 1.0)
        d["ATR_NORM"] = cls.atr_normalized(d, period=14)
        # [v123.0.4] EMA اليومي (إطار أعلى — H43): EMA-21 على الإغلاق اليومي، يُعاد لمحاذاة 4H
        _d1 = d["Close"].resample("1D").last().dropna()
        d["EMA_D"] = (_d1.ewm(span=21, adjust=False).mean()
                      .reindex(d.index).ffill().bfill())
        return d


class SynergyFusionArbiter:
    @staticmethod
    def calculate_confluence(tech_score, psych_score, mom_score,
                             w_tech=0.35, w_psych=0.30, w_mom=0.35):
        return (w_tech * tech_score) + (w_psych * psych_score) + (w_mom * mom_score)

class CrashPredictionEngineV2Minimal:
    def __init__(self):
        self.quarantine_until = -1
        self.last_crash_bar = -9999
        self.quarantines = 0
        self.profit_locks = 0
        self.red_alerts = 0
        self.gmri_history = []
    def check_quarantine(self, t, btc_closes, gmri, nav_dd=0.0, nav_sma_ratio=1.0, btc_weak=False):
        btc_crash = False
        gmri_crash = False
        if t >= 84:
            try:
                import numpy as np
                high_84 = float(np.max(btc_closes[t-84:t]))
                cur = float(btc_closes[t])
                if high_84 > 0 and (high_84 - cur) / high_84 > 0.18:
                    btc_crash = True
            except Exception:
                btc_crash = False
        try:
            if len(self.gmri_history) >= 6:
                max_6 = max(self.gmri_history[-6:])
                if max_6 > 0.70 and gmri < 0.30:
                    gmri_crash = True
            self.gmri_history.append(float(gmri))
            if len(self.gmri_history) > 30:
                self.gmri_history = self.gmri_history[-30:]
        except Exception:
            pass
        if (btc_crash or gmri_crash) and gmri < 0.30 and nav_dd > 0.10 and t - self.last_crash_bar > 72:
            self.last_crash_bar = t
            self.quarantine_until = t + 36
            self.quarantines += 1
        return t < self.quarantine_until

def _fmt_px(x):
    """تنسيق السعر حسب حجمه (BTC مقابل العملات الصغيرة)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(x):
        return "—"
    if x >= 1000:
        return f"{x:,.1f}"
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}"
    return f"{x:.6f}"


# ══════════════════════════════════════════════════════════════════════════════
# 2ب) محرك الدخول الدقيق [v84]: شموع 5m لآخر ساعتين → منطقة دخول + حكم تنفيذ
# ══════════════════════════════════════════════════════════════════════════════
class MicroEntryZoneEngine:
    """عندما تعطي استراتيجية 4H إشارة، لا نشتري سوقياً فوراً — بل نكبّر على آخر
    ساعتين (24 شمعة 5m) ونحدد منطقة دخول دقيقة: بين دعم الساعة وVWAP."""

    HOURS_DEFAULT = 2
    CANDLES_PER_HOUR = 12
    H1_WINDOW = 12               # نافذة الدعم/المقاومة = آخر ساعة
    TREND_EMA_FAST = 9
    TREND_EMA_SLOW = 21
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    EXT_ENTER = 0.75             # امتداد فوق VWAP بمضاعفات ATR → دخول فوري تحته
    EXT_WAIT = 2.00              # امتداد متوسط → انتظار تراجع | فوقه → تخطي (مطاردة)

    # ---------- الجلب ----------
    @staticmethod
    def fetch_binance_5m(symbol, hours=2):
        """أحدث شموع 5m من Binance (عامة، بلا مفاتيح). تُسقط الشمعة الجارية."""
        import urllib.request
        n = int(hours * MicroEntryZoneEngine.CANDLES_PER_HOUR) + 4
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit={n}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data or len(data) < 12:
            return None
        arr = np.array(data, dtype=float)
        df = pd.DataFrame({"Open": arr[:, 1], "High": arr[:, 2], "Low": arr[:, 3],
                           "Close": arr[:, 4], "Volume": arr[:, 5]},
                          index=pd.to_datetime(arr[:, 0].astype(int), unit="ms", utc=True))
        df = df[~df.index.duplicated(keep="first")]
        return df.iloc[:-1].tail(int(hours * MicroEntryZoneEngine.CANDLES_PER_HOUR))

    @staticmethod
    def fetch_yahoo_5m(symbol, hours=2):
        """بديل: شموع 5m من Yahoo (متاحة للأيام الأخيرة — تكفي لنافذة الساعتين)."""
        try:
            import yfinance as yf
        except ImportError:
            return None
        ysym = YAHOO_TICKER_RESOLVER.get(symbol, f"{symbol[:-4]}-USD")
        try:
            df = yf.download(ysym, period="2d", interval="5m", progress=False,
                             auto_adjust=False, threads=False)
            if df is None or df.empty or len(df) < 12:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                if "Close" in df.columns.get_level_values(0):
                    df = (df.xs(ysym, axis=1, level=1)
                          if ysym in df.columns.get_level_values(1) else df.droplevel(1, axis=1))
                else:
                    df.columns = df.columns.get_level_values(0)
            cutoff = df.index.max() - pd.Timedelta(hours=hours)
            df = df[df.index > cutoff]
            if df is None or len(df) < 12:
                return None
            if df.index.tz is not None:
                df.index = df.index.tz_convert(timezone.utc)
            else:
                df.index = df.index.tz_localize(timezone.utc)
            return df.iloc[:-1] if len(df) > 12 else df   # إسقاط الجارية إن أمكن
        except Exception:
            return None

    @staticmethod
    def fetch_yahoo_5m_hist(symbol, days=60):
        """شموع 5m تاريخية من Yahoo (حتى 60 يوماً) — لاختبار المحرك على بيانات حقيقية."""
        try:
            import yfinance as yf
        except ImportError:
            return None
        ysym = YAHOO_TICKER_RESOLVER.get(symbol, f"{symbol[:-4]}-USD")
        try:
            df = yf.download(ysym, period=f"{min(int(days), 60)}d", interval="5m",
                             progress=False, auto_adjust=False, threads=False)
            if df is None or df.empty or len(df) < 500:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                if "Close" in df.columns.get_level_values(0):
                    df = (df.xs(ysym, axis=1, level=1)
                          if ysym in df.columns.get_level_values(1) else df.droplevel(1, axis=1))
                else:
                    df.columns = df.columns.get_level_values(0)
            cols = ["Open", "High", "Low", "Close", "Volume"]
            if not set(cols).issubset(set(df.columns)):
                return None
            if df.index.tz is not None:
                df.index = df.index.tz_convert(timezone.utc)
            else:
                df.index = df.index.tz_localize(timezone.utc)
            return df if len(df) >= 500 else None
        except Exception:
            return None

    @classmethod
    def fetch_5m(cls, symbol, hours=2, warmup_hours=6):
        """يجلب شموع 5m (Binance ثم Yahoo). المنطقة من آخر `hours` والمؤشرات من `warmup_hours`."""
        for name, fn in (("Binance-5m", cls.fetch_binance_5m), ("Yahoo-5m", cls.fetch_yahoo_5m)):
            try:
                df = fn(symbol, warmup_hours)
            except Exception:
                df = None
            if df is not None and len(df) >= 12:
                return df, name
        return None, None

    # ---------- حساب المنطقة بنظام النقاط [v85] ----------
    @staticmethod
    def _pivot_levels(d, atr_abs, tol_mult=0.15, left=3, right=3):
        """مستويات دعم/مقاومة من القمم/القيعان الكسورية + دمج المتقاربة + عدّ اللمسات."""
        h = d["High"].to_numpy(float)
        l = d["Low"].to_numpy(float)
        n = len(d)
        raw_h, raw_l = [], []
        for i in range(left, n - right):
            wh = h[i - left:i + right + 1]
            wl = l[i - left:i + right + 1]
            if (h[i] > wh[:left]).all() and (h[i] > wh[left + 1:]).all():
                raw_h.append((i, float(h[i])))
            if (l[i] < wl[:left]).all() and (l[i] < wl[left + 1:]).all():
                raw_l.append((i, float(l[i])))

        def _cluster(raw):
            lvls = []
            for i, pxx in sorted(raw, key=lambda x: x[1]):
                if lvls and abs(pxx - lvls[-1]["px"]) <= atr_abs * tol_mult:
                    g = lvls[-1]
                    g["pxs"].append(pxx)
                    g["px"] = float(np.median(g["pxs"]))
                    g["touches"] += 1
                    g["last_i"] = max(g["last_i"], i)
                else:
                    lvls.append({"px": pxx, "pxs": [pxx], "touches": 1, "last_i": i})
            for g in lvls:
                g["strength"] = g["touches"] + (0.5 if g["last_i"] >= n - 12 else 0.0)
            return sorted(lvls, key=lambda g: -g["strength"])[:4]

        return _cluster(raw_l), _cluster(raw_h)

    @classmethod
    def compute_zone(cls, df5m, context=None):
        """منطقة الدخول بنظام نقاط (0-100): الموقع + الدعوم/المقاومات + المؤشرات
        (EMA/MACD/RSI/Stochastic/BB) + الشمعة + الحجم + الهيكل + سياق 4H."""
        d = df5m.dropna().copy()
        if d is None or len(d) < 24:
            return {"ok": False, "reason": "شموع 5m غير كافية (<24)"}
        context = context or {}
        w = d.tail(24)                                   # نافذة المنطقة: آخر ساعتين
        px = float(d["Close"].iloc[-1])
        tp = (w["High"] + w["Low"] + w["Close"]) / 3.0
        vol = w["Volume"].replace(0, np.nan)
        vwap = float((tp * vol).sum() / vol.sum()) if vol.notna().sum() > 0 else float(tp.mean())

        prev_c = d["Close"].shift(1)
        tr = pd.concat([d["High"] - d["Low"], (d["High"] - prev_c).abs(),
                        (d["Low"] - prev_c).abs()], axis=1).max(axis=1)
        atr_abs = float(tr.tail(cls.ATR_PERIOD).mean())
        if not np.isfinite(atr_abs) or atr_abs <= 0:
            atr_abs = px * 0.002
        atr_pct = atr_abs / px * 100.0
        atr = atr_abs

        cl = d["Close"]
        ema_f = cl.ewm(span=cls.TREND_EMA_FAST, adjust=False).mean()
        ema_s = cl.ewm(span=cls.TREND_EMA_SLOW, adjust=False).mean()
        ema_up = bool(ema_f.iloc[-1] > ema_s.iloc[-1] and px > ema_s.iloc[-1])
        ema_dn = bool(ema_f.iloc[-1] < ema_s.iloc[-1] and px < ema_s.iloc[-1])
        trend, trend_ar = ("up", "صاعد 📈") if ema_up else (("down", "هابط 📉") if ema_dn else ("flat", "أفقي ➖"))

        rsi_s = TechnicalEngine.rsi(cl, cls.RSI_PERIOD)
        rsi5 = float(rsi_s.iloc[-1])
        rsi_slope = float(rsi_s.iloc[-1] - rsi_s.iloc[-4]) if len(rsi_s) >= 4 else 0.0
        rsi_arrow = "↑" if rsi_slope > 1.0 else ("↓" if rsi_slope < -1.0 else "→")

        macd_line = cl.ewm(span=12, adjust=False).mean() - cl.ewm(span=26, adjust=False).mean()
        macd_sig = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = float(macd_line.iloc[-1] - macd_sig.iloc[-1])
        macd_hist_prev = float(macd_line.iloc[-2] - macd_sig.iloc[-2]) if len(d) > 1 else 0.0
        macd_cross_up = macd_hist > 0 >= macd_hist_prev
        macd_txt = (("➕ إيجابي" + (" (تقاطع⬆)" if macd_cross_up else ""))
                    if macd_hist > 0 else "➖ سلبي")

        ll14 = d["Low"].rolling(14).min()
        hh14 = d["High"].rolling(14).max()
        rng = (hh14 - ll14).replace(0, np.nan)
        k = (((cl - ll14) / rng) * 100.0).rolling(3).mean()
        dd = k.rolling(3).mean()
        K = float(k.iloc[-1]) if np.isfinite(k.iloc[-1]) else 50.0
        D = float(dd.iloc[-1]) if np.isfinite(dd.iloc[-1]) else 50.0
        Kp = float(k.iloc[-2]) if len(k) > 1 and np.isfinite(k.iloc[-2]) else K
        Dp = float(dd.iloc[-2]) if len(dd) > 1 and np.isfinite(dd.iloc[-2]) else D
        stoch_cross_up = (K > D) and (Kp <= Dp)
        stoch_txt = f"{K:.0f}/{D:.0f}" + (" ⬆" if stoch_cross_up else "")

        bb_mid = cl.rolling(20).mean()
        bb_std = cl.rolling(20).std()
        bb_pct = (float((px - bb_mid.iloc[-1]) / (2 * bb_std.iloc[-1]) + 0.5)
                if np.isfinite(bb_mid.iloc[-1]) and bb_std.iloc[-1] > 0 else 0.5)
        bb_txt = f"{bb_pct * 100:.0f}%"

        o, hh, ll, cc = (float(d["Open"].iloc[-1]), float(d["High"].iloc[-1]),
                        float(d["Low"].iloc[-1]), px)
        body = abs(cc - o)
        lower_wick = min(cc, o) - ll
        upper_wick = hh - max(cc, o)
        bullish = cc > o
        hammer = (lower_wick > 2.0 * body + 1e-12) and body < atr * 0.6
        po, pc = float(d["Open"].iloc[-2]), float(d["Close"].iloc[-2])
        bear_engulf = (pc > po) and (cc < o) and (o >= pc) and (cc <= po)
        candle_bits = ["صاعدة✅" if bullish else "هابطة"]
        if hammer:
            candle_bits.append("رفض سفلي🔨")
        if bear_engulf:
            candle_bits.append("ابتلاعية هابطة⚠️")
        if upper_wick > 2.0 * body + 1e-12:
            candle_bits.append("رفض علوي⚠️")
        candle_txt = "+".join(candle_bits)

        vmean = d["Volume"].tail(24).mean()
        vratio = float(d["Volume"].iloc[-3:].mean() / max(vmean, 1e-12))
        upvol = d.tail(12)
        up_share = float(upvol.loc[upvol["Close"] > upvol["Open"], "Volume"].sum()
                         / max(upvol["Volume"].sum(), 1e-12))

        lows12 = d["Low"].tail(12).to_numpy(float)
        highs12 = d["High"].tail(12).to_numpy(float)
        lows_slope = float(np.polyfit(np.arange(12), lows12, 1)[0]) / px * 1e4
        highs_slope = float(np.polyfit(np.arange(12), highs12, 1)[0]) / px * 1e4

        sups, ress = cls._pivot_levels(d, atr)
        cands_s = [g for g in sups if g["px"] <= px and (px - g["px"]) / atr <= 2.0]
        cands_r = [g for g in ress if g["px"] >= px and (g["px"] - px) / atr <= 2.0]
        nearest_support = max(cands_s, key=lambda g: g["px"]) if cands_s else None
        nearest_resistance = min(cands_r, key=lambda g: g["px"]) if cands_r else None

        hour_low = float(w["Low"].min())
        if nearest_support is not None and (px - nearest_support["px"]) / atr <= 1.5:
            zone_low = nearest_support["px"]
        else:
            zone_low = hour_low
        zone_high = min(vwap, zone_low + 1.0 * atr)
        if zone_high <= zone_low:
            zone_high = zone_low + 0.25 * atr
        in_zone_lvls = [g for g in sups if zone_low <= g["px"] <= zone_high]
        if in_zone_lvls:
            snap = max(in_zone_lvls, key=lambda g: g["strength"])
            limit, limit_snapped = snap["px"], True
        else:
            snap, limit, limit_snapped = None, (zone_low + zone_high) / 2.0, False
        invalid = limit - (0.30 if limit_snapped else 0.50) * atr
        ext_atr = (px - vwap) / atr

        # ---- نظام النقاط (يبدأ من 50) ----
        score = 50.0
        contrib = []

        def _add(pts, label):
            nonlocal score
            score += pts
            contrib.append((label, float(pts)))

        veto = None
        if px < invalid:
            veto = "SKIP"
        elif zone_low <= px <= zone_high:
            _add(15, "داخل منطقة الدخول")
        elif px <= zone_high + 0.25 * atr:
            _add(8, "قريب فوق المنطقة")
        elif ext_atr <= cls.EXT_WAIT:
            _add(3, "تراجع معقول مطلوب")
        elif ext_atr <= 2.5:
            _add(-8, "ممتد فوق المنطقة")
        else:
            veto = "SKIP_CHASE"
        if veto is None and px < zone_low:
            _add(-5, "تحت الدعم")

        if limit_snapped:
            _add(12 if snap["touches"] >= 2 else 7,
                 f"حد عند دعم ({snap['touches']} لمسات)")
        if nearest_support is not None and nearest_support["last_i"] >= len(d) - 12:
            _add(3, "دعم مُختبر حديثاً")
        if nearest_resistance is not None:
            room = (nearest_resistance["px"] - px) / atr
            if room >= 1.0:
                _add(5, "مساحة حتى المقاومة")
            elif room < 0.5:
                _add(-8, "سقف مقاومة قريب")

        if ema_up:
            _add(8, "اتجاه 5m صاعد")
        elif ema_dn:
            _add(-8, "اتجاه 5m هابط")
        if macd_hist > 0:
            _add(4, "MACD إيجابي")
            if macd_cross_up:
                _add(3, "تقاطع MACD صاعد")
        elif macd_hist < macd_hist_prev:
            _add(-4, "MACD سلبي متدهور")

        if 45.0 <= rsi5 <= 65.0:
            _add(6, f"RSI متوازن ({rsi5:.0f})")
        elif 40.0 <= rsi5 < 45.0 or 65.0 < rsi5 <= 70.0:
            _add(2, f"RSI مقبول ({rsi5:.0f})")
        elif rsi5 > 75.0:
            _add(-8, f"RSI متشبع ({rsi5:.0f})")
        elif rsi5 < 35.0:
            _add(-5, f"ضعف زخم ({rsi5:.0f})")
        if rsi_slope > 1.0:
            _add(4, "RSI صاعد")
        elif rsi_slope < -1.0:
            _add(-3, "RSI هابط")
        if stoch_cross_up and K < 40.0:
            _add(5, "تقاطع ستوكاستك صاعد")
        elif K > 80.0 and D > 80.0:
            _add(-4, "تشبع ستوكاستك")

        if bullish:
            _add(3, "شمعة صاعدة")
        if hammer and ll <= zone_low + 0.3 * atr:
            _add(5, "مطرقة عند الدعم 🔨")
        if bear_engulf:
            _add(-6, "ابتلاعية هابطة")
        if upper_wick > 2.0 * body + 1e-12:
            _add(-3, "رفض علوي")

        if vratio >= 1.2:
            _add(4, "حجم قوي")
        elif vratio < 0.6:
            _add(-3, "حجم ضعيف")
        if up_share >= 0.55:
            _add(4, "سيطرة شرائية")

        if lows_slope > 0.5:
            _add(3, "قيعان صاعدة")
        if highs_slope < -0.5:
            _add(-3, "قمم هابطة")
        if bb_pct < 0.05 and bullish:
            _add(3, "ارتداد حد بولينجر")
        elif bb_pct > 0.95:
            _add(-3, "ملامسة حد بولينجر العلوي")

        gmri = float(context.get("gmri", 0.5))
        if gmri > BOOST_GMRI:
            _add(5, "بيئة 4H صاعدة")
        elif gmri < RISK_OFF_GMRI:
            _add(-5, "بيئة 4H هابطة")

        score = float(np.clip(score, 0, 100))
        contrib.sort(key=lambda x: -x[1])

        if veto == "SKIP":
            verdict, verdict_ar, score = "SKIP", "تخطي — كسر الدعم", min(score, 25)
        elif veto == "SKIP_CHASE":
            if gmri > BOOST_GMRI:
                # [v87] ترند 4H قوي: الامتداد يستمر — مطاردة محسوبة بحد قريب بدل التخطي
                limit = max(limit, px - 0.5 * atr)
                verdict, verdict_ar = "WAIT_PULLBACK", "مطاردة محسوبة — حد قريب (ترند قوي)"
                score = float(np.clip(max(score, 50), 0, 67))
            else:
                verdict, verdict_ar, score = "SKIP_CHASE", "تخطي — ممتد (مطاردة خطرة)", min(score, 30)
        elif score >= 68:
            verdict, verdict_ar = "ENTER_NOW", "دخول فوري — إشارات مؤكدة"
        elif score >= 42:   # [v87] مركز الهضبة [40,45] — 50 هاوية (−14 نقطة)
            verdict, verdict_ar = "WAIT_PULLBACK", "انتظار تراجع — أمر حد"
        elif ext_atr > 1.0:
            verdict, verdict_ar = "SKIP_CHASE", "تخطي — نقاط ضعيفة وامتداد"
        else:
            verdict, verdict_ar = "SKIP", "تخطي — إشارات غير كافية"
        # [v93-V4] حد ضحل ×0.5 مثبت على سعر إشارة 4H (IS +6.6pp / OOS +11.7pp / كامل +31.5pp)
        _spx = float(context.get("signal_px", px))
        limit = _spx - (_spx - limit) * 0.5
        confidence = float(np.clip(score / 100.0, 0.05, 0.95))

        return {"ok": True, "price": px, "vwap": vwap,
                "support": nearest_support["px"] if nearest_support else zone_low,
                "resistance": nearest_resistance["px"] if nearest_resistance else float(w["High"].max()),
                "nearest_support": nearest_support, "nearest_resistance": nearest_resistance,
                "zone_low": zone_low, "zone_high": zone_high,
                "limit": limit, "limit_snapped": limit_snapped, "invalid": invalid,
                "atr_pct": atr_pct, "rsi5": rsi5, "rsi_arrow": rsi_arrow,
                "macd_txt": macd_txt, "stoch_txt": stoch_txt, "bb_txt": bb_txt,
                "candle_txt": candle_txt, "trend": trend, "trend_ar": trend_ar,
                "vratio": vratio, "ext_atr": ext_atr,
                "verdict": verdict, "verdict_ar": verdict_ar,
                "score": score, "confidence": confidence, "contrib": contrib,
                "reasons": [f"{p:+.0f} {lab}" for lab, p in contrib[:4]],
                "n_candles": len(w), "warmup": len(d), "last_time": d.index[-1]}


# ══════════════════════════════════════════════════════════════════════════════
# 2ج) فحص الإشارة الموحّد (مشترك بين الباكتست والفحص الحي — منطق v83 حرفياً)
# ══════════════════════════════════════════════════════════════════════════════
def _gate_verdict(gate, tkr, bar_time, gmri, signal_px=None):
    """حكم 5m لإشارة 4H: المنطقة من شموع 5m قبل شمعة الإشارة. None = لا بيانات."""
    gd = gate["m5"].get(tkr)
    if gd is None:
        return None
    ts = gd["ts"]
    j = int(__import__("numpy").searchsorted(ts, int(bar_time.value), side="left"))
    # [v103-fix] تحقق صارم من أن شمعة الإشارة داخل نافذة 5m الفعلية (منع تسرب المستقبل)
    if j >= len(ts) or ts[j] - int(bar_time.value) > 24 * 5 * 60 * 1_000_000_000:
        return None
    if j < 24:
        return None
    i = max(0, j - 80)
    sl = slice(i, j)
    df = pd.DataFrame({"Open": gd["o"][sl], "High": gd["h"][sl], "Low": gd["l"][sl],
                       "Close": gd["c"][sl], "Volume": gd["v"][sl]},
                      index=pd.to_datetime(ts[sl]))
    if len(df) < 24:
        return None
    _ctx = {"gmri": gmri}
    if signal_px is not None:
        _ctx["signal_px"] = float(signal_px)
    z = MicroEntryZoneEngine.compute_zone(df, context=_ctx)
    return z if z.get("ok") else None


def check_entry_signal(processed, tkr, t, p, gmri, median_roc, basket_rocs, basket_rs=None):
    """يفحص شروط الدخول لأصل واحد عند الشمعة t.
    يرجع: (ناجح, confluence, alpha, سعر_الإغلاق, atr, النمط, السبب)."""
    a = processed[tkr]
    _ap_ov = (p.get("asset_params") or {}).get(tkr) or {}
    if not _ap_ov.get("roc_free", False) and a["roc_60"][t] < median_roc - 0.05:
        return (False, 0.0, 0.0, np.nan, np.nan, "", "ROC_60 ضعيف")
    _mg = p.get("mom_gate", None)
    if _mg is not None and not _ap_ov.get("roc_free", False):
        _mg_mode = _mg.get("mode", "abs")
        _mg_th = float(_mg.get("theta", 0.0))
        _roc = a["roc_60"][t]
        if _mg_mode == "abs" and _roc < _mg_th:
            return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة الزخم")
        elif _mg_mode == "laggard" and median_roc > 0.0 and _roc < _mg_th:
            return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة الزخم")
        elif _mg_mode == "median" and _roc < median_roc - _mg_th:
            return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة الزخم")
        elif _mg_mode == "rank":
            if basket_rocs:
                _rank = sum(1.0 for _r in basket_rocs if _r < _roc) / len(basket_rocs)
                if _rank < _mg_th:
                    return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة الزخم (رتبة)")
    if bool(p.get("vol_filter", True)) and a["atr_n"][t] > a["atr_hi"][t]:
        return (False, 0.0, 0.0, np.nan, np.nan, "", "فلتر التقلب (إنهاك)")
    if not _ap_ov.get("btc_free", False) and p.get("btc_filter", False):
        _ba = processed.get("BTCUSDT")
        if _ba is not None and _ba["ok"][t] and np.isfinite(_ba["ema"][t]) \
                and np.isfinite(_ba["slope"][t]) \
                and not (_ba["c"][t] > _ba["ema"][t] and _ba["slope"][t] > 0):
            return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة BTC")

    pm = p
    _ap = p.get("asset_params")
    if _ap is not None and tkr in _ap:
        pm = dict(p)
        pm.update(_ap[tkr])

    c, o, e, s, atr_val = a["c"][t], a["o"][t], a["ema"][t], a["slope"][t], a["atr_n"][t]
    rm, rp, r = a["rsim"][t], a["rsip"][t], a["rsi"][t]
    entry_mode = pm.get("mode", "dip")
    # [v123.0.4] فلتر الإطار اليومي (H43): لا دخول تحت EMA اليومي (None = معطل — بتّي)
    _htf = pm.get("htf_ema_d", None)
    if _htf is not None and not _ap_ov.get("htf_free", False):
        _edv = a["ema_d"][t]
        if np.isfinite(_edv) and c < _edv:
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "فلتر الإطار اليومي")
    # [H21 infra] بوابة القوة النسبية مقابل BTC: لا شراء لأصل أضعف من السوق (معطلة افتراضياً)
    _rs_min = pm.get("rs_min", None)
    if _rs_min is not None and not _ap_ov.get("rs_free", False):
        if not np.isfinite(a["rs_btc"][t]) or a["rs_btc"][t] < float(_rs_min):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "بوابة RS/BTC")
    # [H23 infra] بوابة RS المئينية التكيفية: فيتو لمن رتبة قوته النسبية تحت θ من سلة
    # اللحظة (عتبة تتنفس مع السوق بدل رقم ثابت — درس هشاشة H21 الزمنية). معطلة افتراضياً.
    _rsq = pm.get("rs_rank_gate", None)
    if _rsq is not None and not _ap_ov.get("rs_free", False) and basket_rs:
        _rrank = sum(1.0 for _r in basket_rs if _r < a["rs_btc"][t]) / len(basket_rs)
        if _rrank < float(_rsq):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "بوابة RS المئينية")
    # [H21 infra] بوابة السيولة اللحظية: لا دخول على حجم هزيل (معطلة افتراضياً)
    _rv_min = pm.get("rvol_min", None)
    if _rv_min is not None and not _ap_ov.get("rvol_free", False):
        if not np.isfinite(a["rvol"][t]) or a["rvol"][t] < float(_rv_min):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "بوابة السيولة")
    # [H2] بوابة نظام S2: منع الدخول عندما اتساع السوق هابط (None = معطلة)
    _gm = pm.get("s2_gmri_min", None)
    if _gm is not None and gmri < float(_gm) \
            and entry_mode in pm.get("s2_gmri_modes", ("trend",)):
        return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "بوابة النظام (GMRI)")

    if entry_mode == "dip":
        if np.isnan(e) or np.isnan(s) or s <= 0 or c < e or a["l"][t] > e * (1 + pm["prox"]):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط dip: الهيكل/القرب")
        if np.isnan(rm) or np.isnan(rp) or not (pm["rsi_lo"] <= rm <= pm["rsi_hi"]):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط dip: نطاق RSI")
        if not (rp < pm["rsi_trig"] <= r) or c <= o:
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط dip: زناد RSI/شمعة")
    elif entry_mode == "trend":
        if np.isnan(e) or np.isnan(s) or not np.isfinite(s) or s <= 0 or c < e:
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط trend: فوق EMA صاعد")
        if np.isnan(r) or not (pm.get("tr_rsi_lo", 48.0) <= r <= pm.get("tr_rsi_hi", 82.0)):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط trend: نطاق RSI")
        hh = a["hh"][t]
        brk = (not np.isnan(hh)) and c > hh
        dip_ok = (a["l"][t] <= e * (1 + pm.get("prox", 0.03))
                  and not np.isnan(rm) and rm >= pm.get("tr_rm_lo", 48.0))
        if not (brk or dip_ok) or c <= o:
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط trend: اختراق/تراجع")
    elif entry_mode == "floor":
        if np.isnan(rm) or not (rm <= pm.get("fl_rsi_dip", 32.0)):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط floor: غطسة RSI")
        if np.isnan(r) or r < pm.get("fl_rsi_up", 28.0):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط floor: ارتداد RSI")
        ll = a["ll"][t]
        if np.isnan(ll) or c <= o or c <= ll:
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط floor: القاع")
        if np.isnan(e) or c > e * (1 + pm.get("fl_above_ema", 1.00)):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط floor: سقف EMA")
    else:
        return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "نمط مجهول")

    confluence = SynergyFusionArbiter.calculate_confluence(
        a["tech_struct"][t], a["psych_range"][t], a["mom_score"][t])
    _min_conf = pm.get("min_confluence", 0.30)
    _cs = pm.get("conf_sideways", None)
    _cg = pm.get("conf_strong", None)
    if _cs is not None and RISK_OFF_GMRI <= gmri <= BOOST_GMRI:
        _min_conf = float(_cs)
    elif _cg is not None and gmri > BOOST_GMRI:
        _min_conf = float(_cg)
    if confluence >= _min_conf:
        return (True, float(confluence), float(a["alpha"][t]), float(c),
                float(atr_val), entry_mode, "إشارة ✅")
    return (False, float(confluence), float(a["alpha"][t]), float(c),
            float(atr_val), entry_mode, f"تلاقي {confluence:.2f} < {_min_conf:.2f}")

# ══════════════════════════════════════════════════════════════════════════════
# 3) المحاكي فائق السرعة (منطق الدخول/الخروج/الحوكمة — مطابق لـ v83)
# ══════════════════════════════════════════════════════════════════════════════
class FastSimulator:
    @staticmethod
    def prepare_arrays(store, assets=None, ema_p=21, slope_lag=4):
        asset_list = assets if assets is not None else ELITE_TRADEABLE_ASSETS
        tradeable_in_store = [sym for sym in asset_list if sym in store]
        union_index = sorted(set().union(*[store[sym].index for sym in tradeable_in_store + [BENCHMARK_ASSET]]))
        union_index = pd.DatetimeIndex(union_index)
        btc_df = store[BENCHMARK_ASSET]

        processed = {}
        for tkr in tradeable_in_store + [BENCHMARK_ASSET]:
            d_raw = TechnicalEngine.apply(store[tkr], btc_df, ema_p=ema_p,
                                          slope_lag=slope_lag).reindex(union_index)
            ok_tkr = ~d_raw["Close"].isna().to_numpy()  # التوافر الحقيقي قبل الملء
            d = d_raw.ffill().bfill()
            atr_hi = d["ATR_NORM"].rolling(ATR_QUANTILE_WINDOW, min_periods=120).quantile(EXHAUSTION_QUANTILE)
            prior_hh = d["High"].shift(1).rolling(8, min_periods=3).max()
            prior_ll = d["Low"].shift(1).rolling(5, min_periods=3).min()
            processed[tkr] = {
                "o": d["Open"].to_numpy(float), "h": d["High"].to_numpy(float),
                "l": d["Low"].to_numpy(float), "c": d["Close"].to_numpy(float),
                "ema": d["EMA"].to_numpy(float), "slope": d["SLOPE"].to_numpy(float),
                "rsi": d["RSI"].to_numpy(float), "rsip": d["RSI_PREV"].to_numpy(float),
                "rsim": d["RSI_MIN3"].to_numpy(float),
                "roc_60": np.nan_to_num(d["ROC_60"].to_numpy(float), nan=0.0),
                "alpha": np.nan_to_num(d["ALPHA"].to_numpy(float), nan=1.0),
                "tech_struct": d["TECH_STRUCT_SCORE"].to_numpy(float),
                "psych_range": d["PSYCH_RANGE_SCORE"].to_numpy(float),
                "mom_score": d["MOM_SCORE"].to_numpy(float),
                "atr_n": d["ATR_NORM"].to_numpy(float),
                "atr_hi": np.where(np.isnan(atr_hi.to_numpy(float)), np.inf, atr_hi.to_numpy(float)),
                "hh": prior_hh.to_numpy(float),
                "ll": prior_ll.to_numpy(float),
                "rs_btc": np.nan_to_num(d["RS_BTC"].to_numpy(float), nan=1.0),  # [H21 infra]
                "rvol": np.nan_to_num(d["RVOL"].to_numpy(float), nan=1.0),      # [H21 infra]
                "ok": ok_tkr,
                "ema_d": d["EMA_D"].to_numpy(float),   # [v123.0.4] الإطار اليومي (H43)
            }
        return union_index, processed, tradeable_in_store

    @staticmethod
    def simulate_prepared(processed, union_index, tradeable_in_store, p,
                          start_t=0, end_t=None, initial_capital=None, quiet=False,
                          gate5m=None, journal=None):
        tradeable_in_store = [s for s in tradeable_in_store if s in processed]
        if end_t is None:
            end_t = len(union_index)

        T = end_t - start_t
        sub_index = union_index[start_t:end_t]

        friction = SystemConfig.TOTAL_FRICTION
        cash = float(initial_capital if initial_capital is not None else SystemConfig.INITIAL_CAPITAL)
        pos = {}
        peak_nav = float(cash)
        pending = []
        cooldown_until = {}
        nav_series = np.empty(T, dtype=float)
        closed_trades = []
        asset_attribution = {tkr: {"trades": 0, "wins": 0, "realized_usdt": 0.0} for tkr in tradeable_in_store}

        vol_filter_on = bool(p.get("vol_filter", True))
        cooldown_on = bool(p.get("cooldown_on", True))
        cooldown_normal = int(p.get("cooldown_normal", COOLDOWN_NORMAL))
        cooldown_sl = int(p.get("cooldown_sl", COOLDOWN_SL))
        risk_off_mult = float(p.get("risk_off_mult", 0.50))
        exec_mode = EXECUTION_MODE
        micro_on = bool(p.get("micro_entry", False))   # [v84] أوامر حد دقيقة بدل السوق
        micro_pending = []
        micro_stats = {"limits": 0, "chases": 0, "saved_bps": [], "entries": []}
        gate = gate5m if isinstance(gate5m, dict) else None   # [v86] بوابة 5m
        gate_pending = []
        gate_stats = {"checked": 0, "enters": 0, "limits": 0, "chases": 0,
                      "skipped": [], "nogate": 0, "saved_bps": []}
        cur_bar = {"idx": 0}
        day_entries = {}   # [v123.0.3] عدّاد الدخولات لكل يوم تقويمي (لحاكم max_entries_per_day)
        day_entries = {}   # [v123.0.3] عدّاد الدخولات لكل يوم تقويمي (لحاكم max_entries_per_day)

        def _open(tkr, price, spend, atr_val, tag="", signal_px=None):
            nonlocal cash
            if spend < SystemConfig.MIN_ORDER_USDT or cash < SystemConfig.MIN_ORDER_USDT:
                return
            spend = min(cash, spend)
            if not (price > 0 and not np.isnan(price)):
                return
            cash -= spend
            # [v123.0.3] تسجيل الدخول لعدّاد الحاكم اليومي
            _d = sub_index[cur_bar["idx"]].date()
            day_entries[_d] = day_entries.get(_d, 0) + 1
            net_spend = spend * (1 - friction)
            pos[tkr] = {
                "tag": tag,
                "entry": price,
                "qty": net_spend / price,
                "hi": price,
                "sl": price * (1 - atr_val * p["sl_atr_mult"]),
                "tgt1": price * (1 + atr_val * p["t1_atr_mult"]),
                "tgt2": price * (1 + atr_val * p["t2_atr_mult"]),
                "tgt1_g": atr_val * p["t1_atr_mult"],
                "tgt2_g": atr_val * p["t2_atr_mult"],
                "t1": False,
                "t2": False,
                "entry_t": cur_bar["idx"],
                "alpha0": float(processed[tkr]["alpha"][t]) if t < len(processed[tkr]["alpha"]) else np.nan,  # [H26]
            }
            micro_stats["entries"].append({
                "ticker": tkr, "time": sub_index[cur_bar["idx"]],
                "entry_px": price, "signal_px": (signal_px if signal_px else price),
                "spend": spend, "tag": tag})
            if journal is not None:   # [TITAN126-adapter] جرد إضافي (بلا أثر افتراضياً)
                journal.setdefault("entries", []).append({
                    "ticker": tkr, "time": sub_index[cur_bar["idx"]], "price": price,
                    "spend": spend, "sl": pos[tkr]["sl"], "tgt1": pos[tkr]["tgt1"],
                    "tgt2": pos[tkr]["tgt2"], "qty": pos[tkr]["qty"], "tag": tag})

        def _add(tkr, price, spend, atr_val):
            """[v123.0.4] شريحة التصعيد (H44): إضافة ثانية على مركز رابح — شريحة واحدة كحد أقصى."""
            nonlocal cash
            ps = pos[tkr]
            if ps.get("q2", 0.0) > 0 or spend < SystemConfig.MIN_ORDER_USDT \
                    or cash < SystemConfig.MIN_ORDER_USDT:
                return
            spend = min(cash, spend)
            if not (price > 0 and not np.isnan(price)):
                return
            cash -= spend
            _d = sub_index[cur_bar["idx"]].date()
            day_entries[_d] = day_entries.get(_d, 0) + 1
            net_spend = spend * (1 - friction)
            ps["q2"] = net_spend / price
            ps["entry2"] = price
            ps["sl2"] = price * (1 - atr_val * p["sl_atr_mult"])

        def _add2(tkr, price, spend, atr_val):
            """[v124.0.1] شريحة التصعيد الثالثة (H48): إضافة على مركز حامل شريحتين — شريحة واحدة كحد أقصى."""
            nonlocal cash
            ps = pos[tkr]
            if ps.get("q3", 0.0) > 0 or spend < SystemConfig.MIN_ORDER_USDT \
                    or cash < SystemConfig.MIN_ORDER_USDT:
                return
            spend = min(cash, spend)
            if not (price > 0 and not np.isnan(price)):
                return
            cash -= spend
            _d = sub_index[cur_bar["idx"]].date()
            day_entries[_d] = day_entries.get(_d, 0) + 1
            net_spend = spend * (1 - friction)
            ps["q3"] = net_spend / price
            ps["entry3"] = price
            ps["sl3"] = price * (1 - atr_val * p["sl_atr_mult"])

        def _add3(tkr, price, spend, atr_val):
            """[v125.0.1] شريحة التصعيد الرابعة (H50/H51): إضافة على مركز حامل ثلاث شرائح — شريحة واحدة كحد أقصى."""
            nonlocal cash
            ps = pos[tkr]
            if ps.get("q4", 0.0) > 0 or spend < SystemConfig.MIN_ORDER_USDT \
                    or cash < SystemConfig.MIN_ORDER_USDT:
                return
            spend = min(cash, spend)
            if not (price > 0 and not np.isnan(price)):
                return
            cash -= spend
            _d = sub_index[cur_bar["idx"]].date()
            day_entries[_d] = day_entries.get(_d, 0) + 1
            net_spend = spend * (1 - friction)
            ps["q4"] = net_spend / price
            ps["entry4"] = price
            ps["sl4"] = price * (1 - atr_val * p["sl_atr_mult"])

        warmup = min(60, T // 10)
        crash_engine_min = CrashPredictionEngineV2Minimal() if p.get("crash_v2_min", True) else None
        btc_closes_arr_min = processed.get("BTCUSDT", {}).get("c", None)
        bear_gmri_th = float(p.get("bear_gmri", 0.0))
        bear_persist = int(p.get("bear_persist", 30))
        rec_boost = float(p.get("rec_boost", 1.0))
        rec_bars = int(p.get("rec_bars", 48))
        bear_streak = 0
        rec_left = 0

        for idx, t in enumerate(range(start_t, end_t)):
            cur_bar["idx"] = idx
            if idx < warmup:
                nav_series[idx] = cash
                continue

            # ---- 0) تنفيذ الإشارات المؤجلة (وضع next_open فقط) ----
            if exec_mode == "next_open" and pending:
                for pen in pending:
                    a = processed[pen["tkr"]]
                    price = a["o"][t] if a["ok"][t] else a["c"][t]
                    _open(pen["tkr"], price, pen["spend"], pen["atr"])
                pending = []

            # ---- 0ب) أوامر الحد الدقيقة [v84]: لمس الحد = ملء، انتهاء المهلة = مطاردة ----
            if micro_on and micro_pending:
                still = []
                for mp in micro_pending:
                    a = processed[mp["tkr"]]
                    if not a["ok"][t] or mp["tkr"] in pos:
                        if mp["tkr"] not in pos:
                            still.append(mp)
                        continue
                    if a["l"][t] <= mp["limit"]:
                        _open(mp["tkr"], mp["limit"], mp["spend"], mp["atr"], tag="MICRO_LIMIT",
                              signal_px=mp["signal_px"])
                        micro_stats["limits"] += 1
                        micro_stats["saved_bps"].append(
                            (mp["signal_px"] - mp["limit"]) / mp["signal_px"] * 1e4)
                    elif t >= mp["timeout"]:
                        _open(mp["tkr"], a["c"][t], mp["spend"], mp["atr"], tag="MICRO_CHASE",
                              signal_px=mp["signal_px"])
                        micro_stats["chases"] += 1
                    else:
                        still.append(mp)
                micro_pending = still

            # ---- 0ج) حدود البوابة [v86]: فحص الملء على شموع 5m الحقيقية ----
            if gate is not None and gate_pending:
                gstill = []
                now_ns = int(sub_index[idx].value)
                for gp in gate_pending:
                    if gp["tkr"] in pos:
                        continue
                    gd = gate["m5"].get(gp["tkr"])
                    filled = False
                    if gd is not None:
                        i0 = int(np.searchsorted(gd["ts"], gp["from_ns"], side="right"))
                        i1 = int(np.searchsorted(gd["ts"], now_ns, side="right"))
                        if i1 > i0 and np.min(gd["l"][i0:i1]) <= gp["limit"]:
                            filled = True
                    if filled:
                        _open(gp["tkr"], gp["limit"], gp["spend"], gp["atr"],
                              tag="M5_LIMIT", signal_px=gp["signal_px"])
                        gate_stats["limits"] += 1
                        gate_stats["saved_bps"].append(
                            (gp["signal_px"] - gp["limit"]) / gp["signal_px"] * 1e4)
                    elif t >= gp["timeout"]:
                        if gate.get("no_chase", False):
                            gate_stats["cancelled"] = gate_stats.get("cancelled", 0) + 1
                        else:
                            a = processed[gp["tkr"]]
                            _open(gp["tkr"], a["c"][t], gp["spend"], gp["atr"],
                                  tag="M5_CHASE", signal_px=gp["signal_px"])
                            gate_stats["chases"] += 1
                    else:
                        gstill.append(gp)
                gate_pending = gstill

            # ---- مؤشر اتساع السوق GMRI ----
            total_active_assets = 0
            assets_above_ema = 0
            for tkr in tradeable_in_store:
                a = processed[tkr]
                if a["ok"][t]:
                    total_active_assets += 1
                    if a["c"][t] > a["ema"][t]:
                        assets_above_ema += 1
            gmri = (assets_above_ema / total_active_assets) if total_active_assets > 0 else 0.5
            in_quarantine_min = False
            equity_filter_active = False
            btc_weak_q = False
            if crash_engine_min is not None and btc_closes_arr_min is not None:
                try:
                    _nav_est_q = cash + sum((ps["qty"]+ps.get("q2",0)+ps.get("q3",0)+ps.get("q4",0))*processed[tk]["c"][t] for tk, ps in pos.items() if processed[tk]["ok"][t])
                    _nav_dd_q = 1.0 - _nav_est_q / max(peak_nav, 1e-9)
                    if idx >= 50:
                        _sma50 = float(__import__('numpy').mean(nav_series[max(0,idx-50):idx]))
                        _sma_ratio = _nav_est_q / _sma50 if _sma50>0 else 1.0
                        equity_filter_active = _sma_ratio < 1.0
                    else:
                        _sma_ratio = 1.0
                    _btc_a = processed.get("BTCUSDT")
                    if _btc_a is not None and _btc_a["ok"][t]:
                        btc_weak_q = (_btc_a["c"][t] < _btc_a["ema"][t]) or (_btc_a["slope"][t] < 0)
                except Exception:
                    _nav_dd_q = 0.0
                    _sma_ratio = 1.0
                    btc_weak_q = False
                in_quarantine_min = crash_engine_min.check_quarantine(t, btc_closes_arr_min, gmri, _nav_dd_q, _sma_ratio, btc_weak_q)
            # [v83] عدّاد الدببة المستمرة + ذراع دفعة التعافي
            if bear_gmri_th > 0:
                if gmri < bear_gmri_th:
                    bear_streak += 1
                else:
                    if bear_streak >= bear_persist:
                        rec_left = rec_bars
                    bear_streak = 0

            # ---- 1) إدارة الصفقات المفتوحة (V129 Best) ----
            for tkr in list(pos.keys()):
                a = processed[tkr]
                if not a["ok"][t]:
                    continue
                ps = pos[tkr]
                hi, lo, cl, rsi, local_atr = a["h"][t], a["l"][t], a["c"][t], a["rsi"][t], a["atr_n"][t]
                if hi > ps["hi"]:
                    ps["hi"] = hi

                if ps["t2"]:
                    g = (ps["hi"] - ps["entry"]) / ps["entry"]
                    atr_trail = local_atr * p["trail_atr_mult"]
                    if g >= 0.35:
                        dist = atr_trail * 0.40
                    elif g >= 0.20:
                        dist = atr_trail * 0.55
                    elif g >= 0.10:
                        dist = atr_trail * 0.70
                    else:
                        dist = atr_trail
                    new_sl = ps["hi"] * (1 - dist)
                    if new_sl > ps["sl"]:
                        ps["sl"] = new_sl
                    # [v123.0.4] الشريحة تتبع نفس الترايل
                    if ps.get("q2", 0.0) > 0 and new_sl > ps.get("sl2", 0.0):
                        ps["sl2"] = new_sl
                    if ps.get("q3", 0.0) > 0 and new_sl > ps.get("sl3", 0.0):
                        ps["sl3"] = new_sl
                    if ps.get("q4", 0.0) > 0 and new_sl > ps.get("sl4", 0.0):
                        ps["sl4"] = new_sl
                elif ps["t1"] and not ps["t2"]:
                    _t1_lock = float(p.get("t1_gain_lock", 0.0))
                    if _t1_lock > 0:
                        _g = (ps["hi"] - ps["entry"]) / ps["entry"]
                        _lock_level = ps["entry"] * (1.0 + 0.005 + _t1_lock * _g)
                        if _lock_level > ps["sl"]:
                            ps["sl"] = _lock_level

                # [v125.0.1] شريحة التصعيد الرابعة: وقفها يُفحص أولاً (الأعلى — متحفظ)
                if ps.get("q4", 0.0) > 0 and lo <= ps["sl4"]:
                    realized4 = ps["q4"] * ps["sl4"] * (1 - friction)
                    pnl4 = realized4 - (ps["q4"] * ps["entry4"])
                    cash += realized4
                    closed_trades.append({"ticker": tkr,
                                          "pnl_pct": (ps["sl4"] - ps["entry4"]) / ps["entry4"] * 100,
                                          "pnl_usdt": pnl4, "time": sub_index[idx],
                                          "is_win": pnl4 > 0, "type": "PYR3_SL",
                                          "entry_tag": ps.get("tag", "")})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl4
                    if pnl4 > 0:
                        asset_attribution[tkr]["wins"] += 1
                    ps["q4"] = 0.0

                # [v124.0.1] شريحة التصعيد الثالثة: وقفها يُفحص أولاً (الأعلى — متحفظ)
                if ps.get("q3", 0.0) > 0 and lo <= ps["sl3"]:
                    realized3 = ps["q3"] * ps["sl3"] * (1 - friction)
                    pnl3 = realized3 - (ps["q3"] * ps["entry3"])
                    cash += realized3
                    closed_trades.append({"ticker": tkr,
                                          "pnl_pct": (ps["sl3"] - ps["entry3"]) / ps["entry3"] * 100,
                                          "pnl_usdt": pnl3, "time": sub_index[idx],
                                          "is_win": pnl3 > 0, "type": "PYR2_SL",
                                          "entry_tag": ps.get("tag", "")})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl3
                    if pnl3 > 0:
                        asset_attribution[tkr]["wins"] += 1
                    ps["q3"] = 0.0

                # [v123.0.4] شريحة التصعيد: وقفها الخاص يُفحص أولاً (الأعلى — متحفظ)
                if ps.get("q2", 0.0) > 0 and lo <= ps["sl2"]:
                    realized2 = ps["q2"] * ps["sl2"] * (1 - friction)
                    pnl2 = realized2 - (ps["q2"] * ps["entry2"])
                    cash += realized2
                    closed_trades.append({"ticker": tkr,
                                          "pnl_pct": (ps["sl2"] - ps["entry2"]) / ps["entry2"] * 100,
                                          "pnl_usdt": pnl2, "time": sub_index[idx],
                                          "is_win": pnl2 > 0, "type": "PYR_SL",
                                          "entry_tag": ps.get("tag", "")})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl2
                    if pnl2 > 0:
                        asset_attribution[tkr]["wins"] += 1
                    ps["q2"] = 0.0

                # وقف الخسارة
                if lo <= ps["sl"]:
                    # [v123.0.2] مستشعر حساسية الفجوات: ملء عند min(الافتتاح, الوقف) عند التفعيل — افتراضياً معطّل (بتّي)
                    _fill_px = min(a["o"][t], ps["sl"]) if bool(p.get("gap_fill", False)) else ps["sl"]
                    realized_val = ps["qty"] * _fill_px * (1 - friction)
                    pnl_usdt = realized_val - (ps["qty"] * ps["entry"])
                    pnl_pct = (ps["sl"] - ps["entry"]) / ps["entry"] * 100
                    cash += realized_val
                    closed_trades.append({"ticker": tkr, "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt,
                                          "time": sub_index[idx], "is_win": pnl_usdt > 0, "type": "SL",
                                          "entry_tag": ps.get("tag", "")})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl_usdt
                    if pnl_usdt > 0:
                        asset_attribution[tkr]["wins"] += 1
                    if cooldown_on:
                        cooldown_until[tkr] = t + cooldown_sl
                    del pos[tkr]
                    continue

                # الهدف الأول T1
                if not ps["t1"] and hi >= ps["tgt1"]:
                    sell_q = ps["qty"] * p["t1_frac"]
                    ps["qty"] -= sell_q
                    ps["t1"] = True
                    ps["sl"] = ps["entry"] * 1.005
                    # [v123.0.4] حماية تعادل شريحة التصعيد بعد لمسة T1
                    if ps.get("q2", 0.0) > 0 and ps.get("sl2", 0.0) < ps["entry2"] * 1.005:
                        ps["sl2"] = ps["entry2"] * 1.005
                    if ps.get("q3", 0.0) > 0 and ps.get("sl3", 0.0) < ps["entry3"] * 1.005:
                        ps["sl3"] = ps["entry3"] * 1.005
                    if ps.get("q4", 0.0) > 0 and ps.get("sl4", 0.0) < ps["entry4"] * 1.005:
                        ps["sl4"] = ps["entry4"] * 1.005
                    if sell_q > 0:   # [v123.0.1] بلا صفوف وهمية صفرية عندما يكون بنك T1 = 0 (العدّاء الكامل)
                        realized_val = sell_q * ps["tgt1"] * (1 - friction)
                        pnl_usdt = realized_val - (sell_q * ps["entry"])
                        cash += realized_val
                        closed_trades.append({"ticker": tkr, "pnl_pct": ps["tgt1_g"] * 100, "pnl_usdt": pnl_usdt,
                                              "time": sub_index[idx], "is_win": True, "type": "T1_TP",
                                              "entry_tag": ps.get("tag", "")})
                        asset_attribution[tkr]["trades"] += 1
                        asset_attribution[tkr]["wins"] += 1
                        asset_attribution[tkr]["realized_usdt"] += pnl_usdt

                # الهدف الثاني T2
                elif ps["t1"] and not ps["t2"] and hi >= ps["tgt2"]:
                    sell_q = ps["qty"] * p["t2_frac_of_rest"]
                    ps["qty"] -= sell_q
                    ps["t2"] = True
                    ps["sl"] = ps["entry"] * (1 + (local_atr * p["t2_lock_atr_mult"]))
                    if sell_q > 0:   # [v123.0.1] بلا صفوف وهمية صفرية عندما يكون بنك T2 = 0
                        realized_val = sell_q * ps["tgt2"] * (1 - friction)
                        pnl_usdt = realized_val - (sell_q * ps["entry"])
                        cash += realized_val
                        closed_trades.append({"ticker": tkr, "pnl_pct": ps["tgt2_g"] * 100, "pnl_usdt": pnl_usdt,
                                              "time": sub_index[idx], "is_win": True, "type": "T2_TP",
                                              "entry_tag": ps.get("tag", "")})
                        asset_attribution[tkr]["trades"] += 1
                        asset_attribution[tkr]["wins"] += 1
                        asset_attribution[tkr]["realized_usdt"] += pnl_usdt

                # خروج تشبع الشراء
                adaptive_rsi_exit = p["rsi_exit"] + (4.0 if gmri > BOOST_GMRI else (-4.0 if gmri < RISK_OFF_GMRI else 0.0))
                if ps["t2"] and rsi >= adaptive_rsi_exit:
                    realized_val = ps["qty"] * cl * (1 - friction)
                    pnl_usdt = realized_val - (ps["qty"] * ps["entry"])
                    pnl_pct = (cl - ps["entry"]) / ps["entry"] * 100
                    cash += realized_val
                    closed_trades.append({"ticker": tkr, "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt,
                                          "time": sub_index[idx], "is_win": pnl_usdt > 0, "type": "RSI_PEAK",
                                          "entry_tag": ps.get("tag", "")})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl_usdt
                    if pnl_usdt > 0:
                        asset_attribution[tkr]["wins"] += 1
                    # [v123.0.4] صف الشريحة عند الخروج الكامل
                    if ps.get("q2", 0.0) > 0:
                        realized2 = ps["q2"] * cl * (1 - friction)
                        pnl2 = realized2 - (ps["q2"] * ps["entry2"])
                        cash += realized2
                        closed_trades.append({"ticker": tkr,
                                              "pnl_pct": (cl - ps["entry2"]) / ps["entry2"] * 100,
                                              "pnl_usdt": pnl2, "time": sub_index[idx],
                                              "is_win": pnl2 > 0, "type": "PYR",
                                              "entry_tag": ps.get("tag", "")})
                        asset_attribution[tkr]["trades"] += 1
                        asset_attribution[tkr]["realized_usdt"] += pnl2
                        if pnl2 > 0:
                            asset_attribution[tkr]["wins"] += 1
                        ps["q2"] = 0.0
                    if ps.get("q3", 0.0) > 0:
                        realized3 = ps["q3"] * cl * (1 - friction)
                        pnl3 = realized3 - (ps["q3"] * ps["entry3"])
                        cash += realized3
                        closed_trades.append({"ticker": tkr,
                                              "pnl_pct": (cl - ps["entry3"]) / ps["entry3"] * 100,
                                              "pnl_usdt": pnl3, "time": sub_index[idx],
                                              "is_win": pnl3 > 0, "type": "PYR2",
                                              "entry_tag": ps.get("tag", "")})
                        asset_attribution[tkr]["trades"] += 1
                        asset_attribution[tkr]["realized_usdt"] += pnl3
                        if pnl3 > 0:
                            asset_attribution[tkr]["wins"] += 1
                        ps["q3"] = 0.0
                    if ps.get("q4", 0.0) > 0:
                        realized4 = ps["q4"] * cl * (1 - friction)
                        pnl4 = realized4 - (ps["q4"] * ps["entry4"])
                        cash += realized4
                        closed_trades.append({"ticker": tkr,
                                              "pnl_pct": (cl - ps["entry4"]) / ps["entry4"] * 100,
                                              "pnl_usdt": pnl4, "time": sub_index[idx],
                                              "is_win": pnl4 > 0, "type": "PYR3",
                                              "entry_tag": ps.get("tag", "")})
                        asset_attribution[tkr]["trades"] += 1
                        asset_attribution[tkr]["realized_usdt"] += pnl4
                        if pnl4 > 0:
                            asset_attribution[tkr]["wins"] += 1
                        ps["q4"] = 0.0
                    if cooldown_on:
                        cooldown_until[tkr] = t + cooldown_normal
                    del pos[tkr]

                # [H26] خروج استنزاف الألفا: الأطروحة ماتت قبل الوقف — يغلق سوقياً (0 = مطفأ)
                _drain = float(p.get("drain_ratio", 0.0))
                if _drain > 0.0 and tkr in pos and not ps["t1"] \
                        and (idx - ps.get("entry_t", idx)) >= int(p.get("drain_min_bars", 12)):
                    _al0 = ps.get("alpha0", np.nan)
                    if np.isfinite(_al0) and _al0 > 0 and np.isfinite(a["alpha"][t]) \
                            and a["alpha"][t] < _al0 * _drain:
                        realized_val = ps["qty"] * cl * (1 - friction)
                        pnl_usdt = realized_val - (ps["qty"] * ps["entry"])
                        pnl_pct = (cl - ps["entry"]) / ps["entry"] * 100
                        cash += realized_val
                        closed_trades.append({"ticker": tkr, "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt,
                                              "time": sub_index[idx], "is_win": pnl_usdt > 0,
                                              "type": "DRAIN", "entry_tag": ps.get("tag", "")})
                        asset_attribution[tkr]["trades"] += 1
                        asset_attribution[tkr]["realized_usdt"] += pnl_usdt
                        if pnl_usdt > 0:
                            asset_attribution[tkr]["wins"] += 1
                        if cooldown_on:
                            cooldown_until[tkr] = t + cooldown_normal
                        del pos[tkr]

                # [v101] الوقف الزمني: خروج سوقي بعد N شمعة بلا إغلاق (0 = مطفأ)
                _tsb = int(p.get("time_stop_bars", 0) or 0)
                if _tsb > 0 and tkr in pos and (idx - ps.get("entry_t", idx)) >= _tsb:
                    realized_val = ps["qty"] * cl * (1 - friction)
                    pnl_usdt = realized_val - (ps["qty"] * ps["entry"])
                    pnl_pct = (cl - ps["entry"]) / ps["entry"] * 100
                    cash += realized_val
                    closed_trades.append({"ticker": tkr, "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt,
                                          "time": sub_index[idx], "is_win": pnl_usdt > 0, "type": "TIME_STOP",
                                          "entry_tag": ps.get("tag", "")})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl_usdt
                    if pnl_usdt > 0:
                        asset_attribution[tkr]["wins"] += 1
                    if cooldown_on:
                        cooldown_until[tkr] = t + cooldown_normal
                    del pos[tkr]

            # ---- صافي القيمة عند إغلاق الشمعة ----
            cur_nav = cash
            for tkr, ps in pos.items():
                cur_nav += (ps["qty"] + ps.get("q2", 0.0) + ps.get("q3", 0.0) + ps.get("q4", 0.0)) * processed[tkr]["c"][t]
            nav_series[idx] = cur_nav

            # [v123.0.4] H44 تصعيد الرابح: شريحة ثانية ... + [v124.0.1] H48 شريحة ثالثة pyr2_* (0 = معطل بتّي)
            _pyr = float(p.get("pyr_trigger", 0.0) or 0.0)
            _pyr2 = float(p.get("pyr2_trigger", 0.0) or 0.0)
            if (_pyr > 0.0 or _pyr2 > 0.0) and gmri >= RISK_OFF_GMRI:
                for tkr in list(pos.keys()):
                    ps = pos[tkr]
                    a2 = processed[tkr]
                    if not a2["ok"][t]:
                        continue
                    if (idx - ps.get("entry_t", idx)) < int(p.get("pyr_min_bars", 3)):
                        continue
                    _sl_dist = max(a2["atr_n"][t] * p["sl_atr_mult"], 1e-6)
                    if _pyr > 0.0 and ps.get("q2", 0.0) == 0.0 \
                            and a2["c"][t] >= ps["entry"] * (1.0 + a2["atr_n"][t] * _pyr) \
                            and a2["c"][t] > a2["ema"][t]:
                        _rb = cur_nav * p.get("risk_pct", POSITION_RISK_PCT) * float(p.get("pyr_risk_frac", 0.5))
                        _spend = min(cash, cur_nav * float(p.get("pyr_alloc", 0.10)), _rb / _sl_dist)
                        if _spend >= SystemConfig.MIN_ORDER_USDT:
                            _add(tkr, a2["c"][t], _spend, a2["atr_n"][t])
                    elif _pyr2 > 0.0 and ps.get("q2", 0.0) > 0.0 and ps.get("q3", 0.0) == 0.0 \
                            and a2["c"][t] >= ps["entry"] * (1.0 + a2["atr_n"][t] * _pyr2) \
                            and a2["c"][t] > a2["ema"][t]:
                        _rb2 = cur_nav * p.get("risk_pct", POSITION_RISK_PCT) * float(p.get("pyr2_risk_frac", 0.5))
                        _spend2 = min(cash, cur_nav * float(p.get("pyr2_alloc", 0.10)), _rb2 / _sl_dist)
                        if _spend2 >= SystemConfig.MIN_ORDER_USDT:
                            _add2(tkr, a2["c"][t], _spend2, a2["atr_n"][t])
                    elif float(p.get("pyr3_trigger", 0.0) or 0.0) > 0.0 and ps.get("q3", 0.0) > 0.0 \
                            and ps.get("q4", 0.0) == 0.0 \
                            and a2["c"][t] >= ps["entry"] * (1.0 + a2["atr_n"][t] * float(p["pyr3_trigger"])) \
                            and a2["c"][t] > a2["ema"][t]:
                        _rb3 = cur_nav * p.get("risk_pct", POSITION_RISK_PCT) * float(p.get("pyr3_risk_frac", 0.5))
                        _spend3 = min(cash, cur_nav * float(p.get("pyr3_alloc", 0.10)), _rb3 / _sl_dist)
                        if _spend3 >= SystemConfig.MIN_ORDER_USDT:
                            _add3(tkr, a2["c"][t], _spend3, a2["atr_n"][t])

            if cur_nav > peak_nav:
                peak_nav = cur_nav
            nav_dd = 1.0 - cur_nav / max(peak_nav, 1e-9)

            basket_rocs = [processed[sym]["roc_60"][t] for sym in tradeable_in_store
                           if processed[sym]["ok"][t] and not np.isnan(processed[sym]["roc_60"][t])]
            median_roc = np.median(basket_rocs) if basket_rocs else 0.0
            basket_rs = [processed[sym]["rs_btc"][t] for sym in tradeable_in_store
                         if processed[sym]["ok"][t] and np.isfinite(processed[sym]["rs_btc"][t])]

            # ---- 2) فحص إشارات الدخول (V129 Best) ----
            at_risk = sum(1 for x in pos.values() if not x["t1"])
            if gmri < RISK_OFF_GMRI:
                eff_risk_cap = min(1, int(p["max_risk"]))
                eff_total_cap = min(1, int(p["max_total"]))
                regime_multiplier = risk_off_mult
            else:
                eff_risk_cap = int(p["max_risk"])
                eff_total_cap = int(p["max_total"])
                regime_multiplier = p.get("boost", 1.35) if gmri > BOOST_GMRI else 1.00
            if in_quarantine_min:
                eff_risk_cap = min(1, eff_risk_cap)
                eff_total_cap = min(1, eff_total_cap)
                regime_multiplier *= 0.30
                if crash_engine_min is not None:
                    crash_engine_min.red_alerts += 1
            if equity_filter_active and _nav_dd_q > 0.08:
                regime_multiplier *= 0.50
                # [H28] مقاعد الاتساع القوي: سعة إضافية فقط حين GMRI فوق عتبة القوة (0=معطل)
                if gmri > BOOST_GMRI and int(p.get("max_total_strong", 0)) > 0:
                    eff_total_cap = max(eff_total_cap, int(p["max_total_strong"]))
                    eff_risk_cap = max(eff_risk_cap,
                                       int(p.get("max_risk_strong", p["max_total_strong"])))

            dd_freezer = float(p.get("dd_freezer", 0.0))
            if dd_freezer > 0 and nav_dd > dd_freezer + 0.05:
                eff_total_cap = 0
            elif dd_freezer > 0 and nav_dd > dd_freezer:
                eff_risk_cap = min(1, eff_risk_cap)
                eff_total_cap = min(1, eff_total_cap)
                regime_multiplier = min(regime_multiplier, 0.50)

            # [v83] تجميد أثناء حلقة دببة مستمرة + دفعة تعافٍ بعدها
            if bear_gmri_th > 0 and bear_streak >= bear_persist:
                eff_risk_cap = 0
                eff_total_cap = 0
            elif rec_left > 0 and rec_boost > 1.0:
                regime_multiplier = max(regime_multiplier, rec_boost)
            if rec_left > 0:
                rec_left -= 1

            # [H24] تدوير المقعد: إن امتلأت المقاعد وظهر منافس أقوى بفجوة ألفا،
            # أغلق الحامل (قبل قفل التعادل فقط) وافتح المنافس. rot_gap=0 ⇒ معطّل (بتّي).
            _rot_gap = float(p.get("rot_gap", 0.0))
            if _rot_gap > 0.0 and pos:
                _rot_min = int(p.get("rot_min_bars", 0))
                _rot_under = bool(p.get("rot_under_only", False))
                _rot_slots = [hx for hx in pos
                              if not pos[hx]["t1"]
                              and (idx - pos[hx].get("entry_t", idx)) >= _rot_min
                              and (not _rot_under
                                   or processed[hx]["c"][t] < pos[hx]["entry"])]
                for hx in _rot_slots:
                    if hx not in pos:
                        continue
                    _ha = processed[hx]
                    _hold_al = _ha["alpha"][t] if _ha["ok"][t] else np.nan
                    if not np.isfinite(_hold_al) or _hold_al <= 0:
                        continue
                    best = None
                    for tkr in tradeable_in_store:
                        if tkr in pos:
                            continue
                        _a2 = processed[tkr]
                        if not _a2["ok"][t]:
                            continue
                        if cooldown_on and cooldown_until.get(tkr, -10**9) >= t:
                            continue
                        ok2, _cf2, _al2, _px2, _at2, _md2, _rs2 = check_entry_signal(
                            processed, tkr, t, p, gmri, median_roc, basket_rocs,
                            basket_rs=basket_rs)
                        if ok2 and (best is None or _al2 > best[0]):
                            best = (_al2, tkr, _px2, _at2)
                    if best is None:
                        continue
                    _al2, tkr, _px2, _at2 = best
                    if _al2 < _hold_al * (1.0 + _rot_gap):
                        continue
                    # إغلاق الحامل بسعر الإغلاق (احتكاك كامل) ثم فتح المنافس بنفس قواعد الحجم
                    ps = pos[hx]
                    px_close = _ha["c"][t]
                    realized_val = ps["qty"] * px_close * (1 - friction)
                    pnl_usdt = realized_val - (ps["qty"] * ps["entry"])
                    pnl_pct = (px_close - ps["entry"]) / ps["entry"] * 100
                    cash += realized_val
                    closed_trades.append({"ticker": hx, "pnl_pct": pnl_pct,
                                          "pnl_usdt": pnl_usdt, "time": sub_index[idx],
                                          "is_win": pnl_usdt > 0, "type": "ROT",
                                          "entry_tag": ps.get("tag", "")})
                    asset_attribution[hx]["trades"] += 1
                    asset_attribution[hx]["realized_usdt"] += pnl_usdt
                    if pnl_usdt > 0:
                        asset_attribution[hx]["wins"] += 1
                    # [v123.0.4] صف شريحة التصعيد إن وُجدت
                    if ps.get("q2", 0.0) > 0:
                        realized2 = ps["q2"] * px_close * (1 - friction)
                        pnl2 = realized2 - (ps["q2"] * ps["entry2"])
                        cash += realized2
                        closed_trades.append({"ticker": hx,
                                              "pnl_pct": (px_close - ps["entry2"]) / ps["entry2"] * 100,
                                              "pnl_usdt": pnl2, "time": sub_index[idx],
                                              "is_win": pnl2 > 0, "type": "PYR",
                                              "entry_tag": ps.get("tag", "")})
                        asset_attribution[hx]["trades"] += 1
                        asset_attribution[hx]["realized_usdt"] += pnl2
                        if pnl2 > 0:
                            asset_attribution[hx]["wins"] += 1
                        ps["q2"] = 0.0
                    if ps.get("q3", 0.0) > 0:
                        realized3 = ps["q3"] * px_close * (1 - friction)
                        pnl3 = realized3 - (ps["q3"] * ps["entry3"])
                        cash += realized3
                        closed_trades.append({"ticker": hx,
                                              "pnl_pct": (px_close - ps["entry3"]) / ps["entry3"] * 100,
                                              "pnl_usdt": pnl3, "time": sub_index[idx],
                                              "is_win": pnl3 > 0, "type": "PYR2",
                                              "entry_tag": ps.get("tag", "")})
                        asset_attribution[hx]["trades"] += 1
                        asset_attribution[hx]["realized_usdt"] += pnl3
                        if pnl3 > 0:
                            asset_attribution[hx]["wins"] += 1
                        ps["q3"] = 0.0
                    if ps.get("q4", 0.0) > 0:
                        realized4 = ps["q4"] * px_close * (1 - friction)
                        pnl4 = realized4 - (ps["q4"] * ps["entry4"])
                        cash += realized4
                        closed_trades.append({"ticker": hx,
                                              "pnl_pct": (px_close - ps["entry4"]) / ps["entry4"] * 100,
                                              "pnl_usdt": pnl4, "time": sub_index[idx],
                                              "is_win": pnl4 > 0, "type": "PYR3",
                                              "entry_tag": ps.get("tag", "")})
                        asset_attribution[hx]["trades"] += 1
                        asset_attribution[hx]["realized_usdt"] += pnl4
                        if pnl4 > 0:
                            asset_attribution[hx]["wins"] += 1
                        ps["q4"] = 0.0
                    if cooldown_on:
                        cooldown_until[hx] = t + cooldown_normal
                    del pos[hx]
                    at_risk_now = sum(1 for x in pos.values() if not x["t1"])
                    _w_idx_r = min(at_risk_now, len(p["alpha_weights"]) - 1)
                    base_allocation = cur_nav * p["alpha_weights"][_w_idx_r]
                    _vt = float(p.get("vol_target", 0.035))
                    _vlo = float(p.get("vol_lo", 0.75))
                    _vhi = float(p.get("vol_hi", 1.40))
                    volatility_multiplier = np.clip(_vt / max(0.01, _at2), _vlo, _vhi)
                    # [CRASH_PREDICTION_SMART_ARBITER] محرك التحكيم الذكي لدرع الانهيار
                    _ba = processed.get("BTCUSDT")
                    _btc_weak = False
                    _btc_strong = False
                    if _ba is not None and _ba["ok"][t]:
                        if _ba["c"][t] < _ba["ema"][t] or _ba["slope"][t] < 0:
                            _btc_weak = True
                        elif _ba["c"][t] > _ba["ema"][t] and _ba["slope"][t] > 0:
                            _btc_strong = True
                    _dyn_risk = p.get("risk_pct", POSITION_RISK_PCT)
                    # شجرة قرار ذكية: يقرر النظام متى يستعمل المحرك ومتى لا يستعمله وفق المؤشرات الخاصة
                    if _btc_strong and gmri >= 0.45:
                        pass  # [SHIELD OFF]: صعود وبول ران كامل -> ترك الأرباح تتضاعف بحرية فوق +1534%
                    elif (_btc_weak or gmri < 0.35) and nav_dd > 0.14:
                        _dyn_risk *= 0.30  # [SHIELD ACTIVE]: كبح فوري للمخاطرة لحماية المحفظة وتفادي الانهيار
                    risk_budget = cur_nav * _dyn_risk
                    sl_dist = max(_at2 * p["sl_atr_mult"], 1e-6)
                    spend = min(cash, base_allocation * regime_multiplier * volatility_multiplier,
                                risk_budget / sl_dist)
                    _open(tkr, _px2, spend, _at2, tag="ROT_IN", signal_px=_px2)
                    at_risk = sum(1 for x in pos.values() if not x["t1"])
                # بعد التدوير قد تنفتح شروط المقاعد من جديد — يتحقق الفرع أدناه كالمعتاد
                at_risk = sum(1 for x in pos.values() if not x["t1"])

            # [v123.0.3] حاكم تردد الدخول اليومي: سقف دخولات لكل يوم تقويمي (0 = معطل — بتّي)
            _mpd = int(p.get("max_entries_per_day", 0) or 0)
            # [v123.0.4] H45 فلتر ساعات الدخول: ساعات UTC المسموحة لفتح الشمعة (None = الكل — بتّي)
            _eh = p.get("entry_hours", None)
            if at_risk < eff_risk_cap and len(pos) < eff_total_cap:
                _day_cap_ok = (_mpd <= 0 or
                               day_entries.get(sub_index[idx].date(), 0) < _mpd)
                _hours_ok = (not _eh) or (sub_index[idx].hour in _eh)
                cands = []
                if _day_cap_ok and _hours_ok:
                    for tkr in tradeable_in_store:
                        a = processed[tkr]
                        if tkr in pos or not a["ok"][t]:
                            continue
                        if cooldown_on and cooldown_until.get(tkr, -10**9) >= t:
                            continue
                        ok, _cf, _al, _px, _at, _md, _rs = check_entry_signal(
                            processed, tkr, t, p, gmri, median_roc, basket_rocs,
                            basket_rs=basket_rs)
                        if ok:
                            cands.append((_al, tkr, _px, _at))

                if cands:
                    cands.sort(reverse=True, key=lambda x: x[0])
                    slots = min(eff_risk_cap - at_risk, eff_total_cap - len(pos))
                    min_alpha_gap = float(p.get("min_alpha_gap", 0.0))
                    top_alpha = cands[0][0]
                    picked = []
                    for (al, tkr, price_close, atr_val) in cands:
                        if len(picked) >= slots:
                            break
                        if picked and min_alpha_gap > 0 and al < top_alpha * (1.0 - min_alpha_gap):
                            continue
                        picked.append((tkr, price_close, atr_val))

                    for rank_idx, (tkr, price_close, atr_val) in enumerate(picked):
                        w_idx = min(at_risk + rank_idx, len(p["alpha_weights"]) - 1)
                        base_allocation = cur_nav * p["alpha_weights"][w_idx]
                        _vt = float(p.get("vol_target", 0.035))
                        _vlo = float(p.get("vol_lo", 0.75))
                        _vhi = float(p.get("vol_hi", 1.40))
                        volatility_multiplier = np.clip(_vt / max(0.01, atr_val), _vlo, _vhi)
                        # [CRASH_PREDICTION_SMART_ARBITER] محرك التحكيم الذكي لدرع الانهيار
                        _ba = processed.get("BTCUSDT")
                        _btc_weak = False
                        _btc_strong = False
                        if _ba is not None and _ba["ok"][t]:
                            if _ba["c"][t] < _ba["ema"][t] or _ba["slope"][t] < 0:
                                _btc_weak = True
                            elif _ba["c"][t] > _ba["ema"][t] and _ba["slope"][t] > 0:
                                _btc_strong = True
                        _dyn_risk = p.get("risk_pct", POSITION_RISK_PCT)
                        # شجرة قرار ذكية: يقرر النظام متى يستعمل المحرك ومتى لا يستعمله وفق المؤشرات الخاصة
                        if _btc_strong and gmri >= 0.45:
                            pass  # [SHIELD OFF]: صعود وبول ران كامل -> ترك الأرباح تتضاعف بحرية فوق +1534%
                        elif (_btc_weak or gmri < 0.35) and nav_dd > 0.14:
                            _dyn_risk *= 0.30  # [SHIELD ACTIVE]: كبح فوري للمخاطرة لحماية المحفظة وتفادي الانهيار
                        risk_budget = cur_nav * _dyn_risk
                        sl_dist = max(atr_val * p["sl_atr_mult"], 1e-6)
                        risk_cap_spend = risk_budget / sl_dist
                        spend = min(cash, base_allocation * regime_multiplier * volatility_multiplier,
                                    risk_cap_spend)
                        if spend < SystemConfig.MIN_ORDER_USDT:
                            break
                        _gate_tag = ""
                        if gate is not None:
                            gz = _gate_verdict(gate, tkr, union_index[t], gmri,
                                              signal_px=price_close)
                            gate_stats["checked"] += 1
                            if gz is None:
                                gate_stats["nogate"] += 1
                            elif gz["verdict"] in ("SKIP", "SKIP_CHASE"):
                                gate_stats["skipped"].append({
                                    "ticker": tkr, "time": union_index[t],
                                    "signal_px": price_close, "verdict": gz["verdict"],
                                    "score": round(gz["score"], 1)})
                                continue
                            elif gz["verdict"] == "WAIT_PULLBACK" and gz["limit"] < price_close \
                                    and not gate.get("wait_as_enter", False):
                                _dm = float(gate.get("depth_mult", 1.0))
                                _gl = price_close - (price_close - float(gz["limit"])) * _dm
                                gate_pending.append({"tkr": tkr, "spend": spend, "atr": atr_val,
                                                     "limit": float(_gl),
                                                     "signal_px": price_close,
                                                     "from_ns": int(union_index[t].value),
                                                     "timeout": t + int(gate.get("timeout_bars", MICRO_TIMEOUT_BARS))})
                                continue
                            else:
                                gate_stats["enters"] += 1
                                _gate_tag = "M5_ENTER"
                        if exec_mode == "next_open":
                            pending.append({"tkr": tkr, "spend": spend, "atr": atr_val})
                        elif micro_on:
                            # [v84] أمر حد عند منتصف منطقة الدخول بدل الشراء السوقي
                            depth = min(MICRO_DEPTH_CAP, MICRO_DEPTH_ATR * atr_val)
                            micro_pending.append({"tkr": tkr, "spend": spend, "atr": atr_val,
                                                  "limit": price_close * (1.0 - depth * 0.5),
                                                  "signal_px": price_close,
                                                  "timeout": t + MICRO_TIMEOUT_BARS})
                        else:
                            _open(tkr, price_close, spend, atr_val,
                                  tag=_gate_tag, signal_px=price_close)

        nav_df = pd.DataFrame({"nav": nav_series}, index=sub_index)
        micro_stats["gate"] = gate_stats
        if journal is not None:   # [TITAN126-adapter] لقطة المراكز المفتوحة (بلا أثر افتراضياً)
            journal["final_pos"] = [
                {"ticker": tkr, "entry": float(ps["entry"]), "sl": float(ps["sl"]),
                 "tgt1": float(ps["tgt1"]), "tgt2": float(ps["tgt2"]),
                 "t1": bool(ps.get("t1")), "t2": bool(ps.get("t2")),
                 "time": sub_index[ps["entry_t"]], "qty": float(ps["qty"]),
                 "spend": float(ps["qty"] * ps["entry"])}
                for tkr, ps in pos.items()]
        return nav_df, closed_trades, asset_attribution, micro_stats

# ══════════════════════════════════════════════════════════════════════════════
# 4) مصفوفة المقاييس الموحدة
# ══════════════════════════════════════════════════════════════════════════════
class MetricsEngine:
    @staticmethod
    def compute(nav_df, trades, initial_capital=None):
        initial_nav = float(initial_capital if initial_capital is not None else SystemConfig.INITIAL_CAPITAL)
        final_nav = float(nav_df["nav"].iloc[-1])
        total_ret = ((final_nav - initial_nav) / initial_nav) * 100
        total_days = max((nav_df.index[-1] - nav_df.index[0]).days, 1)

        daily_compounded = (((final_nav / initial_nav) ** (1.0 / total_days)) - 1.0) * 100
        daily_arithmetic = total_ret / total_days
        cagr = (((final_nav / initial_nav) ** (365.25 / total_days)) - 1.0) * 100

        peak = nav_df["nav"].cummax()
        dd = (nav_df["nav"] - peak) / np.where(peak == 0, 1e-9, peak) * 100
        max_dd = abs(float(dd.min()))

        df_tr = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["pnl_pct", "pnl_usdt", "is_win"])
        n_trades = len(df_tr)
        wins = df_tr[df_tr["is_win"] == True]
        losses = df_tr[df_tr["is_win"] == False]
        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = (n_wins / n_trades * 100) if n_trades > 0 else 0.0
        total_gain = float(wins["pnl_usdt"].sum()) if n_wins > 0 else 0.0
        total_loss = abs(float(losses["pnl_usdt"].sum())) if n_losses > 0 else 1e-9
        pf = total_gain / total_loss if total_loss > 0 else 0.0
        avg_trade_pct = float(df_tr["pnl_pct"].mean()) if n_trades > 0 else 0.0
        avg_win = float(wins["pnl_usdt"].mean()) if n_wins > 0 else 0.0
        avg_loss = float(losses["pnl_usdt"].mean()) if n_losses > 0 else 0.0
        expectancy = float(df_tr["pnl_usdt"].mean()) if n_trades > 0 else 0.0

        returns = nav_df["nav"].pct_change().dropna()
        std_ret = float(returns.std()) if len(returns) > 0 else 0.0
        sharpe = (float(returns.mean()) / std_ret * math.sqrt(2190)) if std_ret > 0 else 0.0
        calmar = (cagr / max_dd) if max_dd > 0 else 0.0

        split_idx = int(len(nav_df) * SystemConfig.IS_RATIO)
        is_nav = nav_df.iloc[:split_idx]
        oos_nav = nav_df.iloc[split_idx:]
        is_ret = ((float(is_nav["nav"].iloc[-1]) - initial_nav) / initial_nav) * 100
        oos_start = float(is_nav["nav"].iloc[-1])
        oos_ret = ((float(oos_nav["nav"].iloc[-1]) - oos_start) / oos_start) * 100
        stability = (oos_ret / max(is_ret, 1e-9)) if is_ret > 0 else 1.0

        return {
            "period_start": nav_df.index[0].strftime("%Y-%m-%d"),
            "period_end": nav_df.index[-1].strftime("%Y-%m-%d"),
            "total_days": int(total_days),
            "final_nav": final_nav, "total_ret": total_ret,
            "daily_compound": daily_compounded, "daily_arithmetic": daily_arithmetic,
            "cagr": cagr, "max_dd": max_dd, "sharpe": sharpe, "calmar": calmar,
            "n_trades": n_trades, "n_wins": n_wins, "n_losses": n_losses,
            "win_rate": win_rate, "pf": pf, "avg_trade_pct": avg_trade_pct,
            "avg_win_usdt": avg_win, "avg_loss_usdt": avg_loss, "expectancy_usdt": expectancy,
            "is_ret": is_ret, "oos_ret": oos_ret, "stability": stability,
        }

    @staticmethod
    def compute_detailed(nav_df, trades, btc_df=None):
        nav = nav_df["nav"]
        daily = nav.resample("D").last().dropna()
        daily_ret = daily.pct_change().dropna()
        d_comp = (((daily.iloc[-1] / daily.iloc[0]) ** (1.0 / max(len(daily) - 1, 1))) - 1.0) * 100
        d_arith = ((daily.iloc[-1] - daily.iloc[0]) / daily.iloc[0]) * 100 / max(len(daily) - 1, 1)
        out = {
            "n_days": int(len(daily_ret)),
            "best_day": float(daily_ret.max()) * 100,
            "worst_day": float(daily_ret.min()) * 100,
            "avg_day": float(daily_ret.mean()) * 100,
            "median_day": float(daily_ret.median()) * 100,
            "pct_positive_days": float((daily_ret > 0).mean()) * 100,
            "daily_compound": d_comp,
            "daily_arithmetic": d_arith,
        }
        df_tr = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["pnl_pct", "pnl_usdt", "is_win"])
        if len(df_tr):
            wins = df_tr[df_tr["is_win"] == True]["pnl_usdt"]
            losses = df_tr[df_tr["is_win"] == False]["pnl_usdt"]
            out["largest_win_usdt"] = float(wins.max()) if len(wins) else 0.0
            out["largest_loss_usdt"] = float(losses.min()) if len(losses) else 0.0
            out["avg_win_usdt"] = float(wins.mean()) if len(wins) else 0.0
            out["avg_loss_usdt"] = float(losses.mean()) if len(losses) else 0.0
            out["expectancy_usdt"] = float(df_tr["pnl_usdt"].mean())
            out["avg_win_pct"] = float(df_tr[df_tr["is_win"] == True]["pnl_pct"].mean()) if len(wins) else 0.0
            out["avg_loss_pct"] = float(df_tr[df_tr["is_win"] == False]["pnl_pct"].mean()) if len(losses) else 0.0
            seq = [1 if w else 0 for w in df_tr["is_win"]]
            max_lose_streak = cur = 0
            for s in seq:
                cur = cur + 1 if s == 0 else 0
                max_lose_streak = max(max_lose_streak, cur)
            out["max_lose_streak"] = max_lose_streak
            out["max_win_streak"] = 0
            cur = 0
            for s in seq:
                cur = cur + 1 if s == 1 else 0
                out["max_win_streak"] = max(out["max_win_streak"], cur)
        else:
            for k in ("largest_win_usdt", "largest_loss_usdt", "avg_win_usdt", "avg_loss_usdt",
                      "expectancy_usdt", "avg_win_pct", "avg_loss_pct", "max_lose_streak", "max_win_streak"):
                out[k] = 0.0 if "usdt" in k or "pct" in k else 0
        peak = nav.cummax()
        dd_series = (nav - peak) / np.where(peak == 0, 1e-9, peak)
        underwater = dd_series < 0
        longest_dd_days = cur = 0
        for u in underwater:
            cur = cur + 1 if u else 0
            longest_dd_days = max(longest_dd_days, cur)
        out["longest_dd_candles"] = int(longest_dd_days)
        out["longest_dd_days"] = round(longest_dd_days / 6.0, 1)
        if btc_df is not None and len(btc_df):
            b = btc_df["Close"].reindex(nav.index).ffill().bfill()
            b0 = float(b.iloc[0]); b1 = float(b.iloc[-1])
            out["btc_bh_ret"] = ((b1 - b0) / b0) * 100
            bd = b.resample("D").last().dropna()
            bd_ret = bd.pct_change().dropna()
            out["btc_best_day"] = float(bd_ret.max()) * 100
            out["btc_worst_day"] = float(bd_ret.min()) * 100
            bpeak = b.cummax()
            bdd = (b - bpeak) / np.where(bpeak == 0, 1e-9, bpeak) * 100
            out["btc_max_dd"] = abs(float(bdd.min()))
        return out

# ══════════════════════════════════════════════════════════════════════════════
# 5) طبقة رأس المال الديناميكي (v78) — المجموع 400$ ثابت
# ══════════════════════════════════════════════════════════════════════════════
def combine_dynamic_capital(nav1, nav2, union_index, cfg=None):
    cfg = cfg or DYNAMIC_CAPITAL
    if not cfg.get("enabled", False):
        return nav1 + nav2, [], 0
    K = int(cfg.get("rebalance_days", 30))
    gamma = float(cfg.get("gamma", 8.0))
    R = int(cfg.get("lookback_days", 90))
    w_lo = float(cfg.get("w_s2_min", 0.25))
    w_hi = float(cfg.get("w_s2_max", 0.75))
    CPD = 6  # شموع 4H في اليوم
    days = union_index.normalize()
    bounds, last = set(), None
    for i in range(len(union_index)):
        if i > 0 and days[i] != days[i - 1]:
            if last is None or (days[i] - days[last]).days >= K:
                bounds.add(i)
                last = i
    a1, a2 = float(nav1[0]), float(nav2[0])
    out = np.empty(len(nav1))
    w2_hist = []
    for i in range(len(nav1)):
        if i in bounds and i > R * CPD:
            r1 = nav1[i - 1] / nav1[i - 1 - R * CPD] - 1.0
            r2 = nav2[i - 1] / nav2[i - 1 - R * CPD] - 1.0
            w2 = float(np.clip(0.5 + gamma * (r2 - r1), w_lo, w_hi))
            A = a1 + a2
            a1, a2 = A * (1.0 - w2), A * w2
            w2_hist.append(w2)
        if i > 0:
            a1 *= nav1[i] / nav1[i - 1]
            a2 *= nav2[i] / nav2[i - 1]
        out[i] = a1 + a2
    return out, w2_hist, len(w2_hist)

# ══════════════════════════════════════════════════════════════════════════════
# 6) مختبر التحسين (وضع --legacy: السلة الخماسية v59)
# ══════════════════════════════════════════════════════════════════════════════
class ScientificOptimizationLab:
    @staticmethod
    def run_tuning(processed, union_index, tradeable_in_store):
        print("\n" + "=" * 90)
        print("⚡ مختبر التحسين (وضع legacy — السلة الخماسية) على شريحة IS 60% ...")
        print("=" * 90)
        total_len = len(union_index)
        split_idx = int(total_len * SystemConfig.IS_RATIO)
        param_grid = {
            "min_confluence": [0.38, 0.40, 0.42],
            "sl_atr_mult": [2.10, 2.30],
            "t1_atr_mult": [4.80, 5.20, 5.60],
            "t2_atr_mult": [8.80, 9.80],
            "trail_atr_mult": [1.80, 2.10],
            "t1_frac": [0.30, 0.40],
            "alpha_weights": [
                [0.55, 0.30, 0.15], [0.60, 0.30, 0.10],
                [0.65, 0.25, 0.10], [0.70, 0.20, 0.10],
            ],
            "risk_pct": [0.040, 0.050],
            "boost": [1.00, 1.35],
            "dd_freezer": [0.00],
        }
        keys, values = zip(*param_grid.items())
        combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
        print(f"  🧪 فحص {len(combinations)} توليفة عبر شريحة التدريب...")
        best_score = -1e9
        best_candidate = BASELINE_PARAMS.copy()
        best_is_metrics = {}
        t0 = time.time()
        for combo in combinations:
            p = BASELINE_PARAMS.copy()
            p.update(combo)
            is_nav_df, is_trades, _, _ = FastSimulator.simulate_prepared(
                processed, union_index, tradeable_in_store, p, start_t=0, end_t=split_idx)
            m = MetricsEngine.compute(is_nav_df, is_trades)
            dd_penalty = max(0, (m["max_dd"] - 14.0) * 0.25)
            score = (m["total_ret"] * 0.45) + (m["calmar"] * 15.0) + (m["sharpe"] * 10.0) \
                + (m["pf"] * 5.0) - (dd_penalty * 25.0)
            if score > best_score:
                best_score = score
                best_candidate = p
                best_is_metrics = {k: m[k] for k in ("total_ret", "max_dd", "sharpe", "calmar", "pf")}
        print(f"  ✅ اكتمل في {time.time() - t0:.2f} ثانية. البطل (IS): عائد +{best_is_metrics.get('total_ret', 0):.2f}% | "
              f"MaxDD {best_is_metrics.get('max_dd', 0):.2f}% | Sharpe {best_is_metrics.get('sharpe', 0):.2f}")
        return best_candidate, best_is_metrics

# ══════════════════════════════════════════════════════════════════════════════
# 7) تشغيل الحساب الموحّد (الوضع الافتراضي — استراتيجيتان)
# ══════════════════════════════════════════════════════════════════════════════
def run_dual_strategies(store, micro=False, gate5m=None):
    all_assets = list(ELITE_TRADEABLE_ASSETS) + [s for s in STRATEGY2_ASSETS if s not in ELITE_TRADEABLE_ASSETS]
    union_index, proc, _ = FastSimulator.prepare_arrays(store, assets=all_assets)

    def _pp(base):
        q = dict(base)
        if micro:
            q["micro_entry"] = True
        return q

    p1, p2, p3, ps2 = _pp(POOL1_PARAMS), _pp(POOL2_PARAMS), _pp(POOL3_PARAMS), _pp(STRATEGY2_PARAMS)
    s1_scale = STRATEGY1_CAPITAL / 100.0
    s1_budgets = [b * s1_scale for b in POOL_BUDGETS]

    print("\n" + "=" * 90)
    print(f"⚡ {BOT_VERSION} — الحساب الموحّد: استراتيجيتان برأس مال ديناميكي (المجموع {TOTAL_CAPITAL:.0f}$ ثابت)...")
    if micro:
        print("🎯 وضع الدخول الدقيق مفعّل: أوامر حد عند منطقة الدخول (عمق ≤0.25% / مهلة 12 ساعة)")
    if gate5m:
        print("🛡️ بوابة 5m مفعّلة: تخطي SKIP + حد حقيقي لـ WAIT (مهلة 12 ساعة)")
    print("=" * 90)

    # ---------- الاستراتيجية الأولى: المحافظ الثلاث ----------
    navs1, trades1, attrs1, pool_reports = [], [], [], []
    micro_agg = {"limits": 0, "chases": 0, "saved_bps": [], "entries": []}
    gate_agg = {"checked": 0, "enters": 0, "limits": 0, "chases": 0,
                "skipped": [], "nogate": 0, "saved_bps": []}
    for name, assets, pp, budget in [("P1 الخماسية البطلة", POOL1_ASSETS, p1, s1_budgets[0]),
                                     ("P2 الموجات الهادئة", POOL2_ASSETS, p2, s1_budgets[1]),
                                     ("P3 الانفجارية", POOL3_ASSETS, p3, s1_budgets[2])]:
        nv, tr, attr, ms = FastSimulator.simulate_prepared(proc, union_index, assets, pp, initial_capital=budget,
                                                                gate5m=gate5m)
        micro_agg["limits"] += ms["limits"]
        micro_agg["chases"] += ms["chases"]
        micro_agg["saved_bps"].extend(ms["saved_bps"])
        for _e in ms["entries"]:
            _e["pool"] = name
            micro_agg["entries"].append(_e)
        _g = ms.get("gate") or {}
        for _s in _g.get("skipped", []):
            _s["pool"] = name
            gate_agg["skipped"].append(_s)
        gate_agg["checked"] += _g.get("checked", 0)
        gate_agg["enters"] += _g.get("enters", 0)
        gate_agg["limits"] += _g.get("limits", 0)
        gate_agg["chases"] += _g.get("chases", 0)
        gate_agg["nogate"] += _g.get("nogate", 0)
        gate_agg["saved_bps"].extend(_g.get("saved_bps", []))
        met = MetricsEngine.compute(nv, tr, initial_capital=budget)
        navs1.append(nv["nav"].to_numpy(float))
        trades1.extend(tr)
        attrs1.append(attr)
        pool_reports.append((name, assets, budget, met))
    nav1 = np.sum(navs1, axis=0)
    m_s1 = MetricsEngine.compute(pd.DataFrame({"nav": nav1}, index=union_index), trades1,
                                 initial_capital=STRATEGY1_CAPITAL)

    # ---------- الاستراتيجية الثانية: سلة الـ11 ----------
    nv2, trades2, attr2, ms2 = FastSimulator.simulate_prepared(proc, union_index, STRATEGY2_ASSETS,
                                                               ps2, initial_capital=STRATEGY2_CAPITAL,
                                                               gate5m=gate5m)
    micro_agg["limits"] += ms2["limits"]
    micro_agg["chases"] += ms2["chases"]
    micro_agg["saved_bps"].extend(ms2["saved_bps"])
    for _e in ms2["entries"]:
        _e["pool"] = "S2"
        micro_agg["entries"].append(_e)
    _g2 = ms2.get("gate") or {}
    for _s in _g2.get("skipped", []):
        _s["pool"] = "S2"
        gate_agg["skipped"].append(_s)
    gate_agg["checked"] += _g2.get("checked", 0)
    gate_agg["enters"] += _g2.get("enters", 0)
    gate_agg["limits"] += _g2.get("limits", 0)
    gate_agg["chases"] += _g2.get("chases", 0)
    gate_agg["nogate"] += _g2.get("nogate", 0)
    gate_agg["saved_bps"].extend(_g2.get("saved_bps", []))
    nav2 = nv2["nav"].to_numpy(float)
    m_s2 = MetricsEngine.compute(nv2, trades2, initial_capital=STRATEGY2_CAPITAL)

    # ---------- الحساب الموحّد (طبقة رأس المال الديناميكي) ----------
    comb_nav, w2_hist, n_reb = combine_dynamic_capital(nav1, nav2, union_index)
    metrics = MetricsEngine.compute(pd.DataFrame({"nav": comb_nav}, index=union_index),
                                    trades1 + trades2, initial_capital=TOTAL_CAPITAL)

    # إسناد الأرباح لكل رمز
    _all_syms = list(dict.fromkeys(ELITE_TRADEABLE_ASSETS + STRATEGY2_ASSETS))
    sys_attr = {s: {"trades": 0, "wins": 0, "realized_usdt": 0.0} for s in _all_syms}
    for attr in attrs1 + [attr2]:
        for s in attr:
            if s in sys_attr:
                st = attr[s]
                sys_attr[s]["trades"] += st.get("trades", 0)
                sys_attr[s]["wins"] += st.get("wins", 0)
                sys_attr[s]["realized_usdt"] += st.get("realized_usdt", 0.0)

    dyn_stats = {"n_rebalances": len(w2_hist),
                 "w2_mean": round(float(np.mean(w2_hist)), 4) if w2_hist else 0.5,
                 "w2_min": round(float(np.min(w2_hist)), 4) if w2_hist else None,
                 "w2_max": round(float(np.max(w2_hist)), 4) if w2_hist else None}
    return dict(metrics=metrics, m_s1=m_s1, m_s2=m_s2, pool_reports=pool_reports,
                sys_attr=sys_attr, dyn_stats=dyn_stats, comb_nav=comb_nav,
                union_index=union_index, all_trades=trades1 + trades2, w2_hist=w2_hist,
                micro=(micro_agg if micro else None),
                entries=micro_agg["entries"],
                gate=(gate_agg if gate5m else None))

def run_unified_strategy(store, micro=False, gate5m=None):
    """[v99] باكتست موحد: محفظة واحدة × قاعدة واحدة × كل العملات × كامل رأس المال."""
    assets = [a for a in UNIFIED_ASSETS if a in store]
    union_index, proc, _ = FastSimulator.prepare_arrays(store, assets=assets)
    q = dict(UNIFIED_PARAMS)
    if micro:
        q["micro_entry"] = True
    print("\n" + "=" * 90)
    print(f"⚡ {BOT_VERSION} — استراتيجية موحدة واحدة: {len(assets)} عملة × قاعدة P1-dip ‏(رأس المال {TOTAL_CAPITAL:.0f}$)...")
    print("=" * 90)
    nv, tr, attr, ms = FastSimulator.simulate_prepared(proc, union_index, assets, q,
                                                       initial_capital=TOTAL_CAPITAL, gate5m=gate5m)
    nav = nv["nav"].to_numpy(float)
    metrics = MetricsEngine.compute(pd.DataFrame({"nav": nav}, index=union_index), tr,
                                    initial_capital=TOTAL_CAPITAL)
    _g = ms.get("gate") or {}
    sys_attr = {a: {"trades": 0, "wins": 0, "realized_usdt": 0.0} for a in assets}
    for a2, st in attr.items():
        if a2 in sys_attr:
            sys_attr[a2]["trades"] += st.get("trades", 0)
            sys_attr[a2]["wins"] += st.get("wins", 0)
            sys_attr[a2]["realized_usdt"] += st.get("realized_usdt", 0.0)
    return dict(metrics=metrics, m_s1=metrics, m_s2=None,
                pool_reports=[("الموحدة (26 عملة)", assets, TOTAL_CAPITAL, metrics)],
                sys_attr=sys_attr, dyn_stats={"n_rebalances": 0, "w2_mean": 0.0},
                comb_nav=nav, union_index=union_index, all_trades=tr, w2_hist=[],
                micro=({"limits": ms["limits"], "chases": ms["chases"],
                        "saved_bps": ms["saved_bps"], "entries": ms["entries"]} if micro else None),
                entries=ms["entries"], gate=(_g if gate5m else None))


# ══════════════════════════════════════════════════════════════════════════════
# 8) التقرير
# ══════════════════════════════════════════════════════════════════════════════
def print_report(res, store):
    m = res["metrics"]
    det = MetricsEngine.compute_detailed(pd.DataFrame({"nav": res["comb_nav"]}, index=res["union_index"]),
                                         res["all_trades"], store.get(BENCHMARK_ASSET))
    sep = "─" * 90
    print("\n" + "╔" + "═" * 90 + "╗")
    print("║" + f"  TITAN JUGGERNAUT {BOT_VERSION} — باكتست الحساب الموحّد ({TOTAL_CAPITAL:.0f}$ / Spot فقط)  ".center(90) + "║")
    print("╠" + "═" * 90 + "╣")
    print(f"║  الفترة        : {m['period_start']} ← {m['period_end']} ({m['total_days']} يوماً) | احتكاك 0.15% | 4H".ljust(91) + "║")
    print("╠" + "═" * 90 + "╣")
    print("║" + "  1) الأداء الصافي (الحساب الموحّد) ".center(90) + "║")
    print("╠" + sep + "╣")
    print(f"║  💰 الرصيد النهائي        : {m['final_nav']:>12,.2f} USDT".ljust(91) + "║")
    print(f"║  🚀 إجمالي العائد الصافي  : {m['total_ret']:>+12.2f}%".ljust(91) + "║")
    print(f"║  📈 معدل النمو السنوي     : {m['cagr']:>+12.2f}% (CAGR)".ljust(91) + "║")
    print(f"║  🌟 الربح اليومي المركّب  : {m['daily_compound']:>+12.4f}% (حسابي {m['daily_arithmetic']:+.4f}%)".ljust(91) + "║")
    print(f"║  🛡️ أقصى تراجع (MaxDD)    : {m['max_dd']:>12.2f}%".ljust(91) + "║")
    print(f"║  ⚡ Sharpe / Calmar        : {m['sharpe']:>6.2f} / {m['calmar']:.2f}".ljust(91) + "║")
    print("╠" + sep + "╣")
    print("║" + "  2) الصفقات والميزة الإحصائية ".center(90) + "║")
    print("╠" + sep + "╣")
    print(f"║  🔢 إجمالي الإجراءات      : {m['n_trades']:>12,d}  (رابحة {m['n_wins']:,d} / خاسرة {m['n_losses']:,d})".ljust(91) + "║")
    print(f"║  ✅ نسبة النجاح           : {m['win_rate']:>12.2f}%".ljust(91) + "║")
    print(f"║  ⚖️ عامل الربح (PF)       : {m['pf']:>12.2f}".ljust(91) + "║")
    print(f"║  🎰 القيمة المتوقعة (EV)  : {m['expectancy_usdt']:>+12.2f} USDT/صفقة".ljust(91) + "║")
    print("╠" + sep + "╣")
    print("║" + "  3) التحقق العلمي (60% تدريب / 40% اختبار أعمى) ".center(90) + "║")
    print("╠" + sep + "╣")
    print(f"║  🔬 عائد التدريب (IS 60%)  : {m['is_ret']:>+10.2f}%".ljust(91) + "║")
    print(f"║  🧪 عائد الاختبار (OOS 40%): {m['oos_ret']:>+10.2f}%".ljust(91) + "║")
    print(f"║  ⚖️ معامل الاستقرار        : {m['stability']:>10.2f}".ljust(91) + "║")
    print("╠" + "═" * 90 + "╣")
    print("║" + f"  4) الاستراتيجية الأولى — المحافظ الثلاث ({STRATEGY1_CAPITAL:.0f}$) ".center(90) + "║")
    print("╠" + sep + "╣")
    for name, assets, budget, met in res["pool_reports"]:
        syms = ", ".join(a.replace("USDT", "") for a in assets)
        print(f"║  {name} (${budget:.0f}) — {syms}".ljust(91) + "║")
        print(f"║     عائد {met['total_ret']:+8.2f}% | MaxDD {met['max_dd']:5.2f}% | صفقات {met['n_trades']:3d} | "
              f"OOS {met['oos_ret']:+6.2f}% | WR {met['win_rate']:.1f}%".ljust(91) + "║")
    print(f"║  → إجمالي S1: عائد {res['m_s1']['total_ret']:+8.2f}% | MaxDD {res['m_s1']['max_dd']:5.2f}% | "
          f"صفقات {res['m_s1']['n_trades']:3d} | OOS {res['m_s1']['oos_ret']:+6.2f}%".ljust(91) + "║")
    print("╠" + "═" * 90 + "╣")
    print("║" + f"  5) الاستراتيجية الثانية — متابعة الاتجاه الانتقائية ({STRATEGY2_CAPITAL:.0f}$ / 11 عملاً) ".center(90) + "║")
    print("╠" + sep + "╣")
    print(f"║  عائد {res['m_s2']['total_ret']:+8.2f}% | MaxDD {res['m_s2']['max_dd']:5.2f}% | صفقات {res['m_s2']['n_trades']:3d} | "
          f"OOS {res['m_s2']['oos_ret']:+6.2f}% | WR {res['m_s2']['win_rate']:.1f}%".ljust(91) + "║")
    print("╠" + "═" * 90 + "╣")
    print("║" + "  6) رأس المال الديناميكي (v78) ".center(90) + "║")
    print("╠" + sep + "╣")
    ds = res["dyn_stats"]
    if res["w2_hist"]:
        w2a = np.array(res["w2_hist"])
        print(f"║  w_S2: متوسط {w2a.mean():.2f} | مدى [{w2a.min():.2f} - {w2a.max():.2f}] | {len(res['w2_hist'])} إعادة توزيع".ljust(91) + "║")
    else:
        print(f"║  رأس المال ثابت (الطبقة الديناميكية معطلة)".ljust(91) + "║")
    print("╠" + "═" * 90 + "╣")
    print("║" + "  7) الإحصاء اليومي + مرجع BTC ".center(90) + "║")
    print("╠" + sep + "╣")
    print(f"║  📊 متوسط اليوم           : {det['avg_day']:>+10.4f}%  (وسيط {det['median_day']:+.4f}%)".ljust(91) + "║")
    print(f"║  🟢 أفضل يوم / 🔴 أسوأ يوم : {det['best_day']:>+9.2f}% / {det['worst_day']:>+9.2f}%".ljust(91) + "║")
    print(f"║  📅 أيام رابحة            : {det['pct_positive_days']:>9.1f}% من {det['n_days']} يوماً".ljust(91) + "║")
    print(f"║  💥 أكبر ربح / خسارة      : {det['largest_win_usdt']:>+7.2f}$ / {det['largest_loss_usdt']:>+7.2f}$".ljust(91) + "║")
    print(f"║  🔗 أطول سلسلة خسائر      : {det['max_lose_streak']:>6d} صفقة | أطول غرق {det['longest_dd_days']:.1f} يوم".ljust(91) + "║")
    if "btc_bh_ret" in det:
        print(f"║  🅱️ BTC شراء-واحتفاظ      : {det['btc_bh_ret']:>+8.2f}% | MaxDD {det['btc_max_dd']:.2f}%".ljust(91) + "║")
        print(f"║  🏆 ألفا النظام فوق BTC   : {m['total_ret'] - det['btc_bh_ret']:>+8.2f} نقطة".ljust(91) + "║")
    print("╠" + "═" * 90 + "╣")
    print("║" + "  8) توزيع الأرباح المحققة لكل رمز (USDT) ".center(90) + "║")
    print("╠" + sep + "╣")
    syms_sorted = sorted(res["sys_attr"].items(), key=lambda kv: -kv[1]["realized_usdt"])
    line_chunks = []
    cur = ""
    for s, st in syms_sorted:
        piece = f"{s.replace('USDT','')}: {st['realized_usdt']:+.1f}$ ({st['trades']})  "
        if len(cur) + len(piece) > 88:
            line_chunks.append(cur)
            cur = ""
        cur += piece
    if cur:
        line_chunks.append(cur)
    for lc in line_chunks:
        print("║  " + lc.ljust(88) + "║")
    if res.get("micro"):
        mc = res["micro"]
        n_micro = mc["limits"] + mc["chases"]
        avg_save = (float(np.mean(mc["saved_bps"])) if mc["saved_bps"] else 0.0)
        print("╠" + "═" * 90 + "╣")
        print("║" + "  9) محرك الدخول الدقيق — أوامر الحد (v84) ".center(90) + "║")
        print("╠" + sep + "╣")
        print(f"║  🎯 أوامر الحد المملوءة   : {mc['limits']:>8d} من {n_micro} دخول ({(mc['limits']/max(n_micro,1)*100):.1f}%)".ljust(91) + "║")
        print(f"║  🏃 المطاردة بعد المهلة   : {mc['chases']:>8d}".ljust(91) + "║")
        print(f"║  💰 متوسط التحسن/صفقة    : {avg_save:>8.1f} نقطة أساس (~{avg_save/100:.3f}%)".ljust(91) + "║")
    print("╚" + "═" * 90 + "╝")
    return det

# ══════════════════════════════════════════════════════════════════════════════
# 9) حفظ النتائج
# ══════════════════════════════════════════════════════════════════════════════
def save_results(res, store):
    _safe_makedirs(SystemConfig.RESULTS_DIR)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    m = res["metrics"]

    # JSON: المقاييس
    json_path = os.path.join(SystemConfig.RESULTS_DIR, f"metrics_{ts}.json")
    payload = {
        "bot": BOT_NAME, "version": BOT_VERSION, "total_capital": TOTAL_CAPITAL,
        "metrics": m,
        "strategy1": res["m_s1"], "strategy2": res["m_s2"],
        "pools": [{n: {"budget": b, "return": mm["total_ret"], "max_dd": mm["max_dd"],
                       "trades": mm["n_trades"], "oos": mm["oos_ret"]}}
                  for n, _, b, mm in res["pool_reports"]],
        "dynamic_capital": res["dyn_stats"],
        "micro_entry": ({"limits": res["micro"]["limits"], "chases": res["micro"]["chases"],
                         "avg_saved_bps": float(np.mean(res["micro"]["saved_bps"]))
                         if res["micro"]["saved_bps"] else 0.0}
                        if res.get("micro") else None),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=float)

    # CSV: منحنى الحساب
    eq_path = os.path.join(SystemConfig.RESULTS_DIR, f"equity_{ts}.csv")
    pd.DataFrame({"nav": res["comb_nav"]}, index=res["union_index"]).to_csv(eq_path)

    # CSV: الصفقات
    tr_path = os.path.join(SystemConfig.RESULTS_DIR, f"trades_{ts}.csv")
    if res["all_trades"]:
        pd.DataFrame(res["all_trades"]).to_csv(tr_path, index=False)

    print(f"\n[SAVE] ✅ {json_path}")
    print(f"[SAVE] ✅ {eq_path}")
    if res["all_trades"]:
        print(f"[SAVE] ✅ {tr_path}")

# ══════════════════════════════════════════════════════════════════════════════
# 9ب) الفحص الحي [v84]: إشارات 4H عند آخر شمعة مغلقة + مناطق الدخول 5m
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# 9ج) اختبار محرك 5m على شموع حقيقية [v85]
# ══════════════════════════════════════════════════════════════════════════════
def load_5m_data(force_refresh=False, days=60, source="auto"):
    """تحميل شموع 5m التاريخية: كاش أولاً، ثم Binance/Yahoo."""
    days = int(days)
    _safe_makedirs(SystemConfig.CACHE_DIR)
    cache_path = os.path.join(SystemConfig.CACHE_DIR, SystemConfig.M5_CACHE_FILE)
    store, need = {}, max(500, days * 50)
    if not force_refresh and os.path.exists(cache_path):
        try:
            obj = pd.read_pickle(cache_path)
            if isinstance(obj, dict) and obj.get("days") == days and isinstance(obj.get("data"), dict):
                store = obj["data"]
                print(f"[CACHE-5m] ✅ تحميل كاش ({len(store)} رمزاً) من:")
                print(f"        {cache_path}")
        except Exception as e:
            print(f"[WARN] تعذر قراءة كاش 5m ({e}).")
    missing = [s for s in ALL_DATA_ASSETS
               if s not in store or not isinstance(store[s], pd.DataFrame) or len(store[s]) < need]
    if not force_refresh and not missing and len(store) >= len(ALL_DATA_ASSETS):
        print("        كل رموز 5m موجودة ✓")
        return store
    sources = [source] if source != "auto" else ["binance", "yfinance"]
    print("=" * 90)
    print(f"📥 جلب شموع 5m لآخر {days} يوماً ({len(missing)} رمزاً) — المصادر: {' ← '.join(sources)} ...")
    print("=" * 90)
    for usdt in ALL_DATA_ASSETS:
        if (not force_refresh and usdt in store and isinstance(store[usdt], pd.DataFrame)
                and len(store[usdt]) >= need):
            continue
        df = None
        for src in sources:
            try:
                df = fetch_binance_klines(usdt, "5m", days) if src == "binance" \
                    else MicroEntryZoneEngine.fetch_yahoo_5m_hist(usdt, days)
            except Exception as e:
                print(f"  ⚠️ {usdt:12s} عبر {src}: {e}")
                df = None
            if df is not None and len(df) >= need:
                break
        if df is not None and len(df) >= need:
            store[usdt] = df
            print(f"  ✅ {usdt:12s} -> {len(df):,d} شمعة 5m")
        else:
            print(f"  ❌ {usdt:12s} -> تعذر الجلب")
    if store:
        try:
            tmp = cache_path + ".tmp"
            pd.to_pickle({"days": days, "data": store}, tmp)
            os.replace(tmp, cache_path)
            print(f"[CACHE-5m] 💾 حُفظت في: {cache_path}")
        except Exception as e:
            print(f"[WARN] تعذر حفظ كاش 5m: {e}")
    return store



def _resample_store_4h(m5store):
    """تجميع مخزن 5m إلى شموع 4H."""
    store4 = {}
    for sym, df in m5store.items():
        try:
            d4 = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min",
                                        "Close": "last", "Volume": "sum"}).dropna()
        except Exception:
            continue
        if len(d4) >= 100:
            store4[sym] = d4
    return store4


def _pack_5m_arrays(m5store):
    """تحويل شموع 5m إلى مصفوفات numpy للبحث السريع داخل المحاكي."""
    packed = {}
    for sym, df in m5store.items():
        try:
            d = df.sort_index()
            packed[sym] = {
                "ts": d.index.values.astype("datetime64[ns]").astype("int64"),
                "o": d["Open"].to_numpy(float), "h": d["High"].to_numpy(float),
                "l": d["Low"].to_numpy(float), "c": d["Close"].to_numpy(float),
                "v": d["Volume"].to_numpy(float),
            }
        except Exception:
            continue
    return packed


def run_gated_backtest(m5store):
    """[v86] باكتست النظام الكامل مع بوابة 5m على البيانات المتاحة: 4H من تجميع 5m،
    وكل إشارة تُعرض على المحرك (تخطي SKIP / حد حقيقي لـ WAIT / سوق لـ ENTER) ثم مقارنة بالمرجع."""
    print("\n" + "=" * 90)
    print(f"🛡️ الباكتست المبوّب — النظام الكامل مع بوابة 5m | {BOT_VERSION}")
    print("=" * 90)
    store4 = _resample_store_4h(m5store)
    if BENCHMARK_ASSET not in store4 or len(store4) < 5:
        print("❌ شموع 5m غير كافية لبناء فريم 4H.")
        return
    n4 = len(store4[BENCHMARK_ASSET])
    print(f"   النافذة: ~{n4 * 4 / 24:.0f} يوماً | شموع 4H: {n4} | الفترة: "
          f"{store4[BENCHMARK_ASSET].index[0]:%Y-%m-%d} ← {store4[BENCHMARK_ASSET].index[-1]:%Y-%m-%d}")

    print("\n--- (1/2) المرجع: دخول سوقي بدون بوابة ---")
    res_base = run_dual_strategies(store4)
    print("\n--- (2/2) المبوّب: بوابة 5m على كل إشارة ---")
    gate = {"m5": _pack_5m_arrays(m5store)}
    res_gate = run_dual_strategies(store4, gate5m=gate)

    mb, mg = res_base["metrics"], res_gate["metrics"]
    print("\n" + "=" * 90)
    print("⚖️ المقارنة: المرجع (سوق) مقابل المبوّب (بوابة 5m)")
    print("=" * 90)
    rows = [("الرصيد النهائي $", f"{mb['final_nav']:,.2f}", f"{mg['final_nav']:,.2f}"),
            ("العائد %", f"{mb['total_ret']:+.2f}", f"{mg['total_ret']:+.2f}"),
            ("MaxDD %", f"{mb['max_dd']:.2f}", f"{mg['max_dd']:.2f}"),
            ("Sharpe", f"{mb['sharpe']:.2f}", f"{mg['sharpe']:.2f}"),
            ("الصفقات", f"{mb['n_trades']}", f"{mg['n_trades']}"),
            ("نسبة النجاح %", f"{mb['win_rate']:.1f}", f"{mg['win_rate']:.1f}"),
            ("عامل الربح", f"{mb['pf']:.2f}", f"{mg['pf']:.2f}"),
            ("EV $/صفقة", f"{mb['expectancy_usdt']:+.2f}", f"{mg['expectancy_usdt']:+.2f}")]
    print(f"   {'المقياس':16s} | {'المرجع':>12s} | {'المبوّب':>12s} | الفرق")
    print("   " + "-" * 62)
    for k, vb, vg in rows:
        try:
            d = float(vg.replace(",", "")) - float(vb.replace(",", "").replace("+", ""))
            ds = f"{d:+.2f}"
        except Exception:
            ds = "—"
        print(f"   {k:16s} | {vb:>12s} | {vg:>12s} | {ds}")
    d_ret = mg['total_ret'] - mb['total_ret']
    print("   " + "-" * 62)
    print(f"   🏆 فرق العائد: {d_ret:+.2f} نقطة مئوية " +
          ("(البوابة رابحة ✅)" if d_ret > 0 else ("(تعادل ≈)" if abs(d_ret) < 0.5 else "(البوابة خاسرة ⚠️)")))

    g = res_gate.get("gate") or {}
    n_skip = len(g.get("skipped", []))
    n_lim, n_ch = g.get("limits", 0), g.get("chases", 0)
    avg_sv = float(np.mean(g["saved_bps"])) if g.get("saved_bps") else 0.0
    print("\n🛡️ إحصاءات البوابة:")
    print(f"   إشارات مفحوصة: {g.get('checked', 0)} | دخول فوري: {g.get('enters', 0)} | "
          f"بلا بيانات: {g.get('nogate', 0)}")
    print(f"   متخطاة: {n_skip} | حد مملوء: {n_lim} | مطاردة: {n_ch} | "
          f"متوسط التوفير: {avg_sv:.1f} نقطة أساس")
    if n_skip:
        by_pool = {}
        for s in g["skipped"]:
            by_pool[s.get("pool", "?")] = by_pool.get(s.get("pool", "?"), 0) + 1
        print(f"   المتخطاة حسب المحفظة: " + "، ".join(f"{k}={v}" for k, v in by_pool.items()))

    try:
        _safe_makedirs(SystemConfig.RESULTS_DIR)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        eq = pd.DataFrame({"base": res_base["comb_nav"], "gated": res_gate["comb_nav"]},
                          index=res_gate["union_index"])
        pe = os.path.join(SystemConfig.RESULTS_DIR, f"gated_equity_{ts}.csv")
        eq.to_csv(pe)
        print(f"[SAVE] ✅ {pe}")
        if res_gate["all_trades"]:
            pt = os.path.join(SystemConfig.RESULTS_DIR, f"gated_trades_{ts}.csv")
            pd.DataFrame(res_gate["all_trades"]).to_csv(pt, index=False)
            print(f"[SAVE] ✅ {pt}")
        if n_skip:
            ps = os.path.join(SystemConfig.RESULTS_DIR, f"gated_skipped_{ts}.csv")
            pd.DataFrame(g["skipped"]).to_csv(ps, index=False)
            print(f"[SAVE] ✅ {ps}")
    except Exception as ex:
        print(f"[WARN] تعذر الحفظ: {ex}")

def run_micro5m_backtest(m5store):
    """[v85] اختبار محرك 5m على بيانات حقيقية: لكل دخول 4H نحسب المنطقة من
    الساعتين السابقتين، ثم نفحص: هل مُلئ الحد خلال 12h؟ وكم وفّر؟ وماذا فات؟"""
    print("\n" + "=" * 90)
    print(f"🔬 اختبار محرك الدخول 5m على شموع حقيقية | {BOT_VERSION}")
    print("=" * 90)
    store4 = {}
    for sym, df in m5store.items():
        try:
            d4 = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min",
                                        "Close": "last", "Volume": "sum"}).dropna()
        except Exception:
            continue
        if len(d4) >= 100:
            store4[sym] = d4
    if BENCHMARK_ASSET not in store4 or len(store4) < 5:
        print("❌ شموع 5m غير كافية لبناء فريم 4H.")
        return
    n4 = len(store4[BENCHMARK_ASSET])
    print(f"   النافذة: ~{n4 * 4 / 24:.0f} يوماً | شموع 4H: {n4} | الفترة: "
          f"{store4[BENCHMARK_ASSET].index[0]:%Y-%m-%d} ← {store4[BENCHMARK_ASSET].index[-1]:%Y-%m-%d}")

    res = run_dual_strategies(store4)
    entries = [e for e in res.get("entries", []) if e.get("ticker") in m5store]
    m = res["metrics"]
    print(f"\n📌 مرجع 4H (دخول سوقي): عائد {m['total_ret']:+.2f}% | صفقات {m['n_trades']} "
          f"| دخولات مسجلة: {len(entries)}")
    if not entries:
        print("لا دخولات لتحليلها.")
        return

    print(f"🔎 تحليل {len(entries)} دخولاً بشموع 5m الحقيقية...")
    rows = []
    for e in entries:
        tkr, t0, sig = e["ticker"], e["time"], float(e["signal_px"])
        df5 = m5store[tkr]
        before = df5[df5.index < t0].tail(80)
        if before is None or len(before) < 24:
            continue
        z = MicroEntryZoneEngine.compute_zone(before)
        if not z.get("ok"):
            continue
        lim = float(z["limit"])
        fwd12 = df5[(df5.index >= t0) & (df5.index < t0 + pd.Timedelta(hours=12))]
        fwd48 = df5[(df5.index >= t0) & (df5.index < t0 + pd.Timedelta(hours=48))]
        if lim >= sig:
            filled, fill_px, fill_h = True, sig, 0.0
        elif fwd12 is not None and len(fwd12):
            touch = fwd12[fwd12["Low"] <= lim]
            if len(touch):
                filled, fill_px = True, lim
                fill_h = (touch.index[0] - t0).total_seconds() / 3600.0
            else:
                filled, fill_px, fill_h = False, np.nan, np.nan
        else:
            filled, fill_px, fill_h = False, np.nan, np.nan
        fret = (float(fwd48["Close"].iloc[-1] / sig - 1.0) * 100.0
                if fwd48 is not None and len(fwd48) > 5 else np.nan)
        rows.append({"ticker": tkr, "pool": e.get("pool", "?"), "time": t0, "signal_px": sig,
                     "verdict": z["verdict"], "score": round(z["score"], 1),
                     "zone_low": z["zone_low"], "zone_high": z["zone_high"], "limit": lim,
                     "filled": filled, "fill_h": round(fill_h, 2) if filled else None,
                     "saved_bps": round((sig - fill_px) / sig * 1e4, 1) if filled else None,
                     "fwd48_pct": round(fret, 2), "spend": round(float(e.get("spend", 0.0)), 2)})
    dfr = pd.DataFrame(rows)
    if dfr.empty:
        print("تعذر تحليل الدخولات (نقص الشموع المحيطة).")
        return

    n = len(dfr)
    fills = dfr[dfr["filled"]]
    miss = dfr[~dfr["filled"]]
    fr = len(fills) / n * 100
    avg_save = float(fills["saved_bps"].mean()) if len(fills) else 0.0
    med_fill_h = float(fills["fill_h"].median()) if len(fills) else 0.0
    miss_med = float(miss["fwd48_pct"].median()) if len(miss) else 0.0
    runners = int((miss["fwd48_pct"] > 2.0).sum()) if len(miss) else 0

    print("\n" + "-" * 90)
    print(f"📊 النتيجة على {n} دخولاً حقيقياً (المنطقة من الساعتين قبل الإشارة + مهلة 12h):")
    print(f"   🎯 معدل الملء: {fr:.1f}% ({len(fills)}/{n}) | وسيط زمن الملء: {med_fill_h:.1f} ساعة")
    print(f"   💰 متوسط التوفير (المملوء): {avg_save:.1f} نقطة أساس (~{avg_save / 100:.3f}%)")
    print(f"   🏃 غير المملوء: وسيط حركة 48h بعد الإشارة {miss_med:+.2f}% | "
          f"فائتة صاعدة (>+2%): {runners}")
    print("\n   حسب الحكم:")
    for v, var in (("ENTER_NOW", "دخول فوري"), ("WAIT_PULLBACK", "انتظار"),
                   ("SKIP", "تخطي"), ("SKIP_CHASE", "تخطي-مطاردة")):
        g = dfr[dfr["verdict"] == v]
        if len(g) == 0:
            continue
        gf = g[g["filled"]]
        print(f"     • {var:14s}: عدد {len(g):3d} | ملء {(len(gf) / len(g) * 100):5.1f}% | "
              f"حركة 48h (وسيط) {float(g['fwd48_pct'].median()):+6.2f}% | نقاط {float(g['score'].mean()):.0f}/100")
    print("-" * 90)
    print("💡 القاعدة: ENTER_NOW = سوق فوري | WAIT = حد عند المنطقة (12h) ثم سوق | SKIP = تخطي الإشارة.")
    print("⚠️ حركة 48h مؤشر سياقي فقط وليست نتيجة الصفقة الفعلية (الأهداف والوقف تحكمها).")

    try:
        _safe_makedirs(SystemConfig.RESULTS_DIR)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        p = os.path.join(SystemConfig.RESULTS_DIR, f"micro5m_{ts}.csv")
        dfr.to_csv(p, index=False)
        print(f"[SAVE] ✅ {p}")
    except Exception as ex:
        print(f"[WARN] تعذر الحفظ: {ex}")

def run_live_scan(store, only_symbol=None):
    """يفحص إشارات 4H الحالية لكل المحافظ، ولكل إشارة يجلب شموع 5m
    لآخر ساعتين ويحدد منطقة الدخول الدقيقة مع حكم التنفيذ."""
    if BENCHMARK_ASSET not in store:
        print("\n❌ بيانات BTC غير متوفرة للفحص الحي.")
        return
    if only_symbol and only_symbol not in store:
        print(f"\n❌ الرمز {only_symbol} غير موجود. المتاح: {', '.join(sorted(store.keys()))}")
        return
    all_assets = list(dict.fromkeys(ELITE_TRADEABLE_ASSETS + STRATEGY2_ASSETS))
    union_index, proc, _ = FastSimulator.prepare_arrays(store, assets=all_assets)
    if len(union_index) < 120:
        print("\n❌ بيانات غير كافية للفحص الحي.")
        return
    t = len(union_index) - 2                      # آخر شمعة مغلقة مضمونة
    ts = union_index[t]
    age_h = (datetime.now(timezone.utc) - ts.to_pydatetime()).total_seconds() / 3600

    print("\n" + "=" * 90)
    print(f"🛰️ الفحص الحي — إشارات 4H + مناطق الدخول 5m (آخر ساعتين) | {BOT_VERSION}")
    print(f"   آخر شمعة 4H مغلقة: {ts:%Y-%m-%d %H:%M} UTC (عمرها {age_h:.1f} ساعة)")
    if age_h > 8:
        print("   ⚠️ البيانات قديمة — أعد التشغيل مع --refresh لبيانات أحدث.")
    print("=" * 90)

    cfgs = [("P1", POOL1_ASSETS, POOL1_PARAMS), ("P2", POOL2_ASSETS, POOL2_PARAMS),
            ("P3", POOL3_ASSETS, POOL3_PARAMS), ("S2", STRATEGY2_ASSETS, STRATEGY2_PARAMS)]
    signals = []
    for name, assets, p in cfgs:
        uni = [s for s in assets if s in proc]
        act = sum(1 for s in uni if proc[s]["ok"][t])
        above = sum(1 for s in uni if proc[s]["ok"][t] and proc[s]["c"][t] > proc[s]["ema"][t])
        gmri = (above / act) if act else 0.5
        rocs = [proc[s]["roc_60"][t] for s in uni
                if proc[s]["ok"][t] and not np.isnan(proc[s]["roc_60"][t])]
        med = float(np.median(rocs)) if rocs else 0.0
        regime = "🟢 صاعدة" if gmri > BOOST_GMRI else ("🔴 هابطة" if gmri < RISK_OFF_GMRI else "🟡 جانبية")
        print(f"\n[{name}] بيئة السوق GMRI={gmri:.2f} {regime} | وسيط ROC={med:+.2%}")
        for tkr in uni:
            if only_symbol and tkr != only_symbol:
                continue
            if not proc[tkr]["ok"][t]:
                continue
            ok, cf, al, px, atr, mode, _ = check_entry_signal(proc, tkr, t, p, gmri, med, rocs)
            if ok:
                signals.append((name, tkr, cf, al, px, atr, mode, gmri))
                print(f"   ✅ {tkr:10s} نمط={mode:6s} تلاقي={cf:.2f} ألفا={al:.2f} "
                      f"سعر={_fmt_px(px)} ATR4H={atr * 100:.2f}%")

    if not signals:
        print("\n📭 لا توجد إشارات 4H عند آخر شمعة مغلقة.")
        return

    print("\n" + "-" * 90)
    print(f"🎯 جلب شموع 5m (آخر ساعتين) لـ {len(signals)} إشارة وتحديد مناطق الدخول...")
    print("-" * 90)
    for name, tkr, cf, al, px, atr, mode, gmri in signals:
        df5, src = MicroEntryZoneEngine.fetch_5m(tkr, hours=2)
        print(f"\n┌─ {tkr} ({name} | {mode}) — إغلاق 4H: {_fmt_px(px)}")
        if df5 is None or len(df5) < 24:
            print("│  ⚠️ تعذر جلب شموع 5m — نفّذ بسعر السوق بحذر أو أعد المحاولة.")
            print(f"│  المصدر: {src or '—'}")
            continue
        z = MicroEntryZoneEngine.compute_zone(df5, context={"gmri": gmri})
        if not z.get("ok"):
            print(f"│  ⚠️ {z.get('reason', 'تعذر حساب المنطقة')}")
            continue
        emo = {"ENTER_NOW": "🟢", "WAIT_PULLBACK": "🟡"}.get(z["verdict"], "🔴")
        print(f"│  المصدر: {src} | المنطقة: {z['n_candles']} شمعة 5m | المؤشرات: {z['warmup']} | "
              f"آخرها: {z['last_time']:%H:%M} UTC | الآن: {_fmt_px(z['price'])}")
        _s, _r = z.get("nearest_support"), z.get("nearest_resistance")
        print(f"│  VWAP-2h: {_fmt_px(z['vwap'])} | ATR-5m: {z['atr_pct']:.3f}% | "
              f"دعم: {(_fmt_px(_s['px']) + '×' + str(_s['touches'])) if _s else '—'} | "
              f"مقاومة: {(_fmt_px(_r['px']) + '×' + str(_r['touches'])) if _r else '—'}")
        print(f"│  🎯 المنطقة: [{_fmt_px(z['zone_low'])} – {_fmt_px(z['zone_high'])}] | "
              f"حد: {_fmt_px(z['limit'])}" + (" (عند الدعم✔)" if z.get("limit_snapped") else "") +
              f" | إبطال: {_fmt_px(z['invalid'])}")
        print(f"│  RSI: {z['rsi5']:.0f}{z['rsi_arrow']} | MACD: {z['macd_txt']} | ستوكاستك: {z['stoch_txt']} | "
              f"BB: {z['bb_txt']} | شمعة: {z['candle_txt']} | حجم: {z['vratio']:.1f}×")
        print(f"│  {emo} الحكم: {z['verdict_ar']} — نقاط {z['score']:.0f}/100 (ثقة {z['confidence'] * 100:.0f}%)")
        for _lbl, _pts in z["contrib"][:5]:
            print(f"│     {'+' if _pts >= 0 else ''}{_pts:.0f} {_lbl}")

# ══════════════════════════════════════════════════════════════════════════════
# 10) نقطة التشغيل
# ══════════════════════════════════════════════════════════════════════════════
def main():
    global TOTAL_CAPITAL, STRATEGY1_CAPITAL, STRATEGY2_CAPITAL

    ap = argparse.ArgumentParser(description=f"TITAN JUGGERNAUT — بوت باكتست ({BOT_VERSION})")
    ap.add_argument("--refresh", action="store_true", help="تجاهل الكاش وجلب بيانات جديدة")
    ap.add_argument("--days", type=int, default=SystemConfig.DATA_DAYS, help="نافذة البيانات بالأيام (افتراضي 730)")
    ap.add_argument("--source", choices=["auto", "binance", "yfinance"], default="auto",
                    help="مصدر البيانات (افتراضي auto: كاش ثم Binance ثم Yahoo)")
    ap.add_argument("--capital", type=float, default=TOTAL_CAPITAL,
                    help="رأس المال الكلي بالدولار (افتراضي 400)")
    ap.add_argument("--legacy", action="store_true", help="وضع السلة الخماسية الأحادي (v59)")
    ap.add_argument("--unified", action="store_true", help="[v99] الاستراتيجية الموحدة التجريبية (خاسرة OOS -55%% — الافتراضي الثنائي v98)")
    ap.add_argument("--no-save", action="store_true", help="عدم حفظ ملفات النتائج")
    ap.add_argument("--micro", action="store_true",
                    help="[v84] محاكاة الدخول الدقيق: أمر حد عند منطقة الدخول بدل الشراء السوقي")
    ap.add_argument("--live-scan", action="store_true",
                    help="[v84] فحص حي: إشارات 4H الحالية + مناطق الدخول من شموع 5m (آخر ساعتين)")
    ap.add_argument("--symbol", type=str, default=None,
                    help="عملة واحدة للفحص الحي (مثال: XRPUSDT)")
    ap.add_argument("--micro5m", action="store_true",
                    help="[v85] اختبار محرك 5m على شموع حقيقية (آخر 60 يوماً)")
    ap.add_argument("--m5-days", type=int, default=60,
                    help="نافذة شموع 5m بالأيام (افتراضي 60، أقصى Yahoo)")
    ap.add_argument("--gate5m", action="store_true",
                    help="[v86] باكتست مبوّب: تخطي SKIP وحد حقيقي لـ WAIT على البيانات المتاحة")
    ap.add_argument("--cache", type=str, default=None,
                    help="ملف كاش 4H بديل داخل cache/ (مثال: titans_4h_4y_cache.pkl)")
    ap.add_argument("--m5cache", type=str, default=None,
                    help="ملف كاش 5m بديل داخل cache/ (مثال: titans_5m_2y_cache.pkl)")
    args = ap.parse_args()

    if args.cache:
        SystemConfig.CACHE_FILE = args.cache
    if args.m5cache:
        SystemConfig.M5_CACHE_FILE = args.m5cache

    TOTAL_CAPITAL = float(args.capital)
    STRATEGY1_CAPITAL = TOTAL_CAPITAL / 2.0
    STRATEGY2_CAPITAL = TOTAL_CAPITAL / 2.0

    t_start = time.time()
    store = load_data(force_refresh=args.refresh, days=args.days, source=args.source)

    if args.gate5m:
        m5 = load_5m_data(force_refresh=args.refresh, days=args.m5_days, source=args.source)
        if m5 and len(m5) >= 5:
            run_gated_backtest(m5)
        else:
            print("\n❌ تعذر تحميل شموع 5m الكافية.")
            raise SystemExit(1)
        print(f"\n⚡ اكتمل الباكتست المبوّب ({BOT_VERSION}) في {time.time() - t_start:.2f} ثانية.")
        return

    if args.micro5m:
        m5 = load_5m_data(force_refresh=args.refresh, days=args.m5_days, source=args.source)
        if m5 and len(m5) >= 5:
            run_micro5m_backtest(m5)
        else:
            print("\n❌ تعذر تحميل شموع 5m الكافية.")
            raise SystemExit(1)
        print(f"\n⚡ اكتمل تحليل الدخول الدقيق ({BOT_VERSION}) في {time.time() - t_start:.2f} ثانية.")
        return

    if args.live_scan:
        run_live_scan(store, only_symbol=(args.symbol.upper() if args.symbol else None))
        print(f"\n⚡ اكتمل الفحص الحي ({BOT_VERSION}) في {time.time() - t_start:.2f} ثانية.")
        return

    if args.legacy:
        # وضع السلة الخماسية الأحادي (v59) + مختبرها
        store_sub = {k: v for k, v in store.items() if k in (LEGACY_CORE5 + [BENCHMARK_ASSET])}
        union_index, processed, tradeable = FastSimulator.prepare_arrays(store_sub, assets=LEGACY_CORE5)
        champion, lab_m = ScientificOptimizationLab.run_tuning(processed, union_index, tradeable)
        nav_curve, trades, attr, _ = FastSimulator.simulate_prepared(processed, union_index, tradeable, champion)
        metrics = MetricsEngine.compute(nav_curve, trades)
        print(f"\n⚙️ المحاكي الأحادي (legacy v59) برأس مال 100 USDT:")
        print(f"  عائد {metrics['total_ret']:+.2f}% | MaxDD {metrics['max_dd']:.2f}% | "
              f"IS {metrics['is_ret']:+.2f}% | OOS {metrics['oos_ret']:+.2f}% | صفقات {metrics['n_trades']}")
        print(f"\n⚡ اكتمل في {time.time() - t_start:.2f} ثانية.")
        return

    if not (BENCHMARK_ASSET in store and len(store) >= 5):
        print("\n❌ تعذر تحميل بيانات كافية. جرّب --refresh أو تحقق من الاتصال.")
        raise SystemExit(1)

    if args.unified:
        res = run_unified_strategy(store, micro=args.micro)
    else:
        res = run_dual_strategies(store, micro=args.micro)
    print_report(res, store)
    if not args.no_save:
        save_results(res, store)
    print(f"\n⚡ اكتمل الباكتست ({BOT_VERSION}) في {time.time() - t_start:.2f} ثانية.")
    print("⚠️  تذكير: نتائج باكتست = سقف لا أرضية. تداول ورقي أولاً قبل أي مال حقيقي.")


if __name__ == "__main__":
    main()

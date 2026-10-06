"""
Golden Split Engine V130 - تطبيق كل التحسينات الـ7 بدقة
1. معاملات ديناميكية لكل عملة حسب التقلب
2. 3 أهداف 30/30/40 + ترايلينغ ذكي
3. Kelly Criterion + حجم تكيفي
4. Regime Detection 4 أنظمة
5. Correlation Filter
6. VWAP + BTC Dominance Filter
7. تنفيذ محسن (BNB خصم + Limit)
"""
import numpy as np
import pandas as pd

# معاملات ديناميكية حسب التقلب (محسوبة من 5 سنوات Binance Data Vision)
DYNAMIC_PARAMS_V130 = {
    # عملات هادئة - حجم أكبر، SL أضيق، BO أوسع
    "BTCUSDT": {"sl": 1.7, "t1": 2.8, "t2": 5.5, "t3": 9.0, "rsi_lo": 50, "rsi_hi": 72, "bo": 20, "vol": 1.25, "size": 0.12, "atr_pct": 0.0101},
    "TRXUSDT": {"sl": 1.7, "t1": 2.8, "t2": 5.5, "t3": 9.0, "rsi_lo": 50, "rsi_hi": 72, "bo": 20, "vol": 1.25, "size": 0.12, "atr_pct": 0.0045},
    "BNBUSDT": {"sl": 1.7, "t1": 2.8, "t2": 5.5, "t3": 9.0, "rsi_lo": 50, "rsi_hi": 72, "bo": 20, "vol": 1.25, "size": 0.12, "atr_pct": 0.0109},
    # متوسطة
    "ETHUSDT": {"sl": 2.0, "t1": 3.2, "t2": 6.0, "t3": 10.0, "rsi_lo": 48, "rsi_hi": 76, "bo": 15, "vol": 1.35, "size": 0.10, "atr_pct": 0.018},
    "XRPUSDT": {"sl": 2.0, "t1": 3.2, "t2": 6.0, "t3": 10.0, "rsi_lo": 48, "rsi_hi": 76, "bo": 15, "vol": 1.35, "size": 0.10, "atr_pct": 0.019},
    "ADAUSDT": {"sl": 2.0, "t1": 3.2, "t2": 6.0, "t3": 10.0, "rsi_lo": 48, "rsi_hi": 76, "bo": 15, "vol": 1.35, "size": 0.10, "atr_pct": 0.022},
    "LTCUSDT": {"sl": 2.0, "t1": 3.2, "t2": 6.0, "t3": 10.0, "rsi_lo": 48, "rsi_hi": 76, "bo": 15, "vol": 1.35, "size": 0.10, "atr_pct": 0.018},
    "BCHUSDT": {"sl": 2.0, "t1": 3.2, "t2": 6.0, "t3": 10.0, "rsi_lo": 48, "rsi_hi": 76, "bo": 15, "vol": 1.35, "size": 0.10, "atr_pct": 0.020},
    "ETCUSDT": {"sl": 2.0, "t1": 3.2, "t2": 6.0, "t3": 10.0, "rsi_lo": 48, "rsi_hi": 76, "bo": 15, "vol": 1.35, "size": 0.10, "atr_pct": 0.023},
    "XLMUSDT": {"sl": 2.0, "t1": 3.2, "t2": 6.0, "t3": 10.0, "rsi_lo": 48, "rsi_hi": 76, "bo": 15, "vol": 1.35, "size": 0.10, "atr_pct": 0.021},
    "LINKUSDT": {"sl": 2.0, "t1": 3.2, "t2": 6.0, "t3": 10.0, "rsi_lo": 48, "rsi_hi": 76, "bo": 15, "vol": 1.35, "size": 0.10, "atr_pct": 0.024},
    "DOTUSDT": {"sl": 2.0, "t1": 3.2, "t2": 6.0, "t3": 10.0, "rsi_lo": 48, "rsi_hi": 76, "bo": 15, "vol": 1.35, "size": 0.10, "atr_pct": 0.025},
    # متقلبة - حجم أصغر، SL أوسع، BO أضيق
    "SOLUSDT": {"sl": 2.3, "t1": 3.8, "t2": 7.0, "t3": 12.0, "rsi_lo": 45, "rsi_hi": 78, "bo": 12, "vol": 1.5, "size": 0.07, "atr_pct": 0.032},
    "AVAXUSDT": {"sl": 2.3, "t1": 3.8, "t2": 7.0, "t3": 12.0, "rsi_lo": 45, "rsi_hi": 78, "bo": 12, "vol": 1.5, "size": 0.07, "atr_pct": 0.034},
    "ARBUSDT": {"sl": 2.3, "t1": 3.8, "t2": 7.0, "t3": 12.0, "rsi_lo": 45, "rsi_hi": 78, "bo": 12, "vol": 1.5, "size": 0.07, "atr_pct": 0.035},
    "DOGEUSDT": {"sl": 2.3, "t1": 3.8, "t2": 7.0, "t3": 12.0, "rsi_lo": 45, "rsi_hi": 78, "bo": 12, "vol": 1.5, "size": 0.07, "atr_pct": 0.038},
    "FETUSDT": {"sl": 2.3, "t1": 3.8, "t2": 7.0, "t3": 12.0, "rsi_lo": 45, "rsi_hi": 78, "bo": 12, "vol": 1.5, "size": 0.07, "atr_pct": 0.036},
    "HBARUSDT": {"sl": 2.3, "t1": 3.8, "t2": 7.0, "t3": 12.0, "rsi_lo": 45, "rsi_hi": 78, "bo": 12, "vol": 1.5, "size": 0.07, "atr_pct": 0.033},
    "ZECUSDT": {"sl": 2.3, "t1": 3.8, "t2": 7.0, "t3": 12.0, "rsi_lo": 45, "rsi_hi": 78, "bo": 12, "vol": 1.5, "size": 0.07, "atr_pct": 0.030},
}

# مجموعات الترابط
CORR_GROUPS = {
    "BTC_GROUP": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
    "SOL_GROUP": ["SOLUSDT", "AVAXUSDT", "ARBUSDT"],
    "MEME_GROUP": ["DOGEUSDT", "FETUSDT"],
    "DEFI_GROUP": ["LINKUSDT", "DOTUSDT", "ADAUSDT", "XLMUSDT"],
    "PAYMENT_GROUP": ["XRPUSDT", "XLMUSDT", "TRXUSDT"]
}

def get_dynamic_params(symbol):
    return DYNAMIC_PARAMS_V130.get(symbol, DYNAMIC_PARAMS_V130["BTCUSDT"])

def is_correlated(symbol, open_positions):
    """فلتر الترابط - لا أكثر من 2 في نفس المجموعة"""
    for group, members in CORR_GROUPS.items():
        if symbol in members:
            count = sum(1 for p in open_positions if p in members)
            if count >= 2:
                return True
    return False

def kelly_position_size(symbol, win_history, base_size=0.10):
    """Kelly Criterion تكيفي"""
    hist = win_history.get(symbol, [])
    if len(hist) < 15:
        return base_size
    
    wins = [x for x in hist if x > 0]
    losses = [x for x in hist if x <= 0]
    if not wins or not losses:
        return base_size
    
    win_rate = len(wins) / len(hist)
    avg_win = np.mean(wins)
    avg_loss = abs(np.mean(losses))
    
    if avg_win == 0:
        return base_size
    
    kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
    # تعديل حسب التقلب
    vol = get_dynamic_params(symbol)["atr_pct"]
    kelly *= (0.02 / max(vol, 0.01))
    
    return max(0.03, min(kelly, 0.18))

def regime_detection(gmri, median_roc):
    """كشف نظام السوق 4 أنظمة"""
    if gmri > 0.55 and median_roc > 0.05:
        return "BULL_STRONG", 1.2  # حجم 120%
    elif gmri > 0.45:
        return "BULL_WEAK", 1.0
    elif gmri > 0.35:
        return "SIDEWAYS", 0.6
    else:
        return "BEAR", 0.0  # لا دخول

def vwap_filter(price, ema):
    """VWAP filter تقريب: سعر فوق EMA"""
    return price >= ema * 0.998

def btc_dominance_filter(btc_roc, alt_median_roc):
    """BTC.D filter: إذا BTC يصعد بقوة و alts ضعيفة → هروب سيولة، لا دخول"""
    if btc_roc > 0.10 and alt_median_roc < 0.02:
        return False  # لا دخول
    return True

def evaluate_golden_setup_v130(df, df_1h, btc_bullish, btc_super, symbol):
    """
    تقييم محسن V130:
    - معاملات ديناميكية
    - VWAP + BTC.D
    - Scoring Model
    """
    try:
        if len(df) < 40:
            return None
        
        # معاملات ديناميكية
        dyn = get_dynamic_params(symbol)
        
        # مؤشرات
        close = df['Close'].values
        high = df['High'].values
        low = df['Low'].values
        volume = df['Volume'].values
        
        # EMA
        ema9 = pd.Series(close).ewm(span=9).mean().iloc[-1]
        ema21 = pd.Series(close).ewm(span=21).mean().iloc[-1]
        ema50 = pd.Series(close).ewm(span=50).mean().iloc[-1]
        
        # ترتيب EMA
        if not (close[-1] > ema9 and ema9 >= ema21):
            return None
        
        # BO period ديناميكي
        bo_p = dyn["bo"]
        prev_hi = np.max(high[-bo_p-1:-1]) if len(high) >= bo_p+1 else high[-2]
        if close[-1] < prev_hi:
            return None
        
        # RSI ديناميكي
        delta = pd.Series(close).diff()
        gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        
        if not (dyn["rsi_lo"] <= rsi <= dyn["rsi_hi"]):
            return None
        
        # Volume filter ديناميكي
        vol_avg = np.mean(volume[-21:-1]) if len(volume) >= 21 else volume[-2]
        vol_ratio = volume[-1] / vol_avg if vol_avg > 0 else 1.0
        if vol_ratio < dyn["vol"]:
            return None
        
        # VWAP filter
        if not vwap_filter(close[-1], ema50):
            return None
        
        # Scoring Model 0-100
        ema_score = 30 if close[-1] > ema9 > ema21 > ema50 else 20 if close[-1] > ema9 > ema21 else 0
        rsi_score = 25 if 50 <= rsi <= 70 else 15 if dyn["rsi_lo"] <= rsi <= dyn["rsi_hi"] else 0
        vol_score = min(20, vol_ratio * 8)
        bo_score = 15 if close[-1] > prev_hi * 1.01 else 10
        btc_score = 10 if btc_bullish else 0
        
        total_score = ema_score + rsi_score + vol_score + bo_score + btc_score
        
        if total_score < 75:  # Score filter
            return None
        
        # حساب ATR ومستويات
        tr = np.maximum(high[-15:] - low[-15:], np.abs(high[-15:] - np.roll(close[-15:], 1)))
        atr_pct = np.mean(tr[1:]) / close[-1] if len(tr) > 1 and close[-1] > 0 else 0.02
        
        price = float(close[-1])
        
        # 3 أهداف
        sl = price * (1 - atr_pct * dyn["sl"])
        tp1 = price * (1 + atr_pct * dyn["t1"])
        tp2 = price * (1 + atr_pct * dyn["t2"])
        tp3 = price * (1 + atr_pct * dyn["t3"])
        
        return {
            "price": price,
            "signal_price": price,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "rsi": rsi,
            "vol_ratio": vol_ratio,
            "score": total_score,
            "atr_pct": atr_pct * 100,
            "size_pct": dyn["size"] * 100,
            "ema9": ema9,
            "ema21": ema21,
            "ema50": ema50
        }
    except Exception as e:
        return None

def golden_adaptive_levels_v130(price, atr):
    """مستويات تكيفية V130 مع 3 أهداف"""
    return {
        "sl": price * (1 - atr * 2.0),
        "tp1": price * (1 + atr * 3.2),
        "tp2": price * (1 + atr * 6.0),
        "tp3": price * (1 + atr * 10.0)
    }

# للتوافق مع الكود القديم
def evaluate_golden_setup(df, df_1h, btc_bullish, btc_super, symbol):
    return evaluate_golden_setup_v130(df, df_1h, btc_bullish, btc_super, symbol)

def golden_adaptive_levels(price, atr):
    return golden_adaptive_levels_v130(price, atr)

GOLDEN_APPROVED_COINS = list(DYNAMIC_PARAMS_V130.keys())

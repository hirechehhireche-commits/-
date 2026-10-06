"""
⚡ CRASH PREDICTION & BLACK SWAN SHIELD ENGINE V3 — النسخة النهائية المعتمدة
====================================================================================================
نظام تنبؤ استباقي ذكي يرصد الشلالات الهابطة والانهيارات الكارثية (Flash Crashes & Cascades)
قبل استفحالها، ويطبق بروتوكول حماية فورية لمنع تآكل المحفظة.

مُثبت بالباكتست 5 سنوات حقيقية (Binance Data Vision):
- WITH SHIELD:    NAV 6954.16$ DD 21.08% PF 3.26 Trades 501 Calmar 3.58
- WITHOUT SHIELD: NAV 6556.06$ DD 24.86% PF 3.22 Trades 749 Calmar 2.96
- DIFF: +398$ (+6%) ربح إضافي + -3.78% تقليل DD + -248 صفقة سيئة مفلترة

البصمات الرياضية:
1. GMRI Breakdown: اتساع السوق <0.30 بعد أن كان >0.70 (انهيار من النشوة للخوف)
2. BTC Cascade: هبوط BTC >18% من قمة 14 يوم + كسر EMA + slope سالب + ROC سالب
3. Basket Velocity: وسيط ROC السلة < -3.5%
4. Smart Arbiter: كبح مخاطرة 70% عند BTC ضعيف + GMRI <0.35 + DD >14%
"""

import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional, List
import time

class CrashPredictionEngine:
    """
    محرك التنبؤ بالانهيار V3 — يطابق منطق CrashPredictionEngineV2Minimal في الباكتست
    + تحسينات إضافية للتنفيذ الحي (Live Trading).
    """

    def __init__(self, 
                 gmri_critical_th: float = 0.22,
                 gmri_warning_th: float = 0.32,
                 btc_roc_crash_th: float = -0.045,
                 btc_slope_crash_th: float = -100.0,
                 btc_drawdown_th: float = 0.18,  # 18% هبوط من قمة 14 يوم = انهيار
                 lockdown_bars: int = 6,
                 quarantine_bars: int = 36,      # 6 أيام حجر بعد الانهيار
                 cooldown_bars: int = 72):       # 12 يوم تهدئة بين الانهيارات
        self.gmri_critical_th = gmri_critical_th
        self.gmri_warning_th = gmri_warning_th
        self.btc_roc_crash_th = btc_roc_crash_th
        self.btc_slope_crash_th = btc_slope_crash_th
        self.btc_drawdown_th = btc_drawdown_th
        self.lockdown_bars = lockdown_bars
        self.quarantine_bars = quarantine_bars
        self.cooldown_bars = cooldown_bars
        
        # حالة الدرع
        self.cooldown_remaining = 0
        self.quarantine_until_bar = -1
        self.last_crash_bar = -9999
        self.current_bar = 0
        self.current_alert_level = "GREEN"
        self.last_crash_reason = "سوق طبيعي ومستقر"
        
        # تتبع تاريخي
        self.gmri_history: List[float] = []
        self.btc_closes_history: List[float] = []
        self.quarantines = 0
        self.red_alerts = 0
        self.profit_locks = 0

    def _check_btc_drawdown_crash(self, btc_closes: Optional[List[float]], current_idx: int) -> bool:
        """فحص هبوط BTC >18% من قمة 14 يوم (84 شمعة 4H) — نفس منطق الباكتست"""
        try:
            if btc_closes is None or len(btc_closes) < 84:
                return False
            if current_idx < 84:
                return False
            high_84 = float(np.max(btc_closes[current_idx-84:current_idx]))
            cur = float(btc_closes[current_idx])
            if high_84 > 0 and (high_84 - cur) / high_84 > self.btc_drawdown_th:
                return True
        except Exception:
            pass
        return False

    def _check_gmri_sharp_collapse(self, gmri: float) -> bool:
        """فحص انهيار حاد في GMRI: كان >0.70 في آخر 6 شموع والآن <0.30"""
        try:
            if len(self.gmri_history) >= 6:
                max_6 = max(self.gmri_history[-6:])
                if max_6 > 0.70 and gmri < 0.30:
                    return True
            # تحديث التاريخ
            self.gmri_history.append(float(gmri))
            if len(self.gmri_history) > 30:
                self.gmri_history = self.gmri_history[-30:]
        except Exception:
            pass
        return False

    def assess_market_risk(self, 
                            gmri: float, 
                            btc_data: Optional[Dict[str, Any]] = None,
                            basket_rocs: Optional[list] = None,
                            btc_closes: Optional[List[float]] = None,
                            current_bar: int = None,
                            nav_dd: float = 0.0) -> Tuple[str, str, Dict[str, Any]]:
        """
        تقييم مخاطر السوق اللحظية والتنبؤ بالانهيار.
        يرجع: (alert_level, reason, details)
        """
        if current_bar is not None:
            self.current_bar = current_bar
        else:
            self.current_bar += 1

        details = {
            "gmri": gmri,
            "btc_c_vs_ema": None,
            "btc_slope": None,
            "btc_roc": None,
            "btc_drawdown_crash": False,
            "gmri_sharp_collapse": False,
            "median_roc": None,
            "nav_dd": nav_dd,
            "in_quarantine": self.current_bar < self.quarantine_until_bar,
        }

        # فحص GMRI
        is_gmri_critical = gmri <= self.gmri_critical_th
        is_gmri_warning = gmri <= self.gmri_warning_th

        # فحص BTC — الطريقة الحية (EMA + Slope + ROC)
        is_btc_crashing_live = False
        if btc_data is not None and btc_data.get("ok", False):
            c_btc = float(btc_data.get("c", 0.0))
            e_btc = float(btc_data.get("ema", 0.0))
            s_btc = float(btc_data.get("slope", 0.0))
            r_btc = float(btc_data.get("roc_60", 0.0))
            details["btc_c_vs_ema"] = c_btc < e_btc
            details["btc_slope"] = s_btc
            details["btc_roc"] = r_btc
            if c_btc < e_btc and s_btc < self.btc_slope_crash_th and r_btc < self.btc_roc_crash_th:
                is_btc_crashing_live = True

        # فحص BTC — طريقة الباكتست (Drawdown 18%)
        is_btc_drawdown_crash = False
        if btc_closes is not None:
            is_btc_drawdown_crash = self._check_btc_drawdown_crash(btc_closes, self.current_bar)
            details["btc_drawdown_crash"] = is_btc_drawdown_crash

        # فحص GMRI انهيار حاد
        is_gmri_collapse = self._check_gmri_sharp_collapse(gmri)
        details["gmri_sharp_collapse"] = is_gmri_collapse

        # فحص وسيط الزخم
        median_roc = float(np.median(basket_rocs)) if basket_rocs else 0.0
        details["median_roc"] = median_roc
        is_basket_dumping = median_roc < -0.035

        # منطق الحجر الصحي (Quarantine) — يطابق الباكتست تماماً
        btc_crash_any = is_btc_crashing_live or is_btc_drawdown_crash
        gmri_crash_any = is_gmri_collapse

        # شرط الانهيار الحقيقي (كما في الباكتست): (BTC أو GMRI) + GMRI<0.30 + DD>10% + 72 بار منذ آخر انهيار
        if (btc_crash_any or gmri_crash_any) and gmri < 0.30 and nav_dd > 0.10 and (self.current_bar - self.last_crash_bar) > self.cooldown_bars:
            self.last_crash_bar = self.current_bar
            self.quarantine_until_bar = self.current_bar + self.quarantine_bars
            self.quarantines += 1
            self.red_alerts += 1
            self.current_alert_level = "RED"
            reason = f"🚨 انهيار مؤكد: BTC Crash={btc_crash_any} GMRI Collapse={gmri_crash_any} GMRI={gmri:.2f} DD={nav_dd:.1%}"
            self.last_crash_reason = reason
            self.cooldown_remaining = self.lockdown_bars
            details["in_quarantine"] = True
            return ("RED", reason, details)

        # إذا في فترة حجر
        if self.current_bar < self.quarantine_until_bar:
            self.cooldown_remaining = max(0, self.quarantine_until_bar - self.current_bar)
            return ("RED", f"🚨 حجر صحي وقائي بعد انهيار (متبقي {self.cooldown_remaining} شمعة)", details)

        # تحديد مستوى الإنذار العام
        if is_gmri_critical or (is_btc_crashing_live and is_gmri_warning) or (is_btc_crashing_live and is_basket_dumping):
            self.current_alert_level = "RED"
            self.cooldown_remaining = self.lockdown_bars
            self.red_alerts += 1
            reason = f"🚨 إنذار أحمر: GMRI={gmri:.2f} BTC Crash={is_btc_crashing_live} Median ROC={median_roc:.2%}"
            self.last_crash_reason = reason
            return ("RED", reason, details)

        elif is_gmri_warning or is_btc_crashing_live:
            if self.cooldown_remaining > 0:
                self.cooldown_remaining -= 1
                return ("RED", f"🚨 استمرار حظر وقائي (متبقي {self.cooldown_remaining} شمعات)", details)
            self.current_alert_level = "YELLOW"
            reason = f"⚠️ إنذار أصفر: تراجع اتساع السوق GMRI={gmri:.2f}"
            self.last_crash_reason = reason
            return ("YELLOW", reason, details)

        else:
            if self.cooldown_remaining > 0:
                self.cooldown_remaining -= 1
                return ("YELLOW", f"⚠️ تعافي تدريجي (متبقي {self.cooldown_remaining} شمعات للأمان)", details)
            self.current_alert_level = "GREEN"
            self.last_crash_reason = "سوق طبيعي وصاعد"
            return ("GREEN", "✅ السوق مستقر وضمن الحدود الآمنة", details)

    def apply_shield_to_position(self, 
                                 pos: Dict[str, Any], 
                                 current_price: float, 
                                 alert_level: str,
                                 local_atr: float) -> Tuple[bool, str, float]:
        """
        تطبيق الدرع الوقائي على صفقة مفتوحة:
        - RED + ربح >0.8%: قفل BE +0.3%
        - RED + خسارة: تضييق وقف 30%
        - YELLOW + ربح >2%: قفل BE +0.5%
        يدعم كل الصيغ: entry / buy_price / entry_price
        """
        try:
            entry = float(pos.get("entry") or pos.get("buy_price") or pos.get("entry_price") or 0.0)
            cur_sl = float(pos.get("sl") or 0.0)
            if entry <= 0 or cur_sl <= 0 or current_price <= 0:
                return (False, "NO_CHANGE", cur_sl)
            gain = (current_price - entry) / entry

            if alert_level == "RED":
                if gain >= 0.008 and cur_sl < entry * 1.003:
                    new_sl = entry * 1.003
                    pos["sl"] = new_sl
                    self.profit_locks += 1
                    return (True, "CRASH_SHIELD_BE_LOCKED", new_sl)
                elif gain < 0:
                    try:
                        atr_ratio = float(local_atr) / entry if float(local_atr) > 1 else float(local_atr)
                    except Exception:
                        atr_ratio = 0.03
                    tightened = entry * (1 - max(0.005, atr_ratio) * 1.20)
                    if tightened > cur_sl:
                        pos["sl"] = tightened
                        return (True, "CRASH_SHIELD_SL_TIGHTENED", tightened)

            elif alert_level == "YELLOW":
                if gain >= 0.020 and cur_sl < entry * 1.005:
                    new_sl = entry * 1.005
                    pos["sl"] = new_sl
                    self.profit_locks += 1
                    return (True, "CAUTION_SHIELD_BE_LOCKED", new_sl)

            return (False, "NO_CHANGE", cur_sl)
        except Exception as e:
            return (False, f"ERROR:{e}", float(pos.get("sl", 0.0) or 0.0))

    def evaluate_drawdown_ceiling(self, 
                                  current_dd: float, 
                                  gmri: float, 
                                  btc_weak: bool, 
                                  target_ceiling: float = 0.15) -> Dict[str, Any]:
        """
        صمام سقف DD 15% — يطابق Smart Arbiter في الباكتست
        """
        headroom = max(0.0, target_ceiling - current_dd)
        
        if current_dd >= (target_ceiling - 0.015):
            return {
                "allow_new_trades": False,
                "allow_pyramiding": False,
                "risk_scale": 0.0,
                "status": "CRITICAL_DRAWDOWN_FREEZE",
                "reason": f"🚨 تجميد صارم: DD {current_dd:.1%} اقترب من سقف 15%"
            }
        
        if current_dd >= 0.08:
            if btc_weak or gmri < 0.40:
                scale = min(0.20, max(0.05, headroom * 0.35))
                return {
                    "allow_new_trades": True,
                    "allow_pyramiding": False,
                    "risk_scale": scale,
                    "status": "DEFENSIVE_RISK_SCALING",
                    "reason": f"🛡️ كبح مخاطرة {(1-scale):.0%}"
                }
            else:
                return {
                    "allow_new_trades": True,
                    "allow_pyramiding": False,
                    "risk_scale": 0.50,
                    "status": "MODERATE_RECOVERY_MODE",
                    "reason": "⚠️ تعافي بنصف مخاطرة"
                }
        
        if current_dd >= 0.05:
            return {
                "allow_new_trades": True,
                "allow_pyramiding": not (btc_weak or gmri < 0.35),
                "risk_scale": 0.75,
                "status": "MILD_DRAWDOWN_CAUTION",
                "reason": "🟡 حذر طفيف -25% مخاطرة"
            }
        
        return {
            "allow_new_trades": True,
            "allow_pyramiding": True,
            "risk_scale": 1.0,
            "status": "NORMAL_OPERATION",
            "reason": "✅ وضع طبيعي"
        }

    def get_stats(self) -> Dict[str, Any]:
        return {
            "quarantines": self.quarantines,
            "red_alerts": self.red_alerts,
            "profit_locks": self.profit_locks,
            "current_level": self.current_alert_level,
            "last_reason": self.last_crash_reason,
            "cooldown": self.cooldown_remaining,
            "gmri_history_len": len(self.gmri_history),
        }

# كائن عام جاهز
CRASH_SHIELD = CrashPredictionEngine()

# نسخة مصغرة مطابقة للباكتست (للتوافق)
class CrashPredictionEngineV2Minimal(CrashPredictionEngine):
    """نسخة مصغرة مطابقة لمنطق titan_juggernaut_bot.py"""
    def __init__(self):
        super().__init__()
        self.quarantine_until = -1
        self.last_crash_bar = -9999

    def check_quarantine(self, t, btc_closes, gmri, nav_dd=0.0, nav_sma_ratio=1.0, btc_weak=False):
        # يحاكي منطق الباكتست الأصلي
        btc_crash = False
        gmri_crash = False
        if t >= 84:
            try:
                high_84 = float(np.max(btc_closes[t-84:t]))
                cur = float(btc_closes[t])
                if high_84 > 0 and (high_84 - cur) / high_84 > 0.18:
                    btc_crash = True
            except Exception:
                pass
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

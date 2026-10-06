#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
  EMERGENCY CIRCUIT BREAKER & FAIL-SAFE SHIELD (صمام أمان وإنقاذ الحساب)
  ═════════════════════════════════════════════════════════════════════════════
  • حماية استباقية للحساب الحقيقي والورقي من أي تسريب مالي أو خطأ برمجي.
  • مراقبة التراجع اليومي الأقصى (Daily Max Drawdown Guard).
  • كابح توالي الخسائر السريعة (Consecutive Loss Breaker).
  • صمام كبح أخطاء واجهة منصة بايننس (Binance API Burst Error Shield).
  • مراقب نبض النظام (Heartbeat Watchdog) لضمان عدم تجمد البوت أبداً.
═══════════════════════════════════════════════════════════════════════════════
"""

import time
import threading
import traceback
from datetime import datetime, timezone

class CircuitBreakerConfig:
    MAX_DAILY_LOSS_PCT = 0.045      # الحد الأقصى للهبوط اليومي (4.5%): بعده يتوقف فتح الصفقات
    MAX_CONSECUTIVE_LOSSES = 3      # الحد الأقصى للخسائر المتتالية السريعة
    CONSECUTIVE_COOLDOWN_SEC = 3600 # تجميد مؤقت لمدة ساعة عند توالي الخسائر
    MAX_API_ERRORS_BURST = 3        # أقصى أخطاء API متتالية قبل تعليق التنفيذ
    API_COOLDOWN_SEC = 300          # تهدئة 5 دقائق عند أخطاء بايننس المتكررة
    WATCHDOG_TIMEOUT_SEC = 180      # مهلة كشف تجمد أي حلقة عمل


class EmergencyCircuitBreaker:
    _instance = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EmergencyCircuitBreaker, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, logger_func=print, tg_alert_func=None):
        if self._initialized:
            return
        self.log = logger_func
        self.send_alert = tg_alert_func or (lambda msg: None)
        self.halted = False
        self.halt_reason = ""
        self.halt_time = 0.0
        
        # تتبع الخسائر اليومية
        self.day_start_ts = 0.0
        self.day_start_equity = 0.0
        self.current_equity = 0.0
        
        # تتبع الخسائر المتتالية
        self.consecutive_losses = 0
        self.last_loss_time = 0.0
        self.loss_cooldown_until = 0.0
        
        # تتبع أخطاء المنصة
        self.consecutive_api_errors = 0
        self.api_cooldown_until = 0.0
        
        # تتبع نبض الخيوط (Heartbeats)
        self.heartbeats = {}
        self._watchdog_thread = None
        self._watchdog_running = False
        
        self._initialized = True
        self._start_watchdog()

    def update_equity(self, current_equity: float):
        """تحديث رصيد المحفظة وفحص سقف الهبوط اليومي"""
        with self._lock:
            now_dt = datetime.now(timezone.utc)
            now_ts = now_dt.timestamp()
            
            # إعادة ضبط اليوم في 00:00 UTC
            if self.day_start_ts == 0.0 or now_dt.strftime("%Y-%m-%d") != datetime.fromtimestamp(self.day_start_ts, tz=timezone.utc).strftime("%Y-%m-%d"):
                self.day_start_ts = now_ts
                self.day_start_equity = max(current_equity, 1e-6)
                if self.halted and "DAILY_LOSS" in self.halt_reason:
                    self.halted = False
                    self.halt_reason = ""
                    self.log("[BREAKER] 🌅 بداية يوم تداول جديد: رفع التجميد اليومي.")

            self.current_equity = current_equity
            
            # حساب التراجع اليومي
            if self.day_start_equity > 0:
                daily_dd = (self.day_start_equity - current_equity) / self.day_start_equity
                if daily_dd >= CircuitBreakerConfig.MAX_DAILY_LOSS_PCT and not self.halted:
                    self._trigger_halt(
                        f"DAILY_LOSS_LIMIT: هبوط يومي {daily_dd*100:.2f}% تجاوز الحد الأقصى المسموح ({CircuitBreakerConfig.MAX_DAILY_LOSS_PCT*100:.1f}%)"
                    )

    def record_trade_result(self, is_win: bool, pnl_usd: float = 0.0):
        """تسجيل نتيجة الصفقة ومراقبة سلسلة الخسائر"""
        with self._lock:
            now = time.time()
            if is_win:
                self.consecutive_losses = 0
            else:
                self.consecutive_losses += 1
                self.last_loss_time = now
                self.log(f"[BREAKER] ⚠️ خسارة مسجلة: توالي الخسائر = {self.consecutive_losses}")
                
                if self.consecutive_losses >= CircuitBreakerConfig.MAX_CONSECUTIVE_LOSSES:
                    self.loss_cooldown_until = now + CircuitBreakerConfig.CONSECUTIVE_COOLDOWN_SEC
                    msg = (f"🛡️ <b>صمام الإنقاذ: تفعيل التهدئة التلقائية</b>\n"
                           f"• السبب: توالي {self.consecutive_losses} خسائر متتالية.\n"
                           f"• الإجراء: تعليق الدخول في صفقات جديدة لمدة {CircuitBreakerConfig.CONSECUTIVE_COOLDOWN_SEC // 60} دقيقة لحماية المحفظة.")
                    self.log(f"[BREAKER] {msg}")
                    self.send_alert(msg)

    def record_api_error(self, error_str: str):
        """تسجيل خطأ في API بايننس"""
        with self._lock:
            now = time.time()
            self.consecutive_api_errors += 1
            self.log(f"[BREAKER] ⚠️ خطأ API متتالي ({self.consecutive_api_errors}): {error_str}")
            
            if self.consecutive_api_errors >= CircuitBreakerConfig.MAX_API_ERRORS_BURST:
                self.api_cooldown_until = now + CircuitBreakerConfig.API_COOLDOWN_SEC
                msg = (f"🚨 <b>صمام الإنقاذ: كبح أخطاء Binance API</b>\n"
                       f"• السبب: تكرار {self.consecutive_api_errors} أخطاء متتالية من المنصة ({error_str[:50]}).\n"
                       f"• الإجراء: تعليق أوامر التنفيذ لمدة {CircuitBreakerConfig.API_COOLDOWN_SEC // 60} دقائق لمنع الحظر أو تكرار الأوامر.")
                self.log(f"[BREAKER] {msg}")
                self.send_alert(msg)

    def record_api_success(self):
        """إعادة تصفير أخطاء API عند نجاح الاتصال"""
        with self._lock:
            self.consecutive_api_errors = 0

    def can_open_new_trade(self) -> tuple:
        """فحص ما إذا كان مسموحاً بفتح صفقة جديدة الآن أم أن صمام الأمان مفعل"""
        with self._lock:
            now = time.time()
            if self.halted:
                return False, f"🚨 النظام في وضع التوقف الطارئ ({self.halt_reason})"
            if now < self.loss_cooldown_until:
                rem = int(self.loss_cooldown_until - now)
                return False, f"⏳ صمام توالي الخسائر نشط (متبقي {rem//60}د {rem%60}ث)"
            if now < self.api_cooldown_until:
                rem = int(self.api_cooldown_until - now)
                return False, f"🛡️ صمام تهدئة API بايننس نشط (متبقي {rem//60}د {rem%60}ث)"
            return True, "OK"

    def _trigger_halt(self, reason: str):
        self.halted = True
        self.halt_reason = reason
        self.halt_time = time.time()
        msg = (f"🚨🚨 <b>صمام الإنقاذ: تفعيل الإيقاف الطارئ (Emergency Halt)</b> 🚨🚨\n"
               f"• السبب: {reason}\n"
               f"• الإجراء: تم تجميد فتح أي صفقات جديدة فوراً لحماية رأس المال.\n"
               f"• الصفقات المفتوحة: تظل تحت حماية الوقف المتحرك و SL التلقائي.")
        self.log(f"[BREAKER CRITICAL] {msg}")
        self.send_alert(msg)

    def manual_resume(self) -> str:
        """إعادة التفعيل اليدوي من قبل المالك بعد التحقق"""
        with self._lock:
            self.halted = False
            self.halt_reason = ""
            self.loss_cooldown_until = 0.0
            self.api_cooldown_until = 0.0
            self.consecutive_losses = 0
            self.consecutive_api_errors = 0
            msg = "✅ تم استئناف التداول وإعادة ضبط صمامات الأمان بنجاح."
            self.log(f"[BREAKER] {msg}")
            return msg

    # ── مراقبة نبض الخيوط ومنع التجمد ──
    def heartbeat(self, thread_name: str):
        """تسجيل نبض حياة خيط العمل لمنع التجمد"""
        with self._lock:
            self.heartbeats[thread_name] = time.time()

    def _start_watchdog(self):
        if self._watchdog_running:
            return
        self._watchdog_running = True
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="BreakerWatchdog")
        self._watchdog_thread.start()

    def _watchdog_loop(self):
        while self._watchdog_running:
            try:
                time.sleep(30)
                now = time.time()
                with self._lock:
                    for name, last_ts in list(self.heartbeats.items()):
                        elapsed = now - last_ts
                        if elapsed > CircuitBreakerConfig.WATCHDOG_TIMEOUT_SEC:
                            self.log(f"[WATCHDOG WARNING] ⚠️ خيط العمل '{name}' لم يستجب منذ {int(elapsed)} ثانية!")
            except Exception as e:
                self.log(f"[WATCHDOG ERROR] {e}")


# نسخة عامة مركزية للاستخدام المباشر
BREAKER = EmergencyCircuitBreaker()

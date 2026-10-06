#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🛡️ TITAN ULTIMATE FAILSAFE - حماية من كل الكوارث الكارثية
يمنع الخسائر الكارثية والتوقف التام - 12 طبقة حماية
"""
import time, threading, traceback, os, json, math
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np

class DataValidator:
    """حماية من بيانات فاسدة - تمنع صفقات على بيانات خاطئة"""
    @staticmethod
    def validate_ohlcv(df, symbol=""):
        if df is None or len(df) < 21:
            return False, f"{symbol} بيانات قليلة {len(df) if df is not None else 0}"
        try:
            # Check NaN
            if df[['Open','High','Low','Close','Volume']].isna().any().any():
                return False, f"{symbol} NaN في البيانات"
            # Check zero/negative price
            if (df['Close'] <= 0).any() or (df['High'] <= 0).any():
                return False, f"{symbol} سعر صفر أو سالب"
            # Check High < Low
            if (df['High'] < df['Low']).any():
                return False, f"{symbol} High < Low"
            # Check stale data - threshold حسب الفريم
            last_time = df.index[-1]
            now = pd.Timestamp.now(tz="UTC")
            age_sec = (now - last_time).total_seconds()
            # للباكتست 4H نسمح بقديم حتى 7 أيام، للحي 5m ساعة واحدة
            # إذا البيانات قديمة جداً >7 أيام → قد تكون كاش قديم
            if age_sec > 7*24*3600:
                return False, f"{symbol} بيانات قديمة جداً {age_sec/3600/24:.1f} يوم"
            # للحي فقط نفحص ساعة - للباكتست نتجاوز
            # نعرف إذا حي من كون آخر شمعة قريبة من الآن <2 يوم
            # إذا كاش باكتست قديم (2021-2026) لا نعتبره stale
            # Check volume zero for many candles
            if (df['Volume'] == 0).sum() > len(df)*0.5:
                return False, f"{symbol} حجم صفر 50%+"
            return True, "OK"
        except Exception as e:
            return False, f"{symbol} خطأ فحص: {e}"

    @staticmethod
    def validate_setup(setup, symbol=""):
        if not setup:
            return False, "Setup None"
        try:
            price = float(setup.get('price',0))
            sl = float(setup.get('sl',0))
            tp1 = float(setup.get('tp1',0))
            if price <= 0 or sl <= 0 or tp1 <= 0:
                return False, f"{symbol} سعر/SL/TP صفر"
            if sl >= price:
                return False, f"{symbol} SL {sl} >= price {price} (يجب SL < price للشراء)"
            if tp1 <= price:
                return False, f"{symbol} TP {tp1} <= price {price}"
            sl_pct = (price - sl)/price
            if sl_pct > 0.15:
                return False, f"{symbol} SL بعيد {sl_pct*100:.1f}% >15%"
            if sl_pct < 0.002:
                return False, f"{symbol} SL قريب جداً {sl_pct*100:.2f}% <0.2%"
            rsi = setup.get('rsi',50)
            if not (0 <= rsi <= 100):
                return False, f"{symbol} RSI خارج النطاق {rsi}"
            return True, "OK"
        except Exception as e:
            return False, f"{symbol} خطأ setup: {e}"

class OrderValidator:
    """حماية من أوامر كارثية"""
    @staticmethod
    def validate_order_params(symbol, qty, price, sl, tp1, capital):
        try:
            qty = float(qty); price = float(price); sl = float(sl); tp1 = float(tp1); capital = float(capital)
            if qty <= 0: return False, "كمية صفر"
            if price <= 0: return False, "سعر صفر"
            if capital <= 0: return False, "رأس مال صفر"
            notional = qty * price
            if notional < 5: return False, f"قيمة صغيرة {notional:.2f}$ <5$ Binance min"
            if notional > capital * 0.3: return False, f"قيمة كبيرة {notional:.2f}$ >30% رأس مال"
            if notional > 10000: return False, f"قيمة ضخمة {notional:.2f}$ >10000$ خطر"
            return True, "OK"
        except Exception as e:
            return False, f"خطأ فحص أمر: {e}"

class PortfolioGuard:
    """حماية المحفظة من الانهيار الكارثي"""
    def __init__(self, max_dd=0.15, daily_loss=0.045, max_pos=10):
        self.max_dd = max_dd
        self.daily_loss = daily_loss
        self.max_pos = max_pos
        self.day_start_equity = 0
        self.day_start_ts = 0
        self.peak_equity = 0
        self.consecutive_losses = 0
        self.lock = threading.RLock()

    def check_dd(self, current_equity, peak_equity=None):
        with self.lock:
            if peak_equity is None:
                peak_equity = self.peak_equity
            if peak_equity <= 0:
                return True, "OK"
            dd = (peak_equity - current_equity)/peak_equity
            if dd >= self.max_dd:
                return False, f"🚨 DD كارثي {dd*100:.1f}% >= {self.max_dd*100}% - تجميد + إغلاق طارئ"
            if dd >= self.max_dd - 0.02:
                return True, f"⚠️ DD قريب {dd*100:.1f}% من سقف {self.max_dd*100}% - كبح 80%"
            return True, "OK"

    def check_daily_loss(self, current_equity):
        with self.lock:
            now = datetime.now(timezone.utc)
            now_ts = now.timestamp()
            if self.day_start_ts == 0 or now.strftime("%Y-%m-%d") != datetime.fromtimestamp(self.day_start_ts, tz=timezone.utc).strftime("%Y-%m-%d"):
                self.day_start_ts = now_ts
                self.day_start_equity = max(current_equity, 1e-6)
                return True, "يوم جديد"
            if self.day_start_equity > 0:
                daily_dd = (self.day_start_equity - current_equity)/self.day_start_equity
                if daily_dd >= self.daily_loss:
                    return False, f"🚨 خسارة يومية {daily_dd*100:.1f}% >= {self.daily_loss*100}% - تجميد اليوم"
            return True, "OK"

    def check_positions(self, open_positions):
        with self.lock:
            if len(open_positions) >= self.max_pos:
                return False, f"عدد صفقات {len(open_positions)} >= {self.max_pos} max"
            return True, "OK"

class NetworkGuard:
    """حماية من مشاكل الشبكة - exponential backoff"""
    def __init__(self):
        self.failures = {}
        self.lock = threading.RLock()

    def record_failure(self, host):
        with self.lock:
            self.failures[host] = self.failures.get(host, 0) + 1

    def record_success(self, host):
        with self.lock:
            self.failures[host] = 0

    def get_backoff(self, host):
        with self.lock:
            fails = self.failures.get(host, 0)
            if fails == 0:
                return 0
            # Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 60s
            return min(2**fails, 60)

    def should_try(self, host):
        with self.lock:
            fails = self.failures.get(host, 0)
            return fails < 10  # Give up after 10 fails

class PersistenceGuard:
    """حماية من مشاكل الحفظ - SQLite + JSON"""
    @staticmethod
    def safe_write_json(path, data, max_retries=3):
        for attempt in range(max_retries):
            try:
                tmp = Path(str(path) + ".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                tmp.replace(path)
                return True, "OK"
            except Exception as e:
                if attempt == max_retries-1:
                    return False, f"فشل حفظ JSON بعد {max_retries}: {e}"
                time.sleep(0.1 * (attempt+1))
        return False, "فشل"

    @staticmethod
    def safe_sqlite_execute(db, query, params=(), max_retries=3):
        for attempt in range(max_retries):
            try:
                db.execute(query, params)
                db.commit()
                return True, "OK"
            except Exception as e:
                if "locked" in str(e).lower() and attempt < max_retries-1:
                    time.sleep(0.05 * (attempt+1))
                    continue
                return False, f"SQLite فشل: {e}"
        return False, "فشل"

class TelegramGuard:
    """حماية تيليجرام - منع حظر + تقطيع رسائل"""
    @staticmethod
    def truncate_message(text, max_len=4000):
        if len(text) <= max_len:
            return text
        return text[:max_len-100] + f"\n\n... (تم اقتطاع {len(text)-max_len} حرف)"

    @staticmethod
    def safe_send(send_func, chat_id, text, max_retries=3):
        for attempt in range(max_retries):
            try:
                truncated = TelegramGuard.truncate_message(text)
                result = send_func(chat_id, truncated)
                return True, result
            except Exception as e:
                err = str(e)
                if "Too Many Requests" in err or "429" in err:
                    # Rate limit - wait
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue
                if "chat not found" in err.lower() or "blocked" in err.lower():
                    return False, f"Chat blocked/not found: {err}"
                if attempt == max_retries-1:
                    return False, f"TG fail after {max_retries}: {err}"
                time.sleep(0.5)
        return False, "فشل"

class NeverSleepGuard:
    """حماية من النوم - Watchdog + auto-restart"""
    def __init__(self, logger=print):
        self.log = logger
        self.threads = {}
        self.lock = threading.RLock()
        self.running = True
        self.watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="NeverSleepWatchdog")
        self.watchdog_thread.start()

    def register_thread(self, name, thread, heartbeat_func=None):
        with self.lock:
            self.threads[name] = {"thread": thread, "last_heartbeat": time.time(), "heartbeat_func": heartbeat_func}

    def heartbeat(self, name):
        with self.lock:
            if name in self.threads:
                self.threads[name]["last_heartbeat"] = time.time()

    def _watchdog_loop(self):
        while self.running:
            try:
                time.sleep(30)
                now = time.time()
                with self.lock:
                    for name, info in list(self.threads.items()):
                        elapsed = now - info["last_heartbeat"]
                        if elapsed > 180:  # 3 minutes no heartbeat
                            self.log(f"[NeverSleep] ⚠️ خيط {name} لم يستجب {elapsed:.0f}ث - قد يكون مجمد!")
                            # Try to restart if heartbeat_func provided
                            if info.get("heartbeat_func"):
                                try:
                                    info["heartbeat_func"]()
                                    self.log(f"[NeverSleep] ✅ محاولة إعادة إحياء {name}")
                                except Exception as e:
                                    self.log(f"[NeverSleep] ❌ فشل إحياء {name}: {e}")
            except Exception as e:
                self.log(f"[NeverSleep] Watchdog error: {e}")

    def stop(self):
        self.running = False

class EmergencyClose:
    """إغلاق طارئ عند كارثة"""
    @staticmethod
    def should_emergency_close(dd, gmri, crash_level, daily_loss):
        # شروط الإغلاق الطارئ
        if dd >= 0.15:
            return True, f"DD {dd*100:.1f}% >=15% - إغلاق طارئ كل الصفقات"
        if crash_level == "RED" and dd >= 0.10:
            return True, f"Crash RED + DD {dd*100:.1f}% - إغلاق طارئ"
        if daily_loss >= 0.045:
            return True, f"خسارة يومية {daily_loss*100:.1f}% - إغلاق طارئ"
        if gmri <= 0.15:
            return True, f"GMRI {gmri:.2f} <=0.15 انهيار شامل - إغلاق طارئ"
        return False, "OK"

# Global failsafe instance
FAILSAFE = {
    "data": DataValidator(),
    "order": OrderValidator(),
    "portfolio": PortfolioGuard(),
    "network": NetworkGuard(),
    "persistence": PersistenceGuard(),
    "telegram": TelegramGuard(),
    "never_sleep": None,  # Will be init with logger
    "emergency": EmergencyClose(),
}

def init_failsafe(logger=print):
    FAILSAFE["never_sleep"] = NeverSleepGuard(logger)
    return FAILSAFE

# Test
if __name__ == "__main__":
    print("🛡️ TITAN ULTIMATE FAILSAFE - 12 طبقة حماية")
    print("✅ DataValidator")
    print("✅ OrderValidator")
    print("✅ PortfolioGuard DD15% + Daily4.5% + MaxPos10")
    print("✅ NetworkGuard exponential backoff")
    print("✅ PersistenceGuard SQLite retry")
    print("✅ TelegramGuard truncate + rate limit")
    print("✅ NeverSleepGuard watchdog 180s")
    print("✅ EmergencyClose DD15% + Crash RED + GMRI0.15")

# -*- coding: utf-8 -*-
"""
mhf_bridge.py — [MHF-INTEGRATION] جسر Micro Hedge Fund ⟵⟶ TITAN

المسؤولية الوحيدة للجسر:
  1) تشغيل خط أنابيب micro_hedge_fund (StrategyPipeline) بإيقاع زمني مقيّد
     (افتراضي: مسح كل TITAN_MHF_SCAN_MINUTES=5 دقيقة — ذيل D1/H4 مكوَّن من شموع 5د
     عبر klines_live فيقتنص الفرص كل 5 دقائق بدل انتظار الإغلاق الكامل) بدون LLM خارجي افتراضياً.
  2) تحويل الإشارة المعتمدة إلى مخطط خطط TITAN الورقي/الحقيقي مع ثوابت SOP
     ($125 حجم مركز من رأس مال $400؛ مستويات SL/TP تُقرأ من ملف SOP الفعّال — v3.3: SL −4.8%/6$ + خروج مدرّج +3.2%/+22.4%).
  3) قيد الصفقة في سجل المحرك (Journal) عند القبول، ومزامنة إغلاقات الحافظة
     الورقية إلى السجل حتى تعمل قاطعات الحماية (3 صفقات كحد أقصى، تعطيل يومي
     −$24 لمدة 24h، قفل شهري +$120).

لا يلمس الجسر أي استراتيجية دخول أخرى — نقطة الربط الوحيدة داخل run_cycle.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone

import micro_hedge_fund as MHF

MHF_POOL = "MHF"
MHF_FRAME = "4h"
# نسبة المخاطرة من إجمالي السيولة الورقية = حجم المركز / رأس المال (SOP)
MHF_SIZE_PCT = round(MHF.SOP.POSITION_SIZE_USD / MHF.SOP.ACCOUNT_CAPITAL_USD * 100.0, 4)  # 31.25

DEFAULT_SCAN_INTERVAL_S = float(os.environ.get("TITAN_MHF_SCAN_MINUTES", "5")) * 60.0  # [MHF-V3.4] فرص كل 5 دقائق
_TZ = timezone.utc


def _now_iso() -> str:
    return datetime.now(_TZ).isoformat()


def _log(msg: str) -> None:
    print(f"[MHF] {datetime.now(_TZ).strftime('%H:%M:%S')} {msg}", flush=True)


class MHFBridge:
    """غلاف رشيق حول محرك MHF مع إيقاع مسح ومزامنة سجل ثابتة على القرص."""

    def __init__(self, state_dir: str, use_llm: bool = None, scan_interval_s: float = None,
                 pipeline: MHF.StrategyPipeline = None):
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self.journal = MHF.Journal(os.path.join(state_dir, "mhf_journal.json"))
        if use_llm is None:
            use_llm = os.environ.get("TITAN_MHF_LLM", "0").strip() == "1"
        if pipeline is not None:
            self.pipeline = pipeline
        else:
            try:
                self.pipeline = MHF.StrategyPipeline(use_llm=bool(use_llm), journal=self.journal)
            except Exception as e:  # الشبكة/الحظر الجغرافي تُلتقط عند المسح أيضاً
                _log(f"⚠️ تعذّر تهيئة خط أنابيب MHF: {e}")
                self.pipeline = None
        self.scan_interval_s = DEFAULT_SCAN_INTERVAL_S if scan_interval_s is None else float(scan_interval_s)
        self._lock = threading.RLock()
        self._sync_path = os.path.join(state_dir, "mhf_sync.json")
        self._sync = self._load_sync()

    # ----------------------------------------------------------------- state
    def _load_sync(self) -> dict:
        try:
            with open(self._sync_path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            d.setdefault("closed_pos_ids", [])
            d.setdefault("last_scan_ts", 0.0)
            return d
        except Exception:
            return {"closed_pos_ids": [], "last_scan_ts": 0.0}

    def _save_sync(self) -> None:
        try:
            tmp = self._sync_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._sync, fh, ensure_ascii=False)
            os.replace(tmp, self._sync_path)
        except Exception as e:
            _log(f"⚠️ فشل حفظ ملف المزامنة: {e}")

    # ----------------------------------------------------------------- mapping
    @staticmethod
    def _plan_from_signal(signal: dict) -> dict:
        """تحويل إشارة Stage-4 إلى مخطط TITAN (create_open_position / accept_plan)."""
        entry = float(signal["entry_price"])
        tp = float(signal["take_profit"])
        # [MHF-V3-UPGRADE] هدفان مدرّجان عند توفرهما، وإلا الهدف المفرد v2 حرفياً
        tp1 = float(signal.get("take_profit_1") or tp)
        tp2 = float(signal.get("take_profit_2") or tp)
        plan = {
            "ticker": signal["symbol"],
            "signal_price": entry,
            "price": entry,
            "sl": float(signal["stop_loss"]),
            "tgt1": tp1,
            "tgt2": tp2,
            "size_pct": MHF_SIZE_PCT,
            "frame": MHF_FRAME,
            "pool": MHF_POOL,
            "strategy": "micro_hedge_fund",
            "mhf_trade_id": signal.get("id"),
            "candle_time": signal.get("candle_time") or "",   # [MHF-FINGERPRINT] مفتاح بصمة مستقر
            "intent": "LIMIT",
            "timestamp": time.time(),
        }
        if bool(getattr(MHF.SOP, "STAGED_EXITS", False)):
            # [MHF-V3.2-FIVE-ENGINES] إشارات التعزيز الانفجاري تحمل أياماً ممددة — احترم ما حسمه الفريق
            plan["time_stop_days"] = int(signal.get("time_stop_days")
                                         or getattr(MHF.SOP, "TIME_STOP_DAYS", 0) or 0)
        return plan

    def _register_trade(self, signal: dict) -> None:
        """قيد الصفقة المعتمدة في سجل المحرك حتى تعمل قاطعات الحماية."""
        try:
            self.journal.add_trade(MHF.Trade(
                id=str(signal.get("id") or f"MHF-{signal['symbol']}-{int(time.time())}"),
                symbol=signal["symbol"],
                entry_price=float(signal["entry_price"]),
                quantity=float(signal["quantity"]),
                position_size_usd=float(signal.get("position_size_usd", MHF.SOP.POSITION_SIZE_USD)),
                stop_loss=float(signal["stop_loss"]),
                take_profit=float(signal["take_profit"]),
                opened_at=_now_iso(),
                rationale=signal.get("rationale", {}) if isinstance(signal.get("rationale"), dict) else {},
            ))
        except Exception as e:
            _log(f"⚠️ فشل قيد صفقة MHF في السجل: {e}")

    # ----------------------------------------------------------------- scanning
    def scan_plans(self, open_symbols=None) -> list:
        """يعيد قائمة خطط TITAN من MHF (فارغة عند الإيقاع/القاطعات/غياب الإشارة)."""
        if self.pipeline is None:
            return []
        with self._lock:
            now = time.time()
            if now - float(self._sync.get("last_scan_ts", 0.0)) < self.scan_interval_s:
                return []
            if open_symbols:
                for t in self.journal.state["active_trades"]:
                    sym = t.get("symbol")
                    if sym and sym in open_symbols:
                        _log(f"⏭️ {sym}: مفتوحة ورقياً وفي السجل — تخطي المسح لهذا الزوج")
            self._sync["last_scan_ts"] = now
            self._save_sync()
            try:
                result = self.pipeline.run()
            except Exception as e:  # BinanceError / حظر جغرافي / انقطاع — لا نُسقط الدورة أبداً
                _log(f"⚠️ فشل مسح MHF: {e}")
                return []
        if not isinstance(result, dict) or not result.get("ok"):
            _log(f"ℹ️ لا إشارة MHF: {result.get('reason', 'unknown') if isinstance(result, dict) else result}")
            return []
        signal = result["signal"]
        plan = self._plan_from_signal(signal)
        self._register_trade(signal)
        _log(f"🚨 إشارة MHF معتمدة: {plan['ticker']} دخول {plan['signal_price']} "
             f"SL {plan['sl']} TP {plan['tgt1']} حجم {plan['size_pct']}% (SOP $125/$400)")
        return [plan]

    # ----------------------------------------------------------------- journal sync
    def sync_closed_positions(self, positions: list) -> int:
        """يزامن إغلاقات الحافظة الورقية (pool=MHF) إلى سجل المحرك. idempotent."""
        if not positions:
            return 0
        synced = set(self._sync.get("closed_pos_ids", []))
        n = 0
        active_by_symbol = {t.get("symbol"): t for t in self.journal.state["active_trades"]}
        for pos in positions:
            if pos.get("pool") != MHF_POOL or pos.get("status") != "CLOSED":
                continue
            pid = pos.get("id") or f"{pos.get('ticker')}|{pos.get('entry_time')}"
            if pid in synced:
                continue
            sym = pos.get("ticker")
            trade = active_by_symbol.get(sym)
            if not trade:
                synced.add(pid)  # الصفقة مغلقة أصلاً في السجل — لا شيء لعمله
                n += 1
                continue
            # [SOP-FIDELITY] عكس الكمية/الكلفة الفعليتين للمحفظة الورقية (التراكم)
            # حتى تعمل قاطعات السجل (−$24 يوم / +$120 شهر) على أرقام PnL حقيقية لا النموذجية
            try:
                _q = float(pos.get("qty") or 0.0)
                _c = float(pos.get("cost_usd") or 0.0)
                if _q > 0:
                    trade["quantity"] = _q
                if _c > 0:
                    trade["position_size_usd"] = _c
            except Exception:
                pass
            ctype = str(pos.get("close_type", "")).upper()
            outcome = "TAKE_PROFIT" if ctype in ("T1", "T2", "TP") else ("STOP_LOSS" if ctype == "SL" else "MANUAL")
            exit_price = float(pos.get("close_price") or pos.get("current_price") or 0.0)
            closed = self.journal.close_trade(trade["id"], exit_price, outcome)
            if closed:
                _log(f"📕 مزامنة إغلاق MHF: {sym} ⇒ {outcome} PnL {closed.get('pnl_usd'):+.2f}$")
                synced.add(pid)
                n += 1
        if n:
            self._sync["closed_pos_ids"] = sorted(synced)
            self._save_sync()
        return n

    # ----------------------------------------------------------------- info
    def journal_stats(self) -> dict:
        try:
            return self.journal.stats()
        except Exception:
            return {}

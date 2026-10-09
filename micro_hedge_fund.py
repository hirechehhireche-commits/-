#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 MICRO HEDGE FUND — COMPLETE TRADING STRATEGY ENGINE (single file, zero deps)
================================================================================

 الاستراتيجية الكاملة لصندوق التحوّط المصغّر — ملف واحد مستقل بدون أي مكتبات خارجية

 This file is a FULL, self-contained Python port of the strategy implemented by
 the Node.js Telegram bot. It contains:

   1. The Financial SOP ("The Constitution")      -> class SOP
   2. The hardcoded whitelist (89 USDT pairs)     -> WHITELIST
   3. Pure-python indicators (EMA/RSI/ATR/volume) -> class Indicators
   4. Binance Spot public REST client (urllib)    -> class BinanceClient
   5. Stage 1: Narrative Agent                    -> class NarrativeAgent
   6. Stage 2: On-Chain & Liquidity Agent         -> class OnChainAgent
   7. Stage 3: Technical Analyst Agent            -> class TechnicalAgent
   8. Stage 4: Risk Manager (deterministic)       -> class RiskManager
   9. Circuit breakers + JSON journal             -> class Journal
  10. Full pipeline orchestrator                  -> class StrategyPipeline
  11. Historical backtester of the exact rules    -> class Backtester
  12. Optional keyless LLM layer (Pollinations)   -> class KeylessLLM

 DEPENDENCIES: none. Standard library only (urllib, json, math, statistics...).
 PYTHON: 3.9+

 USAGE
 -----
   python3 strategy.py --selftest             # verify SOP math + indicators offline
   python3 strategy.py --levels 100           # print SL/TP/qty for an entry price
   python3 strategy.py --scan                 # run the live 4-stage pipeline
   python3 strategy.py --scan --no-llm        # pipeline using deterministic rules only
   python3 strategy.py --backtest SOLUSDT     # backtest the exact SOP on history
   python3 strategy.py --backtest-all         # backtest the whole whitelist
   python3 strategy.py --explain              # print the strategy as readable text

 NOTE: Binance geo-blocks some IPs. If you get a "restricted location" error,
 run from an allowed IP/VPN. All offline commands still work anywhere.
================================================================================
"""

from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ==============================================================================
# SECTION 1 — THE FINANCIAL SOP (THE CONSTITUTION)
# ==============================================================================


class SOP:
    """Immutable financial rules. Nothing in this engine may violate these."""

    # --- Capital & sizing -----------------------------------------------------
    ACCOUNT_CAPITAL_USD: float = 400.0
    POSITION_SIZE_USD: float = 125.0          # ~31.25% of capital
    MAX_RISK_PER_TRADE_USD: float = 8.0       # exactly 2% of capital
    TARGET_PROFIT_PER_TRADE_USD: float = 24.0 # exactly 1:3 R/R
    RISK_REWARD_RATIO: int = 3
    MAX_OPEN_POSITIONS: int = 3

    # --- Targets --------------------------------------------------------------
    DAILY_TARGET_USD: float = 4.0             # +1%
    MONTHLY_TARGET_USD: float = 120.0         # +30%

    # --- Circuit breakers -----------------------------------------------------
    DAILY_LOSS_CUTOFF_USD: float = 24.0       # -6% -> halt 24h
    DAILY_HALT_SECONDS: int = 24 * 60 * 60

    # --- Stage 2 thresholds (liquidity / flow) --------------------------------
    MIN_24H_QUOTE_VOLUME_USD: float = 50_000_000.0
    VOLUME_SURGE_RATIO: float = 1.5           # >150% of the 30d average
    MIN_ORDERBOOK_DEPTH_USD: float = 50_000.0 # combined depth within 1% of mid
    MAX_SPREAD_PCT: float = 0.2

    # --- Stage 3 thresholds (technical) ---------------------------------------
    RSI_PERIOD: int = 14
    EMA_FAST: int = 20
    EMA_SLOW: int = 50
    RSI_MIN: float = 35.0
    RSI_MAX: float = 65.0
    D1_RSI_OVERBOUGHT: float = 75.0
    BREAKOUT_LOOKBACK: int = 20
    MAX_CONSOLIDATION_RANGE_PCT: float = 12.0
    BREAKOUT_MIN_VOLUME_RATIO: float = 1.2

    # --- Stage 1 ---------------------------------------------------------------
    NARRATIVE_SHORTLIST_SIZE: int = 5
    NARRATIVE_MAX_WEEKLY_PCT: float = 40.0    # reject parabolic
    NARRATIVE_MIN_WEEKLY_PCT: float = -15.0   # reject falling knife

    # --- Timeframes -------------------------------------------------------------
    TF_D1: str = "1d"
    TF_H4: str = "4h"
    KLINE_LIMIT: int = 200

    # --- Derived --------------------------------------------------------------
    @classmethod
    def stop_loss_pct(cls) -> float:
        """Stop distance as a percentage, e.g. -6.4."""
        return -(cls.MAX_RISK_PER_TRADE_USD / cls.POSITION_SIZE_USD) * 100.0

    @classmethod
    def take_profit_pct(cls) -> float:
        """Target distance as a percentage, e.g. +19.2."""
        return (cls.TARGET_PROFIT_PER_TRADE_USD / cls.POSITION_SIZE_USD) * 100.0


# =============================================================================
# SOP PROFILE v3 — [MHF-V3-UPGRADE] خروج مدرّج 1R/2R + قواعد جودة أشد + قفل 40%
# MHF_SOP_PROFILE=v2 يرجّع الدستور الأصلي حرفياً (رجوع فوري، لا مساس بسطر واحد من v2)
# =============================================================================

def _apply_sop_profile() -> str:
    profile = os.getenv("MHF_SOP_PROFILE", "v3").strip().lower()
    if profile == "v3":
        # الخروج المدرّج — القيم مختارَة عبر باكتست M0 فعلي على 90 زوجاً/167يوماً:
        # نصف الكمية عند +0.5R (تأمين مبكر) والوقف للتعادل، والمتبقي نحو +3.5R
        SOP.STAGED_EXITS = True
        SOP.STAGE1_TP_PCT = 3.2          # +0.5R على نصف الكمية  [M0-ITER]
        SOP.STAGE2_TP_PCT = 22.4         # +3.5R على المتبقي     [M0-ITER] (الهضبة 22.4–25.6)
        SOP.TIME_STOP_DAYS = 3           # خروج زمني مبكر — أفضل محفز مقيس [M0-ITER]
        # قفل الشهر: الهدف الموجّه للمستخدم +40% على رأس 400$ (مؤشر أداء وليس وعداً)
        SOP.MONTHLY_TARGET_USD = 160.0
        # قواعد جودة أشد (مستنتجة من الفشل المقيس 23.3% نجاح في v2)
        SOP.MIN_24H_QUOTE_VOLUME_USD = 75_000_000.0
        SOP.VOLUME_SURGE_RATIO = 1.8
        SOP.MAX_CONSOLIDATION_RANGE_PCT = 8.0
        SOP.BREAKOUT_MIN_VOLUME_RATIO = 1.5
        SOP.RSI_MIN, SOP.RSI_MAX = 40.0, 60.0
        # عائلة الإعداد الثانية: تراجع صحي مع الاتجاه — نطاق 35-45 وعمق 3-15% [M0-ITER]
        SOP.PULLBACK_RSI_LOW, SOP.PULLBACK_RSI_HIGH = 35.0, 45.0
        SOP.PULLBACK_MIN_DEPTH_PCT, SOP.PULLBACK_MAX_DEPTH_PCT = 3.0, 15.0
        # بوابة نظام السوق: لا دخول وBTC يومياً هابط
        SOP.BTC_REGIME_GATE = True
        # [MHF-V3.1-CRASH-SENTINEL] محرك التنبؤ بالانهيارات — عتبة مشتقة قياسياً من تجميع الخسائر
        SOP.CRASH_SENTINEL = True
        SOP.CRASH_BTC_RET3_THRESHOLD = -3.5   # قمّة مقيسة على هضبة −2.5..−3.5 (+$371..445) — تهيمن −3.0 بكل المحاور
        # [M11-STOPWIDTH-MEASURED] وقف أضيق مقيس بثلاثة محركات مستقلة: offline +$368.61 (+47)،
        # طيات OOS أقوى بلا انقلاب (−$185.1/+102.7/+460.8)، ومحفظة حقيقية +$74.51 مقابل +$47.98 (+55%).
        # عدم الرتابة عند 7$ موثقة (+$312) — نطاق ضجيج موجود ⟵ اعتماد البطل المقيس بلا مبالغة
        SOP.MAX_RISK_PER_TRADE_USD = 6.0
        # [MHF-V3.2-FIVE-ENGINES] محركات إلغاء التحفظات الخمسة — افتراضيات «متوسطة متحفظة محايدة» حيث لا قياس
        SOP.SIM_FEES = True
        SOP.SIM_FEE_PCT = 0.1            # عمولة لكل طرف (افتراضي متحفظ صريح)
        SOP.SIM_SLIPPAGE_PCT = 0.05      # انزلاق لكل طرف (افتراضي متحفظ صريح)
        SOP.MOONSHOT_SENTINEL = True
        SOP.MOONSHOT_BTC_RET3_THRESHOLD = 3.0   # مرآة عتبة الانهيار: نظام الانفجار الجامع للرابحين
        SOP.MOONSHOT_TSTOP_MULT = 2.0           # مضاعف التمديد (افتراض وسط — مصدره أفضل نقطة في المسح لكل-صفقة)
        # [M5-EXTENSION-MEASURED] آلية تمديد الإيقاف خارج العواصف — تربح +$77 محاسبةً لكل-صفقة لكنها
        # تخسر $14 في محاكاة العاصمة الحقيقية (الآجال الأطول تسد المقاعد: +$33.63 مقابل +$47.98) ⟵
        # آلية جاهزة ومقيسة وموثقة ومرفوضة بالقياس — افتراضياً مطفأة (الحكم النهائي قيد رأس المال)
        SOP.TIME_STOP_EXT_ENABLE = False
        SOP.TIME_STOP_EXT_RET3_MIN = -3.0
    else:
        # إعادة الدستور v2 كاملاً — كل ثابت لمسه v3 يعود لقيمته الأصلية حرفياً
        SOP.STAGED_EXITS = False
        SOP.TIME_STOP_DAYS = 0
        SOP.BTC_REGIME_GATE = False
        SOP.CRASH_SENTINEL = False
        SOP.SIM_FEES = False
        SOP.MOONSHOT_SENTINEL = False
        SOP.TIME_STOP_EXT_ENABLE = False
        SOP.MAX_RISK_PER_TRADE_USD = 8.0          # نسخة r/SOP_v2: رجوع حرفي للخطر الأصلي 2% من رأس المال
        SOP.MONTHLY_TARGET_USD = 120.0
        SOP.MIN_24H_QUOTE_VOLUME_USD = 50_000_000.0
        SOP.VOLUME_SURGE_RATIO = 1.5
        SOP.MAX_CONSOLIDATION_RANGE_PCT = 12.0
        SOP.BREAKOUT_MIN_VOLUME_RATIO = 1.2
        SOP.RSI_MIN, SOP.RSI_MAX = 35.0, 65.0
    return profile


SOP_PROFILE: str = _apply_sop_profile()


# [MHF-V3.4-5M-AGGREGATION] خريطة الإطارات الزمنية ⟵ مللي ثانية — لتكوين D1/H4 من شموع 5 دقائق
TF_FRAME_MS: Dict[str, int] = {
    "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


WHITELIST: Tuple[str, ...] = (
    "XRPUSDT", "SOLUSDT", "TRXUSDT", "ZECUSDT", "DOGEUSDT", "LINKUSDT", "ADAUSDT", "XLMUSDT",
    "BCHUSDT", "NEARUSDT", "LTCUSDT", "AVAXUSDT", "HBARUSDT", "SUIUSDT", "TAOUSDT", "DOTUSDT",
    "ICPUSDT", "WLDUSDT", "ARBUSDT", "ETCUSDT", "ATOMUSDT", "ALGOUSDT", "RENDERUSDT", "FILUSDT",
    "QNTUSDT", "VETUSDT", "APTUSDT", "STXUSDT", "PYTHUSDT", "ZROUSDT", "TIAUSDT", "SEIUSDT",
    "XTZUSDT", "DCRUSDT", "OPUSDT", "ENSUSDT", "CFXUSDT", "ARUSDT", "TWTUSDT", "GRTUSDT",
    "THETAUSDT", "SANDUSDT", "CHZUSDT", "EGLDUSDT", "ROSEUSDT", "MINAUSDT", "JASMYUSDT",
    "MANAUSDT", "MASKUSDT", "ZILUSDT", "RSRUSDT", "IOTAUSDT", "CHRUSDT", "ENJUSDT", "YGGUSDT",
    "IOTXUSDT", "HOTUSDT", "TRBUSDT", "SLPUSDT", "KSMUSDT", "RVNUSDT", "CELRUSDT", "TLMUSDT",
    "LPTUSDT", "XECUSDT", "SKLUSDT", "GTCUSDT", "SFPUSDT", "MTLUSDT", "QTUMUSDT", "CTSIUSDT",
    "AGLDUSDT", "RLCUSDT", "TFUELUSDT", "WAXPUSDT", "POWRUSDT", "RAREUSDT", "XVGUSDT",
    "STRAXUSDT", "SCUSDT", "CVCUSDT", "REQUSDT", "PUNDIXUSDT", "LSKUSDT", "VTHOUSDT", "DGBUSDT",
    "SUSDT", "POLUSDT", "KAIAUSDT", "BTTCUSDT",
)

BINANCE_BASE = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
POLLINATIONS_URL = "https://text.pollinations.ai/openai"
JOURNAL_PATH = os.getenv("JOURNAL_PATH", "trade_journal_py.json")


# ==============================================================================
# SECTION 2 — SMALL UTILITIES
# ==============================================================================


def log(level: str, message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] [{level}] {message}", flush=True)


def fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def fmt_price(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}"
    return f"{value:.8f}".rstrip("0")


@dataclass
class Candle:
    """One OHLCV bar."""
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    trades: int = 0

    @staticmethod
    def from_binance(row: Sequence[Any]) -> "Candle":
        return Candle(
            open_time=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            close_time=int(row[6]),
            quote_volume=float(row[7]),
            trades=int(row[8]) if len(row) > 8 else 0,
        )


# ---------------------------------------------------------------- [MHF-V3.4-5M-AGGREGATION]
# تكوين شموع الإطارات الكبرى من شموع أصغر (5 دقائق) — بلا lookahead، حتمية، ونفس
# اصطلاح Binance في الحقول (open=أول/close=آخر/high=أعلى/low=أدنى/volume=مجموع،
# open_time=فتح الإطار، close_time=فتح+المدة−1ms). شمعة إطار لم تكتمل خاماتها
# تظل «متشكلة» بقيمة آخر سعر — مثل الشمعة المباشرة القادمة من بايننس تماماً.
def resample_candles(bars: Sequence[Candle], frame_ms: int) -> List[Candle]:
    """جمّع شموعاً متتابعة إلى إطار أكبر. لا تعديل للمدخلات، لا حالات خاصة للتوقيت."""
    if not bars or frame_ms <= 0:
        return []
    out: List[Candle] = []
    bucket: List[Candle] = []
    bucket_open: Optional[int] = None

    def flush() -> None:
        if not bucket or bucket_open is None:
            return
        out.append(Candle(
            open_time=bucket_open,
            open=bucket[0].open,
            high=max(c.high for c in bucket),
            low=min(c.low for c in bucket),
            close=bucket[-1].close,
            volume=sum(c.volume for c in bucket),
            close_time=bucket_open + frame_ms - 1,
            quote_volume=sum(c.quote_volume for c in bucket),
            trades=sum(c.trades for c in bucket),
        ))

    for c in bars:
        frame_open = (c.open_time // frame_ms) * frame_ms
        if bucket_open is None:
            bucket_open = frame_open
        if frame_open != bucket_open:
            flush()
            bucket = []
            bucket_open = frame_open
        bucket.append(c)
    flush()
    return out


def merge_live_tail(native: Sequence[Candle], tail: Sequence[Candle]) -> List[Candle]:
    """الجذر (الأصل) محفوظ حتى فتح أول إطار بالذيل المكوَّن من 5د، وما بعده يُستبدل به."""
    if not tail:
        return list(native)
    first_tail_open = tail[0].open_time
    prefix = [c for c in native if c.open_time < first_tail_open]
    return prefix + list(tail)


# ==============================================================================
# SECTION 3 — PURE-PYTHON TECHNICAL INDICATORS
# ==============================================================================


class Indicators:
    """All indicator math, implemented from scratch (no numpy/pandas/TA-Lib)."""

    # ---------------------------------------------------------------- EMA ----
    @staticmethod
    def ema_series(values: Sequence[float], period: int) -> List[float]:
        """Wilder-free standard EMA, seeded with a simple moving average."""
        if len(values) < period or period <= 0:
            return []
        multiplier = 2.0 / (period + 1.0)
        seed = sum(values[:period]) / period
        out = [seed]
        for price in values[period:]:
            out.append((price - out[-1]) * multiplier + out[-1])
        return out

    @staticmethod
    def ema(values: Sequence[float], period: int) -> Optional[float]:
        series = Indicators.ema_series(values, period)
        return series[-1] if series else None

    # ---------------------------------------------------------------- RSI ----
    @staticmethod
    def rsi_series(values: Sequence[float], period: int = SOP.RSI_PERIOD) -> List[float]:
        """Classic Wilder RSI (smoothed average gain/loss)."""
        if len(values) < period + 1:
            return []

        gains, losses = [], []
        for i in range(1, len(values)):
            change = values[i] - values[i - 1]
            gains.append(max(change, 0.0))
            losses.append(max(-change, 0.0))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        def to_rsi(gain: float, loss: float) -> float:
            if loss == 0:
                return 100.0
            rs = gain / loss
            return 100.0 - (100.0 / (1.0 + rs))

        out = [to_rsi(avg_gain, avg_loss)]
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            out.append(to_rsi(avg_gain, avg_loss))
        return out

    @staticmethod
    def rsi(values: Sequence[float], period: int = SOP.RSI_PERIOD) -> Optional[float]:
        series = Indicators.rsi_series(values, period)
        return series[-1] if series else None

    # ---------------------------------------------------------------- ATR ----
    @staticmethod
    def atr(candles: Sequence[Candle], period: int = 14) -> Optional[float]:
        if len(candles) < period + 1:
            return None
        trs: List[float] = []
        for i in range(1, len(candles)):
            c = candles[i]
            prev_close = candles[i - 1].close
            trs.append(max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close)))
        atr_value = sum(trs[:period]) / period
        for tr in trs[period:]:
            atr_value = (atr_value * (period - 1) + tr) / period
        return atr_value

    # ------------------------------------------------------------- VOLUME ----
    @staticmethod
    def average_volume(candles: Sequence[Candle], lookback: int = 20) -> float:
        """Average volume of CLOSED candles (the live candle is excluded)."""
        closed = candles[:-1]
        window = closed[-lookback:]
        if not window:
            return 0.0
        return sum(c.volume for c in window) / len(window)

    @staticmethod
    def volume_spike_ratio(candles: Sequence[Candle], lookback: int = 20) -> float:
        avg = Indicators.average_volume(candles, lookback)
        if avg <= 0 or not candles:
            return 0.0
        return candles[-1].volume / avg

    # ---------------------------------------------------------- BREAKOUT ----
    @staticmethod
    def consolidation_breakout(
        candles: Sequence[Candle], lookback: int = SOP.BREAKOUT_LOOKBACK
    ) -> Dict[str, Any]:
        """
        Consolidation = tight high/low range over `lookback` CLOSED candles.
        Breakout      = last close above that range high, confirmed by volume.
        """
        if len(candles) < lookback + 2:
            return {
                "breakout": False, "reason": "insufficient candles",
                "range_high": None, "range_low": None, "range_pct": None,
                "volume_ratio": 0.0, "is_consolidating": False, "broke_out": False,
            }

        window = candles[-(lookback + 1):-1]
        range_high = max(c.high for c in window)
        range_low = min(c.low for c in window)
        last = candles[-1]
        range_pct = ((range_high - range_low) / range_low * 100.0) if range_low > 0 else math.inf
        vol_ratio = Indicators.volume_spike_ratio(candles, lookback)

        is_consolidating = range_pct <= SOP.MAX_CONSOLIDATION_RANGE_PCT
        broke_out = last.close > range_high
        volume_confirms = vol_ratio >= SOP.BREAKOUT_MIN_VOLUME_RATIO

        if not is_consolidating:
            reason = "range too wide to be consolidation"
        elif not broke_out:
            reason = "still inside consolidation range"
        elif not volume_confirms:
            reason = "breakout without volume confirmation"
        else:
            reason = "valid consolidation breakout"

        return {
            "breakout": bool(is_consolidating and broke_out and volume_confirms),
            "is_consolidating": is_consolidating,
            "broke_out": broke_out,
            "volume_confirms": volume_confirms,
            "volume_ratio": round(vol_ratio, 2),
            "range_high": range_high,
            "range_low": range_low,
            "range_pct": round(range_pct, 2) if range_pct != math.inf else None,
            "last_close": last.close,
            "reason": reason,
        }

    # ---------------------------------------------------------- PULLBACK ----
    @staticmethod
    def pullback_dip(candles: Sequence[Candle]) -> Dict[str, Any]:
        """عائلة الإعداد الثانية (v3): هبوط RSI المؤقت داخل اتجاه صاعد ثم ارتداد.

        شرط الاتجاه D1 مسؤولية بوابة TechnicalAgent؛ هنا نقيس فقط:
        RSI(14) داخل نطاق التراجع [PULLBACK_RSI_LOW, PULLBACK_RSI_HIGH]
        + آخر شمعة مغلقة أعلى من قمة سابقتها (تأكد انعطاف صاعد).
        """
        if not getattr(SOP, "STAGED_EXITS", False) or len(candles) < SOP.RSI_PERIOD + SOP.BREAKOUT_LOOKBACK + 3:
            return {"pullback": False, "reason": "pullback setup disabled / insufficient candles"}
        closes = [c.close for c in candles]
        rsi14 = Indicators.rsi(closes, SOP.RSI_PERIOD)
        last, prev = candles[-1], candles[-2]
        dipped = rsi14 is not None and SOP.PULLBACK_RSI_LOW <= rsi14 <= SOP.PULLBACK_RSI_HIGH
        turned_up = last.close > prev.high
        # [M0-ITER1] تراجع حقيقي وليس ضجيجاً: الإغلاق بين 3% و15% تحت قمة آخر 20 شمعة
        prior_high = max(c.high for c in candles[-SOP.BREAKOUT_LOOKBACK - 1:-1])
        depth_pct = (prior_high - last.close) / prior_high * 100.0 if prior_high > 0 else 0.0
        real_dip = SOP.PULLBACK_MIN_DEPTH_PCT <= depth_pct <= SOP.PULLBACK_MAX_DEPTH_PCT
        ok = dipped and turned_up and real_dip
        if ok:
            reason = (f"RSI {rsi14:.1f} in pullback zone, depth {depth_pct:.1f}% off 20-bar high, "
                      f"bounced above prior high")
        elif not dipped:
            reason = f"RSI {rsi14:.1f} outside pullback zone" if rsi14 is not None else "no RSI"
        elif not real_dip:
            reason = f"no real dip: {depth_pct:.1f}% off 20-bar high (need {SOP.PULLBACK_MIN_DEPTH_PCT}-{SOP.PULLBACK_MAX_DEPTH_PCT}%)"
        else:
            reason = "dip without bounce confirmation"
        return {"pullback": bool(ok),
                "rsi14": round(rsi14, 2) if rsi14 is not None else None,
                "reason": reason}

    # ------------------------------------------------------------ SNAPSHOT ----
    @staticmethod
    def analyze_timeframe(candles: Sequence[Candle]) -> Dict[str, Any]:
        closes = [c.close for c in candles]
        ema20 = Indicators.ema(closes, SOP.EMA_FAST)
        ema50 = Indicators.ema(closes, SOP.EMA_SLOW)
        rsi14 = Indicators.rsi(closes, SOP.RSI_PERIOD)
        last_close = closes[-1] if closes else None

        return {
            "last_close": last_close,
            "ema20": round(ema20, 8) if ema20 is not None else None,
            "ema50": round(ema50, 8) if ema50 is not None else None,
            "rsi14": round(rsi14, 2) if rsi14 is not None else None,
            "atr14": Indicators.atr(candles, 14),
            "avg_volume20": round(Indicators.average_volume(candles, 20), 4),
            "volume_ratio": round(Indicators.volume_spike_ratio(candles, 20), 2),
            "uptrend": bool(ema20 is not None and ema50 is not None and ema20 > ema50),
            "price_above_ema20": bool(last_close is not None and ema20 is not None and last_close > ema20),
            "rsi_in_range": bool(rsi14 is not None and SOP.RSI_MIN < rsi14 < SOP.RSI_MAX),
            "breakout": Indicators.consolidation_breakout(candles),
            "pullback_dip": Indicators.pullback_dip(candles),
        }


# ==============================================================================
# SECTION 4 — BINANCE SPOT PUBLIC REST CLIENT (stdlib only)
# ==============================================================================


class BinanceError(RuntimeError):
    pass


class BinanceClient:
    """Minimal Binance Spot client using urllib, with retry/backoff + throttling."""

    def __init__(self, base_url: str = BINANCE_BASE, timeout: int = 20, spacing: float = 0.2):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.spacing = spacing
        self._last_call = 0.0
        self._ctx = ssl.create_default_context()
        self._filters_cache: Dict[str, Dict[str, Any]] = {}

    def _throttle(self) -> None:
        delta = time.time() - self._last_call
        if delta < self.spacing:
            time.sleep(self.spacing - delta)
        self._last_call = time.time()

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None, retries: int = 3) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        last_error: Optional[str] = None

        for attempt in range(1, retries + 1):
            self._throttle()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "micro-hedge-fund-strategy/1.0"})
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:  # 4xx/5xx
                body = exc.read().decode("utf-8", "ignore")[:200]
                last_error = f"HTTP {exc.code}: {body}"
                if exc.code in (429, 418) or exc.code >= 500:
                    time.sleep(0.5 * 2 ** (attempt - 1))
                    continue
                break
            except Exception as exc:  # network / timeout
                last_error = str(exc)
                time.sleep(0.5 * 2 ** (attempt - 1))

        raise BinanceError(f"GET {path} failed: {last_error}")

    # ------------------------------------------------------------- market ----
    def klines(self, symbol: str, interval: str, limit: int = SOP.KLINE_LIMIT) -> List[Candle]:
        raw = self._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        return [Candle.from_binance(row) for row in raw]

    # [MHF-V3.4-5M-AGGREGATION] بيانات قرار حية: الجذْم المغلق الأصلي + ذيل D1/H4 مكوَّن من
    # شموع 5 دقائق (آخر 25 ساعة) — يُبنى الشكل الحي كل مسح، فيقتنص الفرص كل 5 دقائق فعلياً.
    # فشل الجلب الجزئي ⟵ رجوع للجلب المباشر حرفياً (لا يفتح ولا يغلق أي بوابة).
    def klines_live(self, symbol: str, interval: str, limit: int = SOP.KLINE_LIMIT,
                    tail_5m: int = 300) -> List[Candle]:
        native = self.klines(symbol, interval, limit)
        frame_ms = TF_FRAME_MS.get(str(interval))
        if not native or frame_ms is None or frame_ms < TF_FRAME_MS["5m"]:
            return native
        try:
            tail5m = self.klines(symbol, "5m", tail_5m)
        except BinanceError as e:
            log("WARN", f"5m live-tail fetch failed for {symbol} (fallback to native): {e}")
            return native
        if not tail5m:
            log("WARN", f"5m live-tail empty for {symbol} (fallback to native)")
            return native
        merged = merge_live_tail(native, resample_candles(tail5m, frame_ms))
        if merged and merged[-1].close_time >= native[-1].open_time:
            log("DEBUG", f"[5M-AGG] {symbol} {interval}: tail {len(resample_candles(tail5m, frame_ms))} bar(s) recomposed "
                        f"(last close {merged[-1].close})")
        return merged

    def ticker_24h(self, symbol: str) -> Dict[str, float]:
        d = self._get("/api/v3/ticker/24hr", {"symbol": symbol})
        return {
            "symbol": d["symbol"],
            "last_price": float(d["lastPrice"]),
            "price_change_pct": float(d["priceChangePercent"]),
            "quote_volume": float(d["quoteVolume"]),
            "volume": float(d["volume"]),
            "trades": int(d["count"]),
        }

    def price(self, symbol: str) -> float:
        return float(self._get("/api/v3/ticker/price", {"symbol": symbol})["price"])

    def order_book(self, symbol: str, limit: int = 100) -> Dict[str, float]:
        d = self._get("/api/v3/depth", {"symbol": symbol, "limit": limit})
        bids = [(float(p), float(q)) for p, q in d["bids"]]
        asks = [(float(p), float(q)) for p, q in d["asks"]]
        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else (best_bid or best_ask)

        bid_depth = sum(p * q for p, q in bids if mid * 0.99 <= p <= mid)
        ask_depth = sum(p * q for p, q in asks if mid <= p <= mid * 1.01)
        spread_pct = ((best_ask - best_bid) / mid * 100.0) if mid else 100.0

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread_pct": spread_pct,
            "bid_depth_usd": bid_depth,
            "ask_depth_usd": ask_depth,
            "total_depth_usd": bid_depth + ask_depth,
            "bid_ask_imbalance": (bid_depth / ask_depth) if ask_depth > 0 else 0.0,
        }

    def symbol_filters(self, symbol: str) -> Dict[str, Any]:
        if symbol in self._filters_cache:
            return self._filters_cache[symbol]
        data = self._get("/api/v3/exchangeInfo", {"symbol": symbol})
        info = (data.get("symbols") or [None])[0]
        if not info:
            raise BinanceError(f"Symbol {symbol} not found on Binance Spot.")

        def find(ftype: str) -> Dict[str, Any]:
            for f in info["filters"]:
                if f["filterType"] == ftype:
                    return f
            return {}

        lot, pricef = find("LOT_SIZE"), find("PRICE_FILTER")
        notional = find("NOTIONAL") or find("MIN_NOTIONAL")
        parsed = {
            "symbol": symbol,
            "base_asset": info["baseAsset"],
            "status": info["status"],
            "oco_allowed": bool(info.get("ocoAllowed", False)),
            "step_size": float(lot.get("stepSize", "0.00000001")),
            "min_qty": float(lot.get("minQty", "0")),
            "tick_size": float(pricef.get("tickSize", "0.00000001")),
            "min_notional": float(notional.get("minNotional") or notional.get("notional") or 5),
        }
        self._filters_cache[symbol] = parsed
        return parsed

    @staticmethod
    def round_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        return math.floor(value / step) * step


# ==============================================================================
# SECTION 5 — OPTIONAL KEYLESS LLM LAYER (Pollinations.ai)
# ==============================================================================


class KeylessLLM:
    """
    Optional reasoning layer. NO API key, NO account, NO login.
    Every agent works perfectly without it — it only refines rankings.
    """

    # سلّم نماذج احتياطي — «openai» يجيب 402 أحياناً على المستوى المجاني ([MHF-V3-UPGRADE])
    MODEL_LADDER: Tuple[str, ...] = ("openai", "openai-fast", "mistral")

    def __init__(self, enabled: bool = True, timeout: int = 45, referrer: str = "micro-hedge-fund-strategy"):
        self.enabled = enabled
        self.timeout = timeout
        self.referrer = referrer
        self.available: Optional[bool] = None
        self.model_used: Optional[str] = None
        self._dead: set = set()
        self._ctx = ssl.create_default_context()

    def ask_json(self, system: str, user: str, retries: int = 2) -> Optional[dict]:
        if not self.enabled:
            return None

        for model in self.MODEL_LADDER:
            if model in self._dead:
                continue
            payload = json.dumps({
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.2,
                "referrer": self.referrer,
            }).encode("utf-8")

            for attempt in range(1, retries + 1):
                try:
                    req = urllib.request.Request(
                        POLLINATIONS_URL,
                        data=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Referer": self.referrer,
                            "User-Agent": "micro-hedge-fund-strategy/1.0",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    content = (body.get("choices") or [{}])[0].get("message", {}).get("content")
                    parsed = self.extract_json(content or "")
                    if parsed:
                        self.available = True
                        self.model_used = model
                        return parsed
                except Exception as exc:
                    log("DEBUG", f"LLM {model} attempt {attempt} failed: {str(exc)[:120]}")
                time.sleep(3.5)  # anonymous tier allows ~1 request / 3s
            self._dead.add(model)  # هذا النموذج غير متاح الآن — جرّب التالي على السلّم

        self.available = False
        return None

    @staticmethod
    def extract_json(text: str) -> Optional[dict]:
        """Strips code fences / prose and extracts the first balanced JSON object."""
        if not text or not text.strip():
            return None
        clean = text.strip()
        if "```" in clean:
            start = clean.find("```")
            end = clean.find("```", start + 3)
            if end > start:
                chunk = clean[start + 3:end]
                clean = chunk[4:].strip() if chunk.lstrip().lower().startswith("json") else chunk.strip()

        try:
            return json.loads(clean)
        except Exception:
            pass

        start = clean.find("{")
        if start == -1:
            return None
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(clean)):
            ch = clean[i]
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(clean[start:i + 1])
                    except Exception:
                        return None
        return None


# Professional, per-agent system prompts (mirrors the Node.js PROMPTS object).
PROMPT_NARRATIVE = """# ROLE
You are the NARRATIVE ANALYST of a disciplined micro hedge fund ($400 AUM) trading Binance SPOT, LONG-ONLY.

# HARD RULES
1. Only return symbols present in the "candidates" array. Never invent a symbol.
2. Reject parabolic exhaustion (weekly > +40%) and falling knives (weekly < -15%).
3. Return at most 5 symbols; fewer is better than padding.
4. "strength" is an integer 1-10 = sector heat (0-4) + narrative freshness (0-3) + momentum quality (0-3).

# OUTPUT CONTRACT
Raw JSON only, no markdown, no prose:
{"marketRegime":"risk-on|neutral|risk-off","summary":"...","selected":[{"symbol":"SOLUSDT","narrative":"Layer-1","thesis":"...","strength":8}]}"""


# [MHF-V3-UPGRADE] برومبت احترافي v3 — تخصيص سردي بمستوى مدير صندوق مع ضوابط تكتل ونظام سوقي
PROMPT_NARRATIVE_V3 = """# ROLE
You are the CHIEF NARRATIVE ALLOCATOR of a disciplined crypto micro hedge fund ($400 AUM), SPOT LONG-ONLY on Binance. Your picks feed a mechanical D1-trend + H4-setup pipeline; your job is ONLY to rank liquidity-backed weekly momentum into a short, diversified watchlist.

# HARD RULES (violating any makes the answer unusable)
1. Select ONLY symbols present verbatim in the "candidates" array. Never invent, translate or rename a symbol.
2. Reject parabolic exhaustion (weekly > +40%) and falling knives (weekly < -15%), even if listed.
3. Return AT MOST 5 symbols; fewer is better than padding.
4. SECTOR CAP: at most 2 symbols from the same sector (Layer-1, Layer-2, DeFi, Meme, Gaming/Metaverse, AI, Storage, Payments, Oracle, Privacy, Exchange-token, RWA).
5. "strength" is an integer 1-10 = sector heat (0-4) + narrative freshness (0-3) + momentum quality (0-3) — momentum quality rises with steady volume-backed moves, NOT vertical candles.
6. Prefer candidates whose avg_daily_quote_vol_usd exceeds 50M USD.

# REGIME CLASSIFICATION
marketRegime = "risk-on" if the majority of strong candidates show sustained positive weekly momentum with healthy liquidity; "risk-off" if most show negative or deteriorating momentum; otherwise "neutral". In "risk-off", return an EMPTY "selected" array — standing aside is a decision.

# OUTPUT CONTRACT
Raw JSON only, no markdown, no prose, no code fences:
{"marketRegime":"risk-on|neutral|risk-off","summary":"one line market read","selected":[{"symbol":"SOLUSDT","sector":"Layer-1","narrative":"Layer-1","thesis":"one line why now","strength":8}]}"""

# [MHF-V3.1-CRASH-SENTINEL] برومبت السائل اليومي لمحرك التنبؤ بالانهيارات — شامل/احترافي/مضبوط المخرجات
PROMPT_CRASH_SENTINEL = """# ROLE
You are the CRASH SENTINEL of a crypto micro hedge fund ($400 AUM), SPOT LONG-ONLY on Binance. Once per day you judge the probability of a BROAD SYSTEMIC CRASH — a fast, deep, correlated selloff across majors — over the next 24-72 hours. You never judge individual coins.

# INPUTS (JSON snapshot)
btc_24h_pct / eth_24h_pct, btc_ret3 (rolling 3-day BTC return %), btc_vol20 (stdev of last 20 daily returns %, annualization-free), btc_below_ema20 (bool), eth_below_ema20 (bool), and current UTC date.

# MEASURED EVIDENCE FROM THIS FUND'S BACKTEST (90 pairs, 167 days)
- Trades entered while btc_ret3 <= -3%: 30.7% winners, -$255.79 aggregate (the ONLY toxic zone).
- Trades entered while btc_ret3 in (-3%, 0%): 67.5% winners, +$451.90 aggregate.
- Breadth deterioration (majors falling together) + volatility expansion preceded the worst weeks.

# JUDGMENT RULES
1. Be FALSE-ALARM-TOLERANT but CRASH-AVERSE: prefer "elevated" over "high" unless momentum AND volatility AND breadth align bearishly.
2. "high" means: credible risk of an imminent correlated selloff (>= -6% BTC within 72h). Reserve it for genuine confluence — a quiet pullback is "watch", not "storm".
3. "unknown" when inputs look stale, partial or inconsistent (with low confidence).
4. Scale confidence 1-10 = breadth of evidence (0-4) + volatility confirmation (0-3) + momentum alignment (0-3).

# OUTPUT CONTRACT
Raw JSON only, no markdown, no prose, no code fences:
{"regime":"calm|watch|storm|unknown","crash_risk":"low|elevated|high|unknown","confidence":1-10,"horizon_hours":24-72,"breadth_score":0-10,"summary":"one line market read"}"""

# [MHF-V3.2-FIVE-ENGINES] برومبت السائل اليومي لمحرك التنبؤ بالانفجارات — مرآة عقد Sentinel
PROMPT_MOONSHOT_SENTINEL = """# ROLE
You are the MOONSHOT SENTINEL of a crypto micro hedge fund ($400 AUM), SPOT LONG-ONLY on Binance. Once per day you judge the probability of a BROAD EXPLOSIVE UPSIDE phase — a correlated thrust where majors expand 8-25% within days — over the next 24-72 hours. You never chase single coins; you judge the WIND that lifts them.

# INPUTS (JSON snapshot)
btc_24h_pct / eth_24h_pct, btc_ret3 (rolling 3-day BTC return %), btc_ret7, btc_vol20 (stdev of last 20 daily returns %), btc_above_ema20 (bool), squeeze (true when btc_vol20 sits in the lowest third of its own 90-day range — compressed energy), and current UTC date.

# MEASURED EVIDENCE FROM THIS FUND'S BACKTEST (90 pairs, 167 days)
- Entries while btc_ret3 > +3%: 100% non-losing (0 full stop-losses), +$6.17 average per trade.
- The two best weeks (+$381, +$131) followed breadth ignition, not vertical candles.
- Winners reaching the far target (+22.4%) mostly STARTED in quiet uptrends, NOT in late parabolic phases.

# JUDGMENT RULES
1. Be OPPORTUNITY-TOLERANT but PARABOLA-AVERSE: "launch" requires momentum ignition WITHOUT blow-off excess (btc_ret3 between +2% and +12%; above that, suspect exhaustion -> "thrust" at best).
2. "high" explosion_risk only when ignition + breadth expansion + (squeeze release OR trend alignment above EMA20) agree.
3. "unknown" when inputs look stale, partial or inconsistent (with low confidence).
4. boost_symbols: AT MOST 3 symbols chosen ONLY from "candidates" array — steady leaders above their own 20-day averages, never today's top vertical movers.

# OUTPUT CONTRACT
Raw JSON only, no markdown, no prose, no code fences:
{"regime":"calm|thrust|launch|unknown","explosion_risk":"low|elevated|high|unknown","confidence":1-10,"horizon_hours":24-72,"boost_symbols":["SOLUSDT"],"summary":"one line market read"}"""

PROMPT_ONCHAIN = """# ROLE
You are the ON-CHAIN & LIQUIDITY ANALYST of a micro hedge fund trading Binance SPOT.
Decide whether flow is genuine ACCUMULATION or a DISTRIBUTION TRAP.

# HEURISTICS
accumulation=true : volume expanding, bid/ask imbalance >= 1.0, tight spread, price not already vertical.
accumulation=false: volume explodes while 24h price change > +25%, or imbalance < 0.8, or wide spread.

# HARD RULES
1. Judge only the provided symbols. 2. When ambiguous, choose false (capital preservation first).
3. "comment" must cite at least one concrete number.

# OUTPUT CONTRACT
Raw JSON only:
{"assessments":[{"symbol":"SOLUSDT","accumulation":true,"confidence":72,"comment":"..."}]}"""

PROMPT_TECHNICAL = """# ROLE
You are the TECHNICAL ANALYST and final quality gate of a micro hedge fund trading Binance SPOT, LONG-ONLY.
Indicator values are ALREADY COMPUTED. Never recompute or dispute them — interpret and VETO.

# VETO IF
1. Price far above ema20 on both timeframes (exhaustion).
2. Breakout volume barely above 1.2x while the range was very wide (false breakout risk).
3. D1 RSI > 70 while H4 RSI weakens (divergence risk).
4. D1 EMA20 and EMA50 nearly identical (flat, directionless).
5. The -6.4% stop would sit ABOVE the H4 breakout range high (stop inside noise, gets swept).

# OUTPUT CONTRACT
Raw JSON only, one entry per candidate:
{"validations":[{"symbol":"SOLUSDT","valid":true,"confidence":78,"summary":"..."}],"best":"SOLUSDT"}"""


# ==============================================================================
# SECTION 6 — JOURNAL & CIRCUIT BREAKERS
# ==============================================================================


@dataclass
class Trade:
    id: str
    symbol: str
    entry_price: float
    quantity: float
    position_size_usd: float
    stop_loss: float
    take_profit: float
    opened_at: str
    side: str = "SPOT_LONG"
    risk_usd: float = SOP.MAX_RISK_PER_TRADE_USD
    reward_usd: float = SOP.TARGET_PROFIT_PER_TRADE_USD
    status: str = "OPEN"
    outcome: Optional[str] = None
    exit_price: Optional[float] = None
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None
    closed_at: Optional[str] = None
    rationale: Dict[str, Any] = field(default_factory=dict)


class Journal:
    """JSON-backed state: active/closed trades, PnL aggregation, circuit breakers."""

    def __init__(self, path: str = JOURNAL_PATH):
        self.path = path
        self.state: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        default = {
            "capital": SOP.ACCOUNT_CAPITAL_USD,
            "active_trades": [],
            "closed_trades": [],
            "rejected_signals": [],
            "halt_until": None,
            "monthly_pause_month": None,
        }
        if not os.path.exists(self.path):
            return default
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            default.update(data)
            return default
        except Exception as exc:
            log("WARN", f"Journal unreadable ({exc}); starting fresh.")
            return default

    def save(self) -> None:
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------ queries ----
    @staticmethod
    def _day_key(iso: str) -> str:
        return iso[:10]

    @staticmethod
    def _month_key(iso: str) -> str:
        return iso[:7]

    def daily_pnl(self, when: Optional[datetime] = None) -> float:
        key = (when or datetime.now(timezone.utc)).isoformat()[:10]
        return sum(
            float(t.get("pnl_usd") or 0)
            for t in self.state["closed_trades"]
            if t.get("closed_at", "")[:10] == key
        )

    def monthly_pnl(self, when: Optional[datetime] = None) -> float:
        key = (when or datetime.now(timezone.utc)).isoformat()[:7]
        return sum(
            float(t.get("pnl_usd") or 0)
            for t in self.state["closed_trades"]
            if t.get("closed_at", "")[:7] == key
        )

    def total_pnl(self) -> float:
        return sum(float(t.get("pnl_usd") or 0) for t in self.state["closed_trades"])

    # --------------------------------------------------- circuit breakers ----
    def check_circuit_breakers(self) -> Dict[str, Any]:
        reasons: List[str] = []
        now = datetime.now(timezone.utc)
        daily = self.daily_pnl(now)
        monthly = self.monthly_pnl(now)
        active = len(self.state["active_trades"])

        # 1. Daily loss cutoff (-$24)
        daily_halt = False
        if daily <= -SOP.DAILY_LOSS_CUTOFF_USD:
            daily_halt = True
            reasons.append(f"Daily loss cutoff hit: {fmt_money(daily)} <= -{fmt_money(SOP.DAILY_LOSS_CUTOFF_USD)}.")
        halt_until = self.state.get("halt_until")
        if halt_until and datetime.fromisoformat(halt_until) > now:
            daily_halt = True
            reasons.append(f"Active 24h halt until {halt_until}.")

        # 2. Monthly target lock (+$120)
        monthly_lock = False
        current_month = now.isoformat()[:7]
        if monthly >= SOP.MONTHLY_TARGET_USD or self.state.get("monthly_pause_month") == current_month:
            monthly_lock = True
            reasons.append(f"Monthly target reached: {fmt_money(monthly)} >= {fmt_money(SOP.MONTHLY_TARGET_USD)}.")

        # 3. Max open positions
        max_trades = active >= SOP.MAX_OPEN_POSITIONS
        if max_trades:
            reasons.append(f"Max open positions reached ({active}/{SOP.MAX_OPEN_POSITIONS}).")

        return {
            "allowed": not (daily_halt or monthly_lock or max_trades),
            "reasons": reasons,
            "daily_halt": daily_halt,
            "monthly_lock": monthly_lock,
            "max_trades": max_trades,
            "daily_pnl": round(daily, 2),
            "monthly_pnl": round(monthly, 2),
            "active_count": active,
        }

    def engage_daily_halt(self) -> None:
        until = datetime.fromtimestamp(time.time() + SOP.DAILY_HALT_SECONDS, tz=timezone.utc)
        self.state["halt_until"] = until.isoformat()
        self.save()
        log("WARN", f"24h halt engaged until {until.isoformat()}")

    def lock_month(self) -> None:
        self.state["monthly_pause_month"] = datetime.now(timezone.utc).isoformat()[:7]
        self.save()

    def reconcile(self) -> None:
        """Auto-manage breaker flags from realized PnL."""
        now = datetime.now(timezone.utc)
        changed = False
        if self.daily_pnl(now) <= -SOP.DAILY_LOSS_CUTOFF_USD and not self.state.get("halt_until"):
            self.state["halt_until"] = datetime.fromtimestamp(
                time.time() + SOP.DAILY_HALT_SECONDS, tz=timezone.utc
            ).isoformat()
            changed = True
        halt_until = self.state.get("halt_until")
        if halt_until and datetime.fromisoformat(halt_until) <= now:
            self.state["halt_until"] = None
            changed = True
        if self.monthly_pnl(now) >= SOP.MONTHLY_TARGET_USD:
            month = now.isoformat()[:7]
            if self.state.get("monthly_pause_month") != month:
                self.state["monthly_pause_month"] = month
                changed = True
        if changed:
            self.save()

    # ---------------------------------------------------------- mutations ----
    def has_active(self, symbol: str) -> bool:
        return any(t["symbol"] == symbol for t in self.state["active_trades"])

    def committed_capital(self) -> float:
        return sum(float(t["position_size_usd"]) for t in self.state["active_trades"])

    def add_trade(self, trade: Trade) -> None:
        self.state["active_trades"].append(asdict(trade))
        self.save()

    def close_trade(self, trade_id: str, exit_price: float, outcome: str = "MANUAL") -> Optional[dict]:
        for i, t in enumerate(self.state["active_trades"]):
            if t["id"] == trade_id or t["symbol"] == trade_id:
                trade = self.state["active_trades"].pop(i)
                pnl = (exit_price - trade["entry_price"]) * trade["quantity"]
                trade.update({
                    "status": "CLOSED",
                    "outcome": outcome,
                    "exit_price": exit_price,
                    "pnl_usd": round(pnl, 2),
                    "pnl_pct": round(pnl / trade["position_size_usd"] * 100, 2),
                    "closed_at": datetime.now(timezone.utc).isoformat(),
                })
                self.state["closed_trades"].append(trade)
                self.save()
                return trade
        return None

    def stats(self) -> Dict[str, Any]:
        closed = self.state["closed_trades"]
        wins = sum(1 for t in closed if float(t.get("pnl_usd") or 0) > 0)
        total = self.total_pnl()
        return {
            "active": len(self.state["active_trades"]),
            "closed": len(closed),
            "wins": wins,
            "losses": len(closed) - wins,
            "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
            "total_pnl": round(total, 2),
            "daily_pnl": round(self.daily_pnl(), 2),
            "monthly_pnl": round(self.monthly_pnl(), 2),
            "equity": round(SOP.ACCOUNT_CAPITAL_USD + total, 2),
        }


# ==============================================================================
# SECTION 7 — THE FOUR AGENTS
# ==============================================================================


class CrashSentinel:
    """[MHF-V3.1-CRASH-SENTINEL] العضو الخامس في الفريق: بوابة حظر دخول عند خطر انهيار مؤكد.

    طبقتان تعمل كلتاهما باستقلال:
      ① حتمية قابلة للباكتست: عائد BTC المتدحرج 3 أيام ≤ CRASH_BTC_RET3_THRESHOLD
        (قاعدة مستخرجة من تجميع الخسائر المقيس: تلك المنطقة نجاحها 30.7% فقط بخسارة −255.79$)
      ② سؤال LLM شامل يُطرح مرة كل 24 ساعة (تخزين مؤقت ذاكرة+قرص) بحكم systemic فقط —
        «high» يحظر، «elevated» تحذير، وعند فشل LLM تحكم الحتمية وحدها.
    لا يمس المراكز المفتوحة إطلاقاً — بوابة دخول جديدة فقط.
    """

    TTL_SECONDS: int = 24 * 60 * 60

    def __init__(self, client: Optional[BinanceClient] = None, llm: Optional[KeylessLLM] = None,
                 state_path: Optional[str] = None):
        self.client = client
        self.llm = llm
        self.state_path = state_path
        self._verdict: Optional[Dict[str, Any]] = None  # آخر حكم LLM صالح ضمن TTL

    # ---------------------------------------------------------------- layer 1
    @staticmethod
    def deterministic_risk(btc_d1: Sequence[Candle]) -> Dict[str, Any]:
        """قاعدة القياس: عائد BTC المتدحرج 3 أيام عند آخر إغلاق يومي."""
        closes = [c.close for c in btc_d1]
        if len(closes) < 5:
            return {"regime": "unknown", "veto": False, "ret3": None,
                    "reason": "insufficient BTC history"}
        ret3 = (closes[-1] / closes[-4] - 1) * 100.0
        threshold = getattr(SOP, "CRASH_BTC_RET3_THRESHOLD", -3.0)
        if ret3 <= threshold:
            return {"regime": "storm", "veto": True, "ret3": round(ret3, 2),
                    "reason": f"BTC 3d return {ret3:+.1f}% <= {threshold}%"}
        return {"regime": "calm", "veto": False, "ret3": round(ret3, 2),
                "reason": f"BTC 3d {ret3:+.1f}%"}

    # ---------------------------------------------------------------- layer 2
    def _load_stored(self) -> Optional[Dict[str, Any]]:
        """استرجاع حكم المخزن على القرص إن كان طازجاً — يحمي من إعادة سؤال بعد كل ريستارت."""
        if not self.state_path or not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if time.time() - float(stored.get("ts", 0)) < self.TTL_SECONDS:
                return stored.get("verdict")
        except Exception as e:
            log("WARN", f"CrashSentinel stored verdict unreadable: {e}")
        return None

    def _store(self, verdict: Dict[str, Any]) -> None:
        if not self.state_path:
            return
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            tmp = f"{self.state_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"ts": time.time(), "verdict": verdict}, fh)
            os.replace(tmp, self.state_path)
        except Exception as e:
            log("WARN", f"CrashSentinel verdict store failed: {e}")

    def _snapshot_prompt(self, btc_d1: Sequence[Candle], tickers: Dict[str, Dict[str, Any]]) -> str:
        """لقطة السوق النصية المُطعمة للسؤال اليومي — كلها من بيانات متاحة فعلاً."""
        closes = [c.close for c in btc_d1]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))][-20:]
        mean = sum(rets) / len(rets) if rets else 0.0
        var = sum((r - mean) ** 2 for r in rets) / len(rets) if rets else 0.0
        ema20 = Indicators.ema(closes, SOP.EMA_FAST) if len(closes) >= SOP.EMA_FAST else None
        snap = {
            "date_utc": datetime.now(timezone.utc).isoformat()[:10],
            "btc_24h_pct": tickers.get("BTCUSDT", {}).get("price_change_pct"),
            "eth_24h_pct": tickers.get("ETHUSDT", {}).get("price_change_pct"),
            "btc_ret3": round((closes[-1] / closes[-4] - 1) * 100.0, 2) if len(closes) >= 4 else None,
            "btc_vol20": round(var ** 0.5 * 100.0, 2),
            "btc_below_ema20": bool(ema20 is not None and closes[-1] < ema20),
        }
        return json.dumps({"task": "Judge systemic crash risk for next 24-72h", "snapshot": snap}, indent=2)

    def _llm_verdict(self, btc_d1: Sequence[Candle], tickers: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """حكم LLM مخزَّن 24 ساعة — لا سؤالين في اليوم مهما تكرر المسح."""
        if self._verdict and time.time() - self._verdict.get("asked_at", 0) < self.TTL_SECONDS:
            return self._verdict["data"]
        stored = self._load_stored()
        if stored:
            if not self._verdict:
                self._verdict = {"asked_at": time.time(), "data": stored}
            return stored
        if not self.llm or not self.llm.enabled:
            return None
        if not tickers and self.client is not None:  # لا نطلب الشبكة إلا لحظة السؤال اليومي فعلاً
            try:
                tickers = {"BTCUSDT": self.client.ticker_24h("BTCUSDT"),
                           "ETHUSDT": self.client.ticker_24h("ETHUSDT")}
            except BinanceError as e:
                log("WARN", f"CrashSentinel ticker fetch failed (LLM skipped this scan): {e}")
        parsed = self.llm.ask_json(PROMPT_CRASH_SENTINEL, self._snapshot_prompt(btc_d1, tickers))
        if not parsed:
            return None
        data = {
            "crash_risk": str(parsed.get("crash_risk", "unknown")).lower(),
            "regime": str(parsed.get("regime", "unknown")).lower(),
            "confidence": max(1, min(10, int(parsed.get("confidence") or 1))),
            "summary": str(parsed.get("summary", ""))[:200],
        }
        self._verdict = {"asked_at": time.time(), "data": data}
        self._store(data)
        return data

    # ---------------------------------------------------------------- verdict
    def assess(self, btc_d1: Optional[Sequence[Candle]] = None,
               tickers: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """الحكم الموحد: حظر إن قالت الحتمية «عاصفة» أو قال LLM «high»."""
        det = self.deterministic_risk(btc_d1) if btc_d1 else {"regime": "unknown", "veto": False,
                                                               "ret3": None, "reason": "no BTC data"}
        llm_v = self._llm_verdict(btc_d1 or [], tickers or {}) if getattr(SOP, "CRASH_SENTINEL", False) else None
        llm_high = bool(llm_v and llm_v.get("crash_risk") == "high")
        veto = bool(det.get("veto")) or llm_high
        source = "deterministic+llm" if det.get("veto") and llm_high else (
            "deterministic" if det.get("veto") else ("llm" if llm_high else ("llm" if llm_v else "deterministic")))
        regime = ("storm" if veto else
                  (llm_v.get("regime") if llm_v and llm_v.get("regime") != "unknown" else det.get("regime")))
        reason = det.get("reason", "")
        if llm_v:
            reason += f" | LLM: {llm_v['crash_risk']} ({llm_v['summary']})"
        verdict = {"veto": veto, "regime": regime, "source": source, "reason": reason,
                   "deterministic": det, "llm": llm_v}
        log("INFO", f"CRASH-SENTINEL: veto={veto} regime={regime} via {source} — {reason}")
        return verdict


class MoonshotSentinel:
    """[MHF-V3.2-FIVE-ENGINES] مرآة CrashSentinel للاتجاه الصاعد: التقاط أنظمة الانفجار بلا مطاردة شمول.

    طبقتان:
      ① حتمية قابلة للباكتست: عائد BTC المتدحرج 3 أيام ≥ MOONSHOT_BTC_RET3_THRESHOLD —
        مقيس: تلك الدخولات 100% غير خاسرة (صفر وقف كامل) بمتوسط +$6.17.
      ② سؤال LLM يومي (تخزين 24س ذاكرة+قرص): انفجار مؤكد «launch» + حتى 3 رموز تعزيز —
        أثره المحدود والمعلن: تمديد الإيقاف الزمني ×MOONSHOT_TSTOP_MULT، لا تخفيف أي بوابة دخول.
    """

    TTL_SECONDS: int = 24 * 60 * 60

    def __init__(self, client: Optional[BinanceClient] = None, llm: Optional[KeylessLLM] = None,
                 state_path: Optional[str] = None):
        self.client = client
        self.llm = llm
        self.state_path = state_path
        self._verdict: Optional[Dict[str, Any]] = None

    # ---------------------------------------------------------------- layer 1
    @staticmethod
    def deterministic_regime(btc_d1: Sequence[Candle]) -> Dict[str, Any]:
        """مرآة عتبة الانهيار: عائد BTC المتدحرج 3 أيام عند آخر إغلاق يومي."""
        closes = [c.close for c in btc_d1]
        if len(closes) < 5:
            return {"regime": "unknown", "moonshot": False, "ret3": None,
                    "reason": "insufficient BTC history"}
        ret3 = (closes[-1] / closes[-4] - 1) * 100.0
        threshold = getattr(SOP, "MOONSHOT_BTC_RET3_THRESHOLD", 3.0)
        if ret3 >= threshold:
            return {"regime": "launch", "moonshot": True, "ret3": round(ret3, 2),
                    "reason": f"BTC 3d return {ret3:+.1f}% >= +{threshold}%"}
        return {"regime": "calm", "moonshot": False, "ret3": round(ret3, 2),
                "reason": f"BTC 3d {ret3:+.1f}%"}

    # ---------------------------------------------------------------- layer 2
    def _load_stored(self) -> Optional[Dict[str, Any]]:
        if not self.state_path or not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if time.time() - float(stored.get("ts", 0)) < self.TTL_SECONDS:
                return stored.get("verdict")
        except Exception as e:
            log("WARN", f"MoonshotSentinel stored verdict unreadable: {e}")
        return None

    def _store(self, verdict: Dict[str, Any]) -> None:
        if not self.state_path:
            return
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            tmp = f"{self.state_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"ts": time.time(), "verdict": verdict}, fh)
            os.replace(tmp, self.state_path)
        except Exception as e:
            log("WARN", f"MoonshotSentinel verdict store failed: {e}")

    def _snapshot_prompt(self, btc_d1: Sequence[Candle], tickers: Dict[str, Dict[str, Any]],
                         candidates: Sequence[str]) -> str:
        closes = [c.close for c in btc_d1]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))][-20:]
        mean = sum(rets) / len(rets) if rets else 0.0
        var = sum((r - mean) ** 2 for r in rets) / len(rets) if rets else 0.0
        vol20 = var ** 0.5 * 100.0
        vol_hist = []
        for j in range(max(2, len(closes) - 110), len(closes)):
            win = [closes[k] / closes[k - 1] - 1 for k in range(max(1, j - 20), j)]
            m2 = sum(win) / len(win) if win else 0.0
            vol_hist.append((sum((x - m2) ** 2 for x in win) / len(win) if win else 0.0) ** 0.5 * 100.0)
        ema20 = Indicators.ema(closes, SOP.EMA_FAST) if len(closes) >= SOP.EMA_FAST else None
        snap = {
            "date_utc": datetime.now(timezone.utc).isoformat()[:10],
            "btc_24h_pct": tickers.get("BTCUSDT", {}).get("price_change_pct"),
            "eth_24h_pct": tickers.get("ETHUSDT", {}).get("price_change_pct"),
            "btc_ret3": round((closes[-1] / closes[-4] - 1) * 100.0, 2) if len(closes) >= 4 else None,
            "btc_ret7": round((closes[-1] / closes[-8] - 1) * 100.0, 2) if len(closes) >= 8 else None,
            "btc_vol20": round(vol20, 2),
            "btc_above_ema20": bool(ema20 is not None and closes[-1] > ema20),
            "squeeze": bool(vol_hist and vol20 <= sorted(vol_hist)[max(0, len(vol_hist) // 3)]),
            "candidates": list(candidates)[:10],
        }
        return json.dumps({"task": "Judge broad explosion probability for next 24-72h", "snapshot": snap}, indent=2)

    def _llm_verdict(self, btc_d1: Sequence[Candle], tickers: Dict[str, Dict[str, Any]],
                     candidates: Sequence[str]) -> Optional[Dict[str, Any]]:
        if self._verdict and time.time() - self._verdict.get("asked_at", 0) < self.TTL_SECONDS:
            return self._verdict["data"]
        stored = self._load_stored()
        if stored:
            if not self._verdict:
                self._verdict = {"asked_at": time.time(), "data": stored}
            return stored
        if not self.llm or not self.llm.enabled:
            return None
        parsed = self.llm.ask_json(PROMPT_MOONSHOT_SENTINEL,
                                   self._snapshot_prompt(btc_d1, tickers, candidates))
        if not parsed:
            return None
        data = {
            "explosion_risk": str(parsed.get("explosion_risk", "unknown")).lower(),
            "regime": str(parsed.get("regime", "unknown")).lower(),
            "confidence": max(1, min(10, int(parsed.get("confidence") or 1))),
            "boost_symbols": [str(s).upper() for s in (parsed.get("boost_symbols") or []) if s][:3],
            "summary": str(parsed.get("summary", ""))[:200],
        }
        self._verdict = {"asked_at": time.time(), "data": data}
        self._store(data)
        return data

    # ---------------------------------------------------------------- verdict
    def assess(self, btc_d1: Optional[Sequence[Candle]] = None,
               tickers: Optional[Dict[str, Dict[str, Any]]] = None,
               candidates: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        det = self.deterministic_regime(btc_d1) if btc_d1 else {"regime": "unknown", "moonshot": False,
                                                                 "ret3": None, "reason": "no BTC data"}
        if getattr(SOP, "MOONSHOT_SENTINEL", False):
            if tickers is None and self.client is not None and self.llm and self.llm.enabled \
                    and self._verdict is None and self._load_stored() is None:
                try:
                    tickers = {"BTCUSDT": self.client.ticker_24h("BTCUSDT"),
                               "ETHUSDT": self.client.ticker_24h("ETHUSDT")}
                except BinanceError as e:
                    log("WARN", f"MoonshotSentinel ticker fetch failed (LLM skipped this scan): {e}")
            llm_v = self._llm_verdict(btc_d1 or [], tickers or {}, candidates or [])
        else:
            llm_v = None
        llm_launch = bool(llm_v and llm_v.get("regime") == "launch")
        moonshot = bool(det.get("moonshot")) or llm_launch
        boost = sorted({s for s in (llm_v or {}).get("boost_symbols", [])}) if llm_v else []
        src = "deterministic+llm" if det.get("moonshot") and llm_launch else (
            "deterministic" if det.get("moonshot") else ("llm" if llm_launch else ("llm" if llm_v else "deterministic")))
        verdict = {"moonshot": moonshot, "regime": "launch" if moonshot else det.get("regime"),
                   "source": src, "boost_symbols": boost, "reason": det.get("reason", ""),
                   "deterministic": det, "llm": llm_v}
        log("INFO", f"MOONSHOT-SENTINEL: moonshot={moonshot} boost={boost} via {src} — {det.get('reason','')}")
        return verdict


class NarrativeAgent:
    """STAGE 1 — narrative / momentum shortlist from the whitelist."""

    name = "NarrativeAgent"

    def __init__(self, client: BinanceClient, llm: Optional[KeylessLLM] = None):
        self.client = client
        self.llm = llm

    def weekly_momentum(self, symbols: Iterable[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for symbol in symbols:
            try:
                candles = self.client.klines(symbol, "1d", 8)
                if len(candles) < 8:
                    continue
                first, last = candles[0].close, candles[-1].close
                out.append({
                    "symbol": symbol,
                    "weekly_change_pct": round((last - first) / first * 100, 2),
                    "avg_daily_quote_vol_usd": round(sum(c.quote_volume for c in candles) / len(candles)),
                })
            except BinanceError as exc:
                log("DEBUG", f"{self.name}: skip {symbol} ({str(exc)[:70]})")
        return out

    @staticmethod
    def deterministic_shortlist(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        eligible = [
            c for c in candidates
            if SOP.NARRATIVE_MIN_WEEKLY_PCT < c["weekly_change_pct"] < SOP.NARRATIVE_MAX_WEEKLY_PCT
        ]
        eligible.sort(key=lambda c: c["weekly_change_pct"], reverse=True)
        return [
            {
                "symbol": c["symbol"],
                "narrative": "Momentum (deterministic)",
                "thesis": f"Weekly {c['weekly_change_pct']}% on {fmt_money(c['avg_daily_quote_vol_usd'])} avg daily volume.",
                "strength": 5,
            }
            for c in eligible[:SOP.NARRATIVE_SHORTLIST_SIZE]
        ]

    def run(self) -> Dict[str, Any]:
        log("INFO", "STAGE 1 — NarrativeAgent: screening the whitelist…")
        momentum = self.weekly_momentum(WHITELIST)
        liquid = [m for m in momentum if m["avg_daily_quote_vol_usd"] >= SOP.MIN_24H_QUOTE_VOLUME_USD * 0.5]
        liquid.sort(key=lambda c: c["weekly_change_pct"], reverse=True)
        liquid = liquid[:30]

        if not liquid:
            return {"passed": False, "reason": "No whitelist pair passed baseline liquidity screening.", "candidates": []}

        selected: List[Dict[str, Any]] = []
        llm_used = False

        if self.llm and self.llm.enabled:
            prompt = PROMPT_NARRATIVE_V3 if getattr(SOP, "STAGED_EXITS", False) else PROMPT_NARRATIVE
            parsed = self.llm.ask_json(
                prompt,
                json.dumps({"task": "Select up to 5 strongest narratives", "candidates": liquid}, indent=2),
            )
            if parsed and isinstance(parsed.get("selected"), list):
                allowed = {c["symbol"] for c in liquid}
                selected = [
                    {
                        "symbol": str(s.get("symbol", "")).upper(),
                        "narrative": s.get("narrative", "Unspecified"),
                        "thesis": s.get("thesis", ""),
                        "strength": max(1, min(10, int(s.get("strength") or 5))),
                    }
                    for s in parsed["selected"]
                    if str(s.get("symbol", "")).upper() in allowed
                ]
                if getattr(SOP, "STAGED_EXITS", False):
                    if str(parsed.get("marketRegime", "")).lower() == "risk-off":
                        log("INFO", "STAGE 1 (LLM): marketRegime=risk-off — الانسحاب قرار، لا مرشحين")
                        return {"passed": False, "llm_used": True,
                                "reason": "LLM regime veto: risk-off.", "candidates": []}
                    # ضبط قطاعي إلزامي بعد الرد: سقف رمزين لكل قطاع (حتى لو تجاوز النموذج)
                    sector_counts: Dict[str, int] = {}
                    diversified: List[Dict[str, Any]] = []
                    for s in selected:
                        raw = parsed["selected"]
                        sector = next((str(x.get("sector", s["narrative"])) for x in raw
                                       if str(x.get("symbol", "")).upper() == s["symbol"]), s["narrative"])
                        if sector_counts.get(sector, 0) >= 2:
                            continue
                        sector_counts[sector] = sector_counts.get(sector, 0) + 1
                        diversified.append(s)
                    selected = diversified
                selected = selected[:SOP.NARRATIVE_SHORTLIST_SIZE]
                llm_used = bool(selected)

        if not selected:
            selected = self.deterministic_shortlist(liquid)

        log("INFO", f"STAGE 1 ({'LLM' if llm_used else 'deterministic'}): "
                    f"{', '.join(s['symbol'] for s in selected) or 'none'}")
        return {
            "passed": bool(selected),
            "llm_used": llm_used,
            "reason": "Narrative shortlist produced." if selected else "No defensible narrative.",
            "candidates": selected,
        }


class OnChainAgent:
    """STAGE 2 — liquidity, volume surge and order-book accumulation check."""

    name = "OnChainAgent"

    def __init__(self, client: BinanceClient, llm: Optional[KeylessLLM] = None):
        self.client = client
        self.llm = llm

    def metrics(self, symbol: str) -> Dict[str, Any]:
        ticker = self.client.ticker_24h(symbol)
        book = self.client.order_book(symbol)
        daily = self.client.klines(symbol, "1d", 31)
        closed = daily[:-1]
        avg_30d = sum(c.quote_volume for c in closed) / max(len(closed), 1)

        return {
            "symbol": symbol,
            "last_price": ticker["last_price"],
            "price_change_24h_pct": ticker["price_change_pct"],
            "quote_volume_24h_usd": round(ticker["quote_volume"]),
            "avg_quote_vol_30d_usd": round(avg_30d),
            "volume_surge_ratio": round(ticker["quote_volume"] / avg_30d, 2) if avg_30d > 0 else 0.0,
            "spread_pct": round(book["spread_pct"], 4),
            "depth_usd": round(book["total_depth_usd"]),
            "bid_ask_imbalance": round(book["bid_ask_imbalance"], 2),
        }

    @staticmethod
    def gate(m: Dict[str, Any]) -> Tuple[bool, List[str]]:
        failures: List[str] = []
        if m["quote_volume_24h_usd"] < SOP.MIN_24H_QUOTE_VOLUME_USD:
            failures.append(f"24h volume {fmt_money(m['quote_volume_24h_usd'])} < {fmt_money(SOP.MIN_24H_QUOTE_VOLUME_USD)}")
        if m["volume_surge_ratio"] < SOP.VOLUME_SURGE_RATIO:
            failures.append(f"Volume surge {m['volume_surge_ratio']}x < {SOP.VOLUME_SURGE_RATIO}x")
        if m["depth_usd"] < SOP.MIN_ORDERBOOK_DEPTH_USD:
            failures.append(f"1% depth {fmt_money(m['depth_usd'])} too thin")
        if m["spread_pct"] > SOP.MAX_SPREAD_PCT:
            failures.append(f"Spread {m['spread_pct']}% too wide")
        return (not failures), failures

    @staticmethod
    def deterministic_accumulation(m: Dict[str, Any]) -> Dict[str, Any]:
        accumulation = m["bid_ask_imbalance"] >= 1.0 and m["price_change_24h_pct"] < 25
        return {
            "accumulation": accumulation,
            "confidence": 60,
            "comment": (f"Volume {m['volume_surge_ratio']}x average, bid/ask depth ratio "
                        f"{m['bid_ask_imbalance']}, 24h move {m['price_change_24h_pct']}%."),
        }

    def run(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        log("INFO", f"STAGE 2 — OnChainAgent: verifying {len(candidates)} candidates…")
        survivors: List[Dict[str, Any]] = []

        for cand in candidates:
            try:
                m = self.metrics(cand["symbol"])
            except BinanceError as exc:
                log("WARN", f"{self.name}: {cand['symbol']} -> {str(exc)[:80]}")
                continue
            passed, failures = self.gate(m)
            log("DEBUG", f"  {cand['symbol']}: vol={fmt_money(m['quote_volume_24h_usd'])} "
                         f"surge={m['volume_surge_ratio']}x -> {'PASS' if passed else 'FAIL: ' + '; '.join(failures)}")
            if passed:
                survivors.append({**cand, "metrics": m})

        if not survivors:
            return {"passed": False, "reason": "No candidate met liquidity / volume-surge thresholds.", "survivors": []}

        verdicts: Dict[str, Dict[str, Any]] = {}
        llm_used = False
        if self.llm and self.llm.enabled:
            parsed = self.llm.ask_json(
                PROMPT_ONCHAIN,
                json.dumps({"data": [s["metrics"] for s in survivors]}, indent=2),
            )
            if parsed and isinstance(parsed.get("assessments"), list):
                verdicts = {str(a.get("symbol", "")).upper(): a for a in parsed["assessments"]}
                llm_used = bool(verdicts)

        final: List[Dict[str, Any]] = []
        for s in survivors:
            v = verdicts.get(s["symbol"])
            verdict = (
                {"accumulation": bool(v.get("accumulation")),
                 "confidence": int(v.get("confidence") or 60),
                 "comment": v.get("comment") or ""}
                if v else self.deterministic_accumulation(s["metrics"])
            )
            if verdict["accumulation"]:
                final.append({**s, **verdict})

        log("INFO", f"STAGE 2 ({'LLM' if llm_used else 'deterministic'}): "
                    f"{', '.join(s['symbol'] for s in final) or 'none'}")
        return {
            "passed": bool(final),
            "llm_used": llm_used,
            "reason": "Liquidity & accumulation confirmed." if final else "No accumulation signature detected.",
            "survivors": final,
        }


class TechnicalAgent:
    """STAGE 3 — D1 trend + H4 consolidation breakout + RSI band."""

    name = "TechnicalAgent"

    def __init__(self, client: BinanceClient, llm: Optional[KeylessLLM] = None):
        self.client = client
        self.llm = llm

    def analyze(self, symbol: str) -> Dict[str, Any]:
        # [MHF-V3.4-5M-AGGREGATION] قرار الدخول يتغذى من D1/H4 مكوَّنة من 5د (ذيل حي متجدد)
        d1_c = self.client.klines_live(symbol, SOP.TF_D1, SOP.KLINE_LIMIT)
        h4_c = self.client.klines_live(symbol, SOP.TF_H4, SOP.KLINE_LIMIT)
        d1 = Indicators.analyze_timeframe(d1_c)
        h4 = Indicators.analyze_timeframe(h4_c)
        # [MHF-FINGERPRINT] مفتاح إشارة مستقر: فتح آخر شمعة H4 — إشارة واحدة فقط لكل شمعة
        bar_open_ms = h4_c[-1].open_time if h4_c else None
        h4["bar_open_ms"] = bar_open_ms
        candle_time = (datetime.fromtimestamp(bar_open_ms / 1000, tz=timezone.utc).isoformat()
                       if bar_open_ms else "")
        return {"symbol": symbol, "d1": d1, "h4": h4, "candle_time": candle_time}

    @staticmethod
    def gate(ta: Dict[str, Any]) -> Tuple[bool, List[str]]:
        d1, h4 = ta["d1"], ta["h4"]
        failures: List[str] = []
        if not d1["uptrend"]:
            failures.append(f"D1 not bullish (EMA20 {d1['ema20']} <= EMA50 {d1['ema50']})")
        # v3: يكفي تحقق إحدى عائلتي الإعداد — اختراق تجميع أو تراجع مع الاتجاه
        pb = h4.get("pullback_dip", {})
        is_breakout = bool(h4["breakout"]["breakout"])
        is_pullback = bool(pb.get("pullback"))
        if not is_breakout and not is_pullback:
            failures.append(f"H4 setup missing ({h4['breakout']['reason']}; {pb.get('reason', 'no pullback')})")
        elif is_breakout and not h4["rsi_in_range"]:
            failures.append(f"H4 RSI {h4['rsi14']} outside {SOP.RSI_MIN}-{SOP.RSI_MAX}")
        if d1["rsi14"] is not None and d1["rsi14"] >= SOP.D1_RSI_OVERBOUGHT:
            failures.append(f"D1 RSI {d1['rsi14']} overbought")
        return (not failures), failures

    def run(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        log("INFO", f"STAGE 3 — TechnicalAgent: analysing {len(candidates)} candidates…")
        survivors: List[Dict[str, Any]] = []

        for cand in candidates:
            try:
                ta = self.analyze(cand["symbol"])
            except BinanceError as exc:
                log("WARN", f"{self.name}: {cand['symbol']} -> {str(exc)[:80]}")
                continue
            passed, failures = self.gate(ta)
            log("DEBUG", f"  {cand['symbol']}: D1up={ta['d1']['uptrend']} "
                         f"H4brk={ta['h4']['breakout']['breakout']} RSI={ta['h4']['rsi14']} "
                         f"-> {'PASS' if passed else 'FAIL: ' + '; '.join(failures)}")
            if passed:
                survivors.append({**cand, "ta": ta})

        if not survivors:
            return {"passed": False, "reason": "No candidate satisfied D1 trend + H4 breakout + RSI band.", "survivors": []}

        validations: Dict[str, Dict[str, Any]] = {}
        llm_used = False
        if self.llm and self.llm.enabled:
            parsed = self.llm.ask_json(
                PROMPT_TECHNICAL,
                json.dumps({"candidates": [
                    {"symbol": s["symbol"], "d1": s["ta"]["d1"], "h4": s["ta"]["h4"]} for s in survivors
                ]}, indent=2, default=str),
            )
            if parsed and isinstance(parsed.get("validations"), list):
                validations = {str(v.get("symbol", "")).upper(): v for v in parsed["validations"]}
                llm_used = bool(validations)

        final: List[Dict[str, Any]] = []
        for s in survivors:
            v = validations.get(s["symbol"])
            auto = (f"D1 EMA20 {s['ta']['d1']['ema20']} > EMA50 {s['ta']['d1']['ema50']}; "
                    f"H4 breakout above {s['ta']['h4']['breakout']['range_high']} on "
                    f"{s['ta']['h4']['breakout']['volume_ratio']}x volume, RSI {s['ta']['h4']['rsi14']}.")
            if v is not None and not bool(v.get("valid")):
                continue  # LLM veto
            final.append({
                **s,
                "technical_confidence": int(v.get("confidence") or 65) if v else 65,
                "technical_summary": (v.get("summary") if v else None) or auto,
            })

        final.sort(key=lambda s: s["technical_confidence"], reverse=True)
        log("INFO", f"STAGE 3 ({'LLM' if llm_used else 'deterministic'}): "
                    f"{', '.join(s['symbol'] for s in final) or 'none'}")
        return {
            "passed": bool(final),
            "llm_used": llm_used,
            "reason": "Technical structure validated." if final else "All setups vetoed.",
            "survivors": final,
        }


class RiskManager:
    """STAGE 4 — pure deterministic math. No LLM is ever consulted here."""

    name = "RiskManager"

    def __init__(self, client: Optional[BinanceClient] = None, journal: Optional[Journal] = None):
        self.client = client
        self.journal = journal

    # ---- THE CORE SOP FORMULAS ------------------------------------------------
    @staticmethod
    def compute_levels(entry_price: float, position_size_usd: float = SOP.POSITION_SIZE_USD) -> Dict[str, float]:
        """
        StopLossPrice   = EntryPrice * (1 - (8  / PositionSizeInUSD))
        TakeProfitPrice = EntryPrice * (1 + (24 / PositionSizeInUSD))
        """
        stop_loss = entry_price * (1 - (SOP.MAX_RISK_PER_TRADE_USD / position_size_usd))
        take_profit = entry_price * (1 + (SOP.TARGET_PROFIT_PER_TRADE_USD / position_size_usd))
        staged = bool(getattr(SOP, "STAGED_EXITS", False))
        if staged:
            tp1 = entry_price * (1 + SOP.STAGE1_TP_PCT / 100.0)
            tp2 = entry_price * (1 + SOP.STAGE2_TP_PCT / 100.0)
            reward = position_size_usd * 0.5 * (SOP.STAGE1_TP_PCT + SOP.STAGE2_TP_PCT) / 100.0
            take_profit = tp2  # مرجعية الرصد الصحفي: نهاية الأدراج
        else:
            tp1 = tp2 = take_profit
            reward = SOP.TARGET_PROFIT_PER_TRADE_USD
        quantity = position_size_usd / entry_price
        return {
            "entry_price": entry_price,
            "position_size_usd": position_size_usd,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "stop_limit_price": stop_loss * 0.998,
            "risk_usd": SOP.MAX_RISK_PER_TRADE_USD,
            "reward_usd": reward,
            "risk_reward_ratio": SOP.RISK_REWARD_RATIO,
            "staged_exits": staged,
            "stop_loss_pct": round((stop_loss - entry_price) / entry_price * 100, 2),
            "take_profit_pct": round((take_profit - entry_price) / entry_price * 100, 2),
        }

    def run(self, candidate: Optional[Dict[str, Any]], stage_flags: Dict[str, bool]) -> Dict[str, Any]:
        log("INFO", f"STAGE 4 — RiskManager: validating {candidate['symbol'] if candidate else 'n/a'}…")

        if not all(stage_flags.values()):
            return {"approved": False, "reason": "Triple Confirmation failed (all three agents must pass)."}
        if not candidate:
            return {"approved": False, "reason": "No candidate survived the pipeline."}

        if self.journal:
            breakers = self.journal.check_circuit_breakers()
            if not breakers["allowed"]:
                return {"approved": False, "reason": "Circuit breaker: " + " | ".join(breakers["reasons"])}
            if self.journal.has_active(candidate["symbol"]):
                return {"approved": False, "reason": f"Position already open on {candidate['symbol']}."}
            committed = self.journal.committed_capital()
            if committed + SOP.POSITION_SIZE_USD > SOP.ACCOUNT_CAPITAL_USD:
                return {"approved": False,
                        "reason": f"Insufficient allocation: {fmt_money(committed)} of {fmt_money(SOP.ACCOUNT_CAPITAL_USD)} committed."}

        entry_price = self.client.price(candidate["symbol"]) if self.client else candidate["ta"]["h4"]["last_close"]
        levels = self.compute_levels(entry_price)

        quantity = levels["quantity"]
        if self.client:
            filters = self.client.symbol_filters(candidate["symbol"])
            quantity = BinanceClient.round_step(quantity, filters["step_size"])
            if quantity < filters["min_qty"]:
                return {"approved": False, "reason": f"Quantity {quantity} below exchange minimum {filters['min_qty']}."}
            if SOP.POSITION_SIZE_USD < filters["min_notional"]:
                return {"approved": False, "reason": f"Position below min notional {filters['min_notional']}."}

        signal = {
            "id": f"T-{int(time.time() * 1000)}-{candidate['symbol'].replace('USDT', '')}",
            "symbol": candidate["symbol"],
            "direction": "SPOT LONG",
            # [MHF-FINGERPRINT] مفتاح الإشارة الخارجي المستقر (فتح شمعة الإعداد H4) — منع التكرار مع مسح 5 دقائق
            "candle_time": (candidate.get("ta") or {}).get("candle_time", ""),
            **levels,
            "quantity": quantity,
            "rationale": {
                "narrative": candidate.get("narrative"),
                "thesis": candidate.get("thesis"),
                "onchain": candidate.get("comment"),
                "metrics": candidate.get("metrics"),
                "technical": candidate.get("technical_summary"),
                "confidence": candidate.get("technical_confidence"),
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        log("INFO", f"STAGE 4 APPROVED {signal['symbol']} entry={fmt_price(entry_price)} "
                    f"SL={fmt_price(levels['stop_loss'])} TP={fmt_price(levels['take_profit'])}")
        return {"approved": True, "reason": "All checks passed.", "signal": signal}


# ==============================================================================
# SECTION 8 — PIPELINE ORCHESTRATOR
# ==============================================================================


class StrategyPipeline:
    """Runs the 4 stages sequentially with early exit on any failure."""

    def __init__(self, use_llm: bool = True, journal: Optional[Journal] = None):
        self.client = BinanceClient()
        self.llm = KeylessLLM(enabled=use_llm)
        self.journal = journal or Journal()
        self.narrative = NarrativeAgent(self.client, self.llm)
        self.onchain = OnChainAgent(self.client, self.llm)
        self.technical = TechnicalAgent(self.client, self.llm)
        self.risk = RiskManager(self.client, self.journal)
        # [MHF-V3.1-CRASH-SENTINEL] العضو الخامس — حكم يومي مخزَّن قرب سجل الصفقات
        sentinel_state = (os.path.join(os.path.dirname(self.journal.path), "crash_sentinel.json")
                          if getattr(self.journal, "path", None) else None)
        self.sentinel = CrashSentinel(self.client, self.llm, state_path=sentinel_state)
        # [MHF-V3.2-FIVE-ENGINES] العضو السادس (انفجار) + سجل القمع المستدام — تخزين بمحاذاة السجل
        state_dir = os.path.dirname(self.journal.path) if getattr(self.journal, "path", None) else None
        self.moonshot = MoonshotSentinel(
            self.client, self.llm,
            state_path=(os.path.join(state_dir, "moonshot_sentinel.json") if state_dir else None))
        self.funnel = FunnelLedger(
            os.path.join(state_dir, "funnel_ledger.jsonl") if state_dir else "funnel_ledger.jsonl")
        self._stage_counts = {"s1": 0, "s2": 0, "s3": 0, "signal": 0}
        self._moonshot_verdict: Optional[Dict[str, Any]] = None

    def run(self) -> Dict[str, Any]:
        """واجهة المسح — تغلف التنفيذ بتدوين قمع المراحل مهما كان مسار الخروج (لا يرمي أبداً)."""
        try:
            return self._run_impl()
        finally:
            c = self._stage_counts
            try:
                self.funnel.record(datetime.now(timezone.utc).isoformat()[:10],
                                   c["s1"], c["s2"], c["s3"], c["signal"])
            except Exception:
                pass
            self._stage_counts = {"s1": 0, "s2": 0, "s3": 0, "signal": 0}

    def _run_impl(self) -> Dict[str, Any]:
        started = time.time()
        self.journal.reconcile()

        breakers = self.journal.check_circuit_breakers()
        if not breakers["allowed"]:
            log("WARN", "Scan aborted by circuit breakers: " + " | ".join(breakers["reasons"]))
            return {"ok": False, "halted": True, "reason": " | ".join(breakers["reasons"])}

        s1 = self.narrative.run()
        self._stage_counts["s1"] = len(s1.get("candidates", []))
        if not s1["passed"]:
            return {"ok": False, "reason": f"Stage 1 failed: {s1['reason']}", "duration": time.time() - started}

        # [MHF-V3-UPGRADE] بوابة نظام السوق — لا مسح وBTC تحت EMA20/EMA50 يومي (جلب واحد، غير حاجب عند التعذر)
        if getattr(SOP, "BTC_REGIME_GATE", False) or getattr(SOP, "CRASH_SENTINEL", False):
            try:
                # [MHF-V3.4-5M-AGGREGATION] بوابة BTC أيضاً تتغذى من 5د (ذيل حي كل مسح)
                btc_d1 = self.client.klines_live("BTCUSDT", SOP.TF_D1, SOP.DAILY_LOOKBACK)
                if getattr(SOP, "BTC_REGIME_GATE", False):
                    btc_trend = Backtester._daily_trend_map(btc_d1)
                    if btc_trend and not btc_trend[-1][1]:
                        return {"ok": False,
                                "reason": f"BTC regime gate: BTCUSDT daily EMA20<=EMA50 (قف {btc_trend[-1][0]}).",
                                "duration": time.time() - started}
                # [MHF-V3.1-CRASH-SENTINEL] بوابة التنبؤ بالانهيار — حتمي + حكم LLM اليومي المخزَّن
                if getattr(SOP, "CRASH_SENTINEL", False):
                    verdict = self.sentinel.assess(btc_d1=btc_d1)
                    if verdict.get("veto"):
                        return {"ok": False,
                                "reason": f"CrashSentinel veto ({verdict['source']}): {verdict['reason']}",
                                "duration": time.time() - started}
                # [MHF-V3.2-FIVE-ENGINES] حكم الانفجار — تعزيز فقط (لا يمنع ولا يخفف أي بوابة أبداً)
                if getattr(SOP, "MOONSHOT_SENTINEL", False):
                    self._moonshot_verdict = self.moonshot.assess(
                        btc_d1=btc_d1, candidates=[c["symbol"] for c in s1.get("candidates", [])])
                else:
                    self._moonshot_verdict = {"moonshot": False, "boost_symbols": []}
            except BinanceError as e:
                log("WARN", f"BTC regime gate fetch failed (non-blocking): {e}")
            except Exception as e:
                log("WARN", f"BTC regime gate failed (non-blocking): {type(e).__name__}: {e}")
        else:
            self._moonshot_verdict = self.moonshot.assess() if getattr(SOP, "MOONSHOT_SENTINEL", False) \
                else {"moonshot": False, "boost_symbols": []}

        s2 = self.onchain.run(s1["candidates"])
        self._stage_counts["s2"] = len(s2.get("survivors", []))
        if not s2["passed"]:
            return {"ok": False, "reason": f"Stage 2 failed: {s2['reason']}", "duration": time.time() - started}

        s3 = self.technical.run(s2["survivors"])
        self._stage_counts["s3"] = len(s3.get("survivors", []))
        if not s3["passed"]:
            return {"ok": False, "reason": f"Stage 3 failed: {s3['reason']}", "duration": time.time() - started}

        s4 = self.risk.run(s3["survivors"][0], {"n": s1["passed"], "o": s2["passed"], "t": s3["passed"]})
        if not s4["approved"]:
            return {"ok": False, "reason": f"Stage 4 rejected: {s4['reason']}", "duration": time.time() - started}

        self._stage_counts["signal"] = 1
        signal = s4["signal"]
        # [MHF-V3.2-FIVE-ENGINES] تعزيز الإيقاف الزمني لراكبي الموجة (نظام انفجار أو رمز معزز يومياً)
        mv = self._moonshot_verdict or {"moonshot": False, "boost_symbols": []}
        # التمديد المقيس مرفوض بمحاكاة المحفظة — التعزيز تلميتري/تنبيه فقط طالما TIME_STOP_EXT_ENABLE=False
        if getattr(SOP, "STAGED_EXITS", False) and getattr(SOP, "TIME_STOP_EXT_ENABLE", False):
            boosted = bool(mv.get("moonshot")) or signal.get("symbol") in (mv.get("boost_symbols") or [])
            if boosted:
                signal["moonshot_boost"] = True
                signal["time_stop_days"] = max(
                    1, int(getattr(SOP, "TIME_STOP_DAYS", 10) * getattr(SOP, "MOONSHOT_TSTOP_MULT", 2.0)))
                log("INFO", f"MOONSHOT boost applied to {signal['symbol']}: time_stop={signal['time_stop_days']}d")
        return {"ok": True, "signal": signal, "duration": time.time() - started}


# ==============================================================================
# SECTION 9 — BACKTESTER (exact SOP rules on historical candles)
# ==============================================================================


@dataclass
class BacktestResult:
    symbol: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0               # v3: تعادل بعد تحقيق T1 (قمة/وقف عند التعادل)
    open_at_end: int = 0
    pnl_usd: float = 0.0
    setups: Dict[str, int] = field(default_factory=dict)  # v3: breakout/pullback
    sentinel_blocks: int = 0                # v3.1: دخولات منعها محرك التنبؤ بالانهيارات
    log: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return round(self.wins / self.trades * 100, 1) if self.trades else 0.0

    @property
    def non_losing_rate(self) -> float:
        return round((self.wins + self.scratches) / self.trades * 100, 1) if self.trades else 0.0

    def summary(self) -> str:
        blocks = f" blocks={self.sentinel_blocks}" if self.sentinel_blocks else ""
        return (f"{self.symbol:<12} trades={self.trades:<3} W/S/L={self.wins}/{self.scratches}/{self.losses:<3} "
                f"win%={self.win_rate:<6} non-losing%={self.non_losing_rate:<6} PnL={fmt_money(self.pnl_usd)}{blocks}")


class Backtester:
    """
    Walks historical H4 candles and applies the EXACT entry/exit rules:
      ENTRY : D1 uptrend (EMA20>EMA50) AND H4 consolidation breakout AND 35<RSI<65
      EXIT  : stop loss (-6.4%) or take profit (+19.2%), intrabar, stop checked first
    Conservative assumptions: one position per symbol at a time, stop takes
    precedence when both levels are touched inside the same candle.
    """

    def __init__(self, client: Optional[BinanceClient] = None):
        self.client = client or BinanceClient()
        self._btc_d1_cache: Optional[Sequence[Candle]] = None  # يُعاد استخدامها على رموز الجولة الواحدة

    # ---- [MHF-V3.2-FIVE-ENGINES] نواة مشتركة بين مسار الزوج الواحد ومحاكاة المحفظة ----------
    @staticmethod
    def _cost_rate() -> float:
        """معدل كلفة الطرف الواحد (عمولة+انزلاق) — صفر في v2 ⟵ رياضيات v2 حرفية بلا تغيير."""
        if not getattr(SOP, "SIM_FEES", False):
            return 0.0
        return (SOP.SIM_FEE_PCT + SOP.SIM_SLIPPAGE_PCT) / 100.0

    @staticmethod
    def _setup_of(window: Sequence[Candle]) -> Optional[str]:
        """إعداد H4 عند آخر شمعة مغلقة: اختراق (بنطاق RSI) أو تراجع صحي (v3)."""
        closes = [c.close for c in window]
        rsi_val = Indicators.rsi(closes, SOP.RSI_PERIOD)
        if rsi_val is None:
            return None
        brk = Indicators.consolidation_breakout(window)
        if brk["breakout"] and (SOP.RSI_MIN < rsi_val < SOP.RSI_MAX):
            return "breakout"
        if bool(getattr(SOP, "STAGED_EXITS", False)):
            pb = Indicators.pullback_dip(window)
            if pb["pullback"]:
                return "pullback"
        return None

    @classmethod
    def _close_amount(cls, position: Dict[str, Any], exit_price: float) -> float:
        """صافي PnL لإغلاق المتبقي — يخصم مخصومات الدخول المسجلة + كلفة خروج الكمية الباقية."""
        rate = cls._cost_rate()
        return (position["realized"] + (exit_price - position["entry_price"]) * position["qty_left"]
                - position.get("costs", 0.0) - exit_price * position["qty_left"] * rate)

    @staticmethod
    def _maybe_exit(position: Dict[str, Any], candle: Candle, i: int, staged: bool, rate: float
                    ) -> Optional[Tuple[float, str]]:
        """إدارة شمعة واحدة لمركز مفتوح — الأولوية ذاتها دائماً: وقف/BE ثم أهداف ثم زمن."""
        if candle.low <= position["stop_loss"]:
            return position["stop_loss"], ("BE_PROTECT" if position.get("half_done") else "STOP_LOSS")
        if not staged and candle.high >= position["tp2"]:
            return position["tp2"], "TAKE_PROFIT"
        if staged:
            if not position["half_done"] and candle.high >= position["tp1"]:
                half = position["quantity"] / 2.0
                position["realized"] += (position["tp1"] - position["entry_price"]) * half
                position["costs"] = position.get("costs", 0.0) + position["tp1"] * half * rate
                position["qty_left"] -= half
                position["half_done"] = True
                position["stop_loss"] = position["entry_price"]  # تعليق الوقف عند التعادل
            if position["half_done"] and candle.high >= position["tp2"]:
                return position["tp2"], "TAKE_PROFIT_T2"
        if position.get("tstop_bars") and (i - position["entry_i"]) >= position["tstop_bars"]:
            return candle.close, "TIME_STOP"
        return None

    @staticmethod
    def _daily_trend_map(d1: Sequence[Candle]) -> List[Tuple[int, bool, Optional[float]]]:
        """For each D1 candle, is EMA20 > EMA50 at its close (plus RSI)?"""
        closes = [c.close for c in d1]
        ema20 = Indicators.ema_series(closes, SOP.EMA_FAST)
        ema50 = Indicators.ema_series(closes, SOP.EMA_SLOW)
        rsi = Indicators.rsi_series(closes, SOP.RSI_PERIOD)

        out: List[Tuple[int, bool, Optional[float]]] = []
        off20 = len(closes) - len(ema20)
        off50 = len(closes) - len(ema50)
        offr = len(closes) - len(rsi)
        for i, candle in enumerate(d1):
            if i < off50 or i < off20:
                out.append((candle.close_time, False, None))
                continue
            fast = ema20[i - off20]
            slow = ema50[i - off50]
            r = rsi[i - offr] if i >= offr else None
            out.append((candle.close_time, fast > slow, r))
        return out

    def run(self, symbol: str, h4_limit: int = 1000, d1_limit: int = 500) -> BacktestResult:
        result = BacktestResult(symbol=symbol)
        h4 = self.client.klines(symbol, SOP.TF_H4, h4_limit)
        d1 = self.client.klines(symbol, SOP.TF_D1, d1_limit)
        btc_d1 = None
        if getattr(SOP, "BTC_REGIME_GATE", False) and self.client is not None and symbol != "BTCUSDT":
            if self._btc_d1_cache is None:
                try:
                    self._btc_d1_cache = self.client.klines("BTCUSDT", SOP.TF_D1, d1_limit)
                except BinanceError:
                    self._btc_d1_cache = []  # تعذر الجلب لا يفتح البوابة ولا يغلقها — محافظة على القياس
            btc_d1 = self._btc_d1_cache or None
        return self.run_on_data(symbol, h4, d1, btc_d1)

    def run_on_data(self, symbol: str, h4: Sequence[Candle], d1: Sequence[Candle],
                    btc_d1: Optional[Sequence[Candle]] = None) -> BacktestResult:
        result = BacktestResult(symbol=symbol)
        trend = self._daily_trend_map(d1)
        if not trend or len(h4) < SOP.EMA_SLOW + SOP.BREAKOUT_LOOKBACK + 5:
            return result

        def trend_at(ts: int) -> Tuple[bool, Optional[float]]:
            """Most recent CLOSED daily bar before timestamp ts (no look-ahead)."""
            state, drsi = False, None
            for close_time, up, r in trend:
                if close_time <= ts:
                    state, drsi = up, r
                else:
                    break
            return state, drsi

        btc_map = self._daily_trend_map(btc_d1) if btc_d1 else None

        def btc_up_at(ts: int) -> bool:
            if not btc_map:
                return True
            state = False
            for close_time, up, _ in btc_map:
                if close_time <= ts:
                    state = up
                else:
                    break
            return state

        # [MHF-V3.1-CRASH-SENTINEL] نوافذ عاصفة BTC المحسوبة مسبقاً (عائد 3 أيام متدحرج — بلا lookahead)
        storm_windows: List[Tuple[int, bool]] = []
        if btc_d1 and getattr(SOP, "CRASH_SENTINEL", False):
            threshold = SOP.CRASH_BTC_RET3_THRESHOLD
            closes_b = [c.close for c in btc_d1]
            for i, c in enumerate(btc_d1):
                storm = i >= 3 and (closes_b[i] / closes_b[i - 3] - 1) * 100.0 <= threshold
                storm_windows.append((c.close_time, bool(storm)))

        def crash_veto_at(ts: int) -> bool:
            state = False
            for close_time, storm in storm_windows:
                if close_time <= ts:
                    state = storm
                else:
                    break
            return state

        # [MHF-V3.2-FIVE-ENGINES] خريطة تمديد الإيقاف الزمني — [M5-EXTENSION-MEASURED]
        # الرافعة المقيسة: التمديد خارج العواصف (عائد 3أيام ≥ TIME_STOP_EXT_RET3_MIN)، وليس في الانفجار فحسب
        moonshot_windows: List[Tuple[int, bool]] = []
        ext_on = bool(getattr(SOP, "TIME_STOP_EXT_ENABLE", False))
        if btc_d1 and ext_on:
            m_th = getattr(SOP, "TIME_STOP_EXT_RET3_MIN", -3.0)
            closes_m = [c.close for c in btc_d1]
            for i, c in enumerate(btc_d1):
                moon = i >= 3 and (closes_m[i] / closes_m[i - 3] - 1) * 100.0 >= m_th
                moonshot_windows.append((c.close_time, bool(moon)))

        def moonshot_at(ts: int) -> bool:
            state = False
            for close_time, moon in moonshot_windows:
                if close_time <= ts:
                    state = moon
                else:
                    break
            return state

        staged = bool(getattr(SOP, "STAGED_EXITS", False))
        rate = self._cost_rate()
        base_tstop_bars = int(getattr(SOP, "TIME_STOP_DAYS", 0) or 0) * 6  # 6 شموع H4 لليوم

        def tstop_bars_at(ts: int) -> int:
            if not base_tstop_bars:
                return 0
            mult = getattr(SOP, "MOONSHOT_TSTOP_MULT", 1.0) if moonshot_at(ts) else 1.0
            return max(1, int(base_tstop_bars * mult))

        def close_trade(position, exit_price, outcome, exit_ts):
            pnl = self._close_amount(position, exit_price)
            result.trades += 1
            result.pnl_usd += pnl
            if pnl > 0.01:
                result.wins += 1
            elif pnl < -0.01:
                result.losses += 1
            else:
                result.scratches += 1
            result.log.append({
                "entry_ts": position["entry_time"],
                "entry_time": datetime.fromtimestamp(position["entry_time"] / 1000, tz=timezone.utc).isoformat()[:16],
                "exit_time": datetime.fromtimestamp(exit_ts / 1000, tz=timezone.utc).isoformat()[:16],
                "entry": round(position["entry_price"], 8),
                "exit": round(exit_price, 8),
                "outcome": outcome,
                "setup": position.get("setup", "breakout"),
                "pnl_usd": round(pnl, 2),
            })

        position: Optional[Dict[str, Any]] = None
        start = SOP.EMA_SLOW + SOP.BREAKOUT_LOOKBACK + 1

        for i in range(start, len(h4)):
            candle = h4[i]

            # ---------------- manage an open position (intrabar) ----------------
            if position:
                if position["qty_left"] <= 1e-12:
                    position = None
                    continue
                res = self._maybe_exit(position, candle, i, staged, rate)
                if res is not None:
                    close_trade(position, res[0], res[1], candle.close_time)
                    position = None
                    continue
                continue  # never enter on the same bar we exited

            # ---------------- look for a new entry ----------------
            window = h4[: i + 1]
            daily_up, daily_rsi = trend_at(candle.close_time)
            if not daily_up:
                continue
            if daily_rsi is not None and daily_rsi >= SOP.D1_RSI_OVERBOUGHT:
                continue
            if not btc_up_at(candle.close_time):
                continue
            if crash_veto_at(candle.close_time):
                result.sentinel_blocks += 1
                continue

            setup = self._setup_of(window)
            if setup is None:
                continue

            entry_price = candle.close
            levels = RiskManager.compute_levels(entry_price)
            position = {
                "entry_time": candle.close_time,
                "entry_i": i,
                "entry_price": entry_price,
                "quantity": levels["quantity"],
                "qty_left": levels["quantity"],
                "realized": 0.0,
                "costs": entry_price * levels["quantity"] * rate,
                "half_done": False,
                "stop_loss": levels["stop_loss"],
                "tp1": levels["take_profit_1"],
                "tp2": levels["take_profit_2"],
                "tstop_bars": tstop_bars_at(candle.close_time),
                "setup": setup,
            }
            result.setups[setup] = result.setups.get(setup, 0) + 1

        if position:
            result.open_at_end = 1
        return result

    # ---- [MHF-V3.2-FIVE-ENGINES] محاكاة محفظة حقيقية بقيد ≤3 مراكز متزامنة -------------------
    def _collect_candidates(self, symbol: str, h4: Sequence[Candle], d1: Sequence[Candle],
                            btc_d1: Optional[Sequence[Candle]]) -> List[Dict[str, Any]]:
        """مسح الدخولات المرشحة لرمز واحد بنفس بوابات run_on_data حرفياً (بدون تنفيذ — أحداث فقط)."""
        if len(h4) < SOP.EMA_SLOW + SOP.BREAKOUT_LOOKBACK + 5:
            return []
        trend = self._daily_trend_map(d1)
        if not trend:
            return []
        btc_map = self._daily_trend_map(btc_d1) if btc_d1 else None

        def first_before(ts: int, series) -> Any:
            state = None
            for close_time, *vals in series:
                if close_time <= ts:
                    state = vals
                else:
                    break
            return state

        storm_windows: List[Tuple[int, bool]] = []
        moon_windows: List[Tuple[int, bool]] = []
        if btc_d1:
            closes_b = [c.close for c in btc_d1]
            for i, c in enumerate(btc_d1):
                if i >= 3:
                    r3 = (closes_b[i] / closes_b[i - 3] - 1) * 100.0
                    storm_windows.append((c.close_time, bool(getattr(SOP, "CRASH_SENTINEL", False))
                                          and r3 <= getattr(SOP, "CRASH_BTC_RET3_THRESHOLD", -3.5)))
                    # [M5-EXTENSION-MEASURED] نفس خريطة التمديد غير العاصف في محاكاة المحفظة
                    moon_windows.append((c.close_time, bool(getattr(SOP, "TIME_STOP_EXT_ENABLE", False))
                                         and r3 >= getattr(SOP, "TIME_STOP_EXT_RET3_MIN", -3.0)))

        out: List[Dict[str, Any]] = []
        start = SOP.EMA_SLOW + SOP.BREAKOUT_LOOKBACK + 1
        for i in range(start, len(h4)):
            candle = h4[i]
            ts = candle.close_time
            tr = first_before(ts, trend)
            if not tr or not tr[0]:
                continue
            if tr[1] is not None and tr[1] >= SOP.D1_RSI_OVERBOUGHT:
                continue
            btm = first_before(ts, btc_map) if btc_map else None
            if btc_map and not (btm and btm[0]):
                continue
            stm = first_before(ts, storm_windows) if storm_windows else None
            storm = bool(stm[0]) if stm else False
            mon = first_before(ts, moon_windows) if moon_windows else None
            moon = bool(mon[0]) if mon else False
            setup = self._setup_of(h4[: i + 1])
            if setup is None:
                continue
            out.append({"i": i, "ts": ts, "symbol": symbol, "setup": setup,
                        "storm": storm, "moon": moon, "price": candle.close})
        return out

    def run_portfolio(self, data_map: Dict[str, Tuple[Sequence[Candle], Sequence[Candle]]],
                      btc_d1: Optional[Sequence[Candle]] = None) -> Dict[str, Any]:
        """محاكاة قيد المحفظة الحقيقي: ≤MAX_OPEN_POSITIONS مراكز عبر كل الأزواج + كلفة + بوابات v3.

        شريط H4 الموحد: جميع الأزواج على شبكة زمنية واحدة (مصدر واحد/حدود واحدة) —
        في كل شريط: إدارة المراكز المفتوحة أولاً (وقفٌ أولاً كالعادة) ثم قبول مرشحين حسب الشاغر.
        """
        staged = bool(getattr(SOP, "STAGED_EXITS", False))
        rate = self._cost_rate()
        base_tstop_bars = int(getattr(SOP, "TIME_STOP_DAYS", 0) or 0) * 6
        candidates: Dict[int, List[Dict[str, Any]]] = {}
        for sym in sorted(data_map.keys()):
            for cand in self._collect_candidates(sym, data_map[sym][0], data_map[sym][1], btc_d1):
                candidates.setdefault(cand["i"], []).append(cand)
        if not candidates:
            return {"trades": 0, "wins": 0, "scratches": 0, "losses": 0, "pnl_usd": 0.0,
                    "max_concurrent": 0, "queued_drops": 0, "open_at_end": 0, "log": []}

        open_pos: Dict[str, Dict[str, Any]] = {}
        max_concurrent = 0
        queued_drops = 0
        log_rows: List[Dict[str, Any]] = []
        totals = {"trades": 0, "wins": 0, "scratches": 0, "losses": 0, "pnl_usd": 0.0}
        max_i = max(
            max((len(v[0]) for v in data_map.values()), default=0),
            max(candidates.keys()) + 1,
        )

        for i in range(SOP.EMA_SLOW + SOP.BREAKOUT_LOOKBACK + 1, max_i):
            # -------- إدارة المفتوحة على شريط كل رمز --------
            for sym in sorted(list(open_pos.keys())):
                h4 = data_map[sym][0]
                if i >= len(h4):
                    continue
                candle = h4[i]
                pos = open_pos[sym]
                res = self._maybe_exit(pos, candle, i, staged, rate)
                if res is not None:
                    pnl = self._close_amount(pos, res[0])
                    totals["trades"] += 1
                    totals["pnl_usd"] += pnl
                    totals["wins" if pnl > 0.01 else "losses" if pnl < -0.01 else "scratches"] += 1
                    log_rows.append({
                        "entry_ts": pos["entry_time"],
                        "entry_time": datetime.fromtimestamp(pos["entry_time"] / 1000, tz=timezone.utc).isoformat()[:16],
                        "exit_time": datetime.fromtimestamp(candle.close_time / 1000, tz=timezone.utc).isoformat()[:16],
                        "symbol": sym, "entry": round(pos["entry_price"], 8),
                        "exit": round(res[0], 8), "outcome": res[1],
                        "setup": pos.get("setup", "breakout"), "pnl_usd": round(pnl, 2),
                    })
                    del open_pos[sym]
            # -------- قبول مرشحي هذا الشريط ضمن الشواغر --------
            for cand in sorted(candidates.get(i, []), key=lambda c: c["symbol"]):
                sym = cand["symbol"]
                if sym in open_pos:
                    continue  # نفس الرمز: صفقة واحدة في كل مرة (قاعدة محفوظة من run_on_data)
                h4 = data_map[sym][0]
                if i >= len(h4):
                    continue
                if cand["storm"]:
                    continue  # محرك التنبؤ بالانهيار: ممنوع حتى مع شاغر
                if len(open_pos) >= SOP.MAX_OPEN_POSITIONS:
                    queued_drops += 1
                    continue
                levels = RiskManager.compute_levels(cand["price"])
                mult = getattr(SOP, "MOONSHOT_TSTOP_MULT", 1.0) if cand["moon"] else 1.0
                open_pos[sym] = {
                    "entry_time": cand["ts"], "entry_i": i, "entry_price": cand["price"],
                    "quantity": levels["quantity"], "qty_left": levels["quantity"],
                    "realized": 0.0, "costs": cand["price"] * levels["quantity"] * rate,
                    "half_done": False, "stop_loss": levels["stop_loss"],
                    "tp1": levels["take_profit_1"], "tp2": levels["take_profit_2"],
                    "tstop_bars": max(1, int(base_tstop_bars * mult)) if base_tstop_bars else 0,
                    "setup": cand["setup"],
                }
                max_concurrent = max(max_concurrent, len(open_pos))

        log("INFO", f"PORTFOLIO-SIM: {totals['trades']} trades, max_concurrent={max_concurrent}, "
                    f"queued_drops={queued_drops}, pnl={fmt_money(totals['pnl_usd'])}")
        totals.update({"max_concurrent": max_concurrent, "queued_drops": queued_drops,
                       "open_at_end": len(open_pos), "log": log_rows})
        return totals


# ==============================================================================
# SECTION 10 — SELF-TEST (offline, no network)
# ==============================================================================


class RobustnessEngine:
    """[MHF-V3.2-FIVE-ENGINES] محرك المتانة: حكم خارج-العينة على ثوابت v3 بدل ثقة «داخل العينة».

    قسمة زمنية متتابعة (walk-forward مبسّط): نفس الباكتست بالثوابت الحالية كما هي،
    وتقسيم الصفقات بالمدخل الزمني entry_ts إلى طيات مستمرة — ثوابت لم تُعاد معايرتها
    داخل أي طية ⟵ مقاييس الطية اللاحقة اختبار خارج-العينة صادق للتجميد الحالي.
    """

    @staticmethod
    def run_walk_forward(data_map: Dict[str, Tuple[Sequence[Candle], Sequence[Candle]]],
                         btc_d1: Optional[Sequence[Candle]] = None,
                         folds: int = 3) -> Dict[str, Any]:
        bt = Backtester(client=None)
        rows = []
        for sym in sorted(data_map.keys()):
            h4, d1 = data_map[sym]
            r = bt.run_on_data(sym, h4, d1, btc_d1)
            for t in r.log:
                rows.append({"pnl_usd": t["pnl_usd"], "entry_ts": t["entry_ts"]})
        if not rows:
            return {"folds": [], "verdict": "INSUFFICIENT-DATA", "reason": "no trades"}
        times = sorted(t["entry_ts"] for t in rows)
        folds_out = []
        for k in range(folds):
            lo = times[int(k * len(times) / folds)]
            hi = times[min(len(times) - 1, int((k + 1) * len(times) / folds) - 1)] if k < folds - 1 else float("inf")
            seg = [t for t in rows if lo <= t["entry_ts"] <= hi]
            wins = sum(1 for t in seg if t["pnl_usd"] > 0.01)
            losses = sum(1 for t in seg if t["pnl_usd"] < -0.01)
            folds_out.append({
                "fold": k + 1, "trades": len(seg), "oos_win": wins,
                "oos_win_pct": round(wins / len(seg) * 100, 1) if seg else 0.0,
                "oos_pnl": round(sum(t["pnl_usd"] for t in seg), 2),
                "oos_losses": losses,
            })
        positive_folds = sum(1 for f in folds_out if f["oos_pnl"] > 0.0)
        verdict = ("ROBUST" if positive_folds == folds else
                   "ACCEPTABLE" if positive_folds >= folds - 1 else "FRAGILE")
        return {"folds": folds_out, "positive_folds": positive_folds,
                "verdict": verdict, "total_trades": len(rows)}


class FunnelLedger:
    """[MHF-V3.2-FIVE-ENGINES] قياس قمع مراحل الفريق حياً ومستداماً — يغلق M1 بالأمام لا بالافتراض.

    سطر JSON لكل مسح (اعدادات مرشحي المراحل 1-3 + وجود إشارة) في ملف بمحاذاة السجل —
    إحصاءاته تجيب «كم إشارة/يوم فعلاً؟» من الإنتاج مباشرة دون أي إعادة تشغيل تاريخية.
    """

    def __init__(self, path: str):
        self.path = path

    def record(self, day: str, stage1: int, stage2: int, stage3: int, signal: int) -> None:
        row = {"day": day, "stage1": stage1, "stage2": stage2, "stage3": stage3, "signal": signal,
               "ts": time.time()}
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            log("WARN", f"FunnelLedger record failed: {e}")

    def _rows(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        out = []
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
        except Exception as e:
            log("WARN", f"FunnelLedger read failed: {e}")
        return out

    def stats(self) -> Dict[str, Any]:
        rows = self._rows()
        days = sorted({r["day"] for r in rows}) if rows else []
        signals = sum(int(r.get("signal", 0)) for r in rows)
        s1 = sum(int(r.get("stage1", 0)) for r in rows)
        s3 = sum(int(r.get("stage3", 0)) for r in rows)
        return {
            "days": len(days),
            "scans": len(rows),
            "signals_total": signals,
            "signals_per_day": round(signals / len(days), 2) if days else 0.0,
            "stage1_total": s1,
            "stage3_total": s3,
            "stage1_to_stage3_pass_rate": round(s3 / s1 * 100, 1) if s1 else 0.0,
        }


def synthetic_series(n: int = 300, start: float = 10.0, drift: float = 0.004,
                     consolidate_from: int = 260, breakout: bool = True) -> List[Candle]:
    """Deterministic synthetic candles: trend -> consolidation -> breakout."""
    candles: List[Candle] = []
    price = start
    for i in range(n):
        if i < consolidate_from:
            price *= (1 + drift)
            vol = 1000 + (i % 7) * 10
        else:
            price *= (1 + (0.0015 if i % 2 == 0 else -0.0014))  # tight range
            vol = 900 + (i % 5) * 10
        high, low = price * 1.004, price * 0.996
        candles.append(Candle(
            open_time=i * 14_400_000, open=price, high=high, low=low, close=price,
            volume=vol, close_time=i * 14_400_000 + 14_399_999, quote_volume=price * vol,
        ))
    if breakout:
        last = candles[-1]
        bumped = last.close * 1.03
        candles[-1] = Candle(
            open_time=last.open_time, open=last.open, high=bumped * 1.002, low=last.low,
            close=bumped, volume=last.volume * 3.0, close_time=last.close_time,
            quote_volume=bumped * last.volume * 3.0,
        )
    return candles


def synthetic_market(n: int = 1200, seed: int = 7, drift: float = 0.0012,
                     vol: float = 0.012, tf_ms: int = 14_400_000) -> List[Candle]:
    """Deterministic pseudo-random trending market with realistic noise."""
    import random as _random
    rng = _random.Random(seed)
    price = 10.0
    out: List[Candle] = []
    for i in range(n):
        price *= (1 + drift + rng.gauss(0, vol))
        high = price * (1 + abs(rng.gauss(0, 0.004)))
        low = price * (1 - abs(rng.gauss(0, 0.004)))
        volume = 1000 * (1 + abs(rng.gauss(0, 0.5)))
        out.append(Candle(
            open_time=i * tf_ms, open=price, high=high, low=low, close=price,
            volume=volume, close_time=i * tf_ms + tf_ms - 1, quote_volume=price * volume,
        ))
    return out


def run_selftest() -> int:
    # [MHF-V3-UPGRADE] التحققات الرقمية أدناه مطابقة للدستور v2 حرفياً — تثبيت الملف الشخصي قبل أي قياس
    os.environ["MHF_SOP_PROFILE"] = "v2"
    _apply_sop_profile()
    print("=" * 78)
    print(" SELF-TEST — offline verification of the strategy engine")
    print("=" * 78)
    failures = 0

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal failures
        status = "PASS" if condition else "FAIL"
        if not condition:
            failures += 1
        print(f"  [{status}] {label}{(' — ' + detail) if detail else ''}")

    # ---- 1. SOP math -------------------------------------------------------
    print("\n[1] SOP MATH (the constitution)")
    lv = RiskManager.compute_levels(100.0, 125.0)
    realized_risk = (100.0 - lv["stop_loss"]) * lv["quantity"]
    realized_reward = (lv["take_profit"] - 100.0) * lv["quantity"]
    check("stop loss price = 93.6", abs(lv["stop_loss"] - 93.6) < 1e-9, f"{lv['stop_loss']}")
    check("take profit price = 119.2", abs(lv["take_profit"] - 119.2) < 1e-9, f"{lv['take_profit']}")
    check("quantity = 1.25", abs(lv["quantity"] - 1.25) < 1e-12, f"{lv['quantity']}")
    check("realized risk = $8.00", abs(realized_risk - 8.0) < 1e-9, f"{realized_risk:.10f}")
    check("realized reward = $24.00", abs(realized_reward - 24.0) < 1e-9, f"{realized_reward:.10f}")
    check("risk/reward = 1:3", abs(realized_reward / realized_risk - 3.0) < 1e-9)
    check("stop pct = -6.4%", abs(SOP.stop_loss_pct() + 6.4) < 1e-9, f"{SOP.stop_loss_pct()}")
    check("target pct = +19.2%", abs(SOP.take_profit_pct() - 19.2) < 1e-9, f"{SOP.take_profit_pct()}")

    # scale invariance
    lv2 = RiskManager.compute_levels(0.00001234, 125.0)
    r2 = (0.00001234 - lv2["stop_loss"]) * lv2["quantity"]
    check("risk stays $8 on micro-cap price", abs(r2 - 8.0) < 1e-6, f"{r2:.8f}")

    # ---- 2. Indicators -----------------------------------------------------
    print("\n[2] INDICATORS")
    flat = [10.0] * 60
    check("RSI of a flat series = 100 (no losses)", Indicators.rsi(flat) == 100.0)
    rising = [float(i) for i in range(1, 80)]
    check("EMA20 > EMA50 on a rising series",
          (Indicators.ema(rising, 20) or 0) > (Indicators.ema(rising, 50) or 0))
    known = [44, 44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
             46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22]
    rsi_known = Indicators.rsi(known, 14)
    check("Wilder RSI on reference data ~70", rsi_known is not None and 65 < rsi_known < 75, f"{rsi_known:.2f}")

    candles = synthetic_series()
    snap = Indicators.analyze_timeframe(candles)
    check("uptrend detected", snap["uptrend"], f"EMA20={snap['ema20']:.4f} EMA50={snap['ema50']:.4f}")
    check("consolidation breakout detected", snap["breakout"]["breakout"], snap["breakout"]["reason"])
    check("volume confirmation captured", snap["breakout"]["volume_ratio"] >= 1.2,
          f"{snap['breakout']['volume_ratio']}x")

    no_brk = Indicators.analyze_timeframe(synthetic_series(breakout=False))
    check("no false breakout when price stays in range", not no_brk["breakout"]["breakout"],
          no_brk["breakout"]["reason"])

    # ---- 3. Stage gates ----------------------------------------------------
    print("\n[3] AGENT GATES")
    ok_metrics = {"quote_volume_24h_usd": 1e8, "volume_surge_ratio": 1.8,
                  "depth_usd": 200_000, "spread_pct": 0.01,
                  "bid_ask_imbalance": 1.4, "price_change_24h_pct": 6.0}
    passed, failures_list = OnChainAgent.gate(ok_metrics)
    check("liquid pair passes stage 2", passed, "; ".join(failures_list))

    thin = {**ok_metrics, "quote_volume_24h_usd": 1e6}
    passed2, _ = OnChainAgent.gate(thin)
    check("illiquid pair rejected by stage 2", not passed2)

    no_surge = {**ok_metrics, "volume_surge_ratio": 1.1}
    passed3, _ = OnChainAgent.gate(no_surge)
    check("missing volume surge rejected", not passed3)

    good_ta = {"d1": {"uptrend": True, "ema20": 9, "ema50": 8, "rsi14": 60},
               "h4": {"rsi_in_range": True, "rsi14": 52, "breakout": {"breakout": True, "reason": "ok"}}}
    passed4, _ = TechnicalAgent.gate(good_ta)
    check("valid setup passes stage 3", passed4)

    hot = {"d1": {"uptrend": True, "ema20": 9, "ema50": 8, "rsi14": 80},
           "h4": {"rsi_in_range": True, "rsi14": 52, "breakout": {"breakout": True, "reason": "ok"}}}
    passed5, reasons5 = TechnicalAgent.gate(hot)
    check("overbought D1 rejected", not passed5, "; ".join(reasons5))

    overbought_h4 = {"d1": {"uptrend": True, "ema20": 9, "ema50": 8, "rsi14": 60},
                     "h4": {"rsi_in_range": False, "rsi14": 72, "breakout": {"breakout": True, "reason": "ok"}}}
    passed6, _ = TechnicalAgent.gate(overbought_h4)
    check("H4 RSI outside 35-65 rejected", not passed6)

    shortlist = NarrativeAgent.deterministic_shortlist([
        {"symbol": "SOLUSDT", "weekly_change_pct": 12.4, "avg_daily_quote_vol_usd": 900_000_000},
        {"symbol": "DOGEUSDT", "weekly_change_pct": -30.0, "avg_daily_quote_vol_usd": 400_000_000},
        {"symbol": "TAOUSDT", "weekly_change_pct": 95.0, "avg_daily_quote_vol_usd": 200_000_000},
        {"symbol": "ADAUSDT", "weekly_change_pct": 4.1, "avg_daily_quote_vol_usd": 300_000_000},
    ])
    symbols = [s["symbol"] for s in shortlist]
    check("falling knife filtered out", "DOGEUSDT" not in symbols, str(symbols))
    check("parabolic coin filtered out", "TAOUSDT" not in symbols, str(symbols))
    check("healthy momentum kept", symbols == ["SOLUSDT", "ADAUSDT"], str(symbols))

    # ---- 4. Circuit breakers ------------------------------------------------
    print("\n[4] CIRCUIT BREAKERS")
    tmp_path = "._selftest_journal.json"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    j = Journal(tmp_path)
    check("fresh journal allows trading", j.check_circuit_breakers()["allowed"])

    now_iso = datetime.now(timezone.utc).isoformat()
    j.state["closed_trades"].append({"symbol": "X", "pnl_usd": -24.0, "closed_at": now_iso,
                                     "position_size_usd": 125})
    cb = j.check_circuit_breakers()
    check("daily loss of $24 halts trading", cb["daily_halt"] and not cb["allowed"], str(cb["reasons"][:1]))

    j2 = Journal(tmp_path + "2")
    j2.state["closed_trades"] = [{"symbol": "Y", "pnl_usd": 120.0, "closed_at": now_iso, "position_size_usd": 125}]
    cb2 = j2.check_circuit_breakers()
    check("monthly target of $120 locks the month", cb2["monthly_lock"] and not cb2["allowed"])

    j3 = Journal(tmp_path + "3")
    j3.state["active_trades"] = [{"symbol": s, "position_size_usd": 125} for s in ("A", "B", "C")]
    cb3 = j3.check_circuit_breakers()
    check("3 open positions blocks new trades", cb3["max_trades"] and not cb3["allowed"])

    j4 = Journal(tmp_path + "4")
    j4.state["active_trades"] = [{"symbol": "A", "position_size_usd": 125},
                                 {"symbol": "B", "position_size_usd": 125}]
    check("committed capital tracked", j4.committed_capital() == 250.0)
    check("2 open positions still allowed", j4.check_circuit_breakers()["allowed"])

    # ---- 5. Journal lifecycle ----------------------------------------------
    print("\n[5] JOURNAL LIFECYCLE")
    j5 = Journal(tmp_path + "5")
    trade = Trade(id="T1", symbol="SOLUSDT", entry_price=100.0, quantity=1.25,
                  position_size_usd=125.0, stop_loss=93.6, take_profit=119.2,
                  opened_at=now_iso)
    j5.add_trade(trade)
    check("trade registered as active", j5.has_active("SOLUSDT"))
    closed = j5.close_trade("T1", 119.2, "TAKE_PROFIT")
    check("take profit yields exactly +$24", closed is not None and abs(closed["pnl_usd"] - 24.0) < 0.01,
          f"{closed['pnl_usd'] if closed else 'n/a'}")
    st = j5.stats()
    check("equity updated to $424", st["equity"] == 424.0, str(st["equity"]))
    check("win rate = 100%", st["win_rate"] == 100.0)

    j6 = Journal(tmp_path + "6")
    j6.add_trade(Trade(id="T2", symbol="ADAUSDT", entry_price=1.0, quantity=125.0,
                       position_size_usd=125.0, stop_loss=0.936, take_profit=1.192,
                       opened_at=now_iso))
    closed2 = j6.close_trade("T2", 0.936, "STOP_LOSS")
    check("stop loss costs exactly -$8", closed2 is not None and abs(closed2["pnl_usd"] + 8.0) < 0.01,
          f"{closed2['pnl_usd'] if closed2 else 'n/a'}")

    # ---- 6. Backtester on synthetic data -----------------------------------
    print("\n[6] BACKTESTER")
    h4 = synthetic_market(1200, seed=7)
    d1 = synthetic_market(300, seed=7, drift=0.004, vol=0.02, tf_ms=86_400_000)
    bt = Backtester.__new__(Backtester)   # no network client needed
    res = bt.run_on_data("SYNTH", h4, d1)
    check("backtester runs without error", isinstance(res, BacktestResult))
    check("backtester generated trades", res.trades >= 1,
          f"trades={res.trades} W/L={res.wins}/{res.losses} pnl={fmt_money(res.pnl_usd)}")

    # Every closed trade must land on EXACTLY -$8 or +$24 — proof the SOP holds end-to-end.
    quantized = all(
        abs(e["pnl_usd"] + SOP.MAX_RISK_PER_TRADE_USD) < 0.01
        or abs(e["pnl_usd"] - SOP.TARGET_PROFIT_PER_TRADE_USD) < 0.01
        for e in res.log
    )
    check("every backtest trade is exactly -$8 or +$24", quantized,
          f"{sorted({e['pnl_usd'] for e in res.log})}")
    expected_pnl = res.wins * SOP.TARGET_PROFIT_PER_TRADE_USD - res.losses * SOP.MAX_RISK_PER_TRADE_USD
    check("aggregate PnL matches W/L arithmetic", abs(res.pnl_usd - expected_pnl) < 0.01,
          f"{fmt_money(res.pnl_usd)} vs {fmt_money(expected_pnl)}")

    # A downtrend must produce no entries at all (D1 filter blocks everything).
    bear_h4 = synthetic_market(800, seed=11, drift=-0.002)
    bear_d1 = synthetic_market(200, seed=11, drift=-0.006, vol=0.02, tf_ms=86_400_000)
    bear = bt.run_on_data("BEAR", bear_h4, bear_d1)
    check("no entries taken in a downtrend", bear.trades == 0, f"trades={bear.trades}")

    for entry in res.log[:4]:
        print(f"        {entry['entry_time']} -> {entry['exit_time']} "
              f"{entry['outcome']:<12} {fmt_money(entry['pnl_usd'])}")

    # ---- 7. LLM JSON extraction --------------------------------------------
    print("\n[7] LLM JSON EXTRACTION (keyless layer)")
    cases = [
        ('{"a":1}', {"a": 1}),
        ('```json\n{"b":2}\n```', {"b": 2}),
        ('Sure! Here you go:\n{"c":[1,2]}\nHope that helps.', {"c": [1, 2]}),
        ('no json at all', None),
    ]
    for raw, expected in cases:
        got = KeylessLLM.extract_json(raw)
        check(f"extract {raw[:28]!r}", got == expected, f"got {got}")

    # cleanup
    for suffix in ("", "2", "3", "4", "5", "6"):
        p = tmp_path + suffix
        if os.path.exists(p):
            os.remove(p)

    print("\n" + "=" * 78)
    if failures == 0:
        print(" RESULT: ALL CHECKS PASSED ✅")
    else:
        print(f" RESULT: {failures} CHECK(S) FAILED ❌")
    print("=" * 78)
    return 0 if failures == 0 else 1


# ==============================================================================
# SECTION 11 — HUMAN-READABLE STRATEGY DESCRIPTION
# ==============================================================================


STRATEGY_TEXT = f"""
================================================================================
 MICRO HEDGE FUND STRATEGY — FULL SPECIFICATION
================================================================================

CAPITAL & SIZING
  Account capital ............ {fmt_money(SOP.ACCOUNT_CAPITAL_USD)}
  Position size .............. {fmt_money(SOP.POSITION_SIZE_USD)} per trade (~31.25%)
  Max risk per trade ......... {fmt_money(SOP.MAX_RISK_PER_TRADE_USD)} ({SOP.MAX_RISK_PER_TRADE_USD / SOP.ACCOUNT_CAPITAL_USD * 100:.1f}% of capital)
  Target profit per trade .... {fmt_money(SOP.TARGET_PROFIT_PER_TRADE_USD)} (R:R = 1:{SOP.RISK_REWARD_RATIO})
  Max concurrent positions ... {SOP.MAX_OPEN_POSITIONS}
  Daily target ............... {fmt_money(SOP.DAILY_TARGET_USD)} (+1%)
  Monthly target ............. {fmt_money(SOP.MONTHLY_TARGET_USD)} (+30%)
  Venue ...................... Binance SPOT only (no futures, no leverage, no shorts)
  Universe ................... {len(WHITELIST)} hardcoded USDT pairs

LEVEL FORMULAS (exact)
  StopLossPrice   = EntryPrice * (1 - ({SOP.MAX_RISK_PER_TRADE_USD:.0f} / PositionSizeUSD))   ->  {SOP.stop_loss_pct():.1f}%
  TakeProfitPrice = EntryPrice * (1 + ({SOP.TARGET_PROFIT_PER_TRADE_USD:.0f} / PositionSizeUSD))  ->  +{SOP.take_profit_pct():.1f}%
  Quantity        = PositionSizeUSD / EntryPrice   (floored to LOT_SIZE stepSize)

STAGE 1 — NARRATIVE
  * Screen all {len(WHITELIST)} whitelist pairs for 7-day momentum and liquidity.
  * Keep pairs with avg daily volume >= {fmt_money(SOP.MIN_24H_QUOTE_VOLUME_USD * 0.5)}.
  * Reject parabolic (> +{SOP.NARRATIVE_MAX_WEEKLY_PCT:.0f}% weekly) and falling knives (< {SOP.NARRATIVE_MIN_WEEKLY_PCT:.0f}%).
  * Shortlist the top {SOP.NARRATIVE_SHORTLIST_SIZE} names (LLM-ranked if available, else momentum-ranked).

STAGE 2 — ON-CHAIN & LIQUIDITY
  * 24h quote volume >= {fmt_money(SOP.MIN_24H_QUOTE_VOLUME_USD)}
  * Volume surge >= {SOP.VOLUME_SURGE_RATIO:.0%} of the 30-day average
  * Order-book depth within 1% of mid >= {fmt_money(SOP.MIN_ORDERBOOK_DEPTH_USD)}
  * Spread <= {SOP.MAX_SPREAD_PCT}%
  * Accumulation signature: bid/ask depth imbalance >= 1.0 and 24h move < +25%

STAGE 3 — TECHNICAL
  * D1: EMA{SOP.EMA_FAST} > EMA{SOP.EMA_SLOW} (established uptrend), D1 RSI < {SOP.D1_RSI_OVERBOUGHT:.0f}
  * H4: consolidation range <= {SOP.MAX_CONSOLIDATION_RANGE_PCT:.0f}% wide over {SOP.BREAKOUT_LOOKBACK} candles,
        close breaks above the range high, volume >= {SOP.BREAKOUT_MIN_VOLUME_RATIO}x average
  * H4: {SOP.RSI_MIN:.0f} < RSI({SOP.RSI_PERIOD}) < {SOP.RSI_MAX:.0f}  (momentum available, not overbought)

STAGE 4 — RISK MANAGER (deterministic, never delegated to an LLM)
  * Triple confirmation: stages 1, 2 and 3 must ALL pass.
  * Circuit breakers:
      1. Daily realized loss <= -{fmt_money(SOP.DAILY_LOSS_CUTOFF_USD)}  -> halt all scanning for 24 hours
      2. Monthly realized profit >= {fmt_money(SOP.MONTHLY_TARGET_USD)} -> pause until next calendar month
      3. {SOP.MAX_OPEN_POSITIONS} open positions                    -> reject new setups
  * No duplicate exposure to the same symbol.
  * Committed capital + {fmt_money(SOP.POSITION_SIZE_USD)} must not exceed {fmt_money(SOP.ACCOUNT_CAPITAL_USD)}.
  * Exchange filters respected: stepSize, minQty, minNotional.

EXECUTION
  * MARKET BUY for exactly {fmt_money(SOP.POSITION_SIZE_USD)} (quoteOrderQty).
  * Protective levels RECOMPUTED from the real average fill price.
  * OCO SELL: take-profit limit + stop-limit (stop limit = stop * 0.998).
  * Journal the trade; monitor until stop or target is hit.

EXPECTANCY MATH
  With R:R = 1:3, breakeven win rate = 1 / (1 + 3) = 25%.
  At a 35% win rate over 20 trades: 7 wins x $24 - 13 losses x $8 = $168 - $104 = +$64.
  At a 40% win rate over 20 trades: 8 x $24 - 12 x $8 = $192 - $96 = +$96.
  Reaching the {fmt_money(SOP.MONTHLY_TARGET_USD)} monthly target needs ~5 net winning trades.
================================================================================
"""


# ==============================================================================
# SECTION 12 — CLI
# ==============================================================================


def cmd_scan(args: argparse.Namespace) -> int:
    pipeline = StrategyPipeline(use_llm=not args.no_llm)
    try:
        result = pipeline.run()
    except BinanceError as exc:
        log("ERROR", str(exc))
        log("ERROR", "Binance may be geo-blocking this IP. Offline commands still work: --selftest, --levels, --explain")
        return 2

    print("\n" + "=" * 78)
    if not result.get("ok"):
        print(f" NO SIGNAL — {result.get('reason')}")
        print("=" * 78)
        return 0

    s = result["signal"]
    print(" 🚨 SIGNAL APPROVED — TRIPLE CONFIRMED")
    print("=" * 78)
    print(f"  Pair ............ {s['symbol']}  ({s['direction']})")
    print(f"  Entry ........... {fmt_price(s['entry_price'])}")
    print(f"  Stop Loss ....... {fmt_price(s['stop_loss'])}   ({s['stop_loss_pct']}%)")
    print(f"  Take Profit ..... {fmt_price(s['take_profit'])}   (+{s['take_profit_pct']}%)")
    print(f"  Quantity ........ {s['quantity']}")
    print(f"  Position size ... {fmt_money(s['position_size_usd'])}")
    print(f"  Risk / Reward ... {fmt_money(s['risk_usd'])} / {fmt_money(s['reward_usd'])}  (1:{s['risk_reward_ratio']})")
    print(f"  Narrative ....... {s['rationale'].get('narrative')}")
    print(f"  On-chain ........ {s['rationale'].get('onchain')}")
    print(f"  Technical ....... {s['rationale'].get('technical')}")
    print("=" * 78)
    print(f"  Completed in {result['duration']:.1f}s")
    return 0


def cmd_levels(args: argparse.Namespace) -> int:
    entry = float(args.levels)
    size = float(args.size)
    lv = RiskManager.compute_levels(entry, size)
    risk = (entry - lv["stop_loss"]) * lv["quantity"]
    reward = (lv["take_profit"] - entry) * lv["quantity"]

    print("\n" + "=" * 62)
    print(f" TRADE PLAN — entry {fmt_price(entry)}, size {fmt_money(size)}")
    print("=" * 62)
    print(f"  Quantity ........ {lv['quantity']:.8f}")
    print(f"  Stop Loss ....... {fmt_price(lv['stop_loss'])}   ({lv['stop_loss_pct']}%)")
    print(f"  Stop Limit ...... {fmt_price(lv['stop_limit_price'])}")
    print(f"  Take Profit ..... {fmt_price(lv['take_profit'])}   (+{lv['take_profit_pct']}%)")
    print(f"  Realized risk ... {fmt_money(risk)}")
    print(f"  Realized reward . {fmt_money(reward)}")
    print(f"  Ratio ........... 1:{reward / risk:.2f}")
    print("=" * 62)
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    client = BinanceClient()
    bt = Backtester(client)
    symbols = list(WHITELIST) if args.backtest_all else [args.backtest.upper()]

    print("\n" + "=" * 78)
    print(f" BACKTEST — exact SOP rules | {len(symbols)} symbol(s) | H4 entries, D1 trend filter")
    print("=" * 78)

    total = BacktestResult(symbol="TOTAL")
    for symbol in symbols:
        try:
            res = bt.run(symbol, h4_limit=args.bars)
        except BinanceError as exc:
            print(f"  {symbol:<12} ERROR: {str(exc)[:60]}")
            continue
        total.trades += res.trades
        total.wins += res.wins
        total.losses += res.losses
        total.pnl_usd += res.pnl_usd
        print("  " + res.summary())
        if args.verbose:
            for e in res.log:
                print(f"      {e['entry_time']} -> {e['exit_time']}  {e['outcome']:<12} {fmt_money(e['pnl_usd'])}")

    print("-" * 78)
    print("  " + total.summary())
    if total.trades:
        expectancy = total.pnl_usd / total.trades
        print(f"  Expectancy per trade: {fmt_money(expectancy)}  |  "
              f"Breakeven win rate for 1:3 = 25.0%  |  Actual = {total.win_rate}%")
    print("=" * 78)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Micro Hedge Fund — complete trading strategy engine (single file, no dependencies).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--scan", action="store_true", help="run the live 4-stage pipeline")
    parser.add_argument("--no-llm", action="store_true", help="disable the keyless LLM layer (deterministic only)")
    parser.add_argument("--selftest", action="store_true", help="offline verification of SOP math, indicators and breakers")
    parser.add_argument("--levels", metavar="PRICE", help="print the trade plan for a given entry price")
    parser.add_argument("--size", default=SOP.POSITION_SIZE_USD, help="position size in USD (default 125)")
    parser.add_argument("--backtest", metavar="SYMBOL", help="backtest one symbol, e.g. SOLUSDT")
    parser.add_argument("--backtest-all", action="store_true", help="backtest the entire whitelist")
    parser.add_argument("--bars", type=int, default=1000, help="H4 bars of history for the backtest (default 1000)")
    parser.add_argument("--verbose", action="store_true", help="print every backtest trade")
    parser.add_argument("--explain", action="store_true", help="print the full strategy specification")

    args = parser.parse_args(argv)

    if args.selftest:
        return run_selftest()
    if args.explain:
        print(STRATEGY_TEXT)
        return 0
    if args.levels:
        return cmd_levels(args)
    if args.backtest or args.backtest_all:
        return cmd_backtest(args)
    if args.scan:
        return cmd_scan(args)

    parser.print_help()
    print(STRATEGY_TEXT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

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

    def __init__(self, enabled: bool = True, timeout: int = 45, referrer: str = "micro-hedge-fund-strategy"):
        self.enabled = enabled
        self.timeout = timeout
        self.referrer = referrer
        self.available: Optional[bool] = None
        self._ctx = ssl.create_default_context()

    def ask_json(self, system: str, user: str, retries: int = 2) -> Optional[dict]:
        if not self.enabled:
            return None

        payload = json.dumps({
            "model": "openai",
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
                    return parsed
            except Exception as exc:
                log("DEBUG", f"LLM attempt {attempt} failed: {str(exc)[:120]}")
            time.sleep(3.5)  # anonymous tier allows ~1 request / 3s

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
            parsed = self.llm.ask_json(
                PROMPT_NARRATIVE,
                json.dumps({"task": "Select up to 5 strongest narratives", "candidates": liquid}, indent=2),
            )
            if parsed and isinstance(parsed.get("selected"), list):
                allowed = {c["symbol"] for c in liquid}
                selected = [
                    {
                        "symbol": str(s.get("symbol", "")).upper(),
                        "narrative": s.get("narrative", "Unspecified"),
                        "thesis": s.get("thesis", ""),
                        "strength": int(s.get("strength") or 5),
                    }
                    for s in parsed["selected"]
                    if str(s.get("symbol", "")).upper() in allowed
                ][:SOP.NARRATIVE_SHORTLIST_SIZE]
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
        d1 = Indicators.analyze_timeframe(self.client.klines(symbol, SOP.TF_D1, SOP.KLINE_LIMIT))
        h4 = Indicators.analyze_timeframe(self.client.klines(symbol, SOP.TF_H4, SOP.KLINE_LIMIT))
        return {"symbol": symbol, "d1": d1, "h4": h4}

    @staticmethod
    def gate(ta: Dict[str, Any]) -> Tuple[bool, List[str]]:
        d1, h4 = ta["d1"], ta["h4"]
        failures: List[str] = []
        if not d1["uptrend"]:
            failures.append(f"D1 not bullish (EMA20 {d1['ema20']} <= EMA50 {d1['ema50']})")
        if not h4["breakout"]["breakout"]:
            failures.append(f"H4 breakout missing ({h4['breakout']['reason']})")
        if not h4["rsi_in_range"]:
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
        quantity = position_size_usd / entry_price
        return {
            "entry_price": entry_price,
            "position_size_usd": position_size_usd,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "stop_limit_price": stop_loss * 0.998,
            "risk_usd": SOP.MAX_RISK_PER_TRADE_USD,
            "reward_usd": SOP.TARGET_PROFIT_PER_TRADE_USD,
            "risk_reward_ratio": SOP.RISK_REWARD_RATIO,
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

    def run(self) -> Dict[str, Any]:
        started = time.time()
        self.journal.reconcile()

        breakers = self.journal.check_circuit_breakers()
        if not breakers["allowed"]:
            log("WARN", "Scan aborted by circuit breakers: " + " | ".join(breakers["reasons"]))
            return {"ok": False, "halted": True, "reason": " | ".join(breakers["reasons"])}

        s1 = self.narrative.run()
        if not s1["passed"]:
            return {"ok": False, "reason": f"Stage 1 failed: {s1['reason']}", "duration": time.time() - started}

        s2 = self.onchain.run(s1["candidates"])
        if not s2["passed"]:
            return {"ok": False, "reason": f"Stage 2 failed: {s2['reason']}", "duration": time.time() - started}

        s3 = self.technical.run(s2["survivors"])
        if not s3["passed"]:
            return {"ok": False, "reason": f"Stage 3 failed: {s3['reason']}", "duration": time.time() - started}

        s4 = self.risk.run(s3["survivors"][0], {"n": s1["passed"], "o": s2["passed"], "t": s3["passed"]})
        if not s4["approved"]:
            return {"ok": False, "reason": f"Stage 4 rejected: {s4['reason']}", "duration": time.time() - started}

        return {"ok": True, "signal": s4["signal"], "duration": time.time() - started}


# ==============================================================================
# SECTION 9 — BACKTESTER (exact SOP rules on historical candles)
# ==============================================================================


@dataclass
class BacktestResult:
    symbol: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    open_at_end: int = 0
    pnl_usd: float = 0.0
    log: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return round(self.wins / self.trades * 100, 1) if self.trades else 0.0

    def summary(self) -> str:
        return (f"{self.symbol:<12} trades={self.trades:<3} W/L={self.wins}/{self.losses:<3} "
                f"win%={self.win_rate:<6} PnL={fmt_money(self.pnl_usd)}")


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
        return self.run_on_data(symbol, h4, d1)

    def run_on_data(self, symbol: str, h4: Sequence[Candle], d1: Sequence[Candle]) -> BacktestResult:
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

        position: Optional[Dict[str, Any]] = None
        start = SOP.EMA_SLOW + SOP.BREAKOUT_LOOKBACK + 1

        for i in range(start, len(h4)):
            candle = h4[i]

            # ---------------- manage an open position (intrabar) ----------------
            if position:
                hit_stop = candle.low <= position["stop_loss"]
                hit_target = candle.high >= position["take_profit"]
                exit_price = outcome = None
                if hit_stop:                      # conservative: stop wins ties
                    exit_price, outcome = position["stop_loss"], "STOP_LOSS"
                elif hit_target:
                    exit_price, outcome = position["take_profit"], "TAKE_PROFIT"

                if exit_price is not None:
                    pnl = (exit_price - position["entry_price"]) * position["quantity"]
                    result.trades += 1
                    result.pnl_usd += pnl
                    if pnl > 0:
                        result.wins += 1
                    else:
                        result.losses += 1
                    result.log.append({
                        "entry_time": datetime.fromtimestamp(position["entry_time"] / 1000, tz=timezone.utc).isoformat()[:16],
                        "exit_time": datetime.fromtimestamp(candle.close_time / 1000, tz=timezone.utc).isoformat()[:16],
                        "entry": round(position["entry_price"], 8),
                        "exit": round(exit_price, 8),
                        "outcome": outcome,
                        "pnl_usd": round(pnl, 2),
                    })
                    position = None
                continue  # never enter on the same bar we exited

            # ---------------- look for a new entry ----------------
            window = h4[: i + 1]
            daily_up, daily_rsi = trend_at(candle.close_time)
            if not daily_up:
                continue
            if daily_rsi is not None and daily_rsi >= SOP.D1_RSI_OVERBOUGHT:
                continue

            closes = [c.close for c in window]
            rsi_val = Indicators.rsi(closes, SOP.RSI_PERIOD)
            if rsi_val is None or not (SOP.RSI_MIN < rsi_val < SOP.RSI_MAX):
                continue

            brk = Indicators.consolidation_breakout(window)
            if not brk["breakout"]:
                continue

            entry_price = candle.close
            levels = RiskManager.compute_levels(entry_price)
            position = {
                "entry_time": candle.close_time,
                "entry_price": entry_price,
                "quantity": levels["quantity"],
                "stop_loss": levels["stop_loss"],
                "take_profit": levels["take_profit"],
            }

        if position:
            result.open_at_end = 1
        return result


# ==============================================================================
# SECTION 10 — SELF-TEST (offline, no network)
# ==============================================================================


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
  Max risk per trade ......... {fmt_money(SOP.MAX_RISK_PER_TRADE_USD)} (2% of capital)
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

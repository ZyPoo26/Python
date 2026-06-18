"""
Teknik analiz motoru.

Göstergeler:
  NVI  – Negative Volume Index: düşük hacimli günlerde akıllı para fiyatı iter.
         NVI > EMA(255) → kurumsal alım var → güçlü yükseliş sinyali.
  RSI  – Aşırı satım bölgesi çıkışı → potansiyel toparlanma.
  MACD – Kesişim yönü (hızlı > yavaş = yükseliş).
  BB   – Fiyat alt banda yakın → dip noktası.
  VOL  – Ani hacim artışı + fiyat yükseliş = birikim sinyali.
  MOM  – 10 günlük momentum pozitif mi?
"""

import numpy as np
import pandas as pd
import logging
from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    NVI_EMA_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, VOLUME_MA_PERIOD,
    ATR_PERIOD, ATR_STOP_MULT, ATR_TARGET_MULT
)

logger = logging.getLogger(__name__)


# ─── Gösterge Hesaplamaları ────────────────────────────────────────────────────

def calc_nvi(df: pd.DataFrame) -> pd.Series:
    """
    Negative Volume Index hesaplar.
    Yalnızca hacmin önceki günden DÜŞÜK olduğu günlerde fiyat değişimi NVI'ya yansır.
    Akıllı para düşük hacimli günlerde pozisyon alır — bu günler kurumsal birikimi gösterir.
    """
    close = df["Close"].values
    volume = df["Volume"].values
    nvi = np.full(len(close), 1000.0)
    for i in range(1, len(close)):
        if volume[i] < volume[i - 1]:
            pct = (close[i] - close[i - 1]) / close[i - 1]
            nvi[i] = nvi[i - 1] * (1 + pct)
        else:
            nvi[i] = nvi[i - 1]
    return pd.Series(nvi, index=df.index, name="NVI")


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(series: pd.Series, period=20, std=2):
    ma = series.rolling(period).mean()
    dev = series.rolling(period).std()
    upper = ma + std * dev
    lower = ma - std * dev
    return upper, ma, lower


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR) — hissenin günlük ortalama oynaklığı.
    Stop-loss ve hedefi hissenin kendi volatilitesine göre belirlemek için kullanılır.
    Çok oynak bir hissede stop daha geniş, sakin bir hissede daha dar olur.
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def calc_stop_target(price: float, atr: float) -> dict:
    """ATR bazlı stop-loss, hedef fiyat ve risk/ödül oranını hesaplar."""
    stop = price - ATR_STOP_MULT * atr
    target = price + ATR_TARGET_MULT * atr
    risk = price - stop
    reward = target - price
    rr = (reward / risk) if risk > 0 else 0.0
    return {
        "stop_loss": round(stop, 2),
        "target": round(target, 2),
        "stop_pct": round((stop - price) / price * 100, 2),
        "target_pct": round((target - price) / price * 100, 2),
        "risk_reward": round(rr, 2),
    }


# ─── Ana Analiz Fonksiyonu ─────────────────────────────────────────────────────

def analyze_stock(ticker: str, df: pd.DataFrame) -> dict | None:
    """
    Bir hisseyi tüm göstergelerle analiz eder; puan ve sinyal sözlüğü döner.
    Puan 0-6 arası: her gösterge için 1 puan.
    """
    try:
        close = df["Close"].squeeze()
        volume = df["Volume"].squeeze()

        # ── NVI ──
        nvi = calc_nvi(df)
        nvi_ema = nvi.ewm(span=NVI_EMA_PERIOD, adjust=False).mean()
        nvi_bullish = bool(nvi.iloc[-1] > nvi_ema.iloc[-1])
        nvi_rising = bool(nvi.iloc[-1] > nvi.iloc[-5])  # son 5 günde NVI yükselde mi

        # ── RSI ──
        rsi = calc_rsi(close, RSI_PERIOD)
        rsi_val = float(rsi.iloc[-1])
        rsi_prev = float(rsi.iloc[-3])
        # Aşırı satımdan çıkış: dip yapmış ve toparlanıyor
        rsi_signal = RSI_OVERSOLD < rsi_val < 55 and rsi_val > rsi_prev

        # ── MACD ──
        macd_line, signal_line, histogram = calc_macd(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
        macd_cross_up = (
            float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]) and
            float(macd_line.iloc[-2]) <= float(signal_line.iloc[-2])
        )
        macd_positive = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])

        # ── Bollinger Bantları ──
        bb_upper, bb_mid, bb_lower = calc_bollinger(close, BB_PERIOD)
        price_now = float(close.iloc[-1])
        bb_low_val = float(bb_lower.iloc[-1])
        bb_mid_val = float(bb_mid.iloc[-1])
        # Fiyat alt bandın yakınında ve orta banda doğru hareket ediyor
        bb_signal = price_now < bb_mid_val and price_now > bb_low_val * 0.98

        # ── Hacim Analizi ──
        vol_ma = volume.rolling(VOLUME_MA_PERIOD).mean()
        vol_ratio = float(volume.iloc[-1]) / float(vol_ma.iloc[-1]) if float(vol_ma.iloc[-1]) > 0 else 1.0
        price_change = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2])
        # Hacim arttı + fiyat yükseldi = birikim
        vol_signal = vol_ratio > 1.5 and price_change > 0

        # ── 10 Günlük Momentum ──
        momentum = (float(close.iloc[-1]) - float(close.iloc[-10])) / float(close.iloc[-10]) * 100
        mom_signal = momentum > 0

        # ── Skor Hesaplama ──
        checks = {
            "nvi_bullish": nvi_bullish,       # NVI > EMA → akıllı para alıyor
            "nvi_rising": nvi_rising,          # NVI son 5 günde artıyor
            "rsi_signal": rsi_signal,          # RSI ideal bölge
            "macd_signal": macd_cross_up or (macd_positive and float(histogram.iloc[-1]) > float(histogram.iloc[-2])),
            "bb_signal": bb_signal,            # Fiyat alt bant yakını
            "vol_signal": vol_signal,          # Hacim + fiyat yükselişi
        }
        score = sum(checks.values())

        # ── Trend ──
        ma50 = close.rolling(50).mean()
        ma20 = close.rolling(20).mean()
        trend = "YUKARI" if float(ma20.iloc[-1]) > float(ma50.iloc[-1]) else "ASAGI"

        # ── Stop-Loss / Hedef (ATR bazlı) ──
        atr = calc_atr(df, ATR_PERIOD)
        atr_val = float(atr.iloc[-1])
        risk_levels = calc_stop_target(price_now, atr_val)

        return {
            "ticker": ticker,
            "price": price_now,
            "score": score,
            "max_score": len(checks),
            "checks": checks,
            "rsi": round(rsi_val, 1),
            "macd_hist": round(float(histogram.iloc[-1]), 4),
            "nvi_vs_ema": round(float(nvi.iloc[-1]) - float(nvi_ema.iloc[-1]), 2),
            "vol_ratio": round(vol_ratio, 2),
            "momentum_10d": round(momentum, 2),
            "trend": trend,
            "nvi_bullish": nvi_bullish,
            "atr": round(atr_val, 2),
            **risk_levels,
        }
    except Exception as e:
        logger.debug(f"{ticker} analiz hatası: {e}")
        return None


def analyze_all(stock_data: dict[str, pd.DataFrame]) -> list[dict]:
    """Tüm hisse verilerini analiz edip sonuçları skor sırasına göre döner."""
    results = []
    for ticker, df in stock_data.items():
        result = analyze_stock(ticker, df)
        if result:
            results.append(result)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

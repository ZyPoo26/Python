"""
Telegram bot modülü.
Bot token ve chat ID .env dosyasından okunur.
"""

import requests
import logging
from datetime import datetime
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    MAX_POSITION_PCT, MAX_POSITIONS, MAX_SECTOR_PCT,
    get_profile,
)

logger = logging.getLogger(__name__)


def fmt_price(value: float, market: str | None = None) -> str:
    """Fiyatı market para birimiyle biçimler: '$297.53' veya '142.20 TL'."""
    prof = get_profile(market)
    if prof["currency_prefix"]:
        return f"{prof['currency']}{value:.2f}"
    return f"{value:.2f} {prof['currency']}"


def send_message(text: str) -> bool:
    """Telegram'a mesaj gönderir. Başarılıysa True döner."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID .env dosyasında tanımlı değil!")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram mesaj gönderilemedi: {e}")
        return False


def _score_bar(score: int, max_score: int) -> str:
    filled = "█" * score
    empty = "░" * (max_score - score)
    return f"{filled}{empty} {score}/{max_score}"


def _check_icon(val: bool) -> str:
    return "✅" if val else "❌"


def format_buy_signal(result: dict, reliability: dict | None = None, news: dict | None = None,
                      market: str | None = None) -> str:
    checks = result["checks"]
    score = result["score"]
    max_score = result["max_score"]
    bar = _score_bar(score, max_score)
    label = get_profile(market)["label"]

    strength = "GÜÇLİ" if score >= 5 else ("ORTA" if score >= 3 else "ZAYIF")
    emoji = "🔥" if score >= 5 else ("📈" if score >= 3 else "👀")

    lines = [
        f"{emoji} <b>[{label}] ALIM SİNYALİ: {result['ticker']}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💰 Fiyat       : <b>{fmt_price(result['price'], market)}</b>",
        f"📊 Güç         : {strength}",
        f"📊 Sinyal Puanı: {bar}",
    ]

    # Geçmiş güvenilirlik (backtest'ten) — sinyalin hemen altında, en görünür yerde
    if reliability:
        lines += [
            f"🎖️ Güvenilirlik: {reliability['emoji']} <b>{reliability['label']}</b>",
            f"   <i>{reliability['detail']}</i>",
        ]

    # Haber duygusu (sentiment)
    if news and news.get("total_headlines", 0) > 0:
        lines.append(
            f"📰 Haber Havası: {news['emoji']} <b>{news['label']}</b> "
            f"(+{news['positive']}/-{news['negative']})"
        )
        if news.get("strong_negative"):
            lines.append("   ⚠️ <b>DİKKAT: Olumsuz haber baskın! Girmeden araştır.</b>")
        for title, direction in news.get("examples", [])[:2]:
            mark = "🟢" if direction == "+" else "🔴"
            lines.append(f"   {mark} <i>{title[:70]}</i>")

    lines += [
        "",
        "── Gösterge Detayı ──",
        f"📉 NVI (Akıllı Para): {_check_icon(checks['nvi_bullish'])} {'Kurumsal birikim var' if checks['nvi_bullish'] else 'Birikim yok'}",
        f"📈 NVI Yükseliş     : {_check_icon(checks['nvi_rising'])}",
        f"📊 RSI ({result['rsi']})       : {_check_icon(checks['rsi_signal'])} {'İdeal bölge' if checks['rsi_signal'] else 'Bölge dışı'}",
        f"📊 MACD             : {_check_icon(checks['macd_signal'])} {'Yükseliş sinyali' if checks['macd_signal'] else 'Sinyal yok'}",
        f"📊 Bollinger        : {_check_icon(checks['bb_signal'])} {'Dip yakını' if checks['bb_signal'] else 'Normal bölge'}",
        f"📊 Hacim Artışı     : {_check_icon(checks['vol_signal'])} {result['vol_ratio']:.1f}x normal",
        "",
        f"📅 10 Günlük Momentum: <b>{'▲' if result['momentum_10d'] > 0 else '▼'} {result['momentum_10d']:+.2f}%</b>",
        f"📈 Kısa Vadeli Trend : {result['trend']}",
        "",
        "── 🎯 İşlem Planı (ATR bazlı) ──",
        f"🎯 Hedef Fiyat: <b>{fmt_price(result['target'], market)}</b> ({result['target_pct']:+.1f}%)",
        f"🛑 Stop-Loss  : <b>{fmt_price(result['stop_loss'], market)}</b> ({result['stop_pct']:+.1f}%)",
        f"⚖️ Risk/Ödül  : 1:{result['risk_reward']:.1f} {'✅ iyi' if result['risk_reward'] >= 1.5 else '⚠️ zayıf'}",
        "",
        "── 💼 Risk Yönetimi ──",
        f"💼 Bu hisseye portföyün en fazla <b>%{MAX_POSITION_PCT}</b>'ini ayır",
        f"📊 Aynı anda en fazla <b>{MAX_POSITIONS}</b> hissede dur",
        f"⚠️ Tek sektöre %{MAX_SECTOR_PCT}'dan fazla girme",
        "",
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
        "⚠️ <i>Bu analiz tamamen bilgi amaçlıdır.",
        "Yatırım tavsiyesi değildir. Stop-loss'a mutlaka uy.</i>",
    ]
    return "\n".join(lines)


def format_watch_signal(result: dict) -> str:
    checks = result["checks"]
    score = result["score"]
    max_score = result["max_score"]
    bar = _score_bar(score, max_score)
    lines = [
        f"👀 <b>İZLE: {result['ticker']}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💰 Fiyat       : {fmt_price(result['price'])}",
        f"📊 Sinyal Puanı: {bar}",
        f"📉 NVI         : {'Birikim var ✅' if checks['nvi_bullish'] else 'Birikim yok ❌'}",
        f"📊 RSI         : {result['rsi']}",
        f"📅 Momentum 10g: {result['momentum_10d']:+.2f}%",
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
    ]
    return "\n".join(lines)


def format_summary(results: list[dict], total_scanned: int) -> str:
    buy_signals = [r for r in results if r["score"] >= 3]
    watch_signals = [r for r in results if r["score"] == 2]
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    lines = [
        f"📊 <b>[{get_profile()['label']}] BORSA ANALİZ RAPORU</b>",
        f"🕐 {now}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔍 Taranan hisse    : {total_scanned}",
        f"📈 Alım sinyali     : {len(buy_signals)} hisse",
        f"👀 İzleme listesi   : {len(watch_signals)} hisse",
        "",
    ]
    if buy_signals:
        lines.append("🔥 <b>En güçlü sinyaller:</b>")
        for r in buy_signals[:5]:
            bar = _score_bar(r["score"], r["max_score"])
            lines.append(f"  • <b>{r['ticker']}</b> {bar} — {fmt_price(r['price'])}")
    lines += [
        "",
        "⚠️ <i>Bilgi amaçlıdır, yatırım tavsiyesi değildir.</i>",
    ]
    return "\n".join(lines)

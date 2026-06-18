"""
Borsa Analiz Botu - Ana Modül
------------------------------
Kullanım:
  python main.py          → Sürekli çalışır, SCAN_TIMES saatlerinde tarama yapar
  python main.py --once   → Tek seferlik tarama yapar ve çıkar
  python main.py --test   → Telegram bağlantısını test eder

Kurulum:
  1. pip install -r requirements.txt
  2. .env.example dosyasını .env olarak kopyalayın
  3. .env içine TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID ekleyin
  4. python main.py
"""

import sys
import os
import json
import logging
import schedule
import time
from datetime import datetime

# Windows konsolu Türkçe (cp1254) encoding kullanır ve emoji yazamaz.
# Çıktıyı UTF-8'e zorla ki ✅ 📈 gibi karakterler çökmeye yol açmasın.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from config import (
    SCAN_MODE,
    SCAN_TIMES,
    MARKET_OPEN_HOUR,
    MARKET_CLOSE_HOUR,
    SKIP_WEEKENDS,
    MIN_SCORE_TO_BUY_ALERT,
    MIN_SCORE_TO_WATCH_ALERT,
    DATA_PERIOD,
    DATA_INTERVAL,
)
from config import NEWS_ENABLED
from scraper import get_bist100_tickers, download_all
from analyzer import analyze_all
from backtest import get_reliability
from news_analyzer import get_news_sentiment
from telegram_notifier import (
    send_message,
    format_buy_signal,
    format_watch_signal,
    format_summary,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("borsa_analiz.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# Aynı gün içinde aynı sinyali tekrar tekrar göndermemek için hafıza.
# DOSYAYA yazılır; çünkü GitHub Actions her çalıştığında belleği sıfırlar.
# Dosya GitHub'a geri commit edilerek çalıştırmalar arası korunur.
# {tarih: {ticker: o gün gönderilen en yüksek skor}}
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sent_state.json")


def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception as e:
        logger.warning(f"Sinyal hafızası okunamadı: {e}")
        return {}


def _save_state(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Sinyal hafızası yazılamadı: {e}")


def _should_alert(ticker: str, score: int) -> bool:
    """
    Bu hisse için bugün daha önce bildirim gittiyse VE skor artmadıysa False döner.
    Böylece saat başı tarama aynı sinyali spam yapmaz; sadece yeni veya
    güçlenen (skoru yükselen) sinyaller bildirilir.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()
    # Sadece bugünü tut (eski günleri at, dosya şişmesin)
    today_state = state.get(today, {})
    prev = today_state.get(ticker)
    if prev is not None and score <= prev:
        return False
    today_state[ticker] = score
    _save_state({today: today_state})
    return True


def is_market_open() -> bool:
    """Şu an BIST seansı açık mı? (Hafta içi MARKET_OPEN–CLOSE saatleri arası)"""
    now = datetime.now()
    if SKIP_WEEKENDS and now.weekday() >= 5:  # 5=Cumartesi, 6=Pazar
        return False
    return MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR


def run_scan(force: bool = False):
    # Saatlik modda piyasa kapalıyken tarama yapma (gece/hafta sonu spam'i önler).
    # force=True ise (örn. --once) saat fark etmeksizin tarar.
    if not force and not is_market_open():
        logger.info("Piyasa kapalı, tarama atlandı (hafta sonu veya seans dışı).")
        return

    logger.info("=" * 50)
    logger.info("BIST 100 TARAMASI BAŞLIYOR")
    logger.info("=" * 50)

    # 1. Hisse listesini çek
    tickers = get_bist100_tickers()
    logger.info(f"Taranacak hisse sayısı: {len(tickers)}")

    # 2. Veri indir
    stock_data = download_all(tickers, period=DATA_PERIOD, interval=DATA_INTERVAL)

    # 3. Analiz et
    results = analyze_all(stock_data)
    logger.info(f"Analiz tamamlandı. {len(results)} hisse analiz edildi.")

    # 4. Alım sinyali olan hisseleri belirle
    buy_signals = [r for r in results if r["score"] >= MIN_SCORE_TO_BUY_ALERT]
    watch_signals = [r for r in results if r["score"] == MIN_SCORE_TO_WATCH_ALERT]

    # 5. Yalnızca YENİ veya skoru YÜKSELEN sinyalleri gönder (saatlik spam'i önler)
    new_signals = [r for r in buy_signals if _should_alert(r["ticker"], r["score"])]

    # 6. Özet mesajı: sadece bildirilecek yeni sinyal varsa gönder
    if new_signals:
        summary = format_summary(results, total_scanned=len(stock_data))
        send_message(summary)

    for result in new_signals:
        # Bu hissenin geçmiş güvenilirliğini backtest'ten al (cache'li)
        reliability = get_reliability(result["ticker"])
        # Haber duygusunu çek (cache'li)
        news = get_news_sentiment(result["ticker"]) if NEWS_ENABLED else None
        msg = format_buy_signal(result, reliability=reliability, news=news)
        ok = send_message(msg)
        status = "GÖNDERILDI" if ok else "HATA"
        news_str = f"| Haber: {news['label']}" if news else ""
        logger.info(
            f"  {result['ticker']} | Skor: {result['score']}/{result['max_score']} "
            f"| RSI: {result['rsi']} | Güvenilirlik: {reliability['label']} "
            f"{news_str} | Telegram: {status}"
        )
        time.sleep(0.5)

    if not new_signals:
        if buy_signals:
            logger.info(f"{len(buy_signals)} sinyal var ama hepsi bugün zaten bildirildi (tekrar gönderilmedi).")
        else:
            logger.info("Bu taramada alım sinyali çıkan hisse bulunamadı.")

    # 6. İzleme listesini yalnızca konsola yaz (istenirse Telegram'a da gönderilebilir)
    if watch_signals:
        logger.info(f"İzleme listesi ({len(watch_signals)} hisse):")
        for r in watch_signals[:10]:
            logger.info(f"  👀 {r['ticker']} | Skor: {r['score']}/{r['max_score']} | RSI: {r['rsi']}")

    logger.info("Tarama tamamlandı.\n")


def test_telegram():
    """Telegram bağlantısını test et."""
    msg = (
        "🤖 <b>Borsa Analiz Botu Aktif!</b>\n\n"
        "✅ Bağlantı başarılı.\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        "Bot hazır. Tarama saatlerinde alım sinyallerini buraya göndereceğim."
    )
    ok = send_message(msg)
    if ok:
        print("✅ Telegram bağlantısı başarılı! Mesajı kontrol edin.")
    else:
        print("❌ Telegram bağlantısı BAŞARISIZ. .env dosyasını kontrol edin.")
        print("   TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID doğru mu?")


def run_scheduler():
    """SCAN_MODE'a göre otomatik tarama yapar."""
    logger.info("Borsa Analiz Botu başlatılıyor...")

    if SCAN_MODE == "hourly":
        # Piyasa saatleri içindeki her saat başında tara (10:00, 11:00, ... 17:00).
        for hour in range(MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR):
            schedule.every().day.at(f"{hour:02d}:00").do(run_scan)
        zaman_bilgisi = (
            f"Hafta içi her saat başı, {MARKET_OPEN_HOUR:02d}:00–{MARKET_CLOSE_HOUR:02d}:00 arası"
        )
    else:
        for scan_time in SCAN_TIMES:
            schedule.every().day.at(scan_time).do(run_scan)
        zaman_bilgisi = ", ".join(SCAN_TIMES)

    logger.info(f"Tarama zamanlaması: {zaman_bilgisi}")

    send_message(
        f"🤖 <b>Borsa Analiz Botu Başlatıldı</b>\n"
        f"📅 Tarama: {zaman_bilgisi}\n"
        f"🔍 BIST 100 hisseleri taranacak\n"
        f"📊 Göstergeler: NVI, RSI, MACD, Bollinger, Hacim\n"
        f"🔔 Sadece <b>yeni</b> veya güçlenen sinyaller bildirilir."
    )

    logger.info("Scheduler çalışıyor. Çıkmak için Ctrl+C")
    while True:
        schedule.run_pending()
        time.sleep(30)


def run_backtest_cmd(args):
    """--backtest komutu: belirtilen hisseleri (yoksa varsayılan seti) test eder."""
    from backtest import run_backtest
    # --backtest'ten sonra hisse kodları verilebilir: --backtest THYAO GARAN ASELS
    idx = args.index("--backtest")
    tickers = [a.upper() for a in args[idx + 1:] if not a.startswith("--")]
    if not tickers:
        tickers = ["THYAO", "GARAN", "ASELS", "EREGL", "SISE", "BIMAS"]
        print(f"Hisse belirtilmedi, varsayılan set test ediliyor: {', '.join(tickers)}")
    run_backtest(tickers)


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--test" in args:
        test_telegram()
    elif "--once" in args:
        run_scan(force=True)
    elif "--backtest" in args:
        run_backtest_cmd(args)
    else:
        run_scheduler()

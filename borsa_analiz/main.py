"""
Borsa Analiz Botu - Ana Modül
------------------------------
Kullanım:
  python main.py          → Sürekli çalışır, SCAN_TIMES saatlerinde tarama yapar
  python main.py --once   → Tek seferlik tarama yapar ve çıkar
  python main.py --test   → Telegram bağlantısını test eder
  python main.py --news   → Önemli şirketlerin son haberlerini kontrol eder, önemliyse bildirir

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
from config import (
    ALWAYS_SEND_SUMMARY, MARKET, MIN_FUNDAMENTAL_SCORE_FOR_ALERT, AI_REPORT_ON_SCAN,
)
from scraper import get_bist100_tickers, download_all
from analyzer import analyze_all, is_buy_signal
from advisor import full_analysis, market_regime
from fundamentals import get_fundamentals
from telegram_notifier import (
    send_message,
    format_buy_signal,
    format_summary,
    _esc,
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
# Market'e göre ayrı hafıza (BIST ve ABD sinyalleri karışmasın)
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"sent_state_{MARKET}.json")


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


def _should_alert(ticker: str, score: int, commit: bool = True) -> bool:
    """
    Bu hisse için bugün daha önce bildirim gittiyse VE skor artmadıysa False döner.
    Böylece saat başı tarama aynı sinyali spam yapmaz; sadece yeni veya
    güçlenen (skoru yükselen) sinyaller bildirilir.
    commit=False: sadece kontrol eder, hafızaya yazmaz (mesaj gerçekten
    gönderildikten sonra commit=True ile yazılır; gönderim başarısızsa tekrar denenir).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()
    # Sadece bugünü tut (eski günleri at, dosya şişmesin)
    today_state = state.get(today, {})
    prev = today_state.get(ticker)
    if prev is not None and score <= prev:
        return False
    if not commit:
        return True
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
    logger.info(f"{MARKET} TARAMASI BAŞLIYOR")
    logger.info("=" * 50)

    # 1. Hisse listesini çek
    tickers = get_bist100_tickers()
    logger.info(f"Taranacak hisse sayısı: {len(tickers)}")

    # 2. Veri indir
    stock_data = download_all(tickers, period=DATA_PERIOD, interval=DATA_INTERVAL)

    # 3. Teknik analiz (seans içindeysek bugünün yarım mumu hacim hesabına katılmaz)
    results = analyze_all(stock_data)
    logger.info(f"Analiz tamamlandı. {len(results)} hisse analiz edildi.")

    # 4. Teknik alım sinyali olan hisseler
    buy_signals = [r for r in results if is_buy_signal(r)]
    watch_signals = [r for r in results if r["score"] == MIN_SCORE_TO_WATCH_ALERT]

    # 5. Yalnızca YENİ veya skoru YÜKSELEN sinyaller için derin analiz
    #    (temel analiz + haber + backtest + karar). Temeli zayıf olanlar elenir.
    alerts = []
    filtered = []
    for r in buy_signals:
        if not _should_alert(r["ticker"], r["score"], commit=False):
            continue
        full = full_analysis(r["ticker"], df=stock_data[r["ticker"]])
        if full is None:
            continue
        fund = full["fund"]
        if fund and fund["total"] < MIN_FUNDAMENTAL_SCORE_FOR_ALERT:
            why = fund["cons"][0] if fund["cons"] else f"temel puan {fund['total']}/100"
            filtered.append((r["ticker"], why))
            logger.info(f"  {r['ticker']} elendi: temel puan {fund['total']} ({why})")
            _should_alert(r["ticker"], r["score"])   # bugün tekrar değerlendirme
            continue
        alerts.append(full)

    # 6. Özet mesajı: ALWAYS_SEND_SUMMARY açıksa her taramada (nabız mesajı),
    #    değilse sadece yeni sinyal varsa gönderilir.
    if ALWAYS_SEND_SUMMARY or alerts:
        # Özet için tüm sinyallerin analist görüşü (temel analiz gün içi cache'li)
        analysts = {}
        for r in buy_signals:
            f = get_fundamentals(r["ticker"])
            analysts[r["ticker"]] = f.get("analyst") if f else None
        summary = format_summary(results, total_scanned=len(stock_data),
                                 regime=market_regime(), filtered=filtered, analysts=analysts)
        send_message(summary)

    # Sıralama: önce analistlerin de AL dediği, sonra en iyi karar, sonra en yüksek skor
    alerts.sort(key=lambda a: (a["decision"]["analyst_buy"], a["decision"]["level"], a["tech"]["score"]),
                reverse=True)
    for a in alerts:
        t = a["tech"]
        header = None
        if a["decision"]["analyst_buy"]:
            header = (f"✅ <b>[{MARKET}] ALIM SİNYALİ + ANALİSTLER AL DİYOR: {t['ticker']}</b>"
                      + (f" — {_esc(a['fund']['name'])}" if a["fund"] else ""))
        msg = format_buy_signal(t, reliability=a["reliability"], news=a["news"], fund=a["fund"],
                                decision=a["decision"], regime=a["regime"], header=header)
        ok = send_message(msg)
        if ok:
            _should_alert(t["ticker"], t["score"])
        if AI_REPORT_ON_SCAN:
            from ai_report import generate_report
            rep = generate_report(t["ticker"], t, a["fund"], a["news"], a["decision"], a["regime"])
            if rep:
                send_message(rep)
        logger.info(
            f"  {t['ticker']} | Skor: {t['score']}/{t['max_score']} | Karar: {a['decision']['verdict']} "
            f"| Temel: {a['fund']['total'] if a['fund'] else '—'} | Telegram: {'GÖNDERİLDİ' if ok else 'HATA'}"
        )
        time.sleep(0.5)

    # Öne çıkan hisseleri anlık haber takibine ekle (bir süre haberleri izlenir)
    flagged = [(a["tech"]["ticker"], a["fund"]["name"] if a["fund"] else a["tech"]["ticker"])
               for a in alerts if a["decision"]["level"] >= 3 or a["decision"]["analyst_buy"]]
    if flagged:
        from news_watcher import flag_tickers
        flag_tickers(flagged)

    if not alerts:
        if buy_signals:
            logger.info(f"{len(buy_signals)} teknik sinyal var ama yeni değil veya temel filtreye takıldı.")
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
        f"🔍 {MARKET} hisseleri taranacak\n"
        f"📊 Teknik (trend, NVI, RSI, MACD, Bollinger, hacim) + temel analiz (borç, kârlılık, büyüme)\n"
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
    elif "--news" in args:
        from config import NEWS_WATCH_ENABLED
        if NEWS_WATCH_ENABLED:
            from news_watcher import check_news
            check_news()
        else:
            logger.info("Haber takibi kapalı (NEWS_WATCH_ENABLED=False).")
    elif "--backtest" in args:
        run_backtest_cmd(args)
    else:
        run_scheduler()

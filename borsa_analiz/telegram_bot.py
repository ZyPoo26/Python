"""
İnteraktif Telegram botu (anlık sorgu).

Çalıştırma:
  python telegram_bot.py

Bilgisayarın açıkken çalışır ve Telegram'dan gelen mesajları dinler.
Telegram'da şunları yazabilirsin:
  THYAO            → THYAO hissesini anında analiz eder
  /analiz GARAN    → aynı şey
  /tara            → tüm BIST 100'ü tarar (birkaç dakika sürer)
  /durum           → botun aktif olduğunu doğrular
  /yardim          → komut listesi

Not: Bu, GitHub Actions'taki otomatik saatlik taramadan AYRIDIR.
Otomatik tarama GitHub'da çalışmaya devam eder; bu ise anlık sorgu içindir.
"""

import sys
import time
import logging
import requests

# Windows konsolu emoji için UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import yfinance as yf
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NEWS_ENABLED, DATA_PERIOD
from scraper import download_stock_data, US_POPULAR, BIST100_FALLBACK
from analyzer import analyze_stock
from backtest import get_reliability
from news_analyzer import get_news_sentiment
from telegram_notifier import send_message, format_buy_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

YARDIM = (
    "🤖 <b>Borsa Analiz Botu — Komutlar</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "• <code>THYAO</code> → hisseyi anında analiz et\n"
    "• <code>/analiz GARAN</code> → aynı şey\n"
    "• <code>/tara</code> → tüm BIST 100'ü tara (birkaç dk)\n"
    "• <code>/durum</code> → bot aktif mi?\n"
    "• <code>/yardim</code> → bu liste\n\n"
    "<i>İpucu: Sadece hisse kodunu yazman yeterli.</i>"
)


def detect_market(code: str) -> str | None:
    """
    Hisse kodunun hangi markete ait olduğunu otomatik tespit eder.
    Önce bilinen listelerden (hızlı), bulunamazsa yfinance ile dener.
    """
    code = code.upper().strip()
    if code in US_POPULAR:
        return "US"
    if code in BIST100_FALLBACK:
        return "BIST"
    # Bilinmiyorsa canlı dene: önce BIST (.IS), sonra ABD (uzantısız)
    try:
        if not yf.download(f"{code}.IS", period="5d", progress=False, auto_adjust=True).empty:
            return "BIST"
    except Exception:
        pass
    try:
        if not yf.download(code, period="5d", progress=False, auto_adjust=True).empty:
            return "US"
    except Exception:
        pass
    return None


def analyze_one(code: str) -> str:
    """Tek bir hisseyi (market otomatik tespit edilerek) analiz eder."""
    code = code.upper().strip().lstrip("/").replace("ANALIZ", "").strip()
    if not code or not code.replace("-", "").isalnum():
        return "❌ Geçerli bir hisse kodu yaz. Örnek: <code>THYAO</code> veya <code>AAPL</code>"
    market = detect_market(code)
    if market is None:
        return f"❌ <b>{code}</b>: BIST veya ABD borsasında bulunamadı. Kodu doğru yazdın mı?"
    send_message(f"🔍 <b>[{'ABD' if market == 'US' else 'BIST'}] {code}</b> analiz ediliyor, bir saniye...")
    df = download_stock_data(code, period=DATA_PERIOD, market=market)
    if df is None:
        return f"❌ <b>{code}</b>: veri bulunamadı."
    result = analyze_stock(code, df)
    if result is None:
        return f"❌ <b>{code}</b>: analiz edilemedi (yeterli veri yok)."
    reliability = get_reliability(code, market=market)
    news = get_news_sentiment(code, market=market) if NEWS_ENABLED else None
    return format_buy_signal(result, reliability=reliability, news=news, market=market)


def handle_command(text: str):
    """Gelen metni yorumlayıp uygun cevabı gönderir."""
    low = text.lower().strip()

    if low in ("/start", "/yardim", "/help", "yardim", "yardım"):
        send_message(YARDIM)
    elif low.startswith("/durum") or low == "durum":
        send_message(
            "✅ <b>Bot aktif ve dinlemede.</b>\n"
            f"🕐 {time.strftime('%d.%m.%Y %H:%M')}\n"
            "Bir hisse kodu yazarak analiz isteyebilirsin."
        )
    elif low.startswith("/tara") or low == "tara":
        send_message("🔍 <b>Tüm BIST 100 taranıyor...</b> Bu birkaç dakika sürebilir.")
        from main import run_scan
        run_scan(force=True)
        send_message("✅ Tarama tamamlandı.")
    else:
        # Hisse kodu olarak yorumla (örn "THYAO" veya "/analiz THYAO")
        send_message(analyze_one(text))


def safe_handle(text: str):
    """handle_command'i hataya karşı sarar; hata olsa bile bot çökmez ve kullanıcı bilgilendirilir."""
    try:
        handle_command(text)
    except Exception as e:
        logger.error(f"Komut işlenirken hata: {e}", exc_info=True)
        try:
            send_message(f"⚠️ İşlem sırasında hata oluştu: {e}\nTekrar dener misin?")
        except Exception:
            pass


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID .env içinde tanımlı değil!")
        return

    # Bağlantı testi + olası webhook'u temizle (getUpdates'i engellememesi için)
    try:
        me = requests.get(f"{API}/getMe", timeout=10).json()
        if not me.get("ok"):
            print("❌ Bot token geçersiz. .env dosyasını kontrol et.")
            return
        requests.get(f"{API}/deleteWebhook", timeout=10)
        logger.info(f"Bot bağlandı: @{me['result']['username']}")
    except Exception as e:
        print(f"❌ Telegram'a bağlanılamadı: {e}")
        return

    send_message("💬 <b>İnteraktif bot başlatıldı!</b>\nBir hisse kodu yaz (örn: <code>THYAO</code>) veya /yardim")
    logger.info("Dinlemede... (Çıkmak için Ctrl+C)")

    offset = None
    while True:
        try:
            resp = requests.get(
                f"{API}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=40,
            )
            updates = resp.json().get("result", [])
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message") or u.get("edited_message")
                if not msg:
                    continue
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip()
                # Güvenlik: sadece kendi chat_id'inden gelen mesajlara cevap ver
                if chat_id != str(TELEGRAM_CHAT_ID):
                    logger.warning(f"Yetkisiz chat_id'den mesaj yok sayıldı: {chat_id}")
                    continue
                if not text:
                    continue
                logger.info(f"Gelen mesaj: {text}")
                safe_handle(text)
        except KeyboardInterrupt:
            print("\nBot durduruldu.")
            break
        except Exception as e:
            logger.error(f"Döngü hatası: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()

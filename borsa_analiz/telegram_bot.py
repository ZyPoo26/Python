"""
İnteraktif Telegram botu (anlık sorgu).

Çalıştırma:
  python telegram_bot.py

Bilgisayarın açıkken çalışır ve Telegram'dan gelen mesajları dinler.
Telegram'da şunları yazabilirsin:
  THYAO            → karar + şirket sağlığı + teknik + yol haritası
  /analiz GARAN    → aynı şey
  /temel ASELS     → sadece bilanço/borç/kârlılık analizi
  /rapor THYAO     → yukarıdakiler + yapay zekâ ile detaylı şirket raporu
                     (borç süreci, gelecek olaylar, senaryolar) — ANTHROPIC_API_KEY gerekir
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
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from scraper import US_POPULAR, BIST100_FALLBACK
from advisor import full_analysis
from fundamentals import get_fundamentals
import ai_report
from telegram_notifier import send_message, format_buy_signal, format_fund_only

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

YARDIM = (
    "🤖 <b>Borsa Analiz Botu — Komutlar</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "• <code>THYAO</code> → karar + şirket sağlığı + yol haritası\n"
    "• <code>/analiz GARAN</code> → aynı şey\n"
    "• <code>/temel ASELS</code> → sadece bilanço / borç / kârlılık\n"
    "• <code>/rapor THYAO</code> → + yapay zekâ detaylı şirket raporu\n"
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


def _resolve(text: str) -> tuple[str | None, str | None, str | None]:
    """Mesajdan hisse kodunu çıkarır ve marketini bulur. (kod, market, hata)"""
    parts = text.strip().split()
    code = parts[-1].upper().lstrip("/") if parts else ""
    if not code or code.startswith(("ANALIZ", "TEMEL", "RAPOR")) or not code.replace("-", "").replace(".", "").isalnum():
        return None, None, "❌ Geçerli bir hisse kodu yaz. Örnek: <code>THYAO</code> veya <code>/rapor AAPL</code>"
    market = detect_market(code)
    if market is None:
        return code, None, f"❌ <b>{code}</b>: BIST veya ABD borsasında bulunamadı. Kodu doğru yazdın mı?"
    return code, market, None


def analyze_one(text: str, with_ai: bool = False) -> str:
    """Tek bir hisseyi tüm yönleriyle analiz eder; with_ai=True ise AI raporu da gönderir."""
    code, market, err = _resolve(text)
    if err:
        return err
    label = "ABD" if market == "US" else "BIST"
    send_message(f"🔍 <b>[{label}] {code}</b> analiz ediliyor (fiyat, bilanço, haber, backtest)...")
    a = full_analysis(code, market=market)
    if a is None:
        return f"❌ <b>{code}</b>: veri bulunamadı veya analiz için yeterli değil."
    card = format_buy_signal(a["tech"], reliability=a["reliability"], news=a["news"], market=market,
                             fund=a["fund"], decision=a["decision"], regime=a["regime"])
    if not with_ai:
        if ai_report.is_enabled():
            card += f"\n\n💡 Detaylı AI raporu için: <code>/rapor {code}</code>"
        return card
    send_message(card)
    if not ai_report.is_enabled():
        return ("ℹ️ AI raporu için .env dosyasına <code>ANTHROPIC_API_KEY</code> ekle "
                "(console.anthropic.com'dan alınır). Yukarıdaki kural tabanlı analiz yine geçerli.")
    send_message("🤖 Yapay zekâ raporu hazırlanıyor (güncel haberler taranıyor, ~1-2 dk)...")
    rep = ai_report.generate_report(code, a["tech"], a["fund"], a["news"], a["decision"], a["regime"], market)
    return rep or "⚠️ AI raporu üretilemedi."


def fundamentals_one(text: str) -> str:
    code, market, err = _resolve(text)
    if err:
        return err
    send_message(f"🏦 <b>{code}</b> bilançosu inceleniyor...")
    fund = get_fundamentals(code, market)
    if fund is None:
        return f"❌ <b>{code}</b>: finansal tablo verisi bulunamadı."
    return format_fund_only(fund, market)


def handle_command(text: str):
    """Gelen metni yorumlayıp uygun cevabı gönderir."""
    low = text.lower().strip()

    if low in ("/start", "/yardim", "/help", "yardim", "yardım"):
        send_message(YARDIM)
    elif low.startswith("/durum") or low == "durum":
        send_message(
            "✅ <b>Bot aktif ve dinlemede.</b>\n"
            f"🕐 {time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🤖 AI raporu: {'açık' if ai_report.is_enabled() else 'kapalı (ANTHROPIC_API_KEY yok)'}\n"
            "Bir hisse kodu yazarak analiz isteyebilirsin."
        )
    elif low.startswith("/tara") or low == "tara":
        send_message("🔍 <b>Tüm liste taranıyor...</b> Bu birkaç dakika sürebilir.")
        from main import run_scan
        run_scan(force=True)
        send_message("✅ Tarama tamamlandı.")
    elif low.startswith("/temel"):
        send_message(fundamentals_one(text))
    elif low.startswith("/rapor"):
        send_message(analyze_one(text, with_ai=True))
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

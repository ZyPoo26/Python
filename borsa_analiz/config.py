import os
from dotenv import load_dotenv

load_dotenv()

# .strip() önemli: GitHub Secret'a yapıştırırken sona eklenen görünmez
# boşluk/satır sonu (%0A) token'ı bozar ve 404 hatasına yol açar. Temizliyoruz.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Teknik analiz parametreleri
RSI_PERIOD = 14
RSI_OVERSOLD = 38       # Bu seviyenin altı aşırı satım
RSI_OVERBOUGHT = 68     # Bu seveyinin üstü aşırı alım
NVI_EMA_PERIOD = 255    # Standart NVI sinyal çizgisi (yaklaşık 1 yıl)
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 20
VOLUME_MA_PERIOD = 20

# Kaç puanın üzerindeki hisseler Telegram'a gönderilsin (max 6)
MIN_SCORE_TO_BUY_ALERT = 3
MIN_SCORE_TO_WATCH_ALERT = 2   # 2 puan = "İzle" mesajı

# True ise: her taramada kısa bir özet mesajı gönderilir (sinyal olmasa bile),
# böylece botun çalıştığını görürsün. False ise: sadece yeni sinyal varsa mesaj gelir.
ALWAYS_SEND_SUMMARY = True

# Verinin kaç günlük periyotta çekilmesi
DATA_PERIOD = "1y"
DATA_INTERVAL = "1d"

# ─── Tarama Zamanlaması ─────────────────────────────────────────────────────
# SCAN_MODE = "hourly"  → Piyasa açıkken HER SAAT BAŞI tarar (anlık takip).
# SCAN_MODE = "fixed"   → Aşağıdaki SCAN_TIMES saatlerinde tarar.
SCAN_MODE = "hourly"

# "fixed" modunda kullanılacak sabit saatler (24-saat formatı, Türkiye saati)
SCAN_TIMES = ["10:00", "13:00", "16:30"]

# Piyasa saatleri (BIST hisse seansı, Türkiye saati). Bu aralık dışında tarama yapılmaz.
MARKET_OPEN_HOUR = 10    # 10:00
MARKET_CLOSE_HOUR = 18   # 18:00
# Hafta sonu (Cumartesi/Pazar) borsa kapalı → tarama yapılmaz.
SKIP_WEEKENDS = True

# ─── Risk Yönetimi / Stop-Loss / Hedef ──────────────────────────────────────
ATR_PERIOD = 14              # Volatilite (ATR) hesap periyodu
ATR_STOP_MULT = 2.0          # Stop-loss = giriş - (2.0 x ATR)
ATR_TARGET_MULT = 3.0        # Hedef    = giriş + (3.0 x ATR) → Risk/Ödül ≈ 1:1.5

# Portföy kuralları (Telegram mesajında hatırlatma olarak gösterilir)
MAX_POSITION_PCT = 5         # Tek hisseye portföyün en fazla %5'i
MAX_POSITIONS = 6            # Aynı anda en fazla 6 farklı hissede dur
MAX_SECTOR_PCT = 30          # Tek sektöre en fazla %30

# ─── Backtest ────────────────────────────────────────────────────────────────
BACKTEST_PERIOD = "2y"       # Backtest için kaç yıllık veri çekilsin
BACKTEST_MIN_SCORE = 3       # Backtest'te kaç puanda "AL" kabul edilsin
BACKTEST_MAX_HOLD_DAYS = 30  # Stop/hedef değmezse en fazla kaç gün tut

# ─── Haber Analizi (Sentiment) ───────────────────────────────────────────────
NEWS_ENABLED = True          # Haber analizi açık mı
NEWS_MAX_HEADLINES = 10      # Hisse başına kaç son başlık değerlendirilsin
# Güçlü olumsuz haber (bu skorun altı) varsa sinyale büyük uyarı eklenir
NEWS_STRONG_NEGATIVE = -2

# Türkçe finans haberlerinde OLUMLU sinyal veren kelimeler
NEWS_POSITIVE_WORDS = [
    "rekor", "kâr", "net kar", "kar artış", "kârında artış", "ihale", "ihale aldı",
    "anlaşma", "sözleşme", "temettü", "bedelsiz", "yükseliş", "ralli", "tavan",
    "alım", "büyüme", "yatırım", "ihracat", "zirve", "prim", "satın aldı",
    "kazandı", "beklentiyi aştı", "güçlü", "olumlu", "yeni fabrika",
    "kapasite artış", "hedef fiyat yükselt", "tavsiye yükselt", "AL tavsiyesi",
    "ortaklık", "iş birliği", "işbirliği", "yeni proje", "lisans aldı",
]
# Türkçe finans haberlerinde OLUMSUZ sinyal veren kelimeler
NEWS_NEGATIVE_WORDS = [
    "zarar", "düşüş", "ceza", "soruşturma", "dava", "iflas", "konkordato",
    "gözaltı", "taban", "kâr düşüş", "küçülme", "fesih", "iptal", "uyarı",
    "risk", "kaza", "grev", "istifa", "SPK cezası", "vergi cezası",
    "zayıf", "olumsuz", "satış baskısı", "ihale iptal", "haciz", "rüşvet",
    "yolsuzluk", "tedbir", "hisse satış", "zarar açıkladı", "tahsilat sorunu",
]

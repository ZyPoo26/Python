import os
from dotenv import load_dotenv

load_dotenv()

# .strip() önemli: GitHub Secret'a yapıştırırken sona eklenen görünmez
# boşluk/satır sonu (%0A) token'ı bozar ve 404 hatasına yol açar. Temizliyoruz.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# ─── Piyasa Seçimi ───────────────────────────────────────────────────────────
# MARKET çevre değişkeniyle seçilir. Varsayılan "BIST" → mevcut BIST botu aynen
# çalışır. "US" verilince ABD (S&P 500) moduna geçer.
MARKET = os.getenv("MARKET", "BIST").upper()
IS_US = MARKET == "US"

# Market etiketi (Telegram başlıklarında) ve para birimi
MARKET_LABEL = "ABD" if IS_US else "BIST"
CURRENCY = "$" if IS_US else "TL"          # $ fiyatın ÖNÜNE, TL ARKASINA gelir
CURRENCY_PREFIX = IS_US                      # True → "$297.53", False → "142.20 TL"

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

# Piyasa saatleri (Türkiye saati). Bu aralık dışında tarama yapılmaz.
# BIST: 10:00–18:00 | ABD borsası TR saatiyle ~16:30–23:00 (yaz saati)
if IS_US:
    MARKET_OPEN_HOUR = 16
    MARKET_CLOSE_HOUR = 23
else:
    MARKET_OPEN_HOUR = 10
    MARKET_CLOSE_HOUR = 18
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

# İşlem maliyeti: her AL ve her SAT için tek yönlü oran (komisyon + spread/slippage).
# BIST ~%0.2, ABD ~%0.05. Her işlem çiftinde (al+sat) iki kez uygulanır.
# Backtest gerçekçi olsun diye getiriden düşülür.
COMMISSION_PCT = 0.2 if IS_US is False else 0.05

# ─── Haber Analizi (Sentiment) ───────────────────────────────────────────────
NEWS_ENABLED = True          # Haber analizi açık mı
NEWS_MAX_HEADLINES = 10      # Hisse başına kaç son başlık değerlendirilsin
# Güçlü olumsuz haber (bu skorun altı) varsa sinyale büyük uyarı eklenir
NEWS_STRONG_NEGATIVE = -2

# Google News dil/bölge ayarı (haber sorgusu için)
NEWS_LOCALE = "hl=en-US&gl=US&ceid=US:en" if IS_US else "hl=tr&gl=TR&ceid=TR:tr"
NEWS_QUERY_SUFFIX = "stock" if IS_US else "hisse"

# Türkçe finans haberlerinde OLUMLU/OLUMSUZ kelimeler
_TR_POSITIVE = [
    "rekor", "kâr", "net kar", "kar artış", "kârında artış", "ihale", "ihale aldı",
    "anlaşma", "sözleşme", "temettü", "bedelsiz", "yükseliş", "ralli", "tavan",
    "alım", "büyüme", "yatırım", "ihracat", "zirve", "prim", "satın aldı",
    "kazandı", "beklentiyi aştı", "güçlü", "olumlu", "yeni fabrika",
    "kapasite artış", "hedef fiyat yükselt", "tavsiye yükselt", "AL tavsiyesi",
    "ortaklık", "iş birliği", "işbirliği", "yeni proje", "lisans aldı",
]
_TR_NEGATIVE = [
    "zarar", "düşüş", "ceza", "soruşturma", "dava", "iflas", "konkordato",
    "gözaltı", "taban", "kâr düşüş", "küçülme", "fesih", "iptal", "uyarı",
    "risk", "kaza", "grev", "istifa", "SPK cezası", "vergi cezası",
    "zayıf", "olumsuz", "satış baskısı", "ihale iptal", "haciz", "rüşvet",
    "yolsuzluk", "tedbir", "hisse satış", "zarar açıkladı", "tahsilat sorunu",
]
# İngilizce (ABD) finans haberlerinde OLUMLU/OLUMSUZ kelimeler
_US_POSITIVE = [
    "beat", "beats", "earnings beat", "record", "surge", "soar", "rally",
    "upgrade", "upgraded", "buy rating", "outperform", "price target raised",
    "raises guidance", "strong", "growth", "profit", "all-time high", "jumps",
    "tops estimates", "acquisition", "partnership", "approval", "approved",
    "dividend", "buyback", "expansion", "breakthrough", "bullish",
]
_US_NEGATIVE = [
    "miss", "misses", "earnings miss", "plunge", "plummet", "crash", "drop",
    "downgrade", "downgraded", "sell rating", "underperform", "cuts guidance",
    "lawsuit", "investigation", "probe", "fine", "recall", "bankruptcy",
    "layoffs", "weak", "loss", "warning", "decline", "slump", "bearish",
    "fraud", "delay", "halt", "sec charges", "antitrust",
]

NEWS_POSITIVE_WORDS = _US_POSITIVE if IS_US else _TR_POSITIVE
NEWS_NEGATIVE_WORDS = _US_NEGATIVE if IS_US else _TR_NEGATIVE


# ─── Market Profili (merkezi) ────────────────────────────────────────────────
def get_profile(market: str | None = None) -> dict:
    """
    Belirtilen market için tüm market-spesifik ayarları döner.
    market=None ise aktif MARKET (env) kullanılır → otomatik botların davranışı
    hiç değişmez. İnteraktif bot ise her sorguda doğru market'i geçirir.
    """
    m = (market or MARKET).upper()
    is_us = m == "US"
    return {
        "market": m,
        "is_us": is_us,
        "label": "ABD" if is_us else "BIST",
        "currency": "$" if is_us else "TL",
        "currency_prefix": is_us,                 # True → "$297", False → "142 TL"
        "suffix": "" if is_us else ".IS",         # yfinance ticker uzantısı
        "news_locale": "hl=en-US&gl=US&ceid=US:en" if is_us else "hl=tr&gl=TR&ceid=TR:tr",
        "news_query": "stock" if is_us else "hisse",
        "news_pos": _US_POSITIVE if is_us else _TR_POSITIVE,
        "news_neg": _US_NEGATIVE if is_us else _TR_NEGATIVE,
    }

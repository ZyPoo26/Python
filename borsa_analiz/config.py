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

# True ise: ana trend aşağıdaysa (fiyat MA200 altı) skor ne olursa olsun AL sinyali
# üretilmez. 25 hisselik 3 yıllık testte (iz süren stop ile) False daha iyi sonuç
# verdi; trend zaten 6 puandan biri olarak skora giriyor.
REQUIRE_TREND_FOR_BUY = False
MIN_SCORE_TO_WATCH_ALERT = 2   # 2 puan = "İzle" mesajı

# True ise: her taramada kısa bir özet mesajı gönderilir (sinyal olmasa bile),
# böylece botun çalıştığını görürsün. False ise: sadece yeni sinyal varsa mesaj gelir.
ALWAYS_SEND_SUMMARY = True

# Verinin kaç günlük periyotta çekilmesi.
# 2 yıl: MA200 ve NVI'nin 255 günlük EMA'sının oturması için 1 yıl yetmiyor.
DATA_PERIOD = "2y"
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

# Çıkış yöntemi:
#  "trailing" → İz süren stop: fiyat yükseldikçe stop da yukarı kayar (zirveden
#               ATR_TRAIL_MULT × ATR aşağıda). Sabit hedef yok, kâr koşmaya bırakılır.
#  "fixed"    → Eski yöntem: sabit stop + sabit hedef.
EXIT_MODE = "trailing"
ATR_TRAIL_MULT = 3.0

# Portföy kuralları (Telegram mesajında hatırlatma olarak gösterilir)
MAX_POSITION_PCT = 5         # Tek hisseye portföyün en fazla %5'i
MAX_POSITIONS = 6            # Aynı anda en fazla 6 farklı hissede dur
MAX_SECTOR_PCT = 30          # Tek sektöre en fazla %30

# ─── Backtest ────────────────────────────────────────────────────────────────
BACKTEST_PERIOD = "3y"       # Backtest için kaç yıllık veri çekilsin (ilk ~1 yıl göstergelerin oturmasına gider)
BACKTEST_MIN_SCORE = 3       # Backtest'te kaç puanda "AL" kabul edilsin
BACKTEST_MAX_HOLD_DAYS = 30  # "fixed" modda stop/hedef değmezse en fazla kaç gün tut
BACKTEST_MAX_HOLD_DAYS_TRAIL = 120  # "trailing" modda en fazla kaç gün tut

# İşlem maliyeti: her AL ve her SAT için tek yönlü oran (komisyon + spread/slippage).
# BIST ~%0.2, ABD ~%0.05. Her işlem çiftinde (al+sat) iki kez uygulanır.
# Backtest gerçekçi olsun diye getiriden düşülür.
COMMISSION_PCT = 0.2 if IS_US is False else 0.05

# ─── Temel Analiz (Bilanço) ─────────────────────────────────────────────────
FUNDAMENTALS_ENABLED = True
# Temel puanı (0-100) bu değerin altındaki şirketler için otomatik taramada
# AL sinyali GÖNDERİLMEZ (sadece log'a yazılır). 0 yaparsan filtre kapanır.
MIN_FUNDAMENTAL_SCORE_FOR_ALERT = 40

# Türkiye yıllık TÜFE (%). TL raporlayan BIST şirketlerinde satış büyümesi ve
# ROE bununla kıyaslanır (%30 büyüme, %30 enflasyonda reel büyüme DEĞİLDİR).
# TÜİK her ay açıkladıkça güncelle.
TR_INFLATION_PCT = float(os.getenv("TR_INFLATION_PCT", "30"))

# ─── Yapay Zekâ Raporu (Claude) ──────────────────────────────────────────────
# ANTHROPIC_API_KEY tanımlıysa /rapor komutu Claude ile detaylı şirket raporu
# yazar (borç süreci, gelecek katalizörleri, senaryolar, yol haritası).
# Tanımlı değilse bot yine çalışır; sadece kural tabanlı değerlendirme verir.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
AI_MODEL = "claude-opus-5-5"
# True: rapor yazarken Claude internette güncel haber/KAP açıklaması arar (daha
# isabetli, biraz daha maliyetli). False: sadece botun topladığı veriyi kullanır.
AI_WEB_SEARCH = True
AI_MAX_SEARCHES = 5
# Otomatik taramada her AL sinyaline AI raporu eklensin mi? (maliyet → varsayılan kapalı)
AI_REPORT_ON_SCAN = False

# ─── Anlık Haber Bildirimi ──────────────────────────────────────────────────
# Önemli şirketlerde ÖNEMLİ bir haber çıkınca Telegram'a bildirim atar.
# "Önemli şirketler" = aşağıdaki takip listesi + botun son günlerde önerdiği
# (karar TEMKİNLİ AL / AL ADAYI ya da analistlerin AL dediği) hisseler.
NEWS_WATCH_ENABLED = True
NEWS_WATCH_MIN_IMPORTANCE = 3     # Bu puanın altındaki haberler bildirilmez (rutin haber elenir)
NEWS_WATCH_MAX_AGE_HOURS = 6      # Sadece son X saatte yayınlanmış haberler
NEWS_WATCH_COOLDOWN_HOURS = 4     # Aynı şirket için en az X saat arayla bildirim…
NEWS_WATCH_URGENT_IMPORTANCE = 6  # …ama bu puan ve üstü (iflas, soruşturma vb.) beklemeden gelir
NEWS_WATCH_MAX_PER_RUN = 4        # Bir kontrolde en fazla X şirket için bildirim (spam önleme)
NEWS_WATCH_FLAG_DAYS = 14         # Botun önerdiği hisse kaç gün takipte kalsın

# Sabit takip listesi: kod → haberde aranacak şirket adı (küçük harf, ayırt edici kısım)
NEWS_WATCHLIST_BIST = {
    "THYAO": "türk hava yolları", "ASELS": "aselsan", "TUPRS": "tüpraş", "KCHOL": "koç holding",
    "SAHOL": "sabancı", "GARAN": "garanti", "AKBNK": "akbank", "YKBNK": "yapı kredi",
    "ISCTR": "iş bankası", "BIMAS": "bim", "EREGL": "ereğli", "FROTO": "ford otosan",
    "TOASO": "tofaş", "PGSUS": "pegasus", "TCELL": "turkcell", "SISE": "şişecam",
    "ENKAI": "enka", "KRDMD": "kardemir", "SASA": "sasa", "MGROS": "migros",
}
NEWS_WATCHLIST_US = {
    "AAPL": "apple", "MSFT": "microsoft", "NVDA": "nvidia", "GOOGL": "alphabet", "AMZN": "amazon",
    "META": "meta", "TSLA": "tesla", "AMD": "amd", "AVGO": "broadcom", "JPM": "jpmorgan",
    "V": "visa", "LLY": "eli lilly", "UNH": "unitedhealth", "XOM": "exxon", "NFLX": "netflix",
    "PLTR": "palantir", "BRK-B": "berkshire", "WMT": "walmart", "COST": "costco", "BA": "boeing",
}

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
    "büyüme", "yeni yatırım", "yatırım kararı", "ihracat", "zirve", "prim", "satın aldı",
    "kazandı", "beklentiyi aştı", "güçlü", "olumlu", "yeni fabrika",
    "kapasite artış", "hedef fiyatını yükseltti", "hedef fiyat yükselt", "tavsiye yükselt", "AL tavsiyesi",
    "ortaklık", "iş birliği", "işbirliği", "yeni proje", "lisans aldı",
]
_TR_NEGATIVE = [
    "zarar", "düşüş", "ceza", "soruşturma", "dava", "iflas", "konkordato",
    "gözaltı", "taban", "kâr düşüş", "küçülme", "fesih", "iptal", "uyarı",
    "risk", "kaza", "grev", "istifa", "SPK cezası", "vergi cezası",
    "zayıf", "olumsuz", "satış baskısı", "ihale iptal", "haciz", "rüşvet",
    "yolsuzluk", "tedbir", "hisse satış", "zarar açıkladı", "tahsilat sorunu",
    "düşürdü", "hedef fiyatını düşür", "indirdi", "geriledi", "sert düş", "sat tavsiyesi",
    "borç yapılandırma", "temerrüt", "kredi notu düş", "not indirimi",
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
        # Seans saatleri (Türkiye saati) — seans içi yarım gün tespiti için
        "open_hour": 16 if is_us else 10,
        "close_hour": 23 if is_us else 18,
    }

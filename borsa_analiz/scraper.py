"""
BIST 100 hisse listesini internetten doğrulayan ve yfinance ile fiyat/hacim
verilerini indiren modül.

Not: BIST 100 endeks bileşen listesini anlık veren ücretsiz/açık bir endpoint
yok (Bigpara, İş Yatırım gibi kaynaklar endeks API'sini bot erişimine kapatmış).
Bu yüzden strateji şu: Aşağıdaki güncel BIST 100 referans listesi, Bigpara'nın
ÇALIŞAN "tüm işlem gören hisseler" API'si ile kesiştirilir. Böylece borsadan
çıkmış / işlem görmeyen kodlar canlı olarak elenir.
"""

import requests
import yfinance as yf
import pandas as pd
import time
import logging

from config import IS_US

logger = logging.getLogger(__name__)

# Borsada işlem gören tüm hisseleri canlı veren çalışan API (endeks filtresi yok).
LISTED_API = "https://bigpara.hurriyet.com.tr/api/v1/hisse/list"

# Popüler ~100 ABD hissesi (mega-cap + en likit). MARKET=US iken kullanılır.
US_POPULAR = [
    # Teknoloji
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC",
    "CRM", "ORCL", "ADBE", "CSCO", "AVGO", "QCOM", "TXN", "IBM", "NOW",
    "INTU", "AMAT", "MU", "LRCX", "PANW", "SNPS", "CDNS",
    # İletişim / medya
    "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS",
    # Tüketici
    "WMT", "COST", "HD", "NKE", "MCD", "SBUX", "TGT", "LOW", "BKNG",
    "PG", "KO", "PEP", "PM", "MDLZ",
    # Finans
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "V", "MA", "PYPL",
    "BLK", "SCHW",
    # Sağlık
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR",
    "BMY", "AMGN", "GILD", "CVS",
    # Enerji
    "XOM", "CVX", "COP", "SLB",
    # Sanayi
    "BA", "CAT", "GE", "HON", "UPS", "RTX", "LMT", "DE", "MMM",
    # Otomotiv
    "F", "GM",
    # Popüler / yüksek hacimli
    "BRK-B", "UBER", "ABNB", "SHOP", "COIN", "PLTR", "SOFI", "SNAP",
    "PINS", "ROKU",
]

# Güncel BIST 100 referans listesi. Endeks yılda ~2 kez revize edilir; gerekirse
# buradan güncellenir. API ile kesiştirilerek geçersiz kodlar otomatik elenir.
BIST100_FALLBACK = [
    "AKBNK", "AKSEN", "ALARK", "ALBRK", "ALFAS", "ALKIM", "ANACM", "ARCLK",
    "ARDYZ", "ASELS", "ASTOR", "AYDEM", "AYGAZ", "BERA", "BIMAS", "BRISA",
    "BRYAT", "BTCIM", "CCOLA", "CIMSA", "CWENE", "DOAS", "DOHOL", "EKGYO",
    "ENERY", "ENJSA", "ENKAI", "ERBOS", "EREGL", "EUPWR", "FROTO",
    "GARAN", "GESAN", "GUBRF", "HALKB", "HEKTS", "ISCTR", "ISFIN",
    "ISGYO", "ISMEN", "KARSN", "KCAER", "KCHOL", "KLNMA",
    "KONTR", "KONYA", "KORDS", "KOZAA", "KOZAL", "KRDMD", "LOGO", "MAVI",
    "MGROS", "MIATK", "OTKAR", "OYAKC", "PEKGY", "PETKM", "PGSUS",
    "SAHOL", "SASA", "SISE", "SKBNK", "SOKM",
    "TAVHL", "TCELL", "THYAO", "TKFEN", "TMSN", "TOASO", "TSKB", "TTKOM",
    "TTRAK", "TUPRS", "ULKER", "VAKBN", "VESTL",
    "YKBNK", "AGESA", "ODAS", "TRGYO", "KCAER", "KERVT",
    "SELEC", "KMPUR", "ZEREN", "NETAS", "RGYAS", "PARSN", "UFUK",
    "QUAGR", "TURSG", "SMRTG", "YYLGD", "VERUS"
]


def fetch_listed_tickers() -> set[str]:
    """
    Bigpara API'sinden borsada işlem gören TÜM hisse kodlarını çeker.
    Başarısız olursa boş küme döner.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(LISTED_API, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        codes = {
            item["kod"].strip().upper()
            for item in data
            if item.get("tip") == "Hisse" and item.get("kod")
        }
        if len(codes) >= 100:
            logger.info(f"Canlı API'den {len(codes)} işlem gören hisse kodu alındı.")
            return codes
        logger.warning(f"API'den beklenenden az kod geldi ({len(codes)}).")
    except Exception as e:
        logger.warning(f"Canlı hisse listesi alınamadı: {e}")
    return set()


def get_tickers() -> list[str]:
    """
    Taranacak hisse listesini market'e göre döner.
    ABD: popüler ~100 hisse. BIST: referans liste, canlı API ile doğrulanmış.
    """
    if IS_US:
        logger.info(f"ABD modu: {len(US_POPULAR)} popüler hisse taranacak.")
        return US_POPULAR

    listed = fetch_listed_tickers()
    if not listed:
        logger.info("Canlı doğrulama yapılamadı, referans BIST 100 listesi kullanılıyor.")
        return BIST100_FALLBACK

    valid = [t for t in BIST100_FALLBACK if t in listed]
    removed = [t for t in BIST100_FALLBACK if t not in listed]
    if removed:
        logger.info(f"Canlı doğrulamada {len(removed)} kod elendi (işlem görmüyor): {', '.join(removed)}")
    logger.info(f"Doğrulanmış {len(valid)} BIST 100 hissesi taranacak.")
    return valid


# Geriye dönük uyumluluk (eski isimle çağıranlar için)
get_bist100_tickers = get_tickers


def download_stock_data(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
    """
    Tek bir hisse için OHLCV verisi indirir.
    Türk hisseleri Yahoo'da '.IS' uzantısıyla aranır; ABD hisseleri doğrudan (AAPL).
    """
    if IS_US:
        yf_ticker = ticker  # ABD: AAPL, MSFT... uzantısız
    else:
        yf_ticker = ticker if ticker.endswith(".IS") else f"{ticker}.IS"
    try:
        df = yf.download(
            yf_ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        if df.empty or len(df) < 60:
            logger.debug(f"{ticker}: yeterli veri yok ({len(df)} gün).")
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.dropna()
        return df
    except Exception as e:
        logger.debug(f"{ticker} indirme hatası: {e}")
        return None


def download_all(tickers: list[str], period: str = "1y", interval: str = "1d", delay: float = 0.3) -> dict[str, pd.DataFrame]:
    """
    Tüm hisseler için veri indirir.
    delay: yfinance rate-limit'e takılmamak için istek arası bekleme (saniye).
    """
    results = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers, 1):
        logger.info(f"[{i}/{total}] {ticker} indiriliyor...")
        df = download_stock_data(ticker, period=period, interval=interval)
        if df is not None:
            results[ticker] = df
        time.sleep(delay)
    logger.info(f"Toplam {len(results)}/{total} hisse için veri indirildi.")
    return results

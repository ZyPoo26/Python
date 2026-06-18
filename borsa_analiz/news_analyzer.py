"""
Haber analizi (sentiment) modülü.

Google News RSS'ten hisseye dair son Türkçe haber başlıklarını çeker ve
anahtar kelime tabanlı bir duygu (sentiment) puanı üretir.

Mantık:
  - Olumlu kelime (rekor, ihale, temettü...) → +1
  - Olumsuz kelime (zarar, ceza, soruşturma...) → -1
  Negatif haberler risk açısından daha kritik olduğu için, güçlü olumsuz
  sinyalde (NEWS_STRONG_NEGATIVE altı) sinyale büyük uyarı eklenir.

Not: Anahtar kelime yöntemi bağlamı (ironi, koşul) anlamaz; başlıklar
genelde net olduğu için pratikte iyi çalışır, ama %100 doğru değildir.
"""

import requests
import logging
import re
from xml.etree import ElementTree
from datetime import datetime

from config import (
    NEWS_MAX_HEADLINES, NEWS_POSITIVE_WORDS, NEWS_NEGATIVE_WORDS,
    NEWS_STRONG_NEGATIVE, NEWS_LOCALE, NEWS_QUERY_SUFFIX,
)

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr,en;q=0.9",
}

# Gün içi tekrar tekrar aynı hissenin haberini çekmemek için gün bazlı cache.
_news_cache: dict[str, dict[str, dict]] = {}


def fetch_headlines(ticker: str) -> list[str]:
    """Google News RSS'ten hisseye dair son haber başlıklarını çeker."""
    query = f"{ticker} {NEWS_QUERY_SUFFIX}"
    url = (
        f"https://news.google.com/rss/search?q={requests.utils.quote(query)}"
        f"&{NEWS_LOCALE}"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
        titles = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                # "Başlık - Kaynak" formatından kaynak adını ayıkla
                titles.append(title_el.text.strip())
            if len(titles) >= NEWS_MAX_HEADLINES:
                break
        return titles
    except Exception as e:
        logger.debug(f"{ticker} haber çekme hatası: {e}")
        return []


def score_headlines(ticker: str, headlines: list[str]) -> dict:
    """Başlıkları anahtar kelimelere göre puanlar."""
    score = 0
    pos_hits = 0
    neg_hits = 0
    matched = []  # (başlık, yön) — kullanıcıya örnek göstermek için

    for title in headlines:
        low = title.lower()
        # Hisse kodunu metinden çıkar ki kod harfleri kelimeye karışmasın
        low_clean = low.replace(ticker.lower(), " ")
        title_pos = any(w.lower() in low_clean for w in NEWS_POSITIVE_WORDS)
        title_neg = any(w.lower() in low_clean for w in NEWS_NEGATIVE_WORDS)
        if title_pos and not title_neg:
            score += 1
            pos_hits += 1
            matched.append((title, "+"))
        elif title_neg and not title_pos:
            score -= 1
            neg_hits += 1
            matched.append((title, "-"))
        # Hem pozitif hem negatif kelime varsa nötr say (kararsız başlık)

    # Etiket
    if score >= 2:
        label, emoji = "OLUMLU", "📰🟢"
    elif score <= NEWS_STRONG_NEGATIVE:
        label, emoji = "OLUMSUZ", "📰🔴"
    elif score < 0:
        label, emoji = "ZAYIF OLUMSUZ", "📰🟡"
    else:
        label, emoji = "NÖTR", "📰⚪"

    return {
        "score": score,
        "label": label,
        "emoji": emoji,
        "positive": pos_hits,
        "negative": neg_hits,
        "total_headlines": len(headlines),
        "strong_negative": score <= NEWS_STRONG_NEGATIVE,
        "examples": matched[:3],
    }


def get_news_sentiment(ticker: str) -> dict:
    """
    Bir hissenin haber duygusunu döner (canlı taramada kullanılır).
    Sonuç o gün için cache'lenir.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    for d in list(_news_cache.keys()):
        if d != today:
            del _news_cache[d]
    _news_cache.setdefault(today, {})
    if ticker in _news_cache[today]:
        return _news_cache[today][ticker]

    headlines = fetch_headlines(ticker)
    if not headlines:
        result = {
            "score": 0, "label": "HABER YOK", "emoji": "📰⚪",
            "positive": 0, "negative": 0, "total_headlines": 0,
            "strong_negative": False, "examples": [],
        }
    else:
        result = score_headlines(ticker, headlines)

    _news_cache[today][ticker] = result
    return result

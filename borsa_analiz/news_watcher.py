"""
Anlık haber bildirimi.

Önemli şirketlerde (sabit takip listesi + botun son günlerde önerdiği hisseler)
son saatlerde çıkan haberleri tarar ve SADECE önemli olanları Telegram'a atar.

Spam önleme katmanları:
  1. Önem puanı: rutin haberler (günlük teknik analiz, "en çok işlem gören" listeleri,
     genel piyasa özeti) elenir. İflas, soruşturma, birleşme, sermaye artırımı,
     büyük ihale, bilanço, analist not değişikliği gibi olaylar geçer.
  2. Tekrar yok: gönderilen her haber hafızaya yazılır, bir daha gönderilmez.
  3. Şirket başına bekleme: aynı şirket için NEWS_WATCH_COOLDOWN_HOURS içinde ikinci
     bildirim gelmez (çok kritik haberler hariç).
  4. Kontrol başına üst sınır: bir seferde en fazla NEWS_WATCH_MAX_PER_RUN şirket.

Çalıştırma: python main.py --news   (GitHub Actions'ta 20 dakikada bir)
"""

import hashlib
import html
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from config import (
    MARKET, get_profile,
    NEWS_WATCH_MIN_IMPORTANCE, NEWS_WATCH_MAX_AGE_HOURS, NEWS_WATCH_COOLDOWN_HOURS,
    NEWS_WATCH_URGENT_IMPORTANCE, NEWS_WATCH_MAX_PER_RUN, NEWS_WATCH_FLAG_DAYS,
    NEWS_WATCHLIST_BIST, NEWS_WATCHLIST_US,
)

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"news_state_{MARKET}.json")

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
}

# (kalıp, puan, etiket) — başlıkta geçen en yüksek puanlı olaylar toplanır.
# Kalıplar kelime BAŞINDAN eşleşir (Türkçe ekler için sonu açık).
_TR_EVENTS = [
    (r"konkordato|iflas|temerrüt|borç yapılandır|kayyum|haciz", 8, "Finansal sıkıntı"),
    (r"soruşturma|gözaltı|spk.{0,20}(ceza|yasak|tedbir)|işlem yasağı|rüşvet|yolsuzluk|manipülasyon", 7, "Hukuki / düzenleyici"),
    (r"birleşme|satın al(dı|ma|acak)|devral|pay devri|blok satış|hisse satışı|ortaklık yapısı", 6, "Birleşme / satın alma / pay satışı"),
    (r"bedelli|sermaye artırım|tahsisli", 6, "Sermaye artırımı"),
    (r"bedelsiz|temettü|kâr payı|kar payı|geri alım", 5, "Temettü / bedelsiz / geri alım"),
    (r"kredi not", 5, "Kredi notu"),
    (r"tahvil|borçlanma aracı|eurobond|sendikasyon|kredi anlaşması", 4, "Borçlanma"),
    (r"ihale|sözleşme imzal|anlaşma imzal|sipariş aldı|yeni sipariş|milyon dolarlık|milyar dolarlık", 5, "İhale / sözleşme"),
    (r"bilanço|net kâr|net kar|net zarar|finansal sonuç|çeyrek sonuç", 4, "Finansal sonuçlar"),
    (r"hedef fiyat|tavsiye|model portföy", 3, "Analist görüşü"),
    (r"genel müdür|ceo|yönetim kurulu başkanı|istifa|atandı", 4, "Yönetim değişikliği"),
    (r"yangın|kaza|grev|üretime ara|üretimi durdur|siber saldırı", 6, "Operasyonel olay"),
    (r"devre kesici|tavan|taban oldu", 3, "Sert fiyat hareketi"),
    (r"yatırım kararı|yeni fabrika|kapasite artır|ihracat anlaşma", 4, "Yatırım"),
]
_US_EVENTS = [
    (r"bankruptcy|chapter 11|default|going concern|restructur", 8, "Financial distress"),
    (r"sec (charges|probe|investigation)|doj|fraud|subpoena|indict|antitrust", 7, "Legal / regulatory"),
    (r"merger|to acquire|acquisition|buyout|takeover|to be acquired|spin.?off", 6, "M&A"),
    (r"stock offering|share offering|dilut|convertible", 5, "Share offering"),
    (r"guidance|outlook (cut|raise)|profit warning|preannounce", 5, "Guidance"),
    (r"earnings|quarterly results|beats estimates|misses estimates|revenue (miss|beat)", 4, "Earnings"),
    (r"dividend|buyback|repurchase", 4, "Dividend / buyback"),
    (r"upgrade|downgrade|price target|initiates coverage", 3, "Analyst action"),
    (r"ceo|cfo|steps down|resign|appoint", 4, "Management change"),
    (r"layoff|job cuts|recall|outage|cyberattack|strike", 5, "Operational event"),
    (r"fda (approv|reject)|approval|contract worth|wins contract|billion deal", 5, "Contract / approval"),
    (r"credit rating|moody|fitch|s&p (cuts|raises)", 5, "Credit rating"),
    (r"notes offering|bond sale|debt offering|refinanc", 4, "Debt"),
]
# Rutin / gürültü haberleri: bunlar tamamen elenir
_NOISE = re.compile(
    r"günlük teknik analiz|teknik analiz|destek.{0,5}direnç|en çok (yatırımcılı|işlem gören|yükselen|düşen)|"
    r"bugün (neler|ne oldu)|piyasalarda bugün|borsa güne|borsa günü|hisse yorum|canlı borsa|"
    r"stocks to watch|stock market today|top (gainers|losers)|why .{0,40} stock (is|was) (up|down)|"
    r"should you buy|is it time to buy|motley fool|zacks rank|"
    # Takasbank'ın rutin üye/müşteri "Temerrüt İşlemi" duyuruları şirketin temerrüdü DEĞİLDİR
    r"takas ve saklama|takasbank|temerrüt işlemi|"
    # Fonların 13F pozisyon bildirimleri ("X LLC acquires 8,807 shares of Apple")
    r"shares of .{0,40}(inc|corp)|stake in|position (in|lessened|trimmed|raised)|stock position",
    re.IGNORECASE,
)


def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        st = {}
    st.setdefault("seen", {})
    st.setdefault("last_sent", {})
    st.setdefault("flagged", {})
    return st


def _save_state(st: dict):
    # Eski kayıtları temizle ki dosya şişmesin
    now = datetime.now()
    st["seen"] = {k: v for k, v in st["seen"].items() if now - datetime.fromisoformat(v) < timedelta(days=4)}
    st["flagged"] = {k: v for k, v in st["flagged"].items()
                     if now - datetime.fromisoformat(v["date"]) < timedelta(days=NEWS_WATCH_FLAG_DAYS)}
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception as e:
        logger.warning(f"Haber hafızası yazılamadı: {e}")


def flag_tickers(items: list[tuple[str, str]]):
    """Taramada öne çıkan hisseleri haber takibine ekler: [(kod, şirket adı)]."""
    if not items:
        return
    st = _load_state()
    for ticker, name in items:
        st["flagged"][ticker] = {"name": name, "date": datetime.now().isoformat(timespec="seconds")}
    _save_state(st)


def _name_key(name: str) -> str:
    """'Türk Hava Yollari Anonim Ortakligi' → 'türk hava' (haberde aranacak kısım)."""
    stop = {"inc", "inc.", "corp", "corporation", "anonim", "a.s.", "a.ş.", "ve", "sanayi", "ticaret",
            "holding", "the", "company", "co", "plc", "ltd", "group", "sirketi", "şirketi", "ortakligi"}
    words = [w for w in re.split(r"[\s,]+", name.lower()) if w and w not in stop]
    return " ".join(words[:2])


def watch_list(market: str | None = None) -> dict[str, str]:
    prof = get_profile(market)
    base = dict(NEWS_WATCHLIST_US if prof["is_us"] else NEWS_WATCHLIST_BIST)
    for t, v in _load_state()["flagged"].items():
        base.setdefault(t, _name_key(v.get("name") or t))
    return base


def importance(title: str, market: str | None = None) -> tuple[int, list[str]]:
    """Başlığın önem puanı ve olay etiketleri."""
    events = _US_EVENTS if get_profile(market)["is_us"] else _TR_EVENTS
    low = title.lower()
    score, tags = 0, []
    for pat, pts, tag in events:
        if re.search(r"(?<!\w)(" + pat + ")", low):
            score = max(score, pts) + (1 if score else 0)   # birden fazla olay → biraz daha önemli
            tags.append(tag)
    if _NOISE.search(title):
        return 0, []            # rutin/gürültü haber: tamamen elenir
    return score, tags


def _mentions(title: str, ticker: str, name: str, is_us: bool) -> bool:
    low = title.lower()
    if re.search(r"(?<![\w])" + re.escape(ticker.lower()) + r"(?![\w])", low):
        return True
    if not name:
        return False
    tail = r"(?!\w)" if is_us else ""        # Türkçe ekler için sonu açık: "aselsan'ın"
    return re.search(r"(?<!\w)" + re.escape(name) + tail, low) is not None


def fetch_recent(ticker: str, name: str, market: str | None = None) -> list[dict]:
    """Şirkete ait son NEWS_WATCH_MAX_AGE_HOURS saatteki haberleri döner."""
    prof = get_profile(market)
    query = f"{ticker} stock when:1d" if prof["is_us"] else f"{ticker} when:1d"
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&{prof['news_locale']}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
    except Exception as e:
        logger.debug(f"{ticker} haber alınamadı: {e}")
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_WATCH_MAX_AGE_HOURS)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            continue
        if pub < cutoff:
            continue
        body, _, source = title.rpartition(" - ") if " - " in title else (title, "", "")
        if not _mentions(body, ticker, name, prof["is_us"]):
            continue
        out.append({"title": body, "source": source, "link": it.findtext("link") or "", "pub": pub})
    return out


def _key(title: str) -> str:
    norm = re.sub(r"\W+", " ", title.lower()).strip()
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


def check_news(market: str | None = None, send=None) -> int:
    """Takip listesindeki şirketlerin haberlerini kontrol eder, önemlileri gönderir. Gönderilen bildirim sayısını döner."""
    from news_analyzer import score_headlines
    if send is None:
        from telegram_notifier import send_message as send
    prof = get_profile(market)
    st = _load_state()
    now = datetime.now()
    candidates = []

    for ticker, name in watch_list(market).items():
        important = []
        for n in fetch_recent(ticker, name, market):
            k = _key(n["title"])
            if k in st["seen"]:
                continue
            imp, tags = importance(n["title"], market)
            if imp >= NEWS_WATCH_MIN_IMPORTANCE:
                important.append({**n, "key": k, "imp": imp, "tags": tags})
        if not important:
            continue
        important.sort(key=lambda x: x["imp"], reverse=True)
        top = important[0]["imp"]
        last = st["last_sent"].get(ticker)
        if last and now - datetime.fromisoformat(last) < timedelta(hours=NEWS_WATCH_COOLDOWN_HOURS) \
                and top < NEWS_WATCH_URGENT_IMPORTANCE:
            logger.info(f"{ticker}: önemli haber var ama bekleme süresinde, atlandı.")
            continue
        candidates.append((top, ticker, name, important[:3]))

    candidates.sort(key=lambda c: c[0], reverse=True)
    sent = 0
    for top, ticker, name, items in candidates[:NEWS_WATCH_MAX_PER_RUN]:
        senti = score_headlines(ticker, [i["title"] for i in items], market=market)
        flag = "🚨" if top >= NEWS_WATCH_URGENT_IMPORTANCE else "📰"
        lines = [f"{flag} <b>[{prof['label']}] ÖNEMLİ HABER: {ticker}</b>",
                 f"Haber havası: {senti['emoji']} {senti['label']}", ""]
        for i in items:
            local = i["pub"].astimezone().strftime("%H:%M")
            lines.append(f"• <b>{html.escape(', '.join(i['tags']), quote=False)}</b> — "
                         f"{html.escape(i['title'], quote=False)}")
            lines.append(f"  <i>{html.escape(i['source'], quote=False)}, {local}</i> · "
                         f"<a href=\"{html.escape(i['link'])}\">habere git</a>")
        lines += ["", f"🔎 Güncel analiz için bota <code>{ticker}</code> yaz."]
        if send("\n".join(lines)):
            sent += 1
            st["last_sent"][ticker] = now.isoformat(timespec="seconds")
            for i in items:
                st["seen"][i["key"]] = now.isoformat(timespec="seconds")
            logger.info(f"{ticker}: {len(items)} önemli haber bildirildi (önem {top}).")

    _save_state(st)
    logger.info(f"Haber kontrolü bitti: {len(candidates)} şirkette önemli haber, {sent} bildirim gönderildi.")
    return sent

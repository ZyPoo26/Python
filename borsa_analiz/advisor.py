"""
Karar motoru ("yol gösterici").

Tek tek göstergeler yerine tüm bilgiyi birleştirip NET bir karar ve adım adım
bir yol haritası üretir:

  Temel analiz  → "Bu şirkete uzun vadede güvenilir mi?"  (HANGİ ŞİRKET)
  Teknik analiz → "Şu an girmek için doğru zaman mı?"      (NE ZAMAN)
  Haber         → "Bilmediğim bir risk/katalizör var mı?"
  Backtest      → "Bu hissede teknik sinyaller geçmişte işe yaradı mı?"
  Piyasa yönü   → "Genel piyasa (BIST 100 / S&P 500) rüzgârı arkamda mı?"

Kararlar (iyiden kötüye):
  AL ADAYI · TEMKİNLİ AL · SPEKÜLATİF / KISA VADE · İZLE · UZAK DUR
"""

import logging
from datetime import datetime

from analyzer import is_buy_signal
from config import (
    EXIT_MODE, ATR_TRAIL_MULT, MAX_POSITION_PCT, get_profile,
)
from scraper import download_stock_data

logger = logging.getLogger(__name__)

LEVELS = ["UZAK DUR", "İZLE", "SPEKÜLATİF / KISA VADE", "TEMKİNLİ AL", "AL ADAYI"]
EMOJI = {"UZAK DUR": "🔴", "İZLE": "👀", "SPEKÜLATİF / KISA VADE": "🟠",
         "TEMKİNLİ AL": "🟡", "AL ADAYI": "🟢"}

# Portföy riskinin işlem başına üst sınırı: stop'a takılırsan portföyün en fazla %1'i gider.
RISK_PER_TRADE_PCT = 1.0

_regime_cache: dict[str, dict] = {}


def market_regime(market: str | None = None) -> dict:
    """Genel piyasa yönü: endeks 200 günlük ortalamanın üstünde mi? (gün içi cache'li)"""
    prof = get_profile(market)
    key = f"{datetime.now():%Y-%m-%d}:{prof['market']}"
    if key in _regime_cache:
        return _regime_cache[key]
    index = "^GSPC" if prof["is_us"] else "XU100"
    name = "S&P 500" if prof["is_us"] else "BIST 100"
    res = {"name": name, "up": None, "text": f"{name} yönü alınamadı"}
    try:
        df = download_stock_data(index, period="2y", market=prof["market"])
        if df is not None and len(df) > 200:
            c = df["Close"]
            ma200 = float(c.rolling(200).mean().iloc[-1])
            last = float(c.iloc[-1])
            chg_1m = (last / float(c.iloc[-22]) - 1) * 100
            up = last > ma200
            res = {
                "name": name, "up": up,
                "text": f"{name} {'200 günlük ortalamanın ÜSTÜNDE (yükseliş trendi)' if up else '200 günlük ortalamanın ALTINDA (düşüş trendi)'}, son 1 ay %{chg_1m:+.1f}",
            }
    except Exception as e:
        logger.debug(f"Piyasa yönü alınamadı: {e}")
    _regime_cache[key] = res
    return res


def _position_size(stop_pct: float) -> float:
    """Stop mesafesine göre portföyün yüzde kaçı: risk %1 / stop mesafesi, üst sınır MAX_POSITION_PCT."""
    if stop_pct >= 0:
        return MAX_POSITION_PCT
    return round(min(MAX_POSITION_PCT, RISK_PER_TRADE_PCT / abs(stop_pct) * 100), 1)


def decide(tech: dict, fund: dict | None = None, news: dict | None = None,
           reliability: dict | None = None, regime: dict | None = None,
           market: str | None = None) -> dict:
    """Tüm analizleri birleştirip karar + gerekçe + yol haritası döner."""
    from telegram_notifier import fmt_price   # döngüsel importu önlemek için burada

    reasons: list[str] = []
    warnings: list[str] = []
    tech_buy = is_buy_signal(tech)
    fl = fund["label"] if fund else None

    # ── 1. Temel × teknik matrisi ──
    if fl == "ZAYIF":
        level = 2 if tech_buy else 0
        reasons.append(f"Şirketin temelleri zayıf (temel puan {fund['total']}/100)"
                       + (" — teknik sinyal var ama sadece kısa vadeli işlem için" if tech_buy else ""))
    elif fl == "SAĞLAM":
        if tech_buy:
            level = 4
            reasons.append(f"Sağlam şirket (temel puan {fund['total']}/100) + teknik alım sinyali")
        else:
            level = 1
            reasons.append(f"Sağlam şirket (temel puan {fund['total']}/100) ama teknik zamanlama henüz uygun değil")
    elif fl == "ORTA":
        level = 3 if tech_buy else 1
        reasons.append(f"Temeller orta düzey (temel puan {fund['total']}/100)"
                       + (" + teknik alım sinyali" if tech_buy else ", teknik sinyal yok"))
    else:
        level = 2 if tech_buy else 1
        reasons.append("Temel veri alınamadı — karar sadece teknik analize dayanıyor")

    # ── 2. Analist (aracı kurum) görüşü ──
    # Analist verisi YOKSA karar hiç etkilenmez; hisse diğer kriterlerle değerlendirilir.
    an = (fund or {}).get("analyst")
    analyst_buy = bool(an and an.get("is_buy"))
    if an:
        up_txt = f", ort. hedef %{an['upside']:+.0f}" if an.get("upside") is not None else ""
        an_txt = f"{an['count']} analist, konsensüs {an['consensus']}{up_txt}"
        if analyst_buy:
            if tech_buy and fl != "ZAYIF" and level < 4:
                level += 1
                reasons.append(f"Analistler de AL diyor ({an_txt}) → karar bir kademe güçlendi")
            elif fl == "ZAYIF":
                reasons.append(f"Analistler AL diyor ({an_txt}) ama zayıf temeller nedeniyle karar yükseltilmedi")
            else:
                reasons.append(f"Analistler AL diyor ({an_txt})"
                               + ("" if tech_buy else " — izleme listesinde öncelikli tut"))
        elif an["consensus"] == "SAT":
            level = max(0, level - 1)
            warnings.append(f"Analistlerin çoğu SAT/ZAYIF diyor ({an_txt})")
        elif an["consensus"] in ("GÜÇLÜ AL", "AL"):
            warnings.append(f"Analistler AL diyor ama fiyat ortalama hedefi zaten geçmiş ({an_txt})")
        else:
            reasons.append(f"Analistler nötr ({an_txt})")
    else:
        reasons.append("Analist kapsamı yok — değerlendirme diğer kriterlerle yapıldı")

    # ── 3. Düşürücü faktörler ──
    if news and news.get("strong_negative"):
        # Sadece alım kararlarını düşürür; İZLE'deki sağlam bir şirketi UZAK DUR'a itmez
        if level >= 2:
            level -= 1
        warnings.append("Son haberlerde olumsuzluk baskın — girmeden önce haberleri oku")
    if reliability and reliability.get("label") == "DÜŞÜK" and tech_buy:
        level = max(0, level - 1)
        warnings.append("Bu hissede teknik sinyaller geçmişte kötü çalıştı (backtest: DÜŞÜK)")
    if regime and regime.get("up") is False:
        if level >= 3:
            level -= 1
        warnings.append(f"Genel piyasa düşüş trendinde ({regime['name']}) — pozisyonu küçük tut")

    earnings_soon = None
    if fund:
        for ev in fund.get("events", []):
            if ev["type"] == "earnings" and ev["days"] <= 10:
                earnings_soon = ev
                warnings.append(f"{ev['days']} gün içinde bilanço açıklanacak — sonuç fiyatı sert oynatabilir")
        if fund["scores"]["borc"] < 35 and not fund["is_financial"]:
            warnings.append("Borç yükü riskli seviyede — faiz/kur artışında en çok zarar görenlerden olur")

    verdict = LEVELS[level]

    # ── 4. Yol haritası ──
    p = tech["price"]
    plan: list[str] = []
    stop_pct = tech["stop_pct"]
    size = _position_size(stop_pct)
    if level >= 3:
        if earnings_soon and level < 4:
            plan.append(f"Bilanço ({earnings_soon['date']:%d.%m}) sonrasını bekle; beklentiyi karşılarsa gir")
        else:
            plan.append(f"Kademeli giriş: pozisyonun yarısıyla ~{fmt_price(p, market)} civarından gir, "
                        f"kalanını MA20 ({fmt_price(tech['ma20'], market)}) yakınına geri çekilmede ekle")
        plan.append(f"Pozisyon büyüklüğü: portföyün en fazla %{size}'i "
                    f"(stop'a takılırsan kayıp portföyün ~%{RISK_PER_TRADE_PCT:.0f}'i olur)")
    elif level == 2:
        plan.append(f"Sadece kısa vadeli işlem: portföyün en fazla %{max(1.0, round(size / 2, 1))}'i, stop'a kesin uy")
    elif level == 1:
        triggers = []
        if not tech.get("trend_ok") and tech.get("ma200"):
            triggers.append(f"fiyatın 200 günlük ortalama ({fmt_price(tech['ma200'], market)}) üstüne çıkması")
        if tech["rsi"] < 40:
            triggers.append("RSI'ın 40 üstüne dönmesi (satış baskısının bitmesi)")
        triggers.append("teknik skorun 3+ olması (bot bildirecek)")
        plan.append("Alım için bekle. Takip edilecek tetikleyiciler: " + "; ".join(triggers))
    else:
        plan.append("Bu hisseye şu an girme. Temeller düzelmeden (borç/zarar) teknik sinyaller güvenilir değil")

    if level >= 2:
        if EXIT_MODE == "trailing":
            plan.append(f"İlk stop {fmt_price(tech['stop_loss'], market)} (%{stop_pct:.1f}). Fiyat yükseldikçe "
                        f"stop'u gördüğün en yüksek kapanışın {ATR_TRAIL_MULT:.0f}×ATR ({fmt_price(ATR_TRAIL_MULT * tech['atr'], market)}) altına çek")
        else:
            plan.append(f"Stop {fmt_price(tech['stop_loss'], market)}, hedef {fmt_price(tech['target'], market)}")
        plan.append(f"Tez bozulur: kapanış {fmt_price(tech['stop_loss'], market)} altına inerse ya da "
                    f"temel puan belirgin düşerse (bir sonraki bilançoda borç/marj bozulursa) çık")

    if fund:
        watch = []
        for ev in fund.get("events", []):
            watch.append(ev["text"])
        if not fund["is_financial"] and fund.get("net_debt_ebitda") is not None:
            watch.append(f"Net borç/FAVÖK şu an {fund['net_debt_ebitda']:.1f}x — 3x'i geçerse alarm")
        if watch:
            plan.append("Takvim / takip: " + " · ".join(watch))

    return {
        "verdict": verdict,
        "emoji": EMOJI[verdict],
        "level": level,
        "reasons": reasons,
        "warnings": warnings,
        "plan": plan,
        "position_pct": size,
        "analyst_buy": analyst_buy,
        "has_analyst": an is not None,
    }


def full_analysis(ticker: str, market: str | None = None, df=None,
                  with_news: bool = True, with_reliability: bool = True) -> dict | None:
    """
    Bir hisse için tüm analizleri çalıştırır ve birleştirir.
    df verilirse tekrar indirilmez (tarama sırasında zaten indirilmiş olur).
    """
    from analyzer import analyze_stock
    from backtest import get_reliability
    from config import DATA_PERIOD, NEWS_ENABLED, FUNDAMENTALS_ENABLED
    from fundamentals import get_fundamentals
    from news_analyzer import get_news_sentiment
    from scraper import last_bar_is_partial

    if df is None:
        df = download_stock_data(ticker, period=DATA_PERIOD, market=market)
    if df is None:
        return None
    tech = analyze_stock(ticker, df, partial_last=last_bar_is_partial(df, market))
    if tech is None:
        return None
    fund = get_fundamentals(ticker, market) if FUNDAMENTALS_ENABLED else None
    news = get_news_sentiment(ticker, market=market) if (with_news and NEWS_ENABLED) else None
    reliability = get_reliability(ticker, market=market) if with_reliability else None
    regime = market_regime(market)
    decision = decide(tech, fund, news, reliability, regime, market)
    return {"ticker": ticker, "market": market, "tech": tech, "fund": fund, "news": news,
            "reliability": reliability, "regime": regime, "decision": decision}

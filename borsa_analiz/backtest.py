"""
Backtest motoru.

Stratejiyi geçmiş veri üzerinde gün gün simüle eder:
  - Her gün skoru hesaplanır (canlı taramadaki aynı analyze_stock mantığı).
  - Skor >= BACKTEST_MIN_SCORE olunca o günün kapanışından "alınır".
  - Stop-loss veya hedef fiyata değene ya da süre dolana kadar tutulur.
  - Tüm işlemler kaydedilip istatistik çıkarılır.

Amaç: "Bu strateji gerçek parayla işlese kâr mı zarar mı ederdim?" sorusunu
para koymadan, sayıyla yanıtlamak. Ayrıca al-tut (buy & hold) ile kıyaslar.
"""

import logging
import pandas as pd

from config import (
    BACKTEST_PERIOD, BACKTEST_MIN_SCORE, BACKTEST_MAX_HOLD_DAYS,
    NVI_EMA_PERIOD,
)
from scraper import download_stock_data
from analyzer import analyze_stock

logger = logging.getLogger(__name__)


def backtest_stock(ticker: str, df: pd.DataFrame) -> dict | None:
    """Tek bir hisse için stratejiyi simüle eder ve işlem listesi + özet döner."""
    # Göstergelerin oturması için ilk dönemi atla (NVI EMA en uzun pencere).
    start = NVI_EMA_PERIOD + 5
    if len(df) <= start + 20:
        logger.debug(f"{ticker}: backtest için yeterli veri yok.")
        return None

    trades = []
    i = start
    n = len(df)

    while i < n - 1:
        window = df.iloc[: i + 1]
        result = analyze_stock(ticker, window)
        if result is None or result["score"] < BACKTEST_MIN_SCORE:
            i += 1
            continue

        # ── Pozisyon aç: ertesi günün açılışına en yakın, o günün kapanışından gir ──
        entry_price = result["price"]
        stop = result["stop_loss"]
        target = result["target"]
        entry_date = df.index[i]
        exit_price = None
        exit_reason = None
        exit_date = None

        # Sonraki günlerde stop/hedef kontrolü
        for j in range(i + 1, min(i + 1 + BACKTEST_MAX_HOLD_DAYS, n)):
            day_low = float(df["Low"].iloc[j])
            day_high = float(df["High"].iloc[j])
            # Konservatif: aynı gün hem stop hem hedef değerse stop önce varsayılır
            if day_low <= stop:
                exit_price = stop
                exit_reason = "STOP"
                exit_date = df.index[j]
                break
            if day_high >= target:
                exit_price = target
                exit_reason = "HEDEF"
                exit_date = df.index[j]
                break
        else:
            j = min(i + BACKTEST_MAX_HOLD_DAYS, n - 1)

        if exit_price is None:  # Süre doldu, kapanıştan çık
            exit_price = float(df["Close"].iloc[j])
            exit_reason = "SURE"
            exit_date = df.index[j]

        ret_pct = (exit_price - entry_price) / entry_price * 100
        hold_days = (exit_date - entry_date).days
        trades.append({
            "entry_date": entry_date,
            "exit_date": exit_date,
            "entry": round(entry_price, 2),
            "exit": round(exit_price, 2),
            "return_pct": round(ret_pct, 2),
            "reason": exit_reason,
            "hold_days": hold_days,
        })

        # Çıkıştan sonraki günden devam et (üst üste pozisyon açma)
        i = j + 1

    if not trades:
        return {"ticker": ticker, "trades": [], "num_trades": 0}

    returns = [t["return_pct"] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    # Bileşik getiri (her işlem bir öncekinin sonucuna uygulanır)
    equity = 1.0
    for r in returns:
        equity *= (1 + r / 100)
    total_return = (equity - 1) * 100

    # Al-tut kıyası (test başından sonuna)
    bh_start = float(df["Close"].iloc[start])
    bh_end = float(df["Close"].iloc[-1])
    buy_hold = (bh_end - bh_start) / bh_start * 100

    return {
        "ticker": ticker,
        "trades": trades,
        "num_trades": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "best": round(max(returns), 2),
        "worst": round(min(returns), 2),
        "total_return": round(total_return, 2),
        "buy_hold_return": round(buy_hold, 2),
        "beats_buy_hold": total_return > buy_hold,
    }


# Gün bazlı güvenilirlik cache'i: {tarih: {ticker: özet}}
# Aynı gün aynı hissenin backtest'i değişmez, boşuna tekrar hesaplama.
_reliability_cache: dict[str, dict[str, dict]] = {}


def get_reliability(ticker: str, market: str | None = None) -> dict:
    """
    Bir hissenin geçmiş güvenilirliğini döner (canlı taramada kullanılır).
    Sonuç o gün için cache'lenir. market=None ise aktif MARKET kullanılır.

    Döner:
      label   : "YÜKSEK" | "ORTA" | "DÜŞÜK" | "BİLİNMİYOR"
      emoji   : güvenilirliği gösteren ikon
      detail  : kısa açıklama metni
      ... (backtest ham verileri de dahil)
    """
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    # Eski günleri temizle
    for d in list(_reliability_cache.keys()):
        if d != today:
            del _reliability_cache[d]
    _reliability_cache.setdefault(today, {})
    cache_key = f"{market or ''}:{ticker}"
    if cache_key in _reliability_cache[today]:
        return _reliability_cache[today][cache_key]

    summary = {"label": "BİLİNMİYOR", "emoji": "❔", "detail": "Yeterli geçmiş veri yok"}
    try:
        df = download_stock_data(ticker, period=BACKTEST_PERIOD, market=market)
        if df is not None:
            res = backtest_stock(ticker, df)
            if res and res.get("num_trades", 0) >= 3:
                wr = res["win_rate"]
                beats = res["beats_buy_hold"]
                # Güvenilirlik kararı: al-tut'u geçti mi + başarı oranı
                if beats and wr >= 55:
                    label, emoji = "YÜKSEK", "🟢"
                elif beats or wr >= 50:
                    label, emoji = "ORTA", "🟡"
                else:
                    label, emoji = "DÜŞÜK", "🔴"
                summary = {
                    "label": label,
                    "emoji": emoji,
                    "detail": (
                        f"Son {BACKTEST_PERIOD}: {res['num_trades']} işlem, "
                        f"%{wr} isabet, strateji {'+' if res['total_return'] >= 0 else ''}%{res['total_return']} "
                        f"(al-tut {'+' if res['buy_hold_return'] >= 0 else ''}%{res['buy_hold_return']})"
                    ),
                    "win_rate": wr,
                    "total_return": res["total_return"],
                    "buy_hold_return": res["buy_hold_return"],
                    "beats_buy_hold": beats,
                    "num_trades": res["num_trades"],
                }
    except Exception as e:
        logger.debug(f"{ticker} güvenilirlik hesabı hatası: {e}")

    _reliability_cache[today][cache_key] = summary
    return summary


def print_report(res: dict):
    """Backtest sonucunu konsola okunaklı yazar."""
    if not res or res.get("num_trades", 0) == 0:
        print(f"\n{res['ticker'] if res else '?'}: Hiç işlem üretilmedi (sinyal çıkmamış).")
        return

    t = res
    print("\n" + "═" * 50)
    print(f"  BACKTEST: {t['ticker']}  ({BACKTEST_PERIOD}, min skor {BACKTEST_MIN_SCORE})")
    print("═" * 50)
    print(f"  Toplam işlem    : {t['num_trades']}")
    print(f"  Kazanan         : {t['win_count']} (%{t['win_rate']})")
    print(f"  Kaybeden        : {t['loss_count']}")
    print(f"  Ort. kazanç     : +%{t['avg_win']}")
    print(f"  Ort. kayıp      : %{t['avg_loss']}")
    print(f"  En iyi / en kötü: +%{t['best']} / %{t['worst']}")
    print("  " + "-" * 46)
    print(f"  STRATEJİ getiri : {'+' if t['total_return'] >= 0 else ''}%{t['total_return']}")
    print(f"  Al-tut getiri   : {'+' if t['buy_hold_return'] >= 0 else ''}%{t['buy_hold_return']}")
    verdict = "✅ Stratejı al-tut'u GEÇTİ" if t["beats_buy_hold"] else "❌ Al-tut daha iyiydi"
    print(f"  Sonuç           : {verdict}")
    print("═" * 50)


def run_backtest(tickers: list[str]):
    """Verilen hisseler için backtest çalıştırır ve toplu özet basar."""
    all_results = []
    for ticker in tickers:
        logger.info(f"{ticker} backtest için indiriliyor...")
        df = download_stock_data(ticker, period=BACKTEST_PERIOD)
        if df is None:
            print(f"{ticker}: veri indirilemedi, atlandı.")
            continue
        res = backtest_stock(ticker, df)
        if res:
            print_report(res)
            if res.get("num_trades", 0) > 0:
                all_results.append(res)

    # ── Toplu özet ──
    if all_results:
        total_trades = sum(r["num_trades"] for r in all_results)
        total_wins = sum(r["win_count"] for r in all_results)
        avg_strategy = sum(r["total_return"] for r in all_results) / len(all_results)
        avg_bh = sum(r["buy_hold_return"] for r in all_results) / len(all_results)
        beats = sum(1 for r in all_results if r["beats_buy_hold"])
        print("\n" + "█" * 50)
        print("  GENEL ÖZET (tüm hisseler)")
        print("█" * 50)
        print(f"  Test edilen hisse  : {len(all_results)}")
        print(f"  Toplam işlem       : {total_trades}")
        print(f"  Genel başarı oranı : %{round(total_wins / total_trades * 100, 1) if total_trades else 0}")
        print(f"  Ort. strateji getiri: {'+' if avg_strategy >= 0 else ''}%{round(avg_strategy, 2)}")
        print(f"  Ort. al-tut getiri  : {'+' if avg_bh >= 0 else ''}%{round(avg_bh, 2)}")
        print(f"  Al-tut'u geçen      : {beats}/{len(all_results)} hisse")
        print("█" * 50)
        print("\n⚠️  Geçmiş performans geleceğin garantisi değildir.")
        print("    Bu sonuçlar stratejinin geçmişteki davranışını gösterir.\n")
